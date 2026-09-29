"""Identical privileges, different reach: three referential arms of one rung.

Every role in this domain addresses every unit, so nothing about the acting
identity separates two hospitals — the same safety officer founds both, and the
same charge nurse holds a live entry on one of them. What keeps the second
hospital's inventory out of the first one's case is a single referential band,
and this module drives the three arms of it that nothing else reaches: the
labor bed on attachment, the notified nurse on a tier-1 escalation, and the
theatre on a crash mobilisation. Each foreign probe is built so that a
different, later error would answer if the band were missing or ordered late —
the foreign bed is an AVAILABLE LDR bed, the foreign nurse holds no roster
entry at all, and the crash roster carries no surgical tech and two members
with no shift — and each is paired with the same call re-aimed at a same-unit
row, so the refusal cannot be blamed on a broken endpoint.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_cesarean_event,
    assert_fetal_assessment,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    bootstrap_unit,
    create_active_shift,
    create_encounter,
    get_success_data,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
CHARGE_SHIFT = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
ESCALATION_DUE_AT = "2026-08-01T06:20:00Z"
NEXT_TIER_DUE_AT = "2026-08-01T06:15:00Z"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
UNIT_A_NAME = "Fallowmere Crossing Womens Hospital LDR"
UNIT_B_NAME = "Wickersham Fields Womens Hospital LDR"
BASELINE_RATE = 138
FIRST_TIER = 1

FALLOWMERE_STAFF = {
    "charge": {
        "full_name": "Marguerite Vanterpool RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Teodoro Blankenbaker MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "neonatal": {
        "full_name": "Serafina Odenkirk NNP",
        "staff_role": "NEONATAL_RESUSCITATOR",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Leocadia Marchbanks MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}

WICKERSHAM_STAFF = {
    "charge": {
        "full_name": "Cordelia Wrenfield RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def two_units_and_three_foreign_references():
    """Two hospitals stood up by one identity; one case, and it lives on the first.

    The second hospital holds no encounter at all for the whole run, so its bed
    and its theatre stay `AVAILABLE` and its nurse stays unrostered — every
    later assertion about them being untouched is measured against that.
    """
    home = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=8,
        or_rooms=2,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=FALLOWMERE_STAFF,
        unit_overrides={"unit_name": UNIT_A_NAME},
    )
    away = bootstrap_unit(
        ldr_beds=6,
        or_rooms=2,
        bed_specs=[("LDR-01", "LDR"), ("OR-01", "OR")],
        staff_specs=WICKERSHAM_STAFF,
        unit_overrides={"unit_name": UNIT_B_NAME},
    )
    create_active_shift(home, "charge", "CHARGE", *CHARGE_SHIFT)
    encounter = create_encounter(
        home,
        patient_record_code="PRC-FALL-7701",
        parity=1,
        gestational_age_weeks=39,
    )
    foreign_bed_attachment = api_client.assign_bed(
        encounter["id"], {"bed_id": away.bed_id("LDR-01")}, home.charge_headers
    )
    foreign_bed_after_the_refusal = get_success_data(
        api_client.get_bed(away.bed_id("LDR-01"), home.charge_headers)
    )
    own_bed_attachment = api_client.assign_bed(
        encounter["id"], {"bed_id": home.bed_id("LDR-01")}, home.charge_headers
    )
    assessment = get_success_data(
        api_client.create_assessment(
            {
                "encounter_id": encounter["id"],
                "interpreted_by_staff_id": home.staff_id("charge"),
                "category": "CATEGORY_II",
                "baseline_rate_bpm": BASELINE_RATE,
                "variability": "MINIMAL",
                "recurrent_decelerations": True,
            },
            home.charge_headers,
        )
    )
    foreign_escalation = api_client.escalate_assessment(
        assessment["id"],
        {"target_tier": FIRST_TIER, "notified_staff_id": away.staff_id("charge")},
        home.charge_headers,
    )
    own_escalation = api_client.escalate_assessment(
        assessment["id"],
        {"target_tier": FIRST_TIER, "notified_staff_id": home.staff_id("charge")},
        home.charge_headers,
    )
    declared = api_client.create_cesarean(
        {
            "encounter_id": encounter["id"],
            "urgency_class": "CATEGORY_1_CRASH",
            "triggering_assessment_id": assessment["id"],
        },
        home.ob_headers,
    )
    event = get_success_data(declared)
    home_unit_before_mobilising = home.reload_unit()
    encounter_before_mobilising = reload_encounter(home, encounter["id"])
    foreign_mobilisation = api_client.mobilize_team(
        event["id"],
        {
            "or_bed_id": away.bed_id("OR-01"),
            "staff_ids": [
                home.staff_id("anesthesia"),
                home.staff_id("neonatal"),
                home.staff_id("charge"),
            ],
        },
        home.ob_headers,
    )
    return {
        "home": home,
        "away": away,
        "encounter": encounter,
        "assessment": assessment,
        "foreign_bed_attachment": foreign_bed_attachment,
        "foreign_bed_after_the_refusal": foreign_bed_after_the_refusal,
        "own_bed_attachment": own_bed_attachment,
        "foreign_escalation": foreign_escalation,
        "own_escalation": own_escalation,
        "declared": declared,
        "event": event,
        "home_unit_before_mobilising": home_unit_before_mobilising,
        "encounter_before_mobilising": encounter_before_mobilising,
        "foreign_mobilisation": foreign_mobilisation,
        "event_after_the_refusal": get_success_data(
            api_client.get_cesarean(event["id"], home.ob_headers)
        ),
        "foreign_theatre_after_the_refusal": get_success_data(
            api_client.get_bed(away.bed_id("OR-01"), home.charge_headers)
        ),
    }


def test_the_foreign_labor_bed_is_refused_for_its_unit_and_nothing_else(
    two_units_and_three_foreign_references,
):
    """"**Priority 7** — cross-aggregate scoping, meaning that every referenced record must
    belong to the same `ObstetricUnit` as the operation's subject: `ERR_CROSS_UNIT_REFERENCE`
    at HTTP 422, on care-assignment creation, shift-assignment creation, encounter bed
    attachment, cesarean team mobilisation, fetal escalation, drill scheduling and checklist
    item completion." Also: "Attaching a bed is a separate `ChargeNurse` act naming
    `bed_id`; the bed must be of type `LDR` and `AVAILABLE`, it moves to `OCCUPIED` with
    `current_encounter_id` pointing at the encounter, and an encounter that already occupies
    a bed is refused with `ERR_ENCOUNTER_ALREADY_IN_BED`."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    refused = setup["foreign_bed_attachment"]
    validate_error(refused, ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value, 422)
    seen = refused.json()["data"]["error_id"]
    assert seen != ApiErrorId.ERR_BED_NOT_FOUND.value
    assert seen != ApiErrorId.ERR_BED_TYPE_NOT_ELIGIBLE.value
    away = setup["away"]
    assert away.bed("LDR-01")["bed_type"] == "LDR"
    assert away.bed("LDR-01")["status"] == "AVAILABLE"


