"""Credit-limit overrides (windows, SoD, priority pairs) and forward
capacity accounting on lendable positions.

Covers difficulty instances limit_override_window_half_open_exclusion,
sod_error_beats_window_overlap_on_override_approve,
forward_reservation_aggregate_capacity_per_day, and the corner instance
override_window_inverted_rejected.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_borrower,
    create_limit_override_payload,
    create_loan_proposal,
    get_borrower,
    get_loan,
    get_position,
    make_desk_trader_headers,
    make_risk_officer_headers,
    setup_desk,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


class TestOverrideWindows:
    def test_half_open_adjacency_permitted_overlap_rejected(self, api):
        """PRD §3.8: "the new window may not overlap any other `APPROVED`
        override for the same borrower, where windows are half-open so pure
        adjacency is permitted; overlap is rejected with
        `ERR_OVERRIDE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/limit_override_window_half_open_exclusion
        """
        borrower = create_borrower(display_name="Borrower Win")
        trader = make_desk_trader_headers("trader-1")
        o1 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(new_limit_cents=200_000_000,
                                          effective_from="2026-09-01",
                                          expires_at="2026-10-01"),
            trader), expected_status=201)
        validate_success(api.approve_limit_override(
            o1["id"], make_risk_officer_headers("risk-1")))
        o2 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(new_limit_cents=250_000_000,
                                          effective_from="2026-10-01",
                                          expires_at="2026-11-01"),
            trader), expected_status=201)
        o3 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(new_limit_cents=300_000_000,
                                          effective_from="2026-09-30",
                                          expires_at="2026-10-15"),
            trader), expected_status=201)

        # Adjacent [10-01, 11-01) to approved [09-01, 10-01): permitted.
        o2_after = validate_success(api.approve_limit_override(
            o2["id"], make_risk_officer_headers("risk-2")))
        assert o2_after["status"] == "APPROVED"

        # [09-30, 10-15) covers days inside both approved windows: rejected.
        resp = api.approve_limit_override(
            o3["id"], make_risk_officer_headers("risk-1"))
        validate_error(resp, ApiErrorId.ERR_OVERRIDE_WINDOW_OVERLAP)
        o3_after = validate_success(api.get_limit_override(o3["id"], RISK))
        assert o3_after["status"] == "REQUESTED"

    def test_overlapping_both_neighbors_rejected_second_half(self, api):
        """PRD §3.8: "the new window may not overlap any other `APPROVED`
        override for the same borrower, where windows are half-open so pure
        adjacency is permitted; overlap is rejected with
        `ERR_OVERRIDE_WINDOW_OVERLAP`."

        A window overlapping only the second approved window is also
        rejected: [2026-10-15, 2026-10-20) collides with [10-01, 11-01).

        Design: Difficulty/resource_temporal_overlap/limit_override_window_half_open_exclusion
        """
        borrower = create_borrower(display_name="Borrower WinB")
        trader = make_desk_trader_headers("trader-1")
        o1 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(effective_from="2026-10-01",
                                          expires_at="2026-11-01"),
            trader), expected_status=201)
        validate_success(api.approve_limit_override(
            o1["id"], make_risk_officer_headers("risk-1")))
        o4 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(effective_from="2026-10-15",
                                          expires_at="2026-10-20"),
            trader), expected_status=201)
        resp = api.approve_limit_override(
            o4["id"], make_risk_officer_headers("risk-2"))
        validate_error(resp, ApiErrorId.ERR_OVERRIDE_WINDOW_OVERLAP)
        assert validate_success(
            api.get_limit_override(o4["id"], RISK))["status"] == "REQUESTED"

    def test_override_window_inverted_rejected(self, api):
        """PRD §3.8: "A `DeskTrader` requests a `LimitOverride` for a
        borrower with a `new_limit_cents` and a window from `effective_from`
        (inclusive) to `expires_at` (exclusive); the start must be strictly
        before the end, or the request is rejected with
        `ERR_INVALID_WINDOW`."

        Design: Corner/errors/override_window_inverted_rejected
        """
        borrower = create_borrower(display_name="Borrower Win2")
        resp = api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(effective_from="2026-10-01",
                                          expires_at="2026-09-01"),
            make_desk_trader_headers("trader-9"))
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestOverrideSoDPriority:
    def test_sod_error_beats_window_overlap_on_approve(self, api):
        """PRD §2.7: "When several checks could fail on the same request, the
        server evaluates them in a fixed priority order and reports the first
        failure".
        PRD §2.7: "a `HALTED` security blocks direct loan creation,
        matching, booking, and pledging that security as collateral
        (`ERR_SECURITY_HALTED`); a borrower that is not `ACTIVE` blocks
        matching and booking (`ERR_BORROWER_SUSPENDED`); an owner that is
        not `ACTIVE` blocks position creation, matching, and booking
        (`ERR_OWNER_SUSPENDED`); segregation-of-duties rules block override
        approval and report filing (`ERR_SOD_VIOLATION`)."
        PRD §2.7: "no overlap between an approved override window and
        another approved window for the same borrower
        (`ERR_OVERRIDE_WINDOW_OVERLAP`)"
        PRD §3.8: "Approval carries a segregation-of-duties rule — the
        approver's `X-User-ID` must differ from the `requested_by_user_id`,
        or the decision is rejected with `ERR_SOD_VIOLATION`"

        Design: Difficulty/priority_pair_validation_conflict/sod_error_beats_window_overlap_on_override_approve
        """
        borrower = create_borrower(display_name="Borrower Sod")
        trader7 = make_desk_trader_headers("trader-7")
        o1 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(new_limit_cents=200_000_000,
                                          effective_from="2026-09-01",
                                          expires_at="2026-10-01"),
            trader7), expected_status=201)
        validate_success(api.approve_limit_override(
            o1["id"], make_risk_officer_headers("risk-1")))
        o2 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(new_limit_cents=300_000_000,
                                          effective_from="2026-09-15",
                                          expires_at="2026-10-15"),
            trader7), expected_status=201)

        # Approver's X-User-ID equals the requester's AND the window
        # overlaps O1: the safety gate (priority 7) wins over the
        # structural rule (priority 8).
        resp = api.approve_limit_override(
            o2["id"], make_risk_officer_headers("trader-7"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert validate_success(
            api.get_limit_override(o2["id"], RISK))["status"] == "REQUESTED"
        # Clock is 2026-08-01, before O1's window; effective limit unchanged.
        assert get_borrower(borrower["id"],
                            RISK)["effective_limit_cents"] == 100_000_000

    def test_overlap_error_fires_when_sod_is_satisfied(self, api):
        """PRD §2.7: "the server evaluates them in a fixed priority order and
        reports the first failure"
        PRD §3.8: "the new window may not overlap any other `APPROVED`
        override for the same borrower, where windows are half-open so pure
        adjacency is permitted; overlap is rejected with
        `ERR_OVERRIDE_WINDOW_OVERLAP`."

        With a distinct approver (SoD satisfied), the same overlapping window
        reports the structural error — isolating the priority pair's lower
        branch.

        Design: Difficulty/priority_pair_validation_conflict/sod_error_beats_window_overlap_on_override_approve
        """
        borrower = create_borrower(display_name="Borrower SodB")
        trader7 = make_desk_trader_headers("trader-7")
        o1 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(effective_from="2026-09-01",
                                          expires_at="2026-10-01"),
            trader7), expected_status=201)
        validate_success(api.approve_limit_override(
            o1["id"], make_risk_officer_headers("risk-1")))
        o2 = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(new_limit_cents=300_000_000,
                                          effective_from="2026-09-15",
                                          expires_at="2026-10-15"),
            trader7), expected_status=201)
        resp = api.approve_limit_override(
            o2["id"], make_risk_officer_headers("risk-9"))
        validate_error(resp, ApiErrorId.ERR_OVERRIDE_WINDOW_OVERLAP)
        assert validate_success(
            api.get_limit_override(o2["id"], RISK))["status"] == "REQUESTED"


class TestForwardCapacity:
    def _capacity_setup(self, api):
        security, owner, borrower, position = setup_desk(
            security_symbol="CAP1", quantity_total=10000,
            credit_limit_cents=500_000_000)
        return security, owner, borrower, position

    def test_per_day_aggregate_gate_and_half_open_adjacency(self, api):
        """PRD §2.10: "Taking a new reservation — at direct loan creation or
        at match time — is rejected with `ERR_FORWARD_CAPACITY_EXCEEDED` if
        adding the new quantity would push occupancy above the position's
        `quantity_total` on any single day of the new loan's window; there is
        no buffer."
        PRD §2.10: "A loan's occupancy window runs from the current clock
        date through the current date plus its `term_days`, treated as a
        half-open interval: the start day counts, the end day does not, so a
        deal that starts on the day another deal's window ends does not
        overlap it."
        PRD §3.2: "`quantity_available` is what remains — `quantity_total`
        minus `quantity_reserved` minus `quantity_on_loan`."

        Design: Difficulty/resource_temporal_overlap/forward_reservation_aggregate_capacity_per_day
        """
        from test_helpers import set_clock
        security, owner, borrower, position = self._capacity_setup(api)
        # Clock 2026-08-01. P1 occupies [08-01, 08-08); P2 [08-01, 08-15).
        p1 = create_loan_proposal(owner, borrower, security, position,
                                  quantity=6000, rate_bps=25, term_days=7)
        p2 = create_loan_proposal(owner, borrower, security, position,
                                  quantity=4000, rate_bps=25, term_days=14)

        # 4001 more would push 08-01..07 occupancy to 14001 > 10000.
        resp = api.create_loan(
            {"owner_id": owner["id"], "borrower_id": borrower["id"],
             "security_id": security["id"], "position_id": position["id"],
             "quantity": 4001, "collateral_type": "SECURITIES",
             "rate_bps": 25, "term_days": 7}, TRADER)
        validate_error(resp, ApiErrorId.ERR_FORWARD_CAPACITY_EXCEEDED)

        # Advance to 2026-08-08: P1's window ended 08-08 (exclusive), so the
        # same 4001-share request now overlaps only P2: 4000+4001 <= 10000.
        set_clock("2026-08-08T00:00:00Z")
        p4 = validate_success(api.create_loan(
            {"owner_id": owner["id"], "borrower_id": borrower["id"],
             "security_id": security["id"], "position_id": position["id"],
             "quantity": 4001, "collateral_type": "SECURITIES",
             "rate_bps": 25, "term_days": 7}, TRADER), expected_status=201)
        assert p4["status"] == "PROPOSED"

        pos = get_position(position["id"])
        assert pos["quantity_reserved"] == 14001
        assert pos["quantity_available"] == -4001

    def test_exact_capacity_boundary_allowed(self, api):
        """PRD §2.10: "is rejected with `ERR_FORWARD_CAPACITY_EXCEEDED` if
        adding the new quantity would push occupancy above the position's
        `quantity_total` on any single day of the new loan's window; there is
        no buffer."

        Boundary: occupancy exactly equal to quantity_total is allowed
        (the rejection requires exceeding the total).

        Design: Difficulty/resource_temporal_overlap/forward_reservation_aggregate_capacity_per_day
        """
        security, owner, borrower, position = self._capacity_setup(api)
        create_loan_proposal(owner, borrower, security, position,
                             quantity=6000, rate_bps=25, term_days=7)
        p2 = validate_success(api.create_loan(
            {"owner_id": owner["id"], "borrower_id": borrower["id"],
             "security_id": security["id"], "position_id": position["id"],
             "quantity": 4000, "collateral_type": "SECURITIES",
             "rate_bps": 25, "term_days": 7}, TRADER), expected_status=201)
        assert p2["status"] == "PROPOSED"
        pos = get_position(position["id"])
        assert pos["quantity_reserved"] == 10000
        assert pos["quantity_available"] == 0
