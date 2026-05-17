"""Composite setup helpers — multi-step preambles that tests reuse.

The lab workflow is long: register Clinicians (LabDirector + LabTech +
OrderingProvider) -> register Patient -> define TestPanel -> place
LabOrder -> record Specimen -> open TransportLeg -> arrive at LAB_MAIN
-> resultate -> release -> notification opened. Most interesting test
claims need the system in a late-pipeline state, and the difficulty-
design instances demand cross-entity state combos requiring 10+ API
calls.

IDENTITY THREADING — PRD §2.1.

  "All three roles are entity-backed by the `Clinician` table: when
  `X-User-Role` is `OrderingProvider`, `LabTech`, or `LabDirector`,
  `X-User-ID` is the `id` of the acting `Clinician`."

Every ownership/identity-gated call mints headers via
make_<role>_headers(<clinician_id>). The shared fallback headers are
NEVER used inside fixtures.

  - LabDirector calls (create_clinician, create_test_panel, release,
    amend, retract, clock_advance, run_sweep, list_audit_events) mint
    headers with a real LAB_DIRECTOR Clinician.id.
  - LabTech calls (create_specimen, create_transport_leg,
    arrive_transport_leg, report_break, WAIVED/MODERATE resulting)
    mint headers with the LAB_TECH Clinician.id.
  - OrderingProvider calls (create_lab_order, cancel_lab_order,
    acknowledge_notification, cancel_retest_request) mint headers with
    the OrderingProvider Clinician.id whose id equals
    ordering_provider_id on the order, or recipient_clinician_id on
    the notification.

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ACK_WINDOW_ROUTINE_MIN,
    ACK_WINDOW_STAT_MIN,
    LAB_LOCATION_CODE,
    TEST_DEFAULTS,
)
from .factories import (
    acknowledge_payload,
    amend_result_payload,
    analyte_spec,
    arrive_transport_leg_payload,
    cancel_lab_order_payload,
    clock_advance_payload,
    create_clinician_payload,
    create_lab_order_payload,
    create_patient_payload,
    create_result_payload,
    create_specimen_payload,
    create_test_panel_payload,
    create_transport_leg_payload,
    iso_anchor_offset,
    measurement,
    parse_anchor,
    random_courier_id,
    random_location_code,
    release_result_payload,
    retract_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_lab_director_headers,
    make_lab_tech_headers,
    make_ordering_provider_headers,
)


# ===========================================================================
# Bootstrap LabDirector — chicken-and-egg helper.
# ===========================================================================
# PRD §3.1: "A `Clinician` is registered exclusively by a
# `LabDirector`." But the FIRST LabDirector has no predecessor — the
# implementation must accept an initial LabDirector registration via
# the fallback header so the rest of the catalogue can be built. The
# bootstrap header is used ONLY for this first POST /clinicians call
# in each test; thereafter every Clinician creation mints headers
# against the bootstrapped LabDirector's id.
# ---------------------------------------------------------------------------
def _bootstrap_lab_director(
    full_name: str = "Bootstrap LabDirector",
) -> Dict[str, Any]:
    """Register the first LabDirector. Returns the persisted clinician.

    Implementations that gate POST /clinicians strictly by an
    already-registered LabDirector should accept this initial call when
    the caller's declared role is LabDirector even if X-User-ID is not
    yet known — there is no other way to bootstrap. The implementer is
    free to require the first LabDirector to be seeded out-of-band; in
    that case this fixture must be updated to discover the seeded id
    via GET /_clock or some other known-safe read. The current default
    relies on a permissive first-creation rule.
    """
    payload = create_clinician_payload(
        role_kind="LAB_DIRECTOR", full_name=full_name,
    )
    resp = api_client.create_clinician(
        payload, TEST_USERS["lab_director_fallback_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Clock helpers — PRD §3.8.
# ===========================================================================
def anchor_clock(director: Dict[str, Any]) -> Dict[str, Any]:
    """Pin the server clock to the deterministic test anchor.

    PRD §3.8: 'A clock-advance capability lets a LabDirector move the
    server's notion of "now" forward by supplying a `to_iso8601`
    instant.' Requires LabDirector headers.
    """
    resp = api_client.clock_advance(
        clock_advance_payload(to_iso8601=TEST_DEFAULTS["CLOCK_ANCHOR"]),
        make_lab_director_headers(director["id"]),
    )
    return get_success_data(resp)


def advance_clock_to(director: Dict[str, Any], iso_timestamp: str
                     ) -> Dict[str, Any]:
    resp = api_client.clock_advance(
        clock_advance_payload(to_iso8601=iso_timestamp),
        make_lab_director_headers(director["id"]),
    )
    return get_success_data(resp)


def run_sweep(director: Dict[str, Any]) -> Dict[str, Any]:
    """POST /_sweep/run as LabDirector — PRD §3.8."""
    resp = api_client.run_sweep(make_lab_director_headers(director["id"]))
    return get_success_data(resp)


# ===========================================================================
# Catalog bundle — a reusable cast of Clinicians, Patient, TestPanel.
# ===========================================================================
class CatalogBundle(dict):
    """Container for a freshly created cast used by fixtures.

    Keys: director, director2, lab_tech, lab_tech2, ordering_provider,
    ordering_provider2, patient, panel. Each value is the persisted
    entity dict.

    A typed dict-derived class is unnecessary here — tests reach into
    bundles by short keys to construct further calls.
    """


def create_catalog_bundle(
    *,
    panel_complexity: str = "MODERATE",
    panel_stability_minutes: int = 120,
    analytes: Optional[List[Dict[str, Any]]] = None,
    notification_consent: Optional[str] = None,
    include_second_director: bool = True,
    include_second_ordering_provider: bool = False,
    include_second_lab_tech: bool = False,
) -> CatalogBundle:
    """Bootstrap a cast that satisfies every ownership precondition for
    a single end-to-end pipeline.

    Builds, in order: bootstrap LabDirector -> 2nd LabDirector (so
    CLIA SoD on release can use distinct clinicians) -> LabTech ->
    OrderingProvider -> Patient -> TestPanel. Returns a CatalogBundle.

    The two directors satisfy PRD §2.6: "the clinician named in
    `released_by_id` ... must be a different clinician from the one
    named in `resulted_by_id`."
    """
    director = _bootstrap_lab_director(full_name="Director A")
    bundle = CatalogBundle()
    bundle["director"] = director
    director_headers = make_lab_director_headers(director["id"])

    if include_second_director:
        director2 = get_success_data(api_client.create_clinician(
            create_clinician_payload(
                role_kind="LAB_DIRECTOR", full_name="Director B",
            ),
            director_headers,
        ))
        bundle["director2"] = director2

    lab_tech = get_success_data(api_client.create_clinician(
        create_clinician_payload(
            role_kind="LAB_TECH", full_name="Tech A",
        ),
        director_headers,
    ))
    bundle["lab_tech"] = lab_tech

    if include_second_lab_tech:
        lab_tech2 = get_success_data(api_client.create_clinician(
            create_clinician_payload(
                role_kind="LAB_TECH", full_name="Tech B",
            ),
            director_headers,
        ))
        bundle["lab_tech2"] = lab_tech2

    ordering_provider = get_success_data(api_client.create_clinician(
        create_clinician_payload(
            role_kind="ORDERING_PROVIDER", full_name="Provider A",
        ),
        director_headers,
    ))
    bundle["ordering_provider"] = ordering_provider

    if include_second_ordering_provider:
        ordering_provider2 = get_success_data(api_client.create_clinician(
            create_clinician_payload(
                role_kind="ORDERING_PROVIDER", full_name="Provider B",
            ),
            director_headers,
        ))
        bundle["ordering_provider2"] = ordering_provider2

    # Patient: ordering providers may create patients per PRD §3.1.
    op_headers = make_ordering_provider_headers(ordering_provider["id"])
    patient_payload = create_patient_payload(
        full_name="Test Patient",
        include_notification_consent=(notification_consent is not None),
        notification_consent=notification_consent,
    )
    patient = get_success_data(
        api_client.create_patient(patient_payload, op_headers),
    )
    bundle["patient"] = patient

    # Panel: LabDirector only.
    panel = get_success_data(api_client.create_test_panel(
        create_test_panel_payload(
            clia_complexity=panel_complexity,
            stability_minutes=panel_stability_minutes,
            analytes=analytes,
        ),
        director_headers,
    ))
    bundle["panel"] = panel

    return bundle


# ===========================================================================
# Tier 1: State progression — order through receipt.
# ===========================================================================
def place_lab_order(bundle: CatalogBundle, *,
                    priority: Optional[str] = None,
                    patient_id: Optional[str] = None,
                    ) -> Dict[str, Any]:
    """POST /lab-orders as the bundle's OrderingProvider."""
    op = bundle["ordering_provider"]
    payload = create_lab_order_payload(
        patient_id=patient_id or bundle["patient"]["id"],
        ordering_provider_id=op["id"],
        panel_id=bundle["panel"]["id"],
        priority=priority,
    )
    resp = api_client.create_lab_order(
        payload, make_ordering_provider_headers(op["id"]),
    )
    return get_success_data(resp)


