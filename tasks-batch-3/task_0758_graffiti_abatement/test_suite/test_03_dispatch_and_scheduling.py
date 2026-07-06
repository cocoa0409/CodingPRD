"""Crew dispatch gating: availability, certification, scheduling and buffer conflicts,
validation precedence, and the immediate dispatch cascade.

Queue A (Difficulty): cross_entity_state_dependency, priority_pair_validation_conflict,
resource_temporal_overlap.
Queue B (Corner): validations (scheduled_end order), consistency_model (immediate dispatch).
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    register_owner, register_site, register_crew, register_material,
    file_report, triage, material_lines, make_crew_lead_headers,
    create_site_payload, create_report_payload, create_work_order_payload,
    create_photo_payload,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]

W_0912 = ("2026-03-05T09:00:00Z", "2026-03-05T12:00:00Z")
W_1416 = ("2026-03-05T14:00:00Z", "2026-03-05T16:00:00Z")
W_1113 = ("2026-03-05T11:00:00Z", "2026-03-05T13:00:00Z")
W_1214 = ("2026-03-05T12:00:00Z", "2026-03-05T14:00:00Z")
W_0911 = ("2026-03-05T09:00:00Z", "2026-03-05T11:00:00Z")
W_2022 = ("2026-03-05T20:00:00Z", "2026-03-05T22:00:00Z")


def _triaged_report(api, site_id, **over):
    rep = file_report(api, site_id, **over)
    triage(api, rep["id"])
    return rep["id"]


def _crew_mid_job(api, site_id, crew_id):
    """Dispatch + start a first (material-free) work order so the crew is DISPATCHED."""
    rep1 = _triaged_report(api, site_id, description="job1")
    wo1 = validate_success(api.create_work_order(create_work_order_payload(
        rep1, crew_id, estimated_labor_hours=2.0,
        scheduled_start=W_0912[0], scheduled_end=W_0912[1]), COORD), 201)
    ch = make_crew_lead_headers(crew_id)
    validate_success(api.upload_photo(wo1["id"], create_photo_payload("BEFORE", "http://p/b.jpg"), ch), 201)
    validate_success(api.start_work_order(wo1["id"], ch), 200)
    return wo1["id"]


# --------------------------------------------------------------------------
# cross_entity_state_dependency / dispatch_requires_crew_available
# --------------------------------------------------------------------------
def test_dispatch_rejected_when_crew_already_dispatched(api):
    """PRD §3.3: "The chosen crew must be `AVAILABLE`; a crew already `DISPATCHED` on another job
    causes `ERR_CREW_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_crew_available
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew = register_crew(api)
    _crew_mid_job(api, site["id"], crew["id"])
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    resp = api.create_work_order(create_work_order_payload(
        rep2, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_1416[0], scheduled_end=W_1416[1]), COORD)
    validate_error(resp, ApiErrorId.ERR_CREW_UNAVAILABLE)


def test_dispatch_succeeds_once_crew_freed(api):
    """PRD §3.3: "A crew's `status` is `AVAILABLE` when idle and `DISPATCHED` while it is executing
    an in-progress work order; it starts `AVAILABLE`."
    PRD §3.4: "it frees the crew `DISPATCHED → AVAILABLE`".

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_crew_available
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew = register_crew(api)
    wo1_id = _crew_mid_job(api, site["id"], crew["id"])
    ch = make_crew_lead_headers(crew["id"])
    # Finish the first job so the crew returns to AVAILABLE.
    validate_success(api.upload_photo(wo1_id, create_photo_payload("AFTER", "http://p/a.jpg"), ch), 201)
    validate_success(api.complete_work_order(wo1_id, {"actual_labor_hours": 2.0}, ch), 200)
    freed = validate_success(api.get_crew(crew["id"], COORD), 200)
    assert freed["status"] == "AVAILABLE"
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    wo2 = validate_success(api.create_work_order(create_work_order_payload(
        rep2, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_1416[0], scheduled_end=W_1416[1]), COORD), 201)
    assert wo2["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / dispatch_crew_unavailable_beats_insufficient_material
# --------------------------------------------------------------------------
def test_crew_unavailable_beats_insufficient_material(api):
    """PRD §2.10: "Only after all six of these pass does the system evaluate the operation-specific
    business rules described in §3 — crew availability, offensive certification, scheduling conflicts,
    photo prerequisites, material sufficiency, cure-window timing, the site-version check, and the rest."
    PRD §3.3: "The chosen crew must be `AVAILABLE`; a crew already `DISPATCHED` on another job causes
    `ERR_CREW_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_crew_unavailable_beats_insufficient_material
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew = register_crew(api)
    material = register_material(api, name="Scarce", unit_cost_cents=1000, quantity_available=1.0)
    _crew_mid_job(api, site["id"], crew["id"])
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    resp = api.create_work_order(create_work_order_payload(
        rep2, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_1416[0], scheduled_end=W_1416[1],
        material_lines=material_lines(material["id"], 5.0)), COORD)
    # Crew-availability (listed first) wins over material-sufficiency (listed later).
    validate_error(resp, ApiErrorId.ERR_CREW_UNAVAILABLE)


