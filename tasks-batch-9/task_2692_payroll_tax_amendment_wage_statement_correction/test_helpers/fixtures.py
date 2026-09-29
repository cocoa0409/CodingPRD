"""Composite scenario builders.

The server restarts with an empty database before every test, so each builder
walks the whole preamble through declared endpoints only: it sets the logical
clock, registers the employer, the agency and the employees, posts the evidence
rows, opens the case, and then advances whichever dimensions the caller needs.

Each builder returns a plain dict of the rows it created so a test can read ids
and captured versions without repeating the walk. Every builder accepts
``**overrides`` on the payloads it is most likely to vary.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CANON_CLOCK
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    OFFICER_HEADERS,
    PREPARER_HEADERS,
    USER_AUDITOR,
    USER_OWNER_ELI,
    make_auditor_headers,
    make_employee_headers,
    make_officer_headers,
    make_preparer_headers,
)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock and return the setter's response payload."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN_HEADERS))


def make_employer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_employer(f.employer_payload(**overrides), ADMIN_HEADERS))


def make_federal_agency(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_tax_agency(f.federal_agency_payload(**overrides), ADMIN_HEADERS)
    )


def make_state_agency(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_tax_agency(f.state_agency_payload(**overrides), ADMIN_HEADERS)
    )


def make_employee(api: ApiClient, employer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_employee(f.employee_payload(employer_id, **overrides), ANALYST_HEADERS)
    )


def make_register_line(
    api: ApiClient, employer_id: str, employee_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_register_line(
            f.register_line_payload(employer_id, employee_id, agency_id, **overrides),
            ANALYST_HEADERS,
        )
    )


def make_deposit_record(
    api: ApiClient, employer_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_deposit_record(
            f.deposit_record_payload(employer_id, agency_id, **overrides), ANALYST_HEADERS
        )
    )


def make_filed_return(
    api: ApiClient, employer_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_filed_return(
            f.filed_return_payload(employer_id, agency_id, **overrides), PREPARER_HEADERS
        )
    )


def make_correction_case(
    api: ApiClient, employer_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_correction_case(
            f.correction_case_payload(employer_id, agency_id, **overrides), ANALYST_HEADERS
        )
    )


def read_case(api: ApiClient, case_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_correction_case(case_id, headers or PREPARER_HEADERS))


def case_version(api: ApiClient, case_id: str) -> int:
    return read_case(api, case_id)["version"]


def case_discrepancies(api: ApiClient, case_id: str) -> List[Dict[str, Any]]:
    """Every discrepancy on the case, in emission_index ascending order."""
    body = api.list_discrepancies({"correction_case_id": case_id, "limit": 100}, ANALYST_HEADERS)
    rows = get_success_data(body)
    return sorted(rows, key=lambda row: row["emission_index"])


def discrepancies_by_detected_category(api: ApiClient, case_id: str) -> Dict[str, Dict[str, Any]]:
    """Index the case's discrepancies by the category detection assigned at emission."""
    return {row["detected_category"]: row for row in case_discrepancies(api, case_id)}


