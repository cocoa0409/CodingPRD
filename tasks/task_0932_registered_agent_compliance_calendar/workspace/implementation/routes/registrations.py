"""Occupying and leaving a jurisdiction (PRD 3.2, 3.11, 3.12)."""

import envelope
import listing
import lookup
import serializers
import timeutil
from dispatch import endpoint, query_filter
from errors import ApiError
from services import registrations as registration_service
from services import rollups, rules
from store import DB, new_row, touch

BLOCKING_STATUSES = ("PENDING", "ACTIVE", "DELINQUENT", "ADMIN_DISSOLVED")


def _interval_conflict(entity_id, state_code, start_date):
    for row in lookup.registrations_of_entity(entity_id):
        if row["state_code"] != state_code:
            continue
        if row["status"] in BLOCKING_STATUSES:
            return True
        if row["closed_on"] is not None and start_date < row["closed_on"]:
            return True
    return False


def _governing_rule_or_none(registration):
    return rules.select_or_none(registration["state_code"], timeutil.today())


def _tax_clearance_gate(context, registration):
    """Rung 26.  With no rule row effective for the jurisdiction there is no
    published requirement to enforce, and no declared error covers that here."""
    # No non-empty constraint is declared on this field, so a blank value is a
    # well-formed rung-13 body; it is rung 26 that demands a NON-BLANK value.
    reference = context.body.string("tax_clearance_reference", default=None, non_empty=False)
    rule = _governing_rule_or_none(registration)
    if rule is not None and rule["requires_tax_clearance"]:
        if reference is None or not reference.strip():
            raise ApiError("ERR_TAX_CLEARANCE_REQUIRED")


def _resignation_notice_gate(registration):
    """Rung 31."""
    clock_date = timeutil.today()
    for appointment in lookup.appointments_of_registration(registration["id"]):
        if (
            appointment["status"] == "RESIGNATION_NOTICED"
            and appointment["resignation_effective_on"] is not None
            and clock_date < appointment["resignation_effective_on"]
        ):
            raise ApiError("ERR_RESIGNATION_NOTICE_ACTIVE")


def _new_registration(entity, state_code, kind, name_clearance_id, assumed_name):
    return new_row(
        DB.registrations,
        {
            "legal_entity_id": entity["id"],
            "name_clearance_id": name_clearance_id,
            "state_code": state_code,
            "registration_kind": kind,
            "qualified_on": None,
            "closed_on": None,
            "status": "PENDING",
            "agent_of_record_id": None,
            "admin_dissolved_on": None,
            "reinstatement_deadline": None,
            "delinquency_rank": 0,
            "sop_priority_hold": False,
            "assumed_name": assumed_name,
        },
    )


@endpoint(
    "POST", "/legal-entities/{id}/registrations", roles=["ComplianceOfficer"], success_code=201
)
def create_home_registration(context):
    entity = context.row
    clock_date = timeutil.today()
    rules.select(entity["home_state_code"], clock_date)  # rung 18
    if _interval_conflict(entity["id"], entity["home_state_code"], clock_date):  # rung 20
        raise ApiError("ERR_DUPLICATE_REGISTRATION")
    row = _new_registration(entity, entity["home_state_code"], "HOME", None, None)
    rollups.cascade_from_registration(row)
    return envelope.object_response(serializers.registration(row), 201)


