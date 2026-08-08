"""Notification, storage assignment, posture gating, and re-notify reminders.

Queue A (Difficulty): notify_depends_on_resident_active, notify_depends_on_property_posture,
notify_referential_beats_safety, locker_single_occupancy_conflict,
shelf_aggregate_capacity_conflict, package_renotify_cyclic_reminder.
Queue B (Corner): locker_size_mismatch.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    notify_payload, pms_sync_payload,
    TEST_USERS,
    make_property, make_carrier, make_resident, make_bank, make_locker, make_shelf,
    log_package, notify_into_locker, notify_into_shelf,
    get_package, get_locker, list_package_notifications,
    setup_bank_with_lockers, setup_awaiting_shelf_packages,
    setup_notified_locker_package,
)
from test_helpers import api_client

PM = TEST_USERS["pm_headers"]
CONCIERGE = TEST_USERS["concierge_headers"]
PMS = TEST_USERS["pms_headers"]


# ─── notify_depends_on_resident_active ────────────────────────────────────────
def test_notify_blocked_when_resident_on_hold(api):
    """PRD §3.3: "The recipient resident's `status` must be `ACTIVE`; otherwise the notify is
    rejected with `ERR_RESIDENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/notify_depends_on_resident_active
    """
    ctx = setup_bank_with_lockers()
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    api_client.pms_sync(ctx["resident"]["id"], pms_sync_payload("PLACE_HOLD"), PMS)
    res = api.notify_package(
        pkg["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][0]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_RESIDENT_NOT_ACTIVE", expected_status=409)
    assert get_package(pkg["id"])["status"] == "LOGGED"


def test_notify_blocked_when_resident_moved_out(api):
    """PRD §3.3: "The recipient resident's `status` must be `ACTIVE`; otherwise the notify is
    rejected with `ERR_RESIDENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/notify_depends_on_resident_active
    """
    ctx = setup_bank_with_lockers()
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    api_client.pms_sync(ctx["resident"]["id"], pms_sync_payload("MOVE_OUT"), PMS)
    res = api.notify_package(
        pkg["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][0]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_RESIDENT_NOT_ACTIVE", expected_status=409)
    assert get_package(pkg["id"])["status"] == "LOGGED"


# ─── notify_depends_on_property_posture ───────────────────────────────────────
def test_notify_locker_blocked_when_property_frozen(api):
    """PRD §3.3: "a `FROZEN` property blocks all locker assignment (`ERR_STORAGE_FROZEN`), and
    a `RESTRICTED` property blocks `AMBIENT` locker assignment specifically
    (`ERR_STORAGE_RESTRICTED`) while still permitting refrigerated assignment."

    Design: Difficulty/cross_entity_state_dependency/notify_depends_on_property_posture
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.85},
                                  locker_specs=(("LARGE", None),))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])  # single locker -> util 1.0 -> FROZEN
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    res = api.notify_package(
        pkg2["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][0]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_STORAGE_FROZEN", expected_status=409)
    assert get_package(pkg2["id"])["status"] == "LOGGED"


def test_notify_ambient_locker_blocked_when_property_restricted(api):
    """PRD §3.3: "a `RESTRICTED` property blocks `AMBIENT` locker assignment specifically
    (`ERR_STORAGE_RESTRICTED`) while still permitting refrigerated assignment."

    Design: Difficulty/cross_entity_state_dependency/notify_depends_on_property_posture
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.5},
                                  locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])  # 1 of 2 -> util 0.5 -> RESTRICTED
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    res = api.notify_package(
        pkg2["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][1]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_STORAGE_RESTRICTED", expected_status=409)


# ─── notify_referential_beats_safety (priority 6 outranks priority 8) ─────────
def test_notify_moved_out_and_frozen_reports_resident_not_active(api):
    """PRD §2.10: "(6) recipient resident active on notify (`ERR_RESIDENT_NOT_ACTIVE`, 409);
    (7) cold-chain freshness on perishable pickup (`ERR_COLD_CHAIN_EXPIRED`, 409); (8) posture
    gating of locker assignment (`ERR_STORAGE_FROZEN` / `ERR_STORAGE_RESTRICTED`, 409);"
    PRD §2.10: "Where a lower-numbered check would fire, it takes precedence over any
    higher-numbered one on the same request."

    Design: Difficulty/priority_pair_validation_conflict/notify_referential_beats_safety
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.85},
                                  locker_specs=(("LARGE", None),))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])  # FROZEN, storage retained on hold
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    api_client.pms_sync(ctx["resident"]["id"], pms_sync_payload("MOVE_OUT"), PMS)
    res = api.notify_package(
        pkg2["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][0]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_RESIDENT_NOT_ACTIVE", expected_status=409)


def test_notify_held_resident_and_frozen_reports_resident_not_active(api):
    """PRD §2.10: "(6) recipient resident active on notify (`ERR_RESIDENT_NOT_ACTIVE`, 409);
    (7) cold-chain freshness on perishable pickup (`ERR_COLD_CHAIN_EXPIRED`, 409); (8) posture
    gating of locker assignment (`ERR_STORAGE_FROZEN` / `ERR_STORAGE_RESTRICTED`, 409);"
    PRD §2.10: "Where a lower-numbered check would fire, it takes precedence over any
    higher-numbered one on the same request."

    Design: Difficulty/priority_pair_validation_conflict/notify_referential_beats_safety
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.85},
                                  locker_specs=(("LARGE", None),))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])  # FROZEN, storage retained on hold
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    api_client.pms_sync(ctx["resident"]["id"], pms_sync_payload("PLACE_HOLD"), PMS)
    res = api.notify_package(
        pkg2["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][0]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_RESIDENT_NOT_ACTIVE", expected_status=409)


# ─── locker_single_occupancy_conflict ─────────────────────────────────────────
def test_second_package_into_occupied_locker_rejected(api):
    """PRD §3.3: "The chosen locker must be `AVAILABLE`, must fit the package's size, and must
    match on storage class — a locker that is not available (because it is `OCCUPIED` or
    `OUT_OF_SERVICE`) yields `ERR_LOCKER_UNAVAILABLE`".

    Design: Difficulty/resource_temporal_overlap/locker_single_occupancy_conflict
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.85},
                                  locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    res = api.notify_package(
        pkg2["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][0]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_LOCKER_UNAVAILABLE", expected_status=409)
    assert get_package(pkg2["id"])["status"] == "LOGGED"


def test_second_package_into_free_locker_succeeds(api):
    """PRD §3.3: "The chosen locker must be `AVAILABLE`, must fit the package's size, and must
    match on storage class — a locker that is not available (because it is `OCCUPIED` or
    `OUT_OF_SERVICE`) yields `ERR_LOCKER_UNAVAILABLE`".

    Design: Difficulty/resource_temporal_overlap/locker_single_occupancy_conflict
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.85},
                                  locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    res = api.notify_package(
        pkg2["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][1]["id"]),
        CONCIERGE)
    notified = validate_success(res, 200)
    assert notified["status"] == "AWAITING_PICKUP"
    assert notified["locker_id"] == ctx["lockers"][1]["id"]


# ─── shelf_aggregate_capacity_conflict ────────────────────────────────────────
def test_third_package_into_full_shelf_rejected(api):
    """PRD §2.6: "a shelf can accept a new package only when that available capacity is at least
    1 — equivalently, only while the occupied count is strictly less than the capacity. A shelf
    whose occupied count already equals its capacity is full."

    Design: Difficulty/resource_temporal_overlap/shelf_aggregate_capacity_conflict
    """
    ctx = setup_awaiting_shelf_packages(capacity=2, num_awaiting=2)
    pkg3 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    res = api.notify_package(
        pkg3["id"], notify_payload(storage_target="SHELF", shelf_id=ctx["shelf"]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_SHELF_FULL", expected_status=409)
    from test_helpers.fixtures import get_success_data
    shelf_after = get_success_data(api.get_shelf(ctx["shelf"]["id"], PM))
    assert shelf_after["occupied_count"] == 2
    assert get_package(pkg3["id"])["status"] == "LOGGED"


def test_shelf_accepts_up_to_capacity(api):
    """PRD §2.6: "a shelf can accept a new package only when that available capacity is at least
    1 — equivalently, only while the occupied count is strictly less than the capacity."

    Design: Difficulty/resource_temporal_overlap/shelf_aggregate_capacity_conflict
    """
    prop = make_property(name="Shelf OK Court")
    carrier = make_carrier(prop["id"])
    resident = make_resident(prop["id"])
    shelf = make_shelf(prop["id"], capacity=2)
    pkg1 = log_package(prop["id"], resident["id"], carrier["id"])
    notify_into_shelf(pkg1["id"], shelf["id"])
    pkg2 = log_package(prop["id"], resident["id"], carrier["id"])
    notified = validate_success(
        api.notify_package(pkg2["id"], notify_payload(storage_target="SHELF", shelf_id=shelf["id"]),
                           CONCIERGE), 200)
    assert notified["status"] == "AWAITING_PICKUP"
    from test_helpers.fixtures import get_success_data
    shelf_after = get_success_data(api.get_shelf(shelf["id"], PM))
    assert shelf_after["occupied_count"] == 2


# ─── package_renotify_cyclic_reminder ─────────────────────────────────────────
def test_reminder_keeps_awaiting_and_reuses_code(api):
    """PRD §3.3: "A reminder still requires the resident to be `ACTIVE`, increments
    `notify_count`, refreshes `notified_at`, and creates a `Notification` of `kind` `REMINDER`
    that reuses the original `pickup_code`; it does not re-mint the code and does not reassign
    or change storage."

    Design: Difficulty/non_linear_state_machine/package_renotify_cyclic_reminder
    """
    ctx = setup_notified_locker_package()
    code1 = ctx["pickup_code"]
    assert ctx["package"]["notify_count"] == 1
    res = api.notify_package(ctx["package"]["id"], notify_payload(), CONCIERGE)
    reminded = validate_success(res, 200)
    assert reminded["status"] == "AWAITING_PICKUP"
    assert reminded["notify_count"] == 2
    assert reminded["pickup_code"] == code1


def test_reminder_appends_reminder_notification_with_reused_code(api):
    """PRD §3.3: "A reminder still requires the resident to be `ACTIVE`, increments
    `notify_count`, refreshes `notified_at`, and creates a `Notification` of `kind` `REMINDER`
    that reuses the original `pickup_code`".

    Design: Difficulty/non_linear_state_machine/package_renotify_cyclic_reminder
    """
    ctx = setup_notified_locker_package()
    code1 = ctx["pickup_code"]
    validate_success(api.notify_package(ctx["package"]["id"], notify_payload(), CONCIERGE), 200)
    notes = list_package_notifications(ctx["package"]["id"])
    reminders = [n for n in notes if n["kind"] == "REMINDER"]
    assert len(reminders) == 1, f"expected exactly one REMINDER notification, got {notes}"
    assert reminders[0]["pickup_code"] == code1


# ─── locker_size_mismatch (Corner) ────────────────────────────────────────────
def test_large_package_into_small_locker_rejected(api):
    """PRD §3.3: "a locker too small for the package or of the wrong storage class yields
    `ERR_LOCKER_SIZE_MISMATCH`."

    Design: Corner/validations/locker_size_mismatch_returns_conflict
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.85},
                                  locker_specs=(("SMALL", None),))
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"],
                      size_class="LARGE")
    res = api.notify_package(
        pkg["id"], notify_payload(storage_target="LOCKER", locker_id=ctx["lockers"][0]["id"]),
        CONCIERGE)
    validate_error(res, "ERR_LOCKER_SIZE_MISMATCH", expected_status=409)
