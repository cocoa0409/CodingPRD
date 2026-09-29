"""Lifecycle transitions: declared forks, terminal-state lockdown and cascade hops.

Every test builds its own precondition chain from PRD-declared endpoints, because
the server is restarted (and the database emptied) before each test.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    TERMINAL_DAMAGE_FEE_CENTS,
    ApiErrorId,
    authorize_payload,
    coordination_payload,
    create_active_license,
    create_beam,
    create_license,
    create_order,
    create_service_order_payload,
    create_subscriber,
    create_subscription_payload,
    deliver_terminal,
    enforcement_action_payload,
    get_beam,
    get_cell,
    get_cell_version,
    get_license,
    get_order,
    get_subscriber,
    get_subscription,
    get_terminal,
    open_outage_event,
    prepare_installed_terminal,
    resolve_outage_event,
    resolve_outage_payload,
    return_terminal_payload,
    set_clock,
    setup_active_subscription,
    setup_approved_roaming_window,
    setup_pending_activation_subscription,
    setup_reserved_order,
    setup_topology,
    setup_waitlisted_order,
    ship_terminal,
    suspend_license,
    terminate_payload,
    transfer_terminal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

EPOCH_STAMP = "2026-08-01T00:00:00.000Z"


# ───────────────────────── hardware lifecycle ────────────────────────


def test_deliver_moves_shipped_terminal_to_delivered(api, logistics_headers):
    """Delivery is the first logistics hop and is not an installation.

    PRD §3.4: "Confirming delivery moves the unit `SHIPPED → DELIVERED` and increases the terminal's `version` by 1."
    PRD §3.4: "A shipped unit is born in `terminal_state` `SHIPPED` with no `replaces_terminal_id`, no `last_scan_verdict`, no `installed_at`, no `ownership_changed_at` and no `return_condition`."

    Design: Corner/state_machines/terminal_deliver_moves_shipped_to_delivered
    """
    set_clock(CLOCK_EPOCH)
    subscriber = create_subscriber(index=1)
    terminal = ship_terminal(subscriber["id"], index=1)
    assert terminal["terminal_state"] == "SHIPPED", "a freshly shipped unit is born SHIPPED"
    assert terminal["version"] == 1, "a freshly created terminal is at version 1"

    data = validate_success(api.deliver_terminal(terminal["id"], logistics_headers), 200)

    assert data["terminal_state"] == "DELIVERED", (
        f"deliver moves SHIPPED → DELIVERED, got {data['terminal_state']}"
    )
    assert data["version"] == 2, (
        f"delivery increases the terminal's version by 1, expected 2, got {data['version']}"
    )
    assert not data.get("installed_at"), (
        f"delivery is not installation, installed_at must stay empty, got {data.get('installed_at')}"
    )
    assert not data.get("last_scan_verdict"), (
        "no sky survey has been recorded, so last_scan_verdict stays empty"
    )
    assert not data.get("replaces_terminal_id"), (
        "an original shipment replaces nothing, so replaces_terminal_id stays empty"
    )


def test_install_from_shipped_is_refused_as_an_invalid_terminal_state(api, agent_headers):
    """Install is declared only from DELIVERED or TRANSFER_PENDING.

    PRD §3.4: "Installing a terminal moves it into `INSTALLED` from either `DELIVERED` or `TRANSFER_PENDING`, and can be performed by the owning `Subscriber` or by a `ProvisioningAgent`."
    PRD §2.11: "**Terminal state** — `terminal_state` permits the requested logistics transition. `ERR_TERMINAL_STATE_INVALID`, 409. Six endpoints: `POST /satellite-broadband/terminals/{id}/deliver`, `.../install`, `.../return`, `.../warranty-replacement`, `.../transfer`, and `POST /satellite-broadband/terminals/{id}/obstruction-scans`."

    Design: Corner/state_machines/terminal_install_from_shipped_rejected_as_invalid_state
    """
    set_clock(CLOCK_EPOCH)
    subscriber = create_subscriber(index=1)
    terminal = ship_terminal(subscriber["id"], index=1)

    response = api.install_terminal(terminal["id"], agent_headers)
    validate_error(response, ApiErrorId.ERR_TERMINAL_STATE_INVALID, 409)

    after = get_terminal(terminal["id"])
    assert after["terminal_state"] == "SHIPPED", (
        f"a refused install leaves the unit SHIPPED, got {after['terminal_state']}"
    )
    assert not after.get("installed_at"), "a refused install stamps no installed_at"
    assert after["version"] == 1, (
        f"a refused install mutates nothing, so version stays 1, got {after['version']}"
    )


def test_transfer_moves_installed_to_transfer_pending_and_clears_the_scan(
    api, agent_headers, logistics_headers
):
    """Custody change repoints the terminal and invalidates the installation evidence.

    PRD §3.4: "On success the unit moves `INSTALLED → TRANSFER_PENDING`, its `subscriber_id` is replaced by `new_subscriber_id`, its `ownership_changed_at` is stamped with the logical clock's current instant, and its `last_scan_verdict` is cleared to empty because pre-transfer surveys no longer qualify."
    PRD §3.4: "Operators tracking a replacement chain — including replacement units that only exist because a cascade created them — can filter the terminal collection on `subscriber_id`, on `replaces_terminal_id` and on `terminal_state`."

    Design: Corner/state_machines/terminal_transfer_moves_installed_to_transfer_pending_and_clears_the_scan
    """
    set_clock(CLOCK_EPOCH)
    sub1 = create_subscriber(index=1)
    sub2 = create_subscriber(index=2)
    terminal = prepare_installed_terminal(sub1["id"], index=1)
    assert terminal["terminal_state"] == "INSTALLED", "setup must land the unit INSTALLED"
    assert terminal["last_scan_verdict"] == "PASS", "1 of 200 samples obstructed is a PASS"

    set_clock("2026-08-03T00:00:00Z")
    data = validate_success(
        api.transfer_terminal(
            terminal["id"], transfer_terminal_payload(new_subscriber_id=sub2["id"]), agent_headers
        ),
        200,
    )

    assert data["terminal_state"] == "TRANSFER_PENDING", (
        f"transfer moves INSTALLED → TRANSFER_PENDING, got {data['terminal_state']}"
    )
    assert data["subscriber_id"] == sub2["id"], (
        "the terminal's subscriber_id must be replaced by new_subscriber_id"
    )
    assert data["ownership_changed_at"] == "2026-08-03T00:00:00.000Z", (
        f"ownership_changed_at is the current logical instant, got {data['ownership_changed_at']}"
    )
    assert not data.get("last_scan_verdict"), (
        f"last_scan_verdict is cleared on transfer, got {data.get('last_scan_verdict')}"
    )
    assert data["installed_at"] == EPOCH_STAMP, (
        f"the historical install instant is retained, got {data['installed_at']}"
    )

    _, old_meta = validate_paginated(
        api.list_terminals(logistics_headers, params={"subscriber_id": sub1["id"]})
    )
    assert old_meta["total_count"] == 0, (
        f"the previous custodian holds no terminal, got {old_meta['total_count']}"
    )
    _, new_meta = validate_paginated(
        api.list_terminals(logistics_headers, params={"subscriber_id": sub2["id"]})
    )
    assert new_meta["total_count"] == 1, (
        f"the new custodian holds the transferred terminal, got {new_meta['total_count']}"
    )


@pytest.mark.parametrize(
    "condition,expected_pending_charge_cents",
    [("DAMAGED", TERMINAL_DAMAGE_FEE_CENTS), ("GOOD", 0)],
)
def test_return_receive_books_the_damage_fee_only_for_a_damaged_unit(
    api, logistics_headers, condition, expected_pending_charge_cents
):
    """The RECEIVE branch diverges only in money, keyed on the supplied condition.

    PRD §3.4: "A `RECEIVE` is legal only from `RETURN_INITIATED`, requires a `condition` of either `GOOD` or `DAMAGED`, and moves the unit `RETURN_INITIATED → RETURNED` while recording the supplied value in `return_condition`."
    PRD §3.4: "The two conditions diverge only in money: a `DAMAGED` return adds a flat damage fee of 150.00 in account currency — that is 15,000 cents — to the custodian's `pending_charge_cents`, while a `GOOD` return books nothing at all."

    Design: Corner/state_machines/terminal_return_receive_with_damaged_condition_books_the_damage_fee
    """
    set_clock(CLOCK_EPOCH)
    subscriber = create_subscriber(index=1)
    terminal = ship_terminal(subscriber["id"], index=1)
    deliver_terminal(terminal["id"])
    initiated = validate_success(
        api.return_terminal(
            terminal["id"], return_terminal_payload(event="INITIATE"), logistics_headers
        ),
        200,
    )
    assert initiated["terminal_state"] == "RETURN_INITIATED", "INITIATE opens the return"
    assert get_subscriber(subscriber["id"])["pending_charge_cents"] == 0, (
        "an INITIATE books no charge whatsoever"
    )

    data = validate_success(
        api.return_terminal(
            terminal["id"],
            return_terminal_payload(event="RECEIVE", condition=condition),
            logistics_headers,
        ),
        200,
    )

    assert data["terminal_state"] == "RETURNED", (
        f"RECEIVE moves RETURN_INITIATED → RETURNED, got {data['terminal_state']}"
    )
    assert data["return_condition"] == condition, (
        f"return_condition records the supplied value, expected {condition}, "
        f"got {data['return_condition']}"
    )
    custodian = get_subscriber(subscriber["id"])
    assert custodian["pending_charge_cents"] == expected_pending_charge_cents, (
        f"a {condition} return books {expected_pending_charge_cents} cents of pending charge, "
        f"got {custodian['pending_charge_cents']}"
    )
    assert custodian["credit_balance_cents"] == 0, "a return never touches credit_balance_cents"
    assert custodian["pending_credit_cents"] == 0, "a return never touches pending_credit_cents"


# ─────────────────── licence coordination and enforcement ────────────


def test_coordination_refused_suspends_every_beam_on_the_licence(api, compliance_headers):
    """The REFUSED branch of the coordination fork carries its own side-effect set.

    PRD §3.1: "`REFUSED` on a licence in `PENDING_COORDINATION` moves `license_state` from `PENDING_COORDINATION` to the terminal state `REFUSED`, sets `coordination_state` to `REFUSED`, and — this is the divergent part — puts every beam that names this licence out of service by moving its `beam_state` from `ACTIVE` to `SUSPENDED`."
    PRD §3.1: "The licence's `version` increases by 1."

    Design: Corner/state_machines/license_coordination_refused_suspends_every_beam_on_the_licence
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_license()
    assert license_record["license_state"] == "PENDING_COORDINATION", (
        "a filed licence lands in PENDING_COORDINATION"
    )
    beam = create_beam(license_record["id"], forward_capacity_mbps=100)

    data = validate_success(
        api.record_coordination(
            license_record["id"],
            coordination_payload(
                outcome="REFUSED", coordination_note="neighbour operator objection upheld"
            ),
            compliance_headers,
        ),
        200,
    )

    assert data["license_state"] == "REFUSED", (
        f"a refused coordination moves the licence to REFUSED, got {data['license_state']}"
    )
    assert data["coordination_state"] == "REFUSED", (
        f"the coordination dimension is set to REFUSED, got {data['coordination_state']}"
    )
    assert data["version"] == 2, (
        f"the licence's version increases by 1, expected 2, got {data['version']}"
    )
    after_beam = get_beam(beam["id"])
    assert after_beam["beam_state"] == "SUSPENDED", (
        f"every beam naming a refused licence is out of service, got {after_beam['beam_state']}"
    )


