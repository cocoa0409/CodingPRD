"""Clearance reporting: state machine + rate computation.

Covers corner state_machines + calculations entries and the difficulty
clearance-rate pinned-rounding instance.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    make_station_group_owner_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_clearance_report,
    walk_clearance_to_audited,
    walk_clearance_to_filed,
)


class TestClearanceStateMachine:
    def test_audit_from_draft_rejected(self, api):
        """PRD §3.5: "The affiliate-relations desk audits a filed report,
        moving it from `FILED` to `AUDITED`."
        PRD §2.10 step 4: state-admissibility failures surface
        `ERR_INVALID_STATE`.

        Design: Corner/state_machines/clearance_report_audit_from_draft_returns_invalid_state
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        report = create_clearance_report(nid, sid, sgo)  # stays in DRAFT
        resp = api.audit_clearance_report(nid, sid, report["id"], nar)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_resolve_cleared_below_threshold_rejected(self, api):
        """PRD §3.5: "**Resolve cleared** moves the report to `CLEARED` and
        requires `clearance_rate` to be at least 0.85. Attempting
        resolve-cleared on a rate below 0.85 is rejected with
        `ERR_DEFICIENT_CLEARANCE` (HTTP 409)."

        Design: Corner/state_machines/clearance_resolve_cleared_requires_rate_threshold
        """
        scenario = setup_basic_scenario(clearance_obligation_hours=100)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        # 50 / 100 = 0.5, well below 0.85.
        report = create_clearance_report(
            nid, sid, sgo, cleared_hours=50.0, preempted_hours=50.0
        )
        walk_clearance_to_audited(nid, sid, report["id"], sgo, nar)
        resp = api.resolve_cleared_clearance_report(nid, sid, report["id"], nar)
        validate_error(resp, ApiErrorId.ERR_DEFICIENT_CLEARANCE)


class TestClearanceRateRounding:
    def test_clearance_rate_uses_divide_then_round(self, api):
        """PRD §3.5: "The rate is the report's `cleared_hours` divided by the
        agreement's `clearance_obligation_hours`, rounded half-up to four
        decimal places — and the order of operations is pinned: divide first,
        then round. Pre-rounding the inputs yields different four-decimal
        results and is non-conformant."

        Design: Difficulty/combinatorial_formula/clearance_rate_pinned_rounding_order
        """
        scenario = setup_basic_scenario(clearance_obligation_hours=103)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        # 87.345 / 103 = 0.8480097..., round-half-up to 4 decimals = 0.8480.
        report = create_clearance_report(
            nid, sid, sgo, cleared_hours=87.345, preempted_hours=15.655
        )
        filed = walk_clearance_to_filed(nid, sid, report["id"], sgo)
        assert filed["clearance_rate"] == pytest.approx(0.8480, abs=1e-9), (
            f"Expected clearance_rate == 0.8480 (divide-then-round); got "
            f"{filed['clearance_rate']!r}"
        )

    def test_clearance_rate_distinguishes_pre_rounding_bug(self, api):
        """PRD §3.5: "the order of operations is pinned: divide first, then
        round. Pre-rounding the inputs yields different four-decimal results
        and is non-conformant." A pre-rounding implementation would compute
        round(87.345)=87 then 87/103=0.8447 — distinguishable at the 4th
        decimal.

        Design: Difficulty/combinatorial_formula/clearance_rate_pinned_rounding_order
        """
        scenario = setup_basic_scenario(clearance_obligation_hours=103)
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        report = create_clearance_report(
            nid, sid, sgo, cleared_hours=87.345, preempted_hours=15.655
        )
        filed = walk_clearance_to_filed(nid, sid, report["id"], sgo)
        # Verify the 4-decimal value precisely and that it differs from the
        # pre-rounding alternative (0.8447).
        rate = filed["clearance_rate"]
        assert rate == pytest.approx(0.8480, abs=1e-9)
        assert rate != pytest.approx(0.8447, abs=1e-9)


class TestClearanceRateStation:
    def test_draft_report_does_not_set_station_clearance_rate(self, api):
        """PRD §3.1: station `clearance_rate_current_period` is "null until a
        first clearance report is filed." (A DRAFT report has not been filed.)

        Design: Corner/calculations/clearance_rate_input_set_filters_draft
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        # Create a DRAFT report but never file it.
        create_clearance_report(
            nid, sid, sgo, cleared_hours=50.0, preempted_hours=50.0
        )
        station = validate_success(api.get_station(nid, sid, nar))
        assert station["clearance_rate_current_period"] is None, (
            "DRAFT clearance reports must not drive "
            "Station.clearance_rate_current_period; got "
            f"{station['clearance_rate_current_period']!r}"
        )
