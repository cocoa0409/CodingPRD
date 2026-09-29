"""Pytest fixtures and composite state builders.

The server is restarted with an empty store before every test, so every builder
below constructs the state it needs from scratch using only the API's declared
endpoints. Builders validate each response as they go, so a test that reaches
its trigger knows its arrangement succeeded.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories
from .api_client import ApiClient
from .constants import BASELINE_VALUATION_YEARS
from .test_users import (
    ARBITRATOR_HEADERS,
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_ACTUARY_HEADERS,
    PLAN_ACTUARY_SECONDARY_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    PLAN_TRUSTEE_SECONDARY_HEADERS,
    make_employer_representative_headers,
)
from .types import (
    ArbitrationStatus,
    AssumptionRuling,
    PaymentScheduleSource,
    ReviewDecision,
)


# ─── Client and identities ────────────────────────────────────────────────────

@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return FUND_ADMINISTRATOR_HEADERS


@pytest.fixture
def actuary_headers() -> Dict[str, str]:
    return PLAN_ACTUARY_HEADERS


@pytest.fixture
def other_actuary_headers() -> Dict[str, str]:
    return PLAN_ACTUARY_SECONDARY_HEADERS


@pytest.fixture
def trustee_headers() -> Dict[str, str]:
    return PLAN_TRUSTEE_HEADERS


@pytest.fixture
def other_trustee_headers() -> Dict[str, str]:
    return PLAN_TRUSTEE_SECONDARY_HEADERS


@pytest.fixture
def arbitrator_headers() -> Dict[str, str]:
    return ARBITRATOR_HEADERS


# ─── Primitive builders ───────────────────────────────────────────────────────

def register_plan(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_plan(factories.plan_payload(**overrides), FUND_ADMINISTRATOR_HEADERS)
    return validate_success(response, 201)


def register_controlled_group(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_controlled_group(
        factories.controlled_group_payload(**overrides), FUND_ADMINISTRATOR_HEADERS
    )
    return validate_success(response, 201)


def register_employer(
    api: ApiClient, plan_id: str, controlled_group_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_employer(
        factories.employer_payload(plan_id, controlled_group_id, **overrides),
        FUND_ADMINISTRATOR_HEADERS,
    )
    return validate_success(response, 201)


def file_valuation(api: ApiClient, plan_id: str, plan_year: int, **overrides: Any) -> Dict[str, Any]:
    response = api.create_plan_year_valuation(
        factories.valuation_payload(plan_id, plan_year, **overrides), PLAN_ACTUARY_HEADERS
    )
    return validate_success(response, 201)


def certify_valuation(
    api: ApiClient, valuation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api.certify_plan_year_valuation(valuation_id, headers or PLAN_ACTUARY_HEADERS)
    return validate_success(response, 200)


def file_certified_valuations(
    api: ApiClient,
    plan_id: str,
    years: Sequence[int] = BASELINE_VALUATION_YEARS,
    per_year: Optional[Dict[int, Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[int, Dict[str, Any]]:
    """File and certify one valuation per plan year, keyed by plan year."""
    valuations: Dict[int, Dict[str, Any]] = {}
    for year in years:
        year_overrides = dict(overrides)
        if per_year and year in per_year:
            year_overrides.update(per_year[year])
        valuations[year] = file_valuation(api, plan_id, year, **year_overrides)
    return valuations


def current_employer_version(api: ApiClient, employer_id: str) -> int:
    employer = validate_success(api.get_employer(employer_id, FUND_ADMINISTRATOR_HEADERS), 200)
    return employer["version"]


def file_contribution_record(
    api: ApiClient,
    employer_id: str,
    plan_year_start: int,
    plan_year_end: int,
    expected_employer_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_employer_version
        if expected_employer_version is not None
        else current_employer_version(api, employer_id)
    )
    response = api.create_contribution_record(
        factories.contribution_record_payload(
            employer_id, plan_year_start, plan_year_end, version, **overrides
        ),
        FUND_ADMINISTRATOR_HEADERS,
    )
    return validate_success(response, 201)


def file_contribution_history(
    api: ApiClient, employer_id: str, entries: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """File a sequence of contribution records, re-reading the employer version each time.

    Each entry supplies `plan_year_start`, `plan_year_end` and any of the
    monetary fields.
    """
    records: List[Dict[str, Any]] = []
    for entry in entries:
        payload = dict(entry)
        start = payload.pop("plan_year_start")
        end = payload.pop("plan_year_end")
        records.append(file_contribution_record(api, employer_id, start, end, **payload))
    return records


def report_withdrawal_event(
    api: ApiClient,
    employer_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    response = api.create_withdrawal_event(
        factories.withdrawal_event_payload(employer_id, **overrides),
        headers or FUND_ADMINISTRATOR_HEADERS,
    )
    return validate_success(response, 201)


def determine_withdrawal_event(
    api: ApiClient, withdrawal_event_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api.determine_withdrawal_event(
        withdrawal_event_id, headers or PLAN_ACTUARY_HEADERS
    )
    return validate_success(response, 200)


def create_assessment(
    api: ApiClient, withdrawal_event_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api.create_liability_assessment(
        factories.liability_assessment_payload(withdrawal_event_id),
        headers or PLAN_ACTUARY_HEADERS,
    )
    return validate_success(response, 201)


def issue_assessment(
    api: ApiClient, assessment_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api.issue_liability_assessment(assessment_id, headers or PLAN_TRUSTEE_HEADERS)
    return validate_success(response, 200)


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    response = api.set_clock(factories.clock_payload(to_iso8601), FUND_ADMINISTRATOR_HEADERS)
    return validate_success(response, 200)


def run_sweep(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    response = api.run_collection_sweep(
        factories.collection_sweep_payload(plan_id), FUND_ADMINISTRATOR_HEADERS
    )
    return validate_success(response, 200)


# ─── Read helpers ─────────────────────────────────────────────────────────────

def get_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return validate_success(api.get_plan(plan_id, FUND_ADMINISTRATOR_HEADERS), 200)


def get_group(api: ApiClient, controlled_group_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_controlled_group(controlled_group_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def get_employer(api: ApiClient, employer_id: str) -> Dict[str, Any]:
    return validate_success(api.get_employer(employer_id, FUND_ADMINISTRATOR_HEADERS), 200)


def get_valuation(api: ApiClient, valuation_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_plan_year_valuation(valuation_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def get_record(api: ApiClient, contribution_record_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_contribution_record(contribution_record_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def get_event(api: ApiClient, withdrawal_event_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_withdrawal_event(withdrawal_event_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def get_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_liability_assessment(assessment_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def get_schedule(api: ApiClient, schedule_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_payment_schedule(schedule_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def get_installment(api: ApiClient, installment_id: str) -> Dict[str, Any]:
    return validate_success(api.get_installment(installment_id, FUND_ADMINISTRATOR_HEADERS), 200)


def get_review_request(api: ApiClient, review_request_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_review_request(review_request_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def get_arbitration(api: ApiClient, arbitration_id: str) -> Dict[str, Any]:
    return validate_success(api.get_arbitration(arbitration_id, FUND_ADMINISTRATOR_HEADERS), 200)


def get_transaction(api: ApiClient, transaction_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_asset_sale_transaction(transaction_id, FUND_ADMINISTRATOR_HEADERS), 200
    )


def list_all_schedules(api: ApiClient, assessment_id: str) -> List[Dict[str, Any]]:
    response = api.list_payment_schedules(
        FUND_ADMINISTRATOR_HEADERS,
        {"liability_assessment_id": assessment_id, "limit": 100},
    )
    data, _meta = validate_paginated(response)
    return data


def latest_schedule(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    """The highest generation minted for the assessment."""
    schedules = list_all_schedules(api, assessment_id)
    assert schedules, f"no payment schedule exists for assessment {assessment_id}"
    return max(schedules, key=lambda item: item["generation_seq"])


def list_all_installments(api: ApiClient, schedule_id: str) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    offset = 0
    while True:
        response = api.list_installments(
            FUND_ADMINISTRATOR_HEADERS,
            {"payment_schedule_id": schedule_id, "limit": 100, "offset": offset},
        )
        data, meta = validate_paginated(response)
        collected.extend(data)
        if not meta.get("has_more"):
            break
        offset += 100
    return collected


def installment_at(api: ApiClient, schedule_id: str, sequence_number: int) -> Dict[str, Any]:
    for item in list_all_installments(api, schedule_id):
        if item["sequence_number"] == sequence_number:
            return item
    raise AssertionError(f"schedule {schedule_id} has no instalment {sequence_number}")


# ─── Money movement helpers ───────────────────────────────────────────────────

def pay_installment(
    api: ApiClient,
    installment: Dict[str, Any],
    employer_id: str,
    payment_amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    amount = (
        payment_amount_cents
        if payment_amount_cents is not None
        else installment["amount_due_cents"]
    )
    response = api.pay_installment(
        installment["id"],
        factories.payment_payload(amount),
        make_employer_representative_headers(employer_id),
    )
    return validate_success(response, 200)


def cure_schedule(
    api: ApiClient, schedule_id: str, employer_id: str, payment_amount_cents: int
) -> Dict[str, Any]:
    response = api.cure_payment_schedule(
        schedule_id,
        factories.payment_payload(payment_amount_cents),
        make_employer_representative_headers(employer_id),
    )
    return validate_success(response, 200)


def issue_default_notice(api: ApiClient, schedule_id: str) -> Dict[str, Any]:
    return validate_success(api.issue_default_notice(schedule_id, PLAN_TRUSTEE_HEADERS), 200)


def accelerate_schedule(api: ApiClient, schedule_id: str) -> Dict[str, Any]:
    return validate_success(
        api.accelerate_payment_schedule(schedule_id, PLAN_TRUSTEE_HEADERS), 200
    )


def regenerate_schedule(
    api: ApiClient,
    assessment_id: str,
    expected_assessment_version: int,
    source: str = PaymentScheduleSource.REVIEW_DECISION.value,
    override_net_assessed_cents: Optional[int] = None,
) -> Dict[str, Any]:
    response = api.create_payment_schedule(
        factories.payment_schedule_payload(
            assessment_id,
            expected_assessment_version,
            source=source,
            override_net_assessed_cents=override_net_assessed_cents,
        ),
        PLAN_ACTUARY_HEADERS,
    )
    return validate_success(response, 201)


# ─── Dispute helpers ──────────────────────────────────────────────────────────

def file_review_request(
    api: ApiClient, assessment_id: str, employer_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_review_request(
        factories.review_request_payload(assessment_id, **overrides),
        make_employer_representative_headers(employer_id),
    )
    return validate_success(response, 201)


def decide_review_request(
    api: ApiClient,
    review_request_id: str,
    decision: str = ReviewDecision.AFFIRMED.value,
    assumption_ruling: str = AssumptionRuling.NOT_RAISED.value,
    recomputed_net_assessed_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api.decide_review_request(
        review_request_id,
        factories.review_decision_payload(
            decision, assumption_ruling, recomputed_net_assessed_cents
        ),
        headers or PLAN_TRUSTEE_HEADERS,
    )
    return validate_success(response, 200)


def initiate_arbitration(
    api: ApiClient, assessment_id: str, review_request_id: str, employer_id: str
) -> Dict[str, Any]:
    response = api.create_arbitration(
        factories.arbitration_payload(assessment_id, review_request_id),
        make_employer_representative_headers(employer_id),
    )
    return validate_success(response, 201)


def advance_arbitration(api: ApiClient, arbitration_id: str, to_status: str) -> Dict[str, Any]:
    response = api.advance_arbitration(
        arbitration_id, factories.arbitration_advance_payload(to_status), ARBITRATOR_HEADERS
    )
    return validate_success(response, 200)


def issue_award(
    api: ApiClient,
    arbitration_id: str,
    award_outcome: str,
    assumption_ruling: str = AssumptionRuling.NOT_RAISED.value,
    awarded_net_assessed_cents: Optional[int] = None,
) -> Dict[str, Any]:
    response = api.award_arbitration(
        arbitration_id,
        factories.arbitration_award_payload(
            award_outcome, assumption_ruling, awarded_net_assessed_cents
        ),
        ARBITRATOR_HEADERS,
    )
    return validate_success(response, 200)


def submit_asset_sale(
    api: ApiClient,
    seller_employer_id: str,
    buyer_controlled_group_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    response = api.create_asset_sale_transaction(
        factories.asset_sale_payload(seller_employer_id, buyer_controlled_group_id, **overrides),
        headers or FUND_ADMINISTRATOR_HEADERS,
    )
    return validate_success(response, 201)


def adjudicate_asset_sale(
    api: ApiClient, transaction_id: str, disposition: str
) -> Dict[str, Any]:
    response = api.adjudicate_asset_sale_transaction(
        transaction_id, factories.adjudication_payload(disposition), PLAN_TRUSTEE_HEADERS
    )
    return validate_success(response, 200)


# ─── Composite scenarios ──────────────────────────────────────────────────────

def build_registry(
    api: ApiClient,
    plan_overrides: Optional[Dict[str, Any]] = None,
    group_overrides: Optional[Dict[str, Any]] = None,
    employer_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A plan, a controlled group and one contributing employer inside both."""
    plan = register_plan(api, **(plan_overrides or {}))
    group = register_controlled_group(api, **(group_overrides or {}))
    employer = register_employer(api, plan["id"], group["id"], **(employer_overrides or {}))
    return {"plan": plan, "group": group, "employer": employer}


