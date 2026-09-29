"""Role-authorization breadth: the four exclusive scopes that refuse each
other at the role gate, the one operation two roles genuinely share, and the
duty separation that binds a single tranche rather than a single user."""

from test_helpers import (
    COUNSEL,
    FINANCE,
    FINANCE_RESERVER_USER_ID,
    LEAD,
    ApiErrorId,
    api_client,
    assert_clinical_quality_review,
    assert_doctor_employment,
    assert_earnout_pool_ledger,
    assert_earnout_tranche,
    assert_migration_batch,
    assert_practice,
    assert_supply_preference_exception,
    build_clinical_director,
    build_closed_deal,
    create_clinical_quality_review,
    create_clinical_quality_review_payload,
    create_migration_batch_payload,
    create_supply_preference_exception,
    decide_supply_exception,
    make_dentist_headers,
    practice_version,
    project_tranche,
    read_affiliation,
    read_earnout_tranche,
    read_employment,
    read_practice,
    read_supply_preference_exception,
    reserve_tranche,
    separate_employment,
    set_clock,
    standardize_staffing,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOSE_DAY = "2026-09-01T00:00:00Z"
RESERVE_CLOCK = "2027-03-01T00:00:00Z"
SECOND_RESERVE_CLOCK = "2027-03-02T00:00:00Z"
FULL_YEAR = ("2026-09-01T00:00:00Z", "2027-09-01T00:00:00Z")
FIRST_HALF = ("2026-09-01T00:00:00Z", "2027-03-01T00:00:00Z")
SECOND_HALF = ("2027-03-01T00:00:00Z", "2027-09-01T00:00:00Z")


def test_transaction_counsel_cannot_drive_the_integration():
    """PRD §2.1: "The integration lead owns closing, conversion vendors, chart migration, credentialing enrollments, staffing standardization, vendor consolidation and employment offers."
    PRD §2.1: "A role value outside that set, or a recognized role that is not authorized for the endpoint being called, is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/deal_counsel_cannot_run_integration_lead_exclusive_operations
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)

    validate_error(
        standardize_staffing(ctx["practice_id"], 12000, COUNSEL),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    standardized = validate_success(standardize_staffing(ctx["practice_id"], 12000, LEAD))
    assert_practice(standardized)
    assert standardized["staffing_model_state"] == "STANDARDIZED"
    assert standardized["fte_hygiene_ratio_bps"] == 12000

    batch_payload = create_migration_batch_payload(
        ctx["practice_id"],
        practice_version(ctx["practice_id"]),
        batch_label="BATCH-01",
        records_total=5000,
    )
    validate_error(
        api_client.create_migration_batch(batch_payload, COUNSEL),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    batch = validate_success(
        api_client.create_migration_batch(batch_payload, LEAD), expected_status=201
    )
    assert_migration_batch(batch)
    assert batch["status"] == "STAGED"
    assert batch["records_pending"] == 5000

    rows, meta = validate_paginated(
        api_client.list_migration_batches(LEAD, {"practice_id": ctx["practice_id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == batch["id"]


def test_the_money_role_and_the_clinical_role_stay_on_their_own_side():
    """PRD §2.1: "The finance controller owns payer contracts, fee schedules, compensation harmonization and the earn-out tranche lifecycle."
    PRD §2.1: "The clinical director owns clinical quality determinations, formulary exception decisions and post-departure records custody."

    Design: Corner/rbac/finance_controller_and_clinical_director_cannot_cross_into_each_others_scope
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    director, director_headers = build_clinical_director()
    tranche = project_tranche(
        ctx["affiliation_id"],
        period_label="EO-Y1",
        measurement_start=FULL_YEAR[0],
        measurement_end=FULL_YEAR[1],
    )
    set_clock(RESERVE_CLOCK)

    review_payload = create_clinical_quality_review_payload(
        ctx["employment_id"],
        period_label="QR-2027-Q1",
        charts_sampled=40,
        charts_with_findings=0,
        treatment_plan_overrides=0,
    )
    validate_error(
        api_client.create_clinical_quality_review(review_payload, FINANCE),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.reserve_tranche(
            tranche["id"],
            {
                "reported_net_collections_cents": 210_000_000,
                "reported_expenses_cents": 151_000_000,
            },
            director_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    review = create_clinical_quality_review(
        ctx["employment_id"],
        director["id"],
        period_label="QR-2027-Q1",
        charts_sampled=40,
        charts_with_findings=0,
        treatment_plan_overrides=0,
    )
    assert_clinical_quality_review(review)
    assert review["score_bps"] == 10000
    assert review["status"] == "OPEN"

    reserved = reserve_tranche(tranche["id"], 210_000_000, 151_000_000)
    assert_earnout_tranche(reserved)
    assert reserved["status"] == "RESERVED"
    assert reserved["variant_applied"] == "PROVISIONAL"
    assert reserved["annualized_net_collections_cents"] == 423_480_663
    assert reserved["annualized_expenses_cents"] == 304_502_762
    assert reserved["management_fee_cents"] == 23_291_436
    assert reserved["adjusted_ebitda_cents"] == 95_686_465
    assert reserved["growth_bps"] == 632
    assert reserved["multiple_bps"] == 25000
    assert reserved["reserved_cents"] == 14_216_163
    assert reserved["reserved_by_user_id"] == FINANCE_RESERVER_USER_ID


def test_the_requesting_dentist_owns_the_request_but_not_the_decision():
    """PRD §3.7: "The exception opens in `REQUESTED` with `incremental_cost_cents` empty."
    PRD §3.7: "Only the clinical director may **decide** an exception, which is the corporate-practice boundary at work: a preference for a particular material is a clinical determination, and no non-clinical role may make it."

    Design: Corner/rbac/dentist_cannot_decide_the_preference_exception_they_raised
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    director, _ = build_clinical_director()

    requested = create_supply_preference_exception(
        ctx["employment_id"],
        ctx["doctor_id"],
        vendor_category="SUPPLY",
        item_code="CMP-2200",
        annual_qty=340,
        formulary_unit_cents=1275,
        preferred_unit_cents=1899,
        clinical_rationale="shade matching on anterior composites",
    )
    assert_supply_preference_exception(requested)
    assert requested["status"] == "REQUESTED"
    assert requested["incremental_cost_cents"] is None
    assert requested["decided_by_doctor_id"] is None

    validate_error(
        api_client.decide_supply_preference_exception(
            requested["id"], {"decision": "APPROVE"}, make_dentist_headers(ctx["doctor_id"])
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    untouched = read_supply_preference_exception(requested["id"])
    assert untouched["status"] == "REQUESTED"
    assert untouched["decided_by_doctor_id"] is None

    approved = decide_supply_exception(
        requested["id"], "APPROVE", director["id"], decision_note="clinically justified"
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_doctor_id"] == director["id"]
    assert approved["incremental_cost_cents"] == 212_160


def test_a_departing_doctor_may_run_their_own_separation():
    """PRD §3.4: "Either the integration lead or the departing dentist may perform it, it requires `employment_status` to be `ACTIVE`, and it supplies a `separation_reason` of `VOLUNTARY`, `TERMINATED_FOR_CAUSE` or `NON_RENEWAL`."
    PRD §3.4: "Hop one touches the employment row: `employment_status` moves `ACTIVE → SEPARATED`, `separation_date` is stamped from the logical clock, `separation_reason` is recorded from the request, `non_compete_end_date` is set to `separation_date` advanced by `non_compete_months` calendar months, `records_custody_state` moves `HELD_BY_PRACTICE → TRANSFER_PENDING`, `non_compete_enforcement_state` moves `NOT_APPLICABLE → PENDING`, and the practice's `active_doctor_count` decreases by one."

    Design: Corner/rbac/separation_is_a_shared_operation_for_lead_and_dentist
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    assert ctx["employment"]["non_compete_months"] == 24

    separated = separate_employment(
        ctx["employment_id"], "VOLUNTARY", make_dentist_headers(ctx["doctor_id"])
    )
    assert_doctor_employment(separated)
    assert separated["employment_status"] == "SEPARATED"
    assert separated["separation_reason"] == "VOLUNTARY"
    assert separated["separation_date"].startswith("2026-09-01T00:00:00")
    assert separated["records_custody_state"] == "TRANSFER_PENDING"
    assert separated["non_compete_enforcement_state"] == "PENDING"
    assert separated["non_compete_end_date"].startswith("2028-09-01T00:00:00")
    assert read_employment(ctx["employment_id"])["employment_status"] == "SEPARATED"

    practice = read_practice(ctx["practice_id"])
    assert practice["active_doctor_count"] == 0
    assert practice["integration_posture"] == "FROZEN"
    assert practice["clinical_coverage_gap"] is True


def test_one_controller_may_reserve_two_tranches_without_objection():
    """PRD §3.9: "It requires the tranche to be `RESERVED`, supplies `final_net_collections_cents` and `final_expenses_cents`, and enforces segregation of duties: the settling `X-User-ID` must differ from the `reserved_by_user_id` recorded at reservation, and an identical user is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "Growth below zero takes a multiple of 0 basis points, so a tranche that measures below its baseline earns nothing."

    Design: Corner/rbac/one_controller_may_reserve_two_different_tranches
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    assert ctx["affiliation"]["earnout_pool_cents"] == 90_000_000

    first = project_tranche(
        ctx["affiliation_id"],
        period_label="EO-Y1",
        measurement_start=FIRST_HALF[0],
        measurement_end=FIRST_HALF[1],
    )
    second = project_tranche(
        ctx["affiliation_id"],
        period_label="EO-Y2",
        measurement_start=SECOND_HALF[0],
        measurement_end=SECOND_HALF[1],
    )

    set_clock(RESERVE_CLOCK)
    reserved_first = reserve_tranche(first["id"], 200_000, 100_000)
    assert reserved_first["status"] == "RESERVED"
    assert reserved_first["reserved_by_user_id"] == FINANCE_RESERVER_USER_ID
    assert reserved_first["growth_bps"] < 0
    assert reserved_first["multiple_bps"] == 0
    assert reserved_first["reserved_cents"] == 0

    set_clock(SECOND_RESERVE_CLOCK)
    reserved_second = reserve_tranche(second["id"], 200_000, 100_000)
    assert reserved_second["status"] == "RESERVED"
    assert reserved_second["reserved_by_user_id"] == FINANCE_RESERVER_USER_ID
    assert reserved_second["annualized_net_collections_cents"] == 73_000_000
    assert reserved_second["annualized_expenses_cents"] == 36_500_000
    assert reserved_second["management_fee_cents"] == 5_110_000
    assert reserved_second["adjusted_ebitda_cents"] == 31_390_000
    assert reserved_second["growth_bps"] == -6512
    assert reserved_second["multiple_bps"] == 0
    assert reserved_second["reserved_cents"] == 0

    assert read_earnout_tranche(first["id"])["reserved_cents"] == 0
    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["earnout_unallocated_cents"] == 90_000_000
    assert affiliation["earnout_reserved_cents"] == 0
    assert affiliation["earnout_settled_cents"] == 0
    assert_earnout_pool_ledger(affiliation)
