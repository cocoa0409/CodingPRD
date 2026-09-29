"""Composite state builders.

Each individual test runs against a freshly launched API with an empty
database, so every fixture here builds its preconditions from scratch through
the public API - never by assuming a row already exists.

The single most-used builder is :func:`onboard_merchant`, which walks the whole
intake path (create -> owners -> submit -> verify -> screen ->
advance-to-underwriting -> credit assessment -> committee decision) and returns
the ids of the minted Merchant and ReserveAccount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .factories import (
    appeal_payload,
    application_payload,
    beneficial_owner_payload,
    category_rule_payload,
    credit_assessment_payload,
    day_activity_payload,
    portfolio_forecast_payload,
    release_request_payload,
    remediation_program_payload,
    screening_payload,
    settlement_batch_payload,
    termination_decision_payload,
    verification_payload,
)
from .test_users import (
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    USER_COMMITTEE_02,
    USER_OFFICER_01,
    USER_TREASURY_01,
    make_applicant_headers,
    make_merchant_user_headers,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_risk_committee_headers,
    make_underwriting_officer_headers,
)

# ---------------------------------------------------------------------------
# Date / clock helpers
# ---------------------------------------------------------------------------


def iso_date(value: str | date) -> str:
    return value.isoformat() if isinstance(value, date) else value


def plus_days(business_date: str, days: int) -> str:
    """Calendar-day arithmetic on a YYYY-MM-DD string."""
    return (date.fromisoformat(business_date) + timedelta(days=days)).isoformat()


def day_start(business_date: str) -> str:
    """Midnight UTC of a calendar date, in the clock's wire format."""
    return f"{business_date}T00:00:00Z"


def date_of(instant: str) -> str:
    """The calendar date part of a UTC instant."""
    return instant[:10]


def days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def set_clock(api: ApiClient, now_utc: str, headers: Optional[dict[str, str]] = None) -> None:
    """Move the logical clock. Any role may do this."""
    get_success_data(api.set_clock(now_utc, headers or make_underwriting_officer_headers()))


def reset_clock(api: ApiClient) -> None:
    set_clock(api, CLOCK_EPOCH)


# ---------------------------------------------------------------------------
# Intake step helpers
# ---------------------------------------------------------------------------


def create_category_rule(api: ApiClient, mcc_code: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_category_rule(
            category_rule_payload(mcc_code, **overrides), make_underwriting_officer_headers()
        )
    )


def create_draft_application(api: ApiClient, **overrides: Any) -> dict[str, Any]:
    """POST /merchant-applications as an Applicant (creation skips the owner check)."""
    payload = application_payload(**overrides)
    # A creating Applicant has no application id yet; the contract exempts the
    # creation call from the owner check unless it supersedes another application.
    headers = make_applicant_headers(payload.get("supersedes_application_id") or "new-applicant")
    return get_success_data(api.create_application(payload, headers))


def add_beneficial_owner(api: ApiClient, application_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_beneficial_owner(
            beneficial_owner_payload(application_id, **overrides),
            make_applicant_headers(application_id),
        )
    )


def submit_application(api: ApiClient, application_id: str) -> dict[str, Any]:
    return get_success_data(
        api.submit_application(application_id, make_applicant_headers(application_id))
    )


def record_verification(api: ApiClient, application_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.create_business_verification(
            verification_payload(application_id, **overrides), make_underwriting_officer_headers()
        )
    )


def screen_owner(api: ApiClient, owner_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api.screen_beneficial_owner(
            owner_id, screening_payload(**overrides), make_underwriting_officer_headers()
        )
    )


def advance_to_underwriting(api: ApiClient, application_id: str, user_id: str = USER_OFFICER_01) -> dict[str, Any]:
    return get_success_data(
        api.advance_to_underwriting(application_id, make_underwriting_officer_headers(user_id))
    )


def create_assessment(
    api: ApiClient,
    application_id: str,
    expected_application_version: int,
    method: str = "LAG_WEIGHTED",
    user_id: str = USER_OFFICER_01,
) -> dict[str, Any]:
    return get_success_data(
        api.create_credit_assessment(
            credit_assessment_payload(application_id, expected_application_version, method),
            make_underwriting_officer_headers(user_id),
        )
    )


def decide_application(
    api: ApiClient,
    application_id: str,
    decision: str = "APPROVE",
    user_id: str = USER_COMMITTEE_01,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api.decide_application(application_id, payload, make_risk_committee_headers(user_id))
    )


