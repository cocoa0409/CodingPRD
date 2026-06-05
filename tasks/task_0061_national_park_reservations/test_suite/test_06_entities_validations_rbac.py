"""Breadth coverage: entity creation/defaults/types/not-found, state-machine
initial/invalid/terminal transitions, business validations, RBAC, and the
remaining endpoint/error claims.

Corner queue: entities, state_machines, validations, endpoints, errors, rbac.
"""
from test_helpers import assert_ok, assert_error
from test_helpers import fixtures as fx


# =========================================================================
# entities
# =========================================================================
def test_create_account_returns_active_zero_balance(client):
    """PRD 3.1: "A new account is created with `status` set to `active` (the
    alternative is `suspended`) and a `credit_balance_cents` of 0".

    Design: Corner/entities/create_account_returns_201_with_fields
    """
    acct = assert_ok(client.post("/v1/accounts", role="system", user_id="seed",
                                 json={"email": "c1@x.com", "full_name": "C1",
                                       "birth_date": "1990-01-01"}), 201)
    assert acct["status"] == "active"
    assert acct["credit_balance_cents"] == 0


def test_get_account_not_found(client):
    """PRD 2.11: "Existence of every path- and body-referenced resource is
    checked next, yielding `ERR_NOT_FOUND`."

    Design: Corner/entities/get_account_not_found
    """
    resp = client.get("/v1/accounts/00000000-0000-0000-0000-000000000000",
                      role="system", user_id="seed")
    assert_error(resp, 404, "ERR_NOT_FOUND")


def test_account_email_required(client):
    """PRD 3.1: "A new principal registers by supplying an `email`, a
    `full_name`, and a `birth_date`". PRD 2.11: field-level schema validation
    yields `ERR_VALIDATION`.

    Design: Corner/entities/account_email_required_field_missing
    """
    resp = client.post("/v1/accounts", role="system", user_id="seed",
                       json={"full_name": "NoEmail", "birth_date": "1990-01-01"})
    assert_error(resp, 400, "ERR_VALIDATION")


def test_account_role_defaults_visitor(client):
    """PRD 3.1: "optionally a `role` (defaulting to `visitor`)".

    Design: Corner/entities/account_role_default_visitor
    """
    acct = assert_ok(client.post("/v1/accounts", role="system", user_id="seed",
                                 json={"email": "def@x.com", "full_name": "Def",
                                       "birth_date": "1990-01-01"}), 201)
    assert acct["role"] == "visitor"


def test_campsite_invalid_site_type(client):
    """PRD 3.5: "a `site_type` of `tent`, `rv`, or `group`". An out-of-enum value
    fails field-level schema validation (PRD 2.11 -> `ERR_VALIDATION`).

    Design: Corner/entities/campsite_invalid_site_type_enum
    """
    park = fx.create_park(client, "EN01", utc_offset_minutes=0)
    pa = fx.create_park_admin(client, park["id"])
    resp = client.post("/v1/campsites", role="park_admin", user_id=pa["id"],
                       json={"park_id": park["id"], "site_number": "X1",
                             "site_type": "cabin", "max_occupancy": 4,
                             "base_nightly_cents": 4000})
    assert_error(resp, 400, "ERR_VALIDATION")


def test_clock_has_no_version(client):
    """PRD 2.4: "The `Clock` resource is the sole exception: it is a singleton
    that carries only `id` and `created_at`, and it has neither an `updated_at`
    nor a `version`."

    Design: Corner/entities/clock_immutable_no_version_field
    """
    from datetime import datetime, timezone

    def _instant(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)

    fx.set_clock(client, "2026-06-01T00:00:00Z")
    v = fx.create_visitor(client)
    clk = assert_ok(client.get("/v1/_clock", role="visitor", user_id=v["id"]))
    assert _instant(clk["now_utc"]) == _instant("2026-06-01T00:00:00Z")
    assert "version" not in clk


