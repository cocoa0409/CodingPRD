"""RatingCycle endpoints."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    get_cycle_or_404,
    improvement_stats,
    member_months_pool,
    mint_common_fields,
    perfs_of_cycle,
    published_set_for_cycle,
    rebate_amount,
    serialize,
    sorted_rows,
    touch,
    weighted_stars,
)
from util import (
    apply_filters,
    as_enum,
    as_int,
    as_positive_num,
    body,
    filter_arg,
    pagination_args,
    required,
)

CYCLE_STATES = {"SETUP", "DATA_COLLECTION", "CUTPOINT_REVIEW", "OFFICIAL_PUBLISHED", "CLOSED"}

LEGAL_TRANSITIONS = {
    ("SETUP", "DATA_COLLECTION"),
    ("DATA_COLLECTION", "CUTPOINT_REVIEW"),
    ("CUTPOINT_REVIEW", "DATA_COLLECTION"),
    ("CUTPOINT_REVIEW", "OFFICIAL_PUBLISHED"),
    ("OFFICIAL_PUBLISHED", "CLOSED"),
}


def register(app):
    @app.route("/api/rating-cycles", methods=["POST"])
    def create_cycle():
        auth(["StarsAdmin"])
        data = body()
        measurement_year = as_int(required(data, "measurement_year"), "measurement_year")
        rating_year = as_int(required(data, "rating_year"), "rating_year")
        benchmark_pmpm = as_positive_num(
            required(data, "benchmark_pmpm"), "benchmark_pmpm"
        )
        if rating_year <= measurement_year:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "rating_year must be strictly greater than measurement_year",
            )
        cycle = {
            "measurement_year": measurement_year,
            "rating_year": rating_year,
            "benchmark_pmpm": benchmark_pmpm,
            "status": "SETUP",
            "published_cutpoint_set_id": None,
            "live_weighted_stars": None,
            "official_overall_stars": None,
            "official_rebate_amount": None,
            "official_improvement_star": None,
        }
        mint_common_fields(cycle)
        DB["rating_cycles"][cycle["id"]] = cycle
        return ok(serialize(cycle), 201)

    @app.route("/api/rating-cycles", methods=["GET"])
    def list_cycles():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["rating_cycles"].values())
        rows = apply_filters(rows, [("status", filter_arg("status"))])
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/rating-cycles/<cycleId>", methods=["GET"])
    def get_cycle(cycleId):
        auth(ALL_ROLES)
        cycle = get_cycle_or_404(cycleId)
        return ok(serialize(cycle))

    @app.route("/api/rating-cycles/<cycleId>/transition", methods=["POST"])
    def transition_cycle(cycleId):
        auth(["StarsAdmin"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", CYCLE_STATES)
        cycle = get_cycle_or_404(cycleId)
        cur = cycle["status"]
        if (cur, to_state) not in LEGAL_TRANSITIONS:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition RatingCycle from {cur} to {to_state}",
            )
        if to_state == "CUTPOINT_REVIEW":
            perfs = perfs_of_cycle(cycle["id"])
            if any(p["status"] != "LOCKED" for p in perfs):
                raise ApiError(
                    "ERR_PERFORMANCES_NOT_LOCKED",
                    409,
                    "Cycle cannot enter CUTPOINT_REVIEW while any performance "
                    "is REPORTED or VALIDATED",
                )
        if to_state == "OFFICIAL_PUBLISHED":
            if published_set_for_cycle(cycle) is None:
                raise ApiError(
                    "ERR_NO_PUBLISHED_CUTPOINT_SET",
                    409,
                    "Publish-official requires a PUBLISHED cut point set",
                )
            banded = [
                p
                for p in perfs_of_cycle(cycle["id"])
                if p["status"] == "LOCKED" and p.get("published_star") is not None
            ]
            if not banded:
                raise ApiError(
                    "ERR_NO_BANDED_PERFORMANCES",
                    409,
                    "Publish-official requires at least one LOCKED performance "
                    "with non-null published_star",
                )
        # Side effects
        if cur == "CUTPOINT_REVIEW" and to_state == "DATA_COLLECTION":
            # Reopen leg: every LOCKED performance reverts to VALIDATED (+1 each).
            for p in perfs_of_cycle(cycle["id"]):
                if p["status"] == "LOCKED":
                    p["status"] = "VALIDATED"
                    touch(p)
        if to_state == "OFFICIAL_PUBLISHED":
            imp = improvement_stats(cycle, "published_star", {"LOCKED"})
            cycle["official_improvement_star"] = imp["star"]
            cycle["official_overall_stars"] = weighted_stars(
                cycle, "published_star", {"LOCKED"}
            )
            cycle["official_rebate_amount"] = rebate_amount(
                member_months_pool(),
                cycle["benchmark_pmpm"],
                cycle["official_overall_stars"],
            )
        cycle["status"] = to_state
        touch(cycle)
        return ok(serialize(cycle))