def build_priced_assessment(
    api: ApiClient,
    plan_overrides: Optional[Dict[str, Any]] = None,
    group_overrides: Optional[Dict[str, Any]] = None,
    employer_overrides: Optional[Dict[str, Any]] = None,
    valuation_years: Sequence[int] = BASELINE_VALUATION_YEARS,
    valuation_overrides: Optional[Dict[str, Any]] = None,
    per_year_valuation_overrides: Optional[Dict[int, Dict[str, Any]]] = None,
    contribution_entries: Optional[Sequence[Dict[str, Any]]] = None,
    withdrawal_overrides: Optional[Dict[str, Any]] = None,
    determine: bool = True,
    price: bool = True,
    issue: bool = False,
) -> Dict[str, Any]:
    """Registry, certified valuation history, contribution history and a withdrawal.

    Stops at whichever stage the caller asks for: a determined event, a priced
    draft assessment, or an issued notice and demand with its first schedule
    generation and instalments.
    """
    scenario = build_registry(api, plan_overrides, group_overrides, employer_overrides)
    scenario["valuations"] = file_certified_valuations(
        api,
        scenario["plan"]["id"],
        valuation_years,
        per_year=per_year_valuation_overrides,
        **(valuation_overrides or {}),
    )
    entries = (
        list(contribution_entries)
        if contribution_entries is not None
        else [{"plan_year_start": 2021, "plan_year_end": 2025}]
    )
    scenario["records"] = file_contribution_history(api, scenario["employer"]["id"], entries)
    scenario["event"] = report_withdrawal_event(
        api, scenario["employer"]["id"], **(withdrawal_overrides or {})
    )
    if determine:
        scenario["event"] = determine_withdrawal_event(api, scenario["event"]["id"])
    if price:
        scenario["assessment"] = create_assessment(api, scenario["event"]["id"])
    if issue:
        scenario["assessment"] = issue_assessment(api, scenario["assessment"]["id"])
        scenario["schedule"] = latest_schedule(api, scenario["assessment"]["id"])
        scenario["installments"] = list_all_installments(api, scenario["schedule"]["id"])
    return scenario


