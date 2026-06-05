"""Lottery draws: deterministic greedy selection, empty-set draw, award
acceptance vs decline, and the win->lapse cascade via the ops sweep.

Difficulty queue: non_linear_state_machine (lottery branch),
transitive_cascade (lottery lapse), boundary_precision_check (empty draw).
Corner queue: calculations (lottery_selection).
"""
from test_helpers import assert_ok
from test_helpers import fixtures as fx


def test_lottery_greedy_skip_oversized(client):
    """PRD 3.3: "if an application's `party_size` is less than or equal to the
    remaining quota, it is selected (moving `submitted -> won`) ... otherwise it
    is not selected (moving `submitted -> lost`). An oversized application is
    skipped without partial award, and a later, smaller application may still
    win against the leftover quota."

    Design: Corner/calculations/lottery_selection_greedy_skip_oversized
    """
    park, pa = fx.base_world(client, "CL01", now_utc="2026-05-10T00:00:00Z")
    a = fx.create_visitor(client)
    b = fx.create_visitor(client)
    c = fx.create_visitor(client)
    draw = fx.create_draw(client, park["id"], pa["id"], daily_quota=5,
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z", max_group_size=6,
                          permit_fee_per_person_cents=1000)
    app_a = fx.submit_application(client, draw["id"], a["id"], 3, preference_rank=1)
    app_b = fx.submit_application(client, draw["id"], b["id"], 4, preference_rank=1)
    app_c = fx.submit_application(client, draw["id"], c["id"], 2, preference_rank=1)
    fx.set_clock(client, "2026-06-02T01:00:00Z")
    drawn = fx.run_draw(client, draw["id"], pa["id"])
    sa = assert_ok(client.get(f"/v1/lottery-applications/{app_a['id']}",
                              role="visitor", user_id=a["id"]))
    sb = assert_ok(client.get(f"/v1/lottery-applications/{app_b['id']}",
                              role="visitor", user_id=b["id"]))
    sc = assert_ok(client.get(f"/v1/lottery-applications/{app_c['id']}",
                              role="visitor", user_id=c["id"]))
    assert sa["status"] == "won"
    assert sb["status"] == "lost"   # 4 > remaining 2
    assert sc["status"] == "won"
    assert drawn["awarded_count"] == 5


