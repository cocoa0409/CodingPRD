"""Depreciation calculation engine — book and tax ledgers."""
from decimal import Decimal, ROUND_HALF_UP
import db
from db import new_id, now_iso

MACRS_5_RATES = [Decimal("0.2000"), Decimal("0.3200"), Decimal("0.1920"),
                 Decimal("0.1152"), Decimal("0.1152"), Decimal("0.0576")]
MACRS_7_RATES = [Decimal("0.1429"), Decimal("0.2449"), Decimal("0.1749"),
                 Decimal("0.1249"), Decimal("0.0893"), Decimal("0.0892"),
                 Decimal("0.0893"), Decimal("0.0446")]
BONUS_RATE_PCT = Decimal("0.60")
MID_MONTH_CUTOFF_DAY = 15


def round_half_up_cents(dec_value):
    """Round a Decimal to integer cents, half-up."""
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def period_of_date(iso_date):
    """YYYY-MM of an ISO date string."""
    return iso_date[:7]


def period_next(period):
    """Return the period one month after period (YYYY-MM)."""
    y = int(period[:4])
    m = int(period[5:7])
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


def latest_posted_period():
    """Latest POSTED run period, or None."""
    posted = [r["period"] for r in db.depreciation_runs.values() if r["status"] == "POSTED"]
    return max(posted) if posted else None


def count_book_entries(asset_id):
    n = 0
    for e in db.depreciation_entries.values():
        if e["asset_id"] == asset_id and e["ledger"] == "BOOK":
            n += 1
    return n


def count_tax_entries(asset_id):
    n = 0
    for e in db.depreciation_entries.values():
        if e["asset_id"] == asset_id and e["ledger"] == "TAX":
            n += 1
    return n


def count_tax_entries_in_year(asset_id, year):
    """Count TAX entries whose period is in the given calendar year."""
    n = 0
    prefix = f"{year:04d}-"
    for e in db.depreciation_entries.values():
        if e["asset_id"] == asset_id and e["ledger"] == "TAX" and e["period"].startswith(prefix):
            n += 1
    return n


def sum_tax_entries_in_year(asset_id, year):
    total = 0
    prefix = f"{year:04d}-"
    for e in db.depreciation_entries.values():
        if e["asset_id"] == asset_id and e["ledger"] == "TAX" and e["period"].startswith(prefix):
            total += e["amount_cents"]
    return total


def depreciable_basis(asset):
    return (asset["acquisition_cost_cents"]
            - asset["salvage_value_cents"]
            - asset["impairment_total_cents"])


def book_eligible(asset, period):
    """Book entry eligibility for a given run period."""
    if asset["status"] != "IN_SERVICE":
        return False
    if asset.get("in_service_date") is None:
        return False
    if period_of_date(asset["in_service_date"]) > period:
        return False
    months_posted = count_book_entries(asset["id"])
    if months_posted >= asset["useful_life_months"]:
        return False
    if asset["accumulated_book_cents"] >= depreciable_basis(asset):
        return False
    return True


def book_amount(asset, period):
    """Compute the book depreciation amount for this period. Assumes eligible."""
    basis = depreciable_basis(asset)
    acc = asset["accumulated_book_cents"]
    months_posted = count_book_entries(asset["id"])
    useful = asset["useful_life_months"]
    # Final month plug
    if months_posted == useful - 1:
        return basis - acc
    if asset["book_method"] == "STRAIGHT_LINE":
        remaining_basis = basis - acc
        remaining_months = useful - months_posted
        return round_half_up_cents(Decimal(remaining_basis) / Decimal(remaining_months))
    else:  # DOUBLE_DECLINING
        nbv = asset["acquisition_cost_cents"] - acc - asset["impairment_total_cents"]
        amount = round_half_up_cents(Decimal(nbv) * 2 / Decimal(useful))
        if acc + amount > basis:
            amount = basis - acc
        return amount


def tax_eligible(asset, period):
    """Tax entry eligibility for a given run period."""
    if asset["status"] != "IN_SERVICE":
        return False
    if asset.get("in_service_date") is None:
        return False
    if period_of_date(asset["in_service_date"]) > period:
        return False
    if asset["accumulated_tax_cents"] >= asset["acquisition_cost_cents"]:
        return False
    in_service_year = int(asset["in_service_date"][:4])
    run_year = int(period[:4])
    tax_year_index = run_year - in_service_year + 1
    if asset["tax_method"] == "TAX_STRAIGHT_LINE":
        if count_tax_entries(asset["id"]) >= asset["useful_life_months"]:
            return False
        return True
    else:
        rates = MACRS_5_RATES if asset["tax_method"] == "MACRS_5YR" else MACRS_7_RATES
        if tax_year_index > len(rates):
            return False
        if tax_year_index < 1:
            return False
        return True


def tax_amount(asset, period):
    """Compute the tax depreciation amount for this period. Assumes eligible."""
    cost = asset["acquisition_cost_cents"]
    acc = asset["accumulated_tax_cents"]
    in_service_year = int(asset["in_service_date"][:4])
    run_year = int(period[:4])
    run_month = int(period[5:7])
    tax_year_index = run_year - in_service_year + 1

    if asset["tax_method"] == "TAX_STRAIGHT_LINE":
        months_posted = count_tax_entries(asset["id"])
        if months_posted == asset["useful_life_months"] - 1:
            amount = cost - acc
        else:
            amount = round_half_up_cents(Decimal(cost) / Decimal(asset["useful_life_months"]))
    else:
        rates = MACRS_5_RATES if asset["tax_method"] == "MACRS_5YR" else MACRS_7_RATES
        bonus = bool(asset.get("bonus_elected"))
        cost_d = Decimal(cost)
        if bonus:
            base_after_bonus = cost_d * (Decimal(1) - BONUS_RATE_PCT)
            if tax_year_index == 1:
                annual_dec = cost_d * BONUS_RATE_PCT + base_after_bonus * rates[0]
            else:
                annual_dec = base_after_bonus * rates[tax_year_index - 1]
        else:
            annual_dec = cost_d * rates[tax_year_index - 1]
        annual = round_half_up_cents(annual_dec)
        if run_month == 12:
            prior = sum_tax_entries_in_year(asset["id"], run_year)
            amount = annual - prior
        else:
            amount = round_half_up_cents(Decimal(annual) / Decimal(12))
    # Cap at acquisition cost
    if amount < 0:
        amount = 0
    if acc + amount > cost:
        amount = cost - acc
    return amount


def create_entry(asset_id, ledger, period, amount, source, run_id=None, disposal_id=None):
    """Create a DepreciationEntry and apply it to the asset's accumulated amounts."""
    entry = {
        "id": new_id(),
        "run_id": run_id,
        "disposal_id": disposal_id,
        "asset_id": asset_id,
        "ledger": ledger,
        "period": period,
        "amount_cents": int(amount),
        "source": source,
        "created_at": now_iso(),
    }
    db.depreciation_entries[entry["id"]] = entry
    return entry
