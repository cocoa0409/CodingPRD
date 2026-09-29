"""Boundary and precedence behaviour of the field-level validation rules.

Every case pairs a refusal with the nearest accepted neighbour, so the assertion
pins the boundary itself rather than merely proving that some refusal happens; where
two rules are broken at once the case names which error must surface.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    activate_markdown_stage,
    apply_for_license,
    approve_engagement,
    assert_gob_license,
    assert_instant_equals,
    assert_markdown_stage,
    assert_sales_day,
    create_engagement,
    create_jurisdiction,
    decide_license,
    engagement_payload,
    gob_license_payload,
    make_compliance_headers,
    make_consultant_headers,
    markdown_stage_payload,
    pin_clock,
    post_sales_day,
    read_store,
    reject_sales_day,
    sales_day_payload,
    store_version,
    submit_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "augmentation_prohibited": False, "prohibited_claim_codes": [],
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
NJ_RULES = dict(
    NY_RULES, code="NJ", name="New Jersey",
    prohibited_claim_codes=["LOST_OUR_LEASE"],
)
OR_RULES = {
    "code": "OR", "name": "Oregon", "gob_license_required": False,
    "max_sale_days": 90, "license_cooling_off_days": 0,
    "max_augmentation_ratio": 0.25, "augmentation_disclosure_required": False,
    "augmentation_prohibited": False, "prohibited_claim_codes": [],
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}
APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}


def _pending_store(store_code, jurisdiction_rules=None):
    """An ACTIVE engagement with one store awaiting its licence."""
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**(jurisdiction_rules or NY_RULES))
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code=store_code, address_line=f"{store_code} Liquidation Row",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    return {"jurisdiction": jurisdiction, "engagement": engagement, "store": store}


def _apply_raw(store_id, **overrides):
    return api_client.create_gob_license(
        store_id, gob_license_payload(**overrides), make_compliance_headers()
    )


def _licences_of(store_id):
    return validate_paginated(
        api_client.list_gob_licenses(store_id, make_compliance_headers())
    )


class TestLicencePeriodLengthIsCountedInclusively:
    def test_a_sixty_one_day_period_exceeds_the_jurisdiction_cap(self):
        """2026-09-15 through 2026-11-14 counts 61 days inclusively.

        The PRD says: "Fourth, `requested_days` may not exceed the jurisdiction's
        `max_sale_days`, and an over-long period is refused with
        `ERR_LICENSE_PERIOD_TOO_LONG`."

        Design: Corner/validations/license_period_of_sixty_days_is_accepted_while_sixty_one_days_is_refused
        """
        scenario = _pending_store("S-4001")
        response = _apply_raw(
            scenario["store"]["id"], license_number="NY-GOB-4001-LONG",
            period_start_date="2026-09-15", period_end_date="2026-11-14",
        )
        validate_error(response, ApiErrorId.ERR_LICENSE_PERIOD_TOO_LONG.value, 400)
        _rows, meta = _licences_of(scenario["store"]["id"])
        assert meta["total_count"] == 0

    def test_a_sixty_day_period_lands_exactly_on_the_cap_and_is_accepted(self):
        """One day earlier is exactly 60 days, which the cap permits.

        The PRD says: "`requested_days` computed as the number of days from the start of
        the period to the end of it, counted inclusively — a period whose start and end
        fall on the same day requests one day."

        Design: Corner/validations/license_period_of_sixty_days_is_accepted_while_sixty_one_days_is_refused
        """
        scenario = _pending_store("S-4001")
        _apply_raw(
            scenario["store"]["id"], license_number="NY-GOB-4001-LONG",
            period_start_date="2026-09-15", period_end_date="2026-11-14",
        )
        accepted = validate_success(
            _apply_raw(
                scenario["store"]["id"], license_number="NY-GOB-4001-OK",
                period_start_date="2026-09-15", period_end_date="2026-11-13",
            ),
            201,
        )
        assert_gob_license(accepted)
        assert accepted["license_status"] == "APPLIED"
        assert accepted["requested_days"] == 60
        _rows, meta = _licences_of(scenario["store"]["id"])
        assert meta["total_count"] == 1


def _store_whose_first_licence_ended_on_the_fourteenth_of_october():
    """A SELLING store whose approved licence covered 2026-09-15..2026-10-14."""
    scenario = _pending_store("S-4002")
    license_row = apply_for_license(
        scenario["store"]["id"], license_number="NY-GOB-4002",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    scenario["license"] = decide_license(license_row["id"])
    return scenario


class TestCoolingOffIsMeasuredFromThePriorPeriodEnd:
    def test_a_gap_of_eighteen_days_is_short_of_the_thirty_day_rule(self):
        """2026-10-14 to 2026-11-01 is 18 days, well inside the cooling-off window.

        The PRD says: "Third, the cooling-off gap is enforced against the store's most
        recent licence that was not denied: the number of days from that prior licence's
        `period_end_date` to the new application's `period_start_date` must be at least
        the jurisdiction's `license_cooling_off_days`, which is thirty days in a default
        jurisdiction; a shorter gap is refused with `ERR_LICENSE_COOLING_OFF`."

        Design: Corner/validations/license_cooling_off_counts_days_from_the_prior_period_end
        """
        scenario = _store_whose_first_licence_ended_on_the_fourteenth_of_october()
        response = _apply_raw(
            scenario["store"]["id"], license_number="NY-GOB-4002-EARLY",
            period_start_date="2026-11-01", period_end_date="2026-11-30",
        )
        validate_error(response, ApiErrorId.ERR_LICENSE_COOLING_OFF.value, 409)

    def test_a_gap_of_exactly_thirty_days_satisfies_the_boundary(self):
        """2026-11-13 is precisely thirty days after the prior period end.

        The PRD says: "Advertising claims are drawn from a fixed vocabulary:
        `LOWEST_PRICES_EVER`, `EVERYTHING_MUST_GO`, `LOST_OUR_LEASE`, `BELOW_COST`,
        `FINAL_DAYS`, and `AUGMENTED_MERCHANDISE_DISCLOSURE`."

        Design: Corner/validations/license_cooling_off_counts_days_from_the_prior_period_end
        """
        scenario = _store_whose_first_licence_ended_on_the_fourteenth_of_october()
        _apply_raw(
            scenario["store"]["id"], license_number="NY-GOB-4002-EARLY",
            period_start_date="2026-11-01", period_end_date="2026-11-30",
        )
        accepted = validate_success(
            _apply_raw(
                scenario["store"]["id"], license_number="NY-GOB-4002-OK",
                period_start_date="2026-11-13", period_end_date="2026-12-12",
            ),
            201,
        )
        assert accepted["license_status"] == "APPLIED"
        assert accepted["requested_days"] == 30

    def test_neither_application_disturbed_the_licence_already_in_force(self):
        """The original licence is still APPROVED and the store is still SELLING.

        The PRD says: "An approval moves the licence `APPLIED → APPROVED` and, across
        the entity boundary, lifts a store waiting in `LICENSE_PENDING` into `SELLING`
        with its `selling_start_date` set to the licence's `period_start_date`; the
        store's `version` increments alongside the licence's."

        Design: Corner/validations/license_cooling_off_counts_days_from_the_prior_period_end
        """
        scenario = _store_whose_first_licence_ended_on_the_fourteenth_of_october()
        _apply_raw(
            scenario["store"]["id"], license_number="NY-GOB-4002-EARLY",
            period_start_date="2026-11-01", period_end_date="2026-11-30",
        )
        _apply_raw(
            scenario["store"]["id"], license_number="NY-GOB-4002-OK",
            period_start_date="2026-11-13", period_end_date="2026-12-12",
        )
        original = validate_success(
            api_client.get_gob_license(
                scenario["license"]["id"], make_compliance_headers()
            )
        )
        assert original["license_status"] == "APPROVED"
        assert read_store(scenario["store"]["id"])["store_status"] == "SELLING"


def _store_selling_from_the_sixteenth_with_the_clock_on_the_eighteenth():
    """A licence period of 2026-09-16..2026-10-15 and a clock at 2026-09-18.

    The selling window is therefore bounded below by the licence period start and
    above by the logical clock date, two days later.
    """
    scenario = _pending_store("S-4003")
    license_row = apply_for_license(
        scenario["store"]["id"], license_number="NY-GOB-4003",
        period_start_date="2026-09-16", period_end_date="2026-10-15",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    pin_clock("2026-09-18T00:00:00Z")
    return scenario


def _file_raw(store_id, business_date):
    payload = sales_day_payload(
        business_date=business_date, original_net_sales_cents=10000,
        augmentation_net_sales_cents=0, original_units_sold=5,
        augmentation_units_sold=0,
    )
    return api_client.create_sales_day(store_id, payload, make_consultant_headers())


class TestSellingWindowContainment:
    def test_a_date_before_the_selling_start_is_outside_the_window(self):
        """2026-09-15 precedes the 2026-09-16 the licence set.

        The PRD says: "The `business_date` must fall inside the store's selling window —
        on or after the store's `selling_start_date`, on or before its `selling_end_date`
        where that date has been set, and never later than the current logical clock date
        — with any breach refused as `ERR_SALES_DAY_OUT_OF_WINDOW`."

        Design: Corner/validations/sales_day_window_rejects_dates_before_selling_start_and_after_the_clock
        """
        scenario = _store_selling_from_the_sixteenth_with_the_clock_on_the_eighteenth()
        response = _file_raw(scenario["store"]["id"], "2026-09-15")
        validate_error(response, ApiErrorId.ERR_SALES_DAY_OUT_OF_WINDOW.value, 422)

    def test_a_date_later_than_the_logical_clock_is_outside_the_window(self):
        """2026-09-19 is in the future as far as the service is concerned.

        The PRD says: "A logical clock governs every date and instant the server derives
        for itself."

        Design: Corner/validations/sales_day_window_rejects_dates_before_selling_start_and_after_the_clock
        """
        scenario = _store_selling_from_the_sixteenth_with_the_clock_on_the_eighteenth()
        response = _file_raw(scenario["store"]["id"], "2026-09-19")
        validate_error(response, ApiErrorId.ERR_SALES_DAY_OUT_OF_WINDOW.value, 422)

    def test_the_selling_start_date_itself_is_inside_the_window(self):
        """2026-09-16 is admissible, and only that one day was ever filed.

        The PRD says: "Filing moves no inventory and no ledger figure whatsoever —
        nothing happens to units or money until the retailer posts the day."

        Design: Corner/validations/sales_day_window_rejects_dates_before_selling_start_and_after_the_clock
        """
        scenario = _store_selling_from_the_sixteenth_with_the_clock_on_the_eighteenth()
        store_id = scenario["store"]["id"]
        _file_raw(store_id, "2026-09-15")
        _file_raw(store_id, "2026-09-19")
        accepted = validate_success(_file_raw(store_id, "2026-09-16"), 201)
        assert_sales_day(accepted)
        assert accepted["day_status"] == "PENDING_REVIEW"
        assert accepted["net_sales_cents"] == 10000
        _rows, meta = validate_paginated(
            api_client.list_sales_days(store_id, make_consultant_headers())
        )
        assert meta["total_count"] == 1


def _store_with_a_posted_day_and_a_rejected_day():
    """2026-09-15 is POSTED and 2026-09-16 was filed and then rejected."""
    scenario = _pending_store("S-4004")
    license_row = apply_for_license(
        scenario["store"]["id"], license_number="NY-GOB-4004",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    scenario["posted"] = post_sales_day(
        scenario["store"]["id"], business_date="2026-09-15",
        original_net_sales_cents=50000, augmentation_net_sales_cents=0,
        original_units_sold=20, augmentation_units_sold=0,
    )
    pin_clock("2026-09-16T00:00:00Z")
    scenario["rejected"] = reject_sales_day(
        scenario["store"]["id"], reject_reason="unbalanced till",
        business_date="2026-09-16", original_net_sales_cents=77000,
        augmentation_net_sales_cents=0, original_units_sold=30,
        augmentation_units_sold=0,
    )
    return scenario


class TestDuplicateSellingDayIsScopedToNonRejectedDays:
    def test_a_second_filing_for_the_posted_date_collides(self):
        """2026-09-15 is already held by a POSTED day, so the date is taken.

        The PRD says: "A store may hold at most one selling day per `business_date` in
        any status other than `REJECTED`, so a rejected day frees its date for a
        corrected refiling while a pending or posted day does not; a collision is refused
        with `ERR_DUPLICATE_SALES_DAY`."

        Design: Corner/validations/duplicate_sales_day_is_blocked_unless_the_earlier_day_was_rejected
        """
        scenario = _store_with_a_posted_day_and_a_rejected_day()
        response = _file_raw(scenario["store"]["id"], "2026-09-15")
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SALES_DAY.value, 409)

    def test_the_rejected_date_is_free_for_a_corrected_refiling(self):
        """2026-09-16 was rejected, so a replacement filing for it is admitted.

        The PRD says: "A rejection takes the day `PENDING_REVIEW → REJECTED`, records
        `reviewed_by_user_id`, and does nothing else at all: no unit allocation, no ledger
        recomputation, and the day leaves the inclusion set of both settlement bases
        described in §3.9."

        Design: Corner/validations/duplicate_sales_day_is_blocked_unless_the_earlier_day_was_rejected
        """
        scenario = _store_with_a_posted_day_and_a_rejected_day()
        store_id = scenario["store"]["id"]
        _file_raw(store_id, "2026-09-15")
        replacement = validate_success(
            api_client.create_sales_day(
                store_id,
                sales_day_payload(
                    business_date="2026-09-16", original_net_sales_cents=60000,
                    augmentation_net_sales_cents=0, original_units_sold=25,
                    augmentation_units_sold=0,
                ),
                make_consultant_headers(),
            ),
            201,
        )
        assert replacement["day_status"] == "PENDING_REVIEW"
        assert replacement["net_sales_cents"] == 60000
        _rows, meta = validate_paginated(
            api_client.list_sales_days(store_id, make_consultant_headers())
        )
        assert meta["total_count"] == 3

    def test_only_the_posted_day_reached_the_realized_ledger(self):
        """The rejected day and the pending replacement contribute nothing.

        The PRD says: "The store's `realized_gross_recovery_cents` is the sum of
        `net_sales_cents` over its selling days whose status is `POSTED`; days still in
        review and rejected days contribute nothing."

        Design: Corner/validations/duplicate_sales_day_is_blocked_unless_the_earlier_day_was_rejected
        """
        scenario = _store_with_a_posted_day_and_a_rejected_day()
        store_id = scenario["store"]["id"]
        _file_raw(store_id, "2026-09-15")
        api_client.create_sales_day(
            store_id,
            sales_day_payload(
                business_date="2026-09-16", original_net_sales_cents=60000,
                augmentation_net_sales_cents=0, original_units_sold=25,
                augmentation_units_sold=0,
            ),
            make_consultant_headers(),
        )
        store = read_store(store_id)
        assert store["realized_gross_recovery_cents"] == 50000
        assert store["units_sold_total"] == 20


FIRST_STAGE = {
    "stage_index": 1, "discount_pct": 0.2, "sell_through_target_pct": 0.25,
    "window_start_date": "2026-09-16", "window_end_date": "2026-10-01",
}


def _oregon_store_selling_without_any_licence():
    """An Oregon store, which sells from approval without a regulator's permission."""
    return _pending_store("S-4005", jurisdiction_rules=OR_RULES)