def test_empty_draw_zero_awarded(client):
    """PRD 3.3: "When the draw completes, the draw itself moves to `drawn`, with
    `awarded_count` equal to the sum of the winners' party sizes."

    Design: Difficulty/boundary_precision_check/boundary_empty_lottery_draw_zero_applications
    """
    park, pa = fx.base_world(client, "BRCA", now_utc="2026-06-03T00:00:00Z")
    draw = fx.create_draw(client, park["id"], pa["id"], daily_quota=10,
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z")
    drawn = fx.run_draw(client, draw["id"], pa["id"])
    assert drawn["status"] == "drawn"
    assert drawn["awarded_count"] == 0


def test_empty_draw_status_drawn(client):
    """PRD 3.3: "A `park_admin` runs the draw, which may proceed only when the
    draw is `accepting` and `now_utc` is at or after `draw_at`".

    Design: Difficulty/boundary_precision_check/boundary_empty_lottery_draw_zero_applications
    """
    park, pa = fx.base_world(client, "BRC2", now_utc="2026-06-03T00:00:00Z")
    draw = fx.create_draw(client, park["id"], pa["id"], daily_quota=10,
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z")
    drawn = fx.run_draw(client, draw["id"], pa["id"])
    assert drawn["status"] == "drawn"


def _won_application(client, code):
    """Helper: build a draw with one party-2 application, run it so it wins,
    and return (park, pa, visitor, draw, app)."""
    park, pa = fx.base_world(client, code, now_utc="2026-05-10T00:00:00Z")
    v = fx.create_visitor(client)
    draw = fx.create_draw(client, park["id"], pa["id"], daily_quota=6,
                          application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z",
                          permit_fee_per_person_cents=1000)
    app = fx.submit_application(client, draw["id"], v["id"], party_size=2)
    fx.set_clock(client, "2026-06-02T01:00:00Z")
    fx.run_draw(client, draw["id"], pa["id"])
    return park, pa, v, draw, app


def test_won_accept_creates_permit_payment(client):
    """PRD 3.3: "Accepting requires the application to be `won` ... on success it
    moves `won -> awarded` and creates a captured `Payment` of kind
    `lottery_permit` for the per-person fee times the party —
    `permit_fee_per_person_cents` multiplied by `party_size` — storing its id in
    `permit_payment_id`."

    Design: Difficulty/non_linear_state_machine/branching_lottery_application_won_accept_vs_decline
    """
    park, pa, v, draw, app = _won_application(client, "OLYM")
    accepted = assert_ok(
        client.post(f"/v1/lottery-applications/{app['id']}/accept",
                    role="visitor", user_id=v["id"]), 200)
    assert accepted["status"] == "awarded"
    assert accepted["permit_payment_id"] is not None
    pay = assert_ok(client.get(f"/v1/payments/{accepted['permit_payment_id']}",
                               role="visitor", user_id=v["id"]))
    assert pay["amount_cents"] == 2000  # 1000 * 2


def test_won_decline_releases_persons(client):
    """PRD 3.3: "Declining moves `won -> declined` and releases the held persons
    by subtracting `party_size` from the draw's `awarded_count`."

    Design: Difficulty/non_linear_state_machine/branching_lottery_application_won_accept_vs_decline
    """
    park, pa, v, draw, app = _won_application(client, "OLY2")
    declined = assert_ok(
        client.post(f"/v1/lottery-applications/{app['id']}/decline",
                    role="visitor", user_id=v["id"]), 200)
    assert declined["status"] == "declined"
    d = assert_ok(client.get(f"/v1/lottery-draws/{draw['id']}",
                             role="visitor", user_id=v["id"]))
    assert d["awarded_count"] == 0


def test_lottery_win_then_ops_lapse_restores_pool(client):
    """PRD 3.3: "a `won` application whose `award_accept_deadline` has passed
    (`now_utc` strictly after it) is lapsed `won -> declined`, likewise
    subtracting its `party_size` from `awarded_count` to return those persons to
    the pool."

    Design: Difficulty/transitive_cascade/cascade_lottery_draw_win_sets_deadline_then_ops_lapse_releases
    """
    park, pa = fx.base_world(client, "GLAC", now_utc="2026-05-10T00:00:00Z",
                             park_overrides={"utc_offset_minutes": -420})
    v = fx.create_visitor(client)
    draw = fx.create_draw(client, park["id"], pa["id"], objective="half_dome_cables",
                          daily_quota=4, application_close_at="2026-06-01T00:00:00Z",
                          draw_at="2026-06-02T00:00:00Z",
                          permit_fee_per_person_cents=1000)
    app = fx.submit_application(client, draw["id"], v["id"], party_size=2)
    fx.set_clock(client, "2026-06-02T01:00:00Z")
    fx.run_draw(client, draw["id"], pa["id"])
    # award_accept_deadline = draw_at + 72h = 2026-06-05T00:00:00Z; advance past it.
    fx.set_clock(client, "2026-06-06T00:00:00Z")
    fx.run_ops(client)
    app_after = assert_ok(client.get(f"/v1/lottery-applications/{app['id']}",
                                     role="visitor", user_id=v["id"]))
    assert app_after["status"] == "declined"
    d = assert_ok(client.get(f"/v1/lottery-draws/{draw['id']}",
                             role="visitor", user_id=v["id"]))
    assert d["awarded_count"] == 0


def test_lottery_win_bumps_awarded_count(client):
    """PRD 3.3: "Each winning application has its `award_accept_deadline` set to
    72 hours after the draw's `draw_at` and adds its `party_size` to the draw's
    `awarded_count`".

    Design: Difficulty/transitive_cascade/cascade_lottery_draw_win_sets_deadline_then_ops_lapse_releases
    """
    park, pa, v, draw, app = _won_application(client, "GLA2")
    d = assert_ok(client.get(f"/v1/lottery-draws/{draw['id']}",
                             role="visitor", user_id=v["id"]))
    assert d["awarded_count"] == 2
