"""Race-day operations: check-in windows and the auto-issued credential,
check-out hour logs, no-show grace and the strike/backfill cascade, and the
supply tent (PRD §3.6, §3.7).
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    make_volunteer_headers, make_captain_headers,
    validate_success, validate_error, validate_paginated,
    set_clock,
    setup_event_with_shift, setup_published_with_volunteers,
    setup_race_day_with_confirmed, setup_captain_on_shift,
    add_segment, add_shift, add_inventory,
    register_eligible_volunteer, enroll_and_pass,
    request_signup, approve_signup, confirm_signup, create_confirmed_signup,
    lock_and_start_race_day, check_in_signup, check_out_signup,
    fetch_hour_log_for_signup,
    create_signup_payload, create_distribution_record_payload,
    create_event_payload, assert_hour_log, assert_distribution_record,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Check-in window (PRD §3.6)
# ---------------------------------------------------------------------------

def test_checkin_outside_window_rejected(api):
    """PRD §3.6: "Check-in is accepted within a fixed window: from sixty
    minutes before the shift's `start_at` through the shift's `end_at`,
    inclusive; outside that window the request fails with
    `ERR_CHECKIN_WINDOW_INVALID`."

    Design: Corner/state_machines/checkin_outside_window_rejected
    """
    # Event opens at 05:00 so race day can start before the 07:00 shift's
    # check-in window opens at 06:00.
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        event_overrides={"event_start_at": "2026-10-04T05:00:00Z"},
        shift_overrides={"start_at": "2026-10-04T07:00:00Z",
                         "end_at": "2026-10-04T11:00:00Z",
                         "required_headcount": 1})
    sg = create_confirmed_signup(ctx["volunteers"][0]["id"], ctx["shift"]["id"])
    lock_and_start_race_day(ctx["event"]["id"], at="2026-10-04T05:00:00Z")
    set_clock("2026-10-04T05:59:00Z")
    early = api_client.check_in_signup(sg["id"], COORDINATOR)
    validate_error(early, ApiErrorId.ERR_CHECKIN_WINDOW_INVALID)
    set_clock("2026-10-04T06:00:00Z")
    ok = validate_success(api_client.check_in_signup(sg["id"], COORDINATOR))
    assert ok["status"] == "CHECKED_IN", "exactly start-60min is the inclusive lower bound"


def test_checkin_autoissues_credential_side_effect(api):
    """PRD §3.6: "A successful check-in moves the signup to `CHECKED_IN`,
    stamps `checked_in_at`, recomputes the shift's `checked_in_count`, and
    automatically issues the volunteer's credential: a new distribution
    record of `kind` `CREDENTIAL` in `ISSUED` status, bound to that signup."

    Design: Corner/endpoints/checkin_autoissues_credential_side_effect
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    sg = ctx["signups"][0]
    checked = check_in_signup(sg["id"])
    assert checked["status"] == "CHECKED_IN"
    assert checked["checked_in_at"] is not None
    data, meta = validate_paginated(api_client.list_distribution_records(
        COORDINATOR, params={"signup_id": sg["id"], "kind": "CREDENTIAL"}))
    assert meta["total_count"] == 1, "check-in issues exactly one credential"
    cred = data[0]
    assert_distribution_record(cred)
    assert cred["kind"] == "CREDENTIAL"
    assert cred["status"] == "ISSUED"
    assert cred["inventory_id"] is None
    assert cred["issued_at"] == checked["checked_in_at"]


