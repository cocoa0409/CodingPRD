"""Line termination, tail invoicing, clock monotonicity, cascades (PRD §3.9, §2.5).

Covers notice issuance and rescission, the inclusive tail-invoicing window, the
strictly-monotonic logical clock, and the depth-4 termination sweep cascade.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    approve_registration,
    create_order,
    create_principal,
    get_agreement,
    get_order,
    get_principal,
    get_registration,
    invoice_order,
    list_splits,
    make_order_line,
    make_principal_ops_headers,
    order_line,
    parse_instant,
    set_clock,
    setup_base_scenario,
    ship_order,
    splits_for_line,
    submit_registration,
    validate_error,
    TEST_USERS,
)


def _admin():
    return TEST_USERS["agency_admin_headers"]


class TestClockMonotonicity:
    def test_clock_regression_rejected(self, api, agency_admin_headers):
        """PRD §2.5: "The supplied instant must be strictly later than the current
        reading; an attempt to move the clock to an instant at or before the current
        reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409)."

        Design: Corner/validations/clock_regression_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        backward = api.set_clock("2026-08-15T00:00:00Z", agency_admin_headers)
        validate_error(backward, ApiErrorId.ERR_CLOCK_REGRESSION)
        equal = api.set_clock("2026-09-01T00:00:00Z", agency_admin_headers)
        validate_error(equal, ApiErrorId.ERR_CLOCK_REGRESSION)


