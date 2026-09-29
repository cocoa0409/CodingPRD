"""Domain services: derivations, cascades and the collateral posture gate."""

from datetime import timedelta

from flask import g

import config
from calc import (
    bucket_capacities,
    exception_scoring,
    gross_up,
    membership_stock_requirement,
    pct_bps,
    raw_prepayment_fee,
    rhu_div,
)
from errors import ApiError
from store import (
    date_days_between,
    db,
    finalize,
    fmt_dt,
    new_entity,
    parse_dt,
    public,
    sort_records,
    touch,
    whole_days_between,
)

# --------------------------------------------------------------- collections --


def member_assets(member_id):
    return [a for a in db.assets.values() if a["member_bank_id"] == member_id]


def member_advances(member_id):
    return [a for a in db.advances.values() if a["member_bank_id"] == member_id]


def member_subscriptions(member_id):
    return [s for s in db.subscriptions.values() if s["member_bank_id"] == member_id]


def asset_receipts(asset_id):
    return [r for r in db.receipts.values() if r["collateral_asset_id"] == asset_id]


def review_findings(review_id):
    return [f for f in db.findings.values()
            if f["collateral_verification_review_id"] == review_id]


def asset_findings(asset_id):
    return [f for f in db.findings.values() if f["collateral_asset_id"] == asset_id]


# --------------------------------------------------------------- entity build --


def create_member(name, charter_type, total_assets_cents, credit_rating_tier, cdfi_certified):
    m = new_entity("member")
    m["name"] = name
    m["charter_type"] = charter_type
    m["total_assets_cents"] = total_assets_cents
    m["membership_status"] = "APPLICANT"
    m["credit_rating_tier"] = credit_rating_tier
    m["cdfi_certified"] = cdfi_certified
    m["community_lending_eligible"] = False
    m["pledge_mode"] = "NONE"
    m["pledge_agreement_status"] = "NONE"
    m["pledge_agreement_effective_date"] = None
    m["delivery_required"] = False
    m["verification_haircut_bps"] = 0
    m["latest_review_outcome"] = "NONE"
    m["required_membership_stock_cents"] = 0
    m["required_activity_stock_cents"] = 0
    m["required_total_stock_cents"] = 0
    m["stock_held_cents"] = 0
    m["stock_deficiency_cents"] = 0
    m["excess_stock_cents"] = 0
    m["lendable_collateral_value_cents"] = 0
    m["total_outstanding_advances_cents"] = 0
    m["committed_advances_cents"] = 0
    m["borrowing_capacity_cents"] = 0
    m["collateral_posture"] = "OPEN"
    m["shortfall_status"] = "NONE"
    m["shortfall_required_cure_cents"] = 0
    m["shortfall_opened_at"] = None
    m["shortfall_cure_deadline"] = None
    finalize(m)
    derive_pure(m)
    db.members[m["id"]] = m
    return m


def create_subscription(member_bank_id, subscription_type, amount_cents, advance_id=None,
                        status="SUBSCRIBED"):
    s = new_entity("subscription")
    s["member_bank_id"] = member_bank_id
    s["advance_id"] = advance_id
    s["subscription_type"] = subscription_type
    s["amount_cents"] = amount_cents
    s["shares"] = amount_cents // config.STOCK_PAR_VALUE_CENTS
    s["status"] = status
    s["redemption_requested_at"] = None
    s["repurchased_at"] = None
    finalize(s)
    db.subscriptions[s["id"]] = s
    return s


def create_asset(member, fields, replaces_asset_id=None):
    a = new_entity("asset")
    a["member_bank_id"] = member["id"]
    a["replaces_asset_id"] = replaces_asset_id
    a["asset_class"] = fields["asset_class"]
    a["unpaid_principal_balance_cents"] = fields["unpaid_principal_balance_cents"]
    a["market_value_cents"] = fields["market_value_cents"]
    a["ltv_bps"] = fields["ltv_bps"]
    a["delinquency_days"] = fields["delinquency_days"]
    a["documentation_status"] = fields["documentation_status"]
    a["custody_location"] = fields["custody_location"]
    a["appraisal_date"] = fields["appraisal_date"]
    a["effective_listing_mode"] = "BLANKET"
    a["collateral_basis_cents"] = 0
    a["discount_factor_bps"] = 0
    a["lendable_value_cents"] = 0
    a["status"] = "UNDER_REVIEW"
    a["ineligibility_reason"] = "NONE"
    finalize(a)
    db.assets[a["id"]] = a
    refresh_asset(a, member)
    return a


