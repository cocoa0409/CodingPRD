"""Booking-guard precedence conflicts: when two booking guards would both fail,
the earlier guard in the PRD §3.4 ordered sequence is the one reported.

Difficulty queue: priority_pair_validation_conflict (referential>fiscal, temporal>safety).

The PRD §3.4 booking-guard sentence enumerates the guards as an explicit ordered
sequence ("the system enforces: A; B; C; ..."), so two PRD-only implementers would
agree on which error wins in each pair below.
"""
from test_helpers import validate_error, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
ORMGR = TEST_USERS["or_manager_headers"]


# ===========================================================================
# Difficulty / priority_pair_validation_conflict /
#   referential_beats_fiscal_on_booking_excluded_over_capacity
# ===========================================================================
def test_excluded_procedure_beats_capacity():
    """PRD §3.4: "After the version check described in §2.8, the system enforces: the chosen
    procedure's `cms_payment_indicator` must not be `EXCLUDED` (`ERR_PROCEDURE_EXCLUDED`);
    the block's surgeon must be active and the procedure must belong to the same facility as
    the block (`ERR_SURGEON_INACTIVE`); for a non-add-on case, the case footprint
    `[start_min, end_min)` must lie entirely within the block's own `[start_min, end_min)`
    window (`ERR_CASE_OUTSIDE_BLOCK_WINDOW`); the OR time-conflict rule and the anesthesia
    time-conflict rule described in §3.5 must hold; if an `anesthesiologist_id` is supplied at
    booking, the CRNA-general rule of §3.6 must hold; if a `recovery_bay_id` is supplied at
    booking, the Phase II rule of §3.6 must hold; for a non-add-on case the block's finite
    minute pool must not be exceeded (§3.7); and the day-posture booking rule must hold (§3.7)."

    Booking an EXCLUDED 60-min procedure into a 30-minute empty block violates both the
    EXCLUDED guard (listed first) and the capacity guard (listed near the end); the earlier
    guard wins -> ERR_PROCEDURE_EXCLUDED.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_booking_excluded_over_capacity
    """
    world = fixtures.setup_facility_world(
        turnover_minutes=0,
        proc_overrides={"cpt_code": "99999", "description": "Excluded",
                        "scheduled_minutes": 60, "cms_payment_indicator": "EXCLUDED",
                        "cms_base_rate_cents": 0, "anesthesia_class": "MAC"})
    block = fixtures.setup_block(world, 480, 510)  # allocated 30 < 60 sched
    resp = api_client.book_case(block["id"], {
        "expected_block_version": block["version"], "patient_id": world["patient"]["id"],
        "procedure_id": world["procedure"]["id"], "start_min": 480}, SCHED)
    err = validate_error(resp, "ERR_PROCEDURE_EXCLUDED")
    assert err["error_id"] != "ERR_BLOCK_CAPACITY_EXCEEDED"


def test_excluded_guard_fires_when_only_referential_violated():
    """PRD §3.4: "After the version check described in §2.8, the system enforces: the chosen
    procedure's `cms_payment_indicator` must not be `EXCLUDED` (`ERR_PROCEDURE_EXCLUDED`);
    the block's surgeon must be active and the procedure must belong to the same facility as
    the block (`ERR_SURGEON_INACTIVE`); for a non-add-on case, the case footprint
    `[start_min, end_min)` must lie entirely within the block's own `[start_min, end_min)`
    window (`ERR_CASE_OUTSIDE_BLOCK_WINDOW`); the OR time-conflict rule and the anesthesia
    time-conflict rule described in §3.5 must hold; if an `anesthesiologist_id` is supplied at
    booking, the CRNA-general rule of §3.6 must hold; if a `recovery_bay_id` is supplied at
    booking, the Phase II rule of §3.6 must hold; for a non-add-on case the block's finite
    minute pool must not be exceeded (§3.7); and the day-posture booking rule must hold (§3.7)."

    Booking an EXCLUDED 60-min procedure into a block with ample capacity (allocated 120, no
    capacity violation) still fails the referential guard alone -> ERR_PROCEDURE_EXCLUDED.
    This isolates the referential guard so the precedence test's outcome is unambiguous: the
    referential guard owns this rejection in the conflict scenario.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_booking_excluded_over_capacity
    """
    world = fixtures.setup_facility_world(
        turnover_minutes=0,
        proc_overrides={"cpt_code": "99999", "description": "Excluded",
                        "scheduled_minutes": 60, "cms_payment_indicator": "EXCLUDED",
                        "cms_base_rate_cents": 0, "anesthesia_class": "MAC"})
    block = fixtures.setup_block(world, 480, 600)  # allocated 120 >= 60, no capacity conflict
    resp = api_client.book_case(block["id"], {
        "expected_block_version": block["version"], "patient_id": world["patient"]["id"],
        "procedure_id": world["procedure"]["id"], "start_min": 480}, SCHED)
    validate_error(resp, "ERR_PROCEDURE_EXCLUDED")


