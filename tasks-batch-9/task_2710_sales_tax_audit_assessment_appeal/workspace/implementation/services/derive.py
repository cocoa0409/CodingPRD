"""Read-time derivations, roll-ups and cascades.

Derived recomputation performed for a *read* never bumps version/updated_at
(PRD 2.5: the clock rewrites no stored field).  Explicit mutations call
db.touch() themselves.
"""
import db
from services import calc

LIVE_AUDIT_STATUSES = calc.LIVE_AUDIT_STATUSES


# ------------------------------------------------------------------- lookups
def audits_of_taxpayer(taxpayer_id):
    return db.where("audits", taxpayer_id=taxpayer_id)


def assessments_of_audit(audit_id):
    return db.where("assessments", audit_id=audit_id)


def taxpayer_of_audit(audit):
    return db.get("taxpayers", audit["taxpayer_id"])


def audit_of_assessment(assessment):
    return db.get("audits", assessment["audit_id"])


def taxpayer_of_assessment(assessment):
    audit = audit_of_assessment(assessment)
    return taxpayer_of_audit(audit) if audit else None


def proceedings_of_assessment(assessment_id):
    return db.where("appeal_proceedings", assessment_id=assessment_id)


def arrangements_of_assessment(assessment_id):
    return db.where("payment_arrangements", assessment_id=assessment_id)


def adjustments_of_assessment(assessment_id):
    return db.where("assessment_adjustments", assessment_id=assessment_id)


def agreements_of_audit(audit_id):
    return db.where("sampling_agreements", audit_id=audit_id)


def units_of_agreement(agreement_id):
    return db.where("sample_units", sampling_agreement_id=agreement_id)


def certificates_of_audit(audit_id):
    return db.where("exemption_certificates", audit_id=audit_id)


def purchases_of_audit(audit_id):
    return db.where("use_tax_purchases", audit_id=audit_id)


def waivers_of_audit(audit_id):
    return db.where("statute_waivers", audit_id=audit_id)


def all_assessments_of_taxpayer(taxpayer_id):
    out = []
    for audit in audits_of_taxpayer(taxpayer_id):
        out.extend(assessments_of_audit(audit["id"]))
    return out


# ------------------------------------------------------------------ taxpayer
def open_audit_count(taxpayer_id):
    return sum(
        1
        for a in audits_of_taxpayer(taxpayer_id)
        if a["status"] in LIVE_AUDIT_STATUSES
    )


def refresh_taxpayer(tp):
    lower = db.add_days(db.clock_date(), -calc.STATUTE_BASE_DAYS)
    upper = db.clock_date()
    reported = 0
    matched = 0
    for ir in db.where("information_returns", taxpayer_id=tp["id"]):
        end = db.parse_date(ir["period_end"])
        if end is not None and lower <= end <= upper:
            reported += int(ir["reported_amount_cents"])
            matched += int(ir["matched_return_amount_cents"])
    tp["reported_total_cents"] = reported
    tp["matched_total_cents"] = matched
    tp["info_variance_bp"] = calc.variance_bp(reported, matched)
    tp["delinquency_bp"] = calc.delinquency_bp(tp.get("delinquent_period_count") or 0)
    tp["magnitude_bp"] = calc.magnitude_bp(tp["gross_receipts_annual_cents"])
    tp["prior_audit_bp"] = calc.prior_audit_bp(tp.get("prior_audit_error_rate_bp"))
    tp["screening_score"] = calc.screening_score(tp["info_variance_bp"], tp["delinquency_bp"])
    tp["open_audit_count"] = open_audit_count(tp["id"])
    return tp


def refresh_info_return(ir):
    end = db.parse_date(ir["period_end"])
    ir["in_scoring_window"] = bool(end is not None and end <= db.clock_date())
    return ir


def recompute_taxpayer_compliance(taxpayer):
    """A taxpayer returns to COMPLIANT only when no assessment of theirs is REFERRED."""
    if taxpayer is None:
        return
    for asmt in all_assessments_of_taxpayer(taxpayer["id"]):
        if asmt["collection_status"] == "REFERRED":
            return
    if taxpayer["compliance_status"] != "COMPLIANT":
        taxpayer["compliance_status"] = "COMPLIANT"
        db.touch(taxpayer)


