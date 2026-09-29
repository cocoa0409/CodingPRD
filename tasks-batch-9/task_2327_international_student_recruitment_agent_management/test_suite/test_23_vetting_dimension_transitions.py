"""The due-diligence dimension: legal moves, refused moves and its cascade.

Each named action is defined only from certain states, the clearance gate reads
the checklist on top of the state, rejection reaches sideways into contract
paper, and the integrity dimension is never dragged along.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_version
from test_helpers.test_users import COMPLIANCE, OFFICER


def _vetting(client, agency_id, action, headers, **extra):
    return client.agency_vetting_action(
        agency_id, F.vetting_action_payload(action, **extra), headers
    )


class TestVettingMovesForward:
    def test_submitting_for_screening_advances_only_the_diligence_dimension(
        self, client
    ):
        """One dimension moves, the other stands still, the version counts once.

        "`SUBMIT_FOR_SCREENING`, taken by a `RecruitmentOfficer`, moves `DRAFT →
        SCREENING`."

        "each successful action increments the agency's `version`"

        Design: Corner/state_machines/vetting_submit_for_screening_valid_transition
        """
        agency = fx.register_agency(client, legal_name="Screening Agency")

        moved = validate_success(
            _vetting(
                client,
                agency["id"],
                C.VETTING_SUBMIT_FOR_SCREENING,
                OFFICER,
                note="Dossier complete",
            )
        )

        assert moved["vetting_state"] == C.VETTING_SCREENING
        assert moved["compliance_posture"] == C.POSTURE_GOOD_STANDING, (
            "the integrity dimension is untouched by a due-diligence action"
        )
        assert_version(moved, 2)


class TestVettingRefusesUndefinedMoves:
    def test_clearing_a_draft_agency_fails_on_state_before_the_checklist(self, client):
        """A complete checklist cannot rescue an undefined transition.

        "`CLEAR` moves `SCREENING → CLEARED`"

        "Any action that is not defined from the agency's current `vetting_state`
        is rejected with `ERR_INVALID_VETTING_STATE`; each successful action
        increments the agency's `version`."

        Design: Corner/state_machines/vetting_clear_from_draft_is_invalid_transition
        """
        agency = fx.register_agency(
            client,
            legal_name="Premature Clear Agency",
            beneficial_owner_count=2,
            reference_check_count=3,
        )

        response = _vetting(client, agency["id"], C.VETTING_CLEAR, COMPLIANCE)
        validate_error(response, E.ERR_INVALID_VETTING_STATE)

        unchanged = fx.read_agency(client, agency["id"])
        assert unchanged["vetting_state"] == C.VETTING_DRAFT
        assert_version(unchanged, 1)

    def test_a_rejected_agency_can_never_re_enter_the_screening_cycle(self, client):
        """Three different re-entry attempts all bounce off the terminal state.

        "`REJECT` moves `SCREENING → REJECTED`, and `RE_SCREEN` moves `CLEARED →
        SCREENING` for periodic re-diligence."

        "valued `DRAFT`, `SCREENING`, `INFO_REQUESTED`, `CLEARED` or `REJECTED`,
        beginning at `DRAFT`, with `REJECTED` terminal"

        Design: Corner/state_machines/rejected_agency_cannot_resubmit
        """
        agency = fx.register_agency(
            client, legal_name="Terminal Agency", complete_diligence=False
        )
        fx.screen_agency(client, agency["id"])
        rejected = validate_success(
            _vetting(client, agency["id"], C.VETTING_REJECT, COMPLIANCE)
        )
        assert rejected["vetting_state"] == C.VETTING_REJECTED
        version_after_rejection = rejected["version"]

        for action, headers in (
            (C.VETTING_RESUBMIT, OFFICER),
            (C.VETTING_RE_SCREEN, COMPLIANCE),
            (C.VETTING_SUBMIT_FOR_SCREENING, OFFICER),
        ):
            validate_error(
                _vetting(client, agency["id"], action, headers),
                E.ERR_INVALID_VETTING_STATE,
            )
            still = fx.read_agency(client, agency["id"])
            assert still["vetting_state"] == C.VETTING_REJECTED
            assert_version(still, version_after_rejection)


class TestClearanceGate:
    def test_one_missing_reference_check_blocks_the_clearance_until_it_is_filled(
        self, client
    ):
        """The gate fails on a single shortfall and reopens once it is fixed.

        "Beyond requiring the agency to be in `SCREENING`, `CLEAR` demands that
        the checklist be complete: `ownership_disclosed` must be true,
        `sanctions_screen_passed` must be true, `beneficial_owner_count` must be
        at least 1, and `reference_check_count` must be at least 2. Any shortfall
        is `ERR_DUE_DILIGENCE_INCOMPLETE`."

        "A `RecruitmentOfficer`, or the agency itself acting as `AgencyOwner`, may
        revise `legal_name`, `ownership_disclosed`, `beneficial_owner_count`,
        `sanctions_screen_passed` and `reference_check_count`"

        Design: Corner/state_machines/clear_with_incomplete_due_diligence_blocked
        """
        agency = fx.register_agency(
            client,
            legal_name="Diligence Gap Agency",
            beneficial_owner_count=1,
            reference_check_count=1,
        )
        fx.screen_agency(client, agency["id"])

        blocked = _vetting(client, agency["id"], C.VETTING_CLEAR, COMPLIANCE)
        validate_error(blocked, E.ERR_DUE_DILIGENCE_INCOMPLETE)
        assert (
            fx.read_agency(client, agency["id"])["vetting_state"]
            == C.VETTING_SCREENING
        ), "a failed gate leaves the agency waiting in screening"

        patched = validate_success(
            client.patch_agency(agency["id"], {"reference_check_count": 2}, OFFICER)
        )
        assert patched["reference_check_count"] == 2

        cleared = validate_success(
            _vetting(client, agency["id"], C.VETTING_CLEAR, COMPLIANCE)
        )
        assert cleared["vetting_state"] == C.VETTING_CLEARED


class TestRejectionCascade:
    def test_rejection_also_tears_down_the_agencys_unsigned_paper(self, client):
        """The state change is only half of what REJECT does.

        "Along with the state change, every one of that agency's contracts still
        in `DRAFT`, `PENDING_AGENCY_SIGNATURE` or `PENDING_COMPLIANCE_REVIEW` is
        driven to `TERMINATED` with `termination_reason_code` recorded as
        `NON_RENEWAL`."

        Design: Corner/state_machines/vetting_reject_terminates_pending_contracts
        """
        agency = fx.register_agency(client, legal_name="Reject Cascade Agency")
        fx.screen_agency(client, agency["id"])
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")

        rejected = validate_success(
            _vetting(
                client,
                agency["id"],
                C.VETTING_REJECT,
                COMPLIANCE,
                note="Adverse media on the beneficial owner",
            )
        )
        assert rejected["vetting_state"] == C.VETTING_REJECTED
        assert rejected["compliance_posture"] == C.POSTURE_GOOD_STANDING, (
            "the posture dimension is not touched by a vetting rejection"
        )

        torn_down = fx.read_contract(client, contract["id"])
        assert torn_down["status"] == C.CONTRACT_TERMINATED
        assert torn_down["termination_reason_code"] == C.TERMINATION_NON_RENEWAL


class TestDimensionIndependence:
    def test_posture_moves_and_returns_while_the_diligence_state_holds(self, client):
        """The combined state is the product of two independently driven dimensions.

        "The two run independently: every combination of the two dimensions is
        reachable except that neither terminal can be left."

        "`CLEAR_WATCH` moves `WATCH → GOOD_STANDING`, and only when
        `rolling_risk_score` is strictly below 40.00."

        "every posture change, manual or automatic, records the reason into
        `last_posture_reason` and increments the agency's `version`"

        Design: Corner/state_machines/vetting_and_posture_dimensions_are_independent
        """
        agency = fx.register_agency(client, legal_name="Parallel Dimensions Agency")
        fx.clear_agency(client, agency["id"])

        watched = fx.posture_action(
            client,
            agency["id"],
            C.POSTURE_PLACE_ON_WATCH,
            "Third-party complaint under review",
        )
        assert watched["compliance_posture"] == C.POSTURE_WATCH
        assert watched["vetting_state"] == C.VETTING_CLEARED
        assert watched["last_posture_reason"] == "Third-party complaint under review"

        restored = fx.posture_action(
            client, agency["id"], C.POSTURE_CLEAR_WATCH, "Complaint withdrawn"
        )
        assert restored["compliance_posture"] == C.POSTURE_GOOD_STANDING
        assert restored["vetting_state"] == C.VETTING_CLEARED

        re_screened = validate_success(
            _vetting(client, agency["id"], C.VETTING_RE_SCREEN, COMPLIANCE)
        )
        assert re_screened["vetting_state"] == C.VETTING_SCREENING
        assert re_screened["compliance_posture"] == C.POSTURE_GOOD_STANDING
        assert_version(re_screened, 6)
