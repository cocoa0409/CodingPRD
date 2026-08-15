"""Rate calculations: tiered_balance_rate, effective_account_rate, bundles."""

from db import STORE
from utils import bump, round_half_up_int

CHANNELS = ["BRANCH", "ONLINE", "MOBILE", "CALL_CENTER"]


def tiered_rate(product, tiers, balance_cents):
    """tiered_balance_rate: rate in bp for a balance against a tier set."""
    if balance_cents <= 0:
        return 0
    if product["tier_application"] == "WHOLE_BALANCE":
        for t in tiers:
            lo = t["lower_bound_cents"]
            hi = t["upper_bound_cents"]
            if lo <= balance_cents and (hi == -1 or balance_cents < hi):
                return t["rate_bp"]
        return 0
    # MARGINAL: each tier rate applies to the slice inside it; blended result.
    total = 0
    for t in tiers:
        lo = t["lower_bound_cents"]
        hi = t["upper_bound_cents"]
        if balance_cents <= lo:
            continue
        upper = balance_cents if hi == -1 else min(hi, balance_cents)
        slice_cents = upper - lo
        if slice_cents > 0:
            total += slice_cents * t["rate_bp"]
    return round_half_up_int(total, balance_cents)


def qualifying_bonus(account):
    """Bundle bonus (bp) applicable to an account right now.

    Applies only when rate_source == SHEET and an ENROLLED enrollment exists
    for the customer whose qualifying balance reaches the bundle minimum and
    whose bundle lists the account's product class as eligible.
    """
    if account["rate_source"] != "SHEET":
        return 0
    product = STORE["products"].get(account["product_id"])
    if not product:
        return 0
    pclass = product["product_class"]
    best = 0
    for e in STORE["enrollments"].values():
        if e["customer_ref"] != account["customer_ref"]:
            continue
        if e["status"] != "ENROLLED":
            continue
        bundle = STORE["bundles"].get(e["bundle_id"])
        if not bundle:
            continue
        if e["qualifying_balance_cents"] < bundle["min_combined_balance_cents"]:
            continue
        if pclass not in bundle["eligible_product_classes"]:
            continue
        best = max(best, bundle["bonus_bp"])
    return best


def recompute_account_rates(account):
    """effective_account_rate: fixed order base -> bundle bonus -> cap.

    GRANDFATHERED accounts keep their frozen rate and skip recomputation.
    """
    if account["rate_source"] == "GRANDFATHERED":
        return
    product = STORE["products"][account["product_id"]]
    sheet = STORE["sheets"].get(account["sheet_id"])
    if account["rate_source"] == "SHEET":
        account["base_rate_bp"] = (
            tiered_rate(product, sheet["tiers"], account["balance_cents"]) if sheet else 0
        )
        account["bundle_bonus_bp"] = qualifying_bonus(account)
        stack = account["base_rate_bp"] + account["bundle_bonus_bp"]
    elif account["rate_source"] == "PROMO":
        if sheet:
            account["base_rate_bp"] = tiered_rate(
                product, sheet["tiers"], account["balance_cents"]
            )
        account["bundle_bonus_bp"] = 0
        offer = STORE["promos"].get(account["promo_offer_id"])
        stack = offer["promo_rate_bp"] if offer else account["base_rate_bp"]
    elif account["rate_source"] == "EXCEPTION":
        if sheet:
            account["base_rate_bp"] = tiered_rate(
                product, sheet["tiers"], account["balance_cents"]
            )
        account["bundle_bonus_bp"] = 0
        stack = account["exception_rate_bp"] or 0
    else:
        stack = account["current_rate_bp"]
    account["current_rate_bp"] = min(product["rate_cap_bp"], stack)


def combined_relationship_balance(customer_ref, bundle):
    """Sum of posted balance_cents over the customer's OPEN accounts whose
    product class is in the bundle's required_product_classes."""
    total = 0
    for a in STORE["accounts"].values():
        if a["customer_ref"] != customer_ref:
            continue
        if a["lifecycle"] != "OPEN":
            continue
        prod = STORE["products"].get(a["product_id"])
        if prod and prod["product_class"] in bundle["required_product_classes"]:
            total += a["balance_cents"]
    return total


def refresh_customer_enrollments(customer_ref, skip_bump_ids=()):
    """Refresh qualifying balances on the customer's ENROLLED enrollments and
    re-evaluate bonuses on all of the customer's OPEN accounts.

    Versions bump only where a stored value actually changed.
    """
    for e in STORE["enrollments"].values():
        if e["customer_ref"] != customer_ref or e["status"] != "ENROLLED":
            continue
        bundle = STORE["bundles"].get(e["bundle_id"])
        if not bundle:
            continue
        new_q = combined_relationship_balance(customer_ref, bundle)
        if new_q != e["qualifying_balance_cents"]:
            e["qualifying_balance_cents"] = new_q
            if e["id"] not in skip_bump_ids:
                bump(e)
    for a in STORE["accounts"].values():
        if a["customer_ref"] != customer_ref or a["lifecycle"] != "OPEN":
            continue
        old = (a["bundle_bonus_bp"], a["current_rate_bp"], a["base_rate_bp"])
        recompute_account_rates(a)
        if (a["bundle_bonus_bp"], a["current_rate_bp"], a["base_rate_bp"]) != old:
            if a["id"] not in skip_bump_ids:
                bump(a)


def create_notice(sheet_id, account_id, channel, notice_type, required_by_date):
    row = {
        "sheet_id": sheet_id,
        "account_id": account_id,
        "channel": channel,
        "notice_type": notice_type,
        "required_by_date": required_by_date,
        "sent_at": None,
        "is_late": False,
        "status": "PENDING",
    }
    from utils import stamp_new
    stamp_new(row)
    STORE["notices"][row["id"]] = row
    return row
