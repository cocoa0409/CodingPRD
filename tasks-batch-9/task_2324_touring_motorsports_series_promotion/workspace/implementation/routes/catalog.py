"""Seasons, venues, competitors, sponsors, the market report and the logical clock."""
from db import db, new_row, set_clock
from middleware import (
    ALL_ROLES,
    ROLE_COMPETITOR_TEAM,
    ROLE_FINANCE_CONTROLLER,
    ROLE_SAFETY_OFFICIAL,
    ROLE_SERIES_PROMOTER,
    ROLE_SPONSOR_REP,
    ROLE_TICKETING_MANAGER,
    ROLE_VENUE_MANAGER,
    auth,
)
from response import object_response
from services import calc, derive, serialize
import validate

FLOOR_TYPES = ("DIRT", "CONCRETE", "ASPHALT")
VEHICLE_CLASSES = ("LIGHT", "HEAVY")
SPONSOR_CATEGORIES = ("FUEL", "TIRE", "BEVERAGE", "RETAIL", "AUTOMOTIVE")


def register(app):
    # ----------------------------------------------------------------- seasons
    @app.route("/seasons", methods=["POST"])
    def create_season():
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        name = validate.field_string(payload, "name")
        year = validate.field_int(payload, "year")
        start_raw, _start = validate.field_date(payload, "season_start_date")
        end_raw, _end = validate.field_date(payload, "season_end_date")
        budget = validate.field_int(payload, "total_marketing_budget_cents", minimum=0)
        cooldown = validate.field_int(
            payload, "market_rotation_cooldown_days", required=False, default=21, minimum=0
        )
        row = new_row(
            name=name,
            year=year,
            season_start_date=start_raw,
            season_end_date=end_raw,
            market_rotation_cooldown_days=cooldown,
            total_marketing_budget_cents=budget,
            settled_stop_count=0,
            status="PLANNING",
        )
        db.seasons[row["id"]] = row
        return object_response(serialize.season(row), 201)

    @app.route("/seasons/<season_id>", methods=["GET"])
    def read_season(season_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_FINANCE_CONTROLLER, ROLE_TICKETING_MANAGER)
        row = derive.get_season(season_id)
        return object_response(serialize.season(row))

    @app.route("/seasons/<season_id>/market-report", methods=["GET"])
    def season_market_report(season_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_FINANCE_CONTROLLER)
        season = derive.get_season(season_id)
        stops = derive.stops_of_season(season["id"])
        buckets = {}
        for stop in stops:
            if stop["sales_state"] != "SETTLED":
                continue
            settlement = derive.settlement_of_stop(stop["id"])
            if settlement is None or settlement["state"] != "APPROVED":
                continue
            bucket = buckets.setdefault(
                stop["market_code"],
                {
                    "market_code": stop["market_code"],
                    "stop_count": 0,
                    "collected_cash_cents": 0,
                    "net_to_promoter_cents": 0,
                },
            )
            bucket["stop_count"] += 1
            bucket["collected_cash_cents"] += settlement["collected_cash_cents"]
            bucket["net_to_promoter_cents"] += settlement["net_to_promoter_cents"]

        rows = []
        for bucket in buckets.values():
            bucket["margin_pct"] = calc.margin_pct(
                bucket["net_to_promoter_cents"], bucket["collected_cash_cents"]
            )
            rows.append(bucket)
        rows.sort(key=lambda r: (-r["net_to_promoter_cents"], r["market_code"]))

        data = {
            "season_id": season["id"],
            "market_rows": rows,
            "total_net_cents": sum(r["net_to_promoter_cents"] for r in rows),
            "settled_stop_count": len([s for s in stops if s["sales_state"] == "SETTLED"]),
            "unsettled_stop_count": len(
                [s for s in stops if s["sales_state"] not in ("SETTLED", "CANCELLED")]
            ),
        }
        return object_response(data)

    # ------------------------------------------------------------------ venues
    @app.route("/venues", methods=["POST"])
    def create_venue():
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        row = new_row(
            name=validate.field_string(payload, "name"),
            market_code=validate.field_string(payload, "market_code"),
            city=validate.field_string(payload, "city"),
            state_code=validate.field_string(payload, "state_code"),
            seat_capacity=validate.field_int(payload, "seat_capacity", minimum=1),
            floor_type=validate.field_enum(payload, "floor_type", FLOOR_TYPES),
            catch_fence_max_height_ft=validate.field_int(
                payload, "catch_fence_max_height_ft", minimum=0
            ),
            medical_bay_count=validate.field_int(payload, "medical_bay_count", minimum=0),
            load_in_hours_required=validate.field_int(
                payload, "load_in_hours_required", minimum=0
            ),
            staging_bay_count=validate.field_int(payload, "staging_bay_count", minimum=0),
            turnaround_hours=validate.field_int(
                payload, "turnaround_hours", required=False, default=12, minimum=0
            ),
        )
        db.venues[row["id"]] = row
        return object_response(serialize.venue(row), 201)

    @app.route("/venues/<venue_id>", methods=["GET"])
    def read_venue(venue_id):
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_VENUE_MANAGER,
            ROLE_SAFETY_OFFICIAL,
            ROLE_FINANCE_CONTROLLER,
        )
        return object_response(serialize.venue(derive.get_venue(venue_id)))

    # ------------------------------------------------------------- competitors
    @app.route("/competitors", methods=["POST"])
    def create_competitor():
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        row = new_row(
            team_name=validate.field_string(payload, "team_name"),
            driver_name=validate.field_string(payload, "driver_name"),
            home_market_code=validate.field_string(payload, "home_market_code"),
            vehicle_class=validate.field_enum(payload, "vehicle_class", VEHICLE_CLASSES),
        )
        db.competitors[row["id"]] = row
        return object_response(serialize.competitor(row), 201)

    @app.route("/competitors/<competitor_id>", methods=["GET"])
    def read_competitor(competitor_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_COMPETITOR_TEAM, ROLE_SAFETY_OFFICIAL)
        return object_response(serialize.competitor(derive.get_competitor(competitor_id)))

    # ---------------------------------------------------------------- sponsors
    @app.route("/sponsors", methods=["POST"])
    def create_sponsor():
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        row = new_row(
            company_name=validate.field_string(payload, "company_name"),
            category=validate.field_enum(payload, "category", SPONSOR_CATEGORIES),
            contact_email=validate.field_string(payload, "contact_email"),
            exclusive_category=validate.field_bool(
                payload, "exclusive_category", default=False
            ),
        )
        db.sponsors[row["id"]] = row
        return object_response(serialize.sponsor(row), 201)

    @app.route("/sponsors/<sponsor_id>", methods=["GET"])
    def read_sponsor(sponsor_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_SPONSOR_REP, ROLE_FINANCE_CONTROLLER)
        return object_response(serialize.sponsor(derive.get_sponsor(sponsor_id)))

    # ------------------------------------------------------------ logical clock
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        auth(*ALL_ROLES)
        payload = validate.body()
        raw, parsed = validate.field_datetime(payload, "to_iso8601")
        set_clock(raw, parsed)
        return object_response({"current_utc": raw})
