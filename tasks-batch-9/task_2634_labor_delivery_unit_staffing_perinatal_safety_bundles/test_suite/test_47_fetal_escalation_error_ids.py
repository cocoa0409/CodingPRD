"""Five refusals off one CATEGORY_II escalation chain, each on a different rung.

The chain never moves the clock, so every deadline stays open and every reading
stays fresh: that is what leaves each probe alone with the single rule it is
meant to break. A pre-admission reading is a shape refusal, standing a chain
down before it started is a state refusal, a real nurse on a real ACTIVE shift
is still an illegal tier-1 target because her slot is not CHARGE, tier 3 on a
CATEGORY_II tracing is refused for its category before anyone looks at the
theatre roster, and the phase advance is refused because the chain is notified
rather than resolved. The instance also pins that the unresolved chain lifted
the tier floor and re-priced the shared row in place instead of manufacturing a
coverage breach.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_shift,
    assert_care_assignment,
    assert_fetal_assessment,
    assert_instant_equals,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assign_bed,
    bootstrap_unit,
    create_care_assignment,
    create_encounter,
    create_shift,
    get_success_data,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
BEFORE_ADMISSION = "2026-08-01T05:00:00Z"
SHIFT_WINDOW = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
CATEGORY_TWO_ESCALATION_DUE = "2026-08-01T06:20:00Z"
CATEGORY_TWO_NEXT_TIER_DUE = "2026-08-01T06:15:00Z"
TIER_THREE_WEIGHT_IN_LATENT = 2.0
BEDSIDE_CAPACITY = 4.0

FERNBROOK_STAFF = {
    "charge": {
        "full_name": "Marisol Devereaux RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "bedside": {
        "full_name": "Idris Nakamura RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Priya Sundaresan MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
}


def _reading(encounter_id, interpreter_id, **overrides):
    payload = {
        "encounter_id": encounter_id,
        "interpreted_by_staff_id": interpreter_id,
        "category": "CATEGORY_II",
        "baseline_rate_bpm": 145,
        "variability": "MINIMAL",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def one_category_two_chain_pushed_against_five_rungs():
    """Three ACTIVE shifts on three slots, one bedded and covered encounter in LATENT.

    The CHARGE-slot nurse is both the interpreter and the only legal tier-1
    target; the BEDSIDE-slot nurse carries the encounter's shared row and is the
    illegal tier-1 target; the attending on the TRIAGE slot is the legal tier-2
    target. No `OR_STANDBY` entry exists anywhere on the unit, which is what
    makes the tier-3 ordering visible.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=FERNBROOK_STAFF,
        unit_overrides={"unit_name": "Fernbrook Womens Hospital LDR"},
    )
    charge_shift = activate_shift(
        world, create_shift(world, "charge", "CHARGE", *SHIFT_WINDOW)
    )
    bedside_shift = activate_shift(
        world, create_shift(world, "bedside", "BEDSIDE", *SHIFT_WINDOW)
    )
    triage_shift = activate_shift(
        world, create_shift(world, "ob", "TRIAGE", *SHIFT_WINDOW)
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-FERN-7101",
        parity=1,
        gestational_age_weeks=40,
    )
    assign_bed(world, encounter, "LDR-01")
    assignment = create_care_assignment(
        world, encounter, bedside_shift, coverage_mode="RATIO_SHARED"
    )
    get_success_data(
        api_client.advance_phase(
            encounter["id"], {"target_phase": "LATENT"}, world.charge_headers
        )
    )
    interpreter = world.staff_id("charge")
    before_admission = api_client.create_assessment(
        _reading(encounter["id"], interpreter, assessed_at=BEFORE_ADMISSION),
        world.charge_headers,
    )
    nothing_recorded = api_client.list_assessments(
        world.charge_headers, params={"limit": 10, "encounter_id": encounter["id"]}
    )
    accepted = api_client.create_assessment(
        _reading(encounter["id"], interpreter), world.charge_headers
    )
    assessment = get_success_data(accepted)

    def _escalate(target_tier, notified_staff_id=None):
        payload = {"target_tier": target_tier}
        if notified_staff_id is not None:
            payload["notified_staff_id"] = notified_staff_id
        return api_client.escalate_assessment(
            assessment["id"], payload, world.bedside_headers
        )

    def _reload():
        return get_success_data(
            api_client.get_assessment(assessment["id"], world.charge_headers)
        )

    never_started = api_client.resolve_assessment(
        assessment["id"], {}, world.ob_headers
    )
    still_due = _reload()
    wrong_slot = _escalate(1, world.staff_id("bedside"))
    after_the_wrong_slot = _reload()
    tier_one = _escalate(1, world.staff_id("charge"))
    tier_two = _escalate(2, world.staff_id("ob"))
    wrong_category = _escalate(3)
    after_the_wrong_category = _reload()
    no_cesarean = api_client.list_cesareans(
        world.ob_headers, params={"limit": 10, "encounter_id": encounter["id"]}
    )
    blocked_advance = api_client.advance_phase(
        encounter["id"], {"target_phase": "ACTIVE_FIRST_STAGE"}, world.charge_headers
    )
    return {
        "world": world,
        "charge_shift": charge_shift,
        "bedside_shift": bedside_shift,
        "triage_shift": triage_shift,
        "encounter": encounter,
        "assignment": assignment,
        "before_admission": before_admission,
        "nothing_recorded": nothing_recorded,
        "accepted": accepted,
        "assessment": assessment,
        "never_started": never_started,
        "still_due": still_due,
        "wrong_slot": wrong_slot,
        "after_the_wrong_slot": after_the_wrong_slot,
        "tier_one": tier_one,
        "tier_two": tier_two,
        "wrong_category": wrong_category,
        "after_the_wrong_category": after_the_wrong_category,
        "no_cesarean": no_cesarean,
        "blocked_advance": blocked_advance,
    }


