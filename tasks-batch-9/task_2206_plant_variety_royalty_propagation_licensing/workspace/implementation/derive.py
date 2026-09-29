"""Derived-field re-aggregation and the cascades that propagate it.

Every derived money/quantity field is recomputed by full re-aggregation over
its source rows -- never adjusted by delta (PRD 2.6). Every record a cascade
actually mutates gets a fresh updated_at and version+1; a record a cascade
evaluates but does not change gets neither (PRD 2.9), except where a workflow
in PRD 3 pins the increment explicitly.
"""

from datetime import timedelta
from decimal import Decimal

import calculations as calc
from store import add_days, parse_dt, store

# --- status sets -----------------------------------------------------
FILING_IN_FORCE = ("GRANTED", "MAINTENANCE_DUE")
FILING_PENDING = ("DRAFT", "FILED")
FILING_LIVE = ("DRAFT", "FILED", "GRANTED", "MAINTENANCE_DUE")
TRIAL_OCCUPYING = ("PLANNED", "PLANTED")
TAG_COMMITTED = ("ISSUED", "RECONCILED")
QUOTA_LIVE = ("ACTIVE", "FROZEN")


def apply(record, updates=None, force=False):
    """Write `updates` onto `record`; bump version/updated_at when it changed."""
    dirty = bool(force)
    if updates:
        for key, value in updates.items():
            if record.get(key) != value:
                record[key] = value
                dirty = True
    if dirty:
        store.touch(record)
    return dirty


def children(collection, field, value):
    return [r for r in getattr(store, collection).values() if r[field] == value]


def ordered_children(collection, field, value, *tiebreaks):
    items = children(collection, field, value)
    items.sort(key=lambda r: r["_seq"])
    for key in reversed(tiebreaks):
        items.sort(key=key)
    items.sort(key=lambda r: r["created_at"])
    return items


# ==================================================================
# 2. variety protection posture
# ==================================================================
def protection_values(variety):
    """The four-branch ladder; the first matching branch wins (PRD 3.1)."""
    filings = children("filings", "variety_id", variety["id"])
    in_force = [f for f in filings if f["status"] in FILING_IN_FORCE]
    if in_force:
        posture = "PROTECTED"
    elif any(f["status"] in FILING_PENDING for f in filings):
        posture = "PENDING"
    elif any(f["status"] == "LAPSED" for f in filings):
        posture = "LAPSED_PROTECTION"
    else:
        posture = "UNPROTECTED"
    jurisdictions = sorted(set(f["jurisdiction_code"] for f in in_force))
    return posture, jurisdictions


def recompute_protection(variety, force=False):
    posture, jurisdictions = protection_values(variety)
    return apply(variety, {
        "protection_posture": posture,
        "protected_jurisdictions": jurisdictions,
    }, force=force)


# ==================================================================
# 1. trial aggregates on the variety
# ==================================================================
def variety_trial_aggregates(variety):
    passed = [t for t in children("trials", "variety_id", variety["id"])
              if t["status"] == "PASSED"]
    regions = set()
    for trial in passed:
        site = store.trial_sites.get(trial["trial_site_id"])
        if site is not None:
            regions.add(site["region_code"])
    index = calc.mean_index([t["performance_index"] for t in passed])
    return len(regions), index


def recompute_trial_site_occupancy(site, force=False):
    total = 0
    for trial in children("trials", "trial_site_id", site["id"]):
        if trial["status"] in TRIAL_OCCUPYING:
            total += int(trial["plot_count"])
    return apply(site, {"occupied_plot_count": total}, force=force)


def active_grant_count(variety):
    count = 0
    for grant in children("grants", "variety_id", variety["id"]):
        if grant["status"] == "ACTIVE":
            count += 1
    return count


def recompute_active_sublicense_count(variety, force=False):
    return apply(variety,
                 {"active_sublicense_count": active_grant_count(variety)},
                 force=force)


# ==================================================================
# 8. quota tag inventory
# ==================================================================
def recompute_quota_inventory(quota, force=False):
    committed = 0
    activated = 0
    for order in children("tag_orders", "quota_id", quota["id"]):
        if order["status"] in TAG_COMMITTED:
            committed += int(order["requested_units"])
        if order["status"] == "RECONCILED":
            activated += int(order["activated_units"])
    return apply(quota, {
        "tags_committed_units": committed,
        "units_available": int(quota["allocated_units"]) - committed,
        "tags_activated_units": activated,
    }, force=force)


# ==================================================================
# 5. royalty report pricing
# ==================================================================
def report_lines_ordered(report_id):
    lines = children("line_items", "report_id", report_id)
    lines.sort(key=lambda l: l["_seq"])

    def quota_key(line):
        quota = store.quotas.get(line["quota_id"]) or {}
        return (quota.get("season_code") or "", quota.get("territory_code") or "")

    lines.sort(key=quota_key)
    lines.sort(key=lambda l: l["created_at"])
    return lines


