"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its preconditions from scratch
using only PRD endpoints. Setup calls go through ``get_success_data`` so a broken precondition
surfaces as a setup failure rather than a confusing assertion failure.

Identity threading: the SponsorAdmin headers are always built from the created ``Sponsor.id`` and
the SiteSupervisor headers from the created ``Site.id``, because the PRD makes those identifiers the
caller's ``X-User-ID``.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    DEFAULTS,
    budget_decision_payload,
    create_advance_payment_payload,
    create_area_eligibility_record_payload,
    create_holding_log_payload,
    create_meal_claim_payload,
    create_meal_count_payload,
    create_meal_service_day_payload,
    create_monitoring_visit_payload,
    create_site_payload,
    create_sponsor_budget_payload,
    create_sponsor_payload,
    finding,
    meal_service,
    open_day_payload,
    submit_claim_payload,
    visit_report_payload,
)
from .test_users import (
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
)

REVIEWER = make_state_agency_reviewer_headers()

# Instants the canonical program-year scenario walks through.
CLOCK_PROGRAM_INTAKE = "2026-06-01T00:00:00Z"
CLOCK_FIRST_SERVICE_DAY = "2026-06-08T08:00:00Z"
CLOCK_FIRST_WEEK_VISIT = "2026-06-10T09:00:00Z"
CLOCK_JUNE_CLAIM_WINDOW = "2026-07-06T09:00:00Z"

FIRST_SERVICE_DATE = TEST_DEFAULTS["SEASON_START_DATE"]


# --- Clock -------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Move the logical program clock, the single source of the current instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, REVIEWER))


# --- Sponsors ----------------------------------------------------------------


def create_sponsor(**overrides) -> dict:
    return get_success_data(api_client.create_sponsor(create_sponsor_payload(**overrides), REVIEWER))


def submit_sponsor_application(sponsor: dict) -> dict:
    return get_success_data(
        api_client.submit_sponsor_application(
            sponsor["id"], make_sponsor_admin_headers(sponsor["id"])
        )
    )


def decide_sponsor_application(sponsor_id: str, decision: str = "APPROVED",
                               reason: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.decide_sponsor_application(sponsor_id, payload, REVIEWER)
    )


def create_approved_sponsor(**overrides) -> dict:
    """Register a sponsor and walk it DRAFT -> SUBMITTED -> APPROVED."""
    sponsor = create_sponsor(**overrides)
    submit_sponsor_application(sponsor)
    return decide_sponsor_application(sponsor["id"], "APPROVED")


def get_sponsor(sponsor_id: str) -> dict:
    return get_success_data(
        api_client.get_sponsor(sponsor_id, make_sponsor_admin_headers(sponsor_id))
    )


def sponsor_version(sponsor_id: str) -> int:
    return get_sponsor(sponsor_id)["version"]


# --- Budgets -----------------------------------------------------------------


def create_budget(sponsor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sponsor_budget(
            create_sponsor_budget_payload(sponsor_id, **overrides),
            make_sponsor_admin_headers(sponsor_id),
        )
    )


def submit_budget(budget: dict) -> dict:
    return get_success_data(
        api_client.submit_sponsor_budget(
            budget["id"], make_sponsor_admin_headers(budget["sponsor_id"])
        )
    )


def decide_budget(budget_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_sponsor_budget(budget_id, budget_decision_payload(**overrides), REVIEWER)
    )


def create_approved_budget(sponsor_id: str, *, requested: Optional[Dict[str, int]] = None,
                           approved_operating_cost_cents: Optional[int] = None,
                           approved_admin_cost_cents: Optional[int] = None) -> dict:
    """Open a program-year budget and walk it DRAFT -> SUBMITTED -> APPROVED with ceilings."""
    budget = create_budget(sponsor_id, **(requested or {}))
    submit_budget(budget)
    return decide_budget(
        budget["id"],
        decision="APPROVED",
        approved_operating_cost_cents=(
            approved_operating_cost_cents
            if approved_operating_cost_cents is not None
            else TEST_DEFAULTS["APPROVED_OPERATING_COST_CENTS"]
        ),
        approved_admin_cost_cents=(
            approved_admin_cost_cents
            if approved_admin_cost_cents is not None
            else TEST_DEFAULTS["APPROVED_ADMIN_COST_CENTS"]
        ),
    )


