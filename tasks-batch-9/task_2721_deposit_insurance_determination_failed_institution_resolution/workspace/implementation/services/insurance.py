"""Ownership-category analysis, brokered pass-through attribution and the
uninsured hold allocation -- PRD sections 3.5 and 3.6.

Constants are fixed by the PRD: the standard maximum deposit insurance amount is
25000000 cents and a revocable trust's beneficiary count is capped at five.
"""

import db as dbmod
import lookup
from errors import ApiError
from util import floor_div, round_half_up

SMDIA_CENTS = 25000000
REVOCABLE_BENEFICIARY_CAP = 5

CATEGORY_ORDER = (
    "SINGLE",
    "JOINT",
    "REVOCABLE_TRUST",
    "IRREVOCABLE_TRUST",
    "RETIREMENT",
)

DETERMINABLE_INSURANCE_STATUSES = ("FROZEN_FOR_DETERMINATION", "DETERMINED")


def acct_amount(account):
    """An account's contribution: principal plus accrued, unposted interest."""
    return account["balance_cents"] + account["accrued_interest_cents"]


def eligible_accounts(institution_id):
    """Accounts read at FROZEN_FOR_DETERMINATION or DETERMINED, never PENDING."""
    rows = [
        a
        for a in lookup.accounts_of(institution_id)
        if a["insurance_status"] in DETERMINABLE_INSURANCE_STATUSES
    ]
    return dbmod.ordered(rows)


def validate_joint_shares(depositor_id, accounts):
    """Every joint account contributing to this depositor must carry co-owner
    interests whose designated_share_bps sum to exactly 10000."""
    for account in accounts:
        if account["ownership_category"] != "JOINT":
            continue
        co_owners = lookup.interests_on_account(account["id"], "CO_OWNER")
        if not any(i["depositor_record_id"] == depositor_id for i in co_owners):
            continue
        if sum(i["designated_share_bps"] for i in co_owners) != 10000:
            raise ApiError("ERR_OWNERSHIP_SHARES_UNBALANCED")


def _add(shares, category, account_id, cents):
    if cents == 0 and account_id not in shares[category]:
        shares[category][account_id] = 0
        return
    shares[category][account_id] = shares[category].get(account_id, 0) + cents


