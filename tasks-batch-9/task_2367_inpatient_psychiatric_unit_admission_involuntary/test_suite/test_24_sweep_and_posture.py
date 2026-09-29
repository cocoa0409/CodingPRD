"""Two derivations driven from outside the row that changes: the sweep and the posture.

The sweep is a no-op at exactly the response deadline and fires one millisecond
later, flagging a rights violation that re-derives a unit counter. A unit's posture
is re-derived from its beds on every child change, and the walk down is not monotone.
"""

from test_helpers import (
    BedStatus,
    BedType,
    DischargeDecision,
    DischargeRequestStatus,
    LegalStatus,
    UnitPosture,
    assert_posture_threshold,
    assert_sweep_counts,
    assert_unit_availability,
    build_ward,
    create_admission,
    read_admission,
    read_bed,
    read_discharge_request,
    read_unit,
    request_discharge,
    run_sweep,
    set_bed_status,
    set_clock,
    voluntary_case,
)

SWEEP_UNIT = "Ward 25 Sweep"
SWEEP_BEDS = ({"room_number": "491", "wing_code": "A", "bed_label": "A"},)
RESPONSE_DEADLINE = "2026-09-08T14:00:00.000Z"
AT_THE_DEADLINE = "2026-09-08T14:00:00Z"
ONE_MILLISECOND_LATE = "2026-09-08T14:00:00.001Z"

POSTURE_UNIT = "Ward 26 Posture"
POSTURE_BEDS = (
    {"room_number": "501", "wing_code": "A", "bed_label": "A"},
    {"room_number": "502", "wing_code": "A", "bed_label": "A"},
    {"room_number": "503", "wing_code": "A", "bed_label": "A"},
    {"room_number": "504", "wing_code": "A", "bed_label": "A"},
    {"room_number": "505", "wing_code": "A", "bed_label": "A"},
    {
        "room_number": "506",
        "wing_code": "A",
        "bed_label": "A",
        "bed_type": BedType.SECLUSION.value,
    },
)
STANDARD_BED_COUNT = 5


def _sweep_counters(counts):
    """The three counters that must stay at zero alongside the discharge-request family."""
    return (
        counts["expired_hold_count"],
        counts["expired_restraint_count"],
        counts["expired_consent_count"],
    )


class TestSweepExpiresUnansweredDischargeRequest:
    """The deadline is inclusive, and the expiry is a cascade rather than a status change."""

    def test_the_sweep_is_a_no_op_at_the_deadline_and_flags_a_violation_one_millisecond_later(
        self, api, clock, roster
    ):
        """One millisecond decides between a pending request and a recorded rights violation.

        PRD 2.4: "One sweep performs four families of expiry and reports how many
        records each family touched, as `expired_hold_count`,
        `expired_restraint_count`, `expired_discharge_request_count` and
        `expired_consent_count`: an `ACTIVE` hold whose release deadline has arrived
        moves to `EXPIRED` with its full cascade; a restraint episode still in
        `ORDERED` past its face-to-face deadline, or still in `ACTIVE` at or past its
        authorization end, moves to `EXPIRED_UNAUTHORIZED`; a `PENDING` discharge
        request past its response deadline moves to `EXPIRED_UNANSWERED`; and a
        `MedicationConsent` in `ACTIVE` status whose basis is `EMERGENCY_OVERRIDE` and
        whose `expires_at` has passed moves to `EXPIRED`."

        PRD 2.11: "Each such flag immediately recomputes `open_rights_violation_count`
        on the owning unit, which is defined as the number of that unit's admissions
        carrying a true `rights_violation_flag` whose `placement_status` is anything
        other than `DISCHARGED`."

        Design: Corner/state_machines/compliance_sweep_expires_unanswered_discharge_request_and_flags_violation
        """
        ward = build_ward(
            api,
            name=SWEEP_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=SWEEP_BEDS,
        )
        case = voluntary_case(
            api,
            roster,
            mrn="MRN-2367-SW",
            legal_name="Sweep Case",
            age_years=43,
            gender_care_category="MALE",
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.VOLUNTARY.value,
        )
        pending = request_discharge(api, roster, admission["id"])
        assert pending["response_deadline_at"] == RESPONSE_DEADLINE

        set_clock(api, AT_THE_DEADLINE)
        at_the_deadline = run_sweep(api)
        assert_sweep_counts(at_the_deadline)
        assert at_the_deadline["expired_discharge_request_count"] == 0
        assert _sweep_counters(at_the_deadline) == (0, 0, 0)
        assert (
            read_discharge_request(api, pending["id"])["status"]
            == DischargeRequestStatus.PENDING.value
        )

        set_clock(api, ONE_MILLISECOND_LATE)
        after_the_deadline = run_sweep(api)
        assert after_the_deadline["expired_discharge_request_count"] == 1
        assert _sweep_counters(after_the_deadline) == (0, 0, 0)

        expired = read_discharge_request(api, pending["id"])
        assert expired["status"] == DischargeRequestStatus.EXPIRED_UNANSWERED.value
        assert expired["decision"] == DischargeDecision.PENDING.value
        assert expired["responding_clinician_id"] is None

        assert read_admission(api, admission["id"])["rights_violation_flag"] is True
        assert read_unit(api, ward.id)["open_rights_violation_count"] == 1

        repeated = run_sweep(api)
        assert repeated["expired_discharge_request_count"] == 0
        assert _sweep_counters(repeated) == (0, 0, 0)


