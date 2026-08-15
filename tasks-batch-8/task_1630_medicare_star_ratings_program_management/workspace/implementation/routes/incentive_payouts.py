"""IncentivePayout endpoints: propose (amount by variant), approve/pay/deny."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    compute_payout_amount,
    get_group_or_404,
    get_payout_or_404,
    mint_common_fields,
    pool_move,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    D,
    apply_filters,
    as_enum,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

PAYOUT_STATES = {"PENDING", "APPROVED", "PAID", "DENIED"}


def register(app):
    @app.route("/api/incentive-payouts", methods=["POST"])
    def propose_payout():
        user_id, _ = auth(["IncentiveManager"])
        data = body()
        provider_group_id = as_str(
            required(data, "provider_group_id"), "provider_group_id"
        )
        group = get_group_or_404(provider_group_id)
        if group["status"] != "ACTIVE":
            raise ApiError(
                "ERR_GROUP_NOT_ACTIVE",
                409,
                "Payout propose requires provider group ACTIVE",
            )
        amount, snapshot = compute_payout_amount(group)
        # Fiscal gate: computed amount must fit the remaining pool.
        if D(str(amount)) > D(str(group["remaining_amount"])):
            raise ApiError(
                "ERR_INCENTIVE_POOL_EXCEEDED",
                402,
                "Computed payout amount exceeds group.remaining_amount",
            )
        payout = {
            "provider_group_id": group["id"],
            "amount": amount,
            "basis_snapshot": snapshot,
            "proposed_by_user_id": user_id,
            "status": "PENDING",
        }
        mint_common_fields(payout)
        DB["incentive_payouts"][payout["id"]] = payout
        # Move the amount into reserve at propose time.
        pool_move(group, reserved_delta=amount, remaining_delta=-amount)
        touch(group)
        return ok(serialize(payout), 201)

    @app.route("/api/incentive-payouts", methods=["GET"])
    def list_payouts():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["incentive_payouts"].values())
        rows = apply_filters(
            rows,
            [
                ("provider_group_id", filter_arg("provider_group_id")),
                ("status", filter_arg("status")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/incentive-payouts/<payoutId>", methods=["GET"])
    def get_payout(payoutId):
        auth(ALL_ROLES)
        payout = get_payout_or_404(payoutId)
        return ok(serialize(payout))

    @app.route("/api/incentive-payouts/<payoutId>/transition", methods=["POST"])
    def transition_payout(payoutId):
        user_id, _ = auth(["IncentiveManager"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", PAYOUT_STATES)
        payout = get_payout_or_404(payoutId)
        cur = payout["status"]

        if to_state == "APPROVED":
            if cur != "PENDING":
                raise ApiError(
                    "ERR_PAYOUT_NOT_PENDING",
                    409,
                    "Approve requires payout PENDING",
                )
            if user_id == payout["proposed_by_user_id"]:
                raise ApiError(
                    "ERR_SOD_VIOLATION",
                    403,
                    "Approver X-User-ID must differ from the proposer",
                )
            # Pool fields unchanged: the amount was reserved at propose time.
        elif to_state == "PAID":
            if cur != "APPROVED":
                raise ApiError(
                    "ERR_PAYOUT_NOT_APPROVED", 409, "Pay requires payout APPROVED"
                )
            group = get_group_or_404(payout["provider_group_id"])
            pool_move(
                group, paid_delta=payout["amount"], reserved_delta=-payout["amount"]
            )
            touch(group)
        elif to_state == "DENIED":
            if cur != "PENDING":
                raise ApiError(
                    "ERR_PAYOUT_NOT_PENDING", 409, "Deny requires payout PENDING"
                )
            group = get_group_or_404(payout["provider_group_id"])
            # Compensation: unwind the reservation.
            pool_move(
                group,
                reserved_delta=-payout["amount"],
                remaining_delta=payout["amount"],
            )
            touch(group)
        else:  # PENDING: no transition targets PENDING
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition IncentivePayout from {cur} to {to_state}",
            )
        payout["status"] = to_state
        touch(payout)
        return ok(serialize(payout))
