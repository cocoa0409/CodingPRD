"""Composite setup helpers for the TI project lifecycle (PRD section 3).

Every fixture builds its preconditions from scratch through PRD-declared
endpoints — the harness restarts the server before each test, so nothing is
carried over. Entity-backed roles are always threaded through
make_tenant_rep_headers / make_contractor_rep_headers with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    approve_draw_payload,
    create_change_order_payload,
    create_contractor_payload,
    create_draw_payload,
    create_engagement_payload,
    create_lease_payload,
    create_lease_space_payload,
    create_lien_waiver_payload,
    create_milestone_payload,
    create_plan_submission_payload,
    create_property_payload,
    create_punch_item_payload,
    create_tenant_payload,
    create_ti_project_payload,
    create_work_letter_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_rep_headers,
    make_landlord_approver_headers,
    make_tenant_rep_headers,
)

PM = TEST_USERS["landlord_pm_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["building_engineer_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str) -> None:
    """Drive the server's logical clock (PRD 2.5)."""
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: portfolio hierarchy (property -> space -> tenant -> lease)
# ---------------------------------------------------------------------------

def create_property_record(**overrides) -> dict:
    return get_success_data(api_client.create_property(create_property_payload(**overrides), PM))


def create_lease_space_record(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lease_space(property_id, create_lease_space_payload(**overrides), PM)
    )


def create_tenant_record(**overrides) -> dict:
    return get_success_data(api_client.create_tenant(create_tenant_payload(**overrides), PM))


def create_lease_record(space_id: str, tenant_id: str, **overrides) -> dict:
    """Create a DRAFT lease (PRD 3.1)."""
    return get_success_data(
        api_client.create_lease(create_lease_payload(space_id, tenant_id, **overrides), PM)
    )


def create_active_lease(space_id: str, tenant_id: str, **overrides) -> dict:
    """Create + activate a lease; flips the space VACANT -> LEASED (PRD 3.1)."""
    lease = create_lease_record(space_id, tenant_id, **overrides)
    return get_success_data(api_client.activate_lease(lease["id"], PM))


def setup_property_space_tenant_lease(
    capacity: int = 2, lease_overrides: dict = None, property_overrides: dict = None
) -> dict:
    """Property + one VACANT-then-LEASED space + tenant + ACTIVE lease.

    Returns {"property", "space", "tenant", "lease"}.
    """
    prop = create_property_record(
        **(property_overrides or {"max_concurrent_construction_projects": capacity})
    )
    space = create_lease_space_record(prop["id"])
    tenant = create_tenant_record()
    lease = create_active_lease(space["id"], tenant["id"], **(lease_overrides or {}))
    return {"property": prop, "space": space, "tenant": tenant, "lease": lease}


# ---------------------------------------------------------------------------
# Tier 1/3: TIProject state progression
# ---------------------------------------------------------------------------

def create_project_record(lease_id: str, **overrides) -> dict:
    """Create an INITIATED TI project on an ACTIVE lease (PRD 3.2)."""
    return get_success_data(
        api_client.create_ti_project(lease_id, create_ti_project_payload(**overrides), PM)
    )


def create_work_letter_record(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_letter(project_id, create_work_letter_payload(**overrides), PM)
    )


def execute_work_letter_flow(project_id: str, tenant_id: str, **wl_overrides) -> dict:
    """Create -> propose -> tenant accept -> execute a work letter.

    Ends with the letter EXECUTED and the project's allowance pool stamped
    (PRD 3.2). Returns {"work_letter", "project"}.
    """
    wl = create_work_letter_record(project_id, **wl_overrides)
    wl = get_success_data(api_client.propose_work_letter(wl["id"], PM))
    wl = get_success_data(
        api_client.accept_work_letter(wl["id"], make_tenant_rep_headers(tenant_id))
    )
    wl = get_success_data(api_client.execute_work_letter(wl["id"], PM))
    project = get_success_data(api_client.get_project(project_id, PM))
    return {"work_letter": wl, "project": project}


