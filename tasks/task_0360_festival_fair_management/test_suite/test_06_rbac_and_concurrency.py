"""RBAC denials, optimistic concurrency happy path, derived-field reconciliation,
the re-entry rate threshold, and immediate consistency.

Corner queue (B): rbac, cross_cutting_complexity_layers, and consistency_model sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, assert_zone, assert_festival, assert_wristband,
    create_festival_payload,
    create_festival, create_zone, open_sales, go_live,
    create_festival_with_zone_and_stage, setup_application_under_review,
    setup_live_festival_with_active_wristband, sell_ticket, issue_wristband,
    activate_wristband, topup, pay_fee, make_vendor_headers, gate_enter,
    TEST_USERS,
)

_DIRECTOR = TEST_USERS["director_headers"]
_BOXOFFICE = TEST_USERS["boxoffice_headers"]
_VENDOR_MANAGER = TEST_USERS["vendor_manager_headers"]
_GATE = TEST_USERS["gate_attendant_headers"]


# ─── rbac / missing_headers_returns_unauthenticated ───

def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory
    HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which declares the operational capacity under which the request is made. If either
    header is missing, the request is rejected with `ERR_UNAUTHENTICATED`."

    POST /festivals with no auth headers is rejected with ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_festival(create_festival_payload(name="NoAuth F", start_date="2026-08-01",
                                                      end_date="2026-08-02"),
                              {"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── rbac / boxoffice_cannot_approve_application_forbidden ───

def test_boxoffice_cannot_approve_application(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    A BoxOffice operator calling the VendorManager-exclusive approve endpoint is rejected
    with ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/boxoffice_cannot_approve_application_forbidden
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_application_under_review(festival["id"], zone, vendor_name="RB Co")
    res = api.approve_application(app["id"], {"expected_zone_version": zone["version"]},
                                  _BOXOFFICE)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── rbac / vendor_cannot_confirm_other_vendors_application_not_owner ───

def test_vendor_cannot_confirm_other_vendors_application(api):
    """PRD §2.1: "for the vendor-exclusive transitions on a booth application — paying a
    fee, confirming, and withdrawing — the application's `vendor_id` must equal
    `X-User-ID`, or the request is rejected with `ERR_NOT_OWNER`."

    A Vendor whose X-User-ID does not match the application's vendor_id calling confirm
    on another vendor's application is rejected with ERR_NOT_OWNER (403).

    Design: Corner/rbac/vendor_cannot_confirm_other_vendors_application_not_owner
    """
    from test_helpers import setup_approved_application
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="C", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor1, app = setup_approved_application(festival["id"], zone, booth_tier="STANDARD",
                                              day_count=1, vendor_name="Own1")
    pay_fee(app["id"], vendor1["id"], 150.00)
    # Register a second, different vendor.
    from test_helpers import create_vendor
    vendor2 = create_vendor(company_name="Own2", contact_email="o2@x.com")
    res = api.confirm_application(app["id"], make_vendor_headers(vendor2["id"]))
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


# ─── cross_cutting_complexity_layers / occ_approve_correct_version_succeeds ───

def test_occ_approve_correct_version_succeeds(api):
    """PRD §2.6: "Approving a vendor application consumes one booth slot in the requested
    zone and advances that zone's `version`. The approval request must therefore carry
    `expected_zone_version`, and this field is mandatory on the approval endpoint. The
    server compares it against the target zone's current `version`."
    PRD §3.8: "On a successful approval the server computes the booth fee, persists it on
    the application, increments the zone's `allocated_count` by one, and advances the
    zone's `version`; the application moves to `APPROVED`."

    Approving with the correct current zone version succeeds: the application becomes
    APPROVED, the zone's allocated_count becomes 1, and the zone's version advances.

    Design: Corner/cross_cutting_complexity_layers/occ_approve_correct_version_succeeds
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=2)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    zone_version_before = zone["version"]
    vendor, app = setup_application_under_review(festival["id"], zone, vendor_name="Occ Co")
    res = api.approve_application(app["id"], {"expected_zone_version": zone_version_before},
                                  _VENDOR_MANAGER)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"
    zone_after = validate_success(api.get_zone(zone["id"], _VENDOR_MANAGER), 200)
    assert_zone(zone_after)
    assert zone_after["allocated_count"] == 1
    assert zone_after["version"] > zone_version_before