def test_the_foreign_units_inventory_is_left_exactly_as_it_was(
    two_units_and_three_foreign_references,
):
    """"Beds are created inside a unit by a `PerinatalSafetyOfficer` or a `ChargeNurse` and
    take their `unit_id` from the path, immutably."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    untouched = setup["foreign_bed_after_the_refusal"]
    assert_bed(untouched)
    assert untouched["unit_id"] == setup["away"].unit_id
    assert untouched["status"] == "AVAILABLE"
    assert untouched["current_encounter_id"] is None


def test_the_same_call_aimed_at_its_own_bed_succeeds(
    two_units_and_three_foreign_references,
):
    """"Attaching a bed is a separate `ChargeNurse` act naming `bed_id`; the bed must be of
    type `LDR` and `AVAILABLE`, it moves to `OCCUPIED` with `current_encounter_id` pointing
    at the encounter, and an encounter that already occupies a bed is refused with
    `ERR_ENCOUNTER_ALREADY_IN_BED`."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    home = setup["home"]
    assert setup["own_bed_attachment"].status_code == 200
    bedded = get_success_data(setup["own_bed_attachment"])
    assert_labor_encounter(bedded)
    assert bedded["bed_id"] == home.bed_id("LDR-01")
    own_bed = get_success_data(
        api_client.get_bed(home.bed_id("LDR-01"), home.charge_headers)
    )
    assert_bed(own_bed)
    assert own_bed["status"] == "OCCUPIED"
    assert own_bed["current_encounter_id"] == setup["encounter"]["id"]


