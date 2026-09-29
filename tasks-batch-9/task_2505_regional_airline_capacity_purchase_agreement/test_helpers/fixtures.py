"""Composite setup builders.

Every test starts against an empty service whose logical clock reads
2026-08-01T00:00:00Z, so every precondition has to be built through the public
endpoints. The builders here climb the entity hierarchy and the state machines
that most scenarios share, and each returns the created resources so a test can
name the identifiers it needs.

Builders use the lenient success reader rather than the strict validator: a
failure to construct a precondition should surface as a readable KeyError or a
missing-status assertion in the test body, not as a validation error attributed to
the endpoint under examination.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import CpaApiClient
from .factories import (
    make_advance_payload,
    make_agreement_payload,
    make_aircraft_payload,
    make_attrite_payload,
    make_brand_audit_payload,
    make_cancel_payload,
    make_classify_payload,
    make_completion_payload,
    make_crew_base_payload,
    make_dispute_payload,
    make_extension_offer_payload,
    make_flight_leg_payload,
    make_invoice_payload,
    make_pass_through_payload,
    make_pilot_payload,
    make_reconcile_payload,
    make_remediation_payload,
    make_schedule_cycle_payload,
    make_submit_actual_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OPS_HEADERS,
    SCHEDULER_HEADERS,
    make_base_chief_pilot_headers,
)
from .types import (
    AgreementScenario,
    CycleScenario,
    Headers,
    JsonDict,
    SettledCycleScenario,
    StaffedBaseScenario,
)

# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and single state steps
# ---------------------------------------------------------------------------


def create_agreement(
    api: CpaApiClient, payload: Optional[JsonDict] = None, headers: Headers = ADMIN_HEADERS
) -> JsonDict:
    """Register a DRAFT agreement with its rate card."""
    response = api.create_agreement(payload or make_agreement_payload(), headers=headers)
    return get_success_data(response)


def create_crew_base(
    api: CpaApiClient,
    agreement_id: str,
    station_code: str = "PDX",
    pilots_required_per_aircraft: int = 1,
    aircraft_allocation_cap: int = 2,
    headers: Headers = OPS_HEADERS,
) -> JsonDict:
    """Open a crew base against an agreement."""
    response = api.create_crew_base(
        make_crew_base_payload(
            agreement_id,
            station_code=station_code,
            pilots_required_per_aircraft=pilots_required_per_aircraft,
            aircraft_allocation_cap=aircraft_allocation_cap,
        ),
        headers=headers,
    )
    return get_success_data(response)


def activate_agreement(api: CpaApiClient, agreement_id: str) -> JsonDict:
    """Move a DRAFT agreement to ACTIVE."""
    return get_success_data(api.activate_agreement(agreement_id, headers=ADMIN_HEADERS))


def hire_pilot(
    api: CpaApiClient,
    base_id: str,
    employee_ref: str,
    seat: str = "CAPTAIN",
    hire_class_date: str = "2026-07-01",
) -> JsonDict:
    """Add one pilot to a base's pipeline."""
    response = api.create_pilot(
        make_pilot_payload(
            base_id, employee_ref=employee_ref, seat=seat, hire_class_date=hire_class_date
        ),
        headers=OPS_HEADERS,
    )
    return get_success_data(response)


def advance_pilot_to(api: CpaApiClient, pilot_id: str, base_id: str, to_status: str) -> JsonDict:
    """Walk a pilot one training step, acting as the chief pilot of its own base."""
    response = api.post_raw(
        f"/cpa/pilots/{pilot_id}/advance",
        json=make_advance_payload(to_status),
        headers=make_base_chief_pilot_headers(base_id),
    )
    return get_success_data(response)


def qualify_pilot(api: CpaApiClient, pilot_id: str, base_id: str) -> JsonDict:
    """Take a pipeline pilot all the way to LINE_QUALIFIED."""
    advance_pilot_to(api, pilot_id, base_id, "IN_TRAINING")
    return advance_pilot_to(api, pilot_id, base_id, "LINE_QUALIFIED")


def attrite_pilot(
    api: CpaApiClient, pilot_id: str, base_id: str, destination: str = "MAINLINE"
) -> JsonDict:
    """Record a pilot leaving the base."""
    response = api.attrite_pilot(
        pilot_id,
        make_attrite_payload(destination),
        headers=make_base_chief_pilot_headers(base_id),
    )
    return get_success_data(response)


