"""Chart-migration depth: the quarantine/remediation revisit cycle, the
validation tolerance boundary, the 48-hour closed-interval buffer, the buffer's
precedence over vendor crew capacity, and the conserved chart-records ledger."""

import pytest

from test_helpers import (
    LEAD,
    ApiErrorId,
    accept_offer,
    add_practice_with_doctor,
    advance_to_diligence,
    api_client,
    assert_batch_record_ledger,
    assert_migration_batch,
    assert_practice,
    build_closed_deal,
    build_deal_in_draft,
    build_scheduled_batch,
    close_deal,
    make_agreement_effective_at,
    read_conversion_vendor,
    read_migration_batch,
    read_practice,
    reconcile_batch,
    remediate_batch,
    rollback_batch,
    schedule_cutover_payload,
    set_clock,
    sign_deal,
    stage_batch,
    validate_batch,
    validate_error,
)

WINDOW_1 = ("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")
WINDOW_2 = ("2026-10-04T00:00:00Z", "2026-10-05T00:00:00Z")
WINDOW_BEFORE = ("2026-09-28T00:00:00Z", "2026-09-29T00:00:00Z")
WINDOW_TOO_CLOSE = ("2026-10-06T23:59:59Z", "2026-10-07T12:00:00Z")
WINDOW_5 = ("2026-10-07T00:00:00Z", "2026-10-08T00:00:00Z")


@pytest.fixture
def quarantined_batch():
    """A closed deal whose only batch quarantined on its first round."""
    ctx = build_closed_deal()
    batch = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="CHART-WAVE-1", records_total=5000
    )
    set_clock(WINDOW_1[0])
    ctx["batch"] = validate_batch(batch["id"], 101)
    ctx["batch_id"] = batch["id"]
    return ctx


def test_quarantine_branch_holds_back_the_whole_batch(quarantined_batch):
    """PRD §3.5: "On the **quarantining** branch, the whole batch is held back rather than only the failing records: the batch moves `SCHEDULED → QUARANTINED`, `records_quarantined` is set to the full `records_total`, `records_validated` is set to zero, `records_pending` becomes zero, the practice's `charts_migrated_count` is left completely unchanged so no chart credit at all flows, the vendor's `active_window_count` still decreases by one, the practice's `quarantined_batch_count` increases by one and the recomputed posture carries the practice `STABILIZING → RESTRICTED`, and both versions increment by one."

    Design: Difficulty/non_linear_state_machine/migration_batch_quarantine_remediation_revisit_cycle
    """
    batch = quarantined_batch["batch"]
    assert_migration_batch(batch)
    assert batch["status"] == "QUARANTINED"
    assert batch["validation_error_rate_bps"] == 202
    assert batch["records_validated"] == 0
    assert batch["records_quarantined"] == 5000
    assert batch["records_pending"] == 0

    practice = read_practice(quarantined_batch["practice_id"])
    assert_practice(practice)
    assert practice["charts_migrated_count"] == 0
    assert practice["quarantined_batch_count"] == 1
    assert practice["integration_posture"] == "RESTRICTED"


def test_remediation_reuses_the_row_and_keeps_the_reserved_window(quarantined_batch):
    """PRD §3.5: "It requires `QUARANTINED` status, increments `remediation_round` by one, resets both `records_quarantined` and `records_validated` to zero and clears `validation_error_rate_bps`, decrements the practice's `quarantined_batch_count` by one and recomputes the posture — which carries the practice `RESTRICTED → STABILIZING` when that batch was the last blocker and at least one doctor remains active and the practice has not yet migrated all its expected charts — keeps the previously reserved cutover window in place, increases the vendor's `active_window_count` by one again, and increments both the batch's `version` and the practice's `version` by one."

    Design: Difficulty/non_linear_state_machine/migration_batch_quarantine_remediation_revisit_cycle
    """
    before = quarantined_batch["batch"]
    remediated = remediate_batch(
        quarantined_batch["batch_id"], remediation_note="re-extract accepted by vendor"
    )
    assert remediated["status"] == "SCHEDULED"
    assert remediated["remediation_round"] == 1
    assert remediated["records_validated"] == 0
    assert remediated["records_quarantined"] == 0
    assert remediated["records_pending"] == 5000
    assert remediated["validation_error_rate_bps"] is None
    assert remediated["cutover_start_at"] == before["cutover_start_at"]
    assert remediated["cutover_end_at"] == before["cutover_end_at"]
    assert remediated["version"] > before["version"]

    practice = read_practice(quarantined_batch["practice_id"])
    assert practice["quarantined_batch_count"] == 0
    assert practice["integration_posture"] == "STABILIZING"