# --- Advance payments --------------------------------------------------------


def request_advance(sponsor_id: str, **overrides) -> dict:
    payload = create_advance_payment_payload(sponsor_id, sponsor_version(sponsor_id), **overrides)
    return get_success_data(
        api_client.create_advance_payment(payload, make_sponsor_admin_headers(sponsor_id))
    )


def create_disbursed_advance(sponsor_id: str, request_month: str = "2026-06",
                             requested_amount_cents: int = 30_000,
                             approved_amount_cents: Optional[int] = None) -> dict:
    """Request, approve and disburse one advance, opening its outstanding balance."""
    advance = request_advance(
        sponsor_id, request_month=request_month, requested_amount_cents=requested_amount_cents
    )
    get_success_data(
        api_client.decide_advance_payment(
            advance["id"],
            {
                "decision": "APPROVED",
                "approved_amount_cents": (
                    approved_amount_cents if approved_amount_cents is not None
                    else requested_amount_cents
                ),
            },
            REVIEWER,
        )
    )
    return get_success_data(api_client.disburse_advance_payment(advance["id"], REVIEWER))


# --- Area eligibility records and sites --------------------------------------


def create_area_record(**overrides) -> dict:
    return get_success_data(
        api_client.create_area_eligibility_record(
            create_area_eligibility_record_payload(**overrides), REVIEWER
        )
    )


def create_site(sponsor_id: str, area_record_id: Optional[str] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_site(
            create_site_payload(sponsor_id, area_record_id, **overrides),
            make_sponsor_admin_headers(sponsor_id),
        )
    )


def determine_eligibility(site_id: str) -> dict:
    return get_success_data(api_client.determine_site_eligibility(site_id, REVIEWER))


def decide_site_approval(site_id: str, decision: str = "APPROVED",
                         reason: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.decide_site_approval(site_id, payload, REVIEWER))


def create_approved_site(sponsor_id: str, area_record_id: Optional[str] = None,
                         **overrides) -> dict:
    """Register a site, determine its eligibility basis and approve it."""
    site = create_site(sponsor_id, area_record_id, **overrides)
    determine_eligibility(site["id"])
    return decide_site_approval(site["id"], "APPROVED")


def start_operating(site: dict) -> dict:
    return get_success_data(
        api_client.set_site_operating_status(
            site["id"], {"to_status": "OPERATING"},
            make_sponsor_admin_headers(site["sponsor_id"]),
        )
    )


def close_for_season(site: dict) -> dict:
    return get_success_data(
        api_client.set_site_operating_status(
            site["id"], {"to_status": "CLOSED_FOR_SEASON"},
            make_sponsor_admin_headers(site["sponsor_id"]),
        )
    )


# --- Program baseline --------------------------------------------------------


