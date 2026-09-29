"""Composite setup builders.

The API server is restarted and the database wiped before every individual
test, so nothing here may assume pre-existing rows: each builder constructs its
whole precondition chain through documented endpoints only.

The layers, from thinnest to thickest:

* single-resource wrappers (`build_health_plan` … `build_courier`),
* the reference layer (`build_network`) that nearly every scenario needs,
* state-progression builders that walk one delivery down the custody dimension
  (`build_queued_delivery`, `advance_to_assigned`, `advance_to_out_for_delivery`),
* accumulation builders that drive a delivery to a threshold
  (`exhaust_attempt_ladder`, `force_cold_breach`),
* terminal-state shortcuts (`deliver_and_settle`, `open_and_review_case`),
* read helpers that re-fetch a row so a test can assert on fresh state.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_DISPATCH_DAY3,
    CLOCK_DOORSTEP_DAY3,
    CLOCK_INTAKE_DAY3,
    OPS_USER_A,
    utc_ts,
)
from .test_users import (
    make_courier_headers,
    make_ops_headers,
    make_patient_headers,
    make_pharmacy_headers,
    make_plan_admin_headers,
)

Entity = Dict[str, Any]
Headers = Dict[str, str]

COLD_CLASSES = ("COLD_CHAIN", "COLD_CHAIN_CONTROLLED")
DEFAULT_SEAL_ID = "SEAL-4471"


# ─── Containers ───────────────────────────────────────


@dataclass
class Network:
    """The reference layer: payer, grant pool, dispensing site, zone, recipient."""

    plan: Optional[Entity]
    grant: Optional[Entity]
    pharmacy: Entity
    zone: Entity
    patient: Entity

    @property
    def pharmacy_headers(self) -> Headers:
        return make_pharmacy_headers(self.pharmacy["id"])

    @property
    def patient_headers(self) -> Headers:
        return make_patient_headers(self.patient["id"])

    @property
    def plan_admin_headers(self) -> Headers:
        assert self.plan is not None, "this network has no health plan"
        return make_plan_admin_headers(self.plan["id"])


@dataclass
class Scenario:
    """One delivery and everything standing behind it."""

    net: Network
    order: Entity
    window: Entity
    delivery: Entity
    courier: Optional[Entity] = None
    assignment: Optional[Entity] = None
    case: Optional[Entity] = None
    attempts: List[Entity] = field(default_factory=list)

    @property
    def pharmacy_headers(self) -> Headers:
        return self.net.pharmacy_headers

    @property
    def patient_headers(self) -> Headers:
        return self.net.patient_headers

    @property
    def courier_headers(self) -> Headers:
        assert self.courier is not None, "this scenario has no courier yet"
        return make_courier_headers(self.courier["id"])


# ─── Clock ────────────────────────────────────────────


def set_clock(api: ApiClient, instant: str, headers: Optional[Headers] = None) -> Entity:
    """Move the logical clock that every temporal rule reads."""
    return get_success_data(api.set_clock(instant, headers=headers or make_ops_headers()))


# ─── Single-resource wrappers ─────────────────────────


def build_health_plan(api: ApiClient, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_health_plan(f.health_plan_payload(**overrides), headers=make_ops_headers())
    )


def build_plan_grant(api: ApiClient, health_plan_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_plan_grant(
            f.plan_grant_payload(health_plan_id, **overrides), headers=make_ops_headers()
        )
    )


def build_pharmacy(api: ApiClient, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_pharmacy(f.pharmacy_payload(**overrides), headers=make_ops_headers())
    )


def build_zone(api: ApiClient, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_delivery_zone(f.delivery_zone_payload(**overrides), headers=make_ops_headers())
    )


def build_patient(api: ApiClient, pharmacy_id: str, **overrides: Any) -> Entity:
    """Recipients are registered by the dispensing site that will serve them."""
    return get_success_data(
        api.create_patient(f.patient_payload(**overrides), headers=make_pharmacy_headers(pharmacy_id))
    )


def build_window(api: ApiClient, zone_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_delivery_window(
            f.delivery_window_payload(zone_id, **overrides), headers=make_ops_headers()
        )
    )


def build_courier(api: ApiClient, *, available: bool = True, **overrides: Any) -> Entity:
    """Onboard a courier; couriers start OFFLINE, so put them on shift by default."""
    courier = get_success_data(
        api.create_courier(f.courier_payload(**overrides), headers=make_ops_headers())
    )
    if available:
        courier = get_success_data(
            api.set_courier_status(
                courier["id"],
                f.courier_status_payload("AVAILABLE"),
                headers=make_courier_headers(courier["id"]),
            )
        )
    return courier


# ─── The reference layer ──────────────────────────────


def build_network(
    api: ApiClient,
    *,
    clock: Optional[str] = CLOCK_INTAKE_DAY3,
    plan: Optional[Dict[str, Any]] = None,
    grant: Optional[Dict[str, Any]] = None,
    pharmacy: Optional[Dict[str, Any]] = None,
    zone: Optional[Dict[str, Any]] = None,
    patient: Optional[Dict[str, Any]] = None,
    with_plan: bool = True,
    with_grant: bool = True,
) -> Network:
    """Stand up payer, grant pool, dispensing site, zone and recipient.

    Pass ``with_plan=False`` for a self-pay bag, which selects no pool at all.
    """
    if clock is not None:
        set_clock(api, clock)
    plan_row = build_health_plan(api, **(plan or {})) if with_plan else None
    grant_row = None
    if plan_row is not None and with_grant:
        grant_row = build_plan_grant(api, plan_row["id"], **(grant or {}))
    pharmacy_row = build_pharmacy(api, **(pharmacy or {}))
    zone_row = build_zone(api, **(zone or {}))
    patient_row = build_patient(api, pharmacy_row["id"], **(patient or {}))
    return Network(
        plan=plan_row,
        grant=grant_row,
        pharmacy=pharmacy_row,
        zone=zone_row,
        patient=patient_row,
    )


# ─── Orders ───────────────────────────────────────────


def build_order(api: ApiClient, net: Network, **overrides: Any) -> Entity:
    """Take a filled bundle into the system; it lands at INTAKE."""
    overrides.setdefault("health_plan_id", net.plan["id"] if net.plan else None)
    return get_success_data(
        api.create_pharmacy_order(
            f.pharmacy_order_payload(net.pharmacy["id"], net.patient["id"], **overrides),
            headers=net.pharmacy_headers,
        )
    )


def build_ready_order(api: ApiClient, net: Network, **overrides: Any) -> Entity:
    """An order released for scheduling, with its two proof fields recomputed."""
    order = build_order(api, net, **overrides)
    return get_success_data(api.mark_order_ready(order["id"], headers=net.pharmacy_headers))


# ─── Reservation ──────────────────────────────────────


def reserve_delivery(
    api: ApiClient,
    net: Network,
    order_id: str,
    window_id: str,
    expected_window_version: Optional[int] = None,
    **overrides: Any,
) -> Entity:
    """Reserve a slot, reading the window's current version when none is given.

    A second reservation against the same window must supply the *new* version,
    which is why the version is re-read rather than remembered.
    """
    if expected_window_version is None:
        expected_window_version = read_window(api, window_id)["version"]
    return get_success_data(
        api.create_delivery(
            f.delivery_payload(order_id, window_id, expected_window_version, **overrides),
            headers=net.pharmacy_headers,
        )
    )


def build_queued_delivery(
    api: ApiClient,
    *,
    net: Optional[Network] = None,
    network_kwargs: Optional[Dict[str, Any]] = None,
    order_kwargs: Optional[Dict[str, Any]] = None,
    window_kwargs: Optional[Dict[str, Any]] = None,
    window: Optional[Entity] = None,
    order: Optional[Entity] = None,
) -> Scenario:
    """Reference layer, a READY order, a capacity window, and a QUEUED delivery."""
    net = net or build_network(api, **(network_kwargs or {}))
    order = order or build_ready_order(api, net, **(order_kwargs or {}))
    window = window or build_window(api, net.zone["id"], **(window_kwargs or {}))
    delivery = reserve_delivery(api, net, order["id"], window["id"])
    return Scenario(net=net, order=order, window=window, delivery=delivery)


# ─── Custody progression ──────────────────────────────


def advance_to_assigned(
    api: ApiClient,
    scn: Scenario,
    *,
    courier: Optional[Entity] = None,
    courier_kwargs: Optional[Dict[str, Any]] = None,
    explicit: bool = True,
    dispatch_clock: Optional[str] = CLOCK_DISPATCH_DAY3,
) -> Scenario:
    """Offer the delivery to a courier and have that courier accept it."""
    if courier is None:
        courier = scn.courier or build_courier(api, **(courier_kwargs or {}))
    if dispatch_clock is not None:
        set_clock(api, dispatch_clock)
    payload = f.dispatch_payload(courier["id"] if explicit else None)
    assignment = get_success_data(
        api.dispatch_delivery(scn.delivery["id"], headers=make_ops_headers(), payload=payload)
    )
    assignment = get_success_data(
        api.accept_assignment(assignment["id"], headers=make_courier_headers(courier["id"]))
    )
    scn.courier = courier
    scn.assignment = assignment
    scn.delivery = read_delivery(api, scn.delivery["id"])
    return scn


def advance_to_picked_up(
    api: ApiClient,
    scn: Scenario,
    *,
    cold_chain_seal_id: Optional[str] = DEFAULT_SEAL_ID,
) -> Scenario:
    """Take custody at the counter, sealing the bag when the class is cold."""
    needs_seal = scn.delivery["handling_class"] in COLD_CLASSES
    seal = cold_chain_seal_id if needs_seal else None
    scn.delivery = get_success_data(
        api.pickup_delivery(
            scn.delivery["id"], headers=scn.courier_headers, payload=f.pickup_payload(seal)
        )
    )
    return scn


def advance_to_out_for_delivery(
    api: ApiClient,
    scn: Scenario,
    *,
    depart_clock: Optional[str] = None,
) -> Scenario:
    """Leave the counter for the patient's address."""
    if depart_clock is not None:
        set_clock(api, depart_clock)
    scn.delivery = get_success_data(
        api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers)
    )
    return scn


