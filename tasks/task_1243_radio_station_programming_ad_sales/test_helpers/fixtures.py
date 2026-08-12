"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh database
using only PRD-declared endpoints, and uses get_success_data() so setup
failures surface as clear "Setup failed" errors rather than confusing
assertion failures deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO, DATE_FRI, DATE_MON
from .factories import (
    as_run_import_payload,
    create_barter_avail_payload,
    create_clearance_payload,
    create_clock_payload,
    create_endorsement_contract_payload,
    create_live_read_payload,
    create_log_payload,
    create_order_payload,
    create_rate_card_entry_payload,
    create_ratings_book_payload,
    create_spot_payload,
    create_station_payload,
    create_trade_agreement_payload,
)
from .test_users import (
    TEST_USERS,
    make_billing_admin_headers,
    make_headers,
    make_sales_rep_headers,
)

PD = TEST_USERS["program_director_headers"]
TD = TEST_USERS["traffic_director_headers"]
REP = TEST_USERS["sales_rep_headers"]
MGR = TEST_USERS["sales_manager_headers"]
BA = TEST_USERS["billing_admin_headers"]

EMPTY_IMPORT = {"aired_spot_ids": [], "aired_live_read_ids": [], "aired_barter_avail_ids": []}


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START_ISO, headers=None):
    """Drive the server's logical clock (PRD §2.4). Returns response data."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers or MGR)
    return get_success_data(resp)


def create_station(headers=None, **overrides):
    resp = api_client.create_station(create_station_payload(**overrides), headers or MGR)
    return get_success_data(resp)


def create_clock(station_id, headers=None, **overrides):
    resp = api_client.create_clock(create_clock_payload(station_id, **overrides), headers or PD)
    return get_success_data(resp)


def create_active_clock(station_id, headers=None, **overrides):
    """Create a clock and activate it (DRAFT -> ACTIVE)."""
    clock = create_clock(station_id, headers=headers, **overrides)
    h = headers or PD
    return get_success_data(api_client.activate_clock(clock["id"], h))


def create_rate_card(station_id, headers=None, **overrides):
    resp = api_client.create_rate_card_entry(
        create_rate_card_entry_payload(station_id, **overrides), headers or MGR
    )
    return get_success_data(resp)


def create_ratings_book(station_id, headers=None, **overrides):
    resp = api_client.create_ratings_book(
        create_ratings_book_payload(station_id, **overrides), headers or MGR
    )
    return get_success_data(resp)


def create_published_book(station_id, headers=None, **overrides):
    book = create_ratings_book(station_id, headers=headers, **overrides)
    return get_success_data(api_client.publish_ratings_book(book["id"], headers or MGR))


def create_clearance(station_id, headers=None, **overrides):
    resp = api_client.create_clearance(
        create_clearance_payload(station_id, **overrides), headers or PD
    )
    return get_success_data(resp)


def create_cleared_clearance(station_id, headers=None, **overrides):
    clearance = create_clearance(station_id, headers=headers, **overrides)
    return get_success_data(api_client.clear_clearance(clearance["id"], headers or PD))


def create_trade_agreement(station_id, headers=None, **overrides):
    resp = api_client.create_trade_agreement(
        create_trade_agreement_payload(station_id, **overrides),
        REP if headers is None else headers,
    )
    return get_success_data(resp)


def create_order(station_id, rep_user_id="rep-1", **overrides):
    """Create a DRAFT order; created_by_user_id is stamped from X-User-ID."""
    resp = api_client.create_order(
        create_order_payload(station_id, **overrides), make_sales_rep_headers(rep_user_id)
    )
    return get_success_data(resp)


def advance_order(order_id, target="ACTIVE", rep_user_id="rep-1", mgr_user_id="mgr-1"):
    """Walk an order DRAFT -> SUBMITTED -> APPROVED -> ACTIVE (stops at target).

    Submit is ownership-gated (caller must be the creator SalesRep); approve
    is segregation-gated (approver must differ from the creator), so the
    manager id must not equal rep_user_id.
    """
    rep_h = make_sales_rep_headers(rep_user_id)
    mgr_h = make_headers("SalesManager", mgr_user_id)
    order = get_success_data(api_client.get_order(order_id, rep_h))
    if target == "DRAFT":
        return order
    order = get_success_data(api_client.submit_order(order_id, rep_h))
    if target == "SUBMITTED":
        return order
    order = get_success_data(api_client.approve_order(order_id, mgr_h))
    if target == "APPROVED":
        return order
    order = get_success_data(api_client.activate_order(order_id, mgr_h))
    if target == "ACTIVE":
        return order
    raise ValueError(f"unsupported order target state: {target}")


def create_active_order(station_id, rep_user_id="rep-1", mgr_user_id="mgr-1", **overrides):
    """Create an order and walk it to ACTIVE. Returns the ACTIVE order dict."""
    order = create_order(station_id, rep_user_id=rep_user_id, **overrides)
    return advance_order(order["id"], "ACTIVE", rep_user_id=rep_user_id, mgr_user_id=mgr_user_id)


def create_log(station_id, log_date=DATE_MON, headers=None):
    resp = api_client.create_log(
        create_log_payload(station_id, log_date=log_date), headers or TD
    )
    return get_success_data(resp)


def lock_log(log_id, headers=None):
    """Lock a DRAFT log with a fresh OCC read. Returns the LOCKED log."""
    h = headers or TD
    log = get_success_data(api_client.get_log(log_id, h))
    return get_success_data(
        api_client.lock_log(log_id, {"expected_log_version": log["version"]}, h)
    )


def create_locked_log(station_id, log_date=DATE_MON, headers=None):
    log = create_log(station_id, log_date=log_date, headers=headers)
    return lock_log(log["id"], headers=headers)


def create_endorsement_contract(station_id, rep_user_id="rep-1", **overrides):
    resp = api_client.create_endorsement_contract(
        create_endorsement_contract_payload(station_id, **overrides),
        make_sales_rep_headers(rep_user_id),
    )
    return get_success_data(resp)


def create_active_contract(station_id, rep_user_id="rep-1", mgr_user_id="mgr-1", **overrides):
    contract = create_endorsement_contract(station_id, rep_user_id=rep_user_id, **overrides)
    return get_success_data(
        api_client.activate_endorsement_contract(contract["id"], make_headers("SalesManager", mgr_user_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — a bookable station with clock + rate card
# ---------------------------------------------------------------------------

def setup_bookable_station(
    call_sign=None,
    weekday="MON",
    daypart="MORNING_DRIVE",
    hour=6,
    capacity_units=10,
    capacity_seconds=600,
    slot_type="SPOT_BREAK",
    base_rate_cents=1000,
    min_rate_cents=100,
    default_share_fallback=2.5,
    extra_slots=None,
    rate_weekday_set=None,
    effective_from="2026-01-01",
    effective_to="2026-12-31",
    share_value=None,
    book_period=("2026-01-01", "2026-06-30"),
):
    """Station + one ACTIVE clock (+ optional extra slots) + rate card, and
    optionally a PUBLISHED ratings book. Returns a dict of the pieces."""
    station = create_station(
        call_sign=call_sign, default_share_fallback=default_share_fallback
    ) if call_sign else create_station(default_share_fallback=default_share_fallback)
    slots = [
        {
            "slot_type": slot_type,
            "hour": hour,
            "capacity_units": capacity_units,
            "capacity_seconds": capacity_seconds,
        }
    ]
    if extra_slots:
        slots = slots + list(extra_slots)
    clock = create_active_clock(
        station["id"], applies_weekdays=[weekday], slots=slots
    )
    card = create_rate_card(
        station["id"],
        daypart=daypart,
        weekday_set=rate_weekday_set or [weekday],
        base_rate_cents=base_rate_cents,
        min_rate_cents=min_rate_cents,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    book = None
    if share_value is not None:
        book = create_published_book(
            station["id"],
            period_start=book_period[0],
            period_end=book_period[1],
            share_value=share_value,
        )
    return {"station": station, "clock": clock, "card": card, "book": book}


def setup_bookable_scenario(
    weekday="MON",
    log_date=DATE_MON,
    daypart="MORNING_DRIVE",
    hour=6,
    units=1,
    order_kind="CASH",
    trade_agreement=None,
    rate_tier="FIXED",
    reprice_policy="LOCKED_AT_BOOKING",
    rep_user_id="rep-1",
    flight=("2026-05-01", "2026-05-31"),
    **station_kwargs,
):
    """Bookable station + ACTIVE order + LOCKED log.

    Returns dict with station/clock/card/order/log. The returned order dict
    carries the version as of activation; use book_spot() for OCC-safe booking.
    """
    env = setup_bookable_station(weekday=weekday, daypart=daypart, hour=hour, **station_kwargs)
    order_overrides = dict(
        order_kind=order_kind,
        rate_tier=rate_tier,
        reprice_policy=reprice_policy,
        flight_start=flight[0],
        flight_end=flight[1],
        daypart_targets=[{"daypart": daypart, "units": units}],
    )
    if trade_agreement is not None:
        order_overrides["trade_agreement_id"] = trade_agreement["id"]
    order = create_active_order(env["station"]["id"], rep_user_id=rep_user_id, **order_overrides)
    log = create_locked_log(env["station"]["id"], log_date=log_date)
    env.update({"order": order, "log": log})
    return env


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def book_spot(order_id, log_id, headers=None, as_user_id=None, role="TrafficDirector", **overrides):
    """OCC-safe spot booking: re-reads the order version, then books.

    Pass expected_order_version explicitly in overrides to pin a specific
    (possibly stale) version instead of the fresh read.
    """
    h = headers or (make_headers(role, as_user_id) if as_user_id else TD)
    if "expected_order_version" not in overrides:
        order = get_success_data(api_client.get_order(order_id, h))
        overrides["expected_order_version"] = order["version"]
    resp = api_client.create_spot(create_spot_payload(order_id, log_id, **overrides), h)
    return resp  # raw response: callers may expect failure


def book_spot_ok(order_id, log_id, **overrides):
    """book_spot variant that asserts success and returns the Spot dict."""
    return get_success_data(book_spot(order_id, log_id, **overrides))


def schedule_barter_avail(clearance_id, log_id, headers=None, **overrides):
    """OCC-safe avail scheduling: re-reads the clearance version first."""
    h = headers or TD
    if "expected_clearance_version" not in overrides:
        clearance = get_success_data(api_client.get_clearance(clearance_id, h))
        overrides["expected_clearance_version"] = clearance["version"]
    return api_client.create_barter_avail(
        create_barter_avail_payload(clearance_id, log_id, **overrides), h
    )


def schedule_barter_avail_ok(clearance_id, log_id, **overrides):
    return get_success_data(schedule_barter_avail(clearance_id, log_id, **overrides))


def schedule_live_read(contract_id, log_id, headers=None, **overrides):
    h = headers or TD
    return api_client.create_live_read(create_live_read_payload(contract_id, log_id, **overrides), h)


def schedule_live_read_ok(contract_id, log_id, **overrides):
    return get_success_data(schedule_live_read(contract_id, log_id, **overrides))


def import_as_run(log_id, aired_spot_ids=None, aired_live_read_ids=None, aired_barter_avail_ids=None, headers=None):
    return api_client.as_run_import(
        log_id,
        as_run_import_payload(aired_spot_ids, aired_live_read_ids, aired_barter_avail_ids),
        headers or TD,
    )


def import_as_run_ok(log_id, aired_spot_ids=None, aired_live_read_ids=None, aired_barter_avail_ids=None, headers=None):
    return get_success_data(
        import_as_run(log_id, aired_spot_ids, aired_live_read_ids, aired_barter_avail_ids, headers=headers)
    )


def reconcile_log_as(log_id, td_user_id="td-1"):
    """begin-reconciliation + reconcile as the given TrafficDirector identity."""
    get_success_data(api_client.begin_reconciliation(log_id, TD))
    return get_success_data(
        api_client.reconcile_log(log_id, make_headers("TrafficDirector", td_user_id))
    )


def drive_log_to_reconciled(log_id, td_user_id="td-1", import_payload=None):
    """LOCKED -> AS_RUN -> RECONCILING -> RECONCILED (zero discrepancies)."""
    import_as_run_ok(log_id, **(import_payload or {}))
    return reconcile_log_as(log_id, td_user_id=td_user_id)


def drive_log_to_affidavit(log_id, td_user_id="td-1", ba_user_id="ba-1", import_payload=None):
    """LOCKED -> ... -> AFFIDAVIT_ISSUED (issuer differs from reconciler)."""
    drive_log_to_reconciled(log_id, td_user_id=td_user_id, import_payload=import_payload)
    return get_success_data(
        api_client.issue_affidavit(log_id, make_billing_admin_headers(ba_user_id))
    )


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def book_n_spots(order_id, log_id, n, headers=None, **overrides):
    """Book n spots one at a time with OCC-safe version reads. Returns the list."""
    spots = []
    for _ in range(n):
        spots.append(book_spot_ok(order_id, log_id, headers=headers, **overrides))
    return spots


def append_adjustment(agreement_id, amount_cents, note="manual adjustment", ba_user_id="ba-1"):
    resp = api_client.append_ledger_entry(
        agreement_id,
        {"entry_kind": "ADJUSTMENT", "amount_cents": amount_cents, "note": note},
        make_billing_admin_headers(ba_user_id),
    )
    return get_success_data(resp)


def get_agreement(agreement_id, headers=None):
    return get_success_data(api_client.get_trade_agreement(agreement_id, headers or BA))


def get_ledger_entries(agreement_id, headers=None):
    data, _meta = _list_agreement_ledger(agreement_id, headers or BA)
    return data


def _list_agreement_ledger(agreement_id, headers):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(
        api_client.list_agreement_ledger_entries(agreement_id, headers)
    )


def list_discrepancies(log_id=None, headers=None, **filters):
    from prd_bench_local_runner.testing import validate_paginated

    params = dict(filters)
    if log_id is not None:
        params["log_id"] = log_id
    data, _meta = validate_paginated(api_client.list_discrepancies(headers or TD, params=params))
    return data


# ---------------------------------------------------------------------------
# Tier 5: terminal-state scenarios
# ---------------------------------------------------------------------------

def setup_log_with_missed_spot(
    base_rate_cents=1000,
    min_rate_cents=100,
    units=1,
    order_kind="CASH",
    trade_agreement=None,
    log_date=DATE_MON,
    weekday="MON",
    hour=6,
    daypart="MORNING_DRIVE",
):
    """Bookable station + ACTIVE order + LOCKED log + one spot, then an import
    that airs nothing: the spot lands in MAKE_GOOD_PENDING (reason MISSED)
    with one UNRESOLVED MISSED_SPOT discrepancy. Returns the environment."""
    env = setup_bookable_scenario(
        weekday=weekday,
        log_date=log_date,
        daypart=daypart,
        hour=hour,
        units=units,
        order_kind=order_kind,
        trade_agreement=trade_agreement,
        base_rate_cents=base_rate_cents,
        min_rate_cents=min_rate_cents,
    )
    spot = book_spot_ok(env["order"]["id"], env["log"]["id"], daypart=daypart, hour=hour)
    import_as_run_ok(env["log"]["id"])
    env["spot"] = spot
    env["log"] = get_success_data(api_client.get_log(env["log"]["id"], TD))
    return env
