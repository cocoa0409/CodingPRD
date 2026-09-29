"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints, so each test
starts from an empty system. Setup calls use the lenient validator, so a broken
precondition surfaces as a setup failure rather than a confusing assertion error.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    APPROVER_USER_ID,
    PREPARER_USER_ID,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_agency_officer_headers,
    make_analyst_headers,
    make_director_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["budget_analyst_headers"]
DIRECTOR = TEST_USERS["budget_director_headers"]
LEGISLATIVE = TEST_USERS["legislative_fiscal_officer_headers"]
CONTROLLER = TEST_USERS["state_controller_headers"]

PHASE_SEQUENCE = ["DEVELOPMENT", "EXECUTIVE_PREP", "LEGISLATIVE", "ENACTED", "EXECUTION"]


# ==========================================================================
# Tier 0 — single-call primitives and readers
# ==========================================================================


def register_agency(agency_code="DOH", name="Department of Health", agency_type="EXECUTIVE") -> dict:
    """Register one agency. The returned id is the officer's X-User-ID."""
    return get_success_data(
        api_client.create_agency(
            f.agency_payload(agency_code=agency_code, name=name, agency_type=agency_type),
            ADMIN,
        )
    )


def open_budget_cycle(**overrides) -> dict:
    """Open one budget cycle in phase DEVELOPMENT."""
    return get_success_data(
        api_client.create_budget_cycle(f.budget_cycle_payload(**overrides), ADMIN)
    )


def read_budget_cycle(cycle_id) -> dict:
    return get_success_data(api_client.get_budget_cycle(cycle_id, ANALYST))


def read_agency(agency_id) -> dict:
    return get_success_data(api_client.get_agency(agency_id, ANALYST))


def read_agency_request(request_id) -> dict:
    return get_success_data(api_client.get_agency_request(request_id, ANALYST))


def read_decision_package(package_id) -> dict:
    return get_success_data(api_client.get_decision_package(package_id, ANALYST))


def read_appropriation(appropriation_id) -> dict:
    return get_success_data(api_client.get_appropriation(appropriation_id, ANALYST))


def read_allotment(allotment_id) -> dict:
    return get_success_data(api_client.get_allotment(allotment_id, ANALYST))


def read_federal_grant(grant_id) -> dict:
    return get_success_data(api_client.get_federal_grant(grant_id, ANALYST))


def read_match_commitment(commitment_id) -> dict:
    return get_success_data(api_client.get_match_commitment(commitment_id, ANALYST))


def read_balance_summary(appropriation_id) -> dict:
    return get_success_data(
        api_client.get_appropriation_balance_summary(appropriation_id, ANALYST)
    )


def cycle_version(cycle_id) -> int:
    return read_budget_cycle(cycle_id)["version"]


def request_version(request_id) -> int:
    return read_agency_request(request_id)["version"]


def appropriation_version(appropriation_id) -> int:
    return read_appropriation(appropriation_id)["version"]


def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock."""
    return get_success_data(api_client.set_current_utc(f.clock_payload(to_iso8601), ADMIN))


# ==========================================================================
# Tier 1 — state progression on single entities
# ==========================================================================


def record_forecast(cycle_id, **overrides) -> dict:
    """Record a DRAFT forecast, pinning the cycle's current version."""
    version = overrides.pop("expected_budget_cycle_version", None)
    if version is None:
        version = cycle_version(cycle_id)
    return get_success_data(
        api_client.create_revenue_forecast(
            f.revenue_forecast_payload(cycle_id, version, **overrides), ANALYST
        )
    )


def adopt_forecast(forecast_id, **payload) -> dict:
    return get_success_data(
        api_client.adopt_revenue_forecast(forecast_id, DIRECTOR, payload or {})
    )


def record_and_adopt_forecast(cycle_id, **overrides) -> dict:
    """Record a forecast and adopt it, so the cycle carries adopted revenue."""
    forecast = record_forecast(cycle_id, **overrides)
    return adopt_forecast(forecast["id"])


def advance_phase(cycle_id, to_phase) -> dict:
    return get_success_data(
        api_client.advance_cycle_phase(cycle_id, {"to_phase": to_phase}, DIRECTOR)
    )