class TestLicenceGateIsSkippedWhereNoLicenceIsRequired:
    def test_approval_takes_the_store_straight_into_selling(self):
        """Oregon needs no licence, so the store never waits in LICENSE_PENDING.

        The PRD says: "An `APPROVE` decision moves the engagement
        `PENDING_RETAILER_APPROVAL → ACTIVE` and cascades over every store still in `PLANNED`, splitting on that store's own
        jurisdiction: where the jurisdiction requires a going-out-of-business licence the
        store moves `PLANNED → LICENSE_PENDING` and stays shut until a licence is granted,
        and where the jurisdiction requires none the store moves `PLANNED → SELLING`
        immediately with its `selling_start_date` set to the engagement's
        `sale_start_date`."

        Design: Corner/validations/license_gate_is_skipped_where_the_jurisdiction_requires_no_license
        """
        scenario = _oregon_store_selling_without_any_licence()
        store = read_store(scenario["store"]["id"])
        assert store["store_status"] == "SELLING"
        assert store["selling_start_date"] == "2026-09-15"
        assert store["version"] == 2
        _rows, meta = _licences_of(store["id"])
        assert meta["total_count"] == 0

    def test_a_stage_activates_with_no_licence_on_file_at_all(self):
        """The licence-coverage precondition simply does not apply here.

        The PRD says: "Where the jurisdiction requires a licence, the store must hold an
        `APPROVED` licence whose period covers the stage's entire window — its
        `period_start_date` on or before the stage's `window_start_date`, and its
        `period_end_date` on or after the day immediately preceding the stage's
        `window_end_date`, which is the last day the half-open window actually sells —
        otherwise `ERR_LICENSE_NOT_ACTIVE`."

        Design: Corner/validations/license_gate_is_skipped_where_the_jurisdiction_requires_no_license
        """
        scenario = _oregon_store_selling_without_any_licence()
        stage = add_markdown_stage(scenario["store"]["id"], **FIRST_STAGE)
        activated = activate_markdown_stage(stage["id"])
        assert_markdown_stage(activated)
        assert activated["stage_status"] == "ACTIVE"
        assert_instant_equals(
            activated["activated_at"], "2026-09-15T00:00:00Z", "activated_at"
        )
        _rows, meta = _licences_of(scenario["store"]["id"])
        assert meta["total_count"] == 0

    def test_the_active_stage_drives_the_unlicensed_store_s_projection(self):
        """A 0.2000 planned discount cuts 4,250,000 cents of ticket to 3,400,000.

        The PRD says: "That projected unit count is multiplied by the lot's
        `unit_retail_cents` and then by one minus the store's planned average discount, and
        the result is rounded half up to whole cents and stored as the lot's
        `projected_recovery_cents`."

        Design: Corner/validations/license_gate_is_skipped_where_the_jurisdiction_requires_no_license
        """
        scenario = _oregon_store_selling_without_any_licence()
        stage = add_markdown_stage(scenario["store"]["id"], **FIRST_STAGE)
        activate_markdown_stage(stage["id"])
        store = read_store(scenario["store"]["id"])
        assert store["planned_avg_discount_pct"] == pytest.approx(0.2000, abs=0.00001)
        assert store["projected_gross_recovery_cents"] == 3400000
        assert store["projected_recovery_ratio"] == pytest.approx(1.7000, abs=0.00001)


