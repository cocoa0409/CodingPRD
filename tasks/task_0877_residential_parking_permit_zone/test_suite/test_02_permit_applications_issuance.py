"""Permit application review, issuance, the density/vehicle-cap gates, issuance-fee
proration, validation-priority conflicts, and zone OCC.

Translates Difficulty instances for combinatorial_formula (issuance fee),
boundary_precision_check (density), cross_entity_state_dependency (proof),
priority_pair_validation_conflict (state vs fiscal; safety vs constraint), plus
Corner instances for duplicate applications, foreign vehicles, and zone OCC.
"""
from test_helpers import (
    validate_success, validate_error,
    approve_payload, create_permit_application_payload,
    make_resident_headers,
)
from test_helpers.fixtures import (
    set_clock, create_zone, register_household, add_vehicle,
    setup_verified_household_with_vehicle, verify_household_proof,
    create_application, review_application, approve_application, issue_permit,
    zone_version, SUP, CLERK,
)


# --------------------------------------------------------------------------
# combinatorial_formula / issuance_fee_round_per_month_then_sum
# --------------------------------------------------------------------------
def test_issuance_fee_rounds_monthly_rate_before_multiplying(api):
    """PRD §3.5: "The permit's `fee_paid_cents` is the rounded monthly rate
    multiplied by that month count. The monthly rate must be rounded before it is
    multiplied ("round per month, then sum"); do not instead multiply the annual
    fee by the month count, divide by twelve, and round only at the end, because
    when the annual fee is not divisible by twelve the two orders diverge."

    Design: Difficulty/combinatorial_formula/issuance_fee_round_per_month_then_sum
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_annual_fee_cents=12500, permit_capacity=3)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    # round(12500/12)=1042; 1042 * 10 remaining months = 10420.
    assert permit["fee_paid_cents"] == 10420


def test_issuance_fee_is_not_sum_then_round(api):
    """PRD §3.5: "do not instead multiply the annual fee by the month count, divide
    by twelve, and round only at the end, because when the annual fee is not
    divisible by twelve the two orders diverge."

    Design: Difficulty/combinatorial_formula/issuance_fee_round_per_month_then_sum
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_annual_fee_cents=12500, permit_capacity=3)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    # round(12500*10/12) = 10417 would be the wrong "sum then round" order.
    assert permit["fee_paid_cents"] != 10417
    assert permit["fee_paid_cents"] == 10420


# --------------------------------------------------------------------------
# boundary_precision_check / density_limit_exact_capacity_boundary
# --------------------------------------------------------------------------
def _reviewed_app(api, zone_id, plate):
    hh, veh = setup_verified_household_with_vehicle(api, zone_id, plate=plate)
    app = create_application(api, zone_id, hh["id"], veh["id"])
    review_application(api, app["id"])
    return app


def test_first_approve_succeeds_at_capacity_boundary(api):
    """PRD §3.5: "The zone must be below the density limit — its `active_permit_count`
    must be strictly less than its `permit_capacity`, or the request fails with
    `ERR_ZONE_AT_CAPACITY` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/density_limit_exact_capacity_boundary
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=1)
    a1 = _reviewed_app(api, zone["id"], "BP1-A")
    permit = approve_application(api, a1["id"], zone["id"])
    assert permit["status"] == "ACTIVE"
    zone_after = validate_success(api.get_zone(zone["id"], SUP), 200)
    assert zone_after["active_permit_count"] == 1


def test_second_approve_rejected_at_capacity(api):
    """PRD §3.5: "The zone must be below the density limit — its `active_permit_count`
    must be strictly less than its `permit_capacity`, or the request fails with
    `ERR_ZONE_AT_CAPACITY` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/density_limit_exact_capacity_boundary
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=1)
    a1 = _reviewed_app(api, zone["id"], "BP1-A")
    a2 = _reviewed_app(api, zone["id"], "BP1-B")
    approve_application(api, a1["id"], zone["id"])
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(a2["id"], approve_payload(v), SUP)
    validate_error(resp, "ERR_ZONE_AT_CAPACITY", expected_status=409)


