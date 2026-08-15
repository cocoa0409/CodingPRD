"""Pump calibration and field-sample collection (PRD §2.8, §2.10, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_decimal,
    create_sample_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

IH = TEST_USERS["ih_headers"]
TECH = TEST_USERS["tech_headers"]


@pytest.mark.parametrize("pre,post", [(2.0, 2.1), (1.0, 1.05)])
def test_drift_exactly_five_percent_records_valid(api, pre, post):
    """PRD §3.4: "The calibration's `result` becomes `INVALID` only when
    `drift_pct` is strictly greater than 5.00; a drift of exactly 5.00 records
    `VALID`."

    Design: Difficulty/boundary_precision_check/drift_exactly_five_percent_stays_valid
    """
    site = fx.create_site()
    pump = fx.create_pump(site["id"])
    cal = fx.create_calibration(pump["id"], pre_flow_lpm=pre)

    recorded = validate_success(
        api.record_post_flow(cal["id"], {"post_flow_lpm": post}, TECH), 200
    )
    assert_decimal(recorded["drift_pct"], 5.00)
    assert recorded["result"] == "VALID", "equality with 5.00 is not a violation"
    assert recorded["post_flow_lpm"] == pytest.approx(post)


@pytest.mark.parametrize("pre,post,expected", [(2.0, 2.101, 5.05), (2.0, 2.2, 10.0)])
def test_drift_above_five_percent_records_invalid(api, pre, post, expected):
    """PRD §3.4: "The system computes `drift_pct` as the absolute difference
    between the post-sampling and pre-sampling flow rates, divided by
    `pre_flow_lpm`, multiplied by one hundred, and rounded half up to two
    decimal places. The calibration's `result` becomes `INVALID` only when
    `drift_pct` is strictly greater than 5.00; a drift of exactly 5.00 records
    `VALID`."

    Design: Difficulty/boundary_precision_check/drift_exactly_five_percent_stays_valid
    """
    site = fx.create_site()
    pump = fx.create_pump(site["id"])
    cal = fx.create_calibration(pump["id"], pre_flow_lpm=pre)

    recorded = validate_success(
        api.record_post_flow(cal["id"], {"post_flow_lpm": post}, TECH), 200
    )
    assert_decimal(recorded["drift_pct"], expected)
    assert recorded["result"] == "INVALID"


def test_drift_invalidation_cascade(api):
    """PRD §3.4: "An `INVALID` verdict cascades immediately: the calibration's
    linked sample, if still `COLLECTED` or `SEALED`, is invalidated with
    `invalidate_reason` `PUMP_DRIFT`, which recomputes the plan's counters and
    may regress the plan as described above."
    PRD §2.10: "A sampling plan carries two counters: `active_sample_count`,
    the number of its `PERSONAL` samples in `COLLECTED`, `SEALED`, or
    `ANALYZED` status, and `analyzed_valid_count`, the number of its
    `PERSONAL` samples in `ANALYZED` status".

    Design: Corner/cross_cutting_complexity_layers/drift_invalidation_cascade
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])
    sample = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=cal["id"],
    )
    assert fx.get_plan(ctx.plan["id"])["active_sample_count"] == 1

    recorded = validate_success(
        api.record_post_flow(cal["id"], {"post_flow_lpm": 2.2}, TECH), 200
    )
    assert_decimal(recorded["drift_pct"], 10.0)
    assert recorded["result"] == "INVALID"

    sample = fx.get_sample(sample["id"])
    assert sample["status"] == "INVALIDATED"
    assert sample["invalidate_reason"] == "PUMP_DRIFT"

    plan = fx.get_plan(ctx.plan["id"])
    assert plan["active_sample_count"] == 0
    assert plan["status"] == "APPROVED", (
        "no regression: the plan never reached FIELD_COMPLETE"
    )


def test_calibration_record_post_twice_rejected(api):
    """PRD §3.4: "Recording a post-flow on a calibration whose `result` is
    already `VALID` or `INVALID` is rejected with
    `ERR_CALIBRATION_ALREADY_RECORDED` (409)."
    PRD §3.4: "Both terminal verdicts store `post_flow_lpm` and `drift_pct`
    and increment the calibration's `version`."

    Design: Corner/validations/calibration_record_post_twice_rejected
    """
    site = fx.create_site()
    pump = fx.create_pump(site["id"])
    cal = fx.create_calibration(pump["id"])
    recorded = fx.record_post(cal["id"], post_flow_lpm=2.05)
    assert recorded["result"] == "VALID"

    res = api.record_post_flow(cal["id"], {"post_flow_lpm": 2.07}, TECH)
    validate_error(res, ApiErrorId.ERR_CALIBRATION_ALREADY_RECORDED, 409)

    cal = fx.get_calibration(cal["id"])
    assert_decimal(cal["drift_pct"], 2.5)
    assert cal["result"] == "VALID"
    assert cal["post_flow_lpm"] == pytest.approx(2.05)


