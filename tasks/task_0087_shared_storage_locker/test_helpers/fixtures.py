"""Composite setup helpers — multi-step preambles tests can reuse.

PRD §2.11 logical-clock semantics: the test driver advances the
server clock via POST /_clock/advance, and triggers time-gated
transitions via POST /_sweep/run. These fixtures use the shared
operator headers for those calls.

IDENTITY THREADING — PRD §2.1: Renter ownership compares
X-User-ID against Rental.renter_id (or InsuranceClaim.renter_id).
Because the server takes renter_id from X-User-ID at rental
creation time, any ownership-gated follow-up call MUST use
make_renter_headers(<same renter_id>). These fixtures therefore
ACCEPT a renter_id argument and return it together with the
created rental, so consumers can build the matching headers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    approve_claim_payload,
    clock_advance_payload,
    create_cabinet_payload,
    create_compartment_payload,
    create_insurance_claim_payload,
    create_pricing_profile_payload,
    create_rental_payload,
    create_repair_ticket_payload,
    deny_claim_payload,
    dispatch_repair_payload,
    iso_utc,
    refund_rental_payload,
    reject_evidence_payload,
    renew_rental_payload,
    repair_ticket_payload,
    return_rental_payload,
    submit_evidence_payload,
)
from .test_users import (
    INSURANCE_AGENT_ID,
    OPERATOR_ID,
    RENTER_ID_DEFAULT,
    TECHNICIAN_ID_DEFAULT,
    TEST_USERS,
    make_insurance_agent_headers,
    make_renter_headers,
    make_technician_headers,
)


# A fixed "epoch" the tests advance from, in PRD §2.11 logical-clock form.
TEST_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _op_headers() -> Dict[str, str]:
    return TEST_USERS["operator_headers"]


def _agent_headers() -> Dict[str, str]:
    return TEST_USERS["insurance_agent_headers"]


def _data(resp) -> Dict[str, Any]:
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock controls (PRD §2.11)
# ---------------------------------------------------------------------------
def reset_clock_to_epoch() -> str:
    """Set the logical clock to TEST_EPOCH and return its ISO string."""
    iso = iso_utc(TEST_EPOCH)
    _data(api_client.clock_advance(
        clock_advance_payload(iso), _op_headers(),
    ))
    return iso


def advance_clock_to(target: datetime) -> str:
    iso = iso_utc(target)
    _data(api_client.clock_advance(
        clock_advance_payload(iso), _op_headers(),
    ))
    return iso


def run_sweep() -> Dict[str, Any]:
    return _data(api_client.sweep_run(_op_headers()))


# ---------------------------------------------------------------------------
# Tier 1 — primitive entity creators (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
def create_pricing_profile(
    size_class: str = "SMALL",
    rental_mode: str = "HOURLY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_pricing_profile_payload(
        size_class=size_class, rental_mode=rental_mode, **overrides,
    )
    return _data(api_client.create_pricing_profile(payload, _op_headers()))


def create_cabinet(
    location_code: str = "BJ-CHAOYANG-001",
    partner_share_pct: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_cabinet_payload(
        location_code=location_code,
        partner_share_pct=partner_share_pct,
        **overrides,
    )
    return _data(api_client.create_cabinet(payload, _op_headers()))


def create_compartment(
    cabinet_id: str,
    slot_number: int = 1,
    size_class: str = "SMALL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_compartment_payload(
        slot_number=slot_number, size_class=size_class, **overrides,
    )
    return _data(api_client.create_compartment(cabinet_id, payload, _op_headers()))


# ---------------------------------------------------------------------------
# Tier 2 — composite "ready for renter" scenarios
# ---------------------------------------------------------------------------
def setup_cabinet_with_compartment(
    *,
    size_class: str = "SMALL",
    rental_mode: str = "HOURLY",
    slot_count: int = 1,
    cabinet_overrides: Optional[Dict[str, Any]] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
    create_pricing: bool = True,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Cabinet + N compartments + (optional) pricing profile.

    Returns (cabinet, compartments, pricing_profile_or_None)."""
    cabinet = create_cabinet(**(cabinet_overrides or {}))
    compartments = []
    for i in range(slot_count):
        compartments.append(create_compartment(
            cabinet_id=cabinet["id"], slot_number=i + 1, size_class=size_class,
        ))
    pricing = None
    if create_pricing:
        pricing = create_pricing_profile(
            size_class=size_class, rental_mode=rental_mode,
            **(pricing_overrides or {}),
        )
    return cabinet, compartments, pricing


