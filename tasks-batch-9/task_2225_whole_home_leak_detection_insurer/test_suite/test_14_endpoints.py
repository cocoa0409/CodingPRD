"""Endpoints whose behaviour is more than the sum of one row's fields.

The operational sweep applies several independent families of lapse in one call
and reports a counter for each.  The health summary reruns the uptime arithmetic
as a pure read.  The claim decision verb is legal from exactly one status.  And
account closure refuses to run while money is owed, then cascades in full.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_device_transfer,
    validate_error,
)
from test_helpers.factories import claim_decision_payload
from test_helpers.fixtures import (
    approve_claim,
    begin_claim_review,
    deactivate_homeowner,
    file_claim,
    ingest_quiet_reading,
    initiate_transfer,
    pay_claim,
    read_claim,
    read_device,
    read_device_version,
    read_health_summary,
    read_homeowner,
    read_policy,
    read_property,
    read_telemetry,
    read_transfer,
    run_ops_sweep,
    set_clock,
    set_monitor_mode,
    setup_armed_device,
    setup_armed_device_with_buyer,
    setup_burst_event_with_policy,
)
from test_helpers.test_users import (
    ADJUSTER_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    make_claims_adjuster_headers,
    make_homeowner_headers,
    make_insurer_analyst_headers,
    make_program_admin_headers,
    INSURER_ANALYST_USER_ID,
)

VACATION_ENDS_AT = "2026-08-02T00:00:00Z"
TRANSFER_AT = "2026-08-01T06:10:00Z"
TRANSFER_EXPIRES_AT = "2026-08-08T06:10:00Z"
PAST_BOTH_LAPSES = "2026-08-08T07:00:00Z"


def _a_lapsed_vacation_and_a_lapsed_transfer(api: ApiClient) -> dict:
    """Two unrelated lapses waiting on the same sweep."""
    state = setup_armed_device_with_buyer(api)
    set_monitor_mode(
        api,
        state["device_id"],
        state["homeowner_id"],
        "VACATION",
        vacation_ends_at=VACATION_ENDS_AT,
    )
    set_clock(api, TRANSFER_AT)
    state["transfer"] = initiate_transfer(
        api,
        state["device_id"],
        state["buyer_id"],
        state["homeowner_id"],
        transfer_note="Closing 2026-08-15",
    )
    state["transfer_id"] = state["transfer"]["id"]
    set_clock(api, PAST_BOTH_LAPSES)
    return state


class TestOpsSweepAppliesEveryLapsedFamily:
    def test_one_sweep_reports_a_counter_for_each_family_it_touched(
        self, api: ApiClient
    ):
        """Two families moved, two did not, and all five counters are reported.

        "The **operational sweep** is a `ProgramAdmin` capability that gives the logical
        clock its consequences, and it applies three families of work in one fixed order."
        "The sweep reports what it did as `swept_at`, `modes_reverted`,
        `tickets_escalated`, `tickets_expired`, and `transfers_expired`."

        Design: Corner/endpoints/ops_sweep_reverts_lapsed_vacation_and_expires_transfer_in_one_call
        """
        state = _a_lapsed_vacation_and_a_lapsed_transfer(api)

        report = run_ops_sweep(api)
        assert report["swept_at"].startswith("2026-08-08T07:00:00")
        assert report["modes_reverted"] == 1
        assert report["tickets_escalated"] == 0
        assert report["tickets_expired"] == 0
        assert report["transfers_expired"] == 1

    def test_the_expired_transfer_restores_the_device_and_the_property(
        self, api: ApiClient
    ):
        """The device returns to ARMED because its baseline is still COMPLETE.

        "Third, lapsed transfers expire: a transfer still `INITIATED` once the clock is
        strictly past its `expires_at` moves to `EXPIRED`, restoring the device out of
        `TRANSFER_PENDING` — back to `ARMED` when its baseline profile is still `COMPLETE`,
        otherwise to `LEARNING` — and restoring the property `TRANSFER_PENDING → ACTIVE`
        with its `version` incremented by 1."
        "First, lapsed monitor modes revert: a device in `VACATION` whose
        `vacation_ends_at` the clock has reached moves to `NORMAL` with both vacation
        timestamps cleared, and a device in `SNOOZE` whose `snooze_window_end_at` the clock
        has reached moves to `NORMAL` with its window bounds retained for the cooldown;
        each device changed has `monitor_mode_updated_at` refreshed and its `version`
        incremented by 1."

        Design: Corner/endpoints/ops_sweep_reverts_lapsed_vacation_and_expires_transfer_in_one_call
        """
        state = _a_lapsed_vacation_and_a_lapsed_transfer(api)
        run_ops_sweep(api)

        transfer = read_transfer(api, state["transfer_id"])
        assert_device_transfer(transfer)
        assert transfer["status"] == "EXPIRED"
        assert transfer["expires_at"].startswith("2026-08-08T06:10:00")
        assert transfer["accepted_at"] is None
        assert transfer["cancel_reason"] is None

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "ARMED"
        assert device["monitor_mode"] == "NORMAL"
        assert device["vacation_ends_at"] is None
        assert device["vacation_started_at"] is None

        # An expired transfer restores the property without rewriting ownership.
        home = read_property(api, state["property_id"])
        assert home["property_state"] == "ACTIVE"
        assert home["homeowner_id"] == state["homeowner_id"]

    def test_a_second_sweep_at_the_same_clock_finds_nothing_left_to_do(
        self, api: ApiClient
    ):
        """Already-settled rows are not swept twice.

        "The sweep reports what it did as `swept_at`, `modes_reverted`,
        `tickets_escalated`, `tickets_expired`, and `transfers_expired`."
        "Third, lapsed transfers expire: a transfer still `INITIATED` once the clock is
        strictly past its `expires_at` moves to `EXPIRED`, restoring the device out of
        `TRANSFER_PENDING` — back to `ARMED` when its baseline profile is still `COMPLETE`,
        otherwise to `LEARNING` — and restoring the property `TRANSFER_PENDING → ACTIVE`
        with its `version` incremented by 1."

        Design: Corner/endpoints/ops_sweep_reverts_lapsed_vacation_and_expires_transfer_in_one_call
        """
        state = _a_lapsed_vacation_and_a_lapsed_transfer(api)
        run_ops_sweep(api)
        settled_version = read_device_version(api, state["device_id"])

        again = run_ops_sweep(api)
        assert again["swept_at"].startswith("2026-08-08T07:00:00")
        assert again["modes_reverted"] == 0
        assert again["transfers_expired"] == 0

        assert read_device_version(api, state["device_id"]) == settled_version
        assert read_transfer(api, state["transfer_id"])["status"] == "EXPIRED"


SUMMARY_READINGS = ("2026-08-03T00:00:00Z", "2026-08-03T02:00:00Z")
WINDOW = {
    "window_start_at": "2026-08-03T00:00:00Z",
    "window_end_at": "2026-08-03T04:00:00Z",
}
WIDER_WINDOW = {
    "window_start_at": "2026-08-03T00:00:00Z",
    "window_end_at": "2026-08-03T08:00:00Z",
}
ANALYST = make_insurer_analyst_headers(INSURER_ANALYST_USER_ID)


def _two_covering_samples_and_no_attestation(api: ApiClient) -> dict:
    """Nothing is open, so the endpoint must honour the supplied window."""
    state = setup_armed_device(api)
    for stamp in SUMMARY_READINGS:
        set_clock(api, stamp)
        ingest_quiet_reading(api, state["device_id"], stamp)
    set_clock(api, "2026-08-03T04:00:00Z")
    return state


class TestHealthSummaryIsTheUptimeRuleAsARead:
    def test_the_summary_reproduces_the_coverage_arithmetic_exactly(
        self, api: ApiClient
    ):
        """Two samples two hours apart cover the whole 240-minute window.

        "The same computation is available as a read: a device health summary returns
        `device_id`, `lifecycle_state`, `uptime_pct`, `covered_minutes`, `period_minutes`,
        `offline_gap_count`, `false_positive_count`, and `drip_threshold_gpm` for the
        half-open span between the supplied `window_start_at` and `window_end_at`, and when
        the window is omitted it defaults to the period of the newest `OPEN` attestation."
        "`covered_minutes` is the total length of the merged intervals in whole minutes;
        `uptime_pct` is `covered_minutes` multiplied by 100, divided by `period_minutes`,
        rounded half up to two decimal places."

        Design: Corner/endpoints/health_summary_computed_read_matches_uptime_rule
        """
        state = _two_covering_samples_and_no_attestation(api)

        summary = read_health_summary(api, state["device_id"], ANALYST, WINDOW)
        assert summary["device_id"] == state["device_id"]
        assert summary["lifecycle_state"] == "ARMED"
        assert summary["period_minutes"] == 240
        assert summary["covered_minutes"] == 240
        assert summary["uptime_pct"] == 100.00
        assert summary["offline_gap_count"] == 0

    def test_the_summary_echoes_the_live_baseline_figures(self, api: ApiClient):
        """Threshold and false-positive tally come from the profile, not the window.

        "The same computation is available as a read: a device health summary returns
        `device_id`, `lifecycle_state`, `uptime_pct`, `covered_minutes`, `period_minutes`,
        `offline_gap_count`, `false_positive_count`, and `drip_threshold_gpm` for the
        half-open span between the supplied `window_start_at` and `window_end_at`, and when
        the window is omitted it defaults to the period of the newest `OPEN` attestation."
        "`drip_threshold_gpm` is the greater of an absolute floor of 0.05 gallons per minute
        and two percent of `baseline_peak_flow_gpm`, rounded half up to two decimal places."

        Design: Corner/endpoints/health_summary_computed_read_matches_uptime_rule
        """
        state = _two_covering_samples_and_no_attestation(api)

        summary = read_health_summary(api, state["device_id"], ANALYST, WINDOW)
        assert summary["drip_threshold_gpm"] == 0.12
        assert summary["false_positive_count"] == 0

    def test_a_wider_window_exposes_the_uncovered_tail_and_writes_nothing(
        self, api: ApiClient
    ):
        """The same samples over 480 minutes leave a countable four-hour hole.

        "`offline_gap_count` is the number of maximal uncovered stretches inside the period
        whose length is at least a full hour; shorter holes are not counted."
        "It writes nothing."

        Design: Corner/endpoints/health_summary_computed_read_matches_uptime_rule
        """
        state = _two_covering_samples_and_no_attestation(api)
        version_before = read_device_version(api, state["device_id"])

        wider = read_health_summary(api, state["device_id"], ANALYST, WIDER_WINDOW)
        assert wider["period_minutes"] == 480
        assert wider["covered_minutes"] == 240
        assert wider["uptime_pct"] == 50.00
        assert wider["offline_gap_count"] == 1

        assert read_device_version(api, state["device_id"]) == version_before
        assert len(read_telemetry(api, state["device_id"])) == 5


WATER_DAMAGE_LOSS_CENTS = 400000


def _a_submitted_water_damage_claim(api: ApiClient) -> dict:
    """One claim in SUBMITTED, the only status BEGIN_REVIEW is legal from."""
    state = setup_burst_event_with_policy(api)
    claim = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WATER_DAMAGE",
        WATER_DAMAGE_LOSS_CENTS,
        state["homeowner_id"],
        anomaly_event_id=state["event_id"],
    )
    state["claim_id"] = claim["id"]
    return state


class TestClaimDecisionVerbIsLegalFromOneStatusOnly:
    def test_the_first_begin_review_moves_the_claim_under_review(
        self, api: ApiClient
    ):
        """SUBMITTED is the one status the verb acts from.

        "`BEGIN_REVIEW` moves the claim `SUBMITTED → UNDER_REVIEW` and belongs to a
        `ClaimsAdjuster`."
        "A verb submitted against a status it is not legal from is refused with
        `ERR_CLAIM_NOT_REVIEWABLE`, and every accepted decision increments the claim's
        `version` by 1."

        Design: Corner/endpoints/begin_review_twice_returns_claim_not_reviewable
        """
        state = _a_submitted_water_damage_claim(api)

        reviewing = begin_claim_review(api, state["claim_id"])
        assert reviewing["status"] == "UNDER_REVIEW"
        assert reviewing["version"] == 2

    def test_a_second_begin_review_is_refused_and_stamps_nothing(
        self, api: ApiClient
    ):
        """UNDER_REVIEW is not a status BEGIN_REVIEW may act from.

        "A verb submitted against a status it is not legal from is refused with
        `ERR_CLAIM_NOT_REVIEWABLE`, and every accepted decision increments the claim's
        `version` by 1."
        "`SUPPLY_INFO` moves it `INFO_REQUESTED → UNDER_REVIEW` and is the homeowner's own
        verb — the acting homeowner must be the one recorded in `submitted_by_user_id`."

        Design: Corner/endpoints/begin_review_twice_returns_claim_not_reviewable
        """
        state = _a_submitted_water_damage_claim(api)
        begin_claim_review(api, state["claim_id"])

        # BEGIN_REVIEW "belongs to a `ClaimsAdjuster`", and a `ProgramAdmin`
        # "cannot make the carrier's policy or claim-decision calls" at all.
        validate_error(
            api.decide_claim(
                state["claim_id"],
                claim_decision_payload("BEGIN_REVIEW"),
                make_claims_adjuster_headers(ADJUSTER_USER_ID),
            ),
            ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE,
            409,
        )
        # SUPPLY_INFO is the homeowner's verb but demands INFO_REQUESTED.
        validate_error(
            api.decide_claim(
                state["claim_id"],
                claim_decision_payload("SUPPLY_INFO"),
                make_homeowner_headers(state["homeowner_id"]),
            ),
            ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE,
            409,
        )

        claim = read_claim(api, state["claim_id"])
        assert claim["status"] == "UNDER_REVIEW"
        assert claim["info_request_count"] == 0
        assert claim["decided_by_user_id"] is None
        assert claim["decided_at"] is None
        assert claim["approved_payout_cents"] == 0
        assert claim["version"] == 2


WARRANTY_LOSS_CENTS = 120000
ADMIN_HEADERS = make_program_admin_headers(PROGRAM_ADMIN_USER_ID)


def _an_approved_but_unpaid_warranty_claim(api: ApiClient) -> dict:
    """120000 cents approved and owed, with the account still open."""
    state = setup_burst_event_with_policy(api)
    claim = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WARRANTY_DEVICE",
        WARRANTY_LOSS_CENTS,
        state["homeowner_id"],
    )
    state["claim_id"] = claim["id"]
    begin_claim_review(api, state["claim_id"])
    state["claim"] = approve_claim(api, state["claim_id"], SECOND_ADJUSTER_USER_ID)
    return state


def _attempt_deactivation(api: ApiClient, homeowner_id: str):
    return api.deactivate_homeowner(homeowner_id, {}, ADMIN_HEADERS)


class TestClosureWaitsForAnApprovedPayout:
    def test_closure_is_refused_while_an_approved_payout_is_unsettled(
        self, api: ApiClient
    ):
        """The refusal is by claim status, and it leaves the account untouched.

        "It is refused outright while any reimbursement claim on the account has `status`
        `APPROVED` — an approved but unpaid payout must be settled before the account can
        close — with `ERR_OPEN_PAYOUT_BLOCKS_DEACTIVATION`."
        "Under `WARRANTY_FLAT`, `deductible_applied_cents` is 0 and `approved_payout_cents`
        is the smaller of `documented_loss_cents` and a warranty cap of 150000 cents."

        Design: Corner/endpoints/deactivation_blocked_by_approved_unpaid_claim
        """
        state = _an_approved_but_unpaid_warranty_claim(api)

        validate_error(
            _attempt_deactivation(api, state["homeowner_id"]),
            ApiErrorId.ERR_OPEN_PAYOUT_BLOCKS_DEACTIVATION,
            409,
        )

        claim = read_claim(api, state["claim_id"])
        assert claim["status"] == "APPROVED"
        assert claim["payout_variant"] == "WARRANTY_FLAT"
        assert claim["approved_payout_cents"] == WARRANTY_LOSS_CENTS
        assert claim["deductible_applied_cents"] == 0
        assert claim["decided_by_user_id"] == SECOND_ADJUSTER_USER_ID

        owner = read_homeowner(api, state["homeowner_id"])
        assert owner["account_state"] == "ACTIVE"
        assert owner["deactivated_at"] is None
        assert read_property(api, state["property_id"])["property_state"] == "ACTIVE"

    def test_payment_settles_the_file_and_moves_the_policy_total(
        self, api: ApiClient
    ):
        """Only payment shifts the money, which is what unblocks closure.

        "Payment is the `InsurerAnalyst`'s verb and completes the file."
        "It re-checks the annual cap against `approved_payout_cents`, refuses when the
        paying `X-User-ID` equals the recorded `decided_by_user_id`, and on success stamps
        `paid_at` at the clock, moves the claim `APPROVED → PAID`, and increases the policy's
        `paid_payout_cents_total` by `approved_payout_cents` along with the policy's
        `version`."

        Design: Corner/endpoints/deactivation_blocked_by_approved_unpaid_claim
        """
        state = _an_approved_but_unpaid_warranty_claim(api)
        validate_error(
            _attempt_deactivation(api, state["homeowner_id"]),
            ApiErrorId.ERR_OPEN_PAYOUT_BLOCKS_DEACTIVATION,
            409,
        )

        paid = pay_claim(api, state["claim_id"])
        assert paid["status"] == "PAID"
        assert paid["paid_at"].startswith("2026-08-01T07:00:00")

        policy = read_policy(api, state["policy_id"])
        assert policy["paid_payout_cents_total"] == WARRANTY_LOSS_CENTS

    def test_the_closure_cascade_runs_in_full_once_the_payout_is_paid(
        self, api: ApiClient
    ):
        """The identical call now succeeds and archives the whole account.

        "On success the homeowner moves `ACTIVE → DEACTIVATED` with `deactivated_at`
        stamped at the clock and `version` incremented, and the following cascade runs in
        full:"
        "- every policy not already `TERMINATED` moves to `TERMINATED` with `version`
        incremented, from `PENDING_ENROLLMENT`, `CREDIT_ACTIVE`, or `CREDIT_SUSPENDED`
        alike;"

        Design: Corner/endpoints/deactivation_blocked_by_approved_unpaid_claim
        """
        state = _an_approved_but_unpaid_warranty_claim(api)
        validate_error(
            _attempt_deactivation(api, state["homeowner_id"]),
            ApiErrorId.ERR_OPEN_PAYOUT_BLOCKS_DEACTIVATION,
            409,
        )
        pay_claim(api, state["claim_id"])

        closed = deactivate_homeowner(api, state["homeowner_id"])
        assert closed["account_state"] == "DEACTIVATED"

        owner = read_homeowner(api, state["homeowner_id"])
        assert owner["account_state"] == "DEACTIVATED"
        assert owner["deactivated_at"].startswith("2026-08-01T07:00:00")
        assert read_property(api, state["property_id"])["property_state"] == "ARCHIVED"
        assert read_device(api, state["device_id"])["lifecycle_state"] == "DECOMMISSIONED"
        assert read_policy(api, state["policy_id"])["credit_state"] == "TERMINATED"
