"""Composite setup helpers.

Every test starts against an empty database — the harness restarts the API and
wipes the store before each individual test — so every precondition has to be
built here from scratch out of PRD-declared endpoints only.  These helpers use
the lenient `get_success_data()` validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion further down.

Layering:
  * step helpers      — exactly one API call each (`create_vendor`, `publish_guide`, ...)
  * read helpers      — one GET each, returning the resource body
  * scenario helpers  — the recurring multi-call chains, in five tiers:
      1. state progression   `setup_published_guide`, `setup_received_shipment`
      2. entity hierarchy    `setup_program`, `setup_detected_violation`
      3. lifecycle shortcuts `setup_evidence_complete_violation`,
                             `setup_assessed_chargeback`, `setup_open_dispute`
      4. accumulation        `setup_draft_deduction`, `setup_posted_deduction`,
                             `setup_measured_scorecard`
      5. finalisation        `setup_finalized_scorecard`, `setup_issued_cap`
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_PROGRAMME_START,
    CLOCK_RECEIPT_DAY,
    GUIDE_EFFECTIVE_FROM,
    REQ_SHP_04,
)
from .factories import (
    allocation_payload,
    assess_payload,
    cap_decision_payload,
    cap_escalation_payload,
    cap_submit_payload,
    cash_application_payload,
    deduction_payload,
    dispute_decision_payload,
    dispute_payload,
    evidence_payload,
    measure_payload,
    purchase_order_payload,
    receipt_payload,
    request_info_payload,
    resubmit_payload,
    reversal_payload,
    routing_guide_payload,
    scorecard_payload,
    shipment_payload,
    vendor_payload,
    violation_payload,
    void_payload,
)
from .test_users import TEST_USERS, make_vendor_headers

OFFICER = TEST_USERS["officer_headers"]
SECOND_OFFICER = TEST_USERS["second_officer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
SECOND_INSPECTOR = TEST_USERS["second_inspector_headers"]
BUYER = TEST_USERS["buyer_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the programme logical clock. The clock never advances on its own."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or OFFICER)
    )


# ---------------------------------------------------------------------------
# Step helpers — one API call each
# ---------------------------------------------------------------------------
def create_vendor(headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_vendor(vendor_payload(**overrides), headers or OFFICER)
    )


def create_guide(headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_routing_guide(
            routing_guide_payload(**overrides), headers or OFFICER
        )
    )


def add_requirement(guide_id: str, schedule: Optional[dict] = None, **overrides) -> dict:
    payload = dict(schedule or REQ_SHP_04)
    payload.update(overrides)
    return get_success_data(
        api_client.create_requirement(guide_id, payload, OFFICER)
    )


def publish_guide(guide_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.publish_routing_guide(guide_id, headers or OFFICER)
    )


def create_po(vendor_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_purchase_order(
            purchase_order_payload(vendor_id, **overrides), headers or BUYER
        )
    )


def create_shipment(po_id: str, vendor_id: str, **overrides) -> dict:
    """Suppliers announce their own shipments, so this is a `Vendor` call whose
    `X-User-ID` is the supplier's own id."""
    return get_success_data(
        api_client.create_shipment(
            po_id, shipment_payload(**overrides), make_vendor_headers(vendor_id)
        )
    )


def receive_shipment(
    shipment_id: str, received_units: int, headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.receive_shipment(
            shipment_id, receipt_payload(received_units), headers or INSPECTOR
        )
    )


def file_violation(
    shipment_id: str, requirement_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_violation(
            shipment_id,
            violation_payload(requirement_id, **overrides),
            headers or INSPECTOR,
        )
    )


def add_evidence(
    violation_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.add_violation_evidence(
            violation_id, evidence_payload(**overrides), headers or INSPECTOR
        )
    )


def assess_violation(
    violation_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.assess_violation(
            violation_id, assess_payload(**overrides), headers or OFFICER
        )
    )


def void_violation(
    violation_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.void_violation(
            violation_id, void_payload(**overrides), headers or OFFICER
        )
    )


def open_dispute(chargeback_id: str, vendor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dispute(
            chargeback_id, dispute_payload(**overrides), make_vendor_headers(vendor_id)
        )
    )


def add_dispute_evidence(dispute_id: str, vendor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.add_dispute_evidence(
            dispute_id, evidence_payload(**overrides), make_vendor_headers(vendor_id)
        )
    )


