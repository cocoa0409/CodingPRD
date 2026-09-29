"""The four-step availability chain and the reserve it hands to a restricted unit.

Posture is derived from the raw count alone, the reserve from the posture, and the
effective count from the reserve — in that order and with no second pass. The
visible consequence is a unit that refuses an ordinary placement while a bed
stands empty.
"""

from test_helpers import (
    ApiErrorId,
    BedStatus,
    LegalStatus,
    PlacementStatus,
    UnitPosture,
    assert_error,
    assert_ok,
    assert_posture_threshold,
    assert_unit_availability,
    build_ward,
    placement_payload,
    read_admission,
    read_unit,
    searched_admission,
    set_bed_status,
    unit_version,
    voluntary_case,
)

WARD_BEDS = (
    {"room_number": "601", "wing_code": "A", "bed_label": "A"},
    {"room_number": "602", "wing_code": "A", "bed_label": "A"},
    {"room_number": "603", "wing_code": "A", "bed_label": "A"},
)


def _nearly_full_ward_with_a_waiting_admission(api, roster):
    """Three standard beds with two blocked for cleaning, and one searched admission."""
    ward = build_ward(
        api, name="Ward 6 East", seclusion_room_count=0, bed_specs=WARD_BEDS
    )
    case = voluntary_case(
        api,
        roster,
        mrn="MRN-2367-P1",
        legal_name="Pilar Antone",
        age_years=33,
        gender_care_category="FEMALE",
    )
    admission = searched_admission(
        api,
        roster,
        case["patient"]["id"],
        case["evaluation"]["id"],
        ward.id,
        LegalStatus.VOLUNTARY.value,
    )
    for bed in (ward.beds[1], ward.beds[2]):
        set_bed_status(
            api, bed["id"], BedStatus.BLOCKED_CLEANING.value, roster.charge_nurse_headers
        )
    return ward, admission


class TestUnitPostureReserve:
    """A restricted unit holds one bed back, and the arithmetic never loops."""

    def test_restricted_reserve_refuses_an_ordinary_placement_over_a_free_bed(
        self, api, clock, roster
    ):
        """Three licensed beds and one available bed give a threshold of one and no capacity.

        PRD 3.1: "The consequence must be preserved exactly: a unit with a
        `licensed_placement_bed_count` of 3 and a `raw_available_bed_count` of 1
        has a threshold of 1, is therefore `RESTRICTED`, holds one bed in
        reserve, and reports an `effective_available_bed_count` of 0 — so an
        ordinary placement is refused even though a physically free bed exists."

        Design: Difficulty/combinatorial_formula/unit_posture_reserve_order_blocks_placement_with_free_bed
        """
        ward, admission = _nearly_full_ward_with_a_waiting_admission(api, roster)

        before = read_unit(api, ward.id)
        assert_posture_threshold(3, 1)
        assert_unit_availability(before, licensed=3, raw_available=1, occupied=0)
        assert before["posture"] == UnitPosture.RESTRICTED.value
        assert before["effective_available_bed_count"] == 0

        refusal = api.place_admission(
            roster.charge_nurse_headers,
            admission["id"],
            placement_payload(
                unit_id=ward.id, expected_unit_version=before["version"]
            ),
        )
        assert_error(refusal, ApiErrorId.UNIT_POSTURE_BLOCKED)

        unchanged = read_admission(api, admission["id"])
        assert unchanged["placement_status"] == PlacementStatus.PENDING_PLACEMENT.value
        assert unchanged["bed_id"] is None

    def test_returning_one_blocked_bed_to_service_reopens_the_unit(
        self, api, clock, roster
    ):
        """A second available bed clears the threshold, so the unit reports two open beds.

        PRD 3.1: "Step two derives `posture` from `raw_available_bed_count` and
        nothing else: first compute a restriction threshold equal to the greater
        of 1 and one fifth of `licensed_placement_bed_count` rounded down to a
        whole number; then the posture is `CLOSED` when `raw_available_bed_count`
        is zero, `RESTRICTED` when it is greater than zero but no greater than
        that threshold, and `OPEN` otherwise."

        Design: Difficulty/combinatorial_formula/unit_posture_reserve_order_blocks_placement_with_free_bed
        """
        ward, _ = _nearly_full_ward_with_a_waiting_admission(api, roster)

        set_bed_status(
            api,
            ward.beds[1]["id"],
            BedStatus.AVAILABLE.value,
            roster.charge_nurse_headers,
        )

        reopened = read_unit(api, ward.id)
        assert_unit_availability(reopened, licensed=3, raw_available=2, occupied=0)
        assert reopened["posture"] == UnitPosture.OPEN.value
        assert reopened["effective_available_bed_count"] == 2

    def test_the_placement_that_follows_lands_in_the_lower_numbered_room(
        self, api, clock, roster
    ):
        """With the unit open the queued admission places, and the reserve returns.

        PRD 3.5: "An `OPEN` unit accepts a placement only when its
        `effective_available_bed_count` is at least 1."

        Design: Difficulty/combinatorial_formula/unit_posture_reserve_order_blocks_placement_with_free_bed
        """
        ward, admission = _nearly_full_ward_with_a_waiting_admission(api, roster)
        set_bed_status(
            api,
            ward.beds[1]["id"],
            BedStatus.AVAILABLE.value,
            roster.charge_nurse_headers,
        )

        placed = assert_ok(
            api.place_admission(
                roster.charge_nurse_headers,
                admission["id"],
                placement_payload(
                    unit_id=ward.id, expected_unit_version=unit_version(api, ward.id)
                ),
            )
        )

        assert placed["bed_id"] == ward.beds[0]["id"]
        assert placed["placement_status"] == PlacementStatus.PLACED.value

        after = read_unit(api, ward.id)
        assert_unit_availability(after, licensed=3, raw_available=1, occupied=1)
        assert after["posture"] == UnitPosture.RESTRICTED.value
        assert after["effective_available_bed_count"] == 0