@endpoint(
    "POST",
    "/legal-entities/{id}/foreign-qualifications",
    roles=["ComplianceOfficer"],
    success_code=201,
)
def create_foreign_qualification(context):
    entity = context.row
    body = context.body
    state_code = body.state_code("state_code", required=True)
    body.identifier("name_clearance_id", required=True)
    body.identifier("good_standing_certificate_id", required=True)
    clearance = context.refs["name_clearance_id"]
    certificate = context.refs["good_standing_certificate_id"]
    clock_date = timeutil.today()

    # Declared gate order (PRD 2.9.1): 18, 20, 23, 24, 25.
    target_rule = rules.select(state_code, clock_date)  # rung 18
    if _interval_conflict(entity["id"], state_code, clock_date):  # rung 20
        raise ApiError("ERR_DUPLICATE_REGISTRATION")
    home = next(
        (
            r
            for r in lookup.registrations_of_entity(entity["id"])
            if r["registration_kind"] == "HOME"
        ),
        None,
    )
    if home is not None and home["status"] in (
        "DELINQUENT",
        "ADMIN_DISSOLVED",
        "CLOSED_PERMANENT",
    ):  # rung 23
        raise ApiError("ERR_HOME_STATE_DELINQUENT")
    age_days = timeutil.day_diff(clock_date, certificate["issued_on"])
    if not age_days < target_rule["good_standing_freshness_days"]:  # rung 24, strictly
        raise ApiError("ERR_CERTIFICATE_STALE")
    resolved = clearance["result"] == "AVAILABLE" or (
        clearance["result"] == "CONFLICT" and clearance["fallback_assumed_name"] is not None
    )
    if not resolved:  # rung 25
        raise ApiError("ERR_NAME_CONFLICT_UNRESOLVED")

    assumed_name = clearance["resolved_name"] if clearance["result"] == "CONFLICT" else None
    row = _new_registration(entity, state_code, "FOREIGN", clearance["id"], assumed_name)
    rollups.cascade_from_registration(row)
    return envelope.object_response(serializers.registration(row), 201)


@endpoint(
    "GET",
    "/registrations",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "SopHandler", "ClientContact"],
    success_code=200,
)
def list_registrations(context):
    rows = list(DB.registrations.values())
    rows = listing.scope_to_client(context, rows, listing.registration_owner)
    rows = listing.apply_filters(
        rows,
        [
            ("legal_entity_id", "legal_entity_id"),
            ("name_clearance_id", "name_clearance_id"),
            ("state_code", "state_code"),
            ("status", "status"),
        ],
    )
    return listing.respond(rows, serializers.registration)


@endpoint(
    "GET",
    "/registrations/{id}",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "SopHandler", "ClientContact"],
    success_code=200,
)
def read_registration(context):
    return envelope.object_response(serializers.registration(context.row))


@endpoint("POST", "/registrations/{id}/activate", roles=["FilingAgent"], success_code=200)
def activate_registration(context):
    registration = context.row
    if registration["status"] != "PENDING":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    appointed = any(
        a["status"] == "APPOINTED"
        for a in lookup.appointments_of_registration(registration["id"])
    )
    if not appointed:  # rung 30
        raise ApiError("ERR_AGENT_OF_RECORD_REQUIRED")
    registration["status"] = "ACTIVE"
    registration["qualified_on"] = timeutil.today()
    registration_service.refresh_agent_of_record(registration)
    rollups.recompute_registration_rank(registration)
    touch(registration)
    rollups.cascade_from_registration(registration)
    return envelope.object_response(serializers.registration(registration))


@endpoint("POST", "/registrations/{id}/withdraw", roles=["FilingAgent"], success_code=200)
def withdraw_registration(context):
    registration = context.row
    accepted_withdrawal = any(
        f["registration_id"] == registration["id"]
        and f["filing_kind"] == "WITHDRAWAL"
        and f["status"] == "ACCEPTED"
        for f in DB.filings.values()
    )
    if (
        registration["status"] != "ACTIVE"
        or registration["registration_kind"] != "FOREIGN"
        or not accepted_withdrawal
    ):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    _tax_clearance_gate(context, registration)  # rung 26
    _resignation_notice_gate(registration)  # rung 31

    registration["status"] = "WITHDRAWN"
    registration["closed_on"] = timeutil.today()
    registration_service.void_open_obligations(registration, exempt_final_report=False)
    registration_service.resign_live_appointments(registration)
    rollups.recompute_registration_rank(registration)
    touch(registration)
    rollups.cascade_from_registration(registration)
    return envelope.object_response(serializers.registration(registration))


