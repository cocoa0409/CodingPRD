"""turn_service_charge, line_penalties and the eight-step period_billing_rollup."""
from decimal import Decimal
from fractions import Fraction

import constants as C
from domain import apply_changes, lines_of_period, resources_of_turn
from store import db, rhu, rhu_cents


def _station_of_turn(turn):
    return db.stations.get(turn["station_id"])


def ground_time_tier(excess_minutes):
    if excess_minutes <= C.EXCESS_TIER_1_MINUTES:
        return "TIER_1"
    if excess_minutes <= (C.EXCESS_TIER_1_MINUTES + C.EXCESS_TIER_2_MINUTES):
        return "TIER_2"
    return "TIER_3"


def excess_charge_cents(excess_minutes):
    """Marginal tiers: 900 for the first 15, 1400 for the next 30, 2100 beyond."""
    tier1 = min(excess_minutes, C.EXCESS_TIER_1_MINUTES)
    tier2 = min(max(excess_minutes - C.EXCESS_TIER_1_MINUTES, 0), C.EXCESS_TIER_2_MINUTES)
    tier3 = max(excess_minutes - (C.EXCESS_TIER_1_MINUTES + C.EXCESS_TIER_2_MINUTES), 0)
    return (C.EXCESS_TIER_1_RATE * tier1
            + C.EXCESS_TIER_2_RATE * tier2
            + C.EXCESS_TIER_3_RATE * tier3)


def subcontract_factor(turn):
    for row in resources_of_turn(turn["id"]):
        if row["resource_kind"] != "AGENT":
            continue
        if row["status"] not in ("RESERVED", "COMMITTED", "RELEASED"):
            continue
        agent = db.agents.get(row["agent_id"])
        if agent and agent["employment_type"] == "SUBCONTRACTED":
            return C.SUBCONTRACT_FACTOR
    return C.DIRECT_FACTOR


def charged_ground_minutes(line, turn, variant):
    """Which ground time enters the charge (variant-dependent, PRD 3.9)."""
    if variant == "PROVISIONAL":
        return turn["scheduled_ground_minutes"]
    if turn["status"] == "COMPLETED" and turn["actual_ground_minutes"] is not None:
        return turn["actual_ground_minutes"]
    return turn["scheduled_ground_minutes"]


def compute_charge(line, variant):
    """turn_service_charge -> dict of the charge fields for the given variant."""
    turn = db.turns[line["turn_id"]]
    station = _station_of_turn(turn)
    snapshot = line["turn_type_snapshot"]
    base = C.BASE_RATE_CENTS[snapshot]
    standard = C.STD_GROUND_MIN[snapshot]

    charged = charged_ground_minutes(line, turn, variant)
    excess = max(0, charged - standard)
    charge = excess_charge_cents(excess)

    season_multiplier = (
        C.WINTER_MULTIPLIER if station["season_code"] == "WINTER" else C.SUMMER_MULTIPLIER
    )
    factor = subcontract_factor(turn)

    raw = (Decimal(base) + Decimal(charge)) * season_multiplier * factor
    gross = rhu_cents(raw)
    gross = max(gross, base)
    gross = min(gross, base * C.GROSS_CAP_MULTIPLE)
    return {
        "base_rate_cents": base,
        "charged_ground_minutes": charged,
        "excess_minutes": excess,
        "ground_time_tier": ground_time_tier(excess),
        "gross_amount_cents": gross,
    }


def compute_penalties(line, variant, gross_amount_cents):
    """line_penalties -> (otp_penalty_cents, damage_penalty_cents)."""
    if variant == "PROVISIONAL":
        return 0, 0
    turn = db.turns[line["turn_id"]]
    station = _station_of_turn(turn)

    otp = 0
    if turn["otp_result"] == "DELAYED" and turn["delay_code"] in C.HANDLER_DELAY_CODES:
        otp = rhu_cents(Decimal(gross_amount_cents) * C.OTP_PENALTY_PCT)

    damage = 0
    for incident in db.incidents.values():
        if incident["turn_id"] != line["turn_id"]:
            continue
        if incident["status"] != "CLOSED":
            continue
        if incident["liability_party"] != "HANDLER":
            continue
        if incident["incident_type"] not in C.DAMAGE_INCIDENT_TYPES:
            continue
        base_penalty = Decimal(C.DAMAGE_PENALTY_CENTS[incident["severity"]])
        damage += rhu_cents(base_penalty * station["damage_penalty_multiplier"])
    return otp, damage