def setup_project_negotiated(
    allowance_offer_cents: int = TEST_DEFAULTS["ALLOWANCE_OFFER_CENTS"],
    base_contract_cents: int = TEST_DEFAULTS["BASE_CONTRACT_CENTS"],
    capacity: int = 2,
    lease_overrides: dict = None,
    work_delineation: str = "SPLIT",
) -> dict:
    """Full chain through work-letter execution: project in
    WORK_LETTER_NEGOTIATION with allowance_total_cents stamped (PRD 3.2)."""
    base = setup_property_space_tenant_lease(capacity=capacity, lease_overrides=lease_overrides)
    project = create_project_record(base["lease"]["id"], base_contract_cents=base_contract_cents)
    negotiated = execute_work_letter_flow(
        project["id"],
        base["tenant"]["id"],
        allowance_offer_cents=allowance_offer_cents,
        work_delineation=work_delineation,
    )
    return {**base, "project": negotiated["project"], "work_letter": negotiated["work_letter"]}


def advance_to_plan_review(project_id: str) -> dict:
    return get_success_data(api_client.begin_plan_review(project_id, PM))


def create_plan_submission_record(project_id: str, tenant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_plan_submission(
            project_id,
            create_plan_submission_payload(**overrides),
            make_tenant_rep_headers(tenant_id),
        )
    )


def create_approved_plan_submission(project_id: str, tenant_id: str, **overrides) -> dict:
    """File -> start-review -> approve a submission (PRD 3.3)."""
    sub = create_plan_submission_record(project_id, tenant_id, **overrides)
    sub = get_success_data(api_client.start_review(sub["id"], PM))
    return get_success_data(api_client.approve_submission(sub["id"], PM))


def setup_project_in_plan_review(**kwargs) -> dict:
    """Project in PLAN_REVIEW (exactly one EXECUTED work letter)."""
    sc = setup_project_negotiated(**kwargs)
    sc["project"] = advance_to_plan_review(sc["project"]["id"])
    return sc


def setup_project_in_pre_construction(**kwargs) -> dict:
    """Project in PRE_CONSTRUCTION (one APPROVED plan submission)."""
    sc = setup_project_in_plan_review(**kwargs)
    sc["submission"] = create_approved_plan_submission(
        sc["project"]["id"], sc["tenant"]["id"]
    )
    sc["project"] = get_success_data(api_client.begin_pre_construction(sc["project"]["id"], PM))
    return sc


# ---------------------------------------------------------------------------
# Contractor registry and engagements
# ---------------------------------------------------------------------------

def create_contractor_record(**overrides) -> dict:
    return get_success_data(
        api_client.create_contractor(create_contractor_payload(**overrides), PM)
    )


def create_qualified_contractor(**overrides) -> dict:
    contractor = create_contractor_record(**overrides)
    return get_success_data(api_client.qualify_contractor(contractor["id"], PM))


def create_engagement_record(project_id: str, contractor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_engagement(
            project_id, create_engagement_payload(contractor_id, **overrides), PM
        )
    )


def approve_engagement_flow(engagement_id: str, contractor_id: str) -> dict:
    """acknowledge-rules (by the contractor) -> approve (PRD 3.4)."""
    get_success_data(
        api_client.acknowledge_rules(
            engagement_id, make_contractor_rep_headers(contractor_id)
        )
    )
    return get_success_data(api_client.approve_engagement(engagement_id, PM))


def create_active_engagement(project_id: str, contractor_id: str, **overrides) -> dict:
    """PROPOSED -> APPROVED -> ACTIVE. Requires the project to be in
    PRE_CONSTRUCTION or CONSTRUCTION (PRD 3.4)."""
    eng = create_engagement_record(project_id, contractor_id, **overrides)
    eng = approve_engagement_flow(eng["id"], contractor_id)
    return get_success_data(api_client.activate_engagement(eng["id"], PM))


