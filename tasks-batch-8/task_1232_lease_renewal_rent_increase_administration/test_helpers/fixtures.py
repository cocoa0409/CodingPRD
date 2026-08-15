"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before every test, so each test starts from
an empty database and the default logical clock 2026-05-01T00:00:00Z).

Setup calls use the lenient get_success_data() so failures surface as clear
"Setup failed" errors rather than assertion noise.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import CA_OAK, STD_RENT_CENTS, STD_TERM_MONTHS, STD_TERM_START
from .factories import (
    ca_oak_policy_payload,
    create_lease_payload,
    create_notice_payload,
    create_offer_payload,
    create_property_payload,
    create_resident_payload,
    create_unit_payload,
    respond_accept_payload,
    respond_counter_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_resident_headers

ADMIN = TEST_USERS["admin_headers"]
PM1 = TEST_USERS["pm_1_headers"]
LA1 = TEST_USERS["la_1_headers"]


def _setup_fail(what: str, resp):
    raise AssertionError(f"Setup failed at {what}: status={resp.status_code} body={resp.text}")


def _ok(resp, what: str):
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data:
        # get_success_data is lenient; ensure the call truly succeeded.
        if resp.status_code >= 400:
            _setup_fail(what, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def create_policy(payload=None, headers=None):
    resp = api_client.create_rent_cap_policy(payload or ca_oak_policy_payload(), headers or ADMIN)
    if resp.status_code != 201:
        _setup_fail("create_policy", resp)
    return validate_success(resp, 201)


def create_property(policy_id, min_term_months=12, max_term_months=12, name=None, headers=None):
    payload = create_property_payload(
        policy_id, min_term_months=min_term_months, max_term_months=max_term_months,
    )
    if name is not None:
        payload["name"] = name
    resp = api_client.create_property(payload, headers or ADMIN)
    if resp.status_code != 201:
        _setup_fail("create_property", resp)
    return validate_success(resp, 201)


def create_unit(property_id, market_rent_cents=210000, unit_number=None, bedrooms=1, headers=None):
    payload = create_unit_payload(
        property_id, bedrooms=bedrooms, current_market_rent_cents=market_rent_cents,
    )
    if unit_number is not None:
        payload["unit_number"] = unit_number
    resp = api_client.create_unit(payload, headers or ADMIN)
    if resp.status_code != 201:
        _setup_fail("create_unit", resp)
    return validate_success(resp, 201)


def create_resident(full_name=None, email=None, headers=None):
    payload = create_resident_payload()
    if full_name is not None:
        payload["full_name"] = full_name
    if email is not None:
        payload["email"] = email
    resp = api_client.create_resident(payload, headers or ADMIN)
    if resp.status_code != 201:
        _setup_fail("create_resident", resp)
    return validate_success(resp, 201)


def create_lease(unit_id, resident_id, term_start_date=STD_TERM_START,
                 term_months=STD_TERM_MONTHS, monthly_rent_cents=STD_RENT_CENTS,
                 headers=None):
    payload = create_lease_payload(
        unit_id, resident_id,
        term_start_date=term_start_date, term_months=term_months,
        monthly_rent_cents=monthly_rent_cents,
    )
    resp = api_client.create_lease(payload, headers or PM1)
    if resp.status_code != 201:
        _setup_fail("create_lease", resp)
    return validate_success(resp, 201)


# ---------------------------------------------------------------------------
# Tier 2: base hierarchy — policy + property + unit + resident + lease
# ---------------------------------------------------------------------------

def setup_lease_scenario(band_min=12, band_max=12, market_rent_cents=210000,
                         monthly_rent_cents=STD_RENT_CENTS,
                         term_start_date=STD_TERM_START, term_months=STD_TERM_MONTHS,
                         property_name="Court", unit_number="101",
                         resident_name="Res Ident", resident_email="res.ident@x.com"):
    """CA-OAK policy -> property (staggering band) -> unit -> resident -> lease.

    Returns {"policy", "property", "unit", "resident", "lease"} data dicts.
    """
    policy = create_policy()
    prop = create_property(
        policy["id"], min_term_months=band_min, max_term_months=band_max, name=property_name,
    )
    unit = create_unit(prop["id"], market_rent_cents=market_rent_cents, unit_number=unit_number)
    resident = create_resident(full_name=resident_name, email=resident_email)
    lease = create_lease(
        unit["id"], resident["id"],
        term_start_date=term_start_date, term_months=term_months,
        monthly_rent_cents=monthly_rent_cents,
    )
    return {"policy": policy, "property": prop, "unit": unit,
            "resident": resident, "lease": lease}


# ---------------------------------------------------------------------------
# Tier 3: offer lifecycle shortcuts
# ---------------------------------------------------------------------------

def get_lease(lease_id, headers=None):
    return validate_success(api_client.get_lease(lease_id, headers or PM1), 200)


def get_offer(offer_id, headers=None):
    return validate_success(api_client.get_renewal_offer(offer_id, headers or PM1), 200)


def get_document(document_id, headers=None):
    return validate_success(api_client.get_renewal_document(document_id, headers or PM1), 200)


def get_notice(notice_id, headers=None):
    return validate_success(api_client.get_non_renewal_notice(notice_id, headers or PM1), 200)


def get_concession(concession_id, headers=None):
    return validate_success(api_client.get_concession_approval(concession_id, headers or PM1), 200)


def create_offer_for_lease(lease, rate_strategy="CONSERVATIVE", headers=None):
    """Create a DRAFT offer against the lease with a fresh OCC version.

    Re-reads the lease so the caller never threads a stale version.
    `rate_strategy=None` omits the field (exercises the BALANCED default).
    """
    fresh = get_lease(lease["id"])
    payload = create_offer_payload(fresh["version"])
    if rate_strategy is not None:
        payload["rate_strategy"] = rate_strategy
    resp = api_client.create_renewal_offer(lease["id"], payload, headers or LA1)
    if resp.status_code != 201:
        _setup_fail("create_offer_for_lease", resp)
    return validate_success(resp, 201)


def issue_offer(offer_id, headers=None):
    resp = api_client.issue_renewal_offer(offer_id, headers or LA1)
    if resp.status_code != 200:
        _setup_fail("issue_offer", resp)
    return validate_success(resp, 200)


def resident_accept(offer_id, resident_id):
    resp = api_client.respond_to_offer(
        offer_id, respond_accept_payload(), make_resident_headers(resident_id))
    if resp.status_code != 200:
        _setup_fail("resident_accept", resp)
    return validate_success(resp, 200)


def resident_counter(offer_id, resident_id, counter_rent_cents, counter_term_months=None):
    payload = respond_counter_payload(counter_rent_cents)
    if counter_term_months is not None:
        payload["counter_term_months"] = counter_term_months
    resp = api_client.respond_to_offer(
        offer_id, payload, make_resident_headers(resident_id))
    if resp.status_code != 200:
        _setup_fail("resident_counter", resp)
    return validate_success(resp, 200)


def get_document_for_offer(offer_id, headers=None):
    """The single RenewalDocument chained to an offer (PRD §3.7: at most one)."""
    resp = api_client.list_renewal_documents(headers or PM1, params={"offer_id": offer_id})
    if resp.status_code != 200:
        _setup_fail("get_document_for_offer", resp)
    from prd_bench_local_runner.testing import validate_paginated
    docs, _meta = validate_paginated(resp)
    assert len(docs) == 1, f"expected exactly one document for offer {offer_id}, got {len(docs)}"
    return docs[0]


def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    if resp.status_code != 200:
        _setup_fail("set_clock", resp)
    return validate_success(resp, 200)


def setup_issued_offer_scenario(rate_strategy="CONSERVATIVE", **scenario_kwargs):
    """Base hierarchy + a DRAFT offer + issued. Adds "offer" to the dict."""
    sc = setup_lease_scenario(**scenario_kwargs)
    offer = create_offer_for_lease(sc["lease"], rate_strategy=rate_strategy)
    offer = issue_offer(offer["id"])
    sc["offer"] = offer
    return sc


def setup_countered_offer_scenario(counter_rent_cents=205000, rate_strategy="BALANCED",
                                   band_min=18, band_max=18, market_rent_cents=220000,
                                   **scenario_kwargs):
    """Base hierarchy (band [18,18], market 220000) + offer issued + resident
    counter. Offer ends COUNTERED. Adds "offer"."""
    sc = setup_lease_scenario(
        band_min=band_min, band_max=band_max, market_rent_cents=market_rent_cents,
        **scenario_kwargs,
    )
    offer = create_offer_for_lease(sc["lease"], rate_strategy=rate_strategy)
    offer = issue_offer(offer["id"])
    offer = resident_counter(offer["id"], sc["resident"]["id"], counter_rent_cents)
    sc["offer"] = offer
    return sc


def setup_accepted_offer_scenario(rate_strategy="CONSERVATIVE", **scenario_kwargs):
    """Base hierarchy + offer issued + resident ACCEPT. Adds "offer" (ACCEPTED)
    and "document" (GENERATED)."""
    sc = setup_issued_offer_scenario(rate_strategy=rate_strategy, **scenario_kwargs)
    offer = resident_accept(sc["offer"]["id"], sc["resident"]["id"])
    sc["offer"] = offer
    sc["document"] = get_document_for_offer(offer["id"])
    return sc


def setup_executed_renewal_scenario(rate_strategy="CONSERVATIVE", **scenario_kwargs):
    """Full renewal loop: issue -> accept -> resident sign -> countersign.
    Adds "offer" (EXECUTED) and "document" (COUNTERSIGNED)."""
    sc = setup_accepted_offer_scenario(rate_strategy=rate_strategy, **scenario_kwargs)
    resident_headers = make_resident_headers(sc["resident"]["id"])
    resp = api_client.sign_document_resident(sc["document"]["id"], resident_headers)
    if resp.status_code != 200:
        _setup_fail("sign_document_resident", resp)
    resp = api_client.countersign_document(sc["document"]["id"], PM1)
    if resp.status_code != 200:
        _setup_fail("countersign_document", resp)
    sc["document"] = validate_success(resp, 200)
    sc["offer"] = get_offer(sc["offer"]["id"])
    sc["lease"] = get_lease(sc["lease"]["id"])
    return sc


# ---------------------------------------------------------------------------
# Tier 4: notices
# ---------------------------------------------------------------------------

def create_notice(lease_id, cause_type, effective_date, creator_headers=None,
                  evidence_ref=None):
    payload = create_notice_payload(cause_type, effective_date)
    if evidence_ref is not None:
        payload["evidence_ref"] = evidence_ref
    resp = api_client.create_non_renewal_notice(lease_id, payload, creator_headers or LA1)
    if resp.status_code != 201:
        _setup_fail("create_notice", resp)
    return validate_success(resp, 201)


def serve_notice(notice_id, server_headers=None):
    resp = api_client.serve_notice(notice_id, server_headers or PM1)
    if resp.status_code != 200:
        _setup_fail("serve_notice", resp)
    return validate_success(resp, 200)
