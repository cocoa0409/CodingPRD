"""Settlement endpoints (PRD 3.7): get, submit, verify, pay, plus flat
fetch/search. Segregation of duties: the verifying accountant's X-User-ID
must differ from the submitting promoter's X-User-ID."""
from flask import Blueprint, request

from db import store, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_PROMOTER, ROLE_ACCOUNTANT, get_body, v_int,
)
from response import success_object, list_response
from services import (
    settlement_json, resolve_tour, resolve_show, settlement_for_show,
    accepted_hold_for_show, compute_artist_share, compute_variance,
    recompute_tour_financials,
)

bp = Blueprint("settlements", __name__)


def _resolve_settlement(tourId, showId):
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    st = settlement_for_show(s["id"])
    if st is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Settlement not found")
    return t, s, st


@bp.get("/tours/<tourId>/shows/<showId>/settlement")
def get_settlement(tourId, showId):
    authenticate(READ_ROLES)
    _, _, st = _resolve_settlement(tourId, showId)
    return success_object(settlement_json(st))


@bp.post("/tours/<tourId>/shows/<showId>/settlement/submit")
def submit_settlement(tourId, showId):
    uid, _ = authenticate(frozenset({ROLE_PROMOTER}))
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    # PRD 3.7: submission requires the show to be PERFORMED (otherwise
    # ERR_SHOW_NOT_PERFORMED). The Settlement is spawned at mark-performed, so
    # a non-PERFORMED show has no settlement yet — the show-state gate fires
    # first.
    if s["status"] != "PERFORMED":
        raise ApiError(
            "ERR_SHOW_NOT_PERFORMED",
            409,
            "Settlement submit requires Show.status == PERFORMED",
        )
    st = settlement_for_show(s["id"])
    if st is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Settlement not found")
    if st["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "submit requires Settlement.status == DRAFT"
        )
    b = get_body()
    gross = v_int(b, "box_office_gross_cents", minv=0)
    taxes = v_int(b, "taxes_cents", minv=0)
    facility_fees = v_int(b, "facility_fees_cents", minv=0)
    promoter_expenses = v_int(b, "promoter_expenses_cents", minv=0)
    hold = accepted_hold_for_show(s["id"])
    st["box_office_gross_cents"] = gross
    st["taxes_cents"] = taxes
    st["facility_fees_cents"] = facility_fees
    st["promoter_expenses_cents"] = promoter_expenses
    st["artist_share_cents"] = compute_artist_share(
        hold, gross, taxes, facility_fees, promoter_expenses
    )
    variance, flag = compute_variance(
        gross, s["tickets_sold"], s["avg_ticket_price_cents"]
    )
    st["variance_cents"] = variance
    st["variance_flag"] = flag
    st["status"] = "SUBMITTED"
    st["_submitted_by"] = uid
    touch(st)
    return success_object(settlement_json(st))


@bp.post("/tours/<tourId>/shows/<showId>/settlement/verify")
def verify_settlement(tourId, showId):
    uid, _ = authenticate(frozenset({ROLE_ACCOUNTANT}))
    t, s, st = _resolve_settlement(tourId, showId)
    if st["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "verify requires Settlement.status == SUBMITTED"
        )
    if st["variance_flag"] == "MATERIAL":
        raise ApiError(
            "ERR_MATERIAL_VARIANCE", 409, "Settlement variance_flag == MATERIAL"
        )
    # Budget-cap guard (ERR_BUDGET_OVERRUN): the entity model defines no
    # per-show budget cap field anywhere, so the cap check cannot exceed and
    # never fires.
    # Segregation of duties: verifier's X-User-ID must differ from the
    # submitting promoter's X-User-ID.
    if st["_submitted_by"] is not None and st["_submitted_by"] == uid:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Settlement submitter and verifier must be different X-User-ID",
        )
    st["status"] = "VERIFIED"
    touch(st)
    return success_object(settlement_json(st))


@bp.post("/tours/<tourId>/shows/<showId>/settlement/pay")
def pay_settlement(tourId, showId):
    authenticate(frozenset({ROLE_ACCOUNTANT}))
    t, s, st = _resolve_settlement(tourId, showId)
    if st["status"] != "VERIFIED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "pay requires Settlement.status == VERIFIED"
        )
    st["status"] = "PAID"
    touch(st)
    # Payment cascades: the show moves PERFORMED -> SETTLED and the tour's
    # settled totals absorb the show's settled gross and cost.
    if s["status"] == "PERFORMED":
        s["status"] = "SETTLED"
        touch(s)
    if recompute_tour_financials(t):
        touch(t)
    return success_object(settlement_json(st))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/settlements/<settlementId>")
def flat_get_settlement(settlementId):
    authenticate(READ_ROLES)
    st = store["settlements"].get(settlementId)
    if st is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Settlement not found")
    return success_object(settlement_json(st))


@bp.get("/tours/settlements")
def flat_search_settlements():
    authenticate(READ_ROLES)
    show_id = request.args.get("show_id")
    items = list(store["settlements"].values())
    if show_id is not None:
        items = [s for s in items if s["show_id"] == show_id]
    return list_response(items, settlement_json)
