"""Validation breadth, part two: the temporal preconditions, the inclusive
count and sample bounds, the two places where one refusal outranks another,
and the terminal states that refuse a second decision."""

from test_helpers import (
    COUNSEL,
    FINANCE,
    LEAD,
    ApiErrorId,
    affiliation_version,
    api_client,
    assert_batch_record_ledger,
    assert_earnout_pool_ledger,
    assert_payer_contract,
    activate_fee_schedule,
    add_fee_schedule_item,
    advance_to_diligence,
    approve_enrollment,
    build_approved_supply_exception,
    build_clinical_director,
    build_closed_deal,
    build_contract_ready_for_activation,
    build_deal_in_draft,
    build_scheduled_batch,
    create_affiliation,
    create_clinical_quality_review_payload,
    create_conversion_vendor,
    create_earnout_tranche_payload,
    create_migration_batch_payload,
    create_payer_contract,
    create_payer_enrollment,
    create_practice,
    create_service_agreement,
    harmonize_compensation,
    make_clinical_director_headers,
    monthly_collections_series,
    practice_version,
    project_tranche,
    read_affiliation,
    read_earnout_tranche,
    read_employment,
    read_migration_batch,
    read_payer_contract,
    read_payer_enrollment,
    read_practice,
    read_service_agreement,
    read_supply_preference_exception,
    set_clock,
    validate_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOSE_DAY = "2026-09-01T00:00:00Z"
CUTOVER_START = "2026-09-05T00:00:00Z"
CUTOVER_END = "2026-09-06T00:00:00Z"
INSIDE_WINDOW = "2026-09-05T12:00:00Z"
ONE_SECOND_EARLY = "2026-09-04T23:59:59Z"
MEASUREMENT_START = "2026-09-01T00:00:00Z"
MEASUREMENT_END = "2027-09-01T00:00:00Z"
SUBMIT_CLOCK = "2026-11-15T00:00:00Z"
ENROLLMENT_EFFECTIVE = "2027-02-13T00:00:00Z"
RESERVE_CLOCK = "2027-03-01T00:00:00Z"


def test_a_batch_may_quarantine_every_record_but_never_one_more():
    """PRD §3.5: "The request supplies `quarantined_count`, which may not exceed the batch's `records_total` — a larger figure is refused with `ERR_QUARANTINE_COUNT_EXCEEDS_TOTAL`."
    PRD §3.5: "On the **quarantining** branch, the whole batch is held back rather than only the failing records: the batch moves `SCHEDULED → QUARANTINED`, `records_quarantined` is set to the full `records_total`, `records_validated` is set to zero, `records_pending` becomes zero, the practice's `charts_migrated_count` is left completely unchanged so no chart credit at all flows, the vendor's `active_window_count` still decreases by one, the practice's `quarantined_batch_count` increases by one and the recomputed posture carries the practice `STABILIZING → RESTRICTED`, and both versions increment by one."

    Design: Corner/validations/quarantine_count_may_equal_but_not_exceed_records_total
    """
    ctx = build_closed_deal()
    batch = build_scheduled_batch(
        ctx["practice_id"], CUTOVER_START, CUTOVER_END, records_total=5000
    )
    set_clock(INSIDE_WINDOW)

    validate_error(
        api_client.validate_batch(batch["id"], {"quarantined_count": 5001}, LEAD),
        ApiErrorId.ERR_QUARANTINE_COUNT_EXCEEDS_TOTAL.value,
        422,
    )
    refused = read_migration_batch(batch["id"])
    assert refused["status"] == "SCHEDULED"
    assert refused["records_quarantined"] == 0

    quarantined = validate_batch(batch["id"], 5000)
    assert quarantined["validation_error_rate_bps"] == 10_000
    assert quarantined["records_quarantined"] == 5000
    assert quarantined["records_validated"] == 0
    assert quarantined["status"] == "QUARANTINED"
    assert_batch_record_ledger(quarantined)

    practice = read_practice(ctx["practice_id"])
    assert practice["charts_migrated_count"] == 0
    assert practice["quarantined_batch_count"] == 1
    assert practice["integration_posture"] == "RESTRICTED"


def test_a_sample_of_nineteen_charts_is_below_the_statistical_floor():
    """PRD §3.8: "The sample must clear a statistical floor of 20 charts, where exactly 20 is acceptable and 19 is refused with `ERR_SAMPLE_SIZE_TOO_SMALL`, and neither `charts_with_findings` nor `treatment_plan_overrides` may exceed `charts_sampled`, a violation of which is a payload failure reported as `ERR_INVALID_REQUEST`."
    PRD §3.8: "The review opens in `OPEN` with no `closed_by_doctor_id` and no `outcome_note`."

    Design: Corner/validations/quality_review_sample_below_minimum_rejected
    """
    ctx = build_closed_deal()
    director, director_headers = build_clinical_director()

    validate_error(
        api_client.create_clinical_quality_review(
            create_clinical_quality_review_payload(
                ctx["employment_id"],
                charts_sampled=19,
                charts_with_findings=0,
                treatment_plan_overrides=0,
            ),
            director_headers,
        ),
        ApiErrorId.ERR_SAMPLE_SIZE_TOO_SMALL.value,
        422,
    )

    review = validate_success(
        api_client.create_clinical_quality_review(
            create_clinical_quality_review_payload(
                ctx["employment_id"],
                charts_sampled=20,
                charts_with_findings=5,
                treatment_plan_overrides=5,
            ),
            director_headers,
        ),
        expected_status=201,
    )
    assert review["finding_rate_bps"] == 2500
    assert review["override_rate_bps"] == 2500
    assert review["score_bps"] == 7500
    assert review["status"] == "OPEN"

    _, meta = validate_paginated(
        api_client.list_employment_clinical_quality_reviews(
            ctx["employment_id"], make_clinical_director_headers(director["id"])
        )
    )
    assert meta["total_count"] == 1


def test_measurement_periods_may_touch_but_never_overlap():
    """PRD §3.9: "Measurement periods of the same affiliation may abut but may never overlap: the requested half-open period is compared against every existing tranche of that affiliation whose status is not `CLAWED_BACK`, adjacency is allowed, and a genuine overlap is refused with `ERR_MEASUREMENT_PERIOD_OVERLAP`."
    PRD §2.3: "Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order."

    Design: Corner/validations/measurement_periods_may_abut_but_may_not_overlap
    """
    ctx = build_closed_deal()
    first = project_tranche(
        ctx["affiliation_id"],
        period_label="EO-Y1",
        measurement_start=MEASUREMENT_START,
        measurement_end=MEASUREMENT_END,
    )

    abutting = project_tranche(
        ctx["affiliation_id"],
        period_label="EO-Y2",
        measurement_start=MEASUREMENT_END,
        measurement_end="2028-09-01T00:00:00Z",
    )
    assert abutting["status"] == "PROJECTED"

    validate_error(
        api_client.create_earnout_tranche(
            create_earnout_tranche_payload(
                ctx["affiliation_id"],
                affiliation_version(ctx["affiliation_id"]),
                period_label="EO-Y2B",
                measurement_start="2027-08-31T00:00:00Z",
                measurement_end="2028-08-31T00:00:00Z",
            ),
            FINANCE,
        ),
        ApiErrorId.ERR_MEASUREMENT_PERIOD_OVERLAP.value,
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_earnout_tranches(FINANCE, {"affiliation_id": ctx["affiliation_id"]})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], abutting["id"]]


