"""A two-deep path and an array of foreign keys, both of which must be all or nothing.

The nested checklist read has to resolve its parent before its leaf and has to
refuse a real item that belongs to someone else's activation. The drill roster is
the one array of references in the system: its cardinality is a shape rule, its
members are looked up before they are scoped, and none of the three refusals may
leave a scheduled drill behind.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_checklist_item,
    assert_drill,
    assert_obstetric_unit,
    assert_instant_is_null,
    assert_staff_member,
    activate_hemorrhage_bundle,
    bootstrap_unit,
    checklist_items_by_code,
    create_encounter,
    create_staff_member,
    create_unit,
    get_success_data,
)

CLOCK_START = "2026-08-01T06:00:00Z"
DRILL_SCHEDULED_FOR = "2026-08-01T07:00:00Z"
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
UNKNOWN_ACTIVATION_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_ITEM_ID = "00000000-0000-4000-8000-0000000000bb"
UNKNOWN_STAFF_ID = "00000000-0000-4000-8000-0000000000cc"
HEMORRHAGE_ITEM_COUNT = 4

NEST_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Priya Raman MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
}

DRILL_STAFF = {
    "charge": {
        "full_name": "Dana Alvarez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Priya Raman MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "anesthesia": {
        "full_name": "Tomas Ek MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
}


@pytest.fixture
def two_hemorrhage_checklists_side_by_side():
    """Two patients, two activations, two disjoint four-item checklists, read four ways."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=NEST_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    first_patient = create_encounter(
        world,
        patient_record_code="PRC-NEST-0001",
        parity=1,
        gestational_age_weeks=39,
    )
    second_patient = create_encounter(
        world,
        patient_record_code="PRC-NEST-0002",
        parity=2,
        gestational_age_weeks=40,
    )
    first_activation = activate_hemorrhage_bundle(
        world,
        first_patient,
        activation_trigger="QBL_THRESHOLD",
        quantitative_blood_loss_ml=1200,
    )
    second_activation = activate_hemorrhage_bundle(
        world,
        second_patient,
        activation_trigger="QBL_THRESHOLD",
        quantitative_blood_loss_ml=1500,
    )
    first_item = checklist_items_by_code(world, first_activation)["QBL_MEASURE"]
    foreign_item = checklist_items_by_code(world, second_activation)["QBL_MEASURE"]
    both_bogus = api_client.get_checklist_item(
        UNKNOWN_ACTIVATION_ID, UNKNOWN_ITEM_ID, world.charge_headers
    )
    bogus_leaf = api_client.get_checklist_item(
        first_activation["id"], UNKNOWN_ITEM_ID, world.charge_headers
    )
    someone_elses_item = api_client.get_checklist_item(
        first_activation["id"], foreign_item["id"], world.charge_headers
    )
    own_item = api_client.get_checklist_item(
        first_activation["id"], first_item["id"], world.charge_headers
    )
    return {
        "world": world,
        "first_activation": first_activation,
        "second_activation": second_activation,
        "first_item": first_item,
        "foreign_item": foreign_item,
        "both_bogus": both_bogus,
        "bogus_leaf": bogus_leaf,
        "someone_elses_item": someone_elses_item,
        "own_item": own_item,
    }


def test_the_parent_of_the_path_is_resolved_before_the_leaf(
    two_hemorrhage_checklists_side_by_side,
):
    """"**Priority 3** — existence of every identifier taken from the request path, on
    every operation that carries one, resolved strictly left to right so that a unit
    identifier is resolved before a bed or snapshot identifier in the same path and an
    activation identifier before a checklist item identifier; the fifteen possible
    outcomes are `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`, `ERR_CARE_ASSIGNMENT_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_ACTIVATION_NOT_FOUND`,
    `ERR_CHECKLIST_ITEM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
    `ERR_CESAREAN_EVENT_NOT_FOUND`, `ERR_DRILL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_PASS_NOT_FOUND` and `ERR_SNAPSHOT_NOT_FOUND`, each at HTTP 404."

    Design: Corner/endpoints/nested_checklist_item_path_validates_the_activation_before_the_item_and_refuses_a_foreign_item
    """
    setup = two_hemorrhage_checklists_side_by_side
    refused = setup["both_bogus"]
    validate_error(refused, ApiErrorId.ERR_ACTIVATION_NOT_FOUND.value, 404)
    assert (
        refused.json()["data"]["error_id"] != ApiErrorId.ERR_CHECKLIST_ITEM_NOT_FOUND.value
    )


