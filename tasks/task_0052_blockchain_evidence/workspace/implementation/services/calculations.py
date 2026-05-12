"""Fee calculation rules (scaffold §1.3 / PRD §3)."""
from decimal import Decimal, ROUND_HALF_UP


BASE_FEE_BY_TYPE = {
    "DOCUMENT": 200,
    "IMAGE": 300,
    "VIDEO": 800,
    "CODE_REPOSITORY": 500,
    "DATASET": 1000,
}

PERIOD_MULTIPLIER = {
    30: Decimal("1.00"),
    90: Decimal("2.50"),
    365: Decimal("8.00"),
    1095: Decimal("20.00"),
}

AUTHORITY_MULT = {
    "COURT_BJ": Decimal("1.20"),
    "COURT_SH": Decimal("1.20"),
    "COURT_GZ": Decimal("1.10"),
    "COURT_SZ": Decimal("1.10"),
    "PROCURATORATE": Decimal("1.00"),
    "ARBITRATION": Decimal("0.90"),
}

CHAIN_CONFIRMATION_THRESHOLD = {
    "ETHEREUM": 12,
    "FABRIC": 1,
    "BSN": 5,
    "COSMOS": 6,
}


def round_half_up(value: Decimal) -> int:
    """Half-up rounding to nearest cent (integer cents)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def per_evidence_line_cents(evidence: dict) -> int:
    """Compute the per-line cents for a single evidence (used in both
    single-evidence and per-line batch math)."""
    base = BASE_FEE_BY_TYPE[evidence["evidence_type"]]
    mult = PERIOD_MULTIPLIER[evidence["storage_period_days"]]
    surcharge = 50 if evidence.get("original_data_b64") is not None else 0
    raw = Decimal(base) * mult + Decimal(surcharge)
    return round_half_up(raw)


def preservation_fee_quote(evidence: dict) -> int:
    """Forward-looking preservation fee quote (matches final fee for single-evidence path)."""
    return per_evidence_line_cents(evidence)


def preservation_fee_final(evidence: dict) -> int:
    """Chronological actual preservation fee debit at CONFIRMED."""
    return per_evidence_line_cents(evidence)


def _batch_discount_rate(count: int) -> Decimal:
    if count >= 100:
        return Decimal("0.20")
    if count >= 50:
        return Decimal("0.15")
    if count >= 10:
        return Decimal("0.10")
    if count >= 2:
        return Decimal("0.05")
    return Decimal("0.00")


def batch_fee_final(members: list) -> int:
    """Round-per-line then sum, then apply discount, then round once more.

    `members` is an ordered list of evidence dicts (submission order).
    """
    subtotal = 0
    for ev in members:
        subtotal += per_evidence_line_cents(ev)
    rate = _batch_discount_rate(len(members))
    discounted = Decimal(subtotal) * (Decimal("1") - rate)
    return round_half_up(discounted)


def batch_fee_quote(members: list) -> int:
    """Forward-looking quote — same algorithm as final (already includes discount)."""
    return batch_fee_final(members)


def judicial_surcharge_quote(include_original_data: bool, authority_code: str) -> int:
    base = Decimal("5000")
    uplift = Decimal("1500") if include_original_data else Decimal("0")
    mult = AUTHORITY_MULT[authority_code]
    return round_half_up((base + uplift) * mult)


def judicial_surcharge_final(include_original_data: bool, authority_code: str) -> int:
    return judicial_surcharge_quote(include_original_data, authority_code)
