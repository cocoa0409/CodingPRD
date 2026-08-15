"""MeasurePerformance endpoints."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    get_cycle_or_404,
    get_measure_or_404,
    get_perf_or_404,
    mint_common_fields,
    perf_for_measure,
    recompute_performance,
    refresh_live_stars,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    apply_filters,
    as_enum,
    as_non_negative_int,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

PERF_STATES = {"REPORTED", "VALIDATED", "LOCKED"}

LEGAL_TRANSITIONS = {("REPORTED", "VALIDATED"), ("VALIDATED", "LOCKED")}


def register(app):
    @app.route("/api/measure-performances", methods=["POST"])
    def create_perf():
        user_id, _ = auth(["QualityOps"])
        data = body()
        rating_cycle_id = as_str(required(data, "rating_cycle_id"), "rating_cycle_id")
        measure_id = as_str(required(data, "measure_id"), "measure_id")
        numerator = as_non_negative_int(required(data, "numerator"), "numerator")
        denominator = as_non_negative_int(required(data, "denominator"), "denominator")
        exclusion_count = data.get("exclusion_count", 0)
        exclusion_count = as_non_negative_int(exclusion_count, "exclusion_count")
        if numerator > denominator:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "numerator must not exceed denominator"
            )

        cycle = get_cycle_or_404(rating_cycle_id)
        measure = get_measure_or_404(measure_id)
        if measure["rating_cycle_id"] != cycle["id"]:
            raise ApiError(
                "ERR_MEASURE_CYCLE_MISMATCH",
                409,
                "Performance measure does not belong to the given cycle",
            )
        if perf_for_measure(measure_id) is not None:
            raise ApiError(
                "ERR_DUPLICATE_PERFORMANCE",
                409,
                "A performance already exists for (measure, cycle)",
            )
        perf = {
            "rating_cycle_id": cycle["id"],
            "measure_id": measure_id,
            "numerator": numerator,
            "denominator": denominator,
            "exclusion_count": exclusion_count,
            "raw_value": None,
            "published_star": None,
            "draft_star": None,
            "timeliness_alert": False,
            "reported_by_user_id": user_id,
            "status": "REPORTED",
        }
        mint_common_fields(perf)
        DB["measure_performances"][perf["id"]] = perf
        recompute_performance(perf)
        return ok(serialize(perf), 201)

    @app.route("/api/measure-performances", methods=["GET"])
    def list_perfs():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["measure_performances"].values())
        rows = apply_filters(
            rows,
            [
                ("rating_cycle_id", filter_arg("rating_cycle_id")),
                ("measure_id", filter_arg("measure_id")),
                ("status", filter_arg("status")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/measure-performances/<perfId>", methods=["GET"])
    def get_perf(perfId):
        auth(ALL_ROLES)
        perf = get_perf_or_404(perfId)
        return ok(serialize(perf))

    @app.route("/api/measure-performances/<perfId>", methods=["PUT"])
    def correct_perf(perfId):
        auth(["QualityOps"])
        data = body()
        numerator = data.get("numerator")
        denominator = data.get("denominator")
        exclusion_count = data.get("exclusion_count")
        if numerator is not None:
            numerator = as_non_negative_int(numerator, "numerator")
        if denominator is not None:
            denominator = as_non_negative_int(denominator, "denominator")
        if exclusion_count is not None:
            exclusion_count = as_non_negative_int(exclusion_count, "exclusion_count")

        perf = get_perf_or_404(perfId)
        # Correction is only allowed while REPORTED.
        if perf["status"] == "LOCKED":
            raise ApiError(
                "ERR_PERFORMANCE_LOCKED",
                409,
                "Linked performance is LOCKED; numerator/denominator mutations "
                "forbidden",
            )
        if perf["status"] != "REPORTED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                "Performance corrections are only allowed while REPORTED",
            )
        eff_num = numerator if numerator is not None else perf["numerator"]
        eff_den = denominator if denominator is not None else perf["denominator"]
        if eff_num > eff_den:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "numerator must not exceed denominator"
            )
        if numerator is not None:
            perf["numerator"] = numerator
        if denominator is not None:
            perf["denominator"] = denominator
        if exclusion_count is not None:
            perf["exclusion_count"] = exclusion_count
        touch(perf)
        recompute_performance(perf)
        return ok(serialize(perf))

    @app.route("/api/measure-performances/<perfId>/transition", methods=["POST"])
    def transition_perf(perfId):
        auth(["StarsAnalyst"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", PERF_STATES)
        perf = get_perf_or_404(perfId)
        cur = perf["status"]
        if (cur, to_state) not in LEGAL_TRANSITIONS:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition MeasurePerformance from {cur} to {to_state}",
            )
        perf["status"] = to_state
        touch(perf)
        if to_state == "LOCKED":
            # LOCKED performances enter every weighted input set.
            cycle = get_cycle_or_404(perf["rating_cycle_id"])
            refresh_live_stars(cycle)
        return ok(serialize(perf))
