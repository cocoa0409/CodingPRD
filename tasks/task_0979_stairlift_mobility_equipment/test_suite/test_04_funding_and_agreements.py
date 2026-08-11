"""Funding waterfall, auto-FUNDED threshold, activation gate, cancellation
compensation, outstanding rollup, and optimistic concurrency."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, MODEL_STRAIGHT,
    assert_agreement, assert_agreement_money_invariants,
    set_clock, create_catalog_model, setup_approved_assessment,
    create_agreement, get_agreement, get_customer, get_equipment_unit,
    get_quote, file_funding_application, decide_funding,
    drive_agreement_to_installed, drive_agreement_to_active,
    attach_service_plan, activate_agreement, record_payment,
    schedule_and_complete_install, skip_funding, fully_fund_agreement,
    make_customer_headers, create_accept_payload, create_payment_payload,
    create_unit, fresh_crew,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FUNDING = TEST_USERS["funding_officer_headers"]
COORD = TEST_USERS["install_coordinator_headers"]


def _setup_pending_agreement(model_code=MODEL_STRAIGHT["model_code"], mode="PURCHASE",
                             **accept_overrides):
    """Approved assessment -> issued quote -> accepted. Agreement sits in
    PENDING_FUNDING with list_price_cents == 502000 for the standard straight
    PURCHASE configuration."""
    set_clock()
    create_catalog_model(model_code=model_code)
    base = setup_approved_assessment(model_code)
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           model_code, mode, **accept_overrides)
    return base, bag


# ---------------------------------------------------------------------------
# Funding waterfall: priority order, per-app cap, overflow capping
# ---------------------------------------------------------------------------

def test_waterfall_allocates_in_priority_order_below_cap(api):
    """PRD §3.4: "Eligible applications — those on the agreement's quote in
    `APPROVED` or `PARTIALLY_APPROVED` — are ordered by `priority_rank`
    ascending with `created_at` ascending as the tiebreak, never by
    identifier. The waterfall walks that order allocating each application the
    smaller of its `approved_cents` and the remaining unallocated balance of
    `list_price_cents`, accumulating `funding_applied_cents` until the balance
    reaches zero; the applied sum is therefore capped at `list_price_cents`."

    Design: Difficulty/combinatorial_formula/funding_waterfall_priority_overflow_capping
    """
    base, bag = _setup_pending_agreement()
    agreement = bag["agreement"]
    assert agreement["list_price_cents"] == 502000
    f1 = file_funding_application(bag["quote"]["id"], source_kind="STATE_GRANT",
                                  requested_cents=300000, priority_rank=2)
    f2 = file_funding_application(bag["quote"]["id"], source_kind="INSURANCE",
                                  requested_cents=200000, priority_rank=1)
    f3 = file_funding_application(bag["quote"]["id"], source_kind="CHARITY",
                                  requested_cents=200000, priority_rank=3)
    decide_funding(f1["id"], "APPROVED", approved_cents=300000)
    decide_funding(f2["id"], "APPROVED", approved_cents=200000)

    mid = get_agreement(agreement["id"])
    # Waterfall order F2 (rank 1) then F1 (rank 2): 200000 + 300000.
    assert mid["funding_applied_cents"] == 500000
    assert mid["status"] == "PENDING_FUNDING"
    assert_agreement_money_invariants(mid)


def test_waterfall_caps_applied_sum_at_list_price_and_funds(api):
    """PRD §3.4: "The waterfall walks that order allocating each application
    the smaller of its `approved_cents` and the remaining unallocated balance
    of `list_price_cents`, accumulating `funding_applied_cents` until the
    balance reaches zero; the applied sum is therefore capped at
    `list_price_cents`."
    PRD §3.4: "When the recomputed `funding_applied_cents` reaches or exceeds
    `list_price_cents` while the agreement is still `PENDING_FUNDING`, the
    agreement auto-transitions to `FUNDED`, the customer's
    `lifetime_outstanding_cents` is recomputed, and an audit event is
    appended."

    Design: Difficulty/combinatorial_formula/funding_waterfall_priority_overflow_capping
    """
    base, bag = _setup_pending_agreement()
    agreement = bag["agreement"]
    f1 = file_funding_application(bag["quote"]["id"], source_kind="STATE_GRANT",
                                  requested_cents=300000, priority_rank=2)
    f2 = file_funding_application(bag["quote"]["id"], source_kind="INSURANCE",
                                  requested_cents=200000, priority_rank=1)
    f3 = file_funding_application(bag["quote"]["id"], source_kind="CHARITY",
                                  requested_cents=200000, priority_rank=3)
    decide_funding(f1["id"], "APPROVED", approved_cents=300000)
    decide_funding(f2["id"], "APPROVED", approved_cents=200000)
    decide_funding(f3["id"], "APPROVED", approved_cents=200000)

    final = get_agreement(agreement["id"])
    # Approved total is 700000 but only 2000 of F3 is needed after F2+F1.
    assert final["funding_applied_cents"] == 502000
    assert final["status"] == "FUNDED"
    assert_agreement_money_invariants(final)


# ---------------------------------------------------------------------------
# Auto-FUNDED numeric threshold (X-1 vs X)
# ---------------------------------------------------------------------------

def test_one_cent_below_threshold_stays_pending_funding(api):
    """PRD §3.4: "When the recomputed `funding_applied_cents` reaches or
    exceeds `list_price_cents` while the agreement is still `PENDING_FUNDING`,
    the agreement auto-transitions to `FUNDED`, the customer's
    `lifetime_outstanding_cents` is recomputed, and an audit event is
    appended."

    Design: Difficulty/boundary_precision_check/funding_auto_funded_at_exact_threshold
    """
    base, bag = _setup_pending_agreement()
    f1 = file_funding_application(bag["quote"]["id"], requested_cents=501999,
                                  priority_rank=1)
    decide_funding(f1["id"], "APPROVED", approved_cents=501999)
    below = get_agreement(bag["agreement"]["id"])
    # list is 502000; 501999 is one cent short of the threshold.
    assert below["funding_applied_cents"] == 501999
    assert below["status"] == "PENDING_FUNDING"


def test_exact_threshold_auto_transitions_to_funded(api):
    """PRD §3.4: "When the recomputed `funding_applied_cents` reaches or
    exceeds `list_price_cents` while the agreement is still `PENDING_FUNDING`,
    the agreement auto-transitions to `FUNDED`, the customer's
    `lifetime_outstanding_cents` is recomputed, and an audit event is
    appended."

    Design: Difficulty/boundary_precision_check/funding_auto_funded_at_exact_threshold
    """
    base, bag = _setup_pending_agreement()
    f1 = file_funding_application(bag["quote"]["id"], requested_cents=501999,
                                  priority_rank=1)
    decide_funding(f1["id"], "APPROVED", approved_cents=501999)
    f2 = file_funding_application(bag["quote"]["id"], source_kind="CHARITY",
                                  requested_cents=1, priority_rank=2)
    decide_funding(f2["id"], "APPROVED", approved_cents=1)
    exact = get_agreement(bag["agreement"]["id"])
    assert exact["funding_applied_cents"] == 502000
    assert exact["status"] == "FUNDED"


# ---------------------------------------------------------------------------
# Activation requires an ACTIVE service plan
# ---------------------------------------------------------------------------

def test_agreement_activate_without_service_plan_rejected(api):
    """PRD §3.5: "With an `ACTIVE` plan in place, the coordinator activates the
    agreement, moving it from `INSTALLED` to `ACTIVE`; attempting activation
    without one is `ERR_SERVICE_PLAN_REQUIRED` (402)."

    Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_service_plan_active
    """
    base, bag = _setup_pending_agreement()
    drive_agreement_to_installed(bag["agreement"], bag["quote"], funding="full")
    res = api.activate_agreement(bag["agreement"]["id"], COORD)
    validate_error(res, ApiErrorId.ERR_SERVICE_PLAN_REQUIRED)
    after = get_agreement(bag["agreement"]["id"])
    assert after["status"] == "INSTALLED"


def test_agreement_activate_with_active_plan_succeeds(api):
    """PRD §3.5: "With an `ACTIVE` plan in place, the coordinator activates the
    agreement, moving it from `INSTALLED` to `ACTIVE`; attempting activation
    without one is `ERR_SERVICE_PLAN_REQUIRED` (402). Activation cascades the
    unit from `INSTALLED` to `IN_SERVICE`, begins rental month accrual for
    rentals, and recomputes the customer's outstanding rollup."

    Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_service_plan_active
    """
    base, bag = _setup_pending_agreement()
    drive_agreement_to_installed(bag["agreement"], bag["quote"], funding="full")
    plan = attach_service_plan(bag["agreement"]["id"], "BASIC")
    active = validate_success(
        api.activate_agreement(bag["agreement"]["id"], COORD), 200)
    assert active["status"] == "ACTIVE"
    unit = get_equipment_unit(bag["unit"]["id"])
    assert unit["status"] == "IN_SERVICE"


# ---------------------------------------------------------------------------
# Cancellation conserves equipment stock
# ---------------------------------------------------------------------------

def test_cancel_from_pending_funding_restores_unit_stock(api):
    """PRD §3.4: "And a `FundingOfficer` may cancel an agreement outright while
    it is in `PENDING_FUNDING`, `FUNDED`, or `SCHEDULED`: the reserved unit is
    released back to `IN_STOCK` as a compensating action, every funding
    application on the quote moves to `WITHDRAWN`, any install job still
    `SCHEDULED` is cancelled, and the customer's outstanding rollup is
    recomputed."

    Design: Difficulty/compensating_invariant/agreement_cancel_conserves_equipment_stock
    """
    base, bag = _setup_pending_agreement()
    unit_after_accept = get_equipment_unit(bag["unit"]["id"])
    assert unit_after_accept["status"] == "RESERVED"

    cancelled = validate_success(
        api.cancel_agreement(bag["agreement"]["id"], FUNDING), 200)
    assert cancelled["status"] == "CANCELLED"
    unit_after = get_equipment_unit(bag["unit"]["id"])
    assert unit_after["status"] == "IN_STOCK"
    data, meta = validate_paginated(
        api.list_equipment_units(
            TEST_USERS["inventory_manager_headers"],
            params={"model_code": MODEL_STRAIGHT["model_code"],
                    "status": "IN_STOCK"}))
    assert len(data) == 1


def test_cancel_from_funded_withdraws_applications_and_releases_unit(api):
    """PRD §3.4: "And a `FundingOfficer` may cancel an agreement outright while
    it is in `PENDING_FUNDING`, `FUNDED`, or `SCHEDULED`: the reserved unit is
    released back to `IN_STOCK` as a compensating action, every funding
    application on the quote moves to `WITHDRAWN`, any install job still
    `SCHEDULED` is cancelled, and the customer's outstanding rollup is
    recomputed."

    Design: Difficulty/compensating_invariant/agreement_cancel_conserves_equipment_stock
    """
    base, bag = _setup_pending_agreement()
    app = file_funding_application(bag["quote"]["id"], requested_cents=502000,
                                   priority_rank=1)
    decide_funding(app["id"], "APPROVED", approved_cents=502000)
    assert get_agreement(bag["agreement"]["id"])["status"] == "FUNDED"

    cancelled = validate_success(
        api.cancel_agreement(bag["agreement"]["id"], FUNDING), 200)
    assert cancelled["status"] == "CANCELLED"
    unit_after = get_equipment_unit(bag["unit"]["id"])
    assert unit_after["status"] == "IN_STOCK"
    app_after = validate_success(
        api.get_funding_application(app["id"], FUNDING), 200)
    assert app_after["status"] == "WITHDRAWN"


# ---------------------------------------------------------------------------
# Outstanding rollup
# ---------------------------------------------------------------------------

def test_customer_outstanding_rollup_aggregation(api):
    """PRD §3.4: "The rollup itself is a standing invariant:
    `lifetime_outstanding_cents` is the sum, across all of the customer's
    agreements in `ACTIVE` or `REMOVAL_REQUESTED`, of each agreement's
    `list_price_cents` minus its `funding_applied_cents` minus its
    `paid_to_date_cents`, floored at zero, and it is re-derived on every
    cascade that touches agreement status, funding, or payments."

    Design: Corner/calculations/customer_outstanding_rollup_aggregation
    """
    set_clock()
    create_catalog_model(model_code="SL-R")
    base = setup_approved_assessment("SL-R")
    # Waiver signed so skip-funding can clear the gate with only partial
    # funding approved (200000 of 502000).
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           "SL-R", "PURCHASE", liability_waiver_signed=True)
    app = file_funding_application(bag["quote"]["id"], requested_cents=200000,
                                   priority_rank=1)
    decide_funding(app["id"], "APPROVED", approved_cents=200000)
    skip_funding(bag["agreement"]["id"])
    schedule_and_complete_install(bag["agreement"]["id"])
    attach_service_plan(bag["agreement"]["id"], "BASIC")
    activate_agreement(bag["agreement"]["id"])
    record_payment(bag["agreement"]["id"], 50000, base["customer"]["id"])

    customer = get_customer(base["customer"]["id"])
    # 502000 - 200000 - 50000
    assert customer["lifetime_outstanding_cents"] == 252000


# ---------------------------------------------------------------------------
# Optimistic concurrency
# ---------------------------------------------------------------------------

def test_error_stale_version_triggerable(api):
    """PRD §2.6: "If the customer's current `version` has advanced since that
    read — because another workflow mutated the customer record, most notably a
    recompute of `lifetime_outstanding_cents` — the acceptance is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing
    against customer state it has not observed. A successful acceptance itself
    increments the customer's `version` by one."

    Design: Corner/errors/error_stale_version_triggerable
    """
    set_clock()
    create_catalog_model(model_code="SL-OCC")
    base = setup_approved_assessment("SL-OCC")
    customer = get_customer(base["customer"]["id"])
    stale_version = customer["version"]

    # First accept succeeds and itself advances the customer version.
    quote1 = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                              "SL-OCC")["quote"]
    bumped = get_customer(base["customer"]["id"])
    assert bumped["version"] != stale_version

    # Second quote on the same customer issues fine (first is ACCEPTED), but
    # accepting it with the pre-first-accept version token is stale.
    quote2 = validate_success(
        api.create_quote(base["customer"]["id"],
                         {"home_assessment_id": base["assessment"]["id"],
                          "model_code": "SL-OCC", "acquisition_mode": "PURCHASE"},
                         SALES), 201)
    validate_success(api.issue_quote(quote2["id"], SALES), 200)
    unit2 = create_unit("SL-OCC")
    res = api.accept_quote(
        quote2["id"], create_accept_payload(unit2["id"], stale_version),
        make_customer_headers(base["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_occ_agreement_payment_stale_version(api):
    """PRD §2.6: "Recording an out-of-pocket payment against an agreement must
    carry `expected_agreement_version` holding the value of that agreement's
    `version` the client last observed. If the agreement's current `version`
    no longer matches — for example because a funding decision advanced it
    through the auto-funding cascade, or a skip-funding transition mutated it
    between the client's read and this write — the payment is rejected with
    `ERR_STALE_VERSION` (HTTP 412). A successful payment increments the
    agreement's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_agreement_payment_stale_version
    """
    set_clock()
    create_catalog_model(model_code="SL-OCCP")
    base = setup_approved_assessment("SL-OCCP")
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           "SL-OCCP", "RENTAL", committed_rental_months=6,
                           liability_waiver_signed=True)
    stale_version = bag["agreement"]["version"]
    # Skip-funding mutates the agreement, advancing its version past the token.
    skip_funding(bag["agreement"]["id"])

    res = api.record_payment(
        bag["agreement"]["id"],
        create_payment_payload(10000, stale_version),
        make_customer_headers(base["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
