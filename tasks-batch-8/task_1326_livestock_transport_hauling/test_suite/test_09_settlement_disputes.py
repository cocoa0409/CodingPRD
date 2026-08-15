"""Weight disputes, counters, and payment (PRD §3.8).

Covers the PENDING -> DISPUTED -> COUNTERED -> DISPUTED -> COUNTERED ->
RESOLVED negotiation loop, the inclusive dispute window vs strict pay window,
the money identity across round-trips, and the payment gates.
"""
from test_helpers import (
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    close_incident,
    counter,
    dispute,
    report_incident,
    set_clock,
    setup_delivered_load,
    start_review,
)

ADMIN = TEST_USERS["admin_headers"]
CONSIGNEE = TEST_USERS["consignee_headers"]


class TestNegotiationCycle:
    def test_negotiation_cycle_resolves_at_countered_weight(self, api):
        """PRD §3.8: "Accepting the counter — also a `ConsigneeAgent` action —
        moves `COUNTERED → RESOLVED` (any other state fails with
        `ERR_SETTLEMENT_NOT_COUNTERED`): `dispute_adjustment_cents` is set to
        the shrink penalty as computed at delivery on the delivered-weight
        basis minus the shrink penalty recomputed on the countered-weight
        basis, `effective_delivered_weight_lb` becomes `counter_weight_lb`, the
        shrink fields and `final_amount_cents` are recomputed, and the
        settlement `version` increments."
        PRD §3.8: "Countering — a `Dispatcher` action — moves `DISPUTED →
        COUNTERED`; countering is also legal from `COUNTERED`, where the new
        counter supersedes the previous one (from any state other than
        `DISPUTED` or `COUNTERED` the attempt fails with
        `ERR_SETTLEMENT_NOT_DISPUTED`)."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_counter_negotiation_cycle
        """
        # delivered at net 38800: allowance 800, shrink 1200, excess 400,
        # penalty 1000, final 149000; deadline 2026-08-04T16:30:00Z
        ctx = setup_delivered_load(net_lb=38800)
        s_id = ctx["settlement"]["id"]

        set_clock("2026-08-03T10:00:00Z")
        # PENDING -> DISPUTED
        dispute(s_id, 37000)
        # DISPUTED -> COUNTERED
        counter(s_id, 38500)
        # COUNTERED -> DISPUTED (redispute)
        validate_success(api.redispute_settlement(s_id, {}, CONSIGNEE), 200)
        # COUNTERED loop again: the second counter supersedes the first
        counter(s_id, 39000)
        # COUNTERED -> RESOLVED on the countered weight
        resolved = validate_success(api.accept_counter(s_id, CONSIGNEE), 200)

        assert resolved["status"] == "RESOLVED"
        assert resolved["effective_delivered_weight_lb"] == 39000
        # shrink 1000, allowance 800 -> excess 200 -> penalty 500
        assert resolved["shrink_lb"] == 1000
        assert resolved["excess_shrink_lb"] == 200
        assert resolved["shrink_penalty_cents"] == 500
        # penalty at delivery basis (1000) minus penalty at counter basis (500)
        assert resolved["dispute_adjustment_cents"] == 500
        assert resolved["final_amount_cents"] == 149500

    def test_full_negotiation_cycle_state_transitions(self, api):
        """PRD §3.8: "Re-disputing — a `ConsigneeAgent` action — moves
        `COUNTERED → DISPUTED` (any other state fails with
        `ERR_SETTLEMENT_NOT_COUNTERED`, HTTP 409) and is allowed only while the
        current time is still at or before `dispute_deadline_at`
        (`ERR_DISPUTE_WINDOW_CLOSED`); it records `disputed_weight_lb` when one
        is provided and increments the settlement `version`."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_counter_negotiation_cycle
        """
        ctx = setup_delivered_load(net_lb=38800)
        s_id = ctx["settlement"]["id"]

        set_clock("2026-08-03T10:00:00Z")
        d = dispute(s_id, 37000)
        assert d["status"] == "DISPUTED"
        assert d["disputed_weight_lb"] == 37000

        c1 = counter(s_id, 38500)
        assert c1["status"] == "COUNTERED"
        assert c1["counter_weight_lb"] == 38500

        r = validate_success(api.redispute_settlement(s_id, {}, CONSIGNEE), 200)
        assert r["status"] == "DISPUTED"

        c2 = counter(s_id, 39000)
        assert c2["status"] == "COUNTERED"
        assert c2["counter_weight_lb"] == 39000

        resolved = validate_success(api.accept_counter(s_id, CONSIGNEE), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["final_amount_cents"] == 149500


class TestDisputeRoundtripIdentity:
    def test_dispute_roundtrip_preserves_money_identity(self, api):
        """PRD §3.6: "A money identity holds after every mutation: the final
        amount always equals the provisional amount less the shrink penalty
        less the welfare deduction, so a dispute round-trip whose countered
        weight equals the delivered weight reproduces the pre-dispute final
        exactly."

        Design: Difficulty/compensating_invariant/settlement_dispute_roundtrip_preserves_money_identity
        """
        ctx = setup_delivered_load(net_lb=38800)
        s_id = ctx["settlement"]["id"]
        assert ctx["settlement"]["final_amount_cents"] == 149000

        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 37000)
        # counter at exactly the scale-ticket weight, then accept it
        counter(s_id, 38800)
        resolved = validate_success(api.accept_counter(s_id, CONSIGNEE), 200)

        assert resolved["status"] == "RESOLVED"
        assert resolved["final_amount_cents"] == 149000
        assert resolved["provisional_amount_cents"] == 150000
        assert resolved["shrink_penalty_cents"] == 1000
        assert resolved["welfare_deduction_cents"] == 0
        assert resolved["dispute_adjustment_cents"] == 0
        # identity: final == provisional - shrink penalty - welfare deduction
        assert resolved["final_amount_cents"] == (
            resolved["provisional_amount_cents"]
            - resolved["shrink_penalty_cents"]
            - resolved["welfare_deduction_cents"])

    def test_dispute_roundtrip_leaves_weight_basis_unchanged(self, api):
        """PRD §3.8: "Accepting the counter — also a `ConsigneeAgent` action —
        moves `COUNTERED → RESOLVED` (any other state fails with
        `ERR_SETTLEMENT_NOT_COUNTERED`): `dispute_adjustment_cents` is set to
        the shrink penalty as computed at delivery on the delivered-weight
        basis minus the shrink penalty recomputed on the countered-weight
        basis, `effective_delivered_weight_lb` becomes `counter_weight_lb`, the
        shrink fields and `final_amount_cents` are recomputed, and the
        settlement `version` increments."
        PRD §3.6: "A money identity holds after every mutation: the final
        amount always equals the provisional amount less the shrink penalty
        less the welfare deduction, so a dispute round-trip whose countered
        weight equals the delivered weight reproduces the pre-dispute final
        exactly."

        Design: Difficulty/compensating_invariant/settlement_dispute_roundtrip_preserves_money_identity
        """
        ctx = setup_delivered_load(net_lb=38800)
        s_id = ctx["settlement"]["id"]

        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 37000)
        counter(s_id, 38800)
        resolved = validate_success(api.accept_counter(s_id, CONSIGNEE), 200)

        # countered weight equals the delivered weight: the effective basis
        # stays 38800, so the shrink fields are the pre-dispute ones
        assert resolved["effective_delivered_weight_lb"] == 38800
        assert resolved["shrink_lb"] == 1200
        assert resolved["excess_shrink_lb"] == 400
        assert resolved["final_amount_cents"] == 149000


