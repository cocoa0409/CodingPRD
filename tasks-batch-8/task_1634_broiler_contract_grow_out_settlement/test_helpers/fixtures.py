"""Composite setup helpers: multi-step preconditions for the settlement domain.

Every helper builds its state from scratch via PRD-declared endpoints (the
harness restarts the server before every test, so nothing carries over).
Setup calls use the lenient get_success_data() so failures surface as clear
"Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_biosecurity_audit_payload,
    create_catch_crew_payload,
    create_catch_schedule_payload,
    create_contract_payload,
    create_feed_delivery_payload,
    create_flock_payload,
    create_grower_payload,
    create_house_payload,
    create_loan_payload,
    create_mortality_report_payload,
    create_placement_payload,
    create_settlement_group_payload,
    create_weight_ticket_payload,
)
from .test_users import TEST_USERS, make_grower_headers

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["service_tech_headers"]
LIVEHAUL = TEST_USERS["livehaul_headers"]
ANALYST = TEST_USERS["analyst_headers"]


# ----------------------------------------------------------------------
# Single-step helpers
# ----------------------------------------------------------------------

def set_logical_clock(to_iso8601: str):
    """PRD §2.9: IntegratorAdmin sets the logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_grower(grower_code: str = "G-1", full_name: str = "Test Grower") -> dict:
    return get_success_data(
        api_client.create_grower(
            create_grower_payload(grower_code=grower_code, full_name=full_name),
            ADMIN))


def create_house(grower_id: str, house_no: str = "H1",
                 capacity_birds: int = 10000) -> dict:
    return get_success_data(
        api_client.create_house(
            create_house_payload(grower_id, house_no=house_no,
                                 capacity_birds=capacity_birds),
            ADMIN))


def create_active_contract(grower_id: str, contract_no: str = "C-1",
                           base_pay_cents_per_lb: int = 6,
                           committed_house_count: int = 1,
                           term_start_date: str = "2026-01-01",
                           term_end_date: str = "2027-01-01") -> dict:
    contract = get_success_data(
        api_client.create_contract(
            create_contract_payload(
                grower_id, contract_no=contract_no,
                base_pay_cents_per_lb=base_pay_cents_per_lb,
                committed_house_count=committed_house_count,
                term_start_date=term_start_date, term_end_date=term_end_date),
            ADMIN))
    return get_success_data(api_client.activate_contract(contract["id"], ADMIN))


def create_settlement_group(group_code: str = "WK-1",
                            week_ending_date: str = "2026-12-31") -> dict:
    return get_success_data(
        api_client.create_settlement_group(
            create_settlement_group_payload(group_code=group_code,
                                            week_ending_date=week_ending_date),
            ANALYST))


def create_catch_crew(crew_code: str = "CREW-1", max_catches_per_day: int = 2) -> dict:
    return get_success_data(
        api_client.create_catch_crew(
            create_catch_crew_payload(crew_code=crew_code,
                                      max_catches_per_day=max_catches_per_day),
            LIVEHAUL))


def plan_flock(house_id: str, contract_id: str, settlement_group_id: str,
               flock_no: str = "F-1") -> dict:
    return get_success_data(
        api_client.create_flock(
            create_flock_payload(house_id, contract_id, settlement_group_id,
                                 flock_no=flock_no),
            ADMIN))


def schedule_placement(flock_id: str, scheduled_date: str,
                       head_count: int) -> dict:
    return get_success_data(
        api_client.schedule_placement(
            flock_id,
            create_placement_payload(scheduled_date=scheduled_date,
                                     head_count=head_count),
            ADMIN))


def place_flock(flock_id: str, scheduled_date: str, head_count: int) -> dict:
    """Schedule + confirm a placement; flock lands in PLACED."""
    placement = schedule_placement(flock_id, scheduled_date, head_count)
    return get_success_data(api_client.confirm_placement(placement["id"], ADMIN))


def record_feed(flock_id: str, feed_lbs: int, delivered_date: str = "2026-08-05",
                feed_type: str = "STARTER", ticket_no: str = "FT-1") -> dict:
    return get_success_data(
        api_client.record_feed_delivery(
            flock_id,
            create_feed_delivery_payload(delivered_date=delivered_date,
                                         feed_lbs=feed_lbs, feed_type=feed_type,
                                         ticket_no=ticket_no),
            ADMIN))


