"""Breadth coverage: invalid/valid state transitions, terminal lockdown,
idempotency, calculation corners (season-pass admission waiver, deposit ceiling,
seat filtering), and the validation-error catalog.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_admission_window_payload, create_reservation_payload, create_waiver_payload,
)
from test_helpers.test_users import make_visitor_headers, make_group_leader_headers

MANAGER = fx.MANAGER
GATE = fx.GATE


# ===========================================================================
# Queue B — state_machines
# ===========================================================================

def test_confirm_already_confirmed_reservation_invalid_state(api):
    """PRD §3.3: "a transition attempted from a status other than `PENDING` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_already_confirmed_reservation_invalid_state
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_confirmed_reservation(s["window"]["id"], s["visitor"]["id"],
                                          s["window"]["version"], adult_count=1, child_count=0)
    resp = api.confirm_reservation(res["id"], make_visitor_headers(s["visitor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_reservation(res["id"], make_visitor_headers(s["visitor"]["id"])))
    assert after["status"] == "CONFIRMED"
    win_after = validate_success(api.get_admission_window(s["window"]["id"], MANAGER))
    assert win_after["seats_committed"] == 1, "no double seat move on a rejected re-confirm"


def test_cancel_settled_reservation_terminal_lockdown(api):
    """PRD §3.3: "Cancelling a reservation that is neither `PENDING` nor
    `CONFIRMED` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_settled_reservation_terminal_lockdown
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    settled = fx.create_settled_reservation(s["window"]["id"], s["visitor"]["id"],
                                            s["window"]["version"], adult_count=1, child_count=0)
    assert settled["status"] == "SETTLED"

    resp = api.cancel_reservation(settled["id"], make_visitor_headers(s["visitor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_reservation(settled["id"], make_visitor_headers(s["visitor"]["id"])))
    assert after["status"] == "SETTLED"


def test_weigh_out_already_weighed_pumpkin_rejected(api):
    """PRD §3.4: "Weighing out a pumpkin that is already `WEIGHED` or `VOID` is
    rejected with `ERR_PUMPKIN_ALREADY_WEIGHED`."

    Design: Corner/state_machines/weigh_out_already_weighed_pumpkin_rejected
    """
    s = fx.setup_checked_in(capacity=5, adult_count=1, child_count=0)
    res = s["reservation"]
    pk = fx.add_pumpkin(res["id"], s["visitor"]["id"], estimated_weight_lb=10)
    fx.weigh_out(pk["id"], scale_weight_lb=10)  # -> WEIGHED, charge 1500.

    resp = api.weigh_out_pumpkin(pk["id"], {"scale_weight_lb": 15}, GATE)
    validate_error(resp, ApiErrorId.ERR_PUMPKIN_ALREADY_WEIGHED.value)

    after = validate_success(api.get_reservation(res["id"], GATE))  # noqa: F841 (reservation read)
    pk_after = validate_success(api.list_pumpkin_purchases(res["id"], GATE))[0]
    assert pk_after["charge_cents"] == 1500, "charge must be unchanged after the rejected re-weigh"


def test_revise_confirmed_group_rejected(api):
    """PRD §3.7: "Opening for revision, requoting, or editing a booking that is
    not in the required `QUOTED` or `REVISING` state is rejected with
    `ERR_GROUP_NOT_REVISABLE`."

    Design: Corner/state_machines/revise_confirmed_group_rejected_not_revisable
    """
    farm = fx.create_farm(name="GR Lock Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=20)
    leader = fx.create_visitor(email="gl@x.com", full_name="Gail Lead")
    group = fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                            adult_count=4, child_count=6)
    fx.confirm_group(group["id"], leader["id"], window["version"])

    resp = api.revise_group_booking(group["id"], make_group_leader_headers(leader["id"]))
    validate_error(resp, ApiErrorId.ERR_GROUP_NOT_REVISABLE.value)

    after = validate_success(api.get_group_booking(group["id"], make_group_leader_headers(leader["id"])))
    assert after["status"] == "CONFIRMED"


def test_mark_no_shows_sweeps_confirmed_after_end(api):
    """PRD §3.4: "each reservation still in `CONFIRMED` status whose window has
    ended is moved `CONFIRMED → NO_SHOW`, releasing its `participant_count` from
    the window's `seats_committed` and recomputing `seats_available`."

    Design: Corner/state_machines/mark_no_shows_sweeps_confirmed_to_no_show_after_end
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="NoShow Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=5)
    visitor = fx.create_visitor(email="ns@x.com", full_name="Nora Show")
    res = fx.create_confirmed_reservation(window["id"], visitor["id"], window["version"],
                                          adult_count=1, child_count=0)
    # Advance the clock past the window end.
    fx.set_clock("2026-10-11T17:00:00Z")

    validate_success(api.mark_no_shows(window["id"], GATE))

    res_after = validate_success(api.get_reservation(res["id"], GATE))
    assert res_after["status"] == "NO_SHOW"
    win_after = validate_success(api.get_admission_window(window["id"], MANAGER))
    assert win_after["seats_committed"] == 0, "no-show sweep must release the committed seats"


# ===========================================================================
# Queue B — calculations
# ===========================================================================

def test_season_pass_admission_is_zero(api):
    """PRD §3.5: "If the reservation redeems a pass that is `ACTIVE`, admission is
    waived entirely and the charge is 0".

    Design: Corner/calculations/season_pass_admission_is_zero
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Free Pass Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=5)
    visitor = fx.create_visitor(email="fp@x.com", full_name="Faye Pass")
    season_pass = fx.create_season_pass(farm["id"], visitor["id"],
                                        valid_from="2026-10-01T00:00:00Z",
                                        valid_until="2026-11-01T00:00:00Z")
    res = fx.create_pending_reservation(window["id"], visitor["id"], window["version"],
                                        adult_count=2, child_count=2, season_pass_id=season_pass["id"])
    assert res["admission_charge_cents"] == 0, (
        f"ACTIVE pass must waive admission to 0 regardless of counts, got {res['admission_charge_cents']}"
    )


def test_group_deposit_ceil_rounds_up(api):
    """PRD §3.7: "locks the `deposit_cents` at the ceiling of `quoted_total_cents`
    multiplied by one quarter (the non-refundable deposit is rounded up so it is
    never under a quarter of the quote)".

    Design: Corner/calculations/group_deposit_ceil_rounds_up
    """
    farm = fx.create_farm(name="Deposit Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=40)
    leader = fx.create_visitor(email="dp@x.com", full_name="Dana Deposit")
    group = fx.create_group(farm["id"], window["id"], leader["id"], "SCHOOL",
                            adult_count=5, child_count=25)
    assert group["quoted_total_cents"] == 26000

    confirmed = fx.confirm_group(group["id"], leader["id"], window["version"])
    # ceil(26000 * 0.25) = ceil(6500.0) = 6500.
    assert confirmed["deposit_cents"] == 6500, (
        f"deposit must be ceil(26000*0.25)=6500, got {confirmed['deposit_cents']}"
    )


def test_window_seats_excludes_cancelled_reservation(api):
    """PRD §3.3: "The held count is the sum of `participant_count` over the
    window's `PENDING` reservations."
    PRD §3.3: "Reservations in `NO_SHOW` or `CANCELLED` status, and groups in
    `QUOTED`, `REVISING`, or `CANCELLED` status, contribute to neither sum."

    Design: Corner/calculations/window_seats_excludes_cancelled_and_noshow
    """
    farm = fx.create_farm(name="Filter Seats Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=10)
    vx = fx.create_visitor(email="fx@x.com", full_name="Fox X")
    vy = fx.create_visitor(email="fy@x.com", full_name="Fay Y")

    res_x = fx.create_pending_reservation(window["id"], vx["id"], window["version"],
                                          adult_count=2, child_count=1)  # 3 participants
    fx.cancel_reservation(res_x["id"], vx["id"])
    v_after_cancel = fx.window_version(window["id"])
    fx.create_pending_reservation(window["id"], vy["id"], v_after_cancel,
                                  adult_count=2, child_count=0)  # 2 participants, PENDING

    win_after = validate_success(api.get_admission_window(window["id"], MANAGER))
    assert win_after["seats_held"] == 2, (
        f"only the surviving PENDING reservation counts (2), got {win_after['seats_held']}"
    )
    assert win_after["seats_committed"] == 0
    assert win_after["seats_available"] == 8


# ===========================================================================
# Queue B — validations
# ===========================================================================

def test_window_zero_length_time_invalid(api):
    """PRD §3.1: "a window whose `starts_at` is not strictly before its `ends_at`
    (including a zero-length window) is rejected with `ERR_WINDOW_TIME_INVALID`."

    Design: Corner/validations/window_zero_length_time_invalid
    """
    farm = fx.create_farm(name="Zero Window Farm")
    resp = api.create_admission_window(
        farm["id"],
        create_admission_window_payload(starts_at="2026-10-11T14:00:00Z",
                                        ends_at="2026-10-11T14:00:00Z", capacity=5),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_TIME_INVALID.value)


def test_empty_party_reservation_rejected(api):
    """PRD §3.3: "this is the number of seats the reservation draws against the
    window and must be at least 1 — an empty party is rejected with
    `ERR_EMPTY_PARTY`."

    Design: Corner/validations/empty_party_reservation_rejected
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    resp = api.create_reservation(
        create_reservation_payload(s["window"]["id"], s["visitor"]["id"], s["window"]["version"],
                                   adult_count=0, child_count=0),
        make_visitor_headers(s["visitor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_EMPTY_PARTY.value)


def test_minor_waiver_missing_guardian_rejected(api):
    """PRD §3.4: "A waiver for a minor that omits `guardian_name` is rejected at
    signing with `ERR_GUARDIAN_REQUIRED`."

    Design: Corner/validations/minor_waiver_missing_guardian_rejected
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=1, child_count=1)
    resp = api.create_waiver(
        res["id"], create_waiver_payload("Tiny Tot", is_minor=True),
        make_visitor_headers(s["visitor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_GUARDIAN_REQUIRED.value)


def test_waiver_incomplete_at_checkin_rejected(api):
    """PRD §3.4: "a check-in attempted before a signed waiver covers every
    participant is rejected with `ERR_WAIVER_INCOMPLETE`."

    Design: Corner/validations/waiver_incomplete_at_checkin_rejected
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_confirmed_reservation(s["window"]["id"], s["visitor"]["id"],
                                          s["window"]["version"], adult_count=1, child_count=1)
    # Only one waiver signed (covers 1 of 2 participants).
    fx.sign_waiver(res["id"], s["visitor"]["id"], "Will Gap")

    resp = api.check_in_reservation(res["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_WAIVER_INCOMPLETE.value)

    after = validate_success(api.get_reservation(res["id"], GATE))
    assert after["status"] == "CONFIRMED"


def test_group_window_mismatch_rejected(api):
    """PRD §3.3: "If a `group_booking_id` is supplied, that group must sit on the
    very same window as the reservation, or the create is rejected with
    `ERR_GROUP_WINDOW_MISMATCH`."

    Design: Corner/validations/group_window_mismatch_rejected
    """
    farm = fx.create_farm(name="Mismatch Farm", window_buffer_minutes=0)
    fx.create_active_policy(farm["id"])
    window_a = fx.create_window(farm["id"], capacity=20,
                                starts_at="2026-10-11T14:00:00Z", ends_at="2026-10-11T16:00:00Z")
    window_b = fx.create_window(farm["id"], capacity=20,
                                starts_at="2026-10-12T14:00:00Z", ends_at="2026-10-12T16:00:00Z")
    leader = fx.create_visitor(email="mm@x.com", full_name="Max Match")
    visitor = fx.create_visitor(email="mv@x.com", full_name="Mia Visitor")
    group = fx.create_group(farm["id"], window_a["id"], leader["id"], "FIELD_TRIP",
                            adult_count=4, child_count=6)

    # Reservation targets window B but references a group on window A.
    resp = api.create_reservation(
        create_reservation_payload(window_b["id"], visitor["id"], window_b["version"],
                                   adult_count=1, child_count=0, group_booking_id=group["id"]),
        make_visitor_headers(visitor["id"]))
    validate_error(resp, ApiErrorId.ERR_GROUP_WINDOW_MISMATCH.value)
