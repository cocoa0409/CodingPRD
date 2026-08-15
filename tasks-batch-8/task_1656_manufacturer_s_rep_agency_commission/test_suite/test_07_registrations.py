"""Project registrations: protection windows, renewal, withdrawal, holds (PRD §3.3).

Covers the SUBMITTED/REJECTED resubmission loop, the APPROVED renewal self-loop,
half-open window adjacency at approval, protection's placed_at containment rule,
withdrawal re-attribution, and the COMMISSION_HOLD submission gate.
"""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    approve_registration,
    create_customer,
    create_order,
    create_principal,
    create_rep,
    get_order,
    get_registration,
    get_rep,
    list_splits,
    make_order_line,
    make_principal_ops_headers,
    make_rep_headers,
    order_line,
    parse_instant,
    post_adjustment,
    set_clock,
    setup_base_scenario,
    splits_for_line,
    submit_registration,
    suspend_agreement,
    validate_error,
    TEST_USERS,
)


def _admin():
    return TEST_USERS["agency_admin_headers"]


class TestRejectResubmitRenewCycle:
    def test_registration_reject_resubmit_loop(self, api):
        """PRD §3.3: "The owning rep — and only that rep, else
        `ERR_FORBIDDEN_NOT_OWNER` — may resubmit a `REJECTED` registration, returning
        it to `SUBMITTED` with `submitted_at` refreshed to the current clock".
        PRD §3.3: "On approval, `protection_start` is set to the current clock and
        `protection_end` to 180 days later."

        Design: Difficulty/non_linear_state_machine/registration_reject_resubmit_renew_cycle
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        reg = submit_registration(principal["id"], base["customer"]["id"], r1["id"],
                                  project_name="Project Cyclic")
        assert reg["status"] == "SUBMITTED"

        rejected = api.reject_registration(
            reg["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        assert rejected["status"] == "REJECTED"

        resubmitted = api.resubmit_registration(
            reg["id"], make_rep_headers(r1["id"]),
        ).json()["data"]
        assert resubmitted["status"] == "SUBMITTED"

        approved = approve_registration(reg["id"], principal["id"])
        assert approved["status"] == "APPROVED"
        assert parse_instant(approved["protection_start"]) == parse_instant(CLOCK_DEFAULT)
        assert parse_instant(approved["protection_end"]) == datetime(
            2027, 1, 28, tzinfo=timezone.utc,
        ), "approval at the default clock 2026-08-01 + 180 days"

    def test_registration_renewal_self_loop_extends_protection(self, api):
        """PRD §3.3: "Renewal is allowed only inside the renewal window: the clock
        must be at least thirty days before `protection_end` and still strictly before
        `protection_end` itself". "A successful renewal increments `renewals_used` by
        one and extends `protection_end` by ninety days, leaving the registration in
        `APPROVED`."

        Design: Difficulty/non_linear_state_machine/registration_reject_resubmit_renew_cycle
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        reg = submit_registration(principal["id"], base["customer"]["id"], r1["id"],
                                  project_name="Project Cyclic")
        approve_registration(reg["id"], principal["id"])
        # Inside the renewal window: protection_end (2027-01-28) minus 30 days.
        set_clock("2027-01-10T00:00:00Z")
        renewed = api.renew_registration(reg["id"], make_rep_headers(r1["id"])).json()["data"]
        assert renewed["status"] == "APPROVED", "renewal is an APPROVED self-loop"
        assert renewed["renewals_used"] == 1
        assert parse_instant(renewed["protection_end"]) == datetime(
            2027, 4, 28, tzinfo=timezone.utc,
        ), "2027-01-28 + 90 days"