def request_dispute_info(
    dispute_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.request_dispute_info(
            dispute_id, request_info_payload(**overrides), headers or SECOND_OFFICER
        )
    )


def resubmit_dispute(dispute_id: str, vendor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.resubmit_dispute(
            dispute_id, resubmit_payload(**overrides), make_vendor_headers(vendor_id)
        )
    )


def decide_dispute(
    dispute_id: str,
    decision: str = "APPROVE",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """The adjudicating officer must not be the operator who detected the
    violation, so this defaults to the second officer identity."""
    return get_success_data(
        api_client.decide_dispute(
            dispute_id,
            dispute_decision_payload(decision, **overrides),
            headers or SECOND_OFFICER,
        )
    )


def create_scorecard(vendor_id: str, headers: Optional[dict] = None, **overrides):
    return get_success_data(
        api_client.create_scorecard(
            scorecard_payload(vendor_id, **overrides), headers or OFFICER
        )
    )


def measure_scorecard(
    scorecard_id: str, measurement_variant: str = "ORDER_WEIGHTED", **overrides
) -> dict:
    return get_success_data(
        api_client.measure_scorecard(
            scorecard_id, measure_payload(measurement_variant, **overrides), OFFICER
        )
    )


def finalize_scorecard(scorecard_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.finalize_scorecard(scorecard_id, headers or OFFICER)
    )


def submit_cap(cap_id: str, vendor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.submit_cap(
            cap_id, cap_submit_payload(**overrides), make_vendor_headers(vendor_id)
        )
    )


def decide_cap(cap_id: str, decision: str = "ACCEPT", **overrides) -> dict:
    return get_success_data(
        api_client.decide_cap(cap_id, cap_decision_payload(decision, **overrides), OFFICER)
    )


def escalate_cap(cap_id: str, buying_decision: str = "SOURCING_HOLD", **overrides):
    """Escalation is reserved to the `CategoryBuyer`."""
    return get_success_data(
        api_client.escalate_cap(
            cap_id, cap_escalation_payload(buying_decision, **overrides), BUYER
        )
    )


def close_cap(cap_id: str, outcome: str = "SUCCESS", **overrides) -> dict:
    from .factories import cap_close_payload

    return get_success_data(
        api_client.close_cap(cap_id, cap_close_payload(outcome, **overrides), OFFICER)
    )


def create_deduction(vendor_id: str, **overrides) -> dict:
    """Reads the supplier's current `version` and threads it through
    `expected_vendor_version`, which the deduction-create endpoint requires."""
    version = read_vendor(vendor_id)["version"]
    return get_success_data(
        api_client.create_deduction(
            deduction_payload(vendor_id, version, **overrides), ACCOUNTANT
        )
    )


def add_allocation(deduction_id: str, chargeback_id: str, allocated_cents: int) -> dict:
    return get_success_data(
        api_client.create_allocation(
            deduction_id,
            allocation_payload(chargeback_id, allocated_cents),
            ACCOUNTANT,
        )
    )


def post_deduction(deduction_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.post_deduction(deduction_id, headers or ACCOUNTANT)
    )


def reverse_deduction(deduction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.reverse_deduction(
            deduction_id, reversal_payload(**overrides), ACCOUNTANT
        )
    )


def apply_cash(chargeback_id: str, amount_cents: int, **overrides) -> dict:
    """Reads the chargeback's current `version` and threads it through
    `expected_chargeback_version`."""
    version = read_chargeback(chargeback_id)["version"]
    return get_success_data(
        api_client.apply_cash(
            chargeback_id,
            cash_application_payload(amount_cents, version, **overrides),
            ACCOUNTANT,
        )
    )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------
def read_vendor(vendor_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_vendor(vendor_id, headers or OFFICER))


def read_guide(guide_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_routing_guide(guide_id, headers or OFFICER))


def read_requirements(guide_id: str, headers: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_requirements(guide_id, headers or OFFICER)
    )


def read_purchase_order(po_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_purchase_order(po_id, headers or OFFICER))


def read_shipment(shipment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, headers or OFFICER))


def read_violation(violation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_violation(violation_id, headers or OFFICER))


def read_chargeback(chargeback_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_chargeback(chargeback_id, headers or OFFICER)
    )


def read_dispute(dispute_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_dispute(dispute_id, headers or OFFICER))


def read_scorecard(scorecard_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_scorecard(scorecard_id, headers or OFFICER))


def read_cap(cap_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_cap(cap_id, headers or OFFICER))