def read_application(api: ApiClient, application_id: str) -> dict[str, Any]:
    return get_success_data(api.get_application(application_id, make_underwriting_officer_headers()))


def read_merchant(api: ApiClient, merchant_id: str) -> dict[str, Any]:
    return get_success_data(api.get_merchant(merchant_id, make_risk_analyst_headers()))


def read_reserve_account(api: ApiClient, reserve_account_id: str) -> dict[str, Any]:
    return get_success_data(
        api.get_reserve_account(reserve_account_id, make_portfolio_controller_headers())
    )


def read_batch(api: ApiClient, batch_id: str) -> dict[str, Any]:
    return get_success_data(api.get_settlement_batch(batch_id, make_portfolio_controller_headers()))


def read_alert(api: ApiClient, merchant_id: str, alert_id: str) -> dict[str, Any]:
    rows = get_success_data(api.list_monitoring_alerts(merchant_id, make_risk_analyst_headers()))
    for row in rows:
        if row["id"] == alert_id:
            return row
    raise AssertionError(f"alert {alert_id} not listed for merchant {merchant_id}")


def read_program(api: ApiClient, program_id: str) -> dict[str, Any]:
    return get_success_data(api.get_remediation_program(program_id, make_risk_analyst_headers()))


def read_termination_decision(api: ApiClient, decision_id: str) -> dict[str, Any]:
    return get_success_data(api.get_termination_decision(decision_id, make_risk_analyst_headers()))


def read_appeal(api: ApiClient, appeal_id: str) -> dict[str, Any]:
    return get_success_data(api.get_appeal(appeal_id, make_risk_analyst_headers()))


def read_forecast(api: ApiClient, forecast_id: str) -> dict[str, Any]:
    return get_success_data(
        api.get_portfolio_forecast(forecast_id, make_portfolio_controller_headers())
    )


def list_reserve_ledger(api: ApiClient, reserve_account_id: str, **params: Any) -> list[dict[str, Any]]:
    return get_success_data(
        api.list_reserve_ledger_entries(
            reserve_account_id, make_portfolio_controller_headers(), **params
        )
    )


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


@dataclass
class OwnerSpec:
    """One beneficial owner plus the screening outcome to record for them."""

    ownership_pct: float = 100.00
    full_name: str = "Dana Reyes"
    country_code: str = "US"
    date_of_birth: str = "1980-05-05"
    government_id_last4: str = "1234"
    screening: Optional[dict[str, Any]] = None

    def owner_overrides(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "ownership_pct": self.ownership_pct,
            "country_code": self.country_code,
            "date_of_birth": self.date_of_birth,
            "government_id_last4": self.government_id_last4,
        }


@dataclass
class OnboardedMerchant:
    """Everything a test needs after a merchant has been onboarded."""

    application_id: str
    application: dict[str, Any]
    owner_ids: list[str]
    assessment: dict[str, Any]
    merchant_id: str
    merchant: dict[str, Any]
    reserve_account_id: str
    reserve_account: dict[str, Any]
    application_version_at_assessment: int
    captured_alerts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def applicant_headers(self) -> dict[str, str]:
        return make_applicant_headers(self.application_id)

    @property
    def merchant_headers(self) -> dict[str, str]:
        return make_merchant_user_headers(self.merchant_id)


