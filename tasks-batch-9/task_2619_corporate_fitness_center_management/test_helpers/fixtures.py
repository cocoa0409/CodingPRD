"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only PRD-declared endpoints.  Setup calls use
the lenient success validator so a broken precondition surfaces as a clear
setup failure rather than as a confusing assertion inside the test body.

The scenario dictionaries returned by the `setup_*` helpers carry both the
entities and the correctly-threaded role headers, so ownership-scoped calls
always act as the principal that actually owns the resource.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC, TEST_DEFAULTS
from .factories import (
    aed_asset_payload,
    cardio_asset_payload,
    client_contract_payload,
    facility_room_payload,
    invoice_payload,
    management_fee_contract_payload,
    member_payload,
    participation_payload,
    program_offering_payload,
    program_session_payload,
    staff_assignment_payload,
    staff_credential_payload,
    staff_member_payload,
    waiver_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_sponsor_headers,
    make_fitness_staff_headers,
    make_member_headers,
    make_site_manager_headers,
)

ADMIN = TEST_USERS["operator_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]

_SEQ = {"n": 0}


def _next_seq() -> int:
    _SEQ["n"] += 1
    return _SEQ["n"]


def reset_sequence():
    _SEQ["n"] = 0


# ==========================================================================
# Clock and plain reads
# ==========================================================================
def set_clock(instant: str = CLOCK_START_UTC) -> dict:
    """Point the logical clock at `instant`. Mutates no entity."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


def read_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_client_contract(contract_id, ADMIN))


def contract_version(contract_id: str) -> int:
    return read_contract(contract_id)["version"]


def read_staff(staff_id: str) -> dict:
    return get_success_data(api_client.get_staff_member(staff_id, ADMIN))


def read_credential(credential_id: str) -> dict:
    return get_success_data(api_client.get_staff_credential(credential_id, ADMIN))


def read_room(room_id: str) -> dict:
    return get_success_data(api_client.get_facility_room(room_id, ADMIN))


def read_asset(asset_id: str) -> dict:
    return get_success_data(api_client.get_facility_asset(asset_id, ADMIN))


def read_offering(offering_id: str) -> dict:
    return get_success_data(api_client.get_program_offering(offering_id, ADMIN))


def read_session(session_id: str) -> dict:
    return get_success_data(api_client.get_program_session(session_id, ADMIN))


def read_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_staff_assignment(assignment_id, ADMIN))


def read_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def member_version(member_id: str) -> int:
    return read_member(member_id)["version"]


def read_waiver(waiver_id: str) -> dict:
    return get_success_data(api_client.get_liability_waiver(waiver_id, ADMIN))


def read_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_monthly_invoice(invoice_id, ADMIN))


def read_participation_record(record_id: str) -> dict:
    return get_success_data(api_client.get_participation_record(record_id, ADMIN))


def read_incident(incident_id: str) -> dict:
    return get_success_data(api_client.get_incident_report(incident_id, ADMIN))


def read_attainment(offering_id: str) -> dict:
    return get_success_data(api_client.get_offering_attainment(offering_id, ADMIN))


# ==========================================================================
# Tier 1 — contract origination and state progression
# ==========================================================================
def create_draft_contract(fee_structure: str = "COST_PLUS", **overrides) -> dict:
    """Create one contract in DRAFT. A distinct site_code is minted per call so
    several sites can coexist inside one test."""
    seq = _next_seq()
    if fee_structure == "MANAGEMENT_FEE":
        overrides.setdefault("site_code", f"AXL-{seq:02d}")
        payload = management_fee_contract_payload(**overrides)
    else:
        overrides.setdefault("site_code", f"NWM-{seq:02d}")
        payload = client_contract_payload(**overrides)
    return get_success_data(api_client.create_client_contract(payload, ADMIN))


def hire_staff(contract_id: str, headers=None, **overrides) -> dict:
    """Hire one staff member onto a contract's site."""
    seq = _next_seq()
    defaults = {"full_name": f"Staff {seq}"}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_staff_member(
            staff_member_payload(contract_id, **defaults), headers or ADMIN
        )
    )


def file_credential(staff_member_id: str, headers=None, **overrides) -> dict:
    seq = _next_seq()
    defaults = {"credential_number": f"CRD-{seq:04d}"}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_staff_credential(
            staff_credential_payload(staff_member_id, **defaults), headers or ADMIN
        )
    )