def collect_specimen(bundle: CatalogBundle,
                     order: Dict[str, Any],
                     *,
                     collected_at: Optional[str] = None,
                     ) -> Dict[str, Any]:
    """POST /lab-orders/{id}/specimens as the bundle's LabTech."""
    tech = bundle["lab_tech"]
    payload = create_specimen_payload(
        collected_by_id=tech["id"],
        collected_at=(
            collected_at if collected_at is not None
            else iso_anchor_offset(minutes=-5)
        ),
    )
    resp = api_client.create_specimen(
        order["id"], payload, make_lab_tech_headers(tech["id"]),
    )
    return get_success_data(resp)


def open_transport_leg(bundle: CatalogBundle,
                       specimen: Dict[str, Any],
                       *,
                       from_location: Optional[str] = None,
                       to_location: Optional[str] = None,
                       departed_at: Optional[str] = None,
                       ) -> Dict[str, Any]:
    """POST /specimens/{id}/transport-legs as the bundle's LabTech."""
    tech = bundle["lab_tech"]
    payload = create_transport_leg_payload(
        from_location=(
            from_location if from_location is not None
            else random_location_code("CLINIC")
        ),
        to_location=(
            to_location if to_location is not None else LAB_LOCATION_CODE
        ),
        departed_at=(
            departed_at if departed_at is not None
            else iso_anchor_offset(minutes=0)
        ),
        courier_id=random_courier_id(),
    )
    resp = api_client.create_transport_leg(
        specimen["id"], payload, make_lab_tech_headers(tech["id"]),
    )
    return get_success_data(resp)