class TestPayRejectionPriority:
    def test_pay_rejection_prioritizes_open_incident_over_dispute_window(
            self, api):
        """PRD §3.8: "After the state check, payment is blocked while any
        welfare incident of severity `CRITICAL` on this load remains open in
        `REPORTED` or `UNDER_REVIEW` (`ERR_OPEN_CRITICAL_INCIDENT`, HTTP 422).
        Finally, paying directly from `PENDING` — without any dispute —
        additionally requires the dispute window to have run out: the current
        time must be strictly later than `dispute_deadline_at`, or the attempt
        fails with `ERR_DISPUTE_WINDOW_OPEN` (HTTP 422); a `RESOLVED`
        settlement carries no such waiting requirement."

        Design: Difficulty/priority_pair_validation_conflict/pay_rejection_prioritizes_open_incident_over_dispute_window
        """
        # PENDING settlement, deadline 2026-08-04T16:30:00Z; clock is inside
        # the dispute window AND a CRITICAL incident is UNDER_REVIEW — both
        # violations are live, and the incident safety check is narrated first
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        set_clock("2026-08-03T10:00:00Z")
        incident = report_incident(
            ctx["load"]["id"], ctx["driver"]["id"], incident_type="DOWNER",
            severity="CRITICAL", head_count_affected=1,
            occurred_at="2026-08-02T09:00:00Z")
        start_review(incident["id"])

        resp = api.pay_settlement(s_id, ADMIN)
        validate_error(resp, E.ERR_OPEN_CRITICAL_INCIDENT)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "PENDING"
        assert s["paid_at"] is None

    def test_open_reported_critical_incident_also_blocks_pay_inside_window(
            self, api):
        """PRD §3.8: "After the state check, payment is blocked while any
        welfare incident of severity `CRITICAL` on this load remains open in
        `REPORTED` or `UNDER_REVIEW` (`ERR_OPEN_CRITICAL_INCIDENT`, HTTP 422)."
        PRD §3.8: "Finally, paying directly from `PENDING` — without any
        dispute — additionally requires the dispute window to have run out: the
        current time must be strictly later than `dispute_deadline_at`, or the
        attempt fails with `ERR_DISPUTE_WINDOW_OPEN` (HTTP 422); a `RESOLVED`
        settlement carries no such waiting requirement."

        Design: Difficulty/priority_pair_validation_conflict/pay_rejection_prioritizes_open_incident_over_dispute_window
        """
        # same double violation, with the incident still REPORTED (both
        # REPORTED and UNDER_REVIEW are open states)
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        set_clock("2026-08-03T10:00:00Z")
        incident = report_incident(
            ctx["load"]["id"], ctx["driver"]["id"], incident_type="DOWNER",
            severity="CRITICAL", head_count_affected=1,
            occurred_at="2026-08-02T09:00:00Z")
        assert incident["status"] == "REPORTED"

        resp = api.pay_settlement(s_id, ADMIN)
        validate_error(resp, E.ERR_OPEN_CRITICAL_INCIDENT)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "PENDING"
        assert s["paid_at"] is None
        inc = validate_success(api.get_incident(incident["id"], ADMIN))
        assert inc["status"] == "REPORTED"


