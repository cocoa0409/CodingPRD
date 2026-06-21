"""Entity -> public JSON projection.

Each serializer returns a fresh dict in the field order/shape clients expect.
Computed fields (consumed_allowance_cents, cycles_fulfilled, etc.) are stored
on the entity and kept current by the workflows, so serialization is a plain
projection. We never mutate the stored dict here.
"""

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(obj, fields):
    return {f: obj.get(f) for f in fields}


def patient(o):
    return _pick(o, COMMON + [
        "full_name", "date_of_birth", "insurer_name", "status",
    ])


def device_model(o):
    return _pick(o, COMMON + [
        "model_code", "name", "list_price_cents", "restock_fee_cents",
        "min_severity", "firmware_version", "warranty_months", "status",
    ])


def allowance_benefit(o):
    return _pick(o, COMMON + [
        "patient_id", "plan_name", "total_allowance_cents", "per_device_cap_cents",
        "coinsurance_pct", "consumed_allowance_cents", "period_end", "status",
    ])


def evaluation(o):
    return _pick(o, COMMON + [
        "patient_id", "audiologist_user_id", "pure_tone_avg_db", "severity",
        "is_pediatric", "candidate", "status",
    ])


def order(o):
    return _pick(o, COMMON + [
        "patient_id", "evaluation_id", "device_model_id", "allowance_benefit_id",
        "ear_count", "trial_started_at", "trial_deadline_at", "gross_price_cents",
        "allowance_applied_cents", "patient_due_cents", "refund_cents",
        "fitted_firmware_version", "status",
    ])


def adjustment(o):
    return _pick(o, COMMON + [
        "fitting_order_id", "audiologist_user_id", "reason",
        "applied_firmware_version", "recall_notice_id", "status",
    ])


def warranty_claim(o):
    return _pick(o, COMMON + [
        "fitting_order_id", "claim_type", "incident_date", "assessed_value_cents",
        "deductible_cents", "clinic_cost_cents", "status",
    ])


def subscription(o):
    return _pick(o, COMMON + [
        "patient_id", "fitting_order_id", "cadence_days", "unit_price_cents",
        "started_at", "cycles_fulfilled", "lifetime_billed_cents", "status",
    ])


def supply_cycle(o):
    return _pick(o, COMMON + [
        "subscription_id", "cycle_index", "due_at", "billed_cents", "status",
    ])


def recall(o):
    return _pick(o, COMMON + [
        "device_model_id", "affected_firmware_version", "target_firmware_version",
        "severity_level", "affected_order_count", "status",
    ])


def ledger_entry(o):
    # LedgerEntry carries only id + created_at (no updated_at / version).
    return _pick(o, [
        "id", "created_at", "patient_id", "source_kind", "source_ref_id",
        "amount_cents", "memo",
    ])
