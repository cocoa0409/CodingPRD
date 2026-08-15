"""Container receipt cascades into lots, projects, invoices, and the credit
ledger; damage-claim amounts; container OCC."""
from test_helpers import (
    TEST_USERS,
    add_container_line,
    allocate_current_version,
    api_client,
    assert_lot_invariants,
    book_container,
    create_active_installer,
    create_damage_claim_payload,
    create_locked_project,
    create_module_product,
    create_tariff,
    get_lot,
    receive_container,
    seed_catalog,
    set_clock,
    setup_project_with_on_hand_lot,
    ship_allocation,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_container_payload

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_container_receive_transitions_lot_on_hand(api):
    """PRD section 3.3: "On acceptance, and for each line, the system computes
    the final landed cost per §3.4; increases the lot's `qty_on_hand` by the
    received quantity; increases the lot's `qty_quarantined` by the damaged
    quantity, those units being held for inspection and unavailable for
    allocation; sets the lot's `unit_cost_cents_final`; stamps the lot's
    `received_at`; and transitions the lot `IN_TRANSIT` → `ON_HAND`."

    Design: Difficulty/transitive_cascade/container_receive_cascades_through_lot_to_project_and_installer
    """
    set_clock()
    catalog = seed_catalog()
    installer = create_active_installer()
    create_locked_project(installer["id"], catalog["module"]["id"],
                          catalog["inverter"]["id"], module_qty=5)
    container = book_container()
    line = add_container_line(container["id"], catalog["module"]["id"], 5,
                              50000)

    before = get_lot(line["inventory_lot_id"])
    assert before["status"] == "IN_TRANSIT"
    assert before["qty_on_hand"] == 0
    assert before["unit_cost_cents_final"] is None

    received = receive_container(
        container["id"],
        [{"container_line_id": line["id"], "qty_received": 5,
          "qty_damaged": 0}],
    )
    assert received["status"] == "RECEIVED"
    assert received["actual_arrival_utc"] is not None

    # Link 1 of the cascade: receipt mutates the lot. With zero freight and
    # insurance and a 10% duty, the final unit cost is 50000 + 5000 = 55000.
    lot = get_lot(line["inventory_lot_id"])
    assert lot["status"] == "ON_HAND"
    assert lot["qty_on_hand"] == 5
    assert lot["unit_cost_cents_final"] == 55000
    assert lot["received_at"] is not None
    assert_lot_invariants(lot)


def test_receive_to_ship_cascade_reaches_invoice_and_exposure(api):
    """PRD section 3.5: "It moves `ALLOCATED` → `PARTIALLY_SHIPPED` when at
    least one allocation has shipped while at least one remains `OPEN`, and
    `ALLOCATED` → `SHIPPED` when every non-cancelled allocation has shipped —
    the moment that also issues the progress invoice (§3.7)."
    PRD section 3.2: "An installer's `credit_exposure_cents` is the sum of
    `balance_due_cents` across that installer's invoices in `OPEN`,
    `PARTIALLY_PAID`, or `PAST_DUE` status, excluding `WRITE_OFF` invoices
    entirely".

    Design: Difficulty/transitive_cascade/container_receive_cascades_through_lot_to_project_and_installer
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=5,
                                         progress_payment_pct_bp=10000)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]

    exposure_before = validate_success(api_client.get_installer(inst_id, OFFICER), 200)
    assert exposure_before["credit_exposure_cents"] == 0

    allocation = allocate_current_version(proj_id, inst_id,
                                          ctx["lot"]["id"], 5)
    ship_allocation(allocation["id"])

    project = validate_success(api_client.get_project(proj_id, MANAGER), 200)
    assert project["fulfillment_status"] == "SHIPPED"
    assert project["payment_status"] == "PROGRESS_BILLED"

    # 5 units x 55000c final cost, billed at 100% progress.
    invoices = validate_success(
        api_client.list_project_invoices(proj_id, MANAGER), 200
    )
    assert len(invoices) == 1
    assert invoices[0]["invoice_kind"] == "PROGRESS"
    assert invoices[0]["amount_cents"] == 275000
    assert invoices[0]["balance_due_cents"] == 275000

    exposure_after = validate_success(api_client.get_installer(inst_id, OFFICER), 200)
    assert exposure_after["credit_exposure_cents"] == 275000, (
        f"exposure must equal the open invoice balance 275000, "
        f"got {exposure_after['credit_exposure_cents']}"
    )


def test_damage_claim_amount_uses_base_plus_freight(api):
    """PRD section 3.9: "the freight per unit is the container's total
    `freight_cost_cents` divided by the total booked units across all of its
    lines, rounded half up to a whole cent, and the claim amount is the
    damaged quantity multiplied by the sum of the line's
    `declared_unit_value_cents` and that freight-per-unit figure. Marine
    insurance is deliberately excluded from damage claims — the claim recovers
    base value plus freight only."
    Freight per unit = 10000 / 10 = 1000; claim = 2 x (50000 + 1000) = 102000.

    Design: Corner/calculations/damage_claim_amount_uses_base_plus_freight
    """
    set_clock()
    create_tariff("8541.43", 1000)
    module = create_module_product(sku="M")
    container = book_container(freight_cost_cents=10000,
                               insurance_cost_cents=5000)
    line = add_container_line(container["id"], module["id"], 10, 50000)
    receive_container(
        container["id"],
        [{"container_line_id": line["id"], "qty_received": 8,
          "qty_damaged": 2}],
    )

    lot = get_lot(line["inventory_lot_id"])
    assert lot["qty_quarantined"] == 2, "damaged units are quarantined"

    claim = validate_success(
        api_client.create_damage_claim(
            container["id"],
            create_damage_claim_payload(line["id"], 2),
            ADMIN,
        ),
        201,
    )
    assert claim["status"] == "DRAFT"

    filed = validate_success(api_client.file_damage_claim(claim["id"], ADMIN), 200)
    assert filed["status"] == "FILED"
    assert filed["filed_at"] is not None
    assert filed["claimed_amount_cents"] == 102000, (
        f"claim amount must exclude insurance: 2 x (50000 + 1000) = 102000, "
        f"got {filed['claimed_amount_cents']}"
    )


def test_occ_container_receive_with_stale_version_rejected(api):
    """PRD section 2.8: "If the container's current `version` does not match —
    because another writer has since marked it departed, marked it arrived, or
    revised its ETA or cost figures — the receipt is rejected with
    `ERR_STALE_CONTAINER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_container_receive_with_stale_version_rejected
    """
    set_clock()
    create_tariff("8541.43", 1000)
    module = create_module_product(sku="M")
    container = validate_success(
        api_client.create_container(create_container_payload(), ADMIN), 201
    )
    line = add_container_line(container["id"], module["id"], 5, 50000)

    # Observe the version at departure; the arrival call then advances it.
    departed = validate_success(
        api_client.depart_container(container["id"], ADMIN), 200
    )
    validate_success(api_client.arrive_container(container["id"], ADMIN), 200)

    resp = api_client.receive_container(
        container["id"],
        {
            "expected_container_version": departed["version"],
            "line_receipts": [{"container_line_id": line["id"],
                               "qty_received": 5, "qty_damaged": 0}],
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CONTAINER_VERSION)