def test_slot_list_filtered_by_park(client):
    """PRD 4: "GET /v1/timed-entry-slots | List slots (filter by park_id,
    entry_date)".

    Design: Corner/entities/timed_entry_slot_fk_park_reverse_list
    """
    park, pa = fx.base_world(client, "FK01",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    slot = fx.create_slot(client, park["id"], pa["id"], entry_date="2026-06-05",
                          window_start_local="07:00", window_end_local="09:00",
                          capacity=5, release_at="2026-06-01T00:00:00Z")
    v = fx.create_visitor(client)
    resp = client.get("/v1/timed-entry-slots", role="visitor", user_id=v["id"],
                      params={"park_id": park["id"]})
    data = assert_ok(resp)
    ids = [s["id"] for s in data]
    assert slot["id"] in ids
    assert all(s["park_id"] == park["id"] for s in data)


# =========================================================================
# state_machines
# =========================================================================
def test_timed_entry_confirm_from_cancelled_invalid(client):
    """PRD 3.2: "Confirming requires the reservation to be `held` (otherwise
    `ERR_STATE_INVALID`)".

    Design: Corner/state_machines/timed_entry_confirm_from_cancelled_invalid_state
    """
    park, pa = fx.base_world(client, "SM01", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=3,
                          release_at="2026-06-05T07:00:00Z")
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="SMC1")
    assert_ok(client.post(f"/v1/timed-entry-reservations/{resv['id']}/cancel",
                          role="visitor", user_id=v["id"]), 200)
    resp = client.post(f"/v1/timed-entry-reservations/{resv['id']}/confirm",
                       role="visitor", user_id=v["id"])
    assert_error(resp, 409, "ERR_STATE_INVALID")


def test_timed_entry_initial_state_held(client):
    """PRD 3.2: "On a successful create, the reservation enters `held` with
    `hold_expires_at` set to fifteen minutes after `now_utc`".

    Design: Corner/state_machines/timed_entry_reservation_initial_state_held
    """
    park, pa = fx.base_world(client, "SM02", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=3,
                          release_at="2026-06-05T07:00:00Z")
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="INIT1")
    assert resv["status"] == "held"
    assert resv["hold_expires_at"] is not None


def test_backcountry_cancel_from_expired_terminal(client):
    """PRD 3.4: "The same housekeeping sweep that handles other holds expires a
    `held` permit whose `hold_expires_at` has passed, moving it `held ->
    expired`". A cancel on a terminal permit is an invalid state
    (PRD 2.11 -> `ERR_STATE_INVALID`).

    Design: Corner/state_machines/backcountry_cancel_from_expired_terminal_locked
    """
    park, pa = fx.base_world(client, "SM03")
    v = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"], daily_exit_quota=5)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=5)
    permit = fx.create_backcountry_permit(
        client, park["id"], v["id"], th["id"], "2026-06-20", 1, 2,
        [{"zone_id": z["id"], "date": "2026-06-20"}])
    # Advance past hold_expires_at (now+15m) and sweep.
    fx.set_clock(client, "2026-06-01T01:00:00Z")
    fx.run_ops(client)
    permit_after = assert_ok(client.get(f"/v1/backcountry-permits/{permit['id']}",
                                        role="visitor", user_id=v["id"]))
    assert permit_after["status"] == "expired"
    resp = client.post(f"/v1/backcountry-permits/{permit['id']}/cancel",
                       role="visitor", user_id=v["id"])
    assert_error(resp, 409, "ERR_STATE_INVALID")


def test_atb_void_credits_balance(client):
    """PRD 3.1: "On a successful void the pass moves `active -> voided`, its
    purchase payment is refunded in full ... and the refunded amount is credited
    to the account's `credit_balance_cents`."

    Design: Corner/state_machines/atb_pass_void_compensation_full_refund
    """
    fx.set_clock(client, "2026-06-01T00:00:00Z")
    v = fx.create_visitor(client)
    fin = fx.create_finance(client)
    pass_ = fx.buy_pass(client, v["id"], "annual", "2026-06-01")
    voided = assert_ok(client.post(f"/v1/atb-passes/{pass_['id']}/void",
                                   role="finance", user_id=fin["id"]), 200)
    assert voided["status"] == "voided"
    acct = assert_ok(client.get(f"/v1/accounts/{v['id']}", role="visitor",
                                user_id=v["id"]))
    assert acct["credit_balance_cents"] == 8000


# =========================================================================
# validations
# =========================================================================
def test_error_email_taken(client):
    """PRD 3.1: "The `email` must be unique across all accounts; a collision is
    rejected with `ERR_EMAIL_TAKEN`."

    Design: Corner/validations/error_email_taken_on_duplicate_account
    """
    assert_ok(client.post("/v1/accounts", role="system", user_id="seed",
                          json={"email": "dup@x.com", "full_name": "First",
                                "birth_date": "1990-01-01"}), 201)
    resp = client.post("/v1/accounts", role="system", user_id="seed",
                       json={"email": "dup@x.com", "full_name": "Second",
                             "birth_date": "1991-01-01"})
    assert_error(resp, 409, "ERR_EMAIL_TAKEN")


