"""LiabilityReserve endpoints — the product-liability / IBNR ledger."""

from flask import Blueprint

import lookups
import store
from auth import authenticate
from errors import fail
from response import list_response, object_response
from serialize import dump, dump_many
from services import calc
from validation import Field, no_body, paginate, pagination, query_filter, validate_body

bp = Blueprint("liability", __name__)

READ_ROLES = ("Actuary", "ReserveController", "WarrantyAnalyst")
DECISIONS = ("REVIEWED", "RETURNED")


@bp.post("/warranty/liability-reserves")
def create_reserve():
    authenticate(("Actuary",))
    values, _ = validate_body(
        [
            Field("period_id", "id"),
            Field("family_id", "id"),
            Field("reported_claim_count", "int", minimum=0),
            Field("asserted_case_reserve_cents", "int", minimum=0),
            Field("reporting_lag_months", "int", minimum=0, maximum=24),
            Field("severity_trend_bps", "int", minimum=-5000, maximum=10000),
        ]
    )
    period = lookups.require_period(values["period_id"])
    family = lookups.require_family(values["family_id"])
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")
    for existing in store.all_rows("liability_reserves"):
        if (
            existing["period_id"] == values["period_id"]
            and existing["family_id"] == values["family_id"]
            and existing["status"] in ("DRAFT", "ACTUARY_REVIEWED", "BOOKED")
        ):
            fail("ERR_DUPLICATE_LIABILITY_RESERVE")

    row = store.insert(
        "liability_reserves",
        {
            "_kind": "LiabilityReserve",
            "period_id": values["period_id"],
            "family_id": values["family_id"],
            "reported_claim_count": values["reported_claim_count"],
            "asserted_case_reserve_cents": values["asserted_case_reserve_cents"],
            "reporting_lag_months": values["reporting_lag_months"],
            "severity_trend_bps": values["severity_trend_bps"],
            "avg_case_severity_cents": 0,
            "lag_factor_bps": 0,
            "ibnr_claim_count": 0,
            "ibnr_reserve_cents": 0,
            "total_liability_reserve_cents": 0,
            "status": "DRAFT",
            "return_count": 0,
            "reviewed_by_user_id": None,
        },
    )
    row.update(calc.ibnr_liability_reserve(row, family))
    return object_response(dump(row), 201)


@bp.get("/warranty/liability-reserves/<reserve_id>")
def read_reserve(reserve_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require("liability_reserves", reserve_id)))


@bp.get("/warranty/liability-reserves")
def list_reserves():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("liability_reserves")
    period_id = query_filter("period_id")
    if period_id is not None:
        rows = [r for r in rows if r["period_id"] == period_id]
    family_id = query_filter("family_id")
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    status = query_filter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/warranty/liability-reserves/<reserve_id>/actuarial-decision")
def actuarial_decision(reserve_id):
    user_id, _ = authenticate(("Actuary",))
    reserve = lookups.require("liability_reserves", reserve_id)
    values, _ = validate_body([Field("decision", "enum", enum=DECISIONS)])
    period = store.get("periods", reserve["period_id"])
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")

    if values["decision"] == "REVIEWED":
        if reserve["status"] != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION")
        if period["status"] not in ("ANALYSIS_LOCKED", "ACTUARIAL_REVIEW"):
            fail("ERR_INVALID_STATE_TRANSITION")
        reserve["status"] = "ACTUARY_REVIEWED"
        reserve["reviewed_by_user_id"] = user_id
        family = store.get("families", reserve["family_id"])
        reserve.update(calc.ibnr_liability_reserve(reserve, family))
    else:
        if reserve["status"] != "ACTUARY_REVIEWED":
            fail("ERR_INVALID_STATE_TRANSITION")
        reserve["status"] = "DRAFT"
        reserve["return_count"] += 1
        reserve["reviewed_by_user_id"] = None
    store.touch(reserve)
    return object_response(dump(reserve))


@bp.post("/warranty/liability-reserves/<reserve_id>/book")
def book_reserve(reserve_id):
    user_id, _ = authenticate(("ReserveController",))
    reserve = lookups.require("liability_reserves", reserve_id)
    no_body()
    period = store.get("periods", reserve["period_id"])
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")
    if reserve["status"] != "ACTUARY_REVIEWED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if period["status"] != "ACTUARIAL_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION")
    if user_id == reserve["reviewed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    reserve["status"] = "BOOKED"
    store.touch(reserve)
    return object_response(dump(reserve))
