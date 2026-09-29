"""
Composable state builders for the Prepaid Restaurant Ticketing API.

Every test starts against an empty database, so all preconditions have to be
built from scratch through declared endpoints only. The builders below are
layered:

* tier 1 — single entities: restaurant, guest, table, package, add-on,
  service, ticket class;
* tier 2 — the entity hierarchy a sale needs: a published service carrying one
  ticket class (:func:`build_world`);
* tier 3 — reservations at each point of the seating and money dimensions:
  held, deposit-paid, confirmed, fully paid, table-assigned, seated,
  completed;
* tier 4 — accumulation and threshold targeting: add-on lines, dietary notes,
  waitlist entries, release runs;
* tier 5 — finalisation and terminal states: cancelled and settled
  reservations, filed and adjudicated refund exceptions, issued and redeemed
  goodwill credits.

Each builder returns the resource dictionary the API answered with, and the
tier-2+ builders return a plain dict whose keys name the resources they made,
so a test can reach any of them.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    ADMIN_HEADERS,
    CARE_DECIDER_HEADERS,
    CARE_FILER_HEADERS,
    CARE_ISSUER_HEADERS,
    make_guest_headers,
    make_kitchen_headers,
    make_restaurant_headers,
)

# The instant the recurring scenario pins its clock to before anything else
# happens. It is strictly before every seating instant used below, so no hold,
# offer, cutoff or release window has lapsed at setup time.
SETUP_CLOCK = "2026-09-01T00:00:00Z"


# ─── logical clock ────────────────────────────────────────────────────────


def set_clock(api: ApiClient, current_utc: str) -> None:
    """Set the logical clock. "setting the clock mutates no entity and triggers
    no sweep, offer expiry or automatic transition of any kind"."""
    get_success_data(api.set_clock(current_utc, ADMIN_HEADERS))


def reset_clock(api: ApiClient) -> None:
    """Return the logical clock to the instant it reads before any request."""
    set_clock(api, CLOCK_EPOCH)


# ─── tier 1: single entities ──────────────────────────────────────────────


def create_restaurant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_restaurant(F.restaurant_payload(**overrides), ADMIN_HEADERS)
    )


def create_guest(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_guest(F.guest_payload(**overrides), ADMIN_HEADERS)
    )


def create_guests(api: ApiClient, count: int, **overrides: Any) -> List[Dict[str, Any]]:
    return [create_guest(api, **overrides) for _ in range(count)]


def create_table(
    api: ApiClient, restaurant_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_table(
            F.table_payload(restaurant_id, **overrides),
            make_restaurant_headers(restaurant_id),
        )
    )


def create_package(
    api: ApiClient, restaurant_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_package(
            F.package_payload(restaurant_id, **overrides),
            make_restaurant_headers(restaurant_id),
        )
    )


def create_add_on(
    api: ApiClient, restaurant_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_add_on(
            F.add_on_payload(restaurant_id, **overrides),
            make_restaurant_headers(restaurant_id),
        )
    )