def read_deduction(deduction_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_deduction(deduction_id, headers or OFFICER))


def read_allocation(allocation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_allocation(allocation_id, headers or OFFICER)
    )


def vendor_version(vendor_id: str) -> int:
    return read_vendor(vendor_id)["version"]


def chargeback_version(chargeback_id: str) -> int:
    return read_chargeback(chargeback_id)["version"]


def first_cap_for_scorecard(scorecard_id: str) -> dict:
    """The finalisation cascade mints the plan; the programme exposes it only
    through the plan listing filtered by its triggering scorecard."""
    rows = get_success_data(
        api_client.list_caps(OFFICER, params={"trigger_scorecard_id": scorecard_id})
    )
    assert rows, f"finalisation should have issued a plan for scorecard {scorecard_id}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------
def setup_published_guide(
    schedule: Optional[dict] = None,
    guide_overrides: Optional[dict] = None,
    requirement_overrides: Optional[dict] = None,
) -> dict:
    """A PUBLISHED edition holding exactly one priced requirement."""
    guide = create_guide(**(guide_overrides or {}))
    requirement = add_requirement(
        guide["id"], schedule, **(requirement_overrides or {})
    )
    guide = publish_guide(guide["id"])
    return {"guide": guide, "requirement": requirement}


def setup_received_shipment(
    vendor_id: str,
    ordered_units: int = 1000,
    unit_cost_cents: int = 500,
    shipped_units: Optional[int] = None,
    received_units: Optional[int] = None,
    po_overrides: Optional[dict] = None,
) -> dict:
    """One purchase order, one announced shipment, one receipt."""
    shipped = ordered_units if shipped_units is None else shipped_units
    received = shipped if received_units is None else received_units
    po = create_po(
        vendor_id,
        ordered_units=ordered_units,
        unit_cost_cents=unit_cost_cents,
        **(po_overrides or {}),
    )
    shipment = create_shipment(po["id"], vendor_id, shipped_units=shipped)
    shipment = receive_shipment(shipment["id"], received)
    return {"po": po, "shipment": shipment}


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------
def setup_program(
    schedule: Optional[dict] = None,
    vendor_overrides: Optional[dict] = None,
    guide_overrides: Optional[dict] = None,
    requirement_overrides: Optional[dict] = None,
    start_clock: str = CLOCK_PROGRAMME_START,
    receipt_clock: str = CLOCK_RECEIPT_DAY,
    ordered_units: int = 1000,
    unit_cost_cents: int = 500,
    shipped_units: Optional[int] = None,
    received_units: Optional[int] = None,
    po_overrides: Optional[dict] = None,
    receive: bool = True,
) -> dict:
    """The recurring world: clock pinned, supplier registered, one PUBLISHED
    edition holding one priced requirement, one purchase order, one announced
    shipment and (unless `receive=False`) one receipt.

    Returns the vendor, guide, requirement, po and shipment bodies.
    """
    set_clock(start_clock)
    vendor = create_vendor(**(vendor_overrides or {}))
    published = setup_published_guide(
        schedule,
        {"effective_from": GUIDE_EFFECTIVE_FROM, **(guide_overrides or {})},
        requirement_overrides,
    )
    set_clock(receipt_clock)
    shipped = ordered_units if shipped_units is None else shipped_units
    po = create_po(
        vendor["id"],
        ordered_units=ordered_units,
        unit_cost_cents=unit_cost_cents,
        **(po_overrides or {}),
    )
    shipment = create_shipment(po["id"], vendor["id"], shipped_units=shipped)
    if receive:
        received = shipped if received_units is None else received_units
        shipment = receive_shipment(shipment["id"], received)
    return {
        "vendor": vendor,
        "guide": published["guide"],
        "requirement": published["requirement"],
        "po": po,
        "shipment": shipment,
    }


def setup_detected_violation(
    schedule: Optional[dict] = None,
    affected_units: int = 400,
    affected_cartons: int = 16,
    narrative: str = "ASN transmitted after trailer arrival.",
    **program_kwargs,
) -> dict:
    """A freshly filed breach: `DETECTED`, no evidence yet."""
    world = setup_program(schedule, **program_kwargs)
    violation = file_violation(
        world["shipment"]["id"],
        world["requirement"]["id"],
        affected_units=affected_units,
        affected_cartons=affected_cartons,
        narrative=narrative,
    )
    world["violation"] = violation
    return world


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_evidence_complete_violation(
    schedule: Optional[dict] = None, evidence_kinds=("DOCUMENT", "MEASUREMENT"), **kwargs
) -> dict:
    """A breach carrying enough evidence to be assessable."""
    world = setup_detected_violation(schedule, **kwargs)
    evidence = [
        add_evidence(world["violation"]["id"], kind=kind) for kind in evidence_kinds
    ]
    world["evidence"] = evidence
    world["violation"] = read_violation(world["violation"]["id"])
    return world


