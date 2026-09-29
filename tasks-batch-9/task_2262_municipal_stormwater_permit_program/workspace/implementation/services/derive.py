"""Derived fields, recomputation and the cascade chain (PRD sections 2.8, 3.1).

No derived field is ever supplied by a client.  Every mutation ends with a
recomputation pass over the owning permit term; a row whose derived values
actually changed is a mutated row and gets a fresh `updated_at` and `version`.
"""

from datetime import datetime, timezone

from db import DB, CLOCK, touch
from services import calc
from services.calc import D

# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------


def to_dt(text):
    if not text:
        return None
    value = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def measures_of_term(term_id):
    return [m for m in DB.control_measures.values() if m["permit_term_id"] == term_id]


def measure_by_code(term_id, code):
    for m in DB.control_measures.values():
        if m["permit_term_id"] == term_id and m["measure_code"] == code:
            return m
    return None


def outfalls_of_term(term_id):
    return [o for o in DB.outfalls.values() if o["permit_term_id"] == term_id]


def sites_of_term(term_id):
    return [s for s in DB.sites.values() if s["permit_term_id"] == term_id]


def accounts_of_term(term_id):
    return [a for a in DB.accounts.values() if a["permit_term_id"] == term_id]


def reports_of_term(term_id):
    return [r for r in DB.annual_reports.values() if r["permit_term_id"] == term_id]


def observations_of_outfall(outfall_id):
    return [o for o in DB.observations.values() if o["outfall_id"] == outfall_id]


def cases_of_outfall(outfall_id):
    return [c for c in DB.cases.values() if c["outfall_id"] == outfall_id]


def facilities_of_site(site_id):
    return [f for f in DB.facilities.values() if f["construction_site_id"] == site_id]


def applications_of_account(account_id):
    return [a for a in DB.credit_applications.values() if a["stormwater_account_id"] == account_id]


def cases_of_term(term_id):
    outfall_ids = {o["id"] for o in outfalls_of_term(term_id)}
    return [c for c in DB.cases.values() if c["outfall_id"] in outfall_ids]


def observations_of_term(term_id):
    outfall_ids = {o["id"] for o in outfalls_of_term(term_id)}
    return [o for o in DB.observations.values() if o["outfall_id"] in outfall_ids]


def term_of_outfall(outfall):
    return DB.permit_terms.get(outfall["permit_term_id"])


def term_of_site(site):
    return DB.permit_terms.get(site["permit_term_id"])


def term_of_case(case):
    outfall = DB.outfalls.get(case["outfall_id"])
    return term_of_outfall(outfall) if outfall else None


def term_of_facility(facility):
    site = DB.sites.get(facility["construction_site_id"])
    return term_of_site(site) if site else None


def term_of_observation(observation):
    outfall = DB.outfalls.get(observation["outfall_id"])
    return term_of_outfall(outfall) if outfall else None


def term_of_inspection(inspection):
    if inspection.get("construction_site_id"):
        site = DB.sites.get(inspection["construction_site_id"])
        return term_of_site(site) if site else None
    facility = DB.facilities.get(inspection.get("post_construction_facility_id"))
    return term_of_facility(facility) if facility else None


def term_of_action(action):
    if action.get("illicit_discharge_case_id"):
        case = DB.cases.get(action["illicit_discharge_case_id"])
        return term_of_case(case) if case else None
    if action.get("construction_site_id"):
        site = DB.sites.get(action["construction_site_id"])
        return term_of_site(site) if site else None
    facility = DB.facilities.get(action.get("post_construction_facility_id"))
    return term_of_facility(facility) if facility else None


def subject_key_of(action):
    for key in ("illicit_discharge_case_id", "construction_site_id", "post_construction_facility_id"):
        if action.get(key):
            return key, action[key]
    return None, None


def actions_on_same_subject(action):
    key, value = subject_key_of(action)
    if key is None:
        return []
    return [a for a in DB.enforcement_actions.values() if a.get(key) == value]


def actions_of_case(case_id):
    return [a for a in DB.enforcement_actions.values() if a.get("illicit_discharge_case_id") == case_id]


def actions_of_site(site_id):
    return [a for a in DB.enforcement_actions.values() if a.get("construction_site_id") == site_id]


def inspections_of_facility(facility_id):
    return [
        i
        for i in DB.inspections.values()
        if i.get("post_construction_facility_id") == facility_id
    ]


# ---------------------------------------------------------------------------
# post-construction facility currency (PRD 3.5)
# ---------------------------------------------------------------------------


