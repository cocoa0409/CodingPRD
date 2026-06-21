"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims need the system walked through several API calls to
reach a testable state (an ACTIVE vendor with an APPROVED application, a booth
SEASON_HELD with a rank-1 waitlister, a SUBMITTED sales report on a PRESENT
check-in, ...). These helpers encapsulate those sequences.

All helpers use get_success_data() (lenient 2xx validator) so a setup failure
surfaces as a clear "Setup failed" error rather than a confusing assertion miss.

Identity threading: the Vendor role is entity_backed, so any ownership-gated
Vendor call uses make_vendor_headers(vendor_id) with the real vendor id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_market_payload,
    create_vendor_payload,
    create_permit_payload,
    create_application_payload,
    create_booth_payload,
    create_market_day_payload,
    create_booth_assignment_payload,
    create_check_in_payload,
    create_sales_report_payload,
    create_voucher_batch_payload,
    create_voucher_redemption_payload,
)
from .test_users import TEST_USERS, make_vendor_headers

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Tier 1: primitive creators ───────────────────────────────────────────
def create_market(**overrides) -> dict:
    """Create a market with the standard (or overridden) policy. Returns Market."""
    res = api_client.create_market(create_market_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_vendor(market_id: str, **overrides) -> dict:
    """Register a PROSPECT vendor under a market. Returns Vendor."""
    res = api_client.create_vendor(create_vendor_payload(market_id, **overrides), ADMIN)
    return get_success_data(res)


def create_booth(market_id: str, **overrides) -> dict:
    """Create an OPEN booth on the market map. Returns Booth (incl. version)."""
    res = api_client.create_booth(create_booth_payload(market_id, **overrides), ADMIN)
    return get_success_data(res)


def create_market_day(market_id: str, **overrides) -> dict:
    """Schedule a market day. Returns MarketDay in SCHEDULED status."""
    res = api_client.create_market_day(create_market_day_payload(market_id, **overrides), ADMIN)
    return get_success_data(res)


def create_open_market_day(market_id: str, **overrides) -> dict:
    """Schedule and open a market day. Returns the OPEN MarketDay."""
    day = create_market_day(market_id, **overrides)
    return get_success_data(api_client.open_market_day(day["id"], ADMIN))


def booth_version(booth_id: str) -> int:
    """Read the booth's current version (needed for SEASON OCC threading)."""
    return get_success_data(api_client.get_booth(booth_id, ADMIN))["version"]


# ─── Tier 2: vendor onboarding ─────────────────────────────────────────────
def create_active_vendor(market_id: str, product_category: str = "CRAFTS",
                        legal_name: str = "V1", contact_email: str = "v1@x.com") -> dict:
    """Register a vendor, submit + review + approve one application so the vendor
    is ACTIVE with an APPROVED application of `product_category`.

    Used when the category needs no health permit (PRODUCE/BAKED_GOODS/CRAFTS/
    FLOWERS). Returns the Vendor (re-fetched so status==ACTIVE is reflected).
    """
    vendor = create_vendor(market_id, legal_name=legal_name, contact_email=contact_email)
    vh = make_vendor_headers(vendor["id"])
    app = get_success_data(api_client.create_application(
        create_application_payload(vendor["id"], product_category=product_category), vh))
    get_success_data(api_client.start_review_application(app["id"], ADMIN))
    get_success_data(api_client.approve_application(app["id"], {"review_note": "ok"}, ADMIN))
    return get_success_data(api_client.get_vendor(vendor["id"], ADMIN))


def create_verified_health_permit(vendor_id: str, issue_date: str = "2026-05-01",
                                expiry_date: str = "2026-12-31",
                                permit_number: str = "H-1") -> dict:
    """Submit and VERIFY a HEALTH permit for the vendor. Returns the VERIFIED Permit."""
    vh = make_vendor_headers(vendor_id)
    permit = get_success_data(api_client.create_permit(
        create_permit_payload(vendor_id, permit_type="HEALTH",
                            permit_number=permit_number,
                            issue_date=issue_date, expiry_date=expiry_date), vh))
    return get_success_data(api_client.verify_permit(permit["id"], {"decision": "VERIFY"}, ADMIN))


def create_active_vendor_with_health_permit(market_id: str, product_category: str = "MEAT",
                                            legal_name: str = "V1",
                                            contact_email: str = "v1@x.com",
                                            permit_expiry: str = "2026-12-31") -> dict:
    """Vendor with a VERIFIED HEALTH permit, then an APPROVED application in a
    health-gated category (DAIRY/MEAT/PREPARED_FOOD). Returns the ACTIVE Vendor.
    """
    vendor = create_vendor(market_id, legal_name=legal_name, contact_email=contact_email)
    create_verified_health_permit(vendor["id"], expiry_date=permit_expiry)
    vh = make_vendor_headers(vendor["id"])
    app = get_success_data(api_client.create_application(
        create_application_payload(vendor["id"], product_category=product_category), vh))
    get_success_data(api_client.start_review_application(app["id"], ADMIN))
    get_success_data(api_client.approve_application(app["id"], {"review_note": "ok"}, ADMIN))
    return get_success_data(api_client.get_vendor(vendor["id"], ADMIN))


def create_submitted_application(market_id: str, product_category: str = "CRAFTS",
                                legal_name: str = "V1",
                                contact_email: str = "v1@x.com") -> tuple:
    """Vendor + a SUBMITTED application (no start-review). Returns (vendor, application)."""
    vendor = create_vendor(market_id, legal_name=legal_name, contact_email=contact_email)
    vh = make_vendor_headers(vendor["id"])
    app = get_success_data(api_client.create_application(
        create_application_payload(vendor["id"], product_category=product_category), vh))
    return vendor, app


def create_under_review_application(market_id: str, product_category: str = "CRAFTS",
                                    legal_name: str = "V1",
                                    contact_email: str = "v1@x.com") -> tuple:
    """Vendor + an UNDER_REVIEW application. Returns (vendor, application)."""
    vendor, app = create_submitted_application(
        market_id, product_category, legal_name, contact_email)
    get_success_data(api_client.start_review_application(app["id"], ADMIN))
    return vendor, app


def create_rejected_application(market_id: str, product_category: str = "CRAFTS",
                                legal_name: str = "V1", contact_email: str = "v1@x.com",
                                review_note: str = "needs detail") -> tuple:
    """Vendor + a REJECTED application (submitted -> review -> reject).
    Returns (vendor, application)."""
    vendor, app = create_under_review_application(
        market_id, product_category, legal_name, contact_email)
    get_success_data(api_client.reject_application(app["id"], {"review_note": review_note}, ADMIN))
    return vendor, app


# ─── Tier 3: booth assignment lifecycles ───────────────────────────────────
def reserve_season_assignment(market_id: str, booth_id: str, vendor_id: str) -> dict:
    """Create a SEASON assignment that reserves the booth (booth must be OPEN).
    Threads the current booth version into expected_booth_version. Returns the
    RESERVED BoothAssignment."""
    vh = make_vendor_headers(vendor_id)
    payload = create_booth_assignment_payload(
        market_id, booth_id, vendor_id, assignment_type="SEASON",
        expected_booth_version=booth_version(booth_id))
    return get_success_data(api_client.create_booth_assignment(payload, vh))


def waitlist_season_assignment(market_id: str, booth_id: str, vendor_id: str) -> dict:
    """Create a SEASON assignment on an occupied booth with allow_waitlist=true so
    it lands WAITLISTED. Threads the current (held) booth version. Returns the
    BoothAssignment."""
    vh = make_vendor_headers(vendor_id)
    payload = create_booth_assignment_payload(
        market_id, booth_id, vendor_id, assignment_type="SEASON",
        allow_waitlist=True, expected_booth_version=booth_version(booth_id))
    return get_success_data(api_client.create_booth_assignment(payload, vh))


def reserve_daily_assignment(market_id: str, booth_id: str, vendor_id: str,
                            market_day_id: str) -> dict:
    """Create a DAILY assignment that reserves the booth for one open day.
    Returns the RESERVED BoothAssignment."""
    vh = make_vendor_headers(vendor_id)
    payload = create_booth_assignment_payload(
        market_id, booth_id, vendor_id, assignment_type="DAILY",
        market_day_id=market_day_id)
    return get_success_data(api_client.create_booth_assignment(payload, vh))


def setup_season_held_with_waitlister(corner: bool = True) -> dict:
    """Standard market; one CORNER booth held by V1's RESERVED SEASON assignment;
    V2's later SEASON request auto-WAITLISTED at rank 1.

    Returns a dict with keys: market, booth, v1, v2, asg1 (reserved), asg2 (waitlisted).
    """
    market = create_market()
    size = "CORNER" if corner else "SINGLE"
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class=size)
    v1 = create_active_vendor(market["id"], product_category="CRAFTS",
                            legal_name="V1", contact_email="v1@x.com")
    v2 = create_active_vendor(market["id"], product_category="FLOWERS",
                            legal_name="V2", contact_email="v2@x.com")
    asg1 = reserve_season_assignment(market["id"], booth["id"], v1["id"])
    asg2 = waitlist_season_assignment(market["id"], booth["id"], v2["id"])
    return {"market": market, "booth": booth, "v1": v1, "v2": v2,
            "asg1": asg1, "asg2": asg2}


