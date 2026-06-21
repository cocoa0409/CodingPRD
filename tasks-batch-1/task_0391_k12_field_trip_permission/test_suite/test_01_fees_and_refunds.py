"""Fee calculation, scholarship, payment, and refund behavior.

Covers the dual-variant fee/refund calculations and the conserved-cash invariant.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_approved_trip,
    create_guardian,
    create_student,
    create_signed_slip,
    pay_slip,
    get_trip_version,
    setup_three_signed_slips_locked_ready,
    setup_approved_trip_with_paid_slip,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/slip_fee_provisional_vs_final_diverges
# ─────────────────────────────────────────────────────────────────────────────
class TestProvisionalVsFinalFee:
    def test_provisional_fee_before_lock(self, api):
        """PRD §3.7: "Its transport share is the trip's `transport_cost_cents`
        divided by the trip's current live `signed_count` (or by 1 if `signed_count`
        is zero), rounded up to the next whole cent."

        With 3 SIGNED slips, base_fee 1000, transport 10000: provisional
        transport_share = ceil(10000/3) = 3334, fee_due = 1000 + 3334 = 4334.

        Design: Difficulty/dual_variant_calc/slip_fee_provisional_vs_final_diverges
        """
        s = setup_three_signed_slips_locked_ready(
            transport_cost_cents=10_000, base_fee_cents=1000, deposit_cents=0, grade_band="MIDDLE"
        )
        teacher = make_teacher_headers(s["teacher_id"])
        slip_c = get_success_data(api.get_permission_slip(s["slip_c"]["id"], teacher))
        assert slip_c["fee_due_cents"] == 4334, (
            f"provisional fee should be 1000 + ceil(10000/3)=4334, got {slip_c['fee_due_cents']}"
        )

    def test_final_fee_after_lock_diverges_from_provisional(self, api):
        """PRD §3.8: "The base share is the trip's `transport_cost_cents` divided by C using integer floor division ... Those leftover cents are assigned one apiece to confirmed slips taken in order of `signed_at` ascending ... The first as-many-as-the-remainder slips in that order each get a transport share of the base share plus one cent; the rest get exactly the base share."

        After lock C=3: base_share = 10000//3 = 3333, remainder 1 to earliest
        signed_at (slip_a). So slip_c FINAL fee = 1000 + 3333 = 4333 (diverges from
        provisional 4334); slip_a FINAL fee = 1000 + 3334 = 4334.

        Design: Difficulty/dual_variant_calc/slip_fee_provisional_vs_final_diverges
        """
        s = setup_three_signed_slips_locked_ready(
            transport_cost_cents=10_000, base_fee_cents=1000, deposit_cents=0, grade_band="MIDDLE"
        )
        teacher = make_teacher_headers(s["teacher_id"])
        version = get_trip_version(s["teacher_id"], s["trip_id"])
        validate_success(
            api.lock_roster(s["trip_id"], {"expected_trip_version": version}, teacher), 200
        )
        slip_c = get_success_data(api.get_permission_slip(s["slip_c"]["id"], teacher))
        slip_a = get_success_data(api.get_permission_slip(s["slip_a"]["id"], teacher))
        assert slip_c["fee_due_cents"] == 4333, (
            f"final fee for non-remainder slip should be 1000 + 3333 = 4333, got {slip_c['fee_due_cents']}"
        )
        assert slip_a["fee_due_cents"] == 4334, (
            f"final fee for earliest-signed slip (remainder cent) should be 4334, got {slip_a['fee_due_cents']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/refund_voluntary_vs_cancellation_diverges
# ─────────────────────────────────────────────────────────────────────────────
class TestVoluntaryVsCancellationRefund:
    def _setup_three_signed_one_paid(self, api, deposit_cents=500):
        """Trip APPROVED, base_fee 1000, transport 10000, deposit 500, 3 SIGNED
        slips; slip_a PAID at provisional fee 4334."""
        teacher_id, trip = create_approved_trip(
            grade_band="MIDDLE", capacity=5, base_fee_cents=1000,
            transport_cost_cents=10_000, deposit_cents=deposit_cents,
        )
        trip_id = trip["id"]
        g_a = create_guardian(full_name="GA")
        g_b = create_guardian(full_name="GB")
        g_c = create_guardian(full_name="GC")
        st_a = create_student(teacher_id, full_name="SA", grade_level=7)
        st_b = create_student(teacher_id, full_name="SB", grade_level=7)
        st_c = create_student(teacher_id, full_name="SC", grade_level=7)
        slip_a = create_signed_slip(teacher_id, trip_id, st_a["id"], g_a["id"])
        create_signed_slip(teacher_id, trip_id, st_b["id"], g_b["id"])
        create_signed_slip(teacher_id, trip_id, st_c["id"], g_c["id"])
        teacher = make_teacher_headers(teacher_id)
        slip_a = get_success_data(api.get_permission_slip(slip_a["id"], teacher))
        # provisional fee = 1000 + ceil(10000/3) = 4334
        assert slip_a["fee_due_cents"] == 4334
        pay_slip(g_a["id"], trip_id, slip_a["id"], 4334)
        return teacher_id, trip_id, g_a["id"], slip_a["id"]

    def test_voluntary_withdraw_forfeits_deposit_and_transport(self, api):
        """PRD §3.10: "The refund for a voluntary withdrawal is calculated as what the guardian actually paid — the slip's `net_paid_cents` — minus the forfeited portion, where the forfeit is the trip's `deposit_cents` plus this slip's committed transport share, and the refund is that difference but never less than zero."

        paid 4334; forfeit = deposit 500 + transport_share 3334 = 3834;
        refund = max(4334 - 3834, 0) = 500; net_paid after refund = 4334 - 500 = 3834.

        Design: Difficulty/dual_variant_calc/refund_voluntary_vs_cancellation_diverges
        """
        teacher_id, trip_id, g_a, slip_a_id = self._setup_three_signed_one_paid(api)
        slip = validate_success(
            api.withdraw_slip(trip_id, slip_a_id, make_guardian_headers(g_a)), 200
        )
        assert slip["payment_status"] == "REFUNDED"
        assert slip["net_paid_cents"] == 3834, (
            f"net_paid after voluntary withdraw should be 4334 - 500 refund = 3834, got {slip['net_paid_cents']}"
        )
        trip = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert trip["collected_fees_cents"] == 3834, (
            f"trip collected_fees should retain 3834 after voluntary refund of 500, got {trip['collected_fees_cents']}"
        )

    def test_trip_cancellation_refunds_full_paid_amount(self, api):
        """PRD §3.10: "for a trip cancellation the refund equals exactly what was paid, with nothing forfeited, so the deposit and transport share are returned. Appending those refunds drives each affected slip's `net_paid_cents` to zero..."

        Same paid slip (4334) refunds the FULL 4334 on a Principal cancel — unlike
        the voluntary path which only refunds 500.

        Design: Difficulty/dual_variant_calc/refund_voluntary_vs_cancellation_diverges
        """
        teacher_id, trip_id, g_a, slip_a_id = self._setup_three_signed_one_paid(api)
        validate_success(api.cancel_trip(trip_id, _principal()), 200)
        slip = get_success_data(api.get_permission_slip(slip_a_id, make_teacher_headers(teacher_id)))
        assert slip["payment_status"] == "REFUNDED"
        assert slip["net_paid_cents"] == 0, (
            f"net_paid after full TRIP_CANCELLATION refund should be 0, got {slip['net_paid_cents']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/per_student_remainder_rounding_order
# ─────────────────────────────────────────────────────────────────────────────
class TestRemainderRoundingOrder:
    def test_floor_then_sweep_remainder_to_earliest_signed(self, api):
        """PRD §3.8: "Those leftover cents are assigned one apiece to confirmed slips taken in order of `signed_at` ascending, with `PermissionSlip.created_at` ascending as the tie-break — never by `id`. The first as-many-as-the-remainder slips in that order each get a transport share of the base share plus one cent; the rest get exactly the base share."

        transport 10000 over C=3: base_share 3333, remainder 1 → slip_a (earliest
        signed_at) fee 4334, slip_b/slip_c fee 4333. Floor-then-sweep, not
        sum-then-round.

        Design: Difficulty/combinatorial_formula/per_student_remainder_rounding_order
        """
        s = setup_three_signed_slips_locked_ready(
            transport_cost_cents=10_000, base_fee_cents=1000, deposit_cents=0, grade_band="HIGH"
        )
        teacher = make_teacher_headers(s["teacher_id"])
        version = get_trip_version(s["teacher_id"], s["trip_id"])
        validate_success(api.lock_roster(s["trip_id"], {"expected_trip_version": version}, teacher), 200)
        fa = get_success_data(api.get_permission_slip(s["slip_a"]["id"], teacher))["fee_due_cents"]
        fb = get_success_data(api.get_permission_slip(s["slip_b"]["id"], teacher))["fee_due_cents"]
        fc = get_success_data(api.get_permission_slip(s["slip_c"]["id"], teacher))["fee_due_cents"]
        assert fa == 4334, f"earliest-signed slip_a should get base+1 cent → 4334, got {fa}"
        assert fb == 4333, f"slip_b should get floored base → 4333, got {fb}"
        assert fc == 4333, f"slip_c should get floored base → 4333, got {fc}"

    def test_remainder_shares_conserve_transport_pot(self, api):
        """PRD §2.8: "the calculation floors each per-line share to a whole cent first and then sweeps the leftover cents one at a time, as detailed in §3; this floor-then-distribute order is mandatory and must not be replaced by summing first and rounding once."

        The three FINAL transport shares (3334 + 3333 + 3333) sum to 10000 ==
        transport_cost_cents — no pot drift. (Each slip fee = 1000 + its share.)

        Design: Difficulty/combinatorial_formula/per_student_remainder_rounding_order
        """
        s = setup_three_signed_slips_locked_ready(
            transport_cost_cents=10_000, base_fee_cents=1000, deposit_cents=0, grade_band="HIGH"
        )
        teacher = make_teacher_headers(s["teacher_id"])
        version = get_trip_version(s["teacher_id"], s["trip_id"])
        validate_success(api.lock_roster(s["trip_id"], {"expected_trip_version": version}, teacher), 200)
        shares = []
        for slip_key in ("slip_a", "slip_b", "slip_c"):
            fee = get_success_data(api.get_permission_slip(s[slip_key]["id"], teacher))["fee_due_cents"]
            shares.append(fee - 1000)  # subtract base_fee to recover transport share
        assert sum(shares) == 10_000, f"transport shares must sum to 10000, got {sum(shares)}"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/compensating_invariant/cash_conserved_pay_then_refund
# ─────────────────────────────────────────────────────────────────────────────
class TestCashConservation:
    def test_collected_fees_zero_after_pay_then_full_cancel_refund(self, api):
        """PRD §2.8: "Because the ledger is append-only — refunds are appended, never deleted — a payment followed by its refund leaves the conserved cash exactly where it started."

        Pay 1000 then a full TRIP_CANCELLATION refund of 1000 leaves
        collected_fees_cents and the slip's net_paid_cents both at 0.

        Design: Difficulty/compensating_invariant/cash_conserved_pay_then_refund
        """
        s = setup_approved_trip_with_paid_slip(base_fee_cents=1000, transport_cost_cents=0,
                                               deposit_cents=0)
        teacher = make_teacher_headers(s["teacher_id"])
        validate_success(api.cancel_trip(s["trip_id"], _principal()), 200)
        trip = get_success_data(api.get_field_trip(s["trip_id"], teacher))
        slip = get_success_data(api.get_permission_slip(s["slip"]["id"], teacher))
        assert trip["collected_fees_cents"] == 0, (
            f"collected_fees should return to 0 after pay+full refund, got {trip['collected_fees_cents']}"
        )
        assert slip["net_paid_cents"] == 0, (
            f"slip net_paid should be 0 after full refund, got {slip['net_paid_cents']}"
        )

    def test_conserved_cash_invariant_holds(self, api):
        """PRD §2.8: "The invariant the system preserves is that a trip's `collected_fees_cents` equals the sum of `net_paid_cents` across its slips."

        After pay 1000 then full cancel refund: collected_fees_cents (0) equals the
        sum of slip net_paid_cents (0).

        Design: Difficulty/compensating_invariant/cash_conserved_pay_then_refund
        """
        s = setup_approved_trip_with_paid_slip(base_fee_cents=1000, transport_cost_cents=0,
                                               deposit_cents=0)
        teacher = make_teacher_headers(s["teacher_id"])
        validate_success(api.cancel_trip(s["trip_id"], _principal()), 200)
        trip = get_success_data(api.get_field_trip(s["trip_id"], teacher))
        slip = get_success_data(api.get_permission_slip(s["slip"]["id"], teacher))
        assert trip["collected_fees_cents"] == slip["net_paid_cents"], (
            "conserved-cash invariant: collected_fees must equal sum of slip net_paid"
        )


def _principal():
    return TEST_USERS["principal_headers"]
