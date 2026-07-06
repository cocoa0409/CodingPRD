"""Entity CRUD surface, endpoint actions, reverse-reachability listing, RBAC,
optimistic-concurrency happy paths, and immediate-consistency reads."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    assert_studio,
    create_studio,
    setup_studio_client,
    create_active_client,
    create_draft_project,
    add_milestone,
    create_and_activate_project,
    create_project_in_concept,
    create_project_in_delivery,
    create_presented_concept,
    create_license_payload,
    create_change_order_payload,
    issue_invoice,
    propose_change_order,
    approve_change_order,
)

SO = TEST_USERS["studio_ops_headers"]
DES = TEST_USERS["designer_headers"]
BO = TEST_USERS["billing_ops_headers"]


# --- entities ---

def test_create_studio_returns_201_with_common_fields(api):
    """PRD §2.4: "Every persisted resource ... carries a system-generated id
    formatted as a UUID ... and a created_at timestamp ... Every entity in this
    system is also a mutable resource and therefore additionally carries an
    updated_at timestamp ... and a version integer that begins at its initial value"

    Design: Corner/entities/create_studio_returns_201_with_common_fields
    """
    data = validate_success(
        api.create_studio({"name": "S", "tax_rate": 0.05, "license_markup_pct": 0.1}, SO),
        expected_status=201,
    )
    assert_studio(data)
    assert data["name"] == "S"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_get_project_returns_computed_ledger_fields(api):
    """PRD §3.2: "A project can be fetched (its computed ledger fields are included
    in the response)"
    PRD §3.2: "provisional_deposit_cents is set to the base scope multiplied by the
    project's deposit_pct, rounded half up to whole cents"

    Design: Corner/entities/get_project_returns_computed_ledger_fields
    """
    studio, client, project, _ = create_and_activate_project([10000], deposit_pct=0.30)
    data = validate_success(api.get_project(studio["id"], project["id"], SO))
    assert data["base_scope_cents"] == 10000
    assert data["contract_value_cents"] == 10000
    assert data["provisional_deposit_cents"] == 3000
    assert data["final_deposit_cents"] == 3000


def test_list_clients_paginated_envelope(api):
    """PRD §2.3: "List-based responses include limit, offset, total_count, and
    has_more in the meta object of the response envelope."

    Design: Corner/entities/list_clients_paginated_envelope
    """
    studio = create_studio()
    sid = studio["id"]
    create_active_client(sid, company_name="C1", contact_email="c1@c.com")
    create_active_client(sid, company_name="C2", contact_email="c2@c.com")
    data, meta = validate_paginated(api.list_clients(sid, SO, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_nonexistent_project_returns_not_found(api):
    """PRD §2.9: "the server validates the path identifiers left to right and rejects
    the first one that does not resolve to an existing resource within the enclosing
    scope, returning ERR_NOT_FOUND."

    Design: Corner/entities/get_nonexistent_project_returns_not_found
    """
    studio = create_studio()
    resp = api.get_project(studio["id"], "00000000-0000-4000-8000-000000000000", SO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_project_missing_service_type_invalid_request(api):
    """PRD §2.12: "a malformed body, a missing required field, an invalid enum
    member, or a numeric value outside its declared bounds yields
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_project_missing_required_field_invalid_request
    """
    studio, client = setup_studio_client()
    resp = api.create_project(
        studio["id"], {"client_id": client["id"], "title": "P", "deposit_pct": 0.30}, SO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_concept_applies_default_revision_limit_three(api):
    """PRD §3.4: "an optional revision_limit capping the number of paid-for revision
    rounds before overage applies (defaulting to three). A new concept starts in
    DRAFT with its rounds_used counter at zero."

    Design: Corner/entities/create_concept_default_revision_limit_applied
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    con = validate_success(
        api.create_concept(studio["id"], project["id"], {"label": "Route A"}, DES), expected_status=201
    )
    assert con["revision_limit"] == 3
    assert con["rounds_used"] == 0
    assert con["status"] == "DRAFT"


