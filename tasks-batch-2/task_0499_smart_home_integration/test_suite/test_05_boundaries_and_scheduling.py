"""Boundary precision and scheduling/temporal-overlap rules.

Covers the boundary-precision rule (rack RU exact-fit vs one-over; empty proposal
on send), the resource-temporal-overlap rule (crew half-open adjacency allowed,
overlap rejected; visit closed-interval touch conflicts), and corner claims for
crew daily cap, region mismatch, inactivity, window ordering, and IP exhaustion.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    factories as f, fixtures as fx,
)
from test_helpers.fixtures import (
    DESIGNER, PM, TECH,
    create_client, create_project, create_rack, setup_sent_proposal, accept_proposal,
    setup_provisioning_project, create_crew_member, create_visit, assign_crew,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / boundary_precision_check / empty_proposal_zero_line_items_rejected_on_send
# ===========================================================================

def test_send_proposal_all_line_items_removed_rejected():
    """PRD §3.2: "Sending a proposal is a SystemsDesigner action permitted only
    while the proposal has at least one line item with removed false — otherwise
    ERR_EMPTY_PROPOSAL".

    Design: Difficulty/boundary_precision_check/empty_proposal_zero_line_items_rejected_on_send
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal, items = fx.setup_draft_proposal_with_items(
        project["id"],
        line_items=[dict(sku="C4-CTRL", category="CONTROLLER", qty=1, unit_price_cents=250000)])
    get_success_data(api_client.remove_line_item(
        project["id"], proposal["id"], items[0]["id"], DESIGNER))
    resp = api_client.send_proposal(project["id"], proposal["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_PROPOSAL)


def test_empty_proposal_send_leaves_proposal_draft():
    """PRD §3.2: "Sending a proposal is a SystemsDesigner action permitted only
    while the proposal has at least one line item with removed false — otherwise
    ERR_EMPTY_PROPOSAL".

    Design: Difficulty/boundary_precision_check/empty_proposal_zero_line_items_rejected_on_send
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal, items = fx.setup_draft_proposal_with_items(
        project["id"],
        line_items=[dict(sku="C4-CTRL", category="CONTROLLER", qty=1, unit_price_cents=250000)])
    get_success_data(api_client.remove_line_item(
        project["id"], proposal["id"], items[0]["id"], DESIGNER))
    api_client.send_proposal(project["id"], proposal["id"], DESIGNER)
    data = validate_success(api_client.get_proposal(proposal["id"], DESIGNER))
    assert data["status"] == "DRAFT", "proposal unchanged after rejected send"


# ===========================================================================
# Difficulty / resource_temporal_overlap / crew_half_open_overlap_vs_adjacency_allowed
# ===========================================================================

def _accepted_project_with_visit(client_id, region, window_start, window_end,
                                 visit_kind="SERVICE"):
    project = create_project(client_id, region_code=region)
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client_id)
    visit = create_visit(project["id"], window_start, window_end,
                         visit_kind=visit_kind, crew_size_required=1)
    return project["id"], visit


def test_crew_adjacent_assignment_at_endpoint_allowed():
    """PRD §3.7: "a crew time-overlap check: the member's other ACTIVE assignments'
    visit windows may not overlap the target visit's window, evaluated with
    half-open [window_start, window_end) semantics, so adjacency that merely touches
    at an endpoint — one window's window_end equal to another's window_start — does
    not conflict; an overlap is rejected with ERR_CREW_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_overlap_vs_adjacency_allowed
    """
    client = create_client()
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN", daily_visit_cap=5)
    p1, va = _accepted_project_with_visit(client["id"], "WEST",
                                          "2026-04-01T09:00:00Z", "2026-04-01T12:00:00Z")
    p2, vb = _accepted_project_with_visit(client["id"], "WEST",
                                          "2026-04-01T12:00:00Z", "2026-04-01T15:00:00Z")
    assign_crew(p1, va["id"], crew["id"], va["version"])
    data = validate_success(api_client.create_assignment(
        p2, vb["id"], f.create_assignment_payload(crew["id"], vb["version"]), PM),
        expected_status=201)
    assert data["status"] == "ACTIVE", "12:00 adjacency to 09:00-12:00 allowed under half-open"


def test_crew_genuine_overlap_rejected():
    """PRD §3.7: "the member's other ACTIVE assignments' visit windows may not
    overlap the target visit's window, evaluated with half-open [window_start,
    window_end) semantics ... an overlap is rejected with ERR_CREW_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_overlap_vs_adjacency_allowed
    """
    client = create_client()
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN", daily_visit_cap=5)
    p1, va = _accepted_project_with_visit(client["id"], "WEST",
                                          "2026-04-01T09:00:00Z", "2026-04-01T12:00:00Z")
    p3, vc = _accepted_project_with_visit(client["id"], "WEST",
                                          "2026-04-01T11:00:00Z", "2026-04-01T13:00:00Z")
    assign_crew(p1, va["id"], crew["id"], va["version"])
    resp = api_client.create_assignment(
        p3, vc["id"], f.create_assignment_payload(crew["id"], vc["version"]), PM)
    validate_error(resp, ApiErrorId.ERR_CREW_TIME_CONFLICT)


# ===========================================================================
# Difficulty / resource_temporal_overlap / visit_closed_overlap_touching_endpoint_conflicts
# ===========================================================================

def test_visit_touching_endpoint_conflicts_closed_interval():
    """PRD §3.7: "this conflict check uses closed-interval semantics on
    [window_start, window_end]: two visits that merely touch at an endpoint — where
    one visit's window_end equals another's window_start — do conflict and the
    creation is rejected with ERR_VISIT_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/visit_closed_overlap_touching_endpoint_conflicts
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    create_visit(project["id"], "2026-05-01T09:00:00Z", "2026-05-01T12:00:00Z",
                 visit_kind="INSTALL", crew_size_required=1)
    resp = api_client.create_visit(
        project["id"],
        f.create_visit_payload(window_start="2026-05-01T12:00:00Z",
                               window_end="2026-05-01T15:00:00Z",
                               visit_kind="SERVICE", crew_size_required=1),
        PM)
    validate_error(resp, ApiErrorId.ERR_VISIT_TIME_CONFLICT)


def test_visit_touching_endpoint_conflict_leaves_single_visit():
    """PRD §3.7: "two visits that merely touch at an endpoint ... do conflict and
    the creation is rejected with ERR_VISIT_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/visit_closed_overlap_touching_endpoint_conflicts
    """
    from test_helpers import validate_paginated
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    create_visit(project["id"], "2026-05-01T09:00:00Z", "2026-05-01T12:00:00Z",
                 visit_kind="INSTALL", crew_size_required=1)
    api_client.create_visit(
        project["id"],
        f.create_visit_payload(window_start="2026-05-01T12:00:00Z",
                               window_end="2026-05-01T15:00:00Z",
                               visit_kind="SERVICE", crew_size_required=1),
        PM)
    rows, _ = validate_paginated(api_client.list_visits(project["id"], PM))
    assert len(rows) == 1, "exactly 1 visit after the rejected create"


# ===========================================================================
# Corner / calculations / crew_daily_cap_boundary_third_same_day_rejected
# ===========================================================================

def test_crew_daily_cap_third_same_day_rejected():
    """PRD §3.7: "the member's load for the target visit's UTC calendar day is the
    number of their ACTIVE assignments whose visit's window_start falls on that same
    UTC date; if that load plus one would exceed the member's daily_visit_cap, the
    assignment is rejected with ERR_CREW_DAILY_CAP_EXCEEDED."

    Design: Corner/calculations/crew_daily_cap_boundary_third_same_day_rejected
    """
    client = create_client()
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN", daily_visit_cap=2)
    p1, v1 = _accepted_project_with_visit(client["id"], "WEST",
                                          "2026-07-01T08:00:00Z", "2026-07-01T09:00:00Z")
    p2, v2 = _accepted_project_with_visit(client["id"], "WEST",
                                          "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z")
    p3, v3 = _accepted_project_with_visit(client["id"], "WEST",
                                          "2026-07-01T12:00:00Z", "2026-07-01T13:00:00Z")
    assign_crew(p1, v1["id"], crew["id"], v1["version"])
    assign_crew(p2, v2["id"], crew["id"], v2["version"])
    resp = api_client.create_assignment(
        p3, v3["id"], f.create_assignment_payload(crew["id"], v3["version"]), PM)
    validate_error(resp, ApiErrorId.ERR_CREW_DAILY_CAP_EXCEEDED)


# ===========================================================================
# Corner / validations / assignment_crew_region_mismatch_returns_region_mismatch
# ===========================================================================

def test_assignment_crew_region_mismatch_rejected():
    """PRD §3.7: "the member's region_code must equal the visit's region_code,
    otherwise ERR_CREW_REGION_MISMATCH."

    Design: Corner/validations/assignment_crew_region_mismatch_returns_region_mismatch
    """
    client = create_client()
    crew = create_crew_member(region_code="NORTH", cert_level="JOURNEYMAN")
    p, v = _accepted_project_with_visit(client["id"], "WEST",
                                        "2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z",
                                        visit_kind="INSTALL")
    resp = api_client.create_assignment(
        p, v["id"], f.create_assignment_payload(crew["id"], v["version"]), PM)
    validate_error(resp, ApiErrorId.ERR_CREW_REGION_MISMATCH)


# ===========================================================================
# Corner / validations / assignment_inactive_crew_returns_crew_inactive
# ===========================================================================

def test_assignment_inactive_crew_rejected():
    """PRD §3.7: "the assigned crew member must be active, otherwise
    ERR_CREW_INACTIVE".

    Design: Corner/validations/assignment_inactive_crew_returns_crew_inactive
    """
    client = create_client()
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN", active=False)
    p, v = _accepted_project_with_visit(client["id"], "WEST",
                                        "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z",
                                        visit_kind="INSTALL")
    resp = api_client.create_assignment(
        p, v["id"], f.create_assignment_payload(crew["id"], v["version"]), PM)
    validate_error(resp, ApiErrorId.ERR_CREW_INACTIVE)


# ===========================================================================
# Corner / validations / visit_window_end_not_after_start_returns_invalid_request
# ===========================================================================

def test_visit_window_end_equal_start_rejected():
    """PRD §3.7: "a window_start and a window_end (ISO 8601 UTC instants, where the
    end must be strictly after the start)".

    Design: Corner/validations/visit_window_end_not_after_start_returns_invalid_request
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    accept_proposal(project["id"], proposal["id"], client["id"])
    resp = api_client.create_visit(
        project["id"],
        f.create_visit_payload(window_start="2026-08-03T09:00:00Z",
                               window_end="2026-08-03T09:00:00Z",
                               visit_kind="INSTALL", crew_size_required=1),
        PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Corner / state_machines / ip_pool_exhaustion_on_third_provision_in_slash30
# ===========================================================================

def test_ip_pool_exhaustion_on_third_provision_slash30():
    """PRD §3.4: "the system assigns the lowest host address that is not already
    held by any non-RETIRED device on the same rack. If every host address in the
    pool is already taken, provisioning fails with ERR_IP_POOL_EXHAUSTED."

    Design: Corner/state_machines/ip_pool_exhaustion_on_third_provision_in_slash30
    """
    ctx = setup_provisioning_project(
        region_code="WEST",
        rack_overrides=dict(rack_units_total=20, subnet_cidr="10.20.0.0/30"))
    rack_id = ctx["rack"]["id"]
    d1 = fx.register_device(rack_id, sku="A", category="ACCESSORY", rack_units=1)
    d2 = fx.register_device(rack_id, sku="B", category="ACCESSORY", rack_units=1)
    d3 = fx.register_device(rack_id, sku="C", category="ACCESSORY", rack_units=1)
    p1 = validate_success(api_client.provision_device(d1["id"], TECH))
    p2 = validate_success(api_client.provision_device(d2["id"], TECH))
    assert p1["mgmt_ip"] == "10.20.0.1", "lowest free host"
    assert p2["mgmt_ip"] == "10.20.0.2", "next free host"
    resp = api_client.provision_device(d3["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_IP_POOL_EXHAUSTED)