# ===========================================================================
# Difficulty / priority_pair_validation_conflict /
#   temporal_beats_safety_on_booking_or_conflict_and_phase2
# ===========================================================================
def test_or_time_conflict_beats_phase2_safety():
    """PRD §3.4: "After the version check described in §2.8, the system enforces: the chosen
    procedure's `cms_payment_indicator` must not be `EXCLUDED` (`ERR_PROCEDURE_EXCLUDED`);
    the block's surgeon must be active and the procedure must belong to the same facility as
    the block (`ERR_SURGEON_INACTIVE`); for a non-add-on case, the case footprint
    `[start_min, end_min)` must lie entirely within the block's own `[start_min, end_min)`
    window (`ERR_CASE_OUTSIDE_BLOCK_WINDOW`); the OR time-conflict rule and the anesthesia
    time-conflict rule described in §3.5 must hold; if an `anesthesiologist_id` is supplied at
    booking, the CRNA-general rule of §3.6 must hold; if a `recovery_bay_id` is supplied at
    booking, the Phase II rule of §3.6 must hold; for a non-add-on case the block's finite
    minute pool must not be exceeded (§3.7); and the day-posture booking rule must hold (§3.7)."

    A second case in the same OR that overlaps the first (after turnover) AND requests a
    non-Phase-II bay for a requires_phase2 procedure violates both the OR time-conflict guard
    (listed before) and the Phase II guard (listed after); the earlier guard wins ->
    ERR_OR_TIME_CONFLICT.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_safety_on_booking_or_conflict_and_phase2
    """
    world = fixtures.setup_facility_world(
        turnover_minutes=25, with_bay=True, phase2_capable=False,
        proc_overrides={"requires_phase2": True})
    fac, room, surg, day = world["facility"], world["room"], world["surgeon"], world["day"]
    proc, pat1, bay = world["procedure"], world["patient"], world["bay"]
    pat2 = fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 720)
    fixtures.book_case(block["id"], block["version"], pat1["id"], proc["id"], 480)  # occupies [480,540)+25
    v1 = fixtures.block_version(block["id"])
    resp = api_client.book_case(block["id"], {
        "expected_block_version": v1, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 500, "recovery_bay_id": bay["id"]}, SCHED)
    err = validate_error(resp, "ERR_OR_TIME_CONFLICT")
    assert err["error_id"] != "ERR_RECOVERY_PHASE2_REQUIRED"


def test_or_conflict_guard_fires_when_only_temporal_violated():
    """PRD §3.4: "After the version check described in §2.8, the system enforces: the chosen
    procedure's `cms_payment_indicator` must not be `EXCLUDED` (`ERR_PROCEDURE_EXCLUDED`);
    the block's surgeon must be active and the procedure must belong to the same facility as
    the block (`ERR_SURGEON_INACTIVE`); for a non-add-on case, the case footprint
    `[start_min, end_min)` must lie entirely within the block's own `[start_min, end_min)`
    window (`ERR_CASE_OUTSIDE_BLOCK_WINDOW`); the OR time-conflict rule and the anesthesia
    time-conflict rule described in §3.5 must hold; if an `anesthesiologist_id` is supplied at
    booking, the CRNA-general rule of §3.6 must hold; if a `recovery_bay_id` is supplied at
    booking, the Phase II rule of §3.6 must hold; for a non-add-on case the block's finite
    minute pool must not be exceeded (§3.7); and the day-posture booking rule must hold (§3.7)."

    A second case overlapping the first in the same OR, with NO recovery_bay supplied (so the
    Phase II safety guard does not apply at all), still fails the temporal guard alone ->
    ERR_OR_TIME_CONFLICT. This isolates the temporal guard so the precedence test's outcome
    is unambiguous: the temporal guard owns this rejection in the conflict scenario.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_safety_on_booking_or_conflict_and_phase2
    """
    world = fixtures.setup_facility_world(
        turnover_minutes=25, proc_overrides={"requires_phase2": True})
    fac, room, surg, day = world["facility"], world["room"], world["surgeon"], world["day"]
    proc, pat1 = world["procedure"], world["patient"]
    pat2 = fixtures.create_patient(fac["id"], mrn="MRN2", full_name="Pat Two", date_of_birth="1981-01-01")
    block = fixtures.create_surgeon_block(day["id"], surg["id"], room["id"], 480, 720)
    fixtures.book_case(block["id"], block["version"], pat1["id"], proc["id"], 480)
    v1 = fixtures.block_version(block["id"])
    resp = api_client.book_case(block["id"], {
        "expected_block_version": v1, "patient_id": pat2["id"],
        "procedure_id": proc["id"], "start_min": 500}, SCHED)  # no recovery_bay_id supplied
    validate_error(resp, "ERR_OR_TIME_CONFLICT")
