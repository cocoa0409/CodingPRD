"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints,
using the lenient get_success_data() validator so setup failures surface clearly.
The test harness restarts the server (empty DB) before every test, so nothing is
carried over between tests.

Skater is entity-backed: ownership-gated calls thread the real skater id through
make_skater_headers(skater_id). Operator (RinkManager / FrontDesk) calls use the
shared opaque headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_skater_headers

RM = TEST_USERS["rink_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


def _data(resp):
    return get_success_data(resp)


# --- Logical clock -------------------------------------------------------
def set_clock(api, iso):
    return _data(api.set_clock(iso, RM))


# --- Rinks & skaters -----------------------------------------------------
def create_rink(api, **overrides):
    payload = {
        "name": "Main",
        "resurface_buffer_minutes": 15,
        "public_skate_capacity": 2,
        "public_skate_fee_cents": 0,
        "rental_skate_count": 1,
        "locker_count": 3,
        "locker_fee_cents": 0,
    }
    payload.update(overrides)
    return _data(api.create_rink(payload, RM))


def create_skater(api, email, full_name="Skater", membership=None):
    payload = {"full_name": full_name, "email": email}
    if membership is not None:
        payload["membership"] = membership
    return _data(api.create_skater(payload, RM))


def fund_skater(api, skater_id, amount_cents):
    return _data(api.adjust_wallet(skater_id, {"amount_cents": amount_cents}, RM))


def create_funded_skater(api, email, amount_cents=100000, membership=None,
                         full_name="Skater"):
    sk = create_skater(api, email, full_name=full_name, membership=membership)
    if amount_cents:
        fund_skater(api, sk["id"], amount_cents)
    return sk


def get_skater(api, skater_id):
    return _data(api.get_skater(skater_id, RM))


def get_rink(api, rink_id):
    return _data(api.get_rink(rink_id, RM))


# --- Ice slots -----------------------------------------------------------
def create_slot(api, rink_id, purpose, start_utc, end_utc):
    payload = {"rink_id": rink_id, "purpose": purpose,
               "start_utc": start_utc, "end_utc": end_utc}
    return _data(api.create_ice_slot(payload, RM))


def publish_slot(api, slot_id):
    return _data(api.publish_ice_slot(slot_id, RM))


def create_published_slot(api, rink_id, purpose, start_utc, end_utc):
    slot = create_slot(api, rink_id, purpose, start_utc, end_utc)
    publish_slot(api, slot["id"])
    return slot


def get_slot(api, slot_id):
    return _data(api.get_ice_slot(slot_id, RM))


# --- Admissions ----------------------------------------------------------
def admit(api, slot_id, skater_id, rental_skate=False, as_role="FrontDesk"):
    payload = {"skater_id": skater_id}
    if rental_skate:
        payload["rental_skate"] = True
    headers = FD if as_role == "FrontDesk" else RM
    return _data(api.create_admission(slot_id, payload, headers))


# --- Classes / enrollments / subscriptions -------------------------------
def create_class(api, slot_id, level_name="BASIC_1", capacity=5,
                 prerequisite_class_id=None):
    payload = {"ice_slot_id": slot_id, "level_name": level_name, "capacity": capacity}
    if prerequisite_class_id is not None:
        payload["prerequisite_class_id"] = prerequisite_class_id
    return _data(api.create_class(payload, RM))


def enroll(api, class_id, skater_id):
    return _data(api.create_enrollment(class_id, {"skater_id": skater_id}, RM))


def create_subscription(api, enrollment_id, expected_version, monthly_fee_cents=12000,
                        billing_cycle_start="2026-06-01", billing_cycle_end="2026-07-01",
                        total_sessions_in_cycle=8, proration_mode=None,
                        sessions_attended=None):
    payload = {
        "expected_enrollment_version": expected_version,
        "monthly_fee_cents": monthly_fee_cents,
        "billing_cycle_start": billing_cycle_start,
        "billing_cycle_end": billing_cycle_end,
        "total_sessions_in_cycle": total_sessions_in_cycle,
    }
    if proration_mode is not None:
        payload["proration_mode"] = proration_mode
    if sessions_attended is not None:
        payload["sessions_attended"] = sessions_attended
    return _data(api.create_tuition_subscription(enrollment_id, payload, RM))


def setup_active_subscription(api, clock=None, proration_mode="CALENDAR",
                              sessions_attended=5, monthly_fee_cents=12000,
                              amount_cents=100000, email="sub@x.com",
                              billing_cycle_start="2026-06-01",
                              billing_cycle_end="2026-07-01",
                              total_sessions_in_cycle=8):
    """Full chain: rink -> published LEARN_TO_SKATE slot -> class -> funded skater ->
    enrollment -> ACTIVE tuition subscription. Returns a dict of all handles.
    enrollment reflects the version observed at enroll time (before the subscription
    create bumped it), which OCC tests reuse as a stale value."""
    rink = create_rink(api)
    if clock is not None:
        set_clock(api, clock)
    slot = create_published_slot(api, rink["id"], "LEARN_TO_SKATE",
                                 "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    cls = create_class(api, slot["id"])
    sk = create_funded_skater(api, email, amount_cents)
    enr = enroll(api, cls["id"], sk["id"])
    sub = create_subscription(
        api, enr["id"], enr["version"], monthly_fee_cents=monthly_fee_cents,
        proration_mode=proration_mode, sessions_attended=sessions_attended,
        billing_cycle_start=billing_cycle_start, billing_cycle_end=billing_cycle_end,
        total_sessions_in_cycle=total_sessions_in_cycle)
    return {"rink": rink, "slot": slot, "class_id": cls["id"], "skater": sk,
            "enrollment": enr, "subscription": sub}


def setup_diverging_tuition(api, clock="2026-06-16T00:00:00Z"):
    """One class, two funded skaters each with a subscription: skater A CALENDAR,
    skater B SESSIONS, identical fee/cycle. Returns handles for both."""
    rink = create_rink(api)
    set_clock(api, clock)
    slot = create_published_slot(api, rink["id"], "LEARN_TO_SKATE",
                                 "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    cls = create_class(api, slot["id"])
    sk_a = create_funded_skater(api, "a@x.com", 100000, full_name="Skater A")
    sk_b = create_funded_skater(api, "b@x.com", 100000, full_name="Skater B")
    enr_a = enroll(api, cls["id"], sk_a["id"])
    enr_b = enroll(api, cls["id"], sk_b["id"])
    sub_a = create_subscription(api, enr_a["id"], enr_a["version"],
                                proration_mode="CALENDAR", sessions_attended=5)
    sub_b = create_subscription(api, enr_b["id"], enr_b["version"],
                                proration_mode="SESSIONS", sessions_attended=5)
    return {"rink": rink, "class_id": cls["id"],
            "skater_a": sk_a, "skater_b": sk_b,
            "sub_a": sub_a, "sub_b": sub_b}


# --- Leagues / registrations / lockers -----------------------------------
def create_league(api, name="Beer League", sport="HOCKEY", season_start="2026-06-01",
                  season_end="2026-09-01", roster_capacity=20):
    payload = {"name": name, "sport": sport, "season_start": season_start,
               "season_end": season_end, "roster_capacity": roster_capacity}
    return _data(api.create_league(payload, RM))


def register_skater(api, league_id, skater_id, locker_number=None,
                    season_start_date=None, season_end_date=None, as_skater_id=None):
    payload = {"skater_id": skater_id}
    if locker_number is not None:
        payload["locker_number"] = locker_number
        payload["season_start_date"] = season_start_date
        payload["season_end_date"] = season_end_date
    headers = make_skater_headers(as_skater_id) if as_skater_id else RM
    return _data(api.create_registration(league_id, payload, headers))


def assign_locker(api, rink_id, skater_id, locker_number, season_start_date,
                  season_end_date, size=None, as_skater_id=None):
    payload = {"skater_id": skater_id, "locker_number": locker_number,
               "season_start_date": season_start_date,
               "season_end_date": season_end_date}
    if size is not None:
        payload["size"] = size
    headers = make_skater_headers(as_skater_id) if as_skater_id else RM
    return _data(api.create_locker_assignment(rink_id, payload, headers))


def setup_locker_holder(api, locker_fee_cents=2000, locker_number=1,
                        season_start_date="2026-06-01", season_end_date="2026-09-01"):
    """A rink and a funded skater who holds one ACTIVE locker assignment."""
    rink = create_rink(api, locker_fee_cents=locker_fee_cents)
    sk = create_funded_skater(api, "locker@x.com", 100000)
    la = assign_locker(api, rink["id"], sk["id"], locker_number,
                       season_start_date, season_end_date, as_skater_id=sk["id"])
    return {"rink": rink, "skater": sk, "locker": la}


def setup_league_registration_with_locker(api):
    """A REGISTRATION_OPEN league with one ACTIVE registration that reserved locker 1
    (so the rink's available_lockers has dropped by one)."""
    rink = create_rink(api, locker_count=3, locker_fee_cents=2000)
    sk = create_funded_skater(api, "lgloc@x.com", 100000)
    league = create_league(api, roster_capacity=20)
    reg = register_skater(api, league["id"], sk["id"], locker_number=1,
                          season_start_date="2026-06-01", season_end_date="2026-09-01",
                          as_skater_id=sk["id"])
    return {"rink": rink, "skater": sk, "league": league, "registration": reg}


# --- Slot bookings -------------------------------------------------------
def book_slot(api, slot_id, skater_id, booking_type, as_skater_id=None, **extra):
    payload = {"skater_id": skater_id, "booking_type": booking_type}
    payload.update(extra)
    headers = make_skater_headers(as_skater_id) if as_skater_id else RM
    return _data(api.create_slot_booking(slot_id, payload, headers))


def setup_rental_booking(api, purpose, booking_type, start_utc, end_utc,
                         membership=None, includes_resurface=False,
                         peak_start_hour_utc=16, clock=None):
    """A rink + published RENTAL/BROOMBALL slot + funded skater + a BOOKED booking."""
    rink = create_rink(api, peak_start_hour_utc=peak_start_hour_utc, locker_count=0)
    if clock is not None:
        set_clock(api, clock)
    slot = create_published_slot(api, rink["id"], purpose, start_utc, end_utc)
    sk = create_funded_skater(api, "book@x.com", 100000, membership=membership)
    extra = {}
    if includes_resurface:
        extra["includes_resurface"] = True
    bk = book_slot(api, slot["id"], sk["id"], booking_type,
                   as_skater_id=sk["id"], **extra)
    return {"rink": rink, "slot": slot, "skater": sk, "booking": bk}


def setup_party_booking(api, guest_count_booked, base_fee_cents=5000,
                        per_guest_cents=1010, tax_rate=0.05, clock=None,
                        email="party@x.com"):
    """A rink + published PARTY slot + funded skater + a BOOKED party booking."""
    rink = create_rink(api)
    if clock is not None:
        set_clock(api, clock)
    slot = create_published_slot(api, rink["id"], "PARTY",
                                 "2026-06-12T10:00:00Z", "2026-06-12T12:00:00Z")
    sk = create_funded_skater(api, email, 100000)
    bk = book_slot(api, slot["id"], sk["id"], "PARTY", as_skater_id=sk["id"],
                   base_fee_cents=base_fee_cents, per_guest_cents=per_guest_cents,
                   guest_count_booked=guest_count_booked, tax_rate=tax_rate)
    return {"rink": rink, "slot": slot, "skater": sk, "booking": bk}


# --- Public-skate scenarios ----------------------------------------------
def setup_public_slot(api, published=True, public_skate_capacity=2,
                      public_skate_fee_cents=0, rental_skate_count=1,
                      locker_count=3):
    """A rink + a PUBLIC_SKATE slot (published by default)."""
    rink = create_rink(api, public_skate_capacity=public_skate_capacity,
                       public_skate_fee_cents=public_skate_fee_cents,
                       rental_skate_count=rental_skate_count, locker_count=locker_count)
    slot = create_slot(api, rink["id"], "PUBLIC_SKATE",
                       "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    if published:
        publish_slot(api, slot["id"])
    return {"rink": rink, "slot": slot}


# --- Sharpening ----------------------------------------------------------
def create_sharpening_order(api, skater_id, skate_type="HOCKEY", price_cents=900,
                            as_role="FrontDesk"):
    payload = {"skater_id": skater_id, "skate_type": skate_type,
               "price_cents": price_cents}
    headers = FD if as_role == "FrontDesk" else RM
    return _data(api.create_sharpening_order(payload, headers))


def setup_sharpening_orders(api, skate_types=("HOCKEY", "FIGURE", "GOALIE")):
    """One skater with N sharpening orders created in sequence (created_at order)."""
    sk = create_skater(api, "sharp@x.com")
    orders = [create_sharpening_order(api, sk["id"], skate_type=st)
              for st in skate_types]
    return {"skater": sk, "orders": orders}
