"""Two drills, five refusals and the revision counter walked to its exact bound.

Drill A is documented twice against the same illegal roster, once with the
timestamps reversed and once with them repaired, and both attempts answer at the
11.4 roster band, because that band sits above the 14.1 timestamp band. Drill B then earns currency,
lifts the unit to READY through a standby slot that could not have been opened a
moment earlier, and loses it again three times over. Abandonment is refused on
two different undeclared statuses, and the fourth re-documentation is refused
because 2 is not less than 2.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_drill,
    assert_instant_equals,
    assert_instant_is_null,
    assert_obstetric_unit,
    assert_staff_member,
    bootstrap_unit,
    create_shift,
    get_success_data,
    set_clock,
)

CLOCK_SCHEDULING = "2026-08-01T05:45:00Z"
CLOCK_BOTH_DRILLS_DUE = "2026-08-01T06:00:00Z"
DRILL_A_SCHEDULED_FOR = "2026-08-01T05:50:00Z"
DRILL_B_SCHEDULED_FOR = "2026-08-01T05:55:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:50:00Z"
SIMULATED_INCISION_AT = "2026-08-01T06:00:00Z"
EXPIRES_NINETY_DAYS_ON = "2026-10-30T06:00:00Z"
SHIFT_WINDOW = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
MEASURED_MINUTES = 10
REVISION_LIMIT = 2
OPEN_BUFFER = 45
FROZEN_BUFFER = 75

FIRST_WITHDRAWAL = (
    "Debrief showed the OR team was paged out of sequence; drill result withdrawn."
)
SECOND_WITHDRAWAL = (
    "Second withdrawal: the timing sheet was transcribed from the wrong theatre clock."
)
THIRD_WITHDRAWAL = (
    "Third withdrawal: participant roster did not match the sign-in sheet held by "
    "the charge nurse."
)

THISTLEDOWN_STAFF = {
    "charge": {
        "full_name": "Perpetua Ngozi RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "second_nurse": {
        "full_name": "Lucian Beaumont RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Anneliese Vogtherr MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Fyodor Rasmussen MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "officer": {
        "full_name": "Marguerite Oyelaran RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def two_drills_walked_to_the_revision_bound():
    """One illegal drill probed at three rungs, one legal drill revised three times.

    The anaesthetist's `OR_STANDBY` entry is created `SCHEDULED` and activated
    only after drill B is validated, because standby eligibility is unsatisfiable
    until its holder is drill-current; that ordering is what makes a single
    validation enough to reach `READY`.
    """
    world = bootstrap_unit(
        clock=CLOCK_SCHEDULING,
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=THISTLEDOWN_STAFF,
        unit_overrides={"unit_name": "Thistledown Cove Maternity LDR"},
    )
    standby_shift = create_shift(
        world, "anesthesia", "OR_STANDBY", *SHIFT_WINDOW, acting_key="charge"
    )
    illegal_roster = [world.staff_id("charge"), world.staff_id("second_nurse")]
    legal_roster = [world.staff_id("ob"), world.staff_id("anesthesia")]

    def _schedule(scheduled_for_utc, participant_staff_ids):
        return get_success_data(
            api_client.create_drill(
                world.unit_id,
                {
                    "drill_type": "DECISION_TO_INCISION",
                    "scheduled_for_utc": scheduled_for_utc,
                    "participant_staff_ids": participant_staff_ids,
                },
                world.charge_headers,
            )
        )

    drill_a = _schedule(DRILL_A_SCHEDULED_FOR, illegal_roster)
    drill_b = _schedule(DRILL_B_SCHEDULED_FOR, legal_roster)
    set_clock(CLOCK_BOTH_DRILLS_DUE)
    for drill in (drill_a, drill_b):
        get_success_data(api_client.start_drill(drill["id"], world.charge_headers))

    def _document(drill, documented_key, decision_at, incision_at):
        return api_client.document_drill(
            drill["id"],
            {
                "decision_at": decision_at,
                "incision_at": incision_at,
                "documented_by_staff_id": world.staff_id(documented_key),
            },
            world.charge_headers,
        )

    def _read(drill):
        return get_success_data(api_client.get_drill(drill["id"], world.officer_headers))

    def _currency():
        return {
            key: get_success_data(
                api_client.get_staff_member(world.staff_id(key), world.charge_headers)
            )
            for key in ("ob", "anesthesia")
        }

    backwards = _document(
        drill_a, "charge", SIMULATED_INCISION_AT, SIMULATED_DECISION_AT
    )
    drill_a_after_backwards = _read(drill_a)
    two_nurse_roster = _document(
        drill_a, "charge", SIMULATED_DECISION_AT, SIMULATED_INCISION_AT
    )
    drill_a_after_the_roster_refusal = _read(drill_a)
    abandoned = api_client.abandon_drill(drill_a["id"], world.charge_headers)
    abandoned_twice = api_client.abandon_drill(drill_a["id"], world.charge_headers)
    documented_b = _document(
        drill_b, "ob", SIMULATED_DECISION_AT, SIMULATED_INCISION_AT
    )
    validated_b = api_client.validate_drill(drill_b["id"], world.officer_headers)
    currency_after_validation = _currency()
    standby_activated = api_client.activate_shift(
        standby_shift["id"], world.charge_headers
    )
    unit_when_ready = world.reload_unit()
    abandon_the_validated_drill = api_client.abandon_drill(
        drill_b["id"], world.charge_headers
    )
    drill_b_still_validated = _read(drill_b)
    reason_omitted = api_client.invalidate_drill(
        drill_b["id"], {}, world.officer_headers
    )
    drill_b_after_the_reason_refusal = _read(drill_b)
    invalidated_b = api_client.invalidate_drill(
        drill_b["id"], {"invalidation_reason": FIRST_WITHDRAWAL}, world.officer_headers
    )
    unit_after_the_invalidation = world.reload_unit()
    currency_after_invalidation = _currency()
    first_revision = _document(
        drill_b, "ob", SIMULATED_DECISION_AT, SIMULATED_INCISION_AT
    )
    get_success_data(api_client.validate_drill(drill_b["id"], world.officer_headers))
    get_success_data(
        api_client.invalidate_drill(
            drill_b["id"],
            {"invalidation_reason": SECOND_WITHDRAWAL},
            world.officer_headers,
        )
    )
    second_revision = _document(
        drill_b, "ob", SIMULATED_DECISION_AT, SIMULATED_INCISION_AT
    )
    get_success_data(api_client.validate_drill(drill_b["id"], world.officer_headers))
    get_success_data(
        api_client.invalidate_drill(
            drill_b["id"],
            {"invalidation_reason": THIRD_WITHDRAWAL},
            world.officer_headers,
        )
    )
    third_revision = _document(
        drill_b, "ob", SIMULATED_DECISION_AT, SIMULATED_INCISION_AT
    )
    final_drill_b = _read(drill_b)
    unit_at_the_end = world.reload_unit()
    return {
        "world": world,
        "standby_shift": standby_shift,
        "illegal_roster": illegal_roster,
        "legal_roster": legal_roster,
        "drill_a": drill_a,
        "drill_b": drill_b,
        "backwards": backwards,
        "drill_a_after_backwards": drill_a_after_backwards,
        "two_nurse_roster": two_nurse_roster,
        "drill_a_after_the_roster_refusal": drill_a_after_the_roster_refusal,
        "abandoned": abandoned,
        "abandoned_twice": abandoned_twice,
        "documented_b": documented_b,
        "validated_b": validated_b,
        "currency_after_validation": currency_after_validation,
        "standby_activated": standby_activated,
        "unit_when_ready": unit_when_ready,
        "abandon_the_validated_drill": abandon_the_validated_drill,
        "drill_b_still_validated": drill_b_still_validated,
        "reason_omitted": reason_omitted,
        "drill_b_after_the_reason_refusal": drill_b_after_the_reason_refusal,
        "invalidated_b": invalidated_b,
        "unit_after_the_invalidation": unit_after_the_invalidation,
        "currency_after_invalidation": currency_after_invalidation,
        "first_revision": first_revision,
        "second_revision": second_revision,
        "third_revision": third_revision,
        "final_drill_b": final_drill_b,
        "unit_at_the_end": unit_at_the_end,
    }


def test_a_backwards_incision_still_answers_at_the_roster_band(
    two_drills_walked_to_the_revision_bound,
):
    """"**11.4** cesarean readiness and team gates, yielding ...
    `ERR_DRILL_PARTICIPANTS_INSUFFICIENT` ... on ... drill documentation and drill
    validation." Also: "**Priority 14** covers time in two sub-bands: **14.1** clinical
    timestamp ranges, yielding ... `ERR_DRILL_TIMESTAMP_OUT_OF_RANGE` ... on ... drill
    documentation". The roster band is the earlier one, so a drill whose roster is
    indefensible answers there even when the timestamps are also reversed.

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    refused = setup["backwards"]
    validate_error(
        refused, ApiErrorId.ERR_DRILL_PARTICIPANTS_INSUFFICIENT.value, 422
    )
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_DRILL_TIMESTAMP_OUT_OF_RANGE.value
    )
    untouched = setup["drill_a_after_backwards"]
    assert_drill(untouched)
    assert untouched["status"] == "IN_PROGRESS"
    assert untouched["measured_d2i_minutes"] is None
    assert untouched["documented_by_staff_id"] is None
    assert untouched["revision_count"] == 0


