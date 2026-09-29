"""Composite scenario builders for the CMBS Special Servicing API.

The harness restarts the API server before every test, so every scenario is
built from scratch through the PRD's own endpoints. Each builder returns a plain
dict of the ids and rows it created so tests can assert against them.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import SpecialServicingClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    ASSET_MANAGER,
    ASSET_MANAGER_2,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    PLATFORM_ADMIN,
    TRUSTEE,
    make_borrower_headers,
    make_controlling_class_representative_headers,
)
from .types import Json


# --------------------------------------------------------------------------
# Tier 0 — logical clock
# --------------------------------------------------------------------------
def set_clock(api: SpecialServicingClient, current_utc: str) -> Json:
    """Move the logical clock and return the admin endpoint's payload."""
    return get_success_data(api.set_clock(current_utc, PLATFORM_ADMIN))


# --------------------------------------------------------------------------
# Tier 1 — trusts and loans
# --------------------------------------------------------------------------
def create_trust(api: SpecialServicingClient, **overrides) -> Json:
    """Board one trust as the platform administrator."""
    return get_success_data(
        api.create_trust(f.trust_payload(**overrides), PLATFORM_ADMIN)
    )


def create_small_controlling_class_trust(
    api: SpecialServicingClient, **overrides
) -> Json:
    """Board a trust whose control threshold sits at exactly 2,000,000.00."""
    return get_success_data(
        api.create_trust(
            f.small_controlling_class_trust_payload(**overrides), PLATFORM_ADMIN
        )
    )


def create_loan(api: SpecialServicingClient, trust_id: str, **overrides) -> Json:
    """Board one loan into a trust as the master servicer."""
    return get_success_data(
        api.create_loan(f.loan_payload(trust_id, **overrides), MASTER_SERVICER)
    )


def create_mid_size_loan(
    api: SpecialServicingClient, trust_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_loan(f.mid_size_loan_payload(trust_id, **overrides), MASTER_SERVICER)
    )


def read_loan(api: SpecialServicingClient, loan_id: str, headers=None) -> Json:
    return get_success_data(api.get_loan(loan_id, headers or ASSET_MANAGER))


def read_trust(api: SpecialServicingClient, trust_id: str, headers=None) -> Json:
    return get_success_data(api.get_trust(trust_id, headers or ASSET_MANAGER))


def loan_version(api: SpecialServicingClient, loan_id: str) -> int:
    return read_loan(api, loan_id)["version"]


def trust_version(api: SpecialServicingClient, trust_id: str) -> int:
    return read_trust(api, trust_id, TRUSTEE)["version"]


# --------------------------------------------------------------------------
# Tier 2 — servicing transfer
# --------------------------------------------------------------------------
def record_transfer_event(
    api: SpecialServicingClient, loan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_transfer_event(
            f.transfer_event_payload(loan_id, **overrides), MASTER_SERVICER
        )
    )


def record_bankruptcy_event(
    api: SpecialServicingClient, loan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_transfer_event(
            f.bankruptcy_event_payload(loan_id, **overrides), MASTER_SERVICER
        )
    )


def transfer_to_special_servicing(api: SpecialServicingClient, loan_id: str) -> Json:
    return get_success_data(
        api.set_loan_servicing_status(
            loan_id, f.status_payload("SPECIAL_SERVICING"), MASTER_SERVICER
        )
    )


def loan_in_special_servicing(
    api: SpecialServicingClient,
    trust_id: str = "",
    loan_factory=None,
    event_factory=None,
    trust_overrides: Json = None,
    loan_overrides: Json = None,
) -> Json:
    """Board a trust and a loan, record a qualifying event, and transfer.

    Returns ``{trust, loan, trust_id, loan_id}`` with the loan row read back
    after the transfer.
    """
    trust_overrides = trust_overrides or {}
    loan_overrides = loan_overrides or {}
    if trust_id:
        trust = read_trust(api, trust_id, PLATFORM_ADMIN)
    else:
        trust = create_trust(api, **trust_overrides)
    factory = loan_factory or create_loan
    loan = factory(api, trust["id"], **loan_overrides)
    (event_factory or record_transfer_event)(api, loan["id"])
    transferred = transfer_to_special_servicing(api, loan["id"])
    return {
        "trust": trust,
        "trust_id": trust["id"],
        "loan": transferred,
        "loan_id": loan["id"],
    }


# --------------------------------------------------------------------------
# Tier 3 — appraisals and appraisal reductions
# --------------------------------------------------------------------------
def order_appraisal(api: SpecialServicingClient, loan_id: str, **overrides) -> Json:
    return get_success_data(
        api.create_appraisal(f.appraisal_payload(loan_id, **overrides), ASSET_MANAGER)
    )


