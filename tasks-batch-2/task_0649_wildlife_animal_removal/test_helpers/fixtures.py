"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for setup calls so a setup failure
produces a clear "Setup step failed" error rather than an opaque assertion later.

Identity threading: PropertyOwner is entity_backed:ServiceAccount and FieldTechnician
is entity_backed:Technician, so ownership-gated calls thread the real entity id via
make_property_owner_headers(account_id) / make_field_technician_headers(technician_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_service_account_payload,
    create_property_payload,
    create_species_profile_payload,
    create_technician_payload,
    create_inspection_payload,
    create_entry_point_payload,
    create_quote_payload,
    create_line_item_payload,
    create_accept_payload,
    create_trap_placement_payload,
    create_capture_payload,
    create_exclusion_repair_payload,
    create_permit_approve_payload,
)
from .test_users import (
    TEST_USERS,
    make_dispatcher_headers,
    make_compliance_officer_headers,
    make_property_owner_headers,
    make_field_technician_headers,
)

_DISPATCHER = TEST_USERS["dispatcher_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Unique code helper ────────────────────────────────────────────────────
# species `code` must be unique across all SpeciesProfile (PRD §3.1). Tests run
# against a fresh DB each time, but a single test may need several species; the
# counter keeps codes distinct within one process.
_code_counter = {"n": 0}


def _unique_code(prefix="SP"):
    _code_counter["n"] += 1
    return f"{prefix}_{_code_counter['n']}"


# ─── Tier 0: Atomic creates ────────────────────────────────────────────────

def create_account(account_name="Test Account", contact_email="owner@example.com"):
    return get_success_data(api_client.create_service_account(
        create_service_account_payload(account_name=account_name, contact_email=contact_email),
        _DISPATCHER,
    ))


def create_property(account_id, latitude=40.0, longitude=-75.0):
    return get_success_data(api_client.create_property(
        create_property_payload(account_id, latitude=latitude, longitude=longitude),
        _DISPATCHER,
    ))


def create_species(is_regulated=False, relocation_min_miles=0, relocation_max_miles=50,
                   base_trap_fee_cents=4000, risk_weight=1.0, common_name="Species",
                   code=None, **overrides):
    payload = create_species_profile_payload(
        common_name=common_name,
        code=code or _unique_code("SP"),
        is_regulated=is_regulated,
        relocation_min_miles=relocation_min_miles,
        relocation_max_miles=relocation_max_miles,
        base_trap_fee_cents=base_trap_fee_cents,
        risk_weight=risk_weight,
        **overrides,
    )
    return get_success_data(api_client.create_species_profile(payload, _COMPLIANCE))


def create_technician(license_tier="CERTIFIED", kit_trap_capacity=5, full_name="Tech"):
    return get_success_data(api_client.create_technician(
        create_technician_payload(full_name=full_name, license_tier=license_tier,
                                  kit_trap_capacity=kit_trap_capacity),
        _DISPATCHER,
    ))


# ─── Tier 1: Inspection state progression ──────────────────────────────────

def create_draft_inspection(property_id, scheduled_for="2026-04-02T09:00:00Z", is_emergency=False):
    return get_success_data(api_client.create_inspection(
        property_id,
        create_inspection_payload(scheduled_for=scheduled_for, is_emergency=is_emergency),
        _DISPATCHER,
    ))


def add_entry_point(inspection_id, species_id, severity="MODERATE", estimated_individuals=1,
                    location_label="gap"):
    return get_success_data(api_client.create_entry_point(
        inspection_id,
        create_entry_point_payload(species_id, severity=severity,
                                   estimated_individuals=estimated_individuals,
                                   location_label=location_label),
        _DISPATCHER,
    ))


def complete_inspection(property_id, inspection_id):
    return get_success_data(api_client.complete_inspection(property_id, inspection_id, _DISPATCHER))


# ─── Tier 2: A completed inspection with caller-controlled entry points ─────

def setup_completed_inspection(entry_points=None, is_emergency=False,
                               account_name="Acct", latitude=40.0, longitude=-75.0):
    """account -> property -> (default species) -> draft inspection -> N entry points -> complete.

    entry_points: list of dicts, each may carry
        {species (entity), severity, estimated_individuals, location_label}.
    If omitted, one default MINOR entry point on a fresh non-regulated species is added.

    Returns dict: account, property, inspection (COMPLETED), entry_points (list), species (list).
    """
    account = create_account(account_name=account_name)
    prop = create_property(account["id"], latitude=latitude, longitude=longitude)
    insp = create_draft_inspection(prop["id"], is_emergency=is_emergency)

    eps = []
    species_used = []
    if entry_points is None:
        sp = create_species()
        species_used.append(sp)
        eps.append(add_entry_point(insp["id"], sp["id"], severity="MINOR",
                                   estimated_individuals=1))
    else:
        for spec in entry_points:
            sp = spec.get("species") or create_species()
            species_used.append(sp)
            eps.append(add_entry_point(
                insp["id"], sp["id"],
                severity=spec.get("severity", "MODERATE"),
                estimated_individuals=spec.get("estimated_individuals", 1),
                location_label=spec.get("location_label", "gap"),
            ))

    insp_completed = complete_inspection(prop["id"], insp["id"])
    return {
        "account": account,
        "property": prop,
        "inspection": insp_completed,
        "entry_points": eps,
        "species": species_used,
    }


# ─── Tier 3: Quote build / send / accept ────────────────────────────────────

def setup_draft_quote(line_items=None, entry_points=None, is_emergency=False,
                      account_name="Acct"):
    """Build a DRAFT quote on a COMPLETED inspection with caller-supplied line items.

    line_items: list of dicts, each {species (entity), line_type, quantity, unit_price_cents}.
        If a species is not supplied, the inspection's first species is reused.

    Returns dict (superset of setup_completed_inspection) plus: quote, line_items (list).
    """
    base = setup_completed_inspection(entry_points=entry_points, is_emergency=is_emergency,
                                      account_name=account_name)
    insp = base["inspection"]
    default_species = base["species"][0]

    quote = get_success_data(api_client.create_quote(
        create_quote_payload(insp["id"], insp["version"]),
        _DISPATCHER,
    ))

    li_objs = []
    if line_items is None:
        line_items = [{"line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000}]
    for li in line_items:
        sp = li.get("species") or default_species
        li_objs.append(get_success_data(api_client.create_line_item(
            quote["id"],
            create_line_item_payload(sp["id"], line_type=li.get("line_type", "TRAP"),
                                     quantity=li.get("quantity", 1),
                                     unit_price_cents=li.get("unit_price_cents", 4000)),
            _DISPATCHER,
        )))

    base["quote"] = quote
    base["line_items"] = li_objs
    return base


def setup_sent_quote(**kwargs):
    """setup_draft_quote then POST /quotes/{id}/send. Returns dict with refreshed quote (SENT)."""
    base = setup_draft_quote(**kwargs)
    sent = get_success_data(api_client.send_quote(base["quote"]["id"], _DISPATCHER))
    base["quote"] = sent
    return base


def setup_open_work_order(technician=None, **kwargs):
    """Full chain through quote accept -> OPEN work order.

    technician: a Technician entity (default CERTIFIED kit 5). The accept threads the
    PropertyOwner identity via the owning account id.

    Returns dict (superset of setup_sent_quote) plus: technician, work_order.
    """
    base = setup_sent_quote(**kwargs)
    if technician is None:
        technician = create_technician()
    owner_headers = make_property_owner_headers(base["account"]["id"])
    work_order = get_success_data(api_client.accept_quote(
        base["quote"]["id"],
        create_accept_payload(technician["id"]),
        owner_headers,
    ))
    base["technician"] = technician
    base["work_order"] = work_order
    return base


# ─── Tier 3b: Trap / repair execution shortcuts ─────────────────────────────

def set_trap(work_order_id, species_id, technician_id,
             window_start="2026-04-03T09:00:00Z", window_end="2026-04-03T10:00:00Z"):
    return get_success_data(api_client.create_trap_placement(
        work_order_id,
        create_trap_placement_payload(species_id, technician_id,
                                      window_start=window_start, window_end=window_end),
        make_field_technician_headers(technician_id),
    ))


def relocate_capture(trap_placement_id, technician_id, release_latitude=40.145,
                     release_longitude=-75.0, captured_at="2026-04-03T12:00:00Z"):
    return get_success_data(api_client.create_capture(
        trap_placement_id,
        create_capture_payload(captured_at=captured_at, release_latitude=release_latitude,
                               release_longitude=release_longitude),
        make_field_technician_headers(technician_id),
    ))


def pull_trap(trap_placement_id, technician_id):
    return get_success_data(api_client.pull_trap_placement(
        trap_placement_id, make_field_technician_headers(technician_id)))


def start_repair(work_order_id, entry_point_id, technician_id, sanitation_included=False):
    return get_success_data(api_client.create_exclusion_repair(
        work_order_id,
        create_exclusion_repair_payload(entry_point_id, sanitation_included=sanitation_included),
        make_field_technician_headers(technician_id),
    ))


def complete_repair(work_order_id, repair_id, technician_id):
    return get_success_data(api_client.complete_exclusion_repair(
        work_order_id, repair_id, make_field_technician_headers(technician_id)))


# ─── Tier 3c: Permit helpers ────────────────────────────────────────────────

def get_first_permit(work_order_id):
    permits, _meta = _get_list(api_client.list_work_order_permits(work_order_id, _COMPLIANCE))
    assert permits, "Expected at least one permit on the work order"
    return permits[0]


def deny_first_permit(work_order_id):
    permit = get_first_permit(work_order_id)
    return get_success_data(api_client.deny_permit(permit["id"], _COMPLIANCE))


def approve_first_permit(work_order_id, permit_number="REG-2026-001"):
    permit = get_first_permit(work_order_id)
    return get_success_data(api_client.approve_permit(
        permit["id"], create_permit_approve_payload(permit_number=permit_number), _COMPLIANCE))


def _get_list(response):
    """Lenient list reader returning (data, meta) for setup steps."""
    body = response.json()
    return body["data"], body["meta"]


# ─── Tier 4: Fetch helpers (refresh current state) ──────────────────────────

def fetch_work_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, _DISPATCHER))


def fetch_quote(quote_id):
    return get_success_data(api_client.get_quote(quote_id, _DISPATCHER))


def fetch_technician(technician_id):
    return get_success_data(api_client.get_technician(technician_id, _DISPATCHER))


def fetch_property(property_id):
    return get_success_data(api_client.get_property(property_id, _DISPATCHER))


def fetch_trap_placement(trap_placement_id):
    return get_success_data(api_client.get_trap_placement(trap_placement_id, _DISPATCHER))


def fetch_exclusion_repair(repair_id):
    return get_success_data(api_client.get_exclusion_repair(repair_id, _DISPATCHER))


def fetch_inspection(inspection_id):
    return get_success_data(api_client.get_inspection(inspection_id, _DISPATCHER))


# ─── Tier 5: Closed work order + warranty ───────────────────────────────────

def setup_closed_work_order_via_pull_and_seal(clock_at=None, sanitation_included=False,
                                              account_name="Closed"):
    """Drive a single-entry-point, single-TRAP-line + single-EXCLUSION-line work order to CLOSED:
    accept -> set trap -> pull trap (removal CLEARED) -> start repair -> complete repair
    (exclusion SEALED -> auto-close).

    If clock_at is set, the logical clock is set first so the close timestamp is deterministic.
    Returns dict with technician, work_order (refreshed, CLOSED), entry_point, repair.
    """
    if clock_at is not None:
        get_success_data(api_client.set_clock({"to_iso8601": clock_at}, _DISPATCHER))

    sp = create_species(relocation_min_miles=0, relocation_max_miles=50)
    base = setup_open_work_order(
        entry_points=[{"species": sp, "severity": "MINOR", "estimated_individuals": 1}],
        line_items=[
            {"species": sp, "line_type": "TRAP", "quantity": 1, "unit_price_cents": 4000},
            {"species": sp, "line_type": "EXCLUSION", "quantity": 1, "unit_price_cents": 9000},
        ],
        account_name=account_name,
    )
    wo = base["work_order"]
    tech = base["technician"]
    ep = base["entry_points"][0]

    trap = set_trap(wo["id"], sp["id"], tech["id"])
    pull_trap(trap["id"], tech["id"])  # removal -> CLEARED
    repair = start_repair(wo["id"], ep["id"], tech["id"], sanitation_included=sanitation_included)
    complete_repair(wo["id"], repair["id"], tech["id"])  # exclusion -> SEALED -> auto-close

    base["work_order"] = fetch_work_order(wo["id"])
    base["repair"] = repair
    base["entry_point"] = ep
    return base