def test_error_home_park_required_for_ranger(client):
    """PRD 3.1: "If the requested `role` is `ranger` or `park_admin`, a
    `home_park_id` is mandatory, and its absence is rejected with
    `ERR_HOME_PARK_REQUIRED`".

    Design: Corner/validations/error_home_park_required_for_ranger
    """
    resp = client.post("/v1/accounts", role="system", user_id="seed",
                       json={"email": "rg@x.com", "full_name": "RG",
                             "birth_date": "1980-01-01", "role": "ranger"})
    assert_error(resp, 400, "ERR_HOME_PARK_REQUIRED")


def test_error_age_requirement_senior_pass(client):
    """PRD 3.1: "The senior types — `senior_annual` and `senior_lifetime` —
    require the purchasing account to be at least 62 years old as of
    `valid_from` ... a younger applicant is rejected with `ERR_AGE_REQUIREMENT`."

    Design: Corner/validations/error_age_requirement_senior_pass
    """
    fx.set_clock(client, "2026-06-01T00:00:00Z")
    v = fx.create_visitor(client, birth_date="1966-06-01")  # age 60 on valid_from
    resp = client.post("/v1/atb-passes", role="visitor", user_id=v["id"],
                       json={"account_id": v["id"], "pass_type": "senior_annual",
                             "valid_from": "2026-06-01"})
    assert_error(resp, 400, "ERR_AGE_REQUIREMENT")


def test_error_group_config_missing(client):
    """PRD 3.5: "for a group site, missing any of these three is rejected with
    `ERR_GROUP_CONFIG_MISSING`".

    Design: Corner/validations/error_group_config_missing
    """
    park = fx.create_park(client, "VG01", utc_offset_minutes=0)
    pa = fx.create_park_admin(client, park["id"])
    resp = client.post("/v1/campsites", role="park_admin", user_id=pa["id"],
                       json={"park_id": park["id"], "site_number": "GBAD",
                             "site_type": "group", "max_occupancy": 30,
                             "base_nightly_cents": 0})
    assert_error(resp, 400, "ERR_GROUP_CONFIG_MISSING")


