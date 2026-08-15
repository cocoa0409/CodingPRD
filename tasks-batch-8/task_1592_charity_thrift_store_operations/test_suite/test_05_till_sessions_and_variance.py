"""Till sessions: variance branching, the 500/501 boundary, SoD, uniqueness."""
from test_helpers import (
    ApiErrorId,
    MGR,
    approve_variance,
    close_till_session,
    count_session,
    create_floored_item,
    create_sold_item,
    create_worker,
    make_cashier_headers,
    make_finance_clerk_headers,
    make_store_manager_headers,
    open_till_session,
    ring_sale,
    validate_error,
    validate_success,
)


class TestVarianceBranchDivergence:
    def test_till_variance_branch_divergence(self, api):
        """PRD 3.6: "A discrepancy of at most 500 cents in either direction — exactly
        500 over or under included — reconciles immediately, moving the session
        `OPEN` → `RECONCILED`. A discrepancy of 501 cents or more routes the session
        `OPEN` → `PENDING_APPROVAL`, where it waits for a `FinanceClerk` to approve
        the variance. Approval moves `PENDING_APPROVAL` → `RECONCILED`, records
        `variance_approved_by_user_id`, and enforces segregation of duties"

        Design: Difficulty/non_linear_state_machine/till_variance_branch_divergence
        """
        ctx = create_sold_item(base_cents=2500, opening_float_cents=10000)
        session1 = ctx["session"]
        cashier_id = ctx["cashier"]["id"]
        assert ctx["sale"]["total_cents"] == 2000, "2500 x 0.8"

        # +600 over: the pending-approval branch with a FinanceClerk hop.
        counted = count_session(session1["id"], 12600, counter_user_id="mgr-1")
        assert counted["status"] == "PENDING_APPROVAL"
        assert counted["over_short_cents"] == 600
        assert counted.get("counted_by_user_id") == "mgr-1"

        approved = approve_variance(session1["id"], approver_user_id="fin-1")
        assert approved["status"] == "RECONCILED"
        assert approved.get("variance_approved_by_user_id") == "fin-1"

        closed = close_till_session(session1["id"])
        assert closed["status"] == "CLOSED"

        # +500 over on a fresh session: the direct auto-reconcile branch.
        session2 = open_till_session(cashier_id, 10000)
        counted2 = count_session(session2["id"], 10500, counter_user_id="mgr-1")
        assert counted2["status"] == "RECONCILED", "no approval hop inside the band"
        assert counted2["over_short_cents"] == 500
        assert counted2.get("variance_approved_by_user_id") is None

    def test_negative_variance_within_band_auto_reconciles(self, api):
        """PRD 3.6: "A discrepancy of at most 500 cents in either direction — exactly
        500 over or under included — reconciles immediately, moving the session
        `OPEN` → `RECONCILED`. A discrepancy of 501 cents or more routes the session
        `OPEN` → `PENDING_APPROVAL`"

        Design: Difficulty/non_linear_state_machine/till_variance_branch_divergence
        """
        w1 = create_worker("W One", "STAFF")
        w2 = create_worker("W Two", "STAFF")
        s1 = open_till_session(w1["id"], 5000)
        s2 = open_till_session(w2["id"], 5000)

        within = count_session(s1["id"], 4500)  # exactly 500 under
        assert within["status"] == "RECONCILED"
        assert within["over_short_cents"] == -500

        beyond = count_session(s2["id"], 4499)  # 501 under
        assert beyond["status"] == "PENDING_APPROVAL"
        assert beyond["over_short_cents"] == -501


