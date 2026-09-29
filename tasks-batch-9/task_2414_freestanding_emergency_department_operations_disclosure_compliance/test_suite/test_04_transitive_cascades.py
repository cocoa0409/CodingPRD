"""Cascades that travel three or more hops from the request that started them.

A refusal recorded at the registration desk ends up rewriting a volume forecast's
method and giving the facility a physician-coverage deficit; an insurance-motivated
transfer decline releases an ambulance unit, unsaturates two capacity states, walks
the patient back to a clinical state and appends the gravest finding in the ledger.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_defect_count,
    assert_facility_unit_totals,
    assert_hours_equal,
    assert_ledger_entry,
    assert_mou_unit_ledger,
    assert_posture,
)
from test_helpers.factories import make_transfer_decline_payload
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    COORDINATOR,
    OFFICER,
    coverage_summary,
    create_physician_shift,
    create_transfer_order,
    create_volume_forecast,
    ledger_entries,
    open_facility,
    read_ambulance_mou,
    read_encounter,
    read_facility,
    refuse_disclosure,
    register_encounter,
    transfer_ready_encounter,
)

REFUSAL_FACILITY = {"observation_bed_count": 4, "max_concurrent_physicians": 2}
HISTORY = [22, 19, 26, 31, 18, 24, 29]
SHIFTS = (
    ("doc-a", "2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z"),
    ("doc-b", "2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z"),
    ("doc-a", "2026-08-02T00:00:00Z", "2026-08-02T12:00:00Z"),
)


def _facility_comfortably_staffed_against_a_trailing_mean_requirement():
    """A two-day trailing-mean forecast requiring 32.50 hours, with 36.00 scheduled."""
    context = open_facility(facility_overrides=REFUSAL_FACILITY)
    facility_id = context["facility_id"]
    forecast = create_volume_forecast(
        facility_id,
        period_start_date="2026-08-01",
        period_days=2,
        historical_daily_volumes=HISTORY,
        method="TRAILING_MEAN",
    )
    for clinician_user_id, start_utc, end_utc in SHIFTS:
        create_physician_shift(
            facility_id,
            clinician_user_id=clinician_user_id,
            role_type="PHYSICIAN",
            board_certified=True,
            start_utc=start_utc,
            end_utc=end_utc,
        )
    context.update({"forecast_id": forecast["id"], "forecast": forecast})
    return context


def _refuse_for(facility_id, patient_reference):
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference=patient_reference,
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    return refuse_disclosure(encounter["id"])


def test_third_disclosure_refusal_restricts_the_facility_and_rewrites_its_forecast_method():
    """Hops one through three: defect counter, posture, forecast variant.

    PRD 3.6: "If the counter has now reached 3 and `license_status` is `ACTIVE`, the
    posture moves `OPEN → RESTRICTED` and `restricted_service_codes` becomes `MRI`
    and `THROMBOLYTIC`. Because the posture became `RESTRICTED`, every `ACTIVE`
    volume forecast of the facility whose `method` is `TRAILING_MEAN` is rewritten to
    `PEAK_ADJUSTED` with `escalated_by_posture` set true and its required hours
    recomputed."  PRD 2.8 fixes where the counter bites: "The defect threshold is
    inclusive — a count of exactly 3 restricts the facility, a count of 2 does not."
    Recomputation under the conservative variant lifts the daily volume from 24.14 to
    0.60 * 31 + 0.40 * 24.14 = 28.26 and the two-day requirement from 32.50 to 38.00.

    Design: Difficulty/transitive_cascade/third_disclosure_refusal_cascades_defect_posture_forecast_method_and_coverage_deficit
    """
    context = _facility_comfortably_staffed_against_a_trailing_mean_requirement()
    facility_id = context["facility_id"]

    _refuse_for(facility_id, "PT-5001")
    _refuse_for(facility_id, "PT-5002")

    after_two = read_facility(facility_id)
    assert_defect_count(after_two, 2)
    assert_posture(after_two, "OPEN")

    third = _refuse_for(facility_id, "PT-5003")

    facility = read_facility(facility_id)
    assert_defect_count(facility, 3)
    assert_posture(facility, "RESTRICTED")
    assert sorted(facility["restricted_service_codes"]) == ["MRI", "THROMBOLYTIC"]

    forecast = validate_success(
        api_client.get_volume_forecast(context["forecast_id"], ADMIN)
    )
    assert forecast["status"] == "ACTIVE"
    assert forecast["method"] == "PEAK_ADJUSTED"
    assert forecast["escalated_by_posture"] is True
    assert_hours_equal(forecast["forecast_daily_volume"], "28.26", "escalated volume")
    assert_hours_equal(
        forecast["required_physician_hours_per_day"], "19.00", "escalated per day"
    )
    assert_hours_equal(
        forecast["required_physician_hours_total"], "38.00", "escalated total"
    )
    assert_hours_equal(
        forecast["required_board_certified_hours_total"], "28.50", "escalated board-cert"
    )

    entries = ledger_entries(facility_id)
    assert_ledger_entry(
        entries,
        "DISCLOSURE_REFUSED",
        severity="MAJOR",
        subject_type="ENCOUNTER",
        subject_id=third["id"],
        defect_counted=True,
        count=3,
    )
    assert_ledger_entry(entries, "POSTURE_CHANGE", defect_counted=False)


def test_the_forecast_escalation_second_hop_creates_a_coverage_deficit_out_of_nowhere():
    """Hop four: the reconciliation runs again and the facility acquires a deficit.

    PRD 3.4: "A facility that was comfortably staffed against a trailing-mean
    requirement can therefore acquire a coverage deficit the instant a disclosure
    refusal is recorded at its registration desk, with no coverage-related request
    having been made at all."  36.00 scheduled hours cover the 32.50-hour
    trailing-mean requirement but not the 38.00-hour escalated one, and PRD 3.4 pins
    both consequences: "`coverage_deficit_hours` is the shortfall of
    `required_physician_hours_total` against `scheduled_physician_hours`, rounded half
    up to two decimals, and floored at 0 so that over-coverage never produces a
    negative deficit" and "the facility's `coverage_deficit_flag` is set to true when
    `coverage_deficit_hours` is greater than 0 and false otherwise."

    Design: Difficulty/transitive_cascade/third_disclosure_refusal_cascades_defect_posture_forecast_method_and_coverage_deficit
    """
    context = _facility_comfortably_staffed_against_a_trailing_mean_requirement()
    facility_id = context["facility_id"]

    before = coverage_summary(facility_id, OFFICER)
    assert before["forecast_method"] == "TRAILING_MEAN"
    assert_hours_equal(before["required_physician_hours_total"], "32.50", "requirement")
    assert_hours_equal(before["scheduled_physician_hours"], "36.00", "scheduled")
    assert_hours_equal(before["coverage_deficit_hours"], "0.00", "deficit before")
    assert before["coverage_compliant"] is True
    assert before["coverage_deficit_flag"] is False

    for index in range(3):
        _refuse_for(facility_id, f"PT-51{index:02d}")

    after = coverage_summary(facility_id, OFFICER)
    assert after["compliance_posture"] == "RESTRICTED"
    assert after["forecast_method"] == "PEAK_ADJUSTED"
    assert after["selected_volume_forecast_id"] == context["forecast_id"]
    assert_hours_equal(after["required_physician_hours_total"], "38.00", "requirement")
    assert_hours_equal(after["scheduled_physician_hours"], "36.00", "scheduled")
    assert_hours_equal(after["board_certified_hours"], "36.00", "board-certified")
    assert_hours_equal(after["coverage_deficit_hours"], "2.00", "deficit after")
    assert after["coverage_compliant"] is False
    assert after["coverage_deficit_flag"] is True
    assert read_facility(facility_id)["coverage_deficit_flag"] is True


def _single_unit_reservation():
    """A screened acuity-4 patient holding the memorandum's only ambulance unit."""
    context = transfer_ready_encounter(
        acuity_level=4, service_line="CARDIAC", mou_overrides={"units_committed": 1}
    )
    order = create_transfer_order(
        context["encounter_id"],
        context["agreement_id"],
        context["mou_id"],
        context["encounter_version"],
    )
    context.update({"order_id": order["id"], "order": order})
    return context


