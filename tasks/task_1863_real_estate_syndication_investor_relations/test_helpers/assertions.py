"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_TS3_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_timestamp_ms3(value: str):
    """ISO 8601 UTC timestamp rendered with three fractional digits (PRD §2.4)."""
    assert isinstance(value, str), f"timestamp must be a string, got {type(value)}"
    assert _TS3_RE.match(value), (
        f"timestamp {value!r} is not ISO 8601 UTC with three fractional digits")


def _assert_common_full(data: dict, entity: str):
    """Common fields for full-lifecycle resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_common_light(data: dict, entity: str):
    """Common fields for the lighter resources: only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"


def _assert_money(data: dict, field: str, entity: str):
    assert isinstance(data.get(field), int), \
        f"{entity}.{field} must be integer cents, got {data.get(field)!r}"


def assert_syndication(data: dict):
    _assert_common_full(data, "Syndication")
    assert isinstance(data["syndication_name"], str) and data["syndication_name"]
    assert isinstance(data["sponsor_legal_entity"], str)
    assert isinstance(data["preferred_return_pct_annual"], (int, float))
    assert isinstance(data["carried_interest_pct"], (int, float))
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")


def assert_investor(data: dict):
    _assert_common_full(data, "Investor")
    assert isinstance(data["full_legal_name"], str) and data["full_legal_name"]
    assert isinstance(data["tax_id_last4"], str)
    assert isinstance(data["email"], str)
    assert data["investor_class"] in ("ACCREDITED", "QUALIFIED_PURCHASER",
                                      "NON_ACCREDITED")
    assert data["portal_access_status"] in ("INVITED", "ACTIVE", "SUSPENDED", "REVOKED")


def assert_property(data: dict):
    _assert_common_full(data, "Property")
    assert isinstance(data["property_legal_name"], str)
    assert isinstance(data["street_address"], str)
    _assert_money(data, "acquisition_price_cents", "Property")
    assert data["status"] in ("OWNED", "UNDER_CONTRACT_TO_SELL", "SOLD")


def assert_offering(data: dict):
    _assert_common_full(data, "Offering")
    assert is_valid_uuid(data.get("syndication_id", ""))
    assert is_valid_uuid(data.get("property_id", ""))
    assert isinstance(data["offering_name"], str)
    for f in ("target_raise_cents", "min_subscription_cents", "max_non_accredited_count",
              "total_committed_cents", "total_funded_cents", "total_distributed_cents",
              "unreturned_capital_cents"):
        _assert_money(data, f, "Offering")
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED_TO_NEW_SUBSCRIPTIONS",
                              "FINAL_CLOSE", "DISSOLVED")


def assert_subscription(data: dict):
    _assert_common_full(data, "Subscription")
    assert is_valid_uuid(data.get("offering_id", ""))
    assert is_valid_uuid(data.get("investor_id", ""))
    for f in ("committed_cents", "funded_cents", "unreturned_capital_cents",
              "accrued_pref_cents"):
        _assert_money(data, f, "Subscription")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCREDITATION_VERIFIED",
                              "SUITABILITY_APPROVED", "AWAITING_FUNDING", "FUNDED",
                              "SUITABILITY_REJECTED", "WITHDRAWN")


def assert_subscription_document(data: dict):
    _assert_common_light(data, "SubscriptionDocument")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert data["doc_type"] in ("SUBSCRIPTION_AGREEMENT", "W9", "ACCREDITATION_LETTER",
                                "ID_PROOF", "SUITABILITY_QUESTIONNAIRE")
    assert isinstance(data["file_uri"], str)
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert data["review_status"] in ("PENDING_REVIEW", "ACCEPTED", "REJECTED")


def assert_capital_call(data: dict):
    _assert_common_full(data, "CapitalCall")
    assert is_valid_uuid(data.get("offering_id", ""))
    _assert_money(data, "total_call_cents", "CapitalCall")
    _assert_money(data, "escrow_released_cents", "CapitalCall")
    assert data["status"] in ("DRAFT", "ISSUED", "PARTIALLY_FUNDED", "FULLY_FUNDED",
                              "CANCELLED")


def assert_contribution(data: dict):
    _assert_common_full(data, "CapitalCallContribution")
    assert is_valid_uuid(data.get("capital_call_id", ""))
    assert is_valid_uuid(data.get("subscription_id", ""))
    _assert_money(data, "amount_due_cents", "CapitalCallContribution")
    _assert_money(data, "amount_received_cents", "CapitalCallContribution")
    assert data["status"] in ("PENDING", "ESCROW_RECEIVED", "RELEASED", "DEFAULTED")


def assert_quarterly_report(data: dict):
    _assert_common_full(data, "QuarterlyReport")
    assert is_valid_uuid(data.get("offering_id", ""))
    assert isinstance(data["report_year"], int)
    assert data["report_quarter"] in (1, 2, 3, 4)
    _assert_money(data, "noi_cents", "QuarterlyReport")
    assert data["status"] in ("DRAFT", "PUBLISHED", "AMENDED")


def assert_distribution(data: dict):
    _assert_common_full(data, "Distribution")
    assert is_valid_uuid(data.get("offering_id", ""))
    assert data["distribution_kind"] in ("QUARTERLY_OPERATING", "CAPITAL_EVENT")
    _assert_money(data, "total_distributable_cents", "Distribution")
    assert data["status"] in ("DRAFT", "CALCULATED", "APPROVED", "PAID", "CANCELLED")


def assert_distribution_line(data: dict):
    _assert_common_light(data, "DistributionLine")
    assert is_valid_uuid(data.get("distribution_id", ""))
    for f in ("return_of_capital_cents", "preferred_return_cents",
              "profit_split_lp_cents", "profit_split_gp_cents", "total_cents"):
        _assert_money(data, f, "DistributionLine")


def assert_capital_event(data: dict):
    _assert_common_full(data, "CapitalEvent")
    assert is_valid_uuid(data.get("property_id", ""))
    assert data["event_kind"] in ("REFINANCE", "SALE")
    _assert_money(data, "gross_proceeds_cents", "CapitalEvent")
    _assert_money(data, "debt_payoff_cents", "CapitalEvent")
    assert data["status"] in ("ANNOUNCED", "EXECUTED", "DISTRIBUTED", "CANCELLED")


def assert_k1_package(data: dict):
    _assert_common_full(data, "K1Package")
    assert is_valid_uuid(data.get("offering_id", ""))
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["preparer_firm"], str)
    assert data["status"] in ("PREPARATION", "PARTNER_REVIEW", "FINALIZED", "DELIVERED")


def assert_transfer_request(data: dict):
    _assert_common_full(data, "TransferRequest")
    assert is_valid_uuid(data.get("from_subscription_id", ""))
    assert is_valid_uuid(data.get("to_investor_id", ""))
    _assert_money(data, "transfer_cents", "TransferRequest")
    assert data["status"] in ("PENDING_SPONSOR_REVIEW", "PENDING_TRANSFER_AGENT",
                              "APPROVED", "SETTLED", "REJECTED", "CANCELLED")


def assert_portal_session(data: dict):
    _assert_common_light(data, "InvestorPortalSession")
    assert is_valid_uuid(data.get("investor_id", ""))
    assert isinstance(data["session_token"], str) and data["session_token"]
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_line_totals_consistent(line: dict):
    """Each line's total equals the sum of its four components (PRD §3.5)."""
    assert line["total_cents"] == (
        line["return_of_capital_cents"] + line["preferred_return_cents"]
        + line["profit_split_lp_cents"] + line["profit_split_gp_cents"]), (
        f"line total {line['total_cents']} != sum of components")