def file_and_verify_credential(staff_member_id: str, headers=None, **overrides) -> dict:
    """File a certification and accept it, so the holder ends up VERIFIED."""
    credential = file_credential(staff_member_id, headers=headers, **overrides)
    return get_success_data(
        api_client.verify_credential(
            credential["id"], {"decision": "ACCEPT"}, headers or ADMIN
        )
    )


def record_drill(staff_member_id: str, drill_on: str = None, headers=None) -> dict:
    return get_success_data(
        api_client.record_drill(
            staff_member_id,
            {"drill_on": drill_on or TEST_DEFAULTS["DRILL_ON"], "drill_type": "AED_RESPONSE"},
            headers or ADMIN,
        )
    )


def create_site_manager(contract_id: str, **overrides) -> dict:
    """Hire a SITE_MANAGER with a VERIFIED CPR_AED credential.

    Returns {"staff": ..., "headers": ..., "credential": ...}.
    """
    manager = hire_staff(
        contract_id,
        role_type="SITE_MANAGER",
        full_name=overrides.pop("full_name", "Dana Reed"),
        hourly_cost_cents=overrides.pop(
            "hourly_cost_cents", TEST_DEFAULTS["MANAGER_HOURLY_COST_CENTS"]
        ),
        **overrides,
    )
    credential = file_and_verify_credential(
        manager["id"],
        credential_type="CPR_AED",
        issuer="American Heart Association",
        expires_on=TEST_DEFAULTS["TERM_END_ON"],
    )
    return {
        "staff": manager,
        "headers": make_site_manager_headers(manager["id"]),
        "credential": credential,
    }


def setup_draft_contract(fee_structure: str = "COST_PLUS", **overrides) -> dict:
    """Logical clock pinned, one DRAFT contract, one credentialed site manager.

    Returns the scenario dict shared by every richer helper below.
    """
    set_clock(CLOCK_START_UTC)
    contract = create_draft_contract(fee_structure, **overrides)
    manager = create_site_manager(contract["id"])
    return {
        "contract": contract,
        "contract_id": contract["id"],
        "manager": manager["staff"],
        "manager_id": manager["staff"]["id"],
        "manager_headers": manager["headers"],
        "manager_credential": manager["credential"],
        "sponsor_headers": make_client_sponsor_headers(contract["id"]),
        "admin_headers": ADMIN,
        "auditor_headers": AUDITOR,
    }


def setup_active_contract(fee_structure: str = "COST_PLUS", **overrides) -> dict:
    """Walk a contract DRAFT -> PENDING_CLIENT_APPROVAL -> ACTIVE."""
    scenario = setup_draft_contract(fee_structure, **overrides)
    get_success_data(
        api_client.submit_client_contract(scenario["contract_id"], ADMIN)
    )
    get_success_data(
        api_client.client_decision(
            scenario["contract_id"], {"decision": "APPROVE"}, scenario["sponsor_headers"]
        )
    )
    scenario["contract"] = read_contract(scenario["contract_id"])
    return scenario


# ==========================================================================
# Tier 2 — the physical plant
# ==========================================================================
def add_room(scenario: dict, **overrides) -> dict:
    seq = _next_seq()
    defaults = {"room_name": f"Studio {seq}"}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_facility_room(
            facility_room_payload(scenario["contract_id"], **defaults),
            scenario["manager_headers"],
        )
    )


def add_ready_aed(scenario: dict, room_id: str = None, **overrides) -> dict:
    """Register a defibrillator whose consumables are far from expiry and whose
    last inspection is recent, so its readiness_status is READY."""
    seq = _next_seq()
    defaults = {"asset_tag": f"AED-{seq:02d}"}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_facility_asset(
            aed_asset_payload(
                scenario["contract_id"], room_id or scenario["room_id"], **defaults
            ),
            scenario["manager_headers"],
        )
    )


def add_cardio_asset(scenario: dict, room_id: str = None, **overrides) -> dict:
    seq = _next_seq()
    defaults = {"asset_tag": f"TRD-{seq:02d}"}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_facility_asset(
            cardio_asset_payload(
                scenario["contract_id"], room_id or scenario["room_id"], **defaults
            ),
            scenario["manager_headers"],
        )
    )


def setup_active_site(fee_structure: str = "COST_PLUS", **overrides) -> dict:
    """ACTIVE contract + one OPEN room + one READY defibrillator."""
    scenario = setup_active_contract(fee_structure, **overrides)
    room = add_room(scenario, room_name="Studio A")
    scenario["room"] = room
    scenario["room_id"] = room["id"]
    aed = add_ready_aed(scenario, room["id"])
    scenario["aed"] = aed
    scenario["aed_id"] = aed["id"]
    return scenario


