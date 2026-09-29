"""Pytest fixtures for the Outdoor Gear Repair & Warranty Program API.

The harness restarts the server before every test, so each test begins against
an empty database: every precondition below is built from scratch through the
endpoints the PRD declares. The fixtures are layered:

  Tier 1 — `api`, role headers, `scenario` (the step-by-step scenario driver).
  Tier 2 — entity-hierarchy shortcuts: `catalogue` wires a centre, the
           Ascent 2P/3P model pair, a stocked panel lot, a PRO customer, a
           registered unit and two certified technicians.
  Tier 3 — lifecycle shortcuts: `submitted_claim`, `assessed_claim`,
           `decided_claim`, `open_order`, `paid_repair_order`,
           `order_with_sent_estimate`.
  Tier 4 — accumulation targeting: `claim_after_two_info_rounds`,
           `bench_completed_order`.
  Tier 5 — terminal-state shortcuts: `qc_passed_order`, `irreparable_order`.

Every builder returns the response `data` payload, so tests can read derived
fields straight off the object the endpoint minted.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import GearServiceApiClient
from .constants import SCENARIO_CLOCK_UTC
from .test_users import (
    PARTS_COORDINATOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SERVICE_AGENT_HEADERS,
    make_customer_headers,
    make_technician_headers,
)


# ==========================================================================
# Tier 1 — client, headers, scenario driver
# ==========================================================================
@pytest.fixture
def api() -> GearServiceApiClient:
    return GearServiceApiClient()


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return PROGRAM_ADMIN_HEADERS


@pytest.fixture
def agent_headers() -> Dict[str, str]:
    return SERVICE_AGENT_HEADERS


@pytest.fixture
def parts_headers() -> Dict[str, str]:
    return PARTS_COORDINATOR_HEADERS


class Scenario:
    """Step-by-step driver over the PRD-declared endpoints.

    Every method performs one API call, asserts it succeeded and returns the
    `data` payload. Identity-bearing calls take the entity id of the acting
    principal so the `X-User-ID` header always resolves (PRD §2.1).
    """

    def __init__(self, api: GearServiceApiClient):
        self.api = api

    # ------------------------------------------------------------ logical clock
    def set_clock(self, current_utc: str = SCENARIO_CLOCK_UTC) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc, PROGRAM_ADMIN_HEADERS))

    # ---------------------------------------------------------------- catalogue
    def center(self, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_service_center(
                factories.service_center_payload(**overrides), PROGRAM_ADMIN_HEADERS
            )
        )

    def surge_window(self, center_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_surge_window(
                center_id, factories.surge_window_payload(**overrides),
                PROGRAM_ADMIN_HEADERS,
            )
        )

    def successor_model(self, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_gear_model(
                factories.successor_model_payload(**overrides), PROGRAM_ADMIN_HEADERS
            )
        )

    def model(self, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_gear_model(
                factories.gear_model_payload(**overrides), PROGRAM_ADMIN_HEADERS
            )
        )

    def part_lot(self, gear_model_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_part_lot(
                factories.part_lot_payload(gear_model_id, **overrides),
                PARTS_COORDINATOR_HEADERS,
            )
        )

    def customer(self, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_customer(
                factories.customer_payload(**overrides), SERVICE_AGENT_HEADERS
            )
        )

    def gear_item(
        self, gear_model_id: str, owner_customer_id: str, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_gear_item(
                factories.gear_item_payload(gear_model_id, owner_customer_id, **overrides),
                SERVICE_AGENT_HEADERS,
            )
        )

    def technician(self, service_center_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_technician(
                factories.technician_payload(service_center_id, **overrides),
                PROGRAM_ADMIN_HEADERS,
            )
        )

    # ------------------------------------------------------------------- claims
    def claim(
        self, service_center_id: str, gear_item_id: str, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_warranty_claim(
                factories.warranty_claim_payload(
                    service_center_id, gear_item_id, **overrides
                ),
                SERVICE_AGENT_HEADERS,
            )
        )

    def submit(self, claim_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.submit_claim(claim_id, SERVICE_AGENT_HEADERS))

    def info_request(self, claim_id: str, reason: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_info_request(
                claim_id, {"reason": reason}, SERVICE_AGENT_HEADERS
            )
        )

    def resubmit(self, claim_id: str, customer_id: str, **payload) -> Dict[str, Any]:
        return get_success_data(
            self.api.resubmit_claim(claim_id, payload, make_customer_headers(customer_id))
        )

    def claim_version(self, claim_id: str) -> int:
        claim = get_success_data(
            self.api.get_warranty_claim(claim_id, SERVICE_AGENT_HEADERS)
        )
        return claim["version"]

    def assess(
        self,
        claim_id: str,
        technician_id: str,
        expected_claim_version: Optional[int] = None,
        **overrides,
    ) -> Dict[str, Any]:
        if expected_claim_version is None:
            expected_claim_version = self.claim_version(claim_id)
        return get_success_data(
            self.api.create_assessment(
                claim_id,
                factories.assessment_payload(expected_claim_version, **overrides),
                make_technician_headers(technician_id),
            )
        )

    def decide(self, claim_id: str, **payload) -> Dict[str, Any]:
        return get_success_data(
            self.api.decide_claim(claim_id, SERVICE_AGENT_HEADERS, payload or {})
        )

    # ------------------------------------------------------------ repair orders
    def repair_order(self, warranty_claim_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_repair_order(
                factories.repair_order_payload(warranty_claim_id, **overrides),
                SERVICE_AGENT_HEADERS,
            )
        )

    def order_version(self, order_id: str) -> int:
        order = get_success_data(
            self.api.get_repair_order(order_id, SERVICE_AGENT_HEADERS)
        )
        return order["version"]

    def estimate(
        self,
        order_id: str,
        expected_repair_order_version: Optional[int] = None,
        **overrides,
    ) -> Dict[str, Any]:
        if expected_repair_order_version is None:
            expected_repair_order_version = self.order_version(order_id)
        return get_success_data(
            self.api.create_estimate(
                order_id,
                factories.estimate_payload(expected_repair_order_version, **overrides),
                SERVICE_AGENT_HEADERS,
            )
        )

    def approve_estimate(self, estimate_id: str, customer_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.approve_estimate(estimate_id, make_customer_headers(customer_id))
        )

    def decline_estimate(
        self, estimate_id: str, customer_id: str, **payload
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.decline_estimate(
                estimate_id, make_customer_headers(customer_id), payload or {}
            )
        )

    # -------------------------------------------------------------- bench work
    def work_block(
        self, repair_order_id: str, technician_id: Optional[str] = None, **overrides
    ) -> Dict[str, Any]:
        payload = factories.work_block_payload(repair_order_id, **overrides)
        if technician_id is not None:
            payload["technician_id"] = technician_id
        return get_success_data(
            self.api.create_work_block(payload, SERVICE_AGENT_HEADERS)
        )

    def cancel_work_block(self, block_id: str, reason: str = "Bench reshuffled."):
        return get_success_data(
            self.api.cancel_work_block(block_id, SERVICE_AGENT_HEADERS, {"reason": reason})
        )

    def reserve_parts(
        self, order_id: str, part_lot_id: str, required_part_code: str, units: int = 1
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_parts_reservation(
                order_id,
                factories.parts_reservation_payload(
                    part_lot_id, required_part_code, units
                ),
                PARTS_COORDINATOR_HEADERS,
            )
        )

    def consume_parts(self, reservation_id: str, technician_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.consume_parts_reservation(
                reservation_id, make_technician_headers(technician_id)
            )
        )

    def release_parts(self, reservation_id: str, reason: str = "Not needed.") -> Dict:
        return get_success_data(
            self.api.release_parts_reservation(
                reservation_id, PARTS_COORDINATOR_HEADERS, {"reason": reason}
            )
        )

    def adjust_lot(self, lot_id: str, delta_units: int, reason: str = "Restock"):
        return get_success_data(
            self.api.adjust_part_lot(
                lot_id, {"delta_units": delta_units, "reason": reason},
                PARTS_COORDINATOR_HEADERS,
            )
        )

    def bench_complete(
        self, order_id: str, technician_id: str, entries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.bench_complete(
                order_id, {"work_log": entries}, make_technician_headers(technician_id)
            )
        )

    def qc(
        self,
        order_id: str,
        technician_id: str,
        outcome: str = "PASS",
        notes: str = "Seam re-taped and pressure tested.",
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_qc_inspection(
                order_id,
                {"outcome": outcome, "notes": notes},
                make_technician_headers(technician_id),
            )
        )

    def close_irreparable(self, order_id: str, technician_id: str, reason: str):
        return get_success_data(
            self.api.close_irreparable(
                order_id, {"reason": reason}, make_technician_headers(technician_id)
            )
        )

    # ---------------------------------------------------------------- billing
    def invoice(self, order_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.invoice_order(order_id, SERVICE_AGENT_HEADERS))

    def pay(self, order_id: str, amount_cents: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.pay_order(
                order_id, {"amount_cents": amount_cents}, SERVICE_AGENT_HEADERS
            )
        )

    def release_to_customer(self, order_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.release_to_customer(order_id, SERVICE_AGENT_HEADERS)
        )

    def queue_review(self, center_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.queue_review(center_id, PROGRAM_ADMIN_HEADERS))

    def trade_in(self, item_id: str, customer_id: str, condition_grade: str):
        return get_success_data(
            self.api.trade_in_gear_item(
                item_id,
                {"condition_grade": condition_grade},
                make_customer_headers(customer_id),
            )
        )

    def disposition(self, item_id: str, to: str, **payload) -> Dict[str, Any]:
        body = {"to": to}
        body.update(payload)
        return get_success_data(
            self.api.set_gear_item_disposition(item_id, body, PARTS_COORDINATOR_HEADERS)
        )

    # ------------------------------------------------------------------ reads
    def read_center(self, center_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_service_center(center_id, PROGRAM_ADMIN_HEADERS)
        )

    def read_model(self, model_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_gear_model(model_id, PROGRAM_ADMIN_HEADERS))

    def read_item(self, item_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_gear_item(item_id, SERVICE_AGENT_HEADERS))

    def read_customer(self, customer_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_customer(customer_id, SERVICE_AGENT_HEADERS)
        )

    def read_claim(self, claim_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_warranty_claim(claim_id, SERVICE_AGENT_HEADERS)
        )

    def read_assessment(self, assessment_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_claim_assessment(assessment_id, SERVICE_AGENT_HEADERS)
        )

    def read_order(self, order_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_repair_order(order_id, SERVICE_AGENT_HEADERS)
        )

    def read_estimate(self, estimate_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_estimate(estimate_id, SERVICE_AGENT_HEADERS)
        )

    def read_technician(self, technician_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_technician(technician_id, PROGRAM_ADMIN_HEADERS)
        )

    def read_lot(self, lot_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_part_lot(lot_id, PARTS_COORDINATOR_HEADERS))

    def read_work_block(self, block_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_work_block(block_id, SERVICE_AGENT_HEADERS)
        )

    def read_reservation(self, reservation_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_parts_reservation(reservation_id, PARTS_COORDINATOR_HEADERS)
        )

    def liability_entries(self, claim_id: str, **params) -> List[Dict[str, Any]]:
        body = self.api.list_claim_liability_entries(
            claim_id, SERVICE_AGENT_HEADERS, **params
        )
        return get_success_data(body)


@pytest.fixture
def scenario(api) -> Scenario:
    return Scenario(api)


class World(dict):
    """Attribute-readable bag of the ids and rows a fixture has built."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - debugging aid
            raise AttributeError(name) from exc


