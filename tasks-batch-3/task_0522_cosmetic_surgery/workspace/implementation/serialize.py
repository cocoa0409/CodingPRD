"""Entity -> output dict serializers.

Field order/names follow SCAFFOLD §1.1. QuoteLineItem has only id + created_at
(append-only, PRD §2.5).
"""

COMMON = ["created_at", "updated_at", "version"]


def _pick(entity, fields):
    return {f: entity[f] for f in fields if f in entity}


def procedure(e):
    return _pick(e, [
        "id", "code", "name",
        "surgical_fee_cents", "facility_fee_cents", "anesthesia_fee_cents",
        "revision_window_days", "active", "status",
    ] + COMMON)


def patient(e):
    return _pick(e, [
        "id", "full_name", "date_of_birth", "age_years", "asa_class", "bmi",
        "smoker", "prior_complication_count",
        "surgical_risk_score", "clearance_tier",
    ] + COMMON)


def consultation(e):
    return _pick(e, [
        "id", "patient_id", "surgeon_user_id", "chief_complaint", "status",
    ] + COMMON)


def quote_package(e):
    return _pick(e, [
        "id", "consultation_id", "patient_id",
        "subtotal_cents", "discount_pct", "total_cents",
        "required_deposit_cents", "deposit_paid_cents", "financed_cents",
        "balance_due_cents", "status",
    ] + COMMON)


def line_item(e):
    return _pick(e, [
        "id", "quote_package_id", "procedure_id",
        "surgical_fee_cents", "facility_fee_cents", "anesthesia_fee_cents",
        "bundle_total_cents", "created_at",
    ])


def consent(e):
    return _pick(e, [
        "id", "quote_package_id", "before_photo_ref",
        "photo_consent_signed", "surgical_consent_signed", "status",
    ] + COMMON)


def clearance(e):
    return _pick(e, [
        "id", "patient_id", "tier_required", "tier_provided", "cleared", "status",
    ] + COMMON)


def booking(e):
    return _pick(e, [
        "id", "quote_package_id", "patient_id", "surgeon_user_id",
        "or_room", "scheduled_start", "scheduled_end",
        "deposit_forfeited_cents", "deposit_refunded_cents", "status",
    ] + COMMON)


def financing(e):
    return _pick(e, [
        "id", "quote_package_id", "lender", "requested_amount_cents",
        "approved_amount_cents", "merchant_fee_cents", "practice_net_cents",
        "status",
    ] + COMMON)


def case(e):
    return _pick(e, [
        "id", "surgery_booking_id", "line_item_id", "reported_at",
        "attribution", "within_revision_window", "revision_charge_cents",
        "status",
    ] + COMMON)