def setup_project_in_construction(
    capacity: int = 2,
    allowance_offer_cents: int = TEST_DEFAULTS["ALLOWANCE_OFFER_CENTS"],
    base_contract_cents: int = TEST_DEFAULTS["BASE_CONTRACT_CENTS"],
    construction_start_date: str = TEST_DEFAULTS["CONSTRUCTION_START"],
    construction_end_date: str = TEST_DEFAULTS["CONSTRUCTION_END"],
    lease_overrides: dict = None,
) -> dict:
    """The master fixture: project in CONSTRUCTION with one ACTIVE engagement.

    Returns {"property", "space", "tenant", "lease", "project", "work_letter",
    "submission", "contractor", "engagement"}.
    """
    sc = setup_project_in_pre_construction(
        capacity=capacity,
        allowance_offer_cents=allowance_offer_cents,
        base_contract_cents=base_contract_cents,
        lease_overrides=lease_overrides,
    )
    sc["contractor"] = create_qualified_contractor()
    sc["engagement"] = create_active_engagement(
        sc["project"]["id"], sc["contractor"]["id"]
    )
    sc["project"] = get_success_data(
        api_client.start_construction(
            sc["project"]["id"],
            {
                "construction_start_date": construction_start_date,
                "construction_end_date": construction_end_date,
            },
            PM,
        )
    )
    return sc


def drive_lease_to_pre_construction(
    lease: dict,
    tenant: dict,
    base_contract_cents: int = TEST_DEFAULTS["BASE_CONTRACT_CENTS"],
    allowance_offer_cents: int = TEST_DEFAULTS["ALLOWANCE_OFFER_CENTS"],
    work_delineation: str = "SPLIT",
) -> dict:
    """Drive an existing ACTIVE lease's fresh project to PRE_CONSTRUCTION.

    Used by multi-project scenarios (several leases on one property).
    Returns {"project", "work_letter", "submission"}.
    """
    project = create_project_record(lease["id"], base_contract_cents=base_contract_cents)
    negotiated = execute_work_letter_flow(
        project["id"],
        tenant["id"],
        allowance_offer_cents=allowance_offer_cents,
        work_delineation=work_delineation,
    )
    project = advance_to_plan_review(project["id"])
    submission = create_approved_plan_submission(project["id"], tenant["id"])
    project = get_success_data(api_client.begin_pre_construction(project["id"], PM))
    return {
        "project": project,
        "work_letter": negotiated["work_letter"],
        "submission": submission,
    }


def drive_project_to_construction(
    project: dict,
    contractor: dict = None,
    construction_start_date: str = TEST_DEFAULTS["CONSTRUCTION_START"],
    construction_end_date: str = TEST_DEFAULTS["CONSTRUCTION_END"],
) -> dict:
    """Staff a PRE_CONSTRUCTION project with an ACTIVE engagement and start
    construction (PRD 3.4). Reuses the given contractor when supplied.
    Returns {"project", "contractor", "engagement"}.
    """
    contractor = contractor or create_qualified_contractor()
    engagement = create_active_engagement(project["id"], contractor["id"])
    project = get_success_data(
        api_client.start_construction(
            project["id"],
            {
                "construction_start_date": construction_start_date,
                "construction_end_date": construction_end_date,
            },
            PM,
        )
    )
    return {"project": project, "contractor": contractor, "engagement": engagement}


def setup_project_in_punch(with_milestone: bool = False, **kwargs) -> dict:
    """Project in PUNCH: construction ended per the logical clock and every
    milestone terminal (PRD 3.7). Adds "milestone" to the dict when requested.
    """
    sc = setup_project_in_construction(**kwargs)
    if with_milestone:
        sc["milestone"] = create_milestone_record(
            sc["engagement"]["id"],
            sc["contractor"]["id"],
            window_start=TEST_DEFAULTS["CONSTRUCTION_START"],
            window_end="2026-08-14T00:00:00Z",
            work_type="STANDARD",
        )
        set_logical_clock("2026-08-14T00:00:00Z")
        sc["milestone"] = get_success_data(
            api_client.complete_milestone(
                sc["milestone"]["id"], make_contractor_rep_headers(sc["contractor"]["id"])
            )
        )
    set_logical_clock(sc["project"]["construction_end_date"])
    sc["project"] = get_success_data(api_client.begin_punch(sc["project"]["id"], PM))
    return sc


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

