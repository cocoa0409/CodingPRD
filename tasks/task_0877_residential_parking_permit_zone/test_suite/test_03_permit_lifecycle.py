"""Permit lifecycle: renewal cycle, dual-variant refund, transfer, the conserved
slot-count and fee-ledger invariants, closed-interval permit overlap, the renewal
window, reverse lookup, listing pagination, and permit OCC.

Translates Difficulty instances (non_linear_state_machine renewal cycle,
dual_variant_calc refund, compensating_invariant slot + ledger,
resource_temporal_overlap permit closed interval) and Corner endpoint/validation
instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    approve_payload, renew_approve_payload, transfer_payload, refund_payload,
    assert_fee_ledger_invariant,
)
from test_helpers.fixtures import (
    set_clock, create_zone, register_household, add_vehicle,
    setup_verified_household_with_vehicle, verify_household_proof,
    create_application, review_application, approve_application, issue_permit,
    zone_version, SUP,
)


# --------------------------------------------------------------------------
# non_linear_state_machine / permit_renewal_cycle_returns_to_active
# --------------------------------------------------------------------------
def _issue_and_request_renewal(api):
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2, permit_annual_fee_cents=12000)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])  # expires 2027-03-31
    set_clock(api, "2027-02-15T00:00:00Z")  # inside 60-day renewal window
    validate_success(api.renew_permit(permit["id"], _resident(hh)), 200)
    return zone, hh, permit


def _resident(hh):
    from test_helpers import make_resident_headers
    return make_resident_headers(hh["id"])


def test_renewal_cycle_returns_permit_to_active(api):
    """PRD §3.6: "Approval drives the permit `RENEWAL_PENDING → ACTIVE`, advances
    `expires_at` to the next fiscal-year-end after the current `expires_at`, adds the
    full-year `permit_annual_fee_cents` to the permit's `fee_paid_cents` and the same
    amount to the zone's `fees_collected_cents`, and increments the permit's `version`
    by one."

    Design: Difficulty/non_linear_state_machine/permit_renewal_cycle_returns_to_active
    """
    zone, hh, permit = _issue_and_request_renewal(api)
    pv = validate_success(api.get_permit(permit["id"], SUP), 200)["version"]
    approved = validate_success(api.renew_approve_permit(permit["id"], renew_approve_payload(pv), SUP), 200)
    assert approved["status"] == "ACTIVE"


def test_renewal_advances_expiry_and_adds_annual_fee(api):
    """PRD §3.6: "Approval drives the permit `RENEWAL_PENDING → ACTIVE`, advances
    `expires_at` to the next fiscal-year-end after the current `expires_at`, adds the
    full-year `permit_annual_fee_cents` to the permit's `fee_paid_cents` and the same
    amount to the zone's `fees_collected_cents`, and increments the permit's `version`
    by one."

    Design: Difficulty/non_linear_state_machine/permit_renewal_cycle_returns_to_active
    """
    zone, hh, permit = _issue_and_request_renewal(api)
    pv = validate_success(api.get_permit(permit["id"], SUP), 200)["version"]
    approved = validate_success(api.renew_approve_permit(permit["id"], renew_approve_payload(pv), SUP), 200)
    assert approved["expires_at"] == "2028-03-31T23:59:59.000Z"
    assert approved["fee_paid_cents"] == 22000  # 10000 issuance + 12000 full-year renewal


# --------------------------------------------------------------------------
# dual_variant_calc / refund_voluntary_vs_administrative_diverge
# --------------------------------------------------------------------------
def _two_permits_ready_to_refund(api):
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2, max_permits_per_household=2, permit_annual_fee_cents=12000)
    hh = register_household(api, zone["id"])
    verify_household_proof(api, hh["id"])
    va = add_vehicle(api, hh["id"], license_plate="DV1-A")
    vb = add_vehicle(api, hh["id"], license_plate="DV1-B")
    permit_a = issue_permit(api, zone["id"], hh["id"], va["id"])
    permit_b = issue_permit(api, zone["id"], hh["id"], vb["id"])
    set_clock(api, "2026-08-01T00:00:00Z")
    return zone, hh, permit_a, permit_b


def test_voluntary_refund_withholds_admin_fee(api):
    """PRD §3.6: "For a `VOLUNTARY` refund, the administrative fee of 2000 cents is
    withheld — the refund is the prorated unused amount minus 2000 cents, floored at
    zero."

    Design: Difficulty/dual_variant_calc/refund_voluntary_vs_administrative_diverge
    """
    zone, hh, permit_a, permit_b = _two_permits_ready_to_refund(api)
    refunded = validate_success(api.refund_permit(permit_a["id"], refund_payload("VOLUNTARY"), SUP), 200)
    assert refunded["refund_amount_cents"] == 5246  # prorated 7246 - 2000 admin fee
    assert refunded["refund_type"] == "VOLUNTARY"


def test_administrative_refund_withholds_no_admin_fee(api):
    """PRD §3.6: "For an `ADMINISTRATIVE` refund (a municipality-initiated surrender
    such as a zone decommission), the full prorated unused amount is refunded with no
    administrative fee withheld."

    Design: Difficulty/dual_variant_calc/refund_voluntary_vs_administrative_diverge
    """
    zone, hh, permit_a, permit_b = _two_permits_ready_to_refund(api)
    refunded = validate_success(api.refund_permit(permit_b["id"], refund_payload("ADMINISTRATIVE"), SUP), 200)
    assert refunded["refund_amount_cents"] == 7246  # full prorated, no admin fee
    assert refunded["refund_type"] == "ADMINISTRATIVE"


def test_refund_variants_differ_by_admin_fee(api):
    """PRD §3.6: "For a `VOLUNTARY` refund, the administrative fee of 2000 cents is
    withheld — the refund is the prorated unused amount minus 2000 cents, floored at
    zero."

    Design: Difficulty/dual_variant_calc/refund_voluntary_vs_administrative_diverge
    """
    zone, hh, permit_a, permit_b = _two_permits_ready_to_refund(api)
    ref_a = validate_success(api.refund_permit(permit_a["id"], refund_payload("VOLUNTARY"), SUP), 200)
    ref_b = validate_success(api.refund_permit(permit_b["id"], refund_payload("ADMINISTRATIVE"), SUP), 200)
    assert ref_b["refund_amount_cents"] - ref_a["refund_amount_cents"] == 2000


# --------------------------------------------------------------------------
# compensating_invariant / slot_count_conserved_across_issue_and_refund
# --------------------------------------------------------------------------
def test_zone_slot_count_conserved_after_issue_and_refund(api):
    """PRD §2.9: "After any issuance adds one and its compensating action — a refund,
    revocation, or expiry — removes one, the stored count stays exactly equal to that
    live count."

    Design: Difficulty/compensating_invariant/slot_count_conserved_across_issue_and_refund
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    api.refund_permit(permit["id"], refund_payload("ADMINISTRATIVE"), SUP)
    zone_after = validate_success(api.get_zone(zone["id"], SUP), 200)
    assert zone_after["active_permit_count"] == 0