def test_the_category_two_reading_opens_a_twenty_minute_tier_one_window(
    two_units_and_three_foreign_references,
):
    """"When the `category` is not `CATEGORY_I`, `escalation_due_at` is set to `assessed_at`
    plus 20 minutes for a `CATEGORY_II` reading and plus 5 minutes for a `CATEGORY_III`
    reading." Also: "A tier-1 call must arrive at or before `escalation_due_at`, the boundary
    instant still being in time, refused otherwise with `ERR_ESCALATION_WINDOW_EXPIRED`."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    assessment = setup["assessment"]
    assert_fetal_assessment(assessment)
    assert assessment["category"] == "CATEGORY_II"
    assert assessment["escalation_status"] == "ESCALATION_DUE"
    assert_instant_equals(assessment["assessed_at"], CLOCK_START, "assessed_at")
    assert_instant_equals(
        assessment["escalation_due_at"], ESCALATION_DUE_AT, "escalation_due_at"
    )


def test_the_foreign_nurse_loses_on_her_unit_before_she_loses_on_her_roster(
    two_units_and_three_foreign_references,
):
    """"A tier-1 target must be a staff member holding an `ACTIVE` roster entry in the
    `CHARGE` slot on the encounter's unit; a tier-2 target must have `staff_role`
    `OB_ATTENDING` and an `ACTIVE` roster entry on the unit; either failure is refused with
    `ERR_ESCALATION_TARGET_INELIGIBLE`." The earlier band answers instead: "**Priority 7** —
    cross-aggregate scoping, meaning that every referenced record must belong to the same
    `ObstetricUnit` as the operation's subject: `ERR_CROSS_UNIT_REFERENCE` at HTTP 422, on
    care-assignment creation, shift-assignment creation, encounter bed attachment, cesarean
    team mobilisation, fetal escalation, drill scheduling and checklist item completion."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    refused = setup["foreign_escalation"]
    validate_error(refused, ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_ESCALATION_TARGET_INELIGIBLE.value
    )


def test_the_home_charge_nurse_is_notified_on_the_identical_call(
    two_units_and_three_foreign_references,
):
    """"A successful escalation sets `escalation_tier_high_water` to `target_tier` and moves
    `escalation_status` to `TIER_1_NOTIFIED`, `TIER_2_NOTIFIED` or `TIER_3_ACTIVATED`." Also:
    "For tiers 1 and 2 it sets `next_tier_due_at` to the instant of that notification plus 15
    minutes for a `CATEGORY_II` assessment or 5 minutes for a `CATEGORY_III` assessment; at
    tier 3 `next_tier_due_at` becomes null, because there is no fourth tier."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    assert setup["own_escalation"].status_code == 200
    escalated = get_success_data(setup["own_escalation"])
    assert_fetal_assessment(escalated)
    assert escalated["escalation_status"] == "TIER_1_NOTIFIED"
    assert escalated["escalation_tier_high_water"] == FIRST_TIER
    assert_instant_equals(
        escalated["next_tier_due_at"], NEXT_TIER_DUE_AT, "next_tier_due_at"
    )


def test_the_crash_event_is_declared_on_the_home_encounter(
    two_units_and_three_foreign_references,
):
    """"Both routes produce an identical row: status `DECISION_DECLARED` with `decision_at`
    at the current instant, the two triggering references left null on a clinician declaration
    unless supplied."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    assert setup["declared"].status_code == 201
    event = setup["event"]
    assert_cesarean_event(event)
    assert event["status"] == "DECISION_DECLARED"
    assert event["urgency_class"] == "CATEGORY_1_CRASH"
    assert event["encounter_id"] == setup["encounter"]["id"]
    assert event["triggering_assessment_id"] == setup["assessment"]["id"]
    assert_instant_equals(event["decision_at"], CLOCK_START, "decision_at")