def test_insurance_decline_releases_the_unit_and_unsaturates_both_capacity_states():
    """Hops one through three: the reservation, the memorandum, the facility totals.

    PRD 3.8: "`reserved_unit_count` drops to 0; because the order has left the
    reserving statuses, the memorandum's `units_reserved` decreases by one and
    `units_available` is recomputed as `units_committed` less `units_reserved`;
    because availability is now above 0, that memorandum's `saturation_state` moves
    `SATURATED → AVAILABLE`; and because its availability changed, the facility's
    `ambulance_units_reserved_total` is recomputed and `transfer_capacity_state` moves
    `SATURATED → AVAILABLE`."  PRD 2.10 requires the round trip to be exact: "a
    reservation followed by its compensating release — a decline, a supersede
    cancellation, or a completion — must return the reserved sum to exactly the value
    it held before the reservation."

    Design: Difficulty/transitive_cascade/insurance_based_transfer_decline_cascades_unit_release_saturation_and_capacity_state
    """
    context = _single_unit_reservation()

    assert context["order"]["reserved_unit_count"] == 1
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=1, available=0)
    reserved_facility = read_facility(context["facility_id"])
    assert_facility_unit_totals(reserved_facility, committed=1, reserved=1)
    assert reserved_facility["transfer_capacity_state"] == "SATURATED"

    declined = validate_success(
        api_client.decline_transfer_order(
            context["order_id"], make_transfer_decline_payload("INSURANCE"), COORDINATOR
        )
    )

    assert declined["status"] == "DECLINED"
    assert declined["reserved_unit_count"] == 0
    assert declined["decline_reason"] == "INSURANCE"

    mou = read_ambulance_mou(context["mou_id"])
    assert_mou_unit_ledger(mou, reserved=0, available=1)
    assert mou["saturation_state"] == "AVAILABLE"

    facility = read_facility(context["facility_id"])
    assert_facility_unit_totals(facility, committed=1, reserved=0)
    assert facility["transfer_capacity_state"] == "AVAILABLE"