# ==========================================================================
# Tier 3 — programming
# ==========================================================================
def add_instructor(
    scenario: dict,
    credential_type: str = "GROUP_EX_CERT",
    with_drill: bool = True,
    **overrides,
) -> dict:
    """Hire a GROUP_EX_INSTRUCTOR, verify the named credential and (by default)
    record a recent drill so the readiness index reaches 100."""
    seq = _next_seq()
    role_type = overrides.pop("role_type", "GROUP_EX_INSTRUCTOR")
    instructor = hire_staff(
        scenario["contract_id"],
        role_type=role_type,
        full_name=overrides.pop("full_name", f"Instructor {seq}"),
        hourly_cost_cents=overrides.pop(
            "hourly_cost_cents", TEST_DEFAULTS["INSTRUCTOR_HOURLY_COST_CENTS"]
        ),
        **overrides,
    )
    credential = file_and_verify_credential(
        instructor["id"], credential_type=credential_type, issuer="ACE"
    )
    if with_drill:
        record_drill(instructor["id"], headers=scenario["manager_headers"])
    return {
        "staff": read_staff(instructor["id"]),
        "credential": credential,
        "headers": make_fitness_staff_headers(instructor["id"]),
    }


def add_offering(scenario: dict, lead_staff_id: str = None, **overrides) -> dict:
    seq = _next_seq()
    defaults = {"title": f"Lunch Circuit {seq}"}
    defaults.update(overrides)
    return get_success_data(
        api_client.create_program_offering(
            program_offering_payload(
                scenario["contract_id"],
                lead_staff_id or scenario["instructor_id"],
                **defaults,
            ),
            scenario["manager_headers"],
        )
    )


def activate_offering(scenario: dict, offering_id: str) -> dict:
    return get_success_data(
        api_client.offering_status_change(
            offering_id, {"action": "ACTIVATE"}, scenario["manager_headers"]
        )
    )


def setup_active_program(fee_structure: str = "COST_PLUS", **overrides) -> dict:
    """The workhorse: ACTIVE contract, OPEN room, READY defibrillator, a
    credentialed and drilled instructor, and one ACTIVE offering led by them."""
    offering_overrides = overrides.pop("offering_overrides", {})
    scenario = setup_active_site(fee_structure, **overrides)
    instructor = add_instructor(scenario)
    scenario["instructor"] = instructor["staff"]
    scenario["instructor_id"] = instructor["staff"]["id"]
    scenario["instructor_headers"] = instructor["headers"]
    scenario["instructor_credential"] = instructor["credential"]
    offering = add_offering(scenario, title="Lunch Circuit", **offering_overrides)
    activate_offering(scenario, offering["id"])
    scenario["offering"] = read_offering(offering["id"])
    scenario["offering_id"] = offering["id"]
    return scenario


# ==========================================================================
# Tier 3b — sessions, assignments and their lifecycles
# ==========================================================================
def schedule_session(scenario: dict, offering_id: str = None, room_id: str = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_program_session(
            program_session_payload(
                offering_id or scenario["offering_id"],
                room_id or scenario["room_id"],
                **overrides,
            ),
            scenario["manager_headers"],
        )
    )


def assign_staff(scenario: dict, session_id: str, staff_member_id: str = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_assignment(
            staff_assignment_payload(
                session_id, staff_member_id or scenario["instructor_id"], **overrides
            ),
            scenario["manager_headers"],
        )
    )


def confirm_assignment(scenario: dict, assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.confirm_assignment(
            assignment_id, headers or scenario["manager_headers"]
        )
    )


def staff_session(scenario: dict, session_id: str, staff_member_id: str = None) -> dict:
    """Create a LEAD assignment and confirm it, so the session becomes STAFFED."""
    assignment = assign_staff(
        scenario, session_id, staff_member_id, role_on_session="LEAD"
    )
    confirm_assignment(scenario, assignment["id"])
    return read_assignment(assignment["id"])


def setup_staffed_session(scenario: dict = None, **session_overrides) -> tuple:
    """ACTIVE program + one STAFFED session. Returns (scenario, session,
    lead_assignment)."""
    scenario = scenario or setup_active_program()
    session = schedule_session(scenario, **session_overrides)
    assignment = staff_session(scenario, session["id"])
    return scenario, read_session(session["id"]), assignment


