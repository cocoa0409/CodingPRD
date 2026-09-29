"""Institution registration, closing, franchise marketing, receivership
proceeds, termination and the least-cost test (PRD sections 3.1, 3.3, 3.7, 3.8
and 3.9)."""

from flask import Blueprint, g, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import (
    ALL_ROLES,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
    require,
)
from db import db, new_row, touch
from errors import ApiError
from services import aggregates, least_cost
from util import format_iso

bp = Blueprint("institutions", __name__)

INSTITUTION_STATUSES = (
    "PRE_FAILURE_MONITORING",
    "READINESS_COLLECTION",
    "RESOLUTION_READY",
    "CLOSED_IN_RECEIVERSHIP",
    "RESOLUTION_COMPLETE",
    "RECEIVERSHIP_TERMINATED",
)

CLOSED_OR_LATER = (
    "CLOSED_IN_RECEIVERSHIP",
    "RESOLUTION_COMPLETE",
    "RECEIVERSHIP_TERMINATED",
)

BIDDABLE_STATUSES = ("RESOLUTION_READY", "CLOSED_IN_RECEIVERSHIP")

MARKETING_ACTIONS = ("OPEN", "CLOSE")


@bp.post("/institutions")
@require(CLOSING_MANAGER)
def create_institution():
    payload = shape.body()
    cert_number = shape.req_str(
        payload, "cert_number", min_len=4, max_len=6, pattern=shape.DIGITS_4_6
    )
    legal_name = shape.req_str(payload, "legal_name", min_len=1, max_len=160)
    charter_state = shape.req_str(
        payload, "charter_state", min_len=2, max_len=2, pattern=shape.TWO_UPPER
    )
    book_asset_value_cents = shape.req_int(payload, "book_asset_value_cents", minimum=0)
    estimated_recovery = shape.req_int(
        payload, "estimated_liquidation_recovery_cents", minimum=0
    )

    for existing in db.institutions.values():
        if existing["cert_number"] == cert_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    row = new_row(
        {
            "cert_number": cert_number,
            "legal_name": legal_name,
            "charter_state": charter_state,
            "book_asset_value_cents": book_asset_value_cents,
            "estimated_liquidation_recovery_cents": estimated_recovery,
            "status": "PRE_FAILURE_MONITORING",
            "failure_datetime": None,
            "readiness_standardized": False,
            "franchise_marketing_status": "NOT_STARTED",
            "bid_deadline_at": None,
            "least_cost_status": "NOT_STARTED",
            "least_cost_test_variant": None,
            "liquidation_baseline_cents": None,
            "conforming_bid_count": 0,
            "resolution_method": None,
            "gross_disposition_proceeds_cents": 0,
            "disposition_expense_total_cents": 0,
        }
    )
    db.institutions[row["id"]] = row
    return response.created(serializers.institution(row))


@bp.get("/institutions")
@require(ALL_ROLES)
def list_institutions():
    rows = list(db.institutions.values())
    status = request.args.get("status")
    charter_state = request.args.get("charter_state")
    least_cost_status = request.args.get("least_cost_status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if charter_state is not None:
        rows = [r for r in rows if r["charter_state"] == charter_state]
    if least_cost_status is not None:
        rows = [r for r in rows if r["least_cost_status"] == least_cost_status]
    return response.paginated(dbmod.ordered(rows), serializers.institution)


@bp.get("/institutions/<institution_id>")
@require(ALL_ROLES)
def get_institution(institution_id):
    row = lookup.institution(institution_id)
    return response.ok(serializers.institution(row))


@bp.get("/institutions/<institution_id>/insurance-summary")
@require(ALL_ROLES)
def get_insurance_summary(institution_id):
    row = lookup.institution(institution_id)
    return response.ok(aggregates.insurance_summary(row))


@bp.post("/institutions/<institution_id>/close")
@require(CLOSING_MANAGER)
def close_institution(institution_id):
    institution = lookup.institution(institution_id)
    shape.body()

    # PRD 3.3 assigns the closed-or-later statuses to their own guard, so that
    # set is screened before the readiness gate.
    if institution["status"] in CLOSED_OR_LATER:
        raise ApiError("ERR_INSTITUTION_ALREADY_CLOSED")
    if institution["status"] != "RESOLUTION_READY" or not institution[
        "readiness_standardized"
    ]:
        raise ApiError("ERR_INSTITUTION_NOT_READY")

    institution["status"] = "CLOSED_IN_RECEIVERSHIP"
    institution["failure_datetime"] = db.now_iso()
    touch(institution)

    # Cascade: the deposit base freezes so determinations can read it.
    for account in dbmod.ordered(lookup.accounts_of(institution_id)):
        if account["insurance_status"] == "PENDING":
            account["insurance_status"] = "FROZEN_FOR_DETERMINATION"
            touch(account)

    return response.ok(serializers.institution(institution))


@bp.post("/institutions/<institution_id>/franchise-marketing")
@require(RESOLUTION_ANALYST)
def franchise_marketing(institution_id):
    institution = lookup.institution(institution_id)
    payload = shape.body()
    action = shape.req_enum(payload, "marketing_action", MARKETING_ACTIONS)
    deadline = shape.opt_datetime(payload, "bid_deadline_at")
    if action == "OPEN" and deadline is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "bid_deadline_at is required when opening marketing"
        )

    if action == "OPEN":
        if (
            institution["franchise_marketing_status"] != "NOT_STARTED"
            or institution["status"] not in BIDDABLE_STATUSES
        ):
            raise ApiError("ERR_MARKETING_ACTION_INVALID")
        institution["franchise_marketing_status"] = "OPEN"
        institution["bid_deadline_at"] = format_iso(deadline)
    else:
        if institution["franchise_marketing_status"] != "OPEN":
            raise ApiError("ERR_MARKETING_ACTION_INVALID")
        institution["franchise_marketing_status"] = "CLOSED"
    touch(institution)
    return response.ok(serializers.institution(institution))