@endpoint("POST", "/registrations/{id}/terminate", roles=["FilingAgent"], success_code=200)
def terminate_registration(context):
    registration = context.row
    accepted_dissolution = any(
        f["registration_id"] == registration["id"]
        and f["filing_kind"] == "DISSOLUTION"
        and f["status"] == "ACCEPTED"
        for f in DB.filings.values()
    )
    if (
        registration["status"] != "ACTIVE"
        or registration["registration_kind"] != "HOME"
        or not accepted_dissolution
    ):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    _tax_clearance_gate(context, registration)  # rung 26 -- before the sweep
    siblings = lookup.registrations_of_entity(registration["legal_entity_id"])
    if any(
        r["registration_kind"] == "FOREIGN"
        and r["status"] not in ("WITHDRAWN", "CLOSED_PERMANENT")
        for r in siblings
    ):  # rung 27
        raise ApiError("ERR_FOREIGN_QUALIFICATIONS_OUTSTANDING")
    _resignation_notice_gate(registration)  # rung 31

    registration["status"] = "TERMINATED"
    registration["closed_on"] = timeutil.today()
    registration_service.void_open_obligations(registration, exempt_final_report=True)
    registration_service.resign_live_appointments(registration)
    rollups.recompute_registration_rank(registration)
    touch(registration)
    rollups.cascade_from_registration(registration)
    return envelope.object_response(serializers.registration(registration))


@endpoint(
    "POST",
    "/registrations/{id}/administratively-dissolve",
    roles=["PlatformAdmin"],
    success_code=200,
)
def administratively_dissolve(context):
    registration = context.row
    clock_date = timeutil.today()
    if registration["status"] != "DELINQUENT" or not registration_service.dissolution_horizon_passed(
        registration, clock_date
    ):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    registration_service.administratively_dissolve(registration)
    rollups.cascade_from_registration(registration)
    return envelope.object_response(serializers.registration(registration))


@endpoint(
    "POST",
    "/registrations/{id}/good-standing-certificates",
    roles=["ComplianceOfficer"],
    success_code=201,
)
def create_certificate(context):
    registration = context.row
    issued_on = context.body.date("issued_on", required=True)
    certificate_number = context.body.string("certificate_number", required=True)
    row = new_row(
        DB.certificates,
        {
            "registration_id": registration["id"],
            "state_code": registration["state_code"],
            "issued_on": issued_on,
            "certificate_number": certificate_number,
        },
        versioned=False,
    )
    return envelope.object_response(serializers.certificate(row), 201)


@endpoint(
    "GET",
    "/registrations/{id}/good-standing-certificates",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent"],
    success_code=200,
)
def list_certificates(context):
    rows = [
        c for c in DB.certificates.values() if c["registration_id"] == context.row["id"]
    ]
    return listing.respond(rows, serializers.certificate)


@endpoint(
    "GET",
    "/registrations/{id}/reinstatement-cases",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent"],
    success_code=200,
)
def list_cases(context):
    rows = lookup.cases_of_registration(context.row["id"])
    status = query_filter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, serializers.reinstatement_case)


@endpoint(
    "POST",
    "/registrations/{id}/reinstatement-cases",
    roles=["ComplianceOfficer"],
    success_code=201,
)
def open_case(context):
    registration = context.row
    if registration["status"] != "ADMIN_DISSOLVED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    deadline = registration["reinstatement_deadline"]
    if deadline is None or timeutil.today() > deadline:  # rung 42
        raise ApiError("ERR_REINSTATEMENT_WINDOW_CLOSED")
    row = new_row(
        DB.reinstatement_cases,
        {
            "registration_id": registration["id"],
            "status": "OPEN",
            "window_close_date": deadline,
            "assessment_date": None,
            "missed_period_count": 0,
            "back_fee_total_cents": 0,
            "obligations_cured_count": 0,
            "denial_reason": None,
        },
    )
    return envelope.object_response(serializers.reinstatement_case(row), 201)