# ==========================================================================
# Tier 2 — entity hierarchy
# ==========================================================================
@pytest.fixture
def catalogue(scenario) -> World:
    """Centre, model pair, stocked panel lot, PRO owner, unit, two technicians.

    The unit is serial AS2-00417 on the Ascent 2P tent: purchased 2023-05-10
    for 74900 cents, with the logical clock pinned to 2026-06-15T09:00:00Z.
    """
    scenario.set_clock()
    center = scenario.center()
    successor = scenario.successor_model()
    model = scenario.model(
        discontinued_at="2024-03-01T00:00:00Z", successor_model_id=successor["id"]
    )
    panel_lot = scenario.part_lot(model["id"])
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[
            factories.certification("FABRIC", 3),
            factories.certification("ZIPPER", 2),
            factories.certification("FRAME", 2),
        ],
    )
    second_technician = scenario.technician(
        center["id"],
        employee_code="T-102",
        full_name="Dev Osei",
        certifications=[
            factories.certification("FABRIC", 2),
            factories.certification("ZIPPER", 3),
        ],
    )
    return World(
        scenario=scenario,
        center=center,
        center_id=center["id"],
        successor=successor,
        successor_id=successor["id"],
        model=model,
        model_id=model["id"],
        panel_lot=panel_lot,
        panel_lot_id=panel_lot["id"],
        customer=customer,
        customer_id=customer["id"],
        item=item,
        item_id=item["id"],
        technician=technician,
        technician_id=technician["id"],
        second_technician=second_technician,
        second_technician_id=second_technician["id"],
    )