class TestClaimRuleOrderingAndListHygiene:
    def test_a_doubled_prohibited_code_reports_the_prohibition_not_the_duplicate(self):
        """Both faults are present and the prohibition check runs first.

        The PRD says: "First, no declared claim may appear in the jurisdiction's
        `prohibited_claim_codes` list; an intersection is refused with
        `ERR_PROHIBITED_ADVERTISING_CLAIM`."

        Design: Corner/validations/prohibited_claim_code_outranks_the_duplicate_claim_code_check
        """
        scenario = _pending_store("S-4006", jurisdiction_rules=NJ_RULES)
        response = _apply_raw(
            scenario["store"]["id"], license_number="NJ-GOB-4006-A",
            period_start_date="2026-09-15", period_end_date="2026-10-14",
            advertising_claim_codes=["LOST_OUR_LEASE", "LOST_OUR_LEASE"],
        )
        error = validate_error(
            response, ApiErrorId.ERR_PROHIBITED_ADVERTISING_CLAIM.value, 409
        )
        assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_CLAIM_CODE.value

    def test_a_doubled_permitted_code_reports_the_duplicate(self):
        """With no prohibition to catch it, the list-hygiene rule surfaces.

        The PRD says: "Beyond those, the claim list itself must be well formed — it must
        carry at least one code and must not repeat a code — with either fault refused as
        `ERR_DUPLICATE_CLAIM_CODE`."

        Design: Corner/validations/prohibited_claim_code_outranks_the_duplicate_claim_code_check
        """
        scenario = _pending_store("S-4006", jurisdiction_rules=NJ_RULES)
        response = _apply_raw(
            scenario["store"]["id"], license_number="NJ-GOB-4006-B",
            period_start_date="2026-09-15", period_end_date="2026-10-14",
            advertising_claim_codes=["EVERYTHING_MUST_GO", "EVERYTHING_MUST_GO"],
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM_CODE.value, 400)

    def test_a_single_permitted_code_clears_both_rules(self):
        """One unrepeated, unbanned claim is accepted and is the only licence filed.

        The PRD says: "A `ComplianceOfficer` files the application against the store,
        supplying the regulator's `license_number`, the inclusive first licensed selling
        day `period_start_date`, the inclusive last licensed selling day
        `period_end_date`, and the list of `advertising_claim_codes` the licence is to
        authorise."

        Design: Corner/validations/prohibited_claim_code_outranks_the_duplicate_claim_code_check
        """
        scenario = _pending_store("S-4006", jurisdiction_rules=NJ_RULES)
        store_id = scenario["store"]["id"]
        _apply_raw(
            store_id, license_number="NJ-GOB-4006-A",
            period_start_date="2026-09-15", period_end_date="2026-10-14",
            advertising_claim_codes=["LOST_OUR_LEASE", "LOST_OUR_LEASE"],
        )
        _apply_raw(
            store_id, license_number="NJ-GOB-4006-B",
            period_start_date="2026-09-15", period_end_date="2026-10-14",
            advertising_claim_codes=["EVERYTHING_MUST_GO", "EVERYTHING_MUST_GO"],
        )
        accepted = validate_success(
            _apply_raw(
                store_id, license_number="NJ-GOB-4006-C",
                period_start_date="2026-09-15", period_end_date="2026-10-14",
                advertising_claim_codes=["EVERYTHING_MUST_GO"],
            ),
            201,
        )
        assert accepted["license_status"] == "APPLIED"
        assert accepted["advertising_claim_codes"] == ["EVERYTHING_MUST_GO"]
        _rows, meta = _licences_of(store_id)
        assert meta["total_count"] == 1


