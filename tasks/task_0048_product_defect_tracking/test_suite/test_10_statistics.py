"""Statistics endpoints: density (provisional & final), reopen-rate,
removal-rate.
"""
from __future__ import annotations

import math

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    api_client,
    approve_severity_override,
    assign_defect,
    close_defect,
    create_defect,
    fetch_defect,
    latest_fix_record,
    request_severity_override,
    setup_basic_module,
    setup_defect_in_state,
    start_progress,
    submit_fix,
    verify_defect,
)


class TestProvisionalDensity:
    def test_provisional_density_three_majors(self):
        """PRD §3.13: "Each eligible defect contributes a per-defect
        weight keyed on its current effective_severity: 3.0 for BLOCKER,
        2.0 for CRITICAL, 1.0 for MAJOR, 0.5 for MINOR, and 0.25 for
        TRIVIAL. The computation proceeds in a strictly pinned four-step
        order: first, each defect's per-defect weight is rounded half-up
        to one decimal place; second, the rounded contributions are
        summed; third, the sum is divided by the module's kloc ...
        fourth, the quotient is rounded half-up to two decimal places."

        Three MAJOR defects on a kloc=2.0 module:
        per-line: 1.0,1.0,1.0; sum=3.0; / 2.0 = 1.5; final 1.50.
        """
        team, module = setup_basic_module(
            initial_defect_quota=10, kloc=2.0,
        )
        for _ in range(3):
            create_defect(team, module, severity="MAJOR")
        resp = api_client.get_density(
            team.triage_headers,
            params={"module_id": module["id"], "mode": "provisional"},
        )
        data = validate_success(resp)
        assert data["density"] == pytest.approx(1.50, abs=0.001)

    def test_provisional_density_four_trivials_per_line_round_first(self):
        """PRD §3.13: "The order is load-bearing: rounding per defect
        first, then summing, then dividing, then final-rounding produces
        a different number from summing-then-rounding or from
        divide-then-round-the-input."

        Four TRIVIAL (weight 0.25 each) on kloc=2.0. Per-line round
        half-up to 1 dec: 0.25 → 0.3 (round_half_up of x.x5 away from
        zero). Sum = 1.2. /2.0 = 0.6. Final = 0.60.
        Sum-then-divide-then-round (wrong) would yield 0.50.
        """
        team, module = setup_basic_module(
            initial_defect_quota=10, kloc=2.0,
        )
        for _ in range(4):
            create_defect(team, module, severity="TRIVIAL")
        resp = api_client.get_density(
            team.triage_headers,
            params={"module_id": module["id"], "mode": "provisional"},
        )
        data = validate_success(resp)
        # The pinned per-line-first order yields 0.60.
        assert data["density"] == pytest.approx(0.60, abs=0.001)

    def test_provisional_density_excludes_closed_defects(self):
        """PRD §3.13: "CLOSED defects are excluded".
        """
        team, module = setup_basic_module(
            initial_defect_quota=10, kloc=2.0,
        )
        # One MAJOR will be closed.
        d_closed = setup_defect_in_state(
            team, module, "CLOSED", severity="MAJOR",
        )
        # One MAJOR is still open.
        create_defect(team, module, severity="MAJOR")
        resp = api_client.get_density(
            team.triage_headers,
            params={"module_id": module["id"], "mode": "provisional"},
        )
        data = validate_success(resp)
        # Only the open MAJOR contributes: 1.0/2.0 = 0.50.
        assert data["density"] == pytest.approx(0.50, abs=0.001)


class TestFinalDensity:
    def test_final_density_uses_severity_at_closure(self):
        """PRD §3.13: "For each eligible defect the per-defect weight is
        keyed on its effective_severity as it stood at the moment of
        closure, not at the moment of original report — so a defect that
        entered the window classified as MAJOR but had a SeverityOverride
        approved to BLOCKER during the window contributes 3.0, not 1.0."
        """
        team, module = setup_basic_module(
            initial_defect_quota=5, kloc=2.0,
        )
        d = create_defect(team, module, severity="MAJOR")
        # Override to BLOCKER, drive to CLOSED.
        override = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, override)
        assign_defect(team, d)
        start_progress(team, d)
        submit_fix(team, d, fix_version="1.0.1")
        verify_defect(team, d, outcome="PASSED")
        close_defect(team, d)
        # Query final density with a window that includes first_fixed_at_minute.
        resp = api_client.get_density(
            team.triage_headers,
            params={
                "module_id": module["id"], "mode": "final",
                "period_start": 0, "period_end": 1000,
            },
        )
        data = validate_success(resp)
        # weight_at_closure = BLOCKER -> 3.0; per-line round = 3.0; sum 3.0;
        # /2.0 = 1.5; final 1.50.
        assert data["density"] == pytest.approx(1.50, abs=0.001)


# NOTE: Tests asserting a specific response field name (`reopen_rate` /
# `removal_rate`) for the reopen-rate and removal-rate endpoints have been
# removed. PRD §3.13 names the rate computation but does not name the
# response field; an implementer could reasonably use `rate`, `reopen_rate`,
# or another key. Per the PRD-First contract, asserting a specific key fails
# unique derivability.