# ==========================================================================
# Tier 3 — lifecycle shortcuts
# ==========================================================================
@pytest.fixture
def submitted_claim(catalogue) -> World:
    """A WARRANTY_CLAIM on the registered unit, submitted with a receipt."""
    scenario = catalogue.scenario
    claim = scenario.claim(catalogue.center_id, catalogue.item_id)
    submitted = scenario.submit(claim["id"])
    catalogue.update(claim=submitted, claim_id=claim["id"])
    return catalogue


@pytest.fixture
def assessed_claim(submitted_claim) -> World:
    """The submitted claim assessed MANUFACTURING_DEFECT, FABRIC 120 min, parts 4200."""
    scenario = submitted_claim.scenario
    assessment = scenario.assess(
        submitted_claim.claim_id,
        submitted_claim.technician_id,
        expected_claim_version=submitted_claim.claim["version"],
    )
    submitted_claim.update(assessment=assessment, assessment_id=assessment["id"])
    return submitted_claim


@pytest.fixture
def decided_claim(assessed_claim) -> World:
    """The assessed claim adjudicated — a WARRANTY_REPAIR approval."""
    scenario = assessed_claim.scenario
    claim = scenario.decide(
        assessed_claim.claim_id, decision_note="Defect confirmed."
    )
    assessed_claim.update(claim=claim)
    return assessed_claim