def test_second_round_validates_and_the_batch_can_then_reconcile(quarantined_batch):
    """PRD §3.5: "On the **validating** branch, the batch moves `SCHEDULED → VALIDATED`, `records_quarantined` is set to the reported `quarantined_count`, `records_validated` is set to `records_total` less that count, `records_pending` becomes zero, the practice's `charts_migrated_count` increases by `records_validated`, the vendor's `active_window_count` decreases by one"
    PRD §3.5: "The batch moves `VALIDATED → RECONCILED`, its `version` increments by one, and the practice's `charts_migrated_count` keeps counting that batch's `records_validated`, since reconciled batches remain inside the practice-level roll-up."

    Design: Difficulty/non_linear_state_machine/migration_batch_quarantine_remediation_revisit_cycle
    """
    remediate_batch(quarantined_batch["batch_id"])
    validated = validate_batch(quarantined_batch["batch_id"], 100)
    assert validated["status"] == "VALIDATED"
    assert validated["validation_error_rate_bps"] == 200
    assert validated["records_validated"] == 4900
    assert validated["records_quarantined"] == 100
    assert validated["records_pending"] == 0
    assert_batch_record_ledger(validated)

    practice = read_practice(quarantined_batch["practice_id"])
    assert practice["charts_migrated_count"] == 4900

    reconciled = reconcile_batch(quarantined_batch["batch_id"])
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["remediation_round"] == 1
    assert reconciled["records_validated"] == 4900

    after = read_practice(quarantined_batch["practice_id"])
    assert after["charts_migrated_count"] == 4900


def test_error_rate_of_exactly_two_hundred_basis_points_validates():
    """PRD §3.5: "Tolerance is two percent, that is 200 basis points: a rate exactly equal to 200 validates, and 201 quarantines the entire batch."
    PRD §3.5: "The rate is then `validation_error_rate_bps`, computed as `quarantined_count` multiplied by ten thousand and divided by `records_total`, rounded half up to whole basis points."

    Design: Difficulty/boundary_precision_check/chart_validation_error_rate_at_exact_tolerance
    """
    ctx = build_closed_deal(practice={"charts_total_expected": 20_000})
    first = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="CHART-WAVE-1", records_total=5000
    )
    set_clock(WINDOW_1[0])
    validated = validate_batch(first["id"], 100)

    assert validated["validation_error_rate_bps"] == 200
    assert validated["status"] == "VALIDATED"
    assert validated["records_validated"] == 4900
    assert validated["records_quarantined"] == 100
    assert validated["records_pending"] == 0


