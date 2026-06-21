"""Composite setup helpers for the Film/TV Production Scheduling API.

These encapsulate the multi-step preambles that nearly every interesting test
requires (open a production, budget it, hire crew, advance to ACTIVE, lay out
days, book/publish/start/check-in/check-out an assignment). Each helper uses the
lenient ``get_success_data`` validator so setup failures surface clearly.

The harness resets the database before every test, so each helper builds its
preconditions from scratch using only PRD-declared endpoints.

All roles are opaque operator identifiers (PRD 2.1): authorization is by role,
never by matching X-User-ID to an entity id, so the shared role headers in
TEST_USERS are the canonical form for every gated call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS

LP = TEST_USERS["line_producer_headers"]
AD = TEST_USERS["first_ad_headers"]
PC = TEST_USERS["payroll_coordinator_headers"]
PS = TEST_USERS["post_supervisor_headers"]
UR = TEST_USERS["union_rep_headers"]


# --------------------------------------------------------------------------- #
# Low-level single-entity creators (return the resource dict)
# --------------------------------------------------------------------------- #
def create_production(total_budget_cents=1_000_000, title="Test Production",
                      production_type="FEATURE"):
    return get_success_data(api_client.create_production(
        {"title": title, "production_type": production_type,
         "total_budget_cents": total_budget_cents}, LP))


def create_budget_line(production_id, category="BELOW_THE_LINE_LABOR", estimated_cents=500_000):
    return get_success_data(api_client.create_budget_line(
        {"production_id": production_id, "category": category,
         "estimated_cents": estimated_cents}, LP))


def create_union_fringe(production_id, union_code="SAG_AFTRA", fringe_rate_bps=1800,
                        pension_health_flat_cents=15_000):
    return get_success_data(api_client.create_union_fringe(
        {"production_id": production_id, "union_code": union_code,
         "fringe_rate_bps": fringe_rate_bps,
         "pension_health_flat_cents": pension_health_flat_cents}, LP))


def create_crew(production_id, full_name="Lead", role_title="Lead",
                daily_rate_cents=200_000, is_sag_aftra=True, union_code="SAG_AFTRA"):
    return get_success_data(api_client.create_crew_member(
        {"production_id": production_id, "full_name": full_name, "role_title": role_title,
         "daily_rate_cents": daily_rate_cents, "is_sag_aftra": is_sag_aftra,
         "union_code": union_code}, LP))


def create_shooting_day(production_id, shoot_date="2026-07-01", day_number=1, unit=None):
    payload = {"production_id": production_id, "shoot_date": shoot_date, "day_number": day_number}
    if unit is not None:
        payload["unit"] = unit
    return get_success_data(api_client.create_shooting_day(payload, AD))


def advance_production(production_id):
    return get_success_data(api_client.advance_production(production_id, LP))


def create_scene(production_id, scene_number="1A", page_eighths=8, int_ext="INT", day_night="DAY"):
    return get_success_data(api_client.create_scene(
        {"production_id": production_id, "scene_number": scene_number,
         "page_eighths": page_eighths, "int_ext": int_ext, "day_night": day_night}, AD))


def schedule_scene(scene_id, shooting_day_id):
    return get_success_data(api_client.schedule_scene(
        scene_id, {"shooting_day_id": shooting_day_id}, AD))


def book_assignment(shooting_day_id, crew_member_id, expected_shooting_day_version,
                    call_time="2026-07-01T06:00:00.000Z"):
    return get_success_data(api_client.create_assignment(
        {"shooting_day_id": shooting_day_id, "crew_member_id": crew_member_id,
         "call_time": call_time,
         "expected_shooting_day_version": expected_shooting_day_version}, AD))


def create_call_sheet(shooting_day_id, general_call_time="2026-07-01T06:00:00.000Z"):
    return get_success_data(api_client.create_call_sheet(
        {"shooting_day_id": shooting_day_id, "general_call_time": general_call_time}, AD))


def create_location(production_id, name="Rooftop", address="1 Main St"):
    return get_success_data(api_client.create_location(
        {"production_id": production_id, "name": name, "address": address}, LP))


def create_permit(location_id, permit_number, window_start, window_end):
    return get_success_data(api_client.create_location_permit(
        {"location_id": location_id, "permit_number": permit_number,
         "window_start": window_start, "window_end": window_end}, LP))


def create_dailies(shooting_day_id, reel_label="A001"):
    return get_success_data(api_client.create_dailies(
        {"shooting_day_id": shooting_day_id, "reel_label": reel_label}, PS))


# --------------------------------------------------------------------------- #
# Tier 1/2: Production reaching a target lifecycle state
# --------------------------------------------------------------------------- #
def production_in_pre_production(total_budget_cents=1_000_000, budget_category="BELOW_THE_LINE_LABOR",
                                 budget_estimated_cents=500_000):
    """Create a production with one budget line and advance DRAFT -> PRE_PRODUCTION."""
    prod = create_production(total_budget_cents=total_budget_cents)
    create_budget_line(prod["id"], category=budget_category, estimated_cents=budget_estimated_cents)
    advance_production(prod["id"])
    return prod


def production_active_with_day(total_budget_cents=1_000_000, shoot_date="2026-07-01",
                               day_number=1, budget_estimated_cents=500_000):
    """ACTIVE production with one PLANNED shooting day. Returns (production, day).

    Walks: create -> budget line -> advance(PRE_PRODUCTION) -> day ->
    advance(ACTIVE). Re-fetches the production so its returned status is ACTIVE.
    """
    prod = create_production(total_budget_cents=total_budget_cents)
    create_budget_line(prod["id"], estimated_cents=budget_estimated_cents)
    advance_production(prod["id"])
    day = create_shooting_day(prod["id"], shoot_date=shoot_date, day_number=day_number)
    advance_production(prod["id"])
    prod = get_success_data(api_client.get_production(prod["id"], LP))
    return prod, day


# --------------------------------------------------------------------------- #
# Tier 3: Assignment lifecycle shortcuts on a fresh ACTIVE production
# --------------------------------------------------------------------------- #
def setup_scheduled_assignment(total_budget_cents=1_000_000, daily_rate_cents=200_000,
                               is_sag_aftra=True, union_code="SAG_AFTRA", with_fringe=True,
                               fringe_rate_bps=1800, fringe_flat_cents=15_000,
                               call_time="2026-07-01T06:00:00.000Z", shoot_date="2026-07-01"):
    """Active production + one crew + one PLANNED day + one SCHEDULED assignment.

    Returns dict with prod, day, crew, assignment (and union_fringe if created).
    The day is PLANNED at this point (no call sheet published yet).
    """
    prod = create_production(total_budget_cents=total_budget_cents)
    create_budget_line(prod["id"], estimated_cents=500_000)
    union_fringe = None
    if with_fringe and union_code in {"SAG_AFTRA", "IATSE", "DGA"}:
        union_fringe = create_union_fringe(
            prod["id"], union_code=union_code, fringe_rate_bps=fringe_rate_bps,
            pension_health_flat_cents=fringe_flat_cents)
    crew = create_crew(prod["id"], daily_rate_cents=daily_rate_cents,
                       is_sag_aftra=is_sag_aftra, union_code=union_code)
    advance_production(prod["id"])
    day = create_shooting_day(prod["id"], shoot_date=shoot_date, day_number=1)
    advance_production(prod["id"])
    assignment = book_assignment(day["id"], crew["id"], day["version"], call_time=call_time)
    return {"prod": prod, "day": day, "crew": crew, "assignment": assignment,
            "union_fringe": union_fringe}


def setup_in_progress_assignment(call_time="2026-07-01T06:00:00.000Z", **kwargs):
    """As setup_scheduled_assignment but call sheet published + day started.

    The assignment remains SCHEDULED; the day is IN_PROGRESS. Returns the same
    dict plus 'call_sheet'. Pass general_call_time via call_time matching the
    booking call time so the published sheet is consistent.
    """
    ctx = setup_scheduled_assignment(call_time=call_time, **kwargs)
    cs = create_call_sheet(ctx["day"]["id"], general_call_time=call_time)
    get_success_data(api_client.publish_call_sheet(cs["id"], AD))
    get_success_data(api_client.start_shooting_day(ctx["day"]["id"], AD))
    ctx["call_sheet"] = cs
    return ctx


def setup_checked_in_assignment(call_time="2026-07-01T06:00:00.000Z", **kwargs):
    """IN_PROGRESS day with the assignment CHECKED_IN. Returns same dict."""
    ctx = setup_in_progress_assignment(call_time=call_time, **kwargs)
    get_success_data(api_client.check_in_assignment(ctx["assignment"]["id"], AD))
    return ctx


def setup_wrapped_assignment(wrap_time="2026-07-01T19:00:00.000Z", meal_breaks_taken=1,
                             call_time="2026-07-01T06:00:00.000Z", **kwargs):
    """Assignment WRAPPED (checked in then out) on an IN_PROGRESS day.

    Returns the same dict; 'assignment' is refreshed to the wrapped state with
    stamped penalties/fringe.
    """
    ctx = setup_checked_in_assignment(call_time=call_time, **kwargs)
    wrapped = get_success_data(api_client.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": wrap_time, "meal_breaks_taken": meal_breaks_taken}, AD))
    ctx["assignment"] = wrapped
    return ctx


def setup_approved_assignment(wrap_time="2026-07-01T19:00:00.000Z", meal_breaks_taken=1,
                              call_time="2026-07-01T06:00:00.000Z", **kwargs):
    """Assignment with payment_status APPROVED (wrapped then approve-pay)."""
    ctx = setup_wrapped_assignment(wrap_time=wrap_time, meal_breaks_taken=meal_breaks_taken,
                                   call_time=call_time, **kwargs)
    approved = get_success_data(api_client.approve_pay_assignment(ctx["assignment"]["id"], PC))
    ctx["assignment"] = approved
    return ctx


# --------------------------------------------------------------------------- #
# Tier 5: Dailies pipeline
# --------------------------------------------------------------------------- #
def setup_dailies_in_review(reel_label="A001"):
    """ACTIVE production, WRAPPED day, dailies record advanced to IN_REVIEW.

    A WRAPPED day is reached without any assignments by booking a crew member,
    publishing/starting, then a no-show clears the open assignment so the day
    can wrap. Returns dict with prod, day, dailies.
    """
    prod = create_production(total_budget_cents=1_000_000)
    create_budget_line(prod["id"], category="POST", estimated_cents=100_000)
    crew = create_crew(prod["id"], daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    advance_production(prod["id"])
    day = create_shooting_day(prod["id"], shoot_date="2026-09-07", day_number=1)
    advance_production(prod["id"])
    assignment = book_assignment(day["id"], crew["id"], day["version"],
                                 call_time="2026-09-07T06:00:00.000Z")
    cs = create_call_sheet(day["id"], general_call_time="2026-09-07T06:00:00.000Z")
    get_success_data(api_client.publish_call_sheet(cs["id"], AD))
    get_success_data(api_client.start_shooting_day(day["id"], AD))
    # clear the open assignment so the day may wrap
    get_success_data(api_client.no_show_assignment(assignment["id"], AD))
    get_success_data(api_client.wrap_shooting_day(day["id"], AD))
    dailies = create_dailies(day["id"], reel_label=reel_label)
    get_success_data(api_client.start_review_dailies(dailies["id"], PS))
    dailies = get_success_data(api_client.get_dailies(dailies["id"], PS))
    return {"prod": prod, "day": day, "dailies": dailies}


def setup_dailies_pending_on_planned_day(reel_label="A001"):
    """ACTIVE production, one PLANNED day, a PENDING dailies record. Returns dict."""
    prod = create_production(total_budget_cents=1_000_000)
    create_budget_line(prod["id"], category="POST", estimated_cents=100_000)
    advance_production(prod["id"])
    day = create_shooting_day(prod["id"], shoot_date="2026-09-03", day_number=1)
    advance_production(prod["id"])
    dailies = create_dailies(day["id"], reel_label=reel_label)
    return {"prod": prod, "day": day, "dailies": dailies}
