"""Composite setup helpers for the Cold Chain Logistics test suite.

Most interesting claims require the system to be in a specific state
that takes 5-15 API calls to reach (create vehicle/driver/task →
dispatch → depart → arrive → handover → deliver → assess → decide →
claim). These helpers encapsulate those preambles so test bodies stay
focused on assertions.

Identity threading (PRD §2.1):

  'a TransportTask records shipper_id, carrier_id and consignee_id
   whose values are expected to match the X-User-ID of the corresponding
   party. ... Ownership-based access ... is enforced by comparing
   X-User-ID to the shipper_id, carrier_id, or consignee_id stored on
   the task.'

So the opaque X-User-IDs we use when creating a task must be the SAME
ones we send on later ownership-gated calls against it (carrier close,
shipper accept, consignee accept, segregation-of-duties on finalize).
Each fixture mints fresh opaque ids per scenario and threads them
back through the role builders in test_users.py.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    abort_payload,
    assess_claim_payload,
    clock_advance_payload,
    create_compliance_report_payload,
    create_damage_assessment_payload,
    create_driver_payload,
    create_insurance_claim_payload,
    create_responsibility_decision_payload,
    create_transport_task_payload,
    create_vehicle_payload,
    dispute_payload,
    handover_payload,
    iso_utc,
    patch_damage_assessment_payload,
    response_action_payload,
    subrogate_payload,
    temperature_reading_payload,
    unique_idempotency_key,
    unique_party_id,
)
from .test_users import (
    TEST_USERS,
    make_carrier_headers,
    make_compliance_headers,
    make_consignee_headers,
    make_dispatcher_headers,
    make_driver_headers,
    make_insurance_headers,
    make_shipper_headers,
    make_system_headers,
)


# ===========================================================================
# Shared opaque-role constants (only safe for non-ownership tests)
# ===========================================================================
SYSTEM = TEST_USERS["system_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DISP_ALT = TEST_USERS["dispatcher_headers_alt"]
COMPLIANCE = TEST_USERS["compliance_headers"]
COMPLIANCE_ALT = TEST_USERS["compliance_headers_alt"]
INSURANCE = TEST_USERS["insurance_headers"]


# ===========================================================================
# Clock control (PRD §2.7)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.7: 'an admin-only test-fixture capability advances the
    logical clock by a supplied seconds value.'"""
    return get_success_data(
        api_client.clock_advance(
            clock_advance_payload(seconds=seconds),
            headers or SYSTEM,
        )
    )


def get_clock_now(headers: Optional[Dict[str, str]] = None) -> str:
    """Returns the current logical clock as ISO 8601 (PRD §2.7)."""
    data = get_success_data(api_client.clock_get(headers or SYSTEM))
    return data["now"]


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp as a tz-aware datetime."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def advance_clock_to(target: datetime,
                     headers: Optional[Dict[str, str]] = None) -> None:
    """Advance the server clock so that 'now' >= target."""
    now = parse_iso(get_clock_now(headers))
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delta = int((target - now).total_seconds())
    if delta > 0:
        advance_clock(delta, headers)


# ===========================================================================
# Party id minting — keeps shipper/carrier/consignee ids unique per task
# so cross-task ownership tests don't accidentally collide.
# ===========================================================================
class TaskParties:
    """Bundle of opaque ids used to construct a single TransportTask.

    PRD §2.1: TransportTask records shipper_id, carrier_id and
    consignee_id whose values are expected to match the X-User-ID of
    the corresponding party. Use the bundle's headers methods to
    issue ownership-gated calls.
    """

    def __init__(self,
                 shipper_id: Optional[str] = None,
                 carrier_id: Optional[str] = None,
                 consignee_id: Optional[str] = None,
                 driver_id: Optional[str] = None):
        self.shipper_id = shipper_id or unique_party_id("shipper")
        self.carrier_id = carrier_id or unique_party_id("carrier")
        self.consignee_id = consignee_id or unique_party_id("consignee")
        self.driver_id = driver_id or unique_party_id("driver")

    # Identity-threading header builders
    def shipper_h(self) -> Dict[str, str]:
        return make_shipper_headers(self.shipper_id)

    def carrier_h(self) -> Dict[str, str]:
        return make_carrier_headers(self.carrier_id)

    def consignee_h(self) -> Dict[str, str]:
        return make_consignee_headers(self.consignee_id)

    def driver_h(self) -> Dict[str, str]:
        return make_driver_headers(self.driver_id)


# ===========================================================================
# Vehicle / Driver creation (uses carrier identity)
# ===========================================================================
def create_vehicle(*,
                   parties: Optional[TaskParties] = None,
                   insured_cap_cents: int = 1_000_000,
                   compartment_count: int = 2,
                   vehicle_no: Optional[str] = None) -> Dict[str, Any]:
    """PRD §3.1: 'A CARRIER creates a Vehicle by submitting vehicle_no,
    compartment_count, and insured_cap_cents.'"""
    headers = (parties.carrier_h()
               if parties is not None
               else TEST_USERS["carrier_headers"])
    overrides: Dict[str, Any] = {
        "insured_cap_cents": insured_cap_cents,
        "compartment_count": compartment_count,
    }
    if vehicle_no:
        overrides["vehicle_no"] = vehicle_no
    payload = create_vehicle_payload(**overrides)
    return get_success_data(
        api_client.create_vehicle(payload, headers)
    )


