"""Service-order workflow: the branching custody fork, the destruction cascade,
cancellation compensation, invalid transitions, mode/precondition enforcement,
and certificate lifecycle.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_field_technician_headers,
    make_destruction_witness_headers,
    setup_account_with_rate_card,
    setup_onsite_order_en_route,
    setup_onsite_order_shredded,
    setup_offsite_order_at_plant,
    create_container,
    create_order,
)
from test_helpers import factories as f

CO = TEST_USERS["compliance_officer_headers"]
AM = TEST_USERS["account_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


# ===========================================================================
# non_linear_state_machine / service_order_branching_fork_onsite_vs_plant
# ===========================================================================
def test_onsite_fork_reaches_shredded_and_issues_certificate(api):
    """PRD §3.4: "An on-site order is shredded in place by a FieldTechnician,
    advancing EN_ROUTE to the terminal ON_SITE_SHREDDED."

    PRD §3.6: "The second hop auto-issues a destruction certificate in status
    ISSUED, carrying the order's order_id and account_id, a server-minted
    certificate_no that is monotonic per account in order of issuance, a
    destroyed_weight_kg snapshot equal to the order's finalized billed_weight_kg,
    and a witnessed_by identifier recorded at issuance."

    The on-site branch's distinct side effect is the issued certificate.

    Design: Difficulty/non_linear_state_machine/service_order_branching_fork_onsite_vs_plant
    """
    state = setup_onsite_order_en_route(tech_id="tech-1", weigh_in=True, gross_weight_kg=70.0)
    shred = validate_success(api.shred_on_site(state["order"]["id"], state["tech_headers"]), 200)
    assert shred["status"] == "ON_SITE_SHREDDED", f"got {shred['status']}"
    data, meta = validate_paginated(
        api.list_certificates(CO, params={"order_id": state["order"]["id"]}))
    assert len(data) == 1, f"exactly one certificate, got {len(data)}"
    assert data[0]["status"] == "ISSUED", f"got {data[0]['status']}"


def test_onsite_fork_is_terminal(api):
    """PRD §3.4: "An on-site order is shredded in place by a FieldTechnician,
    advancing EN_ROUTE to the terminal ON_SITE_SHREDDED."

    Reaching ON_SITE_SHREDDED leaves the order in a terminal state distinct from
    the off-site DESTROYED path.

    Design: Difficulty/non_linear_state_machine/service_order_branching_fork_onsite_vs_plant
    """
    state = setup_onsite_order_shredded(tech_id="tech-1", gross_weight_kg=70.0)
    order = validate_success(api.get_order(state["order"]["id"], AM), 200)
    assert order["status"] == "ON_SITE_SHREDDED"


# ===========================================================================
# transitive_cascade / destroy_to_certificate_to_invoice_depth3
# ===========================================================================
def test_destroy_cascades_to_certificate_and_invoice(api):
    """PRD §3.6: "The third hop, fired by the certificate's issuance, creates a
    destruction invoice in status ISSUED, carrying the order's order_id and
    account_id, the certificate_id of the certificate that triggered it, and a
    line_cents snapshot equal to the order's finalized order_charge_cents."

    OFF_SITE ONE_TIME order over one BIN (cap 40/tare 4.0), gross 36 -> net 32 ->
    final 32*8 = 256. After /destroy: one ISSUED certificate (destroyed_weight_kg
    32.0) and one invoice with line_cents 256.

    Design: Difficulty/transitive_cascade/destroy_to_certificate_to_invoice_depth3
    """
    state = setup_offsite_order_at_plant(tech_id="tech-1", gross_weight_kg=36.0,
                                         capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME")
    witness_headers = make_destruction_witness_headers("witness-9")
    destroyed = validate_success(api.destroy_order(
        state["order"]["id"], f.destroy_payload("witness-9"), witness_headers), 200)
    assert destroyed["status"] == "DESTROYED", f"got {destroyed['status']}"

    certs, _ = validate_paginated(
        api.list_certificates(CO, params={"order_id": state["order"]["id"]}))
    assert len(certs) == 1, f"one certificate, got {len(certs)}"
    assert certs[0]["status"] == "ISSUED"
    assert certs[0]["destroyed_weight_kg"] == 32.0, f"got {certs[0]['destroyed_weight_kg']}"

    invs, _ = validate_paginated(
        api.list_destruction_invoices(CO, params={"order_id": state["order"]["id"]}))
    assert len(invs) == 1, f"one invoice, got {len(invs)}"
    assert invs[0]["line_cents"] == 256, f"got {invs[0]['line_cents']}"


def test_destroy_finalizes_order_status(api):
    """PRD §3.5: "The final destruction at the plant is performed by a
    DestructionWitness, advancing AT_PLANT to the terminal DESTROYED."

    The first cascade hop finalizes the order to DESTROYED before the certificate
    and invoice are issued.

    Design: Difficulty/transitive_cascade/destroy_to_certificate_to_invoice_depth3
    """
    state = setup_offsite_order_at_plant(tech_id="tech-1", gross_weight_kg=36.0,
                                         capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME")
    witness_headers = make_destruction_witness_headers("witness-9")
    destroyed = validate_success(api.destroy_order(
        state["order"]["id"], f.destroy_payload("witness-9"), witness_headers), 200)
    assert destroyed["status"] == "DESTROYED"


# ===========================================================================
# compensating_invariant / cancel_conserves_placed_container_count
# ===========================================================================
def test_cancel_reverts_containers_to_placed(api):
    """PRD §3.6: "A cancellation is a compensating action: every serviced
    container reverts to PLACED, which conserves the global count of placed
    containers against the pre-dispatch baseline."

    Two CONSOLE containers dispatched to IN_SERVICE; cancel from EN_ROUTE returns
    both to PLACED, restoring the count of two PLACED containers.

    Design: Difficulty/compensating_invariant/cancel_conserves_placed_container_count
    """
    state = setup_onsite_order_en_route(
        tech_id="tech-1",
        container_specs=[
            {"container_type": "CONSOLE", "capacity_kg": 50, "tare_weight_kg": 8.0},
            {"container_type": "CONSOLE", "capacity_kg": 30, "tare_weight_kg": 5.0},
        ],
        weigh_in=False,
    )
    c1, c2 = state["containers"][0], state["containers"][1]
    cancelled = validate_success(api.cancel_order(state["order"]["id"], AM), 200)
    assert cancelled["status"] == "CANCELLED", f"got {cancelled['status']}"
    assert validate_success(api.get_container(c1["id"], AM), 200)["status"] == "PLACED"
    assert validate_success(api.get_container(c2["id"], AM), 200)["status"] == "PLACED"
    placed, _ = validate_paginated(api.list_containers(
        AM, params={"account_id": state["account"]["id"], "status": "PLACED"}))
    assert len(placed) == 2, f"two PLACED containers restored, got {len(placed)}"


def test_cancel_from_en_route_terminal(api):
    """PRD §3.6: "An order may be cancelled by an AccountManager while it is still
    early in its life - specifically while it is in SCHEDULED or EN_ROUTE."

    PRD §3.6: "Cancellation moves the order to the terminal CANCELLED."

    Design: Difficulty/compensating_invariant/cancel_conserves_placed_container_count
    """
    state = setup_onsite_order_en_route(
        tech_id="tech-1",
        container_specs=[
            {"container_type": "CONSOLE", "capacity_kg": 50, "tare_weight_kg": 8.0},
            {"container_type": "CONSOLE", "capacity_kg": 30, "tare_weight_kg": 5.0},
        ],
        weigh_in=False,
    )
    cancelled = validate_success(api.cancel_order(state["order"]["id"], AM), 200)
    assert cancelled["status"] == "CANCELLED"


# ===========================================================================
# compensating_invariant / cancel_conserves_provisional_charge
# ===========================================================================
def test_cancel_zeroes_provisional_charge_and_weight(api):
    """PRD §3.6: "the order's order_charge_cents and billed_weight_kg are both
    reset to 0, fully reversing the provisional charge."

    A SCHEDULED ON_SITE order over two CONSOLE (estimate 80) carries a provisional
    4900; cancel resets order_charge_cents and billed_weight_kg to 0.

    Design: Difficulty/compensating_invariant/cancel_conserves_provisional_charge
    """
    account, location, rate_card = setup_account_with_rate_card()
    c1 = create_container(account["id"], location["id"], "CONSOLE", 50, 8.0)
    c2 = create_container(account["id"], location["id"], "CONSOLE", 30, 5.0)
    created = validate_success(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[c1["id"], c2["id"]]), AM), 201)
    assert created["order_charge_cents"] == 4900, f"provisional, got {created['order_charge_cents']}"
    cancelled = validate_success(api.cancel_order(created["id"], AM), 200)
    assert cancelled["order_charge_cents"] == 0, f"got {cancelled['order_charge_cents']}"
    assert cancelled["billed_weight_kg"] == 0, f"got {cancelled['billed_weight_kg']}"


def test_cancel_from_scheduled_is_terminal(api):
    """PRD §3.6: "Cancellation moves the order to the terminal CANCELLED."

    Cancelling a never-dispatched SCHEDULED order moves it to CANCELLED.

    Design: Difficulty/compensating_invariant/cancel_conserves_provisional_charge
    """
    account, location, rate_card = setup_account_with_rate_card()
    c1 = create_container(account["id"], location["id"], "CONSOLE", 50, 8.0)
    c2 = create_container(account["id"], location["id"], "CONSOLE", 30, 5.0)
    created = validate_success(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[c1["id"], c2["id"]]), AM), 201)
    cancelled = validate_success(api.cancel_order(created["id"], AM), 200)
    assert cancelled["status"] == "CANCELLED"


# ===========================================================================
# Corner: state_machines / dispatch_from_at_plant_invalid
# ===========================================================================
def test_dispatch_from_at_plant_rejected(api):
    """PRD §3.4: "Dispatch is defined only for orders in SCHEDULED (otherwise
    ERR_ORDER_NOT_SCHEDULED) whose service_mode is ON_SITE or OFF_SITE_PICKUP."

    An order already AT_PLANT cannot be dispatched; the order is unchanged.

    Design: Corner/state_machines/dispatch_from_at_plant_invalid
    """
    state = setup_offsite_order_at_plant(tech_id="tech-1", gross_weight_kg=36.0,
                                         capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME")
    tech_headers = make_field_technician_headers("tech-1")
    validate_error(api.dispatch_order(state["order"]["id"], tech_headers),
                   ApiErrorId.ERR_ORDER_NOT_SCHEDULED.value)
    order = validate_success(api.get_order(state["order"]["id"], AM), 200)
    assert order["status"] == "AT_PLANT", "unchanged after rejected dispatch"


# ===========================================================================
# Corner: state_machines / terminal_destroyed_no_further_transitions
# ===========================================================================
def test_cancel_from_destroyed_rejected(api):
    """PRD §3.6: "a cancel attempt from any other state is rejected with
    ERR_ORDER_NOT_CANCELLABLE."

    A terminal DESTROYED order cannot be cancelled.

    Design: Corner/state_machines/terminal_destroyed_no_further_transitions
    """
    state = setup_offsite_order_at_plant(tech_id="tech-1", gross_weight_kg=36.0,
                                         capacity_kg=40, tare_weight_kg=4.0, cadence="ONE_TIME")
    witness_headers = make_destruction_witness_headers("witness-9")
    get_success_data(api.destroy_order(state["order"]["id"], f.destroy_payload("witness-9"),
                                       witness_headers))
    validate_error(api.cancel_order(state["order"]["id"], AM),
                   ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)


# ===========================================================================
# Corner: state_machines / shred_on_site_requires_weigh_in
# ===========================================================================
def test_shred_on_site_requires_weight_ticket(api):
    """PRD §3.4: "this is defined only when the order is in EN_ROUTE (otherwise
    ERR_ORDER_NOT_EN_ROUTE), only when service_mode is ON_SITE (otherwise
    ERR_MODE_NOT_ON_SITE), and only when at least one weight ticket already exists
    for the order (otherwise ERR_WEIGH_IN_REQUIRED)."

    An EN_ROUTE on-site order with no weigh-in is rejected on shred.

    Design: Corner/state_machines/shred_on_site_requires_weigh_in
    """
    state = setup_onsite_order_en_route(tech_id="tech-1", weigh_in=False)
    validate_error(api.shred_on_site(state["order"]["id"], state["tech_headers"]),
                   ApiErrorId.ERR_WEIGH_IN_REQUIRED.value)


# ===========================================================================
# Corner: state_machines / drop_off_confirm_pickup_wrong_mode
# ===========================================================================
def test_confirm_pickup_from_scheduled_requires_drop_off_mode(api):
    """PRD §3.4: "A FieldTechnician confirms the drop-off straight from SCHEDULED
    to PICKED_UP; this is defined only when the order is in SCHEDULED (otherwise
    ERR_ORDER_NOT_DROP_OFF_READY), only when service_mode is DROP_OFF (otherwise
    ERR_MODE_NOT_DROP_OFF)."

    An ON_SITE order still in SCHEDULED hitting confirm-pickup is rejected for the
    wrong mode.

    Design: Corner/state_machines/drop_off_confirm_pickup_wrong_mode
    """
    account, location, rate_card = setup_account_with_rate_card()
    c1 = create_container(account["id"], location["id"], "CONSOLE", 50, 8.0)
    order = validate_success(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[c1["id"]], assigned_tech_id="tech-1"), AM), 201)
    tech_headers = make_field_technician_headers("tech-1")
    validate_error(api.confirm_pickup(order["id"], tech_headers),
                   ApiErrorId.ERR_MODE_NOT_DROP_OFF.value)


# ===========================================================================
# Corner: errors / void_certificate_then_listed_voided
# ===========================================================================
def test_void_certificate_flips_to_voided(api):
    """PRD §3.6: "A ComplianceOfficer may void an issued certificate, moving its
    status from ISSUED to VOIDED."

    Voiding the certificate issued by an on-site shred flips its status to VOIDED.

    Design: Corner/errors/void_certificate_then_listed_voided
    """
    state = setup_onsite_order_shredded(tech_id="tech-1", gross_weight_kg=70.0)
    certs, _ = validate_paginated(
        api.list_certificates(CO, params={"order_id": state["order"]["id"]}))
    assert len(certs) == 1
    cert_id = certs[0]["id"]
    voided = validate_success(api.void_certificate(cert_id, CO), 200)
    assert voided["status"] == "VOIDED", f"got {voided['status']}"


# ===========================================================================
# Corner: errors / cancel_after_certificate_issued
# ===========================================================================
def test_cancel_after_shred_rejected(api):
    """PRD §3.6: "a cancel attempt from any other state is rejected with
    ERR_ORDER_NOT_CANCELLABLE."

    An ON_SITE_SHREDDED order (terminal, certificate issued) is no longer in
    SCHEDULED/EN_ROUTE, so cancel is rejected.

    Design: Corner/errors/cancel_after_certificate_issued
    """
    state = setup_onsite_order_shredded(tech_id="tech-1", gross_weight_kg=70.0)
    validate_error(api.cancel_order(state["order"]["id"], AM),
                   ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)