@pytest.fixture
def open_order(decided_claim) -> World:
    """A WARRANTY_REPAIR order opened on the decided claim (QUEUED / NOT_BILLABLE)."""
    scenario = decided_claim.scenario
    order = scenario.repair_order(decided_claim.claim_id)
    decided_claim.update(order=order, order_id=order["id"])
    return decided_claim


@pytest.fixture
def paid_repair_order(catalogue) -> World:
    """A PAID_REPAIR order: USER_DAMAGE determination on a paid-repair intake.

    Assessment covers FABRIC 25 min and ZIPPER 35 min with 1800 cents of parts,
    so the order lands in ESTIMATE_PENDING awaiting a quote (PRD §3.7).
    """
    scenario = catalogue.scenario
    zip_lot = scenario.part_lot(
        catalogue.model_id,
        part_code=factories.ZIP_PART_CODE,
        part_kind="ZIPPER_SLIDER",
        on_hand_units=4,
        unit_price_cents=3100,
        low_watermark_units=1,
    )
    claim = scenario.claim(
        catalogue.center_id,
        catalogue.item_id,
        intake_kind="PAID_REPAIR_REQUEST",
        reported_defect_type="ZIPPER_FAILURE",
        customer_narrative="Door zipper torn after a snag; also a scuffed floor patch.",
    )
    submitted = scenario.submit(claim["id"])
    assessment = scenario.assess(
        claim["id"],
        catalogue.technician_id,
        expected_claim_version=submitted["version"],
        determination="USER_DAMAGE",
        required_work_types=["FABRIC", "ZIPPER"],
        estimated_labor_lines=[
            factories.labor_line("FABRIC", 25),
            factories.labor_line("ZIPPER", 35),
        ],
        estimated_parts_cents=1800,
        defect_notes="Snag damage, not a defect: zipper tape torn, floor abrasion.",
    )
    scenario.decide(claim["id"], decision_note="User damage: quote as paid repair.")
    order = scenario.repair_order(claim["id"])
    catalogue.update(
        zip_lot=zip_lot,
        zip_lot_id=zip_lot["id"],
        claim=submitted,
        claim_id=claim["id"],
        assessment=assessment,
        assessment_id=assessment["id"],
        order=order,
        order_id=order["id"],
    )
    return catalogue


