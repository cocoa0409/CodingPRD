"""Payload factories, timestamp arithmetic, and the PRD's own formulas.

Three groups live here:

* **Timestamp helpers** — the logical clock of PRD §2.5 is a UTC instant, and the
  windows of §3.4 through §3.7 are exact second arithmetic on it.
* **Payload factories** — one per write endpoint, each returning a valid,
  minimal-but-complete body and accepting keyword overrides, so a test that cares
  about one field states only that field.
* **Formula re-implementations** — the §2.6 / §3 arithmetic, so a test can assert
  both the literal the contract works through *and* that the literal is what the
  stated formula produces.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from .constants import (
    AGENT_FEE_PCT,
    BUYOUT_CHANNEL_MULT,
    BUYOUT_TERM_BANDS,
    BUYOUT_TERM_MULT_ABOVE,
    CATEGORY_POST,
    CERT_FILM_PERMIT,
    CERT_LIABILITY_COI,
    DEFAULT_CLOCK,
    EXTRA_ROUND_LABOR_CENTS,
    MONTH_DAYS,
    NEW_DELIVERABLE_LABOR_CENTS,
    NON_UNION,
    OT1_MULT,
    OT1_SPAN_HOURS,
    OT2_MULT,
    OT2_THRESHOLD_HOURS,
    POST_APPROVAL_ALLOWANCE_MULT,
    PRODUCER_FEE_BANDS,
    PRODUCER_FEE_PCT_BELOW,
    RETENTION_MONTH_DAYS,
    REUSE_CYCLE_DAYS,
    REUSE_CYCLE_PCT,
    RUSH_BANDS,
    RUSH_PCT_BEYOND,
    SECONDS_PER_DAY,
    STRAIGHT_TIME_HOURS,
    UNION_PENSION_HEALTH_PCT,
    USAGE_BUYOUT,
)

_FMT = "%Y-%m-%dT%H:%M:%SZ"


# ─── Timestamp arithmetic (PRD §2.5) ───────────────────────────────────────


def parse_ts(value: str) -> datetime:
    """Parse a UTC instant as either the API or this module spells it.

    PRD §2.4 renders stored stamps "with three fractional digits", so a value read
    back off a row may carry them while the literals here do not. Both spellings
    denote the same instant and both must parse.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_ts(value: datetime) -> str:
    """Render a datetime as a whole-second UTC instant."""
    return value.astimezone(timezone.utc).strftime(_FMT)


def plus_seconds(value: str, seconds: int) -> str:
    return fmt_ts(parse_ts(value) + timedelta(seconds=seconds))


def plus_hours(value: str, hours: float) -> str:
    return fmt_ts(parse_ts(value) + timedelta(hours=hours))


def plus_days(value: str, days: int) -> str:
    """Whole-day addition, which is the only kind PRD §3.10 uses."""
    return fmt_ts(parse_ts(value) + timedelta(days=days))


def same_instant(left: str, right: str) -> bool:
    """True when two spellings denote the same UTC instant."""
    return parse_ts(left) == parse_ts(right)


def hours_between(start: str, end: str) -> float:
    return (parse_ts(end) - parse_ts(start)).total_seconds() / 3600.0


def date_part(value: str) -> str:
    """The UTC calendar date of an instant, as `shoot_date` must be spelled."""
    return parse_ts(value).strftime("%Y-%m-%d")


# ─── Rounding (PRD §2.6) ───────────────────────────────────────────────────


