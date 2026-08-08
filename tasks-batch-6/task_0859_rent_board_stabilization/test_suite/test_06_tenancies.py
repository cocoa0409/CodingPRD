"""Tenancies: stabilization gate, occupancy adjacency/overlap, precedence ordering.

Sources: Difficulty/cross_entity_state_dependency, Difficulty/resource_temporal_overlap,
Difficulty/priority_pair_validation_conflict.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_landlord_headers, make_compliance_officer_headers,
    create_tenancy_payload, create_exemption_payload,
    create_tenant, create_active_tenancy,
    setup_landlord_and_unit, setup_unit_with_active_tenancy, setup_exemption_requested,
)


def _make_unit_exempt(api, ctx, exemption_type="OWNER_OCCUPIED"):
    """Request + approve a non-vacancy exemption so the unit becomes EXEMPT."""
    lheaders = make_landlord_headers(ctx["landlord_id"])
    exemption = get_success_data(api.create_exemption(
        create_exemption_payload(ctx["unit_id"], exemption_type), lheaders))
    get_success_data(api.decide_exemption(
        exemption["id"], {"decision": "APPROVE", "effective_date": "2026-06-01"},
        make_compliance_officer_headers("co-exempt")))


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/tenancy_requires_unit_stabilized
# ---------------------------------------------------------------------------
def test_create_tenancy_on_exempt_unit_rejected(api):
    """PRD §3.4: "Creating a tenancy on a non-stabilized unit is rejected with
    ERR_UNIT_NOT_STABILIZED."

    Design: Difficulty/cross_entity_state_dependency/tenancy_requires_unit_stabilized
    """
    base = setup_landlord_and_unit(api)
    _make_unit_exempt(api, base, exemption_type="OWNER_OCCUPIED")
    tenant = create_tenant(api)
    resp = api.create_tenancy(
        create_tenancy_payload(base["unit_id"], tenant["id"], "2026-07-01"),
        make_landlord_headers(base["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_STABILIZED)


def test_create_tenancy_on_stabilized_unit_succeeds(api):
    """PRD §3.4: "A tenancy is created on a `STABILIZED` unit ... On creation the new
    tenancy's `monthly_rent_cents` is set to the unit's current `current_lawful_rent_cents`,
    and its `status` is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/tenancy_requires_unit_stabilized
    """
    base = setup_landlord_and_unit(api, base_rent_cents=300000)
    tenant = create_tenant(api)
    data = validate_success(api.create_tenancy(
        create_tenancy_payload(base["unit_id"], tenant["id"], "2026-07-01"),
        make_landlord_headers(base["landlord_id"])), expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["monthly_rent_cents"] == 300000


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/tenancy_unit_adjacency_allowed
# ---------------------------------------------------------------------------
def test_adjacent_tenancy_start_equals_prior_end_allowed(api):
    """PRD §3.4: "Two intervals that merely touch — one starting exactly at the instant a
    prior one ends — do not overlap and are allowed; a genuine overlap is rejected with
    ERR_UNIT_OCCUPIED."

    Design: Difficulty/resource_temporal_overlap/tenancy_unit_adjacency_allowed
    """
    ctx = setup_unit_with_active_tenancy(api, base_rent_cents=300000,
                                         start_date="2026-06-01", end_date="2026-12-01")
    tenant2 = create_tenant(api)
    data = validate_success(api.create_tenancy(
        create_tenancy_payload(ctx["unit_id"], tenant2["id"], "2026-12-01",
                               end_date="2027-06-01"),
        make_landlord_headers(ctx["landlord_id"])), expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["monthly_rent_cents"] == 300000


def test_overlapping_tenancy_start_rejected(api):
    """PRD §3.4: "it may not overlap any existing `ACTIVE` tenancy on the same unit ...
    do not overlap and are allowed; a genuine overlap is rejected with `ERR_UNIT_OCCUPIED`."

    Design: Difficulty/resource_temporal_overlap/tenancy_unit_adjacency_allowed
    """
    ctx = setup_unit_with_active_tenancy(api, base_rent_cents=300000,
                                         start_date="2026-06-01", end_date="2026-12-01")
    tenant2 = create_tenant(api)
    resp = api.create_tenancy(
        create_tenancy_payload(ctx["unit_id"], tenant2["id"], "2026-11-01",
                               end_date="2027-06-01"),
        make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_OCCUPIED)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/stabilization_state_outranks_occupancy_temporal
# ---------------------------------------------------------------------------
def test_exempt_and_occupied_returns_not_stabilized(api):
    """PRD §2.8: the endpoint-specific checks follow in priority order "unit-stabilized
    (ERR_UNIT_NOT_STABILIZED) ... unit-occupied (ERR_UNIT_OCCUPIED)"; the earlier-listed
    unit-stabilized check wins when both fail.
    PRD §3.4: "Creating a tenancy on a non-stabilized unit is rejected with
    ERR_UNIT_NOT_STABILIZED."

    Design: Difficulty/priority_pair_validation_conflict/stabilization_state_outranks_occupancy_temporal
    """
    ctx = setup_exemption_requested(api, "SUBSTANTIAL_REHAB", with_active_tenancy=True)
    get_success_data(api.decide_exemption(
        ctx["exemption_id"], {"decision": "APPROVE", "effective_date": "2026-06-15"},
        make_compliance_officer_headers("co-precedence")))
    # Unit is now EXEMPT and still occupied by the active tenancy -> both checks would fail.
    resp = api.create_tenancy(
        create_tenancy_payload(ctx["unit_id"], ctx["tenant_id"], "2026-08-01",
                               end_date="2027-08-01"),
        make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_STABILIZED)


def test_stabilized_and_occupied_returns_unit_occupied(api):
    """PRD §2.8: with only the occupancy conflict present (the unit remains STABILIZED),
    the later-listed unit-occupied check fires — confirming the precedence between
    unit-stabilized and unit-occupied.
    PRD §3.4: "do not overlap and are allowed; a genuine overlap is rejected with
    `ERR_UNIT_OCCUPIED`."

    Design: Difficulty/priority_pair_validation_conflict/stabilization_state_outranks_occupancy_temporal
    """
    ctx = setup_unit_with_active_tenancy(api, start_date="2026-06-01", end_date="2027-06-01")
    resp = api.create_tenancy(
        create_tenancy_payload(ctx["unit_id"], ctx["tenant_id"], "2026-08-01",
                               end_date="2027-08-01"),
        make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_OCCUPIED)