def setup_program_baseline(*, include_budget: bool = True, site_count: int = 1,
                           sponsor_overrides: Optional[Dict[str, Any]] = None,
                           area_overrides: Optional[Dict[str, Any]] = None,
                           site_overrides: Optional[Dict[str, Any]] = None,
                           site_names: Optional[Sequence[str]] = None,
                           operating: bool = True,
                           operating_clock: str = CLOCK_FIRST_SERVICE_DAY,
                           budget_kwargs: Optional[Dict[str, Any]] = None) -> dict:
    """Approved sponsor, optional approved budget, one area record and ``site_count`` approved
    sites, with the clock moved to the first service day and every site set OPERATING.

    Returns a dict with keys: sponsor, budget, area_record, sites, site, sponsor_headers,
    supervisor_headers (for the first site), reviewer_headers, monitor_headers.
    """
    set_clock(CLOCK_PROGRAM_INTAKE)
    sponsor = create_approved_sponsor(**(sponsor_overrides or {}))
    budget = create_approved_budget(sponsor["id"], **(budget_kwargs or {})) if include_budget else None
    # The PRD makes (area_code, data_source) unique across all area eligibility records, so the
    # baseline files its default record only when a site here will actually cite one. With
    # site_count=0 the caller files its own record, and a default one would collide with it.
    area_record = (
        create_area_record(**(area_overrides or {}))
        if site_count > 0 or area_overrides
        else None
    )

    names = list(site_names) if site_names else [
        DEFAULTS["SITE_NAME"] if index == 0 else f"{DEFAULTS['SITE_NAME']} {index + 1}"
        for index in range(site_count)
    ]
    sites: List[dict] = []
    for index in range(site_count):
        overrides = dict(site_overrides or {})
        overrides.setdefault("name", names[index])
        sites.append(create_approved_site(sponsor["id"], area_record["id"], **overrides))

    if operating:
        set_clock(operating_clock)
        sites = [start_operating(site) for site in sites]

    return {
        "sponsor": sponsor,
        "budget": budget,
        "area_record": area_record,
        "sites": sites,
        "site": sites[0] if sites else None,
        "sponsor_headers": make_sponsor_admin_headers(sponsor["id"]),
        "supervisor_headers": make_site_supervisor_headers(sites[0]["id"]) if sites else None,
        "reviewer_headers": REVIEWER,
        "monitor_headers": make_field_monitor_headers(DEFAULTS["MONITOR_USER_ID"]),
    }


# --- Meal service days -------------------------------------------------------


def create_planned_day(site_id: str, service_date: str = FIRST_SERVICE_DATE,
                       meal_services: Optional[List[dict]] = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_meal_service_day(
            create_meal_service_day_payload(site_id, service_date, meal_services, **overrides),
            make_site_supervisor_headers(site_id),
        )
    )


def open_day(day: dict, production_counts: Optional[Dict[str, int]] = None,
             food_received_at: Optional[str] = None) -> dict:
    site_id = day["site_id"]
    payload = open_day_payload(
        production_counts=production_counts,
        food_received_at=food_received_at or f"{day['service_date']}T10:30:00Z",
    )
    return get_success_data(
        api_client.open_meal_service_day(day["id"], payload, make_site_supervisor_headers(site_id))
    )


def record_meal_count(day: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_meal_count(
            day["id"], create_meal_count_payload(**overrides),
            make_site_supervisor_headers(day["site_id"]),
        )
    )


def record_holding_log(day: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_holding_log(
            day["id"], create_holding_log_payload(**overrides),
            make_site_supervisor_headers(day["site_id"]),
        )
    )


def close_day(day: dict) -> dict:
    return get_success_data(
        api_client.close_meal_service_day(day["id"], make_site_supervisor_headers(day["site_id"]))
    )


def finalize_day(day: dict, sponsor_id: str) -> dict:
    return get_success_data(
        api_client.finalize_meal_service_day(day["id"], make_sponsor_admin_headers(sponsor_id))
    )


def create_open_day(site_id: str, service_date: str = FIRST_SERVICE_DATE,
                    meal_services: Optional[List[dict]] = None,
                    production_counts: Optional[Dict[str, int]] = None,
                    food_received_at: Optional[str] = None) -> dict:
    """Plan one service date and open it for service."""
    day = create_planned_day(site_id, service_date, meal_services)
    return open_day(day, production_counts, food_received_at)


def create_finalized_day(site_id: str, sponsor_id: str,
                         service_date: str = FIRST_SERVICE_DATE,
                         *, first_meals: int = TEST_DEFAULTS["FIRST_MEALS"],
                         second_meals: int = 0, adult_meals: int = 0,
                         meal_type: str = "LUNCH",
                         planned_meals: int = TEST_DEFAULTS["PLANNED_MEALS"],
                         meal_services: Optional[List[dict]] = None,
                         production_counts: Optional[Dict[str, int]] = None,
                         food_received_at: Optional[str] = None,
                         counts: Optional[List[Dict[str, Any]]] = None) -> dict:
    """Plan, open, count, close and finalize one service day so its meals become claimable."""
    services = meal_services if meal_services is not None else [
        meal_service(meal_type=meal_type, planned_meals=planned_meals)
    ]
    day = create_planned_day(site_id, service_date, services)
    day = open_day(
        day,
        production_counts if production_counts is not None else {meal_type: planned_meals},
        food_received_at,
    )
    for entry in (counts if counts is not None else [
        {"meal_type": meal_type, "first_meals": first_meals,
         "second_meals": second_meals, "adult_meals": adult_meals}
    ]):
        record_meal_count(day, **entry)
    close_day(day)
    return finalize_day(day, sponsor_id)