def _draft_engagement(**overrides):
    return api_client.create_engagement(
        engagement_payload(**overrides), make_consultant_headers()
    )


class TestEconomicsConfigurationCoherence:
    def test_a_fee_based_agreement_may_not_carry_a_guaranty_rate(self):
        """A 0.50 guaranty rate contradicts the FEE_BASED model outright.

        The PRD says: "A `GUARANTEED` or `HYBRID` agreement requires `guaranty_pct` to be
        strictly greater than 0; a `FEE_BASED` agreement requires it to carry no value at
        all or exactly 0."

        Design: Corner/validations/economics_fields_contradicting_the_model_are_refused
        """
        pin_clock("2026-09-15T00:00:00Z")
        response = _draft_engagement(
            economics_model="FEE_BASED", guaranty_pct=0.5,
            hybrid_retailer_excess_pct=0, expense_responsibility="LIQUIDATOR",
            shared_expense_liquidator_pct=0,
        )
        validate_error(response, ApiErrorId.ERR_ECONOMICS_CONFIG_INVALID.value, 422)

    def test_shared_responsibility_may_not_carry_a_zero_liquidator_fraction(self):
        """SHARED expenses with a 0 liquidator fraction share nothing.

        The PRD says: "When `expense_responsibility` is `SHARED`,
        `shared_expense_liquidator_pct` must be strictly greater than 0; under
        `LIQUIDATOR` or `RETAILER` responsibility it must be exactly 0."

        Design: Corner/validations/economics_fields_contradicting_the_model_are_refused
        """
        pin_clock("2026-09-15T00:00:00Z")
        response = _draft_engagement(
            economics_model="FEE_BASED", guaranty_pct=0,
            hybrid_retailer_excess_pct=0, expense_responsibility="SHARED",
            shared_expense_liquidator_pct=0,
        )
        validate_error(response, ApiErrorId.ERR_ECONOMICS_CONFIG_INVALID.value, 422)

    def test_a_hybrid_agreement_may_not_carry_a_zero_excess_share(self):
        """A HYBRID with no retailer excess share is not a hybrid at all.

        The PRD says: "A `HYBRID` agreement requires `hybrid_retailer_excess_pct` to be
        strictly greater than 0, while `GUARANTEED` and `FEE_BASED` agreements require it
        to be exactly 0 — this field is never null."

        Design: Corner/validations/economics_fields_contradicting_the_model_are_refused
        """
        pin_clock("2026-09-15T00:00:00Z")
        response = _draft_engagement(
            economics_model="HYBRID", guaranty_pct=1.2,
            hybrid_retailer_excess_pct=0, expense_responsibility="LIQUIDATOR",
            shared_expense_liquidator_pct=0,
        )
        validate_error(response, ApiErrorId.ERR_ECONOMICS_CONFIG_INVALID.value, 422)

    def test_a_coherent_guaranteed_agreement_at_the_rate_ceiling_is_accepted(self):
        """A 1.5 guaranty with a 0.40 shared fraction satisfies all three rules.

        The PRD says: "Those five economic fields must be mutually consistent, and the
        coherence check is applied twice — once when the agreement is drafted and again
        when it is submitted for approval — with any breach reported as
        `ERR_ECONOMICS_CONFIG_INVALID`."

        Design: Corner/validations/economics_fields_contradicting_the_model_are_refused
        """
        pin_clock("2026-09-15T00:00:00Z")
        engagement = validate_success(
            _draft_engagement(
                economics_model="GUARANTEED", guaranty_pct=1.5,
                hybrid_retailer_excess_pct=0, expense_responsibility="SHARED",
                shared_expense_liquidator_pct=0.4,
            ),
            201,
        )
        assert engagement["economics_model"] == "GUARANTEED"
        assert engagement["guaranty_pct"] == pytest.approx(1.5000, abs=0.00001)
        assert engagement["shared_expense_liquidator_pct"] == pytest.approx(
            0.4000, abs=0.00001
        )
        assert engagement["guaranty_amount_cents"] == 0
        assert engagement["engagement_status"] == "DRAFT"


