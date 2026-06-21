"""Temporal-overlap conflicts (half-open certificates vs closed return periods)
and the remaining validation triggers: uniqueness, interval well-formedness,
the seller-suspension gate, and existence-beats-state priority.

Queue A: resource_temporal_overlap (≥2 tests per instance).
Queue B: validations section.
"""
import pytest

from test_helpers import (
    make_seller_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import NONEXISTENT_UUID_V4
from test_helpers.factories import create_exemption_certificate_payload
from test_helpers.test_users import TEST_USERS, make_preparer_headers

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Queue A — resource_temporal_overlap (certificate, half-open)
# ===========================================================================

def test_certificate_overlapping_window_rejected(api):
    """PRD §3.7: "the system rejects it with `ERR_CERTIFICATE_OVERLAP` if its half-open window from `valid_from` up to but not including `valid_to` intersects the half-open window of any existing `ACTIVE` certificate sharing the same `seller_id`, `jurisdiction_id`, `customer_ref`, and `exempt_category_code`."

    Design: Difficulty/resource_temporal_overlap/certificate_halfopen_overlap_adjacency_allowed
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_certificate(seller["id"], ca["id"], customer_ref="b1",
                          exempt_category_code="TANGIBLE",
                          valid_from="2026-01-01T00:00:00Z", valid_to="2026-07-01T00:00:00Z")
    overlapping = create_exemption_certificate_payload(
        seller["id"], ca["id"], customer_ref="b1", exempt_category_code="TANGIBLE",
        valid_from="2026-06-01T00:00:00Z", valid_to="2026-12-01T00:00:00Z")
    res = api.create_exemption_certificate(overlapping, make_seller_headers(seller["id"]))
    validate_error(res, "ERR_CERTIFICATE_OVERLAP", expected_status=409)


def test_certificate_adjacent_window_allowed(api):
    """PRD §3.7: "Because the interval is half-open, touching endpoints do not collide: an existing certificate whose `valid_to` exactly equals the new certificate's `valid_from` is allowed."

    Design: Difficulty/resource_temporal_overlap/certificate_halfopen_overlap_adjacency_allowed
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_certificate(seller["id"], ca["id"], customer_ref="b1",
                          exempt_category_code="TANGIBLE",
                          valid_from="2026-01-01T00:00:00Z", valid_to="2026-07-01T00:00:00Z")
    adjacent = create_exemption_certificate_payload(
        seller["id"], ca["id"], customer_ref="b1", exempt_category_code="TANGIBLE",
        valid_from="2026-07-01T00:00:00Z", valid_to="2026-12-01T00:00:00Z")
    res = api.create_exemption_certificate(adjacent, make_seller_headers(seller["id"]))
    created = validate_success(res, 201)
    assert created["status"] == "ACTIVE", f"adjacent certificate should be created ACTIVE, got {created['status']}"


# ===========================================================================
# Queue A — resource_temporal_overlap (tax return, closed)
# ===========================================================================

def test_return_touching_period_rejected_adjacency_forbidden(api):
    """PRD §3.9: "Because this interval is treated as closed and adjacency is forbidden, shared endpoints do collide: an existing return whose `period_end` exactly equals the new return's `period_start` is rejected."

    Design: Difficulty/resource_temporal_overlap/return_closed_overlap_adjacency_forbidden
    """
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_draft_return(seller["id"], ca["id"],
                           period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z")
    res = api.create_tax_return(
        {"seller_id": seller["id"], "jurisdiction_id": ca["id"],
         "period_start": "2026-03-01T00:00:00Z", "period_end": "2026-04-01T00:00:00Z"},
        make_preparer_headers())
    validate_error(res, "ERR_RETURN_PERIOD_OVERLAP", expected_status=409)


def test_return_overlapping_period_rejected(api):
    """PRD §3.9: "A new return is rejected with `ERR_RETURN_PERIOD_OVERLAP` if its closed period — from `period_start` through `period_end` inclusive — intersects or touches the closed period of any existing return for the same `seller_id` and `jurisdiction_id` that is not `REJECTED` (that is, any return whose `status` is `DRAFT`, `ACCEPTED`, `FILED`, or `REMITTED`)."

    Design: Difficulty/resource_temporal_overlap/return_closed_overlap_adjacency_forbidden
    """
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_draft_return(seller["id"], ca["id"],
                           period_start="2026-02-01T00:00:00Z", period_end="2026-04-01T00:00:00Z")
    res = api.create_tax_return(
        {"seller_id": seller["id"], "jurisdiction_id": ca["id"],
         "period_start": "2026-03-01T00:00:00Z", "period_end": "2026-05-01T00:00:00Z"},
        make_preparer_headers())
    validate_error(res, "ERR_RETURN_PERIOD_OVERLAP", expected_status=409)


# ===========================================================================
# Queue B — validations section
# ===========================================================================

def test_duplicate_state_code_returns_duplicate_resource(api):
    """PRD §3.1: "Attempting to create a second jurisdiction with an already-used `state_code` is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_state_code_returns_duplicate_resource
    """
    fx.create_ca_jurisdiction()
    res = api.create_tax_jurisdiction(
        {"state_code": "CA", "sourcing_rule": "ORIGIN", "state_rate": 0.06,
         "local_rate": 0.00, "reduced_rate": 0.00,
         "economic_nexus_sales_threshold": 200000.00, "economic_nexus_txn_threshold": 0},
        ADMIN)
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


def test_duplicate_nexus_profile_returns_duplicate_resource(api):
    """PRD §3.2: "The pair must be unique per seller and state; a second profile for the same `seller_id` and `jurisdiction_id` is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_nexus_profile_returns_duplicate_resource
    """
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_nexus_profile(seller["id"], ca["id"])
    res = api.create_nexus_profile(
        {"seller_id": seller["id"], "jurisdiction_id": ca["id"]},
        make_seller_headers(seller["id"]))
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


def test_certificate_valid_to_before_valid_from_returns_invalid_interval(api):
    """PRD §3.7: "The validity window is half-open and must be well-formed: `valid_to` must be strictly after `valid_from`, and a window that is not is rejected with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/certificate_valid_to_before_valid_from_returns_invalid_interval
    """
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    payload = create_exemption_certificate_payload(
        seller["id"], ca["id"], customer_ref="b1", exempt_category_code="TANGIBLE",
        valid_from="2026-07-01T00:00:00Z", valid_to="2026-01-01T00:00:00Z")
    res = api.create_exemption_certificate(payload, make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_settle_suspended_seller_returns_seller_suspended(api):
    """PRD §3.4: "Settlement is also blocked for a suspended seller: if the selling `Seller` has `status` of `SUSPENDED`, the attempt is rejected with `ERR_SELLER_SUSPENDED`."

    Design: Corner/validations/settle_suspended_seller_returns_seller_suspended
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    txn = fx.create_transaction_with_lines(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 10.00}],
        customer_ref="b1", customer_exempt_requested=False)
    validate_success(api.suspend_seller(seller["id"], ADMIN), 200)
    res = api.settle_transaction(txn["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_SELLER_SUSPENDED", expected_status=409)


def test_existence_beats_state_on_unknown_transaction_settle(api):
    """PRD §2.9: "then existence of any path-referenced resource (`ERR_NOT_FOUND`), then existence of any body-referenced foreign key such as `jurisdiction_id`, `facilitator_id`, `transaction_id`, `tax_return_id`, or `seller_id` (`ERR_REFERENCE_NOT_FOUND`), then well-formedness of the request body including required fields, types, enum membership, and numeric bounds (`ERR_INVALID_REQUEST`), then uniqueness constraints (`ERR_DUPLICATE_RESOURCE`), then interval well-formedness (`ERR_INVALID_INTERVAL`), then the temporal-overlap checks for certificates and return periods (`ERR_CERTIFICATE_OVERLAP` and `ERR_RETURN_PERIOD_OVERLAP`), and finally the state and business-rule checks particular to each operation."

    Design: Corner/validations/priority_existence_beats_state_on_unknown_transaction_settle
    """
    seller = fx.create_seller(origin_state_code="CA")
    res = api.settle_transaction(NONEXISTENT_UUID_V4, make_seller_headers(seller["id"]))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
