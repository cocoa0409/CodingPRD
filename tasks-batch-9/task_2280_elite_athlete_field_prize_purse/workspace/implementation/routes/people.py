"""Athletes, representation agents and performance records (PRD 3.2)."""
from flask import Blueprint

from clock import parse_date
from constants import AGENT_STATUSES, DIVISIONS, GENDERS, VERIFICATION_STATUSES
from db import db, new_record, touch
from errors import err
from middleware import authenticate
from response import list_response, object_response, paginate
from services import lookup, serializers
from validators import (
    enum_filter,
    get_body,
    obool,
    oint,
    ostr,
    pagination_args,
    present,
    renum,
    rint,
    rstr,
)

bp = Blueprint("people", __name__)


@bp.post("/athletes")
def create_athlete():
    authenticate(("ElitesDirector",))
    body = get_body()
    full_name = rstr(body, "full_name")
    country_code = rstr(body, "country_code")
    gender = renum(body, "gender", GENDERS)
    birth_date = parse_date(rstr(body, "birth_date"), "birth_date")
    tax_residency_country = ostr(body, "tax_residency_country", None, allow_empty=False)
    athlete = new_record(
        full_name=full_name,
        country_code=country_code,
        gender=gender,
        birth_date=birth_date.isoformat(),
        tax_residency_country=tax_residency_country or country_code,
        w8ben_on_file=obool(body, "w8ben_on_file", False),
        treaty_withholding_bps=oint(body, "treaty_withholding_bps", 0, 0, 3000),
        whereabouts_filed=obool(body, "whereabouts_filed", False),
        missed_test_count=0,
    )
    db.athletes[athlete["id"]] = athlete
    return object_response(serializers.ser_athlete(athlete), 201)


@bp.get("/athletes/<athlete_id>")
def read_athlete(athlete_id):
    authenticate((
        "ElitesDirector",
        "FinanceOfficer",
        "TechnicalOfficial",
        "AntiDopingLiaison",
        "SanctioningBody",
    ))
    athlete = lookup.get_athlete(athlete_id)
    return object_response(serializers.ser_athlete(athlete))


@bp.patch("/athletes/<athlete_id>/tax-profile")
def update_tax_profile(athlete_id):
    authenticate(("FinanceOfficer",))
    athlete = lookup.get_athlete(athlete_id)
    body = get_body()
    tax_residency_country = ostr(body, "tax_residency_country", None, allow_empty=False)
    w8ben_on_file = obool(body, "w8ben_on_file", None)
    treaty_withholding_bps = oint(body, "treaty_withholding_bps", None, 0, 3000)
    if tax_residency_country is not None:
        athlete["tax_residency_country"] = tax_residency_country
    if w8ben_on_file is not None:
        athlete["w8ben_on_file"] = w8ben_on_file
    if treaty_withholding_bps is not None:
        athlete["treaty_withholding_bps"] = treaty_withholding_bps
    touch(athlete)
    return object_response(serializers.ser_athlete(athlete))


@bp.get("/athletes/<athlete_id>/performance-records")
def list_performance_records(athlete_id):
    authenticate(("ElitesDirector", "TechnicalOfficial", "AthleteAgent"))
    lookup.get_athlete(athlete_id)
    limit, offset = pagination_args()
    verification_status = enum_filter("verification_status", VERIFICATION_STATUSES)
    division = enum_filter("division", DIVISIONS)
    rows = lookup.rows("performance_records", athlete_id=athlete_id)
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    if division is not None:
        rows = [r for r in rows if r["division"] == division]
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_performance(r) for r in window], limit, offset, total
    )


@bp.post("/rep-agents")
def create_rep_agent():
    authenticate(("ElitesDirector",))
    body = get_body()
    agency_name = rstr(body, "agency_name")
    license_code = rstr(body, "license_code")
    commission_bps = oint(body, "commission_bps", 1500, 0, 3000)
    status = body.get("status")
    status = renum(body, "status", AGENT_STATUSES) if present(body, "status") else "ACTIVE"
    for existing in db.rep_agents.values():
        if existing["license_code"] == license_code:
            raise err("ERR_CONFIG_DUPLICATE", "license_code is already registered")
    agent = new_record(
        agency_name=agency_name,
        license_code=license_code,
        commission_bps=commission_bps,
        status=status,
    )
    db.rep_agents[agent["id"]] = agent
    return object_response(serializers.ser_agent(agent), 201)


@bp.post("/performance-records")
def create_performance_record():
    authenticate(("AthleteAgent", "ElitesDirector"))
    body = get_body()
    athlete_id = rstr(body, "athlete_id")
    lookup.get_athlete(athlete_id)
    race_name = rstr(body, "race_name")
    performance_date = parse_date(rstr(body, "performance_date"), "performance_date")
    performance_seconds = rint(body, "performance_seconds", minimum=1)
    division = renum(body, "division", DIVISIONS)
    sanctioning_ref = rstr(body, "sanctioning_ref")
    chip_timed = obool(body, "chip_timed", False)
    record = new_record(
        athlete_id=athlete_id,
        race_name=race_name,
        performance_date=performance_date.isoformat(),
        performance_seconds=performance_seconds,
        division=division,
        chip_timed=chip_timed,
        sanctioning_ref=sanctioning_ref,
        verification_status="SUBMITTED",
        verified_seconds=None,
        rejection_reason=None,
    )
    db.performance_records[record["id"]] = record
    return object_response(serializers.ser_performance(record), 201)


@bp.post("/performance-records/<record_id>/verification")
def verify_performance_record(record_id):
    authenticate(("TechnicalOfficial",))
    record = lookup.get_performance(record_id)
    body = get_body()
    decision = renum(body, "decision", ("VERIFIED", "REJECTED"))
    official_seconds = None
    rejection_reason = None
    if decision == "VERIFIED":
        official_seconds = rint(body, "official_seconds", minimum=1)
    else:
        rejection_reason = rstr(body, "rejection_reason")
    if record["verification_status"] != "SUBMITTED":
        raise err(
            "ERR_INVALID_PERFORMANCE_STATE",
            "The performance record has already been adjudicated",
        )
    if decision == "VERIFIED":
        record["verification_status"] = "VERIFIED"
        record["verified_seconds"] = official_seconds
    else:
        record["verification_status"] = "REJECTED"
        record["rejection_reason"] = rejection_reason
    touch(record)
    return object_response(serializers.ser_performance(record))