def _line_rate(line, agreement, billable_units):
    quota = store.quotas.get(line["quota_id"]) or {}
    variety = store.varieties.get(quota.get("variety_id")) or {}
    if quota.get("basis") == "PER_ACRE":
        base = variety.get("base_royalty_cents_per_acre", 0)
    else:
        base = variety.get("base_royalty_cents_per_plant", 0)
    return calc.effective_royalty_rate(
        base,
        agreement["quality_tier"],
        quota.get("territory_class") or "DOMESTIC",
        billable_units,
        variety.get("regional_performance_index", Decimal("0.00")),
    )


def price_report_reported_basis(report):
    """Submission pricing (PRD 3.7). Every recomputed line bumps its version."""
    agreement = store.agreements[report["agreement_id"]]
    total = 0
    for line in report_lines_ordered(report["id"]):
        billable = int(line["reported_units"])
        rate = _line_rate(line, agreement, billable)
        amount = calc.line_amount_cents(billable, rate)
        total += amount
        apply(line, {
            "billable_units": billable,
            "effective_rate_cents": rate,
            "provisional_amount_cents": amount,
            "overrun_flagged": False,
        }, force=True)
    return total


def price_report_audited_basis(report):
    """Acceptance pricing (PRD 3.7). Provisional figures are left untouched."""
    agreement = store.agreements[report["agreement_id"]]
    total = 0
    for line in report_lines_ordered(report["id"]):
        quota = store.quotas.get(line["quota_id"]) or {}
        activated = int(quota.get("tags_activated_units") or 0)
        reported = int(line["reported_units"])
        billable = max(reported, activated)
        rate = _line_rate(line, agreement, billable)
        amount = calc.line_amount_cents(billable, rate)
        total += amount
        apply(line, {
            "billable_units": billable,
            "effective_rate_cents": rate,
            "final_amount_cents": amount,
            "overrun_flagged": activated > reported,
        }, force=True)
    return total


# ==================================================================
# 9. propagator royalty ledger
# ==================================================================
def propagator_reports(propagator_id):
    out = []
    for agreement in children("agreements", "propagator_id", propagator_id):
        out.extend(children("reports", "agreement_id", agreement["id"]))
    return out


def ledger_values(propagator_id):
    payable = 0
    settled = 0
    for report in propagator_reports(propagator_id):
        if report["review_status"] != "ACCEPTED":
            continue
        booked = int(report["booked_amount_cents"])
        if report["settlement_status"] in ("UNSETTLED", "REVERSED"):
            payable += booked
        elif report["settlement_status"] == "SETTLED":
            settled += booked
    return payable, settled


def recompute_ledger(propagator, force=False):
    payable, settled = ledger_values(propagator["id"])
    return apply(propagator, {
        "royalty_payable_cents": payable,
        "royalty_settled_cents": settled,
    }, force=force)


def propagator_engagements(propagator_id):
    out = []
    for agreement in children("agreements", "propagator_id", propagator_id):
        out.extend(children("engagements", "agreement_id", agreement["id"]))
    return out


def material_finding_count(propagator_id):
    count = 0
    for engagement in propagator_engagements(propagator_id):
        if (engagement["status"] == "FINDINGS_ISSUED"
                and engagement["finding_severity"] == "MATERIAL"):
            count += 1
    return count


def recompute_material_finding_count(propagator, force=False):
    return apply(propagator,
                 {"material_audit_finding_count": material_finding_count(propagator["id"])},
                 force=force)


# ==================================================================
# 6. compliance scoring
# ==================================================================
def penalty_events(propagator_id):
    """Derived on demand from persisted rows -- never an event log."""
    events = []
    for report in propagator_reports(propagator_id):
        if report["review_status"] != "ACCEPTED":
            continue
        if report["is_late"] and report["submitted_at"]:
            events.append((calc.PENALTY_LATE_REPORT, parse_dt(report["submitted_at"])))
        if report["accepted_at"]:
            for line in children("line_items", "report_id", report["id"]):
                if line["overrun_flagged"]:
                    events.append((calc.PENALTY_QUOTA_OVERRUN,
                                   parse_dt(report["accepted_at"])))
    for engagement in propagator_engagements(propagator_id):
        if engagement["status"] != "FINDINGS_ISSUED" or not engagement["finalized_at"]:
            continue
        if engagement["finding_severity"] == "MINOR":
            events.append((calc.PENALTY_MINOR_AUDIT_FINDING,
                           parse_dt(engagement["finalized_at"])))
        elif engagement["finding_severity"] == "MATERIAL":
            events.append((calc.PENALTY_MATERIAL_AUDIT_FINDING,
                           parse_dt(engagement["finalized_at"])))
    for case in store.cases.values():
        if case["suspected_propagator_id"] != propagator_id:
            continue
        if not case["concluded_at"]:
            continue
        confirmed = (case["status"] == "MATCH_CONFIRMED"
                     or (case["status"] == "RESOLVED"
                         and case.get("_concluded_result") == "MATCH_CONFIRMED"))
        if confirmed:
            events.append((calc.PENALTY_CONFIRMED_UNAUTH_MATCH,
                           parse_dt(case["concluded_at"])))
    return [(points, at) for points, at in events if at is not None]


