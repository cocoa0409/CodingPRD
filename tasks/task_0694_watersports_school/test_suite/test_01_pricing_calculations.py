"""Pricing calculations: enrollment estimate vs final price, rental fee, refund.

Queue A (Difficulty) translations for rule_id=dual_variant_calc and
rule_id=combinatorial_formula, plus queue B (Corner) calculation instances.
Every literal expected value is copied from the design index, which precomputes
it against the PRD §3.8 formulas.
"""
from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    setup_catalog, create_student_with_waiver, create_school, create_student,
    create_equipment, create_paid_enrollment,
    create_session, book, attend_session, set_clock,
    create_rental, create_membership,
)

ADMIN = TEST_USERS["admin_headers"]


# ============================================================================
# rule_id=dual_variant_calc
# ============================================================================
class TestEstimateVsFinalDivergence:
    """Same enrollment priced two ways: forward-looking estimate (booked party
    size) vs chronological final (actual attended group size)."""

    def _build_attended_two_session_enrollment(self):
        # base 10000, party 4, planned 2, student is sole attendee of 2 sessions.
        cat = setup_catalog(level_overrides={
            "max_students_per_instructor": 2, "base_price_cents": 10000,
            "min_age": 0, "requires_swim_test": False, "required_equipment_type": "NONE"})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student_with_waiver(school["id"])
        enr = create_paid_enrollment(school["id"], student["id"], level["id"],
                                     planned_sessions=2, party_size=4)
        s1 = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                            tide_window_start="2026-03-05T08:00:00Z",
                            tide_window_end="2026-03-05T12:00:00Z", capacity=6)
        s2 = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-06T09:00:00Z", ends_at="2026-03-06T10:00:00Z",
                            tide_window_start="2026-03-06T08:00:00Z",
                            tide_window_end="2026-03-06T12:00:00Z", capacity=6)
        bk1 = book(s1["id"], enr["id"], s1["version"])
        bk2 = book(s2["id"], enr["id"], s2["version"])
        attend_session(s1["id"], [bk1["id"]], "2026-03-05T08:30:00Z")
        attend_session(s2["id"], [bk2["id"]], "2026-03-06T08:30:00Z")
        return enr["id"]

    def test_estimate_uses_booked_party_size(self, api):
        """PRD §3.8: "The group discount is applied once over that gross, using
        the single supplied `party_size` to select the group percentage — the
        amount after the group discount is the gross multiplied by one minus
        that group percentage."

        Design: Difficulty/dual_variant_calc/enrollment_estimate_vs_final_diverge_on_attended_group_size
        """
        enr_id = self._build_attended_two_session_enrollment()
        data = validate_success(api.complete_enrollment(enr_id, ADMIN), 200)
        assert data["estimated_price_cents"] == 16000, \
            f"estimate should use party_size=4 (20%) over 2*10000: got {data['estimated_price_cents']}"

    def test_final_uses_actual_attended_group_size(self, api):
        """PRD §3.8: "the group tier is recomputed per session from the actual
        attended group size, rounding is applied per line rather than once, and
        only `ATTENDED` bookings count."

        Design: Difficulty/dual_variant_calc/enrollment_estimate_vs_final_diverge_on_attended_group_size
        """
        enr_id = self._build_attended_two_session_enrollment()
        data = validate_success(api.complete_enrollment(enr_id, ADMIN), 200)
        # Each session had exactly one attended student -> 0% group tier -> line 10000 each.
        assert data["final_price_cents"] == 20000, \
            f"final should use actual attended size 1 (0%): got {data['final_price_cents']}"

    def test_estimate_and_final_diverge(self, api):
        """PRD §3.8: "it diverges deliberately from the estimate in three ways:
        the group tier is recomputed per session from the actual attended group
        size, rounding is applied per line rather than once, and only `ATTENDED`
        bookings count."

        Design: Difficulty/dual_variant_calc/enrollment_estimate_vs_final_diverge_on_attended_group_size
        """
        enr_id = self._build_attended_two_session_enrollment()
        data = validate_success(api.complete_enrollment(enr_id, ADMIN), 200)
        assert data["estimated_price_cents"] != data["final_price_cents"], \
            "estimate (16000) and final (20000) must diverge"