class TestDisputeWindowBoundary:
    def test_dispute_window_inclusive_deadline_vs_pay_strict_boundary(self, api):
        """PRD §3.8: "Dispute is allowed only while the current time is at or
        before `dispute_deadline_at` — the window is inclusive, closing at
        exactly `delivered_at` plus 48 hours — after which the attempt fails
        with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 422)."
        PRD §3.8: "Finally, paying directly from `PENDING` — without any
        dispute — additionally requires the dispute window to have run out: the
        current time must be strictly later than `dispute_deadline_at`, or the
        attempt fails with `ERR_DISPUTE_WINDOW_OPEN` (HTTP 422); a `RESOLVED`
        settlement carries no such waiting requirement."

        Design: Difficulty/boundary_precision_check/dispute_window_inclusive_deadline_vs_pay_strict_boundary
        """
        # delivered 2026-08-02T16:30 -> deadline 2026-08-04T16:30:00Z
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]

        # at exactly the deadline: pay (strict >) fails, dispute (<=) succeeds
        set_clock("2026-08-04T16:30:00Z")
        resp_pay = api.pay_settlement(s_id, ADMIN)
        validate_error(resp_pay, E.ERR_DISPUTE_WINDOW_OPEN)

        d = validate_success(
            api.dispute_settlement(s_id, {"disputed_weight_lb": 39000},
                                   CONSIGNEE), 200)
        assert d["status"] == "DISPUTED"
        assert d["disputed_weight_lb"] == 39000

    def test_pay_at_exact_deadline_rejected_while_dispute_succeeds(self, api):
        """PRD §3.8: "Finally, paying directly from `PENDING` — without any
        dispute — additionally requires the dispute window to have run out: the
        current time must be strictly later than `dispute_deadline_at`, or the
        attempt fails with `ERR_DISPUTE_WINDOW_OPEN` (HTTP 422); a `RESOLVED`
        settlement carries no such waiting requirement."
        PRD §3.8: "Dispute is allowed only while the current time is at or
        before `dispute_deadline_at` — the window is inclusive, closing at
        exactly `delivered_at` plus 48 hours — after which the attempt fails
        with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/dispute_window_inclusive_deadline_vs_pay_strict_boundary
        """
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]

        # one minute before the deadline: both pay is too early and dispute OK
        set_clock("2026-08-04T16:29:00Z")
        resp_pay = api.pay_settlement(s_id, ADMIN)
        validate_error(resp_pay, E.ERR_DISPUTE_WINDOW_OPEN)
        d = validate_success(
            api.dispute_settlement(s_id, {"disputed_weight_lb": 39000},
                                   CONSIGNEE), 200)
        assert d["status"] == "DISPUTED"

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "DISPUTED"


