"""
Two conserved quantities and their compensating actions: the store's physical
refrigerant mass under a voided service record, and the statutory 30-day
extension budget under a revoked grant.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_extension_budget,
    assert_instant,
    assert_leak_event_schedule,
    assert_mass,
    assert_mass_conserved,
    assert_money,
    assert_system_charge,
)
from test_helpers.test_users import COMPLIANCE_MANAGER_HEADERS, REGULATOR_HEADERS
from test_helpers.types import (
    EVENT_OPEN,
    EXTENSION_APPROVED,
    EXTENSION_REVOKED,
)


# ─── refrigerant mass across the store's four buckets ─────────────────


def _ten_pounds_moved_and_two_vented(api):
    """
    The store opens holding 120.0 lbs in total: 80.0 in the system and 40.0 in the
    cylinder. One record then moves three of the four buckets at once — 10.0 lbs
    out of the cylinder, 8.0 into the system and 2.0 vented.
    """
    env = X.base_env(api, with_second_technician=False)
    env["version_before"] = X.system_version(api, env["system_id"])
    env["record"] = X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        env["version_before"],
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=10.0,
        refrigerant_lost_lbs=2.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=120,
    )
    env["record_id"] = env["record"]["id"]
    return env


def test_forward_action_moves_three_buckets_and_conserves_the_total(api):
    """
    The system gains 8.0, the cylinder loses 10.0 and 2.0 is vented, so the total
    is still exactly 120.0 lbs and the leak rate reads 10.0 percent with no event.

    Design: Difficulty/compensating_invariant/voiding_service_record_restores_total_refrigerant_mass_exactly
    """
    env = _ten_pounds_moved_and_two_vented(api)

    system = X.get_system(api, env["system_id"])
    cylinder = X.get_cylinder(api, env["cyl1_id"])
    store = X.get_store(api, env["store_id"])

    assert_system_charge(system, current_charge_lbs=88.0)
    assert_mass(cylinder["current_contents_lbs"], 30.0, "current_contents_lbs")
    assert_mass(store["vented_loss_lbs"], 2.0, "vented_loss_lbs")
    assert_mass_conserved([system], [cylinder], store, 120.0)

    assert_money(env["record"]["leak_rate_pct_after"], 10.0, "leak_rate_pct_after")
    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0
    assert_instant(
        env["record"]["retention_until"], "2029-08-01T00:00:00Z", "retention_until"
    )


def test_voiding_the_record_reverses_all_three_buckets_exactly(api):
    """
    The void is not merely a flag: every bucket returns to its opening figure, the
    total is still 120.0, the leak rate falls back to zero, and the retention
    clock survives the void.

    Design: Difficulty/compensating_invariant/voiding_service_record_restores_total_refrigerant_mass_exactly
    """
    env = _ten_pounds_moved_and_two_vented(api)

    voided = validate_success(
        api.void_service_record(
            env["record_id"], F.void_payload(), COMPLIANCE_MANAGER_HEADERS
        )
    )
    assert voided["voided"] is True
    assert_instant(voided["voided_at"], "2026-08-01T00:00:00Z", "voided_at")
    assert voided["void_reason_code"] == "MISKEYED_QUANTITY"

    system = X.get_system(api, env["system_id"])
    cylinder = X.get_cylinder(api, env["cyl1_id"])
    store = X.get_store(api, env["store_id"])

    assert_system_charge(
        system, current_charge_lbs=80.0, leak_rate_pct=0.0, exceedance_count_12mo=0
    )
    assert_mass(cylinder["current_contents_lbs"], 40.0, "current_contents_lbs")
    assert_mass(store["vented_loss_lbs"], 0.0, "vented_loss_lbs")
    assert_mass_conserved([system], [cylinder], store, 120.0)
    assert_mass(cylinder["shipped_for_reclaim_lbs"], 0.0, "shipped_for_reclaim_lbs")

    assert system["version"] == env["version_before"] + 2
    assert_instant(
        X.get_service_record(api, env["record_id"])["retention_until"],
        "2029-08-01T00:00:00Z",
        "retention_until",
    )


# ─── the statutory 30-day extension budget ────────────────────────────


def _twenty_days_granted(api):
    """
    A manually declared event whose repair deadline opens 30 days out, carrying one
    approved 20-day grant that pushed the deadline to 2026-09-20.
    """
    env = X.manual_event_env(api)
    env["event_at_open"] = X.get_leak_event(api, env["event_id"])
    er1 = X.file_extension_request(api, env["event_id"])
    env["er1_id"] = er1["id"]
    env["er1_at_filing"] = er1
    env["er1_decided"] = X.approve_extension_request(api, er1["id"], 20)
    return env


def test_approved_grant_spends_twenty_of_the_thirty_day_budget(api):
    """
    The budget starts whole and the grant spends exactly 20 of it; the request
    records the deadline it moved away from.

    Design: Difficulty/compensating_invariant/revoking_extension_restores_thirty_day_budget_and_original_deadline
    """
    env = _twenty_days_granted(api)

    assert_extension_budget(env["event_at_open"], granted_total=0, remaining=30)
    assert_instant(
        env["er1_at_filing"]["expires_at"], "2026-08-16T00:00:00Z", "expires_at"
    )
    assert_instant(
        env["er1_at_filing"]["deadline_before"],
        "2026-08-31T00:00:00Z",
        "deadline_before",
    )

    assert env["er1_decided"]["status"] == EXTENSION_APPROVED
    assert env["er1_decided"]["granted_days"] == 20
    assert_instant(
        env["er1_decided"]["deadline_after"], "2026-09-20T00:00:00Z", "deadline_after"
    )
    assert_extension_budget(
        X.get_leak_event(api, env["event_id"]), granted_total=20, remaining=10
    )


def test_revoking_the_grant_restores_the_budget_and_the_original_deadline(api):
    """
    The revocation puts the whole budget back and the repair deadline lands on the
    exact instant the request recorded as `deadline_before`, recomputed rather than
    counted back from today; the request keeps its grant as history.

    Design: Difficulty/compensating_invariant/revoking_extension_restores_thirty_day_budget_and_original_deadline
    """
    env = _twenty_days_granted(api)

    revoked = validate_success(
        api.revoke_extension_request(
            env["er1_id"], F.extension_revocation_payload(), REGULATOR_HEADERS
        )
    )
    assert revoked["status"] == EXTENSION_REVOKED
    assert_instant(revoked["revoked_at"], "2026-08-01T00:00:00Z", "revoked_at")
    assert revoked["revocation_reason_code"] == "JUSTIFICATION_WITHDRAWN"
    assert revoked["granted_days"] == 20
    assert_instant(
        revoked["deadline_after"], "2026-09-20T00:00:00Z", "deadline_after"
    )

    event = X.get_leak_event(api, env["event_id"])
    assert_extension_budget(event, granted_total=0, remaining=30)
    assert_leak_event_schedule(
        event,
        initial_repair_deadline="2026-08-31T00:00:00Z",
        repair_deadline="2026-08-31T00:00:00Z",
    )
    assert_instant(
        event["repair_deadline"],
        env["er1_at_filing"]["deadline_before"],
        "repair_deadline restored to deadline_before",
    )
    assert event["status"] == EVENT_OPEN
