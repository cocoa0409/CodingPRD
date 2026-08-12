"""
Composite setup helpers for multi-step test prerequisites.
Uses get_success_data() (lenient validator) internally so setup failures
produce clear "setup failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_property_payload,
    create_jurisdiction_policy_payload,
    create_banner_config_payload,
    create_vendor_payload,
    create_tag_rule_payload,
    create_visitor_payload,
    age_attestation_payload,
    gpc_signal_payload,
    create_consent_record_payload,
    create_do_not_sell_request_payload,
    create_tag_audit_scan_payload,
    run_scan_payload,
    observed_tracker,
    create_regulatory_sweep_payload,
)
from .test_users import TEST_USERS, make_visitor_headers, make_auditor_headers

ADMIN = TEST_USERS["privacy_admin_headers"]
VM = TEST_USERS["vendor_manager_headers"]
AUD1 = TEST_USERS["compliance_auditor_headers"]  # X-User-ID "aud-1"
ANON = TEST_USERS["anonymous_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_property(**overrides):
    """Create a Property. Returns the property dict."""
    return get_success_data(api_client.create_property(create_property_payload(**overrides), ADMIN))


def create_active_policy(property_id, **overrides):
    """Create a JurisdictionPolicy and activate it. Returns the ACTIVE policy."""
    pol = get_success_data(
        api_client.create_jurisdiction_policy(
            create_jurisdiction_policy_payload(property_id, **overrides), ADMIN
        )
    )
    return get_success_data(
        api_client.update_jurisdiction_policy(pol["id"], {"status": "ACTIVE"}, ADMIN)
    )


def create_published_banner_config(property_id, **overrides):
    """Create a banner config and publish it (reads fresh property version for OCC)."""
    cfg = get_success_data(
        api_client.create_banner_config(create_banner_config_payload(property_id, **overrides), ADMIN)
    )
    prop = get_success_data(api_client.get_property(property_id, ANY))
    return get_success_data(
        api_client.publish_banner_config(
            cfg["id"], {"expected_property_version": prop["version"]}, ADMIN
        )
    )


def create_approved_vendor(property_id, **overrides):
    """Register a vendor and approve it. Returns the APPROVED vendor."""
    vend = get_success_data(
        api_client.create_vendor(create_vendor_payload(property_id, **overrides), VM)
    )
    return get_success_data(api_client.approve_vendor(vend["id"], ADMIN))


def create_visitor(property_id, **overrides):
    """Register a visitor. Returns the VisitorProfile."""
    return get_success_data(
        api_client.create_visitor(create_visitor_payload(property_id, **overrides), ANON)
    )


def create_adult_visitor(property_id, birthdate="1990-01-01T00:00:00Z", **overrides):
    """Register a visitor and complete age attestation as an ADULT.
    Returns the attested VisitorProfile."""
    vis = create_visitor(property_id, **overrides)
    return get_success_data(
        api_client.attest_age(vis["id"], age_attestation_payload(birthdate), make_visitor_headers(vis["id"]))
    )


# ---------------------------------------------------------------------------
# Tier 2: composite hierarchies
# ---------------------------------------------------------------------------

def setup_property_with_active_policy(property_overrides=None, policy_overrides=None):
    """Property + ACTIVE jurisdiction policy. Returns (property, policy)."""
    prop = create_property(**(property_overrides or {}))
    pol = create_active_policy(prop["id"], **(policy_overrides or {}))
    return prop, pol


def setup_consent_ready(property_overrides=None, policy_overrides=None,
                        birthdate="1990-01-01T00:00:00Z", visitor_overrides=None):
    """Property + ACTIVE policy + ADULT visitor. Returns (property, policy, visitor)."""
    prop, pol = setup_property_with_active_policy(property_overrides, policy_overrides)
    v_overrides = {"jurisdiction_code": pol["jurisdiction_code"]}
    v_overrides.update(visitor_overrides or {})
    vis = create_adult_visitor(prop["id"], birthdate=birthdate, **v_overrides)
    return prop, pol, vis


def setup_granted_consent(purpose_category="ANALYTICS", property_overrides=None,
                          policy_overrides=None, birthdate="1990-01-01T00:00:00Z",
                          clock_iso=None, visitor_overrides=None):
    """Property + ACTIVE policy + ADULT visitor + one GRANTED consent record.
    Optionally pins the clock before granting. Returns (property, policy, visitor, record)."""
    prop, pol, vis = setup_consent_ready(
        property_overrides, policy_overrides, birthdate=birthdate,
        visitor_overrides=visitor_overrides,
    )
    if clock_iso:
        get_success_data(api_client.set_clock({"to_iso8601": clock_iso}, ADMIN))
    rec = get_success_data(
        api_client.create_consent_record(
            vis["id"], create_consent_record_payload(purpose_category),
            make_visitor_headers(vis["id"]),
        )
    )
    return prop, pol, vis, rec


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_published_config_with_rule(property_overrides=None, policy_overrides=None,
                                     vendor_overrides=None, purpose_category="ADVERTISING"):
    """Property + ACTIVE policy + PUBLISHED config + APPROVED vendor + ENABLED tag rule.
    Returns (property, policy, config, vendor, rule)."""
    prop, pol = setup_property_with_active_policy(property_overrides, policy_overrides)
    cfg = create_published_banner_config(
        prop["id"], jurisdiction_code=pol["jurisdiction_code"],
        categories_shown=[purpose_category],
    )
    vend = create_approved_vendor(
        prop["id"], declared_purposes=[purpose_category], **(vendor_overrides or {})
    )
    rule = get_success_data(
        api_client.create_tag_rule(
            create_tag_rule_payload(vend["id"], cfg["id"], purpose_category=purpose_category), VM
        )
    )
    return prop, pol, cfg, vend, rule


def setup_completed_scan_with_findings(observed_trackers, property_overrides=None,
                                       vendor_overrides=None, auditor_id="aud-1"):
    """Property (+ optional APPROVED vendor) + scan created and run by the given auditor.
    Returns (property, scan, findings_list)."""
    prop = create_property(**(property_overrides or {}))
    if vendor_overrides is not None:
        create_approved_vendor(prop["id"], **vendor_overrides)
    scan = get_success_data(
        api_client.create_tag_audit_scan(
            create_tag_audit_scan_payload(prop["id"]), make_auditor_headers(auditor_id)
        )
    )
    scan = get_success_data(
        api_client.run_tag_audit_scan(
            scan["id"], run_scan_payload(observed_trackers), make_auditor_headers(auditor_id)
        )
    )
    findings, _meta = _list_all(api_client.list_scan_findings(scan["id"], ANY))
    return prop, scan, findings


def _list_all(resp):
    """Unwrap a paginated list response into (data_list, meta)."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def setup_verified_dns_request(property_overrides=None, visitor_overrides=None,
                               request_overrides=None):
    """Property (SELLS_AND_SHARES by default) + visitor + VERIFIED do-not-sell request.
    Returns (property, visitor, request)."""
    prop = create_property(**(property_overrides or {}))
    vis = create_visitor(prop["id"], **(visitor_overrides or {}))
    req = get_success_data(
        api_client.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(**(request_overrides or {})),
            make_visitor_headers(vis["id"]),
        )
    )
    req = get_success_data(
        api_client.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    return prop, vis, req


def setup_propagated_dns(vendor_count=1, vendor_purposes=None, scope_categories=None):
    """Property + N APPROVED vendors + visitor + VERIFIED request + propagate executed.
    Returns (property, visitor, request, propagations_list)."""
    prop = create_property()
    purposes = vendor_purposes or ["SALE_SHARE"]
    for i in range(vendor_count):
        create_approved_vendor(
            prop["id"], legal_name=f"Vendor-{i}", tracker_signatures=[f"vend-{i}.com"],
            declared_purposes=purposes,
        )
    vis = create_visitor(prop["id"])
    req_overrides = {}
    if scope_categories is not None:
        req_overrides["scope_categories"] = scope_categories
    req = get_success_data(
        api_client.create_do_not_sell_request(
            vis["id"], create_do_not_sell_request_payload(**req_overrides),
            make_visitor_headers(vis["id"]),
        )
    )
    get_success_data(
        api_client.update_do_not_sell_request(req["id"], {"verification_status": "VERIFIED"}, ADMIN)
    )
    req = get_success_data(api_client.propagate_do_not_sell_request(req["id"], ADMIN))
    props, _meta = _list_all(api_client.list_request_propagations(req["id"], ANY))
    return prop, vis, req, props


# ---------------------------------------------------------------------------
# Tier 4: temporal / clock targeting
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def setup_open_sweep(property_overrides=None, sweep_overrides=None, auditor_id="aud-1"):
    """Property + OPEN regulatory sweep created by the given auditor.
    Returns (property, sweep)."""
    prop = create_property(**(property_overrides or {}))
    sweep = get_success_data(
        api_client.create_regulatory_sweep(
            create_regulatory_sweep_payload(prop["id"], **(sweep_overrides or {})),
            make_auditor_headers(auditor_id),
        )
    )
    return prop, sweep


# ---------------------------------------------------------------------------
# Tier 5: frozen / escalated terminal states
# ---------------------------------------------------------------------------

def setup_frozen_property(**sweep_overrides):
    """Property + sweep escalated (manual) -> posture FROZEN. Returns (property, sweep)."""
    prop, sweep = setup_open_sweep(sweep_overrides=sweep_overrides)
    sweep = get_success_data(
        api_client.escalate_regulatory_sweep(sweep["id"], make_auditor_headers("aud-1"))
    )
    return prop, sweep