class TestRentalFeeVsRefundDivergeAcrossDomains:
    """Two distinct cost algorithms on different entity domains computed in the
    same world: tiered rental_fee on RentalAgreement vs lead-time refund on
    Enrollment."""

    def _build(self):
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={
            "max_students_per_instructor": 2, "base_price_cents": 10000,
            "min_age": 0, "requires_swim_test": False, "required_equipment_type": "NONE"})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student_with_waiver(school["id"])
        equipment = create_equipment(school["id"], equipment_type="BOARD",
                                     hourly_rate_cents=1000, deposit_cents=5000)
        rental = create_rental(school["id"], student["id"], equipment["id"],
                               equipment["version"],
                               starts_at="2026-03-02T09:00:00Z",
                               ends_at="2026-03-02T12:00:00Z")
        enr = create_paid_enrollment(school["id"], student["id"], level["id"],
                                     planned_sessions=2, party_size=4)
        sess = create_session(school["id"], level["id"], inst["id"],
                             starts_at="2026-03-03T00:00:00Z", ends_at="2026-03-03T01:00:00Z",
                             tide_window_start="2026-03-02T23:00:00Z",
                             tide_window_end="2026-03-03T03:00:00Z", capacity=6)
        book(sess["id"], enr["id"], sess["version"])
        get_success_data(api_client.withdraw_enrollment(enr["id"], ADMIN))
        return rental["id"], enr["id"]

    def test_rental_fee_tiered_marginal(self, api):
        """PRD §3.8: "The first 2 hours are billed at the full rate; the next 6
        hours (hours 3 through 8) are billed at half the rate; every hour beyond
        the eighth is billed at one quarter of the rate."

        Design: Difficulty/dual_variant_calc/rental_fee_vs_refund_diverge_across_equipment_and_enrollment_domains
        """
        rental_id, _ = self._build()
        data = validate_success(api.get_rental(rental_id, ADMIN), 200)
        # 3h @ 1000: t1 2*1000 + t2 1*500 = 2500.
        assert data["rental_fee_cents"] == 2500, \
            f"3h marginal tiered fee should be 2500: got {data['rental_fee_cents']}"

    def test_refund_lead_time_waterfall(self, api):
        """PRD §3.8: "The refund percentage is one hundred percent when the lead
        time is at least 48 hours, fifty percent when it is at least 24 hours but
        under 48, and zero otherwise."

        Design: Difficulty/dual_variant_calc/rental_fee_vs_refund_diverge_across_equipment_and_enrollment_domains
        """
        _, enr_id = self._build()
        data = validate_success(api.refund_enrollment(enr_id, ADMIN), 200)
        # estimate 16000, earliest remaining session exactly 48h out -> 100%.
        assert data["refund_cents"] == 16000, \
            f"full refund of estimate 16000 expected: got {data['refund_cents']}"


# ============================================================================
# rule_id=combinatorial_formula
# ============================================================================
class TestRentalFeeCombinatorial:

    def _build_ten_hour_kayak_rental(self):
        school = create_school(name="Tier School")
        student = create_student(school["id"], full_name="Leo")
        equipment = create_equipment(school["id"], equipment_type="KAYAK",
                                     asset_tag="K-1", hourly_rate_cents=1000, deposit_cents=0)
        rental = create_rental(school["id"], student["id"], equipment["id"],
                               equipment["version"],
                               starts_at="2026-03-02T00:00:00Z",
                               ends_at="2026-03-02T10:00:00Z")
        return rental["id"]

    def test_rental_fee_ten_hours_three_tiers(self, api):
        """PRD §3.8: "The fee is the first-tier hours times the rate, plus the
        second-tier hours times the rate times one half, plus the third-tier
        hours times the rate times one quarter, all summed and then rounded half
        up to whole cents once at the end."

        Design: Difficulty/combinatorial_formula/rental_fee_tiered_marginal_three_inputs
        """
        rental_id = self._build_ten_hour_kayak_rental()
        data = validate_success(api.get_rental(rental_id, ADMIN), 200)
        # 10h: 2*1000 + 6*500 + 2*250 = 5500.
        assert data["rental_fee_cents"] == 5500, \
            f"10h marginal fee should be 5500: got {data['rental_fee_cents']}"

    def test_rental_deposit_captured_from_item(self, api):
        """PRD §3.8: "At creation the agreement's `deposit_held_cents` is
        captured from the equipment item's `deposit_cents`."

        Design: Difficulty/combinatorial_formula/rental_fee_tiered_marginal_three_inputs
        """
        rental_id = self._build_ten_hour_kayak_rental()
        data = validate_success(api.get_rental(rental_id, ADMIN), 200)
        assert data["deposit_held_cents"] == 0, \
            f"deposit_held_cents should mirror item deposit 0: got {data['deposit_held_cents']}"