def create_driver(*,
                  parties: Optional[TaskParties] = None,
                  max_daily_minutes: Optional[int] = None,
                  name: str = "Test Driver",
                  license_no: Optional[str] = None) -> Dict[str, Any]:
    """PRD §3.1 driver registration."""
    headers = (parties.carrier_h()
               if parties is not None
               else TEST_USERS["carrier_headers"])
    overrides: Dict[str, Any] = {"name": name}
    if max_daily_minutes is not None:
        overrides["max_daily_minutes"] = max_daily_minutes
    if license_no:
        overrides["license_no"] = license_no
    payload = create_driver_payload(**overrides)
    return get_success_data(
        api_client.create_driver(payload, headers)
    )


# ===========================================================================
# Transport task creation
# ===========================================================================
def create_transport_task(
    *,
    parties: TaskParties,
    vehicle: Optional[Dict[str, Any]] = None,
    driver: Optional[Dict[str, Any]] = None,
    planned_start_at: Optional[datetime] = None,
    duration_seconds: int = 3600,
    cargo_type: str = "FOOD",
    cargo_value_cents: int = 1_000_000,
    cargo_quantity: int = 100,
    temp_min_celsius: float = -5.00,
    temp_max_celsius: float = 8.00,
    n_stops: int = 2,
    stops_override: Optional[List[Dict[str, Any]]] = None,
    polling_interval_seconds: int = 60,
    actor: str = "DISPATCHER",
) -> Dict[str, Any]:
    """PRD §3.2 task creation.

    Vehicle and driver IDs are NOT included on the create payload
    (per the input list in PRD §4) — they are PATCHed in afterward by
    the dispatcher before /dispatch.
    """
    if actor == "SHIPPER":
        headers = parties.shipper_h()
    elif actor == "DISPATCHER":
        headers = make_dispatcher_headers()
    else:  # pragma: no cover
        raise ValueError(f"Unsupported actor {actor!r}")

    if planned_start_at is None:
        # default well in the future to satisfy planned_start_at >= now
        planned_start_at = parse_iso(get_clock_now()) + timedelta(seconds=60)
    overrides: Dict[str, Any] = {
        "cargo_type": cargo_type,
        "cargo_value_cents": cargo_value_cents,
        "cargo_quantity": cargo_quantity,
        "temp_min_celsius": temp_min_celsius,
        "temp_max_celsius": temp_max_celsius,
        "polling_interval_seconds": polling_interval_seconds,
    }
    if stops_override is not None:
        overrides["stops"] = stops_override
    payload = create_transport_task_payload(
        shipper_id=parties.shipper_id,
        carrier_id=parties.carrier_id,
        consignee_id=parties.consignee_id,
        planned_start_at=planned_start_at,
        duration_seconds=duration_seconds,
        n_stops=n_stops,
        **overrides,
    )
    task = get_success_data(
        api_client.create_transport_task(payload, headers)
    )
    # PATCH vehicle_id / driver_id before dispatch.
    if vehicle is not None or driver is not None:
        patch_payload: Dict[str, Any] = {"version": task["version"]}
        if vehicle is not None:
            patch_payload["vehicle_id"] = vehicle["id"]
        if driver is not None:
            patch_payload["driver_id"] = driver["id"]
        task = get_success_data(
            api_client.patch_transport_task(
                task["id"], patch_payload, make_dispatcher_headers(),
            )
        )
    return task