def test_coordination_recorded_twice_is_refused_as_an_invalid_licence_state(
    api, compliance_headers
):
    """A GRANTED coordination is not idempotent.

    PRD §3.1: "`GRANTED` on a licence in `PENDING_COORDINATION` moves `license_state` from `PENDING_COORDINATION` to `ACTIVE` and sets `coordination_state` to `COORDINATED`. The supplied note is stored in `coordination_note`, and the licence's `version` increases by 1."
    PRD §3.1: "Any coordination filing that does not match one of those four shapes — for instance a filing against a licence that is `SUSPENDED`, `REFUSED` or `EXPIRED`, an outcome of `GRANTED` against an `ACTIVE` licence that is already `COORDINATED`, or a `GRANTED_PROVISIONAL` against anything other than `PENDING_COORDINATION` — is refused with `ERR_LICENSE_STATE_INVALID`."

    Design: Corner/state_machines/license_coordination_recorded_twice_rejected_as_invalid_state
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license()
    assert license_record["version"] == 2, "the first grant takes the licence to version 2"

    response = api.record_coordination(
        license_record["id"],
        coordination_payload(outcome="GRANTED", coordination_note="duplicate filing"),
        compliance_headers,
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_STATE_INVALID, 409)

    after = get_license(license_record["id"])
    assert after["license_state"] == "ACTIVE", (
        f"the licence stays ACTIVE, got {after['license_state']}"
    )
    assert after["coordination_state"] == "COORDINATED", (
        f"the licence stays COORDINATED, got {after['coordination_state']}"
    )
    assert after["coordination_note"] == "no neighbour objection", (
        f"the refused duplicate note was not stored, got {after['coordination_note']!r}"
    )
    assert after["version"] == 2, (
        f"a refused filing does not move the version again, got {after['version']}"
    )


def test_refused_licence_is_terminal_and_rejects_an_enforcement_action(api, compliance_headers):
    """REFUSED is terminal, so no enforcement lever can resurrect the licence.

    PRD §3.1: "Enforcement is the second regulatory lever, and it carries an `action` of either `SUSPEND` or `REINSTATE` together with a mandatory `reason` that is stored in `enforcement_reason`. Suspension is only legal from `ACTIVE`; reinstatement is only legal from `SUSPENDED`. Anything else is refused with `ERR_LICENSE_STATE_INVALID`."
    PRD §3.1: "Unlike the granted branches, no `coordination_note` semantics apply beyond what the filing supplies, and there is no path back: `REFUSED` is terminal."

    Design: Corner/state_machines/refused_licence_is_terminal_and_rejects_enforcement_action
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_license()
    refused = validate_success(
        api.record_coordination(
            license_record["id"],
            coordination_payload(outcome="REFUSED", coordination_note="objection upheld"),
            compliance_headers,
        ),
        200,
    )
    assert refused["license_state"] == "REFUSED", "setup must land the licence in REFUSED"

    response = api.enforcement_action(
        license_record["id"],
        enforcement_action_payload("SUSPEND", reason="attempt to act on a refused licence"),
        compliance_headers,
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_STATE_INVALID, 409)

    after = get_license(license_record["id"])
    assert after["license_state"] == "REFUSED", (
        f"the terminal state is preserved, got {after['license_state']}"
    )
    assert not after.get("enforcement_reason"), (
        f"a refused enforcement action stores no reason, got {after.get('enforcement_reason')!r}"
    )
    assert after["version"] == 2, (
        f"a refused enforcement action does not move the version, got {after['version']}"
    )


