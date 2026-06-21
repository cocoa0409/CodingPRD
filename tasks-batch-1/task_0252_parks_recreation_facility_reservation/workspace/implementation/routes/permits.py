"""Permit endpoints: apply, grant, deny, cancel, complete, no-show, preview.

The grant guard chain follows the priority order pinned in PRD §3.5:
  auth -> role -> existence -> state -> OCC -> BARRED -> double-booking
  -> (GRANTED branch only) PROBATION-prime -> COI -> payment.
"""
from flask import Blueprint, request

import errors
import serializers
from clock import now as clock_now
from db import db, stamp_create, touch
from helpers import parse_body, require_fields, require_enum, parse_dt, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success
from services import calculations as calc
from services import domain
from routes.facilities import get_facility_or_404

bp = Blueprint("permits", __name__)


def get_permit_or_404(permit_id):
    p = db.permits.get(permit_id)
    if p is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Permit not found")
    return p


def _scoped_permit(facility_id, permit_id):
    """Validate facility then permit (left-to-right) and that the permit belongs
    to the facility in the path."""
    facility = get_facility_or_404(facility_id)
    permit = db.permits.get(permit_id)
    if permit is None or permit["facility_id"] != facility_id:
        raise errors.err(errors.ERR_NOT_FOUND, "Permit not found")
    return facility, permit


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
@bp.post("/facilities/<facility_id>/permits")
def apply_permit(facility_id):
    user_id, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    facility = get_facility_or_404(facility_id)
    body = parse_body()
    require_fields(body, ["patron_id", "start_at", "end_at"])

    patron = db.patrons.get(body["patron_id"])
    if patron is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Patron not found")

    coi_id = body.get("coi_id")
    if coi_id is not None:
        if db.insurance_certificates.get(coi_id) is None:
            raise errors.err(errors.ERR_NOT_FOUND, "Insurance certificate not found")

    # Patron acting on own application only.
    if role == "Patron" and body["patron_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Patron may only apply for themselves")

    # BARRED standing cannot apply (PRD §3.3).
    if patron["standing"] == "BARRED":
        raise errors.err(errors.ERR_PATRON_BARRED, "BARRED patron cannot apply")

    start_at = parse_dt(body["start_at"], "start_at")
    end_at = parse_dt(body["end_at"], "end_at")
    now = clock_now()
    if not (start_at < end_at) or start_at <= now or end_at <= now:
        raise errors.err(errors.ERR_INVALID_WINDOW,
                         "Window must have start_at < end_at and both in the future")

    is_prime, tier, quoted = domain.compute_apply_pricing(facility, patron, start_at, end_at)

    rec = {
        "facility_id": facility_id,
        "patron_id": body["patron_id"],
        "coi_id": coi_id,
        "league_id": None,
        "lottery_round_id": None,
        "start_at": start_at,
        "end_at": end_at,
        "is_prime_requested": is_prime,
        "status": "APPLIED",
        "pricing_residency": tier,
        "quoted_fee_cents": quoted,
        "final_fee_cents": None,
        "deposit_held_cents": 0,
        "refunded_cents": 0,
        "cancelled_lead_hours": None,
    }
    stamp_create(rec)
    db.permits[rec["id"]] = rec
    return success(serializers.permit(rec), status=201)


