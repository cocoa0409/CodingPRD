"""Entity assertions and domain invariant checkers for the Short Sale Negotiation API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApprovalLetterStatus,
    ContributionForm,
    DeficiencyWaiver,
    DisputeStatus,
    DocType,
    DocumentationStatus,
    ExtensionRequestStatus,
    HardshipPackageStatus,
    HardshipReason,
    InvestorType,
    JuniorLienStatus,
    LineBasis,
    LineType,
    MarketingStatus,
    MiClaimStatus,
    NegotiationStatus,
    NetSheetStatus,
    NetSheetVariant,
    OfferStatus,
    SellerDocumentStatus,
    ValuationStatus,
    ValuationType,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_identity_fields(data: dict, entity: str):
    """Every persisted resource carries a bare-UUID `id` and an ISO 8601 UTC
    `created_at` with exactly three fractional-second digits."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )


def assert_audit_fields(data: dict, entity: str):
    """Resources other than the immutable vendor firm also carry `updated_at`
    and an integer `version`."""
    assert_identity_fields(data, entity)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


# ─── Per-entity assertions ────────────────────────────

def assert_case(data: dict):
    assert_audit_fields(data, "ShortSaleCase")
    assert isinstance(data["property_address"], str) and data["property_address"]
    assert isinstance(data["servicer_name"], str) and data["servicer_name"]
    assert data["investor_type"] in _values(InvestorType)
    assert isinstance(data["unpaid_principal_balance_cents"], int)
    assert data["unpaid_principal_balance_cents"] >= 1
    assert data["negotiation_status"] in _values(NegotiationStatus)
    assert data["documentation_status"] in _values(DocumentationStatus)
    assert isinstance(data["junior_contribution_total_cents"], int)
    assert isinstance(data["junior_lien_count"], int)
    assert isinstance(data["failed_offer_count"], int)
    assert isinstance(data["price_reduction_required"], bool)
    assert isinstance(data["deficiency_waiver_permitted"], bool)
    assert isinstance(data["assigned_negotiator_user_id"], str)
    # deficiency_waiver_permitted is exactly "investor is GSE or FHA"
    assert data["deficiency_waiver_permitted"] == (
        data["investor_type"] in ("GSE", "FHA")
    ), "deficiency_waiver_permitted must be true for GSE and FHA and false for PORTFOLIO"


def assert_bpo_vendor(data: dict):
    """A vendor firm is immutable configuration: id and created_at only."""
    assert_identity_fields(data, "BpoVendor")
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["license_state"], str)
    assert isinstance(data["daily_inspection_capacity"], int)
    assert data["daily_inspection_capacity"] >= 1
    assert "updated_at" not in data, "a vendor firm carries no updated_at"
    assert "version" not in data, "a vendor firm carries no version"


