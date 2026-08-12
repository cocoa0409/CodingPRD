"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    """Common fields per PRD §2.4: id (UUID), created_at/updated_at, version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_captive(data: dict):
    _assert_common_fields(data, "CaptiveEntity")
    assert isinstance(data.get("captive_name"), str) and data["captive_name"]
    assert data.get("domicile_jurisdiction") in ["VERMONT", "BERMUDA", "CAYMAN", "GUERNSEY", "LUXEMBOURG"]
    assert data.get("status") in [
        "FORMATION_PENDING", "DOMICILE_FILED", "CAPITALIZED", "ACTIVE", "SUSPENDED", "DISSOLVED",
    ]
    assert data.get("solvency_status") in ["ADEQUATE", "WARNING", "BREACH"]
    assert data.get("tax_classification") in ["MICRO_CAPTIVE_831B", "STANDARD_831A", "NON_ELECTING"]


def assert_domicile_filing(data: dict):
    _assert_common_fields(data, "DomicileFiling")
    assert data.get("filing_type") in ["INITIAL_FORMATION", "ANNUAL_RENEWAL", "AMENDMENT", "REDOMESTICATION"]
    assert data.get("jurisdiction") in ["VERMONT", "BERMUDA", "CAYMAN", "GUERNSEY", "LUXEMBOURG"]
    assert data.get("status") in ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN"]


def assert_program(data: dict):
    _assert_common_fields(data, "InsuranceProgram")
    assert data.get("line_of_business") in [
        "GENERAL_LIABILITY", "WORKERS_COMP", "PROPERTY", "PROFESSIONAL_LIABILITY", "CYBER", "D_AND_O",
    ]
    assert data.get("program_status") in [
        "DRAFT", "QUOTED", "BOUND", "IN_FORCE", "RUN_OFF", "CLOSED", "CANCELLED",
    ]
    assert data.get("coverage_status") in ["UNBOUND", "BOUND", "EXPIRED"]


def assert_fronting(data: dict):
    _assert_common_fields(data, "FrontingArrangement")
    assert data.get("status") in [
        "NEGOTIATING", "TERMS_AGREED", "COLLATERAL_POSTED", "ACTIVE", "EXPIRED", "TERMINATED",
    ]


def assert_collateral(data: dict):
    _assert_common_fields(data, "CollateralPosting")
    assert data.get("collateral_type") in [
        "LETTER_OF_CREDIT", "TRUST_ACCOUNT", "SURETY_BOND", "CASH_ESCROW", "INVESTMENT_SECURITIES",
    ]
    assert data.get("verification_status") in ["PENDING_VERIFICATION", "VERIFIED", "RELEASED", "EXPIRED"]


def assert_operating_unit(data: dict):
    _assert_common_fields(data, "OperatingUnit")
    assert data.get("exposure_basis") in ["REVENUE", "HEADCOUNT", "PAYROLL", "ASSET_VALUE", "SQUARE_FOOTAGE"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED", "DECOMMISSIONED"]


def assert_allocation(data: dict):
    _assert_common_fields(data, "PremiumAllocation")
    assert data.get("allocation_method") in ["EXPOSURE_PRO_RATA", "EQUAL_SHARE", "MANUAL", "RISK_WEIGHTED"]
    assert data.get("status") in ["PROVISIONAL", "AUDITED", "FINALIZED", "DISPUTED", "CANCELLED"]


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert data.get("claim_status") in [
        "REPORTED", "ACKNOWLEDGED", "UNDER_INVESTIGATION", "RESERVED",
        "SETTLED", "DENIED", "CLOSED_WITHOUT_PAYMENT",
    ]
    assert data.get("payment_status") in ["UNPAID", "PARTIALLY_PAID", "FULLY_PAID"]
    assert data.get("litigation_status") in ["NOT_LITIGATED", "LITIGATED", "SETTLED_IN_LITIGATION"]


def assert_tpa(data: dict):
    _assert_common_fields(data, "TPAAssignment")
    assert data.get("fee_structure") in ["FLAT_FEE", "PER_CLAIM", "PERCENTAGE_OF_SAVINGS"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED", "REINSTATED", "TERMINATED"]


def assert_reserve(data: dict):
    _assert_common_fields(data, "ActuarialReserve")
    assert data.get("reserve_type") in ["CASE_RESERVE", "IBNR_RESERVE", "LAE_RESERVE", "UNALLOCATED_EXPENSE"]
    assert data.get("actuarial_method") in [
        "CHAIN_LADDER", "BORNHUETTER_FERGUSON", "EXPECTED_LOSS_RATIO", "BERQUIST_SHERMAN",
    ]
    assert data.get("status") in ["PRELIMINARY", "REVIEWED", "CERTIFIED", "FILED", "SUPERSEDED"]


def assert_annual_statement(data: dict):
    _assert_common_fields(data, "AnnualStatement")
    assert isinstance(data.get("statement_year"), int)
    assert data.get("status") in ["DRAFT", "ACTUARIAL_REVIEW", "BOARD_APPROVED", "FILED", "AMENDED"]


def assert_board_meeting(data: dict):
    _assert_common_fields(data, "BoardMeeting")
    assert data.get("meeting_type") in ["ANNUAL", "QUARTERLY", "SPECIAL", "EMERGENCY"]
    assert data.get("status") in [
        "SCHEDULED", "IN_SESSION", "MINUTES_DRAFTED", "MINUTES_APPROVED", "FILED", "CANCELLED",
    ]


def assert_tax_position(data: dict):
    _assert_common_fields(data, "TaxPosition")
    assert data.get("position_type") in [
        "PREMIUM_DEDUCTIBILITY", "RISK_DISTRIBUTION", "MICRO_CAPTIVE_ELECTION",
        "ARM_LENGTH_PRICING", "EXCISE_TAX_EXEMPTION",
    ]
    assert data.get("status") in ["DRAFT", "ANALYZED", "OPINION_ISSUED", "FILED", "CHALLENGED"]


def assert_audit_log(data: dict):
    """Append-only log: id + created_at only; no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "AuditLog.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "AuditLog.created_at must be ISO 8601"
    assert "updated_at" not in data, "AuditLog must not carry updated_at"
    assert "version" not in data, "AuditLog must not carry version"
    assert data.get("action_type") in [
        "STATE_CHANGE", "CALCULATION_RUN", "FILING_SUBMITTED",
        "CERTIFICATION", "GOVERNANCE_ACTION", "TAX_POSITION_CHANGE",
    ]