def register_aircraft(
    api: CpaApiClient,
    agreement_id: str,
    base_id: str,
    tail_number: str = "N101CR",
    ownership: str = "REGIONAL_OWNED",
    seat_count: int = 76,
) -> JsonDict:
    """Register a tail in PENDING_INDUCTION."""
    response = api.create_aircraft(
        make_aircraft_payload(
            agreement_id,
            base_id,
            tail_number=tail_number,
            ownership=ownership,
            seat_count=seat_count,
        ),
        headers=OPS_HEADERS,
    )
    return get_success_data(response)


def induct_aircraft(api: CpaApiClient, aircraft_id: str) -> JsonDict:
    """Place a pending tail into revenue service."""
    return get_success_data(api.induct_aircraft(aircraft_id, headers=OPS_HEADERS))


def create_cycle(
    api: CpaApiClient,
    agreement_id: str,
    cycle_month: str = "2026-08",
    published_departures: int = 100,
) -> JsonDict:
    """Publish a settlement month in PLANNED."""
    response = api.create_schedule_cycle(
        make_schedule_cycle_payload(
            agreement_id,
            cycle_month=cycle_month,
            published_departures=published_departures,
        ),
        headers=SCHEDULER_HEADERS,
    )
    return get_success_data(response)


def open_cycle(api: CpaApiClient, cycle_id: str) -> JsonDict:
    """Open a planned month for flying and reporting."""
    return get_success_data(api.open_schedule_cycle(cycle_id, headers=SCHEDULER_HEADERS))


def close_cycle(api: CpaApiClient, cycle_id: str) -> JsonDict:
    """Close the month, settling pass-throughs and publishing a scorecard."""
    return get_success_data(api.close_schedule_cycle(cycle_id, headers=SCHEDULER_HEADERS))


def schedule_leg(api: CpaApiClient, payload: JsonDict) -> JsonDict:
    """Publish a flight leg."""
    return get_success_data(api.create_flight_leg(payload, headers=SCHEDULER_HEADERS))


def complete_leg(api: CpaApiClient, leg_id: str, payload: Optional[JsonDict] = None) -> JsonDict:
    """Report a leg as flown."""
    response = api.complete_flight_leg(
        leg_id, payload or make_completion_payload(), headers=OPS_HEADERS
    )
    return get_success_data(response)


def cancel_leg(api: CpaApiClient, leg_id: str, cause_code: str = "MAINTENANCE") -> JsonDict:
    """Cancel a scheduled leg, which opens exactly one cancellation claim."""
    response = api.cancel_flight_leg(leg_id, make_cancel_payload(cause_code), headers=OPS_HEADERS)
    return get_success_data(response)


