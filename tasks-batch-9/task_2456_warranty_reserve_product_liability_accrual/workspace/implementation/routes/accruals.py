"""WarrantyAccrual and AdequacyReview endpoints."""

from flask import Blueprint

import lookups
import store
from auth import authenticate
from errors import fail
from response import list_response, object_response
from serialize import dump, dump_many
from services import calc
from validation import Field, no_body, paginate, pagination, query_filter, validate_body

bp = Blueprint("accruals", __name__)

READ_ROLES = ("WarrantyAnalyst", "ReserveController", "Actuary")
METHODS = ("HISTORICAL_RATE", "ANALOG_BLEND")

# Statuses in which an AccrualPeriod still accepts accrual estimation work.
ESTIMATION_OPEN = ("OPEN", "ANALYSIS_LOCKED")


@bp.post("/warranty/accruals")
def create_accrual():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body(
        [
            Field("period_id", "id"),
            Field("vintage_id", "id"),
            Field("method", "enum", enum=METHODS),
            Field("elapsed_exposure_bps", "int", minimum=0, maximum=10000),
            Field("expected_period_version", "int"),
        ]
    )
    period = lookups.require_period(values["period_id"])
    vintage = lookups.require_vintage(values["vintage_id"])

    # Rung 9 precedes rung 11: the OCC guard answers before the period-status guard.
    if values["expected_period_version"] != period["version"]:
        fail("ERR_STALE_PERIOD_VERSION")
    if period["status"] not in ESTIMATION_OPEN:
        fail("ERR_PERIOD_CLOSED")

    family = calc.family_of_vintage(vintage)
    if not calc.failure_modes_of_family(family["id"]):
        fail("ERR_NO_FAILURE_MODES_DEFINED")
    if values["method"] == "ANALOG_BLEND":
        if family["analog_family_id"] is None or family["engineering_estimate_rate_ppm"] is None:
            fail("ERR_ANALOG_BASIS_MISSING")
    if values["method"] == "HISTORICAL_RATE" and family["history_maturity_status"] != "MATURE":
        fail("ERR_INSUFFICIENT_CLAIM_HISTORY")
    if vintage["exposure_status"] != "ACTIVE":
        fail("ERR_VINTAGE_EXPOSURE_EXPIRED")
    for existing in store.all_rows("accruals"):
        if (
            existing["period_id"] == values["period_id"]
            and existing["vintage_id"] == values["vintage_id"]
            and existing["status"] in ("DRAFT", "PROPOSED")
        ):
            fail("ERR_DUPLICATE_ACCRUAL")

    row = store.insert(
        "accruals",
        {
            "_kind": "WarrantyAccrual",
            "period_id": values["period_id"],
            "vintage_id": values["vintage_id"],
            "method": values["method"],
            "elapsed_exposure_bps": values["elapsed_exposure_bps"],
            "status": "DRAFT",
            "revision_index": 0,
            "expected_claim_rate_ppm": 0,
            "cost_per_claim_basis_cents": 0,
            "paid_to_date_cents": 0,
            "accrued_amount_cents": 0,
            "proposed_by_user_id": None,
            "posted_by_user_id": None,
        },
    )
    row.update(calc.warranty_accrual_amount(row))
    store.touch(period)
    return object_response(dump(row), 201)


@bp.get("/warranty/accruals/<accrual_id>")
def read_accrual(accrual_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require("accruals", accrual_id)))


@bp.get("/warranty/accruals")
def list_accruals():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("accruals")
    period_id = query_filter("period_id")
    if period_id is not None:
        rows = [r for r in rows if r["period_id"] == period_id]
    vintage_id = query_filter("vintage_id")
    if vintage_id is not None:
        rows = [r for r in rows if r["vintage_id"] == vintage_id]
    status = query_filter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/warranty/accruals/<accrual_id>/propose")