def create_receipt(asset_id, file_count, delivery_date, return_date):
    r = new_entity("receipt")
    r["collateral_asset_id"] = asset_id
    r["file_count"] = file_count
    r["delivery_date"] = delivery_date
    r["return_date"] = return_date
    r["status"] = "PENDING_DELIVERY"
    r["received_at"] = None
    r["exception_note"] = None
    finalize(r)
    db.receipts[r["id"]] = r
    return r


def create_review(member_bank_id, window_start, window_end, sample_size):
    r = new_entity("review")
    r["member_bank_id"] = member_bank_id
    r["window_start"] = window_start
    r["window_end"] = window_end
    r["sample_size"] = sample_size
    r["status"] = "SCHEDULED"
    r["retest_count"] = 0
    r["weighted_exception_score"] = 0
    r["exception_rate_pct"] = 0
    r["haircut_bps"] = 0
    r["outcome"] = "PENDING"
    r["closed_at"] = None
    finalize(r)
    db.reviews[r["id"]] = r
    return r


def create_finding(review_id, asset_id, finding_type, severity, raised_by_user_id):
    f = new_entity("finding")
    f["collateral_verification_review_id"] = review_id
    f["collateral_asset_id"] = asset_id
    f["finding_type"] = finding_type
    f["severity"] = severity
    f["weight"] = config.SEVERITY_WEIGHT[severity]
    f["status"] = "OPEN"
    f["raised_by_user_id"] = raised_by_user_id
    f["waived_by_user_id"] = None
    finalize(f)
    db.findings[f["id"]] = f
    return f


def create_product(fields):
    p = new_entity("product")
    for key in ("product_code", "structure", "min_term_days", "max_term_days", "rate_bps",
                "prepayment_fee_method", "flat_prepayment_fee_bps", "symmetric_credit_enabled",
                "activity_stock_pct_bps", "min_principal_cents", "requires_collateral_delivery",
                "community_program_flag"):
        p[key] = fields[key]
    finalize(p)
    db.products[p["id"]] = p
    return p


def create_advance(fields):
    a = new_entity("advance")
    for key in ("member_bank_id", "advance_product_id", "community_program_allocation_id",
                "community_bucket", "requested_subsidy_cents", "requested_net_proceeds_cents",
                "fund_stock_from_advance", "term_days", "gross_principal_cents",
                "activity_stock_cents", "net_proceeds_cents", "rate_bps"):
        a[key] = fields[key]
    a["outstanding_principal_cents"] = 0
    a["credit_status"] = "REQUESTED"
    a["collateral_status"] = "PENDING_VERIFICATION"
    a["approved_by_user_id"] = None
    a["funded_by_user_id"] = None
    a["funded_at"] = None
    a["maturity_date"] = None
    a["capacity_at_request_cents"] = fields["capacity_at_request_cents"]
    a["capacity_at_funding_cents"] = None
    finalize(a)
    a["_subsidy_bucket"] = None
    a["_subsidy_take"] = 0
    a["_subsidy_spill"] = 0
    db.advances[a["id"]] = a
    return a


def create_prepayment(advance, product, prepay_kind, prepay_amount_cents):
    e = new_entity("prepayment")
    e["advance_id"] = advance["id"]
    e["prepay_kind"] = prepay_kind
    e["prepay_amount_cents"] = prepay_amount_cents
    e["quote_date"] = db.now_iso()
    e["quoted_market_rate_bps"] = db.market_rate_bps
    days = remaining_days(advance, db.now())
    e["quoted_remaining_days"] = days
    e["quoted_fee_cents"] = raw_prepayment_fee(
        product, prepay_amount_cents, advance["rate_bps"], db.market_rate_bps, days)
    e["settlement_date"] = None
    e["settlement_market_rate_bps"] = None
    e["settled_remaining_days"] = None
    e["admin_fee_cents"] = 0
    e["symmetric_credit_cents"] = 0
    e["settled_fee_cents"] = None
    e["fee_delta_cents"] = None
    e["status"] = "QUOTED"
    finalize(e)
    db.prepayments[e["id"]] = e
    return e


