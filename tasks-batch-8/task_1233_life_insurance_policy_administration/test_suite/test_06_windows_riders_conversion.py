"""Clock-based windows (reinstatement, conversion) and rider gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_days,
    add_rider,
    add_years,
    create_issued_policy,
    create_lapsed_policy,
    create_term_convertible_policy,
    get_policy,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["agent_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


def _window_inside(paid_to_date_or_issue: str) -> str:
    """Thirty days inside the five-year window (robust to leap-year counting)."""
    return add_days(add_years(paid_to_date_or_issue, 5), -30)


def _window_outside(paid_to_date_or_issue: str) -> str:
    """Thirty days beyond the five-year window under any day-count reading."""
    return add_days(add_years(paid_to_date_or_issue, 5), 30)


class TestReinstatementWindow:
    def test_request_inside_five_year_window_accepted(self, api):
        """PRD §3.9: "the request falls within five years of the lapse — the logical clock must not
        be later than five years after the lapse date, or the request is
        rejected with `ERR_WINDOW_EXPIRED`". And: "The lapse date is the policy's `paid_to_date` — the last date through which
        premiums were fully paid."

        Design: Difficulty/resource_temporal_overlap/reinstatement_window_half_open
        """
        bundle = create_lapsed_policy(date_of_birth="1980-09-01")
        policy = get_policy(bundle["policy"]["id"])
        assert policy["premium_payment_status"] == "LAPSED"
        lapse_date = policy["paid_to_date"]

        set_clock(_window_inside(lapse_date))
        resp = api.create_reinstatement_request(bundle["policy"]["id"], AGENT)
        request = validate_success(resp, expected_status=201)
        assert request["status"] == "PENDING"
        assert get_policy(bundle["policy"]["id"])["premium_payment_status"] == (
            "REINSTATED_PENDING")

    def test_request_beyond_five_year_window_rejected(self, api):
        """PRD §3.9: "the request falls within five years of the lapse — the logical clock must not
        be later than five years after the lapse date, or the request is
        rejected with `ERR_WINDOW_EXPIRED`". And: "The lapse date is the policy's `paid_to_date` — the last date through which
        premiums were fully paid."

        Design: Difficulty/resource_temporal_overlap/reinstatement_window_half_open
        """
        bundle = create_lapsed_policy(date_of_birth="1980-09-01")
        policy = get_policy(bundle["policy"]["id"])
        lapse_date = policy["paid_to_date"]

        set_clock(_window_outside(lapse_date))
        resp = api.create_reinstatement_request(bundle["policy"]["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_WINDOW_EXPIRED)


class TestConversionWindow:
    def test_filing_inside_five_year_window_accepted(self, api):
        """PRD §3.10: "the logical clock must be within five years of the source policy's
        `issue_date` — later filings are rejected with `ERR_WINDOW_EXPIRED`".

        Design: Difficulty/resource_temporal_overlap/conversion_window_aggregate_capacity
        """
        bundle = create_term_convertible_policy(
            date_of_birth="1985-05-10")
        issue_date = bundle["policy"]["issue_date"]
        set_clock(_window_inside(issue_date))
        resp = api.create_conversion_request(
            bundle["policy"]["id"], bundle["target_template"]["id"],
            5_000_000, AGENT)
        request = validate_success(resp, expected_status=201)
        assert request["status"] == "PENDING"
        assert request["source_policy_id"] == bundle["policy"]["id"]

    def test_filing_beyond_five_year_window_rejected(self, api):
        """PRD §3.10: "the logical clock must be within five years of the source policy's
        `issue_date` — later filings are rejected with `ERR_WINDOW_EXPIRED`".

        Design: Difficulty/resource_temporal_overlap/conversion_window_aggregate_capacity
        """
        bundle = create_term_convertible_policy(
            date_of_birth="1985-05-10")
        issue_date = bundle["policy"]["issue_date"]
        set_clock(_window_outside(issue_date))
        resp = api.create_conversion_request(
            bundle["policy"]["id"], bundle["target_template"]["id"],
            5_000_000, AGENT)
        validate_error(resp, ApiErrorId.ERR_WINDOW_EXPIRED)


class TestRiderExerciseGate:
    def test_waiver_exercise_in_grace_rejected(self, api):
        """PRD §3.10: "Exercising `WAIVER_OF_PREMIUM` requires the policy's `premium_payment_status`
        to be `CURRENT`".
        PRD §2.8: "operations blocked by a non-terminal but incompatible state are rejected with
        `ERR_INVALID_STATE`".

        Design: Difficulty/cross_entity_state_dependency/rider_terminate_requires_in_force_policy
        """
        bundle = create_issued_policy(premium_mode="MONTHLY",
                                      date_of_birth="1986-04-25")
        rider = add_rider(bundle, "WAIVER_OF_PREMIUM", 0)
        # Mid-grace under any cycle-creation model (first unpaid monthly cycle
        # ends at most two months after issue; 31-day grace never over by then).
        set_clock("2026-07-02T00:00:00Z")
        assert get_policy(bundle["policy"]["id"])["premium_payment_status"] == "GRACE"

        resp = api.exercise_rider(bundle["policy"]["id"], rider["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_waiver_exercise_while_current_waives_cycles(self, api):
        """PRD §3.10: "Exercising `WAIVER_OF_PREMIUM` requires the policy's `premium_payment_status`
        to be `CURRENT`; while the rider stands `EXERCISED`, all current and
        future billing cycles are `WAIVED`."

        Design: Difficulty/cross_entity_state_dependency/rider_terminate_requires_in_force_policy
        """
        bundle = create_issued_policy(premium_mode="MONTHLY",
                                      date_of_birth="1986-04-25")
        rider = add_rider(bundle, "WAIVER_OF_PREMIUM", 0)
        policy_id = bundle["policy"]["id"]
        assert get_policy(policy_id)["premium_payment_status"] == "CURRENT"

        exercised = validate_success(api.exercise_rider(policy_id, rider["id"], AGENT))
        assert exercised["status"] == "EXERCISED"
        cycles, _m = validate_paginated(api.list_billing_cycles(policy_id, AGENT))
        assert cycles
        assert all(c["status"] in ("PAID", "WAIVED") for c in cycles), (
            "current and future cycles are WAIVED while the rider is EXERCISED")

    def test_terminate_exercised_rider_rejected(self, api):
        """PRD §3.10: "operating on a rider already `TERMINATED` or `EXERCISED` — terminating an
        exercised rider, for instance — is rejected with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/terminal_rider_terminate_returns_invalid_state
        """
        bundle = create_issued_policy(premium_mode="MONTHLY",
                                      date_of_birth="1983-09-09")
        rider = add_rider(bundle, "WAIVER_OF_PREMIUM", 0)
        policy_id = bundle["policy"]["id"]
        exercised = validate_success(api.exercise_rider(policy_id, rider["id"], AGENT))
        assert exercised["status"] == "EXERCISED"

        resp = api.terminate_rider(policy_id, rider["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