def test_the_foreign_theatre_outranks_two_armed_mobilisation_defects(
    two_units_and_three_foreign_references,
):
    """"It names `or_bed_id`, which must be a bed of `bed_type` `OR` on the encounter's own
    unit whose `status` is `AVAILABLE`, refused otherwise with `ERR_OR_BED_UNAVAILABLE`, and
    `staff_ids`, an array of 3 to 12 staff identifiers whose payload order is preserved
    verbatim in `mobilized_staff_ids`." Also: "That array must contain at least one staff
    member with `staff_role` `ANESTHESIOLOGIST`, at least one `SURGICAL_TECH` whose
    `or_circulating_qualified` is true, and at least one `NEONATAL_RESUSCITATOR`, each holding
    an `ACTIVE` roster entry on the unit, refused otherwise with
    `ERR_CESAREAN_TEAM_INCOMPLETE`."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    refused = setup["foreign_mobilisation"]
    validate_error(refused, ApiErrorId.ERR_CROSS_UNIT_REFERENCE.value, 422)
    seen = refused.json()["data"]["error_id"]
    assert seen != ApiErrorId.ERR_OR_BED_UNAVAILABLE.value
    assert seen != ApiErrorId.ERR_CESAREAN_TEAM_INCOMPLETE.value
    assert seen != ApiErrorId.ERR_SHIFT_NOT_ACTIVE.value
    assert setup["away"].bed("OR-01")["bed_type"] == "OR"


def test_the_readiness_gate_could_never_have_answered_for_a_crash(
    two_units_and_three_foreign_references,
):
    """"For a `CATEGORY_2_URGENT` event the unit's `cesarean_readiness_state` must not be
    `NOT_READY`, refused otherwise with `ERR_CESAREAN_READINESS_NOT_MET`; a
    `CATEGORY_1_CRASH` event bypasses that check entirely, because a crash section is never
    refused for a paperwork lapse."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    home_unit = setup["home_unit_before_mobilising"]
    assert_obstetric_unit(home_unit)
    assert home_unit["cesarean_readiness_state"] == "NOT_READY"
    assert (
        setup["foreign_mobilisation"].json()["data"]["error_id"]
        != ApiErrorId.ERR_CESAREAN_READINESS_NOT_MET.value
    )


def test_the_refused_mobilisation_wrote_nothing_on_either_unit(
    two_units_and_three_foreign_references,
):
    """"Mobilising takes the OR bed from `AVAILABLE` to `OCCUPIED`, sets the encounter's
    `one_to_one_required` to true with the usual re-pricing and posture consequences, and
    auto-checks-out every `CHECKED_IN` support pass on the encounter — moving it from
    `CHECKED_IN` to `CHECKED_OUT` — unless that pass has `credential_type` `DOULA_CERTIFIED`
    with `or_credentialed` true, which is the one pass allowed to follow the patient into
    theatre."

    Design: Corner/rbac/cross_unit_references_are_refused_on_bed_attachment_escalation_targets_and_or_room_mobilization
    """
    setup = two_units_and_three_foreign_references
    home = setup["home"]
    survivor = setup["event_after_the_refusal"]
    assert_cesarean_event(survivor)
    assert survivor["status"] == "DECISION_DECLARED"
    assert survivor["or_bed_id"] is None
    assert_instant_is_null(survivor["incision_at"], "incision_at")
    for staff_key in ("anesthesia", "neonatal", "charge"):
        assert home.staff_id(staff_key) not in survivor["mobilized_staff_ids"]
    foreign_theatre = setup["foreign_theatre_after_the_refusal"]
    assert_bed(foreign_theatre)
    assert foreign_theatre["unit_id"] == setup["away"].unit_id
    assert foreign_theatre["status"] == "AVAILABLE"
    unmoved = reload_encounter(home, setup["encounter"]["id"])
    assert_labor_encounter(unmoved)
    # The declared event already carries the encounter: "`TIER_IV` fires when ...
    # a cesarean event on the encounter is in `DECISION_DECLARED`", and
    # one-to-one follows the tier. The refused mobilisation neither set it nor
    # cleared it, so the pre-refusal reading is what has to survive.
    assert unmoved["one_to_one_required"] is True
    assert unmoved["acuity_tier"] == "TIER_IV"
    assert unmoved["one_to_one_required"] == (
        setup["encounter_before_mobilising"]["one_to_one_required"]
    )