def record_mortality(flock_id: str, grower_id: str, dead_head: int,
                     condemned_head: int, report_date: str = "2026-08-10") -> dict:
    """Mortality reporting is the grower's own operation (PRD §3.3)."""
    return get_success_data(
        api_client.record_mortality_report(
            flock_id,
            create_mortality_report_payload(report_date=report_date,
                                            dead_head=dead_head,
                                            condemned_head=condemned_head),
            make_grower_headers(grower_id)))


def get_grower_version(grower_id: str) -> int:
    return get_success_data(api_client.get_grower(grower_id, ADMIN))["version"]


def issue_loan(grower_id: str, principal_cents: int, recovery_pct: int,
               purpose: str = "OPERATING") -> dict:
    """Issue a loan with the OCC handshake of PRD §2.7 (fresh grower version)."""
    version = get_grower_version(grower_id)
    return get_success_data(
        api_client.issue_loan(
            grower_id,
            create_loan_payload(version, principal_cents=principal_cents,
                                recovery_pct=recovery_pct, purpose=purpose),
            ADMIN))


def schedule_catch(flock_id: str, crew_id: str, catch_date: str) -> dict:
    return get_success_data(
        api_client.schedule_catch(
            flock_id,
            create_catch_schedule_payload(crew_id, catch_date=catch_date),
            LIVEHAUL))


def record_weight_ticket(flock_id: str, ticket_no: str, weighed_at: str,
                         live_weight_lbs: int) -> dict:
    return get_success_data(
        api_client.record_weight_ticket(
            flock_id,
            create_weight_ticket_payload(ticket_no=ticket_no, weighed_at=weighed_at,
                                         live_weight_lbs=live_weight_lbs),
            LIVEHAUL))


def harvest_flock(flock_id: str, crew_id: str, catch_date: str = "2026-09-10",
                  ticket_no: str = "WT-1",
                  weighed_at: str = "2026-09-10T08:00:00Z",
                  live_weight_lbs: int = 5000) -> dict:
    """Schedule a catch, weigh once, complete: flock lands in HARVESTED.

    Returns the completed CatchSchedule."""
    schedule = schedule_catch(flock_id, crew_id, catch_date)
    record_weight_ticket(flock_id, ticket_no, weighed_at, live_weight_lbs)
    return get_success_data(api_client.complete_catch(schedule["id"], LIVEHAUL))


def preview_settlement(flock_id: str) -> dict:
    """Create/recompute the flock's settlement (PRD §3.7): OCC token is the
    flock's current version, re-read immediately before the write."""
    version = get_success_data(api_client.get_flock(flock_id, ANALYST))["version"]
    return get_success_data(
        api_client.recompute_settlement(
            flock_id, {"expected_flock_version": version}, ANALYST))


def lock_group(group_id: str) -> dict:
    return get_success_data(api_client.lock_settlement_group(group_id, ANALYST))


def get_settlement_for_flock(flock_id: str) -> list:
    """GET the flock's settlement — an array of 0 or 1 rows (PRD §4)."""
    return get_success_data(api_client.get_flock_settlement(flock_id, ANALYST))


def record_audit(house_id: str, audit_date: str, result: str,
                 quarantine_days: int = 0) -> dict:
    return get_success_data(
        api_client.record_audit(
            house_id,
            create_biosecurity_audit_payload(audit_date=audit_date, result=result,
                                             quarantine_days=quarantine_days),
            TECH))


# ----------------------------------------------------------------------
# Composite fixtures
# ----------------------------------------------------------------------