class TestFinalPriceRoundPerLine:

    def _build_three_session_premium(self):
        """PREMIUM member attends 3 sessions with actual attended group sizes
        2, 2, 1 (10%, 10%, 0% group tiers)."""
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(
            course_overrides={"discipline": "SAIL", "title": "Sail Basics", "kind": "LESSON"},
            level_overrides={"max_students_per_instructor": 6, "base_price_cents": 10000,
                             "min_age": 0, "requires_swim_test": False,
                             "required_equipment_type": "NONE"},
            instructor_overrides={"full_name": "Ana", "certified_disciplines": ["SAIL"]})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        stu_a = create_student_with_waiver(school["id"], full_name="Tom")
        mem_a = create_membership(stu_a["id"], tier="PREMIUM")
        stu_b = create_student_with_waiver(school["id"], full_name="Bea")
        enr_a = create_paid_enrollment(school["id"], stu_a["id"], level["id"],
                                       membership_id=mem_a["id"], planned_sessions=3, party_size=2)
        enr_b = create_paid_enrollment(school["id"], stu_b["id"], level["id"],
                                       planned_sessions=3, party_size=2)
        sessions = []
        for day in ("05", "06", "07"):
            sessions.append(create_session(
                school["id"], level["id"], inst["id"],
                starts_at=f"2026-03-{day}T09:00:00Z", ends_at=f"2026-03-{day}T10:00:00Z",
                tide_window_start=f"2026-03-{day}T08:00:00Z",
                tide_window_end=f"2026-03-{day}T12:00:00Z", capacity=6))
        s1, s2, s3 = sessions
        # Session 1: A and B. Session 2: A and B. Session 3: A only.
        a1 = book(s1["id"], enr_a["id"], s1["version"])
        s1_now = get_success_data(api_client.get_session(s1["id"], ADMIN))
        b1 = book(s1["id"], enr_b["id"], s1_now["version"])
        a2 = book(s2["id"], enr_a["id"], s2["version"])
        s2_now = get_success_data(api_client.get_session(s2["id"], ADMIN))
        b2 = book(s2["id"], enr_b["id"], s2_now["version"])
        a3 = book(s3["id"], enr_a["id"], s3["version"])
        attend_session(s1["id"], [a1["id"], b1["id"]], "2026-03-05T08:30:00Z")
        attend_session(s2["id"], [a2["id"], b2["id"]], "2026-03-06T08:30:00Z")
        attend_session(s3["id"], [a3["id"]], "2026-03-07T08:30:00Z")
        return enr_a["id"]

    def test_final_price_round_per_line_then_member_discount(self, api):
        """PRD §3.8: "These per-line amounts are summed into a subtotal. The
        membership discount is then applied to the subtotal — the subtotal
        multiplied by one minus the membership percentage — and that result is
        rounded half up to whole cents once more."

        Design: Difficulty/combinatorial_formula/enrollment_final_price_round_per_line_then_sum
        """
        enr_id = self._build_three_session_premium()
        data = validate_success(api.complete_enrollment(enr_id, ADMIN), 200)
        # Lines 9000 + 9000 + 10000 = 28000, PREMIUM 15% -> 23800.
        assert data["final_price_cents"] == 23800, \
            f"round-per-line then 15% should give 23800: got {data['final_price_cents']}"

    def test_final_price_completes_with_attended_lines(self, api):
        """PRD §3.8: "When an enrollment completes, its `final_price_cents` is
        computed over only the sessions the student actually attended."

        Design: Difficulty/combinatorial_formula/enrollment_final_price_round_per_line_then_sum
        """
        enr_id = self._build_three_session_premium()
        data = validate_success(api.complete_enrollment(enr_id, ADMIN), 200)
        assert data["progress_status"] == "COMPLETED"
        assert data["final_price_cents"] == 23800


