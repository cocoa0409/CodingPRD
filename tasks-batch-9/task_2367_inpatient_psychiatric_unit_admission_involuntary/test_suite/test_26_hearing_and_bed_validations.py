"""Two stacks of gates that must fire in order and refuse for the declared reason.

Hearing scheduling checks the slot, then the hold's expiry, then the advocate's
credential. Placement checks the admission's own state, then the posture, then the
bed — and an explicitly named bed carries four separate eligibility conditions.
"""

from test_helpers import (
    AcuityTier,
    ApiErrorId,
    BedStatus,
    BedType,
    COMPLIANCE_OFFICER_HEADERS,
    HOLIDAY_DATES,
    HearingStatus,
    LegalStatus,
    PetitionStatus,
    PlacementStatus,
    SafetySearchStatus,
    UnitPosture,
    active_hold_case,
    assert_created,
    assert_docket_minutes,
    assert_error,
    assert_page,
    assert_unit_availability,
    build_ward,
    complete_safety_search,
    create_admission,
    create_bed,
    create_petition,
    hearing_payload,
    place_admission,
    placement_payload,
    read_admission,
    read_bed,
    read_clinician,
    read_petition,
    read_unit,
    set_bed_status,
    unit_version,
    voluntary_case,
)

HEARING_MINUTES = 60
RELEASE_DEADLINE = "2026-09-06T08:00:00.000Z"
SATURDAY_SLOT = "2026-09-05T10:00:00Z"
HOLIDAY_SLOT = "2026-09-07T10:00:00Z"
RECOGNIZED_HOLIDAY = "2026-09-07"
BEFORE_THE_COURT_OPENS = "2026-09-04T08:30:00Z"
ENDING_AFTER_THE_CLOSE = "2026-09-04T15:30:00Z"
ALREADY_PAST = "2026-09-02T10:00:00Z"
BEYOND_THE_HOLD = "2026-09-08T09:00:00Z"
OTHERWISE_VALID_SLOT = "2026-09-04T09:00:00Z"
ACCEPTED_SLOT = "2026-09-04T15:00:00Z"
ACCEPTED_SLOT_INSTANT = "2026-09-04T15:00:00.000Z"
ACCEPTED_SLOT_END = "2026-09-04T16:00:00.000Z"

ELIGIBILITY_UNIT = "Ward 30 Eligibility"
FOREIGN_UNIT = "Ward 31 Foreign"
ELIGIBILITY_BEDS = (
    {"room_number": "521", "wing_code": "A", "bed_label": "A"},
    {
        "room_number": "522",
        "wing_code": "A",
        "bed_label": "A",
        "bed_type": BedType.SECLUSION.value,
    },
    {"room_number": "523", "wing_code": "A", "bed_label": "A"},
)
FOREIGN_BEDS = ({"room_number": "531", "wing_code": "A", "bed_label": "A"},)
OBSERVATION_ROOM = "524"
OVERRIDE_REASON = "High-acuity admission accepted under RESTRICTED posture."