def create_active_rental(
    cabinet_id: str,
    compartment_id: str,
    *,
    renter_id: str = RENTER_ID_DEFAULT,
    rental_mode: str = "HOURLY",
    billing_units: int = 1,
    unlock_channel: str = "QR",
    insurance_tier: str = "NONE",
    declared_value_cents: int = 0,
    **payload_overrides: Any,
) -> Tuple[Dict[str, Any], str]:
    """Create a rental as the given renter; returns (rental, renter_id) so
    ownership-gated follow-up calls can use make_renter_headers(renter_id)."""
    payload = create_rental_payload(
        rental_mode=rental_mode,
        billing_units=billing_units,
        unlock_channel=unlock_channel,
        insurance_tier=insurance_tier,
        declared_value_cents=declared_value_cents,
        **payload_overrides,
    )
    rental = _data(api_client.create_rental(
        cabinet_id, compartment_id, payload, make_renter_headers(renter_id),
    ))
    return rental, renter_id


def setup_basic_rental(
    *,
    renter_id: str = RENTER_ID_DEFAULT,
    rental_mode: str = "HOURLY",
    billing_units: int = 1,
    unlock_channel: str = "QR",
    insurance_tier: str = "NONE",
    declared_value_cents: int = 0,
    cabinet_overrides: Optional[Dict[str, Any]] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """End-to-end one-shot: cabinet + compartment + pricing + active rental.

    Returns a dict with keys: cabinet, compartment, pricing, rental, renter_id.
    """
    cabinet, compartments, pricing = setup_cabinet_with_compartment(
        size_class="SMALL",
        rental_mode=rental_mode,
        slot_count=1,
        cabinet_overrides=cabinet_overrides,
        pricing_overrides=pricing_overrides,
    )
    rental, _ = create_active_rental(
        cabinet["id"], compartments[0]["id"],
        renter_id=renter_id,
        rental_mode=rental_mode,
        billing_units=billing_units,
        unlock_channel=unlock_channel,
        insurance_tier=insurance_tier,
        declared_value_cents=declared_value_cents,
    )
    return {
        "cabinet": cabinet,
        "compartment": compartments[0],
        "pricing": pricing,
        "rental": rental,
        "renter_id": renter_id,
    }


# ---------------------------------------------------------------------------
# Tier 3 — state-progression shortcuts (PRD §3.3, §3.5, §3.6)
# ---------------------------------------------------------------------------
def drive_rental_to_overdue(
    rental_started_at: datetime,
    *,
    grace_minutes: int = 15,
    extra_seconds_past_grace: int = 1,
) -> str:
    """Advance the clock past grace_end and run /_sweep/run.

    rental_started_at is the started_at the fixture observed on the rental;
    HOURLY single-unit rentals expire at started_at + 1h, so grace_end =
    started_at + 1h + grace_minutes. Returns the advanced timestamp.
    """
    grace_end = rental_started_at + timedelta(hours=1, minutes=grace_minutes)
    target = grace_end + timedelta(seconds=extra_seconds_past_grace)
    iso = advance_clock_to(target)
    run_sweep()
    return iso


def return_rental_as_owner(rental: Dict[str, Any], renter_id: str,
                           unlock_channel: str = "QR") -> Dict[str, Any]:
    headers = make_renter_headers(renter_id)
    payload = return_rental_payload(unlock_channel=unlock_channel)
    return _data(api_client.return_rental(rental["id"], payload, headers))


def refund_rental_as_operator(rental_id: str,
                              version: Optional[int] = None) -> Dict[str, Any]:
    payload = refund_rental_payload(version=version)
    return _data(api_client.refund_rental(rental_id, payload, _op_headers()))


def setup_returned_rental(
    *,
    renter_id: str = RENTER_ID_DEFAULT,
    billing_units: int = 1,
    insurance_tier: str = "NONE",
    declared_value_cents: int = 0,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Active → RETURNED. Returns dict with cabinet/compartment/rental/renter_id."""
    ctx = setup_basic_rental(
        renter_id=renter_id,
        rental_mode="HOURLY",
        billing_units=billing_units,
        insurance_tier=insurance_tier,
        declared_value_cents=declared_value_cents,
        pricing_overrides=pricing_overrides,
    )
    returned = return_rental_as_owner(ctx["rental"], renter_id)
    ctx["rental"] = returned
    return ctx


def setup_refunded_rental(
    *,
    renter_id: str = RENTER_ID_DEFAULT,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = setup_returned_rental(
        renter_id=renter_id, pricing_overrides=pricing_overrides,
    )
    refunded = refund_rental_as_operator(
        ctx["rental"]["id"], version=ctx["rental"]["version"],
    )
    ctx["rental"] = refunded
    return ctx


def setup_overdue_rental(
    *,
    renter_id: str = RENTER_ID_DEFAULT,
    billing_units: int = 1,
    grace_minutes: int = 15,
    seconds_past_grace: int = 3600 + 1,
    insurance_tier: str = "NONE",
    declared_value_cents: int = 0,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Active → OVERDUE. seconds_past_grace controls overdue duration
    (default = 3601s past grace, i.e., 2 ceil'd hours of accrual)."""
    reset_clock_to_epoch()
    ctx = setup_basic_rental(
        renter_id=renter_id,
        rental_mode="HOURLY",
        billing_units=billing_units,
        insurance_tier=insurance_tier,
        declared_value_cents=declared_value_cents,
        pricing_overrides={"grace_minutes": grace_minutes,
                           **(pricing_overrides or {})},
    )
    started_at = datetime.fromisoformat(
        ctx["rental"]["started_at"].replace("Z", "+00:00"),
    )
    drive_rental_to_overdue(
        started_at, grace_minutes=grace_minutes,
        extra_seconds_past_grace=seconds_past_grace,
    )
    # Refresh the rental so the caller sees status=OVERDUE.
    refreshed = _data(api_client.get_rental(
        ctx["rental"]["id"], make_renter_headers(renter_id),
    ))
    ctx["rental"] = refreshed
    return ctx


def setup_force_cleared_rental(
    *,
    renter_id: str = RENTER_ID_DEFAULT,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Active → OVERDUE → FORCE_CLEARED. Default profile uses
    forced_clearance_hours=2 (well above grace_minutes/60=0.25 minimum)
    so we don't have to advance the clock multiple days.
    """
    reset_clock_to_epoch()
    p_over = {"grace_minutes": 15,
              "forced_clearance_hours": 2,
              **(pricing_overrides or {})}
    ctx = setup_basic_rental(
        renter_id=renter_id,
        rental_mode="HOURLY",
        billing_units=1,
        pricing_overrides=p_over,
    )
    started_at = datetime.fromisoformat(
        ctx["rental"]["started_at"].replace("Z", "+00:00"),
    )
    # current_expires_at = started_at + 1h. forced_clearance fires when
    # now >= current_expires_at + forced_clearance_hours_snapshot * 3600s.
    fc_seconds = 2 * 3600  # forced_clearance_hours=2
    target = started_at + timedelta(hours=1, seconds=fc_seconds + 1)
    advance_clock_to(target)
    run_sweep()
    refreshed = _data(api_client.get_rental(
        ctx["rental"]["id"], _op_headers(),
    ))
    ctx["rental"] = refreshed
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — repair-ticket walkers (PRD §3.8)
# ---------------------------------------------------------------------------
def open_repair_ticket(compartment_id: str,
                       fault_category: str = "DOOR_NOT_CLOSED",
                       *, reporter_headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    payload = create_repair_ticket_payload(
        compartment_id=compartment_id, fault_category=fault_category,
    )
    headers = reporter_headers or _op_headers()
    return _data(api_client.create_repair_ticket(payload, headers))


def dispatch_repair_ticket(ticket_id: str,
                           technician_id: str = TECHNICIAN_ID_DEFAULT,
                           version: Optional[int] = None) -> Dict[str, Any]:
    payload = dispatch_repair_payload(
        assigned_technician_id=technician_id, version=version,
    )
    return _data(api_client.dispatch_repair(ticket_id, payload, _op_headers()))


def repair_as_technician(ticket_id: str,
                         technician_id: str = TECHNICIAN_ID_DEFAULT,
                         repair_notes: str = "door realigned",
                         version: Optional[int] = None) -> Dict[str, Any]:
    payload = repair_ticket_payload(repair_notes=repair_notes, version=version)
    return _data(api_client.repair_ticket(
        ticket_id, payload, make_technician_headers(technician_id),
    ))


def accept_repair(ticket_id: str,
                  version: Optional[int] = None) -> Dict[str, Any]:
    payload = {"version": version} if version is not None else {}
    return _data(api_client.accept_repair(ticket_id, _op_headers(), payload))


def walk_repair_to_accepted(compartment_id: str,
                            fault_category: str = "DOOR_NOT_CLOSED",
                            ) -> Dict[str, Any]:
    ticket = open_repair_ticket(compartment_id, fault_category=fault_category)
    ticket = dispatch_repair_ticket(ticket["id"], version=ticket["version"])
    ticket = repair_as_technician(ticket["id"], version=ticket["version"])
    ticket = accept_repair(ticket["id"], version=ticket["version"])
    return ticket


# ---------------------------------------------------------------------------
# Tier 5 — insurance-claim walkers (PRD §3.9)
# ---------------------------------------------------------------------------
def file_insurance_claim(rental_id: str, renter_id: str,
                         claim_type: str = "DAMAGE",
                         claimed_amount_cents: int = 100_000,
                         ) -> Dict[str, Any]:
    payload = create_insurance_claim_payload(
        rental_id=rental_id,
        claim_type=claim_type,
        claimed_amount_cents=claimed_amount_cents,
    )
    return _data(api_client.create_insurance_claim(
        payload, make_renter_headers(renter_id),
    ))


def request_evidence(claim_id: str, version: Optional[int] = None
                     ) -> Dict[str, Any]:
    payload = {"version": version} if version is not None else {}
    return _data(api_client.request_evidence(claim_id, _agent_headers(), payload))


def submit_evidence(claim_id: str, renter_id: str,
                    description: str = "photo",
                    version: Optional[int] = None) -> Dict[str, Any]:
    payload = submit_evidence_payload(
        evidence_description=description, version=version,
    )
    return _data(api_client.submit_evidence(
        claim_id, payload, make_renter_headers(renter_id),
    ))


def reject_evidence(claim_id: str, reason: str = "blurry",
                    version: Optional[int] = None) -> Dict[str, Any]:
    payload = reject_evidence_payload(rejection_reason=reason, version=version)
    return _data(api_client.reject_evidence(claim_id, payload, _agent_headers()))


def approve_claim(claim_id: str, payout_cents: int,
                  version: Optional[int] = None) -> Dict[str, Any]:
    payload = approve_claim_payload(payout_cents=payout_cents, version=version)
    return _data(api_client.approve_claim(claim_id, payload, _agent_headers()))


def deny_claim(claim_id: str, reason: str = "denied",
               version: Optional[int] = None) -> Dict[str, Any]:
    payload = deny_claim_payload(rejection_reason=reason, version=version)
    return _data(api_client.deny_claim(claim_id, payload, _agent_headers()))


def pay_claim(claim_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    payload = {"version": version} if version is not None else {}
    return _data(api_client.pay_claim(claim_id, _agent_headers(), payload))


def setup_returned_rental_with_insurance_claim(
    *,
    renter_id: str = RENTER_ID_DEFAULT,
    declared_value_cents: int = 500_000,
    claimed_amount_cents: int = 300_000,
    claim_type: str = "DAMAGE",
    insurance_tier: str = "BASIC",
) -> Dict[str, Any]:
    """Active BASIC/PREMIUM rental → return → open claim (REPORTED).

    Returns dict with: cabinet, compartment, rental, claim, renter_id.
    """
    ctx = setup_returned_rental(
        renter_id=renter_id,
        insurance_tier=insurance_tier,
        declared_value_cents=declared_value_cents,
    )
    claim = file_insurance_claim(
        ctx["rental"]["id"], renter_id,
        claim_type=claim_type,
        claimed_amount_cents=claimed_amount_cents,
    )
    ctx["claim"] = claim
    return ctx


def drive_claim_to_denied(claim: Dict[str, Any], renter_id: str
                          ) -> Dict[str, Any]:
    """REPORTED → EVIDENCE_PENDING → submit → UNDER_REVIEW → deny → DENIED."""
    c = request_evidence(claim["id"], version=claim["version"])
    c = submit_evidence(c["id"], renter_id, version=c["version"])
    c = deny_claim(c["id"], version=c["version"])
    return c


# ---------------------------------------------------------------------------
# Tier 6 — capacity-targeting helpers (PRD §3.7)
# ---------------------------------------------------------------------------
def setup_cabinet_with_n_small_compartments(
    n: int,
    *,
    rental_mode: str = "DAILY",
    cabinet_overrides: Optional[Dict[str, Any]] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """N SMALL compartments + matching pricing profile."""
    cabinet, compartments, pricing = setup_cabinet_with_compartment(
        size_class="SMALL",
        rental_mode=rental_mode,
        slot_count=n,
        cabinet_overrides=cabinet_overrides,
        pricing_overrides=pricing_overrides,
    )
    return cabinet, compartments, pricing


def rent_k_compartments(cabinet_id: str, compartments: List[Dict[str, Any]],
                        k: int, *, rental_mode: str = "DAILY",
                        unlock_channel: str = "QR",
                        ) -> List[Tuple[Dict[str, Any], str]]:
    """Create k rentals on the first k compartments, each with a distinct
    renter_id. Returns list of (rental, renter_id) tuples."""
    out: List[Tuple[Dict[str, Any], str]] = []
    for i, comp in enumerate(compartments[:k]):
        renter_id = f"renter-bulk-{i + 1:03d}"
        rental, _ = create_active_rental(
            cabinet_id, comp["id"],
            renter_id=renter_id,
            rental_mode=rental_mode,
            billing_units=1,
            unlock_channel=unlock_channel,
        )
        out.append((rental, renter_id))
    return out


# ---------------------------------------------------------------------------
# Tier 7 — offline cabinet (PRD §3.1)
# ---------------------------------------------------------------------------
def drive_cabinet_offline(cabinet_id: str,
                          *, starting_at: Optional[datetime] = None,
                          ) -> str:
    """Set last_heartbeat_at via /heartbeat, advance the clock 15m+1s,
    and run the sweep. Cabinet should be OFFLINE afterwards.

    Returns the advanced timestamp as ISO."""
    _data(api_client.cabinet_heartbeat(cabinet_id, _op_headers()))
    # advance the logical clock 15m+1s into the future
    now_dt = starting_at or TEST_EPOCH
    target = now_dt + timedelta(minutes=16)
    iso = advance_clock_to(target)
    run_sweep()
    return iso


__all__ = [
    "TEST_EPOCH",
    "reset_clock_to_epoch",
    "advance_clock_to",
    "run_sweep",
    "create_pricing_profile",
    "create_cabinet",
    "create_compartment",
    "setup_cabinet_with_compartment",
    "create_active_rental",
    "setup_basic_rental",
    "drive_rental_to_overdue",
    "return_rental_as_owner",
    "refund_rental_as_operator",
    "setup_returned_rental",
    "setup_refunded_rental",
    "setup_overdue_rental",
    "setup_force_cleared_rental",
    "open_repair_ticket",
    "dispatch_repair_ticket",
    "repair_as_technician",
    "accept_repair",
    "walk_repair_to_accepted",
    "file_insurance_claim",
    "request_evidence",
    "submit_evidence",
    "reject_evidence",
    "approve_claim",
    "deny_claim",
    "pay_claim",
    "setup_returned_rental_with_insurance_claim",
    "drive_claim_to_denied",
    "setup_cabinet_with_n_small_compartments",
    "rent_k_compartments",
    "drive_cabinet_offline",
]