def receive_appraisal(
    api: SpecialServicingClient,
    appraisal_id: str,
    value_usd: float,
    as_of_date: str = DEFAULT_CLOCK,
    **overrides,
) -> Json:
    return get_success_data(
        api.set_appraisal_status(
            appraisal_id,
            f.appraisal_received_payload(value_usd, as_of_date, **overrides),
            ASSET_MANAGER,
        )
    )


def accept_appraisal(api: SpecialServicingClient, appraisal_id: str) -> Json:
    """Accept an appraisal as the second asset manager, satisfying segregation
    of duties against the ordering user."""
    return get_success_data(
        api.set_appraisal_status(
            appraisal_id, f.status_payload("ACCEPTED"), ASSET_MANAGER_2
        )
    )


def accepted_appraisal(
    api: SpecialServicingClient,
    loan_id: str,
    value_usd: float = 9000000,
    as_of_date: str = DEFAULT_CLOCK,
    ordered_on: str = DEFAULT_CLOCK,
    appraisal_type: str = "UPDATE",
    received_extra: Json = None,
    **order_overrides,
) -> Json:
    """Order, receive and accept one appraisal; returns the accepted row."""
    appraisal = order_appraisal(
        api,
        loan_id,
        appraisal_type=appraisal_type,
        ordered_on=ordered_on,
        **order_overrides,
    )
    receive_appraisal(
        api, appraisal["id"], value_usd, as_of_date, **(received_extra or {})
    )
    return accept_appraisal(api, appraisal["id"])


def provisional_reduction(api: SpecialServicingClient, loan_id: str) -> Json:
    """Read back the PROVISIONAL appraisal reduction on a loan."""
    data, _ = _paginated(
        api.list_appraisal_reductions(
            ASSET_MANAGER, {"loan_id": loan_id, "status": "PROVISIONAL"}
        )
    )
    assert data, f"expected a PROVISIONAL appraisal reduction on loan {loan_id}"
    return data[0]


def reductions_for_loan(api: SpecialServicingClient, loan_id: str) -> list:
    data, _ = _paginated(
        api.list_appraisal_reductions(ASSET_MANAGER, {"loan_id": loan_id})
    )
    return data


def make_reduction_effective(api: SpecialServicingClient, reduction_id: str) -> Json:
    return get_success_data(
        api.set_appraisal_reduction_status(
            reduction_id, f.status_payload("EFFECTIVE"), COMMITTEE_OFFICER
        )
    )


def effective_reduction(
    api: SpecialServicingClient,
    loan_id: str,
    value_usd: float,
    as_of_date: str = DEFAULT_CLOCK,
    **appraisal_overrides,
) -> Json:
    """Accept an appraisal and make its auto-created reduction EFFECTIVE."""
    accepted_appraisal(
        api, loan_id, value_usd=value_usd, as_of_date=as_of_date, **appraisal_overrides
    )
    reduction = provisional_reduction(api, loan_id)
    return make_reduction_effective(api, reduction["id"])


def _paginated(response):
    """Local pagination reader that tolerates setup-time reads."""
    body = response.json()
    assert response.status_code == 200, f"list read failed: {response.text}"
    return body["data"], body["meta"]


# --------------------------------------------------------------------------
# Tier 4 — advances
# --------------------------------------------------------------------------
def record_advance(api: SpecialServicingClient, loan_id: str, **overrides) -> Json:
    return get_success_data(
        api.create_advance(f.advance_payload(loan_id, **overrides), MASTER_SERVICER)
    )


def two_advances(api: SpecialServicingClient, loan_id: str) -> Json:
    """The pinned pair: 200,000.00 on 2026-02-01 and 150,000.00 on 2026-04-01."""
    advance_a = record_advance(
        api,
        loan_id,
        advance_type="TAX_INSURANCE_ADVANCE",
        amount_usd=200000,
        advanced_on="2026-02-01T00:00:00Z",
    )
    advance_b = record_advance(
        api,
        loan_id,
        advance_type="PROPERTY_PROTECTION_ADVANCE",
        amount_usd=150000,
        advanced_on="2026-04-01T00:00:00Z",
    )
    return {"advance_a": advance_a, "advance_b": advance_b}


# --------------------------------------------------------------------------
# Tier 5 — workout plans and alternatives
# --------------------------------------------------------------------------
def create_plan(api: SpecialServicingClient, loan_id: str, **overrides) -> Json:
    """Open a workout plan, reading the loan version the PRD requires."""
    version = loan_version(api, loan_id)
    return get_success_data(
        api.create_workout_plan(
            f.workout_plan_payload(loan_id, version, **overrides), ASSET_MANAGER
        )
    )


