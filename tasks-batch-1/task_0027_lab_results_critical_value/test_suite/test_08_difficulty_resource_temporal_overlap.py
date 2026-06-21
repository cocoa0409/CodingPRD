"""Difficulty Rule 8 — resource_temporal_overlap.

Instrument runs use half-open [start, end) windows widened by qc_buffer_minutes
on both sides (different resource: Instrument). Phlebotomist collections use
point-collision against a five-minute window (different resource: Phlebotomist).
"""
from test_helpers import (
    accession_specimen,
    api_client,
    ApiErrorId,
    bootstrap_actors,
    collect_specimen,
    create_instrument_run_payload,
    create_order,
    create_specimen,
    get_success_data,
    register_patient,
    set_clock,
    transit_specimen,
    validate_error,
    validate_success,
)


class TestInstrumentRunHalfOpenOverlapWithQcBuffer:
    """PRD §3.4: existing run [A, B) is widened to [A − qc_buffer, B + qc_buffer)
    for overlap purposes; the new run's [scheduled_start, scheduled_end) must be
    disjoint.
    """

    def test_new_run_starting_at_existing_end_conflicts_due_to_qc_buffer(self, api):
        """PRD §3.4: "an existing run with interval `[A, B)` is treated, for overlap
        purposes, as occupying `[A − qc_buffer_minutes, B + qc_buffer_minutes)`, and
        the proposed run's `[scheduled_start, scheduled_end)` must be disjoint from
        every such buffered window for every existing run in `SCHEDULED`, `IN_PROGRESS`,
        or `COMPLETED`. A conflict is rejected with `ERR_INSTRUMENT_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/instrument_qc_buffer_half_open_overlap_with_5min_pad
        """
        actors = bootstrap_actors(
            clock="2026-05-28T08:00:00Z", panels=["CMP"], qc_buffer_minutes=5,
        )
        # Build two specimens on separate orders, both ACCESSIONED — runs need
        # specimen.status == ACCESSIONED at scheduling time (PRD §3.4).
        pat_a = register_patient(actors.lt_id, mrn="MRN-T1A000", date_of_birth="1980-01-01")
        pat_b = register_patient(actors.lt_id, mrn="MRN-T1B000", date_of_birth="1980-01-01")
        ord_a = create_order(actors, pat_a["id"], panel_code="CMP", priority="ROUTINE")
        ord_b = create_order(actors, pat_b["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, ord_a["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp2 = create_specimen(actors, ord_b["id"], container_code="GREEN")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])
        accession_specimen(actors, sp1["id"])
        accession_specimen(actors, sp2["id"])

        # Existing run on sp1: [09:00, 09:30). Buffered for overlap: [08:55, 09:35).
        get_success_data(api_client.create_instrument_run(
            create_instrument_run_payload(
                actors.instrument_id, sp1["id"],
                "2026-05-28T09:00:00Z", "2026-05-28T09:30:00Z",
            ),
            actors.lt_headers,
        ))

        # New run [09:30, 09:50): scheduled_start 09:30 lies inside the buffered
        # window [08:55, 09:35), so the proposed window overlaps and MUST be
        # rejected with ERR_INSTRUMENT_SLOT_CONFLICT.
        res = api_client.create_instrument_run(
            create_instrument_run_payload(
                actors.instrument_id, sp2["id"],
                "2026-05-28T09:30:00Z", "2026-05-28T09:50:00Z",
            ),
            actors.lt_headers,
        )
        validate_error(res, ApiErrorId.ERR_INSTRUMENT_SLOT_CONFLICT)

    def test_new_run_well_outside_buffered_window_succeeds(self, api):
        """PRD §3.4: "the proposed run's `[scheduled_start, scheduled_end)` must be disjoint from every such buffered window for every existing run in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED`."

        Design: Difficulty/resource_temporal_overlap/instrument_qc_buffer_half_open_overlap_with_5min_pad
        """
        actors = bootstrap_actors(
            clock="2026-05-28T08:00:00Z", panels=["CMP"], qc_buffer_minutes=5,
        )
        pat_a = register_patient(actors.lt_id, mrn="MRN-T1C000", date_of_birth="1980-01-01")
        pat_b = register_patient(actors.lt_id, mrn="MRN-T1D000", date_of_birth="1980-01-01")
        ord_a = create_order(actors, pat_a["id"], panel_code="CMP", priority="ROUTINE")
        ord_b = create_order(actors, pat_b["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, ord_a["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp2 = create_specimen(actors, ord_b["id"], container_code="GREEN")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])
        accession_specimen(actors, sp1["id"])
        accession_specimen(actors, sp2["id"])

        # Existing run on sp1: [09:00, 09:30). Buffered: [08:55, 09:35).
        get_success_data(api_client.create_instrument_run(
            create_instrument_run_payload(
                actors.instrument_id, sp1["id"],
                "2026-05-28T09:00:00Z", "2026-05-28T09:30:00Z",
            ),
            actors.lt_headers,
        ))

        # New run [09:36, 09:56) — strictly past the buffered window's end (09:35).
        res = api_client.create_instrument_run(
            create_instrument_run_payload(
                actors.instrument_id, sp2["id"],
                "2026-05-28T09:36:00Z", "2026-05-28T09:56:00Z",
            ),
            actors.lt_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["instrument_id"] == actors.instrument_id
        assert data["status"] == "SCHEDULED"

    def test_overlap_check_is_per_instrument(self, api):
        """PRD §3.4: "This check is per-instrument: two runs on different instruments
        do not interact regardless of their windows."

        Design: Difficulty/resource_temporal_overlap/instrument_qc_buffer_half_open_overlap_with_5min_pad
        """
        actors = bootstrap_actors(
            clock="2026-05-28T08:00:00Z", panels=["CMP"], qc_buffer_minutes=5,
        )
        # Register a SECOND instrument.
        from test_helpers import register_instrument
        inst2 = register_instrument(
            actors.director_id, analyte_panels_supported=["CMP"], qc_buffer_minutes=5,
        )

        pat_a = register_patient(actors.lt_id, mrn="MRN-T1E000", date_of_birth="1980-01-01")
        pat_b = register_patient(actors.lt_id, mrn="MRN-T1F000", date_of_birth="1980-01-01")
        ord_a = create_order(actors, pat_a["id"], panel_code="CMP", priority="ROUTINE")
        ord_b = create_order(actors, pat_b["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, ord_a["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp2 = create_specimen(actors, ord_b["id"], container_code="GREEN")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])
        accession_specimen(actors, sp1["id"])
        accession_specimen(actors, sp2["id"])

        # Run on instrument 1 at [09:00, 09:30).
        get_success_data(api_client.create_instrument_run(
            create_instrument_run_payload(
                actors.instrument_id, sp1["id"],
                "2026-05-28T09:00:00Z", "2026-05-28T09:30:00Z",
            ),
            actors.lt_headers,
        ))
        # Identical window on instrument 2 — MUST succeed (different instrument).
        res = api_client.create_instrument_run(
            create_instrument_run_payload(
                inst2["id"], sp2["id"],
                "2026-05-28T09:00:00Z", "2026-05-28T09:30:00Z",
            ),
            actors.lt_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["instrument_id"] == inst2["id"]


class TestPhlebotomistCollectionWithinFiveMinutesRejected:
    """PRD §3.3: collection by the same Phlebotomist within five minutes of any
    non-rejected prior collection is rejected with ERR_COLLECTOR_BUSY.
    """

    def test_collect_within_five_minutes_returns_collector_busy(self, api):
        """PRD §3.3: "Collection by the same `Phlebotomist` is rate-limited: if any
        other non-rejected specimen of theirs (in `COLLECTED`, `IN_TRANSIT`, or
        `ACCESSIONED`) was collected within five minutes of the new attempt, the new
        collection is rejected with `ERR_COLLECTOR_BUSY`."

        Design: Difficulty/resource_temporal_overlap/phlebotomist_point_collision_within_5min_window
        """
        actors = bootstrap_actors(
            clock="2026-05-28T08:00:00Z", with_instrument=False,
        )
        pat_a = register_patient(actors.lt_id, mrn="MRN-T2A000", date_of_birth="1980-01-01")
        pat_b = register_patient(actors.lt_id, mrn="MRN-T2B000", date_of_birth="1980-01-01")
        ord_a = create_order(actors, pat_a["id"], panel_code="CMP", priority="ROUTINE")
        ord_b = create_order(actors, pat_b["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, ord_a["id"], container_code="GREEN")
        sp2 = create_specimen(actors, ord_b["id"], container_code="GREEN")
        # Collect sp1 at 08:00 (pinned by clock).
        collect_specimen(actors, sp1["id"])
        # Advance to 08:04 — within the 5-minute window.
        set_clock("2026-05-28T08:04:00Z", actors.director_id)
        res = api_client.collect_specimen(sp2["id"], actors.phleb_headers)
        validate_error(res, ApiErrorId.ERR_COLLECTOR_BUSY)
        # sp2 must remain DRAFT.
        sp2_after = get_success_data(api_client.get_specimen(sp2["id"], actors.lt_headers))
        assert sp2_after["status"] == "DRAFT", (
            f"sp2 must remain DRAFT after rejected collect; got {sp2_after['status']!r}"
        )

    def test_collect_after_six_minutes_succeeds(self, api):
        """PRD §3.3: "The semantics are point-collision against a buffered window — the new specimen's intended collection moment must fall outside a five-minute window around every prior non-rejected specimen of the same collector."

        Design: Difficulty/resource_temporal_overlap/phlebotomist_point_collision_within_5min_window
        """
        actors = bootstrap_actors(
            clock="2026-05-28T08:00:00Z", with_instrument=False,
        )
        pat_a = register_patient(actors.lt_id, mrn="MRN-T2C000", date_of_birth="1980-01-01")
        pat_b = register_patient(actors.lt_id, mrn="MRN-T2D000", date_of_birth="1980-01-01")
        ord_a = create_order(actors, pat_a["id"], panel_code="CMP", priority="ROUTINE")
        ord_b = create_order(actors, pat_b["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, ord_a["id"], container_code="GREEN")
        sp2 = create_specimen(actors, ord_b["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        # Advance to 08:06 — strictly outside the 5-minute window.
        set_clock("2026-05-28T08:06:00Z", actors.director_id)
        res = api_client.collect_specimen(sp2["id"], actors.phleb_headers)
        data = validate_success(res)
        assert data["status"] == "COLLECTED"
