"""CRUD, defaults, computed fields, listing/pagination, the contractor
qualification lifecycle, project completion/closure, RBAC and ownership checks,
and FK-reverse listing.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    set_clock,
    create_homeowner,
    create_contractor,
    create_qualified_contractor,
    create_draft_project,
    open_project,
    create_submitted_bid,
    award_bid,
    get_project_escrow,
    fund_escrow,
    request_approve_pay_draw,
    make_homeowner_headers,
    make_contractor_headers,
    NON_EXISTENT_UUID,
)
from test_helpers import TEST_USERS

_ADMIN = TEST_USERS["platform_admin_headers"]
_ANON = TEST_USERS["anonymous_headers"]


# ───────────────────────── Entity creation / CRUD ──────────────────────────
def test_create_project_returns_201_with_initial_fields(api):
    """PRD §3.2: "A new project starts in `DRAFT` status with a
    `contract_value_cents` of zero, an `awarded_bid_id` of null, and `scope_locked`
    set to false."

    Design: Corner/entities/create_project_returns_201_with_all_fields
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    res = api.create_project(
        {"homeowner_id": homeowner["id"], "title": "New", "budget_cap_cents": 500_000,
         "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL", "min_rating": 0},
        ho)
    project = validate_success(res, 201)
    assert project["status"] == "DRAFT", project
    assert project["contract_value_cents"] == 0, project
    assert project["scope_locked"] is False, project
    assert project["awarded_bid_id"] is None, project


def test_get_project_not_found_returns_404(api):
    """PRD §2.8: "every resource referenced either by a path identifier or by a
    foreign-key field in the request body must exist; if any referenced resource
    is absent, the request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    res = api.get_project(NON_EXISTENT_UUID, _ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_project_missing_budget_cap_invalid_request(api):
    """PRD §3.2: "A homeowner then creates a project by supplying the owning
    `homeowner_id`, a `title`, a `budget_cap_cents` ceiling that must be strictly
    greater than zero, a `bid_deadline`, and a `required_trade` that the eventual
    winner must hold."
    PRD §5 error catalogue: `ERR_INVALID_REQUEST` for "missing required field".

    Design: Corner/entities/create_project_missing_required_field_returns_invalid_request
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    res = api.create_project(
        {"homeowner_id": homeowner["id"], "title": "NoBudget",
         "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL"},
        ho)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_project_min_rating_defaults_to_zero(api):
    """PRD §3.2: "An optional `min_rating` floor may be supplied; it defaults to
    zero (meaning no rating floor), and when supplied must be between zero and five
    inclusive."

    Design: Corner/entities/create_project_min_rating_default_applied
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    res = api.create_project(
        {"homeowner_id": homeowner["id"], "title": "DefRating", "budget_cap_cents": 500_000,
         "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL"},
        ho)
    project = validate_success(res, 201)
    assert project["min_rating"] == 0, project


def test_create_contractor_starts_pending(api):
    """PRD §3.1: "A newly registered contractor begins with a `qualification_status`
    of `PENDING` and is not yet allowed to bid."

    Design: Corner/entities/create_contractor_system_fields_generated
    """
    res = api.create_contractor(
        {"legal_name": "Sys Co", "trade": "PLUMBING", "license_number": "SY",
         "license_expiry": "2027-01-01T00:00:00Z", "insurance_coverage_cents": 5_000_000},
        _ANON)
    contractor = validate_success(res, 201)
    assert contractor["qualification_status"] == "PENDING", contractor


def test_create_scope_line_item_invalid_unit_rejected(api):
    """PRD §3.2: "Each scope line is added by supplying a `description`, a
    `quantity` greater than zero, a `unit` of measure that must be one of `SQFT`,
    `UNIT`, `HOUR`, or `LUMP`."
    PRD §5 error catalogue: `ERR_INVALID_REQUEST` for "bad enum".

    Design: Corner/entities/create_scope_line_item_invalid_enum_unit_rejected
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    project = get_success_data(api.create_project(
        {"homeowner_id": homeowner["id"], "title": "EnumProj", "budget_cap_cents": 500_000,
         "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL", "min_rating": 0},
        ho))
    res = api.create_scope_line_item(
        project["id"],
        {"description": "Bad", "quantity": 1, "unit": "TONNE", "estimated_unit_cost_cents": 100},
        ho)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_scope_line_item_wrong_project_not_found(api):
    """PRD §2.8: "for any endpoint, every resource referenced either by a path
    identifier or by a foreign-key field in the request body must exist; if any
    referenced resource is absent, the request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/parent_relationship_scope_item_wrong_project_not_found
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    res = api.create_scope_line_item(
        NON_EXISTENT_UUID,
        {"description": "X", "quantity": 1, "unit": "LUMP", "estimated_unit_cost_cents": 100},
        ho)
    validate_error(res, "ERR_NOT_FOUND")


# ───────────────────────── Listing / pagination ────────────────────────────
def test_list_projects_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    set_clock()
    homeowner = create_homeowner()
    ho = make_homeowner_headers(homeowner["id"])
    for title in ("P1", "P2"):
        get_success_data(api.create_project(
            {"homeowner_id": homeowner["id"], "title": title, "budget_cap_cents": 500_000,
             "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL", "min_rating": 0},
            ho))
    data, meta = validate_paginated(
        api.list_projects(ho, params={"homeowner_id": homeowner["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_list_bids_filtered_by_project(api):
    """PRD §4 endpoint table: "List bids, filterable by project or contractor"
    PRD §2.4: "List endpoints return resources ordered by this `created_at` value
    ascending."

    A project with exactly one bid: filtering the bid list by that project_id
    returns exactly that bid — the only meaning "filterable by project" can carry.

    Design: Corner/endpoints/fk_reverse_list_bids_by_project
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = get_success_data(api.create_bid(
        {"project_id": opened["id"], "contractor_id": contractor["id"], "duration_days": 30},
        make_contractor_headers(contractor["id"])))

    ho = make_homeowner_headers(homeowner["id"])
    data, _meta = validate_paginated(api.list_bids(ho, params={"project_id": opened["id"]}))
    assert len(data) == 1, data
    assert data[0]["id"] == bid["id"], data