def compliance_scores(propagator_id):
    now = store.now
    lower = now - timedelta(days=calc.COMPLIANCE_WINDOW_DAYS)
    rolling = 0
    lifetime = 0
    for points, at in penalty_events(propagator_id):
        lifetime += points
        if lower < at <= now:
            rolling += points
    return calc.score_from_points(rolling), calc.score_from_points(lifetime)


def freeze_agreement_quotas(agreement):
    """Suspension cascade limb: ACTIVE quotas of the agreement -> FROZEN."""
    quotas = ordered_children("quotas", "agreement_id", agreement["id"],
                              lambda q: q["season_code"])
    for quota in quotas:
        if quota["status"] == "ACTIVE":
            apply(quota, {"status": "FROZEN"})


def thaw_agreement_quotas(agreement):
    quotas = ordered_children("quotas", "agreement_id", agreement["id"],
                              lambda q: q["season_code"])
    for quota in quotas:
        if quota["status"] == "FROZEN":
            apply(quota, {"status": "ACTIVE"})


def suspend_agreement(agreement, reason):
    apply(agreement, {"status": "SUSPENDED", "suspension_reason": reason})
    freeze_agreement_quotas(agreement)


def recompute_compliance(propagator, force=False):
    """Recompute both scores and run the auto-suspension cascade below 70."""
    rolling, lifetime = compliance_scores(propagator["id"])
    changed = apply(propagator, {
        "compliance_score": rolling,
        "lifetime_compliance_score": lifetime,
    }, force=force)
    auto_suspend_below_threshold(propagator, rolling)
    return changed


def close_quota_and_void_requests(quota):
    apply(quota, {"status": "CLOSED"})
    orders = ordered_children("tag_orders", "quota_id", quota["id"])
    for order in orders:
        if order["status"] == "REQUESTED":
            apply(order, {
                "status": "VOIDED",
                "voided_units": int(order["requested_units"]),
            })


def revoke_grants_for_lapsed_filing(variety, jurisdiction_code):
    grants = ordered_children("grants", "variety_id", variety["id"],
                              lambda g: g["territory_code"],
                              lambda g: g["sublicensee_name"])
    touched = False
    for grant in grants:
        if grant["status"] == "ACTIVE" and grant["jurisdiction_code"] == jurisdiction_code:
            apply(grant, {"status": "REVOKED", "revocation_reason": "PROTECTION_LAPSED"})
            touched = True
    return touched


def lapse_filing(filing, reason):
    """The three-level cascade shared by voluntary lapse and grace expiry.

    PRD 3.2 pins the version increments to exactly one for the filing, one for
    the variety and one per revoked grant, so both variety derivations are
    committed as a single mutation.
    """
    apply(filing, {"status": "LAPSED", "lapse_reason": reason})
    variety = store.varieties.get(filing["variety_id"])
    if variety is None:
        return
    posture, jurisdictions = protection_values(variety)
    if filing["jurisdiction_code"] not in jurisdictions:
        revoke_grants_for_lapsed_filing(variety, filing["jurisdiction_code"])
    apply(variety, {
        "protection_posture": posture,
        "protected_jurisdictions": jurisdictions,
        "active_sublicense_count": active_grant_count(variety),
    }, force=True)


def grace_deadline(filing):
    due = parse_dt(filing["annuity_due_date"])
    if due is None:
        return None
    return add_days(due, int(filing["annuity_grace_days"]))


def auto_suspend_below_threshold(propagator, rolling):
    """Cascade limb shared by every compliance recomputation (PRD 2.11)."""
    if rolling >= calc.COMPLIANCE_SUSPEND_THRESHOLD:
        return
    for agreement in ordered_children("agreements", "propagator_id", propagator["id"]):
        if agreement["status"] == "ACTIVE":
            suspend_agreement(agreement, "COMPLIANCE_SCORE_BREACH")


def refresh_after_accept(propagator):
    """Report acceptance: ledger and both scores land as one propagator mutation
    whose version PRD 3.7 pins to a single increment."""
    payable, settled = ledger_values(propagator["id"])
    rolling, lifetime = compliance_scores(propagator["id"])
    apply(propagator, {
        "royalty_payable_cents": payable,
        "royalty_settled_cents": settled,
        "compliance_score": rolling,
        "lifetime_compliance_score": lifetime,
    }, force=True)
    auto_suspend_below_threshold(propagator, rolling)


def refresh_after_finalize(propagator, material):
    """Engagement finalization: material count (MATERIAL only), ledger and both
    scores land as one propagator mutation, bumped only if something changed."""
    updates = {}
    if material:
        updates["material_audit_finding_count"] = material_finding_count(propagator["id"])
    payable, settled = ledger_values(propagator["id"])
    updates["royalty_payable_cents"] = payable
    updates["royalty_settled_cents"] = settled
    rolling, lifetime = compliance_scores(propagator["id"])
    updates["compliance_score"] = rolling
    updates["lifetime_compliance_score"] = lifetime
    apply(propagator, updates)
    return rolling
