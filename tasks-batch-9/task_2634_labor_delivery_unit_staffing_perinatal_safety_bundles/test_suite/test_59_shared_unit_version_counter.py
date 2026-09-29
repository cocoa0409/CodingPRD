"""One unit counter, two unrelated endpoints, four consecutive revisions.

The unit is the only parent in this domain that guards two different writes,
and they are as far apart as two writes get: a coordinator freezing a
bed-minute projection and a safety officer minting a reporting snapshot. Both
echo the same field, so one counter serialises them, and this module walks a
single unit through four values of it — read, bump, refuse, accept, refuse
again, accept again. The second refusal is the sharper one: the version it
carries was perfectly current one call earlier, and it went stale because the
caller's own successful hold advanced it. Both refusals are also proved to have
written nothing, which rules out an implementation that mutates first and
compares afterwards.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_drill,
    assert_induction_booking,
    assert_instant_equals,
    assert_obstetric_unit,
    assert_snapshot,
    bootstrap_unit,
    get_success_data,
    set_clock,
    setup_validated_drill,
)

CLOCK_BOOTSTRAP = "2026-08-01T05:45:00Z"
CLOCK_DRILL_DUE = "2026-08-01T05:50:00Z"
CLOCK_DOCUMENTED = "2026-08-01T06:00:00Z"
DRILL_SCHEDULED_FOR = "2026-08-01T05:50:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:52:00Z"
SIMULATED_INCISION_AT = "2026-08-01T05:55:00Z"
MEASURED_MINUTES = 3
DRILL_PASS_CEILING = 30
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
UNIT_NAME = "Thornapple Landing Womens Hospital LDR"
INDUCTION_START = "2026-08-02T08:00:00Z"
INDUCTION_DAY = "2026-08-02"
EXPECTED_LABOR_MINUTES = 720
OPEN_BUFFER_MINUTES = 45
FROZEN_PROJECTION = 765
HOLD_EXPIRES_AT = "2026-08-01T08:00:00Z"
ADJUSTED_BUDGET = 2400
PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-07-02T00:00:00Z"

THORNAPPLE_STAFF = {
    "charge": {
        "full_name": "Perpetua Wrangham RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Isolde Vantongeren MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "ob": {
        "full_name": "Cormac Halvorsen MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Ottoline Skarsgaard RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_unit_walked_through_four_revisions():
    """A unit with no encounters at all, lifted off NOT_READY so a hold is legal.

    A validated drill with no `OR_STANDBY` entry behind it leaves readiness at
    `DEGRADED`, which the posture derivation does not freeze; with a zero
    deficit and two available labor beds the unit sits `OPEN` for the whole run,
    so every rung above the revision guard on both endpoints stays unarmed.
    """
    world = bootstrap_unit(
        clock=CLOCK_BOOTSTRAP,
        ldr_beds=6,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=THORNAPPLE_STAFF,
        unit_overrides={"unit_name": UNIT_NAME},
    )
    set_clock(CLOCK_DRILL_DUE)
    drill = setup_validated_drill(
        world,
        scheduled_for_utc=DRILL_SCHEDULED_FOR,
        decision_at=SIMULATED_DECISION_AT,
        incision_at=SIMULATED_INCISION_AT,
        documented_key="anesthesia",
        validator_key="officer",
        participant_keys=["ob", "anesthesia"],
        document_clock=CLOCK_DOCUMENTED,
    )
    unit_after_the_drill = world.reload_unit()
    booking = get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": "PRC-THRN-2101",
                "gestational_age_weeks": 41,
                "indication_code": "POST_DATES_41W",
                "requested_start_utc": INDUCTION_START,
                "expected_labor_minutes": EXPECTED_LABOR_MINUTES,
            },
            world.access_headers,
        )
    )
    unit_as_the_coordinator_read_it = get_success_data(
        api_client.get_unit(world.unit_id, world.access_headers)
    )
    stale_version = unit_as_the_coordinator_read_it["version"]
    budget_adjustment = api_client.patch_unit(
        world.unit_id,
        {"max_daily_induction_bed_minutes": ADJUSTED_BUDGET},
        world.officer_headers,
    )
    fresh_version = get_success_data(budget_adjustment)["version"]
    stale_hold = api_client.hold_capacity(
        booking["id"],
        {"bed_id": world.bed_id("LDR-01"), "expected_unit_version": stale_version},
        world.access_headers,
    )
    booking_after_the_refusal = get_success_data(
        api_client.get_booking(booking["id"], world.access_headers)
    )
    unit_after_the_refusal = world.reload_unit()
    bed_after_the_refusal = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    accepted_hold = api_client.hold_capacity(
        booking["id"],
        {"bed_id": world.bed_id("LDR-01"), "expected_unit_version": fresh_version},
        world.access_headers,
    )
    unit_after_the_hold = world.reload_unit()
    version_after_the_hold = unit_after_the_hold["version"]
    stale_snapshot = api_client.create_snapshot(
        world.unit_id,
        {
            "period_start_utc": PERIOD_START,
            "period_end_utc": PERIOD_END,
            "expected_unit_version": fresh_version,
        },
        world.officer_headers,
    )
    snapshots_after_the_refusal = api_client.list_unit_snapshots(
        world.unit_id, world.officer_headers, params={"limit": 10, "offset": 0}
    )
    accepted_snapshot = api_client.create_snapshot(
        world.unit_id,
        {
            "period_start_utc": PERIOD_START,
            "period_end_utc": PERIOD_END,
            "expected_unit_version": version_after_the_hold,
        },
        world.officer_headers,
    )
    return {
        "world": world,
        "drill": drill,
        "unit_after_the_drill": unit_after_the_drill,
        "booking": booking,
        "stale_version": stale_version,
        "budget_adjustment": budget_adjustment,
        "fresh_version": fresh_version,
        "stale_hold": stale_hold,
        "booking_after_the_refusal": booking_after_the_refusal,
        "unit_after_the_refusal": unit_after_the_refusal,
        "bed_after_the_refusal": bed_after_the_refusal,
        "accepted_hold": accepted_hold,
        "unit_after_the_hold": unit_after_the_hold,
        "version_after_the_hold": version_after_the_hold,
        "stale_snapshot": stale_snapshot,
        "snapshots_after_the_refusal": snapshots_after_the_refusal,
        "accepted_snapshot": accepted_snapshot,
        "bed_after_the_hold": get_success_data(
            api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
        ),
    }


def test_the_validated_drill_leaves_the_unit_open_and_unfrozen(
    one_unit_walked_through_four_revisions,
):
    """"The state is then decided by the first matching branch: `NOT_READY` when the current
    drill is null, or when the mean is non-null and strictly greater than 45.00; otherwise
    `DEGRADED` when the standby test is not satisfied, or when the mean is non-null and
    strictly greater than 30.00; otherwise `READY`." Also: "After the posture is settled, and
    only then, `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75
    otherwise."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    drill = setup["drill"]
    assert_drill(drill)
    assert drill["status"] == "VALIDATED"
    assert drill["measured_d2i_minutes"] == MEASURED_MINUTES
    assert MEASURED_MINUTES <= DRILL_PASS_CEILING
    unit = setup["unit_after_the_drill"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == OPEN_BUFFER_MINUTES


def test_one_budget_adjustment_advances_the_counter_by_exactly_one(
    one_unit_walked_through_four_revisions,
):
    """"`version` is an integer that starts at 1 when the record is created and increments by
    1 on each mutation of that record; because this system cascades aggressively, a single
    request routinely increments the `version` of a dozen records, and every such increment is
    called out in the workflow descriptions in section 3." Also: "Only
    `max_daily_induction_bed_minutes` may later be adjusted, by the same role; the name, the
    licensed counts and every derived field are immutable through that path, and although
    raising or lowering the budget never moves the posture by itself, it immediately changes
    the outcome of the priority-15 capacity test."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    assert setup["budget_adjustment"].status_code == 200
    adjusted = get_success_data(setup["budget_adjustment"])
    assert_obstetric_unit(adjusted)
    assert adjusted["max_daily_induction_bed_minutes"] == ADJUSTED_BUDGET
    assert adjusted["staffing_posture"] == "OPEN"
    assert setup["fresh_version"] == setup["stale_version"] + 1


def test_the_superseded_revision_number_is_refused_on_the_hold(
    one_unit_walked_through_four_revisions,
):
    """"Placing a capacity hold on an induction booking requires `expected_unit_version` to
    equal the current `version` of the owning `ObstetricUnit`; a mismatch is refused with
    `ERR_STALE_UNIT_VERSION` and HTTP 412, leaving the bed and both bed-minute maps
    untouched." Also: "A caller holding a revision number that is no longer current is, by
    definition, reasoning about a chart state that has been superseded, and its write is
    refused rather than merged."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    validate_error(setup["stale_hold"], ApiErrorId.ERR_STALE_UNIT_VERSION.value, 412)
    assert setup["stale_version"] != setup["fresh_version"]


def test_the_refused_hold_froze_no_projection_and_took_no_bed(
    one_unit_walked_through_four_revisions,
):
    """"Placing a capacity hold on an induction booking requires `expected_unit_version` to
    equal the current `version` of the owning `ObstetricUnit`; a mismatch is refused with
    `ERR_STALE_UNIT_VERSION` and HTTP 412, leaving the bed and both bed-minute maps
    untouched." Also: "The guard is evaluated before any state-machine or business rule for
    that operation, so a stale revision number is reported as a stale revision even when the
    request would also have failed a clinical precondition."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    unmoved = setup["booking_after_the_refusal"]
    assert_induction_booking(unmoved)
    assert unmoved["status"] == "REQUESTED"
    assert unmoved["projected_occupancy_minutes"] is None
    assert unmoved["bed_id"] is None
    bed = setup["bed_after_the_refusal"]
    assert_bed(bed)
    assert bed["status"] == "AVAILABLE"
    assert bed["held_booking_id"] is None
    unit = setup["unit_after_the_refusal"]
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0


def test_the_refreshed_revision_number_freezes_the_projection(
    one_unit_walked_through_four_revisions,
):
    """"Placing a hold is a `PatientAccessCoordinator` act supplying `bed_id` and
    `expected_unit_version`. The booking moves `REQUESTED` to `CAPACITY_HELD`, the named `LDR`
    bed moves `AVAILABLE` to `HELD` with `held_booking_id` written, and `hold_expires_at` is
    set to the current instant plus 120 minutes. This is also the moment
    `projected_occupancy_minutes` is frozen, as `expected_labor_minutes` plus the unit's
    current `turnover_buffer_minutes`, and that frozen integer is the exact quantum every later
    credit and debit moves."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    world = setup["world"]
    assert setup["accepted_hold"].status_code == 200
    held = get_success_data(setup["accepted_hold"])
    assert_induction_booking(held)
    assert held["status"] == "CAPACITY_HELD"
    assert held["bed_id"] == world.bed_id("LDR-01")
    assert held["projected_occupancy_minutes"] == FROZEN_PROJECTION
    assert EXPECTED_LABOR_MINUTES + OPEN_BUFFER_MINUTES == FROZEN_PROJECTION
    assert_instant_equals(held["hold_expires_at"], HOLD_EXPIRES_AT, "hold_expires_at")
    bed = setup["bed_after_the_hold"]
    assert_bed(bed)
    assert bed["status"] == "HELD"
    assert bed["held_booking_id"] == setup["booking"]["id"]
    unit = setup["unit_after_the_hold"]
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == FROZEN_PROJECTION


def test_the_version_the_caller_just_used_successfully_is_already_stale(
    one_unit_walked_through_four_revisions,
):
    """"The day's `held_bed_minutes_by_day` entry for the UTC date of `requested_start_utc` is
    increased by it." Also: "A posture re-derivation triggered by somebody else's checklist
    completion increments the unit's `version`; an acuity re-price triggered by a phase advance
    increments the encounter's `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    assert setup["version_after_the_hold"] == setup["fresh_version"] + 1
    assert setup["version_after_the_hold"] == setup["stale_version"] + 2