def arrive_leg(bundle: CatalogBundle,
               leg: Dict[str, Any],
               *,
               arrived_at: Optional[str] = None,
               ) -> Dict[str, Any]:
    """POST /transport-legs/{id}/arrive as the bundle's LabTech."""
    tech = bundle["lab_tech"]
    payload = arrive_transport_leg_payload(
        arrived_at=(
            arrived_at if arrived_at is not None
            else iso_anchor_offset(minutes=10)
        ),
    )
    resp = api_client.arrive_transport_leg(
        leg["id"], payload, make_lab_tech_headers(tech["id"]),
    )
    return get_success_data(resp)


def walk_order_to_received(
    bundle: CatalogBundle,
    *,
    priority: Optional[str] = None,
    collected_at: Optional[str] = None,
    departed_at: Optional[str] = None,
    arrived_at: Optional[str] = None,
    from_location: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end: place order -> collect -> open leg to LAB_MAIN ->
    arrive within stability. Returns dict {order, specimen, leg}.
    """
    order = place_lab_order(bundle, priority=priority)
    spec = collect_specimen(bundle, order, collected_at=collected_at)
    leg = open_transport_leg(
        bundle, spec,
        from_location=from_location,
        to_location=LAB_LOCATION_CODE,
        departed_at=departed_at,
    )
    leg_after = arrive_leg(bundle, leg, arrived_at=arrived_at)
    return {"order": order, "specimen": spec, "leg": leg_after}


# ===========================================================================
# Tier 2: Resulting and release (drafts + critical and non-critical).
# ===========================================================================
def resultate(
    bundle: CatalogBundle,
    order: Dict[str, Any],
    *,
    measurements: List[Dict[str, Any]],
    resulted_by: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """POST /lab-orders/{id}/results.

    Defaults to the bundle's LabTech for MODERATE/WAIVED panels; the
    caller passes a LabDirector explicitly for HIGH panels per PRD
    §2.6.
    """
    actor = resulted_by or bundle["lab_tech"]
    role_kind = actor.get("role_kind")
    if role_kind == "LAB_TECH":
        headers = make_lab_tech_headers(actor["id"])
    else:
        headers = make_lab_director_headers(actor["id"])
    payload = create_result_payload(
        resulted_by_id=actor["id"], measurements=measurements,
    )
    resp = api_client.create_result(order["id"], payload, headers)
    return get_success_data(resp)


def release(
    bundle: CatalogBundle,
    result: Dict[str, Any],
    *,
    released_by: Optional[Dict[str, Any]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /results/{id}/release as a LabDirector distinct from the
    resulted_by per PRD §2.6.

    Default releaser is bundle["director2"] when present, otherwise
    bundle["director"]. Caller may override.
    """
    director = released_by
    if director is None:
        director = bundle.get("director2") or bundle["director"]
    payload = release_result_payload(
        released_by_id=director["id"], version=version,
    )
    resp = api_client.release_result(
        result["id"], payload, make_lab_director_headers(director["id"]),
    )
    return get_success_data(resp)


def critical_measurements_high(
    panel_analytes: List[Dict[str, Any]],
    *, value: float = 400.0,
) -> List[Dict[str, Any]]:
    """Build a measurement list where every HIGH-bounded analyte is
    above its critical_high. Useful for getting non-empty
    critical_flags."""
    out = []
    for spec in panel_analytes:
        unit = spec["unit"]
        code = spec["analyte_code"]
        if spec.get("critical_high") is not None:
            out.append(measurement(
                analyte_code=code, value=value, unit=unit,
            ))
        elif spec.get("critical_low") is not None:
            out.append(measurement(
                analyte_code=code,
                value=spec["critical_low"] - 1, unit=unit,
            ))
        else:
            out.append(measurement(
                analyte_code=code, value=value, unit=unit,
            ))
    return out


def normal_measurements(
    panel_analytes: List[Dict[str, Any]],
    *, value: float = 250.0,
) -> List[Dict[str, Any]]:
    """Build a measurement list where every value is well inside any
    declared bound. Useful for getting empty critical_flags."""
    out = []
    for spec in panel_analytes:
        unit = spec["unit"]
        code = spec["analyte_code"]
        out.append(measurement(
            analyte_code=code, value=value, unit=unit,
        ))
    return out


# ===========================================================================
# Tier 3: Full lifecycle shortcuts — released order with notification.
# ===========================================================================
def setup_released_critical(
    *,
    priority: str = "ROUTINE",
    panel_complexity: str = "MODERATE",
    notification_consent: Optional[str] = None,
    analytes: Optional[List[Dict[str, Any]]] = None,
    high_value: float = 400.0,
    bundle: Optional[CatalogBundle] = None,
) -> Dict[str, Any]:
    """Full setup: catalog -> order -> specimen -> leg -> arrive ->
    result with critical_flags non-empty -> release. Returns dict with
    bundle, order, specimen, leg, result, notification.

    Side effect of release per PRD §3.4: a CriticalNotification is
    created on the SMS channel in PENDING.
    """
    if bundle is None:
        bundle = create_catalog_bundle(
            panel_complexity=panel_complexity,
            analytes=analytes,
            notification_consent=notification_consent,
        )
    anchor_clock(bundle["director"])

    walked = walk_order_to_received(bundle, priority=priority)
    order = walked["order"]

    panel = bundle["panel"]
    # Choose resulter that satisfies CLIA complexity tier.
    if panel["clia_complexity"] == "HIGH":
        resulted_by = bundle["director"]
    else:
        resulted_by = bundle["lab_tech"]

    meas = critical_measurements_high(panel["analytes"], value=high_value)
    result = resultate(
        bundle, order,
        measurements=meas,
        resulted_by=resulted_by,
    )
    released = release(bundle, result)

    # Locate the freshly opened CriticalNotification — list by
    # recipient_clinician_id (cloned from order.ordering_provider_id at
    # release time per PRD §3.4).
    op = bundle["ordering_provider"]
    list_resp = api_client.list_notifications(
        make_ordering_provider_headers(op["id"]),
        params={"recipient_clinician_id": op["id"], "limit": 100},
    )
    list_data = get_success_data(list_resp)
    # list_data may be either the array directly or wrapped — use
    # response["data"] semantics on the envelope.
    items = list_data if isinstance(list_data, list) else list_data
    notification = None
    for n in items:
        if n.get("lab_result_id") == released["id"]:
            notification = n
            break

    return {
        "bundle": bundle,
        "order": order,
        "specimen": walked["specimen"],
        "leg": walked["leg"],
        "result": released,
        "notification": notification,
    }


def setup_released_non_critical(
    *,
    priority: str = "ROUTINE",
    panel_complexity: str = "MODERATE",
    notification_consent: Optional[str] = None,
    analytes: Optional[List[Dict[str, Any]]] = None,
    normal_value: float = 250.0,
) -> Dict[str, Any]:
    """Released order whose measurements have NO critical flags.

    Per PRD §3.4: 'When the result's critical_flags is empty, the
    system appends a single ComplianceAuditEvent with event_type of
    RESULT_RELEASED and the workflow ends with the result released and
    no notification opened.' Returns bundle/order/specimen/leg/result.
    """
    bundle = create_catalog_bundle(
        panel_complexity=panel_complexity,
        analytes=analytes,
        notification_consent=notification_consent,
    )
    anchor_clock(bundle["director"])
    walked = walk_order_to_received(bundle, priority=priority)
    order = walked["order"]
    panel = bundle["panel"]
    if panel["clia_complexity"] == "HIGH":
        resulted_by = bundle["director"]
    else:
        resulted_by = bundle["lab_tech"]
    meas = normal_measurements(panel["analytes"], value=normal_value)
    result = resultate(
        bundle, order,
        measurements=meas, resulted_by=resulted_by,
    )
    released = release(bundle, result)
    return {
        "bundle": bundle,
        "order": order,
        "specimen": walked["specimen"],
        "leg": walked["leg"],
        "result": released,
    }


# ===========================================================================
# Tier 4: Threshold / accumulation targeting.
# ===========================================================================
def setup_two_priorities_at_anchor() -> Dict[str, Any]:
    """Two released orders at the same anchored clock — one ROUTINE and
    one STAT — both with critical_flags non-empty so both produce a
    CriticalNotification. Returns dict {bundle, routine, stat}.

    PRD §3.5 ack_deadline_at differs by priority: ROUTINE -> +30 min,
    STAT -> +10 min. Both notifications are produced with the same
    first_sent_at because we keep the clock at anchor between releases.
    """
    bundle = create_catalog_bundle(panel_complexity="MODERATE")
    anchor_clock(bundle["director"])

    # Two orders, two specimens, two arrivals — all at anchor.
    routine = _walked_and_released(
        bundle, priority="ROUTINE",
    )
    stat = _walked_and_released(
        bundle, priority="STAT",
    )
    return {
        "bundle": bundle,
        "routine": routine,
        "stat": stat,
    }


def _walked_and_released(bundle: CatalogBundle, *, priority: str
                         ) -> Dict[str, Any]:
    walked = walk_order_to_received(bundle, priority=priority)
    panel = bundle["panel"]
    resulted_by = (
        bundle["director"] if panel["clia_complexity"] == "HIGH"
        else bundle["lab_tech"]
    )
    meas = critical_measurements_high(panel["analytes"], value=400.0)
    result = resultate(
        bundle, walked["order"],
        measurements=meas, resulted_by=resulted_by,
    )
    released = release(bundle, result)
    op = bundle["ordering_provider"]
    listing = get_success_data(api_client.list_notifications(
        make_ordering_provider_headers(op["id"]),
        params={
            "recipient_clinician_id": op["id"], "limit": 100,
        },
    ))
    notification = None
    for n in listing:
        if n.get("lab_result_id") == released["id"]:
            notification = n
            break
    return {
        "order": walked["order"],
        "specimen": walked["specimen"],
        "leg": walked["leg"],
        "result": released,
        "notification": notification,
    }


def setup_two_orders_for_ordered_escalation(
) -> Dict[str, Any]:
    """Two ROUTINE-priority orders released back-to-back so that their
    notifications have identical ack_deadline_at but different
    created_at — needed for the chronological-ordering test of the
    sweep (PRD §3.5 sort key: ack_deadline_at ASC, created_at ASC).

    Strategy: keep the clock anchored at T0 for the entire setup (so
    both notifications share first_sent_at = T0), and release order A
    first then order B. The implementation should record created_at in
    real time, producing A.created_at < B.created_at.

    Returns dict {bundle, A, B}.
    """
    bundle = create_catalog_bundle(panel_complexity="MODERATE")
    anchor_clock(bundle["director"])
    a = _walked_and_released(bundle, priority="ROUTINE")
    b = _walked_and_released(bundle, priority="ROUTINE")
    return {"bundle": bundle, "A": a, "B": b}


# ===========================================================================
# Tier 5: Cascade / terminal-state setups.
# ===========================================================================
def setup_in_transit_for_break() -> Dict[str, Any]:
    """Order walked to IN_TRANSIT with a DEPARTED leg, ready for
    report-break. Returns dict {bundle, order, specimen, leg}.
    """
    bundle = create_catalog_bundle(panel_complexity="MODERATE")
    anchor_clock(bundle["director"])
    order = place_lab_order(bundle)
    spec = collect_specimen(bundle, order)
    leg = open_transport_leg(
        bundle, spec,
        from_location="CLINIC_A", to_location="HUB_B",
    )
    return {
        "bundle": bundle,
        "order": order,
        "specimen": spec,
        "leg": leg,
    }


def setup_specimen_with_arrived_first_leg(
) -> Dict[str, Any]:
    """Order with a first leg already ARRIVED at HUB_B (not LAB_MAIN
    so no stability check fires). Returns dict {bundle, order, spec,
    leg1}.

    Used by the transport-chain-contiguity test, which then attempts a
    second leg whose from_location does NOT equal HUB_B.
    """
    bundle = create_catalog_bundle(panel_complexity="MODERATE")
    anchor_clock(bundle["director"])
    order = place_lab_order(bundle)
    spec = collect_specimen(bundle, order)
    leg1 = open_transport_leg(
        bundle, spec,
        from_location="CLINIC_A", to_location="HUB_B",
        departed_at=iso_anchor_offset(minutes=0),
    )
    leg1_arr = arrive_leg(
        bundle, leg1,
        arrived_at=iso_anchor_offset(minutes=5),
    )
    return {
        "bundle": bundle,
        "order": order,
        "specimen": spec,
        "leg1": leg1_arr,
    }


# ===========================================================================
# Tier 6: Multi-patient / multi-order setups (conservation invariants).
# ===========================================================================
def setup_patient_with_three_ordered(
) -> Dict[str, Any]:
    """One patient with three LabOrders all in ORDERED. Returns dict
    {bundle, orders: [o1, o2, o3]}.
    """
    bundle = create_catalog_bundle(panel_complexity="MODERATE")
    anchor_clock(bundle["director"])
    orders = [
        place_lab_order(bundle, priority="ROUTINE")
        for _ in range(3)
    ]
    return {"bundle": bundle, "orders": orders}


# ===========================================================================
# Tier 7: Helpers used by tests that need to read by id after mutation.
# ===========================================================================
def reget_lab_order(bundle: CatalogBundle, order_id: str
                    ) -> Dict[str, Any]:
    """GET /lab-orders/{id} as LabDirector — universally permitted to
    read."""
    director = bundle["director"]
    resp = api_client.get_lab_order(
        order_id, make_lab_director_headers(director["id"]),
    )
    return get_success_data(resp)


def reget_specimen(bundle: CatalogBundle, specimen_id: str
                   ) -> Dict[str, Any]:
    director = bundle["director"]
    resp = api_client.get_specimen(
        specimen_id, make_lab_director_headers(director["id"]),
    )
    return get_success_data(resp)


def reget_result(bundle: CatalogBundle, result_id: str
                 ) -> Dict[str, Any]:
    director = bundle["director"]
    resp = api_client.get_result(
        result_id, make_lab_director_headers(director["id"]),
    )
    return get_success_data(resp)


def reget_notification(bundle: CatalogBundle, notif_id: str
                       ) -> Dict[str, Any]:
    op = bundle["ordering_provider"]
    resp = api_client.get_notification(
        notif_id, make_ordering_provider_headers(op["id"]),
    )
    return get_success_data(resp)


def reget_retest(bundle: CatalogBundle, retest_id: str
                 ) -> Dict[str, Any]:
    director = bundle["director"]
    resp = api_client.get_retest_request(
        retest_id, make_lab_director_headers(director["id"]),
    )
    return get_success_data(resp)


def list_retests_for_order(bundle: CatalogBundle, order_id: str,
                           ) -> List[Dict[str, Any]]:
    director = bundle["director"]
    resp = api_client.list_retest_requests(
        make_lab_director_headers(director["id"]),
        params={"lab_order_id": order_id, "limit": 100},
    )
    return get_success_data(resp)


def list_audit_for_order(bundle: CatalogBundle,
                         order_id: str,
                         event_type: Optional[str] = None,
                         ) -> List[Dict[str, Any]]:
    director = bundle["director"]
    params: Dict[str, Any] = {"lab_order_id": order_id, "limit": 100}
    if event_type is not None:
        params["event_type"] = event_type
    resp = api_client.list_audit_events(
        make_lab_director_headers(director["id"]), params=params,
    )
    return get_success_data(resp)


def list_notifications_for_result(bundle: CatalogBundle,
                                  result_id: str,
                                  ) -> List[Dict[str, Any]]:
    op = bundle["ordering_provider"]
    resp = api_client.list_notifications(
        make_ordering_provider_headers(op["id"]),
        params={
            "recipient_clinician_id": op["id"], "limit": 100,
        },
    )
    items = get_success_data(resp)
    return [n for n in items if n.get("lab_result_id") == result_id]


def list_orders_for_patient(bundle: CatalogBundle, patient_id: str
                            ) -> List[Dict[str, Any]]:
    director = bundle["director"]
    resp = api_client.list_lab_orders(
        make_lab_director_headers(director["id"]),
        params={"patient_id": patient_id, "limit": 100},
    )
    return get_success_data(resp)


def acknowledge_with_recipient(
    bundle: CatalogBundle,
    notification: Dict[str, Any],
    *,
    read_back_text: str,
) -> Dict[str, Any]:
    """POST /notifications/{id}/acknowledge as the recipient — the
    OrderingProvider whose id equals recipient_clinician_id."""
    op = bundle["ordering_provider"]
    payload = acknowledge_payload(
        acknowledged_by_id=op["id"], read_back_text=read_back_text,
    )
    resp = api_client.acknowledge_notification(
        notification["id"], payload,
        make_ordering_provider_headers(op["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Bundle-aware mutating helpers (returning raw Response).
# ===========================================================================
# These return the raw Response object so test assertions can check
# error envelopes via validate_error(). The helpers above that return
# get_success_data(...) are for setup that MUST succeed.


def attempt_release(
    bundle: CatalogBundle,
    result: Dict[str, Any],
    *,
    released_by: Optional[Dict[str, Any]] = None,
    actor: Optional[Dict[str, Any]] = None,
    version: Optional[int] = None,
):
    """POST /results/{id}/release as `actor` (LabDirector). When
    `actor` is None, defaults to `released_by` so identity matches
    the body."""
    director = released_by or bundle.get("director2") or bundle["director"]
    headers_actor = actor or director
    payload = release_result_payload(
        released_by_id=director["id"], version=version,
    )
    return api_client.release_result(
        result["id"], payload,
        make_lab_director_headers(headers_actor["id"]),
    )


def attempt_amend(
    bundle: CatalogBundle,
    result: Dict[str, Any],
    *,
    measurements: List[Dict[str, Any]],
    actor: Optional[Dict[str, Any]] = None,
    version: Optional[int] = None,
):
    director = actor or bundle.get("director2") or bundle["director"]
    payload = amend_result_payload(
        measurements=measurements, version=version,
    )
    return api_client.amend_result(
        result["id"], payload,
        make_lab_director_headers(director["id"]),
    )


def attempt_retract(
    bundle: CatalogBundle,
    result: Dict[str, Any],
    *,
    actor: Optional[Dict[str, Any]] = None,
    version: Optional[int] = None,
):
    director = actor or bundle.get("director2") or bundle["director"]
    payload = retract_result_payload(version=version)
    return api_client.retract_result(
        result["id"],
        make_lab_director_headers(director["id"]),
        payload=payload,
    )


def attempt_acknowledge(
    bundle: CatalogBundle,
    notification: Dict[str, Any],
    *,
    acknowledger_id: str,
    actor_id: Optional[str] = None,
    read_back_text: str,
):
    """POST /notifications/{id}/acknowledge with explicit ids — used by
    tests that DELIBERATELY pass a non-recipient acknowledger or a
    non-recipient actor (to provoke error paths)."""
    headers_id = actor_id if actor_id is not None else acknowledger_id
    payload = acknowledge_payload(
        acknowledged_by_id=acknowledger_id, read_back_text=read_back_text,
    )
    return api_client.acknowledge_notification(
        notification["id"], payload,
        make_ordering_provider_headers(headers_id),
    )


def attempt_cancel_order(
    bundle: CatalogBundle,
    order: Dict[str, Any],
    *,
    actor: Optional[Dict[str, Any]] = None,
    version: Optional[int] = None,
):
    op = actor or bundle["ordering_provider"]
    payload = cancel_lab_order_payload(version=version)
    return api_client.cancel_lab_order(
        order["id"], make_ordering_provider_headers(op["id"]),
        payload=payload,
    )


def attempt_cancel_retest(
    bundle: CatalogBundle,
    retest: Dict[str, Any],
    *,
    actor: Optional[Dict[str, Any]] = None,
):
    op = actor or bundle["ordering_provider"]
    return api_client.cancel_retest_request(
        retest["id"], make_ordering_provider_headers(op["id"]),
    )


def attempt_resultate(
    bundle: CatalogBundle,
    order: Dict[str, Any],
    *,
    measurements: List[Dict[str, Any]],
    resulted_by: Optional[Dict[str, Any]] = None,
    actor: Optional[Dict[str, Any]] = None,
):
    """POST /lab-orders/{id}/results with explicit actor. When `actor`
    is None defaults to `resulted_by` so identity matches body."""
    rb = resulted_by or bundle["lab_tech"]
    headers_actor = actor or rb
    role_kind = headers_actor.get("role_kind")
    if role_kind == "LAB_TECH":
        headers = make_lab_tech_headers(headers_actor["id"])
    else:
        headers = make_lab_director_headers(headers_actor["id"])
    payload = create_result_payload(
        resulted_by_id=rb["id"], measurements=measurements,
    )
    return api_client.create_result(order["id"], payload, headers)


def attempt_arrive_leg(
    bundle: CatalogBundle,
    leg: Dict[str, Any],
    *,
    arrived_at: str,
    actor: Optional[Dict[str, Any]] = None,
):
    tech = actor or bundle["lab_tech"]
    payload = arrive_transport_leg_payload(arrived_at=arrived_at)
    return api_client.arrive_transport_leg(
        leg["id"], payload, make_lab_tech_headers(tech["id"]),
    )


def attempt_open_transport_leg(
    bundle: CatalogBundle,
    specimen: Dict[str, Any],
    *,
    from_location: str,
    to_location: str,
    departed_at: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
):
    tech = actor or bundle["lab_tech"]
    payload = create_transport_leg_payload(
        from_location=from_location,
        to_location=to_location,
        departed_at=(
            departed_at if departed_at is not None
            else iso_anchor_offset(minutes=5)
        ),
        courier_id=random_courier_id(),
    )
    return api_client.create_transport_leg(
        specimen["id"], payload, make_lab_tech_headers(tech["id"]),
    )


__all__ = [
    "CatalogBundle",
    # bootstrap / catalog
    "create_catalog_bundle",
    # clock / sweep
    "anchor_clock",
    "advance_clock_to",
    "run_sweep",
    # progression
    "place_lab_order",
    "collect_specimen",
    "open_transport_leg",
    "arrive_leg",
    "walk_order_to_received",
    # resulting / release
    "resultate",
    "release",
    "critical_measurements_high",
    "normal_measurements",
    # composite setups
    "setup_released_critical",
    "setup_released_non_critical",
    "setup_two_priorities_at_anchor",
    "setup_two_orders_for_ordered_escalation",
    "setup_in_transit_for_break",
    "setup_specimen_with_arrived_first_leg",
    "setup_patient_with_three_ordered",
    # re-reads
    "reget_lab_order",
    "reget_specimen",
    "reget_result",
    "reget_notification",
    "reget_retest",
    "list_retests_for_order",
    "list_audit_for_order",
    "list_notifications_for_result",
    "list_orders_for_patient",
    "acknowledge_with_recipient",
    # raw-response attempts
    "attempt_release",
    "attempt_amend",
    "attempt_retract",
    "attempt_acknowledge",
    "attempt_cancel_order",
    "attempt_cancel_retest",
    "attempt_resultate",
    "attempt_arrive_leg",
    "attempt_open_transport_leg",
]
