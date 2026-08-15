"""Drivers, waivers, safety inspections, clearance, and coach assignment."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_track, make_coach, make_open_track_day, make_block, make_booking,
    make_driver, get_driver, sign_waiver, inspect_driver, approve_booking,
    pay_booking, assign_coach, set_clock,
    setup_booking_with_driver, setup_open_day_with_block,
    assert_waiver, assert_safety_inspection,
    FAR_FUTURE_ISO,
    TEST_USERS, make_organizer_headers,
)

OPS = TEST_USERS["trackops_headers"]


def test_signed_and_passed_driver_not_cleared_when_booking_pending(api):
    """PRD §3.4: "The two flags meet in `cleared_to_run`, a derived boolean
    that is true only when the driver's `waiver_status` is `SIGNED`,
    `safety_status` is `PASSED`, the booking stands `APPROVED`, and
    `payment_status` is `CAPTURED`; it is recomputed whenever any of those
    four inputs changes."

    Design: Difficulty/cross_entity_state_dependency/driver_cleared_gated_by_booking_and_inspection
    """
    env = setup_booking_with_driver("2026-09-05", "org14", sign=True,
                                    inspect=True)
    driver = env["driver"]
    assert driver["waiver_status"] == "SIGNED"
    assert driver["safety_status"] == "PASSED"
    assert env["booking"]["approval_status"] == "PENDING"
    assert driver["cleared_to_run"] is False, \
        "booking not APPROVED and payment not CAPTURED block clearance"


def test_driver_cleared_after_approval_and_capture(api):
    """PRD §3.4: "The two flags meet in `cleared_to_run`, a derived boolean
    that is true only when the driver's `waiver_status` is `SIGNED`,
    `safety_status` is `PASSED`, the booking stands `APPROVED`, and
    `payment_status` is `CAPTURED`; it is recomputed whenever any of those
    four inputs changes."

    Design: Difficulty/cross_entity_state_dependency/driver_cleared_gated_by_booking_and_inspection
    """
    env = setup_booking_with_driver("2026-09-05", "org14", approve=True,
                                    sign=True, inspect=True, pay=True)
    booking = env["booking"]
    assert booking["approval_status"] == "APPROVED"
    assert booking["payment_status"] == "CAPTURED"
    assert env["driver"]["cleared_to_run"] is True, \
        "all four clearance inputs satisfied"


def test_waiver_computed_expires_at_utc(api):
    """PRD §3.4: "The record's `expires_at_utc` is computed as `signed_at_utc`
    plus `WAIVER_TTL_HOURS` hours, and the driver's `waiver_status` becomes
    `SIGNED`." PRD §2.4: "Three record types are append-only evidence and
    carry only `id` and `created_at`: waivers, safety inspections, and noise
    readings have neither `updated_at` nor `version`."

    Design: Corner/entities/waiver_computed_expires_at_utc
    """
    env = setup_booking_with_driver("2026-09-10", "orgW")
    tid, tdid, rbid = (env["track"]["id"], env["day"]["id"],
                       env["block"]["id"])
    bid, did = env["booking"]["id"], env["driver"]["id"]
    resp = api.submit_waiver(
        tid, tdid, rbid, bid, did,
        {"signed_at_utc": "2026-08-01T10:00:00Z",
         "signature_payload_hash": "h"},
        make_organizer_headers("orgW"))
    waiver = validate_success(resp, 201)
    assert_waiver(waiver)  # append-only: no updated_at, no version
    assert waiver["expires_at_utc"] > waiver["signed_at_utc"], \
        "server computes the expiry as a positive offset from signing"
    driver = get_driver(tid, tdid, rbid, bid, did)
    assert driver["waiver_status"] == "SIGNED"


def test_safety_inspection_computed_result(api):
    """PRD §3.4: "The officer submits `inspector_user_id`, `helmet_ok`, and
    `harness_ok`; the server stamps `inspected_at_utc` from the logical clock
    and computes the `result` — `PASSED` when both `helmet_ok` and
    `harness_ok` are true, `FAILED` otherwise — and the driver's
    `safety_status` follows the `result`."

    Design: Corner/entities/safety_inspection_computed_result
    """
    env = setup_booking_with_driver("2026-09-11", "orgS")
    tid, tdid, rbid = (env["track"]["id"], env["day"]["id"],
                       env["block"]["id"])
    bid, did = env["booking"]["id"], env["driver"]["id"]
    inspection = inspect_driver(tid, tdid, rbid, bid, did,
                                inspector_user_id="so1",
                                helmet_ok=True, harness_ok=False)
    assert_safety_inspection(inspection)
    assert inspection["result"] == "FAILED", "harness_ok=false forces FAILED"
    driver = get_driver(tid, tdid, rbid, bid, did)
    assert driver["safety_status"] == "FAILED"


def test_segregation_of_duties_inspector_is_organizer(api):
    """PRD §3.4: "Segregation of duties is enforced: `inspector_user_id` must
    differ from the booking's `organizer_user_id`, or the submission is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (422)."

    Design: Corner/validations/segregation_of_duties_inspector_is_organizer
    """
    env = setup_booking_with_driver("2026-09-25", "orgX")
    resp = api.inspect_driver(
        env["track"]["id"], env["day"]["id"], env["block"]["id"],
        env["booking"]["id"], env["driver"]["id"],
        {"inspector_user_id": "orgX", "helmet_ok": True, "harness_ok": True},
        TEST_USERS["safety_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_coach_cert_insufficient_for_novice_requires_intermediate(api):
    """PRD §3.1: "Certificate sufficiency: a booking in the `NOVICE` run group
    requires a coach holding `INTERMEDIATE` or `RACE` certification, and a
    `RACE` booking requires a `RACE`-certified coach; an under-certified
    assignment is rejected with `ERR_COACH_CERT_INSUFFICIENT` (422)."

    Design: Corner/validations/coach_cert_insufficient_for_novice_requires_intermediate
    """
    track = make_track(name="V8")
    coach = make_coach(track["id"], cert_level="BASIC", full_name="Basic")
    day = make_open_track_day(track["id"], "2026-09-27")
    block = make_block(track["id"], day["id"])
    booking = make_booking(track["id"], day["id"], block["id"], "oV8",
                           run_group_class="NOVICE")
    resp = api.assign_coach(track["id"], day["id"], block["id"],
                            booking["id"], {"coach_id": coach["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_COACH_CERT_INSUFFICIENT)


def test_coach_overloaded_at_max_bookings(api):
    """PRD §3.1: "Load: a coach may serve at most three bookings on the same
    track day — a fourth simultaneous assignment draws `ERR_COACH_OVERLOADED`
    (409)."

    Design: Corner/validations/coach_overloaded_at_max_bookings
    """
    track = make_track(name="V9", run_group_capacity=20)
    coach = make_coach(track["id"], cert_level="INTERMEDIATE", full_name="Busy")
    day = make_open_track_day(track["id"], "2026-09-28")
    block = make_block(track["id"], day["id"], max_group_size=20)
    tid, tdid, rbid = track["id"], day["id"], block["id"]
    booking_ids = [
        make_booking(tid, tdid, rbid, f"oV9{suffix}", run_group_class="NOVICE")["id"]
        for suffix in ("a", "b", "c", "d")
    ]
    for bid in booking_ids[:3]:
        assign_coach(tid, tdid, rbid, bid, coach["id"])
        approve_booking(tid, tdid, rbid, bid)
    # Coach now serves three APPROVED bookings on this day; the fourth
    # simultaneous assignment must be refused.
    resp = api.assign_coach(tid, tdid, rbid, booking_ids[3],
                            {"coach_id": coach["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_COACH_OVERLOADED)


def test_coach_roll_tracks_approved_booking(api):
    """PRD §3.1: "A coach's `assigned_booking_ids` is a computed roll of the
    bookings currently attached to that coach — bookings whose `coach_id`
    references the coach and whose `approval_status` stands at `APPROVED`."
    PRD §3.3: "Success sets the booking's `coach_id` and refreshes the coach's
    `assigned_booking_ids`."

    Design: Difficulty/compensating_invariant/coach_assignment_conservation
    """
    track = make_track(name="Monza")
    coach = make_coach(track["id"], cert_level="INTERMEDIATE", full_name="Carol")
    day = make_open_track_day(track["id"], "2026-09-09")
    block = make_block(track["id"], day["id"])
    booking = make_booking(track["id"], day["id"], block["id"], "orgC18",
                           run_group_class="NOVICE")
    assign_coach(track["id"], day["id"], block["id"], booking["id"],
                 coach["id"])
    approve_booking(track["id"], day["id"], block["id"], booking["id"])
    coach_after = validate_success(api.get_coach(track["id"], coach["id"], OPS))
    assert coach_after["assigned_booking_ids"] == [booking["id"]]


def test_coach_roll_empties_after_cancel(api):
    """PRD §3.9: "the assigned coach, if any, is detached — the booking's
    `coach_id` is nulled and the coach's `assigned_booking_ids` refreshed".
    PRD §3.1: "A coach's `assigned_booking_ids` is a computed roll of the
    bookings currently attached to that coach — bookings whose `coach_id`
    references the coach and whose `approval_status` stands at `APPROVED`."

    Design: Difficulty/compensating_invariant/coach_assignment_conservation
    """
    track = make_track(name="Monza")
    coach = make_coach(track["id"], cert_level="INTERMEDIATE", full_name="Carol")
    day = make_open_track_day(track["id"], "2026-09-09")
    block = make_block(track["id"], day["id"])
    booking = make_booking(track["id"], day["id"], block["id"], "orgC18",
                           run_group_class="NOVICE")
    assign_coach(track["id"], day["id"], block["id"], booking["id"],
                 coach["id"])
    approve_booking(track["id"], day["id"], block["id"], booking["id"])
    validate_success(api.cancel_booking(
        track["id"], day["id"], block["id"], booking["id"],
        {"reason": "CUSTOMER"}, make_organizer_headers("orgC18")))
    coach_after = validate_success(api.get_coach(track["id"], coach["id"], OPS))
    assert coach_after["assigned_booking_ids"] == [], \
        "no ghost reference may remain after the cancel"


def test_waiver_expiry_reconciled_by_run_ops(api):
    """PRD §3.4: "Expiry is swept by the operations checkpoint described in
    §3.6 — any waiver whose `expires_at_utc` is strictly earlier than the
    current logical time flips its driver's `waiver_status` to `EXPIRED`."
    PRD §3.6: "The operations checkpoint, a `TrackOps`-run sweep, bumps
    `ops_run_index` by one, expires every waiver whose `expires_at_utc` is
    strictly before the current logical time (flipping those drivers'
    `waiver_status` to `EXPIRED`), recomputes posture, and advances the day's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_after_waiver_expiry
    """
    set_clock("2026-08-01T00:00:00Z")
    env = setup_booking_with_driver("2026-10-06", "oX2", approve=True,
                                    sign=True, inspect=True, pay=True)
    tid, tdid, rbid = (env["track"]["id"], env["day"]["id"],
                       env["block"]["id"])
    bid, did = env["booking"]["id"], env["driver"]["id"]
    assert env["driver"]["cleared_to_run"] is True
    # Advance the logical clock years beyond any plausible waiver lifetime.
    set_clock(FAR_FUTURE_ISO)
    validate_success(api.run_ops(tid, tdid, OPS))
    driver = get_driver(tid, tdid, rbid, bid, did)
    assert driver["waiver_status"] == "EXPIRED"
    assert driver["cleared_to_run"] is False, \
        "an expired waiver must revoke clearance"