def test_project_status_system_assigned_draft_on_create(api):
    """PRD §3.2: "At creation the project records its parent studio_id from the path,
    sets status to DRAFT, and initializes base_scope_cents, contract_value_cents, and
    deposit_collected_cents to zero."

    Design: Corner/entities/project_status_system_assigned_draft_on_create
    """
    studio, client = setup_studio_client()
    data = validate_success(
        api.create_project(
            studio["id"],
            {"client_id": client["id"], "title": "P", "service_type": "LOGO", "deposit_pct": 0.30},
            SO,
        ),
        expected_status=201,
    )
    assert data["status"] == "DRAFT"
    assert data["base_scope_cents"] == 0
    assert data["deposit_collected_cents"] == 0


def test_create_project_invalid_service_type_enum_rejected(api):
    """PRD §3.2: "a service_type of LOGO, IDENTITY, or WEB" — an out-of-set value is
    an invalid enum member (PRD §2.12: "an invalid enum member ... yields
    ERR_INVALID_REQUEST").

    Design: Corner/entities/create_project_invalid_service_type_enum_rejected
    """
    studio, client = setup_studio_client()
    resp = api.create_project(
        studio["id"],
        {"client_id": client["id"], "title": "P", "service_type": "POSTER", "deposit_pct": 0.30},
        SO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_project_under_nonexistent_studio_not_found(api):
    """PRD §2.9: "A moodboard requested under a project that does not exist fails on
    the project before the moodboard is ever consulted" — the same left-to-right
    existence discipline rejects a child under a non-existent studio with
    ERR_NOT_FOUND.

    Design: Corner/entities/project_create_with_wrong_parent_studio_not_found
    """
    resp = api.create_project(
        "00000000-0000-4000-8000-000000000000",
        {
            "client_id": "00000000-0000-4000-8000-000000000001",
            "title": "P", "service_type": "LOGO", "deposit_pct": 0.30,
        },
        SO,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_invoice_carries_milestone_and_project_ids(api):
    """PRD §3.6: "The invoice records its project_id and the milestone_id it bills"

    Design: Corner/entities/hybrid_cross_aggregate_invoice_references_milestone
    """
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.30, tax_rate=0.0, deposit_cents=12000
    )
    sid, pid = studio["id"], project["id"]
    mid = milestones[0]["id"]
    inv = issue_invoice(sid, mid, "2026-04-01T00:00:00Z")
    assert inv["milestone_id"] == mid
    assert inv["project_id"] == pid


# --- endpoints ---

def test_record_deposit_increments_collected_ledger(api):
    """PRD §3.2: "A BillingOps operator records a deposit cash payment of
    amount_cents against the project, which adds that amount to the running
    deposit_collected_cents."

    Design: Corner/endpoints/record_deposit_increments_collected_ledger
    """
    studio, client = setup_studio_client()
    sid = studio["id"]
    project = create_draft_project(sid, client["id"], deposit_pct=0.30)
    pid = project["id"]
    get_success_data(api.record_deposit(sid, pid, {"amount_cents": 5000}, BO))
    data = validate_success(api.record_deposit(sid, pid, {"amount_cents": 3000}, BO), expected_status=201)
    assert data["deposit_collected_cents"] == 8000


def test_list_invoices_filtered_by_project(api):
    """PRD §3.6: "and can be fetched or listed (filterable by project_id or
    milestone_id)."

    Design: Corner/endpoints/list_invoices_filtered_by_project_reverse_reachability
    """
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.0, tax_rate=0.0
    )
    sid, pid = studio["id"], project["id"]
    inv = issue_invoice(sid, milestones[0]["id"], "2026-04-01T00:00:00Z")
    data, meta = validate_paginated(api.list_invoices(sid, BO, params={"project_id": pid}))
    assert meta["total_count"] == 1
    assert any(i["id"] == inv["id"] for i in data)