def build_out_for_delivery(
    api: ApiClient,
    *,
    net: Optional[Network] = None,
    network_kwargs: Optional[Dict[str, Any]] = None,
    order_kwargs: Optional[Dict[str, Any]] = None,
    window_kwargs: Optional[Dict[str, Any]] = None,
    courier_kwargs: Optional[Dict[str, Any]] = None,
    dispatch_clock: Optional[str] = CLOCK_DISPATCH_DAY3,
    depart_clock: Optional[str] = CLOCK_DOORSTEP_DAY3,
    cold_chain_seal_id: Optional[str] = DEFAULT_SEAL_ID,
) -> Scenario:
    """The whole chain from an empty database to a bag standing at the door."""
    scn = build_queued_delivery(
        api,
        net=net,
        network_kwargs=network_kwargs,
        order_kwargs=order_kwargs,
        window_kwargs=window_kwargs,
    )
    advance_to_assigned(api, scn, courier_kwargs=courier_kwargs, dispatch_clock=dispatch_clock)
    advance_to_picked_up(api, scn, cold_chain_seal_id=cold_chain_seal_id)
    advance_to_out_for_delivery(api, scn, depart_clock=depart_clock)
    return scn


# ─── Door-step runs ───────────────────────────────────


def record_attempt(
    api: ApiClient,
    scn: Scenario,
    requested_outcome: str = "NO_ANSWER",
    **overrides: Any,
) -> Entity:
    """Record one run and refresh the delivery afterwards."""
    attempt = get_success_data(
        api.record_attempt(
            scn.delivery["id"],
            f.attempt_payload(requested_outcome, **overrides),
            headers=scn.courier_headers,
        )
    )
    scn.attempts.append(attempt)
    scn.delivery = read_delivery(api, scn.delivery["id"])
    return attempt


