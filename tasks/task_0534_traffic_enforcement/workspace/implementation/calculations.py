from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from clock import parse_iso

SPEED_BAND_1_MULT = Decimal("1.0")
SPEED_BAND_2_MULT = Decimal("1.5")
SPEED_BAND_3_MULT = Decimal("2.5")


def round_half_up(value):
    """Round a Decimal/number to the nearest whole cent (integer), half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def band_multiplier(over):
    if over <= 10:
        return SPEED_BAND_1_MULT
    elif over <= 20:
        return SPEED_BAND_2_MULT
    else:
        return SPEED_BAND_3_MULT


def compute_statutory_fine(db, program, camera, citation, notice_time):
    """fine_schedule_statutory: returns assessed_amount_cents (integer).

    notice_time is the citation's notice_issued_at_utc (an aware datetime).
    """
    if camera["camera_type"] == "RED_LIGHT":
        base = int(program["base_red_light_fine_cents"])
    else:  # SPEED
        over = citation["measured_speed_mph"] - camera["speed_limit_mph"]
        mult = band_multiplier(over)
        base = round_half_up(Decimal(int(program["base_speed_fine_cents"])) * mult)

    # Repeat-offender surcharge: count prior citations for SAME owner in this Program
    # with qualifying status and notice time within (now - window, now].
    owner_id = citation["registered_owner_id"]
    window_days = int(program["repeat_offender_window_days"])
    lower_bound = notice_time - timedelta(days=window_days)  # exclusive
    qualifying_statuses = {
        "CITED", "CONTESTED", "HEARING_SCHEDULED",
        "ADJUDICATED_UPHELD", "PAID", "DELINQUENT",
    }
    prior_count = 0
    for c in db.citations.values():
        if c["id"] == citation["id"]:
            continue
        if c["program_id"] != program["id"]:
            continue
        if c.get("registered_owner_id") != owner_id:
            continue
        if c["status"] not in qualifying_statuses:
            continue
        nissued = c.get("notice_issued_at_utc")
        if not nissued:
            continue
        n_dt = parse_iso(nissued)
        # half-open lower (strictly later than lower_bound), inclusive upper (<= notice_time)
        if lower_bound < n_dt <= notice_time:
            prior_count += 1

    if prior_count >= 1:
        surcharge_factor = Decimal(1) + Decimal(str(program["repeat_offender_surcharge_pct"]))
        base = round_half_up(Decimal(base) * surcharge_factor)

    assessed = base + int(program["admin_fee_cents"])
    return assessed


def compute_adjudicated_reduced(program, reduced_amount_cents):
    """fine_schedule_adjudicated: reduced fine + admin fee (integer addition)."""
    return int(reduced_amount_cents) + int(program["admin_fee_cents"])


def amount_owed_total(program, citation):
    """Total needed to reach PAID given current escalation."""
    owed = int(citation.get("adjudicated_amount_cents") or 0)
    if citation.get("escalation_stage") == "DELINQUENT":
        owed += int(program["late_fee_cents"])
    return owed


def compute_vendor_share(program, citation, contract):
    """vendor_revenue_share: applied share (integer) respecting cap.

    Returns the share to accrue (does not mutate).
    """
    fine_portion = int(citation["adjudicated_amount_cents"]) - int(program["admin_fee_cents"])
    if fine_portion < 0:
        fine_portion = 0
    raw_share = round_half_up(Decimal(fine_portion) * Decimal(str(contract["revenue_share_pct"])))
    cap = contract.get("monthly_cap_cents")
    if cap is not None:
        headroom = max(0, int(cap) - int(contract["accrued_vendor_share_cents"]))
        share = min(raw_share, headroom)
    else:
        share = raw_share
    return share
