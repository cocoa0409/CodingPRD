"""CRUD surface, defaults, system-generated fields, not-found / required-field /
type-constraint validation, cross-inn references, append-only ledger immutability,
pagination envelope, and role-based access control.

Covers queue-B entities and rbac corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_inn,
    assert_room,
    assert_booking,
    assert_ledger_entry,
    create_inn_payload,
    create_room_payload,
    create_guest_payload,
    create_booking_payload,
    create_gift_certificate_payload,
    create_tax_remittance_payload,
    TEST_USERS,
    make_guest_headers,
    build_user_headers,
    setup_inn_room_guest,
    create_booking,
)
from test_helpers import api_client
from test_helpers.constants import MISSING_UUID

INNKEEPER = TEST_USERS["innkeeper_headers"]
HOUSEKEEPER = TEST_USERS["housekeeper_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ─── queue B: creation + computed defaults ───────────────────────────────────
def test_create_inn_returns_201_with_declared_defaults(api):
    """PRD §3.1: "An `Innkeeper` stands up an inn as the configuration root by
    supplying its `name` and `lodging_tax_rate_bps`, and optionally a daily
    `checkin_time` (defaulting to `15:00`), a daily `checkout_time` (defaulting to
    `11:00`), a `gift_cert_expiry_days` window (defaulting to 365 days), and a
    `turnover_minutes` buffer (defaulting to 180 minutes, that is three hours).
    Each created inn begins at version 1."

    Design: Corner/entities/create_inn_returns_201_with_computed_defaults
    """
    res = api.create_inn(create_inn_payload(name="Harbor Inn", lodging_tax_rate_bps=1450), INNKEEPER)
    inn = validate_success(res, 201)
    assert_inn(inn)
    assert inn["checkin_time"] == "15:00"
    assert inn["checkout_time"] == "11:00"
    assert inn["gift_cert_expiry_days"] == 365
    assert inn["turnover_minutes"] == 180
    assert inn["version"] == 1


def test_room_default_is_taxable_true(api):
    """PRD §3.1: "its `max_occupancy` headcount (which must be at least 1), and
    optionally `is_taxable` (defaulting to true). A new room is born `ACTIVE` at
    version 1."

    Design: Corner/entities/room_default_is_taxable_true
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="E Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    room = validate_success(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="Def", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER), 201)
    assert room["is_taxable"] is True
    assert room["status"] == "ACTIVE"


def test_booking_system_fields_generated(api):
    """PRD §3.2: "A booking enters the world in `reservation_status` `PENDING` and
    `payment_status` `UNPAID`."
    PRD §2.5: "The `version` is an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation; it underpins optimistic concurrency
    control."

    Design: Corner/entities/booking_system_fields_generated
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "H Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    assert bk["reservation_status"] == "PENDING"
    assert bk["payment_status"] == "UNPAID"
    assert bk["version"] == 1


# ─── queue B: retrieval ──────────────────────────────────────────────────────
def test_get_room_returns_stored_entity(api):
    """PRD §3.1: "Rooms are added under the inn by the innkeeper, who provides the
    room's `name` (its label, such as "Rose Suite", unique within the inn), its
    `base_rate_cents` nightly rack rate (which must be zero or greater), its
    `max_occupancy` headcount (which must be at least 1), and optionally
    `is_taxable` (defaulting to true). A new room is born `ACTIVE` at version 1."

    Design: Corner/entities/get_room_returns_stored_entity
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="A Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    created = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="R1", base_rate_cents=12345,
                                       max_occupancy=4), INNKEEPER))
    fetched = validate_success(api.get_room(inn["id"], created["id"], INNKEEPER), 200)
    assert fetched["base_rate_cents"] == 12345
    assert fetched["max_occupancy"] == 4
    assert fetched["status"] == "ACTIVE"
    assert_room(fetched)