def test_reinstate_compensates_the_suspension_without_restoring_roaming(api, compliance_headers):
    """Reinstatement reverses the beam, subscription and cell hops but never the roaming hop.

    PRD §3.1: "Moving `license_state` from `SUSPENDED` back to `ACTIVE` returns every beam under the licence whose `beam_state` is `SUSPENDED` to `ACTIVE`, and returns every subscription whose `deauthorized_by_license_id` equals this licence and whose `service_state` is anything other than `TERMINATED` to `authorization_state` `AUTHORIZED_FIXED`, clearing `deauthorized_by_license_id` back to empty in the process."
    PRD §3.1: "Roaming authorisations revoked by the suspension are **not** restored — they stay `REVOKED` and must be requested again."
    PRD §3.7: "The licence suspension and licence expiry cascades of §3.1 revoke authorisations that were `APPROVED`, writing `LICENSE_SUSPENDED` into `revoked_reason`; and note that this hop does **not** restore the subscription's `authorization_state` to `AUTHORIZED_FIXED` — the subscription is left `DEAUTHORIZED` by the hop above it."

    Design: Corner/state_machines/license_reinstate_compensates_the_suspension_without_restoring_roaming
    """
    env = setup_approved_roaming_window(max_active_terminals=2)
    license_id = env["license"]["id"]
    suspend_license(license_id, reason="interference investigation")

    suspended_roaming = validate_success(
        api.get_roaming_authorization(env["roaming"]["id"], compliance_headers), 200
    )
    assert suspended_roaming["auth_state"] == "REVOKED", (
        "the suspension cascade must revoke the approved roaming grant"
    )

    data = validate_success(
        api.enforcement_action(
            license_id,
            enforcement_action_payload("REINSTATE", reason="investigation closed"),
            compliance_headers,
        ),
        200,
    )

    assert data["license_state"] == "ACTIVE", (
        f"reinstatement moves SUSPENDED → ACTIVE, got {data['license_state']}"
    )
    assert data["coordination_state"] == "COORDINATED", (
        "the coordination dimension is untouched by enforcement"
    )
    assert data["enforcement_reason"] == "investigation closed", (
        f"the mandatory reason is stored in enforcement_reason, got {data['enforcement_reason']!r}"
    )

    beam = get_beam(env["beam"]["id"])
    assert beam["beam_state"] == "ACTIVE", (
        f"every suspended beam under the licence returns to ACTIVE, got {beam['beam_state']}"
    )
    assert beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001), (
        f"the ACTIVE subscription still sells 200 weighted Mbps, got {beam['weighted_sold_mbps']}"
    )
    assert beam["oversubscription_ratio"] == pytest.approx(2.0, abs=0.001), (
        f"200 / 100 is a ratio of 2.0, got {beam['oversubscription_ratio']}"
    )
    assert beam["capacity_state"] == "NORMAL", (
        f"2.0 is at or below three quarters of the 4.0 limit, got {beam['capacity_state']}"
    )

    subscription = get_subscription(env["subscription"]["id"])
    assert subscription["authorization_state"] == "AUTHORIZED_FIXED", (
        f"the deauthorised subscription returns to AUTHORIZED_FIXED, "
        f"got {subscription['authorization_state']}"
    )
    assert not subscription.get("deauthorized_by_license_id"), (
        "deauthorized_by_license_id is cleared back to empty on reinstatement"
    )
    assert subscription["service_state"] == "ACTIVE", (
        f"the provisioning dimension was never moved by the cascade, "
        f"got {subscription['service_state']}"
    )

    roaming = validate_success(
        api.get_roaming_authorization(env["roaming"]["id"], compliance_headers), 200
    )
    assert roaming["auth_state"] == "REVOKED", (
        f"a revoked roaming grant is deliberately not restored, got {roaming['auth_state']}"
    )
    assert roaming["revoked_reason"] == "LICENSE_SUSPENDED", (
        f"the revocation reason stays LICENSE_SUSPENDED, got {roaming['revoked_reason']!r}"
    )

    cell = get_cell(env["cell"]["id"])
    assert cell["committed_terminal_count"] == 1, (
        f"the live subscription keeps its slot, got {cell['committed_terminal_count']}"
    )
    assert cell["free_slot_count"] == 1, (
        f"one of the two slots is still free, got {cell['free_slot_count']}"
    )
    assert cell["availability_state"] == "AVAILABLE", (
        f"with the beam back in service and a free slot the cell is AVAILABLE, "
        f"got {cell['availability_state']}"
    )


