"""ComplaintCase endpoints: file and resolve (valid/invalid branches)."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    complaints_perf_for_cycle,
    compute_late_resolution,
    get_case_or_404,
    get_cycle_or_404,
    get_member_or_404,
    mint_common_fields,
    recompute_performance,
    refresh,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    apply_filters,
    as_enum,
    as_iso_dt,
    as_str,
    body,
    filter_arg,
    format_iso,
    logical_now_dt,
    pagination_args,
    required,
)

CATEGORIES = {
    "APPEALS_TIMELINESS",
    "COVERAGE_DETERMINATION",
    "BILLING",
    "ENROLLMENT",
    "SERVICE_QUALITY",
}
CASE_STATES = {"FILED", "RESOLVED_VALID", "RESOLVED_INVALID"}


def register(app):
    @app.route("/api/complaint-cases", methods=["POST"])
    def create_case():
        auth(["ComplaintsAuditor"])
        data = body()
        rating_cycle_id = as_str(required(data, "rating_cycle_id"), "rating_cycle_id")
        member_id = as_str(required(data, "member_id"), "member_id")
        category = as_enum(required(data, "category"), "category", CATEGORIES)
        filed_at = as_iso_dt(required(data, "filed_at"), "filed_at")

        cycle = get_cycle_or_404(rating_cycle_id)
        member = get_member_or_404(member_id)
        case = {
            "rating_cycle_id": cycle["id"],
            "member_id": member["id"],
            "category": category,
            "filed_at": filed_at,
            "resolved_at": None,
            "late_resolution": None,
            "status": "FILED",
        }
        mint_common_fields(case)
        DB["complaint_cases"][case["id"]] = case
        return ok(serialize(case), 201)

    @app.route("/api/complaint-cases", methods=["GET"])
    def list_cases():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["complaint_cases"].values())
        rows = apply_filters(
            rows,
            [
                ("rating_cycle_id", filter_arg("rating_cycle_id")),
                ("member_id", filter_arg("member_id")),
                ("status", filter_arg("status")),
                ("category", filter_arg("category")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/complaint-cases/<caseId>", methods=["GET"])
    def get_case(caseId):
        auth(ALL_ROLES)
        case = get_case_or_404(caseId)
        return ok(serialize(case))

    @app.route("/api/complaint-cases/<caseId>/transition", methods=["POST"])
    def transition_case(caseId):
        auth(["ComplaintsAuditor"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", CASE_STATES)
        case = get_case_or_404(caseId)
        if case["status"] != "FILED" or to_state not in (
            "RESOLVED_VALID",
            "RESOLVED_INVALID",
        ):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition ComplaintCase from {case['status']} to "
                f"{to_state}",
            )
        now_dt = logical_now_dt()
        case["resolved_at"] = format_iso(now_dt)
        case["late_resolution"] = compute_late_resolution(case["filed_at"], now_dt)

        perf = complaints_perf_for_cycle(case["rating_cycle_id"])
        if to_state == "RESOLVED_VALID" and perf is not None:
            # Branch A: credit the complaints measure unless LOCKED.
            if perf["status"] != "LOCKED":
                perf["numerator"] += 1
                recompute_performance(perf)
        # Timeliness alert raises on either resolution branch when late and the
        # complaints-source performance exists (sticky, never auto-cleared).
        if case["late_resolution"] and perf is not None:
            perf["timeliness_alert"] = True
            refresh(perf)
        case["status"] = to_state
        touch(case)
        return ok(serialize(case))