class TestHearingSlotValidationStack:
    """Seven refusals, each naming its own gate, and then one accepted slot."""

    def test_the_slot_gate_precedes_the_hold_expiry_gate_and_the_advocate_credential(
        self, api, clock, roster
    ):
        """A weekend, a holiday, a too-early start, a late end, a past slot, a slot beyond the hold and an unqualified advocate.

        PRD 3.4: "Four scheduling constraints guard the slot itself, and they are
        evaluated in the order given in §2.9. The slot must be a genuine court slot:
        its date must be a judicial day, its start time no earlier than 09:00:00, its
        end time no later than 16:00:00, and its start strictly after the current clock
        — any breach is `ERR_HEARING_SLOT_INVALID`. The hearing must also conclude
        while detention authority still exists, so `scheduled_end_at` must be at or
        before the petition's hold's `release_deadline_at`, failing which the request is
        refused with `ERR_HEARING_BEYOND_HOLD_EXPIRY`."

        PRD 3.4: "Finally the nominated advocate must be credentialed for the job —
        their roster `staff_role` must be `RIGHTS_ADVOCATE`, and anyone else is refused
        with `ERR_ADVOCATE_NOT_QUALIFIED`."

        PRD 2.6: "The **court calendar** treats a judicial day as any day that is not a
        Saturday, not a Sunday, and not one of the five recognized holidays —
        `2026-01-01`, `2026-07-03`, `2026-09-07`, `2026-11-26` and `2026-12-25` — and
        its window runs from 09:00:00 to 16:00:00 UTC."

        Design: Corner/validations/hearing_slot_judicial_day_court_window_and_hold_expiry_bounds
        """
        assert RECOGNIZED_HOLIDAY in HOLIDAY_DATES
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-SL",
            legal_name="Slot Case",
            age_years=41,
            gender_care_category="MALE",
        )
        assert case["hold"]["release_deadline_at"] == RELEASE_DEADLINE
        petition = create_petition(
            api, roster.psychiatrist_headers, case["hold"]["id"]
        )

        def book(start_at, advocate_clinician_id=None):
            return api.create_hearing(
                roster.advocate_headers,
                hearing_payload(
                    petition_id=petition["id"],
                    advocate_clinician_id=advocate_clinician_id
                    or roster.advocate["id"],
                    scheduled_start_at=start_at,
                    duration_minutes=HEARING_MINUTES,
                ),
            )

        for start_at in (
            SATURDAY_SLOT,
            HOLIDAY_SLOT,
            BEFORE_THE_COURT_OPENS,
            ENDING_AFTER_THE_CLOSE,
            ALREADY_PAST,
        ):
            assert_error(book(start_at), ApiErrorId.HEARING_SLOT_INVALID)

        assert_error(book(BEYOND_THE_HOLD), ApiErrorId.HEARING_BEYOND_HOLD_EXPIRY)
        assert_error(
            book(OTHERWISE_VALID_SLOT, advocate_clinician_id=roster.intake["id"]),
            ApiErrorId.ADVOCATE_NOT_QUALIFIED,
        )

        assert read_petition(api, petition["id"])["status"] == PetitionStatus.FILED.value
        assert_docket_minutes(read_clinician(api, roster.advocate["id"]), 0)

        booked = assert_created(book(ACCEPTED_SLOT))
        assert booked["scheduled_start_at"] == ACCEPTED_SLOT_INSTANT
        assert booked["scheduled_end_at"] == ACCEPTED_SLOT_END
        assert booked["status"] == HearingStatus.SCHEDULED.value
        assert (
            read_petition(api, petition["id"])["status"]
            == PetitionStatus.HEARING_SCHEDULED.value
        )
        assert_docket_minutes(
            read_clinician(api, roster.advocate["id"]), HEARING_MINUTES
        )


