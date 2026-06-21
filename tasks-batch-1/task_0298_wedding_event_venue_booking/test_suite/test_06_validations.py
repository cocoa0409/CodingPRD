"""Business-rule validations: space-kind compatibility, coordinator capacity,
walkthrough timing, reschedule exclusivity, time-window ordering, deposit gating,
the validation-priority conflicts, and the boundary-precision checks.

Translates corner `validations` plus difficulty rules
`priority_pair_validation_conflict` and `boundary_precision_check`.
"""
from test_helpers import (
    validate_error,
    validate_success,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_booking_payload,
    create_hold_payload,
    create_walkthrough_payload,
    create_reschedule_payload,
    create_guarantee_payload,
    create_payment_payload,
    create_inventory,
    create_inquiry_booking,
    add_both_holds,
    place_soft_hold,
    pay_deposit,
    confirm,
    setup_confirmed_booking,
    setup_held_booking,
)

VA = TEST_USERS["venue_admin_headers"]
FO = TEST_USERS["finance_officer_headers"]

_R1 = ("2026-10-10", "2026-10-10T20:00:00Z", "2026-10-10T21:00:00Z",
       "2026-10-10T21:00:00Z", "2026-10-11T02:00:00Z")
_R2 = ("2026-10-17", "2026-10-17T20:00:00Z", "2026-10-17T21:00:00Z",
       "2026-10-17T21:00:00Z", "2026-10-18T02:00:00Z")


# ───────────── Corner: validations ─────────────

def test_space_kind_mismatch_ceremony_hold_on_reception_only_space(api):
    """PRD §3.3: "a `CEREMONY` hold requires the space's `space_kind` to be
    `CEREMONY` or `DUAL`, and a `RECEPTION` hold requires `space_kind` to be
    `RECEPTION` or `DUAL`; an incompatible pairing is rejected with
    `ERR_SPACE_KIND_MISMATCH` (HTTP 422)."

    Design: Corner/validations/space_kind_mismatch_ceremony_hold_on_reception_only_space
    """
    inv = create_inventory(space_overrides={"name": "Banquet", "space_kind": "RECEPTION"})
    booking = create_inquiry_booking(inv)
    res = api.create_hold(
        booking["id"], create_hold_payload(inv["space_id"], "CEREMONY", booking["version"]),
        inv["coord_headers"])
    validate_error(res, ApiErrorId.ERR_SPACE_KIND_MISMATCH.value)


def test_coordinator_at_capacity_blocks_assignment(api):
    """PRD §3.2: "An assignment that would push `assigned_active_count` above the
    coordinator's `active_booking_cap` is rejected with `ERR_COORDINATOR_AT_CAPACITY`
    (HTTP 409)."

    Design: Corner/validations/coordinator_at_capacity_blocks_assignment
    """
    inv = create_inventory(with_space=False, coordinator_cap=1)
    coord = inv["coord_headers"]
    bkA = create_inquiry_booking(inv, assign_coordinator=False)
    get_success_data(api.assign_coordinator(
        bkA["id"], {"coordinator_id": inv["coordinator_id"]}, coord))
    bkB = create_inquiry_booking(inv, assign_coordinator=False, booking_overrides={
        "event_date": "2026-09-19",
        "ceremony_start": "2026-09-19T20:00:00Z", "ceremony_end": "2026-09-19T21:00:00Z",
        "reception_start": "2026-09-19T21:00:00Z", "reception_end": "2026-09-20T02:00:00Z",
        "expected_guest_count": 90})
    res = api.assign_coordinator(
        bkB["id"], {"coordinator_id": inv["coordinator_id"]}, coord)
    validate_error(res, ApiErrorId.ERR_COORDINATOR_AT_CAPACITY.value)
    fetched = get_success_data(api.get_coordinator(inv["coordinator_id"], coord))
    assert fetched["assigned_active_count"] == 1


