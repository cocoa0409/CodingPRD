"""Validation coverage: each rung of the precedence ladder refusing, and persisting nothing.

PRD §2.9: "When a request violates more than one rule, the response is determined by the
**first** violated rule in the ordering below, and no later rule is evaluated. Implementations
must honour this ladder exactly."
"""

from test_helpers import (
    ACTUARY_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    ERR_ANALOG_BASIS_MISSING,
    ERR_CONTRACT_PRECEDES_LAUNCH,
    ERR_DUPLICATE_ACCRUAL,
    ERR_DUPLICATE_CODE,
    ERR_DUPLICATE_LIABILITY_RESERVE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LIABILITY_RESERVE_NOT_BOOKED,
    ERR_NO_ELIGIBLE_REMEDY_OPTION,
    ERR_NO_EXPECTED_BASE,
    ERR_NO_FAILURE_MODES_DEFINED,
    ERR_NO_OPEN_PERIOD,
    ERR_PERIOD_CLOSED,
    ERR_REGULATORY_NOTICE_MISSING,
    ERR_SELF_ANALOG_REFERENCE,
    ERR_SETTLEMENT_EXCEEDS_ASSERTED,
    ERR_SUPPLIER_IMPAIRED,
    ERR_UNPOSTED_ACCRUALS_REMAIN,
    ERR_VINTAGE_EXPOSURE_EXPIRED,
    RESERVE_CONTROLLER_USER_ID,
    actuarial_decision,
    assert_recovery,
    book_liability_reserve,
    create_accrual,
    create_failure_mode,
    create_family,
    create_field_action,
    create_liability_reserve,
    create_observation,
    create_period,
    create_recovery,
    create_remedy_option,
    create_service_contract,
    create_supplier,
    create_vintage,
    decide_field_action,
    factories,
    generate_rollforward,
    lock_period,
    open_review,
    period_version,
    post_accrual,
    propose_accrual,
    read_accrual,
    read_family,
    read_field_action,
    read_liability_reserve,
    read_period,
    read_recovery,
    read_service_contract,
    read_supplier,
    read_vintage,
    select_remedy,
    submit_field_action,
    success_data,
    validate_error,
    validate_paginated,
)


def _analog_basis(api):
    """FAM-A: 300 observed claims on a 10000-unit cohort, the standard analogue basis."""
    analog_family = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog_family["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2029-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog_family["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )
    return analog_family


def _blend_family(api, analog_family_id, family_code, name, reserve_cap_cents=20000000):
    """A 3000-unit cohort priced at 30000 cents a claim against the analogue basis."""
    family = create_family(
        api,
        family_code=family_code,
        name=name,
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=reserve_cap_cents,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family_id,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code=f"{family_code}-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code=f"FM-{family_code}-01",
        description="Blend platform mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=30000,
    )
    return family, vintage


