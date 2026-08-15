"""Member endpoints."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    cascade_disenroll,
    get_member_or_404,
    mint_common_fields,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    apply_filters,
    as_enum,
    as_int_range,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

MEMBER_STATES = {"ENROLLED", "DISENROLLED"}


def register(app):
    @app.route("/api/members", methods=["POST"])
    def create_member():
        auth(["QualityOps"])
        data = body()
        member_ref = as_str(required(data, "member_ref"), "member_ref")
        plan_contract = as_str(required(data, "plan_contract"), "plan_contract")
        enrolled_months = as_int_range(
            required(data, "enrolled_months"), "enrolled_months", 1, 12
        )
        for m in DB["members"].values():
            if m["member_ref"] == member_ref:
                raise ApiError(
                    "ERR_DUPLICATE_MEMBER_REF",
                    409,
                    "member_ref already registered",
                )
        member = {
            "member_ref": member_ref,
            "plan_contract": plan_contract,
            "enrolled_months": enrolled_months,
            "status": "ENROLLED",
        }
        mint_common_fields(member)
        DB["members"][member["id"]] = member
        return ok(serialize(member), 201)

    @app.route("/api/members", methods=["GET"])
    def list_members():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["members"].values())
        rows = apply_filters(rows, [("status", filter_arg("status"))])
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/members/<memberId>", methods=["GET"])
    def get_member(memberId):
        auth(ALL_ROLES)
        member = get_member_or_404(memberId)
        return ok(serialize(member))

    @app.route("/api/members/<memberId>/transition", methods=["POST"])
    def transition_member(memberId):
        auth(["QualityOps"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", MEMBER_STATES)
        member = get_member_or_404(memberId)
        if (member["status"], to_state) != ("ENROLLED", "DISENROLLED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition Member from {member['status']} to {to_state}",
            )
        cascade_disenroll(member)
        member["status"] = "DISENROLLED"
        touch(member)
        return ok(serialize(member))
