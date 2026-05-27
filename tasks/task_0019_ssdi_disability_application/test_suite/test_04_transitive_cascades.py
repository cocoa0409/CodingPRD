"""Transitive cascades: CDR cessation → Application/Award/Children/Supplement;
hearing cancel → Application reverts to RECONSIDERATION."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    set_clock,
    setup_application_awarded,
    setup_hearing_in_requested,
    create_child_auxiliary,
    fetch_cdr_for_award, start_cdr, complete_cdr,
    make_claimant_headers,
)


# =========================================================================
# Instance: cdr_cessation_cascade_application_award_children_supplement
# =========================================================================

class TestCdrCessationCascadeApplicationAwardChildrenSupplement:
    """Depth-3 cascade from CDR completion (CESSATION) → application
    CESSATION → award TERMINATED → children TERMINATED_PARENT → supplement
    TERMINATED."""

    def test_cessation_cascades_application_award_and_children(self, api):
        """PRD §3.9: "A `CESSATION` outcome is far more consequential: the
        application transitions from `CDR_FROZEN` to the terminal
        `CESSATION` state, the underlying `BenefitAward` is moved to
        `TERMINATED` (refreshing its `updated_at` and incrementing its
        `version`), every `ChildAuxiliaryBenefit` attached to that award
        is moved to `TERMINATED_PARENT`, and any associated `SSISupplement`
        is moved to `TERMINATED`."

        Design: Difficulty/transitive_cascade/cdr_cessation_cascade_application_award_children_supplement
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "4040",
                "full_name": "CDR Cease",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "CA",
                "monthly_income_cents": 0,
                "countable_resources_cents": 100_000,
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "CONCURRENT_SSDI_SSI",
            },
        )
        app_id = ctx["application"]["id"]
        award = ctx["award"]
        child = create_child_auxiliary(
            award["id"],
            expected_benefit_award_version=award["version"],
            child_full_name="Cease Child",
            child_date_of_birth="2015-01-01T00:00:00Z",
        )
        # Advance time past the scheduled CDR review.
        cdr = fetch_cdr_for_award(award["id"])
        set_clock("2028-01-15T00:00:00Z")
        start_cdr(cdr["id"])
        complete_cdr(cdr["id"], "CESSATION")
        # Application → CESSATION.
        res = api_client.get_application(app_id, TEST_USERS["ssa_admin_headers"])
        app_after = get_success_data(res)
        assert app_after["status"] == "CESSATION"
        # Award → TERMINATED.
        res = api_client.get_award(award["id"], TEST_USERS["benefits_admin_headers"])
        award_after = get_success_data(res)
        assert award_after["status"] == "TERMINATED"
        # Child → TERMINATED_PARENT.
        res = api_client.list_child_auxiliaries(award["id"], TEST_USERS["benefits_admin_headers"])
        children = get_success_data(res)
        children_by_id = {c["id"]: c for c in children}
        assert children_by_id[child["id"]]["status"] == "TERMINATED_PARENT"

    def test_cessation_terminates_concurrent_ssi_supplement(self, api):
        """PRD §3.9: "every `ChildAuxiliaryBenefit` attached to that award
        is moved to `TERMINATED_PARENT`, and any associated `SSISupplement`
        is moved to `TERMINATED`."

        Design: Difficulty/transitive_cascade/cdr_cessation_cascade_application_award_children_supplement
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "4041",
                "full_name": "CDR Sup Cease",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "CA",
                "monthly_income_cents": 0,
                "countable_resources_cents": 100_000,
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "CONCURRENT_SSDI_SSI",
            },
        )
        app_id = ctx["application"]["id"]
        award = ctx["award"]
        cdr = fetch_cdr_for_award(award["id"])
        set_clock("2028-01-15T00:00:00Z")
        start_cdr(cdr["id"])
        complete_cdr(cdr["id"], "CESSATION")
        # SSISupplement → TERMINATED.
        res = api_client.list_ssi_supplements(TEST_USERS["benefits_admin_headers"],
                                                params={"application_id": app_id})
        sups = get_success_data(res)
        assert len(sups) == 1
        assert sups[0]["status"] == "TERMINATED", \
            f"Expected TERMINATED for SSISupplement after CESSATION cascade, got {sups[0]['status']}"


# =========================================================================
# Instance: hearing_cancel_cascade_application_revert_to_reconsideration
# =========================================================================

class TestHearingCancelCascadeApplicationRevertToReconsideration:
    """Cancel→revert two-hop cascade: HearingRequest → CANCELLED triggers
    Application → RECONSIDERATION revert."""

    def test_cancel_requested_hearing_reverts_application_to_reconsideration(self, api):
        """PRD §3.5: "A claimant who changes their mind before the hearing
        is scheduled may cancel a `REQUESTED` hearing; the cancellation
        moves the hearing to `CANCELLED`, reverts the parent application
        from `ALJ_PENDING` to `RECONSIDERATION` so that the claimant
        retains the option to re-request, and increments the hearing's
        `version`."

        Design: Difficulty/transitive_cascade/hearing_cancel_cascade_application_revert_to_reconsideration
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "5050",
                "full_name": "Cancel Hear",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        claimant = ctx["claimant"]
        # Cancel the requested hearing.
        res = api_client.cancel_hearing(hearing["id"], make_claimant_headers(claimant["id"]))
        get_success_data(res)
        # HearingRequest → CANCELLED.
        res = api_client.get_hearing(hearing["id"], TEST_USERS["alj_headers"])
        hearing_after = get_success_data(res)
        assert hearing_after["status"] == "CANCELLED"
        # Application reverts to RECONSIDERATION.
        res = api_client.get_application(ctx["application"]["id"], TEST_USERS["ssa_admin_headers"])
        app_after = get_success_data(res)
        assert app_after["status"] == "RECONSIDERATION", \
            f"Expected RECONSIDERATION after hearing cancel, got {app_after['status']}"

    def test_cancel_increments_hearing_version(self, api):
        """PRD §3.5: "the cancellation moves the hearing to `CANCELLED`,
        reverts the parent application from `ALJ_PENDING` to
        `RECONSIDERATION` so that the claimant retains the option to
        re-request, and increments the hearing's `version`."

        Design: Difficulty/transitive_cascade/hearing_cancel_cascade_application_revert_to_reconsideration
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "5051",
                "full_name": "Cancel Ver",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        v_before = hearing["version"]
        res = api_client.cancel_hearing(hearing["id"], make_claimant_headers(ctx["claimant"]["id"]))
        hearing_after = get_success_data(res)
        assert hearing_after["version"] > v_before, \
            f"Expected hearing version to increment, got {hearing_after['version']} vs {v_before}"