def test_checkout_creates_hourlog_side_effect(api):
    """PRD §3.6: "The signup moves to `COMPLETED`, stamps `checked_out_at`,
    and spawns an hour log in `PENDING_VERIFICATION` status, with `event_id`
    denormalized from the signup at creation and its duration fields computed
    as §3.8 defines."
    PRD §3.8: "`raw_minutes` is the elapsed time from `checked_in_at` to
    `checked_out_at` minus `break_minutes`, floored at zero so a long break
    can never produce a negative duration. `claimed_hours` is `raw_minutes`
    divided by sixty, rounded half up to two decimal places. `credited_hours`
    is `raw_minutes` divided by fifteen, that quotient rounded half up to a
    whole number of quarter-hours, and the result multiplied by one quarter
    hour."

    Design: Corner/endpoints/checkout_creates_hourlog_side_effect
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    sg = ctx["signups"][0]
    check_in_signup(sg["id"])
    completed = check_out_signup(sg["id"], "2026-10-04T10:00:00Z")
    assert completed["status"] == "COMPLETED"
    assert completed["checked_out_at"] is not None
    log = fetch_hour_log_for_signup(sg["id"])
    assert_hour_log(log)
    assert log["status"] == "PENDING_VERIFICATION"
    assert log["raw_minutes"] == 240
    assert log["claimed_hours"] == pytest.approx(4.0, abs=0.001)
    assert log["credited_hours"] == pytest.approx(4.0, abs=0.001)
    assert log["event_id"] == ctx["event"]["id"]


# ---------------------------------------------------------------------------
# No-show grace and signup state guards (PRD §3.7, §3.6)
# ---------------------------------------------------------------------------

def test_mark_no_show_before_grace_rejected(api):
    """PRD §3.7: "The mark requires the signup to be `CONFIRMED`
    (`ERR_SIGNUP_NOT_NO_SHOWABLE`), the event to be `RACE_DAY` or `COMPLETED`
    (`ERR_INVALID_EVENT_STATE`), and the logical clock to have reached at
    least thirty minutes past the shift's `start_at`
    (`ERR_NO_SHOW_GRACE_NOT_PASSED`)."

    Design: Corner/state_machines/mark_no_show_before_grace_rejected
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 1})
    sg = ctx["signups"][0]
    set_clock("2026-10-04T06:15:00Z")
    early = api_client.mark_no_show(sg["id"], COORDINATOR)
    validate_error(early, ApiErrorId.ERR_NO_SHOW_GRACE_NOT_PASSED)
    set_clock("2026-10-04T06:31:00Z")
    marked = validate_success(api_client.mark_no_show(sg["id"], COORDINATOR))
    assert marked["status"] == "NO_SHOW"


