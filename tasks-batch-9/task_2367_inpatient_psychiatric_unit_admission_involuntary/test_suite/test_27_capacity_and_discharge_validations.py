"""Three preconditions that a client can only satisfy by reading the rule exactly.

The surrogate triple is a biconditional rather than a presence check. An open
petition locks the hold in both directions until it is withdrawn. And the four
discharge preconditions surface strictly one at a time, in their declared order.
"""

from test_helpers import (
    AcuityTier,
    ApiErrorId,
    BedStatus,
    CheckType,
    DeterminationStatus,
    DischargePlanStatus,
    FOLLOW_UP_BASE_DAYS,
    HoldStatus,
    InterventionType,
    LegalStatus,
    PetitionStatus,
    PlacementStatus,
    RestraintStatus,
    SurrogateAuthorityScope,
    SurrogateRelationship,
    UnitPosture,
    active_hold_case,
    admission_version,
    assert_created,
    assert_error,
    assert_monitoring_compliance,
    assert_ok,
    assert_page,
    assert_unit_availability,
    build_ward,
    complete_safety_search,
    conversion_payload,
    create_admission,
    create_petition,
    debrief_payload,
    determine_capacity,
    discharge_payload,
    discharge_plan_payload,
    face_to_face_payload,
    monitoring_check_payload,
    order_restraint,
    place_admission,
    read_admission,
    read_bed,
    read_hold,
    read_patient,
    read_petition,
    read_restraint,
    read_unit,
    release_payload,
    rescind_payload,
    set_clock,
    voluntary_case,
    withdraw_payload,
)

SURROGATE_UNIT = "Ward 32 Surrogate"
CONVERSION_UNIT = "Ward 33 Conversion"
LADDER_UNIT = "Ward 34 Ladder"
NO_BEDS = ()
# Two beds, so PRD 3.1's restriction threshold — "the greater of 1 and one fifth of
# `licensed_placement_bed_count` rounded down" — leaves the unit `OPEN` and an ordinary
# placement is not refused by the `RESTRICTED` safety reserve.
LADDER_BEDS = (
    {"room_number": "541", "wing_code": "A", "bed_label": "A"},
    {"room_number": "542", "wing_code": "A", "bed_label": "A"},
)

SURROGATE_NAME = "Marta Sole"
DETERMINED_AT = "2026-09-03T08:00:00.000Z"

CONVERSION_NOTE = "Patient now agrees to voluntary treatment."

PHYSICAL_HOLD_MINUTES = 30
FIRST_CHECK_AT = "2026-09-03T08:02:00Z"
SECOND_CHECK_AT = "2026-09-03T08:07:00Z"
RELEASE_AT = "2026-09-03T08:10:00Z"
RELEASED_INSTANT = "2026-09-03T08:10:00.000Z"
ACTUAL_MINUTES = 10
REQUIRED_CHECKS = 2
FULL_COMPLIANCE = 100.0
QUARTER_HOURS = 1
STAFF_PARTICIPANTS = 3
FOLLOW_UP_PROVIDER = "Northside Behavioral Clinic"
APPOINTMENT_AT = "2026-09-10T09:00:00Z"
APPOINTMENT_INSTANT = "2026-09-10T09:00:00.000Z"
GUARANTEE_DEADLINE = "2026-09-17T08:10:00.000Z"


def _attempt_discharge(api, roster, admission_id):
    """One physical discharge attempt whose outcome the caller inspects."""
    return api.discharge_admission(
        roster.psychiatrist_headers, admission_id, discharge_payload()
    )


