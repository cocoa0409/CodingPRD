"""Calculation rules (SCAFFOLD §1.3 / PRD §3)."""
from datetime import datetime, timedelta
from decimal import Decimal

from core import UTC, db, fail, iso, make_instant, now, r2, rows

RANK = {"LOW": 1, "MODERATE": 2, "HIGH": 3}
LEVEL_OF = {1: "LOW", 2: "MODERATE", 3: "HIGH"}

BASE_DAYS = {"HIGH": 30, "MODERATE": 90, "LOW": 180}
SEVERITY_WEIGHT = {"HIGH": Decimal("10.0"), "MODERATE": Decimal("4.0"), "LOW": Decimal("1.0")}
DISPOSITION_FACTOR = {
    "NONE": Decimal("1.0"),
    "DEVIATION_REQUESTED": Decimal("1.0"),
    "EXTENSION_GRANTED": Decimal("1.0"),
    "RISK_ACCEPTED": Decimal("0.5"),
    "FALSE_POSITIVE_ACCEPTED": Decimal("0.0"),
}
OVERDUE_MULTIPLIER = Decimal("1.5")
SCORE_CEILING = Decimal("100.00")

HOUR_ALLOWANCE = {"LOW": 400, "MODERATE": 900, "HIGH": 1600}
OVERAGE_RATE = Decimal("120.00")

OPEN_REMEDIATION = ("OPEN", "IN_REMEDIATION", "AWAITING_VERIFICATION")
REQUIRED_SCAN_TYPES = ("INFRASTRUCTURE", "WEB_APP", "DATABASE")
SCAN_TYPES = ("INFRASTRUCTURE", "WEB_APP", "DATABASE", "CONTAINER")


# ---------------------------------------------------------------------------
# impact_level_determination
# ---------------------------------------------------------------------------


def _category_high(cat):
    return max(
        RANK[cat["confidentiality_impact"]],
        RANK[cat["integrity_impact"]],
        RANK[cat["availability_impact"]],
    )


def categories_of(offering_id):
    return [c for c in rows("data_categories") if c["offering_id"] == offering_id]


def preliminary_impact_level(offering_id):
    included = [c for c in categories_of(offering_id) if c["status"] in ("DECLARED", "CONFIRMED")]
    if not included:
        return None
    return LEVEL_OF[max(_category_high(c) for c in included)]


def final_impact_level(offering):
    confirmed = [c for c in categories_of(offering["id"]) if c["status"] == "CONFIRMED"]
    if not confirmed:
        fail("ERR_NO_CONFIRMED_DATA_CATEGORY", "The offering has no CONFIRMED data category.")
    water_mark = max(_category_high(c) for c in confirmed)
    external = RANK[offering.get("external_dependency_impact_level") or "LOW"]
    return LEVEL_OF[max(water_mark, external)]


def select_baseline(impact_level):
    best = None
    for b in rows("baselines"):
        if b["impact_level"] != impact_level or b["retired"]:
            continue
        if best is None:
            best = b
            continue
        if b["effective_from"] > best["effective_from"]:
            best = b
        elif b["effective_from"] == best["effective_from"] and b["created_at"] < best["created_at"]:
            best = b
    if best is None:
        fail("ERR_BASELINE_NOT_AVAILABLE", "No non-retired baseline exists for impact level %s." % impact_level)
    return best


# ---------------------------------------------------------------------------
# crm_documentation_coverage
# ---------------------------------------------------------------------------


