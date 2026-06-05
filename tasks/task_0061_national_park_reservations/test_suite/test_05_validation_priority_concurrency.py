"""Validation-priority conflicts, ATB pass overlap, optimistic concurrency on
slot version, and idempotency replay/conflict.

Difficulty queue: priority_pair_validation_conflict,
cross_entity_state_dependency (ATB overlap).
Corner queue: cross_cutting_complexity_layers (OCC, idempotency).
"""
from test_helpers import assert_ok, assert_error
from test_helpers import fixtures as fx


# --- priority_state_invalid_beats_business_fiscal_slot_full --------------
def test_state_invalid_beats_slot_full(client):
    """PRD 2.11: "state validity is judged before any temporal-window check, and
    capacity is judged last, so a request that is both in the wrong state and
    over capacity surfaces the state error."
    PRD 3.2: "Confirming requires the reservation to be `held` (otherwise
    `ERR_STATE_INVALID`)".

    Design: Difficulty/priority_pair_validation_conflict/priority_state_invalid_beats_business_fiscal_slot_full
    """
    park, pa = fx.base_world(client, "YELL", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": -420,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=1,
                          release_at="2026-06-05T07:00:00Z", entry_fee_cents=200)
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="ABC123")
    # Cancel it (now cancelled, terminal). Slot is full conceptually from the
    # hold's lifecycle, but the state check must fire first on confirm.
    assert_ok(client.post(f"/v1/timed-entry-reservations/{resv['id']}/cancel",
                          role="visitor", user_id=v["id"]), 200)
    resp = client.post(f"/v1/timed-entry-reservations/{resv['id']}/confirm",
                       role="visitor", user_id=v["id"])
    assert_error(resp, 409, "ERR_STATE_INVALID")


def test_state_invalid_beats_slot_full_double_confirm(client):
    """PRD 2.11: "state validity is judged before any temporal-window check, and
    capacity is judged last, so a request that is both in the wrong state and
    over capacity surfaces the state error."
    PRD 3.2: "Confirming requires the reservation to be `held` (otherwise
    `ERR_STATE_INVALID`)".

    Design: Difficulty/priority_pair_validation_conflict/priority_state_invalid_beats_business_fiscal_slot_full
    """
    park, pa = fx.base_world(client, "YEL2", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": -420,
                                             "timed_entry_required": True})
    v = fx.create_visitor(client)
    # capacity 1: the single confirmed reservation fills the slot.
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=1,
                          release_at="2026-06-05T07:00:00Z", entry_fee_cents=200)
    resv = fx.create_slot_hold(client, slot["id"], v["id"], slot["version"], plate="DEF456")
    assert_ok(client.post(f"/v1/timed-entry-reservations/{resv['id']}/confirm",
                          role="visitor", user_id=v["id"]), 200)
    # Re-confirming an already-confirmed reservation against a now-full slot:
    # the state check (not slot-full) must surface.
    resp = client.post(f"/v1/timed-entry-reservations/{resv['id']}/confirm",
                       role="visitor", user_id=v["id"])
    assert_error(resp, 409, "ERR_STATE_INVALID")


# --- priority_forbidden_beats_business_temporal_lottery_closed -----------
def test_forbidden_beats_lottery_closed(client):
    """PRD 2.11: "Authentication is checked first ... then role/ownership/
    park-scope permission yields `ERR_FORBIDDEN`" — before the temporal-window
    checks. PRD 4: lottery applications are authorized for `visitor` only.

    Design: Difficulty/priority_pair_validation_conflict/priority_forbidden_beats_business_temporal_lottery_closed
    """
    park, pa = fx.base_world(client, "ARCH", now_utc="2026-07-15T00:00:00Z",
                             park_overrides={"utc_offset_minutes": -420})
    fin = fx.create_finance(client)
    v = fx.create_visitor(client)
    # Draw whose application window has already closed (close 2026-07-01).
    draw = fx.create_draw(client, park["id"], pa["id"],
                          application_open_at="2026-05-01T00:00:00Z",
                          application_close_at="2026-07-01T00:00:00Z",
                          draw_at="2026-07-02T00:00:00Z",
                          permit_fee_per_person_cents=1500)
    # Finance (not a visitor) applies -> FORBIDDEN, not LOTTERY_CLOSED.
    resp = client.post(f"/v1/lottery-draws/{draw['id']}/applications",
                       role="finance", user_id=fin["id"],
                       json={"account_id": v["id"], "party_size": 2})
    assert_error(resp, 403, "ERR_FORBIDDEN")


def test_forbidden_beats_lottery_closed_ranger(client):
    """PRD 2.11: "then role/ownership/park-scope permission yields
    `ERR_FORBIDDEN`" — evaluated before "the temporal-window checks
    (`ERR_NOT_YET_RELEASED`, `ERR_OUTSIDE_BOOKING_WINDOW`, `ERR_LOTTERY_CLOSED`,
    ...)". PRD 4: lottery applications are authorized for `visitor` only.

    Design: Difficulty/priority_pair_validation_conflict/priority_forbidden_beats_business_temporal_lottery_closed
    """
    park, pa = fx.base_world(client, "ARC2", now_utc="2026-07-15T00:00:00Z",
                             park_overrides={"utc_offset_minutes": -420})
    rg = fx.create_ranger(client, park["id"])
    v = fx.create_visitor(client)
    # Draw whose application window closed at 2026-07-01 (now is past it).
    draw = fx.create_draw(client, park["id"], pa["id"],
                          application_open_at="2026-05-01T00:00:00Z",
                          application_close_at="2026-07-01T00:00:00Z",
                          draw_at="2026-07-02T00:00:00Z",
                          permit_fee_per_person_cents=1500)
    # A ranger (not a visitor) applying to a closed lottery -> FORBIDDEN wins.
    resp = client.post(f"/v1/lottery-draws/{draw['id']}/applications",
                       role="ranger", user_id=rg["id"],
                       json={"account_id": v["id"], "party_size": 2})
    assert_error(resp, 403, "ERR_FORBIDDEN")


