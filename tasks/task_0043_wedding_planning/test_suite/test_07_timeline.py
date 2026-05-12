"""TimelineSlot creation, the per-vendor overlap rule, the project-wide
parallel-CEREMONY cap, and the rehearsal_version counter. Covers PRD §3.6.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_timeline_slot,
    create_timeline_slot_payload,
    get_project,
    make_planner_headers,
    setup_project_in_planning,
    setup_project_with_n_accepted_vendors,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 -- Vendor must have ACCEPTED contract on this project.
# ===========================================================================
class TestVendorContractedRule:

    def test_uncontracted_vendor_rejected(self, api):
        """PRD §3.6: "When vendor_id is supplied, the named vendor MUST
        have an ACCEPTED Contract on this project; otherwise the request is
        rejected with ERR_TIMELINE_VENDOR_NOT_CONTRACTED (HTTP 422)."

        Claim: TimelineSlot with random vendor id (no ACCEPTED contract) ->
        ERR_TIMELINE_VENDOR_NOT_CONTRACTED / 422.
        """
        project = setup_project_in_planning()
        planner_headers = make_planner_headers()
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=1000, end_at=2000,
                vendor_id=NON_EXISTENT_UUID,
                kind="CEREMONY", label="X",
            ),
            planner_headers,
        )
        validate_error(
            res, ApiErrorId.ERR_TIMELINE_VENDOR_NOT_CONTRACTED.value
        )

    def test_contracted_vendor_succeeds(self, api):
        """PRD §3.6: "When vendor_id is supplied, the named vendor MUST
        have an ACCEPTED Contract on this project; otherwise the request
        is rejected with ERR_TIMELINE_VENDOR_NOT_CONTRACTED (HTTP 422)."

        Claim: ACCEPTED-contracted vendor + valid interval -> 201 created.
        """
        project, vendors, _contracts = (
            setup_project_with_n_accepted_vendors(2)
        )
        slot = create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=vendors[0]["id"], kind="PREPARATION",
            label="prep",
        )
        assert slot["vendor_id"] == vendors[0]["id"]


# ===========================================================================
# §3.6 -- Per-vendor overlap (with setup_buffer extension).
# ===========================================================================
class TestPerVendorOverlap:

    def test_adjacent_with_zero_buffer_allowed(self, api):
        """PRD §3.6: "Adjacency without overlap -- where one slot's end_at
        equals the next slot's start_at adjusted by setup buffer -- is
        allowed because the intervals are half-open."

        Claim: slot A=[1000,2000) buffer=0 + slot B=[2000,3000) buffer=0
        on the same vendor -> 201 (no overlap).
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(1)
        v = vendors[0]
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="A",
        )
        # Adjacent, no buffer -> allowed.
        slot_b = create_timeline_slot(
            project["id"], start_at=2000, end_at=3000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="B",
        )
        assert slot_b["start_at"] == 2000

    def test_setup_buffer_extends_start_backward_causing_overlap(self, api):
        """PRD §3.6: "two slots A and B overlap iff the larger of
        A.start_at - A.setup_buffer_seconds and B.start_at -
        B.setup_buffer_seconds is strictly less than the smaller of A.end_at
        and B.end_at."

        Claim: A=[1000,2000) buffer=0 + B=[2000,3000) buffer=300 on same
        vendor -> B's effective start is 1700, overlapping A;
        ERR_TIMELINE_VENDOR_OVERLAP / 409.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(1)
        v = vendors[0]
        planner_headers = make_planner_headers()
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="A",
        )
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=2000, end_at=3000,
                vendor_id=v["id"], setup_buffer_seconds=300,
                kind="CEREMONY", label="B",
            ),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_TIMELINE_VENDOR_OVERLAP.value)


# ===========================================================================
# §3.6 -- Project-wide parallel-CEREMONY cap (count-at-instant).
# ===========================================================================
class TestParallelCeremonyCap:

    def test_three_simultaneous_ceremony_slots_rejected(self, api):
        """PRD §3.6: "the project-wide parallel-ceremony cap: among slots
        filtered to kind of CEREMONY (ignoring vendor), the count of slots
        active at any single instant -- counting the setup-buffer extension
        on the start side -- MUST not exceed two; a violation is rejected
        with ERR_TIMELINE_PARALLEL_CAP_EXCEEDED (HTTP 409)."

        Claim: A=[1000,3000), B=[2000,4000), C=[2500,2800) all CEREMONY
        -> at t=2500 three CEREMONY slots overlap; C is rejected.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(3)
        planner_headers = make_planner_headers()
        create_timeline_slot(
            project["id"], start_at=1000, end_at=3000,
            vendor_id=vendors[0]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="A",
        )
        create_timeline_slot(
            project["id"], start_at=2000, end_at=4000,
            vendor_id=vendors[1]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="B",
        )
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=2500, end_at=2800,
                vendor_id=vendors[2]["id"], kind="CEREMONY",
                setup_buffer_seconds=0, label="C",
            ),
            planner_headers,
        )
        validate_error(
            res, ApiErrorId.ERR_TIMELINE_PARALLEL_CAP_EXCEEDED.value
        )

    def test_non_ceremony_slot_excluded_from_cap(self, api):
        """PRD §3.6: "the project-wide parallel-ceremony cap: among slots
        filtered to kind of CEREMONY (ignoring vendor)".

        Claim: 2 CEREMONY slots in parallel + a 3rd PREPARATION slot at the
        same overlapping instant on a 4th vendor -> the 4th slot succeeds
        because PREPARATION is not counted by the cap.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(4)
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=vendors[0]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="A",
        )
        create_timeline_slot(
            project["id"], start_at=1500, end_at=2500,
            vendor_id=vendors[1]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="B",
        )
        # Third slot is PREPARATION; it overlaps in time but is not subject
        # to the CEREMONY cap.
        slot_c = create_timeline_slot(
            project["id"], start_at=1700, end_at=1900,
            vendor_id=vendors[2]["id"], kind="PREPARATION",
            setup_buffer_seconds=0, label="C-prep",
        )
        assert slot_c["kind"] == "PREPARATION"


# ===========================================================================
# §3.6 -- Rehearsal snapshot increments rehearsal_version by exactly 1.
# ===========================================================================
class TestRehearsalSnapshot:

    def test_snapshot_increments_rehearsal_version(self, api):
        """PRD §3.6: "At any point, a planner may snapshot the current
        timeline as a rehearsal version, which atomically increments
        WeddingProject.rehearsal_version by exactly 1."

        Claim: project.rehearsal_version starts at 0; after one snapshot,
        increments to 1.
        """
        project = setup_project_in_planning()
        assert project["rehearsal_version"] == 0
        planner_headers = make_planner_headers()
        api.snapshot_rehearsal(project["id"], planner_headers)
        p_after = get_project(project["id"])
        assert p_after["rehearsal_version"] == 1