def setup_growing_flock(*, placed_head: int = 5000, feed_lbs: int = 10000,
                        placed_date: str = "2026-08-01",
                        feed_date: str = "2026-08-05",
                        feed_type: str = "STARTER", ticket_no: str = "FT-1",
                        capacity_birds: int = 10000,
                        base_pay_cents_per_lb: int = 6,
                        committed_house_count: int = 1,
                        grower_code: str = "G-1", full_name: str = "Test Grower",
                        house_no: str = "H1", contract_no: str = "C-1",
                        group_code: str = "WK-1",
                        week_ending_date: str = "2026-12-31",
                        flock_no: str = "F-1",
                        mortality: tuple = None,
                        mortality_date: str = "2026-08-20",
                        set_clock_to: str = "2026-08-01T00:00:00Z") -> dict:
    """Grower + house + ACTIVE contract + group + flock walked to GROWING.

    Pass set_clock_to=None to leave the logical clock at its startup default
    (PRD §2.9). mortality=(dead, condemned) files one report as the grower.
    """
    if set_clock_to is not None:
        set_logical_clock(set_clock_to)
    grower = create_grower(grower_code, full_name)
    house = create_house(grower["id"], house_no, capacity_birds)
    contract = create_active_contract(
        grower["id"], contract_no, base_pay_cents_per_lb, committed_house_count)
    group = create_settlement_group(group_code, week_ending_date)
    flock = plan_flock(house["id"], contract["id"], group["id"], flock_no)
    placement = place_flock(flock["id"], placed_date, placed_head)
    delivery = record_feed(flock["id"], feed_lbs, feed_date, feed_type, ticket_no)
    report = None
    if mortality is not None:
        dead, condemned = mortality
        report = record_mortality(flock["id"], grower["id"], dead, condemned,
                                  report_date=mortality_date)
    flock = get_success_data(api_client.get_flock(flock["id"], ADMIN))
    return {
        "grower": grower,
        "house": house,
        "contract": contract,
        "group": group,
        "flock": flock,
        "placement": placement,
        "delivery": delivery,
        "mortality_report": report,
        "grower_headers": make_grower_headers(grower["id"]),
    }


def setup_harvested_flock(*, live_weight_lbs: int = 5000,
                          catch_date: str = "2026-09-10",
                          clock_to: str = "2026-09-10T00:00:00Z",
                          crew_code: str = "CREW-1", max_catches_per_day: int = 2,
                          weight_ticket_no: str = "WT-1",
                          weighed_at: str = "2026-09-10T08:00:00Z",
                          **grow_kwargs) -> dict:
    """setup_growing_flock + crew + catch completed: flock HARVESTED, house in
    DOWNTIME (catch_date + 14), group averages recomputed (PRD §3.5)."""
    ctx = setup_growing_flock(**grow_kwargs)
    crew = create_catch_crew(crew_code, max_catches_per_day)
    if clock_to is not None:
        set_logical_clock(clock_to)
    schedule = harvest_flock(ctx["flock"]["id"], crew["id"], catch_date,
                             weight_ticket_no, weighed_at, live_weight_lbs)
    ctx["crew"] = crew
    ctx["catch_schedule"] = schedule
    ctx["flock"] = get_success_data(api_client.get_flock(ctx["flock"]["id"], ADMIN))
    return ctx


def setup_locked_settlement(*, preview: bool = True, **harvest_kwargs) -> dict:
    """Harvested flock whose settlement exists and whose group is LOCKED:
    optionally previews the PROVISIONAL settlement first (the OPEN-group
    creation pathway of PRD §3.7), then locks the group so every PENDING
    settlement is recomputed and flipped to FINAL (PRD §3.7)."""
    ctx = setup_harvested_flock(**harvest_kwargs)
    if preview:
        ctx["provisional"] = preview_settlement(ctx["flock"]["id"])
    ctx["group"] = lock_group(ctx["group"]["id"])
    settlements = get_settlement_for_flock(ctx["flock"]["id"])
    assert len(settlements) == 1, (
        "Setup expected exactly one settlement row for the harvested flock "
        "after group lock")
    ctx["settlement"] = settlements[0]
    return ctx


def setup_paid_settlement(**harvest_kwargs) -> dict:
    """Full lifecycle through PAID: harvest -> lock -> approve -> pay."""
    ctx = setup_locked_settlement(**harvest_kwargs)
    sid = ctx["settlement"]["id"]
    ctx["settlement"] = get_success_data(api_client.approve_settlement(sid, ANALYST))
    ctx["settlement"] = get_success_data(api_client.pay_settlement(sid, ANALYST))
    return ctx