def test_walkthrough_after_event_rejected(api):
    """PRD §3.8: "The appointment must fall strictly before the booking's
    `event_date`; a walkthrough scheduled on or after the event date is rejected
    with `ERR_WALKTHROUGH_AFTER_EVENT` (HTTP 422)."

    Design: Corner/validations/walkthrough_after_event_rejected
    """
    inv = create_inventory(with_space=False)
    booking = create_inquiry_booking(inv)  # event_date 2026-09-12
    res = api.create_walkthrough(
        booking["id"],
        create_walkthrough_payload("2026-09-13T10:00:00Z", "2026-09-13T11:00:00Z"),
        inv["coord_headers"])
    validate_error(res, ApiErrorId.ERR_WALKTHROUGH_AFTER_EVENT.value)


def test_reschedule_in_progress_blocks_second_nonsuperseding(api):
    """PRD §3.10: "Only one active request — one in `PROPOSED` or `COUNTERED` — may
    exist per booking at a time; proposing a second, non-superseding request while
    one is active is rejected with `ERR_RESCHEDULE_IN_PROGRESS` (HTTP 409)."

    Design: Corner/validations/reschedule_in_progress_blocks_second_nonsuperseding
    """
    inv, booking = setup_confirmed_booking()
    client_h = inv["client_headers"]
    get_success_data(api.create_reschedule_request(
        booking["id"], create_reschedule_payload("CLIENT_REQUEST", *_R1), client_h))
    res = api.create_reschedule_request(
        booking["id"], create_reschedule_payload("CLIENT_REQUEST", *_R2), client_h)
    validate_error(res, ApiErrorId.ERR_RESCHEDULE_IN_PROGRESS.value)


