"""Difficulty Rule 8 — resource_temporal_overlap.

(A) The ClosingDisclosure wait window is closed on the upper bound: at
    clock == earliest_consummation_at, acknowledge SUCCEEDS.
(B) The ExchangeAccount identification window is closed on the upper bound
    too — identify at clock == identification_deadline SUCCEEDS, at one
    second strictly later it FAILS with ERR_EXCHANGE_ID_DEADLINE_PASSED.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    setup_actors,
    setup_delivered_cd,
    create_exchange_account,
    identify_exchange_account_payload,
    advance_clock,
    api_client,
)


class TestClosingDisclosureWindowInclusiveAtSeventyTwoHours:
    """Acknowledge at exactly issued_at + 72h succeeds (closed boundary).
    """

    def test_acknowledge_at_inclusive_72h_boundary_succeeds(self, api):
        """PRD §3.4: "It is gated on time: the current UTC clock must be at or after ``earliest_consummation_at``. Acknowledging on the 72-hour mark itself is allowed; strictly earlier is rejected with ``ERR_CD_THREE_DAY_NOT_ELAPSED`` (HTTP 409). Acknowledgement stamps ``acknowledged_at`` to the current UTC clock."

        Design: Difficulty/resource_temporal_overlap/cd_72h_window_inclusive_lower_bound_clock_overlap
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z")
        advance_clock(259200, scenario["actors"]["co"])  # exactly +72h
        res = api.acknowledge_closing_disclosure(
            scenario["cd_id"], scenario["actors"]["eo"]
        )
        cd = validate_success(res, expected_status=200)
        assert cd["status"] == "ACKNOWLEDGED", \
            f"acknowledge at exactly +72h must succeed, got {cd['status']}"

    def test_acknowledge_at_inclusive_72h_stamps_acknowledged_at_to_clock(self, api):
        """PRD §3.4: "It is gated on time: the current UTC clock must be at or after ``earliest_consummation_at``. Acknowledging on the 72-hour mark itself is allowed; strictly earlier is rejected with ``ERR_CD_THREE_DAY_NOT_ELAPSED`` (HTTP 409). Acknowledgement stamps ``acknowledged_at`` to the current UTC clock."

        Design: Difficulty/resource_temporal_overlap/cd_72h_window_inclusive_lower_bound_clock_overlap
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z")
        advance_clock(259200, scenario["actors"]["co"])
        res = api.acknowledge_closing_disclosure(
            scenario["cd_id"], scenario["actors"]["eo"]
        )
        cd = validate_success(res, expected_status=200)
        assert cd["acknowledged_at"].startswith("2026-06-04T00:00:00"), \
            f"acknowledged_at must stamp the +72h instant (2026-06-04T00:00:00Z), got {cd['acknowledged_at']}"


class TestExchangeIdentificationWindowAtFortyFiveDayBoundary:
    """Identification deadline is right-closed: at clock == deadline the
    identify call succeeds; one second past, it fails.
    """

    def test_identify_at_exact_45d_deadline_succeeds(self, api):
        """PRD §3.7: "The action is allowed only while the current UTC clock is at or before ``identification_deadline`` — equality is allowed (an identification on the last day is valid), strictly later is rejected with ``ERR_EXCHANGE_ID_DEADLINE_PASSED``."

        Design: Difficulty/resource_temporal_overlap/exchange_identification_45d_strict_upper_buffer
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        ea = create_exchange_account(
            actors, relinquished_closing_date="2026-06-01T00:00:00Z"
        )
        # Advance clock by exactly 45 days = 3_888_000 seconds.
        advance_clock(3_888_000, actors["co"])
        res = api.identify_exchange_account(
            ea["id"],
            identify_exchange_account_payload(replacement_property_address="100 Boundary Ln"),
            actors["eo"],
        )
        out = validate_success(res, expected_status=200)
        assert out["status"] == "IDENTIFIED", \
            f"identify at exactly +45d must succeed (inclusive boundary), got {out['status']}"

    def test_identify_one_second_past_45d_deadline_rejected(self, api):
        """PRD §3.7: "The action is allowed only while the current UTC clock is at or before ``identification_deadline`` — equality is allowed (an identification on the last day is valid), strictly later is rejected with ``ERR_EXCHANGE_ID_DEADLINE_PASSED``."

        PRD §3.7 also states the OPEN account "flips to ``FAILED`` when the
        current UTC clock is strictly greater than ``identification_deadline``
        and ``replacement_property_identified`` is still ``false``", and that
        this transition is "evaluated synchronously when the system observes
        the relevant deadline (typically on a read or a related write)". The
        identify call at deadline+1s is such a related write: a faithful
        PRD-only implementer may legitimately fire the auto-FAILED transition
        first, after which the OPEN-state gate rejects the identify with
        ``ERR_INVALID_STATE``. The PRD names ``ERR_EXCHANGE_ID_DEADLINE_PASSED``
        for the strictly-later identify but never states the deadline check
        pre-empts the FAILED auto-transition / state gate, so both error_ids
        are PRD-consistent here (ERROR PRECEDENCE SILENCE).

        Design: Difficulty/resource_temporal_overlap/exchange_identification_45d_strict_upper_buffer
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        ea = create_exchange_account(
            actors, relinquished_closing_date="2026-06-01T00:00:00Z"
        )
        # Push the clock one second past the 45-day deadline.
        advance_clock(3_888_001, actors["co"])
        res = api.identify_exchange_account(
            ea["id"],
            identify_exchange_account_payload(replacement_property_address="101 Over Ln"),
            actors["eo"],
        )
        # Both candidate error_ids map to HTTP 409 in the PRD error catalog.
        assert res.status_code == 409, \
            f"past-deadline identify must be HTTP 409, got {res.status_code}"
        validate_error_is_one_of(
            res,
            ["ERR_EXCHANGE_ID_DEADLINE_PASSED", "ERR_INVALID_STATE"],
        )
