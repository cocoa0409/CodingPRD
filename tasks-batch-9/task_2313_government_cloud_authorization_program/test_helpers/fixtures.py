"""Composite state builders.

Every test runs against a freshly launched server with an empty database, so all
preconditions must be created through the API. These builders assemble the state
progressions the contract demands — a categorized offering, a path-selected
offering, an engagement that has delivered its report, a live authorization with
its first monitoring period, a reuse grant in a chosen access state — so tests
can state a precondition in one call and spend their body on the behaviour under
test.

Each builder threads an ``env`` dict of captured identifiers, mirroring the way
one workflow stage feeds the next. Callers may start from any stage by passing
the ``env`` returned by the stage before it.
"""

from typing import Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ASSESSOR_1,
    BOARD_1,
    BOARD_2,
    CSP_LEAD_1,
    make_agency_official_headers,
    make_assessor_headers,
    make_board_headers,
    make_csp_lead_headers,
)

# ---------------------------------------------------------------------------
# Canonical instants used across the workflow builders
# ---------------------------------------------------------------------------

#: Clock the program is stood up at.
SETUP_CLOCK = "2026-02-01T00:00:00Z"

#: Clock the assessment report is delivered and the package decided at.
AUTHORIZATION_CLOCK = "2026-03-30T00:00:00Z"

#: A control set that documents every control of ``MODERATE_FAMILIES``, giving
#: 100.00 coverage: two of two in AC and one of one in SC.
FULL_COVERAGE_CONTROLS = (("AC-2", "AC"), ("AC-3", "AC"), ("SC-7", "SC"))


# ---------------------------------------------------------------------------
# Low-level single-call helpers
# ---------------------------------------------------------------------------