def start_session(scenario: dict, session_id: str, clock_at: str = None) -> dict:
    """Move a STAFFED session to IN_PROGRESS, pointing the clock at the start
    instant first when asked."""
    if clock_at:
        set_clock(clock_at)
    return get_success_data(
        api_client.session_status_change(
            session_id, {"action": "START"}, scenario["manager_headers"]
        )
    )


def complete_session(scenario: dict, session_id: str) -> dict:
    return get_success_data(
        api_client.session_status_change(
            session_id, {"action": "COMPLETE"}, scenario["manager_headers"]
        )
    )


def cancel_session(scenario: dict, session_id: str, cancel_reason: str) -> dict:
    return get_success_data(
        api_client.session_status_change(
            session_id,
            {"action": "CANCEL", "cancel_reason": cancel_reason},
            scenario["manager_headers"],
        )
    )


def setup_in_progress_session(scenario: dict = None, **session_overrides) -> tuple:
    """ACTIVE program + one session started at its scheduled start instant.
    Returns (scenario, session, lead_assignment)."""
    scenario, session, assignment = setup_staffed_session(scenario, **session_overrides)
    start_session(scenario, session["id"], clock_at=session["scheduled_start_utc"])
    return scenario, read_session(session["id"]), assignment


def add_committed_minutes(
    scenario: dict,
    staff_member_id: str,
    minutes: int,
    start_utc: str = "2026-09-01T00:00:00Z",
    role_on_session: str = "SUPPORT",
) -> dict:
    """Book exactly `minutes` of paid time onto a staff member by scheduling a
    session of that length in a room of its own and assigning them to it as
    SUPPORT (a SUPPORT assignment is paid the session's scheduled minutes).

    Returns the created assignment.
    """
    from datetime import datetime, timedelta, timezone

    start = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    end = start + timedelta(minutes=minutes)
    room = add_room(scenario, max_occupancy=5)
    session = schedule_session(
        scenario,
        room_id=room["id"],
        scheduled_start_utc=start_utc,
        scheduled_end_utc=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        forecast_attendance=0,
    )
    return assign_staff(
        scenario, session["id"], staff_member_id, role_on_session=role_on_session
    )


# ==========================================================================
# Tier 4 — membership
# ==========================================================================
def enrol_member(scenario: dict, **overrides) -> dict:
    seq = _next_seq()
    defaults = {"full_name": f"Member {seq}", "employee_number": f"E-{1000 + seq}"}
    defaults.update(overrides)
    if defaults.get("member_class") in ("DEPENDENT", "RETIREE"):
        defaults["employee_number"] = None
    return get_success_data(
        api_client.create_member(
            member_payload(scenario["contract_id"], **defaults),
            scenario["sponsor_headers"],
        )
    )


def verify_member(scenario: dict, member_id: str) -> dict:
    return get_success_data(
        api_client.eligibility_decision(
            member_id, {"action": "VERIFY"}, scenario["sponsor_headers"]
        )
    )


def file_waiver(scenario: dict, member_id: str, headers=None, **overrides) -> dict:
    """File a liability waiver, reading the member's current version first so
    the mandatory stale-read guard is satisfied."""
    return get_success_data(
        api_client.create_waiver(
            member_id,
            waiver_payload(member_version(member_id), **overrides),
            headers or scenario["manager_headers"],
        )
    )


def grant_badge(scenario: dict, member_id: str, badge_number: str = None) -> dict:
    return get_success_data(
        api_client.badge_access(
            member_id,
            {"action": "GRANT", "badge_number": badge_number or "B-1001"},
            scenario["manager_headers"],
        )
    )


def setup_ready_member(scenario: dict, **overrides) -> dict:
    """Enrol a member, verify eligibility, file a signed waiver and grant the
    badge — the state a check-in requires."""
    member = enrol_member(scenario, **overrides)
    verify_member(scenario, member["id"])
    waiver = file_waiver(scenario, member["id"])
    grant_badge(scenario, member["id"])
    member = read_member(member["id"])
    member["_waiver"] = waiver
    member["_headers"] = make_member_headers(member["id"])
    return member


def check_in(scenario: dict, member_id: str, session_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_participation_record(
            participation_payload(member_id, session_id, **overrides),
            headers or scenario["instructor_headers"],
        )
    )


def void_participation(scenario: dict, record_id: str, void_reason: str = "Wrong member scanned") -> dict:
    return get_success_data(
        api_client.void_participation_record(
            record_id, {"void_reason": void_reason}, scenario["manager_headers"]
        )
    )