class TestBedEligibilityAndEmptyCandidatePool:
    """Four named-bed conditions, then an empty pool, then a placed admission that cannot move."""

    def test_each_named_bed_condition_is_refused_before_the_selector_ever_runs(
        self, api, clock, roster
    ):
        """A high-acuity admission rejects a standard, a seclusion, an out-of-service and a foreign bed.

        PRD 3.5: "A bed is a candidate only when it belongs to the requested unit, its
        `status` is exactly `AVAILABLE`, its `bed_type` is `STANDARD` or
        `LIGATURE_RESISTANT_OBSERVATION` — a `SECLUSION` bed is never a placement
        destination — and, when the admission's `acuity_tier` is `HIGH`, its `bed_type`
        is specifically `LIGATURE_RESISTANT_OBSERVATION`."

        PRD 3.5: "A cohort failure is `ERR_ROOM_COHORT_VIOLATION`; an explicitly named
        `bed_id` that fails the unit, status or bed-type conditions is
        `ERR_BED_NOT_ELIGIBLE`."

        Design: Corner/validations/explicit_bed_eligibility_and_empty_candidate_pool
        """
        ward, foreign, admission = self._high_acuity_case_on_a_restricted_unit(
            api, roster
        )
        version = unit_version(api, ward.id)

        for bed_id in (
            ward.beds[0]["id"],
            ward.beds[1]["id"],
            ward.beds[2]["id"],
            foreign.beds[0]["id"],
        ):
            refusal = api.place_admission(
                roster.charge_nurse_headers,
                admission["id"],
                placement_payload(
                    unit_id=ward.id, expected_unit_version=version, bed_id=bed_id
                ),
            )
            assert_error(refusal, ApiErrorId.BED_NOT_ELIGIBLE)

        assert unit_version(api, ward.id) == version
        assert (
            read_admission(api, admission["id"])["placement_status"]
            == PlacementStatus.PENDING_PLACEMENT.value
        )
        assert read_admission(api, admission["id"])["bed_id"] is None

    def test_an_empty_candidate_pool_is_reached_only_after_the_posture_gate(
        self, api, clock, roster
    ):
        """The override clears the restricted posture and the selector then finds nothing to give.

        PRD 3.5: "If the candidate set is empty for an explicit placement call, the
        request is refused with `ERR_NO_ELIGIBLE_BED`."

        PRD 3.5: "First it fixes the exact-fit bed type for this admission:
        `LIGATURE_RESISTANT_OBSERVATION` when the `acuity_tier` is `HIGH` or
        `MODERATE`, and `STANDARD` when it is `LOW`."

        Design: Corner/validations/explicit_bed_eligibility_and_empty_candidate_pool
        """
        ward, _, admission = self._high_acuity_case_on_a_restricted_unit(api, roster)
        restricted = read_unit(api, ward.id)
        assert_unit_availability(restricted, licensed=1, raw_available=1)
        assert restricted["posture"] == UnitPosture.RESTRICTED.value
        assert restricted["effective_available_bed_count"] == 0

        refusal = api.place_admission(
            roster.psychiatrist_headers,
            admission["id"],
            placement_payload(
                unit_id=ward.id,
                expected_unit_version=restricted["version"],
                posture_override_reason=OVERRIDE_REASON,
            ),
        )
        assert_error(refusal, ApiErrorId.NO_ELIGIBLE_BED)
        assert unit_version(api, ward.id) == restricted["version"]

    def test_the_selector_takes_the_new_observation_bed_and_then_refuses_a_second_placement(
        self, api, clock, roster
    ):
        """Adding one eligible bed reopens the unit, and the placed admission is no longer placeable.

        PRD 3.5: "A successful placement sets `bed_id` to the selected bed, stamps
        `placed_at` from the logical clock, and advances the placement axis
        `PENDING_PLACEMENT → PLACED` while leaving `legal_status` exactly as it was. The
        chosen bed's `status` flips `AVAILABLE → OCCUPIED` with `Bed.version`
        incremented by one, and the unit's `occupied_bed_count`,
        `raw_available_bed_count`, `posture` and `effective_available_bed_count` are
        all recomputed with `Unit.version` incremented by one."

        PRD 3.5: "The admission must be in `PENDING_PLACEMENT`, or the request fails
        with `ERR_ADMISSION_NOT_PLACEABLE`, and its `safety_search_status` must be
        exactly `COMPLETED`, or the request fails with `ERR_SAFETY_SEARCH_INCOMPLETE`."

        Design: Corner/validations/explicit_bed_eligibility_and_empty_candidate_pool
        """
        ward, _, admission = self._high_acuity_case_on_a_restricted_unit(api, roster)
        observation_bed = create_bed(
            api,
            unit_id=ward.id,
            room_number=OBSERVATION_ROOM,
            wing_code="A",
            bed_label="A",
            bed_type=BedType.LIGATURE_RESISTANT_OBSERVATION.value,
        )

        reopened = read_unit(api, ward.id)
        assert_unit_availability(reopened, licensed=2, raw_available=2)
        assert reopened["posture"] == UnitPosture.OPEN.value
        assert reopened["effective_available_bed_count"] == 2

        placed = place_admission(api, roster, admission["id"], ward.id)
        assert placed["bed_id"] == observation_bed["id"]
        assert placed["placement_status"] == PlacementStatus.PLACED.value
        assert (
            read_bed(api, observation_bed["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )

        refusal = api.place_admission(
            roster.charge_nurse_headers,
            admission["id"],
            placement_payload(
                unit_id=ward.id,
                expected_unit_version=unit_version(api, ward.id),
                bed_id=observation_bed["id"],
            ),
        )
        assert_error(refusal, ApiErrorId.ADMISSION_NOT_PLACEABLE)
        assert (
            read_bed(api, observation_bed["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )
        assert read_admission(api, admission["id"])["bed_id"] == observation_bed["id"]
        assert_page(
            api.list_unit_beds(
                COMPLIANCE_OFFICER_HEADERS, ward.id, status=BedStatus.OCCUPIED.value
            ),
            1,
        )

    @staticmethod
    def _high_acuity_case_on_a_restricted_unit(api, roster):
        """A searched HIGH-acuity voluntary admission facing one standard bed on a restricted unit."""
        ward = build_ward(
            api,
            name=ELIGIBILITY_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=ELIGIBILITY_BEDS,
        )
        foreign = build_ward(
            api,
            name=FOREIGN_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=FOREIGN_BEDS,
        )
        set_bed_status(api, ward.beds[2]["id"], BedStatus.OUT_OF_SERVICE.value)
        case = voluntary_case(
            api,
            roster,
            mrn="MRN-2367-BE",
            legal_name="Bed Eligibility",
            age_years=38,
            gender_care_category="FEMALE",
            danger_to_self=True,
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
        searched = complete_safety_search(api, roster, admission["id"])
        assert admission["acuity_tier"] == AcuityTier.HIGH.value
        assert admission["legal_status"] == LegalStatus.VOLUNTARY.value
        assert searched["safety_search_status"] == SafetySearchStatus.COMPLETED.value
        return ward, foreign, admission