def test_signup_state_guards_rejected(api):
    """PRD §3.6: "A coordinator checks in a `CONFIRMED` signup — from any
    other status, `ERR_SIGNUP_NOT_CHECKINABLE`"
    PRD §3.6: "A coordinator checks out a `CHECKED_IN` signup — from any other
    status, `ERR_SIGNUP_NOT_CHECKED_OUTABLE`"
    PRD §3.7: "The mark requires the signup to be `CONFIRMED`
    (`ERR_SIGNUP_NOT_NO_SHOWABLE`)"

    Design: Corner/errors/signup_state_guards_rejected
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02"},
         {"full_name": "V Three", "date_of_birth": "2000-01-03"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 3})
    sh = ctx["shift"]["id"]
    v1, v2, v3 = ctx["volunteers"]
    sg_req = request_signup(v1["id"], sh)
    sg_app = request_signup(v2["id"], sh)
    approve_signup(sg_app["id"])
    sg_con = create_confirmed_signup(v3["id"], sh)
    lock_and_start_race_day(ctx["event"]["id"])
    set_clock("2026-10-04T06:31:00Z")
    bad_checkin = api_client.check_in_signup(sg_app["id"], COORDINATOR)
    validate_error(bad_checkin, ApiErrorId.ERR_SIGNUP_NOT_CHECKINABLE)
    bad_checkout = api_client.check_out_signup(sg_con["id"], COORDINATOR)
    validate_error(bad_checkout, ApiErrorId.ERR_SIGNUP_NOT_CHECKED_OUTABLE)
    bad_noshow = api_client.mark_no_show(sg_req["id"], COORDINATOR)
    validate_error(bad_noshow, ApiErrorId.ERR_SIGNUP_NOT_NO_SHOWABLE)


def test_captain_can_mark_no_show_own_shift(api):
    """PRD §3.7: "The actor is a `VolunteerCoordinator`, or a `Captain` whose
    own captain signup sits on the same shift as the absent volunteer; anyone
    else is rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.7: "Marking a no-show fires a five-link cascade. Link one: the
    volunteer's `no_show_strikes` increments by one."

    Design: Corner/rbac/captain_can_mark_no_show_own_shift
    """
    ctx = setup_captain_on_shift(
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 2})
    ev = ctx["event"]["id"]
    v2 = register_eligible_volunteer(ev, full_name="V Two", date_of_birth="2000-01-02")
    sg2 = create_confirmed_signup(v2["id"], ctx["shift"]["id"])
    lock_and_start_race_day(ev)
    set_clock("2026-10-04T06:31:00Z")
    marked = validate_success(api_client.mark_no_show(
        sg2["id"], make_captain_headers(ctx["captain"]["id"])))
    assert marked["status"] == "NO_SHOW", "the shift's own captain may mark the no-show"
    vol2 = validate_success(api_client.get_volunteer(v2["id"], COORDINATOR))
    assert vol2["no_show_strikes"] == 1


# ---------------------------------------------------------------------------
# Supply tent: stock boundary and kind/inventory coherence (PRD §3.6)
# ---------------------------------------------------------------------------

def _setup_checked_in_with_inventory(api, quantity_total=2):
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    inv = add_inventory(ctx["event"]["id"], quantity_total=quantity_total)
    check_in_signup(ctx["signups"][0]["id"])
    ctx["inventory"] = inv
    return ctx


def test_stock_last_unit_issues_successfully(api):
    """PRD §3.6: "Issuing a supply item consumes stock: the inventory's
    `quantity_issued` must still be below its `quantity_total`, which means
    issuing the final unit succeeds and the attempt after it fails with
    `ERR_OUT_OF_STOCK`."

    Design: Difficulty/boundary_precision_check/stock_last_unit_then_out_of_stock
    """
    ctx = _setup_checked_in_with_inventory(api, quantity_total=2)
    sg = ctx["signups"][0]
    for _ in range(2):
        ok = validate_success(api_client.create_distribution_record(
            create_distribution_record_payload(sg["id"], "SUPPLY_ITEM",
                                               inventory_id=ctx["inventory"]["id"]),
            COORDINATOR), expected_status=201)
        assert ok["status"] == "ISSUED"
    inv = validate_success(api_client.get_supply_inventory(ctx["inventory"]["id"], COORDINATOR))
    assert inv["quantity_issued"] == 2 == inv["quantity_total"]


def test_stock_zero_remaining_rejected(api):
    """PRD §3.6: "Issuing a supply item consumes stock: the inventory's
    `quantity_issued` must still be below its `quantity_total`, which means
    issuing the final unit succeeds and the attempt after it fails with
    `ERR_OUT_OF_STOCK`."

    Design: Difficulty/boundary_precision_check/stock_last_unit_then_out_of_stock
    """
    ctx = _setup_checked_in_with_inventory(api, quantity_total=2)
    sg = ctx["signups"][0]
    for _ in range(2):
        validate_success(api_client.create_distribution_record(
            create_distribution_record_payload(sg["id"], "SUPPLY_ITEM",
                                               inventory_id=ctx["inventory"]["id"]),
            COORDINATOR), expected_status=201)
    third = api_client.create_distribution_record(
        create_distribution_record_payload(sg["id"], "SUPPLY_ITEM",
                                           inventory_id=ctx["inventory"]["id"]),
        COORDINATOR)
    validate_error(third, ApiErrorId.ERR_OUT_OF_STOCK)


def test_supply_issue_kind_inventory_mismatch_rejected(api):
    """PRD §3.6: "The two kinds have opposite inventory rules: a `CREDENTIAL`
    record must carry a null `inventory_id`, a `SUPPLY_ITEM` record must carry
    a live one, and any mismatch is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/supply_issue_kind_inventory_mismatch_rejected
    """
    ctx = _setup_checked_in_with_inventory(api, quantity_total=5)
    sg = ctx["signups"][0]
    # Free the credential slot so only the payload-shape rule can fail on the
    # CREDENTIAL leg: revoke the auto-issued credential first.
    creds, _ = validate_paginated(api_client.list_distribution_records(
        COORDINATOR, params={"signup_id": sg["id"], "kind": "CREDENTIAL"}))
    validate_success(api_client.revoke_distribution_record(creds[0]["id"], COORDINATOR))
    missing_inv = api_client.create_distribution_record(
        {"signup_id": sg["id"], "kind": "SUPPLY_ITEM"}, COORDINATOR)
    validate_error(missing_inv, ApiErrorId.ERR_INVALID_REQUEST)
    stray_inv = api_client.create_distribution_record(
        {"signup_id": sg["id"], "kind": "CREDENTIAL",
         "inventory_id": ctx["inventory"]["id"]}, COORDINATOR)
    validate_error(stray_inv, ApiErrorId.ERR_INVALID_REQUEST)


def test_credential_reissue_while_issued_rejected(api):
    """PRD §3.6: "A signup may hold at most one credential in `ISSUED`
    status; a second issuance is rejected with `ERR_CREDENTIAL_ALREADY_ISSUED`."

    Design: Corner/validations/credential_reissue_while_issued_rejected
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    sg = ctx["signups"][0]
    check_in_signup(sg["id"])  # auto-issues the credential
    resp = api_client.create_distribution_record(
        {"signup_id": sg["id"], "kind": "CREDENTIAL"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_ALREADY_ISSUED)


def test_distribution_state_guards_rejected(api):
    """PRD §3.6: "Returning — allowed only for a `SUPPLY_ITEM` record in
    `ISSUED` status; credentials cannot be returned, and any record not
    currently `ISSUED` rejects with `ERR_DISTRIBUTION_INVALID_STATE`"

    Design: Corner/errors/distribution_state_guards_rejected
    """
    ctx = _setup_checked_in_with_inventory(api, quantity_total=2)
    sg = ctx["signups"][0]
    creds, _ = validate_paginated(api_client.list_distribution_records(
        COORDINATOR, params={"signup_id": sg["id"], "kind": "CREDENTIAL"}))
    cred_return = api_client.return_distribution_record(creds[0]["id"], COORDINATOR)
    validate_error(cred_return, ApiErrorId.ERR_DISTRIBUTION_INVALID_STATE)
    supply = validate_success(api_client.create_distribution_record(
        create_distribution_record_payload(sg["id"], "SUPPLY_ITEM",
                                           inventory_id=ctx["inventory"]["id"]),
        COORDINATOR), expected_status=201)
    validate_success(api_client.return_distribution_record(supply["id"], COORDINATOR))
    re_return = api_client.return_distribution_record(supply["id"], COORDINATOR)
    validate_error(re_return, ApiErrorId.ERR_DISTRIBUTION_INVALID_STATE)


# ---------------------------------------------------------------------------
# Distribution gated on the signup's state (PRD §3.6)
# ---------------------------------------------------------------------------

def _setup_confirmed_not_checked_in(api):
    """PUBLISHED event; V1 CONFIRMED on the shift; inventory total 5. The
    signup never checks in (the event is not yet RACE_DAY)."""
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}])
    inv = add_inventory(ctx["event"]["id"], quantity_total=5)
    sg = create_confirmed_signup(ctx["volunteers"][0]["id"], ctx["shift"]["id"])
    ctx["inventory"] = inv
    ctx["signup"] = sg
    return ctx


