"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: FacilityManager calls are entity-backed by Facility and
FieldTechnician calls are entity-backed by Technician. Ownership-gated calls
always use make_facility_manager_headers(facility["id"]) /
make_field_technician_headers(technician["id"]) — never the shared fallback
constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_UTC,
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_DELIVERY_DATE,
    DEFAULT_FUEL_INDEX,
    DEFAULT_GROUP_CODE,
)
from .factories import (
    create_contract_bid_payload,
    create_dispenser_payload,
    create_facility_payload,
    create_forecast_profile_payload,
    create_order_payload,
    create_product_payload,
    create_standing_order_payload,
    create_technician_payload,
    create_training_record_payload,
    create_trial_program_payload,
    create_usage_record_payload,
    order_line,
)
from .test_users import (
    TEST_USERS,
    make_facility_manager_headers,
    make_field_technician_headers,
)

ADMIN = TEST_USERS["distributor_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def fm_headers(facility) -> dict:
    """Ownership-correct FacilityManager headers for the given facility."""
    return make_facility_manager_headers(facility["id"])


def tech_headers(technician) -> dict:
    """Ownership-correct FieldTechnician headers for the given technician."""
    return make_field_technician_headers(technician["id"])


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_facility(name="Fac", facility_group_code=DEFAULT_GROUP_CODE,
                    credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS,
                    delivery_distance_miles=10, **overrides):
    """Create a facility (born ACTIVE, ledger counters zero)."""
    payload = create_facility_payload(
        name=name, facility_group_code=facility_group_code,
        credit_limit_cents=credit_limit_cents,
        delivery_distance_miles=delivery_distance_miles, **overrides)
    return get_success_data(api_client.create_facility(payload, ADMIN))


def create_product(category="PAPER", base_price_cents=1000, qty_on_hand=100,
                   dilution_required=False, chemical_family="NONE",
                   unit_of_measure="CASE", **overrides):
    """Create a product (born ACTIVE, qty_allocated zero)."""
    payload = create_product_payload(
        category=category, base_price_cents=base_price_cents,
        qty_on_hand=qty_on_hand, dilution_required=dilution_required,
        chemical_family=chemical_family, unit_of_measure=unit_of_measure,
        **overrides)
    return get_success_data(api_client.create_product(payload, ADMIN))


def create_technician(name="Tech One"):
    """Create a field technician (born ACTIVE)."""
    return get_success_data(
        api_client.create_technician(create_technician_payload(name=name),
                                     ADMIN))


def suspend_facility(facility_id):
    return get_success_data(api_client.suspend_facility(facility_id, ADMIN))


def reinstate_facility(facility_id):
    return get_success_data(api_client.reinstate_facility(facility_id, ADMIN))


def set_clock(to_iso8601):
    """Advance the logical clock (monotonic)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_daily():
    """Run the pinned daily ops sweep; returns the summary payload."""
    return get_success_data(api_client.run_daily_ops(ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: facility + product pair
# ---------------------------------------------------------------------------

def setup_facility_with_product(facility_name="Fac",
                                facility_group_code=DEFAULT_GROUP_CODE,
                                credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS,
                                delivery_distance_miles=10,
                                category="PAPER", base_price_cents=1000,
                                qty_on_hand=100, dilution_required=False,
                                chemical_family="NONE", unit_of_measure="CASE",
                                product_overrides=None):
    """Facility plus one product. Returns (facility, product)."""
    facility = create_facility(
        name=facility_name, facility_group_code=facility_group_code,
        credit_limit_cents=credit_limit_cents,
        delivery_distance_miles=delivery_distance_miles)
    product = create_product(
        category=category, base_price_cents=base_price_cents,
        qty_on_hand=qty_on_hand, dilution_required=dilution_required,
        chemical_family=chemical_family, unit_of_measure=unit_of_measure,
        **(product_overrides or {}))
    return facility, product


# ---------------------------------------------------------------------------
# Usage records and forecast profiles
# ---------------------------------------------------------------------------

def create_usage_record(facility, product, quantity_used=90,
                        period_start="2026-06-01T00:00:00Z",
                        period_end="2026-06-30T00:00:00Z", source="MANUAL",
                        post=False):
    """Submit a usage record; optionally post it (SUBMITTED -> POSTED)."""
    record = get_success_data(api_client.create_usage_record(
        create_usage_record_payload(
            facility["id"], product["id"], quantity_used=quantity_used,
            period_start=period_start, period_end=period_end, source=source),
        ADMIN))
    if post:
        record = get_success_data(
            api_client.post_usage_record(record["id"], ADMIN))
    return record


def create_forecast_profile(facility, product, horizon_days=30,
                            safety_stock=0, current_on_hand=0):
    return get_success_data(api_client.create_forecast_profile(
        create_forecast_profile_payload(
            facility["id"], product["id"], horizon_days=horizon_days,
            safety_stock=safety_stock, current_on_hand=current_on_hand),
        ADMIN))


def recompute_profile(profile_id, variant="FINAL"):
    return get_success_data(
        api_client.recompute_forecast_profile(profile_id, variant, ADMIN))


def setup_profile_with_usage(quantity_posted=90, horizon_days=30,
                             safety_stock=0, current_on_hand=0):
    """Facility + product + one POSTED usage record (in the trailing window at
    the default clock) + forecast profile. Returns (facility, product,
    profile)."""
    facility, product = setup_facility_with_product(base_price_cents=1200)
    create_usage_record(facility, product, quantity_used=quantity_posted,
                        post=True)
    profile = create_forecast_profile(
        facility, product, horizon_days=horizon_days,
        safety_stock=safety_stock, current_on_hand=current_on_hand)
    return facility, product, profile


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def create_order_draft(facility, lines, delivery_date=DEFAULT_DELIVERY_DATE,
                       fuel_index=DEFAULT_FUEL_INDEX, as_admin=False):
    """Create a DRAFT manual order with its lines (born PENDING)."""
    payload = create_order_payload(
        facility["id"], lines, delivery_date=delivery_date,
        fuel_index=fuel_index)
    headers = ADMIN if as_admin else fm_headers(facility)
    return get_success_data(api_client.create_order(payload, headers))


def place_order(order_id, facility=None, as_admin=False):
    """Place a DRAFT order; returns the PLACED order."""
    if as_admin:
        headers = ADMIN
    else:
        headers = fm_headers(facility)
    return get_success_data(api_client.place_order(order_id, headers))


def setup_placed_order(qty=5, base_price_cents=1000, qty_on_hand=100,
                       fuel_index=DEFAULT_FUEL_INDEX,
                       credit_limit_cents=DEFAULT_CREDIT_LIMIT_CENTS,
                       delivery_distance_miles=10, category="PAPER",
                       dilution_required=False, chemical_family="NONE",
                       unit_of_measure="CASE",
                       discount_pct=None, facility_name="Fac",
                       product_overrides=None):
    """Facility + product + one-line order driven DRAFT -> PLACED.
    Returns (facility, product, order)."""
    facility, product = setup_facility_with_product(
        facility_name=facility_name, credit_limit_cents=credit_limit_cents,
        delivery_distance_miles=delivery_distance_miles, category=category,
        base_price_cents=base_price_cents, qty_on_hand=qty_on_hand,
        dilution_required=dilution_required, chemical_family=chemical_family,
        unit_of_measure=unit_of_measure,
        product_overrides=product_overrides)
    order = create_order_draft(
        facility, [order_line(product["id"], qty, discount_pct)],
        fuel_index=fuel_index)
    order = place_order(order["id"], facility)
    return facility, product, order


def deliver_order(order_id, fuel_index_at_delivery=DEFAULT_FUEL_INDEX):
    """PLACED -> DELIVERED at the given delivery-day diesel index."""
    return get_success_data(
        api_client.confirm_delivery(order_id, fuel_index_at_delivery, ADMIN))


def invoice_order(order_id):
    """DELIVERED -> INVOICED."""
    return get_success_data(api_client.invoice_order(order_id, ADMIN))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_facility(facility_id):
    return get_success_data(api_client.get_facility(facility_id, ADMIN))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ADMIN))


def get_order_lines(order_id):
    """All lines of an order (creation order)."""
    data, _meta = validate_paginated(
        api_client.list_order_lines(ADMIN, params={"order_id": order_id,
                                                   "limit": 100}))
    return data


def get_only_order_line(order_id):
    lines = get_order_lines(order_id)
    assert len(lines) == 1, f"Expected exactly one line, got {len(lines)}"
    return lines[0]


# ---------------------------------------------------------------------------
# Standing orders
# ---------------------------------------------------------------------------

def create_standing_order(facility, items, frequency="WEEKLY",
                          next_run_date="2026-08-03T00:00:00Z",
                          fuel_index=None):
    """Create a standing order (born DRAFT) as the facility's manager."""
    payload = create_standing_order_payload(
        facility["id"], items, frequency=frequency,
        next_run_date=next_run_date)
    if fuel_index is not None:
        payload["fuel_index"] = fuel_index
    return get_success_data(
        api_client.create_standing_order(payload, fm_headers(facility)))


def activate_standing_order(standing_order_id, facility):
    return get_success_data(api_client.activate_standing_order(
        standing_order_id, fm_headers(facility)))


def pause_standing_order(standing_order_id, facility):
    return get_success_data(api_client.pause_standing_order(
        standing_order_id, fm_headers(facility)))


def resume_standing_order(standing_order_id, facility):
    return get_success_data(api_client.resume_standing_order(
        standing_order_id, fm_headers(facility)))


def get_standing_order(standing_order_id):
    return get_success_data(
        api_client.get_standing_order(standing_order_id, ADMIN))


def setup_active_standing_order(qty=2, frequency="WEEKLY",
                                next_run_date="2026-08-03T00:00:00Z",
                                fuel_index=None, base_price_cents=1000,
                                qty_on_hand=500,
                                facility_group_code=DEFAULT_GROUP_CODE):
    """Facility + product + standing order driven DRAFT -> ACTIVE.
    Returns (facility, product, standing_order)."""
    facility, product = setup_facility_with_product(
        facility_group_code=facility_group_code,
        base_price_cents=base_price_cents, qty_on_hand=qty_on_hand)
    so = create_standing_order(
        facility, [order_line(product["id"], qty)], frequency=frequency,
        next_run_date=next_run_date, fuel_index=fuel_index)
    so = activate_standing_order(so["id"], facility)
    return facility, product, so


# ---------------------------------------------------------------------------
# Dispensers and training
# ---------------------------------------------------------------------------

def create_dispenser(facility, product, technician, zone="kitchen",
                     install_start="2026-08-10T09:00:00Z",
                     install_end="2026-08-10T10:00:00Z"):
    """Schedule a dispenser install (born SCHEDULED)."""
    return get_success_data(api_client.create_dispenser(
        create_dispenser_payload(
            facility["id"], product["id"], technician["id"], zone=zone,
            install_start=install_start, install_end=install_end),
        ADMIN))


def complete_dispenser(dispenser_id, technician):
    return get_success_data(api_client.complete_dispenser(
        dispenser_id, tech_headers(technician)))


def create_training_record(facility, product, employee_name="Emp One"):
    return get_success_data(api_client.create_training_record(
        create_training_record_payload(facility["id"], product["id"],
                                       employee_name=employee_name),
        ADMIN))


def certify_training_record(training_record_id, score_pct=90):
    return get_success_data(api_client.certify_training_record(
        training_record_id, score_pct, ADMIN))


def setup_certified_training(facility, product, score_pct=90):
    """Schedule + certify a dilution training record. Returns the record."""
    record = create_training_record(facility, product)
    return certify_training_record(record["id"], score_pct)


# ---------------------------------------------------------------------------
# Contract bids
# ---------------------------------------------------------------------------

def create_contract_bid(product, facility_group_code="GPO-2",
                        bid_price_cents=800,
                        protection_start="2026-09-01T00:00:00Z",
                        protection_end="2026-12-31T00:00:00Z",
                        bid_reference=None):
    """Create a contract bid (born DRAFT) as a SalesRep."""
    overrides = {}
    if bid_reference is not None:
        overrides["bid_reference"] = bid_reference
    payload = create_contract_bid_payload(
        facility_group_code,
        [{"product_id": product["id"], "bid_price_cents": bid_price_cents}],
        protection_start=protection_start, protection_end=protection_end,
        **overrides)
    return get_success_data(api_client.create_contract_bid(payload, SALES))


def submit_bid(bid_id):
    return get_success_data(api_client.submit_bid(bid_id, SALES))


def open_review_bid(bid_id):
    return get_success_data(api_client.open_review_bid(bid_id, SALES))


def award_bid(bid_id):
    return get_success_data(api_client.award_bid(bid_id, ADMIN))


def bid_to_under_review(bid):
    """DRAFT -> SUBMITTED -> UNDER_REVIEW. Returns the bid."""
    submit_bid(bid["id"])
    return open_review_bid(bid["id"])


def setup_awarded_bid(product, facility_group_code="GPO-2",
                      bid_price_cents=800,
                      protection_start="2026-09-01T00:00:00Z",
                      protection_end="2026-12-31T00:00:00Z"):
    """Bid driven all the way to AWARDED. Returns the bid."""
    bid = create_contract_bid(
        product, facility_group_code=facility_group_code,
        bid_price_cents=bid_price_cents, protection_start=protection_start,
        protection_end=protection_end)
    bid_to_under_review(bid)
    return award_bid(bid["id"])


# ---------------------------------------------------------------------------
# Substitution proposals (shortage cascade)
# ---------------------------------------------------------------------------

def setup_pending_proposal(qty=2, short_price=1000, sub_price=900,
                           stock=100, fuel_index=DEFAULT_FUEL_INDEX,
                           category="PAPER"):
    """Facility + short product + cheaper same-category substitute + order
    placed against the short product, then shortage declared so the line is
    SUBSTITUTION_PENDING with a PENDING proposal.
    Returns (facility, short_product, sub_product, order, proposal)."""
    facility, short_product = setup_facility_with_product(
        category=category, base_price_cents=short_price, qty_on_hand=stock)
    sub_product = create_product(category=category,
                                 base_price_cents=sub_price,
                                 qty_on_hand=stock)
    order = create_order_draft(
        facility, [order_line(short_product["id"], qty)],
        fuel_index=fuel_index)
    order = place_order(order["id"], facility)
    get_success_data(api_client.declare_shortage(short_product["id"], ADMIN))
    proposals, _meta = validate_paginated(
        api_client.list_substitution_proposals(ADMIN,
                                               params={"status": "PENDING"}))
    assert len(proposals) == 1, (
        f"Expected exactly one PENDING proposal, got {len(proposals)}")
    return facility, short_product, sub_product, order, proposals[0]


def get_proposal(proposal_id):
    return get_success_data(
        api_client.get_substitution_proposal(proposal_id, ADMIN))


# ---------------------------------------------------------------------------
# Trial programs
# ---------------------------------------------------------------------------

def create_trial_program(facility, product, sample_value_cents=1000,
                         trial_start="2026-08-01T00:00:00Z",
                         trial_end="2026-08-15T00:00:00Z"):
    """Create a sample/trial program (born ACTIVE) as a SalesRep."""
    return get_success_data(api_client.create_trial_program(
        create_trial_program_payload(
            facility["id"], product["id"],
            sample_value_cents=sample_value_cents, trial_start=trial_start,
            trial_end=trial_end),
        SALES))


def get_trial_program(trial_program_id):
    return get_success_data(
        api_client.get_trial_program(trial_program_id, ADMIN))