def test_crew_unavailable_precedence_leaves_material_untouched(api):
    """PRD §3.3: "It creates one **MaterialReservation** per `material_lines` entry ... for each, the
    reserved quantity is moved out of the material's `quantity_available` and into its
    `quantity_reserved`, leaving the material's total holdings unchanged."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_crew_unavailable_beats_insufficient_material
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew = register_crew(api)
    material = register_material(api, name="Scarce", unit_cost_cents=1000, quantity_available=1.0)
    _crew_mid_job(api, site["id"], crew["id"])
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    api.create_work_order(create_work_order_payload(
        rep2, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_1416[0], scheduled_end=W_1416[1],
        material_lines=material_lines(material["id"], 5.0)), COORD)
    # The rejected dispatch reserved nothing: stock is unchanged.
    mat = validate_success(api.get_material(material["id"], COORD), 200)
    assert mat["quantity_available"] == 1.0
    assert mat["quantity_reserved"] == 0.0


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / dispatch_offensive_uncertified_beats_schedule_conflict
# --------------------------------------------------------------------------
def _uncertified_crew_with_scheduled_wo(api, site_id):
    crew = register_crew(api, crew_type="CONTRACTOR", is_offensive_certified=False)
    rep1 = _triaged_report(api, site_id, severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job1")
    validate_success(api.create_work_order(create_work_order_payload(
        rep1, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_0912[0], scheduled_end=W_0912[1]), COORD), 201)
    return crew["id"]


def test_offensive_uncertified_beats_schedule_conflict(api):
    """PRD §2.10: "Only after all six of these pass does the system evaluate the operation-specific
    business rules described in §3 — crew availability, offensive certification, scheduling conflicts,
    photo prerequisites, material sufficiency, cure-window timing, the site-version check, and the rest."
    PRD §3.3: "If the report's `is_offensive` is true, the crew's `is_offensive_certified` must also be
    true, or the dispatch is rejected with `ERR_CREW_NOT_CERTIFIED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_offensive_uncertified_beats_schedule_conflict
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew_id = _uncertified_crew_with_scheduled_wo(api, site["id"])
    rep2 = _triaged_report(api, site["id"], severity="SEVERE", surface_type="WALL",
                           is_offensive=True, description="hateful")
    resp = api.create_work_order(create_work_order_payload(
        rep2, crew_id, estimated_labor_hours=2.0,
        scheduled_start=W_1113[0], scheduled_end=W_1113[1]), COORD)
    # Offensive certification (listed before scheduling conflicts) wins.
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_CERTIFIED)


def test_offensive_uncertified_precedence_leaves_report_triaged(api):
    """PRD §3.3: "a successful dispatch advances the report `TRIAGED → DISPATCHED` and creates a
    **WorkOrder** in `SCHEDULED` status."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_offensive_uncertified_beats_schedule_conflict
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew_id = _uncertified_crew_with_scheduled_wo(api, site["id"])
    rep2 = _triaged_report(api, site["id"], severity="SEVERE", surface_type="WALL",
                           is_offensive=True, description="hateful")
    api.create_work_order(create_work_order_payload(
        rep2, crew_id, estimated_labor_hours=2.0,
        scheduled_start=W_1113[0], scheduled_end=W_1113[1]), COORD)
    # Dispatch was rejected, so the report never advanced past TRIAGED.
    rep = validate_success(api.get_report(rep2, COORD), 200)
    assert rep["status"] == "TRIAGED"


# --------------------------------------------------------------------------
# resource_temporal_overlap / crew_window_halfopen_overlap
# --------------------------------------------------------------------------
def test_crew_window_overlap_rejected(api):
    """PRD §3.3: "if the crew has any other non-terminal work order whose half-open interval from its
    `scheduled_start` up to (but not including) its `scheduled_end` overlaps the new window, the
    request is rejected with `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_window_halfopen_overlap
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew = register_crew(api)
    rep1 = _triaged_report(api, site["id"], description="job1")
    validate_success(api.create_work_order(create_work_order_payload(
        rep1, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_0912[0], scheduled_end=W_0912[1]), COORD), 201)
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    resp = api.create_work_order(create_work_order_payload(
        rep2, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_1113[0], scheduled_end=W_1113[1]), COORD)
    validate_error(resp, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)


