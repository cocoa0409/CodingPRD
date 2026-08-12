"""Enforcement ladder: fine accrual variants, rounding order, settle/waive, liens."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId,
    create_settle_payload, create_waive_payload, create_violation_payload,
    read_property, get_violation_fine, set_logical_clock, run_daily_sweep,
    setup_violation_with_fine, assert_fine_invariant,
    make_homeowner_headers,
)

MANAGER = TEST_USERS["manager_headers"]


class TestFineAccrualVariants:
    """Identical base/rate/duration diverge purely from the fine_mode snapshot."""

    def test_tiered_escalation_five_day_total(self, api):
        """Tiered: base + 3 grace days at base rate + 2 escalated days = 17000.

        PRD §3.8: "The two modes genuinely diverge: a fine created with a base of
        10000 cents, a daily rate of 1000 cents, a grace of 3 days, and a
        20000-basis-point multiplier stands at 17000 cents after five accrual days
        under tiered escalation — the base plus three days of 1000 plus two days of
        2000 — against 15000 cents under simple daily."
        PRD §3.8: "`mode_snapshot` copies `fine_mode`"

        Design: Difficulty/dual_variant_calc/fine_accrual_simple_vs_tiered_totals
        """
        bundle = setup_violation_with_fine(assoc_overrides={
            "name": "Tiered HOA", "fine_mode": "TIERED_ESCALATION",
            "grace_days": 3, "escalation_multiplier_bp": 20000})
        set_logical_clock("2026-05-06T09:00:00Z")
        run_daily_sweep()
        fine = get_violation_fine(bundle["violation"]["id"])
        assert fine["mode_snapshot"] == "TIERED_ESCALATION"
        assert fine["accrued_cents"] == 17000, (
            f"10000 + 3*1000 + 2*2000 = 17000, got {fine['accrued_cents']}")

    def test_simple_daily_five_day_total_and_variant_delta(self, api):
        """Simple: base + 5 flat days = 15000; the mode delta is exactly 2000.

        PRD §3.8: "Under the `SIMPLE_DAILY` snapshot, every day adds
        `daily_rate_cents`."
        PRD §3.8: "stands at 17000 cents after five accrual days under tiered
        escalation — the base plus three days of 1000 plus two days of 2000 —
        against 15000 cents under simple daily."

        Design: Difficulty/dual_variant_calc/fine_accrual_simple_vs_tiered_totals
        """
        simple = setup_violation_with_fine(assoc_overrides={"name": "Simple HOA"})
        tiered = setup_violation_with_fine(assoc_overrides={
            "name": "Tiered HOA", "fine_mode": "TIERED_ESCALATION",
            "grace_days": 3, "escalation_multiplier_bp": 20000})
        set_logical_clock("2026-05-06T09:00:00Z")
        run_daily_sweep()
        fine_s = get_violation_fine(simple["violation"]["id"])
        fine_t = get_violation_fine(tiered["violation"]["id"])
        assert fine_s["mode_snapshot"] == "SIMPLE_DAILY"
        assert fine_s["accrued_cents"] == 15000, (
            f"10000 + 5*1000 = 15000, got {fine_s['accrued_cents']}")
        assert fine_t["accrued_cents"] - fine_s["accrued_cents"] == 2000


class TestPerDayRoundingOrder:
    """Each day's escalated increment is rounded half up BEFORE accumulation."""

    def test_three_days_of_rounded_escalated_increments(self, api):
        """333 cents at 15000 bp rounds to 500 per day; 3 days total 1500.

        PRD §2.7: "Fine accrual follows a pinned rounding order: each individual
        day's increment is rounded half up to a whole cent (a half cent rounds up)
        before being added into the fine's `accrued_cents`, and the accrued total is
        the sum of those per-day rounded increments."
        PRD §3.8: "a day whose index exceeds the grace count adds the escalated
        increment: `daily_rate_cents` multiplied by `escalation_multiplier_bp_snapshot`
        and divided by 10000, rounded half up to a whole cent for that day."

        Design: Difficulty/combinatorial_formula/fine_accrual_per_day_rounding_order
        """
        bundle = setup_violation_with_fine(assoc_overrides={
            "name": "Round HOA", "fine_mode": "TIERED_ESCALATION",
            "base_fine_cents": 0, "daily_fine_cents": 333,
            "grace_days": 0, "escalation_multiplier_bp": 15000})
        set_logical_clock("2026-05-04T09:00:00Z")
        run_daily_sweep()
        fine = get_violation_fine(bundle["violation"]["id"])
        # per-day: round_half_up(333 * 15000 / 10000) = round_half_up(499.5) = 500
        assert fine["accrued_cents"] == 1500, (
            f"3 * 500 = 1500 (per-day rounding); sum-then-round would give 1499, "
            f"got {fine['accrued_cents']}")

    def test_each_single_day_adds_the_rounded_increment(self, api):
        """Sweeping one day at a time shows +500 per day, never a fractional drift.

        PRD §2.7: "The alternative ordering — summing raw unrounded per-day amounts
        and rounding the total once — is explicitly forbidden, because it yields
        different totals than the pinned order."
        PRD §3.8: "The daily checkpoint advances every `ACCRUING` fine from the day
        after its `accrued_through_date` through the current logical date, rounding
        each day's increment before adding it into `accrued_cents`"

        Design: Difficulty/combinatorial_formula/fine_accrual_per_day_rounding_order
        """
        bundle = setup_violation_with_fine(assoc_overrides={
            "name": "Round HOA", "fine_mode": "TIERED_ESCALATION",
            "base_fine_cents": 0, "daily_fine_cents": 333,
            "grace_days": 0, "escalation_multiplier_bp": 15000})
        violation_id = bundle["violation"]["id"]
        for day, expected in (("2026-05-02T09:00:00Z", 500),
                              ("2026-05-03T09:00:00Z", 1000),
                              ("2026-05-04T09:00:00Z", 1500)):
            set_logical_clock(day)
            run_daily_sweep()
            fine = get_violation_fine(violation_id)
            assert fine["accrued_cents"] == expected, (
                f"after {day}: expected {expected}, got {fine['accrued_cents']}")