def create_milestone_record(engagement_id: str, contractor_id: str, **overrides) -> dict:
    """Schedule a work window as the owning ContractorRep (PRD 3.4)."""
    return get_success_data(
        api_client.create_milestone(
            engagement_id,
            create_milestone_payload(**overrides),
            make_contractor_rep_headers(contractor_id),
        )
    )


# ---------------------------------------------------------------------------
# Change orders (OCC: read the fresh project version before every create)
# ---------------------------------------------------------------------------

def fresh_project_version(project_id: str) -> int:
    return get_success_data(api_client.get_project(project_id, PM))["version"]


def create_change_order_record(
    project_id: str, creator_headers: dict, lines: list, description: str = None
) -> dict:
    """Create a DRAFT change order with a fresh expected_ti_project_version."""
    payload_kwargs = {"description": description} if description else {}
    return get_success_data(
        api_client.create_change_order(
            project_id,
            create_change_order_payload(
                fresh_project_version(project_id), lines=lines, **payload_kwargs
            ),
            creator_headers,
        )
    )


def create_submitted_change_order(
    project_id: str, creator_headers: dict, lines: list, description: str = None
) -> dict:
    co = create_change_order_record(project_id, creator_headers, lines, description)
    return get_success_data(api_client.submit_change_order(co["id"], creator_headers))