def test_invalid_time_window_inverted_reception_block(api):
    """PRD §3.2: "`reception_start` must be before `reception_end`. Furthermore,
    `event_date` must be strictly in the future ... Any violation of this block
    ordering ... is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 422)."

    Design: Corner/validations/invalid_time_window_inverted_reception_block
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    payload = create_booking_payload(
        inv["client_id"], inv["venue_id"], inv["package_id"],
        reception_start="2026-09-12T23:00:00Z", reception_end="2026-09-12T22:00:00Z")
    res = api.create_booking(payload, inv["client_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)


def test_confirm_without_deposit_returns_fiscal_error(api):
    """PRD §3.4: "If the deposit milestone is not yet settled at confirm time, the
    request is rejected with `ERR_DEPOSIT_NOT_SETTLED` (HTTP 402)."

    Design: Corner/validations/confirm_without_deposit_returns_fiscal_error
    """
    inv, booking = setup_held_booking()  # HELD, both holds, coordinator, NO deposit
    res = api.confirm_booking(booking["id"], inv["coord_headers"])
    validate_error(res, ApiErrorId.ERR_DEPOSIT_NOT_SETTLED.value)
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["booking_status"] == "HELD"


# ───────────── Rule 5: validation-priority conflicts ─────────────

def test_state_beats_fiscal_on_confirm_from_inquiry(api):
    """PRD §2.9: "then the target's state admissibility (`ERR_INVALID_STATE`)" is
    checked before the business constraints including "deposit settlement".
    PRD §2.7: "Any attempt to drive a transition that is not defined from a
    resource's current state ... is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    # Booking still in INQUIRY (never placed on hold) and deposit unpaid: both the
    # state check and the fiscal check would fail; the earlier state check wins.
    inv = create_inventory(with_space=False)
    booking = create_inquiry_booking(inv)
    res = api.confirm_booking(booking["id"], inv["coord_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_beats_fiscal_returns_409_not_402(api):
    """PRD §5: "`ERR_INVALID_STATE` | 409" and "`ERR_DEPOSIT_NOT_SETTLED` | 402".
    PRD §2.9: "then the target's state admissibility (`ERR_INVALID_STATE`)" is
    checked before the business constraints.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    inv = create_inventory(with_space=False)
    booking = create_inquiry_booking(inv)
    res = api.confirm_booking(booking["id"], inv["coord_headers"])
    # The state check (409) pre-empts the fiscal check (402).
    assert res.status_code == 409, f"expected 409 ERR_INVALID_STATE, got {res.status_code}"


def test_existence_beats_temporal_on_create_booking(api):
    """PRD §2.9: "then existence of body foreign keys (`ERR_REFERENCE_NOT_FOUND`).
    Only after those gates does the system validate the request body's shape ...
    Time-window ordering is validated next (`ERR_INVALID_TIME_WINDOW`)".

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_create_booking
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    # Non-existent package_id AND an inverted ceremony window: existence wins.
    payload = create_booking_payload(
        inv["client_id"], inv["venue_id"], NON_EXISTENT_UUID,
        ceremony_start="2026-09-12T21:00:00Z", ceremony_end="2026-09-12T20:00:00Z")
    res = api.create_booking(payload, inv["client_headers"])
    validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_existence_beats_temporal_returns_404_not_422(api):
    """PRD §2.9: "Only after those gates does the system validate the request body's
    shape — required fields present and well-typed, enums in range, numeric bounds
    satisfied — yielding `ERR_INVALID_REQUEST`. Time-window ordering is validated
    next (`ERR_INVALID_TIME_WINDOW`)".
    PRD §2.9: "Existence of path identifiers comes next (`ERR_NOT_FOUND`), then
    existence of body foreign keys (`ERR_REFERENCE_NOT_FOUND`)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_create_booking
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    payload = create_booking_payload(
        inv["client_id"], inv["venue_id"], NON_EXISTENT_UUID,
        ceremony_start="2026-09-12T21:00:00Z", ceremony_end="2026-09-12T20:00:00Z")
    res = api.create_booking(payload, inv["client_headers"])
    # The reference-existence check (404) pre-empts the time-window check (422).
    assert res.status_code == 404, f"expected 404 ERR_REFERENCE_NOT_FOUND, got {res.status_code}"


# ───────────── Rule 6: boundary-precision checks ─────────────

def test_guarantee_equal_to_capacity_allowed(api):
    """PRD §3.2: "`expected_guest_count` must not exceed the seated `max_capacity`
    of the reception space ... this same capacity ceiling is re-checked at guarantee
    time".
    PRD §3.7: "The guaranteed count is also bounded by the reception space's seated
    `max_capacity` — a guarantee that exceeds capacity is rejected with
    `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/capacity_equal_to_max_is_allowed_one_over_rejected
    """
    inv, booking = setup_confirmed_booking(space_overrides={"max_capacity": 140})
    res = api.guarantee_booking(
        booking["id"], create_guarantee_payload(140), inv["coord_headers"])
    data = validate_success(res)
    assert data["booking_status"] == "GUARANTEED"


def test_guarantee_one_over_capacity_rejected(api):
    """PRD §3.7: "The guaranteed count is also bounded by the reception space's
    seated `max_capacity` — a guarantee that exceeds capacity is rejected with
    `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/capacity_equal_to_max_is_allowed_one_over_rejected
    """
    inv, booking = setup_confirmed_booking(space_overrides={"max_capacity": 140})
    res = api.guarantee_booking(
        booking["id"], create_guarantee_payload(141), inv["coord_headers"])
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


def test_payment_exact_balance_allowed_reaches_paid_in_full(api):
    """PRD §3.5: "It reaches `PAID_IN_FULL` when `amount_paid_cents` is at least
    `event_charge_cents` (with a positive event charge) and every milestone is
    `SETTLED` or `WAIVED`".

    Design: Difficulty/boundary_precision_check/overpayment_exact_balance_allowed_one_over_rejected
    """
    inv, booking = setup_confirmed_booking()  # charge 3_135_200, deposit 783_800 paid
    # Exactly the remaining balance (2_351_400) → settles to PAID_IN_FULL.
    get_success_data(api.post_payment(
        booking["id"], create_payment_payload("INBOUND", 2_351_400, "WIRE"), FO))
    data = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert data["payment_status"] == "PAID_IN_FULL"
    assert data["balance_due_cents"] == 0


def test_payment_one_over_balance_rejected_overpayment(api):
    """PRD §3.5: "An `INBOUND` payment may not exceed the current `balance_due_cents`;
    an attempt to pay more than the contracted charge leaves outstanding is rejected
    with `ERR_OVERPAYMENT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/overpayment_exact_balance_allowed_one_over_rejected
    """
    inv, booking = setup_confirmed_booking()  # balance after deposit = 2_351_400
    res = api.post_payment(
        booking["id"], create_payment_payload("INBOUND", 2_351_401, "WIRE"), FO)
    validate_error(res, ApiErrorId.ERR_OVERPAYMENT.value)