def test_calibration_pump_mismatch_rejected(api):
    """PRD §3.4: "The referenced calibration must belong to the same pump the
    sample names — the calibration's pump must equal the sample's `pump_id` —
    else `ERR_CALIBRATION_PUMP_MISMATCH`."

    Design: Corner/validations/calibration_pump_mismatch_rejected
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump1 = fx.create_pump(ctx.site["id"], serial_number="P-001")
    pump2 = fx.create_pump(ctx.site["id"], serial_number="P-002")
    cal_of_pump2 = fx.create_calibration(pump2["id"])

    res = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            employee_id=ctx.employees[0]["id"],
            pump_id=pump1["id"],
            pre_calibration_id=cal_of_pump2["id"],
        ),
        TECH,
    )
    validate_error(res, ApiErrorId.ERR_CALIBRATION_PUMP_MISMATCH, 422)


def test_calibration_single_use_rejected(api):
    """PRD §3.4: "And the calibration must not already be linked to another
    sample that has not been invalidated, else `ERR_CALIBRATION_IN_USE` (409);
    a calibration serves at most one live sample at a time, and creating the
    sample records it in the calibration's `linked_sample_id`."

    Design: Corner/validations/calibration_single_use_rejected
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])
    fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=cal["id"],
    )
    assert fx.get_calibration(cal["id"])["linked_sample_id"] is not None

    res = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            collection_date="2026-08-04",
            employee_id=ctx.employees[0]["id"],
            pump_id=pump["id"],
            pre_calibration_id=cal["id"],
        ),
        TECH,
    )
    validate_error(res, ApiErrorId.ERR_CALIBRATION_IN_USE, 409)


def test_blank_personal_conditional_fields(api):
    """PRD §3.4: "A `PERSONAL` sample must carry `employee_id`, `pump_id`, and
    `pre_calibration_id`; a `FIELD_BLANK` must carry none of the three, and
    violating either conditional rule is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/blank_personal_conditional_fields
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])

    missing_pump = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            employee_id=ctx.employees[0]["id"],
            pre_calibration_id=cal["id"],
        ),
        TECH,
    )
    validate_error(missing_pump, ApiErrorId.ERR_INVALID_REQUEST, 400)

    blank_with_pump = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            sample_type="FIELD_BLANK",
            start_minute=0,
            pump_id=pump["id"],
        ),
        TECH,
    )
    validate_error(blank_with_pump, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_pump_touching_intervals_accepted(api):
    """PRD §3.4: "Pumps themselves may not be double-booked: on a single
    `collection_date`, a pump may not appear on two non-`INVALIDATED` samples
    whose time intervals overlap, where each sample's interval begins at its
    `start_minute` and runs `duration_minutes` minutes forward, including the
    starting minute but excluding the ending minute; intervals that merely
    touch end-to-start are permitted."

    Design: Difficulty/resource_temporal_overlap/pump_half_open_interval_booking
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")

    first = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        start_minute=480,
    )
    touching = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        start_minute=720,  # exactly the first interval's excluded end
    )
    assert touching["start_minute"] == 720
    assert fx.get_plan(ctx.plan["id"])["active_sample_count"] == 2
    assert first["status"] == "COLLECTED"