class TestPayGates:
    def test_settlement_pay_blocked_by_open_critical_incident(self, api):
        """PRD §3.8: "After the state check, payment is blocked while any
        welfare incident of severity `CRITICAL` on this load remains open in
        `REPORTED` or `UNDER_REVIEW` (`ERR_OPEN_CRITICAL_INCIDENT`, HTTP 422)."
        PRD §3.8: "It is permitted from `PENDING` or `RESOLVED`; from
        `PRELIMINARY` or from an already `PAID` settlement the attempt fails
        with `ERR_SETTLEMENT_NOT_PAYABLE` (HTTP 409), and from `DISPUTED` or
        `COUNTERED` it fails with `ERR_UNRESOLVED_DISPUTE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/settlement_pay_blocked_by_open_critical_incident
        """
        # on-weight delivery; dispute then accept-original -> RESOLVED
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 39500)
        validate_success(api.accept_original(s_id, CONSIGNEE), 200)

        # a CRITICAL incident on this load is still open (REPORTED)
        incident = report_incident(
            ctx["load"]["id"], ctx["driver"]["id"],
            incident_type="INJURY", severity="CRITICAL", head_count_affected=1,
            occurred_at="2026-08-02T09:00:00Z")
        assert incident["status"] == "REPORTED"

        resp = api.pay_settlement(s_id, ADMIN)
        validate_error(resp, E.ERR_OPEN_CRITICAL_INCIDENT)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "RESOLVED"
        assert s["paid_at"] is None
        inc = validate_success(api.get_incident(incident["id"], ADMIN))
        assert inc["status"] == "REPORTED"

    def test_resolved_settlement_pays_after_incident_closed(self, api):
        """PRD §3.8: "After the state check, payment is blocked while any
        welfare incident of severity `CRITICAL` on this load remains open in
        `REPORTED` or `UNDER_REVIEW` (`ERR_OPEN_CRITICAL_INCIDENT`, HTTP 422)."
        PRD §3.8: "A successful payment sets `paid_at` to now and increments
        the settlement `version`."

        Design: Difficulty/cross_entity_state_dependency/settlement_pay_blocked_by_open_critical_incident
        """
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 39500)
        validate_success(api.accept_original(s_id, CONSIGNEE), 200)

        # open CRITICAL incident blocks payment
        incident = report_incident(
            ctx["load"]["id"], ctx["driver"]["id"],
            incident_type="INJURY", severity="CRITICAL", head_count_affected=1,
            occurred_at="2026-08-02T09:00:00Z")
        resp = api.pay_settlement(s_id, ADMIN)
        validate_error(resp, E.ERR_OPEN_CRITICAL_INCIDENT)

        # once closed, the RESOLVED settlement may be paid
        start_review(incident["id"])
        close_incident(incident["id"])
        paid = validate_success(api.pay_settlement(s_id, ADMIN), 200)
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None

    def test_settlement_pay_from_disputed_rejected(self, api):
        """PRD §3.8: "It is permitted from `PENDING` or `RESOLVED`; from
        `PRELIMINARY` or from an already `PAID` settlement the attempt fails
        with `ERR_SETTLEMENT_NOT_PAYABLE` (HTTP 409), and from `DISPUTED` or
        `COUNTERED` it fails with `ERR_UNRESOLVED_DISPUTE` (HTTP 422)."

        Design: Corner/state_machines/settlement_pay_from_disputed_rejected
        """
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]
        set_clock("2026-08-03T10:00:00Z")
        dispute(s_id, 39000)

        resp = api.pay_settlement(s_id, ADMIN)
        validate_error(resp, E.ERR_UNRESOLVED_DISPUTE)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "DISPUTED"
        assert s["paid_at"] is None

    def test_dispute_after_window_closed_rejected(self, api):
        """PRD §3.8: "Dispute is allowed only while the current time is at or
        before `dispute_deadline_at` — the window is inclusive, closing at
        exactly `delivered_at` plus 48 hours — after which the attempt fails
        with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 422)."

        Design: Corner/validations/dispute_after_window_closed_rejected
        """
        # delivered 2026-08-02T16:30 -> deadline 2026-08-04T16:30:00Z
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]

        # one minute past the deadline
        set_clock("2026-08-04T16:31:00Z")
        resp = api.dispute_settlement(s_id, {"disputed_weight_lb": 39000},
                                      CONSIGNEE)
        validate_error(resp, E.ERR_DISPUTE_WINDOW_CLOSED)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "PENDING"

    def test_pay_pending_before_deadline_rejected(self, api):
        """PRD §3.8: "Finally, paying directly from `PENDING` — without any
        dispute — additionally requires the dispute window to have run out: the
        current time must be strictly later than `dispute_deadline_at`, or the
        attempt fails with `ERR_DISPUTE_WINDOW_OPEN` (HTTP 422); a `RESOLVED`
        settlement carries no such waiting requirement."

        Design: Corner/validations/pay_pending_before_deadline_rejected
        """
        ctx = setup_delivered_load(net_lb=40000)
        s_id = ctx["settlement"]["id"]

        # one day before the deadline, no incidents open
        set_clock("2026-08-03T16:30:00Z")
        resp = api.pay_settlement(s_id, ADMIN)
        validate_error(resp, E.ERR_DISPUTE_WINDOW_OPEN)

        s = validate_success(api.get_settlement(s_id, ADMIN))
        assert s["status"] == "PENDING"
        assert s["paid_at"] is None
