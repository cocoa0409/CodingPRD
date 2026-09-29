"""The two duty pairs whose disqualifying fact lives on somebody else's row.

Nothing on the cesarean event or on the snapshot names the refused caller: the
first is disqualified by an array stamped two transitions earlier, the second by a
join that runs snapshot to cohort to review to facilitator. Both are then pinned
between their neighbouring bands. The case close only reaches the duty check
because the newborn review was closed first, otherwise the priority-8 rung would
have answered; and the certification answers the duty check while an empty
episiotomy denominator and an unclosed period both sit waiting underneath, which
the follow-up call from a clean identity then collects.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_cesarean_event,
    assert_instant_equals,
    assert_labor_encounter,
    assert_newborn_review,
    assert_snapshot,
    assign_bed,
    bootstrap_unit,
    create_active_shift,
    create_encounter,
    declare_cesarean,
    get_success_data,
    mobilize_cesarean,
    reload_encounter,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
CLOCK_AFTER_DELIVERY = "2026-08-01T06:10:00Z"
CLOCK_DEBRIEF_HELD = "2026-08-01T06:15:00Z"
INCISION_AT = "2026-08-01T06:05:00Z"
DELIVERY_AT = "2026-08-01T06:08:00Z"
DEBRIEF_SLOT = "2026-08-01T06:15:00Z"
SHIFT_WINDOW = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-08-02T00:00:00Z"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
CRASH_TARGET_MINUTES = 15
MEASURED_MINUTES = 5
FULL_RATE_PCT = 100.0
FINDINGS_SUMMARY = (
    "Crash cesarean for prolonged bradycardia; the neonatal team was present at "
    "incision and cord gases were drawn without delay."
)
FACTOR_CODES = ["FETAL_STATUS_NON_REASSURING"]

CINDERFELL_STAFF = {
    "charge": {
        "full_name": "Ophelia Brandvold RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Aurelio Panchenko MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "tech": {
        "full_name": "Ximena Dalgaard ST",
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "neonatal": {
        "full_name": "Barnaby Fitzhugh NNP",
        "staff_role": "NEONATAL_RESUSCITATOR",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "fac": {
        "full_name": "Rosamund Achterhof RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Ludovica Marchetti MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "officer": {
        "full_name": "Hyacinth Ravensworth RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them():
    """One NTSV crash cesarean carried to `REVIEW_PENDING`, its review closed first.

    No care assignment is ever created on this encounter, so no probe here can be
    explained by the care-participant clause of the duty rules; the only identities
    that carry a disqualifying fact are the three mobilised team members and the
    review facilitator.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("OR-01", "OR")],
        staff_specs=CINDERFELL_STAFF,
        unit_overrides={"unit_name": "Cinderfell Point Womens Hospital LDR"},
    )
    for staff_key, role_slot in (
        ("charge", "CHARGE"),
        ("anesthesia", "TRIAGE"),
        ("tech", "TRIAGE"),
        ("neonatal", "TRIAGE"),
    ):
        create_active_shift(world, staff_key, role_slot, *SHIFT_WINDOW)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-CIND-4401",
        parity=0,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    assessment = get_success_data(
        api_client.create_assessment(
            {
                "encounter_id": encounter["id"],
                "interpreted_by_staff_id": world.staff_id("charge"),
                "category": "CATEGORY_III",
                "baseline_rate_bpm": 104,
                "variability": "ABSENT",
                "recurrent_decelerations": True,
            },
            world.charge_headers,
        )
    )
    event = declare_cesarean(
        world,
        encounter,
        urgency_class="CATEGORY_1_CRASH",
        triggering_assessment_id=assessment["id"],
    )
    mobilize_cesarean(
        world, event, "OR-01", staff_keys=["anesthesia", "tech", "neonatal"]
    )
    set_clock(CLOCK_AFTER_DELIVERY)
    api_client.record_incision(
        event["id"], {"incision_at": INCISION_AT}, world.ob_headers
    )
    delivered = api_client.record_delivery(
        event["id"], {"delivery_at": DELIVERY_AT}, world.ob_headers
    )
    review = get_success_data(
        api_client.create_review(
            {
                "encounter_id": encounter["id"],
                "complication_code": "UNEXPECTED_NICU_TERM",
                "facilitator_staff_id": world.staff_id("fac"),
            },
            world.officer_headers,
        )
    )
    api_client.schedule_debrief(
        review["id"],
        {"debrief_scheduled_for_utc": DEBRIEF_SLOT},
        world.charge_headers,
    )
    set_clock(CLOCK_DEBRIEF_HELD)
    api_client.submit_findings(
        review["id"],
        {
            "findings_summary": FINDINGS_SUMMARY,
            "contributing_factor_codes": FACTOR_CODES,
        },
        world.charge_headers,
    )
    closed_review = get_success_data(
        api_client.close_review(review["id"], world.officer_headers)
    )
    close_by_the_anesthesiologist = api_client.close_cesarean(
        event["id"], world.officer_headers_for("anesthesia")
    )
    close_by_the_surgical_tech = api_client.close_cesarean(
        event["id"], world.officer_headers_for("tech")
    )
    close_by_a_bystander = api_client.close_cesarean(
        event["id"], world.officer_headers
    )
    snapshot = get_success_data(
        api_client.create_snapshot(
            world.unit_id,
            {
                "period_start_utc": PERIOD_START,
                "period_end_utc": PERIOD_END,
                "expected_unit_version": world.unit_version(),
            },
            world.officer_headers,
        )
    )
    certify_by_the_facilitator = api_client.certify_snapshot(
        snapshot["id"], world.officer_headers_for("fac")
    )
    certify_by_a_bystander = api_client.certify_snapshot(
        snapshot["id"], world.officer_headers
    )
    return {
        "world": world,
        "encounter": encounter,
        "assessment": assessment,
        "event": event,
        "delivered": delivered,
        "review": review,
        "closed_review": closed_review,
        "close_by_the_anesthesiologist": close_by_the_anesthesiologist,
        "close_by_the_surgical_tech": close_by_the_surgical_tech,
        "close_by_a_bystander": close_by_a_bystander,
        "snapshot": snapshot,
        "certify_by_the_facilitator": certify_by_the_facilitator,
        "certify_by_a_bystander": certify_by_a_bystander,
        "snapshot_at_the_end": get_success_data(
            api_client.get_snapshot(snapshot["id"], world.officer_headers)
        ),
        "encounter_at_the_end": reload_encounter(world, encounter["id"]),
    }