def test_distribution_gated_by_signup_checkin_rejected(api):
    """PRD §3.6: "The recipient signup must be `CHECKED_IN`
    (`ERR_SIGNUP_NOT_CHECKED_IN`)."

    Design: Difficulty/cross_entity_state_dependency/distribution_gated_by_signup_checkin
    """
    ctx = _setup_confirmed_not_checked_in(api)
    assert ctx["signup"]["status"] == "CONFIRMED"
    resp = api_client.create_distribution_record(
        create_distribution_record_payload(ctx["signup"]["id"], "SUPPLY_ITEM",
                                           inventory_id=ctx["inventory"]["id"]),
        COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_CHECKED_IN)


def test_distribution_gated_by_signup_checkin_no_partial_write(api):
    """PRD §3.6: "The recipient signup must be `CHECKED_IN`
    (`ERR_SIGNUP_NOT_CHECKED_IN`)."
    PRD §3.6: "The computed `quantity_issued` starts at zero and always equals
    the number of distribution records referencing that inventory with `kind`
    `SUPPLY_ITEM` in `ISSUED` status."

    Design: Difficulty/cross_entity_state_dependency/distribution_gated_by_signup_checkin
    """
    ctx = _setup_confirmed_not_checked_in(api)
    resp = api_client.create_distribution_record(
        create_distribution_record_payload(ctx["signup"]["id"], "SUPPLY_ITEM",
                                           inventory_id=ctx["inventory"]["id"]),
        COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_CHECKED_IN)
    inv = validate_success(api_client.get_supply_inventory(ctx["inventory"]["id"], COORDINATOR))
    assert inv["quantity_issued"] == 0, "no partial write may leak through"
    recs, meta = validate_paginated(api_client.list_distribution_records(
        COORDINATOR, params={"signup_id": ctx["signup"]["id"]}))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Stock conservation across an issue/return pair (PRD §3.6)
