"""Resource projections. Field sets follow SCAFFOLD 1.1; audit fields follow
PRD 2.4 (rate-card lines and sponsor surveys carry id + created_at only)."""

from decimal import Decimal


def _v(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _pick(row, keys):
    return dict((k, _v(row.get(k))) for k in keys)


PROPERTY_FIELDS = [
    "id", "name", "sport_code", "season_year", "season_start", "season_end",
    "status", "seasonality_index", "inventory_target_value_cents",
    "committed_gross_value_cents", "delivered_media_value_cents", "sellout_pct",
    "created_at", "updated_at", "version",
]

RATE_CARD_FIELDS = [
    "id", "property_id", "label", "effective_year", "status", "published_at",
    "superseded_by_rate_card_id", "line_count",
    "created_at", "updated_at", "version",
]

RATE_CARD_LINE_FIELDS = [
    "id", "rate_card_id", "asset_class", "base_unit_price_cents", "tier_breaks",
    "exclusivity_multiplier", "created_at",
]

INVENTORY_ASSET_FIELDS = [
    "id", "property_id", "name", "asset_class", "capacity_units",
    "changeover_buffer_minutes", "requires_staffing", "min_staff_count",
    "status", "reserved_units_total",
    "created_at", "updated_at", "version",
]

SPONSOR_FIELDS = [
    "id", "name", "category", "contact_email", "status",
    "renewal_likelihood_score", "renewal_band",
    "created_at", "updated_at", "version",
]

CONTRACT_FIELDS = [
    "id", "sponsor_id", "property_id", "rate_card_id", "status",
    "fulfillment_status", "term_start", "term_end", "exclusivity_scope",
    "in_kind_declared_value_cents", "in_kind_category",
    "gross_entitlement_value_cents", "volume_discount_pct", "cash_value_cents",
    "in_kind_recognized_value_cents", "total_recognized_value_cents",
    "delivered_media_value_cents", "makegood_credit_cents", "revision_round",
    "submitted_by_user_id", "countersigned_by_user_id",
    "created_at", "updated_at", "version",
]

ENTITLEMENT_FIELDS = [
    "id", "contract_id", "inventory_asset_id", "clause_ref", "asset_class",
    "promised_units", "unit_value_cents", "gross_value_cents", "delivered_units",
    "delivery_pct", "status", "makegood_credit_cents",
    "created_at", "updated_at", "version",
]

BOOKING_FIELDS = [
    "id", "entitlement_id", "inventory_asset_id", "window_start", "window_end",
    "units_booked", "status", "proof_state", "verified_impressions",
    "delivered_at", "created_at", "updated_at", "version",
]

PROOF_FIELDS = [
    "id", "asset_booking_id", "evidence_type", "measured_value", "media_uri",
    "status", "captured_by_user_id", "adjudicated_by_user_id", "reject_reason",
    "created_at", "updated_at", "version",
]

STAFF_MEMBER_FIELDS = [
    "id", "full_name", "hourly_rate_cents", "status", "scheduled_minutes",
    "created_at", "updated_at", "version",
]

STAFF_ASSIGNMENT_FIELDS = [
    "id", "asset_booking_id", "staff_member_id", "shift_start", "shift_end",
    "role_label", "status", "created_at", "updated_at", "version",
]

SURVEY_FIELDS = [
    "id", "contract_id", "satisfaction_score", "activation_quality_score",
    "reporting_quality_score", "renewal_intent", "submitted_by_user_id",
    "composite_score", "created_at",
]


def property_out(row):
    return _pick(row, PROPERTY_FIELDS)


def rate_card_out(row):
    return _pick(row, RATE_CARD_FIELDS)


def rate_card_line_out(row):
    out = _pick(row, RATE_CARD_LINE_FIELDS)
    out["tier_breaks"] = [dict(tb) for tb in row.get("tier_breaks", [])]
    return out


def inventory_asset_out(row):
    return _pick(row, INVENTORY_ASSET_FIELDS)


def sponsor_out(row):
    return _pick(row, SPONSOR_FIELDS)


def contract_out(row):
    return _pick(row, CONTRACT_FIELDS)


def entitlement_out(row):
    return _pick(row, ENTITLEMENT_FIELDS)


def booking_out(row):
    return _pick(row, BOOKING_FIELDS)


def proof_out(row):
    return _pick(row, PROOF_FIELDS)


def staff_member_out(row):
    return _pick(row, STAFF_MEMBER_FIELDS)


def staff_assignment_out(row):
    return _pick(row, STAFF_ASSIGNMENT_FIELDS)


def survey_out(row):
    return _pick(row, SURVEY_FIELDS)
