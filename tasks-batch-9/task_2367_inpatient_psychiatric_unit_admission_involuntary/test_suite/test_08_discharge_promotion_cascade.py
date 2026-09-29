"""Discharging the only patient in a one-bed unit promotes the patient in the queue.

The chain runs discharge, bed release, unit recomputation, posture change and
promotion — all inside the one request, and the unit ends exactly as full as it
started.
"""

from test_helpers import (
    BedStatus,
    BedType,
    COMPLIANCE_OFFICER_HEADERS,
    LegalStatus,
    PlacementStatus,
    UnitPosture,
    assert_page,
    assert_unit_availability,
    build_ward,
    create_patient,
    discharge,
    place_admission,
    read_admission,
    read_bed,
    read_unit,
    searched_admission,
    secure_discharge_plan,
    signed_evaluation,
)

SINGLE_BED = (
    {
        "room_number": "701",
        "wing_code": "A",
        "bed_label": "A",
        "bed_type": BedType.LIGATURE_RESISTANT_OBSERVATION.value,
    },
)

OVERRIDE_REASON = "High-acuity admission accepted against the restricted-posture reserve."
FOLLOW_UP_AT = "2026-09-12T13:00:00Z"
DISCHARGE_INSTANT = "2026-09-03T08:00:00.000Z"


def _one_bed_unit_with_a_queue(api, roster):
    """A single occupied bed, a plan in place, and one searched admission waiting."""
    ward = build_ward(
        api, name="Ward 7 Annex", seclusion_room_count=0, bed_specs=SINGLE_BED
    )

    occupant = create_patient(
        api,
        mrn="MRN-2367-D1",
        legal_name="Dov Marek",
        age_years=44,
        gender_care_category="MALE",
    )
    occupant_evaluation = signed_evaluation(
        api,
        roster.intake_headers,
        occupant["id"],
        danger_to_self=True,
        danger_to_others=True,
        capacity_present=False,
    )
    occupant_admission = searched_admission(
        api,
        roster,
        occupant["id"],
        occupant_evaluation["id"],
        ward.id,
        LegalStatus.VOLUNTARY.value,
    )
    occupant_admission = place_admission(
        api,
        roster,
        occupant_admission["id"],
        ward.id,
        posture_override_reason=OVERRIDE_REASON,
        headers=roster.psychiatrist_headers,
    )
    secure_discharge_plan(api, roster, occupant_admission["id"], FOLLOW_UP_AT)

    waiting = create_patient(
        api,
        mrn="MRN-2367-D2",
        legal_name="Desmond Ozal",
        age_years=51,
        gender_care_category="MALE",
    )
    waiting_evaluation = signed_evaluation(
        api, roster.intake_headers, waiting["id"], danger_to_self=True, capacity_present=False
    )
    waiting_admission = searched_admission(
        api,
        roster,
        waiting["id"],
        waiting_evaluation["id"],
        ward.id,
        LegalStatus.VOLUNTARY.value,
    )
    return ward, occupant_admission, waiting_admission


class TestDischargePromotionCascade:
    """One discharge, four links, and a promotion at the end of them."""

    def test_discharge_stamps_the_clock_and_keeps_the_bed_on_the_record(
        self, api, clock, roster
    ):
        """The discharged admission retains its bed id for the audit trail.

        PRD 3.8: "First, `placement_status` becomes `DISCHARGED` and
        `discharged_at` is stamped from the logical clock, while `bed_id` is
        deliberately retained on the record for audit rather than nulled."

        Design: Difficulty/transitive_cascade/discharge_frees_bed_reopens_posture_and_promotes_queued_admission
        """
        ward, occupant_admission, _ = _one_bed_unit_with_a_queue(api, roster)

        before = read_unit(api, ward.id)
        assert_unit_availability(before, licensed=1, raw_available=0, occupied=1)
        assert before["posture"] == UnitPosture.CLOSED.value

        discharged = discharge(api, roster, occupant_admission["id"])

        assert discharged["placement_status"] == PlacementStatus.DISCHARGED.value
        assert discharged["discharged_at"] == DISCHARGE_INSTANT
        assert discharged["bed_id"] == ward.beds[0]["id"]

    def test_freeing_the_only_bed_promotes_the_waiting_admission_into_it(
        self, api, clock, roster
    ):
        """The queued admission is placed inside the discharging request itself.

        PRD 3.8: "Fourth — and only when that recomputation moved the unit's
        `posture` out of `CLOSED` — the queued-admission promotion of §3.5 selects
        a single winner, flips that admission `PENDING_PLACEMENT → PLACED`, flips
        its selected bed `AVAILABLE → OCCUPIED`, and recomputes the unit's
        counters and posture a second time."

        Design: Difficulty/transitive_cascade/discharge_frees_bed_reopens_posture_and_promotes_queued_admission
        """
        ward, occupant_admission, waiting_admission = _one_bed_unit_with_a_queue(
            api, roster
        )

        discharge(api, roster, occupant_admission["id"])

        promoted = read_admission(api, waiting_admission["id"])
        assert promoted["placement_status"] == PlacementStatus.PLACED.value
        assert promoted["bed_id"] == ward.beds[0]["id"]
        assert promoted["placed_at"] == DISCHARGE_INSTANT
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )

    def test_the_unit_ends_the_request_as_closed_as_it_began(
        self, api, clock, roster
    ):
        """The bed changes hands, so the counters recompute twice and land where they were.

        PRD 2.8: "Symmetrically, freeing a bed recomputes the owning unit's
        occupancy and availability counters, which may move the unit's `posture`,
        which may in turn promote a queued admission into the bed that just opened
        — and that promotion recomputes the unit's counters a second time within
        the same request."

        Design: Difficulty/transitive_cascade/discharge_frees_bed_reopens_posture_and_promotes_queued_admission
        """
        ward, occupant_admission, _ = _one_bed_unit_with_a_queue(api, roster)

        discharge(api, roster, occupant_admission["id"])

        after = read_unit(api, ward.id)
        assert_unit_availability(after, licensed=1, raw_available=0, occupied=1)
        assert after["posture"] == UnitPosture.CLOSED.value

        assert_page(
            api.list_admissions(
                COMPLIANCE_OFFICER_HEADERS,
                unit_id=ward.id,
                placement_status=PlacementStatus.PLACED.value,
            ),
            1,
        )
