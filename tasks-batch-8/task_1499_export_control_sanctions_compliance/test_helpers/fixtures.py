"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient) so a broken precondition raises a
clear "Setup step failed" error instead of a confusing assertion failure.

Standard segregation-of-duties pairing used throughout: the analyst-1 /
manager-1 user ids from TEST_USERS are always distinct, so submit/review
cycles satisfy the PRD's SoD rule without extra plumbing.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_access_grant_payload,
    create_classification_payload,
    create_license_payload,
    create_order_payload,
    create_party_payload,
    create_product_payload,
    create_screening_list_entry_payload,
    create_shipment_payload,
    create_tcp_payload,
    create_violation_payload,
)
from .test_users import TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
ANALYST2 = TEST_USERS["analyst2_headers"]
MANAGER = TEST_USERS["manager_headers"]
MANAGER2 = TEST_USERS["manager2_headers"]
OPS = TEST_USERS["ops_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def to_iso_z(dt: datetime) -> str:
    """Format a datetime back to ISO 8601 UTC for the clock endpoint."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Tier 1/2: single entities and the classification lifecycle ──────────────

def create_product(sku="P-1000", name="Widget", controlled_content_pct=0, unit_value_cents=1000):
    """Create a product as the analyst. Returns the Product (UNCLASSIFIED)."""
    res = api_client.create_product(
        create_product_payload(
            sku=sku, name=name,
            controlled_content_pct=controlled_content_pct,
            unit_value_cents=unit_value_cents,
        ),
        ANALYST,
    )
    return get_success_data(res)


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ANALYST))


def create_draft_classification(product, jurisdiction="EAR", classification_code="EAR99",
                                determination_basis="SELF_CLASSIFICATION"):
    """Draft a classification against the product's current version. Returns it (DRAFT)."""
    res = api_client.create_classification(
        create_classification_payload(
            product["id"], product["version"],
            jurisdiction=jurisdiction,
            classification_code=classification_code,
            determination_basis=determination_basis,
        ),
        ANALYST,
    )
    return get_success_data(res)


def submit_classification(classification_id, headers=None):
    return get_success_data(api_client.submit_classification(classification_id, headers or ANALYST))


def review_classification(classification_id, decision="APPROVE", headers=None):
    return get_success_data(
        api_client.review_classification(classification_id, {"decision": decision}, headers or MANAGER)
    )


def create_classified_product(sku="P-1000", name="Widget", controlled_content_pct=0,
                              unit_value_cents=1000, jurisdiction="EAR",
                              classification_code="EAR99",
                              determination_basis="SELF_CLASSIFICATION"):
    """Product + one ACTIVE classification. Returns (product_refetched, classification)."""
    product = create_product(sku=sku, name=name,
                             controlled_content_pct=controlled_content_pct,
                             unit_value_cents=unit_value_cents)
    classification = create_draft_classification(
        product, jurisdiction=jurisdiction, classification_code=classification_code,
        determination_basis=determination_basis,
    )
    submit_classification(classification["id"])
    classification = review_classification(classification["id"], "APPROVE")
    return get_product(product["id"]), classification


def create_party(legal_name="Clean Buyer Ltd", country_code="GBR", city="London",
                 party_type="CUSTOMER", is_foreign_national=None, headers=None):
    """Create a party. is_foreign_national omitted unless explicitly given."""
    res = api_client.create_party(
        create_party_payload(
            is_foreign_national=is_foreign_national,
            legal_name=legal_name, country_code=country_code,
            city=city, party_type=party_type,
        ),
        headers or OPS,
    )
    return get_success_data(res)


def create_foreign_national(legal_name="Chen Wei", country_code="CHN", city="Shanghai"):
    """A foreign-national person (deemed-export scope), created by the analyst."""
    return create_party(legal_name=legal_name, country_code=country_code, city=city,
                        party_type="FOREIGN_NATIONAL", is_foreign_national=True,
                        headers=ANALYST)


def get_party(party_id, headers=None):
    return get_success_data(api_client.get_party(party_id, headers or MANAGER))


def create_entry(list_source="DENIED_PERSONS", match_name="Listed Entity",
                 country_code="DEU", severity="RESTRICTED"):
    """Create a screening list entry (born ACTIVE). Returns the entry."""
    res = api_client.create_screening_list_entry(
        create_screening_list_entry_payload(
            list_source=list_source, match_name=match_name,
            country_code=country_code, severity=severity,
        ),
        DIRECTOR,
    )
    return get_success_data(res)


def screen_party(party_id, headers=None):
    """Manual FUZZY screening. Returns the created ScreeningResult."""
    return get_success_data(api_client.screen_party(party_id, headers or OPS))


def resolve_screening_result(result_id, resolution="FALSE_POSITIVE", headers=None):
    return get_success_data(
        api_client.resolve_screening_result(result_id, {"resolution": resolution},
                                            headers or MANAGER)
    )


def block_party_with_confirmed_match(party):
    """Drive a party to BLOCKED: exact-name PROHIBITED entry -> manual screen
    (POTENTIAL_MATCH, FUZZY score 1.00 >= 0.85) -> resolve CONFIRMED_MATCH.
    Returns the CONFIRMED_MATCH ScreeningResult."""
    create_entry(list_source="SDN", match_name=party["legal_name"],
                 country_code=party["country_code"], severity="PROHIBITED")
    result = screen_party(party["id"])
    return resolve_screening_result(result["id"], "CONFIRMED_MATCH")


# ─── Orders ──────────────────────────────────────────────────────────────────

def create_order(product_id, party_id, destination_country="FRA", end_use="CIVILIAN", quantity=1):
    res = api_client.create_order(
        create_order_payload(
            product_id, party_id,
            destination_country=destination_country, end_use=end_use, quantity=quantity,
        ),
        OPS,
    )
    return get_success_data(res)


def get_order(order_id, headers=None):
    return get_success_data(api_client.get_order(order_id, headers or OPS))


def submit_order(order_id):
    return get_success_data(api_client.submit_order(order_id, OPS))


def setup_cleared_order(party_name="Clean Buyer Ltd", party_country="GBR", party_city="London",
                        destination_country="FRA", end_use="CIVILIAN", quantity=1,
                        controlled_content_pct=0, unit_value_cents=1000,
                        classification_code="EAR99", jurisdiction="EAR"):
    """Classified product + clean party + submitted order landing CLEARED.
    With EAR99/CIVILIAN the determination is NOT_REQUIRED; with a real ECCN and
    pct above the destination's de minimis threshold it is LICENSE_REQUIRED.
    Returns dict(product, classification, party, order)."""
    product, classification = create_classified_product(
        controlled_content_pct=controlled_content_pct,
        unit_value_cents=unit_value_cents,
        classification_code=classification_code,
        jurisdiction=jurisdiction,
    )
    party = create_party(legal_name=party_name, country_code=party_country, city=party_city)
    order = create_order(product["id"], party["id"],
                         destination_country=destination_country,
                         end_use=end_use, quantity=quantity)
    order = submit_order(order["id"])
    assert order["status"] == "CLEARED", f"order should be CLEARED, got {order['status']}"
    return {"product": product, "classification": classification,
            "party": party, "order": order}


def setup_released_not_required_order(party_name="Clean Buyer Ltd", party_country="GBR",
                                      party_city="London", destination_country="FRA",
                                      quantity=2, unit_value_cents=1000):
    """EAR99/CIVILIAN order walked to RELEASED. Returns dict(product, party, order)."""
    ctx = setup_cleared_order(
        party_name=party_name, party_country=party_country, party_city=party_city,
        destination_country=destination_country, end_use="CIVILIAN", quantity=quantity,
        controlled_content_pct=0, unit_value_cents=unit_value_cents,
        classification_code="EAR99",
    )
    order = get_success_data(api_client.release_order(ctx["order"]["id"], OPS))
    assert order["status"] == "RELEASED", f"order should be RELEASED, got {order['status']}"
    ctx["order"] = order
    return ctx


# ─── Licenses ────────────────────────────────────────────────────────────────

def create_draft_license(product_id, approved_value_cents=100000, approved_quantity=100,
                         valid_from="2026-07-01", valid_until="2026-12-31",
                         conditions=None, issuing_authority="BIS", headers=None):
    res = api_client.create_license(
        create_license_payload(
            product_id, conditions=conditions,
            issuing_authority=issuing_authority,
            approved_value_cents=approved_value_cents,
            approved_quantity=approved_quantity,
            valid_from=valid_from, valid_until=valid_until,
        ),
        headers or ANALYST,
    )
    return get_success_data(res)


def submit_license(license_id, headers=None):
    return get_success_data(api_client.submit_license(license_id, headers or ANALYST))


def review_license(license_id, decision="APPROVE", headers=None):
    return get_success_data(
        api_client.review_license(license_id, {"decision": decision}, headers or MANAGER)
    )


def create_approved_license(product_id, approved_value_cents=100000, approved_quantity=100,
                            valid_from="2026-07-01", valid_until="2026-12-31",
                            conditions=None):
    """License walked DRAFT -> SUBMITTED -> APPROVED (analyst-1 submits, manager-1
    approves). Returns the APPROVED license."""
    lic = create_draft_license(
        product_id, approved_value_cents=approved_value_cents,
        approved_quantity=approved_quantity, valid_from=valid_from,
        valid_until=valid_until, conditions=conditions,
    )
    submit_license(lic["id"])
    lic = review_license(lic["id"], "APPROVE")
    assert lic["status"] == "APPROVED", f"license should be APPROVED, got {lic['status']}"
    return lic


def get_license(license_id, headers=None):
    return get_success_data(api_client.get_license(license_id, headers or MANAGER))


def setup_licensed_order(product_pct=50, unit_value_cents=1000, classification_code="5A002",
                         destination_country="FRA", end_use="DUAL_USE", order_quantity=5,
                         license_value=100000, license_quantity=100, conditions=None,
                         party_name="Clean Buyer Ltd", party_country="GBR", party_city="London",
                         valid_from="2026-07-01", valid_until="2026-12-31"):
    """Full licensed pipeline: CLASSIFIED ECCN product + APPROVED license + clean
    party + order submitted (LICENSE_REQUIRED -> CLEARED) -> license attached
    (LICENSED). Returns dict(product, classification, license, party, order)."""
    ctx = setup_cleared_order(
        party_name=party_name, party_country=party_country, party_city=party_city,
        destination_country=destination_country, end_use=end_use, quantity=order_quantity,
        controlled_content_pct=product_pct, unit_value_cents=unit_value_cents,
        classification_code=classification_code,
    )
    assert ctx["order"]["determination"] == "LICENSE_REQUIRED", (
        f"order should be LICENSE_REQUIRED, got {ctx['order']['determination']}"
    )
    lic = create_approved_license(
        ctx["product"]["id"], approved_value_cents=license_value,
        approved_quantity=license_quantity, valid_from=valid_from,
        valid_until=valid_until, conditions=conditions,
    )
    order = get_success_data(
        api_client.attach_license_to_order(ctx["order"]["id"], {"license_id": lic["id"]}, OPS)
    )
    assert order["status"] == "LICENSED", f"order should be LICENSED, got {order['status']}"
    ctx["license"] = lic
    ctx["order"] = order
    return ctx


def setup_released_licensed_order(**kwargs):
    """Licensed pipeline plus order release (LICENSED -> RELEASED)."""
    ctx = setup_licensed_order(**kwargs)
    order = get_success_data(api_client.release_order(ctx["order"]["id"], OPS))
    assert order["status"] == "RELEASED", f"order should be RELEASED, got {order['status']}"
    ctx["order"] = order
    return ctx


# ─── Shipments ───────────────────────────────────────────────────────────────

def create_shipment(order_id, quantity=1, planned_ship_date="2026-08-10"):
    res = api_client.create_shipment(
        create_shipment_payload(order_id, quantity=quantity,
                                planned_ship_date=planned_ship_date),
        OPS,
    )
    return get_success_data(res)


def get_shipment(shipment_id, headers=None):
    return get_success_data(api_client.get_shipment(shipment_id, headers or OPS))


def screen_shipment(shipment_id):
    """SHIPMENT-context (FUZZY) screening. Returns the created ScreeningResult."""
    return get_success_data(api_client.screen_shipment(shipment_id, OPS))


def create_screened_shipment(order_id, quantity=1, planned_ship_date="2026-08-10"):
    """Shipment created and screened to SCREENED (clean party). Returns it."""
    shipment = create_shipment(order_id, quantity, planned_ship_date)
    screen_shipment(shipment["id"])
    shipment = get_shipment(shipment["id"])
    assert shipment["status"] == "SCREENED", (
        f"shipment should be SCREENED, got {shipment['status']}"
    )
    return shipment


def release_shipment(shipment_id):
    return get_success_data(api_client.release_shipment(shipment_id, OPS))


def create_released_shipment(order_id, quantity=1, planned_ship_date="2026-08-10"):
    """Shipment walked PLANNED -> SCREENED -> RELEASED. Returns it."""
    shipment = create_screened_shipment(order_id, quantity, planned_ship_date)
    return release_shipment(shipment["id"])


# ─── TCPs and access grants ──────────────────────────────────────────────────

def create_tcp(product_id, name="TCP-1", enclave_id="LAB-1", segregation_level="LEVEL_1",
               effective_from="2026-01-01", effective_to="2027-01-01"):
    res = api_client.create_tcp(
        create_tcp_payload(
            product_id, name=name, enclave_id=enclave_id,
            segregation_level=segregation_level,
            effective_from=effective_from, effective_to=effective_to,
        ),
        ANALYST,
    )
    return get_success_data(res)


def set_tcp_status(tcp_id, to):
    return get_success_data(api_client.set_tcp_status(tcp_id, {"to": to}, ANALYST))


def setup_active_tcp(enclave_id="LAB-1", product_pct=0, classification_code="EAR99",
                     unit_value_cents=1000, effective_from="2026-01-01",
                     effective_to="2027-01-01"):
    """CLASSIFIED product + TCP activated on `enclave_id`. Returns (product, tcp)."""
    product, _ = create_classified_product(
        controlled_content_pct=product_pct, unit_value_cents=unit_value_cents,
        classification_code=classification_code,
    )
    tcp = create_tcp(product["id"], enclave_id=enclave_id,
                     effective_from=effective_from, effective_to=effective_to)
    tcp = set_tcp_status(tcp["id"], "ACTIVE")
    assert tcp["status"] == "ACTIVE", f"tcp should be ACTIVE, got {tcp['status']}"
    return product, tcp


def create_access_grant(tcp_id, party_id, start_date="2026-08-01", end_date="2026-12-01",
                        headers=None):
    """Create a REQUESTED grant (requested_by anchored to the caller)."""
    res = api_client.create_access_grant(
        create_access_grant_payload(tcp_id, party_id, start_date=start_date, end_date=end_date),
        headers or ANALYST,
    )
    return get_success_data(res)


def get_access_grant(grant_id, headers=None):
    return get_success_data(api_client.get_access_grant(grant_id, headers or MANAGER))


def review_access_grant(grant_id, decision="APPROVE", headers=None):
    return get_success_data(
        api_client.review_access_grant(grant_id, {"decision": decision}, headers or MANAGER)
    )


def create_approved_grant(tcp_id, party_id, start_date="2026-08-01", end_date="2026-12-01"):
    """Grant requested by analyst-1 and approved by manager-1. Returns APPROVED grant."""
    grant = create_access_grant(tcp_id, party_id, start_date=start_date, end_date=end_date)
    grant = review_access_grant(grant["id"], "APPROVE")
    assert grant["status"] == "APPROVED", f"grant should be APPROVED, got {grant['status']}"
    return grant


def activate_grant(grant_id, headers=None):
    return get_success_data(api_client.activate_access_grant(grant_id, headers or MANAGER))


def create_active_grant(tcp_id, party_id, start_date="2026-08-01", end_date="2026-09-01"):
    """Grant walked REQUESTED -> APPROVED -> ACTIVE. Returns the ACTIVE grant."""
    grant = create_approved_grant(tcp_id, party_id, start_date=start_date, end_date=end_date)
    grant = activate_grant(grant["id"])
    assert grant["status"] == "ACTIVE", f"grant should be ACTIVE, got {grant['status']}"
    return grant


def setup_tcp_with_fn_party(enclave_id="LAB-1"):
    """ACTIVE TCP + a foreign-national party with clean posture.
    Returns (product, tcp, party)."""
    product, tcp = setup_active_tcp(enclave_id=enclave_id)
    party = create_foreign_national()
    return product, tcp, party


# ─── Violations ──────────────────────────────────────────────────────────────

def create_violation(source_type="OTHER", source_id="n/a", severity="MINOR",
                     description="Suspected compliance breach", headers=None):
    res = api_client.create_violation(
        create_violation_payload(source_type=source_type, source_id=source_id,
                                 severity=severity, description=description),
        headers or ANALYST,
    )
    return get_success_data(res)


def advance_violation(violation_id, event, headers=None):
    return get_success_data(
        api_client.advance_violation(violation_id, {"event": event}, headers or MANAGER)
    )


def get_violation(violation_id, headers=None):
    return get_success_data(api_client.get_violation(violation_id, headers or MANAGER))


# ─── Audit records and the logical clock ─────────────────────────────────────

def list_audit_records(headers=None, **params):
    """Returns (rows, meta) from the audit record listing."""
    return validate_paginated(api_client.list_audit_records(headers or DIRECTOR, params=params))


def audit_records_for(entity_type, entity_id, event_type=None, headers=None):
    """All audit records for one subject entity, optionally one event_type."""
    params = {"entity_type": entity_type, "entity_id": entity_id}
    if event_type is not None:
        params["event_type"] = event_type
    rows, meta = list_audit_records(headers=headers, **params)
    assert meta["total_count"] == len(rows) or meta["has_more"] is False
    return rows


def set_clock(to_iso8601, headers=None):
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, headers or DIRECTOR)
    )


def purge_audit_records(headers=None):
    return get_success_data(api_client.purge_audit_records(headers or DIRECTOR))
