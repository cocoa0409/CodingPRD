"""Structuring detection and alert lifecycle (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    alert_in_status,
    create_manual_alert,
    get_single_ctr_for_customer,
    get_success_data,
    list_ctrs_for_customer,
    make_analyst_headers,
    make_officer_headers,
    post_cash_txn,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_error,
)


def _list_alerts(customer_id: str):
    resp = api_client.list_structuring_alerts(
        headers=make_officer_headers(), params={"customer_id": customer_id},
    )
    body = resp.json()
    return body["data"], body["meta"]


class TestStructuringScoreCombinatorial:
    def test_structuring_score_combinatorial_weighted(self, api):
        """PRD §3.7: "Its `risk_score` starts at a base of 40, adds 8 points per
        distinct branch counting at most 4 branches, adds 6 points per distinct
        day counting at most 5 days, adds 15 points when the largest single-day
        total falls in the near-threshold band of at least 900000 cents and at
        most 1000000 cents, adds 10 points per prior referral counting at most
        3 prior referrals where the prior count is the customer's
        `structuring_referral_count` as it stood before this alert, and is
        capped at a maximum of 100."
        PRD §3.7: "Either the contributing records span at least two distinct
        branches, or at least three days in the window have a cash-in total
        greater than zero."

        Fixture: 2 branches, 3 days, max day 950000 in [900000, 1000000],
        0 priors -> score = 40 + 8*2 + 6*3 + 15*1 + 10*0 = 89.

        Design: Difficulty/combinatorial_formula/structuring_score_combinatorial_weighted
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        br2 = create_branch(name="West", branch_code="BR2")
        c1 = create_customer(legal_name="Eve Person", tin="44-4444444")
        # First two deposits cross the window sum but fail condition (4)
        post_cash_txn(c1["id"], br1["id"], amount_cents=950_000,
                      occurred_at="2026-07-28T10:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=100_000,
                      occurred_at="2026-07-29T10:00:00Z")
        _, pre_meta = _list_alerts(c1["id"])
        assert pre_meta["total_count"] == 0
        # Third deposit on a second branch satisfies condition (4) and fires
        post_cash_txn(c1["id"], br2["id"], amount_cents=100_000,
                      occurred_at="2026-08-01T08:00:00Z")
        data, meta = _list_alerts(c1["id"])
        assert meta["total_count"] == 1
        alert = data[0]
        assert alert["status"] == "OPEN"
        assert alert["window_start_date"] == "2026-07-28"
        assert alert["window_end_date"] == "2026-08-01"
        assert alert["detected_amount_cents"] == 1_150_000
        assert alert["risk_score"] == 89

    def test_structuring_score_no_near_threshold_band(self, api):
        """PRD §3.7: "Its `risk_score` starts at a base of 40, adds 8 points per
        distinct branch counting at most 4 branches, adds 6 points per distinct
        day counting at most 5 days, adds 15 points when the largest single-day
        total falls in the near-threshold band of at least 900000 cents and at
        most 1000000 cents".

        Independent confirmation with max day below the near-threshold band
        (score = 40 + 8*2 + 6*3 + 15*0 + 10*0 = 74).

        Design: Difficulty/combinatorial_formula/structuring_score_combinatorial_weighted
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        br2 = create_branch(name="West", branch_code="BR2")
        c1 = create_customer(legal_name="No Band Nancy", tin="44-4444445")
        # max day 400000 (below the [900000, 1000000] band); 2 branches; 3 days
        post_cash_txn(c1["id"], br1["id"], amount_cents=400_000,
                      occurred_at="2026-07-28T10:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=350_000,
                      occurred_at="2026-07-29T10:00:00Z")
        post_cash_txn(c1["id"], br2["id"], amount_cents=350_000,
                      occurred_at="2026-08-01T08:00:00Z")
        data, meta = _list_alerts(c1["id"])
        assert meta["total_count"] == 1
        # 40 + 8*2 + 6*3 + 15*0 + 10*0 = 74
        assert data[0]["risk_score"] == 74


class TestStructuringDetectionConditions:
    def test_structuring_not_fired_when_single_day_reportable(self, api):
        """PRD §3.7: "The largest single-day total in the window is at most
        1000000 cents—no single reportable day, since the CTR machinery already
        covers that case."

        Design: Corner/calculations/structuring_not_fired_when_single_day_reportable
        """
        branch, customer = setup_branch_and_customer()
        post_cash_txn(customer["id"], branch["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:00:00Z")
        _, alert_meta = _list_alerts(customer["id"])
        assert alert_meta["total_count"] == 0
        _, ctr_meta = list_ctrs_for_customer(customer["id"])
        assert ctr_meta["total_count"] == 1

    def test_structuring_window_sum_exactly_at_threshold_no_fire(self, api):
        """PRD §3.7: "The sum of the daily cash-in totals across the window is
        strictly greater than 1000000 cents."

        Design: Corner/calculations/structuring_window_sum_exactly_at_threshold_no_fire
        """
        branch, customer = setup_branch_and_customer()
        for d in ("2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-01"):
            occurred = f"{d}T10:00:00Z" if d != "2026-08-01" else "2026-08-01T08:00:00Z"
            post_cash_txn(customer["id"], branch["id"], amount_cents=200_000,
                          occurred_at=occurred)
        _, meta = _list_alerts(customer["id"])
        assert meta["total_count"] == 0
        _, ctr_meta = list_ctrs_for_customer(customer["id"])
        assert ctr_meta["total_count"] == 0

    def test_structuring_dedup_overlapping_window_silent_skip(self, api):
        """PRD §3.7: "No existing alert for the customer in `OPEN` or
        `UNDER_REVIEW` has a window overlapping the new window under
        closed-interval semantics—two windows sharing at least one date
        conflict, while windows that touch without sharing a date do not. When
        this condition fails, detection is silently deduplicated and no new
        alert row is created."

        Design: Corner/calculations/structuring_dedup_overlapping_window_silent_skip
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        br2 = create_branch(name="West", branch_code="BR2")
        c1 = create_customer(legal_name="Dedup Deb", tin="12-1212120")
        post_cash_txn(c1["id"], br1["id"], amount_cents=950_000,
                      occurred_at="2026-07-28T10:00:00Z")
        post_cash_txn(c1["id"], br1["id"], amount_cents=100_000,
                      occurred_at="2026-07-29T10:00:00Z")
        post_cash_txn(c1["id"], br2["id"], amount_cents=100_000,
                      occurred_at="2026-07-30T10:00:00Z")
        # Fourth deposit has its own 5-day window [07-27, 07-31] which satisfies
        # all firing conditions BUT overlaps the existing OPEN alert's window
        # [07-26, 07-30] -> silently deduplicated.
        post_cash_txn(c1["id"], br1["id"], amount_cents=100_000,
                      occurred_at="2026-07-31T10:00:00Z")
        data, meta = _list_alerts(c1["id"])
        assert meta["total_count"] == 1
        assert data[0]["window_start_date"] == "2026-07-26"
        assert data[0]["window_end_date"] == "2026-07-30"