# ---------------------------------------------------------------------------

def test_stock_conservation_issue_increments(api):
    """PRD §3.6: "Every issuance lands in `ISSUED` status, stamps `issued_at`,
    and recomputes the inventory's `quantity_issued` upward."

    Design: Difficulty/compensating_invariant/stock_conservation_issue_return_pair
    """
    ctx = _setup_checked_in_with_inventory(api, quantity_total=3)
    sg = ctx["signups"][0]
    before = validate_success(api_client.get_supply_inventory(ctx["inventory"]["id"], COORDINATOR))
    assert before["quantity_issued"] == 0
    rec = validate_success(api_client.create_distribution_record(
        create_distribution_record_payload(sg["id"], "SUPPLY_ITEM",
                                           inventory_id=ctx["inventory"]["id"]),
        COORDINATOR), expected_status=201)
    assert rec["status"] == "ISSUED"
    after = validate_success(api_client.get_supply_inventory(ctx["inventory"]["id"], COORDINATOR))
    assert after["quantity_issued"] == 1


def test_stock_conservation_return_restores(api):
    """PRD §3.6: "Returning — allowed only for a `SUPPLY_ITEM` record in
    `ISSUED` status; credentials cannot be returned, and any record not
    currently `ISSUED` rejects with `ERR_DISTRIBUTION_INVALID_STATE` — moves
    the record to `RETURNED`, stamps `returned_at`, and decrements the
    inventory's `quantity_issued`."

    Design: Difficulty/compensating_invariant/stock_conservation_issue_return_pair
    """
    ctx = _setup_checked_in_with_inventory(api, quantity_total=3)
    sg = ctx["signups"][0]
    rec = validate_success(api_client.create_distribution_record(
        create_distribution_record_payload(sg["id"], "SUPPLY_ITEM",
                                           inventory_id=ctx["inventory"]["id"]),
        COORDINATOR), expected_status=201)
    returned = validate_success(api_client.return_distribution_record(rec["id"], COORDINATOR))
    assert returned["status"] == "RETURNED"
    assert returned["returned_at"] is not None
    after = validate_success(api_client.get_supply_inventory(ctx["inventory"]["id"], COORDINATOR))
    assert after["quantity_issued"] == 0, \
        "the issue (+1) and its compensating return (-1) leave the inventory unchanged"


# ---------------------------------------------------------------------------
# The no-show strike / suspension / backfill cascade (PRD §3.7)
# ---------------------------------------------------------------------------