def set_clock(client: ApiClient, to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock; returns the response data carrying ``current_utc``."""
    return get_success_data(
        client.set_clock(
            f.build_clock_payload(to_iso8601), headers or make_board_headers(BOARD_1)
        ),
        200,
    )


def create_agency(
    client: ApiClient,
    *,
    name: str = "Department of Transportation",
    agency_code: str = "DOT",
    **overrides,
) -> dict:
    """Register one agency and return its row."""
    return get_success_data(
        client.create_agency(
            f.build_agency_payload(name=name, agency_code=agency_code, **overrides),
            make_board_headers(BOARD_1),
        ),
        201,
    )


def create_baseline(
    client: ApiClient,
    *,
    impact_level: str = "MODERATE",
    families: Optional[List[dict]] = None,
    effective_from: str = "2026-01-01T00:00:00Z",
    **overrides,
) -> dict:
    """Publish one control baseline and return its row."""
    return get_success_data(
        client.create_control_baseline(
            f.build_baseline_payload(
                impact_level=impact_level,
                families=families,
                effective_from=effective_from,
                **overrides,
            ),
            make_board_headers(BOARD_1),
        ),
        201,
    )


def read_offering(client: ApiClient, offering_id: str, headers: Optional[dict] = None) -> dict:
    """Read one offering row."""
    return get_success_data(
        client.get_offering(offering_id, headers or make_csp_lead_headers()), 200
    )


def offering_version(client: ApiClient, offering_id: str) -> int:
    """The offering's current ``version``, for ``expected_offering_version``."""
    return read_offering(client, offering_id)["version"]


def read_engagement(client: ApiClient, engagement_id: str) -> dict:
    """Read one assessment engagement row."""
    return get_success_data(
        client.get_engagement(engagement_id, make_csp_lead_headers()), 200
    )


def read_package(client: ApiClient, package_id: str, headers: Optional[dict] = None) -> dict:
    """Read one authorization package row."""
    return get_success_data(
        client.get_package(package_id, headers or make_csp_lead_headers()), 200
    )


def read_authorization(client: ApiClient, authorization_id: str) -> dict:
    """Read one authorization row."""
    return get_success_data(
        client.get_authorization(authorization_id, make_csp_lead_headers()), 200
    )


def authorization_version(client: ApiClient, authorization_id: str) -> int:
    """The authorization's current ``version``, for ``expected_authorization_version``."""
    return read_authorization(client, authorization_id)["version"]


def read_poam_item(client: ApiClient, poam_item_id: str) -> dict:
    """Read one plan-of-action item row."""
    return get_success_data(
        client.get_poam_item(poam_item_id, make_csp_lead_headers()), 200
    )


def read_risk_summary(client: ApiClient, authorization_id: str) -> dict:
    """Read the live risk-summary computation beside the stored score."""
    return get_success_data(
        client.get_risk_summary(authorization_id, make_csp_lead_headers()), 200
    )


def read_monitoring_period(client: ApiClient, period_id: str) -> dict:
    """Read one monitoring period row."""
    return get_success_data(
        client.get_monitoring_period(period_id, make_csp_lead_headers()), 200
    )


def read_reuse_grant(client: ApiClient, grant_id: str) -> dict:
    """Read one reuse grant row."""
    return get_success_data(
        client.get_reuse_grant(grant_id, make_csp_lead_headers()), 200
    )


def read_agency(client: ApiClient, agency_id: str) -> dict:
    """Read one agency row with its notice and reuse counters."""
    return get_success_data(client.get_agency(agency_id, make_board_headers()), 200)


def list_poam_items(client: ApiClient, **params) -> List[dict]:
    """The plan-of-action items matching the given filters, in page order."""
    return get_success_data(
        client.list_poam_items(make_csp_lead_headers(), params or None), 200
    )


def list_monitoring_periods(client: ApiClient, authorization_id: str, **params) -> List[dict]:
    """The monitoring periods of one authorization, in page order."""
    return get_success_data(
        client.list_monitoring_periods(
            authorization_id, make_csp_lead_headers(), params or None
        ),
        200,
    )


def list_test_slots(client: ApiClient, engagement_id: str, **params) -> List[dict]:
    """The testing schedule of one engagement, in page order."""
    return get_success_data(
        client.list_test_slots(engagement_id, make_assessor_headers(), params or None),
        200,
    )


# ---------------------------------------------------------------------------
# Tier 1: reference data
# ---------------------------------------------------------------------------


def seed_reference_data(
    client: ApiClient,
    *,
    clock: Optional[str] = SETUP_CLOCK,
    impact_level: str = "MODERATE",
    families: Optional[List[dict]] = None,
    agency_name: str = "Department of Transportation",
    agency_code: str = "DOT",
    sponsorship_capacity: int = 3,
) -> Dict:
    """Set the clock, register one agency and publish one control baseline.

    Returns an ``env`` carrying the agency row and its official's headers — the
    ``AgencyAuthorizingOfficial`` identity is the agency's ``id``, so it cannot
    be known before this call.
    """
    env: Dict = {}
    if clock is not None:
        env["clock"] = set_clock(client, clock)["current_utc"]
        env["clock_set_to"] = clock
    agency = create_agency(
        client,
        name=agency_name,
        agency_code=agency_code,
        sponsorship_capacity=sponsorship_capacity,
    )
    baseline = create_baseline(client, impact_level=impact_level, families=families)
    env.update(
        {
            "agency": agency,
            "agency_id": agency["id"],
            "agency_code": agency_code,
            "agency_headers": make_agency_official_headers(agency["id"]),
            "baseline": baseline,
            "baseline_id": baseline["id"],
            "baseline_impact_level": impact_level,
        }
    )
    return env


def add_agency(
    client: ApiClient, env: Dict, *, name: str, agency_code: str, key: str, **overrides
) -> Dict:
    """Register a further agency and file it in ``env`` under ``key``."""
    agency = create_agency(client, name=name, agency_code=agency_code, **overrides)
    env[key] = agency
    env[f"{key}_id"] = agency["id"]
    env[f"{key}_headers"] = make_agency_official_headers(agency["id"])
    return env


# ---------------------------------------------------------------------------
# Tier 2: offering through categorization and path selection
# ---------------------------------------------------------------------------

#: One MODERATE data category, confirmed, which is enough to determine a
#: MODERATE final impact level.
DEFAULT_CATEGORIES = (
    {
        "category_code": "PII",
        "confidentiality_impact": "MODERATE",
        "integrity_impact": "MODERATE",
        "availability_impact": "LOW",
        "confirm": True,
    },
)


def seed_draft_offering(
    client: ApiClient,
    env: Optional[Dict] = None,
    *,
    name: str = "GovCloud Compute",
    assessment_budget_usd: float = 400000.00,
    lead_id: str = CSP_LEAD_1,
    key: str = "offering",
    **overrides,
) -> Dict:
    """Create one offering in ``DRAFT`` owned by the acting compliance lead."""
    env = dict(env) if env else {}
    lead_headers = make_csp_lead_headers(lead_id)
    offering = get_success_data(
        client.create_offering(
            f.build_offering_payload(
                name=name, assessment_budget_usd=assessment_budget_usd, **overrides
            ),
            lead_headers,
        ),
        201,
    )
    env.setdefault("lead_id", lead_id)
    env.setdefault("lead_headers", lead_headers)
    env[key] = offering
    env[f"{key}_id"] = offering["id"]
    if key == "offering":
        env["assessment_budget_usd"] = assessment_budget_usd
    return env


def declare_categories(
    client: ApiClient,
    env: Dict,
    categories=DEFAULT_CATEGORIES,
    *,
    offering_key: str = "offering",
) -> Dict:
    """Declare data categories on an offering, confirming those marked ``confirm``.

    Confirmation is a government act, so it is performed by a
    ``ProgramBoardReviewer``.
    """
    offering_id = env[f"{offering_key}_id"]
    rows = env.setdefault("data_categories", {})
    for spec in categories:
        spec = dict(spec)
        confirm = spec.pop("confirm", False)
        row = get_success_data(
            client.create_data_category(
                offering_id, f.build_data_category_payload(**spec), env["lead_headers"]
            ),
            201,
        )
        if confirm:
            row = get_success_data(
                client.confirm_data_category(
                    row["id"],
                    f.build_category_decision_payload("CONFIRM"),
                    make_board_headers(BOARD_1),
                ),
                200,
            )
        rows[spec["category_code"]] = row
    return env


def seed_categorized_offering(
    client: ApiClient,
    env: Optional[Dict] = None,
    *,
    categories=DEFAULT_CATEGORIES,
    offering_key: str = "offering",
    **offering_kwargs,
) -> Dict:
    """Drive an offering ``DRAFT -> CATEGORIZED`` with its baseline bound."""
    if env is None or f"{offering_key}_id" not in env:
        env = seed_draft_offering(client, env, key=offering_key, **offering_kwargs)
    env = declare_categories(client, env, categories, offering_key=offering_key)
    env[offering_key] = get_success_data(
        client.determine_impact(
            env[f"{offering_key}_id"], {}, make_board_headers(BOARD_1)
        ),
        200,
    )
    return env


def seed_path_selected_offering(
    client: ApiClient,
    env: Optional[Dict] = None,
    *,
    authorization_path: str = "AGENCY_SPONSORED",
    offering_key: str = "offering",
    **categorized_kwargs,
) -> Dict:
    """Drive an offering ``CATEGORIZED -> PATH_SELECTED`` on the chosen path."""
    if env is None or env.get(f"{offering_key}_id") is None:
        env = seed_categorized_offering(
            client, env, offering_key=offering_key, **categorized_kwargs
        )
    elif env[offering_key]["status"] == "DRAFT":
        env = seed_categorized_offering(
            client, env, offering_key=offering_key, **categorized_kwargs
        )
    sponsor_agency_id = (
        env["agency_id"] if authorization_path == "AGENCY_SPONSORED" else None
    )
    env[offering_key] = get_success_data(
        client.select_path(
            env[f"{offering_key}_id"],
            f.build_path_selection_payload(
                authorization_path=authorization_path,
                sponsor_agency_id=sponsor_agency_id,
            ),
            env["lead_headers"],
        ),
        200,
    )
    if offering_key == "offering":
        env["authorization_path"] = authorization_path
    return env


def seed_control_implementations(
    client: ApiClient,
    env: Dict,
    controls=FULL_COVERAGE_CONTROLS,
    *,
    offering_key: str = "offering",
    **overrides,
) -> Dict:
    """Record control implementations, documented and ``IMPLEMENTED`` by default.

    ``controls`` is a sequence of ``(control_id, family_code)`` pairs, or of
    dicts when a row needs a non-default status or ``crm_documented`` flag.
    """
    rows = env.setdefault("control_implementations", {})
    for control in controls:
        if isinstance(control, dict):
            spec = dict(control)
        else:
            spec = {"control_id": control[0], "family_code": control[1]}
        spec.update(overrides)
        row = get_success_data(
            client.create_control_implementation(
                f.build_control_implementation_payload(
                    env[f"{offering_key}_id"], **spec
                ),
                env["lead_headers"],
            ),
            201,
        )
        rows[row["control_id"]] = row
    return env


# ---------------------------------------------------------------------------
# Tier 3: engagement lifecycle
# ---------------------------------------------------------------------------


def _plan_approver_headers(env: Dict) -> dict:
    """Plan approval belongs to the sponsoring agency or to the program board."""
    if env.get("authorization_path") == "AGENCY_SPONSORED":
        return env["agency_headers"]
    return make_board_headers(BOARD_1)


def seed_engagement(
    client: ApiClient,
    env: Dict,
    *,
    contracted_hours: float = 200.00,
    labor_cost_usd: float = 120000.00,
    assessor_user_id: str = ASSESSOR_1,
    submit_plan: bool = True,
    approve_plan: bool = True,
    planned_test_start: str = "2026-03-01T00:00:00Z",
    planned_test_end: str = "2026-03-31T00:00:00Z",
    offering_key: str = "offering",
) -> Dict:
    """Create an engagement and optionally drive it to ``PLAN_APPROVED``.

    Approving the plan bubbles the offering ``PATH_SELECTED -> IN_ASSESSMENT``,
    so the offering row in ``env`` is refreshed afterwards.
    """
    engagement = get_success_data(
        client.create_engagement(
            f.build_engagement_payload(
                env[f"{offering_key}_id"],
                contracted_hours=contracted_hours,
                labor_cost_usd=labor_cost_usd,
                assessor_user_id=assessor_user_id,
            ),
            env["lead_headers"],
        ),
        201,
    )
    env["engagement"] = engagement
    env["engagement_id"] = engagement["id"]
    env["assessor_user_id"] = assessor_user_id
    env["assessor_headers"] = make_assessor_headers(assessor_user_id)
    env["contracted_hours"] = contracted_hours
    env["labor_cost_usd"] = labor_cost_usd

    if submit_plan:
        env["engagement"] = get_success_data(
            client.submit_plan(
                engagement["id"],
                f.build_plan_payload(planned_test_start, planned_test_end),
                env["assessor_headers"],
            ),
            200,
        )
    if submit_plan and approve_plan:
        env["engagement"] = get_success_data(
            client.decide_plan(
                engagement["id"],
                f.build_plan_decision_payload("APPROVE"),
                _plan_approver_headers(env),
            ),
            200,
        )
        env[offering_key] = read_offering(client, env[f"{offering_key}_id"])
    return env


def seed_test_slot(
    client: ApiClient,
    env: Dict,
    *,
    start_at: str = "2026-03-02T09:00:00Z",
    end_at: str = "2026-03-02T17:00:00Z",
    hours: float = 8.00,
    family_code: str = "AC",
    key: str = "slot",
) -> Dict:
    """Schedule one test slot against the engagement's hour pool."""
    slot = get_success_data(
        client.create_test_slot(
            f.build_test_slot_payload(
                env["engagement_id"],
                start_at=start_at,
                end_at=end_at,
                hours=hours,
                family_code=family_code,
            ),
            env["assessor_headers"],
        ),
        201,
    )
    env.setdefault("slots", {})[key] = slot
    env[f"{key}_id"] = slot["id"]
    env["engagement"] = read_engagement(client, env["engagement_id"])
    return env


def seed_report_delivered(
    client: ApiClient,
    env: Dict,
    *,
    findings: Optional[List[dict]] = None,
    ensure_slot: bool = True,
    report_at: Optional[str] = None,
    offering_key: str = "offering",
) -> Dict:
    """Drive an engagement to ``REPORT_DELIVERED``.

    An engagement must be in ``TESTING`` to deliver its report, and the first
    slot of an engagement is what moves it there, so one slot is scheduled
    unless the caller has already scheduled its own.
    """
    if ensure_slot and not env.get("slots"):
        env = seed_test_slot(client, env)
    if report_at is not None:
        set_clock(client, report_at)
        env["clock_set_to"] = report_at
    env["engagement"] = get_success_data(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(findings),
            env["assessor_headers"],
        ),
        200,
    )
    env["assessment_findings"] = list_poam_items(
        client, offering_id=env[f"{offering_key}_id"]
    )
    return env


