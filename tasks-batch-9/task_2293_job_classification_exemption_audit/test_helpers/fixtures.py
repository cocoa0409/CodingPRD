"""Composite setup helpers and pytest fixtures.

The harness empties the database before every individual test, so each helper
builds the state it needs from scratch through the public endpoints only.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    CLASSIFICATION_REVIEWER_HEADERS,
    COMPENSATION_MANAGER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    EMPLOYEE_RELATIONS_LEAD_HEADERS,
    LEGAL_COUNSEL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)
from .types import (
    BackWageMethod,
    CorrectionDecision,
    ExemptionTest,
    ProjectStatus,
    RespondentType,
)

# Standard interview windows used whenever the calendar itself is not the subject.
MANAGER_WINDOW = ("2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z")
INCUMBENT_WINDOW = ("2026-09-11T14:00:00Z", "2026-09-11T15:00:00Z")

# Manager and incumbent accounts whose 6.0 point spread corroborates at 49.6.
MANAGER_ACCOUNT = (46.0, 45, 3, True)
INCUMBENT_ACCOUNT = (52.0, 49, 2, True)


# ---------------------------------------------------------------------------
# Single-step helpers
# ---------------------------------------------------------------------------
def pin_clock(api: ApiClient, current_utc: str = DEFAULT_CLOCK_UTC) -> None:
    get_success_data(api.set_clock(factories.clock_payload(current_utc), PROGRAM_ADMIN_HEADERS))


def register_state_rule(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_state_rule(payload, PROGRAM_ADMIN_HEADERS))


def create_project(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_audit_project(factories.audit_project_payload(**overrides), PROGRAM_ADMIN_HEADERS)
    )


def create_family(api: ApiClient, project_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_job_family(
            factories.job_family_payload(project_id, **overrides), PROGRAM_ADMIN_HEADERS
        )
    )


def advance_project(api: ApiClient, project_id: str, target_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_audit_project_status(
            project_id, factories.project_status_payload(target_status), PROGRAM_ADMIN_HEADERS
        )
    )


def create_position(api: ApiClient, family_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_position(
            factories.position_payload(family_id, **overrides), PROGRAM_ADMIN_HEADERS
        )
    )


def add_duty(api: ApiClient, position_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_duty_statement(
            factories.duty_statement_payload(position_id, **overrides), COMPLIANCE_ANALYST_HEADERS
        )
    )


def book_interview(
    api: ApiClient,
    position_id: str,
    interviewer_user_id: str,
    window: tuple,
    respondent_type: str = RespondentType.MANAGER,
    respondent_ref: str = "MGR-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_interview(
            factories.interview_payload(
                position_id,
                interviewer_user_id,
                window[0],
                window[1],
                respondent_type=respondent_type,
                respondent_ref=respondent_ref,
            ),
            COMPLIANCE_ANALYST_HEADERS,
        )
    )


def complete_interview(api: ApiClient, interview_id: str, account: tuple) -> Dict[str, Any]:
    return get_success_data(
        api.complete_interview(
            interview_id, factories.interview_completion_payload(*account), COMPLIANCE_ANALYST_HEADERS
        )
    )


def attest_interview(api: ApiClient, interview_id: str) -> Dict[str, Any]:
    return get_success_data(api.attest_interview(interview_id, COMPLIANCE_ANALYST_HEADERS))


def read_position(api: ApiClient, position_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_position(position_id, COMPLIANCE_ANALYST_HEADERS))


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_audit_project(project_id, PROGRAM_ADMIN_HEADERS))


def read_family(api: ApiClient, family_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_job_family(family_id, PROGRAM_ADMIN_HEADERS))


def read_interview(api: ApiClient, interview_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_interview(interview_id, COMPLIANCE_ANALYST_HEADERS))


def read_analysis(api: ApiClient, analysis_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_exemption_analysis(analysis_id, COMPLIANCE_ANALYST_HEADERS))


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reclassification_case(case_id, COMPENSATION_MANAGER_HEADERS))


def corroborate_duties(
    api: ApiClient,
    position_id: str,
    interviewer_user_id: str,
    manager_account: tuple = MANAGER_ACCOUNT,
    incumbent_account: tuple = INCUMBENT_ACCOUNT,
    manager_window: tuple = MANAGER_WINDOW,
    incumbent_window: tuple = INCUMBENT_WINDOW,
) -> Dict[str, Any]:
    """Book, complete and attest both sides of the interview pair."""
    manager = book_interview(
        api, position_id, interviewer_user_id, manager_window, RespondentType.MANAGER, "MGR-1"
    )
    complete_interview(api, manager["id"], manager_account)
    attest_interview(api, manager["id"])
    incumbent = book_interview(
        api, position_id, interviewer_user_id, incumbent_window, RespondentType.INCUMBENT, "INC-1"
    )
    complete_interview(api, incumbent["id"], incumbent_account)
    attest_interview(api, incumbent["id"])
    return {"manager": manager, "incumbent": incumbent}


def author_analysis(
    api: ApiClient,
    position_id: str,
    applied_test: str = ExemptionTest.EXECUTIVE,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Read the position version, then create an analysis against it."""
    acting = headers or COMPLIANCE_ANALYST_HEADERS
    position = get_success_data(api.get_position(position_id, acting))
    return get_success_data(
        api.create_exemption_analysis(
            factories.exemption_analysis_payload(
                position_id, position["version"], applied_test=applied_test
            ),
            acting,
        )
    )