def create_service(
    api: ApiClient, restaurant_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A service is born in status DRAFT."""
    return get_success_data(
        api.create_service(
            F.service_payload(restaurant_id, **overrides),
            make_restaurant_headers(restaurant_id),
        )
    )


def create_ticket_class(
    api: ApiClient,
    restaurant_id: str,
    service_id: str,
    package_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Allocating a class requires the owning service to still be DRAFT."""
    return get_success_data(
        api.create_ticket_class(
            F.ticket_class_payload(service_id, package_id, **overrides),
            make_restaurant_headers(restaurant_id),
        )
    )


def publish_service(
    api: ApiClient, restaurant_id: str, service_id: str
) -> Dict[str, Any]:
    """Move a DRAFT service to PUBLISHED, "opening its ticket classes for
    sale"."""
    return get_success_data(
        api.publish_service(service_id, make_restaurant_headers(restaurant_id))
    )


# ─── reads ────────────────────────────────────────────────────────────────


def read_ticket_class(
    api: ApiClient, ticket_class_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.get_ticket_class(ticket_class_id, headers))


def ticket_class_version(
    api: ApiClient, ticket_class_id: str, headers: Dict[str, str]
) -> int:
    """The version a reservation create must echo back."""
    return read_ticket_class(api, ticket_class_id, headers)["version"]


def read_reservation(
    api: ApiClient, reservation_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.get_reservation(reservation_id, headers))


def reservation_version(
    api: ApiClient, reservation_id: str, headers: Dict[str, str]
) -> int:
    """The version an add-on line append must echo back."""
    return read_reservation(api, reservation_id, headers)["version"]


def read_service(
    api: ApiClient, service_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.get_service(service_id, headers))


def read_guest(
    api: ApiClient, guest_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.get_guest(guest_id, headers))


def read_credit(
    api: ApiClient, credit_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.get_goodwill_credit(credit_id, headers))


def credit_version(
    api: ApiClient, credit_id: str, headers: Dict[str, str]
) -> int:
    """The version a goodwill redemption must echo back."""
    return read_credit(api, credit_id, headers)["version"]


def read_waitlist_entry(
    api: ApiClient, entry_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.get_waitlist_entry(entry_id, headers))


def read_note(
    api: ApiClient, note_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.get_dietary_note(note_id, headers))


def ledger_rows(
    api: ApiClient, reservation_id: str, headers: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Every ledger row of one reservation, in ascending created_at order."""
    response = api.list_payment_transactions(
        headers, {"reservation_id": reservation_id, "limit": 100}
    )
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"listing the ledger failed with HTTP {response.status_code}: "
        f"{response.text}"
    )
    return body["data"]


# ─── tier 2: the entity hierarchy a sale needs ────────────────────────────


def build_world(
    api: ApiClient,
    *,
    clock: Optional[str] = SETUP_CLOCK,
    restaurant: Optional[Dict[str, Any]] = None,
    package: Optional[Dict[str, Any]] = None,
    service: Optional[Dict[str, Any]] = None,
    ticket_class: Optional[Dict[str, Any]] = None,
    publish: bool = True,
    guests: int = 1,
) -> Dict[str, Any]:
    """A published service carrying one ticket class, plus its guests.

    ``restaurant``, ``package``, ``service`` and ``ticket_class`` are override
    dictionaries merged into the corresponding creation payloads.
    """
    if clock is not None:
        set_clock(api, clock)
    rest = create_restaurant(api, **(restaurant or {}))
    pkg = create_package(api, rest["id"], **(package or {}))
    svc = create_service(api, rest["id"], **(service or {}))
    tc = create_ticket_class(
        api, rest["id"], svc["id"], pkg["id"], **(ticket_class or {})
    )
    if publish:
        svc = publish_service(api, rest["id"], svc["id"])
        tc = read_ticket_class(api, tc["id"], make_restaurant_headers(rest["id"]))
    guest_rows = create_guests(api, guests)
    world = {
        "restaurant": rest,
        "restaurant_id": rest["id"],
        "package": pkg,
        "package_id": pkg["id"],
        "service": svc,
        "service_id": svc["id"],
        "ticket_class": tc,
        "ticket_class_id": tc["id"],
        "guests": guest_rows,
        "guest": guest_rows[0] if guest_rows else None,
        "guest_id": guest_rows[0]["id"] if guest_rows else None,
        "manager_headers": make_restaurant_headers(rest["id"]),
        "kitchen_headers": make_kitchen_headers(rest["id"]),
        "seating_start_utc": svc["seating_start_utc"],
    }
    return world


# ─── tier 3: reservations along both dimensions ───────────────────────────


def hold_seats(
    api: ApiClient,
    ticket_class_id: str,
    guest_id: str,
    *,
    party_size: int = 2,
    primary_guest_name: str = "Primary Guest",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a PENDING, UNPAID reservation, echoing the class's live
    version."""
    headers = make_guest_headers(guest_id)
    version = ticket_class_version(api, ticket_class_id, headers)
    payload = F.reservation_payload(
        ticket_class_id,
        guest_id,
        version,
        party_size=party_size,
        primary_guest_name=primary_guest_name,
        **overrides,
    )
    return get_success_data(api.create_reservation(payload, headers))


def pay(
    api: ApiClient, reservation_id: str, guest_id: str, amount_cents: int
) -> Dict[str, Any]:
    """Take one payment as the owning guest."""
    return get_success_data(
        api.take_payment(
            reservation_id,
            F.payment_payload(amount_cents),
            make_guest_headers(guest_id),
        )
    )


def pay_deposit(
    api: ApiClient, reservation_id: str, guest_id: str
) -> Dict[str, Any]:
    """Pay exactly the reservation's deposit_due_cents."""
    headers = make_guest_headers(guest_id)
    reservation = read_reservation(api, reservation_id, headers)
    return pay(api, reservation_id, guest_id, reservation["deposit_due_cents"])


def pay_in_full(
    api: ApiClient, reservation_id: str, guest_id: str
) -> Dict[str, Any]:
    """Pay the whole outstanding balance in one go."""
    headers = make_guest_headers(guest_id)
    reservation = read_reservation(api, reservation_id, headers)
    return pay(api, reservation_id, guest_id, reservation["balance_due_cents"])


def confirm(api: ApiClient, reservation_id: str, guest_id: str) -> Dict[str, Any]:
    """Turn a paid hold into a real booking."""
    return get_success_data(
        api.confirm_reservation(reservation_id, make_guest_headers(guest_id))
    )


def deposit_paid_reservation(
    api: ApiClient,
    ticket_class_id: str,
    guest_id: str,
    *,
    party_size: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """A PENDING hold whose deposit has settled — DEPOSIT_PAID."""
    reservation = hold_seats(
        api, ticket_class_id, guest_id, party_size=party_size, **overrides
    )
    pay_deposit(api, reservation["id"], guest_id)
    return read_reservation(api, reservation["id"], make_guest_headers(guest_id))


def confirmed_reservation(
    api: ApiClient,
    ticket_class_id: str,
    guest_id: str,
    *,
    party_size: int = 2,
    pay_full: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """A CONFIRMED reservation, deposit-paid by default or fully paid."""
    reservation = hold_seats(
        api, ticket_class_id, guest_id, party_size=party_size, **overrides
    )
    if pay_full:
        pay_in_full(api, reservation["id"], guest_id)
    else:
        pay_deposit(api, reservation["id"], guest_id)
    confirm(api, reservation["id"], guest_id)
    return read_reservation(api, reservation["id"], make_guest_headers(guest_id))


def fully_paid_reservation(
    api: ApiClient,
    ticket_class_id: str,
    guest_id: str,
    *,
    party_size: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """A CONFIRMED and FULLY_PAID reservation, which is what completion and
    transfer both require."""
    reservation = hold_seats(
        api, ticket_class_id, guest_id, party_size=party_size, **overrides
    )
    pay_in_full(api, reservation["id"], guest_id)
    confirm(api, reservation["id"], guest_id)
    return read_reservation(api, reservation["id"], make_guest_headers(guest_id))


def assign_table(
    api: ApiClient,
    restaurant_id: str,
    reservation_id: str,
    table_id: str,
    seat_from_utc: str,
) -> Dict[str, Any]:
    return get_success_data(
        api.assign_table(
            reservation_id,
            F.assign_table_payload(table_id, seat_from_utc),
            make_restaurant_headers(restaurant_id),
        )
    )


def seat(api: ApiClient, restaurant_id: str, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.seat_reservation(reservation_id, make_restaurant_headers(restaurant_id))
    )


def complete(
    api: ApiClient, restaurant_id: str, reservation_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_reservation(
            reservation_id, make_restaurant_headers(restaurant_id)
        )
    )


def seated_reservation(
    api: ApiClient,
    world: Dict[str, Any],
    guest_id: str,
    *,
    party_size: int = 2,
    table: Optional[Dict[str, Any]] = None,
    seat_from_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """A SEATED, FULLY_PAID reservation on a table of the same restaurant.

    Seating "requires ... the logical clock to have reached seat_from_utc", so
    the clock is advanced to the seating instant before the seat call.
    """
    restaurant_id = world["restaurant_id"]
    tbl = table or create_table(api, restaurant_id)
    reservation = fully_paid_reservation(
        api, world["ticket_class_id"], guest_id, party_size=party_size
    )
    instant = seat_from_utc or world["service"]["seating_start_utc"]
    assign_table(api, restaurant_id, reservation["id"], tbl["id"], instant)
    set_clock(api, instant)
    seat(api, restaurant_id, reservation["id"])
    reservation = read_reservation(
        api, reservation["id"], make_guest_headers(guest_id)
    )
    reservation["_table"] = tbl
    return reservation


# ─── tier 4: accumulation and threshold targeting ─────────────────────────


def append_add_on_line(
    api: ApiClient,
    reservation_id: str,
    guest_id: str,
    add_on_id: str,
    qty: int = 1,
) -> Dict[str, Any]:
    """Append one add-on line, echoing the reservation's live version."""
    headers = make_guest_headers(guest_id)
    version = reservation_version(api, reservation_id, headers)
    return get_success_data(
        api.append_add_on_line(
            reservation_id,
            F.add_on_line_payload(add_on_id, version, qty=qty),
            headers,
        )
    )


def add_dietary_note(
    api: ApiClient,
    reservation_id: str,
    guest_id: str,
    *,
    guest_index: int = 1,
    severity: str = "ALLERGY",
    restriction_code: str = "NUT",
    note_text: str = "No nuts of any kind.",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_dietary_note(
            reservation_id,
            F.dietary_note_payload(
                guest_index=guest_index,
                severity=severity,
                restriction_code=restriction_code,
                note_text=note_text,
            ),
            make_guest_headers(guest_id),
        )
    )


def ack_note(api: ApiClient, restaurant_id: str, note_id: str) -> Dict[str, Any]:
    """Accept a note, which moves it PENDING -> ACKED."""
    return get_success_data(
        api.ack_dietary_note(
            note_id, F.ack_payload("ACCEPT"), make_kitchen_headers(restaurant_id)
        )
    )


def reject_note(
    api: ApiClient,
    restaurant_id: str,
    note_id: str,
    reject_reason_code: str = "CROSS_CONTAMINATION_RISK",
) -> Dict[str, Any]:
    """Prep-reject a note, which moves it PENDING -> PREP_REJECTED."""
    return get_success_data(
        api.ack_dietary_note(
            note_id,
            F.reject_payload(reject_reason_code),
            make_kitchen_headers(restaurant_id),
        )
    )


def amend_note(
    api: ApiClient, note_id: str, guest_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Amend a prep-rejected note, which moves it PREP_REJECTED -> PENDING."""
    return get_success_data(
        api.amend_dietary_note(
            note_id, F.amend_payload(**overrides), make_guest_headers(guest_id)
        )
    )


def acked_anaphylaxis_note(
    api: ApiClient,
    restaurant_id: str,
    reservation_id: str,
    guest_id: str,
    *,
    guest_index: int = 1,
) -> Dict[str, Any]:
    """An ANAPHYLAXIS note already ACKED, which is what unblocks assignment and
    seating."""
    note = add_dietary_note(
        api,
        reservation_id,
        guest_id,
        guest_index=guest_index,
        severity="ANAPHYLAXIS",
        restriction_code="SHELLFISH",
    )
    return ack_note(api, restaurant_id, note["id"])


def join_waitlist(
    api: ApiClient,
    service_id: str,
    guest_id: str,
    *,
    party_size: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """A new WAITING entry with offer_round at 0."""
    return get_success_data(
        api.create_waitlist_entry(
            F.waitlist_entry_payload(
                service_id, guest_id, party_size=party_size, **overrides
            ),
            make_guest_headers(guest_id),
        )
    )


def claim_offer(api: ApiClient, entry_id: str, guest_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.claim_waitlist_entry(entry_id, make_guest_headers(guest_id))
    )


def withdraw_entry(api: ApiClient, entry_id: str, guest_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.withdraw_waitlist_entry(entry_id, make_guest_headers(guest_id))
    )


def run_release(api: ApiClient, restaurant_id: str, service_id: str) -> Dict[str, Any]:
    """Fire a release run, which is legal only once the release window has
    opened."""
    return get_success_data(
        api.release_run(service_id, make_restaurant_headers(restaurant_id))
    )


def sweep_holds(
    api: ApiClient, service_id: str, *, close_service: bool = False
) -> Dict[str, Any]:
    """Run the PlatformAdmin hold sweep, optionally closing the service."""
    return get_success_data(
        api.hold_sweep(service_id, ADMIN_HEADERS, {"close_service": close_service})
    )


def sold_out_class(
    api: ApiClient, world: Dict[str, Any], guest_id: str, party_size: int
) -> Dict[str, Any]:
    """Consume the whole allocation of the world's class with one confirmed
    booking, so the precedence ladder lands the class on SOLD_OUT."""
    confirmed_reservation(
        api, world["ticket_class_id"], guest_id, party_size=party_size
    )
    return read_ticket_class(api, world["ticket_class_id"], world["manager_headers"])


# ─── tier 5: settlement, adjudication and goodwill ─────────────────────────


def cancel(
    api: ApiClient, reservation_id: str, guest_id: str
) -> Dict[str, Any]:
    """Cancel as the holding guest, which runs the settlement procedure."""
    return get_success_data(
        api.cancel_reservation(reservation_id, make_guest_headers(guest_id))
    )


def declare_no_show(
    api: ApiClient, restaurant_id: str, reservation_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.declare_no_show(reservation_id, make_restaurant_headers(restaurant_id))
    )


def settled_cancelled_reservation(
    api: ApiClient,
    world: Dict[str, Any],
    guest_id: str,
    *,
    party_size: int = 2,
    cancel_at: str,
    pay_full: bool = False,
) -> Dict[str, Any]:
    """A CONFIRMED reservation cancelled at a pinned instant, so its
    forfeited_cents and refunded_cents are settled."""
    reservation = confirmed_reservation(
        api,
        world["ticket_class_id"],
        guest_id,
        party_size=party_size,
        pay_full=pay_full,
    )
    set_clock(api, cancel_at)
    cancel(api, reservation["id"], guest_id)
    return read_reservation(api, reservation["id"], make_guest_headers(guest_id))


def file_refund_exception(
    api: ApiClient,
    reservation_id: str,
    requested_cents: int,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File an exception. The acting X-User-ID is recorded as
    requested_by_user_id and is thereafter barred from deciding it."""
    return get_success_data(
        api.create_refund_exception(
            F.refund_exception_payload(reservation_id, requested_cents, **overrides),
            headers or CARE_FILER_HEADERS,
        )
    )


def decide_refund_exception(
    api: ApiClient,
    exception_id: str,
    *,
    decision: str = "APPROVED",
    approved_cents: Optional[int] = None,
    decision_note_code: str = "POLICY_EXCEPTION",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adjudicate an exception with an operator distinct from the filer."""
    return get_success_data(
        api.decide_refund_exception(
            exception_id,
            F.decide_payload(
                decision=decision,
                approved_cents=approved_cents,
                decision_note_code=decision_note_code,
            ),
            headers or CARE_DECIDER_HEADERS,
        )
    )


def approved_exception_with_shortfall(
    api: ApiClient,
    reservation_id: str,
    requested_cents: int,
    approved_cents: int,
) -> Dict[str, Any]:
    """An APPROVED exception whose shortfall_cents is above 0, which is the
    precondition for issuing a compensating credit."""
    exception = file_refund_exception(api, reservation_id, requested_cents)
    return decide_refund_exception(
        api,
        exception["id"],
        decision="APPROVED",
        approved_cents=approved_cents,
        decision_note_code="PARTIAL_GOODWILL",
    )


def issue_goodwill_credit(
    api: ApiClient,
    refund_exception_id: str,
    issued_cents: int,
    expires_at_utc: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Issue a credit with an operator distinct from the decider."""
    return get_success_data(
        api.create_goodwill_credit(
            F.goodwill_credit_payload(
                refund_exception_id, issued_cents, expires_at_utc
            ),
            headers or CARE_ISSUER_HEADERS,
        )
    )


def redeem_goodwill_credit(
    api: ApiClient,
    credit_id: str,
    reservation_id: str,
    amount_cents: int,
    *,
    guest_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Redeem part or all of a credit, echoing the credit's live version."""
    acting = headers or (
        make_guest_headers(guest_id) if guest_id else CARE_ISSUER_HEADERS
    )
    version = credit_version(api, credit_id, acting)
    return get_success_data(
        api.redeem_goodwill_credit(
            credit_id,
            F.redemption_payload(reservation_id, amount_cents, version),
            acting,
        )
    )


def revoke_goodwill_credit(
    api: ApiClient, credit_id: str, *, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Revoke a credit with an operator distinct from the issuer."""
    from .test_users import CARE_REVOKER_HEADERS

    return get_success_data(
        api.revoke_goodwill_credit(credit_id, headers or CARE_REVOKER_HEADERS)
    )