# ---------------------------------------------------------------------------
# Tier 4: package lifecycle
# ---------------------------------------------------------------------------


def seed_package(
    client: ApiClient,
    env: Dict,
    *,
    expected_offering_version: Optional[int] = None,
    offering_key: str = "offering",
) -> Dict:
    """Create an authorization package in ``DRAFT`` against the live offering version."""
    version = (
        expected_offering_version
        if expected_offering_version is not None
        else offering_version(client, env[f"{offering_key}_id"])
    )
    package = get_success_data(
        client.create_package(
            f.build_package_payload(
                env[f"{offering_key}_id"], env["engagement_id"], version
            ),
            env["lead_headers"],
        ),
        201,
    )
    env["package"] = package
    env["package_id"] = package["id"]
    return env


def submit_package(client: ApiClient, env: Dict) -> Dict:
    """Submit the package, freezing coverage, risk and finding counts."""
    env["package"] = get_success_data(
        client.submit_package(env["package_id"], env["lead_headers"]), 200
    )
    return env


def review_package(client: ApiClient, env: Dict, *, reviewer: str = BOARD_1) -> Dict:
    """Take the submitted package into program review."""
    env["package"] = get_success_data(
        client.review_package(env["package_id"], make_board_headers(reviewer)), 200
    )
    env["reviewed_by_user_id"] = reviewer
    return env


