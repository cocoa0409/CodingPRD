"""
Requests that violate two rules at once. Only the higher-priority rule's error
may be reported, and the loser must not be reported instead.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CYLINDER_FILL_LIMIT_EXCEEDED,
    ERR_INSUFFICIENT_CYLINDER_CONTENTS,
    ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED,
    ERR_REFRIGERANT_TYPE_MISMATCH,
    ERR_SYSTEM_RETIRED,
    ERR_TECHNICIAN_CERT_EXPIRED,
)
from test_helpers.assertions import assert_mass, assert_system_charge
from test_helpers.test_users import make_technician_headers
from test_helpers.types import (
    EQUIPMENT_VERIFICATION_OVERDUE,
    SERVICE_RECOVER_REFRIGERANT,
)


# ─── entity state beats technician safety ─────────────────────────────


def _retired_system_and_expired_technician(api):
    """
    A 60.0 lb system commissioned empty and retired straight away, plus a
    technician whose EPA certification lapsed a month before the work instant.
    One service record therefore breaks two rules at once.
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    system = X.create_empty_system(api, store["id"], rt404["id"])
    technician = X.create_technician(
        api,
        full_name="Marta Vogel",
        epa_certification_number="EPA-608-33333",
        certification_expires_on="2026-07-01T00:00:00Z",
    )
    equipment = X.create_equipment(api, store["id"], technician["id"])
    cylinder = X.create_cylinder(api, store["id"], rt404["id"])
    X.retire_system(api, system["id"])
    return {
        "store_id": store["id"],
        "system_id": system["id"],
        "technician_id": technician["id"],
        "equipment_id": equipment["id"],
        "cylinder_id": cylinder["id"],
        "version": X.system_version(api, system["id"]),
    }


def _record_on_retired_system(api, env):
    return api.create_service_record(
        F.service_record_payload(
            env["system_id"],
            env["technician_id"],
            env["equipment_id"],
            env["version"],
            cylinder_id=env["cylinder_id"],
            refrigerant_added_lbs=10.0,
            performed_at="2026-08-01T00:00:00Z",
            duration_minutes=60,
        ),
        make_technician_headers(env["technician_id"]),
    )


def test_retired_system_error_wins_over_the_expired_certification_error(api):
    """
    The system's retired state is reported and the expired certification is not;
    the two even differ in HTTP status, so the ordering is unambiguous.

    Design: Difficulty/priority_pair_validation_conflict/retired_system_beats_expired_certification_state_over_safety
    """
    env = _retired_system_and_expired_technician(api)

    body = validate_error(_record_on_retired_system(api, env), ERR_SYSTEM_RETIRED, 409)
    assert body["error_id"] != ERR_TECHNICIAN_CERT_EXPIRED


def test_rejected_record_on_a_retired_system_writes_nothing(api):
    """
    The refused write leaves the system's charge, the system's version and the
    cylinder's contents exactly as they were.

    Design: Difficulty/priority_pair_validation_conflict/retired_system_beats_expired_certification_state_over_safety
    """
    env = _retired_system_and_expired_technician(api)

    validate_error(_record_on_retired_system(api, env), ERR_SYSTEM_RETIRED, 409)

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=0.0)
    assert system["version"] == env["version"]
    assert_mass(
        X.get_cylinder(api, env["cylinder_id"])["current_contents_lbs"],
        40.0,
        "current_contents_lbs",
    )


# ─── equipment safety beats the cylinder fill constraint ──────────────


