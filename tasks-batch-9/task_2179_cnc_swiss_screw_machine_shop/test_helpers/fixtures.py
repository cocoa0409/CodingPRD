"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SCENARIO
from .factories import (
    MEASUREMENTS_AT_CPK_MIN,
    accept_quote_payload,
    calibration_payload,
    certify_payload,
    clock_payload,
    complete_machining_payload,
    create_bar_stock_lot_payload,
    create_characteristic_payload,
    create_gauge_payload,
    create_machine_payload,
    create_operator_payload,
    create_part_payload,
    create_quote_payload,
    create_release_payload,
    create_routing_step_payload,
    create_second_bar_stock_lot_payload,
    create_second_part_payload,
    create_spc_sample_payload,
    create_tool_assignment_payload,
    create_work_order_payload,
    disposition_payload,
    offset_log_payload,
    price_payload,
)
from .test_users import (
    make_inspector_headers,
    make_machinist_headers,
    make_quality_manager_headers,
    make_shop_planner_headers,
)

PLANNER = make_shop_planner_headers()
QUALITY = make_quality_manager_headers()


class Scenario(dict):
    """Dict of the entities a composite fixture built, with attribute access."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error only
            raise AttributeError(item) from exc


# --------------------------------------------------------------------------
# Single-step helpers
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str = SCENARIO["CLOCK"]) -> dict:
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), PLANNER))


def register_operator(**overrides) -> dict:
    return get_success_data(
        api_client.create_operator(create_operator_payload(**overrides), PLANNER)
    )


def register_machinist(**overrides) -> dict:
    """Operator BM-01, certified for SWISS_SETUP and LIGHTS_OUT."""
    return register_operator(**overrides)


def register_inspector(**overrides) -> dict:
    """Operator BI-01, a different person from the machinist."""
    payload = {"name": "Ida Chen", "badge_code": "BI-01", "certifications": ["CMM"]}
    payload.update(overrides)
    return register_operator(**payload)


def register_machine(**overrides) -> dict:
    return get_success_data(
        api_client.create_machine(create_machine_payload(**overrides), PLANNER)
    )


def register_part(**overrides) -> dict:
    return get_success_data(api_client.create_part(create_part_payload(**overrides), PLANNER))


def register_second_part(**overrides) -> dict:
    return get_success_data(
        api_client.create_part(create_second_part_payload(**overrides), PLANNER)
    )


def register_gauge(**overrides) -> dict:
    return get_success_data(api_client.create_gauge(create_gauge_payload(**overrides), QUALITY))


def post_calibration(gauge_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_gauge_calibration(gauge_id, calibration_payload(**overrides), QUALITY)
    )


def add_characteristic(part_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_characteristic(
            create_characteristic_payload(part_id, **overrides), PLANNER
        )
    )


def receive_bar_lot(**overrides) -> dict:
    return get_success_data(
        api_client.create_bar_stock_lot(create_bar_stock_lot_payload(**overrides), PLANNER)
    )


def receive_second_bar_lot(**overrides) -> dict:
    return get_success_data(
        api_client.create_bar_stock_lot(create_second_bar_stock_lot_payload(**overrides), PLANNER)
    )


def certify_bar_lot(lot_id: str, certificate_number: str = "CERT-1") -> dict:
    return get_success_data(
        api_client.certify_bar_stock_lot(lot_id, certify_payload(certificate_number), QUALITY)
    )


def receive_and_certify_bar_lot(certificate_number: str = "CERT-1", **overrides) -> dict:
    lot = receive_bar_lot(**overrides)
    return certify_bar_lot(lot["id"], certificate_number)


def open_quote(part_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_quote(create_quote_payload(part_id, **overrides), PLANNER)
    )


def price_quote(quote_id: str, costing_basis: str = "STANDARD_CYCLE") -> dict:
    return get_success_data(
        api_client.price_quote(quote_id, price_payload(costing_basis), PLANNER)
    )


def accept_quote(quote_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.accept_quote(quote_id, accept_quote_payload(**overrides), PLANNER)
    )


def read_blanket_po(po_id: str) -> dict:
    return get_success_data(api_client.get_blanket_po(po_id, PLANNER))


def blanket_po_version(po_id: str) -> int:
    return read_blanket_po(po_id)["version"]


def read_machine(machine_id: str) -> dict:
    return get_success_data(api_client.get_machine(machine_id, PLANNER))


def machine_version(machine_id: str) -> int:
    return read_machine(machine_id)["version"]


def read_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, PLANNER))


def read_bar_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_bar_stock_lot(lot_id, PLANNER))


def read_release(release_id: str) -> dict:
    return get_success_data(api_client.get_kanban_release(release_id, PLANNER))


def read_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, PLANNER))


def read_part(part_id: str) -> dict:
    return get_success_data(api_client.get_part(part_id, PLANNER))


def read_tool_assignment(tool_id: str) -> dict:
    return get_success_data(api_client.get_tool_assignment(tool_id, PLANNER))


def read_routing_step(step_id: str) -> dict:
    return get_success_data(api_client.get_routing_step(step_id, PLANNER))


def read_gauge(gauge_id: str) -> dict:
    return get_success_data(api_client.get_gauge(gauge_id, PLANNER))


def cut_release(po_id: str, **overrides) -> dict:
    """Cut a kanban release, reading the order's current version first."""
    expected = overrides.pop("expected_blanket_po_version", None)
    if expected is None:
        expected = blanket_po_version(po_id)
    return get_success_data(
        api_client.create_kanban_release(create_release_payload(po_id, expected, **overrides), PLANNER)
    )