def test_validation_waits_for_the_cutover_window_to_open():
    """PRD §3.5: "The batch must be `SCHEDULED`; the logical clock must be at or after the batch's `cutover_start_at`, and an earlier clock is refused with `ERR_CUTOVER_WINDOW_NOT_STARTED`; and the practice's posture must be `STABILIZING`, `INTEGRATED` or `RESTRICTED`."
    PRD §3.5: "On the **validating** branch, the batch moves `SCHEDULED → VALIDATED`, `records_quarantined` is set to the reported `quarantined_count`, `records_validated` is set to `records_total` less that count, `records_pending` becomes zero, the practice's `charts_migrated_count` increases by `records_validated`, the vendor's `active_window_count` decreases by one, the practice's posture is recomputed — which can carry it `STABILIZING → INTEGRATED` once `charts_migrated_count` reaches `charts_total_expected` and no other blocker remains — and both the batch's `version` and the practice's `version` increment by one."

    Design: Corner/validations/validation_cannot_run_before_the_cutover_window_opens
    """
    ctx = build_closed_deal()
    batch = build_scheduled_batch(
        ctx["practice_id"], CUTOVER_START, CUTOVER_END, records_total=5000
    )
    set_clock(ONE_SECOND_EARLY)

    validate_error(
        api_client.validate_batch(batch["id"], {"quarantined_count": 0}, LEAD),
        ApiErrorId.ERR_CUTOVER_WINDOW_NOT_STARTED.value,
        409,
    )
    assert read_migration_batch(batch["id"])["status"] == "SCHEDULED"

    set_clock(CUTOVER_START)
    validated = validate_batch(batch["id"], 0)
    assert validated["status"] == "VALIDATED"
    assert validated["validation_error_rate_bps"] == 0
    assert validated["records_validated"] == 5000

    practice = read_practice(ctx["practice_id"])
    assert practice["charts_migrated_count"] == 5000
    assert practice["integration_posture"] == "INTEGRATED"