# ─────────────────── orders, activation and termination ──────────────


def test_service_order_takes_the_waitlisted_branch_when_no_slot_is_free(api, agent_headers):
    """Branch B of the determination fork consumes no slot and waitlists the account.

    PRD §3.3: "When the admission figure after lazy expiry is 0, the order moves `PENDING_DETERMINATION → WAITLISTED` provided the cell's `waitlist_depth` is strictly below 3. Its `waitlist_priority_score` is computed as described below, the subscriber's `account_state` moves from `PROSPECT` to `WAITLISTED`, the cell's `waitlist_depth` increases by 1, `availability_state` is recomputed, and the cell's `version` increases by 1."
    PRD §3.3: "The plan tier contributes a rank multiplied by one thousand: 3 for a `requested_plan_id` whose `priority_tier` is `PRIORITY_1`, 2 for `PRIORITY_2` and 1 for `BEST_EFFORT`."
    PRD §3.3: "Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."

    Design: Corner/state_machines/service_order_takes_the_waitlisted_branch_when_no_slot_is_free
    """
    env = setup_topology(max_active_terminals=1, priority_tier="PRIORITY_1")
    sub1 = create_subscriber(index=1)
    order1 = create_order(sub1["id"], env["cell"]["id"], env["plan"]["id"])
    assert order1["order_state"] == "RESERVED", "the first order takes the reserved branch"
    sub2 = create_subscriber(index=2)

    data = validate_success(
        api.create_service_order(
            create_service_order_payload(
                subscriber_id=sub2["id"],
                service_cell_id=env["cell"]["id"],
                requested_plan_id=env["plan"]["id"],
            ),
            agent_headers,
        ),
        201,
    )

    assert data["order_state"] == "WAITLISTED", (
        f"with no admitting slot the order lands WAITLISTED, got {data['order_state']}"
    )
    assert data["waitlist_priority_score"] == 3000, (
        f"PRIORITY_1 rank 3 times one thousand plus 0 whole waiting days is 3000, "
        f"got {data['waitlist_priority_score']}"
    )
    assert not data.get("reservation_expires_at"), (
        "the waitlisted branch holds no reservation, so reservation_expires_at stays empty"
    )
    assert not data.get("promoted_at"), "a freshly waitlisted order has never been promoted"

    assert get_order(order1["id"])["order_state"] == "RESERVED", (
        "the incumbent reservation is untouched by the second filing"
    )
    assert get_subscriber(sub2["id"])["account_state"] == "WAITLISTED", (
        "the waitlisted branch moves the subscriber PROSPECT → WAITLISTED"
    )

    cell = get_cell(env["cell"]["id"])
    assert cell["reserved_slot_count"] == 1, (
        f"no slot is consumed on the waitlisted branch, got {cell['reserved_slot_count']}"
    )
    assert cell["free_slot_count"] == 0, f"the single slot is held, got {cell['free_slot_count']}"
    assert cell["waitlist_depth"] == 1, (
        f"waitlist_depth increases by 1, got {cell['waitlist_depth']}"
    )
    assert cell["availability_state"] == "WAITLIST_ONLY", (
        f"no free slot and a waitlist depth below 3 advertises WAITLIST_ONLY, "
        f"got {cell['availability_state']}"
    )


