"""Digitization lab: tickets, workstation scheduling buffer, QC rework cap, derivative
assets, auto-assign selector, and the preservation priority score."""
from test_helpers import (
    api_client, validate_paginated,
    validate_success, validate_error, ApiErrorId,
    create_asset, create_workstation, create_digitization_ticket,
    drive_ticket_to_qc, set_clock,
    create_digitization_ticket_payload, create_workstation_payload,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
LAB = TEST_USERS["lab_technician_headers"]


def _beta_asset(title="T"):
    return create_asset(title=title, media_type="VIDEO", format_class="BETACAM_SP")


def test_qc_pass_creates_self_referential_derivative(api):
    """PRD §3.9: "Passing — optionally annotated with `qc_notes` — requires `QC_REVIEW`
    (otherwise `ERR_TICKET_NOT_IN_QC`, HTTP 409), moves the ticket to the terminal
    `COMPLETED` state, and creates the derivative asset: its `source_asset_id` set to
    the original asset's `id`, its `format_class` set to the ticket's `output_format`,
    its `ingest_batch_id` set to the original's batch — a system exception that is
    permitted even though the batch is `FINALIZED` — its `catalog_status` starting at
    `METADATA_DRAFT`, and its `storage_tier` at `ONLINE`."

    Design: Corner/entities/digitization_qc_pass_creates_self_referential_derivative
    """
    ws = create_workstation(["BETACAM_SP"])
    asset = _beta_asset()
    ticket = create_digitization_ticket(asset["id"])  # slot at the default clock
    drive_ticket_to_qc(ticket["id"], ws["id"])

    passed = validate_success(api.qc_pass_digitization_ticket(
        ticket["id"], {"qc_notes": "clean"}, LAB), 200)
    assert passed["status"] == "COMPLETED"

    derivatives, meta = validate_paginated(api.list_assets(
        ARCHIVIST, params={"source_asset_id": asset["id"]}))
    assert len(derivatives) == 1
    deriv = derivatives[0]
    assert deriv["format_class"] == "PRORES_FILE"
    assert deriv["catalog_status"] == "METADATA_DRAFT"
    assert deriv["storage_tier"] == "ONLINE"
    assert deriv["ingest_batch_id"] == asset["ingest_batch_id"]
    assert deriv["source_asset_id"] == asset["id"]


def test_qc_rework_cap_forces_terminal_qc_failed(api):
    """PRD §3.9: "While `rework_count` is below the cap of 2, a failure loops the ticket
    back to `QUEUED`, increments `rework_count` by one, and clears `workstation_id` so
    the slot is freed; when `rework_count` has already reached 2, the next failure
    instead moves the ticket to the terminal `QC_FAILED` state and likewise clears
    `workstation_id`."

    Design: Corner/cross_cutting_layers/qc_rework_cap_forces_terminal_qc_failed
    """
    ws = create_workstation(["BETACAM_SP"])
    asset = _beta_asset()
    ticket = create_digitization_ticket(asset["id"])
    tid = ticket["id"]

    for expected_count in (1, 2):
        drive_ticket_to_qc(tid, ws["id"])
        failed = validate_success(api.qc_fail_digitization_ticket(
            tid, {"qc_notes": "bad"}, LAB), 200)
        assert failed["status"] == "QUEUED"
        assert failed["rework_count"] == expected_count
        assert failed["workstation_id"] is None

    drive_ticket_to_qc(tid, ws["id"])
    terminal = validate_success(api.qc_fail_digitization_ticket(
        tid, {"qc_notes": "still bad"}, LAB), 200)
    assert terminal["status"] == "QC_FAILED"
    assert terminal["workstation_id"] is None


def test_ticket_format_obsolescence_and_due_gates(api):
    """PRD §3.9: "a ticket for any other format is rejected with
    `ERR_FORMAT_NOT_OBSOLETE` (HTTP 422)".
    PRD §3.9: "The asset's `format_class` must appear in the workstation's
    `supported_formats` (otherwise `ERR_WORKSTATION_FORMAT_UNSUPPORTED`, HTTP 422)."
    PRD §3.9: "Starting the work requires the ticket to be `ASSIGNED` (otherwise
    `ERR_TICKET_NOT_ASSIGNED`, HTTP 409) and the logical clock to have reached
    `scheduled_start` (otherwise `ERR_TICKET_NOT_DUE`, HTTP 422); it moves the ticket to
    `DIGITIZING`."

    Design: Corner/errors/ticket_format_and_obsolescence_gates
    """
    ws_vhs = create_workstation(["VHS"])
    digital = create_asset(title="D", format_class="DIGITAL_FILE")
    beta = _beta_asset(title="B")
    t1 = create_digitization_ticket(
        beta["id"], scheduled_start="2030-01-01T10:00:00Z",
        scheduled_end="2030-01-01T12:00:00Z")

    res1 = api.create_digitization_ticket(
        create_digitization_ticket_payload(digital["id"]), ARCHIVIST)
    validate_error(res1, ApiErrorId.ERR_FORMAT_NOT_OBSOLETE)

    res2 = api.assign_digitization_ticket(t1["id"], {"workstation_id": ws_vhs["id"]}, LAB)
    validate_error(res2, ApiErrorId.ERR_WORKSTATION_FORMAT_UNSUPPORTED)

    ws_beta = create_workstation(["BETACAM_SP"])
    validate_success(api.assign_digitization_ticket(
        t1["id"], {"workstation_id": ws_beta["id"]}, LAB), 200)
    res3 = api.start_digitization_ticket(t1["id"], LAB)
    validate_error(res3, ApiErrorId.ERR_TICKET_NOT_DUE)


# ─── workstation buffered gap (Difficulty x2) ─────────

def test_workstation_buffer_gap_zero_conflicts_gap_30_allowed(api):
    """PRD §3.9: "for every ticket on the workstation in `ASSIGNED` or `DIGITIZING`, the
    new slot must end at least 30 minutes before the existing slot's start or start at
    least 30 minutes after the existing slot's end — a gap of exactly 30 minutes is
    allowed, while touching adjacency is a conflict rejected with
    `ERR_WORKSTATION_SCHEDULE_CONFLICT` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/workstation_buffered_gap_conflict
    """
    ws = create_workstation(["BETACAM_SP"])
    a1 = _beta_asset("A1")
    a2 = _beta_asset("A2")
    t1 = create_digitization_ticket(a1["id"], scheduled_start="2030-01-01T10:00:00Z",
                                    scheduled_end="2030-01-01T12:00:00Z")
    validate_success(api.assign_digitization_ticket(
        t1["id"], {"workstation_id": ws["id"]}, LAB), 200)

    t2 = create_digitization_ticket(a2["id"], scheduled_start="2030-01-01T12:00:00Z",
                                    scheduled_end="2030-01-01T14:00:00Z")
    res = api.assign_digitization_ticket(t2["id"], {"workstation_id": ws["id"]}, LAB)
    validate_error(res, ApiErrorId.ERR_WORKSTATION_SCHEDULE_CONFLICT)

    t3 = create_digitization_ticket(a2["id"], scheduled_start="2030-01-01T12:30:00Z",
                                    scheduled_end="2030-01-01T14:30:00Z")
    assigned = validate_success(api.assign_digitization_ticket(
        t3["id"], {"workstation_id": ws["id"]}, LAB), 200)
    assert assigned["status"] == "ASSIGNED"


def test_workstation_buffer_gap_29_minutes_conflicts(api):
    """PRD §3.9: "the new slot must end at least 30 minutes before the existing slot's
    start or start at least 30 minutes after the existing slot's end — a gap of exactly
    30 minutes is allowed, while touching adjacency is a conflict rejected with
    `ERR_WORKSTATION_SCHEDULE_CONFLICT` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/workstation_buffered_gap_conflict
    """
    ws = create_workstation(["BETACAM_SP"])
    a1 = _beta_asset("A1")
    a2 = _beta_asset("A2")
    t1 = create_digitization_ticket(a1["id"], scheduled_start="2030-01-01T10:00:00Z",
                                    scheduled_end="2030-01-01T12:00:00Z")
    validate_success(api.assign_digitization_ticket(
        t1["id"], {"workstation_id": ws["id"]}, LAB), 200)

    t2 = create_digitization_ticket(a2["id"], scheduled_start="2030-01-01T12:29:00Z",
                                    scheduled_end="2030-01-01T14:29:00Z")
    res = api.assign_digitization_ticket(t2["id"], {"workstation_id": ws["id"]}, LAB)
    validate_error(res, ApiErrorId.ERR_WORKSTATION_SCHEDULE_CONFLICT)


def test_workstation_maintenance_blocked_while_busy(api):
    """PRD §3.9: "Taking it down to `MAINTENANCE` is blocked while any ticket on the
    station is `ASSIGNED` or `DIGITIZING` (`ERR_WORKSTATION_BUSY`, HTTP 409); bringing
    it back to `ACTIVE` carries no precondition."
    PRD §3.9: "An `ArchivistLead` may cancel a ticket while it is `QUEUED` or `ASSIGNED`
    — from any other state, `ERR_TICKET_NOT_CANCELLABLE` (HTTP 409)".

    Design: Corner/cross_cutting_layers/workstation_maintenance_blocked_while_busy
    """
    ws = create_workstation(["BETACAM_SP"])
    asset = _beta_asset()
    ticket = create_digitization_ticket(asset["id"])
    validate_success(api.assign_digitization_ticket(
        ticket["id"], {"workstation_id": ws["id"]}, LAB), 200)

    res = api.patch_workstation(ws["id"], {"status": "MAINTENANCE"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_WORKSTATION_BUSY)

    validate_success(api.cancel_digitization_ticket(ticket["id"], ARCHIVIST), 200)
    patched = validate_success(api.patch_workstation(
        ws["id"], {"status": "MAINTENANCE"}, ADMIN), 200)
    assert patched["status"] == "MAINTENANCE"


def test_auto_assign_ranking_tiebreak_and_empty_pool(api):
    """PRD §3.9: "the auto-assigner takes a `workstation_id`, selects among `QUEUED`
    tickets whose asset format the station supports the one with the highest
    `priority_score` — ties broken toward the earliest `created_at` — and books the slot
    as now through now plus four hours, setting `scheduled_start` and `scheduled_end`
    accordingly."
    PRD §3.9: "When no eligible ticket exists for the station, the auto-assigner is
    rejected with `ERR_NO_ELIGIBLE_TICKET` (HTTP 409)."

    Design: Corner/cross_cutting_layers/auto_assign_selector_ranking_tiebreak_and_empty_pool
    """
    ws1 = create_workstation(["BETACAM_SP", "VHS"])
    ws2 = create_workstation(["UMATIC"])
    a_early = _beta_asset("Early")
    a_late = _beta_asset("Late")
    t_early = create_digitization_ticket(a_early["id"])
    set_clock("2026-08-01T00:00:01Z")
    t_late = create_digitization_ticket(a_late["id"])
    set_clock("2026-08-01T00:00:00Z")
    # Both assets are 0 years old with zero deliveries -> both scores are 0.

    picked = validate_success(api.auto_assign_digitization_ticket(
        {"workstation_id": ws1["id"]}, LAB), 200)
    assert picked["id"] == t_early["id"], (
        "equal priority scores must tie-break toward the earliest created_at")
    assert picked["status"] == "ASSIGNED"
    assert picked["workstation_id"] == ws1["id"]
    assert picked["scheduled_start"].startswith("2026-08-01T00:00:00")
    assert picked["scheduled_end"].startswith("2026-08-01T04:00:00")

    res = api.auto_assign_digitization_ticket({"workstation_id": ws2["id"]}, LAB)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_TICKET)


def test_priority_score_decay_times_age(api):
    """PRD §3.9: "The score is the decay risk of the asset's `format_class` times the
    age in years, plus ten times the delivered count. Decay risk by format: `BETACAM_SP`
    90, `UMATIC` 85, `VHS` 70, `FILM_16MM` 95, `AUDIO_REEL` 80, `AUDIO_DAT` 75,
    `DIGITAL_FILE` 10, `PRORES_FILE` 5."
    PRD §3.9: "The asset's age in days is the elapsed logical time since its
    `created_at`, truncated down to whole days; the age in years truncates those days
    down to whole 365-day years."
    (BETACAM_SP, created 2026-08-01, read 2027-08-01: 365 days -> 1 year -> 90 x 1 + 0.)

    Design: Corner/calculations/priority_score_decay_times_age
    """
    asset = _beta_asset()
    set_clock("2027-08-01T00:00:00Z")
    ticket = validate_success(api.create_digitization_ticket(
        create_digitization_ticket_payload(
            asset["id"], scheduled_start="2027-08-02T00:00:00Z",
            scheduled_end="2027-08-02T04:00:00Z"),
        ARCHIVIST), 201)
    assert ticket["priority_score"] == 90
