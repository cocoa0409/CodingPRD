"""Composite setup helpers.

The server and its database are reset before every test, so every helper here
rebuilds its preconditions from scratch through the public API only — there is
no direct database access and no shared state between tests.

All helpers use `get_success_data`, which is lenient about the exact 2xx code,
because a fixture's job is to reach a state, not to assert the contract; the
tests themselves do the asserting with `validate_success` / `validate_error`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import COMPONENT_TYPE_ORDER, DEFAULT_CLOCK_MS, TEST_DEFAULTS
from .factories import (
    appointment_payload,
    certify_component_payload,
    clock_payload,
    collect_component_payload,
    deny_payload,
    destruction_payload,
    discipline_incident_payload,
    exclude_component_payload,
    fee_transaction_payload,
    hearing_officer_payload,
    hearing_schedule_payload,
    hold_payload,
    inspection_request_payload,
    inspection_room_payload,
    legal_demand_payload,
    mark_ready_payload,
    notification_payload,
    production_payload,
    records_request_payload,
    release_payload,
    state_rule_payload,
    statement_payload,
    student_payload,
    validate_request_payload,
    withdrawal_payload,
)
from .factories import amendment_decision_payload, amendment_request_payload
from .factories import district_payload
from .test_users import (
    make_compliance_officer_headers,
    make_legal_affairs_officer_headers,
    make_parent_headers,
    make_receiving_registrar_headers,
    make_records_clerk_headers,
    make_records_officer_headers,
    make_system_admin_headers,
)

ADMIN = make_system_admin_headers()
CLERK = make_records_clerk_headers()
OFFICER_1 = make_records_officer_headers(TEST_DEFAULTS["OFFICER_ONE"])
OFFICER_2 = make_records_officer_headers(TEST_DEFAULTS["OFFICER_TWO"])
COMPLIANCE = make_compliance_officer_headers()
LEGAL = make_legal_affairs_officer_headers()


# --- Primitives -----------------------------------------------------------


def set_clock(current_utc: str, headers: dict = None) -> dict:
    """Move the logical clock. Only a SystemAdmin may do this."""
    response = api_client.set_current_utc(clock_payload(current_utc), headers or ADMIN)
    return get_success_data(response)


def run_sweep(headers: dict = None) -> dict:
    """Run the compliance sweep as a ComplianceOfficer."""
    response = api_client.run_compliance_sweep(headers or COMPLIANCE)
    return get_success_data(response)


def create_state_rule(state_code: str = "CA", headers: dict = None, **overrides) -> dict:
    response = api_client.create_state_rule(
        state_rule_payload(state_code, **overrides), headers or ADMIN
    )
    return get_success_data(response)


def create_state_rules(state_codes=("CA", "TX", "NY"), overrides=None) -> dict:
    """Create one rule per state code. `overrides` maps a state code to a dict
    of parameter overrides for that rule only."""
    overrides = overrides or {}
    return {
        code: create_state_rule(code, **overrides.get(code, {})) for code in state_codes
    }


def create_district(
    district_code: str, state_code: str = "CA", name: str = None, headers: dict = None
) -> dict:
    response = api_client.create_district(
        district_payload(
            district_code=district_code,
            state_code=state_code,
            name=name or f"District {district_code}",
        ),
        headers or ADMIN,
    )
    return get_success_data(response)


def create_inspection_room(
    room_code: str = None, seats: int = None, headers: dict = None, **overrides
) -> dict:
    payload = inspection_room_payload(**overrides)
    if room_code is not None:
        payload["room_code"] = room_code
    if seats is not None:
        payload["seats"] = seats
    response = api_client.create_inspection_room(payload, headers or ADMIN)
    return get_success_data(response)


def close_inspection_room(room_id: str, headers: dict = None) -> dict:
    response = api_client.update_inspection_room(room_id, {"status": "CLOSED"}, headers or ADMIN)
    return get_success_data(response)


def create_hearing_officer(
    full_name: str = None, credential: str = None, headers: dict = None, **overrides
) -> dict:
    payload = hearing_officer_payload(**overrides)
    if full_name is not None:
        payload["full_name"] = full_name
    if credential is not None:
        payload["credential"] = credential
    response = api_client.create_hearing_officer(payload, headers or ADMIN)
    return get_success_data(response)


def deactivate_hearing_officer(officer_id: str, headers: dict = None) -> dict:
    response = api_client.update_hearing_officer(
        officer_id, {"status": "INACTIVE"}, headers or ADMIN
    )
    return get_success_data(response)


def create_student(district_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.create_student(
        student_payload(district_id, **overrides), headers or CLERK
    )
    return get_success_data(response)


# --- Cumulative file and components ---------------------------------------


def get_cumulative_file_id(student_id: str, headers: dict = None) -> str:
    """A student's cumulative file is created with the student, so the listing
    always holds exactly one row."""
    response = api_client.list_student_cumulative_files(student_id, headers or CLERK)
    rows = get_success_data(response)
    return rows[0]["id"]


def get_file(file_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_cumulative_file(file_id, headers or CLERK))


def get_components(file_id: str, headers: dict = None) -> dict:
    """Return the four components keyed by component_type."""
    response = api_client.list_file_components(file_id, headers or CLERK)
    rows = get_success_data(response)
    return {row["component_type"]: row for row in rows}


def get_component_list(file_id: str, headers: dict = None) -> list:
    """Return the components as the server ordered them."""
    return get_success_data(api_client.list_file_components(file_id, headers or CLERK))


def collect_component(
    file_id: str,
    component_id: str,
    page_count: int,
    redacted_page_count: int = 0,
    headers: dict = None,
) -> dict:
    response = api_client.update_file_component(
        file_id,
        component_id,
        collect_component_payload(page_count, redacted_page_count),
        headers or CLERK,
    )
    return get_success_data(response)


def certify_component(file_id: str, component_id: str, headers: dict = None) -> dict:
    """Certification is a RecordsOfficer action and stamps the acting user id."""
    response = api_client.update_file_component(
        file_id, component_id, certify_component_payload(), headers or OFFICER_1
    )
    return get_success_data(response)


def exclude_component(
    file_id: str,
    component_id: str,
    exclusion_reason: str = "OTHER_STUDENT_INFO",
    headers: dict = None,
) -> dict:
    response = api_client.update_file_component(
        file_id, component_id, exclude_component_payload(exclusion_reason), headers or OFFICER_1
    )
    return get_success_data(response)


def reinstate_component(file_id: str, component_id: str, headers: dict = None) -> dict:
    response = api_client.update_file_component(
        file_id, component_id, {"status": "COLLECTED"}, headers or OFFICER_1
    )
    return get_success_data(response)


def file_version(file_id: str, headers: dict = None) -> int:
    """Read the cumulative file's current optimistic-locking version."""
    return get_file(file_id, headers)["version"]


