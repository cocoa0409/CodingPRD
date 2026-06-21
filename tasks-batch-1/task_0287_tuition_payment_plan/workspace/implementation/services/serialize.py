"""Public resource serialization. Computed fields are recomputed/refreshed in
domain.py before serialization; here we just project the stored record.
"""


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def institution_view(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "currency": r["currency"],
        "clock_utc": r["clock_utc"],
        "refund_policy": r["refund_policy"],
    })
    return out


def term_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "code": r["code"],
        "term_start": r["term_start"],
        "term_end": r["term_end"],
        "enroll_open": r["enroll_open"],
        "enroll_close": r["enroll_close"],
        "status": r["status"],
    })
    return out


def student_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "external_ref": r["external_ref"],
        "full_name": r["full_name"],
        "email": r["email"],
        "has_active_hold": r["has_active_hold"],
    })
    return out


def plan_template_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "name": r["name"],
        "installment_count": r["installment_count"],
        "down_payment_pct": r["down_payment_pct"],
        "plan_fee_cents": r["plan_fee_cents"],
        "late_fee_grace_days": r["late_fee_grace_days"],
        "autopay_required": r["autopay_required"],
        "status": r["status"],
    })
    return out


def enrollment_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "student_id": r["student_id"],
        "term_id": r["term_id"],
        "plan_template_id": r["plan_template_id"],
        "installment_count": r["installment_count"],
        "down_payment_pct": r["down_payment_pct"],
        "plan_fee_cents": r["plan_fee_cents"],
        "autopay_enabled": r["autopay_enabled"],
        "gross_charges_cents": r["gross_charges_cents"],
        "total_aid_cents": r["total_aid_cents"],
        "net_after_aid_cents": r["net_after_aid_cents"],
        "down_payment_cents": r["down_payment_cents"],
        "financed_principal_cents": r["financed_principal_cents"],
        "scheduled_balance_cents": r["scheduled_balance_cents"],
        "paid_principal_cents": r["paid_principal_cents"],
        "late_fee_balance_cents": r["late_fee_balance_cents"],
        "delinquent_installment_count": r["delinquent_installment_count"],
        "status": r["status"],
    })
    return out


def installment_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "enrollment_id": r["enrollment_id"],
        "sequence_index": r["sequence_index"],
        "due_date": r["due_date"],
        "amount_cents": r["amount_cents"],
        "paid_amount_cents": r["paid_amount_cents"],
        "status": r["status"],
    })
    return out


def charge_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "enrollment_id": r["enrollment_id"],
        "kind": r["kind"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def aid_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "enrollment_id": r["enrollment_id"],
        "source": r["source"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def payment_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "enrollment_id": r["enrollment_id"],
        "installment_id": r["installment_id"],
        "purpose": r["purpose"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def late_fee_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "enrollment_id": r["enrollment_id"],
        "installment_id": r["installment_id"],
        "days_late": r["days_late"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def hold_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "student_id": r["student_id"],
        "enrollment_id": r["enrollment_id"],
        "reason": r["reason"],
        "status": r["status"],
    })
    return out


def withdrawal_view(r):
    out = _common(r)
    out.update({
        "institution_id": r["institution_id"],
        "enrollment_id": r["enrollment_id"],
        "effective_date": r["effective_date"],
        "variant_used": r["variant_used"],
        "retained_charges_cents": r["retained_charges_cents"],
        "net_owed_after_withdrawal_cents": r["net_owed_after_withdrawal_cents"],
        "refund_to_student_cents": r["refund_to_student_cents"],
    })
    return out
