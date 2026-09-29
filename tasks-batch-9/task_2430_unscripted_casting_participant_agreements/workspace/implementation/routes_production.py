"""Productions, welfare protocols, venues and the logical-clock control."""

from flask import Blueprint

import calc
import services
import store
from clock import clock, parse_iso
from envelope import list_response, object_response
from errors import ApiError
from store import serialize, serialize_all, touch
from validation import (
    ALL_ROLES,
    OPERATOR_ROLES,
    authenticate,
    filter_arg,
    json_body,
    opt_int,
    opt_string,
    pagination,
    paginate,
    req_datetime,
    req_enum,
    req_int,
    req_string,
    require_after,
)

bp = Blueprint("production", __name__)

FORMAT_TYPES = ("COMPETITION_HIGH_STRESS", "DOCUSOAP", "DATING_FORMAT", "TALENT_SEARCH")
JURISDICTIONS = ("CA", "NY", "GA", "IL")
PROTOCOL_KINDS = (
    "DUTY_OF_CARE_OFFICER",
    "ONSET_PSYCH_SUPPORT",
    "INSURANCE_RIDER",
    "AFTERCARE_PROGRAM",
)


# ------------------------------------------------------------------ productions
@bp.post("/casting/productions")
def create_production():
    authenticate(("ProductionAdmin",))
    body = json_body()
    title = req_string(body, "title", min_len=1, max_len=200)
    format_type = req_enum(body, "format_type", FORMAT_TYPES)
    jurisdiction_code = req_enum(body, "jurisdiction_code", JURISDICTIONS)
    season_number = req_int(body, "season_number", minimum=1)
    episode_order = req_int(body, "episode_order", minimum=1, maximum=40)
    photography_start_utc = req_datetime(body, "photography_start_utc")
    photography_end_utc = req_datetime(body, "photography_end_utc")
    require_after(
        body,
        "photography_end_utc",
        "photography_start_utc",
        photography_end_utc,
        photography_start_utc,
    )
    stipend_pool_cents = req_int(body, "stipend_pool_cents", minimum=0)
    welfare_budget_cents = req_int(body, "welfare_budget_cents", minimum=0)
    minor_participant_cap = req_int(body, "minor_participant_cap", minimum=0)

    record = store.new_record(
        "production",
        {
            "title": title,
            "format_type": format_type,
            "jurisdiction_code": jurisdiction_code,
            "season_number": season_number,
            "episode_order": episode_order,
            "photography_start_utc": photography_start_utc,
            "photography_end_utc": photography_end_utc,
            "stipend_pool_cents": stipend_pool_cents,
            "stipend_committed_cents": 0,
            "welfare_budget_cents": welfare_budget_cents,
            "welfare_committed_cents": 0,
            "trust_escrow_balance_cents": 0,
            "duty_of_care_tier": "ENHANCED" if format_type == "COMPETITION_HIGH_STRESS" else "STANDARD",
            "welfare_incident_count": 0,
            "breached_obligation_count": 0,
            "casting_posture": "OPEN",
            "minor_participant_cap": minor_participant_cap,
            "minor_participant_count": 0,
        },
    )
    store.productions[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/casting/productions/<production_id>")
def read_production(production_id):
    authenticate(ALL_ROLES)
    production = services.get_production(production_id)
    return object_response(serialize(production))


@bp.post("/casting/productions/<production_id>/welfare-run")
def welfare_run(production_id):
    authenticate(("ProductionAdmin",))
    production = services.get_production(production_id)
    services.welfare_run(production)
    return object_response(serialize(production))


# ------------------------------------------------------------ welfare protocols
@bp.post("/casting/productions/<production_id>/welfare-protocols")
def plan_welfare_protocol(production_id):
    authenticate(("WelfareOfficer",))
    production = services.get_production(production_id)
    body = json_body()
    kind = req_enum(body, "kind", PROTOCOL_KINDS)
    coverage_start_utc = req_datetime(body, "coverage_start_utc")
    coverage_end_utc = req_datetime(body, "coverage_end_utc")
    require_after(body, "coverage_end_utc", "coverage_start_utc", coverage_end_utc, coverage_start_utc)
    cost_cents = req_int(body, "cost_cents", minimum=0)
    carrier_certificate_number = opt_string(body, "carrier_certificate_number")

    # rung 38
    if kind == "INSURANCE_RIDER" and not carrier_certificate_number:
        raise ApiError("ERR_INSURANCE_CERTIFICATE_MISSING")
    # rung 45
    if services.welfare_committed_preview(production, cost_cents) > production["welfare_budget_cents"]:
        raise ApiError("ERR_WELFARE_BUDGET_EXCEEDED")

    record = store.new_record(
        "welfare_protocol",
        {
            "production_id": production["id"],
            "kind": kind,
            "coverage_start_utc": coverage_start_utc,
            "coverage_end_utc": coverage_end_utc,
            "cost_cents": cost_cents,
            "carrier_certificate_number": carrier_certificate_number,
            "status": "PLANNED",
        },
    )
    store.welfare_protocols[record["id"]] = record

    services.recompute_welfare_committed(production)
    touch(production)
    services.recompute_posture(production)
    return object_response(serialize(record), 201)


@bp.get("/casting/productions/<production_id>/welfare-protocols")
def list_welfare_protocols(production_id):
    authenticate(OPERATOR_ROLES)
    production = services.get_production(production_id)
    limit, offset = pagination()
    records = services.protocols_of_production(production["id"])
    status = filter_arg("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    kind = filter_arg("kind")
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.post("/casting/welfare-protocols/<protocol_id>/activate")
def activate_welfare_protocol(protocol_id):
    authenticate(("WelfareOfficer",))
    protocol = services.get_welfare_protocol(protocol_id)
    production = services.get_production(protocol["production_id"])

    if protocol["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if protocol["kind"] == "INSURANCE_RIDER" and not protocol["carrier_certificate_number"]:
        raise ApiError("ERR_INSURANCE_CERTIFICATE_MISSING")
    if parse_iso(protocol["coverage_end_utc"]) <= clock.now():
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Coverage has already ended; the protocol cannot be activated.",
        )
    if services.welfare_committed_preview(production) > production["welfare_budget_cents"]:
        raise ApiError("ERR_WELFARE_BUDGET_EXCEEDED")

    protocol["status"] = "ACTIVE"
    touch(protocol)
    services.recompute_welfare_committed(production)
    touch(production)
    services.recompute_posture(production)
    return object_response(serialize(protocol))


@bp.post("/casting/welfare-protocols/<protocol_id>/cancel")
def cancel_welfare_protocol(protocol_id):
    authenticate(("WelfareOfficer",))
    protocol = services.get_welfare_protocol(protocol_id)
    production = services.get_production(protocol["production_id"])
    if protocol["status"] not in ("PLANNED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    protocol["status"] = "CANCELLED"
    touch(protocol)
    services.recompute_welfare_committed(production)
    touch(production)
    services.recompute_posture(production)
    return object_response(serialize(protocol))


# ---------------------------------------------------------------------- venues
@bp.post("/casting/locations")
def create_location():
    authenticate(("ProductionAdmin",))
    body = json_body()
    name = req_string(body, "name")
    state_code = req_enum(body, "state_code", JURISDICTIONS)
    capacity = req_int(body, "capacity", minimum=1)
    turnaround_buffer_minutes = opt_int(
        body, "turnaround_buffer_minutes", default=60, minimum=0, maximum=480
    )
    filming_permit_number = opt_string(body, "filming_permit_number")

    record = store.new_record(
        "location",
        {
            "name": name,
            "state_code": state_code,
            "capacity": capacity,
            "turnaround_buffer_minutes": turnaround_buffer_minutes,
            "filming_permit_number": filming_permit_number,
        },
    )
    store.locations[record["id"]] = record
    return object_response(serialize(record), 201)


# ----------------------------------------------------------- logical clock
clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("ProductionAdmin",))
    body = json_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    clock.set(parse_iso(to_iso8601))
    return object_response({})
