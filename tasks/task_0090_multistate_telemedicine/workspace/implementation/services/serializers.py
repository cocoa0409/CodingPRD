"""Entity -> public JSON projections.

Field sets follow SCAFFOLD §1.1 exactly. Full entities expose
created_at/updated_at/version; lean entities (Payer, ComplianceCheck, ClockState)
expose only the fields the scaffold gives them (id + created_at for Payer/CC).
"""

_FULL_COMMON = ["id", "created_at", "updated_at", "version"]


def _project(record, fields):
    return {k: record.get(k) for k in fields}


def physician(p):
    return _project(p, _FULL_COMMON + [
        "full_name", "npi", "dea_number", "imlc_eligible", "home_state_code",
        "active_license_count", "status",
    ])


def state_license(s):
    return _project(s, _FULL_COMMON + [
        "physician_id", "state_code", "issuance_type",
        "controlled_substance_authority", "effective_date", "expiration_date",
        "status", "suspension_reason",
    ])


def patient(p):
    return _project(p, _FULL_COMMON + [
        "full_name", "email", "residence_state_code", "insurance_payer_id",
    ])


def payer(p):
    # Lean entity: id + created_at only.
    return _project(p, ["id", "created_at"] + [
        "name", "telehealth_parity", "copay_cents", "covered_state_codes",
        "allowed_amount_cents",
    ])


def visit(v):
    return _project(v, _FULL_COMMON + [
        "physician_id", "patient_id", "modality", "scheduled_at",
        "determined_state_code", "list_fee_cents", "platform_fee_cents",
        "routing", "patient_cost_cents", "prescription_version", "status",
    ])


def compliance_check(c):
    # Lean entity: id + created_at only.
    return _project(c, ["id", "created_at"] + [
        "visit_id", "outcome", "matched_license_id", "reason_code",
    ])


def prescription(p):
    return _project(p, _FULL_COMMON + [
        "visit_id", "drug_name", "dea_schedule", "days_supply", "status",
    ])


def claim(c):
    return _project(c, _FULL_COMMON + [
        "visit_id", "payer_id", "billed_cents", "allowed_cents",
        "plan_paid_cents", "status",
    ])


def follow_up(f):
    return _project(f, _FULL_COMMON + [
        "source_visit_id", "due_at", "linked_visit_id", "status",
    ])


def clock_state(c):
    # Lean entity: id + created_at + current_utc.
    return {
        "id": c.get("id"),
        "created_at": c.get("created_at"),
        "current_utc": c.get("current_utc"),
    }