class TestSettleWaiveConservation:
    """accrued == settled + waived + outstanding holds across waive and settle."""

    def _accrued_12000(self):
        """Violation at 05-01; two accrual days by 05-03 -> accrued 12000."""
        bundle = setup_violation_with_fine()
        set_logical_clock("2026-05-03T09:00:00Z")
        run_daily_sweep()
        fine = get_violation_fine(bundle["violation"]["id"])
        assert fine["accrued_cents"] == 12000, f"setup accrual: {fine['accrued_cents']}"
        return bundle, fine

    def test_waive_conserves_accounted_cents(self, api):
        """Waiving 2000 against 12000 leaves outstanding 10000 and rebalances the property.

        PRD §2.5: "For every fine, the invariant `accrued_cents` equals
        `settled_cents` plus `waived_cents` plus `outstanding_cents` holds at all
        times."
        PRD §3.8: "Waiving is permitted on `ACCRUING` and `STOPPED` fines alike, adds
        the amount to `waived_cents`, recomputes `outstanding_cents` and the
        property, and increments the fine's `version` by one."

        Design: Difficulty/compensating_invariant/fine_settle_waive_conserves_accounted_cents
        """
        bundle, fine = self._accrued_12000()
        waived = validate_success(api.waive_fine(
            fine["id"], create_waive_payload(2000, "goodwill partial waiver"),
            MANAGER), 200)
        assert waived["accrued_cents"] == 12000
        assert waived["settled_cents"] == 0
        assert waived["waived_cents"] == 2000
        assert waived["outstanding_cents"] == 10000
        assert_fine_invariant(waived)
        prop = read_property(bundle["property"]["id"])
        assert prop["outstanding_fine_balance_cents"] == 10000

    def test_settle_after_waive_zeroes_outstanding_and_clears_property(self, api):
        """Settling the remaining 10000 conserves the identity and clears the ledger.

        PRD §3.8: "a `Homeowner` settles a fine that is `ACCRUING` or `STOPPED` by
        paying `amount_cents` equal to the fine's `outstanding_cents` exactly ...
        moving the fine to `SETTLED`, setting `settled_cents` to the paid
        `amount_cents`, zeroing `outstanding_cents`, stamping `settled_at`, and
        recomputing the property."
        PRD §2.5: "the invariant `accrued_cents` equals `settled_cents` plus
        `waived_cents` plus `outstanding_cents` holds at all times."

        Design: Difficulty/compensating_invariant/fine_settle_waive_conserves_accounted_cents
        """
        bundle, fine = self._accrued_12000()
        validate_success(api.waive_fine(
            fine["id"], create_waive_payload(2000, "goodwill partial waiver"),
            MANAGER), 200)
        settled = validate_success(api.settle_fine(
            fine["id"], create_settle_payload(10000),
            make_homeowner_headers(bundle["owner"]["id"])), 200)
        assert settled["status"] == "SETTLED"
        assert settled["accrued_cents"] == 12000
        assert settled["settled_cents"] == 10000
        assert settled["waived_cents"] == 2000
        assert settled["outstanding_cents"] == 0
        assert_fine_invariant(settled)
        prop = read_property(bundle["property"]["id"])
        assert prop["outstanding_fine_balance_cents"] == 0
        assert prop["compliance_posture"] == "CLEAR"