def request_revision(
    client: ApiClient, env: Dict, *, revision_note: str, reviewer: str = BOARD_1
) -> Dict:
    """Send the package back for revision, or reject it at the revision limit."""
    env["package"] = get_success_data(
        client.request_package_revision(
            env["package_id"],
            f.build_revision_request_payload(revision_note),
            make_board_headers(reviewer),
        ),
        200,
    )
    return env


def _decision_headers(env: Dict) -> dict:
    """The package decision belongs to the sponsor agency or to a second board member."""
    if env.get("authorization_path") == "AGENCY_SPONSORED":
        return env["agency_headers"]
    return make_board_headers(BOARD_2)


def decide_package(
    client: ApiClient,
    env: Dict,
    *,
    decision: str = "AUTHORIZE",
    headers: Optional[dict] = None,
    offering_key: str = "offering",
) -> Dict:
    """Issue the authorization decision and capture the minted authorization."""
    env["package"] = get_success_data(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload(decision),
            headers or _decision_headers(env),
        ),
        200,
    )
    env[offering_key] = read_offering(client, env[f"{offering_key}_id"])
    if decision == "AUTHORIZE":
        authorizations = get_success_data(
            client.list_authorizations(
                make_csp_lead_headers(), {"package_id": env["package_id"]}
            ),
            200,
        )
        env["authorization"] = authorizations[0]
        env["authorization_id"] = authorizations[0]["id"]
        periods = list_monitoring_periods(client, env["authorization_id"])
        env["monitoring_periods"] = periods
        if periods:
            env["period"] = periods[0]
            env["period_id"] = periods[0]["id"]
    return env


