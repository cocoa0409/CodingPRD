"""RatingForecast endpoints: run and persist a forecast + rebate snapshot."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    draft_set_for_cycle,
    get_cycle_or_404,
    get_forecast_or_404,
    improvement_stats,
    included_measures,
    member_months_pool,
    mint_common_fields,
    published_set_for_cycle,
    rebate_amount,
    rebate_tier_rate,
    serialize,
    sorted_rows,
    weighted_stars,
)
from util import (
    apply_filters,
    as_enum,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

BASES = {"PUBLISHED_CUTPOINTS", "DRAFT_CUTPOINTS"}
FORECAST_FILTER = {"VALIDATED", "LOCKED"}


def register(app):
    @app.route("/api/rating-forecasts", methods=["POST"])
    def create_forecast():
        auth(["StarsAnalyst"])
        data = body()
        rating_cycle_id = as_str(required(data, "rating_cycle_id"), "rating_cycle_id")
        basis = as_enum(required(data, "basis"), "basis", BASES)

        cycle = get_cycle_or_404(rating_cycle_id)
        if basis == "PUBLISHED_CUTPOINTS":
            if published_set_for_cycle(cycle) is None:
                raise ApiError(
                    "ERR_NO_PUBLISHED_CUTPOINT_SET",
                    409,
                    "Published-basis forecast requires a PUBLISHED cut point set",
                )
            basis_field = "published_star"
        else:
            if draft_set_for_cycle(cycle["id"]) is None:
                raise ApiError(
                    "ERR_NO_DRAFT_CUTPOINT_SET",
                    409,
                    "Draft-basis forecast requires at least one DRAFT cut point set",
                )
            basis_field = "draft_star"

        included = included_measures(cycle, basis_field, FORECAST_FILTER)
        imp = improvement_stats(cycle, basis_field, FORECAST_FILTER)
        projected = weighted_stars(cycle, basis_field, FORECAST_FILTER)
        member_months = member_months_pool()
        tier = rebate_tier_rate(projected)
        rebate = rebate_amount(member_months, cycle["benchmark_pmpm"], projected)

        forecast = {
            "rating_cycle_id": cycle["id"],
            "basis": basis,
            "measures_included": len(included),
            "measures_improved": imp["improved"],
            "measures_declined": imp["declined"],
            "measures_eligible": imp["eligible"],
            "improvement_score": imp["score"],
            "improvement_star": imp["star"],
            "projected_overall_stars": projected,
            "member_months_used": member_months,
            "rebate_tier_rate": tier,
            "projected_rebate_amount": rebate,
        }
        mint_common_fields(forecast)
        DB["rating_forecasts"][forecast["id"]] = forecast
        return ok(serialize(forecast), 201)

    @app.route("/api/rating-forecasts", methods=["GET"])
    def list_forecasts():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["rating_forecasts"].values())
        rows = apply_filters(
            rows,
            [
                ("rating_cycle_id", filter_arg("rating_cycle_id")),
                ("basis", filter_arg("basis")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/rating-forecasts/<forecastId>", methods=["GET"])
    def get_forecast(forecastId):
        auth(ALL_ROLES)
        forecast = get_forecast_or_404(forecastId)
        return ok(serialize(forecast))
