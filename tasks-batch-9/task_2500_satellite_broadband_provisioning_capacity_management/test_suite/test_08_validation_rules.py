"""Validation rules: field ranges, cross-field shape, temporal boundaries and
the fixed order in which competing rejections are reported.

Every test builds its own world from an empty database through PRD-declared
endpoints, then exercises exactly one validation rule.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    create_active_license,
    create_beam_payload,
    create_cell,
    create_order,
    create_subscriber,
    create_subscriber_payload,
    create_subscription_payload,
    create_roaming_authorization_payload,
    create_service_order_payload,
    deliver_terminal,
    disclosure_acknowledgement_payload,
    make_subscriber_headers,
    obstruction_scan_payload,
    prepare_installed_terminal,
    request_roaming,
    reset_clock_to_epoch,
    scan_terminal,
    set_clock,
    setup_active_subscription,
    setup_pending_activation_subscription,
    setup_reserved_order,
    setup_topology,
    ship_terminal,
    suspend_license,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_replacement_payload,
)


# ───────────────────────── authentication gate ────────────────────────

@pytest.mark.parametrize(
    "user_id_header",
    [
        pytest.param(None, id="header_omitted"),
        pytest.param("", id="header_blank"),
    ],
)
def test_subscriber_creation_without_a_user_id_header_is_unauthenticated(api, user_id_header):
    """A body-valid account creation with no caller identity is refused 401.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role."
    PRD §2.1: "If either header is missing or empty, or if `X-User-Role` is not one of the five role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is examined."

    Design: Corner/validations/subscriber_creation_missing_x_user_id_header_returns_unauthenticated
    """
    reset_clock_to_epoch()

    headers = {"X-User-Role": "ProvisioningAgent", "Content-Type": "application/json"}
    if user_id_header is not None:
        headers["X-User-ID"] = user_id_header

    payload = create_subscriber_payload(
        email="sub1@example.com", full_name="Sub One", jurisdiction_code="US-CA"
    )
    response = api.create_subscriber(payload, headers)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ────────────────────── consumer disclosure pinning ───────────────────

def test_disclosure_acknowledgement_with_a_stale_version_string_is_rejected(api, agent_headers):
    """Acknowledging a version other than the pinned one leaves the ack dimension alone.

    PRD §3.5: "The subscriber submits `acknowledged_version`, which must equal the pinned `disclosure_version_issued` exactly; a mismatch is refused with `ERR_DISCLOSURE_VERSION_MISMATCH`."
    PRD §3.5: "On success the disclosure dimension moves `PENDING_ACK → ACKNOWLEDGED` and nothing else changes."

    Design: Corner/validations/disclosure_acknowledgement_with_a_stale_version_string_rejected
    """
    env = setup_pending_activation_subscription()
    subscription_id = env["subscription"]["id"]
    subscriber_id = env["subscriber"]["id"]

    response = api.acknowledge_disclosure(
        subscription_id,
        disclosure_acknowledgement_payload("CD-2025.9"),
        make_subscriber_headers(subscriber_id),
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_VERSION_MISMATCH, expected_status=422)

    after = validate_success(api.get_subscription(subscription_id, agent_headers))
    assert after["disclosure_ack_state"] == "PENDING_ACK", (
        "a rejected acknowledgement must leave disclosure_ack_state at PENDING_ACK, got "
        f"{after['disclosure_ack_state']}"
    )
    assert after["disclosure_version_issued"] == "CD-2026.1", (
        "the pinned disclosure version must not move, got "
        f"{after['disclosure_version_issued']}"
    )
    assert after["version"] == 1, (
        f"a refused acknowledgement mutates nothing, so version stays 1, got {after['version']}"
    )


# ───────────────────────── plan mobility flags ────────────────────────

@pytest.mark.parametrize("mode", ["ROAM_TEMPORARY", "PORTABILITY_MOVE"])
def test_roaming_request_on_a_plan_that_forbids_roaming_is_rejected(api, agent_headers, mode):
    """The gate is the plan flag, not the subscription: both roaming modes are refused 422.

    PRD §3.7: "A `mode` of `PORTABILITY_MOVE` or `ROAM_TEMPORARY` on a plan whose `roaming_allowed` is false is refused with `ERR_ROAMING_NOT_PERMITTED`."
    PRD §3.7: "A newly raised request is born in `auth_state` `REQUESTED` with `info_round_count` at 0, and with `governing_license_id`, `decision_note` and `revoked_reason` all empty."

    Design: Corner/validations/roaming_request_on_a_plan_that_forbids_roaming_rejected
    """
    env = setup_active_subscription(
        roaming_allowed=False,
        in_motion_allowed=False,
        plan_overrides={"plan_code": "PLAN-NR-200"},
    )
    subscription_id = env["subscription"]["id"]

    target_cell_id = None
    if mode == "PORTABILITY_MOVE":
        target_cell_id = create_cell(
            env["beam"]["id"],
            cell_code="CELL-002",
            jurisdiction_code=env["cell"]["jurisdiction_code"],
            max_active_terminals=1,
        )["id"]

    payload = create_roaming_authorization_payload(
        subscription_id=subscription_id,
        mode=mode,
        target_jurisdiction_code="US-CA",
        effective_from="2026-08-05T00:00:00Z",
        effective_until="2026-08-06T00:00:00Z",
        target_service_cell_id=target_cell_id,
    )
    response = api.create_roaming_authorization(payload, agent_headers)
    validate_error(response, ApiErrorId.ERR_ROAMING_NOT_PERMITTED, expected_status=422)

    _, meta = validate_paginated(
        api.list_roaming_authorizations(agent_headers, params={"subscription_id": subscription_id})
    )
    assert meta["total_count"] == 0, (
        f"a refused request must persist no authorisation row, got {meta['total_count']}"
    )

    after = validate_success(api.get_subscription(subscription_id, agent_headers))
    assert after["authorization_state"] == "AUTHORIZED_FIXED", (
        "the subscription's authorisation dimension must be untouched, got "
        f"{after['authorization_state']}"
    )


# ──────────────────────── reservation hold expiry ─────────────────────

@pytest.mark.parametrize(
    "clock_at_activation",
    [
        pytest.param("2026-08-04T00:00:00Z", id="exactly_at_expiry"),
        pytest.param("2026-08-05T00:00:00Z", id="after_expiry"),
    ],
)
def test_activation_rejected_when_the_reservation_hold_has_lapsed(
    api, agent_headers, clock_at_activation
):
    """The hold is half-open: at or after `reservation_expires_at` activation is refused 409.

    PRD §3.3: "Its `reservation_expires_at` is set to the logical clock's current instant plus three days — the reservation hold is 72 hours, long enough for hardware to ship."
    PRD §3.5: "The order's `reservation_expires_at` must be strictly later than the logical clock's current instant; at or after that instant the hold is gone and the attempt is refused with `ERR_RESERVATION_EXPIRED`."

    Design: Corner/validations/activation_rejected_when_the_reservation_hold_has_already_lapsed
    """
    env = setup_reserved_order(clock=CLOCK_EPOCH)
    order_id = env["order"]["id"]
    cell_id = env["cell"]["id"]

    reserved = validate_success(api.get_service_order(order_id, agent_headers))
    assert reserved["order_state"] == "RESERVED", (
        f"setup expects a RESERVED order, got {reserved['order_state']}"
    )
    assert reserved["reservation_expires_at"] == "2026-08-04T00:00:00.000Z", (
        "the 72-hour hold from the epoch must expire at 2026-08-04T00:00:00.000Z, got "
        f"{reserved['reservation_expires_at']}"
    )

    set_clock(clock_at_activation)
    cell_version = validate_success(api.get_service_cell(cell_id, agent_headers))["version"]

    response = api.create_subscription(
        create_subscription_payload(
            service_order_id=order_id,
            terminal_id=env["terminal"]["id"],
            expected_service_cell_version=cell_version,
        ),
        agent_headers,
    )
    validate_error(response, ApiErrorId.ERR_RESERVATION_EXPIRED, expected_status=409)

    after_order = validate_success(api.get_service_order(order_id, agent_headers))
    assert after_order["order_state"] == "RESERVED", (
        "activation performs no lazy expiry sweep, so the order stays RESERVED, got "
        f"{after_order['order_state']}"
    )
    assert after_order["reservation_expires_at"] == "2026-08-04T00:00:00.000Z", (
        "the lapsed hold instant is kept for audit, got "
        f"{after_order['reservation_expires_at']}"
    )

    _, meta = validate_paginated(
        api.list_subscriptions(agent_headers, params={"service_order_id": order_id})
    )
    assert meta["total_count"] == 0, (
        f"no subscription may exist after a refused activation, got {meta['total_count']}"
    )

    cell = validate_success(api.get_service_cell(cell_id, agent_headers))
    assert cell["committed_terminal_count"] == 0, (
        f"no commitment was made, got {cell['committed_terminal_count']}"
    )
    assert cell["reserved_slot_count"] == 1, (
        f"the stored reservation row still counts as reserved, got {cell['reserved_slot_count']}"
    )


# ─────────────────────────── warranty boundary ────────────────────────

@pytest.mark.parametrize(
    "clock_at_request",
    [
        pytest.param("2026-08-10T00:00:00Z", id="exactly_at_expiry"),
        pytest.param("2026-08-11T00:00:00Z", id="after_expiry"),
    ],
)
def test_warranty_replacement_rejected_at_or_after_the_warranty_expiry_instant(
    api, logistics_headers, clock_at_request
):
    """Warranty cover is half-open: at the expiry instant itself the RMA is refused 422.

    PRD §3.4: "It is legal from `DELIVERED` or from `INSTALLED`, and only while the faulty unit's `warranty_expires_at` is strictly later than the logical clock's current instant — at or after that instant the request is refused with `ERR_WARRANTY_EXPIRED`."
    PRD §3.4: "A new terminal record is created in `terminal_state` `SHIPPED`, carrying the faulty unit's `subscriber_id`, a `replaces_terminal_id` pointing at the faulty unit, and `warranty_expires_at` taken from `replacement_warranty_expires_at`."

    Design: Corner/validations/warranty_replacement_rejected_at_exactly_the_warranty_expiry_instant
    """
    reset_clock_to_epoch()
    subscriber = create_subscriber(index=1)
    terminal = prepare_installed_terminal(
        subscriber["id"], index=1, warranty_expires_at="2026-08-10T00:00:00Z"
    )
    assert terminal["terminal_state"] == "INSTALLED", (
        f"setup expects an INSTALLED terminal, got {terminal['terminal_state']}"
    )

    set_clock(clock_at_request)

    response = api.warranty_replacement(
        terminal["id"],
        warranty_replacement_payload(
            replacement_serial_number="TRM-0002",
            replacement_warranty_expires_at="2029-08-01T00:00:00Z",
        ),
        logistics_headers,
    )
    validate_error(response, ApiErrorId.ERR_WARRANTY_EXPIRED, expected_status=422)

    after = validate_success(api.get_terminal(terminal["id"], logistics_headers))
    assert after["terminal_state"] == "INSTALLED", (
        f"the faulty unit must not move to RMA_PENDING, got {after['terminal_state']}"
    )

    _, replacements_meta = validate_paginated(
        api.list_terminals(logistics_headers, params={"replaces_terminal_id": terminal["id"]})
    )
    assert replacements_meta["total_count"] == 0, (
        f"no replacement record may be created, got {replacements_meta['total_count']}"
    )

    _, all_meta = validate_paginated(api.list_terminals(logistics_headers))
    assert all_meta["total_count"] == 1, (
        f"the fleet must still hold exactly the one original terminal, got {all_meta['total_count']}"
    )


# ───────────────────────────── waitlist cap ───────────────────────────

def test_service_order_rejected_when_the_waitlist_is_already_at_its_cap(api, agent_headers):
    """One slot plus three waitlist places is the whole cell: the fifth order is refused 409.

    PRD §3.3: "When the admission figure after lazy expiry is 0, the order moves `PENDING_DETERMINATION → WAITLISTED` provided the cell's `waitlist_depth` is strictly below 3."
    PRD §3.3: "If the cell's `waitlist_depth` has already reached 3, the filing is refused outright with `ERR_WAITLIST_CLOSED`."
    PRD §3.3: "Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."

    Design: Corner/validations/service_order_rejected_when_the_waitlist_is_already_at_its_cap
    """
    env = setup_topology(max_active_terminals=1)
    cell_id = env["cell"]["id"]
    plan_id = env["plan"]["id"]

    subscribers = [create_subscriber(index=i) for i in range(1, 6)]
    filed = [create_order(subscribers[i]["id"], cell_id, plan_id) for i in range(4)]

    assert filed[0]["order_state"] == "RESERVED", (
        f"the first order takes the only slot, got {filed[0]['order_state']}"
    )
    for position, order in enumerate(filed[1:], start=2):
        assert order["order_state"] == "WAITLISTED", (
            f"order {position} has no slot to take and must be WAITLISTED, "
            f"got {order['order_state']}"
        )

    response = api.create_service_order(
        create_service_order_payload(
            subscriber_id=subscribers[4]["id"],
            service_cell_id=cell_id,
            requested_plan_id=plan_id,
        ),
        agent_headers,
    )
    validate_error(response, ApiErrorId.ERR_WAITLIST_CLOSED, expected_status=409)

    _, cell_orders_meta = validate_paginated(
        api.list_service_orders(agent_headers, params={"service_cell_id": cell_id})
    )
    assert cell_orders_meta["total_count"] == 4, (
        f"the refused filing must persist no order row, got {cell_orders_meta['total_count']}"
    )

    _, fifth_meta = validate_paginated(
        api.list_service_orders(agent_headers, params={"subscriber_id": subscribers[4]["id"]})
    )
    assert fifth_meta["total_count"] == 0, (
        f"the fifth account must hold no order, got {fifth_meta['total_count']}"
    )

    fifth = validate_success(api.get_subscriber(subscribers[4]["id"], agent_headers))
    assert fifth["account_state"] == "PROSPECT", (
        f"a refused filing does not waitlist the account, got {fifth['account_state']}"
    )

    cell = validate_success(api.get_service_cell(cell_id, agent_headers))
    assert cell["reserved_slot_count"] == 1, (
        f"exactly one live hold on the cell, got {cell['reserved_slot_count']}"
    )
    assert cell["waitlist_depth"] == 3, (
        f"the waitlist stays at its cap of 3, got {cell['waitlist_depth']}"
    )
    assert cell["free_slot_count"] == 0, (
        f"no slot is free, got {cell['free_slot_count']}"
    )
    assert cell["availability_state"] == "CLOSED", (
        "no free slot and a waitlist_depth of 3 reads as CLOSED, got "
        f"{cell['availability_state']}"
    )


# ───────────────────── portability admission on approval ──────────────

def test_portability_move_approval_rejected_when_the_target_cell_is_full(
    api, agent_headers, compliance_headers, netops_headers
):
    """Approval admits against the target cell, which a foreign live hold has filled.

    PRD §3.7: "For `mode` `PORTABILITY_MOVE`, approval additionally requires the target cell to admit at least one terminal under the expiry-aware admission reading of §3.3 — with no reservation of its own to exclude — refusing otherwise with `ERR_CELL_CAPACITY_EXHAUSTED`."
    PRD §3.3: "On order filing and on portability approval there is no order of one's own to exclude, so only the expiry adjustment applies."

    Design: Corner/validations/portability_move_approval_rejected_when_the_target_cell_is_full
    """
    env = setup_active_subscription(forward_capacity_mbps=1000, max_active_terminals=1)
    home_cell_id = env["cell"]["id"]
    subscription_id = env["subscription"]["id"]

    target_cell = create_cell(
        env["beam"]["id"],
        cell_code="CELL-002",
        jurisdiction_code=env["cell"]["jurisdiction_code"],
        max_active_terminals=1,
    )
    foreign_subscriber = create_subscriber(index=2)
    foreign_order = create_order(foreign_subscriber["id"], target_cell["id"], env["plan"]["id"])
    assert foreign_order["order_state"] == "RESERVED", (
        "the target cell's only slot must be held by a live reservation, got "
        f"{foreign_order['order_state']}"
    )

    authorization = request_roaming(
        subscription_id,
        subscriber_id=env["subscriber"]["id"],
        mode="PORTABILITY_MOVE",
        target_jurisdiction_code="US-CA",
        effective_from="2026-08-05T00:00:00Z",
        effective_until="2026-08-06T00:00:00Z",
        target_service_cell_id=target_cell["id"],
    )

    response = api.decide_roaming_authorization(
        authorization["id"],
        {"decision": "APPROVE", "decision_note": "attempt to relocate onto a full cell"},
        compliance_headers,
    )
    validate_error(response, ApiErrorId.ERR_CELL_CAPACITY_EXHAUSTED, expected_status=409)

    after_auth = validate_success(
        api.get_roaming_authorization(authorization["id"], compliance_headers)
    )
    assert after_auth["auth_state"] == "REQUESTED", (
        f"a refused decision leaves the review open, got {after_auth['auth_state']}"
    )
    assert not after_auth.get("governing_license_id"), (
        "no governing licence is stamped by a refused approval, got "
        f"{after_auth.get('governing_license_id')!r}"
    )

    after_subscription = validate_success(api.get_subscription(subscription_id, agent_headers))
    assert after_subscription["service_cell_id"] == home_cell_id, (
        "the service must stay on its original cell, got "
        f"{after_subscription['service_cell_id']}"
    )

    target_after = validate_success(api.get_service_cell(target_cell["id"], netops_headers))
    assert target_after["committed_terminal_count"] == 0, (
        f"no commitment lands on the full cell, got {target_after['committed_terminal_count']}"
    )
    assert target_after["reserved_slot_count"] == 1, (
        f"the foreign hold still occupies the target cell, got {target_after['reserved_slot_count']}"
    )
    assert target_after["free_slot_count"] == 0, (
        f"the target cell advertises no free slot, got {target_after['free_slot_count']}"
    )

    home_after = validate_success(api.get_service_cell(home_cell_id, netops_headers))
    assert home_after["committed_terminal_count"] == 1, (
        f"the vacating cell keeps its commitment, got {home_after['committed_terminal_count']}"
    )

    foreign_after = validate_success(api.get_service_order(foreign_order["id"], agent_headers))
    assert foreign_after["order_state"] == "RESERVED", (
        f"the foreign order is untouched, got {foreign_after['order_state']}"
    )


# ──────────────────────── installation sky survey ─────────────────────

def test_install_without_any_obstruction_scan_is_rejected(api, logistics_headers):
    """With zero surveys the missing-evidence rule answers, not the verdict rule.

    PRD §3.4: "If `last_scan_verdict` is empty — meaning no survey exists with a `scanned_at` at or after the later of the terminal's `created_at` and its `ownership_changed_at` — the install is refused with `ERR_OBSTRUCTION_SCAN_REQUIRED`."
    PRD §3.4: "Installing a terminal moves it into `INSTALLED` from either `DELIVERED` or `TRANSFER_PENDING`, and can be performed by the owning `Subscriber` or by a `ProvisioningAgent`."

    Design: Corner/validations/install_without_any_obstruction_scan_rejected_before_the_verdict_check
    """
    reset_clock_to_epoch()
    subscriber = create_subscriber(index=1)
    terminal = ship_terminal(subscriber["id"], index=1)
    delivered = deliver_terminal(terminal["id"])
    assert delivered["terminal_state"] == "DELIVERED", (
        f"setup expects a DELIVERED terminal, got {delivered['terminal_state']}"
    )

    response = api.install_terminal(terminal["id"], make_subscriber_headers(subscriber["id"]))
    validate_error(response, ApiErrorId.ERR_OBSTRUCTION_SCAN_REQUIRED, expected_status=422)

    after = validate_success(api.get_terminal(terminal["id"], logistics_headers))
    assert after["terminal_state"] == "DELIVERED", (
        f"the refused install leaves the unit DELIVERED, got {after['terminal_state']}"
    )
    assert not after.get("installed_at"), (
        f"installed_at must stay empty, got {after.get('installed_at')!r}"
    )
    assert not after.get("last_scan_verdict"), (
        f"last_scan_verdict must stay empty, got {after.get('last_scan_verdict')!r}"
    )

    _, meta = validate_paginated(
        api.list_obstruction_scans(terminal["id"], make_subscriber_headers(subscriber["id"]))
    )
    assert meta["total_count"] == 0, (
        f"no survey exists on this terminal, got {meta['total_count']}"
    )


def test_install_succeeds_when_the_newest_scan_verdict_is_only_marginal(api, logistics_headers):
    """10 obstructed of 200 samples is 5.00 percent — MARGINAL, and MARGINAL admits.

    PRD §3.4: "The survey computes `obstruction_pct` as one hundred times the obstructed count divided by the total count, rounded half up to 2 decimal places, and derives a `scan_verdict` from three bands: `PASS` when `obstruction_pct` is at most 2.00, `MARGINAL` when it is strictly greater than 2.00 and at most 8.00, and `FAIL` when it is strictly greater than 8.00."
    PRD §3.4: "If a qualifying survey exists but its verdict is `FAIL`, the install is refused with `ERR_OBSTRUCTION_VERDICT_FAIL`; a verdict of `PASS` or of `MARGINAL` both admit."
    PRD §3.4: "On success, `installed_at` is stamped with the logical clock's current instant."

    Design: Corner/validations/install_succeeds_when_the_newest_scan_verdict_is_only_marginal
    """
    reset_clock_to_epoch()
    subscriber = create_subscriber(index=1)
    terminal = ship_terminal(subscriber["id"], index=1)
    deliver_terminal(terminal["id"])
    scan = scan_terminal(
        terminal["id"], subscriber["id"], obstructed_sample_count=10, total_sample_count=200
    )
    assert scan["scan_verdict"] == "MARGINAL", (
        f"10 of 200 samples is 5.00 percent, which bands as MARGINAL, got {scan['scan_verdict']}"
    )

    response = api.install_terminal(terminal["id"], make_subscriber_headers(subscriber["id"]))
    installed = validate_success(response, expected_status=200)

    assert installed["terminal_state"] == "INSTALLED", (
        f"a MARGINAL verdict admits the install, got {installed['terminal_state']}"
    )
    assert installed["installed_at"] == "2026-08-01T00:00:00.000Z", (
        f"installed_at is the logical clock instant, got {installed['installed_at']}"
    )
    assert installed["last_scan_verdict"] == "MARGINAL", (
        f"the terminal records the qualifying verdict, got {installed['last_scan_verdict']}"
    )

    scans, meta = validate_paginated(
        api.list_obstruction_scans(terminal["id"], logistics_headers)
    )
    assert meta["total_count"] == 1, f"exactly one survey was recorded, got {meta['total_count']}"
    assert scans[0]["obstruction_pct"] == pytest.approx(5.00, abs=0.001), (
        f"100 * 10 / 200 is 5.00, got {scans[0]['obstruction_pct']}"
    )
    assert scans[0]["scan_verdict"] == "MARGINAL", (
        f"the newest survey bands as MARGINAL, got {scans[0]['scan_verdict']}"
    )


# ─────────────────────── competing rejection order ────────────────────

def test_expired_reservation_outranks_a_suspended_beam_on_activation(
    api, agent_headers, netops_headers
):
    """Both the lapsed hold and the suspended beam are violated; position 26 reports first.

    PRD §2.11: "Checks are evaluated in the following order and the first failure wins."
    PRD §2.11 item 26: "**Reservation still held** — the activating order's `reservation_expires_at` is strictly later than the logical clock's current instant. `ERR_RESERVATION_EXPIRED`, 409. `POST /satellite-broadband/subscriptions`."
    PRD §2.11 item 38: "**Beam in service** — the governing beam's `beam_state` is `ACTIVE`. This is a last-resort catch for beam suspension in the cases the licence checks at positions 19 and 20 do not already pre-empt. `ERR_BEAM_SUSPENDED`, 409. Four endpoints: `POST /satellite-broadband/service-orders`, `POST /satellite-broadband/subscriptions`, `POST /satellite-broadband/subscriptions/{id}/authorize`, `POST /satellite-broadband/roaming-authorizations/{id}/decide`."

    Design: Corner/validations/expired_reservation_outranks_a_suspended_beam_on_activation
    """
    env = setup_reserved_order(clock=CLOCK_EPOCH)
    order_id = env["order"]["id"]
    beam_id = env["beam"]["id"]

    set_clock("2026-08-05T00:00:00Z")
    suspend_license(env["license"]["id"], reason="interference investigation")

    beam = validate_success(api.get_beam(beam_id, netops_headers))
    assert beam["beam_state"] == "SUSPENDED", (
        "the lower-priority beam violation must really be present, got "
        f"{beam['beam_state']}"
    )

    cell_version = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))["version"]
    response = api.create_subscription(
        create_subscription_payload(
            service_order_id=order_id,
            terminal_id=env["terminal"]["id"],
            expected_service_cell_version=cell_version,
        ),
        agent_headers,
    )
    validate_error(response, ApiErrorId.ERR_RESERVATION_EXPIRED, expected_status=409)

    after_order = validate_success(api.get_service_order(order_id, agent_headers))
    assert after_order["order_state"] == "RESERVED", (
        f"the refused activation consumes nothing, got {after_order['order_state']}"
    )

    _, meta = validate_paginated(
        api.list_subscriptions(agent_headers, params={"service_order_id": order_id})
    )
    assert meta["total_count"] == 0, (
        f"no subscription may exist after a refused activation, got {meta['total_count']}"
    )


# ───────────────────────── field range and shape ──────────────────────

@pytest.mark.parametrize(
    "oversubscription_limit",
    [
        pytest.param(25.0, id="above_maximum"),
        pytest.param(0.5, id="below_minimum"),
    ],
)
def test_beam_creation_with_an_out_of_range_oversubscription_limit_is_rejected(
    api, netops_headers, oversubscription_limit
):
    """The declared range is 1.0 to 20.0 inclusive; anything outside is malformed.

    PRD §3.2: "The beam may also declare its `oversubscription_limit`, the maximum permitted ratio of weighted sold megabits to physical forward capacity; when omitted it defaults to 4.0, and any supplied value must lie between 1.0 and 20.0 inclusive."
    PRD §2.11 item 4: "**Request shape** — required body fields present, enum members valid, numeric ranges honoured."
    PRD §2.11 item 4: "This covers `limit` within 1 to 100 and `offset` at least 0, `total_sample_count` strictly greater than 0, `obstructed_sample_count` no greater than `total_sample_count`, `gb_used` at least 0, `effective_until` strictly later than `effective_from`, `ended_at` strictly later than `started_at`, and `target_service_cell_id` supplied when and only when `mode` is `PORTABILITY_MOVE`. `ERR_INVALID_REQUEST`, 400. All endpoints."

    Design: Corner/validations/beam_creation_with_an_out_of_range_oversubscription_limit_rejected
    """
    reset_clock_to_epoch()
    license_record = create_active_license()

    response = api.create_beam(
        create_beam_payload(
            spectrum_license_id=license_record["id"],
            beam_code="BEAM-01",
            forward_capacity_mbps=100,
            oversubscription_limit=oversubscription_limit,
        ),
        netops_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    _, meta = validate_paginated(
        api.list_beams(netops_headers, params={"spectrum_license_id": license_record["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a malformed creation must persist no beam, got {meta['total_count']}"
    )


def test_beam_creation_admits_the_oversubscription_limit_maximum_exactly(api, netops_headers):
    """The range is inclusive at both ends, so exactly 20.0 is accepted.

    PRD §3.2: "The beam may also declare its `oversubscription_limit`, the maximum permitted ratio of weighted sold megabits to physical forward capacity; when omitted it defaults to 4.0, and any supplied value must lie between 1.0 and 20.0 inclusive."

    Design: Corner/validations/beam_creation_with_an_out_of_range_oversubscription_limit_rejected
    """
    reset_clock_to_epoch()
    license_record = create_active_license()

    response = api.create_beam(
        create_beam_payload(
            spectrum_license_id=license_record["id"],
            beam_code="BEAM-01",
            forward_capacity_mbps=100,
            oversubscription_limit=20.0,
        ),
        netops_headers,
    )
    beam = validate_success(response, expected_status=201)
    assert float(beam["oversubscription_limit"]) == pytest.approx(20.0, abs=0.001), (
        f"the supplied ceiling must be stored verbatim, got {beam['oversubscription_limit']}"
    )


def test_obstruction_scan_with_more_obstructed_than_total_samples_is_rejected(
    api, logistics_headers
):
    """A cross-field impossibility inside one payload is refused 400 and stores nothing.

    PRD §3.4: "Either the owning `Subscriber` or a `ProvisioningAgent` may record one, supplying `obstructed_sample_count` — the number of sky samples blocked by obstruction, which must be at least 0 and no greater than the total — and `total_sample_count`, the number of samples taken, which must be strictly greater than 0."
    PRD §2.11 item 4: "This covers `limit` within 1 to 100 and `offset` at least 0, `total_sample_count` strictly greater than 0, `obstructed_sample_count` no greater than `total_sample_count`, `gb_used` at least 0, `effective_until` strictly later than `effective_from`, `ended_at` strictly later than `started_at`, and `target_service_cell_id` supplied when and only when `mode` is `PORTABILITY_MOVE`. `ERR_INVALID_REQUEST`, 400. All endpoints."

    Design: Corner/validations/obstruction_scan_with_more_obstructed_than_total_samples_rejected
    """
    reset_clock_to_epoch()
    subscriber = create_subscriber(index=1)
    terminal = ship_terminal(subscriber["id"], index=1)
    deliver_terminal(terminal["id"])

    response = api.create_obstruction_scan(
        terminal["id"],
        obstruction_scan_payload(obstructed_sample_count=201, total_sample_count=200),
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    _, meta = validate_paginated(
        api.list_obstruction_scans(terminal["id"], logistics_headers)
    )
    assert meta["total_count"] == 0, (
        f"a malformed survey must persist no row, got {meta['total_count']}"
    )

    after = validate_success(api.get_terminal(terminal["id"], logistics_headers))
    assert not after.get("last_scan_verdict"), (
        f"last_scan_verdict must stay empty, got {after.get('last_scan_verdict')!r}"
    )
    assert after["terminal_state"] == "DELIVERED", (
        f"the terminal is untouched by the refusal, got {after['terminal_state']}"
    )