def create_allocation(program_code, fiscal_year, total_pool_cents, subsidy_rate_bps):
    a = new_entity("allocation")
    a["program_code"] = program_code
    a["fiscal_year"] = fiscal_year
    a["total_pool_cents"] = total_pool_cents
    a["subsidy_rate_bps"] = subsidy_rate_bps
    first, rehab, general = bucket_capacities(total_pool_cents)
    a["bucket_capacity_first_time_cents"] = first
    a["bucket_capacity_rehabilitation_cents"] = rehab
    a["bucket_capacity_general_cents"] = general
    a["bucket_committed_first_time_cents"] = 0
    a["bucket_committed_rehabilitation_cents"] = 0
    a["bucket_committed_general_cents"] = 0
    a["committed_cents"] = 0
    a["remaining_cents"] = total_pool_cents
    a["status"] = "OPEN"
    finalize(a)
    db.allocations[a["id"]] = a
    return a


# ------------------------------------------------------------------- assets --


def effective_listing_mode(asset, member):
    delivered = (asset["custody_location"] == "FHLB_SAFEKEEPING"
                 and any(r["status"] == "RECEIVED" for r in asset_receipts(asset["id"])))
    if delivered:
        return "DELIVERED"
    mode = member["pledge_mode"]
    if mode == "DELIVERY_REQUIRED":
        return "SPECIFIC"
    if mode == "SPECIFIC_LISTING":
        return "SPECIFIC"
    return "BLANKET"


def collateral_basis(asset):
    if asset["asset_class"] in config.SECURITIES_CLASSES:
        return asset["market_value_cents"]
    return min(asset["unpaid_principal_balance_cents"], asset["market_value_cents"])


def base_factor_bps(asset_class, listing_mode):
    return config.BASE_FACTOR_BPS.get(asset_class, {}).get(listing_mode)


def discount_factor_bps(asset, member, listing_mode=None):
    """Return the discount factor, or None when no base factor is defined."""
    mode = listing_mode or asset["effective_listing_mode"]
    base = base_factor_bps(asset["asset_class"], mode)
    if base is None:
        return None
    f = base
    if asset["ltv_bps"] > config.LTV_PENALTY_THRESHOLD_BPS:
        f -= config.LTV_PENALTY_BPS
    if asset["delinquency_days"] >= config.DELINQUENCY_PENALTY_DAYS:
        f -= config.DELINQUENCY_PENALTY_BPS
    if asset["documentation_status"] == "EXCEPTION":
        f -= config.DOC_EXCEPTION_PENALTY_BPS
    if asset["asset_class"] in config.STALE_APPRAISAL_CLASSES:
        age = date_days_between(parse_dt(asset["appraisal_date"]), db.now())
        if age > config.STALE_APPRAISAL_DAYS:
            f -= config.STALE_APPRAISAL_PENALTY_BPS
    f -= member["verification_haircut_bps"]
    return max(config.FLOOR_FACTOR_BPS, f)


def refresh_asset(asset, member):
    """Recompute the asset's derived pricing fields for its current status."""
    asset["effective_listing_mode"] = effective_listing_mode(asset, member)
    asset["collateral_basis_cents"] = collateral_basis(asset)
    if asset["status"] == "ELIGIBLE":
        factor = discount_factor_bps(asset, member)
        if factor is None:
            factor = 0
        asset["discount_factor_bps"] = factor
        asset["lendable_value_cents"] = pct_bps(asset["collateral_basis_cents"], factor)
    else:
        asset["discount_factor_bps"] = 0
        asset["lendable_value_cents"] = 0


def refresh_member_assets(member, statuses=("ELIGIBLE", "SUSPENDED")):
    """Re-derive listing mode / factor / lendable value across a member's pledge."""
    for asset in member_assets(member["id"]):
        if statuses is not None and asset["status"] not in statuses:
            continue
        before = (asset["effective_listing_mode"], asset["collateral_basis_cents"],
                  asset["discount_factor_bps"], asset["lendable_value_cents"])
        refresh_asset(asset, member)
        after = (asset["effective_listing_mode"], asset["collateral_basis_cents"],
                 asset["discount_factor_bps"], asset["lendable_value_cents"])
        if before != after:
            touch(asset)


def hypothetical_lendable(asset, member):
    """Lendable value the asset would carry if it were approved as it stands."""
    mode = effective_listing_mode(asset, member)
    factor = discount_factor_bps(asset, member, mode)
    if factor is None:
        return 0
    return pct_bps(collateral_basis(asset), factor)


def certified_lendable(member):
    total = 0
    for asset in member_assets(member["id"]):
        if asset["status"] == "ELIGIBLE":
            total += asset["lendable_value_cents"]
    return total