class TestRenewalGuards:
    def test_renew_window_and_limit_guards(self, api):
        """PRD §3.3: "an attempt outside that window — too early, or after protection
        has lapsed — is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. A registration
        that has already consumed its single renewal is rejected with
        `ERR_RENEWAL_LIMIT_REACHED`, enforced through the `renewals_used` counter that
        starts at zero."

        Design: Corner/validations/renew_window_and_limit_guards
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        principal = base["principal"]
        r1 = base["reps"][0]
        reg = submit_registration(principal["id"], base["customer"]["id"], r1["id"],
                                  project_name="Project R")
        approve_registration(reg["id"], principal["id"])

        # Too early: 2026-12-01 is more than thirty days before the 2027-01-28 end.
        set_clock("2026-12-01T00:00:00Z")
        early = api.renew_registration(reg["id"], make_rep_headers(r1["id"]))
        validate_error(early, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN)

        # Inside the window the renewal succeeds.
        set_clock("2027-01-10T00:00:00Z")
        renewed = api.renew_registration(reg["id"], make_rep_headers(r1["id"])).json()["data"]
        assert renewed["renewals_used"] == 1

        # With the single renewal consumed, only the cap can fail: the clock sits
        # inside the extended window [2027-03-29, 2027-04-28), isolating the limit.
        set_clock("2027-04-10T00:00:00Z")
        capped = api.renew_registration(reg["id"], make_rep_headers(r1["id"]))
        validate_error(capped, ApiErrorId.ERR_RENEWAL_LIMIT_REACHED)


class TestApprovalOverlap:
    def test_referential_gate_fires_before_overlap(self, api):
        """PRD §2.9: "When a request could fail several rules at once, the checks
        execute in a fixed pipeline and the request fails with the first check it
        violates; later checks are never reached." Linked-entity gates
        ("`ERR_AGREEMENT_NOT_ACTIVE`", check 7) precede temporal windows
        ("`ERR_PROTECTION_WINDOW_OVERLAP`", check 8).

        Design: Difficulty/priority_pair_validation_conflict/registration_referential_beats_overlap_temporal
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        reg_a = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Alpha")
        approve_registration(reg_a["id"], principal["id"])
        reg_b = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Beta")

        suspend_agreement(base["agreement"]["id"])
        resp = api.approve_registration(
            reg_b["id"], make_principal_ops_headers(principal["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        assert get_registration(reg_b["id"])["status"] == "SUBMITTED"

    def test_overlap_error_fires_when_agreement_active(self, api):
        """PRD §3.3: "And no other `APPROVED` registration for the same combination
        of `principal_id`, `customer_id`, and `family_code` may have a protection
        window that overlaps the new one."
        PRD §3.3: "A colliding approval is rejected with
        `ERR_PROTECTION_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/registration_referential_beats_overlap_temporal
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        reg_a = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Alpha")
        approve_registration(reg_a["id"], principal["id"])
        reg_b = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Beta")
        # Control: agreement ACTIVE, so only the temporal overlap rule can fail.
        set_clock("2026-09-01T00:00:00Z")
        resp = api.approve_registration(
            reg_b["id"], make_principal_ops_headers(principal["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROTECTION_WINDOW_OVERLAP)
        assert get_registration(reg_b["id"])["status"] == "SUBMITTED"

    def test_overlapping_window_approval_rejected(self, api):
        """PRD §3.3: "The new window opens at the current clock and closes 180 days
        later; windows are half-open — they include their opening instant and exclude
        their closing instant — so a new window that opens exactly when an existing
        window closes does not overlap. A colliding approval is rejected with
        `ERR_PROTECTION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/registration_windows_half_open_adjacency
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        reg_a = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Alpha")
        approve_registration(reg_a["id"], principal["id"])
        reg_b = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Beta")
        set_clock("2026-09-01T00:00:00Z")  # reg_A window [2026-08-01, 2027-01-28) open
        resp = api.approve_registration(
            reg_b["id"], make_principal_ops_headers(principal["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROTECTION_WINDOW_OVERLAP)

    def test_adjacent_window_approval_allowed(self, api):
        """PRD §3.3: "windows are half-open — they include their opening instant and
        exclude their closing instant — so a new window that opens exactly when an
        existing window closes does not overlap." PRD §2.5: "registrations in
        `APPROVED` whose `protection_end` has been reached transition to `EXPIRED`".

        Design: Difficulty/resource_temporal_overlap/registration_windows_half_open_adjacency
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        reg_a = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Alpha")
        approve_registration(reg_a["id"], principal["id"])
        reg_b = submit_registration(principal["id"], customer["id"], r1["id"],
                                    project_name="Project Beta")

        # At exactly reg_A's protection_end the sweep expires reg_A, and reg_B's new
        # window opens at the same instant without overlapping (half-open adjacency).
        set_clock("2027-01-28T00:00:00Z")
        assert get_registration(reg_a["id"])["status"] == "EXPIRED"
        approved = approve_registration(reg_b["id"], principal["id"])
        assert approved["status"] == "APPROVED"
        assert parse_instant(approved["protection_start"]) == datetime(
            2027, 1, 28, tzinfo=timezone.utc,
        )
        assert parse_instant(approved["protection_end"]) == datetime(
            2027, 7, 27, tzinfo=timezone.utc,
        ), "2027-01-28 + 180 days"


class TestProtectionContainment:
    def test_order_placed_inside_window_is_protected(self, api):
        """PRD §3.3: "A line is considered protected for commission purposes when an
        `APPROVED` registration exists whose `principal_id`, `customer_id`, and
        `family_code` all match the order and line, and whose window contains the
        order's `placed_at` — including the window's opening instant and excluding its
        closing instant."

        Design: Difficulty/boundary_precision_check/protection_end_exclusive
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project Window")
        approve_registration(reg["id"], principal["id"])
        # Twelve hours before the window closes: still inside.
        set_clock("2027-01-27T12:00:00Z")
        order = create_order(
            customer["id"], principal["id"], "PO-IN", placed_at="2027-01-27T12:00:00Z",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        assert len(rows) == 1 and rows[0]["role"] == "REGISTERED"
        assert rows[0]["rep_id"] == r1["id"]
        assert order_line(get_order(order["id"]), "L1")["protected_registration_id"] == reg["id"]

    def test_order_placed_at_protection_end_is_unprotected(self, api):
        """PRD §3.3: "A line is considered protected for commission purposes when an
        `APPROVED` registration exists whose `principal_id`, `customer_id`, and
        `family_code` all match the order and line, and whose window contains the
        order's `placed_at` — including the window's opening instant and excluding its
        closing instant." An order placed exactly at `protection_end` falls outside
        the half-open window.

        Design: Difficulty/boundary_precision_check/protection_end_exclusive
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1, r2 = base["reps"]
        customer = base["customer"]
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project Window")
        approve_registration(reg["id"], principal["id"])

        set_clock("2027-01-28T00:00:00Z")  # exactly protection_end
        assert get_registration(reg["id"])["status"] == "EXPIRED"
        order = create_order(
            customer["id"], principal["id"], "PO-OUT", placed_at="2027-01-28T00:00:00Z",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        by_role = {row["role"]: row for row in rows}
        assert set(by_role) == {"SPECIFY", "SHIP_TO"}
        assert by_role["SPECIFY"]["rep_id"] == r1["id"]
        assert by_role["SPECIFY"]["share_bp"] == 6000
        assert by_role["SHIP_TO"]["rep_id"] == r2["id"]
        assert by_role["SHIP_TO"]["share_bp"] == 4000
        assert order_line(get_order(order["id"]), "L1")["protected_registration_id"] is None


class TestWithdrawalAndHold:
    def test_withdraw_approved_registration_reattributes_order(self, api):
        """PRD §3.3: "Withdrawal of an `APPROVED` registration voids protection from
        that moment." and "In all three cases, uninvoiced orders of that principal —
        those still in `PLACED` or `SHIPPED` — whose lines referenced the registration
        are re-attributed: the `REGISTERED` share is dropped, the attribution
        precedence of §3.4 is re-resolved for those lines, and each affected line's
        `protected_registration_id` is cleared."

        Design: Corner/state_machines/withdraw_approved_registration_reattributes_order
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        principal = base["principal"]
        r1, r2 = base["reps"]
        customer = base["customer"]
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project W")
        approve_registration(reg["id"], principal["id"])
        order = create_order(
            customer["id"], principal["id"], "PO-W",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        assert order_line(get_order(order["id"]), "L1")["protected_registration_id"] == reg["id"]

        withdrawn = api.withdraw_registration(reg["id"], make_rep_headers(r1["id"])).json()["data"]
        assert withdrawn["status"] == "WITHDRAWN"

        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        by_role = {row["role"]: row for row in rows}
        assert set(by_role) == {"SPECIFY", "SHIP_TO"}, "REGISTERED share dropped"
        assert by_role["SPECIFY"]["share_bp"] == 6000
        assert by_role["SHIP_TO"]["share_bp"] == 4000
        assert order_line(get_order(order["id"]), "L1")["protected_registration_id"] is None

    def test_rep_on_hold_blocks_registration_submit(self, api):
        """PRD §2.6: "After any entry posts, if a rep's `commission_balance_cents`
        falls below the hold floor of negative 50,000 cents — five hundred dollars in
        the red — the rep transitions from `ACTIVE` to `COMMISSION_HOLD`. While on
        hold, the rep's new project registration submissions, registration
        resubmissions, and sample checkouts are rejected with `ERR_REP_ON_HOLD`. The
        hold is released — the rep returns to `ACTIVE` — when the balance recovers to
        zero or better, re-evaluated after any entry posts and again during each clock
        sweep."

        Design: Corner/validations/rep_on_hold_blocks_registration_submit
        """
        principal = create_principal()
        customer = create_customer(spec_territory_code="NV", ship_to_territory_code="NV")
        rep = create_rep("RH", ["NV"])
        post_adjustment(rep["id"], -60_000, "prior-period clawback")
        assert get_rep(rep["id"])["status"] == "COMMISSION_HOLD"

        resp = api.create_registration(
            {
                "principal_id": principal["id"],
                "customer_id": customer["id"],
                "family_code": "CONNECTORS",
                "project_name": "Project Held",
            },
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REP_ON_HOLD)

        post_adjustment(rep["id"], 60_000, "clawback reversed")
        assert get_rep(rep["id"])["status"] == "ACTIVE", "balance 0 releases the hold"
        reg = submit_registration(principal["id"], customer["id"], rep["id"],
                                  project_name="Project Held")
        assert reg["status"] == "SUBMITTED"
