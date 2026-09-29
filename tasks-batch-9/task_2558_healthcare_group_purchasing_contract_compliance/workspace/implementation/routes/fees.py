"""Administrative fee accrual, collection, distribution and reversal.

PRD section 3.9.
"""

from flask import Blueprint

from db import db, ordered
from enums import DISTRIBUTION_STATUSES
from errors import ApiError
from middleware import ALL_ROLES, FINANCE_ADMINISTRATOR, authenticate
from response import list_response, object_response
from services.calc import accrued_fee_for, holdback_for, member_waterfall
from services.lookup import get_distribution, resolve_body_fks
from validation import (
    bad,
    body_json,
    field_date,
    field_int,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

fees_bp = Blueprint("fees", __name__)

# A reversed settlement releases its period so it can be settled again.
PERIOD_BLOCKING_STATUSES = ("ACCRUED", "COLLECTED", "DISTRIBUTED")


@fees_bp.route("/gpo/admin-fee-distributions", methods=["POST"])
def create_distribution():
    authenticate((FINANCE_ADMINISTRATOR,))
    body = body_json()
    resolved = resolve_body_fks(body, ("contract_id",))
    contract = resolved["contract_id"]
    if contract is None:
        raise bad("Field 'contract_id' is required.")

    period_start = field_date(body, "period_start")
    period_end = field_date(body, "period_end")

    if contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE",
            "Administrative fees can only be accrued on an ACTIVE contract.",
        )
    for existing in db.distributions.values():
        if existing["contract_id"] != contract["id"]:
            continue
        if existing["status"] not in PERIOD_BLOCKING_STATUSES:
            continue
        if (
            existing["period_start"] == period_start
            and existing["period_end"] == period_end
        ):
            raise ApiError(
                "ERR_DUPLICATE_DISTRIBUTION_PERIOD",
                "A live settlement already covers this period for the contract.",
            )
    if period_end <= period_start:
        raise ApiError(
            "ERR_EFFECTIVE_WINDOW_INVALID", "period_end must be strictly after period_start."
        )

    row = db.new_row()
    row.update(
        {
            "contract_id": contract["id"],
            "period_start": period_start,
            "period_end": period_end,
            "status": "ACCRUED",
            # Computed once here and never recomputed by a later transition.
            "accrued_fee_cents": accrued_fee_for(contract, period_start, period_end),
            "collected_fee_cents": 0,
            "basis": None,
            "gross_pool_cents": 0,
            "holdback_bps_applied": 0,
            "holdback_cents": 0,
            "net_pool_cents": 0,
            "member_pool_cents": 0,
            "member_shares": [],
            "member_share_total_cents": 0,
            "undistributed_cents": 0,
            "gpo_retained_cents": 0,
            "reverse_note": None,
        }
    )
    db.distributions[row["id"]] = row
    return object_response(row, 201)


@fees_bp.route("/gpo/admin-fee-distributions/<distribution_id>", methods=["GET"])
def read_distribution(distribution_id):
    authenticate(ALL_ROLES)
    return object_response(get_distribution(distribution_id))


