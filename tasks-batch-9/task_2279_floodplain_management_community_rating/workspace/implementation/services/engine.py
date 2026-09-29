"""Derived-state engine: aggregates, classifications, credit, cascades.

Everything here mutates rows in place and refreshes `updated_at` / `version`
through db.touch() exactly when a stored value actually changes, per PRD 2.4.
"""

from db import (base_fields, db, iso, iso_now, now, plus_days, shift_years,
                sort_rows, to_dt, touch)
from services import calc

# --------------------------------------------------------------- collections


def props_of_community(community_id):
    return [p for p in db.properties.values() if p["community_id"] == community_id]


def structures_of_property(property_id):
    return [s for s in db.structures.values() if s["property_id"] == property_id]


def structures_of_community(community_id):
    out = []
    for prop in sort_rows(props_of_community(community_id)):
        out.extend(sort_rows(structures_of_property(prop["id"])))
    return out


def records_of(structure_id):
    return [r for r in db.records.values() if r["structure_id"] == structure_id]


def cases_of(structure_id):
    return [c for c in db.cases.values() if c["structure_id"] == structure_id]


def permits_of(structure_id):
    return [p for p in db.permits.values() if p["structure_id"] == structure_id]


def certificates_of_permit(permit_id):
    return [c for c in db.certificates.values() if c["permit_id"] == permit_id]


def certificates_of_structure(structure_id):
    return [c for c in db.certificates.values() if c["structure_id"] == structure_id]


def orders_of(violation_id):
    return [o for o in db.orders.values() if o["violation_id"] == violation_id]


def standards_of(community_id):
    return [h for h in db.standards.values() if h["community_id"] == community_id]


def cycles_of(community_id):
    return [c for c in db.cycles.values() if c["community_id"] == community_id]


def areas_of(community_id):
    return [a for a in db.loss_areas.values() if a["community_id"] == community_id]


def property_of_structure(structure):
    return db.properties.get(structure["property_id"])


def community_of_property(prop):
    return db.communities.get(prop["community_id"])


def community_of_structure(structure):
    prop = property_of_structure(structure)
    return community_of_property(prop) if prop else None


def has_active_violation(structure_id):
    return any(v["structure_id"] == structure_id
               and v["status"] in calc.ACTIVE_VIOLATION_STATUSES
               for v in db.violations.values())


def newest_resolved_case(structure_id):
    resolved = [c for c in cases_of(structure_id)
                if c["status"] in calc.RESOLVED_CASE_STATUSES]
    if not resolved:
        return None
    resolved.sort(key=lambda c: (c["determined_at"] or "", c["created_at"], c["_seq"]),
                  reverse=True)
    return resolved[0]


# ------------------------------------------- structure_improvement_aggregates


def _counted_records(structure_id):
    return [r for r in records_of(structure_id)
            if r["counted_in_cumulative"] and not r["reversed"]]


def _anchor_of(counted):
    return sorted(counted,
                  key=lambda r: (to_dt(r["event_date"]), r["created_at"], r["_seq"]),
                  reverse=True)[0]


def improvement_window(structure):
    """(anchor, window_start, window_end, counted_records_inside_window)."""
    counted = _counted_records(structure["id"])
    if not counted:
        return None, None, None, []
    anchor = _anchor_of(counted)
    community = community_of_structure(structure)
    years = community["cumulative_period_years"] if community else 0
    end = to_dt(anchor["event_date"])
    start = shift_years(end, -years)
    inside = [r for r in counted if start <= to_dt(r["event_date"]) <= end]
    return anchor, start, end, inside


def recompute_aggregates(structure):
    anchor, _start, _end, inside = improvement_window(structure)
    if anchor is None:
        structure["anchor_record_id"] = None
        structure["cumulative_counted_cost_usd"] = calc.money(0)
        structure["cumulative_improvement_pct"] = calc.r2(0)
        structure["single_event_improvement_pct"] = calc.r2(0)
        return
    total = calc.money(sum((r["cost_usd"] for r in inside), calc.ZERO))
    denominator = anchor["market_value_at_event_usd"]
    structure["anchor_record_id"] = anchor["id"]
    structure["cumulative_counted_cost_usd"] = total
    structure["cumulative_improvement_pct"] = calc.pct(total, denominator)
    structure["single_event_improvement_pct"] = calc.pct(anchor["cost_usd"], denominator)


