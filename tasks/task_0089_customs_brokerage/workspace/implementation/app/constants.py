"""Calculation constants and lookup tables (scaffold §1.3, PRD §3.8 / §3.9)."""
from __future__ import annotations

from decimal import Decimal


CURRENCIES = {"USD", "EUR", "CNY", "JPY", "GBP"}
JURISDICTIONS = {"CN", "US", "EU", "JP", "GB"}
SCOPE_CODES = {"DECLARATION", "INSPECTION", "TARIFF_ADVANCE", "RETURN_SHIP", "AMENDMENT"}
TRADE_AGREEMENTS = {"NONE", "RCEP", "USMCA", "EU_GSP", "CPTPP"}
DOC_TYPES = {
    "COMMERCIAL_INVOICE",
    "PACKING_LIST",
    "BILL_OF_LADING",
    "CONTRACT",
    "IMPORT_LICENSE",
    "INSPECTION_CERT",
    "DANGEROUS_GOODS_DECL",
}
CORE_DOC_TYPES = {"COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING", "CONTRACT"}
TERMINATED_REASONS = {"CLIENT_REQUEST", "BREACH", "REGULATORY"}
REJECTION_REASONS = {
    "HS_MISMATCH",
    "VALUE_UNDERSTATED",
    "MISSING_LICENSE",
    "INSPECTION_FAILED",
    "MANIFEST_MISMATCH",
    "OTHER",
}
INSPECTION_OUTCOMES = {"RELEASE", "DETENTION", "PENALTY"}

# Declaration status sets
DECLARATION_NON_TERMINAL = {
    "DRAFT",
    "DOCS_PENDING",
    "PRE_VALIDATED",
    "FILED",
    "QUERIED",
    "INSPECTING",
    "AMENDING",
}
DECLARATION_TERMINAL = {"RELEASED", "WITHDRAWN", "REJECTED"}


MFN_RATE_TABLE: dict[str, dict[str, Decimal]] = {
    "CN": {"default": Decimal("0.10"), "8517": Decimal("0.05")},
    "US": {"default": Decimal("0.08"), "8517": Decimal("0.04")},
    "EU": {"default": Decimal("0.12"), "8517": Decimal("0.06")},
    "JP": {"default": Decimal("0.09"), "8517": Decimal("0.045")},
    "GB": {"default": Decimal("0.10"), "8517": Decimal("0.05")},
}

FTA_RATE_TABLE: dict[str, dict[str, dict[str, Decimal]]] = {
    "RCEP": {
        "CN": {"default": Decimal("0.05"), "8517": Decimal("0.02")},
        "JP": {"default": Decimal("0.04"), "8517": Decimal("0.02")},
    },
    "USMCA": {
        "US": {"default": Decimal("0.03"), "8517": Decimal("0.015")},
    },
    "EU_GSP": {
        "EU": {"default": Decimal("0.06"), "8517": Decimal("0.03")},
    },
    "CPTPP": {
        "JP": {"default": Decimal("0.035"), "8517": Decimal("0.015")},
    },
}

VAT_RATE_TABLE: dict[str, Decimal] = {
    "CN": Decimal("0.13"),
    "US": Decimal("0.00"),
    "EU": Decimal("0.21"),
    "JP": Decimal("0.10"),
    "GB": Decimal("0.20"),
}

# (jurisdiction, hs_first_4) -> rate
CONSUMPTION_TAX_TABLE: dict[tuple[str, str], Decimal] = {
    ("CN", "2208"): Decimal("0.20"),
    ("JP", "2208"): Decimal("0.15"),
    ("US", "2402"): Decimal("0.30"),
    ("GB", "2402"): Decimal("0.25"),
}

# (jurisdiction, hs_first_4) -> ref_price (in settlement-currency units)
REFERENCE_PRICE_TABLE: dict[tuple[str, str], Decimal] = {
    ("CN", "8517"): Decimal("800.00"),
    ("US", "8517"): Decimal("800.00"),
    ("EU", "8517"): Decimal("800.00"),
    ("JP", "8517"): Decimal("800.00"),
    ("GB", "8517"): Decimal("800.00"),
    ("CN", "2208"): Decimal("50.00"),
}

# Agreement-currency -> declared-currency FX
AGREEMENT_FX_TABLE: dict[tuple[str, str], Decimal] = {
    ("USD", "USD"): Decimal("1.00"),
    ("USD", "CNY"): Decimal("7.20"),
    ("USD", "EUR"): Decimal("0.92"),
    ("USD", "JPY"): Decimal("150.0"),
    ("USD", "GBP"): Decimal("0.78"),
    ("CNY", "CNY"): Decimal("1.00"),
    ("CNY", "USD"): Decimal("0.139"),
    ("EUR", "EUR"): Decimal("1.00"),
    ("EUR", "USD"): Decimal("1.08"),
    ("JPY", "JPY"): Decimal("1.00"),
    ("JPY", "USD"): Decimal("0.0067"),
    ("GBP", "GBP"): Decimal("1.00"),
    ("GBP", "USD"): Decimal("1.28"),
}

# Default settlement_currency<->declared_currency FX rate, identity if equal.
# For convenience we use 1.0 when currencies match; otherwise apply a sentinel rate.
# In a real system this would be a live FX feed; for testing we hardcode 1.0.
DECLARED_TO_SETTLEMENT_FX: dict[tuple[str, str], Decimal] = {
    # identity pairs — fx_rate_to_settlement = 1.0 always
}


def declared_to_settlement_rate(declared: str, settlement: str) -> Decimal:
    """Snapshot rate for declared->settlement currency conversion at PRE_VALIDATED.
    When currencies match, the rate is 1.0. Otherwise, this implementation falls back
    to deriving via AGREEMENT_FX_TABLE (declared->USD->settlement) to keep deterministic
    behaviour for tests.
    """
    if declared == settlement:
        return Decimal("1")
    # Try direct lookup
    if (declared, settlement) in AGREEMENT_FX_TABLE:
        return AGREEMENT_FX_TABLE[(declared, settlement)]
    # Pivot via USD
    leg1 = AGREEMENT_FX_TABLE.get((declared, "USD"))
    leg2 = AGREEMENT_FX_TABLE.get(("USD", settlement))
    if leg1 is not None and leg2 is not None:
        return leg1 * leg2
    return Decimal("1")
