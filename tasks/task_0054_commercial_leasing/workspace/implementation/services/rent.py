"""Rent schedule generation per §3.4."""
from decimal import Decimal

from clock import now, iso, parse_iso
import db
from services.calendar_utils import (
    iter_months, days_in_month, intersect_days, first_of_month, months_between,
)
from services.money import D, round_half_up


DAYS_PER_YEAR = Decimal("365.25")


def _monthly_for_period(lease: dict, m_start, m_end) -> int:
    """Compute the monthly rent (integer cents) in effect for month M starting at m_start."""
    base = lease["base_monthly_rent_cents"]
    mode = lease["escalation_mode"]
    pct_bps = lease.get("escalation_pct_bps") or 0
    start_date = parse_iso(lease["start_date"])
    if mode == "NONE":
        return base
    if mode in ("ANNUAL", "BIENNIAL"):
        # years_elapsed = floor( (M.start - start_date) / 365.25 )
        elapsed_days = (m_start - start_date).days
        if elapsed_days < 0:
            elapsed_days = 0
        divisor = DAYS_PER_YEAR if mode == "ANNUAL" else (DAYS_PER_YEAR * Decimal("2"))
        years_elapsed = int((Decimal(elapsed_days) / divisor).to_integral_value(rounding="ROUND_FLOOR"))
        if years_elapsed < 0:
            years_elapsed = 0
        factor = (Decimal(10000) + Decimal(pct_bps)) / Decimal(10000)
        rent = Decimal(base) * (factor ** years_elapsed)
        return round_half_up(rent)
    if mode == "STEPPED":
        # Table lookup: row with largest index whose effective_from <= M.start
        sched = lease.get("stepped_schedule") or []
        # sort by effective_from ascending
        rows = sorted(sched, key=lambda r: r["effective_from"])
        chosen = None
        for r in rows:
            eff = parse_iso(r["effective_from"])
            if eff <= m_start:
                chosen = r
            else:
                break
        if chosen is None:
            # Should not happen if stepped_schedule is valid
            return base
        return int(chosen["monthly_rent_cents"])
    return base


def _create_rsi(lease_id: str, period_start, period_end,
                gross: int, offset: int, net: int) -> dict:
    rsi = {
        "lease_id": lease_id,
        "period_start": iso(period_start),
        "period_end": iso(period_end),
        "gross_rent_cents": int(gross),
        "rent_free_offset_cents": int(offset),
        "net_rent_cents": int(net),
        "status": "PENDING",
    }
    db.stamp_create(rsi, common_fields=False)
    db.rent_schedule_items[rsi["id"]] = rsi
    return rsi


def generate_for_lease(lease: dict, *, from_date=None) -> list:
    """Generate (or regenerate) RentScheduleItem rows for the given lease.

    If from_date is provided: delete rows with period_start >= from_date and regenerate
    only those months. Otherwise regenerate from scratch (deletes all existing rows).
    """
    lease_id = lease["id"]
    start_date = parse_iso(lease["start_date"])
    end_date = parse_iso(lease["end_date"])
    rent_free_days = int(lease.get("rent_free_days") or 0)

    # Remove rows to be regenerated.
    if from_date is None:
        ids_to_remove = [rid for rid, r in db.rent_schedule_items.items()
                         if r["lease_id"] == lease_id]
    else:
        ids_to_remove = []
        for rid, r in db.rent_schedule_items.items():
            if r["lease_id"] != lease_id:
                continue
            if parse_iso(r["period_start"]) >= from_date:
                ids_to_remove.append(rid)
    for rid in ids_to_remove:
        del db.rent_schedule_items[rid]

    # Determine generation window start
    if from_date is None:
        gen_start = start_date
    else:
        gen_start = max(start_date, from_date)

    created = []
    for m_start, m_end in iter_months(gen_start, end_date):
        if m_end <= start_date:
            continue
        monthly = _monthly_for_period(lease, m_start, m_end)
        dim = days_in_month(m_start.year, m_start.month)
        active_days = intersect_days(m_start, m_end, start_date, end_date)
        if active_days <= 0:
            continue
        # gross_rent = round_half_up(monthly * active_days / days_in_month)
        gross = round_half_up(D(monthly) * D(active_days) / D(dim))
        # free days falling in this month
        days_from_start_to_m_start = max(0, (m_start - start_date).days)
        # range available in this month (from start_date or m_start to end of active span)
        days_from_start_to_m_active_end = days_from_start_to_m_start + active_days
        free_days_in_this_month = max(
            0,
            min(rent_free_days, days_from_start_to_m_active_end) - days_from_start_to_m_start,
        )
        offset = round_half_up(D(monthly) * D(free_days_in_this_month) / D(dim))
        net = max(0, gross - offset)
        rsi = _create_rsi(lease_id, m_start, m_end, gross, offset, net)
        created.append(rsi)
    return created


def void_after(lease_id: str, terminated_on) -> int:
    """Mark every RentScheduleItem with period_start > terminated_on as VOIDED."""
    count = 0
    for r in db.rent_schedule_items.values():
        if r["lease_id"] != lease_id:
            continue
        if parse_iso(r["period_start"]) > terminated_on:
            if r["status"] != "VOIDED":
                r["status"] = "VOIDED"
                count += 1
    return count


def validate_stepped_schedule(schedule, start_date, end_date) -> None:
    """Validate stepped schedule rows per §3.3."""
    from errors import err
    if not isinstance(schedule, list) or len(schedule) == 0:
        raise err("ERR_STEPPED_SCHEDULE_INVALID", "stepped_schedule must be a non-empty array")
    parsed = []
    for i, row in enumerate(schedule):
        if not isinstance(row, dict):
            raise err("ERR_STEPPED_SCHEDULE_INVALID", "stepped_schedule entry must be object")
        if "effective_from" not in row or "monthly_rent_cents" not in row:
            raise err("ERR_STEPPED_SCHEDULE_INVALID",
                      "stepped_schedule entry must have effective_from and monthly_rent_cents")
        try:
            eff = parse_iso(row["effective_from"])
        except Exception:
            raise err("ERR_STEPPED_SCHEDULE_INVALID", "effective_from must be ISO 8601")
        m = row["monthly_rent_cents"]
        if isinstance(m, bool) or not isinstance(m, int):
            raise err("ERR_STEPPED_SCHEDULE_INVALID", "monthly_rent_cents must be integer")
        parsed.append((eff, m))
    # strictly ascending
    for i in range(1, len(parsed)):
        if not (parsed[i][0] > parsed[i - 1][0]):
            raise err("ERR_STEPPED_SCHEDULE_INVALID",
                      "stepped_schedule must be strictly ascending in effective_from")
    if parsed[0][0] != start_date:
        raise err("ERR_STEPPED_SCHEDULE_INVALID",
                  "stepped_schedule first effective_from must equal start_date")
    if parsed[-1][0] >= end_date:
        raise err("ERR_STEPPED_SCHEDULE_INVALID",
                  "stepped_schedule last effective_from must be strictly before end_date")
