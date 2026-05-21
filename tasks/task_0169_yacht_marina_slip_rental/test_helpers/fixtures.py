"""Composite setup helpers — multi-step preambles tests can reuse.

The marina-slip-rental lifecycle takes 5-15 API calls to reach
interesting states (a Reservation APPROVED on a size-matched slip with
an ACTIVE policy, a CHECKED_IN reservation with a pump-out scheduled,
a marina with a liveaboard quota nearly full, a SlipTransferRequest in
OFFERED, etc.). Each fixture composes the lower-level steps so test
bodies focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "The `Boater` role is entity-backed: when `X-User-Role` is `Boater`,
    the value of `X-User-ID` is the `id` of the acting `Boater`, and
    ownership checks on any resource that references a boater compare
    the resource's `boater_id` foreign-key field to `X-User-ID`."

After a Boater is created via DockMaster, any subsequent boater-acting
call (create vessel, create reservation, create waitlist entry,
create/accept transfer request, schedule pump-out, buy policy, buy tow
contract, etc.) MUST mint headers via `make_boater_headers(boater["id"])`.
The shared placeholder in TEST_USERS is reserved for negative tests
that probe auth / role / 404 paths without ownership.

CLOCK ANCHORING — PRD §2.7 / §3.1:

    "Time inside a marina advances only when an operator advances it. A
    test-driving capability accepts a target instant via the `to`
    request field and assigns it to the marina's `current_date`."

Marinas are born at `1970-01-01T00:00:00.000Z` (PRD §3.1). Any test
that needs a specific clock (e.g., to gate a check-in) must advance the
clock explicitly via `advance_clock_to_iso`.

Setup calls use `get_success_data` (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    INITIAL_MARINA_CLOCK,
    TEST_DEFAULTS,
)
from .factories import (
    add_days,
    add_hours,
    clock_advance_payload,
    complete_pump_out_payload,
    create_boater_payload,
    create_marina_payload,
    create_policy_payload,
    create_pump_out_payload,
    create_reservation_payload,
    create_slip_payload,
    create_tow_contract_payload,
    create_tow_event_payload,
    create_transfer_request_payload,
    create_utility_reading_payload,
    create_vessel_payload,
    create_waitlist_payload,
    date_iso,
    iso_utc,
    parse_iso,
    patch_slip_status_payload,
    random_suffix,
    unique_code,
)
from .test_users import (
    TEST_USERS,
    make_boater_headers,
)


# ===========================================================================
# Clock helper — PRD §2.7
# ===========================================================================
def advance_clock_to_iso(marina_id: str, target_iso: str) -> Dict[str, Any]:
    """Advance the marina logical clock to `target_iso` (PRD §2.7)."""
    h = TEST_USERS["dock_master_headers"]
    resp = api_client.clock_advance(
        marina_id, clock_advance_payload(to=target_iso), h,
    )
    return get_success_data(resp)


def run_ops(marina_id: str) -> Dict[str, Any]:
    """Run the ops sweep (PRD §2.7) and return the refreshed Marina."""
    h = TEST_USERS["dock_master_headers"]
    return get_success_data(api_client.ops_run(marina_id, h))


# ===========================================================================
# Tier 0 — Read helpers
# ===========================================================================
def get_marina(marina_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["dock_master_headers"]
    return get_success_data(api_client.get_marina(marina_id, h))


def get_slip(marina_id: str, slip_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["dock_master_headers"]
    return get_success_data(api_client.get_slip(marina_id, slip_id, h))


def get_reservation(
    marina_id: str, reservation_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["dock_master_headers"]
    return get_success_data(
        api_client.get_reservation(marina_id, reservation_id, h)
    )


def get_policy(marina_id: str, policy_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["dock_master_headers"]
    return get_success_data(api_client.get_policy(marina_id, policy_id, h))


def get_tow_contract(
    marina_id: str, contract_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["dock_master_headers"]
    return get_success_data(
        api_client.get_tow_contract(marina_id, contract_id, h)
    )


def get_settlement(
    marina_id: str, reservation_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["dock_master_headers"]
    return get_success_data(
        api_client.get_utility_settlement(marina_id, reservation_id, h)
    )


# ===========================================================================
# Tier 1 — Foundation creators
# ===========================================================================
def create_marina(
    *,
    name: Optional[str] = None,
    base_daily_rate_cents: int = TEST_DEFAULTS["BASE_DAILY_RATE_CENTS"],
    liveaboard_quota: int = TEST_DEFAULTS["LIVEABOARD_QUOTA"],
    timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Marina via DockMaster (PRD §3.1: POST /marinas is
    DockMaster/BillingClerk-only)."""
    h = TEST_USERS["dock_master_headers"]
    payload = create_marina_payload(
        name=name,
        base_daily_rate_cents=base_daily_rate_cents,
        liveaboard_quota=liveaboard_quota,
        timezone=timezone,
    )
    return get_success_data(api_client.create_marina(payload, h))


