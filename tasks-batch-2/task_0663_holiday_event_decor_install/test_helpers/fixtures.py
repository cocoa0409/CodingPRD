"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" style errors instead of confusing assertion failures.

Identity threading: ClientContact is entity_backed:Client, so every ownership-gated call
(sign / accept / reject / decline) uses make_client_contact_headers(client_id) with the
owning Client's id. Falling back to the shared constant would make every ownership check reject.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload,
    create_contract_payload,
    create_design_proposal_payload,
    create_line_item_payload,
    create_inventory_item_payload,
    create_crew_payload,
    create_work_order_payload,
    create_visit_payload,
    create_schedule_payload,
    create_storage_bay_payload,
    create_storage_lot_payload,
    create_damage_report_payload,
    create_renewal_offer_payload,
)
from .test_users import TEST_USERS, make_client_contact_headers

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ─── Atomic creators ──────────────────────────────────────────────────────
def create_client(account_type="COMMERCIAL", **overrides):
    """Create a Client. Returns the client dict."""
    payload = create_client_payload(account_type=account_type, **overrides)
    return get_success_data(api_client.create_client(payload, AM))


def create_inventory_item(sku, **overrides):
    """Create an InventoryItem (PlatformAdmin). Returns the item dict."""
    payload = create_inventory_item_payload(sku=sku, **overrides)
    return get_success_data(api_client.create_inventory_item(payload, PA))


def create_crew(crew_name="Test Crew", **overrides):
    """Create a Crew (FieldSupervisor). Returns the crew dict."""
    payload = create_crew_payload(crew_name=crew_name, **overrides)
    return get_success_data(api_client.create_crew(payload, FS))


def create_storage_bay(bay_code, capacity_units=100):
    """Create a StorageBay (FieldSupervisor). Returns the bay dict."""
    payload = create_storage_bay_payload(bay_code=bay_code, capacity_units=capacity_units)
    return get_success_data(api_client.create_storage_bay(payload, FS))


def create_draft_contract(client_id, **overrides):
    """Create a DRAFT contract under a client. Returns the contract dict."""
    payload = create_contract_payload(**overrides)
    return get_success_data(api_client.create_contract(client_id, payload, AM))


# ─── Tier 1/2: Proposal + line items, walked to a target contract state ────
def setup_proposal_with_lines(contract_id, lines, theme="Test Theme", is_custom=False):
    """Create one DRAFT proposal with the given line items, then SUBMIT it.

    `lines` is a list of dicts: {inventory_item_id, quantity, unit_install_cents}.
    Returns the proposal dict (post-submit)."""
    proposal = get_success_data(api_client.create_design_proposal(
        contract_id, create_design_proposal_payload(theme=theme, is_custom=is_custom), AM))
    for line in lines:
        get_success_data(api_client.create_line_item(
            proposal["id"],
            create_line_item_payload(**line),
            AM,
        ))
    submitted = get_success_data(api_client.submit_proposal(proposal["id"], AM))
    return submitted


def setup_signed_contract(client_id, contract_id, proposal_id):
    """From a DRAFT contract carrying a SUBMITTED proposal: propose → accept → sign.

    Returns the signed contract dict (with computed fee fields)."""
    contract = get_success_data(api_client.propose_contract(client_id, contract_id, AM))
    contract_v = contract["version"]
    cc = make_client_contact_headers(client_id)
    get_success_data(api_client.accept_proposal(
        proposal_id, {"expected_contract_version": contract_v}, cc))
    signed = get_success_data(api_client.sign_contract(client_id, contract_id, cc))
    return signed