class TestManualAlertWindowOverlap:
    def test_manual_alert_window_closed_interval_overlap(self, api):
        """PRD §3.7: "it must not overlap, under the same closed-interval date
        semantics, an existing alert in `OPEN` or `UNDER_REVIEW` for the same
        customer (`ERR_ALERT_WINDOW_OVERLAP`)."
        PRD §3.7: "two windows sharing at least one date conflict, while windows
        that touch without sharing a date do not."

        Design: Difficulty/resource_temporal_overlap/manual_alert_window_closed_interval_overlap
        """
        branch, customer = setup_branch_and_customer()
        create_manual_alert(
            customer["id"], creator_id="officer-z",
            window_start_date="2026-08-01", window_end_date="2026-08-05", note="tip-1",
        )
        # Sharing the date 2026-08-05 conflicts under closed semantics
        resp = api_client.create_structuring_alert(
            {
                "customer_id": customer["id"],
                "window_start_date": "2026-08-05",
                "window_end_date": "2026-08-09",
                "note": "tip-2",
            },
            headers=make_officer_headers("officer-z"),
        )
        validate_error(resp, ApiErrorId.ERR_ALERT_WINDOW_OVERLAP)
        # Strictly disjoint successor window succeeds
        ok = get_success_data(api_client.create_structuring_alert(
            {
                "customer_id": customer["id"],
                "window_start_date": "2026-08-06",
                "window_end_date": "2026-08-10",
                "note": "tip-3",
            },
            headers=make_officer_headers("officer-z"),
        ))
        assert ok["id"]
        _, meta = _list_alerts(customer["id"])
        assert meta["total_count"] == 2

    def test_manual_alert_window_shared_interior_date_rejected(self, api):
        """PRD §3.7: "two windows sharing at least one date conflict, while
        windows that touch without sharing a date do not."

        Independent confirmation with a shared interior date (not just an edge).

        Design: Difficulty/resource_temporal_overlap/manual_alert_window_closed_interval_overlap
        """
        branch, customer = setup_branch_and_customer()
        create_manual_alert(
            customer["id"], creator_id="officer-z",
            window_start_date="2026-08-01", window_end_date="2026-08-05", note="tip-1",
        )
        resp = api_client.create_structuring_alert(
            {
                "customer_id": customer["id"],
                "window_start_date": "2026-08-03",
                "window_end_date": "2026-08-07",
                "note": "tip-overlap",
            },
            headers=make_officer_headers("officer-z"),
        )
        validate_error(resp, ApiErrorId.ERR_ALERT_WINDOW_OVERLAP)


