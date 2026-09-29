"""Derived move state: consent linkage, the consent gate, readiness scoring
(calculation 2), mapped order counts and the SCHEDULING -> IN_SERVICE bubble-up.
"""

from datetime import timedelta
from decimal import Decimal

import db
from services import enums
from services.lookup import (
    filings_of_move,
    orders_of_move,
    verifications_of_move,
)

# Fields whose mutation makes the move row dirty (version + updated_at bump).
TRACKED_MOVE_FIELDS = (
    "duplicate_of_move_id",
    "reactivation_candidate_move_id",
    "move_date",
    "external_reference",
    "lifecycle_status",
    "duplicate_flag",
    "duplicate_match_score",
    "duplicate_candidate_move_id",
    "consent_gate",
    "blocked_reason",
    "readiness_score",
    "verified_at",
    "identity_attempt_count",
    "mapped_order_count",
    "unmapped_utility_types",
    "cancellation_reason",
)


def snapshot(move):
    return {k: move.get(k) for k in TRACKED_MOVE_FIELDS}


def commit(move, snap, force=False):
    """Bump version/updated_at when the move row actually changed."""
    if force or any(move.get(k) != snap.get(k) for k in TRACKED_MOVE_FIELDS):
        db.touch(move)
        return True
    return False


# ------------------------------------------------------------------- consents
def linked_consents(move, scope=None):
    """Consent records that govern this move: resident-wide or move-scoped."""
    out = []
    for c in db.db.consents.values():
        if c["resident_id"] != move["resident_id"]:
            continue
        if c["move_id"] is not None and c["move_id"] != move["id"]:
            continue
        if scope is not None and c["scope"] != scope:
            continue
        out.append(c)
    return sorted(out, key=db.order_key)


def granted_consent(move, scope):
    for c in linked_consents(move, scope):
        if c["state"] == "GRANTED":
            return c
    return None


def has_consent(move, scope):
    return granted_consent(move, scope) is not None


def scope_blocked(move, scope):
    """A gate scope blocks when its consent was revoked or expired and no fresh
    grant has replaced it."""
    records = linked_consents(move, scope)
    if any(c["state"] == "GRANTED" for c in records):
        return False
    return any(c["state"] in enums.CONSENT_BLOCKING for c in records)


def compute_gate(move):
    for scope in enums.GATE_SCOPES:
        if scope_blocked(move, scope):
            return "BLOCKED"
    return "OPEN"


# ------------------------------------------------------------------- identity
def latest_verification(move_id):
    rows = verifications_of_move(move_id)
    return rows[-1] if rows else None


def identity_valid_until(move):
    verified_at = db.parse_ts(move.get("verified_at"))
    if verified_at is None:
        return None
    return verified_at + timedelta(days=enums.IDENTITY_VALIDITY_DAYS)


def identity_is_current(move):
    limit = identity_valid_until(move)
    if limit is None:
        return False
    return db.now() <= limit


# ------------------------------------------------- calculation 2: readiness
def identity_component(move):
    latest = latest_verification(move["id"])
    if latest is not None and latest["status"] == "PASSED" and identity_is_current(move):
        return Decimal("100")
    if latest is not None and latest["status"] == "PENDING":
        return Decimal("50")
    return Decimal("0")


def utility_component(move):
    orders = orders_of_move(move["id"])
    mapped = [o for o in orders if o["provision_status"] != "CANCELLED"]
    if not mapped:
        return Decimal("0")
    done = [o for o in mapped if o["provision_status"] in enums.ORDER_DONE_PROVISION]
    return db.round_money(Decimal(100) * Decimal(len(done)) / Decimal(len(mapped)), 0)


def filing_component(move):
    rows = [f for f in filings_of_move(move["id"]) if f["status"] != "CANCELLED"]
    if not rows:
        return Decimal("0")
    newest = rows[-1]
    if newest["status"] == "CONFIRMED":
        return Decimal("100")
    if newest["status"] == "SUBMITTED":
        return Decimal("60")
    return Decimal("0")


def consent_component(move):
    if move["consent_gate"] == "BLOCKED":
        return Decimal("0")
    granted = sum(1 for scope in enums.GATE_SCOPES if has_consent(move, scope))
    if granted == 2:
        return Decimal("100")
    if granted == 1:
        return Decimal("50")
    return Decimal("0")


def readiness_variant_for(move):
    if move["lifecycle_status"] in enums.PRE_VERIFICATION_LIFECYCLE:
        return "pre_verification"
    return "post_verification"


def readiness_breakdown(move, variant=None):
    variant = variant or readiness_variant_for(move)
    identity = identity_component(move)
    utility = utility_component(move)
    filing = filing_component(move)
    consent = consent_component(move)
    if variant == "pre_verification":
        weighted = (
            enums.READINESS_WEIGHT_UTILITY * utility
            + enums.READINESS_WEIGHT_FILING * filing
            + enums.READINESS_WEIGHT_CONSENT * consent
        )
        total = weighted / (
            enums.READINESS_WEIGHT_UTILITY
            + enums.READINESS_WEIGHT_FILING
            + enums.READINESS_WEIGHT_CONSENT
        )
    else:
        total = (
            enums.READINESS_WEIGHT_IDENTITY * identity
            + enums.READINESS_WEIGHT_UTILITY * utility
            + enums.READINESS_WEIGHT_FILING * filing
            + enums.READINESS_WEIGHT_CONSENT * consent
        )
    score = int(db.round_money(total, 0))
    score = max(0, min(100, score))
    return {
        "variant": variant,
        "identity_component": int(identity),
        "utility_component": int(utility),
        "filing_component": int(filing),
        "consent_component": int(consent),
        "readiness_score": score,
    }


def readiness_score(move, variant=None):
    return readiness_breakdown(move, variant)["readiness_score"]


# ----------------------------------------------------------- derived counters
def mapped_order_count(move_id):
    """Every service order of the move, regardless of the state it is in."""
    return len(orders_of_move(move_id))


def recompute(move):
    """Refresh every computed field the move carries.  Does not bump version;
    callers pair this with snapshot()/commit()."""
    move["consent_gate"] = compute_gate(move)
    move["mapped_order_count"] = mapped_order_count(move["id"])
    move["readiness_score"] = readiness_score(move)
    return move


def refresh(move, force=False):
    snap = snapshot(move)
    recompute(move)
    return commit(move, snap, force=force)


# ------------------------------------------------- bubble-up to IN_SERVICE
def try_bubble_up(move):
    """SCHEDULING -> IN_SERVICE once every child has settled."""
    if move["lifecycle_status"] != "SCHEDULING":
        return False
    orders = orders_of_move(move["id"])
    if mapped_order_count(move["id"]) < 1:
        return False
    if not orders:
        return False
    if not all(o["provision_status"] in enums.ORDER_SETTLED_PROVISION for o in orders):
        return False
    if not any(o["provision_status"] == "ACTIVE_SERVICE" for o in orders):
        return False
    confirmed = [f for f in filings_of_move(move["id"]) if f["status"] == "CONFIRMED"]
    if len(confirmed) != 1:
        return False
    move["lifecycle_status"] = "IN_SERVICE"
    return True


def park_attention(move, reason):
    """Park a live move in ATTENTION_REQUIRED with the supplied blocked_reason."""
    if move["lifecycle_status"] in ("SCHEDULING", "IN_SERVICE"):
        move["lifecycle_status"] = "ATTENTION_REQUIRED"
        move["blocked_reason"] = reason
        return True
    if move["lifecycle_status"] == "ATTENTION_REQUIRED":
        move["blocked_reason"] = reason
        return True
    return False
