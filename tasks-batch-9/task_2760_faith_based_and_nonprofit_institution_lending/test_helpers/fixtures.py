"""
Composite setup builders and pytest fixtures.

The harness restarts the service before every test, so each test begins against
an empty store with the clock at the PRD §2.5 startup instant. Everything here
is therefore built from scratch per test: a tiered set of builders that walk the
reference chain one workflow stage at a time, plus pytest fixtures that expose
the common stopping points.

Every setup call is validated with ``get_success_data`` so a broken precondition
fails loudly at the point it breaks instead of surfacing as a mystifying
assertion later in the test body.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import GenericApiClient, get_success_data

from .api_client import ApiClient
from .constants import CLOCK_STARTUP_UTC
from .factories import (
    REFERENCE_AUDITED_QUARTERS,
    assignment_payload,
    board_verification_payload,
    collateral_asset_payload,
    committee_decision_payload,
    committee_referral_payload,
    covenant_payload,
    draw_approval_payload,
    draw_request_payload,
    giving_period_payload,
    governance_authorization_payload,
    installment_payload,
    institution_payload,
    loan_application_payload,
    loan_payload,
    pledge_campaign_payload,
    pledge_payload,
    submit_underwriting_payload,
)
from .test_users import (
    ANALYST_1,
    COMMITTEE_1,
    CREDIT_ANALYST,
    LOAN_SERVICER,
    PLATFORM_ADMIN,
    make_committee_member_headers,
    make_credit_analyst_headers,
    make_governance_officer_headers,
    make_institution_representative_headers,
)


# ─── Chain container ──────────────────────────────────────────────────────


@dataclass
class Chain:
    """Whatever the reference chain has produced so far."""

    api: ApiClient
    institution: Optional[Dict[str, Any]] = None
    giving_periods: List[Dict[str, Any]] = field(default_factory=list)
    governance_authorization: Optional[Dict[str, Any]] = None
    collateral_asset: Optional[Dict[str, Any]] = None
    loan_application: Optional[Dict[str, Any]] = None
    loan: Optional[Dict[str, Any]] = None

    # -- convenience id accessors -----------------------------------------
    @property
    def institution_id(self) -> str:
        return self.institution["id"]

    @property
    def governance_authorization_id(self) -> str:
        return self.governance_authorization["id"]

    @property
    def collateral_asset_id(self) -> str:
        return self.collateral_asset["id"]

    @property
    def loan_application_id(self) -> str:
        return self.loan_application["id"]

    @property
    def loan_id(self) -> str:
        return self.loan["id"]

    @property
    def giving_period_ids(self) -> List[str]:
        return [period["id"] for period in self.giving_periods]

    @property
    def rep_headers(self) -> Dict[str, str]:
        """Headers for this institution's own representative (PRD §2.1)."""
        return make_institution_representative_headers(self.institution_id)

    # -- re-reads ---------------------------------------------------------
    def read_loan(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_loan(self.loan_id, LOAN_SERVICER))

    def read_application(self) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_loan_application(self.loan_application_id, CREDIT_ANALYST)
        )

    def read_asset(self) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_collateral_asset(self.collateral_asset_id, CREDIT_ANALYST)
        )

    def read_authorization(self) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_governance_authorization(
                self.governance_authorization_id, make_governance_officer_headers()
            )
        )


# ─── Tier 0: clock ────────────────────────────────────────────────────────


def reset_clock(api: ApiClient, to_iso8601: str = CLOCK_STARTUP_UTC) -> Dict[str, Any]:
    return get_success_data(api.set_clock(to_iso8601, PLATFORM_ADMIN))


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(to_iso8601, PLATFORM_ADMIN))


# ─── Tier 1: institution ──────────────────────────────────────────────────


def build_institution(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_institution(institution_payload(**overrides), PLATFORM_ADMIN), 201
    )


# ─── Tier 2: giving periods ───────────────────────────────────────────────


