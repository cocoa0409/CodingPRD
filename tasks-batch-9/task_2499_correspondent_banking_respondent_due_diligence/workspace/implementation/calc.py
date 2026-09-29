"""Deterministic calculations (PRD 2.6, 3.1, 3.3, 3.4, 3.6-3.9)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import clock
import store
from errors import fail
from validate import dec, q2, q4

D0 = Decimal("0")

# --- 3.4 control domains -----------------------------------------------------
CONTROL_DOMAINS = (
    "GOVERNANCE",
    "KYC_ONBOARDING",
    "TRANSACTION_MONITORING",
    "SANCTIONS_SCREENING",
    "PEP_HANDLING",
    "TRAINING",
    "AUDIT",
    "NESTED_CONTROLS",
)

DOMAIN_WEIGHTS = {
    "GOVERNANCE": Decimal("0.10"),
    "KYC_ONBOARDING": Decimal("0.18"),
    "TRANSACTION_MONITORING": Decimal("0.20"),
    "SANCTIONS_SCREENING": Decimal("0.22"),
    "PEP_HANDLING": Decimal("0.10"),
    "TRAINING": Decimal("0.05"),
    "AUDIT": Decimal("0.08"),
    "NESTED_CONTROLS": Decimal("0.07"),
}

RATING_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "PROHIBITED": 3}

CADENCE_MONTHS = {"LOW": 36, "MEDIUM": 24, "HIGH": 12, "PROHIBITED": 0, "UNRATED": 0}

NESTED_STATE_WEIGHT = {
    "DISCLOSED": 1,
    "UNDISCLOSED_DETECTED": 5,
    "CONFIRMED": 3,
    "SUSPENDED": 3,
    "PROHIBITED": 0,
    "TERMINATED": 0,
}

NESTED_LIVE = ("DISCLOSED", "UNDISCLOSED_DETECTED", "CONFIRMED", "SUSPENDED")

RATING_FACTOR = {
    "UNRATED": Decimal("1.30"),
    "LOW": Decimal("1.30"),
    "MEDIUM": Decimal("1.15"),
    "HIGH": Decimal("1.00"),
    "PROHIBITED": Decimal("0.85"),
}

SLA_BASE = {"CRITICAL": 24, "HIGH": 72, "MEDIUM": 168, "LOW": 336}

NOTICE_BASE = {
    "UNRESPONSIVE": 30,
    "SANCTIONS_EXPOSURE": 0,
    "PROHIBITED_NESTING": 15,
    "REGULATORY_ACTION": 15,
    "RISK_APPETITE": 60,
    "COMMERCIAL": 90,
}

TIER_POINTS = {"TIER_1": Decimal("12.0"), "TIER_2": Decimal("7.0"), "TIER_3": Decimal("3.0")}
RELIABILITY = {"A": Decimal("1.00"), "B": Decimal("0.75"), "C": Decimal("0.50")}

AGGREGATE_CEILING = Decimal("500000000.00")
CORRIDOR_FLOOR = Decimal("10000.00")


# ------------------------------------------------------- 3.1 jurisdiction ---

def jurisdiction_risk_points(profile):
    sanctions = {"PERMITTED": 0, "RESTRICTED": 8, "COMPREHENSIVELY_SANCTIONED": 20}
    listing = {"NONE": 0, "INCREASED_MONITORING": 5, "CALL_FOR_ACTION": 12}
    total = Decimal(sanctions[profile["sanctions_status"]])
    total += Decimal(listing[profile["fatf_listing"]])
    total += Decimal(3) if profile["secrecy_flag"] else D0
    total += dec(profile["basel_aml_index"]) * Decimal("2.0")
    if total > Decimal("40.00"):
        total = Decimal("40.00")
    return q2(total)


def home_profile(respondent):
    return store.jurisdiction_by_code(respondent["home_jurisdiction_code"])


def home_sanctioned(respondent):
    prof = home_profile(respondent)
    return prof is not None and prof["sanctions_status"] == "COMPREHENSIVELY_SANCTIONED"


# ----------------------------------------------------------- 3.3 ownership ---

def owner_chain(owner):
    """The owner plus every ancestor, nearest first."""
    chain = [owner]
    seen = {owner["id"]}
    cur = owner
    while cur.get("parent_owner_id"):
        parent = store.get("owners", cur["parent_owner_id"])
        if parent is None or parent["id"] in seen:
            break
        chain.append(parent)
        seen.add(parent["id"])
        cur = parent
    return chain


def effective_ownership_pct(owner):
    chain = owner_chain(owner)
    product = Decimal(1)
    for node in chain:
        product = product * dec(node["ownership_pct"])
    divisor = Decimal(100) ** (len(chain) - 1)
    return q2(product / divisor)


def ownership_rollup(respondent):
    """Writes verified_ownership_pct, control_chain_complete, ownership_verified."""
    owners = store.owners_of(respondent["id"])
    direct = [o for o in owners if o.get("parent_owner_id") is None]
    verified_direct = [o for o in direct if o["verification_status"] == "VERIFIED"]
    total = D0
    for o in verified_direct:
        total = total + dec(o["ownership_pct"])
    pct = q2(total)
    complete = True
    for o in verified_direct:
        if o["owner_type"] == "LEGAL_ENTITY" and dec(o["ownership_pct"]) >= Decimal("25.00"):
            kids = [c for c in owners
                    if c.get("parent_owner_id") == o["id"]
                    and c["verification_status"] == "VERIFIED"]
            if not kids:
                complete = False
    respondent["verified_ownership_pct"] = pct
    respondent["control_chain_complete"] = complete
    respondent["ownership_verified"] = bool(pct >= Decimal("75.00") and complete)


# ------------------------------------------------------ 3.4 control score ----

def control_score(questionnaire, variant):
    rows = {r["control_domain"]: r for r in store.controls_of(questionnaire["id"])}
    total = D0
    for domain in CONTROL_DOMAINS:
        row = rows.get(domain)
        if variant == "ONBOARDING_PROVISIONAL":
            if row is None:
                rating = Decimal(3)
            elif row.get("assessed_rating") is not None:
                rating = Decimal(row["assessed_rating"])
            else:
                rating = Decimal(row["self_rating"])
        else:
            if row is None or row.get("assessed_rating") is None:
                rating = Decimal(1)
            else:
                rating = Decimal(row["assessed_rating"])
        total = total + rating * DOMAIN_WEIGHTS[domain]
    raw = q2(total * Decimal("20.0"))
    critical = sum(1 for r in rows.values() if r["gap_severity"] == "CRITICAL")
    major = sum(1 for r in rows.values() if r["gap_severity"] == "MAJOR")
    if critical >= 1:
        return min(raw, Decimal("40.00"))
    if major >= 2:
        return min(raw, Decimal("60.00"))
    if major == 1:
        return min(raw, Decimal("75.00"))
    return raw


# -------------------------------------------------------- 3.6 inherent -------

def inherent_risk_score(respondent):
    prof = home_profile(respondent)
    jurisdiction = dec(prof["jurisdiction_risk_points"]) if prof else D0

    owners = store.owners_of(respondent["id"])
    verified = [o for o in owners if o["verification_status"] == "VERIFIED"]
    own = D0
    if any(o["is_pep"] for o in verified):
        own += Decimal(10)
    if any(o["owner_type"] == "STATE"
           and dec(o["effective_ownership_pct"]) >= Decimal("10.00")
           for o in verified):
        own += Decimal(8)
    if dec(respondent["verified_ownership_pct"]) < Decimal("75.00"):
        own += Decimal(6)
    countries = set()
    for o in verified:
        jp = store.jurisdiction_by_code(o["country_of_residence"])
        if jp is not None and jp["sanctions_status"] != "PERMITTED":
            countries.add(o["country_of_residence"])
    own += min(Decimal(12), Decimal(len(countries) * 4))
    if own > Decimal("24.0"):
        own = Decimal("24.0")

    rows = store.nested_of(respondent["id"])
    count = sum(1 for r in rows
                if r["state"] in ("CONFIRMED", "UNDISCLOSED_DETECTED"))
    nested = Decimal(count * 5)
    if int(respondent["max_nested_depth"]) >= 2:
        nested += Decimal(8)
    if nested > Decimal("20.0"):
        nested = Decimal("20.0")

    volume = dec(respondent["expected_monthly_volume_usd"])
    if volume >= Decimal("100000000.00"):
        activity = Decimal(14)
    elif volume >= Decimal("10000000.00"):
        activity = Decimal(10)
    elif volume >= Decimal("1000000.00"):
        activity = Decimal(6)
    else:
        activity = Decimal(2)
    if respondent["nested_activity_permitted"]:
        activity += Decimal(2)
    if activity > Decimal("16.0"):
        activity = Decimal("16.0")

    total = jurisdiction + own + nested + activity
    if total > Decimal("100.00"):
        total = Decimal("100.00")
    return q2(total)


# ---------------------------------------------------- 3.6 adverse media ------

def event_uplift_points(event):
    return q2(TIER_POINTS[event["severity_tier"]] * RELIABILITY[event["source_reliability"]])


def qualifying_media(respondent, start, end):
    out = []
    for ev in store.media_of(respondent["id"]):
        if ev["adjudication_state"] != "CONFIRMED":
            continue
        when = store.dt(ev, "event_date")
        if when is None:
            continue
        if when >= start and when < end:
            out.append(ev)
    out.sort(key=lambda e: (store.dt(e, "event_date"), e["_seq"]))
    return out


def adverse_media_uplift(respondent, start, end):
    total = D0
    for ev in qualifying_media(respondent, start, end):
        total = q2(total + event_uplift_points(ev))
    if total > Decimal("20.00"):
        total = Decimal("20.00")
    return total


def media_window(respondent, variant):
    """Returns (start, end) for the uplift accumulator."""
    last = store.dt(respondent, "last_approved_at")
    if variant == "REFRESH_FINAL" and last is not None:
        base_end = base_window_end(respondent)
        end = min(clock.now(), base_end) if base_end else clock.now()
        return last, end
    now = clock.now()
    return clock.add_days(now, -730), now


def base_window_end(respondent):
    last = store.dt(respondent, "last_approved_at")
    if last is None:
        return None
    months = CADENCE_MONTHS.get(respondent["approved_risk_rating"], 0)
    return clock.add_months(last, months)


# ------------------------------------------------------- 3.6 residual --------

def control_credit_of(control_score_value):
    cs = dec(control_score_value)
    if cs <= Decimal("20.00"):
        return Decimal("0.0000")
    return q4((cs - Decimal("20.00")) / Decimal("80.00") * Decimal("0.4500"))


def residual_from(inherent, credit, uplift):
    credited = q2(dec(inherent) * (Decimal(1) - dec(credit)))
    return q2(credited + dec(uplift))


def rating_from(respondent, residual):
    if home_sanctioned(respondent):
        return "PROHIBITED"
    residual = dec(residual)
    if residual >= Decimal("70.00"):
        return "PROHIBITED"
    if residual >= Decimal("50.00"):
        return "HIGH"
    if residual >= Decimal("30.00"):
        return "MEDIUM"
    return "LOW"


# --------------------------------------------------- 3.8 refresh due date ----

def refresh_due_date(respondent):
    """The five-step, non-iterative procedure of PRD 3.8."""
    last = store.dt(respondent, "last_approved_at")
    if last is None:
        return None
    base_end = clock.add_months(
        last, CADENCE_MONTHS.get(respondent["approved_risk_rating"], 0))
    win_end = min(clock.now(), base_end)
    uplift = adverse_media_uplift(respondent, last, win_end)
    live_residual = residual_from(respondent["inherent_risk_score"],
                                 respondent["control_credit"], uplift)
    live_rating = rating_from(respondent, live_residual)
    accelerated = clock.add_months(last, CADENCE_MONTHS.get(live_rating, 0))
    tier1 = []
    for ev in qualifying_media(respondent, last, win_end):
        if ev["severity_tier"] == "TIER_1" and store.dt(ev, "triaged_at") is not None:
            tier1.append(store.dt(ev, "triaged_at"))
    if tier1:
        candidate = clock.add_days(min(tier1), 30)
        if candidate < accelerated:
            accelerated = candidate
    floor = clock.add_days(last, 30)
    return max(floor, min(base_end, accelerated))


# --------------------------------------------- 3.7 calibration arithmetic ----

def calibrate_thresholds(profile, respondent):
    factor = RATING_FACTOR[respondent["risk_rating"]]
    tolerance = dec(profile["tolerance_pct"])
    lines = []
    running = D0
    for entry in profile["expected_corridors"]:
        jp = store.jurisdiction_by_code(entry["jurisdiction_code"])
        if jp is None:
            fail("ERR_JURISDICTION_PROFILE_NOT_FOUND",
                 "Corridor jurisdiction %s does not resolve." % entry["jurisdiction_code"])
        weight = dec(jp["corridor_risk_weight"])
        usd = dec(entry["expected_monthly_usd"]) * (Decimal(1) + tolerance) * factor / weight
        if usd < CORRIDOR_FLOOR:
            usd = CORRIDOR_FLOOR
        elif usd > AGGREGATE_CEILING:
            usd = AGGREGATE_CEILING
        usd = q2(usd)
        raw_count = dec(entry["expected_monthly_count"]) * (Decimal(1) + tolerance) * factor / weight
        count = int(raw_count.to_integral_value(rounding=ROUND_CEILING))
        if count < 5:
            count = 5
        lines.append({
            "jurisdiction_code": entry["jurisdiction_code"],
            "usd_threshold": usd,
            "count_threshold": count,
        })
        running = running + usd
    aggregate = q2(running * Decimal("1.10"))
    if aggregate > AGGREGATE_CEILING:
        fail("ERR_AGGREGATE_THRESHOLD_EXCEEDED",
             "Buffered aggregate corridor threshold exceeds the platform ceiling.")
    hold = q2(aggregate / Decimal("10.0"))
    return lines, aggregate, hold


# ------------------------------------------------------------- 3.8 SLA -------

def rfi_sla_hours(respondent, severity):
    hours = Decimal(SLA_BASE[severity])
    if respondent["risk_rating"] in ("HIGH", "PROHIBITED"):
        hours = hours * Decimal("0.5")
    if int(respondent["unresponsive_strikes"]) >= 2:
        hours = hours * Decimal("0.5")
    whole = int(hours.to_integral_value(rounding=ROUND_CEILING))
    if whole < 12:
        whole = 12
    return whole


# ------------------------------------------------------- 3.9 notice / cap ----

def notice_period_days(plan, respondent):
    days = NOTICE_BASE[plan["termination_reason"]]
    if int(plan["original_obligation_cents"]) > 0:
        days += 15
    if respondent["risk_rating"] == "PROHIBITED":
        days -= 15
    if days < 0:
        days = 0
    if home_sanctioned(respondent):
        days = 0
    return days


def wind_down_cap(plan, respondent):
    months = dec(plan["notice_period_days"]) / Decimal("30.0")
    if plan["cap_basis"] == "CHRONOLOGICAL_ACTUAL":
        rows = store.observations_of(respondent["id"])
        rows.sort(key=lambda r: (r["period_month"], r["_seq"]))
        if not rows:
            fail("ERR_INSUFFICIENT_ACTIVITY_HISTORY",
                 "A chronological-actual cap requires activity observations.")
        periods = []
        for row in rows:
            if row["period_month"] not in periods:
                periods.append(row["period_month"])
        chosen = periods[-3:]
        capped = []
        for period in chosen:
            members = [r for r in rows if r["period_month"] == period]
            total = D0
            for r in members:
                total = total + dec(r["aggregate_usd"])
            owner_profile = store.get("profiles", members[0]["monitoring_profile_id"])
            ceiling = q2(Decimal("1.25") * dec(owner_profile["aggregate_usd_threshold"]))
            capped.append(min(q2(total), ceiling))
        acc = D0
        for value in capped:
            acc = acc + value
        base = q2(acc / Decimal(len(capped)))
    else:
        base = dec(respondent["expected_monthly_volume_usd"])
    return q2(base * months * Decimal("0.60"))


# ------------------------------------------------- 3.9 settlement lines ------

def settlement_lines(respondent, amount_cents):
    profiles = store.profiles_of(respondent["id"])
    chosen = None
    for prof in profiles:
        if prof["calibration_state"] == "CALIBRATED":
            chosen = prof
    if chosen is None and profiles:
        chosen = store.by_seq_desc(profiles)[0]
    if chosen is None:
        return []
    corridors = list(chosen["expected_corridors"])
    corridors.sort(key=lambda c: (-dec(c["expected_monthly_usd"]), c["jurisdiction_code"]))
    total_expected = D0
    for c in corridors:
        total_expected = total_expected + dec(c["expected_monthly_usd"])
    if total_expected == D0:
        return []
    lines = []
    summed = 0
    for c in corridors:
        raw = dec(amount_cents) * dec(c["expected_monthly_usd"]) / total_expected
        cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        lines.append({"jurisdiction_code": c["jurisdiction_code"], "line_cents": cents})
        summed += cents
    residue = int(amount_cents) - summed
    if lines and residue != 0:
        lines[0]["line_cents"] = lines[0]["line_cents"] + residue
    return lines
