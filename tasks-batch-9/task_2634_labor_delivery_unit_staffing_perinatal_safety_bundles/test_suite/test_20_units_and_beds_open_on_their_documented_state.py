"""What a unit and a bed look like the instant they are created.

Every derived counter on a new unit sits at its documented zero, the induction
budget defaults to a concrete literal, the only editable field is the budget, a
new bed carries three null occupancy pointers, beds list in label order rather
than creation order, and a bed cannot be hung under a unit that does not exist.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_instant_is_null,
    assert_obstetric_unit,
    BOOTSTRAP_OFFICER_HEADERS,
    DEFAULT_MAX_DAILY_INDUCTION_BED_MINUTES,
    create_bed,
    create_unit,
    get_success_data,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
UNKNOWN_UNIT_ID = "00000000-0000-4000-8000-000000000002"


def test_a_new_unit_opens_with_every_counter_at_zero():
    """"A newly created unit opens with `staffing_posture` at `OPEN`,
    `coverage_deficit_units` at 0, `cesarean_readiness_state` at `NOT_READY` because
    no drill has yet been validated, `escalation_breach_count` and
    `bundle_breach_count` at 0, `turnover_buffer_minutes` at 45, both of its
    bed-minute ledgers — `committed_bed_minutes_by_day` and
    `held_bed_minutes_by_day`, each a map keyed by UTC calendar date — empty, and
    `last_capacity_sweep_at` null."

    Design: Corner/entities/obstetric_unit_creation_echoes_declared_inputs_with_zeroed_breach_counters
    """
    set_clock(CLOCK_START)
    unit = get_success_data(
        api_client.create_unit(
            {
                "unit_name": "Larkspur Perinatal Center LDR",
                "licensed_ldr_beds": 6,
                "licensed_or_rooms": 2,
                "max_daily_induction_bed_minutes": 4320,
            },
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )
    assert_obstetric_unit(unit)
    assert unit["unit_name"] == "Larkspur Perinatal Center LDR"
    assert unit["licensed_ldr_beds"] == 6
    assert unit["licensed_or_rooms"] == 2
    assert unit["max_daily_induction_bed_minutes"] == 4320
    assert unit["staffing_posture"] == "OPEN"
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["escalation_breach_count"] == 0
    assert unit["bundle_breach_count"] == 0
    assert unit["turnover_buffer_minutes"] == 45
    assert unit["committed_bed_minutes_by_day"] == {}
    assert unit["held_bed_minutes_by_day"] == {}
    assert_instant_is_null(unit["last_capacity_sweep_at"], "last_capacity_sweep_at")
    assert unit["version"] == 1


def test_the_induction_budget_defaults_to_two_thousand_eight_hundred_and_eighty():
    """"`max_daily_induction_bed_minutes` is an integer no smaller than 0 and
    defaults to 2880 when omitted — two full bed-days of induction time per
    calendar day, which is the quota the whole scheduling half of this product
    spends."

    Design: Corner/entities/omitting_max_daily_induction_bed_minutes_applies_the_2880_default
    """
    set_clock(CLOCK_START)
    unit = get_success_data(
        api_client.create_unit(
            {
                "unit_name": "Marigold Womens Pavilion LDR",
                "licensed_ldr_beds": 4,
                "licensed_or_rooms": 1,
            },
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )
    assert_obstetric_unit(unit)
    assert unit["max_daily_induction_bed_minutes"] == (
        DEFAULT_MAX_DAILY_INDUCTION_BED_MINUTES
    )
    assert unit["max_daily_induction_bed_minutes"] == 2880
    assert unit["licensed_ldr_beds"] == 4
    assert unit["licensed_or_rooms"] == 1
    assert unit["version"] == 1


def test_only_the_budget_is_editable_after_creation():
    """"Only `max_daily_induction_bed_minutes` may later be adjusted, by the same role; the
    name, the licensed counts and every derived field are immutable through that
    path, and although raising or lowering the budget never moves the posture by
    itself, it immediately changes the outcome of the priority-15 capacity test."

    Design: Corner/entities/patching_the_induction_budget_leaves_unit_name_and_licensed_counts_untouched
    """
    set_clock(CLOCK_START)
    unit = create_unit(
        unit_name="Willowmere Perinatal LDR",
        licensed_ldr_beds=4,
        licensed_or_rooms=1,
    )
    assert unit["version"] == 1
    patched = get_success_data(
        api_client.patch_unit(
            unit["id"],
            {"max_daily_induction_bed_minutes": 5760},
            BOOTSTRAP_OFFICER_HEADERS,
        )
    )
    assert_obstetric_unit(patched)
    assert patched["max_daily_induction_bed_minutes"] == 5760
    assert patched["unit_name"] == "Willowmere Perinatal LDR"
    assert patched["licensed_ldr_beds"] == 4
    assert patched["licensed_or_rooms"] == 1
    assert patched["version"] == 2


def test_a_new_bed_carries_three_null_occupancy_pointers():
    """"A bed opens at `AVAILABLE` and moves through `HELD`, `OCCUPIED`,
    `TURNOVER`, `BLOCKED` and finally `CLOSED`, carrying `current_encounter_id`
    while a patient is in it, `held_booking_id` while a booking reserves it, and
    `turnover_clear_at` while it is being cleaned."

    Design: Corner/entities/retrieving_a_freshly_created_bed_returns_available_with_null_occupancy_pointers
    """
    set_clock(CLOCK_START)
    unit = create_unit(
        unit_name="Bluebell Family Birth LDR",
        licensed_ldr_beds=4,
        licensed_or_rooms=1,
    )
    created = create_bed(unit["id"], "LDR-07", "LDR")
    bed = get_success_data(api_client.get_bed(created["id"], BOOTSTRAP_OFFICER_HEADERS))
    assert_bed(bed)
    assert bed["bed_label"] == "LDR-07"
    assert bed["bed_type"] == "LDR"
    assert bed["status"] == "AVAILABLE"
    assert bed["unit_id"] == unit["id"]
    assert bed["current_encounter_id"] is None
    assert bed["held_booking_id"] is None
    assert_instant_is_null(bed["turnover_clear_at"], "turnover_clear_at")
    assert bed["version"] == 1


def test_beds_page_in_label_order_rather_than_creation_order():
    """"Beds may be listed within a unit ordered by `bed_label` ascending — the same
    lexicographic order the capacity sweep uses when it chooses among candidate beds
    — or across units through a flat collection filtered by `unit_id`, `bed_type`,
    `status`, `current_encounter_id` and `held_booking_id`, which is the only way to
    discover the bed a cascade attached to a particular encounter or booking."

    Design: Corner/entities/bed_listing_pages_in_bed_label_order_not_creation_order
    """
    set_clock(CLOCK_START)
    unit = create_unit(
        unit_name="Juniper Ridge Obstetrics LDR",
        licensed_ldr_beds=6,
        licensed_or_rooms=1,
    )
    for label in ("LDR-03", "LDR-01", "LDR-02"):
        create_bed(unit["id"], label, "LDR")
    first = api_client.list_unit_beds(
        unit["id"], BOOTSTRAP_OFFICER_HEADERS, params={"limit": 2, "offset": 0}
    ).json()
    second = api_client.list_unit_beds(
        unit["id"], BOOTSTRAP_OFFICER_HEADERS, params={"limit": 2, "offset": 2}
    ).json()
    assert [row["bed_label"] for row in first["data"]] == ["LDR-01", "LDR-02"]
    assert [row["bed_label"] for row in second["data"]] == ["LDR-03"]
    assert first["meta"]["total_count"] == 3
    assert first["meta"]["has_more"] is True
    assert second["meta"]["has_more"] is False


def test_a_bed_cannot_be_hung_under_a_unit_that_does_not_exist():
    """"**Priority 3** — existence of every identifier taken from the request
    path, on every operation that carries one, resolved strictly left to right so
    that a unit identifier is resolved before a bed or snapshot identifier in the
    same path" — so the parent check precedes the duplicate-label check.

    Design: Corner/entities/creating_a_bed_under_an_unknown_parent_unit_returns_unit_not_found
    """
    set_clock(CLOCK_START)
    unit = create_unit(
        unit_name="Alderbrook Birthing Suites LDR",
        licensed_ldr_beds=4,
        licensed_or_rooms=1,
    )
    real_bed = create_bed(unit["id"], "LDR-01", "LDR")
    response = api_client.create_bed(
        UNKNOWN_UNIT_ID,
        {"bed_label": "LDR-01", "bed_type": "LDR"},
        BOOTSTRAP_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_UNIT_NOT_FOUND.value, 404)
    rows = api_client.list_unit_beds(
        unit["id"], BOOTSTRAP_OFFICER_HEADERS, params={"limit": 10}
    ).json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == real_bed["id"]
    assert rows[0]["unit_id"] == unit["id"]