def test_activation_starts_all_four_subscription_dimensions_at_their_initial_states(
    api, agent_headers
):
    """A brand-new subscription is born in four independent dimensions at once.

    PRD §3.5: "On success a subscription record is created and lands in four independent state dimensions at once: `service_state` `PENDING_ACTIVATION`, `authorization_state` `UNAUTHORIZED`, `priority_state` `PRIORITY` and `disclosure_ack_state` `PENDING_ACK`."
    PRD §3.5: "The subscription's `disclosure_version_issued` takes the `consumer_disclosure_version` of the governing licence — the licence the beam radiates under, per §2.10 — and `disclosure_ack_deadline_at` is set to the activation instant plus 14 days."
    PRD §3.5: "Its `activated_at` is stamped with the logical clock's current instant, its `cycle_priority_gb_used` starts at 0, its `cycle_charge_cents` starts at 0, its `effective_rate_mbps` starts as the plan's `committed_rate_mbps`, and its `deauthorized_by_license_id`, `deprioritized_at`, `terminated_at` and `suspension_reason` all start empty."
    PRD §3.5: "Its `cycle_billing_index` is copied from the governing beam's current `billing_cycle_index`, which is what makes metered readings from a stale cycle identifiable later."
    PRD §3.5: "The consumed order moves `RESERVED → ACTIVATED`, which is terminal for it. The subscriber's `account_state` moves to `ACTIVE`. On the cell, `reserved_slot_count` drops by 1 while `committed_terminal_count` rises by 1 — the hold becomes a commitment — after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."

    Design: Corner/state_machines/subscription_creation_starts_all_four_dimensions_at_their_initial_states
    """
    env = setup_reserved_order(max_active_terminals=1)
    cell_version = get_cell_version(env["cell"]["id"])

    data = validate_success(
        api.create_subscription(
            create_subscription_payload(
                service_order_id=env["order"]["id"],
                terminal_id=env["terminal"]["id"],
                expected_service_cell_version=cell_version,
            ),
            agent_headers,
        ),
        201,
    )

    assert data["service_state"] == "PENDING_ACTIVATION", (
        f"the provisioning dimension starts PENDING_ACTIVATION, got {data['service_state']}"
    )
    assert data["authorization_state"] == "UNAUTHORIZED", (
        f"the authorisation dimension starts UNAUTHORIZED, got {data['authorization_state']}"
    )
    assert data["priority_state"] == "PRIORITY", (
        f"the fair-use dimension starts PRIORITY, got {data['priority_state']}"
    )
    assert data["disclosure_ack_state"] == "PENDING_ACK", (
        f"the disclosure dimension starts PENDING_ACK, got {data['disclosure_ack_state']}"
    )
    assert data["disclosure_version_issued"] == "CD-2026.1", (
        f"the governing licence's disclosure version is pinned, "
        f"got {data['disclosure_version_issued']!r}"
    )
    assert data["disclosure_ack_deadline_at"] == "2026-08-15T00:00:00.000Z", (
        f"the ack deadline is the activation instant plus 14 days, "
        f"got {data['disclosure_ack_deadline_at']}"
    )
    assert data["activated_at"] == EPOCH_STAMP, (
        f"activated_at is the current logical instant, got {data['activated_at']}"
    )
    assert data["cycle_billing_index"] == 0, (
        f"cycle_billing_index copies the beam's billing_cycle_index of 0, "
        f"got {data['cycle_billing_index']}"
    )
    assert data["cycle_priority_gb_used"] == pytest.approx(0, abs=0.001), (
        f"metered volume starts at 0, got {data['cycle_priority_gb_used']}"
    )
    assert data["cycle_charge_cents"] == 0, (
        f"cycle_charge_cents starts at 0, got {data['cycle_charge_cents']}"
    )
    assert data["effective_rate_mbps"] == pytest.approx(200, abs=0.001), (
        f"effective_rate_mbps starts as the plan's committed_rate_mbps, "
        f"got {data['effective_rate_mbps']}"
    )
    assert not data.get("deauthorized_by_license_id"), "deauthorized_by_license_id starts empty"
    assert not data.get("deprioritized_at"), "deprioritized_at starts empty"
    assert not data.get("terminated_at"), "terminated_at starts empty"
    assert not data.get("suspension_reason"), "suspension_reason starts empty"
    assert data["subscriber_id"] == env["subscriber"]["id"], (
        "subscriber_id is copied from the consumed order"
    )
    assert data["service_cell_id"] == env["cell"]["id"], (
        "service_cell_id is copied from the consumed order"
    )
    assert data["service_plan_id"] == env["plan"]["id"], (
        "service_plan_id comes from the order's requested_plan_id"
    )
    assert data["terminal_id"] == env["terminal"]["id"], (
        "terminal_id is taken from the request body"
    )
    assert data["version"] == 1, f"a freshly created record is at version 1, got {data['version']}"

    assert get_order(env["order"]["id"])["order_state"] == "ACTIVATED", (
        "the consumed order moves RESERVED → ACTIVATED"
    )
    assert get_subscriber(env["subscriber"]["id"])["account_state"] == "ACTIVE", (
        "the subscriber's account_state moves to ACTIVE"
    )

    cell = get_cell(env["cell"]["id"])
    assert cell["committed_terminal_count"] == 1, (
        f"the hold becomes a commitment, got {cell['committed_terminal_count']}"
    )
    assert cell["reserved_slot_count"] == 0, (
        f"reserved_slot_count drops by 1, got {cell['reserved_slot_count']}"
    )
    assert cell["free_slot_count"] == 0, (
        f"the single slot is now committed, got {cell['free_slot_count']}"
    )
    assert cell["availability_state"] == "WAITLIST_ONLY", (
        f"no free slot with an empty waitlist advertises WAITLIST_ONLY, "
        f"got {cell['availability_state']}"
    )

    beam = get_beam(env["beam"]["id"])
    assert beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001), (
        f"200 Mbps at PRIORITY_1 weight 1.0 is 200 weighted Mbps, "
        f"got {beam['weighted_sold_mbps']}"
    )
    assert beam["oversubscription_ratio"] == pytest.approx(2.0, abs=0.001), (
        f"200 / 100 is a ratio of 2.0, got {beam['oversubscription_ratio']}"
    )
    assert beam["capacity_state"] == "NORMAL", (
        f"2.0 is at or below three quarters of the 4.0 limit, got {beam['capacity_state']}"
    )


