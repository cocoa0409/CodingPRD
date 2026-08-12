"""Validation and error-catalog corner claims: schema violations, auth,
authorization/ownership, existence, safety gates, uniqueness, temporal gates,
fiscal gates (PRD §2.6, §3.1–§3.9).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    make_permit_holder_headers, build_user_headers,
    create_community, create_eligible_holder, create_holder, create_vehicle,
    create_full_equipment_lsv,
    create_draft_registration, finalize_inspection_for_registration,
    create_insurance, deposit, get_holder, set_clock,
    setup_active_registration, setup_route, setup_station, setup_reservation,
    setup_fleet_scenario, setup_fleet_vehicle, setup_dispatch,
    create_route_payload, create_route_pass_payload, create_vehicle_payload,
    create_insurance_policy_payload, create_charging_reservation_payload,
    create_fleet_dispatch_payload, create_registration_payload,
    create_violation_payload, create_inspection_payload,
    finalize_inspection_payload,
    COMMUNITY_ADMIN, INSPECTOR, OFFICER, ANON,
    ApiErrorId, NON_EXISTENT_UUID,
)


# ── validations section ──────────────────────────────────────────────────

def test_renewal_window_opens_exactly_sixty_days_before():
    """PRD §3.6: "A renewal opened while the registration is `ACTIVE` requires the
    current instant to fall within the renewal window: from `renewal_window_days`
    days before `expiry_date` through `expiry_date` itself, both bounds inclusive."
    PRD §3.1: "`renewal_window_days` sets how many days before expiry a renewal
    opens, with the opening boundary inclusive (default 60)"

    Design: Corner/validations/renewal_window_opens_exactly_sixty_days_before
    """
    ctx = setup_active_registration(
        community_name="C-RW1", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-RW1"})
    holder = ctx["holder"]
    reg = ctx["registration"]
    # expiry 2027-05-01 - 60 days = 2027-03-02T00:00:00Z (boundary included).
    set_clock("2027-03-02T00:00:00Z")
    hh = make_permit_holder_headers(holder["id"])
    renewed = validate_success(api_client.renew_registration(reg["id"], hh), 200)
    assert renewed["status"] == "RENEWAL_PENDING"


def test_renew_before_window_rejected():
    """PRD §3.6: "A renewal attempted outside both the window and the grace period
    is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422)."
    PRD §3.6: "A renewal opened while the registration is `ACTIVE` requires the
    current instant to fall within the renewal window: from `renewal_window_days`
    days before `expiry_date` through `expiry_date` itself, both bounds inclusive."

    Design: Corner/validations/renew_before_window_rejected
    """
    ctx = setup_active_registration(
        community_name="C-RW2", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-RW2"})
    holder = ctx["holder"]
    reg = ctx["registration"]
    # 2027-03-01 is one day before the window opens (expiry - 61 days).
    set_clock("2027-03-01T00:00:00Z")
    hh = make_permit_holder_headers(holder["id"])
    res = api_client.renew_registration(reg["id"], hh)
    validate_error(res, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED, expected_status=422)
    reg_after = get_success_data(
        api_client.get_registration(reg["id"], COMMUNITY_ADMIN))
    assert reg_after["status"] == "ACTIVE"


def test_invalid_role_header_unauthenticated():
    """PRD §2.1: "A request whose headers are missing, or whose `X-User-Role` is
    not one of these declared values, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401); the sole exception is permit-holder self-registration, which an
    `Anonymous` caller may perform without headers."
    PRD §2.6: "**Authentication** — `X-User-Role` and `X-User-ID` are present and
    the role is a declared role. Failure: `ERR_UNAUTHENTICATED` (HTTP 401).
    Permit-holder self-registration is exempt; `Anonymous` is allowed there."

    Design: Corner/validations/invalid_role_header_unauthenticated
    """
    community = create_community(name="C-AUTH")
    ghost = build_user_headers("test-ghost-1", "GhostRole")
    res = api_client.get_community(community["id"], ghost)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_permit_holder_cannot_create_route_forbidden():
    """PRD §2.6: "**Authorization** — the role is permitted for the endpoint, and
    for `PermitHolder`-role calls `X-User-ID` equals the owning holder of the
    target or payload resource. Failure: `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the route-designation endpoint lists "CommunityAdmin" as its only
    authorized role.

    Design: Corner/validations/permit_holder_cannot_create_route_forbidden
    """
    community = create_community(name="C-FB1")
    holder = create_holder(community["id"], full_name="H FB1",
                           birth_date="2010-05-01")
    res = api_client.create_route(
        create_route_payload(community["id"], name="Rogue", route_type="STREET",
                             allowed_vehicle_class="LSV_ALLOWED"),
        make_permit_holder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_vehicle_create_for_other_holder_forbidden():
    """PRD §2.1: "When `X-User-Role` is `PermitHolder`, `X-User-ID` is the `id` of
    the acting PermitHolder; ownership checks on any resource that references a
    PermitHolder compare the resource's holder foreign-key field to `X-User-ID`,
    and a PermitHolder-role call acting on a resource owned by another holder is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/validations/vehicle_create_for_other_holder_forbidden
    """
    community = create_community(name="C-FB2")
    holder_a = create_holder(community["id"], full_name="H A",
                             birth_date="2010-05-01")
    holder_b = create_holder(community["id"], full_name="H B",
                             birth_date="2010-05-01")
    res = api_client.create_vehicle(
        create_vehicle_payload(holder_b["id"]),
        make_permit_holder_headers(holder_a["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_activate_nonexistent_registration_not_found():
    """PRD §2.6: "**Existence** — every identifier referenced in the path and body
    exists. Identifiers are validated left to right: path parameters first, then
    body foreign keys in their declared field order. Failure: `ERR_NOT_FOUND`
    (HTTP 404)."
    PRD §2.6: "The pipeline short-circuits at the first stage that fails: the error
    raised by that stage is the one returned, and later stages are never
    consulted."

    Design: Corner/validations/activate_nonexistent_registration_not_found
    """
    community = create_community(name="C-NF2")
    holder = create_holder(community["id"], full_name="H NF2",
                           birth_date="2010-05-01")
    hh = make_permit_holder_headers(holder["id"])
    res = api_client.activate_registration(NON_EXISTENT_UUID, hh)
    # Existence (stage 4) precedes state (stage 5).
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_lsv_equipment_minimum_mirror_zero_rejected():
    """PRD §3.3: "At creation the system enforces class-specific equipment
    minimums: a `GOLF_CART` must declare headlights and brake lights; an `LSV` must
    declare headlights, brake lights, seatbelts, and at least one mirror. A vehicle
    falling short of its class minimum is rejected with `ERR_EQUIPMENT_MINIMUM`
    (HTTP 422)."

    Design: Corner/validations/lsv_equipment_minimum_mirror_zero_rejected
    """
    community = create_community(name="C-EQ")
    holder = create_eligible_holder(community["id"], full_name="H EQ",
                                    birth_date="2010-05-01")
    vehicle = create_vehicle(
        holder["id"], vehicle_type="LSV", seat_count=4,
        has_headlights=True, has_brake_lights=True, has_seatbelts=True,
        mirror_count=0)
    res = api_client.create_registration(
        create_registration_payload(vehicle["id"], holder["id"]),
        make_permit_holder_headers(holder["id"]))
    # mirror_count >= 1 is required for LSV.
    validate_error(res, ApiErrorId.ERR_EQUIPMENT_MINIMUM, expected_status=422)


def test_insurance_coverage_one_cent_below_minimum_rejected():
    """PRD §3.5: "The documented coverage must be at least the community's
    `min_liability_coverage_cents`, or creation is rejected with
    `ERR_INSURANCE_COVERAGE_LOW` (HTTP 422)."
    PRD §3.1: "`min_liability_coverage_cents` is the minimum liability coverage an
    insurance policy must document (default 10000000 cents)"

    Design: Corner/validations/insurance_coverage_one_cent_below_minimum_rejected
    """
    community = create_community(name="C-COV")
    holder = create_eligible_holder(community["id"], full_name="H COV",
                                    birth_date="2010-05-01")
    vehicle = create_vehicle(holder["id"])
    res = api_client.create_insurance_policy(
        create_insurance_policy_payload(holder["id"], vehicle["id"],
                                        policy_number="N-COV",
                                        liability_coverage_cents=9999999),
        make_permit_holder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_INSURANCE_COVERAGE_LOW, expected_status=422)


def test_duplicate_registration_same_year_rejected():
    """PRD §3.3: "Creation also enforces annual uniqueness: no second registration
    may exist for the same vehicle and `registration_year` while any earlier
    registration for that pair is not yet `REVOKED` — including one that is merely
    `EXPIRED`. A violating create is rejected with `ERR_DUPLICATE_REGISTRATION`
    (HTTP 409)."

    Design: Corner/validations/duplicate_registration_same_year_rejected
    """
    community = create_community(name="C-DUP")
    holder = create_eligible_holder(community["id"], full_name="H DUP",
                                    birth_date="2010-05-01")
    vehicle = create_vehicle(holder["id"])
    create_draft_registration(vehicle["id"], holder["id"], registration_year=2026)
    res = api_client.create_registration(
        create_registration_payload(vehicle["id"], holder["id"],
                                    registration_year=2026),
        make_permit_holder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_REGISTRATION, expected_status=409)


def test_slot_index_out_of_range_rejected():
    """PRD §3.8: "A holder books a charging reservation by naming the `station_id`,
    their `holder_id`, a `slot_index` identifying the bay (valid values run from 0
    to `slot_count` minus 1), and the window's `start_at` and `end_at`."
    PRD §2.6: "**Request-body schema** — all required fields are present, enum
    values are in range, integers fall within their declared ranges, and on every
    windowed payload the window end is strictly after its start. Failure:
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/slot_index_out_of_range_rejected
    """
    community = create_community(name="C-SLOT")
    holder = create_holder(community["id"], full_name="H SLOT",
                           birth_date="2010-05-01")
    station = setup_station(community["id"], name="S-SLOT", slot_count=2,
                            rate_cents_per_min=10)
    res = api_client.create_charging_reservation(
        create_charging_reservation_payload(
            station["id"], holder["id"], slot_index=2,
            start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z"),
        make_permit_holder_headers(holder["id"]))
    # slot_index must satisfy 0..slot_count-1; index == slot_count fails schema.
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_reservation_end_not_after_start_rejected():
    """PRD §2.10: "On every windowed payload, the window end must be strictly after
    the window start, or the request fails schema validation with
    `ERR_VALIDATION`."
    PRD §2.6: "**Request-body schema** — all required fields are present, enum
    values are in range, integers fall within their declared ranges, and on every
    windowed payload the window end is strictly after its start. Failure:
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/reservation_end_not_after_start_rejected
    """
    community = create_community(name="C-WIN")
    holder = create_holder(community["id"], full_name="H WIN",
                           birth_date="2010-05-01")
    station = setup_station(community["id"], name="S-WIN", slot_count=2,
                            rate_cents_per_min=10)
    res = api_client.create_charging_reservation(
        create_charging_reservation_payload(
            station["id"], holder["id"], slot_index=0,
            start_at="2026-06-01T11:00:00Z", end_at="2026-06-01T10:00:00Z"),
        make_permit_holder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


# ── endpoints section ────────────────────────────────────────────────────

def test_list_registrations_filtered_by_vehicle_id(community_admin_headers):
    """PRD §2.3: "Many list endpoints additionally accept an optional foreign-key
    filter restricting the listing to children of a given parent — for example
    `community_id` on the permit-holder, route, charging-station, and fleet-vehicle
    listings, `holder_id` on the vehicle, registration, insurance-policy,
    route-pass, charging-reservation, fleet-dispatch, and violation listings,
    `vehicle_id` on the registration, insurance-policy, and fleet-dispatch
    listings, `registration_id` on the inspection, route-pass, and violation
    listings, `route_id` on the route-pass listing, and `station_id` on the
    charging-reservation and fleet-vehicle listings."

    Design: Corner/endpoints/list_registrations_filtered_by_vehicle_id
    """
    community = create_community(name="C-FK")
    holder = create_eligible_holder(community["id"], full_name="H FK",
                                    birth_date="2010-05-01")
    v1 = create_vehicle(holder["id"])
    v2 = create_vehicle(holder["id"])
    create_draft_registration(v1["id"], holder["id"], registration_year=2026)
    create_draft_registration(v2["id"], holder["id"], registration_year=2026)
    res = api_client.list_registrations(community_admin_headers,
                                        params={"vehicle_id": v1["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert data[0]["vehicle_id"] == v1["id"]
    assert all(item["vehicle_id"] != v2["id"] for item in data)


def test_route_pass_on_decommissioned_route_rejected():
    """PRD §3.7: "A route's `designation_status` starts `DESIGNATED`.
    Decommissioning flips it to `DECOMMISSIONED` (terminal) and revokes every
    `ACTIVE` pass booked on it."
    PRD §3.7: "Booking requires the route to be `DESIGNATED` (otherwise
    `ERR_ROUTE_NOT_DESIGNATED`, HTTP 422), the registration to be `ACTIVE`
    (otherwise `ERR_REGISTRATION_NOT_ACTIVE`, HTTP 422), and the holder to be
    `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`)."

    Design: Corner/endpoints/route_pass_on_decommissioned_route_rejected
    """
    ctx = setup_active_registration(
        community_name="C-DEC", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-DEC"})
    holder = ctx["holder"]
    reg = ctx["registration"]
    route = setup_route(ctx["community"]["id"], name="R-DEC",
                        route_type="STREET", allowed_vehicle_class="LSV_ALLOWED")
    validate_success(api_client.decommission_route(route["id"], COMMUNITY_ADMIN), 200)
    res = api_client.create_route_pass(
        create_route_pass_payload(route["id"], reg["id"], holder["id"]),
        make_permit_holder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_ROUTE_NOT_DESIGNATED, expected_status=422)


# ── errors section ───────────────────────────────────────────────────────

def test_checkout_second_dispatch_fleet_unavailable():
    """PRD §3.8: "Checkout is performed by the holder at or after `shift_start` and
    requires the vehicle to be `AVAILABLE` — if it is not, the attempt is rejected
    with `ERR_FLEET_UNAVAILABLE` (HTTP 409)."
    PRD §2.4: "a fleet dispatch in `CHECKED_OUT` flips to `OVERDUE` once the clock
    moves past its `shift_end`"

    Design: Corner/errors/checkout_second_dispatch_fleet_unavailable
    """
    ctx = setup_fleet_scenario(community_name="C-FU", slot_count=1, rate=10)
    holder = ctx["holder"]
    fv = ctx["fleet_vehicle"]
    d1 = setup_dispatch(fv["id"], holder["id"],
                        shift_start="2026-05-01T09:00:00Z",
                        shift_end="2026-05-01T12:00:00Z")
    d2 = setup_dispatch(fv["id"], holder["id"],
                        shift_start="2026-05-01T13:00:00Z",
                        shift_end="2026-05-01T15:00:00Z")
    set_clock("2026-05-01T10:00:00Z")
    hh = make_permit_holder_headers(holder["id"])
    validate_success(api_client.checkout_fleet_dispatch(d1["id"], hh), 200)
    set_clock("2026-05-01T13:30:00Z")
    res = api_client.checkout_fleet_dispatch(d2["id"], hh)
    validate_error(res, ApiErrorId.ERR_FLEET_UNAVAILABLE, expected_status=409)
    d2_after = get_success_data(api_client.get_fleet_dispatch(d2["id"], COMMUNITY_ADMIN))
    assert d2_after["status"] == "BOOKED"
    d1_after = get_success_data(api_client.get_fleet_dispatch(d1["id"], COMMUNITY_ADMIN))
    assert d1_after["status"] == "OVERDUE"  # 12:00 passed while checked out


def test_activate_with_insufficient_wallet_rejected():
    """PRD §2.9: "Any debit is permitted when the balance equals the amount due —
    equality is sufficient — and is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP
    402) when the balance falls short."
    PRD §3.5: "the wallet must hold at least `total_due_cents` — for a fresh draft
    this equals the finalized fee, and a balance exactly equal to the amount due is
    sufficient (otherwise `ERR_INSUFFICIENT_FUNDS`, HTTP 402)."

    Design: Corner/errors/activate_with_insufficient_wallet_rejected
    """
    community = create_community(name="C-FIS", fleet_program_enabled=True)
    holder = create_eligible_holder(community["id"], full_name="H FIS",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 18999, holder["version"])
    vehicle = create_full_equipment_lsv(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    finalize_inspection_for_registration(registration["id"], score=90)
    create_insurance(holder["id"], vehicle["id"], policy_number="N-FIS")
    hh = make_permit_holder_headers(holder["id"])
    res = api_client.activate_registration(registration["id"], hh)
    # 18999 < 19000: one cent short fails.
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS, expected_status=402)
    reg_after = get_success_data(
        api_client.get_registration(registration["id"], COMMUNITY_ADMIN))
    assert reg_after["status"] == "DRAFT"
    assert get_holder(holder["id"])["wallet_balance_cents"] == 18999


def test_dispatch_requires_eligible_holder():
    """PRD §3.8: "A holder books a dispatch by naming the `vehicle_id`, their
    `holder_id`, and the shift window `shift_start` and `shift_end`; the holder
    must be `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`), and the closed-window
    overlap rule of §2.10 applies per vehicle."

    Design: Corner/errors/dispatch_requires_eligible_holder
    """
    community = create_community(name="C-ELG")
    holder = create_holder(community["id"], full_name="H ELG",
                           birth_date="2010-05-01")  # never verified
    station = setup_station(community["id"], name="S-ELG", slot_count=1,
                            rate_cents_per_min=10)
    fv = setup_fleet_vehicle(community["id"], station["id"], label="F-ELG")
    res = api_client.create_fleet_dispatch(
        create_fleet_dispatch_payload(fv["id"], holder["id"]),
        make_permit_holder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_HOLDER_NOT_ELIGIBLE, expected_status=422)


def test_license_class_none_rejected():
    """PRD §3.2: "Independently, a holder whose `driver_license_class` is `NONE`
    cannot be verified and is rejected with `ERR_LICENSE_CLASS_INSUFFICIENT` (HTTP
    422)."

    Design: Corner/errors/license_class_none_rejected
    """
    community = create_community(name="C-LIC")
    holder = create_holder(community["id"], full_name="H LIC",
                           birth_date="2010-05-01", driver_license_class="NONE")
    res = api_client.verify_eligibility(holder["id"], COMMUNITY_ADMIN)
    validate_error(res, ApiErrorId.ERR_LICENSE_CLASS_INSUFFICIENT, expected_status=422)
    after = get_holder(holder["id"])
    assert after["eligibility_status"] == "PENDING_VERIFICATION"
