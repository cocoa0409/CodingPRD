"""
Read-after-write consistency: every derived value is already settled in the very
response that caused it, and the compliance sweep is for deadlines only.
"""

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_leak_event_schedule,
    assert_mass,
    assert_penalty_exposure,
    assert_store_posture,
    assert_system_axes,
    assert_system_charge,
    assert_sweep_report,
)
from test_helpers.types import (
    APPLICABILITY_REGULATED,
    CERT_TYPE_II,
    EQUIPMENT_CERTIFIED,
    EVENT_OPEN,
    POSTURE_AT_RISK,
    STATE_LEAK_OPEN,
)


def test_every_derived_value_is_settled_in_the_response_that_caused_it(api):
    """
    Nothing in this system is settled lazily. The system create response already
    classifies the rack, the record response already carries the recomputed leak
    rate and the retention horizon, the store already counts the event, the
    inspection is already priced against the posture that write produced — and a
    compliance run immediately afterwards recomputes nothing at all.

    Design: Corner/consistency_model/every_derived_value_is_already_settled_in_the_response_that_caused_it
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    technician = X.create_second_technician(
        api, full_name="Marek Olsen", certification_expires_on="2027-12-31T00:00:00Z"
    )
    cylinder = X.create_cylinder(api, store["id"], rt404["id"])

    system = X.create_system(api, store["id"], rt404["id"])
    assert system["applicability"] == APPLICABILITY_REGULATED
    assert system["required_certification_type"] == CERT_TYPE_II
    assert_mass(system["threshold_pct"], 20.0, "threshold_pct")
    assert_system_charge(system, current_charge_lbs=80.0)
    assert system["version"] == 1

    assert_store_posture(
        X.get_store(api, store["id"]),
        regulated_system_count=1,
        total_regulated_charge_lbs=100.0,
    )

    equipment = X.create_equipment(api, store["id"], technician["id"])
    assert equipment["status"] == EQUIPMENT_CERTIFIED

    record = X.file_service_record(
        api,
        system["id"],
        technician["id"],
        equipment["id"],
        system["version"],
        cylinder_id=cylinder["id"],
        refrigerant_added_lbs=20.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=60,
    )
    assert_mass(record["leak_rate_pct_after"], 20.0, "leak_rate_pct_after")
    assert_mass(record["system_charge_after_lbs"], 100.0, "system_charge_after_lbs")
    assert_instant(record["retention_until"], "2029-08-01T00:00:00Z", "retention_until")

    triggered = X.list_leak_events(api, triggering_service_record_id=record["id"])
    assert triggered["meta"]["total_count"] == 1
    event = triggered["data"][0]
    assert event["status"] == EVENT_OPEN
    assert_leak_event_schedule(event, repair_deadline="2026-08-31T00:00:00Z")

    settled_system = X.get_system(api, system["id"])
    assert_system_charge(settled_system, current_charge_lbs=100.0, leak_rate_pct=20.0)
    assert_system_axes(settled_system, compliance_state=STATE_LEAK_OPEN)

    assert_store_posture(
        X.get_store(api, store["id"]),
        compliance_status=POSTURE_AT_RISK,
        open_leak_event_count=1,
    )

    # 275.55 base exposure at the AT_RISK multiplier: 275.55 x 1.25 = 344.4375,
    # rounded half-up to 344.44 in the create response itself.
    inspection = X.open_inspection(
        api,
        store["id"],
        citations=[F.citation("608-LEAK-REC")],
        inspector_name="Inspector Vale",
    )
    assert_penalty_exposure(
        inspection, penalty_exposure_usd=344.44, chronic_multiplier_applied=1.25
    )
    assert_store_posture(
        X.get_store(api, store["id"]), penalty_exposure_total_usd=344.44
    )

    report = X.run_sweep(api)
    assert_sweep_report(
        report,
        repair_overdue=[],
        verification_overdue=[],
        expired_extensions=[],
        overdue_equipment=[],
        escalated_inspections=[],
        stores_recomputed_count=0,
        as_of="2026-08-01T00:00:00Z",
    )

    after_sweep_system = X.get_system(api, system["id"])
    assert_system_charge(after_sweep_system, current_charge_lbs=100.0, leak_rate_pct=20.0)
    assert_system_axes(after_sweep_system, compliance_state=STATE_LEAK_OPEN)
    assert after_sweep_system["version"] == settled_system["version"]

    assert_store_posture(
        X.get_store(api, store["id"]),
        compliance_status=POSTURE_AT_RISK,
        open_leak_event_count=1,
        regulated_system_count=1,
        total_regulated_charge_lbs=100.0,
        penalty_exposure_total_usd=344.44,
    )
    assert X.get_leak_event(api, event["id"])["status"] == EVENT_OPEN
    assert_penalty_exposure(
        X.get_inspection(api, inspection["id"]),
        penalty_exposure_usd=344.44,
        chronic_multiplier_applied=1.25,
    )
