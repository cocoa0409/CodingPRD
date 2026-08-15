"""Settlement endpoints: GET /stops/{id}/settlement (array of 0-1),
PUT /settlements/{settlement_id} — figure recording + the submit/approve/pay
custody chain with segregation of duties (PRD §2.11, §3.7)."""

from flask import Blueprint

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_SOD_SUBMIT_APPROVE, ERR_SOD_APPROVE_PAY,
                    ERR_SETTLEMENT_INVALID_STATE, ERR_SETTLEMENT_INCOMPLETE)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain, calc
from util import (get_body, reject_unknown, as_int, as_enum, paginate)

bp = Blueprint("settlements", __name__)

SETTLEMENT_STATUSES = ("DRAFT", "SUBMITTED", "DISPUTED", "APPROVED", "PAID", "VOID")
FIGURE_FIELDS = ("audited_gross_cents", "taxes_cents", "levies_cents")


@bp.route("/stops/<stop_id>/settlement", methods=["GET"])
def get_stop_settlement(stop_id):
    authenticate()
    if db.stops.get(stop_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    settlement = domain.settlement_of_stop(stop_id)
    items = [settlement] if settlement is not None else []
    data, total, limit, offset = paginate(items, lambda r: db.serialize("settlement", r))
    return success_list(data, total, limit, offset, 200)


def _recompute_waterfall(settlement, stop):
    """Pinned order: taxes then levies -> guarantee-vs-split (only rounding
    step) -> producer share (may go negative). Royalty never feeds back."""
    adj = calc.waterfall_adjusted_gross(settlement["audited_gross_cents"],
                                        settlement["taxes_cents"],
                                        settlement["levies_cents"])
    vp = calc.waterfall_venue_payment(stop["guarantee_cents"], stop["split_pct"], adj)
    settlement["adjusted_gross_cents"] = adj
    settlement["venue_payment_cents"] = vp
    settlement["producer_share_cents"] = calc.waterfall_producer_share(adj, vp)


@bp.route("/settlements/<settlement_id>", methods=["PUT"])
def put_settlement(settlement_id):
    user_id, role = authenticate()
    body = get_body()
    # Role-for-transition (priority 2) on this shared endpoint: figures and
    # SUBMITTED are Treasurer-only; DISPUTED/VOID Producer-only;
    # APPROVED/PAID shared (SoD separates the users, not the roles).
    target = body.get("status")
    has_figures = any(k in body for k in FIGURE_FIELDS)
    allowed = None
    if target == "SUBMITTED":
        allowed = ("Treasurer",)
    elif target in ("DISPUTED", "VOID"):
        allowed = ("Producer",)
    elif target in ("APPROVED", "PAID"):
        allowed = ("Producer", "Treasurer")
    if has_figures:
        allowed = ("Treasurer",) if allowed is None else tuple(
            r for r in allowed if r == "Treasurer")
    if allowed is None:
        allowed = ("Treasurer", "Producer")
    require_roles(role, allowed)

    settlement = db.settlements.get(settlement_id)
    if settlement is None:
        raise err(ERR_NOT_FOUND, 404, "Settlement not found")

    # Segregation of duties (authorization class — before shape/state):
    # approve requires caller != submitted_by; pay requires caller != approved_by.
    if target == "APPROVED" and user_id == settlement.get("submitted_by"):
        raise err(ERR_SOD_SUBMIT_APPROVE, 403,
                  "The submitting user may not approve this settlement")
    if target == "PAID" and user_id == settlement.get("approved_by"):
        raise err(ERR_SOD_APPROVE_PAY, 403,
                  "The approving user may not pay this settlement")

    # Shape (priority 4).
    reject_unknown(body, set(FIGURE_FIELDS) | {"status", "dispute_reason"})
    figures = {}
    for k in FIGURE_FIELDS:
        if k in body:
            figures[k] = as_int(body[k], k, minv=0)
    if target is not None:
        target = as_enum(target, "status", SETTLEMENT_STATUSES)
        if target == "DISPUTED":
            reason = body.get("dispute_reason")
            if not isinstance(reason, str) or reason == "":
                raise err(ERR_INVALID_REQUEST, 400,
                          "Disputing a settlement requires a dispute_reason")

    cur = settlement["status"]
    # State (priority 5): figure writes only while DRAFT or DISPUTED; the
    # transition guards SUBMITTED from {DRAFT, DISPUTED}, APPROVED/DISPUTED
    # from SUBMITTED, VOID from DISPUTED, PAID from APPROVED.
    if has_figures and cur not in ("DRAFT", "DISPUTED"):
        raise err(ERR_SETTLEMENT_INVALID_STATE, 409,
                  "Audited figures may be recorded only while DRAFT or DISPUTED")
    legal = {
        ("DRAFT", "SUBMITTED"), ("SUBMITTED", "APPROVED"),
        ("SUBMITTED", "DISPUTED"), ("DISPUTED", "SUBMITTED"),
        ("DISPUTED", "VOID"), ("APPROVED", "PAID"),
    }
    if target is not None and (cur, target) not in legal:
        raise err(ERR_SETTLEMENT_INVALID_STATE, 409,
                  "Settlement transition %s -> %s is not allowed" % (cur, target))

    # Apply figure writes (status preserved on a figures-only PUT).
    for k, v in figures.items():
        settlement[k] = v

    stop = db.stops[settlement["stop_id"]]
    if target == "SUBMITTED":
        # Fiscal completeness (priority 10): all three audited figures recorded.
        if any(settlement[k] is None for k in FIGURE_FIELDS):
            raise err(ERR_SETTLEMENT_INCOMPLETE, 422,
                      "Submit requires audited_gross_cents, taxes_cents and levies_cents")
        settlement["submitted_by"] = user_id
        settlement["status"] = "SUBMITTED"
        _recompute_waterfall(settlement, stop)
    elif target == "APPROVED":
        settlement["approved_by"] = user_id
        # Royalty sampled against tour.recouped at THIS instant (marginal brackets).
        tour = db.tours[stop["tour_id"]]
        settlement["royalty_cents"] = calc.calc_licensor_royalty(
            settlement["producer_share_cents"],
            tour["royalty_tier_threshold_cents"], tour["recouped"])
        settlement["status"] = "APPROVED"
        tour["royalty_accrued_cents"] += settlement["royalty_cents"]
        touch(tour)
    elif target == "DISPUTED":
        settlement["dispute_reason"] = body["dispute_reason"]
        settlement["status"] = "DISPUTED"
    elif target in ("VOID", "PAID"):
        settlement["status"] = target
    elif has_figures:
        # Figures PUT (DRAFT/DISPUTED): waterfall recomputes from current figures.
        if all(settlement[k] is not None for k in FIGURE_FIELDS):
            _recompute_waterfall(settlement, stop)
    else:
        raise err(ERR_INVALID_REQUEST, 400,
                  "A settlement PUT requires figure fields or a status")
    touch(settlement)
    return success(db.serialize("settlement", settlement), 200)