def certify_balance(cycle_id) -> dict:
    return get_success_data(api_client.certify_cycle_balance(cycle_id, DIRECTOR))


def introduce_appropriation(cycle_id, agency_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_appropriation(
            f.appropriation_payload(cycle_id, agency_id, **overrides), LEGISLATIVE
        )
    )


def enact_appropriation(appropriation_id) -> dict:
    return get_success_data(api_client.enact_appropriation(appropriation_id, LEGISLATIVE))


def introduce_and_enact_appropriation(cycle_id, agency_id, **overrides) -> dict:
    appropriation = introduce_appropriation(cycle_id, agency_id, **overrides)
    return enact_appropriation(appropriation["id"])


def record_committee_action(appropriation_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_committee_action(
            f.committee_action_payload(appropriation_id, **overrides), LEGISLATIVE
        )
    )


def open_allotment(appropriation_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_allotment(f.allotment_payload(appropriation_id, **overrides), ANALYST)
    )


def prepare_allotment(allotment_id, preparer_user_id=PREPARER_USER_ID) -> dict:
    return get_success_data(
        api_client.prepare_allotment(allotment_id, make_analyst_headers(preparer_user_id))
    )


def approve_allotment(allotment_id, approver_user_id=APPROVER_USER_ID) -> dict:
    return get_success_data(
        api_client.approve_allotment(allotment_id, make_director_headers(approver_user_id))
    )


def release_allotment(allotment_id) -> dict:
    return get_success_data(api_client.release_allotment(allotment_id, CONTROLLER))


def recall_allotment(allotment_id, reason="funds no longer needed") -> dict:
    return get_success_data(
        api_client.recall_allotment(allotment_id, {"reason": reason}, CONTROLLER)
    )


def post_expenditure(appropriation_id, agency_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_expenditure(
            f.expenditure_payload(appropriation_id, **overrides),
            make_agency_officer_headers(agency_id),
        )
    )


def void_expenditure(expenditure_id, reason="duplicate invoice") -> dict:
    return get_success_data(
        api_client.void_expenditure(expenditure_id, {"reason": reason}, CONTROLLER)
    )


def record_federal_grant(agency_id, cycle_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_federal_grant(
            f.federal_grant_payload(agency_id, cycle_id, **overrides), ANALYST
        )
    )


def pledge_match(grant_id, appropriation_id, agency_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_match_commitment(
            f.match_commitment_payload(grant_id, appropriation_id, **overrides),
            make_agency_officer_headers(agency_id),
        )
    )


def assess_moe(grant_id, basis="SINGLE_YEAR") -> dict:
    return get_success_data(api_client.assess_grant_moe(grant_id, {"basis": basis}, ANALYST))


# ==========================================================================
# Tier 2 — allotment lifecycle shortcuts
# ==========================================================================


def prepared_allotment(appropriation_id, preparer_user_id=PREPARER_USER_ID, **overrides) -> dict:
    """Open an allotment and prepare it. Returns the PREPARED row."""
    allotment = open_allotment(appropriation_id, **overrides)
    return prepare_allotment(allotment["id"], preparer_user_id)


def approved_allotment(
    appropriation_id,
    preparer_user_id=PREPARER_USER_ID,
    approver_user_id=APPROVER_USER_ID,
    **overrides,
) -> dict:
    """Open, prepare and approve an allotment. Returns the APPROVED row."""
    allotment = prepared_allotment(appropriation_id, preparer_user_id, **overrides)
    return approve_allotment(allotment["id"], approver_user_id)


def released_allotment(
    appropriation_id,
    preparer_user_id=PREPARER_USER_ID,
    approver_user_id=APPROVER_USER_ID,
    **overrides,
) -> dict:
    """Walk one allotment from creation to RELEASED. Returns the RELEASED row."""
    allotment = approved_allotment(
        appropriation_id, preparer_user_id, approver_user_id, **overrides
    )
    return release_allotment(allotment["id"])


# ==========================================================================
# Tier 3 — agency request lifecycle
# ==========================================================================


def create_draft_request(cycle_id, agency_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_agency_request(
            f.agency_request_payload(cycle_id, agency_id, **overrides),
            make_agency_officer_headers(agency_id),
        )
    )