def _setup_strike_cascade(api):
    """V1 CONFIRMED on S0 (06:00-07:00, segA), S1 (08:00-10:00, segA) and S2
    (11:00-13:00, segB), all headcount 1; V2 an ELIGIBLE floater with no
    signups; event RACE_DAY at 06:00."""
    ctx = setup_event_with_shift(
        publish=True,
        segment_overrides={"segment_code": "SEG-A", "mile_start": 5, "mile_end": 10},
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T07:00:00Z",
                         "required_headcount": 1})
    ev = ctx["event"]["id"]
    seg_b = add_segment(ev, segment_code="SEG-B", mile_start=10, mile_end=15)
    s1 = add_shift(ev, ctx["role"]["id"], ctx["segment"]["id"],
                   start_at="2026-10-04T08:00:00Z", end_at="2026-10-04T10:00:00Z",
                   required_headcount=1)
    s2 = add_shift(ev, ctx["role"]["id"], seg_b["id"],
                   start_at="2026-10-04T11:00:00Z", end_at="2026-10-04T13:00:00Z",
                   required_headcount=1)
    v1 = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    v2 = register_eligible_volunteer(ev, full_name="V Floater",
                                     date_of_birth="1999-01-01", float_opt_in=True)
    sg0 = create_confirmed_signup(v1["id"], ctx["shift"]["id"])
    sg1 = create_confirmed_signup(v1["id"], s1["id"])
    sg2 = create_confirmed_signup(v1["id"], s2["id"])
    lock_and_start_race_day(ev)
    ctx.update({"seg_b": seg_b, "s1": s1, "s2": s2, "v1": v1, "v2": v2,
                "sg0": sg0, "sg1": sg1, "sg2": sg2})
    return ctx


def test_no_show_first_strike_backfills_seat(api):
    """PRD §3.7: "The top-ranked candidate receives a brand-new signup placed
    directly in `CONFIRMED` status — no approval or confirmation step — with
    `origin` set to `FLOAT_POOL_BACKFILL`, `replaces_signup_id` pointing at
    the freed `NO_SHOW` or `CANCELLED` signup it replaces (the field is null
    on all non-backfill signups), and `confirmed_at` stamped at creation."
    PRD §3.7: "Marking a no-show fires a five-link cascade. Link one: the
    volunteer's `no_show_strikes` increments by one."

    Design: Difficulty/transitive_cascade/no_show_strike_suspension_backfill_cascade
    """
    ctx = _setup_strike_cascade(api)
    set_clock("2026-10-04T06:31:00Z")
    marked = validate_success(api_client.mark_no_show(ctx["sg0"]["id"], COORDINATOR))
    assert marked["status"] == "NO_SHOW"
    vol1 = validate_success(api_client.get_volunteer(ctx["v1"]["id"], COORDINATOR))
    assert vol1["no_show_strikes"] == 1
    assert vol1["status"] == "ELIGIBLE", "one strike is below the two-strike suspension"
    backfills, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"replaces_signup_id": ctx["sg0"]["id"]}))
    assert meta["total_count"] == 1
    bf = backfills[0]
    assert bf["origin"] == "FLOAT_POOL_BACKFILL"
    assert bf["status"] == "CONFIRMED"
    assert bf["volunteer_id"] == ctx["v2"]["id"], "the only eligible floater takes the seat"


def test_no_show_second_strike_suspends_and_cascades(api):
    """PRD §3.7: "Link two: when the strike count reaches two, an `ELIGIBLE`
    volunteer flips automatically to `SUSPENDED`. Link three: every other
    signup of that volunteer in `APPROVED` or `CONFIRMED` status is cancelled,
    with each signup's `origin` preserved on the cancelled record. Link four:
    each affected shift recomputes its `confirmed_count` and falls from `FULL`
    to `OPEN` wherever the count dropped below `required_headcount`. Link
    five: every freed seat fires seat-open handling."

    Design: Difficulty/transitive_cascade/no_show_strike_suspension_backfill_cascade
    """
    ctx = _setup_strike_cascade(api)
    set_clock("2026-10-04T06:31:00Z")
    validate_success(api_client.mark_no_show(ctx["sg0"]["id"], COORDINATOR))
    set_clock("2026-10-04T08:31:00Z")
    marked = validate_success(api_client.mark_no_show(ctx["sg1"]["id"], COORDINATOR))
    assert marked["status"] == "NO_SHOW"
    vol1 = validate_success(api_client.get_volunteer(ctx["v1"]["id"], COORDINATOR))
    assert vol1["no_show_strikes"] == 2
    assert vol1["status"] == "SUSPENDED"
    sg2 = validate_success(api_client.get_signup(ctx["sg2"]["id"], COORDINATOR))
    assert sg2["status"] == "CANCELLED", "the suspension cascade cancels the third signup"
    backfills, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"replaces_signup_id": ctx["sg2"]["id"]}))
    assert meta["total_count"] == 1
    bf = backfills[0]
    assert bf["origin"] == "FLOAT_POOL_BACKFILL"
    assert bf["status"] == "CONFIRMED"
    assert bf["volunteer_id"] == ctx["v2"]["id"]
    shift2 = validate_success(api_client.get_shift(ctx["s2"]["id"], COORDINATOR))
    assert shift2["confirmed_count"] == 1, "the freed seat is refilled end-to-end"
    assert shift2["understaffed_alert"] is False


