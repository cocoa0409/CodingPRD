"""Transitions that a row on a different entity refuses to allow.

Two gates in this domain read a field the caller cannot touch in the same
request. Provisioning a booked tester's access consults the tester's own
clearance row, and starting fieldwork consults the counter-signature on the
rules-of-engagement document. In both cases the same request is sent twice,
unchanged, and flips from refusal to success purely because the other entity
moved in between.
"""

from test_helpers import (
    advance_clock,
    assert_engagement_axes,
    assert_error_id,
    assert_exact_int,
    assert_hour_ledger,
    assert_instant_equals,
    build_scenario,
    compliance_officer_headers,
    success_data,
)
from test_helpers.api_errors import (
    ERR_ENGAGEMENT_NOT_AUTHORIZED,
    ERR_INVALID_EXECUTION_TRANSITION,
    ERR_TESTER_NOT_CLEARED,
)
from test_helpers.constants import T_BEFORE_ASSIGNMENT
from test_helpers.test_users import CO_USER_ID, PM_USER_ID


def _booking_for_an_uncleared_tester(client):
    """Book a tester whose background check has deliberately not been recorded."""
    return build_scenario(client, stage="assignment", background_check_result=None)


def _clear_the_tester(client, tester_id):
    """A ComplianceOfficer records the clearance that unblocks provisioning."""
    return success_data(
        client.record_background_check(
            tester_id, "CLEARED", headers=compliance_officer_headers()
        )
    )