def test_the_same_error_answers_the_snapshot_for_the_same_reason(
    one_unit_walked_through_four_revisions,
):
    """"Creating a quality measure snapshot likewise requires `expected_unit_version` to equal
    the unit's current `version`, and a mismatch is refused with `ERR_STALE_UNIT_VERSION` and
    HTTP 412 before any cohort is computed." Also: "**Priority 6** — the revision guard
    described in section 2.4, on care-assignment creation, induction capacity holding, snapshot
    creation and bundle rescission, yielding `ERR_STALE_ENCOUNTER_VERSION`,
    `ERR_STALE_UNIT_VERSION` or `ERR_STALE_ACTIVATION_VERSION` at HTTP 412; it is checked
    before any state-machine or business rule for those four operations."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    refused = setup["stale_snapshot"]
    validate_error(refused, ApiErrorId.ERR_STALE_UNIT_VERSION.value, 412)
    seen = refused.json()["data"]["error_id"]
    assert seen != ApiErrorId.ERR_MEASURE_PERIOD_INVALID.value
    assert seen == setup["stale_hold"].json()["data"]["error_id"]


def test_the_refused_snapshot_left_no_draft_row_behind(
    one_unit_walked_through_four_revisions,
):
    """"Creating a quality measure snapshot likewise requires `expected_unit_version` to equal
    the unit's current `version`, and a mismatch is refused with `ERR_STALE_UNIT_VERSION` and
    HTTP 412 before any cohort is computed."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    listed = setup["snapshots_after_the_refusal"]
    assert listed.status_code == 200
    body = listed.json()
    assert body["meta"]["total_count"] == 0
    assert body["data"] == []