# ============================================================================
# Queue B (Corner) — section: calculations
# ============================================================================
def test_rental_fee_tier_boundary_at_two_hours(api):
    """PRD §3.8: "The first 2 hours are billed at the full rate; the next 6
    hours (hours 3 through 8) are billed at half the rate."

    Design: Corner/calculations/rental_fee_tier_boundary_at_two_hours
    """
    school = create_school(name="Tb School")
    student = create_student(school["id"], full_name="Leo")
    equipment = create_equipment(school["id"], equipment_type="KAYAK",
                                 asset_tag="K-1", hourly_rate_cents=1000, deposit_cents=0)
    rental = create_rental(school["id"], student["id"], equipment["id"],
                           equipment["version"],
                           starts_at="2026-03-02T09:00:00Z",
                           ends_at="2026-03-02T11:00:00Z")
    data = validate_success(api.get_rental(rental["id"], ADMIN), 200)
    assert data["rental_fee_cents"] == 2000, \
        f"exactly 2h at full rate should be 2000: got {data['rental_fee_cents']}"


def test_refund_half_tier_at_thirty_six_hours(api):
    """PRD §3.8: "The refund percentage is one hundred percent when the lead
    time is at least 48 hours, fifty percent when it is at least 24 hours but
    under 48, and zero otherwise."

    Design: Corner/calculations/refund_half_tier_at_thirty_six_hours
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = setup_catalog(level_overrides={
        "max_students_per_instructor": 4, "base_price_cents": 10000,
        "min_age": 0, "requires_swim_test": False, "required_equipment_type": "NONE"})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    student = create_student_with_waiver(school["id"])
    enr = create_paid_enrollment(school["id"], student["id"], level["id"],
                                 planned_sessions=1, party_size=1)
    sess = create_session(school["id"], level["id"], inst["id"],
                         starts_at="2026-03-02T12:00:00Z", ends_at="2026-03-02T13:00:00Z",
                         tide_window_start="2026-03-02T11:00:00Z",
                         tide_window_end="2026-03-02T15:00:00Z", capacity=4)
    book(sess["id"], enr["id"], sess["version"])
    get_success_data(api_client.withdraw_enrollment(enr["id"], ADMIN))
    data = validate_success(api.refund_enrollment(enr["id"], ADMIN), 200)
    # earliest remaining session 36h out (>=24, <48) -> 50% of 10000 -> 5000.
    assert data["refund_cents"] == 5000, \
        f"36h lead -> 50% of 10000 -> 5000: got {data['refund_cents']}"


def test_estimate_group_and_member_discount_stacking(api):
    """PRD §3.8: "The membership discount is then applied to that intermediate
    amount, multiplying it by one minus the membership percentage."

    Design: Corner/calculations/enrollment_estimate_group_and_member_discount_stacking
    """
    cat = setup_catalog(level_overrides={
        "max_students_per_instructor": 6, "base_price_cents": 10000,
        "min_age": 0, "requires_swim_test": False, "required_equipment_type": "NONE"})
    school, level = cat["school"], cat["level"]
    student = create_student_with_waiver(school["id"])
    mem = create_membership(student["id"], tier="BASIC")
    res = api.create_enrollment({
        "school_id": school["id"], "student_id": student["id"],
        "course_level_id": level["id"], "membership_id": mem["id"],
        "planned_sessions": 3, "party_size": 4}, ADMIN)
    data = validate_success(res, 201)
    # 30000 * 0.8 (party 4) * 0.95 (BASIC) = 22800.
    assert data["estimated_price_cents"] == 22800, \
        f"stacked group(20%)+member(5%) on 30000 -> 22800: got {data['estimated_price_cents']}"


# ============================================================================
# Queue B (Corner) — section: consistency_model
# ============================================================================
def test_estimate_immediately_visible_on_create(api):
    """PRD §3.4: "Its `estimated_price_cents` is computed at creation (see §3.8),
    while `final_price_cents` and `refund_cents` remain null until the
    enrollment completes or is refunded, and `attended_count` starts at 0."

    Design: Corner/consistency_model/immediate_visibility_of_estimate_on_enrollment_create
    """
    cat = setup_catalog(level_overrides={
        "max_students_per_instructor": 4, "base_price_cents": 5000,
        "min_age": 0, "requires_swim_test": False, "required_equipment_type": "NONE"})
    school, level = cat["school"], cat["level"]
    student = create_student_with_waiver(school["id"])
    res = api.create_enrollment({
        "school_id": school["id"], "student_id": student["id"],
        "course_level_id": level["id"], "planned_sessions": 2, "party_size": 1}, ADMIN)
    data = validate_success(res, 201)
    # planned 2, party 1 (no discount), base 5000 -> 10000.
    assert data["estimated_price_cents"] == 10000, \
        f"estimate present immediately and equal to 10000: got {data['estimated_price_cents']}"
