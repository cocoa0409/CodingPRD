"""Consult lifecycle: route, unroute, start, complete, close.

PRD §3.3 (route/unroute/decline), §3.4 (start), §3.7 (complete + close).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    approve_claim,
    assert_consult,
    close_consult,
    complete_consult,
    create_consult,
    create_patient,
    create_prescription,
    deny_claim,
    get_post_complete_claim_or_invoice,
    make_physician_headers,
    mark_paid_claim,
    mark_paid_invoice,
    occ_payload,
    re_get_consult,
    route_consult,
    route_consult_payload,
    setup_completed_consult,
    setup_completed_insurance_consult_for_billing,
    setup_completed_insurance_consult_with_followup,
    setup_in_progress_consult,
    setup_physician_with_license,
    setup_routed_consult,
    setup_two_physicians_one_consult,
    setup_two_physicians_one_consult_route_cycle,
    start_consult,
    unroute_consult,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 Routing — happy path + routing_basis
# ===========================================================================
class TestConsultRouting:

    def test_route_sets_physician_and_routing_basis(self, api):
        """PRD §3.3: "If one exists, the consult's physician_id is set,
        routing_basis is set to that matched license's license_type
        (so FULL_LICENSE or IMLC_EXPEDITED), the consult advances from
        REQUESTED to ROUTED".

        Claim: after route, status=ROUTED, physician_id is set,
        routing_basis=FULL_LICENSE (license_type was FULL).
        """
        physician, _, _, consult = setup_routed_consult(license_type="FULL")
        # routed_consult fixture already routes; re-read to confirm.
        refreshed = re_get_consult(consult["id"])
        assert refreshed["status"] == "ROUTED"
        assert refreshed["physician_id"] == physician["id"]
        assert refreshed["routing_basis"] == "FULL_LICENSE"

    def test_route_uses_imlc_basis_for_imlc_license(self, api):
        """PRD §3.3: "routing_basis is set to that matched license's
        license_type (so FULL_LICENSE or IMLC_EXPEDITED)".

        Claim: routing through an IMLC_EXPEDITED license writes
        routing_basis=IMLC_EXPEDITED.
        """
        physician, _, _, consult = setup_routed_consult(
            license_type="IMLC_EXPEDITED",
        )
        refreshed = re_get_consult(consult["id"])
        assert refreshed["status"] == "ROUTED"
        assert refreshed["routing_basis"] == "IMLC_EXPEDITED"

    def test_route_without_valid_license_rejected(self, api):
        """PRD §3.3: "If no such license exists the route is rejected
        with ERR_NO_VALID_LICENSE."

        Claim: a physician with NO license in the patient's
        present_state_code cannot be routed; returns ERR_NO_VALID_LICENSE.
        """
        from test_helpers import create_physician
        physician_with_license, _ = setup_physician_with_license(
            state_code="NY",
        )
        # Create a REQUESTED consult for a CA patient.
        physician_no_license = create_physician()
        patient = create_patient(home_state_code="CA")
        consult = create_consult(
            patient=patient, billing_mode="SELF_PAY",
            visit_tier="BRIEF", present_state_code="CA",
        )
        res = api.route_consult(
            consult["id"],
            route_consult_payload(
                physician_id=physician_no_license["id"],
                version=consult["version"],
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_NO_VALID_LICENSE")

    def test_route_already_routed_rejected_with_invalid_state(self, api):
        """PRD §2.6: "state-machine permissibility for the target
        resource (→ ERR_INVALID_STATE)".

        Claim: a second /route on a ROUTED consult returns
        ERR_INVALID_STATE.
        """
        physician, _, _, consult = setup_routed_consult()
        res = api.route_consult(
            consult["id"],
            route_consult_payload(physician_id=physician["id"]),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.3 Unroute — and the "no prescriptions" precondition
# ===========================================================================
class TestConsultUnroute:

    def test_unroute_clears_physician_and_routing_basis(self, api):
        """PRD §3.3: "the unroute clears physician_id and routing_basis
        to null and allows reassignment to another physician."

        Claim: after /unroute, consult.status=REQUESTED,
        physician_id=null, routing_basis=null.
        """
        physician, _, _, consult = setup_routed_consult()
        result = unroute_consult(consult=consult)
        assert result["status"] == "REQUESTED"
        assert result.get("physician_id") in (None, "")
        assert result.get("routing_basis") in (None, "")

    # PRD §3.3 "no prescription" precondition for unroute is not
    # observable through the API: prescriptions can only be drafted from
    # IN_PROGRESS (PRD §3.4), but unroute is defined only on the
    # ROUTED → REQUESTED edge (PRD §3.3). No public transition returns
    # an IN_PROGRESS consult back to ROUTED while preserving its
    # prescriptions, so the only path to satisfy both halves of the
    # precondition is through internal state manipulation the API does
    # not expose. Escalated to the summary under applies_to-scope.


# ===========================================================================
# §3.4 Start — re-check matched license status
# ===========================================================================
class TestConsultStart:

    def test_start_advances_routed_to_in_progress(self, api):
        """PRD §3.4: "Once a consult is ROUTED, the assigned physician
        advances it to IN_PROGRESS by starting the consult."

        Claim: a Physician starting a ROUTED consult advances it to
        IN_PROGRESS.
        """
        physician, _, _, consult = setup_routed_consult()
        result = start_consult(consult=consult, physician=physician)
        assert result["status"] == "IN_PROGRESS"

    def test_start_by_other_physician_rejected(self, api):
        """PRD §3.4: "Only the assigned physician — whose id must equal
        the consult's physician_id — may issue this start command."
        PRD §2.1: ownership check rejects with ERR_FORBIDDEN.

        Claim: a different Physician calling /start returns
        ERR_FORBIDDEN.
        """
        physician_a, physician_b, _, consult_routed = (
            setup_two_physicians_one_consult_route_cycle()
        )
        # Route to physician_a.
        consult_routed = route_consult(
            consult=consult_routed, physician=physician_a,
        )
        res = api.start_consult(
            consult_routed["id"],
            occ_payload(version=consult_routed["version"]),
            make_physician_headers(physician_b["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §3.4 / §3.7 Complete — drives the billing + follow-up cascade
# ===========================================================================
class TestConsultComplete:

    def test_complete_sets_base_charge_for_standard_tier(self, api):
        """PRD §3.7: "The base charge is read directly from the
        consult's visit_tier: a BRIEF consult is 5000 cents, a STANDARD
        consult is 10000 cents, and an EXTENDED consult is 18000 cents.
        That value is stored as base_charge_cents on the consult".

        Claim: completing a STANDARD self-pay consult sets
        base_charge_cents=10000.
        """
        _, _, _, consult = setup_completed_consult(
            billing_mode="SELF_PAY", visit_tier="STANDARD",
        )
        assert consult["status"] == "COMPLETED"
        assert consult["base_charge_cents"] == 10000

    def test_complete_sets_base_charge_for_brief_tier(self, api):
        """PRD §3.7: "The base charge is read directly from the
        consult's visit_tier: a BRIEF consult is 5000 cents, a STANDARD
        consult is 10000 cents, and an EXTENDED consult is 18000 cents."

        Claim: completing a BRIEF self-pay consult sets
        base_charge_cents=5000.
        """
        _, _, _, consult = setup_completed_consult(
            billing_mode="SELF_PAY", visit_tier="BRIEF",
        )
        assert consult["base_charge_cents"] == 5000

    def test_complete_sets_base_charge_for_extended_tier(self, api):
        """PRD §3.7: "The base charge is read directly from the
        consult's visit_tier: a BRIEF consult is 5000 cents, a STANDARD
        consult is 10000 cents, and an EXTENDED consult is 18000 cents."

        Claim: completing an EXTENDED self-pay consult sets
        base_charge_cents=18000.
        """
        _, _, _, consult = setup_completed_consult(
            billing_mode="SELF_PAY", visit_tier="EXTENDED",
        )
        assert consult["base_charge_cents"] == 18000


# ===========================================================================
# §3.7 Close — terminal-status precondition
# ===========================================================================
class TestConsultClose:

    def test_close_blocked_by_non_terminal_claim(self, api):
        """PRD §3.7: "The close requires that billing has reached a
        terminal status — when billing_mode is INSURANCE, the
        InsuranceClaim must be in PAID or DENIED". "A close attempted
        against non-terminal billing or follow-up is rejected with
        ERR_BILLING_NOT_TERMINAL."

        Claim: closing a COMPLETED consult whose claim is still
        SUBMITTED returns ERR_BILLING_NOT_TERMINAL.

        difficulty: cross_entity_state_dependency/consult_close_depends_on_claim_followup_terminal
        """
        physician, patient, consult, claim = (
            setup_completed_insurance_consult_with_followup()
        )
        assert claim["status"] == "SUBMITTED"
        res = api.close_consult(
            consult["id"], occ_payload(version=consult["version"]),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_BILLING_NOT_TERMINAL")

    # PRD §3.7 close-after-claim-paid-and-followup-terminal: the
    # "followup must be terminal" half of the close precondition needs
    # a portable surface to mutate the FollowUp. PRD does not pin a
    # list-followups-by-consult endpoint or a FOLLOWUP_SCHEDULED audit
    # event, so the FollowUp.id is not portably discoverable. Escalated
    # under cross-entity-cascade. The billing-only variant of the test
    # below covers the happy-path close.

    def test_close_succeeds_for_no_followup_after_claim_paid(self, api):
        """PRD §3.7: "If no follow-up was created (because
        requires_followup was false), that clause is vacuous."

        Claim: a COMPLETED consult with requires_followup=false closes
        once the claim is PAID, even though no followup exists.
        """
        physician, _, patient, consult, claim = (
            setup_completed_insurance_consult_for_billing(
                requires_followup=False,
            )
        )
        claim = approve_claim(claim=claim)
        claim = mark_paid_claim(claim=claim)
        assert claim["status"] == "PAID"
        from test_helpers import re_get_consult
        consult = re_get_consult(consult["id"])
        res = api.close_consult(
            consult["id"], occ_payload(version=consult["version"]),
            TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(res, 200)
        assert data["status"] == "CLOSED"


# ===========================================================================
# §3.3 / §3.4 / §3.7 Invalid state transitions
# ===========================================================================
class TestInvalidStateTransitions:

    def test_start_from_requested_rejected(self, api):
        """PRD §3.4: "Once a consult is ROUTED, the assigned physician
        advances it to IN_PROGRESS by starting the consult."
        PRD §2.6: "state-machine permissibility for the target resource
        (→ ERR_INVALID_STATE)".

        Claim: /start on a REQUESTED consult returns ERR_INVALID_STATE.
        """
        physician, _ = setup_physician_with_license()
        patient = create_patient(home_state_code="CA")
        consult = create_consult(
            patient=patient, billing_mode="SELF_PAY",
            visit_tier="BRIEF", present_state_code="CA",
        )
        res = api.start_consult(
            consult["id"], occ_payload(version=consult["version"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_complete_from_routed_rejected(self, api):
        """PRD §3.7: "Once treatment is finished and every prescription
        under the consult is in a non-DRAFT state ... the assigned
        physician completes the consult."
        PRD §2.6: "state-machine permissibility for the target resource
        (→ ERR_INVALID_STATE)".

        Claim: /complete on a ROUTED consult returns ERR_INVALID_STATE.
        """
        physician, _, _, consult = setup_routed_consult()
        res = api.complete_consult(
            consult["id"], occ_payload(version=consult["version"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_close_from_in_progress_rejected(self, api):
        """PRD §3.7: "Finally, a completed consult may be closed by a
        compliance officer."
        PRD §2.6: "state-machine permissibility for the target resource
        (→ ERR_INVALID_STATE)".

        Claim: /close on an IN_PROGRESS consult returns
        ERR_INVALID_STATE.
        """
        _, _, _, consult = setup_in_progress_consult()
        res = api.close_consult(
            consult["id"], occ_payload(version=consult["version"]),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