@fees_bp.route("/gpo/admin-fee-distributions", methods=["GET"])
def list_distributions():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    contract_id = query_string("contract_id")
    status = query_enum("status", DISTRIBUTION_STATUSES)
    rows = [
        row
        for row in ordered(db.distributions.values())
        if (contract_id is None or row["contract_id"] == contract_id)
        and (status is None or row["status"] == status)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@fees_bp.route(
    "/gpo/admin-fee-distributions/<distribution_id>/collect", methods=["POST"]
)
def collect_distribution(distribution_id):
    authenticate((FINANCE_ADMINISTRATOR,))
    distribution = get_distribution(distribution_id)
    body = body_json()
    collected_fee_cents = field_int(body, "collected_fee_cents", minimum=0)
    if distribution["status"] != "ACCRUED":
        raise ApiError(
            "ERR_INVALID_DISTRIBUTION_STATE", "Only an ACCRUED settlement can be collected."
        )
    if collected_fee_cents > distribution["accrued_fee_cents"]:
        raise ApiError(
            "ERR_COLLECTION_EXCEEDS_ACCRUAL",
            "collected_fee_cents cannot exceed accrued_fee_cents.",
        )
    distribution["collected_fee_cents"] = collected_fee_cents
    distribution["status"] = "COLLECTED"
    db.touch(distribution)
    return object_response(distribution)


@fees_bp.route(
    "/gpo/admin-fee-distributions/<distribution_id>/distribute", methods=["POST"]
)
def distribute_distribution(distribution_id):
    authenticate((FINANCE_ADMINISTRATOR,))
    distribution = get_distribution(distribution_id)
    if distribution["status"] not in ("ACCRUED", "COLLECTED"):
        raise ApiError(
            "ERR_INVALID_DISTRIBUTION_STATE",
            "Only an ACCRUED or COLLECTED settlement can be distributed.",
        )
    contract = db.contracts.get(distribution["contract_id"])
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "The settled contract no longer exists.")
    share_basis = contract["share_basis"]
    if distribution["status"] == "ACCRUED" and share_basis != "ACCRUAL":
        raise ApiError(
            "ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE",
            "This contract settles on collected cash, which has not been recorded yet.",
        )
    if distribution["status"] == "COLLECTED" and share_basis != "COLLECTED":
        raise ApiError(
            "ERR_DISTRIBUTION_BASIS_MISMATCH",
            "This contract settles on the accrued figure, not the collected one.",
        )

    # The settlement records the rule it was computed under.
    distribution["basis"] = share_basis
    gross_pool_cents = (
        distribution["accrued_fee_cents"]
        if share_basis == "ACCRUAL"
        else distribution["collected_fee_cents"]
    )
    distribution["gross_pool_cents"] = gross_pool_cents

    bps, holdback_cents, net_pool_cents, member_pool_cents = holdback_for(
        contract, gross_pool_cents
    )
    distribution["holdback_bps_applied"] = bps
    distribution["holdback_cents"] = holdback_cents
    distribution["net_pool_cents"] = net_pool_cents
    distribution["member_pool_cents"] = member_pool_cents

    shares, share_total, undistributed = member_waterfall(contract, member_pool_cents)
    distribution["member_shares"] = shares
    distribution["member_share_total_cents"] = share_total
    distribution["undistributed_cents"] = undistributed
    distribution["gpo_retained_cents"] = gross_pool_cents - share_total - undistributed
    distribution["status"] = "DISTRIBUTED"
    db.touch(distribution)

    for entry in shares:
        member = db.members.get(entry["member_id"])
        if member is None:
            continue
        member["fee_credit_balance_cents"] = (
            member["fee_credit_balance_cents"] + entry["share_cents"]
        )
        db.touch(member)
    return object_response(distribution)


@fees_bp.route(
    "/gpo/admin-fee-distributions/<distribution_id>/reverse", methods=["POST"]
)
def reverse_distribution(distribution_id):
    authenticate((FINANCE_ADMINISTRATOR,))
    distribution = get_distribution(distribution_id)
    body = body_json()
    reason = field_string(body, "reason", 0, None, required=False, default=None)
    if distribution["status"] != "DISTRIBUTED":
        raise ApiError(
            "ERR_INVALID_DISTRIBUTION_STATE",
            "Only a DISTRIBUTED settlement can be reversed.",
        )
    # The credits are read back off the stored array, never re-derived.
    for entry in distribution["member_shares"]:
        member = db.members.get(entry["member_id"])
        if member is None:
            continue
        member["fee_credit_balance_cents"] = (
            member["fee_credit_balance_cents"] - entry["share_cents"]
        )
        db.touch(member)

    distribution["holdback_bps_applied"] = 0
    distribution["holdback_cents"] = 0
    distribution["net_pool_cents"] = 0
    distribution["member_pool_cents"] = 0
    distribution["member_share_total_cents"] = 0
    distribution["gpo_retained_cents"] = 0
    distribution["member_shares"] = []
    # The conservation identity stays true with the whole gross pool undistributed.
    distribution["undistributed_cents"] = distribution["gross_pool_cents"]
    distribution["reverse_note"] = reason
    distribution["status"] = "REVERSED"
    db.touch(distribution)
    return object_response(distribution)
