"""Entity creation/defaults/system fields, not-found and shape errors, FK filtering,
listing envelopes, RBAC denials, optimistic concurrency, and immediate consistency.

Covers the corner sections: entities, endpoints, errors, rbac, the OCC and
immediate-consistency cross-cutting instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    create_draft_order, create_stylist, create_fitting_room, create_bridal_party,
    create_booked_appointment, create_held_booking, create_order_with_plan,
)
from test_helpers.fixtures import CONSULTANT, MANAGER, CLERK, SEAMSTRESS, get_plan


# ─── Corner: entities ────────────────────────────────────────────────────────

def test_create_gown_order_returns_201_with_computed_quoted_total(api):
    """PRD §3.3: "A new order is created with `fulfillment_status` of `DRAFT` and
    `payment_status` of `UNPAID`." PRD §2.4: "`version` ... starts at the resource's
    creation". Base 180000, size 10, non-rush -> quoted_total_cents 180000.

    Design: Corner/entities/create_gown_order_returns_201_with_computed_quoted_total
    """
    res = api.create_gown_order(
        {"gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
         "standard_lead_days": 60}, CONSULTANT)
    order = validate_success(res, 201)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["quoted_total_cents"] == 180000
    assert order["version"] == 1


def test_create_gown_order_missing_base_price_rejected(api):
    """PRD §2.8: "Request-body validation (step 4) confirms that required fields are
    present ... Any such shape failure is rejected with `ERR_INVALID_REQUEST` and HTTP
    status 422." Omitting base_price_cents is rejected.

    Design: Corner/entities/create_gown_order_missing_base_price_returns_invalid_request
    """
    res = api.create_gown_order(
        {"gown_style_code": "ATELIER", "ordered_size": 10, "standard_lead_days": 60}, CONSULTANT)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_gown_order_not_found(api):
    """PRD §2.8: existence resolution "rejects on the first identifier that does not
    resolve to an existing row. Each unresolved reference maps to its own 404 code:
    ... `ERR_ORDER_NOT_FOUND`".

    Design: Corner/entities/get_gown_order_nonexistent_returns_not_found
    """
    res = api.get_gown_order("00000000-0000-4000-8000-000000000001", CONSULTANT)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_create_gown_order_default_is_rush_false(api):
    """PRD §3.3: "an optional `is_rush` flag that defaults to `false`." PRD §3.3: "A rush
    surcharge applies only when `is_rush` is true". Omitting is_rush leaves quoted at the
    bare base 180000 (no rush surcharge).

    Design: Corner/entities/create_gown_order_default_is_rush_false_applied
    """
    res = api.create_gown_order(
        {"gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
         "standard_lead_days": 60}, CONSULTANT)
    order = validate_success(res, 201)
    assert order["is_rush"] is False
    assert order["quoted_total_cents"] == 180000


def test_stylist_system_fields_minted_version_starts_at_one(api):
    """PRD §2.4: "`version` (integer): a system-managed counter that starts at the
    resource's creation". PRD §3.1: a stylist carries a `turnaround_buffer_minutes`
    supplied at creation. version starts at 1; the supplied buffer 20 round-trips.

    Design: Corner/entities/system_fields_generated_on_stylist_create_input_ignored
    """
    res = api.create_stylist({"full_name": "Sol", "turnaround_buffer_minutes": 20}, MANAGER)
    stylist = validate_success(res, 201)
    assert stylist["version"] == 1
    assert stylist["turnaround_buffer_minutes"] == 20


def test_create_fitting_room_capacity_below_one_rejected(api):
    """PRD §2.8: "a fitting room's `capacity` is at least 1 ... Any such shape failure is
    rejected with `ERR_INVALID_REQUEST` and HTTP status 422." capacity 0 is rejected.

    Design: Corner/entities/create_fitting_room_capacity_below_one_rejected
    """
    res = api.create_fitting_room({"room_label": "Bad", "capacity": 0}, MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_payment_is_immutable_ledger_record(api):
    """PRD §2.4: "A payment is an immutable ledger record once posted, so it carries only
    `id` and `created_at`". PRD §3.7: "The system sets the payment's `kind`: it is
    `DEPOSIT` while the deposit is still being covered" and "A posted payment is `SETTLED`".

    Design: Corner/entities/payment_immutable_entity_no_version_field
    """
    order, plan = create_order_with_plan(
        order_overrides={"gown_style_code": "ATELIER", "ordered_size": 10,
                         "base_price_cents": 180000, "standard_lead_days": 60},
        plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    res = api.post_payment(
        plan["id"], {"amount_cents": 90000, "expected_plan_version": plan["version"]}, CLERK)
    payment = validate_success(res, 201)
    assert payment["kind"] == "DEPOSIT"
    assert payment["settlement_status"] == "SETTLED"
    assert "version" not in payment
    assert "updated_at" not in payment


# ─── Corner: endpoints (listing + FK filtering) ──────────────────────────────

def test_list_gown_orders_paginated_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`." Two orders yield total_count 2, has_more false.

    Design: Corner/endpoints/list_gown_orders_paginated_envelope
    """
    create_draft_order(gown_style_code="A1", ordered_size=10, base_price_cents=100000,
                       standard_lead_days=30)
    create_draft_order(gown_style_code="A2", ordered_size=12, base_price_cents=120000,
                       standard_lead_days=30)
    data, meta = validate_paginated(api.list_gown_orders(MANAGER))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_filter_alteration_jobs_by_gown_order(api):
    """PRD §3.5: "Jobs may be listed and filtered by `gown_order_id` or `fitting_room_id`."
    Only the job on the first order is returned.

    Design: Corner/endpoints/filter_alteration_jobs_by_gown_order_fk
    """
    o1 = create_draft_order(gown_style_code="A1", ordered_size=10, base_price_cents=100000,
                            standard_lead_days=30)
    create_draft_order(gown_style_code="A2", ordered_size=12, base_price_cents=120000,
                       standard_lead_days=30)
    job = validate_success(api.create_alteration_job(
        {"gown_order_id": o1["id"], "estimated_labor_minutes": 30}, SEAMSTRESS), 201)
    data, meta = validate_paginated(api.list_alteration_jobs(SEAMSTRESS, params={"gown_order_id": o1["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["gown_order_id"] == o1["id"]


def test_list_payments_for_plan(api):
    """PRD §3.7: "Payments may be listed for a plan." A plan with one deposit returns that
    DEPOSIT payment.

    Design: Corner/endpoints/list_payments_for_plan_reverse_reachable
    """
    order, plan = create_order_with_plan(
        order_overrides={"gown_style_code": "ATELIER", "ordered_size": 10,
                         "base_price_cents": 180000, "standard_lead_days": 60},
        plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 90000, "expected_plan_version": plan["version"]}, CLERK), 201)
    data, meta = validate_paginated(api.list_payments(plan["id"], CLERK))
    assert meta["total_count"] == 1
    assert data[0]["kind"] == "DEPOSIT"


def test_filter_appointments_by_bridal_party(api):
    """PRD §3.2: "Appointments may later be listed and filtered by `stylist_id` or by
    `bridal_party_id`." Only the party-linked appointment is returned.

    Design: Corner/endpoints/filter_appointments_by_bridal_party_fk
    """
    party = create_bridal_party(party_name="Filter Wedding", event_date="2026-10-01T00:00:00.000Z")
    stylist = create_stylist(full_name="Wendy")
    appt = validate_success(api.create_appointment(
        {"stylist_id": stylist["id"], "appointment_type": "CONSULTATION",
         "start_at": "2026-07-11T10:00:00.000Z", "end_at": "2026-07-11T11:00:00.000Z",
         "bridal_party_id": party["id"]}, CONSULTANT), 201)
    data, meta = validate_paginated(api.list_appointments(CONSULTANT, params={"bridal_party_id": party["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["bridal_party_id"] == party["id"]


def test_filter_bookings_by_fitting_room(api):
    """PRD §3.2: "Bookings may be listed and filtered by `appointment_id` or
    `fitting_room_id`." Only the room's booking is returned.

    Design: Corner/endpoints/filter_fitting_room_bookings_by_room_fk
    """
    room = create_fitting_room(room_label="Suite F", capacity=3)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-12T10:00:00.000Z", end_at="2026-07-12T11:00:00.000Z")
    create_held_booking(room["id"], appt["id"], party_size=2,
                        slot_start_at="2026-07-12T10:00:00.000Z", slot_end_at="2026-07-12T11:00:00.000Z")
    data, meta = validate_paginated(api.list_fitting_room_bookings(CONSULTANT, params={"fitting_room_id": room["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["fitting_room_id"] == room["id"]


def test_filter_accessory_addons_by_order(api):
    """PRD §3.3: "Add-ons may be listed and filtered by `gown_order_id`." The order's veil
    add-on is returned.

    Design: Corner/endpoints/filter_accessory_addons_by_order_fk
    """
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    validate_success(api.create_accessory_addon(
        {"gown_order_id": order["id"], "accessory_type": "VEIL", "price_cents": 12000}, CONSULTANT), 201)
    data, meta = validate_paginated(api.list_accessory_addons(CONSULTANT, params={"gown_order_id": order["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["accessory_type"] == "VEIL"


def test_filter_payment_plans_by_order(api):
    """PRD §4: "GET `/payment-plans` | List payment plans; filter by gown order". The
    order's plan is returned.

    Design: Corner/endpoints/filter_payment_plans_by_order_fk
    """
    order, plan = create_order_with_plan(
        order_overrides={"gown_style_code": "ATELIER", "ordered_size": 10,
                         "base_price_cents": 180000, "standard_lead_days": 60},
        plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    data, meta = validate_paginated(api.list_payment_plans(CLERK, params={"gown_order_id": order["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["gown_order_id"] == order["id"]


def test_filter_gown_orders_by_party(api):
    """PRD §3.3: "Orders may be listed and filtered by `bridal_party_id` or
    `origin_appointment_id`." Only the party's member order is returned.

    Design: Corner/endpoints/filter_gown_orders_by_party_fk
    """
    party = create_bridal_party(party_name="Member Wedding", event_date="2026-11-01T00:00:00.000Z")
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60,
                               bridal_party_id=party["id"])
    data, meta = validate_paginated(api.list_gown_orders(CONSULTANT, params={"bridal_party_id": party["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["bridal_party_id"] == party["id"]


def test_filter_gown_orders_by_origin_appointment(api):
    """PRD §3.3: "Orders may be listed and filtered by `bridal_party_id` or
    `origin_appointment_id`." Only the order originating from the appointment is returned.

    Design: Corner/endpoints/filter_gown_orders_by_origin_appointment_fk
    """
    stylist = create_stylist(full_name="Yon")
    appt = validate_success(api.create_appointment(
        {"stylist_id": stylist["id"], "appointment_type": "CONSULTATION",
         "start_at": "2026-07-13T10:00:00.000Z", "end_at": "2026-07-13T11:00:00.000Z"}, CONSULTANT), 201)
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60,
                               origin_appointment_id=appt["id"])
    data, meta = validate_paginated(api.list_gown_orders(CONSULTANT, params={"origin_appointment_id": appt["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["origin_appointment_id"] == appt["id"]


def test_filter_alteration_jobs_by_fitting_room(api):
    """PRD §3.5: "Jobs may be listed and filtered by `gown_order_id` or `fitting_room_id`."
    The job referencing the room is returned.

    Design: Corner/endpoints/filter_alteration_jobs_by_fitting_room_fk
    """
    room = create_fitting_room(room_label="Suite G", capacity=2)
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    job = validate_success(api.create_alteration_job(
        {"gown_order_id": order["id"], "estimated_labor_minutes": 30, "fitting_room_id": room["id"]},
        SEAMSTRESS), 201)
    data, meta = validate_paginated(api.list_alteration_jobs(SEAMSTRESS, params={"fitting_room_id": room["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["fitting_room_id"] == room["id"]


def test_filter_bookings_by_appointment(api):
    """PRD §3.2: "Bookings may be listed and filtered by `appointment_id` or
    `fitting_room_id`." Only the appointment's booking is returned.

    Design: Corner/endpoints/filter_fitting_room_bookings_by_appointment_fk
    """
    room = create_fitting_room(room_label="Suite H", capacity=3)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-14T10:00:00.000Z", end_at="2026-07-14T11:00:00.000Z")
    create_held_booking(room["id"], appt["id"], party_size=1,
                        slot_start_at="2026-07-14T10:00:00.000Z", slot_end_at="2026-07-14T11:00:00.000Z")
    data, meta = validate_paginated(api.list_fitting_room_bookings(CONSULTANT, params={"appointment_id": appt["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["appointment_id"] == appt["id"]


def test_filter_appointments_by_stylist(api):
    """PRD §3.2: "Appointments may later be listed and filtered by `stylist_id` or by
    `bridal_party_id`." Only the stylist's appointment is returned.

    Design: Corner/endpoints/filter_appointments_by_stylist_fk
    """
    stylist = create_stylist(full_name="Ada")
    appt, _ = create_booked_appointment(
        stylist["id"], appointment_type="CONSULTATION",
        start_at="2026-07-15T10:00:00.000Z", end_at="2026-07-15T11:00:00.000Z")
    data, meta = validate_paginated(api.list_appointments(CONSULTANT, params={"stylist_id": stylist["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["stylist_id"] == stylist["id"]


def test_bridal_party_lead_order_self_reference_set(api):
    """PRD §3.1: a party "may optionally name an anchor order through `lead_gown_order_id`,
    the self-referential link to the bride's own `GownOrder` ... and may be assigned later
    through a party update that supplies `lead_gown_order_id`." The value round-trips.

    Design: Corner/endpoints/bridal_party_lead_order_self_reference_set
    """
    party = create_bridal_party(party_name="Anchor Wedding", event_date="2026-12-01T00:00:00.000Z")
    order = create_draft_order(gown_style_code="BRIDE", ordered_size=10, base_price_cents=250000,
                               standard_lead_days=60, bridal_party_id=party["id"])
    res = api.update_bridal_party(party["id"], {"lead_gown_order_id": order["id"]}, CONSULTANT)
    updated = validate_success(res, 200)
    assert updated["lead_gown_order_id"] == order["id"]


# ─── Corner: errors ──────────────────────────────────────────────────────────

def test_inactive_stylist_blocks_check_in(api):
    """PRD §3.2: checking a client in "requires the appointment to be `BOOKED` ... and the
    stylist to be `active` (else `ERR_STYLIST_INACTIVE`)." An appointment whose stylist was
    toggled inactive rejects check-in; the appointment stays BOOKED.

    Design: Corner/errors/stylist_inactive_blocks_check_in
    """
    stylist = create_stylist(full_name="Bee")
    appt, _ = create_booked_appointment(
        stylist["id"], appointment_type="CONSULTATION",
        start_at="2026-07-16T10:00:00.000Z", end_at="2026-07-16T11:00:00.000Z")
    validate_success(api.update_stylist(stylist["id"], {"active": False}, MANAGER), 200)

    res = api.check_in_appointment(appt["id"], CONSULTANT)
    validate_error(res, ApiErrorId.ERR_STYLIST_INACTIVE.value)
    appt_after = validate_success(api.get_appointment(appt["id"], CONSULTANT), 200)
    assert appt_after["status"] == "BOOKED"


def test_release_already_released_booking_rejected(api):
    """PRD §3.2: releasing a booking "requires the booking to be `HELD` (else
    `ERR_BOOKING_NOT_HELD`)". Releasing an already-RELEASED booking is rejected.

    Design: Corner/errors/release_already_released_booking_rejected
    """
    room = create_fitting_room(room_label="Suite I", capacity=2)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-17T10:00:00.000Z", end_at="2026-07-17T11:00:00.000Z")
    booking = create_held_booking(room["id"], appt["id"], party_size=1,
                                  slot_start_at="2026-07-17T10:00:00.000Z",
                                  slot_end_at="2026-07-17T11:00:00.000Z")
    validate_success(api.release_fitting_room_booking(booking["id"], CONSULTANT), 200)

    res = api.release_fitting_room_booking(booking["id"], CONSULTANT)
    validate_error(res, ApiErrorId.ERR_BOOKING_NOT_HELD.value)


def test_appointment_unknown_stylist_not_found(api):
    """PRD §2.8: existence resolution "rejects on the first identifier that does not
    resolve to an existing row. Each unresolved reference maps to its own 404 code:
    `ERR_STYLIST_NOT_FOUND`". A booking naming a non-existent stylist_id returns 404.

    Design: Corner/errors/fk_appointment_unknown_stylist_not_found
    """
    res = api.create_appointment(
        {"stylist_id": "00000000-0000-4000-8000-000000000099", "appointment_type": "CONSULTATION",
         "start_at": "2026-07-18T10:00:00.000Z", "end_at": "2026-07-18T11:00:00.000Z"}, CONSULTANT)
    validate_error(res, ApiErrorId.ERR_STYLIST_NOT_FOUND.value)


# ─── Corner: rbac ────────────────────────────────────────────────────────────

def test_consultant_cannot_receive_order(api):
    """PRD §4 endpoint table: POST `/gown-orders/{id}/receive` is authorized for
    `ShopManager` only. PRD §2.1: "A request whose role is authenticated but not permitted
    to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/consultant_cannot_receive_order
    """
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 2, "deposit_cents": 90000}, CLERK), 201)
    validate_success(api.submit_gown_order(order["id"], CONSULTANT), 200)

    res = api.receive_gown_order(order["id"], CONSULTANT)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_seamstress_cannot_post_payment(api):
    """PRD §4 endpoint table: POST `/payment-plans/{id}/payments` is authorized for
    `FinanceClerk, ShopManager`. PRD §2.1: an authenticated but unpermitted role is
    rejected with `ERR_FORBIDDEN_ROLE`.

    Design: Corner/rbac/seamstress_cannot_post_payment
    """
    order, plan = create_order_with_plan(
        order_overrides={"gown_style_code": "ATELIER", "ordered_size": 10,
                         "base_price_cents": 180000, "standard_lead_days": 60},
        plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    res = api.post_payment(
        plan["id"], {"amount_cents": 90000, "expected_plan_version": plan["version"]}, SEAMSTRESS)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_user_context_rejected(api):
    """PRD §2.1: "A request that omits either header, or carries a malformed value, is
    rejected with `ERR_MISSING_USER_CONTEXT`." A request with no auth headers is rejected.

    Design: Corner/rbac/missing_user_context_header_unauthenticated
    """
    res = api.create_gown_order(
        {"gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
         "standard_lead_days": 60}, {})
    validate_error(res, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


# ─── Corner: cross_cutting_complexity_layers (OCC) ───────────────────────────

def test_stale_plan_version_payment_rejected(api):
    """PRD §2.6: "If `expected_plan_version` does not equal the plan's current `version` at
    the time the write is processed, the request is rejected with `ERR_STALE_PLAN_VERSION`
    and HTTP status 412." A second payment carrying the pre-advance version is rejected;
    the ledger is unchanged.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_rejected_on_payment
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 5, "deposit_cents": 145000}, CLERK), 201)
    pv0 = plan["version"]
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 145000, "expected_plan_version": pv0}, CLERK), 201)

    res = api.post_payment(plan["id"], {"amount_cents": 29000, "expected_plan_version": pv0}, CLERK)
    validate_error(res, ApiErrorId.ERR_STALE_PLAN_VERSION.value)
    after = get_plan(plan["id"])
    assert after["amount_paid_cents"] == 145000


def test_correct_plan_version_payment_bumps_version(api):
    """PRD §3.7: "Each successful posting recomputes the plan's `amount_paid_cents` and
    `balance_due_cents` and increments the plan's `version` by one." PRD §3.7: covering the
    deposit advances the plan to ACTIVE. Create-time version 1 advances to 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 5, "deposit_cents": 145000}, CLERK), 201)
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 145000, "expected_plan_version": plan["version"]}, CLERK), 201)

    fresh = get_plan(plan["id"])
    assert fresh["version"] == 2
    assert fresh["status"] == "ACTIVE"


# ─── Corner: consistency_model ───────────────────────────────────────────────

def test_payment_reflects_paid_in_full_in_same_request(api):
    """PRD §2.7: "every cascade and every derived-field recompute completes atomically
    inside the request that triggered it, before the response is returned." PRD §3.7: a
    payment driving the balance to zero moves the plan to PAID_IN_FULL and the order to
    PAID_IN_FULL. An immediate plan GET already reflects balance 0.

    Design: Corner/consistency_model/immediate_consistency_payment_reflects_in_same_request
    """
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 2, "deposit_cents": 90000}, CLERK), 201)
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 90000, "expected_plan_version": plan["version"]}, CLERK), 201)
    fresh = get_plan(plan["id"])
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 90000, "expected_plan_version": fresh["version"]}, CLERK), 201)

    final = get_plan(plan["id"])
    assert final["balance_due_cents"] == 0
    assert final["status"] == "PAID_IN_FULL"
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["payment_status"] == "PAID_IN_FULL"