def build_giving_period(
    api: ApiClient,
    institution_id: str,
    spec: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    merged = dict(spec or {})
    merged.update(overrides)
    return get_success_data(
        api.create_giving_period(
            giving_period_payload(institution_id, **merged), headers or CREDIT_ANALYST
        ),
        201,
    )


def build_giving_periods(
    api: ApiClient,
    institution_id: str,
    specs: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Create the periods in ascending calendar order, oldest first."""
    return [
        build_giving_period(api, institution_id, spec, headers)
        for spec in (specs if specs is not None else REFERENCE_AUDITED_QUARTERS)
    ]


# ─── Tier 3: governance authorization ─────────────────────────────────────


def build_draft_authorization(
    api: ApiClient, institution_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_governance_authorization(
            governance_authorization_payload(institution_id, **overrides),
            make_institution_representative_headers(institution_id),
        ),
        201,
    )


def build_submitted_authorization(
    api: ApiClient, institution_id: str, **overrides: Any
) -> Dict[str, Any]:
    draft = build_draft_authorization(api, institution_id, **overrides)
    return get_success_data(
        api.submit_governance_authorization(
            draft["id"], {}, make_institution_representative_headers(institution_id)
        )
    )


def build_authorized_authorization(
    api: ApiClient, institution_id: str, **overrides: Any
) -> Dict[str, Any]:
    """
    Carry a resolution all the way to AUTHORIZED. Only valid for an institution
    whose ``requires_denominational_approval`` is false, where PRD §3.2 sends
    board verification straight to AUTHORIZED.
    """
    submitted = build_submitted_authorization(api, institution_id, **overrides)
    return get_success_data(
        api.board_verify_governance_authorization(
            submitted["id"], board_verification_payload(), make_governance_officer_headers()
        )
    )


# ─── Tier 4: collateral ───────────────────────────────────────────────────


def build_collateral_asset(
    api: ApiClient,
    institution_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_collateral_asset(
            collateral_asset_payload(institution_id, **overrides), headers or CREDIT_ANALYST
        ),
        201,
    )


def assign_asset(
    api: ApiClient,
    collateral_asset_id: str,
    loan_application_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.assign_collateral_asset(
            collateral_asset_id,
            assignment_payload(loan_application_id, **overrides),
            headers or CREDIT_ANALYST,
        )
    )


# ─── Tier 5: loan application ─────────────────────────────────────────────


def build_draft_application(
    api: ApiClient,
    institution_id: str,
    governance_authorization_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_loan_application(
            loan_application_payload(institution_id, governance_authorization_id, **overrides),
            headers or CREDIT_ANALYST,
        ),
        201,
    )


def submit_to_underwriting(
    api: ApiClient,
    loan_application_id: str,
    user_id: str = ANALYST_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_underwriting(
            loan_application_id,
            submit_underwriting_payload(**overrides),
            make_credit_analyst_headers(user_id),
        )
    )


def refer_to_committee(
    api: ApiClient,
    loan_application_id: str,
    user_id: str = ANALYST_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.committee_referral(
            loan_application_id,
            committee_referral_payload(**overrides),
            make_credit_analyst_headers(user_id),
        )
    )


def render_committee_decision(
    api: ApiClient,
    loan_application_id: str,
    decision: str = "APPROVE",
    user_id: str = COMMITTEE_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.committee_decision(
            loan_application_id,
            committee_decision_payload(decision, **overrides),
            make_committee_member_headers(user_id),
        )
    )


# ─── Tier 6: loan ─────────────────────────────────────────────────────────


def build_loan(api: ApiClient, loan_application_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_loan(loan_payload(loan_application_id, **overrides), LOAN_SERVICER), 201
    )


# ─── Tier 7: draws and covenants ──────────────────────────────────────────


def build_draw_request(api: ApiClient, loan_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_draw_request(draw_request_payload(loan_id, **overrides), LOAN_SERVICER), 201
    )


def build_approved_draw(
    api: ApiClient, loan_id: str, approved_amount_cents: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    draw = build_draw_request(api, loan_id, **overrides)
    amount = (
        approved_amount_cents
        if approved_amount_cents is not None
        else draw["requested_amount_cents"]
    )
    return get_success_data(
        api.approve_draw_request(draw["id"], draw_approval_payload(amount), LOAN_SERVICER)
    )


def build_covenant(api: ApiClient, loan_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8 and §4: writing a covenant is a ``CreditAnalyst`` act."""
    return get_success_data(
        api.create_covenant(covenant_payload(loan_id, **overrides), CREDIT_ANALYST), 201
    )


def build_pledge_campaign(api: ApiClient, institution_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_pledge_campaign(
            pledge_campaign_payload(institution_id, **overrides),
            make_institution_representative_headers(institution_id),
        ),
        201,
    )


def build_pledge(
    api: ApiClient,
    pledge_campaign_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Create a pledge, reading the campaign's current ``version`` first.

    PRD §2.8 makes ``expected_pledge_campaign_version`` a mandatory input, and every
    preceding pledge or installment has already advanced that counter, so the value
    must be re-read rather than remembered.
    """
    campaign = get_success_data(api.get_pledge_campaign(pledge_campaign_id, CREDIT_ANALYST))
    return get_success_data(
        api.create_pledge(
            pledge_payload(pledge_campaign_id, campaign["version"], **overrides),
            headers or CREDIT_ANALYST,
        ),
        201,
    )


def record_installment(
    api: ApiClient, pledge_id: str, installment_month: int, outcome: str, amount_cents: int
) -> Dict[str, Any]:
    return get_success_data(
        api.record_pledge_payment(
            pledge_id, installment_payload(installment_month, outcome, amount_cents), LOAN_SERVICER
        )
    )


def build_house_campaign(
    api: ApiClient, institution_id: str, major_missed_months: Sequence[int] = (2, 3)
) -> Dict[str, Any]:
    """
    The 'Build His House' campaign: goal 120000000, 36 months, sponsor rate 9200 bps,
    with one LEAD, one MAJOR and one GENERAL pledge each carrying a first paid
    installment, and the MAJOR donor missing the months named by the caller.
    """
    campaign = build_pledge_campaign(
        api,
        institution_id,
        campaign_name="Build His House",
        goal_cents=120000000,
        pledge_period_months=36,
        sponsor_collection_rate_bps=9200,
    )
    lead = build_pledge(
        api, campaign["id"], donor_tier="LEAD", pledged_amount_cents=60000000, installment_count=12
    )
    major = build_pledge(
        api, campaign["id"], donor_tier="MAJOR", pledged_amount_cents=40000000, installment_count=12
    )
    general = build_pledge(
        api,
        campaign["id"],
        donor_tier="GENERAL",
        pledged_amount_cents=25000000,
        installment_count=12,
    )
    record_installment(api, lead["id"], 1, "PAID", 12000000)
    record_installment(api, major["id"], 1, "PAID", 8000000)
    for month in major_missed_months:
        record_installment(api, major["id"], month, "MISSED", 0)
    record_installment(api, general["id"], 1, "PAID", 5000000)
    return {"campaign": campaign, "lead": lead, "major": major, "general": general}


# ─── Whole-chain builders ─────────────────────────────────────────────────


def chain_through_periods(
    api: ApiClient,
    institution_overrides: Optional[Dict[str, Any]] = None,
    period_specs: Optional[List[Dict[str, Any]]] = None,
) -> Chain:
    chain = Chain(api=api)
    chain.institution = build_institution(api, **(institution_overrides or {}))
    chain.giving_periods = build_giving_periods(api, chain.institution_id, period_specs)
    return chain


def chain_through_authorization(
    api: ApiClient,
    institution_overrides: Optional[Dict[str, Any]] = None,
    period_specs: Optional[List[Dict[str, Any]]] = None,
    authorization_overrides: Optional[Dict[str, Any]] = None,
) -> Chain:
    chain = chain_through_periods(api, institution_overrides, period_specs)
    chain.governance_authorization = build_authorized_authorization(
        api, chain.institution_id, **(authorization_overrides or {})
    )
    return chain


def chain_through_underwriting(
    api: ApiClient,
    institution_overrides: Optional[Dict[str, Any]] = None,
    period_specs: Optional[List[Dict[str, Any]]] = None,
    authorization_overrides: Optional[Dict[str, Any]] = None,
    asset_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
) -> Chain:
    chain = chain_through_authorization(
        api, institution_overrides, period_specs, authorization_overrides
    )
    chain.collateral_asset = build_collateral_asset(
        api, chain.institution_id, **(asset_overrides or {})
    )
    chain.loan_application = build_draft_application(
        api,
        chain.institution_id,
        chain.governance_authorization_id,
        **(application_overrides or {}),
    )
    chain.loan_application = submit_to_underwriting(api, chain.loan_application_id)
    return chain


def chain_through_assignment(api: ApiClient, **kwargs: Any) -> Chain:
    chain = chain_through_underwriting(api, **kwargs)
    chain.collateral_asset = assign_asset(
        api, chain.collateral_asset_id, chain.loan_application_id
    )
    return chain


def chain_through_approval(api: ApiClient, **kwargs: Any) -> Chain:
    chain = chain_through_assignment(api, **kwargs)
    refer_to_committee(api, chain.loan_application_id)
    chain.loan_application = render_committee_decision(api, chain.loan_application_id, "APPROVE")
    return chain


def chain_through_loan(
    api: ApiClient, loan_overrides: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Chain:
    chain = chain_through_approval(api, **kwargs)
    chain.loan = build_loan(api, chain.loan_application_id, **(loan_overrides or {}))
    return chain


# ─── pytest fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def api() -> ApiClient:
    """One client per test; the harness supplies API_BASE_URL."""
    return ApiClient()


@pytest.fixture
def generic_api() -> GenericApiClient:
    """Raw framework client, for probing paths the typed client does not name."""
    return GenericApiClient()


@pytest.fixture
def institution(api: ApiClient) -> Dict[str, Any]:
    return build_institution(api)


@pytest.fixture
def chain_periods(api: ApiClient) -> Chain:
    return chain_through_periods(api)


@pytest.fixture
def chain_authorized(api: ApiClient) -> Chain:
    return chain_through_authorization(api)


@pytest.fixture
def chain_underwriting(api: ApiClient) -> Chain:
    return chain_through_underwriting(api)


@pytest.fixture
def chain_assigned(api: ApiClient) -> Chain:
    return chain_through_assignment(api)


@pytest.fixture
def chain_approved(api: ApiClient) -> Chain:
    return chain_through_approval(api)


@pytest.fixture
def chain_loan(api: ApiClient) -> Chain:
    return chain_through_loan(api)