def add_modification_alternative(
    api: SpecialServicingClient, plan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_workout_alternative(
            f.modification_alternative_payload(plan_id, **overrides), ASSET_MANAGER
        )
    )


def add_note_sale_alternative(
    api: SpecialServicingClient, plan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_workout_alternative(
            f.note_sale_alternative_payload(plan_id, **overrides), ASSET_MANAGER
        )
    )


def add_foreclosure_alternative(
    api: SpecialServicingClient, plan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_workout_alternative(
            f.foreclosure_alternative_payload(plan_id, **overrides), ASSET_MANAGER
        )
    )


def score_plan(api: SpecialServicingClient, plan_id: str) -> Json:
    return get_success_data(
        api.set_workout_plan_status(plan_id, f.status_payload("SCORED"), ASSET_MANAGER)
    )


def recommend_plan(
    api: SpecialServicingClient, plan_id: str, alternative_id: str
) -> Json:
    return get_success_data(
        api.set_workout_plan_status(
            plan_id,
            f.status_payload("RECOMMENDED", selected_alternative_id=alternative_id),
            ASSET_MANAGER,
        )
    )


def issue_plan_consultation(
    api: SpecialServicingClient, trust_id: str, plan_id: str
) -> Json:
    return get_success_data(
        api.create_consultation(
            f.plan_consultation_payload(trust_id, plan_id), ASSET_MANAGER
        )
    )


def respond_to_consultation(
    api: SpecialServicingClient, consultation_id: str, trust_id: str, response: str
) -> Json:
    return get_success_data(
        api.respond_to_consultation(
            consultation_id,
            f.consultation_response_payload(response),
            make_controlling_class_representative_headers(trust_id),
        )
    )


