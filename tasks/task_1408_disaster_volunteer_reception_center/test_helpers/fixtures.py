"""Composite setup helpers for multi-step test prerequisites.

The readiness pipeline (credential -> vetting -> background check -> verify ->
briefing + waiver -> mark-ready) and the assignment pipeline (request -> publish
-> shift -> open-roster -> propose -> accept -> confirm) each take ~10 API
calls, so they are encapsulated here. All helpers use get_success_data() so a
setup failure raises a clear "Setup step failed" error.

Identity threading: after a volunteer is created, every ownership-gated call
(accept/decline/withdraw/resubmit, hour-entry creation by the volunteer) uses
make_volunteer_headers(volunteer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_incident_payload, create_volunteer_payload, create_credential_payload,
    create_background_check_payload, create_clearance_payload,
    create_support_request_payload, create_shift_payload, create_assignment_payload,
    create_trip_payload, create_seat_booking_payload, create_ppe_issuance_payload,
    create_hour_entry_payload, create_risk_report_payload,
)
from .constants import TEST_DEFAULTS
from .test_users import TEST_USERS, make_volunteer_headers

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
VET = TEST_USERS["vetting_headers"]
LOGI = TEST_USERS["logistics_headers"]
SITE = TEST_USERS["supervisor_headers"]
RISK = TEST_USERS["risk_headers"]
AGENCY = TEST_USERS["agency_headers"]


def set_clock(to_iso8601: str):
    """Advance the logical clock (also fires the expiry sweep)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, MGR))


def _vol_headers(volunteer) -> dict:
    return make_volunteer_headers(volunteer["id"])


# --- Tier 1: incident state progression ---

def create_incident(clock: str = None, **overrides):
    """Pin the clock (default 2026-08-01T00:00:00Z) and create an incident."""
    set_clock(clock or "2026-08-01T00:00:00Z")
    return get_success_data(api_client.create_incident(create_incident_payload(**overrides), MGR))


def create_active_incident(clock: str = None, **overrides):
    """Incident created and activated (lifecycle ACTIVE, posture OPEN)."""
    incident = create_incident(clock=clock, **overrides)
    return get_success_data(api_client.activate_incident(incident["id"], MGR))


def create_demobilizing_incident(**overrides):
    """Incident walked ACTIVATION -> ACTIVE -> DEMOBILIZATION (no checked-in work)."""
    incident = create_active_incident(**overrides)
    get_success_data(api_client.begin_demobilization(incident["id"], MGR))
    return get_success_data(api_client.get_incident(incident["id"], MGR))


# --- Tier 2: volunteers and the readiness pipeline ---

def register_volunteer(incident_id: str, registrar_headers=None, **overrides):
    """Register a volunteer (REGISTERED). Registrar defaults to intake-1."""
    return get_success_data(api_client.create_volunteer(
        create_volunteer_payload(incident_id, **overrides),
        registrar_headers or INTAKE,
    ))


def vet_volunteer(incident_id: str, volunteer=None, credential_overrides=None,
                  with_clearances=True, mark_ready=True, registrar_headers=None,
                  **vol_overrides):
    """Drive a volunteer to CLEARED or READY.

    Credential CLAIMED -> submit-for-vetting -> background check CLEARED ->
    credential VERIFIED (-> safety briefing + liability waiver -> mark-ready).
    Returns dict with volunteer/credential/background_check/clearances.
    """
    if volunteer is None:
        volunteer = register_volunteer(incident_id, registrar_headers=registrar_headers,
                                       **vol_overrides)
    credential = get_success_data(api_client.create_credential(
        create_credential_payload(volunteer["id"], **(credential_overrides or {})), INTAKE))
    get_success_data(api_client.submit_for_vetting(volunteer["id"], INTAKE))
    check = get_success_data(api_client.create_background_check(
        create_background_check_payload(volunteer["id"]), VET))
    get_success_data(api_client.clear_background_check(check["id"], VET))
    credential = get_success_data(api_client.verify_credential(credential["id"], VET))
    result = {"volunteer": volunteer, "credential": credential, "background_check": check,
              "briefing": None, "waiver": None}
    if with_clearances:
        result["briefing"] = get_success_data(api_client.create_clearance(
            create_clearance_payload(volunteer["id"], "SAFETY_BRIEFING"), INTAKE))
        result["waiver"] = get_success_data(api_client.create_clearance(
            create_clearance_payload(volunteer["id"], "LIABILITY_WAIVER"), INTAKE))
    if mark_ready:
        get_success_data(api_client.mark_ready(volunteer["id"], INTAKE))
    result["volunteer"] = get_success_data(api_client.get_volunteer(volunteer["id"], MGR))
    return result


def create_ready_volunteer(incident_id: str, **kwargs):
    """Fully vetted READY volunteer. Returns the volunteer resource."""
    return vet_volunteer(incident_id, **kwargs)["volunteer"]


def refresh_briefing(volunteer_id: str):
    """Record a fresh ACTIVE safety briefing at the current logical instant."""
    return get_success_data(api_client.create_clearance(
        create_clearance_payload(volunteer_id, "SAFETY_BRIEFING"), INTAKE))