# ───────────────────────── Contractor qualification lifecycle ──────────────
def test_qualify_pending_contractor_to_qualified(api):
    """PRD §3.1: "Qualifying a contractor advances `qualification_status` from
    `PENDING` to `QUALIFIED`, but only when three conditions hold: the
    `license_number` is non-empty, the `license_expiry` is in the future relative
    to the current clock, and the `insurance_coverage_cents` is at least 1,000,000
    cents — that is, at least ten thousand dollars of coverage."

    Design: Corner/state_machines/qualify_contractor_pending_to_qualified
    """
    set_clock()
    contractor = create_contractor(
        license_number="QC", license_expiry="2027-01-01T00:00:00Z",
        insurance_coverage_cents=5_000_000)
    res = api.qualify_contractor(contractor["id"], _ADMIN)
    qualified = validate_success(res, 200)
    assert qualified["qualification_status"] == "QUALIFIED", qualified


def test_qualify_contractor_with_insufficient_insurance_rejected(api):
    """PRD §3.1: "Qualifying a contractor advances `qualification_status` from
    `PENDING` to `QUALIFIED`, but only when three conditions hold: the
    `license_number` is non-empty, the `license_expiry` is in the future relative
    to the current clock, and the `insurance_coverage_cents` is at least 1,000,000
    cents — that is, at least ten thousand dollars of coverage."

    Insurance 500000 (< 1,000,000) fails the qualification precondition; the
    contractor stays PENDING.

    Design: Corner/state_machines/qualify_contractor_insurance_too_low_rejected
    """
    set_clock()
    contractor = create_contractor(insurance_coverage_cents=500_000)
    res = api.qualify_contractor(contractor["id"], _ADMIN)
    assert res.status_code >= 400, res.text
    after = validate_success(api.get_contractor(contractor["id"], _ADMIN), 200)
    assert after["qualification_status"] == "PENDING", after


def test_contractor_initial_state_is_pending(api):
    """PRD §3.1: "A newly registered contractor begins with a
    `qualification_status` of `PENDING` and is not yet allowed to bid."

    Design: Corner/state_machines/contractor_starts_in_pending_initial_state
    """
    res = api.create_contractor(
        {"legal_name": "Init Co", "trade": "HVAC", "license_number": "IN",
         "license_expiry": "2027-01-01T00:00:00Z", "insurance_coverage_cents": 5_000_000},
        _ANON)
    contractor = validate_success(res, 201)
    assert contractor["qualification_status"] == "PENDING", contractor


def test_revoke_from_qualified_invalid_state(api):
    """PRD §3.1: "An admin may suspend a qualified contractor, moving
    `qualification_status` from `QUALIFIED` to `SUSPENDED` with no further
    precondition, and may revoke a suspended contractor, moving
    `qualification_status` from `SUSPENDED` to the terminal `REVOKED` state, again
    with no further precondition."

    Revoke is only defined from SUSPENDED; revoking a QUALIFIED contractor is an
    invalid-state transition.

    Design: Corner/state_machines/revoke_from_qualified_invalid_transition
    """
    set_clock()
    contractor = create_qualified_contractor()
    res = api.revoke_contractor(contractor["id"], _ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_contractor(contractor["id"], _ADMIN), 200)
    assert after["qualification_status"] == "QUALIFIED", after


