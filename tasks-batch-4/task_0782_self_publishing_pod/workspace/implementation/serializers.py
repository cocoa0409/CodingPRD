"""Entity -> public JSON serializers. Only declared fields are emitted; internal
keys (prefixed with '_') are never exposed."""
from decimal import Decimal

_COMMON = ["id", "created_at", "updated_at", "version"]

_FIELDS = {
    "publisher": ["name", "email", "payout_method", "reserve_held_cents",
                  "lifetime_paid_cents", "status"],
    "title": ["publisher_id", "title", "subtitle", "language", "bisac_category",
              "status"],
    "format": ["title_id", "format_type", "trim_size", "interior_color",
               "page_count", "file_size_mb", "isbn_id", "print_cost_cents",
               "status"],
    "asset": ["format_id", "asset_type", "file_ref", "file_format",
              "declared_page_count", "paper_type", "declared_spine_mm",
              "spine_width_mm", "status", "rejection_reason"],
    "isbn": ["publisher_id", "isbn_13", "assigned_format_id", "status"],
    "channel": ["name", "channel_type", "supports_formats", "ebook_high_rate",
                "ebook_low_rate", "ebook_rate_low_threshold_cents",
                "ebook_rate_high_threshold_cents", "delivery_fee_per_mb_cents",
                "distribution_discount_standard", "distribution_discount_expanded",
                "returns_reserve_pct", "min_list_price_cents",
                "max_list_price_cents"],
    "price": ["format_id", "channel_id", "territory", "list_price_cents",
              "currency", "effective_from", "effective_to", "expanded_reach",
              "royalty_per_unit_cents", "status"],
    "proof": ["format_id", "round_number", "revision_notes", "status"],
    "drequest": ["format_id", "channel_id", "territory", "expanded_reach",
                 "reason", "status"],
    "salesline": ["format_id", "channel_id", "territory", "units", "line_type",
                  "sale_date", "royalty_per_unit_cents", "gross_royalty_cents",
                  "reserve_held_cents", "status"],
    "statement": ["publisher_id", "period_start", "period_end",
                  "gross_royalty_cents", "reserve_held_cents",
                  "reserve_released_cents", "provisional_net_cents",
                  "net_payable_cents", "status"],
}


def _coerce(value):
    if isinstance(value, Decimal):
        # spine widths etc. — represent as float for JSON
        return float(value)
    return value


def make_serializer(kind, provisional_fn=None):
    fields = _FIELDS[kind]

    def _ser(rec):
        out = {k: _coerce(rec.get(k)) for k in _COMMON}
        for f in fields:
            out[f] = _coerce(rec.get(f))
        if kind == "statement" and provisional_fn is not None:
            out["provisional_net_cents"] = provisional_fn(rec)
        return out

    return _ser
