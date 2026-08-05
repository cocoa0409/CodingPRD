"""Business-logic helpers: entity factory, calculations, and cascades."""

import store

CASE_TERMINAL = {"CLOSED_ENFORCED", "DIVERSION_SATISFIED", "DISMISSED"}


# ---------------------------------------------------------------------------
# Entity factory / mutation
# ---------------------------------------------------------------------------
def new_entity(collection, versioned):
    ts = store.now()
    ent = {
        "id": store.new_id(),
        "created_at": ts,
        "_seq": store.next_seq(),
    }
    if versioned:
        ent["updated_at"] = ts
        ent["version"] = 1
    store.db[collection][ent["id"]] = ent
    return ent


def touch(ent):
    if "version" in ent:
        ent["version"] += 1
        ent["updated_at"] = store.now()


# ---------------------------------------------------------------------------
# Case-linked lookups (for ownership scoping)
# ---------------------------------------------------------------------------
def case_of(kind, ent):
    if kind == "cases":
        return ent
    if kind == "installments":
        plan = store.db["payment_plans"].get(ent["payment_plan_id"])
        if plan is None:
            return None
        return store.db["cases"].get(plan["case_id"])
    cid = ent.get("case_id")
    if cid is None:
        return None
    return store.db["cases"].get(cid)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def final_net_arrears(case):
    cid = case["id"]
    paid = 0
    for inst in store.db["installments"].values():
        if inst["status"] != "PAID":
            continue
        plan = store.db["payment_plans"].get(inst["payment_plan_id"])
        if plan is None or plan["case_id"] != cid:
            continue
        if plan["status"] in {"ACCEPTED", "COMPLETED", "DEFAULTED"}:
            paid += inst["amount_cents"]
    disbursed = 0
    for ref in store.db["referrals"].values():
        if (ref["case_id"] == cid and ref["referral_type"] == "RENTAL_ASSISTANCE"
                and ref["status"] == "DISBURSED"):
            disbursed += ref["disbursed_amount_cents"]
    return max(0, case["claimed_arrears_cents"] - paid - disbursed)


def refresh_case(case):
    """Keep the derived net_arrears_cents field current for serialization."""
    case["net_arrears_cents"] = final_net_arrears(case)
    return case


def program_budget_remaining():
    spent = 0
    for ref in store.db["referrals"].values():
        if ref["status"] == "DISBURSED":
            spent += ref["disbursed_amount_cents"]
    return store.ASSISTANCE_PROGRAM_BUDGET_CENTS - spent


def income_cap(tenant):
    return (store.INCOME_CAP_BASE_CENTS
            + (tenant["household_size"] - 1) * store.INCOME_CAP_PER_MEMBER_CENTS)


def generate_installments(plan):
    total = plan["total_cents"]
    count = plan["installment_count"]
    base = total // count
    remainder = total - base * count
    first_due = plan["first_due_date"]
    for seq in range(1, count + 1):
        inst = new_entity("installments", versioned=True)
        inst["payment_plan_id"] = plan["id"]
        inst["sequence"] = seq
        inst["amount_cents"] = base + (remainder if seq == count else 0)
        inst["due_date"] = first_due + store.days((seq - 1) * store.INSTALLMENT_INTERVAL_DAYS)
        inst["paid_at"] = None
        inst["status"] = "DUE"


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cancel_scheduled_hearings(case):
    for h in store.db["hearings"].values():
        if h["case_id"] == case["id"] and h["status"] == "SCHEDULED":
            h["status"] = "CANCELLED"
            touch(h)
            court = store.db["courts"].get(h["court_id"])
            if court is not None:
                court["hearings_scheduled_count"] -= 1
                touch(court)


def withdraw_open_plans(case):
    for p in store.db["payment_plans"].values():
        if p["case_id"] == case["id"] and p["status"] in {"PROPOSED", "COUNTERED"}:
            p["status"] = "WITHDRAWN"
            p["current_proposer"] = None
            touch(p)


def cancel_open_lockouts(case):
    for lo in store.db["lockout_orders"].values():
        if lo["case_id"] == case["id"] and lo["status"] in {"REQUESTED", "SCHEDULED"}:
            lo["status"] = "CANCELLED"
            touch(lo)


def satisfy_diversion(case):
    """Case IN_DIVERSION -> DIVERSION_SATISFIED with closing cascade."""
    case["status"] = "DIVERSION_SATISFIED"
    case["outcome"] = "DIVERTED"
    case["closed_at"] = store.now()
    touch(case)
    cancel_scheduled_hearings(case)
    withdraw_open_plans(case)


def maybe_satisfy_after_money(case):
    """After a payment/disbursement, satisfy the diversion if arrears hit 0."""
    if case["status"] == "IN_DIVERSION" and final_net_arrears(case) == 0:
        satisfy_diversion(case)


def dismiss_via_vacatur(case):
    """Case JUDGMENT_ENTERED -> DISMISSED via judgment vacatur cascade."""
    if case["status"] in {"JUDGMENT_ENTERED", "ENFORCEMENT"}:
        case["status"] = "DISMISSED"
        case["outcome"] = "DISMISSED"
        case["closed_at"] = store.now()
        touch(case)
    cancel_open_lockouts(case)