def test_authorize_before_disclosure_acknowledgement_is_refused(api, agent_headers):
    """The authorise transition's disclosure gate stands on its own.

    PRD §3.5: "In both modes the subscription's `service_state` must be `PENDING_ACTIVATION` or `ACTIVE` and its `authorization_state` must be `UNAUTHORIZED` (otherwise `ERR_SUBSCRIPTION_STATE_INVALID`); its `disclosure_ack_state` must be `ACKNOWLEDGED` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); the governing licence's `license_state` must be `ACTIVE` (otherwise `ERR_LICENSE_NOT_ACTIVE`); that licence's `coordination_state` must be `COORDINATED` (otherwise `ERR_SPECTRUM_NOT_COORDINATED`); and the beam's `beam_state` must be `ACTIVE` (otherwise `ERR_BEAM_SUSPENDED`)."
    PRD §2.11: "**Disclosure acknowledged** — `disclosure_ack_state` is `ACKNOWLEDGED` before network authorisation is granted. `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, 422. `POST /satellite-broadband/subscriptions/{id}/authorize`."

    Design: Corner/state_machines/authorize_before_disclosure_acknowledgement_rejected
    """
    env = setup_pending_activation_subscription(max_active_terminals=1)
    subscription_id = env["subscription"]["id"]
    assert env["subscription"]["disclosure_ack_state"] == "PENDING_ACK", (
        "setup must leave the disclosure unacknowledged"
    )

    response = api.authorize_subscription(
        subscription_id, authorize_payload("FIXED"), agent_headers
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED, 422)

    after = get_subscription(subscription_id)
    assert after["authorization_state"] == "UNAUTHORIZED", (
        f"a refused authorisation leaves the dimension UNAUTHORIZED, "
        f"got {after['authorization_state']}"
    )
    assert after["service_state"] == "PENDING_ACTIVATION", (
        f"the provisioning dimension does not advance, got {after['service_state']}"
    )
    assert after["disclosure_ack_state"] == "PENDING_ACK", (
        f"the disclosure dimension is unchanged, got {after['disclosure_ack_state']}"
    )
    assert after["version"] == 1, (
        f"a refused authorisation mutates nothing, so version stays 1, got {after['version']}"
    )