# --- The transfer scenario -------------------------------------------------


def setup_transfer_scenario(
    responding_state: str = "CA",
    requesting_state: str = "TX",
    state_rule_overrides: dict = None,
    has_iep: bool = False,
    student_overrides: dict = None,
    pages: dict = None,
    redactions: dict = None,
    certify=(),
    file_request: bool = True,
    request_overrides: dict = None,
    validate: bool = False,
    mark_ready: bool = False,
    responding_district_code: str = None,
    requesting_district_code: str = None,
) -> dict:
    """Build the recurring inter-district transfer scenario.

    Creates the state rules, the responding (record-holding) district, the
    requesting (receiving) district, a student enrolled in the responding
    district with its cumulative file, optionally drives components to
    COLLECTED / CERTIFIED, and optionally files, validates and marks-ready an
    inter-district records request.

    `pages` and `redactions` map a component type to a page count; `certify` is
    the iterable of component types to certify afterwards.
    """
    rules = {}
    state_rule_overrides = state_rule_overrides or {}
    for code in dict.fromkeys([responding_state, requesting_state]):
        rules[code] = create_state_rule(code, **state_rule_overrides.get(code, {}))

    responding_district_code = (
        responding_district_code or TEST_DEFAULTS["SENDING_DISTRICT_CODE"]
    )
    requesting_district_code = (
        requesting_district_code or TEST_DEFAULTS["RECEIVING_DISTRICT_CODE"]
    )
    responding_district = create_district(responding_district_code, responding_state)
    requesting_district = create_district(requesting_district_code, requesting_state)

    overrides = dict(student_overrides or {})
    overrides.setdefault("has_iep", has_iep)
    student = create_student(responding_district["id"], **overrides)

    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)

    pages = pages or {}
    redactions = redactions or {}
    for ctype in COMPONENT_TYPE_ORDER:
        if ctype in pages:
            collect_component(
                file_id,
                components[ctype]["id"],
                pages[ctype],
                redactions.get(ctype, 0),
            )
    for ctype in COMPONENT_TYPE_ORDER:
        if ctype in certify:
            certify_component(file_id, components[ctype]["id"])
    components = get_components(file_id)

    registrar_headers = make_receiving_registrar_headers(requesting_district["id"])
    parent_headers = make_parent_headers(
        overrides.get("guardian_user_id", TEST_DEFAULTS["GUARDIAN_USER_ID"])
    )

    scenario = {
        "rules": rules,
        "responding_district": responding_district,
        "requesting_district": requesting_district,
        "student": student,
        "file_id": file_id,
        "file": get_file(file_id),
        "components": components,
        "request": None,
        "registrar_headers": registrar_headers,
        "parent_headers": parent_headers,
        "officer_headers": OFFICER_1,
        "clerk_headers": CLERK,
        "admin_headers": ADMIN,
    }

    if file_request:
        request = create_records_request(
            student["id"],
            requesting_district["id"],
            responding_district["id"],
            headers=registrar_headers,
            **(request_overrides or {}),
        )
        scenario["request"] = request
        if validate or mark_ready:
            scenario["request"] = validate_request(request["id"])
        if mark_ready:
            scenario["request"] = mark_ready_request(request["id"], file_id)
        scenario["file"] = get_file(file_id)
        scenario["components"] = get_components(file_id)

    return scenario


