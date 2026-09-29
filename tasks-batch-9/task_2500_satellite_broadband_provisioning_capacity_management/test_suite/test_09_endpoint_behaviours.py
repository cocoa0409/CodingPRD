"""Endpoint behaviour tests for the Satellite Broadband Provisioning API.

Every test builds its own world from the PRD-declared endpoints, because the
runner restarts the server — and therefore empties the database — before each
test function.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    WAITLIST_CAP_PER_CELL,
    assert_cycle_close_report,
    assert_availability_projection,
    authorize_payload,
    create_active_license,
    create_beam,
    create_cell,
    create_order,
    create_plan,
    create_service_cell_payload,
    create_subscriber,
    get_beam_version,
    get_cell_version,
    ingest_usage,
    is_iso8601_timestamp,
    is_valid_uuid,
    plan_change_payload,
    prepare_installed_terminal,
    set_clock,
    setup_acknowledged_subscription,
    setup_active_subscription,
    setup_topology,
    validate_paginated,
    validate_success,
    warranty_replacement_payload,
)

# ─────────────────────────────────────────────────────────────────────
# GET /satellite-broadband/service-cells/{id}/availability
# ─────────────────────────────────────────────────────────────────────


def test_cell_availability_read_projects_every_declared_summary_field(api, agent_headers):
    """A determination on a two-slot cell holding one live reservation reports all
    nine declared keys, with the free figure netting the reservation off the ceiling.

    PRD §3.3: "The **advertised** answer is what an availability determination returns, and it is a pure projection: it never mutates a record and never expires a reservation."
    PRD §3.3: "It reports the cell's identity as `service_cell_id`, the cell's `availability_state`, the free slot figure as `advertised_free_slot_count`, the raw counters `committed_terminal_count`, `reserved_slot_count` and `waitlist_depth`, the constant `waitlist_cap` of 3 orders per cell, and the governing beam's congestion band as `beam_capacity_state` alongside its `beam_state`."
    PRD §3.3: "The free slot figure is the cell's `max_active_terminals` less the number of subscriptions occupying slots less the number of orders in `RESERVED`, floored at 0 so it is never negative."
    PRD §3.3: "Otherwise it is `AVAILABLE` when the free slot figure is at least 1."

    Design: Corner/endpoints/cell_availability_read_projects_every_declared_summary_field
    """
    env = setup_topology(max_active_terminals=2)
    subscriber = create_subscriber(index=1, jurisdiction_code=env["cell"]["jurisdiction_code"])
    order = create_order(subscriber["id"], env["cell"]["id"], env["plan"]["id"])
    assert order["order_state"] == "RESERVED", (
        "setup expects the sole order on a two-slot cell to be reserved, "
        f"got {order['order_state']}"
    )
    version_before = get_cell_version(env["cell"]["id"])

    response = api.get_cell_availability(env["cell"]["id"], agent_headers)
    data = validate_success(response, expected_status=200)
    assert_availability_projection(data)

    assert data["service_cell_id"] == env["cell"]["id"], (
        "the determination must name the cell it was read from"
    )
    assert data["availability_state"] == "AVAILABLE", (
        "one free slot out of two makes the cell AVAILABLE, got "
        f"{data['availability_state']}"
    )
    assert data["advertised_free_slot_count"] == 1, (
        "advertised_free_slot_count is 2 - 0 committed - 1 reserved = 1, got "
        f"{data['advertised_free_slot_count']}"
    )
    assert data["committed_terminal_count"] == 0, (
        "no subscription exists yet, so committed_terminal_count must be 0"
    )
    assert data["reserved_slot_count"] == 1, (
        "the single RESERVED order must be counted, got "
        f"{data['reserved_slot_count']}"
    )
    assert data["waitlist_depth"] == 0, "nothing is waitlisted on this cell"
    assert data["waitlist_cap"] == WAITLIST_CAP_PER_CELL, (
        f"waitlist_cap is the constant 3, got {data['waitlist_cap']}"
    )
    assert data["beam_capacity_state"] == "NORMAL", (
        "the beam has sold nothing, so its congestion band is NORMAL, got "
        f"{data['beam_capacity_state']}"
    )
    assert data["beam_state"] == "ACTIVE", (
        f"the beam radiates under a live licence, got {data['beam_state']}"
    )

    assert get_cell_version(env["cell"]["id"]) == version_before, (
        "a pure projection must not mutate the cell, so its version must not move"
    )
    assert version_before == 2, (
        "the cell was created at version 1 and the reservation moved it to 2, got "
        f"{version_before}"
    )


# ─────────────────────────────────────────────────────────────────────
# POST /satellite-broadband/beams/{id}/billing-cycle-close
# ─────────────────────────────────────────────────────────────────────


def _setup_beam_ready_for_cycle_close():
    """One ACTIVE, throttled subscription plus one lapsed reservation on the beam.

    Returns the env dict extended with "second_subscriber" and "stale_order".
    """
    env = setup_active_subscription(
        env=setup_topology(max_active_terminals=2, forward_capacity_mbps=1000)
    )
    # 150 GB against a 100 GB allowance with a 0 GB beam grace throttles the row.
    ingest_usage(env["subscription"]["id"], 150.0, billing_cycle_index=0)

    second_subscriber = create_subscriber(
        index=2, jurisdiction_code=env["cell"]["jurisdiction_code"]
    )
    stale_order = create_order(
        second_subscriber["id"], env["cell"]["id"], env["plan"]["id"]
    )
    assert stale_order["order_state"] == "RESERVED", (
        "setup expects the second order to take the remaining slot, got "
        f"{stale_order['order_state']}"
    )
    # The 72-hour hold taken at 2026-08-01 has lapsed well before 2026-08-10.
    set_clock("2026-08-10T00:00:00Z")
    env["second_subscriber"] = second_subscriber
    env["stale_order"] = stale_order
    return env


def test_billing_cycle_close_reports_a_count_for_every_step(api, netops_headers):
    """The ops-run report names each of the nine declared fields, counting the one
    swept reservation, the one charged row and the one restored row separately.

    PRD §3.9: "Its response carries the `beam_id` it ran against, the beam's new `billing_cycle_index`, a `license_expired` flag recording whether step 2 fired, a `disclosure_expired_count` from step 3, an `expired_order_count` from step 4, a `charged_subscription_count` from step 5, a `restored_subscription_count` from step 6, a `promoted_order_count` from step 8, and the beam's resulting `capacity_state`."
    PRD §3.9: "**Reservation expiry sweep.** Every order on the beam's cells whose `order_state` is `RESERVED` and whose `reservation_expires_at` is at or before the logical clock's current instant moves `RESERVED → EXPIRED`, keeping its `reservation_expires_at` for audit and releasing its slot from `reserved_slot_count`."
    PRD §3.9: "**Cycle charges.** Every subscription on the beam's cells whose `service_state` is `ACTIVE` is charged by the rule below."
    PRD §3.9: "Those among them whose `priority_state` was `DEPRIORITIZED` move `DEPRIORITIZED → PRIORITY`, which is the only way a throttled subscription is ever restored."
    PRD §3.9: "**Waitlist promotion.** The beam's cells are swept in `cell_code` ascending order, and the promotion routine of §3.3 runs on each in turn, filling whatever slots steps 2 through 4 released."

    Design: Corner/endpoints/billing_cycle_close_reports_per_step_counts_and_skips_ineligible_rows
    """
    env = _setup_beam_ready_for_cycle_close()

    response = api.close_billing_cycle(env["beam"]["id"], netops_headers)
    report = validate_success(response, expected_status=200)
    assert_cycle_close_report(report)

    assert report["beam_id"] == env["beam"]["id"], "the report must name the beam it ran against"
    assert report["billing_cycle_index"] == 1, (
        f"step 1 moves the index from 0 to 1, got {report['billing_cycle_index']}"
    )
    assert report["license_expired"] is False, (
        "the licence expires in 2027, so step 2 must not fire"
    )
    assert report["disclosure_expired_count"] == 0, (
        "the only subscription acknowledged its disclosure, so step 3 expires nothing"
    )
    assert report["expired_order_count"] == 1, (
        "step 4 must sweep the one hold that lapsed at 2026-08-04, got "
        f"{report['expired_order_count']}"
    )
    assert report["charged_subscription_count"] == 1, (
        "exactly one ACTIVE subscription is charged, got "
        f"{report['charged_subscription_count']}"
    )
    assert report["restored_subscription_count"] == 1, (
        "the throttled subscription is restored to PRIORITY, got "
        f"{report['restored_subscription_count']}"
    )
    assert report["promoted_order_count"] == 0, (
        "nothing is waitlisted, so step 8 promotes nobody, got "
        f"{report['promoted_order_count']}"
    )
    assert report["capacity_state"] == "NORMAL", (
        "200 weighted Mbps on a 1000 Mbps beam is a ratio of 0.2, well inside NORMAL, "
        f"got {report['capacity_state']}"
    )


def test_billing_cycle_close_charges_before_resetting_the_fair_use_counter(
    api, netops_headers, agent_headers
):
    """Step 5 bills the 50 GB overage the closing cycle accumulated and only then does
    step 6 zero the counter and restore priority.

    PRD §3.9: "The overage fee in cents is that volume multiplied by the plan's `overage_rate_cents_per_gb`, rounded half up to whole cents."
    PRD §3.9: "Fourth, the subscription's `cycle_charge_cents` is the gross total multiplied by one minus that discount rate, rounded half up to whole cents — a single rounding applied after the discount, not before it."
    PRD §3.9: "That charge is then added to the subscriber's `pending_charge_cents`."
    PRD §3.9: "Because step 5 runs before step 6, the charge sees the closing cycle's accumulated `cycle_priority_gb_used` rather than the zero the reset is about to write."
    PRD §3.9: "**Fair-use reset.** Every subscription on the beam's cells whose `service_state` is `ACTIVE` has its `cycle_priority_gb_used` reset to 0, has its `deprioritized_at` cleared to empty, and has its `cycle_billing_index` set to the beam's newly incremented `billing_cycle_index`."
    PRD §3.6: "On the flip, `deprioritized_at` is stamped with the logical clock's current instant and `effective_rate_mbps` is replaced by the plan's `deprioritized_rate_mbps` — this is the field a subscriber-facing portal reads to explain the slowdown, and it holds the plan's `committed_rate_mbps` whenever `priority_state` is `PRIORITY` and the plan's `deprioritized_rate_mbps` whenever it is `DEPRIORITIZED`."

    Design: Corner/endpoints/billing_cycle_close_reports_per_step_counts_and_skips_ineligible_rows
    """
    env = _setup_beam_ready_for_cycle_close()
    subscription_id = env["subscription"]["id"]

    validate_success(api.close_billing_cycle(env["beam"]["id"], netops_headers), 200)

    subscription = validate_success(api.get_subscription(subscription_id, netops_headers), 200)
    # Overage 150 - 100 = 50 GB at 25 cents = 1250; gross 9900 + 1250 = 11150 sits in
    # the five-percent band; 11150 * 0.95 = 10592.5 rounds half up to 10593.
    assert subscription["cycle_charge_cents"] == 10593, (
        "the gross total of 11150 cents discounted five percent and rounded once is "
        f"10593 cents, got {subscription['cycle_charge_cents']}"
    )
    assert subscription["cycle_priority_gb_used"] == pytest.approx(0.0, abs=0.001), (
        "step 6 resets the metered counter to 0, got "
        f"{subscription['cycle_priority_gb_used']}"
    )
    assert subscription["cycle_billing_index"] == 1, (
        "step 6 pins the row to the beam's newly incremented index, got "
        f"{subscription['cycle_billing_index']}"
    )
    assert subscription["priority_state"] == "PRIORITY", (
        "the fair-use reset is the only path back from DEPRIORITIZED, got "
        f"{subscription['priority_state']}"
    )
    assert not subscription.get("deprioritized_at"), (
        "step 6 clears deprioritized_at, got "
        f"{subscription.get('deprioritized_at')!r}"
    )
    assert subscription["effective_rate_mbps"] == pytest.approx(200.0, abs=0.001), (
        "a restored PRIORITY row advertises the plan's committed rate of 200 Mbps, got "
        f"{subscription['effective_rate_mbps']}"
    )
    assert subscription["service_state"] == "ACTIVE", (
        "a cycle close does not tear down live service"
    )

    subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers), 200)
    assert subscriber["pending_charge_cents"] == 10593, (
        "the booked cycle charge lands on the account's pending charges, got "
        f"{subscriber['pending_charge_cents']}"
    )


def test_billing_cycle_close_sweeps_the_lapsed_hold_and_recomputes_the_ledgers(
    api, netops_headers, agent_headers
):
    """The swept order keeps its lapsed hold for audit while the cell releases the slot
    and the beam re-prices the one remaining live subscription.

    PRD §3.9: "The beam's `billing_cycle_index` increases by 1 and its `last_cycle_closed_at` is stamped with the logical clock's current instant."
    PRD §3.9: "**Reservation expiry sweep.** Every order on the beam's cells whose `order_state` is `RESERVED` and whose `reservation_expires_at` is at or before the logical clock's current instant moves `RESERVED → EXPIRED`, keeping its `reservation_expires_at` for audit and releasing its slot from `reserved_slot_count`."
    PRD §3.9: "**Beam recompute.** `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state` are recomputed, now reflecting every restoration step 6 performed, and the beam's `version` increases by 1."
    PRD §3.9: "**Cell recompute.** Every cell of the beam recomputes its counters and `availability_state`."

    Design: Corner/endpoints/billing_cycle_close_reports_per_step_counts_and_skips_ineligible_rows
    """
    env = _setup_beam_ready_for_cycle_close()

    validate_success(api.close_billing_cycle(env["beam"]["id"], netops_headers), 200)

    order = validate_success(
        api.get_service_order(env["stale_order"]["id"], agent_headers), 200
    )
    assert order["order_state"] == "EXPIRED", (
        f"the lapsed hold must be swept to EXPIRED, got {order['order_state']}"
    )
    assert order["reservation_expires_at"], (
        "the sweep keeps reservation_expires_at for audit rather than clearing it"
    )

    beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers), 200)
    assert beam["billing_cycle_index"] == 1, (
        f"step 1 advances the beam's cycle index to 1, got {beam['billing_cycle_index']}"
    )
    assert beam["last_cycle_closed_at"] == "2026-08-10T00:00:00.000Z", (
        "last_cycle_closed_at is the logical clock instant of the run, got "
        f"{beam['last_cycle_closed_at']!r}"
    )
    assert beam["weighted_sold_mbps"] == pytest.approx(200.0, abs=0.001), (
        "the restored PRIORITY_1 row weighs 200 * 1.0 Mbps, got "
        f"{beam['weighted_sold_mbps']}"
    )
    assert beam["oversubscription_ratio"] == pytest.approx(0.2, abs=0.001), (
        f"200 / 1000 is a ratio of 0.2, got {beam['oversubscription_ratio']}"
    )
    assert beam["capacity_state"] == "NORMAL", (
        f"0.2 is at or below three quarters of 4.0, got {beam['capacity_state']}"
    )

    cell = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers), 200)
    assert cell["committed_terminal_count"] == 1, (
        "the live subscription keeps its slot, got "
        f"{cell['committed_terminal_count']}"
    )
    assert cell["reserved_slot_count"] == 0, (
        f"the swept hold releases its slot, got {cell['reserved_slot_count']}"
    )
    assert cell["free_slot_count"] == 1, (
        "2 - 1 committed - 0 reserved leaves 1 free slot, got "
        f"{cell['free_slot_count']}"
    )


# ─────────────────────────────────────────────────────────────────────
# POST /satellite-broadband/terminals/{id}/warranty-replacement
# ─────────────────────────────────────────────────────────────────────


def test_warranty_replacement_links_the_new_unit_to_the_unit_it_replaces(
    api, logistics_headers
):
    """The RMA creates a second terminal row pointing back at the faulty one, which
    itself only moves to RMA_PENDING.

    PRD §3.4: "A new terminal record is created in `terminal_state` `SHIPPED`, carrying the faulty unit's `subscriber_id`, a `replaces_terminal_id` pointing at the faulty unit, and `warranty_expires_at` taken from `replacement_warranty_expires_at`."
    PRD §3.4: "**The response body is the newly created replacement terminal, not the faulty one**, and the operation is treated as a creation."
    PRD §3.4: "The faulty unit itself moves into `RMA_PENDING`, and here the two source states diverge."
    PRD §3.4: "Operators tracking a replacement chain — including replacement units that only exist because a cascade created them — can filter the terminal collection on `subscriber_id`, on `replaces_terminal_id` and on `terminal_state`."

    Design: Corner/endpoints/warranty_replacement_links_the_new_unit_to_the_unit_it_replaces
    """
    set_clock(CLOCK_EPOCH)
    subscriber = create_subscriber(index=1)
    faulty = prepare_installed_terminal(subscriber["id"], index=1)
    assert faulty["terminal_state"] == "INSTALLED", (
        f"setup expects an installed unit, got {faulty['terminal_state']}"
    )
    set_clock("2026-08-04T00:00:00Z")

    response = api.warranty_replacement(
        faulty["id"],
        warranty_replacement_payload(
            replacement_serial_number="TRM-0002",
            replacement_warranty_expires_at="2029-08-01T00:00:00Z",
        ),
        logistics_headers,
    )
    replacement = validate_success(response, expected_status=201)

    assert is_valid_uuid(replacement["id"]), "the replacement is a freshly minted record"
    assert replacement["id"] != faulty["id"], (
        "the response body is the new replacement terminal, not the faulty one"
    )
    assert replacement["serial_number"] == "TRM-0002", (
        f"the replacement carries the supplied serial, got {replacement['serial_number']!r}"
    )
    assert replacement["terminal_state"] == "SHIPPED", (
        f"a replacement is born SHIPPED, got {replacement['terminal_state']}"
    )
    assert replacement["subscriber_id"] == subscriber["id"], (
        "custody follows the faulty unit's subscriber"
    )
    assert replacement["replaces_terminal_id"] == faulty["id"], (
        "replaces_terminal_id must point at the faulty unit, got "
        f"{replacement['replaces_terminal_id']!r}"
    )
    assert replacement["warranty_expires_at"] == "2029-08-01T00:00:00.000Z", (
        "warranty_expires_at is taken from replacement_warranty_expires_at, got "
        f"{replacement['warranty_expires_at']!r}"
    )
    assert replacement["version"] == 1, (
        f"a newly created record starts at version 1, got {replacement['version']}"
    )
    assert not replacement.get("installed_at"), (
        "a SHIPPED replacement has not been installed yet"
    )
    assert not replacement.get("last_scan_verdict"), (
        "a SHIPPED replacement carries no sky-survey verdict yet"
    )

    faulty_after = validate_success(api.get_terminal(faulty["id"], logistics_headers), 200)
    assert faulty_after["terminal_state"] == "RMA_PENDING", (
        f"the faulty unit moves into RMA_PENDING, got {faulty_after['terminal_state']}"
    )

    by_replaced, meta = validate_paginated(
        api.list_terminals(logistics_headers, params={"replaces_terminal_id": faulty["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one unit replaces the faulty terminal, got {meta['total_count']}"
    )
    assert by_replaced[0]["id"] == replacement["id"], (
        "the replaces_terminal_id filter must find the replacement row"
    )

    by_custodian, custodian_meta = validate_paginated(
        api.list_terminals(logistics_headers, params={"subscriber_id": subscriber["id"]})
    )
    assert custodian_meta["total_count"] == 2, (
        "the custodian now holds both the faulty unit and its replacement, got "
        f"{custodian_meta['total_count']}"
    )
    assert {row["id"] for row in by_custodian} == {faulty["id"], replacement["id"]}, (
        "the subscriber filter must return exactly the two units in that chain"
    )


# ─────────────────────────────────────────────────────────────────────
# POST /satellite-broadband/subscriptions/{id}/plan-change
# ─────────────────────────────────────────────────────────────────────


def test_plan_change_admitted_when_the_new_rate_stays_inside_the_beam_limit(
    api, agent_headers, netops_headers
):
    """Swapping a 200 Mbps plan for a 400 Mbps plan on a 1000 Mbps beam projects a
    ratio of 0.4, so the re-assignment commits and the beam is re-priced with it.

    PRD §3.6: "The projected ratio is the beam's current `weighted_sold_mbps` plus that net delta, divided by `forward_capacity_mbps`, rounded half up to 4 decimal places; a value strictly above `oversubscription_limit` is refused with `ERR_BEAM_OVERSUBSCRIBED`, and exact equality is admitted."
    PRD §3.6: "On success the subscription's `service_plan_id` is replaced, its `effective_rate_mbps` is recomputed against the new plan, and its `priority_state` is re-evaluated against the new plan's `priority_data_gb` plus the beam's `deprioritization_grace_gb`."
    PRD §3.6: "The beam then recomputes `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state`, its `version` increases by 1, and every affected coverage cell recomputes `availability_state`."
    PRD §3.6: "Re-assigning a plan is a `ProvisioningAgent` action supplying `new_service_plan_id` and the `expected_beam_version` token of §2.6, and it leaves the provisioning dimension where it was — the state pair is `ACTIVE → ACTIVE`, or `PENDING_ACTIVATION` staying `PENDING_ACTIVATION`."

    Design: Corner/endpoints/plan_change_admitted_when_the_new_rate_stays_inside_the_beam_limit
    """
    env = setup_active_subscription(
        env=setup_topology(max_active_terminals=1, forward_capacity_mbps=1000)
    )
    bigger_plan = create_plan(
        plan_code="PLAN-P1-400",
        committed_rate_mbps=400,
        priority_tier="PRIORITY_1",
        monthly_fee_cents=15900,
        priority_data_gb=200,
        deprioritized_rate_mbps=40,
        overage_rate_cents_per_gb=20,
    )
    beam_version_before = get_beam_version(env["beam"]["id"])

    response = api.change_plan(
        env["subscription"]["id"],
        plan_change_payload(
            new_service_plan_id=bigger_plan["id"],
            expected_beam_version=beam_version_before,
        ),
        agent_headers,
    )
    subscription = validate_success(response, expected_status=200)

    assert subscription["service_plan_id"] == bigger_plan["id"], (
        "the subscription must now hold the new plan"
    )
    assert subscription["effective_rate_mbps"] == pytest.approx(400.0, abs=0.001), (
        "a PRIORITY row advertises the new plan's committed rate of 400 Mbps, got "
        f"{subscription['effective_rate_mbps']}"
    )
    assert subscription["priority_state"] == "PRIORITY", (
        "0 GB used against a 200 GB allowance stays PRIORITY, got "
        f"{subscription['priority_state']}"
    )
    assert subscription["service_state"] == "ACTIVE", (
        "a plan change leaves the provisioning dimension where it was, got "
        f"{subscription['service_state']}"
    )

    beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers), 200)
    assert beam["weighted_sold_mbps"] == pytest.approx(400.0, abs=0.001), (
        "the one PRIORITY_1 row now weighs 400 * 1.0 Mbps, got "
        f"{beam['weighted_sold_mbps']}"
    )
    assert beam["oversubscription_ratio"] == pytest.approx(0.4, abs=0.001), (
        f"400 / 1000 is a ratio of 0.4, got {beam['oversubscription_ratio']}"
    )
    assert beam["capacity_state"] == "NORMAL", (
        f"0.4 is well below three quarters of 4.0, got {beam['capacity_state']}"
    )
    assert beam["version"] == beam_version_before + 1, (
        "the beam recompute increments the beam's version by exactly 1, got "
        f"{beam['version']} against {beam_version_before}"
    )


# ─────────────────────────────────────────────────────────────────────
# POST /satellite-broadband/subscriptions/{id}/authorize
# ─────────────────────────────────────────────────────────────────────


def test_authorize_in_motion_grants_the_moving_platform_authorization_state(
    api, agent_headers, netops_headers
):
    """With both mobility flags true, an IN_MOTION grant lands on AUTHORIZED_IN_MOTION
    while the provisioning dimension still advances to ACTIVE.

    PRD §3.5: "An `IN_MOTION` authorisation adds two further requirements on top of every `FIXED` requirement: the subscription's plan must have `in_motion_allowed` true, and the governing licence must have `in_motion_permitted` true."
    PRD §3.5: "When both hold, the authorisation dimension moves `UNAUTHORIZED → AUTHORIZED_IN_MOTION` and the provisioning dimension likewise advances `PENDING_ACTIVATION → ACTIVE`."
    PRD §3.5: "The beam's `weighted_sold_mbps` does not change across this transition, since `PENDING_ACTIVATION` and `ACTIVE` both contribute to the sold set."
    PRD §3.5: "Its `activated_at` is stamped with the logical clock's current instant, its `cycle_priority_gb_used` starts at 0, its `cycle_charge_cents` starts at 0, its `effective_rate_mbps` starts as the plan's `committed_rate_mbps`, and its `deauthorized_by_license_id`, `deprioritized_at`, `terminated_at` and `suspension_reason` all start empty."

    Design: Corner/endpoints/authorize_in_motion_grants_the_moving_platform_authorization_state
    """
    env = setup_acknowledged_subscription(
        env=setup_topology(
            max_active_terminals=1,
            forward_capacity_mbps=100,
            in_motion_permitted=True,
            in_motion_allowed=True,
        )
    )
    assert env["subscription"]["authorization_state"] == "UNAUTHORIZED", (
        "setup expects an unauthorised subscription, got "
        f"{env['subscription']['authorization_state']}"
    )

    response = api.authorize_subscription(
        env["subscription"]["id"], authorize_payload("IN_MOTION"), agent_headers
    )
    subscription = validate_success(response, expected_status=200)

    assert subscription["authorization_state"] == "AUTHORIZED_IN_MOTION", (
        "mode IN_MOTION must land on AUTHORIZED_IN_MOTION rather than AUTHORIZED_FIXED, "
        f"got {subscription['authorization_state']}"
    )
    assert subscription["service_state"] == "ACTIVE", (
        "first authorisation advances PENDING_ACTIVATION to ACTIVE, got "
        f"{subscription['service_state']}"
    )
    assert subscription["disclosure_ack_state"] == "ACKNOWLEDGED", (
        "the acknowledgement that gated the grant is untouched by it, got "
        f"{subscription['disclosure_ack_state']}"
    )
    assert subscription["priority_state"] == "PRIORITY", (
        "the fair-use dimension is independent of authorisation, got "
        f"{subscription['priority_state']}"
    )
    assert not subscription.get("deauthorized_by_license_id"), (
        "no licence has deauthorised this subscription, got "
        f"{subscription.get('deauthorized_by_license_id')!r}"
    )

    beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers), 200)
    assert beam["weighted_sold_mbps"] == pytest.approx(200.0, abs=0.001), (
        "the sold total does not move across this transition and stays at 200 Mbps, got "
        f"{beam['weighted_sold_mbps']}"
    )
    assert beam["capacity_state"] == "NORMAL", (
        "a ratio of 2.0 is at or below three quarters of the 4.0 limit, got "
        f"{beam['capacity_state']}"
    )


# ─────────────────────────────────────────────────────────────────────
# POST / GET /satellite-broadband/service-cells
# ─────────────────────────────────────────────────────────────────────


def test_service_cell_create_read_and_filtered_list_round_trip(
    api, netops_headers, agent_headers
):
    """Creation, the read by id and the jurisdiction filter all agree on one cell,
    while the sibling US-NV cell on the same beam stays out of the filtered page.

    PRD §3.2: "Creating one supplies its `cell_code`, between 1 and 40 characters and unique across cells, which doubles as the deterministic sweep-order key when an ops run walks a beam's cells; the `beam_id` of the beam that serves it; the `jurisdiction_code` of the footprint it covers, between 2 and 8 characters; and `max_active_terminals`, the hard slot ceiling, which must be at least 0."
    PRD §3.2: "All four counters — `committed_terminal_count`, `reserved_slot_count`, `free_slot_count` and `waitlist_depth` — start at 0, and `availability_state` is computed immediately: a cell whose `max_active_terminals` is 0, or whose beam is `SUSPENDED`, or whose beam's `capacity_state` is `SATURATED`, is born `CLOSED`, and any other new cell is born `AVAILABLE`."
    PRD §3.2: "The cell collection can be filtered by `beam_id`, by `jurisdiction_code` and by advertised `availability_state`."
    PRD §3.3: "The free slot figure is the cell's `max_active_terminals` less the number of subscriptions occupying slots less the number of orders in `RESERVED`, floored at 0 so it is never negative."

    Design: Corner/endpoints/service_cell_create_read_and_filtered_list_round_trip
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license()
    beam = create_beam(license_record["id"])
    create_cell(
        beam["id"],
        cell_code="CELL-NV-001",
        jurisdiction_code="US-NV",
        max_active_terminals=5,
    )

    created = validate_success(
        api.create_service_cell(
            create_service_cell_payload(
                beam_id=beam["id"],
                cell_code="CELL-001",
                jurisdiction_code="US-CA",
                max_active_terminals=4,
            ),
            netops_headers,
        ),
        expected_status=201,
    )
    assert is_valid_uuid(created["id"]), "a created cell carries a server-minted UUID"
    assert is_iso8601_timestamp(created["created_at"]), "a created cell is stamped created_at"

    read_back = validate_success(api.get_service_cell(created["id"], agent_headers), 200)
    assert read_back["id"] == created["id"], "the read by id must return the created row"
    assert read_back["cell_code"] == "CELL-001", (
        f"the read repeats the supplied cell_code, got {read_back['cell_code']!r}"
    )
    assert read_back["beam_id"] == beam["id"], "the read repeats the serving beam"
    assert read_back["jurisdiction_code"] == "US-CA", (
        f"the read repeats the footprint jurisdiction, got {read_back['jurisdiction_code']!r}"
    )
    assert read_back["max_active_terminals"] == 4, (
        f"the read repeats the slot ceiling, got {read_back['max_active_terminals']}"
    )
    assert read_back["committed_terminal_count"] == 0, "a new cell commits nothing"
    assert read_back["reserved_slot_count"] == 0, "a new cell holds no reservation"
    assert read_back["waitlist_depth"] == 0, "a new cell has an empty waitlist"
    assert read_back["availability_state"] == "AVAILABLE", (
        "a non-zero ceiling on an ACTIVE, uncongested beam is born AVAILABLE, got "
        f"{read_back['availability_state']}"
    )
    assert read_back["version"] == 1, (
        f"an untouched new cell is still at version 1, got {read_back['version']}"
    )

    filtered, filtered_meta = validate_paginated(
        api.list_service_cells(
            agent_headers, params={"jurisdiction_code": "US-CA", "limit": 10, "offset": 0}
        )
    )
    assert filtered_meta["total_count"] == 1, (
        "only the US-CA cell matches the jurisdiction filter, got "
        f"{filtered_meta['total_count']}"
    )
    assert filtered_meta["has_more"] is False, (
        "a single match inside a ten-row window leaves nothing beyond it"
    )
    assert [row["id"] for row in filtered] == [created["id"]], (
        "the filtered page must contain exactly the US-CA cell"
    )

    on_beam, beam_meta = validate_paginated(
        api.list_service_cells(agent_headers, params={"beam_id": beam["id"]})
    )
    assert beam_meta["total_count"] == 2, (
        f"both cells hang off the same beam, got {beam_meta['total_count']}"
    )
    assert created["id"] in {row["id"] for row in on_beam}, (
        "the beam filter must include the newly created cell"
    )