# ------------------------------------------- repetitive_loss_classification


def recompute_property_rl(prop):
    structure_ids = {s["id"] for s in structures_of_property(prop["id"])}
    claims = [r for r in db.records.values()
              if r["structure_id"] in structure_ids
              and r["record_type"] == "DAMAGE"
              and not r["reversed"]
              and r["claim_paid_amount_usd"] >= calc.RL_CLAIM_MIN_PAID_USD]
    claims.sort(key=lambda r: (to_dt(r["event_date"]), r["created_at"], r["_seq"]))

    count = len(claims)
    total = calc.money(sum((c["claim_paid_amount_usd"] for c in claims), calc.ZERO))
    best = 0
    for anchor in claims:
        start = to_dt(anchor["event_date"])
        end = shift_years(start, calc.RL_WINDOW_YEARS)
        best = max(best, sum(1 for c in claims
                             if start <= to_dt(c["event_date"]) <= end))
    newest = claims[-1] if claims else None
    if best >= calc.RL_SEVERE_CLAIM_COUNT or (
            best >= calc.RL_REPETITIVE_CLAIM_COUNT and newest is not None
            and total > newest["market_value_at_event_usd"]):
        status = "SEVERE_REPETITIVE_LOSS"
    elif best >= calc.RL_REPETITIVE_CLAIM_COUNT:
        status = "REPETITIVE_LOSS"
    else:
        status = "NONE"

    status_changed = prop["repetitive_loss_status"] != status
    changed = (status_changed
               or prop["qualifying_claim_count"] != count
               or prop["max_window_claim_count"] != best
               or prop["cumulative_claim_paid_usd"] != total)
    prop["qualifying_claim_count"] = count
    prop["max_window_claim_count"] = best
    prop["cumulative_claim_paid_usd"] = total
    prop["repetitive_loss_status"] = status
    return changed, status_changed


def mark_area_stale(prop):
    area_id = prop.get("repetitive_loss_area_id")
    if not area_id:
        return
    area = db.loss_areas.get(area_id)
    if area is not None and area["analysis_status"] == "ANALYZED":
        area["analysis_status"] = "STALE"
        touch(area)


# ----------------------------------------------- sanction_risk_and_posture


def sanction_breakdown(community):
    community_id = community["id"]
    property_ids = {p["id"] for p in props_of_community(community_id)}
    violations = [v for v in db.violations.values()
                  if v["property_id"] in property_ids]
    counted = [v for v in violations
               if v["status"] in calc.ACTIVE_VIOLATION_STATUSES]
    raw = sum(calc.SEVERITY_WEIGHT[v["severity"]] for v in counted)
    escalated = {v["id"] for v in violations if v["status"] == "ESCALATED"}
    defaulted = [o for o in db.orders.values()
                 if o["status"] == "DEFAULTED" and o["violation_id"] in escalated]
    raw += calc.DEFAULTED_ORDER_PENALTY_POINTS * len(defaulted)

    provisional = calc.tier(raw)
    credit = 0
    if provisional == "ON_PROBATION" and any(
            h["activity_code"] == "A510_HIGHER_STD_ENFORCEMENT"
            and h["documentation_status"] == "VERIFIED"
            for h in standards_of(community_id)):
        credit = calc.A510_PROBATION_CREDIT_POINTS
    points = max(raw - credit, 0)
    return {
        "raw": raw,
        "counted_violation_count": len(counted),
        "defaulted_order_count": len(defaulted),
        "credit": credit,
        "points": points,
        "posture": calc.tier(points),
    }


def sanction_fields(community):
    """Rewrite the sanction fields in place; returns True when anything moved."""
    breakdown = sanction_breakdown(community)
    changed = (community["sanction_risk_points"] != breakdown["points"]
               or community["compliance_posture"] != breakdown["posture"])
    community["sanction_risk_points"] = breakdown["points"]
    community["compliance_posture"] = breakdown["posture"]
    if breakdown["posture"] == "SUSPENDED" and retrograde(community):
        changed = True
    return changed


