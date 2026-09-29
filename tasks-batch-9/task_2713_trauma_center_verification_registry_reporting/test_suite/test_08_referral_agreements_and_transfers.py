"""Referral agreements as an interval resource, and transfers as a reversible partition move.

A transfer-out reads the partner agreement's state, agreement activation reads every other
active interval on the same directed pair, and rescinding a transfer has to put the cohort
counters back exactly where they were.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    AgreementStatus,
    DesignationLevel,
    EdDisposition,
    InclusionReason,
    InclusionStatus,
    ReadinessPosture,
    TierCode,
    assert_cohort_partition,
    assert_decimal,
    assert_instant,
    assert_referral_agreement,
    factories as f,
    fixtures as fx,
    make_system_admin_headers,
    make_trauma_program_manager_headers,
)


def _pair_with_draft_agreement(api: ApiClient):
    """A referring center with one minor case and a partner agreement still in draft."""
    fx.anchor_clock(api)
    pair = fx.referral_pair(
        api,
        referring_name="Rockvale Trauma",
        receiving_name="Metro Regional Trauma",
        state_code="OH",
        activate=False,
    )
    case = fx.create_case(
        api,
        pair["referring"]["id"],
        pair["tier"]["id"],
        mrn="MRN-RV1",
        arrival_at="2026-07-15T06:00:00Z",
        injury_severity_score=5,
        los_hours=12.00,
    )
    return pair, case


def _pair_with_active_agreement_and_minor_case(api: ApiClient):
    """A live partnership with one short-stay minor case counted in the cohort."""
    fx.anchor_clock(api)
    pair = fx.referral_pair(
        api,
        referring_name="Willow Creek Trauma",
        receiving_name="Capitol Regional Trauma",
        state_code="KS",
        activate=True,
        tier_code=TierCode.TIER_2_MODIFIED,
        surgeon_response_limit_minutes=30,
        specialty_response_limit_minutes=60,
        iss_threshold=9,
    )
    case = fx.create_case(
        api,
        pair["referring"]["id"],
        pair["tier"]["id"],
        mrn="MRN-WC1",
        arrival_at="2026-07-10T02:00:00Z",
        injury_severity_score=5,
        los_hours=12.00,
    )
    return pair, case


class TestTransferOutRequiresActiveAgreement:
    """The transfer-out gate reads the state of a partner agreement, not of the case."""

    def test_a_draft_agreement_refuses_the_transfer_out(self, api: ApiClient) -> None:
        """The interval already covers the arrival, but a draft is not an agreement in force.

        Design: Difficulty/cross_entity_state_dependency/transfer_out_requires_partner_agreement_in_active_state
        """
        pair, case = _pair_with_draft_agreement(api)
        assert pair["agreement"]["agreement_status"] == AgreementStatus.DRAFT

        refused = api.record_transfer_out(
            case["id"],
            f.transfer_out_payload(pair["receiving"]["id"]),
            make_trauma_program_manager_headers(pair["referring"]["id"]),
        )
        validate_error(refused, E.NO_ACTIVE_REFERRAL_AGREEMENT, 409)

        untouched = fx.get_case(api, case["id"])
        assert untouched["transfer_out_to_center_id"] is None
        assert untouched["inclusion_status"] == InclusionStatus.INCLUDED
        assert_cohort_partition(
            fx.get_center(api, pair["referring"]["id"]), included=1, excluded=0
        )

    def test_activating_the_agreement_admits_the_same_transfer(
        self, api: ApiClient
    ) -> None:
        """Activation by the receiving center is what makes the transfer legal.

        Design: Difficulty/cross_entity_state_dependency/transfer_out_requires_partner_agreement_in_active_state
        """
        pair, case = _pair_with_draft_agreement(api)
        validate_error(
            api.record_transfer_out(
                case["id"],
                f.transfer_out_payload(pair["receiving"]["id"]),
                make_trauma_program_manager_headers(pair["referring"]["id"]),
            ),
            E.NO_ACTIVE_REFERRAL_AGREEMENT,
            409,
        )

        activated = fx.activate_agreement(api, pair["agreement"])
        assert activated["agreement_status"] == AgreementStatus.ACTIVE
        assert_instant(activated["activated_at"], "2026-08-01T00:00:00Z", "activated_at")

        accepted = api.record_transfer_out(
            case["id"],
            f.transfer_out_payload(pair["receiving"]["id"]),
            make_trauma_program_manager_headers(pair["referring"]["id"]),
        )
        transferred = validate_success(accepted, 200)
        assert transferred["transfer_out_to_center_id"] == pair["receiving"]["id"]
        assert transferred["ed_disposition"] == EdDisposition.TRANSFER_OUT
        assert transferred["inclusion_status"] == InclusionStatus.EXCLUDED
        assert transferred["inclusion_reason"] == InclusionReason.TRANSFER_OUT_MINOR_UNDER_24H

        assert_cohort_partition(
            fx.get_center(api, pair["referring"]["id"]), included=0, excluded=1
        )


class TestAgreementIntervalOverlap:
    """Adjacent intervals may both be active; intersecting ones may not."""

    def test_an_adjacent_interval_activates_but_an_intersecting_one_is_refused(
        self, api: ApiClient
    ) -> None:
        """An interval starting the instant another ends is legal; an overlap is not.

        Design: Difficulty/resource_temporal_overlap/adjacent_referral_intervals_legal_but_intersecting_one_rejected
        """
        fx.anchor_clock(api)
        referring = fx.create_center(
            api,
            name="Cedar Fork Trauma",
            state_code="IA",
            designation_level=DesignationLevel.LEVEL_III,
        )
        receiving = fx.create_center(
            api,
            name="Statehouse Regional Trauma",
            state_code="IA",
            designation_level=DesignationLevel.LEVEL_I,
        )
        first = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-07-01T00:00:00Z",
            guaranteed_acceptance_minutes=45,
        )
        fx.activate_agreement(api, first)
        adjacent = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
            guaranteed_acceptance_minutes=45,
        )
        intersecting = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
            guaranteed_acceptance_minutes=45,
        )

        accepted = api.activate_referral_agreement(
            adjacent["id"], make_trauma_program_manager_headers(receiving["id"])
        )
        activated = validate_success(accepted, 200)
        assert_referral_agreement(activated)
        assert activated["agreement_status"] == AgreementStatus.ACTIVE

        refused = api.activate_referral_agreement(
            intersecting["id"], make_trauma_program_manager_headers(receiving["id"])
        )
        validate_error(refused, E.AGREEMENT_INTERVAL_OVERLAP, 409)

        still_draft = fx.get_agreement(api, referring["id"], intersecting["id"])
        assert still_draft["agreement_status"] == AgreementStatus.DRAFT
        assert still_draft["activated_at"] is None

    def test_only_the_two_non_overlapping_intervals_are_listed_as_active(
        self, api: ApiClient
    ) -> None:
        """The active filter over the pair returns the first and the adjacent agreement.

        Design: Difficulty/resource_temporal_overlap/adjacent_referral_intervals_legal_but_intersecting_one_rejected
        """
        fx.anchor_clock(api)
        referring = fx.create_center(
            api,
            name="Cedar Fork Trauma",
            state_code="IA",
            designation_level=DesignationLevel.LEVEL_III,
        )
        receiving = fx.create_center(
            api,
            name="Statehouse Regional Trauma",
            state_code="IA",
            designation_level=DesignationLevel.LEVEL_I,
        )
        first = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-07-01T00:00:00Z",
            guaranteed_acceptance_minutes=45,
        )
        fx.activate_agreement(api, first)
        adjacent = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
            guaranteed_acceptance_minutes=45,
        )
        intersecting = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
            guaranteed_acceptance_minutes=45,
        )
        fx.activate_agreement(api, adjacent)
        validate_error(
            api.activate_referral_agreement(
                intersecting["id"], make_trauma_program_manager_headers(receiving["id"])
            ),
            E.AGREEMENT_INTERVAL_OVERLAP,
            409,
        )

        active = get_success_data(
            api.list_center_referral_agreements(
                referring["id"],
                make_system_admin_headers(),
                {"agreement_status": AgreementStatus.ACTIVE},
            )
        )
        assert {row["id"] for row in active} == {first["id"], adjacent["id"]}


class TestTransferRescindRestoresCohort:
    """The cohort partition is conserved across a transfer and its rescission."""

    def test_rescinding_the_transfer_returns_the_case_to_the_cohort(
        self, api: ApiClient
    ) -> None:
        """The counters move 1/0 to 0/1 and back to exactly 1/0.

        Design: Difficulty/compensating_invariant/transfer_out_rescind_restores_cohort_partition_counters
        """
        pair, case = _pair_with_active_agreement_and_minor_case(api)
        referring_id = pair["referring"]["id"]
        assert_cohort_partition(fx.get_center(api, referring_id), included=1, excluded=0)

        transferred = fx.record_transfer_out(api, case, pair["receiving"]["id"])
        assert transferred["inclusion_status"] == InclusionStatus.EXCLUDED
        assert transferred["inclusion_reason"] == InclusionReason.TRANSFER_OUT_MINOR_UNDER_24H
        assert_cohort_partition(fx.get_center(api, referring_id), included=0, excluded=1)

        restored = fx.rescind_transfer_out(api, case)
        assert restored["inclusion_status"] == InclusionStatus.INCLUDED
        assert restored["inclusion_reason"] == InclusionReason.MEETS_INCLUSION_CRITERIA
        assert restored["transfer_out_to_center_id"] is None
        assert restored["ed_disposition"] == EdDisposition.ADMIT
        assert_cohort_partition(fx.get_center(api, referring_id), included=1, excluded=0)

    def test_the_round_trip_costs_exactly_two_case_versions(self, api: ApiClient) -> None:
        """Both writes are recorded, and the rates the cohort feeds are unchanged.

        Design: Difficulty/compensating_invariant/transfer_out_rescind_restores_cohort_partition_counters
        """
        pair, case = _pair_with_active_agreement_and_minor_case(api)
        opening_version = case["version"]

        fx.record_transfer_out(api, case, pair["receiving"]["id"])
        fx.rescind_transfer_out(api, case)

        after_case = fx.get_case(api, case["id"])
        assert after_case["version"] == opening_version + 2, (
            "the rescission is a second write, not an erasure of the first"
        )

        after_center = fx.get_center(api, pair["referring"]["id"])
        assert_decimal(
            after_center["under_triage_rate_pct"], 0.00, "under_triage_rate_pct"
        )
        assert after_center["readiness_posture"] == ReadinessPosture.READY