# ==========================================================================
# Tier 5 — invoicing and period close
# ==========================================================================
def draft_invoice(scenario: dict, period_month: str = "2026-08", **overrides) -> dict:
    """Draft an invoice, reading the contract's current version first so the
    mandatory stale-read guard is satisfied."""
    return get_success_data(
        api_client.create_monthly_invoice(
            invoice_payload(
                scenario["contract_id"],
                contract_version(scenario["contract_id"]),
                period_month=period_month,
                **overrides,
            ),
            ADMIN,
        )
    )


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, ADMIN))


def dispute_invoice(scenario: dict, invoice_id: str, reason: str = "Line items queried") -> dict:
    return get_success_data(
        api_client.dispute_invoice(
            invoice_id, {"dispute_reason": reason}, scenario["sponsor_headers"]
        )
    )


def setup_completed_session_for_billing(scenario: dict = None) -> dict:
    """One 55-minute session staffed by a LEAD and a SUPPORT worker, both paid
    at the same hourly cost, started and completed so both assignments settle
    their labor cost and enter the period's billing.

    Returns the scenario augmented with `session`, `lead_assignment`,
    `support_assignment` and `support_staff`.
    """
    scenario = scenario or setup_active_program()
    support = add_instructor(scenario, with_drill=False, full_name="Mia Chen")
    session = schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
        direct_supply_cost_cents=23522,
    )
    lead = assign_staff(scenario, session["id"], role_on_session="LEAD")
    sup = assign_staff(
        scenario, session["id"], support["staff"]["id"], role_on_session="SUPPORT"
    )
    confirm_assignment(scenario, lead["id"])
    confirm_assignment(scenario, sup["id"])
    start_session(scenario, session["id"], clock_at="2026-08-05T12:00:00Z")
    complete_session(scenario, session["id"])
    scenario["session"] = read_session(session["id"])
    scenario["lead_assignment"] = read_assignment(lead["id"])
    scenario["support_assignment"] = read_assignment(sup["id"])
    scenario["support_staff"] = support["staff"]
    return scenario


def setup_uncovered_sessions(scenario: dict, count: int, start_day: int = 5) -> list:
    """Schedule `count` sessions and cancel each with cancel_reason NO_COVER,
    driving the contract's uncovered_session_count up by `count`."""
    sessions = []
    for index in range(count):
        day = start_day + index
        session = schedule_session(
            scenario,
            scheduled_start_utc=f"2026-08-{day:02d}T12:00:00Z",
            scheduled_end_utc=f"2026-08-{day:02d}T12:55:00Z",
            forecast_attendance=3,
        )
        cancel_session(scenario, session["id"], "NO_COVER")
        sessions.append(read_session(session["id"]))
    return sessions


def setup_asset_downtime(scenario: dict, asset_id: str, out_on: str, back_on: str) -> dict:
    """Take an asset out of service at `out_on` and repair it at `back_on`,
    accruing the outage into out_of_service_days_current_period."""
    set_clock(out_on)
    get_success_data(
        api_client.create_service_event(
            asset_id,
            {"event_type": "TAKE_OUT_OF_SERVICE", "note": "Fault reported"},
            scenario["manager_headers"],
        )
    )
    set_clock(back_on)
    payload = {"event_type": "REPAIR_COMPLETE", "note": "Repaired"}
    asset = read_asset(asset_id)
    if asset["asset_type"] == "AED":
        payload["pad_expiry_on"] = TEST_DEFAULTS["AED_PAD_EXPIRY_ON"]
        payload["battery_expiry_on"] = TEST_DEFAULTS["AED_BATTERY_EXPIRY_ON"]
    get_success_data(
        api_client.create_service_event(asset_id, payload, scenario["manager_headers"])
    )
    return read_asset(asset_id)


def run_readiness_sweep(contract_id: str) -> dict:
    return get_success_data(
        api_client.daily_readiness_run({"contract_id": contract_id}, ADMIN)
    )


# ==========================================================================
# Incidents
# ==========================================================================
def file_incident(scenario: dict, reported_by_staff_id: str = None, **overrides) -> dict:
    from .factories import incident_report_payload

    reporter = reported_by_staff_id or scenario["instructor_id"]
    return get_success_data(
        api_client.create_incident_report(
            incident_report_payload(scenario["contract_id"], reporter, **overrides),
            make_fitness_staff_headers(reporter),
        )
    )


def review_incident(scenario: dict, incident_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.review_incident(
            incident_id, overrides or {}, headers or scenario["manager_headers"]
        )
    )