def reinstate_leg(api: CpaApiClient, leg_id: str) -> JsonDict:
    """Reinstate a cancelled leg, voiding its claim."""
    return get_success_data(api.reinstate_flight_leg(leg_id, headers=OPS_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1: reading current state back
# ---------------------------------------------------------------------------


def read_agreement(api: CpaApiClient, agreement_id: str) -> JsonDict:
    """The agreement as it currently stands, including its derived counters."""
    return get_success_data(api.get_agreement(agreement_id, headers=ADMIN_HEADERS))


def read_crew_base(api: CpaApiClient, base_id: str) -> JsonDict:
    """The crew base as it currently stands, including both shortfall bases."""
    return get_success_data(api.get_crew_base(base_id, headers=ADMIN_HEADERS))


def read_aircraft(api: CpaApiClient, aircraft_id: str) -> JsonDict:
    """The tail as it currently stands."""
    return get_success_data(api.get_aircraft(aircraft_id, headers=ADMIN_HEADERS))


def read_pilot(api: CpaApiClient, pilot_id: str) -> JsonDict:
    """The pilot as it currently stands."""
    return get_success_data(api.get_pilot(pilot_id, headers=ADMIN_HEADERS))


def read_cycle(api: CpaApiClient, cycle_id: str) -> JsonDict:
    """The month as it currently stands, with its ledger counters."""
    return get_success_data(api.get_schedule_cycle(cycle_id, headers=ADMIN_HEADERS))


def read_leg(api: CpaApiClient, leg_id: str) -> JsonDict:
    """The leg as it currently stands, including its variable payment."""
    return get_success_data(api.get_flight_leg(leg_id, headers=ADMIN_HEADERS))


def read_invoice(api: CpaApiClient, invoice_id: str) -> JsonDict:
    """The invoice as it currently stands, with all of its components."""
    return get_success_data(api.get_invoice(invoice_id, headers=ADMIN_HEADERS))


def read_scorecard(api: CpaApiClient, scorecard_id: str) -> JsonDict:
    """The scorecard as it currently stands."""
    return get_success_data(api.get_scorecard(scorecard_id, headers=ADMIN_HEADERS))


def read_brand_audit(api: CpaApiClient, audit_id: str) -> JsonDict:
    """The brand audit as it currently stands, with both status dimensions."""
    return get_success_data(api.get_brand_audit(audit_id, headers=ADMIN_HEADERS))


def read_negotiation(api: CpaApiClient, negotiation_id: str) -> JsonDict:
    """The extension round as it currently stands."""
    return get_success_data(api.get_extension_negotiation(negotiation_id, headers=ADMIN_HEADERS))


def agreement_version(api: CpaApiClient, agreement_id: str) -> int:
    """The agreement's current version, for the stale-version guard on offers."""
    return read_agreement(api, agreement_id)["version"]


def cycle_version(api: CpaApiClient, cycle_id: str) -> int:
    """The month's current version, for the stale-version guard on invoices."""
    return read_cycle(api, cycle_id)["version"]


def claim_for_leg(api: CpaApiClient, leg_id: str) -> JsonDict:
    """The single cancellation claim the server opened for a cancelled leg."""
    response = api.list_cancellation_claims(headers=ADMIN_HEADERS, params={"leg_id": leg_id})
    data = get_success_data(response)
    records = data["data"] if isinstance(data, dict) and "data" in data else data
    assert records, f"a cancellation claim should exist for leg {leg_id}"
    return records[0]


def scorecard_for_cycle(api: CpaApiClient, cycle_id: str) -> JsonDict:
    """The single scorecard the close of a month published."""
    response = api.list_scorecards(headers=ADMIN_HEADERS, params={"cycle_id": cycle_id})
    data = get_success_data(response)
    records = data["data"] if isinstance(data, dict) and "data" in data else data
    assert records, f"a scorecard should exist for cycle {cycle_id}"
    return records[0]


# ---------------------------------------------------------------------------
# Tier 2: the entity hierarchy
# ---------------------------------------------------------------------------


def build_active_agreement(
    api: CpaApiClient,
    *,
    agreement_payload: Optional[JsonDict] = None,
    station_code: str = "PDX",
    pilots_required_per_aircraft: int = 1,
    aircraft_allocation_cap: int = 2,
) -> AgreementScenario:
    """An ACTIVE agreement with one ACTIVE crew base underneath it.

    Activation is only permitted once at least one crew base has been opened
    against the agreement, so the base is created before the activation call.
    """
    agreement = create_agreement(api, agreement_payload)
    base = create_crew_base(
        api,
        agreement["id"],
        station_code=station_code,
        pilots_required_per_aircraft=pilots_required_per_aircraft,
        aircraft_allocation_cap=aircraft_allocation_cap,
    )
    agreement = activate_agreement(api, agreement["id"])
    return AgreementScenario(
        agreement=agreement,
        crew_base=base,
        base_headers=make_base_chief_pilot_headers(base["id"]),
    )


def build_staffed_base(
    api: CpaApiClient,
    *,
    agreement_payload: Optional[JsonDict] = None,
    station_code: str = "PDX",
    pilots_required_per_aircraft: int = 1,
    aircraft_allocation_cap: int = 2,
    line_qualified_pilots: int = 1,
    tail_numbers: Optional[List[str]] = None,
    ownership: str = "REGIONAL_OWNED",
    induct: bool = True,
) -> StaffedBaseScenario:
    """An ACTIVE agreement whose base holds line-qualified captains and tails.

    Induction requires the base's line-qualified headcount to cover the tails it
    would then hold, so the pilots are qualified before any tail is inducted.
    """
    scenario = build_active_agreement(
        api,
        agreement_payload=agreement_payload,
        station_code=station_code,
        pilots_required_per_aircraft=pilots_required_per_aircraft,
        aircraft_allocation_cap=aircraft_allocation_cap,
    )
    pilots: List[JsonDict] = []
    for index in range(line_qualified_pilots):
        pilot = hire_pilot(api, scenario.crew_base_id, f"EMP-{index + 1:04d}")
        pilots.append(qualify_pilot(api, pilot["id"], scenario.crew_base_id))

    tails: List[JsonDict] = []
    for index, tail_number in enumerate(tail_numbers or ["N101CR"]):
        tail = register_aircraft(
            api,
            scenario.agreement_id,
            scenario.crew_base_id,
            tail_number=tail_number,
            ownership=ownership,
        )
        if induct:
            tail = induct_aircraft(api, tail["id"])
        tails.append(tail)

    return StaffedBaseScenario(
        agreement=read_agreement(api, scenario.agreement_id),
        crew_base=read_crew_base(api, scenario.crew_base_id),
        base_headers=scenario.base_headers,
        pilots=pilots,
        aircraft=tails,
    )


def build_open_cycle(
    api: CpaApiClient,
    *,
    agreement_payload: Optional[JsonDict] = None,
    station_code: str = "PDX",
    pilots_required_per_aircraft: int = 1,
    aircraft_allocation_cap: int = 2,
    line_qualified_pilots: int = 1,
    tail_numbers: Optional[List[str]] = None,
    ownership: str = "REGIONAL_OWNED",
    cycle_month: str = "2026-08",
    published_departures: int = 100,
) -> CycleScenario:
    """A staffed base with an inducted tail and an OPEN settlement month."""
    staffed = build_staffed_base(
        api,
        agreement_payload=agreement_payload,
        station_code=station_code,
        pilots_required_per_aircraft=pilots_required_per_aircraft,
        aircraft_allocation_cap=aircraft_allocation_cap,
        line_qualified_pilots=line_qualified_pilots,
        tail_numbers=tail_numbers,
        ownership=ownership,
    )
    cycle = create_cycle(
        api,
        staffed.agreement_id,
        cycle_month=cycle_month,
        published_departures=published_departures,
    )
    cycle = open_cycle(api, cycle["id"])
    return CycleScenario(
        agreement=staffed.agreement,
        crew_base=staffed.crew_base,
        base_headers=staffed.base_headers,
        pilots=staffed.pilots,
        aircraft=staffed.aircraft,
        cycle=cycle,
    )


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------


def add_leg(
    api: CpaApiClient,
    scenario: CycleScenario,
    *,
    flight_number: str = "SA1200",
    scheduled_departure_utc: str = "2026-08-05T14:00:00Z",
    scheduled_arrival_utc: str = "2026-08-05T15:30:00Z",
    planned_block_hours: float = 1.500,
    aircraft_id: Optional[str] = None,
    captain_pilot_id: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    """Publish one leg into an open month and remember it on the scenario."""
    leg = schedule_leg(
        api,
        make_flight_leg_payload(
            scenario.cycle_id,
            aircraft_id or scenario.aircraft_id,
            captain_pilot_id or scenario.captain_pilot_id,
            flight_number=flight_number,
            scheduled_departure_utc=scheduled_departure_utc,
            scheduled_arrival_utc=scheduled_arrival_utc,
            planned_block_hours=planned_block_hours,
            **overrides,
        ),
    )
    scenario.legs.append(leg)
    return leg


def build_cycle_with_completed_leg(
    api: CpaApiClient,
    *,
    actual_block_hours: float = 1.500,
    enplaned_bags: int = 1000,
    mishandled_bags: int = 2,
    published_departures: int = 100,
    on_time: bool = True,
    **cycle_kwargs: Any,
) -> CycleScenario:
    """An open month carrying exactly one completed leg.

    The reported arrival is placed inside the fourteen-minute inclusive grace
    allowance for an on-time completion and well outside it otherwise.
    """
    scenario = build_open_cycle(api, published_departures=published_departures, **cycle_kwargs)
    leg = add_leg(api, scenario, planned_block_hours=actual_block_hours)
    arrival = "2026-08-05T15:30:00Z" if on_time else "2026-08-05T16:30:00Z"
    completed = complete_leg(
        api,
        leg["id"],
        make_completion_payload(
            actual_block_hours=actual_block_hours,
            actual_arrival_utc=arrival,
            enplaned_bags=enplaned_bags,
            mishandled_bags=mishandled_bags,
        ),
    )
    scenario.legs[-1] = completed
    scenario.cycle = read_cycle(api, scenario.cycle_id)
    return scenario


def build_cancelled_leg_with_claim(
    api: CpaApiClient,
    *,
    cause_code: str = "MAINTENANCE",
    published_departures: int = 100,
    **cycle_kwargs: Any,
) -> Tuple[CycleScenario, JsonDict, JsonDict]:
    """An open month with one cancelled leg and the claim the cancellation raised."""
    scenario = build_open_cycle(api, published_departures=published_departures, **cycle_kwargs)
    leg = add_leg(api, scenario)
    cancelled = cancel_leg(api, leg["id"], cause_code=cause_code)
    scenario.legs[-1] = cancelled
    scenario.cycle = read_cycle(api, scenario.cycle_id)
    return scenario, cancelled, claim_for_leg(api, leg["id"])


def classify_claim(
    api: CpaApiClient, claim_id: str, classification: str = "UNCONTROLLABLE"
) -> JsonDict:
    """Record the mainline partner's verdict on a cancellation."""
    response = api.classify_claim(
        claim_id, make_classify_payload(classification), headers=SCHEDULER_HEADERS
    )
    return get_success_data(response)


def dispute_claim(api: CpaApiClient, claim_id: str, note: Optional[str] = None) -> JsonDict:
    """Send a classified claim back with the regional carrier's rationale."""
    payload = make_dispute_payload(note) if note else make_dispute_payload()
    return get_success_data(api.dispute_claim(claim_id, payload, headers=OPS_HEADERS))


def finalize_claim(api: CpaApiClient, claim_id: str) -> JsonDict:
    """Lock a classified claim's verdict for penalty purposes."""
    return get_success_data(api.finalize_claim(claim_id, headers=ADMIN_HEADERS))


def adjudicate_claim(
    api: CpaApiClient, claim_id: str, classification: str = "UNCONTROLLABLE"
) -> JsonDict:
    """Classify and then finalize a claim in one step."""
    classify_claim(api, claim_id, classification)
    return finalize_claim(api, claim_id)


# ---------------------------------------------------------------------------
# Tier 3: pass-through claims
# ---------------------------------------------------------------------------


def open_pass_through(
    api: CpaApiClient,
    cycle_id: str,
    category: str = "FUEL",
    estimated_amount_usd: float = 40000.00,
) -> JsonDict:
    """Open a cost category against a month with its accrual estimate."""
    response = api.create_pass_through_claim(
        make_pass_through_payload(
            cycle_id, category=category, estimated_amount_usd=estimated_amount_usd
        ),
        headers=OPS_HEADERS,
    )
    return get_success_data(response)


def file_pass_through_actual(
    api: CpaApiClient,
    claim_id: str,
    actual_amount_usd: float,
    supporting_doc_ref: str = "DOC-0001",
    headers: Headers = OPS_HEADERS,
) -> JsonDict:
    """File the invoiced actual, recording the filer for the segregation rule."""
    response = api.submit_actual(
        claim_id,
        make_submit_actual_payload(
            actual_amount_usd=actual_amount_usd, supporting_doc_ref=supporting_doc_ref
        ),
        headers=headers,
    )
    return get_success_data(response)


def reconcile_pass_through(
    api: CpaApiClient,
    claim_id: str,
    decision: str = "APPROVE",
    headers: Headers = ADMIN_HEADERS,
) -> JsonDict:
    """Adjudicate a filed actual against the category tolerance."""
    response = api.reconcile_pass_through(
        claim_id, make_reconcile_payload(decision), headers=headers
    )
    return get_success_data(response)


def build_reconciled_pass_through(
    api: CpaApiClient,
    cycle_id: str,
    *,
    category: str = "FUEL",
    estimated_amount_usd: float = 40000.00,
    actual_amount_usd: float = 41000.00,
    decision: str = "APPROVE",
) -> JsonDict:
    """Take one cost category all the way to a terminal, adjudicated status."""
    claim = open_pass_through(
        api, cycle_id, category=category, estimated_amount_usd=estimated_amount_usd
    )
    file_pass_through_actual(api, claim["id"], actual_amount_usd)
    return reconcile_pass_through(api, claim["id"], decision=decision)


# ---------------------------------------------------------------------------
# Tier 4: brand audits
# ---------------------------------------------------------------------------


def create_brand_audit(
    api: CpaApiClient,
    base_id: str,
    *,
    audit_scope: str = "UNIFORM",
    findings_count: int = 2,
    severity: str = "MAJOR",
) -> JsonDict:
    """Raise a brand-standards audit, which puts it into the exposure set."""
    response = api.create_brand_audit(
        make_brand_audit_payload(
            base_id,
            audit_scope=audit_scope,
            findings_count=findings_count,
            severity=severity,
        ),
        headers=AUDITOR_HEADERS,
    )
    return get_success_data(response)


def acknowledge_brand_audit(api: CpaApiClient, audit_id: str) -> JsonDict:
    """Acknowledge a finding, which changes no exposure."""
    return get_success_data(api.acknowledge_brand_audit(audit_id, headers=OPS_HEADERS))


def advance_remediation(
    api: CpaApiClient,
    audit_id: str,
    to_remediation_status: str,
    evidence_ref: Optional[str] = None,
) -> JsonDict:
    """Move the remediation dimension one step, supplying evidence when required."""
    response = api.advance_remediation(
        audit_id,
        make_remediation_payload(to_remediation_status, evidence_ref=evidence_ref),
        headers=OPS_HEADERS,
    )
    return get_success_data(response)


def verify_remediation(
    api: CpaApiClient, audit_id: str, evidence_ref: str = "EV-0001"
) -> JsonDict:
    """Take the remediation dimension from NOT_STARTED through to VERIFIED."""
    advance_remediation(api, audit_id, "IN_PROGRESS")
    return advance_remediation(api, audit_id, "VERIFIED", evidence_ref=evidence_ref)


def close_brand_audit(api: CpaApiClient, audit_id: str) -> JsonDict:
    """Close an acknowledged finding whose remediation is verified."""
    return get_success_data(api.close_brand_audit(audit_id, headers=AUDITOR_HEADERS))


def build_closed_brand_audit(
    api: CpaApiClient,
    base_id: str,
    *,
    audit_scope: str = "UNIFORM",
    findings_count: int = 2,
    severity: str = "MAJOR",
) -> JsonDict:
    """An audit taken off the exposure set on both dimensions."""
    audit = create_brand_audit(
        api,
        base_id,
        audit_scope=audit_scope,
        findings_count=findings_count,
        severity=severity,
    )
    acknowledge_brand_audit(api, audit["id"])
    verify_remediation(api, audit["id"])
    return close_brand_audit(api, audit["id"])


# ---------------------------------------------------------------------------
# Tier 5: closing the month, invoicing and settlement
# ---------------------------------------------------------------------------


def build_closed_cycle(
    api: CpaApiClient,
    *,
    scenario: Optional[CycleScenario] = None,
    **cycle_kwargs: Any,
) -> SettledCycleScenario:
    """A CLOSED month with its PUBLISHED scorecard.

    Closing requires every leg to have reached a resolved status, so the caller
    either hands in a scenario whose legs are already resolved or lets this builder
    close a month that carries one completed leg.
    """
    if scenario is None:
        scenario = build_cycle_with_completed_leg(api, **cycle_kwargs)
    cycle = close_cycle(api, scenario.cycle_id)
    return SettledCycleScenario(
        agreement=read_agreement(api, scenario.agreement_id),
        crew_base=scenario.crew_base,
        base_headers=scenario.base_headers,
        cycle=cycle,
        legs=scenario.legs,
        scorecard=scorecard_for_cycle(api, scenario.cycle_id),
    )


def raise_invoice(
    api: CpaApiClient,
    cycle_id: str,
    variant: str,
    *,
    expected_schedule_cycle_version: Optional[int] = None,
) -> JsonDict:
    """Raise a DRAFT invoice against a month, quoting the month's current version."""
    version = (
        expected_schedule_cycle_version
        if expected_schedule_cycle_version is not None
        else cycle_version(api, cycle_id)
    )
    response = api.create_invoice(
        cycle_id,
        make_invoice_payload(variant, version),
        headers=ADMIN_HEADERS,
    )
    return get_success_data(response)


def issue_invoice(api: CpaApiClient, invoice_id: str) -> JsonDict:
    """Issue a DRAFT FINAL invoice, moving the month to SETTLED."""
    return get_success_data(api.issue_final_invoice(invoice_id, headers=ADMIN_HEADERS))


def void_invoice(api: CpaApiClient, invoice_id: str) -> JsonDict:
    """Void a DRAFT or ISSUED invoice explicitly."""
    return get_success_data(api.void_invoice(invoice_id, headers=ADMIN_HEADERS))


def build_issued_final_invoice(
    api: CpaApiClient,
    *,
    scenario: Optional[CycleScenario] = None,
    **cycle_kwargs: Any,
) -> SettledCycleScenario:
    """A SETTLED month whose FINAL invoice has been issued."""
    settled = build_closed_cycle(api, scenario=scenario, **cycle_kwargs)
    invoice = raise_invoice(api, settled.cycle_id, "FINAL")
    invoice = issue_invoice(api, invoice["id"])
    settled.invoice = invoice
    settled.cycle = read_cycle(api, settled.cycle_id)
    settled.agreement = read_agreement(api, settled.agreement_id)
    return settled


# ---------------------------------------------------------------------------
# Tier 5: term renegotiation and the logical clock
# ---------------------------------------------------------------------------


def open_extension_offer(
    api: CpaApiClient,
    agreement_id: str,
    *,
    proposed_term_end_date: str = "2031-12-31",
    proposed_block_hour_rate_usd: float = 1520.00,
    expected_agreement_version: Optional[int] = None,
) -> JsonDict:
    """Open an extension round, quoting the agreement's current version."""
    version = (
        expected_agreement_version
        if expected_agreement_version is not None
        else agreement_version(api, agreement_id)
    )
    response = api.create_extension_negotiation(
        agreement_id,
        make_extension_offer_payload(
            version,
            proposed_term_end_date=proposed_term_end_date,
            proposed_block_hour_rate_usd=proposed_block_hour_rate_usd,
        ),
        headers=SCHEDULER_HEADERS,
    )
    return get_success_data(response)


def advance_clock(api: CpaApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Drive the service's logical clock forward, sweeping expired agreements."""
    return get_success_data(api.set_clock(to_iso8601, headers=ADMIN_HEADERS))


__all__ = [
    "create_agreement",
    "create_crew_base",
    "activate_agreement",
    "hire_pilot",
    "advance_pilot_to",
    "qualify_pilot",
    "attrite_pilot",
    "register_aircraft",
    "induct_aircraft",
    "create_cycle",
    "open_cycle",
    "close_cycle",
    "schedule_leg",
    "complete_leg",
    "cancel_leg",
    "reinstate_leg",
    "read_agreement",
    "read_crew_base",
    "read_aircraft",
    "read_pilot",
    "read_cycle",
    "read_leg",
    "read_invoice",
    "read_scorecard",
    "read_brand_audit",
    "read_negotiation",
    "agreement_version",
    "cycle_version",
    "claim_for_leg",
    "scorecard_for_cycle",
    "build_active_agreement",
    "build_staffed_base",
    "build_open_cycle",
    "add_leg",
    "build_cycle_with_completed_leg",
    "build_cancelled_leg_with_claim",
    "classify_claim",
    "dispute_claim",
    "finalize_claim",
    "adjudicate_claim",
    "open_pass_through",
    "file_pass_through_actual",
    "reconcile_pass_through",
    "build_reconciled_pass_through",
    "create_brand_audit",
    "acknowledge_brand_audit",
    "advance_remediation",
    "verify_remediation",
    "close_brand_audit",
    "build_closed_brand_audit",
    "build_closed_cycle",
    "raise_invoice",
    "issue_invoice",
    "void_invoice",
    "build_issued_final_invoice",
    "open_extension_offer",
    "advance_clock",
]
