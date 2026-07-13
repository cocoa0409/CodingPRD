from flask import Blueprint, request, g

import store
from store import (DB, make, touch, ser, by_seq, now,
                   quotes_of_parcel, bonds_of_district, installments_of_bond)
from web import (protected, ALL_ROLES, ok, ok_list, pagination, body_json,
                 require, as_int, as_str, as_enum, owner_check, ApiError)
from fetch import get_parcel, get_district, get_quote
import calc
import logic
from util import parse_dt, add_days

bp = Blueprint("quotes", __name__)

QUOTE_MODES = {"IMMEDIATE", "NEXT_CALL_DATE"}


def _issued_bond_for(parcel, district):
    issued = [b for b in bonds_of_district(district["id"]) if b["status"] == "ISSUED"]
    for b in issued:
        if any(i["parcel_id"] == parcel["id"] for i in installments_of_bond(b["id"])):
            return b
    return issued[0] if issued else None


@bp.post("/parcels/<pid>/payoff-quotes")
@protected(["ParcelOwner", "CountyTreasurer"])
def create_quote(pid):
    if g.role == "ParcelOwner":
        owner_check(pid)
    parcel = get_parcel(pid)

    b = body_json()
    # OCC (priority 4) — check when the field is provided and well-typed
    epv = b.get("expected_parcel_version")
    if epv is not None and isinstance(epv, int) and not isinstance(epv, bool):
        if epv != parcel["version"]:
            raise ApiError("ERR_STALE_PARCEL_VERSION")

    if parcel["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PARCEL_STATE")
    district = get_district(parcel["district_id"])
    if district["status"] != "FORMED":
        raise ApiError("ERR_DISTRICT_NOT_FORMED")

    epv = as_int(require(b, "expected_parcel_version"), "expected_parcel_version", minimum=0)
    mode = as_enum(require(b, "quote_mode"), "quote_mode", QUOTE_MODES)
    quote_dt = parse_dt(as_str(require(b, "quote_date"), "quote_date"))

    bond = _issued_bond_for(parcel, district)
    if bond is None:
        raise ApiError("ERR_VALIDATION", "no issued bond for this parcel's district")
    if quote_dt < bond["issuance_date"]:
        raise ApiError("ERR_QUOTE_DATE_INVALID")

    fig = calc.payoff_figures(parcel["remaining_principal_cents"], bond,
                              district["total_apportioned_principal_cents"], mode, quote_dt)

    # void prior QUOTED quotes on this parcel
    for q in quotes_of_parcel(pid):
        if q["status"] == "QUOTED":
            q["status"] = "VOIDED"
            touch(q)

    quote = make("quotes", {
        "parcel_id": parcel["id"],
        "quote_mode": mode,
        "quote_date": quote_dt,
        "remaining_principal_cents": fig["remaining_principal_cents"],
        "accrued_interest_cents": fig["accrued_interest_cents"],
        "prepayment_premium_cents": fig["prepayment_premium_cents"],
        "reserve_credit_cents": fig["reserve_credit_cents"],
        "total_payoff_cents": fig["total_payoff_cents"],
        "valid_until": add_days(quote_dt, calc.QUOTE_VALIDITY_DAYS),
        "status": "QUOTED",
    })

    # creating a quote advances the parcel's version by 1
    touch(parcel)

    return ok(ser(quote), status=201)


@bp.get("/parcels/<pid>/payoff-quotes")
@protected(ALL_ROLES)
def list_quotes(pid):
    get_parcel(pid)
    items = quotes_of_parcel(pid)
    status = request.args.get("status")
    if status:
        items = [q for q in items if q["status"] == status]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.post("/payoff-quotes/<qid>/honor")
@protected(["CountyTreasurer"])
def honor_quote(qid):
    quote = get_quote(qid)
    if quote["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_QUOTE_STATE")
    parcel = get_parcel(quote["parcel_id"])
    if parcel["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PARCEL_STATE")

    parcel["remaining_principal_cents"] = 0
    logic.parcel_paid_off(parcel)

    quote["status"] = "HONORED"
    touch(quote)

    logic.maybe_call_bonds(parcel["district_id"])

    return ok(ser(quote))
