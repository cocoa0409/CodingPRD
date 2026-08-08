"""Calculation rules: increment capture, interest, surplus determination & split."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

ADMIN_FEE_RATE = Decimal("0.03")


def round_half_up(value: Decimal) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(x) -> Decimal:
    """Decimal from a possibly-float value, preserving input precision via str."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# increment_capture
# ---------------------------------------------------------------------------
def increment_capture(current_eav_cents, base_eav_cents, agg_rate_dec, collection_rate=None):
    incremental = max(0, current_eav_cents - base_eav_cents)
    gross_base = Decimal(incremental) * agg_rate_dec
    if collection_rate is not None:
        gross_base = gross_base * dec(collection_rate)
    gross = round_half_up(gross_base)
    admin_fee = round_half_up(ADMIN_FEE_RATE * Decimal(gross))
    captured = gross - admin_fee
    return {
        "incremental_eav_cents": incremental,
        "gross_increment_cents": gross,
        "admin_fee_cents": admin_fee,
        "captured_increment_cents": captured,
    }


# ---------------------------------------------------------------------------
# interest accrual
# ---------------------------------------------------------------------------
def accrue_interest(principal_remaining_cents, interest_rate_bps):
    return round_half_up(Decimal(principal_remaining_cents) * Decimal(interest_rate_bps) / Decimal(10000))


# ---------------------------------------------------------------------------
# annual surplus determination
# ---------------------------------------------------------------------------
def per_year_amortization(principal_cents, issue_tax_year, final_maturity_tax_year):
    term = final_maturity_tax_year - issue_tax_year + 1
    if term <= 0:
        term = 1
    return round_half_up(Decimal(principal_cents) / Decimal(term))


def obligation_reserve(senior_obligations, basis):
    """senior_obligations: list of REGISTERED SENIOR obligation dicts."""
    if basis == "NET":
        return sum(o["outstanding_balance_cents"] for o in senior_obligations)
    # GROSS: near-term debt service
    total = 0
    for o in senior_obligations:
        amort = per_year_amortization(
            o["principal_cents"], o["issue_tax_year"], o["final_maturity_tax_year"]
        )
        total += o["accrued_interest_cents"] + min(o["principal_remaining_cents"], amort)
    return total


# ---------------------------------------------------------------------------
# surplus_taxing_body_split (largest-remainder / Hamilton)
# ---------------------------------------------------------------------------
def surplus_split(bodies, agreements, report_tax_year, S):
    """bodies: taxing body dicts ordered created_at ASC (with _seq).
    agreements: all SurplusAgreement dicts for the district.
    Returns list of dicts {body, share_ppm, amount_cents} in body order.
    Reconciles exactly to S.
    """
    # Determine override set for this report_tax_year (half-open window).
    override = {}
    for b in bodies:
        for ag in agreements:
            if ag["taxing_body_id"] == b["id"] and \
                    ag["start_tax_year"] <= report_tax_year < ag["end_tax_year"]:
                override[b["id"]] = ag["surplus_share_ppm_override"]
                break

    override_weight_sum = sum(
        Decimal(ppm) / Decimal(1000000) for ppm in override.values()
    ) if override else Decimal(0)
    residual = Decimal(1) - override_weight_sum
    rate_sum_non = sum(
        dec(b["tax_rate"]) for b in bodies if b["id"] not in override
    )

    entries = []
    for b in bodies:
        if b["id"] in override:
            w = Decimal(override[b["id"]]) / Decimal(1000000)
        elif rate_sum_non > 0:
            w = residual * (dec(b["tax_rate"]) / rate_sum_non)
        else:
            w = Decimal(0)
        share_ppm = round_half_up(w * Decimal(1000000))
        exact = Decimal(S) * w
        floor_val = int(exact.to_integral_value(rounding=ROUND_FLOOR))
        frac = exact - Decimal(floor_val)
        entries.append({
            "body": b,
            "share_ppm": share_ppm,
            "floor": floor_val,
            "frac": frac,
        })

    sum_floor = sum(e["floor"] for e in entries)
    remainder = S - sum_floor  # whole cents to hand out

    # Rank by fractional part DESC, tie-break created_at ASC (_seq).
    ranked = sorted(
        range(len(entries)),
        key=lambda i: (-entries[i]["frac"], entries[i]["body"].get("_seq", 0)),
    )
    getters = set(ranked[:remainder]) if remainder > 0 else set()

    result = []
    for i, e in enumerate(entries):
        amount = e["floor"] + (1 if i in getters else 0)
        result.append({
            "body": e["body"],
            "share_ppm": e["share_ppm"],
            "amount_cents": amount,
        })
    return result
