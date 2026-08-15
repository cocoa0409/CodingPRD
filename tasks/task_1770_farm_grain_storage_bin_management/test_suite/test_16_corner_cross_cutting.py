"""Corner queue / cross-cutting layers + consistency model — OCC stale
version, derived inventory reconciliation, immediate visibility of
settlement."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_bin_with_lot, setup_dispatched_loadout,
    create_contract,
    get_bin, get_contract, get_lot,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_loadout_payload, deliver_payload

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


def test_occ_stale_contract_version_rejected(api):
    """PRD section 2.8: "The scheduling request must carry
    `expected_contract_version`, a non-optional field holding the `version`
    of the target contract as the client last observed it. If that value
    does not match the contract's current `version` at the moment the
    write is evaluated — because the contract has been mutated since the
    client read it, whether by another load-out committing bushels, a
    settlement posting or reversing, a posture hold or release, or an
    assessment sweep — the request is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412) and no load-out is created".

    A client that observed version 1 sees its second create rejected after
    the first create bumped the version to 2.

    Design: Corner/cross_cutting_layers/occ_stale_contract_version_rejected
    """
    b, lot = setup_bin_with_lot(
        bin_name="BIN-OC", original_bu=2000.00)
    con = create_contract(contracted_bu=2000.00)
    stale_version = con["version"]

    ok = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], stale_version, planned_bu=100.00,
        scheduled_start="2026-08-10T08:00:00Z",
        scheduled_end="2026-08-10T12:00:00Z"), SM)
    validate_success(ok, expected_status=201)

    con_now = get_contract(con["id"])
    assert con_now["version"] == stale_version + 1

    stale = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], stale_version, planned_bu=100.00,
        scheduled_start="2026-08-11T08:00:00Z",
        scheduled_end="2026-08-11T12:00:00Z"), SM)
    validate_error(stale, ApiErrorId.ERR_STALE_CONTRACT_VERSION,
                   expected_status=412)


def test_derived_inventory_reconciliation(api):
    """PRD section 3.1: "The `current_inventory_bu` of a bin is at all
    times the sum of `current_bu` over every lot assigned to that bin,
    recomputed whenever lot inventory moves".
    PRD section 3.6: "The bin's `current_inventory_bu` and posture are
    recomputed to close the loop."

    Bin inventory tracks the waterfall debit on confirm (973.00 -> 496.35)
    and is restored exactly by void (496.35 -> 973.00).

    Design: Corner/cross_cutting_layers/derived_inventory_reconciliation
    """
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-DI", original_bu=1000.00, fill_moisture_pct=17.0,
        contracted_bu=2000.00, planned_bu=476.65,
    )
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 486.50, "moisture_pct": 16.5},
        ],
    ), SM))
    # Deliver alone does not debit lots
    assert get_bin(b["id"])["current_inventory_bu"] == pytest.approx(
        973.00, abs=1e-9)

    get_success_data(api_client.confirm_settlement(lo["id"], SM))
    assert get_bin(b["id"])["current_inventory_bu"] == pytest.approx(
        496.35, abs=1e-9)

    get_success_data(api_client.void_settlement(lo["id"], SM))
    assert get_bin(b["id"])["current_inventory_bu"] == pytest.approx(
        973.00, abs=1e-9)


def test_immediate_visibility_of_settlement(api):
    """PRD section 3.6: "Confirmation accumulates onto the contract:
    `delivered_bu` increases by the `settled_net_bu`,
    `settled_value_cents` increases by the `settlement_net_cents`, the
    contract's `version` increments, and the settlement dimension moves to
    `SETTLED`."
    PRD section 3.6: "each take is subtracted from the lot's `current_bu`,
    added to its `drawn_bu`, and recorded on the load-out's `draws` array
    as a lot-and-bushels entry. A lot drawn to exactly 0.00 becomes
    `DEPLETED`; any lot from which a positive amount was taken without
    depletion becomes `PARTIALLY_DRAWN`."

    The confirm response itself carries the money fields, and the very
    next lot read already reflects the waterfall debit — no reconciliation
    lag.

    Design: Corner/consistency_model/immediate_visibility_of_settlement
    """
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-IM", original_bu=500.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=100.00,
        basis_cents_per_bu=-20, futures_ref_cents_per_bu=450,
    )
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ],
    ), SM))
    conf = get_success_data(api_client.confirm_settlement(lo["id"], SM))
    assert conf["settlement_status"] == "SETTLED"
    assert conf["grain_value_cents"] == 43000
    assert conf["service_fee_cents"] == 645
    assert conf["settlement_net_cents"] == 42355

    lot_now = get_lot(lot["id"])
    assert lot_now["current_bu"] == pytest.approx(400.00, abs=1e-9)
    assert lot_now["status"] == "PARTIALLY_DRAWN"