def onboard_merchant(
    api: ApiClient,
    *,
    legal_business_name: str = "Harborline Goods",
    tax_id: Optional[str] = None,
    owners: Optional[Sequence[OwnerSpec]] = None,
    verification: Optional[dict[str, Any]] = None,
    method: str = "LAG_WEIGHTED",
    decision_user_id: str = USER_COMMITTEE_01,
    officer_user_id: str = USER_OFFICER_01,
    **application_overrides: Any,
) -> OnboardedMerchant:
    """Walk an application all the way to an ACTIVE merchant with a reserve account.

    Keyword overrides are applied to the application payload, so the credit
    band, delivery lag, declared chargeback ratio, MCC and requested volume can
    all be steered from a single call.
    """
    owners = list(owners) if owners is not None else [OwnerSpec()]

    payload_overrides = dict(application_overrides)
    payload_overrides["legal_business_name"] = legal_business_name
    if tax_id is not None:
        payload_overrides["tax_id"] = tax_id

    application = create_draft_application(api, **payload_overrides)
    application_id = application["id"]

    owner_ids: list[str] = []
    for spec in owners:
        owner = add_beneficial_owner(api, application_id, **spec.owner_overrides())
        owner_ids.append(owner["id"])

    submit_application(api, application_id)
    record_verification(api, application_id, **(verification or {}))

    for spec, owner_id in zip(owners, owner_ids):
        screen_owner(api, owner_id, **(spec.screening or {}))

    advanced = advance_to_underwriting(api, application_id, officer_user_id)
    version_at_assessment = advanced["version"]
    assessment = create_assessment(
        api, application_id, version_at_assessment, method, officer_user_id
    )
    decided = decide_application(api, application_id, "APPROVE", decision_user_id)

    merchants = get_success_data(
        api.list_onboarded_merchants(application_id, make_risk_committee_headers(decision_user_id))
    )
    assert merchants, "approval did not mint a merchant"
    merchant = merchants[0]
    merchant_id = merchant["id"]

    accounts = get_success_data(
        api.list_merchant_reserve_accounts(merchant_id, make_risk_analyst_headers())
    )
    assert accounts, "approval did not mint a reserve account"
    reserve_account = accounts[0]

    return OnboardedMerchant(
        application_id=application_id,
        application=decided,
        owner_ids=owner_ids,
        assessment=assessment,
        merchant_id=merchant_id,
        merchant=merchant,
        reserve_account_id=reserve_account["id"],
        reserve_account=reserve_account,
        application_version_at_assessment=version_at_assessment,
    )


def onboard_standard_merchant(api: ApiClient, **kwargs: Any) -> OnboardedMerchant:
    """The reference merchant: credit_score 700, zero lag, 24 months of history.

    Resolves to reserve_pct_bps 500, ROLLING, cap 2 000 000 cents.
    """
    set_clock(api, kwargs.pop("clock", CLOCK_EPOCH))
    return onboard_merchant(api, **kwargs)


# ---------------------------------------------------------------------------
# Activity / monitoring
# ---------------------------------------------------------------------------


def ingest_activity(
    api: ApiClient,
    merchant_id: str,
    business_date: str,
    user_id: str = USER_ANALYST_01,
    **overrides: Any,
) -> dict[str, Any]:
    return get_success_data(
        api.create_day_activity(
            day_activity_payload(merchant_id, business_date, **overrides),
            make_risk_analyst_headers(user_id),
        )
    )


def ingest_clean_days(
    api: ApiClient,
    merchant_id: str,
    dates: Sequence[str],
    advance_clock: bool = True,
    **overrides: Any,
) -> list[dict[str, Any]]:
    """Ingest one clean activity row per date, moving the clock to each date first."""
    rows = []
    for business_date in dates:
        if advance_clock:
            set_clock(api, day_start(business_date), make_risk_analyst_headers())
        rows.append(ingest_activity(api, merchant_id, business_date, **overrides))
    return rows


def chargeback_day_overrides(txn_count: int, chargeback_count: int, **extra: Any) -> dict[str, Any]:
    """A trading day whose count-based chargeback ratio is fully determined."""
    overrides: dict[str, Any] = {
        "txn_count": txn_count,
        "chargeback_count": chargeback_count,
        "chargeback_amount_cents": chargeback_count * 1000,
        "chargeback_network": "VISA",
        "decline_count": 5,
        "distinct_card_count": max(txn_count - 100, 1),
        "unique_bin_count": 400,
        "volume_cents": txn_count * 1000,
    }
    overrides.update(extra)
    return overrides


def card_testing_day_overrides(**extra: Any) -> dict[str, Any]:
    """A day that satisfies every card-testing condition at once."""
    overrides: dict[str, Any] = {
        "txn_count": 100,
        "volume_cents": 30_000,
        "decline_count": 70,
        "distinct_card_count": 100,
        "cross_border_count": 0,
        "refund_cents": 0,
        "unique_bin_count": 40,
        "chargeback_count": 0,
        "chargeback_amount_cents": 0,
    }
    overrides.update(extra)
    return overrides


def run_monitoring(
    api: ApiClient, as_of_date: str, user_id: str = USER_ANALYST_01
) -> list[dict[str, Any]]:
    return get_success_data(
        api.create_monitoring_run(as_of_date, make_risk_analyst_headers(user_id))
    )


