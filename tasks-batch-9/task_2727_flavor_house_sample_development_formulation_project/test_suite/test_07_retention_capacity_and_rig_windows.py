"""Cabinet slot admission and the buffer-inflated rig occupation window."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_application_test_payload,
    create_retention_sample_payload,
)
from test_helpers.fixtures import (
    citrus_released_lot,
    create_cabinet,
    create_rig,
    error_id_of,
    read_cabinet,
    read_lot,
    schedule_application_test,
    store_retention_sample,
)
from test_helpers.test_users import LAB_COMPOUNDER

WINDOW_A_FROM = "2026-08-01T00:00:00Z"
WINDOW_A_UNTIL = "2026-11-01T00:00:00Z"
WINDOW_B_UNTIL = "2027-02-01T00:00:00Z"
STRADDLE_FROM = "2026-10-01T00:00:00Z"
STRADDLE_UNTIL = "2027-01-01T00:00:00Z"

RIG_INCUMBENT_START = "2026-08-10T08:00:00Z"
RIG_INCUMBENT_END = "2026-08-10T10:00:00Z"
RIG_GAP_EQUAL_START = "2026-08-10T10:30:00Z"
RIG_GAP_OVER_START = "2026-08-10T10:31:00Z"
RIG_CANDIDATE_END = "2026-08-10T12:00:00Z"


def _released_lot_with_cabinet(api, capacity_slots, cabinet_code):
    scenario = citrus_released_lot(api, batch_size_g=500)
    scenario["cabinet"] = create_cabinet(api, cabinet_code=cabinet_code,
                                        capacity_slots=capacity_slots,
                                        storage_temp_c=-20)
    return scenario


def test_slot_counts_are_ceilings_over_the_fifty_gram_slot(api):
    """120 g takes three slots and 50 g takes exactly one.

    The PRD says an aliquot's "`slot_count` is its `quantity_g` divided by the
    50-gram capacity of a single slot, rounded up to the next whole slot, so 50
    grams occupy one slot and 51 grams occupy two", and a fresh cabinet
    "reports `slots_available` equal to its `capacity_slots`".

    Design: Difficulty/boundary_precision_check/cabinet_slot_capacity_equality_admits_then_next_aliquot_overflows
    """
    scenario = _released_lot_with_cabinet(api, 4, "CAB-01")
    assert scenario["cabinet"]["slots_available"] == 4

    first = store_retention_sample(api, scenario["lot"]["id"],
                                   scenario["cabinet"]["id"], 120,
                                   WINDOW_A_FROM, WINDOW_A_UNTIL)
    second = store_retention_sample(api, scenario["lot"]["id"],
                                    scenario["cabinet"]["id"], 50,
                                    WINDOW_A_FROM, WINDOW_A_UNTIL)

    assert first["slot_count"] == 3
    assert second["slot_count"] == 1


def test_landing_exactly_on_cabinet_capacity_is_admitted(api):
    """Occupancy 3 + 1 equals the capacity of 4 and the aliquot is stored.

    The PRD says the candidate "is admitted when the summed `slot_count` of
    every `STORED` aliquot in the same cabinet whose interval overlaps the
    candidate's, plus the candidate's own `slot_count`, is at or below the
    cabinet's `capacity_slots`; landing exactly on capacity is admitted".

    Design: Difficulty/boundary_precision_check/cabinet_slot_capacity_equality_admits_then_next_aliquot_overflows
    """
    scenario = _released_lot_with_cabinet(api, 4, "CAB-01")
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, WINDOW_A_FROM, WINDOW_A_UNTIL)

    filling = store_retention_sample(api, scenario["lot"]["id"],
                                     scenario["cabinet"]["id"], 50,
                                     WINDOW_A_FROM, WINDOW_A_UNTIL)

    assert filling["status"] == "STORED"
    assert read_cabinet(api, scenario["cabinet"]["id"])["slots_available"] == 0


def test_the_aliquot_after_capacity_is_refused_and_allocates_nothing(api):
    """A single further gram needs a fifth slot and is refused.

    The PRD says exceeding capacity "is `ERR_CABINET_CAPACITY_EXCEEDED`", and
    since storing "also raises the lot's `allocated_g` by `quantity_g`" only on
    success, the refused aliquot must leave the ledger at 170 g allocated.

    Design: Difficulty/boundary_precision_check/cabinet_slot_capacity_equality_admits_then_next_aliquot_overflows
    """
    scenario = _released_lot_with_cabinet(api, 4, "CAB-01")
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, WINDOW_A_FROM, WINDOW_A_UNTIL)
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           50, WINDOW_A_FROM, WINDOW_A_UNTIL)

    response = api.create_retention_sample(
        create_retention_sample_payload(scenario["lot"]["id"],
                                        scenario["cabinet"]["id"], 1,
                                        WINDOW_A_FROM, WINDOW_A_UNTIL),
        LAB_COMPOUNDER)
    validate_error(response, ApiErrorId.ERR_CABINET_CAPACITY_EXCEEDED.value)

    stored = api.list_retention_samples(
        LAB_COMPOUNDER, {"cabinet_id": scenario["cabinet"]["id"]}).json()
    assert stored["meta"]["total_count"] == 2
    assert all(row["status"] == "STORED" for row in stored["data"])

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["allocated_g"] == 170
    assert lot["available_g"] == 330


def test_two_touching_retention_intervals_do_not_contend(api):
    """A cabinet of three slots holds two 120 g aliquots that merely touch.

    The PRD says "two aliquots contend only if their half-open intervals
    genuinely overlap ... two aliquots that merely touch, where one's
    `stored_until` equals the other's `stored_from`, do not overlap and do not
    contend", so both three-slot aliquots fit a three-slot cabinet.

    Design: Difficulty/resource_temporal_overlap/retention_half_open_adjacency_admitted_then_straddling_aliquot_overflows
    """
    scenario = _released_lot_with_cabinet(api, 3, "CAB-02")

    aliquot_a = store_retention_sample(api, scenario["lot"]["id"],
                                       scenario["cabinet"]["id"], 120,
                                       WINDOW_A_FROM, WINDOW_A_UNTIL)
    aliquot_b = store_retention_sample(api, scenario["lot"]["id"],
                                       scenario["cabinet"]["id"], 120,
                                       WINDOW_A_UNTIL, WINDOW_B_UNTIL)

    assert aliquot_a["slot_count"] == 3
    assert aliquot_b["slot_count"] == 3
    assert aliquot_b["status"] == "STORED"


def test_occupancy_at_the_current_clock_counts_only_the_covering_aliquot(api):
    """With the clock at 2026-08-01 only aliquot A occupies the cabinet.

    The PRD computes `slots_available` as "`capacity_slots` less the
    `slot_count` of every `STORED` aliquot in that cabinet whose storage
    interval covers the current logical clock, meaning its `stored_from` is at
    or before the clock and its `stored_until` is strictly after it".

    Design: Difficulty/resource_temporal_overlap/retention_half_open_adjacency_admitted_then_straddling_aliquot_overflows
    """
    scenario = _released_lot_with_cabinet(api, 3, "CAB-02")
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, WINDOW_A_FROM, WINDOW_A_UNTIL)
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, WINDOW_A_UNTIL, WINDOW_B_UNTIL)

    assert read_cabinet(api, scenario["cabinet"]["id"])["slots_available"] == 0


def test_a_straddling_aliquot_aggregates_both_neighbours_and_overflows(api):
    """One gram spanning both intervals sums to seven slots against three.

    The admission test is aggregate over every overlapping `STORED` aliquot, so
    a candidate from 2026-10-01 to 2027-01-01 overlaps both neighbours and its
    occupancy is 3 + 3 + 1.  Its 92-day span is above the "at least 90 days"
    minimum, so the refusal is `ERR_CABINET_CAPACITY_EXCEEDED` and not
    `ERR_RETENTION_PERIOD_TOO_SHORT`.

    Design: Difficulty/resource_temporal_overlap/retention_half_open_adjacency_admitted_then_straddling_aliquot_overflows
    """
    scenario = _released_lot_with_cabinet(api, 3, "CAB-02")
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, WINDOW_A_FROM, WINDOW_A_UNTIL)
    store_retention_sample(api, scenario["lot"]["id"], scenario["cabinet"]["id"],
                           120, WINDOW_A_UNTIL, WINDOW_B_UNTIL)

    response = api.create_retention_sample(
        create_retention_sample_payload(scenario["lot"]["id"],
                                        scenario["cabinet"]["id"], 1,
                                        STRADDLE_FROM, STRADDLE_UNTIL),
        LAB_COMPOUNDER)
    validate_error(response, ApiErrorId.ERR_CABINET_CAPACITY_EXCEEDED.value)
    assert error_id_of(response) != "ERR_RETENTION_PERIOD_TOO_SHORT"

    rows = api.list_retention_samples(
        LAB_COMPOUNDER, {"cabinet_id": scenario["cabinet"]["id"]}).json()
    assert rows["meta"]["total_count"] == 2

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["allocated_g"] == 240
    assert lot["available_g"] == 260


def test_a_gap_equal_to_the_cleanout_buffer_is_refused(api):
    """A candidate starting exactly 30 minutes after the incumbent conflicts.

    The PRD says "the gap from the incumbent's `window_end` to the candidate's
    `window_start` must be strictly greater than `cleanout_buffer_minutes`: a
    gap of exactly the buffer is refused", the refusal being
    `ERR_RIG_WINDOW_CONFLICT` at HTTP 409.

    Design: Difficulty/resource_temporal_overlap/rig_buffer_inflated_window_rejects_gap_equal_to_buffer
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    rig = create_rig(api, rig_code="RIG-BEV-02", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    incumbent = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                          dosage_pct=2.5, consumed_g=100,
                                          window_start=RIG_INCUMBENT_START,
                                          window_end=RIG_INCUMBENT_END)
    assert rig["cleanout_buffer_minutes"] == 30
    assert incumbent["status"] == "SCHEDULED"

    response = api.create_application_test(
        create_application_test_payload(scenario["lot"]["id"], rig["id"],
                                        RIG_GAP_EQUAL_START, RIG_CANDIDATE_END,
                                        2.5, 100),
        LAB_COMPOUNDER)
    validate_error(response, ApiErrorId.ERR_RIG_WINDOW_CONFLICT.value)