def setup_season_held_two_waitlisters() -> dict:
    """CORNER booth held by V1 (RESERVED SEASON); V2 WAITLISTED rank1; V3 WAITLISTED rank2.

    Returns dict with: market, booth, v1, v2, v3, asg1, asg2, asg3.
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    v1 = create_active_vendor(market["id"], "CRAFTS", "V1", "v1@x.com")
    v2 = create_active_vendor(market["id"], "FLOWERS", "V2", "v2@x.com")
    v3 = create_active_vendor(market["id"], "FLOWERS", "V3", "v3@x.com")
    asg1 = reserve_season_assignment(market["id"], booth["id"], v1["id"])
    asg2 = waitlist_season_assignment(market["id"], booth["id"], v2["id"])
    asg3 = waitlist_season_assignment(market["id"], booth["id"], v3["id"])
    return {"market": market, "booth": booth, "v1": v1, "v2": v2, "v3": v3,
            "asg1": asg1, "asg2": asg2, "asg3": asg3}


# ─── Tier 4: attendance + sales-report setup ──────────────────────────────
def setup_present_check_in(product_category: str = "CRAFTS") -> dict:
    """Standard market; SINGLE booth; ACTIVE vendor; OPEN day; RESERVED DAILY
    assignment; an ARRIVED (PRESENT) check-in.

    Returns dict: market, booth, vendor, day, assignment, check_in.
    """
    market = create_market()
    booth = create_booth(market["id"], label="B-01", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category, "V1", "v1@x.com")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api_client.create_check_in(
        create_check_in_payload(market["id"], asg["id"], day["id"]), vh))
    ci = get_success_data(api_client.arrive_check_in(ci["id"], vh))
    return {"market": market, "booth": booth, "vendor": vendor, "day": day,
            "assignment": asg, "check_in": ci}


def setup_submitted_sales_report(gross_sales_cents: int = 30000,
                                tokens_accepted: int = 0,
                                product_category: str = "CRAFTS") -> dict:
    """A PRESENT check-in plus a SUBMITTED sales report on it.

    Returns dict: market, booth, vendor, day, assignment, check_in, sales_report.
    The provisional commission is already computed on submit.
    """
    base = setup_present_check_in(product_category)
    vh = make_vendor_headers(base["vendor"]["id"])
    sr = get_success_data(api_client.create_sales_report(
        create_sales_report_payload(base["market"]["id"], base["check_in"]["id"],
                                    gross_sales_cents=gross_sales_cents,
                                    tokens_accepted=tokens_accepted), vh))
    sr = get_success_data(api_client.submit_sales_report(sr["id"], {}, vh))
    base["sales_report"] = sr
    return base


# ─── Tier 5: voucher setup ─────────────────────────────────────────────────
def setup_open_day_with_batch(tokens_issued: int = 100) -> dict:
    """Standard market; one vendor; OPEN day; one ISSUED voucher batch.

    Returns dict: market, vendor, day, batch.
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    batch = get_success_data(api_client.create_voucher_batch(
        create_voucher_batch_payload(market["id"], day["id"], tokens_issued=tokens_issued),
        MANAGER))
    return {"market": market, "vendor": vendor, "day": day, "batch": batch}


def submit_redemption(market_id: str, batch_id: str, vendor_id: str,
                    market_day_id: str, token_count: int) -> dict:
    """Submit a voucher redemption (SUBMITTED). Returns the VoucherRedemption."""
    vh = make_vendor_headers(vendor_id)
    return get_success_data(api_client.create_voucher_redemption(
        create_voucher_redemption_payload(market_id, batch_id, vendor_id,
                                        market_day_id, token_count=token_count), vh))


def reconcile_redemption(redemption_id: str) -> dict:
    """Reconcile a SUBMITTED redemption (-> RECONCILED). Returns the redemption."""
    return get_success_data(api_client.reconcile_voucher_redemption(redemption_id, MANAGER))


def setup_reconciled_redemption(tokens_issued: int = 100, token_count: int = 40) -> dict:
    """OPEN day + batch + a single RECONCILED redemption of `token_count` tokens.

    Returns dict: market, vendor, day, batch, redemption.
    """
    base = setup_open_day_with_batch(tokens_issued=tokens_issued)
    red = submit_redemption(base["market"]["id"], base["batch"]["id"],
                            base["vendor"]["id"], base["day"]["id"], token_count)
    red = reconcile_redemption(red["id"])
    base["redemption"] = red
    return base
