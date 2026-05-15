"""Composite setup helpers — multi-step preambles tests can reuse.

The exhibition-venue pipeline is long: exhibition draft → hall →
ACTIVE FloorPlanVersion → booth(s) → open-intake → exhibitor
application(s) → submit → start-review → qualify → allocation(s) →
publish-allocation → confirm (or object → start-relocation → relocate
or revoke) → start-setup → safety-inspection PRE_OPEN PASS →
open-doors → tickets → scan-in / scan-out → close-doors → teardown →
work orders / dock slots / entitlements → close. Many test claims need
the system in a late-pipeline state; these helpers reach it.

IDENTITY THREADING — PRD §2.1:

- Exhibitor is ENTITY-BACKED against ExhibitorApplication. X-User-ID is
  the opaque exhibitor identifier carried as the exhibitor_id foreign
  key on ExhibitorApplication, BoothAllocation, DockSlot, WorkOrder,
  and SponsorEntitlement. Every ownership-gated Exhibitor call
  (object, confirm, dock-slot create/cancel, work-order
  create/submit/dispute/cancel, accept-make-good, waive,
  application submit/withdraw) MUST mint headers via
  make_exhibitor_headers(exhibitor_id) — never via the shared
  EXHIBITOR_FALLBACK_ID constant.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_OBJECTION_WINDOW_HOURS,
    SECONDS_PER_HOUR,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_allocation_payload,
    create_application_payload,
    create_booth_payload,
    create_dock_slot_payload,
    create_entitlement_payload,
    create_exhibition_payload,
    create_floor_plan_payload,
    create_hall_payload,
    create_safety_inspection_payload,
    create_ticket_payload,
    create_work_order_payload,
    fulfill_entitlement_payload,
    iso_now,
    iso_offset,
    iso_utc,
    make_full_modular_cells,
    object_allocation_payload,
    random_exhibitor_id,
    random_suffix,
    relocate_payload,
    revoke_allocation_payload,
    utcnow,
    work_order_line,
)
from .test_users import (
    TEST_USERS,
    make_exhibitor_headers,
)


# ===========================================================================
# Clock — PRD §4 (TestHarness only)
# ===========================================================================
def advance_clock(*, to: str) -> Dict[str, Any]:
    """POST /_clock/advance to=<ISO timestamp>. PRD §4 declares this
    endpoint exclusive to TestHarness.
    """
    return get_success_data(api_client.clock_advance(
        clock_advance_payload(to=to),
        TEST_USERS["test_harness_headers"],
    ))


def advance_clock_by_hours(hours: int) -> Dict[str, Any]:
    """Advance the server clock by `hours` hours from current real time."""
    return advance_clock(to=iso_offset(hours=hours))


# ===========================================================================
# Exhibition base — fresh DRAFT exhibition with one Hall and one ACTIVE
# FloorPlanVersion (no booths). PRD §3.1 / §3.2.
# ===========================================================================
def create_exhibition(
    *,
    theme_code: str = "GEN",
    capacity_max: int = 100,
    open_date: Optional[str] = None,
    close_date: Optional[str] = None,
    objection_window_hours: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /exhibitions. PRD §3.1: returns a DRAFT exhibition."""
    payload = create_exhibition_payload(
        theme_code=theme_code,
        capacity_max=capacity_max,
        open_date=open_date,
        close_date=close_date,
        objection_window_hours=objection_window_hours,
        **overrides,
    )
    return get_success_data(api_client.create_exhibition(
        payload, TEST_USERS["venue_admin_headers"],
    ))


