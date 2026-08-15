"""Discolored-water complaints: cluster auto-creation, the three-complaint
boundary, enum validation, manual link integrity, and close-path guards."""
from datetime import datetime, timedelta

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    api_client,
    TEST_USERS,
    create_program,
    create_zone,
    create_hydrant,
    create_planned_sequence,
    create_open_complaint,
    setup_complaint_cluster,
    get_hydrant,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestComplaintClusterCascade:
    def test_complaint_cluster_cascade_links_and_creates(self, api):
        """PRD §3.5: "If that count reaches at least three, and the hydrant is
        `IN_SERVICE`, and no `FlushSequence` already exists for this hydrant
        with `origin` `COMPLAINT_AUTO` and `status` `PLANNED` or `IN_PROGRESS`,
        then the system auto-creates a targeted sequence."
        PRD §3.5: "Every complaint counted in the cluster is moved to `LINKED`
        with its `flush_sequence_id` pointing at the new sequence, and the
        hydrant's `targeted_flush_pending` is set to true."

        Design: Difficulty/transitive_cascade/complaint_cluster_cascade
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-100"}
        )
        c1 = create_open_complaint(hydrant["id"], category="DISCOLORED_WATER")
        c2 = create_open_complaint(hydrant["id"], category="DISCOLORED_WATER")
        third_resp = api.create_complaint(
            {"hydrant_id": hydrant["id"], "category": "DISCOLORED_WATER"}, OP1
        )
        c3 = validate_success(third_resp, expected_status=201)
        assert c3["status"] == "LINKED", (
            f"the triggering complaint must itself be LINKED, got {c3['status']}"
        )
        auto_seq_id = c3["flush_sequence_id"]

        for complaint_id in (c1["id"], c2["id"]):
            after = validate_success(api.get_complaint(complaint_id, OP1))
            assert after["status"] == "LINKED"
            assert after["flush_sequence_id"] == auto_seq_id

        auto_seq = validate_success(api.get_flush_sequence(auto_seq_id, OP1))
        assert_flush_origin_and_status(auto_seq)
        assert get_hydrant(hydrant["id"])["targeted_flush_pending"] is True

    def test_complaint_cluster_cascade_auto_sequence_window(self, api):
        """PRD §3.5: "The auto-created sequence has `origin` `COMPLAINT_AUTO`,
        takes `program_id`, `zone_id`, and `hydrant_id` from the hydrant,
        starts in `PLANNED` status, has `window_start` set 24 hours after the
        current logical clock and `window_end` set 28 hours after (a four-hour
        window), and is initialized with a single step: `step_index` 1,
        `valve_tag` `MAIN`, `action` `OPEN`, `status` `PENDING`."

        Design: Difficulty/transitive_cascade/complaint_cluster_cascade
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-100"}
        )
        complaints = setup_complaint_cluster(program, zone, hydrant, count=3)
        auto_seq_id = complaints[-1]["flush_sequence_id"]

        auto_seq = validate_success(api.get_flush_sequence(auto_seq_id, OP1))
        assert_flush_origin_and_status(auto_seq)
        # Clock never touched: default 2026-08-01T00:00:00Z.
        assert _parse(auto_seq["window_start"]) == _parse("2026-08-01T00:00:00Z") + timedelta(hours=24)
        assert _parse(auto_seq["window_end"]) == _parse("2026-08-01T00:00:00Z") + timedelta(hours=28)
        assert auto_seq["hydrant_id"] == hydrant["id"]
        assert auto_seq["program_id"] == program["id"]
        assert auto_seq["zone_id"] == zone["id"]


def assert_flush_origin_and_status(seq):
    assert seq["origin"] == "COMPLAINT_AUTO", (
        f"auto-created sequence must carry origin COMPLAINT_AUTO, got {seq['origin']}"
    )
    assert seq["status"] == "PLANNED", (
        f"auto-created sequence must start PLANNED, got {seq['status']}"
    )


class TestClusterBoundary:
    def test_complaint_cluster_exactly_three_second_does_not_trigger(self, api):
        """PRD §3.5: "The boundary is pinned: the third qualifying complaint
        triggers the auto-creation; the second does not."
        PRD §3.5: "When any of the cluster conditions fails — fewer than three
        complaints, hydrant out of service, or a targeted sequence already in
        flight — the new complaint stays `OPEN` and nothing else changes."

        Design: Difficulty/boundary_precision_check/complaint_cluster_exactly_three_triggers
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-100"}
        )
        create_open_complaint(hydrant["id"], category="DISCOLORED_WATER")
        c2 = create_open_complaint(hydrant["id"], category="DISCOLORED_WATER")
        assert c2["status"] == "OPEN", (
            f"the second complaint must stay OPEN, got {c2['status']}"
        )
        seqs, meta = validate_paginated(
            api.list_flush_sequences(OP1, params={"hydrant_id": hydrant["id"]})
        )
        assert meta["total_count"] == 0, (
            f"no auto sequence may exist after two complaints, got {meta['total_count']}"
        )

    def test_complaint_cluster_exactly_three_third_triggers(self, api):
        """PRD §3.5: "The boundary is pinned: the third qualifying complaint
        triggers the auto-creation; the second does not."
        PRD §3.5: "Count the complaints on the same hydrant whose `category` is
        `DISCOLORED_WATER`, whose `status` is either `OPEN` or `LINKED`, and
        whose `created_at` falls within the rolling 72-hour window ending at
        the current logical clock — both bounds inclusive."

        Design: Difficulty/boundary_precision_check/complaint_cluster_exactly_three_triggers
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-100"}
        )
        create_open_complaint(hydrant["id"], category="DISCOLORED_WATER")
        create_open_complaint(hydrant["id"], category="DISCOLORED_WATER")
        c3 = create_open_complaint(hydrant["id"], category="DISCOLORED_WATER")
        assert c3["status"] == "LINKED"

        seqs, meta = validate_paginated(
            api.list_flush_sequences(OP1, params={"hydrant_id": hydrant["id"]})
        )
        assert meta["total_count"] == 1, (
            f"exactly one auto sequence must exist after three complaints, "
            f"got {meta['total_count']}"
        )
        assert seqs[0]["origin"] == "COMPLAINT_AUTO"
        assert seqs[0]["status"] == "PLANNED"


