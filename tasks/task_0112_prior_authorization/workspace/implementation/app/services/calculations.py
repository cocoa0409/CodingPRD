"""Business calculations — SCAFFOLD §1.3, PRD §3.6/3.7/3.10.

All numeric scores use Decimal with ROUND_HALF_UP per PRD §2.9.
All datetime extensions are exact wall-clock durations expressed at millisecond
precision in ISO 8601 UTC.
"""
from decimal import Decimal, ROUND_HALF_UP

from ..clock import add_hours
from ..store import get_store


# --- helpers -----------------------------------------------------------------


def _q2(value) -> float:
    """Round to two decimal places half-up and return as a float for JSON-friendly storage."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def _clamp_unit(value: float) -> float:
    return max(0.00, min(1.00, value))


def _catalog_snapshot(auth: dict) -> dict:
    """Return the version-pinned snapshot the auth was bound to at submission.

    PRD §2.10: SLA windows, validity_days, required_evidence_categories all come
    from the snapshot pinned at submitted_at, NOT the live catalog row.

    Snapshot is stored on the auth as `_pinned_catalog`.
    """
    return auth.get("_pinned_catalog") or {}


# --- decision_deadline -------------------------------------------------------


def calc_decision_deadline(auth: dict) -> str:
    """Compute decision_deadline_at from submitted_at + base SLA + accumulated PI extensions.

    base = standard_sla_hours or expedited_sla_hours (from pinned snapshot)
    extension per cycle = 168 h (STANDARD) or 24 h (EXPEDITED)
    """
    snap = _catalog_snapshot(auth)
    urgency = auth.get("urgency", "STANDARD")
    if urgency == "EXPEDITED":
        base_hours = snap.get("expedited_sla_hours", 72)
        ext_per_cycle = 24
    else:
        base_hours = snap.get("standard_sla_hours", 336)
        ext_per_cycle = 168

    cycles = auth.get("_pending_info_cycles", 0)
    total_hours = base_hours + cycles * ext_per_cycle
    submitted_at = auth.get("submitted_at")
    if submitted_at is None:
        return None
    return add_hours(submitted_at, total_hours)


# --- appeal_decision_deadline -----------------------------------------------


APPEAL_HOURS_STANDARD = {1: 240, 2: 480, 3: 720}
APPEAL_HOURS_EXPEDITED = {1: 72, 2: 96, 3: 168}


def calc_appeal_decision_deadline(appeal: dict, auth: dict) -> str:
    """Appeal.filed_at + hours_by_tier[tier] hours, urgency-driven."""
    urgency = auth.get("urgency", "STANDARD")
    table = APPEAL_HOURS_EXPEDITED if urgency == "EXPEDITED" else APPEAL_HOURS_STANDARD
    hours = table[appeal["tier"]]
    return add_hours(appeal["filed_at"], hours)


# --- evidence_completeness ---------------------------------------------------


def calc_evidence_completeness(auth: dict) -> float:
    """Compute evidence_completeness_score per PRD §3.7.

    base = (#required categories with at least one ATTACHED evidence) / (#required)
           (or 1.00 when required is empty)
    score = round(base - reuse_discount + post_p2p_bonus, 2)
    score = clamp(score, 0.00, 1.00)
    """
    store = get_store()
    snap = _catalog_snapshot(auth)
    required = list(snap.get("required_evidence_categories") or [])

    # Index attached evidence categories under this auth.
    attached_categories = set()
    for e in store.clinical_evidence.values():
        if e["authorization_request_id"] != auth["id"]:
            continue
        if e["status"] != "ATTACHED":
            continue
        attached_categories.add(e["category"])

    if len(required) == 0:
        base = 1.00
    else:
        covered = sum(1 for c in required if c in attached_categories)
        base = covered / len(required)

    reuse_discount = auth.get("evidence_reuse_discount", 0.00) or 0.00

    # post_p2p_bonus: based on the LATEST completed P2P outcome for this auth.
    bonus = 0.00
    latest_p2p = _latest_completed_p2p(auth["id"])
    if latest_p2p is not None and latest_p2p.get("outcome") == "OVERTURNED":
        bonus = 0.10

    raw = float(base) - float(reuse_discount) + float(bonus)
    rounded = _q2(raw)
    return _clamp_unit(rounded)


def _latest_completed_p2p(authorization_request_id: str):
    """Return the most-recently-COMPLETED PeerToPeerReview for an auth, or None."""
    store = get_store()
    candidates = [
        p for p in store.peer_to_peer_reviews.values()
        if p["authorization_request_id"] == authorization_request_id
        and p["status"] == "COMPLETED"
    ]
    if not candidates:
        return None
    # 'most recent' is determined by updated_at (last mutation, which is when
    # the COMPLETED transition happened).
    candidates.sort(key=lambda p: p.get("updated_at", p.get("created_at", "")))
    return candidates[-1]


# --- evidence_reuse_discount -------------------------------------------------


def calc_evidence_reuse_discount(auth: dict) -> float:
    """Compute evidence_reuse_discount per PRD §3.7.

    - 0.00 if prior_request_id is null.
    - Otherwise: min(0.05 * reused_count, 0.20), round half-up to 2dp.
    - If pinned catalog requires no categories at all, the discount is 0.00.
    """
    if not auth.get("prior_request_id"):
        return 0.00

    store = get_store()
    prior = store.authorization_requests.get(auth["prior_request_id"])
    if prior is None:
        # Validation 4 should have caught this earlier. Defensive fallback.
        return 0.00

    snap = _catalog_snapshot(auth)
    total_required = len(snap.get("required_evidence_categories") or [])
    if total_required == 0:
        return 0.00

    reused = 0
    for e in store.clinical_evidence.values():
        if e["authorization_request_id"] != auth["id"]:
            continue
        if e["status"] != "ATTACHED":
            continue
        if e.get("sourced_from_request_id") == prior["id"]:
            reused += 1

    raw = min(0.20, 0.05 * reused)
    return _q2(raw)


# --- approval_expiration -----------------------------------------------------


def calc_approval_expiration(auth: dict) -> str:
    """expires_at = decided_at + version-pinned approval_validity_days * 24 hours.

    PRD §3.10: the appeal-overturn path uses the SAME version-pinned validity
    captured at original submission — appeals do not re-pin.
    """
    snap = _catalog_snapshot(auth)
    validity_days = snap.get("approval_validity_days", 90)
    decided_at = auth.get("decided_at")
    if decided_at is None:
        return None
    return add_hours(decided_at, validity_days * 24)


# --- recompute helper --------------------------------------------------------


def recompute_evidence_metrics(auth: dict) -> None:
    """Recompute evidence_reuse_discount and evidence_completeness_score in order.

    Per SCAFFOLD §1.3: the reuse discount is recomputed on every completeness
    recompute, so we must compute it first (since the completeness formula
    subtracts it).
    """
    auth["evidence_reuse_discount"] = calc_evidence_reuse_discount(auth)
    auth["evidence_completeness_score"] = calc_evidence_completeness(auth)
