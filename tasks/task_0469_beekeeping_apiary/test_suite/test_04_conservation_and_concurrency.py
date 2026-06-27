"""Compensating-action invariants (colony-count and honey-mass conservation) and
optimistic concurrency on placement confirmation.

Covers difficulty queue-A rule compensating_invariant and the corner-queue
cross-cutting OCC instances. Each test's Design tag names its source.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_harvest_payload,
    TEST_USERS, make_apiary_manager_headers,
    create_apiary, create_registered_apiary, create_hive, create_inspected_hive,
    setup_lot_with_harvests, reserve_sale, setup_shipped_nuc,
    create_signed_contract, propose_placement, confirm_placement_fresh,
    current_contract_version, assert_colony_count_invariant, set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["contract_coordinator_headers"]


# ─── compensating_invariant / nuc ship then void conserves colony count ─────
def test_nuc_ship_then_void_conserves_colony_count(api):
    """PRD §3.8: "For a nucleus sale, shipping decrements the source colony's
    `brood_frames` by `frames_drawn` and decrements the owning apiary's
    `active_colony_count` by one, because the nucleus leaves the yard as a new
    colony."
    PRD §3.8: "Voiding a shipped sale moves it from `SHIPPED` to the terminal
    `VOIDED` and compensates the conserved totals: for a nucleus sale it restores
    the source colony's `brood_frames` by `frames_drawn` and increments the apiary's
    `active_colony_count` by one."

    Design: Difficulty/compensating_invariant/nuc_ship_then_void_conserves_apiary_colony_count
    """
    set_clock("2026-04-01T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=8)
    sale = setup_shipped_nuc(apiary["id"], hive["id"], frames_drawn=3)

    voided = validate_success(api.void_sale(sale["id"], COORDINATOR), 200)
    assert voided["status"] == "VOIDED"

    ap_after = validate_success(api.get_apiary(apiary["id"], headers), 200)
    assert_colony_count_invariant(ap_after, 1)
    hive_after = validate_success(api.get_hive(hive["id"], headers), 200)
    assert hive_after["brood_frames"] == 8


def test_nuc_ship_decrements_then_void_restores_brood_frames(api):
    """PRD §3.8: "For a nucleus sale, shipping decrements the source colony's
    `brood_frames` by `frames_drawn` and decrements the owning apiary's
    `active_colony_count` by one, because the nucleus leaves the yard as a new
    colony."
    PRD §3.8: "for a nucleus sale it restores the source colony's `brood_frames` by
    `frames_drawn` and increments the apiary's `active_colony_count` by one."

    Design: Difficulty/compensating_invariant/nuc_ship_then_void_conserves_apiary_colony_count
    """
    set_clock("2026-04-01T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=8)
    sale = setup_shipped_nuc(apiary["id"], hive["id"], frames_drawn=3)

    # After ship: brood 8 -> 5, count 1 -> 0.
    hive_shipped = validate_success(api.get_hive(hive["id"], headers), 200)
    assert hive_shipped["brood_frames"] == 5
    ap_shipped = validate_success(api.get_apiary(apiary["id"], headers), 200)
    assert ap_shipped["active_colony_count"] == 0

    validate_success(api.void_sale(sale["id"], COORDINATOR), 200)
    hive_after = validate_success(api.get_hive(hive["id"], headers), 200)
    assert hive_after["brood_frames"] == 8


# ─── compensating_invariant / harvest void conserves honey mass ─────────────
def test_harvest_void_restores_lot_gross_weight_and_provisional(api):
    """PRD §3.7: "Voiding a single harvest moves it from `RECORDED` to the terminal
    `VOID`, but only while its parent lot is `DRAFT` or `BLOCKED`; doing so subtracts
    the contribution's `weight_kg` from the lot's `gross_weight_kg` and recomputes
    the provisional yield, preserving honey-mass conservation."

    Design: Difficulty/compensating_invariant/harvest_void_conserves_lot_gross_weight_and_provisional_yield
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, rows = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0)])
    hv = rows[0]
    # Before void: gross 12.0, provisional 4*2.5=10.0
    lot_before = validate_success(api.get_honey_lot(lot["id"], headers), 200)
    assert lot_before["gross_weight_kg"] == 12.0
    assert lot_before["provisional_yield_kg"] == 10.0

    voided = validate_success(api.void_harvest(hv["id"], headers), 200)
    assert voided["status"] == "VOID"

    lot_after = validate_success(api.get_honey_lot(lot["id"], headers), 200)
    assert lot_after["gross_weight_kg"] == 0
    assert lot_after["provisional_yield_kg"] == 0


def test_harvest_void_sets_status_void(api):
    """PRD §3.7: "Voiding a single harvest moves it from `RECORDED` to the terminal
    `VOID`, but only while its parent lot is `DRAFT` or `BLOCKED`; doing so subtracts
    the contribution's `weight_kg` from the lot's `gross_weight_kg` and recomputes
    the provisional yield, preserving honey-mass conservation."

    Design: Difficulty/compensating_invariant/harvest_void_conserves_lot_gross_weight_and_provisional_yield
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, rows = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0)])
    hv = rows[0]
    voided = validate_success(api.void_harvest(hv["id"], headers), 200)
    assert voided["status"] == "VOID"


# ─── Corner / cross_cutting OCC ─────────────────────────────────────────────
def test_occ_stale_contract_version_on_second_confirm(api):
    """PRD §2.11: "If `expected_contract_version` does not equal the contract's
    current `version` — meaning another writer has advanced the contract since the
    client last read it — the confirmation is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412), forcing the client to re-read before
    acting on out-of-date capacity."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_placement_confirm
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    h1 = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                               brood_frames_observed=5)
    h2 = create_inspected_hive(apiary["id"], tag="H2", brood_frames=5,
                               brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=2, max_hives_on_site=4)
    stale_version = contract["version"]
    p1 = propose_placement(contract["id"], h1["id"])
    p2 = propose_placement(contract["id"], h2["id"])
    # Confirm P1 with the (then-fresh) version; this bumps the contract version.
    validate_success(api.confirm_placement(
        p1["id"], {"expected_contract_version": stale_version}, COORDINATOR), 200)

    # Confirm P2 with the now-stale version.
    res = api.confirm_placement(
        p2["id"], {"expected_contract_version": stale_version}, COORDINATOR)
    validate_error(res, "ERR_STALE_CONTRACT_VERSION", expected_status=412)
    p2_after = validate_success(api.get_placement(p2["id"], COORDINATOR), 200)
    assert p2_after["status"] == "PROPOSED"


def test_occ_correct_version_confirm_succeeds_and_bumps_version(api):
    """PRD §2.11: "Each confirmation legitimately consumes site capacity and
    advances the contract — it can raise `placed_strong_hives` and it always
    increments the contract's `version`."
    PRD §3.5: "increments the contract's `placed_strong_hives` by one when the
    resulting `grade` is `CONTRACT_GRADE`, and increments the contract's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_contract_version_confirm_succeeds_and_bumps_version
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1, max_hives_on_site=4)
    v0 = contract["version"]
    placement = propose_placement(contract["id"], hive["id"])

    confirmed = validate_success(api.confirm_placement(
        placement["id"], {"expected_contract_version": v0}, COORDINATOR), 200)
    assert confirmed["status"] == "CONFIRMED"
    contract_after = validate_success(api.get_contract(contract["id"], COORDINATOR), 200)
    assert contract_after["version"] == v0 + 1