def review_alert(
    api: ApiClient,
    alert_id: str,
    disposition: str,
    user_id: str = USER_ANALYST_01,
    review_note: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"disposition": disposition}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(
        api.review_alert(alert_id, payload, make_risk_analyst_headers(user_id))
    )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def create_batch(
    api: ApiClient,
    merchant_id: str,
    period_start_date: str,
    period_end_date: str,
    gross_volume_cents: int,
    user_id: str = USER_TREASURY_01,
) -> dict[str, Any]:
    return get_success_data(
        api.create_settlement_batch(
            settlement_batch_payload(
                merchant_id, period_start_date, period_end_date, gross_volume_cents
            ),
            make_portfolio_controller_headers(user_id),
        )
    )


def settle_one_clean_day(
    api: ApiClient,
    merchant_id: str,
    business_date: str,
    gross_volume_cents: int = 1_000_000,
    **activity_overrides: Any,
) -> dict[str, Any]:
    """Ingest a single day of activity at that date and settle exactly that day."""
    set_clock(api, day_start(business_date), make_risk_analyst_headers())
    ingest_activity(api, merchant_id, business_date, **activity_overrides)
    return create_batch(api, merchant_id, business_date, business_date, gross_volume_cents)


def pay_batch(api: ApiClient, batch_id: str, user_id: str = USER_TREASURY_01) -> dict[str, Any]:
    return get_success_data(
        api.pay_settlement_batch(batch_id, make_portfolio_controller_headers(user_id))
    )


def reverse_batch(
    api: ApiClient, batch_id: str, reversal_reason_code: str = "FUNDING_ERROR", user_id: str = USER_TREASURY_01
) -> dict[str, Any]:
    return get_success_data(
        api.reverse_settlement_batch(
            batch_id, reversal_reason_code, make_portfolio_controller_headers(user_id)
        )
    )


def request_release(
    api: ApiClient,
    reserve_account_id: str,
    amount_cents: int,
    tranche_start_date: str,
    tranche_end_date: str,
    expected_reserve_account_version: int,
    user_id: str = USER_TREASURY_01,
) -> dict[str, Any]:
    return get_success_data(
        api.create_release_request(
            reserve_account_id,
            release_request_payload(
                amount_cents, tranche_start_date, tranche_end_date, expected_reserve_account_version
            ),
            make_portfolio_controller_headers(user_id),
        )
    )


# ---------------------------------------------------------------------------
# Remediation / termination / appeal
# ---------------------------------------------------------------------------


def open_program(
    api: ApiClient,
    merchant_id: str,
    window_start_date: str,
    window_end_date: str,
    user_id: str = USER_ANALYST_01,
    **overrides: Any,
) -> dict[str, Any]:
    return get_success_data(
        api.create_remediation_program(
            remediation_program_payload(merchant_id, window_start_date, window_end_date, **overrides),
            make_risk_analyst_headers(user_id),
        )
    )


def activate_program(
    api: ApiClient, program_id: str, user_id: str = USER_COMMITTEE_01
) -> dict[str, Any]:
    return get_success_data(
        api.activate_remediation_program(program_id, make_risk_committee_headers(user_id))
    )


def evaluate_month(
    api: ApiClient, program_id: str, month_index: int, user_id: str = USER_ANALYST_01
) -> dict[str, Any]:
    return get_success_data(
        api.evaluate_remediation_month(program_id, month_index, make_risk_analyst_headers(user_id))
    )


def propose_termination(
    api: ApiClient,
    merchant_id: str,
    reason_code: str = "EXCESSIVE_CHARGEBACKS",
    user_id: str = USER_ANALYST_01,
    **overrides: Any,
) -> dict[str, Any]:
    return get_success_data(
        api.create_termination_decision(
            termination_decision_payload(merchant_id, reason_code, **overrides),
            make_risk_analyst_headers(user_id),
        )
    )


def approve_termination(
    api: ApiClient, decision_id: str, user_id: str = USER_COMMITTEE_01
) -> dict[str, Any]:
    return get_success_data(
        api.approve_termination_decision(decision_id, make_risk_committee_headers(user_id))
    )


def execute_termination(
    api: ApiClient, decision_id: str, user_id: str = USER_TREASURY_01
) -> dict[str, Any]:
    return get_success_data(
        api.execute_termination_decision(decision_id, make_portfolio_controller_headers(user_id))
    )