def setup_active_contract(
    account_type="COMMERCIAL",
    contract_type="COMMERCIAL",
    sku="SKU-FIX",
    sku_overrides=None,
    contract_overrides=None,
    line_quantity=4,
    unit_install_cents=5000,
    theme="Test Theme",
    is_custom=False,
):
    """Full chain: client → inventory → DRAFT contract → proposal+line → submit →
    propose → accept → sign → activate.

    Returns dict with keys: client_id, contract_id, proposal_id, sku_id, contract (active).
    """
    sku_overrides = sku_overrides or {}
    contract_overrides = contract_overrides or {}

    client = create_client(account_type=account_type)
    item = create_inventory_item(sku=sku, **sku_overrides)
    contract = create_draft_contract(
        client["id"], contract_type=contract_type, **contract_overrides)
    proposal = setup_proposal_with_lines(
        contract["id"],
        [{"inventory_item_id": item["id"], "quantity": line_quantity,
          "unit_install_cents": unit_install_cents}],
        theme=theme,
        is_custom=is_custom,
    )
    setup_signed_contract(client["id"], contract["id"], proposal["id"])
    active = get_success_data(api_client.activate_contract(client["id"], contract["id"], AM))
    return {
        "client_id": client["id"],
        "contract_id": contract["id"],
        "proposal_id": proposal["id"],
        "sku_id": item["id"],
        "contract": active,
    }


# ─── Tier 3: Work-order lifecycle shortcuts ────────────────────────────────
def create_work_order_with_visits(contract_id, job_type="INSTALL", visits=None):
    """Create a WorkOrder and add visits. `visits` is a list of visit-payload override
    dicts (stop_sequence/leg_distance_km/on_site_minutes). Defaults to one 5km/60min leg.

    Returns (work_order, [visit, ...])."""
    if visits is None:
        visits = [{"stop_sequence": 1, "leg_distance_km": 5.0, "on_site_minutes": 60}]
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(contract_id, job_type=job_type), FS))
    created_visits = []
    for v in visits:
        created_visits.append(get_success_data(
            api_client.create_visit(wo["id"], create_visit_payload(**v), FS)))
    return wo, created_visits


def schedule_work_order(wo_id, crew_id, scheduled_date):
    """Schedule a work order onto a crew/date. Returns the scheduled work order dict."""
    return get_success_data(api_client.schedule_work_order(
        wo_id, create_schedule_payload(crew_id, scheduled_date), FS))


def create_completed_takedown(
    active_ctx,
    crew_id,
    scheduled_date="2027-01-10T00:00:00Z",
    actual_minutes=55,
):
    """From an active-contract context dict (see setup_active_contract): build a TAKEDOWN
    work order, schedule it, dispatch it, complete its single visit and complete the WO.

    Returns the completed work-order dict."""
    wo, visits = create_work_order_with_visits(active_ctx["contract_id"], job_type="TAKEDOWN")
    schedule_work_order(wo["id"], crew_id, scheduled_date)
    get_success_data(api_client.dispatch_work_order(wo["id"], FS))
    get_success_data(api_client.complete_visit(
        visits[0]["id"], {"actual_minutes": actual_minutes}, FS))
    completed = get_success_data(api_client.complete_work_order(wo["id"], FS))
    return completed


# ─── Tier 4: Renewal posture ───────────────────────────────────────────────
def setup_sent_renewal_offer(active_ctx, expires_at="2026-12-31T00:00:00Z"):
    """From an active-contract context: create a renewal offer (moves contract
    ACTIVE→RENEWAL_OFFERED) then SEND it.

    Returns dict with keys: offer (SENT), provisional_price_cents, contract_id, client_id."""
    active = get_success_data(api_client.get_contract(active_ctx["contract_id"], AM))
    offer = get_success_data(api_client.create_renewal_offer(
        active_ctx["contract_id"],
        create_renewal_offer_payload(expires_at, active["version"]),
        AM,
    ))
    sent = get_success_data(api_client.send_renewal_offer(offer["id"], AM))
    return {
        "offer": sent,
        "provisional_price_cents": offer.get("provisional_price_cents"),
        "contract_id": active_ctx["contract_id"],
        "client_id": active_ctx["client_id"],
    }


# ─── Tier 5: Storage lot lifecycle ─────────────────────────────────────────
def create_stored_lot(contract_id, bay_id, unit_count, stored_from, released_on):
    """Reserve a storage lot then check it in (RESERVED→STORED). Returns the stored lot dict."""
    lot = get_success_data(api_client.create_storage_lot(
        create_storage_lot_payload(
            contract_id, bay_id, unit_count=unit_count,
            stored_from=stored_from, released_on=released_on),
        FS,
    ))
    stored = get_success_data(api_client.check_in_storage_lot(lot["id"], FS))
    return stored