class TestIntervalOrderingRunsBeforeTheSubstantiveRules:
    def test_an_inverted_licence_period_reports_the_date_range_not_the_length(self):
        """2026-12-31 to 2026-09-15 is both inverted and far over the 60-day cap.

        The PRD says: "Interval ordering of paired date fields on
        `POST /stores/{id}/gob-licenses`, `POST /stores/{id}/markdown-stages`,
        `POST /stores/{id}/augmentation-consignments`, and
        `POST /stores/{id}/employees`: `period_start_date` must not be later than
        `period_end_date`, `window_start_date` must not be later than `window_end_date`,
        `delivery_window_start_date` must not be later than
        `delivery_window_end_date`, and `retention_start_date` must not be later than
        `retention_target_date` — otherwise `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/inverted_date_interval_is_caught_before_the_length_and_sequence_checks
        """
        scenario = _pending_store("S-4008")
        response = _apply_raw(
            scenario["store"]["id"], license_number="NY-GOB-4008",
            period_start_date="2026-12-31", period_end_date="2026-09-15",
        )
        error = validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 400)
        assert error["error_id"] != ApiErrorId.ERR_LICENSE_PERIOD_TOO_LONG.value

    def test_an_inverted_stage_window_reports_the_date_range_not_the_sequence(self):
        """Index 7 on a store with no stages is also wrong, and the dates win.

        The PRD says: "`stage_index` is one-based and must be exactly one greater than the
        highest `stage_index` already present on the store among stages that have not been
        voided, so the first stage of a store is index 1 and a voided stage leaves no gap
        behind it."

        Design: Corner/validations/inverted_date_interval_is_caught_before_the_length_and_sequence_checks
        """
        scenario = _pending_store("S-4008")
        store_id = scenario["store"]["id"]
        response = api_client.create_markdown_stage(
            store_id,
            markdown_stage_payload(
                store_version(store_id), stage_index=7, discount_pct=0.3,
                sell_through_target_pct=0.5,
                window_start_date="2026-10-01", window_end_date="2026-09-16",
            ),
            make_consultant_headers(),
        )
        error = validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 400)
        assert error["error_id"] != ApiErrorId.ERR_STAGE_SEQUENCE_INVALID.value

    def test_neither_refusal_wrote_a_row_or_moved_the_store_version(self):
        """No licence, no stage, and the store's version is exactly where it was.

        The PRD says: "If the store's current `version` differs, the create is refused
        with `ERR_STALE_STORE_VERSION` (HTTP 412) and no stage is authored."

        Design: Corner/validations/inverted_date_interval_is_caught_before_the_length_and_sequence_checks
        """
        scenario = _pending_store("S-4008")
        store_id = scenario["store"]["id"]
        before = store_version(store_id)
        _apply_raw(
            store_id, license_number="NY-GOB-4008",
            period_start_date="2026-12-31", period_end_date="2026-09-15",
        )
        api_client.create_markdown_stage(
            store_id,
            markdown_stage_payload(
                before, stage_index=7, discount_pct=0.3,
                sell_through_target_pct=0.5,
                window_start_date="2026-10-01", window_end_date="2026-09-16",
            ),
            make_consultant_headers(),
        )
        _licences, licence_meta = _licences_of(store_id)
        assert licence_meta["total_count"] == 0
        _stages, stage_meta = validate_paginated(
            api_client.list_markdown_stages(store_id, make_consultant_headers())
        )
        assert stage_meta["total_count"] == 0
        assert store_version(store_id) == before