def apply_sanction(community):
    if community is None:
        return False
    changed = sanction_fields(community)
    if changed:
        touch(community)
    return changed


def retrograde(community):
    """Cascade B hop 4 — every live cycle retrogrades and the class resets."""
    changed = False
    live = [c for c in cycles_of(community["id"])
            if c["status"] in ("OPEN", "SUBMITTED", "UNDER_VERIFICATION")]
    for cycle in sort_rows(live):
        cycle["status"] = "RETROGRADED"
        touch(cycle)
        changed = True
    if community["crs_class"] != calc.WORST_CRS_CLASS:
        community["crs_class"] = calc.WORST_CRS_CLASS
        changed = True
    return changed


# --------------------------------------------------- CRS credit and class


def recompute_claimed(community):
    total = sum(h["claimed_points"] for h in standards_of(community["id"])
                if h["documentation_status"] in ("SUBMITTED", "VERIFIED"))
    changed = community["crs_credit_points_claimed"] != total
    community["crs_credit_points_claimed"] = total
    return changed


def recompute_verified(community):
    total = sum(h["verified_points"] for h in standards_of(community["id"])
                if h["documentation_status"] == "VERIFIED")
    changed = community["crs_credit_points_verified"] != total
    community["crs_credit_points_verified"] = total
    return changed


def outreach_score(community_id, cycle_year):
    scored = [a for a in areas_of(community_id)
              if a["status"] == "DESIGNATED"
              and a["outreach_status"] in ("COMPLETED", "INSUFFICIENT")
              and a["outreach_cycle_year"] == cycle_year]
    scored = sort_rows(scored)
    if not scored:
        return calc.r2(0)
    total = sum((a["coverage_pct"] for a in scored), calc.ZERO)
    return calc.r2(total / calc.dec(len(scored)))


def outreach_points(community_id, cycle_year):
    score = outreach_score(community_id, cycle_year)
    if score >= calc.OUTREACH_FULL_CREDIT_PCT:
        return calc.A330_FULL_POINTS
    if score >= calc.OUTREACH_PARTIAL_CREDIT_PCT:
        return calc.A330_PARTIAL_POINTS
    return 0


def max_points_for(standard, community):
    code = standard["activity_code"]
    if code == "A430_FREEBOARD":
        feet = min(community["freeboard_ft"], calc.A430_FREEBOARD_CAP_FT)
        return calc.floor_int(calc.dec(calc.A430_POINTS_PER_FOOT) * feet)
    if code == "A430_CUMULATIVE_SI":
        return calc.A430_CUMULATIVE_POINTS if community["cumulative_period_years"] >= 10 else 0
    if code == "A420_OPEN_SPACE":
        designated = sum(1 for a in areas_of(community["id"]) if a["status"] == "DESIGNATED")
        return min(calc.A420_POINTS_PER_AREA * designated, calc.A420_POINTS_CAP)
    if code == "A510_HIGHER_STD_ENFORCEMENT":
        property_ids = {p["id"] for p in props_of_community(community["id"])}
        remediated = any(v["property_id"] in property_ids and v["status"] == "REMEDIATED"
                         for v in db.violations.values())
        return calc.A510_POINTS if remediated else 0
    if code == "A330_OUTREACH":
        return outreach_points(community["id"], standard["documentation_cycle_year"])
    return 0


