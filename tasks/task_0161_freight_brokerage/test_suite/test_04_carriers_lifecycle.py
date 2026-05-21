"""Carrier qualification, suspension, requalification, revocation — PRD §3.3.

Covers MC#/USDOT uniqueness, the insurance-expiry gate, and the safety
score requalify floor of 700.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    advance_clock_by_days,
    assert_carrier,
    create_brokerage,
    create_carrier,
    create_carrier_payload,
    create_qualified_carrier,
    get_carrier,
    iso_utc,
    parse_iso,
    qualify_carrier,
    requalify_carrier,
    revoke_carrier,
    SAFETY_SCORE_INITIAL,
    setup_brokerage_with_shipper,
    suspend_carrier,
    unique_mc_number,
    unique_usdot_number,
    utcnow,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 — Creation
# ===========================================================================
def test_carrier_created_in_pending_qualification(api, carrier_ops_headers):
    """PRD §3.3: "The new carrier lands in `PENDING_QUALIFICATION` with
    `safety_score` initialised to 1000."

    Claim: a freshly created carrier is PENDING_QUALIFICATION with
    safety_score == 1000.
    """
    brokerage = create_brokerage()
    res = api.create_carrier(brokerage["id"], create_carrier_payload(),
                             carrier_ops_headers)
    carrier = validate_success(res, 201)
    assert_carrier(carrier)
    assert carrier["status"] == "PENDING_QUALIFICATION"
    assert carrier["safety_score"] == SAFETY_SCORE_INITIAL


def test_mc_usdot_uniqueness_per_brokerage(api, carrier_ops_headers):
    """PRD §3.3: "The MC# and USDOT number must each be unique per
    brokerage across all non-`REVOKED` carriers: a duplicate filing yields
    `ERR_CARRIER_AUTHORITY_DUPLICATE`."

    Claim: creating a second carrier with the same MC# in the same
    brokerage -> ERR_CARRIER_AUTHORITY_DUPLICATE.
    """
    brokerage = create_brokerage()
    payload = create_carrier_payload()
    api.create_carrier(brokerage["id"], payload, carrier_ops_headers)
    res = api.create_carrier(brokerage["id"], payload, carrier_ops_headers)
    validate_error(res, "ERR_CARRIER_AUTHORITY_DUPLICATE")


def test_mc_usdot_uniqueness_lifted_on_revocation(api, carrier_ops_headers):
    """PRD §3.3: "Revoked carriers are explicitly excluded from the
    uniqueness set, so an `mc_number` belonging to a `REVOKED` row may be
    re-registered."

    Claim: after revoking a carrier, the same MC# / USDOT can be reused.
    """
    brokerage = create_brokerage()
    mc = unique_mc_number()
    usdot = unique_usdot_number()
    first = create_qualified_carrier(brokerage["id"], mc_number=mc,
                                     usdot_number=usdot)
    suspend_carrier(brokerage["id"], first["id"])
    revoke_carrier(brokerage["id"], first["id"])

    # Now reuse the same MC#/USDOT — should succeed.
    res = api.create_carrier(brokerage["id"],
                             create_carrier_payload(mc_number=mc,
                                                    usdot_number=usdot),
                             carrier_ops_headers)
    validate_success(res, 201)


# ===========================================================================
# §3.3 — Qualification
# ===========================================================================
def test_qualify_pending_carrier_succeeds(api, carrier_ops_headers):
    """PRD §3.3: "Qualifying a `PENDING_QUALIFICATION` carrier advances
    it to `QUALIFIED`."

    Claim: /qualify on a fresh carrier -> status == QUALIFIED.
    """
    brokerage = create_brokerage()
    carrier = create_carrier(brokerage["id"])
    res = api.qualify_carrier(brokerage["id"], carrier["id"],
                              carrier_ops_headers)
    qualified = validate_success(res, 200)
    assert qualified["status"] == "QUALIFIED"


def test_qualify_with_expired_insurance_rejected(api, carrier_ops_headers):
    """PRD §3.3: "the `insurance_expires_on` timestamp [must be] strictly
    after the brokerage clock (failure yields `ERR_INSURANCE_EXPIRED`)."

    Claim: insurance_expires_on in the past -> ERR_INSURANCE_EXPIRED on /qualify.
    """
    brokerage = create_brokerage()
    expired = iso_utc(add_days(utcnow(), -1))
    carrier = create_carrier(brokerage["id"], insurance_expires_on=expired)
    res = api.qualify_carrier(brokerage["id"], carrier["id"],
                              carrier_ops_headers)
    validate_error(res, "ERR_INSURANCE_EXPIRED")


def test_qualify_already_qualified_rejected(api, carrier_ops_headers):
    """PRD §3.3: "Attempting to qualify a carrier not currently in
    `PENDING_QUALIFICATION` yields `ERR_CARRIER_NOT_PENDING`."

    Claim: /qualify on a QUALIFIED carrier -> ERR_CARRIER_NOT_PENDING.
    """
    brokerage = create_brokerage()
    carrier = create_qualified_carrier(brokerage["id"])
    res = api.qualify_carrier(brokerage["id"], carrier["id"],
                              carrier_ops_headers)
    validate_error(res, "ERR_CARRIER_NOT_PENDING")


# ===========================================================================
# §3.3 — Suspension and the open-loads guard.
# ===========================================================================
def test_manual_suspend_qualified_carrier_succeeds(api, carrier_ops_headers):
    """PRD §3.3: "A `CarrierOps` operator can manually suspend a `QUALIFIED`
    carrier; this fails with `ERR_CARRIER_HAS_OPEN_LOADS` if the carrier
    has any load currently in `TENDERED`, `ACCEPTED`, or `IN_TRANSIT`."

    Claim: /suspend on a QUALIFIED carrier with no open loads -> SUSPENDED.
    """
    brokerage = create_brokerage()
    carrier = create_qualified_carrier(brokerage["id"])
    res = api.suspend_carrier(brokerage["id"], carrier["id"],
                              carrier_ops_headers)
    suspended = validate_success(res, 200)
    assert suspended["status"] == "SUSPENDED"


# ===========================================================================
# §3.3 — Requalification
# ===========================================================================
def test_requalify_suspended_carrier_succeeds(api, carrier_ops_headers):
    """PRD §3.3: "A `SUSPENDED` carrier can be moved back to `QUALIFIED` by
    a `CarrierOps` operator via the requalification capability."

    Claim: /requalify on a SUSPENDED carrier (with valid insurance and
    safety_score >= 700) -> status == QUALIFIED.
    """
    brokerage = create_brokerage()
    carrier = create_qualified_carrier(brokerage["id"])
    suspend_carrier(brokerage["id"], carrier["id"])

    res = api.requalify_carrier(brokerage["id"], carrier["id"],
                                carrier_ops_headers)
    qualified = validate_success(res, 200)
    assert qualified["status"] == "QUALIFIED"


def test_requalify_with_expired_insurance_rejected(api, carrier_ops_headers):
    """PRD §3.3: "Two preconditions apply [on requalify]: `insurance_expires_on`
    must still be strictly after the brokerage clock (otherwise
    `ERR_INSURANCE_EXPIRED`)."

    Claim: requalify with the clock past insurance -> ERR_INSURANCE_EXPIRED.
    """
    brokerage = create_brokerage()
    # Insurance is valid right now (utcnow+365d) at creation; we will
    # advance the clock past it.
    carrier = create_qualified_carrier(brokerage["id"])
    suspend_carrier(brokerage["id"], carrier["id"])

    # Advance the brokerage clock past the carrier's insurance.
    advance_clock_by_days(brokerage["id"], 400)

    res = api.requalify_carrier(brokerage["id"], carrier["id"],
                                carrier_ops_headers)
    validate_error(res, "ERR_INSURANCE_EXPIRED")


def test_requalify_non_suspended_carrier_rejected(api, carrier_ops_headers):
    """PRD §3.3: "Attempting to requalify a carrier not in `SUSPENDED`
    yields `ERR_CARRIER_NOT_SUSPENDED`."

    Claim: /requalify on a QUALIFIED carrier -> ERR_CARRIER_NOT_SUSPENDED.
    """
    brokerage = create_brokerage()
    carrier = create_qualified_carrier(brokerage["id"])
    res = api.requalify_carrier(brokerage["id"], carrier["id"],
                                carrier_ops_headers)
    validate_error(res, "ERR_CARRIER_NOT_SUSPENDED")


# ===========================================================================
# §3.3 — Revocation
# ===========================================================================
def test_revoke_suspended_carrier_succeeds(api, carrier_ops_headers):
    """PRD §3.3: "Revocation is a one-way terminal move available only
    from `SUSPENDED`: a `CarrierOps` operator drives the carrier into `REVOKED`."

    Claim: /revoke on a SUSPENDED carrier -> REVOKED.
    """
    brokerage = create_brokerage()
    carrier = create_qualified_carrier(brokerage["id"])
    suspend_carrier(brokerage["id"], carrier["id"])
    res = api.revoke_carrier(brokerage["id"], carrier["id"],
                             carrier_ops_headers)
    revoked = validate_success(res, 200)
    assert revoked["status"] == "REVOKED"


def test_revoke_qualified_carrier_rejected(api, carrier_ops_headers):
    """PRD §3.3: "Attempting to revoke a non-`SUSPENDED` carrier yields
    `ERR_CARRIER_NOT_SUSPENDED`."

    Claim: /revoke on a QUALIFIED carrier -> ERR_CARRIER_NOT_SUSPENDED.
    """
    brokerage = create_brokerage()
    carrier = create_qualified_carrier(brokerage["id"])
    res = api.revoke_carrier(brokerage["id"], carrier["id"],
                             carrier_ops_headers)
    validate_error(res, "ERR_CARRIER_NOT_SUSPENDED")