class TestTerminationNotice:
    def test_rescind_notice_reverts_principal(self, api):
        """PRD §3.9: "The notice stamps `termination_notice_issued_at` with the
        current clock and computes `termination_effective_at` as the notice time plus
        the principal's `notice_period_days`". and "A successful rescission returns
        the principal from `NOTICE_PENDING` to `ACTIVE`, clears both termination
        timestamps back to null, and increments the principal's `version`."

        Design: Corner/state_machines/rescind_notice_reverts_principal
        """
        principal = create_principal()
        noticed = api.issue_termination_notice(
            principal["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        assert noticed["status"] == "NOTICE_PENDING"
        assert parse_instant(noticed["termination_effective_at"]) == datetime(
            2026, 10, 30, tzinfo=timezone.utc,
        ), "default clock 2026-08-01 + 90-day notice period"
        assert parse_instant(noticed["termination_notice_issued_at"]) == parse_instant(
            "2026-08-01T00:00:00Z",
        )

        rescinded = api.rescind_termination_notice(
            principal["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        assert rescinded["status"] == "ACTIVE"
        assert rescinded["termination_notice_issued_at"] is None
        assert rescinded["termination_effective_at"] is None


class TestTailInvoicing:
    def test_tail_period_invoice_window_boundary(self, api):
        """PRD §3.5: "One temporal gate applies up front when the principal has been
        terminated: the order's `placed_at` must be strictly earlier than the
        principal's `termination_effective_at`, and the current clock must be no later
        than `termination_effective_at` plus the agreement's `tail_period_days` — the
        tail boundary is inclusive. An invoice attempt outside that window fails with
        `ERR_TAIL_PERIOD_EXPIRED`."

        Design: Corner/validations/tail_period_invoice_window_boundary
        """
        base = setup_base_scenario(
            agreement_territories=["CA", "OR", "WA"], reps=(("R1", ["CA", "OR", "WA"]),),
        )
        principal = base["principal"]
        customer = base["customer"]
        set_clock("2026-08-10T00:00:00Z")
        orders = [
            create_order(
                customer["id"], principal["id"], ref, placed_at="2026-08-10T00:00:00Z",
                lines=[make_order_line(quantity=1, unit_price_cents=5000)],
            )
            for ref in ("PO-T1", "PO-T2", "PO-T3")
        ]
        for o in orders:
            ship_order(o["id"], principal["id"])

        noticed = api.issue_termination_notice(
            principal["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        # Notice at 2026-08-10 + 90 days; tail end is effective + 180 days.
        assert parse_instant(noticed["termination_effective_at"]) == datetime(
            2026, 11, 8, tzinfo=timezone.utc,
        )

        set_clock("2026-12-01T00:00:00Z")  # past the effective instant, inside tail
        t1 = invoice_order(orders[0]["id"], principal["id"])
        assert t1["fulfillment_status"] == "INVOICED"

        set_clock("2027-05-07T00:00:00Z")  # exactly the inclusive tail end
        t2 = invoice_order(orders[1]["id"], principal["id"])
        assert t2["fulfillment_status"] == "INVOICED"

        set_clock("2027-05-08T00:00:00Z")  # one day past the tail
        resp = api.invoice_order(
            orders[2]["id"], make_principal_ops_headers(principal["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TAIL_PERIOD_EXPIRED)


class TestTerminationSweepCascade:
    def _setup_termination_scenario(self, api):
        """BASE with an APPROVED registration and a protected PLACED order, notice
        issued at 2026-08-15 (effective 2026-11-13)."""
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        set_clock("2026-08-15T00:00:00Z")
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project Term")
        approve_registration(reg["id"], principal["id"])
        order = create_order(
            customer["id"], principal["id"], "PO-T", placed_at="2026-08-15T00:00:00Z",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        # The order is protected: a single REGISTERED row for the registering rep.
        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        assert len(rows) == 1 and rows[0]["role"] == "REGISTERED"

        noticed = api.issue_termination_notice(
            principal["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        assert parse_instant(noticed["termination_effective_at"]) == datetime(
            2026, 11, 13, tzinfo=timezone.utc,
        ), "notice 2026-08-15 + 90 days"
        set_clock("2026-11-13T00:00:00Z")  # the sweep fires at the effective instant
        return base, reg, order

    def test_termination_sweep_terminates_principal_and_agreement(self, api):
        """PRD §3.9: "When the clock reaches `termination_effective_at`, the sweep
        terminates the line. The principal moves from `NOTICE_PENDING` to its terminal
        `TERMINATED` state, and the cascade runs in three links. First, every
        territory agreement of the principal that is `ACTIVE` or `SUSPENDED` moves to
        `TERMINATED`."

        Design: Difficulty/transitive_cascade/termination_effective_sweep_cascade
        """
        base, reg, order = self._setup_termination_scenario(api)
        assert get_principal(base["principal"]["id"])["status"] == "TERMINATED"
        assert get_agreement(base["agreement"]["id"])["status"] == "TERMINATED"

    def test_termination_sweep_expires_registration_and_reattributes(self, api):
        """PRD §3.9: "Second, each terminated agreement expires every `APPROVED`
        project registration on that principal, moving it to `EXPIRED`. Third, each
        expired registration triggers the re-attribution of §3.3 on the principal's
        uninvoiced orders: non-override split rows on orders still `PLACED` or
        `SHIPPED` have their `REGISTERED` share dropped, precedence is re-resolved,
        and the affected lines' `protected_registration_id` is cleared."

        Design: Difficulty/transitive_cascade/termination_effective_sweep_cascade
        """
        base, reg, order = self._setup_termination_scenario(api)
        r1, r2 = base["reps"]
        assert get_registration(reg["id"])["status"] == "EXPIRED"

        after = get_order(order["id"])
        assert after["fulfillment_status"] == "PLACED", (
            "re-attribution does not touch the fulfillment dimension"
        )
        assert order_line(after, "L1")["protected_registration_id"] is None
        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        by_role = {row["role"]: row for row in rows}
        assert set(by_role) == {"SPECIFY", "SHIP_TO"}
        assert by_role["SPECIFY"]["rep_id"] == r1["id"]
        assert by_role["SPECIFY"]["share_bp"] == 6000
        assert by_role["SHIP_TO"]["rep_id"] == r2["id"]
        assert by_role["SHIP_TO"]["share_bp"] == 4000
