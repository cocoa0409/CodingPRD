"""Practitioner recommendations: half-open interval overlap vs touching,
terminal-state revoke guard, expiry materialization, and filtered listing.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    make_practitioner_headers,
    new_customer, new_practitioner, new_product, new_recommendation,
    create_recommendation_payload, set_clock, run_expiry_sweep,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def test_overlapping_recommendation_interval_rejected(api):
    """PRD §3.4: "A new recommendation's interval may not overlap the interval of
    any existing `ISSUED` recommendation for the same customer-and-product pair;
    because the interval is half-open, two intervals that merely touch at an
    endpoint do not overlap and are allowed, but any genuine overlap is rejected
    with `ERR_RECOMMENDATION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/recommendation_interval_overlap
    """
    cust = new_customer(email="c13@x.com", full_name="Cust Thirteen")
    prac = new_practitioner(full_name="Dr Bee", license_number="LIC-2")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True)
    set_clock("2026-07-01T00:00:00Z")
    new_recommendation(prac["id"], cust["id"], prod["id"],
                       expires_at="2026-12-31T00:00:00Z", max_units=5)
    res = api.create_recommendation(
        create_recommendation_payload(cust["id"], prod["id"],
                                      expires_at="2026-10-01T00:00:00Z", max_units=3),
        make_practitioner_headers(prac["id"]))
    validate_error(res, "ERR_RECOMMENDATION_OVERLAP", expected_status=409)


def test_touching_recommendation_intervals_allowed(api):
    """PRD §3.4: "because the interval is half-open, two intervals that merely
    touch at an endpoint do not overlap and are allowed, but any genuine overlap
    is rejected with `ERR_RECOMMENDATION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/recommendation_interval_overlap
    """
    cust = new_customer(email="c13b@x.com", full_name="Cust Thirteen B")
    prac = new_practitioner(full_name="Dr Bee", license_number="LIC-2b")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True)
    set_clock("2026-07-01T00:00:00Z")
    # First interval [2026-07-01, 2026-09-01).
    new_recommendation(prac["id"], cust["id"], prod["id"],
                       expires_at="2026-09-01T00:00:00Z", max_units=5)
    # Advance clock so the second recommendation's issued_at == the first's
    # expires_at: [2026-09-01, ...) touches [..., 2026-09-01) — no overlap.
    set_clock("2026-09-01T00:00:00Z")
    second = new_recommendation(prac["id"], cust["id"], prod["id"],
                                expires_at="2026-12-01T00:00:00Z", max_units=3)
    assert second["status"] == "ISSUED"


def test_revoke_already_revoked_recommendation_rejected(api):
    """PRD §3.4: "it is moved to `REVOKED` when its issuing practitioner revokes
    it while it is still `ISSUED` (a revoke on a recommendation not in `ISSUED` is
    rejected with `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/corner_revoke_already_revoked_recommendation_invalid_state
    """
    cust = new_customer(email="sm3@x.com", full_name="SM Three")
    prac = new_practitioner(full_name="Dr Cee", license_number="LIC-3")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True)
    rec = new_recommendation(prac["id"], cust["id"], prod["id"], max_units=3)
    headers = make_practitioner_headers(prac["id"])
    validate_success(api.revoke_recommendation(rec["id"], headers), 200)
    res = api.revoke_recommendation(rec["id"], headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_expiry_sweep_marks_recommendation_expired(api):
    """PRD §3.4: "It is moved to `EXPIRED` by the operator-run expiry sweep when
    its `expires_at` is at or before the current logical clock."

    Design: Corner/cross_cutting/corner_expiry_sweep_marks_recommendation_expired
    """
    cust = new_customer(email="cc5@x.com", full_name="CC Five")
    prac = new_practitioner(full_name="Dr Eff", license_number="LIC-5")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True)
    rec = new_recommendation(prac["id"], cust["id"], prod["id"],
                             expires_at="2026-08-01T00:00:00Z", max_units=5)
    set_clock("2026-09-01T00:00:00Z")
    run_expiry_sweep()
    fetched = validate_success(api.get_recommendation(rec["id"], OPERATOR), 200)
    assert fetched["status"] == "EXPIRED"


def test_list_recommendations_filtered_by_customer(api):
    """PRD §3.4: "Recommendations may be listed and filtered by `practitioner_id`,
    `customer_id`, `product_id`, or `status`."

    Design: Corner/endpoints/corner_list_recommendations_filter_by_customer
    """
    cust = new_customer(email="e1@x.com", full_name="E One")
    prac = new_practitioner(full_name="Dr Dee", license_number="LIC-4")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True)
    rec = new_recommendation(prac["id"], cust["id"], prod["id"], max_units=5)
    data, meta = validate_paginated(
        api.list_recommendations(OPERATOR, params={"customer_id": cust["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == rec["id"]