def _stale_machine_and_full_cylinder(api):
    """
    A recovery machine whose annual verification lapsed more than 365 days ago,
    and a cylinder already sitting exactly on its 80 percent fill limit. A
    recovery into that cylinder breaks both rules.
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        equipment_overrides={
            "equipment_serial": "RM-8888",
            "last_verification_on": "2025-01-01T00:00:00Z",
        },
    )
    env["version"] = X.system_version(api, env["system_id"])
    return env


def _recovery_into_a_full_cylinder(api, env):
    return api.create_service_record(
        F.service_record_payload(
            env["system_id"],
            env["tech1_id"],
            env["eq1_id"],
            env["version"],
            cylinder_id=env["cyl1_id"],
            service_type=SERVICE_RECOVER_REFRIGERANT,
            refrigerant_added_lbs=F.OMIT,
            refrigerant_recovered_lbs=5.0,
            performed_at="2026-08-01T00:00:00Z",
            duration_minutes=60,
        ),
        make_technician_headers(env["tech1_id"]),
    )


def test_uncertified_machine_error_wins_over_the_fill_limit_error(api):
    """
    Both candidates carry HTTP 422, so only the identifier distinguishes them:
    the machine's lapsed verification is the substantive safety violation.

    Design: Difficulty/priority_pair_validation_conflict/uncertified_recovery_machine_beats_cylinder_fill_limit_safety_over_constraint
    """
    env = _stale_machine_and_full_cylinder(api)

    assert env["eq1"]["status"] == EQUIPMENT_VERIFICATION_OVERDUE
    assert_mass(env["cyl1"]["fill_limit_lbs"], 40.0, "fill_limit_lbs")

    body = validate_error(
        _recovery_into_a_full_cylinder(api, env),
        ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED,
        422,
    )
    assert body["error_id"] != ERR_CYLINDER_FILL_LIMIT_EXCEEDED


def test_rejected_recovery_moves_neither_the_system_nor_the_cylinder(api):
    """
    Nothing is recovered: the system keeps its 80.0 lbs and the cylinder stays at
    its limit.

    Design: Difficulty/priority_pair_validation_conflict/uncertified_recovery_machine_beats_cylinder_fill_limit_safety_over_constraint
    """
    env = _stale_machine_and_full_cylinder(api)

    validate_error(
        _recovery_into_a_full_cylinder(api, env),
        ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED,
        422,
    )
    assert_system_charge(X.get_system(api, env["system_id"]), current_charge_lbs=80.0)
    assert_mass(
        X.get_cylinder(api, env["cyl1_id"])["current_contents_lbs"],
        40.0,
        "current_contents_lbs",
    )


# ─── referential identity beats the quantity constraint ───────────────


def _wrong_chemistry_empty_cylinder(api):
    """
    A cylinder that holds the wrong chemistry for the system and is empty as
    well, so a charge from it breaks a referential rule and an arithmetic one.
    """
    env = X.base_env(
        api, with_r448a=True, with_second_technician=False, with_cylinder=False
    )
    cyl448 = X.create_cylinder(
        api,
        env["store_id"],
        env["rt448_id"],
        cylinder_serial="CYL-0448",
        initial_contents_lbs=0.0,
    )
    env["cyl448"] = cyl448
    env["cyl448_id"] = cyl448["id"]
    env["version"] = X.system_version(api, env["system_id"])
    return env


def _charge_from_the_wrong_cylinder(api, env):
    return api.create_service_record(
        F.service_record_payload(
            env["system_id"],
            env["tech1_id"],
            env["eq1_id"],
            env["version"],
            cylinder_id=env["cyl448_id"],
            refrigerant_added_lbs=10.0,
            performed_at="2026-08-01T00:00:00Z",
            duration_minutes=60,
        ),
        make_technician_headers(env["tech1_id"]),
    )


def test_refrigerant_mismatch_error_wins_over_the_empty_cylinder_error(api):
    """
    Charging the wrong refrigerant is the substantive violation; the empty
    cylinder is merely arithmetic and must not be reported in its place.

    Design: Difficulty/priority_pair_validation_conflict/refrigerant_type_mismatch_beats_insufficient_cylinder_contents_referential_over_constraint
    """
    env = _wrong_chemistry_empty_cylinder(api)

    body = validate_error(
        _charge_from_the_wrong_cylinder(api, env), ERR_REFRIGERANT_TYPE_MISMATCH, 422
    )
    assert body["error_id"] != ERR_INSUFFICIENT_CYLINDER_CONTENTS


def test_rejected_mismatched_charge_leaves_the_ledger_untouched(api):
    """
    The system keeps its 80.0 lbs at a 0.0 percent leak rate and the wrong-
    chemistry cylinder stays empty.

    Design: Difficulty/priority_pair_validation_conflict/refrigerant_type_mismatch_beats_insufficient_cylinder_contents_referential_over_constraint
    """
    env = _wrong_chemistry_empty_cylinder(api)

    validate_error(
        _charge_from_the_wrong_cylinder(api, env), ERR_REFRIGERANT_TYPE_MISMATCH, 422
    )
    assert_system_charge(
        X.get_system(api, env["system_id"]), current_charge_lbs=80.0, leak_rate_pct=0.0
    )
    assert_mass(
        X.get_cylinder(api, env["cyl448_id"])["current_contents_lbs"],
        0.0,
        "current_contents_lbs",
    )
