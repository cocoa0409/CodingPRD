"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so every test
starts against an empty database). Setup calls use get_success_data() so a
failed precondition surfaces as a clear "Setup failed" error.

Identity threading: Member/Coach are entity-backed roles — ownership-gated
calls always use make_member_headers(entity_id) / make_coach_headers(entity_id)
with the real entity id, never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_participant_payload,
    create_coach_payload,
    create_lane_payload,
    create_league_payload,
    create_lesson_payload,
    create_member_payload,
    create_range_session_payload,
    create_rental_agreement_payload,
    create_rental_item_payload,
    create_repair_order_payload,
    create_shop_product_payload,
    purchase_punch_card_payload,
    quote_repair_order_payload,
    scorecard_payload,
)
from .test_users import TEST_USERS, make_coach_headers, make_member_headers

ADMIN = TEST_USERS["admin_headers"]
RANGE_OFFICER = TEST_USERS["range_officer_headers"]
SHOP_CLERK = TEST_USERS["shop_clerk_headers"]
LEAGUE_DIRECTOR = TEST_USERS["league_director_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def _setup_ok(resp, what):
    assert resp.status_code < 300, (
        f"Setup failed ({what}): {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# ---------------------------------------------------------------- clock


def set_clock(to_iso8601):
    return _setup_ok(api_client.set_clock(to_iso8601, ADMIN), "set clock")


# ---------------------------------------------------------------- members


def register_member(email, full_name="Test Archer", date_of_birth="1990-01-01",
                    tier=None, guardian_id=None):
    overrides = {}
    if tier is not None:
        overrides["tier"] = tier
    if guardian_id is not None:
        overrides["guardian_id"] = guardian_id
    payload = create_member_payload(
        email=email, full_name=full_name, date_of_birth=date_of_birth, **overrides
    )
    return _setup_ok(api_client.create_member(payload, ANONYMOUS),
                     f"register member {email}")


def fund_wallet(member_id, amount_cents):
    return _setup_ok(
        api_client.adjust_wallet(member_id, {"amount_cents": amount_cents}, ADMIN),
        "fund wallet",
    )


def sign_waiver(member_id, signer_id=None):
    """Sign a waiver; adults sign for themselves, a minor's guardian signs."""
    signer = signer_id if signer_id is not None else member_id
    return _setup_ok(
        api_client.sign_waiver(member_id, make_member_headers(signer)),
        f"sign waiver for {member_id}",
    )


def get_member(member_id):
    return _setup_ok(api_client.get_member(member_id, ADMIN), "get member")


def register_ready_member(email, tier=None, wallet_cents=0,
                          date_of_birth="1990-01-01", full_name="Test Archer"):
    """Register + optional wallet top-up + self-signed waiver. Returns member."""
    member = register_member(email, full_name=full_name,
                             date_of_birth=date_of_birth, tier=tier)
    if wallet_cents:
        fund_wallet(member["id"], wallet_cents)
    sign_waiver(member["id"])
    return get_member(member["id"])


def suspend_member_with_strikes(member_id, count=3):
    for i in range(count):
        _setup_ok(
            api_client.add_safety_strike(
                member_id, {"reason": f"strike {i + 1}"}, RANGE_OFFICER
            ),
            "record safety strike",
        )
    return get_member(member_id)


# ---------------------------------------------------------------- lanes


def create_lane(name, lane_type="INDOOR", max_archers=4):
    return _setup_ok(
        api_client.create_lane(
            create_lane_payload(name=name, lane_type=lane_type,
                                max_archers=max_archers),
            ADMIN,
        ),
        f"create lane {name}",
    )


# ---------------------------------------------------------------- sessions


def book_session(creator_member_id, lane_id, booking_type, start_at, end_at):
    return _setup_ok(
        api_client.create_range_session(
            create_range_session_payload(lane_id, booking_type, start_at, end_at),
            make_member_headers(creator_member_id),
        ),
        "book range session",
    )


def add_wallet_participant(session_id, archer_member_id, actor_member_id):
    return _setup_ok(
        api_client.add_participant(
            session_id,
            add_participant_payload(archer_member_id, "WALLET"),
            make_member_headers(actor_member_id),
        ),
        "add wallet participant",
    )


def add_punch_participant(session_id, archer_member_id, punch_card_id,
                          actor_member_id):
    return _setup_ok(
        api_client.add_participant(
            session_id,
            add_participant_payload(archer_member_id, "PUNCH_CARD",
                                    punch_card_id=punch_card_id),
            make_member_headers(actor_member_id),
        ),
        "add punch-card participant",
    )


def get_session(session_id):
    return _setup_ok(api_client.get_range_session(session_id, RANGE_OFFICER),
                     "get session")


def list_participants_for_session(session_id):
    data = _setup_ok(
        api_client.list_participants(RANGE_OFFICER, params={"session_id": session_id}),
        "list participants",
    )
    return data


def setup_booked_wallet_session(email="archer@example.com", tier=None,
                                wallet_cents=10000, lane_name="Lane 1",
                                max_archers=4,
                                booking_type="RESERVATION",
                                start_at="2026-05-02T10:00:00Z",
                                end_at="2026-05-02T11:00:00Z"):
    """Ready member + lane + BOOKED session + the member as sole WALLET
    participant. Returns (member, lane, session, participant)."""
    member = register_ready_member(email, tier=tier, wallet_cents=wallet_cents)
    lane = create_lane(lane_name, max_archers=max_archers)
    session = book_session(member["id"], lane["id"], booking_type, start_at, end_at)
    participant = add_wallet_participant(session["id"], member["id"], member["id"])
    return member, lane, session, participant


def setup_checked_in_session(clock_checkin, **kwargs):
    """BOOKED session walked to CHECKED_IN. The clock must be moved to
    `clock_checkin` (inside the check-in window) by the caller beforehand via
    kwargs-driven booking times; this helper sets the clock itself.
    Returns (member, lane, session, participant)."""
    member, lane, session, participant = setup_booked_wallet_session(**kwargs)
    set_clock(clock_checkin)
    session = _setup_ok(
        api_client.check_in_session(session["id"], RANGE_OFFICER), "check in session"
    )
    return member, lane, session, participant


# ---------------------------------------------------------------- punch cards


def purchase_punch_card(member_id, punches_total=5):
    return _setup_ok(
        api_client.purchase_punch_card(
            member_id, purchase_punch_card_payload(punches_total),
            make_member_headers(member_id),
        ),
        "purchase punch card",
    )


def get_punch_card(punch_card_id):
    return _setup_ok(api_client.get_punch_card(punch_card_id, RANGE_OFFICER),
                     "get punch card")


# ---------------------------------------------------------------- rentals


def create_rental_item(name="Recurve Bow", item_type="BOW", daily_rate_cents=2500):
    return _setup_ok(
        api_client.create_rental_item(
            create_rental_item_payload(name=name, item_type=item_type,
                                       daily_rate_cents=daily_rate_cents),
            SHOP_CLERK,
        ),
        "create rental item",
    )


def create_rental_agreement(rental_item_id, member_id, due_date, session_id=None):
    overrides = {}
    if session_id is not None:
        overrides["session_id"] = session_id
    return _setup_ok(
        api_client.create_rental_agreement(
            create_rental_agreement_payload(rental_item_id, member_id, due_date,
                                            **overrides),
            RANGE_OFFICER,
        ),
        "create rental agreement",
    )


def get_rental_agreement(agreement_id):
    return _setup_ok(
        api_client.get_rental_agreement(agreement_id, RANGE_OFFICER),
        "get rental agreement",
    )


def get_rental_item_via_list(rental_item_id):
    data = _setup_ok(api_client.list_rental_items(RANGE_OFFICER),
                     "list rental items")
    for item in data:
        if item["id"] == rental_item_id:
            return item
    raise AssertionError(f"Setup failed: rental item {rental_item_id} not listed")


# ---------------------------------------------------------------- coaches & lessons


def create_coach(full_name="Coach Taylor", disciplines=("RECURVE",)):
    return _setup_ok(
        api_client.create_coach(
            create_coach_payload(full_name=full_name, disciplines=list(disciplines)),
            ADMIN,
        ),
        "create coach",
    )


def request_lesson(member_id, coach_id, discipline="RECURVE",
                   proposed_start_at="2026-05-02T10:00:00Z", duration_minutes=60):
    return _setup_ok(
        api_client.create_lesson(
            create_lesson_payload(coach_id, discipline, proposed_start_at,
                                  duration_minutes=duration_minutes),
            make_member_headers(member_id),
        ),
        "request lesson",
    )


def get_lesson(lesson_id):
    return _setup_ok(api_client.get_lesson(lesson_id, ADMIN), "get lesson")


def setup_requested_lesson(email="student@example.com", tier=None,
                           wallet_cents=10000, disciplines=("RECURVE",),
                           discipline="RECURVE",
                           proposed_start_at="2026-05-02T10:00:00Z",
                           duration_minutes=60):
    """ACTIVE coach + funded waivered member + REQUESTED lesson.
    Returns (coach, member, lesson)."""
    coach = create_coach(disciplines=disciplines)
    member = register_ready_member(email, tier=tier, wallet_cents=wallet_cents)
    lesson = request_lesson(member["id"], coach["id"], discipline,
                            proposed_start_at, duration_minutes)
    return coach, member, lesson


# ---------------------------------------------------------------- leagues


def create_league(name="Spring League", entry_fee_cents=5000, max_entries=10):
    return _setup_ok(
        api_client.create_league(
            create_league_payload(name=name, entry_fee_cents=entry_fee_cents,
                                  max_entries=max_entries),
            LEAGUE_DIRECTOR,
        ),
        "create league",
    )


def enter_league(league_id, member_id):
    return _setup_ok(
        api_client.enter_league(league_id, make_member_headers(member_id)),
        "enter league",
    )


def get_league(league_id):
    return _setup_ok(api_client.get_league(league_id, LEAGUE_DIRECTOR),
                     "get league")


def get_league_entry(entry_id):
    return _setup_ok(api_client.get_league_entry(entry_id, LEAGUE_DIRECTOR),
                     "get league entry")


def setup_league_with_entries(entry_count, entry_fee_cents=5000,
                              wallet_cents=10000, league_name="League",
                              max_entries=10):
    """OPEN league with `entry_count` CONFIRMED entries, each a distinct
    funded, waivered BASIC member. Returns (league, members, entries)."""
    league = create_league(league_name, entry_fee_cents, max_entries)
    members, entries = [], []
    for i in range(entry_count):
        member = register_ready_member(f"entrant{i}@example.com",
                                       wallet_cents=wallet_cents)
        entry = enter_league(league["id"], member["id"])
        members.append(member)
        entries.append(entry)
    return league, members, entries


def setup_closed_league_with_scorecard(ends=None, x_hits=0, entry_fee_cents=5000,
                                       wallet_cents=5000,
                                       league_name="Closed League"):
    """League CLOSED with one CONFIRMED entry and one SUBMITTED scorecard.
    Returns (league, member, entry, scorecard)."""
    league, members, entries = setup_league_with_entries(
        1, entry_fee_cents=entry_fee_cents, wallet_cents=wallet_cents,
        league_name=league_name,
    )
    member, entry = members[0], entries[0]
    _setup_ok(api_client.close_league(league["id"], LEAGUE_DIRECTOR),
              "close league")
    scorecard = _setup_ok(
        api_client.submit_scorecard(
            entry["id"], scorecard_payload(ends=ends, x_hits=x_hits),
            make_member_headers(member["id"]),
        ),
        "submit scorecard",
    )
    return get_league(league["id"]), member, entry, scorecard


def get_scorecard_via_list(entry_id, scorecard_id):
    data = _setup_ok(
        api_client.list_scorecards(entry_id, LEAGUE_DIRECTOR), "list scorecards"
    )
    for card in data:
        if card["id"] == scorecard_id:
            return card
    raise AssertionError(f"Setup failed: scorecard {scorecard_id} not listed")


# ---------------------------------------------------------------- shop & repair


def create_shop_product(name="Target Face", sku="TF-1", unit_price_cents=1000,
                        initial_stock=10):
    return _setup_ok(
        api_client.create_shop_product(
            create_shop_product_payload(name=name, sku=sku,
                                        unit_price_cents=unit_price_cents,
                                        initial_stock=initial_stock),
            SHOP_CLERK,
        ),
        f"create product {sku}",
    )


def get_product_stock(product_id):
    data = _setup_ok(api_client.list_shop_products(SHOP_CLERK), "list products")
    for product in data:
        if product["id"] == product_id:
            return product["stock_quantity"]
    raise AssertionError(f"Setup failed: product {product_id} not listed")


def create_repair_order(member_id, item_description="cracked limb"):
    return _setup_ok(
        api_client.create_repair_order(
            create_repair_order_payload(member_id,
                                        item_description=item_description),
            SHOP_CLERK,
        ),
        "create repair order",
    )


def quote_repair_order(order_id, parts, labor_minutes, promised_hours,
                       expected_version):
    return _setup_ok(
        api_client.quote_repair_order(
            order_id,
            quote_repair_order_payload(parts, labor_minutes, promised_hours,
                                       expected_version),
            SHOP_CLERK,
        ),
        "quote repair order",
    )


def get_repair_order(order_id):
    return _setup_ok(api_client.get_repair_order(order_id, SHOP_CLERK),
                     "get repair order")