def build_issued_assessment(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The canonical issued notice and demand with its first schedule generation."""
    kwargs.setdefault("issue", True)
    return build_priced_assessment(api, **kwargs)


def build_reviewed_assessment(
    api: ApiClient,
    filed_at: str = "2026-09-01T00:00:00Z",
    decided_at: Optional[str] = "2026-10-01T00:00:00Z",
    decision: Optional[str] = ReviewDecision.AFFIRMED.value,
    assumption_ruling: str = AssumptionRuling.NOT_RAISED.value,
    recomputed_net_assessed_cents: Optional[int] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An issued assessment with a filed request for review, optionally decided."""
    scenario = build_issued_assessment(api, **kwargs)
    set_clock(api, filed_at)
    scenario["review_request"] = file_review_request(
        api,
        scenario["assessment"]["id"],
        scenario["employer"]["id"],
        **(review_overrides or {}),
    )
    if decision is not None:
        if decided_at:
            set_clock(api, decided_at)
        scenario["review_request"] = decide_review_request(
            api,
            scenario["review_request"]["id"],
            decision,
            assumption_ruling,
            recomputed_net_assessed_cents,
            headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
        )
    scenario["assessment"] = get_assessment(api, scenario["assessment"]["id"])
    return scenario


def build_arbitration(
    api: ApiClient,
    initiated_at: str = "2026-10-15T00:00:00Z",
    advance_to_hearing: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A decided review request carried into arbitration."""
    scenario = build_reviewed_assessment(api, **kwargs)
    set_clock(api, initiated_at)
    scenario["arbitration"] = initiate_arbitration(
        api,
        scenario["assessment"]["id"],
        scenario["review_request"]["id"],
        scenario["employer"]["id"],
    )
    if advance_to_hearing:
        scenario["arbitration"] = advance_arbitration(
            api, scenario["arbitration"]["id"], ArbitrationStatus.HEARING.value
        )
    return scenario


def build_delinquent_schedule(
    api: ApiClient, swept_at: str = "2027-02-28T00:00:00Z", **kwargs: Any
) -> Dict[str, Any]:
    """An issued assessment swept far enough forward to make two instalments delinquent."""
    scenario = build_issued_assessment(api, **kwargs)
    set_clock(api, swept_at)
    scenario["sweep"] = run_sweep(api, scenario["plan"]["id"])
    scenario["schedule"] = get_schedule(api, scenario["schedule"]["id"])
    scenario["installments"] = list_all_installments(api, scenario["schedule"]["id"])
    scenario["assessment"] = get_assessment(api, scenario["assessment"]["id"])
    scenario["employer"] = get_employer(api, scenario["employer"]["id"])
    return scenario


def build_noticed_schedule(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A delinquent schedule carried through the written notice of default."""
    scenario = build_delinquent_schedule(api, **kwargs)
    scenario["schedule"] = issue_default_notice(api, scenario["schedule"]["id"])
    scenario["assessment"] = get_assessment(api, scenario["assessment"]["id"])
    return scenario


def build_asset_sale(
    api: ApiClient,
    contribution_entries: Optional[Sequence[Dict[str, Any]]] = None,
    sale_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    employer_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A seller employer with a contribution history and a submitted asset sale."""
    scenario = build_registry(api, plan_overrides, None, employer_overrides)
    scenario["buyer_group"] = register_controlled_group(api)
    entries = (
        list(contribution_entries)
        if contribution_entries is not None
        else [
            {"plan_year_start": year, "plan_year_end": year}
            for year in (2023, 2024, 2025)
        ]
    )
    scenario["records"] = file_contribution_history(api, scenario["employer"]["id"], entries)
    scenario["transaction"] = submit_asset_sale(
        api,
        scenario["employer"]["id"],
        scenario["buyer_group"]["id"],
        **(sale_overrides or {}),
    )
    return scenario


__all__ = [name for name in dir() if not name.startswith("_")]