class TestStructuringAlertLifecycle:
    def test_alert_referred_terminal_lockdown(self, api):
        """PRD §3.7: "referral moves `UNDER_REVIEW → REFERRED` (the terminal
        state), stamps `referred_at` with the current logical time, stores the
        supplied `referral_note` as the `note`, and increments the customer's
        `structuring_referral_count` by one."
        PRD §2.10 step 6: "the requested action is a valid transition from the
        record's current status (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/alert_referred_terminal_lockdown
        """
        branch, customer = setup_branch_and_customer()
        alert_in_status(customer["id"], "REFERRED", creator_id="officer-z",
                        window_start_date="2026-07-27", window_end_date="2026-07-31",
                        disposition_note="pattern confirmed")
        alerts, _ = _list_alerts(customer["id"])
        alert_id = alerts[0]["id"]
        r1 = api_client.dismiss_alert(
            alert_id, {"disposition_note": "no"}, headers=make_officer_headers("officer-z"),
        )
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        r2 = api_client.reopen_alert(
            alert_id, {"note": "no"}, headers=make_officer_headers("officer-z"),
        )
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        cust = get_success_data(api_client.get_customer(customer["id"], headers=make_officer_headers()))
        assert cust["structuring_referral_count"] == 1

    def test_alert_dismiss_reopen_cycle(self, api):
        """PRD §3.7: "A `DISMISSED` alert may be returned to active work by a
        `BSAOfficer`, moving `DISMISSED → UNDER_REVIEW` and replacing the `note`
        with the supplied input `note`."

        Design: Corner/state_machines/alert_dismiss_reopen_cycle
        """
        branch, customer = setup_branch_and_customer()
        alert_in_status(customer["id"], "DISMISSED", creator_id="officer-z",
                        window_start_date="2026-07-27", window_end_date="2026-07-31",
                        disposition_note="benign")
        alerts, _ = _list_alerts(customer["id"])
        alert_id = alerts[0]["id"]
        reopened = get_success_data(api_client.reopen_alert(
            alert_id, {"note": "new information received"},
            headers=make_officer_headers("officer-z"),
        ))
        assert reopened["status"] == "UNDER_REVIEW"
        assert reopened["note"] == "new information received"
