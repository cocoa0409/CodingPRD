"""One checklist completion breaks two rules at once.

The named performer is attached to nothing on the case, which the refusal
ladder places at priority 12 and answers with HTTP 422, while the supplied
completion instant sits in the future, which the ladder places at priority 14.1
and answers with HTTP 400. The attachment refusal must win.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_hemorrhage_bundle,
    assert_bundle_activation,
    assert_checklist_item,
    assert_instant_equals,
    assert_obstetric_unit,
    add_staff,
    bootstrap_unit,
    checklist_items_by_code,
    create_active_shift,
    create_encounter,
    get_success_data,
    minutes_between,
    read_clock,
    set_clock,
)

ACTIVATION_INSTANT = "2026-08-14T09:00:00Z"
CLOCK_NOW = "2026-08-14T09:05:00Z"
FUTURE_COMPLETED_AT = "2026-08-14T09:40:00Z"
SHIFT_START = "2026-08-14T08:00:00Z"
SHIFT_END = "2026-08-14T18:00:00Z"

LADDER_STAFF = {
    "charge": {
        "full_name": "Wilhelmina Strachan RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-09-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def unattached_performer_with_a_future_timestamp():
    """A gate-1 hemorrhage item completed by a clinician who is on no roster,
    with a completion instant 35 minutes past the clock."""
    set_clock(ACTIVATION_INSTANT)
    world = bootstrap_unit(
        clock=None,
        ldr_beds=2,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=LADDER_STAFF,
        unit_overrides={"unit_name": "Ashcombe Regional Birthing Suite"},
    )
    add_staff(
        world,
        "unattached",
        full_name="Ottoline Farraday RN",
        staff_role="RN_LABOR_DELIVERY",
        fetal_monitoring_cert_level="ADVANCED",
        credential_expires_at="2027-09-30T00:00:00Z",
        or_circulating_qualified=False,
    )
    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)

    encounter = create_encounter(
        world,
        acting_key="charge",
        patient_record_code="PRC-LADDER-4501",
        parity=1,
        gestational_age_weeks=40,
        prior_cesarean=False,
        fetus_count=1,
        presentation="VERTEX",
    )
    activation = activate_hemorrhage_bundle(
        world, encounter, acting_key="charge", quantitative_blood_loss_ml=1400
    )
    qbl_item = checklist_items_by_code(world, activation, acting_key="charge")["QBL_MEASURE"]

    set_clock(CLOCK_NOW)
    response = api_client.complete_checklist_item(
        activation["id"],
        qbl_item["id"],
        {
            "completed_at": FUTURE_COMPLETED_AT,
            "performed_by_staff_id": world.staff_id("unattached"),
        },
        world.charge_headers,
    )
    return {
        "world": world,
        "encounter": encounter,
        "activation": activation,
        "qbl_item": qbl_item,
        "response": response,
    }


def test_the_attachment_band_outranks_the_timestamp_band(
    unattached_performer_with_a_future_timestamp,
):
    """"A checklist completion whose performer is not attached to the case and
    whose `completed_at` also precedes the activation instant fails at 12 with
    `ERR_PERFORMER_NOT_ON_CASE` and HTTP 422, not at 14.1 with
    `ERR_CHECKLIST_TIMESTAMP_OUT_OF_RANGE`."

    Design: Difficulty/priority_pair_validation_conflict/unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete
    """
    response = unattached_performer_with_a_future_timestamp["response"]
    validate_error(response, ApiErrorId.ERR_PERFORMER_NOT_ON_CASE.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_CHECKLIST_TIMESTAMP_OUT_OF_RANGE.value
    )


def test_the_performer_is_attached_to_nothing_on_the_unit(
    unattached_performer_with_a_future_timestamp,
):
    """"The named performer must hold an `ACTIVE` care assignment on the
    encounter, or an `ACTIVE` roster entry on the unit in the `CHARGE` or
    `OR_STANDBY` slot, refused otherwise with `ERR_PERFORMER_NOT_ON_CASE`." She
    holds neither, so the priority-12 half of the pair is genuinely violated.

    Design: Difficulty/priority_pair_validation_conflict/unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete
    """
    world = unattached_performer_with_a_future_timestamp["world"]
    performer_id = world.staff_id("unattached")
    shifts = api_client.list_shifts(
        world.charge_headers, params={"staff_id": performer_id, "limit": 100}
    ).json()["data"]
    assert shifts == []
    rows = api_client.list_care_assignments(
        world.charge_headers, params={"staff_id": performer_id, "limit": 100}
    ).json()["data"]
    assert rows == []


def test_the_completion_instant_is_genuinely_in_the_future(
    unattached_performer_with_a_future_timestamp,
):
    """"`completed_at` must be at or after `activated_at` and at or before the
    current instant, refused otherwise with
    `ERR_CHECKLIST_TIMESTAMP_OUT_OF_RANGE`." The supplied instant is 35 minutes
    past the clock, so the priority-14.1 half is genuinely violated too.

    Design: Difficulty/priority_pair_validation_conflict/unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete
    """
    setup = unattached_performer_with_a_future_timestamp
    assert_instant_equals(read_clock()["current_utc"], CLOCK_NOW, "current_utc")
    assert_instant_equals(
        setup["activation"]["activated_at"], ACTIVATION_INSTANT, "activated_at"
    )
    assert minutes_between(CLOCK_NOW, FUTURE_COMPLETED_AT) == 35


def test_the_item_is_left_exactly_as_it_was_minted(
    unattached_performer_with_a_future_timestamp,
):
    """"Every item opens `PENDING` with `completed_at`, `performed_by_staff_id`
    and `minutes_from_activation` null." A refused completion writes none of the
    three and does not move the row's version.

    Design: Difficulty/priority_pair_validation_conflict/unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete
    """
    setup = unattached_performer_with_a_future_timestamp
    world = setup["world"]
    item = get_success_data(
        api_client.get_checklist_item(
            setup["activation"]["id"], setup["qbl_item"]["id"], world.charge_headers
        )
    )
    assert_checklist_item(item)
    assert item["step_code"] == "QBL_MEASURE"
    assert item["status"] == "PENDING"
    assert item["completed_at"] is None
    assert item["performed_by_staff_id"] is None
    assert item["minutes_from_activation"] is None
    assert item["version"] == 1


def test_the_activation_never_left_activated(
    unattached_performer_with_a_future_timestamp,
):
    """"The first completion of a gate-1 item also moves the activation from
    `ACTIVATED` to `STAGE_1_IN_PROGRESS`" — so a refused completion must leave
    the activation on its opening counters with both scores still null.

    Design: Difficulty/priority_pair_validation_conflict/unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete
    """
    setup = unattached_performer_with_a_future_timestamp
    activation = get_success_data(
        api_client.get_activation(
            setup["activation"]["id"], setup["world"].charge_headers
        )
    )
    assert_bundle_activation(activation)
    assert activation["status"] == "ACTIVATED"
    assert activation["highest_stage_reached"] == 0
    assert activation["on_time_step_count"] == 0
    assert activation["late_step_count"] == 0
    assert activation["missed_step_count"] == 0
    assert activation["timeliness_score"] is None
    assert activation["sequence_adjusted_score"] is None
    assert activation["version"] == 1


def test_the_unit_records_no_bundle_breach(
    unattached_performer_with_a_future_timestamp,
):
    """A unit opens with "`escalation_breach_count` and `bundle_breach_count` at
    0", and only a controlled activation carrying a missed step increments the
    latter, so a refusal leaves the counter alone.

    Design: Difficulty/priority_pair_validation_conflict/unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete
    """
    unit = unattached_performer_with_a_future_timestamp["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["bundle_breach_count"] == 0


def test_the_gate_one_row_was_completable_all_along(
    unattached_performer_with_a_future_timestamp,
):
    """"The activation's `highest_stage_reached` must be at least the item's `stage_gate`,
    refused otherwise with `ERR_CHECKLIST_STAGE_NOT_REACHED` — with the deliberate
    exception that a gate-1 item may be completed while the activation is still
    `ACTIVATED`, since that first completion is what moves the activation forward." — so the stage gate was never the obstacle, and repairing only the
    performer and the instant lets the very same row through.

    Design: Difficulty/priority_pair_validation_conflict/unattached_performer_at_12_outranks_future_dated_completed_at_at_14_1_on_checklist_complete
    """
    setup = unattached_performer_with_a_future_timestamp
    world = setup["world"]
    item = get_success_data(
        api_client.complete_checklist_item(
            setup["activation"]["id"],
            setup["qbl_item"]["id"],
            {
                "completed_at": CLOCK_NOW,
                "performed_by_staff_id": world.staff_id("charge"),
            },
            world.charge_headers,
        )
    )
    assert item["status"] == "COMPLETED"
    assert item["minutes_from_activation"] == 5
    activation = get_success_data(
        api_client.get_activation(setup["activation"]["id"], world.charge_headers)
    )
    assert activation["status"] == "STAGE_1_IN_PROGRESS"
    assert activation["on_time_step_count"] == 1