def test_the_identical_window_succeeds_once_the_version_is_refreshed(
    one_unit_walked_through_four_revisions,
):
    """"A `PerinatalSafetyOfficer` computes a quality measure snapshot on a unit over the
    half-open window from `period_start_utc`, which is inclusive, to `period_end_utc`, which is
    exclusive and must be strictly greater than the start, refused otherwise with
    `ERR_MEASURE_PERIOD_INVALID`." Also: "The snapshot opens at `DRAFT`, and creating a
    snapshot for an identical window supersedes every existing row for that window, whether
    `DRAFT` or `CERTIFIED`, moving each to the terminal `SUPERSEDED` and writing the new
    snapshot's identifier into each predecessor's `superseded_by_snapshot_id`; a certified
    predecessor keeps its frozen counts for audit and is never recomputed."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    assert setup["accepted_snapshot"].status_code == 201
    snapshot = get_success_data(setup["accepted_snapshot"])
    assert_snapshot(snapshot)
    assert snapshot["status"] == "DRAFT"
    assert snapshot["unit_id"] == setup["world"].unit_id
    assert_instant_equals(snapshot["period_start_utc"], PERIOD_START, "period_start_utc")
    assert_instant_equals(snapshot["period_end_utc"], PERIOD_END, "period_end_utc")
    assert snapshot["superseded_by_snapshot_id"] is None


def test_the_empty_july_cohort_reports_null_rates_and_not_zeroes(
    one_unit_walked_through_four_revisions,
):
    """"The cohort is the encounters on this unit whose `delivery_mode` is non-null and whose
    attribution instant falls inside the half-open window, meaning at or after the start and
    strictly before the end." Also: "Each rate — `ntsv_cesarean_rate_pct` and
    `episiotomy_rate_pct` — is null when its own denominator is 0 — never 0.0 — and otherwise
    is 100.0 multiplied by that numerator and divided by that denominator, rounded to 4 decimal
    places half-up."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_refused_on_both_declared_unit_scoped_writes_while_the_refreshed_version_passes
    """
    setup = one_unit_walked_through_four_revisions
    snapshot = get_success_data(setup["accepted_snapshot"])
    assert snapshot["ntsv_cesarean_denominator"] == 0
    assert snapshot["ntsv_cesarean_numerator"] == 0
    assert snapshot["episiotomy_denominator"] == 0
    assert snapshot["episiotomy_numerator"] == 0
    assert snapshot["ntsv_cesarean_rate_pct"] is None
    assert snapshot["episiotomy_rate_pct"] is None
    assert snapshot["composite_quality_index"] is None
