"""Role authorisation, shared reads and segregation of duties.

Every test here drives the caller's declared ``X-User-Role`` against an endpoint
whose authorised role list is fixed by PRD §4, or drives two settlement analysts
against the same settlement, and asserts the documented refusal.
"""

from test_helpers import (
    ANALYST_ONE,
    ANALYST_TWO,
    BALLROOM_C,
    EVENT_SERVICES,
    FACILITIES_PLANNER,
    NON_EXISTENT_UUID,
    SALES_MANAGER,
    SETTLEMENT_ANALYST,
    VENUE_ADMIN,
    ApiErrorId,
    assert_fields,
    make_analyst_headers,
    make_licensee_headers,
    read_booking,
    read_client,
    read_license,
    read_settlement,
    set_clock,
    setup_event_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# The Licensee is confined to its own paperwork
# --------------------------------------------------------------------------


def test_licensee_cannot_create_a_booking(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §2.11: "**Role authorization.** The acting role appears in the called endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`."

    Booking creation authorises SalesManager and VenueAdmin only, so the role gate refuses the
    Licensee ahead of the body-reference existence checks and the unknown client and space
    identifiers in the payload never matter.

    Design: Corner/rbac/licensee_cannot_create_bookings_or_publish_policy_windows
    """
    resp = api.create_booking(
        client_id=NON_EXISTENT_UUID,
        space_id=NON_EXISTENT_UUID,
        event_name="Self Serve Congress",
        event_class="LOCAL_EVENT",
        move_in_start_date="2027-05-01",
        show_start_date="2027-05-02",
        show_end_date="2027-05-03",
        move_out_end_date="2027-05-04",
        headers=make_licensee_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


def test_licensee_cannot_publish_a_policy_window(api):
    """PRD §3.1: "Finally, only a `VenueAdmin` publishes the **BookingPolicyWindow** rows that make the booking calendar a policy instrument rather than a queue."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/licensee_cannot_create_bookings_or_publish_policy_windows
    """
    resp = api.create_policy_window(
        event_class="LOCAL_EVENT",
        priority_rank=2,
        open_months_before=24,
        close_months_before=3,
        max_holds_per_booking=2,
        challenge_response_hours=72,
        rental_discount_pct=0.1,
        max_challenge_rounds=2,
        headers=make_licensee_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)

    _, meta = validate_paginated(api.list_policy_windows(headers=VENUE_ADMIN))
    assert meta["total_count"] == 0, f"refused publication must persist nothing: {meta}"


# --------------------------------------------------------------------------
# The FacilitiesPlanner owns the maintenance calendar and nothing else
# --------------------------------------------------------------------------


def test_facilities_planner_cannot_issue_a_license(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §2.11: "**Role authorization.** The acting role appears in the called endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`."

    Issuing a license authorises SalesManager only, so the planner is refused before the
    unresolvable license identifier in the path is examined.

    Design: Corner/rbac/facilities_planner_cannot_issue_licenses_or_order_event_services
    """
    resp = api.issue_license(NON_EXISTENT_UUID, headers=FACILITIES_PLANNER)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


def test_facilities_planner_cannot_order_event_services(api):
    """PRD §3.5: "An `EventServicesManager` orders event services against the booking, naming the `vendor_id`, the `service_category` being ordered — `UTILITIES`, `RIGGING`, `CLEANING` or `SECURITY`, with catering handled separately in §3.7 — and the billable `ordered_quantity`, which must be strictly greater than zero."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/facilities_planner_cannot_issue_licenses_or_order_event_services
    """
    resp = api.create_service_order(
        NON_EXISTENT_UUID,
        vendor_id=NON_EXISTENT_UUID,
        service_category="CLEANING",
        ordered_quantity=500,
        headers=FACILITIES_PLANNER,
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


# --------------------------------------------------------------------------
# The SalesManager sells dates but neither blacks them out nor closes the money
# --------------------------------------------------------------------------


def test_sales_manager_cannot_propose_a_maintenance_blackout(api):
    """PRD §3.10: "A `FacilitiesPlanner` proposes a **MaintenanceBlackout** against a space, supplying `space_id`, the `window_start_date` and `window_end_date` bracketing the unavailability, and the `project_kind` — `ROUTINE_MAINTENANCE` for ordinary facility work or `CAPITAL_PROJECT` for scheduled capital work."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/sales_manager_cannot_schedule_blackouts_or_open_settlements
    """
    resp = api.create_maintenance_blackout(
        space_id=NON_EXISTENT_UUID,
        window_start_date="2027-12-01",
        window_end_date="2027-12-10",
        project_kind="CAPITAL_PROJECT",
        headers=SALES_MANAGER,
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)

    _, meta = validate_paginated(api.list_maintenance_blackouts(headers=FACILITIES_PLANNER))
    assert meta["total_count"] == 0, f"refused proposal must persist nothing: {meta}"


def test_sales_manager_cannot_open_a_settlement(api):
    """PRD §3.9: "A `SettlementAnalyst` opens the **EventSettlement** for a booking, choosing the rental `basis` — `CONTRACTED` or `ACTUAL_USAGE` — which fixes how the rental charge will be computed and cannot be changed thereafter."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/sales_manager_cannot_schedule_blackouts_or_open_settlements
    """
    resp = api.create_settlement(NON_EXISTENT_UUID, basis="CONTRACTED", headers=SALES_MANAGER)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


# --------------------------------------------------------------------------
# The EventServicesManager works the show floor, not the queue or the close
# --------------------------------------------------------------------------


def test_event_services_manager_cannot_confirm_first_option(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §2.11: "**Role authorization.** The acting role appears in the called endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`."

    Confirming first option authorises SalesManager only, so the refusal arrives before the
    unresolvable hold identifier is examined.

    Design: Corner/rbac/event_services_manager_cannot_confirm_first_option_or_finalize_settlements
    """
    resp = api.confirm_first_option(NON_EXISTENT_UUID, headers=EVENT_SERVICES)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


def test_event_services_manager_cannot_finalize_a_settlement(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §2.11: "**Role authorization.** The acting role appears in the called endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`."

    Ordinary finalization authorises the SettlementAnalyst alone, so the desk that attests the
    usage feeding the figure is refused before the unresolvable settlement identifier is
    examined.

    Design: Corner/rbac/event_services_manager_cannot_confirm_first_option_or_finalize_settlements
    """
    resp = api.finalize_settlement(NON_EXISTENT_UUID, headers=EVENT_SERVICES)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


# --------------------------------------------------------------------------
# The SettlementAnalyst reads broadly and writes narrowly
# --------------------------------------------------------------------------


def test_settlement_analyst_cannot_open_the_show(api):
    """PRD §3.8: "**Opening the show floor** drives the booking `DEFINITE → IN_HOUSE` and belongs to the `EventServicesManager`."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/settlement_analyst_cannot_open_the_show_or_approve_service_orders
    """
    resp = api.open_show(NON_EXISTENT_UUID, headers=SETTLEMENT_ANALYST)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


def test_settlement_analyst_cannot_approve_a_service_order(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §2.11: "**Role authorization.** The acting role appears in the called endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`."

    Approving a service order authorises EventServicesManager only: the analyst prices the
    charges but never approves them, and the refusal precedes the unresolvable service-order
    identifier in the path.

    Design: Corner/rbac/settlement_analyst_cannot_open_the_show_or_approve_service_orders
    """
    resp = api.approve_service_order(NON_EXISTENT_UUID, headers=SETTLEMENT_ANALYST)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)


# --------------------------------------------------------------------------
# The VenueAdmin's breadth stops at the counterparty's signature
# --------------------------------------------------------------------------


def test_venue_admin_cannot_countersign_in_place_of_the_licensee(api):
    """PRD §3.4: "**Countersigning** drives `ISSUED → EXECUTED` and is reserved to the `Licensee` itself: the acting `X-User-ID` must equal the `client_id` of the license's booking, or the request is `ERR_NOT_RESOURCE_OWNER`."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    The same administrator still reaches license termination, whose refusal is the ordinary
    left-to-right path-existence code, so the countersignature refusal is specific to the
    counterparty act rather than a general lack of reach into licenses.

    Design: Corner/rbac/venue_admin_cannot_countersign_or_dispute_in_place_of_the_licensee
    """
    resp = api.countersign_license(NON_EXISTENT_UUID, headers=VENUE_ADMIN)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)

    reachable = api.terminate_license(NON_EXISTENT_UUID, headers=VENUE_ADMIN)
    validate_error(reachable, ApiErrorId.LICENSE_NOT_FOUND.value)


def test_venue_admin_cannot_dispute_in_place_of_the_licensee(api):
    """PRD §3.9: "**Disputing** drives `ISSUED → DISPUTED` and belongs to the `Licensee` alone, subject to the ownership check comparing `X-User-ID` to the booking's `client_id`."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    The same administrator still reaches arbitration finalisation, whose refusal is the ordinary
    left-to-right path-existence code, so the dispute refusal is specific to the counterparty
    act rather than a general lack of reach into settlements.

    Design: Corner/rbac/venue_admin_cannot_countersign_or_dispute_in_place_of_the_licensee
    """
    resp = api.dispute_settlement(
        NON_EXISTENT_UUID,
        dispute_reason="administrator speaking for the licensee",
        headers=VENUE_ADMIN,
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value)

    reachable = api.arbitrate_finalize_settlement(NON_EXISTENT_UUID, headers=VENUE_ADMIN)
    validate_error(reachable, ApiErrorId.SETTLEMENT_NOT_FOUND.value)


# --------------------------------------------------------------------------
# The booking row is the shared spine
# --------------------------------------------------------------------------


def test_booking_read_shared_by_five_internal_roles_and_the_owner(api):
    """PRD §2.1: "This ownership check is enforced on exactly five operations: countersigning an issued license, accepting an open license amendment, disputing an issued settlement, recording a deposit payment on a client, and reading a single booking by its identifier."

    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    All six roles read the same booking by identifier — the owning Licensee passes the ownership
    gate — and every one of them sees the identical computed money figures. The listing endpoint
    is narrower: the owner cannot enumerate bookings.

    Design: Corner/rbac/shared_booking_read_allowed_for_five_internal_roles_and_the_owner
    """
    world = setup_event_lifecycle(api, stage="booking", event_class="CONSUMER_SHOW")
    booking_id = world["booking"]["id"]
    licensee_headers = world["licensee_headers"]

    readers = {
        "VenueAdmin": VENUE_ADMIN,
        "SalesManager": SALES_MANAGER,
        "EventServicesManager": EVENT_SERVICES,
        "SettlementAnalyst": SETTLEMENT_ANALYST,
        "FacilitiesPlanner": FACILITIES_PLANNER,
        "Licensee": licensee_headers,
    }
    for role, headers in readers.items():
        data = validate_success(api.get_booking(booking_id, headers=headers), 200)
        assert_fields(
            data,
            contracted_rental_cents=363_600,
            deposit_required_cents=90_900,
            status="TENTATIVE",
            order_posture="OPEN",
        )
        assert data["id"] == booking_id, f"{role} read the wrong booking"

    listing = api.list_bookings(headers=licensee_headers)
    validate_error(listing, ApiErrorId.FORBIDDEN_ROLE.value)


# --------------------------------------------------------------------------
# Segregation of duties on settlement finalisation
# --------------------------------------------------------------------------


def test_settlement_issuer_cannot_finalize_the_settlement_it_issued(api):
    """PRD §2.12: "On a finalization attempt the acting `X-User-ID` is compared to `issued_by_user_id`; if they are equal, the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Both actors carry the SettlementAnalyst role, so the check is on `X-User-ID` rather than on
    role membership. The clock is already past `dispute_deadline_utc`, so the timing is
    impeccable and the only defect is that the first analyst issued the figure it is now signing
    off; the very same call from the second analyst succeeds and applies the deposit.

    Design: Corner/rbac/settlement_issuer_finalizing_the_same_settlement_rejected
    """
    world = setup_event_lifecycle(
        api,
        stage="settlement_issued",
        event_class="CONSUMER_SHOW",
        space=dict(BALLROOM_C),
        deposit_cents=1_300_000,
        booking={
            "event_name": "Sunbelt Boat Show",
            "move_in_start_date": "2027-06-09",
            "show_start_date": "2027-06-10",
            "show_end_date": "2027-06-12",
            "move_out_end_date": "2027-06-13",
        },
        settlement_basis="CONTRACTED",
        analyst_id=ANALYST_ONE,
        open_show_at="2027-06-09T08:00:00Z",
        close_at="2027-06-14T09:00:00Z",
    )
    settlement_id = world["settlement"]["id"]
    license_id = world["license"]["id"]
    booking_id = world["booking"]["id"]
    client_id = world["client"]["id"]

    set_clock(api, "2027-06-25T10:00:00Z")

    refused = api.finalize_settlement(settlement_id, headers=make_analyst_headers(ANALYST_ONE))
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value)

    still_issued = read_settlement(api, settlement_id)
    assert_fields(still_issued, status="ISSUED", finalized_by_user_id=None)
    assert_fields(read_license(api, license_id), deposit_held_cents=1_250_000)

    accepted = api.finalize_settlement(settlement_id, headers=make_analyst_headers(ANALYST_TWO))
    validate_success(accepted, 200)

    finalized = read_settlement(api, settlement_id)
    assert_fields(
        finalized,
        status="FINAL",
        issued_by_user_id=ANALYST_ONE,
        finalized_by_user_id=ANALYST_TWO,
        facility_service_fee_cents=350_000,
        deposit_applied_cents=1_250_000,
        grand_total_cents=4_100_000,
    )
    assert_fields(read_booking(api, booking_id), status="SETTLED")
    assert_fields(read_client(api, client_id), booking_standing="GOOD")