def schedule_work_order(release_id: str, machine_id: str, bar_lot_id: str, **overrides) -> dict:
    """Schedule a work order, reading the machine's current version first."""
    expected = overrides.pop("expected_machine_version", None)
    if expected is None:
        expected = machine_version(machine_id)
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(release_id, machine_id, bar_lot_id, expected, **overrides),
            PLANNER,
        )
    )


def start_work_order(work_order_id: str, operator_id: str) -> dict:
    return get_success_data(
        api_client.start_work_order(work_order_id, make_machinist_headers(operator_id))
    )


def complete_machining(work_order_id: str, operator_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.complete_machining(
            work_order_id, complete_machining_payload(**overrides), make_machinist_headers(operator_id)
        )
    )


def cancel_work_order(work_order_id: str, reason: str = "CUSTOMER_PULL_IN") -> dict:
    return get_success_data(
        api_client.cancel_work_order(work_order_id, {"reason": reason}, PLANNER)
    )


def disposition(work_order_id: str, decision: str, note: str = "recorded by quality") -> dict:
    return get_success_data(
        api_client.disposition_work_order(work_order_id, disposition_payload(decision, note), QUALITY)
    )


def post_subgroup(
    work_order_id: str,
    characteristic_id: str,
    gauge_id: str,
    inspector_operator_id: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_spc_sample(
            create_spc_sample_payload(work_order_id, characteristic_id, gauge_id, **overrides),
            make_inspector_headers(inspector_operator_id),
        )
    )


def add_routing_step(work_order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_routing_step(
            create_routing_step_payload(work_order_id, **overrides), PLANNER
        )
    )


def load_tool(machine_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tool_assignment(
            create_tool_assignment_payload(machine_id, **overrides), PLANNER
        )
    )


def log_offset(tool_id: str, operator_id: str, pieces_produced: int, measured_drift_um: float) -> dict:
    return get_success_data(
        api_client.post_offset_log(
            tool_id,
            offset_log_payload(pieces_produced, measured_drift_um),
            make_machinist_headers(operator_id),
        )
    )


def index_tool(tool_id: str, operator_id: str, **payload) -> dict:
    return get_success_data(
        api_client.index_tool_assignment(tool_id, payload, make_machinist_headers(operator_id))
    )


def restore_machine(machine_id: str, operator_id: str) -> dict:
    return get_success_data(
        api_client.restore_machine(machine_id, make_machinist_headers(operator_id))
    )


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------


def setup_shop_floor(
    clock: str = SCENARIO["CLOCK"],
    part_overrides=None,
    machine_overrides=None,
    gauge_overrides=None,
    characteristic_overrides=None,
    lot_overrides=None,
    quote_lot_qty: int = 200,
    requested_lights_out_hours: float = 0,
    committed_qty: int = 200,
    po_expires_on: str = SCENARIO["PO_EXPIRES_ON"],
    customer_po_number: str = "ACME-9911",
    release_qty=200,
    with_characteristic: bool = True,
    with_release: bool = True,
) -> Scenario:
    """Clock, two operators, a lathe, a part, a gauge, a print characteristic,
    a certified bar lot, a priced-and-accepted quote and one kanban release.

    This is the standing shop the majority of scenarios need before they can
    schedule anything onto the floor.
    """
    set_clock(clock)
    machinist = register_machinist()
    inspector = register_inspector()
    machine = register_machine(**(machine_overrides or {}))
    part = register_part(**(part_overrides or {}))
    gauge = register_gauge(**(gauge_overrides or {}))
    characteristic = (
        add_characteristic(part["id"], **(characteristic_overrides or {}))
        if with_characteristic
        else None
    )
    lot = receive_bar_lot(**(lot_overrides or {}))
    lot = certify_bar_lot(lot["id"])
    quote = open_quote(
        part["id"],
        lot_qty=quote_lot_qty,
        requested_lights_out_hours=requested_lights_out_hours,
    )
    quote = price_quote(quote["id"])
    po = accept_quote(
        quote["id"],
        customer_po_number=customer_po_number,
        total_committed_qty=committed_qty,
        expires_on=po_expires_on,
    )
    scenario = Scenario(
        machinist=machinist,
        inspector=inspector,
        machinist_id=machinist["id"],
        inspector_id=inspector["id"],
        machine=machine,
        machine_id=machine["id"],
        part=part,
        part_id=part["id"],
        gauge=gauge,
        gauge_id=gauge["id"],
        characteristic=characteristic,
        characteristic_id=characteristic["id"] if characteristic else None,
        lot=lot,
        lot_id=lot["id"],
        quote=quote,
        quote_id=quote["id"],
        po=po,
        po_id=po["id"],
        release=None,
        release_id=None,
    )
    if with_release:
        release = cut_release(po["id"], qty=release_qty)
        scenario["release"] = release
        scenario["release_id"] = release["id"]
    return scenario


