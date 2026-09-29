"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds all of
its own preconditions from scratch using only declared endpoints.  Helpers use
the lenient setup validator: a broken precondition raises immediately with the
server's own error id instead of surfacing as a confusing assertion later.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import api_client
from .test_users import TEST_USERS, make_resident_headers

PA = TEST_USERS["program_admin"]
HCO = TEST_USERS["compliance_officer"]
HCO2 = TEST_USERS["second_compliance_officer"]
DEV = TEST_USERS["developer"]
DEV2 = TEST_USERS["rival_developer"]
AUDITOR = TEST_USERS["fund_auditor"]

# A ten-unit R-2 development owes exactly one whole affordable unit and no
# residual fraction, so a single onsite unit satisfies the entire obligation.
ONE_UNIT_PROJECT: Dict[str, Any] = {
    "name": "Alder Row",
    "zoning_district": "R-2",
    "total_units": 10,
    "approval_date": "2026-03-01",
}


# =============================================================================
# Tier 1 — single-step primitives
# =============================================================================
def set_clock(current_utc: str, headers: Optional[dict] = None) -> Dict[str, Any]:
    """Move the logical clock and return the sweep counts it reports."""
    return get_success_data(api_client.set_clock(current_utc, headers=headers or PA))


def publish_ordinance(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_ordinance(F.create_ordinance_payload(**overrides), headers=PA)
    )


def publish_ami_schedule(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_ami_schedule(F.create_ami_schedule_payload(**overrides), headers=PA)
    )


def publish_later_ami_schedule(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_ami_schedule(
            F.create_later_ami_schedule_payload(**overrides), headers=PA
        )
    )