def round_half_up(value: Any) -> int:
    """Round to whole cents half up.

    PRD §2.6: "Wherever a monetary amount is derived from a multiplication, the
    result is converted to whole cents by rounding half up — that is, to the
    nearest whole cent, with an exact half rounding away from zero."
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _ceil_div(numerator: Decimal, denominator: Decimal) -> int:
    """Exact ceiling division on decimals, for the two "rounded up" rules."""
    whole = numerator / denominator
    floor = int(whole // 1)
    return floor + (1 if whole != floor else 0)


# ─── Payload factories: project, deliverable, budget line ──────────────────


def project_payload(**over: Any) -> dict:
    """A valid `POST /projects` body (PRD §3.1)."""
    payload = {
        "client_name": "Northwind Bank",
        "campaign_title": "Trust Anthem 2027",
        "creative_brief_summary": "Sixty-second brand film with OLV and social cutdowns.",
        "channel_scope": ["OLV", "SOCIAL"],
        "usage_term_months": 24,
        "budget_ceiling_cents": 50000000,
    }
    payload.update(over)
    return payload


def deliverable_payload(project_id: str, **over: Any) -> dict:
    """A valid `POST /deliverables` body (PRD §3.1)."""
    payload = {
        "project_id": project_id,
        "title": "Hero 60",
        "channel": "OLV",
        "aspect_ratio": "16:9",
        "target_duration_seconds": 60,
        "caption_requirement": "NONE",
        "usage_rights_months": 12,
        "air_date": "2026-12-01T00:00:00Z",
    }
    payload.update(over)
    return payload


def budget_line_payload(project_id: str, **over: Any) -> dict:
    """A valid `POST /budget-lines` body (PRD §3.2)."""
    payload = {
        "project_id": project_id,
        "category": CATEGORY_POST,
        "description": "Post production package",
        "quantity": 2,
        "unit_rate_cents": 1000000,
        "markup_pct": 0,
    }
    payload.update(over)
    return payload


def approve_budget_payload(approved_budget_cents: int) -> dict:
    """A valid `POST /projects/{id}/approve-budget` body (PRD §3.2)."""
    return {"approved_budget_cents": approved_budget_cents}


def handover_payload(handover_recipient: str = "Northwind Brand Studio", **over: Any) -> dict:
    """A valid `POST /projects/{id}/handover` body (PRD §3.10)."""
    payload = {"handover_recipient": handover_recipient}
    payload.update(over)
    return payload


# ─── Payload factories: talent ─────────────────────────────────────────────


def talent_engagement_payload(project_id: str, **over: Any) -> dict:
    """A valid `POST /talent-engagements` body (PRD §3.3)."""
    payload = {
        "project_id": project_id,
        "talent_name": "Dana Reyes",
        "union_affiliation": NON_UNION,
        "compensation_model": USAGE_BUYOUT,
        "session_fee_cents": 250000,
        "session_days": 2,
    }
    payload.update(over)
    return payload


# ─── Payload factories: locations and shoot days ───────────────────────────


def location_payload(**over: Any) -> dict:
    """A valid `POST /locations` body (PRD §3.4)."""
    payload = {
        "name": "Pier 9 Stage",
        "address": "9 Harbor Way, Oakland",
        "stage_count": 2,
        "daily_fee_cents": 400000,
        "insurance_minimum_cents": 100000000,
        "permit_authority": "City Film Office",
    }
    payload.update(over)
    return payload


def shoot_day_payload(project_id: str, location_id: str, **over: Any) -> dict:
    """A valid `POST /shoot-days` body (PRD §3.4).

    `shoot_date` "must equal the UTC date part of `call_time`", so it is derived
    from whatever `call_time` the caller ends up with rather than stated twice.
    """
    payload = {
        "project_id": project_id,
        "location_id": location_id,
        "call_time": "2026-09-10T06:00:00Z",
        "wrap_time": "2026-09-10T16:00:00Z",
    }
    payload.update(over)
    payload.setdefault("shoot_date", date_part(payload["call_time"]))
    return payload


def cancel_payload(cancellation_reason: str = "Client pushed the shoot window.") -> dict:
    """A valid `POST /shoot-days/{id}/cancel` body (PRD §3.7)."""
    return {"cancellation_reason": cancellation_reason}


# ─── Payload factories: compliance certificates ────────────────────────────


def film_permit_payload(project_id: str, shoot_day_id: str, **over: Any) -> dict:
    """A valid `FILM_PERMIT` filing (PRD §3.5).

    "A `FILM_PERMIT` covers exactly one shooting day and must carry a
    `shoot_day_id`", and "may leave the coverage amount at its default".
    """
    payload = {
        "project_id": project_id,
        "cert_type": CERT_FILM_PERMIT,
        "shoot_day_id": shoot_day_id,
        "carrier_or_authority": "City Film Office",
        "reference_code": "PRM-40771",
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2026-09-30T23:59:59Z",
        "fee_cents": 250000,
    }
    payload.update(over)
    return payload


def liability_coi_payload(project_id: str, **over: Any) -> dict:
    """A valid `LIABILITY_COI` filing (PRD §3.5).

    "A `LIABILITY_COI` covers the whole project and must omit `shoot_day_id`
    entirely", and its coverage "must be strictly greater than 0".
    """
    payload = {
        "project_id": project_id,
        "cert_type": CERT_LIABILITY_COI,
        "carrier_or_authority": "Bluewater Mutual",
        "reference_code": "COI-88213",
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-12-31T23:59:59Z",
        "coverage_amount_cents": 100000000,
        "fee_cents": 180000,
    }
    payload.update(over)
    return payload


def cert_decision_payload(decision: str, decision_note: Optional[str] = None) -> dict:
    """A valid `POST /compliance-certs/{id}/decision` body (PRD §3.5)."""
    payload: dict = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


# ─── Payload factories: crew and equipment ─────────────────────────────────


def crew_member_payload(**over: Any) -> dict:
    """A valid `POST /crew-members` body (PRD §3.6)."""
    payload = {
        "full_name": "Ivo Marek",
        "department": "CAMERA",
        "hourly_rate_cents": 5000,
        "min_turnaround_hours": 10,
    }
    payload.update(over)
    return payload


def crew_booking_payload(shoot_day_id: str, crew_member_id: str, **over: Any) -> dict:
    """A valid `POST /crew-bookings` body (PRD §3.6)."""
    payload = {
        "shoot_day_id": shoot_day_id,
        "crew_member_id": crew_member_id,
        "department_role": "1st AC",
        "call_time": "2026-09-10T06:00:00Z",
        "wrap_time": "2026-09-10T16:00:00Z",
    }
    payload.update(over)
    return payload


def release_payload(release_reason: str = "Client cut the package after the tech scout.") -> dict:
    """A valid `POST /crew-bookings/{id}/release` body (PRD §3.6)."""
    return {"release_reason": release_reason}


def equipment_reservation_payload(shoot_day_id: str, **over: Any) -> dict:
    """A valid `POST /equipment-reservations` body (PRD §3.6)."""
    payload = {
        "shoot_day_id": shoot_day_id,
        "vendor_name": "Radiant Rentals",
        "kit_label": "Alexa 35 two-body package",
        "unit_count": 2,
        "daily_rate_cents": 30000,
        "pickup_at": "2026-09-09T12:00:00Z",
        "return_at": "2026-09-11T12:00:00Z",
    }
    payload.update(over)
    return payload


# ─── Payload factories: cuts and decisions ─────────────────────────────────


def cut_payload(deliverable_id: str, expected_deliverable_version: int, **over: Any) -> dict:
    """A valid `POST /deliverable-versions` body (PRD §3.8, §2.10).

    `expected_deliverable_version` is "a non-optional integer field holding the
    client's last observed `version` of the parent deliverable", so it is always
    positional here rather than defaulted.
    """
    payload = {
        "deliverable_id": deliverable_id,
        "expected_deliverable_version": expected_deliverable_version,
        "cut_label": "v1 rough",
        "aspect_ratio": "16:9",
        "duration_seconds": 60,
        "has_captions": False,
        "caption_format": "NONE",
        "file_size_gb": 11.0,
    }
    payload.update(over)
    return payload


def review_decision_payload(decision: str, review_note: Optional[str] = None) -> dict:
    """A valid `POST /deliverable-versions/{id}/review-decision` body (PRD §3.8)."""
    payload: dict = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def change_order_decision_payload(decision: str, decision_note: Optional[str] = None) -> dict:
    """A valid `POST /change-orders/{id}/decision` body (PRD §3.9)."""
    payload: dict = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


# ─── Formula: budget line extended cents (PRD §3.2) ────────────────────────


def expected_extended_cents(quantity: Any, unit_rate_cents: int, markup_pct: Any = 0) -> int:
    """"First the raw amount is the `quantity` multiplied by the `unit_rate_cents`,
    kept exact with no rounding. Then the markup amount is that raw amount
    multiplied by `markup_pct` and rounded half up to whole cents. Finally
    `extended_cents` is the exact raw amount plus the rounded markup amount."
    """
    raw = _dec(quantity) * _dec(unit_rate_cents)
    markup = round_half_up(raw * _dec(markup_pct))
    return int(raw) + markup


# ─── Formula: crew booking cost (PRD §3.6) ─────────────────────────────────


def expected_booking_components(scheduled_hours: Any, hourly_rate_cents: int) -> dict:
    """The three nested tiers and the single final rounding of a booking's cost.

    "`straight_time_cents` is the lesser of the scheduled hours and 10 hours,
    multiplied by the rate; `overtime_tier1_cents` covers the hours from the tenth
    to the twelfth — the lesser of two hours and however much of the span exceeds
    10 hours, never below zero — multiplied by the rate and by 1.5; and
    `overtime_tier2_cents` covers everything beyond the twelfth hour — the span
    minus 12 hours, never below zero — multiplied by the rate and by 2.0."
    """
    hours = _dec(scheduled_hours)
    rate = _dec(hourly_rate_cents)
    straight = min(hours, _dec(STRAIGHT_TIME_HOURS)) * rate
    tier1_hours = min(_dec(OT1_SPAN_HOURS), max(hours - _dec(STRAIGHT_TIME_HOURS), _dec(0)))
    tier1 = tier1_hours * rate * _dec(OT1_MULT)
    tier2_hours = max(hours - _dec(OT2_THRESHOLD_HOURS), _dec(0))
    tier2 = tier2_hours * rate * _dec(OT2_MULT)
    return {
        "scheduled_hours": float(hours),
        "straight_time_cents": round_half_up(straight),
        "overtime_tier1_cents": round_half_up(tier1),
        "overtime_tier2_cents": round_half_up(tier2),
        # "`cost_cents` is the sum of those three components, rounded half up to
        # whole cents exactly once at the end".
        "cost_cents": round_half_up(straight + tier1 + tier2),
    }


# ─── Formula: equipment reservation (PRD §3.6) ─────────────────────────────


def expected_rental_days(pickup_at: str, return_at: str) -> int:
    """"`rental_days` is the span from pickup to return in hours divided by 24 and
    rounded up to a whole day, with a floor of one day".
    """
    hours = _dec(hours_between(pickup_at, return_at))
    return max(_ceil_div(hours, _dec(24)), 1)


def expected_reservation_cost(unit_count: int, daily_rate_cents: int, rental_days: int) -> int:
    """"`total_cost_cents` is the `unit_count` multiplied by the `daily_rate_cents`
    and by `rental_days`."
    """
    return unit_count * daily_rate_cents * rental_days


# ─── Formula: talent compensation (PRD §3.3) ───────────────────────────────


def buyout_channel_multiplier(channel_count: int) -> float:
    """"one channel gives 0.50, two channels 0.85, three channels 1.20, and four or
    more channels 1.60" — "treating any count above four as four".
    """
    return BUYOUT_CHANNEL_MULT[min(max(channel_count, 1), 4)]


def buyout_term_multiplier(term_months: int) -> float:
    """"1.00 when the term is 12 months or fewer, 1.35 when it is more than 12 and
    at most 24, 1.65 when it is more than 24 and at most 36, and 2.00 for any
    longer term."
    """
    for upper, mult in BUYOUT_TERM_BANDS:
        if term_months <= upper:
            return mult
    return BUYOUT_TERM_MULT_ABOVE


def expected_buyout_comp(session_fee_cents: int, session_days: int,
                         channel_count: int, term_months: int) -> dict:
    """The `USAGE_BUYOUT` component set, each component rounded on its own.

    "`usage_load_cents` is then the base fee multiplied by the channel multiplier
    and by the term multiplier, rounded half up to whole cents. `reuse_cycles`,
    `reuse_fee_cents` and `pension_health_cents` are all 0 for a buyout. The
    agent's commission, `agent_fee_cents`, is ten percent of the sum of the base
    fee and the rounded usage load, itself rounded half up. `total_comp_cents` is
    the base fee plus the rounded usage load plus the rounded agent fee."
    """
    base = session_fee_cents * session_days
    usage_load = round_half_up(
        _dec(base) * _dec(buyout_channel_multiplier(channel_count))
        * _dec(buyout_term_multiplier(term_months))
    )
    agent_fee = round_half_up(_dec(base + usage_load) * _dec(AGENT_FEE_PCT))
    return {
        "channel_basis_count": channel_count,
        "term_basis_months": term_months,
        "base_fee_cents": base,
        "usage_load_cents": usage_load,
        "reuse_cycles": 0,
        "reuse_fee_cents": 0,
        "pension_health_cents": 0,
        "agent_fee_cents": agent_fee,
        "total_comp_cents": base + usage_load + agent_fee,
    }


def expected_reuse_cycles(term_months: int) -> int:
    """"`reuse_cycles` is the term in months multiplied by 30 days per month,
    divided by 91 days per cycle, rounded up to a whole cycle."
    """
    days = _dec(term_months) * _dec(MONTH_DAYS)
    return _ceil_div(days, _dec(REUSE_CYCLE_DAYS))


def expected_union_comp(session_fee_cents: int, session_days: int, term_months: int) -> dict:
    """The `UNION_SESSION_REUSE` component set.

    PRD §3.3: "The first cycle is covered by the session fee itself, so `reuse_fee_cents` is
    thirty-five percent of the base fee multiplied by the number of cycles beyond
    the first — using zero whenever the cycle count is one or fewer — rounded half
    up. `pension_health_cents`, the union pension and health contribution, is
    19.75 percent of the sum of the base fee and the rounded reuse fee, rounded
    half up. `agent_fee_cents` is ten percent of that same sum of base fee and
    rounded reuse fee, rounded half up. `total_comp_cents` is the base fee plus the
    rounded reuse fee plus the rounded pension-and-health contribution plus the
    rounded agent fee."
    """
    base = session_fee_cents * session_days
    cycles = expected_reuse_cycles(term_months)
    extra_cycles = max(cycles - 1, 0)
    reuse_fee = round_half_up(_dec(base) * _dec(REUSE_CYCLE_PCT) * _dec(extra_cycles))
    pension_health = round_half_up(_dec(base + reuse_fee) * _dec(UNION_PENSION_HEALTH_PCT))
    agent_fee = round_half_up(_dec(base + reuse_fee) * _dec(AGENT_FEE_PCT))
    return {
        "term_basis_months": term_months,
        "base_fee_cents": base,
        "usage_load_cents": 0,
        "reuse_cycles": cycles,
        "reuse_fee_cents": reuse_fee,
        "pension_health_cents": pension_health,
        "agent_fee_cents": agent_fee,
        "total_comp_cents": base + reuse_fee + pension_health + agent_fee,
    }


# ─── Formula: change order pricing (PRD §3.9) ──────────────────────────────


def whole_days_to_air(clock: str, air_date: str) -> int:
    """"the number of whole days from the logical clock to the deliverable's
    `air_date` is computed by taking the difference in seconds, dividing by 86,400
    seconds per day and discarding any fraction".
    """
    seconds = (parse_ts(air_date) - parse_ts(clock)).total_seconds()
    return int(seconds // SECONDS_PER_DAY) if seconds >= 0 else -int(-seconds // SECONDS_PER_DAY)


def expected_rush_pct(days_to_air: int) -> float:
    """"0.25 when the day count is 7 or fewer, 0.15 when it is more than 7 and 14 or
    fewer, and 0.00 for anything further out."
    """
    for upper, pct in RUSH_BANDS:
        if days_to_air <= upper:
            return pct
    return RUSH_PCT_BEYOND


def expected_producer_fee_pct(subtotal_cents: int) -> float:
    """"`producer_fee_pct` is 0.12 when `subtotal_cents` is at least 1,000,000
    cents, 0.15 when it is at least 500,000 but below 1,000,000, and 0.18 below
    500,000." Keyed on the subtotal, never on the invoiced total.
    """
    for floor, pct in PRODUCER_FEE_BANDS:
        if subtotal_cents >= floor:
            return pct
    return PRODUCER_FEE_PCT_BELOW


def expected_change_order(trigger_reason: str, days_to_air: int) -> dict:
    """The whole pinned pricing chain of PRD §3.9, in its declared order."""
    labor = (
        EXTRA_ROUND_LABOR_CENTS
        if trigger_reason == "REVISION_ROUND_EXCEEDED"
        else NEW_DELIVERABLE_LABOR_CENTS
    )
    rush_pct = expected_rush_pct(days_to_air)
    rush = round_half_up(_dec(labor) * _dec(rush_pct))
    subtotal = labor + rush
    fee_pct = expected_producer_fee_pct(subtotal)
    fee = round_half_up(_dec(subtotal) * _dec(fee_pct))
    return {
        "trigger_reason": trigger_reason,
        "labor_cents": labor,
        "rush_pct": rush_pct,
        "rush_cents": rush,
        "subtotal_cents": subtotal,
        "producer_fee_pct": fee_pct,
        "producer_fee_cents": fee,
        "amount_cents": subtotal + fee,
    }


# ─── Formula: the allowance gate and retention window ──────────────────────


def expected_allowance(budget_ceiling_cents: int, budget_approved: bool) -> int:
    """The allowance of PRD §2.8, which widens by five percent at sign-off.

    PRD §2.8: "The allowance depends on where the project stands: while the project's
    `status` is `DRAFT` or `SCOPED` the allowance equals `budget_ceiling_cents` exactly,
    with no tolerance; once the budget has been approved — that is, for `IN_PRODUCTION`,
    `IN_POST` and any later status — the allowance is `budget_ceiling_cents` multiplied by
    1.05, rounded half up to whole cents, so the production may run five percent hot
    against its contracted ceiling."
    """
    if not budget_approved:
        return budget_ceiling_cents
    return round_half_up(_dec(budget_ceiling_cents) * _dec(POST_APPROVAL_ALLOWANCE_MULT))


def expected_retention_expiry(handover_at: str, retention_months: int) -> str:
    """"`retention_expires_at` is `handover_at` plus the project's
    `raw_footage_retention_months` multiplied by 30 days, using whole days added to
    the handover instant; calendar month lengths are deliberately not used, so a
    12-month retention term is exactly 360 days."
    """
    return plus_days(handover_at, retention_months * RETENTION_MONTH_DAYS)


# The clock default, re-exported so tests do not import two modules for one value.
CLOCK_DEFAULT = DEFAULT_CLOCK