def provisional_lendable(member):
    total = certified_lendable(member)
    for asset in member_assets(member["id"]):
        if asset["status"] == "UNDER_REVIEW":
            hyp = hypothetical_lendable(asset, member)
            total += pct_bps(hyp, config.PROVISIONAL_UNDER_REVIEW_BPS)
    return total


# ---------------------------------------------------------------- aggregates --


def capacity_breakdown(member, variant="CERTIFIED", exclude_advance_id=None):
    if variant == "PROVISIONAL":
        lendable = provisional_lendable(member)
        commit_states = ("CREDIT_APPROVED",)
    else:
        lendable = certified_lendable(member)
        commit_states = ("REQUESTED", "CREDIT_APPROVED")
    tier_cap = config.TIER_CAP_BPS[member["credit_rating_tier"]]
    statutory = pct_bps(member["total_assets_cents"], config.TOTAL_ASSET_CAP_BPS)
    base = min(pct_bps(lendable, tier_cap), statutory)
    outstanding = 0
    commitments = 0
    for advance in member_advances(member["id"]):
        if advance["credit_status"] == "FUNDED":
            outstanding += advance["outstanding_principal_cents"]
        elif advance["credit_status"] in commit_states:
            if exclude_advance_id is not None and advance["id"] == exclude_advance_id:
                continue
            commitments += advance["gross_principal_cents"]
    return {
        "variant": "PROVISIONAL" if variant == "PROVISIONAL" else "CERTIFIED",
        "lendable_collateral_value_cents": lendable,
        "tier_cap_bps": tier_cap,
        "statutory_cap_cents": statutory,
        "capacity_base_cents": base,
        "outstanding_advances_cents": outstanding,
        "commitments_cents": commitments,
        "borrowing_capacity_cents": base - outstanding - commitments,
    }


def derive_pure(member):
    """Re-derive every purely computed member aggregate; never touches state."""
    member["community_lending_eligible"] = bool(
        member["membership_status"] == "ACTIVE"
        and member["credit_rating_tier"] <= 3
        and (member["cdfi_certified"] or member["charter_type"] != "INSURANCE_COMPANY"))
    member["delivery_required"] = bool(
        member["pledge_mode"] == "DELIVERY_REQUIRED"
        or member["membership_status"] in ("PROBATION", "SUSPENDED")
        or member["credit_rating_tier"] == 4)
    member["required_membership_stock_cents"] = membership_stock_requirement(
        member["total_assets_cents"])
    activity = 0
    for advance in member_advances(member["id"]):
        if advance["credit_status"] in ("CREDIT_APPROVED", "FUNDED"):
            activity += advance["activity_stock_cents"]
    member["required_activity_stock_cents"] = activity
    member["required_total_stock_cents"] = (
        member["required_membership_stock_cents"] + activity)
    held = 0
    for sub in member_subscriptions(member["id"]):
        if sub["status"] in ("ISSUED", "REDEMPTION_REQUESTED"):
            held += sub["amount_cents"]
    member["stock_held_cents"] = held
    member["stock_deficiency_cents"] = max(0, member["required_total_stock_cents"] - held)
    member["excess_stock_cents"] = max(0, held - member["required_total_stock_cents"])
    breakdown = capacity_breakdown(member, "CERTIFIED")
    member["lendable_collateral_value_cents"] = breakdown["lendable_collateral_value_cents"]
    member["total_outstanding_advances_cents"] = breakdown["outstanding_advances_cents"]
    member["committed_advances_cents"] = breakdown["commitments_cents"]
    member["borrowing_capacity_cents"] = breakdown["borrowing_capacity_cents"]


# ------------------------------------------------------------------- posture --


