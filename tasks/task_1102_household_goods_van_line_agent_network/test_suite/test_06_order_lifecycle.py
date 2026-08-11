"""Order lifecycle: book gates, spread window, weighment, dispatch, cancel (PRD 3.2, 3.4, 3.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    assert_move_order,
    assert_weight_ticket,
    book_additional_order,
    book_order,
    confirm_crew,
    create_agent,
    create_crew,
    create_order_payload,
    dispatch_order,
    elect_coverage,
    get_order,
    issue_estimate,
    record_original_weighment,
    register_order,
    set_clock,
    setup_booked_order,
    setup_network,
    setup_registered_order,
    staff_order,
    validate_error,
    validate_paginated,
    get_success_data,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


def _setup_book_blocked_on_estimate():
    """REGISTERED order: coverage elected, estimate ISSUED (never accepted),
    ORIGIN/HAULING/DESTINATION assignments CONFIRMED."""
    ctx = setup_registered_order(pricing_mode="NON_BINDING", mileage=1200)
    elect_coverage(ctx)
    issue_estimate(ctx, estimated_weight_lbs=8000)
    staff_order(ctx)
    return ctx


def test_book_blocked_until_estimate_accepted(api):
    """PRD section 3.4: "Booking requires the order to be `REGISTERED` (otherwise
    `ERR_ORDER_NOT_REGISTERED`) and then enforces three gates, evaluated in this
    written order: an `ACCEPTED` estimate exists whose kind matches the order's
    `pricing_mode` (else `ERR_NO_ACCEPTED_ESTIMATE`); an `ELECTED` valuation
    coverage exists (else `ERR_NO_VALUATION_COVERAGE`); and all four role
    assignments are `CONFIRMED` (else `ERR_AGENT_ROLES_INCOMPLETE` — the `BOOKING`
    leg is already `CONFIRMED` from registration, so the operative checks are
    `ORIGIN`, `HAULING`, and `DESTINATION`)."

    Design: Difficulty/cross_entity_state_dependency/book_gated_on_estimate_acceptance
    """
    ctx = _setup_book_blocked_on_estimate()
    resp = api.book_order(ctx["order"]["id"], ctx["booking_h"])
    validate_error(resp, ApiErrorId.ERR_NO_ACCEPTED_ESTIMATE)
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "REGISTERED", "the rejected book must not move the order"


def test_book_after_accept_computes_spread_window(api):
    """PRD section 3.4: "Booking computes the contractual delivery spread window
    from the order's mileage: under 500 miles allows 2 transit days followed by a
    2-day spread; 500 miles up to under 1500 allows 4 transit days and a 3-day
    spread; 1500 up to under 2500 allows 6 transit days and a 4-day spread; and
    2500 miles and above, up to the table's 999999 ceiling, allows 8 transit days
    and a 5-day spread. A mileage of exactly 500 selects the 500-to-1500 band, not
    the first band. The `earliest_delivery_date` is the pickup date plus the
    transit days, and the `latest_delivery_date` is the earliest delivery date
    plus the spread days."

    Design: Difficulty/cross_entity_state_dependency/book_gated_on_estimate_acceptance
    """
    ctx = _setup_book_blocked_on_estimate()
    accept_estimate(ctx)
    booked = book_order(ctx)
    assert booked["status"] == "BOOKED"
    # Mileage 1200 -> 4 transit days + 3 spread days from pickup 2026-06-10.
    assert booked["earliest_delivery_date"] == "2026-06-14T00:00:00Z", (
        f"earliest delivery must be pickup + 4 days, got {booked['earliest_delivery_date']}"
    )
    assert booked["latest_delivery_date"] == "2026-06-17T00:00:00Z", (
        f"latest delivery must be earliest + 3 days, got {booked['latest_delivery_date']}"
    )


def test_delivery_spread_mileage_band_boundary(api):
    """PRD section 3.4: "A mileage of exactly 500 selects the 500-to-1500 band,
    not the first band. The `earliest_delivery_date` is the pickup date plus the
    transit days, and the `latest_delivery_date` is the earliest delivery date
    plus the spread days."
    PRD section 3.4: "Booking computes the contractual delivery spread window from
    the order's mileage: under 500 miles allows 2 transit days followed by a 2-day
    spread; 500 miles up to under 1500 allows 4 transit days and a 3-day spread;
    1500 up to under 2500 allows 6 transit days and a 4-day spread; and 2500 miles
    and above, up to the table's 999999 ceiling, allows 8 transit days and a 5-day
    spread."

    Design: Corner/calculations/delivery_spread_mileage_band_boundary
    """
    o499 = setup_booked_order(pricing_mode="BINDING", mileage=499)
    # Both orders share one PUBLISHED tariff covering the pickup date — PRD 2.8
    # forbids a second published tariff whose window intersects the first.
    o500 = book_additional_order(o499, pricing_mode="BINDING", mileage=500)

    below = get_order(o499["order"]["id"])
    assert below["earliest_delivery_date"] == "2026-06-12T00:00:00Z"
    assert below["latest_delivery_date"] == "2026-06-14T00:00:00Z"

    at = get_order(o500["order"]["id"])
    assert at["earliest_delivery_date"] == "2026-06-14T00:00:00Z", (
        "mileage 500 must select the min-inclusive [500,1500) band"
    )
    assert at["latest_delivery_date"] == "2026-06-17T00:00:00Z"


def test_dispatch_before_pickup_date_rejected(api):
    """PRD section 3.4: "Dispatch is the hauling agent's act and is gated by four
    checks evaluated in this written order: the order is `BOOKED` (otherwise
    `ERR_TRANSITION_NOT_ALLOWED`); an `ORIGINAL` weight ticket exists on the order
    (else `ERR_WEIGHT_TICKET_REQUIRED`); every `CONFIRMED` origin-end crew
    assignment on the order has been `COMPLETED` (else
    `ERR_ORIGIN_SERVICES_INCOMPLETE`); and the logical clock has reached the
    order's `pickup_date` (else `ERR_PICKUP_DATE_NOT_REACHED`, HTTP 422)."
    PRD section 3.4: "Dispatch locks the elected coverage — the `ELECTED`
    valuation coverage becomes `LOCKED` with its `version` bumped — moves
    `billing_status` from `UNBILLED` to `PROVISIONALLY_BILLED` with
    `delivery_amount_due_cents` provisionally set to the accepted estimate's
    `estimated_charges_cents`, and lands the order in `IN_TRANSIT` with its
    `version` bumped."

    Design: Corner/validations/dispatch_before_pickup_date_rejected
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    record_original_weighment(ctx, net_weight_lbs=8000, weighed_at="2026-06-09T09:00:00Z")

    set_clock("2026-06-09T12:00:00Z")
    resp = api.dispatch_order(ctx["order"]["id"], ctx["hauling_h"])
    validate_error(resp, ApiErrorId.ERR_PICKUP_DATE_NOT_REACHED)

    set_clock("2026-06-10T00:00:00Z")
    dispatched = get_success_data(api.dispatch_order(ctx["order"]["id"], ctx["hauling_h"]))
    assert dispatched["status"] == "IN_TRANSIT", "dispatch at exactly pickup_date must pass"
    assert dispatched["billing_status"] == "PROVISIONALLY_BILLED"


