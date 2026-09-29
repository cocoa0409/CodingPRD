"""Logical clock, stations (incl. analytics), apparatus and hiring rosters."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import created_object, ok_list, ok_object, ok_raw
from errors import ApiError
from flask import Blueprint, request
from store import db

bp = Blueprint("master", __name__)


# ------------------------------------------------------------- logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(ALL_ROLES)
    body = V.parse_body()
    data = V.validate(body, [V.spec("now", "datetime")])
    db.set_clock(data["now"])
    return ok_raw({"now": db.now_iso()})


# ------------------------------------------------------------------ stations
@bp.route("/fire-ops/stations", methods=["POST"])
def create_station():
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("name", "string"),
            V.spec("battalion_code", "string"),
            V.spec("minimum_staffing_floor", "integer", minimum=0),
            V.spec("fiscal_ot_budget_cents", "integer", minimum=0),
            V.spec("fiscal_period_start_date", "date"),
            V.spec("fiscal_period_end_date", "date"),
        ],
    )
    if data["fiscal_period_end_date"] < data["fiscal_period_start_date"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "fiscal_period_end_date must be on or after fiscal_period_start_date.",
        )
    station = db.new(
        {
            "name": data["name"],
            "battalion_code": data["battalion_code"],
            "minimum_staffing_floor": data["minimum_staffing_floor"],
            "fiscal_ot_budget_cents": data["fiscal_ot_budget_cents"],
            "fiscal_period_start_date": data["fiscal_period_start_date"],
            "fiscal_period_end_date": data["fiscal_period_end_date"],
            "ot_committed_cents": 0,
            "ot_actual_cents": 0,
            "budget_posture": calc.budget_posture(0, 0, data["fiscal_ot_budget_cents"]),
        }
    )
    db.stations[station["id"]] = station
    return created_object(station)


@bp.route("/fire-ops/stations/<station_id>", methods=["GET"])
def get_station(station_id):
    authenticate(ALL_ROLES)
    station = domain.require(db.stations, station_id, "ERR_STATION_NOT_FOUND")
    return ok_object(station)


@bp.route("/fire-ops/stations", methods=["GET"])
def list_stations():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.stations.values())
    items = apply_filters(
        items, {"battalion_code": f("battalion_code"), "budget_posture": f("budget_posture")}
    )
    items = sorted_by(items, lambda e: (e["battalion_code"], e["name"]))
    return ok_list(items)


def _station_vacancies(station_id, statuses):
    out = []
    for vacancy in db.vacancies.values():
        if vacancy["status"] not in statuses:
            continue
        shift = db.duty_shifts.get(vacancy["duty_shift_id"])
        if shift is None or shift["station_id"] != station_id:
            continue
        out.append((vacancy, shift))
    return out


@bp.route("/fire-ops/stations/<station_id>/overtime-forecast", methods=["GET"])
def overtime_forecast(station_id):
    authenticate(("StaffingOfficer", "PayrollAnalyst"))
    station = domain.require(db.stations, station_id, "ERR_STATION_NOT_FOUND")
    method = request.args.get("method") or "VACANCY_DRIVEN"
    if method not in V.FORECAST_METHODS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "method must be one of %s." % ", ".join(V.FORECAST_METHODS),
        )

    pool = [
        m
        for m in db.firefighters.values()
        if m["station_id"] == station_id and m["employment_status"] != "SEPARATED"
    ]
    if pool:
        total = sum(int(m["hourly_rate_cents"]) for m in pool)
        avg_rate_cents = calc.rhu(calc.dec(total) / calc.dec(len(pool)))
    else:
        avg_rate_cents = 0
    shift_base_cents = calc.rhu(
        calc.dec(avg_rate_cents) * calc.dec(calc.SHIFT_HOURS) * calc.OT_MULTIPLIER_VOLUNTARY
    )

    horizon_vacancy_count = 0
    vacancy_driver_cents = 0
    injury_headcount = 0
    injury_driver_cents = 0
    daily_run_rate_cents = 0
    remaining_days = 0

    today = calc.date_str(db.today())
    if method == "VACANCY_DRIVEN":
        for vacancy, shift in _station_vacancies(station_id, ("OPEN", "OFFERING")):
            if shift["shift_date"] < today:
                continue
            if shift["shift_date"] > station["fiscal_period_end_date"]:
                continue
            horizon_vacancy_count += 1
            pct = calc.CERT_PREMIUM_PCT.get(vacancy["required_certification"], 0)
            vacancy_driver_cents += calc.rhu(
                calc.dec(shift_base_cents) * calc.dec(100 + pct) / calc.dec(100)
            )
        injury_headcount = len(
            [m for m in pool if m["employment_status"] == "INJURY_LEAVE"]
        )
        injury_driver_cents = (
            injury_headcount * calc.INJURY_SHIFTS_PER_PERIOD * shift_base_cents
        )
        forecast_cents = vacancy_driver_cents + injury_driver_cents
    else:
        elapsed = calc.date_diff_days(today, station["fiscal_period_start_date"]) + 1
        remaining_days = max(
            0, calc.date_diff_days(station["fiscal_period_end_date"], today)
        )
        if elapsed > 0:
            daily_run_rate_cents = calc.rhu(
                calc.dec(station["ot_actual_cents"]) / calc.dec(elapsed)
            )
        forecast_cents = daily_run_rate_cents * remaining_days

    projected_total = (
        int(station["ot_actual_cents"]) + int(station["ot_committed_cents"]) + forecast_cents
    )
    variance = int(station["fiscal_ot_budget_cents"]) - projected_total
    return ok_raw(
        {
            "station_id": station_id,
            "method": method,
            "avg_rate_cents": avg_rate_cents,
            "shift_base_cents": shift_base_cents,
            "horizon_vacancy_count": horizon_vacancy_count,
            "vacancy_driver_cents": vacancy_driver_cents,
            "injury_headcount": injury_headcount,
            "injury_driver_cents": injury_driver_cents,
            "daily_run_rate_cents": daily_run_rate_cents,
            "remaining_days": remaining_days,
            "forecast_cents": forecast_cents,
            "projected_period_total_cents": projected_total,
            "variance_cents": variance,
            "forecast_posture": "WITHIN" if variance >= 0 else "OVER",
        }
    )


@bp.route("/fire-ops/stations/<station_id>/academy-hiring-signal", methods=["GET"])
def academy_hiring_signal(station_id):
    authenticate(("StaffingOfficer", "PayrollAnalyst"))
    domain.require(db.stations, station_id, "ERR_STATION_NOT_FOUND")
    open_vacancy_seats = len(_station_vacancies(station_id, ("OPEN", "OFFERING")))
    injury_headcount = len(
        [
            m
            for m in db.firefighters.values()
            if m["station_id"] == station_id and m["employment_status"] == "INJURY_LEAVE"
        ]
    )
    raw_need, recommended, tier = calc.academy_signal(open_vacancy_seats, injury_headcount)
    return ok_raw(
        {
            "station_id": station_id,
            "open_vacancy_seats": open_vacancy_seats,
            "injury_headcount": injury_headcount,
            "raw_need": raw_need,
            "recommended_recruit_count": recommended,
            "signal_tier": tier,
        }
    )


# ----------------------------------------------------------------- apparatus
@bp.route("/fire-ops/apparatus", methods=["POST"])
def create_apparatus():
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("station_id", "id"),
            V.spec("unit_designation", "string"),
            V.spec("apparatus_type", "enum", values=V.APPARATUS_TYPES),
            V.spec("minimum_crew_size", "integer", minimum=1, maximum=8),
            V.spec(
                "required_certifications",
                "array_enum",
                required=False,
                values=V.CERTIFICATIONS,
                default=[],
            ),
            V.spec("closure_priority", "integer", minimum=0),
            V.spec("closure_exempt", "boolean", required=False, default=False),
            V.spec("status", "enum", required=False, values=V.APPARATUS_STATUSES,
                   default="IN_SERVICE"),
        ],
    )
    certs = list(data["required_certifications"] or [])
    if len(certs) > data["minimum_crew_size"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "required_certifications may not be longer than minimum_crew_size.",
        )
    domain.require(db.stations, data["station_id"], "ERR_STATION_NOT_FOUND")
    for unit in db.apparatus.values():
        if (
            unit["station_id"] == data["station_id"]
            and unit["unit_designation"] == data["unit_designation"]
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "unit_designation must be unique within the station.",
            )
    unit = db.new(
        {
            "station_id": data["station_id"],
            "unit_designation": data["unit_designation"],
            "apparatus_type": data["apparatus_type"],
            "minimum_crew_size": data["minimum_crew_size"],
            "required_certifications": certs,
            "closure_priority": data["closure_priority"],
            "closure_exempt": bool(data["closure_exempt"]),
            "status": data["status"] or "IN_SERVICE",
        }
    )
    db.apparatus[unit["id"]] = unit
    return created_object(unit)


@bp.route("/fire-ops/apparatus/<apparatus_id>", methods=["GET"])
def get_apparatus(apparatus_id):
    authenticate(ALL_ROLES)
    unit = domain.require(db.apparatus, apparatus_id, "ERR_RESOURCE_NOT_FOUND")
    return ok_object(unit)


@bp.route("/fire-ops/apparatus", methods=["GET"])
def list_apparatus():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.apparatus.values())
    items = apply_filters(
        items,
        {
            "station_id": f("station_id"),
            "apparatus_type": f("apparatus_type"),
            "status": f("status"),
        },
    )
    items = sorted_by(items, lambda e: (e["closure_priority"], e["unit_designation"]))
    return ok_list(items)


# -------------------------------------------------------------- hiring roster
@bp.route("/fire-ops/hiring-rosters", methods=["POST"])
def create_roster():
    authenticate(("StaffingOfficer",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("station_id", "id"),
            V.spec("roster_type", "enum", values=V.ROSTER_TYPES),
            V.spec("certification_scope", "enum", required=False,
                   values=V.SEAT_CERTIFICATIONS, default="NONE"),
        ],
    )
    domain.require(db.stations, data["station_id"], "ERR_STATION_NOT_FOUND")
    scope = data["certification_scope"] or "NONE"
    for roster in db.hiring_rosters.values():
        if (
            roster["station_id"] == data["station_id"]
            and roster["roster_type"] == data["roster_type"]
            and roster["certification_scope"] == scope
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "A roster already exists for this station, type and certification scope.",
            )
    roster = db.new(
        {
            "station_id": data["station_id"],
            "roster_type": data["roster_type"],
            "certification_scope": scope,
            "dispatch_count": 0,
        }
    )
    db.hiring_rosters[roster["id"]] = roster
    return created_object(roster)


@bp.route("/fire-ops/hiring-rosters/<hiring_roster_id>", methods=["GET"])
def get_roster(hiring_roster_id):
    authenticate(ALL_ROLES)
    roster = domain.require(db.hiring_rosters, hiring_roster_id, "ERR_RESOURCE_NOT_FOUND")
    return ok_object(roster)


@bp.route("/fire-ops/hiring-rosters", methods=["GET"])
def list_rosters():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, sorted_by

    items = list(db.hiring_rosters.values())
    items = apply_filters(
        items,
        {
            "station_id": f("station_id"),
            "roster_type": f("roster_type"),
            "certification_scope": f("certification_scope"),
        },
    )
    items = sorted_by(items, lambda e: (e["roster_type"], e["certification_scope"]))
    return ok_list(items)
