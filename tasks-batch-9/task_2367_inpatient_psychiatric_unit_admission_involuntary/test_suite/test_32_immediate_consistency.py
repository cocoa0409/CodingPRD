"""Every counter a write touches is already correct in that write's own response.

No follow-up read is needed to see the placement's effect on the unit or the
rescission's effect on the patient, and repeating any read returns the same body.
"""

from test_helpers import (
    AcuityTier,
    BedStatus,
    HoldStatus,
    LegalStatus,
    PlacementStatus,
    UnitPosture,
    active_hold_case,
    assert_ok,
    assert_unit_availability,
    build_ward,
    complete_safety_search,
    create_admission,
    place_admission,
    read_admission,
    read_bed,
    read_hold,
    read_patient,
    read_unit,
    rescind_payload,
)

COUNTER_UNIT = "Ward 41 Counters"
COUNTER_BEDS = (
    {"room_number": "4101", "wing_code": "A", "bed_label": "4101-A"},
    {"room_number": "4102", "wing_code": "A", "bed_label": "4102-A"},
)
PLACED_AT = "2026-09-03T08:00:00.000Z"
RESCIND_REASON = "Criteria no longer met."


class TestDerivedCountersAreVisibleImmediately:
    """The write's own body, the next read, and the read after that all agree."""

    def test_the_write_response_already_carries_the_recomputed_counters(
        self, api, clock, roster
    ):
        """Placement publishes the unit's posture triple and rescission publishes the patient's count.

        PRD 2.5: "Recomputing a derived counter counts as a mutation. When placing an
        admission changes a unit's occupancy figures, that unit's `updated_at` is
        refreshed and its `version` increments by one even though no client field on the
        unit was touched. The same holds for `Patient` when `active_hold_count` is
        recomputed, for `Clinician` when `booked_docket_minutes` is recomputed, and for
        `Bed` when its `status` flips as a side effect of a placement or a discharge."

        PRD 3.5: "A successful placement sets `bed_id` to the selected bed, stamps
        `placed_at` from the logical clock, and advances the placement axis
        `PENDING_PLACEMENT → PLACED` while leaving `legal_status` exactly as it was."

        PRD 3.2: "A patient's `active_hold_count` starts at 0 and is always the number of
        that patient's holds whose `status` is `ACTIVE`."

        PRD 3.3: "It carries a `rescind_reason`, which is stored verbatim as the hold's
        `closure_reason`, and moves the hold to `RESCINDED`. Rescinding a hold that was
        still `PENDING_CERTIFICATION` has no further consequence, because that hold never
        counted toward detention. Rescinding an `ACTIVE` hold starts a four-link chain:
        the patient's `active_hold_count` is recomputed and reaches 0 when no other
        `ACTIVE` hold remains; because the patient now has no `ACTIVE` hold, every
        admission of theirs in `PENDING_PLACEMENT` or `PLACED` flips `legal_status` from
        `INVOLUNTARY` to `VOLUNTARY`; because such an admission is now voluntary, every
        discharge request against it that is still `PENDING` flips to `GRANTED_DISCHARGE`
        with its `decision` set to `GRANT` and its `responding_clinician_id` set to the
        rescinding psychiatrist's `X-User-ID`; and because a discharge request was
        granted, that admission's `placement_status` advances `PLACED →
        DISCHARGE_READY`."

        Design: Corner/consistency_model/derived_counters_are_visible_in_the_same_response
        """
        ward = build_ward(
            api,
            name=COUNTER_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=COUNTER_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-IM",
            legal_name="Counter Case",
            age_years=36,
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
        assert admission["acuity_tier"] == AcuityTier.MODERATE.value
        complete_safety_search(api, roster, admission["id"], items_secured=0)

        placed = place_admission(
            api, roster, admission["id"], ward.id, bed_id=ward.beds[0]["id"]
        )
        assert placed["placement_status"] == PlacementStatus.PLACED.value
        assert placed["bed_id"] == ward.beds[0]["id"]
        assert placed["placed_at"] == PLACED_AT

        occupied = read_unit(api, ward.id)
        assert_unit_availability(occupied, licensed=2, raw_available=1, occupied=1)
        assert occupied["posture"] == UnitPosture.RESTRICTED.value
        assert occupied["effective_available_bed_count"] == 0
        assert occupied == read_unit(api, ward.id)
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )

        assert read_patient(api, case["patient"]["id"])["active_hold_count"] == 1

        rescinded = assert_ok(
            api.rescind_hold(
                roster.psychiatrist_headers,
                case["hold"]["id"],
                rescind_payload(rescind_reason=RESCIND_REASON),
            )
        )
        assert rescinded["status"] == HoldStatus.RESCINDED.value
        assert rescinded["closure_reason"] == RESCIND_REASON
        assert rescinded == read_hold(api, case["hold"]["id"])

        released = read_patient(api, case["patient"]["id"])
        assert released["active_hold_count"] == 0
        assert released == read_patient(api, case["patient"]["id"])

        converted = read_admission(api, admission["id"])
        assert converted["legal_status"] == LegalStatus.VOLUNTARY.value
        assert converted["placement_status"] == PlacementStatus.PLACED.value
        assert converted == read_admission(api, admission["id"])
