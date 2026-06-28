"""Optimistic-concurrency guards, the immediate-consistency contract, RBAC
denials, not-found errors, and remaining entity/endpoint breadth (creation
defaults, immutability, listing, filtered reads, sender-role derivation).

Depth (queue A): none (this file is corner-design breadth only).
Breadth (queue B): cross_cutting_complexity_layers, consistency_model, rbac,
errors, entities, endpoints sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, api_client,
    set_clock, create_trainer, create_client, submit_intake, assess_client,
    create_assessed_client,
    setup_session_pack_engagement, setup_subscription_engagement,
    setup_pack_engagement,
    create_pack, get_pack, book_pack_session,
    create_published_program,
    create_engagement_payload, create_client_payload, create_trainer_payload,
    create_booking_payload, create_message_payload, create_habit_log_payload,
    make_trainer_headers, make_client_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Corner: cross_cutting / occ_engagement_create_stale_client_version ──────

def test_engagement_create_stale_client_version_rejected(api):
    """PRD §2.7: "When creating an engagement, the request must carry
    `expected_client_version` holding the `version` of the target `Client` as last
    observed. If the client's current `version` has advanced ... the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Creating an engagement with expected_client_version one below the assessed
    client's current version returns ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_engagement_create_stale_client_version
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    client = create_assessed_client(t_id)
    stale_version = client["version"] - 1
    resp = api.create_engagement(
        create_engagement_payload(client["id"], stale_version, billing_model="SESSION_PACK"),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ─── Corner: cross_cutting / occ_booking_create_stale_pack_version ───────────

def test_booking_create_stale_pack_version_rejected(api):
    """PRD §2.7: "When booking a session against a session pack, the request must
    carry `expected_session_pack_version` holding the `version` of the target
    `SessionPack` as the client last observed it. If the pack's current `version`
    has advanced since then ... the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)"

    A second booking reusing the pack's create-time version (after a prior booking
    bumped it) returns ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_booking_create_stale_pack_version
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    stale_version = pack["version"]
    book_pack_session(t_id, e_id, pack["id"], stale_version,
                      "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    resp = api.create_booking(
        create_booking_payload(e_id, "2026-06-12T10:00:00Z", "2026-06-12T11:00:00Z",
                               session_pack_id=pack["id"],
                               expected_session_pack_version=stale_version),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ─── Corner: cross_cutting / occ_version_increments_on_pack_mutation ─────────

def test_booking_increments_pack_version_by_one(api):
    """PRD §3.4: "For a `SESSION_PACK` booking the pack's `sessions_committed` is
    incremented, the pack's `version` is incremented by one"
    PRD §2.4: "`version` starts at the initial value and increments by one on each
    mutation"

    A successful seat-committing booking takes the pack version from 1 to 2 and
    drops sessions_remaining to 4.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_pack_mutation
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    assert pack["version"] == 1
    book_pack_session(t_id, e_id, pack["id"], pack["version"],
                      "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["version"] == 2, f"got {refreshed['version']}"
    assert refreshed["sessions_remaining"] == 4


# ─── Corner: consistency_model / immediate_visibility_of_pack_seat_change ────

def test_booking_response_reflects_decremented_seats_immediately(api):
    """PRD §2.9: "When a pack seat is committed or released, the pack's seat counts
    and lifecycle status are recomputed"
    PRD §1: "the system computes them deterministically and keeps them immediately
    consistent."

    The booking-create flow leaves the pack's sessions_remaining at 4 with no read
    lag; the booking itself is BOOKED.

    Design: Corner/consistency_model/immediate_visibility_of_pack_seat_change
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    resp = api.create_booking(
        create_booking_payload(e_id, "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z",
                               session_pack_id=pack["id"],
                               expected_session_pack_version=pack["version"]),
        make_trainer_headers(t_id))
    booking = validate_success(resp, 201)
    assert booking["status"] == "BOOKED"
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["sessions_remaining"] == 4


# ─── Corner: rbac / client_cannot_assess_intake ──────────────────────────────

def test_client_cannot_assess_intake(api):
    """PRD §2.1: "When a caller presents a syntactically valid role but is not
    permitted to perform the requested operation — or is an ownership-bound role
    attempting to act on a resource it does not own — the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    A Client calling the Trainer-exclusive assess endpoint is rejected
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/client_cannot_assess_intake
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    client = create_client(t_id)
    submit_intake(client["id"])
    resp = api.assess_client(client["id"], make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── Corner: rbac / trainer_cannot_create_trainer ────────────────────────────

def test_trainer_cannot_register_trainer(api):
    """PRD §2.1: "the `PlatformAdmin` is an operational actor who registers
    trainers"
    PRD §4: the `POST /trainers` row authorizes only `PlatformAdmin`.

    A Trainer calling the PlatformAdmin-exclusive POST /trainers is rejected
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/trainer_cannot_create_trainer
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    resp = api.create_trainer(create_trainer_payload(), make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── Corner: errors / engagement_not_found_on_session_pack_create ────────────

def test_session_pack_under_missing_engagement_returns_not_found(api):
    """PRD §2.5: "a request under a missing engagement fails with
    `ERR_ENGAGEMENT_NOT_FOUND` before its children are examined."

    Purchasing a pack under a non-existent engagement id returns
    ERR_ENGAGEMENT_NOT_FOUND.

    Design: Corner/errors/engagement_not_found_on_session_pack_create
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    from test_helpers import create_session_pack_payload
    resp = api.create_session_pack(
        "00000000-0000-4000-8000-0000000000ee",
        create_session_pack_payload(total_sessions=5, price_cents=50000),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value)


# ─── Corner: entities / create_trainer_returns_201_with_system_fields ────────

def test_create_trainer_returns_201_active_version_one(api):
    """PRD §3.1: "A registered trainer begins with `status` of `ACTIVE`; the
    alternative `status` value is `DEACTIVATED`."
    PRD §2.4: "`version` starts at the initial value and increments by one on each
    mutation"

    POST /trainers returns 201 with status ACTIVE and version 1.

    Design: Corner/entities/create_trainer_returns_201_with_system_fields
    """
    set_clock("2026-06-01T00:00:00Z")
    resp = api.create_trainer(create_trainer_payload(full_name="Alex"), ADMIN)
    trainer = validate_success(resp, 201)
    assert trainer["status"] == "ACTIVE"
    assert trainer["version"] == 1


# ─── Corner: entities / get_client_not_found_returns_404 ─────────────────────

def test_get_client_not_found_returns_404(api):
    """PRD §2.5: "A request that names a missing client fails with
    `ERR_CLIENT_NOT_FOUND` before any nested engagement, booking, or check-in is
    consulted"

    GET /clients/{id} on a non-existent UUID returns ERR_CLIENT_NOT_FOUND.

    Design: Corner/entities/get_client_not_found_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    resp = api.get_client("00000000-0000-4000-8000-000000000000",
                          make_trainer_headers(trainer["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


# ─── Corner: entities / create_client_missing_required_sex_returns_422 ───────

def test_create_client_missing_sex_returns_422(api):
    """PRD §2.6: "the request body itself is validated for well-formedness —
    required fields present, enum values within range ... with any breach raising
    `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.1: "the client's `sex` (either `MALE` or `FEMALE`, which selects the
    metabolic constant used later for nutrition math)"

    POST /clients omitting the required sex field returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_client_missing_required_sex_returns_422
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    payload = create_client_payload(t_id)
    payload.pop("sex")
    resp = api.create_client(payload, make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner: entities / create_session_pack_nonpositive_total_returns_422 ────

def test_create_session_pack_zero_total_returns_422(api):
    """PRD §2.6: "numeric fields that must be positive (`total_sessions`,
    `price_cents`, `weight_kg`, `planned_workouts_per_week`, `habit_checks_target`)
    strictly greater than zero ... with any breach raising `ERR_INVALID_REQUEST`
    (HTTP 422)."

    POST session-pack with total_sessions=0 violates the >0 rule -> 422.

    Design: Corner/entities/create_session_pack_nonpositive_total_returns_422
    """
    ctx = setup_session_pack_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    from test_helpers import create_session_pack_payload
    resp = api.create_session_pack(
        e_id, create_session_pack_payload(total_sessions=0, price_cents=10000),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner: entities / trainer_default_timezone_applied ─────────────────────

def test_trainer_default_timezone_is_utc(api):
    """PRD §3.1: "an optional `timezone` (defaulting to `UTC` and used only to
    display booking windows — every stored instant is UTC regardless)."

    POST /trainers without a timezone applies the default 'UTC'.

    Design: Corner/entities/trainer_default_timezone_applied
    """
    resp = api.create_trainer(create_trainer_payload(full_name="Dee"), ADMIN)
    trainer = validate_success(resp, 201)
    assert trainer["timezone"] == "UTC"


# ─── Corner: entities / habit_log_immutable_no_version_field ─────────────────

def test_habit_log_has_no_version_field(api):
    """PRD §2.4: "the `HabitLog` and the `Message`. Each of these carries only an
    `id` (a UUID, no prefix) and a `created_at` timestamp. They have no
    `updated_at` and no `version` field, because they are never modified after they
    are written."

    A created HabitLog carries id + created_at but no version (append-only).

    Design: Corner/entities/habit_log_immutable_no_version_field
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    program = create_published_program(t_id, e_id)
    resp = api.create_habit_log(
        create_habit_log_payload(e_id, program["id"], "HABIT_CHECK", "2026-06-02T07:00:00Z"),
        make_client_headers(c_id))
    hl = validate_success(resp, 201)
    assert "version" not in hl, "HabitLog must not carry a version field"
    assert "updated_at" not in hl, "HabitLog must not carry an updated_at field"


# ─── Corner: entities / list_clients_pagination_envelope ─────────────────────

def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "Every list response includes the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    GET /clients?limit=1 over a trainer with two clients reports total_count 2 and
    has_more true.

    Design: Corner/entities/list_clients_pagination_envelope
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    create_client(t_id, full_name="C1")
    create_client(t_id, full_name="C2")
    resp = api.list_clients(make_trainer_headers(t_id),
                            params={"trainer_id": t_id, "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert meta["has_more"] is True


# ─── Corner: endpoints / get_bookings_filtered_by_engagement ─────────────────

def test_list_bookings_filtered_by_engagement(api):
    """PRD §4: the `GET /bookings` row lists bookings, "filter by `engagement_id`,
    `session_pack_id`, `trainer_id`, or `rescheduled_from_booking_id`".

    GET /bookings?engagement_id returns that engagement's one booking as an array.

    Design: Corner/endpoints/get_bookings_filtered_by_engagement
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    book_pack_session(t_id, e_id, pack["id"], pack["version"],
                      "2026-06-20T10:00:00Z", "2026-06-20T11:00:00Z")
    resp = api.list_bookings(make_trainer_headers(t_id), params={"engagement_id": e_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"got {meta['total_count']}"


# ─── Corner: endpoints / message_sender_role_derived_from_caller ─────────────

def test_message_sender_role_derived_from_client_caller(api):
    """PRD §3.8: "A `Message` is an append-only record naming the `engagement_id`
    and a non-empty `body`; its `sender_role` is set by the system from the
    caller's role to either `TRAINER` or `CLIENT`, never supplied by the client."

    Posting a message as the Client stamps sender_role CLIENT (server-derived).

    Design: Corner/endpoints/message_sender_role_derived_from_caller
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    c_id, e_id = ctx["client"]["id"], ctx["engagement"]["id"]
    resp = api.create_message(create_message_payload(e_id, body="Hi coach"),
                              make_client_headers(c_id))
    msg = validate_success(resp, 201)
    assert msg["sender_role"] == "CLIENT"