def create_records_request(
    student_id: str,
    requesting_district_id: str,
    responding_district_id: str,
    headers: dict = None,
    **overrides,
) -> dict:
    """Only the requesting district's own ReceivingRegistrar may file it."""
    response = api_client.create_records_request(
        records_request_payload(
            student_id, requesting_district_id, responding_district_id, **overrides
        ),
        headers or make_receiving_registrar_headers(requesting_district_id),
    )
    return get_success_data(response)


def validate_request(request_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.validate_records_request(
        request_id, validate_request_payload(**overrides), headers or OFFICER_1
    )
    return get_success_data(response)


def mark_ready_request(
    request_id: str, file_id: str, headers: dict = None, expected_version: int = None
) -> dict:
    """Read the cumulative file's version and present it as the mark-ready
    optimistic-locking token."""
    version = expected_version if expected_version is not None else file_version(file_id)
    response = api_client.mark_ready_records_request(
        request_id, mark_ready_payload(version), headers or OFFICER_1
    )
    return get_success_data(response)


def release_request(
    request_id: str, transmission_method: str = "SECURE_PORTAL", headers: dict = None
) -> dict:
    response = api_client.release_records_request(
        request_id, release_payload(transmission_method), headers or OFFICER_1
    )
    return get_success_data(response)


def deny_request(
    request_id: str, denial_reason: str = "DUPLICATE_REQUEST", headers: dict = None
) -> dict:
    response = api_client.deny_records_request(
        request_id, deny_payload(denial_reason), headers or OFFICER_1
    )
    return get_success_data(response)


def setup_request_ready_for_release(
    pages: dict = None,
    redactions: dict = None,
    responding_state: str = "CA",
    requesting_state: str = "TX",
    state_rule_overrides: dict = None,
    has_iep: bool = False,
    student_overrides: dict = None,
    request_overrides: dict = None,
    certifier: dict = None,
) -> dict:
    """Drive a records request all the way to READY_FOR_RELEASE.

    Every component the file declares required is collected and certified, so
    the file reaches COMPLETE and mark-ready succeeds; the packet snapshot is
    taken at that moment.
    """
    scenario = setup_transfer_scenario(
        responding_state=responding_state,
        requesting_state=requesting_state,
        state_rule_overrides=state_rule_overrides,
        has_iep=has_iep,
        student_overrides=student_overrides,
        file_request=False,
    )
    file_id = scenario["file_id"]
    required = scenario["file"]["required_component_types"]
    pages = pages or {ctype: 20 for ctype in required}
    redactions = redactions or {}
    for ctype in COMPONENT_TYPE_ORDER:
        if ctype in pages:
            collect_component(
                file_id,
                scenario["components"][ctype]["id"],
                pages[ctype],
                redactions.get(ctype, 0),
            )
    for ctype in required:
        certify_component(
            file_id, scenario["components"][ctype]["id"], certifier or OFFICER_1
        )

    request = create_records_request(
        scenario["student"]["id"],
        scenario["requesting_district"]["id"],
        scenario["responding_district"]["id"],
        headers=scenario["registrar_headers"],
        **(request_overrides or {}),
    )
    validate_request(request["id"])
    scenario["request"] = mark_ready_request(request["id"], file_id)
    scenario["file"] = get_file(file_id)
    scenario["components"] = get_components(file_id)
    return scenario


# --- Discipline incidents --------------------------------------------------


def create_incident(student_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.create_discipline_incident(
        student_id, discipline_incident_payload(**overrides), headers or CLERK
    )
    return get_success_data(response)


def create_incidents(student_id: str, specs, headers: dict = None) -> list:
    """Create one incident per spec dict, in order."""
    return [create_incident(student_id, headers=headers, **spec) for spec in specs]


# --- Withdrawals -----------------------------------------------------------


def create_withdrawal(student_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.create_withdrawal(
        student_id, withdrawal_payload(**overrides), headers or CLERK
    )
    return get_success_data(response)


def place_hold(withdrawal_id: str, hold_type: str, headers: dict = None) -> dict:
    response = api_client.place_withdrawal_hold(
        withdrawal_id, hold_payload(hold_type), headers or CLERK
    )
    return get_success_data(response)


def release_hold(withdrawal_id: str, hold_type: str, headers: dict = None) -> dict:
    response = api_client.release_withdrawal_hold(
        withdrawal_id, hold_payload(hold_type), headers or CLERK
    )
    return get_success_data(response)


def complete_withdrawal(withdrawal_id: str, headers: dict = None) -> dict:
    """Completion is reserved to a RecordsOfficer."""
    response = api_client.complete_withdrawal(withdrawal_id, headers or OFFICER_1)
    return get_success_data(response)


def setup_withdrawal_completed(
    student_id: str, holds=(), headers: dict = None, **overrides
) -> dict:
    """File a withdrawal, place then release every hold in `holds`, and
    complete it so the exit cascade runs."""
    withdrawal = create_withdrawal(student_id, headers=headers, **overrides)
    for hold_type in holds:
        place_hold(withdrawal["id"], hold_type, headers)
    for hold_type in holds:
        release_hold(withdrawal["id"], hold_type, headers)
    return complete_withdrawal(withdrawal["id"])


def get_retention_schedules(file_id: str, headers: dict = None) -> list:
    response = api_client.list_file_retention_schedules(file_id, headers or COMPLIANCE)
    return get_success_data(response)


def destroy_schedule(
    schedule_id: str, destruction_method: str = "CROSS_CUT_SHRED", headers: dict = None
) -> dict:
    response = api_client.execute_destruction(
        schedule_id, destruction_payload(destruction_method), headers or COMPLIANCE
    )
    return get_success_data(response)


# --- Inspection requests, fees, appointments -------------------------------


def create_inspection_request(
    student_id: str,
    headers: dict,
    categories=None,
    copies_requested: bool = False,
    **overrides,
) -> dict:
    """A Parent or an EligibleStudent files the inspection request, so the
    caller must pass the matching identity headers."""
    response = api_client.create_inspection_request(
        student_id,
        inspection_request_payload(categories, copies_requested, **overrides),
        headers,
    )
    return get_success_data(response)


def get_inspection_request(inspection_request_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_inspection_request(inspection_request_id, headers or CLERK)
    )


def pay_fee(
    inspection_request_id: str,
    amount_cents: int,
    fee_transaction_type: str = "PAYMENT",
    headers: dict = None,
) -> dict:
    response = api_client.create_fee_transaction(
        inspection_request_id,
        fee_transaction_payload(fee_transaction_type, amount_cents),
        headers or CLERK,
    )
    return get_success_data(response)


def clear_fees(inspection_request_id: str, headers: dict = None) -> dict:
    """Pay off whatever the inspection request still owes."""
    request = get_inspection_request(inspection_request_id, headers)
    outstanding = request["fee_outstanding_cents"]
    if outstanding > 0:
        pay_fee(inspection_request_id, outstanding, "PAYMENT", headers)
    return get_inspection_request(inspection_request_id, headers)


def book_appointment(
    inspection_request_id: str,
    room_id: str,
    start_at: str,
    end_at: str,
    expected_version: int = None,
    headers: dict = None,
) -> dict:
    """Present the inspection request's current version as the appointment's
    optimistic-locking token."""
    if expected_version is None:
        expected_version = get_inspection_request(inspection_request_id, headers)["version"]
    response = api_client.create_review_appointment(
        inspection_request_id,
        appointment_payload(room_id, start_at, end_at, expected_version),
        headers or OFFICER_1,
    )
    return get_success_data(response)


def record_attendance(appointment_id: str, attended: bool = True, headers: dict = None) -> dict:
    response = api_client.record_attendance(
        appointment_id, {"attended": attended}, headers or OFFICER_1
    )
    return get_success_data(response)


def setup_inspection_scenario(
    pages: dict = None,
    redactions: dict = None,
    certify_required: bool = True,
    copies_requested: bool = False,
    categories=None,
    responding_state: str = "CA",
    has_iep: bool = False,
    student_overrides: dict = None,
    room_code: str = None,
) -> dict:
    """Build a student with a populated cumulative file, an inspection room and
    a filed inspection request. Returns the scenario plus `inspection_request`
    and `room`."""
    scenario = setup_transfer_scenario(
        responding_state=responding_state,
        requesting_state=responding_state,
        has_iep=has_iep,
        student_overrides=student_overrides,
        file_request=False,
        requesting_district_code=TEST_DEFAULTS["RECEIVING_DISTRICT_CODE"],
    )
    file_id = scenario["file_id"]
    pages = pages or {ctype: 20 for ctype in scenario["file"]["required_component_types"]}
    redactions = redactions or {}
    for ctype in COMPONENT_TYPE_ORDER:
        if ctype in pages:
            collect_component(
                file_id,
                scenario["components"][ctype]["id"],
                pages[ctype],
                redactions.get(ctype, 0),
            )
    if certify_required:
        for ctype in scenario["file"]["required_component_types"]:
            certify_component(file_id, scenario["components"][ctype]["id"])

    scenario["room"] = create_inspection_room(room_code or TEST_DEFAULTS["ROOM_CODE"])
    scenario["inspection_request"] = create_inspection_request(
        scenario["student"]["id"],
        scenario["parent_headers"],
        categories=categories,
        copies_requested=copies_requested,
    )
    scenario["file"] = get_file(file_id)
    scenario["components"] = get_components(file_id)
    return scenario


# --- Amendment challenges, hearings, statements -----------------------------


def create_amendment(student_id: str, component_id: str, headers: dict, **overrides) -> dict:
    """A Parent or an EligibleStudent contests a component."""
    response = api_client.create_amendment_request(
        student_id, amendment_request_payload(component_id, **overrides), headers
    )
    return get_success_data(response)


def decide_amendment(
    amendment_request_id: str, outcome: str = "DENY", headers: dict = None, **overrides
) -> dict:
    """The acting RecordsOfficer is recorded on the decision, so pass distinct
    officer headers wherever the deciding identity matters."""
    response = api_client.create_amendment_decision(
        amendment_request_id, amendment_decision_payload(outcome, **overrides), headers or OFFICER_1
    )
    return get_success_data(response)


def request_hearing(amendment_request_id: str, headers: dict) -> dict:
    response = api_client.create_hearing_request(amendment_request_id, headers)
    return get_success_data(response)


def schedule_hearing(
    amendment_request_id: str,
    hearing_officer_id: str,
    hearing_start_at: str,
    hearing_end_at: str,
    headers: dict = None,
) -> dict:
    response = api_client.create_hearing_schedule(
        amendment_request_id,
        hearing_schedule_payload(hearing_officer_id, hearing_start_at, hearing_end_at),
        headers or OFFICER_1,
    )
    return get_success_data(response)


def file_statement(amendment_request_id: str, headers: dict, **overrides) -> dict:
    response = api_client.create_statement_of_disagreement(
        amendment_request_id, statement_payload(**overrides), headers
    )
    return get_success_data(response)


def setup_amendment_denied(
    pages: dict = None,
    contested_type: str = "ACADEMIC",
    decider: dict = None,
    responding_state: str = "CA",
    has_iep: bool = False,
) -> dict:
    """Build a student with a certified component, a filed amendment request and
    an initial DENY decision, so the hearing path is open."""
    scenario = setup_transfer_scenario(
        responding_state=responding_state,
        requesting_state=responding_state,
        has_iep=has_iep,
        file_request=False,
        requesting_district_code=TEST_DEFAULTS["RECEIVING_DISTRICT_CODE"],
    )
    file_id = scenario["file_id"]
    pages = pages or {ctype: 20 for ctype in scenario["file"]["required_component_types"]}
    for ctype in COMPONENT_TYPE_ORDER:
        if ctype in pages:
            collect_component(file_id, scenario["components"][ctype]["id"], pages[ctype])
    for ctype in scenario["file"]["required_component_types"]:
        certify_component(file_id, scenario["components"][ctype]["id"])

    amendment = create_amendment(
        scenario["student"]["id"],
        scenario["components"][contested_type]["id"],
        scenario["parent_headers"],
    )
    scenario["amendment"] = decide_amendment(
        amendment["id"], "DENY", decider or OFFICER_1
    )
    scenario["components"] = get_components(file_id)
    scenario["file"] = get_file(file_id)
    return scenario


def setup_amendment_hearing_scheduled(
    hearing_start_at: str = "2026-08-05T09:00:00.000Z",
    hearing_end_at: str = "2026-08-05T10:00:00.000Z",
    officer_credential: str = "DISTRICT_DESIGNEE",
    decider: dict = None,
    **kwargs,
) -> dict:
    """Deny the amendment, request a hearing and schedule it with a fresh
    ACTIVE hearing officer."""
    scenario = setup_amendment_denied(decider=decider, **kwargs)
    request_hearing(scenario["amendment"]["id"], scenario["parent_headers"])
    scenario["hearing_officer"] = create_hearing_officer(
        credential=officer_credential
    )
    scenario["amendment"] = schedule_hearing(
        scenario["amendment"]["id"],
        scenario["hearing_officer"]["id"],
        hearing_start_at,
        hearing_end_at,
    )
    return scenario


def setup_amendment_upheld(
    hearing_decider: dict = None, **kwargs
) -> dict:
    """Carry the amendment through the hearing to an UPHELD outcome, which is
    the only state in which a statement of disagreement may be filed."""
    scenario = setup_amendment_hearing_scheduled(**kwargs)
    scenario["amendment"] = decide_amendment(
        scenario["amendment"]["id"], "DENY", hearing_decider or OFFICER_2
    )
    return scenario


# --- Legal demands ---------------------------------------------------------


def create_legal_demand(student_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.create_legal_demand(
        student_id, legal_demand_payload(**overrides), headers or LEGAL
    )
    return get_success_data(response)


def notify_demand(demand_id: str, headers: dict = None, **overrides) -> dict:
    response = api_client.create_demand_notification(
        demand_id, notification_payload(**overrides), headers or LEGAL
    )
    return get_success_data(response)


def produce_demand(demand_id: str, produced_page_count: int, headers: dict = None) -> dict:
    response = api_client.create_demand_production(
        demand_id, production_payload(produced_page_count), headers or LEGAL
    )
    return get_success_data(response)


def get_disclosure_log(student_id: str, headers: dict = None, params: dict = None) -> list:
    response = api_client.list_disclosure_log(student_id, headers or CLERK, params=params)
    return get_success_data(response)