class TestVarianceBoundary:
    def test_variance_boundary_500_vs_501(self, api):
        """PRD 3.6: "A discrepancy of at most 500 cents in either direction — exactly
        500 over or under included — reconciles immediately, moving the session
        `OPEN` → `RECONCILED`. A discrepancy of 501 cents or more routes the session
        `OPEN` → `PENDING_APPROVAL`"

        Design: Difficulty/boundary_precision_check/variance_boundary_500_vs_501
        """
        ctx = create_sold_item(base_cents=2500, opening_float_cents=10000)
        cashier_id = ctx["cashier"]["id"]
        session1 = ctx["session"]
        assert ctx["sale"]["total_cents"] == 2000

        # Expected cash is 12000; +500 sits exactly on the inclusive boundary.
        counted1 = count_session(session1["id"], 12500)
        assert counted1["status"] == "RECONCILED"
        assert counted1["over_short_cents"] == 500
        close_till_session(session1["id"])

        # A second session with the same cashier plus a second 2000-cent sale:
        # +501 crosses the boundary. The item floors into the already-OPEN cycle.
        ctx2 = create_floored_item("CLOTHING", "GOOD", 2500, cycle=ctx["cycle"])
        session2 = open_till_session(cashier_id, 10000)
        ring_sale(session2["id"], cashier_id, [ctx2["item"]["id"]], "CASH")
        counted2 = count_session(session2["id"], 12501)
        assert counted2["status"] == "PENDING_APPROVAL"
        assert counted2["over_short_cents"] == 501

    def test_negative_500_boundary_auto_reconciles(self, api):
        """PRD 3.6: "A discrepancy of at most 500 cents in either direction — exactly
        500 over or under included — reconciles immediately, moving the session
        `OPEN` → `RECONCILED`."

        Design: Difficulty/boundary_precision_check/variance_boundary_500_vs_501
        """
        ctx = create_sold_item(base_cents=2000, opening_float_cents=3000)
        session = ctx["session"]
        assert ctx["sale"]["total_cents"] == 1600
        # Expected cash 4600; counting 4100 is exactly 500 short.
        counted = count_session(session["id"], 4100)
        assert counted["status"] == "RECONCILED"
        assert counted["over_short_cents"] == -500


class TestVarianceSegregationOfDuties:
    def test_sod_counter_cannot_approve_own_variance(self, api):
        """PRD 2.10: "When a count lands outside the auto-reconcile band, the
        `FinanceClerk` approving the variance must not be the manager who entered
        the count — the approver's `X-User-ID` must differ from the session's
        `counted_by_user_id`, or the approval is rejected with
        `ERR_SOD_APPROVER_IS_COUNTER` (HTTP 422)."

        Design: Corner/validations/sod_counter_cannot_approve_own_variance
        """
        ctx = create_sold_item(base_cents=2000, opening_float_cents=10000)
        session = ctx["session"]
        counted = count_session(session["id"], 12200, counter_user_id="mgr-1")
        assert counted["status"] == "PENDING_APPROVAL", "+600 is outside the band"
        assert counted.get("counted_by_user_id") == "mgr-1"

        resp = api.approve_variance(session["id"], make_finance_clerk_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_APPROVER_IS_COUNTER)

        approved = approve_variance(session["id"], approver_user_id="fin-9")
        assert approved["status"] == "RECONCILED"
        assert approved.get("variance_approved_by_user_id") == "fin-9"


class TestSessionUniquenessAndReplay:
    def test_cashier_cannot_open_second_session(self, api):
        """PRD 3.6: "The session's `cashier_worker_id` is taken from the acting
        cashier's `X-User-ID`, never from the payload, and a cashier may hold at most
        one OPEN session — a second open attempt fails with
        `ERR_TILL_SESSION_OPEN_EXISTS`."

        Design: Corner/state_machines/cashier_cannot_open_second_session
        """
        w1 = create_worker("W One", "STAFF")
        w2 = create_worker("W Two", "STAFF")
        open_till_session(w1["id"], 5000)

        resp = api.create_till_session({"opening_float_cents": 5000},
                                       make_cashier_headers(w1["id"]))
        validate_error(resp, ApiErrorId.ERR_TILL_SESSION_OPEN_EXISTS)

        other = open_till_session(w2["id"], 3000)
        assert other["status"] == "OPEN", "uniqueness is per cashier, not global"

    def test_double_count_rejected(self, api):
        """PRD 3.6: "a `StoreManager` enters `counted_cash_cents` against an OPEN
        session — counting a session in any other state fails with
        `ERR_TILL_INVALID_STATE`."

        Design: Corner/state_machines/double_count_rejected
        """
        w1 = create_worker("W Cash", "STAFF")
        session = open_till_session(w1["id"], 7000)
        counted = count_session(session["id"], 7000)
        assert counted["status"] == "RECONCILED"

        resp = api.count_till_session(session["id"], {"counted_cash_cents": 7000},
                                      make_store_manager_headers("mgr-counter-1"))
        validate_error(resp, ApiErrorId.ERR_TILL_INVALID_STATE)
        after = validate_success(api.get_till_session(session["id"], MGR))
        assert after["status"] == "RECONCILED"