def test_a_crash_section_routes_through_review_even_when_it_met_its_target(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"Then, at the end of that same request, the event moves on from `DELIVERED` without a
    second call: to `REVIEW_PENDING` when `met_target` is false or the `urgency_class` is
    `CATEGORY_1_CRASH`, also setting the encounter's `review_required` to true; and straight
    to `CLOSED` when `met_target` is true and the `urgency_class` is `CATEGORY_2_URGENT`."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    world = setup["world"]
    assert setup["delivered"].status_code == 200
    delivered = get_success_data(setup["delivered"])
    assert_cesarean_event(delivered)
    assert delivered["status"] == "REVIEW_PENDING"
    assert delivered["urgency_class"] == "CATEGORY_1_CRASH"
    assert delivered["decision_to_incision_minutes"] == MEASURED_MINUTES
    assert MEASURED_MINUTES <= CRASH_TARGET_MINUTES
    assert delivered["met_target"] is True
    assert delivered["mobilized_staff_ids"] == [
        world.staff_id("anesthesia"),
        world.staff_id("tech"),
        world.staff_id("neonatal"),
    ]


def test_the_system_and_not_the_caller_chose_the_delivery_mode(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"The system, not the caller, chooses the delivery mode: the encounter's
    `delivery_mode` becomes `CESAREAN_REPEAT` when its `prior_cesarean` is true and
    `CESAREAN_PRIMARY` otherwise, and `delivery_recorded_at` is set to `delivery_at`."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    delivered_encounter = setup["encounter_at_the_end"]
    assert_labor_encounter(delivered_encounter)
    assert delivered_encounter["prior_cesarean"] is False
    assert delivered_encounter["delivery_mode"] == "CESAREAN_PRIMARY"
    assert_instant_equals(
        delivered_encounter["delivery_recorded_at"], DELIVERY_AT, "delivery_recorded_at"
    )
    assert delivered_encounter["is_ntsv"] is True


def test_the_closed_review_is_what_clears_the_state_rung_on_the_case_close(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"A close from `REVIEW_PENDING` requires a `CLOSED` newborn complication review on the
    encounter first, refused otherwise with `ERR_NEWBORN_REVIEW_OPEN`."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    closed_review = setup["closed_review"]
    assert_newborn_review(closed_review)
    assert closed_review["status"] == "CLOSED"
    assert closed_review["facilitator_staff_id"] == setup["world"].staff_id("fac")


def test_the_duty_check_scans_the_whole_mobilised_array(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"The acting `X-User-ID` must not appear anywhere in `mobilized_staff_ids` — the team
    that ran the case cannot sign it off — refused otherwise with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    for refused in (
        setup["close_by_the_anesthesiologist"],
        setup["close_by_the_surgical_tech"],
    ):
        validate_error(
            refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
        )
        reported = refused.json()["data"]["error_id"]
        assert reported != ApiErrorId.ERR_NEWBORN_REVIEW_OPEN.value
        assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value


def test_an_identity_absent_from_the_array_closes_the_same_case(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"Fifth, anyone recorded among the mobilised team of an emergency cesarean may not
    close that case: the surgeons who ran it cannot sign it off."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    world = setup["world"]
    accepted = setup["close_by_a_bystander"]
    assert accepted.status_code == 200
    closed = get_success_data(accepted)
    assert_cesarean_event(closed)
    assert closed["status"] == "CLOSED"
    assert world.staff_id("officer") not in closed["mobilized_staff_ids"]


def test_the_authoritative_cohort_holds_exactly_the_one_delivered_encounter(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"The `ntsv_cesarean_denominator` counts cohort encounters whose `is_ntsv` is true, and
    the `ntsv_cesarean_numerator` counts those same encounters whose `delivery_mode` is
    additionally `CESAREAN_PRIMARY`." Also: "The `episiotomy_denominator` counts cohort
    encounters whose `delivery_mode` is `SPONTANEOUS_VAGINAL` or `OPERATIVE_VAGINAL`, and the
    `episiotomy_numerator` counts those same encounters whose `episiotomy_performed` is
    additionally true."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    snapshot = setup["snapshot"]
    assert_snapshot(snapshot)
    assert snapshot["status"] == "DRAFT"
    assert snapshot["attribution_basis"] == "DELIVERY_COHORT"
    assert snapshot["ntsv_cesarean_denominator"] == 1
    assert snapshot["ntsv_cesarean_numerator"] == 1
    assert snapshot["episiotomy_denominator"] == 0
    assert snapshot["episiotomy_numerator"] == 0


def test_the_empty_episiotomy_denominator_yields_null_and_never_zero(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"Each rate — `ntsv_cesarean_rate_pct` and `episiotomy_rate_pct` — is null when its own
    denominator is 0 — never 0.0 — and otherwise is 100.0 multiplied by that numerator and
    divided by that denominator, rounded to 4 decimal places half-up." Also: "The
    `composite_quality_index` is null when either rate is null, and otherwise is the sum of
    the two rates divided by 2.0, rounded to 2 decimal places half-up."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    snapshot = setup["snapshot"]
    assert snapshot["ntsv_cesarean_rate_pct"] == pytest.approx(FULL_RATE_PCT, abs=1e-9)
    assert snapshot["episiotomy_rate_pct"] is None
    assert snapshot["composite_quality_index"] is None


def test_the_facilitator_inside_the_window_cannot_certify(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"The certifier must not be the facilitator of any newborn complication review inside
    the reporting window, refused otherwise with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    refused = setup["certify_by_the_facilitator"]
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
    )
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_EMPTY_MEASURE_DENOMINATOR.value
    assert reported != ApiErrorId.ERR_MEASURE_PERIOD_NOT_CLOSED.value


def test_the_clean_identity_collects_the_reporting_band_refusal_underneath(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"Both denominators must be 1 or more, since an empty cohort is readable as a draft but
    never certifiable, refused otherwise with `ERR_EMPTY_MEASURE_DENOMINATOR`." Also:
    "**Priority 16** — reporting completeness, the last band of all:
    `ERR_EMPTY_MEASURE_DENOMINATOR`, `ERR_MEASURE_PERIOD_NOT_CLOSED` and
    `ERR_BUNDLE_NOT_CLOSED`, all at HTTP 409, on snapshot certification."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    refused = setup["certify_by_a_bystander"]
    validate_error(refused, ApiErrorId.ERR_EMPTY_MEASURE_DENOMINATOR.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_MEASURE_PERIOD_NOT_CLOSED.value
    )
    assert setup["snapshot"]["episiotomy_denominator"] == 0


def test_neither_refusal_froze_the_draft_row(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"Certification stamps `certified_at` with the current instant and
    `certified_by_user_id` with the acting user and freezes the counts and rates permanently,
    so a delivery recorded inside the window afterwards changes nothing in that row."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    survivor = setup["snapshot_at_the_end"]
    assert_snapshot(survivor)
    assert survivor["status"] == "DRAFT"
    assert survivor["certified_at"] is None
    assert survivor["certified_by_user_id"] is None
    assert survivor["superseded_by_snapshot_id"] is None


def test_the_closed_case_and_closed_review_together_lift_the_encounter_flag(
    one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them,
):
    """"Closing re-derives the encounter's `review_required`, which becomes false once no
    other event or review is open, and drops the encounter from the in-theatre clause of the
    posture derivation."

    Design: Corner/rbac/sod_5_and_sod_6_refuse_the_mobilized_surgeon_the_case_close_and_the_review_facilitator_the_certification
    """
    setup = one_crash_case_and_one_snapshot_probed_by_the_people_named_on_them
    encounter = setup["encounter_at_the_end"]
    assert_labor_encounter(encounter)
    assert encounter["review_required"] is False