def test_pump_overlapping_interval_rejected(api):
    """PRD §3.4: "An overlapping booking is rejected with
    `ERR_PUMP_DOUBLE_BOOKED` (409)."
    PRD §3.4: "on a single `collection_date`, a pump may not appear on two
    non-`INVALIDATED` samples whose time intervals overlap".

    Design: Difficulty/resource_temporal_overlap/pump_half_open_interval_booking
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        start_minute=480,
    )

    overlap = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            employee_id=ctx.employees[0]["id"],
            pump_id=pump["id"],
            pre_calibration_id=fx.create_calibration(pump["id"])["id"],
            start_minute=719,  # one minute into [480, 720)
        ),
        TECH,
    )
    validate_error(overlap, ApiErrorId.ERR_PUMP_DOUBLE_BOOKED, 409)
    assert fx.get_plan(ctx.plan["id"])["active_sample_count"] == 1

    # The booking rule is scoped to a single collection_date.
    other_day = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        collection_date="2026-08-04",
        start_minute=480,
    )
    assert other_day["collection_date"] == "2026-08-04"


def test_sample_seal_twice_rejected(api):
    """PRD §3.4: "Chain of custody continues with sealing: a technician seals
    a `COLLECTED` sample, moving it `COLLECTED → SEALED` and incrementing its
    `version`; sealing from any other status is rejected with
    `ERR_SAMPLE_INVALID_STATE` (409)."

    Design: Corner/state_machines/sample_seal_twice_rejected
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    sample = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
    )
    sealed = fx.seal_sample(sample["id"])
    assert sealed["status"] == "SEALED"
    assert sealed["version"] == sample["version"] + 1

    res = api.seal_sample(sample["id"], TECH)
    validate_error(res, ApiErrorId.ERR_SAMPLE_INVALID_STATE, 409)

    resealed = fx.get_sample(sample["id"])
    assert resealed["status"] == "SEALED"
    assert resealed["version"] == sealed["version"]