def setup_two_grower_tournament() -> dict:
    """Two growers in one settlement group, both flocks GROWING, grower A
    carrying an ISSUED loan (principal 120000, recovery 15%). Shared preamble
    for tournament settlement tests.

    Flock A: 10000 head on 2026-08-01, 300 dead / 40 condemned,
             100000 lbs feed (two deliveries).
    Flock B: 10000 head on 2026-08-01, 500 dead / 0 condemned, 102000 lbs feed.
    Logical clock ends at 2026-09-10 (both flocks aged 40 days, PRD §3.5).
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    grower_a = create_grower("G-A", "Grower A")
    grower_b = create_grower("G-B", "Grower B")
    loan_a = issue_loan(grower_a["id"], 120000, 15, "OPERATING")
    house_a = create_house(grower_a["id"], "H1", 20000)
    house_b = create_house(grower_b["id"], "H1", 20000)
    contract_a = create_active_contract(grower_a["id"], "C-A", 6, 1)
    contract_b = create_active_contract(grower_b["id"], "C-B", 6, 1)
    group = create_settlement_group("WK-32", "2026-09-12")
    flock_a = plan_flock(house_a["id"], contract_a["id"], group["id"], "F-A")
    flock_b = plan_flock(house_b["id"], contract_b["id"], group["id"], "F-B")
    place_flock(flock_a["id"], "2026-08-01", 10000)
    place_flock(flock_b["id"], "2026-08-01", 10000)
    record_feed(flock_a["id"], 60000, "2026-08-10", "STARTER", "FT-A1")
    record_feed(flock_a["id"], 40000, "2026-08-25", "FINISHER", "FT-A2")
    record_feed(flock_b["id"], 102000, "2026-08-10", "STARTER", "FT-B1")
    record_mortality(flock_a["id"], grower_a["id"], 300, 40, "2026-09-01")
    record_mortality(flock_b["id"], grower_b["id"], 500, 0, "2026-09-01")
    crew = create_catch_crew("CREW-1", 4)
    set_logical_clock("2026-09-10T00:00:00Z")
    return {
        "grower_a": grower_a,
        "grower_b": grower_b,
        "loan_a": loan_a,
        "house_a": house_a,
        "house_b": house_b,
        "contract_a": contract_a,
        "contract_b": contract_b,
        "group": group,
        "flock_a": get_success_data(api_client.get_flock(flock_a["id"], ADMIN)),
        "flock_b": get_success_data(api_client.get_flock(flock_b["id"], ADMIN)),
        "crew": crew,
        "grower_a_headers": make_grower_headers(grower_a["id"]),
        "grower_b_headers": make_grower_headers(grower_b["id"]),
    }


def harvest_tournament_flock(ctx: dict, which: str) -> dict:
    """Harvest flock A or B of the two-grower tournament (50000 lbs live)."""
    flock = ctx[f"flock_{which}"]
    schedule = harvest_flock(
        flock["id"], ctx["crew"]["id"], "2026-09-10",
        f"WT-{which.upper()}1", f"2026-09-10T0{8 if which == 'a' else 9}:00:00Z",
        50000)
    ctx[f"flock_{which}"] = get_success_data(
        api_client.get_flock(flock["id"], ADMIN))
    return schedule


def setup_two_loan_grower(principal_1: int = 30000, principal_2: int = 90000,
                          recovery_pct: int = 15) -> dict:
    """Grower with two ISSUED loans (oldest first), plus a harvested flock in a
    locked single-member group with a FINAL settlement ready to approve."""
    set_logical_clock("2026-08-01T00:00:00Z")
    grower = create_grower("G-W", "Waterfall Grower")
    loan1 = issue_loan(grower["id"], principal_1, recovery_pct, "OPERATING")
    loan2 = issue_loan(grower["id"], principal_2, recovery_pct, "OPERATING")
    house = create_house(grower["id"], "H1", 20000)
    contract = create_active_contract(grower["id"], "C-W", 6, 1)
    group = create_settlement_group("WK-38", "2026-10-24")
    flock = plan_flock(house["id"], contract["id"], group["id"], "F-W")
    place_flock(flock["id"], "2026-08-01", 10000)
    record_feed(flock["id"], 100000, "2026-08-10", "STARTER", "FT-W1")
    crew = create_catch_crew("CREW-W", 2)
    set_logical_clock("2026-09-10T00:00:00Z")
    harvest_flock(flock["id"], crew["id"], "2026-09-10", "WT-W1",
                  "2026-09-10T08:00:00Z", 50000)
    preview_settlement(flock["id"])
    lock_group(group["id"])
    settlements = get_settlement_for_flock(flock["id"])
    assert len(settlements) == 1
    return {
        "grower": grower,
        "loan1": loan1,
        "loan2": loan2,
        "house": house,
        "contract": contract,
        "group": group,
        "flock": get_success_data(api_client.get_flock(flock["id"], ADMIN)),
        "crew": crew,
        "settlement": settlements[0],
        "grower_headers": make_grower_headers(grower["id"]),
    }


def list_loans_for_grower(grower_id: str) -> list:
    return get_success_data(api_client.list_loans(grower_id, ADMIN))
