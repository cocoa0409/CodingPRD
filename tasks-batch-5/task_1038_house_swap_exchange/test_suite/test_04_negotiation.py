"""The negotiation loop (counter/repropose cycle) and lazy TTL expiry."""
from test_helpers import (
    validate_success,
    counter_payload,
    make_admin_headers,
    set_clock, register_member, subscribe_and_activate, verify_identity,
    create_active_listing, add_window, open_points_request, get_member,
    make_member_headers,
)

ADMIN = make_admin_headers()


def _proposed_points_request(ppn=100):
    set_clock("2026-07-01T00:00:00Z")
    guest = register_member(full_name="Guest", home_city="Boston")
    host = register_member(full_name="Host", home_city="Denver")
    subscribe_and_activate(guest["id"], "PLUS")
    verify_identity(host["id"])
    listing = create_active_listing(host["id"], points_per_night=ppn)
    add_window(listing["id"], host["id"], "2026-07-25", "2026-07-27")
    req = open_points_request(guest["id"], listing["id"], "2026-07-10", "2026-07-12")
    return guest, host, listing, req


# ── Difficulty 3a: PROPOSED <-> COUNTERED cycle ──────────────────────────────
def test_host_counter_moves_request_to_countered(api):
    """PRD §3.4: "The host may counter a `PROPOSED` request, moving it
    `PROPOSED → COUNTERED`; only the target listing's owner may do so and only while
    the request is `PROPOSED`."

    Design: Difficulty/non_linear_state_machine/exchange_request_counter_repropose_cycle
    """
    guest, host, listing, req = _proposed_points_request()
    res = api.counter_exchange_request(
        req["id"], counter_payload("2026-07-14", "2026-07-16"), make_member_headers(host["id"]))
    countered = validate_success(res, 200)
    assert countered["status"] == "COUNTERED"


def test_requester_repropose_returns_request_to_proposed(api):
    """PRD §3.4: "The requester answers a counter by re-proposing, moving the
    request `COUNTERED → PROPOSED`; only the original requester may do so and only
    while the request is `COUNTERED`. ... This loop between `PROPOSED` and
    `COUNTERED` can repeat as many times as the two parties need."

    Design: Difficulty/non_linear_state_machine/exchange_request_counter_repropose_cycle
    """
    guest, host, listing, req = _proposed_points_request()
    countered = validate_success(api.counter_exchange_request(
        req["id"], counter_payload("2026-07-14", "2026-07-16"), make_member_headers(host["id"])), 200)
    assert countered["status"] == "COUNTERED"
    reproposed = validate_success(api.repropose_exchange_request(
        req["id"], counter_payload("2026-07-14", "2026-07-16"), make_member_headers(guest["id"])), 200)
    assert reproposed["status"] == "PROPOSED"


# ── Corner: lazy TTL expiry releases the hold ────────────────────────────────
def test_request_auto_expires_after_ttl(api):
    """PRD §3.3: "sets the request's `expires_at` to the creation instant plus the
    fixed request time-to-live of `REQUEST_TTL_DAYS` (exactly 7) days".
    PRD §3.4: "if the logical clock passes a request's `expires_at` while it is still
    `PROPOSED` or `COUNTERED`, it lazily transitions to `EXPIRED`. In every one of
    these three endings, a points request releases its reservation by voiding the
    `HELD` hold ledger entry — conserving the requester's points — and the
    requester's available balance is recomputed accordingly."

    Design: Corner/state_machines/request_auto_expires_after_ttl
    """
    guest, host, listing, req = _proposed_points_request()
    # Hold placed at creation -> available reduced below settled.
    before = get_member(guest["id"])
    assert before["available_points_balance"] == 730
    set_clock("2026-07-20T00:00:00Z")   # past expires_at (2026-07-08)
    fetched = validate_success(api.get_exchange_request(req["id"], make_member_headers(guest["id"])), 200)
    assert fetched["status"] == "EXPIRED"
    after = get_member(guest["id"])
    assert after["available_points_balance"] == 1000   # hold released
