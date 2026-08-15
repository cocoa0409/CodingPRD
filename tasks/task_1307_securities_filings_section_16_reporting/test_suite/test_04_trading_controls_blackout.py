"""Blackout windows: closed-interval overlap and the confirm-time blackout
guard with its 10b5-1 plan exemption (PRD §2.6, §3.3, §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    make_compliance_officer_headers,
    create_issuer, create_blackout_window, create_active_person,
    set_clock, ingest_transaction, confirm_transaction,
    setup_active_plan,
)


class TestBlackoutWindowOverlap:
    def test_touching_windows_share_a_date_and_conflict(self, api):
        """PRD §3.6: "a `ComplianceOfficer` declares issuer trading blackouts as
        closed-interval windows naming the `issuer_id`, a `start_date`, and an
        `end_date` — both bounds inclusive, with `end_date` no earlier than
        `start_date` — plus an optional `reason`. Two windows of the same issuer
        conflict when they share at least one calendar date, and a conflicting
        creation is rejected with `ERR_BLACKOUT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/blackout_windows_closed_interval_overlap
        """
        issuer = create_issuer()
        create_blackout_window(issuer["id"], "2026-09-28", "2026-10-02",
                               reason="Q3 earnings")
        # Closed interval: [09-28, 10-02] and [10-02, 10-05] share 2026-10-02.
        resp = api.create_blackout_window(
            {"issuer_id": issuer["id"], "start_date": "2026-10-02",
             "end_date": "2026-10-05", "reason": "overlap attempt"},
            make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_WINDOW_OVERLAP)

    def test_adjacent_disjoint_window_accepted(self, api):
        """PRD §3.6: "Two windows of the same issuer conflict when they share
        at least one calendar date, and a conflicting creation is rejected with
        `ERR_BLACKOUT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/blackout_windows_closed_interval_overlap
        """
        issuer = create_issuer()
        create_blackout_window(issuer["id"], "2026-09-28", "2026-10-02",
                               reason="Q3 earnings")
        # Start 2026-10-03 is one day past the existing end: no shared date.
        resp = api.create_blackout_window(
            {"issuer_id": issuer["id"], "start_date": "2026-10-03",
             "end_date": "2026-10-09", "reason": "adjacent but disjoint"},
            make_compliance_officer_headers())
        data = validate_success(resp, 201)
        assert data["id"], "Disjoint window must be created"
        resp = api.list_blackout_windows(
            make_compliance_officer_headers(),
            params={"issuer_id": issuer["id"], "limit": 100})
        listed, meta = validate_paginated(resp)
        assert len(listed) == 2, (
            f"Expected exactly 2 windows for the issuer, got {len(listed)}")


class TestBlackoutPeriodConfirmGuard:
    def test_blackout_period_blocks_nonplan_transaction(self, api):
        """PRD §3.6: "Confirming a transaction that carries no `plan_id` whose
        `transaction_date` lands inside any of the issuer's blackout windows
        fails with `ERR_BLACKOUT_PERIOD` (§3.3)"
        PRD §3.3: "when no `plan_id` is set, the `transaction_date` must not
        fall inside any of the issuer's blackout windows, whose start and end
        dates are both inclusive (`ERR_BLACKOUT_PERIOD`)"

        Design: Corner/validations/blackout_period_blocks_nonplan_transaction
        """
        issuer = create_issuer()
        create_blackout_window(issuer["id"], "2026-08-03", "2026-08-07",
                               reason="earnings")
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-05",
                                 shares=100, price_per_share=10.00)
        set_clock("2026-08-05T09:00:00Z")
        resp = api.confirm_transaction(
            txn["id"], make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_PERIOD)

    def test_blackout_period_allows_plan_affiliated_transaction(self, api):
        """PRD §3.6: "trades executed under a 10b5-1 plan skip the blackout
        check entirely."
        PRD §3.6: "Activation (`ACTIVATE`) moves an `ADOPTED` plan to `ACTIVE`
        once the logical clock date has reached `cooling_off_end_date` —
        equality satisfies the rule"

        Design: Corner/validations/blackout_period_allows_plan_affiliated_transaction
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z",
                                      full_name="Dana Owner",
                                      person_cik="0001000002",
                                      is_ten_pct_owner=True)
        # Pure 10% owner: cooling-off end is adoption_date + 90 calendar days
        # (2026-08-03 + 90 = 2026-11-01); activation on that date satisfies the
        # rule by equality.
        plan = setup_active_plan(
            issuer["id"], person["id"],
            approve_at="2026-08-03T09:00:00Z",
            activate_at="2026-11-01T09:00:00Z",
            first_trade_date="2026-11-01", expiration_date="2027-03-01")
        assert plan["status"] == "ACTIVE", (
            f"Plan must be ACTIVE once cooling-off is satisfied, "
            f"got {plan['status']}")
        create_blackout_window(issuer["id"], "2026-10-28", "2026-11-04",
                               reason="earnings")
        txn = ingest_transaction(person["id"], transaction_date="2026-11-02",
                                 shares=100, price_per_share=10.00,
                                 plan_id=plan["id"])
        set_clock("2026-11-02T09:00:00Z")
        resp = api.confirm_transaction(
            txn["id"], make_compliance_officer_headers("co_1"))
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED", (
            f"Plan-affiliated trade must skip the blackout check, "
            f"got {data['status']}")