def recompute_posture(member, exclude_advance_id=None):
    """The pinned three-step posture recomputation of PRD section 2.8."""
    derive_pure(member)                                     # step 1
    previous = member["collateral_posture"]
    cured = False
    frozen = (member["membership_status"] == "SUSPENDED"
              or member["borrowing_capacity_cents"] < 0)
    if frozen:                                              # step 2
        member["collateral_posture"] = "FROZEN"
        if member["shortfall_status"] in ("NONE", "CURED"):
            member["shortfall_status"] = "OPEN"
            member["shortfall_required_cure_cents"] = (
                (-member["borrowing_capacity_cents"])
                + pct_bps(member["total_outstanding_advances_cents"],
                          config.SHORTFALL_BUFFER_BPS))
            member["shortfall_opened_at"] = db.now_iso()
            member["shortfall_cure_deadline"] = fmt_dt(
                db.now() + timedelta(days=config.SHORTFALL_CURE_DAYS))
    else:
        if member["shortfall_status"] == "OPEN":
            member["shortfall_status"] = "CURED"
            member["shortfall_required_cure_cents"] = 0
            cured = True
        buffer_cents = pct_bps(member["total_outstanding_advances_cents"],
                               config.RESTRICTED_BUFFER_BPS)
        if (member["shortfall_status"] == "ESCALATED"                  # step 3
                or member["latest_review_outcome"] == "FAIL"
                or member["borrowing_capacity_cents"] < buffer_cents):
            member["collateral_posture"] = "RESTRICTED"
        else:
            member["collateral_posture"] = "OPEN"
    if member["collateral_posture"] == "FROZEN" and previous != "FROZEN":
        cascade_frozen(member, exclude_advance_id)
        derive_pure(member)
    if cured:
        for advance in member_advances(member["id"]):
            if advance["collateral_status"] == "SHORTFALL" and advance["credit_status"] == "FUNDED":
                advance["collateral_status"] = "SECURED"
                touch(advance)


def cascade_frozen(member, exclude_advance_id=None):
    """Mark funded advances short and cancel uncommitted credit on a freeze."""
    for advance in sort_records(member_advances(member["id"])):
        if (advance["credit_status"] == "FUNDED"
                and advance["collateral_status"] == "SECURED"):
            advance["collateral_status"] = "SHORTFALL"
            touch(advance)
        elif advance["credit_status"] in ("REQUESTED", "CREDIT_APPROVED"):
            if exclude_advance_id is not None and advance["id"] == exclude_advance_id:
                continue
            advance["credit_status"] = "CANCELLED_FOR_COLLATERAL"
            touch(advance)
            release_subsidy(advance)
            for sub in member_subscriptions(member["id"]):
                if (sub["advance_id"] == advance["id"]
                        and sub["subscription_type"] == "ACTIVITY"
                        and sub["status"] == "SUBSCRIBED"):
                    sub["status"] = "CANCELLED"
                    touch(sub)


# --------------------------------------------------------------- set-asides --


def refresh_allocation(allocation):
    committed = (allocation["bucket_committed_first_time_cents"]
                 + allocation["bucket_committed_rehabilitation_cents"]
                 + allocation["bucket_committed_general_cents"])
    allocation["committed_cents"] = committed
    allocation["remaining_cents"] = allocation["total_pool_cents"] - committed
    allocation["status"] = "CLOSED" if allocation["remaining_cents"] == 0 else "OPEN"


def commit_subsidy(advance, allocation):
    """Waterfall commit; raises ERR_SETASIDE_POOL_EXHAUSTED when it cannot fit."""
    requested = advance["requested_subsidy_cents"]
    purpose = advance["community_bucket"]
    if purpose in ("NONE", None):
        purpose = "GENERAL"
    general_cap = allocation["bucket_capacity_general_cents"]
    general_free = general_cap - allocation["bucket_committed_general_cents"]
    if purpose == "GENERAL":
        if general_free < requested:
            raise ApiError("ERR_SETASIDE_POOL_EXHAUSTED")
        allocation["bucket_committed_general_cents"] += requested
        advance["_subsidy_bucket"] = "GENERAL"
        advance["_subsidy_take"] = 0
        advance["_subsidy_spill"] = requested
    else:
        cap_field = config.BUCKET_CAPACITY_FIELD[purpose]
        com_field = config.BUCKET_COMMITTED_FIELD[purpose]
        purpose_free = allocation[cap_field] - allocation[com_field]
        take = min(requested, purpose_free)
        spill = requested - take
        if spill > general_free:
            raise ApiError("ERR_SETASIDE_POOL_EXHAUSTED")
        allocation[com_field] += take
        allocation["bucket_committed_general_cents"] += spill
        advance["_subsidy_bucket"] = purpose
        advance["_subsidy_take"] = take
        advance["_subsidy_spill"] = spill
    refresh_allocation(allocation)
    touch(allocation)


