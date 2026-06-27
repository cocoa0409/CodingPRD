"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for setup calls so a setup failure
surfaces as a clear error rather than a confusing assertion failure downstream.

Every ApiaryManager mutation threads the owning Apiary.id through
make_apiary_manager_headers(apiary_id) — never the shared constant — because
ApiaryManager is entity_backed:Apiary and ownership is gated on X-User-ID.

The logical-clock default at server start is 2026-01-01T00:00:00Z (PRD §2.4);
fixtures set the clock explicitly when a transition is time-gated.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_apiary_payload, create_registration_payload, create_hive_payload,
    create_inspection_payload, create_treatment_payload, create_honey_lot_payload,
    create_harvest_payload, create_contract_payload, create_placement_payload,
    confirm_placement_payload, create_sale_payload, create_requeen_schedule_payload,
)
from .test_users import TEST_USERS, make_apiary_manager_headers

ADMIN = TEST_USERS["platform_admin_headers"]
APIARIST = TEST_USERS["state_apiarist_headers"]
COORDINATOR = TEST_USERS["contract_coordinator_headers"]


# ─── Clock ───────────────────────────────────────────────────────────────
def set_clock(iso):
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ─── Tier 1: Apiary + registration ────────────────────────────────────────
def create_apiary(**overrides):
    """Create a yard. Returns the Apiary entity."""
    res = api_client.create_apiary(create_apiary_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_registered_apiary(effective="2026-01-01T00:00:00Z",
                             expiry="2026-12-31T00:00:00Z",
                             registration_number="CA-001", **apiary_overrides):
    """Create a yard and bring it to registration_status == ACTIVE.

    Assumes the clock is already at/after `effective` and before `expiry`.
    Returns (apiary, registration)."""
    apiary = create_apiary(**apiary_overrides)
    reg = get_success_data(api_client.create_registration(
        apiary["id"],
        create_registration_payload(registration_number=registration_number,
                                    effective_date=effective, expiry_date=expiry),
        APIARIST))
    reg = get_success_data(api_client.approve_registration(
        apiary["id"], reg["id"], APIARIST))
    return apiary, reg


def create_pending_registration(apiary_id, **overrides):
    res = api_client.create_registration(
        apiary_id, create_registration_payload(**overrides), APIARIST)
    return get_success_data(res)


# ─── Tier 2: Hives ─────────────────────────────────────────────────────────
def create_hive(apiary_id, **overrides):
    """Create a colony in the yard, owner-threaded. Returns the Hive."""
    headers = make_apiary_manager_headers(apiary_id)
    res = api_client.create_hive(create_hive_payload(apiary_id, **overrides), headers)
    return get_success_data(res)


def create_inspected_hive(apiary_id, brood_frames_observed=5,
                          honey_frames_observed=3, mites=1.0, queen_seen=True,
                          inspected_at="2026-01-06T00:00:00Z", tag="H1",
                          brood_frames=5):
    """Create a colony and record one inspection (drives inspection_strength).

    With brood=5, honey=3, mite<3.0, queenright -> point_in_time strength 59.
    Returns the Hive (re-read after inspection)."""
    headers = make_apiary_manager_headers(apiary_id)
    hive = create_hive(apiary_id, tag=tag, brood_frames=brood_frames)
    get_success_data(api_client.create_inspection(
        hive["id"],
        create_inspection_payload(
            inspected_at=inspected_at, mites_per_100_bees=mites,
            brood_frames_observed=brood_frames_observed,
            honey_frames_observed=honey_frames_observed, queen_seen=queen_seen),
        headers))
    return get_success_data(api_client.get_hive(hive["id"], headers))


# ─── Tier 3: Honey lots and harvests ───────────────────────────────────────
def create_draft_lot(apiary_id, lot_code="L1", floral_source="WILDFLOWER"):
    headers = make_apiary_manager_headers(apiary_id)
    res = api_client.create_honey_lot(
        create_honey_lot_payload(apiary_id, lot_code=lot_code,
                                 floral_source=floral_source), headers)
    return get_success_data(res)


def add_harvest(apiary_id, lot_id, hive_id, frames_pulled=4, weight_kg=12.0):
    headers = make_apiary_manager_headers(apiary_id)
    res = api_client.create_harvest(
        lot_id, create_harvest_payload(hive_id, frames_pulled=frames_pulled,
                                       weight_kg=weight_kg), headers)
    return get_success_data(res)


def setup_lot_with_harvests(apiary_id, hive_id, harvests):
    """Create a DRAFT lot and add the given harvest contributions.

    `harvests` is a list of (frames_pulled, weight_kg) tuples.
    Returns (lot, [harvest, ...])."""
    lot = create_draft_lot(apiary_id)
    rows = [add_harvest(apiary_id, lot["id"], hive_id, fp, wk)
            for (fp, wk) in harvests]
    return lot, rows


def setup_extracted_lot(apiary_id, hive_id, harvests):
    """DRAFT lot + harvests -> EXTRACTED. Returns the lot after extraction."""
    headers = make_apiary_manager_headers(apiary_id)
    lot, _ = setup_lot_with_harvests(apiary_id, hive_id, harvests)
    return get_success_data(api_client.extract_honey_lot(lot["id"], headers))


# ─── Tier 4: Contracts and placements ──────────────────────────────────────
def create_signed_contract(**overrides):
    """Create a contract and move DRAFT -> SIGNED. Returns the contract (SIGNED)."""
    contract = get_success_data(api_client.create_contract(
        create_contract_payload(**overrides), COORDINATOR))
    return get_success_data(api_client.sign_contract(contract["id"], COORDINATOR))


def propose_placement(contract_id, hive_id,
                      placement_start="2026-02-04T00:00:00Z",
                      removal_due="2026-03-06T00:00:00Z"):
    res = api_client.create_placement(
        contract_id,
        create_placement_payload(hive_id, placement_start=placement_start,
                                 removal_due=removal_due), COORDINATOR)
    return get_success_data(res)


def confirm_placement(placement_id, expected_contract_version):
    """Confirm a placement against the contract's current version."""
    res = api_client.confirm_placement(
        placement_id, confirm_placement_payload(expected_contract_version),
        COORDINATOR)
    return get_success_data(res)


def current_contract_version(contract_id):
    return get_success_data(api_client.get_contract(contract_id, COORDINATOR))["version"]


def confirm_placement_fresh(contract_id, placement_id):
    """Read the contract's live version then confirm the placement with it."""
    v = current_contract_version(contract_id)
    return confirm_placement(placement_id, v)


def setup_contract_with_confirmed_hives(apiary_id, hive_ids, required_strong_hives,
                                        max_hives_on_site=4, base_rate_cents=20000,
                                        placement_start="2026-02-04T00:00:00Z",
                                        removal_due="2026-03-06T00:00:00Z",
                                        bloom_start="2026-02-04T00:00:00Z",
                                        bloom_end="2026-03-06T00:00:00Z"):
    """SIGNED contract + one CONFIRMED placement per hive (re-reading the version
    before each confirm to respect OCC). Returns (contract, [placement, ...])."""
    contract = create_signed_contract(
        required_strong_hives=required_strong_hives,
        max_hives_on_site=max_hives_on_site, base_rate_cents=base_rate_cents,
        bloom_start=bloom_start, bloom_end=bloom_end)
    placements = []
    for hid in hive_ids:
        p = propose_placement(contract["id"], hid, placement_start, removal_due)
        p = confirm_placement_fresh(contract["id"], p["id"])
        placements.append(p)
    return get_success_data(
        api_client.get_contract(contract["id"], COORDINATOR)), placements


def setup_placed_contract(apiary_id, hive_ids, required_strong_hives,
                          max_hives_on_site=4, base_rate_cents=20000,
                          bloom_start="2026-02-04T00:00:00Z",
                          bloom_end="2026-03-06T00:00:00Z"):
    """SIGNED contract -> CONFIRMED placements -> PLACED (finalize-placement).
    Returns (contract_after_finalize, [placement, ...])."""
    contract, placements = setup_contract_with_confirmed_hives(
        apiary_id, hive_ids, required_strong_hives,
        max_hives_on_site=max_hives_on_site, base_rate_cents=base_rate_cents,
        placement_start=bloom_start, removal_due=bloom_end,
        bloom_start=bloom_start, bloom_end=bloom_end)
    placed = get_success_data(
        api_client.finalize_placement(contract["id"], COORDINATOR))
    return placed, placements


# ─── Tier 5: Treatments / blocking ─────────────────────────────────────────
def apply_treatment(apiary_id, hive_id, product="APIVAR",
                    applied_at="2026-02-10T00:00:00Z", duration_days=42):
    headers = make_apiary_manager_headers(apiary_id)
    res = api_client.create_treatment(
        hive_id, create_treatment_payload(product=product, applied_at=applied_at,
                                          duration_days=duration_days), headers)
    return get_success_data(res)


def setup_blocked_lot(apiary_id, hive_id,
                      applied_at="2026-02-10T00:00:00Z", duration_days=42):
    """DRAFT lot with a RECORDED harvest from `hive_id`, then APIVAR treatment on
    that hive which cascades the lot DRAFT -> BLOCKED. Returns (lot, treatment)."""
    lot, _ = setup_lot_with_harvests(apiary_id, hive_id, [(4, 12.0)])
    tx = apply_treatment(apiary_id, hive_id, product="APIVAR",
                         applied_at=applied_at, duration_days=duration_days)
    return lot, tx


# ─── Tier 6: Queen / nuc sales ─────────────────────────────────────────────
def reserve_sale(apiary_id, source_hive_id, product_type="NUC",
                 frames_drawn=3, price_cents=18000):
    res = api_client.create_sale(
        apiary_id,
        create_sale_payload(source_hive_id, product_type=product_type,
                            frames_drawn=frames_drawn, price_cents=price_cents),
        COORDINATOR)
    return get_success_data(res)


def setup_shipped_nuc(apiary_id, source_hive_id, frames_drawn=3, price_cents=18000):
    """Reserve a NUC sale from the source hive and ship it. Returns the sale."""
    sale = reserve_sale(apiary_id, source_hive_id, product_type="NUC",
                        frames_drawn=frames_drawn, price_cents=price_cents)
    return get_success_data(api_client.ship_sale(sale["id"], COORDINATOR))


# ─── Tier 7: Requeen schedules ─────────────────────────────────────────────
def setup_queenless_with_schedule(apiary_id, hive_id,
                                  due_date="2026-04-01T00:00:00Z", reason="QUEENLESS"):
    """Mark the hive QUEENLESS and create a SCHEDULED requeen. Returns the schedule."""
    headers = make_apiary_manager_headers(apiary_id)
    get_success_data(api_client.mark_queenless(hive_id, headers))
    res = api_client.create_requeen_schedule(
        hive_id, create_requeen_schedule_payload(due_date=due_date, reason=reason),
        headers)
    return get_success_data(res)