@bp.get("/permits/<permit_id>")
def get_permit(permit_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    p = get_permit_or_404(permit_id)
    return success(serializers.permit(p))


@bp.get("/permits/<permit_id>/refund-preview")
def refund_preview(permit_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    p = get_permit_or_404(permit_id)
    now = clock_now()
    lead = calc.lead_hours(p["start_at"], now)
    fee_refund, deposit_refund, total = calc.cancellation_refund(
        p["final_fee_cents"] or 0, p["deposit_held_cents"], lead
    )
    payment = domain._captured_payment_for(p["id"])
    preview = {
        "permit_id": p["id"],
        "payment_id": payment["id"] if payment else None,
        "refund_destination": "ORIGINAL",
        "fee_refund_cents": fee_refund,
        "deposit_refund_cents": deposit_refund,
        "total_refund_cents": total,
        # non-persisted shape; carry common fields as empty/derived placeholders
        "id": None,
        "created_at": now,
        "updated_at": now,
        "version": 0,
    }
    return success(serializers.refund(preview))


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------
@bp.post("/facilities/<facility_id>/permits/<permit_id>/grant")
def grant_permit(facility_id, permit_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    facility, permit = _scoped_permit(facility_id, permit_id)
    body = parse_body()

    # State: grant defined only from APPLIED or WAITLISTED.
    if permit["status"] not in ("APPLIED", "WAITLISTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Permit not in a grantable state")

    # OCC: expected_facility_version mandatory and must match.
    require_fields(body, ["expected_facility_version"])
    expected = body["expected_facility_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err(errors.ERR_VALIDATION, "expected_facility_version must be an integer")
    if expected != facility["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_facility_version does not match")

    patron = db.patrons[permit["patron_id"]]
    # BARRED cannot be granted.
    if patron["standing"] == "BARRED":
        raise errors.err(errors.ERR_PATRON_BARRED, "BARRED patron cannot be granted")

    on_conflict = body.get("on_conflict")
    conflict = domain.has_buffer_conflict(facility, permit)

    # Double-booking branch (priority 11).
    if conflict:
        if on_conflict == "WAITLIST":
            # Short-circuit to WAITLISTED; skip COI/payment gates.
            permit["status"] = "WAITLISTED"
            touch(permit)
            if permit.get("league_id"):
                domain.recompute_league(permit["league_id"])
            return success(serializers.permit(permit))
        raise errors.err(errors.ERR_DOUBLE_BOOKING, "Grant collides with a GRANTED permit")

    # ---- Outcome would be GRANTED: remaining gates ----
    # Facility must be OPEN to accept a grant into GRANTED.
    if facility["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Facility is not OPEN")

    # PROBATION prime block.
    if patron["standing"] == "PROBATION" and permit["is_prime_requested"]:
        raise errors.err(errors.ERR_PROBATION_PRIME_BLOCKED,
                         "PROBATION patron cannot be granted a prime-window permit")

    # COI gate.
    domain.check_coi_for_grant(facility, permit)

    # Final fee (chronological) then payment gate.
    final_fee = domain.compute_final_fee(facility, patron, permit["start_at"], permit["end_at"])
    domain.check_payment_for_grant(facility, permit, final_fee)

    # ---- Commit grant side effects ----
    was_waitlisted = permit["status"] == "WAITLISTED"
    permit["final_fee_cents"] = final_fee
    permit["deposit_held_cents"] = facility["deposit_cents"]
    permit["status"] = "GRANTED"
    touch(permit)
    domain.facility_grant_inc(facility)

    if permit.get("league_id"):
        domain.recompute_league(permit["league_id"])

    return success(serializers.permit(permit))


# ---------------------------------------------------------------------------
# Deny
# ---------------------------------------------------------------------------
@bp.post("/facilities/<facility_id>/permits/<permit_id>/deny")
def deny_permit(facility_id, permit_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    facility, permit = _scoped_permit(facility_id, permit_id)
    if permit["status"] != "APPLIED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an APPLIED permit can be denied")

    # VOID any captured payment (full reverse, no fee).
    for pay in db.payments.values():
        if pay["permit_id"] == permit["id"] and pay["status"] == "CAPTURED":
            pay["status"] = "VOIDED"
            touch(pay)

    permit["status"] = "DENIED"
    touch(permit)
    if permit.get("league_id"):
        domain.recompute_league(permit["league_id"])
    return success(serializers.permit(permit))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/facilities/<facility_id>/permits/<permit_id>/cancel")
def cancel_permit_route(facility_id, permit_id):
    user_id, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    facility, permit = _scoped_permit(facility_id, permit_id)

    if role == "Patron" and permit["patron_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Patron may only cancel their own permit")

    if permit["status"] not in ("APPLIED", "GRANTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Permit not in a cancellable state")

    # Temporal guard applies to a started/past reservation.
    if clock_now() >= permit["start_at"]:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Cannot cancel a reservation whose start time has passed")

    body = parse_body()
    refund_destination = body.get("refund_destination")
    if refund_destination is not None and refund_destination not in ("ORIGINAL", "CREDIT"):
        raise errors.err(errors.ERR_VALIDATION, "refund_destination must be ORIGINAL or CREDIT")

    domain.cancel_permit(permit, refund_destination)
    return success(serializers.permit(permit))


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------
@bp.post("/facilities/<facility_id>/permits/<permit_id>/complete")
def complete_permit(facility_id, permit_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    facility, permit = _scoped_permit(facility_id, permit_id)
    if permit["status"] != "GRANTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a GRANTED permit can be completed")
    if clock_now() < permit["end_at"]:
        raise errors.err(errors.ERR_INVALID_STATE, "Cannot complete before end_at")

    # Release deposit in full.
    domain.create_refund(permit, 0, permit["deposit_held_cents"], "ORIGINAL")
    permit["refunded_cents"] = permit["deposit_held_cents"]
    permit["status"] = "COMPLETED"
    touch(permit)
    domain.facility_grant_dec(facility)
    if permit.get("league_id"):
        domain.recompute_league(permit["league_id"])
    return success(serializers.permit(permit))


# ---------------------------------------------------------------------------
# No-show
# ---------------------------------------------------------------------------
@bp.post("/facilities/<facility_id>/permits/<permit_id>/no-show")
def no_show_permit(facility_id, permit_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    facility, permit = _scoped_permit(facility_id, permit_id)
    if permit["status"] != "GRANTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a GRANTED permit can be marked no-show")
    if clock_now() < permit["end_at"]:
        raise errors.err(errors.ERR_INVALID_STATE, "Cannot mark no-show before end_at")

    # Forfeit deposit entirely (no refund created).
    permit["status"] = "NO_SHOW"
    touch(permit)

    patron = db.patrons[permit["patron_id"]]
    patron["no_show_strikes"] += 1
    patron["standing"] = calc.patron_standing(patron["no_show_strikes"])
    touch(patron)

    domain.facility_grant_dec(facility)
    if permit.get("league_id"):
        domain.recompute_league(permit["league_id"])
    return success(serializers.permit(permit))


# ---------------------------------------------------------------------------
# Global permit list (reverse-reachability)
# ---------------------------------------------------------------------------
@bp.get("/permits")
def list_permits():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    items = list(db.permits.values())
    for key in ("coi_id", "lottery_round_id", "facility_id", "patron_id", "league_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.permit(p) for p in page], pagination=meta)