def test_a_second_family_reusing_a_family_code_is_refused(api):
    """The code scope is global, so the second registration loses outright.

    PRD §2.9 rung 8: "Code uniqueness within the declared scope ... otherwise
    `ERR_DUPLICATE_CODE` (HTTP 409). The scopes are: `period_code` unique across all accrual
    periods, `family_code` unique across all product families".

    Design: Corner/validations/corner_duplicate_family_code_rejected
    """
    survivor = create_family(
        api,
        family_code="FAM-DUP",
        name="Duplicate Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )

    validate_error(
        api.create_product_family_raw(
            ANALYST_HEADERS,
            factories.family_payload(
                family_code="FAM-DUP",
                name="Second Duplicate Platform",
                launch_date="2025-02-01",
                base_warranty_months=12,
                standard_cost_per_claim_cents=9000,
                reserve_cap_cents=9000000,
            ),
        ),
        ERR_DUPLICATE_CODE,
        expected_status=409,
    )

    families, meta = validate_paginated(api.list_product_families(ANALYST_HEADERS))
    assert meta["total_count"] == 1
    assert families[0]["id"] == survivor["id"]
    assert families[0]["name"] == "Duplicate Platform"


def test_pointing_a_family_at_itself_as_its_own_analogue_is_refused(api):
    """The circular reference is caught even though the identifier resolves.

    PRD §2.9 rung 7: "A supplied `analog_family_id` is not the identifier of the family row
    being patched — guarding `PATCH /warranty/product-families/{familyId}` — otherwise
    `ERR_SELF_ANALOG_REFERENCE` (HTTP 422)." PRD §3.2 repeats the intent: "Pointing
    `analog_family_id` at the very row being updated is a circular reference and is refused
    with `ERR_SELF_ANALOG_REFERENCE`", and a successful update is what "advances the family's
    `version` by 1."

    Design: Corner/validations/corner_self_analog_reference_on_patch_rejected
    """
    family = create_family(
        api,
        family_code="FAM-SR",
        name="Self Reference Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    assert family["analog_family_id"] is None
    assert family["version"] == 1

    validate_error(
        api.update_product_family(
            ANALYST_HEADERS, family["id"], {"analog_family_id": family["id"]}
        ),
        ERR_SELF_ANALOG_REFERENCE,
        expected_status=422,
    )

    unchanged = read_family(api, family["id"])
    assert unchanged["analog_family_id"] is None
    assert unchanged["version"] == 1


def test_an_analog_blend_accrual_without_an_analogue_basis_is_refused(api):
    """The gate is method-specific: valid modes and a live cohort do not help.

    PRD §2.9 rung 22: "When the accrual `method` is `ANALOG_BLEND`, the vintage's family has
    both a non-null `analog_family_id` and a non-null `engineering_estimate_rate_ppm` —
    guarding `POST /warranty/accruals` — otherwise `ERR_ANALOG_BASIS_MISSING` (HTTP 422)."
    PRD §3.3 adds that only a successful create "advances the parent period's `version` by 1."

    Design: Corner/validations/corner_analog_blend_without_basis_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-AB",
        name="Analog Basis Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="AB-MY2025",
        units_shipped=800,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-01-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-AB-01",
        description="Analog basis mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=12000,
    )

    validate_error(
        api.create_accrual_raw(
            ANALYST_HEADERS,
            factories.accrual_payload(
                period["id"],
                vintage["id"],
                expected_period_version=period["version"],
                method="ANALOG_BLEND",
                elapsed_exposure_bps=1000,
            ),
        ),
        ERR_ANALOG_BASIS_MISSING,
        expected_status=422,
    )

    _, meta = validate_paginated(api.list_accruals(ANALYST_HEADERS, period_id=period["id"]))
    assert meta["total_count"] == 0
    assert read_period(api, period["id"])["version"] == 1


def test_a_family_with_no_failure_modes_outranks_the_analogue_basis_check(api):
    """Both rules are violated at once and the earlier rung answers.

    PRD §2.9 rung 21: "At least one failure mode exists for the family of the vintage being
    accrued — guarding `POST /warranty/accruals` — otherwise `ERR_NO_FAILURE_MODES_DEFINED`
    (HTTP 422)", which sits above rung 22's `ERR_ANALOG_BASIS_MISSING`. PRD §3.3: "The
    cohort's family must have at least one failure mode on file, because an accrual with
    nothing to price answers `ERR_NO_FAILURE_MODES_DEFINED`."

    Design: Corner/validations/corner_accrual_for_family_without_failure_modes_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-NF",
        name="No Failure Modes Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="NF-MY2025",
        units_shipped=800,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2029-01-31",
    )

    validate_error(
        api.create_accrual_raw(
            ANALYST_HEADERS,
            factories.accrual_payload(
                period["id"],
                vintage["id"],
                expected_period_version=period["version"],
                method="ANALOG_BLEND",
                elapsed_exposure_bps=1000,
            ),
        ),
        ERR_NO_FAILURE_MODES_DEFINED,
        expected_status=422,
    )

    _, meta = validate_paginated(api.list_accruals(ANALYST_HEADERS, period_id=period["id"]))
    assert meta["total_count"] == 0


def test_a_second_draft_accrual_for_the_same_cohort_and_period_is_refused(api):
    """The duplicate rule bites once the version guard has been satisfied afresh.

    PRD §2.9 rung 26: "No warranty accrual already exists for the same period-and-vintage pair
    in `DRAFT` or `PROPOSED` — guarding `POST /warranty/accruals` — otherwise
    `ERR_DUPLICATE_ACCRUAL` (HTTP 409)." PRD §3.3 adds the version mechanics: "the create
    advances the parent period's `version` by 1", so the second attempt must re-read the
    period before it writes.

    Design: Corner/validations/corner_duplicate_draft_accrual_for_same_period_and_vintage_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api)
    _, vintage = _blend_family(
        api, analog_family["id"], "FAM-DA", "Duplicate Accrual Platform"
    )
    first = create_accrual(
        api, period["id"], vintage["id"], method="ANALOG_BLEND", elapsed_exposure_bps=2000
    )
    assert first["status"] == "DRAFT"

    current_version = period_version(api, period["id"])

    validate_error(
        api.create_accrual_raw(
            ANALYST_HEADERS,
            factories.accrual_payload(
                period["id"],
                vintage["id"],
                expected_period_version=current_version,
                method="ANALOG_BLEND",
                elapsed_exposure_bps=4000,
            ),
        ),
        ERR_DUPLICATE_ACCRUAL,
        expected_status=409,
    )

    accruals, meta = validate_paginated(
        api.list_accruals(ANALYST_HEADERS, vintage_id=vintage["id"])
    )
    assert meta["total_count"] == 1
    assert accruals[0]["id"] == first["id"]
    assert accruals[0]["elapsed_exposure_bps"] == 2000


def test_a_second_liability_reserve_for_the_same_pair_is_refused(api):
    """The scope is the pair, so a different family in the same period is fine.

    PRD §2.9 rung 27: "No liability reserve already exists for the same period-and-family pair
    in `DRAFT`, `ACTUARY_REVIEWED` or `BOOKED` — guarding `POST /warranty/liability-reserves`
    — otherwise `ERR_DUPLICATE_LIABILITY_RESERVE` (HTTP 409)." PRD §3.8 says the same in
    prose: "only one reserve may exist per period-and-family pair across the states `DRAFT`,
    `ACTUARY_REVIEWED` and `BOOKED` — a second answers `ERR_DUPLICATE_LIABILITY_RESERVE`."

    Design: Corner/validations/corner_duplicate_liability_reserve_for_period_and_family_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    first_family = create_family(
        api,
        family_code="FAM-DL1",
        name="Duplicate Reserve Platform One",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    second_family = create_family(
        api,
        family_code="FAM-DL2",
        name="Duplicate Reserve Platform Two",
        launch_date="2024-06-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=13000,
        reserve_cap_cents=15000000,
    )
    first_reserve = create_liability_reserve(
        api,
        period["id"],
        first_family["id"],
        reported_claim_count=5,
        asserted_case_reserve_cents=500000,
        reporting_lag_months=1,
        severity_trend_bps=0,
    )

    validate_error(
        api.create_liability_reserve_raw(
            ACTUARY_HEADERS,
            factories.liability_reserve_payload(
                period["id"],
                first_family["id"],
                reported_claim_count=9,
                asserted_case_reserve_cents=900000,
                reporting_lag_months=2,
                severity_trend_bps=0,
            ),
        ),
        ERR_DUPLICATE_LIABILITY_RESERVE,
        expected_status=409,
    )

    second_reserve = create_liability_reserve(
        api,
        period["id"],
        second_family["id"],
        reported_claim_count=9,
        asserted_case_reserve_cents=900000,
        reporting_lag_months=2,
        severity_trend_bps=0,
    )

    reserves, meta = validate_paginated(
        api.list_liability_reserves(ACTUARY_HEADERS, period_id=period["id"])
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in reserves} == {first_reserve["id"], second_reserve["id"]}


def test_a_cohort_whose_warranty_has_already_run_out_cannot_be_accrued(api):
    """The cohort is born expired against the default clock, and still counts as exposure.

    PRD §3.2: the cohort's `exposure_status` "is `ACTIVE` while the logical clock is strictly
    earlier than `warranty_expiry_date` and `EXPIRED` from that date onward." PRD §2.9 rung
    25: "The referenced vintage has `exposure_status` equal to `ACTIVE` — guarding
    `POST /warranty/accruals` — otherwise `ERR_VINTAGE_EXPOSURE_EXPIRED` (HTTP 422)". Because
    that rung sits *below* rung 24's maturity gate in the same ladder, the family here is set
    up to classify `MATURE` so that rung 25 is the first rung the request violates: PRD §3.2
    makes "`history_maturity_status` ... `MATURE` when `observed_history_months` is at least 12
    **and** `observed_exposure_units` is at least 5000". PRD §3.2 also keeps the exposure metric
    intact across expiry: "`observed_exposure_units` is the sum of `units_shipped` over every
    production vintage of the family whose `exposure_status` is `ACTIVE` or `EXPIRED`."

    Design: Corner/validations/corner_expired_vintage_cannot_be_accrued
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-EP",
        name="Expired Exposure Platform",
        launch_date="2021-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
        engineering_estimate_rate_ppm=4000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="EP-MY2021",
        units_shipped=6000,
        ship_period_code="2021-Q1",
        warranty_expiry_date="2026-07-01",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-EP-01",
        description="Expired exposure mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=12000,
    )
    create_observation(
        api,
        vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=120,
        paid_cost_cents=1440000,
    )
    assert read_vintage(api, vintage["id"])["exposure_status"] == "EXPIRED"
    assert read_family(api, family["id"])["history_maturity_status"] == "MATURE"

    validate_error(
        api.create_accrual_raw(
            ANALYST_HEADERS,
            factories.accrual_payload(
                period["id"],
                vintage["id"],
                expected_period_version=period["version"],
                method="HISTORICAL_RATE",
                elapsed_exposure_bps=10000,
            ),
        ),
        ERR_VINTAGE_EXPOSURE_EXPIRED,
        expected_status=422,
    )

    assert read_family(api, family["id"])["observed_exposure_units"] == 6000


def test_a_contract_sold_before_the_family_launched_is_refused(api):
    """One day early loses; the launch date itself is accepted.

    PRD §2.9 rung 34: "A service contract's `sold_date` is the same as or later than the
    covered family's `launch_date` — guarding `POST /warranty/service-contracts` — otherwise
    `ERR_CONTRACT_PRECEDES_LAUNCH` (HTTP 422)." PRD §3.6: "`recognized_revenue_cents` is
    `total_contract_price_cents` multiplied by `months_elapsed`, divided by `term_months`,
    rounded to the nearest integer."

    Design: Corner/validations/corner_contract_sold_before_family_launch_rejected
    """
    family = create_family(
        api,
        family_code="FAM-CL",
        name="Contract Launch Platform",
        launch_date="2026-01-01",
        base_warranty_months=12,
        standard_cost_per_claim_cents=9000,
        reserve_cap_cents=10000000,
    )

    validate_error(
        api.create_service_contract_raw(
            ANALYST_HEADERS,
            factories.service_contract_payload(
                family["id"],
                contract_number="SC-CL-EARLY",
                sold_date="2025-12-31",
                term_months=12,
                total_contract_price_cents=120000,
                recognition_method="STRAIGHT_LINE",
            ),
        ),
        ERR_CONTRACT_PRECEDES_LAUNCH,
        expected_status=422,
    )

    on_launch_day = create_service_contract(
        api,
        family["id"],
        contract_number="SC-CL-ONDAY",
        sold_date="2026-01-01",
        term_months=12,
        total_contract_price_cents=120000,
        recognition_method="STRAIGHT_LINE",
    )
    assert on_launch_day["months_elapsed"] == 7
    assert on_launch_day["recognized_revenue_cents"] == 70000

    contracts, meta = validate_paginated(
        api.list_service_contracts(ANALYST_HEADERS, family_id=family["id"])
    )
    assert meta["total_count"] == 1
    assert contracts[0]["id"] == on_launch_day["id"]


def test_settling_above_the_asserted_amount_is_refused(api):
    """The comparison is inclusive, so settling at the asserted figure exactly works.

    PRD §2.9 rung 35: "When a recovery is closed as settled, the supplied
    `settled_amount_cents` does not exceed the recovery's `asserted_amount_cents` — guarding
    `POST /warranty/supplier-recoveries/{recoveryId}/close` — otherwise
    `ERR_SETTLEMENT_EXCEEDS_ASSERTED` (HTTP 422)." PRD §3.7 hop one "writes the supplied
    `settled_amount_cents`, writes the selected booking period into `settled_period_id`,
    switches `valuation_variant` to `CONTRACTUAL_FLOOR`, and recomputes
    `recognized_recovery_cents` under that variant."

    Design: Corner/validations/corner_settlement_above_asserted_amount_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    supplier = create_supplier(
        api,
        supplier_code="SUP-SE",
        name="Settlement Components AS",
        credit_rating="AAA",
        annual_purchase_volume_cents=1000000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-SE",
        name="Settlement Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=20000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-SE-01",
        description="Settlement component fault",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier["id"],
    )
    recovery = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=4000000
    )
    assert_recovery(api, recovery["id"])

    validate_error(
        api.close_recovery(
            CONTROLLER_HEADERS,
            recovery["id"],
            outcome="SETTLED",
            settled_amount_cents=5000000,
        ),
        ERR_SETTLEMENT_EXCEEDS_ASSERTED,
        expected_status=422,
    )

    refused = read_recovery(api, recovery["id"])
    assert refused["status"] == "ASSERTED"
    assert refused["settled_amount_cents"] is None

    settled = success_data(
        api.close_recovery(
            CONTROLLER_HEADERS,
            recovery["id"],
            outcome="SETTLED",
            settled_amount_cents=4000000,
        )
    )
    assert settled["status"] == "SETTLED"
    assert settled["recognized_recovery_cents"] == 4000000
    assert settled["valuation_variant"] == "CONTRACTUAL_FLOOR"
    assert settled["settled_period_id"] == period["id"]


def test_implicit_selection_with_no_eligible_candidate_mutates_nothing(api):
    """The one candidate is unapproved, so the filter empties and the row is untouched.

    PRD §2.9 rung 29: "When `remedy_option_id` is omitted, the server-side selector's
    eligibility filter yields at least one candidate — guarding
    `POST /warranty/field-actions/{fieldActionId}/select-remedy` — otherwise
    `ERR_NO_ELIGIBLE_REMEDY_OPTION` (HTTP 422)." PRD §3.5: "If the eligibility filter yields
    no candidate at all, the request answers `ERR_NO_ELIGIBLE_REMEDY_OPTION` — and in that
    case no field of the action is mutated and the action's `version` is **not** incremented",
    and only "a successful selection ... recomputes the selected option's
    `per_unit_expected_cents`."

    Design: Corner/validations/corner_select_remedy_without_eligible_option_rejected
    """
    family = create_family(
        api,
        family_code="FAM-NE",
        name="No Eligible Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-NE-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=400,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-NE-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=50,
        admin_cost_cents=100,
        expected_take_rate_bps=8000,
        is_engineering_approved=False,
    )
    before, _ = validate_paginated(api.list_remedy_options(ENGINEER_HEADERS, action["id"]))

    validate_error(
        api.select_remedy(
            ENGINEER_HEADERS, action["id"], expected_field_action_version=action["version"]
        ),
        ERR_NO_ELIGIBLE_REMEDY_OPTION,
        expected_status=422,
    )

    untouched = read_field_action(api, action["id"])
    assert untouched["selected_remedy_option_id"] is None
    assert untouched["specific_accrual_cents"] == 0
    assert untouched["version"] == 1

    after, _ = validate_paginated(api.list_remedy_options(ENGINEER_HEADERS, action["id"]))
    assert after[0]["id"] == option["id"]
    assert after[0]["per_unit_expected_cents"] == before[0]["per_unit_expected_cents"]


def test_an_adequacy_review_with_no_posted_accrual_has_no_base(api):
    """A draft estimate is not an expectation, so step three has nothing to divide by.

    PRD §3.4 step one works from "each accrual in the working set" and step three says: "If
    `expected_to_date_cents` is 0 there is no base to compare against, the review is refused
    with `ERR_NO_EXPECTED_BASE`, and nothing whatsoever is persisted." PRD §2.9 rung 31: "The
    adequacy analysis produces an expected-to-date base strictly greater than zero — guarding
    `POST /warranty/adequacy-reviews` — otherwise `ERR_NO_EXPECTED_BASE` (HTTP 422)."

    Design: Corner/validations/corner_adequacy_review_without_posted_accruals_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api)
    family, vintage = _blend_family(api, analog_family["id"], "FAM-NB", "No Base Platform")
    accrual = create_accrual(
        api, period["id"], vintage["id"], method="ANALOG_BLEND", elapsed_exposure_bps=2000
    )
    assert accrual["status"] == "DRAFT"
    assert accrual["accrued_amount_cents"] == 2910000

    validate_error(
        api.create_adequacy_review(ANALYST_HEADERS, period["id"], family["id"]),
        ERR_NO_EXPECTED_BASE,
        expected_status=422,
    )

    _, meta = validate_paginated(
        api.list_adequacy_reviews(ANALYST_HEADERS, period_id=period["id"])
    )
    assert meta["total_count"] == 0


def test_approving_a_campaign_with_no_bookable_period_is_refused(api):
    """With no period at all the selector is empty and the approval cannot land.

    PRD §2.9 rung 30: "The booking-period selector finds at least one accrual period in status
    `OPEN` or `ANALYSIS_LOCKED` — guarding `POST /warranty/field-actions/{fieldActionId}/decision`
    ... otherwise `ERR_NO_OPEN_PERIOD` (HTTP 422)." PRD §3.1: "When the candidate set is empty
    the calling operation fails with `ERR_NO_OPEN_PERIOD` and nothing is persisted." PRD §2.10
    keeps the ledger clean: "field actions in `DRAFT`, `SUBMITTED` or `REJECTED` contribute
    nothing to the approved campaign total."

    Design: Corner/validations/corner_field_action_decision_with_no_bookable_period_rejected
    """
    family = create_family(
        api,
        family_code="FAM-NP",
        name="No Period Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-NP-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=400,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-NP-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])

    validate_error(
        api.decide_field_action(CONTROLLER_HEADERS, action["id"], decision="APPROVED"),
        ERR_NO_OPEN_PERIOD,
        expected_status=422,
    )

    refused = read_field_action(api, action["id"])
    assert refused["approval_state"] == "SUBMITTED"
    assert refused["approved_period_id"] is None
    assert refused["decided_by_user_id"] is None
    assert refused["specific_accrual_cents"] == 4280000
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 0


def test_submitting_a_campaign_with_no_selected_remedy_is_refused(api):
    """Having candidates on file is not the same as having chosen one.

    PRD §2.9 rung 12 covers "a field action having a non-null `selected_remedy_option_id` when
    it is submitted", answering `ERR_INVALID_STATE_TRANSITION` (HTTP 409). PRD §3.5:
    "Submitting advances the approval dimension from `DRAFT` to `SUBMITTED` and records the
    acting engineer's identifier as `submitted_by_user_id` ... An action with a null
    `selected_remedy_option_id` cannot be submitted and answers
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/validations/corner_submit_without_selected_remedy_rejected
    """
    family = create_family(
        api,
        family_code="FAM-SB",
        name="Submit Block Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-SB-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=200,
    )
    create_remedy_option(
        api,
        action["id"],
        option_code="OPT-SB-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )

    validate_error(
        api.submit_field_action(ENGINEER_HEADERS, action["id"]),
        ERR_INVALID_STATE_TRANSITION,
        expected_status=409,
    )

    refused = read_field_action(api, action["id"])
    assert refused["approval_state"] == "DRAFT"
    assert refused["submitted_by_user_id"] is None


def test_a_safety_recall_cannot_be_approved_before_the_regulator_is_notified(api):
    """The notice gate guards only the approving branch; rejection stays open.

    PRD §2.9 rung 18: "When a field action's `is_safety_recall` is true, its
    `regulatory_notice_filed` is true before an approving decision may be recorded — guarding
    `POST /warranty/field-actions/{fieldActionId}/decision` — otherwise
    `ERR_REGULATORY_NOTICE_MISSING` (HTTP 422)." PRD §3.5: "The system derives
    `is_safety_recall` as true exactly when `action_type` is `SAFETY_RECALL`", and
    `regulatory_notice_filed` "defaults to false when omitted". PRD §3.5 on the other branch:
    "The **rejecting** branch is deliberately inert on the ledger. It advances the action to
    `REJECTED` ... and forces `specific_accrual_cents` back to 0."

    Design: Corner/validations/corner_safety_recall_approval_without_notice_rejected
    """
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-RN",
        name="Regulatory Notice Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-RN-01",
        action_type="SAFETY_RECALL",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=300,
    )
    assert action["is_safety_recall"] is True
    assert action["regulatory_notice_filed"] is False

    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RN-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])

    validate_error(
        api.decide_field_action(CONTROLLER_HEADERS, action["id"], decision="APPROVED"),
        ERR_REGULATORY_NOTICE_MISSING,
        expected_status=422,
    )
    assert read_field_action(api, action["id"])["approval_state"] == "SUBMITTED"

    rejected = decide_field_action(api, action["id"], "REJECTED")
    assert rejected["approval_state"] == "REJECTED"
    assert rejected["specific_accrual_cents"] == 0


def test_a_closed_period_refuses_new_claim_history_coded_into_it(api):
    """The period is resolved through the observation's period code, not an identifier.

    PRD §2.9 rung 11: "The accrual period that scopes the mutation — whether named directly by
    `period_id` in the body, inherited from the target row's `period_id`, or resolved through
    `observation_period_code` — does not have status `CLOSED`. This guards
    `POST /warranty/claim-observations` ... otherwise `ERR_PERIOD_CLOSED` (HTTP 409)."
    PRD §3.2 fixes the metric: `observed_history_months` "is the largest
    `months_in_service_to` found across all such observations."

    Design: Corner/validations/corner_closed_period_blocks_new_claim_observation
    """
    closing = create_period(api, "2026-Q2", "2026-04-01", "2026-06-30")
    still_open = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    lock_period(api, closing["id"])
    generate_rollforward(api, closing["id"])
    open_review(api, closing["id"])
    success_data(api.close_period(CONTROLLER_HEADERS, closing["id"]))
    assert read_period(api, closing["id"])["status"] == "CLOSED"
    assert read_period(api, still_open["id"])["status"] == "OPEN"

    family = create_family(
        api,
        family_code="FAM-PC",
        name="Period Closed Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="PC-MY2024",
        units_shipped=700,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-PC-01",
        description="Period closed mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=12000,
    )

    validate_error(
        api.create_claim_observation_raw(
            ANALYST_HEADERS,
            factories.claim_observation_payload(
                vintage["id"],
                mode["id"],
                observation_period_code="2026-Q2",
                months_in_service_from=0,
                months_in_service_to=6,
                claim_count=4,
                paid_cost_cents=40000,
            ),
        ),
        ERR_PERIOD_CLOSED,
        expected_status=409,
    )

    accepted = create_observation(
        api,
        vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=6,
        claim_count=4,
        paid_cost_cents=40000,
    )
    assert accepted["observation_period_code"] == "2026-Q3"
    assert read_family(api, family["id"])["observed_history_months"] == 6


def test_one_unposted_accrual_holds_the_period_out_of_actuarial_review(api):
    """The aggregate gate clears the moment the last estimate is booked.

    PRD §2.9 rung 13: "No warranty accrual of the period remains in `DRAFT` or `PROPOSED` —
    guarding `POST /warranty/periods/{periodId}/open-actuarial-review` — otherwise
    `ERR_UNPOSTED_ACCRUALS_REMAIN` (HTTP 409)." PRD §3.1: "Opening actuarial review moves it
    from `ANALYSIS_LOCKED` to `ACTUARIAL_REVIEW` and advances `version` by 1, but only if the
    estimation work is genuinely finished: if even one warranty accrual of the period still
    sits in `DRAFT` or `PROPOSED`, the request is refused with `ERR_UNPOSTED_ACCRUALS_REMAIN`."

    Design: Corner/validations/corner_unposted_accruals_block_actuarial_review
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api)
    _, vintage = _blend_family(api, analog_family["id"], "FAM-UP", "Unposted Platform")
    accrual = create_accrual(
        api, period["id"], vintage["id"], method="ANALOG_BLEND", elapsed_exposure_bps=2000
    )
    lock_period(api, period["id"])

    validate_error(
        api.open_actuarial_review(CONTROLLER_HEADERS, period["id"]),
        ERR_UNPOSTED_ACCRUALS_REMAIN,
        expected_status=409,
    )
    assert read_period(api, period["id"])["status"] == "ANALYSIS_LOCKED"

    propose_accrual(api, accrual["id"])
    post_accrual(api, accrual["id"])

    reviewing = open_review(api, period["id"])
    assert reviewing["status"] == "ACTUARIAL_REVIEW"

    posted = read_accrual(api, accrual["id"])
    assert posted["status"] == "POSTED"
    assert posted["accrued_amount_cents"] == 2910000


