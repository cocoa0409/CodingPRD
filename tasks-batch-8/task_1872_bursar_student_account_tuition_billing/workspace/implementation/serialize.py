"""Explicit per-entity serializers (no internal fields leak)."""


def _common(r):
    return {"id": r["id"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "version": r["version"]}


def ser_term(t):
    d = _common(t)
    d.update({
        "code": t["code"], "name": t["name"],
        "start_date": t["start_date"], "end_date": t["end_date"],
        "census_date": t["census_date"],
        "full_refund_end_date": t["full_refund_end_date"],
        "mid_refund_end_date": t["mid_refund_end_date"],
        "withdrawal_deadline": t["withdrawal_deadline"],
        "refund_policy": t["refund_policy"],
        "flat_fee_cents": t["flat_fee_cents"],
        "hold_threshold_cents": t["hold_threshold_cents"],
        "plan_setup_fee_cents": t["plan_setup_fee_cents"],
        "late_fee_pct": t["late_fee_pct"],
        "grace_days": t["grace_days"],
        "status": t["status"],
    })
    return d


def ser_student(s):
    d = _common(s)
    d.update({
        "full_name": s["full_name"], "external_ref": s["external_ref"],
        "residency_status": s["residency_status"], "level": s["level"],
    })
    return d


def ser_rate(r):
    d = _common(r)
    d.update({
        "term_id": r["term_id"], "residency": r["residency"], "level": r["level"],
        "per_credit_rate_cents": r["per_credit_rate_cents"],
        "full_time_threshold_credits": r["full_time_threshold_credits"],
        "flat_rate_cents": r["flat_rate_cents"],
        "max_flat_credits": r["max_flat_credits"],
        "overload_rate_cents": r["overload_rate_cents"],
        "effective_from": r["effective_from"], "effective_to": r["effective_to"],
    })
    return d


def ser_account(a):
    d = _common(a)
    d.update({
        "student_id": a["student_id"], "term_id": a["term_id"],
        "status": a["status"],
        "charges_total_cents": a["charges_total_cents"],
        "payments_total_cents": a["payments_total_cents"],
        "waivers_total_cents": a["waivers_total_cents"],
        "sponsor_total_cents": a["sponsor_total_cents"],
        "writeoffs_total_cents": a["writeoffs_total_cents"],
        "balance_cents": a["balance_cents"],
        "past_due_cents": a["past_due_cents"],
        "writeoff_status": a["writeoff_status"],
        "writeoff_requester_id": a["writeoff_requester_id"],
    })
    return d


def ser_ledger_entry(e):
    # LedgerEntry is immutable: only id and created_at as common properties.
    return {
        "id": e["id"], "account_id": e["account_id"],
        "entry_type": e["entry_type"], "charge_kind": e["charge_kind"],
        "amount_cents": e["amount_cents"], "due_date": e["due_date"],
        "enrollment_id": e["enrollment_id"], "source_ref": e["source_ref"],
        "memo": e["memo"], "created_at": e["created_at"],
    }


def ser_enrollment(en):
    d = _common(en)
    d.update({
        "student_id": en["student_id"], "term_id": en["term_id"],
        "account_id": en["account_id"], "credit_hours": en["credit_hours"],
        "effective_date": en["effective_date"], "status": en["status"],
        "exit_date": en["exit_date"],
        "assessed_total_cents": en["assessed_total_cents"],
    })
    return d


def ser_payment(p):
    d = _common(p)
    d.update({
        "account_id": p["account_id"], "amount_cents": p["amount_cents"],
        "method": p["method"], "status": p["status"],
        "allocations": p["allocations"],
        "unapplied_cents": p["unapplied_cents"],
        "reversed_reason": p["reversed_reason"],
    })
    return d


def ser_waiver(w):
    d = _common(w)
    d.update({
        "account_id": w["account_id"], "kind": w["kind"],
        "awarded_cents": w["awarded_cents"], "posted_cents": w["posted_cents"],
        "allocations": w["allocations"], "status": w["status"],
    })
    return d


def ser_agreement(a):
    d = _common(a)
    d.update({
        "sponsor_name": a["sponsor_name"], "student_id": a["student_id"],
        "term_id": a["term_id"], "cap_cents": a["cap_cents"],
        "covers_tuition": a["covers_tuition"], "covers_fees": a["covers_fees"],
        "billing_basis": a["billing_basis"],
        "start_date": a["start_date"], "end_date": a["end_date"],
        "billed_cents": a["billed_cents"], "status": a["status"],
    })
    return d


def ser_invoice(i):
    d = _common(i)
    d.update({
        "agreement_id": i["agreement_id"], "invoice_date": i["invoice_date"],
        "lines": i["lines"], "total_cents": i["total_cents"],
        "paid_cents": i["paid_cents"], "status": i["status"],
        "dispute_reason": i["dispute_reason"],
    })
    return d


def ser_plan(p):
    d = _common(p)
    d.update({
        "account_id": p["account_id"],
        "installment_count": p["installment_count"],
        "first_due_date": p["first_due_date"],
        "principal_cents": p["principal_cents"], "fee_cents": p["fee_cents"],
        "total_cents": p["total_cents"],
        "defaulted_count": p["defaulted_count"], "status": p["status"],
    })
    return d


def ser_installment(i):
    d = _common(i)
    d.update({
        "plan_id": i["plan_id"], "sequence": i["sequence"],
        "due_date": i["due_date"], "amount_cents": i["amount_cents"],
        "paid_cents": i["paid_cents"],
        "late_fee_posted": i["late_fee_posted"], "status": i["status"],
    })
    return d


def ser_hold(h):
    d = _common(h)
    d.update({
        "account_id": h["account_id"], "hold_type": h["hold_type"],
        "origin": h["origin"], "reason": h["reason"], "status": h["status"],
        "released_reason": h["released_reason"],
    })
    return d


def ser_refund(r):
    d = _common(r)
    d.update({
        "account_id": r["account_id"], "enrollment_id": r["enrollment_id"],
        "trigger": r["trigger"], "effective_date": r["effective_date"],
        "policy_variant": r["policy_variant"],
        "basis_cents": r["basis_cents"], "pct_applied": r["pct_applied"],
        "amount_cents": r["amount_cents"], "status": r["status"],
    })
    return d


def ser_tax_form(f):
    d = _common(f)
    d.update({
        "student_id": f["student_id"], "tax_year": f["tax_year"],
        "box1_cents": f["box1_cents"], "box4_cents": f["box4_cents"],
        "box5_cents": f["box5_cents"], "status": f["status"],
        "corrected_from_id": f["corrected_from_id"],
    })
    return d
