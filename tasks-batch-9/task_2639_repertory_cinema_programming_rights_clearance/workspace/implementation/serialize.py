"""Wire serialisers.  Every entity carries id/created_at/updated_at/version."""
from calc import refresh_member
from timeutil import fmt_day, fmt_instant


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "updated_at": fmt_instant(row["updated_at"]),
        "version": row["version"],
    }


def _pick(row, out, names):
    for name in names:
        out[name] = row.get(name)
    return out


VENUE_FIELDS = ("name", "seat_capacity", "house_hold_seats", "trailer_reel_minutes",
                "turnaround_minutes", "min_useful_gap_minutes", "dcp_ingest_lane_count",
                "open_local_time", "last_start_local_time", "utc_offset_minutes",
                "max_first_run_share", "weekly_repertory_target", "supported_formats",
                "base_house_nut_weekly_cents")

DISTRIBUTOR_FIELDS = ("name", "contact_email", "default_terms_variant",
                      "default_min_run_days", "default_distributor_share_pct",
                      "requires_advance_guarantee")

TITLE_FIELDS = ("title_name", "release_year", "runtime_minutes", "is_first_run",
                "native_format", "rights_holder_distributor_id")

BOOKING_FIELDS = ("title_id", "distributor_id", "venue_id", "supersedes_booking_id",
                  "terms_variant", "house_nut_cents", "distributor_share_pct",
                  "guarantee_cents", "min_run_days", "status", "round_count",
                  "scheduled_showtime_count", "actual_playing_days", "min_run_compliant",
                  "min_run_penalty_cents", "created_by_user_id", "confirmed_by_user_id")

OFFER_FIELDS = ("booking_id", "round_index", "proposed_by", "proposed_house_nut_cents",
                "proposed_distributor_share_pct", "proposed_min_run_days",
                "proposed_guarantee_cents", "outcome", "submitted_by_user_id")

CLEARANCE_FIELDS = ("title_id", "booking_id", "licensor_name", "license_fee_cents",
                    "territory", "max_screenings", "source_format", "screenings_used",
                    "screenings_remaining", "status", "submitted_by_user_id",
                    "cleared_by_user_id", "change_request_note", "revoked_reason")

ASSET_FIELDS = ("title_id", "source_distributor_id", "venue_id", "format",
                "is_encrypted", "carrier_ref", "status")

KEY_FIELDS = ("dcp_asset_id", "venue_id", "server_ref", "status", "revoked_reason")

SHOWTIME_FIELDS = ("venue_id", "title_id", "booking_id", "clearance_id", "dcp_asset_id",
                   "strand", "series_label", "extra_minutes", "base_price_cents",
                   "surcharge_cents", "format", "status", "sale_status",
                   "playback_status", "seats_sold", "seats_available", "gross_cents",
                   "admissions_count", "slot_score", "cancel_reason")

EVENT_FIELDS = ("showtime_id", "event_type", "guest_name", "extra_minutes",
                "surcharge_cents", "guest_fee_cents", "status", "displaced_showtime_ids")

ORDER_FIELDS = ("showtime_id", "member_id", "quantity", "comp_quantity",
                "purchaser_email", "unit_price_cents", "line_subtotal_cents",
                "facility_fee_cents", "applied_credit_cents", "total_cents",
                "status", "refund_destination")

MEMBER_FIELDS = ("full_name", "email", "status", "rolling_donation_cents",
                 "fiscal_ytd_donation_cents", "rolling_tier", "fiscal_tier",
                 "effective_tier", "discount_pct", "advance_access_hours",
                 "comp_tickets_granted", "comp_tickets_remaining", "credit_balance_cents")

SETTLEMENT_FIELDS = ("booking_id", "variant", "status", "box_office_cents",
                     "facility_fee_total_cents", "adjusted_gross_cents", "playing_days",
                     "proration_factor", "house_nut_applied_cents", "film_rent_cents",
                     "cinema_retained_cents", "min_run_penalty_cents",
                     "submitted_by_user_id", "finalized_by_user_id", "dispute_note")


def venue(row):
    return _pick(row, _common(row), VENUE_FIELDS)


def distributor(row):
    return _pick(row, _common(row), DISTRIBUTOR_FIELDS)


def title(row):
    return _pick(row, _common(row), TITLE_FIELDS)


def booking(row):
    out = _pick(row, _common(row), BOOKING_FIELDS)
    out["engagement_start_date"] = fmt_day(row["engagement_start_date"])
    out["engagement_end_date"] = fmt_day(row["engagement_end_date"])
    return out


def offer(row):
    out = _pick(row, _common(row), OFFER_FIELDS)
    out["expires_at"] = fmt_instant(row["expires_at"])
    return out


def clearance(row):
    out = _pick(row, _common(row), CLEARANCE_FIELDS)
    out["window_start_date"] = fmt_day(row["window_start_date"])
    out["window_end_date"] = fmt_day(row["window_end_date"])
    return out


def asset(row):
    out = _pick(row, _common(row), ASSET_FIELDS)
    out["ingest_window_start_at"] = fmt_instant(row["ingest_window_start_at"])
    out["ingest_window_end_at"] = fmt_instant(row["ingest_window_end_at"])
    out["received_at"] = fmt_instant(row["received_at"])
    out["ingested_at"] = fmt_instant(row["ingested_at"])
    return out


def key(row):
    out = _pick(row, _common(row), KEY_FIELDS)
    out["valid_from"] = fmt_instant(row["valid_from"])
    out["valid_until"] = fmt_instant(row["valid_until"])
    return out


def showtime(row):
    out = _pick(row, _common(row), SHOWTIME_FIELDS)
    out["start_at"] = fmt_instant(row["start_at"])
    out["end_at"] = fmt_instant(row["end_at"])
    out["blocked_until"] = fmt_instant(row["blocked_until"])
    out["public_sale_opens_at"] = fmt_instant(row["public_sale_opens_at"])
    return out


def event(row):
    return _pick(row, _common(row), EVENT_FIELDS)


def order(row):
    return _pick(row, _common(row), ORDER_FIELDS)


def member(row):
    refresh_member(row)
    out = _pick(row, _common(row), MEMBER_FIELDS)
    out["join_date"] = fmt_day(row["join_date"])
    out["expires_at"] = fmt_instant(row["expires_at"])
    out["donations"] = [
        {"amount_cents": d["amount_cents"], "received_at": fmt_instant(d["received_at"])}
        for d in row["donations"]
    ]
    return out


def settlement(row):
    return _pick(row, _common(row), SETTLEMENT_FIELDS)
