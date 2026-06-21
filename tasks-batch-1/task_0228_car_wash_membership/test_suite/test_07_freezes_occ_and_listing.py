"""Freeze windows, add-on capacity, OCC, wallet debits, and listing (PRD §2.3, §2.8, §3.5, §3.8, §3.9, §3.10).

Translates queue-A resource_temporal_overlap (freeze overlap) plus queue-B
validation, OCC, and endpoint corners.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_plan_payload, create_addon_payload, create_single_wash_plan_payload,
    freeze_scheduled_payload, attach_addon_payload, topup_payload, adjustment_payload,
    assert_membership_addon,
    TEST_USERS, make_account_holder_headers,
    setup_unlimited_active, setup_single_wash_active,
    create_plan, create_addon, create_account, create_vehicle, enroll_membership,
    pay_first_cycle_invoice, fund_wallet, schedule_freeze,
)

PA = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["billing_admin_headers"]


# ─── Queue A: resource_temporal_overlap / freeze_window_overlap_rejected_half_open ───

def test_overlapping_scheduled_freeze_rejected(api):
    """PRD §3.8: "The requested window must not overlap any existing non-cancelled freeze
    on the same membership; overlap is judged on the half-open interval, so two windows
    that merely touch at an endpoint do not overlap, but any true interior overlap is
    rejected with `ERR_FREEZE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/freeze_window_overlap_rejected_half_open
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="FRZ011"
    )
    hdr = make_account_holder_headers(account["id"])
    schedule_freeze(membership["id"], account["id"], "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z")
    res = api.freeze_scheduled(
        membership["id"],
        freeze_scheduled_payload("2026-06-15T00:00:00Z", "2026-06-25T00:00:00Z"),
        hdr,
    )
    validate_error(res, "ERR_FREEZE_OVERLAP", expected_status=409)


def test_overlap_rejection_leaves_single_scheduled_freeze(api):
    """PRD §3.8: "The requested window must not overlap any existing non-cancelled freeze
    on the same membership ... but any true interior overlap is rejected with
    `ERR_FREEZE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/freeze_window_overlap_rejected_half_open
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="FRZ012"
    )
    hdr = make_account_holder_headers(account["id"])
    fz1 = schedule_freeze(membership["id"], account["id"], "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z")
    api.freeze_scheduled(
        membership["id"],
        freeze_scheduled_payload("2026-06-15T00:00:00Z", "2026-06-25T00:00:00Z"),
        hdr,
    )
    freezes = validate_success(api.list_freezes(membership["id"], hdr), 200)
    non_cancelled = [f for f in freezes if f["status"] != "CANCELLED"]
    assert len(non_cancelled) == 1, "the overlapping freeze must not be persisted"
    assert non_cancelled[0]["id"] == fz1["id"]


# ─── Queue B: validation corners ──────────────────────────────────────────

def test_freeze_window_end_before_start_rejected(api):
    """PRD §3.8: "The `end_utc` must be strictly after the `start_utc`, or the request is
    rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/freeze_window_end_before_start_invalid_window
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="WIN001"
    )
    hdr = make_account_holder_headers(account["id"])
    res = api.freeze_scheduled(
        membership["id"],
        freeze_scheduled_payload("2026-06-20T00:00:00Z", "2026-06-10T00:00:00Z"),
        hdr,
    )
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=422)


def test_topup_credit_quantity_zero_rejected(api):
    """PRD §3.5: "The request names a `credit_quantity` (which must be at least 1) ... A
    `credit_quantity` below 1 is rejected with `ERR_VALIDATION`."

    Design: Corner/validations/topup_credit_quantity_zero_validation
    """
    plan, account, vehicle, membership = setup_single_wash_active(
        included_credits=2, clock="2026-06-01T00:00:00Z", license_plate="VAL001", fund_cents=5000
    )
    hdr = make_account_holder_headers(account["id"])
    mem = validate_success(api.get_membership(membership["id"], hdr), 200)
    res = api.topup_membership(membership["id"], topup_payload(0, mem["version"]), hdr)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_addon_limit_exceeded_rejected(api):
    """PRD §3.9: "The number of add-ons that are `ACTIVE` or `PAUSED` on the membership
    must be fewer than the plan's `max_addons` before a new attachment is allowed; an
    attachment that would exceed the cap is rejected with `ERR_ADDON_LIMIT`."

    Design: Corner/validations/addon_limit_exceeded_rejected
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        max_addons=1, clock="2026-06-01T00:00:00Z", license_plate="LIM001"
    )
    hdr = make_account_holder_headers(account["id"])
    ax1 = create_addon(name="AX1", recurring_fee_cents=300)
    ax2 = create_addon(name="AX2", recurring_fee_cents=400)
    mem_v1 = validate_success(api.get_membership(membership["id"], hdr), 200)
    validate_success(
        api.attach_addon(membership["id"], attach_addon_payload(ax1["id"], mem_v1["version"]), hdr), 201
    )
    mem_v2 = validate_success(api.get_membership(membership["id"], hdr), 200)
    res = api.attach_addon(membership["id"], attach_addon_payload(ax2["id"], mem_v2["version"]), hdr)
    validate_error(res, "ERR_ADDON_LIMIT", expected_status=409)


