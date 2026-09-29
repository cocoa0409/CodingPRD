"""
Two resources with deliberately different interval semantics: a technician's
labour window is half-open so abutting work is legal, while a recovery machine's
occupancy is closed and decontamination-buffered so touching it is a conflict.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_EQUIPMENT_DECONTAMINATION_CONFLICT,
    ERR_TECHNICIAN_SCHEDULE_CONFLICT,
)
from test_helpers.assertions import (
    assert_instant,
    assert_store_posture,
    assert_system_charge,
)
from test_helpers.test_users import make_technician_headers
from test_helpers.types import POSTURE_COMPLIANT, SERVICE_ROUTINE_MAINTENANCE


def _maintenance(api, env, technician_id, equipment_id, performed_at, duration_minutes):
    """
    A ROUTINE_MAINTENANCE record, which moves no refrigerant at all, so the only
    thing under test is the occupancy of the technician and of the machine.
    """
    return api.create_service_record(
        F.service_record_payload(
            env["system_id"],
            technician_id,
            equipment_id,
            env["version"],
            service_type=SERVICE_ROUTINE_MAINTENANCE,
            refrigerant_added_lbs=F.OMIT,
            performed_at=performed_at,
            duration_minutes=duration_minutes,
        ),
        make_technician_headers(technician_id),
    )


# ─── technician labour is half-open ───────────────────────────────────


def _technician_busy_from_eight_to_nine(api):
    """
    One technician with two machines, already booked for an hour of maintenance on
    the first machine, so the second machine cannot mask the technician rule.
    """
    env = X.base_env(
        api,
        clock="2026-08-01T12:00:00Z",
        with_second_technician=False,
        with_second_equipment=True,
        with_cylinder=False,
    )
    env["version"] = X.system_version(api, env["system_id"])
    env["record1"] = validate_success(
        _maintenance(
            api, env, env["tech1_id"], env["eq1_id"], "2026-08-01T08:00:00Z", 60
        ),
        expected_status=201,
    )
    env["version"] = X.system_version(api, env["system_id"])
    return env


def test_one_minute_of_technician_overlap_is_refused(api):
    """
    Starting a minute before the previous window ends overlaps by exactly one
    minute, which the half-open interval still counts; nothing is written.

    Design: Difficulty/resource_temporal_overlap/technician_labour_intervals_are_half_open_abutting_allowed
    """
    env = _technician_busy_from_eight_to_nine(api)

    assert_instant(
        env["record1"]["occupies_until"], "2026-08-01T09:00:00Z", "occupies_until"
    )
    assert_instant(
        env["record1"]["equipment_released_at"],
        "2026-08-01T10:00:00Z",
        "equipment_released_at",
    )

    validate_error(
        _maintenance(
            api, env, env["tech1_id"], env["eq2_id"], "2026-08-01T08:59:00Z", 30
        ),
        ERR_TECHNICIAN_SCHEDULE_CONFLICT,
        409,
    )
    assert X.get_system(api, env["system_id"])["version"] == env["version"]


def test_technician_work_abutting_at_the_exact_end_instant_is_allowed(api):
    """
    The upper bound is exclusive, so starting at the very instant the previous
    window ends is legal, and no refrigerant moved anywhere along the way.

    Design: Difficulty/resource_temporal_overlap/technician_labour_intervals_are_half_open_abutting_allowed
    """
    env = _technician_busy_from_eight_to_nine(api)

    record2 = validate_success(
        _maintenance(
            api, env, env["tech1_id"], env["eq2_id"], "2026-08-01T09:00:00Z", 30
        ),
        expected_status=201,
    )
    assert_instant(record2["occupies_until"], "2026-08-01T09:30:00Z", "occupies_until")

    assert_system_charge(
        X.get_system(api, env["system_id"]), current_charge_lbs=80.0, leak_rate_pct=0.0
    )
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        compliance_status=POSTURE_COMPLIANT,
        open_leak_event_count=0,
    )


# ─── machine occupancy is closed and buffered ─────────────────────────


def _machine_released_at_ten(api):
    """
    One machine and two technicians: an hour of work by the first technician plus
    the hour of decontamination releases the machine at 10:00, and the second
    technician has no other work so only the machine rule can fire.
    """
    env = X.base_env(api, clock="2026-08-01T12:00:00Z", with_cylinder=False)
    env["version"] = X.system_version(api, env["system_id"])
    env["record1"] = validate_success(
        _maintenance(
            api, env, env["tech1_id"], env["eq1_id"], "2026-08-01T08:00:00Z", 60
        ),
        expected_status=201,
    )
    env["version"] = X.system_version(api, env["system_id"])
    return env


def test_starting_exactly_at_the_release_instant_is_refused_for_a_machine(api):
    """
    Sharing the closing instant is a conflict for a machine, and the technician
    rule cannot be what fired because the second technician is otherwise idle —
    the same 09:00-style reuse a technician is granted is denied here.

    Design: Difficulty/resource_temporal_overlap/recovery_machine_occupancy_is_closed_and_buffered_touching_rejected
    """
    env = _machine_released_at_ten(api)

    assert_instant(
        env["record1"]["equipment_released_at"],
        "2026-08-01T10:00:00Z",
        "equipment_released_at",
    )

    body = validate_error(
        _maintenance(
            api, env, env["tech2_id"], env["eq1_id"], "2026-08-01T10:00:00Z", 30
        ),
        ERR_EQUIPMENT_DECONTAMINATION_CONFLICT,
        409,
    )
    assert body["error_id"] != ERR_TECHNICIAN_SCHEDULE_CONFLICT
    assert X.get_system(api, env["system_id"])["version"] == env["version"]


def test_one_minute_clear_of_the_buffer_is_allowed_for_a_machine(api):
    """
    A single minute past the closed endpoint is enough, and the new record earns
    its own work-plus-decontamination release stamp.

    Design: Difficulty/resource_temporal_overlap/recovery_machine_occupancy_is_closed_and_buffered_touching_rejected
    """
    env = _machine_released_at_ten(api)

    record2 = validate_success(
        _maintenance(
            api, env, env["tech2_id"], env["eq1_id"], "2026-08-01T10:01:00Z", 30
        ),
        expected_status=201,
    )
    assert_instant(
        record2["equipment_released_at"],
        "2026-08-01T11:31:00Z",
        "equipment_released_at",
    )
