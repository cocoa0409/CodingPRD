"""Market-day scheduling, lifecycle, and reconciliation claims (PRD §3.2)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_program, create_market, create_market_day, create_market_day_payload,
    setup_booth_scenario, issue_tokens, redeem_serials, close_day,
    create_submission, verify_submission,
    assert_market_day,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["market_manager_headers"]


class TestMarketDayScheduling:
    def test_inverted_window_rejected(self, api):
        """PRD §3.2: "A `MarketManager` schedules a market day by naming its
        `market_id`, a calendar `date` in ISO year-month-day form, and a
        half-open operating window from `opens_at` (inclusive) to `closes_at`
        (exclusive); `closes_at` must be strictly after `opens_at`."
        PRD §2.10: "Request shape follows — `ERR_INVALID_REQUEST` for missing
        required fields, wrong types, out-of-range enum values (`benefit_type`,
        `kind`, `outcome`, `to`), a `serial_end` that precedes its
        `serial_start`, or a `closes_at` not strictly after its `opens_at` —
        then claim emptiness (`ERR_SUBMISSION_EMPTY`), then the
        optimistic-concurrency checks of §2.8, which run ahead of any state
        evaluation."

        Design: Corner/entities/c_ent_market_day_inverted_window_rejected
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        resp = api.create_market_day(
            create_market_day_payload(market_id=market["id"], date="2026-08-01",
                                      opens_at="2026-08-01T14:00:00Z",
                                      closes_at="2026-08-01T08:00:00Z"),
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_market_day_outside_season_rejected(self, api):
        """PRD §3.2: "The day's `date` must fall within the program's season —
        on or after `season_start` and strictly before `season_end` — or
        scheduling is rejected with `ERR_SEASON_INACTIVE`."

        Design: Corner/validations/c_val_market_day_outside_season_rejected
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        resp = api.create_market_day(
            create_market_day_payload(market_id=market["id"], date="2026-09-01",
                                      opens_at="2026-09-01T08:00:00Z",
                                      closes_at="2026-09-01T14:00:00Z"),
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_SEASON_INACTIVE)

    def test_abutting_market_day_windows_legal(self, api):
        """PRD §3.2: "And the new window must not overlap any other market-day
        window of the same market, regardless of that day's status: because
        windows are half-open, abutting windows — an existing window closing
        exactly when the new one opens — are legal, and mere date equality is
        not the test, so two same-date days with disjoint windows are
        permitted; a genuine overlap is rejected with `ERR_MARKET_DAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/market_day_half_open_window_abutment_vs_overlap
        """
        program = create_program()
        market = create_market(program["id"])
        day1 = create_market_day(market["id"])
        assert day1["status"] == "SCHEDULED"

        abutting = api.create_market_day(
            create_market_day_payload(market_id=market["id"], date="2026-08-01",
                                      opens_at="2026-08-01T14:00:00Z",
                                      closes_at="2026-08-01T20:00:00Z"),
            MANAGER)
        created = validate_success(abutting, expected_status=201)
        assert created["opens_at"].startswith("2026-08-01T14:00:00")
        assert_market_day(created)

    def test_overlapping_market_day_window_rejected(self, api):
        """PRD §3.2: "And the new window must not overlap any other market-day
        window of the same market, regardless of that day's status: because
        windows are half-open, abutting windows — an existing window closing
        exactly when the new one opens — are legal, and mere date equality is
        not the test, so two same-date days with disjoint windows are
        permitted; a genuine overlap is rejected with `ERR_MARKET_DAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/market_day_half_open_window_abutment_vs_overlap
        """
        program = create_program()
        market = create_market(program["id"])
        create_market_day(market["id"])  # [08:00, 14:00) on 2026-08-01

        overlapping = api.create_market_day(
            create_market_day_payload(market_id=market["id"], date="2026-08-01",
                                      opens_at="2026-08-01T13:00:00Z",
                                      closes_at="2026-08-01T15:00:00Z"),
            MANAGER)
        validate_error(overlapping, ApiErrorId.ERR_MARKET_DAY_OVERLAP)


class TestMarketDayOpenClose:
    def test_open_requires_clock_date_match_then_succeeds(self, api):
        """PRD §3.2: "Opening a day moves it `SCHEDULED → OPEN` and is guarded
        by the logical clock: the clock's current date must equal the day's
        `date`, otherwise the open is rejected with `ERR_MARKET_DAY_NOT_OPEN`."

        Design: Corner/state_machines/c_sm_open_requires_clock_date_match_then_succeeds
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        day = create_market_day(market["id"], date="2026-08-02",
                                opens_at="2026-08-02T08:00:00Z",
                                closes_at="2026-08-02T14:00:00Z")

        early = api.open_market_day(day["id"], MANAGER)
        validate_error(early, ApiErrorId.ERR_MARKET_DAY_NOT_OPEN)

        validate_success(api.set_clock("2026-08-02T00:00:00Z", ADMIN))
        opened = validate_success(api.open_market_day(day["id"], MANAGER))
        assert opened["status"] == "OPEN"

    def test_second_close_rejected(self, api):
        """PRD §3.2: "An `OPEN` day admits the four same-day operations —
        issuance, redemption, redemption reversal, and issuance void — and
        closing moves the day `OPEN → CLOSED`."
        PRD §2.10: "State gates come next: first the generic rule that any
        transition attempted from a state that does not permit it is rejected
        with `ERR_INVALID_STATE`, then the specific gates in their relative
        order — shopper eligibility (`ERR_SHOPPER_NOT_ELIGIBLE`), vendor
        standing (`ERR_VENDOR_NOT_ACTIVE`), market-day openness
        (`ERR_MARKET_DAY_NOT_OPEN`), and market-day closedness
        (`ERR_MARKET_DAY_NOT_CLOSED`)."

        Design: Corner/state_machines/c_sm_close_is_one_way_second_close_rejected
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        day = create_market_day(market["id"])
        validate_success(api.open_market_day(day["id"], MANAGER))
        closed = validate_success(api.close_market_day(day["id"], MANAGER))
        assert closed["status"] == "CLOSED"

        again = api.close_market_day(day["id"], MANAGER)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)


def _setup_variance_500(api):
    """Issued 2000 (charge 1000: 2x500 base + 10x100 match), redeem 1500."""
    sc = setup_booth_scenario()
    issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 1000)
    vend_id = sc["vendor"]["id"]
    redeem_serials(vend_id, [100001, 100002, 300001, 300002, 300003, 300004, 300005])
    close_day(sc["market_day"]["id"])
    return sc


class TestReconciliationTolerance:
    def test_reconcile_at_exact_tolerance_reconciles(self, api):
        """PRD §3.2: "From `CLOSED`, a plain reconcile succeeds only while the
        absolute value of `variance_cents` is at most 500 cents — the
        five-dollar tolerance boundary is inclusive, so a variance of exactly
        five dollars reconciles while five dollars and one cent does not — and
        moves the day `CLOSED → RECONCILED`."

        Design: Difficulty/boundary_precision_check/reconcile_variance_exactly_at_tolerance_reconciles
        """
        sc = _setup_variance_500(api)
        reconciled = validate_success(api.reconcile_market_day(
            sc["market_day"]["id"], MANAGER, payload={"override_variance": False}))
        assert reconciled["status"] == "RECONCILED", "variance exactly 500 reconciles"
        assert reconciled["variance_cents"] == 500

    def test_reconcile_at_exact_tolerance_variance_value(self, api):
        """PRD §3.2: "The day's `variance_cents` is what remains unaccounted:
        issued minus voided minus redeemed."
        PRD §3.2: "From `CLOSED`, a plain reconcile succeeds only while the
        absolute value of `variance_cents` is at most 500 cents — the
        five-dollar tolerance boundary is inclusive, so a variance of exactly
        five dollars reconciles while five dollars and one cent does not — and
        moves the day `CLOSED → RECONCILED`."

        Design: Difficulty/boundary_precision_check/reconcile_variance_exactly_at_tolerance_reconciles
        """
        sc = _setup_variance_500(api)
        day = get_success_data(api.get_market_day(sc["market_day"]["id"], MANAGER))
        assert day["issued_value_cents"] == 2000, "base 1000 + match 1000"
        assert day["voided_value_cents"] == 0
        assert day["redeemed_value_cents"] == 1500
        assert day["variance_cents"] == 500, "2000 issued - 0 voided - 1500 redeemed"
        assert_market_day(day)


class TestVarianceFlagging:
    def _setup_variance_600(self, api):
        """Issued 2000, redeem 1400 -> variance 600 > 500 tolerance."""
        sc = setup_booth_scenario()
        issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 1000)
        vend_id = sc["vendor"]["id"]
        redeem_serials(vend_id, [100001, 100002, 300001, 300002, 300003, 300004])
        close_day(sc["market_day"]["id"])
        return sc

    def test_reconcile_soft_fail_then_plain_reject_then_override(self, api):
        """PRD §3.2: "When the variance exceeds the tolerance and no override is
        supplied, the attempt does not fail: it returns 200 OK and instead routes
        the day `CLOSED → VARIANCE_FLAGGED`, surfacing the discrepancy for
        investigation."
        PRD §3.2: "From `VARIANCE_FLAGGED` the only way forward is an explicit
        `override_variance` flag set to true, and that flag is `ProgramAdmin`-only
        — a `MarketManager` sending `override_variance` set to true is refused
        with `ERR_FORBIDDEN`, and a plain reconcile attempted on a flagged day is
        rejected with `ERR_RECONCILIATION_VARIANCE`."

        Design: Corner/errors/c_err_reconcile_variance_soft_fail_then_plain_reject_then_override
        """
        sc = self._setup_variance_600(api)
        day_id = sc["market_day"]["id"]

        flagged = validate_success(api.reconcile_market_day(day_id, MANAGER))
        assert flagged["status"] == "VARIANCE_FLAGGED", "soft failure returns 200 and flags the day"

        plain_again = api.reconcile_market_day(day_id, MANAGER)
        validate_error(plain_again, ApiErrorId.ERR_RECONCILIATION_VARIANCE)

        overridden = validate_success(api.reconcile_market_day(
            day_id, ADMIN, payload={"override_variance": True}))
        assert overridden["status"] == "RECONCILED"

    def test_market_manager_override_reconcile_forbidden(self, api):
        """PRD §3.2: "From `VARIANCE_FLAGGED` the only way forward is an explicit
        `override_variance` flag set to true, and that flag is `ProgramAdmin`-only
        — a `MarketManager` sending `override_variance` set to true is refused
        with `ERR_FORBIDDEN`, and a plain reconcile attempted on a flagged day is
        rejected with `ERR_RECONCILIATION_VARIANCE`."

        Design: Corner/rbac/c_rbac_market_manager_override_reconcile_forbidden
        """
        sc = self._setup_variance_600(api)
        day_id = sc["market_day"]["id"]
        flagged = validate_success(api.reconcile_market_day(day_id, MANAGER))
        assert flagged["status"] == "VARIANCE_FLAGGED"

        forbidden = api.reconcile_market_day(day_id, MANAGER, payload={"override_variance": True})
        validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN)

        day = get_success_data(api.get_market_day(day_id, MANAGER))
        assert day["status"] == "VARIANCE_FLAGGED", "day stays flagged after refused override"


class TestReconciledTerminalLock:
    def test_reconciled_day_locks_submission_decide(self, api):
        """PRD §3.6: "Approval is possible only from `VERIFIED`, and only while
        the claim's market day is `CLOSED` or `VARIANCE_FLAGGED`: a day not yet
        closed rejects with `ERR_MARKET_DAY_NOT_CLOSED`, and a `RECONCILED` day
        is terminally locked, rejecting with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/c_sm_reconciled_day_locks_submission_decide
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        vend_id = sc["vendor"]["id"]
        t0, t1 = tokens[0], tokens[1]
        redeem_serials(vend_id, [t0["serial_number"], t1["serial_number"]])
        create_submission(vend_id, sc["market_day"]["id"], [t0["id"]])
        sub_b = create_submission(vend_id, sc["market_day"]["id"], [t1["id"]])
        close_day(sc["market_day"]["id"])
        verify_submission(sub_b["id"], "VERIFIED")

        reconciled = validate_success(api.reconcile_market_day(sc["market_day"]["id"], MANAGER))
        assert reconciled["status"] == "RECONCILED", "variance 400 within tolerance"
        assert reconciled["variance_cents"] == 400

        decide = api.decide_submission(sub_b["id"], "APPROVED", ADMIN)
        validate_error(decide, ApiErrorId.ERR_INVALID_STATE)
