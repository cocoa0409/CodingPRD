"""Missed-pickup credit amounts (base + repeat escalation) and contamination fees
(free-first-warning + MAJOR doubling). Covers difficulty rule
boundary_precision_check (missed-credit repeat threshold) and the calculations
corner instances.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_active_account, set_clock,
    setup_account_with_n_contamination_notices,
)

DISP = TEST_USERS["dispatcher_headers"]
CREW = TEST_USERS["crew_lead_headers"]


def _report_missed(api, schedule):
    return get_success_data(api.report_event(
        schedule["id"], {"outcome": "MISSED", "reported_at": schedule["effective_pickup_date"]}, CREW))


class TestMissedCreditRepeatThreshold:
    def test_fourth_miss_escalates_to_450(self, api):
        """PRD §3.8: "If that count of prior misses is strictly greater than 2, the
        household is a repeat victim and an extra 150 cents is added to the base credit;
        otherwise the credit is exactly the base."
        PRD §3.8: "The base credit is 300 cents for a missed TRASH pickup."

        Design: Difficulty/boundary_precision_check/missed_credit_repeat_threshold_strictly_greater_than_two
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="28 Oak St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        assert len(rows) >= 4, "need four TRASH schedules in the 28-day horizon"
        # Advance the clock to the fourth pickup's effective date so all four
        # reported_at instants land within the rolling 90-day window the PRD
        # bounds at "the current clock instant" (PRD §3.8). Reporting at the
        # earlier clock would leave the later pickups' reported_at > clock and
        # thus outside the window, never accumulating prior misses.
        set_clock(rows[3]["effective_pickup_date"])
        # first three misses: prior_misses 0,1,2 -> all base 300
        for i in range(3):
            _report_missed(api, rows[i])
        # fourth miss: prior_misses == 3 (> 2) -> 300 + 150 = 450
        ev4 = _report_missed(api, rows[3])
        credits = get_success_data(api.list_credits(DISP, {"pickup_event_id": ev4["id"]}))
        assert credits[0]["amount_cents"] == 450

    def test_third_miss_still_base_300(self, api):
        """PRD §3.8: "If that count of prior misses is strictly greater than 2 ...
        otherwise the credit is exactly the base."
        PRD §3.8: "The base credit is 300 cents for a missed TRASH pickup."

        Design: Difficulty/boundary_precision_check/missed_credit_repeat_threshold_strictly_greater_than_two
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="29 Oak St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        assert len(rows) >= 3
        for i in range(2):
            _report_missed(api, rows[i])
        # third miss: prior_misses == 2 (not > 2) -> base 300
        ev3 = _report_missed(api, rows[2])
        credits = get_success_data(api.list_credits(DISP, {"pickup_event_id": ev3["id"]}))
        assert credits[0]["amount_cents"] == 300


class TestMissedRecyclingBaseCredit:
    def test_first_missed_recycling_credit_is_200(self, api):
        """PRD §3.8: "and 200 cents for a missed RECYCLING pickup."

        Design: Corner/calculations/missed_recycling_credit_base_two_hundred
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="70 Oak St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "RECYCLING"}))
        assert rows, "need at least one RECYCLING schedule"
        ev = _report_missed(api, rows[0])
        credits = get_success_data(api.list_credits(DISP, {"pickup_event_id": ev["id"]}))
        assert credits[0]["amount_cents"] == 200


class TestContaminationFee:
    def test_first_notice_is_free_warning(self, api):
        """PRD §3.9: "If that prior count is zero — this is the account's first
        contamination notice ever — the fee is 0 cents, a free warning."

        Design: Corner/calculations/contamination_first_notice_is_free_warning
        """
        s = setup_account_with_n_contamination_notices(1, last_severity="MINOR", address="66 Oak St")
        notice = s["notices"][0]
        assert notice["fee_cents"] == 0
        assert notice["status"] == "OPEN"

    def test_second_major_notice_fee_doubled_to_3000(self, api):
        """PRD §3.9: "Otherwise the fee is 1500 cents for a MINOR notice, and for a MAJOR
        notice it is 1500 cents multiplied by 2, i.e. 3000 cents."

        Design: Corner/calculations/contamination_second_major_fee_doubled
        """
        s = setup_account_with_n_contamination_notices(2, last_severity="MAJOR", address="68 Oak St")
        second = s["notices"][1]
        assert second["fee_cents"] == 3000