# ─── cross_cutting_complexity_layers / derived_wallet_liability_recompute_on_unfreeze ──

def test_wallet_liability_recomputed_on_unfreeze(api):
    """PRD §2.8: "freezing or unfreezing a wristband removes or re-includes its balance
    respectively, because a frozen wristband is no longer in the `ACTIVE` set."
    PRD §3.6: "Unfreezing moves a `FROZEN` wristband back to `ACTIVE`, provided the
    festival is not `CANCELLED`, and recomputes `total_wallet_liability` to re-include
    the balance."

    A 40.00-balance wristband frozen (dropping total_wallet_liability to 0.00) then
    unfrozen returns to ACTIVE and the festival's total_wallet_liability is recomputed
    back to 40.00.

    Design: Corner/cross_cutting_complexity_layers/derived_wallet_liability_recompute_on_unfreeze
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Recon F",
        rfid_uid="RF-RC-1", balance=40.00)
    validate_success(api.freeze_wristband(wristband["id"], _DIRECTOR), 200)
    res = api.unfreeze_wristband(wristband["id"], _DIRECTOR)
    unfrozen = validate_success(res, 200)
    assert_wristband(unfrozen)
    assert unfrozen["lifecycle_status"] == "ACTIVE"
    festival_after = validate_success(api.get_festival(festival["id"], _DIRECTOR), 200)
    assert festival_after["total_wallet_liability"] == 40.00, (
        f"expected total_wallet_liability 40.00, got {festival_after['total_wallet_liability']}")


# ─── cross_cutting_complexity_layers / rate_threshold_reentry_within_cap_succeeds ──

def test_reentry_within_cap_admitted(api):
    """PRD §3.7: "an entry is permitted only when the wristband has not yet been inside
    (its `entry_count` is still 0) or when the re-entries already used remain below the
    festival's `max_reentries` cap. On a successful entry the server moves
    `presence_status` to `INSIDE`, increases `entry_count` by one, and — if the
    `entry_count` was already at least 1 before this scan — increases `reentry_used` by
    one as well, then writes a gate event with outcome `ADMITTED`."

    With max_reentries 1, after ENTER+EXIT the first re-entry (reentry_used 0->1, just
    below the cap) is ADMITTED and reentry_used reads 1.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_reentry_within_cap_succeeds
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="ReOk F",
        rfid_uid="RF-RO-1", max_reentries=1)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    from test_helpers import gate_exit
    validate_success(gate_exit(festival["id"], wristband["id"]), 201)
    res = gate_enter(festival["id"], wristband["id"])
    event = validate_success(res, 201)
    assert event["outcome"] == "ADMITTED"
    after = validate_success(api.get_wristband(wristband["id"], _GATE), 200)
    assert after["reentry_used"] == 1


# ─── consistency_model / topup_balance_visible_immediately ───

def test_topup_balance_and_liability_visible_immediately(api):
    """PRD §3.6: "A top-up records a wallet transaction with `kind` of `TOPUP` and a
    positive `amount`, adds that amount to the wristband's `balance`, and adds it to the
    festival's `total_wallet_liability`."

    Topping up 25.00 then reading the wristband and festival in subsequent requests
    reflects balance 25.00 and total_wallet_liability 25.00 immediately.

    Design: Corner/consistency_model/topup_balance_visible_immediately
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                name="Immed F")
    open_sales(festival["id"])
    ticket = sell_ticket(festival["id"], purchaser_email="im@x.com")
    wristband = issue_wristband(festival["id"], "RF-IM-1")
    activate_wristband(wristband["id"], ticket["id"])
    topup(wristband["id"], 25.00)
    wb_after = validate_success(api.get_wristband(wristband["id"], _BOXOFFICE), 200)
    assert wb_after["balance"] == 25.00
    festival_after = validate_success(api.get_festival(festival["id"], _DIRECTOR), 200)
    assert festival_after["total_wallet_liability"] == 25.00
