"""Invoice issuance, charge resolution, billing run (PRD Section 3.3, 3.4, 3.11)."""
import calc
import domain
from db import store
from domain import touch, _stamp_create


def _cycle_invoice_amounts(membership, account, plan):
    """Compute base/addon/discount/total for a CYCLE invoice (PRD 3.4)."""
    base = plan["monthly_fee_cents"]
    addon_fee = sum(
        ma["locked_fee_cents"]
        for ma in store.membership_addons.values()
        if ma["membership_id"] == membership["id"] and ma["status"] == "ACTIVE"
    )
    subtotal = base + addon_fee
    discount = calc.cycle_discount_cents(subtotal, domain.account_fleet_discount_pct(account))
    total = subtotal - discount
    return base, addon_fee, discount, total


def create_cycle_invoice(membership, account, plan):
    """Create a CYCLE invoice and move DRAFT -> ISSUED (attempt_count = 1)."""
    base, addon_fee, discount, total = _cycle_invoice_amounts(membership, account, plan)
    inv = {
        "id": store.new_id(),
        "account_id": account["id"],
        "membership_id": membership["id"],
        "status": "ISSUED",
        "kind": "CYCLE",
        "base_fee_cents": base,
        "addon_fee_cents": addon_fee,
        "discount_cents": discount,
        "total_cents": total,
        "attempt_count": 1,
    }
    _stamp_create(inv)
    store.invoices[inv["id"]] = inv
    return inv


def is_first_cycle_invoice(inv):
    """True if this is the membership's first CYCLE invoice (activation trigger)."""
    membership = store.memberships.get(inv["membership_id"])
    if not membership:
        return False
    if inv["kind"] != "CYCLE":
        return False
    cycle_invoices = sorted(
        [
            i
            for i in store.invoices.values()
            if i["membership_id"] == inv["membership_id"] and i["kind"] == "CYCLE"
        ],
        key=lambda i: i["created_at"],
    )
    return cycle_invoices and cycle_invoices[0]["id"] == inv["id"]


def _activate_membership(membership, plan):
    """PENDING -> ACTIVE on first cycle paid (PRD 3.3)."""
    membership["status"] = "ACTIVE"
    membership["cycle_anchor_utc"] = store.now()
    membership["current_cycle_paid_cents"] = _last_paid_total(membership)
    membership["cycle_credits_consumed_start"] = membership.get("credits_consumed", 0)
    if plan["tier_type"] == "SINGLE_WASH":
        membership["credits_granted"] = membership.get("credits_granted", 0) + plan["included_credits"]
    touch(membership)


def _reactivate_membership(membership, plan):
    """PAST_DUE -> ACTIVE on retry success (PRD 3.4)."""
    membership["status"] = "ACTIVE"
    if membership.get("cycle_anchor_utc"):
        from datetime import timedelta

        membership["cycle_anchor_utc"] = membership["cycle_anchor_utc"] + timedelta(days=calc.CYCLE_DAYS)
    membership["current_cycle_paid_cents"] = _last_paid_total(membership)
    membership["cycle_credits_consumed_start"] = membership.get("credits_consumed", 0)
    if plan["tier_type"] == "SINGLE_WASH":
        membership["credits_granted"] = membership.get("credits_granted", 0) + plan["included_credits"]
    touch(membership)


def _last_paid_total(membership):
    """Total of the most recently paid CYCLE invoice for this membership."""
    paid_cycles = sorted(
        [
            i
            for i in store.invoices.values()
            if i["membership_id"] == membership["id"]
            and i["kind"] == "CYCLE"
            and i["status"] == "PAID"
        ],
        key=lambda i: i["created_at"],
    )
    if paid_cycles:
        return paid_cycles[-1]["total_cents"]
    return membership.get("current_cycle_paid_cents", 0)


def resolve_charge(inv, outcome):
    """Resolve an ISSUED or RETRYING invoice charge (PRD 3.4, 3.11).

    SUCCEEDED -> PAID with activation/reactivation cascades.
    DECLINED  -> FAILED with ACTIVE -> PAST_DUE for a cycle charge.
    """
    membership = store.memberships.get(inv["membership_id"])
    plan = store.plans.get(membership["plan_id"]) if membership else None
    from_state = inv["status"]

    if outcome == "SUCCEEDED":
        first_cycle = is_first_cycle_invoice(inv)
        was_past_due = membership and membership["status"] == "PAST_DUE"
        inv["status"] = "PAID"
        # Gateway-paid by default: cycle/proration invoices write no wallet txn.
        touch(inv)
        if first_cycle and membership and membership["status"] == "PENDING":
            _activate_membership(membership, plan)
        elif was_past_due and inv["kind"] == "CYCLE":
            _reactivate_membership(membership, plan)
    else:  # DECLINED
        inv["status"] = "FAILED"
        touch(inv)
        if (
            inv["kind"] == "CYCLE"
            and membership
            and membership["status"] == "ACTIVE"
            and not is_first_cycle_invoice(inv)
        ):
            # A failed recurring cycle charge against an ACTIVE membership.
            membership["status"] = "PAST_DUE"
            touch(membership)
        elif (
            inv["kind"] == "CYCLE"
            and membership
            and membership["status"] == "ACTIVE"
            and from_state == "RETRYING"
        ):
            membership["status"] = "PAST_DUE"
            touch(membership)
    return inv


def run_billing(membership_id=None):
    """Run the recurring billing cycle (PRD 3.4 / 3.10).

    For each membership whose current cycle has elapsed, issue a CYCLE invoice.
    Flip CANCEL_SCHEDULED -> CANCELLED at cycle end.
    Returns the list of newly issued CYCLE invoices.
    """
    issued = []
    now = store.now()
    if membership_id is not None:
        candidates = [store.memberships[membership_id]] if membership_id in store.memberships else []
    else:
        candidates = list(store.memberships.values())

    for m in candidates:
        if not m.get("cycle_anchor_utc"):
            continue
        cycle_end = _cycle_end(m)
        cycle_elapsed = now >= cycle_end

        if m["status"] == "CANCEL_SCHEDULED":
            if cycle_elapsed:
                m["status"] = "CANCELLED"
                domain.detach_addons_on_cancel(m["id"])
                touch(m)
            continue

        if m["status"] in ("ACTIVE", "PAST_DUE") and cycle_elapsed:
            account = store.accounts[m["account_id"]]
            plan = store.plans[m["plan_id"]]
            inv = create_cycle_invoice(m, account, plan)
            issued.append(inv)

    return issued


def _cycle_end(m):
    from datetime import timedelta

    return m["cycle_anchor_utc"] + timedelta(days=calc.CYCLE_DAYS)
