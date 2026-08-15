"""Capital credit allocation, retirement, and payout services."""
import math
from decimal import Decimal, ROUND_FLOOR
from datetime import timedelta

from errors import ApiError
import db
from db import store, new_common, touch


# =============================================================================
# Capital Credit Allocation
# =============================================================================

def create_allocation(body):
    required = ["cooperative_id", "fiscal_year", "method"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    coop = store.cooperatives.get(body["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")
    if body["method"] not in ("PATRONAGE_WEIGHTED", "FLAT_PER_MEMBER"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "method must be PATRONAGE_WEIGHTED or FLAT_PER_MEMBER")

    alloc = new_common({
        "cooperative_id": body["cooperative_id"],
        "fiscal_year": body["fiscal_year"],
        "status": "DRAFT",
        "total_allocated_cents": 0,
        "method": body["method"],
        "_created_by": None,  # Will be set by the route handler
    })
    store.capital_credit_allocations[alloc["id"]] = alloc

    # Compute allocation lines
    _compute_allocation_lines(alloc, coop)
    return alloc


def _compute_allocation_lines(alloc, coop):
    """Compute CapitalCreditAllocationLine rows for the allocation."""
    fiscal_year = alloc["fiscal_year"]
    pool_cents = coop.get("capital_credits_pool_cents", 0)
    method = alloc["method"]

    # Find eligible members: ACTIVE or TERMINATED with >=1 kwh billed during fiscal_year
    fy_end_month = coop.get("fiscal_year_end_month", 12)
    eligible = _get_eligible_members(fiscal_year, fy_end_month)

    if not eligible:
        alloc["total_allocated_cents"] = 0
        return

    lines = []
    if method == "PATRONAGE_WEIGHTED":
        lines = _patronage_weighted_shares(eligible, pool_cents)
    elif method == "FLAT_PER_MEMBER":
        lines = _flat_per_member_shares(eligible, pool_cents)

    total = 0
    for member_id, share, weight in lines:
        line = new_common({
            "allocation_id": alloc["id"],
            "member_id": member_id,
            "allocated_cents": share,
            "weight_kwh_effective": weight,
        })
        store.capital_credit_allocation_lines[line["id"]] = line
        total += share

    alloc["total_allocated_cents"] = total


def _get_eligible_members(fiscal_year, fy_end_month):
    """Get members eligible for allocation: ACTIVE or TERMINATED with >=1 kwh in fiscal_year."""
    # Fiscal year N ends on the last day of month fy_end_month of calendar year N
    # Fiscal year start = day after prior year end
    from datetime import datetime, timezone
    import calendar

    fy_end_year = fiscal_year
    fy_end_month_last_day = calendar.monthrange(fy_end_year, fy_end_month)[1]
    fy_end = datetime(fy_end_year, fy_end_month, fy_end_month_last_day, 23, 59, 59, tzinfo=timezone.utc)

    # Start of fiscal year = day after prior fiscal year end
    prior_fy_end_year = fiscal_year - 1
    prior_fy_end_last_day = calendar.monthrange(prior_fy_end_year, fy_end_month)[1]
    fy_start = datetime(prior_fy_end_year, fy_end_month, prior_fy_end_last_day, 23, 59, 59, tzinfo=timezone.utc) + timedelta(seconds=1)

    eligible = []
    for member in store.members.values():
        if member.get("status") not in ("ACTIVE", "TERMINATED"):
            continue
        # Check if member had any finalized invoices in this fiscal year
        loc_ids = {sl["id"] for sl in store.service_locations.values()
                   if sl.get("member_id") == member["id"]}
        has_kwh = False
        for inv in store.invoices.values():
            if (inv.get("service_location_id") in loc_ids
                    and inv.get("status") in ("FINALIZED", "PAID", "WRITTEN_OFF")
                    and inv.get("kwh_billed", 0) >= 1):
                inv_end = db.parse_iso(inv["billing_period_end"])
                if fy_start <= inv_end <= fy_end:
                    has_kwh = True
                    break
        if has_kwh:
            eligible.append(member)

    return eligible


def _patronage_weighted_shares(eligible, pool_cents):
    """PATRONAGE_WEIGHTED allocation: proportional to effective weight."""
    IRRIGATION_WEIGHT_FACTOR = 0.5
    weights = {}
    total_weight = 0

    for m in eligible:
        w = m.get("patronage_base_kwh", 0) + IRRIGATION_WEIGHT_FACTOR * m.get("patronage_base_irrigation_kwh", 0)
        weights[m["id"]] = w
        total_weight += w

    if total_weight == 0:
        return [(m["id"], 0, 0) for m in eligible]

    # Compute raw shares
    raw_shares = {}
    for m in eligible:
        w = weights[m["id"]]
        raw = Decimal(str(pool_cents)) * Decimal(str(w)) / Decimal(str(total_weight))
        raw_shares[m["id"]] = raw

    # Floor each share
    floored = {}
    for m in eligible:
        floored[m["id"]] = int(raw_shares[m["id"]].to_integral_value(rounding=ROUND_FLOOR))

    total_floored = sum(floored.values())
    remainder = pool_cents - total_floored

    # Distribute remainder one cent at a time, sorted by fractional part DESC, tie-break created_at ASC
    if remainder > 0:
        fracs = []
        for m in eligible:
            frac = raw_shares[m["id"]] - Decimal(str(floored[m["id"]]))
            fracs.append((frac, m.get("created_at", ""), m["id"]))
        fracs.sort(key=lambda x: (-x[0], x[1]))
        for i in range(min(remainder, len(fracs))):
            floored[fracs[i][2]] += 1

    return [(m["id"], floored[m["id"]], weights[m["id"]]) for m in eligible]


def _flat_per_member_shares(eligible, pool_cents):
    """FLAT_PER_MEMBER allocation: equal share per eligible member."""
    count = len(eligible)
    if count == 0:
        return []

    base_share = pool_cents // count
    remainder = pool_cents - (base_share * count)

    # Sort by created_at ASC for remainder distribution
    sorted_members = sorted(eligible, key=lambda m: m.get("created_at", ""))

    result = []
    for i, m in enumerate(sorted_members):
        share = base_share + (1 if i < remainder else 0)
        result.append((m["id"], share, 0))

    return result


def get_allocation(alloc_id):
    a = store.capital_credit_allocations.get(alloc_id)
    if not a:
        raise ApiError("ERR_NOT_FOUND", 404, "CapitalCreditAllocation not found")
    return a


def list_allocations(cooperative_id=None, fiscal_year=None, status=None):
    rows = list(store.capital_credit_allocations.values())
    if cooperative_id is not None:
        rows = [r for r in rows if r.get("cooperative_id") == cooperative_id]
    if fiscal_year is not None:
        rows = [r for r in rows if str(r.get("fiscal_year")) == str(fiscal_year)]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def get_allocation_lines(alloc_id):
    return [l for l in store.capital_credit_allocation_lines.values()
            if l.get("allocation_id") == alloc_id]


def get_allocation_line(line_id):
    l = store.capital_credit_allocation_lines.get(line_id)
    if not l:
        raise ApiError("ERR_NOT_FOUND", 404, "CapitalCreditAllocationLine not found")
    return l


def list_allocation_lines(member_id=None, allocation_id=None):
    rows = list(store.capital_credit_allocation_lines.values())
    if member_id is not None:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if allocation_id is not None:
        rows = [r for r in rows if r.get("allocation_id") == allocation_id]
    return rows


def approve_allocation(alloc_id, user_id):
    alloc = get_allocation(alloc_id)
    if alloc["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Allocation must be DRAFT to approve")

    # Segregation of duties: approver must differ from creator
    if alloc.get("_created_by") and alloc["_created_by"] == user_id:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Same X-User-ID attempted both propose and approve steps")

    # Pool match check
    coop = store.cooperatives.get(alloc["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")
    if alloc["total_allocated_cents"] != coop.get("capital_credits_pool_cents", 0):
        raise ApiError("ERR_ALLOCATION_POOL_MISMATCH", 409,
                       "total_allocated_cents does not equal Cooperative.capital_credits_pool_cents")

    alloc["status"] = "APPROVED"
    touch(alloc)
    return alloc


def post_allocation(alloc_id, body):
    alloc = get_allocation(alloc_id)
    if alloc["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Allocation must be APPROVED to post")

    # OCC check
    expected_version = body.get("expected_cooperative_version")
    if expected_version is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_cooperative_version is required")
    coop = store.cooperatives.get(alloc["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")
    if int(expected_version) != coop.get("version", 1):
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_cooperative_version does not match current Cooperative.version")

    # Credit each line to member balance
    lines = get_allocation_lines(alloc_id)
    for line in lines:
        member = store.members.get(line["member_id"])
        if member:
            member["capital_credit_balance_cents"] = member.get("capital_credit_balance_cents", 0) + line["allocated_cents"]
            touch(member)

    # Debit pool to zero
    coop["capital_credits_pool_cents"] = 0
    touch(coop)

    alloc["status"] = "POSTED"
    touch(alloc)
    return alloc


def void_allocation(alloc_id):
    alloc = get_allocation(alloc_id)
    if alloc["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Allocation must be DRAFT to void")
    alloc["status"] = "VOIDED"
    touch(alloc)
    return alloc


# =============================================================================
# Capital Credit Retirement
# =============================================================================

def create_retirement(body):
    required = ["cooperative_id", "method", "total_retire_cents"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    coop = store.cooperatives.get(body["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")

    ret = new_common({
        "cooperative_id": body["cooperative_id"],
        "status": "PROPOSED",
        "method": body["method"],
        "total_retire_cents": body["total_retire_cents"],
        "pro_rata_pct": body.get("pro_rata_pct"),
        "executed_at": None,
        "total_disbursed_cents": 0,
        "_created_by": None,
    })
    store.capital_credit_retirements[ret["id"]] = ret
    return ret


def get_retirement(ret_id):
    r = store.capital_credit_retirements.get(ret_id)
    if not r:
        raise ApiError("ERR_NOT_FOUND", 404, "CapitalCreditRetirement not found")
    return r


def list_retirements(cooperative_id=None, status=None):
    rows = list(store.capital_credit_retirements.values())
    if cooperative_id is not None:
        rows = [r for r in rows if r.get("cooperative_id") == cooperative_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def board_approve_retirement(ret_id, user_id):
    ret = get_retirement(ret_id)
    if ret["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Retirement must be PROPOSED to board-approve")

    coop = store.cooperatives.get(ret["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")

    # Method allowed check
    if ret["method"] not in coop.get("retirement_methods_allowed", []):
        raise ApiError("ERR_RETIREMENT_METHOD_NOT_ALLOWED", 409,
                       "Retirement method not in Cooperative.retirement_methods_allowed")

    # PRO_RATA_PERCENTAGE requires 0 < pro_rata_pct <= 1
    if ret["method"] == "PRO_RATA_PERCENTAGE":
        pct = ret.get("pro_rata_pct")
        if pct is None or not (0 < float(pct) <= 1):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "PRO_RATA_PERCENTAGE requires 0 < pro_rata_pct <= 1")

    # Segregation of duties
    if ret.get("_created_by") and ret["_created_by"] == user_id:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Same X-User-ID attempted both propose and approve steps")

    ret["status"] = "BOARD_APPROVED"
    touch(ret)
    return ret


def execute_retirement(ret_id, body):
    ret = get_retirement(ret_id)
    if ret["status"] != "BOARD_APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Retirement must be BOARD_APPROVED to execute")

    coop = store.cooperatives.get(ret["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")

    # OCC check
    expected_version = body.get("expected_cooperative_version")
    if expected_version is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_cooperative_version is required")
    if int(expected_version) != coop.get("version", 1):
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_cooperative_version does not match current Cooperative.version")

    # Budget check
    total_balance = sum(m.get("capital_credit_balance_cents", 0) for m in store.members.values())
    if ret["total_retire_cents"] > total_balance:
        raise ApiError("ERR_RETIREMENT_BUDGET_EXCEEDED", 409,
                       "total_retire_cents exceeds sum of member capital_credit_balance_cents")

    # Generate payouts
    ret["executed_at"] = db.iso_logical(db.logical_now())
    ret["status"] = "EXECUTING"
    touch(ret)
    touch(coop)

    if ret["method"] == "FIFO_OLDEST":
        _execute_fifo(ret, coop)
    elif ret["method"] == "PRO_RATA_PERCENTAGE":
        _execute_pro_rata(ret, coop)

    # Check if all payouts settled -> SETTLED
    _check_retirement_settled(ret)

    return ret


def _execute_fifo(ret, coop):
    """FIFO_OLDEST: walk members by oldest allocation vintage."""
    target = ret["total_retire_cents"]
    remaining = target

    # Build member list with their oldest allocation vintage
    member_vintages = []
    for member in store.members.values():
        balance = member.get("capital_credit_balance_cents", 0)
        if balance <= 0:
            continue
        # Find oldest allocation fiscal year for this member
        oldest_fy = None
        for line in store.capital_credit_allocation_lines.values():
            if line.get("member_id") == member["id"]:
                alloc = store.capital_credit_allocations.get(line.get("allocation_id"))
                if alloc and alloc.get("status") == "POSTED":
                    fy = alloc.get("fiscal_year", 0)
                    if oldest_fy is None or fy < oldest_fy:
                        oldest_fy = fy
        if oldest_fy is None:
            oldest_fy = 0
        member_vintages.append((oldest_fy, member.get("created_at", ""), member))

    # Sort by (oldest_fy, created_at)
    member_vintages.sort(key=lambda x: (x[0], x[1]))

    for fy, created_at, member in member_vintages:
        if remaining <= 0:
            break
        balance = member.get("capital_credit_balance_cents", 0)
        pay = min(balance, remaining)
        if pay <= 0:
            continue

        payout = new_common({
            "retirement_id": ret["id"],
            "member_id": member["id"],
            "payout_cents": pay,
            "status": "ISSUED",
            "issued_at": db.iso_logical(db.logical_now()),
            "claim_deadline": _compute_claim_deadline(coop),
        })
        store.capital_credit_payouts[payout["id"]] = payout
        remaining -= pay


def _execute_pro_rata(ret, coop):
    """PRO_RATA_PERCENTAGE: pay each member pro_rata_pct of their balance."""
    pct = float(ret.get("pro_rata_pct", 0))
    target = ret["total_retire_cents"]

    members_with_balance = [
        m for m in store.members.values()
        if m.get("capital_credit_balance_cents", 0) > 0
    ]

    if not members_with_balance:
        return

    # First pass: floor(pct * balance)
    payouts_map = {}
    computed_total = 0
    for m in members_with_balance:
        balance = m["capital_credit_balance_cents"]
        raw = Decimal(str(pct)) * Decimal(str(balance))
        pay = int(raw.to_integral_value(rounding=ROUND_FLOOR))
        payouts_map[m["id"]] = pay
        computed_total += pay

    # Scale down if needed
    if computed_total > target and computed_total > 0:
        ratio = Decimal(str(target)) / Decimal(str(computed_total))
        for mid in payouts_map:
            scaled = Decimal(str(payouts_map[mid])) * ratio
            payouts_map[mid] = int(scaled.to_integral_value(rounding=ROUND_FLOOR))

    for m in members_with_balance:
        pay = payouts_map.get(m["id"], 0)
        if pay <= 0:
            continue
        payout = new_common({
            "retirement_id": ret["id"],
            "member_id": m["id"],
            "payout_cents": pay,
            "status": "ISSUED",
            "issued_at": db.iso_logical(db.logical_now()),
            "claim_deadline": _compute_claim_deadline(coop),
        })
        store.capital_credit_payouts[payout["id"]] = payout


def _compute_claim_deadline(coop):
    """claim_deadline = issued_at + unclaimed_dormancy_years."""
    now = db.logical_now()
    years = coop.get("unclaimed_dormancy_years", 0)
    # Approximate: add years as timedelta
    try:
        deadline = now.replace(year=now.year + years)
    except ValueError:
        # Feb 29 edge case
        deadline = now.replace(year=now.year + years, day=28)
    return db.iso_logical(deadline)


def _check_retirement_settled(ret):
    """Check if all payouts are in terminal states; if so, transition to SETTLED."""
    payouts = [p for p in store.capital_credit_payouts.values()
               if p.get("retirement_id") == ret["id"]]
    if not payouts:
        return
    terminal_states = {"CASHED", "UNCLAIMED", "ESCHEATED"}
    all_settled = all(p["status"] in terminal_states for p in payouts)
    if all_settled and ret["status"] == "EXECUTING":
        ret["status"] = "SETTLED"
        ret["total_disbursed_cents"] = sum(
            p["payout_cents"] for p in payouts if p["status"] in ("CASHED",)
        )
        touch(ret)


def abort_retirement(ret_id):
    ret = get_retirement(ret_id)
    if ret["status"] not in ("PROPOSED", "BOARD_APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Retirement must be PROPOSED or BOARD_APPROVED to abort")
    ret["status"] = "ABORTED"
    touch(ret)
    return ret


def get_retirement_payouts(ret_id):
    return [p for p in store.capital_credit_payouts.values()
            if p.get("retirement_id") == ret_id]


# =============================================================================
# Capital Credit Payout
# =============================================================================

def get_payout(payout_id):
    p = store.capital_credit_payouts.get(payout_id)
    if not p:
        raise ApiError("ERR_NOT_FOUND", 404, "CapitalCreditPayout not found")
    return p


def cash_payout(payout_id):
    p = get_payout(payout_id)
    if p["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payout must be ISSUED to cash")

    # Temporal check: logical clock < claim_deadline
    now = db.logical_now()
    deadline = db.parse_iso(p["claim_deadline"])
    if now >= deadline:
        raise ApiError("ERR_PAYOUT_STALE", 409,
                       "Attempt to cash a payout at or after its claim_deadline")

    p["status"] = "CASHED"
    touch(p)

    member = store.members.get(p["member_id"])
    if member:
        member["capital_credit_balance_cents"] = max(
            0, member.get("capital_credit_balance_cents", 0) - p["payout_cents"]
        )
        touch(member)

    # Check if parent retirement is settled
    ret = store.capital_credit_retirements.get(p["retirement_id"])
    if ret:
        _check_retirement_settled(ret)

    return p


def mark_unclaimed_payout(payout_id):
    p = get_payout(payout_id)
    if p["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payout must be ISSUED to mark unclaimed")

    p["status"] = "UNCLAIMED"
    touch(p)

    member = store.members.get(p["member_id"])
    if member:
        member["unclaimed_credit_cents"] = member.get("unclaimed_credit_cents", 0) + p["payout_cents"]
        member["capital_credit_balance_cents"] = max(
            0, member.get("capital_credit_balance_cents", 0) - p["payout_cents"]
        )
        touch(member)

    # Check if parent retirement is settled
    ret = store.capital_credit_retirements.get(p["retirement_id"])
    if ret:
        _check_retirement_settled(ret)

    return p


def get_member_payouts(member_id):
    return [p for p in store.capital_credit_payouts.values()
            if p.get("member_id") == member_id]
