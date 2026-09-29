"""Nothing in this system lags behind the request that changed it.

The issuance response already carries the minted seed and both status dimensions,
the parent counters are current on the very next read, and the admit is fully
settled across ticket, zone, event, gate and session before the response returns.
"""

from test_helpers import (
    AdmissionStatus,
    DeviceBindingStatus,
    EventStatus,
    GATE_OPERATOR,
    LifecycleStatus,
    ScanResult,
    ScanSource,
    SessionMode,
    ZonePosture,
    constants as C,
    fixtures as fx,
    validate_success,
)


def test_every_counter_touched_by_a_write_is_settled_on_the_very_next_read(api):
    """One issuance and one admit, each followed immediately by reads of everything they moved.

    PRD: "Issuance mints the ticket's `barcode_seed`, the server-side secret every rotating barcode for that ticket is derived from, and opens the ticket in `lifecycle_status` `ISSUED`, `admission_status` `NOT_ADMITTED` and `device_binding_status` `UNBOUND`, with `transfer_count`, `admitted_scan_count` at zero and `bound_device_fingerprint`, `last_admitted_at`, `last_exited_at` and `credential_request_id` all null."
    PRD: "Issuance moves three counters. The target zone's `issued_entitlement_count` rises by one and its `posture` is recomputed; the event's `entitlements_outstanding` rises by one; and only when the `ticket_type` is `PAID` does the event's `settlement_pool_cents` rise by the ticket's `face_value_cents`."
    PRD: "The posture is derived from the exact ratio of `issued_entitlement_count` to the zone's `fire_code_capacity`, compared without rounding: the posture is `FROZEN` when that ratio is at least 1.00, `RESTRICTED` when it is at least 0.90 but below 1.00, and `OPEN` otherwise."
    PRD: "Admission moves the ticket `NOT_ADMITTED → INSIDE`, refreshes `last_admitted_at` and increments the ticket's `admitted_scan_count`, raises the zone's `occupancy_count` and the event's `live_occupancy` by one each, raises the event's `peak_live_occupancy` whenever the new live figure exceeds it, and increments the gate's `admitted_scan_count` and the session's `online_scan_count`."
    PRD: "The **live** reading, persisted as an event's `live_occupancy` and a zone's `occupancy_count`, replays only those scan events whose `source` is `ONLINE`, in ascending `recorded_at` order with ascending `created_at` as the tie-break."
    PRD: "The **reconciled** reading, persisted as a report's `scan_derived_attendance` and surfaced as `reconciled_attendance` on the occupancy read, counts distinct `ticket_id` values across scan events whose `result` is `ADMITTED` regardless of `source`, so offline-replayed scans are included, processed in ascending `scanned_at` order with ascending `recorded_at` as the tie-break."
    PRD: "The server persists a **ScanEvent** with its `scan_session_id`, the `ticket_id` the seed part resolved to (null when it resolved to nothing), a `source` of `ONLINE`, a `recorded_at` equal to the logical clock, an adjudicated `result`, and a `denied_reason_code` carrying the error identifier the denial mapped to, which is null for admitted and exit results."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_caused_it
    """
    event = fx.create_event(api)
    # A capacity of two makes the posture ratio move measurably on one issuance.
    zone = fx.create_zone(api, event["id"], fire_code_capacity=2)
    gate = fx.create_gate(api, event["id"], zone["id"], throughput_per_minute=20)
    assert zone["issued_entitlement_count"] == 0
    assert zone["posture"] == ZonePosture.OPEN
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)
    ada = fx.register_patron(api)

    issued = fx.issue_ticket(
        api, event["id"], zone["id"], ada["id"], face_value_cents=12000
    )
    # The creating response is already complete on both status dimensions.
    assert issued["lifecycle_status"] == LifecycleStatus.ISSUED
    assert issued["admission_status"] == AdmissionStatus.NOT_ADMITTED
    assert issued["device_binding_status"] == DeviceBindingStatus.UNBOUND
    assert issued["barcode_seed"] is not None

    counted_zone = fx.read_zone(api, zone["id"])
    assert counted_zone["issued_entitlement_count"] == 1
    assert counted_zone["occupancy_count"] == 0
    # One of two is a ratio of 0.50, short of the advisory band.
    assert counted_zone["posture"] == ZonePosture.OPEN

    counted_event = fx.read_event(api, event["id"])
    # The parent counters are current with no intervening write.
    assert counted_event["entitlements_outstanding"] == 1
    assert counted_event["settlement_pool_cents"] == 12000

    fx.bind_device(api, issued["id"], ada["id"], "DEV-ADA")
    fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, gate["id"], mode=SessionMode.ONLINE)

    admitted = fx.admit_ticket(api, session["id"], issued["id"], "DEV-ADA", "C1")
    assert admitted["result"] == ScanResult.ADMITTED
    assert admitted["source"] == ScanSource.ONLINE
    assert admitted["recorded_at"] == C.T_18_10_00

    # No clock movement sits between the admit and any of these reads.
    occupancy = fx.read_occupancy(api, event["id"])
    assert occupancy["live_occupancy"] == 1
    assert occupancy["peak_live_occupancy"] == 1
    assert occupancy["reconciled_attendance"] == 1

    assert fx.read_ticket(api, issued["id"])["admission_status"] == AdmissionStatus.INSIDE
    assert fx.read_gate(api, gate["id"])["admitted_scan_count"] == 1
    assert (
        validate_success(api.get_scan_session(session["id"], GATE_OPERATOR))["online_scan_count"]
        == 1
    )

    # Reads settle nothing of their own: a second pass returns the same derived figures.
    assert fx.read_occupancy(api, event["id"]) == occupancy
    assert fx.read_zone(api, zone["id"])["occupancy_count"] == 1
    assert fx.read_event(api, event["id"])["live_occupancy"] == 1