def test_error_rate_one_basis_point_above_tolerance_quarantines_the_batch():
    """PRD §3.5: "Tolerance is two percent, that is 200 basis points: a rate exactly equal to 200 validates, and 201 quarantines the entire batch."
    PRD §2.6: "Clause three dominates clause four: a practice with even one quarantined batch is `RESTRICTED` even when every expected chart has migrated and nothing is pending in credentialing."

    Design: Difficulty/boundary_precision_check/chart_validation_error_rate_at_exact_tolerance
    """
    ctx = build_closed_deal(practice={"charts_total_expected": 20_000})
    first = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="CHART-WAVE-1", records_total=5000
    )
    second = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_2, batch_label="CHART-WAVE-2", records_total=5000
    )
    set_clock(WINDOW_2[0])
    validate_batch(first["id"], 100)
    quarantined = validate_batch(second["id"], 101)

    assert quarantined["validation_error_rate_bps"] == 202
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["records_validated"] == 0
    assert quarantined["records_quarantined"] == 5000

    practice = read_practice(ctx["practice_id"])
    assert practice["charts_migrated_count"] == 4900
    assert practice["quarantined_batch_count"] == 1
    assert practice["integration_posture"] == "RESTRICTED"

    vendor = read_conversion_vendor(ctx["vendor_id"])
    assert vendor["active_window_count"] == 0


def test_a_gap_of_exactly_forty_eight_hours_is_accepted_on_either_side():
    """PRD §3.5: "The requested window is acceptable when its `cutover_start_at` falls at or after the existing window's `cutover_end_at` advanced by 48 hours, or when its `cutover_end_at` advanced by 48 hours falls at or before the existing window's `cutover_start_at`."
    PRD §3.5: "A gap of exactly 48 hours is therefore allowed and a gap of 47 hours 59 minutes is not; a violation is refused with `ERR_CUTOVER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/cutover_window_closed_interval_forty_eight_hour_buffer
    """
    ctx = build_closed_deal()
    first = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="CHART-WAVE-1", records_total=1000
    )
    after = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_2, batch_label="CHART-WAVE-2", records_total=1000
    )
    before = build_scheduled_batch(
        ctx["practice_id"],
        *WINDOW_BEFORE,
        batch_label="CHART-WAVE-3",
        records_total=1000,
    )

    assert first["status"] == "SCHEDULED"
    assert after["status"] == "SCHEDULED"
    assert after["cutover_start_at"] == WINDOW_2[0]
    assert before["status"] == "SCHEDULED"
    assert before["cutover_end_at"] == WINDOW_BEFORE[1]

    vendor = read_conversion_vendor(ctx["vendor_id"])
    assert vendor["active_window_count"] == 3


def test_a_gap_one_second_short_of_the_buffer_is_refused():
    """PRD §3.5: "The **buffer rule** is a mandatory 48-hour separation between the requested closed window and the closed window of every other batch of the *same* practice whose status is `SCHEDULED` or `HELD`."
    PRD §3.5: "Staging is exclusive per practice: every earlier batch of the same practice still in `STAGED` status is moved `STAGED → SUPERSEDED`, processed in `created_at` ascending order, with each superseded batch's `version` incremented by one, and the practice's own `version` incremented by one."

    Design: Difficulty/resource_temporal_overlap/cutover_window_closed_interval_forty_eight_hour_buffer
    """
    ctx = build_closed_deal()
    build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="CHART-WAVE-1", records_total=1000
    )
    build_scheduled_batch(
        ctx["practice_id"], *WINDOW_2, batch_label="CHART-WAVE-2", records_total=1000
    )
    build_scheduled_batch(
        ctx["practice_id"],
        *WINDOW_BEFORE,
        batch_label="CHART-WAVE-3",
        records_total=1000,
    )

    crowded = stage_batch(
        ctx["practice_id"], batch_label="CHART-WAVE-4", records_total=1000
    )
    validate_error(
        api_client.schedule_cutover(
            crowded["id"], schedule_cutover_payload(*WINDOW_TOO_CLOSE), LEAD
        ),
        ApiErrorId.ERR_CUTOVER_WINDOW_CONFLICT.value,
    )
    unscheduled = read_migration_batch(crowded["id"])
    assert unscheduled["status"] == "STAGED"
    assert unscheduled["cutover_start_at"] is None
    assert unscheduled["cutover_end_at"] is None

    fifth = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_5, batch_label="CHART-WAVE-5", records_total=1000
    )
    assert fifth["status"] == "SCHEDULED"
    superseded = read_migration_batch(crowded["id"])
    assert superseded["status"] == "SUPERSEDED"

    vendor = read_conversion_vendor(ctx["vendor_id"])
    assert vendor["active_window_count"] == 4