def test_a_reservation_needs_one_whole_elapsed_day_and_may_pay_nothing():
    """PRD §3.9: "In the `PROVISIONAL` variant the collections and expense inputs are `reported_net_collections_cents` and `reported_expenses_cents`, and the elapsed-day count is the whole days from `measurement_start` to the logical clock, taking the floor of the UTC difference; at least one whole day must have elapsed, so a reservation with zero or fewer elapsed days is refused with `ERR_MEASUREMENT_PERIOD_NOT_STARTED` rather than dividing by zero."
    PRD §3.9: "Rounding occurs at steps one, two, four, six and eight and nowhere else."

    Design: Corner/validations/reserve_needs_one_elapsed_day_and_a_zero_growth_period_pays_nothing
    """
    ctx = build_closed_deal()
    tranche = project_tranche(
        ctx["affiliation_id"],
        measurement_start=MEASUREMENT_START,
        measurement_end=MEASUREMENT_END,
    )
    reserve_payload = {
        "reported_net_collections_cents": 200_000,
        "reported_expenses_cents": 100_000,
    }

    validate_error(
        api_client.reserve_tranche(tranche["id"], reserve_payload, FINANCE),
        ApiErrorId.ERR_MEASUREMENT_PERIOD_NOT_STARTED.value,
        422,
    )
    assert read_earnout_tranche(tranche["id"])["status"] == "PROJECTED"

    set_clock("2026-09-02T00:00:00Z")
    reserved = validate_success(
        api_client.reserve_tranche(tranche["id"], reserve_payload, FINANCE)
    )
    assert reserved["annualized_net_collections_cents"] == 73_000_000
    assert reserved["annualized_expenses_cents"] == 36_500_000
    assert reserved["management_fee_cents"] == 5_110_000
    assert reserved["adjusted_ebitda_cents"] == 31_390_000
    assert reserved["growth_bps"] == -6512
    assert reserved["multiple_bps"] == 0
    assert reserved["reserved_cents"] == 0

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert_earnout_pool_ledger(affiliation)
    assert affiliation["earnout_unallocated_cents"] == 90_000_000
    assert affiliation["earnout_reserved_cents"] == 0


def test_the_version_guard_answers_before_the_posture_gate():
    """PRD §2.9: "A request to `POST /dso/migration-batches` must carry `expected_practice_version` holding the client's last observed `version` of the target `Practice`. If that value does not equal the practice's current `version`, the create is rejected with `ERR_STALE_PRACTICE_VERSION` and HTTP 412."
    PRD §2.11: "8. `expected_practice_version` matches the practice's current `version`, on batch creation — `ERR_STALE_PRACTICE_VERSION` (412)."

    Note: PRD §2.11 position 17 enumerates the six operations guarded by
    `ERR_PRACTICE_NOT_AFFILIATED` and batch staging is not among them, so the
    stale-version rejection is the only gate this test may assert.

    Design: Corner/validations/stale_practice_version_preempts_the_not_affiliated_gate
    """
    set_clock(CLOSE_DAY)
    affiliation = create_affiliation()
    vendor = create_conversion_vendor()
    practice = create_practice(affiliation["id"], vendor["id"])
    advance_to_diligence(affiliation["id"])

    practice_v = practice_version(practice["id"])
    affiliation_v = affiliation_version(affiliation["id"])
    assert practice_v == 1
    assert affiliation_v == 3

    validate_error(
        api_client.create_migration_batch(
            create_migration_batch_payload(
                practice["id"], affiliation_v, batch_label="BATCH-01", records_total=5000
            ),
            LEAD,
        ),
        ApiErrorId.ERR_STALE_PRACTICE_VERSION.value,
        412,
    )

    unchanged = read_practice(practice["id"])
    assert unchanged["version"] == practice_v
    assert unchanged["integration_posture"] == "PRE_CLOSE"

    _, meta = validate_paginated(
        api_client.list_migration_batches(LEAD, {"practice_id": practice["id"]})
    )
    assert meta["total_count"] == 0


