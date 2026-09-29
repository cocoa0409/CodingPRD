"""Setup helpers that build the compliance record described in PRD §3.1.

Every test starts against an empty database and a logical clock reading
2026-08-01T00:00:00Z (PRD §2.8), so these helpers create their own profile,
passenger, booking and legs from scratch. They use the lenient
``get_success_data`` validator because a setup step's exact status code is not
what the test is about.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .test_users import (
    ADMIN_HEADERS,
    OFFICER_HEADERS,
    OPS_HEADERS,
    make_passenger_headers,
)


# ─── Single-row creators ──────────────────────────────


def create_policy_profile(api, carrier_code: str = "ZQ", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_policy_profile(
            f.policy_profile_payload(carrier_code, **overrides), ADMIN_HEADERS
        )
    )


def create_passenger(
    api,
    email: str = "pat@example.com",
    full_name: str = "Pat Rivera",
    headers=OFFICER_HEADERS,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_passenger(
            f.passenger_payload(email, full_name, **overrides), headers
        )
    )


def create_booking(
    api,
    passenger_id: str,
    policy_profile_id: str,
    record_locator: str = "ABC123",
    total_fare_cents: int = 50000,
    payment_method: str = "CREDIT_CARD",
    headers=OFFICER_HEADERS,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_booking(
            f.booking_payload(
                passenger_id,
                policy_profile_id,
                record_locator,
                total_fare_cents,
                payment_method,
                **overrides,
            ),
            headers,
        )
    )


def add_segment(api, booking_id: str, headers=OPS_HEADERS, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_flight_segment(
            booking_id, f.flight_segment_payload(**overrides), headers
        )
    )


def add_second_segment(
    api, booking_id: str, segment_fare_cents: int = 60000, headers=OPS_HEADERS, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_flight_segment(
            booking_id,
            f.second_segment_payload(segment_fare_cents=segment_fare_cents, **overrides),
            headers,
        )
    )


def add_ancillary(
    api,
    booking_id: str,
    flight_segment_id: str,
    service_type: str = "SEAT_SELECTION",
    amount_cents: int = 2000,
    headers=OFFICER_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_ancillary_purchase(
            f.ancillary_payload(booking_id, flight_segment_id, service_type, amount_cents),
            headers,
        )
    )


def add_checked_bag(
    api,
    booking_id: str,
    tag_number: str = "BAG0000001",
    fee_cents: int = 4500,
    checked_at_utc: str = "2026-08-10T11:00:00Z",
    scheduled_delivery_utc: str = "2026-08-10T21:00:00Z",
    headers=OFFICER_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_checked_bag(
            f.checked_bag_payload(
                booking_id,
                tag_number,
                fee_cents,
                checked_at_utc,
                scheduled_delivery_utc,
            ),
            headers,
        )
    )


# ─── Composite worlds ─────────────────────────────────


def build_world(
    api,
    total_fare_cents: int = 50000,
    payment_method: str = "CREDIT_CARD",
    segment_fares: Optional[List[int]] = None,
    carrier_code: str = "ZQ",
    record_locator: str = "ABC123",
    email: str = "pat@example.com",
    full_name: str = "Pat Rivera",
    requires_disability_assistance: Optional[bool] = None,
    is_international: bool = False,
) -> SimpleNamespace:
    """Profile + passenger + booking + optional legs, the shape §3.1 prescribes.

    ``segment_fares`` gives one ``segment_fare_cents`` per leg in travel order;
    the first leg is ZQ410 ORD→DFW and the second ZQ520 DFW→LAX.
    """
    profile = create_policy_profile(api, carrier_code)
    passenger_overrides = {}
    if requires_disability_assistance is not None:
        passenger_overrides["requires_disability_assistance"] = (
            requires_disability_assistance
        )
    passenger = create_passenger(api, email, full_name, **passenger_overrides)
    booking = create_booking(
        api,
        passenger["id"],
        profile["id"],
        record_locator,
        total_fare_cents,
        payment_method,
    )
    segments: List[Dict[str, Any]] = []
    for index, fare in enumerate(segment_fares or [], start=1):
        if index == 1:
            segments.append(
                add_segment(
                    api,
                    booking["id"],
                    segment_fare_cents=fare,
                    is_international=is_international,
                )
            )
        elif index == 2:
            segments.append(
                add_second_segment(
                    api,
                    booking["id"],
                    segment_fare_cents=fare,
                    is_international=is_international,
                )
            )
        else:
            segments.append(
                add_segment(
                    api,
                    booking["id"],
                    sequence_index=index,
                    flight_number=f"ZQ{600 + index}",
                    origin_iata="LAX",
                    destination_iata="SEA",
                    scheduled_departure_utc="2026-08-10T20:00:00Z",
                    scheduled_arrival_utc="2026-08-10T22:00:00Z",
                    segment_fare_cents=fare,
                    is_international=is_international,
                )
            )
    return SimpleNamespace(
        api=api,
        profile=profile,
        passenger=passenger,
        booking=booking,
        segments=segments,
        passenger_headers=make_passenger_headers(passenger["id"]),
    )


def build_international_world(
    api, total_fare_cents: int = 90000, segment_fare_cents: int = 90000
) -> SimpleNamespace:
    """A single international leg ORD→LHR, so the international thresholds apply."""
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api)
    booking = create_booking(
        api, passenger["id"], profile["id"], "ABC123", total_fare_cents, "CREDIT_CARD"
    )
    segment = add_segment(
        api,
        booking["id"],
        flight_number="ZQ900",
        origin_iata="ORD",
        destination_iata="LHR",
        is_international=True,
        segment_fare_cents=segment_fare_cents,
    )
    return SimpleNamespace(
        api=api,
        profile=profile,
        passenger=passenger,
        booking=booking,
        segments=[segment],
        passenger_headers=make_passenger_headers(passenger["id"]),
    )


# ─── Read-back helpers ────────────────────────────────


def read_booking(api, booking_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_booking(booking_id, headers))


def booking_version(api, booking_id: str, headers=OFFICER_HEADERS) -> int:
    return read_booking(api, booking_id, headers)["version"]


def read_segment(api, segment_id: str, headers=OPS_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_flight_segment(segment_id, headers))


def read_passenger(api, passenger_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_passenger(passenger_id, headers))


def read_profile(api, profile_id: str, headers=ADMIN_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_policy_profile(profile_id, headers))


def read_obligation(api, obligation_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_refund_obligation(obligation_id, headers))


def read_complaint(api, complaint_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_consumer_complaint(complaint_id, headers))


def read_bag(api, bag_id: str, booking_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    rows, _ = validate_paginated(api.list_booking_checked_bags(booking_id, headers))
    for row in rows:
        if row["id"] == bag_id:
            return row
    raise AssertionError(f"checked bag {bag_id} not found on booking {booking_id}")


def read_ancillary(api, purchase_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_ancillary_purchase(purchase_id, headers))


def read_denied_boarding(api, record_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_denied_boarding_record(record_id, headers))


def read_tarmac_event(
    api, event_id: str, segment_id: str, headers=ADMIN_HEADERS
) -> Dict[str, Any]:
    rows, _ = validate_paginated(api.list_segment_tarmac_events(segment_id, headers))
    for row in rows:
        if row["id"] == event_id:
            return row
    raise AssertionError(f"tarmac event {event_id} not found on segment {segment_id}")


def list_obligations(
    api, booking_id: str, headers=OFFICER_HEADERS, **filters
) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_refund_obligations(headers, booking_id=booking_id, limit=100, **filters)
    )
    return rows


def obligations_with_meta(api, booking_id: str, headers=OFFICER_HEADERS, **filters):
    return validate_paginated(
        api.list_refund_obligations(headers, booking_id=booking_id, limit=100, **filters)
    )


def sole_obligation(api, booking_id: str, headers=OFFICER_HEADERS, **filters) -> Dict[str, Any]:
    rows = list_obligations(api, booking_id, headers, **filters)
    assert len(rows) == 1, f"expected exactly one obligation, got {len(rows)}"
    return rows[0]


def list_activities(
    api, complaint_id: str, headers=OFFICER_HEADERS, **filters
) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_complaint_activities(complaint_id, headers, limit=100, **filters)
    )
    return rows


def read_exposure(api, booking_id: str, headers=OFFICER_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.get_refund_exposure(booking_id, headers))


# ─── Clock and sweep (PRD §2.8, §3.9) ─────────────────


def set_clock(api, instant: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(instant, ADMIN_HEADERS))


def run_sweep(api, policy_profile_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.run_compliance_sweep(f.sweep_payload(policy_profile_id), ADMIN_HEADERS)
    )


# ─── Frequently reused chains ─────────────────────────


def cancel_segment(
    api, segment_id: str, declared_at_utc: str = "2026-08-10T10:00:00Z", headers=OPS_HEADERS
) -> Dict[str, Any]:
    return get_success_data(
        api.declare_disruption(segment_id, f.cancellation_payload(declared_at_utc), headers)
    )


def delay_segment(
    api,
    segment_id: str,
    revised_arrival_utc: str,
    declared_at_utc: str = "2026-08-10T09:00:00Z",
    headers=OPS_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        api.declare_disruption(
            segment_id, f.delay_payload(revised_arrival_utc, declared_at_utc), headers
        )
    )


def record_operation(
    api, segment_id: str, operation: str, occurred_at_utc: str, headers=OPS_HEADERS
) -> Dict[str, Any]:
    return get_success_data(
        api.record_operation(
            segment_id, f.operation_payload(operation, occurred_at_utc), headers
        )
    )


def cancelled_booking_with_obligation(
    api, total_fare_cents: int = 50000, payment_method: str = "CREDIT_CARD"
) -> SimpleNamespace:
    """One leg, cancelled, with the cascade's PROACTIVE FARE obligation in hand."""
    world = build_world(
        api,
        total_fare_cents=total_fare_cents,
        payment_method=payment_method,
        segment_fares=[total_fare_cents],
    )
    cancel_segment(api, world.segments[0]["id"])
    world.obligation = sole_obligation(api, world.booking["id"])
    return world


