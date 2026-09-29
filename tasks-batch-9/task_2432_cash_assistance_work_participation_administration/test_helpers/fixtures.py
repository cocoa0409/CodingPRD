"""Composite state builders.

The service starts with an empty database and the logical clock at its epoch
before every test, so every builder here drives the public endpoints to reach
the state it needs. Each builder returns the parsed entity so a test can chain
from it.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import validate_paginated

from . import factories
from .api_client import ApiClient
from .test_users import (
    ANALYST_ID,
    CASEWORKER_ID,
    FISCAL_OFFICER_ID,
    SUPERVISOR_ID,
    caseworker_headers,
    analyst_headers,
    fiscal_officer_headers,
    fraud_investigator_headers,
    make_applicant_headers,
    supervisor_headers,
    work_specialist_headers,
)


def _created(response, expected_status: int = 201) -> Dict[str, Any]:
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {response.text}"
    )
    return response.json()["data"]


def _ok(response) -> Dict[str, Any]:
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    return response.json()["data"]


@dataclass
class CaseContext:
    """The identifiers threaded through a fully approved case."""

    household_id: str
    application_id: str
    case_id: str
    case: Dict[str, Any]
    income_source_ids: List[str] = field(default_factory=list)
    resource_item_ids: List[str] = field(default_factory=list)

    @property
    def applicant_headers(self) -> Dict[str, str]:
        return make_applicant_headers(self.household_id)


# --- Logical clock ----------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock and return the response payload."""
    return _ok(api.set_clock(to_iso8601))


def set_clock_date(api: ApiClient, day: str) -> Dict[str, Any]:
    """Move the logical clock to midnight of a ``YYYY-MM-DD`` day."""
    return set_clock(api, f"{day}T00:00:00Z")


def add_days(day: str, days: int) -> str:
    """Advance a ``YYYY-MM-DD`` day by a whole number of days."""
    parsed = date(int(day[:4]), int(day[5:7]), int(day[8:10]))
    return (parsed + timedelta(days=days)).isoformat()