def seed_submitted_package(
    client: ApiClient, env: Dict, *, reviewed: bool = True, reviewer: str = BOARD_1
) -> Dict:
    """Create, submit and (by default) take a package into review."""
    env = seed_package(client, env)
    env = submit_package(client, env)
    if reviewed:
        env = review_package(client, env, reviewer=reviewer)
    return env


# ---------------------------------------------------------------------------
# Tier 5: the full authorization prelude
# ---------------------------------------------------------------------------


def seed_authorized_offering(
    client: ApiClient,
    *,
    clock: str = SETUP_CLOCK,
    authorized_at: str = AUTHORIZATION_CLOCK,
    impact_level: str = "MODERATE",
    families: Optional[List[dict]] = None,
    authorization_path: str = "AGENCY_SPONSORED",
    agency_name: str = "Department of Transportation",
    agency_code: str = "DOT",
    offering_name: str = "GovCloud Compute",
    assessment_budget_usd: float = 400000.00,
    contracted_hours: float = 200.00,
    labor_cost_usd: float = 120000.00,
    controls=FULL_COVERAGE_CONTROLS,
    categories=DEFAULT_CATEGORIES,
    findings: Optional[List[dict]] = None,
    reviewer: str = BOARD_1,
) -> Dict:
    """Build a live authorization end to end.

    The chain is: clock, agency, baseline, offering, data category, impact
    determination, path selection, control implementations, engagement, plan,
    plan approval, test slot, clock advance, report, package, submit, review,
    ``AUTHORIZE``. The returned ``env`` carries the authorization, the first
    monitoring period auto-created for the month containing ``authorized_at``,
    and any assessment-sourced findings the report opened.
    """
    env = seed_reference_data(
        client,
        clock=clock,
        impact_level=impact_level,
        families=families,
        agency_name=agency_name,
        agency_code=agency_code,
    )
    env = seed_path_selected_offering(
        client,
        env,
        authorization_path=authorization_path,
        categories=categories,
        name=offering_name,
        assessment_budget_usd=assessment_budget_usd,
    )
    env = seed_control_implementations(client, env, controls)
    env = seed_engagement(
        client,
        env,
        contracted_hours=contracted_hours,
        labor_cost_usd=labor_cost_usd,
    )
    env = seed_report_delivered(client, env, findings=findings, report_at=authorized_at)
    env = seed_submitted_package(client, env, reviewer=reviewer)
    env = decide_package(client, env, decision="AUTHORIZE")
    env["authorized_at"] = authorized_at
    return env