@pytest.fixture
def two_practices_one_crew():
    """One vendor with a single crew serving two closed, affiliated practices."""
    ctx = build_deal_in_draft(
        clock_utc="2026-09-01T00:00:00Z", vendor={"max_concurrent_windows": 1}
    )
    add_practice_with_doctor(
        ctx,
        practice={"name": "Oak Park Dental", "charts_total_expected": 4000},
        doctor={
            "full_name": "Beto Alvarez",
            "npi": "1710000002",
            "license_number": "IL-DDS-5521",
        },
        employment={
            "base_salary_monthly_cents": 1_700_000,
            "collections_pct_bps": 2800,
            "comp_model": "ANNUAL_TRUE_UP",
            "legacy_annual_comp_cents": 23_000_000,
            "non_compete_months": 18,
            "non_compete_radius_miles": 8,
        },
    )
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])
    make_agreement_effective_at(ctx["practice_id"])
    make_agreement_effective_at(
        ctx["second_practice_id"],
        line_items=[{"service_code": "SVC-RCM-02", "monthly_fee_cents": 210_000}],
        fee_model="FIXED_MONTHLY",
        mgmt_fee_bps=1500,
    )
    accept_offer(ctx["employment_id"], ctx["doctor_id"])
    accept_offer(ctx["second_employment_id"], ctx["second_doctor_id"])
    close_deal(ctx["affiliation_id"])
    return ctx


def test_vendor_capacity_refuses_an_intersecting_window_at_another_practice(
    two_practices_one_crew
):
    """PRD §3.5: "The **vendor capacity rule** looks wider, across every practice the vendor serves: the number of batches in status `SCHEDULED` or `HELD` on the same conversion vendor whose closed window intersects the requested closed window must be strictly less than that vendor's `max_concurrent_windows`, and a request that would meet or exceed the crew count is refused with `ERR_VENDOR_WINDOW_CAPACITY`."

    Design: Difficulty/priority_pair_validation_conflict/cutover_window_conflict_beats_vendor_window_capacity
    """
    ctx = two_practices_one_crew
    build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="ELM-WAVE-1", records_total=5000
    )
    oak = stage_batch(
        ctx["second_practice_id"], batch_label="OAK-WAVE-1", records_total=4000
    )
    validate_error(
        api_client.schedule_cutover(
            oak["id"],
            schedule_cutover_payload(
                "2026-10-01T12:00:00Z", "2026-10-02T12:00:00Z"
            ),
            LEAD,
        ),
        ApiErrorId.ERR_VENDOR_WINDOW_CAPACITY.value,
    )
    unscheduled = read_migration_batch(oak["id"])
    assert unscheduled["status"] == "STAGED"
    assert unscheduled["cutover_start_at"] is None

    vendor = read_conversion_vendor(ctx["vendor_id"])
    assert vendor["active_window_count"] == 1


def test_same_practice_conflict_is_reported_before_vendor_capacity(
    two_practices_one_crew
):
    """PRD §2.11: "Cutover windows of the same practice respect the mandatory buffer — `ERR_CUTOVER_WINDOW_CONFLICT` (409). Ordered above the vendor-capacity check at position 37."
    PRD §3.5: "the requested window must respect the practice-level buffer; and only then is the vendor's aggregate capacity examined."

    Design: Difficulty/priority_pair_validation_conflict/cutover_window_conflict_beats_vendor_window_capacity
    """
    ctx = two_practices_one_crew
    first = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="ELM-WAVE-1", records_total=5000
    )
    second = stage_batch(
        ctx["practice_id"], batch_label="ELM-WAVE-2", records_total=5000
    )
    validate_error(
        api_client.schedule_cutover(
            second["id"],
            schedule_cutover_payload(
                "2026-10-01T12:00:00Z", "2026-10-02T12:00:00Z"
            ),
            LEAD,
        ),
        ApiErrorId.ERR_CUTOVER_WINDOW_CONFLICT.value,
    )
    unscheduled = read_migration_batch(second["id"])
    assert unscheduled["status"] == "STAGED"
    assert unscheduled["cutover_start_at"] is None
    assert unscheduled["cutover_end_at"] is None

    untouched = read_migration_batch(first["id"])
    assert untouched["status"] == "SCHEDULED"
    assert untouched["cutover_start_at"] == WINDOW_1[0]

    vendor = read_conversion_vendor(ctx["vendor_id"])
    assert vendor["active_window_count"] == 1


