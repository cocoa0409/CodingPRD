"""The same deactivate request succeeds once and is then refused, and a clock advance with nothing
due still answers with both cascade counters at zero."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_visitor
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import Certification, VisitorStatus
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)


def _one_visitor_holding_no_seats(api):
    """A roster entry with nothing depending on it anywhere in the system."""
    fx.reset_clock(api)
    visitor = fx.add_visitor(
        api, "Roster Only Visitor", certifications=[Certification.LEAD_VISITOR]
    )
    assert visitor["status"] == VisitorStatus.ACTIVE
    return visitor


def _deactivate_attempt(api, visitor_id, deactivated_reason):
    return api.deactivate_visitor(
        visitor_id, {"deactivated_reason": deactivated_reason}, OFFICER_ONE_HEADERS
    )


def test_removing_a_visitor_stores_the_reason_and_leaves_the_ledger_at_zero(api):
    """PRD §3.5: "Removing a visitor from the roster takes an optional `deactivated_reason` and
    moves the visitor `ACTIVE → INACTIVE`."

    Design: Corner/endpoints/deactivation_is_refused_the_second_time_and_a_quiet_clock_advance_reports_zero_cascades
    """
    visitor = _one_visitor_holding_no_seats(api)

    removed = validate_success(_deactivate_attempt(api, visitor["id"], "left the corps"))
    assert_visitor(removed)
    assert removed["status"] == VisitorStatus.INACTIVE
    assert removed["deactivated_reason"] == "left the corps"
    # No seat ever existed, so the cascade had nothing to release.
    assert removed["committed_travel_days"] == 0
    assert fx.list_seats_for_visitor(api, visitor["id"])[1]["total_count"] == 0


def test_the_second_identical_removal_is_refused_rather_than_absorbed(api):
    """PRD §3.5: "Deactivating a visitor who is already `INACTIVE` is rejected with
    `ERR_VISITOR_INACTIVE` (HTTP 409)."

    Design: Corner/endpoints/deactivation_is_refused_the_second_time_and_a_quiet_clock_advance_reports_zero_cascades
    """
    visitor = _one_visitor_holding_no_seats(api)
    removed = validate_success(_deactivate_attempt(api, visitor["id"], "left the corps"))

    validate_error(
        _deactivate_attempt(api, visitor["id"], "left the corps again"),
        ApiErrorId.VISITOR_INACTIVE,
        409,
    )

    held = fx.read_visitor(api, visitor["id"])
    assert held["version"] == removed["version"]
    assert held["deactivated_reason"] == "left the corps"
    assert held["status"] == VisitorStatus.INACTIVE


def test_a_clock_advance_with_nothing_due_reports_both_counters_at_zero(api):
    """PRD §2.4: "An administrative test-driving capability sets the clock to a supplied
    `to_iso8601` instant and answers with the resulting `current_utc`, together with
    `escalated_deficiency_count` and `terminated_cycle_count` reporting how many deficiencies
    escalated and how many cycles terminated as a consequence of the advance."

    Design: Corner/endpoints/deactivation_is_refused_the_second_time_and_a_quiet_clock_advance_reports_zero_cascades
    """
    visitor = _one_visitor_holding_no_seats(api)
    fx.deactivate_visitor(api, visitor["id"], "left the corps")

    advance = fx.set_clock(api, "2026-12-31T00:00:00Z")
    assert is_iso8601_timestamp(advance["current_utc"])
    assert advance["current_utc"].startswith("2026-12-31T00:00:00")
    # The counters report work done, not rows inspected.
    assert advance["escalated_deficiency_count"] == 0
    assert advance["terminated_cycle_count"] == 0