# ---------------------------------------------------------------------------
# Tier 1/2 — the federal 2025 Q1 scenario, built up one dimension at a time
# ---------------------------------------------------------------------------
def federal_scenario(
    api: ApiClient,
    clock: str = CANON_CLOCK,
    with_deposit: bool = True,
    employer_overrides: Optional[Dict[str, Any]] = None,
    agency_overrides: Optional[Dict[str, Any]] = None,
    deposit_overrides: Optional[Dict[str, Any]] = None,
    filed_return_overrides: Optional[Dict[str, Any]] = None,
    register_totals: Any = ((3000000, 450000), (2000000, 300000)),
) -> Dict[str, Any]:
    """Employer, federal agency, two employees, the register, the filed return,
    one cleared deposit and an open case — reconciliation has not run yet."""
    set_clock(api, clock)
    employer = make_employer(api, **(employer_overrides or {}))
    agency = make_federal_agency(api, **(agency_overrides or {}))
    employees = [
        make_employee(api, employer["id"], full_name="Dana Reed", national_id_last4="4821"),
        make_employee(api, employer["id"], full_name="Lee Park", national_id_last4="7130"),
    ]
    register_lines = []
    for employee, (wage, withheld) in zip(employees, register_totals):
        register_lines.append(
            make_register_line(
                api,
                employer["id"],
                employee["id"],
                agency["id"],
                taxable_wage_cents=wage,
                withheld_cents=withheld,
                work_jurisdiction_code="US",
            )
        )
    filed_return = make_filed_return(
        api, employer["id"], agency["id"], **(filed_return_overrides or {})
    )
    deposit = None
    if with_deposit:
        deposit = make_deposit_record(
            api, employer["id"], agency["id"], **(deposit_overrides or {})
        )
    case = make_correction_case(api, employer["id"], agency["id"])
    return {
        "employer": employer,
        "agency": agency,
        "employees": employees,
        "employee": employees[0],
        "register_lines": register_lines,
        "filed_return": filed_return,
        "deposit": deposit,
        "case": case,
        "case_id": case["id"],
        "employer_id": employer["id"],
        "agency_id": agency["id"],
    }


