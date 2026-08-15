"""ProviderGroup endpoints."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    get_group_or_404,
    get_measure_or_404,
    mint_common_fields,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    apply_filters,
    as_enum,
    as_int_range,
    as_non_negative_num,
    as_positive_num,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

PROGRAM_TYPES = {"ATTAINMENT", "GAP_CLOSURE"}
GROUP_STATES = {"ACTIVE", "CLOSED"}


def register(app):
    @app.route("/api/provider-groups", methods=["POST"])
    def create_group():
        auth(["IncentiveManager"])
        data = body()
        name = as_str(required(data, "name"), "name")
        program_type = as_enum(
            required(data, "program_type"), "program_type", PROGRAM_TYPES
        )
        linked_measure_id = as_str(
            required(data, "linked_measure_id"), "linked_measure_id"
        )
        target_star = as_int_range(required(data, "target_star"), "target_star", 1, 5)
        unit_reward_per_gap = as_positive_num(
            required(data, "unit_reward_per_gap"), "unit_reward_per_gap"
        )
        max_pool_amount = as_non_negative_num(
            required(data, "max_pool_amount"), "max_pool_amount"
        )

        measure = get_measure_or_404(linked_measure_id)
        for g in DB["provider_groups"].values():
            if g["name"] == name:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 409, "Provider group name must be unique"
                )
        group = {
            "name": name,
            "program_type": program_type,
            "linked_measure_id": measure["id"],
            "target_star": target_star,
            "unit_reward_per_gap": unit_reward_per_gap,
            "max_pool_amount": max_pool_amount,
            "paid_total": 0,
            "reserved_total": 0,
            "remaining_amount": max_pool_amount,
            "status": "ACTIVE",
        }
        mint_common_fields(group)
        DB["provider_groups"][group["id"]] = group
        return ok(serialize(group), 201)

    @app.route("/api/provider-groups", methods=["GET"])
    def list_groups():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["provider_groups"].values())
        rows = apply_filters(
            rows,
            [
                ("status", filter_arg("status")),
                ("program_type", filter_arg("program_type")),
                ("linked_measure_id", filter_arg("linked_measure_id")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/provider-groups/<groupId>", methods=["GET"])
    def get_group(groupId):
        auth(ALL_ROLES)
        group = get_group_or_404(groupId)
        return ok(serialize(group))

    @app.route("/api/provider-groups/<groupId>/transition", methods=["POST"])
    def transition_group(groupId):
        auth(["IncentiveManager"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", GROUP_STATES)
        group = get_group_or_404(groupId)
        if (group["status"], to_state) != ("ACTIVE", "CLOSED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition ProviderGroup from {group['status']} to "
                f"{to_state}",
            )
        for p in DB["incentive_payouts"].values():
            if p["provider_group_id"] == group["id"] and p["status"] in (
                "PENDING",
                "APPROVED",
            ):
                raise ApiError(
                    "ERR_GROUP_HAS_OPEN_PAYOUTS",
                    409,
                    "Group close forbidden while PENDING or APPROVED payouts "
                    "exist",
                )
        group["status"] = "CLOSED"
        touch(group)
        return ok(serialize(group))