def create_hall(
    exhibition_id: str,
    *,
    grid_rows: int = 5,
    grid_cols: int = 5,
    fire_safety_zone_cells: Optional[List[Dict[str, int]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /exhibitions/{id}/halls. PRD §3.2."""
    payload = create_hall_payload(
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        fire_safety_zone_cells=fire_safety_zone_cells,
        **overrides,
    )
    return get_success_data(api_client.create_hall(
        exhibition_id, payload, TEST_USERS["venue_admin_headers"],
    ))


def create_and_activate_floor_plan(
    hall_id: str,
    *,
    grid_rows: int = 5,
    grid_cols: int = 5,
    cells: Optional[List[Dict[str, Any]]] = None,
    fire_safety_cells: Optional[List[Dict[str, int]]] = None,
    power_kw: float = 2.0,
    water_lpm: float = 10.0,
    network_mbps: int = 100,
) -> Dict[str, Any]:
    """POST /halls/{hall_id}/floor-plans then activate. PRD §3.2."""
    if cells is None:
        cells = make_full_modular_cells(
            grid_rows, grid_cols,
            fire_safety_cells=fire_safety_cells,
            power_kw=power_kw, water_lpm=water_lpm, network_mbps=network_mbps,
        )
    plan = get_success_data(api_client.create_floor_plan(
        hall_id, create_floor_plan_payload(cells=cells),
        TEST_USERS["venue_admin_headers"],
    ))
    activated = get_success_data(api_client.activate_floor_plan(
        hall_id, plan["id"], TEST_USERS["venue_admin_headers"],
    ))
    return activated


def setup_exhibition_with_active_plan(
    *,
    theme_code: str = "GEN",
    capacity_max: int = 100,
    grid_rows: int = 5,
    grid_cols: int = 5,
    open_date: Optional[str] = None,
    close_date: Optional[str] = None,
    objection_window_hours: Optional[int] = None,
    fire_safety_cells: Optional[List[Dict[str, int]]] = None,
    power_kw: float = 2.0,
    water_lpm: float = 10.0,
    network_mbps: int = 100,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Fresh DRAFT exhibition + one Hall + one ACTIVE FloorPlanVersion.

    Returns (exhibition, hall, plan). PRD §3.1 lifecycle starts at DRAFT;
    PRD §3.2 allows FloorPlanVersion activation only while the owning
    Exhibition is in DRAFT.
    """
    exhibition = create_exhibition(
        theme_code=theme_code,
        capacity_max=capacity_max,
        open_date=open_date,
        close_date=close_date,
        objection_window_hours=objection_window_hours,
    )
    hall = create_hall(
        exhibition["id"],
        grid_rows=grid_rows, grid_cols=grid_cols,
        fire_safety_zone_cells=[],
    )
    plan = create_and_activate_floor_plan(
        hall["id"],
        grid_rows=grid_rows, grid_cols=grid_cols,
        fire_safety_cells=fire_safety_cells,
        power_kw=power_kw, water_lpm=water_lpm, network_mbps=network_mbps,
    )
    return exhibition, hall, plan


# ===========================================================================
# Booth helpers — PRD §3.2 (booth creation on an ACTIVE plan).
# ===========================================================================
def create_booth(
    hall_id: str,
    *,
    cells: Optional[List[Dict[str, int]]] = None,
    tier: str = "STANDARD",
    code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /halls/{hall_id}/booths. PRD §3.2 computes is_corner,
    capacities, and base_price_cents at creation.
    """
    payload = create_booth_payload(
        cells=cells, tier=tier, code=code, **overrides,
    )
    return get_success_data(api_client.create_booth(
        hall_id, payload, TEST_USERS["venue_admin_headers"],
    ))


def create_standard_booth(hall_id: str, *, row: int = 2, col: int = 2,
                          code: Optional[str] = None) -> Dict[str, Any]:
    """Convenience: create a STANDARD booth on a single non-corner cell."""
    return create_booth(
        hall_id, cells=[{"row": row, "col": col}],
        tier="STANDARD", code=code,
    )


# ===========================================================================
# Application + Allocation builders — PRD §3.3, §3.4.
# ===========================================================================
def create_submitted_application(
    exhibition_id: str,
    *,
    exhibitor_id: Optional[str] = None,
    theme_tags: Optional[List[str]] = None,
    requested_tier: str = "STANDARD",
    sponsorship_level: Optional[str] = None,
    seniority_years: Optional[int] = None,
) -> Tuple[Dict[str, Any], str]:
    """Mint a new exhibitor_id, create application, submit it.

    Returns (application, exhibitor_id). PRD §2.1: the exhibitor_id is
    set from the X-User-ID supplied on the FIRST application created
    under that identity.
    """
    if exhibitor_id is None:
        exhibitor_id = random_exhibitor_id()
    headers = make_exhibitor_headers(exhibitor_id)
    payload = create_application_payload(
        theme_tags=theme_tags,
        requested_tier=requested_tier,
        sponsorship_level=sponsorship_level,
        seniority_years=seniority_years,
    )
    app = get_success_data(api_client.create_application(
        exhibition_id, payload, headers,
    ))
    submitted = get_success_data(api_client.submit_application(
        app["id"], headers,
    ))
    return submitted, exhibitor_id


def qualify_application(application_id: str) -> Dict[str, Any]:
    """Walk SUBMITTED → UNDER_REVIEW → QUALIFIED. PRD §3.3."""
    get_success_data(api_client.start_review_application(
        application_id, TEST_USERS["venue_admin_headers"],
    ))
    return get_success_data(api_client.qualify_application(
        application_id, TEST_USERS["venue_admin_headers"],
    ))


def create_qualified_application(
    exhibition_id: str,
    *,
    exhibitor_id: Optional[str] = None,
    theme_tags: Optional[List[str]] = None,
    requested_tier: str = "STANDARD",
    sponsorship_level: Optional[str] = None,
    seniority_years: Optional[int] = None,
) -> Tuple[Dict[str, Any], str]:
    """Build an application all the way to QUALIFIED. PRD §3.3 requires
    intake to be OPEN before submission; the caller must have opened
    intake first.

    Returns (application, exhibitor_id).
    """
    app, exhibitor_id = create_submitted_application(
        exhibition_id,
        exhibitor_id=exhibitor_id,
        theme_tags=theme_tags,
        requested_tier=requested_tier,
        sponsorship_level=sponsorship_level,
        seniority_years=seniority_years,
    )
    qualified = qualify_application(app["id"])
    return qualified, exhibitor_id


def open_intake(exhibition_id: str) -> Dict[str, Any]:
    """POST /exhibitions/{id}/open-intake. PRD §3.1: DRAFT →
    INTAKE_OPEN, requires at least one Hall with ACTIVE plan and a
    non-empty theme_code.
    """
    return get_success_data(api_client.open_intake(
        exhibition_id, TEST_USERS["venue_admin_headers"],
    ))


def create_allocation(application_id: str, booth_id: str) -> Dict[str, Any]:
    """POST /allocations. PRD §3.4: link a QUALIFIED application to an
    AVAILABLE booth; allocation starts in PROPOSED.
    """
    return get_success_data(api_client.create_allocation(
        create_allocation_payload(
            application_id=application_id,
            booth_id=booth_id,
        ),
        TEST_USERS["venue_admin_headers"],
    ))


def publish_allocation(exhibition_id: str) -> Dict[str, Any]:
    """POST /exhibitions/{id}/publish-allocation. PRD §3.4 cascades all
    PROPOSED allocations to PUBLISHED.
    """
    return get_success_data(api_client.publish_allocation(
        exhibition_id, TEST_USERS["venue_admin_headers"],
    ))


# ===========================================================================
# Composite — exhibition + booth + qualified application + allocation,
# all the way to a PUBLISHED allocation. PRD §3.1–§3.4.
# ===========================================================================
def setup_exhibition_with_published_allocation(
    *,
    theme_code: str = "GEN",
    capacity_max: int = 100,
    grid_rows: int = 5,
    grid_cols: int = 5,
    booth_tier: str = "STANDARD",
    booth_cell: Optional[Dict[str, int]] = None,
    open_date: Optional[str] = None,
    close_date: Optional[str] = None,
    objection_window_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """Active plan → one booth → submit + qualify application →
    create allocation → publish.

    Returns a dict with: exhibition, hall, plan, booth, application,
    allocation, exhibitor_id.
    """
    if booth_cell is None:
        booth_cell = {"row": 2, "col": 2}
    exhibition, hall, plan = setup_exhibition_with_active_plan(
        theme_code=theme_code,
        capacity_max=capacity_max,
        grid_rows=grid_rows, grid_cols=grid_cols,
        open_date=open_date, close_date=close_date,
        objection_window_hours=objection_window_hours,
    )
    booth = create_booth(
        hall["id"], cells=[booth_cell], tier=booth_tier,
    )
    open_intake(exhibition["id"])
    application, exhibitor_id = create_qualified_application(
        exhibition["id"],
        theme_tags=[theme_code],
        requested_tier=booth_tier,
    )
    allocation = create_allocation(application["id"], booth["id"])
    publish_allocation(exhibition["id"])
    # Refresh both exhibition (status now ALLOCATION_PUBLISHED) and
    # allocation (status now PUBLISHED, quoted_price_cents pinned).
    exhibition = get_success_data(api_client.get_exhibition(
        exhibition["id"], TEST_USERS["venue_admin_headers"],
    ))
    allocation = get_success_data(api_client.get_allocation(
        allocation["id"], TEST_USERS["venue_admin_headers"],
    ))
    return {
        "exhibition": exhibition,
        "hall": hall,
        "plan": plan,
        "booth": booth,
        "application": application,
        "allocation": allocation,
        "exhibitor_id": exhibitor_id,
    }


def confirm_allocation_as_owner(allocation_id: str, exhibitor_id: str
                                ) -> Dict[str, Any]:
    """POST /allocations/{id}/confirm under the owning exhibitor.

    PRD §3.4: only the allocation's own exhibitor may confirm.
    """
    return get_success_data(api_client.confirm_allocation(
        allocation_id, make_exhibitor_headers(exhibitor_id),
    ))


def setup_exhibition_in_setup_with_confirmed_allocation(
    *,
    theme_code: str = "GEN",
    capacity_max: int = 100,
    grid_rows: int = 5,
    grid_cols: int = 5,
    open_date: Optional[str] = None,
    close_date: Optional[str] = None,
    objection_window_hours: int = 1,  # short so /start-setup is reachable
) -> Dict[str, Any]:
    """Active plan → booth → published allocation → confirm by
    exhibitor → advance clock past objection window → start-setup.

    Returns dict with: exhibition (in SETUP, posture RESTRICTED), hall,
    plan, booth, application, allocation (CONFIRMED), exhibitor_id.

    PRD §3.1: ALLOCATION_PUBLISHED → SETUP requires every allocation to
    be CONFIRMED or REVOKED, and the objection window to have elapsed.
    """
    if open_date is None:
        open_date = iso_offset(days=10)
    if close_date is None:
        close_date = iso_offset(days=17)
    ctx = setup_exhibition_with_published_allocation(
        theme_code=theme_code,
        capacity_max=capacity_max,
        grid_rows=grid_rows, grid_cols=grid_cols,
        open_date=open_date, close_date=close_date,
        objection_window_hours=objection_window_hours,
    )
    # Owner confirms.
    confirm_allocation_as_owner(
        ctx["allocation"]["id"], ctx["exhibitor_id"],
    )
    # Advance past the objection window.
    advance_clock(to=iso_offset(hours=objection_window_hours + 1))
    # Transition to SETUP.
    ctx["exhibition"] = get_success_data(api_client.start_setup(
        ctx["exhibition"]["id"], TEST_USERS["venue_admin_headers"],
    ))
    ctx["allocation"] = get_success_data(api_client.get_allocation(
        ctx["allocation"]["id"], TEST_USERS["venue_admin_headers"],
    ))
    return ctx


def setup_open_exhibition(
    *,
    theme_code: str = "GEN",
    capacity_max: int = 100,
    grid_rows: int = 5,
    grid_cols: int = 5,
    open_date_offset_hours: int = 2,
    close_date_offset_hours: int = 200,
    objection_window_hours: int = 1,
) -> Dict[str, Any]:
    """Build all the way to Exhibition.status==OPEN, posture==OPEN.

    PRD §3.1: SETUP → OPEN requires a PRE_OPEN safety inspection with
    result=PASS and now() >= open_date.

    Returns ctx with: exhibition (OPEN), hall, plan, booth, application,
    allocation (CONFIRMED), exhibitor_id.
    """
    open_date = iso_offset(hours=open_date_offset_hours)
    close_date = iso_offset(hours=close_date_offset_hours)
    ctx = setup_exhibition_in_setup_with_confirmed_allocation(
        theme_code=theme_code,
        capacity_max=capacity_max,
        grid_rows=grid_rows, grid_cols=grid_cols,
        open_date=open_date,
        close_date=close_date,
        objection_window_hours=objection_window_hours,
    )
    # Record PRE_OPEN PASS inspection.
    get_success_data(api_client.create_safety_inspection(
        ctx["exhibition"]["id"],
        create_safety_inspection_payload(kind="PRE_OPEN", result="PASS"),
        TEST_USERS["venue_ops_headers"],
    ))
    # Advance clock past open_date.
    advance_clock(to=iso_offset(hours=open_date_offset_hours + 1))
    # Open doors.
    ctx["exhibition"] = get_success_data(api_client.open_doors(
        ctx["exhibition"]["id"], TEST_USERS["venue_admin_headers"],
    ))
    return ctx


# ===========================================================================
# Posture-driven setups for capacity / scan-in boundary tests.
# PRD §3.7.
# ===========================================================================
def setup_open_exhibition_at_occupancy(
    *,
    capacity_max: int,
    target_live_occupancy: int,
    theme_code: str = "GEN",
    extra_unscanned_tickets: int = 0,
) -> Dict[str, Any]:
    """Build an OPEN exhibition with live_occupancy == target by
    creating `target_live_occupancy` VISITOR tickets and scanning each
    one in via /tickets/{id}/scan-in. Then optionally create
    additional ISSUED tickets the caller can scan later.

    PRD §3.7: scan-in increments live_occupancy; PRD §3.1 SETUP→OPEN
    has been reached; PRD §2.9: posture==OPEN allows scanning.

    Returns ctx with: exhibition, ..., issued_tickets (the
    extra_unscanned_tickets list).
    """
    assert target_live_occupancy <= capacity_max
    ctx = setup_open_exhibition(capacity_max=capacity_max,
                                theme_code=theme_code)
    issued_extra: List[Dict[str, Any]] = []
    # First pre-load to (target_live_occupancy) via scan-in.
    for _ in range(target_live_occupancy):
        ticket = get_success_data(api_client.create_ticket(
            ctx["exhibition"]["id"],
            create_ticket_payload(kind="VISITOR", channel="ONLINE_PRESALE"),
            TEST_USERS["venue_admin_headers"],
        ))
        get_success_data(api_client.scan_in_ticket(
            ticket["id"], TEST_USERS["gate_operator_headers"],
        ))
    # Now mint extra unscanned tickets (still ISSUED).
    for _ in range(extra_unscanned_tickets):
        ticket = get_success_data(api_client.create_ticket(
            ctx["exhibition"]["id"],
            create_ticket_payload(kind="VISITOR", channel="ONLINE_PRESALE"),
            TEST_USERS["venue_admin_headers"],
        ))
        issued_extra.append(ticket)
    ctx["exhibition"] = get_success_data(api_client.get_exhibition(
        ctx["exhibition"]["id"], TEST_USERS["venue_admin_headers"],
    ))
    ctx["issued_tickets"] = issued_extra
    return ctx


# ===========================================================================
# Work orders — PRD §3.6.
# ===========================================================================
def create_draft_work_order(
    *,
    exhibition_id: str,
    allocation_id: str,
    exhibitor_id: str,
    lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """POST /work-orders. PRD §3.6 starts in DRAFT. The acting
    exhibitor MUST equal the allocation's exhibitor_id; we therefore
    mint headers via make_exhibitor_headers(exhibitor_id).
    """
    payload = create_work_order_payload(
        exhibition_id=exhibition_id,
        allocation_id=allocation_id,
        lines=lines,
    )
    return get_success_data(api_client.create_work_order(
        payload, make_exhibitor_headers(exhibitor_id),
    ))


def submit_work_order(work_order_id: str, exhibitor_id: str
                      ) -> Dict[str, Any]:
    """POST /work-orders/{id}/submit. PRD §3.6: pins billing fields."""
    return get_success_data(api_client.submit_work_order(
        work_order_id, make_exhibitor_headers(exhibitor_id),
    ))


def progress_work_order_to_executed(work_order_id: str, exhibitor_id: str
                                    ) -> Dict[str, Any]:
    """DRAFT → SUBMITTED → DISPATCHED → EXECUTED. PRD §3.6."""
    submit_work_order(work_order_id, exhibitor_id)
    get_success_data(api_client.dispatch_work_order(
        work_order_id, TEST_USERS["venue_ops_headers"],
    ))
    return get_success_data(api_client.confirm_execution(
        work_order_id, TEST_USERS["service_provider_headers"],
    ))


def setup_executed_work_order(
    *,
    lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Full pipeline to an EXECUTED work order on a CONFIRMED allocation.

    Returns ctx (exhibition/hall/plan/booth/application/allocation/
    exhibitor_id from setup_exhibition_in_setup_with_confirmed_allocation)
    plus a 'work_order' key (EXECUTED).
    """
    ctx = setup_exhibition_in_setup_with_confirmed_allocation()
    wo = create_draft_work_order(
        exhibition_id=ctx["exhibition"]["id"],
        allocation_id=ctx["allocation"]["id"],
        exhibitor_id=ctx["exhibitor_id"],
        lines=lines,
    )
    wo = progress_work_order_to_executed(wo["id"], ctx["exhibitor_id"])
    ctx["work_order"] = wo
    return ctx


# ===========================================================================
# Entitlements — PRD §3.8.
# ===========================================================================
def create_entitlement(
    exhibition_id: str,
    *,
    exhibitor_id: str,
    entitlement_code: str = "SIGNAGE",
    sponsor_tier: str = "GOLD",
    deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /exhibitions/{id}/entitlements. PRD §3.8 starts in PLANNED."""
    payload = create_entitlement_payload(
        exhibitor_id=exhibitor_id,
        entitlement_code=entitlement_code,
        sponsor_tier=sponsor_tier,
        deadline=deadline,
    )
    return get_success_data(api_client.create_entitlement(
        exhibition_id, payload, TEST_USERS["venue_admin_headers"],
    ))


def start_entitlement(entitlement_id: str) -> Dict[str, Any]:
    """POST /entitlements/{id}/start. PRD §3.8: PLANNED → IN_PROGRESS."""
    return get_success_data(api_client.start_entitlement(
        entitlement_id, TEST_USERS["venue_ops_headers"],
    ))


def setup_in_progress_entitlement(
    *,
    exhibitor_id: Optional[str] = None,
    entitlement_code: str = "SIGNAGE",
    sponsor_tier: str = "GOLD",
    deadline_offset_hours: int = 24,
) -> Dict[str, Any]:
    """Fresh exhibition → entitlement → start.

    Returns ctx with: exhibition (still DRAFT), entitlement (IN_PROGRESS),
    exhibitor_id.
    """
    exhibition = create_exhibition()
    if exhibitor_id is None:
        exhibitor_id = random_exhibitor_id()
    deadline = iso_offset(hours=deadline_offset_hours)
    ent = create_entitlement(
        exhibition["id"],
        exhibitor_id=exhibitor_id,
        entitlement_code=entitlement_code,
        sponsor_tier=sponsor_tier,
        deadline=deadline,
    )
    ent = start_entitlement(ent["id"])
    return {
        "exhibition": exhibition,
        "entitlement": ent,
        "exhibitor_id": exhibitor_id,
    }


# ===========================================================================
# Booth allocation lifecycle helpers — PRD §3.4.
# ===========================================================================
def setup_two_standard_booths_with_published_allocation_on_first(
    *,
    theme_code: str = "GEN",
    grid_rows: int = 5,
    grid_cols: int = 5,
    objection_window_hours: int = 72,
) -> Dict[str, Any]:
    """Create two STANDARD booths in the same hall; publish an
    allocation for an exhibitor on booth B1. Booth B2 remains
    AVAILABLE. PRD §3.4 — feeds objection / relocate tests.

    Returns ctx with: exhibition, hall, plan, booth_b1, booth_b2,
    application, allocation (PUBLISHED), exhibitor_id.
    """
    exhibition, hall, plan = setup_exhibition_with_active_plan(
        theme_code=theme_code,
        grid_rows=grid_rows, grid_cols=grid_cols,
        objection_window_hours=objection_window_hours,
    )
    booth_b1 = create_booth(
        hall["id"], cells=[{"row": 1, "col": 1}], tier="STANDARD", code="B1",
    )
    booth_b2 = create_booth(
        hall["id"], cells=[{"row": 3, "col": 3}], tier="STANDARD", code="B2",
    )
    open_intake(exhibition["id"])
    application, exhibitor_id = create_qualified_application(
        exhibition["id"],
        theme_tags=[theme_code],
        requested_tier="STANDARD",
    )
    allocation = create_allocation(application["id"], booth_b1["id"])
    publish_allocation(exhibition["id"])
    exhibition = get_success_data(api_client.get_exhibition(
        exhibition["id"], TEST_USERS["venue_admin_headers"],
    ))
    allocation = get_success_data(api_client.get_allocation(
        allocation["id"], TEST_USERS["venue_admin_headers"],
    ))
    return {
        "exhibition": exhibition,
        "hall": hall,
        "plan": plan,
        "booth_b1": booth_b1,
        "booth_b2": booth_b2,
        "application": application,
        "allocation": allocation,
        "exhibitor_id": exhibitor_id,
    }


def setup_objected_allocation_ready_to_relocate(
    *,
    theme_code: str = "GEN",
    objection_window_hours: int = 72,
) -> Dict[str, Any]:
    """Two STANDARD booths; allocation on B1 PUBLISHED → OBJECTED →
    RELOCATING (B1 freed back to AVAILABLE).

    Returns ctx with allocation in RELOCATING. PRD §3.4.
    """
    ctx = setup_two_standard_booths_with_published_allocation_on_first(
        theme_code=theme_code,
        objection_window_hours=objection_window_hours,
    )
    headers = make_exhibitor_headers(ctx["exhibitor_id"])
    get_success_data(api_client.object_allocation(
        ctx["allocation"]["id"],
        object_allocation_payload(reason="Wrong location"),
        headers,
    ))
    get_success_data(api_client.start_relocation(
        ctx["allocation"]["id"], TEST_USERS["venue_admin_headers"],
    ))
    ctx["allocation"] = get_success_data(api_client.get_allocation(
        ctx["allocation"]["id"], TEST_USERS["venue_admin_headers"],
    ))
    return ctx


# ===========================================================================
# Audit log retrieval.
# ===========================================================================
def list_audit_log(exhibition_id: str,
                   *, subject_kind: Optional[str] = None,
                   limit: int = 100, offset: int = 0
                   ) -> List[Dict[str, Any]]:
    """GET /exhibitions/{id}/audit-log. PRD §2.11."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if subject_kind is not None:
        params["subject_kind"] = subject_kind
    response = api_client.get_audit_log(
        exhibition_id, TEST_USERS["venue_admin_headers"], params=params,
    )
    # Lenient — return data list whatever shape.
    data = get_success_data(response)
    if isinstance(data, list):
        return data
    return data  # framework may have given the paginator already


# ===========================================================================
# Booth count helpers.
# ===========================================================================
def list_booths_in_hall(hall_id: str,
                        *, status: Optional[str] = None,
                        limit: int = 100, offset: int = 0
                        ) -> List[Dict[str, Any]]:
    """GET /halls/{hall_id}/booths. PRD §3.2."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if status is not None:
        params["status"] = status
    response = api_client.list_booths(
        hall_id, TEST_USERS["venue_admin_headers"], params=params,
    )
    data = get_success_data(response)
    if isinstance(data, list):
        return data
    return data


def count_booths_with_status(hall_id: str, status: str) -> int:
    """Count Booth rows in a hall whose status equals `status`.
    PRD §3.2. Useful for compensating-invariant tests on
    ALLOCATED-count conservation across relocations.
    """
    rows = list_booths_in_hall(hall_id, status=status)
    if isinstance(rows, dict) and "data" in rows:
        rows = rows["data"]
    return len([r for r in rows if r.get("status") == status])


__all__ = [
    "advance_clock",
    "advance_clock_by_hours",
    "create_exhibition",
    "create_hall",
    "create_and_activate_floor_plan",
    "setup_exhibition_with_active_plan",
    "create_booth",
    "create_standard_booth",
    "create_submitted_application",
    "qualify_application",
    "create_qualified_application",
    "open_intake",
    "create_allocation",
    "publish_allocation",
    "confirm_allocation_as_owner",
    "setup_exhibition_with_published_allocation",
    "setup_exhibition_in_setup_with_confirmed_allocation",
    "setup_open_exhibition",
    "setup_open_exhibition_at_occupancy",
    "create_draft_work_order",
    "submit_work_order",
    "progress_work_order_to_executed",
    "setup_executed_work_order",
    "create_entitlement",
    "start_entitlement",
    "setup_in_progress_entitlement",
    "setup_two_standard_booths_with_published_allocation_on_first",
    "setup_objected_allocation_ready_to_relocate",
    "list_audit_log",
    "list_booths_in_hall",
    "count_booths_with_status",
]