def crm_coverage(offering):
    baseline = db.baselines.get(offering.get("baseline_id"))
    breakdown = []
    weighted_sum = Decimal("0")
    weight_total = 0
    if baseline is not None:
        impls = [ci for ci in rows("control_implementations") if ci["offering_id"] == offering["id"]]
        families = sorted(
            baseline["families"],
            key=lambda f: (int(f["priority_rank"]), str(f["family_code"])),
        )
        for fam in families:
            required = int(fam["required_control_count"])
            if required == 0:
                continue
            implemented = sum(
                1
                for ci in impls
                if ci["family_code"] == fam["family_code"]
                and ci["implementation_status"] in ("IMPLEMENTED", "PARTIALLY_IMPLEMENTED")
                and ci["crm_documented"] is True
            )
            documented = min(implemented, required)
            family_pct = r2(Decimal(documented) / Decimal(required) * Decimal(100))
            weighted_sum += family_pct * Decimal(required)
            weight_total += required
            breakdown.append(
                {
                    "family_code": fam["family_code"],
                    "priority_rank": int(fam["priority_rank"]),
                    "required_control_count": required,
                    "implemented_count": implemented,
                    "documented_count": documented,
                    "family_coverage_pct": family_pct,
                }
            )
    if weight_total == 0:
        overall = Decimal("0.00")
    else:
        overall = r2(weighted_sum / Decimal(weight_total))
    return {
        "overall_coverage_pct": overall,
        "weight_total": weight_total,
        "family_breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# engagement_cost_rollup
# ---------------------------------------------------------------------------


def engagement_cost(offering, contracted_hours, labor_cost_usd):
    if labor_cost_usd < Decimal("250000.00"):
        rate = Decimal("0.06")
    elif labor_cost_usd < Decimal("600000.00"):
        rate = Decimal("0.045")
    else:
        rate = Decimal("0.03")
    surcharge = r2(labor_cost_usd * rate)
    allowance = Decimal(HOUR_ALLOWANCE.get(offering.get("final_impact_level"), 0))
    overage_hours = contracted_hours - allowance
    if overage_hours < 0:
        overage_hours = Decimal("0")
    overage = r2(overage_hours * OVERAGE_RATE)
    total = r2(labor_cost_usd + surcharge + overage)
    return {
        "surcharge_rate": rate,
        "program_surcharge_usd": surcharge,
        "hour_overage_usd": overage,
        "total_cost_usd": total,
    }


# ---------------------------------------------------------------------------
# poam_remediation_deadline
# ---------------------------------------------------------------------------


def deadline_from(anchor_at, severity, extension_days=0):
    return make_instant(anchor_at + timedelta(days=BASE_DAYS[severity] + int(extension_days)))


def recompute_deadline(item):
    item["deadline_at"] = deadline_from(
        item["anchor_at"], item["severity"], item.get("granted_extension_days") or 0
    )


def base_deadline(item):
    """Deadline ignoring granted_extension_days (at_submission variant)."""
    return deadline_from(item["anchor_at"], item["severity"], 0)


# ---------------------------------------------------------------------------
# residual_risk_score
# ---------------------------------------------------------------------------


def findings_of(offering_id):
    return [p for p in rows("poam_items") if p["offering_id"] == offering_id]


def residual_risk(offering_id, variant="at_monitoring_review", as_of=None):
    if as_of is None:
        as_of = now()
    score = Decimal("0")
    for item in findings_of(offering_id):
        if item["remediation_status"] not in OPEN_REMEDIATION:
            continue
        if variant == "at_submission":
            effective_deadline = base_deadline(item)
        else:
            effective_deadline = item["deadline_at"]
        overdue = as_of >= effective_deadline
        contribution = r2(
            SEVERITY_WEIGHT[item["severity"]]
            * DISPOSITION_FACTOR[item["risk_disposition"]]
            * (OVERDUE_MULTIPLIER if overdue else Decimal("1.0"))
        )
        score += contribution
    score = r2(score)
    if score > SCORE_CEILING:
        score = SCORE_CEILING
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    return score


def risk_tier(score):
    if score == Decimal("0.00"):
        return "NONE"
    if score < Decimal("10.00"):
        return "LOW"
    if score < Decimal("30.00"):
        return "MODERATE"
    return "ELEVATED"


def overdue_high_count(offering_id, as_of=None):
    if as_of is None:
        as_of = now()
    total = 0
    for item in findings_of(offering_id):
        if item["severity"] != "HIGH":
            continue
        if item["remediation_status"] == "CLOSED":
            continue
        if as_of >= item["deadline_at"]:
            total += 1
    return total


# ---------------------------------------------------------------------------
# engagement_hour_ledger
# ---------------------------------------------------------------------------


def slots_of(engagement_id):
    return [s for s in rows("test_slots") if s["engagement_id"] == engagement_id]


def hour_ledger(engagement):
    allocated = Decimal("0")
    for slot in slots_of(engagement["id"]):
        if slot["status"] in ("SCHEDULED", "COMPLETED"):
            allocated += slot["hours"]
    allocated = r2(allocated)
    unallocated = r2(engagement["contracted_hours"] - allocated)
    if unallocated < 0:
        unallocated = Decimal("0.00")
    return allocated, unallocated


# ---------------------------------------------------------------------------
# scan_submission_timeliness
# ---------------------------------------------------------------------------


def timeliness(submitted_at, scan_due_at):
    if submitted_at <= scan_due_at:
        days_late = 0
    else:
        days_late = int((submitted_at - scan_due_at).total_seconds() // 86400)
    if days_late == 0:
        status = "ACCEPTED"
    elif days_late <= 3:
        status = "LATE_ACCEPTED"
    else:
        status = "REJECTED"
    return days_late, status


# ---------------------------------------------------------------------------
# monitoring period month geometry
# ---------------------------------------------------------------------------


def month_bounds(period_month):
    year = int(period_month[:4])
    month = int(period_month[5:7])
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return make_instant(start), make_instant(end), make_instant(end + timedelta(days=5))


def month_string(instant):
    return "%04d-%02d" % (instant.year, instant.month)


def next_month_string(period_month):
    year = int(period_month[:4])
    month = int(period_month[5:7])
    if month == 12:
        return "%04d-01" % (year + 1)
    return "%04d-%02d" % (year, month + 1)


# ---------------------------------------------------------------------------
# change_window_separation / test_slot_overlap_geometry
# ---------------------------------------------------------------------------

BUFFER = timedelta(days=7)


def change_windows_separated(new_start, new_end, other_start, other_end):
    return (new_start - other_end) >= BUFFER or (other_start - new_end) >= BUFFER


def slots_overlap(new_start, new_end, other_start, other_end):
    return new_start < other_end and other_start < new_end


__all__ = [name for name in dir() if not name.startswith("_")]
