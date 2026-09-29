"""Recovery approval chain, scorecard supersession and read-after-write reads."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    CLAIMS_EXAMINER_USER_ID,
    IPA_ADMIN_HEADERS,
    REINSURANCE_UNDERWRITER_HEADERS,
    REINSURANCE_UNDERWRITER_USER_ID,
    assert_created_at_ascending,
    assert_fields,
    assert_pagination_meta,
    assert_pmpm_components,
    build_enrollee_past_attachment,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_recovery,
    create_scorecard,
    expected_pmpm_components,
    expected_recovery_figures,
    read_enrollee,
    read_physician,
    read_pool,
    read_recovery,
    read_scorecard,
    set_clock,
    state_payload,
    submit_recovery,
)

# The attachment point, the eligible paid total and the reinsurance share the
# recovery instances below are written against (PRD §3.7 arithmetic).
_ATTACHMENT_CENTS = 10000
_ELIGIBLE_PAID_CENTS = 20000
_REINSURANCE_RECOVERY_BPS = 9000

_EXPECTED_RECOVERY = expected_recovery_figures(
    _ELIGIBLE_PAID_CENTS, _ATTACHMENT_CENTS, _REINSURANCE_RECOVERY_BPS
)


def _a_draft_recovery_over_the_attachment_point(api):
    """One member whose PAID total in a PROFESSIONAL pool is twice attachment."""
    scenario = build_enrollee_past_attachment(
        api, _ATTACHMENT_CENTS, overshoot_cents=_ATTACHMENT_CENTS
    )
    recovery = create_recovery(
        api, scenario["pool"]["id"], scenario["enrollee"]["id"]
    )
    return scenario, recovery


class TestRecoveryIsMintedInDraft:
    def test_a_created_recovery_is_in_draft_with_no_audit_identifiers(self, api):
        """PRD §3.7: "The record begins in `status` `DRAFT` with
        `submitted_by_user_id`, `adjudicated_by_user_id` and `denial_reason` all
        null."

        Design: Corner/state_machines/stop_loss_recovery_created_in_draft_initial_state
        """
        _scenario, recovery = _a_draft_recovery_over_the_attachment_point(api)

        assert_fields(
            recovery,
            {
                "status": "DRAFT",
                "submitted_by_user_id": None,
                "adjudicated_by_user_id": None,
                "denial_reason": None,
            },
        )

    def test_every_money_field_is_already_computed_at_create_time(self, api):
        """PRD §3.7: "`recovery_cents` is `excess_cents` multiplied by the
        agreement's `reinsurance_recovery_bps` as a proportion of 10000, rounded
        half up to whole cents in a single rounding step."

        Design: Corner/state_machines/stop_loss_recovery_created_in_draft_initial_state
        """
        _scenario, recovery = _a_draft_recovery_over_the_attachment_point(api)

        assert _EXPECTED_RECOVERY == {
            "attachment_cents": 10000,
            "eligible_paid_cents": 20000,
            "excess_cents": 10000,
            "recovery_cents": 9000,
        }
        assert_fields(recovery, _EXPECTED_RECOVERY)
        assert_fields(read_recovery(api, recovery["id"]), _EXPECTED_RECOVERY)

    def test_a_draft_recovery_credits_nothing_to_the_pool(self, api):
        """PRD §3.7: "Only recoveries whose `status` is `APPROVED` or `RECOVERED`
        contribute to a pool's `stop_loss_recovery_cents`; `DRAFT`, `SUBMITTED` and
        `DENIED` recoveries contribute nothing."

        Design: Corner/state_machines/stop_loss_recovery_created_in_draft_initial_state
        """
        scenario, _recovery = _a_draft_recovery_over_the_attachment_point(api)

        pool = read_pool(api, scenario["pool"]["id"])
        assert_fields(
            pool,
            {
                "stop_loss_recovery_cents": 0,
                "paid_claims_cents": _ELIGIBLE_PAID_CENTS,
                "stop_loss_eligible_enrollee_count": 1,
            },
        )


def _approve(api, recovery_id):
    return api.set_recovery_state(
        recovery_id, state_payload("APPROVED"), REINSURANCE_UNDERWRITER_HEADERS
    )


def _mark_recovered(api, recovery_id):
    return api.set_recovery_state(
        recovery_id, state_payload("RECOVERED"), IPA_ADMIN_HEADERS
    )


class TestRecoveryApprovalCreditsThePoolOnce:
    def test_submission_records_the_submitter_and_moves_no_money(self, api):
        """PRD §3.7: "The originating `ClaimsExaminer` takes it `DRAFT →
        SUBMITTED`, permitted when `status` is `DRAFT` and `excess_cents` is
        greater than zero; the transition records the acting `X-User-ID` in
        `submitted_by_user_id`."

        Design: Corner/state_machines/stop_loss_approval_credits_pool_recovery_and_recovered_leaves_it_flat
        """
        scenario, recovery = _a_draft_recovery_over_the_attachment_point(api)

        submitted = submit_recovery(api, recovery["id"], CLAIMS_EXAMINER_HEADERS)
        assert_fields(
            submitted,
            {
                "status": "SUBMITTED",
                "submitted_by_user_id": CLAIMS_EXAMINER_USER_ID,
                "adjudicated_by_user_id": None,
            },
        )
        assert read_pool(api, scenario["pool"]["id"])["stop_loss_recovery_cents"] == 0

    def test_approval_credits_the_pool_with_the_recovery_amount(self, api):
        """PRD §3.7: "Approval records the acting identifier in
        `adjudicated_by_user_id` and increases the pool's
        `stop_loss_recovery_cents` by the recovery's `recovery_cents`, advancing
        both the recovery's `version` and the pool's `version` by 1."

        Design: Corner/state_machines/stop_loss_approval_credits_pool_recovery_and_recovered_leaves_it_flat
        """
        scenario, recovery = _a_draft_recovery_over_the_attachment_point(api)
        submit_recovery(api, recovery["id"], CLAIMS_EXAMINER_HEADERS)
        before = read_pool(api, scenario["pool"]["id"])

        approved = validate_success(_approve(api, recovery["id"]), 200)
        assert_fields(
            approved,
            {
                "status": "APPROVED",
                "submitted_by_user_id": CLAIMS_EXAMINER_USER_ID,
                "adjudicated_by_user_id": REINSURANCE_UNDERWRITER_USER_ID,
            },
        )

        after = read_pool(api, scenario["pool"]["id"])
        assert after["stop_loss_recovery_cents"] == _EXPECTED_RECOVERY["recovery_cents"]
        assert after["version"] == before["version"] + 1

    def test_reaching_recovered_leaves_the_pool_credit_flat(self, api):
        """PRD §3.7: "Only recoveries whose `status` is `APPROVED` or `RECOVERED`
        contribute to a pool's `stop_loss_recovery_cents`; `DRAFT`, `SUBMITTED` and
        `DENIED` recoveries contribute nothing."

        Design: Corner/state_machines/stop_loss_approval_credits_pool_recovery_and_recovered_leaves_it_flat
        """
        scenario, recovery = _a_draft_recovery_over_the_attachment_point(api)
        submit_recovery(api, recovery["id"], CLAIMS_EXAMINER_HEADERS)
        validate_success(_approve(api, recovery["id"]), 200)
        assert (
            read_pool(api, scenario["pool"]["id"])["stop_loss_recovery_cents"]
            == _EXPECTED_RECOVERY["recovery_cents"]
        )

        recovered = validate_success(_mark_recovered(api, recovery["id"]), 200)
        assert recovered["status"] == "RECOVERED"
        assert (
            read_pool(api, scenario["pool"]["id"])["stop_loss_recovery_cents"]
            == _EXPECTED_RECOVERY["recovery_cents"]
        )


def _one_active_physician_under_an_active_agreement(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Supersede Health", quality_withhold_bps=0
    )
    physician = create_active_physician(
        api, agreement["id"], full_name="Petra Nakamura"
    )
    return agreement, physician


def _two_draft_scorecards_for_the_same_period(api):
    agreement, physician = _one_active_physician_under_an_active_agreement(api)
    first = create_scorecard(
        api,
        physician["id"],
        measurement_period="2026",
        hedis_composite_bps=6000,
        access_score_bps=6000,
        patient_experience_bps=6000,
    )
    physician_after_first = read_physician(api, physician["id"])
    second = create_scorecard(
        api,
        physician["id"],
        measurement_period="2026",
        hedis_composite_bps=9000,
        access_score_bps=8000,
        patient_experience_bps=7000,
    )
    return agreement, physician_after_first, first, second


class TestNewerDraftScorecardSupersedes:
    def test_the_second_create_supersedes_the_earlier_draft(self, api):
        """PRD §3.8: "Creating it has two side effects on its surroundings: any
        earlier scorecard for the same physician and the same `measurement_period`
        that is still in `DRAFT` moves to `SUPERSEDED`, advancing that scorecard's
        `version` by 1; and the physician's `latest_scorecard_period` is updated to
        the new `measurement_period`, advancing the physician's `version` by 1."

        Design: Corner/state_machines/newer_draft_scorecard_supersedes_the_earlier_draft
        """
        _agreement, physician_after_first, first, _second = (
            _two_draft_scorecards_for_the_same_period(api)
        )
        assert physician_after_first["latest_scorecard_period"] == "2026"

        assert read_scorecard(api, first["id"])["status"] == "SUPERSEDED"
        assert (
            read_physician(api, physician_after_first["id"])["version"]
            == physician_after_first["version"] + 1
        )

    def test_the_surviving_scorecard_is_a_draft_with_zeroed_computations(self, api):
        """PRD §3.8: "A new scorecard begins in `status` `DRAFT` with
        `composite_score_bps` 0 and `withhold_release_bps` 0."

        Design: Corner/state_machines/newer_draft_scorecard_supersedes_the_earlier_draft
        """
        _agreement, _physician, _first, second = (
            _two_draft_scorecards_for_the_same_period(api)
        )

        assert_fields(
            second,
            {
                "status": "DRAFT",
                "measurement_period": "2026",
                "composite_score_bps": 0,
                "withhold_release_bps": 0,
            },
        )
        assert_fields(read_scorecard(api, second["id"]), {"status": "DRAFT"})

    def test_no_scorecard_has_reached_final_so_the_composite_stays_zero(self, api):
        """PRD §3.8: "`SUPERSEDED` is terminal; only a scorecard whose `status` is
        `FINAL` ever contributes to a physician's `quality_composite_bps`, and
        `DRAFT` and `SUPERSEDED` scorecards never do."

        Design: Corner/state_machines/newer_draft_scorecard_supersedes_the_earlier_draft
        """
        _agreement, physician_after_first, _first, _second = (
            _two_draft_scorecards_for_the_same_period(api)
        )

        assert read_physician(api, physician_after_first["id"])["quality_composite_bps"] == 0

    def test_exactly_one_draft_remains_listable_for_the_period(self, api):
        """PRD §3.8: "A physician's scorecards may be listed with optional `status`
        and `measurement_period` filters, and an individual read exposes the
        computed `composite_score_bps` and `withhold_release_bps`."

        Design: Corner/state_machines/newer_draft_scorecard_supersedes_the_earlier_draft
        """
        _agreement, physician_after_first, _first, second = (
            _two_draft_scorecards_for_the_same_period(api)
        )

        rows, meta = validate_paginated(
            api.list_physician_scorecards(
                physician_after_first["id"],
                IPA_ADMIN_HEADERS,
                {
                    "status": "DRAFT",
                    "measurement_period": "2026",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [second["id"]]


def _an_active_agreement_with_a_seven_percent_withhold(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    return create_active_agreement(
        api,
        payer_name="Corner Immediate Health",
        base_pmpm_cents=20000,
        quality_withhold_bps=700,
    )


def _register_adult_member(api, agreement_id):
    return create_enrollee(
        api,
        agreement_id,
        external_member_id="X5-0001",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
        coverage_start_date="2026-01-01T00:00:00Z",
    )


def _register_senior_member(api, agreement_id):
    return create_enrollee(
        api,
        agreement_id,
        external_member_id="X5-0002",
        age_band="SENIOR",
        benefit_tier="POS",
        risk_score_bps=12000,
        coverage_start_date="2026-01-01T00:00:00Z",
    )


def _list_enrollees(api, agreement_id, **extra):
    params = {"agreement_id": agreement_id, "limit": 10, "offset": 0}
    params.update(extra)
    return validate_paginated(api.list_enrollees(IPA_ADMIN_HEADERS, params))


class TestCreatedRowIsComputedAndImmediatelyListable:
    def test_the_create_response_already_carries_the_pmpm_components(self, api):
        """PRD §3.3: "Registration immediately derives the member's three
        capitation components, and the derivation is also re-run for every enrollee
        of an agreement at the moment that agreement is activated out of `DRAFT`."

        Design: Corner/consistency_model/created_row_is_fully_computed_in_its_own_response_and_immediately_listable
        """
        agreement = _an_active_agreement_with_a_seven_percent_withhold(api)

        adult = _register_adult_member(api, agreement["id"])
        gross, withhold, net = expected_pmpm_components(20000, "ADULT", "HMO", 10000, 700)
        assert (gross, withhold, net) == (20000, 1400, 18600)
        assert_pmpm_components(adult, gross, withhold, net)
        assert adult["cumulative_paid_claims_cents"] == 0

        senior = _register_senior_member(api, agreement["id"])
        s_gross, s_withhold, s_net = expected_pmpm_components(
            20000, "SENIOR", "POS", 12000, 700
        )
        assert (s_gross, s_withhold, s_net) == (36000, 2520, 33480)
        assert_pmpm_components(senior, s_gross, s_withhold, s_net)

    def test_each_created_row_is_counted_by_the_very_next_list_read(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where
        `total_count` is the number of records matching the filter before
        pagination is applied and `has_more` indicates whether records remain
        beyond the current window."

        Design: Corner/consistency_model/created_row_is_fully_computed_in_its_own_response_and_immediately_listable
        """
        agreement = _an_active_agreement_with_a_seven_percent_withhold(api)

        adult = _register_adult_member(api, agreement["id"])
        rows, meta = _list_enrollees(api, agreement["id"])
        assert_pagination_meta(meta, 10, 0, 1, False)
        assert [row["id"] for row in rows] == [adult["id"]]

        senior = _register_senior_member(api, agreement["id"])
        rows, meta = _list_enrollees(api, agreement["id"])
        assert_pagination_meta(meta, 10, 0, 2, False)
        assert [row["id"] for row in rows] == [adult["id"], senior["id"]]

    def test_the_list_window_is_ordered_by_created_at_ascending(self, api):
        """PRD §2.3: "Unless a specific endpoint states otherwise, list results are
        ordered by the resource's `created_at` timestamp, ascending."

        Design: Corner/consistency_model/created_row_is_fully_computed_in_its_own_response_and_immediately_listable
        """
        agreement = _an_active_agreement_with_a_seven_percent_withhold(api)
        adult = _register_adult_member(api, agreement["id"])
        senior = _register_senior_member(api, agreement["id"])

        rows, _meta = _list_enrollees(api, agreement["id"])
        assert_created_at_ascending(rows)
        assert [row["id"] for row in rows] == [adult["id"], senior["id"]]

    def test_the_filtered_read_sees_the_second_row_without_a_retry(self, api):
        """PRD §3.3: "Enrollees may be listed with optional `agreement_id`,
        `assigned_physician_id` and `age_band` filters, and an individual read
        exposes the gross, withhold and net components together with
        `cumulative_paid_claims_cents`."

        Design: Corner/consistency_model/created_row_is_fully_computed_in_its_own_response_and_immediately_listable
        """
        agreement = _an_active_agreement_with_a_seven_percent_withhold(api)
        _register_adult_member(api, agreement["id"])
        senior = _register_senior_member(api, agreement["id"])

        rows, meta = _list_enrollees(api, agreement["id"], age_band="SENIOR")
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [senior["id"]]
        assert_pmpm_components(read_enrollee(api, senior["id"]), 36000, 2520, 33480)
