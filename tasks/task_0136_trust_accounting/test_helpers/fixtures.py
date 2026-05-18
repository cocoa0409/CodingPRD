"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests need the system in a late state (e.g., an ACTIVE trust
with two trustees of distinct user_ids, a funded asset, an open
tax year, an approved distribution waiting to be executed). Each
fixture composes the lower-level steps so the test body can focus on
the rule under assertion.

IDENTITY THREADING — PRD §2.1:

- Grantor identity is recorded as Trust.grantor_user_id at creation
  and compared on every later grantor-scoped operation. Every helper
  that creates a Trust returns the grantor X-User-ID alongside it,
  and re-uses that same identity for downstream grantor calls (add
  trustee, add beneficiary, activate, revoke, patch). Callers MAY
  override by passing an explicit `grantor_user_id` kwarg.

- Trustee identity is entity_backed:Trustee — X-User-ID must equal
  the user_id of a Trustee record under the trust. Every helper that
  needs a Trustee role threads make_trustee_headers(trustee_user_id)
  using the actual Trustee.user_id returned by create_trustee. Many
  PRD rules (segregation of duties on approve, on reject) require
  two DIFFERENT trustee user_ids; helpers that build approvable
  distributions therefore register TWO trustees by default.

- Beneficiary identity is entity_backed:Beneficiary — X-User-ID must
  equal Beneficiary.id. Helpers that simulate Beneficiary reads use
  make_beneficiary_headers(beneficiary["id"]).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clock_advance_payload,
    create_asset_payload,
    create_beneficiary_payload,
    create_distribution_payload,
    create_tax_year_payload,
    create_transaction_payload,
    create_trust_payload,
    create_trustee_payload,
    iso_instant_utc,
    random_suffix,
)
from .test_users import (
    GRANTOR_ID,
    GRANTOR_ID_ALT,
    TEST_USERS,
    make_beneficiary_headers,
    make_grantor_headers,
    make_trustee_headers,
)


