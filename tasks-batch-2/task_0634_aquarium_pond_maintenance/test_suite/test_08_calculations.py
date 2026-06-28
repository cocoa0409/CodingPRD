"""Calculation corner cases: dosing boundary and precision, bioload input-set
filtering, and the media-due-date schedule.
"""
from datetime import date, timedelta

from test_helpers import (
    validate_success,
    make_field_tech_headers,
    create_started_visit,
    create_equipment_on_system,
    TEST_USERS,
)
from test_helpers.fixtures import create_contract, create_system, create_technician
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_dose_at_or_above_target_is_zero(api):
    """PRD §3.5: "When the measured_value is at or above the target_value, the
    recommended dose is exactly 0.0 — a reading exactly at target doses nothing,
    not a sliver."

    Design: Corner/calculations/dose_at_or_above_target_is_zero
    """
    base = create_started_visit(service_tier="BASIC", tech_user_id="tech-1",
                                nominal_volume_l=200, substrate_displacement_pct=0.10,
                                scheduled_start="2026-02-27T09:00:00Z",
                                scheduled_end="2026-02-27T10:00:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    data = validate_success(api.create_water_test(
        base["visit"]["id"],
        f.create_water_test_payload(parameter="ALKALINITY", measured_value=8.0,
                                    target_value=8.0, product_strength_ppm_per_ml=50),
        tech_headers), expected_status=201)
    assert data["recommended_dose_ml"] == 0.0, (
        f"Expected dose 0.0 at-or-above target, got {data['recommended_dose_ml']}")


def test_dose_below_target_rounds_up_to_tenth_ml(api):
    """PRD §3.5: "Otherwise the raw dose is the difference between target and
    measured, multiplied by the system's effective volume (its nominal_volume_l
    times one minus its substrate_displacement_pct), divided by
    product_strength_ppm_per_ml; this raw millilitre figure is then rounded up to
    the next 0.1 mL so the system never under-doses."

    200 L @0.10 -> eff 180; (8-5)*180/50 = 10.8 -> 10.8.

    Design: Corner/calculations/dose_below_target_rounds_up_to_tenth_ml
    """
    base = create_started_visit(service_tier="BASIC", tech_user_id="tech-1",
                                nominal_volume_l=200, substrate_displacement_pct=0.10,
                                scheduled_start="2026-02-28T09:00:00Z",
                                scheduled_end="2026-02-28T10:00:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    data = validate_success(api.create_water_test(
        base["visit"]["id"],
        f.create_water_test_payload(parameter="ALKALINITY", measured_value=5.0,
                                    target_value=8.0, product_strength_ppm_per_ml=50),
        tech_headers), expected_status=201)
    assert data["recommended_dose_ml"] == 10.8, (
        f"Expected dose 10.8, got {data['recommended_dose_ml']}")


def test_bioload_excludes_quarantined_livestock(api):
    """PRD §2.9: "The bioload is the sum, over every Livestock on the system whose
    status is ALIVE, of that animal's adult_length_cm multiplied by the waste
    factor for its species_class; animals that are QUARANTINED or DECEASED are
    excluded entirely. ... The waste factor is ... 2.0 for GOLDFISH".

    Two GOLDFISH 10cm + 8cm on 200 L @0.10 (eff 180): (20+16)/180*100 = 20.0.
    After quarantining the 10cm fish only the 8cm remains: 16/180*100 = 8.89.

    Design: Corner/calculations/bioload_excludes_quarantined_and_deceased
    """
    create_technician(tech_user_id="tech-1")
    contract = create_contract(customer_user_id="owner-1")
    home = create_system(contract["id"], system_kind="FRESHWATER",
                         nominal_volume_l=200, label="Home",
                         substrate_displacement_pct=0.10)
    qt = create_system(contract["id"], system_kind="FRESHWATER",
                       nominal_volume_l=80, label="QT")
    validate_success(api.activate_contract(contract["id"], AM))
    validate_success(api.commission_system(home["id"], AM))
    qt = validate_success(api.commission_system(qt["id"], AM))
    tech_headers = make_field_tech_headers("tech-1")

    f1 = validate_success(api.create_livestock(
        f.create_livestock_payload(home["id"], common_name="G1",
                                   species_class="GOLDFISH", adult_length_cm=10),
        tech_headers), expected_status=201)
    validate_success(api.create_livestock(
        f.create_livestock_payload(home["id"], common_name="G2",
                                   species_class="GOLDFISH", adult_length_cm=8),
        tech_headers), expected_status=201)

    before = validate_success(api.get_system(home["id"], tech_headers))
    assert before["bioload_index"] == 20.0, (
        f"Expected bioload 20.0 with both alive, got {before['bioload_index']}")

    validate_success(api.create_quarantine(
        f.create_quarantine_payload(f1["id"], qt["id"], qt["version"],
                                    window_start="2026-03-01T00:00:00Z",
                                    window_end="2026-03-03T00:00:00Z"),
        tech_headers), expected_status=201)

    after = validate_success(api.get_system(home["id"], tech_headers))
    assert after["bioload_index"] == 8.89, (
        f"Expected bioload 8.89 after quarantining G1, got {after['bioload_index']}")


