"""Two calendars with opposite interval conventions: remediation windows and release tranches."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    OwnerSpec,
    api_client,
    create_batch,
    day_start,
    ingest_activity,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    onboard_standard_merchant,
    open_program,
    read_merchant,
    read_reserve_account,
    release_request_payload,
    remediation_program_payload,
    request_release,
    run_monitoring,
    set_clock,
    USER_ANALYST_01,
)


def _restricted_merchant_with_one_draft_program(api):
    """Restrict a merchant, then open a program over [2026-08-01, 2026-10-30)."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-08T00:00:00Z",
        legal_business_name="Bellhaven Market LLC",
        mcc_code="5999",
        requested_monthly_volume_cents=300_000_000,
        owners=[OwnerSpec(full_name="Nia Okafor")],
    )
    ingest_activity(
        api,
        onboarded.merchant_id,
        "2026-07-08",
        txn_count=2_000,
        volume_cents=20_000_000,
        distinct_card_count=1_900,
        decline_count=5,
        unique_bin_count=300,
        chargeback_count=18,
        chargeback_amount_cents=180_000,
        chargeback_network="VISA",
    )
    set_clock(api, "2026-07-09T00:00:00Z")
    run_monitoring(api, "2026-07-09")

    merchant = read_merchant(api, onboarded.merchant_id)
    assert merchant["account_state"] == "RESTRICTED"
    assert merchant["remediation_required"] is True

    first = open_program(
        api,
        onboarded.merchant_id,
        "2026-08-01",
        "2026-10-30",
        USER_ANALYST_01,
        target_ratio_bps=65,
        monitoring_month_count=3,
    )
    assert first["window_end_date"] == "2026-10-30"
    return onboarded, first


def _open_program_response(api, merchant_id, start, end):
    return api.create_remediation_program(
        remediation_program_payload(
            merchant_id, start, end, target_ratio_bps=65, monitoring_month_count=3
        ),
        make_risk_analyst_headers(USER_ANALYST_01),
    )


class TestRemediationWindowsAreHalfOpen:
    """A window that starts the day the previous one ends is legal; a day earlier is not."""

    def test_a_window_starting_on_the_previous_end_date_is_accepted(self):
        """Touching endpoints are not an overlap, so the adjacent program opens as DRAFT.

        PRD 3.11: "The requested window must not overlap the window of any other program of the
        same merchant whose state is `DRAFT` or `ACTIVE`, with touching endpoints - a new window
        starting exactly where an existing one ends - explicitly not an overlap; a genuine overlap
        is rejected with `ERR_REMEDIATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/remediation_windows_half_open_touching_allowed_overlap_rejected
        """
        api = api_client
        onboarded, first = _restricted_merchant_with_one_draft_program(api)

        response = _open_program_response(
            api, onboarded.merchant_id, "2026-10-30", "2027-01-28"
        )
        adjacent = validate_success(response, 201)

        assert adjacent["window_start_date"] == "2026-10-30"
        assert adjacent["window_start_date"] == first["window_end_date"]
        assert adjacent["state"] == "DRAFT"

    def test_a_window_starting_one_day_earlier_is_rejected(self):
        """One day of genuine intersection is enough to refuse the third program.

        PRD 3.11: "The window is **half-open**: it includes `window_start_date` and excludes
        `window_end_date`."

        Design: Difficulty/resource_temporal_overlap/remediation_windows_half_open_touching_allowed_overlap_rejected
        """
        api = api_client
        onboarded, _ = _restricted_merchant_with_one_draft_program(api)

        validate_success(
            _open_program_response(api, onboarded.merchant_id, "2026-10-30", "2027-01-28"), 201
        )
        overlapping = _open_program_response(
            api, onboarded.merchant_id, "2026-10-29", "2027-01-27"
        )

        validate_error(overlapping, "ERR_REMEDIATION_WINDOW_OVERLAP", 409)


def _account_after_the_first_tranche(api):
    """Two matured holds totalling 150000 cents, with one tranche ending 2026-04-30 taken."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-04-01T00:00:00Z",
        legal_business_name="Stonegate Provisions LLC",
        mcc_code="5999",
        owners=[OwnerSpec(full_name="Elias Frost")],
    )
    ingest_activity(api, onboarded.merchant_id, "2026-04-01")
    create_batch(api, onboarded.merchant_id, "2026-04-01", "2026-04-01", 1_000_000)

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
    create_batch(api, onboarded.merchant_id, "2026-04-15", "2026-04-15", 2_000_000)

    set_clock(api, "2026-07-20T00:00:00Z")
    account = read_reserve_account(api, onboarded.reserve_account_id)
    assert account["held_balance_cents"] == 150_000
    request_release(
        api, onboarded.reserve_account_id, 50_000, "2026-04-01", "2026-04-30", account["version"]
    )
    return onboarded


def _second_tranche_response(api, reserve_account_id, start, end):
    account = read_reserve_account(api, reserve_account_id)
    return api.create_release_request(
        reserve_account_id,
        release_request_payload(100_000, start, end, account["version"]),
        make_portfolio_controller_headers(),
    )


class TestReleaseTranchesNeedAFullCoolingGap:
    """Adjacency is not enough for tranches: 30 clear days plus one must separate them."""

    def test_a_start_thirty_days_after_the_prior_end_is_refused(self):
        """2026-05-30 is only 30 days after 2026-04-30, so the buffer is not satisfied.

        PRD 3.10: "The previous scheduled release is the account's `RELEASE` entry with
        `reason_code` `SCHEDULED_RELEASE` having the greatest `effective_date`, breaking a tie in
        favour of the entry with the greater `created_at`."

        Design: Difficulty/resource_temporal_overlap/release_tranches_closed_intervals_need_thirty_one_day_gap
        """
        api = api_client
        onboarded = _account_after_the_first_tranche(api)

        response = _second_tranche_response(
            api, onboarded.reserve_account_id, "2026-05-30", "2026-06-30"
        )

        validate_error(response, "ERR_RELEASE_TRANCHE_COOLING_VIOLATION", 409)
        assert read_reserve_account(api, onboarded.reserve_account_id)[
            "released_to_date_cents"
        ] == 50_000

    def test_a_start_thirty_one_days_after_the_prior_end_is_accepted(self):
        """2026-05-31 clears the buffer and the remaining 100000 cents leave the account.

        PRD 3.10: "When such an entry exists, `tranche_start_date` must be at least 31 days after
        that entry's `tranche_end_date` - a 30-day cooling period plus one day, so that consecutive
        tranches never touch."

        Design: Difficulty/resource_temporal_overlap/release_tranches_closed_intervals_need_thirty_one_day_gap
        """
        api = api_client
        onboarded = _account_after_the_first_tranche(api)

        _second_tranche_response(api, onboarded.reserve_account_id, "2026-05-30", "2026-06-30")
        accepted = _second_tranche_response(
            api, onboarded.reserve_account_id, "2026-05-31", "2026-06-30"
        )
        validate_success(accepted, 201)

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["released_to_date_cents"] == 150_000
        assert account["held_balance_cents"] == 0
        assert account["total_accrued_cents"] == 150_000
        assert account["last_release_tranche_end_date"] == "2026-06-30"
