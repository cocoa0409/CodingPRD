"""Size-match approval validations — PRD §3.4.

Three independent precondition checks govern slip suitability:
- LOA: slip.length_feet >= vessel.loa_feet → ERR_LOA_EXCEEDS_SLIP
- Beam: slip.beam_feet - 2.0 >= vessel.beam_feet →
  ERR_BEAM_BUFFER_VIOLATION
- Draft: slip.depth_feet >= vessel.draft_feet → ERR_DRAFT_EXCEEDS_DEPTH

These tests are isolated so only one rule can fire per scenario, per
the §validation-priority Silence-pattern category guidance.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    approve_reservation,
    create_active_policy,
    create_boater_with_vessel,
    create_marina,
    create_reservation,
    create_slip,
    setup_draft_reservation,
    validate_error,
)


# ===========================================================================
# LOA size-match — PRD §3.4
# ===========================================================================
class TestLoaSizeMatch:

    def test_loa_exceeds_slip_rejected(self, api, dock_master_headers):
        """PRD §3.4: "The slip's `length_feet` must be at least the
        vessel's `loa_feet`; if the vessel is longer than the slip can
        berth, approval is rejected with `ERR_LOA_EXCEEDS_SLIP`."

        Claim: vessel LOA strictly greater than slip length →
        ERR_LOA_EXCEEDS_SLIP."""
        # Slip 30ft, vessel 40ft LOA — over-length.
        # Beam/draft selected so other size-match checks pass cleanly.
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=False,
            slip_length_feet=30.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=40.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LOA_EXCEEDS_SLIP.value)

    def test_loa_exact_match_accepted(self, api, dock_master_headers):
        """PRD §3.4: "The slip's `length_feet` must be at least the
        vessel's `loa_feet`..." — the wording "at least" implies
        equality passes.

        Claim: vessel LOA == slip length passes (the boundary is
        inclusive on the slip's side)."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=False,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=40.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        result = approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert result["status"] == "APPROVED", (
            f"Boundary LOA = slip length must approve, got "
            f"{result['status']!r}"
        )


# ===========================================================================
# Beam buffer — PRD §3.4
# ===========================================================================
class TestBeamBuffer:

    def test_beam_buffer_violation_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "The slip's `beam_feet` must be at least two feet
        greater than the vessel's `beam_feet`, reserving a two-foot
        buffer on each side for fenders and ingress; a beam violation
        is rejected with `ERR_BEAM_BUFFER_VIOLATION`."

        Claim: slip_beam - vessel_beam < 2.0 → ERR_BEAM_BUFFER_VIOLATION.
        Use slip_beam=11.0 and vessel_beam=10.0 (delta=1.0 < 2.0)."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=False,
            slip_length_feet=40.0,
            slip_beam_feet=11.0,
            slip_depth_feet=6.0,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BEAM_BUFFER_VIOLATION.value)

    def test_beam_buffer_exact_two_feet_passes(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "The slip's `beam_feet` must be at least two feet
        greater than the vessel's `beam_feet`..." — boundary case: a
        gap of exactly 2.0 feet satisfies the rule.

        Claim: slip_beam - vessel_beam == 2.0 passes."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=False,
            slip_length_feet=40.0,
            slip_beam_feet=12.0,
            slip_depth_feet=6.0,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        result = approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert result["status"] == "APPROVED", (
            f"Beam delta exactly 2.0 must approve, got "
            f"{result['status']!r}"
        )


# ===========================================================================
# Draft / depth — PRD §3.4
# ===========================================================================
class TestDraftDepth:

    def test_draft_exceeds_depth_rejected(self, api, dock_master_headers):
        """PRD §3.4: "The slip's `depth_feet` must be at least the
        vessel's `draft_feet`; if the vessel sits too deep for the
        slip, approval is rejected with `ERR_DRAFT_EXCEEDS_DEPTH`."

        Claim: vessel draft strictly greater than slip depth →
        ERR_DRAFT_EXCEEDS_DEPTH."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=False,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=4.0,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=5.0,
        )
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRAFT_EXCEEDS_DEPTH.value)

    def test_draft_exact_depth_passes(self, api, dock_master_headers):
        """PRD §3.4: "The slip's `depth_feet` must be at least the
        vessel's `draft_feet`..." — boundary case: depth == draft
        passes.

        Claim: slip.depth_feet == vessel.draft_feet → APPROVED."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=False,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=4.0,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        result = approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert result["status"] == "APPROVED"