def setup_assessed_chargeback(
    schedule: Optional[dict] = None,
    evidence_kinds=("DOCUMENT", "MEASUREMENT"),
    assessment_note: str = "Late ASN.",
    **kwargs,
) -> dict:
    """The canonical money position: one assessed chargeback on one supplier."""
    world = setup_evidence_complete_violation(schedule, evidence_kinds, **kwargs)
    world["chargeback"] = assess_violation(
        world["violation"]["id"], assessment_note=assessment_note
    )
    return world


def setup_open_dispute(
    dispute_clock: str = "2026-08-12T00:00:00Z",
    reason_code: str = "CARRIER_CAUSED",
    claimed_reversal_cents: int = 200_000,
    narrative: str = "Carrier detained the trailer at the yard.",
    **kwargs,
) -> dict:
    """An assessed chargeback carrying one SUBMITTED dispute."""
    world = setup_assessed_chargeback(**kwargs)
    set_clock(dispute_clock)
    world["dispute"] = open_dispute(
        world["chargeback"]["id"],
        world["vendor"]["id"],
        reason_code=reason_code,
        claimed_reversal_cents=claimed_reversal_cents,
        narrative=narrative,
    )
    return world


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------
def setup_draft_deduction(
    allocated_cents: int,
    invoice_reference: str = "INV-77",
    **kwargs,
) -> dict:
    """A DRAFT deduction carrying one PENDING allocation against the chargeback."""
    world = setup_assessed_chargeback(**kwargs)
    deduction = create_deduction(
        world["vendor"]["id"], invoice_reference=invoice_reference
    )
    allocation = add_allocation(
        deduction["id"], world["chargeback"]["id"], allocated_cents
    )
    world["deduction"] = deduction
    world["allocation"] = allocation
    return world


def setup_posted_deduction(
    allocated_cents: int,
    invoice_reference: str = "INV-77",
    **kwargs,
) -> dict:
    """A POSTED deduction: the allocation is EFFECTIVE and the money has moved."""
    world = setup_draft_deduction(allocated_cents, invoice_reference, **kwargs)
    world["deduction"] = post_deduction(world["deduction"]["id"])
    world["allocation"] = read_allocation(world["allocation"]["id"])
    world["chargeback"] = read_chargeback(world["chargeback"]["id"])
    return world


def setup_measured_scorecard(
    vendor_id: str,
    measurement_variant: str = "ORDER_WEIGHTED",
    measure_clock: Optional[str] = None,
    **scorecard_overrides,
) -> dict:
    """One measured scorecard over an already-populated order history."""
    if measure_clock:
        set_clock(measure_clock)
    scorecard = create_scorecard(vendor_id, **scorecard_overrides)
    scorecard = measure_scorecard(scorecard["id"], measurement_variant)
    return scorecard


# ---------------------------------------------------------------------------
# Tier 5 — finalisation and terminal states
# ---------------------------------------------------------------------------
def setup_finalized_scorecard(
    vendor_id: str,
    measurement_variant: str = "ORDER_WEIGHTED",
    measure_clock: Optional[str] = None,
    **scorecard_overrides,
) -> dict:
    """A FINALIZED scorecard: the composite has been pushed onto the supplier."""
    scorecard = setup_measured_scorecard(
        vendor_id, measurement_variant, measure_clock, **scorecard_overrides
    )
    return finalize_scorecard(scorecard["id"])


def setup_issued_cap(
    vendor_id: str,
    measurement_variant: str = "ORDER_WEIGHTED",
    measure_clock: Optional[str] = None,
    **scorecard_overrides,
) -> dict:
    """Finalise a failing scorecard and return the plan the cascade issued."""
    scorecard = setup_finalized_scorecard(
        vendor_id, measurement_variant, measure_clock, **scorecard_overrides
    )
    cap = first_cap_for_scorecard(scorecard["id"])
    return {"scorecard": scorecard, "cap": cap}