# --- Monitoring --------------------------------------------------------------


def schedule_visit(site_id: str, **overrides) -> dict:
    monitor_user_id = overrides.pop("monitor_user_id", DEFAULTS["MONITOR_USER_ID"])
    payload = create_monitoring_visit_payload(site_id, monitor_user_id, **overrides)
    return get_success_data(
        api_client.create_monitoring_visit(payload, make_field_monitor_headers(monitor_user_id))
    )


def conduct_visit(visit: dict) -> dict:
    return get_success_data(
        api_client.conduct_monitoring_visit(
            visit["id"], make_field_monitor_headers(visit["monitor_user_id"])
        )
    )


def report_visit(visit: dict, findings: Optional[List[dict]] = None) -> dict:
    return get_success_data(
        api_client.report_monitoring_visit(
            visit["id"], visit_report_payload(findings),
            make_field_monitor_headers(visit["monitor_user_id"]),
        )
    )


def create_reported_visit(site_id: str, *, findings: Optional[List[dict]] = None,
                          scheduled_date: str = "2026-06-10",
                          conduct_clock: Optional[str] = CLOCK_FIRST_WEEK_VISIT,
                          monitor_user_id: str = DEFAULTS["MONITOR_USER_ID"],
                          visit_type: str = "FIRST_WEEK",
                          window_start: str = "09:00",
                          window_end: str = "11:00") -> dict:
    """Schedule a visit, move the clock into its window, conduct it and file its report."""
    visit = schedule_visit(
        site_id, monitor_user_id=monitor_user_id, visit_type=visit_type,
        scheduled_date=scheduled_date, window_start=window_start, window_end=window_end,
    )
    if conduct_clock:
        set_clock(conduct_clock)
    conduct_visit(visit)
    return report_visit(visit, findings)


def create_satisfied_first_week_visit(site_id: str, **overrides) -> dict:
    """A FIRST_WEEK visit conducted and reported with no findings, which closes it."""
    return create_reported_visit(site_id, findings=[], **overrides)


def create_critical_finding_visit(site_id: str, *, finding_code: str = "MEALS_SERVED_OFFSITE",
                                  **overrides) -> dict:
    """A visit reported with one CRITICAL finding, which suspends the site."""
    return create_reported_visit(
        site_id, findings=[finding(finding_code=finding_code, severity="CRITICAL")], **overrides
    )


def list_actions_for_site(site_id: str) -> List[dict]:
    response = api_client.list_corrective_actions(REVIEWER, params={"site_id": site_id})
    return response.json()["data"]


# --- Claims ------------------------------------------------------------------


def create_draft_claim(sponsor_id: str, claim_month: str = "2026-06", **overrides) -> dict:
    """Open a monthly claim under the sponsor version guard, reading the live version first."""
    payload = create_meal_claim_payload(
        sponsor_id, sponsor_version(sponsor_id), claim_month, **overrides
    )
    return get_success_data(
        api_client.create_meal_claim(payload, make_sponsor_admin_headers(sponsor_id))
    )


def add_line_item(claim: dict, site_id: str) -> dict:
    return get_success_data(
        api_client.create_claim_line_item(
            claim["id"], {"site_id": site_id},
            make_sponsor_admin_headers(claim["sponsor_id"]),
        )
    )


def submit_claim(claim: dict, **overrides) -> dict:
    return get_success_data(
        api_client.submit_meal_claim(
            claim["id"], submit_claim_payload(**overrides),
            make_sponsor_admin_headers(claim["sponsor_id"]),
        )
    )


