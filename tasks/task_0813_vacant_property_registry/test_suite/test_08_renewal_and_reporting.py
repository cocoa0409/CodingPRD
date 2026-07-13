"""Renewal optimistic concurrency and the aggregate registry report.

Covers corner instances from the cross_cutting_complexity_layers and endpoints
sections.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_registrant_headers, create_registrant, create_property,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_renew_with_stale_version_returns_412(api):
    """PRD §2.8: "If the value the client supplies does not equal the property's
    current `version` — because a prior renewal, a cascade, or any other mutation
    has advanced the property since the client last read it — the renewal is
    rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/renew_stale_property_version_returns_412
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    headers = make_registrant_headers(registrant["id"])
    first = validate_success(
        api.renew_property(prop["id"], {"expected_property_version": prop["version"]}, headers)
    )
    assert first["version"] == 2
    # Reuse the stale (pre-first-renewal) version.
    resp = api.renew_property(
        prop["id"], {"expected_property_version": prop["version"]}, headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROPERTY_VERSION.value)


def test_renew_with_current_version_succeeds_and_extends_expiry(api):
    """PRD §3.1: "Renewing a registration extends the property's
    `registration_expires_at` by a further 365 days beyond its current value and
    increments the property's `version`."
    PRD §2.8: "A renewal request must carry `expected_property_version`, and the
    server compares it to the target property's current `version`."

    Design: Corner/cross_cutting_complexity_layers/renew_correct_version_succeeds_and_extends_expiry
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    headers = make_registrant_headers(registrant["id"])
    renewed = validate_success(
        api.renew_property(prop["id"], {"expected_property_version": prop["version"]}, headers)
    )
    assert renewed["version"] == 2
    # registered_at 2026-03-01 -> expires 2027-03-01 -> +365 days -> 2028-02-29.
    assert renewed["registration_expires_at"].startswith("2028-02-29")


def test_registry_summary_aggregates_properties_and_balances(api):
    """PRD §3.10: "Its response reports `total_properties` (the number of
    properties in scope) ... the `total_outstanding_balance_cents` and
    `total_lien_balance_cents` summed across the in-scope properties".
    PRD §3.1: registration fee is 10000 for an OWNER/VACANT property and 15000 for
    an OWNER/ABANDONED property (10000 base + 50% surcharge).

    Design: Corner/endpoints/registry_summary_report_aggregates
    """
    registrant = create_registrant(api, party_type="OWNER")
    create_property(api, registrant, occupancy_status="VACANT", registration_type="OWNER")
    create_property(api, registrant, occupancy_status="ABANDONED", registration_type="OWNER")
    report = validate_success(api.get_registry_summary(ADMIN))
    assert report["total_properties"] == 2
    assert report["total_outstanding_balance_cents"] == 25000