# ---------------------------------------------------------------------------
# Float pool selection policy (PRD §3.7)
# ---------------------------------------------------------------------------

def test_float_pool_selector_ranks_fewest_hours_first(api):
    """PRD §3.7: "Candidates are ranked by fewest hours already worked at
    this event — the sum of `credited_hours` across that volunteer's hour logs
    in every status except `REJECTED` — and then by earliest volunteer
    `created_at`; the order is deterministic and total, and resource `id`
    values never participate."

    Design: Corner/complexity_layers/float_pool_selector_ranks_fewest_hours_first
    """
    ctx = setup_event_with_shift(
        publish=True,
        segment_overrides={"segment_code": "SEG-A", "mile_start": 5, "mile_end": 10},
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 2})
    ev = ctx["event"]["id"]
    seg_b = add_segment(ev, segment_code="SEG-B", mile_start=10, mile_end=15)
    s_target = add_shift(ev, ctx["role"]["id"], seg_b["id"],
                         start_at="2026-10-04T11:00:00Z", end_at="2026-10-04T13:00:00Z",
                         required_headcount=1)
    v_a = register_eligible_volunteer(ev, full_name="V Early",
                                      date_of_birth="2000-01-01", float_opt_in=True)
    v_b = register_eligible_volunteer(ev, full_name="V Late",
                                      date_of_birth="2000-01-02", float_opt_in=True)
    v_g = register_eligible_volunteer(ev, full_name="V Goer", date_of_birth="2000-01-03")
    sg_a = create_confirmed_signup(v_a["id"], ctx["shift"]["id"])
    sg_g = create_confirmed_signup(v_g["id"], s_target["id"])
    lock_and_start_race_day(ev)
    # VA works 06:00-08:00 (a 2.00-hour log, left PENDING_VERIFICATION).
    set_clock("2026-10-04T06:00:00Z")
    check_in_signup(sg_a["id"])
    check_out_signup(sg_a["id"], "2026-10-04T08:00:00Z")
    log = fetch_hour_log_for_signup(sg_a["id"])
    assert log["credited_hours"] == pytest.approx(2.0, abs=0.001)
    set_clock("2026-10-04T11:31:00Z")
    validate_success(api_client.mark_no_show(sg_g["id"], COORDINATOR))
    backfills, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"replaces_signup_id": sg_g["id"]}))
    assert meta["total_count"] == 1
    bf = backfills[0]
    assert bf["volunteer_id"] == v_b["id"], \
        "the zero-hour floater outranks the two-hour floater despite earlier creation"
    assert bf["status"] == "CONFIRMED"
    assert bf["origin"] == "FLOAT_POOL_BACKFILL"


def test_float_pool_empty_sets_understaffed_alert(api):
    """PRD §3.7: "When the eligible pool is empty, the attempt raises no
    error; instead the shift's `understaffed_alert` flag is set to true, and
    it remains set until `confirmed_count` again reaches `required_headcount`,
    at which point the alert clears."

    Design: Corner/complexity_layers/float_pool_empty_sets_understaffed_alert
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 1})
    sg = ctx["signups"][0]
    set_clock("2026-10-04T06:31:00Z")
    marked = validate_success(api_client.mark_no_show(sg["id"], COORDINATOR))
    assert marked["status"] == "NO_SHOW", "an empty pool is a documented fallback, not an error"
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["understaffed_alert"] is True
    assert shift["confirmed_count"] == 0
