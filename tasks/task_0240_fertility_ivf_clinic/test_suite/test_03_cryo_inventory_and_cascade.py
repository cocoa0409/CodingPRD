"""Cryo specimen inventory, tank capacity, the cross-aggregate slot accounting,
the depth-3 cancellation cascade, and tank-slot conservation.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    assert_tank_slot_invariants,
    ApiErrorId,
    TEST_USERS,
)
import test_helpers.factories as f
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["clinic_admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
EMBRYO = TEST_USERS["embryologist_headers"]


# ===========================================================================
# Queue A — dual_variant_calc / tank_committed_vs_projected_free_slots_diverge
# ===========================================================================
def _tank_one_stored_two_pending():
    ctx = fx.setup_cycle_in_fertilization(name="Cryo Clinic",
                                          required_for=["CYCLE_START", "RETRIEVAL", "CRYO_STORE"],
                                          oocytes_retrieved=6, embryos_fertilized=3)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    tank = fx.create_tank(cid, label="Tank-X", capacity_slots=5)
    sp1 = fx.create_specimen(cid, cyc, tank["id"])["id"]
    fx.create_specimen(cid, cyc, tank["id"])
    fx.create_specimen(cid, cyc, tank["id"])
    fx.store_specimen(cid, sp1, tank["version"])
    return cid, tank["id"]


def test_committed_free_counts_only_stored():
    """PRD 3.7: "The committed view, `committed_free_slots`, is the tank's
    `capacity_slots` minus the count of its `STORED` specimens — a chronological reading
    that counts only slots already occupied."

    Design: Difficulty/dual_variant_calc/tank_committed_vs_projected_free_slots_diverge
    """
    cid, tank_id = _tank_one_stored_two_pending()
    tank = get_success_data(api_client.get_tank(cid, tank_id, EMBRYO))
    assert tank["reserved_slots"] == 1
    assert tank["committed_free_slots"] == 4


def test_projected_free_reserves_pending_and_diverges():
    """PRD 3.7: "The projected view, `projected_free_slots`, is the tank's
    `capacity_slots` minus the count of its specimens that are either `PENDING` or
    `STORED` — a forward-looking reading that also reserves a slot for every pending
    specimen earmarked for the tank."

    Design: Difficulty/dual_variant_calc/tank_committed_vs_projected_free_slots_diverge
    """
    cid, tank_id = _tank_one_stored_two_pending()
    tank = get_success_data(api_client.get_tank(cid, tank_id, EMBRYO))
    assert tank["projected_free_slots"] == 2
    assert tank["committed_free_slots"] != tank["projected_free_slots"]


# ===========================================================================
# Queue A — transitive_cascade / cancel_cycle_depth3_specimen_tank_derived
# ===========================================================================
def _fertilization_cycle_one_stored():
    ctx = fx.setup_cycle_in_fertilization(name="Cascade Clinic",
                                          required_for=["CYCLE_START", "RETRIEVAL", "CRYO_STORE"],
                                          oocytes_retrieved=6, embryos_fertilized=3)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    tank = fx.create_tank(cid, label="Tank-C", capacity_slots=5)
    sp = fx.create_specimen(cid, cyc, tank["id"])["id"]
    fx.store_specimen(cid, sp, tank["version"])
    return cid, cyc, tank["id"], sp


def test_cancel_discards_stored_specimen():
    """PRD 3.2: "every specimen of the cycle still `PENDING` or `STORED` moves to
    `DISCARDED`. The specimen step reaches further: each specimen that was `STORED` at
    cancellation, on moving to `DISCARDED`, decrements its tank's `reserved_slots` by 1
    (a second-level cascade into the separate tank aggregate)..."

    Design: Difficulty/transitive_cascade/cancel_cycle_depth3_specimen_tank_derived
    """
    cid, cyc, tank_id, sp = _fertilization_cycle_one_stored()
    v = get_success_data(api_client.get_cycle(cid, cyc, NURSE))["version"]
    res = validate_success(api_client.cancel_cycle(cid, cyc, {"expected_cycle_version": v}, NURSE))
    assert res["protocol_status"] == "CANCELLED"
    assert get_success_data(api_client.get_specimen(cid, sp, EMBRYO))["status"] == "DISCARDED"


def test_cancel_cascade_releases_tank_slot_and_recomputes_free():
    """PRD 3.2: "and that change to `reserved_slots` in turn forces the tank's
    `committed_free_slots` and `projected_free_slots` to be recomputed (a third-level
    cascade)."

    Design: Difficulty/transitive_cascade/cancel_cycle_depth3_specimen_tank_derived
    """
    cid, cyc, tank_id, sp = _fertilization_cycle_one_stored()
    v = get_success_data(api_client.get_cycle(cid, cyc, NURSE))["version"]
    validate_success(api_client.cancel_cycle(cid, cyc, {"expected_cycle_version": v}, NURSE))
    tank = get_success_data(api_client.get_tank(cid, tank_id, EMBRYO))
    assert tank["reserved_slots"] == 0
    assert tank["committed_free_slots"] == 5


# ===========================================================================
# Queue A — boundary_precision_check / tank_store_exactly_at_capacity_boundary
# ===========================================================================
def _capacity1_two_pending():
    ctx = fx.setup_cycle_in_fertilization(name="Cap1 Clinic",
                                          required_for=["CYCLE_START", "RETRIEVAL", "CRYO_STORE"],
                                          oocytes_retrieved=4, embryos_fertilized=2)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    tank = fx.create_tank(cid, label="Tiny", capacity_slots=1)
    sp1 = fx.create_specimen(cid, cyc, tank["id"])["id"]
    sp2 = fx.create_specimen(cid, cyc, tank["id"])["id"]
    return cid, tank, sp1, sp2


def test_store_succeeds_at_capacity_boundary():
    """PRD 3.7: "the tank to have room, meaning its current `reserved_slots` plus one is
    at most its `capacity_slots` (`ERR_TANK_AT_CAPACITY`)..."

    Design: Difficulty/boundary_precision_check/tank_store_exactly_at_capacity_boundary
    """
    cid, tank, sp1, _ = _capacity1_two_pending()
    res = validate_success(api_client.store_specimen(cid, sp1, {"expected_tank_version": tank["version"]}, EMBRYO))
    assert res["status"] == "STORED"


def test_second_store_over_capacity_rejected():
    """PRD 3.7: "the tank to have room, meaning its current `reserved_slots` plus one is
    at most its `capacity_slots` (`ERR_TANK_AT_CAPACITY`)..."

    Design: Difficulty/boundary_precision_check/tank_store_exactly_at_capacity_boundary
    """
    cid, tank, sp1, sp2 = _capacity1_two_pending()
    validate_success(api_client.store_specimen(cid, sp1, {"expected_tank_version": tank["version"]}, EMBRYO))
    tank_now = get_success_data(api_client.get_tank(cid, tank["id"], EMBRYO))
    resp = api_client.store_specimen(cid, sp2, {"expected_tank_version": tank_now["version"]}, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_TANK_AT_CAPACITY.value)
    assert tank_now["reserved_slots"] == 1


# ===========================================================================
# Queue A — cross_entity_state_dependency / specimen_store_requires_online_tank
# ===========================================================================
def test_store_into_maintenance_tank_rejected():
    """PRD 3.7: "the tank to be `ONLINE` (`ERR_TANK_OFFLINE`)..."

    Design: Difficulty/cross_entity_state_dependency/specimen_store_requires_online_tank
    """
    ctx = fx.setup_cycle_in_fertilization(name="XDep Clinic B",
                                          required_for=["CYCLE_START", "RETRIEVAL", "CRYO_STORE"],
                                          oocytes_retrieved=5, embryos_fertilized=2)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    tank = fx.create_tank(cid, label="Tank-M", capacity_slots=3)
    sp = fx.create_specimen(cid, cyc, tank["id"])["id"]
    maint = get_success_data(api_client.set_tank_maintenance(cid, tank["id"], EMBRYO))
    resp = api_client.store_specimen(cid, sp, {"expected_tank_version": maint["version"]}, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_TANK_OFFLINE.value)
    assert get_success_data(api_client.get_specimen(cid, sp, EMBRYO))["status"] == "PENDING"


def test_store_into_maintenance_tank_consent_present_still_offline():
    """PRD 3.1: "either role may set it to `MAINTENANCE`; a tank in `MAINTENANCE` rejects
    new stores but retains its existing specimens."

    Design: Difficulty/cross_entity_state_dependency/specimen_store_requires_online_tank
    """
    ctx = fx.setup_cycle_in_fertilization(name="XDep Clinic B2",
                                          required_for=["CYCLE_START", "RETRIEVAL", "CRYO_STORE"],
                                          oocytes_retrieved=5, embryos_fertilized=2)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    tank = fx.create_tank(cid, label="Tank-M2", capacity_slots=3)
    sp = fx.create_specimen(cid, cyc, tank["id"])["id"]
    maint = get_success_data(api_client.set_tank_maintenance(cid, tank["id"], EMBRYO))
    resp = api_client.store_specimen(cid, sp, {"expected_tank_version": maint["version"]}, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_TANK_OFFLINE.value)


# ===========================================================================
# Queue A — compensating_invariant / tank_slot_conservation_store_then_thaw
# ===========================================================================
def _stored_then_setup():
    ctx = fx.setup_cycle_in_fertilization(name="Slot Clinic",
                                          required_for=["CYCLE_START", "RETRIEVAL", "CRYO_STORE"],
                                          oocytes_retrieved=5, embryos_fertilized=2)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    tank = fx.create_tank(cid, label="Tank-S", capacity_slots=3)
    sp = fx.create_specimen(cid, cyc, tank["id"])["id"]
    fx.store_specimen(cid, sp, tank["version"])
    return cid, tank["id"], sp


def test_thaw_releases_slot_status_thawed():
    """PRD 3.7: "**Thawing** moves `STORED → THAWED` (requires `STORED`,
    `ERR_SPECIMEN_BAD_STATE`). ... Each of these decrements the tank's `reserved_slots`
    by 1 and increments the tank's `version` by 1 as a compensating release of the slot
    reserved at store time."

    Design: Difficulty/compensating_invariant/tank_slot_conservation_store_then_thaw
    """
    cid, tank_id, sp = _stored_then_setup()
    res = validate_success(api_client.thaw_specimen(cid, sp, EMBRYO))
    assert res["status"] == "THAWED"


def test_store_then_thaw_conserves_slot_count():
    """PRD 3.7: "A tank's committed occupancy, `reserved_slots`, is by definition the
    count of specimens pointing at the tank that are currently `STORED`; it is maintained
    incrementally by the plus-one on store and the minus-one on each release, and always
    reconciles to that count."

    Design: Difficulty/compensating_invariant/tank_slot_conservation_store_then_thaw
    """
    cid, tank_id, sp = _stored_then_setup()
    validate_success(api_client.thaw_specimen(cid, sp, EMBRYO))
    tank = get_success_data(api_client.get_tank(cid, tank_id, EMBRYO))
    assert tank["reserved_slots"] == 0
    assert tank["committed_free_slots"] == 3
    assert_tank_slot_invariants(tank)


# ===========================================================================
# Queue B — state_machines / store_into_already_thawed_specimen_rejected
# ===========================================================================
def test_store_into_already_thawed_specimen_rejected():
    """PRD 3.7: "**Storing** a specimen advances it `PENDING → STORED` and is the
    cross-aggregate capacity event. The store requires the specimen to be `PENDING`
    (`ERR_SPECIMEN_BAD_STATE`)..."

    Design: Corner/state_machines/store_into_already_thawed_specimen_rejected
    """
    cid, tank_id, sp = _stored_then_setup()
    validate_success(api_client.thaw_specimen(cid, sp, EMBRYO))
    tank = get_success_data(api_client.get_tank(cid, tank_id, EMBRYO))
    resp = api_client.store_specimen(cid, sp, {"expected_tank_version": tank["version"]}, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_BAD_STATE.value)
    assert get_success_data(api_client.get_specimen(cid, sp, EMBRYO))["status"] == "THAWED"


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / occ_store_stale_tank_version_conflict
# ===========================================================================
def test_store_with_stale_tank_version_rejected():
    """PRD 2.7: "The store request must carry `expected_tank_version`, a non-optional
    field holding the client's last observed `version` of the target `CryoTank`. If that
    value does not equal the tank's current `version`, the store is rejected with
    `ERR_STALE_TANK_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_store_stale_tank_version_conflict
    """
    ctx = fx.setup_cycle_in_fertilization(name="OCC Clinic",
                                          required_for=["CYCLE_START", "RETRIEVAL", "CRYO_STORE"],
                                          oocytes_retrieved=6, embryos_fertilized=3)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    tank = fx.create_tank(cid, label="Tank-OCC", capacity_slots=5)
    sp1 = fx.create_specimen(cid, cyc, tank["id"])["id"]
    sp2 = fx.create_specimen(cid, cyc, tank["id"])["id"]
    stale_v = tank["version"]
    fx.store_specimen(cid, sp1, stale_v)  # bumps tank version
    resp = api_client.store_specimen(cid, sp2, {"expected_tank_version": stale_v}, EMBRYO)
    validate_error(resp, ApiErrorId.ERR_STALE_TANK_VERSION.value)
    assert get_success_data(api_client.get_specimen(cid, sp2, EMBRYO))["status"] == "PENDING"
