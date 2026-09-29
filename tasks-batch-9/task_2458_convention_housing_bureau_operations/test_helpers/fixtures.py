"""Composite setup helpers.

Most interesting claims in this API need the system driven several calls deep:
an event, a property, a negotiated and signed block, a carved and approved
sub-block, an opened portal, imported delegates and their reservations, and
often the logical clock repositioned past the cutoff or the event end. These
helpers encapsulate those ladders so tests can focus on assertions.

Every helper uses the lenient success reader so a broken precondition surfaces
as a setup failure rather than as a confusing assertion error.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_attendee_headers,
    make_event_organizer_headers,
    make_hotel_manager_headers,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

_ATTENDEE_NAMES = [
    "Attendee One",
    "Attendee Two",
    "Attendee Three",
    "Attendee Four",
    "Attendee Five",
    "Attendee Six",
]


# ---------------------------------------------------------------------------
# Tier 1: single-step primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Reposition the logical clock (PRD §2.5)."""
    return get_success_data(
        api_client.set_clock(f.clock_payload(to_iso8601), COORDINATOR)
    )


def register_event(**overrides) -> dict:
    return get_success_data(
        api_client.create_event(f.create_event_payload(**overrides), COORDINATOR)
    )


def register_hotel(**overrides) -> dict:
    return get_success_data(
        api_client.create_hotel(f.create_hotel_payload(**overrides), COORDINATOR)
    )


def set_hotel_standing(hotel_id: str, standing: str) -> dict:
    return get_success_data(
        api_client.update_hotel_standing(
            hotel_id, f.hotel_standing_payload(standing), COORDINATOR
        )
    )


def assemble_block(event_id: str, hotel_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_hotel_block(
            f.create_hotel_block_payload(event_id, hotel_id, **overrides), COORDINATOR
        )
    )


def read_block(block_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_hotel_block(block_id, headers or COORDINATOR)
    )


def submit_terms(block: dict, expected_version: Optional[int] = None, **overrides) -> dict:
    version = expected_version if expected_version is not None else block["version"]
    return get_success_data(
        api_client.submit_block_terms(
            block["id"], f.block_terms_payload(version, **overrides), COORDINATOR
        )
    )


def request_block_changes(block_id: str, hotel_id: str) -> dict:
    return get_success_data(
        api_client.request_block_changes(block_id, make_hotel_manager_headers(hotel_id))
    )


def contract_block(block_id: str, hotel_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.contract_hotel_block(
            block_id,
            f.contract_block_payload(**overrides),
            make_hotel_manager_headers(hotel_id),
        )
    )


def carve_sub_block(
    block_id: str,
    segment: str,
    allotted_rooms: int,
    expected_version: Optional[int] = None,
    headers=None,
    **overrides,
) -> dict:
    """Carve a sub-block, reading the block's current version when none is given."""
    version = (
        expected_version
        if expected_version is not None
        else read_block(block_id)["version"]
    )
    return get_success_data(
        api_client.carve_sub_block(
            block_id,
            f.carve_sub_block_payload(segment, allotted_rooms, version, **overrides),
            headers or COORDINATOR,
        )
    )


def approve_sub_block(sub_block_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.approve_sub_block(sub_block_id, headers or CONTROLLER)
    )


def reject_sub_block(sub_block_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.reject_sub_block(sub_block_id, headers or CONTROLLER)
    )


def release_sub_block_rooms(sub_block_id: str, rooms: int) -> dict:
    return get_success_data(
        api_client.release_sub_block(
            sub_block_id, f.release_sub_block_payload(rooms), COORDINATOR
        )
    )


def open_block(block_id: str) -> dict:
    return get_success_data(api_client.open_hotel_block(block_id, COORDINATOR))


def cutoff_block(block_id: str) -> dict:
    return get_success_data(api_client.cutoff_hotel_block(block_id, COORDINATOR))


def close_block(block_id: str) -> dict:
    return get_success_data(api_client.close_hotel_block(block_id, COORDINATOR))


