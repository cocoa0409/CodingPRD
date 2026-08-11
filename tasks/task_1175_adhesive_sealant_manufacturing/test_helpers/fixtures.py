"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
the lenient get_success_data() validator so failures surface as clear
"Setup failed" errors.

Identity threading: the Distributor role is entity-backed, so every
ownership-gated Distributor call uses make_distributor_headers(distributor.id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import QA_MANAGER_USER_ID, QA_TECH_USER_ID, WORK_MORNING
from .factories import (
    create_agreement_payload,
    create_batch_payload,
    create_cure_test_payload,
    create_distributor_payload,
    create_dry_room_payload,
    create_formulation_payload,
    create_run_payload,
    create_shipment_payload,
    create_vessel_payload,
)
from .test_users import TEST_USERS, make_distributor_headers, make_qa_manager_headers, make_qa_technician_headers

ADMIN = TEST_USERS["admin_headers"]
PM = TEST_USERS["plant_manager_headers"]
BO = TEST_USERS["batch_operator_headers"]
TSE = TEST_USERS["tech_service_headers"]
CM = TEST_USERS["commercial_manager_headers"]
LC = TEST_USERS["logistics_headers"]


def _ok(resp, context: str):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed ({context}): {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Basic master-data helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = WORK_MORNING):
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), "set_clock")


def create_formulation(code: str, activate: bool = True, **overrides):
    data = _ok(api_client.create_formulation(create_formulation_payload(code=code, **overrides), PM), "create_formulation")
    if activate:
        data = _ok(api_client.activate_formulation(data["id"], PM), "activate_formulation")
    return data


def create_vessel(vessel_code: str, capacity_liters: int = 500):
    return _ok(
        api_client.create_vessel(
            create_vessel_payload(vessel_code=vessel_code, capacity_liters=capacity_liters), PM
        ),
        "create_vessel",
    )


def create_dry_room(room_code: str, max_concurrent_runs: int = 2, humidity_limit_pct: float = 10.0):
    return _ok(
        api_client.create_dry_room(
            create_dry_room_payload(
                room_code=room_code,
                max_concurrent_runs=max_concurrent_runs,
                humidity_limit_pct=humidity_limit_pct,
            ),
            PM,
        ),
        "create_dry_room",
    )


def create_distributor(name: str = "Dist", credit_limit_cents: int = 1000000, contact_email: str = "d@x.com"):
    return _ok(
        api_client.create_distributor(
            create_distributor_payload(name=name, credit_limit_cents=credit_limit_cents, contact_email=contact_email),
            CM,
        ),
        "create_distributor",
    )


# ---------------------------------------------------------------------------
# Batch / run helpers
# ---------------------------------------------------------------------------

def create_batch(formulation_id, vessel_id, **overrides):
    return _ok(
        api_client.create_batch(create_batch_payload(formulation_id, vessel_id, **overrides), BO),
        "create_batch",
    )


def create_mixed_batch(formulation_id, vessel_id, **overrides):
    """Create a batch and complete its mix. Returns the batch dict (which
    carries production_lot_id)."""
    batch = create_batch(formulation_id, vessel_id, **overrides)
    return _ok(api_client.complete_mix(batch["id"], BO), "complete_mix")


def create_run(batch_id, **overrides):
    return _ok(api_client.create_packaging_run(create_run_payload(batch_id, **overrides), BO), "create_run")


def create_and_complete_run(batch_id, **overrides):
    """Open a run and seal it. Returns the SEALED run dict."""
    run = create_run(batch_id, **overrides)
    return _ok(api_client.complete_run(run["id"], BO), "complete_run")


# ---------------------------------------------------------------------------
# Lot QA helpers
# ---------------------------------------------------------------------------

def record_test(lot_id, method="FULL", specimens=None, technician_id: str = QA_TECH_USER_ID):
    payload = create_cure_test_payload(method=method)
    if specimens is not None:
        payload["specimens"] = specimens
    return _ok(
        api_client.create_cure_test(lot_id, payload, make_qa_technician_headers(technician_id)),
        "create_cure_test",
    )


def accept_test(test_id, qa_manager_id: str = QA_MANAGER_USER_ID):
    return _ok(api_client.accept_cure_test(test_id, make_qa_manager_headers(qa_manager_id)), "accept_cure_test")


def record_and_accept_test(lot_id, method="FULL", specimens=None,
                           technician_id: str = QA_TECH_USER_ID, qa_manager_id: str = QA_MANAGER_USER_ID):
    test = record_test(lot_id, method=method, specimens=specimens, technician_id=technician_id)
    return accept_test(test["id"], qa_manager_id=qa_manager_id)


def release_lot(lot_id, qa_manager_id: str = QA_MANAGER_USER_ID):
    return _ok(api_client.release_lot(lot_id, make_qa_manager_headers(qa_manager_id)), "release_lot")


def lot_under_review_with_passing_full(lot_id, technician_id: str = QA_TECH_USER_ID,
                                       qa_manager_id: str = QA_MANAGER_USER_ID):
    """Record + accept a passing FULL test; lot lands in UNDER_REVIEW.
    Returns the ACCEPTED test dict."""
    return record_and_accept_test(
        lot_id, method="FULL", technician_id=technician_id, qa_manager_id=qa_manager_id
    )


# ---------------------------------------------------------------------------
# Composite: released lot
# ---------------------------------------------------------------------------

