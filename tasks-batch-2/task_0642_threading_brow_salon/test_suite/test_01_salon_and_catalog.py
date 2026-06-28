"""Salon creation, catalog/member registration, defaults, duplicates, and the
salon open/close lifecycle including version + occupancy reconciliation.

Covers corner-design queue B instances under sections `entities`, `state_machines`
(Salon), and `cross_cutting_complexity_layers` (derived version/occupancy).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_salon_payload,
    create_member_payload,
    create_loyalty_adjustment_payload,
    assert_salon,
    assert_member,
    assert_loyalty_ledger_entry,
)
import test_helpers as th

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ===========================================================================
# Entity creation, defaults, computed fields, uniqueness
# ===========================================================================
def test_create_salon_returns_201_with_system_fields(api):
    """PRD §3.1: "A freshly created salon starts in the `CLOSED` state with an
    `active_occupancy_count` of 0 and a `version` of 1."

    Design: Corner/entities/create_salon_returns_201_with_system_fields
    """
    resp = api.create_salon(create_salon_payload(name="Brow Bar"), MANAGER)
    data = validate_success(resp, expected_status=201)
    assert_salon(data)
    assert data["status"] == "CLOSED", f"expected CLOSED, got {data['status']}"
    assert data["active_occupancy_count"] == 0
    assert data["version"] == 1


def test_get_salon_not_found(api):
    """PRD §2.6: "The first identifier in the path that does not resolve produces
    its corresponding not-found error — `ERR_SALON_NOT_FOUND` ... before the system
    looks any deeper."

    Design: Corner/entities/get_salon_not_found
    """
    resp = api.get_salon(th.NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_SALON_NOT_FOUND.value, expected_status=404)


def test_create_salon_missing_required_field_returns_validation(api):
    """PRD §2.7: "Where a request schema is itself malformed — a required field
    missing, a wrong type, or a value that is negative or zero where a positive
    number is required — the request is rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_salon_missing_required_field_returns_validation
    """
    payload = create_salon_payload()
    payload.pop("license_number")
    resp = api.create_salon(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_salon_default_loyalty_earn_rate_applied(api):
    """PRD §3.1: "may optionally set the `loyalty_earn_rate_bps`; when omitted that
    rate defaults to 500, meaning five loyalty points are earned per finalized dollar."

    Design: Corner/entities/salon_default_loyalty_earn_rate_applied
    """
    payload = create_salon_payload()
    payload.pop("loyalty_earn_rate_bps", None)
    data = validate_success(api.create_salon(payload, MANAGER), expected_status=201)
    assert data["loyalty_earn_rate_bps"] == 500


def test_list_salons_pagination_envelope(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_salons_pagination_envelope
    """
    validate_success(api.create_salon(create_salon_payload(name="S1"), MANAGER), 201)
    validate_success(api.create_salon(create_salon_payload(name="S2"), MANAGER), 201)
    resp = api.list_salons(MANAGER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected 2 salons, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1


def test_member_loyalty_balance_computed_input_ignored(api):
    """PRD §3.1: "A new member starts `ACTIVE` with a `loyalty_balance` of 0 and
    `no_show_strikes` of 0."

    Design: Corner/entities/member_loyalty_balance_computed_input_ignored
    """
    salon = validate_success(api.create_salon(create_salon_payload(), MANAGER), 201)
    resp = api.create_member(create_member_payload(salon["id"]), FRONT_DESK)
    member = validate_success(resp, expected_status=201)
    assert_member(member)
    assert member["loyalty_balance"] == 0
    assert member["no_show_strikes"] == 0
    assert member["status"] == "ACTIVE"


def test_duplicate_member_phone_within_salon_rejected(api):
    """PRD §3.1: "Any attempt to create a `Member` with a `phone` ... that already
    exists within the same salon is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_member_phone_within_salon_rejected
    """
    salon = validate_success(api.create_salon(create_salon_payload(), MANAGER), 201)
    validate_success(
        api.create_member(create_member_payload(salon["id"], phone="555-DUP"), FRONT_DESK),
        201,
    )
    resp = api.create_member(
        create_member_payload(salon["id"], phone="555-DUP", full_name="B"), FRONT_DESK
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, expected_status=409)


def test_loyalty_ledger_entry_immutable_no_version(api):
    """PRD §2.4: "The one exception is the `LoyaltyLedgerEntry`, which is an
    append-only event record: it carries only `id` and `created_at`, and has neither
    an `updated_at` field nor a `version` field."
    PRD §3.7: "A `SalonManager` may also adjust a member's loyalty manually, granting
    or deducting points; this writes an `ADJUSTMENT` ledger entry carrying the signed
    `points` and the member's `loyalty_balance` is recomputed."

    Design: Corner/entities/loyalty_ledger_entry_immutable_no_version
    """
    salon = validate_success(api.create_salon(create_salon_payload(), MANAGER), 201)
    member = validate_success(
        api.create_member(create_member_payload(salon["id"]), FRONT_DESK), 201
    )
    resp = api.create_loyalty_adjustment(
        member["id"], create_loyalty_adjustment_payload(50), MANAGER
    )
    entry = validate_success(resp, expected_status=201)
    assert_loyalty_ledger_entry(entry)
    assert entry["entry_type"] == "ADJUSTMENT"
    assert entry["points"] == 50
    reread = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert reread["loyalty_balance"] == 50


# ===========================================================================
# Salon state machine: initial state, open transition, license precondition
# ===========================================================================
def test_open_salon_initial_state_closed(api):
    """PRD §3.1: "A freshly created salon starts in the `CLOSED` state with an
    `active_occupancy_count` of 0 and a `version` of 1."

    Design: Corner/state_machines/open_salon_initial_state_closed
    """
    salon = validate_success(api.create_salon(create_salon_payload(), MANAGER), 201)
    assert salon["status"] == "CLOSED"


def test_open_salon_valid_transition_bumps_version(api):
    """PRD §3.2: "A successful open increments `Salon.version` by one and unlocks
    queue and seating operations."

    Design: Corner/state_machines/open_salon_valid_transition_bumps_version
    """
    salon = validate_success(api.create_salon(create_salon_payload(), MANAGER), 201)
    resp = api.open_salon(
        salon["id"], {"expected_salon_version": salon["version"]}, MANAGER
    )
    opened = validate_success(resp)
    assert opened["status"] == "OPEN"
    assert opened["version"] == 2, f"expected version 2 after open, got {opened['version']}"


def test_open_salon_with_lapsed_license_rejected(api):
    """PRD §3.2: "Opening is permitted only when the license is current — the logical
    clock must be strictly earlier than `license_expiry` ... — otherwise the open is
    refused with `ERR_LICENSE_LAPSED`."

    Design: Corner/state_machines/open_salon_with_lapsed_license_rejected
    """
    salon = validate_success(
        api.create_salon(
            create_salon_payload(license_expiry="2026-01-15T00:00:00Z"), MANAGER
        ),
        201,
    )
    validate_success(api.set_clock("2026-02-01T00:00:00Z", MANAGER))
    resp = api.open_salon(
        salon["id"], {"expected_salon_version": salon["version"]}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_LAPSED.value, expected_status=403)


def test_close_salon_cancels_waiting_tickets_cascade(api):
    """PRD §3.2: "When the salon does close, every queue ticket still `WAITING` or
    `CALLED` is cascaded to `CANCELLED`, clearing the floor, and `Salon.version` is
    incremented by one."

    Design: Corner/state_machines/close_salon_cancels_waiting_tickets_cascade
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_queue(salon["id"], member["id"], svc["id"])
    # Re-read live salon version (open bumped it); close requires no occupied chairs.
    resp = api.close_salon(
        salon["id"], {"expected_salon_version": salon["version"]}, MANAGER
    )
    closed = validate_success(resp)
    assert closed["status"] == "CLOSED"
    reread = validate_success(api.get_queue_ticket(ticket["id"], FRONT_DESK))
    assert reread["status"] == "CANCELLED"


def test_close_salon_with_active_visit_rejected(api):
    """PRD §3.2: "A salon may only close when no chair is currently occupied, that is
    when `active_occupancy_count` equals zero; a close attempted while a guest is still
    in a chair is rejected with `ERR_SALON_HAS_ACTIVE_VISITS`."

    Design: Corner/state_machines/close_salon_with_active_visit_rejected
    """
    s = th.setup_seated_visit()
    salon, visit = s["salon"], s["visit"]
    # Salon occupancy is now 1 (a guest is seated). Use the live version.
    live = validate_success(api.get_salon(salon["id"], MANAGER))
    assert live["active_occupancy_count"] == 1
    resp = api.close_salon(
        salon["id"], {"expected_salon_version": live["version"]}, MANAGER
    )
    validate_error(
        resp, ApiErrorId.ERR_SALON_HAS_ACTIVE_VISITS.value, expected_status=409
    )


# ===========================================================================
# Cross-cutting: derived salon version + occupancy on seating
# ===========================================================================
def test_occ_version_increments_on_each_seating(api):
    """PRD §2.9: "every successful seating, every freeing of a chair on completion or
    void, and every open or close increments `Salon.version` by one."
    PRD §3.4: "the salon's `active_occupancy_count` rises by one; and `Salon.version`
    is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_seating
    """
    base = th.setup_open_salon_basic()
    salon, chair, tech, svc, member = (
        base["salon"], base["chair"], base["tech"], base["svc"], base["member"]
    )
    # salon was opened (version 2). Seat one guest -> version 3, occupancy 1.
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"])
    reread = validate_success(api.get_salon(salon["id"], MANAGER))
    assert reread["version"] == 3, f"expected version 3, got {reread['version']}"
    assert reread["active_occupancy_count"] == 1