def import_attendee(event_id: str, index: int = 1, **overrides) -> dict:
    fields = {
        "email": f"a{index}@example.com",
        "full_name": _ATTENDEE_NAMES[(index - 1) % len(_ATTENDEE_NAMES)],
        "registration_id": f"REG-{index}",
    }
    fields.update(overrides)
    payload = f.create_attendee_payload(event_id, **fields)
    return get_success_data(api_client.create_attendee(payload, COORDINATOR))


def book_reservation(
    sub_block_id: str,
    attendee: dict,
    check_in_date: Optional[str] = None,
    check_out_date: Optional[str] = None,
    occupants: int = 1,
    headers=None,
    **overrides,
) -> dict:
    payload = f.create_reservation_payload(
        sub_block_id,
        attendee["id"],
        check_in_date=check_in_date or TEST_DEFAULTS["EVENT_START_DATE"],
        check_out_date=check_out_date or TEST_DEFAULTS["EVENT_END_DATE"],
        occupants=occupants,
        **overrides,
    )
    return get_success_data(
        api_client.create_reservation(
            payload, headers or make_attendee_headers(attendee["id"])
        )
    )


def cancel_reservation(reservation_id: str, attendee_id: Optional[str] = None) -> dict:
    headers = make_attendee_headers(attendee_id) if attendee_id else COORDINATOR
    return get_success_data(api_client.cancel_reservation(reservation_id, headers))


def report_no_show(reservation_id: str, hotel_id: str) -> dict:
    return get_success_data(
        api_client.no_show_reservation(
            reservation_id, make_hotel_manager_headers(hotel_id)
        )
    )


def transmit_rooming_list(block_id: str, transmission_type: str = "INITIAL") -> dict:
    return get_success_data(
        api_client.transmit_rooming_list(
            block_id, f.rooming_list_payload(transmission_type), COORDINATOR
        )
    )


def file_pickup_report(
    block_id: str,
    hotel_id: str,
    as_of_date: str,
    reported_rooms_picked_up: int,
    reported_room_nights: int,
    reported_gross_revenue_cents: int,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_pickup_report(
            block_id,
            f.pickup_report_payload(
                as_of_date,
                reported_rooms_picked_up,
                reported_room_nights,
                reported_gross_revenue_cents,
                **overrides,
            ),
            make_hotel_manager_headers(hotel_id),
        )
    )


def file_reduction(block_id: str, rooms: int, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_attrition_reduction(
            f.attrition_reduction_payload(block_id, rooms, **overrides),
            headers or COORDINATOR,
        )
    )


def approve_reduction(reduction_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.approve_attrition_reduction(reduction_id, headers or CONTROLLER)
    )


def exercise_reduction(reduction_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.exercise_attrition_reduction(reduction_id, headers or COORDINATOR)
    )


def record_rogue_vendor(event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rogue_vendor(
            f.create_rogue_vendor_payload(event_id, **overrides), COMPLIANCE
        )
    )


def record_incident(
    vendor_id: str,
    attendee_id: str,
    contact_channel: str = "EMAIL",
    occurred_at: str = "2026-07-20T10:00:00Z",
    verified: bool = True,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_poaching_incident(
            vendor_id,
            f.poaching_incident_payload(
                attendee_id, contact_channel, occurred_at, verified, **overrides
            ),
            COMPLIANCE,
        )
    )


def confirm_vendor(vendor_id: str) -> dict:
    return get_success_data(api_client.confirm_rogue_vendor(vendor_id, COMPLIANCE))


def clear_vendor(vendor_id: str) -> dict:
    return get_success_data(api_client.clear_rogue_vendor(vendor_id, COMPLIANCE))


def issue_invoice(block_id: str, basis: str = "BUREAU_CONFIRMED") -> dict:
    return get_success_data(
        api_client.issue_commission_invoice(
            block_id, f.commission_invoice_payload(basis), COORDINATOR
        )
    )


def pay_invoice(invoice_id: str, hotel_id: str, amount_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.pay_commission_invoice(
            invoice_id,
            f.payment_payload(amount_cents, **overrides),
            make_hotel_manager_headers(hotel_id),
        )
    )


def reverse_payment(invoice_id: str, amount_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.reverse_commission_payment(
            invoice_id, f.payment_reversal_payload(amount_cents, **overrides), CONTROLLER
        )
    )