def approve_plan(api: SpecialServicingClient, plan_id: str) -> Json:
    return get_success_data(
        api.set_workout_plan_status(
            plan_id, f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )


def execute_plan(api: SpecialServicingClient, plan_id: str) -> Json:
    return get_success_data(
        api.set_workout_plan_status(plan_id, f.status_payload("EXECUTED"), ASSET_MANAGER)
    )


def scored_plan(
    api: SpecialServicingClient,
    loan_id: str,
    alternative_builders=None,
    **plan_overrides,
) -> Json:
    """Open a plan, attach alternatives and score it.

    Returns ``{plan, plan_id, alternatives}`` where ``alternatives`` holds the
    rows as created, in creation order.
    """
    plan = create_plan(api, loan_id, **plan_overrides)
    builders = alternative_builders or [add_modification_alternative]
    alternatives = [builder(api, plan["id"]) for builder in builders]
    scored = score_plan(api, plan["id"])
    return {
        "plan": scored,
        "plan_id": plan["id"],
        "alternatives": alternatives,
        "alternative_ids": [alt["id"] for alt in alternatives],
    }


def consented_plan(
    api: SpecialServicingClient,
    trust_id: str,
    loan_id: str,
    alternative_builders=None,
    **plan_overrides,
) -> Json:
    """Carry a plan to CONSENT_SATISFIED through an explicit CONSENTED response."""
    built = scored_plan(
        api, loan_id, alternative_builders=alternative_builders, **plan_overrides
    )
    recommended_id = built["plan"]["recommended_alternative_id"]
    recommend_plan(api, built["plan_id"], recommended_id)
    consultation = issue_plan_consultation(api, trust_id, built["plan_id"])
    respond_to_consultation(api, consultation["id"], trust_id, "CONSENTED")
    built["consultation"] = consultation
    built["consultation_id"] = consultation["id"]
    built["selected_alternative_id"] = recommended_id
    return built


def approved_plan(
    api: SpecialServicingClient,
    trust_id: str,
    loan_id: str,
    alternative_builders=None,
    **plan_overrides,
) -> Json:
    built = consented_plan(
        api, trust_id, loan_id, alternative_builders=alternative_builders, **plan_overrides
    )
    built["plan"] = approve_plan(api, built["plan_id"])
    return built


def executed_plan(
    api: SpecialServicingClient,
    trust_id: str,
    loan_id: str,
    alternative_builders=None,
    **plan_overrides,
) -> Json:
    built = approved_plan(
        api, trust_id, loan_id, alternative_builders=alternative_builders, **plan_overrides
    )
    built["plan"] = execute_plan(api, built["plan_id"])
    return built


# --------------------------------------------------------------------------
# Tier 6 — borrower requests
# --------------------------------------------------------------------------
def submit_modification_request(
    api: SpecialServicingClient, loan_id: str, headers=None, **overrides
) -> Json:
    return get_success_data(
        api.create_borrower_request(
            f.modification_request_payload(loan_id, **overrides),
            headers or ASSET_MANAGER,
        )
    )


def submit_assumption_request(
    api: SpecialServicingClient, loan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_borrower_request(
            f.assumption_request_payload(loan_id, **overrides),
            make_borrower_headers(loan_id),
        )
    )


def submit_lease_request(
    api: SpecialServicingClient, loan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_borrower_request(
            f.lease_approval_request_payload(loan_id, **overrides),
            make_borrower_headers(loan_id),
        )
    )


def set_request_status(
    api: SpecialServicingClient, request_id: str, to_status: str, headers=None
) -> Json:
    return get_success_data(
        api.set_borrower_request_status(
            request_id, f.status_payload(to_status), headers or ASSET_MANAGER
        )
    )


def record_analysis(
    api: SpecialServicingClient, request_id: str, payload: Json = None
) -> Json:
    return get_success_data(
        api.record_borrower_request_analysis(
            request_id, payload or f.analysis_payload(), ASSET_MANAGER
        )
    )


def request_under_analysis(
    api: SpecialServicingClient, loan_id: str, submitter=None, **overrides
) -> Json:
    submitted = (submitter or submit_modification_request)(api, loan_id, **overrides)
    set_request_status(api, submitted["id"], "UNDER_ANALYSIS")
    return submitted


def recommended_request(
    api: SpecialServicingClient,
    loan_id: str,
    submitter=None,
    analysis: Json = None,
    **overrides,
) -> Json:
    submitted = request_under_analysis(api, loan_id, submitter=submitter, **overrides)
    record_analysis(api, submitted["id"], analysis)
    recommended = set_request_status(api, submitted["id"], "RECOMMENDED")
    return recommended


def consultation_pending_request(
    api: SpecialServicingClient,
    trust_id: str,
    loan_id: str,
    submitter=None,
    analysis: Json = None,
    **overrides,
) -> Json:
    """Carry a borrower request to CONSULTATION_PENDING with a CONSENTED reply."""
    request = recommended_request(
        api, loan_id, submitter=submitter, analysis=analysis, **overrides
    )
    consultation = get_success_data(
        api.create_consultation(
            f.request_consultation_payload(trust_id, request["id"]), ASSET_MANAGER
        )
    )
    respond_to_consultation(api, consultation["id"], trust_id, "CONSENTED")
    return {
        "request": request,
        "request_id": request["id"],
        "consultation": consultation,
        "consultation_id": consultation["id"],
    }


def approve_request(api: SpecialServicingClient, request_id: str) -> Json:
    return get_success_data(
        api.set_borrower_request_status(
            request_id, f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )


# --------------------------------------------------------------------------
# Tier 7 — REO, fees and distribution reports
# --------------------------------------------------------------------------
def acquire_reo(
    api: SpecialServicingClient, loan_id: str, plan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_reo_asset(
            f.reo_asset_payload(loan_id, plan_id, **overrides), ASSET_MANAGER
        )
    )


def set_reo_status(
    api: SpecialServicingClient, reo_id: str, to_status: str, headers=None, **extra
) -> Json:
    return get_success_data(
        api.set_reo_asset_status(
            reo_id, f.status_payload(to_status, **extra), headers or ASSET_MANAGER
        )
    )


def reo_under_contract(
    api: SpecialServicingClient,
    loan_id: str,
    plan_id: str,
    list_price_usd: float = 7500000,
    **overrides,
) -> Json:
    reo = acquire_reo(api, loan_id, plan_id, **overrides)
    set_reo_status(api, reo["id"], "STABILIZING")
    set_reo_status(api, reo["id"], "MARKETED", list_price_usd=list_price_usd)
    return set_reo_status(api, reo["id"], "UNDER_CONTRACT")


def accrue_special_servicing_fee(
    api: SpecialServicingClient, loan_id: str, **overrides
) -> Json:
    return get_success_data(
        api.create_fee_accrual(
            f.special_servicing_fee_payload(loan_id, **overrides), ASSET_MANAGER
        )
    )


def fees_for_loan(api: SpecialServicingClient, loan_id: str, fee_type: str = "") -> list:
    params = {"loan_id": loan_id}
    if fee_type:
        params["fee_type"] = fee_type
    data, _ = _paginated(api.list_fee_accruals(ASSET_MANAGER, params))
    return data


def create_distribution_report(
    api: SpecialServicingClient, trust_id: str, **overrides
) -> Json:
    version = trust_version(api, trust_id)
    return get_success_data(
        api.create_distribution_report(
            f.distribution_report_payload(trust_id, version, **overrides), TRUSTEE
        )
    )


def set_report_status(
    api: SpecialServicingClient, report_id: str, to_status: str, **extra
) -> Json:
    return get_success_data(
        api.set_distribution_report_status(
            report_id, f.status_payload(to_status, **extra), TRUSTEE
        )
    )