def compute(depositor, method_variant, accounts=None):
    """Run the two movements of PRD section 3.5 for one depositor.

    Returns the determination amounts, the per-ownership-category breakdown and
    the per-account attribution map this depositor's position was built from.
    """
    depositor_id = depositor["id"]
    if accounts is None:
        accounts = eligible_accounts(depositor["institution_id"])

    shares = {category: {} for category in CATEGORY_ORDER}

    # --- the single-ownership bucket collects three streams --------------
    for account in accounts:
        category = account["ownership_category"]
        amount = acct_amount(account)
        if category == "SINGLE" and account["primary_depositor_id"] == depositor_id:
            _add(shares, "SINGLE", account["id"], amount)
        elif category == "BROKERED_PASS_THROUGH":
            # Brokered pass-through attribution: one enum value decides whose
            # determination the omnibus dollars land in.
            if account["recordkeeping_status"] == "COMPLETE":
                for participant in lookup.interests_on_account(
                    account["id"], "PARTICIPANT"
                ):
                    if participant["depositor_record_id"] != depositor_id:
                        continue
                    _add(
                        shares,
                        "SINGLE",
                        account["id"],
                        round_half_up(
                            amount * participant["designated_share_bps"], 10000
                        ),
                    )
            elif account["primary_depositor_id"] == depositor_id:
                _add(shares, "SINGLE", account["id"], amount)
        elif category == "JOINT":
            for co_owner in lookup.interests_on_account(account["id"], "CO_OWNER"):
                if co_owner["depositor_record_id"] != depositor_id:
                    continue
                _add(
                    shares,
                    "JOINT",
                    account["id"],
                    round_half_up(amount * co_owner["designated_share_bps"], 10000),
                )
        elif (
            category == "REVOCABLE_TRUST"
            and account["primary_depositor_id"] == depositor_id
        ):
            _add(shares, "REVOCABLE_TRUST", account["id"], amount)
        elif (
            category == "IRREVOCABLE_TRUST"
            and account["primary_depositor_id"] == depositor_id
        ):
            _add(shares, "IRREVOCABLE_TRUST", account["id"], amount)
        elif category == "RETIREMENT" and account["primary_depositor_id"] == depositor_id:
            _add(shares, "RETIREMENT", account["id"], amount)

    # --- the revocable-trust limit varies with the beneficiary count -----
    beneficiary_ids = set()
    for account_id in shares["REVOCABLE_TRUST"]:
        for beneficiary in lookup.interests_on_account(account_id, "BENEFICIARY"):
            beneficiary_ids.add(beneficiary["depositor_record_id"])
    beneficiary_count = max(1, len(beneficiary_ids))
    if beneficiary_count > REVOCABLE_BENEFICIARY_CAP:
        beneficiary_count = REVOCABLE_BENEFICIARY_CAP

    limits = {
        "SINGLE": SMDIA_CENTS,
        "JOINT": SMDIA_CENTS,
        "REVOCABLE_TRUST": SMDIA_CENTS * beneficiary_count,
        "RETIREMENT": SMDIA_CENTS,
    }

    # --- the irrevocable-trust bucket is insured beneficiary by beneficiary
    accounts_by_id = {a["id"]: a for a in accounts}
    irrevocable_insured = 0
    for account_id, attributed in shares["IRREVOCABLE_TRUST"].items():
        beneficiaries = lookup.interests_on_account(account_id, "BENEFICIARY")
        amount = acct_amount(accounts_by_id[account_id])
        if beneficiaries:
            for beneficiary in beneficiaries:
                share = round_half_up(
                    amount * beneficiary["designated_share_bps"], 10000
                )
                irrevocable_insured += min(share, SMDIA_CENTS)
        else:
            irrevocable_insured += min(attributed, SMDIA_CENTS)

    breakdown = {}
    insured_total = 0
    uninsured_total = 0
    attributed_total = 0

    for category in CATEGORY_ORDER:
        per_account = shares[category]
        attributed = sum(per_account.values())
        if category == "IRREVOCABLE_TRUST":
            insured = min(irrevocable_insured, attributed)
            uninsured = attributed - insured
            limit = insured
        else:
            limit = limits[category]
            if method_variant == "PER_ACCOUNT_PROVISIONAL":
                insured = sum(min(value, limit) for value in per_account.values())
                uninsured = sum(
                    max(0, value - limit) for value in per_account.values()
                )
            else:
                insured = min(attributed, limit)
                uninsured = max(0, attributed - limit)
        attributed_total += attributed
        insured_total += insured
        uninsured_total += uninsured
        if attributed != 0:
            breakdown[category] = {
                "attributed_cents": attributed,
                "limit_cents": limit,
                "insured_cents": insured,
                "uninsured_cents": uninsured,
            }

    account_attribution = {}
    for category in CATEGORY_ORDER:
        for account_id, value in shares[category].items():
            account_attribution[account_id] = (
                account_attribution.get(account_id, 0) + value
            )

    return {
        "insured_amount_cents": insured_total,
        "uninsured_amount_cents": uninsured_total,
        "attributed_total_cents": attributed_total,
        "category_breakdown": breakdown,
        "account_attribution": account_attribution,
    }


def allocate_uninsured_hold(uninsured_cents, attribution):
    """calculations.uninsured_hold_allocation (PRD section 3.6).

    Truncate every proportional share, then hand the remainder out one cent at a
    time in created_at ascending / account_number ascending order, so the
    allocated holds sum to exactly ``uninsured_cents``.
    """
    if uninsured_cents == 0:
        return []
    eligible = []
    for account_id, attributed in attribution.items():
        if attributed <= 0:
            continue
        account = dbmod.db.accounts.get(account_id)
        if account is None:
            continue
        eligible.append((account, attributed))
    if not eligible:
        return []
    eligible.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["account_number"]))

    divisor = sum(attributed for _, attributed in eligible)
    if divisor <= 0:
        return []

    holds = [
        floor_div(uninsured_cents * attributed, divisor) for _, attributed in eligible
    ]
    remainder = uninsured_cents - sum(holds)
    index = 0
    while remainder > 0 and eligible:
        holds[index % len(holds)] += 1
        remainder -= 1
        index += 1
    return [(pair[0], holds[i]) for i, pair in enumerate(eligible)]
