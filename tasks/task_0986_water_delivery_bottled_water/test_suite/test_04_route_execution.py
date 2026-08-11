"""Route execution: deliveries, skips, commitment release, and custody ledger."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    validate_paginated, setup_customer, setup_two_customers, setup_skip_credit,
    deliver_via_work_order, create_route, plan_stop, publish_route, start_route,
    arrive_stop, deliver_arrived_stop, create_skip_payload, set_clock,
    get_route, get_stop, assert_ledger_entry,
    OPS_ADMIN, DISPATCHER, DRIVER, BILLING_ADMIN,
)


def _published_two_stop_route():
    """Route 2026-06-15 with stops planned=3 (customer A) and planned=2 (B)."""
    world = setup_two_customers(
        a_overrides={"service_mode": "AUTO", "par_level_bottles": 3},
        b_overrides={"service_mode": "AUTO", "par_level_bottles": 2},
    )
    zone = world["zone"]
    route = create_route(zone["id"], "2026-06-15")
    stop_a = plan_stop(route["id"], world["customer_a"]["id"], sequence_index=1)
    stop_b = plan_stop(route["id"], world["customer_b"]["id"], sequence_index=2)
    publish_route(route["id"])
    start_route(route["id"], "2026-06-15T08:00:00Z")
    return {"zone": zone, "route": route, "stop_a": stop_a, "stop_b": stop_b,
            **{k: world[k] for k in ("customer_a", "customer_b")}}


class TestCommitmentInvariant:
    def test_commit_deliver_then_skip_releases_all_bottles(self, api):
        """PRD §3.4: "The customer's `bottles_on_site` is then recomputed from
        the ledger (and, for a clean delivery, `deposit_liability_cents` is
        recomputed with it), while the route releases the stop's
        `planned_bottles` from `committed_bottles` and bumps its `version`."
        PRD §3.5: "A skip, like any terminal stop event, releases the stop's
        planned bottles from the route commitment and bumps the route `version`."

        Design: Difficulty/compensating_invariant/route_commit_deliver_then_cancel_invariant
        """
        s = _published_two_stop_route()
        route_id = s["route"]["id"]
        assert get_route(route_id)["committed_bottles"] == 5

        arrive_stop(s["stop_a"]["id"])
        deliver_arrived_stop(s["stop_a"]["id"], route_id, 3, 3)
        after_deliver = get_route(route_id)
        assert after_deliver["committed_bottles"] == 2, (
            f"delivering the planned=3 stop must release 3 bottles (5-3=2), "
            f"got {after_deliver['committed_bottles']}"
        )

        validate_success(
            api.skip_stop(s["stop_b"]["id"],
                          create_skip_payload(skip_reason="not home",
                                              notified_before_cutoff=False),
                          DRIVER),
            200,
        )
        after_skip = get_route(route_id)
        assert after_skip["committed_bottles"] == 0, (
            f"skipping the planned=2 stop must release the remaining bottles, "
            f"got {after_skip['committed_bottles']}"
        )

    def test_route_completes_once_all_stops_terminal(self, api):
        """PRD §3.3: "Completion moves `IN_PROGRESS` to `COMPLETED`, but only
        once every stop on the route has reached a terminal state — `DELIVERED`,
        `PARTIAL`, `SKIPPED`, `FAILED`, or `CANCELLED`; at completion the system
        generates invoice line entries against the next `DRAFT` invoice for each
        `DELIVERED` or `PARTIAL` stop."

        Design: Difficulty/compensating_invariant/route_commit_deliver_then_cancel_invariant
        """
        s = _published_two_stop_route()
        route_id = s["route"]["id"]

        arrive_stop(s["stop_a"]["id"])
        deliver_arrived_stop(s["stop_a"]["id"], route_id, 3, 3)
        validate_success(
            api.skip_stop(s["stop_b"]["id"],
                          create_skip_payload(skip_reason="not home",
                                              notified_before_cutoff=False),
                          DRIVER),
            200,
        )
        completed = validate_success(api.complete_route(route_id, DRIVER), 200)
        assert completed["route_status"] == "COMPLETED"
        assert get_route(route_id)["committed_bottles"] == 0


class TestSkipRules:
    def test_skip_reason_required(self, api):
        """PRD §3.5: "A skip is accepted from `PLANNED`, `EN_ROUTE`, or
        `ARRIVED`, and it always requires a non-empty `skip_reason`; an empty
        explanation is rejected with `ERR_SKIP_REASON_REQUIRED`."

        Design: Corner/validations/skip_reason_required
        """
        world = setup_customer(account_type="OFFICE", business_name="SkipR",
                               billing_email="s@x.example", service_address="1 S",
                               service_mode="AUTO", par_level_bottles=1,
                               pricing_tier="STANDARD")
        route = create_route(world["zone"]["id"], "2026-06-01")
        stop = plan_stop(route["id"], world["customer"]["id"], sequence_index=1)

        res = api.skip_stop(stop["id"],
                            create_skip_payload(skip_reason="",
                                                notified_before_cutoff=True),
                            DRIVER)
        validate_error(res, "ERR_SKIP_REASON_REQUIRED")


class TestSkipCreditExpiryBoundary:
    # Credit created at 2026-05-01T00:00:00Z expires exactly 90 days later
    # (PRD §3.5), i.e. at 2026-07-30T00:00:00Z.
    EXPIRES_AT = "2026-07-30T00:00:00Z"
    JUST_BEFORE = "2026-07-29T23:59:59Z"

    def test_apply_one_second_before_expiry_succeeds(self, api):
        """PRD §3.5: "Applying requires the credit to still be `PENDING` and the
        logical clock to be earlier than `expires_at` — a credit past its expiry
        is rejected with `ERR_CREDIT_EXPIRED`."
        PRD §3.5: "Each credit carries a `stop_id` pointing back at the skipped
        stop, begins life with `credit_status` at `PENDING`, and is stamped with
        an `expires_at` exactly 90 days after creation."

        Design: Difficulty/boundary_precision_check/skip_credit_expires_at_boundary
        """
        s = setup_skip_credit(notified_before_cutoff=True)
        credit = s["skip_credit"]
        assert credit["credit_status"] == "PENDING"

        set_clock(self.JUST_BEFORE)
        applied = validate_success(api.apply_skip_credit(credit["id"], BILLING_ADMIN), 200)
        assert applied["credit_status"] == "APPLIED", (
            f"a credit one second before expires_at must still apply, "
            f"got {applied['credit_status']}"
        )

    def test_apply_at_expiry_is_rejected(self, api):
        """PRD §3.5: "Applying requires the credit to still be `PENDING` and the
        logical clock to be earlier than `expires_at` — a credit past its expiry
        is rejected with `ERR_CREDIT_EXPIRED`."
        PRD §2.4: "Advancing the logical clock fires time-based auto-transitions:
        any `OPEN` invoice whose `due_date` has been passed while its
        `balance_due_cents` remains positive flips to `OVERDUE`, and any
        `PENDING` skip credit whose `expires_at` has been reached flips to
        `EXPIRED`."

        At exactly expires_at the credit is no longer applicable; whether the
        rejection surfaces as the expiry check or as a terminal-state check on
        the auto-expired credit is left open by the contract, so any of the
        three error ids satisfies it.

        Design: Difficulty/boundary_precision_check/skip_credit_expires_at_boundary
        """
        s = setup_skip_credit(notified_before_cutoff=True)
        credit = s["skip_credit"]

        set_clock(self.EXPIRES_AT)
        res = api.apply_skip_credit(credit["id"], BILLING_ADMIN)
        actual = validate_error_is_one_of(
            res, ["ERR_CREDIT_EXPIRED", "ERR_INVALID_STATE", "ERR_ALREADY_TERMINAL"]
        )
        assert res.status_code in (409, 422), \
            f"expected a rejection at expiry, got HTTP {res.status_code} ({actual})"


class TestCustodyLedger:
    def test_bottle_custody_ledger_immutable_no_version(self, api):
        """PRD §2.5: "One resource is deliberately lighter. Entries in the
        bottle custody ledger are immutable once written: a custody entry
        carries `id` and `created_at` only, and both `updated_at` and `version`
        are absent from it."
        PRD §3.4: "Either way the system records the actuals on the stop and
        writes the custody trail: a `DELIVER_FULL` entry crediting the customer
        with the bottles dropped, a `PICKUP_EMPTY` entry removing the empties
        collected, and — for a partial with shortages — a `MARK_SHORTAGE` entry
        for the missing count, which keeps those bottles in the customer's
        custody but flags them as owed."

        Design: Corner/entities/bottle_custody_ledger_immutable_no_version
        """
        world = setup_customer(account_type="OFFICE", business_name="LedgerCo",
                               billing_email="l@x.example", service_address="1 L",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        customer = world["customer"]
        deliver_via_work_order(customer["id"], world["zone"]["id"], "2026-05-10", 1)

        res = api.list_customer_bottle_custody_ledger(customer["id"], OPS_ADMIN)
        data, meta = validate_paginated(res)
        assert len(data) >= 2, "a clean exchange must write at least DELIVER_FULL and PICKUP_EMPTY"
        kinds = {entry["entry_kind"] for entry in data}
        assert "DELIVER_FULL" in kinds and "PICKUP_EMPTY" in kinds
        for entry in data:
            assert_ledger_entry(entry)