def release_subsidy(advance):
    """Reverse a waterfall commit exactly: spill out of GENERAL first."""
    allocation_id = advance.get("community_program_allocation_id")
    if not allocation_id:
        return
    allocation = db.allocations.get(allocation_id)
    if allocation is None:
        return
    take = advance.get("_subsidy_take") or 0
    spill = advance.get("_subsidy_spill") or 0
    bucket = advance.get("_subsidy_bucket")
    if take == 0 and spill == 0:
        return
    allocation["bucket_committed_general_cents"] -= spill
    if bucket and bucket != "GENERAL":
        allocation[config.BUCKET_COMMITTED_FIELD[bucket]] -= take
    advance["_subsidy_take"] = 0
    advance["_subsidy_spill"] = 0
    refresh_allocation(allocation)
    touch(allocation)


# -------------------------------------------------------------- prepayments --


def remaining_days(advance, as_of):
    if not advance.get("maturity_date"):
        return 0
    return max(0, whole_days_between(as_of, parse_dt(advance["maturity_date"])))


def settle_prepayment_amounts(event, advance, product):
    days = remaining_days(advance, db.now())
    principal = event["prepay_amount_cents"]
    raw = raw_prepayment_fee(product, principal, advance["rate_bps"],
                             db.market_rate_bps, days)
    admin = pct_bps(principal, config.PREPAY_ADMIN_FEE_BPS)
    event["settlement_date"] = db.now_iso()
    event["settlement_market_rate_bps"] = db.market_rate_bps
    event["settled_remaining_days"] = days
    event["admin_fee_cents"] = admin
    event["symmetric_credit_cents"] = -raw if raw < 0 else 0
    event["settled_fee_cents"] = raw + admin
    event["fee_delta_cents"] = event["settled_fee_cents"] - event["quoted_fee_cents"]
    event["status"] = "SETTLED"


# ------------------------------------------------------------ review closing --


def close_review_cascade(review, member):
    """The five-level close cascade of PRD section 3.8."""
    findings = review_findings(review["id"])
    counted = [f for f in findings if f["status"] in ("OPEN", "UNRESOLVED")]
    critical = sum(1 for f in counted if f["severity"] == "CRITICAL")
    major = sum(1 for f in counted if f["severity"] == "MAJOR")
    minor = sum(1 for f in counted if f["severity"] == "MINOR")
    score, rate, haircut, outcome = exception_scoring(
        critical, major, minor, review["sample_size"])
    review["weighted_exception_score"] = score
    review["exception_rate_pct"] = rate
    review["haircut_bps"] = haircut
    review["outcome"] = outcome
    review["status"] = "CLOSED"
    review["closed_at"] = db.now_iso()
    for finding in findings:
        if finding["status"] == "OPEN":
            finding["status"] = "UNRESOLVED"
            touch(finding)
    member["verification_haircut_bps"] = haircut
    member["latest_review_outcome"] = outcome

    # L2: reprice the pledge, then suspend assets carrying unresolved findings
    refresh_member_assets(member)
    flagged = set()
    for finding in review_findings(review["id"]):
        if finding["status"] == "UNRESOLVED" and finding["severity"] in ("MAJOR", "CRITICAL"):
            flagged.add(finding["collateral_asset_id"])
    for asset_id in flagged:
        asset = db.assets.get(asset_id)
        if asset is not None and asset["status"] == "ELIGIBLE":
            asset["status"] = "SUSPENDED"
            asset["discount_factor_bps"] = 0
            asset["lendable_value_cents"] = 0
            asset["ineligibility_reason"] = "UNRESOLVED_REVIEW_FINDING"
            touch(asset)

    # L3 / L4 / L5
    recompute_posture(member)


# ------------------------------------------------------------- serialization --


def serialize_member(member):
    derive_pure(member)
    return public(member)


def serialize_allocation(allocation):
    refresh_allocation(allocation)
    return public(allocation)


def serialize(entity):
    kind = entity.get("_kind")
    if kind == "member":
        return serialize_member(entity)
    if kind == "allocation":
        return serialize_allocation(entity)
    return public(entity)


# --------------------------------------------------------------- pagination --


def paginate(records, limit, offset):
    ordered = sort_records(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total


# ------------------------------------------------------------------- scoping --


def is_treasury():
    return getattr(g, "role", None) == config.ROLE_TREASURY_OFFICER


def require_own_member(member_id):
    if is_treasury() and g.user_id != member_id:
        raise ApiError("ERR_MEMBER_SCOPE_VIOLATION")


def bump_member(member):
    """Register the single member mutation of this request."""
    derive_pure(member)
    touch(member)