# ===========================================================================
# Clock — PRD §2.10
# ===========================================================================
def advance_clock_to(to_timestamp: str,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """POST /_clock/advance — PRD §2.10. Allowed roles:
    TaxPreparer, Trustee, Grantor."""
    headers = headers or TEST_USERS["tax_preparer_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(to_timestamp), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Trust — PRD §3.1
# ===========================================================================
def create_trust(
    *,
    grantor_user_id: Optional[str] = None,
    trust_type: str = "IRREVOCABLE",
    grantor_tax_status: str = "NON_GRANTOR",
    has_grantor_powers: bool = False,
    name: Optional[str] = None,
    situs_state: Optional[str] = None,
    inception_date: Optional[str] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """POST /trusts — PRD §3.1 (Grantor role).

    Returns ``(trust, grantor_headers)`` so callers can thread the
    same grantor X-User-ID into every later grantor-scoped call.
    PRD §2.1 requires that subsequent Trust-scoped grantor operations
    use the same X-User-ID that was recorded as Trust.grantor_user_id.
    """
    grantor_user_id = grantor_user_id or GRANTOR_ID
    grantor_headers = make_grantor_headers(grantor_user_id)
    payload = create_trust_payload(
        name=name,
        trust_type=trust_type,
        grantor_tax_status=grantor_tax_status,
        has_grantor_powers=has_grantor_powers,
        situs_state=situs_state,
        inception_date=inception_date,
        **overrides,
    )
    resp = api_client.create_trust(payload, grantor_headers)
    trust = get_success_data(resp)
    return trust, grantor_headers


def add_trustee(
    trust: Dict[str, Any],
    grantor_headers: Dict[str, str],
    *,
    user_id: Optional[str] = None,
    full_name: Optional[str] = None,
    is_primary: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """POST /trusts/{trustId}/trustees — PRD §3.2 (Grantor role).

    Returns ``(trustee, trustee_headers)`` where trustee_headers is
    pre-built via make_trustee_headers(trustee.user_id) ready for any
    later Trustee-acting call.
    """
    user_id = user_id or f"trustee-user-{random_suffix(8)}"
    payload = create_trustee_payload(
        user_id=user_id, full_name=full_name, is_primary=is_primary,
    )
    resp = api_client.create_trustee(
        trust["id"], payload, grantor_headers,
    )
    trustee = get_success_data(resp)
    trustee_headers = make_trustee_headers(trustee["user_id"])
    return trustee, trustee_headers


def add_beneficiary(
    trust: Dict[str, Any],
    grantor_headers: Dict[str, str],
    *,
    full_name: Optional[str] = None,
    relation_class: str = "CHILD",
    beneficiary_class: str = "INCOME_AND_REMAINDER",
    distribution_tier: str = "TIER_1",
    birth_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /trusts/{trustId}/beneficiaries — PRD §3.2."""
    payload = create_beneficiary_payload(
        full_name=full_name,
        relation_class=relation_class,
        beneficiary_class=beneficiary_class,
        distribution_tier=distribution_tier,
        birth_date=birth_date,
        **overrides,
    )
    resp = api_client.create_beneficiary(
        trust["id"], payload, grantor_headers,
    )
    return get_success_data(resp)


def add_tax_year(
    trust: Dict[str, Any],
    *,
    calendar_year: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /trusts/{trustId}/tax-years — PRD §3.5 (Trustee or
    TaxPreparer)."""
    headers = headers or TEST_USERS["tax_preparer_headers"]
    payload = create_tax_year_payload(calendar_year=calendar_year)
    resp = api_client.create_tax_year(trust["id"], payload, headers)
    return get_success_data(resp)


def add_asset(
    trust: Dict[str, Any],
    *,
    book_value: float = 100_000.00,
    classification: str = "PRINCIPAL",
    asset_class: str = "CASH",
    description: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /trusts/{trustId}/assets — PRD §3.2 (Grantor or Trustee).

    Defaults to the Grantor-owner headers if the caller supplies them;
    otherwise opaque Grantor fallback (only safe if ownership is not
    exercised). Most call sites pass `headers=grantor_headers` so the
    ownership comparison passes.
    """
    headers = headers or TEST_USERS["grantor_headers"]
    payload = create_asset_payload(
        book_value=book_value,
        classification=classification,
        asset_class=asset_class,
        description=description,
    )
    resp = api_client.create_asset(trust["id"], payload, headers)
    return get_success_data(resp)


def activate_trust(
    trust: Dict[str, Any],
    grantor_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /trusts/{trustId}/activate — PRD §3.1 (Grantor)."""
    resp = api_client.activate_trust(trust["id"], grantor_headers)
    return get_success_data(resp)


def revoke_trust(
    trust: Dict[str, Any],
    grantor_headers: Dict[str, str],
) -> Dict[str, Any]:
    resp = api_client.revoke_trust(trust["id"], grantor_headers)
    return get_success_data(resp)


def re_get_trust(
    trust_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["auditor_headers"]
    resp = api_client.get_trust(trust_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Transactions — PRD §3.3
# ===========================================================================
def book_transaction(
    trust: Dict[str, Any],
    trustee_headers: Dict[str, str],
    *,
    txn_type: str = "INCOME_ORDINARY",
    amount: float = 10_000.00,
    transaction_date: Optional[str] = None,
    principal_or_income: str = "INCOME",
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /trusts/{trustId}/transactions — PRD §3.3 (Trustee)."""
    payload = create_transaction_payload(
        txn_type=txn_type,
        amount=amount,
        transaction_date=transaction_date,
        principal_or_income=principal_or_income,
        description=description,
    )
    resp = api_client.create_transaction(
        trust["id"], payload, trustee_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Distributions — PRD §3.4
# ===========================================================================
def propose_distribution(
    trust: Dict[str, Any],
    beneficiary: Dict[str, Any],
    proposer_headers: Dict[str, str],
    *,
    amount_principal: float = 0.0,
    amount_income: float = 0.0,
    distribution_type: str = "DISCRETIONARY",
    scheduled_date: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /trusts/{trustId}/distributions — PRD §3.4. Either Grantor
    or Trustee may propose."""
    payload = create_distribution_payload(
        beneficiary_id=beneficiary["id"],
        amount_principal=amount_principal,
        amount_income=amount_income,
        distribution_type=distribution_type,
        scheduled_date=scheduled_date,
    )
    resp = api_client.create_distribution(
        trust["id"], payload, proposer_headers,
    )
    return get_success_data(resp)


def approve_distribution(
    trust: Dict[str, Any],
    distribution: Dict[str, Any],
    approver_trustee_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /distributions/{id}/approve — PRD §3.4 (Trustee, must
    differ from proposer)."""
    resp = api_client.approve_distribution(
        trust["id"], distribution["id"], approver_trustee_headers,
    )
    return get_success_data(resp)


def execute_distribution(
    trust: Dict[str, Any],
    distribution: Dict[str, Any],
    trustee_headers: Dict[str, str],
) -> Dict[str, Any]:
    """POST /distributions/{id}/execute — PRD §3.4 (Trustee)."""
    resp = api_client.execute_distribution(
        trust["id"], distribution["id"], trustee_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# TaxYear — PRD §3.5
# ===========================================================================
def begin_close_tax_year(
    trust: Dict[str, Any],
    tax_year: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["tax_preparer_headers"]
    resp = api_client.begin_close_tax_year(
        trust["id"], tax_year["id"], headers,
    )
    return get_success_data(resp)


def finalize_tax_year(
    trust: Dict[str, Any],
    tax_year: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["tax_preparer_headers"]
    resp = api_client.finalize_tax_year(
        trust["id"], tax_year["id"], headers,
    )
    return get_success_data(resp)


def amend_tax_year(
    trust: Dict[str, Any],
    tax_year: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["tax_preparer_headers"]
    resp = api_client.amend_tax_year(
        trust["id"], tax_year["id"], headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Composite scenario — Tier 2: trust shaped for activation
# ===========================================================================
class TrustScenario:
    """Convenience bag holding everything fixtures need to thread
    identity correctly.

    Fields:
      trust              — Trust dict
      grantor_headers    — headers carrying Trust.grantor_user_id
      primary_trustee    — Trustee dict (is_primary=True, ACTIVE)
      primary_trustee_headers — headers carrying primary trustee user_id
      second_trustee     — Trustee dict (is_primary=False, ACTIVE)
      second_trustee_headers  — headers carrying second trustee user_id
      beneficiary        — Beneficiary dict (TIER_1, ACTIVE)
      tax_year           — open TaxYear matching inception_date's year
    """

    def __init__(
        self,
        *,
        trust: Dict[str, Any],
        grantor_headers: Dict[str, str],
        primary_trustee: Optional[Dict[str, Any]] = None,
        primary_trustee_headers: Optional[Dict[str, str]] = None,
        second_trustee: Optional[Dict[str, Any]] = None,
        second_trustee_headers: Optional[Dict[str, str]] = None,
        beneficiary: Optional[Dict[str, Any]] = None,
        tax_year: Optional[Dict[str, Any]] = None,
    ):
        self.trust = trust
        self.grantor_headers = grantor_headers
        self.primary_trustee = primary_trustee
        self.primary_trustee_headers = primary_trustee_headers
        self.second_trustee = second_trustee
        self.second_trustee_headers = second_trustee_headers
        self.beneficiary = beneficiary
        self.tax_year = tax_year


def setup_draft_trust(
    *,
    trust_type: str = "IRREVOCABLE",
    grantor_tax_status: str = "NON_GRANTOR",
    has_grantor_powers: bool = False,
    inception_date: str = "2026-01-01",
    grantor_user_id: Optional[str] = None,
    name: Optional[str] = None,
) -> TrustScenario:
    """Tier-1 helper: just a DRAFT trust with grantor headers threaded.

    PRD §3.1: 'The new Trust enters DRAFT status, its grantor_user_id
    is pinned to the creator's X-User-ID'.
    """
    trust, grantor_headers = create_trust(
        grantor_user_id=grantor_user_id,
        trust_type=trust_type,
        grantor_tax_status=grantor_tax_status,
        has_grantor_powers=has_grantor_powers,
        inception_date=inception_date,
        name=name,
    )
    return TrustScenario(trust=trust, grantor_headers=grantor_headers)


def setup_activatable_trust(
    *,
    trust_type: str = "IRREVOCABLE",
    grantor_tax_status: str = "NON_GRANTOR",
    has_grantor_powers: bool = False,
    inception_date: str = "2026-01-01",
    calendar_year: int = 2026,
    grantor_user_id: Optional[str] = None,
    beneficiary_distribution_tier: str = "TIER_1",
    beneficiary_relation_class: str = "CHILD",
    beneficiary_birth_date: str = "1990-06-01",
    num_trustees: int = 2,
) -> TrustScenario:
    """Tier-2 helper: trust still DRAFT but with all activation
    preconditions satisfied.

    PRD §3.1: 'Before a trust can be activated, three structural
    conditions must hold. There must be exactly one Trustee record
    under the trust with is_primary set to true and status equal to
    ACTIVE ... There must be at least one Beneficiary record under
    the trust with status equal to ACTIVE ... A TaxYear matching the
    calendar year of inception_date must exist for the trust in OPEN
    status'.

    Registers up to two distinct trustee user_ids so downstream
    approve/reject calls can satisfy PRD §3.4 segregation of duties.
    """
    scenario = setup_draft_trust(
        trust_type=trust_type,
        grantor_tax_status=grantor_tax_status,
        has_grantor_powers=has_grantor_powers,
        inception_date=inception_date,
        grantor_user_id=grantor_user_id,
    )
    # Primary trustee.
    primary_trustee, primary_trustee_headers = add_trustee(
        scenario.trust, scenario.grantor_headers,
        user_id=f"primary-trustee-{random_suffix(6)}",
        full_name="Primary Trustee",
        is_primary=True,
    )
    scenario.primary_trustee = primary_trustee
    scenario.primary_trustee_headers = primary_trustee_headers

    # Optional second trustee with a DIFFERENT user_id (PRD §3.4
    # segregation of duties).
    if num_trustees >= 2:
        second_trustee, second_trustee_headers = add_trustee(
            scenario.trust, scenario.grantor_headers,
            user_id=f"second-trustee-{random_suffix(6)}",
            full_name="Second Trustee",
            is_primary=False,
        )
        scenario.second_trustee = second_trustee
        scenario.second_trustee_headers = second_trustee_headers

    # Beneficiary.
    beneficiary = add_beneficiary(
        scenario.trust, scenario.grantor_headers,
        relation_class=beneficiary_relation_class,
        beneficiary_class="INCOME_AND_REMAINDER",
        distribution_tier=beneficiary_distribution_tier,
        birth_date=beneficiary_birth_date,
    )
    scenario.beneficiary = beneficiary

    # TaxYear matching inception_date's calendar year (PRD §3.1
    # ERR_NO_OPEN_TAX_YEAR).
    tax_year = add_tax_year(
        scenario.trust, calendar_year=calendar_year,
    )
    scenario.tax_year = tax_year
    # PRD §3.5: opening the first TaxYear for a trust sets the Trust's
    # `current_tax_year_id`, which is a Trust mutation and therefore a
    # PRD §2.9 cascade that bumps `Trust.version`. Re-fetch the trust so
    # callers that read `scenario.trust["version"]` see the live value.
    scenario.trust = re_get_trust(scenario.trust["id"])
    return scenario


def setup_active_trust(
    *,
    trust_type: str = "IRREVOCABLE",
    grantor_tax_status: str = "NON_GRANTOR",
    has_grantor_powers: bool = False,
    inception_date: str = "2026-01-01",
    calendar_year: int = 2026,
    grantor_user_id: Optional[str] = None,
    beneficiary_distribution_tier: str = "TIER_1",
    beneficiary_relation_class: str = "CHILD",
    beneficiary_birth_date: str = "1990-06-01",
    num_trustees: int = 2,
) -> TrustScenario:
    """Tier-2 helper: trust ACTIVE, primary trustee + second trustee +
    beneficiary + open TaxYear. No assets yet."""
    scenario = setup_activatable_trust(
        trust_type=trust_type,
        grantor_tax_status=grantor_tax_status,
        has_grantor_powers=has_grantor_powers,
        inception_date=inception_date,
        calendar_year=calendar_year,
        grantor_user_id=grantor_user_id,
        beneficiary_distribution_tier=beneficiary_distribution_tier,
        beneficiary_relation_class=beneficiary_relation_class,
        beneficiary_birth_date=beneficiary_birth_date,
        num_trustees=num_trustees,
    )
    scenario.trust = activate_trust(
        scenario.trust, scenario.grantor_headers,
    )
    return scenario


def setup_active_trust_with_income(
    *,
    income_amount: float = 50_000.00,
    income_txn_type: str = "INCOME_ORDINARY",
    income_date_year: int = 2026,
    income_date_month: int = 6,
    income_date_day: int = 1,
    **overrides: Any,
) -> TrustScenario:
    """Tier-3 helper: ACTIVE trust + ordinary income booked, ready to
    propose income distributions.

    PRD §3.3: 'Booking a Transaction triggers a balance recomputation
    cascade on the parent Trust — depending on principal_or_income,
    either principal_balance or income_balance is updated'.
    """
    scenario = setup_active_trust(**overrides)
    book_transaction(
        scenario.trust,
        scenario.primary_trustee_headers,
        txn_type=income_txn_type,
        amount=income_amount,
        transaction_date=iso_instant_utc(
            income_date_year, income_date_month, income_date_day,
        ),
        principal_or_income="INCOME",
    )
    # Refresh trust to pick up income_balance.
    scenario.trust = re_get_trust(scenario.trust["id"])
    return scenario


def setup_active_trust_with_principal(
    *,
    principal_amount: float = 100_000.00,
    asset_class: str = "CASH",
    **overrides: Any,
) -> TrustScenario:
    """ACTIVE trust + a FUNDED PRINCIPAL asset already on the books.

    Useful when a test needs principal_balance to be non-zero without
    booking transactions. Activation runs after the asset is added so
    the asset is included in the initial principal_balance computation
    (PRD §3.1 activation side-effect).
    """
    scenario = setup_activatable_trust(**overrides)
    # Add a FUNDED PRINCIPAL asset BEFORE activate, so activation
    # recomputes principal_balance from it (PRD §3.1).
    add_asset(
        scenario.trust,
        book_value=principal_amount,
        classification="PRINCIPAL",
        asset_class=asset_class,
        headers=scenario.grantor_headers,
    )
    scenario.trust = activate_trust(
        scenario.trust, scenario.grantor_headers,
    )
    return scenario


# ===========================================================================
# Composite scenario — Tier 3: proposed / approved distribution
# ===========================================================================
def setup_active_trust_with_proposed_income_distribution(
    *,
    income_amount: float = 50_000.00,
    distribution_income: float = 20_000.00,
    distribution_principal: float = 0.0,
    distribution_type: str = "DISCRETIONARY",
    proposer: str = "primary_trustee",
    **overrides: Any,
) -> Tuple[TrustScenario, Dict[str, Any]]:
    """ACTIVE trust with income booked + a PROPOSED Distribution
    ready to be approved.

    `proposer` selects which actor proposes the distribution.
    'primary_trustee' → primary trustee headers (so the SECOND trustee
                         can approve)
    'second_trustee'  → second trustee headers (so the PRIMARY trustee
                         can approve)
    'grantor'         → grantor headers (so any trustee can approve)
    """
    scenario = setup_active_trust_with_income(
        income_amount=income_amount, **overrides,
    )
    proposer_headers_map = {
        "primary_trustee": scenario.primary_trustee_headers,
        "second_trustee": scenario.second_trustee_headers,
        "grantor": scenario.grantor_headers,
    }
    proposer_headers = proposer_headers_map[proposer]
    distribution = propose_distribution(
        scenario.trust,
        scenario.beneficiary,
        proposer_headers,
        amount_income=distribution_income,
        amount_principal=distribution_principal,
        distribution_type=distribution_type,
    )
    return scenario, distribution


def setup_active_trust_with_approved_income_distribution(
    *,
    income_amount: float = 50_000.00,
    distribution_income: float = 20_000.00,
    distribution_principal: float = 0.0,
    distribution_type: str = "DISCRETIONARY",
    **overrides: Any,
) -> Tuple[TrustScenario, Dict[str, Any]]:
    """ACTIVE trust + income booked + Distribution PROPOSED by the
    primary trustee and APPROVED by the second trustee (PRD §3.4
    segregation of duties)."""
    scenario, distribution = (
        setup_active_trust_with_proposed_income_distribution(
            income_amount=income_amount,
            distribution_income=distribution_income,
            distribution_principal=distribution_principal,
            distribution_type=distribution_type,
            proposer="primary_trustee",
            **overrides,
        )
    )
    distribution = approve_distribution(
        scenario.trust, distribution,
        scenario.second_trustee_headers,
    )
    return scenario, distribution


def setup_active_trust_with_executed_income_distribution(
    *,
    income_amount: float = 50_000.00,
    distribution_income: float = 20_000.00,
    **overrides: Any,
) -> Tuple[TrustScenario, Dict[str, Any]]:
    """Push the lifecycle one more step: PROPOSED → APPROVED →
    EXECUTED."""
    scenario, distribution = (
        setup_active_trust_with_approved_income_distribution(
            income_amount=income_amount,
            distribution_income=distribution_income,
            **overrides,
        )
    )
    distribution = execute_distribution(
        scenario.trust, distribution,
        scenario.second_trustee_headers,
    )
    return scenario, distribution


# ===========================================================================
# Tier 4 — TaxYear closing helpers
# ===========================================================================
def setup_closed_tax_year(
    *,
    income_amount: float = 5_000.00,
    distribution_income: float = 0.0,
    **overrides: Any,
) -> TrustScenario:
    """Full lifecycle through TaxYear CLOSED.

    PRD §3.5: 'A TaxPreparer initiates closing when the calendar year
    has ended. The transition OPEN → CLOSING requires that the
    logical clock has reached at least the TaxYear's end_date'. So we
    advance the clock past 2026-12-31 first.
    """
    inception_date = overrides.pop("inception_date", "2026-01-01")
    calendar_year = overrides.pop("calendar_year", 2026)
    scenario = setup_active_trust_with_income(
        income_amount=income_amount,
        inception_date=inception_date,
        calendar_year=calendar_year,
        **overrides,
    )
    # Optionally execute a single income distribution before closing.
    if distribution_income > 0:
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_income=distribution_income,
            distribution_type="DISCRETIONARY",
            scheduled_date=iso_instant_utc(calendar_year, 6, 15),
        )
        dist = approve_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
        execute_distribution(
            scenario.trust, dist, scenario.second_trustee_headers,
        )
    # PRD §3.5: clock must be >= end_date for begin-close.
    advance_clock_to(iso_instant_utc(calendar_year + 1, 1, 2))
    scenario.tax_year = begin_close_tax_year(
        scenario.trust, scenario.tax_year,
    )
    scenario.tax_year = finalize_tax_year(
        scenario.trust, scenario.tax_year,
    )
    # Refresh trust to capture final balances.
    scenario.trust = re_get_trust(scenario.trust["id"])
    return scenario


# ===========================================================================
# Difficulty-design helpers — pre-built recipes for §1.8 instances
# ===========================================================================
def setup_grantor_vs_non_grantor_pair() -> Tuple[
    TrustScenario, TrustScenario,
]:
    """For difficulty instance grantor_vs_non_grantor_trust_taxable_income.

    Builds two trusts whose only meaningful difference is
    grantor_tax_status and trust_type. Each ends with a CLOSED 2026
    TaxYear after booking 10000 ordinary income and executing a 3000
    income distribution.
    """
    # Non-grantor trust — IRREVOCABLE / NON_GRANTOR.
    non_grantor = setup_closed_tax_year(
        trust_type="IRREVOCABLE",
        grantor_tax_status="NON_GRANTOR",
        has_grantor_powers=False,
        income_amount=10_000.00,
        distribution_income=3_000.00,
        grantor_user_id=f"{GRANTOR_ID}-ng-{random_suffix(4)}",
    )
    # Grantor trust — REVOCABLE / GRANTOR (the simplest grantor-tax-status
    # combo that PRD §3.1 permits).
    grantor = setup_closed_tax_year(
        trust_type="REVOCABLE",
        grantor_tax_status="GRANTOR",
        has_grantor_powers=False,
        income_amount=10_000.00,
        distribution_income=3_000.00,
        grantor_user_id=f"{GRANTOR_ID}-g-{random_suffix(4)}",
    )
    return non_grantor, grantor


def setup_skip_person_distribution_pair() -> Tuple[
    TrustScenario, Dict[str, Any], Dict[str, Any],
]:
    """For difficulty instance skip_vs_non_skip_distribution_gst_tax.

    Builds an ACTIVE non-grantor trust funded with 5,000,000 principal
    CASH, two beneficiaries (one GRANDCHILD aka skip-person, one
    CHILD aka non-skip), and pre-consumes gst_exemption_used down to
    13,500,000 by executing a prior 13,500,000 distribution to the
    grandchild.

    Returns (scenario, beneficiary_skip, beneficiary_non_skip).
    """
    # Big trust seeded with $5M PRINCIPAL CASH so distributions can fit.
    scenario = setup_active_trust_with_principal(
        principal_amount=5_000_000.00,
        beneficiary_distribution_tier="TIER_2",
        beneficiary_relation_class="CHILD",  # the default non-skip
        beneficiary_birth_date="2000-01-01",
    )
    non_skip = scenario.beneficiary

    # Add a GRANDCHILD skip-person beneficiary.
    skip = add_beneficiary(
        scenario.trust, scenario.grantor_headers,
        full_name="Skip Grandchild",
        relation_class="GRANDCHILD",
        beneficiary_class="INCOME_AND_REMAINDER",
        distribution_tier="TIER_2",
        birth_date="2010-01-01",
    )

    # Pre-consume exemption: book a prior 13,500,000 distribution to
    # the skip beneficiary. We need enough principal to cover it, so
    # add an additional 13,500,000 principal asset first.
    add_asset(
        scenario.trust,
        book_value=13_500_000.00,
        classification="PRINCIPAL",
        asset_class="CASH",
        description="Pre-fund for exemption consumption",
        headers=scenario.grantor_headers,
    )
    scenario.trust = re_get_trust(scenario.trust["id"])

    preseed = propose_distribution(
        scenario.trust, skip,
        scenario.primary_trustee_headers,
        amount_principal=13_500_000.00,
        amount_income=0.0,
        distribution_type="DISCRETIONARY",
    )
    preseed = approve_distribution(
        scenario.trust, preseed, scenario.second_trustee_headers,
    )
    execute_distribution(
        scenario.trust, preseed, scenario.second_trustee_headers,
    )
    scenario.trust = re_get_trust(scenario.trust["id"])
    return scenario, skip, non_skip


def setup_exemption_almost_consumed_trust(
    *,
    pre_consumed: float = 13_609_999.00,
) -> Tuple[TrustScenario, Dict[str, Any]]:
    """For difficulty instance gst_exemption_then_tax_evaluation_order.

    Builds an ACTIVE non-grantor trust where gst_exemption_used has
    already been pushed to `pre_consumed` (default 13,609,999 — 1.00
    of exemption remaining). A GRANDCHILD skip-person beneficiary is
    returned for the caller to propose a distribution against.
    """
    needed = pre_consumed + 100.00  # buffer for the test's own
    # later distribution amount
    scenario = setup_active_trust_with_principal(
        principal_amount=needed,
        beneficiary_distribution_tier="TIER_2",
        beneficiary_relation_class="CHILD",
        beneficiary_birth_date="2000-01-01",
    )
    # Add a GRANDCHILD beneficiary.
    skip = add_beneficiary(
        scenario.trust, scenario.grantor_headers,
        full_name="Skip Grandchild",
        relation_class="GRANDCHILD",
        beneficiary_class="INCOME_AND_REMAINDER",
        distribution_tier="TIER_2",
        birth_date="2010-01-01",
    )
    # Pre-consume exemption with one big distribution.
    if pre_consumed > 0:
        d = propose_distribution(
            scenario.trust, skip,
            scenario.primary_trustee_headers,
            amount_principal=pre_consumed,
            amount_income=0.0,
            distribution_type="DISCRETIONARY",
        )
        d = approve_distribution(
            scenario.trust, d, scenario.second_trustee_headers,
        )
        execute_distribution(
            scenario.trust, d, scenario.second_trustee_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
    return scenario, skip


def setup_tax_year_in_amend_state(
    *,
    income_amount: float = 5_000.00,
    distribution_income: float = 0.0,
) -> TrustScenario:
    """Drive a TaxYear through CLOSED → AMENDED.

    Returns a scenario whose tax_year is in AMENDED status; the
    caller can finalize → CLOSED, amend again, etc.
    """
    scenario = setup_closed_tax_year(
        income_amount=income_amount,
        distribution_income=distribution_income,
    )
    scenario.tax_year = amend_tax_year(
        scenario.trust, scenario.tax_year,
    )
    return scenario


def list_k1s_for_year(
    trust: Dict[str, Any],
    tax_year: Dict[str, Any],
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """List K-1s with default 1000-limit so callers don't need to
    paginate during setup."""
    headers = headers or TEST_USERS["auditor_headers"]
    merged_params: Dict[str, Any] = {"limit": 100}
    if params:
        merged_params.update(params)
    resp = api_client.list_k1s(
        trust["id"], tax_year["id"], headers, params=merged_params,
    )
    # Use validate_paginated indirectly by reading the envelope; we
    # only need the data list here.
    body = resp.json()
    return body.get("data", [])


__all__ = [
    "TrustScenario",
    "advance_clock_to",
    "create_trust",
    "add_trustee",
    "add_beneficiary",
    "add_tax_year",
    "add_asset",
    "activate_trust",
    "revoke_trust",
    "re_get_trust",
    "book_transaction",
    "propose_distribution",
    "approve_distribution",
    "execute_distribution",
    "begin_close_tax_year",
    "finalize_tax_year",
    "amend_tax_year",
    "setup_draft_trust",
    "setup_activatable_trust",
    "setup_active_trust",
    "setup_active_trust_with_income",
    "setup_active_trust_with_principal",
    "setup_active_trust_with_proposed_income_distribution",
    "setup_active_trust_with_approved_income_distribution",
    "setup_active_trust_with_executed_income_distribution",
    "setup_closed_tax_year",
    "setup_grantor_vs_non_grantor_pair",
    "setup_skip_person_distribution_pair",
    "setup_exemption_almost_consumed_trust",
    "setup_tax_year_in_amend_state",
    "list_k1s_for_year",
    "make_beneficiary_headers",
]
