"""Season-pass usage counters, gating, OCC, and window validation (PRD §2.7, §3.3, §3.4)."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_open_slot, setup_course_slot_guide, create_participant, sign_waiver,
    create_season_pass, create_booking, list_season_passes, get_participant,
    create_season_pass_payload,
)

OP = TEST_USERS["operator_headers"]


def _slot_with_passholder(api, total_uses=5, valid_from=None, valid_until="2026-12-31T23:59:59Z",
                          open_slot=False):
    """Course + slot + guide + participant(waiver) + ACTIVE pass. Returns (ts, p, pass)."""
    if open_slot:
        course, ts, guide = setup_open_slot(api)
    else:
        course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api)
    sign_waiver(api, p["id"], signature_name="P A")
    sp = create_season_pass(api, p["id"], total_uses=total_uses,
                            valid_from=valid_from, valid_until=valid_until)
    return ts, p, sp


def test_pass_usage_committed_and_settled_counts(api):
    """PRD §3.3: "`uses_committed` counts the pass's bookings currently held in the active
    states `CONFIRMED`, `CHECKED_IN`, or `BRIEFED`. `uses_settled` counts the pass's
    bookings that have reached `COMPLETED`."

    Design: Difficulty/dual_variant_calc/season_pass_usage_provisional_vs_settled
    """
    course, ts, guide = setup_open_slot(api)
    p = create_participant(api)
    sign_waiver(api, p["id"], signature_name="P A")
    sp = create_season_pass(api, p["id"], total_uses=5)
    b1 = create_booking(api, ts["id"], p["id"], use_season_pass=True)
    create_booking(api, ts["id"], p["id"], use_season_pass=True)  # b2 stays CONFIRMED
    api.checkin_booking(b1["id"], OP)
    api.brief_booking(b1["id"], OP)
    validate_success(api.complete_booking(b1["id"], OP), 200)

    passes = list_season_passes(api, p["id"])
    pass_row = next(row for row in passes if row["id"] == sp["id"])
    assert pass_row["uses_committed"] == 1
    assert pass_row["uses_settled"] == 1


def test_pass_provisional_uses_remaining_subtracts_both(api):
    """PRD §3.3: "`uses_remaining` is the `total_uses` less both `uses_committed` and
    `uses_settled`, never allowed below zero."

    Design: Difficulty/dual_variant_calc/season_pass_usage_provisional_vs_settled
    """
    course, ts, guide = setup_open_slot(api)
    p = create_participant(api)
    sign_waiver(api, p["id"], signature_name="P A")
    sp = create_season_pass(api, p["id"], total_uses=5)
    b1 = create_booking(api, ts["id"], p["id"], use_season_pass=True)
    create_booking(api, ts["id"], p["id"], use_season_pass=True)
    api.checkin_booking(b1["id"], OP)
    api.brief_booking(b1["id"], OP)
    validate_success(api.complete_booking(b1["id"], OP), 200)

    passes = list_season_passes(api, p["id"])
    pass_row = next(row for row in passes if row["id"] == sp["id"])
    assert pass_row["uses_remaining"] == 3  # 5 - committed 1 - settled 1


def test_pass_entitlement_committed_on_booking(api):
    """PRD §3.3: "`uses_remaining` is the `total_uses` less both `uses_committed` and
    `uses_settled`, never allowed below zero."

    Design: Difficulty/compensating_invariant/pass_entitlement_conserved_use_then_cancel
    """
    ts, p, sp = _slot_with_passholder(api, total_uses=5)
    create_booking(api, ts["id"], p["id"], use_season_pass=True)
    passes = list_season_passes(api, p["id"])
    pass_row = next(row for row in passes if row["id"] == sp["id"])
    assert pass_row["uses_remaining"] == 4


def test_pass_entitlement_restored_on_cancel(api):
    """PRD §3.6: "Cancellation cascades the same way as a closure at the booking level:
    outstanding gear checkouts are returned and their gear items freed to `AVAILABLE`,
    the seat is released, and any season-pass commitment is released."

    Design: Difficulty/compensating_invariant/pass_entitlement_conserved_use_then_cancel
    """
    ts, p, sp = _slot_with_passholder(api, total_uses=5)
    booking = create_booking(api, ts["id"], p["id"], use_season_pass=True)
    api.cancel_booking(booking["id"], OP)
    passes = list_season_passes(api, p["id"])
    pass_row = next(row for row in passes if row["id"] == sp["id"])
    assert pass_row["uses_remaining"] == 5
    assert pass_row["uses_committed"] == 0


def test_pass_out_of_window_rejected_on_booking(api):
    """PRD §3.4: "A pass that is not `ACTIVE`, or whose window does not contain the current
    clock (the clock must be at or after `valid_from` and at or before `valid_until`), is
    rejected with `ERR_SEASON_PASS_INVALID`."

    Design: Corner/validations/season_pass_invalid_out_of_window_422
    """
    # Clock default 2026-05-01 precedes the pass valid_from 2026-07-01.
    ts, p, sp = _slot_with_passholder(api, total_uses=5,
                                      valid_from="2026-07-01T00:00:00Z")
    res = api.create_booking(
        {"time_slot_id": ts["id"], "participant_id": p["id"], "use_season_pass": True}, OP)
    validate_error(res, "ERR_SEASON_PASS_INVALID", expected_status=422)


def test_pass_exhausted_rejected_on_booking(api):
    """PRD §3.4: "A pass whose provisional `uses_remaining` is below 1 is rejected with
    `ERR_SEASON_PASS_EXHAUSTED`."

    Design: Corner/validations/season_pass_exhausted_422
    """
    ts, p, sp = _slot_with_passholder(api, total_uses=1)
    create_booking(api, ts["id"], p["id"], use_season_pass=True)  # consumes the only use
    res = api.create_booking(
        {"time_slot_id": ts["id"], "participant_id": p["id"], "use_season_pass": True}, OP)
    validate_error(res, "ERR_SEASON_PASS_EXHAUSTED", expected_status=422)


def test_pass_window_valid_until_not_after_from_returns_400(api):
    """PRD §2.9: "where a season pass is issued the window must satisfy `valid_until`
    strictly after `valid_from`; otherwise `ERR_VALIDATION`."

    Design: Corner/validations/season_pass_invalid_window_valid_until_before_from_400
    """
    p = create_participant(api)
    res = api.create_season_pass(
        p["id"],
        create_season_pass_payload(expected_participant_version=p["version"],
                                   valid_from="2026-12-31T00:00:00Z",
                                   valid_until="2026-01-01T00:00:00Z", total_uses=5),
        OP)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_season_pass_stale_version_rejected(api):
    """PRD §2.7: "If that value does not equal the participant's current `version` at the
    moment the server processes the request, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/season_pass_occ_stale_version_returns_412
    """
    p = create_participant(api)
    stale_version = p["version"]
    create_season_pass(api, p["id"], expected_version=stale_version)  # advances version
    res = api.create_season_pass(
        p["id"],
        create_season_pass_payload(expected_participant_version=stale_version,
                                   tier="PREMIUM", total_uses=10),
        OP)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_season_pass_correct_version_succeeds_and_bumps_participant(api):
    """PRD §3.3: "A newly issued pass starts `ACTIVE`; as a side effect, any prior
    `ACTIVE` pass held by the same participant is driven to `SUPERSEDED`, and the
    participant's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/season_pass_occ_correct_version_succeeds_and_supersedes
    """
    p = create_participant(api)
    res = api.create_season_pass(
        p["id"],
        create_season_pass_payload(expected_participant_version=p["version"],
                                   total_uses=5), OP)
    sp = validate_success(res, 201)
    assert sp["status"] == "ACTIVE"
    refreshed = get_participant(api, p["id"])
    assert refreshed["version"] == 2
