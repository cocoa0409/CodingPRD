"""Derived-field reconciliation and review-driven cascade side effects."""
from test_helpers import (
    get_success_data,
    create_client,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestOpenCloseCountReconciliation:
    def test_open_close_count_returns_to_zero_after_finalize(self, api):
        """PRD §2.5: "Its `open_close_count` is the number of `MonthlyClose` rows for
        the client whose status is anything other than `FINALIZED`, and it is
        reconciled on every monthly-close mutation — incremented when a close is
        opened and decremented when one is finalized."

        Design: Corner/cross_cutting_complexity_layers/derived_open_close_count_reconciled_on_finalize
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 3, "txn_count": 10}, BK))
        after_open = get_success_data(api.get_client(cid, CFO))
        assert after_open["open_close_count"] == 1
        task = get_success_data(api.create_close_task(
            close["id"], {"name": "Reconcile", "weight": 1}, BK))
        get_success_data(api.transition_close_task(task["id"], {"to_status": "DONE"}, BK))
        get_success_data(api.approve_review(close["id"], CFO))
        finalized = get_success_data(api.finalize_close(close["id"], CFO))
        assert finalized["status"] == "FINALIZED"
        after_final = get_success_data(api.get_client(cid, CFO))
        assert after_final["open_close_count"] == 0


class TestRequestChangesCascade:
    def test_request_changes_reopens_named_task_and_drops_completion(self, api):
        """PRD §3.4: "The close moves `READY_FOR_REVIEW → REOPENED`, its
        `review_status` becomes `CHANGES_REQUESTED`, every `DONE` task whose `name`
        appears in `changed_task_names` is reset to `PENDING`, and the two completion
        percentages are recomputed."

        Design: Corner/cross_cutting_complexity_layers/request_changes_reopens_named_done_task
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 4, "txn_count": 10}, BK))
        t1 = get_success_data(api.create_close_task(
            close["id"], {"name": "Reconcile", "weight": 1}, BK))
        t2 = get_success_data(api.create_close_task(
            close["id"], {"name": "Review", "weight": 1}, BK))
        get_success_data(api.transition_close_task(t1["id"], {"to_status": "DONE"}, BK))
        get_success_data(api.transition_close_task(t2["id"], {"to_status": "DONE"}, BK))
        reopened = get_success_data(api.request_changes(
            close["id"], {"changed_task_names": ["Reconcile"]}, CFO))
        assert reopened["status"] == "REOPENED"
        assert reopened["review_status"] == "CHANGES_REQUESTED"
        assert reopened["completion_pct"] == 50.00
