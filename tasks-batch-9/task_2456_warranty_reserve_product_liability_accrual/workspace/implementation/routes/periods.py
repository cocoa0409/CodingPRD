"""AccrualPeriod and ReserveRollforward endpoints."""

from flask import Blueprint

import lookups
import store
from auth import authenticate
from errors import fail
from response import list_response, object_response
from serialize import dump, dump_many
from services import calc
from validation import Field, no_body, paginate, pagination, query_filter, validate_body

bp = Blueprint("periods", __name__)

READ_ROLES = ("ReserveController", "WarrantyAnalyst", "QualityEngineer", "Actuary")
ROLLFORWARD_READ_ROLES = ("ReserveController", "WarrantyAnalyst", "Actuary")


@bp.post("/warranty/periods")
def create_period():
    authenticate(("ReserveController",))
    values, _ = validate_body(
        [
            Field("period_code", "str"),
            Field("period_start_date", "date"),
            Field("period_end_date", "date"),
        ]
    )
    if values["period_end_date"] <= values["period_start_date"]:
        fail("ERR_INVALID_REQUEST", "period_end_date must be strictly after period_start_date.")
    if lookups.period_by_code(values["period_code"]) is not None:
        fail("ERR_DUPLICATE_CODE")
    row = store.insert(
        "periods",
        {
            "_kind": "AccrualPeriod",
            "period_code": values["period_code"],
            "period_start_date": values["period_start_date"],
            "period_end_date": values["period_end_date"],
            "status": "OPEN",
            "locked_at": None,
            "closed_at": None,
            "reopen_count": 0,
        },
    )
    return object_response(dump(row), 201)


@bp.get("/warranty/periods/<period_id>")
def read_period(period_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require_period(period_id)))


@bp.post("/warranty/periods/<period_id>/lock-analysis")
def lock_analysis(period_id):
    authenticate(("ReserveController",))
    period = lookups.require_period(period_id)
    no_body()
    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")
    period["status"] = "ANALYSIS_LOCKED"
    period["locked_at"] = store.logical_now_iso()
    store.touch(period)
    return object_response(dump(period))


@bp.post("/warranty/periods/<period_id>/open-actuarial-review")
def open_actuarial_review(period_id):
    authenticate(("ReserveController",))
    period = lookups.require_period(period_id)
    no_body()
    if period["status"] != "ANALYSIS_LOCKED":
        fail("ERR_INVALID_STATE_TRANSITION")
    for accrual in store.all_rows("accruals"):
        if accrual["period_id"] == period_id and accrual["status"] in ("DRAFT", "PROPOSED"):
            fail("ERR_UNPOSTED_ACCRUALS_REMAIN")
    period["status"] = "ACTUARIAL_REVIEW"
    store.touch(period)
    return object_response(dump(period))


@bp.post("/warranty/periods/<period_id>/reopen-analysis")
def reopen_analysis(period_id):
    authenticate(("ReserveController",))
    period = lookups.require_period(period_id)
    no_body()
    if period["status"] != "ACTUARIAL_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION")
    period["status"] = "ANALYSIS_LOCKED"
    period["reopen_count"] += 1
    period["locked_at"] = store.logical_now_iso()
    store.touch(period)
    # Conditional cascade: only ACTUARY_REVIEWED rows return; BOOKED and DRAFT
    # rows are left untouched.  Rows are processed in created_at ASC order.
    for reserve in store.all_rows("liability_reserves"):
        if reserve["period_id"] != period_id or reserve["status"] != "ACTUARY_REVIEWED":
            continue
        reserve["status"] = "DRAFT"
        reserve["return_count"] += 1
        reserve["reviewed_by_user_id"] = None
        store.touch(reserve)
    return object_response(dump(period))


@bp.post("/warranty/periods/<period_id>/close")
def close_period(period_id):
    authenticate(("ReserveController",))
    period = lookups.require_period(period_id)
    no_body()
    if period["status"] != "ACTUARIAL_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION")
    if not any(r["period_id"] == period_id for r in store.all_rows("rollforwards")):
        fail("ERR_ROLLFORWARD_MISSING")
    for reserve in store.all_rows("liability_reserves"):
        if reserve["period_id"] == period_id and reserve["status"] != "BOOKED":
            fail("ERR_LIABILITY_RESERVE_NOT_BOOKED")
    period["status"] = "CLOSED"
    period["closed_at"] = store.logical_now_iso()
    store.touch(period)
    return object_response(dump(period))


@bp.post("/warranty/periods/<period_id>/rollforward")
def generate_rollforward(period_id):
    user_id, _ = authenticate(("ReserveController",))
    period = lookups.require_period(period_id)
    values, _ = validate_body([Field("expected_period_version", "int")])
    if values["expected_period_version"] != period["version"]:
        fail("ERR_STALE_PERIOD_VERSION")
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")

    figures = calc.rollforward_figures(period)
    row = {"_kind": "ReserveRollforward", "period_id": period_id}
    row.update(figures)
    row["generated_by_user_id"] = user_id
    store.insert("rollforwards", row, common_fields=False)
    # rollforward_generated is derived from the existence of this row; the period's
    # version still advances so a second generation attempt reads as stale.
    store.touch(period)
    return object_response(dump(row), 201)


@bp.get("/warranty/rollforwards/<rollforward_id>")
def read_rollforward(rollforward_id):
    authenticate(ROLLFORWARD_READ_ROLES)
    return object_response(dump(lookups.require("rollforwards", rollforward_id)))


@bp.get("/warranty/rollforwards")
def list_rollforwards():
    authenticate(ROLLFORWARD_READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("rollforwards")
    period_id = query_filter("period_id")
    if period_id is not None:
        rows = [r for r in rows if r["period_id"] == period_id]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))
