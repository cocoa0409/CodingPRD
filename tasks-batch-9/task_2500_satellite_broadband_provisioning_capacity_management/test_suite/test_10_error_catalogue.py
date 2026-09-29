"""Error catalogue: each identifier is triggered through its PRD-stated condition.

Every test builds its whole precondition chain from PRD-declared endpoints, because
the server is restarted against an empty database before each test.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    ApiErrorId,
    acknowledge_disclosure,
    activate_subscription,
    assert_beam_congestion_band,
    authorize_payload,
    create_active_license,
    create_beam,
    create_cell,
    create_license,
    create_plan,
    create_provisional_license,
    create_roaming_authorization_payload,
    create_subscriber,
    create_subscription_payload,
    create_terminal_payload,
    coordinate_license,
    credit_decision_payload,
    create_order,
    get_beam,
    get_beam_version,
    get_cell,
    get_cell_version,
    get_license,
    get_order,
    get_subscriber,
    get_subscription,
    get_terminal,
    open_outage_event,
    plan_change_payload,
    prepare_installed_terminal,
    request_roaming,
    reset_clock_to_epoch,
    resolve_outage_event,
    set_clock,
    setup_acknowledged_subscription,
    setup_active_subscription,
    ship_terminal,
    suspend_license,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─────────────────────────── path-existence 404s ──────────────────────────

NOT_FOUND_CASES = [
    ("get_spectrum_license", ApiErrorId.ERR_SPECTRUM_LICENSE_NOT_FOUND),
    ("get_beam", ApiErrorId.ERR_BEAM_NOT_FOUND),
    ("get_service_cell", ApiErrorId.ERR_SERVICE_CELL_NOT_FOUND),
    ("get_subscriber", ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND),
    ("get_service_order", ApiErrorId.ERR_SERVICE_ORDER_NOT_FOUND),
    ("get_terminal", ApiErrorId.ERR_TERMINAL_NOT_FOUND),
    ("get_subscription", ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND),
    ("get_roaming_authorization", ApiErrorId.ERR_ROAMING_AUTHORIZATION_NOT_FOUND),
    ("get_outage_event", ApiErrorId.ERR_OUTAGE_EVENT_NOT_FOUND),
    ("get_outage_credit", ApiErrorId.ERR_OUTAGE_CREDIT_NOT_FOUND),
]


@pytest.mark.parametrize(
    "reader_name,expected_error_id",
    NOT_FOUND_CASES,
    ids=[name for name, _ in NOT_FOUND_CASES],
)
def test_unknown_path_id_returns_the_entity_specific_not_found_code(
    api, agent_headers, reader_name, expected_error_id
):
    """The same unknown UUID yields a different 404 identifier per collection.

    PRD §2.11: "**Path existence** — every id embedded in the URL resolves, validated left to right, so an outer id that does not exist is reported before an inner one is examined."
    PRD §2.11: "HTTP 404, with the identifier naming the missing type: `ERR_SPECTRUM_LICENSE_NOT_FOUND`, `ERR_BEAM_NOT_FOUND`, `ERR_SERVICE_CELL_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_ROAMING_AUTHORIZATION_NOT_FOUND`, `ERR_OUTAGE_EVENT_NOT_FOUND`, `ERR_OUTAGE_CREDIT_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_code_for_every_entity
    """
    # Only the clock has been set; the database is otherwise empty, so the
    # all-zero UUID exists in no collection.
    reset_clock_to_epoch()

    response = getattr(api, reader_name)(NON_EXISTENT_UUID, agent_headers)

    error = validate_error(response, expected_error_id)
    assert error["message"].strip(), (
        f"{reader_name} must return a non-empty message alongside {expected_error_id}"
    )


# ──────────────────────── terminal serial uniqueness ──────────────────────

def test_reusing_a_terminal_serial_returns_duplicate_terminal_serial(
    api, logistics_headers
):
    """A second shipment on an existing serial is the one collision with its own 409.

    PRD §3.4: "A serial number that already exists on another terminal is refused with `ERR_DUPLICATE_TERMINAL_SERIAL` rather than with the generic malformed-request error that other duplicate codes produce."

    Design: Corner/errors/reusing_a_terminal_serial_returns_duplicate_terminal_serial
    """
    reset_clock_to_epoch()
    subscriber = create_subscriber(index=1)
    first = ship_terminal(subscriber["id"], index=1)  # serial TRM-0001, SHIPPED

    response = api.create_terminal(
        create_terminal_payload(
            subscriber_id=subscriber["id"],
            serial_number="TRM-0001",
            warranty_expires_at="2030-01-01T00:00:00Z",
        ),
        logistics_headers,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_TERMINAL_SERIAL)

    terminals, meta = validate_paginated(api.list_terminals(logistics_headers))
    assert meta["total_count"] == 1, (
        f"the rejected create must leave exactly one Terminal row, got {meta['total_count']}"
    )
    assert terminals[0]["id"] == first["id"], "the surviving row must be the first terminal"
    stored = get_terminal(first["id"])
    assert stored["warranty_expires_at"].startswith("2028-08-01T00:00:00"), (
        "the first terminal's warranty_expires_at must be unchanged by the rejected "
        f"create, got {stored['warranty_expires_at']}"
    )


# ───────────────────── ordering against a suspended beam ──────────────────

def test_ordering_on_a_beam_suspended_by_a_refused_filing_returns_beam_suspended(
    api, agent_headers
):
    """A refused coordination puts the beam out of service, so filing is refused.

    PRD §3.1: "`REFUSED` on a licence in `PENDING_COORDINATION` moves `license_state` from `PENDING_COORDINATION` to the terminal state `REFUSED`, sets `coordination_state` to `REFUSED`, and — this is the divergent part — puts every beam that names this licence out of service by moving its `beam_state` from `ACTIVE` to `SUSPENDED`."
    PRD §3.3: "If the governing beam is `SUSPENDED`, the filing is refused with `ERR_BEAM_SUSPENDED` regardless of which branch it would otherwise have taken."

    Design: Corner/errors/ordering_service_on_a_beam_suspended_by_a_refused_filing_returns_beam_suspended
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_license(jurisdiction_code="US-CA", in_motion_permitted=True)
    beam = create_beam(
        license_record["id"], forward_capacity_mbps=100, oversubscription_limit=4.0
    )
    # max 2 slots and an empty waitlist, so only the beam check can reject the filing.
    cell = create_cell(beam["id"], jurisdiction_code="US-CA", max_active_terminals=2)
    plan = create_plan()
    subscriber = create_subscriber(index=1, jurisdiction_code="US-CA")
    coordinate_license(
        license_record["id"], outcome="REFUSED", coordination_note="neighbour objection upheld"
    )

    response = api.create_service_order(
        {
            "subscriber_id": subscriber["id"],
            "service_cell_id": cell["id"],
            "requested_plan_id": plan["id"],
        },
        agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_BEAM_SUSPENDED)

    assert get_beam(beam["id"])["beam_state"] == "SUSPENDED", (
        "the refused coordination must have driven the beam to SUSPENDED"
    )
    _, meta = validate_paginated(
        api.list_service_orders(agent_headers, params={"service_cell_id": cell["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused filing must create no order, got {meta['total_count']}"
    )
    stored_cell = get_cell(cell["id"])
    assert stored_cell["reserved_slot_count"] == 0, "no slot may be reserved"
    assert stored_cell["waitlist_depth"] == 0, "no waitlist entry may be created"
    assert stored_cell["availability_state"] == "CLOSED", (
        "a cell whose beam is SUSPENDED advertises CLOSED, got "
        f"{stored_cell['availability_state']}"
    )
    assert get_subscriber(subscriber["id"])["account_state"] == "PROSPECT", (
        "the refused filing must leave the account in PROSPECT"
    )


# ───────────────────────── jurisdiction at activation ─────────────────────

def test_activating_a_subscriber_from_another_jurisdiction_is_refused(api, agent_headers):
    """The jurisdiction gate lives on activation, not on ordering.

    PRD §3.5: "The subscriber's `jurisdiction_code` must equal the activating cell's `jurisdiction_code`, or the attempt is refused with `ERR_JURISDICTION_NOT_PERMITTED`."

    Design: Corner/errors/activating_a_subscriber_from_another_jurisdiction_returns_jurisdiction_not_permitted
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license(
        jurisdiction_code="US-CA", in_motion_permitted=True
    )
    beam = create_beam(
        license_record["id"], forward_capacity_mbps=100, oversubscription_limit=4.0
    )
    cell = create_cell(beam["id"], jurisdiction_code="US-CA", max_active_terminals=1)
    plan = create_plan()
    # The account is on file in US-NV while the serving cell covers US-CA.
    subscriber = create_subscriber(
        index=1,
        jurisdiction_code="US-NV",
        email="nv1@example.com",
        full_name="Nevada One",
    )
    order = create_order(subscriber["id"], cell["id"], plan["id"])
    terminal = prepare_installed_terminal(subscriber["id"], index=1)
    cell_version = get_cell_version(cell["id"])

    response = api.create_subscription(
        create_subscription_payload(
            service_order_id=order["id"],
            terminal_id=terminal["id"],
            expected_service_cell_version=cell_version,
        ),
        agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_PERMITTED)

    _, meta = validate_paginated(
        api.list_subscriptions(agent_headers, params={"service_order_id": order["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no subscription may be created, got {meta['total_count']}"
    )
    assert get_order(order["id"])["order_state"] == "RESERVED", (
        "the order must still hold its reservation"
    )
    stored_cell = get_cell(cell["id"])
    assert stored_cell["committed_terminal_count"] == 0, (
        "the hold must not have become a commitment"
    )
    assert stored_cell["reserved_slot_count"] == 1, "the slot must stay reserved"
    assert float(get_beam(beam["id"])["weighted_sold_mbps"]) == 0, (
        "no megabits may be sold on the beam"
    )


# ───────────────────── provisional grant blocks authorisation ─────────────

def test_authorizing_under_a_provisional_filing_returns_spectrum_not_coordinated(
    api, agent_headers
):
    """A provisional grant is live but uncoordinated, so the coordination gate fires.

    PRD §3.1: "The beams radiate, but network authorisation of individual subscribers is still refused with `ERR_SPECTRUM_NOT_COORDINATED`, because the coordination gate is independent of the liveness gate."
    PRD §3.5: "In both modes the subscription's `service_state` must be `PENDING_ACTIVATION` or `ACTIVE` and its `authorization_state` must be `UNAUTHORIZED` (otherwise `ERR_SUBSCRIPTION_STATE_INVALID`); its `disclosure_ack_state` must be `ACKNOWLEDGED` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); the governing licence's `license_state` must be `ACTIVE` (otherwise `ERR_LICENSE_NOT_ACTIVE`); that licence's `coordination_state` must be `COORDINATED` (otherwise `ERR_SPECTRUM_NOT_COORDINATED`); and the beam's `beam_state` must be `ACTIVE` (otherwise `ERR_BEAM_SUSPENDED`)."

    Design: Corner/errors/authorizing_under_a_provisional_filing_returns_spectrum_not_coordinated
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_provisional_license(
        jurisdiction_code="US-CA", in_motion_permitted=True
    )
    beam = create_beam(
        license_record["id"], forward_capacity_mbps=100, oversubscription_limit=4.0
    )
    cell = create_cell(beam["id"], jurisdiction_code="US-CA", max_active_terminals=1)
    plan = create_plan()
    subscriber = create_subscriber(index=1, jurisdiction_code="US-CA")
    order = create_order(subscriber["id"], cell["id"], plan["id"])
    terminal = prepare_installed_terminal(subscriber["id"], index=1)
    subscription = activate_subscription(
        order["id"], terminal["id"], service_cell_id=cell["id"]
    )
    # Every other authorisation gate is satisfied, so only the coordination gate can fail.
    acknowledge_disclosure(
        subscription["id"],
        subscriber["id"],
        license_record["consumer_disclosure_version"],
    )

    response = api.authorize_subscription(
        subscription["id"], authorize_payload("FIXED"), agent_headers
    )

    validate_error(response, ApiErrorId.ERR_SPECTRUM_NOT_COORDINATED)

    stored_license = get_license(license_record["id"])
    assert stored_license["license_state"] == "ACTIVE", (
        "a provisional grant leaves the licence ACTIVE"
    )
    assert stored_license["coordination_state"] == "UNCOORDINATED", (
        "a provisional grant deliberately leaves coordination open"
    )
    stored = get_subscription(subscription["id"])
    assert stored["authorization_state"] == "UNAUTHORIZED", (
        "the refused authorisation must not move the authorisation dimension"
    )
    assert stored["service_state"] == "PENDING_ACTIVATION", (
        "the refused authorisation must not advance the provisioning dimension"
    )
    assert stored["disclosure_ack_state"] == "ACKNOWLEDGED", (
        "the acknowledgement recorded during setup must survive"
    )


# ──────────────────── planned maintenance credit ineligible ───────────────

def test_submitting_a_planned_maintenance_credit_returns_credit_not_eligible(
    api, agent_headers
):
    """A long planned-maintenance window drafts a 0-cent credit that can never ship.

    PRD §3.8: "It then computes `credit_eligible`, which is true only when the `cause` is anything other than `PLANNED_MAINTENANCE` **and** `outage_minutes` is at least 30 — a shorter blip is beneath the service-level floor."
    PRD §3.8: "The cause factor is 0.5 for `WEATHER_RAIN_FADE`, 1.0 for `EQUIPMENT_FAILURE`, 1.0 for `SPECTRUM_INTERFERENCE` and 0.0 for `PLANNED_MAINTENANCE`."
    PRD §3.8: "They sit in `DRAFT` forever, visible for audit, refused at submission with `ERR_CREDIT_NOT_ELIGIBLE`."
    PRD §3.8: "It is legal only from `credit_state` `DRAFT`, refusing anything else with `ERR_CREDIT_STATE_INVALID`; it additionally requires the credit's event to be `RESOLVED` and that event's `credit_eligible` to be true, refusing an ineligible event with `ERR_CREDIT_NOT_ELIGIBLE`."

    Design: Corner/errors/submitting_a_planned_maintenance_credit_returns_credit_not_eligible
    """
    env = setup_active_subscription()  # ACTIVE + AUTHORIZED_FIXED, activated at the epoch
    set_clock("2026-08-02T06:00:00Z")
    event = open_outage_event(
        env["beam"]["id"],
        cause="PLANNED_MAINTENANCE",
        severity="FULL_OUTAGE",
        started_at="2026-08-02T00:00:00Z",
    )
    resolved = resolve_outage_event(event["id"], "2026-08-02T01:00:00Z")

    assert resolved["outage_minutes"] == 60, (
        f"a one-hour window is 60 whole minutes, got {resolved['outage_minutes']}"
    )
    assert resolved["credit_eligible"] is False, (
        "PLANNED_MAINTENANCE is never credit eligible"
    )
    assert resolved["generated_credit_count"] == 1, (
        "the drafting gate is the 30-minute duration alone, so one row is drafted, got "
        f"{resolved['generated_credit_count']}"
    )

    credits, meta = validate_paginated(
        api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
    )
    assert meta["total_count"] == 1, f"exactly one credit was drafted, got {meta['total_count']}"
    credit = credits[0]
    assert credit["provisional_credit_cents"] == 0, (
        "a zero cause multiplier drafts the credit at 0 cents, got "
        f"{credit['provisional_credit_cents']}"
    )

    response = api.submit_outage_credit(credit["id"], agent_headers)

    validate_error(response, ApiErrorId.ERR_CREDIT_NOT_ELIGIBLE)

    stored = validate_success(api.get_outage_credit(credit["id"], agent_headers))
    assert stored["credit_state"] == "DRAFT", "the refused submission leaves the credit DRAFT"
    assert stored["provisional_credit_cents"] == 0, "the provisional amount stays 0 cents"
    assert not stored.get("submitted_by_user_id"), (
        "no submitting operator may be stamped on a refused submission"
    )
    subscriber = get_subscriber(env["subscriber"]["id"])
    assert subscriber["pending_credit_cents"] == 0, (
        "a 0-cent draft moves no money into the pending ledger"
    )
    assert subscriber["credit_balance_cents"] == 0, "no balance may be credited"


# ─────────────────── re-authorising an authorised subscription ────────────

def test_authorizing_an_already_authorized_subscription_is_refused(api, agent_headers):
    """Authorisation is legal only from UNAUTHORIZED, so the second call is refused.

    PRD §3.5: "In both modes the subscription's `service_state` must be `PENDING_ACTIVATION` or `ACTIVE` and its `authorization_state` must be `UNAUTHORIZED` (otherwise `ERR_SUBSCRIPTION_STATE_INVALID`); its `disclosure_ack_state` must be `ACKNOWLEDGED` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); the governing licence's `license_state` must be `ACTIVE` (otherwise `ERR_LICENSE_NOT_ACTIVE`); that licence's `coordination_state` must be `COORDINATED` (otherwise `ERR_SPECTRUM_NOT_COORDINATED`); and the beam's `beam_state` must be `ACTIVE` (otherwise `ERR_BEAM_SUSPENDED`)."

    Design: Corner/errors/authorizing_an_already_authorized_subscription_returns_subscription_state_invalid
    """
    env = setup_active_subscription(authorization_mode="FIXED")

    response = api.authorize_subscription(
        env["subscription"]["id"], authorize_payload("FIXED"), agent_headers
    )

    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_STATE_INVALID)

    stored = get_subscription(env["subscription"]["id"])
    assert stored["authorization_state"] == "AUTHORIZED_FIXED", (
        "the first authorisation must still stand"
    )
    assert stored["service_state"] == "ACTIVE", "the provisioning dimension must stay ACTIVE"
    beam = get_beam(env["beam"]["id"])
    assert float(beam["weighted_sold_mbps"]) == 200, (
        "the refused call must not double-count the subscription's megabits, got "
        f"{beam['weighted_sold_mbps']}"
    )
    assert float(beam["oversubscription_ratio"]) == 2.0, (
        f"200 Mbps over 100 Mbps of forward capacity is 2.0, got {beam['oversubscription_ratio']}"
    )


# ──────────────────── resubmitting a REQUESTED authorisation ──────────────

def test_resubmitting_a_still_requested_roaming_authorization_is_refused(
    api, agent_headers
):
    """Resubmission closes a NEEDS_INFO round, so it is refused from REQUESTED.

    PRD §3.7: "Resubmitting from any state other than `NEEDS_INFO` is refused with `ERR_ROAMING_STATE_INVALID`."

    Design: Corner/errors/resubmitting_a_roaming_request_that_is_still_requested_returns_roaming_state_invalid
    """
    env = setup_active_subscription()
    request = request_roaming(
        env["subscription"]["id"],
        mode="ROAM_TEMPORARY",
        target_jurisdiction_code="US-CA",
        effective_from="2026-08-05T00:00:00Z",
        effective_until="2026-08-06T00:00:00Z",
    )
    assert request["auth_state"] == "REQUESTED", "setup must leave the review untouched"

    response = api.resubmit_roaming_authorization(
        request["id"],
        {
            "effective_from": "2026-08-09T00:00:00Z",
            "effective_until": "2026-08-10T00:00:00Z",
        },
        agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_ROAMING_STATE_INVALID)

    stored = validate_success(api.get_roaming_authorization(request["id"], agent_headers))
    assert stored["auth_state"] == "REQUESTED", "the refused resubmission changes no state"
    assert stored["effective_from"].startswith("2026-08-05T00:00:00"), (
        f"the stored window start must not be overwritten, got {stored['effective_from']}"
    )
    assert stored["effective_until"].startswith("2026-08-06T00:00:00"), (
        f"the stored window end must not be overwritten, got {stored['effective_until']}"
    )
    assert stored["info_round_count"] == 0, (
        f"no information round was opened, got {stored['info_round_count']}"
    )
    assert not stored.get("decision_note"), "no note may be recorded"


# ────────────────────────── deciding a DRAFT credit ───────────────────────

def test_deciding_a_draft_credit_returns_credit_state_invalid(
    api, agent_headers, compliance_headers
):
    """The review workflow cannot be short-circuited past submission.

    PRD §2.11: "**Credit review state** — `credit_state` permits the requested action; submission requires `DRAFT`, decision requires `SUBMITTED`."
    PRD §3.8: "It is legal only from `SUBMITTED`, and the deciding operator's `X-User-ID` must differ from the credit's `submitted_by_user_id`, or the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "Take the plan's `monthly_fee_cents`, multiply it by the event's `outage_minutes` divided by a nominal billing month of 43,200 minutes — thirty days of minutes — then multiply by the multiplier."
    PRD §3.8: "Round that product half up to whole cents, and take the smaller of it and the cap."

    Design: Corner/errors/deciding_a_draft_credit_returns_credit_state_invalid
    """
    env = setup_active_subscription()  # plan monthly_fee_cents 9900, activated at the epoch
    set_clock("2026-08-02T06:00:00Z")
    event = open_outage_event(
        env["beam"]["id"],
        cause="EQUIPMENT_FAILURE",
        severity="FULL_OUTAGE",
        started_at="2026-08-02T00:00:00Z",
    )
    resolve_outage_event(event["id"], "2026-08-02T01:00:00Z")

    credits, meta = validate_paginated(
        api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
    )
    assert meta["total_count"] == 1, f"one credit was drafted, got {meta['total_count']}"
    credit = credits[0]
    assert credit["credit_state"] == "DRAFT", "the drafted credit was never submitted"

    response = api.decide_outage_credit(
        credit["id"],
        credit_decision_payload(
            decision="APPROVE", decision_reason="approving without a submission"
        ),
        compliance_headers,
    )

    validate_error(response, ApiErrorId.ERR_CREDIT_STATE_INVALID)

    stored = validate_success(api.get_outage_credit(credit["id"], agent_headers))
    assert stored["credit_state"] == "DRAFT", "the refused decision leaves the credit DRAFT"
    assert stored["provisional_credit_cents"] == 14, (
        "9900 cents times 60 minutes over 43200 times a 1.0 multiplier rounds to 14 cents, "
        f"got {stored['provisional_credit_cents']}"
    )
    assert not stored.get("final_credit_cents"), (
        "no final amount may be computed on a refused decision"
    )
    assert not stored.get("decided_by_user_id"), "no deciding operator may be stamped"
    assert not stored.get("decision_reason"), "no decision reason may be stored"
    subscriber = get_subscriber(env["subscriber"]["id"])
    assert subscriber["pending_credit_cents"] == 14, (
        "the drafted estimate must stay on the pending ledger, got "
        f"{subscriber['pending_credit_cents']}"
    )
    assert subscriber["credit_balance_cents"] == 0, "nothing may reach the balance"


# ───────────────────── portability move onto the same cell ────────────────

def test_portability_move_onto_the_current_cell_is_refused(api, agent_headers):
    """A move must actually move, so naming the current cell is refused at request time.

    PRD §3.7: "A `PORTABILITY_MOVE` whose `target_service_cell_id` equals the subscription's current `service_cell_id` is refused with `ERR_PORTABILITY_TARGET_INVALID` — a move must actually move."

    Design: Corner/errors/portability_move_onto_the_current_cell_returns_portability_target_invalid
    """
    # Two slots and a roomy beam, so neither capacity nor headroom can be the reason.
    env = setup_active_subscription(max_active_terminals=2, forward_capacity_mbps=1000)

    response = api.create_roaming_authorization(
        create_roaming_authorization_payload(
            subscription_id=env["subscription"]["id"],
            mode="PORTABILITY_MOVE",
            target_jurisdiction_code="US-CA",
            target_service_cell_id=env["cell"]["id"],
            effective_from="2026-08-05T00:00:00Z",
            effective_until="2026-08-06T00:00:00Z",
        ),
        agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_PORTABILITY_TARGET_INVALID)

    _, meta = validate_paginated(
        api.list_roaming_authorizations(
            agent_headers, params={"subscription_id": env["subscription"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no authorisation row may be created, got {meta['total_count']}"
    )
    stored = get_subscription(env["subscription"]["id"])
    assert stored["service_cell_id"] == env["cell"]["id"], "the service must not move"
    assert stored["service_state"] == "ACTIVE", "the subscription must stay ACTIVE"
    cell = get_cell(env["cell"]["id"])
    assert cell["committed_terminal_count"] == 1, (
        f"the single commitment must stand, got {cell['committed_terminal_count']}"
    )
    assert cell["free_slot_count"] == 1, (
        f"two slots less one commitment leaves 1 free, got {cell['free_slot_count']}"
    )


# ─────────────────── authorising under a suspended licence ────────────────

def test_authorizing_under_a_suspended_licence_returns_license_not_active(
    api, agent_headers
):
    """Suspension trips both the licence gate and the beam gate; the licence gate wins.

    PRD §2.11: "Checks are evaluated in the following order and the first failure wins."
    PRD §2.11: "**Beam in service** — the governing beam's `beam_state` is `ACTIVE`. This is a last-resort catch for beam suspension in the cases the licence checks at positions 19 and 20 do not already pre-empt."
    PRD §3.1: "Hop one: every beam whose `spectrum_license_id` names this licence and whose `beam_state` is `ACTIVE` moves to `beam_state` `SUSPENDED`."
    PRD §3.5: "In both modes the subscription's `service_state` must be `PENDING_ACTIVATION` or `ACTIVE` and its `authorization_state` must be `UNAUTHORIZED` (otherwise `ERR_SUBSCRIPTION_STATE_INVALID`); its `disclosure_ack_state` must be `ACKNOWLEDGED` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); the governing licence's `license_state` must be `ACTIVE` (otherwise `ERR_LICENSE_NOT_ACTIVE`); that licence's `coordination_state` must be `COORDINATED` (otherwise `ERR_SPECTRUM_NOT_COORDINATED`); and the beam's `beam_state` must be `ACTIVE` (otherwise `ERR_BEAM_SUSPENDED`)."

    Design: Corner/errors/authorizing_under_a_suspended_licence_returns_license_not_active
    """
    env = setup_acknowledged_subscription()  # PENDING_ACTIVATION, UNAUTHORIZED, ACKNOWLEDGED
    suspend_license(env["license"]["id"], reason="interference investigation")

    response = api.authorize_subscription(
        env["subscription"]["id"], authorize_payload("FIXED"), agent_headers
    )

    validate_error(response, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

    assert get_license(env["license"]["id"])["license_state"] == "SUSPENDED", (
        "the enforcement action must have suspended the licence"
    )
    assert get_beam(env["beam"]["id"])["beam_state"] == "SUSPENDED", (
        "hop one of the cascade must have suspended the beam too"
    )
    stored = get_subscription(env["subscription"]["id"])
    assert stored["authorization_state"] == "UNAUTHORIZED", (
        "the refused authorisation must leave the subscription UNAUTHORIZED"
    )
    assert stored["service_state"] == "PENDING_ACTIVATION", (
        "the provisioning dimension must not advance"
    )
    assert not stored.get("deauthorized_by_license_id"), (
        "the subscription was never authorised, so the cascade left no marker"
    )


# ──────────────────── plan change past the beam's headroom ────────────────

def test_plan_change_past_the_beam_limit_returns_beam_oversubscribed(api, agent_headers):
    """Upgrading past the beam's limit is refused and the delta is not half-applied.

    PRD §3.6: "It re-runs the beam headroom test with a two-sided delta this time: the megabits added are the new plan's `committed_rate_mbps` multiplied by the weight the subscription will carry, and the megabits removed are the outgoing plan's `committed_rate_mbps` multiplied by the weight the subscription carries today."
    PRD §3.6: "The projected ratio is the beam's current `weighted_sold_mbps` plus that net delta, divided by `forward_capacity_mbps`, rounded half up to 4 decimal places; a value strictly above `oversubscription_limit` is refused with `ERR_BEAM_OVERSUBSCRIBED`, and exact equality is admitted."

    Design: Corner/errors/plan_change_past_the_beam_limit_returns_beam_oversubscribed
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license(
        jurisdiction_code="US-CA", in_motion_permitted=True
    )
    beam = create_beam(
        license_record["id"], forward_capacity_mbps=200, oversubscription_limit=2.0
    )
    cell = create_cell(beam["id"], jurisdiction_code="US-CA", max_active_terminals=1)
    plan_200 = create_plan(plan_code="PLAN-P1-200", committed_rate_mbps=200)
    plan_500 = create_plan(
        plan_code="PLAN-P1-500",
        committed_rate_mbps=500,
        priority_tier="PRIORITY_1",
        monthly_fee_cents=19900,
        priority_data_gb=300,
        deprioritized_rate_mbps=50,
        overage_rate_cents_per_gb=15,
    )
    subscriber = create_subscriber(index=1, jurisdiction_code="US-CA")
    order = create_order(subscriber["id"], cell["id"], plan_200["id"])
    terminal = prepare_installed_terminal(subscriber["id"], index=1)
    subscription = activate_subscription(
        order["id"], terminal["id"], service_cell_id=cell["id"]
    )
    acknowledge_disclosure(
        subscription["id"],
        subscriber["id"],
        license_record["consumer_disclosure_version"],
    )
    validate_success(
        api.authorize_subscription(
            subscription["id"], authorize_payload("FIXED"), agent_headers
        )
    )
    beam_version = get_beam_version(beam["id"])

    # 200 Mbps out, 500 Mbps in on a 200 Mbps beam projects 2.5 against a limit of 2.0.
    response = api.change_plan(
        subscription["id"],
        plan_change_payload(
            new_service_plan_id=plan_500["id"], expected_beam_version=beam_version
        ),
        agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_BEAM_OVERSUBSCRIBED)

    stored = get_subscription(subscription["id"])
    assert stored["service_plan_id"] == plan_200["id"], (
        "the subscription must keep the outgoing plan"
    )
    assert float(stored["effective_rate_mbps"]) == 200, (
        f"the effective rate must stay on the old plan, got {stored['effective_rate_mbps']}"
    )
    stored_beam = get_beam(beam["id"])
    assert float(stored_beam["weighted_sold_mbps"]) == 200, (
        f"the sold total must be unchanged, got {stored_beam['weighted_sold_mbps']}"
    )
    assert float(stored_beam["oversubscription_ratio"]) == 1.0, (
        f"200 Mbps over 200 Mbps of forward capacity is 1.0, got "
        f"{stored_beam['oversubscription_ratio']}"
    )
    assert_beam_congestion_band(stored_beam)
    assert stored_beam["version"] == beam_version, (
        f"the rejected write must not move the beam's version, got {stored_beam['version']}"
    )
