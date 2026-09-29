"""
Composite setup builders.

Every function here drives real HTTP calls to bring the system into a named
state, and every one uses the lenient setup validator so a setup failure is
reported as a setup failure rather than as a test assertion failure.

The layering is deliberate:

* single-step creators and transitions (`create_*`, `open_plan_year`, ...)
* the flexible scenario core, `build_claim_scenario`
* named lifecycle shortcuts (`setup_submitted_claim`, `setup_accepted_claim`,
  `setup_settled_batch`, `setup_locked_plan_year_for_true_up`, ...)
* accumulation / threshold targeting helpers (`setup_acp_population`,
  `setup_exhausted_qslp_space`, ...)

Tests import these by name instead of re-inventing chains inline.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    DEFAULT_CLOCK_UTC,
    HCE_PRIOR_COMPENSATION_CENTS,
    STANDARD_CERTIFIED_PAYMENT_CENTS,
    STANDARD_PERIOD_COMPENSATION_CENTS,
    STANDARD_PERIOD_DEFERRAL_CENTS,
    payroll_period_window,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    PAYROLL_HEADERS,
    RECORDKEEPER_HEADERS,
    make_admin_headers,
    make_employee_headers,
)

Resource = Dict[str, Any]

# Amendment path from creation to full effectiveness, current state first.
_AMENDMENT_CHAIN = ["DRAFTED", "ADOPTED", "NOTICE_SENT", "EFFECTIVE"]


# ---------------------------------------------------------------------------
# Tier 1 — single-step creators and transitions
# ---------------------------------------------------------------------------


def set_clock(client: ApiClient, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Move the logical clock and return the instant it now reads."""
    response = client.set_clock(
        f.clock_payload(to_iso8601), headers or ADMIN_HEADERS
    )
    data = get_success_data(response)
    return data["current_utc"]


def create_plan_year(client: ApiClient, **overrides: Any) -> Resource:
    """Create a DRAFT plan year."""
    response = client.create_plan_year(f.plan_year_payload(**overrides), ADMIN_HEADERS)
    return get_success_data(response)


def set_plan_year_status(client: ApiClient, plan_year_id: str, to_status: str) -> Resource:
    """Drive one plan-year status transition."""
    response = client.set_plan_year_status(
        plan_year_id, f.plan_year_status_payload(to_status), ADMIN_HEADERS
    )
    return get_success_data(response)


def setup_open_plan_year(client: ApiClient, **overrides: Any) -> Resource:
    """Create a plan year and move it DRAFT to OPEN."""
    plan_year = create_plan_year(client, **overrides)
    return set_plan_year_status(client, plan_year["id"], "OPEN")


def lock_plan_year(client: ApiClient, plan_year_id: str) -> Resource:
    """Move an open plan year to LOCKED."""
    return set_plan_year_status(client, plan_year_id, "LOCKED")


