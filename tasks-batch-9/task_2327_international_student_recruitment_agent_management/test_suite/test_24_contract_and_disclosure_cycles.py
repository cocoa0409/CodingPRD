"""Where the contract graph and the disclosure loop meet.

A new student file starts on both of its dimensions at once.  A replayed
signature is a refusal rather than a no-op.  The disclosure dimension can loop
back through issuance without limit.  And a suspended contract can only come
back once the agency's integrity standing lets it.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_version
from test_helpers.test_users import COMPLIANCE, OFFICER, make_agency_owner_headers


class TestApplicationInitialStates:
    def test_a_new_file_starts_on_both_dimensions_with_nothing_pinned(self, client):
        """Status and disclosure state are seeded independently and simultaneously.

        "The new application sits in `status` `DRAFT` and `disclosure_state`
        `NOT_ISSUED`, with `custody_agency_id` initialised to the recruiting
        `agency_id`, `pinned_contract_id`, `pinned_schedule_id`,
        `disclosure_template_version`, `disclosure_ack_token`,
        `disclosure_acknowledged_at`, `submitted_on`, `tier_snapshot_at_submission`"

        Design: Corner/state_machines/application_created_in_dual_initial_states
        """
        agency = fx.register_agency(
            client, legal_name="Initial State Agency", complete_diligence=False
        )
        program = fx.create_program(client)

        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )

        assert application["status"] == C.APPLICATION_DRAFT
        assert application["disclosure_state"] == C.DISCLOSURE_NOT_ISSUED

        assert application["disclosure_template_version"] is None
        assert application["disclosure_ack_token"] is None
        assert application["disclosure_acknowledged_at"] is None

        assert application["submitted_on"] is None
        assert application["pinned_contract_id"] is None
        assert application["pinned_schedule_id"] is None
        assert application["tier_snapshot_at_submission"] is None


class TestSignatureIsNotIdempotent:
    def test_replaying_the_agency_signature_is_refused_rather_than_ignored(
        self, client
    ):
        """The second call writes nothing at all, not even a fresh version.

        "`AGENCY_SIGN` moves `PENDING_AGENCY_SIGNATURE → PENDING_COMPLIANCE_REVIEW`
        and is reserved to the `AgencyOwner` whose `X-User-ID` equals the
        contract's `agency_id`. The signing identity is stamped into
        `agency_signed_by_user_id`."

        "An action that is not defined from the contract's current `status` is
        rejected with `ERR_INVALID_CONTRACT_STATE`, and every successful action
        increments the contract's `version`."

        Design: Corner/state_machines/second_agency_sign_rejected_as_non_idempotent
        """
        agency = fx.register_agency(client, legal_name="Double Sign Agency")
        fx.clear_agency(client, agency["id"])
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")
        fx.append_schedule(client, contract["id"], contract["version"])
        fx.send_contract_for_signature(client, contract["id"])
        signed = fx.agency_sign_contract(client, agency["id"], contract["id"])
        version_after_signature = signed["version"]

        replay = client.contract_lifecycle_action(
            contract["id"],
            F.lifecycle_payload(C.LIFECYCLE_AGENCY_SIGN),
            make_agency_owner_headers(agency["id"]),
        )
        validate_error(replay, E.ERR_INVALID_CONTRACT_STATE)

        unchanged = fx.read_contract(client, contract["id"])
        assert unchanged["status"] == C.CONTRACT_PENDING_COMPLIANCE_REVIEW
        assert unchanged["agency_signed_by_user_id"] == agency["id"]
        assert_version(unchanged, version_after_signature)


class TestDisclosureCyclesBackToIssued:
    @pytest.fixture()
    def amended_paper(self, client):
        """An issued disclosure invalidated by an amendment, with paper re-sent."""
        agency = fx.register_agency(client, legal_name="Disclosure Cycle Agency")
        fx.clear_agency(client, agency["id"])
        program = fx.create_program(client)
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")
        fx.append_schedule(client, contract["id"], contract["version"])
        fx.send_contract_for_signature(client, contract["id"])
        fx.agency_sign_contract(client, agency["id"], contract["id"])

        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )
        first_issue = fx.issue_disclosure(
            client, agency["id"], application["id"]
        )

        fx.request_amendment(
            client, contract["id"], "Commission clause reworded"
        )
        fx.send_contract_for_signature(client, contract["id"])

        return {
            "agency_id": agency["id"],
            "contract_id": contract["id"],
            "application_id": application["id"],
            "first_token": first_issue["disclosure_ack_token"],
        }

    def test_the_amendment_invalidates_the_disclosure_and_advances_the_template(
        self, client, amended_paper
    ):
        """The loop's downward leg: ISSUED falls back to INVALIDATED.

        "It increments `amendment_round`, increments `disclosure_template_version`,
        and clears `agency_signed_by_user_id` so the agency must sign the revised
        paper again. It also reaches into the student files: every application of
        that agency whose `disclosure_state` is `ISSUED` is driven to
        `INVALIDATED`."

        "In both cases `disclosure_ack_token` is cleared, so a fresh issuance is
        required before the student can acknowledge again."

        Design: Corner/state_machines/disclosure_reissue_after_invalidation_cycles
        """
        env = amended_paper

        application = fx.read_application(client, env["application_id"])
        assert application["disclosure_state"] == C.DISCLOSURE_INVALIDATED
        assert application["disclosure_ack_token"] is None

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["disclosure_template_version"] == 2
        assert contract["amendment_round"] == 1

    def test_re_issuing_mints_a_fresh_token_and_re_pins_the_new_template(
        self, client, amended_paper
    ):
        """The loop's upward leg: INVALIDATED climbs back to ISSUED.

        "Re-issuing from `INVALIDATED` follows the identical rule set:
        `INVALIDATED → ISSUED` re-pins the template version and replaces the
        previous token with a fresh one, discarding the old token."

        "The `NOT_ISSUED → ISSUED → ACKNOWLEDGED → INVALIDATED → ISSUED` cycle may
        repeat without limit; the disclosure dimension has no terminal state."

        Design: Corner/state_machines/disclosure_reissue_after_invalidation_cycles
        """
        env = amended_paper

        reissued = validate_success(
            client.application_disclosure(
                env["application_id"], F.disclosure_issue_payload(), OFFICER
            )
        )

        assert reissued["disclosure_state"] == C.DISCLOSURE_ISSUED
        assert reissued["disclosure_ack_token"] != env["first_token"], (
            "the superseded token must not be handed back a second time"
        )
        assert reissued["disclosure_template_version"] == 2


class TestReinstateIsGuardedByPosture:
    @pytest.fixture()
    def probation_suspended_partner(self, client):
        """An active partner whose contract was suspended by a probation cascade."""
        partner = fx.build_active_partner(
            client,
            legal_name="Guarded Reinstate Agency",
            contract_ref="CTR-001",
        )
        fx.posture_action(
            client,
            partner["agency_id"],
            C.POSTURE_PLACE_ON_PROBATION,
            "Pattern of misrepresentation alleged",
        )
        return partner

    def test_the_probation_cascade_suspends_the_paper_and_frees_the_country(
        self, client, probation_suspended_partner
    ):
        """One posture action reaches two hops down.

        "Either way, the probation transition suspends every contract of that
        agency that is in `ACTIVE`, recording `POSTURE_PROBATION` as each
        contract's `suspension_reason`, which in turn releases those contracts'
        active territories and invalidates their `DRAFT` applications'
        disclosures."

        Design: Corner/state_machines/contract_reinstate_guarded_by_agency_posture
        """
        partner = probation_suspended_partner

        contract = fx.read_contract(client, partner["contract_id"])
        assert contract["status"] == C.CONTRACT_SUSPENDED
        assert contract["suspension_reason"] == C.SUSPENSION_REASON_POSTURE_PROBATION

        assignments = fx.read_assignments(client, partner["contract_id"])
        assert len(assignments) == 1
        assert assignments[0]["status"] == C.ASSIGNMENT_RELEASED

    def test_reinstatement_waits_for_the_posture_and_never_restores_the_territory(
        self, client, probation_suspended_partner
    ):
        """The same call fails on probation and succeeds on watch.

        "`REINSTATE` moves `SUSPENDED → ACTIVE` and clears `suspension_reason`. It
        requires the agency's due-diligence dimension to be `CLEARED`, its
        integrity standing to be `GOOD_STANDING` or `WATCH`, and the current
        logical-clock date to be no later than the contract's `term_end_date`."

        "`REINSTATE` is the de-escalation and it lands on `WATCH`, never on
        `GOOD_STANDING`: from `PROBATION` or from `SUSPENDED` the agency returns to
        `WATCH`, and only when `rolling_risk_score` is strictly below 65.00."

        "Reinstatement restores the contract only — territory assignments released
        by the suspension are gone for good and must be re-created if the agency is
        to recruit in those countries again."

        Design: Corner/state_machines/contract_reinstate_guarded_by_agency_posture
        """
        partner = probation_suspended_partner

        blocked = client.contract_lifecycle_action(
            partner["contract_id"],
            F.lifecycle_payload(C.LIFECYCLE_REINSTATE),
            COMPLIANCE,
        )
        validate_error(blocked, E.ERR_AGENCY_POSTURE_BLOCKED)
        assert (
            fx.read_contract(client, partner["contract_id"])["status"]
            == C.CONTRACT_SUSPENDED
        )

        reinstated_agency = fx.posture_action(
            client,
            partner["agency_id"],
            C.POSTURE_REINSTATE,
            "Allegations unsubstantiated",
        )
        assert reinstated_agency["compliance_posture"] == C.POSTURE_WATCH

        revived = validate_success(
            client.contract_lifecycle_action(
                partner["contract_id"],
                F.lifecycle_payload(C.LIFECYCLE_REINSTATE),
                COMPLIANCE,
            )
        )
        assert revived["status"] == C.CONTRACT_ACTIVE
        assert revived["suspension_reason"] is None

        assignments = fx.read_assignments(client, partner["contract_id"])
        assert assignments[0]["status"] == C.ASSIGNMENT_RELEASED, (
            "a released territory is never brought back by reinstatement"
        )