def test_list_change_orders_filtered_by_concept(api):
    """PRD §3.8: "Change orders can be fetched and listed (filterable by project_id
    or concept_id)."

    Design: Corner/endpoints/list_change_orders_filtered_by_concept_reverse_reachability
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30, service_type="IDENTITY")
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = get_success_data(api.create_concept(sid, pid, {"label": "Route A", "revision_limit": 1}, DES))
    pv = validate_success(api.get_project(sid, pid, SO))["version"]
    co = propose_change_order(
        sid, pid, 5000, pv, reason="EXTRA_REVISION", concept_id=con["id"], extra_revisions=2
    )
    data, meta = validate_paginated(api.list_change_orders(sid, SO, params={"concept_id": con["id"]}))
    assert meta["total_count"] == 1
    assert any(c["id"] == co["id"] for c in data)


def test_clear_license_reserved_to_cleared(api):
    """PRD §3.7: "A StudioOps operator clears a license, moving it from RESERVED to
    CLEARED, which is allowed only while the parent project is not yet terminal"

    Design: Corner/endpoints/clear_license_reserved_to_cleared_action
    """
    studio, client, project, _ = create_and_activate_project([20000], deposit_pct=0.20, service_type="WEB")
    sid, pid = studio["id"], project["id"]
    lic = get_success_data(api.create_license(
        sid, create_license_payload(pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=1000), SO
    ))
    cleared = validate_success(api.clear_license(sid, lic["id"], SO))
    assert cleared["status"] == "CLEARED"


def test_clock_default_startup_blocks_mark_overdue_before_due(api):
    """PRD §2.11: "At startup the clock reads exactly 2026-03-01T00:00:00Z, and
    before any clock-setting call it holds that default and never falls back to real
    time."
    PRD §3.6: "calling mark-overdue before that instant is rejected with
    ERR_NOT_YET_DUE."

    Design: Corner/endpoints/clock_default_startup_time_when_unset
    """
    # No clock set: default 2026-03-01. Invoice due 2026-03-02 is not yet due.
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.0, tax_rate=0.0
    )
    sid = studio["id"]
    inv = issue_invoice(sid, milestones[0]["id"], "2026-03-02T00:00:00Z")
    resp = api.mark_invoice_overdue(sid, inv["id"], BO)
    validate_error(resp, ApiErrorId.ERR_NOT_YET_DUE.value)


# --- rbac ---

def test_designer_cannot_approve_concept_unauthorized(api):
    """PRD §2.1: "When an authenticated caller invokes an operation its role is not
    permitted to perform, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/rbac_designer_cannot_approve_concept_unauthorized
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid)
    resp = api.approve_concept(sid, pid, con["id"], DES)  # Designer is not Client
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_billingops_cannot_create_project_unauthorized(api):
    """PRD §2.1: "StudioOps is the studio operator who manages projects" — project
    creation is a StudioOps capability; another role attempting it yields
    ERR_UNAUTHORIZED (PRD §2.1: "the request is rejected with ERR_UNAUTHORIZED").

    Design: Corner/rbac/rbac_billingops_cannot_create_project_unauthorized
    """
    studio, client = setup_studio_client()
    resp = api.create_project(
        studio["id"],
        {"client_id": client["id"], "title": "P", "service_type": "LOGO", "deposit_pct": 0.30},
        BO,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_acting_on_foreign_project_unauthorized(api):
    """PRD §2.1: "a Client acting on a project, moodboard, concept, deliverable, or
    change order that does not trace back to its own client_id is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/rbac_client_acting_on_foreign_project_unauthorized
    """
    studio = create_studio()
    sid = studio["id"]
    client_a = create_active_client(sid, company_name="A", contact_email="a@a.com")
    client_b = create_active_client(sid, company_name="B", contact_email="b@b.com")
    project = create_draft_project(sid, client_a["id"], deposit_pct=0.30)
    pid = project["id"]
    add_milestone(sid, pid, 10000, 1)
    get_success_data(api.activate_project(sid, pid, SO))
    mb = get_success_data(api.create_moodboard(sid, pid, {"title": "MB"}, DES))
    get_success_data(api.submit_moodboard(sid, pid, mb["id"], DES))
    # client B tries to approve client A's moodboard
    resp = api.approve_moodboard(sid, pid, mb["id"], make_client_headers(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_shared_get_studio_allowed_for_designer(api):
    """PRD §4: the GET /studios/{studioId} endpoint authorizes "StudioOps, BillingOps,
    Designer, Client" — a shared read succeeds for a non-owning peer role.
    PRD §2.4: "Every persisted resource ... carries a system-generated id"

    Design: Corner/rbac/rbac_shared_get_studio_allowed_for_all_roles
    """
    studio = create_studio(name="S")
    data = validate_success(api.get_studio(studio["id"], DES))
    assert data["name"] == "S"


def test_studioops_cannot_pay_invoice_unauthorized(api):
    """PRD §2.1: "BillingOps is the billing operator who issues and pays invoices" —
    invoice payment is a BillingOps capability; another role attempting it yields
    ERR_UNAUTHORIZED (PRD §2.1: "the request is rejected with ERR_UNAUTHORIZED").

    Design: Corner/rbac/rbac_studioops_cannot_pay_invoice_unauthorized
    """
    studio, client, project, milestones = create_project_in_delivery(
        [40000], deposit_pct=0.0, tax_rate=0.0
    )
    sid = studio["id"]
    inv = issue_invoice(sid, milestones[0]["id"], "2026-04-01T00:00:00Z")
    resp = api.pay_invoice(sid, inv["id"], SO)  # StudioOps is not BillingOps
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# --- cross_cutting_complexity_layers ---

def test_change_order_create_with_current_version_succeeds(api):
    """PRD §2.7: "A change-order creation request must carry an
    expected_project_version field whose value is the version of the target project
    as the client last observed it"

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_change_order_create_succeeds
    """
    studio, client, project, _ = create_and_activate_project(
        [100000], deposit_pct=0.30, service_type="IDENTITY"
    )
    sid, pid = studio["id"], project["id"]
    pv = project["version"]
    data = validate_success(
        api.create_change_order(sid, create_change_order_payload(pid, 25000, pv, reason="SCOPE_ADD"), SO),
        expected_status=201,
    )
    assert data["status"] == "PROPOSED"


def test_change_order_approval_increments_project_version_by_one(api):
    """PRD §3.8: "The project's version is incremented by one as part of this
    approval, which is exactly what later renders any in-flight change-order proposal
    holding an older expected_project_version stale."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_change_order_approval
    """
    studio, client, project, _ = create_project_in_concept(
        [100000], deposit_pct=0.30, service_type="IDENTITY"
    )
    sid, pid, cid = studio["id"], project["id"], client["id"]
    pv_before = validate_success(api.get_project(sid, pid, SO))["version"]
    co = propose_change_order(sid, pid, 25000, pv_before, reason="SCOPE_ADD")
    approve_change_order(sid, co["id"], cid)
    pv_after = validate_success(api.get_project(sid, pid, SO))["version"]
    assert pv_after == pv_before + 1


def test_extra_revision_change_order_raises_effective_limit(api):
    """PRD §3.4: "The number of rounds a concept may absorb is its effective revision
    limit: its own revision_limit plus the sum of the extra_revisions granted by
    every approved change order whose reason is EXTRA_REVISION and whose concept_id
    names this concept."

    Design: Corner/cross_cutting_complexity_layers/extra_revision_change_order_raises_effective_revision_limit
    """
    studio, client, project, _ = create_project_in_concept(
        [10000], deposit_pct=0.30, service_type="IDENTITY"
    )
    sid, pid, cid = studio["id"], project["id"], client["id"]
    ch = make_client_headers(cid)
    pv = validate_success(api.get_project(sid, pid, SO))["version"]
    con = get_success_data(api.create_concept(sid, pid, {"label": "Route A", "revision_limit": 1}, DES))
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))  # rounds_used -> 1
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    # grant 1 extra revision via approved EXTRA_REVISION change order
    co = propose_change_order(sid, pid, 0, pv, reason="EXTRA_REVISION", concept_id=con["id"], extra_revisions=1)
    approve_change_order(sid, co["id"], cid)
    # second revision now allowed (effective limit 2)
    data = validate_success(api.request_concept_revision(sid, pid, con["id"], ch))
    assert data["status"] == "IN_REVISION"
    assert data["rounds_used"] == 2


# --- consistency_model ---

def test_activation_response_carries_freshly_computed_ledger(api):
    """PRD §3.2: "On a successful activation the server snapshots the money model:
    base_scope_cents becomes the sum of the amount_cents of every milestone on the
    project; contract_value_cents is set equal to base_scope_cents ... ;
    provisional_deposit_cents is set to the base scope multiplied by the project's
    deposit_pct, rounded half up to whole cents"

    Design: Corner/consistency_model/immediate_consistency_computed_fields_in_same_response
    """
    studio, client = setup_studio_client()
    sid = studio["id"]
    project = create_draft_project(sid, client["id"], deposit_pct=0.30, service_type="IDENTITY")
    pid = project["id"]
    add_milestone(sid, pid, 20000, 1)
    add_milestone(sid, pid, 40000, 2)
    data = validate_success(api.activate_project(sid, pid, SO))
    assert data["base_scope_cents"] == 60000
    assert data["contract_value_cents"] == 60000
    assert data["provisional_deposit_cents"] == 18000