# --- cross_atb_pass_overlap_depends_on_existing_active_pass --------------
def test_atb_pass_overlap_rejected(client):
    """PRD 3.1: "an account may not hold two passes that are both `active` and
    whose validity ranges overlap, where a `senior_lifetime` pass is treated as
    open-ended from its `valid_from`; an overlapping purchase is rejected with
    `ERR_PASS_OVERLAP`."

    Design: Difficulty/cross_entity_state_dependency/cross_atb_pass_overlap_depends_on_existing_active_pass
    """
    fx.set_clock(client, "2026-06-01T00:00:00Z")
    v = fx.create_visitor(client)
    fx.buy_pass(client, v["id"], "annual", "2026-06-01")
    # Second annual valid_from 2026-09-01 overlaps the first (valid to 2027-06-01).
    resp = client.post("/v1/atb-passes", role="visitor", user_id=v["id"],
                       json={"account_id": v["id"], "pass_type": "annual",
                             "valid_from": "2026-09-01"})
    assert_error(resp, 409, "ERR_PASS_OVERLAP")


def test_atb_pass_void_within_window_refunds(client):
    """PRD 3.1: "On a successful void the pass moves `active -> voided`, its
    purchase payment is refunded in full ... and the refunded amount is credited
    to the account's `credit_balance_cents`."

    Design: Difficulty/cross_entity_state_dependency/cross_atb_pass_overlap_depends_on_existing_active_pass
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


# --- Corner: occ_timed_entry_hold_stale_slot_version ---------------------
def test_stale_slot_version_rejected(client):
    """PRD 2.9: "If the slot's current `version` differs — because another writer
    has already placed a hold on the same slot and advanced its version, making
    the client's view of remaining capacity stale — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_timed_entry_hold_stale_slot_version
    """
    park, pa = fx.base_world(client, "CC01", now_utc="2026-06-05T08:00:00Z",
                             park_overrides={"utc_offset_minutes": 0,
                                             "timed_entry_required": True})
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    slot = fx.create_slot(client, park["id"], pa["id"], capacity=5,
                          release_at="2026-06-05T07:00:00Z", entry_fee_cents=200)
    v0 = slot["version"]
    fx.create_slot_hold(client, slot["id"], a["id"], v0, plate="OCC1")  # bumps version
    # b still carries the stale v0.
    resp = client.post("/v1/timed-entry-reservations", role="visitor", user_id=b["id"],
                       json={"slot_id": slot["id"], "account_id": b["id"],
                             "vehicle_plate": "OCC2", "expected_slot_version": v0})
    assert_error(resp, 412, "ERR_STALE_VERSION")


# --- Corner: idempotency_replay_same_key_same_body_returns_original -------
def test_idempotency_replay_returns_original(client):
    """PRD 2.10: "Replaying the same key with an identical request body returns
    the original result rather than creating a duplicate".

    Design: Corner/cross_cutting_complexity_layers/idempotency_replay_same_key_same_body_returns_original
    """
    park, pa = fx.base_world(client, "CC02")
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TGG")
    body = {"campsite_id": site["id"], "account_id": v["id"],
            "check_in": "2026-06-10", "check_out": "2026-06-12", "party_size": 2}
    first = assert_ok(client.post("/v1/camp-reservations", role="visitor",
                                  user_id=v["id"], json=body,
                                  idempotency_key="K2"), 201)
    second = assert_ok(client.post("/v1/camp-reservations", role="visitor",
                                   user_id=v["id"], json=body,
                                   idempotency_key="K2"), 201)
    assert second["id"] == first["id"]


# --- Corner: error_idempotency_conflict_camp -----------------------------
def test_idempotency_conflict_different_body(client):
    """PRD 2.10: "replaying the same key with a *different* request body is
    rejected with `ERR_IDEMPOTENCY_CONFLICT`."

    Design: Corner/errors/error_idempotency_conflict_camp
    """
    park, pa = fx.base_world(client, "ER03")
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TBB")
    body1 = {"campsite_id": site["id"], "account_id": v["id"],
             "check_in": "2026-06-10", "check_out": "2026-06-12", "party_size": 2}
    assert_ok(client.post("/v1/camp-reservations", role="visitor", user_id=v["id"],
                          json=body1, idempotency_key="K1"), 201)
    body2 = {"campsite_id": site["id"], "account_id": v["id"],
             "check_in": "2026-07-10", "check_out": "2026-07-12", "party_size": 4}
    resp = client.post("/v1/camp-reservations", role="visitor", user_id=v["id"],
                       json=body2, idempotency_key="K1")
    assert_error(resp, 409, "ERR_IDEMPOTENCY_CONFLICT")