def file_complaint(
    api,
    booking_id: str,
    headers=OFFICER_HEADERS,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_consumer_complaint(f.complaint_payload(booking_id, **overrides), headers)
    )


def acknowledge(api, complaint_id: str, acknowledged_at_utc: str, headers=OFFICER_HEADERS):
    return get_success_data(
        api.acknowledge_complaint(
            complaint_id, f.acknowledge_payload(acknowledged_at_utc), headers
        )
    )


def answer(
    api,
    complaint_id: str,
    answered_at_utc: str,
    disposition: str = "POLICY_EXPLAINED",
    headers=OFFICER_HEADERS,
    **overrides,
):
    return get_success_data(
        api.answer_complaint(
            complaint_id,
            f.answer_payload(answered_at_utc, disposition, **overrides),
            headers,
        )
    )


def elect(api, obligation_id: str, election: str, headers) -> Dict[str, Any]:
    return get_success_data(
        api.elect_refund_obligation(obligation_id, f.elect_payload(election), headers)
    )


def initiate(
    api, obligation_id: str, headers, processor_reference: str = "PROC-0001"
) -> Dict[str, Any]:
    return get_success_data(
        api.initiate_settlement(
            obligation_id, f.initiate_payload(processor_reference), headers
        )
    )


def complete(api, obligation_id: str, headers, outcome: str = "SUCCEEDED", **overrides):
    return get_success_data(
        api.complete_settlement(
            obligation_id, f.complete_payload(outcome, **overrides), headers
        )
    )


def void(api, obligation_id: str, void_reason: str = "CREATED_IN_ERROR") -> Dict[str, Any]:
    return get_success_data(
        api.void_refund_obligation(
            obligation_id, f.void_payload(void_reason), ADMIN_HEADERS
        )
    )


def open_report(
    api,
    policy_profile_id: str,
    period_start_utc: str = "2026-07-01T00:00:00Z",
    period_end_utc: str = "2026-07-31T23:59:59Z",
    expected_policy_profile_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = expected_policy_profile_version
    if version is None:
        version = read_profile(api, policy_profile_id)["version"]
    return get_success_data(
        api.create_regulator_report(
            f.report_payload(
                policy_profile_id, version, period_start_utc, period_end_utc
            ),
            ADMIN_HEADERS,
        )
    )