def setup_scheduled_work_order(
    qty_ordered: int = 200,
    lights_out_hours: float = 4,
    scheduled_start_at: str = SCENARIO["WINDOW_START"],
    scheduled_end_at: str = SCENARIO["WINDOW_END"],
    **shop_overrides,
) -> Scenario:
    """The standing shop plus one SCHEDULED work order on the certified lot."""
    scenario = setup_shop_floor(**shop_overrides)
    work_order = schedule_work_order(
        scenario.release_id,
        scenario.machine_id,
        scenario.lot_id,
        qty_ordered=qty_ordered,
        lights_out_hours=lights_out_hours,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    scenario["work_order"] = work_order
    scenario["work_order_id"] = work_order["id"]
    return scenario


def setup_running_work_order(**overrides) -> Scenario:
    """A work order whose spindle is turning, started by operator BM-01."""
    scenario = setup_scheduled_work_order(**overrides)
    scenario["work_order"] = start_work_order(scenario.work_order_id, scenario.machinist_id)
    return scenario


def setup_machining_complete_work_order(
    qty_good: int = 200,
    qty_scrap: int = 0,
    actual_run_seconds: float = 9300,
    post_accept_subgroup: bool = True,
    **overrides,
) -> Scenario:
    """A job whose production dimension is closed.

    When ``post_accept_subgroup`` is set the quality dimension has already been
    moved to IN_SPC by one accepting subgroup, which is the state the ACCEPT and
    REJECT dispositions are declared from.
    """
    scenario = setup_running_work_order(**overrides)
    if post_accept_subgroup:
        scenario["first_sample"] = post_subgroup(
            scenario.work_order_id,
            scenario.characteristic_id,
            scenario.gauge_id,
            scenario.inspector_id,
            piece_index=200,
            measurements=list(MEASUREMENTS_AT_CPK_MIN),
        )
    scenario["work_order"] = complete_machining(
        scenario.work_order_id,
        scenario.machinist_id,
        qty_good=qty_good,
        qty_scrap=qty_scrap,
        actual_run_seconds=actual_run_seconds,
    )
    return scenario


def setup_held_tool_station(
    expected_life_pieces: int = 1500,
    drift_limit_um: float = 8,
    clock: str = SCENARIO["CLOCK"],
) -> Scenario:
    """A lathe sent DOWN by a station that walked onto its drift limit.

    Two offset logs of +3 and +5 microns put cumulative_drift_um at exactly the
    8 micron limit, so the station is OFFSET_HOLD and its machine is DOWN.
    """
    set_clock(clock)
    machinist = register_machinist()
    machine = register_machine()
    tool = load_tool(
        machine["id"], expected_life_pieces=expected_life_pieces, drift_limit_um=drift_limit_um
    )
    log_offset(tool["id"], machinist["id"], 40, 3)
    tool = log_offset(tool["id"], machinist["id"], 40, 5)
    return Scenario(
        machinist=machinist,
        machinist_id=machinist["id"],
        machine=machine,
        machine_id=machine["id"],
        tool=tool,
        tool_id=tool["id"],
    )


def setup_interrupted_work_order(routing_step_count: int = 0, **overrides) -> Scenario:
    """A RUNNING job carried to INTERRUPTED by a tool hold on its machine.

    The station is loaded before the start so the four-hop chain has a running
    work order and, when ``routing_step_count`` is set, a DEBURR step followed by
    a WASH step to act on.
    """
    scenario = setup_scheduled_work_order(**overrides)
    tool = load_tool(scenario.machine_id)
    scenario["tool"] = tool
    scenario["tool_id"] = tool["id"]
    start_work_order(scenario.work_order_id, scenario.machinist_id)

    steps = []
    if routing_step_count >= 1:
        steps.append(add_routing_step(scenario.work_order_id, sequence=1, operation="DEBURR"))
    if routing_step_count >= 2:
        steps.append(
            add_routing_step(
                scenario.work_order_id,
                sequence=2,
                operation="WASH",
                predecessor_step_id=steps[0]["id"],
            )
        )
    scenario["routing_steps"] = steps

    log_offset(tool["id"], scenario.machinist_id, 40, 3)
    scenario["tool"] = log_offset(tool["id"], scenario.machinist_id, 40, 5)
    scenario["work_order"] = read_work_order(scenario.work_order_id)
    return scenario


def setup_accepted_work_order(**overrides) -> Scenario:
    """A job carried all the way to an ACCEPT disposition.

    Fires the whole fulfilment chain, so the release is FULFILLED, the order's
    ledger has been recomputed and the part's observed running figures exist.
    """
    scenario = setup_machining_complete_work_order(**overrides)
    scenario["work_order"] = disposition(scenario.work_order_id, "ACCEPT", "lot accepted")
    return scenario


def setup_two_part_shop(clock: str = SCENARIO["CLOCK"]) -> Scenario:
    """Two parts of different bar diameter, each with its own certified lot,
    blanket order and kanban release, sharing one lathe."""
    set_clock(clock)
    machinist = register_machinist()
    machine = register_machine()
    part_a = register_part()
    part_b = register_second_part()
    lot_a = certify_bar_lot(receive_bar_lot()["id"], "CERT-A")
    lot_b = certify_bar_lot(receive_second_bar_lot()["id"], "CERT-B")

    quote_a = price_quote(open_quote(part_a["id"], lot_qty=200)["id"])
    po_a = accept_quote(
        quote_a["id"], customer_po_number="ACME-A", total_committed_qty=200
    )
    release_a = cut_release(po_a["id"], qty=200)

    quote_b = price_quote(open_quote(part_b["id"], lot_qty=100)["id"])
    po_b = accept_quote(
        quote_b["id"], customer_po_number="ACME-B", total_committed_qty=100
    )
    release_b = cut_release(po_b["id"], qty=100)

    return Scenario(
        machinist=machinist,
        machinist_id=machinist["id"],
        machine=machine,
        machine_id=machine["id"],
        part_a=part_a,
        part_b=part_b,
        lot_a=lot_a,
        lot_a_id=lot_a["id"],
        lot_b=lot_b,
        lot_b_id=lot_b["id"],
        po_a=po_a,
        po_b=po_b,
        release_a=release_a,
        release_a_id=release_a["id"],
        release_b=release_b,
        release_b_id=release_b["id"],
    )


def setup_machine_with_two_alloy_accruals() -> Scenario:
    """One lathe that has completed a 303SS job and a C360 job.

    Leaves chip_accrual_by_alloy holding 3.504 kg of 303SS and 2.861 kg of
    C360 with 1.342 litres of coolant make-up, ready for a settlement.
    """
    scenario = setup_two_part_shop()
    work_order_a = schedule_work_order(
        scenario.release_a_id,
        scenario.machine_id,
        scenario.lot_a_id,
        qty_ordered=200,
        lights_out_hours=0,
        scheduled_start_at="2026-09-02T06:00:00Z",
        scheduled_end_at="2026-09-02T14:00:00Z",
    )
    start_work_order(work_order_a["id"], scenario.machinist_id)
    work_order_a = complete_machining(
        work_order_a["id"], scenario.machinist_id, qty_good=200, qty_scrap=0, actual_run_seconds=8400
    )
    work_order_b = schedule_work_order(
        scenario.release_b_id,
        scenario.machine_id,
        scenario.lot_b_id,
        qty_ordered=100,
        lights_out_hours=0,
        scheduled_start_at="2026-09-03T06:00:00Z",
        scheduled_end_at="2026-09-03T12:00:00Z",
    )
    start_work_order(work_order_b["id"], scenario.machinist_id)
    work_order_b = complete_machining(
        work_order_b["id"], scenario.machinist_id, qty_good=100, qty_scrap=0, actual_run_seconds=5400
    )
    scenario["work_order_a"] = work_order_a
    scenario["work_order_b"] = work_order_b
    return scenario


def setup_shared_lot_on_two_machines(clock: str = SCENARIO["CLOCK"]) -> Scenario:
    """One certified single-slot bar lot staged for two lathes, with a
    400-piece release that still has room for a second job."""
    scenario = setup_shop_floor(committed_qty=400, release_qty=400, clock=clock)
    second_machine = register_machine(asset_tag="SW-02")
    scenario["machine2"] = second_machine
    scenario["machine2_id"] = second_machine["id"]
    return scenario