def setup_released_lot(code: str = "EPX-FIX", volume_ml: int = 5000, planned_units: int = 10,
                       pack_format: str = "CARTRIDGE", unit_volume_ml: int = 310,
                       moisture_sensitive: bool = False, with_dry_room: bool = False,
                       **formulation_overrides):
    """EFFECTIVE formulation + vessel + MIXED batch + one SEALED run + passing
    FULL test + RELEASED lot. Returns a dict of the created resources."""
    set_clock(WORK_MORNING)
    formulation = create_formulation(code, moisture_sensitive=moisture_sensitive, **formulation_overrides)
    vessel = create_vessel(f"V-{code}")
    dry_room = None
    if with_dry_room:
        dry_room = create_dry_room(f"DR-{code}")
    batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=volume_ml)
    lot_id = batch["production_lot_id"]
    run_kwargs = {}
    if dry_room is not None:
        run_kwargs["dry_room_id"] = dry_room["id"]
    run = create_and_complete_run(
        batch["id"], pack_format=pack_format, unit_volume_ml=unit_volume_ml,
        planned_units=planned_units, **run_kwargs,
    )
    test = lot_under_review_with_passing_full(lot_id)
    lot = release_lot(lot_id)
    return {
        "formulation": formulation,
        "vessel": vessel,
        "dry_room": dry_room,
        "batch": batch,
        "lot": lot,
        "lot_id": lot_id,
        "run": run,
        "test": test,
    }


# ---------------------------------------------------------------------------
# Composite: consignment scenario
# ---------------------------------------------------------------------------

def setup_consignment_scenario(code: str = "PU-FIX", units_to_dispatch: int = 300,
                               unit_price_cents: int = 2000, max_consigned_value_cents: int = 900000,
                               reorder_threshold_units: int = 0, reorder_qty_units: int = 200,
                               credit_limit_cents: int = 10000000, volume_ml: int = 200000,
                               planned_units: int = 400):
    """Released lot + distributor + ACTIVE agreement + a DISPATCHED consignment
    shipment of `units_to_dispatch` units. Returns resource dict; the stock row
    for (agreement, lot) then holds qty_shipped == qty_on_hand == units."""
    ctx = setup_released_lot(
        code=code, volume_ml=volume_ml, planned_units=planned_units, chemistry_family="POLYURETHANE"
    )
    distributor = create_distributor(name=f"Dist {code}", credit_limit_cents=credit_limit_cents,
                                     contact_email=f"{code.lower()}@x.com")
    agreement = _ok(
        api_client.create_agreement(
            create_agreement_payload(
                distributor["id"], ctx["formulation"]["id"],
                unit_price_cents=unit_price_cents,
                max_consigned_value_cents=max_consigned_value_cents,
                reorder_threshold_units=reorder_threshold_units,
                reorder_qty_units=reorder_qty_units,
            ),
            CM,
        ),
        "create_agreement",
    )
    agreement = _ok(api_client.activate_agreement(agreement["id"], CM), "activate_agreement")
    shipment = _ok(
        api_client.create_shipment(
            create_shipment_payload(
                distributor["id"], shipment_kind="CONSIGNMENT", agreement_id=agreement["id"]
            ),
            LC,
        ),
        "create_shipment",
    )
    _ok(api_client.add_shipment_line(shipment["id"], {"lot_id": ctx["lot_id"], "units": units_to_dispatch}, LC),
        "add_shipment_line")
    _ok(api_client.plan_shipment(shipment["id"], LC), "plan_shipment")
    _ok(api_client.confirm_shipment(shipment["id"], LC), "confirm_shipment")
    shipment = _ok(api_client.dispatch_shipment(shipment["id"], LC), "dispatch_shipment")
    ctx.update({"distributor": distributor, "agreement": agreement, "shipment": shipment})
    return ctx


def get_stock_row(agreement_id):
    data, _meta = None, None
    resp = api_client.list_consignment_stock(CM, params={"agreement_id": agreement_id})
    body = resp.json()
    rows = body.get("data", [])
    assert rows, f"Setup failed (get_stock_row): no stock rows for agreement {agreement_id}"
    return rows[0]


def create_report(agreement_id, distributor_id, expected_version, period="2026-06", consumed_units=5):
    return _ok(
        api_client.create_consumption_report(
            agreement_id,
            {
                "period": period,
                "consumed_units": consumed_units,
                "expected_agreement_version": expected_version,
            },
            make_distributor_headers(distributor_id),
        ),
        "create_consumption_report",
    )


def get_agreement(agreement_id):
    return _ok(api_client.get_agreement(agreement_id, CM), "get_agreement")


def setup_submitted_report(code: str = "PU-SUB", consumed_units: int = 250, units_to_dispatch: int = 300,
                           reorder_threshold_units: int = 0, reorder_qty_units: int = 200,
                           unit_price_cents: int = 2000,
                           volume_ml: int = 200000, planned_units: int = 400):
    """Consignment scenario plus a SUBMITTED report consuming `consumed_units`.
    Returns the scenario dict extended with the report. `volume_ml` and
    `planned_units` size the underlying batch; they must cover
    `units_to_dispatch` (e.g. planned_units >= units_to_dispatch)."""
    ctx = setup_consignment_scenario(
        code=code,
        units_to_dispatch=units_to_dispatch,
        unit_price_cents=unit_price_cents,
        reorder_threshold_units=reorder_threshold_units,
        reorder_qty_units=reorder_qty_units,
        volume_ml=volume_ml,
        planned_units=planned_units,
    )
    report = create_report(
        ctx["agreement"]["id"], ctx["distributor"]["id"], ctx["agreement"]["version"],
        consumed_units=consumed_units,
    )
    report = _ok(
        api_client.submit_report(report["id"], make_distributor_headers(ctx["distributor"]["id"])),
        "submit_report",
    )
    ctx["report"] = report
    return ctx