def _rebate_tier(gross_total, any_provisional):
    if any_provisional:
        return "NONE"
    if gross_total >= C.REBATE_TIER_B_MIN_CENTS:
        return "TIER_B"
    if gross_total >= C.REBATE_TIER_A_MIN_CENTS:
        return "TIER_A"
    return "NONE"


def rollup_period(period):
    """The eight pinned steps of period_billing_rollup (PRD 3.9)."""
    lines = sorted(
        [l for l in lines_of_period(period["id"]) if l["status"] != "VOID"],
        key=lambda l: (l["created_at"], l["_seq"]),
    )

    # STEP 1 - recompute every non-VOID line's gross under its current variant.
    charges = {}
    for line in lines:
        charge = compute_charge(line, line["status"])
        charges[line["id"]] = charge

    # STEP 2 - round per line, then add.
    gross_total = sum(charges[l["id"]]["gross_amount_cents"] for l in lines)

    # STEP 3 - tier from the STEP 2 total; NONE while any line is PROVISIONAL.
    any_provisional = any(l["status"] == "PROVISIONAL" for l in lines)
    tier = _rebate_tier(gross_total, any_provisional)

    # STEP 4 - period rebate.
    rebate_cents = rhu_cents(Decimal(gross_total) * C.REBATE_PCT[tier])

    # STEP 5 - largest-remainder allocation across the non-VOID FINAL lines.
    allocation = {l["id"]: 0 for l in lines}
    final_lines = [l for l in lines if l["status"] == "FINAL"]
    if rebate_cents and gross_total > 0 and final_lines:
        shares = []
        floor_total = 0
        for line in final_lines:
            exact = Fraction(rebate_cents * charges[line["id"]]["gross_amount_cents"], gross_total)
            floor_part = exact.numerator // exact.denominator
            remainder = exact - floor_part
            floor_total += floor_part
            allocation[line["id"]] = floor_part
            shares.append((remainder, charges[line["id"]]["gross_amount_cents"], line))
        leftover = rebate_cents - floor_total
        shares.sort(key=lambda s: (-s[0], -s[1], s[2]["created_at"], s[2]["_seq"]))
        for index in range(min(leftover, len(shares))):
            allocation[shares[index][2]["id"]] += 1

    # STEP 6 - per-line penalties, summed into the period.
    penalties = {}
    for line in lines:
        penalties[line["id"]] = compute_penalties(
            line, line["status"], charges[line["id"]]["gross_amount_cents"]
        )
    otp_total = sum(p[0] for p in penalties.values())
    damage_total = sum(p[1] for p in penalties.values())

    # STEP 7 - per-line net.
    for line in lines:
        charge = charges[line["id"]]
        otp, damage = penalties[line["id"]]
        alloc = allocation[line["id"]]
        net = charge["gross_amount_cents"] - otp - damage + alloc
        changes = dict(charge)
        changes.update({
            "otp_penalty_cents": otp,
            "damage_penalty_cents": damage,
            "rebate_alloc_cents": alloc,
            "net_amount_cents": net,
        })
        apply_changes(line, changes)

    # STEP 8 - period ledgers.
    accrued = sum(
        l["net_amount_cents"] for l in lines if l["status"] in ("PROVISIONAL", "FINAL")
    )
    net_total = gross_total - otp_total - damage_total + rebate_cents
    line_count = sum(1 for l in lines if l["status"] in ("PROVISIONAL", "FINAL"))
    apply_changes(period, {
        "line_count": line_count,
        "gross_total_cents": gross_total,
        "otp_penalty_cents": otp_total,
        "damage_penalty_cents": damage_total,
        "rebate_tier": tier,
        "rebate_cents": rebate_cents,
        "accrued_cents": accrued,
        "net_total_cents": net_total,
    })


def projected_finalization_penalties(period):
    """Dry run of the FINAL variant used by the penalty-cap gate."""
    lines = [l for l in lines_of_period(period["id"]) if l["status"] != "VOID"]
    otp_total = 0
    damage_total = 0
    for line in lines:
        charge = compute_charge(line, "FINAL")
        otp, damage = compute_penalties(line, "FINAL", charge["gross_amount_cents"])
        otp_total += otp
        damage_total += damage
    return otp_total, damage_total