def redepart(api: ApiClient, scn: Scenario, clock: str) -> Scenario:
    """Wait out the cooldown, then leave again on a ladder re-attempt leg."""
    set_clock(api, clock)
    scn.delivery = get_success_data(
        api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers)
    )
    return scn


def exhaust_attempt_ladder(
    api: ApiClient,
    scn: Scenario,
    *,
    outcomes: Optional[List[str]] = None,
    first_attempt_clock: str = CLOCK_DOORSTEP_DAY3,
) -> Scenario:
    """Drive a bag through all three failed runs, honouring both cooldowns.

    One hour must pass after the first failure and three hours after the second,
    so the caller's window has to stay open until the third run.
    """
    outcomes = outcomes or ["NO_ANSWER", "NO_ANSWER", "NO_ANSWER"]
    assert len(outcomes) == 3
    set_clock(api, first_attempt_clock)
    record_attempt(api, scn, outcomes[0])
    redepart(api, scn, _plus_minutes(first_attempt_clock, 60))
    record_attempt(api, scn, outcomes[1])
    redepart(api, scn, _plus_minutes(first_attempt_clock, 60 + 180))
    record_attempt(api, scn, outcomes[2])
    scn.case = latest_case(api, scn.delivery["id"])
    return scn


def force_cold_breach(
    api: ApiClient,
    scn: Scenario,
    *,
    breach_clock: str,
    requested_outcome: str = "DELIVERED",
    **overrides: Any,
) -> Scenario:
    """Record a run at least two hours after pickup on a cold bag.

    The reported outcome is discarded: two hours out of the box means the
    product is unsafe whatever happened at the door.
    """
    set_clock(api, breach_clock)
    overrides.setdefault("id_verification_method", "GOVT_ID_SCAN")
    overrides.setdefault("signature_captured", True)
    record_attempt(api, scn, requested_outcome, **overrides)
    scn.case = latest_case(api, scn.delivery["id"])
    return scn