def test_revoked_contractor_cannot_be_requalified(api):
    """PRD §3.1: "and may revoke a suspended contractor, moving
    `qualification_status` from `SUSPENDED` to the terminal `REVOKED` state."
    PRD §3.1: "Qualifying a contractor advances `qualification_status` from
    `PENDING` to `QUALIFIED`... The same admin capability re-qualifies a contractor
    who has been suspended, moving `qualification_status` from `SUSPENDED` back to
    `QUALIFIED`."

    REVOKED is terminal: qualify is defined only from PENDING or SUSPENDED, so a
    qualify on a REVOKED contractor is an invalid-state transition.

    Design: Corner/state_machines/revoked_contractor_terminal_lockdown
    """
    set_clock()
    contractor = create_qualified_contractor()
    get_success_data(api.suspend_contractor(contractor["id"], _ADMIN))
    get_success_data(api.revoke_contractor(contractor["id"], _ADMIN))
    res = api.qualify_contractor(contractor["id"], _ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_contractor(contractor["id"], _ADMIN), 200)
    assert after["qualification_status"] == "REVOKED", after


# ───────────────────────── Completion / closure ────────────────────────────
def test_complete_project_closes_escrow(api):
    """PRD §3.8: "A homeowner completes a project, moving its `status` from
    `IN_PROGRESS` to the terminal `COMPLETED` state, only when every milestone of
    the project is in `PAID` status and the escrow's `retained_cents` has been
    fully released back to zero. Completion also moves the escrow's `status` to the
    terminal `CLOSED` state."

    A single final milestone (release_pct 1.0, retainage 0) is drawn and paid, so
    the project can complete and the escrow closes.

    Design: Corner/state_machines/project_complete_bubbles_escrow_closed
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, milestones = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    award_bid(opened, homeowner, bid, opened["version"])
    escrow = get_project_escrow(opened, homeowner)
    fund_escrow(escrow, 600_000)
    ctx = {"homeowner": homeowner, "contractor": contractor, "project": opened}
    request_approve_pay_draw(ctx, milestones[0], 600_000)  # final draw, retainage 0

    ho = make_homeowner_headers(homeowner["id"])
    completed = validate_success(api.complete_project(opened["id"], ho), 200)
    assert completed["status"] == "COMPLETED", completed
    escrow_after = validate_success(api.get_escrow(escrow["id"], ho), 200)
    assert escrow_after["status"] == "CLOSED", escrow_after
    assert escrow_after["released_cents"] == 600_000, escrow_after


# ───────────────────────── RBAC and ownership ──────────────────────────────
def test_contractor_cannot_award_project(api):
    """PRD §2.1: "A request whose role is recognized and authenticated but is not
    permitted to perform the requested operation under the access matrix in
    Section 4 is rejected with `ERR_FORBIDDEN`."
    PRD §4 endpoint matrix: `POST /projects/{id}/award` is authorized for
    Homeowner only.

    Design: Corner/rbac/contractor_cannot_award_project
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    res = api.award_project(
        opened["id"],
        {"bid_id": bid["id"], "expected_project_version": opened["version"]},
        make_contractor_headers(contractor["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    ho = make_homeowner_headers(homeowner["id"])
    assert validate_success(api.get_project(opened["id"], ho), 200)["status"] == "OPEN_FOR_BIDS"


def test_homeowner_cannot_open_another_homeowners_project(api):
    """PRD §2.1: "For the operations that require ownership — a homeowner acting on
    their own project and its sub-resources, and a contractor acting on their own
    bids and draw requests — a caller who is authenticated and role-permitted but
    is not the owner of the targeted resource is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/homeowner_cannot_act_on_another_homeowners_project
    """
    set_clock()
    owner_a = create_homeowner()
    owner_b = create_homeowner()
    project, _scope, _ms = create_draft_project(
        owner_a,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    res = api.open_project(project["id"], make_homeowner_headers(owner_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
    after = validate_success(
        api.get_project(project["id"], make_homeowner_headers(owner_a["id"])), 200)
    assert after["status"] == "DRAFT", after


def test_missing_auth_role_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that carries an
    `X-User-Role` that is not one of these recognized values, is rejected with
    `ERR_UNAUTHENTICATED`."

    Calling an authenticated endpoint with no auth headers is unauthenticated.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.list_projects(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