def propose_accrual(accrual_id):
    user_id, _ = authenticate(("WarrantyAnalyst",))
    accrual = lookups.require("accruals", accrual_id)
    no_body()
    period = store.get("periods", accrual["period_id"])
    if period["status"] not in ESTIMATION_OPEN:
        fail("ERR_PERIOD_CLOSED")
    if accrual["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")

    accrual["status"] = "PROPOSED"
    accrual["proposed_by_user_id"] = user_id
    accrual.update(calc.warranty_accrual_amount(accrual))
    store.touch(accrual)
    return object_response(dump(accrual))


@bp.post("/warranty/accruals/<accrual_id>/revise")
def revise_accrual(accrual_id):
    authenticate(("WarrantyAnalyst",))
    accrual = lookups.require("accruals", accrual_id)
    no_body()
    period = store.get("periods", accrual["period_id"])
    if period["status"] not in ESTIMATION_OPEN:
        fail("ERR_PERIOD_CLOSED")
    if accrual["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION")

    accrual["status"] = "DRAFT"
    accrual["revision_index"] += 1
    accrual["proposed_by_user_id"] = None
    store.touch(accrual)
    return object_response(dump(accrual))


@bp.post("/warranty/accruals/<accrual_id>/post")
def post_accrual(accrual_id):
    user_id, _ = authenticate(("ReserveController",))
    accrual = lookups.require("accruals", accrual_id)
    no_body()
    period = store.get("periods", accrual["period_id"])

    # Rung 11 is narrower here than for the estimation transitions: only a CLOSED
    # period answers ERR_PERIOD_CLOSED, and rung 12 handles OPEN / ACTUARIAL_REVIEW.
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")
    if accrual["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if period["status"] != "ANALYSIS_LOCKED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if user_id == accrual["proposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    vintage = store.get("vintages", accrual["vintage_id"])
    family = calc.family_of_vintage(vintage)
    if calc.family_reserve_balance(family, hypothetical_post=accrual) > family["reserve_cap_cents"]:
        fail("ERR_RESERVE_CAP_EXCEEDED")

    accrual["status"] = "POSTED"
    accrual["posted_by_user_id"] = user_id
    store.touch(accrual)
    for other in store.all_rows("accruals"):
        if other["id"] == accrual["id"]:
            continue
        if (
            other["period_id"] == accrual["period_id"]
            and other["vintage_id"] == accrual["vintage_id"]
            and other["status"] == "POSTED"
        ):
            other["status"] = "SUPERSEDED"
            store.touch(other)
    if calc.apply_balance_and_posture(family):
        store.touch(family)
    return object_response(dump(accrual))


# ---------------------------------------------------------------------------
# AdequacyReview
# ---------------------------------------------------------------------------
@bp.post("/warranty/adequacy-reviews")
def create_adequacy_review():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body([Field("period_id", "id"), Field("family_id", "id")])
    period = lookups.require_period(values["period_id"])
    family = lookups.require_family(values["family_id"])
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")

    figures = calc.adequacy_analysis(period, family)
    row = {
        "_kind": "AdequacyReview",
        "period_id": values["period_id"],
        "family_id": values["family_id"],
    }
    row.update(figures)
    row["true_up_applied"] = False
    row["applied_by_user_id"] = None
    store.insert("adequacy_reviews", row)
    return object_response(dump(row), 201)


@bp.get("/warranty/adequacy-reviews/<review_id>")
def read_adequacy_review(review_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require("adequacy_reviews", review_id)))


@bp.get("/warranty/adequacy-reviews")
def list_adequacy_reviews():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("adequacy_reviews")
    period_id = query_filter("period_id")
    if period_id is not None:
        rows = [r for r in rows if r["period_id"] == period_id]
    family_id = query_filter("family_id")
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/warranty/adequacy-reviews/<review_id>/apply-true-up")
def apply_true_up(review_id):
    user_id, _ = authenticate(("ReserveController",))
    review = lookups.require("adequacy_reviews", review_id)
    no_body()
    period = store.get("periods", review["period_id"])
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")
    if review["true_up_applied"]:
        fail("ERR_INVALID_STATE_TRANSITION")

    review["true_up_applied"] = True
    review["applied_by_user_id"] = user_id
    store.touch(review)
    family = store.get("families", review["family_id"])
    if family is not None and calc.apply_balance_and_posture(family):
        store.touch(family)
    return object_response(dump(review))
