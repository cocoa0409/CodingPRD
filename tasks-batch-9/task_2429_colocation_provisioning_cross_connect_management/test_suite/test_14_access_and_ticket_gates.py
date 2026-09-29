"""Access and ticket gates: contact scopes, biometric enrollment, the half-open visit
window, the escort naming rule, and the cabinet-to-contract footprint test.
"""

from datetime import datetime

from test_helpers import assertions as ax, factories as f, fixtures as fx
from test_helpers import (
    SECURITY_OFFICER_1_ID,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(value, str), f"expected an ISO 8601 UTC timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), f"{label}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Contact scopes on a remote-hands ticket
# ---------------------------------------------------------------------------


def test_ticket_raised_by_a_contact_without_the_remote_hands_scope_is_refused(
    api, provisioning_engineer_headers
):
    """PRD §3.6: "The contract must be `ACTIVE` and free of credit hold, reporting `ERR_CONTRACT_NOT_ACTIVE` and `ERR_CREDIT_HOLD_ACTIVE` respectively; the requesting contact must sit on the owning customer's authorization list and hold the `REMOTE_HANDS` scope, otherwise `ERR_CONTACT_NOT_AUTHORIZED`; and the target cabinet's `contract_id` must equal the named contract, otherwise `ERR_CABINET_NOT_ON_CONTRACT`."
    PRD §3.7: "A `CustomerAdmin` or a `SecurityOfficer` adds a contact under a `customer_id` with a `full_name` and `authorization_scopes`, a non-empty subset of `REMOTE_HANDS`, which permits raising and authorizing hands-and-eyes work, and `SITE_ACCESS`, which permits visits."

    Design: Corner/validations/ticket_raised_by_a_contact_without_the_remote_hands_scope_is_refused
    """
    scenario = fx.setup_installed_cabinet(api)
    site_access_only = fx.create_contact(
        api, scenario.customer_id, authorization_scopes=["SITE_ACCESS"]
    )

    validate_error(
        api.create_remote_hands_ticket(
            f.create_remote_hands_ticket_payload(
                scenario.contract_id,
                site_access_only["id"],
                scenario.cabinet_id,
                severity="HIGH",
            ),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_CONTACT_NOT_AUTHORIZED,
    )

    tickets, meta = validate_paginated(
        api.list_remote_hands_tickets(
            provisioning_engineer_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 0, f"a refused raise must persist no ticket, got {tickets}"


# ---------------------------------------------------------------------------
# Biometric enrollment
# ---------------------------------------------------------------------------


def test_check_in_before_biometric_enrollment_is_refused(api, security_officer_headers):
    """PRD §3.7: "Checking a `SCHEDULED` visit in requires the visiting contact's `biometric_state` to be `ENROLLED`, otherwise `ERR_BIOMETRIC_NOT_ENROLLED` — scheduling before enrollment is allowed, entering is not — and requires the logical clock to lie inside the half-open window, at or after `window_start` and strictly before `window_end`, otherwise `ERR_OUTSIDE_VISIT_WINDOW`; both early and late arrivals are refused."
    PRD §3.7: "Every contact starts with `biometric_state` `NOT_ENROLLED` and no `enrolled_at`."
    PRD §3.7: "Enrolling stamps `enrolled_at` from the logical clock."
    PRD §3.7: "On success `checked_in_at` is stamped from the logical clock, the escorting officer is recorded, and the visit's `version` increments."

    Design: Corner/validations/check_in_before_biometric_enrollment_is_refused
    """
    scenario = fx.setup_visit_scenery(api, access_level="UNESCORTED", enrolled=False)
    contact = scenario.contact
    assert contact["biometric_state"] == "NOT_ENROLLED", (
        f"a new contact is not enrolled, got {contact['biometric_state']}"
    )
    visit = fx.schedule_visit(api, scenario, "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")
    fx.set_clock(api, "2026-08-01T09:30:00Z")

    validate_error(
        api.set_access_visit_state(
            visit["id"], f.state_payload("CHECKED_IN"), security_officer_headers
        ),
        ApiErrorId.ERR_BIOMETRIC_NOT_ENROLLED,
    )
    held = fx.read_visit(api, visit["id"])
    assert held["status"] == "SCHEDULED", (
        f"a refused check-in leaves the visit SCHEDULED, got {held['status']}"
    )

    enrolled = validate_success(
        api.set_contact_biometric_state(
            contact["id"], f.state_payload("ENROLLED"), security_officer_headers
        )
    )
    assert enrolled["biometric_state"] == "ENROLLED"
    _assert_same_instant(
        enrolled["enrolled_at"], "2026-08-01T09:30:00Z", "contact.enrolled_at"
    )

    checked_in = validate_success(
        api.set_access_visit_state(
            visit["id"], f.state_payload("CHECKED_IN"), security_officer_headers
        )
    )
    assert checked_in["status"] == "CHECKED_IN", (
        f"the same request now succeeds, got {checked_in['status']}"
    )
    _assert_same_instant(
        checked_in["checked_in_at"], "2026-08-01T09:30:00Z", "visit.checked_in_at"
    )


# ---------------------------------------------------------------------------
# The half-open visit window
# ---------------------------------------------------------------------------


def test_check_in_one_second_before_the_window_opens_is_refused(api, security_officer_headers):
    """PRD §3.7: "Checking a `SCHEDULED` visit in requires the visiting contact's `biometric_state` to be `ENROLLED`, otherwise `ERR_BIOMETRIC_NOT_ENROLLED` — scheduling before enrollment is allowed, entering is not — and requires the logical clock to lie inside the half-open window, at or after `window_start` and strictly before `window_end`, otherwise `ERR_OUTSIDE_VISIT_WINDOW`; both early and late arrivals are refused."
    PRD §3.7: "On success `checked_in_at` is stamped from the logical clock, the escorting officer is recorded, and the visit's `version` increments."

    Design: Corner/validations/check_in_outside_the_booked_window_is_refused
    """
    scenario = fx.setup_visit_scenery(api, access_level="UNESCORTED", enrolled=True)
    visit = fx.schedule_visit(api, scenario, "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")

    fx.set_clock(api, "2026-08-01T08:59:59Z")
    validate_error(
        api.set_access_visit_state(
            visit["id"], f.state_payload("CHECKED_IN"), security_officer_headers
        ),
        ApiErrorId.ERR_OUTSIDE_VISIT_WINDOW,
    )
    held = fx.read_visit(api, visit["id"])
    assert held["status"] == "SCHEDULED", (
        f"an early arrival leaves the visit SCHEDULED, got {held['status']}"
    )
    assert held.get("checked_in_at") is None, "a refused check-in stamps nothing"

    # The window start is inclusive, so the very next second is admitted.
    fx.set_clock(api, "2026-08-01T09:00:00Z")
    checked_in = validate_success(
        api.set_access_visit_state(
            visit["id"], f.state_payload("CHECKED_IN"), security_officer_headers
        )
    )
    assert checked_in["status"] == "CHECKED_IN", (
        f"the inclusive window start admits the visitor, got {checked_in['status']}"
    )
    _assert_same_instant(
        checked_in["checked_in_at"], "2026-08-01T09:00:00Z", "visit.checked_in_at"
    )


# ---------------------------------------------------------------------------
# Naming the escorting officer
# ---------------------------------------------------------------------------


def test_meet_me_check_in_without_a_named_escort_is_refused(api, security_officer_headers):
    """PRD §3.7: "When `escort_required` is true the request must name the escorting officer in `escort_officer_user_id`, and when it is false the request must not supply one; either mismatch is refused with `ERR_ESCORT_REQUIRED`."
    PRD §3.7: "It is true when any one of three conditions holds: the contact's `access_level` is `ESCORTED_ONLY`, or the visit's `purpose` is `CARRIER_INSTALL`, or the target cabinet's `footprint_type` is `MEET_ME`."
    PRD §3.7: "On success `checked_in_at` is stamped from the logical clock, the escorting officer is recorded, and the visit's `version` increments."

    Design: Corner/validations/meet_me_check_in_without_a_named_escort_is_refused
    """
    scenario = fx.setup_visit_scenery(
        api,
        cabinet={"footprint_type": "MEET_ME"},
        access_level="UNESCORTED",
        enrolled=True,
    )
    visit = fx.schedule_visit(api, scenario, "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")
    assert visit["escort_required"] is True, (
        "the meet-me footprint pins escort_required true at booking"
    )
    fx.set_clock(api, "2026-08-01T09:30:00Z")

    validate_error(
        api.set_access_visit_state(
            visit["id"], f.state_payload("CHECKED_IN"), security_officer_headers
        ),
        ApiErrorId.ERR_ESCORT_REQUIRED,
    )
    held = fx.read_visit(api, visit["id"])
    assert held["status"] == "SCHEDULED", (
        f"an unescorted check-in leaves the visit SCHEDULED, got {held['status']}"
    )

    checked_in = validate_success(
        api.set_access_visit_state(
            visit["id"],
            f.state_payload("CHECKED_IN", escort_officer_user_id=SECURITY_OFFICER_1_ID),
            security_officer_headers,
        )
    )
    assert checked_in["status"] == "CHECKED_IN", (
        f"naming the officer admits the visitor, got {checked_in['status']}"
    )
    assert checked_in["escort_officer_user_id"] == SECURITY_OFFICER_1_ID, (
        "the escorting officer is recorded on the visit"
    )


# ---------------------------------------------------------------------------
# The cabinet-to-contract footprint test
# ---------------------------------------------------------------------------


def test_ticket_targeting_a_cabinet_outside_the_contract_footprint_is_refused(
    api, provisioning_engineer_headers
):
    """PRD §3.6: "The contract must be `ACTIVE` and free of credit hold, reporting `ERR_CONTRACT_NOT_ACTIVE` and `ERR_CREDIT_HOLD_ACTIVE` respectively; the requesting contact must sit on the owning customer's authorization list and hold the `REMOTE_HANDS` scope, otherwise `ERR_CONTACT_NOT_AUTHORIZED`; and the target cabinet's `contract_id` must equal the named contract, otherwise `ERR_CABINET_NOT_ON_CONTRACT`."
    PRD §3.3: "New cabinets open with `status` `AVAILABLE` and no `contract_id`; because an `AVAILABLE` cabinet occupies no slot, creating one does not move the row's density ceiling, though the row's capacity picture is recomputed anyway."
    PRD §3.6: "`authorization_state` walks `PENDING_AUTHORIZATION` → `AUTHORIZED`, `PENDING_AUTHORIZATION` → `DENIED` or `AUTHORIZED` → `REVOKED`, while `execution_state` walks `QUEUED` → `DISPATCHED` → `COMPLETED`, with `CANCELLED` as its abandonment state and `IN_PROGRESS` as an intermediate execution value."
    PRD §3.6: "Both dimensions start at their initial values when the ticket is raised."

    Design: Corner/validations/ticket_targeting_a_cabinet_outside_the_contract_footprint_is_refused
    """
    scenario = fx.setup_installed_cabinet(api, cabinet={"cabinet_code": "C01"})
    contact = fx.create_contact(
        api, scenario.customer_id, authorization_scopes=["REMOTE_HANDS"]
    )
    foreign = fx.create_cabinet(api, scenario.row_id, cabinet_code="C02")
    assert foreign["contract_id"] is None, "the second cabinet belongs to no contract"

    validate_error(
        api.create_remote_hands_ticket(
            f.create_remote_hands_ticket_payload(
                scenario.contract_id, contact["id"], foreign["id"], severity="HIGH"
            ),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_CABINET_NOT_ON_CONTRACT,
    )

    # The identical request against the contract's own cabinet is accepted.
    ticket = validate_success(
        api.create_remote_hands_ticket(
            f.create_remote_hands_ticket_payload(
                scenario.contract_id, contact["id"], scenario.cabinet_id, severity="HIGH"
            ),
            provisioning_engineer_headers,
        ),
        expected_status=201,
    )
    ax.assert_remote_hands_ticket(ticket)
    assert ticket["authorization_state"] == "PENDING_AUTHORIZATION", (
        f"a raised ticket awaits authorization, got {ticket['authorization_state']}"
    )
    assert ticket["execution_state"] == "QUEUED", (
        f"a raised ticket queues execution, got {ticket['execution_state']}"
    )

    tickets, meta = validate_paginated(
        api.list_remote_hands_tickets(
            provisioning_engineer_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 1, f"only the accepted ticket exists, got {tickets}"
