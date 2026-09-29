"""The risk assessment run (PRD 3.2)."""

import clock
import db
from db import store
from errors import ApiError
from money import ZERO, dec, q2

SECTOR_MULTIPLIER = {
    "TECH": dec("1.15"),
    "BIOTECH": dec("1.30"),
    "FINANCIAL": dec("1.25"),
    "ENERGY": dec("1.10"),
    "INDUSTRIAL": dec("1.00"),
    "CONSUMER": dec("0.95"),
}

LITIGATION_WEIGHT = {
    "SECURITIES_CLASS_ACTION": dec("20"),
    "REGULATORY_ENFORCEMENT": dec("15"),
    "DERIVATIVE": dec("12"),
    "FIDUCIARY": dec("8"),
    "MERGER_OBJECTION": dec("5"),
    "EMPLOYMENT_PRACTICES": dec("3"),
}

INDICATIVE_CASE_TYPES = ("SECURITIES_CLASS_ACTION", "REGULATORY_ENFORCEMENT")

FINANCIAL_CAP = dec("60")
GOVERNANCE_CAP = dec("50")
LITIGATION_CAP = dec("70")
OPEN_LITIGATION_SURCHARGE = dec("10")
STALENESS_DAYS = 540
RECENT_DAYS = 1095
HALF_WEIGHT_DAYS = 2190


def packages_of(insured_id):
    return db.ordered(
        [p for p in store.disclosure_packages.values() if p["insured_id"] == insured_id]
    )


def events_of(insured_id):
    return db.ordered(
        [e for e in store.litigation_events.values() if e["insured_id"] == insured_id]
    )


def _package_rank(package):
    return (package["fiscal_year"], package["created_at"], package["_seq"])


def select_packages(insured_id, variant):
    """INDICATIVE reads the single latest package; UNDERWRITTEN reads the top three."""
    ranked = sorted(packages_of(insured_id), key=_package_rank, reverse=True)
    if not ranked:
        return []
    if variant == "INDICATIVE":
        return ranked[:1]
    return ranked[:3]


def select_events(insured_id, variant):
    events = events_of(insured_id)
    if variant == "INDICATIVE":
        return [e for e in events if e["case_type"] in INDICATIVE_CASE_TYPES]
    return events


def financial_subscore(package):
    total = ZERO
    if package["restatement_flag"]:
        total += dec("18")
    weaknesses = package["material_weakness_count"]
    total += dec("6") * dec(min(weaknesses, 3))
    if package["going_concern_flag"]:
        total += dec("12")
    if package["negative_operating_cash_flow_flag"]:
        total += dec("10")
    if dec(package["debt_to_equity"]) >= dec("2.0"):
        total += dec("8")
    return q2(min(FINANCIAL_CAP, total))


def governance_subscore(package):
    total = ZERO
    if dec(package["independent_director_ratio"]) < dec("0.50"):
        total += dec("14")
    if package["dual_class_shares_flag"]:
        total += dec("10")
    if package["combined_ceo_chair_flag"]:
        total += dec("8")
    if package["staggered_board_flag"]:
        total += dec("6")
    if package["auditor_change_flag"]:
        total += dec("12")
    return q2(min(GOVERNANCE_CAP, total))


def recency_factor(event, variant, now):
    age = clock.whole_days_between(event["filed_date"], now)
    if age <= RECENT_DAYS:
        return dec("1.0")
    if variant == "UNDERWRITTEN" and age <= HALF_WEIGHT_DAYS:
        return dec("0.5")
    return ZERO


def run(submission, insured, variant, touched):
    """Apply a scoring run to the submission, its packages and its events."""
    now = clock.now()
    packages = select_packages(insured["id"], variant)
    if not packages_of(insured["id"]):
        raise ApiError("ERR_DISCLOSURE_REQUIRED")
    if not packages:
        raise ApiError("ERR_DISCLOSURE_REQUIRED")
    latest = packages[0]
    if latest["filed_date"] <= clock.plus_days(now, -STALENESS_DAYS):
        raise ApiError("ERR_DISCLOSURE_STALE")

    financial_component = ZERO
    governance_component = ZERO
    for package in packages:
        package["financial_subscore"] = financial_subscore(package)
        package["governance_subscore"] = governance_subscore(package)
        touched.add(package)
        if package["financial_subscore"] > financial_component:
            financial_component = package["financial_subscore"]
        if package["governance_subscore"] > governance_component:
            governance_component = package["governance_subscore"]

    events = select_events(insured["id"], variant)
    weight_total = ZERO
    has_open = False
    for event in events:
        factor = recency_factor(event, variant, now)
        event["weight_units"] = q2(LITIGATION_WEIGHT[event["case_type"]] * factor)
        weight_total += event["weight_units"]
        if event.get("resolved_date") is None:
            has_open = True
    if variant == "UNDERWRITTEN" and has_open:
        weight_total += OPEN_LITIGATION_SURCHARGE
    litigation_units = q2(min(LITIGATION_CAP, weight_total))

    composite = financial_component + governance_component + litigation_units
    multiplier = SECTOR_MULTIPLIER[insured["sector_code"]]
    risk_score = q2(composite * multiplier)

    if risk_score < dec("40"):
        risk_band = "LOW"
    elif risk_score < dec("70"):
        risk_band = "MODERATE"
    elif risk_score < dec("100"):
        risk_band = "ELEVATED"
    else:
        risk_band = "SEVERE"

    submission["risk_score"] = risk_score
    submission["risk_band"] = risk_band
    submission["litigation_units"] = litigation_units
    submission["disclosure_packages_considered"] = len(packages)
    submission["score_variant"] = variant
    submission["scored_at"] = now
    submission["status"] = "SCORED"
    touched.add(submission)
    return submission