def test_an_approved_preference_exception_cannot_be_reversed():
    """PRD §3.7: "The decision requires the exception to be `REQUESTED` and the underlying employment to still be `ACTIVE`, and it supplies a `decision` of `APPROVE` or `DENY` plus an optional `decision_note`."
    PRD §3.7: "On `APPROVE` the exception moves `REQUESTED → APPROVED` and `incremental_cost_cents` is stamped as the difference between `preferred_unit_cents` and `formulary_unit_cents` multiplied by `annual_qty`, which makes the exception eligible for consolidation leakage at the next finalization."

    Design: Corner/validations/decided_supply_exception_cannot_be_decided_again
    """
    ctx = build_closed_deal()
    approved, director_id = build_approved_supply_exception(ctx)

    validate_error(
        api_client.decide_supply_preference_exception(
            approved["id"],
            {"decision": "DENY", "decision_note": "reversal attempt"},
            make_clinical_director_headers(director_id),
        ),
        ApiErrorId.ERR_INVALID_WORKFLOW_STATE.value,
        409,
    )

    unchanged = read_supply_preference_exception(approved["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["incremental_cost_cents"] == 212_160
    assert unchanged["decided_by_doctor_id"] == director_id

    _, meta = validate_paginated(
        api_client.list_employment_supply_preference_exceptions(
            ctx["employment_id"],
            make_clinical_director_headers(director_id),
            {"status": "APPROVED"},
        )
    )
    assert meta["total_count"] == 1


def test_a_live_dso_schedule_refuses_a_further_priced_procedure():
    """PRD §3.6: "**Pricing** the transition is done one procedure at a time while the contract is `LEGACY` or `PENDING_CREDENTIALING`."
    PRD §3.6: "The contract's `blended_impact_cents` is then the plain sum of the stored line figures, with no further rounding at the contract level."

    Design: Corner/validations/activated_contract_rejects_further_fee_schedule_items
    """
    ctx = build_closed_deal()
    contract, enrollment = build_contract_ready_for_activation(
        ctx, lead_effective_date=ENROLLMENT_EFFECTIVE, submit_clock=SUBMIT_CLOCK
    )
    assert enrollment["lead_days"] == 90
    approve_enrollment(enrollment["id"])
    activated = validate_success(
        activate_fee_schedule(contract["id"], ENROLLMENT_EFFECTIVE)
    )
    assert activated["transition_state"] == "DSO_SCHEDULE_ACTIVE"

    validate_error(
        api_client.add_fee_schedule_item(
            contract["id"],
            {
                "procedure_code": "D2740",
                "legacy_allowed_cents": 108_000,
                "dso_allowed_cents": 99_503,
                "annual_volume": 130,
            },
            FINANCE,
        ),
        ApiErrorId.ERR_INVALID_CONTRACT_STATE.value,
        409,
    )

    frozen = read_payer_contract(contract["id"])
    assert_payer_contract(frozen)
    assert frozen["transition_state"] == "DSO_SCHEDULE_ACTIVE"
    assert frozen["fee_schedule_item_count"] == 1
    assert frozen["blended_impact_cents"] == -39_195

    rows, meta = validate_paginated(
        api_client.list_fee_schedule_items(contract["id"], FINANCE)
    )
    assert meta["total_count"] == 1
    assert rows[0]["line_impact_cents"] == -39_195


def test_legal_review_will_not_open_on_an_empty_scope():
    """PRD §3.2: "Submitting the drafted scope for corporate-practice legal review moves the agreement `DRAFT → LEGAL_REVIEW` and increments `review_round`; a submission is refused with `ERR_SERVICE_SCOPE_EMPTY` when `line_item_count` is still zero."
    PRD §3.2: "The agreement opens in `DRAFT` with `review_round`, `scope_findings_count` and `line_item_count` all at zero and no `effective_date`."

    Design: Corner/validations/empty_service_scope_blocks_legal_review
    """
    ctx = build_deal_in_draft(clock_utc=CLOSE_DAY)
    advance_to_diligence(ctx["affiliation_id"])
    agreement = create_service_agreement(ctx["practice_id"])
    assert agreement["review_round"] == 0
    assert agreement["line_item_count"] == 0

    validate_error(
        api_client.submit_legal_review(agreement["id"], COUNSEL),
        ApiErrorId.ERR_SERVICE_SCOPE_EMPTY.value,
        422,
    )
    refused = read_service_agreement(agreement["id"])
    assert refused["status"] == "DRAFT"
    assert refused["review_round"] == 0

    line = validate_success(
        api_client.add_service_line_item(
            agreement["id"],
            {
                "service_code": "SVC-RCM-01",
                "service_domain": "BILLING",
                "monthly_fee_cents": 250_000,
            },
            COUNSEL,
        ),
        expected_status=201,
    )
    assert line["is_clinical"] is False

    submitted = validate_success(
        api_client.submit_legal_review(agreement["id"], COUNSEL)
    )
    assert submitted["status"] == "LEGAL_REVIEW"
    assert submitted["review_round"] == 1
    assert submitted["line_item_count"] == 1


def test_the_empty_fee_schedule_is_reported_before_the_unapproved_enrollment():
    """PRD §2.11: "Every request runs through one ordered gauntlet of checks. The first check whose condition is violated determines the response, no later check is evaluated, and **no state change whatsoever is written** when any check fires."
    PRD §3.6: "`fee_schedule_item_count` must be at least one, or the request is refused with `ERR_FEE_SCHEDULE_EMPTY`; the contract must have at least one enrollment and every one of them must be `APPROVED`, or it is refused with `ERR_ENROLLMENTS_NOT_APPROVED`; every enrollment of the contract must show `lead_days` of at least 90 whole days, where exactly 90 passes and 89 fails with `ERR_CREDENTIALING_LEAD_TIME_SHORT`; and finally the materiality rule of §2.5 is applied, with `erosion_override_ack` recorded from the request."

    Design: Corner/validations/empty_fee_schedule_is_reported_before_missing_enrollment_approvals
    """
    ctx = build_closed_deal()
    contract = create_payer_contract(ctx["practice_id"])
    enrollment = create_payer_enrollment(
        contract["id"], ctx["employment_id"], ENROLLMENT_EFFECTIVE
    )
    assert read_payer_contract(contract["id"])["transition_state"] == (
        "PENDING_CREDENTIALING"
    )

    validate_error(
        activate_fee_schedule(contract["id"], ENROLLMENT_EFFECTIVE),
        ApiErrorId.ERR_FEE_SCHEDULE_EMPTY.value,
        422,
    )

    add_fee_schedule_item(contract["id"])

    validate_error(
        activate_fee_schedule(contract["id"], ENROLLMENT_EFFECTIVE),
        ApiErrorId.ERR_ENROLLMENTS_NOT_APPROVED.value,
        422,
    )

    unchanged = read_payer_contract(contract["id"])
    assert unchanged["transition_state"] == "PENDING_CREDENTIALING"
    assert unchanged["enrollment_open_count"] == 1
    assert unchanged["fee_schedule_item_count"] == 1
    assert unchanged["blended_impact_cents"] == -39_195
    assert unchanged["dso_schedule_effective_date"] is None

    reread = read_payer_enrollment(enrollment["id"])
    assert reread["status"] == "NOT_STARTED"
    assert reread["lead_days"] is None


def test_the_uplift_ceiling_admits_a_package_landing_exactly_on_it():
    """PRD §3.4: "The uplift cap of §2.11 position 50 bounds the result after the calculation has run — the harmonized figure may not exceed the legacy package multiplied by 12,500 and divided by ten thousand, which is to say one hundred and twenty-five percent of the legacy package, and a result above that ceiling is refused with `ERR_COMP_HARMONIZATION_CAP_EXCEEDED` with nothing written."
    PRD §3.4: "Whichever variant ran, the result is then compared against `legacy_annual_comp_cents`: `harmonization_delta_cents` is `harmonized_annual_comp_cents` less `legacy_annual_comp_cents`, and `is_harmonized` becomes true."

    Design: Corner/validations/comp_harmonization_cap_is_inclusive_at_twenty_five_percent_uplift
    """
    ctx = build_closed_deal()
    assert ctx["employment"]["comp_model"] == "MONTHLY_MIN_GUARANTEE"
    assert ctx["employment"]["legacy_annual_comp_cents"] == 24_000_000

    validate_error(
        api_client.harmonize_compensation(
            ctx["employment_id"],
            {"monthly_collections_cents": monthly_collections_series(*[12_000_000] * 12)},
            FINANCE,
        ),
        ApiErrorId.ERR_COMP_HARMONIZATION_CAP_EXCEEDED.value,
        422,
    )
    refused = read_employment(ctx["employment_id"])
    assert refused["is_harmonized"] is False
    assert refused["harmonized_annual_comp_cents"] is None
    assert refused["harmonization_delta_cents"] is None

    harmonized = harmonize_compensation(
        ctx["employment_id"],
        monthly_collections_series(*([8_000_000] * 11 + [12_000_000])),
    )
    assert harmonized["harmonized_annual_comp_cents"] == 30_000_000
    assert harmonized["harmonization_delta_cents"] == 6_000_000
    assert harmonized["is_harmonized"] is True
    assert harmonized["comp_model"] == "MONTHLY_MIN_GUARANTEE"


def test_a_payout_larger_than_the_pool_is_refused_outright():
    """PRD §3.9: "A reservation's payout must not exceed the affiliation's current `earnout_unallocated_cents`; a settlement's payout must not exceed `earnout_unallocated_cents` plus the reservation the settlement is about to release, that is the tranche's own `reserved_cents`."
    PRD §2.8: "`earnout_unallocated_cents` must never be negative: any reservation or settlement that would drive it below zero is refused with `ERR_EARNOUT_POOL_EXCEEDED` and leaves all four figures exactly as they were."

    Design: Corner/validations/reserve_exceeding_the_unallocated_pool_is_rejected
    """
    ctx = build_closed_deal()
    tranche = project_tranche(
        ctx["affiliation_id"],
        measurement_start=MEASUREMENT_START,
        measurement_end=MEASUREMENT_END,
    )
    set_clock(RESERVE_CLOCK)

    validate_error(
        api_client.reserve_tranche(
            tranche["id"],
            {
                "reported_net_collections_cents": 250_000_000,
                "reported_expenses_cents": 100_000_000,
            },
            FINANCE,
        ),
        ApiErrorId.ERR_EARNOUT_POOL_EXCEEDED.value,
        422,
    )
    untouched = read_earnout_tranche(tranche["id"])
    assert untouched["status"] == "PROJECTED"
    assert untouched["reserved_cents"] == 0
    assert read_affiliation(ctx["affiliation_id"])["earnout_unallocated_cents"] == (
        90_000_000
    )

    reserved = validate_success(
        api_client.reserve_tranche(
            tranche["id"],
            {
                "reported_net_collections_cents": 210_000_000,
                "reported_expenses_cents": 151_000_000,
            },
            FINANCE,
        )
    )
    assert reserved["annualized_net_collections_cents"] == 423_480_663
    assert reserved["management_fee_cents"] == 23_291_436
    assert reserved["adjusted_ebitda_cents"] == 95_686_465
    assert reserved["growth_bps"] == 632
    assert reserved["multiple_bps"] == 25_000
    assert reserved["reserved_cents"] == 14_216_163

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert_earnout_pool_ledger(affiliation)
    assert affiliation["earnout_reserved_cents"] == 14_216_163
    assert affiliation["earnout_unallocated_cents"] == 75_783_837