def test_manual_adjustment_overdraw_rejected(api):
    """PRD §3.10: "A negative adjustment that would drive `wallet_balance_cents` below 0 is
    rejected with `ERR_INSUFFICIENT_WALLET`."

    Design: Corner/validations/manual_adjustment_overdraw_insufficient_wallet
    """
    acct = create_account(contact_email="ovr@x.com")
    res = api.create_adjustment(acct["id"], adjustment_payload(-100), BA)
    validate_error(res, "ERR_INSUFFICIENT_WALLET", expected_status=409)
    refreshed = validate_success(api.get_account(acct["id"], BA), 200)
    assert refreshed["wallet_balance_cents"] == 0, "balance never goes below 0"


# ─── Queue B: OCC positive path ───────────────────────────────────────────

def test_addon_attach_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "The request must carry `expected_membership_version` equal to the
    membership's current `version`."
    PRD §3.9: "A newly attached add-on begins `ACTIVE`."
    PRD §2.4: "a `version`, an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation".

    Design: Corner/cross_cutting_complexity_layers/occ_addon_attach_correct_version_succeeds
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        max_addons=3, clock="2026-06-01T00:00:00Z", license_plate="OK0001"
    )
    hdr = make_account_holder_headers(account["id"])
    addon = create_addon(name="OkAdd", recurring_fee_cents=500)
    mem_before = validate_success(api.get_membership(membership["id"], hdr), 200)
    res = api.attach_addon(
        membership["id"], attach_addon_payload(addon["id"], mem_before["version"]), hdr
    )
    ma = validate_success(res, 201)
    assert_membership_addon(ma)
    assert ma["status"] == "ACTIVE"
    mem_after = validate_success(api.get_membership(membership["id"], hdr), 200)
    assert mem_after["version"] == mem_before["version"] + 1, \
        "attaching an add-on increments the membership version by exactly 1"


# ─── Queue B: pagination envelope ─────────────────────────────────────────

def test_list_memberships_pagination_envelope(api):
    """PRD §2.3: "`limit` controls the maximum number of items returned ... Every list
    response reports the pagination state in the `meta` object via the fields `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_memberships_pagination_envelope
    """
    set_plan = create_plan(name="UPag", monthly_fee_cents=3000, max_addons=3)
    acct = create_account(contact_email="pag@x.com")
    hdr = make_account_holder_headers(acct["id"])
    v1 = create_vehicle(acct["id"], "PAG001", "CA", hdr)
    v2 = create_vehicle(acct["id"], "PAG002", "CA", hdr)
    enroll_membership(acct["id"], v1["id"], set_plan["id"], hdr)
    enroll_membership(acct["id"], v2["id"], set_plan["id"], hdr)

    res = api.list_memberships(hdr, params={"account_id": acct["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert len(data) == 1, "limit=1 returns exactly one element"
    assert meta["total_count"] == 2, f"total_count expected 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "two memberships with limit=1 means has_more is true"