def test_original_weighment_uniqueness(api):
    """PRD section 3.4: "Exactly one `ORIGINAL` ticket may exist per order: a
    second original weighment is rejected with `ERR_ORIGINAL_WEIGHT_EXISTS`, and
    any further weighment must come through the re-weigh program of §3.5."

    Design: Corner/validations/original_weighment_uniqueness
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    record_original_weighment(ctx, net_weight_lbs=8000)

    resp = api.create_weight_ticket(
        ctx["order"]["id"],
        {
            "scale_location": "SCALE-02",
            "weighed_at": "2026-06-10T09:30:00Z",
            "tare_weight_lbs": 14000,
            "gross_weight_lbs": 22100,
        },
        ctx["hauling_h"],
    )
    validate_error(resp, ApiErrorId.ERR_ORIGINAL_WEIGHT_EXISTS)

    data, meta = validate_paginated(
        api.list_weight_tickets(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 1, "the second original weighment must not be recorded"


def test_weight_ticket_net_weight_computed_and_immutable(api):
    """PRD section 3.4: "The ticket's `net_weight_lbs` is the gross weight minus
    the tare weight. Recording the original ticket makes it authoritative: the
    order's `authoritative_weight_ticket_id` is set to the new ticket,
    `actual_weight_lbs` is recomputed from it, and the order's `version` is
    bumped. On an original ticket the `ticket_kind` is `ORIGINAL` and both
    `reweigh_request_id` and `supersedes_ticket_id` are null."
    PRD section 2.4: "The `WeightTicket` resource is the single exception: as
    immutable scale evidence it carries only `id` and `created_at`, and both
    `updated_at` and `version` are absent from it."

    Design: Corner/entities/weight_ticket_net_weight_computed_and_immutable
    """
    ctx = setup_booked_order(pricing_mode="NON_BINDING", mileage=1200)
    ticket = record_original_weighment(
        ctx, tare_weight_lbs=14000, net_weight_lbs=9000
    )
    assert_weight_ticket(ticket)
    assert ticket["net_weight_lbs"] == 9000, "net must be gross minus tare (computed)"
    assert ticket["ticket_kind"] == "ORIGINAL"
    assert ticket["reweigh_request_id"] is None
    assert ticket["supersedes_ticket_id"] is None

    order = get_order(ctx["order"]["id"])
    assert order["actual_weight_lbs"] == 9000
    assert order["authoritative_weight_ticket_id"] == ticket["id"]


def test_agent_capability_and_suspension_gates(api):
    """PRD section 3.2: "The named agent must be `ACTIVE` — assigning to a
    `SUSPENDED` or `TERMINATED` agent is rejected with `ERR_AGENT_SUSPENDED` — and
    its `capabilities` must include the proposed role, otherwise the proposal
    fails with `ERR_AGENT_CAPABILITY_MISSING` (HTTP 422)."

    Design: Corner/validations/agent_capability_and_suspension_gates
    """
    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    origin_only = create_agent(["ORIGIN"])

    resp = api.create_agent_assignment(
        ctx["order"]["id"],
        {"agent_id": origin_only["id"], "role": "HAULING"},
        ctx["booking_h"],
    )
    validate_error(resp, ApiErrorId.ERR_AGENT_CAPABILITY_MISSING)

    data, meta = validate_paginated(
        api.list_agent_assignments(ADMIN, params={"order_id": ctx["order"]["id"], "role": "HAULING"})
    )
    assert meta["total_count"] == 0, "the capability-mismatched proposal must not persist"


def test_register_existence_error_precedes_tariff_referential(api):
    """PRD section 2.10: "Every request is evaluated against a fixed validation
    pipeline, and a request rejected at an earlier stage never reaches a later
    one."
    PRD section 2.10: "Existence — path-template resources are validated left to
    right, and body-referenced identifiers (such as `customer_id`, `tariff_id`,
    `agent_id`, `warehouse_id`, `claim_id`, and `revenue_statement_id`) must
    resolve to existing resources; the first missing identifier, scanning the path
    from left to right, yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD section 3.2: "The referenced tariff must be `PUBLISHED` and its effective
    window must cover the pickup date, otherwise registration is rejected with
    `ERR_TARIFF_NOT_PUBLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/register_existence_error_precedes_tariff_referential
    """
    from test_helpers import create_draft_tariff

    ctx = setup_network()
    draft = create_draft_tariff()

    # Both violations present: nonexistent customer AND a DRAFT tariff.
    resp = api.create_order(
        create_order_payload(NON_EXISTENT_UUID, draft["id"], pricing_mode="BINDING"),
        ctx["booking_h"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    data, meta = validate_paginated(
        api.list_orders(ADMIN, params={"customer_id": NON_EXISTENT_UUID})
    )
    assert meta["total_count"] == 0, "no order may be created by the rejected write"


def test_register_missing_tariff_also_yields_not_found(api):
    """PRD section 2.10: "Every request is evaluated against a fixed validation
    pipeline, and a request rejected at an earlier stage never reaches a later
    one."
    PRD section 2.10: "Existence — path-template resources are validated left to
    right, and body-referenced identifiers (such as `customer_id`, `tariff_id`,
    `agent_id`, `warehouse_id`, `claim_id`, and `revenue_statement_id`) must
    resolve to existing resources; the first missing identifier, scanning the path
    from left to right, yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD section 3.2: "The referenced tariff must be `PUBLISHED` and its effective
    window must cover the pickup date, otherwise registration is rejected with
    `ERR_TARIFF_NOT_PUBLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/register_existence_error_precedes_tariff_referential
    """
    ctx = setup_network()
    # Valid customer, but the tariff id does not exist: existence precedes the
    # published-tariff referential check.
    resp = api.create_order(
        create_order_payload(ctx["customer"]["id"], NON_EXISTENT_UUID, pricing_mode="BINDING"),
        ctx["booking_h"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_cancel_cascades_to_children_compensation(api):
    """PRD section 3.7: "Cancellation voids every `ISSUED` or `ACCEPTED` estimate
    into `VOIDED`, supersedes the `ELECTED` valuation coverage into `SUPERSEDED`,
    releases every `PROPOSED` or `CONFIRMED` assignment into `RELEASED`, cancels
    every `REQUESTED` or `CONFIRMED` crew with crew hours returned to the
    agent-date pool, leaves `billing_status` at `UNBILLED`, and lands the order in
    `CANCELLED` with its `version` bumped."
    PRD section 3.7: "Earlier, the booking agent or a `VanLineAdmin` may cancel
    from `REGISTERED` or `BOOKED` — from any other state the cancel is
    `ERR_TRANSITION_NOT_ALLOWED`."

    Design: Corner/state_machines/cancel_cascades_to_children_compensation
    """
    ctx = setup_booked_order(pricing_mode="BINDING", mileage=900)
    crew = create_crew(ctx, service_end="ORIGIN", start_hour=8, end_hour=10, crew_size=2)
    confirm_crew(ctx, crew["id"], service_end="ORIGIN")

    cancelled = get_success_data(api.cancel_order(ctx["order"]["id"], ctx["booking_h"]))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["billing_status"] == "UNBILLED"

    estimate = get_success_data(api.get_estimate(ctx["estimate"]["id"], ADMIN))
    assert estimate["status"] == "VOIDED"
    coverage = get_success_data(api.get_valuation_coverage(ctx["coverage"]["id"], ADMIN))
    assert coverage["status"] == "SUPERSEDED"
    for role in ("ORIGIN", "HAULING", "DESTINATION"):
        assignment = get_success_data(
            api.get_agent_assignment(ctx["assignments"][role]["id"], ADMIN)
        )
        assert assignment["status"] == "RELEASED", f"{role} assignment must be RELEASED"
    crew_after = get_success_data(api.get_crew_assignment(crew["id"], ADMIN))
    assert crew_after["status"] == "CANCELLED", (
        "the confirmed crew must be cancelled with its hours returned to the pool"
    )