def test_two_nurses_satisfy_the_count_but_not_the_composition(
    two_drills_walked_to_the_revision_bound,
):
    """"The participant roster must contain at least one staff member with `staff_role`
    `OB_ATTENDING` and at least one `ANESTHESIOLOGIST`, refused otherwise with
    `ERR_DRILL_PARTICIPANTS_INSUFFICIENT`."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    validate_error(
        setup["two_nurse_roster"],
        ApiErrorId.ERR_DRILL_PARTICIPANTS_INSUFFICIENT.value,
        422,
    )
    assert setup["drill_a"]["participant_staff_ids"] == setup["illegal_roster"]
    assert len(setup["illegal_roster"]) == 2
    still_running = setup["drill_a_after_the_roster_refusal"]
    assert_drill(still_running)
    assert still_running["status"] == "IN_PROGRESS"
    assert still_running["measured_d2i_minutes"] is None


def test_an_abandoned_drill_cannot_be_abandoned_a_second_time(
    two_drills_walked_to_the_revision_bound,
):
    """"**8.10** escalation and attempt-limit guards, yielding
    `ERR_ESCALATION_TIER_SKIPPED`, `ERR_ESCALATION_NOT_STARTED`,
    `ERR_CESAREAN_ALREADY_INCISED`, `ERR_DRILL_NOT_ABANDONABLE`,
    `ERR_BUNDLE_STAGE_BLOCKS_RESCIND`, `ERR_REVIEW_REWORK_LIMIT_REACHED`,
    `ERR_DRILL_REVISION_LIMIT_REACHED` or `ERR_SUPPORT_REENTRY_LIMIT_REACHED`, on fetal
    escalation, fetal escalation stand-down, cesarean abort, drill abandonment, drill
    documentation, bundle rescission, review rework request and support pass check-in."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    assert setup["abandoned"].status_code == 200
    dropped = get_success_data(setup["abandoned"])
    assert_drill(dropped)
    assert dropped["status"] == "ABANDONED"
    refused = setup["abandoned_twice"]
    assert refused.status_code == 409
    validate_error_is_one_of(
        refused,
        [
            ApiErrorId.ERR_DRILL_NOT_ABANDONABLE.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )


def test_the_legal_roster_documents_a_ten_minute_simulation_at_revision_zero(
    two_drills_walked_to_the_revision_bound,
):
    """"`measured_d2i_minutes` is computed by the same truncating rule as a real event:
    the elapsed seconds from `decision_at` to `incision_at` divided by 60 with the
    remainder discarded."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    assert setup["documented_b"].status_code == 200
    documented = get_success_data(setup["documented_b"])
    assert_drill(documented)
    assert documented["status"] == "DOCUMENTED"
    assert documented["measured_d2i_minutes"] == MEASURED_MINUTES
    assert documented["revision_count"] == 0
    assert documented["documented_by_staff_id"] == setup["world"].staff_id("ob")
    assert_instant_equals(documented["decision_at"], SIMULATED_DECISION_AT, "decision_at")
    assert_instant_equals(documented["incision_at"], SIMULATED_INCISION_AT, "incision_at")


def test_validation_stamps_the_ninety_day_currency_and_the_acting_officer(
    two_drills_walked_to_the_revision_bound,
):
    """"Validation sets `validated_at` to the current instant, `expires_at` to
    `validated_at` plus 90 days, and `validated_by_user_id` to the acting user; it stamps
    every participant's `last_validated_drill_at` with the drill's simulated `decision_at`
    and moves each participant's `drill_currency_state` from `LAPSED` to `CURRENT`."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    assert setup["validated_b"].status_code == 200
    validated = get_success_data(setup["validated_b"])
    assert_drill(validated)
    assert validated["status"] == "VALIDATED"
    assert_instant_equals(
        validated["validated_at"], CLOCK_BOTH_DRILLS_DUE, "validated_at"
    )
    assert_instant_equals(validated["expires_at"], EXPIRES_NINETY_DAYS_ON, "expires_at")
    assert validated["validated_by_user_id"] == setup["world"].staff_id("officer")
    assert validated["validated_by_user_id"] != validated["documented_by_staff_id"]


def test_the_participants_carry_the_simulated_decision_instant_not_the_validation_one(
    two_drills_walked_to_the_revision_bound,
):
    """"It then recomputes unit readiness, which can rise to `READY` and thereby unblock
    induction confirmations and second-stage advances, and makes `OR_STANDBY` eligibility
    satisfiable."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    for member in setup["currency_after_validation"].values():
        assert_staff_member(member)
        assert member["drill_currency_state"] == "CURRENT"
        assert_instant_equals(
            member["last_validated_drill_at"],
            SIMULATED_DECISION_AT,
            "last_validated_drill_at",
        )
    assert setup["standby_activated"].status_code == 200
    standby = get_success_data(setup["standby_activated"])
    assert standby["status"] == "ACTIVE"
    assert standby["role_slot"] == "OR_STANDBY"


def test_a_unit_with_no_measured_events_at_all_reaches_ready(
    two_drills_walked_to_the_revision_bound,
):
    """"The empty rolling window is not a failure: a unit with a current validated drill,
    standby staffed and no measured emergency events at all is `READY`." "After the posture
    is settled, and only then, `turnover_buffer_minutes` is set to 45 when the posture is
    `OPEN` and 75 otherwise."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    unit = setup["unit_when_ready"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "READY"
    assert unit["current_drill_id"] == setup["drill_b"]["id"]
    assert_instant_equals(
        unit["current_drill_expires_at"], EXPIRES_NINETY_DAYS_ON, "current_drill_expires_at"
    )
    assert unit["mean_d2i_minutes"] is None
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == OPEN_BUFFER


def test_a_validated_drill_can_never_be_abandoned(
    two_drills_walked_to_the_revision_bound,
):
    """"A `ChargeNurse` may instead abandon a drill, moving it from `SCHEDULED` or
    `IN_PROGRESS` to the terminal `ABANDONED`; a `DOCUMENTED`, `VALIDATED` or
    already-`INVALIDATED` drill can never be abandoned, refused with
    `ERR_DRILL_NOT_ABANDONABLE`."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    refused = setup["abandon_the_validated_drill"]
    validate_error(refused, ApiErrorId.ERR_DRILL_NOT_ABANDONABLE.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    )
    survivor = setup["drill_b_still_validated"]
    assert_drill(survivor)
    assert survivor["status"] == "VALIDATED"
    assert_instant_equals(survivor["expires_at"], EXPIRES_NINETY_DAYS_ON, "expires_at")


def test_the_omitted_reason_is_a_context_field_not_a_field_shape(
    two_drills_walked_to_the_revision_bound,
):
    """"**Priority 9** — context-required fields and their length bounds, at HTTP 422:
    `ERR_RESCIND_REASON_REQUIRED`, `ERR_INVALIDATION_REASON_REQUIRED`,
    `ERR_DEBRIEF_NOTES_REQUIRED`, `ERR_CONTRIBUTING_FACTORS_REQUIRED` and
    `ERR_DELIVERY_MODE_REQUIRED`, on bundle rescission, bundle debrief closure, drill
    invalidation, review findings submission, review closure and phase advance."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    refused = setup["reason_omitted"]
    validate_error(refused, ApiErrorId.ERR_INVALIDATION_REASON_REQUIRED.value, 422)
    assert (
        refused.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_FIELD_VALUE.value
    )
    survivor = setup["drill_b_after_the_reason_refusal"]
    assert_drill(survivor)
    assert survivor["status"] == "VALIDATED"
    assert_instant_equals(survivor["expires_at"], EXPIRES_NINETY_DAYS_ON, "expires_at")
    assert survivor["invalidation_reason"] is None


def test_the_only_current_drill_takes_readiness_down_with_it(
    two_drills_walked_to_the_revision_bound,
):
    """"Second hop: if this was the unit's only current drill, `cesarean_readiness_state`
    becomes `NOT_READY` with `readiness_reason` `NO_CURRENT_DRILL`."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    assert setup["invalidated_b"].status_code == 200
    withdrawn = get_success_data(setup["invalidated_b"])
    assert_drill(withdrawn)
    assert withdrawn["status"] == "INVALIDATED"
    assert_instant_is_null(withdrawn["expires_at"], "expires_at")
    assert withdrawn["invalidation_reason"] == FIRST_WITHDRAWAL
    unit = setup["unit_after_the_invalidation"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["readiness_reason"] == "NO_CURRENT_DRILL"
    assert unit["current_drill_id"] is None


def test_currency_is_revocable_and_falls_back_to_lapsed(
    two_drills_walked_to_the_revision_bound,
):
    """"First hop: each participant re-derives `last_validated_drill_at` from the drills
    that remain `VALIDATED` for them, ordered by `decision_at` descending with `created_at`
    descending as the tie-break, and any participant left with no other validated drill
    moves from `CURRENT` to `LAPSED`."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    for member in setup["currency_after_invalidation"].values():
        assert_staff_member(member)
        assert member["drill_currency_state"] == "LAPSED"
        assert_instant_is_null(
            member["last_validated_drill_at"], "last_validated_drill_at"
        )


def test_the_third_revision_lap_is_refused_by_the_counter_not_by_the_edge(
    two_drills_walked_to_the_revision_bound,
):
    """"A re-documentation entered from `INVALIDATED` requires `revision_count` to be less
    than 2, refused otherwise with `ERR_DRILL_REVISION_LIMIT_REACHED`, and increments
    `revision_count` by 1; a first documentation from `IN_PROGRESS` does not touch that
    counter."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    assert setup["first_revision"].status_code == 200
    assert get_success_data(setup["first_revision"])["revision_count"] == 1
    assert setup["second_revision"].status_code == 200
    assert get_success_data(setup["second_revision"])["revision_count"] == REVISION_LIMIT
    refused = setup["third_revision"]
    validate_error(refused, ApiErrorId.ERR_DRILL_REVISION_LIMIT_REACHED.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    )


def test_an_unready_unit_freezes_inductions_with_no_encounters_at_all(
    two_drills_walked_to_the_revision_bound,
):
    """"`INDUCTION_FROZEN` when the deficit is 4.0 or greater, or `escalation_breach_count`
    is 2 or greater, or `bundle_breach_count` is 3 or greater, or
    `cesarean_readiness_state` is `NOT_READY`, or the deficit is greater than 0.0 while some
    activation is in `STAGE_2_ESCALATED`."

    Design: Corner/errors/five_drill_lifecycle_ids_across_two_drills_and_three_revision_laps
    """
    setup = two_drills_walked_to_the_revision_bound
    final = setup["final_drill_b"]
    assert_drill(final)
    assert final["status"] == "INVALIDATED"
    assert final["revision_count"] == REVISION_LIMIT
    assert final["measured_d2i_minutes"] == MEASURED_MINUTES
    assert_instant_is_null(final["expires_at"], "expires_at")
    unit = setup["unit_at_the_end"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["escalation_breach_count"] == 0
    assert unit["bundle_breach_count"] == 0
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert unit["turnover_buffer_minutes"] == FROZEN_BUFFER
