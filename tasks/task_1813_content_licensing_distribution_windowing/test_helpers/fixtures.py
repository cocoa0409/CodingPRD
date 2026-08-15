"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: PlatformBuyer calls are entity-backed by Platform. The
catalog workspace carries per-instance buyer headers built from the real
Platform.id via make_platform_buyer_headers(); ownership-gated calls never
fall back to the shared constant.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client
from .constants import (
    DEFAULT_METADATA_SPEC,
    DEFAULT_SELLABLE_FROM,
    DEFAULT_SELLABLE_TO,
    TEST_DEFAULTS,
)
from .factories import (
    create_avail_package_payload,
    create_delivery_batch_payload,
    create_license_payload,
    create_platform_payload,
    create_rights_holder_payload,
    create_rights_slot_payload,
    create_revenue_report_payload,
    create_royalty_statement_payload,
    create_title_payload,
    package_line_payload,
)
from .test_users import (
    TEST_USERS,
    make_finance_analyst_headers,
    make_finance_controller_headers,
    make_platform_buyer_headers,
)

RM = TEST_USERS["rights_manager_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_rights_holder(name="Test Holder", payee_reference="PAY-1",
                         royalty_share_pct=TEST_DEFAULTS["HOLDER_SHARE_PCT"]):
    """Register a rights holder. Returns the holder."""
    payload = create_rights_holder_payload(
        name=name, payee_reference=payee_reference,
        royalty_share_pct=royalty_share_pct,
    )
    return get_success_data(api_client.create_rights_holder(payload, RM))


def create_title(title_code="T1", name="Test Title", content_type="FILM",
                 original_language="en", production_year=2024,
                 embargoed_territories=None):
    """Register a title. Returns the title."""
    payload = create_title_payload(
        title_code=title_code, name=name, content_type=content_type,
        original_language=original_language, production_year=production_year,
    )
    if embargoed_territories is not None:
        payload["embargoed_territories"] = embargoed_territories
    return get_success_data(api_client.create_title(payload, RM))


def create_platform(name="Test Platform", platform_type="SVOD",
                    metadata_spec_version=DEFAULT_METADATA_SPEC,
                    required_asset_profiles=("4K_HDR",)):
    """Register a buyer platform. Returns the platform."""
    payload = create_platform_payload(
        name=name, platform_type=platform_type,
        metadata_spec_version=metadata_spec_version,
        required_asset_profiles=list(required_asset_profiles),
    )
    return get_success_data(api_client.create_platform(payload, RM))


def create_rights_slot(title_id, rights_holder_id, territory_code="US",
                       language_code="en", window_type="SVOD",
                       sellable_from=DEFAULT_SELLABLE_FROM,
                       sellable_to=DEFAULT_SELLABLE_TO):
    """Create a rights inventory slot (born AVAILABLE). Returns the slot."""
    payload = create_rights_slot_payload(
        title_id, rights_holder_id, territory_code=territory_code,
        language_code=language_code, window_type=window_type,
        sellable_from=sellable_from, sellable_to=sellable_to,
    )
    return get_success_data(api_client.create_rights_slot(payload, RM))