def dispute_invoice(invoice_id: str, hotel_id: str) -> dict:
    return get_success_data(
        api_client.dispute_commission_invoice(
            invoice_id, make_hotel_manager_headers(hotel_id)
        )
    )


def adjust_invoice(invoice_id: str, write_off_cents: int) -> dict:
    return get_success_data(
        api_client.adjust_commission_invoice(
            invoice_id, f.adjust_invoice_payload(write_off_cents), CONTROLLER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2/3: the housing-program ladder
# ---------------------------------------------------------------------------


def setup_housing_program(
    contracted_rooms_per_night: int = 10,
    carves: Optional[List[dict]] = None,
    open_portal: bool = False,
    attendees: Optional[List[dict]] = None,
    reservations: Optional[List[dict]] = None,
    contract: bool = True,
    event_overrides: Optional[dict] = None,
    hotel_overrides: Optional[dict] = None,
    block_overrides: Optional[dict] = None,
    terms_overrides: Optional[dict] = None,
    confirmation_number: str = TEST_DEFAULTS["CONFIRMATION_NUMBER"],
) -> dict:
    """Drive the full program ladder and return every entity it created.

    `carves` is a list of dicts such as
    ``{"segment": "VIP", "allotted_rooms": 2, "approve": True,
       "eligibility_code": "VIP-GOLD", "parent": 0}``
    where ``parent`` is the index of an earlier carve to nest under.
    `attendees` is a list of payload override dicts (one per delegate).
    `reservations` is a list of dicts such as
    ``{"attendee": 0, "sub_block": 0, "check_in_date": ..., "check_out_date": ...}``.

    Returns a context dict with keys: event, hotel, block, hotel_headers,
    organizer_headers, sub_blocks, attendees, reservations.
    """
    event = register_event(**(event_overrides or {}))
    hotel = register_hotel(**(hotel_overrides or {}))
    block = assemble_block(
        event["id"],
        hotel["id"],
        contracted_rooms_per_night=contracted_rooms_per_night,
        **(block_overrides or {}),
    )
    terms_defaults = {}
    for key in (
        "negotiated_nightly_rate_cents",
        "commission_pct",
        "rebate_per_room_night_cents",
        "cutoff_date",
        "reduction_rights_pct",
    ):
        if block_overrides and key in block_overrides:
            terms_defaults[key] = block_overrides[key]
    terms_defaults.update(terms_overrides or {})
    block = submit_terms(block, **terms_defaults)

    if contract:
        block = contract_block(
            block["id"], hotel["id"], confirmation_number=confirmation_number
        )

    sub_blocks = []
    for carve in carves or []:
        parent_index = carve.get("parent")
        extra = {}
        if parent_index is not None:
            extra["parent_sub_block_id"] = sub_blocks[parent_index]["id"]
        if "eligibility_code" in carve:
            extra["eligibility_code"] = carve["eligibility_code"]
        sub_block = carve_sub_block(
            block["id"],
            carve["segment"],
            carve["allotted_rooms"],
            headers=carve.get("headers"),
            **extra,
        )
        if carve.get("approve") and sub_block["approval_status"] == "PENDING_APPROVAL":
            sub_block = approve_sub_block(sub_block["id"])
        sub_blocks.append(sub_block)

    if open_portal:
        block = open_block(block["id"])

    delegates = []
    for index, overrides in enumerate(attendees or [], start=1):
        delegates.append(import_attendee(event["id"], index, **(overrides or {})))

    bookings = []
    for spec in reservations or []:
        target = sub_blocks[spec.get("sub_block", 0)]
        attendee = delegates[spec.get("attendee", 0)]
        bookings.append(
            book_reservation(
                target["id"],
                attendee,
                check_in_date=spec.get("check_in_date"),
                check_out_date=spec.get("check_out_date"),
                occupants=spec.get("occupants", 1),
                headers=spec.get("headers"),
            )
        )

    return {
        "event": event,
        "hotel": hotel,
        "block": read_block(block["id"]),
        "hotel_headers": make_hotel_manager_headers(hotel["id"]),
        "organizer_headers": make_event_organizer_headers(event["id"]),
        "sub_blocks": sub_blocks,
        "attendees": delegates,
        "reservations": bookings,
    }


def setup_contracted_block(contracted_rooms_per_night: int = 10, **kwargs) -> dict:
    """Event + hotel + block negotiated and signed, nothing carved yet."""
    return setup_housing_program(
        contracted_rooms_per_night=contracted_rooms_per_night, **kwargs
    )


def setup_open_block(
    general_rooms: int = 6,
    contracted_rooms_per_night: int = 10,
    num_attendees: int = 0,
    attendee_overrides: Optional[List[dict]] = None,
    **kwargs,
) -> dict:
    """CONTRACTED block with one GENERAL sub-block, portal OPEN.

    The GENERAL carve is created already APPROVED by the API, so the block's
    open precondition is satisfied without a controller round trip.
    """
    attendees = attendee_overrides
    if attendees is None:
        attendees = [{} for _ in range(num_attendees)]
    ctx = setup_housing_program(
        contracted_rooms_per_night=contracted_rooms_per_night,
        carves=[{"segment": "GENERAL", "allotted_rooms": general_rooms}],
        open_portal=True,
        attendees=attendees,
        **kwargs,
    )
    ctx["sub_block"] = ctx["sub_blocks"][0]
    return ctx


def setup_open_block_with_reservations(
    stays: List[dict],
    general_rooms: int = 6,
    contracted_rooms_per_night: int = 10,
    attendee_overrides: Optional[List[dict]] = None,
    **kwargs,
) -> dict:
    """OPEN block with one GENERAL sub-block and one delegate per stay.

    `stays` is a list of dicts such as
    ``{"check_in_date": "2026-09-14", "check_out_date": "2026-09-18"}``;
    stay N is booked by delegate N.
    """
    attendees = attendee_overrides or [{} for _ in stays]
    reservations = [
        {
            "attendee": index,
            "sub_block": 0,
            "check_in_date": stay.get("check_in_date"),
            "check_out_date": stay.get("check_out_date"),
            "occupants": stay.get("occupants", 1),
        }
        for index, stay in enumerate(stays)
    ]
    ctx = setup_housing_program(
        contracted_rooms_per_night=contracted_rooms_per_night,
        carves=[{"segment": "GENERAL", "allotted_rooms": general_rooms}],
        open_portal=True,
        attendees=attendees,
        reservations=reservations,
        **kwargs,
    )
    ctx["sub_block"] = ctx["sub_blocks"][0]
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: clock-driven lifecycle shortcuts
# ---------------------------------------------------------------------------


def advance_to_cutoff_and_sweep(ctx: dict) -> dict:
    """Move the clock to the block's cutoff date and run the sweep."""
    set_clock(f"{ctx['block']['cutoff_date']}T00:00:00Z")
    ctx["block"] = cutoff_block(ctx["block"]["id"])
    return ctx


def advance_to_event_end_and_close(ctx: dict) -> dict:
    """Move the clock to the event end date and close the block."""
    set_clock(f"{ctx['event']['event_end_date']}T00:00:00Z")
    ctx["block"] = close_block(ctx["block"]["id"])
    return ctx


def setup_block_at_cutoff(stays: Optional[List[dict]] = None, **kwargs) -> dict:
    """OPEN block with optional reservations, swept to CUTOFF_PASSED."""
    ctx = setup_open_block_with_reservations(stays or [], **kwargs)
    return advance_to_cutoff_and_sweep(ctx)


def setup_closed_block(stays: Optional[List[dict]] = None, **kwargs) -> dict:
    """Block driven all the way to its terminal CLOSED state."""
    ctx = setup_block_at_cutoff(stays, **kwargs)
    return advance_to_event_end_and_close(ctx)


# ---------------------------------------------------------------------------
# Tier 5: settlement and monitoring shortcuts
# ---------------------------------------------------------------------------


def setup_issued_invoice(
    stays: Optional[List[dict]] = None,
    basis: str = "BUREAU_CONFIRMED",
    pickup_reports: Optional[List[dict]] = None,
    **kwargs,
) -> dict:
    """Post-cutoff block with a commission invoice issued on `basis`.

    `pickup_reports` is a list of dicts of pickup-report input fields; they are
    filed while the block is still OPEN, before the cutoff sweep.
    """
    ctx = setup_open_block_with_reservations(stays or [], **kwargs)
    for report in pickup_reports or []:
        file_pickup_report(
            ctx["block"]["id"],
            ctx["hotel"]["id"],
            report["as_of_date"],
            report["reported_rooms_picked_up"],
            report["reported_room_nights"],
            report["reported_gross_revenue_cents"],
        )
    ctx = advance_to_cutoff_and_sweep(ctx)
    ctx["invoice"] = issue_invoice(ctx["block"]["id"], basis)
    return ctx


def setup_paid_invoice(amount_cents: int, **kwargs) -> dict:
    """Issued invoice with `amount_cents` of commission cash already posted."""
    ctx = setup_issued_invoice(**kwargs)
    ctx["invoice"] = pay_invoice(
        ctx["invoice"]["id"], ctx["hotel"]["id"], amount_cents
    )
    return ctx


def setup_disputed_invoice(**kwargs) -> dict:
    """Invoice moved to DISPUTED by the owning hotel."""
    ctx = setup_issued_invoice(**kwargs)
    ctx["invoice"] = dispute_invoice(ctx["invoice"]["id"], ctx["hotel"]["id"])
    return ctx


def setup_pickup_history(
    reports: List[dict], contracted_rooms_per_night: int = 10, **kwargs
) -> dict:
    """CONTRACTED block carrying a series of cumulative pickup reports."""
    ctx = setup_contracted_block(
        contracted_rooms_per_night=contracted_rooms_per_night, **kwargs
    )
    ctx["pickup_reports"] = [
        file_pickup_report(
            ctx["block"]["id"],
            ctx["hotel"]["id"],
            report["as_of_date"],
            report["reported_rooms_picked_up"],
            report["reported_room_nights"],
            report["reported_gross_revenue_cents"],
        )
        for report in reports
    ]
    return ctx


def setup_vendor_with_incidents(
    event_id: str, incidents: List[dict], **vendor_overrides
) -> dict:
    """Rogue vendor carrying the supplied incidents, in creation order.

    Each incident dict carries `attendee_id` plus any of `contact_channel`,
    `occurred_at`, `verified`, `solicited_payment`.
    """
    vendor = record_rogue_vendor(event_id, **vendor_overrides)
    recorded = []
    for incident in incidents:
        recorded.append(
            record_incident(
                vendor["id"],
                incident["attendee_id"],
                contact_channel=incident.get("contact_channel", "EMAIL"),
                occurred_at=incident.get("occurred_at", "2026-07-20T10:00:00Z"),
                verified=incident.get("verified", True),
                **(
                    {"solicited_payment": incident["solicited_payment"]}
                    if "solicited_payment" in incident
                    else {}
                ),
            )
        )
    return {"vendor": vendor, "incidents": recorded}


def setup_flagged_attendee(ctx: dict, attendee_index: int = 0) -> dict:
    """Drive a delegate's warning_count to the housing-risk threshold.

    Records two verified incidents on distinct channels against the delegate
    and confirms the vendor, which issues both warnings.
    """
    attendee = ctx["attendees"][attendee_index]
    vendor_ctx = setup_vendor_with_incidents(
        ctx["event"]["id"],
        [
            {
                "attendee_id": attendee["id"],
                "contact_channel": "EMAIL",
                "occurred_at": "2026-07-20T10:00:00Z",
                "verified": True,
            },
            {
                "attendee_id": attendee["id"],
                "contact_channel": "SMS",
                "occurred_at": "2026-07-22T09:00:00Z",
                "verified": True,
            },
        ],
        detection_source="WEB_MONITORING",
    )
    ctx["vendor"] = confirm_vendor(vendor_ctx["vendor"]["id"])
    ctx["vendor_incidents"] = vendor_ctx["incidents"]
    ctx["attendees"][attendee_index] = get_success_data(
        api_client.get_attendee(attendee["id"], COORDINATOR)
    )
    return ctx


def setup_approved_reduction(ctx: dict, rooms: int = 1, **overrides) -> dict:
    """File and approve one attrition reduction against the context's block."""
    reduction = file_reduction(ctx["block"]["id"], rooms, **overrides)
    ctx["reduction"] = approve_reduction(reduction["id"])
    return ctx