def deliver(api: ApiClient, scn: Scenario, **overrides: Any) -> Entity:
    """A run that clears both proof gates and lands the bag with the patient."""
    payload = f.delivered_attempt_payload(**overrides)
    attempt = get_success_data(
        api.record_attempt(scn.delivery["id"], payload, headers=scn.courier_headers)
    )
    scn.attempts.append(attempt)
    scn.delivery = read_delivery(api, scn.delivery["id"])
    return attempt


def settle(api: ApiClient, scn: Scenario, headers: Optional[Headers] = None) -> Scenario:
    """Finalize the money dimension, rebuilding the bill as the FINAL variant."""
    scn.delivery = get_success_data(
        api.settle_delivery(scn.delivery["id"], headers=headers or make_ops_headers())
    )
    return scn


def deliver_and_settle(api: ApiClient, scn: Scenario, **overrides: Any) -> Scenario:
    """Walk a bag to DELIVERED and then to FINALIZED in one step."""
    deliver(api, scn, **overrides)
    return settle(api, scn)


# ─── Exception cases ──────────────────────────────────


def open_case(
    api: ApiClient,
    delivery_id: str,
    exception_type: str = "ATTEMPTS_EXHAUSTED",
    headers: Optional[Headers] = None,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api.open_exception_case(
            f.exception_case_payload(delivery_id, exception_type, **overrides),
            headers=headers or make_ops_headers(),
        )
    )


def start_review(api: ApiClient, case_id: str, headers: Optional[Headers] = None) -> Entity:
    """An OPEN case must be taken up before it can be adjudicated."""
    return get_success_data(
        api.start_exception_review(case_id, headers=headers or make_ops_headers())
    )