def test_insurance_decline_counts_a_critical_defect_and_walks_the_patient_back():
    """Hops four and five: the clinical return path and the gravest ledger finding.

    PRD 3.8: "A decline whose `decline_reason` is `INSURANCE` is treated as the
    gravest finding this system records. It appends a ledger entry with `event_type`
    `TRANSFER_DECLINED_FOR_INSURANCE`, `severity` `CRITICAL`, `subject_type`
    `TRANSFER_ORDER`, `subject_id` set to the declined order's id and
    `defect_counted` true, increments the facility's `open_compliance_defect_count` by
    1, and runs the full posture recomputation cascade including the forecast
    escalation."  The patient never held a bed, so PRD 3.8's second return path
    applies: "`TRANSFER_PENDING → MSE_COMPLETE` when it is false".  One counted defect
    is below the threshold PRD 2.8 sets, so the posture stays `OPEN`.

    Design: Difficulty/transitive_cascade/insurance_based_transfer_decline_cascades_unit_release_saturation_and_capacity_state
    """
    context = _single_unit_reservation()

    validate_success(
        api_client.decline_transfer_order(
            context["order_id"], make_transfer_decline_payload("INSURANCE"), COORDINATOR
        )
    )

    encounter = read_encounter(context["encounter_id"])
    assert encounter["clinical_state"] == "MSE_COMPLETE"
    assert encounter["observation_bed_held"] is False
    assert encounter["declined_transfer_count"] == 1

    facility = read_facility(context["facility_id"])
    assert_defect_count(facility, 1)
    assert_posture(facility, "OPEN")

    assert_ledger_entry(
        ledger_entries(context["facility_id"]),
        "TRANSFER_DECLINED_FOR_INSURANCE",
        severity="CRITICAL",
        subject_type="TRANSFER_ORDER",
        subject_id=context["order_id"],
        defect_counted=True,
        count=1,
    )
