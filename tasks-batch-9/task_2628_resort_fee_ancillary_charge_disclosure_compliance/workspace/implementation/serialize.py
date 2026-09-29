"""Entity -> JSON serialisers. Timestamps are ISO 8601 UTC with 3 fractional digits."""

import clock


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": clock.fmt(row["created_at"])}
    if versioned:
        out["updated_at"] = clock.fmt(row.get("updated_at"))
        out["version"] = row.get("version")
    return out


def _pick(row, names):
    return {n: row.get(n) for n in names}


def _dt(row, names):
    return {n: clock.fmt(row.get(n)) for n in names}


JURISDICTION_FIELDS = [
    "code", "name", "occupancy_tax_rate_bps", "first_quote_total_required",
    "itemization_required_on_folio", "mandatory_fee_ban", "opt_out_mandate",
]

TAXABILITY_RULE_FIELDS = ["jurisdiction_id", "fee_code", "taxability", "tax_rate_bps"]

PROPERTY_FIELDS = [
    "jurisdiction_id", "name", "brand_code", "base_room_rate_cents", "status",
    "min_channel_disclosure_score", "disclosure_posture",
    "open_disclosure_obligation_count", "published_fee_program_count",
    "aggregate_disclosure_gap_cents",
]

CHANNEL_FIELDS = ["name", "channel_type", "supports_total_price_display", "supports_itemization"]

FEE_PROGRAM_FIELDS = [
    "property_id", "supersedes_program_id", "version_label", "status",
    "authored_by_user_id", "attested_by_user_id", "attestation_note",
    "fee_count", "mandatory_fee_count", "total_mandatory_fee_cents_per_night",
    "inclusion_coverage_ratio",
]

FEE_FIELDS = [
    "fee_program_id", "code", "label", "classification", "basis", "amount_cents",
    "percent_bps", "avoidable", "opt_out_window_hours", "disclosure_text",
    "inclusion_count", "inclusion_value_cents",
]

FEE_INCLUSION_FIELDS = [
    "fee_id", "service_code", "service_label", "retail_value_cents", "units",
    "included_value_cents",
]

PROFILE_FIELDS = [
    "property_id", "channel_id", "fee_program_id", "first_quote_shows_total",
    "itemized_at_first_quote", "disclosure_placement", "status", "disclosure_score",
    "confirmed_undisclosed_count", "remediation_round",
]

BOOKING_FIELDS = [
    "property_id", "channel_id", "channel_disclosure_profile_id", "fee_program_id",
    "nights", "guests", "room_rate_cents", "disclosed_fee_amounts",
    "quoted_room_total_cents", "quoted_mandatory_fee_cents", "quoted_tax_cents",
    "quoted_total_cents", "quote_disclosure_gap_cents", "folio_fee_total_cents",
    "folio_total_cents", "quote_folio_variance_cents", "guest_out_of_pocket_cents",
    "stay_status", "disclosure_status",
]

FOLIO_FIELDS = [
    "booking_id", "status", "line_count", "charges_subtotal_cents",
    "credits_total_cents", "tax_total_cents", "folio_total_cents",
    "itemization_complete",
]

FOLIO_LINE_FIELDS = [
    "folio_id", "fee_id", "jurisdiction_id", "line_type", "fee_code", "description",
    "amount_cents", "taxability_determination", "tax_rate_bps", "tax_cents",
    "sequence_no",
]

OPT_OUT_FIELDS = [
    "booking_id", "fee_id", "status", "requested_hours_before_arrival",
    "credit_cents", "tax_credit_cents", "credit_line_sequence_no",
    "denial_reason_code",
]

COMPLAINT_FIELDS = [
    "booking_id", "folio_line_id", "complaint_reason", "narrative", "status",
    "refund_variant", "disputed_amount_cents", "disclosed_amount_cents",
    "refund_entitlement_cents", "refunded_amount_cents", "dismissal_reason_code",
    "investigated_by_user_id", "adjudicated_by_user_id",
]

INQUIRY_FIELDS = [
    "jurisdiction_id", "property_id", "docket_number", "channel_scope", "status",
    "response_summary", "remediation_directive", "remediation_summary",
    "rejection_reason", "withdrawal_reason", "drafted_by_user_id",
    "submitted_by_user_id", "flagged_profile_ids", "remediation_round",
    "exposure_cents",
]

REVENUE_MODEL_FIELDS = [
    "property_id", "fee_program_id", "scenario", "variant", "roll_in_fee_codes",
    "baseline_adr_cents", "baseline_commission_cents", "baseline_tax_cents",
    "baseline_guest_total_cents", "baseline_net_revenue_cents",
    "modeled_adr_cents", "applied_commission_bps", "modeled_commission_cents",
    "modeled_tax_cents", "modeled_guest_total_cents", "modeled_net_revenue_cents",
    "modeled_adr_delta_cents", "modeled_commission_delta_cents",
    "modeled_tax_delta_cents", "modeled_guest_total_delta_cents",
    "modeled_net_revenue_delta_cents",
]


def jurisdiction(row):
    out = _common(row)
    out.update(_pick(row, JURISDICTION_FIELDS))
    return out


def taxability_rule(row):
    out = _common(row)
    out.update(_pick(row, TAXABILITY_RULE_FIELDS))
    return out


def property_row(row):
    out = _common(row)
    out.update(_pick(row, PROPERTY_FIELDS))
    return out


def channel(row):
    out = _common(row)
    out.update(_pick(row, CHANNEL_FIELDS))
    return out


def fee_program(row):
    out = _common(row)
    out.update(_pick(row, FEE_PROGRAM_FIELDS))
    out.update(_dt(row, ["effective_from", "effective_to", "published_at"]))
    return out


def fee(row):
    out = _common(row)
    out.update(_pick(row, FEE_FIELDS))
    return out


def fee_inclusion(row):
    out = _common(row)
    out.update(_pick(row, FEE_INCLUSION_FIELDS))
    return out


def profile(row):
    out = _common(row)
    out.update(_pick(row, PROFILE_FIELDS))
    out.update(_dt(row, ["deployed_from", "deployed_to", "last_audited_at"]))
    return out


def booking(row):
    out = _common(row)
    out.update(_pick(row, BOOKING_FIELDS))
    out.update(_dt(row, ["arrival_date"]))
    return out


def folio(row):
    out = _common(row)
    out.update(_pick(row, FOLIO_FIELDS))
    out.update(_dt(row, ["posted_at"]))
    return out


def folio_line(row):
    out = _common(row, versioned=False)
    out.update(_pick(row, FOLIO_LINE_FIELDS))
    return out


def opt_out_request(row):
    out = _common(row)
    out.update(_pick(row, OPT_OUT_FIELDS))
    out.update(_dt(row, ["decided_at"]))
    return out


def complaint(row):
    out = _common(row)
    out.update(_pick(row, COMPLAINT_FIELDS))
    return out


def inquiry(row):
    out = _common(row)
    out.update(_pick(row, INQUIRY_FIELDS))
    out.update(_dt(row, ["response_due_at"]))
    return out


def revenue_model(row):
    out = _common(row, versioned=False)
    out.update(_pick(row, REVENUE_MODEL_FIELDS))
    return out