class TestProvisioningDependsOnTesterClearance:
    """The assignment cannot be provisioned until the tester's own row says CLEARED."""

    def test_the_grant_is_bookable_while_the_tester_is_still_pending(self, client):
        """Booking reads no clearance field, so the row is created against a PENDING tester.

        PRD: "Their `background_check_status` opens at `PENDING`, their `background_check_at` is null, their `availability_state` opens at `PENDING_CLEARANCE`, and their `active_assignment_count` — the number of assignments they hold in the provisioned access state — opens at 0."
        PRD: "An accepted booking opens at `REQUESTED` access state, with `provisioned_at` and `revoked_at` null and `settled_hours` at 0."
        PRD: "This deliberate re-check at provisioning time, rather than at booking time, is what keeps least privilege honest: authorization can shrink between the two moments."

        Design: Difficulty/cross_entity_state_dependency/access_provisioning_depends_on_tester_clearance_state
        """
        scenario = _booking_for_an_uncleared_tester(client)

        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert tester["background_check_status"] == "PENDING", (
            f"background_check_status: expected PENDING, got "
            f"{tester['background_check_status']}"
        )
        assert tester["availability_state"] == "PENDING_CLEARANCE", (
            f"availability_state: expected PENDING_CLEARANCE, got "
            f"{tester['availability_state']}"
        )
        assert tester["background_check_at"] is None
        assert scenario["assignment"]["access_state"] == "REQUESTED", (
            f"access_state: expected REQUESTED, got "
            f"{scenario['assignment']['access_state']}"
        )

    def test_provisioning_is_refused_while_the_clearance_is_missing(self, client):
        """A field on the tester entity, not on the assignment, blocks the transition.

        PRD: "It then re-verifies the human: the tester's `background_check_status` must be `CLEARED`, refused with `ERR_TESTER_NOT_CLEARED` if it is anything else, and their `clearance_expires_at` must lie strictly after the current instant, refused with `ERR_CLEARANCE_EXPIRED` when the expiry has arrived or passed."

        Design: Difficulty/cross_entity_state_dependency/access_provisioning_depends_on_tester_clearance_state
        """
        scenario = _booking_for_an_uncleared_tester(client)

        response = client.set_access(scenario["assignment_id"], "PROVISION")

        assert_error_id(response, ERR_TESTER_NOT_CLEARED)
        assert response.status_code == 422, (
            f"expected HTTP 422 for an uncleared tester, got {response.status_code}"
        )
        assignment = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert assignment["access_state"] == "REQUESTED", (
            "a refused provisioning must leave the grant at REQUESTED, "
            f"got {assignment['access_state']}"
        )

    def test_recording_the_clearance_moves_only_the_tester_row(self, client):
        """The clearance is written on the tester and stamped from the clock.

        PRD: "On success the result is written to `background_check_status`, `background_check_at` is stamped with the current instant, and `availability_state` advances `PENDING_CLEARANCE` → `AVAILABLE` (or `SUSPENDED` → `AVAILABLE`, which is how a re-cleared tester rejoins the roster)."

        Design: Difficulty/cross_entity_state_dependency/access_provisioning_depends_on_tester_clearance_state
        """
        scenario = _booking_for_an_uncleared_tester(client)
        client.set_access(scenario["assignment_id"], "PROVISION")

        tester = _clear_the_tester(client, scenario["tester_id"])

        assert tester["background_check_status"] == "CLEARED"
        assert tester["availability_state"] == "AVAILABLE", (
            f"availability_state: expected AVAILABLE, got {tester['availability_state']}"
        )
        assert_instant_equals(
            tester["background_check_at"], T_BEFORE_ASSIGNMENT, "background_check_at"
        )
        assignment = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert assignment["access_state"] == "REQUESTED", (
            "clearing the tester must not provision the grant by itself"
        )

    def test_the_identical_provision_call_then_succeeds(self, client):
        """Nothing about the request changed; only the tester's row did.

        PRD: "On success the assignment moves `REQUESTED` → `PROVISIONED`, `provisioned_at` is stamped with the current instant, the tester's `active_assignment_count` is incremented, and the tester's `availability_state` moves `AVAILABLE` → `ASSIGNED` (a tester already at `ASSIGNED` stays there, since the state reflects "holds at least one live grant" rather than a count)."
        PRD: "Its `requested_hours` are added to the engagement's `hours_reserved`, `hours_available` is recomputed as the allocation minus reserved minus consumed, and the engagement's `version` advances."

        Design: Difficulty/cross_entity_state_dependency/access_provisioning_depends_on_tester_clearance_state
        """
        scenario = _booking_for_an_uncleared_tester(client)
        client.set_access(scenario["assignment_id"], "PROVISION")
        _clear_the_tester(client, scenario["tester_id"])

        assignment = success_data(client.set_access(scenario["assignment_id"], "PROVISION"))

        assert assignment["access_state"] == "PROVISIONED", (
            f"access_state: expected PROVISIONED, got {assignment['access_state']}"
        )
        assert_instant_equals(
            assignment["provisioned_at"], T_BEFORE_ASSIGNMENT, "provisioned_at"
        )
        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert tester["availability_state"] == "ASSIGNED"
        assert_exact_int(tester["active_assignment_count"], 1, "active_assignment_count")
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=40, consumed=0, available=40)


SIGNATURE_NOTE = "Authorized for the FY2026 window"


def _engagement_with_an_unsigned_document(client):
    """Charter an engagement and draft its document, but do not counter-sign it."""
    scenario = build_scenario(
        client,
        stage="targets",
        roe={"exclusions": ["prod-db-01"], "allowed_techniques": ["SQLI", "XSS"]},
        target={"technique_allowlist": ["SQLI", "XSS"]},
    )
    advance_clock(client, T_BEFORE_ASSIGNMENT)
    return scenario