def attach_package(request_id, agency_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_decision_package(
            f.decision_package_payload(request_id, **overrides),
            make_agency_officer_headers(agency_id),
        )
    )


def attach_measure(package_id, agency_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_performance_measure(
            f.performance_measure_payload(package_id, **overrides),
            make_agency_officer_headers(agency_id),
        )
    )


def submit_request(request_id, agency_id) -> dict:
    return get_success_data(
        api_client.submit_agency_request(request_id, make_agency_officer_headers(agency_id))
    )


def begin_review(request_id) -> dict:
    return get_success_data(api_client.begin_review_agency_request(request_id, ANALYST))


def return_for_revision(request_id, reason="insufficient justification") -> dict:
    return get_success_data(
        api_client.return_agency_request_for_revision(request_id, {"reason": reason}, ANALYST)
    )


def accept_request(request_id) -> dict:
    return get_success_data(api_client.accept_agency_request(request_id, ANALYST))


def recommend_package(package_id) -> dict:
    return get_success_data(api_client.recommend_decision_package(package_id, ANALYST))


def defer_package(package_id) -> dict:
    return get_success_data(api_client.defer_decision_package(package_id, ANALYST))


def setup_request_with_packages(cycle_id, agency_id, base_budget_cents=None, packages=()) -> tuple:
    """Create a DRAFT request and attach the given packages.

    Each package spec is a dict of decision-package input fields; the optional
    "measures" key holds performance-measure input dicts to attach to it.
    Returns (request, [packages]).
    """
    kwargs = {}
    if base_budget_cents is not None:
        kwargs["base_budget_cents"] = base_budget_cents
    request = create_draft_request(cycle_id, agency_id, **kwargs)
    created = []
    for spec in packages:
        spec = dict(spec)
        measures = spec.pop("measures", [])
        package = attach_package(request["id"], agency_id, **spec)
        for measure in measures:
            attach_measure(package["id"], agency_id, **measure)
        created.append(package)
    return request, created


def setup_accepted_request(cycle_id, agency_id, base_budget_cents=None, packages=()) -> tuple:
    """Drive a request through DRAFT → SUBMITTED → UNDER_REVIEW → ACCEPTED.

    Returns (accepted_request, [packages]).
    """
    request, created = setup_request_with_packages(
        cycle_id, agency_id, base_budget_cents, packages
    )
    submit_request(request["id"], agency_id)
    begin_review(request["id"])
    accepted = accept_request(request["id"])
    return accepted, created


def prepare_recommendation(request_id, **overrides) -> dict:
    """Prepare an executive recommendation, pinning the request's current version."""
    version = overrides.pop("expected_agency_request_version", None)
    if version is None:
        version = request_version(request_id)
    preparer = overrides.pop("prepared_by_user_id", PREPARER_USER_ID)
    return get_success_data(
        api_client.create_executive_recommendation(
            f.executive_recommendation_payload(request_id, version, **overrides),
            make_analyst_headers(preparer),
        )
    )


def approve_recommendation(recommendation_id, approver_user_id=APPROVER_USER_ID) -> dict:
    return get_success_data(
        api_client.approve_executive_recommendation(
            recommendation_id, make_director_headers(approver_user_id)
        )
    )


# ==========================================================================
# Tier 4 — the cycle backbone
# ==========================================================================

DEFAULT_APPROPRIATIONS = (
    {
        "fund_type": "GENERAL",
        "program_code": "P100",
        "introduced_amount_cents": TEST_DEFAULTS["APPROPRIATION_CENTS"],
    },
)

DEFAULT_AGENCIES = (
    {"agency_code": "DOH", "name": "Department of Health", "agency_type": "EXECUTIVE"},
)


