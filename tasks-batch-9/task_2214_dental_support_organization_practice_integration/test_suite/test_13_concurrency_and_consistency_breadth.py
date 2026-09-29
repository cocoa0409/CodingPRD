"""Concurrency and consistency breadth: the two optimistic-concurrency guards
that reject a view the writer has already invalidated, the derived rollup that
is recomputed rather than latched, and the two responses that already carry the
recomputed state a follow-up read confirms."""

from test_helpers import (
    FINANCE,
    LEAD,
    ApiErrorId,
    affiliation_version,
    api_client,
    assert_batch_record_ledger,
    assert_credentialing_rollup,
    assert_doctor_employment,
    assert_earnout_tranche,
    assert_migration_batch,
    assert_practice,
    build_closed_deal,
    build_scheduled_batch,
    create_earnout_tranche_payload,
    create_migration_batch_payload,
    create_payer_contract,
    create_payer_enrollment,
    approve_enrollment,
    harmonize_compensation,
    monthly_collections_series,
    practice_version,
    project_tranche,
    read_conversion_vendor,
    read_employment,
    read_migration_batch,
    read_payer_enrollment,
    read_practice,
    set_clock,
    stage_batch,
    submit_enrollment,
    validate_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOSE_DAY = "2026-09-01T00:00:00Z"
CUTOVER_START = "2026-09-05T00:00:00Z"
CUTOVER_END = "2026-09-06T00:00:00Z"
INSIDE_WINDOW = "2026-09-05T12:00:00Z"
SUBMIT_CLOCK = "2026-11-15T00:00:00Z"
ENROLLMENT_EFFECTIVE = "2027-02-13T00:00:00Z"
FIRST_YEAR = ("2026-09-01T00:00:00Z", "2027-09-01T00:00:00Z")
SECOND_YEAR = ("2027-09-01T00:00:00Z", "2028-09-01T00:00:00Z")


def test_a_stale_affiliation_view_cannot_project_a_second_tranche():
    """PRD §2.9: "If that value does not equal the affiliation's current `version`, the create is rejected with `ERR_STALE_AFFILIATION_VERSION` and HTTP 412."
    PRD §3.9: "A new tranche opens in `PROJECTED` with no `variant_applied`, with `reserved_cents`, `awarded_cents` and `clawed_back_cents` all at zero, with every reported, annualized, final and derived figure still empty, and with neither `reserved_by_user_id` nor `settled_by_user_id` recorded; it increments the affiliation's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_affiliation_version_rejects_a_second_tranche_projection
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    first_version = affiliation_version(ctx["affiliation_id"])
    first = project_tranche(
        ctx["affiliation_id"],
        period_label="EO-Y1",
        measurement_start=FIRST_YEAR[0],
        measurement_end=FIRST_YEAR[1],
    )
    assert_earnout_tranche(first)
    assert first["status"] == "PROJECTED"

    stale_payload = create_earnout_tranche_payload(
        ctx["affiliation_id"],
        first_version,
        period_label="EO-Y2",
        measurement_start=SECOND_YEAR[0],
        measurement_end=SECOND_YEAR[1],
    )
    validate_error(
        api_client.create_earnout_tranche(stale_payload, FINANCE),
        ApiErrorId.ERR_STALE_AFFILIATION_VERSION.value,
        412,
    )

    second_version = affiliation_version(ctx["affiliation_id"])
    assert second_version == first_version + 1

    fresh_payload = dict(stale_payload, expected_affiliation_version=second_version)
    second = validate_success(
        api_client.create_earnout_tranche(fresh_payload, FINANCE), expected_status=201
    )
    assert second["status"] == "PROJECTED"

    rows, meta = validate_paginated(
        api_client.list_earnout_tranches(
            FINANCE, {"affiliation_id": ctx["affiliation_id"]}
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]


def test_a_stale_practice_view_cannot_supersede_a_staged_batch():
    """PRD §2.9: "If that value does not equal the practice's current `version`, the create is rejected with `ERR_STALE_PRACTICE_VERSION` and HTTP 412."
    PRD §3.5: "Staging is exclusive per practice: every earlier batch of the same practice still in `STAGED` status is moved `STAGED → SUPERSEDED`, processed in `created_at` ascending order, with each superseded batch's `version` incremented by one, and the practice's own `version` incremented by one."

    Design: Corner/cross_cutting_complexity_layers/stale_practice_version_rejects_a_superseding_batch
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    first = stage_batch(ctx["practice_id"], batch_label="BATCH-01", records_total=5000)
    assert first["status"] == "STAGED"

    version_before_supersede = practice_version(ctx["practice_id"])
    second = stage_batch(ctx["practice_id"], batch_label="BATCH-02", records_total=5000)
    assert_migration_batch(second)
    assert second["status"] == "STAGED"
    assert read_migration_batch(first["id"])["status"] == "SUPERSEDED"

    version_after_supersede = practice_version(ctx["practice_id"])
    assert version_after_supersede == version_before_supersede + 1

    stale_payload = create_migration_batch_payload(
        ctx["practice_id"],
        version_before_supersede,
        batch_label="BATCH-03",
        records_total=5000,
    )
    validate_error(
        api_client.create_migration_batch(stale_payload, LEAD),
        ApiErrorId.ERR_STALE_PRACTICE_VERSION.value,
        412,
    )
    assert read_migration_batch(second["id"])["status"] == "STAGED"

    fresh_payload = dict(
        stale_payload, expected_practice_version=version_after_supersede
    )
    third = validate_success(
        api_client.create_migration_batch(fresh_payload, LEAD), expected_status=201
    )
    assert third["status"] == "STAGED"
    assert read_migration_batch(second["id"])["status"] == "SUPERSEDED"

    rows, meta = validate_paginated(
        api_client.list_migration_batches(
            LEAD, {"practice_id": ctx["practice_id"], "status": "STAGED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == third["id"]


def test_the_credentialing_rollup_is_recomputed_after_every_enrollment_write():
    """PRD §3.4: "It is recomputed from the enrollment rows referencing the employment whenever any of their statuses changes, including during the close cascade that creates them, and it never reads either of the other two dimensions."
    PRD §3.6: "A new enrollment opens in `NOT_STARTED` with `submission_round` at zero, no `lead_days`, no `submitted_at`, no `decided_at` and no `denial_reason`; it increments its contract's `enrollment_open_count` and `version`, and moves a `LEGACY` contract to `PENDING_CREDENTIALING`."
    PRD §3.6: "Submission stamps `submitted_at` from the logical clock, increments `submission_round` by one, computes `lead_days`, increments the practice's `pending_credentialing_count` by one, recomputes the employment's credentialing dimension and the practice's posture, and increments both the enrollment's `version` and the practice's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/credentialing_rollup_reconciles_after_every_enrollment_write
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    first_contract = create_payer_contract(
        ctx["practice_id"], payer_name="Statewide Dental Plan"
    )
    second_contract = create_payer_contract(
        ctx["practice_id"], payer_name="Prairie Dental Benefits"
    )

    first_enrollment = create_payer_enrollment(
        first_contract["id"], ctx["employment_id"], ENROLLMENT_EFFECTIVE
    )
    assert first_enrollment["status"] == "NOT_STARTED"
    employment = read_employment(ctx["employment_id"])
    assert employment["credentialing_status"] == "PENDING"
    assert_credentialing_rollup(employment, ["NOT_STARTED"])
    assert read_practice(ctx["practice_id"])["pending_credentialing_count"] == 0

    set_clock(SUBMIT_CLOCK)
    submitted = submit_enrollment(first_enrollment["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_round"] == 1
    assert submitted["submitted_at"].startswith("2026-11-15T00:00:00")
    assert submitted["lead_days"] == 90
    assert read_employment(ctx["employment_id"])["credentialing_status"] == "SUBMITTED"
    assert read_practice(ctx["practice_id"])["pending_credentialing_count"] == 1

    approved = approve_enrollment(first_enrollment["id"])
    assert approved["status"] == "APPROVED"
    assert read_employment(ctx["employment_id"])["credentialing_status"] == "APPROVED"
    assert read_practice(ctx["practice_id"])["pending_credentialing_count"] == 0

    second_enrollment = create_payer_enrollment(
        second_contract["id"], ctx["employment_id"], ENROLLMENT_EFFECTIVE
    )
    assert second_enrollment["status"] == "NOT_STARTED"
    reread = read_employment(ctx["employment_id"])
    assert reread["credentialing_status"] == "PENDING"
    assert_credentialing_rollup(reread, ["APPROVED", "NOT_STARTED"])
    assert read_practice(ctx["practice_id"])["pending_credentialing_count"] == 0
    assert read_payer_enrollment(second_enrollment["id"])["status"] == "NOT_STARTED"


def test_the_validate_response_already_shows_the_recomputed_chart_state():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.5: "On the **validating** branch, the batch moves `SCHEDULED → VALIDATED`, `records_quarantined` is set to the reported `quarantined_count`, `records_validated` is set to `records_total` less that count, `records_pending` becomes zero, the practice's `charts_migrated_count` increases by `records_validated`, the vendor's `active_window_count` decreases by one, the practice's posture is recomputed — which can carry it `STABILIZING → INTEGRATED` once `charts_migrated_count` reaches `charts_total_expected` and no other blocker remains — and both the batch's `version` and the practice's `version` increment by one."

    Design: Corner/consistency_model/validation_response_already_carries_the_recomputed_chart_state
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    batch = build_scheduled_batch(
        ctx["practice_id"],
        CUTOVER_START,
        CUTOVER_END,
        batch_label="BATCH-01",
        records_total=5000,
    )
    set_clock(INSIDE_WINDOW)

    validated = validate_batch(batch["id"], 100)
    assert_migration_batch(validated)
    assert validated["validation_error_rate_bps"] == 200
    assert validated["status"] == "VALIDATED"
    assert validated["records_validated"] == 4900
    assert validated["records_quarantined"] == 100
    assert validated["records_pending"] == 0
    assert_batch_record_ledger(validated)

    practice = read_practice(ctx["practice_id"])
    assert_practice(practice)
    assert practice["charts_migrated_count"] == 4900
    assert practice["integration_posture"] == "STABILIZING"
    assert read_conversion_vendor(ctx["vendor_id"])["active_window_count"] == 0


def test_the_harmonize_response_already_carries_the_computed_pair():
    """PRD §3.4: "For each of the twelve months in turn, the doctor's percentage share for that month is the month's collections multiplied by `collections_pct_bps` and divided by ten thousand, rounded half up to whole cents; that month's pay is the greater of `base_salary_monthly_cents` and that rounded share; and `harmonized_annual_comp_cents` is the sum of the twelve monthly pay figures."
    PRD §3.4: "Whichever variant ran, the result is then compared against `legacy_annual_comp_cents`: `harmonization_delta_cents` is `harmonized_annual_comp_cents` less `legacy_annual_comp_cents`, and `is_harmonized` becomes true."

    Design: Corner/consistency_model/harmonization_response_carries_the_computed_pair_without_a_second_read
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    assert ctx["employment"]["comp_model"] == "MONTHLY_MIN_GUARANTEE"
    assert ctx["employment"]["base_salary_monthly_cents"] == 1_800_000
    assert ctx["employment"]["collections_pct_bps"] == 3000
    assert ctx["employment"]["legacy_annual_comp_cents"] == 24_000_000
    assert ctx["employment"]["harmonized_annual_comp_cents"] is None
    assert ctx["employment"]["is_harmonized"] is False

    harmonized = harmonize_compensation(
        ctx["employment_id"],
        monthly_collections_series(
            5_000_000,
            5_000_000,
            5_000_000,
            5_000_000,
            5_000_000,
            5_000_000,
            7_500_000,
            7_500_000,
            7_500_000,
            7_500_000,
            7_500_000,
            7_500_000,
        ),
    )
    assert_doctor_employment(harmonized)
    assert harmonized["harmonized_annual_comp_cents"] == 24_300_000
    assert harmonized["harmonization_delta_cents"] == 300_000
    assert harmonized["is_harmonized"] is True

    reread = read_employment(ctx["employment_id"])
    assert reread["harmonized_annual_comp_cents"] == 24_300_000
    assert reread["harmonization_delta_cents"] == 300_000
    assert reread["comp_model"] == "MONTHLY_MIN_GUARANTEE"
    assert reread["legacy_annual_comp_cents"] == 24_000_000