@pytest.fixture
def two_validated_batches():
    """One practice whose two batches together migrate every expected chart."""
    ctx = build_closed_deal()
    first = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_1, batch_label="CHART-WAVE-1", records_total=4900
    )
    second = build_scheduled_batch(
        ctx["practice_id"], *WINDOW_2, batch_label="CHART-WAVE-2", records_total=100
    )
    set_clock(WINDOW_1[0])
    ctx["first_batch"] = validate_batch(first["id"], 0)
    set_clock(WINDOW_2[0])
    ctx["second_batch"] = validate_batch(second["id"], 0)
    return ctx


def test_two_validations_carry_the_practice_to_its_chart_target(two_validated_batches):
    """PRD §2.8: "The practice-level invariant is that `charts_migrated_count` equals the sum of `records_validated` over that practice's batches whose status is `VALIDATED` or `RECONCILED`."
    PRD §3.5: "the practice's posture is recomputed — which can carry it `STABILIZING → INTEGRATED` once `charts_migrated_count` reaches `charts_total_expected` and no other blocker remains"

    Design: Difficulty/compensating_invariant/chart_records_conserved_across_validation_rollback
    """
    assert two_validated_batches["first_batch"]["records_validated"] == 4900
    assert two_validated_batches["first_batch"]["validation_error_rate_bps"] == 0
    assert two_validated_batches["second_batch"]["records_validated"] == 100

    practice = read_practice(two_validated_batches["practice_id"])
    assert_practice(practice)
    assert practice["charts_migrated_count"] == 5000
    assert practice["integration_posture"] == "INTEGRATED"


def test_rollback_restores_the_chart_count_even_after_a_later_validation(
    two_validated_batches
):
    """PRD §3.5: "The practice's `charts_migrated_count` is decreased by exactly that batch's `records_validated`, then `records_quarantined` is set to `records_total` and `records_validated` to zero, the batch moves `VALIDATED → QUARANTINED`, the practice's `quarantined_batch_count` increases by one, the posture is recomputed, and both versions increment by one."
    PRD §3.5: "Both invariants of the chart records ledger in §2.8 must hold again afterwards, and the practice's chart count must equal its exact pre-validation value even when other batches validated in between."

    Design: Difficulty/compensating_invariant/chart_records_conserved_across_validation_rollback
    """
    ctx = two_validated_batches
    rolled_back = rollback_batch(
        ctx["first_batch"]["id"], "source extract missed the perio chart annexes"
    )
    assert rolled_back["status"] == "QUARANTINED"
    assert rolled_back["records_validated"] == 0
    assert rolled_back["records_quarantined"] == 4900
    assert rolled_back["records_pending"] == 0
    assert_batch_record_ledger(rolled_back)

    practice = read_practice(ctx["practice_id"])
    assert practice["charts_migrated_count"] == 100
    assert practice["quarantined_batch_count"] == 1
    assert practice["integration_posture"] == "RESTRICTED"
    assert_practice(practice)

    untouched = read_migration_batch(ctx["second_batch"]["id"])
    assert untouched["status"] == "VALIDATED"
    assert untouched["records_validated"] == 100
    assert_batch_record_ledger(untouched)