def test_household_slot_count_conserved_after_refund(api):
    """PRD §2.9: "the identical definition applied to a single household's permits
    gives that household's `active_permit_count`. After any issuance adds one and its
    compensating action — a refund, revocation, or expiry — removes one, the stored
    count stays exactly equal to that live count."

    Design: Difficulty/compensating_invariant/slot_count_conserved_across_issue_and_refund
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    refunded = validate_success(api.refund_permit(permit["id"], refund_payload("ADMINISTRATIVE"), SUP), 200)
    assert refunded["status"] == "REFUNDED"
    hh_after = validate_success(api.get_household(hh["id"], SUP), 200)
    assert hh_after["active_permit_count"] == 0


# --------------------------------------------------------------------------
# compensating_invariant / fee_ledger_conserved_across_issue_and_refund
# --------------------------------------------------------------------------
def test_fee_ledger_collected_and_refunded_sides(api):
    """PRD §2.9: "`fees_collected_cents` is the sum of `fee_paid_cents` across every
    permit ever issued in the zone, including renewal collections; `fees_refunded_cents`
    is the sum of `refund_amount_cents` across the zone's permits whose status is
    `REFUNDED`."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_across_issue_and_refund
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2, permit_annual_fee_cents=12000)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])  # fee 10000
    set_clock(api, "2026-08-01T00:00:00Z")
    api.refund_permit(permit["id"], refund_payload("VOLUNTARY"), SUP)  # refund 5246
    zone_after = validate_success(api.get_zone(zone["id"], SUP), 200)
    assert zone_after["fees_collected_cents"] == 10000
    assert zone_after["fees_refunded_cents"] == 5246


