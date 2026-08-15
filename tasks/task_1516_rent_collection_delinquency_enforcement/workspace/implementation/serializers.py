"""Entity -> public JSON view. Exposes exactly the fields declared in the
scaffold entity table (PRD 2.5 common fields; PaymentAllocation carries only
id/created_at). Internal bookkeeping keys (prefixed "_") never leak."""


def _pick(rec, fields):
    return {k: rec.get(k) for k in fields}


_COMMON = ["id", "created_at", "updated_at", "version"]

PROPERTY_FIELDS = _COMMON + [
    "name", "state_code", "posting_priority_policy", "late_fee_cap_cents",
    "nsf_fee_cap_cents", "monthly_waiver_cap_cents", "min_partial_payment_percent",
    "collections_threshold_cents", "notice_cure_period_days",
    "plan_cooling_off_days", "plan_setup_fee_cents", "plan_setup_fee_threshold_cents",
]

TENANT_FIELDS = _COMMON + ["full_name", "email", "phone"]

LEASE_FIELDS = _COMMON + [
    "property_id", "primary_tenant_id", "unit_label", "monthly_rent_cents",
    "due_day", "grace_period_days", "late_fee_type", "late_fee_flat_cents",
    "late_fee_percent_bps", "late_fee_daily_cents", "term_start_date",
    "term_end_date", "status", "move_out_date",
]

CHARGE_FIELDS = _COMMON + [
    "lease_id", "kind", "source", "period_start_date", "period_end_date",
    "due_date", "amount_cents", "waived_cents", "outstanding_cents", "status",
    "created_by_user_id",
]

PAYMENT_FIELDS = _COMMON + [
    "lease_id", "tenant_id", "channel", "amount_cents", "received_date",
    "status", "posted_date", "return_reason_code", "nsf_fee_cents", "return_count",
]

ALLOCATION_FIELDS = [
    "id", "created_at", "payment_id", "charge_id", "direction",
    "amount_cents", "allocation_order", "note",
]

NOTICE_FIELDS = _COMMON + [
    "lease_id", "charge_ids", "period_start_date", "period_end_date",
    "amount_demanded_cents", "status", "issued_date", "cure_deadline_date",
    "service_method", "served_date", "served_by_user_id", "cancel_reason",
]

PLAN_FIELDS = _COMMON + [
    "lease_id", "charge_ids", "drafted_by_user_id", "approved_by_user_id",
    "status", "setup_fee_cents", "scheduled_total_cents", "installment_count",
    "first_installment_date", "installments", "missed_installment_count",
    "defaulted_date", "cancel_reason",
]

DISPUTE_FIELDS = _COMMON + [
    "lease_id", "charge_id", "tenant_id", "reason", "status", "reopen_count",
    "adjusted_amount_cents", "resolution_notes",
]

REFERRAL_FIELDS = _COMMON + [
    "lease_id", "referred_balance_cents", "status", "agency_name",
    "referred_date", "recall_reason",
]


def property_view(r):
    return _pick(r, PROPERTY_FIELDS)


def tenant_view(r):
    return _pick(r, TENANT_FIELDS)


def lease_view(r):
    return _pick(r, LEASE_FIELDS)


def charge_view(r):
    return _pick(r, CHARGE_FIELDS)


def payment_view(r):
    return _pick(r, PAYMENT_FIELDS)


def allocation_view(r):
    return _pick(r, ALLOCATION_FIELDS)


def notice_view(r):
    return _pick(r, NOTICE_FIELDS)


def plan_view(r):
    out = _pick(r, PLAN_FIELDS)
    out["installments"] = [
        {
            "sequence_number": i["sequence_number"],
            "due_date": i["due_date"],
            "amount_cents": i["amount_cents"],
            "status": i["status"],
        }
        for i in r["installments"]
    ]
    return out


def dispute_view(r):
    return _pick(r, DISPUTE_FIELDS)


def referral_view(r):
    return _pick(r, REFERRAL_FIELDS)