# --------------------------------------------------------------------------
# cross_entity_state_dependency / review_blocked_when_household_proof_unverified
# --------------------------------------------------------------------------
def test_review_rejected_when_household_proof_unverified(api):
    """PRD §3.4: "Review requires the applying household's `proof_status` to be
    `VERIFIED` and the zone to be `ACTIVE`; a household without verified proof fails
    with `ERR_PROOF_NOT_VERIFIED` and a suspended zone with `ERR_ZONE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/review_blocked_when_household_proof_unverified
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    veh = add_vehicle(api, hh["id"])
    app = create_application(api, zone["id"], hh["id"], veh["id"])
    resp = api.review_permit_application(app["id"], CLERK)
    validate_error(resp, "ERR_PROOF_NOT_VERIFIED", expected_status=422)


def test_application_stays_submitted_when_review_blocked(api):
    """PRD §2.7: "a household whose proof is not verified raises `ERR_PROOF_NOT_VERIFIED`
    (HTTP 422) on review, approve, and renew-approve"

    Design: Difficulty/cross_entity_state_dependency/review_blocked_when_household_proof_unverified
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    veh = add_vehicle(api, hh["id"])
    app = create_application(api, zone["id"], hh["id"], veh["id"])
    api.review_permit_application(app["id"], CLERK)
    fetched = validate_success(api.get_permit_application(app["id"], CLERK), 200)
    assert fetched["status"] == "SUBMITTED"


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / state_beats_fiscal_on_approve
# --------------------------------------------------------------------------
def test_invalid_state_wins_over_capacity_on_approve(api):
    """PRD §2.7: "they are evaluated in a fixed priority order and the first failure
    determines the returned error. The order is: (1) authentication of the headers
    (`ERR_UNAUTHENTICATED`); (2) role authorization, including entity-backed ownership
    (`ERR_UNAUTHORIZED`); (3) existence of every path- and body-referenced resource,
    left to right (`ERR_NOT_FOUND`); (4) whether the target resource is in a legal
    state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_approve
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=1)
    a1 = _reviewed_app(api, zone["id"], "PP1-A")
    approve_application(api, a1["id"], zone["id"])
    # Second household: application left in SUBMITTED (never reviewed) in a full zone.
    hh2, veh2 = setup_verified_household_with_vehicle(api, zone["id"], plate="PP1-B")
    ax = create_application(api, zone["id"], hh2["id"], veh2["id"])
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(ax["id"], approve_payload(v), SUP)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_submitted_app_not_approved_when_zone_full(api):
    """PRD §3.5: "it is gated on five conditions checked in the priority order of §2.7.
    The application must be `UNDER_REVIEW`; the zone must be `ACTIVE`; the applying
    household's `proof_status` must be `VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_approve
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=1)
    a1 = _reviewed_app(api, zone["id"], "PP1-A")
    approve_application(api, a1["id"], zone["id"])
    hh2, veh2 = setup_verified_household_with_vehicle(api, zone["id"], plate="PP1-B")
    ax = create_application(api, zone["id"], hh2["id"], veh2["id"])
    v = zone_version(api, zone["id"])
    api.approve_permit_application(ax["id"], approve_payload(v), SUP)
    fetched = validate_success(api.get_permit_application(ax["id"], SUP), 200)
    assert fetched["status"] == "SUBMITTED"


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / safety_zone_suspended_beats_vehicle_cap
# --------------------------------------------------------------------------
def _household_at_vehicle_cap_with_third_reviewed(api, zone):
    """Household holds 2 ACTIVE permits (at cap 2); a 3rd application is UNDER_REVIEW."""
    hh = register_household(api, zone["id"])
    verify_household_proof(api, hh["id"])
    va = add_vehicle(api, hh["id"], license_plate="PP2-A")
    vb = add_vehicle(api, hh["id"], license_plate="PP2-B")
    vc = add_vehicle(api, hh["id"], license_plate="PP2-C")
    for veh in (va, vb):
        app = create_application(api, zone["id"], hh["id"], veh["id"])
        review_application(api, app["id"])
        approve_application(api, app["id"], zone["id"])
    a3 = create_application(api, zone["id"], hh["id"], vc["id"])
    review_application(api, a3["id"])
    return hh, a3