def test_media_due_on_computed_from_system_creation_date(api):
    """PRD §3.2: "The due date is computed by taking the base date —
    last_serviced_on when it is set, otherwise the date component of the owning
    SystemProfile's creation date — and adding media_interval_days whole days to
    it. At registration, because the device has never been serviced, media_due_on
    is computed from the system's creation date plus the interval."
    PRD §3.11: "The clock starts at 2026-01-01T00:00:00Z at server startup".

    Default clock -> system created 2026-01-01; 30-day FILTER -> due 2026-01-31.

    Design: Corner/calculations/media_due_on_computed_from_interval
    """
    base = create_equipment_on_system(customer_user_id="owner-1", device_kind="FILTER",
                                       media_interval_days=30)
    system = base["system"]
    equipment = base["equipment"]
    base_date = date.fromisoformat(system["created_at"][:10])
    expected_due = (base_date + timedelta(days=30)).isoformat()
    assert equipment["media_due_on"][:10] == expected_due, (
        f"Expected media_due_on {expected_due}, got {equipment['media_due_on']}")


def test_media_schedule_advances_on_serviced_visit(api):
    """PRD §3.3: "For each device named in serviced_equipment_ids, that
    Equipment's last_serviced_on is set to the visit's completion date and its
    media_due_on is recomputed from the new base date."
    PRD §3.2: "the base date — last_serviced_on when it is set ... and adding
    media_interval_days whole days to it."

    Clock at 2026-04-01; completing a visit listing the FILTER sets
    last_serviced_on 2026-04-01 and media_due_on 2026-05-01.

    Design: Corner/calculations/media_schedule_advances_on_serviced_visit
    """
    tech = create_technician(tech_user_id="tech-1")
    contract = create_contract(customer_user_id="owner-1")
    system = create_system(contract["id"], nominal_volume_l=200)
    equipment = validate_success(api.create_equipment(
        f.create_equipment_payload(system["id"], device_kind="FILTER",
                                   media_interval_days=30),
        AM), expected_status=201)
    validate_success(api.activate_contract(contract["id"], AM))
    system = validate_success(api.commission_system(system["id"], AM))
    validate_success(api.set_clock("2026-04-01T00:00:00Z", AM))

    visit = validate_success(api.create_visit(
        f.create_visit_payload(system["id"], tech["id"], system["version"],
                               scheduled_start="2026-04-01T09:00:00Z",
                               scheduled_end="2026-04-01T10:00:00Z"),
        DISP), expected_status=201)
    tech_headers = make_field_tech_headers("tech-1")
    validate_success(api.start_visit(visit["id"], tech_headers))
    validate_success(api.complete_visit(
        visit["id"], {"labor_minutes": 30, "serviced_equipment_ids": [equipment["id"]]},
        tech_headers))

    eq = validate_success(api.get_equipment(equipment["id"], tech_headers))
    assert eq["last_serviced_on"][:10] == "2026-04-01", (
        f"Expected last_serviced_on 2026-04-01, got {eq['last_serviced_on']}")
    assert eq["media_due_on"][:10] == "2026-05-01", (
        f"Expected media_due_on 2026-05-01, got {eq['media_due_on']}")