def test_a_reading_taken_before_the_admission_is_refused_as_a_timestamp(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"A `BedsideNurse`, `ChargeNurse` or `ObstetricianAttending` records an
    interpretation of the fetal heart-rate tracing against an encounter, naming
    `encounter_id`, `interpreted_by_staff_id`, a `category` of `CATEGORY_I`,
    `CATEGORY_II` or `CATEGORY_III`, a `baseline_rate_bpm` from 50 to 220, a
    `variability` of `ABSENT`, `MINIMAL`, `MODERATE` or `MARKED`, an optional
    `recurrent_decelerations` flag defaulting to false, and an optional `assessed_at`
    which defaults to the current instant and, when supplied, must be at or after the
    encounter's `admitted_at` and at or before the current instant, refused otherwise
    with `ERR_ASSESSMENT_TIMESTAMP_OUT_OF_RANGE`."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    validate_error(
        setup["before_admission"],
        ApiErrorId.ERR_ASSESSMENT_TIMESTAMP_OUT_OF_RANGE.value,
        400,
    )
    body = setup["nothing_recorded"].json()
    assert body["meta"]["total_count"] == 0
    assert body["data"] == []
    admitted = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_instant_equals(admitted["admitted_at"], CLOCK_START, "admitted_at")


def test_the_accepted_reading_opens_due_with_a_twenty_minute_window(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"The new row's `escalation_status` starts at `NOT_REQUIRED` when the `category`
    is `CATEGORY_I` and at `ESCALATION_DUE` otherwise, and `supersedes_assessment_id`
    is set to the immediately prior assessment on the same encounter, chosen as the one
    with the greatest `assessed_at` and, where two share that instant, the later
    `created_at`."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    assert setup["accepted"].status_code == 201
    assessment = setup["assessment"]
    assert_fetal_assessment(assessment)
    assert assessment["category"] == "CATEGORY_II"
    assert assessment["escalation_status"] == "ESCALATION_DUE"
    assert assessment["escalation_tier_high_water"] == 0
    assert assessment["supersedes_assessment_id"] is None
    assert_instant_equals(assessment["assessed_at"], CLOCK_START, "assessed_at")


def test_the_escalation_deadline_is_the_reading_plus_twenty_minutes(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"When the `category` is not `CATEGORY_I`, `escalation_due_at` is set to
    `assessed_at` plus 20 minutes for a `CATEGORY_II` reading and plus 5 minutes for a
    `CATEGORY_III` reading."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    assert_instant_equals(
        setup["assessment"]["escalation_due_at"],
        CATEGORY_TWO_ESCALATION_DUE,
        "escalation_due_at",
    )


def test_a_chain_that_was_never_escalated_cannot_be_stood_down(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"This requires `escalation_tier_high_water` to be 1 or more, since nothing that was
    never escalated can be stood down, refused otherwise with
    `ERR_ESCALATION_NOT_STARTED`, and requires that no cesarean event minted from
    this assessment sits in `TEAM_MOBILIZED` or `INCISION_RECORDED`, refused
    otherwise with `ERR_CESAREAN_EVENT_IN_PROGRESS`." The stand-down is declared only from
    `TIER_1_NOTIFIED`, `TIER_2_NOTIFIED` or `TIER_3_ACTIVATED`, so priority 8 answers
    with one of its two 409 identifiers for this operation.

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    refused = setup["never_started"]
    assert refused.status_code == 409
    validate_error_is_one_of(
        refused,
        [
            ApiErrorId.ERR_ESCALATION_NOT_STARTED.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    still_due = setup["still_due"]
    assert_fetal_assessment(still_due)
    assert still_due["escalation_status"] == "ESCALATION_DUE"
    assert still_due["escalation_tier_high_water"] == 0
    assert still_due["reassessment_due_at"] is None


def test_a_bedside_slot_nurse_is_not_a_legal_tier_one_target(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"A tier-1 target must be a staff member holding an `ACTIVE` roster entry in the
    `CHARGE` slot on the encounter's unit; a tier-2 target must have `staff_role`
    `OB_ATTENDING` and an `ACTIVE` roster entry on the unit; either failure is refused
    with `ERR_ESCALATION_TARGET_INELIGIBLE`."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    validate_error(
        setup["wrong_slot"], ApiErrorId.ERR_ESCALATION_TARGET_INELIGIBLE.value, 422
    )
    unmoved = setup["after_the_wrong_slot"]
    assert unmoved["escalation_status"] == "ESCALATION_DUE"
    assert unmoved["escalation_tier_high_water"] == 0
    rejected_target = setup["bedside_shift"]
    assert_shift_assignment(rejected_target)
    assert rejected_target["status"] == "ACTIVE"
    assert rejected_target["role_slot"] == "BEDSIDE"


def test_the_charge_slot_nurse_carries_tier_one_and_sets_the_next_deadline(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"A successful escalation sets `escalation_tier_high_water` to `target_tier` and
    moves `escalation_status` to `TIER_1_NOTIFIED`, `TIER_2_NOTIFIED` or
    `TIER_3_ACTIVATED`. For tiers 1 and 2 it sets `next_tier_due_at` to the instant of
    that notification plus 15 minutes for a `CATEGORY_II` assessment or 5 minutes for a
    `CATEGORY_III` assessment; at tier 3 `next_tier_due_at` becomes null, because there
    is no fourth tier."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    assert setup["tier_one"].status_code == 200
    notified = get_success_data(setup["tier_one"])
    assert_fetal_assessment(notified)
    assert notified["escalation_status"] == "TIER_1_NOTIFIED"
    assert notified["escalation_tier_high_water"] == 1
    assert_instant_equals(
        notified["next_tier_due_at"], CATEGORY_TWO_NEXT_TIER_DUE, "next_tier_due_at"
    )
    assert setup["charge_shift"]["role_slot"] == "CHARGE"
    assert setup["charge_shift"]["status"] == "ACTIVE"


def test_tier_two_reaches_the_attending_and_lifts_the_high_water_again(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"Escalation advances exactly one tier per call. The request names `target_tier`
    as 1, 2 or 3, and `notified_staff_id` which is required for tiers 1 and 2 and
    omitted for tier 3."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    assert setup["tier_two"].status_code == 200
    notified = get_success_data(setup["tier_two"])
    assert_fetal_assessment(notified)
    assert notified["escalation_status"] == "TIER_2_NOTIFIED"
    assert notified["escalation_tier_high_water"] == 2
    assert_instant_equals(
        notified["next_tier_due_at"], CATEGORY_TWO_NEXT_TIER_DUE, "next_tier_due_at"
    )
    assert setup["triage_shift"]["role_slot"] == "TRIAGE"


def test_tier_three_is_refused_for_its_category_before_the_theatre_roster(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"Tier 3 requires the assessment's `category` to be `CATEGORY_III`, refused
    otherwise with `ERR_ESCALATION_CATEGORY_INSUFFICIENT`, and requires an `ACTIVE`
    `OR_STANDBY` roster entry on the unit, refused otherwise with
    `ERR_OR_STANDBY_NOT_STAFFED`."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    refused = setup["wrong_category"]
    validate_error(
        refused, ApiErrorId.ERR_ESCALATION_CATEGORY_INSUFFICIENT.value, 422
    )
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_OR_STANDBY_NOT_STAFFED.value
    )
    unmoved = setup["after_the_wrong_category"]
    assert unmoved["escalation_status"] == "TIER_2_NOTIFIED"
    assert unmoved["escalation_tier_high_water"] == 2
    cesareans = setup["no_cesarean"].json()
    assert cesareans["meta"]["total_count"] == 0
    assert cesareans["data"] == []


def test_the_phase_cannot_advance_while_the_chain_is_still_notified(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"That assessment's `escalation_status` must not be `ESCALATION_DUE`,
    `TIER_1_NOTIFIED`, `TIER_2_NOTIFIED`, `TIER_3_ACTIVATED` or `TIMED_OUT_BREACH`,
    refused otherwise with `ERR_FETAL_ESCALATION_UNRESOLVED`."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    refused = setup["blocked_advance"]
    validate_error(refused, ApiErrorId.ERR_FETAL_ESCALATION_UNRESOLVED.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_FETAL_ASSESSMENT_STALE.value
    )
    stalled = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(stalled)
    assert stalled["labor_phase"] == "LATENT"


def test_the_unresolved_category_two_chain_lifted_the_tier_floor(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"`TIER_III` fires when `labor_phase` is `SECOND_STAGE`, or an activation on the
    encounter is in `STAGE_1_IN_PROGRESS`, or the latest assessment on the encounter is
    `CATEGORY_II` with an `escalation_status` of `ESCALATION_DUE`, `TIER_1_NOTIFIED`,
    `TIER_2_NOTIFIED` or `REASSESSMENT_PENDING`."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    lifted = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(lifted)
    assert lifted["acuity_tier"] == "TIER_III"
    assert lifted["one_to_one_required"] is False
    assert lifted["required_coverage_units"] == pytest.approx(
        TIER_THREE_WEIGHT_IN_LATENT, abs=1e-9
    )
    assert lifted["assigned_coverage_units"] == pytest.approx(
        TIER_THREE_WEIGHT_IN_LATENT, abs=1e-9
    )
    assert lifted["staffing_state"] == "RATIO_COVERED"


def test_the_shared_row_was_repriced_in_place_rather_than_breached(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"Whenever a tier or a phase changes, every affected row is re-priced in place,
    and the order of the two ledger movements is fixed: the old value is credited back
    first and the new value debited second, never the reverse."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    world = setup["world"]
    row = get_success_data(
        api_client.get_care_assignment(
            setup["assignment"]["id"], world.charge_headers
        )
    )
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["coverage_mode"] == "RATIO_SHARED"
    assert row["acuity_units_consumed"] == pytest.approx(
        TIER_THREE_WEIGHT_IN_LATENT, abs=1e-9
    )
    assert row["superseded_by_assignment_id"] is None
    carrier = get_success_data(
        api_client.get_shift(setup["bedside_shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(carrier)
    assert carrier["assigned_acuity_load_units"] == pytest.approx(
        TIER_THREE_WEIGHT_IN_LATENT, abs=1e-9
    )
    assert carrier["capacity_units_effective"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )


def test_the_unit_carries_no_deficit_but_is_frozen_for_readiness(
    one_category_two_chain_pushed_against_five_rungs,
):
    """"`INDUCTION_FROZEN` when the deficit is 4.0 or greater, or
    `escalation_breach_count` is 2 or greater, or `bundle_breach_count` is 3 or greater,
    or `cesarean_readiness_state` is `NOT_READY`, or the deficit is greater than 0.0
    while some activation is in `STAGE_2_ESCALATED`."

    Design: Corner/errors/five_fetal_escalation_ids_separate_across_the_14_1_8_10_11_2_and_11_3_rungs
    """
    setup = one_category_two_chain_pushed_against_five_rungs
    unit = setup["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert unit["escalation_breach_count"] == 0