def crs_class_for(points, community):
    raw = calc.WORST_CRS_CLASS - (int(points) // calc.CRS_POINTS_PER_CLASS)
    result = max(raw, calc.BEST_CRS_CLASS)
    if community["compliance_posture"] != "GOOD_STANDING":
        result = calc.WORST_CRS_CLASS
    return result


def expire_standard(standard, community):
    standard["documentation_status"] = "EXPIRED"
    standard["verified_points"] = 0
    touch(standard)
    if standard["activity_code"] == "A510_HIGHER_STD_ENFORCEMENT" and community is not None:
        apply_sanction(community)


# ------------------------------------------ required_lowest_floor_elevation


def required_elevation(permit, structure):
    zone = permit.get("determined_zone")
    bfe = permit.get("determined_bfe_ft")
    if zone is None or bfe is None or zone not in calc.ZONE_MIN_FREEBOARD_FT:
        return None
    if zone == "AO":
        base = calc.dec(structure["highest_adjacent_grade_ft"]) + calc.dec(bfe)
    else:
        base = calc.dec(bfe)
    applied = permit.get("freeboard_applied_ft")
    applied = calc.dec(applied) if applied is not None else calc.ZERO
    freeboard = max(applied, calc.ZONE_MIN_FREEBOARD_FT[zone])
    bump = calc.SI_ADDITIONAL_FREEBOARD_FT if structure["substantial_status"] != "NONE" else calc.ZERO
    credit = (calc.FLOODPROOFING_CREDIT_FT
              if permit.get("floodproofing_requested") and structure["structure_use"] == "NON_RESIDENTIAL"
              else calc.ZERO)
    return calc.r1(base + freeboard + bump - credit)


# ------------------------------------------ certificate_datum_normalization


def normalize_certificate(certificate, permit):
    normalized = calc.r1(calc.dec(certificate["measured_lowest_floor_ft"])
                         + calc.DATUM_OFFSET_FT[certificate["datum"]])
    required = permit.get("required_lowest_floor_elevation_ft")
    margin = calc.r1(normalized - calc.dec(required)) if required is not None else None
    changed = (certificate.get("normalized_lowest_floor_ft") != normalized
               or certificate.get("freeboard_margin_ft") != margin)
    certificate["normalized_lowest_floor_ft"] = normalized
    certificate["freeboard_margin_ft"] = margin
    return changed


def refresh_submitted_certificates(permit):
    for certificate in sort_rows(certificates_of_permit(permit["id"])):
        if certificate["status"] != "SUBMITTED":
            continue
        if normalize_certificate(certificate, permit):
            touch(certificate)


def recompute_permits_for_structure(structure):
    """Determination-axis movement re-runs the requirement for live permits."""
    live = [p for p in permits_of(structure["id"])
            if p["status"] in calc.LIVE_PERMIT_STATUSES]
    for permit in sort_rows(live):
        value = required_elevation(permit, structure)
        changed = False
        if value is not None and permit["required_lowest_floor_elevation_ft"] != value:
            permit["required_lowest_floor_elevation_ft"] = value
            changed = True
        if (permit["status"] == "APPROVED" and value is not None
                and value > calc.dec(permit["proposed_lowest_floor_elevation_ft"])):
            permit["status"] = "REVISION_REQUIRED"
            changed = True
        if changed:
            touch(permit)
            refresh_submitted_certificates(permit)


def set_substantial_status(structure, value):
    if structure["substantial_status"] == value:
        return False
    structure["substantial_status"] = value
    touch(structure)
    recompute_permits_for_structure(structure)
    return True


# ------------------------------------------------------------- the ledger


def create_record(structure, record_type, source, event_date, cost_usd,
                  claim_paid_amount_usd, is_code_compliance_only=False,
                  permit_id=None, inspection_id=None, reverses_record_id=None):
    counted = (record_type in ("IMPROVEMENT", "DAMAGE")
               and not is_code_compliance_only
               and calc.dec(cost_usd) >= calc.MIN_COUNTED_COST_USD)
    row = base_fields(versioned=False)
    row.update({
        "structure_id": structure["id"],
        "record_type": record_type,
        "source": source,
        "permit_id": permit_id,
        "inspection_id": inspection_id,
        "reverses_record_id": reverses_record_id,
        "event_date": iso(to_dt(event_date)),
        "cost_usd": calc.money(cost_usd),
        "market_value_at_event_usd": calc.money(structure["market_value_usd"]),
        "claim_paid_amount_usd": calc.money(claim_paid_amount_usd),
        "is_code_compliance_only": bool(is_code_compliance_only),
        "counted_in_cumulative": counted,
        "reversed": False,
    })
    db.records[row["id"]] = row
    return row


def new_case(structure, method, trigger_source):
    anchor_id = structure["anchor_record_id"]
    anchor = db.records.get(anchor_id) if anchor_id else None
    determination_type = ("SUBSTANTIAL_DAMAGE"
                          if anchor is not None and anchor["record_type"] == "DAMAGE"
                          else "SUBSTANTIAL_IMPROVEMENT")
    row = base_fields()
    row.update({
        "structure_id": structure["id"],
        "anchor_record_id": anchor_id,
        "method": method,
        "trigger_source": trigger_source,
        "determination_type": determination_type,
        "computed_ratio_pct": None,
        "threshold_pct": calc.r2(calc.SI_THRESHOLD_PCT),
        "outcome": None,
        "status": "OPEN",
        "determined_by_user_id": None,
        "determined_at": None,
        "appeal_deadline_at": None,
        "appealed_at": None,
        "appeal_decided_by_user_id": None,
    })
    db.cases[row["id"]] = row
    return row


_TRIGGER_BY_SOURCE = {
    "PERMIT_CLOSEOUT": "PERMIT_REVIEW",
    "DISASTER_INSPECTION": "DISASTER_INSPECTION",
}


def auto_case(structure, source):
    """The automatic-case rule of PRD 3.6 / Cascade A hop 3."""
    if structure["cumulative_improvement_pct"] < calc.SI_THRESHOLD_PCT:
        return None
    if any(c["status"] in calc.BLOCKING_CASE_STATUSES for c in cases_of(structure["id"])):
        return None
    case = new_case(structure, "CUMULATIVE", _TRIGGER_BY_SOURCE.get(source, "ADMIN"))
    if source == "DISASTER_INSPECTION":
        case["status"] = "DETERMINED"
        case["computed_ratio_pct"] = structure["cumulative_improvement_pct"]
        case["outcome"] = "SUBSTANTIAL"
        case["determined_by_user_id"] = None
        case["determined_at"] = iso_now()
        case["appeal_deadline_at"] = iso(plus_days(now(), calc.APPEAL_WINDOW_DAYS))
        set_substantial_status(structure, case["determination_type"])
    return case


def withdraw_case(structure, case):
    was_determined = case["status"] == "DETERMINED"
    case["status"] = "WITHDRAWN"
    touch(case)
    if was_determined:
        set_substantial_status(structure, "NONE")


def ledger_effects(structure, record, reversed_target=None):
    """Shared post-append pipeline: aggregates, RL, auto-case, staleness."""
    recompute_aggregates(structure)
    touch(structure)

    prop = property_of_structure(structure)
    changed, status_changed = recompute_property_rl(prop)
    if changed:
        touch(prop)

    auto_case(structure, record["source"])

    if reversed_target is not None:
        anchored = [c for c in cases_of(structure["id"])
                    if c["anchor_record_id"] == reversed_target["id"]
                    and c["status"] in ("OPEN", "DETERMINED")]
        for case in sort_rows(anchored):
            withdraw_case(structure, case)

    if status_changed:
        mark_area_stale(prop)


# ----------------------------------------------------------- enforcement


def remediate_violation(violation, community, restore_structure=True):
    violation["status"] = "REMEDIATED"
    violation["resolved_at"] = iso_now()
    violation["sanction_points_contributed"] = 0
    touch(violation)
    for order in sort_rows(orders_of(violation["id"])):
        if order["status"] in ("ISSUED", "EXTENDED"):
            order["status"] = "SATISFIED"
            order["resolved_at"] = iso_now()
            touch(order)
    apply_sanction(community)
    if not restore_structure:
        return
    structure_id = violation.get("structure_id")
    if violation["violation_type"] != "ELEVATION_DEFICIENT" or not structure_id:
        return
    structure = db.structures.get(structure_id)
    if structure is None or structure["compliance_status"] != "NON_COMPLIANT":
        return
    if has_active_violation(structure_id):
        return
    structure["compliance_status"] = ("COMPLIANT"
                                      if structure["lowest_floor_elevation_ft"] is not None
                                      else "PENDING_CERTIFICATE")
    touch(structure)