def assert_hardship_package(data: dict):
    assert_audit_fields(data, "HardshipPackage")
    assert is_valid_uuid(data["case_id"])
    assert data["hardship_reason"] in _values(HardshipReason)
    assert data["status"] in _values(HardshipPackageStatus)
    assert isinstance(data["monthly_income_cents"], int) and data["monthly_income_cents"] >= 1
    assert isinstance(data["monthly_expenses_cents"], int) and data["monthly_expenses_cents"] >= 1
    assert isinstance(data["liquid_assets_cents"], int) and data["liquid_assets_cents"] >= 0
    for counter in (
        "document_count",
        "pending_document_count",
        "verified_document_count",
        "rejected_document_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must be non-negative"
    assert_package_counter_partition(data)


def assert_package_counter_partition(data: dict):
    """The three review buckets always partition document_count."""
    total = (
        data["pending_document_count"]
        + data["verified_document_count"]
        + data["rejected_document_count"]
    )
    assert total == data["document_count"], (
        "pending + verified + rejected must equal document_count, got "
        f"{data['pending_document_count']} + {data['verified_document_count']} + "
        f"{data['rejected_document_count']} != {data['document_count']}"
    )


def assert_seller_document(data: dict):
    assert_audit_fields(data, "SellerDocument")
    assert is_valid_uuid(data["package_id"])
    assert data["doc_type"] in _values(DocType)
    assert data["status"] in _values(SellerDocumentStatus)
    assert is_iso8601_timestamp(data["issued_on"])
    assert isinstance(data["reference_label"], str)


def assert_listing(data: dict):
    assert_audit_fields(data, "Listing")
    assert is_valid_uuid(data["case_id"])
    assert data["marketing_status"] in _values(MarketingStatus)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 1
    assert 0 < data["commission_pct"] <= 0.10, (
        "commission_pct must be strictly above 0 and no greater than 0.10"
    )
    assert is_iso8601_timestamp(data["listed_at"])
    assert isinstance(data["days_on_market"], int) and data["days_on_market"] >= 0
    assert isinstance(data["price_reduction_count"], int)


def assert_offer(data: dict):
    assert_audit_fields(data, "Offer")
    assert is_valid_uuid(data["case_id"])
    assert data["status"] in _values(OfferStatus)
    assert isinstance(data["offer_price_cents"], int) and data["offer_price_cents"] >= 1
    assert isinstance(data["earnest_money_cents"], int) and data["earnest_money_cents"] >= 0
    assert isinstance(data["requested_closing_days"], int)
    assert data["requested_closing_days"] >= 1
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1


def assert_net_sheet(data: dict):
    assert_audit_fields(data, "NetSheet")
    assert is_valid_uuid(data["offer_id"])
    assert data["variant"] in _values(NetSheetVariant)
    assert data["status"] in _values(NetSheetStatus)
    assert isinstance(data["gross_deductions_cents"], int)
    assert isinstance(data["mi_contribution_credit_cents"], int)
    assert isinstance(data["base_net_cents"], int)
    assert isinstance(data["relocation_incentive_cents"], int)
    assert isinstance(data["net_proceeds_cents"], int)
    assert_net_sheet_line_items(data)
    assert_net_sheet_arithmetic(data)


NET_SHEET_LINE_ORDER = [
    LineType.COMMISSION.value,
    LineType.TITLE_AND_ESCROW.value,
    LineType.TRANSFER_TAX.value,
    LineType.PROPERTY_TAX_ARREARS.value,
    LineType.HOA_ARREARS.value,
    LineType.JUNIOR_LIEN_PAYOFF.value,
]


def assert_net_sheet_line_items(data: dict):
    """Six deduction lines, in the order the settlement waterfall fixes."""
    lines = data["line_items"]
    assert isinstance(lines, list), "line_items must be an array"
    assert len(lines) == 6, f"expected 6 deduction lines, got {len(lines)}"
    for index, expected_type in enumerate(NET_SHEET_LINE_ORDER):
        line = lines[index]
        assert line["line_type"] == expected_type, (
            f"line {index + 1} must be {expected_type}, got {line['line_type']}"
        )
        assert line["basis"] in _values(LineBasis)
        assert isinstance(line["amount_cents"], int), (
            f"{expected_type}.amount_cents must be a whole-cent integer"
        )
        assert "rate_or_amount" in line, f"{expected_type} must record rate_or_amount"


def assert_net_sheet_arithmetic(data: dict):
    """gross_deductions is the sum of the six already-rounded lines; the net is
    the base net less the relocation incentive."""
    line_sum = sum(line["amount_cents"] for line in data["line_items"])
    assert data["gross_deductions_cents"] == line_sum, (
        f"gross_deductions_cents {data['gross_deductions_cents']} must equal the sum "
        f"of the six already-rounded lines {line_sum}"
    )
    assert data["net_proceeds_cents"] == (
        data["base_net_cents"] - data["relocation_incentive_cents"]
    ), "net_proceeds_cents must be base_net_cents less relocation_incentive_cents"
    assert data["relocation_incentive_cents"] in (100_000, 200_000, 300_000), (
        "every sheet falls in one of the three relocation tiers"
    )


def assert_valuation(data: dict):
    assert_audit_fields(data, "Valuation")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert data["valuation_type"] in _values(ValuationType)
    assert data["status"] in _values(ValuationStatus)
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["inspection_start"])
    assert is_iso8601_timestamp(data["inspection_end"])
    assert data["inspection_end"] > data["inspection_start"], (
        "inspection_end must fall strictly after inspection_start"
    )
    assert isinstance(data["ordered_by_user_id"], str)