def facility_state(facility):
    best = None
    for inspection in inspections_of_facility(facility["id"]):
        if inspection.get("status") != "FINALIZED" or not inspection.get("finalized_at"):
            continue
        if best is None:
            best = inspection
            continue
        if inspection["finalized_at"] > best["finalized_at"]:
            best = inspection
        elif inspection["finalized_at"] == best["finalized_at"] and (
            inspection.get("created_at"),
            inspection.get("_seq"),
        ) < (best.get("created_at"), best.get("_seq")):
            best = inspection

    last_finalized = best["finalized_at"] if best else None
    base_text = last_finalized or facility.get("agreement_recorded_at")
    base = to_dt(base_text)
    months = calc.whole_months_between(base, CLOCK.now()) if base else 0
    interval = facility.get("inspection_interval_months")
    overdue = bool(
        facility.get("agreement_status") == "RECORDED"
        and interval is not None
        and months > int(interval)
    )
    eligible = bool(
        facility.get("ownership") == "PRIVATE"
        and facility.get("agreement_status") == "RECORDED"
        and not overdue
    )
    return {
        "last_inspection_finalized_at": last_finalized,
        "months_since_last_inspection": months,
        "inspection_overdue": overdue,
        "credit_eligible": eligible,
    }


def refresh_facility(facility):
    """Write the currency fields onto the row without forcing a version bump."""
    state = facility_state(facility)
    changed = any(facility.get(k) != v for k, v in state.items())
    facility.update(state)
    return changed


# ---------------------------------------------------------------------------
# account fee chain (PRD 3.8)
# ---------------------------------------------------------------------------


def recompute_account(account):
    term = DB.permit_terms.get(account["permit_term_id"])
    eru_sqft = term.get("eru_sqft") if term else 3000
    fee = calc.tiered_fee(account["impervious_area_sqft"], eru_sqft, account["parcel_class"])
    pct = calc.credit_pool(applications_of_account(account["id"]), "FINAL")
    credit, net = calc.apply_credit(fee["gross_billable_cents"], pct)
    updates = dict(fee)
    updates["total_credit_pct"] = float(pct)
    updates["current_net_fee_cents"] = net
    changed = any(account.get(k) != v for k, v in updates.items())
    account.update(updates)
    if changed:
        touch(account)
    return changed


# ---------------------------------------------------------------------------
# child aggregates
# ---------------------------------------------------------------------------


def recompute_outfall(outfall):
    observations = observations_of_outfall(outfall["id"])
    screenings = [o for o in observations if o["observation_type"] == "DRY_WEATHER_SCREENING"]
    best = None
    for obs in screenings:
        if best is None:
            best = obs
            continue
        if obs["observed_at"] > best["observed_at"]:
            best = obs
        elif obs["observed_at"] == best["observed_at"] and (
            obs.get("created_at"),
            obs.get("_seq"),
        ) < (best.get("created_at"), best.get("_seq")):
            best = obs
    open_cases = [c for c in cases_of_outfall(outfall["id"]) if c["status"] != "RESOLVED"]
    total_lane_miles = sum((D(r["lane_miles_swept"]) for r in outfall.get("sweeping_runs", [])), D(0))
    if open_cases:
        screening_status = "SUSPECT"
    elif screenings:
        screening_status = "CLEAR"
    else:
        screening_status = "NOT_SCREENED"
    updates = {
        "screening_count": len(screenings),
        "last_screened_at": best["observed_at"] if best else None,
        "open_case_count": len(open_cases),
        "swept_lane_miles_ytd": calc.num(total_lane_miles, 2),
        "screening_status": screening_status,
    }
    changed = any(outfall.get(k) != v for k, v in updates.items())
    outfall.update(updates)
    if changed:
        touch(outfall)
    return changed


def recompute_case(case):
    actions = actions_of_case(case["id"])
    count = len([a for a in actions if a["status"] in ("ISSUED", "ESCALATED", "CLOSED")])
    if case.get("enforcement_action_count") != count:
        case["enforcement_action_count"] = count
        touch(case)
        return True
    return False


def recompute_site(site):
    actions = actions_of_site(site["id"])
    count = len([a for a in actions if a["status"] in ("ISSUED", "ESCALATED")])
    if site.get("open_enforcement_count") != count:
        site["open_enforcement_count"] = count
        touch(site)
        return True
    return False


