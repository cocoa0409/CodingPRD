"""Invoice fee folding, credit/compensation, and family fiscal standing."""
from db import db, touch


def open_invoice_for(family_id):
    """The family's current OPEN invoice, if any. If several exist, the most
    recently created one is the 'current' open invoice."""
    opens = [inv for inv in db.invoices.values()
             if inv["family_id"] == family_id and inv["status"] == "OPEN"]
    if not opens:
        return None
    return sorted(opens, key=lambda i: (i["created_at"], i["_seq"]))[-1]


def recompute_invoice_amounts(inv):
    """amount_due = max(0, tuition + fees - credit_applied) (PRD 3.9 / invoice_totals)."""
    gross = inv["tuition_cents"] + inv["fees_cents"]
    inv["amount_due_cents"] = max(0, gross - inv["credit_applied_cents"])


def add_fee_line(family_id, amount):
    """Fold a positive fee into the family's current OPEN invoice if one exists.
    Returns True if folded into an invoice, False otherwise."""
    if amount == 0:
        return False
    inv = open_invoice_for(family_id)
    if inv is None:
        return False
    inv["fees_cents"] += amount
    recompute_invoice_amounts(inv)
    touch(inv)
    return True


def remove_fee_or_credit(family_id, amount):
    """Compensation: remove a fee line from the family's OPEN invoice fees, or
    credit it to account_credit_cents if no OPEN invoice exists (PRD 3.6/3.7).
    Conserves the total (invoice fees + family credit)."""
    if amount == 0:
        return
    inv = open_invoice_for(family_id)
    family = db.families.get(family_id)
    if inv is not None:
        inv["fees_cents"] -= amount
        recompute_invoice_amounts(inv)
        touch(inv)
    elif family is not None:
        family["account_credit_cents"] += amount
        touch(family)


def credit_family(family_id, amount):
    """Add to account_credit_cents (refunds / admin credit). Never negative."""
    if amount == 0:
        return
    family = db.families.get(family_id)
    if family is not None:
        family["account_credit_cents"] += amount
        touch(family)


def has_other_past_due(family_id, exclude_invoice_id):
    for inv in db.invoices.values():
        if inv["family_id"] != family_id:
            continue
        if inv["id"] == exclude_invoice_id:
            continue
        if inv["status"] == "PAST_DUE":
            return True
    return False


def set_family_status(family_id, status):
    family = db.families.get(family_id)
    if family is not None and family["status"] != status:
        family["status"] = status
        touch(family)
