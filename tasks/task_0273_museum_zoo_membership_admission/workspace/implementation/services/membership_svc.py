"""Membership lifecycle: activation, renewal (early/lapsed), grace, expiry, cancel.

State machine (scaffold §1.2): PENDING_PAYMENT -> ACTIVE -> {GRACE -> ACTIVE,
GRACE -> EXPIRED} ; any of {PENDING_PAYMENT, ACTIVE, GRACE} -> CANCELLED.
"""
import clock
import db
from errors import invalid_state, ApiError, ERR_STALE_VERSION
from timeutil import add_days, format_iso, parse_iso
from services import order_svc

GRACE_DAYS = 30


def _plan(membership):
    return db.membership_plans[membership["plan_id"]]


def _renewal_fee(plan, variant):
    """renewal_fee calc (scaffold §1.3). variant in {initial, early, lapsed}."""
    base = plan["annual_fee_cents"]
    if variant == "lapsed":
        return base + plan.get("reinstatement_fee_cents", 0)
    # initial and early are both the plain annual fee, no proration.
    return base


def _mint_guest_passes(membership):
    """Mint plan.guest_passes_granted fresh UNUSED GuestPass rows."""
    plan = _plan(membership)
    for _ in range(plan["guest_passes_granted"]):
        gp = {
            "membership_id": membership["id"],
            "status": "UNUSED",
            "reserved_order_id": None,
        }
        db.stamp_create(gp)
        db.guest_passes[gp["id"]] = gp


def _membership_guest_passes(membership_id):
    return [g for g in db.guest_passes.values() if g["membership_id"] == membership_id]


# ---------------------------------------------------------------------------
# Activation (PENDING_PAYMENT -> ACTIVE) via payment settle
# ---------------------------------------------------------------------------

def activate(membership):
    if membership["status"] != "PENDING_PAYMENT":
        raise invalid_state("Membership is not PENDING_PAYMENT")
    plan = _plan(membership)
    started = clock.now()
    membership["status"] = "ACTIVE"
    membership["started_at"] = format_iso(started)
    membership["expires_at"] = format_iso(add_days(started, plan["term_days"]))
    membership["grace_until"] = None
    membership["term_count"] = 1
    membership["last_paid_fee_cents"] = _renewal_fee(plan, "initial")
    db.touch(membership)
    _mint_guest_passes(membership)
    # Record a pending donation, if one was attached at creation.
    pending = membership.pop("_pending_donation_cents", 0)
    if pending and pending > 0:
        _create_membership_donation(membership, pending)
    return membership


def _create_membership_donation(membership, amount_cents):
    don = {
        "order_id": None,
        "membership_id": membership["id"],
        "amount_cents": amount_cents,
    }
    don["id"] = db.new_id()
    don["created_at"] = db.now_iso()
    don["_seq"] = db.next_seq()
    db.donations[don["id"]] = don
    return don


# ---------------------------------------------------------------------------
# Renewal — manual (early/lapsed) with OCC, and auto (early) via job
# ---------------------------------------------------------------------------

def renew_manual(membership, expected_version, donation_cents):
    """Patron/BoxOffice renew. Validates state, then OCC, then applies.

    Priority order (scaffold §1.4): state (priority 7) before OCC (priority 8).
    """
    status = membership["status"]
    if status not in ("ACTIVE", "GRACE"):
        raise invalid_state("Membership is not in a renewable state")
    # GRACE renewal must be within the grace window; past grace_until is an
    # undefined transition for that state -> ERR_INVALID_STATE (PRD §3.3).
    if status == "GRACE":
        grace_until = parse_iso(membership["grace_until"])
        if clock.now() > grace_until:
            raise invalid_state("Grace window has elapsed")
    # OCC check after state validity.
    if expected_version != membership["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_membership_version is stale")

    if status == "ACTIVE":
        _apply_early_renewal(membership)
    else:  # GRACE
        _apply_lapsed_renewal(membership)

    if donation_cents and donation_cents > 0:
        _create_membership_donation(membership, donation_cents)
    return membership


def _apply_early_renewal(membership):
    plan = _plan(membership)
    # Term extends from the prior expires_at (stacking), not from clock.now.
    prior_expiry = parse_iso(membership["expires_at"])
    membership["expires_at"] = format_iso(add_days(prior_expiry, plan["term_days"]))
    membership["status"] = "ACTIVE"
    membership["grace_until"] = None
    membership["last_paid_fee_cents"] = _renewal_fee(plan, "early")
    membership["term_count"] = membership.get("term_count", 1) + 1
    db.touch(membership)
    _mint_guest_passes(membership)


def _apply_lapsed_renewal(membership):
    plan = _plan(membership)
    started = clock.now()
    membership["status"] = "ACTIVE"
    membership["started_at"] = format_iso(started)
    membership["expires_at"] = format_iso(add_days(started, plan["term_days"]))
    membership["grace_until"] = None
    membership["last_paid_fee_cents"] = _renewal_fee(plan, "lapsed")
    membership["term_count"] = membership.get("term_count", 1) + 1
    db.touch(membership)
    _mint_guest_passes(membership)


def auto_renew_one(membership):
    """Auto-renew job applies the early variant; advances version (OCC writer)."""
    _apply_early_renewal(membership)


# ---------------------------------------------------------------------------
# Expiry job transitions
# ---------------------------------------------------------------------------

def to_grace(membership):
    """ACTIVE -> GRACE. Expire UNUSED passes."""
    plan = _plan(membership)
    expires = parse_iso(membership["expires_at"])
    membership["status"] = "GRACE"
    membership["grace_until"] = format_iso(add_days(expires, GRACE_DAYS))
    db.touch(membership)
    for gp in _membership_guest_passes(membership["id"]):
        if gp["status"] == "UNUSED":
            gp["status"] = "EXPIRED"
            db.touch(gp)


def to_expired(membership):
    """GRACE -> EXPIRED. Expire remaining UNUSED/RESERVED passes."""
    membership["status"] = "EXPIRED"
    db.touch(membership)
    for gp in _membership_guest_passes(membership["id"]):
        if gp["status"] in ("UNUSED", "RESERVED"):
            gp["status"] = "EXPIRED"
            db.touch(gp)


# ---------------------------------------------------------------------------
# Cancellation (deepest cascade, depth 3)
# ---------------------------------------------------------------------------

def cancel(membership):
    if membership["status"] not in ("PENDING_PAYMENT", "ACTIVE", "GRACE"):
        raise invalid_state("Membership is not cancellable")
    membership["status"] = "CANCELLED"
    membership["auto_renew"] = False
    db.touch(membership)
    # Process RESERVED passes first: release -> UNUSED -> EXPIRED, voiding the
    # linked ticket and giving back held capacity (cascade depth 3).
    for gp in _membership_guest_passes(membership["id"]):
        if gp["status"] == "RESERVED":
            order_svc.release_guest_pass_on_membership_cancel(gp)
            gp["status"] = "EXPIRED"
            db.touch(gp)
    # Then UNUSED passes expire directly.
    for gp in _membership_guest_passes(membership["id"]):
        if gp["status"] == "UNUSED":
            gp["status"] = "EXPIRED"
            db.touch(gp)
    return membership
