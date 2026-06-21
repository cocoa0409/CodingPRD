"""Cyclic FieldTrip approval chain (reject → DRAFT revision loop) and the parallel
signature × payment dimensions of a PermissionSlip.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_approved_trip,
    create_pending_principal_trip,
    create_guardian,
    create_student,
    create_signed_slip,
    pay_slip,
)


_PRINCIPAL = TEST_USERS["principal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/trip_reject_loops_back_to_draft
# ─────────────────────────────────────────────────────────────────────────────
class TestApprovalRejectRevisionLoop:
    def test_principal_reject_returns_trip_to_draft(self, api):
        """PRD §3.2: "a `PRINCIPAL`/`REJECT` decision sends the trip back to `DRAFT` for the teacher to revise and resubmit, also appending a record."

        Design: Difficulty/non_linear_state_machine/trip_reject_loops_back_to_draft
        """
        teacher_id, trip = create_pending_principal_trip(grade_band="ELEMENTARY", capacity=10)
        trip_id = trip["id"]
        validate_success(
            api.create_approval(trip_id, {"step": "PRINCIPAL", "decision": "REJECT",
                                          "comment": "fix budget"}, _PRINCIPAL), 201
        )
        after = get_success_data(api.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
        assert after["status"] == "DRAFT", (
            f"trip should return to DRAFT after PRINCIPAL REJECT, got {after['status']}"
        )

    def test_rejected_trip_resubmits_and_closes_cycle(self, api):
        """PRD §3.2: "The reject branches form revision loops: a rejected trip lands back in `DRAFT`, may be edited, and may re-enter the chain."
        PRD §3.2: "When the trip is ready, the teacher submits it, advancing `DRAFT → PENDING_PRINCIPAL`."

        After a reject lands the trip in DRAFT, resubmitting drives it back to
        PENDING_PRINCIPAL — the cycle closes.

        Design: Difficulty/non_linear_state_machine/trip_reject_loops_back_to_draft
        """
        teacher_id, trip = create_pending_principal_trip(grade_band="ELEMENTARY", capacity=10)
        trip_id = trip["id"]
        teacher = make_teacher_headers(teacher_id)
        validate_success(
            api.create_approval(trip_id, {"step": "PRINCIPAL", "decision": "REJECT"}, _PRINCIPAL), 201
        )
        resubmitted = validate_success(api.submit_trip(trip_id, teacher), 200)
        assert resubmitted["status"] == "PENDING_PRINCIPAL", (
            f"resubmit should drive DRAFT → PENDING_PRINCIPAL, got {resubmitted['status']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/slip_parallel_signature_payment_dimensions
# ─────────────────────────────────────────────────────────────────────────────
class TestSlipParallelDimensions:
    def _setup_signed_and_paid(self, api):
        """Trip APPROVED; one slip SIGNED then PAID (base_fee 1000, transport 0,
        deposit 0 → fee_due 1000)."""
        teacher_id, trip = create_approved_trip(
            grade_band="ELEMENTARY", capacity=5, base_fee_cents=1000,
            transport_cost_cents=0, deposit_cents=0,
        )
        trip_id = trip["id"]
        g = create_guardian(full_name="G6")
        st = create_student(teacher_id, full_name="S6", grade_level=5)
        slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        pay_slip(g["id"], trip_id, slip["id"], 1000)
        return teacher_id, trip_id, g["id"], slip["id"]

    def test_revoke_signature_leaves_payment_paid(self, api):
        """PRD §2.10: "A `PermissionSlip` carries three independent dimensions: `signature_status` is `UNSIGNED`, `SIGNED`, or `REVOKED`; `payment_status` is `UNPAID`, `PAID`, or `REFUNDED`; and `participation_status` is `PENDING`, `CONFIRMED`, or `WITHDRAWN`."
        PRD §3.3: "A guardian may revoke their own signature before the roster locks, driving `signature_status` `SIGNED → REVOKED`."

        Revoking the signature of a PAID slip moves signature_status to REVOKED
        while payment_status stays PAID — the two dimensions evolve independently.

        Design: Difficulty/non_linear_state_machine/slip_parallel_signature_payment_dimensions
        """
        teacher_id, trip_id, g_id, slip_id = self._setup_signed_and_paid(api)
        slip = validate_success(api.revoke_slip(trip_id, slip_id, make_guardian_headers(g_id)), 200)
        assert slip["signature_status"] == "REVOKED"
        assert slip["payment_status"] == "PAID", (
            f"payment dimension should be unaffected by signature revoke, got {slip['payment_status']}"
        )

    def test_revoke_signature_leaves_payment_ledger_intact(self, api):
        """PRD §2.8: "a slip's `net_paid_cents` always equals the sum of `amount_cents` over that slip's own transactions."

        Revoking the signature does not touch the payment ledger: net_paid_cents
        stays 1000 (the payment dimension is independent of the signature one).

        Design: Difficulty/non_linear_state_machine/slip_parallel_signature_payment_dimensions
        """
        teacher_id, trip_id, g_id, slip_id = self._setup_signed_and_paid(api)
        slip = validate_success(api.revoke_slip(trip_id, slip_id, make_guardian_headers(g_id)), 200)
        assert slip["net_paid_cents"] == 1000, (
            f"net_paid_cents should stay 1000 after signature revoke, got {slip['net_paid_cents']}"
        )
