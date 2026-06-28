"""Booking-gate tests (§2.8, §2.9, §3.4).

Booking is the busiest gate. These tests pin the deterministic precedence
(OCC before standing-order safety), the unit-authorization boundary, the
deposit-activation boundary, cross-entity state dependencies (plan must be
`ACTIVE`; standing order must be `SIGNED`), and the inclusive/exclusive temporal
boundaries for lot expiry and standing-order validity.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_provider_headers,
    make_clinic_admin_headers,
    setup_active_plan,
    setup_proposed_plan,
    book_session,
    plan_version,
    make_standing_order,
    revoke_standing_order,
    post_deposit,
    set_clock,
    create_treatment_session_payload,
)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_stale_plan_version_beats_inactive_standing_order(api):
    """PRD §2.8: "... sixth, the optimistic-concurrency version check (§2.9);
    seventh, the target resource's source-state requirement for the requested
    transition ...; and only then the domain-specific safety, compliance, and
    fiscal checks described in §3." PRD §3.4: "The plan must be `ACTIVE` (otherwise
    `ERR_PLAN_NOT_ACTIVE`), and `expected_treatment_plan_version` must match the
    plan's current version (otherwise `ERR_STALE_PLAN_VERSION`, HTTP 412 — see
    §2.9). The standing order must be active, meaning its `status` is `SIGNED` and the
    logical clock is strictly before its `valid_until_utc` (otherwise
    `ERR_STANDING_ORDER_INACTIVE`)."

    A booking carrying a stale plan version AND a `REVOKED` order returns the
    higher-precedence `ERR_STALE_PLAN_VERSION` (412), not `ERR_STANDING_ORDER_INACTIVE`.

    Design: Difficulty/priority_pair_validation_conflict/occ_state_beats_standing_order_safety_on_booking
    """
    sc = setup_active_plan(planned_sessions=2, planned_units_per_session=20,
                           max_units_authorized=30, lot_units=100)
    inj = sc.injector_id
    # A valid SIGNED order to advance the plan version via a real booking.
    ok_order = make_standing_order(sc.consultation_id, sc.director_id, product="BOTOX",
                                   max_units_authorized=30)["id"]
    stale_v = sc.plan_version
    book_session(sc.plan_id, ok_order, inj, sc.lot_id, 20, stale_v)  # advances version
    # Revoke the original order so it is inactive.
    order = validate_success(api.get_standing_order(
        sc.standing_order_id, make_provider_headers(sc.director_id)))
    revoke_standing_order(sc.standing_order_id, order["version"], sc.director_id)
    # Book again with the now-STALE version AND the REVOKED order.
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, inj, sc.lot_id, 20, stale_v)
    resp = api.create_treatment_session(payload, make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value)


def test_stale_plan_version_returns_412_status(api):
    """PRD §2.9: "Such a booking is rejected with `ERR_STALE_PLAN_VERSION` (HTTP
    412), forcing the client to refresh before retrying rather than reserve
    against a plan state it never saw." PRD §3.4: "and `expected_treatment_plan_version`
    must match the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION`, HTTP
    412 — see §2.9)."

    The stale-version booking returns HTTP 412 (auto-checked against the error map).

    Design: Difficulty/priority_pair_validation_conflict/occ_state_beats_standing_order_safety_on_booking
    """
    sc = setup_active_plan(planned_sessions=2, planned_units_per_session=20,
                           max_units_authorized=30, lot_units=100)
    inj = sc.injector_id
    stale_v = sc.plan_version
    book_session(sc.plan_id, sc.standing_order_id, inj, sc.lot_id, 20, stale_v)
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, inj, sc.lot_id, 20, stale_v)
    resp = api.create_treatment_session(payload, make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value, expected_status=412)


# ---------------------------------------------------------------------------
# boundary_precision_check: units vs max_units_authorized
# ---------------------------------------------------------------------------
def test_planned_units_at_max_authorized_books(api):
    """PRD §3.4: "The `planned_units` must not exceed the standing order's
    `max_units_authorized` (otherwise `ERR_UNITS_EXCEED_ORDER`)."

    With `max_units_authorized`=30, `planned_units`=30 books successfully (`BOOKED`).

    Design: Difficulty/boundary_precision_check/units_at_max_authorized_books_units_over_rejects
    """
    sc = setup_active_plan(planned_sessions=2, planned_units_per_session=30,
                           max_units_authorized=30, lot_units=100)
    session = book_session(sc.plan_id, sc.standing_order_id, sc.injector_id,
                           sc.lot_id, 30, sc.plan_version)
    assert session["status"] == "BOOKED", (
        f"planned_units==max should book, got {session['status']}")


def test_planned_units_over_max_authorized_rejected(api):
    """PRD §3.4: "The `planned_units` must not exceed the standing order's
    `max_units_authorized` (otherwise `ERR_UNITS_EXCEED_ORDER`)."

    With `max_units_authorized`=30, `planned_units`=31 is rejected
    `ERR_UNITS_EXCEED_ORDER` (422).

    Design: Difficulty/boundary_precision_check/units_at_max_authorized_books_units_over_rejects
    """
    sc = setup_active_plan(planned_sessions=2, planned_units_per_session=30,
                           max_units_authorized=30, lot_units=100)
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id, 31, sc.plan_version)
    resp = api.create_treatment_session(payload, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_UNITS_EXCEED_ORDER.value)


# ---------------------------------------------------------------------------
# boundary_precision_check: deposit vs required_deposit
# ---------------------------------------------------------------------------
def test_deposit_at_required_activates_plan(api):
    """PRD §3.3: "Activation is permitted only when the plan is in `PROPOSED`
    (otherwise `ERR_PLAN_NOT_PROPOSED`), when `expected_treatment_plan_version`
    matches the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION`),
    when the referenced consultation is in `EXAM_COMPLETE` (otherwise
    `ERR_NO_GOOD_FAITH_EXAM`), and when `deposit_paid_cents` is at least
    `required_deposit_cents` (otherwise `ERR_DEPOSIT_REQUIRED`)."

    `required_deposit_cents`=10000, `deposit_paid_cents`=10000 activates (`ACTIVE`).

    Design: Difficulty/boundary_precision_check/deposit_at_required_activates_deposit_short_rejects
    """
    sc = setup_active_plan(required_deposit_cents=10000)
    plan = validate_success(api.get_treatment_plan(
        sc.plan_id, make_provider_headers(sc.injector_id)))
    assert plan["status"] == "ACTIVE", (
        f"deposit at exactly required should activate, got {plan['status']}")


def test_deposit_short_of_required_rejects_activation(api):
    """PRD §3.3: "... and when `deposit_paid_cents` is at least
    `required_deposit_cents` (otherwise `ERR_DEPOSIT_REQUIRED`)." PRD §3.3: "A
    `ClinicAdmin` posts a `Deposit` by supplying the `treatment_plan_id` it funds and
    the `amount_cents` (greater than 0), along with `expected_treatment_plan_version`.
    A posted deposit begins with `status` of `POSTED`; posting it adds its
    `amount_cents` to the plan's `deposit_paid_cents` and increments the plan's
    version by 1."

    `required_deposit_cents`=10000 funded to only 9999 is rejected
    `ERR_DEPOSIT_REQUIRED` (402).

    Design: Difficulty/boundary_precision_check/deposit_at_required_activates_deposit_short_rejects
    """
    sc = setup_proposed_plan(required_deposit_cents=10000)
    inj = sc.injector_id
    # Post 9999 (short) against the proposed plan.
    post_deposit(sc.plan_id, 9999, sc.plan_version)
    pv = plan_version(sc.plan_id, inj)
    resp = api.activate_plan(sc.plan_id, {"expected_treatment_plan_version": pv},
                             make_provider_headers(inj))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_REQUIRED.value)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_booking_requires_plan_active(api):
    """PRD §3.4: "Booking is the system's busiest gate, and its preconditions
    apply in this order. The plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`),
    and `expected_treatment_plan_version` must match the plan's current version
    (otherwise `ERR_STALE_PLAN_VERSION`, HTTP 412 — see §2.9)."

    Booking against a still-`PROPOSED` plan is rejected `ERR_PLAN_NOT_ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/session_booking_requires_plan_active
    """
    sc = setup_proposed_plan()
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id, 20, sc.plan_version)
    resp = api.create_treatment_session(payload, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


def test_booking_succeeds_once_plan_active(api):
    """PRD §3.4: "The plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) ..."
    PRD §3.3: "Activating a plan advances it from `PROPOSED` to `ACTIVE`."

    Once the plan is `ACTIVE` the same booking succeeds (`BOOKED`).

    Design: Difficulty/cross_entity_state_dependency/session_booking_requires_plan_active
    """
    sc = setup_active_plan()
    session = book_session(sc.plan_id, sc.standing_order_id, sc.injector_id,
                           sc.lot_id, 20, sc.plan_version)
    assert session["status"] == "BOOKED", (
        f"booking against ACTIVE plan should succeed, got {session['status']}")


def test_booking_requires_standing_order_signed(api):
    """PRD §3.4: "The standing order must be active, meaning its `status` is `SIGNED`
    and the logical clock is strictly before its `valid_until_utc` (otherwise
    `ERR_STANDING_ORDER_INACTIVE`)." PRD §3.2: "Revoking an order sets `status` to
    `REVOKED`; a `REVOKED` order can authorize no further sessions."

    Booking against a `REVOKED` standing order is rejected `ERR_STANDING_ORDER_INACTIVE`,
    independent of the plan being `ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/session_booking_requires_standing_order_signed
    """
    sc = setup_active_plan()
    order = validate_success(api.get_standing_order(
        sc.standing_order_id, make_provider_headers(sc.director_id)))
    revoke_standing_order(sc.standing_order_id, order["version"], sc.director_id)
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id, 20, sc.plan_version)
    resp = api.create_treatment_session(payload, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_STANDING_ORDER_INACTIVE.value)


def test_booking_with_signed_order_succeeds(api):
    """PRD §3.2: "The order is created with `status` of `SIGNED`. An order is active
    only while its `status` is `SIGNED` and the logical clock is strictly before its
    `valid_until_utc`." PRD §3.4: "The standing order must be active, meaning its
    `status` is `SIGNED` and the logical clock is strictly before its `valid_until_utc`
    (otherwise `ERR_STANDING_ORDER_INACTIVE`)."

    A `SIGNED`, unexpired order permits booking (`BOOKED`).

    Design: Difficulty/cross_entity_state_dependency/session_booking_requires_standing_order_signed
    """
    sc = setup_active_plan()
    session = book_session(sc.plan_id, sc.standing_order_id, sc.injector_id,
                           sc.lot_id, 20, sc.plan_version)
    assert session["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_lot_expiry_inclusive_boundary_excludes_lot(api):
    """PRD §3.1: "A lot is treated as expired once the logical clock reaches or
    passes its `expiration_date`." PRD §3.4: "there must be enough inventory: the
    sum of `remaining_units` across all `AVAILABLE`, non-expired lots of the plan's
    product must be at least `planned_units` (otherwise `ERR_INSUFFICIENT_LOT_UNITS`)."

    With clock set to exactly the lot's `expiration_date`, the only lot is expired,
    so FEFO finds no eligible units and booking fails `ERR_INSUFFICIENT_LOT_UNITS`.

    Design: Difficulty/resource_temporal_overlap/lot_expiry_inclusive_boundary_excludes_lot
    """
    sc = setup_active_plan(lot_expiration="2026-06-01T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id, 20, sc.plan_version)
    resp = api.create_treatment_session(payload, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_UNITS.value)


def test_lot_one_second_before_expiry_still_eligible(api):
    """PRD §3.1: "A lot is treated as expired once the logical clock reaches or
    passes its `expiration_date`." PRD §3.4: "the sum of `remaining_units` across all
    `AVAILABLE`, non-expired lots of the plan's product must be at least
    `planned_units` (otherwise `ERR_INSUFFICIENT_LOT_UNITS`)."

    With clock strictly before the lot's `expiration_date`, the lot is non-expired
    and booking succeeds (`BOOKED`).

    Design: Difficulty/resource_temporal_overlap/lot_expiry_inclusive_boundary_excludes_lot
    """
    sc = setup_active_plan(lot_expiration="2026-06-01T00:00:00Z")
    set_clock("2026-05-31T23:59:59Z")
    session = book_session(sc.plan_id, sc.standing_order_id, sc.injector_id,
                           sc.lot_id, 20, sc.plan_version)
    assert session["status"] == "BOOKED", (
        f"lot before expiry should be eligible, got {session['status']}")


def test_standing_order_validity_exclusive_end_boundary(api):
    """PRD §3.2: "An order is active only while its `status` is `SIGNED` and the
    logical clock is strictly before its `valid_until_utc`." PRD §3.4: "The standing
    order must be active, meaning its `status` is `SIGNED` and the logical clock is
    strictly before its `valid_until_utc` (otherwise `ERR_STANDING_ORDER_INACTIVE`)."

    With clock set to exactly the order's `valid_until_utc`, the order is inactive
    (validity is half-open with exclusive end) and booking fails
    `ERR_STANDING_ORDER_INACTIVE`, even with a non-expired lot.

    Design: Difficulty/resource_temporal_overlap/standing_order_validity_exclusive_end_boundary
    """
    sc = setup_active_plan(valid_until_utc="2026-06-01T00:00:00Z",
                           lot_expiration="2026-12-01T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")
    payload = create_treatment_session_payload(
        sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id, 20, sc.plan_version)
    resp = api.create_treatment_session(payload, make_provider_headers(sc.injector_id))
    validate_error(resp, ApiErrorId.ERR_STANDING_ORDER_INACTIVE.value)


def test_standing_order_one_second_before_end_still_active(api):
    """PRD §3.2: "An order is active only while its `status` is `SIGNED` and the
    logical clock is strictly before its `valid_until_utc`." PRD §3.4: "The standing
    order must be active, meaning its `status` is `SIGNED` and the logical clock is
    strictly before its `valid_until_utc` (otherwise `ERR_STANDING_ORDER_INACTIVE`)."

    With clock strictly before `valid_until_utc` the order is active and booking
    succeeds (`BOOKED`).

    Design: Difficulty/resource_temporal_overlap/standing_order_validity_exclusive_end_boundary
    """
    sc = setup_active_plan(valid_until_utc="2026-06-01T00:00:00Z",
                           lot_expiration="2026-12-01T00:00:00Z")
    set_clock("2026-05-31T23:59:59Z")
    session = book_session(sc.plan_id, sc.standing_order_id, sc.injector_id,
                           sc.lot_id, 20, sc.plan_version)
    assert session["status"] == "BOOKED", (
        f"order before valid_until should be active, got {session['status']}")