class TestFieldworkDependsOnTheCountersignature:
    """The execution axis cannot leave PLANNED until another entity is signed."""

    def test_the_engagement_opens_pending_against_a_drafted_document(self, client):
        """Both axes open at their initial values and the document opens at DRAFT.

        PRD: "The new engagement opens with `execution_state` at `PLANNED` and `authorization_state` at `ROE_PENDING`, with a null `suspension_reason` and with both `provisional_assurance_score` and `final_assurance_score` null."
        PRD: "The server stamps `drafted_by_user_id` from `X-User-ID`, opens the document at `DRAFT` status, and sets `active_target_count` to 0."

        Design: Difficulty/cross_entity_state_dependency/engagement_start_depends_on_rules_of_engagement_signature
        """
        scenario = _engagement_with_an_unsigned_document(client)

        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(
            engagement, execution_state="PLANNED", authorization_state="ROE_PENDING"
        )
        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert document["status"] == "DRAFT", (
            f"document status: expected DRAFT, got {document['status']}"
        )
        assert document["drafted_by_user_id"] == PM_USER_ID, (
            f"drafted_by_user_id: expected {PM_USER_ID}, "
            f"got {document['drafted_by_user_id']}"
        )

    def test_starting_fieldwork_is_refused_before_the_countersignature(self, client):
        """The authorization gate speaks, not the execution-transition complaint.

        PRD: "It requires the authorization axis to be `AUTHORIZED`: an engagement still at `ROE_PENDING` or already at `TERMINATED` is refused with `ERR_ENGAGEMENT_NOT_AUTHORIZED`, while a `SUSPENDED` engagement is refused with `ERR_ENGAGEMENT_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/engagement_start_depends_on_rules_of_engagement_signature
        """
        scenario = _engagement_with_an_unsigned_document(client)

        response = client.drive_execution(scenario["engagement_id"], "START")

        payload = assert_error_id(response, ERR_ENGAGEMENT_NOT_AUTHORIZED)
        assert response.status_code == 409, (
            f"expected HTTP 409 for an unauthorized engagement, got {response.status_code}"
        )
        assert payload["error_id"] != ERR_INVALID_EXECUTION_TRANSITION, (
            "the cross-entity authorization gate answers ahead of the transition check"
        )
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(engagement, execution_state="PLANNED")

    def test_signing_the_document_moves_only_the_authorization_axis(self, client):
        """The signature reaches across into the engagement, but not into its work.

        PRD: "On success the document moves `DRAFT` → `SIGNED`, `signed_by_user_id` is stamped from `X-User-ID` and `signed_at` from the current instant, and — the cross-record effect that matters most — the engagement's authorization axis moves `ROE_PENDING` → `AUTHORIZED`."
        PRD: "An engagement carries **two independent state axes**, and confusing them is the most common modelling error in this domain."

        Design: Difficulty/cross_entity_state_dependency/engagement_start_depends_on_rules_of_engagement_signature
        """
        scenario = _engagement_with_an_unsigned_document(client)
        client.drive_execution(scenario["engagement_id"], "START")

        document = success_data(
            client.sign_rules_of_engagement(
                scenario["roe_id"], signature_note=SIGNATURE_NOTE
            )
        )

        assert document["status"] == "SIGNED", (
            f"document status: expected SIGNED, got {document['status']}"
        )
        assert document["signed_by_user_id"] == CO_USER_ID, (
            f"signed_by_user_id: expected {CO_USER_ID}, got {document['signed_by_user_id']}"
        )
        assert_instant_equals(document["signed_at"], T_BEFORE_ASSIGNMENT, "signed_at")
        assert_exact_int(document["active_target_count"], 1, "active_target_count")
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(
            engagement, execution_state="PLANNED", authorization_state="AUTHORIZED"
        )

    def test_the_identical_start_call_then_succeeds(self, client):
        """The same request is accepted because the other entity was signed.

        PRD: "Fieldwork begins with a start action on the engagement, which either a `ProgramManager` or a `Tester` may issue and which moves the execution axis `PLANNED` → `EXECUTING`."

        Design: Difficulty/cross_entity_state_dependency/engagement_start_depends_on_rules_of_engagement_signature
        """
        scenario = _engagement_with_an_unsigned_document(client)
        client.drive_execution(scenario["engagement_id"], "START")
        client.sign_rules_of_engagement(scenario["roe_id"], signature_note=SIGNATURE_NOTE)

        engagement = success_data(client.drive_execution(scenario["engagement_id"], "START"))

        assert_engagement_axes(
            engagement, execution_state="EXECUTING", authorization_state="AUTHORIZED"
        )
