"""Meter-read lifecycle: submission, consumption computation, the high-reading
validation band, the flag/re-read cycle, and supersession.

Covers queue-A non_linear_state_machine (re-read cycle) and boundary_precision_check
(3x band), plus queue-B meter-read corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    create_meter_read_payload,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["meter_tech_headers"]


def _open_consumption_cycle(state_code="TX", utility_type="ELECTRIC", unom="KWH"):
    """Property + CONSUMPTION utility + unit + assigned meter + OPEN cycle.
    Returns (property, utility, unit, meter, cycle)."""
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code=state_code, common_area_pct=0.10)
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION", utility_type=utility_type, unit_of_measure=unom)
    unit = fx.create_unit(prop["id"], unit_number="U1")
    meter = fx.create_and_assign_meter(prop["id"], util["id"], unit["id"], "RR1")
    vb = fx.create_vendor_bill(prop["id"], util["id"], total_cost_cents=50000)
    cycle = fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    return prop, util, unit, meter, cycle


# --------------------------------------------------------------------------- #
# non_linear_state_machine / meter_read_re_read_cycle_flagged_rereadrequested_submitted
# --------------------------------------------------------------------------- #
def test_request_re_read_moves_flagged_to_re_read_requested_and_increments_count(api):
    """PRD §3.5: "From `FLAGGED`, the manager may request a re-read, moving the
    read to `RE_READ_REQUESTED` and incrementing its `re_read_count` by one."

    Design: Difficulty/non_linear_state_machine/meter_read_re_read_cycle_flagged_rereadrequested_submitted
    """
    prop, util, unit, meter, cycle = _open_consumption_cycle()
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=500), TECH)
    )
    get_success_data(api.submit_meter_read(read["id"], headers=TECH))
    get_success_data(api.flag_meter_read(read["id"], {"flag_reason": "suspected misread"}, PM))
    data = validate_success(api.request_re_read(read["id"], PM))
    assert data["status"] == "RE_READ_REQUESTED"
    assert data["re_read_count"] == 1


def test_re_submit_returns_read_to_submitted_and_recomputes_consumption(api):
    """PRD §3.5: "The technician then submits the re-read, which carries the read
    from `RE_READ_REQUESTED` back to `SUBMITTED`; this submission again requires
    the matching billing cycle to be `OPEN` (otherwise `ERR_CYCLE_NOT_OPEN`),
    overwrites the `reading_value` with the re-read value supplied as
    `reading_value`, and recomputes `consumption` as the larger of zero and the
    difference between the new reading value and the meter's
    `last_validated_reading`."

    Design: Difficulty/non_linear_state_machine/meter_read_re_read_cycle_flagged_rereadrequested_submitted
    """
    prop, _, unit, meter, cycle = _open_consumption_cycle()
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=500), TECH)
    )
    get_success_data(api.submit_meter_read(read["id"], headers=TECH))
    get_success_data(api.flag_meter_read(read["id"], {"flag_reason": "suspected misread"}, PM))
    get_success_data(api.request_re_read(read["id"], PM))
    data = validate_success(api.submit_meter_read(read["id"], payload={"reading_value": 480}, headers=TECH))
    assert data["status"] == "SUBMITTED"
    assert data["consumption"] == 480  # max(0, 480 - last_validated_reading 0)


# --------------------------------------------------------------------------- #
# boundary_precision_check / read_validation_band_exactly_3x_vs_over_3x
# --------------------------------------------------------------------------- #
def test_read_validation_accepts_exactly_three_times_baseline(api):
    """PRD §3.5: "The boundary is inclusive: a consumption exactly equal to three
    times the prior validated reading is accepted, and only consumption strictly
    above that limit is rejected."

    Design: Difficulty/boundary_precision_check/read_validation_band_exactly_3x_vs_over_3x
    """
    prop, util, unit, meter, cycle = _open_consumption_cycle()
    # baseline validated read -> last_validated_reading = 100
    fx.submit_and_validate_read(meter["id"], prop["id"], reading_value=100)
    # candidate at exactly 3x: consumption = 400 - 100 = 300
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=400), TECH)
    )
    get_success_data(api.submit_meter_read(read["id"], headers=TECH))
    data = validate_success(api.validate_meter_read(read["id"], PM))
    assert data["consumption"] == 300  # exactly 3 * 100
    assert data["status"] == "VALIDATED"


def test_read_validation_rejects_just_over_three_times_baseline(api):
    """PRD §3.5: "otherwise the read's `consumption` may not exceed the
    `last_validated_reading` multiplied by the high-reading multiple of three."
    PRD §3.5: "A read that exceeds the band must not be validated; the attempt is
    rejected with `ERR_READING_OUT_OF_RANGE`, and the read must instead be
    flagged and re-read."

    Design: Difficulty/boundary_precision_check/read_validation_band_exactly_3x_vs_over_3x
    """
    prop, util, unit, meter, cycle = _open_consumption_cycle()
    fx.submit_and_validate_read(meter["id"], prop["id"], reading_value=100)
    # candidate at 3x + 1: consumption = 401 - 100 = 301
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=401), TECH)
    )
    get_success_data(api.submit_meter_read(read["id"], headers=TECH))
    validate_error(api.validate_meter_read(read["id"], PM), ApiErrorId.ERR_READING_OUT_OF_RANGE.value)


# --------------------------------------------------------------------------- #
# Corner: entities / meter_read_consumption_computed_clamped_nonnegative
# --------------------------------------------------------------------------- #
def test_consumption_clamps_to_zero_below_baseline(api):
    """PRD §3.5: "On submission the read's `consumption` is computed as the
    reading value minus the meter's `last_validated_reading`, clamped so it is
    never negative; concretely, consumption is the larger of zero and the
    difference between `reading_value` and the meter's current
    `last_validated_reading`."

    Design: Corner/entities/meter_read_consumption_computed_clamped_nonnegative
    """
    prop, util, unit, meter, cycle = _open_consumption_cycle(utility_type="ELECTRIC")
    fx.submit_and_validate_read(meter["id"], prop["id"], reading_value=500)
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=480), TECH)
    )
    data = validate_success(api.submit_meter_read(read["id"], headers=TECH))
    assert data["consumption"] == 0  # max(0, 480 - 500)
    assert data["status"] == "SUBMITTED"


# --------------------------------------------------------------------------- #
# Corner: calculations / read_validation_baseline_zero_accepts_any_consumption
# --------------------------------------------------------------------------- #
def test_baseline_zero_accepts_any_consumption(api):
    """PRD §3.5: "if the meter's `last_validated_reading` is zero — the
    first-ever validated read for that meter — any non-negative consumption is
    accepted"
    PRD §3.5: "On successful validation the system sets the meter's
    `last_validated_reading` to this read's `reading_value`"

    Design: Corner/calculations/read_validation_baseline_zero_accepts_any_consumption
    """
    prop, util, unit, meter, cycle = _open_consumption_cycle(state_code="CA", utility_type="WATER", unom="GAL")
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=99999), TECH)
    )
    get_success_data(api.submit_meter_read(read["id"], headers=TECH))
    data = validate_success(api.validate_meter_read(read["id"], PM))
    assert data["status"] == "VALIDATED"
    meter_after = get_success_data(api.get_meter(meter["id"], PM))
    assert meter_after["last_validated_reading"] == 99999


# --------------------------------------------------------------------------- #
# Corner: state_machines / validate_read_supersedes_prior_validated_sibling
# --------------------------------------------------------------------------- #
def test_validate_supersedes_prior_validated_sibling(api):
    """PRD §3.5: "On successful validation the system sets the meter's
    `last_validated_reading` to this read's `reading_value`, and any other read
    for the same meter and period that was in `SUBMITTED` or `VALIDATED` status
    is transitioned to `SUPERSEDED`."

    Design: Corner/state_machines/validate_read_supersedes_prior_validated_sibling
    """
    prop, util, unit, meter, cycle = _open_consumption_cycle(state_code="CA", utility_type="WATER", unom="GAL")
    first = fx.submit_and_validate_read(meter["id"], prop["id"], reading_value=100)
    second = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=250), TECH)
    )
    get_success_data(api.submit_meter_read(second["id"], headers=TECH))
    data = validate_success(api.validate_meter_read(second["id"], PM))
    assert data["status"] == "VALIDATED"
    first_after = get_success_data(api.get_meter_read(first["id"], PM))
    assert first_after["status"] == "SUPERSEDED"
    meter_after = get_success_data(api.get_meter(meter["id"], PM))
    assert meter_after["last_validated_reading"] == 250
