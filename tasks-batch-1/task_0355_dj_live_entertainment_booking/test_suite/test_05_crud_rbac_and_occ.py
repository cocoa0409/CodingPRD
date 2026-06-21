"""Resource creation, required-field/enum/FK validation, immutability, listing
(reverse-reachability), RBAC, and optimistic-concurrency on the booking aggregate.

Covers the corner entities, endpoints, rbac, and cross_cutting OCC sections.
PRD §2.1, §2.3, §2.4, §2.6, §2.7, §3.1, §3.2, §3.3.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_performer, assert_blackout_window, fixtures as fx,
)
from test_helpers.test_users import make_client_headers

AGENT = fx.AGENT
ADMIN = fx.ADMIN


# =====================================================================
# Corner/entities
# =====================================================================
def test_create_performer_returns_201_with_system_fields(api):
    """PRD §3.2: "The `availability_status` begins `AVAILABLE`"
    PRD §3.2: "The `reliability_score` starts at 100"
    PRD §2.4: "an integer `version` that begins at 1 and increments by exactly 1 on
    every mutation."

    Design: Corner/entities/create_performer_returns_201_with_all_fields
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    resp = api.create_performer(
        fx.F.create_performer_payload(home_zone_id=zhome["id"]), ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_performer(data)
    assert data["stage_name"] == "DJ A"
    assert data["availability_status"] == "AVAILABLE"
    assert data["reliability_score"] == 100
    assert data["version"] == 1


def test_get_nonexistent_booking_returns_not_found(api):
    """PRD §2.6: "the first one that does not resolve to an existing row yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    resp = api.get_booking("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_booking_missing_event_start_rejected(api):
    """PRD §2.8: "Next is generic request well-formedness — required fields present,
    correct types, valid enum values, integers within their declared bounds
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_booking_missing_required_field_returns_invalid_request
    """
    cat = fx.setup_home_catalogue()
    resp = api.create_booking(
        {"client_id": cat["cli_id"], "performer_id": cat["perf_id"],
         "package_id": cat["pkg_id"], "event_zone_id": cat["zhome_id"],
         "event_miles_from_home": 0},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_booking_defaults_contracted_minutes_from_package(api):
    """PRD §3.3: "If `contracted_set_minutes` is omitted, it defaults to the chosen
    package's `included_set_minutes`"

    Design: Corner/entities/create_booking_default_contracted_minutes_from_package
    """
    cat = fx.setup_home_catalogue()
    resp = api.create_booking(
        {"client_id": cat["cli_id"], "performer_id": cat["perf_id"],
         "package_id": cat["pkg_id"], "event_zone_id": cat["zhome_id"],
         "event_start_utc": "2026-08-01T20:00:00Z", "event_miles_from_home": 0},
        AGENT,
    )
    data = validate_success(resp, expected_status=201)
    assert data["contracted_set_minutes"] == 120, data["contracted_set_minutes"]


def test_create_booking_status_inquiry_and_quote_zero(api):
    """PRD §3.3: "A freshly created booking enters the `INQUIRY` state with its
    `active_performer_id` unset."
    PRD §3.4: "The provisional grand total, stored on the booking as
    `quote_total_cents`, is assembled at the moment of the hold"

    Design: Corner/entities/create_booking_computed_status_ignores_input
    """
    cat = fx.setup_home_catalogue()
    resp = api.create_booking(
        {"client_id": cat["cli_id"], "performer_id": cat["perf_id"],
         "package_id": cat["pkg_id"], "event_zone_id": cat["zhome_id"],
         "event_start_utc": "2026-08-01T20:00:00Z", "event_miles_from_home": 0,
         "contracted_set_minutes": 120},
        AGENT,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "INQUIRY", data["status"]
    assert data["quote_total_cents"] == 0, data["quote_total_cents"]


def test_create_performer_invalid_act_type_rejected(api):
    """PRD §3.2: "an `act_type` that is one of `DJ`, `BAND`, `SOLO_MUSICIAN`, `EMCEE`,
    or `DUO`"

    Design: Corner/entities/create_performer_invalid_enum_act_type_rejected
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    resp = api.create_performer(
        {"stage_name": "X", "act_type": "ORCHESTRA", "genre": "HOUSE",
         "home_zone_id": zhome["id"], "base_set_rate_cents": 200000,
         "overtime_rate_cents_per_15min": 3000},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_blackout_window_carries_only_id_and_created_at(api):
    """PRD §2.4: "The `BlackoutWindow` entity is the sole exception: it is immutable
    once created and therefore carries only `id` and `created_at` — it has neither an
    `updated_at` field nor a `version` field."

    Design: Corner/entities/blackout_window_immutable_only_id_created_at
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    perf = fx.create_performer(zhome["id"])
    resp = api.create_blackout(
        perf["id"],
        {"start_utc": "2026-08-01T10:00:00Z", "end_utc": "2026-08-01T14:00:00Z"},
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_blackout_window(data)


def test_create_performer_unknown_zone_rejected(api):
    """PRD §2.6: "when a create request carries foreign-key references in its body —
    such as `client_id`, `performer_id`, `package_id`, `event_zone_id`, `booking_id`,
    or `candidate_performer_id` — each such reference must resolve to an existing row;
    if any does not, the request is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/foreign_key_performer_unknown_zone_rejected
    """
    resp = api.create_performer(
        {"stage_name": "DJ A", "act_type": "DJ", "genre": "HOUSE",
         "home_zone_id": "00000000-0000-4000-8000-000000000000",
         "base_set_rate_cents": 200000, "overtime_rate_cents_per_15min": 3000},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value)


def test_list_bookings_returns_paginated_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` in its `meta` object, where `total_count` is the count of all matching
    rows before the page window is applied and `has_more` indicates whether rows remain
    beyond the current page."

    Design: Corner/entities/list_bookings_pagination_envelope
    """
    cat = fx.setup_home_catalogue()
    fx.create_booking(cat, event_zone_id=cat["zhome_id"],
                      event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    resp = api.list_bookings(AGENT, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


# =====================================================================
# Corner/endpoints (FK reverse-reachability listings)
# =====================================================================
def test_list_equipment_for_package(api):
    """PRD §4: "GET | `/packages/{id}/equipment` | List equipment items for a package"
    PRD §3.1: "Equipment line items hang off a package. Each is created against a
    package and carries that package's identity in its `package_id`"

    Design: Corner/endpoints/list_equipment_for_package_reverse_reachability
    """
    pkg = fx.create_package()
    fx.add_equipment(pkg["id"], category="SOUND", label="PA", unit_fee_cents=30000)
    resp = api.list_equipment(pkg["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


def test_list_payments_for_booking(api):
    """PRD §4: "GET | `/bookings/{id}/payments` | List payment records for a booking"
    PRD §3.6: "A payment is authorized against a booking by supplying the `booking_id`"

    Design: Corner/endpoints/list_payments_for_booking_reverse_reachability
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    fx.create_payment(held["id"], kind="DEPOSIT", amount_cents=62500)
    resp = api.list_payments(held["id"], AGENT)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


def test_list_backups_by_candidate(api):
    """PRD §4: "GET | `/backup-assignments` | List backup assignments filterable by
    candidate and booking"
    PRD §3.11: "The agent offers a backup slot to a candidate by supplying the
    booking's `booking_id`, the `candidate_performer_id`, and an operator-assigned
    `rank` (at least 1)"

    Design: Corner/endpoints/list_backups_by_candidate_reverse_reachability
    """
    cat = fx.setup_home_catalogue()
    backup = fx.create_performer(cat["zhome_id"], stage_name="Backup", base_set_rate_cents=180000)
    cat2, held = fx.create_held_booking(cat, contracted_set_minutes=120)
    fx.offer_backup(held["id"], backup["id"], rank=1)

    resp = api.list_backup_assignments(AGENT, params={"candidate_performer_id": backup["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


def test_list_blackouts_for_performer(api):
    """PRD §4: "GET | `/performers/{id}/blackouts` | List blackout windows for a
    performer"
    PRD §3.2: "A blackout window names the `performer_id` it applies to"

    Design: Corner/endpoints/list_blackouts_for_performer_reverse_reachability
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    perf = fx.create_performer(zhome["id"])
    fx.create_blackout(perf["id"], start_utc="2026-08-01T10:00:00Z",
                       end_utc="2026-08-01T14:00:00Z")
    resp = api.list_blackouts(perf["id"], AGENT)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


def test_list_contracts_for_booking(api):
    """PRD §4: "GET | `/bookings/{id}/contracts` | List contract documents for a
    booking"
    PRD §3.5: "Each contract document records the `booking_id` it covers."

    Design: Corner/endpoints/list_contracts_for_booking_reverse_reachability
    """
    cat, bk, ct_id = fx.create_contract_sent_booking(contracted_set_minutes=120)
    resp = api.list_contracts(bk["id"], AGENT)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


def test_list_song_requests_for_booking(api):
    """PRD §4: "GET | `/bookings/{id}/song-requests` | List song requests for a
    booking"
    PRD §3.10: "Each entry names the booking it belongs to via `booking_id`"

    Design: Corner/endpoints/list_songrequests_for_booking_reverse_reachability
    """
    cat = fx.setup_home_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zhome_id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    fx.add_song_request(bk["id"], cat["cli_id"], title="Song", artist="Artist",
                        list_type="REQUEST", priority=5)
    resp = api.list_song_requests(bk["id"], AGENT)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


def test_filter_bookings_by_active_performer(api):
    """PRD §4: "GET | `/bookings` | List bookings with filters"
    PRD §3.3: "records `active_performer_id` as the originally booked `performer_id`"

    Design: Corner/endpoints/filter_bookings_by_active_performer_reverse_reachability
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    resp = api.list_bookings(AGENT, params={"active_performer_id": cat["perf_id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


# =====================================================================
# Corner/rbac
# =====================================================================
def test_client_cannot_create_booking_forbidden(api):
    """PRD §4: "POST | `/bookings` | Create a booking inquiry | BookingAgent"
    PRD §2.1: "When a recognised role calls an endpoint it is not permitted to use,
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/client_cannot_create_booking_forbidden
    """
    cat = fx.setup_home_catalogue()
    resp = api.create_booking(
        {"client_id": cat["cli_id"], "performer_id": cat["perf_id"],
         "package_id": cat["pkg_id"], "event_zone_id": cat["zhome_id"],
         "event_start_utc": "2026-08-01T20:00:00Z", "event_miles_from_home": 0,
         "contracted_set_minutes": 120},
        make_client_headers(cat["cli_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_client_cannot_sign_other_clients_contract(api):
    """PRD §2.1: "A client may only sign or decline a contract, request a revision,
    add a song entry, pay, capture, or cancel on a booking whose `client_id` equals
    `X-User-ID`; signing another client's contract, for example, is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/client_cannot_sign_other_clients_contract_not_owner
    """
    cat = fx.setup_home_catalogue()
    other_client = fx.create_client(full_name="Client B")
    cat2, bk, ct_id = fx.create_contract_sent_booking(cat, contracted_set_minutes=120)

    resp = api.sign_contract(ct_id, make_client_headers(other_client["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    four recognised roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api._request(
        "GET", "/bookings/00000000-0000-4000-8000-000000000000",
        headers={"X-User-ID": "x", "X-User-Role": "Intruder"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =====================================================================
# Corner/cross_cutting_complexity_layers (OCC)
# =====================================================================
def test_stale_issue_contract_rejected(api):
    """PRD §2.7: "Issuing or re-issuing a contract requires the caller to supply
    `expected_booking_version` in the request body, carrying the `version` of the
    booking the caller last observed. If `expected_booking_version` does not equal the
    booking's current `version`, the request is rejected with
    `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_issue_contract_rejected
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    stale_version = held["version"]
    # First issue-contract succeeds and advances the booking version.
    fx.issue_contract(held["id"], stale_version)
    # Client requests a revision -> NEGOTIATING (version advances again).
    fx.get_success_data(api.request_revision(held["id"], make_client_headers(cat["cli_id"])))

    resp = api.issue_contract(held["id"], stale_version, AGENT)
    validate_error(resp, ApiErrorId.ERR_STALE_BOOKING_VERSION.value)


def test_issue_contract_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "Issuing or re-issuing a contract requires the caller to supply
    `expected_booking_version` in the request body, carrying the `version` of the
    booking the caller last observed."
    PRD §3.5: "Issuing from `HOLD` creates a `ContractDocument` at `revision` 1 with
    `status` `ISSUED`, snapshots the current quote into the contract's
    `quoted_total_cents`, and moves the booking from `HOLD` to `CONTRACT_SENT`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_issue_contract_succeeds
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    resp = api.issue_contract(held["id"], held["version"], AGENT)
    data = validate_success(resp)
    assert data["status"] == "CONTRACT_SENT", data["status"]
    assert data["version"] == held["version"] + 1, data["version"]