class TestSettleSettledFine:
    """A second settle hits the state gate (P6) before the fiscal check (P11)."""

    def _settled_fine(self, api):
        bundle = setup_violation_with_fine()  # accrued == outstanding == 10000
        fine = bundle["fine"]
        settled = validate_success(api.settle_fine(
            fine["id"], create_settle_payload(10000),
            make_homeowner_headers(bundle["owner"]["id"])), 200)
        assert settled["status"] == "SETTLED"
        return bundle, settled

    def test_state_gate_beats_fiscal_on_terminal_fine(self, api):
        """A wrong-amount settle on a SETTLED fine reports ERR_INVALID_STATE, not the fiscal error.

        PRD §2.9: "Every request is validated against the rules below in the listed
        order, and the first failing rule produces the response error."
        PRD §2.9: "6. State: the target resource is in a state from which the
        requested transition is defined; otherwise `ERR_INVALID_STATE` (409)."
        PRD §3.8: "a `Homeowner` settles a fine that is `ACCRUING` or `STOPPED`"

        Design: Difficulty/priority_pair_validation_conflict/settle_settled_fine_state_beats_fiscal
        """
        bundle, settled = self._settled_fine(api)
        res = api.settle_fine(settled["id"], create_settle_payload(1),
                              make_homeowner_headers(bundle["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_first_settle_effects_and_property_recompute(self, api):
        """The successful settle sets the fields, stamps settled_at, and rebalances.

        PRD §3.8: "moving the fine to `SETTLED`, setting `settled_cents` to the paid
        `amount_cents`, zeroing `outstanding_cents`, stamping `settled_at`, and
        recomputing the property."

        Design: Difficulty/priority_pair_validation_conflict/settle_settled_fine_state_beats_fiscal
        """
        bundle, settled = self._settled_fine(api)
        assert settled["settled_cents"] == 10000
        assert settled["outstanding_cents"] == 0
        assert settled.get("settled_at"), "settled_at must be stamped"
        assert_fine_invariant(settled)
        prop = read_property(bundle["property"]["id"])
        assert prop["outstanding_fine_balance_cents"] == 0
        assert prop["compliance_posture"] == "CLEAR"


def test_fine_tier_boundary_grace_day_exact(api):
    """The grace day itself accrues at base rate; the next day escalates.

    PRD §3.8: "Under the `TIERED_ESCALATION` snapshot, a day whose index is at most
    `grace_days_snapshot` still adds the base `daily_rate_cents` — the grace day
    itself included — while a day whose index exceeds the grace count adds the
    escalated increment"

    Design: Corner/calculations/fine_tier_boundary_day_grace_exact
    """
    bundle = setup_violation_with_fine(assoc_overrides={
        "name": "Tier HOA", "fine_mode": "TIERED_ESCALATION",
        "grace_days": 3, "escalation_multiplier_bp": 20000})
    violation_id = bundle["violation"]["id"]
    set_logical_clock("2026-05-04T09:00:00Z")  # days 1..3 at base rate
    run_daily_sweep()
    fine = get_violation_fine(violation_id)
    assert fine["accrued_cents"] == 13000, (
        f"10000 + 3*1000 = 13000, got {fine['accrued_cents']}")
    set_logical_clock("2026-05-05T09:00:00Z")  # day 4 escalates
    run_daily_sweep()
    fine = get_violation_fine(violation_id)
    assert fine["accrued_cents"] == 15000, (
        f"13000 + 2000 = 15000, got {fine['accrued_cents']}")


def test_balance_aggregation_excludes_settled_fines(api):
    """Settling one of two fines drops the property balance to the other's outstanding.

    PRD §2.5: "`outstanding_fine_balance_cents` is the sum, over every violation of
    the property in any status, of that violation's single fine's
    `outstanding_cents`, where a fine's `outstanding_cents` is its `accrued_cents`
    minus its `settled_cents` minus its `waived_cents`."

    Design: Corner/calculations/balance_aggregation_excludes_settled_fines
    """
    bundle = setup_violation_with_fine()
    validate_success(api.create_violation(
        bundle["property"]["id"],
        create_violation_payload("CONDITION_BREACH", description="wrong trim color"),
        MANAGER), 201)
    prop = read_property(bundle["property"]["id"])
    assert prop["outstanding_fine_balance_cents"] == 20000, (
        f"two fines of 10000 each: {prop['outstanding_fine_balance_cents']}")

    validate_success(api.settle_fine(
        bundle["fine"]["id"], create_settle_payload(10000),
        make_homeowner_headers(bundle["owner"]["id"])), 200)
    prop = read_property(bundle["property"]["id"])
    assert prop["outstanding_fine_balance_cents"] == 10000
    assert prop["compliance_posture"] == "FINES_OUTSTANDING"


def test_waiver_exceeds_outstanding_rejected(api):
    """A waiver larger than outstanding fails; one equal to it succeeds.

    PRD §3.8: "a `Manager` waives by supplying `amount_cents` and a `reason`, with
    the amount not exceeding the fine's `outstanding_cents` — a larger waiver is
    rejected with `ERR_WAIVER_EXCEEDS_OUTSTANDING`."

    Design: Corner/errors/err_waiver_exceeds_outstanding_trigger
    """
    bundle = setup_violation_with_fine()  # outstanding == 10000
    fine_id = bundle["fine"]["id"]
    res = api.waive_fine(fine_id, create_waive_payload(10001, "too much"), MANAGER)
    validate_error(res, ApiErrorId.ERR_WAIVER_EXCEEDS_OUTSTANDING)

    waived = validate_success(api.waive_fine(
        fine_id, create_waive_payload(10000, "full goodwill"), MANAGER), 200)
    assert waived["outstanding_cents"] == 0
    assert_fine_invariant(waived)


def test_settlement_amount_mismatch_rejected(api):
    """Settlement is all-or-nothing: 9999 fails, exactly 10000 succeeds.

    PRD §3.8: "Settlement is all-or-nothing: a `Homeowner` settles a fine that is
    `ACCRUING` or `STOPPED` by paying `amount_cents` equal to the fine's
    `outstanding_cents` exactly — any other amount is rejected with
    `ERR_SETTLEMENT_AMOUNT_MISMATCH`"

    Design: Corner/errors/err_settlement_amount_mismatch_trigger
    """
    bundle = setup_violation_with_fine()  # outstanding == 10000
    fine_id = bundle["fine"]["id"]
    owner_headers = make_homeowner_headers(bundle["owner"]["id"])
    res = api.settle_fine(fine_id, create_settle_payload(9999), owner_headers)
    validate_error(res, ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH)
    assert get_violation_fine(bundle["violation"]["id"])["status"] == "ACCRUING"

    settled = validate_success(api.settle_fine(
        fine_id, create_settle_payload(10000), owner_headers), 200)
    assert settled["status"] == "SETTLED"


def test_lien_auto_files_at_exact_threshold(api):
    """Below the threshold files nothing; landing exactly on it files the lien.

    PRD §3.8: "The daily checkpoint auto-files a lien on a property when three
    conditions hold together: the property's `outstanding_fine_balance_cents` is at
    or above the association's `lien_threshold_cents`, the oldest unpaid fine is at
    least `lien_min_age_days` old, and no `FILED` lien already exists for the
    property."
    PRD §3.8: "The lien captures the property's balance at that instant in
    `amount_at_filing_cents`, stamps `filed_at`, and starts in `FILED` status"

    Design: Corner/cross_cutting_complexity_layers/lien_auto_files_at_exact_threshold
    """
    bundle = setup_violation_with_fine(assoc_overrides={
        "name": "Lien HOA", "daily_fine_cents": 2000,
        "lien_threshold_cents": 20000, "lien_min_age_days": 0})
    prop_id = bundle["property"]["id"]

    set_logical_clock("2026-05-05T09:00:00Z")  # balance 10000 + 4*2000 = 18000
    report = run_daily_sweep()
    assert report["liens_filed"] == 0, "18000 < 20000 threshold: nothing files"

    set_logical_clock("2026-05-06T09:00:00Z")  # balance exactly 20000
    report = run_daily_sweep()
    assert report["liens_filed"] == 1, "balance at-or-above threshold must file"

    liens = validate_paginated(api.list_liens(prop_id, MANAGER))[0]
    assert len(liens) == 1
    assert liens[0]["status"] == "FILED"
    assert liens[0]["amount_at_filing_cents"] == 20000
    assert read_property(prop_id)["compliance_posture"] == "LIENED"


def test_sweep_idempotent_same_day(api):
    """Re-running the checkpoint for the same logical date accrues nothing further.

    PRD §3.8: "The checkpoint is idempotent per date — `accrued_through_date`
    tracking ensures a second run for the same date accrues nothing further — and
    its response reports `applications_deemed_approved`, `fines_accrued`,
    `violations_escalated`, `liens_filed`, and `permits_expired`."

    Design: Corner/cross_cutting_complexity_layers/sweep_idempotent_same_day
    """
    bundle = setup_violation_with_fine()  # fine ACCRUING at base 10000 on 05-01
    set_logical_clock("2026-05-02T09:00:00Z")
    report1 = run_daily_sweep()
    assert report1["fines_accrued"] == 1
    report2 = run_daily_sweep()
    assert report2["fines_accrued"] == 0, "second sweep for the same date accrues nothing"
    fine = get_violation_fine(bundle["violation"]["id"])
    assert fine["accrued_cents"] == 11000