def create_approved_change_order(
    project_id: str,
    creator_headers: dict,
    lines: list,
    approver_id: str = "approver-2",
    description: str = None,
) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED (markup + overage-share sweep, PRD 3.5)."""
    co = create_submitted_change_order(project_id, creator_headers, lines, description)
    return get_success_data(
        api_client.approve_change_order(co["id"], make_landlord_approver_headers(approver_id))
    )


# ---------------------------------------------------------------------------
# Disbursement draws and lien waivers
# ---------------------------------------------------------------------------

def create_draw_record(
    project_id: str,
    contractor_id: str,
    requested_amount_cents: int,
    period_end_date: str = TEST_DEFAULTS["PERIOD_END"],
    is_final_draw: bool = None,
) -> dict:
    """Create a DRAFT draw with a fresh expected_ti_project_version (PRD 3.6)."""
    overrides = {}
    if is_final_draw is not None:
        overrides["is_final_draw"] = is_final_draw
    return get_success_data(
        api_client.create_draw(
            project_id,
            create_draw_payload(
                fresh_project_version(project_id),
                period_end_date=period_end_date,
                requested_amount_cents=requested_amount_cents,
                **overrides,
            ),
            make_contractor_rep_headers(contractor_id),
        )
    )


def create_lien_waiver_record(
    draw_id: str, contractor_id: str, amount_cents: int, waiver_type: str = "UNCONDITIONAL_PROGRESS"
) -> dict:
    return get_success_data(
        api_client.create_lien_waiver(
            draw_id,
            create_lien_waiver_payload(contractor_id, amount_cents, waiver_type=waiver_type),
            make_contractor_rep_headers(contractor_id),
        )
    )


def submit_draw_with_verified_waiver(
    draw_id: str,
    contractor_id: str,
    waiver_amount_cents: int = None,
    waiver_type: str = "UNCONDITIONAL_PROGRESS",
) -> dict:
    """Submit a DRAFT draw, then attach + verify a lien waiver on it.

    waiver_amount_cents defaults to the draw's requested_amount_cents so the
    approval-time amount-match gate passes (PRD 3.6). Returns the verified
    waiver.
    """
    draw = get_success_data(
        api_client.submit_draw(draw_id, make_contractor_rep_headers(contractor_id))
    )
    waiver = create_lien_waiver_record(
        draw_id,
        contractor_id,
        waiver_amount_cents
        if waiver_amount_cents is not None
        else draw["requested_amount_cents"],
        waiver_type=waiver_type,
    )
    return get_success_data(api_client.verify_lien_waiver(waiver["id"], PM))


def create_submitted_draw(
    project_id: str,
    contractor_id: str,
    requested_amount_cents: int,
    waiver_amount_cents: int = None,
    waiver_type: str = "UNCONDITIONAL_PROGRESS",
    waiver_action: str = "verified",
    period_end_date: str = TEST_DEFAULTS["PERIOD_END"],
    is_final_draw: bool = None,
) -> dict:
    """Create + submit a draw; optionally attach a lien waiver on it.

    waiver_action: "verified" (attach + verify, the default), "pending"
    (attach but leave PENDING), or "none" (no waiver). The waiver amount
    defaults to the draw's requested_amount_cents so the approval-time
    amount-match gate passes (PRD 3.6). Returns {"draw", "waiver"}.
    """
    draw = create_draw_record(
        project_id,
        contractor_id,
        requested_amount_cents,
        period_end_date=period_end_date,
        is_final_draw=is_final_draw,
    )
    draw = get_success_data(
        api_client.submit_draw(draw["id"], make_contractor_rep_headers(contractor_id))
    )
    waiver = None
    if waiver_action != "none":
        waiver = create_lien_waiver_record(
            draw["id"],
            contractor_id,
            waiver_amount_cents
            if waiver_amount_cents is not None
            else draw["requested_amount_cents"],
            waiver_type=waiver_type,
        )
        if waiver_action == "verified":
            waiver = get_success_data(api_client.verify_lien_waiver(waiver["id"], PM))
    return {"draw": draw, "waiver": waiver}


def create_approved_draw(
    project_id: str,
    contractor_id: str,
    requested_amount_cents: int,
    approver_id: str = "approver-1",
    approved_amount_cents: int = None,
    waiver_type: str = "UNCONDITIONAL_PROGRESS",
    period_end_date: str = TEST_DEFAULTS["PERIOD_END"],
    is_final_draw: bool = None,
) -> dict:
    """Full draw ladder: create -> submit -> verified waiver -> approve.

    Returns the APPROVED draw (PRD 3.6).
    """
    submitted = create_submitted_draw(
        project_id,
        contractor_id,
        requested_amount_cents,
        waiver_type=waiver_type,
        period_end_date=period_end_date,
        is_final_draw=is_final_draw,
    )
    return get_success_data(
        api_client.approve_draw(
            submitted["draw"]["id"],
            approve_draw_payload(
                approved_amount_cents
                if approved_amount_cents is not None
                else requested_amount_cents
            ),
            make_landlord_approver_headers(approver_id),
        )
    )


# ---------------------------------------------------------------------------
# Punch items and occupancy certification
# ---------------------------------------------------------------------------

def create_punch_item_record(
    project_id: str, engagement_id: str, as_engineer: bool = False, **overrides
) -> dict:
    headers = ENGINEER if as_engineer else PM
    return get_success_data(
        api_client.create_punch_item(
            project_id, create_punch_item_payload(engagement_id, **overrides), headers
        )
    )


def resolve_punch_item_flow(punch_item_id: str, contractor_id: str) -> dict:
    """OPEN -> IN_PROGRESS -> RESOLVED by the owning ContractorRep (PRD 3.7)."""
    headers = make_contractor_rep_headers(contractor_id)
    get_success_data(api_client.start_punch_item(punch_item_id, headers))
    return get_success_data(api_client.resolve_punch_item(punch_item_id, headers))


def verify_punch_item_flow(punch_item_id: str, contractor_id: str) -> dict:
    """OPEN -> IN_PROGRESS -> RESOLVED -> VERIFIED (PRD 3.7)."""
    item = resolve_punch_item_flow(punch_item_id, contractor_id)
    return get_success_data(api_client.verify_punch_item(item["id"], ENGINEER))


def issue_certificate(project_id: str, **overrides) -> dict:
    """PUNCH -> CLOSEOUT via occupancy certificate issuance (PRD 3.7)."""
    from .factories import issue_certificate_payload

    return get_success_data(
        api_client.issue_occupancy_certificate(
            project_id, issue_certificate_payload(**overrides), PM
        )
    )