def test_error_not_yet_released(client):
    """PRD 3.2: "Booking is permitted only once the slot has released — `now_utc`
    must be at or after `release_at`, otherwise `ERR_NOT_YET_RELEASED`."

    Design: Corner/validations/error_not_yet_released_timed_entry
    """
    park, pa = fx.base_world(client, "VR01",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    # now=2026-06-01; release_at 2026-06-04 is in the future.
    slot = fx.create_slot(client, park["id"], pa["id"], entry_date="2026-06-05",
                          window_start_local="07:00", window_end_local="09:00",
                          capacity=5, release_at="2026-06-04T00:00:00Z")
    resp = client.post("/v1/timed-entry-reservations", role="visitor", user_id=v["id"],
                       json={"slot_id": slot["id"], "account_id": v["id"],
                             "vehicle_plate": "EARLY1",
                             "expected_slot_version": slot["version"]})
    assert_error(resp, 409, "ERR_NOT_YET_RELEASED")


def test_error_duplicate_application(client):
    """PRD 3.3: "An account may have at most one non-terminal application per
    draw; a second is rejected with `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/validations/error_duplicate_application_same_account_draw
    """
    park, pa = fx.base_world(client, "VD01", now_utc="2026-05-10T00:00:00Z")
    v = fx.create_visitor(client)
    draw = fx.create_draw(client, park["id"], pa["id"],
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z")
    fx.submit_application(client, draw["id"], v["id"], party_size=2)
    resp = client.post(f"/v1/lottery-draws/{draw['id']}/applications",
                       role="visitor", user_id=v["id"],
                       json={"account_id": v["id"], "party_size": 3})
    assert_error(resp, 409, "ERR_DUPLICATE_APPLICATION")


def test_error_over_occupancy(client):
    """PRD 3.5: "The `party_size` must not exceed the campsite's
    `max_occupancy`, otherwise `ERR_OVER_OCCUPANCY`."

    Design: Corner/validations/error_over_occupancy_camp
    """
    park, pa = fx.base_world(client, "OC01")
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TR",
                              site_type="tent", max_occupancy=4, base_nightly_cents=4000)
    resp = client.post("/v1/camp-reservations", role="visitor", user_id=v["id"],
                       json={"campsite_id": site["id"], "account_id": v["id"],
                             "check_in": "2026-06-10", "check_out": "2026-06-12",
                             "party_size": 5})
    assert_error(resp, 409, "ERR_OVER_OCCUPANCY")


def test_error_dates_available_cannot_waitlist(client):
    """PRD 3.7: "A waitlist join is allowed only when the exact half-open range
    from `check_in` to `check_out` on that campsite is currently *not* bookable
    ... If the range is in fact currently bookable, the join is refused with
    `ERR_DATES_AVAILABLE`."

    Design: Corner/validations/error_dates_available_cannot_waitlist
    """
    park, pa = fx.base_world(client, "DA01")
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TS")
    resp = client.post("/v1/waitlist-entries", role="visitor", user_id=v["id"],
                       json={"campsite_id": site["id"], "account_id": v["id"],
                             "check_in": "2026-06-25", "check_out": "2026-06-27",
                             "party_size": 2,
                             "expected_campsite_version": site["version"]})
    assert_error(resp, 409, "ERR_DATES_AVAILABLE")


def test_error_void_not_allowed_after_30_days(client):
    """PRD 3.1: "The void is permitted only when `now_utc` is at or before 30
    days after the pass's `created_at` ... either failing condition yields
    `ERR_VOID_NOT_ALLOWED`."

    Design: Corner/validations/error_void_not_allowed_after_30_days
    """
    fx.set_clock(client, "2026-06-01T00:00:00Z")
    v = fx.create_visitor(client)
    fin = fx.create_finance(client)
    pass_ = fx.buy_pass(client, v["id"], "annual", "2026-06-01")
    fx.set_clock(client, "2026-07-05T00:00:00Z")  # >30 days after created_at
    resp = client.post(f"/v1/atb-passes/{pass_['id']}/void",
                       role="finance", user_id=fin["id"])
    assert_error(resp, 409, "ERR_VOID_NOT_ALLOWED")


def test_error_invalid_itinerary_nights_mismatch(client):
    """PRD 3.4: "the length of `zone_nights` must equal `nights`, and every
    element must carry both a zone and a date; any violation is rejected with
    `ERR_INVALID_ITINERARY`."

    Design: Corner/validations/error_invalid_itinerary_nights_mismatch
    """
    park, pa = fx.base_world(client, "IT01")
    v = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"], daily_exit_quota=5)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=5)
    resp = client.post("/v1/backcountry-permits", role="visitor", user_id=v["id"],
                       json={"park_id": park["id"], "account_id": v["id"],
                             "trailhead_id": th["id"], "entry_date": "2026-06-20",
                             "nights": 2, "party_size": 2,
                             "zone_nights": [
                                 {"zone_id": z["id"], "date": "2026-06-20"},
                                 {"zone_id": z["id"], "date": "2026-06-21"},
                                 {"zone_id": z["id"], "date": "2026-06-22"}]})
    assert_error(resp, 400, "ERR_INVALID_ITINERARY")


# =========================================================================
# endpoints / errors
# =========================================================================
def test_lottery_application_fee_nonrefundable_on_withdraw(client):
    """PRD 3.3: "A visitor may withdraw a `submitted` application while the draw
    is still `accepting` and `now_utc` is before `application_close_at`, moving
    it `submitted -> withdrawn`; the non-refundable application fee stays
    captured."

    Design: Corner/endpoints/lottery_application_fee_nonrefundable_on_withdraw
    """
    park, pa = fx.base_world(client, "EP02", now_utc="2026-05-10T00:00:00Z")
    v = fx.create_visitor(client)
    draw = fx.create_draw(client, park["id"], pa["id"],
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z",
                          permit_fee_per_person_cents=1500, application_fee_cents=1000)
    app = fx.submit_application(client, draw["id"], v["id"], party_size=2)
    withdrawn = assert_ok(client.post(f"/v1/lottery-applications/{app['id']}/withdraw",
                                      role="visitor", user_id=v["id"]), 200)
    assert withdrawn["status"] == "withdrawn"
    acct = assert_ok(client.get(f"/v1/accounts/{v['id']}", role="visitor",
                                user_id=v["id"]))
    assert acct["credit_balance_cents"] == 0


def test_ops_run_marks_timed_entry_no_show(client):
    """PRD 3.2: "a `confirmed` reservation whose slot window-end (converted to
    UTC) has passed without a check-in moves `confirmed -> no_show`,
    decrementing the slot's `booked_count` while the payment stays captured."

    Design: Corner/endpoints/ops_run_marks_timed_entry_no_show
    """
    park, pa = fx.base_world(client, "EP03", now_utc="2026-06-08T06:00:00Z",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], entry_date="2026-06-08",
                          window_start_local="07:00", window_end_local="09:00",
                          capacity=3, release_at="2026-06-08T06:00:00Z",
                          entry_fee_cents=200)
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="NSH1")
    assert_ok(client.post(f"/v1/timed-entry-reservations/{resv['id']}/confirm",
                          role="visitor", user_id=v["id"]), 200)
    fx.set_clock(client, "2026-06-08T10:00:00Z")  # past window_end (09:00 UTC)
    fx.run_ops(client)
    resv_after = assert_ok(client.get(f"/v1/timed-entry-reservations/{resv['id']}",
                                      role="visitor", user_id=v["id"]))
    assert resv_after["status"] == "no_show"
    slot_after = assert_ok(client.get(f"/v1/timed-entry-slots/{slot['id']}",
                                      role="visitor", user_id=v["id"]))
    assert slot_after["booked_count"] == 0