def run_edit_check(claim: dict) -> dict:
    return get_success_data(api_client.edit_check_meal_claim(claim["id"], REVIEWER))


def pay_claim(claim: dict) -> dict:
    return get_success_data(api_client.pay_meal_claim(claim["id"], REVIEWER))


def open_claim_revision(claim: dict, reason: str = "Reopened for revision.") -> dict:
    return get_success_data(
        api_client.open_meal_claim_revision(claim["id"], {"reason": reason}, REVIEWER)
    )


def setup_june_claim_scenario(*, first_meals: int = TEST_DEFAULTS["FIRST_MEALS"],
                              site_count: int = 1,
                              include_monitoring_visit: bool = True,
                              claim_month: str = "2026-06",
                              service_date: str = FIRST_SERVICE_DATE,
                              claim_clock: str = CLOCK_JUNE_CLAIM_WINDOW,
                              day_kwargs: Optional[Dict[str, Any]] = None,
                              add_line_items: bool = True,
                              **baseline_kwargs) -> dict:
    """The canonical June scenario: approved sponsor with an approved budget, ``site_count``
    approved and operating sites, one finalized service day per site, an optional satisfied
    FIRST_WEEK monitoring visit per site, and a DRAFT June claim with one line item per site.

    Returns the baseline dict extended with: days, day, visits, claim, line_items, line_item.
    """
    scenario = setup_program_baseline(site_count=site_count, **baseline_kwargs)
    days: List[dict] = []
    visits: List[dict] = []
    for site in scenario["sites"]:
        days.append(
            create_finalized_day(
                site["id"], scenario["sponsor"]["id"], service_date,
                first_meals=first_meals, **(day_kwargs or {})
            )
        )
    if include_monitoring_visit:
        # One monitor per site: the monitor window conflict rule is scoped to a single monitor and
        # date, so distinct monitors may hold the same window on the same date.
        for index, site in enumerate(scenario["sites"]):
            visits.append(
                create_satisfied_first_week_visit(
                    site["id"],
                    monitor_user_id=f"mon_{index + 1}",
                    conduct_clock=CLOCK_FIRST_WEEK_VISIT if index == 0 else None,
                )
            )

    set_clock(claim_clock)
    claim = create_draft_claim(scenario["sponsor"]["id"], claim_month)
    line_items = (
        [add_line_item(claim, site["id"]) for site in scenario["sites"]]
        if add_line_items else []
    )

    scenario.update({
        "days": days,
        "day": days[0] if days else None,
        "visits": visits,
        "visit": visits[0] if visits else None,
        "claim": claim,
        "line_items": line_items,
        "line_item": line_items[0] if line_items else None,
    })
    return scenario


def setup_validated_june_claim(*, claimed_operating_cost_cents: int = 30_000,
                               claimed_admin_cost_cents: int = 6_000,
                               **scenario_kwargs) -> dict:
    """The canonical June scenario carried through submit and a clean edit check."""
    scenario = setup_june_claim_scenario(**scenario_kwargs)
    scenario["claim"] = submit_claim(
        scenario["claim"],
        claimed_operating_cost_cents=claimed_operating_cost_cents,
        claimed_admin_cost_cents=claimed_admin_cost_cents,
    )
    scenario["claim"] = run_edit_check(scenario["claim"])
    return scenario


# --- Forecast history --------------------------------------------------------


def setup_finalized_history(site_id: str, sponsor_id: str,
                           days: Sequence[Dict[str, Any]]) -> List[dict]:
    """Finalize a run of service days from ``days`` entries shaped
    {"service_date": ..., "planned_meals": ..., "first_meals": ...}."""
    finalized: List[dict] = []
    for entry in days:
        planned = entry.get("planned_meals", TEST_DEFAULTS["PLANNED_MEALS"])
        finalized.append(
            create_finalized_day(
                site_id, sponsor_id, entry["service_date"],
                first_meals=entry.get("first_meals", 0),
                second_meals=entry.get("second_meals", 0),
                adult_meals=entry.get("adult_meals", 0),
                meal_type=entry.get("meal_type", "LUNCH"),
                planned_meals=planned,
            )
        )
    return finalized