def test_a_gap_one_minute_over_the_buffer_is_admitted(api):
    """The 10:31 candidate books while the 10:30 candidate did not.

    The PRD says "a gap of the buffer plus one minute is admitted", so the same
    rig accepts the later booking and ends up carrying exactly two live tests.

    Design: Difficulty/resource_temporal_overlap/rig_buffer_inflated_window_rejects_gap_equal_to_buffer
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    rig = create_rig(api, rig_code="RIG-BEV-02", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                              dosage_pct=2.5, consumed_g=100,
                              window_start=RIG_INCUMBENT_START,
                              window_end=RIG_INCUMBENT_END)
    validate_error(
        api.create_application_test(
            create_application_test_payload(scenario["lot"]["id"], rig["id"],
                                            RIG_GAP_EQUAL_START,
                                            RIG_CANDIDATE_END, 2.5, 100),
            LAB_COMPOUNDER),
        ApiErrorId.ERR_RIG_WINDOW_CONFLICT.value)

    admitted = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                         dosage_pct=2.5, consumed_g=100,
                                         window_start=RIG_GAP_OVER_START,
                                         window_end=RIG_CANDIDATE_END)

    assert admitted["status"] == "SCHEDULED"
    booked = api.list_application_tests(LAB_COMPOUNDER, {"rig_id": rig["id"]}).json()
    assert booked["meta"]["total_count"] == 2


def test_the_refused_rig_booking_allocates_no_sample_mass(api):
    """Only the two admitted bookings hold grams: 200 allocated, 300 available.

    The PRD allocates on scheduling — "scheduling immediately raises the lot's
    `allocated_g` by `consumed_g` and lowers `available_g`" — so the rejected
    candidate must leave the ledger untouched.

    Design: Difficulty/resource_temporal_overlap/rig_buffer_inflated_window_rejects_gap_equal_to_buffer
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    rig = create_rig(api, rig_code="RIG-BEV-02", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    incumbent = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                          dosage_pct=2.5, consumed_g=100,
                                          window_start=RIG_INCUMBENT_START,
                                          window_end=RIG_INCUMBENT_END)
    validate_error(
        api.create_application_test(
            create_application_test_payload(scenario["lot"]["id"], rig["id"],
                                            RIG_GAP_EQUAL_START,
                                            RIG_CANDIDATE_END, 2.5, 100),
            LAB_COMPOUNDER),
        ApiErrorId.ERR_RIG_WINDOW_CONFLICT.value)
    schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                              dosage_pct=2.5, consumed_g=100,
                              window_start=RIG_GAP_OVER_START,
                              window_end=RIG_CANDIDATE_END)

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["allocated_g"] == 200
    assert lot["available_g"] == 300
    assert incumbent["window_end"].startswith("2026-08-10T10:00:00")
