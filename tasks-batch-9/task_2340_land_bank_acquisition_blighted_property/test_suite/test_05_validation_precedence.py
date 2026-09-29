"""
Which rule decides the response when one request breaks two of them at once.

The PRD orders every rejection into a single ladder and lets the earliest rung
that fires name the cause. These tests build requests that break two rungs
simultaneously and pin the one error identifier the ladder allows to surface,
together with the untouched state that proves the later rung never ran.
"""

from test_helpers import (
    CLERK_1,
    INV_1,
    expected_mow_estimate_cents,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)


# ── the parcel-state gate versus the fiscal gate ────────────────────────────
def _prospect_parcel_over_a_thin_budget(api):
    """
    A registry-only parcel of 100,000 square feet, a contractor fit to mow it,
    and a budget too small to pay for the mowing: the request that follows
    breaks both the inventory-custody rule and the available-balance rule.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Thin Maintenance Line",
        source_type="GENERAL_FUND",
        authorized_cents=50000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    prop = fixtures.create_property(
        api,
        address="110 Juniper Rd",
        situs_ward=8,
        lot_area_sqft=100000,
        assessed_value_cents=500000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=5,
    )
    contractor = fixtures.create_contractor(api)
    return funding_source, prop, contractor


def test_prospect_custody_error_answers_before_the_thin_budget(api):
    """
    A mowing order on a registry-only parcel funded from a budget too small for the estimate is refused for the parcel's custody, not for the money.

    When several rules could reject one request, the earliest rule in the following ladder decides the response, so that the reported cause is the real one:

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_funding_insufficiency
    """
    funding_source, prop, contractor = _prospect_parcel_over_a_thin_budget(api)

    before = fixtures.read_property(api, prop["id"])
    assert before["custody_status"] == "PROSPECT"

    # Both rules really are broken: the mowing estimate on a 100,000 sqft lot is
    # 197,025 cents against 50,000 cents of available money.
    assert expected_mow_estimate_cents(100000) == 197025
    assert funding_source["available_cents"] == 50000

    payload = factories.maintenance_order_payload(
        contractor["id"], funding_source["id"], before["version"]
    )
    response = api.create_maintenance_order(prop["id"], payload, INV_1)

    validate_error(response, "ERR_PROPERTY_NOT_IN_INVENTORY", 409)


def test_thin_budget_is_left_whole_when_the_custody_error_answers(api):
    """
    Because the custody rule answers first, the money rule never runs: no order is written and the budget keeps every cent of its authorization.

    When several rules could reject one request, the earliest rule in the following ladder decides the response, so that the reported cause is the real one:

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_funding_insufficiency
    """
    funding_source, prop, contractor = _prospect_parcel_over_a_thin_budget(api)
    version_before = fixtures.property_version(api, prop["id"])

    payload = factories.maintenance_order_payload(
        contractor["id"], funding_source["id"], version_before
    )
    response = api.create_maintenance_order(prop["id"], payload, INV_1)
    validate_error(response, "ERR_PROPERTY_NOT_IN_INVENTORY", 409)

    ledger = fixtures.read_funding_source(api, funding_source["id"])
    assert ledger["committed_cents"] == 0
    assert ledger["disbursed_cents"] == 0
    assert ledger["available_cents"] == 50000
    assert ledger["status"] == "ACTIVE"

    orders, meta = validate_paginated(
        api.list_maintenance_orders(INV_1, {"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0
    assert orders == []
    assert fixtures.property_version(api, prop["id"]) == version_before


# ── contractor debarment versus contractor licence expiry ───────────────────
def _acquired_parcel_and_unfit_contractor(api):
    """
    An acquired parcel, plus a contractor that is both debarred and licensed
    only to 10 August 2026 — so a September window breaks both contractor rules.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Maintenance Line",
        source_type="GENERAL_FUND",
        authorized_cents=1000000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    prop = fixtures.create_property(
        api,
        address="120 Juniper Rd",
        situs_ward=8,
        lot_area_sqft=10000,
        assessed_value_cents=200000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=5,
    )
    fixtures.acquire_property(
        api, prop["id"], funding_source["id"], donor_name="Juniper Road Trust"
    )
    contractor = fixtures.create_contractor(
        api,
        name="Barred Brothers Yardwork",
        license_expires_on="2026-08-10T00:00:00Z",
        max_concurrent_crews=3,
        specialties=["MOW", "SECURE"],
        debarred=True,
    )
    return funding_source, prop, contractor


def test_debarment_answers_before_the_lapsed_licence(api):
    """
    A contractor that is debarred and whose licence also lapses before the work window is refused for the debarment.

    When several rules could reject one request, the earliest rule in the following ladder decides the response, so that the reported cause is the real one:

    Design: Difficulty/priority_pair_validation_conflict/contractor_debarment_outranks_license_expiry
    """
    funding_source, prop, contractor = _acquired_parcel_and_unfit_contractor(api)
    assert contractor["debarred"] is True

    payload = factories.maintenance_order_payload(
        contractor["id"],
        funding_source["id"],
        fixtures.property_version(api, prop["id"]),
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
    )
    response = api.create_maintenance_order(prop["id"], payload, INV_1)

    # The window closes on 3 September, well past the 10 August licence expiry,
    # so the licence rule is broken too and still may not surface.
    validate_error(response, "ERR_CONTRACTOR_DEBARRED", 422)


def test_custody_gate_passed_and_no_money_moved_on_the_debarment_refusal(api):
    """
    The parcel is in inventory and the budget is ample, so the debarment is the first rule the request breaks and nothing is committed against the budget.

    When several rules could reject one request, the earliest rule in the following ladder decides the response, so that the reported cause is the real one:

    Design: Difficulty/priority_pair_validation_conflict/contractor_debarment_outranks_license_expiry
    """
    funding_source, prop, contractor = _acquired_parcel_and_unfit_contractor(api)

    parcel = fixtures.read_property(api, prop["id"])
    assert parcel["custody_status"] == "ACQUIRED"

    payload = factories.maintenance_order_payload(
        contractor["id"],
        funding_source["id"],
        parcel["version"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
    )
    response = api.create_maintenance_order(prop["id"], payload, INV_1)
    validate_error(response, "ERR_CONTRACTOR_DEBARRED", 422)

    ledger = fixtures.read_funding_source(api, funding_source["id"], CLERK_1)
    assert ledger["committed_cents"] == 0
    assert ledger["disbursed_cents"] == 0
    assert ledger["available_cents"] == 1000000

    orders, meta = validate_paginated(
        api.list_maintenance_orders(INV_1, {"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0
    assert orders == []
