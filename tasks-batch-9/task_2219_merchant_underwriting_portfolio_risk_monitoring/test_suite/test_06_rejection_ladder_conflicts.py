"""Requests that break two rules at once: the ladder decides which refusal is returned."""

from __future__ import annotations

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    OwnerSpec,
    add_beneficial_owner,
    api_client,
    create_batch,
    create_draft_application,
    day_start,
    ingest_activity,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_underwriting_officer_headers,
    onboard_standard_merchant,
    read_application,
    read_reserve_account,
    record_verification,
    release_request_payload,
    request_release,
    screen_owner,
    set_clock,
    submit_application,
    USER_ANALYST_01,
)


def _merchant_with_a_matured_hold(api, *, name: str, owner_name: str):
    """Settle one clean day in April so 50000 cents of reserve has matured by 2026-07-20."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-04-01T00:00:00Z",
        legal_business_name=name,
        mcc_code="5999",
        owners=[OwnerSpec(full_name=owner_name)],
    )
    ingest_activity(api, onboarded.merchant_id, "2026-04-01")
    batch = create_batch(api, onboarded.merchant_id, "2026-04-01", "2026-04-01", 1_000_000)
    assert batch["reserve_hold_cents"] == 50_000
    return onboarded


class TestFundingStateBeatsTheReleaseAmount:
    """A held merchant asking for ten times its releasable balance hears the state refusal."""

    def _request_too_much_while_held(self, api):
        onboarded = _merchant_with_a_matured_hold(
            api, name="Quarry Lane LLC", owner_name="Ines Kaur"
        )
        set_clock(api, "2026-07-20T00:00:00Z")
        get_success_data(
            api.place_funding_hold(
                onboarded.merchant_id,
                "EXCESSIVE_CHARGEBACKS",
                make_risk_analyst_headers(USER_ANALYST_01),
            )
        )
        account = read_reserve_account(api, onboarded.reserve_account_id)
        response = api.create_release_request(
            onboarded.reserve_account_id,
            release_request_payload(500_000, "2026-04-01", "2026-04-30", account["version"]),
            make_portfolio_controller_headers(),
        )
        return onboarded, response

    def test_the_state_guard_answers_and_the_fiscal_ceiling_never_speaks(self):
        """funding_state HELD is checked before the requested amount, so a 409 comes back.

        PRD 2.6: "On a reserve release request, the merchant's `funding_state` is checked before
        the tranche cooling buffer, and the cooling buffer is checked before the releasable
        balance, which is itself checked before the requested amount."

        Design: Difficulty/priority_pair_validation_conflict/funding_hold_state_beats_release_amount_fiscal
        """
        api = api_client
        _, response = self._request_too_much_while_held(api)

        error = validate_error(response, "ERR_FUNDING_STATE_INVALID", 409)
        assert error["error_id"] != "ERR_RELEASE_AMOUNT_EXCEEDS_RELEASABLE"

    def test_the_refused_request_leaves_the_reserve_account_exactly_as_it_was(self):
        """Nothing is released, nothing is unheld and the account keeps accruing.

        PRD 3.10: "On acceptance a `RELEASE` entry is appended with `reason_code`
        `SCHEDULED_RELEASE`, the supplied `amount_cents` and tranche dates, `effective_date` set to
        the logical clock date, `settlement_batch_id` null and `recorded_by_user_id` set to the
        acting controller."

        Design: Difficulty/priority_pair_validation_conflict/funding_hold_state_beats_release_amount_fiscal
        """
        api = api_client
        onboarded, _ = self._request_too_much_while_held(api)

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["released_to_date_cents"] == 0
        assert account["held_balance_cents"] == 50_000
        assert account["state"] == "ACCRUING"
        assert account["last_release_tranche_end_date"] is None


class TestTheSanctionsStopBeatsThinOwnership:
    """One owner who is both sanctioned and only 60 percent of the cap table."""

    def _advance_a_sanctioned_thin_application(self, api):
        set_clock(api, "2026-07-01T00:00:00Z")
        application = create_draft_application(
            api,
            legal_business_name="Ridgeway Imports LLC",
            mcc_code="5999",
            requested_monthly_volume_cents=20_000_000,
            average_ticket_cents=12_000,
            avg_delivery_lag_days=5,
            declared_chargeback_ratio_bps=10,
            prior_processing_history_months=18,
            credit_score=690,
        )
        application_id = application["id"]
        owner = add_beneficial_owner(
            api,
            application_id,
            full_name="Yuri Sokolov",
            ownership_pct=60.00,
            country_code="US",
            date_of_birth="1971-05-08",
            government_id_last4="1010",
        )
        submit_application(api, application_id)
        record_verification(api, application_id)
        screen_owner(api, owner["id"], sanctions_hit=True, pep_flag=False, id_verified=True)
        response = api.advance_to_underwriting(
            application_id, make_underwriting_officer_headers()
        )
        return application_id, owner["id"], response

    def test_the_compliance_stop_surfaces_even_though_the_cap_table_is_also_short(self):
        """The sanctions check runs before the 75 percent coverage check, so 422 sanctions wins.

        PRD 3.3: "Placing the sanctions check ahead of the ownership-coverage check is deliberate:
        a sanctioned owner is a compliance stop, and it must surface as such even when the
        disclosed ownership is also thin."

        Design: Difficulty/priority_pair_validation_conflict/sanctions_safety_beats_ownership_coverage_constraint
        """
        api = api_client
        _, owner_id, response = self._advance_a_sanctioned_thin_application(api)

        error = validate_error(response, "ERR_SANCTIONED_BENEFICIAL_OWNER", 422)
        assert error["error_id"] != "ERR_OWNERSHIP_COVERAGE_INSUFFICIENT"
        assert owner_id

    def test_the_application_and_the_owner_keep_the_state_they_had(self):
        """The screening outcome stands, the disclosed total stays 60.00 and the state holds.

        PRD 3.2: "Attaching an owner immediately recomputes the application's
        `owner_ownership_pct_total` as the sum of `ownership_pct` across all owners of that
        application, carried to two decimal places."

        Design: Difficulty/priority_pair_validation_conflict/sanctions_safety_beats_ownership_coverage_constraint
        """
        api = api_client
        application_id, owner_id, _ = self._advance_a_sanctioned_thin_application(api)

        owners = get_success_data(
            api.list_beneficial_owners(application_id, make_underwriting_officer_headers())
        )
        assert [owner["status"] for owner in owners if owner["id"] == owner_id] == ["SANCTIONS_HIT"]

        application = read_application(api, application_id)
        assert float(application["owner_ownership_pct_total"]) == 60.00
        assert application["state"] == "IN_VERIFICATION"


class TestTrancheCoolingBeatsTheReleaseAmount:
    """A second tranche that both starts a day too early and asks for too much."""

    def _second_release_one_day_early(self, api):
        onboarded = _merchant_with_a_matured_hold(
            api, name="Halyard Supply LLC", owner_name="Greta Lind"
        )
        set_clock(api, day_start("2026-04-15"))
        ingest_activity(
            api,
            onboarded.merchant_id,
            "2026-04-15",
            txn_count=200,
            volume_cents=2_000_000,
            distinct_card_count=190,
            decline_count=2,
            unique_bin_count=80,
        )
        second = create_batch(api, onboarded.merchant_id, "2026-04-15", "2026-04-15", 2_000_000)
        assert second["reserve_hold_cents"] == 100_000

        set_clock(api, "2026-07-20T00:00:00Z")
        account = read_reserve_account(api, onboarded.reserve_account_id)
        request_release(
            api, onboarded.reserve_account_id, 50_000, "2026-04-01", "2026-04-30", account["version"]
        )

        refreshed = read_reserve_account(api, onboarded.reserve_account_id)
        response = api.create_release_request(
            onboarded.reserve_account_id,
            release_request_payload(500_000, "2026-05-30", "2026-06-30", refreshed["version"]),
            make_portfolio_controller_headers(),
        )
        return onboarded, response

    def test_the_cooling_buffer_answers_before_the_amount_is_ever_compared(self):
        """A start date 30 days after the prior tranche end is a temporal refusal, not a fiscal one.

        PRD 3.10: "When such an entry exists, `tranche_start_date` must be at least 31 days after
        that entry's `tranche_end_date` - a 30-day cooling period plus one day, so that consecutive
        tranches never touch."

        Design: Difficulty/priority_pair_validation_conflict/tranche_cooling_temporal_beats_release_amount_fiscal
        """
        api = api_client
        _, response = self._second_release_one_day_early(api)

        error = validate_error(response, "ERR_RELEASE_TRANCHE_COOLING_VIOLATION", 409)
        assert error["error_id"] != "ERR_RELEASE_AMOUNT_EXCEEDS_RELEASABLE"

    def test_only_the_first_tranche_is_recorded_on_the_account(self):
        """The account still shows the accepted 50000 release and its April tranche end.

        PRD 3.10: "`released_to_date_cents` rises, `held_balance_cents` falls,
        `last_release_tranche_end_date` is set to this entry's `tranche_end_date`,
        `Merchant.reserve_balance_cents` is refreshed, and the account's `version` increments"

        Design: Difficulty/priority_pair_validation_conflict/tranche_cooling_temporal_beats_release_amount_fiscal
        """
        api = api_client
        onboarded, _ = self._second_release_one_day_early(api)

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["released_to_date_cents"] == 50_000
        assert account["held_balance_cents"] == 100_000
        assert account["last_release_tranche_end_date"] == "2026-04-30"