def federal_reconciled(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The federal scenario with reconciliation run once."""
    ctx = federal_scenario(api, **kwargs)
    ctx["reconcile_result"] = get_success_data(
        api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS)
    )
    ctx["discrepancies"] = discrepancies_by_detected_category(api, ctx["case_id"])
    return ctx


def categorize_all(
    api: ApiClient,
    discrepancies: Dict[str, Dict[str, Any]],
    root_causes: Optional[Dict[str, str]] = None,
    skip: Any = (),
) -> None:
    """Confirm each emitted discrepancy under its detected category."""
    defaults = {
        "TAXABLE_WAGE": "RATE_TABLE_STALE",
        "WITHHOLDING": "RATE_TABLE_STALE",
        "JURISDICTION_ASSIGNMENT": "JURISDICTION_MAPPING_ERROR",
        "DEPOSIT_SHORTFALL": "DEPOSIT_SCHEDULING_ERROR",
    }
    defaults.update(root_causes or {})
    for category, row in discrepancies.items():
        if category in skip:
            continue
        get_success_data(
            api.categorize_discrepancy(
                row["id"], f.categorize_payload(category, defaults[category]), ANALYST_HEADERS
            )
        )


def federal_categorized(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Reconciled federal scenario with all three discrepancies categorised."""
    ctx = federal_reconciled(api, **kwargs)
    categorize_all(api, ctx["discrepancies"])
    return ctx


def open_amendment(
    api: ApiClient,
    case_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a draft amendment against the case's currently observed version."""
    version = case_version(api, case_id)
    return get_success_data(
        api.create_amended_return(
            f.amended_return_payload(case_id, version, **overrides), headers or PREPARER_HEADERS
        )
    )


def federal_draft_amendment(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    ctx = federal_categorized(api, **kwargs)
    ctx["amended_return"] = open_amendment(api, ctx["case_id"])
    ctx["amended_return_id"] = ctx["amended_return"]["id"]
    return ctx


def federal_prepared_amendment(
    api: ApiClient, preparer_user_id: str = "u_prep_alex", **kwargs: Any
) -> Dict[str, Any]:
    ctx = federal_draft_amendment(api, **kwargs)
    ctx["preparer_user_id"] = preparer_user_id
    ctx["amended_return"] = get_success_data(
        api.prepare_amended_return(
            ctx["amended_return_id"], {}, make_preparer_headers(preparer_user_id)
        )
    )
    return ctx


def federal_signed_amendment(
    api: ApiClient, signer_user_id: str = "u_sign_bo", **kwargs: Any
) -> Dict[str, Any]:
    ctx = federal_prepared_amendment(api, **kwargs)
    ctx["signer_user_id"] = signer_user_id
    ctx["amended_return"] = get_success_data(
        api.sign_amended_return(ctx["amended_return_id"], {}, make_officer_headers(signer_user_id))
    )
    return ctx


def federal_submitted_amendment(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    ctx = federal_signed_amendment(api, **kwargs)
    ctx["amended_return"] = get_success_data(
        api.submit_amended_return(ctx["amended_return_id"], {}, OFFICER_HEADERS)
    )
    return ctx


def federal_accepted_amendment(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Drive the amendment all the way to ACCEPTED so the five-link cascade fires.

    The remediation the cascade creates is named by nothing in the acceptance
    response, so it is looked up through the filtered remediation list.
    """
    ctx = federal_submitted_amendment(api, **kwargs)
    ctx["amended_return"] = get_success_data(
        api.record_agency_outcome(
            ctx["amended_return_id"], f.agency_outcome_payload("ACCEPTED"), OFFICER_HEADERS
        )
    )
    remediations = get_success_data(
        api.list_control_remediations({"correction_case_id": ctx["case_id"]}, AUDITOR_HEADERS)
    )
    ctx["remediations"] = remediations
    ctx["cascade_remediation"] = remediations[0] if remediations else None
    return ctx


def federal_verified_remediation(
    api: ApiClient, owner_user_id: str = USER_OWNER_ELI, verifier_user_id: str = USER_AUDITOR,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Carry the cascade-created remediation through assignment, evidence and
    an independent pass so the case becomes closeable."""
    ctx = federal_accepted_amendment(api, **kwargs)
    remediation_id = ctx["cascade_remediation"]["id"]
    get_success_data(
        api.assign_control_remediation(
            remediation_id, f.assign_payload(owner_user_id), AUDITOR_HEADERS
        )
    )
    get_success_data(
        api.submit_remediation_verification(
            remediation_id, f.submit_verification_payload(), AUDITOR_HEADERS
        )
    )
    ctx["cascade_remediation"] = get_success_data(
        api.verify_control_remediation(
            remediation_id, f.verify_payload(True), make_auditor_headers(verifier_user_id)
        )
    )
    ctx["remediation_id"] = remediation_id
    ctx["remediation_owner_user_id"] = owner_user_id
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — the jurisdiction-misassignment scenario behind the statement chain
# ---------------------------------------------------------------------------
def jurisdiction_scenario(
    api: ApiClient,
    clock: str = CANON_CLOCK,
    taxable_wage_cents: int = 1000000,
    withheld_cents: int = 150000,
    workday_ratio_bps: int = 4000,
    work_jurisdiction_code: str = "NJ",
    tax_year: int = 2025,
    quarter: int = 1,
    mailing_state_code: str = "NJ",
) -> Dict[str, Any]:
    """A register line worked outside the agency's own jurisdiction, with a filed
    return matching the register totals, so reconciliation emits exactly one
    JURISDICTION_ASSIGNMENT discrepancy and nothing else."""
    set_clock(api, clock)
    employer = make_employer(api, deposit_schedule="MONTHLY")
    agency = make_federal_agency(api)
    employee = make_employee(
        api, employer["id"], full_name="Dana Reed", national_id_last4="4821",
        mailing_state_code=mailing_state_code,
    )
    register_line = make_register_line(
        api,
        employer["id"],
        employee["id"],
        agency["id"],
        tax_year=tax_year,
        quarter=quarter,
        taxable_wage_cents=taxable_wage_cents,
        withheld_cents=withheld_cents,
        work_jurisdiction_code=work_jurisdiction_code,
        workday_ratio_bps=workday_ratio_bps,
    )
    filed_return = make_filed_return(
        api,
        employer["id"],
        agency["id"],
        tax_year=tax_year,
        quarter=quarter,
        reported_taxable_wage_cents=taxable_wage_cents,
        reported_withheld_cents=withheld_cents,
    )
    case = make_correction_case(api, employer["id"], agency["id"], tax_year=tax_year, quarter=quarter)
    get_success_data(api.reconcile_case(case["id"], {}, ANALYST_HEADERS))
    discrepancies = discrepancies_by_detected_category(api, case["id"])
    categorize_all(api, discrepancies)
    return {
        "employer": employer,
        "employer_id": employer["id"],
        "agency": agency,
        "agency_id": agency["id"],
        "employee": employee,
        "employee_id": employee["id"],
        "register_line": register_line,
        "filed_return": filed_return,
        "case": case,
        "case_id": case["id"],
        "discrepancies": discrepancies,
        "tax_year": tax_year,
    }


def draft_statement(
    api: ApiClient, case_id: str, employee_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_statement(f.statement_payload(case_id, employee_id, **overrides), PREPARER_HEADERS)
    )


def jurisdiction_drafted_statement(
    api: ApiClient, delivery_channel: str = "MAIL", **kwargs: Any
) -> Dict[str, Any]:
    ctx = jurisdiction_scenario(api, **kwargs)
    ctx["statement"] = draft_statement(
        api,
        ctx["case_id"],
        ctx["employee_id"],
        tax_year=ctx["tax_year"],
        delivery_channel=delivery_channel,
    )
    ctx["statement_id"] = ctx["statement"]["id"]
    return ctx


def jurisdiction_issued_statement(
    api: ApiClient, delivery_channel: str = "MAIL", **kwargs: Any
) -> Dict[str, Any]:
    ctx = jurisdiction_drafted_statement(api, delivery_channel=delivery_channel, **kwargs)
    ctx["statement"] = get_success_data(
        api.issue_statement(ctx["statement_id"], {}, PREPARER_HEADERS)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — agency notices and the abatement argument
# ---------------------------------------------------------------------------
def notice_scenario(
    api: ApiClient,
    clock: str = CANON_CLOCK,
    correction_case_id: Optional[str] = None,
    employer_id: Optional[str] = None,
    agency_id: Optional[str] = None,
    **notice_overrides: Any,
) -> Dict[str, Any]:
    """A received notice, either standalone or attached to an existing case."""
    if employer_id is None or agency_id is None:
        set_clock(api, clock)
        employer = make_employer(api)
        agency = make_federal_agency(api)
        employer_id, agency_id = employer["id"], agency["id"]
    else:
        employer = agency = None
    if correction_case_id is not None:
        notice_overrides.setdefault("correction_case_id", correction_case_id)
    notice = get_success_data(
        api.create_agency_notice(
            f.agency_notice_payload(employer_id, agency_id, **notice_overrides), OFFICER_HEADERS
        )
    )
    return {
        "employer": employer,
        "employer_id": employer_id,
        "agency": agency,
        "agency_id": agency_id,
        "notice": notice,
        "notice_id": notice["id"],
    }


def responded_notice(
    api: ApiClient,
    abatement_grounds: Optional[str] = "FIRST_TIME",
    requested_penalty_waiver_cents: Optional[int] = 200000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Draft the response with its abatement argument, then transmit it."""
    ctx = notice_scenario(api, **kwargs)
    draft = f.draft_response_payload()
    if abatement_grounds is not None:
        draft["abatement_grounds"] = abatement_grounds
    if requested_penalty_waiver_cents is not None:
        draft["requested_penalty_waiver_cents"] = requested_penalty_waiver_cents
    ctx["notice"] = get_success_data(
        api.draft_notice_response(ctx["notice_id"], draft, OFFICER_HEADERS)
    )
    ctx["notice"] = get_success_data(api.respond_to_notice(ctx["notice_id"], {}, OFFICER_HEADERS))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — wage repayment recovery
# ---------------------------------------------------------------------------
def proposed_repayment(
    api: ApiClient, case_id: str, employee_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_wage_repayment(
            f.wage_repayment_payload(case_id, employee_id, **overrides), ANALYST_HEADERS
        )
    )


def agreed_repayment(
    api: ApiClient, case_id: str, employee_id: str, installment_count: int = 4, **overrides: Any
) -> Dict[str, Any]:
    repayment = proposed_repayment(api, case_id, employee_id, **overrides)
    return get_success_data(
        api.agree_wage_repayment(
            repayment["id"], f.agree_payload(installment_count), make_employee_headers(employee_id)
        )
    )