def test_terminate_promotes_the_top_waitlisted_order_on_the_cell(api, agent_headers):
    """Freeing the committed slot promotes the waitlist inside the terminate transaction.

    PRD §3.9: "A `ProvisioningAgent` supplies a `termination_reason`, and a subscription whose `service_state` is `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED` moves to the terminal state `TERMINATED`; its `terminated_at` is stamped with the logical clock's current instant and its `authorization_state` is forced to `DEAUTHORIZED`."
    PRD §3.9: "Hop one: the cell's `committed_terminal_count` drops by 1, after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."
    PRD §3.9: "Hop two, caused by hop one: the promotion routine runs on that cell, so the top-ranked waitlisted order — highest `waitlist_priority_score`, `created_at` ascending as tie-break — moves `WAITLISTED → RESERVED` with its `reservation_expires_at` set to the logical clock's current instant plus 72 hours and its `promoted_at` stamped."
    PRD §3.9: "Hop three, caused by hop two: that promoted order's subscriber moves `account_state` from `WAITLISTED` to `PROSPECT`."
    PRD §3.9: "The bound terminal is pulled back: a terminal in `INSTALLED` moves `INSTALLED → RETURN_INITIATED`."
    PRD §3.9: "And the subscriber's `account_state` moves to `CLOSED` when that subscriber has no remaining subscription whose `service_state` is `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED`."

    Design: Corner/state_machines/subscription_terminate_promotes_the_top_waitlisted_order_on_the_cell
    """
    env = setup_active_subscription(max_active_terminals=1)
    waiting = setup_waitlisted_order(env, subscriber_index=2)
    assert waiting["order"]["order_state"] == "WAITLISTED", "setup must waitlist the second order"

    data = validate_success(
        api.terminate_subscription(
            env["subscription"]["id"],
            terminate_payload(termination_reason="customer moved out of footprint"),
            agent_headers,
        ),
        200,
    )

    assert data["service_state"] == "TERMINATED", (
        f"termination moves the subscription to TERMINATED, got {data['service_state']}"
    )
    assert data["authorization_state"] == "DEAUTHORIZED", (
        f"authorization_state is forced to DEAUTHORIZED, got {data['authorization_state']}"
    )
    assert data["terminated_at"] == EPOCH_STAMP, (
        f"terminated_at is the current logical instant, got {data['terminated_at']}"
    )

    promoted = get_order(waiting["order"]["id"])
    assert promoted["order_state"] == "RESERVED", (
        f"the top-ranked waitlisted order is promoted to RESERVED, got {promoted['order_state']}"
    )
    assert promoted["promoted_at"] == EPOCH_STAMP, (
        f"promoted_at is stamped with the promotion instant, got {promoted['promoted_at']}"
    )
    assert promoted["reservation_expires_at"] == "2026-08-04T00:00:00.000Z", (
        f"the fresh hold runs 72 hours from the promotion instant, "
        f"got {promoted['reservation_expires_at']}"
    )
    assert get_subscriber(waiting["subscriber"]["id"])["account_state"] == "PROSPECT", (
        "the promoted order's subscriber moves WAITLISTED → PROSPECT"
    )
    assert get_subscriber(env["subscriber"]["id"])["account_state"] == "CLOSED", (
        "the terminating subscriber has no remaining non-terminal subscription, so it CLOSES"
    )
    assert get_terminal(env["terminal"]["id"])["terminal_state"] == "RETURN_INITIATED", (
        "the bound INSTALLED terminal is pulled back to RETURN_INITIATED"
    )

    cell = get_cell(env["cell"]["id"])
    assert cell["committed_terminal_count"] == 0, (
        f"the terminated subscription leaves the committed count, "
        f"got {cell['committed_terminal_count']}"
    )
    assert cell["reserved_slot_count"] == 1, (
        f"the promotion converts the freed slot into a hold, got {cell['reserved_slot_count']}"
    )
    assert cell["waitlist_depth"] == 0, (
        f"the promoted order has left the waitlist, got {cell['waitlist_depth']}"
    )
    assert cell["free_slot_count"] == 0, (
        f"the single slot is held by the promoted order, got {cell['free_slot_count']}"
    )

    beam = get_beam(env["beam"]["id"])
    assert beam["weighted_sold_mbps"] == pytest.approx(0, abs=0.001), (
        f"a TERMINATED subscription contributes nothing, got {beam['weighted_sold_mbps']}"
    )
    assert beam["oversubscription_ratio"] == pytest.approx(0, abs=0.001), (
        f"no sold megabits gives a ratio of 0, got {beam['oversubscription_ratio']}"
    )
    assert beam["capacity_state"] == "NORMAL", (
        f"a ratio of 0 bands as NORMAL, got {beam['capacity_state']}"
    )