def add_months(month: str, months: int) -> str:
    """Advance a ``YYYY-MM`` month by a whole number of calendar months."""
    index = (int(month[:4]) * 12 + int(month[5:7]) - 1) + months
    return "%04d-%02d" % (index // 12, index % 12 + 1)


# --- Households and applications --------------------------------------------


def create_household(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.register_household(factories.household_payload(**overrides), caseworker_headers())
    )


def read_household(api: ApiClient, household_id: str) -> Dict[str, Any]:
    return _ok(api.get_household(household_id, caseworker_headers()))


def record_prior_assistance(
    api: ApiClient, household_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _ok(
        api.record_prior_assistance(
            household_id,
            factories.prior_assistance_payload(**overrides),
            caseworker_headers(),
        )
    )


def create_application(api: ApiClient, household_id: str, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.file_application(
            factories.application_payload(household_id, **overrides), caseworker_headers()
        )
    )


def add_income_source(
    api: ApiClient,
    application_id: str,
    verification_status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Attach an income source and optionally record its verification outcome."""
    source = _created(
        api.add_income_source(
            application_id, factories.income_source_payload(**overrides), caseworker_headers()
        )
    )
    if verification_status is not None:
        source = _ok(
            api.verify_income_source(
                source["id"],
                factories.verify_income_payload(verification_status),
                caseworker_headers(),
            )
        )
    return source


def add_resource_item(api: ApiClient, application_id: str, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.add_resource_item(
            application_id, factories.resource_item_payload(**overrides), caseworker_headers()
        )
    )


def determine(
    api: ApiClient, application_id: str, determiner: str = CASEWORKER_ID
) -> Dict[str, Any]:
    return _ok(api.determine_application(application_id, caseworker_headers(determiner)))


def approve(
    api: ApiClient,
    application_id: str,
    certification_start_month: str = "2026-08",
    approver: str = SUPERVISOR_ID,
) -> Dict[str, Any]:
    """Approve a determined application; the response body is the new case."""
    return _created(
        api.approve_application(
            application_id,
            factories.approve_payload(certification_start_month),
            supervisor_headers(approver),
        )
    )


DEFAULT_INCOMES: Sequence[Dict[str, Any]] = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)


def build_determined_application(
    api: ApiClient,
    household_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    incomes: Optional[Sequence[Dict[str, Any]]] = None,
    resources: Optional[Sequence[Dict[str, Any]]] = None,
    determiner: str = CASEWORKER_ID,
) -> Dict[str, Any]:
    """Register a household, build its application record and determine it.

    Returns a dict with the household, the determined application and the
    identifiers of the attached income sources and resource items.
    """
    household = create_household(api, **(household_overrides or {}))
    application = create_application(
        api, household["id"], **(application_overrides or {})
    )
    income_ids = []
    for spec in DEFAULT_INCOMES if incomes is None else incomes:
        spec = dict(spec)
        verification_status = spec.pop("verification_status", None)
        income_ids.append(
            add_income_source(
                api, application["id"], verification_status=verification_status, **spec
            )["id"]
        )
    resource_ids = [
        add_resource_item(api, application["id"], **dict(spec))["id"]
        for spec in (resources or [])
    ]
    determined = determine(api, application["id"], determiner=determiner)
    return {
        "household": household,
        "application": determined,
        "income_source_ids": income_ids,
        "resource_item_ids": resource_ids,
    }


def build_approved_case(
    api: ApiClient,
    household_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    incomes: Optional[Sequence[Dict[str, Any]]] = None,
    resources: Optional[Sequence[Dict[str, Any]]] = None,
    certification_start_month: str = "2026-08",
    determiner: str = CASEWORKER_ID,
    approver: str = SUPERVISOR_ID,
) -> CaseContext:
    """Carry a household all the way to an approved case in PENDING_ISSUANCE."""
    built = build_determined_application(
        api,
        household_overrides=household_overrides,
        application_overrides=application_overrides,
        incomes=incomes,
        resources=resources,
        determiner=determiner,
    )
    case = approve(
        api,
        built["application"]["id"],
        certification_start_month=certification_start_month,
        approver=approver,
    )
    return CaseContext(
        household_id=built["household"]["id"],
        application_id=built["application"]["id"],
        case_id=case["id"],
        case=case,
        income_source_ids=built["income_source_ids"],
        resource_item_ids=built["resource_item_ids"],
    )


def build_active_case(
    api: ApiClient,
    benefit_months: Sequence[str] = ("2026-08",),
    **kwargs: Any,
) -> CaseContext:
    """An approved case advanced to ACTIVE by issuing one or more months."""
    context = build_approved_case(api, **kwargs)
    for month in benefit_months:
        issue_month(api, context.case_id, month)
    context.case = read_case(api, context.case_id)
    return context


# --- Case reads and issuance ------------------------------------------------


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return _ok(api.get_case(case_id, caseworker_headers()))


def search_cases(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(api.search_cases(caseworker_headers(), params=query))
    return data


def case_version(api: ApiClient, case_id: str) -> int:
    """The case version a client echoes back on the two guarded writes."""
    return read_case(api, case_id)["version"]


def read_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return _ok(api.get_application(application_id, caseworker_headers()))


def issue_month(api: ApiClient, case_id: str, benefit_month: str) -> Dict[str, Any]:
    return _created(
        api.issue_month(
            case_id, factories.issuance_payload(benefit_month), caseworker_headers()
        )
    )


def issue_months(api: ApiClient, case_id: str, months: Sequence[str]) -> None:
    for month in months:
        issue_month(api, case_id, month)


def consecutive_months(first_month: str, count: int) -> List[str]:
    """``count`` consecutive months starting at ``first_month``."""
    return [add_months(first_month, offset) for offset in range(count)]


def list_time_limit_months(
    api: ApiClient, case_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_time_limit_months(case_id, caseworker_headers(), params=query)
    )
    return data


# --- Hardship extensions ----------------------------------------------------


def request_extension(api: ApiClient, case_id: str, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.request_extension(
            case_id, factories.extension_request_payload(**overrides), caseworker_headers()
        )
    )


def grant_extension(
    api: ApiClient, extension_id: str, months_granted: int, approver: str = SUPERVISOR_ID
) -> Dict[str, Any]:
    return _ok(
        api.grant_extension(
            extension_id,
            factories.grant_extension_payload(months_granted),
            supervisor_headers(approver),
        )
    )


def revoke_extension(
    api: ApiClient, extension_id: str, approver: str = SUPERVISOR_ID, **overrides: Any
) -> Dict[str, Any]:
    return _ok(
        api.revoke_extension(
            extension_id,
            factories.revoke_extension_payload(**overrides),
            supervisor_headers(approver),
        )
    )


def build_granted_extension(
    api: ApiClient,
    case_id: str,
    first_effective_month: str,
    months: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Request and grant an extension spanning ``months`` from a first month."""
    extension = request_extension(
        api,
        case_id,
        first_effective_month=first_effective_month,
        months_requested=months,
        **overrides,
    )
    return grant_extension(api, extension["id"], months)


# --- Work assignments -------------------------------------------------------


def create_assignment(api: ApiClient, case_id: str, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.create_work_assignment(
            case_id, factories.work_assignment_payload(**overrides), work_specialist_headers()
        )
    )


def activate_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return _ok(api.activate_work_assignment(assignment_id, work_specialist_headers()))


def create_active_assignment(api: ApiClient, case_id: str, **overrides: Any) -> Dict[str, Any]:
    assignment = create_assignment(api, case_id, **overrides)
    return activate_assignment(api, assignment["id"])


def terminate_assignment(
    api: ApiClient, assignment_id: str, termination_reason: str
) -> Dict[str, Any]:
    return _ok(
        api.terminate_work_assignment(
            assignment_id,
            factories.terminate_assignment_payload(termination_reason),
            work_specialist_headers(),
        )
    )


def read_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return _ok(api.get_work_assignment(assignment_id, caseworker_headers()))


def list_assignments(api: ApiClient, case_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_work_assignments(case_id, caseworker_headers(), params=query)
    )
    return data


# --- Participation reports --------------------------------------------------


def file_report(api: ApiClient, assignment_id: str, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.file_participation_report(
            assignment_id,
            factories.participation_report_payload(**overrides),
            work_specialist_headers(),
        )
    )


def verify_report(api: ApiClient, report_id: str, verified_hours: int) -> Dict[str, Any]:
    return _ok(
        api.verify_participation_report(
            report_id,
            factories.verify_report_payload(verified_hours),
            work_specialist_headers(),
        )
    )


def reject_report(api: ApiClient, report_id: str, **overrides: Any) -> Dict[str, Any]:
    return _ok(
        api.reject_participation_report(
            report_id, factories.reject_report_payload(**overrides), work_specialist_headers()
        )
    )


def credit_hours(
    api: ApiClient,
    assignment_id: str,
    report_month: str,
    reported_hours: int,
    verified_hours: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a report for a month and verify it in one step."""
    report = file_report(
        api,
        assignment_id,
        report_month=report_month,
        reported_hours=reported_hours,
        **overrides,
    )
    return verify_report(
        api, report["id"], reported_hours if verified_hours is None else verified_hours
    )


def list_reports(api: ApiClient, assignment_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_participation_reports(assignment_id, caseworker_headers(), params=query)
    )
    return data


# --- Compliance episodes ----------------------------------------------------


def open_episode(
    api: ApiClient,
    case_id: str,
    expected_case_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Refer a noncompliance episode, reading the case version when omitted."""
    version = (
        case_version(api, case_id) if expected_case_version is None else expected_case_version
    )
    return _created(
        api.create_compliance_episode(
            factories.compliance_episode_payload(case_id, version, **overrides),
            work_specialist_headers(),
        )
    )


def read_episode(api: ApiClient, episode_id: str) -> Dict[str, Any]:
    return _ok(api.get_compliance_episode(episode_id, caseworker_headers()))


def start_conciliation(api: ApiClient, episode_id: str) -> Dict[str, Any]:
    return _ok(api.start_conciliation(episode_id, work_specialist_headers()))


def impose_sanction(
    api: ApiClient, episode_id: str, approver: str = SUPERVISOR_ID
) -> Dict[str, Any]:
    return _ok(api.impose_sanction(episode_id, supervisor_headers(approver)))


def begin_cure(api: ApiClient, episode_id: str, **overrides: Any) -> Dict[str, Any]:
    return _ok(
        api.begin_cure(
            episode_id, factories.begin_cure_payload(**overrides), work_specialist_headers()
        )
    )


def resolve_compliant(api: ApiClient, episode_id: str) -> Dict[str, Any]:
    return _ok(api.resolve_compliant(episode_id, work_specialist_headers()))


def grant_good_cause(
    api: ApiClient, episode_id: str, approver: str = SUPERVISOR_ID, **overrides: Any
) -> Dict[str, Any]:
    return _ok(
        api.grant_good_cause(
            episode_id, factories.good_cause_payload(**overrides), supervisor_headers(approver)
        )
    )


def advance_clock_to_deadline(api: ApiClient, episode: Dict[str, Any]) -> str:
    """Move the logical clock onto an episode's conciliation deadline day."""
    deadline = episode["conciliation_deadline_date"]
    set_clock_date(api, deadline)
    return deadline


def sanction_episode(
    api: ApiClient, case_id: str, approver: str = SUPERVISOR_ID, **overrides: Any
) -> Dict[str, Any]:
    """Refer, conciliate, wait out the deadline and impose one sanction level."""
    episode = open_episode(api, case_id, **overrides)
    conciliating = start_conciliation(api, episode["id"])
    advance_clock_to_deadline(api, conciliating)
    return impose_sanction(api, episode["id"], approver=approver)


def escalate_episode(
    api: ApiClient, episode_id: str, approver: str = SUPERVISOR_ID
) -> Dict[str, Any]:
    """Run one cure-then-fail cycle on a sanctioned episode, raising its level."""
    begin_cure(api, episode_id)
    return impose_sanction(api, episode_id, approver=approver)


# --- Supportive service authorizations --------------------------------------


def request_authorization(
    api: ApiClient,
    case_id: str,
    work_assignment_id: str,
    expected_case_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Request supportive funding, reading the case version when omitted."""
    version = (
        case_version(api, case_id) if expected_case_version is None else expected_case_version
    )
    return _created(
        api.create_supportive_authorization(
            factories.supportive_authorization_payload(
                case_id, work_assignment_id, version, **overrides
            ),
            work_specialist_headers(),
        )
    )


def authorize(api: ApiClient, authorization_id: str) -> Dict[str, Any]:
    return _ok(api.authorize_supportive(authorization_id, work_specialist_headers()))


def void_authorization(api: ApiClient, authorization_id: str, **overrides: Any) -> Dict[str, Any]:
    return _ok(
        api.void_supportive(
            authorization_id, factories.void_payload(**overrides), work_specialist_headers()
        )
    )


def release_hold(api: ApiClient, authorization_id: str) -> Dict[str, Any]:
    return _ok(api.release_supportive_hold(authorization_id, work_specialist_headers()))


def read_authorization(api: ApiClient, authorization_id: str) -> Dict[str, Any]:
    return _ok(api.get_supportive_authorization(authorization_id, caseworker_headers()))


def build_authorized_service(
    api: ApiClient, case_id: str, work_assignment_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Request and authorize supportive funding in one step."""
    authorization = request_authorization(api, case_id, work_assignment_id, **overrides)
    return authorize(api, authorization["id"])


# --- Overpayments -----------------------------------------------------------


def draft_overpayment(api: ApiClient, case_id: str, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.draft_overpayment(
            factories.overpayment_payload(case_id, **overrides), fiscal_officer_headers()
        )
    )


def establish_overpayment(
    api: ApiClient, overpayment_id: str, establisher: str = FISCAL_OFFICER_ID
) -> Dict[str, Any]:
    return _ok(api.establish_overpayment(overpayment_id, fiscal_officer_headers(establisher)))


def read_overpayment(api: ApiClient, overpayment_id: str) -> Dict[str, Any]:
    return _ok(api.get_overpayment(overpayment_id, fiscal_officer_headers()))


def overpayment_version(api: ApiClient, overpayment_id: str) -> int:
    return read_overpayment(api, overpayment_id)["version"]


def post_recovery(
    api: ApiClient,
    overpayment_id: str,
    expected_overpayment_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Post a ledger entry, reading the claim version when omitted."""
    version = (
        overpayment_version(api, overpayment_id)
        if expected_overpayment_version is None
        else expected_overpayment_version
    )
    return _created(
        api.post_recovery_transaction(
            overpayment_id,
            factories.recovery_transaction_payload(version, **overrides),
            fiscal_officer_headers(),
        )
    )


def list_recoveries(api: ApiClient, overpayment_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_recovery_transactions(overpayment_id, fiscal_officer_headers(), params=query)
    )
    return data


def list_case_overpayments(api: ApiClient, case_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_case_overpayments(case_id, fiscal_officer_headers(), params=query)
    )
    return data


def build_established_overpayment(
    api: ApiClient,
    case_id: str,
    establisher: str = FISCAL_OFFICER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft and establish a claim in one step."""
    claim = draft_overpayment(api, case_id, **overrides)
    return establish_overpayment(api, claim["id"], establisher=establisher)


def refer_fraud(api: ApiClient, overpayment_id: str, **overrides: Any) -> Dict[str, Any]:
    return _ok(
        api.refer_fraud(
            overpayment_id,
            factories.fraud_referral_payload(**overrides),
            fraud_investigator_headers(),
        )
    )


def record_fraud_disposition(
    api: ApiClient, overpayment_id: str, disposition: str
) -> Dict[str, Any]:
    return _ok(
        api.record_fraud_disposition(
            overpayment_id,
            factories.fraud_disposition_payload(disposition),
            fraud_investigator_headers(),
        )
    )


def write_off(
    api: ApiClient, overpayment_id: str, actor: str = FISCAL_OFFICER_ID, **overrides: Any
) -> Dict[str, Any]:
    return _ok(
        api.write_off_overpayment(
            overpayment_id, factories.write_off_payload(**overrides), fiscal_officer_headers(actor)
        )
    )


# --- Federal reporting periods ----------------------------------------------


def open_period(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return _created(
        api.open_reporting_period(
            factories.reporting_period_payload(**overrides), analyst_headers()
        )
    )


def calculate_period(
    api: ApiClient, period_id: str, calculator: str = ANALYST_ID
) -> Dict[str, Any]:
    return _ok(api.calculate_reporting_period(period_id, analyst_headers(calculator)))


def certify_period(api: ApiClient, period_id: str, certifier: str) -> Dict[str, Any]:
    return _ok(api.certify_reporting_period(period_id, analyst_headers(certifier)))


def read_period(api: ApiClient, period_id: str) -> Dict[str, Any]:
    return _ok(api.get_reporting_period(period_id, analyst_headers()))


def build_calculated_period(
    api: ApiClient, calculator: str = ANALYST_ID, **overrides: Any
) -> Dict[str, Any]:
    """Open a quarter and run its calculation in one step."""
    period = open_period(api, **overrides)
    return calculate_period(api, period["id"], calculator=calculator)


# --- Diversion --------------------------------------------------------------


def offer_diversion(
    api: ApiClient, application_id: str, approver: str = SUPERVISOR_ID
) -> Dict[str, Any]:
    return _created(
        api.offer_diversion(application_id, {}, supervisor_headers(approver))
    )


def accept_diversion(api: ApiClient, grant_id: str, household_id: str) -> Dict[str, Any]:
    return _ok(api.accept_diversion(grant_id, make_applicant_headers(household_id)))


def decline_diversion(
    api: ApiClient, grant_id: str, household_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _ok(
        api.decline_diversion(
            grant_id,
            make_applicant_headers(household_id),
            factories.decline_diversion_payload(**overrides),
        )
    )


# --- Listing readers --------------------------------------------------------


def list_extensions(api: ApiClient, case_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_extensions(case_id, caseworker_headers(), params=query)
    )
    return data


def read_extension(api: ApiClient, case_id: str, extension_id: str) -> Dict[str, Any]:
    """Read one extension out of its case's extension listing."""
    rows = [row for row in list_extensions(api, case_id) if row["id"] == extension_id]
    assert len(rows) == 1, f"expected extension {extension_id} in the listing of {case_id}"
    return rows[0]


def read_report(api: ApiClient, assignment_id: str, report_id: str) -> Dict[str, Any]:
    """Read one participation report out of its assignment's listing."""
    rows = [row for row in list_reports(api, assignment_id) if row["id"] == report_id]
    assert len(rows) == 1, f"expected report {report_id} in the listing of {assignment_id}"
    return rows[0]


def list_diversion_grants(
    api: ApiClient, application_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_diversion_grants(application_id, caseworker_headers(), params=query)
    )
    return data


def read_diversion_grant(
    api: ApiClient, application_id: str, grant_id: str
) -> Dict[str, Any]:
    rows = [row for row in list_diversion_grants(api, application_id) if row["id"] == grant_id]
    assert len(rows) == 1, f"expected grant {grant_id} in the listing of {application_id}"
    return rows[0]


def search_episodes(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.search_compliance_episodes(caseworker_headers(), params=query)
    )
    return data


def search_authorizations(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.search_supportive_authorizations(caseworker_headers(), params=query)
    )
    return data
