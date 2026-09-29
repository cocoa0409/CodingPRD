"""Transitions on one entity gated by the state of another: match activation on the
mentor's certification, and packet submission on the cohort's closure.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_COHORT_STATE_INVALID,
    ERR_LICENSE_RECOMMENDATION_MISSING,
    ERR_MENTOR_NOT_CERTIFIED,
)
from test_helpers.fixtures import (
    build_program,
    read_cohort,
    read_match,
    read_mentor,
    read_novice,
    read_packet,
    read_site,
)
from test_helpers.test_users import ADMIN


class TestMatchActivationRequiresCertifiedMentor:
    """The same activation request fails and then succeeds as the mentor moves."""

    @staticmethod
    def _proposed_match_with_a_suspended_mentor(api: InductionApiClient) -> dict:
        program = build_program(api, activate=False)
        validate_success(
            api.certification_action(
                program["mentor_id"],
                f.certification_payload(
                    "SUSPEND", reason="Fingerprint clearance expired pending renewal"
                ),
                ADMIN,
            )
        )
        return program

    def test_activation_is_refused_while_the_mentor_is_suspended(
        self, api: InductionApiClient
    ):
        """A SUSPENDED mentor cannot have a proposal activated onto them.

        The PRD gates the transition on the other entity: "It requires the match
        to be `PROPOSED`, the mentor to be `CERTIFIED` with a
        `certification_expires_on` strictly after the current logical time
        (otherwise `ERR_MENTOR_NOT_CERTIFIED`), the mentor's site to be `OPEN`".

        Design: Difficulty/cross_entity_state_dependency/match_activation_requires_certified_mentor
        """
        program = self._proposed_match_with_a_suspended_mentor(api)

        response = api.dispose_match(
            program["match_id"], f.disposition_payload("ACTIVATE"), ADMIN
        )
        validate_error(response, ERR_MENTOR_NOT_CERTIFIED, 422)

        match = read_match(api, program["match_id"])
        assert match["match_status"] == "PROPOSED", (
            f"the refused activation leaves the match proposed, got {match['match_status']}"
        )
        assert match["pinned_stipend_rate_cents_per_hour"] is None, (
            "nothing is pinned by a refused activation, got "
            f"{match['pinned_stipend_rate_cents_per_hour']}"
        )
        assert read_mentor(api, program["mentor_id"])["active_caseload_count"] == 0, (
            "no slot is consumed by a refused activation"
        )

    def test_reinstating_the_mentor_lets_the_identical_request_through(
        self, api: InductionApiClient
    ):
        """Reinstatement flips the gate and the same activation pins the EXACT rate.

        Nothing about the request changes; only the other entity's state does.
        The PRD lists what a successful activation writes: "On success the match
        stamps `activated_at` from the logical clock, pins
        `pinned_stipend_rate_cents_per_hour` from the tier — 4200 cents per hour
        for `EXACT`, 3600 for `ADJACENT`, 2800 for `CROSS` — increments the
        mentor's `active_caseload_count` and the site's `active_match_count` by
        one each, moves the novice from `MATCHED` to `ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/match_activation_requires_certified_mentor
        """
        program = self._proposed_match_with_a_suspended_mentor(api)
        validate_error(
            api.dispose_match(program["match_id"], f.disposition_payload("ACTIVATE"), ADMIN),
            ERR_MENTOR_NOT_CERTIFIED,
            422,
        )

        mentor = validate_success(
            api.certification_action(
                program["mentor_id"], f.certification_payload("REINSTATE"), ADMIN
            )
        )
        assert mentor["certification_status"] == "CERTIFIED", (
            f"reinstatement returns the mentor to CERTIFIED, got "
            f"{mentor['certification_status']}"
        )

        match = validate_success(
            api.dispose_match(program["match_id"], f.disposition_payload("ACTIVATE"), ADMIN)
        )
        assert match["match_status"] == "ACTIVE", (
            f"the identical request now succeeds, got {match['match_status']}"
        )
        assert match["pinned_stipend_rate_cents_per_hour"] == 4200, (
            "a MATH mentor matched to a MATH novice pins the EXACT rate, got "
            f"{match['pinned_stipend_rate_cents_per_hour']}"
        )
        assert read_mentor(api, program["mentor_id"])["active_caseload_count"] == 1
        assert read_site(api, program["site_id"])["active_match_count"] == 1
        assert read_novice(api, program["novice_id"])["program_status"] == "ACTIVE"


class TestPacketSubmissionRequiresClosedCohort:
    """The cohort gate blocks submission, and closing it moves the refusal one rung down."""

    @staticmethod
    def _assembling_packet_in_a_forming_cohort(api: InductionApiClient) -> dict:
        program = build_program(api)
        novice = read_novice(api, program["novice_id"])
        packet = validate_success(
            api.create_packet(f.packet_payload(program["novice_id"], novice["version"]), ADMIN),
            201,
        )
        program["packet_id"] = packet["id"]
        return program

    def test_submission_is_refused_while_the_cohort_is_still_forming(
        self, api: InductionApiClient
    ):
        """A packet cannot go to the state until the novice's cohort has closed.

        The PRD names the cohort as the first of the submission gates: "The packet
        is re-scored first, and then every one of the following must hold: the
        novice's cohort must be `CLOSED`, or the submission is refused with
        `ERR_COHORT_STATE_INVALID`".

        Design: Difficulty/cross_entity_state_dependency/packet_submission_requires_closed_cohort
        """
        program = self._assembling_packet_in_a_forming_cohort(api)
        assert read_cohort(api, program["cohort_id"])["status"] == "FORMING"

        response = api.packet_transition(
            program["packet_id"], f.packet_transition_payload("SUBMIT"), ADMIN
        )
        validate_error(response, ERR_COHORT_STATE_INVALID, 422)

        packet = read_packet(api, program["packet_id"])
        assert packet["packet_status"] == "ASSEMBLING", (
            f"the refused submission leaves the packet assembling, got "
            f"{packet['packet_status']}"
        )
        assert packet["submitted_at"] is None, (
            "no submission instant is stamped by a refused submission"
        )

    def test_closing_the_cohort_clears_that_gate_and_exposes_the_next_one(
        self, api: InductionApiClient
    ):
        """Once the cohort is CLOSED the same request is stopped by the licence rung.

        The refusal moving from rung 20 to rung 33 is what proves the cohort gate
        itself cleared: "The novice's `license_advancement_status` is
        `RECOMMENDED` — otherwise `ERR_LICENSE_RECOMMENDATION_MISSING` (HTTP 422)
        on packet submission."

        Design: Difficulty/cross_entity_state_dependency/packet_submission_requires_closed_cohort
        """
        program = self._assembling_packet_in_a_forming_cohort(api)
        validate_error(
            api.packet_transition(
                program["packet_id"], f.packet_transition_payload("SUBMIT"), ADMIN
            ),
            ERR_COHORT_STATE_INVALID,
            422,
        )

        cohort = validate_success(
            api.close_cohort(program["cohort_id"], f.close_cohort_payload("CLOSED"), ADMIN)
        )
        assert cohort["status"] == "CLOSED", (
            f"a cohort with no scheduled session can be closed, got {cohort['status']}"
        )

        response = api.packet_transition(
            program["packet_id"], f.packet_transition_payload("SUBMIT"), ADMIN
        )
        error = validate_error(response, ERR_LICENSE_RECOMMENDATION_MISSING, 422)
        assert error["error_id"] != ERR_COHORT_STATE_INVALID, (
            "the cohort gate has cleared, so the refusal must come from a later rung"
        )

        assert read_packet(api, program["packet_id"])["packet_status"] == "ASSEMBLING"
        assert read_novice(api, program["novice_id"])["license_advancement_status"] == (
            "NOT_ELIGIBLE"
        ), "with no milestone attained the novice never reached RECOMMENDED"