# --- Tier 3: requests, shifts, assignments ---

def create_published_request(incident_id: str, **overrides):
    request = get_success_data(api_client.create_support_request(
        create_support_request_payload(incident_id, **overrides), AGENCY))
    return get_success_data(api_client.publish_support_request(request["id"], AGENCY))


def create_open_shift(incident_id: str, **overrides):
    shift = get_success_data(api_client.create_shift(
        create_shift_payload(incident_id, **overrides), LOGI))
    return get_success_data(api_client.open_roster(shift["id"], LOGI))


def propose_assignment(volunteer, request, shift):
    return get_success_data(api_client.create_assignment(
        create_assignment_payload(volunteer["id"], request["id"], shift["id"]), INTAKE))


def propose_accept_assignment(volunteer, request, shift):
    assignment = propose_assignment(volunteer, request, shift)
    return get_success_data(api_client.accept_assignment(
        assignment["id"], _vol_headers(volunteer)))


def propose_accept_confirm_assignment(volunteer, request, shift):
    """Walk an assignment to CONFIRMED (debits committed_hours)."""
    assignment = propose_accept_assignment(volunteer, request, shift)
    return get_success_data(api_client.confirm_assignment(assignment["id"], INTAKE))


def issue_ppe(volunteer_id: str, item_type: str = "GLOVES", quantity: int = 1):
    return get_success_data(api_client.create_ppe_issuance(
        create_ppe_issuance_payload(volunteer_id, item_type=item_type, quantity=quantity),
        LOGI))


def check_in_and_complete(assignment, volunteer_id: str, at: str):
    """Refresh the briefing, move the clock, check in, complete.

    Returns the COMPLETED assignment. The assignment must be CONFIRMED and the
    volunteer must hold at least one ISSUED PPE record (call issue_ppe first).
    A refresh that hits the one-active-briefing rule simply means the current
    briefing is still valid, so it is tolerated.
    """
    set_clock(at)
    refresh_res = api_client.create_clearance(
        create_clearance_payload(volunteer_id, "SAFETY_BRIEFING"), INTAKE)
    if refresh_res.status_code >= 400:
        body = refresh_res.json()
        error_id = (body.get("data") or {}).get("error_id")
        assert error_id == "ERR_CLEARANCE_ALREADY_ACTIVE", (
            f"briefing refresh failed unexpectedly: {error_id}")
    get_success_data(api_client.check_in_assignment(assignment["id"], SITE))
    return get_success_data(api_client.complete_assignment(assignment["id"], SITE))


def create_completed_assignment_with_entry(volunteer, request, shift,
                                           work_date: str, hours: float,
                                           checkin_at: str, submit_as: str = "volunteer",
                                           ppe_item: str = "GLOVES"):
    """Full lifecycle: confirm -> PPE -> check-in -> complete -> SUBMITTED entry.

    Returns (assignment, entry). Entry is submitted by the volunteer themselves
    (submitted_by = volunteer id) unless submit_as == "supervisor".

    The check-in gate requires at least one PPE issuance still ISSUED for the
    volunteer, so PPE is issued here only when the volunteer does not already
    hold one — re-issuing on every call would drain the incident's ppe_stock.
    """
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    existing = get_success_data(api_client.list_volunteer_ppe_issuances(
        volunteer["id"], LOGI, params={"status": "ISSUED"}))
    if not existing:
        issue_ppe(volunteer["id"], item_type=ppe_item)
    assignment = check_in_and_complete(assignment, volunteer["id"], checkin_at)
    if submit_as == "volunteer":
        headers = _vol_headers(volunteer)
    else:
        headers = SITE
    entry = get_success_data(api_client.create_hour_entry(
        create_hour_entry_payload(assignment["id"], work_date=work_date, hours=hours),
        headers))
    return assignment, entry


def create_verified_entry(volunteer, request, shift, work_date: str, hours: float,
                          checkin_at: str, verifier_headers=None, **kwargs):
    """COMPLETED assignment with its hour entry VERIFIED. Returns (assignment, entry)."""
    assignment, entry = create_completed_assignment_with_entry(
        volunteer, request, shift, work_date, hours, checkin_at, **kwargs)
    entry = get_success_data(api_client.verify_hour_entry(
        entry["id"], verifier_headers or SITE))
    return assignment, entry


# --- Tier 4: risk ---

def file_and_substantiate_report(volunteer_id: str, severity: str,
                                 occurred_at: str = "2026-08-01T00:00:00Z",
                                 category: str = "OTHER",
                                 description: str = "reported conduct concern"):
    """File a report (reporter site-1) and substantiate it (risk-1, SoD-clean)."""
    report = get_success_data(api_client.create_risk_report(
        create_risk_report_payload(volunteer_id, severity=severity, category=category,
                                   description=description, occurred_at=occurred_at),
        SITE))
    return get_success_data(api_client.substantiate_risk_report(report["id"], RISK))