# ─── queue B: listing pagination ─────────────────────────────────────────────
def test_list_rooms_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_rooms_paginated_envelope
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="B Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="R1", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER))
    get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="R2", base_rate_cents=11000,
                                       max_occupancy=2), INNKEEPER))
    data, meta = validate_paginated(api.list_rooms(inn["id"], INNKEEPER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── queue B: not found ──────────────────────────────────────────────────────
def test_get_nonexistent_room_returns_not_found(api):
    """PRD §2.9: "When a path carries several identifiers, the server validates
    them left to right and rejects the request with `ERR_NOT_FOUND` at the first
    identifier that does not resolve within the inn scope, before evaluating any
    deeper resource or business rule."

    Design: Corner/entities/get_room_nonexistent_returns_not_found
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="C Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    res = api.get_room(inn["id"], MISSING_UUID, INNKEEPER)
    validate_error(res, "ERR_NOT_FOUND")


# ─── queue B: required field ─────────────────────────────────────────────────
def test_create_room_missing_base_rate_returns_invalid_request(api):
    """PRD §2.9: "Then request-body well-formedness — required fields present,
    enum values legal, dates parseable, and integers non-negative where
    constrained (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_room_missing_required_field_returns_invalid_request
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="D Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    payload = {"inn_id": inn["id"], "name": "NoRate", "max_occupancy": 2}  # base_rate_cents omitted
    res = api.create_room(inn["id"], payload, INNKEEPER)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── queue B: type/enum constraint ───────────────────────────────────────────
def test_booking_invalid_channel_enum_rejected(api):
    """PRD §2.9: "Then request-body well-formedness — required fields present,
    enum values legal, dates parseable, and integers non-negative where
    constrained (`ERR_INVALID_REQUEST`)."
    PRD §3.2: "an optional `package_id`, and the booking `channel`, which is
    either `DIRECT` (booked through the inn) or `OTA` (booked through an online
    travel agency)."

    Design: Corner/entities/booking_invalid_channel_enum_rejected
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "I Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    res = api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-05-10",
                               "2026-05-12", channel="WALKIN", guest_count=1),
        INNKEEPER)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── queue B: cross-inn reference ────────────────────────────────────────────
def test_booking_cross_inn_room_reference_rejected(api):
    """PRD §3.2: "Every foreign key — `room_id`, `guest_id`, `package_id` — must
    belong to the same inn as the path, failing which the request is
    `ERR_CROSS_INN_REFERENCE`."

    Design: Corner/entities/booking_cross_inn_room_reference_rejected
    """
    inn_a = get_success_data(api.create_inn(
        create_inn_payload(name="Inn A", lodging_tax_rate_bps=0), INNKEEPER))
    inn_b = get_success_data(api.create_inn(
        create_inn_payload(name="Inn B", lodging_tax_rate_bps=0), INNKEEPER))
    room_a = get_success_data(api.create_room(
        inn_a["id"], create_room_payload(inn_a["id"], name="G", base_rate_cents=10000,
                                         max_occupancy=2), INNKEEPER))
    guest_b = get_success_data(api.create_guest(
        inn_b["id"], create_guest_payload(inn_b["id"], full_name="X G", email="xg@x.com"), INNKEEPER))
    res = api.create_booking(
        inn_b["id"],
        create_booking_payload(inn_b["id"], room_a["id"], guest_b["id"], "2026-05-10",
                               "2026-05-12", channel="DIRECT", guest_count=1),
        INNKEEPER)
    validate_error(res, "ERR_CROSS_INN_REFERENCE")


# ─── queue B: append-only ledger immutability ────────────────────────────────
def test_payment_ledger_entry_is_append_only(api):
    """PRD §2.5: "A `PaymentLedgerEntry` is append-only: it likewise carries only
    `id` and `created_at`, is never updated after it is written, and exposes no
    `updated_at` or `version` field."
    PRD §3.3: "A valid redemption appends a positive `REDEMPTION` ledger entry
    that records the drawing certificate in its `gift_certificate_id`, debits the
    certificate's `remaining_cents` by the redeemed amount, increments the
    certificate's `version`, recomputes `deposit_paid_cents`, and — if the debit
    drives `remaining_cents` to exactly 0 — moves the certificate to `DEPLETED`."

    Design: Corner/entities/payment_ledger_entry_immutable_no_version
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "J Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 20000), FINANCE))
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 10000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    data, meta = validate_paginated(api.list_booking_ledger(inn["id"], bk["id"], FINANCE))
    assert meta["total_count"] == 1
    entry = data[0]
    assert entry["source_kind"] == "REDEMPTION"
    assert entry["amount_cents"] == 10000
    assert "updated_at" not in entry, "ledger entry must not expose updated_at"
    assert "version" not in entry, "ledger entry must not expose version"
    assert_ledger_entry(entry)


# ─── queue B: RBAC ───────────────────────────────────────────────────────────
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_inn(create_inn_payload(name="NoAuth", lodging_tax_rate_bps=0), {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_guest_cannot_create_room(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/guest_cannot_create_room
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Ff Inn", lodging_tax_rate_bps=0), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Ss G", email="ssg@x.com"), INNKEEPER))
    res = api.create_room(
        inn["id"],
        create_room_payload(inn["id"], name="Sneaky", base_rate_cents=10000, max_occupancy=2),
        make_guest_headers(guest["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_guest_cannot_cancel_other_guests_booking(api):
    """PRD §2.1: "a guest-driven booking action (confirming, cancelling,
    redeeming a gift toward, or requesting a refund quote for a booking)
    performed by a guest who is not the owner is rejected with
    `ERR_NOT_BOOKING_OWNER`."

    Design: Corner/rbac/guest_cannot_cancel_other_guests_booking
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Gg Inn", lodging_tax_rate_bps=0), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="G", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER))
    guest_a = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Owner", email="own@x.com"), INNKEEPER))
    guest_b = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Intruder", email="intr@x.com"), INNKEEPER))
    bk = get_success_data(api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest_a["id"], "2026-05-10",
                               "2026-05-12", channel="DIRECT", guest_count=1),
        make_guest_headers(guest_a["id"])))
    res = api.cancel_booking(inn["id"], bk["id"], make_guest_headers(guest_b["id"]))
    validate_error(res, "ERR_NOT_BOOKING_OWNER")
    after = get_success_data(api.get_booking(inn["id"], bk["id"], INNKEEPER))
    assert after["reservation_status"] == "PENDING"


def test_housekeeper_cannot_open_remittance(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/housekeeper_cannot_open_remittance
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Hh Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    res = api.create_tax_remittance(
        inn["id"],
        create_tax_remittance_payload(inn["id"], "2026-05-01", "2026-05-31", "FINAL"),
        HOUSEKEEPER)
    validate_error(res, "ERR_FORBIDDEN")