def terminate_merchant(
    api: ApiClient,
    merchant_id: str,
    reason_code: str = "EXCESSIVE_CHARGEBACKS",
    proposer: str = USER_ANALYST_01,
    approver: str = USER_COMMITTEE_01,
    executor: str = USER_TREASURY_01,
    **overrides: Any,
) -> dict[str, Any]:
    """Propose, approve and execute a termination with three distinct seats."""
    decision = propose_termination(api, merchant_id, reason_code, proposer, **overrides)
    approve_termination(api, decision["id"], approver)
    return execute_termination(api, decision["id"], executor)


def file_appeal(
    api: ApiClient,
    merchant_id: str,
    termination_decision_id: str,
    evidence_summary: Optional[str] = None,
) -> dict[str, Any]:
    payload = appeal_payload(
        merchant_id,
        termination_decision_id,
        **({"evidence_summary": evidence_summary} if evidence_summary else {}),
    )
    return get_success_data(api.create_appeal(payload, make_merchant_user_headers(merchant_id)))


def review_appeal(api: ApiClient, appeal_id: str, user_id: str = USER_COMMITTEE_01) -> dict[str, Any]:
    return get_success_data(api.review_appeal(appeal_id, make_risk_committee_headers(user_id)))


def request_appeal_info(
    api: ApiClient, appeal_id: str, items: Sequence[str], user_id: str = USER_COMMITTEE_01
) -> dict[str, Any]:
    return get_success_data(
        api.request_appeal_info(appeal_id, list(items), make_risk_committee_headers(user_id))
    )


def respond_to_appeal(
    api: ApiClient, appeal_id: str, merchant_id: str, response_text: str = "Documents attached."
) -> dict[str, Any]:
    return get_success_data(
        api.respond_to_appeal_info(appeal_id, response_text, make_merchant_user_headers(merchant_id))
    )


def decide_appeal(
    api: ApiClient,
    appeal_id: str,
    outcome: str,
    user_id: str = USER_COMMITTEE_02,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"outcome": outcome}
    payload.update(extra)
    return get_success_data(
        api.decide_appeal(appeal_id, payload, make_risk_committee_headers(user_id))
    )


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------


def create_forecast(
    api: ApiClient, as_of_date: str, method: str = "EXPECTED_LOSS", **overrides: Any
) -> dict[str, Any]:
    return get_success_data(
        api.create_portfolio_forecast(
            portfolio_forecast_payload(as_of_date, method, **overrides),
            make_portfolio_controller_headers(),
        )
    )


# ---------------------------------------------------------------------------
# Higher-level composites the scenarios reuse
# ---------------------------------------------------------------------------


def merchant_with_open_chargeback_alert(
    api: ApiClient,
    *,
    business_date: str = "2026-08-05",
    txn_count: int = 1000,
    chargeback_count: int = 7,
    **onboard_kwargs: Any,
) -> tuple[OnboardedMerchant, dict[str, Any]]:
    """Onboard a standard merchant and raise one CHARGEBACK_THRESHOLD alert."""
    onboarded = onboard_standard_merchant(api, **onboard_kwargs)
    set_clock(api, day_start(business_date), make_risk_analyst_headers())
    ingest_activity(
        api,
        onboarded.merchant_id,
        business_date,
        **chargeback_day_overrides(txn_count, chargeback_count),
    )
    alerts = run_monitoring(api, business_date)
    assert alerts, "monitoring run raised no alert"
    return onboarded, alerts[0]


def merchant_with_held_reserve(
    api: ApiClient,
    *,
    business_date: str = "2026-08-04",
    gross_volume_cents: int = 1_000_000,
    **onboard_kwargs: Any,
) -> tuple[OnboardedMerchant, dict[str, Any]]:
    """Onboard a standard merchant and settle one clean day so reserve is held."""
    onboarded = onboard_standard_merchant(api, **onboard_kwargs)
    batch = settle_one_clean_day(
        api, onboarded.merchant_id, business_date, gross_volume_cents
    )
    return onboarded, batch


def terminated_merchant_with_decision(
    api: ApiClient,
    *,
    termination_date: str = "2026-08-10",
    reason_code: str = "EXCESSIVE_CHARGEBACKS",
    **onboard_kwargs: Any,
) -> tuple[OnboardedMerchant, dict[str, Any]]:
    """Onboard a standard merchant then terminate it on the given date."""
    onboarded = onboard_standard_merchant(api, **onboard_kwargs)
    set_clock(api, day_start(termination_date), make_risk_analyst_headers())
    decision = terminate_merchant(api, onboarded.merchant_id, reason_code)
    return onboarded, decision


def utc_now_from_response(entity: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(entity["created_at"].replace("Z", "+00:00"))
