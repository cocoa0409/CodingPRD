"""Chaperone ratio computation: tiered ceil + dedicated 1:1 + water surcharge,
its recomputation cascade on revoke, and the boundary at the ratio crossing.
"""
from test_helpers import (
    get_success_data,
    make_teacher_headers,
    make_guardian_headers,
    create_approved_trip,
    create_guardian,
    create_student,
    create_signed_slip,
    setup_signed_slips_count,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/chaperone_ratio_nonlinear_three_inputs
# ─────────────────────────────────────────────────────────────────────────────
class TestChaperoneRatioCombination:
    def test_ratio_with_special_needs_and_water_at_one_signed(self, api):
        """PRD §3.4: "General chaperones cover all signed students, special-needs included; on top of them, each special-needs signed student needs its own dedicated one-to-one, adding N more. Finally, if the trip has `has_water_activity` set, one additional chaperone is added as a water surcharge; otherwise nothing is added. The required total is the general count plus N plus the water surcharge."

        ELEMENTARY (ratio 8), S=1 special-needs, water=true:
        ceil(1/8)=1 general + 1 dedicated + 1 water = 3.

        Design: Difficulty/combinatorial_formula/chaperone_ratio_nonlinear_three_inputs
        """
        teacher_id, trip = create_approved_trip(
            grade_band="ELEMENTARY", capacity=20, base_fee_cents=0,
            transport_cost_cents=0, has_water_activity=True,
        )
        trip_id = trip["id"]
        g = create_guardian(full_name="GSN")
        st = create_student(teacher_id, full_name="SN", grade_level=3, special_needs=True)
        create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["required_chaperones"] == 3, (
            f"ceil(1/8)=1 general + 1 dedicated + 1 water should be 3, got {trip['required_chaperones']}"
        )

    def test_water_surcharge_distinct_from_dedicated(self, api):
        """PRD §3.4: "A base ratio is selected by the trip's `grade_band`: one chaperone per 8 students for `ELEMENTARY`, one per 12 for `MIDDLE`, and one per 15 for `HIGH`."

        ELEMENTARY with one ordinary (non-special-needs) signed student and NO
        water: ceil(1/8)=1 general + 0 dedicated + 0 water = 1, isolating the
        general-tier term from the dedicated and water terms.

        Design: Difficulty/combinatorial_formula/chaperone_ratio_nonlinear_three_inputs
        """
        teacher_id, trip = create_approved_trip(
            grade_band="ELEMENTARY", capacity=20, base_fee_cents=0,
            transport_cost_cents=0, has_water_activity=False,
        )
        trip_id = trip["id"]
        g = create_guardian(full_name="GORD")
        st = create_student(teacher_id, full_name="ORD", grade_level=3)
        create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["required_chaperones"] == 1, (
            f"ceil(1/8)=1 general only (no dedicated, no water) should be 1, got {trip['required_chaperones']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/chaperone_ratio_ceil_boundary_at_13
# ─────────────────────────────────────────────────────────────────────────────
class TestChaperoneRatioCeilBoundary:
    def test_ratio_one_at_single_middle_signed(self, api):
        """PRD §3.4: "The general requirement is S divided by that base ratio, rounded up to the next whole chaperone — so a `MIDDLE` trip with 10 signed students needs 1 general chaperone, while 13 signed students needs 2."

        MIDDLE base ratio 12. At signed_count 1, ceil(1/12)=1.

        Design: Difficulty/boundary_precision_check/chaperone_ratio_ceil_boundary_at_13
        """
        teacher_id, trip = create_approved_trip(
            grade_band="MIDDLE", capacity=20, base_fee_cents=0, transport_cost_cents=0,
        )
        trip_id = trip["id"]
        g = create_guardian(full_name="GM")
        st = create_student(teacher_id, full_name="M1", grade_level=7)
        create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["required_chaperones"] == 1, (
            f"ceil(1/12) should be 1, got {trip['required_chaperones']}"
        )

    def test_ratio_crosses_from_one_to_two_at_thirteen_middle(self, api):
        """PRD §3.4: "so a `MIDDLE` trip with 10 signed students needs 1 general chaperone, while 13 signed students needs 2."

        Sign 12 MIDDLE slips → ceil(12/12)=1; the 13th sign pushes ceil(13/12)=2,
        proving the >= vs > boundary at S=12.

        Design: Difficulty/boundary_precision_check/chaperone_ratio_ceil_boundary_at_13
        """
        s = setup_signed_slips_count(12, grade_band="MIDDLE", capacity=20)
        teacher_id, trip_id = s["teacher_id"], s["trip_id"]
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["required_chaperones"] == 1, (
            f"at 12 signed MIDDLE, ceil(12/12) should be 1, got {trip['required_chaperones']}"
        )
        # 13th signed slip pushes to ceil(13/12)=2
        g = create_guardian(full_name="G13")
        st = create_student(teacher_id, full_name="S13", grade_level=7)
        create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["required_chaperones"] == 2, (
            f"at 13 signed MIDDLE, ceil(13/12) should be 2, got {trip['required_chaperones']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/transitive_cascade/revoke_depth2_signed_count_and_ratio
# ─────────────────────────────────────────────────────────────────────────────
class TestRevokeDepthTwoCascade:
    def _setup_one_special_needs_signed(self, api):
        teacher_id, trip = create_approved_trip(
            grade_band="ELEMENTARY", capacity=20, base_fee_cents=0,
            transport_cost_cents=0, has_water_activity=False,
        )
        trip_id = trip["id"]
        g = create_guardian(full_name="GSN")
        st = create_student(teacher_id, full_name="SN", grade_level=2, special_needs=True)
        slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        return teacher_id, trip_id, g["id"], slip["id"]

    def test_signed_count_and_ratio_before_revoke(self, api):
        """PRD §3.3: "On a successful sign the server moves the slip to `SIGNED ...
        increments the trip's `signed_count` by 1, and recomputes the trip's `required_chaperones`."

        After signing one special-needs ELEMENTARY slip (no water): signed_count 1,
        required_chaperones = ceil(1/8)=1 general + 1 dedicated = 2.

        Design: Difficulty/transitive_cascade/revoke_depth2_signed_count_and_ratio
        """
        teacher_id, trip_id, _, _ = self._setup_one_special_needs_signed(api)
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["signed_count"] == 1
        assert trip["required_chaperones"] == 2, (
            f"ceil(1/8)=1 + 1 dedicated should be 2, got {trip['required_chaperones']}"
        )

    def test_revoke_decrements_signed_count_and_drops_dedicated(self, api):
        """PRD §3.3: "Revoking cascades: the slip becomes `REVOKED`, the trip's `signed_count` decreases by 1, and `required_chaperones` is recomputed; moreover, if any chaperone on the trip was assigned as the dedicated one-to-one for this slip's student, that student's one-to-one requirement drops out of the ratio computation."

        Revoking the only (special-needs) signed slip: signed_count 1→0,
        required_chaperones 2→0 (ceil(0/8)=0 general + 0 dedicated).

        Design: Difficulty/transitive_cascade/revoke_depth2_signed_count_and_ratio
        """
        teacher_id, trip_id, g_id, slip_id = self._setup_one_special_needs_signed(api)
        api.revoke_slip(trip_id, slip_id, make_guardian_headers(g_id))
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["signed_count"] == 0, f"signed_count should drop to 0, got {trip['signed_count']}"
        assert trip["required_chaperones"] == 0, (
            f"required_chaperones should drop to 0 after revoke, got {trip['required_chaperones']}"
        )