def test_crew_adjacent_window_halfopen_allowed(api):
    """PRD §3.3: "if the crew has any other non-terminal work order whose half-open interval from its
    `scheduled_start` up to (but not including) its `scheduled_end` overlaps the new window, the
    request is rejected with `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/crew_window_halfopen_overlap
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew = register_crew(api)
    rep1 = _triaged_report(api, site["id"], description="job1")
    validate_success(api.create_work_order(create_work_order_payload(
        rep1, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_0912[0], scheduled_end=W_0912[1]), COORD), 201)
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    # [12:00,14:00) starts exactly at the prior window's end — half-open, so no overlap.
    wo2 = validate_success(api.create_work_order(create_work_order_payload(
        rep2, crew["id"], estimated_labor_hours=2.0,
        scheduled_start=W_1214[0], scheduled_end=W_1214[1]), COORD), 201)
    assert wo2["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# resource_temporal_overlap / site_buffer_private_adjacency
# --------------------------------------------------------------------------
def test_private_site_buffer_conflict_rejected(api):
    """PRD §3.3: "for a `PRIVATE` site, no other non-terminal work order on the same site may fall
    within a 24-hour buffer of the new window — concretely, a conflict exists when the new window's
    start is earlier than the other window's end plus 24 hours **and** the other window's start is
    earlier than the new window's end plus 24 hours — and a violation yields
    `ERR_SITE_ABATEMENT_BUFFER_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/site_buffer_private_adjacency
    """
    owner = register_owner(api)
    site = register_site(api, ownership_type="PRIVATE", property_owner_id=owner["id"])
    crew_a = register_crew(api, name="Crew A")
    crew_b = register_crew(api, name="Crew B", crew_type="CONTRACTOR")
    rep1 = _triaged_report(api, site["id"], description="job1")
    validate_success(api.create_work_order(create_work_order_payload(
        rep1, crew_a["id"], estimated_labor_hours=2.0,
        scheduled_start=W_0911[0], scheduled_end=W_0911[1]), COORD), 201)
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    # [20:00,22:00) is 9h from [09:00,11:00) — within the 24h private-site buffer.
    resp = api.create_work_order(create_work_order_payload(
        rep2, crew_b["id"], estimated_labor_hours=2.0,
        scheduled_start=W_2022[0], scheduled_end=W_2022[1]), COORD)
    validate_error(resp, ApiErrorId.ERR_SITE_ABATEMENT_BUFFER_CONFLICT)


def test_public_site_no_buffer_rule(api):
    """PRD §3.3: "A private-property spacing rule also applies: for a `PRIVATE` site, no other
    non-terminal work order on the same site may fall within a 24-hour buffer of the new window".

    Design: Difficulty/resource_temporal_overlap/site_buffer_private_adjacency
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew_a = register_crew(api, name="Crew A")
    crew_b = register_crew(api, name="Crew B", crew_type="CONTRACTOR")
    rep1 = _triaged_report(api, site["id"], description="job1")
    validate_success(api.create_work_order(create_work_order_payload(
        rep1, crew_a["id"], estimated_labor_hours=2.0,
        scheduled_start=W_0911[0], scheduled_end=W_0911[1]), COORD), 201)
    rep2 = _triaged_report(api, site["id"], severity="MEDIUM", surface_type="FENCE",
                           reported_via="WEB", description="job2")
    # The buffer is PRIVATE-only, so the same adjacency on a PUBLIC site is accepted.
    wo2 = validate_success(api.create_work_order(create_work_order_payload(
        rep2, crew_b["id"], estimated_labor_hours=2.0,
        scheduled_start=W_2022[0], scheduled_end=W_2022[1]), COORD), 201)
    assert wo2["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Corner: validations / workorder_scheduled_end_before_start
# --------------------------------------------------------------------------
def test_workorder_scheduled_end_before_start_returns_invalid_request(api):
    """PRD §2.10: "Third is request well-formedness — required fields present, types and enums valid,
    and `scheduled_end` strictly after `scheduled_start` — a failure of which yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/workorder_scheduled_end_before_start_returns_invalid_request
    """
    site = register_site(api, ownership_type="PUBLIC")
    crew = register_crew(api)
    rep = _triaged_report(api, site["id"])
    resp = api.create_work_order(create_work_order_payload(
        rep, crew["id"], estimated_labor_hours=2.0,
        scheduled_start="2026-03-05T12:00:00Z", scheduled_end="2026-03-05T09:00:00Z"), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# --------------------------------------------------------------------------
# Corner: consistency_model / dispatch_response_immediately_reflects_report_dispatched
# --------------------------------------------------------------------------
def test_dispatch_immediately_reflects_report_dispatched_and_reservation(api):
    """PRD §3.3: "a successful dispatch advances the report `TRIAGED → DISPATCHED` and creates a
    **WorkOrder** in `SCHEDULED` status."
    PRD §3.3: "It creates one **MaterialReservation** per `material_lines` entry, each in `RESERVED`
    status ... for each, the reserved quantity is moved out of the material's `quantity_available`
    and into its `quantity_reserved`".

    Design: Corner/consistency_model/dispatch_response_immediately_reflects_report_dispatched
    """
    owner = register_owner(api)
    site = register_site(api, ownership_type="PRIVATE", property_owner_id=owner["id"])
    material = register_material(api, unit_cost_cents=1200, quantity_available=10.0)
    crew = register_crew(api)
    rep = _triaged_report(api, site["id"])
    validate_success(api.create_work_order(create_work_order_payload(
        rep, crew["id"], estimated_labor_hours=2.0,
        material_lines=material_lines(material["id"], 2.0)), COORD), 201)
    report = validate_success(api.get_report(rep, COORD), 200)
    assert report["status"] == "DISPATCHED"
    mat = validate_success(api.get_material(material["id"], COORD), 200)
    assert mat["quantity_reserved"] == 2.0