class TestSurrogateBiconditional:
    """Missing fields, a partial triple and forbidden fields all read the same error."""

    def test_the_surrogate_triple_is_required_exactly_when_capacity_is_absent(
        self, api, clock, roster
    ):
        """Three malformed determinations leave the admission version untouched and the fourth is accepted.

        PRD 3.7: "When `capacity_present` is false the body must also carry all three
        surrogate fields: a `surrogate_name`, a `surrogate_relationship` of `SPOUSE`,
        `PARENT`, `ADULT_CHILD` or `GUARDIAN`, and a `surrogate_authority_scope` of
        `NONE`, `MEDICATION_ONLY` or `FULL`. When `capacity_present` is true all three
        must be absent. Either asymmetry — missing surrogate fields on an incapacity
        finding, or surrogate fields supplied alongside a finding of capacity — is
        refused with `ERR_SURROGATE_REQUIRED`."

        PRD 2.9: "`ERR_SURROGATE_REQUIRED` — the surrogate fields are supplied exactly
        when capacity is absent and omitted entirely when capacity is present; on
        capacity determination."

        Design: Corner/validations/surrogate_fields_required_exactly_when_capacity_is_absent
        """
        ward = build_ward(
            api,
            name=SURROGATE_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        case = voluntary_case(
            api,
            roster,
            mrn="MRN-2367-SR",
            legal_name="Surrogate Rules",
            age_years=48,
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
        # PRD 3.2 puts `acuity_score` on the evaluation; PRD 3.5 has the admission copy
        # only `acuity_tier` from it.
        assert case["evaluation"]["acuity_score"] == 8
        assert admission["acuity_tier"] == AcuityTier.MODERATE.value
        first_version = admission_version(api, admission["id"])

        malformed = (
            {
                "admission_id": admission["id"],
                "expected_admission_version": first_version,
                "capacity_present": False,
            },
            {
                "admission_id": admission["id"],
                "expected_admission_version": first_version,
                "capacity_present": False,
                "surrogate_name": SURROGATE_NAME,
            },
            {
                "admission_id": admission["id"],
                "expected_admission_version": first_version,
                "capacity_present": True,
                "surrogate_name": SURROGATE_NAME,
                "surrogate_relationship": SurrogateRelationship.SPOUSE.value,
                "surrogate_authority_scope": SurrogateAuthorityScope.MEDICATION_ONLY.value,
            },
        )
        for payload in malformed:
            refusal = api.create_capacity_determination(
                roster.psychiatrist_headers, payload
            )
            assert_error(refusal, ApiErrorId.SURROGATE_REQUIRED)
            assert admission_version(api, admission["id"]) == first_version

        accepted = assert_created(
            api.create_capacity_determination(
                roster.psychiatrist_headers,
                {
                    "admission_id": admission["id"],
                    "expected_admission_version": first_version,
                    "capacity_present": False,
                    "surrogate_name": SURROGATE_NAME,
                    "surrogate_relationship": SurrogateRelationship.SPOUSE.value,
                    "surrogate_authority_scope": (
                        SurrogateAuthorityScope.MEDICATION_ONLY.value
                    ),
                },
            )
        )
        assert accepted["status"] == DeterminationStatus.ACTIVE.value
        assert accepted["capacity_present"] is False
        assert accepted["surrogate_name"] == SURROGATE_NAME
        assert accepted["surrogate_relationship"] == SurrogateRelationship.SPOUSE.value
        assert (
            accepted["surrogate_authority_scope"]
            == SurrogateAuthorityScope.MEDICATION_ONLY.value
        )
        assert accepted["determined_by_clinician_id"] == roster.psychiatrist["id"]
        assert accepted["determined_at"] == DETERMINED_AT
        assert admission_version(api, admission["id"]) == first_version + 1


class TestConversionBlockedByOpenPetition:
    """The open petition refuses a sibling and the conversion, then releases both."""

    def test_the_identical_conversion_call_succeeds_once_the_petition_is_withdrawn(
        self, api, clock, roster
    ):
        """One lock, two directions: a second petition and a bedside conversion both wait for the withdrawal.

        PRD 3.3: "Conversion is refused with `ERR_HOLD_NOT_ACTIVE` unless the hold is
        `ACTIVE`, and refused with `ERR_PETITION_PENDING` when any petition for that
        hold is in `FILED`, `HEARING_SCHEDULED` or `CONTINUED` — a matter before the
        court may not be settled unilaterally at the bedside."

        PRD 3.3: "Voluntary conversion closes the hold from the admission side and is
        described in §3.5, but its effect on the hold belongs here: the patient's
        `ACTIVE` hold moves `ACTIVE → CONVERTED_VOLUNTARY`, its `closure_reason` is set
        to the supplied `conversion_note`, the patient's `active_hold_count` is
        recomputed with `Patient.version` incremented by one, and the admission's
        `legal_status` flips `INVOLUNTARY → VOLUNTARY` with `Admission.version`
        incremented by one."

        PRD 3.5: "It flips `legal_status` `INVOLUNTARY → VOLUNTARY` and closes the hold
        as described in §3.3, and it never touches the placement axis."

        Design: Corner/validations/convert_to_voluntary_blocked_until_open_petition_is_withdrawn
        """
        ward = build_ward(
            api,
            name=CONVERSION_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-CV",
            legal_name="Convert Case",
            age_years=44,
            gender_care_category="FEMALE",
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )
        determination = determine_capacity(api, roster, admission["id"], True)
        assert determination["status"] == DeterminationStatus.ACTIVE.value
        assert determination["capacity_present"] is True

        petition = create_petition(
            api, roster.psychiatrist_headers, case["hold"]["id"]
        )
        assert petition["status"] == PetitionStatus.FILED.value

        second_petition = api.create_petition(
            roster.psychiatrist_headers,
            {
                "hold_id": case["hold"]["id"],
                "requested_hold_type": "EXTENSION_14D",
                "petition_grounds": "Duplicate filing while the first is still open.",
            },
        )
        assert_error(second_petition, ApiErrorId.PETITION_PENDING)
        assert_page(
            api.list_petitions(
                roster.advocate_headers, hold_id=case["hold"]["id"]
            ),
            1,
        )

        blocked = api.convert_admission_to_voluntary(
            roster.psychiatrist_headers,
            admission["id"],
            conversion_payload(conversion_note=CONVERSION_NOTE),
        )
        assert_error(blocked, ApiErrorId.PETITION_PENDING)
        assert read_hold(api, case["hold"]["id"])["status"] == HoldStatus.ACTIVE.value
        assert (
            read_admission(api, admission["id"])["legal_status"]
            == LegalStatus.INVOLUNTARY.value
        )

        assert_ok(
            api.withdraw_petition(
                roster.psychiatrist_headers, petition["id"], withdraw_payload()
            )
        )
        assert (
            read_petition(api, petition["id"])["status"]
            == PetitionStatus.WITHDRAWN.value
        )

        converted = assert_ok(
            api.convert_admission_to_voluntary(
                roster.psychiatrist_headers,
                admission["id"],
                conversion_payload(conversion_note=CONVERSION_NOTE),
            )
        )
        assert converted["legal_status"] == LegalStatus.VOLUNTARY.value
        assert converted["placement_status"] == PlacementStatus.PENDING_PLACEMENT.value

        closed = read_hold(api, case["hold"]["id"])
        assert closed["status"] == HoldStatus.CONVERTED_VOLUNTARY.value
        assert closed["closure_reason"] == CONVERSION_NOTE
        assert read_patient(api, case["patient"]["id"])["active_hold_count"] == 0


class TestDischargePreconditionLadder:
    """One admission breaches three preconditions and clears them in the declared order."""

    def test_each_discharge_precondition_surfaces_only_once_the_previous_one_is_cleared(
        self, api, clock, roster
    ):
        """The open episode hides the active hold, which in turn hides the missing plan.

        PRD 3.8: "Four preconditions apply. The admission's `placement_status` must be
        `PLACED` or `DISCHARGE_READY`, or the request fails with
        `ERR_ADMISSION_NOT_DISCHARGEABLE`. Its `legal_status` must be `VOLUNTARY`, or
        the request fails with `ERR_ACTIVE_HOLD_BLOCKS_DISCHARGE`. Its
        `discharge_plan_status` must be `APPOINTMENT_SECURED` and its
        `follow_up_appointment_at` must still lie strictly in the future relative to the
        current clock, or the request fails with `ERR_DISCHARGE_PLAN_INCOMPLETE` — a
        secured appointment that has since gone stale is no guarantee at all. And no
        restraint episode of that admission may remain in `ORDERED`, `ACTIVE` or
        `RELEASED`; an episode released but never debriefed still blocks discharge, and
        the refusal is `ERR_OPEN_RESTRAINT_EPISODE`."

        PRD 2.9: "Many operations are guarded by several checks at once, and which
        error a client sees is part of the contract. Checks are evaluated in the
        following fixed order, and the first failing check terminates the request."

        PRD 3.6: "Debriefing closes the episode properly. Performed by an
        `AttendingPsychiatrist` or a `ChargeNurse` on an episode in `RELEASED`, it
        carries `patient_participated_in_debrief`, a `staff_participants_count` of at
        least 1, and a `debrief_note`; it moves the episode `RELEASED → DEBRIEFED` and
        stamps `debrief_completed_at` from the clock."

        Design: Corner/validations/discharge_precondition_ladder_reveals_one_error_at_a_time
        """
        ward = build_ward(
            api,
            name=LADDER_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=LADDER_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-LD",
            legal_name="Ladder Case",
            age_years=47,
            gender_care_category="MALE",
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )
        complete_safety_search(api, roster, admission["id"])
        placed = place_admission(api, roster, admission["id"], ward.id)
        assert placed["placement_status"] == PlacementStatus.PLACED.value
        assert placed["bed_id"] == ward.beds[0]["id"]
        # Two licensed beds, one now OCCUPIED: raw_available is 1 and the threshold is
        # max(1, floor(2/5)) = 1, so PRD 3.1 puts the unit in RESTRICTED with the one
        # remaining bed held back in reserve.
        occupied_unit = read_unit(api, ward.id)
        assert occupied_unit["posture"] == UnitPosture.RESTRICTED.value
        assert occupied_unit["effective_available_bed_count"] == 0

        episode = order_restraint(
            api,
            roster,
            admission["id"],
            InterventionType.PHYSICAL_HOLD.value,
            PHYSICAL_HOLD_MINUTES,
        )
        assert episode["status"] == RestraintStatus.ORDERED.value

        assert_error(
            _attempt_discharge(api, roster, admission["id"]),
            ApiErrorId.OPEN_RESTRAINT_EPISODE,
        )

        reviewed = assert_ok(
            api.record_face_to_face(
                roster.psychiatrist_headers, episode["id"], face_to_face_payload()
            )
        )
        assert reviewed["status"] == RestraintStatus.ACTIVE.value

        for moment, check_type in (
            (FIRST_CHECK_AT, CheckType.CIRCULATION.value),
            (SECOND_CHECK_AT, CheckType.TOILETING.value),
        ):
            set_clock(api, moment)
            assert_ok(
                api.add_monitoring_check(
                    roster.charge_nurse_headers,
                    episode["id"],
                    monitoring_check_payload(check_type=check_type),
                )
            )

        set_clock(api, RELEASE_AT)
        released = assert_ok(
            api.release_restraint(
                roster.charge_nurse_headers, episode["id"], release_payload()
            )
        )
        assert released["status"] == RestraintStatus.RELEASED.value
        assert released["released_at"] == RELEASED_INSTANT
        assert released["actual_duration_minutes"] == ACTUAL_MINUTES
        assert_monitoring_compliance(
            released,
            required=REQUIRED_CHECKS,
            grid_satisfied=REQUIRED_CHECKS,
            logged=REQUIRED_CHECKS,
        )
        assert released["grid_compliance_pct"] == FULL_COMPLIANCE
        assert released["raw_compliance_pct"] == FULL_COMPLIANCE

        assert_error(
            _attempt_discharge(api, roster, admission["id"]),
            ApiErrorId.OPEN_RESTRAINT_EPISODE,
        )

        debriefed = assert_ok(
            api.debrief_restraint(
                roster.psychiatrist_headers,
                episode["id"],
                debrief_payload(staff_participants_count=STAFF_PARTICIPANTS),
            )
        )
        assert debriefed["status"] == RestraintStatus.DEBRIEFED.value
        assert debriefed["debrief_completed_at"] == RELEASED_INSTANT
        assert (
            read_admission(api, admission["id"])["observation_staff_quarter_hours"]
            == QUARTER_HOURS
        )

        assert_error(
            _attempt_discharge(api, roster, admission["id"]),
            ApiErrorId.ACTIVE_HOLD_BLOCKS_DISCHARGE,
        )

        rescinded = assert_ok(
            api.rescind_hold(
                roster.psychiatrist_headers, case["hold"]["id"], rescind_payload()
            )
        )
        assert rescinded["status"] == HoldStatus.RESCINDED.value
        assert read_patient(api, case["patient"]["id"])["active_hold_count"] == 0
        freed = read_admission(api, admission["id"])
        assert freed["legal_status"] == LegalStatus.VOLUNTARY.value
        assert freed["placement_status"] == PlacementStatus.PLACED.value

        assert_error(
            _attempt_discharge(api, roster, admission["id"]),
            ApiErrorId.DISCHARGE_PLAN_INCOMPLETE,
        )

        planned = assert_ok(
            api.submit_discharge_plan(
                roster.psychiatrist_headers,
                admission["id"],
                discharge_plan_payload(
                    follow_up_appointment_at=APPOINTMENT_AT,
                    follow_up_provider_name=FOLLOW_UP_PROVIDER,
                ),
            )
        )
        assert planned["follow_up_provider_name"] == FOLLOW_UP_PROVIDER
        assert planned["follow_up_appointment_at"] == APPOINTMENT_INSTANT
        assert (
            planned["follow_up_guarantee_days"]
            == FOLLOW_UP_BASE_DAYS[LegalStatus.VOLUNTARY.value][
                AcuityTier.MODERATE.value
            ]
        )
        assert planned["follow_up_guarantee_deadline_at"] == GUARANTEE_DEADLINE
        assert (
            planned["discharge_plan_status"]
            == DischargePlanStatus.APPOINTMENT_SECURED.value
        )

        discharged = assert_ok(_attempt_discharge(api, roster, admission["id"]))
        assert discharged["placement_status"] == PlacementStatus.DISCHARGED.value
        assert discharged["discharged_at"] == RELEASED_INSTANT
        assert discharged["bed_id"] == ward.beds[0]["id"]
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.AVAILABLE.value
        )
        emptied = read_unit(api, ward.id)
        assert_unit_availability(emptied, licensed=2, raw_available=2, occupied=0)
        assert emptied["posture"] == UnitPosture.OPEN.value
        assert emptied["effective_available_bed_count"] == 2
        assert (
            read_restraint(api, episode["id"])["status"]
            == RestraintStatus.DEBRIEFED.value
        )