# ------------------------------------------------------------------- project
def refresh_project(project):
    used = 0
    for lead in db.where("audit_leads", industry_project_id=project["id"]):
        if lead["status"] in ("SELECTED", "CONVERTED"):
            used += 1
    project["selections_used"] = used
    project["selections_remaining"] = int(project["selection_quota"]) - used
    return project


# --------------------------------------------------------------------- audit
def tolled_days_of_audit(audit_id):
    total = 0
    for asmt in assessments_of_audit(audit_id):
        for prc in proceedings_of_assessment(asmt["id"]):
            if prc["status"] == "DECIDED":
                total += int(prc.get("tolled_days") or 0)
    return total


def executed_waivers_in_replay_order(audit_id):
    rows = [w for w in waivers_of_audit(audit_id) if w["status"] == "EXECUTED"]
    return sorted(
        rows,
        key=lambda w: (w.get("signed_date") or "", w["created_at"], w["_seq"]),
    )


def statute_replay(audit, write=False):
    """Returns (base_expiry, waiver_days_added, tolled_days, statute_expiry_date)."""
    scope_end = db.parse_date(audit.get("scope_period_end"))
    if scope_end is None:
        return None, 0, tolled_days_of_audit(audit["id"]), None
    base = db.add_days(scope_end, calc.STATUTE_BASE_DAYS)
    running = base
    days_added = 0
    for waiver in executed_waivers_in_replay_order(audit["id"]):
        extended = db.parse_date(waiver.get("extended_to_date"))
        if extended is None or extended <= running:
            if write:
                waiver["prior_expiry_date"] = db.format_date(running)
                waiver["days_added"] = 0
            continue
        gained = db.days_between(running, extended)
        if write:
            waiver["prior_expiry_date"] = db.format_date(running)
            waiver["days_added"] = gained
        days_added += gained
        running = extended
    tolled = tolled_days_of_audit(audit["id"])
    return base, days_added, tolled, db.add_days(running, tolled)


def refresh_audit(audit):
    base, days_added, tolled, expiry = statute_replay(audit, write=False)
    audit["base_statute_expiry_date"] = db.format_date(base)
    audit["waiver_days_added"] = days_added
    audit["tolled_days"] = tolled
    audit["statute_expiry_date"] = db.format_date(expiry)
    audit["statute_status"] = statute_status(expiry)
    return audit


def statute_status(expiry):
    if expiry is None:
        return "UNSET"
    today = db.clock_date()
    if today > expiry:
        return "EXPIRED"
    if db.days_between(today, expiry) <= calc.EXPIRING_SOON_DAYS:
        return "EXPIRING_SOON"
    return "PROTECTED"


def audit_statute_status(audit):
    _, _, _, expiry = statute_replay(audit, write=False)
    return statute_status(expiry)


def rewrite_statute(audit):
    """Explicit recomputation: writes the waiver replay fields too."""
    base, days_added, tolled, expiry = statute_replay(audit, write=True)
    audit["base_statute_expiry_date"] = db.format_date(base)
    audit["waiver_days_added"] = days_added
    audit["tolled_days"] = tolled
    audit["statute_expiry_date"] = db.format_date(expiry)
    audit["statute_status"] = statute_status(expiry)
    return audit


# ----------------------------------------------------------------- agreement
def refresh_agreement(agreement):
    base_total = 0
    unit_total = 0
    for stratum in agreement.get("strata") or []:
        base_total += int(stratum.get("population_base_amount_cents") or 0)
        unit_total += int(stratum.get("population_unit_count") or 0)
    agreement["population_base_amount_cents"] = base_total
    agreement["population_unit_count"] = unit_total
    # PRD 3.4: "The agreement additionally tracks its own examined_unit_count as
    # the number of sample units created against it" -- all rows, PENDING included.
    agreement["examined_unit_count"] = len(units_of_agreement(agreement["id"]))
    return agreement


# ---------------------------------------------------------- audit roll-up sums
def recompute_certificate_deficiency(audit):
    total = 0
    for cert in certificates_of_audit(audit["id"]):
        if cert["status"] == "REJECTED" and cert.get("sample_unit_id") is None:
            total += int(cert.get("missing_certificate_tax_cents") or 0)
    audit["certificate_deficiency_cents"] = total
    return total