# ---------------------------------------------------------------------------
# Findings, deviations and remediation
# ---------------------------------------------------------------------------


def seed_poam_item(
    client: ApiClient,
    env: Dict,
    *,
    severity: str = "MODERATE",
    detected_at: Optional[str] = None,
    control_id: str = "AC-2",
    key: str = "poam",
    offering_key: str = "offering",
    **overrides,
) -> Dict:
    """File one plan-of-action item directly against the offering."""
    item = get_success_data(
        client.create_poam_item(
            f.build_poam_item_payload(
                env[f"{offering_key}_id"],
                control_id=control_id,
                severity=severity,
                detected_at=detected_at or env.get("clock_set_to", SETUP_CLOCK),
                **overrides,
            ),
            env["lead_headers"],
        ),
        201,
    )
    env.setdefault("poam_items", {})[key] = item
    env[f"{key}_id"] = item["id"]
    return env


#: Which role owns which remediation action (PRD 3.6): the lead starts work and
#: submits evidence, the assessor verifies closure and reopens.
_REMEDIATION_ACTOR = {
    "START": "lead",
    "SUBMIT_EVIDENCE": "lead",
    "VERIFY_CLOSE": "assessor",
    "REOPEN": "assessor",
}


def drive_remediation(
    client: ApiClient, env: Dict, poam_item_id: str, actions: Sequence = ()
) -> dict:
    """Advance a finding's remediation dimension through a sequence of actions.

    Each action is issued by the role that owns it, so a caller can write
    ``drive_remediation(client, env, item_id, ["START", "SUBMIT_EVIDENCE"])``
    without tracking which party may do what.
    """
    row = None
    for action in actions:
        headers = (
            env["lead_headers"]
            if _REMEDIATION_ACTOR[action] == "lead"
            else env.get("assessor_headers", make_assessor_headers())
        )
        row = get_success_data(
            client.advance_remediation(
                poam_item_id, f.build_remediation_payload(action), headers
            ),
            200,
        )
    return row


def seed_deviation(
    client: ApiClient,
    env: Dict,
    poam_item_id: str,
    *,
    kind: str = "OPERATIONAL_REQUIREMENT",
    requested_extension_days: int = 0,
    review_queue: Optional[str] = None,
    router: str = BOARD_1,
    key: str = "deviation",
) -> Dict:
    """File a deviation request and optionally route it into a review queue."""
    deviation = get_success_data(
        client.create_deviation_request(
            f.build_deviation_payload(
                poam_item_id,
                kind=kind,
                requested_extension_days=requested_extension_days,
            ),
            env["lead_headers"],
        ),
        201,
    )
    if review_queue is not None:
        deviation = get_success_data(
            client.route_deviation(
                deviation["id"],
                f.build_route_payload(review_queue),
                make_board_headers(router),
            ),
            200,
        )
        env[f"{key}_routed_by"] = router
    env[key] = deviation
    env[f"{key}_id"] = deviation["id"]
    return env


def decide_deviation(
    client: ApiClient,
    env: Dict,
    deviation_id: str,
    *,
    decision: str = "APPROVE",
    headers: Optional[dict] = None,
    decider: str = BOARD_2,
) -> dict:
    """Decide a routed deviation request.

    A board-queue request must be decided by a board member other than the one
    who routed it; an agency-queue request belongs to the sponsoring agency's
    official.
    """
    if headers is None:
        queue = read_deviation(client, deviation_id)["review_queue"]
        headers = (
            make_board_headers(decider) if queue == "BOARD" else env["agency_headers"]
        )
    return get_success_data(
        client.decide_deviation(
            deviation_id, f.build_deviation_decision_payload(decision), headers
        ),
        200,
    )


