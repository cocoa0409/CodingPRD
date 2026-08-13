"""Rate/product conversions: scheduling rules, due-date gating, terminal
idempotency, and the two pinned interest-rounding variants settled at
execution."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    api_client,
    assert_product_conversion,
    get_account,
    open_account,
    schedule_conversion,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInterestRoundingVariants:
    """Identical 3-day balance series; the product in force selects the
    rounding variant and changes the settled cents."""

    def test_interest_settlement_standard_variant_rounds_per_day(self):
        """PRD section 2.6: "Under the STANDARD variant, which applies to
        `BASIC_CHECKING`, `PREMIUM_CHECKING`, and `SAVINGS`, each day's raw
        interest is first rounded half-up to whole cents and the rounded
        daily amounts are then summed."
        PRD section 3.7: "Execution first settles the old regime: interest
        accrued over the half-open window from `accrual_start_date` to
        `effective_date`, computed under the old product's rounding variant,
        posts as an `INTEREST_CREDIT` transaction and is recorded in
        `accrued_interest_settled_cents`, which stays null until that
        moment."

        Design: Difficulty/combinatorial_formula/interest_rounding_per_day_vs_round_at_end
        """
        acct = open_account(opening_deposit_cents=100000, rate_bps=500,
                            product_code="SAVINGS",
                            primary_owner_name="Sav S", owner_tax_id="T6")
        conv = schedule_conversion(acct["id"], "BASIC_CHECKING", 100,
                                   "2026-08-04")
        assert conv["accrued_interest_settled_cents"] is None
        set_clock("2026-08-04T00:00:00Z")

        executed = validate_success(
            api_client.execute_conversion(conv["id"], OFFICER),
            expected_status=200,
        )
        assert_product_conversion(executed)
        assert executed["status"] == "COMPLETED"
        # 3 days [08-01, 08-04) at 100000 * 500bps / 365 = 13.698.../day;
        # STANDARD rounds per day: 14 * 3 = 42.
        assert executed["accrued_interest_settled_cents"] == 42

        acct_after = get_account(acct["id"])
        assert acct_after["balance_cents"] == 100042
        # PRD section 3.7: "Then the account's `product_code` becomes
        # `to_product_code`, its `rate_bps` becomes `new_rate_bps`, and its
        # `accrual_start_date` resets to `effective_date`".
        assert acct_after["product_code"] == "BASIC_CHECKING"
        assert acct_after["rate_bps"] == 100
        assert acct_after["accrual_start_date"] == "2026-08-04"

    def test_interest_settlement_simple_variant_rounds_once(self):
        """PRD section 2.6: "Under the SIMPLE variant, which applies to
        `MONEY_MARKET`, the exact raw daily amounts are summed first and a
        single half-up rounding to whole cents is applied once at the end.
        The two variants can differ by cents for the same balance series, so
        the applicable variant is always pinned — by the product in force
        during the window, or by an explicit rule where this document names
        one, as with deceased-case snapshots."

        Design: Difficulty/combinatorial_formula/interest_rounding_per_day_vs_round_at_end
        """
        acct_a = open_account(opening_deposit_cents=100000, rate_bps=500,
                              product_code="SAVINGS",
                              primary_owner_name="Sav S", owner_tax_id="T6")
        acct_b = open_account(opening_deposit_cents=100000, rate_bps=500,
                              product_code="MONEY_MARKET",
                              primary_owner_name="Mm M", owner_tax_id="T7")
        conv_a = schedule_conversion(acct_a["id"], "BASIC_CHECKING", 100,
                                     "2026-08-04")
        conv_b = schedule_conversion(acct_b["id"], "PREMIUM_CHECKING", 100,
                                     "2026-08-04")
        set_clock("2026-08-04T00:00:00Z")

        settled_a = validate_success(
            api_client.execute_conversion(conv_a["id"], OFFICER),
            expected_status=200)
        settled_b = validate_success(
            api_client.execute_conversion(conv_b["id"], OFFICER),
            expected_status=200)
        # Identical balance series; SIMPLE rounds once: floor-half-up of
        # 3 * 13.698... = 41.095... -> 41.
        assert settled_a["accrued_interest_settled_cents"] == 42
        assert settled_b["accrued_interest_settled_cents"] == 41
        assert settled_a["accrued_interest_settled_cents"] != \
            settled_b["accrued_interest_settled_cents"]

        acct_b_after = get_account(acct_b["id"])
        assert acct_b_after["balance_cents"] == 100041
        assert acct_b_after["product_code"] == "PREMIUM_CHECKING"


class TestConversionSchedulingRules:

    def test_conversion_effective_date_not_future_rejected(self):
        """PRD section 3.7: "An `OpsOfficer` schedules a conversion with a
        `to_product_code` that differs from the account's current product —
        failing shape validation with `ERR_INVALID_REQUEST` otherwise — a
        `new_rate_bps` between 0 and 2000 inclusive, and an `effective_date`
        that lies strictly after the current logical clock date
        (`ERR_EFFECTIVE_DATE_NOT_FUTURE` otherwise)."

        Design: Corner/validations/conversion_effective_date_not_future_rejected
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Eff F", owner_tax_id="C18")
        # Effective date equal to the clock date is not strictly after it.
        resp = api_client.schedule_conversion(
            acct["id"],
            {"to_product_code": "BASIC_CHECKING", "new_rate_bps": 100,
             "effective_date": "2026-08-01"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_NOT_FUTURE)

    def test_err_conversion_not_due_before_effective_date(self):
        """PRD section 3.7: "An `OpsOfficer` or the `System` principal
        executes a conversion still in `SCHEDULED` — any other status fails
        `ERR_INVALID_STATE` — once the logical clock date reaches the
        `effective_date`; executing earlier fails with
        `ERR_CONVERSION_NOT_DUE`."

        Design: Corner/errors/err_conversion_not_due_before_effective_date
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Nd N", owner_tax_id="E5")
        conv = schedule_conversion(acct["id"], "BASIC_CHECKING", 100,
                                   "2026-08-04")
        set_clock("2026-08-03T00:00:00Z")  # one day before effective

        resp = api_client.execute_conversion(conv["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CONVERSION_NOT_DUE)

        # The failed execute leaves the conversion untouched.
        convs, _meta = validate_paginated(
            api_client.list_conversions(acct["id"], OFFICER))
        by_id = {c["id"]: c for c in convs}
        assert by_id[conv["id"]]["status"] == "SCHEDULED"

    def test_conversion_execute_twice_rejected(self):
        """PRD section 3.7: "An `OpsOfficer` or the `System` principal
        executes a conversion still in `SCHEDULED` — any other status fails
        `ERR_INVALID_STATE` — once the logical clock date reaches the
        `effective_date`; executing earlier fails with
        `ERR_CONVERSION_NOT_DUE`."
        PRD section 3.7: "`COMPLETED` is terminal, and the only other exit
        from `SCHEDULED` is account closure, which cancels the conversion;
        there is no manual cancellation."

        Design: Corner/state_machines/conversion_execute_twice_rejected
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Twice W", owner_tax_id="C9")
        conv = schedule_conversion(acct["id"], "BASIC_CHECKING", 100,
                                   "2026-08-04")
        set_clock("2026-08-04T00:00:00Z")
        executed = validate_success(
            api_client.execute_conversion(conv["id"], OFFICER),
            expected_status=200)
        assert executed["status"] == "COMPLETED"

        resp = api_client.execute_conversion(conv["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