def setup_cycle(
    agencies=DEFAULT_AGENCIES,
    appropriations=DEFAULT_APPROPRIATIONS,
    stop_after="EXECUTION",
    revenue_amount_cents=TEST_DEFAULTS["GENERAL_REVENUE_CENTS"],
    revenue_source_code="SALES_TAX",
    revenue_effective_from="2026-07-01T00:00:00Z",
    revenue_effective_to="2027-07-01T00:00:00Z",
    fiscal_year=TEST_DEFAULTS["FISCAL_YEAR"],
    fiscal_year_start_date=TEST_DEFAULTS["FISCAL_YEAR_START_DATE"],
    reserve_balance_cents=TEST_DEFAULTS["RESERVE_BALANCE_CENTS"],
    constitutional_reserve_pct=0.05,
    adopt_revenue=True,
    certify=None,
) -> dict:
    """Walk a cycle from registration up to `stop_after`, introducing appropriations.

    `stop_after` is one of DEVELOPMENT, EXECUTIVE_PREP, LEGISLATIVE, ENACTED, EXECUTION.
    Appropriations are introduced once the cycle reaches LEGISLATIVE; each spec may carry
    "agency_code" to pick its owning agency and "enact" (default True) to control enactment.

    Returns a context dict with keys: agencies (by agency_code), agency, cycle, forecast,
    appropriations (by program_code) and appropriation.
    """
    assert stop_after in PHASE_SEQUENCE, f"unknown stop_after {stop_after}"
    target = PHASE_SEQUENCE.index(stop_after)

    registered = {}
    for spec in agencies:
        agency = register_agency(**spec)
        registered[agency["agency_code"]] = agency
    first_agency = registered[agencies[0]["agency_code"]]

    cycle = open_budget_cycle(
        fiscal_year=fiscal_year,
        fiscal_year_start_date=fiscal_year_start_date,
        reserve_balance_cents=reserve_balance_cents,
        constitutional_reserve_pct=constitutional_reserve_pct,
    )
    forecast = None
    if adopt_revenue:
        forecast = record_and_adopt_forecast(
            cycle["id"],
            source_code=revenue_source_code,
            amount_cents=revenue_amount_cents,
            effective_from=revenue_effective_from,
            effective_to=revenue_effective_to,
        )

    should_certify = certify if certify is not None else target >= PHASE_SEQUENCE.index("LEGISLATIVE")

    if target >= PHASE_SEQUENCE.index("EXECUTIVE_PREP"):
        advance_phase(cycle["id"], "EXECUTIVE_PREP")
        if should_certify:
            certify_balance(cycle["id"])

    introduced = {}
    if target >= PHASE_SEQUENCE.index("LEGISLATIVE"):
        advance_phase(cycle["id"], "LEGISLATIVE")
        for spec in appropriations:
            spec = dict(spec)
            agency_code = spec.pop("agency_code", agencies[0]["agency_code"])
            enact = spec.pop("enact", True)
            owner = registered[agency_code]
            row = introduce_appropriation(cycle["id"], owner["id"], **spec)
            if enact:
                row = enact_appropriation(row["id"])
            introduced[row["program_code"]] = row

    if target >= PHASE_SEQUENCE.index("ENACTED"):
        advance_phase(cycle["id"], "ENACTED")
    if target >= PHASE_SEQUENCE.index("EXECUTION"):
        advance_phase(cycle["id"], "EXECUTION")

    cycle = read_budget_cycle(cycle["id"])
    refreshed = {code: read_appropriation(row["id"]) for code, row in introduced.items()}
    first_program = None
    if appropriations and refreshed:
        first_program = appropriations[0]["program_code"]

    return {
        "agencies": registered,
        "agency": first_agency,
        "cycle": cycle,
        "forecast": forecast,
        "appropriations": refreshed,
        "appropriation": refreshed.get(first_program) if first_program else None,
    }


def setup_execution_cycle(**kwargs) -> dict:
    """The canonical chain: registration through phase EXECUTION with enacted appropriations."""
    kwargs.setdefault("stop_after", "EXECUTION")
    return setup_cycle(**kwargs)


def setup_legislative_cycle(**kwargs) -> dict:
    """Registration through phase LEGISLATIVE, with appropriations introduced."""
    kwargs.setdefault("stop_after", "LEGISLATIVE")
    return setup_cycle(**kwargs)


def setup_executive_prep_cycle(**kwargs) -> dict:
    """Registration through phase EXECUTIVE_PREP with an adopted general-fund forecast."""
    kwargs.setdefault("stop_after", "EXECUTIVE_PREP")
    kwargs.setdefault("appropriations", ())
    return setup_cycle(**kwargs)


