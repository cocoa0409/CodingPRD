"""Supplier registration, verification, and blacklist.

Covers PRD §3.3 and §2.4 common-fields invariants.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    assert_supplier,
    blacklist_supplier,
    create_supplier_payload,
    make_supplier_headers,
    register_supplier,
    register_verified_supplier,
    set_credit_score,
    unique_legal_name,
    unique_tax_id,
    validate_error,
    validate_success,
    verify_supplier,
)


def test_register_supplier_starts_pending_with_default_credit_score(api, officer_headers):
    """PRD §3.3: "A newly created supplier starts in PENDING
    registration with a default credit_score of 600 ... and a
    blacklist_until of null."

    Claim: brand-new Supplier has registration_status=PENDING,
    credit_score=600, blacklist_until=null.
    """
    payload = create_supplier_payload(
        legal_name=unique_legal_name(), tax_id=unique_tax_id(),
    )
    res = api.create_supplier(payload, officer_headers)
    data = validate_success(res, 201)
    assert_supplier(data)
    assert data["registration_status"] == "PENDING"
    assert data["credit_score"] == 600
    assert data.get("blacklist_until") is None


def test_register_supplier_legal_name_must_be_unique(api, officer_headers):
    """PRD §3.3: "providing a legal_name (non-empty and unique across
    all suppliers)."

    Claim: a second registration with the same legal_name is rejected.
    PRD prose names uniqueness without naming a specific error_id; we
    therefore assert HTTP-level rejection only (4xx).
    """
    name = unique_legal_name()
    api.create_supplier(
        create_supplier_payload(legal_name=name, tax_id=unique_tax_id()),
        officer_headers,
    )
    res = api.create_supplier(
        create_supplier_payload(legal_name=name, tax_id=unique_tax_id()),
        officer_headers,
    )
    assert 400 <= res.status_code < 500, (
        f"duplicate legal_name should be a client error, "
        f"got {res.status_code}"
    )


def test_register_supplier_tax_id_must_be_unique(api, officer_headers):
    """PRD §3.3: "and a tax_id (non-empty and unique)."

    Claim: a second registration with the same tax_id is rejected.
    """
    tid = unique_tax_id()
    api.create_supplier(
        create_supplier_payload(legal_name=unique_legal_name(), tax_id=tid),
        officer_headers,
    )
    res = api.create_supplier(
        create_supplier_payload(legal_name=unique_legal_name(), tax_id=tid),
        officer_headers,
    )
    assert 400 <= res.status_code < 500


def test_verify_supplier_pending_to_verified(api, officer_headers):
    """PRD §3.3: "The procurement officer verifies the supplier by
    transitioning PENDING → VERIFIED; only a verified supplier can
    subsequently bid."
    """
    sup = register_supplier()
    res = api.verify_supplier(sup["id"], officer_headers)
    data = validate_success(res, 200)
    assert data["registration_status"] == "VERIFIED"


def test_blacklist_supplier_sets_status_and_until(api, regulator_headers):
    """PRD §3.3: "A regulator may at any point blacklist the supplier —
    transitioning the registration to BLACKLISTED — supplying a
    blacklist_until UTC timestamp until which the supplier is treated
    as blacklisted."
    """
    sup = register_verified_supplier()
    until = "2030-01-01T00:00:00.000Z"
    res = api.blacklist_supplier(
        sup["id"], {"blacklist_until": until}, regulator_headers,
    )
    data = validate_success(res, 200)
    assert data["registration_status"] == "BLACKLISTED"
    assert data["blacklist_until"] == until


def test_credit_score_event_updates_supplier(api, officer_headers):
    """PRD §2.4: "such events may update a supplier's credit_score."
    PRD §3.3: "the credit score is later mirrored from an external
    credit-information system into the same field."

    Claim: emitting a credit-info event updates Supplier.credit_score.
    """
    sup = register_verified_supplier()
    advance_clock("2026-01-01T00:00:00.000Z")
    set_credit_score(sup["id"], 750)
    res = api.get_supplier(sup["id"], officer_headers)
    data = validate_success(res)
    assert data["credit_score"] == 750


def test_supplier_response_carries_common_fields(api, officer_headers):
    """PRD §2.4: "Every persisted entity carries a server-minted id ...
    Entities marked as carrying common fields additionally carry
    updated_at ... and version (a non-negative integer that ...
    increments by one on every mutation)."

    Claim: Supplier carries updated_at and version, and version
    increments on the verify mutation.
    """
    sup = register_supplier()
    assert "version" in sup
    assert "updated_at" in sup
    v0 = sup["version"]
    after = verify_supplier(sup["id"])
    assert after["version"] > v0, (
        f"version must increment on mutation; before={v0}, "
        f"after={after['version']}"
    )