def recompute_measure(measure, term):
    if measure.get("status") != "ACTIVE":
        return False
    term_id = term["id"]
    updates = {}
    code = measure["measure_code"]
    if code == "ILLICIT_DISCHARGE":
        updates["open_case_count"] = len(
            [c for c in cases_of_term(term_id) if c["status"] != "RESOLVED"]
        )
    if code == "CONSTRUCTION_RUNOFF":
        site_ids = {s["id"] for s in sites_of_term(term_id)}
        updates["enforcement_count"] = len(
            [
                a
                for a in DB.enforcement_actions.values()
                if a.get("construction_site_id") in site_ids
                and a["status"] in ("ISSUED", "ESCALATED", "CLOSED")
            ]
        )
    if code == "MUNICIPAL_OPERATIONS":
        total = D(0)
        runs_seen = 0
        for outfall in outfalls_of_term(term_id):
            if outfall.get("status") != "ACTIVE":
                continue
            for run in outfall.get("sweeping_runs", []):
                total += D(run["lane_miles_swept"])
                runs_seen += 1
        # The mirror only asserts itself once the term actually has sweeping
        # data; before that the measure keeps whatever it was created with.
        if runs_seen:
            mirrored = calc.num(total, 2)
            updates["swept_lane_miles_ytd"] = mirrored
            updates["measurable_goal_actual"] = mirrored

    probe = dict(measure)
    probe.update(updates)
    pct = calc.attainment_pct(probe.get("measurable_goal_actual"), probe.get("measurable_goal_target"))
    updates["attainment_pct"] = float(pct)
    updates["goal_status"] = calc.goal_status(probe, pct)

    changed = any(measure.get(k) != v for k, v in updates.items())
    measure.update(updates)
    if changed:
        touch(measure)
    return changed


def recompute_term(term):
    term_id = term["id"]
    measures = measures_of_term(term_id)
    behind = len([m for m in measures if m["status"] == "ACTIVE" and m["goal_status"] == "BEHIND"])
    outfalls = outfalls_of_term(term_id)
    exceeding = len(
        [o for o in outfalls if o["status"] == "ACTIVE" and o["tmdl_status"] == "EXCEEDING"]
    )
    accounts = accounts_of_term(term_id)
    revenue = sum(int(a.get("current_net_fee_cents") or 0) for a in accounts)
    ledger = 0
    for action in DB.enforcement_actions.values():
        if action["status"] not in ("ISSUED", "ESCALATED", "CLOSED"):
            continue
        action_term = term_of_action(action)
        if action_term is not None and action_term["id"] == term_id:
            ledger += int(action.get("penalty_cents") or 0)
    updates = {
        "behind_measure_count": behind,
        "exceeding_outfall_count": exceeding,
        "compliance_posture": calc.posture(behind, exceeding),
        "total_assessed_penalty_cents": ledger,
    }
    if accounts:
        # The revenue projection and its adequacy verdict only exist once the
        # utility has at least one billed parcel under the term.
        updates["projected_annual_revenue_cents"] = revenue
        updates["funding_adequacy_status"] = (
            "ADEQUATE" if revenue >= int(term.get("funding_target_cents") or 0) else "UNDERFUNDED"
        )
    changed = any(term.get(k) != v for k, v in updates.items())
    term.update(updates)
    if changed:
        touch(term)
    return changed


def recompute_world(term):
    """Recompute every derived aggregate under one permit term."""
    if term is None:
        return
    term_id = term["id"]
    for outfall in outfalls_of_term(term_id):
        recompute_outfall(outfall)
    for case in cases_of_term(term_id):
        recompute_case(case)
    for site in sites_of_term(term_id):
        recompute_site(site)
        for facility in facilities_of_site(site["id"]):
            refresh_facility(facility)
    for account in accounts_of_term(term_id):
        recompute_account(account)
    for measure in measures_of_term(term_id):
        recompute_measure(measure, term)
    recompute_term(term)


# ---------------------------------------------------------------------------
# annual report invalidation (PRD 2.8)
# ---------------------------------------------------------------------------


def snapshot(term):
    if term is None:
        return None
    return (term.get("compliance_posture"), int(term.get("total_assessed_penalty_cents") or 0))


def invalidate_reports(term, before, event_instant):
    """Push COMPILED/CERTIFIED reports of the term back to DRAFT when required."""
    if term is None or before is None or event_instant is None:
        return
    after = snapshot(term)
    posture_moved = after[0] != before[0]
    penalty_moved = after[1] != before[1]
    if not (posture_moved or penalty_moved):
        return
    reason = "POSTURE_CHANGED" if posture_moved else "PENALTY_LEDGER_CHANGED"
    for report in reports_of_term(term["id"]):
        if report["status"] not in ("COMPILED", "CERTIFIED"):
            continue
        start, end = calc.window_bounds(
            _date(report["reporting_period_start"]), _date(report["reporting_period_end"])
        )
        if not calc.in_window(event_instant, start, end):
            continue
        report["status"] = "DRAFT"
        report["compiled_at"] = None
        report["compiled_by_user_id"] = None
        report["certified_at"] = None
        report["certified_by_user_id"] = None
        report["certification_statement"] = None
        report["invalidation_count"] = int(report.get("invalidation_count") or 0) + 1
        report["invalidated_reason"] = reason
        touch(report)


def _date(text):
    from datetime import date as _d

    return _d.fromisoformat(text)
