"""Role-based access control: exclusive-operation denial, entity-backed
ownership, and the unauthenticated short-circuit."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_engagement_in_open,
    create_rate_card_payload,
    create_submitted_timesheet,
    create_worker_payload,
    get_success_data,
    get_supplier,
    get_timesheet,
    make_supplier_coordinator_headers,
    make_worker_headers,
    onboard_supplier,
    pick_offer_for_supplier,
    set_logical_clock,
    setup_staffed_assignment,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_worker_cannot_approve_timesheet(api):
    """PRD: "A request whose role is authenticated but not permitted on the
    target endpoint — or whose entity-backed identity does not match the
    resource being acted on — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD: "Approval belongs to the `HiringManager` and computes the `FINAL`
    variant."

    Design: Corner/rbac/worker_cannot_approve_timesheet
    """
    ctx = setup_staffed_assignment(supplier_name="RBAC Co", supplier_code="SUP-RB")
    timesheet = create_submitted_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=8.0
    )
    resp = api.approve_timesheet(
        timesheet["id"], {}, make_worker_headers(ctx["worker"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_timesheet(timesheet["id"])["status"] == "SUBMITTED", (
        "the forbidden approval changes nothing"
    )


def test_supplier_coordinator_cannot_create_rate_card(api):
    """PRD: "A request whose role is authenticated but not permitted on the
    target endpoint — or whose entity-backed identity does not match the
    resource being acted on — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD endpoint table: POST /v1/rate-cards is authorized for ProgramAdmin
    only ("Create a rate card in `DRAFT` | ProgramAdmin").

    Design: Corner/rbac/supplier_coordinator_cannot_create_rate_card
    """
    supplier = onboard_supplier(tier="APPROVED", name="RBAC2 Co",
                                supplier_code="SUP-R2")
    resp = api.create_rate_card(
        create_rate_card_payload(effective_from="2026-05-01",
                                 effective_to="2026-08-01"),
        make_supplier_coordinator_headers(supplier["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    _, meta = validate_paginated(api.list_rate_cards(ADMIN))
    assert meta["total_count"] == 0, "the forbidden create persists nothing"


def test_supplier_a_cannot_respond_to_supplier_b_offer(api):
    """PRD: "The supplier's response comes through a single respond action
    carrying an `action` of `ACCEPT` or `DECLINE`, and it is
    ownership-checked: the caller's `X-User-ID` must equal the offer's
    `supplier_id`."
    PRD: "an entity-backed identity mismatches the resource owner (a
    `SupplierCoordinator` acting on another supplier's offers, milestones or
    workers; a `Worker` acting on another worker's timesheets):
    `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/supplier_a_cannot_respond_to_supplier_b_offer
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    sa = onboard_supplier(tier="PREFERRED", name="Own A", supplier_code="SUP-OA")
    sb = onboard_supplier(tier="APPROVED", name="Own B", supplier_code="SUP-OB")
    engagement = create_engagement_in_open(title="Ownership")
    offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
    offer_a = pick_offer_for_supplier(offers, sa["id"])
    assert offer_a["supplier_id"] == sa["id"]

    resp = api.respond_to_offer(
        offer_a["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(sb["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = get_success_data(api.get_distribution_offer(offer_a["id"], ADMIN))
    assert after["status"] == "OFFERED", "the forbidden respond changes nothing"
    assert get_supplier(sa["id"])["open_offers_count"] == 1, (
        "SA's outstanding-slot count is unchanged"
    )


def test_worker_cannot_submit_for_other_workers_assignment(api):
    """PRD: "A timesheet is created by a `Worker` against one of that
    worker's own `ACTIVE` assignments"
    PRD: "an entity-backed identity mismatches the resource owner (a
    `SupplierCoordinator` acting on another supplier's offers, milestones or
    workers; a `Worker` acting on another worker's timesheets):
    `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/worker_cannot_submit_for_other_workers_assignment
    """
    ctx = setup_staffed_assignment(supplier_name="OwnW Co", supplier_code="SUP-OW")
    worker2 = get_success_data(
        api.create_worker(
            create_worker_payload(ctx["supplier"]["id"], full_name="Worker Two",
                                  email="w2@example.com"),
            make_supplier_coordinator_headers(ctx["supplier"]["id"]),
        )
    )
    resp = api.create_timesheet(
        {
            "assignment_id": ctx["assignment"]["id"],
            "period_start": "2026-05-04",
            "period_end": "2026-05-10",
            "submitted_hours": 8.0,
        },
        make_worker_headers(worker2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    # worker2 is not the assignment's worker
    _, meta = validate_paginated(
        api.list_timesheets(ADMIN, params={"assignment_id": ctx["assignment"]["id"]})
    )
    assert meta["total_count"] == 0


def test_anonymous_caller_returns_unauthenticated(api):
    """PRD: "A request missing either header, carrying a role that is not one
    of the declared roles below, or carrying the role `Anonymous` is
    unauthenticated and is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD: "1. **Authentication** — missing or invalid `X-User-ID` /
    `X-User-Role` headers, an undeclared role, or `Anonymous`:
    `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/rbac/anonymous_caller_returns_unauthenticated
    """
    supplier = onboard_supplier(tier="APPROVED", name="Anon Co",
                                supplier_code="SUP-AN")
    resp = api.get_supplier(supplier["id"], ANON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401, (
        "authentication short-circuits before authorization and existence"
    )