def create_amendment(client: ApiClient, plan_year_id: str, **overrides: Any) -> Resource:
    """Create a DRAFTED plan amendment."""
    response = client.create_plan_amendment(
        f.plan_amendment_payload(plan_year_id, **overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


def refresh_amendment(client: ApiClient, amendment_id: str) -> Resource:
    """Re-read a plan amendment, picking up its current status and version."""
    return get_success_data(client.get_plan_amendment(amendment_id, ADMIN_HEADERS))


def advance_amendment_to(client: ApiClient, amendment_id: str, target_status: str) -> Resource:
    """
    Walk an amendment forward one step at a time up to `target_status`.

    The walk resumes from the amendment's *current* status, because the PRD only
    admits the single-step transitions `DRAFTED` to `ADOPTED` to `NOTICE_SENT`
    to `EFFECTIVE`; re-issuing a step the amendment has already taken is a state
    the PRD rejects with `ERR_AMENDMENT_STATE_INVALID`.
    """
    amendment = refresh_amendment(client, amendment_id)
    start = _AMENDMENT_CHAIN.index(amendment["status"])
    stop = _AMENDMENT_CHAIN.index(target_status)
    for step in _AMENDMENT_CHAIN[start + 1 : stop + 1]:
        response = client.set_amendment_status(
            amendment_id, f.amendment_status_payload(step), ADMIN_HEADERS
        )
        amendment = get_success_data(response)
    return amendment


def setup_amendment_at(
    client: ApiClient, plan_year_id: str, status: str = "EFFECTIVE", **overrides: Any
) -> Resource:
    """Create an amendment and park it at the requested status."""
    amendment = create_amendment(client, plan_year_id, **overrides)
    if status == "DRAFTED":
        return amendment
    return advance_amendment_to(client, amendment["id"], status)


def setup_effective_amendment(client: ApiClient, plan_year_id: str, **overrides: Any) -> Resource:
    """Create an amendment and drive it all the way to EFFECTIVE."""
    return setup_amendment_at(client, plan_year_id, "EFFECTIVE", **overrides)


def create_employee(client: ApiClient, **overrides: Any) -> Resource:
    """Create an ACTIVE employee."""
    response = client.create_employee(f.employee_payload(**overrides), ADMIN_HEADERS)
    return get_success_data(response)


def refresh_employee(client: ApiClient, employee_id: str) -> Resource:
    """Re-read an employee, picking up its current version and accumulators."""
    return get_success_data(client.get_employee(employee_id, ADMIN_HEADERS))


def refresh_plan_year(client: ApiClient, plan_year_id: str) -> Resource:
    """Re-read a plan year, picking up its current version and rollups."""
    return get_success_data(client.get_plan_year(plan_year_id, ADMIN_HEADERS))


def refresh_certification(client: ApiClient, certification_id: str) -> Resource:
    """Re-read a certification claim as the benefits administrator."""
    return get_success_data(client.get_loan_certification(certification_id, ADMIN_HEADERS))


def refresh_funding_batch(client: ApiClient, funding_batch_id: str) -> Resource:
    """Re-read a funding batch."""
    return get_success_data(client.get_funding_batch(funding_batch_id, PAYROLL_HEADERS))


def refresh_allocation(client: ApiClient, allocation_id: str) -> Resource:
    """Re-read a match allocation."""
    return get_success_data(client.get_match_allocation(allocation_id, ADMIN_HEADERS))


def create_payroll_period(client: ApiClient, plan_year_id: str, period_number: int = 3, **overrides: Any) -> Resource:
    """Create one OPEN payroll period of a plan year."""
    response = client.create_payroll_period(
        f.payroll_period_payload(plan_year_id, period_number, **overrides), PAYROLL_HEADERS
    )
    return get_success_data(response)


def set_payroll_period_status(client: ApiClient, payroll_period_id: str, to_status: str) -> Resource:
    """Drive one payroll-period status transition."""
    response = client.set_payroll_period_status(
        payroll_period_id, f.payroll_period_status_payload(to_status), PAYROLL_HEADERS
    )
    return get_success_data(response)


def close_payroll_period(client: ApiClient, payroll_period_id: str) -> Resource:
    """Move a payroll period OPEN to CLOSED."""
    return set_payroll_period_status(client, payroll_period_id, "CLOSED")


def post_contribution_record(
    client: ApiClient,
    employee_id: str,
    payroll_period_id: str,
    eligible_compensation_cents: int = STANDARD_PERIOD_COMPENSATION_CENTS,
    elective_deferral_cents: int = STANDARD_PERIOD_DEFERRAL_CENTS,
    **overrides: Any,
) -> Resource:
    """Post one payroll line into an open period."""
    response = client.create_contribution_record(
        f.contribution_record_payload(
            employee_id,
            payroll_period_id,
            eligible_compensation_cents,
            elective_deferral_cents,
            **overrides,
        ),
        PAYROLL_HEADERS,
    )
    return get_success_data(response)


def create_loan_account(client: ApiClient, employee: Resource, **overrides: Any) -> Resource:
    """Register an UNVERIFIED loan account owned by the given employee."""
    response = client.create_loan_account(
        f.loan_account_payload(employee["id"], **overrides),
        make_employee_headers(employee["id"]),
    )
    return get_success_data(response)


def verify_loan_account(client: ApiClient, loan_account_id: str, to_status: str = "VERIFIED") -> Resource:
    """Move a loan account out of UNVERIFIED."""
    response = client.set_loan_account_verification(
        loan_account_id, f.loan_verification_payload(to_status), ADMIN_HEADERS
    )
    return get_success_data(response)


def setup_verified_loan_account(client: ApiClient, employee: Resource, **overrides: Any) -> Resource:
    """Register a loan account and verify it."""
    account = create_loan_account(client, employee, **overrides)
    return verify_loan_account(client, account["id"])


def open_certification(client: ApiClient, employee: Resource, plan_year_id: str, **overrides: Any) -> Resource:
    """
    Open a DRAFT certification claim.

    The employee is re-read first so the create carries the employee's current
    version, which the concurrency guard on this endpoint compares against.
    """
    current = refresh_employee(client, employee["id"])
    payload = f.loan_certification_payload(
        employee["id"], plan_year_id, current["version"], **overrides
    )
    response = client.create_loan_certification(payload, make_employee_headers(employee["id"]))
    return get_success_data(response)


def add_certification_line(
    client: ApiClient,
    certification_id: str,
    employee: Resource,
    loan_account_id: str,
    **overrides: Any,
) -> Resource:
    """Attach one certified payment line to a draft claim."""
    response = client.add_certification_line(
        certification_id,
        f.certification_line_payload(loan_account_id, **overrides),
        make_employee_headers(employee["id"]),
    )
    return get_success_data(response)


def submit_certification(client: ApiClient, certification_id: str, employee: Resource) -> Resource:
    """Submit a draft claim for review."""
    response = client.submit_certification(
        certification_id, None, make_employee_headers(employee["id"])
    )
    return get_success_data(response)


def create_funding_batch(client: ApiClient, plan_year_id: str, payroll_period_id: str) -> Resource:
    """Open a PENDING funding batch for one payroll period."""
    response = client.create_funding_batch(
        f.funding_batch_payload(plan_year_id, payroll_period_id), PAYROLL_HEADERS
    )
    return get_success_data(response)


def accept_certification(
    client: ApiClient, certification_id: str, user_id: Optional[str] = None
) -> Resource:
    """Accept a submitted claim, recording the deciding administrator."""
    headers = make_admin_headers(user_id) if user_id else ADMIN_HEADERS
    response = client.decide_certification(certification_id, f.decision_payload("ACCEPT"), headers)
    return get_success_data(response)


def return_certification(
    client: ApiClient, certification_id: str, reason: str = "servicer statement illegible"
) -> Resource:
    """Return a submitted claim to the participant for rework."""
    response = client.decide_certification(
        certification_id, f.decision_payload("RETURN", reason), ADMIN_HEADERS
    )
    return get_success_data(response)


def place_audit_hold(
    client: ApiClient, certification_id: str, reason: str = "certification documentation sampling"
) -> Resource:
    """Place an accepted claim on audit hold."""
    response = client.audit_hold_certification(
        certification_id, f.audit_hold_payload(reason), AUDITOR_HEADERS
    )
    return get_success_data(response)


def release_audit_hold(
    client: ApiClient,
    certification_id: str,
    resolution: str = "VOID",
    note: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Resource:
    """Release an audit hold, either clearing the claim or voiding it."""
    from .test_users import make_auditor_headers

    headers = make_auditor_headers(user_id) if user_id else AUDITOR_HEADERS
    response = client.audit_release_certification(
        certification_id, f.audit_release_payload(resolution, note), headers
    )
    return get_success_data(response)


def transmit_batch(client: ApiClient, funding_batch_id: str) -> Resource:
    """Transmit a pending batch to the recordkeeper."""
    response = client.transmit_funding_batch(funding_batch_id, None, PAYROLL_HEADERS)
    return get_success_data(response)


def settle_batch(client: ApiClient, funding_batch_id: str) -> Resource:
    """Record a successful settlement on a transmitted batch."""
    response = client.settle_funding_batch(
        funding_batch_id, f.settlement_payload("SETTLED"), RECORDKEEPER_HEADERS
    )
    return get_success_data(response)


def reject_batch(client: ApiClient, funding_batch_id: str, rejection_code: str = "RK-101") -> Resource:
    """Record a rejection on a transmitted batch."""
    response = client.settle_funding_batch(
        funding_batch_id,
        f.settlement_payload("REJECTED", rejection_code),
        RECORDKEEPER_HEADERS,
    )
    return get_success_data(response)


def terminate_employee(
    client: ApiClient, employee_id: str, effective_date: str = DEFAULT_CLOCK_UTC
) -> Resource:
    """File a termination event, which evaluates vesting and forfeitures."""
    response = client.create_employment_event(
        employee_id, f.employment_event_payload("TERMINATE", effective_date), ADMIN_HEADERS
    )
    return get_success_data(response)


def rehire_employee(client: ApiClient, employee_id: str, effective_date: str) -> Resource:
    """File a rehire event for a terminated employee."""
    response = client.create_employment_event(
        employee_id, f.employment_event_payload("REHIRE", effective_date), ADMIN_HEADERS
    )
    return get_success_data(response)


def file_leave_event(
    client: ApiClient, employee_id: str, start_date: str, end_date: str, **overrides: Any
) -> Resource:
    """File one leave interval for an employee."""
    response = client.create_leave_event(
        f.leave_event_payload(employee_id, start_date, end_date, **overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


def open_nondiscrimination_test(client: ApiClient, plan_year_id: str, **overrides: Any) -> Resource:
    """Open a PENDING ACP test over a plan year."""
    response = client.create_nondiscrimination_test(
        f.nondiscrimination_test_payload(plan_year_id, **overrides), AUDITOR_HEADERS
    )
    return get_success_data(response)


def compute_nondiscrimination_test(client: ApiClient, test_id: str) -> Resource:
    """Compute an ACP test that stands in PENDING or STALE."""
    response = client.compute_nondiscrimination_test(test_id, None, AUDITOR_HEADERS)
    return get_success_data(response)


def correct_nondiscrimination_test(
    client: ApiClient, test_id: str, correction_method: str = "CORRECTIVE_FORFEITURE"
) -> Resource:
    """Correct a failed ACP test."""
    response = client.correct_nondiscrimination_test(
        test_id, f.test_correction_payload(correction_method), AUDITOR_HEADERS
    )
    return get_success_data(response)


def run_true_up(client: ApiClient, plan_year_id: str) -> Resource:
    """Run the annual true-up over a locked plan year."""
    response = client.run_true_up(plan_year_id, None, ADMIN_HEADERS)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Read helpers over listings
# ---------------------------------------------------------------------------


def list_data(response: Any) -> List[Resource]:
    """Return the element list of a successful listing response."""
    body = response.json()
    return body["data"]


def list_meta(response: Any) -> Dict[str, Any]:
    """Return the meta block of a successful listing response."""
    body = response.json()
    return body["meta"]


def allocations_of_certification(client: ApiClient, certification_id: str) -> List[Resource]:
    """List every match allocation attached to a certification."""
    response = client.list_match_allocations(
        ADMIN_HEADERS, {"certification_id": certification_id}
    )
    get_success_data(response)
    return list_data(response)


def allocations_of_plan_year(client: ApiClient, plan_year_id: str) -> List[Resource]:
    """List every match allocation of a plan year."""
    response = client.list_match_allocations(ADMIN_HEADERS, {"plan_year_id": plan_year_id})
    get_success_data(response)
    return list_data(response)


def forfeitures_of_employee(client: ApiClient, employee_id: str) -> List[Resource]:
    """List every forfeiture record written for an employee."""
    response = client.list_forfeiture_records(ADMIN_HEADERS, {"employee_id": employee_id})
    get_success_data(response)
    return list_data(response)


def corrections_of_plan_year(client: ApiClient, plan_year_id: str) -> List[Resource]:
    """List every correction adjustment of a plan year."""
    response = client.list_correction_adjustments(ADMIN_HEADERS, {"plan_year_id": plan_year_id})
    get_success_data(response)
    return list_data(response)


# ---------------------------------------------------------------------------
# Tier 2/3 — the flexible scenario core
# ---------------------------------------------------------------------------


def build_claim_scenario(
    client: ApiClient,
    *,
    plan_year_overrides: Optional[Dict[str, Any]] = None,
    amendment_status: Optional[str] = "EFFECTIVE",
    amendment_overrides: Optional[Dict[str, Any]] = None,
    employee_overrides: Optional[Dict[str, Any]] = None,
    period_numbers: Sequence[int] = (3,),
    compensation_cents: int = STANDARD_PERIOD_COMPENSATION_CENTS,
    deferral_cents: int = STANDARD_PERIOD_DEFERRAL_CENTS,
    post_contributions: bool = True,
    loan_status: str = "VERIFIED",
    open_claim: bool = True,
    certification_overrides: Optional[Dict[str, Any]] = None,
    line_specs: Optional[Sequence[Dict[str, Any]]] = None,
    submit: bool = False,
    create_batches: bool = False,
    batch_period_numbers: Optional[Sequence[int]] = None,
    accept: bool = False,
    accepting_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Bring the whole benefit chain up to a chosen point and return every id.

    The returned mapping always carries `plan_year`, `employee` and
    `employee_headers`, plus whichever of `amendment`, `periods`,
    `contribution_records`, `loan_account`, `certification`, `lines` and
    `batches` the requested depth produced.
    """
    plan_year = setup_open_plan_year(client, **(plan_year_overrides or {}))
    scenario: Dict[str, Any] = {"plan_year": plan_year, "plan_year_id": plan_year["id"]}

    if amendment_status is not None:
        scenario["amendment"] = setup_amendment_at(
            client, plan_year["id"], amendment_status, **(amendment_overrides or {})
        )

    employee = create_employee(client, **(employee_overrides or {}))
    scenario["employee"] = employee
    scenario["employee_id"] = employee["id"]
    scenario["employee_headers"] = make_employee_headers(employee["id"])

    periods: List[Resource] = []
    records: List[Resource] = []
    for number in period_numbers:
        period = create_payroll_period(client, plan_year["id"], number)
        periods.append(period)
        if post_contributions:
            records.append(
                post_contribution_record(
                    client, employee["id"], period["id"], compensation_cents, deferral_cents
                )
            )
    scenario["periods"] = periods
    scenario["contribution_records"] = records
    if periods:
        scenario["payroll_period"] = periods[0]
        scenario["payroll_period_id"] = periods[0]["id"]
    if records:
        scenario["contribution_record"] = records[0]

    if loan_status is not None:
        account = create_loan_account(client, employee)
        if loan_status != "UNVERIFIED":
            account = verify_loan_account(client, account["id"], loan_status)
        scenario["loan_account"] = account
        scenario["loan_account_id"] = account["id"]

    if open_claim:
        certification = open_certification(
            client, employee, plan_year["id"], **(certification_overrides or {})
        )
        scenario["certification"] = certification
        scenario["certification_id"] = certification["id"]

        specs = (
            list(line_specs)
            if line_specs is not None
            else [{"amount_cents": STANDARD_CERTIFIED_PAYMENT_CENTS}]
        )
        lines: List[Resource] = []
        for spec in specs:
            lines.append(
                add_certification_line(
                    client,
                    certification["id"],
                    employee,
                    scenario["loan_account_id"],
                    **spec,
                )
            )
        scenario["lines"] = lines

    if create_batches:
        wanted = (
            list(batch_period_numbers)
            if batch_period_numbers is not None
            else list(period_numbers)
        )
        batches: List[Resource] = []
        for period in periods:
            if period["period_number"] in wanted:
                batches.append(create_funding_batch(client, plan_year["id"], period["id"]))
        scenario["batches"] = batches
        if batches:
            scenario["funding_batch"] = batches[0]
            scenario["funding_batch_id"] = batches[0]["id"]

    if submit or accept:
        scenario["certification"] = submit_certification(
            client, scenario["certification_id"], employee
        )

    if accept:
        scenario["certification"] = accept_certification(
            client, scenario["certification_id"], accepting_user_id
        )
        scenario["allocations"] = allocations_of_certification(
            client, scenario["certification_id"]
        )
        if scenario["allocations"]:
            scenario["allocation"] = scenario["allocations"][0]
            scenario["allocation_id"] = scenario["allocations"][0]["id"]

    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — named lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_draft_claim(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Open plan year, effective amendment, funded payroll and a DRAFT claim."""
    return build_claim_scenario(client, **overrides)


def setup_claim_without_lines(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A DRAFT claim carrying no certified lines at all."""
    overrides.setdefault("line_specs", [])
    return build_claim_scenario(client, **overrides)


def setup_submitted_claim(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A claim standing in SUBMITTED, awaiting a decision."""
    overrides["submit"] = True
    return build_claim_scenario(client, **overrides)


def setup_accepted_claim(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A claim accepted while a pending batch exists, so allocations schedule."""
    overrides["create_batches"] = True
    overrides["accept"] = True
    return build_claim_scenario(client, **overrides)


def setup_accepted_claim_without_batch(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A claim accepted with no pending batch, so allocations stay UNFUNDED."""
    overrides["create_batches"] = False
    overrides["accept"] = True
    return build_claim_scenario(client, **overrides)


def setup_transmitted_batch(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An accepted claim whose batch is CLOSED-period and TRANSMITTED."""
    scenario = setup_accepted_claim(client, **overrides)
    close_payroll_period(client, scenario["payroll_period_id"])
    scenario["funding_batch"] = transmit_batch(client, scenario["funding_batch_id"])
    return scenario


def setup_settled_batch(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An accepted claim whose batch has been transmitted and settled."""
    scenario = setup_transmitted_batch(client, **overrides)
    scenario["funding_batch"] = settle_batch(client, scenario["funding_batch_id"])
    return scenario


def setup_rejected_batch(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An accepted claim whose batch was transmitted and then rejected."""
    scenario = setup_transmitted_batch(client, **overrides)
    scenario["funding_batch"] = reject_batch(client, scenario["funding_batch_id"])
    return scenario


def setup_audit_hold_claim(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An accepted claim parked in AUDIT_HOLD."""
    hold_reason = overrides.pop("hold_reason", "certification documentation sampling")
    scenario = setup_accepted_claim(client, **overrides)
    scenario["certification"] = place_audit_hold(
        client, scenario["certification_id"], hold_reason
    )
    return scenario


def setup_voided_claim(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An accepted claim taken through audit hold to VOIDED."""
    note = overrides.pop("void_note", "no supporting statement")
    voiding_user_id = overrides.pop("voiding_user_id", None)
    scenario = setup_audit_hold_claim(client, **overrides)
    scenario["certification"] = release_audit_hold(
        client, scenario["certification_id"], "VOID", note, voiding_user_id
    )
    return scenario


def setup_returned_claim(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A submitted claim that the administrator returned for rework."""
    reason = overrides.pop("return_reason", "servicer statement illegible")
    scenario = setup_submitted_claim(client, **overrides)
    scenario["certification"] = return_certification(
        client, scenario["certification_id"], reason
    )
    return scenario


def setup_locked_plan_year_for_true_up(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An accepted mirror match whose plan year has then been locked."""
    scenario = setup_accepted_claim(client, **overrides)
    scenario["plan_year"] = lock_plan_year(client, scenario["plan_year_id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------


def setup_acp_population(
    client: ApiClient,
    *,
    nhce_deferrals: Sequence[int] = (),
    hce_deferrals: Sequence[int] = (),
    compensation_cents: int = STANDARD_PERIOD_COMPENSATION_CENTS,
    nhce_prior_compensation_cents: int = 6_000_000,
    hce_prior_compensation_cents: int = HCE_PRIOR_COMPENSATION_CENTS,
    plan_year_overrides: Optional[Dict[str, Any]] = None,
    period_number: int = 3,
) -> Dict[str, Any]:
    """
    Build an open plan year with a chosen HCE / NHCE deferral population.

    One payroll line is posted per requested deferral, all into the same
    period, so each participant's ratio is the period's match over its counted
    compensation.
    """
    plan_year = setup_open_plan_year(client, **(plan_year_overrides or {}))
    period = create_payroll_period(client, plan_year["id"], period_number)

    nhce: List[Dict[str, Any]] = []
    for index, deferral in enumerate(nhce_deferrals, start=1):
        employee = create_employee(
            client,
            external_id=f"E-NHCE-{index}",
            prior_year_compensation_cents=nhce_prior_compensation_cents,
        )
        record = post_contribution_record(
            client, employee["id"], period["id"], compensation_cents, deferral
        )
        nhce.append({"employee": employee, "contribution_record": record})

    hce: List[Dict[str, Any]] = []
    for index, deferral in enumerate(hce_deferrals, start=1):
        employee = create_employee(
            client,
            external_id=f"E-HCE-{index}",
            prior_year_compensation_cents=hce_prior_compensation_cents,
        )
        record = post_contribution_record(
            client, employee["id"], period["id"], compensation_cents, deferral
        )
        hce.append({"employee": employee, "contribution_record": record})

    return {
        "plan_year": plan_year,
        "plan_year_id": plan_year["id"],
        "payroll_period": period,
        "payroll_period_id": period["id"],
        "nhce": nhce,
        "hce": hce,
    }


def setup_computed_test(
    client: ApiClient,
    *,
    nhce_deferrals: Sequence[int] = (),
    hce_deferrals: Sequence[int] = (),
    test_overrides: Optional[Dict[str, Any]] = None,
    **population_overrides: Any,
) -> Dict[str, Any]:
    """Build an ACP population, open a test over it, and compute the test."""
    scenario = setup_acp_population(
        client,
        nhce_deferrals=nhce_deferrals,
        hce_deferrals=hce_deferrals,
        **population_overrides,
    )
    test = open_nondiscrimination_test(
        client, scenario["plan_year_id"], **(test_overrides or {})
    )
    scenario["test"] = compute_nondiscrimination_test(client, test["id"])
    scenario["test_id"] = test["id"]
    return scenario


def setup_multi_period_deferrals(
    client: ApiClient,
    *,
    period_specs: Sequence[Dict[str, Any]],
    employee_overrides: Optional[Dict[str, Any]] = None,
    plan_year_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Post one payroll line per spec into successive periods of one plan year.

    Each spec carries `period_number`, `eligible_compensation_cents` and
    `elective_deferral_cents`, which lets a test drive the compensation-cap
    accumulator or the shared ladder across periods.
    """
    plan_year = setup_open_plan_year(client, **(plan_year_overrides or {}))
    employee = create_employee(client, **(employee_overrides or {}))
    periods: List[Resource] = []
    records: List[Resource] = []
    for spec in period_specs:
        number = spec["period_number"]
        window_overrides = {
            key: spec[key]
            for key in ("start_date", "end_date", "pay_date")
            if key in spec
        }
        period = create_payroll_period(client, plan_year["id"], number, **window_overrides)
        periods.append(period)
        records.append(
            post_contribution_record(
                client,
                employee["id"],
                period["id"],
                spec["eligible_compensation_cents"],
                spec["elective_deferral_cents"],
            )
        )
    return {
        "plan_year": plan_year,
        "plan_year_id": plan_year["id"],
        "employee": employee,
        "employee_id": employee["id"],
        "employee_headers": make_employee_headers(employee["id"]),
        "periods": periods,
        "contribution_records": records,
    }


def setup_exhausted_qslp_space(
    client: ApiClient, **overrides: Any
) -> Dict[str, Any]:
    """
    Drive an employee's remaining statutory space to exactly zero.

    A single payroll line whose deferral equals the plan year's annual deferral
    limit leaves nothing for certified loan payments.
    """
    overrides.setdefault("compensation_cents", 10_000_000)
    overrides.setdefault("deferral_cents", 2_300_000)
    overrides.setdefault("open_claim", True)
    overrides.setdefault("line_specs", [])
    return build_claim_scenario(client, **overrides)


def full_year_period_specs(
    count: int,
    compensation_cents: int = STANDARD_PERIOD_COMPENSATION_CENTS,
    deferral_cents: int = STANDARD_PERIOD_DEFERRAL_CENTS,
    first_period: int = 1,
) -> List[Dict[str, Any]]:
    """Build `count` consecutive monthly period specs with identical amounts."""
    specs: List[Dict[str, Any]] = []
    for offset in range(count):
        number = first_period + offset
        window = payroll_period_window(number)
        specs.append(
            {
                "period_number": number,
                "eligible_compensation_cents": compensation_cents,
                "elective_deferral_cents": deferral_cents,
                **window,
            }
        )
    return specs