def assert_valuation_dispute(data: dict):
    assert_audit_fields(data, "ValuationDispute")
    assert is_valid_uuid(data["valuation_id"])
    assert data["status"] in _values(DisputeStatus)
    assert isinstance(data["claimed_value_cents"], int) and data["claimed_value_cents"] >= 1
    assert isinstance(data["comparable_count"], int) and data["comparable_count"] >= 0
    assert isinstance(data["rationale"], str)
    assert isinstance(data["filed_by_user_id"], str)
    assert isinstance(data["variance_pct"], (int, float))


def assert_junior_lien(data: dict):
    assert_audit_fields(data, "JuniorLien")
    assert is_valid_uuid(data["case_id"])
    assert data["status"] in _values(JuniorLienStatus)
    assert isinstance(data["lien_position"], int) and data["lien_position"] >= 2
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 1
    assert isinstance(data["approved_contribution_cents"], int)
    assert data["approved_contribution_cents"] <= data["balance_cents"], (
        "an approved contribution may never exceed the lien's outstanding balance"
    )
    if data.get("demand_cents") is not None:
        assert data["demand_cents"] <= data["balance_cents"], (
            "a demanded payoff may never exceed the lien's outstanding balance"
        )


def assert_mi_claim(data: dict):
    assert_audit_fields(data, "MiClaim")
    assert is_valid_uuid(data["case_id"])
    assert data["status"] in _values(MiClaimStatus)
    assert data["contribution_form"] in _values(ContributionForm)
    assert isinstance(data["mi_provider"], str)
    assert isinstance(data["claim_reference"], str)
    assert 0 <= data["coverage_pct"] <= 1
    assert isinstance(data["required_contribution_cents"], int)
    assert data["required_contribution_cents"] >= 0


def assert_approval_letter(data: dict):
    assert_audit_fields(data, "ApprovalLetter")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["offer_id"])
    assert data["status"] in _values(ApprovalLetterStatus)
    assert data["deficiency_waiver"] in _values(DeficiencyWaiver)
    assert isinstance(data["approved_net_proceeds_cents"], int)
    assert data["approved_net_proceeds_cents"] >= 0
    assert 0 < data["commission_cap_pct"] <= 0.055, (
        "commission_cap_pct must be strictly above 0 and no greater than 0.055"
    )
    assert isinstance(data["seller_relocation_incentive_cents"], int)
    assert isinstance(data["conditions"], list)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["closing_deadline"])
    assert isinstance(data["cumulative_extension_days_used"], int)
    assert data["cumulative_extension_days_used"] >= 0
    assert isinstance(data["issued_by_user_id"], str)


def assert_extension_request(data: dict):
    assert_audit_fields(data, "ExtensionRequest")
    assert is_valid_uuid(data["approval_letter_id"])
    assert data["status"] in _values(ExtensionRequestStatus)
    assert isinstance(data["requested_days"], int) and data["requested_days"] >= 1
    assert isinstance(data["reason"], str)
    assert isinstance(data["requested_by_user_id"], str)


# ─── Cross-record invariants ──────────────────────────

def assert_junior_ledger_matches(case: dict, liens: list):
    """The case's junior-contribution ledger is exactly the sum of
    approved_contribution_cents over the liens on that case that are APPROVED."""
    expected = sum(
        lien["approved_contribution_cents"]
        for lien in liens
        if lien["status"] == JuniorLienStatus.APPROVED.value
    )
    assert case["junior_contribution_total_cents"] == expected, (
        f"junior_contribution_total_cents {case['junior_contribution_total_cents']} must "
        f"equal the sum over APPROVED liens {expected}"
    )
    assert case["junior_lien_count"] == len(liens), (
        f"junior_lien_count {case['junior_lien_count']} must equal the number of liens "
        f"on the case {len(liens)}"
    )