class TestComplaintSchema:
    def test_complaint_create_invalid_enum_rejected(self, api):
        """PRD §2.10: "Endpoints with a request body enforce strict schema
        validation: required fields must be present, types must be valid, enum
        values must come from the declared set, and unknown fields are
        rejected."
        PRD §3.5: "the payload supplies the `hydrant_id`, a `category` of
        `DISCOLORED_WATER`, `ODOR`, `TASTE`, or `PRESSURE`, and an optional
        `description` (default empty)."

        Design: Corner/validations/complaint_create_invalid_enum_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        resp = api.create_complaint(
            {"hydrant_id": hydrant["id"], "category": "NOISE"}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(api.list_complaints(OP1))
        assert meta["total_count"] == 0, "rejected create must not persist a complaint"


class TestManualLinkIntegrity:
    def test_complaint_link_hydrant_mismatch_rejected(self, api):
        """PRD §3.5: "The complaint must be `OPEN` (else
        `ERR_COMPLAINT_NOT_LINKABLE`), the target sequence must be `PLANNED`
        (else `ERR_SEQUENCE_NOT_PLANNED`), and the sequence's `hydrant_id` must
        equal the complaint's `hydrant_id` (else `ERR_LINK_HYDRANT_MISMATCH`,
        HTTP 422)."

        Design: Corner/validations/complaint_link_hydrant_mismatch_rejected
        """
        program = create_program()
        zone = create_zone()
        h1 = create_hydrant(program["id"], zone["id"], hydrant_number="H-1")
        h2 = create_hydrant(program["id"], zone["id"], hydrant_number="H-2")
        seq = create_planned_sequence(program["id"], zone["id"], h2["id"],
                                      window_start="2026-08-03T10:00:00Z",
                                      window_end="2026-08-03T11:00:00Z")
        complaint = create_open_complaint(h1["id"], category="ODOR")

        resp = api.link_complaint(complaint["id"], {"flush_sequence_id": seq["id"]}, OP1)
        validate_error(resp, ApiErrorId.ERR_LINK_HYDRANT_MISMATCH, 422)

        after = validate_success(api.get_complaint(complaint["id"], OP1))
        assert after["status"] == "OPEN", "rejected link must leave the complaint OPEN"


class TestClosePathGuards:
    def test_complaint_close_paths_guarded(self, api):
        """PRD §3.5: "A manual close with `outcome` `RESOLVED` requires the
        complaint to be `LINKED` and its linked sequence to be `COMPLETED`; a
        premature close is rejected with `ERR_LINKED_SEQUENCE_NOT_COMPLETED`."
        PRD §3.5: "A manual close with `outcome` `DISMISSED` is only valid from
        `OPEN`; attempting to dismiss from `LINKED` or from any terminal state
        is rejected with `ERR_COMPLAINT_NOT_CLOSABLE`."

        Design: Corner/validations/complaint_close_paths_guarded
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_planned_sequence(program["id"], zone["id"], hydrant["id"],
                                      window_start="2026-08-03T10:00:00Z",
                                      window_end="2026-08-03T11:00:00Z")
        complaint = create_open_complaint(hydrant["id"], category="ODOR")
        linked = validate_success(
            api.link_complaint(complaint["id"], {"flush_sequence_id": seq["id"]}, OP1)
        )
        assert linked["status"] == "LINKED"

        resp_resolved = api.close_complaint(complaint["id"], {"outcome": "RESOLVED"}, SUP1)
        validate_error(resp_resolved, ApiErrorId.ERR_LINKED_SEQUENCE_NOT_COMPLETED, 409)

        resp_dismissed = api.close_complaint(complaint["id"], {"outcome": "DISMISSED"}, SUP1)
        validate_error(resp_dismissed, ApiErrorId.ERR_COMPLAINT_NOT_CLOSABLE, 409)

        after = validate_success(api.get_complaint(complaint["id"], OP1))
        assert after["status"] == "LINKED", (
            "both rejected closes must leave the complaint LINKED"
        )