@bp.post("/institutions/<institution_id>/receivership-proceeds")
@require(RECEIVERSHIP_TRUSTEE)
def receivership_proceeds(institution_id):
    institution = lookup.institution(institution_id)
    payload = shape.body()
    shape.req_str(payload, "asset_pool_code", min_len=1)
    gross = shape.req_int(payload, "gross_proceeds_cents", minimum=0)
    expense = shape.req_int(payload, "disposition_expense_cents", minimum=0)

    # Fiscal guards run last in the pipeline of PRD 2.11.
    if expense > gross:
        raise ApiError("ERR_DISPOSITION_EXPENSE_EXCEEDS_PROCEEDS")

    institution["gross_disposition_proceeds_cents"] += gross
    institution["disposition_expense_total_cents"] += expense
    touch(institution)
    return response.ok(serializers.institution(institution))


@bp.post("/institutions/<institution_id>/terminate-receivership")
@require(RECEIVERSHIP_TRUSTEE)
def terminate_receivership(institution_id):
    institution = lookup.institution(institution_id)
    shape.body()

    terminable = institution["status"] == "RESOLUTION_COMPLETE"
    if terminable and any(
        d["status"] == "DECLARED" for d in lookup.distributions_of(institution_id)
    ):
        terminable = False
    if terminable and any(
        a["hold_status"] == "HELD" for a in lookup.accounts_of(institution_id)
    ):
        terminable = False
    if not terminable:
        raise ApiError("ERR_RECEIVERSHIP_NOT_TERMINABLE")

    institution["status"] = "RECEIVERSHIP_TERMINATED"
    touch(institution)
    return response.ok(serializers.institution(institution))


@bp.post("/institutions/<institution_id>/least-cost-test/evaluate")
@require(RESOLUTION_ANALYST)
def evaluate_least_cost(institution_id):
    institution = lookup.institution(institution_id)
    payload = shape.body()
    test_variant = shape.req_enum(payload, "test_variant", least_cost.TEST_VARIANTS)

    if (
        institution["status"] != "CLOSED_IN_RECEIVERSHIP"
        or institution["franchise_marketing_status"] not in ("OPEN", "CLOSED")
        or institution["least_cost_status"] != "NOT_STARTED"
    ):
        raise ApiError("ERR_LEAST_COST_TEST_NOT_OPEN")

    institution["least_cost_test_variant"] = test_variant
    institution["liquidation_baseline_cents"] = least_cost.liquidation_baseline_cents(
        institution
    )

    for bid in dbmod.ordered(lookup.bids_of_institution(institution_id)):
        if bid["status"] != "SUBMITTED":
            # Withdrawn and already-screened bids are not touched.
            continue
        reason = least_cost.non_conformance_reason(institution, bid)
        if reason is None:
            bid.update(least_cost.evaluated_cost(institution, bid, test_variant))
            bid["status"] = "CONFORMING"
        else:
            # A non-conforming bid has no cost calculation run at all.
            bid["status"] = "NON_CONFORMING"
            bid["non_conformance_reason"] = reason
        touch(bid)

    institution["conforming_bid_count"] = len(
        [
            b
            for b in lookup.bids_of_institution(institution_id)
            if b["status"] == "CONFORMING"
        ]
    )
    institution["least_cost_status"] = "EVALUATED"
    touch(institution)
    return response.ok(serializers.institution(institution))


@bp.post("/institutions/<institution_id>/least-cost-test/award")
@require(RESOLUTION_ANALYST)
def award_least_cost(institution_id):
    institution = lookup.institution(institution_id)
    shape.body()

    if institution["least_cost_status"] != "EVALUATED":
        raise ApiError("ERR_LEAST_COST_TEST_NOT_EVALUATED")

    winner = least_cost.award_candidate(institution)

    # --- level 1 --------------------------------------------------------
    if winner is not None:
        winner["status"] = "WINNER"
        touch(winner)
        institution["least_cost_status"] = "AWARDED"
        institution["resolution_method"] = winner["structure"]
        transition_target = "TRANSFERRED"
    else:
        institution["least_cost_status"] = "FAILED_ALL_BIDS"
        institution["resolution_method"] = "DEPOSIT_PAYOFF"
        transition_target = "PAID_OUT"
    institution["status"] = "RESOLUTION_COMPLETE"
    touch(institution)

    # --- level 2: every remaining screened bid is rejected ---------------
    for bid in dbmod.ordered(lookup.bids_of_institution(institution_id)):
        if winner is not None and bid["id"] == winner["id"]:
            continue
        if bid["status"] in ("CONFORMING", "NON_CONFORMING"):
            bid["status"] = "REJECTED"
            touch(bid)

    # --- level 3: the customer transition -------------------------------
    transitioned = 0
    for account in dbmod.ordered(lookup.accounts_of(institution_id)):
        if account["insurance_status"] != "DETERMINED":
            continue
        if account["hold_status"] not in ("NONE", "RELEASED"):
            continue
        if account["transition_status"] != "PENDING":
            continue
        account["transition_status"] = transition_target
        touch(account)
        transitioned += 1

    # --- level 4: branches become ready, caused by level 3 --------------
    if transitioned > 0:
        for reopening in dbmod.ordered(lookup.reopenings_of(institution_id)):
            if reopening["status"] == "PLANNED":
                reopening["status"] = "READY"
                touch(reopening)

    return response.ok(serializers.institution(institution))