def bootstrap_program(
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """Publish the one ordinance vintage and one AMI schedule the rules read."""
    ordinance = publish_ordinance(**(ordinance_overrides or {}))
    ami_schedule = publish_ami_schedule(**(ami_overrides or {}))
    return {"ordinance": ordinance, "ami_schedule": ami_schedule}


def register_project(headers: Optional[dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_project(F.create_project_payload(**overrides), headers=headers or DEV)
    )


def screen_project(project_id: str, headers: Optional[dict] = None) -> Dict[str, Any]:
    return get_success_data(api_client.screen_project(project_id, headers=headers or HCO))


def elect_path(
    project_id: str, compliance_path: str = "ONSITE", headers: Optional[dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.elect_path(project_id, compliance_path, headers=headers or DEV)
    )


def draft_agreement(project_id: str, headers: Optional[dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_agreement(
            F.create_agreement_payload(project_id, **overrides), headers=headers or HCO
        )
    )


def record_agreement(
    agreement_id: str,
    doc_number: str = "REC-2026-0001",
    recorded_at: str = "2026-06-01",
    headers: Optional[dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_agreement(
            agreement_id, doc_number, recorded_at, headers=headers or HCO
        )
    )


def add_unit(
    project_id: str, agreement_id: str, headers: Optional[dict] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_unit(
            F.create_unit_payload(project_id, agreement_id, **overrides), headers=headers or DEV
        )
    )


def record_restriction(
    unit_id: str,
    original_purchase_price_cents: int = 30000000,
    recorded_at: str = "2026-08-01",
    headers: Optional[dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_restriction(
            unit_id, original_purchase_price_cents, recorded_at, headers=headers or HCO
        )
    )


def register_household(headers: Optional[dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_household(F.create_household_payload(**overrides), headers=headers or PA)
    )


def apply_to_lottery(
    household_id: str,
    lottery_event_id: str,
    preference_claims: Any = ...,
) -> Dict[str, Any]:
    """A Resident applies for itself: its X-User-ID is the household's own id."""
    return get_success_data(
        api_client.apply_household(
            household_id,
            lottery_event_id,
            preference_claims=preference_claims,
            headers=make_resident_headers(household_id),
        )
    )


def certify_income(
    household_id: str, unit_id: str, headers: Optional[dict] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_certification(
            F.create_certification_payload(household_id, unit_id, **overrides),
            headers=headers or HCO,
        )
    )


def live_project(project_id: str, headers: Optional[dict] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_project(project_id, headers=headers or DEV))


def live_unit(unit_id: str, headers: Optional[dict] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_unit(unit_id, headers=headers or HCO))


def assess_fee(
    project_id: str, basis: str = "FULL", headers: Optional[dict] = None
) -> Dict[str, Any]:
    """Assess a fee, reading the project's live version for the OCC guard."""
    version = live_project(project_id)["version"]
    return get_success_data(
        api_client.create_in_lieu_fee(
            F.create_in_lieu_fee_payload(project_id, version, basis=basis), headers=headers or PA
        )
    )


def pay_fee(
    fee_id: str, amount_cents: Optional[int] = None, headers: Optional[dict] = None
) -> Dict[str, Any]:
    """Pay a fee; by default settle the whole outstanding balance in one payment."""
    if amount_cents is None:
        fee = get_success_data(api_client.get_in_lieu_fee(fee_id, headers=PA))
        amount_cents = fee["assessed_amount_cents"] - fee["paid_amount_cents"]
    return get_success_data(
        api_client.pay_in_lieu_fee(fee_id, amount_cents, headers=headers or DEV)
    )


def fund_summary(headers: Optional[dict] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_trust_fund_summary(headers=headers or PA))


def request_draw(
    source_fee_id: str,
    amount_cents: int,
    eligible_use: str = "AFFORDABLE_HOUSING_PRODUCTION",
    headers: Optional[dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_disbursement(
            F.create_disbursement_payload(
                source_fee_id, amount_cents, eligible_use=eligible_use
            ),
            headers=headers or PA,
        )
    )


# =============================================================================
# Tier 2 — a screened, path-elected project
# =============================================================================
def screened_project(
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
    developer_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """Program published, project registered and screened once."""
    program = bootstrap_program(ordinance_overrides, ami_overrides)
    project = register_project(
        headers=developer_headers, **(project_overrides or dict(ONE_UNIT_PROJECT))
    )
    project = screen_project(project["id"])
    program["project"] = project
    return program


def path_elected_project(
    compliance_path: str = "ONSITE",
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
    developer_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """A screened project whose compliance path has been elected."""
    ctx = screened_project(
        project_overrides, ordinance_overrides, ami_overrides, developer_headers
    )
    ctx["project"] = elect_path(
        ctx["project"]["id"], compliance_path, headers=developer_headers
    )
    return ctx


def agreement_recorded_project(
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
    recorded_at: str = "2026-06-01",
    developer_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """An ONSITE project carrying one RECORDED regulatory agreement."""
    ctx = path_elected_project(
        "ONSITE", project_overrides, ordinance_overrides, ami_overrides, developer_headers
    )
    agreement = draft_agreement(ctx["project"]["id"], **(agreement_overrides or {}))
    ctx["agreement"] = record_agreement(agreement["id"], recorded_at=recorded_at)
    ctx["project"] = live_project(ctx["project"]["id"])
    return ctx


# =============================================================================
# Tier 3 — projects that carry units
# =============================================================================
def project_with_unit(
    unit_overrides: Optional[dict] = None,
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
    developer_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """An ONSITE project with a recorded agreement and one restricted unit."""
    ctx = agreement_recorded_project(
        project_overrides,
        ordinance_overrides,
        ami_overrides,
        agreement_overrides,
        developer_headers=developer_headers,
    )
    ctx["unit"] = add_unit(
        ctx["project"]["id"],
        ctx["agreement"]["id"],
        headers=developer_headers,
        **(unit_overrides or {}),
    )
    ctx["project"] = live_project(ctx["project"]["id"])
    return ctx


def restricted_ownership_unit(
    unit_overrides: Optional[dict] = None,
    original_purchase_price_cents: int = 30000000,
    restriction_recorded_at: str = "2026-08-01",
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
    agreement_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """An OWNERSHIP unit whose deed restriction is RECORDED and basis frozen."""
    overrides = {"tenure": "OWNERSHIP", "bedrooms": 2}
    overrides.update(unit_overrides or {})
    ctx = project_with_unit(
        unit_overrides=overrides,
        project_overrides=project_overrides,
        ordinance_overrides=ordinance_overrides,
        ami_overrides=ami_overrides,
        agreement_overrides=agreement_overrides,
    )
    ctx["unit"] = record_restriction(
        ctx["unit"]["id"],
        original_purchase_price_cents=original_purchase_price_cents,
        recorded_at=restriction_recorded_at,
    )
    return ctx


def occupied_rental_unit(
    unit_overrides: Optional[dict] = None,
    household_overrides: Optional[dict] = None,
    certification_overrides: Optional[dict] = None,
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """A RENTAL unit taken all the way to OCCUPIED by a certified household.

    Certifying the household also drives the project from AGREEMENT_RECORDED
    into MONITORING, which is the state annual reviews and close-out require.
    """
    ctx = project_with_unit(
        unit_overrides=unit_overrides,
        project_overrides=project_overrides,
        ordinance_overrides=ordinance_overrides,
        ami_overrides=ami_overrides,
    )
    ctx["household"] = register_household(**(household_overrides or {}))
    ctx["certification"] = certify_income(
        ctx["household"]["id"], ctx["unit"]["id"], **(certification_overrides or {})
    )
    ctx["unit"] = live_unit(ctx["unit"]["id"])
    ctx["project"] = live_project(ctx["project"]["id"])
    return ctx


# =============================================================================
# Tier 4 — marketing, lottery and occupancy
# =============================================================================
def submitted_marketing_plan(
    ctx: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[dict] = None,
    unit_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """A project with one unit and one SUBMITTED marketing plan."""
    ctx = ctx or project_with_unit(unit_overrides=unit_overrides)
    ctx["marketing_plan"] = get_success_data(
        api_client.create_marketing_plan(
            F.create_marketing_plan_payload(ctx["project"]["id"], **(plan_overrides or {})),
            headers=DEV,
        )
    )
    return ctx


def approved_marketing_plan(
    ctx: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[dict] = None,
    unit_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """An APPROVED plan; approval also flips every PLANNED unit to MARKETING."""
    ctx = submitted_marketing_plan(ctx, plan_overrides, unit_overrides)
    ctx["marketing_plan"] = get_success_data(
        api_client.review_marketing_plan(
            ctx["marketing_plan"]["id"], "APPROVE", headers=HCO
        )
    )
    if "unit" in ctx:
        ctx["unit"] = live_unit(ctx["unit"]["id"])
    return ctx


def open_lottery_round(
    ctx: Optional[Dict[str, Any]] = None,
    lottery_overrides: Optional[dict] = None,
    plan_overrides: Optional[dict] = None,
    unit_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """A PENDING lottery round against an approved plan."""
    ctx = approved_marketing_plan(ctx, plan_overrides, unit_overrides)
    ctx["lottery_event"] = get_success_data(
        api_client.create_lottery_event(
            F.create_lottery_event_payload(
                ctx["marketing_plan"]["id"], **(lottery_overrides or {})
            ),
            headers=PA,
        )
    )
    return ctx


def lottery_with_applicants(
    applicants: Optional[List[dict]] = None,
    inside_window_at: str = "2026-09-05T00:00:00Z",
    ctx: Optional[Dict[str, Any]] = None,
    lottery_overrides: Optional[dict] = None,
    plan_overrides: Optional[dict] = None,
    unit_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """A PENDING round whose applicants applied inside the half-open window.

    Each entry of `applicants` may carry household field overrides plus an
    optional "preference_claims" list used at apply time.
    """
    ctx = open_lottery_round(ctx, lottery_overrides, plan_overrides, unit_overrides)
    set_clock(inside_window_at)
    ctx["households"] = []
    for spec in applicants or [{}]:
        spec = dict(spec)
        claims = spec.pop("preference_claims", ...)
        household = register_household(**spec)
        ctx["households"].append(apply_to_lottery(household["id"], ctx["lottery_event"]["id"], claims))
    return ctx


def drawn_lottery(
    applicants: Optional[List[dict]] = None,
    inside_window_at: str = "2026-09-05T00:00:00Z",
    after_window_at: str = "2026-09-30T00:00:00Z",
    ctx: Optional[Dict[str, Any]] = None,
    lottery_overrides: Optional[dict] = None,
    plan_overrides: Optional[dict] = None,
    unit_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """A DRAWN round: the window has closed and the draw has been run."""
    ctx = lottery_with_applicants(
        applicants, inside_window_at, ctx, lottery_overrides, plan_overrides, unit_overrides
    )
    set_clock(after_window_at)
    ctx["lottery_event"] = get_success_data(
        api_client.draw_lottery(ctx["lottery_event"]["id"], headers=PA)
    )
    if "unit" in ctx:
        ctx["unit"] = live_unit(ctx["unit"]["id"])
    ctx["marketing_plan"] = get_success_data(
        api_client.get_marketing_plan(ctx["marketing_plan"]["id"], headers=HCO)
    )
    return ctx


# =============================================================================
# Tier 4 — monitoring findings
# =============================================================================
def review_with_finding(
    reported_rent_cents: int,
    review_year: int = 2027,
    ctx: Optional[Dict[str, Any]] = None,
    review_overrides: Optional[dict] = None,
    officer_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """An occupied rental unit carrying one FINDING_ISSUED annual review."""
    ctx = ctx or occupied_rental_unit()
    overrides = {"review_year": review_year, "reported_rent_cents": reported_rent_cents}
    overrides.update(review_overrides or {})
    ctx["monitoring_review"] = get_success_data(
        api_client.create_monitoring_review(
            F.create_monitoring_review_payload(ctx["unit"]["id"], **overrides),
            headers=officer_headers or HCO,
        )
    )
    ctx["unit"] = live_unit(ctx["unit"]["id"])
    return ctx


def review_with_submitted_cure(
    reported_rent_cents: int,
    corrected_rent_cents: int,
    review_year: int = 2027,
    ctx: Optional[Dict[str, Any]] = None,
    officer_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """A finding whose cure has been submitted by the developer."""
    ctx = review_with_finding(
        reported_rent_cents, review_year, ctx, officer_headers=officer_headers
    )
    ctx["monitoring_review"] = get_success_data(
        api_client.submit_cure(
            ctx["monitoring_review"]["id"], corrected_rent_cents, headers=DEV
        )
    )
    ctx["unit"] = live_unit(ctx["unit"]["id"])
    return ctx


# =============================================================================
# Tier 4 — the housing trust fund
# =============================================================================
def fee_path_project(
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    ami_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """A project that elected IN_LIEU_FEE and therefore records no agreement."""
    return path_elected_project(
        "IN_LIEU_FEE", project_overrides, ordinance_overrides, ami_overrides
    )


def funded_trust_fund(
    project_overrides: Optional[dict] = None,
    ordinance_overrides: Optional[dict] = None,
    basis: str = "FULL",
) -> Dict[str, Any]:
    """One fully paid in-lieu assessment, so the fund holds real money."""
    ctx = fee_path_project(project_overrides, ordinance_overrides)
    ctx["fee"] = assess_fee(ctx["project"]["id"], basis=basis)
    ctx["fee"] = pay_fee(ctx["fee"]["id"])
    ctx["summary"] = fund_summary()
    return ctx


# =============================================================================
# Tier 5 — the resale track
# =============================================================================
def submitted_resale(
    proposed_price_cents: int,
    ctx: Optional[Dict[str, Any]] = None,
    resale_overrides: Optional[dict] = None,
    submitter_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """A SUBMITTED resale on a restriction-recorded ownership unit."""
    ctx = ctx or restricted_ownership_unit()
    unit = live_unit(ctx["unit"]["id"])
    payload = F.create_resale_payload(
        unit["id"], unit["version"], proposed_price_cents=proposed_price_cents,
        **(resale_overrides or {}),
    )
    ctx["resale"] = get_success_data(
        api_client.create_resale(payload, headers=submitter_headers or HCO)
    )
    ctx["unit"] = live_unit(unit["id"])
    return ctx


def price_approved_resale(
    proposed_price_cents: int,
    ctx: Optional[Dict[str, Any]] = None,
    resale_overrides: Optional[dict] = None,
    approver_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """A resale whose price is approved and whose ROFR window is therefore open."""
    ctx = submitted_resale(proposed_price_cents, ctx, resale_overrides)
    ctx["resale"] = get_success_data(
        api_client.approve_resale_price(ctx["resale"]["id"], headers=approver_headers or HCO)
    )
    return ctx


def rofr_waived_resale(
    proposed_price_cents: int,
    ctx: Optional[Dict[str, Any]] = None,
    resale_overrides: Optional[dict] = None,
    approver_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """A resale the city has explicitly declined to buy."""
    ctx = price_approved_resale(
        proposed_price_cents, ctx, resale_overrides, approver_headers
    )
    ctx["resale"] = get_success_data(
        api_client.rofr_decision(ctx["resale"]["id"], "WAIVE", headers=PA)
    )
    return ctx


def buyer_certified_resale(
    proposed_price_cents: int,
    ctx: Optional[Dict[str, Any]] = None,
    buyer_overrides: Optional[dict] = None,
    resale_overrides: Optional[dict] = None,
    approver_headers: Optional[dict] = None,
    certifier_headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """A waived resale with a certified buyer attached, ready to close.

    Because the price approver may not also certify the buyer, the two steps are
    taken by two different officers.
    """
    ctx = rofr_waived_resale(
        proposed_price_cents, ctx, resale_overrides, approver_headers or HCO
    )
    ctx["buyer"] = register_household(**(buyer_overrides or {"applicant_name": "Bo Ferreira"}))
    ctx["buyer_certification"] = certify_income(
        ctx["buyer"]["id"], ctx["unit"]["id"], contract_rent_cents=0
    )
    ctx["resale"] = get_success_data(
        api_client.certify_buyer(
            ctx["resale"]["id"],
            ctx["buyer"]["id"],
            ctx["buyer_certification"]["id"],
            headers=certifier_headers or HCO2,
        )
    )
    ctx["unit"] = live_unit(ctx["unit"]["id"])
    return ctx


def closed_resale(
    proposed_price_cents: int,
    ctx: Optional[Dict[str, Any]] = None,
    buyer_overrides: Optional[dict] = None,
    resale_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """A CLOSED resale whose proceeds waterfall has run."""
    ctx = buyer_certified_resale(
        proposed_price_cents, ctx, buyer_overrides, resale_overrides
    )
    ctx["resale"] = get_success_data(
        api_client.close_resale(ctx["resale"]["id"], headers=HCO)
    )
    ctx["unit"] = live_unit(ctx["unit"]["id"])
    return ctx
