"""Inter-district transfer authorization lifecycle.

Covers PRD §3.3 (transfer request flow, capacity arithmetic, revoke
cascade) and §3.4 (cross-district submit requires APPROVED transfer).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    advance_clock_to,
    api_client,
    approve_transfer_request,
    assert_transfer_request,
    create_application,
    create_family,
    create_program,
    create_school,
    create_district,
    create_student,
    create_transfer_request,
    deny_transfer_request,
    draw_lottery,
    get_application,
    iso_utc,
    make_district_admin_headers,
    make_family_user_headers,
    open_program_window,
    close_program_window,
    revoke_transfer_request,
    setup_cross_district_setup,
    setup_family_with_student,
    submit_application,
    make_cross_district_application_with_approved_transfer,
    validate_error,
    validate_success,
)


class TestApprovalPath:

    def test_pending_to_approved_with_capacity_held(self, api):
        """PRD §3.3: "Otherwise the transfer request transitions from
        PENDING to APPROVED and its capacity_units_held is set to 1."
        """
        bundle = make_cross_district_application_with_approved_transfer()
        tr = bundle["transfer_request"]
        assert_transfer_request(tr)
        assert tr["status"] == "APPROVED"
        assert tr["capacity_units_held"] == 1

    def test_approval_when_district_refuses_transfers_yields_no_transfers(self, api):
        """PRD §3.3: "Approval is rejected with ERR_DISTRICT_NO_TRANSFERS
        if the target district has accepts_inter_district_transfers set
        to false."
        """
        bundle = setup_cross_district_setup(target_accepts_transfers=False)
        app = create_application(
            bundle["family"], bundle["student"], bundle["target_program"],
            choice_rank=1,
        )
        tr = create_transfer_request(
            bundle["family"], app, bundle["target_district"],
        )
        # Try to approve under admin of target_district.
        res = api.approve_transfer_request(
            tr["id"],
            make_district_admin_headers(bundle["target_district"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DISTRICT_NO_TRANSFERS.value)


class TestCapacityArithmetic:

    def test_approval_at_capacity_floor_succeeds(self, api):
        """PRD §3.3: capacity = SUM(seats_total - seats_accepted) across
        MAGNET/CHARTER programs in the target district whose
        window_status is in {SCHEDULED, OPEN, CLOSED, LOTTERY_DRAWN,
        BACKFILL}. "If granting this approval would push that count
        strictly above the computed capacity ... is rejected with
        ERR_DISTRICT_CAPACITY_EXCEEDED."

        Claim: with capacity = 2 and zero existing APPROVED rows, the
        first approval succeeds (held=1 ≤ capacity=2).
        """
        bundle = make_cross_district_application_with_approved_transfer(
            target_seats_total=2,
        )
        assert bundle["transfer_request"]["status"] == "APPROVED"
        assert bundle["transfer_request"]["capacity_units_held"] == 1

    def test_approval_exceeding_capacity_rejected(self, api):
        """PRD §3.3: "If granting this approval would push that count
        strictly above the computed capacity — that is, if the current
        APPROVED count plus one would exceed the capacity — the
        approval is rejected with ERR_DISTRICT_CAPACITY_EXCEEDED."

        Claim: with capacity = 1 (one MAGNET program with seats_total=1)
        and one already-APPROVED transfer, a second approval is
        rejected with ERR_DISTRICT_CAPACITY_EXCEEDED.
        """
        # capacity = 1, accept transfers
        advance_clock_to(DEFAULT_BASE_CLOCK)
        target = create_district(accepts_inter_district_transfers=True)
        target_school = create_school(
            target, school_type="MAGNET", grade_levels_offered=[5],
        )
        target_program = create_program(
            target, target_school,
            grade_level=5,
            seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
            lottery_seed="cap1",
        )
        home = create_district()
        # First family with APPROVED TR.
        f1 = create_family(home, poverty_index_score=0.10)
        s1 = create_student(f1, grade_level_next_year=5)
        a1 = create_application(f1, s1, target_program, choice_rank=1)
        tr1 = create_transfer_request(f1, a1, target)
        tr1 = approve_transfer_request(target, tr1)
        assert tr1["status"] == "APPROVED"
        # Second family racing for a non-existent second slot.
        f2 = create_family(home, poverty_index_score=0.10)
        s2 = create_student(f2, grade_level_next_year=5)
        a2 = create_application(f2, s2, target_program, choice_rank=1)
        tr2 = create_transfer_request(f2, a2, target)
        res = api.approve_transfer_request(
            tr2["id"], make_district_admin_headers(target["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DISTRICT_CAPACITY_EXCEEDED.value)


class TestDeny:

    def test_pending_to_denied(self, api):
        """PRD §3.3: "The same administrator may deny a pending request,
        transitioning PENDING to DENIED."
        """
        bundle = setup_cross_district_setup()
        app = create_application(
            bundle["family"], bundle["student"], bundle["target_program"],
            choice_rank=1,
        )
        tr = create_transfer_request(bundle["family"], app, bundle["target_district"])
        denied = deny_transfer_request(bundle["target_district"], tr)
        assert denied["status"] == "DENIED"
        assert denied["capacity_units_held"] == 0


class TestRevokeCascade:

    def test_revoke_resets_capacity_units(self, api):
        """PRD §3.3: "Revocation transitions APPROVED to REVOKED, sets
        capacity_units_held back to 0".

        Claim: after revoke, tr.capacity_units_held == 0.
        """
        bundle = make_cross_district_application_with_approved_transfer()
        revoked = revoke_transfer_request(
            bundle["target_district"], bundle["transfer_request"],
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["capacity_units_held"] == 0


class TestSubmitRequiresApprovedTransfer:

    def test_cross_district_submit_without_approved_transfer_rejected(self, api):
        """PRD §3.4: "If the application crosses district lines — the
        program's school's district_id is different from the family's
        residency_district_id — a transfer request linking this
        application must currently be in APPROVED; if not, the
        submission is rejected with ERR_TRANSFER_NOT_APPROVED."
        """
        bundle = setup_cross_district_setup()
        app = create_application(
            bundle["family"], bundle["student"], bundle["target_program"],
            choice_rank=1,
        )
        # Create transfer request but do NOT approve.
        create_transfer_request(bundle["family"], app, bundle["target_district"])
        # Open window of target program.
        open_program_window(bundle["target_program"])
        res = api.submit_application(
            app["id"], make_family_user_headers(bundle["family"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRANSFER_NOT_APPROVED.value)

    def test_cross_district_submit_with_approved_transfer_succeeds(self, api):
        """PRD §3.4: with APPROVED transfer, cross-district submit
        succeeds."""
        bundle = make_cross_district_application_with_approved_transfer()
        open_program_window(bundle["target_program"])
        submitted = submit_application(bundle["family"], bundle["application"])
        assert submitted["status"] == "SUBMITTED"