def test_fee_ledger_net_conserved(api):
    """PRD §2.9: "The net revenue is `fees_collected_cents` minus `fees_refunded_cents`,
    and that net must equal the sum over all permits of each permit's `fee_paid_cents`
    minus its `refund_amount_cents`."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_across_issue_and_refund
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2, permit_annual_fee_cents=12000)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    set_clock(api, "2026-08-01T00:00:00Z")
    refunded = validate_success(api.refund_permit(permit["id"], refund_payload("VOLUNTARY"), SUP), 200)
    zone_after = validate_success(api.get_zone(zone["id"], SUP), 200)
    assert zone_after["fees_collected_cents"] - zone_after["fees_refunded_cents"] == 4754
    assert refunded["refund_amount_cents"] == 5246
    assert_fee_ledger_invariant(zone_after, [refunded])


# --------------------------------------------------------------------------
# resource_temporal_overlap / permit_closed_interval_shared_endpoint_overlap
# --------------------------------------------------------------------------
def _second_reviewed_app_same_vehicle(api):
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=3, max_permits_per_household=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"], plate="TO2-A")
    permit1 = issue_permit(api, zone["id"], hh["id"], veh["id"])
    a2 = create_application(api, zone["id"], hh["id"], veh["id"])
    review_application(api, a2["id"])
    return zone, hh, permit1, a2


def test_overlapping_permit_period_rejected(api):
    """PRD §3.5: "a vehicle may not hold two occupying permits whose closed validity
    intervals — from `issued_at` through `expires_at` inclusive — intersect, so a new
    permit's `issued_at` must be strictly after any prior permit's `expires_at`; a
    shared endpoint counts as an overlap and fails with `ERR_PERMIT_PERIOD_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_shared_endpoint_overlap
    """
    zone, hh, permit1, a2 = _second_reviewed_app_same_vehicle(api)
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(a2["id"], approve_payload(v), SUP)
    validate_error(resp, "ERR_PERMIT_PERIOD_OVERLAP", expected_status=409)


def test_first_permit_active_when_overlap_rejected(api):
    """PRD §3.5: "a new permit's `issued_at` must be strictly after any prior permit's
    `expires_at`; a shared endpoint counts as an overlap and fails with
    `ERR_PERMIT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_shared_endpoint_overlap
    """
    zone, hh, permit1, a2 = _second_reviewed_app_same_vehicle(api)
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(a2["id"], approve_payload(v), SUP)
    assert resp.status_code == 409
    fetched = validate_success(api.get_permit(permit1["id"], SUP), 200)
    assert fetched["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Corner/validations/renew_outside_window_returns_renewal_window_error
# --------------------------------------------------------------------------
def test_renew_outside_window_rejected(api):
    """PRD §3.6: "A resident requests renewal of an `ACTIVE` permit only within the
    renewal window — the current clock must be at or after the permit's `expires_at`
    minus 60 days. Outside that window the request fails with `ERR_RENEWAL_WINDOW`
    (HTTP 422)."

    Design: Corner/validations/renew_outside_window_returns_renewal_window_error
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])  # expires 2027-03-31; clock still 2026-05-01
    resp = api.renew_permit(permit["id"], _resident(hh))
    validate_error(resp, "ERR_RENEWAL_WINDOW", expected_status=422)


# --------------------------------------------------------------------------
# Corner/endpoints/transfer_creates_successor_conserves_count
# --------------------------------------------------------------------------
def test_transfer_creates_successor_and_conserves_count(api):
    """PRD §3.6: "Transfer drives the predecessor `ACTIVE → TRANSFERRED`, mints a
    successor `Permit` in status `ACTIVE` bound to the new vehicle that inherits the
    predecessor's `issued_at`, `expires_at`, and `fee_paid_cents`, and stores the
    successor's id on the predecessor as `transferred_to_permit_id`."

    Design: Corner/endpoints/transfer_creates_successor_conserves_count
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2, max_permits_per_household=2)
    hh = register_household(api, zone["id"])
    verify_household_proof(api, hh["id"])
    v1 = add_vehicle(api, hh["id"], license_plate="EP2-A")
    v2 = add_vehicle(api, hh["id"], license_plate="EP2-B")
    permit = issue_permit(api, zone["id"], hh["id"], v1["id"])
    successor = validate_success(api.transfer_permit(permit["id"], transfer_payload(v2["id"]), SUP), 201)
    assert successor["status"] == "ACTIVE"
    predecessor = validate_success(api.get_permit(permit["id"], SUP), 200)
    assert predecessor["status"] == "TRANSFERRED"
    assert predecessor["transferred_to_permit_id"] == successor["id"]
    zone_after = validate_success(api.get_zone(zone["id"], SUP), 200)
    assert zone_after["active_permit_count"] == 1


# --------------------------------------------------------------------------
# Corner/endpoints/permits_reverse_lookup_by_household
# --------------------------------------------------------------------------
def test_permits_reverse_lookup_by_household(api):
    """PRD §2.3: "List endpoints accept two query parameters, `limit` and `offset`."
    PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the total
    number of matching records before pagination), and `has_more` (true when records
    remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/permits_reverse_lookup_by_household
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    resp = api.list_permits(_resident(hh), params={"household_id": hh["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == permit["id"]


# --------------------------------------------------------------------------
# Corner/endpoints/list_permits_pagination_envelope
# --------------------------------------------------------------------------
def test_list_permits_pagination_envelope(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the total
    number of matching records before pagination), and `has_more` (true when records
    remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/list_permits_pagination_envelope
    """
    zone = create_zone(api)
    resp = api.list_permits(SUP, params={"zone_id": zone["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# --------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_stale_permit_version_returns_412
# --------------------------------------------------------------------------
def test_stale_permit_version_on_renew_approve_rejected(api):
    """PRD §2.8: "A transfer or a prior renewal-approval bumps the permit's `version`;
    if the permit's `version` has advanced since the supervisor last read it, the
    request is rejected with `ERR_PERMIT_VERSION_CONFLICT` (HTTP 412), so a renewal is
    never applied to a superseded permit view."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_permit_version_returns_412
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    permit = issue_permit(api, zone["id"], hh["id"], veh["id"])
    stale_permit_version = permit["version"]  # captured at issuance
    set_clock(api, "2027-02-15T00:00:00Z")
    validate_success(api.renew_permit(permit["id"], _resident(hh)), 200)  # bumps version
    resp = api.renew_approve_permit(permit["id"], renew_approve_payload(stale_permit_version), SUP)
    validate_error(resp, "ERR_PERMIT_VERSION_CONFLICT", expected_status=412)