# ===========================================================================
# Lifecycle shortcuts
# ===========================================================================
def setup_dispatched_task(
    *,
    parties: Optional[TaskParties] = None,
    insured_cap_cents: int = 1_000_000,
    max_daily_minutes: int = 660,
    planned_start_at: Optional[datetime] = None,
    duration_seconds: int = 3600,
    cargo_type: str = "FOOD",
    cargo_value_cents: int = 1_000_000,
    cargo_quantity: int = 100,
    temp_min_celsius: float = -5.00,
    temp_max_celsius: float = 8.00,
    n_stops: int = 2,
    stops_override: Optional[List[Dict[str, Any]]] = None,
    vehicle: Optional[Dict[str, Any]] = None,
    driver: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create vehicle + driver + task, then /dispatch.

    PRD §3.3: dispatch flips Vehicle->IN_USE, Driver->ON_DUTY, task PLANNED->DISPATCHED.
    """
    parties = parties or TaskParties()
    if vehicle is None:
        vehicle = create_vehicle(
            parties=parties, insured_cap_cents=insured_cap_cents,
        )
    if driver is None:
        driver = create_driver(
            parties=parties, max_daily_minutes=max_daily_minutes,
        )
    task = create_transport_task(
        parties=parties,
        vehicle=vehicle,
        driver=driver,
        planned_start_at=planned_start_at,
        duration_seconds=duration_seconds,
        cargo_type=cargo_type,
        cargo_value_cents=cargo_value_cents,
        cargo_quantity=cargo_quantity,
        temp_min_celsius=temp_min_celsius,
        temp_max_celsius=temp_max_celsius,
        n_stops=n_stops,
        stops_override=stops_override,
    )
    task = get_success_data(
        api_client.dispatch_task(task["id"], make_dispatcher_headers())
    )
    return {
        "parties": parties, "vehicle": vehicle, "driver": driver, "task": task,
    }


def setup_in_transit_task(**kwargs: Any) -> Dict[str, Any]:
    """DISPATCHED -> IN_TRANSIT (PRD §3.4).

    'Departure is gated by the clock: the current logical clock must be
    at least planned_start_at minus 3600 seconds.'
    """
    dispatched = setup_dispatched_task(**kwargs)
    parties: TaskParties = dispatched["parties"]
    task = dispatched["task"]
    # Make sure we're past the depart pre-window.
    advance_clock_to(parse_iso(task["planned_start_at"]))
    task = get_success_data(
        api_client.depart_task(task["id"], parties.driver_h())
    )
    dispatched["task"] = task
    return dispatched


def setup_at_stop_task(*, stop_index: int = 2, **kwargs: Any) -> Dict[str, Any]:
    """DISPATCHED -> IN_TRANSIT -> AT_STOP at the given stop sequence.

    PRD §3.4: 'As a side effect of departure, the first TaskStop
    (sequence equal to one) advances from PENDING to ARRIVED because
    the cargo is already at origin.' Therefore stop 1 is ARRIVED
    immediately after /depart; the next /arrive call must target stop 2
    or later. The default stop_index=2 matches that.

    If the caller passes stop_index=1 and the task is already past
    depart, we DO NOT issue /arrive on stop 1 — the depart side-effect
    has already advanced it.
    """
    in_transit = setup_in_transit_task(**kwargs)
    parties: TaskParties = in_transit["parties"]
    task = in_transit["task"]
    # Re-read for stops detail.
    task = get_success_data(
        api_client.get_transport_task(task["id"], parties.driver_h())
    )
    target_stop = next(
        s for s in task["stops"] if s["sequence"] == stop_index
    )
    if target_stop["status"] != "ARRIVED":
        # Advance clock to planned arrival of that stop.
        advance_clock_to(parse_iso(target_stop["planned_arrival_at"]))
        get_success_data(
            api_client.arrive_stop(task["id"], target_stop["id"], parties.driver_h())
        )
        task = get_success_data(
            api_client.get_transport_task(task["id"], parties.driver_h())
        )
    in_transit["task"] = task
    in_transit["arrived_stop_id"] = target_stop["id"]
    return in_transit


def setup_delivered_task(**kwargs: Any) -> Dict[str, Any]:
    """Walk a freshly created task all the way to DELIVERED via
    departures, arrivals and handovers (PRD §3.4)."""
    in_transit = setup_in_transit_task(**kwargs)
    parties: TaskParties = in_transit["parties"]
    task = in_transit["task"]
    task = get_success_data(
        api_client.get_transport_task(task["id"], parties.driver_h())
    )
    stops = sorted(task["stops"], key=lambda s: s["sequence"])
    # First stop already ARRIVED post-depart (PRD §3.4 side effect).
    # Handover stop 1.
    h1 = handover_payload(
        from_party_id=parties.shipper_id,
        to_party_id=parties.carrier_id,
        quantity_attested=task["cargo_quantity"],
    )
    get_success_data(
        api_client.create_handover(task["id"], stops[0]["id"], h1, parties.driver_h())
    )
    # PRD §3.4: stop 1 was advanced to ARRIVED as a side effect of the
    # origin /depart, so the parent task is already IN_TRANSIT. The
    # /depart-stop endpoint transitions AT_STOP -> IN_TRANSIT; calling it
    # on stop 1 is unnecessary because /arrive was never issued for it.
    # Iterate intermediate stops.
    for idx in range(1, len(stops) - 1):
        stop = stops[idx]
        advance_clock_to(parse_iso(stop["planned_arrival_at"]))
        get_success_data(
            api_client.arrive_stop(task["id"], stop["id"], parties.driver_h())
        )
        h = handover_payload(
            from_party_id=parties.carrier_id,
            to_party_id=parties.carrier_id,
            quantity_attested=task["cargo_quantity"],
        )
        get_success_data(
            api_client.create_handover(task["id"], stop["id"], h, parties.driver_h())
        )
        get_success_data(
            api_client.depart_stop(task["id"], stop["id"], parties.driver_h())
        )
    # Final stop: arrive then handover (cascades parent to DELIVERED).
    final_stop = stops[-1]
    advance_clock_to(parse_iso(final_stop["planned_arrival_at"]))
    get_success_data(
        api_client.arrive_stop(task["id"], final_stop["id"], parties.driver_h())
    )
    h_final = handover_payload(
        from_party_id=parties.carrier_id,
        to_party_id=parties.consignee_id,
        quantity_attested=task["cargo_quantity"],
    )
    get_success_data(
        api_client.create_handover(task["id"], final_stop["id"], h_final, parties.driver_h())
    )
    task = get_success_data(
        api_client.get_transport_task(task["id"], parties.driver_h())
    )
    in_transit["task"] = task
    in_transit["final_stop_id"] = final_stop["id"]
    return in_transit


def close_task(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.8: 'A CARRIER closes a task from DELIVERED to CLOSED.'

    Uses the carrier identity stored on the task so the ownership check
    on /close passes; falling back to the shared carrier constant would
    force the implementation to drop the ownership rule.
    """
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    task = get_success_data(
        api_client.close_task(task["id"], parties.carrier_h())
    )
    scenario["task"] = task
    return scenario


# ===========================================================================
# Temperature ingest + alert helpers
# ===========================================================================
def ingest_reading(
    *,
    task_id: str,
    captured_at: datetime,
    temperature_celsius: float = 5.00,
    sensor_kind: str = "COMPARTMENT",
    headers: Optional[Dict[str, str]] = None,
    idempotency_key: Optional[str] = None,
    strict: Optional[bool] = None,
    sensor_id: Optional[str] = None,
    gps_lat: float = 39.9042,
    gps_lng: float = 116.4074,
) -> Dict[str, Any]:
    """PRD §3.5 reading ingest. Strict mode optional."""
    payload = temperature_reading_payload(
        captured_at=captured_at,
        temperature_celsius=temperature_celsius,
        sensor_kind=sensor_kind,
        idempotency_key=idempotency_key,
        sensor_id=sensor_id,
        gps_lat=gps_lat,
        gps_lng=gps_lng,
    )
    params = {"strict": "true"} if strict else None
    return get_success_data(
        api_client.ingest_reading(
            task_id, payload, headers or SYSTEM, params=params,
        )
    )


def open_alert_via_reading(
    *,
    scenario: Dict[str, Any],
    breach_temp: float = 20.00,  # default: above 8.00 max -> ABOVE_MAX
    captured_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Open a fresh Alert by ingesting a single breaching reading on a
    task that is in DISPATCHED / IN_TRANSIT / AT_STOP (PRD §3.5/§3.6).

    Returns the Alert dict via GET /alerts?task_id=...
    """
    task = scenario["task"]
    parties: TaskParties = scenario["parties"]
    if captured_at is None:
        captured_at = parse_iso(get_clock_now())
    ingest_reading(
        task_id=task["id"],
        captured_at=captured_at,
        temperature_celsius=breach_temp,
    )
    # Locate the alert via /alerts?task_id=...
    resp = api_client.list_alerts(parties.carrier_h(),
                                  params={"task_id": task["id"]})
    page = get_success_data(resp)
    # Some implementations may flatten list into the data envelope as
    # a list directly; tolerate both shapes via the runner's lenient
    # validator.
    if isinstance(page, list):
        alerts = page
    else:  # pragma: no cover
        alerts = page if isinstance(page, list) else []
    # The list endpoint should yield at least one alert tied to task_id.
    assert alerts, "Setup: no alert opened by breaching reading"
    return alerts[-1] if isinstance(alerts, list) else alerts


def walk_alert_to_resolved(*, alert_id: str,
                           scenario: Dict[str, Any]) -> Dict[str, Any]:
    """OPEN -> ACKNOWLEDGED -> IN_RESPONSE -> RESOLVED (PRD §3.7).

    Acknowledge as DISPATCHER, record one VENTILATION response, then
    resolve. Parent task must still be IN_TRANSIT/AT_STOP/DELIVERED
    (the precondition is checked by the implementation).
    """
    get_success_data(
        api_client.acknowledge_alert(alert_id, DISP)
    )
    get_success_data(
        api_client.respond_alert(
            alert_id, response_action_payload(action_kind="VENTILATION"), DISP,
        )
    )
    alert = get_success_data(
        api_client.resolve_alert(alert_id, DISP)
    )
    return alert


# ===========================================================================
# Damage assessment helpers
# ===========================================================================
def setup_delivered_with_alert(
    *,
    parties: Optional[TaskParties] = None,
    cargo_value_cents: int = 1_000_000,
    cargo_quantity: int = 100,
    insured_cap_cents: int = 1_000_000,
    breach_temp: float = 20.00,
    extra_alerts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Bring task to DELIVERED with one RESOLVED alert.

    Optional extra_alerts is a list of dicts: each may set
      - breach_temp (float, default -15.00 BELOW_MIN)
      - keep_open  (bool, default False) — if True, the alert stays OPEN
        and is NOT walked through to RESOLVED.
      - resolve    (bool, default True)  — alias for not keep_open.
    Extra alerts are opened *before* the cargo is delivered (i.e. while
    the task is still IN_TRANSIT) because PRD §3.5 forbids reading
    ingest once the task is DELIVERED.

    Used by damage-assessment tests that require evidence_alert_ids to
    reference an alert in {RESOLVED, CLOSED} on the same task (PRD §3.9).
    """
    parties = parties or TaskParties()
    scenario = setup_in_transit_task(
        parties=parties,
        cargo_value_cents=cargo_value_cents,
        cargo_quantity=cargo_quantity,
        insured_cap_cents=insured_cap_cents,
    )
    alert = open_alert_via_reading(
        scenario=scenario, breach_temp=breach_temp,
    )
    walk_alert_to_resolved(alert_id=alert["id"], scenario=scenario)
    # Optional: open additional alerts while still IN_TRANSIT.
    extra_alert_objs: List[Dict[str, Any]] = []
    if extra_alerts:
        for spec in extra_alerts:
            # Advance a few seconds so opened_at differs from prior alerts.
            advance_clock(60)
            extra = open_alert_via_reading(
                scenario=scenario,
                breach_temp=spec.get("breach_temp", -15.00),
            )
            extra_alert_objs.append(extra)
            keep_open = spec.get("keep_open", False) or not spec.get(
                "resolve", True
            )
            if not keep_open:
                walk_alert_to_resolved(
                    alert_id=extra["id"], scenario=scenario,
                )
    # Now walk to DELIVERED — handover all stops.
    task = scenario["task"]
    task = get_success_data(
        api_client.get_transport_task(task["id"], parties.driver_h())
    )
    stops = sorted(task["stops"], key=lambda s: s["sequence"])
    # Stop 1 — already ARRIVED post-depart. Handover.
    get_success_data(
        api_client.create_handover(
            task["id"], stops[0]["id"],
            handover_payload(
                from_party_id=parties.shipper_id,
                to_party_id=parties.carrier_id,
                quantity_attested=task["cargo_quantity"],
            ),
            parties.driver_h(),
        )
    )
    # PRD §3.4: parent task is already IN_TRANSIT post-/depart-from-origin;
    # no /depart-stop is needed for stop 1.
    for idx in range(1, len(stops) - 1):
        stop = stops[idx]
        advance_clock_to(parse_iso(stop["planned_arrival_at"]))
        get_success_data(
            api_client.arrive_stop(task["id"], stop["id"], parties.driver_h())
        )
        get_success_data(
            api_client.create_handover(
                task["id"], stop["id"],
                handover_payload(
                    from_party_id=parties.carrier_id,
                    to_party_id=parties.carrier_id,
                    quantity_attested=task["cargo_quantity"],
                ),
                parties.driver_h(),
            )
        )
        get_success_data(
            api_client.depart_stop(task["id"], stop["id"], parties.driver_h())
        )
    final_stop = stops[-1]
    advance_clock_to(parse_iso(final_stop["planned_arrival_at"]))
    get_success_data(
        api_client.arrive_stop(task["id"], final_stop["id"], parties.driver_h())
    )
    get_success_data(
        api_client.create_handover(
            task["id"], final_stop["id"],
            handover_payload(
                from_party_id=parties.carrier_id,
                to_party_id=parties.consignee_id,
                quantity_attested=task["cargo_quantity"],
            ),
            parties.driver_h(),
        )
    )
    task = get_success_data(
        api_client.get_transport_task(task["id"], parties.driver_h())
    )
    scenario["task"] = task
    scenario["alert"] = alert
    scenario["extra_alerts"] = extra_alert_objs
    return scenario


def create_damage_assessment(
    *,
    scenario: Dict[str, Any],
    damaged_quantity: int = 5,
    damage_class: str = "MODERATE",
    salvage_pct: float = 0.10,
    variant: str = "INSURED_VALUE",
    invoice_unit_value_cents: Optional[int] = None,
    evidence_alert_ids: Optional[List[str]] = None,
    cause_primary: str = "TEMPERATURE_DEVIATION",
) -> Dict[str, Any]:
    """POST /damage-assessments (PRD §3.9). Returns the DRAFT assessment."""
    task = scenario["task"]
    if evidence_alert_ids is None:
        evidence_alert_ids = [scenario["alert"]["id"]]
    payload = create_damage_assessment_payload(
        task_id=task["id"],
        evidence_alert_ids=evidence_alert_ids,
        damaged_quantity=damaged_quantity,
        damage_class=damage_class,
        salvage_pct=salvage_pct,
        variant=variant,
        invoice_unit_value_cents=invoice_unit_value_cents,
        cause_primary=cause_primary,
    )
    return get_success_data(
        api_client.create_damage_assessment(payload, COMPLIANCE)
    )


def setup_finalized_assessment(**kwargs: Any) -> Dict[str, Any]:
    """Delivered + alert + draft + finalize (PRD §3.9).

    Returns scenario dict augmented with 'assessment'.
    """
    scenario = setup_delivered_with_alert(
        parties=kwargs.pop("parties", None),
        cargo_value_cents=kwargs.pop("cargo_value_cents", 1_000_000),
        cargo_quantity=kwargs.pop("cargo_quantity", 100),
        insured_cap_cents=kwargs.pop("insured_cap_cents", 1_000_000),
        breach_temp=kwargs.pop("breach_temp", 20.00),
    )
    assessment = create_damage_assessment(scenario=scenario, **kwargs)
    assessment = get_success_data(
        api_client.finalize_damage_assessment(assessment["id"], COMPLIANCE)
    )
    scenario["assessment"] = assessment
    return scenario


# ===========================================================================
# Responsibility decision helpers
# ===========================================================================
def setup_drafted_decision(
    *,
    parties: Optional[TaskParties] = None,
    shipper_pct: float = 0.30,
    carrier_pct: float = 0.50,
    consignee_pct: float = 0.20,
    split_method: str = "DURATION_WEIGHTED",
    damaged_quantity: int = 5,
    cargo_quantity: int = 100,
    **assessment_kwargs: Any,
) -> Dict[str, Any]:
    """Finalize assessment, then POST /responsibility-decisions in DRAFT."""
    scenario = setup_finalized_assessment(
        parties=parties,
        cargo_quantity=cargo_quantity,
        damaged_quantity=damaged_quantity,
        **assessment_kwargs,
    )
    task = scenario["task"]
    assessment = scenario["assessment"]
    payload = create_responsibility_decision_payload(
        task_id=task["id"],
        assessment_id=assessment["id"],
        shipper_pct=shipper_pct,
        carrier_pct=carrier_pct,
        consignee_pct=consignee_pct,
        split_method=split_method,
    )
    decision = get_success_data(
        api_client.create_responsibility_decision(payload, COMPLIANCE)
    )
    scenario["decision"] = decision
    return scenario


def setup_accepted_decision(**kwargs: Any) -> Dict[str, Any]:
    """Drafted -> Submitted -> all three parties accept (PRD §3.10).

    'when all three parties have accepted the status moves to ACCEPTED.'
    """
    scenario = setup_drafted_decision(**kwargs)
    parties: TaskParties = scenario["parties"]
    decision = scenario["decision"]
    decision = get_success_data(
        api_client.submit_decision(decision["id"], COMPLIANCE)
    )
    # All three parties accept. Each must use the same opaque ID
    # threaded into the task's shipper_id / carrier_id / consignee_id.
    get_success_data(
        api_client.accept_decision(decision["id"], parties.shipper_h())
    )
    get_success_data(
        api_client.accept_decision(decision["id"], parties.carrier_h())
    )
    decision = get_success_data(
        api_client.accept_decision(decision["id"], parties.consignee_h())
    )
    scenario["decision"] = decision
    return scenario


def setup_finalized_decision(*,
                             finalizer_id: str = "compliance-finalizer-001",
                             **kwargs: Any) -> Dict[str, Any]:
    """ACCEPTED -> FINALIZED with a distinct compliance officer ID so
    the SoD check passes (PRD §3.10).

    'Segregation of duties is the load-bearing check here: the
    finalizing actor's X-User-ID must not equal any of the task's
    shipper_id, carrier_id, or consignee_id.'
    """
    scenario = setup_accepted_decision(**kwargs)
    decision = scenario["decision"]
    finalizer_h = make_compliance_headers(finalizer_id)
    decision = get_success_data(
        api_client.finalize_decision(decision["id"], finalizer_h)
    )
    scenario["decision"] = decision
    scenario["finalizer_id"] = finalizer_id
    return scenario


# ===========================================================================
# Insurance claim helpers
# ===========================================================================
def setup_reported_claim(
    *,
    requested_amount_cents: int = 1000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Finalize the decision, then POST /insurance-claims (PRD §3.11)."""
    scenario = setup_finalized_decision(**kwargs)
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    decision = scenario["decision"]
    payload = create_insurance_claim_payload(
        task_id=task["id"],
        decision_id=decision["id"],
        requested_amount_cents=requested_amount_cents,
    )
    claim = get_success_data(
        api_client.create_insurance_claim(payload, parties.carrier_h())
    )
    scenario["claim"] = claim
    return scenario


def setup_assessment_claim(
    *,
    assessed_amount_cents: int = 800,
    requested_amount_cents: int = 1000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Reported -> EvidencePrep -> ASSESSMENT (PRD §3.11)."""
    scenario = setup_reported_claim(
        requested_amount_cents=requested_amount_cents, **kwargs,
    )
    parties: TaskParties = scenario["parties"]
    claim = scenario["claim"]
    claim = get_success_data(
        api_client.prepare_evidence(claim["id"], parties.carrier_h())
    )
    claim = get_success_data(
        api_client.assess_claim(
            claim["id"], assess_claim_payload(assessed_amount_cents),
            INSURANCE,
        )
    )
    scenario["claim"] = claim
    return scenario


def setup_paid_out_claim(
    *,
    assessed_amount_cents: int = 800,
    requested_amount_cents: int = 1000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Assessment -> PAID_OUT (PRD §3.11)."""
    scenario = setup_assessment_claim(
        assessed_amount_cents=assessed_amount_cents,
        requested_amount_cents=requested_amount_cents,
        **kwargs,
    )
    claim = scenario["claim"]
    claim = get_success_data(api_client.pay_claim(claim["id"], INSURANCE))
    scenario["claim"] = claim
    return scenario


# ===========================================================================
# DIFFICULTY-DESIGN composite fixtures
# ===========================================================================
def setup_finalized_assessment_pair_for_dual_variant(
    *,
    insured_cap_cents: int = 500_000,
    cargo_value_cents: int = 1_000_000,
    cargo_quantity: int = 100,
    invoice_unit_value_cents: int = 12_000,
    damaged_quantity: int = 5,
    damage_class: str = "MODERATE",
    salvage_pct: float = 0.10,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build two sibling DamageAssessments — one with variant=INSURED_VALUE,
    one with variant=INVOICE_VALUE — same damaged_quantity/damage_class/
    salvage_pct, distinct tasks.

    PRD §3.9 dual-variant calculation.
    Difficulty: dual_variant_calc / damage_amount_insured_vs_invoice_value.
    """
    parties_a = TaskParties()
    parties_b = TaskParties()
    scenario_a = setup_delivered_with_alert(
        parties=parties_a,
        cargo_value_cents=cargo_value_cents,
        cargo_quantity=cargo_quantity,
        insured_cap_cents=insured_cap_cents,
    )
    scenario_b = setup_delivered_with_alert(
        parties=parties_b,
        cargo_value_cents=cargo_value_cents,
        cargo_quantity=cargo_quantity,
        insured_cap_cents=insured_cap_cents,
    )
    a = create_damage_assessment(
        scenario=scenario_a,
        damaged_quantity=damaged_quantity,
        damage_class=damage_class,
        salvage_pct=salvage_pct,
        variant="INSURED_VALUE",
    )
    b = create_damage_assessment(
        scenario=scenario_b,
        damaged_quantity=damaged_quantity,
        damage_class=damage_class,
        salvage_pct=salvage_pct,
        variant="INVOICE_VALUE",
        invoice_unit_value_cents=invoice_unit_value_cents,
    )
    scenario_a["assessment"] = a
    scenario_b["assessment"] = b
    return scenario_a, scenario_b


def setup_two_dispatch_overlap_pair(
    *,
    base_start: Optional[datetime] = None,
    first_duration_seconds: int = 3600,
    gap_seconds: int = 0,
    second_duration_seconds: int = 3600,
    insured_cap_cents: int = 1_000_000,
) -> Dict[str, Any]:
    """Build two tasks sharing the same Vehicle. First task is dispatched;
    second is a PLANNED candidate offset by gap_seconds from first.end.

    gap_seconds = 0 -> exact adjacency (PRD §3.3 half-open allowed).
    gap_seconds < 0 -> strict overlap (rejection).

    PRD §3.3: 'when both intervals are treated as half-open ranges of
    the form starting at planned_start_at (inclusive) and ending at
    planned_end_at (exclusive), no other task on this vehicle in
    DISPATCHED, IN_TRANSIT, or AT_STOP may have an interval that strictly
    intersects the new task's interval.'
    """
    if base_start is None:
        base_start = parse_iso(get_clock_now()) + timedelta(seconds=60)
    parties_a = TaskParties()
    # Both tasks share the same vehicle (carrier identity).
    parties_b = TaskParties(carrier_id=parties_a.carrier_id)
    vehicle = create_vehicle(
        parties=parties_a, insured_cap_cents=insured_cap_cents,
    )
    driver_a = create_driver(parties=parties_a, max_daily_minutes=660)
    driver_b = create_driver(parties=parties_a, max_daily_minutes=660)
    first = setup_dispatched_task(
        parties=parties_a,
        planned_start_at=base_start,
        duration_seconds=first_duration_seconds,
        vehicle=vehicle, driver=driver_a,
    )
    first_end = base_start + timedelta(seconds=first_duration_seconds)
    second_start = first_end + timedelta(seconds=gap_seconds)
    second = create_transport_task(
        parties=parties_b,
        vehicle=vehicle, driver=driver_b,
        planned_start_at=second_start,
        duration_seconds=second_duration_seconds,
    )
    return {
        "vehicle": vehicle,
        "driver_a": driver_a, "driver_b": driver_b,
        "first": first, "second": second,
        "second_parties": parties_b,
    }


def setup_driver_at_minutes(
    *,
    consumed_minutes: int,
    new_task_minutes: int,
    max_daily_minutes: int = 660,
    base_start: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a Driver with one already-DISPATCHED task consuming
    `consumed_minutes`, plus a second PLANNED candidate of
    `new_task_minutes` entirely inside the same 24h window.

    PRD §3.3: 'For any candidate 24-hour rolling window ... the driver's
    accumulated minutes within that window is the sum, over all assigned
    tasks, of the minute-count of the intersection of each task's
    interval with that window. The dispatch is rejected if there exists
    any such anchored window where the driver's accumulated minutes plus
    the new task's overlap into that window strictly exceeds
    max_daily_minutes; equality with max_daily_minutes is allowed.'

    Difficulty: boundary_precision_check / driver_rolling_24h_minutes_strict_gt.
    Difficulty: resource_temporal_overlap / driver_rolling_24h_aggregate_capacity.
    """
    if base_start is None:
        base_start = parse_iso(get_clock_now()) + timedelta(seconds=60)
    parties_a = TaskParties()
    parties_b = TaskParties(carrier_id=parties_a.carrier_id)
    # Two distinct vehicles, one shared driver.
    vehicle_a = create_vehicle(parties=parties_a)
    vehicle_b = create_vehicle(parties=parties_a)
    driver = create_driver(parties=parties_a,
                           max_daily_minutes=max_daily_minutes)
    first = setup_dispatched_task(
        parties=parties_a,
        planned_start_at=base_start,
        duration_seconds=consumed_minutes * 60,
        vehicle=vehicle_a, driver=driver,
    )
    # Second task starts after first ends (no vehicle overlap because
    # different vehicle) but inside the same 24h window relative to
    # first.planned_start_at.
    second_start = base_start + timedelta(
        seconds=consumed_minutes * 60 + 600,  # 10 min gap
    )
    second = create_transport_task(
        parties=parties_b,
        vehicle=vehicle_b, driver=driver,
        planned_start_at=second_start,
        duration_seconds=new_task_minutes * 60,
    )
    return {
        "driver": driver, "vehicle_a": vehicle_a, "vehicle_b": vehicle_b,
        "first": first, "second": second,
        "second_parties": parties_b,
    }


def setup_two_evidence_alerts_with_custody(
    *,
    parties: Optional[TaskParties] = None,
    cargo_value_cents: int = 1_000_000,
    cargo_quantity: int = 100,
    insured_cap_cents: int = 1_000_000,
) -> Dict[str, Any]:
    """Build a DELIVERED task with two RESOLVED alerts under distinct
    custody segments — Alert A under SHIPPER custody (longer duration,
    smaller peak), Alert B under CARRIER custody (shorter duration,
    larger peak).

    Custody segments come from HandoverRecord boundaries (PRD §2.9, §3.10):

      Origin -> Stop1 handover: SHIPPER custody.
      Stop1 -> Stop2 handover: CARRIER custody.
      After Stop2 final handover: CONSIGNEE custody.

    Used for responsibility_split_advisory difficulty instance.
    """
    parties = parties or TaskParties()
    # Use 3 stops (origin + intermediate + final) for two custody legs.
    base_start = parse_iso(get_clock_now()) + timedelta(seconds=60)
    stops_override: List[Dict[str, Any]] = [
        {
            "sequence": 1, "location_label": "Origin",
            "planned_arrival_at": iso_utc(base_start + timedelta(seconds=600)),
            "handover_required": True,
        },
        {
            "sequence": 2, "location_label": "Transfer Hub",
            "planned_arrival_at": iso_utc(base_start + timedelta(seconds=3600)),
            "handover_required": True,
        },
        {
            "sequence": 3, "location_label": "Final Destination",
            "planned_arrival_at": iso_utc(base_start + timedelta(seconds=7200)),
            "handover_required": True,
        },
    ]
    scenario = setup_in_transit_task(
        parties=parties,
        planned_start_at=base_start,
        duration_seconds=7800,
        cargo_value_cents=cargo_value_cents,
        cargo_quantity=cargo_quantity,
        insured_cap_cents=insured_cap_cents,
        n_stops=3,
        stops_override=stops_override,
    )
    task = scenario["task"]
    parties = scenario["parties"]
    task = get_success_data(
        api_client.get_transport_task(task["id"], parties.driver_h())
    )
    stops = sorted(task["stops"], key=lambda s: s["sequence"])
    # Alert A in SHIPPER custody (before stop 1 handover) — long duration,
    # small peak (temp_max=8.00 so 9.00 gives peak deviation 1.00, but
    # peak grows when we add a second reading at 9.50 -> peak 1.50.
    # Keep peak small (1.50) so SEVERITY favours alert B.
    alert_a_open_at = parse_iso(get_clock_now())
    ingest_reading(
        task_id=task["id"],
        captured_at=alert_a_open_at,
        temperature_celsius=9.00,
    )
    # Hold this elevated reading for a while to give alert A a long
    # duration under SHIPPER custody.
    advance_clock(1500)  # 25 min
    # Resolve A.
    resp_a = api_client.list_alerts(parties.carrier_h(),
                                    params={"task_id": task["id"]})
    page_a = get_success_data(resp_a)
    alerts_a = page_a if isinstance(page_a, list) else []
    assert alerts_a, "Setup: alert A not opened"
    alert_a = alerts_a[-1]
    walk_alert_to_resolved(alert_id=alert_a["id"], scenario=scenario)
    # Handover stop 1 -> hands custody from SHIPPER to CARRIER.
    advance_clock_to(parse_iso(stops[0]["planned_arrival_at"]))
    get_success_data(
        api_client.create_handover(
            task["id"], stops[0]["id"],
            handover_payload(
                from_party_id=parties.shipper_id,
                to_party_id=parties.carrier_id,
                quantity_attested=task["cargo_quantity"],
            ),
            parties.driver_h(),
        )
    )
    # PRD §3.4: parent task is already IN_TRANSIT post-/depart-from-origin;
    # no /depart-stop is needed for stop 1 (no /arrive was issued for it).
    # Alert B in CARRIER custody — short duration, large peak.
    alert_b_open_at = parse_iso(get_clock_now())
    ingest_reading(
        task_id=task["id"],
        captured_at=alert_b_open_at,
        temperature_celsius=15.00,  # peak deviation 7.00 — CRITICAL
    )
    advance_clock(300)  # 5 min
    resp_b = api_client.list_alerts(parties.carrier_h(),
                                    params={"task_id": task["id"]})
    page_b = get_success_data(resp_b)
    alerts_b = page_b if isinstance(page_b, list) else []
    # The latest alert is alert B (BELOW or ABOVE distinct from A).
    alert_b = [a for a in alerts_b if a["id"] != alert_a["id"]]
    assert alert_b, "Setup: alert B not opened"
    alert_b_obj = alert_b[-1]
    walk_alert_to_resolved(alert_id=alert_b_obj["id"], scenario=scenario)
    # Arrive stop 2 -> handover to CARRIER (intra-carrier).
    advance_clock_to(parse_iso(stops[1]["planned_arrival_at"]))
    get_success_data(
        api_client.arrive_stop(task["id"], stops[1]["id"], parties.driver_h())
    )
    get_success_data(
        api_client.create_handover(
            task["id"], stops[1]["id"],
            handover_payload(
                from_party_id=parties.carrier_id,
                to_party_id=parties.carrier_id,
                quantity_attested=task["cargo_quantity"],
            ),
            parties.driver_h(),
        )
    )
    get_success_data(
        api_client.depart_stop(task["id"], stops[1]["id"], parties.driver_h())
    )
    # Arrive stop 3 (final) -> handover -> DELIVERED.
    advance_clock_to(parse_iso(stops[2]["planned_arrival_at"]))
    get_success_data(
        api_client.arrive_stop(task["id"], stops[2]["id"], parties.driver_h())
    )
    get_success_data(
        api_client.create_handover(
            task["id"], stops[2]["id"],
            handover_payload(
                from_party_id=parties.carrier_id,
                to_party_id=parties.consignee_id,
                quantity_attested=task["cargo_quantity"],
            ),
            parties.driver_h(),
        )
    )
    task = get_success_data(
        api_client.get_transport_task(task["id"], parties.driver_h())
    )
    scenario["task"] = task
    scenario["alert_a"] = alert_a
    scenario["alert_b"] = alert_b_obj
    return scenario


def setup_mediation_cycle_decision(**kwargs: Any) -> Dict[str, Any]:
    """Drive a ResponsibilityDecision through DRAFT -> UNDER_REVIEW ->
    DISPUTED -> MEDIATION (PRD §3.10).

    'Submitting the decision moves it from DRAFT to UNDER_REVIEW. ...
    Any of the three parties may instead dispute, supplying a reason,
    which moves the decision from UNDER_REVIEW to DISPUTED. A compliance
    officer then enters mediation, advancing the decision from DISPUTED
    to MEDIATION.'
    """
    scenario = setup_drafted_decision(**kwargs)
    parties: TaskParties = scenario["parties"]
    decision = scenario["decision"]
    decision = get_success_data(
        api_client.submit_decision(decision["id"], COMPLIANCE)
    )
    decision = get_success_data(
        api_client.dispute_decision(
            decision["id"], dispute_payload("carrier objection"),
            parties.carrier_h(),
        )
    )
    decision = get_success_data(
        api_client.mediate_decision(decision["id"], COMPLIANCE)
    )
    scenario["decision"] = decision
    return scenario


__all__ = [
    "SYSTEM", "DISP", "DISP_ALT", "COMPLIANCE", "COMPLIANCE_ALT", "INSURANCE",
    "TaskParties",
    "advance_clock", "advance_clock_to", "get_clock_now", "parse_iso",
    "create_vehicle", "create_driver",
    "create_transport_task",
    "setup_dispatched_task", "setup_in_transit_task",
    "setup_at_stop_task", "setup_delivered_task", "close_task",
    "ingest_reading",
    "open_alert_via_reading", "walk_alert_to_resolved",
    "setup_delivered_with_alert", "create_damage_assessment",
    "setup_finalized_assessment",
    "setup_drafted_decision", "setup_accepted_decision",
    "setup_finalized_decision",
    "setup_reported_claim", "setup_assessment_claim", "setup_paid_out_claim",
    "setup_finalized_assessment_pair_for_dual_variant",
    "setup_two_dispatch_overlap_pair", "setup_driver_at_minutes",
    "setup_two_evidence_alerts_with_custody",
    "setup_mediation_cycle_decision",
]
