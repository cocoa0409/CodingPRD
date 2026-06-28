"""Serialize internal records to JSON-friendly output dicts.

Internal records store datetimes as aware datetime objects; on output they
are formatted as ISO 8601 UTC strings with three fractional digits. Every
entity exposes id/created_at/updated_at/version plus its own fields.
"""
from util import iso

_DATETIME_FIELDS = {
    "created_at", "updated_at", "scheduled_start", "scheduled_end",
    "issued_at", "expires_at", "promised_ready_date", "started_at",
    "window_start", "window_end",
}


def _out(record: dict, fields) -> dict:
    out = {}
    for f in fields:
        val = record.get(f)
        if f in _DATETIME_FIELDS and val is not None:
            out[f] = iso(val)
        else:
            out[f] = val
    return out


_COMMON = ["id", "created_at", "updated_at", "version"]


def customer(r):
    return _out(r, _COMMON + ["email", "full_name", "zip_code", "install_region"])


def project(r):
    return _out(r, _COMMON + [
        "customer_id", "room_type", "status", "financing_application_id",
        "accepted_quote_id", "balance_due_cents", "install_region",
    ])


def design_consult(r):
    return _out(r, _COMMON + [
        "project_id", "designer_user_id", "scheduled_start", "scheduled_end",
        "status", "rendering_url",
    ])


def space_measure(r):
    return _out(r, _COMMON + [
        "project_id", "wall_count", "linear_feet", "ceiling_height_in",
        "confirmed",
    ])


def component_config(r):
    return _out(r, _COMMON + [
        "project_id", "space_measure_id", "material_grade", "line_items",
        "status", "total_units",
    ])


def quote(r):
    return _out(r, _COMMON + [
        "project_id", "component_config_id", "status", "subtotal_cents",
        "discount_cents", "tax_cents", "total_cents", "promo_code",
        "issued_at", "expires_at",
    ])


def deposit(r):
    return _out(r, _COMMON + ["project_id", "quote_id", "amount_cents", "status"])


def manufacture_order(r):
    return _out(r, _COMMON + [
        "project_id", "quote_id", "status", "lead_time_days",
        "promised_ready_date", "started_at",
    ])


def crew(r):
    return _out(r, _COMMON + ["crew_name", "region", "daily_capacity_units", "active"])


def install_job(r):
    return _out(r, _COMMON + [
        "project_id", "manufacture_order_id", "crew_id", "window_start",
        "window_end", "sched_status", "completion_status", "units_booked",
    ])


def change_order(r):
    return _out(r, _COMMON + [
        "project_id", "base_quote_id", "change_type", "revised_config_id",
        "status", "delta_cents",
    ])


def warranty_claim(r):
    return _out(r, _COMMON + [
        "project_id", "install_job_id", "defect_type", "status", "covered",
    ])


def financing_application(r):
    return _out(r, _COMMON + [
        "project_id", "quote_id", "requested_amount_cents", "term_months",
        "status", "approved_amount_cents", "monthly_payment_cents",
    ])