def test_an_unbooked_liability_reserve_holds_the_period_open(api):
    """The rollforward already exists, so only the reserve gate can be firing.

    PRD §2.9 rung 15: "Every liability reserve of the period has status `BOOKED` — guarding
    `POST /warranty/periods/{periodId}/close` — otherwise `ERR_LIABILITY_RESERVE_NOT_BOOKED`
    (HTTP 409)." PRD §3.1: "Two guards protect the close, and they answer with distinct codes.
    The period's `rollforward_generated` flag must already be true ... And every
    product-liability reserve of the period must have reached `BOOKED`; a reserve still in
    `DRAFT` or in `ACTUARY_REVIEWED` refuses the close with `ERR_LIABILITY_RESERVE_NOT_BOOKED`."

    Design: Corner/validations/corner_unbooked_liability_reserve_blocks_period_close
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-UB",
        name="Unbooked Reserve Platform",
        launch_date="2023-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=18000,
        reserve_cap_cents=30000000,
    )
    create_vintage(
        api,
        family["id"],
        vintage_code="UB-MY2023",
        units_shipped=1000,
        ship_period_code="2023-Q1",
        warranty_expiry_date="2028-12-31",
    )
    reserve = create_liability_reserve(
        api,
        period["id"],
        family["id"],
        reported_claim_count=20,
        asserted_case_reserve_cents=2000000,
        reporting_lag_months=2,
        severity_trend_bps=0,
    )
    lock_period(api, period["id"])
    generate_rollforward(api, period["id"])
    actuarial_decision(api, reserve["id"], "REVIEWED")
    open_review(api, period["id"])
    assert read_period(api, period["id"])["rollforward_generated"] is True

    validate_error(
        api.close_period(CONTROLLER_HEADERS, period["id"]),
        ERR_LIABILITY_RESERVE_NOT_BOOKED,
        expected_status=409,
    )
    assert read_period(api, period["id"])["status"] == "ACTUARIAL_REVIEW"

    book_liability_reserve(api, reserve["id"])
    closed = success_data(api.close_period(CONTROLLER_HEADERS, period["id"]))
    assert closed["status"] == "CLOSED"

    booked = read_liability_reserve(api, reserve["id"])
    assert booked["status"] == "BOOKED"
    assert booked["total_liability_reserve_cents"] == 2500000


def test_no_receivable_may_be_asserted_against_an_impaired_supplier(api):
    """A D-rated counterparty values every claim at nothing and refuses the assertion.

    PRD §3.7: the base rating map places `D` at `IMPAIRED`, and "when `closed_recovery_count`
    is 0 the base rating stands". PRD §3.7 weights `IMPAIRED` at 0 basis points. PRD §2.9 rung
    28: "The referenced supplier's `collectability_rating` is not `IMPAIRED` — guarding
    `POST /warranty/supplier-recoveries/{recoveryId}/assert` — otherwise
    `ERR_SUPPLIER_IMPAIRED` (HTTP 422)", and PRD §3.7 explains: "the company does not book a
    receivable against a counterparty it has already written off."

    Design: Corner/validations/corner_impaired_supplier_cannot_have_recovery_asserted
    """
    supplier = create_supplier(
        api,
        supplier_code="SUP-IM",
        name="Impaired Components GmbH",
        credit_rating="D",
        annual_purchase_volume_cents=50000000,
        contractual_recovery_cap_bps=1000,
    )
    assert supplier["collectability_rating"] == "IMPAIRED"
    assert supplier["realization_bps"] == 10000

    family = create_family(
        api,
        family_code="FAM-IM",
        name="Impaired Supplier Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=20000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-IM-01",
        description="Impaired-source relay defect",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier["id"],
    )
    recovery = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=1000000
    )
    assert recovery["recognized_recovery_cents"] == 0

    validate_error(
        api.assert_recovery(ANALYST_HEADERS, recovery["id"]),
        ERR_SUPPLIER_IMPAIRED,
        expected_status=422,
    )

    refused = read_recovery(api, recovery["id"])
    assert refused["status"] == "DRAFT"
    assert refused["assert_count"] == 0
    assert read_supplier(api, supplier["id"])["collectability_rating"] == "IMPAIRED"


def test_posting_an_accrual_that_lands_exactly_on_the_cap_succeeds(api):
    """The ceiling comparison is inclusive, and equality reads as CONSTRAINED.

    PRD §2.9 rung 36: "The reserve ceiling: the family reserve balance that would result from
    counting this accrual as posted does not exceed the family's `reserve_cap_cents` —
    guarding `POST /warranty/accruals/{accrualId}/post`." PRD §2.10: "If that ratio is at
    least 10000 basis points, `reserve_posture` becomes `CONSTRAINED` ... Both comparisons are
    inclusive, so a balance exactly equal to the cap yields `CONSTRAINED`."

    Design: Corner/validations/corner_accrual_post_at_exactly_the_reserve_cap_passes
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api)
    family, vintage = _blend_family(
        api,
        analog_family["id"],
        "FAM-CE",
        "Cap Equality Platform",
        reserve_cap_cents=2910000,
    )
    accrual = create_accrual(
        api, period["id"], vintage["id"], method="ANALOG_BLEND", elapsed_exposure_bps=2000
    )
    assert accrual["accrued_amount_cents"] == 2910000
    propose_accrual(api, accrual["id"])
    lock_period(api, period["id"])

    posted = post_accrual(api, accrual["id"])

    assert posted["status"] == "POSTED"
    assert posted["posted_by_user_id"] == RESERVE_CONTROLLER_USER_ID

    family_now = read_family(api, family["id"])
    assert family_now["warranty_reserve_balance_cents"] == 2910000
    assert family_now["reserve_posture"] == "CONSTRAINED"