def _selling_store_with_one_armed_stage_at_twenty_percent():
    """A licensed SELLING store whose cadence holds a single ARMED stage at 0.2000."""
    scenario = _pending_store("S-4009")
    license_row = apply_for_license(
        scenario["store"]["id"], license_number="NY-GOB-4009",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    scenario["stage_one"] = add_markdown_stage(scenario["store"]["id"], **FIRST_STAGE)
    scenario["store_version"] = store_version(scenario["store"]["id"])
    return scenario


def _author_raw(store_id, expected_version, **overrides):
    payload = markdown_stage_payload(
        expected_version, sell_through_target_pct=0.5,
        window_start_date="2026-10-01", window_end_date="2026-10-14", **overrides
    )
    return api_client.create_markdown_stage(
        store_id, payload, make_consultant_headers()
    )


class TestStageSequenceAndDiscountMonotonicity:
    def test_an_index_that_skips_the_successor_is_refused(self):
        """Index 3 leaves a gap behind index 1, so it is not the next stage.

        The PRD says: "Any of those three faults is refused with
        `ERR_STAGE_SEQUENCE_INVALID`."

        Design: Corner/validations/stage_sequence_requires_next_index_strictly_deeper_discount_within_the_cap
        """
        scenario = _selling_store_with_one_armed_stage_at_twenty_percent()
        response = _author_raw(
            scenario["store"]["id"], scenario["store_version"],
            stage_index=3, discount_pct=0.3,
        )
        validate_error(response, ApiErrorId.ERR_STAGE_SEQUENCE_INVALID.value, 422)

    def test_a_discount_shallower_than_its_predecessor_is_refused(self):
        """0.15 after 0.20 reverses the cadence instead of deepening it.

        The PRD says: "`discount_pct` is a fraction to four decimal places that may not
        exceed 0.9000 — a ninety-percent markdown is the deepest this service will record
        — and it must be strictly greater than the `discount_pct` of that predecessor
        stage, because a cadence that flattens or reverses is not a liquidation cadence."

        Design: Corner/validations/stage_sequence_requires_next_index_strictly_deeper_discount_within_the_cap
        """
        scenario = _selling_store_with_one_armed_stage_at_twenty_percent()
        response = _author_raw(
            scenario["store"]["id"], scenario["store_version"],
            stage_index=2, discount_pct=0.15,
        )
        validate_error(response, ApiErrorId.ERR_STAGE_SEQUENCE_INVALID.value, 422)

    def test_a_discount_beyond_the_ninety_percent_cap_is_refused(self):
        """0.95 is deeper than its predecessor but deeper than the model allows.

        The PRD says: "`discount_pct` is a fraction to four decimal places that may not
        exceed 0.9000 — a ninety-percent markdown is the deepest this service will record
        — and it must be strictly greater than the `discount_pct` of that predecessor
        stage, because a cadence that flattens or reverses is not a liquidation cadence."

        Design: Corner/validations/stage_sequence_requires_next_index_strictly_deeper_discount_within_the_cap
        """
        scenario = _selling_store_with_one_armed_stage_at_twenty_percent()
        response = _author_raw(
            scenario["store"]["id"], scenario["store_version"],
            stage_index=2, discount_pct=0.95,
        )
        validate_error(response, ApiErrorId.ERR_STAGE_SEQUENCE_INVALID.value, 422)

    def test_the_next_index_at_a_deeper_permitted_discount_is_accepted(self):
        """Index 2 at 0.3000 is the successor stage the rules describe.

        The PRD says: "A newly authored stage begins at `stage_status` of `ARMED` with
        `escalation_applied_pct` at exactly 0.0000, `closed_reason` and
        `checkpoint_sell_through_pct` unset, and `activated_at` unset."

        Design: Corner/validations/stage_sequence_requires_next_index_strictly_deeper_discount_within_the_cap
        """
        scenario = _selling_store_with_one_armed_stage_at_twenty_percent()
        accepted = validate_success(
            _author_raw(
                scenario["store"]["id"], scenario["store_version"],
                stage_index=2, discount_pct=0.3,
            ),
            201,
        )
        assert_markdown_stage(accepted)
        assert accepted["stage_status"] == "ARMED"
        assert accepted["stage_index"] == 2
        assert accepted["discount_pct"] == pytest.approx(0.3000, abs=0.00001)

    def test_the_two_armed_stages_average_into_the_planned_discount(self):
        """0.2000 and 0.3000 mean 0.2500, which cuts the projection to 3,187,500.

        The PRD says: "It begins from the store's planned discount: gather the store's
        markdown stages whose status is `ARMED` or `ACTIVE`, and if that set is empty the
        store's `planned_avg_discount_pct` is exactly 0.0000, otherwise it is the sum of
        those stages' `discount_pct` values divided by how many stages are in the set,
        rounded half up to four decimal places."

        Design: Corner/validations/stage_sequence_requires_next_index_strictly_deeper_discount_within_the_cap
        """
        scenario = _selling_store_with_one_armed_stage_at_twenty_percent()
        _author_raw(
            scenario["store"]["id"], scenario["store_version"],
            stage_index=2, discount_pct=0.3,
        )
        store = read_store(scenario["store"]["id"])
        assert store["planned_avg_discount_pct"] == pytest.approx(0.2500, abs=0.00001)
        assert store["projected_gross_recovery_cents"] == 3187500