def recompute_use_tax_deficiency(audit):
    total = 0
    for row in purchases_of_audit(audit["id"]):
        total += int(row.get("use_tax_due_cents") or 0)
    audit["use_tax_deficiency_cents"] = total
    return total


def mark_projection_stale(audit):
    """Sets the audit's projection stale and cascades DRAFT assessments."""
    audit["projection_status"] = "STALE"
    for asmt in assessments_of_audit(audit["id"]):
        if asmt["status"] == "DRAFT":
            asmt["status"] = "DRAFT_STALE"
            db.touch(asmt)


# ---------------------------------------------------------------- assessment
def refresh_assessment(assessment):
    total_adjustments = 0
    total_abated = 0
    for adj in adjustments_of_assessment(assessment["id"]):
        if adj["status"] != "POSTED":
            continue
        total_adjustments += int(adj["amount_cents"])
        if adj["kind"] == "PENALTY_ABATEMENT":
            total_abated += int(adj["amount_cents"])
    assessment["total_adjustments_cents"] = total_adjustments
    assessment["total_abated_cents"] = total_abated
    assessment["balance_due_cents"] = (
        int(assessment["total_due_cents"]) - total_adjustments - int(assessment["amount_paid_cents"])
    )
    return assessment


def has_open_proceeding(assessment_id):
    return any(p["status"] == "OPEN" for p in proceedings_of_assessment(assessment_id))


def clear_hold_if_settled(assessment):
    if not has_open_proceeding(assessment["id"]):
        assessment["collection_hold"] = False


def cascade_satisfied(assessment):
    """Fires whenever the collection axis reaches SATISFIED by any route."""
    assessment["collection_status"] = "SATISFIED"
    for arr in arrangements_of_assessment(assessment["id"]):
        if arr["status"] in ("REQUESTED", "APPROVED"):
            arr["status"] = "COMPLETED"
            db.touch(arr)
    recompute_taxpayer_compliance(taxpayer_of_assessment(assessment))


def finalize_notice(assessment):
    """ISSUED -> FINAL, cascading the audit closed and freeing the taxpayer."""
    assessment["status"] = "FINAL"
    db.touch(assessment)
    audit = audit_of_assessment(assessment)
    if audit is not None and audit["status"] == "ASSESSED":
        audit["status"] = "CLOSED"
        db.touch(audit)
        holder = taxpayer_of_audit(audit)
        if holder is not None:
            refresh_taxpayer(holder)
            db.touch(holder)
    return assessment


def settle_balance(assessment):
    """Re-derives the money block and moves the collection axis if it crossed zero."""
    refresh_assessment(assessment)
    if assessment["balance_due_cents"] == 0 and assessment["collection_status"] in (
        "DUE",
        "ARRANGED",
        "REFERRED",
    ):
        cascade_satisfied(assessment)
    elif assessment["balance_due_cents"] > 0 and assessment["collection_status"] == "SATISFIED":
        assessment["collection_status"] = "DUE"


def post_adjustment(assessment, kind, amount_cents, source, appeal_proceeding_id=None,
                    abatement_factors=None, abatement_pct=None):
    rec = db.new_record(
        {
            "assessment_id": assessment["id"],
            "appeal_proceeding_id": appeal_proceeding_id,
            "kind": kind,
            "amount_cents": int(amount_cents),
            "status": "POSTED",
            "abatement_factors": abatement_factors,
            "abatement_pct": abatement_pct,
            "posted_at": db.clock_instant_str(),
            "source": source,
            "reversal_reason": None,
        }
    )
    db.insert("assessment_adjustments", rec)
    return rec


# --------------------------------------------------------------- serialization
_REFRESHERS = {
    "taxpayers": refresh_taxpayer,
    "information_returns": refresh_info_return,
    "industry_projects": refresh_project,
    "audits": refresh_audit,
    "sampling_agreements": refresh_agreement,
    "assessments": refresh_assessment,
}


def view(kind, rec):
    refresher = _REFRESHERS.get(kind)
    if refresher is not None:
        refresher(rec)
    return db.public(rec)


def views(kind, records):
    return [view(kind, r) for r in records]