def test_error_draw_not_ready_before_draw_at(client):
    """PRD 3.3: "A `park_admin` runs the draw, which may proceed only when the
    draw is `accepting` and `now_utc` is at or after `draw_at`; otherwise
    `ERR_DRAW_NOT_READY`."

    Design: Corner/errors/error_draw_not_ready_before_draw_at
    """
    park, pa = fx.base_world(client, "ER02", now_utc="2026-05-10T00:00:00Z")
    draw = fx.create_draw(client, park["id"], pa["id"],
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z")
    resp = client.post(f"/v1/lottery-draws/{draw['id']}/draw",
                       role="park_admin", user_id=pa["id"])
    assert_error(resp, 409, "ERR_DRAW_NOT_READY")


# =========================================================================
# rbac
# =========================================================================
def test_rbac_visitor_cannot_run_draw(client):
    """PRD 4: "POST /v1/lottery-draws/{id}/draw | Run the deterministic draw |
    park_admin". A non-permitted role is rejected with `ERR_FORBIDDEN`
    (PRD 2.1).

    Design: Corner/rbac/rbac_visitor_cannot_run_draw
    """
    park, pa = fx.base_world(client, "RB01", now_utc="2026-06-03T00:00:00Z")
    v = fx.create_visitor(client)
    draw = fx.create_draw(client, park["id"], pa["id"],
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z")
    resp = client.post(f"/v1/lottery-draws/{draw['id']}/draw",
                       role="visitor", user_id=v["id"])
    assert_error(resp, 403, "ERR_FORBIDDEN")


def test_rbac_ranger_cannot_void_pass(client):
    """PRD 4: "POST /v1/atb-passes/{id}/void | Void a pass for a full refund |
    finance". A non-permitted role is rejected with `ERR_FORBIDDEN` (PRD 2.1).

    Design: Corner/rbac/rbac_ranger_cannot_void_pass
    """
    park, pa = fx.base_world(client, "RB02")
    rg = fx.create_ranger(client, park["id"])
    v = fx.create_visitor(client)
    pass_ = fx.buy_pass(client, v["id"], "annual", "2026-06-01")
    resp = client.post(f"/v1/atb-passes/{pass_['id']}/void",
                       role="ranger", user_id=rg["id"])
    assert_error(resp, 403, "ERR_FORBIDDEN")


def test_rbac_visitor_cannot_confirm_others_reservation(client):
    """PRD 2.1: "A request whose role is known but is not permitted the operation
    — including a visitor acting on another visitor's resource ... — is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_visitor_cannot_confirm_others_reservation
    """
    park, pa = fx.base_world(client, "RB03")
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TEE")
    r = fx.create_camp_reservation(client, site["id"], a["id"],
                                   "2026-06-10", "2026-06-12", party_size=2)
    resp = client.post(f"/v1/camp-reservations/{r['id']}/confirm",
                       role="visitor", user_id=b["id"])
    assert_error(resp, 403, "ERR_FORBIDDEN")