@pytest.fixture
def order_with_sent_estimate(paid_repair_order) -> World:
    """The paid-repair order quoted: a SENT PROVISIONAL estimate on the order."""
    scenario = paid_repair_order.scenario
    estimate = scenario.estimate(
        paid_repair_order.order_id,
        expected_repair_order_version=paid_repair_order.order["version"],
        labor_lines=[
            factories.labor_line("FABRIC", 25),
            factories.labor_line("ZIPPER", 35),
        ],
        parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
    )
    paid_repair_order.update(estimate=estimate, estimate_id=estimate["id"])
    return paid_repair_order


# ==========================================================================
# Tier 4 — accumulation targeting
# ==========================================================================
@pytest.fixture
def claim_after_two_info_rounds(catalogue) -> World:
    """A claim that has already burned both documentation rounds (PRD §3.3).

    info_request_count is 2 and the claim is back at SUBMITTED, so the next
    information request is the one the cycle bound refuses.
    """
    scenario = catalogue.scenario
    claim = scenario.claim(catalogue.center_id, catalogue.item_id)
    scenario.submit(claim["id"])
    scenario.info_request(claim["id"], "Photographs of the failed seam required.")
    scenario.resubmit(
        claim["id"],
        catalogue.customer_id,
        customer_narrative="Photos attached of the split seam.",
    )
    scenario.info_request(claim["id"], "Original retailer receipt number required.")
    latest = scenario.resubmit(
        claim["id"],
        catalogue.customer_id,
        proof_of_purchase_type="RETAILER_LOOKUP",
        proof_of_purchase_ref="RTL-55921",
        customer_narrative="Retailer lookup reference added.",
    )
    catalogue.update(claim=latest, claim_id=claim["id"])
    return catalogue


@pytest.fixture
def bench_completed_order(open_order) -> World:
    """The warranty order worked to BENCH_DONE with parts consumed (PRD §3.8).

    One 120-minute FABRIC block logged at 120 actual minutes, one panel unit
    reserved and consumed, so every required work type has a completed block
    and every reservation is settled.
    """
    scenario = open_order.scenario
    block = scenario.work_block(
        open_order.order_id,
        open_order.technician_id,
        work_type="FABRIC",
        start_at="2026-06-16T09:00:00Z",
        end_at="2026-06-16T11:00:00Z",
    )
    reservation = scenario.reserve_parts(
        open_order.order_id, open_order.panel_lot_id, factories.PANEL_PART_CODE, 1
    )
    scenario.consume_parts(reservation["id"], open_order.technician_id)
    order = scenario.bench_complete(
        open_order.order_id,
        open_order.technician_id,
        [factories.work_log_entry(block["id"], 120)],
    )
    open_order.update(
        block=block,
        block_id=block["id"],
        reservation=reservation,
        reservation_id=reservation["id"],
        order=order,
    )
    return open_order


# ==========================================================================
# Tier 5 — terminal-state shortcuts
# ==========================================================================
@pytest.fixture
def qc_passed_order(bench_completed_order) -> World:
    """The bench-done warranty order signed off by the non-assessing technician."""
    scenario = bench_completed_order.scenario
    order = scenario.qc(
        bench_completed_order.order_id, bench_completed_order.second_technician_id
    )
    bench_completed_order.update(order=order)
    return bench_completed_order


@pytest.fixture
def released_order(qc_passed_order) -> World:
    """The QC-passed warranty order handed back: RELEASED / CLOSED_FULFILLED."""
    scenario = qc_passed_order.scenario
    order = scenario.release_to_customer(qc_passed_order.order_id)
    qc_passed_order.update(order=order)
    return qc_passed_order


@pytest.fixture
def irreparable_order(open_order) -> World:
    """A warranty order condemned from IN_WORK, leaving the unit IRREPARABLE_HOLD."""
    scenario = open_order.scenario
    block = scenario.work_block(
        open_order.order_id,
        open_order.technician_id,
        work_type="FABRIC",
        start_at="2026-06-16T09:00:00Z",
        end_at="2026-06-16T11:00:00Z",
    )
    order = scenario.close_irreparable(
        open_order.order_id,
        open_order.technician_id,
        "Floor fabric delaminated beyond patchable area.",
    )
    open_order.update(block=block, block_id=block["id"], order=order)
    return open_order