# ────────────────────────── impairment events ────────────────────────


def test_outage_event_resolved_twice_is_refused_as_already_resolved(
    api, netops_headers, agent_headers
):
    """Resolution is a one-way transition and cannot re-stamp its own arithmetic.

    PRD §3.8: "Resolution is legal only from `OPEN`; a second attempt is refused with `ERR_OUTAGE_ALREADY_RESOLVED`."
    PRD §3.8: "Resolution moves the event `OPEN → RESOLVED` and computes `outage_minutes` as the number of whole minutes between `started_at` and `ended_at`, discarding any partial minute."
    PRD §3.8: "It then computes `credit_eligible`, which is true only when the `cause` is anything other than `PLANNED_MAINTENANCE` **and** `outage_minutes` is at least 30 — a shorter blip is beneath the service-level floor."
    PRD §3.8: "The event's `generated_credit_count` records how many credits were created."

    Design: Corner/state_machines/outage_event_resolved_twice_rejected_as_already_resolved
    """
    set_clock(CLOCK_EPOCH)
    license_record = create_active_license()
    beam = create_beam(license_record["id"], forward_capacity_mbps=100)
    set_clock("2026-08-02T00:00:00Z")
    event = open_outage_event(
        beam["id"],
        cause="EQUIPMENT_FAILURE",
        severity="FULL_OUTAGE",
        started_at="2026-08-01T10:00:00Z",
    )
    resolved = resolve_outage_event(event["id"], "2026-08-01T11:00:00Z")
    assert resolved["event_state"] == "RESOLVED", "setup must resolve the event once"

    response = api.resolve_outage_event(
        event["id"], resolve_outage_payload("2026-08-01T12:00:00Z"), netops_headers
    )
    validate_error(response, ApiErrorId.ERR_OUTAGE_ALREADY_RESOLVED, 409)

    after = validate_success(api.get_outage_event(event["id"], netops_headers), 200)
    assert after["event_state"] == "RESOLVED", (
        f"the event stays RESOLVED, got {after['event_state']}"
    )
    assert after["ended_at"] == "2026-08-01T11:00:00.000Z", (
        f"the refused second resolve cannot re-stamp ended_at, got {after['ended_at']}"
    )
    assert after["outage_minutes"] == 60, (
        f"one whole hour is 60 whole minutes, got {after['outage_minutes']}"
    )
    assert after["credit_eligible"] is True, (
        f"an EQUIPMENT_FAILURE lasting at least 30 minutes is credit eligible, "
        f"got {after['credit_eligible']}"
    )
    assert after["generated_credit_count"] == 0, (
        f"no subscription was affected, so no credit row was created, "
        f"got {after['generated_credit_count']}"
    )

    _, meta = validate_paginated(api.list_outage_credits(agent_headers))
    assert meta["total_count"] == 0, (
        f"the credit collection is empty, got {meta['total_count']}"
    )
