"""Premium billing: grace-period boundary, lapse, and the lapse cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_days,
    add_rider,
    complete_reinstatement,
    create_funded_policy,
    create_issued_policy,
    create_lapsed_policy,
    create_policy_with_loan,
    create_reinstatement_request,
    get_policy,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
)

AGENT = TEST_USERS["agent_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


def _grace_policy():
    """MONTHLY policy pushed into GRACE; returns (bundle, grace_period_end_date).

    The clock lands mid-grace under any cycle-creation model: the first unpaid
    monthly cycle ends at most two months after issue, so 2026-07-02 is always
    inside its 31-day grace window, never past it.
    """
    bundle = create_issued_policy(premium_mode="MONTHLY")
    set_clock("2026-07-02T00:00:00Z")
    policy = get_policy(bundle["policy"]["id"])
    assert policy["premium_payment_status"] == "GRACE", (
        f"expected GRACE mid-window, got {policy['premium_payment_status']}")
    grace_end = policy["grace_period_end_date"]
    assert grace_end, "policy in GRACE must carry grace_period_end_date"
    return bundle, grace_end


class TestGracePeriodBoundary:
    def test_policy_remains_in_grace_on_grace_end_date(self, api):
        """PRD §3.4: "The grace-to-lapse boundary is strict: the policy lapses only when the current
        date is **strictly after** `grace_period_end_date`; when the current
        date equals `grace_period_end_date` exactly, the policy remains in
        `GRACE`, and lapse fires on the following day."

        Design: Difficulty/boundary_precision_check/grace_period_end_date_boundary
        """
        bundle, grace_end = _grace_policy()
        set_clock(grace_end[:10] + "T23:59:59Z")
        policy = get_policy(bundle["policy"]["id"])
        assert policy["premium_payment_status"] == "GRACE", (
            "on grace_period_end_date itself the policy must remain in GRACE")

    def test_policy_lapses_the_day_after_grace_end(self, api):
        """PRD §3.4: "The grace-to-lapse boundary is strict: the policy lapses only when the current
        date is **strictly after** `grace_period_end_date`; when the current
        date equals `grace_period_end_date` exactly, the policy remains in
        `GRACE`, and lapse fires on the following day."

        Design: Difficulty/boundary_precision_check/grace_period_end_date_boundary
        """
        bundle, grace_end = _grace_policy()
        set_clock(add_days(grace_end, 1))
        policy = get_policy(bundle["policy"]["id"])
        assert policy["premium_payment_status"] == "LAPSED", (
            "one day past grace_period_end_date the policy must be LAPSED")


class TestLapseCascade:
    def test_lapse_forecloses_loans_and_terminates_riders(self, api):
        """PRD §3.4: "At lapse, the cycle moves from `GRACE` to `LAPSED`, the policy's
        `premium_payment_status` moves from `GRACE` to `LAPSED`, and a
        three-part cascade runs: any outstanding policy loans are marked
        `FORECLOSED`, with their principal and accrued interest folded into
        the non-forfeiture arithmetic of §3.8; every active rider on the
        policy is `TERMINATED`".

        Design: Difficulty/transitive_cascade/lapse_cascade_three_hop
        """
        bundle, loan = create_policy_with_loan(
            5_000_000, cash_to_add=10_000_000,
            date_of_birth="1978-08-01")
        rider = add_rider(bundle, "ACCIDENTAL_DEATH_BENEFIT", 1_000_000)
        policy_id = bundle["policy"]["id"]

        set_clock(add_days(bundle["policy"]["issue_date"], 200))

        policy = get_policy(policy_id)
        assert policy["premium_payment_status"] == "LAPSED"
        loan_after = get_success_data(api.get_loan(policy_id, loan["id"], AGENT))
        assert loan_after["status"] == "FORECLOSED", (
            "outstanding loan must be FORECLOSED by the lapse cascade")
        rider_after = get_success_data(api.get_rider(rider["id"], AGENT))
        assert rider_after["status"] == "TERMINATED", (
            "active rider must be TERMINATED by the lapse cascade")

    def test_lapse_with_value_auto_elects_extended_term(self, api):
        """PRD §3.4: "if the policy holds non-forfeiture value — `cash_value_cents` greater than
        zero — and no explicit non-forfeiture election exists, the system
        automatically creates an election of type `EXTENDED_TERM` on the
        policyholder's behalf."
        PRD §3.8: "the policy's `premium_payment_status` moves to `PAID_UP` and its `form_status`
        moves from `IN_FORCE` to `EXTENDED_TERM`."

        Design: Difficulty/transitive_cascade/lapse_cascade_three_hop
        """
        # Cash value comfortably above one month of term cost (no loans), so
        # the automatic election can actually be computed.
        bundle = create_funded_policy(500_000, premium_mode="MONTHLY",
                                      date_of_birth="1978-08-01")
        policy_id = bundle["policy"]["id"]
        set_clock(add_days(bundle["policy"]["issue_date"], 200))

        policy = get_policy(policy_id)
        assert policy["form_status"] == "EXTENDED_TERM"
        assert policy["premium_payment_status"] == "PAID_UP"
        elections, _meta = validate_paginated(
            api.list_policy_nonforfeiture_elections(policy_id, AGENT))
        assert len(elections) == 1, "exactly one automatic election must exist"
        assert elections[0]["election_type"] == "EXTENDED_TERM"
        assert elections[0]["resulting_term_months"] > 0


class TestParallelStateDimensions:
    def test_lapse_changes_billing_dimension_only(self, api):
        """PRD §2.8: "The two dimensions evolve in parallel: a policy may lapse (a billing event)
        while remaining `IN_FORCE` in form".
        PRD §3.4: "At lapse, the cycle moves from `GRACE` to `LAPSED`, the policy's
        `premium_payment_status` moves from `GRACE` to `LAPSED`".

        Design: Difficulty/non_linear_state_machine/policy_parallel_dimensions_independent
        """
        bundle = create_issued_policy(premium_mode="MONTHLY",
                                      date_of_birth="1980-06-01")
        set_clock(add_days(bundle["policy"]["issue_date"], 200))
        policy = get_policy(bundle["policy"]["id"])
        assert policy["premium_payment_status"] == "LAPSED"
        assert policy["form_status"] == "IN_FORCE", (
            "lapse is a billing event; the form dimension stays IN_FORCE")

    def test_reinstatement_cycle_leaves_form_in_force(self, api):
        """PRD §2.8: "The two dimensions evolve in parallel: a policy may lapse (a billing event)
        while remaining `IN_FORCE` in form".
        PRD §3.9: "On approval the request's status and `underwriter_decision` become `APPROVED`;
        the policy's `premium_payment_status` returns to `CURRENT`".

        Design: Difficulty/non_linear_state_machine/policy_parallel_dimensions_independent
        """
        bundle = create_lapsed_policy(date_of_birth="1980-06-01")
        policy_id = bundle["policy"]["id"]
        assert get_policy(policy_id)["premium_payment_status"] == "LAPSED"

        request = create_reinstatement_request(bundle)
        assert get_policy(policy_id)["premium_payment_status"] == "REINSTATED_PENDING"
        complete_reinstatement(bundle, request["id"])

        policy = get_policy(policy_id)
        assert policy["premium_payment_status"] == "CURRENT", (
            "reinstatement approval returns billing posture to CURRENT")
        assert policy["form_status"] == "IN_FORCE", (
            "the form dimension is untouched by the lapse/reinstatement cycle")


class TestReinstatementEvidenceCycle:
    def test_evidence_cycle_may_repeat(self, api):
        """PRD §3.9: "the underwriter may move the request from `PENDING` to `EVIDENCE_REQUIRED`,
        and the agent's submission of evidence returns it from
        `EVIDENCE_REQUIRED` to `PENDING` with `evidence_of_insurability` set
        to true — a cycle that may repeat while the underwriter gathers what
        is needed."

        Design: Difficulty/non_linear_state_machine/reinstatement_request_evidence_cycle
        """
        bundle = create_lapsed_policy(date_of_birth="1982-04-01")
        policy_id = bundle["policy"]["id"]
        request = create_reinstatement_request(bundle)
        rid = request["id"]

        for _ in range(2):
            get_success_data(api.request_reinstatement_evidence(policy_id, rid,
                                                                UNDERWRITER))
            get_success_data(api.submit_reinstatement_evidence(policy_id, rid, AGENT))

        after = get_success_data(api.get_reinstatement_request(rid, AGENT))
        assert after["status"] == "PENDING"
        assert after["evidence_of_insurability"] is True

    def test_second_open_request_rejected_while_one_pending(self, api):
        """PRD §3.9: "An `Agent` may request reinstatement of a policy whose
        `premium_payment_status` is `LAPSED`, provided the policy's
        `form_status` is still `IN_FORCE`, the request falls within five years
        of the lapse — the logical clock must not be later than five years
        after the lapse date, or the request is rejected with
        `ERR_WINDOW_EXPIRED` — and no earlier reinstatement request on the
        same policy still stands in `PENDING` or `EVIDENCE_REQUIRED`."
        PRD §2.12: "**fourth**, whether the target resource's current state permits the operation
        (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` where the resource
        sits in a terminal state)".

        Design: Difficulty/non_linear_state_machine/reinstatement_request_evidence_cycle
        """
        bundle = create_lapsed_policy(date_of_birth="1982-04-01")
        policy_id = bundle["policy"]["id"]
        first = create_reinstatement_request(bundle)
        assert first["status"] == "PENDING"
        # The policy now stands REINSTATED_PENDING, not LAPSED, and an earlier
        # request is still PENDING: the creation gate rejects the duplicate.
        resp = api.create_reinstatement_request(policy_id, AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