def create_boater(
    marina_id: str,
    *,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Boater via DockMaster (PRD §3.2)."""
    h = TEST_USERS["dock_master_headers"]
    payload = create_boater_payload(name=name)
    return get_success_data(
        api_client.create_boater(marina_id, payload, h)
    )


def create_vessel(
    marina_id: str,
    boater: Dict[str, Any],
    *,
    name: Optional[str] = None,
    loa_feet: float = TEST_DEFAULTS["VESSEL_LOA_FEET"],
    beam_feet: float = TEST_DEFAULTS["VESSEL_BEAM_FEET"],
    draft_feet: float = TEST_DEFAULTS["VESSEL_DRAFT_FEET"],
    holding_tank_gallons: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a Vessel on behalf of `boater` (PRD §3.2). The caller acts
    as the boater (entity_backed identity, PRD §2.1)."""
    h = make_boater_headers(boater["id"])
    payload = create_vessel_payload(
        name=name,
        loa_feet=loa_feet, beam_feet=beam_feet, draft_feet=draft_feet,
        holding_tank_gallons=holding_tank_gallons,
    )
    return get_success_data(
        api_client.create_vessel(marina_id, boater["id"], payload, h)
    )


def create_slip(
    marina_id: str,
    *,
    code: Optional[str] = None,
    length_feet: float = TEST_DEFAULTS["SLIP_LENGTH_FEET"],
    beam_feet: float = TEST_DEFAULTS["SLIP_BEAM_FEET"],
    depth_feet: float = TEST_DEFAULTS["SLIP_DEPTH_FEET"],
    flat_daily_charge_cents: int = TEST_DEFAULTS[
        "SLIP_FLAT_DAILY_CHARGE_CENTS"
    ],
    liveaboard_allowed: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a Slip via DockMaster (PRD §3.3)."""
    h = TEST_USERS["dock_master_headers"]
    payload = create_slip_payload(
        code=code or unique_code(),
        length_feet=length_feet, beam_feet=beam_feet, depth_feet=depth_feet,
        flat_daily_charge_cents=flat_daily_charge_cents,
        liveaboard_allowed=liveaboard_allowed,
    )
    return get_success_data(
        api_client.create_slip(marina_id, payload, h)
    )


def patch_slip_status(
    marina_id: str,
    slip: Dict[str, Any],
    new_status: str,
) -> Dict[str, Any]:
    """PATCH slip status with If-Match (PRD §3.3 / §2.6)."""
    h = dict(TEST_USERS["dock_master_headers"])
    h["If-Match"] = str(slip["version"])
    resp = api_client.patch_slip_status(
        marina_id, slip["id"],
        patch_slip_status_payload(status=new_status), h,
    )
    return get_success_data(resp)


def create_policy(
    marina_id: str,
    boater: Dict[str, Any],
    *,
    carrier: Optional[str] = None,
    liability_limit_cents: int = TEST_DEFAULTS[
        "INSURANCE_LIABILITY_LIMIT_CENTS"
    ],
    effective_date: Optional[str] = None,
    expiration_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an InsurancePolicy on behalf of a Boater (PRD §3.2). The
    caller acts as the boater."""
    h = make_boater_headers(boater["id"])
    payload = create_policy_payload(
        carrier=carrier,
        liability_limit_cents=liability_limit_cents,
        effective_date=effective_date,
        expiration_date=expiration_date,
    )
    return get_success_data(
        api_client.create_policy(marina_id, boater["id"], payload, h)
    )


def create_tow_contract(
    marina_id: str,
    boater: Dict[str, Any],
    *,
    tier: str = "BASIC",
) -> Dict[str, Any]:
    """Create a TowAssistContract for a Boater (PRD §3.2)."""
    h = make_boater_headers(boater["id"])
    payload = create_tow_contract_payload(tier=tier)
    return get_success_data(
        api_client.create_tow_contract(marina_id, boater["id"], payload, h)
    )


def cancel_policy(
    marina_id: str,
    boater: Dict[str, Any],
    policy_id: str,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    return get_success_data(
        api_client.cancel_policy(marina_id, policy_id, h)
    )


# ===========================================================================
# Tier 2 — Composite Boater + Vessel + Policy bundles
# ===========================================================================
def create_boater_with_vessel(
    marina_id: str,
    *,
    name: Optional[str] = None,
    loa_feet: float = TEST_DEFAULTS["VESSEL_LOA_FEET"],
    beam_feet: float = TEST_DEFAULTS["VESSEL_BEAM_FEET"],
    draft_feet: float = TEST_DEFAULTS["VESSEL_DRAFT_FEET"],
    holding_tank_gallons: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Boater plus one Vessel. Returns (boater, vessel)."""
    boater = create_boater(marina_id, name=name)
    vessel = create_vessel(
        marina_id, boater,
        loa_feet=loa_feet, beam_feet=beam_feet, draft_feet=draft_feet,
        holding_tank_gallons=holding_tank_gallons,
    )
    return boater, vessel


def create_active_policy(
    marina_id: str,
    boater: Dict[str, Any],
    *,
    effective_date: str = "2024-01-01T00:00:00.000Z",
    expiration_date: str = "2025-01-01T00:00:00.000Z",
    liability_limit_cents: int = 1_000_000,
) -> Dict[str, Any]:
    """Create an ACTIVE InsurancePolicy covering the given window."""
    return create_policy(
        marina_id, boater,
        liability_limit_cents=liability_limit_cents,
        effective_date=effective_date,
        expiration_date=expiration_date,
    )


# ===========================================================================
# Tier 3 — Reservation lifecycle helpers
# ===========================================================================
def create_reservation(
    marina_id: str,
    boater: Dict[str, Any],
    vessel: Dict[str, Any],
    slip: Dict[str, Any],
    policy: Dict[str, Any],
    *,
    check_in_date: str,
    check_out_date: str,
    liveaboard: bool = False,
) -> Dict[str, Any]:
    """Create a DRAFT Reservation as the boater (PRD §3.4)."""
    h = make_boater_headers(boater["id"])
    payload = create_reservation_payload(
        boater_id=boater["id"],
        vessel_id=vessel["id"],
        slip_id=slip["id"],
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        insurance_policy_id=policy["id"],
        liveaboard=liveaboard,
    )
    return get_success_data(
        api_client.create_reservation(marina_id, payload, h)
    )


def approve_reservation(
    marina_id: str, reservation_id: str,
) -> Dict[str, Any]:
    """Approve a reservation via DockMaster (PRD §3.4)."""
    h = TEST_USERS["dock_master_headers"]
    return get_success_data(
        api_client.approve_reservation(marina_id, reservation_id, h)
    )


def check_in_reservation(
    marina_id: str, reservation_id: str,
) -> Dict[str, Any]:
    h = TEST_USERS["dock_master_headers"]
    return get_success_data(
        api_client.check_in_reservation(marina_id, reservation_id, h)
    )


def check_out_reservation(
    marina_id: str, reservation_id: str,
) -> Dict[str, Any]:
    h = TEST_USERS["dock_master_headers"]
    return get_success_data(
        api_client.check_out_reservation(marina_id, reservation_id, h)
    )


def cancel_reservation_as_boater(
    marina_id: str,
    boater: Dict[str, Any],
    reservation_id: str,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    return get_success_data(
        api_client.cancel_reservation(marina_id, reservation_id, h)
    )


# ===========================================================================
# Tier 4 — Marina + size-matched slip + boater + vessel + policy bundle
# ===========================================================================
def setup_marina_with_actors(
    *,
    base_daily_rate_cents: int = TEST_DEFAULTS["BASE_DAILY_RATE_CENTS"],
    liveaboard_quota: int = TEST_DEFAULTS["LIVEABOARD_QUOTA"],
    slip_length_feet: float = TEST_DEFAULTS["SLIP_LENGTH_FEET"],
    slip_beam_feet: float = TEST_DEFAULTS["SLIP_BEAM_FEET"],
    slip_depth_feet: float = TEST_DEFAULTS["SLIP_DEPTH_FEET"],
    slip_flat_daily_charge_cents: int = TEST_DEFAULTS[
        "SLIP_FLAT_DAILY_CHARGE_CENTS"
    ],
    slip_liveaboard_allowed: bool = True,
    vessel_loa_feet: float = TEST_DEFAULTS["VESSEL_LOA_FEET"],
    vessel_beam_feet: float = TEST_DEFAULTS["VESSEL_BEAM_FEET"],
    vessel_draft_feet: float = TEST_DEFAULTS["VESSEL_DRAFT_FEET"],
    vessel_holding_tank_gallons: Optional[int] = 40,
    policy_effective_date: str = "2024-01-01T00:00:00.000Z",
    policy_expiration_date: str = "2025-01-01T00:00:00.000Z",
    advance_clock_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Marina + Slip + Boater + Vessel + ACTIVE policy, all
    size-matched and policy-aligned so a Reservation may be created and
    approved. Returns a dict with marina, slip, boater, vessel, policy.

    If `advance_clock_to` is provided, the marina clock is advanced to
    that ISO instant (PRD §2.7) before returning.
    """
    marina = create_marina(
        base_daily_rate_cents=base_daily_rate_cents,
        liveaboard_quota=liveaboard_quota,
    )
    slip = create_slip(
        marina["id"],
        length_feet=slip_length_feet,
        beam_feet=slip_beam_feet,
        depth_feet=slip_depth_feet,
        flat_daily_charge_cents=slip_flat_daily_charge_cents,
        liveaboard_allowed=slip_liveaboard_allowed,
    )
    boater, vessel = create_boater_with_vessel(
        marina["id"],
        loa_feet=vessel_loa_feet,
        beam_feet=vessel_beam_feet,
        draft_feet=vessel_draft_feet,
        holding_tank_gallons=vessel_holding_tank_gallons,
    )
    policy = create_active_policy(
        marina["id"], boater,
        effective_date=policy_effective_date,
        expiration_date=policy_expiration_date,
    )
    if advance_clock_to is not None:
        marina = advance_clock_to_iso(marina["id"], advance_clock_to)
    return {
        "marina": marina,
        "slip": slip,
        "boater": boater,
        "vessel": vessel,
        "policy": policy,
    }


# ===========================================================================
# Tier 5 — Reservation in target state (DRAFT, APPROVED, CHECKED_IN, ...)
# ===========================================================================
def setup_draft_reservation(
    *,
    check_in_date: str = "2024-08-30T00:00:00.000Z",
    check_out_date: str = "2024-09-02T00:00:00.000Z",
    liveaboard: bool = False,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """Build a Marina + Slip + Boater + Vessel + Policy + DRAFT
    Reservation. Returns the scenario dict plus 'reservation'."""
    scenario = setup_marina_with_actors(**scenario_overrides)
    reservation = create_reservation(
        scenario["marina"]["id"],
        scenario["boater"], scenario["vessel"],
        scenario["slip"], scenario["policy"],
        check_in_date=check_in_date, check_out_date=check_out_date,
        liveaboard=liveaboard,
    )
    scenario["reservation"] = reservation
    return scenario


def setup_approved_reservation(
    *,
    check_in_date: str = "2024-08-30T00:00:00.000Z",
    check_out_date: str = "2024-09-02T00:00:00.000Z",
    liveaboard: bool = False,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """Build a scenario through DRAFT → APPROVED."""
    scenario = setup_draft_reservation(
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=liveaboard,
        **scenario_overrides,
    )
    scenario["reservation"] = approve_reservation(
        scenario["marina"]["id"], scenario["reservation"]["id"],
    )
    scenario["marina"] = get_marina(scenario["marina"]["id"])
    return scenario


def setup_checked_in_reservation(
    *,
    check_in_date: str = "2024-08-30T00:00:00.000Z",
    check_out_date: str = "2024-09-02T00:00:00.000Z",
    liveaboard: bool = False,
    clock_after_approve: Optional[str] = None,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """Build a scenario through DRAFT → APPROVED → CHECKED_IN.

    Advances the clock to `check_in_date` (or `clock_after_approve` if
    given) before issuing check-in, since PRD §3.4 requires
    "Marina.current_date is at or after `check_in_date`".
    """
    scenario = setup_approved_reservation(
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=liveaboard,
        **scenario_overrides,
    )
    target_clock = clock_after_approve or check_in_date
    advance_clock_to_iso(scenario["marina"]["id"], target_clock)
    scenario["reservation"] = check_in_reservation(
        scenario["marina"]["id"], scenario["reservation"]["id"],
    )
    scenario["marina"] = get_marina(scenario["marina"]["id"])
    return scenario


def setup_checked_out_reservation(
    *,
    check_in_date: str = "2024-08-30T00:00:00.000Z",
    check_out_date: str = "2024-09-02T00:00:00.000Z",
    liveaboard: bool = False,
    clock_at_checkout: Optional[str] = None,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """Build a scenario all the way to CHECKED_OUT.

    Advances the clock to `clock_at_checkout` (default: check_out_date)
    before issuing check-out, since PRD §3.4 requires the marina clock
    be at or after `check_in_date` and PRD §3.6 defines the settlement
    window as [check_in_date, Marina.current_date).
    """
    scenario = setup_checked_in_reservation(
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=liveaboard,
        **scenario_overrides,
    )
    final_clock = clock_at_checkout or check_out_date
    advance_clock_to_iso(scenario["marina"]["id"], final_clock)
    scenario["reservation"] = check_out_reservation(
        scenario["marina"]["id"], scenario["reservation"]["id"],
    )
    scenario["marina"] = get_marina(scenario["marina"]["id"])
    return scenario


# ===========================================================================
# Tier 6 — Pump-out lifecycle
# ===========================================================================
def schedule_pump_out(
    marina_id: str,
    boater: Dict[str, Any],
    reservation_id: str,
    *,
    scheduled_start: str,
    scheduled_end: str,
) -> Dict[str, Any]:
    """Schedule a pump-out as the boater (PRD §3.8)."""
    h = make_boater_headers(boater["id"])
    payload = create_pump_out_payload(
        reservation_id=reservation_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    return get_success_data(
        api_client.create_pump_out_job(marina_id, payload, h)
    )


def complete_pump_out(
    marina_id: str,
    job_id: str,
    *,
    tank_gallons_drained: int,
) -> Dict[str, Any]:
    h = TEST_USERS["dock_master_headers"]
    payload = complete_pump_out_payload(
        tank_gallons_drained=tank_gallons_drained,
    )
    return get_success_data(
        api_client.complete_pump_out_job(marina_id, job_id, payload, h)
    )


def cancel_pump_out_as_boater(
    marina_id: str,
    boater: Dict[str, Any],
    job_id: str,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    return get_success_data(
        api_client.cancel_pump_out_job(marina_id, job_id, h)
    )


# ===========================================================================
# Tier 7 — Utility readings
# ===========================================================================
def add_utility_reading(
    marina_id: str,
    reservation_id: str,
    *,
    read_at: str,
    kwh_delta: int,
    water_gallons_delta: int,
) -> Dict[str, Any]:
    """Append a utility reading via DockMaster (PRD §3.6)."""
    h = TEST_USERS["dock_master_headers"]
    payload = create_utility_reading_payload(
        read_at=read_at, kwh_delta=kwh_delta,
        water_gallons_delta=water_gallons_delta,
    )
    return get_success_data(
        api_client.create_utility_reading(
            marina_id, reservation_id, payload, h,
        )
    )


# ===========================================================================
# Tier 8 — Slip Transfer lifecycle
# ===========================================================================
def request_slip_transfer(
    marina_id: str,
    boater: Dict[str, Any],
    reservation_id: str,
    desired_slip_id: str,
) -> Dict[str, Any]:
    """Boater submits a SlipTransferRequest (PRD §3.7)."""
    h = make_boater_headers(boater["id"])
    payload = create_transfer_request_payload(
        reservation_id=reservation_id,
        desired_slip_id=desired_slip_id,
    )
    return get_success_data(
        api_client.create_transfer_request(marina_id, payload, h)
    )


def offer_slip_transfer(marina_id: str, request_id: str) -> Dict[str, Any]:
    h = TEST_USERS["dock_master_headers"]
    return get_success_data(
        api_client.offer_transfer_request(marina_id, request_id, h)
    )


def accept_slip_transfer(
    marina_id: str,
    boater: Dict[str, Any],
    request_id: str,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    return get_success_data(
        api_client.accept_transfer_request(marina_id, request_id, h)
    )


def decline_slip_transfer(
    marina_id: str,
    boater: Dict[str, Any],
    request_id: str,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    return get_success_data(
        api_client.decline_transfer_request(marina_id, request_id, h)
    )


def requeue_slip_transfer(
    marina_id: str,
    boater: Dict[str, Any],
    request_id: str,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    return get_success_data(
        api_client.requeue_transfer_request(marina_id, request_id, h)
    )


# ===========================================================================
# Tier 9 — Waitlist
# ===========================================================================
def add_waitlist_entry(
    marina_id: str,
    boater: Dict[str, Any],
    vessel: Dict[str, Any],
    *,
    requested_check_in: str,
    requested_check_out: str,
    liveaboard: bool = False,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    payload = create_waitlist_payload(
        boater_id=boater["id"],
        vessel_id=vessel["id"],
        requested_check_in=requested_check_in,
        requested_check_out=requested_check_out,
        liveaboard=liveaboard,
    )
    return get_success_data(
        api_client.create_waitlist_entry(marina_id, payload, h)
    )


def cancel_waitlist_entry(
    marina_id: str,
    boater: Dict[str, Any],
    waitlist_id: str,
) -> Dict[str, Any]:
    h = make_boater_headers(boater["id"])
    return get_success_data(
        api_client.cancel_waitlist_entry(marina_id, waitlist_id, h)
    )


def get_waitlist_entry(
    marina_id: str,
    waitlist_id: str,
    boater: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    h = (make_boater_headers(boater["id"])
         if boater else TEST_USERS["dock_master_headers"])
    return get_success_data(
        api_client.get_waitlist_entry(marina_id, waitlist_id, h)
    )


# ===========================================================================
# Tier 10 — Tow events
# ===========================================================================
def record_tow_event(
    marina_id: str,
    contract_id: str,
    *,
    occurred_at: str,
    from_position: str = "Open water",
    to_slip_id: str,
) -> Dict[str, Any]:
    """Record a tow event via DockMaster (PRD §3.8)."""
    h = TEST_USERS["dock_master_headers"]
    payload = create_tow_event_payload(
        occurred_at=occurred_at,
        from_position=from_position,
        to_slip_id=to_slip_id,
    )
    return get_success_data(
        api_client.create_tow_event(marina_id, contract_id, payload, h)
    )


# ===========================================================================
# Tier 11 — Difficulty-design composite scenarios
# ===========================================================================
def setup_two_slip_marina_with_active_reservation(
    *,
    base_daily_rate_cents: int = 500,
    liveaboard_quota: int = 10,
    check_in_date: str = "2024-05-01T00:00:00.000Z",
    check_out_date: str = "2024-05-10T00:00:00.000Z",
    s1_code: str = "A-01",
    s2_code: str = "A-02",
) -> Dict[str, Any]:
    """Two-slip marina with an APPROVED reservation on S1 and an empty
    S2; suitable for the slip-transfer-cyclic-revision-loop recipe
    (difficulty rule 3 / instance 1).

    Returns dict with marina, s1, s2, boater, vessel, policy, reservation.
    """
    marina = create_marina(
        base_daily_rate_cents=base_daily_rate_cents,
        liveaboard_quota=liveaboard_quota,
    )
    s1 = create_slip(marina["id"], code=s1_code,
                     length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
                     flat_daily_charge_cents=2000)
    s2 = create_slip(marina["id"], code=s2_code,
                     length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
                     flat_daily_charge_cents=2500)
    boater, vessel = create_boater_with_vessel(
        marina["id"],
        loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    policy = create_active_policy(
        marina["id"], boater,
        effective_date="2024-01-01T00:00:00.000Z",
        expiration_date="2025-01-01T00:00:00.000Z",
    )
    reservation = create_reservation(
        marina["id"], boater, vessel, s1, policy,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=False,
    )
    reservation = approve_reservation(marina["id"], reservation["id"])
    return {
        "marina": get_marina(marina["id"]),
        "s1": s1, "s2": s2,
        "boater": boater, "vessel": vessel,
        "policy": policy, "reservation": reservation,
    }


def setup_dual_liveaboard_approved_reservations(
    *,
    liveaboard_quota: int = 3,
) -> Dict[str, Any]:
    """Two distinct liveaboard reservations APPROVED on two slips for
    non-overlapping (but adjacent) date ranges — recipe shape for
    `reservation_branching_with_expiry_branch` (difficulty rule 3 /
    instance 2). Returns dict with both reservation contexts."""
    marina = create_marina(
        base_daily_rate_cents=500,
        liveaboard_quota=liveaboard_quota,
    )

    # First reservation R_A on slip A — non-overlapping date range
    slip_a = create_slip(
        marina["id"], code="A-01",
        length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
        flat_daily_charge_cents=2000,
        liveaboard_allowed=True,
    )
    boater_a, vessel_a = create_boater_with_vessel(
        marina["id"],
        loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    policy_a = create_active_policy(
        marina["id"], boater_a,
        effective_date="2024-01-01T00:00:00.000Z",
        expiration_date="2025-01-01T00:00:00.000Z",
    )
    res_a = create_reservation(
        marina["id"], boater_a, vessel_a, slip_a, policy_a,
        check_in_date="2024-05-01T00:00:00.000Z",
        check_out_date="2024-05-05T00:00:00.000Z",
        liveaboard=True,
    )
    res_a = approve_reservation(marina["id"], res_a["id"])

    # Second reservation R_B on slip B
    slip_b = create_slip(
        marina["id"], code="B-01",
        length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
        flat_daily_charge_cents=2000,
        liveaboard_allowed=True,
    )
    boater_b, vessel_b = create_boater_with_vessel(
        marina["id"],
        loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    policy_b = create_active_policy(
        marina["id"], boater_b,
        effective_date="2024-01-01T00:00:00.000Z",
        expiration_date="2025-01-01T00:00:00.000Z",
    )
    res_b = create_reservation(
        marina["id"], boater_b, vessel_b, slip_b, policy_b,
        check_in_date="2024-06-01T00:00:00.000Z",
        check_out_date="2024-06-05T00:00:00.000Z",
        liveaboard=True,
    )
    res_b = approve_reservation(marina["id"], res_b["id"])
    return {
        "marina": get_marina(marina["id"]),
        "slip_a": slip_a, "slip_b": slip_b,
        "boater_a": boater_a, "boater_b": boater_b,
        "vessel_a": vessel_a, "vessel_b": vessel_b,
        "policy_a": policy_a, "policy_b": policy_b,
        "res_a": res_a, "res_b": res_b,
    }


def setup_liveaboard_pump_out_chain(
    *,
    check_in_date: str = "2024-02-01T00:00:00.000Z",
    check_out_date: str = "2024-02-02T00:00:00.000Z",
    pump_out_start: str = "2024-02-01T19:00:00.000Z",
    pump_out_end: str = "2024-02-01T19:30:00.000Z",
    kwh_reading_at: str = "2024-02-01T18:00:00.000Z",
    kwh_delta: int = 100,
) -> Dict[str, Any]:
    """Build the depth-3 cascade scenario used by
    `pump_out_complete_to_utility_reading_to_settlement` (difficulty
    rule 4 / instance 1). Liveaboard reservation CHECKED_IN, one kwh
    reading, one SCHEDULED pump-out — ready for tests to drive the
    cascade.

    Returns dict with marina, slip, boater, vessel, policy, reservation,
    job (SCHEDULED), and the kwh reading.
    """
    # Anchor the clock to before check-in so the same call sequence
    # works regardless of the initial marina clock.
    scenario = setup_checked_in_reservation(
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=True,
        slip_liveaboard_allowed=True,
        vessel_holding_tank_gallons=60,
        policy_effective_date="2024-01-01T00:00:00.000Z",
        policy_expiration_date="2025-01-01T00:00:00.000Z",
        clock_after_approve="2024-02-01T10:00:00.000Z",
    )
    marina = scenario["marina"]
    boater = scenario["boater"]
    reservation = scenario["reservation"]

    # KWH reading at 18:00
    advance_clock_to_iso(marina["id"], kwh_reading_at)
    reading = add_utility_reading(
        marina["id"], reservation["id"],
        read_at=kwh_reading_at,
        kwh_delta=kwh_delta,
        water_gallons_delta=0,
    )

    # Pump-out scheduled at 19:00-19:30
    job = schedule_pump_out(
        marina["id"], boater, reservation["id"],
        scheduled_start=pump_out_start,
        scheduled_end=pump_out_end,
    )
    scenario["job"] = job
    scenario["reading"] = reading
    scenario["marina"] = get_marina(marina["id"])
    return scenario


def setup_policy_expiry_cascade_scenario(
    *,
    policy_expiration_date: str = "2024-06-01T00:00:00.000Z",
    reservation_check_in: str = "2024-07-01T00:00:00.000Z",
    reservation_check_out: str = "2024-07-05T00:00:00.000Z",
) -> Dict[str, Any]:
    """Build the depth-2 cascade scenario used by
    `hub_clock_advance_to_policy_expiry_to_approval_block` (difficulty
    rule 4 / instance 2). Returns marina, slip, boater, vessel, policy,
    reservation (DRAFT)."""
    scenario = setup_draft_reservation(
        check_in_date=reservation_check_in,
        check_out_date=reservation_check_out,
        liveaboard=False,
        policy_effective_date="2024-01-01T00:00:00.000Z",
        policy_expiration_date=policy_expiration_date,
    )
    return scenario


# ===========================================================================
# Tier 12 — Boundary precision helpers
# ===========================================================================
def setup_loa_boundary_scenario() -> Dict[str, Any]:
    """Set up two boaters with vessels at LOA=40.0 (exact) and LOA=40.1
    (over) and DRAFT reservations against a size-40.0 slip. For the
    `loa_exact_match_boundary` difficulty recipe (rule 6 / instance 1).

    Returns dict with marina, slip, two boaters/vessels, two policies,
    and two DRAFT reservations (R_exact, R_over).
    """
    marina = create_marina(base_daily_rate_cents=500, liveaboard_quota=5)
    slip = create_slip(
        marina["id"], code="A-01",
        length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
        flat_daily_charge_cents=2000,
        liveaboard_allowed=False,
    )

    # Exact-fit boater + vessel (LOA=40.0)
    boater_exact = create_boater(marina["id"], name="Exact-Fit Boater")
    vessel_exact = create_vessel(
        marina["id"], boater_exact,
        loa_feet=40.0, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    policy_exact = create_active_policy(
        marina["id"], boater_exact,
        effective_date="2024-01-01T00:00:00.000Z",
        expiration_date="2025-01-01T00:00:00.000Z",
    )
    res_exact = create_reservation(
        marina["id"], boater_exact, vessel_exact, slip, policy_exact,
        check_in_date="2024-05-01T00:00:00.000Z",
        check_out_date="2024-05-03T00:00:00.000Z",
        liveaboard=False,
    )

    # Over-fit boater + vessel (LOA=40.1)
    boater_over = create_boater(marina["id"], name="Over-LOA Boater")
    vessel_over = create_vessel(
        marina["id"], boater_over,
        loa_feet=40.1, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    policy_over = create_active_policy(
        marina["id"], boater_over,
        effective_date="2024-01-01T00:00:00.000Z",
        expiration_date="2025-01-01T00:00:00.000Z",
    )
    res_over = create_reservation(
        marina["id"], boater_over, vessel_over, slip, policy_over,
        check_in_date="2024-06-01T00:00:00.000Z",  # different month, no overlap
        check_out_date="2024-06-03T00:00:00.000Z",
        liveaboard=False,
    )

    return {
        "marina": marina,
        "slip": slip,
        "boater_exact": boater_exact, "vessel_exact": vessel_exact,
        "policy_exact": policy_exact, "res_exact": res_exact,
        "boater_over": boater_over, "vessel_over": vessel_over,
        "policy_over": policy_over, "res_over": res_over,
    }


def setup_marina_with_too_small_slip_and_waitlist(
    *,
    requested_check_in: str = "2024-05-01T00:00:00.000Z",
    requested_check_out: str = "2024-05-05T00:00:00.000Z",
) -> Dict[str, Any]:
    """Marina with one too-small slip + waitlist entry whose vessel is
    too large to fit. For `empty_candidate_set_waitlist_no_promotion`
    (difficulty rule 6 / instance 2). Returns marina, slip_small,
    boater, vessel, waitlist entry.
    """
    marina = create_marina(base_daily_rate_cents=500, liveaboard_quota=5)
    slip_small = create_slip(
        marina["id"], code="A-01",
        length_feet=20.0, beam_feet=14.0, depth_feet=6.0,
        flat_daily_charge_cents=2000,
    )
    boater, vessel = create_boater_with_vessel(
        marina["id"],
        loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    entry = add_waitlist_entry(
        marina["id"], boater, vessel,
        requested_check_in=requested_check_in,
        requested_check_out=requested_check_out,
        liveaboard=False,
    )
    return {
        "marina": marina,
        "slip_small": slip_small,
        "boater": boater, "vessel": vessel,
        "entry": entry,
    }


def setup_quota_full_marina_with_overlap_attempt(
    *,
    quota: int = 1,
) -> Dict[str, Any]:
    """Marina with liveaboard_quota=1, one approved liveaboard
    reservation on slip S1 for 2024-03-01..2024-03-05, and a second
    DRAFT liveaboard reservation on the SAME slip overlapping. For
    `liveaboard_quota_fiscal_vs_slip_occupied_temporal` (difficulty
    rule 5 / instance 2).
    """
    marina = create_marina(
        base_daily_rate_cents=500, liveaboard_quota=quota,
    )
    slip = create_slip(
        marina["id"], code="A-01",
        length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
        flat_daily_charge_cents=2000,
        liveaboard_allowed=True,
    )

    # Existing liveaboard reservation (APPROVED) — fills the quota.
    boater_a, vessel_a = create_boater_with_vessel(
        marina["id"],
        loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    policy_a = create_active_policy(
        marina["id"], boater_a,
        effective_date="2024-01-01T00:00:00.000Z",
        expiration_date="2025-01-01T00:00:00.000Z",
    )
    res_existing = create_reservation(
        marina["id"], boater_a, vessel_a, slip, policy_a,
        check_in_date="2024-03-01T00:00:00.000Z",
        check_out_date="2024-03-05T00:00:00.000Z",
        liveaboard=True,
    )
    res_existing = approve_reservation(marina["id"], res_existing["id"])

    # New DRAFT liveaboard reservation on the same slip, overlapping.
    boater_b, vessel_b = create_boater_with_vessel(
        marina["id"],
        loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
        holding_tank_gallons=40,
    )
    policy_b = create_active_policy(
        marina["id"], boater_b,
        effective_date="2024-01-01T00:00:00.000Z",
        expiration_date="2025-01-01T00:00:00.000Z",
    )
    res_new = create_reservation(
        marina["id"], boater_b, vessel_b, slip, policy_b,
        check_in_date="2024-03-02T00:00:00.000Z",
        check_out_date="2024-03-06T00:00:00.000Z",
        liveaboard=True,
    )

    return {
        "marina": get_marina(marina["id"]),
        "slip": slip,
        "boater_a": boater_a, "vessel_a": vessel_a, "policy_a": policy_a,
        "res_existing": res_existing,
        "boater_b": boater_b, "vessel_b": vessel_b, "policy_b": policy_b,
        "res_new": res_new,
    }


def setup_three_liveaboard_drafts(
    *,
    quota: int = 3,
) -> Dict[str, Any]:
    """For `liveaboard_active_count_conservation` (difficulty rule 9 /
    instance 1). Three DRAFT liveaboard reservations on distinct slips
    with non-overlapping dates."""
    marina = create_marina(
        base_daily_rate_cents=500, liveaboard_quota=quota,
    )

    def _mk(slot_code: str, ci_iso: str, co_iso: str) -> Dict[str, Any]:
        slip = create_slip(
            marina["id"], code=slot_code,
            length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
            flat_daily_charge_cents=2000,
            liveaboard_allowed=True,
        )
        boater, vessel = create_boater_with_vessel(
            marina["id"],
            loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
            holding_tank_gallons=40,
        )
        policy = create_active_policy(
            marina["id"], boater,
            effective_date="2024-01-01T00:00:00.000Z",
            expiration_date="2025-01-01T00:00:00.000Z",
        )
        reservation = create_reservation(
            marina["id"], boater, vessel, slip, policy,
            check_in_date=ci_iso, check_out_date=co_iso,
            liveaboard=True,
        )
        return {
            "slip": slip, "boater": boater, "vessel": vessel,
            "policy": policy, "reservation": reservation,
        }

    r1 = _mk("A-01", "2024-05-01T00:00:00.000Z",
             "2024-05-05T00:00:00.000Z")
    r2 = _mk("A-02", "2024-06-01T00:00:00.000Z",
             "2024-06-05T00:00:00.000Z")
    r3 = _mk("A-03", "2024-07-01T00:00:00.000Z",
             "2024-07-05T00:00:00.000Z")

    return {
        "marina": get_marina(marina["id"]),
        "r1": r1, "r2": r2, "r3": r3,
    }


def setup_basic_tow_contract_with_destinations(
    *,
    num_destinations: int = 3,
) -> Dict[str, Any]:
    """For `tow_assist_coverage_pool_conservation` (difficulty rule 9 /
    instance 2) and `tow_event_charge_vs_utility_settlement_billing`
    (difficulty rule 1 / instance 2). Returns marina, boater, BASIC
    contract, and N AVAILABLE destination slips."""
    marina = create_marina(
        base_daily_rate_cents=500, liveaboard_quota=5,
    )
    boater = create_boater(marina["id"])
    contract = create_tow_contract(marina["id"], boater, tier="BASIC")
    dests: List[Dict[str, Any]] = []
    for i in range(num_destinations):
        dests.append(
            create_slip(marina["id"], code=f"D-{i+1:02d}",
                        length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
                        flat_daily_charge_cents=2000)
        )
    return {
        "marina": marina, "boater": boater,
        "contract": contract, "destinations": dests,
    }


# ===========================================================================
# Tier 13 — Reservation→Insurance / Reservation→PumpOut cross-entity
# ===========================================================================
def setup_reservation_with_cancelled_policy(
    *,
    check_in_date: str = "2024-02-01T00:00:00.000Z",
    check_out_date: str = "2024-02-05T00:00:00.000Z",
) -> Dict[str, Any]:
    """For `reservation_approve_depends_on_insurance_policy_status`
    (difficulty rule 7 / instance 1). DRAFT reservation referencing a
    policy that is then explicitly CANCELLED.
    """
    scenario = setup_draft_reservation(
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=False,
        policy_effective_date="2024-01-01T00:00:00.000Z",
        policy_expiration_date="2025-03-01T00:00:00.000Z",
    )
    # Cancel the policy as the boater (no active referencing
    # reservation yet — DRAFT does not block per PRD §3.4).
    cancel_policy(
        scenario["marina"]["id"], scenario["boater"],
        scenario["policy"]["id"],
    )
    # Refresh policy state for the caller.
    scenario["policy"] = get_policy(
        scenario["marina"]["id"], scenario["policy"]["id"],
    )
    return scenario


def setup_checked_in_liveaboard_with_scheduled_pump_out(
    *,
    check_in_date: str = "2024-02-01T00:00:00.000Z",
    check_out_date: str = "2024-02-03T00:00:00.000Z",
    pump_out_start: str = "2024-02-01T15:00:00.000Z",
    pump_out_end: str = "2024-02-01T15:30:00.000Z",
) -> Dict[str, Any]:
    """For `reservation_checkout_depends_on_pumpoutjob_status`
    (difficulty rule 7 / instance 2). CHECKED_IN liveaboard reservation
    with a SCHEDULED pump-out blocking check-out."""
    scenario = setup_checked_in_reservation(
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=True,
        slip_liveaboard_allowed=True,
        vessel_holding_tank_gallons=60,
        policy_effective_date="2024-01-01T00:00:00.000Z",
        policy_expiration_date="2025-01-01T00:00:00.000Z",
        clock_after_approve="2024-02-01T10:00:00.000Z",
    )
    job = schedule_pump_out(
        scenario["marina"]["id"], scenario["boater"],
        scenario["reservation"]["id"],
        scheduled_start=pump_out_start, scheduled_end=pump_out_end,
    )
    scenario["job"] = job
    return scenario


# ===========================================================================
# Tier 14 — Overlap geometry helpers
# ===========================================================================
def setup_existing_approved_reservation_for_overlap(
    *,
    check_in_date: str = "2024-05-01T00:00:00.000Z",
    check_out_date: str = "2024-05-05T00:00:00.000Z",
) -> Dict[str, Any]:
    """One APPROVED reservation R_A on slip S1 — recipe shape for the
    half-open overlap test (`reservation_overlap_half_open_intervals`,
    difficulty rule 8 / instance 1)."""
    return setup_approved_reservation(
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        liveaboard=False,
        slip_liveaboard_allowed=False,
    )


__all__ = [
    # Clock + ops
    "advance_clock_to_iso", "run_ops",
    # Read helpers
    "get_marina", "get_slip", "get_reservation",
    "get_policy", "get_tow_contract", "get_settlement",
    "get_waitlist_entry",
    # Foundation creators
    "create_marina", "create_boater", "create_vessel", "create_slip",
    "patch_slip_status",
    "create_policy", "create_tow_contract", "cancel_policy",
    # Composite Boater+Vessel/Policy bundles
    "create_boater_with_vessel", "create_active_policy",
    # Reservation lifecycle
    "create_reservation",
    "approve_reservation", "check_in_reservation",
    "check_out_reservation",
    "cancel_reservation_as_boater",
    # Marina+actors bundles
    "setup_marina_with_actors",
    # Reservation in target state
    "setup_draft_reservation", "setup_approved_reservation",
    "setup_checked_in_reservation", "setup_checked_out_reservation",
    # Pump-out / utility readings
    "schedule_pump_out", "complete_pump_out",
    "cancel_pump_out_as_boater",
    "add_utility_reading",
    # Transfer
    "request_slip_transfer", "offer_slip_transfer",
    "accept_slip_transfer", "decline_slip_transfer",
    "requeue_slip_transfer",
    # Waitlist
    "add_waitlist_entry", "cancel_waitlist_entry",
    # Tow events
    "record_tow_event",
    # Difficulty-design composite scenarios
    "setup_two_slip_marina_with_active_reservation",
    "setup_dual_liveaboard_approved_reservations",
    "setup_liveaboard_pump_out_chain",
    "setup_policy_expiry_cascade_scenario",
    "setup_loa_boundary_scenario",
    "setup_marina_with_too_small_slip_and_waitlist",
    "setup_quota_full_marina_with_overlap_attempt",
    "setup_three_liveaboard_drafts",
    "setup_basic_tow_contract_with_destinations",
    "setup_reservation_with_cancelled_policy",
    "setup_checked_in_liveaboard_with_scheduled_pump_out",
    "setup_existing_approved_reservation_for_overlap",
]
