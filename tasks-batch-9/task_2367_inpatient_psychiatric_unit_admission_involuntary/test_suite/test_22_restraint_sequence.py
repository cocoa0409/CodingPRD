"""The restraint episode lifecycle: ordered, reviewed, released, debriefed.

Each action names the one status it accepts, the in-person review closes on a
millisecond, the reviewer may be the orderer only for a physical hold, and the
duration ceiling depends on both the intervention and the patient's age.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_HEADERS,
    InterventionType,
    LegalStatus,
    MONITORING_INTERVAL_MINUTES,
    RESTRAINT_CEILING_MINUTES,
    RestraintStatus,
    assert_created,
    assert_error,
    assert_ok,
    assert_page,
    build_ward,
    create_admission,
    debrief_payload,
    face_to_face_payload,
    monitoring_check_payload,
    order_restraint,
    read_restraint,
    release_payload,
    restraint_payload,
    set_clock,
    voluntary_case,
)

SEQUENCE_UNIT = "Ward 20 Sequence"
WINDOW_UNIT = "Ward 21 Window"
DUTIES_UNIT = "Ward 22 Duties"
CEILING_UNIT = "Ward 23 Ceilings"
NO_BEDS = ()

PINNED_INSTANT = "2026-09-03T08:00:00.000Z"
PHYSICAL_HOLD_MINUTES = 20
PHYSICAL_HOLD_END = "2026-09-03T08:20:00Z"
PHYSICAL_HOLD_END_INSTANT = "2026-09-03T08:20:00.000Z"

MECHANICAL_MINUTES = 120
DUTIES_PHYSICAL_MINUTES = 30
FACE_TO_FACE_DEADLINE = "2026-09-03T09:00:00.000Z"
AT_THE_DEADLINE = "2026-09-03T09:00:00Z"
ONE_MILLISECOND_LATE = "2026-09-03T09:00:00.001Z"

MINOR_PHYSICAL_CEILING = RESTRAINT_CEILING_MINUTES[True][
    InterventionType.PHYSICAL_HOLD.value
]
MINOR_MECHANICAL_CEILING = RESTRAINT_CEILING_MINUTES[True][
    InterventionType.MECHANICAL_RESTRAINT.value
]
ADULT_PHYSICAL_CEILING = RESTRAINT_CEILING_MINUTES[False][
    InterventionType.PHYSICAL_HOLD.value
]
ADULT_MECHANICAL_CEILING = RESTRAINT_CEILING_MINUTES[False][
    InterventionType.MECHANICAL_RESTRAINT.value
]
MINOR_PHYSICAL_UNTIL = "2026-09-03T08:30:00.000Z"
ADULT_MECHANICAL_UNTIL = "2026-09-03T09:01:00.000Z"


def _pending_admission(api, roster, unit_id, *, mrn, legal_name, age_years, gender):
    """A voluntary agitation case admitted to the named unit but not yet placed."""
    case = voluntary_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender,
        danger_to_self=False,
        danger_to_others=True,
        grave_disability=True,
    )
    case["admission"] = create_admission(
        api,
        roster,
        case["patient"]["id"],
        case["evaluation"]["id"],
        unit_id,
        requested_legal_status=LegalStatus.VOLUNTARY.value,
    )
    return case


def _order(api, roster, admission_id, intervention_type, minutes, headers=None):
    """Attempt one restraint order without asserting the outcome."""
    return api.create_restraint(
        headers or roster.psychiatrist_headers,
        restraint_payload(
            admission_id=admission_id,
            intervention_type=intervention_type,
            ordered_duration_minutes=minutes,
        ),
    )


class TestRestraintActionSequence:
    """Every restraint action names one acceptable status and refuses the others."""

    def test_each_restraint_action_is_refused_from_the_wrong_status(
        self, api, clock, roster
    ):
        """Release before review, debrief before release, a second review and a late check all fail.

        PRD 2.9: "`ERR_RESTRAINT_INVALID_STATE` — the episode is in the status the
        action needs: `ORDERED` for the face-to-face review, `ACTIVE` for release,
        either `ORDERED` or `ACTIVE` for appending a monitoring check, and `RELEASED`
        for debriefing."

        PRD 3.6: "Release is performed by a `ChargeNurse` or an
        `AttendingPsychiatrist` with a `release_note` and requires the episode to be
        `ACTIVE`. It moves the episode `ACTIVE → RELEASED`, stamps `released_at` from
        the logical clock, and computes the episode's compliance record.
        `actual_duration_minutes` is the elapsed interval from `started_at` to
        `released_at` expressed in whole minutes with any partial minute discarded.
        `required_check_count` is `actual_duration_minutes` divided by
        `monitoring_interval_minutes`, rounded up to the next whole number."

        Design: Corner/state_machines/restraint_actions_out_of_sequence_rejected_as_invalid_state
        """
        ward = build_ward(
            api,
            name=SEQUENCE_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=NO_BEDS,
        )
        case = _pending_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-SQ",
            legal_name="Sequence Guard",
            age_years=41,
            gender="FEMALE",
        )
        episode = order_restraint(
            api,
            roster,
            case["admission"]["id"],
            InterventionType.PHYSICAL_HOLD.value,
            PHYSICAL_HOLD_MINUTES,
        )
        assert episode["status"] == RestraintStatus.ORDERED.value

        early_release = api.release_restraint(
            roster.charge_nurse_headers, episode["id"], release_payload()
        )
        assert_error(early_release, ApiErrorId.RESTRAINT_INVALID_STATE)
        assert read_restraint(api, episode["id"])["released_at"] is None

        reviewed = assert_ok(
            api.record_face_to_face(
                roster.psychiatrist_headers, episode["id"], face_to_face_payload()
            )
        )
        assert reviewed["status"] == RestraintStatus.ACTIVE.value
        assert reviewed["face_to_face_at"] == PINNED_INSTANT

        early_debrief = api.debrief_restraint(
            roster.psychiatrist_headers, episode["id"], debrief_payload()
        )
        assert_error(early_debrief, ApiErrorId.RESTRAINT_INVALID_STATE)
        assert read_restraint(api, episode["id"])["debrief_completed_at"] is None

        second_review = api.record_face_to_face(
            roster.second_psychiatrist_headers, episode["id"], face_to_face_payload()
        )
        assert_error(second_review, ApiErrorId.RESTRAINT_INVALID_STATE)

        set_clock(api, PHYSICAL_HOLD_END)
        released = assert_ok(
            api.release_restraint(
                roster.charge_nurse_headers, episode["id"], release_payload()
            )
        )
        assert released["status"] == RestraintStatus.RELEASED.value
        assert released["released_at"] == PHYSICAL_HOLD_END_INSTANT
        assert released["actual_duration_minutes"] == PHYSICAL_HOLD_MINUTES
        assert released["required_check_count"] == PHYSICAL_HOLD_MINUTES // (
            MONITORING_INTERVAL_MINUTES[InterventionType.PHYSICAL_HOLD.value]
        )
        assert released["grid_compliance_pct"] == 0.0
        assert released["raw_compliance_pct"] == 0.0

        late_check = api.add_monitoring_check(
            roster.charge_nurse_headers, episode["id"], monitoring_check_payload()
        )
        assert_error(late_check, ApiErrorId.RESTRAINT_INVALID_STATE)
        assert read_restraint(api, episode["id"])["monitoring_check_log"] == []


class TestFaceToFaceWindowBoundary:
    """The review deadline is inclusive to the millisecond."""

    def test_a_review_at_the_deadline_is_accepted_and_one_millisecond_later_is_not(
        self, api, clock, roster
    ):
        """Two identical episodes diverge on a single millisecond of review timing.

        PRD 3.6: "`face_to_face_deadline_at` is `started_at` plus 60 minutes."

        PRD 3.6: "The in-person review is what authorizes continuation. Performed by
        an `AttendingPsychiatrist` with an `assessment_note`, it moves the episode
        `ORDERED → ACTIVE`, stamps `face_to_face_at` from the clock and
        `face_to_face_clinician_id` from the header. It must arrive at or before
        `face_to_face_deadline_at`; strictly later is
        `ERR_FACE_TO_FACE_WINDOW_CLOSED`."

        Design: Corner/state_machines/face_to_face_at_deadline_accepted_one_millisecond_later_rejected
        """
        ward = build_ward(
            api,
            name=WINDOW_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=NO_BEDS,
        )
        on_time = _pending_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-F1",
            legal_name="Window On Time",
            age_years=34,
            gender="FEMALE",
        )
        late = _pending_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-F2",
            legal_name="Window Late",
            age_years=35,
            gender="FEMALE",
        )
        episodes = {}
        for label, case in (("on_time", on_time), ("late", late)):
            episodes[label] = order_restraint(
                api,
                roster,
                case["admission"]["id"],
                InterventionType.MECHANICAL_RESTRAINT.value,
                MECHANICAL_MINUTES,
            )
            assert episodes[label]["face_to_face_deadline_at"] == FACE_TO_FACE_DEADLINE

        set_clock(api, AT_THE_DEADLINE)
        accepted = assert_ok(
            api.record_face_to_face(
                roster.second_psychiatrist_headers,
                episodes["on_time"]["id"],
                face_to_face_payload(),
            )
        )
        assert accepted["status"] == RestraintStatus.ACTIVE.value
        assert accepted["face_to_face_at"] == FACE_TO_FACE_DEADLINE

        set_clock(api, ONE_MILLISECOND_LATE)
        refused = api.record_face_to_face(
            roster.second_psychiatrist_headers,
            episodes["late"]["id"],
            face_to_face_payload(),
        )
        assert_error(refused, ApiErrorId.FACE_TO_FACE_WINDOW_CLOSED)

        stalled = read_restraint(api, episodes["late"]["id"])
        assert stalled["status"] == RestraintStatus.ORDERED.value
        assert stalled["face_to_face_at"] is None
        assert stalled["face_to_face_clinician_id"] is None


class TestFaceToFaceSegregationByInterventionType:
    """The orderer may review only the intervention where hands are on the patient."""

    def test_the_orderer_may_review_a_physical_hold_but_not_a_mechanical_restraint(
        self, api, clock, roster
    ):
        """Same clinician, same clock, two interventions, two different answers.

        PRD 3.6: "For a `MECHANICAL_RESTRAINT` or a `SECLUSION` the reviewer must
        differ from the orderer; for a `PHYSICAL_HOLD` the same clinician may do
        both."

        Design: Corner/state_machines/face_to_face_by_orderer_allowed_for_physical_hold_only
        """
        ward = build_ward(
            api,
            name=DUTIES_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=NO_BEDS,
        )
        physical_case = _pending_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-D1",
            legal_name="Duties Physical",
            age_years=29,
            gender="FEMALE",
        )
        mechanical_case = _pending_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-D2",
            legal_name="Duties Mechanical",
            age_years=33,
            gender="FEMALE",
        )
        physical = order_restraint(
            api,
            roster,
            physical_case["admission"]["id"],
            InterventionType.PHYSICAL_HOLD.value,
            DUTIES_PHYSICAL_MINUTES,
        )
        mechanical = order_restraint(
            api,
            roster,
            mechanical_case["admission"]["id"],
            InterventionType.MECHANICAL_RESTRAINT.value,
            MECHANICAL_MINUTES,
        )

        self_reviewed = assert_ok(
            api.record_face_to_face(
                roster.psychiatrist_headers, physical["id"], face_to_face_payload()
            )
        )
        assert self_reviewed["status"] == RestraintStatus.ACTIVE.value
        assert (
            self_reviewed["face_to_face_clinician_id"]
            == self_reviewed["ordered_by_clinician_id"]
        )
        assert self_reviewed["face_to_face_clinician_id"] == roster.psychiatrist["id"]

        refused = api.record_face_to_face(
            roster.psychiatrist_headers, mechanical["id"], face_to_face_payload()
        )
        assert_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)
        assert (
            read_restraint(api, mechanical["id"])["status"]
            == RestraintStatus.ORDERED.value
        )

        independent = assert_ok(
            api.record_face_to_face(
                roster.second_psychiatrist_headers,
                mechanical["id"],
                face_to_face_payload(),
            )
        )
        assert independent["status"] == RestraintStatus.ACTIVE.value
        assert (
            independent["face_to_face_clinician_id"]
            == roster.second_psychiatrist["id"]
        )


class TestRestraintDurationCeilings:
    """The ceiling table has four cells and each is probed at its edge."""

    def test_the_ceiling_depends_on_both_the_intervention_and_the_patient_age(
        self, api, clock, roster
    ):
        """A minor's physical hold stops at 30 minutes where an adult's mechanical order runs to 240.

        PRD 3.6: "Duration ceilings depend on both the patient's age and the
        intervention: for an adult, 60 minutes for a `PHYSICAL_HOLD` and 240 minutes
        for either other type; for a patient whose `is_minor` is true, 30 minutes for
        a `PHYSICAL_HOLD` and 120 minutes for either other type. An order above its
        ceiling is refused with `ERR_RESTRAINT_DURATION_EXCEEDS_LIMIT`."

        PRD 3.6: "And `monitoring_interval_minutes` is 5 for a `PHYSICAL_HOLD` and 15
        for a `MECHANICAL_RESTRAINT` or a `SECLUSION` — the tighter cadence for the
        intervention where a clinician's hands are physically on the patient."

        Design: Corner/state_machines/restraint_duration_ceiling_varies_by_age_and_intervention_type
        """
        ward = build_ward(
            api,
            name=CEILING_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=NO_BEDS,
        )
        minor = _pending_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-M1",
            legal_name="Minor Ceiling",
            age_years=15,
            gender="MALE",
        )
        adult = _pending_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-A1",
            legal_name="Adult Ceiling",
            age_years=40,
            gender="MALE",
        )
        assert minor["patient"]["is_minor"] is True
        assert adult["patient"]["is_minor"] is False

        at_the_minor_ceiling = assert_created(
            _order(
                api,
                roster,
                minor["admission"]["id"],
                InterventionType.PHYSICAL_HOLD.value,
                MINOR_PHYSICAL_CEILING,
            )
        )
        assert at_the_minor_ceiling["authorized_until_at"] == MINOR_PHYSICAL_UNTIL
        assert (
            at_the_minor_ceiling["monitoring_interval_minutes"]
            == MONITORING_INTERVAL_MINUTES[InterventionType.PHYSICAL_HOLD.value]
        )

        for intervention, minutes in (
            (InterventionType.PHYSICAL_HOLD.value, MINOR_PHYSICAL_CEILING + 1),
            (InterventionType.MECHANICAL_RESTRAINT.value, MINOR_MECHANICAL_CEILING + 1),
        ):
            assert_error(
                _order(api, roster, minor["admission"]["id"], intervention, minutes),
                ApiErrorId.RESTRAINT_DURATION_EXCEEDS_LIMIT,
            )

        assert_error(
            _order(
                api,
                roster,
                adult["admission"]["id"],
                InterventionType.PHYSICAL_HOLD.value,
                ADULT_PHYSICAL_CEILING + 1,
            ),
            ApiErrorId.RESTRAINT_DURATION_EXCEEDS_LIMIT,
        )

        above_the_minor_ceiling = assert_created(
            _order(
                api,
                roster,
                adult["admission"]["id"],
                InterventionType.MECHANICAL_RESTRAINT.value,
                ADULT_PHYSICAL_CEILING + 1,
            )
        )
        assert above_the_minor_ceiling["ordered_duration_minutes"] == (
            ADULT_PHYSICAL_CEILING + 1
        )
        assert above_the_minor_ceiling["ordered_duration_minutes"] <= (
            ADULT_MECHANICAL_CEILING
        )
        assert above_the_minor_ceiling["authorized_until_at"] == ADULT_MECHANICAL_UNTIL
        assert (
            above_the_minor_ceiling["monitoring_interval_minutes"]
            == MONITORING_INTERVAL_MINUTES[InterventionType.MECHANICAL_RESTRAINT.value]
        )

        assert_page(
            api.list_restraints(
                COMPLIANCE_OFFICER_HEADERS, admission_id=minor["admission"]["id"]
            ),
            1,
        )
