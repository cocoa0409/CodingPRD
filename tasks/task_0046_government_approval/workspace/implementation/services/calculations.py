"""Calculation rules: deadline, SLA evaluator, and fee breakdown."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

import db
from config import (
    APPLICATION_TERMINAL,
    CAP_SURCHARGE_CENTS,
    ESCALATION_PCT,
    HANDLING_RATE_BP,
    OVERHEAD_RATE_BP,
    SURCHARGE_PER_ROUND_CENTS,
    WORKING_DAY_SECONDS,
)


# ---------------------------------------------------------------------------
# derive_application_deadline
# ---------------------------------------------------------------------------

def derive_application_deadline(application: dict, version: dict,
                                variant: str = "committed"):
    """Return ISO timestamp of the application's deadline_at, or None."""
    if not application.get("clock_started_at"):
        return None
    if variant == "committed":
        base_days = version["committed_time_limit_days"]
    else:
        base_days = version["statutory_time_limit_days"]
    base_window_seconds = base_days * WORKING_DAY_SECONDS
    started = db.parse_iso(application["clock_started_at"])
    raw_deadline = started.timestamp() + base_window_seconds
    adjusted = raw_deadline + application.get("total_paused_seconds", 0)
    from datetime import datetime, timezone
    return db.format_ts(datetime.fromtimestamp(adjusted, tz=timezone.utc))


# ---------------------------------------------------------------------------
# time_limit_warning_evaluator
# ---------------------------------------------------------------------------

def time_limit_warning(application: dict, version: dict) -> dict:
    if not application.get("clock_started_at"):
        return {
            "elapsed_seconds": 0,
            "active_elapsed_seconds": 0,
            "committed_seconds": version["committed_time_limit_days"] * WORKING_DAY_SECONDS,
            "pct": 0,
            "status": "NOT_STARTED",
            "deadline_at": None,
            "statutory_deadline_at": None,
            "escalation_alert": False,
        }
    now = db.now_dt()
    started = db.parse_iso(application["clock_started_at"])
    total_elapsed = int((now - started).total_seconds())
    paused = application.get("total_paused_seconds", 0)
    active_elapsed = total_elapsed - paused
    committed_seconds = version["committed_time_limit_days"] * WORKING_DAY_SECONDS
    if committed_seconds <= 0:
        pct = 0
    else:
        pct = (active_elapsed * 100) // committed_seconds
    warning_pct = version["warning_threshold_pct"]
    if pct < warning_pct:
        status = "ON_TRACK"
    elif pct < 100:
        status = "WARNING"
    else:
        status = "OVERDUE"
    return {
        "elapsed_seconds": total_elapsed,
        "active_elapsed_seconds": active_elapsed,
        "committed_seconds": committed_seconds,
        "pct": pct,
        "status": status,
        "deadline_at": derive_application_deadline(application, version, "committed"),
        "statutory_deadline_at": derive_application_deadline(application, version, "statutory"),
        "escalation_alert": pct >= ESCALATION_PCT,
    }


# ---------------------------------------------------------------------------
# certificate_fee_breakdown
# ---------------------------------------------------------------------------

def fee_breakdown(application: dict, version: dict) -> dict:
    base_fee_cents = version["fee_amount_cents"]
    cr = application.get("correction_round", 0)
    if cr == 0:
        surcharge_subtotal_cents = 0
    elif cr <= 2:
        surcharge_subtotal_cents = SURCHARGE_PER_ROUND_CENTS * cr
    else:
        surcharge_subtotal_cents = CAP_SURCHARGE_CENTS

    handling_line_cents = math.ceil(base_fee_cents * HANDLING_RATE_BP / 10000)
    admin_overhead_cents = math.ceil(surcharge_subtotal_cents * OVERHEAD_RATE_BP / 10000)
    total_cents = (base_fee_cents + handling_line_cents
                   + surcharge_subtotal_cents + admin_overhead_cents)

    if application.get("review_status") in APPLICATION_TERMINAL:
        variant = "final"
    else:
        variant = "provisional"

    return {
        "base_fee_cents": base_fee_cents,
        "surcharge_subtotal_cents": surcharge_subtotal_cents,
        "handling_line_cents": handling_line_cents,
        "admin_overhead_cents": admin_overhead_cents,
        "total_cents": total_cents,
        "correction_round": cr,
        "variant": variant,
    }


# ---------------------------------------------------------------------------
# Round-half-up formatter for certificate variable rendering.
# ---------------------------------------------------------------------------

def format_variable(value):
    """Render a variable into a string with round-half-up to 2dp on numbers."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) or isinstance(value, Decimal):
        d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{d:.2f}"
    if value is None:
        return ""
    return str(value)