def setup_development_cycle(**kwargs) -> dict:
    """One agency plus one cycle in phase DEVELOPMENT."""
    kwargs.setdefault("stop_after", "DEVELOPMENT")
    kwargs.setdefault("appropriations", ())
    kwargs.setdefault("adopt_revenue", False)
    return setup_cycle(**kwargs)


# ==========================================================================
# Tier 5 — accumulation targeting
# ==========================================================================


def setup_appropriation_with_released_cash(
    requested_cents=440_000_000,
    expenditure_cents=None,
    appropriation_cents=TEST_DEFAULTS["APPROPRIATION_CENTS"],
    quarter=1,
    **cycle_kwargs,
) -> dict:
    """Phase EXECUTION with one enacted GENERAL line, one released allotment and
    optionally one posted charge.

    Returns the cycle context extended with keys allotment and expenditure.
    """
    cycle_kwargs.setdefault(
        "appropriations",
        (
            {
                "fund_type": "GENERAL",
                "program_code": "P100",
                "introduced_amount_cents": appropriation_cents,
            },
        ),
    )
    ctx = setup_execution_cycle(**cycle_kwargs)
    appropriation = ctx["appropriation"]
    allotment = released_allotment(
        appropriation["id"], quarter=quarter, requested_cents=requested_cents
    )
    expenditure = None
    if expenditure_cents:
        expenditure = post_expenditure(
            appropriation["id"],
            ctx["agency"]["id"],
            quarter=quarter,
            amount_cents=expenditure_cents,
        )
    ctx["allotment"] = allotment
    ctx["expenditure"] = expenditure
    ctx["cycle"] = read_budget_cycle(ctx["cycle"]["id"])
    ctx["appropriation"] = read_appropriation(appropriation["id"])
    ctx["appropriations"][appropriation["program_code"]] = ctx["appropriation"]
    return ctx


def setup_transfer_pair(
    source_cents=1_000_000_000,
    target_cents=1_000_000_000,
    fund_type="GENERAL",
    **cycle_kwargs,
) -> dict:
    """Phase EXECUTION with two enacted lines of the same agency and fund, P100 and P200."""
    cycle_kwargs.setdefault(
        "appropriations",
        (
            {
                "fund_type": fund_type,
                "program_code": "P100",
                "introduced_amount_cents": source_cents,
            },
            {
                "fund_type": fund_type,
                "program_code": "P200",
                "introduced_amount_cents": target_cents,
            },
        ),
    )
    ctx = setup_execution_cycle(**cycle_kwargs)
    ctx["source"] = ctx["appropriations"]["P100"]
    ctx["target"] = ctx["appropriations"]["P200"]
    return ctx


def propose_transfer(source_id, target_id, headers=None, **overrides) -> dict:
    """Propose a transfer, pinning the source appropriation's current version."""
    version = overrides.pop("expected_source_appropriation_version", None)
    if version is None:
        version = appropriation_version(source_id)
    return get_success_data(
        api_client.create_budget_transfer(
            f.budget_transfer_payload(source_id, target_id, version, **overrides),
            headers or ANALYST,
        )
    )


def approve_transfer(transfer_id, approver_user_id=APPROVER_USER_ID) -> dict:
    return get_success_data(
        api_client.approve_budget_transfer(transfer_id, make_director_headers(approver_user_id))
    )


def execute_transfer(transfer_id) -> dict:
    return get_success_data(api_client.execute_budget_transfer(transfer_id, CONTROLLER))


def reverse_transfer(transfer_id, reason="proposal withdrawn") -> dict:
    return get_success_data(
        api_client.reverse_budget_transfer(transfer_id, {"reason": reason}, CONTROLLER)
    )


def executed_transfer(source_id, target_id, amount_cents=100_000_000, **overrides) -> dict:
    """Propose, approve and execute one transfer. Returns the EXECUTED row."""
    transfer = propose_transfer(source_id, target_id, amount_cents=amount_cents, **overrides)
    approve_transfer(transfer["id"], APPROVER_USER_ID)
    return execute_transfer(transfer["id"])