def test_zone_suspended_wins_over_vehicle_cap_on_approve(api):
    """PRD §2.7: "a suspended zone raises `ERR_ZONE_SUSPENDED` (HTTP 409) on review,
    approve, and waitlist, while a suspended household raises `ERR_HOUSEHOLD_SUSPENDED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_zone_suspended_beats_vehicle_cap
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=3, max_permits_per_household=2)
    hh, a3 = _household_at_vehicle_cap_with_third_reviewed(api, zone)
    api.suspend_zone(zone["id"], SUP)
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(a3["id"], approve_payload(v), SUP)
    validate_error(resp, "ERR_ZONE_SUSPENDED", expected_status=409)


def test_suspended_zone_approve_leaves_application_under_review(api):
    """PRD §3.5: "the zone must be `ACTIVE`; the applying household's `proof_status`
    must be `VERIFIED`. The household must be below the vehicle cap — its
    `active_permit_count` must be strictly less than the zone's
    `max_permits_per_household`, or the request fails with `ERR_HOUSEHOLD_VEHICLE_CAP`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_zone_suspended_beats_vehicle_cap
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=3, max_permits_per_household=2)
    hh, a3 = _household_at_vehicle_cap_with_third_reviewed(api, zone)
    api.suspend_zone(zone["id"], SUP)
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(a3["id"], approve_payload(v), SUP)
    assert resp.status_code == 409
    fetched = validate_success(api.get_permit_application(a3["id"], SUP), 200)
    assert fetched["status"] == "UNDER_REVIEW"


# --------------------------------------------------------------------------
# Corner/validations/duplicate_application_returns_409
# --------------------------------------------------------------------------
def test_duplicate_open_application_rejected(api):
    """PRD §3.4: "if an application for the same household and vehicle already sits in
    `SUBMITTED`, `UNDER_REVIEW`, or `WAITLISTED`, the new application is rejected with
    `ERR_DUPLICATE_APPLICATION` (HTTP 409)."

    Design: Corner/validations/duplicate_application_returns_409
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    veh = add_vehicle(api, hh["id"])
    create_application(api, zone["id"], hh["id"], veh["id"])
    resp = api.create_permit_application(
        create_permit_application_payload(zone["id"], hh["id"], veh["id"]),
        make_resident_headers(hh["id"]),
    )
    validate_error(resp, "ERR_DUPLICATE_APPLICATION", expected_status=409)


# --------------------------------------------------------------------------
# Corner/validations/application_with_foreign_vehicle_rejected
# --------------------------------------------------------------------------
def test_application_with_foreign_vehicle_rejected(api):
    """PRD §3.4: "The named vehicle must be an `ACTIVE` vehicle of the applying
    household — otherwise `ERR_VEHICLE_HOUSEHOLD_MISMATCH` (HTTP 409)."

    Design: Corner/validations/application_with_foreign_vehicle_rejected
    """
    zone = create_zone(api)
    h1 = register_household(api, zone["id"])
    v1 = add_vehicle(api, h1["id"])
    h2 = register_household(api, zone["id"])
    resp = api.create_permit_application(
        create_permit_application_payload(zone["id"], h2["id"], v1["id"]),
        make_resident_headers(h2["id"]),
    )
    validate_error(resp, "ERR_VEHICLE_HOUSEHOLD_MISMATCH", expected_status=409)


# --------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_stale_zone_version_returns_412
# --------------------------------------------------------------------------
def test_stale_zone_version_on_second_approve_rejected(api):
    """PRD §2.8: "Every approval bumps the zone's `version` and consumes a slot; if
    another approval, refund, or suspension has advanced the zone's `version` since
    the supervisor last read it, the request is rejected with `ERR_ZONE_VERSION_CONFLICT`
    (HTTP 412), so a decision taken against a stale view of the zone can never silently
    over-fill it."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_zone_version_returns_412
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    stale_version = zone["version"]  # captured at creation (=1)
    a1 = _reviewed_app(api, zone["id"], "OC1-A")
    a2 = _reviewed_app(api, zone["id"], "OC1-B")
    first = validate_success(api.approve_permit_application(a1["id"], approve_payload(stale_version), SUP), 201)
    assert first["status"] == "ACTIVE"
    resp = api.approve_permit_application(a2["id"], approve_payload(stale_version), SUP)
    validate_error(resp, "ERR_ZONE_VERSION_CONFLICT", expected_status=412)