def test_another_activations_item_is_not_found_under_this_one(
    two_hemorrhage_checklists_side_by_side,
):
    """"Activation also mints the checklist; items are never created by a client." The
    item is therefore addressable only underneath the activation that minted it.

    Design: Corner/endpoints/nested_checklist_item_path_validates_the_activation_before_the_item_and_refuses_a_foreign_item
    """
    setup = two_hemorrhage_checklists_side_by_side
    validate_error(
        setup["bogus_leaf"], ApiErrorId.ERR_CHECKLIST_ITEM_NOT_FOUND.value, 404
    )
    foreign = setup["someone_elses_item"]
    validate_error(foreign, ApiErrorId.ERR_CHECKLIST_ITEM_NOT_FOUND.value, 404)
    assert foreign.status_code != 200
    assert setup["foreign_item"]["activation_id"] == setup["second_activation"]["id"]


def test_the_activations_own_item_reads_back_untouched(
    two_hemorrhage_checklists_side_by_side,
):
    """"Every item opens `PENDING` with `completed_at`, `performed_by_staff_id` and
    `minutes_from_activation` null."

    Design: Corner/endpoints/nested_checklist_item_path_validates_the_activation_before_the_item_and_refuses_a_foreign_item
    """
    setup = two_hemorrhage_checklists_side_by_side
    assert setup["own_item"].status_code == 200
    item = get_success_data(setup["own_item"])
    assert_checklist_item(item)
    assert item["id"] == setup["first_item"]["id"]
    assert item["activation_id"] == setup["first_activation"]["id"]
    assert item["status"] == "PENDING"
    assert_instant_is_null(item["completed_at"], "completed_at")
    assert item["performed_by_staff_id"] is None
    assert item["minutes_from_activation"] is None


def test_each_checklist_holds_its_own_four_steps(
    two_hemorrhage_checklists_side_by_side,
):
    """"An `OBSTETRIC_HEMORRHAGE` bundle receives four items: `step_sequence` 1,
    `step_code` `QBL_MEASURE`, `stage_gate` 1, `required_within_minutes` 10; sequence 2,
    `UTEROTONIC_GIVEN`, gate 1, 15 minutes; sequence 3, `TYPE_AND_SCREEN`, gate 2, 20
    minutes; sequence 4, `MTP_ACTIVATED`, gate 3, 10 minutes."

    Design: Corner/endpoints/nested_checklist_item_path_validates_the_activation_before_the_item_and_refuses_a_foreign_item
    """
    setup = two_hemorrhage_checklists_side_by_side
    body = api_client.list_checklist_items(
        setup["first_activation"]["id"],
        setup["world"].charge_headers,
        params={"limit": 10, "offset": 0},
    ).json()
    assert body["meta"]["total_count"] == HEMORRHAGE_ITEM_COUNT
    assert len(body["data"]) == HEMORRHAGE_ITEM_COUNT
    by_sequence = {row["step_sequence"]: row for row in body["data"]}
    assert sorted(by_sequence) == [1, 2, 3, 4]
    for sequence, step_code, stage_gate, allowance in (
        (1, "QBL_MEASURE", 1, 10),
        (2, "UTEROTONIC_GIVEN", 1, 15),
        (3, "TYPE_AND_SCREEN", 2, 20),
        (4, "MTP_ACTIVATED", 3, 10),
    ):
        row = by_sequence[sequence]
        assert_checklist_item(row)
        assert row["step_code"] == step_code
        assert row["stage_gate"] == stage_gate
        assert row["required_within_minutes"] == allowance
        assert row["activation_id"] == setup["first_activation"]["id"]
    ids = [row["id"] for row in body["data"]]
    assert setup["foreign_item"]["id"] not in ids


