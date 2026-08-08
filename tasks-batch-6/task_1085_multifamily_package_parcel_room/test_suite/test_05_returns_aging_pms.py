"""Retail returns, aging sweep, cold-chain disposal, PMS cascades, and dual-control completion.

Queue A (Difficulty): retail_return_branch_reject_vs_verify, moveout_cascade_hold_and_notice_depth2,
fee_ledger_conserved_on_waive.
Queue B (Corner): aging_sweep_returns_overdue_ambient_package,
perishable_disposed_by_aging_sweep_after_cold_chain, retail_return_staging_full_returns_conflict,
carrier_pickup_by_wrong_carrier_returns_403, return_complete_same_actor_returns_sod_violation,
return_complete_from_awaiting_returns_invalid_state, hold_then_release_roundtrip_restores_awaiting.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_retail_return_payload, pms_sync_payload,
    TEST_USERS, make_resident_headers, make_carrier_headers, make_concierge_headers,
    setup_property_carrier_resident, setup_notified_locker_package,
    setup_return_initiated_package,
    make_property, make_carrier, make_resident,
    advance_clock, get_package, get_property, get_locker, get_resident,
    list_package_notifications, list_package_charges,
)
from test_helpers import api_client
from test_helpers.fixtures import get_success_data

PM = TEST_USERS["pm_headers"]
CONCIERGE = TEST_USERS["concierge_headers"]
PMS = TEST_USERS["pms_headers"]


def _drop_off(prop_id, resident, carrier_id, tracking):
    return get_success_data(api_client.create_retail_return(
        create_retail_return_payload(prop_id, resident["id"], carrier_id, tracking_number=tracking),
        make_resident_headers(resident["id"])))


# ─── retail_return_branch_reject_vs_verify ────────────────────────────────────
def test_reject_branch_sets_reason_and_terminal(api):
    """PRD §3.9: "or rejects a bad-label return with an optional `reject_reason`, advancing it
    to the terminal `REJECTED` status (`DROPPED_OFF → REJECTED`) and recording the reason on
    `reject_reason` while decrementing the property's `return_staging_count`."

    Design: Difficulty/non_linear_state_machine/retail_return_branch_reject_vs_verify
    """
    ctx = setup_property_carrier_resident()
    rr1 = _drop_off(ctx["property"]["id"], ctx["resident"], ctx["carrier"]["id"], "RR-1")
    rr2 = _drop_off(ctx["property"]["id"], ctx["resident"], ctx["carrier"]["id"], "RR-2")
    validate_success(api.verify_label(rr2["id"], CONCIERGE), 200)
    rejected = validate_success(
        api.reject_return(rr1["id"], {"reject_reason": "torn label"}, CONCIERGE), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "torn label"
    rr2_after = get_success_data(api.get_retail_return(rr2["id"], PM))
    assert rr2_after["status"] == "AWAITING_CARRIER"


def test_verify_branch_advances_without_reject_reason(api):
    """PRD §3.9: "`ConciergeStaff` then verifies the return label, advancing it
    `DROPPED_OFF → AWAITING_CARRIER`".

    Design: Difficulty/non_linear_state_machine/retail_return_branch_reject_vs_verify
    """
    ctx = setup_property_carrier_resident()
    rr = _drop_off(ctx["property"]["id"], ctx["resident"], ctx["carrier"]["id"], "RR-1")
    verified = validate_success(api.verify_label(rr["id"], CONCIERGE), 200)
    assert verified["status"] == "AWAITING_CARRIER"
    assert verified.get("reject_reason") in (None, "")


# ─── moveout_cascade_hold_and_notice_depth2 ───────────────────────────────────
def test_moveout_cascades_awaiting_package_to_held(api):
    """PRD §3.6: "A `MOVE_OUT` event moves a resident — whether currently `ACTIVE` or `HOLD` —
    to the terminal `MOVED_OUT` state. When the resident was `ACTIVE`, move-out first cascades
    each `AWAITING_PICKUP` package to `HELD` (which, as above, creates a `MOVE_OUT_HOLD`
    notification)."

    Design: Difficulty/transitive_cascade/moveout_cascade_hold_and_notice_depth2
    """
    ctx = setup_notified_locker_package()
    validate_success(api.pms_sync(ctx["resident"]["id"], pms_sync_payload("MOVE_OUT"), PMS), 200)
    assert get_resident(ctx["resident"]["id"])["status"] == "MOVED_OUT"
    assert get_package(ctx["package"]["id"])["status"] == "HELD"


def test_moveout_emits_move_out_hold_notification(api):
    """PRD §3.6: "each such package emits a `Notification` of `kind` `MOVE_OUT_HOLD`, and the
    package's storage assignment is retained (not released) while it is `HELD`."

    Design: Difficulty/transitive_cascade/moveout_cascade_hold_and_notice_depth2
    """
    ctx = setup_notified_locker_package()
    validate_success(api.pms_sync(ctx["resident"]["id"], pms_sync_payload("MOVE_OUT"), PMS), 200)
    notes = list_package_notifications(ctx["package"]["id"])
    holds = [n for n in notes if n["kind"] == "MOVE_OUT_HOLD"]
    assert len(holds) == 1, f"expected one MOVE_OUT_HOLD notification, got {notes}"


# ─── fee_ledger_conserved_on_waive ────────────────────────────────────────────
def test_moveout_waive_zeroes_uncollected_ledger(api):
    """PRD §3.6: "move-out then waives money: every `OUTSTANDING` `HOLDING_FEE` charge belonging
    to that resident's packages is set to `WAIVED`, and the property's `uncollected_fee_cents`
    is decreased by the summed waived amount."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_waive
    """
    ctx = setup_notified_locker_package(resident_overrides={"loyalty_discount_pct": 0.0})
    advance_clock("2026-05-09T00:00:00Z")
    validate_success(api.return_initiate(ctx["package"]["id"], CONCIERGE), 200)
    assert get_property(ctx["property"]["id"])["uncollected_fee_cents"] == 750
    validate_success(api.pms_sync(ctx["resident"]["id"], pms_sync_payload("MOVE_OUT"), PMS), 200)
    assert get_property(ctx["property"]["id"])["uncollected_fee_cents"] == 0


def test_moveout_marks_outstanding_charge_waived(api):
    """PRD §3.6: "move-out then waives money: every `OUTSTANDING` `HOLDING_FEE` charge belonging
    to that resident's packages is set to `WAIVED`, and the property's `uncollected_fee_cents`
    is decreased by the summed waived amount."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_waive
    """
    ctx = setup_notified_locker_package(resident_overrides={"loyalty_discount_pct": 0.0})
    advance_clock("2026-05-09T00:00:00Z")
    validate_success(api.return_initiate(ctx["package"]["id"], CONCIERGE), 200)
    validate_success(api.pms_sync(ctx["resident"]["id"], pms_sync_payload("MOVE_OUT"), PMS), 200)
    charges = list_package_charges(ctx["package"]["id"])
    assert len(charges) == 1, f"expected one charge, got {charges}"
    assert charges[0]["status"] == "WAIVED"


# ─── aging_sweep_returns_overdue_ambient_package (Corner) ─────────────────────
def test_aging_sweep_returns_overdue_ambient(api):
    """PRD §3.8: "Every remaining candidate is evicted `AWAITING_PICKUP → RETURN_INITIATED` with
    the system as actor and `return_initiated_by_user_id` set to `SYSTEM`, pinning
    `final_fee_cents`, creating `OUTSTANDING` `HOLDING_FEE` charges".

    Design: Corner/calculations/aging_sweep_returns_overdue_ambient_package
    """
    ctx = setup_notified_locker_package()  # AMBIENT, aging_days_standard 10, intake 2026-05-01
    advance_clock("2026-05-12T00:00:00Z")  # 11 days >= aging deadline 2026-05-11
    validate_success(api.aging_sweep(ctx["property"]["id"], PM), 200)
    pkg = get_package(ctx["package"]["id"])
    assert pkg["status"] == "RETURN_INITIATED"
    assert pkg["return_initiated_by_user_id"] == "SYSTEM"
    assert get_locker(ctx["locker"]["id"])["status"] == "AVAILABLE"


# ─── perishable_disposed_by_aging_sweep_after_cold_chain (Corner) ─────────────
def test_perishable_disposed_by_aging_sweep(api):
    """PRD §3.8: "any `PERISHABLE` package already strictly past its `cold_chain_deadline_at` is
    forfeited first: it transitions `AWAITING_PICKUP → DISPOSED`, which releases its storage".

    Design: Corner/calculations/perishable_disposed_by_aging_sweep_after_cold_chain
    """
    ctx = setup_notified_locker_package(
        bank_storage="REFRIGERATED", locker_size="MEDIUM", pkg_size="MEDIUM",
        pkg_storage_type="PERISHABLE")
    advance_clock("2026-05-04T00:00:00Z")  # past both 48h cold-chain and 2-day aging deadline
    validate_success(api.aging_sweep(ctx["property"]["id"], PM), 200)
    assert get_package(ctx["package"]["id"])["status"] == "DISPOSED"
    assert get_locker(ctx["locker"]["id"])["status"] == "AVAILABLE"


# ─── retail_return_staging_full_returns_conflict (Corner) ─────────────────────
def test_retail_return_staging_full_rejected(api):
    """PRD §3.9: "The drop-off is blocked when the property is already at capacity — that is,
    when `return_staging_count` equals `return_staging_capacity` — and rejected with
    `ERR_STAGING_FULL`".

    Design: Corner/validations/retail_return_staging_full_returns_conflict
    """
    ctx = setup_property_carrier_resident(prop_overrides={"return_staging_capacity": 1})
    _drop_off(ctx["property"]["id"], ctx["resident"], ctx["carrier"]["id"], "RR-1")
    res = api.create_retail_return(
        create_retail_return_payload(ctx["property"]["id"], ctx["resident"]["id"],
                                     ctx["carrier"]["id"], tracking_number="RR-2"),
        make_resident_headers(ctx["resident"]["id"]))
    validate_error(res, "ERR_STAGING_FULL", expected_status=409)


# ─── carrier_pickup_by_wrong_carrier_returns_403 (Corner) ─────────────────────
def test_carrier_pickup_by_wrong_carrier_rejected(api):
    """PRD §3.9: "the carrier's `X-User-ID` must equal the return's `carrier_id`, otherwise the
    collection is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/carrier_pickup_by_wrong_carrier_returns_403
    """
    prop = make_property(name="Own Court")
    carrier1 = make_carrier(prop["id"], name="UPS", scac="UPSN")
    carrier2 = make_carrier(prop["id"], name="FDX", scac="FDXN")
    resident = make_resident(prop["id"])
    rr = _drop_off(prop["id"], resident, carrier1["id"], "RR-1")
    validate_success(api.verify_label(rr["id"], CONCIERGE), 200)
    res = api.carrier_pickup(rr["id"], make_carrier_headers(carrier2["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
    assert get_success_data(api.get_retail_return(rr["id"], PM))["status"] == "AWAITING_CARRIER"


# ─── return_complete_same_actor_returns_sod_violation (Corner) ────────────────
def test_return_complete_same_actor_sod_violation(api):
    """PRD §3.7: "The confirming actor's `X-User-ID` must differ from the
    `return_initiated_by_user_id` recorded at eviction; if the same user attempts both halves,
    the completion is rejected with `ERR_SOD_VIOLATION`".

    Design: Corner/rbac/return_complete_same_actor_returns_sod_violation
    """
    ctx = setup_return_initiated_package(concierge_user_id="staff-1")
    res = api.return_complete(ctx["package"]["id"], make_concierge_headers("staff-1"))
    validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)
    assert get_package(ctx["package"]["id"])["status"] == "RETURN_INITIATED"


# ─── return_complete_from_awaiting_returns_invalid_state (Corner) ─────────────
def test_return_complete_from_awaiting_rejected(api):
    """PRD §3.7: "A package in any state other than the one each transition expects yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/return_complete_from_awaiting_returns_invalid_state
    """
    ctx = setup_notified_locker_package()
    res = api.return_complete(ctx["package"]["id"], CONCIERGE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── hold_then_release_roundtrip_restores_awaiting (Corner) ───────────────────
def test_hold_then_release_restores_awaiting_and_retains_locker(api):
    """PRD §3.6: "A later `RELEASE_HOLD` event returns a `HOLD` resident to `ACTIVE` and cascades
    each of that resident's `HELD` packages back to `AWAITING_PICKUP`, with no additional side
    effects."

    Design: Corner/state_machines/hold_then_release_roundtrip_restores_awaiting
    """
    ctx = setup_notified_locker_package()
    locker_id = ctx["locker"]["id"]
    validate_success(api.pms_sync(ctx["resident"]["id"], pms_sync_payload("PLACE_HOLD"), PMS), 200)
    assert get_package(ctx["package"]["id"])["status"] == "HELD"
    validate_success(api.pms_sync(ctx["resident"]["id"], pms_sync_payload("RELEASE_HOLD"), PMS), 200)
    assert get_resident(ctx["resident"]["id"])["status"] == "ACTIVE"
    pkg = get_package(ctx["package"]["id"])
    assert pkg["status"] == "AWAITING_PICKUP"
    assert pkg["locker_id"] == locker_id
