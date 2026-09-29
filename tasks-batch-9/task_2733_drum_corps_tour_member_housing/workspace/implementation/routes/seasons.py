from flask import Blueprint

import find
import serialize
import services
import validators as v
from auth import endpoint
from envelope import object_response
from store import db, new_record

bp = Blueprint("seasons", __name__)

READ_ROLES = ["CorpsDirector", "MembershipCoordinator", "TourManager", "BusinessManager"]


@bp.route("/seasons", methods=["POST"])
@endpoint(["CorpsDirector"])
def create_season():
    body = v.get_body()
    name = v.req_str(body, "name")
    year = v.req_int(body, "year")
    tuition_base_cents = v.req_int(body, "tuition_base_cents")
    start_raw, start = v.req_date(body, "spring_training_start_date")
    end_raw, end = v.req_date(body, "spring_training_end_date")
    departure_raw, departure = v.req_date(body, "tour_departure_date")
    v.check(2020 <= year <= 2100, "year", "must be between 2020 and 2100")
    v.check(tuition_base_cents >= 0, "tuition_base_cents", "must be at least 0")
    # Rung 4 -- ordered date pairs are strictly increasing.
    v.date_range(end > start,
                 "spring_training_end_date must be later than spring_training_start_date.")
    v.date_range(departure > start,
                 "tour_departure_date must be later than spring_training_start_date.")

    record = new_record()
    record.update({
        "name": name,
        "year": year,
        "tuition_base_cents": tuition_base_cents,
        "spring_training_start_date": start_raw,
        "spring_training_end_date": end_raw,
        "tour_departure_date": departure_raw,
        "_spring_training_start_date": start,
        "_spring_training_end_date": end,
        "_tour_departure_date": departure,
        "billing_epoch": 0,
        "tuition_charged_cents": 0,
        "tuition_collected_cents": 0,
        "late_fee_collected_cents": 0,
        "housing_cost_cents": 0,
        "tour_revenue_cents": 0,
        "ledger_status": "OPEN",
    })
    db.seasons[record["id"]] = record
    return object_response(serialize.season(record), 201)


@bp.route("/seasons/<season_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_season(season_id):
    return object_response(serialize.season(find.season(season_id)))


@bp.route("/seasons/<season_id>/run-billing-cycle", methods=["POST"])
@endpoint(["BusinessManager"])
def run_billing_cycle(season_id):
    season = find.season(season_id)
    services.run_billing_cycle(season)
    return object_response(serialize.season(season))
