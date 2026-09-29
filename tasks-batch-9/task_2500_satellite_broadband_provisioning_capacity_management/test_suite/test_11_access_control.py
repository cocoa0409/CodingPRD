"""Access control: the endpoint role gate, per-row subscriber ownership, and the
segregation of submission from decision on an outage credit.

Every test starts from an empty database and builds its own preconditions.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    TEST_USERS,
    cancel_order_payload,
    capacity_policy_payload,
    coordination_payload,
    create_beam_payload,
    create_order,
    create_outage_event_payload,
    create_service_cell_payload,
    create_service_order_payload,
    create_service_plan_payload,
    create_spectrum_license_payload,
    create_subscriber,
    create_subscriber_payload,
    create_terminal_payload,
    credit_decision_payload,
    deliver_terminal,
    enforcement_action_payload,
    get_beam_version,
    make_compliance_officer_headers,
    make_provisioning_agent_headers,
    make_subscriber_headers,
    obstruction_scan_payload,
    set_clock_payload,
    setup_drafted_credit,
    setup_topology,
    ship_terminal,
    submit_credit,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─────────────────────────────────────────────────────────────────────────────
# The whole provisioning funnel, each hop issued by the role that owns it
# ─────────────────────────────────────────────────────────────────────────────


def test_each_role_performs_the_operations_its_own_role_list_grants(
    api, agent_headers, netops_headers, compliance_headers, logistics_headers
):
    """Walk the funnel to an installed terminal, issuing every hop as the single
    role §4 authorises for it: the clock move and the topology as a
    NetworkOpsEngineer, the licence filing and its coordination as a
    ComplianceOfficer, the plan, the account and the service order as a
    ProvisioningAgent, the shipment and the delivery confirmation as a
    LogisticsCoordinator, and the sky survey plus the self-install as the owning
    Subscriber. No hop may be refused, so no role is over-restricted.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles listed for the requested endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "Endpoints that bring a brand-new resource into existence respond with HTTP 201 Created; endpoints that modify, transition or read an existing resource respond with HTTP 200 OK."
    PRD §3.1: "`GRANTED` on a licence in `PENDING_COORDINATION` moves `license_state` from `PENDING_COORDINATION` to `ACTIVE` and sets `coordination_state` to `COORDINATED`."
    PRD §3.2: "Its `beam_state` is `ACTIVE` when the named licence is `ACTIVE`, and `SUSPENDED` otherwise — a beam created under a licence still in `PENDING_COORDINATION` is born out of service."
    PRD §3.3: "When the admission figure after lazy expiry is at least 1 and the governing beam's `beam_state` is `ACTIVE`, the order moves `PENDING_DETERMINATION → RESERVED`."
    PRD §3.4: "Confirming delivery moves the unit `SHIPPED → DELIVERED` and increases the terminal's `version` by 1."
    PRD §3.4: "Installing a terminal moves it into `INSTALLED` from either `DELIVERED` or `TRANSFER_PENDING`, and can be performed by the owning `Subscriber` or by a `ProvisioningAgent`."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_and_shared_operations
    """
    # NetworkOpsEngineer owns the logical clock.
    validate_success(
        api.set_clock(set_clock_payload(CLOCK_EPOCH), netops_headers),
        expected_status=200,
    )

    # ComplianceOfficer owns the regulatory surface.
    license_record = validate_success(
        api.create_spectrum_license(
            create_spectrum_license_payload(in_motion_permitted=True), compliance_headers
        ),
        expected_status=201,
    )
    coordinated = validate_success(
        api.record_coordination(
            license_record["id"],
            coordination_payload(outcome="GRANTED", coordination_note="no neighbour objection"),
            compliance_headers,
        ),
        expected_status=200,
    )
    assert coordinated["license_state"] == "ACTIVE", (
        "POST /satellite-broadband/spectrum-licenses/{id}/coordination as ComplianceOfficer "
        f"should leave the licence ACTIVE, got {coordinated['license_state']!r}"
    )
    assert coordinated["coordination_state"] == "COORDINATED", (
        "a GRANTED coordination filed by a ComplianceOfficer should leave the licence "
        f"COORDINATED, got {coordinated['coordination_state']!r}"
    )

    # NetworkOpsEngineer owns capacity and topology.
    beam = validate_success(
        api.create_beam(
            create_beam_payload(
                spectrum_license_id=license_record["id"], forward_capacity_mbps=1000
            ),
            netops_headers,
        ),
        expected_status=201,
    )
    assert beam["beam_state"] == "ACTIVE", (
        "POST /satellite-broadband/beams as NetworkOpsEngineer under an ACTIVE licence "
        f"should be born ACTIVE, got {beam['beam_state']!r}"
    )
    cell = validate_success(
        api.create_service_cell(
            create_service_cell_payload(beam_id=beam["id"], max_active_terminals=1),
            netops_headers,
        ),
        expected_status=201,
    )

    # ProvisioningAgent owns the retail funnel.
    plan = validate_success(
        api.create_service_plan(create_service_plan_payload(), agent_headers),
        expected_status=201,
    )
    subscriber = validate_success(
        api.create_subscriber(create_subscriber_payload(), agent_headers),
        expected_status=201,
    )
    order = validate_success(
        api.create_service_order(
            create_service_order_payload(
                subscriber_id=subscriber["id"],
                service_cell_id=cell["id"],
                requested_plan_id=plan["id"],
            ),
            agent_headers,
        ),
        expected_status=201,
    )
    assert order["order_state"] == "RESERVED", (
        "POST /satellite-broadband/service-orders as ProvisioningAgent on a cell with a free "
        f"slot should land RESERVED, got {order['order_state']!r}"
    )

    # LogisticsCoordinator owns hardware movement.
    terminal = validate_success(
        api.create_terminal(
            create_terminal_payload(subscriber_id=subscriber["id"]), logistics_headers
        ),
        expected_status=201,
    )
    delivered = validate_success(
        api.deliver_terminal(terminal["id"], logistics_headers), expected_status=200
    )
    assert delivered["terminal_state"] == "DELIVERED", (
        "POST /satellite-broadband/terminals/{id}/deliver as LogisticsCoordinator should move "
        f"the unit to DELIVERED, got {delivered['terminal_state']!r}"
    )

    # The owning Subscriber surveys and installs.
    owner_headers = make_subscriber_headers(subscriber["id"])
    scan = validate_success(
        api.create_obstruction_scan(
            terminal["id"], obstruction_scan_payload(1, 200), owner_headers
        ),
        expected_status=201,
    )
    assert scan["terminal_id"] == terminal["id"], (
        "POST /satellite-broadband/terminals/{id}/obstruction-scans as the owning Subscriber "
        "should record the survey against that terminal"
    )
    installed = validate_success(
        api.install_terminal(terminal["id"], owner_headers), expected_status=200
    )
    assert installed["terminal_state"] == "INSTALLED", (
        "POST /satellite-broadband/terminals/{id}/install as the owning Subscriber should move "
        f"the unit to INSTALLED, got {installed['terminal_state']!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The same endpoints refused to a role §4 does not list
# ─────────────────────────────────────────────────────────────────────────────


def _seed_environment() -> dict:
    """An ACTIVE + COORDINATED licence, one beam, one single-slot cell, one plan,
    one account and one RESERVED order. Returns the records plus the beam's
    current version so a policy write can carry a fresh concurrency token."""
    env = setup_topology(max_active_terminals=1, forward_capacity_mbps=1000)
    subscriber = create_subscriber(index=1, jurisdiction_code=env["cell"]["jurisdiction_code"])
    order = create_order(subscriber["id"], env["cell"]["id"], env["plan"]["id"])
    assert order["order_state"] == "RESERVED", (
        f"setup expected a RESERVED order, got {order['order_state']!r}"
    )
    env["subscriber"] = subscriber
    env["order"] = order
    env["beam_version"] = get_beam_version(env["beam"]["id"])
    return env


def _attempt_create_beam_as_agent(api, env):
    return api.create_beam(
        create_beam_payload(
            spectrum_license_id=env["license"]["id"],
            beam_code="BEAM-02",
            forward_capacity_mbps=500,
        ),
        TEST_USERS["provisioning_agent_headers"],
    )


def _verify_no_second_beam(api, env):
    _, meta = validate_paginated(api.list_beams(TEST_USERS["network_ops_engineer_headers"]))
    assert meta["total_count"] == 1, (
        "the refused POST /satellite-broadband/beams by a ProvisioningAgent must not create a "
        f"beam; expected 1 beam on file, got total_count {meta['total_count']}"
    )


def _attempt_create_service_cell_as_compliance(api, env):
    return api.create_service_cell(
        create_service_cell_payload(
            beam_id=env["beam"]["id"], cell_code="CELL-002", max_active_terminals=5
        ),
        TEST_USERS["compliance_officer_headers"],
    )


def _verify_no_second_cell(api, env):
    _, meta = validate_paginated(
        api.list_service_cells(TEST_USERS["network_ops_engineer_headers"])
    )
    assert meta["total_count"] == 1, (
        "the refused POST /satellite-broadband/service-cells by a ComplianceOfficer must not "
        f"create a cell; expected 1 cell on file, got total_count {meta['total_count']}"
    )


def _attempt_write_capacity_policy_as_agent(api, env):
    return api.write_capacity_policy(
        env["beam"]["id"],
        capacity_policy_payload(
            expected_beam_version=env["beam_version"],
            oversubscription_limit=6.0,
            deprioritization_grace_gb=50,
        ),
        TEST_USERS["provisioning_agent_headers"],
    )


def _verify_capacity_policy_unchanged(api, env):
    beam = validate_success(
        api.get_beam(env["beam"]["id"], TEST_USERS["network_ops_engineer_headers"])
    )
    assert beam["version"] == env["beam_version"], (
        "the refused POST /satellite-broadband/beams/{id}/capacity-policy by a "
        f"ProvisioningAgent must not mutate the beam; version moved from "
        f"{env['beam_version']} to {beam['version']}"
    )
    assert float(beam["oversubscription_limit"]) == 4.0, (
        "the refused capacity-policy write by a ProvisioningAgent must leave "
        f"oversubscription_limit at 4.0, got {beam['oversubscription_limit']}"
    )
    assert int(beam["deprioritization_grace_gb"]) == 0, (
        "the refused capacity-policy write by a ProvisioningAgent must leave "
        f"deprioritization_grace_gb at 0, got {beam['deprioritization_grace_gb']}"
    )


def _attempt_open_outage_event_as_compliance(api, env):
    return api.create_outage_event(
        create_outage_event_payload(
            beam_id=env["beam"]["id"],
            cause="EQUIPMENT_FAILURE",
            severity="FULL_OUTAGE",
            started_at=CLOCK_EPOCH,
        ),
        TEST_USERS["compliance_officer_headers"],
    )


def _verify_no_outage_event(api, env):
    _, meta = validate_paginated(
        api.list_outage_events(TEST_USERS["network_ops_engineer_headers"])
    )
    assert meta["total_count"] == 0, (
        "the refused POST /satellite-broadband/outage-events by a ComplianceOfficer must not "
        f"open an event; expected 0 events on file, got total_count {meta['total_count']}"
    )


def _attempt_ship_terminal_as_netops(api, env):
    return api.create_terminal(
        create_terminal_payload(
            subscriber_id=env["subscriber"]["id"], serial_number="TRM-9999"
        ),
        TEST_USERS["network_ops_engineer_headers"],
    )


def _verify_no_terminal(api, env):
    _, meta = validate_paginated(
        api.list_terminals(TEST_USERS["logistics_coordinator_headers"])
    )
    assert meta["total_count"] == 0, (
        "the refused POST /satellite-broadband/terminals by a NetworkOpsEngineer must not ship "
        f"a unit; expected 0 terminals on file, got total_count {meta['total_count']}"
    )


def _attempt_open_account_as_logistics(api, env):
    return api.create_subscriber(
        create_subscriber_payload(email="sub9@example.com", full_name="Sub Nine"),
        TEST_USERS["logistics_coordinator_headers"],
    )


def _verify_no_account_claimed_the_email(api, env):
    # The e-mail is unique across accounts, so it is still free exactly when the
    # refused LogisticsCoordinator attempt opened nothing.
    reopened = validate_success(
        api.create_subscriber(
            create_subscriber_payload(email="sub9@example.com", full_name="Sub Nine"),
            TEST_USERS["provisioning_agent_headers"],
        ),
        expected_status=201,
    )
    assert reopened["email"] == "sub9@example.com", (
        "the refused POST /satellite-broadband/subscribers by a LogisticsCoordinator must not "
        "open an account, so a ProvisioningAgent must still be able to claim that e-mail"
    )


def _attempt_suspend_license_as_netops(api, env):
    return api.enforcement_action(
        env["license"]["id"],
        enforcement_action_payload("SUSPEND", reason="attempted by the wrong role"),
        TEST_USERS["network_ops_engineer_headers"],
    )


def _verify_license_still_active(api, env):
    license_record = validate_success(
        api.get_spectrum_license(
            env["license"]["id"], TEST_USERS["compliance_officer_headers"]
        )
    )
    assert license_record["license_state"] == "ACTIVE", (
        "the refused POST /satellite-broadband/spectrum-licenses/{id}/enforcement-action by a "
        f"NetworkOpsEngineer must not suspend the licence, got "
        f"{license_record['license_state']!r}"
    )


def _attempt_cancel_order_as_logistics(api, env):
    return api.cancel_service_order(
        env["order"]["id"],
        cancel_order_payload(cancel_reason="attempted by the wrong role"),
        TEST_USERS["logistics_coordinator_headers"],
    )


def _verify_order_still_reserved(api, env):
    order = validate_success(
        api.get_service_order(env["order"]["id"], TEST_USERS["provisioning_agent_headers"])
    )
    assert order["order_state"] == "RESERVED", (
        "the refused POST /satellite-broadband/service-orders/{id}/cancel by a "
        f"LogisticsCoordinator must leave the order RESERVED, got {order['order_state']!r}"
    )


UNAUTHORIZED_ROLE_CASES = [
    pytest.param(
        _attempt_create_beam_as_agent,
        _verify_no_second_beam,
        "POST /satellite-broadband/beams",
        "ProvisioningAgent",
        id="create_beam_as_provisioning_agent",
    ),
    pytest.param(
        _attempt_create_service_cell_as_compliance,
        _verify_no_second_cell,
        "POST /satellite-broadband/service-cells",
        "ComplianceOfficer",
        id="create_service_cell_as_compliance_officer",
    ),
    pytest.param(
        _attempt_write_capacity_policy_as_agent,
        _verify_capacity_policy_unchanged,
        "POST /satellite-broadband/beams/{id}/capacity-policy",
        "ProvisioningAgent",
        id="write_capacity_policy_as_provisioning_agent",
    ),
    pytest.param(
        _attempt_open_outage_event_as_compliance,
        _verify_no_outage_event,
        "POST /satellite-broadband/outage-events",
        "ComplianceOfficer",
        id="open_outage_event_as_compliance_officer",
    ),
    pytest.param(
        _attempt_ship_terminal_as_netops,
        _verify_no_terminal,
        "POST /satellite-broadband/terminals",
        "NetworkOpsEngineer",
        id="ship_terminal_as_network_ops_engineer",
    ),
    pytest.param(
        _attempt_open_account_as_logistics,
        _verify_no_account_claimed_the_email,
        "POST /satellite-broadband/subscribers",
        "LogisticsCoordinator",
        id="open_account_as_logistics_coordinator",
    ),
    pytest.param(
        _attempt_suspend_license_as_netops,
        _verify_license_still_active,
        "POST /satellite-broadband/spectrum-licenses/{id}/enforcement-action",
        "NetworkOpsEngineer",
        id="suspend_license_as_network_ops_engineer",
    ),
    pytest.param(
        _attempt_cancel_order_as_logistics,
        _verify_order_still_reserved,
        "POST /satellite-broadband/service-orders/{id}/cancel",
        "LogisticsCoordinator",
        id="cancel_service_order_as_logistics_coordinator",
    ),
]


@pytest.mark.parametrize(
    "attempt, verify_nothing_was_written, endpoint, role", UNAUTHORIZED_ROLE_CASES
)
def test_role_absent_from_the_endpoints_role_list_is_refused(
    api, attempt, verify_nothing_was_written, endpoint, role
):
    """Eight cross-role attempts, one per exclusive-operation family, each issued
    by a well-formed caller whose role §4 does not list for that endpoint:
    creating a beam as a ProvisioningAgent, creating a coverage cell as a
    ComplianceOfficer, writing a beam's capacity policy as a ProvisioningAgent,
    opening an outage event as a ComplianceOfficer, shipping a terminal as a
    NetworkOpsEngineer, opening a subscriber account as a LogisticsCoordinator,
    filing a licence enforcement action as a NetworkOpsEngineer, and cancelling a
    service order as a LogisticsCoordinator. Each is refused with
    ERR_UNAUTHORIZED and leaves no trace; for the account case the absence of a
    write is observed by re-claiming the same unique e-mail afterwards.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles listed for the requested endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.11: "**Authorisation** — the acting role appears in the endpoint's role list in §4. `ERR_UNAUTHORIZED`, 403. All endpoints."
    PRD §2.11: "When a request violates several rules at once, exactly one error is returned, and which one is fixed rather than incidental."
    PRD §2.11: "**Uniqueness** — `license_code`, `beam_code`, `cell_code`, `plan_code`, a subscriber's `email` and a terminal's `serial_number` (including a `replacement_serial_number`) are each unique across their own collection."

    Design: Corner/rbac/every_role_is_refused_the_other_roles_exclusive_operations
    """
    env = _seed_environment()

    response = attempt(api, env)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    verify_nothing_was_written(api, env)


# ─────────────────────────────────────────────────────────────────────────────
# Subscriber identity is entity backed, so authorisation is per row
# ─────────────────────────────────────────────────────────────────────────────


def _seed_two_subscribers_with_delivered_terminals() -> dict:
    """Two accounts, each holding one DELIVERED terminal and no survey yet."""
    env = setup_topology(max_active_terminals=2, forward_capacity_mbps=1000)
    first = create_subscriber(index=1, jurisdiction_code=env["cell"]["jurisdiction_code"])
    second = create_subscriber(index=2, jurisdiction_code=env["cell"]["jurisdiction_code"])
    first_terminal = ship_terminal(first["id"], index=1)
    second_terminal = ship_terminal(second["id"], index=2)
    deliver_terminal(first_terminal["id"])
    deliver_terminal(second_terminal["id"])
    env.update(
        {
            "first_subscriber": first,
            "second_subscriber": second,
            "first_terminal": first_terminal,
            "second_terminal": second_terminal,
        }
    )
    return env


def test_subscriber_cannot_record_a_survey_on_another_subscribers_terminal(api):
    """The second account holds the very same shared permission on
    POST /satellite-broadband/terminals/{id}/obstruction-scans, yet aiming it at
    the first account's terminal is refused because the comparison is against
    that terminal's own subscriber_id. The owner's byte-identical call is then
    accepted, and only that one survey is stored.

    PRD §2.1: "When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting subscriber account, and every ownership check compares the target resource's subscriber chain to that value."
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "This ownership check runs on every endpoint whose authorised-role list includes `Subscriber`, and on no other endpoint."
    PRD §3.4: "Either the owning `Subscriber` or a `ProvisioningAgent` may record one, supplying `obstructed_sample_count` — the number of sky samples blocked by obstruction, which must be at least 0 and no greater than the total — and `total_sample_count`, the number of samples taken, which must be strictly greater than 0."

    Design: Corner/rbac/a_subscriber_cannot_touch_another_subscribers_terminal
    """
    env = _seed_two_subscribers_with_delivered_terminals()
    target_terminal_id = env["first_terminal"]["id"]
    intruder_headers = make_subscriber_headers(env["second_subscriber"]["id"])
    owner_headers = make_subscriber_headers(env["first_subscriber"]["id"])

    refused = api.create_obstruction_scan(
        target_terminal_id, obstruction_scan_payload(1, 200), intruder_headers
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    _, meta = validate_paginated(
        api.list_obstruction_scans(
            target_terminal_id, TEST_USERS["logistics_coordinator_headers"]
        )
    )
    assert meta["total_count"] == 0, (
        "the refused POST /satellite-broadband/terminals/{id}/obstruction-scans by a "
        "non-owning Subscriber must store nothing; expected total_count 0, got "
        f"{meta['total_count']}"
    )

    accepted = validate_success(
        api.create_obstruction_scan(
            target_terminal_id, obstruction_scan_payload(1, 200), owner_headers
        ),
        expected_status=201,
    )
    assert accepted["terminal_id"] == target_terminal_id, (
        "POST /satellite-broadband/terminals/{id}/obstruction-scans by the owning Subscriber "
        f"should record the survey against {target_terminal_id}, got {accepted['terminal_id']}"
    )

    _, meta_after = validate_paginated(
        api.list_obstruction_scans(
            target_terminal_id, TEST_USERS["logistics_coordinator_headers"]
        )
    )
    assert meta_after["total_count"] == 1, (
        "only the owning Subscriber's survey should be on file for this terminal; expected "
        f"total_count 1, got {meta_after['total_count']}"
    )


def test_subscriber_cannot_read_another_subscribers_terminal(api):
    """GET /satellite-broadband/terminals/{id} lists Subscriber among its
    authorised roles, so the ownership check runs on it: the second account is
    refused on the first account's terminal while the first account reads the
    same record.

    PRD §2.1: "When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting subscriber account, and every ownership check compares the target resource's subscriber chain to that value."
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "This ownership check runs on every endpoint whose authorised-role list includes `Subscriber`, and on no other endpoint."

    Design: Corner/rbac/a_subscriber_cannot_touch_another_subscribers_terminal
    """
    env = _seed_two_subscribers_with_delivered_terminals()
    target_terminal_id = env["first_terminal"]["id"]

    refused = api.get_terminal(
        target_terminal_id, make_subscriber_headers(env["second_subscriber"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    owned = validate_success(
        api.get_terminal(
            target_terminal_id, make_subscriber_headers(env["first_subscriber"]["id"])
        ),
        expected_status=200,
    )
    assert owned["id"] == target_terminal_id, (
        "GET /satellite-broadband/terminals/{id} by the owning Subscriber should return that "
        f"terminal, got {owned['id']}"
    )
    assert owned["subscriber_id"] == env["first_subscriber"]["id"], (
        "the terminal the owning Subscriber reads must be the one whose subscriber_id is that "
        "account"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Segregation of duties on an outage credit
# ─────────────────────────────────────────────────────────────────────────────


def test_the_operator_who_submitted_a_credit_cannot_also_decide_it(api):
    """One human identifier, ops-user-7, submits the credit as a
    ProvisioningAgent and then attempts
    POST /satellite-broadband/outage-credits/{id}/decide as a ComplianceOfficer.
    The credit is genuinely SUBMITTED, so the review-state gate passes and the
    separation rule is what refuses the call. A second ComplianceOfficer with a
    different X-User-ID then decides the very same credit.

    PRD §2.1: "One separation rule cuts across the compliance role and is worth stating up front: a `ComplianceOfficer` may not decide an outage credit whose `submitted_by_user_id` equals that officer's own `X-User-ID`."
    PRD §2.1: "The attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "It is legal only from `SUBMITTED`, and the deciding operator's `X-User-ID` must differ from the credit's `submitted_by_user_id`, or the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "On success the credit moves `DRAFT → SUBMITTED` and `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
    PRD §3.8: "An approval moves the credit `SUBMITTED → APPROVED`, computes `final_credit_cents` by the final per-day rule, and increases the subscriber's `credit_balance_cents` by that final amount."

    Design: Corner/rbac/the_operator_who_submitted_a_credit_cannot_also_decide_it
    """
    submitting_user_id = "ops-user-7"
    deciding_user_id = "compliance-user-2"

    env = setup_drafted_credit(
        cause="EQUIPMENT_FAILURE", severity="FULL_OUTAGE", started_at=CLOCK_EPOCH
    )
    assert env["credit"] is not None, (
        "setup expected the outage resolution to draft one credit for the impaired subscription"
    )
    credit = submit_credit(
        env["credit"]["id"], make_provisioning_agent_headers(submitting_user_id)
    )
    assert credit["credit_state"] == "SUBMITTED", (
        f"setup expected a SUBMITTED credit, got {credit['credit_state']!r}"
    )
    assert credit["submitted_by_user_id"] == submitting_user_id, (
        "submission must stamp submitted_by_user_id with the submitting operator's X-User-ID; "
        f"expected {submitting_user_id!r}, got {credit['submitted_by_user_id']!r}"
    )

    refused = api.decide_outage_credit(
        credit["id"],
        credit_decision_payload(
            decision="APPROVE", decision_reason="same operator deciding their own submission"
        ),
        make_compliance_officer_headers(submitting_user_id),
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    unchanged = validate_success(
        api.get_outage_credit(credit["id"], TEST_USERS["compliance_officer_headers"])
    )
    assert unchanged["credit_state"] == "SUBMITTED", (
        "the refused decide by the submitting operator must leave the credit SUBMITTED, got "
        f"{unchanged['credit_state']!r}"
    )
    assert not unchanged.get("decided_by_user_id"), (
        "the refused decide by the submitting operator must not stamp decided_by_user_id, got "
        f"{unchanged.get('decided_by_user_id')!r}"
    )
    assert not unchanged.get("final_credit_cents"), (
        "the refused decide by the submitting operator must leave final_credit_cents empty, "
        f"got {unchanged.get('final_credit_cents')!r}"
    )

    approved = validate_success(
        api.decide_outage_credit(
            credit["id"],
            credit_decision_payload(decision="APPROVE", decision_reason="independent review"),
            make_compliance_officer_headers(deciding_user_id),
        ),
        expected_status=200,
    )
    assert approved["credit_state"] == "APPROVED", (
        "a ComplianceOfficer whose X-User-ID differs from submitted_by_user_id should be able "
        f"to approve the credit, got credit_state {approved['credit_state']!r}"
    )
    assert approved["submitted_by_user_id"] == submitting_user_id, (
        "approval must not disturb submitted_by_user_id; expected "
        f"{submitting_user_id!r}, got {approved['submitted_by_user_id']!r}"
    )
    assert approved["decided_by_user_id"] == deciding_user_id, (
        "approval must stamp decided_by_user_id with the deciding operator's X-User-ID; "
        f"expected {deciding_user_id!r}, got {approved['decided_by_user_id']!r}"
    )