def test_sample_invalidate_terminal_rejected(api):
    """PRD §3.4: "A hygienist may manually invalidate a sample while it is
    `COLLECTED` or `SEALED`, optionally supplying a free-text `reason`; the
    stored `invalidate_reason` records `MANUAL`, and the attempt from any
    other status is `ERR_SAMPLE_INVALID_STATE`."

    Design: Corner/state_machines/sample_invalidate_terminal_rejected
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    sample = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
    )
    invalidated = fx.invalidate_sample(sample["id"], reason="dropped")
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["invalidate_reason"] == "MANUAL"

    res = api.invalidate_sample(sample["id"], {"reason": "again"}, IH)
    validate_error(res, ApiErrorId.ERR_SAMPLE_INVALID_STATE, 409)

    sample = fx.get_sample(sample["id"])
    assert sample["status"] == "INVALIDATED"
    assert sample["invalidate_reason"] == "MANUAL"


def test_invalidate_replace_conserves_active_count(api):
    """PRD §2.10: "Because invalidating a sample subtracts one from
    `active_sample_count` and collecting a replacement adds one back, the
    invalidate-then-replace pair leaves the count unchanged."
    PRD §3.4: "Any invalidation recomputes the plan's counters, releases the
    calibration link by resetting the calibration's `linked_sample_id` to
    null, regresses the plan `FIELD_COMPLETE → APPROVED` or `LAB_COMPLETE →
    APPROVED` if the counters fall below the requirement, and increments the
    sample's `version`."

    Design: Difficulty/compensating_invariant/invalidate_replace_conserves_active_count
    """
    ctx = fx.setup_approved_plan(member_count=1)
    fx.collect_personal_samples(ctx, 3, record_post_flows=False)
    assert fx.get_plan(ctx.plan["id"])["active_sample_count"] == 3

    doomed = ctx.samples[0]
    fx.invalidate_sample(doomed["id"])
    assert fx.get_sample(doomed["id"])["status"] == "INVALIDATED"
    assert fx.get_plan(ctx.plan["id"])["active_sample_count"] == 2
    assert fx.get_calibration(ctx.calibrations[0]["id"])["linked_sample_id"] is None

    fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=ctx.pump["id"],
        pre_calibration_id=ctx.calibrations[0]["id"],
        collection_date="2026-08-04",
    )
    plan = fx.get_plan(ctx.plan["id"])
    assert plan["active_sample_count"] == 3
    assert plan["status"] == "APPROVED"


def test_counter_recompute_does_not_advance_plan_version(api):
    """PRD §2.10: "These counters are recomputed whenever a sample is created,
    invalidated, or analyzed, and the recomputation by itself does not advance
    the plan's `version` — only an actual plan status transition does."

    Design: Difficulty/compensating_invariant/invalidate_replace_conserves_active_count
    """
    ctx = fx.setup_approved_plan(member_count=1)
    approved = fx.get_plan(ctx.plan["id"])
    fx.collect_personal_samples(ctx, 3, record_post_flows=False)

    after_create = fx.get_plan(ctx.plan["id"])
    assert after_create["version"] == approved["version"], (
        "collecting samples recomputes counters without a status transition"
    )
    assert after_create["active_sample_count"] == 3

    fx.invalidate_sample(ctx.samples[1]["id"])
    after_invalidate = fx.get_plan(ctx.plan["id"])
    assert after_invalidate["version"] == approved["version"]
    assert after_invalidate["active_sample_count"] == 2

    fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=ctx.pump["id"],
        pre_calibration_id=ctx.calibrations[1]["id"],
        collection_date="2026-08-04",
    )
    after_replace = fx.get_plan(ctx.plan["id"])
    assert after_replace["version"] == approved["version"]
    assert after_replace["active_sample_count"] == 3


def test_sample_create_existence_beats_plan_state(api):
    """PRD §2.8: "Every request is evaluated against a fixed validation
    pipeline, and the first failing stage determines the error returned —
    later stages are never consulted for that request."
    PRD §2.8: "Fourth, existence: path identifiers are resolved left to right,
    then body-referenced identifiers in their declared input order; the first
    identifier that does not correspond to an existing resource yields
    `ERR_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/sample_create_existence_beats_plan_state
    """
    ctx = fx.setup_site_seg(member_count=1)
    plan = fx.create_plan(ctx.seg["id"])  # DRAFT: sampling would be closed
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])

    res = api.create_field_sample(
        create_sample_payload(
            plan["id"],
            employee_id=ctx.employees[0]["id"],
            pump_id="11111111-1111-1111-1111-111111111111",
            pre_calibration_id=cal["id"],
        ),
        TECH,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)


def test_sample_create_existence_beats_plan_state_employee(api):
    """PRD §2.8: "Fourth, existence: path identifiers are resolved left to
    right, then body-referenced identifiers in their declared input order; the
    first identifier that does not correspond to an existing resource yields
    `ERR_NOT_FOUND`."
    PRD §2.8: "Sixth, state preconditions: the target entity must be in a
    status that permits the requested operation".

    Design: Difficulty/priority_pair_validation_conflict/sample_create_existence_beats_plan_state
    """
    ctx = fx.setup_site_seg(member_count=1)
    plan = fx.create_plan(ctx.seg["id"])  # DRAFT
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])

    res = api.create_field_sample(
        create_sample_payload(
            plan["id"],
            employee_id=NON_EXISTENT_UUID,
            pump_id=pump["id"],
            pre_calibration_id=cal["id"],
        ),
        TECH,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)


def test_sample_create_referential_beats_temporal(api):
    """PRD §2.8: "Seventh, cross-entity referential coherence: the sampled
    employee's membership, the calibration's pump, the batch's analyte, and
    the fit test's clearance ownership (§3.4, §3.5, §3.8). Eighth,
    segregation-of-duties and safety gates (§2.9). Ninth, temporal windows:
    the plan collection window, the batch intake window, and the retention
    gate."
    PRD §3.4: "The sampled employee must hold a membership in the plan's
    group, else `ERR_EMPLOYEE_NOT_SEG_MEMBER`."

    Design: Difficulty/priority_pair_validation_conflict/sample_create_referential_beats_temporal
    """
    ctx = fx.setup_approved_plan(member_count=1)
    outsider = fx.create_employee(ctx.site["id"], external_ref="E9")
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])

    res = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            collection_date="2026-08-20",  # outside the plan window too
            employee_id=outsider["id"],
            pump_id=pump["id"],
            pre_calibration_id=cal["id"],
        ),
        TECH,
    )
    validate_error(res, ApiErrorId.ERR_EMPLOYEE_NOT_SEG_MEMBER, 422)


def test_sample_create_referential_and_temporal_in_isolation(api):
    """PRD §3.4: "The sampled employee must hold a membership in the plan's
    group, else `ERR_EMPLOYEE_NOT_SEG_MEMBER`."
    PRD §3.4: "The `collection_date` must fall within the plan's window from
    `planned_start_date` through `planned_end_date`, inclusive at both ends,
    else `ERR_SAMPLE_OUTSIDE_PLAN_WINDOW` (422)."

    Design: Difficulty/priority_pair_validation_conflict/sample_create_referential_beats_temporal
    """
    ctx = fx.setup_approved_plan(member_count=1)
    outsider = fx.create_employee(ctx.site["id"], external_ref="E9")
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")

    # Non-member, in-window date: the referential rule fires alone.
    non_member = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            collection_date="2026-08-04",
            employee_id=outsider["id"],
            pump_id=pump["id"],
            pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        ),
        TECH,
    )
    validate_error(non_member, ApiErrorId.ERR_EMPLOYEE_NOT_SEG_MEMBER, 422)

    # Member, out-of-window date: the temporal rule fires alone.
    out_of_window = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            collection_date="2026-08-20",
            employee_id=ctx.employees[0]["id"],
            pump_id=pump["id"],
            pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        ),
        TECH,
    )
    validate_error(out_of_window, ApiErrorId.ERR_SAMPLE_OUTSIDE_PLAN_WINDOW, 422)
