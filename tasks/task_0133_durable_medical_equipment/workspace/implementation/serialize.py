"""Entity -> response-dict serialization.

Each serializer emits exactly the fields the scaffold/PRD define for that entity,
including common fields (id, created_at, updated_at, version) per PRD 2.4.
"""

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(record, *field_names):
    out = {}
    for f in _COMMON:
        out[f] = record.get(f)
    for f in field_names:
        out[f] = record.get(f)
    return out


def patient(r):
    return _base(r, "full_name", "medicare_id", "date_of_birth", "address_state")


def supplier(r):
    return _base(r, "name", "ptan", "accreditation_active")


def hcpcs_item(r):
    return _base(
        r,
        "hcpcs_code",
        "description",
        "billing_category",
        "purchase_price_cents",
        "monthly_rental_cents",
        "requires_cmn",
        "requires_prior_auth",
        "is_cpap",
    )


def dme_order(r):
    return _base(
        r,
        "patient_id",
        "supplier_id",
        "hcpcs_item_id",
        "acquisition_type",
        "modifier",
        "ordered_at_utc",
        "rental_months_billed",
        "cap_reached",
        "total_allowed_cents",
        "status",
    )


def cmn(r):
    return _base(
        r,
        "order_id",
        "physician_npi",
        "length_of_need_months",
        "signed_date",
        "superseded_by_id",
        "status",
    )


def prior_authorization(r):
    return _base(
        r,
        "order_id",
        "payer_reference",
        "decision_reason",
        "status",
        "expires_at_utc",
    )


def delivery(r):
    return _base(
        r,
        "order_id",
        "scheduled_for_utc",
        "delivered_at_utc",
        "pod_signature_name",
        "pod_received",
        "status",
    )


def rental_cycle(r):
    return _base(
        r,
        "order_id",
        "cycle_index",
        "period_start_utc",
        "period_end_utc",
        "billed_amount_cents",
        "status",
    )


def claim_line(r):
    return _base(
        r,
        "order_id",
        "rental_cycle_id",
        "audit_id",
        "line_type",
        "allowed_amount_cents",
        "status",
    )


def cpap_resupply_order(r):
    return _base(
        r,
        "order_id",
        "supply_kind",
        "requested_at_utc",
        "quantity",
        "status",
    )


def audit(r):
    return _base(
        r,
        "order_id",
        "reason_code",
        "recouped_total_cents",
        "recouped_cycle_count",
        "status",
    )