def submit_analysis(
    api: ApiClient, analysis_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_exemption_analysis(analysis_id, headers or COMPLIANCE_ANALYST_HEADERS)
    )


def determine_analysis(
    api: ApiClient, analysis_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.determine_exemption_analysis(analysis_id, headers or CLASSIFICATION_REVIEWER_HEADERS)
    )


def open_case(api: ApiClient, position_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_reclassification_case(
            factories.reclassification_case_payload(position_id, **overrides),
            COMPENSATION_MANAGER_HEADERS,
        )
    )


def estimate_back_wages(
    api: ApiClient, case_id: str, method: str = BackWageMethod.FULL_RATE
) -> Dict[str, Any]:
    """Re-read the case version so the estimate always carries a fresh token."""
    case = read_case(api, case_id)
    return get_success_data(
        api.create_back_wage_estimate(
            factories.back_wage_estimate_payload(case_id, case["version"], method),
            COMPENSATION_MANAGER_HEADERS,
        )
    )


def propose_correction(
    api: ApiClient,
    case_id: str,
    amount_cents: int,
    decision: str = CorrectionDecision.SELF_CORRECT_FULL,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_voluntary_correction(
            factories.voluntary_correction_payload(case_id, amount_cents, decision),
            headers or COMPENSATION_MANAGER_HEADERS,
        )
    )


def approve_correction(
    api: ApiClient,
    correction_id: str,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_voluntary_correction(
            correction_id,
            factories.correction_approval_payload(amount_cents),
            headers or LEGAL_COUNSEL_HEADERS,
        )
    )


def send_notice(api: ApiClient, case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.case_communication(
            case_id, factories.communication_payload(**overrides), EMPLOYEE_RELATIONS_LEAD_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# Composite fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def pinned_clock(api: ApiClient) -> str:
    """Every scenario starts from the same logical instant."""
    pin_clock(api)
    return DEFAULT_CLOCK_UTC


@pytest.fixture
def ca_planning_engagement(api: ApiClient, pinned_clock: str) -> Dict[str, Any]:
    """California jurisdiction, an engagement still in PLANNING, one family, one job."""
    register_state_rule(api, factories.california_rule_payload())
    project = create_project(api)
    family = create_family(api, project["id"])
    position = create_position(api, family["id"])
    return {
        "project": project,
        "family": family,
        "position": position,
        "project_id": project["id"],
        "family_id": family["id"],
        "position_id": position["id"],
    }


@pytest.fixture
def ca_engagement(api: ApiClient, pinned_clock: str) -> Dict[str, Any]:
    """California jurisdiction, an engagement in FIELDWORK, one family, one job."""
    register_state_rule(api, factories.california_rule_payload())
    project = create_project(api)
    family = create_family(api, project["id"])
    advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    position = create_position(api, family["id"])
    return {
        "project": project,
        "family": family,
        "position": position,
        "project_id": project["id"],
        "family_id": family["id"],
        "position_id": position["id"],
    }


@pytest.fixture
def willful_ca_engagement(api: ApiClient, pinned_clock: str) -> Dict[str, Any]:
    """A wilful-lookback engagement in a state with its own statutory lookback."""
    register_state_rule(
        api,
        factories.california_rule_payload(
            liquidated_damages_multiplier=1.0, back_wage_lookback_weeks_override=156
        ),
    )
    project = create_project(api, lookback_policy="WILLFUL_3Y")
    family = create_family(api, project["id"])
    advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    position = create_position(api, family["id"])
    return {
        "project": project,
        "family": family,
        "position": position,
        "project_id": project["id"],
        "family_id": family["id"],
        "position_id": position["id"],
    }


@pytest.fixture
def corroborated_engagement(api: ApiClient, ca_engagement: Dict[str, Any]) -> Dict[str, Any]:
    """Both interviews attested, so the job's duties are corroborated at 49.6."""
    interviews = corroborate_duties(api, ca_engagement["position_id"], "int-101")
    return {**ca_engagement, "interviews": interviews}


@pytest.fixture
def submitted_analysis(api: ApiClient, corroborated_engagement: Dict[str, Any]) -> Dict[str, Any]:
    """A submitted analysis whose outcome is NONEXEMPT under the California floors."""
    analysis = author_analysis(api, corroborated_engagement["position_id"])
    submitted = submit_analysis(api, analysis["id"])
    return {**corroborated_engagement, "analysis": submitted, "analysis_id": analysis["id"]}


@pytest.fixture
def determined_engagement(api: ApiClient, submitted_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """The nonexemption is determined, so the job is MISCLASSIFIED."""
    determined = determine_analysis(api, submitted_analysis["analysis_id"])
    return {**submitted_analysis, "analysis": determined}