def advance_clock(to_iso8601, headers=None):
    """Advance the logical clock and run the expiration sweep. Returns tallies."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or RM))


# ---------------------------------------------------------------------------
# Tier 2: the catalog workspace (holder + title + platform + buyer headers)
# ---------------------------------------------------------------------------

def setup_catalog(holder_share=TEST_DEFAULTS["HOLDER_SHARE_PCT"],
                  platform_type="SVOD",
                  metadata_spec_version=DEFAULT_METADATA_SPEC,
                  required_asset_profiles=("4K_HDR",),
                  embargoed_territories=None,
                  title_code="T1"):
    """Holder + title + platform. Returns a workspace dict including
    buyer_headers threaded with the real Platform.id."""
    holder = create_rights_holder(royalty_share_pct=holder_share)
    title = create_title(title_code=title_code,
                         embargoed_territories=embargoed_territories)
    platform = create_platform(platform_type=platform_type,
                               metadata_spec_version=metadata_spec_version,
                               required_asset_profiles=required_asset_profiles)
    return {
        "holder": holder,
        "title": title,
        "platform": platform,
        "buyer_headers": make_platform_buyer_headers(platform["id"]),
    }


def add_slot(workspace, window_type="SVOD", territory_code="US", language_code="en",
             sellable_from=DEFAULT_SELLABLE_FROM, sellable_to=DEFAULT_SELLABLE_TO):
    """Add a slot to an existing catalog workspace. Returns the slot."""
    return create_rights_slot(
        workspace["title"]["id"], workspace["holder"]["id"],
        territory_code=territory_code, language_code=language_code,
        window_type=window_type, sellable_from=sellable_from,
        sellable_to=sellable_to,
    )


# ---------------------------------------------------------------------------
# Tier 3: licenses and packages
# ---------------------------------------------------------------------------

def create_direct_license(slot_id, platform_id,
                          license_start="2026-09-01T00:00:00Z",
                          license_end="2026-12-01T00:00:00Z",
                          exclusive=False, fee_model="FLAT_FEE",
                          flat_fee_cents=None, revenue_share_pct=None,
                          minimum_guarantee_cents=None, proration_mode=None,
                          extra_fields=None):
    """Direct deal against a slot (born EXECUTED). Returns the license."""
    payload = create_license_payload(
        slot_id, platform_id, license_start=license_start,
        license_end=license_end, exclusive=exclusive, fee_model=fee_model,
    )
    if fee_model == "FLAT_FEE":
        payload["flat_fee_cents"] = (
            flat_fee_cents if flat_fee_cents is not None
            else TEST_DEFAULTS["FLAT_FEE_CENTS"]
        )
    else:
        payload.pop("flat_fee_cents", None)
        if revenue_share_pct is not None:
            payload["revenue_share_pct"] = revenue_share_pct
        if minimum_guarantee_cents is not None:
            payload["minimum_guarantee_cents"] = minimum_guarantee_cents
    if proration_mode is not None:
        payload["proration_mode"] = proration_mode
    if extra_fields:
        payload.update(extra_fields)
    return get_success_data(api_client.create_license_agreement(payload, RM))


def get_license(license_id):
    return get_success_data(api_client.get_license_agreement(license_id, RM))


def get_slot(slot_id):
    return get_success_data(api_client.get_rights_slot(slot_id, RM))


def get_package(package_id):
    return get_success_data(api_client.get_avail_package(package_id, RM))


def make_line(slot_id, license_start="2026-09-01T00:00:00Z",
              license_end="2026-12-01T00:00:00Z", exclusive=False,
              fee_model="FLAT_FEE", flat_fee_cents=None, revenue_share_pct=None,
              minimum_guarantee_cents=None, proration_mode=None):
    """One embedded offer line for an avail package."""
    line = package_line_payload(
        slot_id, license_start=license_start, license_end=license_end,
        exclusive=exclusive, fee_model=fee_model,
    )
    if fee_model == "FLAT_FEE":
        line["flat_fee_cents"] = (
            flat_fee_cents if flat_fee_cents is not None
            else TEST_DEFAULTS["FLAT_FEE_CENTS"]
        )
    else:
        line.pop("flat_fee_cents", None)
        if revenue_share_pct is not None:
            line["revenue_share_pct"] = revenue_share_pct
        if minimum_guarantee_cents is not None:
            line["minimum_guarantee_cents"] = minimum_guarantee_cents
    if proration_mode is not None:
        line["proration_mode"] = proration_mode
    return line


def create_and_offer_package(platform_id, lines,
                             offer_expires_at=TEST_DEFAULTS["OFFER_EXPIRES_AT"],
                             name="PKG"):
    """Create a package and send the offer. Returns the OFFERED package."""
    payload = create_avail_package_payload(
        platform_id, lines, name=name, offer_expires_at=offer_expires_at,
    )
    package = get_success_data(api_client.create_avail_package(payload, RM))
    return get_success_data(api_client.offer_package(package["id"], RM))


def accept_package(package_id, accepted_slot_ids, buyer_headers):
    """PlatformBuyer accept. Returns the updated package (validated 200)."""
    return validate_success(
        api_client.accept_package(package_id, accepted_slot_ids, buyer_headers), 200
    )


# ---------------------------------------------------------------------------
# Tier 4: revenue reports (OCC-threaded) and recoupment state
# ---------------------------------------------------------------------------

def book_report(license_id, buyer_headers, period_start, period_end,
                gross_revenue_cents):
    """Submit a revenue report, threading the license's current version (OCC).
    Returns the created RevenueReport."""
    license_now = get_license(license_id)
    payload = create_revenue_report_payload(
        period_start, period_end, gross_revenue_cents, license_now["version"],
    )
    return get_success_data(
        api_client.submit_revenue_report(license_id, payload, buyer_headers)
    )


def list_reports_for_license(license_id):
    data, _meta = validate_paginated(
        api_client.list_revenue_reports(RM, params={"license_id": license_id})
    )
    return data


def reverse_report(report_id):
    return get_success_data(api_client.reverse_revenue_report(report_id, FA))


# ---------------------------------------------------------------------------
# Tier 5: deliveries, statements, takedown notices
# ---------------------------------------------------------------------------

def create_and_deliver_batch(license_id, platform):
    """Queue a spec-complete batch for the license and submit it to DELIVERED.
    The manifest covers the platform's required profiles and matches its
    metadata spec. Returns the DELIVERED batch."""
    payload = create_delivery_batch_payload(
        license_id,
        asset_manifest=list(platform["required_asset_profiles"]),
        metadata_spec_version=platform["metadata_spec_version"],
    )
    batch = get_success_data(api_client.create_delivery_batch(payload, RM))
    return get_success_data(api_client.submit_delivery_batch(batch["id"], RM))


def create_statement(rights_holder_id, period_start, period_end,
                     attribution_mode="BY_REPORT_DATE", user_id="fin-ana-1"):
    """Create a DRAFT royalty statement. Returns the statement."""
    payload = create_royalty_statement_payload(
        rights_holder_id, period_start, period_end, attribution_mode,
    )
    return get_success_data(
        api_client.create_royalty_statement(payload, make_finance_analyst_headers(user_id))
    )


def finalize_statement(statement_id, user_id="fin-ana-1"):
    return get_success_data(
        api_client.finalize_statement(statement_id, make_finance_analyst_headers(user_id))
    )


def mark_statement_paid(statement_id, user_id="fin-ctl-1"):
    return get_success_data(
        api_client.mark_statement_paid(statement_id,
                                       make_finance_controller_headers(user_id))
    )


def list_notices_for_license(license_id):
    data, _meta = validate_paginated(
        api_client.list_takedown_notices(RM, params={"license_id": license_id})
    )
    return data


def list_all_licenses():
    data, _meta = validate_paginated(api_client.list_license_agreements(RM))
    return data