def open_and_review_case(
    api: ApiClient,
    delivery_id: str,
    exception_type: str = "ATTEMPTS_EXHAUSTED",
    opener_headers: Optional[Headers] = None,
    **overrides: Any,
) -> Entity:
    """A hand-opened case carried to UNDER_REVIEW and ready for adjudication."""
    case = open_case(api, delivery_id, exception_type, headers=opener_headers, **overrides)
    return start_review(api, case["id"])


def adjudicate(
    api: ApiClient,
    case_id: str,
    disposition: str,
    expected_delivery_version: int,
    headers: Optional[Headers] = None,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api.adjudicate_exception_case(
            case_id,
            f.adjudication_payload(disposition, expected_delivery_version, **overrides),
            headers=headers or make_ops_headers(OPS_USER_A),
        )
    )


# ─── Read helpers ─────────────────────────────────────


def read_delivery(api: ApiClient, delivery_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_delivery(delivery_id, headers=headers or make_ops_headers()))


def read_window(api: ApiClient, window_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(
        api.get_delivery_window(window_id, headers=headers or make_ops_headers())
    )


def read_order(api: ApiClient, order_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_pharmacy_order(order_id, headers=headers or make_ops_headers()))


def read_courier(api: ApiClient, courier_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_courier(courier_id, headers=headers or make_ops_headers()))


def read_grant(api: ApiClient, grant_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_plan_grant(grant_id, headers=headers or make_ops_headers()))


def read_case(api: ApiClient, case_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(api.get_exception_case(case_id, headers=headers or make_ops_headers()))


def read_assignment(api: ApiClient, assignment_id: str, headers: Optional[Headers] = None) -> Entity:
    return get_success_data(
        api.get_courier_assignment(assignment_id, headers=headers or make_ops_headers())
    )


def list_rows(response) -> List[Entity]:
    """Pull the row list out of a paginated read."""
    return get_success_data(response)


def allocations_for(
    api: ApiClient,
    delivery_id: str,
    headers: Optional[Headers] = None,
    **filters: Any,
) -> List[Entity]:
    """Every allocation ever written for a delivery, newest history included."""
    return get_success_data(
        api.list_fee_allocations(
            headers or make_ops_headers(), delivery_id=delivery_id, limit=100, **filters
        )
    )


def active_allocation(api: ApiClient, delivery_id: str, headers: Optional[Headers] = None) -> Entity:
    rows = allocations_for(api, delivery_id, headers=headers, status="ACTIVE")
    assert len(rows) == 1, f"expected exactly one ACTIVE allocation, found {len(rows)}"
    return rows[0]


def cases_for(api: ApiClient, delivery_id: str, headers: Optional[Headers] = None) -> List[Entity]:
    return get_success_data(
        api.list_exception_cases(headers or make_ops_headers(), delivery_id=delivery_id, limit=100)
    )


def latest_case(api: ApiClient, delivery_id: str) -> Optional[Entity]:
    """The most recently created case on a delivery, or None when there is none."""
    rows = cases_for(api, delivery_id)
    return rows[-1] if rows else None


def assignments_for(
    api: ApiClient,
    delivery_id: str,
    headers: Optional[Headers] = None,
    **filters: Any,
) -> List[Entity]:
    return get_success_data(
        api.list_courier_assignments(
            headers or make_ops_headers(), delivery_id=delivery_id, limit=100, **filters
        )
    )


def attempts_for(
    api: ApiClient,
    delivery_id: str,
    headers: Optional[Headers] = None,
    **filters: Any,
) -> List[Entity]:
    return get_success_data(
        api.list_delivery_attempts(
            headers or make_ops_headers(), delivery_id=delivery_id, limit=100, **filters
        )
    )


# ─── Small time arithmetic ────────────────────────────


def _plus_minutes(instant: str, minutes: int) -> str:
    """Advance an ISO instant by whole minutes, staying inside one August day."""
    day = int(instant[8:10])
    hour = int(instant[11:13])
    minute = int(instant[14:16])
    total = day * 24 * 60 + hour * 60 + minute + minutes
    return utc_ts(total // (24 * 60), (total % (24 * 60)) // 60, total % 60)


plus_minutes = _plus_minutes