def read_deviation(client: ApiClient, deviation_id: str) -> dict:
    """Read one deviation request row."""
    return get_success_data(
        client.get_deviation_request(deviation_id, make_csp_lead_headers()), 200
    )


# ---------------------------------------------------------------------------
# Monitoring and reuse
# ---------------------------------------------------------------------------


def open_monitoring_period(
    client: ApiClient, env: Dict, period_month: str, *, key: str = "period"
) -> Dict:
    """Open a monthly monitoring period on the authorization."""
    period = get_success_data(
        client.create_monitoring_period(
            env["authorization_id"],
            f.build_monitoring_period_payload(period_month),
            env["lead_headers"],
        ),
        201,
    )
    env[key] = period
    env[f"{key}_id"] = period["id"]
    return env


def submit_scans(
    client: ApiClient,
    env: Dict,
    period_id: str,
    *,
    scan_types: Optional[List[str]] = None,
) -> dict:
    """Submit the monthly vulnerability scans for a monitoring period."""
    return get_success_data(
        client.create_scan_submission(
            period_id, f.build_scan_submission_payload(scan_types), env["lead_headers"]
        ),
        201,
    )


def close_period(
    client: ApiClient, env: Dict, period_id: str, *, headers: Optional[dict] = None
) -> dict:
    """Close a monitoring period and propagate the posture consequences."""
    return get_success_data(
        client.close_monitoring_period(
            period_id, headers or make_board_headers(BOARD_1)
        ),
        200,
    )


def seed_reuse_grant(
    client: ApiClient,
    env: Dict,
    *,
    agency_id: str,
    agency_headers: Optional[dict] = None,
    advance_to: str = "REQUESTED",
    findings_count: int = 0,
    key: str = "grant",
) -> Dict:
    """Request reuse of the authorization and advance the grant to a chosen state.

    ``advance_to`` accepts ``REQUESTED``, ``PACKAGE_ACCESS_GRANTED``,
    ``INCREMENTAL_REVIEW`` or ``REUSE_ACCEPTED``.
    """
    headers = agency_headers or make_agency_official_headers(agency_id)
    grant = get_success_data(
        client.create_reuse_grant(
            f.build_reuse_grant_payload(
                env["authorization_id"],
                agency_id,
                authorization_version(client, env["authorization_id"]),
            ),
            headers,
        ),
        201,
    )
    if advance_to in (
        "PACKAGE_ACCESS_GRANTED",
        "INCREMENTAL_REVIEW",
        "REUSE_ACCEPTED",
    ):
        grant = get_success_data(
            client.grant_package_access(grant["id"], env["lead_headers"]), 200
        )
    if advance_to == "INCREMENTAL_REVIEW":
        grant = get_success_data(
            client.record_incremental_review(
                grant["id"],
                f.build_incremental_review_payload("MORE_INFO", findings_count),
                headers,
            ),
            200,
        )
    if advance_to == "REUSE_ACCEPTED":
        grant = get_success_data(
            client.record_incremental_review(
                grant["id"],
                f.build_incremental_review_payload("ACCEPT", findings_count),
                headers,
            ),
            200,
        )
    env[key] = grant
    env[f"{key}_id"] = grant["id"]
    return env


def seed_change_request(
    client: ApiClient,
    env: Dict,
    *,
    window_start: str,
    window_end: str,
    change_kind: str = "TECH_REFRESH",
    decision: Optional[str] = None,
    key: str = "change_request",
    offering_key: str = "offering",
    **overrides,
) -> Dict:
    """File a significant change request and optionally decide it."""
    request = get_success_data(
        client.create_change_request(
            f.build_change_request_payload(
                env[f"{offering_key}_id"],
                window_start,
                window_end,
                change_kind=change_kind,
                **overrides,
            ),
            env["lead_headers"],
        ),
        201,
    )
    if decision is not None:
        headers = (
            env["agency_headers"]
            if env.get("authorization_path") == "AGENCY_SPONSORED"
            else make_board_headers(BOARD_1)
        )
        request = get_success_data(
            client.decide_change_request(
                request["id"], f.build_change_decision_payload(decision), headers
            ),
            200,
        )
    env[key] = request
    env[f"{key}_id"] = request["id"]
    env[offering_key] = read_offering(client, env[f"{offering_key}_id"])
    return env
