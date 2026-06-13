"""Permit and category gating, cross-entity state dependencies, and the
priority-pair validation conflicts where one gate pre-empts another.

Covers Difficulty rules priority_pair_validation_conflict, cross_entity_state_
dependency, boundary_precision_check (empty allowed_categories), plus the corner
permit-expiry sweep instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_vendor_headers,
    TEST_USERS,
    create_market, create_booth, create_vendor, create_active_vendor,
    create_active_vendor_with_health_permit, create_verified_health_permit,
    create_open_market_day, reserve_daily_assignment, booth_version,
    create_booth_assignment_payload, setup_present_check_in,
    submit_redemption,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_permit_gate_pre_empts_category_gate(api):
    """PRD 2.11: "then the permit-safety gate (ERR_PERMIT_NOT_VERIFIED); then the
    category gate (ERR_CATEGORY_NOT_ALLOWED)" and "An earlier failure short-circuits
    and masks any later one". A DAILY request by a vendor whose permit_ok is false
    AND whose category is disallowed surfaces ERR_PERMIT_NOT_VERIFIED.

    Design: Difficulty/priority_pair_validation_conflict/permit_safety_beats_category_constraint
    """
    market = create_market()
    # Clock before the permit window so we can verify, then expire it.
    validate_success(api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN), 200)
    booth = create_booth(market["id"], label="P-1", grid_row=0, grid_col=1,
                        size_class="SINGLE", allowed_categories=["PRODUCE"])
    # Vendor approved for DAIRY (disallowed by the booth) via a HEALTH permit that
    # is verified for approval (expiry on/after the market's season_start_date of
    # 2026-06-01, per PRD 3.2) but expires before the assignment day, so permit_ok
    # is false at assignment time.
    vendor = create_active_vendor_with_health_permit(
        market["id"], product_category="DAIRY", permit_expiry="2026-06-03")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    # Advance clock past the permit expiry; the sweep expires it and recomputes permit_ok.
    validate_success(api.set_clock({"to_iso8601": "2026-06-06T08:00:00Z"}, ADMIN), 200)

    vh = make_vendor_headers(vendor["id"])
    res = api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], vendor["id"],
                                        assignment_type="DAILY",
                                        market_day_id=day["id"]), vh)
    validate_error(res, "ERR_PERMIT_NOT_VERIFIED")


def test_permit_gate_blocks_assignment_when_permit_lapsed(api):
    """PRD 3.3: "the vendor's permit_ok must be true, evaluated against the
    assignment window ... A vendor whose permit_ok is false at that window is
    rejected with ERR_PERMIT_NOT_VERIFIED." Here the booth allows the vendor's
    category, so only the permit-safety gate (priority 8) can fire — confirming it
    is the permit gate, not the category gate, that rejects.

    Design: Difficulty/priority_pair_validation_conflict/permit_safety_beats_category_constraint
    """
    market = create_market()
    validate_success(api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN), 200)
    # Empty allowed_categories => category gate cannot fire (all categories welcome).
    booth = create_booth(market["id"], label="P-2", grid_row=0, grid_col=2,
                        size_class="SINGLE", allowed_categories=[])
    # Permit verified for approval (expiry >= season_start 2026-06-01, PRD 3.2)
    # but lapsed before the 2026-06-06 assignment day.
    vendor = create_active_vendor_with_health_permit(
        market["id"], product_category="DAIRY", permit_expiry="2026-06-03")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    validate_success(api.set_clock({"to_iso8601": "2026-06-06T08:00:00Z"}, ADMIN), 200)

    vh = make_vendor_headers(vendor["id"])
    res = api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], vendor["id"],
                                        assignment_type="DAILY",
                                        market_day_id=day["id"]), vh)
    validate_error(res, "ERR_PERMIT_NOT_VERIFIED")


def test_state_check_pre_empts_token_overdraw_on_reconcile(api):
    """PRD 2.11: "then the state-legality check that the target is in a state from
    which the transition is permitted (ERR_INVALID_STATE) ... then the voucher
    fiscal cap (ERR_TOKEN_OVERDRAW)" and earlier failures mask later ones.
    Re-reconciling an already-RECONCILED redemption is an illegal transition, so
    ERR_INVALID_STATE wins even when the token cap would also be violated.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_token_overdraw_on_reconcile
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 50}, MANAGER))
    red = submit_redemption(market["id"], batch["id"], vendor["id"], day["id"], 40)
    validate_success(api.reconcile_voucher_redemption(red["id"], MANAGER), 200)

    res = api.reconcile_voucher_redemption(red["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")


def test_already_reconciled_redemption_stays_reconciled_after_blocked_reconcile(api):
    """PRD 3.7: "Reconciliation is legal only when the redemption is SUBMITTED and
    the owning market day is OPEN or CLOSED but not CANCELLED". PRD 3.3: an illegal
    transition "is rejected with ERR_INVALID_STATE" and so does not mutate the row.
    The already-RECONCILED redemption keeps its RECONCILED status and locked
    reimbursement even though a re-reconcile would also overdraw the batch (the
    state check at priority 6 masks the fiscal cap at priority 11).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_token_overdraw_on_reconcile
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 50}, MANAGER))
    red = submit_redemption(market["id"], batch["id"], vendor["id"], day["id"], 40)
    validate_success(api.reconcile_voucher_redemption(red["id"], MANAGER), 200)

    res = api.reconcile_voucher_redemption(red["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_voucher_redemption(red["id"], ADMIN))
    assert after["status"] == "RECONCILED"
    assert after["reimbursed_cents"] == 8000, "40 tokens * 200 face, unchanged"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_approve_health_gated_application_without_permit_rejected(api):
    """PRD 3.2: "where requires_health_permit is true it additionally requires the
    applicant vendor to hold at least one permit whose permit_type is HEALTH, whose
    status is VERIFIED, and whose expiry_date is on or after the market's
    season_start_date; approving a health-gated application without such a permit is
    rejected with ERR_NO_HEALTH_PERMIT." A PENDING permit does not satisfy it.

    Design: Difficulty/cross_entity_state_dependency/application_approve_requires_verified_health_permit
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    vh = make_vendor_headers(vendor["id"])
    # PENDING (not verified) HEALTH permit.
    get_success_data(api.create_permit(
        {"vendor_id": vendor["id"], "permit_type": "HEALTH", "permit_number": "H-2",
         "issue_date": "2026-05-01", "expiry_date": "2026-12-31"}, vh))
    app = get_success_data(api.create_application(
        {"vendor_id": vendor["id"], "product_category": "PREPARED_FOOD"}, vh))
    get_success_data(api.start_review_application(app["id"], ADMIN))

    res = api.approve_application(app["id"], {"review_note": "try"}, ADMIN)
    validate_error(res, "ERR_NO_HEALTH_PERMIT")
    after = get_success_data(api.get_application(app["id"], ADMIN))
    assert after["status"] == "UNDER_REVIEW", "unchanged"


def test_approve_health_gated_application_succeeds_once_permit_verified(api):
    """PRD 3.2: approval of a health-gated category "additionally requires the
    applicant vendor to hold at least one permit whose permit_type is HEALTH, whose
    status is VERIFIED, and whose expiry_date is on or after the market's
    season_start_date" — once such a permit exists, the same approve succeeds and
    moves the PREPARED_FOOD application to APPROVED.

    Design: Difficulty/cross_entity_state_dependency/application_approve_requires_verified_health_permit
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    create_verified_health_permit(vendor["id"], issue_date="2026-05-01",
                                expiry_date="2026-12-31")
    vh = make_vendor_headers(vendor["id"])
    app = get_success_data(api.create_application(
        {"vendor_id": vendor["id"], "product_category": "PREPARED_FOOD"}, vh))
    get_success_data(api.start_review_application(app["id"], ADMIN))

    approved = validate_success(api.approve_application(app["id"], {"review_note": "ok"}, ADMIN), 200)
    assert approved["status"] == "APPROVED"


def test_reconcile_sales_report_blocked_by_unreconciled_redemption(api):
    """PRD 3.8: "Reconciliation is legal only when the report is SUBMITTED and when
    every voucher redemption for the same vendor and market day has itself reached
    RECONCILED." A still-SUBMITTED redemption for the same vendor+day blocks it.
    PRD 3.3: an illegal transition is rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/sales_reconcile_requires_redemptions_reconciled
    """
    base = setup_present_check_in(product_category="CRAFTS")
    market, vendor, day, ci = base["market"], base["vendor"], base["day"], base["check_in"]
    vh = make_vendor_headers(vendor["id"])
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 100}, MANAGER))
    # A SUBMITTED (un-reconciled) redemption for the same vendor+day.
    submit_redemption(market["id"], batch["id"], vendor["id"], day["id"], 20)
    sr = get_success_data(api.create_sales_report(
        {"market_id": market["id"], "check_in_id": ci["id"],
         "gross_sales_cents": 30000, "tokens_accepted": 50}, vh))
    sr = get_success_data(api.submit_sales_report(sr["id"], {}, vh))

    res = api.reconcile_sales_report(sr["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_sales_report(sr["id"], ADMIN))
    assert after["status"] == "SUBMITTED", "unchanged"


def test_reconcile_sales_report_succeeds_once_redemption_reconciled(api):
    """PRD 3.8: reconciliation "is legal only when the report is SUBMITTED and when
    every voucher redemption for the same vendor and market day has itself reached
    RECONCILED." Once the blocking redemption is reconciled, the sales report
    reconcile succeeds and moves the report to RECONCILED.

    Design: Difficulty/cross_entity_state_dependency/sales_reconcile_requires_redemptions_reconciled
    """
    base = setup_present_check_in(product_category="CRAFTS")
    market, vendor, day, ci = base["market"], base["vendor"], base["day"], base["check_in"]
    vh = make_vendor_headers(vendor["id"])
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 100}, MANAGER))
    red = submit_redemption(market["id"], batch["id"], vendor["id"], day["id"], 20)
    sr = get_success_data(api.create_sales_report(
        {"market_id": market["id"], "check_in_id": ci["id"],
         "gross_sales_cents": 30000, "tokens_accepted": 50}, vh))
    sr = get_success_data(api.submit_sales_report(sr["id"], {}, vh))

    validate_success(api.reconcile_voucher_redemption(red["id"], MANAGER), 200)
    reconciled = validate_success(api.reconcile_sales_report(sr["id"], MANAGER), 200)
    assert reconciled["status"] == "RECONCILED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check (empty allowed_categories edge)
# ---------------------------------------------------------------------------
def test_empty_allowed_categories_admits_any_category(api):
    """PRD 3.1: an allowed_categories array names which categories the booth may
    host — "an empty array meaning all categories are welcome". PRD 3.3: "The
    booth's allowed_categories, if non-empty, must contain the vendor's approved
    product_category". So a MEAT vendor reserves on an empty-list booth.

    Design: Difficulty/boundary_precision_check/empty_allowed_categories_means_all_allowed
    """
    market = create_market()
    validate_success(api.set_clock({"to_iso8601": "2026-06-06T08:00:00Z"}, ADMIN), 200)
    booth = create_booth(market["id"], label="B-1", grid_row=0, grid_col=1,
                        size_class="SINGLE", allowed_categories=[])
    vendor = create_active_vendor_with_health_permit(
        market["id"], product_category="MEAT", permit_expiry="2026-12-31")
    day = create_open_market_day(market["id"], market_date="2026-06-06")

    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    assert asg["status"] == "RESERVED"
    assert asg["fee_charged_cents"] == 4000


def test_empty_allowed_categories_admits_produce_vendor(api):
    """PRD 3.1: "an allowed_categories array naming which product categories the
    booth may host — an empty array meaning all categories are welcome." PRD 3.3:
    "The booth's allowed_categories, if non-empty, must contain the vendor's
    approved product_category". So a PRODUCE vendor reserves on an empty-list booth.

    Design: Difficulty/boundary_precision_check/empty_allowed_categories_means_all_allowed
    """
    market = create_market()
    booth = create_booth(market["id"], label="B-2", grid_row=0, grid_col=2,
                        size_class="SINGLE", allowed_categories=[])
    vendor = create_active_vendor(market["id"], product_category="PRODUCE")
    day = create_open_market_day(market["id"], market_date="2026-06-06")

    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    assert asg["status"] == "RESERVED"
    assert asg["fee_charged_cents"] == 4000


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers (permit expiry sweep)
# ---------------------------------------------------------------------------
def test_clock_sweep_expires_permit_and_demotes_permit_ok(api):
    """PRD 3.9: "any permit that was VERIFIED whose expiry_date now falls before
    the current date transitions to EXPIRED, and the owning vendor's permit_ok is
    recomputed to reflect the lost permit."

    The vendor is approved for DAIRY — a health-gated category (PRD 2.10) — so its
    permit_ok depends on holding a VERIFIED HEALTH permit. Sweeping that permit to
    EXPIRED therefore demotes permit_ok to false.

    Design: Corner/cross_cutting_complexity_layers/permit_expiry_sweep_demotes_permit_ok
    """
    market = create_market()
    validate_success(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN), 200)
    # Vendor approved for DAIRY via a VERIFIED HEALTH permit whose expiry (2026-06-30)
    # is on/after season_start (2026-06-01) so the approval is legal (PRD 3.2).
    vendor = create_active_vendor_with_health_permit(
        market["id"], product_category="DAIRY", permit_expiry="2026-06-30")
    permit = get_success_data(
        api.list_permits(ADMIN, params={"vendor_id": vendor["id"]}))[0]
    assert permit["status"] == "VERIFIED"
    vendor_before = get_success_data(api.get_vendor(vendor["id"], ADMIN))
    assert vendor_before["permit_ok"] is True

    validate_success(api.set_clock({"to_iso8601": "2026-07-01T00:00:00Z"}, ADMIN), 200)

    permit_after = get_success_data(api.get_permit(permit["id"], ADMIN))
    assert permit_after["status"] == "EXPIRED"
    vendor_after = get_success_data(api.get_vendor(vendor["id"], ADMIN))
    assert vendor_after["permit_ok"] is False