@pytest.fixture
def three_rejected_drill_rosters_then_a_good_one():
    """A one-name roster, a roster holding a phantom and a neighbour, a roster holding
    only the neighbour, and finally the two names that belong here."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=DRILL_STAFF,
        unit_overrides={"unit_name": "Rowan Perinatal Center LDR"},
    )
    annex = create_unit(
        unit_name="Rowan Perinatal Center Annex",
        licensed_ldr_beds=2,
        licensed_or_rooms=1,
    )
    neighbour = create_staff_member(
        annex["id"],
        full_name="Rosa Lindqvist MD",
        staff_role="ANESTHESIOLOGIST",
        fetal_monitoring_cert_level="BASIC",
        credential_expires_at=LIVE_CREDENTIAL,
    )
    ours = world.staff_id("ob")
    also_ours = world.staff_id("anesthesia")

    def _schedule(participant_staff_ids):
        return api_client.create_drill(
            world.unit_id,
            {
                "drill_type": "DECISION_TO_INCISION",
                "scheduled_for_utc": DRILL_SCHEDULED_FOR,
                "participant_staff_ids": participant_staff_ids,
            },
            world.charge_headers,
        )

    too_few = _schedule([ours])
    phantom_and_neighbour = _schedule([ours, UNKNOWN_STAFF_ID, neighbour["id"]])
    neighbour_only = _schedule([ours, neighbour["id"]])
    after_the_refusals = api_client.list_unit_drills(
        world.unit_id, world.charge_headers, params={"limit": 10, "offset": 0}
    )
    accepted = _schedule([ours, also_ours])
    return {
        "world": world,
        "annex": annex,
        "neighbour": neighbour,
        "ours": ours,
        "also_ours": also_ours,
        "too_few": too_few,
        "phantom_and_neighbour": phantom_and_neighbour,
        "neighbour_only": neighbour_only,
        "after_the_refusals": after_the_refusals,
        "accepted": accepted,
    }


def test_a_one_name_roster_fails_the_cardinality_floor(
    three_rejected_drill_rosters_then_a_good_one,
):
    """"A `ChargeNurse` or `AnesthesiaLead` schedules a drill on a unit, naming a
    `drill_type` of `DECISION_TO_INCISION`, `HEMORRHAGE_STAGE_2` or `ECLAMPSIA` which is
    immutable, a `scheduled_for_utc` which must be at or after the current instant,
    refused otherwise with `ERR_DRILL_TIMESTAMP_OUT_OF_RANGE`, and
    `participant_staff_ids`, an array of 2 to 20 staff identifiers all belonging to that
    unit."

    Design: Corner/endpoints/drill_participant_roster_is_all_or_nothing_and_rejects_a_foreign_id_without_creating_the_drill
    """
    setup = three_rejected_drill_rosters_then_a_good_one
    validate_error(setup["too_few"], ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 400)


def test_a_phantom_member_is_reported_before_a_foreign_one(
    three_rejected_drill_rosters_then_a_good_one,
):
    """"**Priority 4** — existence of every identifier taken from the request body,
    resolved in the order the fields are declared for that operation, yielding
    `ERR_ENCOUNTER_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
    `ERR_BED_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ACTIVATION_NOT_FOUND` or
    `ERR_UNIT_NOT_FOUND` at HTTP 404."

    Design: Corner/endpoints/drill_participant_roster_is_all_or_nothing_and_rejects_a_foreign_id_without_creating_the_drill
    """
    setup = three_rejected_drill_rosters_then_a_good_one
    refused = setup["phantom_and_neighbour"]
    validate_error(refused, ApiErrorId.ERR_STAFF_NOT_FOUND.value, 404)
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value
    assert setup["neighbour"]["unit_id"] == setup["annex"]["id"]


def test_a_neighbours_anaesthetist_is_out_of_scope(
    three_rejected_drill_rosters_then_a_good_one,
):
    """"**Priority 7** — cross-aggregate scoping, meaning that every referenced record
    must belong to the same `ObstetricUnit` as the operation's subject:
    `ERR_CROSS_UNIT_REFERENCE` at HTTP 422, on care-assignment creation,
    shift-assignment creation, encounter bed attachment, cesarean team mobilisation,
    fetal escalation, drill scheduling and checklist item completion."

    Design: Corner/endpoints/drill_participant_roster_is_all_or_nothing_and_rejects_a_foreign_id_without_creating_the_drill
    """
    setup = three_rejected_drill_rosters_then_a_good_one
    validate_error(
        setup["neighbour_only"], ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value, 422
    )
    body = setup["after_the_refusals"].json()
    assert body["meta"]["total_count"] == 0
    assert body["data"] == []


def test_a_scheduled_drill_grants_no_currency_at_all(
    three_rejected_drill_rosters_then_a_good_one,
):
    """"The drill opens at `SCHEDULED`, and scheduling changes nothing about readiness,
    because only a validated drill grants currency."

    Design: Corner/endpoints/drill_participant_roster_is_all_or_nothing_and_rejects_a_foreign_id_without_creating_the_drill
    """
    setup = three_rejected_drill_rosters_then_a_good_one
    world = setup["world"]
    assert setup["accepted"].status_code == 201
    drill = get_success_data(setup["accepted"])
    assert_drill(drill)
    assert drill["status"] == "SCHEDULED"
    assert drill["unit_id"] == world.unit_id
    assert drill["participant_staff_ids"] == [setup["ours"], setup["also_ours"]]
    assert drill["documented_by_staff_id"] is None
    assert drill["version"] == 1
    attending = get_success_data(
        api_client.get_staff_member(setup["ours"], world.charge_headers)
    )
    assert_staff_member(attending)
    assert attending["drill_currency_state"] == "LAPSED"
    assert_instant_is_null(
        attending["last_validated_drill_at"], "last_validated_drill_at"
    )
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