class TestUnitPostureReDerivedFromBedChanges:
    """Five beds walk out of service and the posture chain is recomputed each time."""

    def test_taking_beds_out_of_service_walks_the_unit_from_open_to_closed(
        self, api, clock, roster
    ):
        """OPEN at five, OPEN at two, RESTRICTED with nothing spendable at one, CLOSED at zero.

        PRD 3.1: "Step one counts inventory from bed statuses alone, and it considers
        only beds of type `STANDARD` or `LIGATURE_RESISTANT_OBSERVATION` — a
        `SECLUSION` bed is never counted and therefore can never influence posture.
        `licensed_placement_bed_count` is the number of such beds on the unit whose
        `status` is anything other than `OUT_OF_SERVICE`; `raw_available_bed_count` is
        the number of such beds whose `status` is exactly `AVAILABLE`."

        PRD 3.1: "Step two derives `posture` from `raw_available_bed_count` and
        nothing else: first compute a restriction threshold equal to the greater of 1
        and one fifth of `licensed_placement_bed_count` rounded down to a whole
        number; then the posture is `CLOSED` when `raw_available_bed_count` is zero,
        `RESTRICTED` when it is greater than zero but no greater than that threshold,
        and `OPEN` otherwise."

        Design: Corner/state_machines/unit_posture_re_derived_from_child_bed_status_changes
        """
        ward = build_ward(
            api,
            name=POSTURE_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=POSTURE_BEDS,
        )
        baseline = read_unit(api, ward.id)
        assert_unit_availability(
            baseline, licensed=STANDARD_BED_COUNT, raw_available=STANDARD_BED_COUNT
        )
        assert baseline["posture"] == UnitPosture.OPEN.value
        assert baseline["effective_available_bed_count"] == STANDARD_BED_COUNT

        version = baseline["version"]
        for index in range(3):
            patched = set_bed_status(
                api,
                ward.beds[index]["id"],
                BedStatus.OUT_OF_SERVICE.value,
                headers=roster.charge_nurse_headers,
            )
            assert patched["status"] == BedStatus.OUT_OF_SERVICE.value
            assert patched["version"] == ward.beds[index]["version"] + 1
            version += 1
            assert read_unit(api, ward.id)["version"] == version

        three_gone = read_unit(api, ward.id)
        assert_unit_availability(three_gone, licensed=2, raw_available=2)
        assert_posture_threshold(2, 1)
        assert three_gone["posture"] == UnitPosture.OPEN.value
        assert three_gone["effective_available_bed_count"] == 2

        set_bed_status(
            api,
            ward.beds[3]["id"],
            BedStatus.OUT_OF_SERVICE.value,
            headers=roster.charge_nurse_headers,
        )
        version += 1
        four_gone = read_unit(api, ward.id)
        assert_unit_availability(four_gone, licensed=1, raw_available=1)
        assert_posture_threshold(1, 1)
        assert four_gone["posture"] == UnitPosture.RESTRICTED.value
        assert four_gone["effective_available_bed_count"] == 0
        assert four_gone["version"] == version

        set_bed_status(
            api,
            ward.beds[4]["id"],
            BedStatus.OUT_OF_SERVICE.value,
            headers=roster.charge_nurse_headers,
        )
        version += 1
        five_gone = read_unit(api, ward.id)
        assert_unit_availability(five_gone, licensed=0, raw_available=0)
        assert five_gone["posture"] == UnitPosture.CLOSED.value
        assert five_gone["effective_available_bed_count"] == 0
        assert five_gone["version"] == version
        assert five_gone["version"] == baseline["version"] + STANDARD_BED_COUNT

        seclusion = read_bed(api, ward.beds[5]["id"], ward.id)
        assert seclusion["bed_type"] == BedType.SECLUSION.value
        assert seclusion["status"] == BedStatus.AVAILABLE.value
