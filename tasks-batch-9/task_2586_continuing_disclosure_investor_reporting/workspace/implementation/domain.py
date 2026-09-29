"""Derived-field recomputation, ordered cascades, and the sweep engine."""
from decimal import Decimal

import calc
from core import (DB, by_seq, clock_date, clock_stamp, date_part, day_diff,
                  engagements_of, cycles_of, failure_events_of,
                  failure_events_of_cycle, items_of, new_row, notices_of_issue,
                  parse_date_str, requirements_of, touch, undertaking_for_issue)


# ---------------------------------------------------------------- derived flags
def recompute_open_material_event_count(issue):
    if issue is None:
        return
    count = len([n for n in notices_of_issue(issue["id"])
                 if n["status"] in calc.OPEN_NOTICE_STATUSES])
    if issue["open_material_event_count"] != count:
        touch(issue)
        issue["open_material_event_count"] = count


def recompute_completeness(cycle):
    if cycle is None:
        return
    score = calc.completeness_score(cycle)
    if cycle["completeness_score_pct"] != score:
        touch(cycle)
        cycle["completeness_score_pct"] = score


def recompute_counters(undertaking):
    """late_filing_count / missed_event_count / delinquent_cycle_count /
    content_weight_bp_total — always a full aggregation over source rows."""
    if undertaking is None:
        return
    events = failure_events_of(undertaking["id"])
    late = len([e for e in events
                if e["kind"] in ("ANNUAL_REPORT_LATE", "ANNUAL_REPORT_MISSED")])
    missed = len([e for e in events if e["kind"] == "MATERIAL_EVENT_MISSED"])
    delinquent = len([c for c in cycles_of(undertaking["id"])
                      if c["status"] == "DELINQUENT"])
    weight_total = sum(r["weight_bp"] for r in requirements_of(undertaking["id"]))
    if (undertaking["late_filing_count"] != late
            or undertaking["missed_event_count"] != missed
            or undertaking["delinquent_cycle_count"] != delinquent
            or undertaking["content_weight_bp_total"] != weight_total):
        touch(undertaking)
        undertaking["late_filing_count"] = late
        undertaking["missed_event_count"] = missed
        undertaking["delinquent_cycle_count"] = delinquent
        undertaking["content_weight_bp_total"] = weight_total


def run_risk_pass(undertaking):
    """Runs exactly once per trigger; reads the *persisted* remediation_tier."""
    if undertaking is None:
        return
    score, tier = calc.risk_score_and_tier(
        undertaking["late_filing_count"],
        undertaking["missed_event_count"],
        undertaking["delinquent_cycle_count"],
        undertaking["remediation_tier"],
    )
    posture = calc.compliance_posture(score, undertaking["delinquent_cycle_count"])
    if (undertaking["disclosure_risk_score"] != score
            or undertaking["remediation_tier"] != tier
            or undertaking["compliance_posture"] != posture):
        touch(undertaking)
        undertaking["disclosure_risk_score"] = score
        undertaking["remediation_tier"] = tier
        undertaking["compliance_posture"] = posture


def recompute_open_obligation_count(undertaking):
    if undertaking is None:
        return
    open_cycles = len([c for c in cycles_of(undertaking["id"])
                       if c["status"] in calc.OPEN_CYCLE_STATUSES])
    open_notices = len([n for n in notices_of_issue(undertaking["issue_id"])
                        if n["status"] in calc.OPEN_NOTICE_STATUSES])
    total = open_cycles + open_notices
    if undertaking["open_obligation_count"] != total:
        touch(undertaking)
        undertaking["open_obligation_count"] = total


def recompute_invoice(engagement, posture=None):
    """Skipped entirely for TERMINATED engagements — their invoice is frozen."""
    if engagement is None or engagement["status"] == "TERMINATED":
        return
    if posture is None:
        undertaking = DB.undertakings.get(engagement["undertaking_id"])
        posture = undertaking["compliance_posture"] if undertaking else "COMPLIANT"
    count = calc.confirmed_filing_count(engagement["id"])
    total = calc.invoice_total(count, engagement["retainer_cents"], posture)
    if (engagement["billable_filing_count"] != count
            or engagement["invoice_total_cents"] != total):
        touch(engagement)
        engagement["billable_filing_count"] = count
        engagement["invoice_total_cents"] = total


def recompute_undertaking_invoices(undertaking):
    if undertaking is None:
        return
    for engagement in engagements_of(undertaking["id"]):
        recompute_invoice(engagement, undertaking["compliance_posture"])


def refresh_monitoring_lapse(engagement):
    if engagement is None or engagement["status"] == "TERMINATED":
        return
    lapse = calc.monitoring_lapse_days(engagement)
    if engagement["monitoring_lapse_days"] != lapse:
        touch(engagement)
        engagement["monitoring_lapse_days"] = lapse


def undertaking_recompute_all(undertaking):
    """Counters, then the risk pass, then obligations, then invoice, then flags."""
    if undertaking is None:
        return
    recompute_counters(undertaking)
    run_risk_pass(undertaking)
    recompute_open_obligation_count(undertaking)
    recompute_undertaking_invoices(undertaking)
    recompute_open_material_event_count(DB.bond_issues.get(undertaking["issue_id"]))


# ------------------------------------------------------------ row constructors
def create_notice(issue_id, event_type, occurrence_date, created_by_user_id,
                  per_se=None, financial_obligation_ref=None, rating_agency=None,
                  prior_rating=None, new_rating=None):
    if per_se is None:
        per_se = calc.is_per_se_material(event_type)
    notice = new_row({
        "issue_id": issue_id,
        "event_type": event_type,
        "per_se_material": per_se,
        "occurrence_date": occurrence_date.isoformat(),
        "filing_deadline_date": calc.material_event_deadline(occurrence_date).isoformat(),
        "status": "DETERMINATION_PENDING",
        "determination_note": None,
        "determined_by_user_id": None,
        "determined_at": None,
        "created_by_user_id": created_by_user_id,
        "rating_agency": rating_agency,
        "prior_rating": prior_rating,
        "new_rating": new_rating,
        "financial_obligation_ref": financial_obligation_ref,
        "filed_filing_id": None,
        "days_late": 0,
    })
    DB.notices[notice["id"]] = notice
    return notice


def create_failure_event(undertaking_id, kind, occurred_at, days_late,
                         cycle_id=None, material_event_id=None):
    event = new_row({
        "undertaking_id": undertaking_id,
        "cycle_id": cycle_id,
        "material_event_id": material_event_id,
        "kind": kind,
        "occurred_at": occurred_at.isoformat() if hasattr(occurred_at, "isoformat")
        else occurred_at,
        "days_late": days_late,
        "severity": calc.failure_severity(kind, days_late),
        "status": "OPEN",
        "remediation_filing_id": None,
        "remediation_note": None,
        "remediated_at": None,
        "disclosed_in_official_statement_ids": [],
    })
    DB.failure_events[event["id"]] = event
    return event


def create_content_items(cycle, undertaking):
    for requirement in requirements_of(undertaking["id"]):
        item = new_row({
            "cycle_id": cycle["id"],
            "content_requirement_id": requirement["id"],
            "status": "NOT_STARTED",
            "weight_bp_snapshot": requirement["weight_bp"],
            "audit_opinion_type": None,
            "data_as_of_date": None,
            "source_document_ref": None,
            "attested_by_user_id": None,
            "attested_at": None,
            "waiver_reason": None,
            "readiness_factor": calc.readiness_factor("NOT_STARTED"),
        })
        DB.content_items[item["id"]] = item


# -------------------------------------------------------- termination cascade
def terminate_issue(issue, cause, actor_id=None, defeasance_type=None,
                    escrow_deposit_cents=None, occurrence_date=None):
    """The shared four-hop cascade behind defeasance (§3.1) and maturity (§3.11)."""
    touch(issue)
    if cause == "DEFEASANCE":
        issue["status"] = "DEFEASED"
        issue["defeasance_type"] = defeasance_type
        issue["escrow_deposit_cents"] = escrow_deposit_cents
        issue["defeased_at"] = clock_stamp()
    else:
        issue["status"] = "MATURED"
        issue["matured_at"] = clock_stamp()
    issue["outstanding_par_amount_cents"] = 0

    undertaking = undertaking_for_issue(issue["id"])
    if undertaking is not None and undertaking["status"] in ("ACTIVE", "SUSPENDED"):
        touch(undertaking)
        undertaking["status"] = "TERMINATED"
        undertaking["termination_cause"] = cause
        # hop 2 — non-terminal cycles close, created_at ascending
        for cycle in cycles_of(undertaking["id"]):
            if cycle["status"] not in ("DRAFTING", "READY_TO_FILE", "DELINQUENT"):
                continue
            touch(cycle)
            cycle["status"] = "CLOSED_NOT_REQUIRED"
            # hop 3 — content items void
            for item in items_of(cycle["id"]):
                if item["status"] == "VOID":
                    continue
                touch(item)
                item["status"] = "VOID"
                item["readiness_factor"] = calc.readiness_factor("VOID")
            recompute_completeness(cycle)
        # hop 2b — engagements terminate, invoice freezes
        for engagement in engagements_of(undertaking["id"]):
            if engagement["status"] not in ("ACTIVE", "SUSPENDED"):
                continue
            touch(engagement)
            engagement["status"] = "TERMINATED"
            engagement["termination_reason"] = "UNDERTAKING_TERMINATED"

    # every open notice on the issue is voided
    for notice in notices_of_issue(issue["id"]):
        if notice["status"] not in ("DETERMINATION_PENDING", "MATERIAL"):
            continue
        touch(notice)
        notice["status"] = "VOID"

    # a row minted after the void pass is untouched by it
    if cause == "DEFEASANCE" and occurrence_date is not None:
        create_notice(issue["id"], "DEFEASANCE", occurrence_date, actor_id,
                      per_se=True)

    recompute_open_material_event_count(issue)
    if undertaking is not None:
        recompute_counters(undertaking)
        run_risk_pass(undertaking)
        recompute_open_obligation_count(undertaking)
        recompute_undertaking_invoices(undertaking)
    return undertaking


# --------------------------------------------- official-statement lookback pass
def lookback_required_ids(statement):
    issue = DB.bond_issues.get(statement["issue_id"])
    program = issue["issuer_program_code"] if issue else None
    dated = parse_date_str(statement["dated_date"])
    if dated is None:
        return []
    left_edge = calc.minus_five_years(dated)
    scope_issues = set(i["id"] for i in DB.bond_issues.values()
                       if i["issuer_program_code"] == program)
    scope_undertakings = set(u["id"] for u in DB.undertakings.values()
                             if u["issue_id"] in scope_issues)
    candidates = []
    for event in DB.failure_events.values():
        if event["undertaking_id"] not in scope_undertakings:
            continue
        occurred = parse_date_str(event["occurred_at"])
        if occurred is None or occurred < left_edge or occurred >= dated:
            continue
        if statement["lookback_policy"] == "REMEDIATED_EXCLUDED":
            if event["status"] == "REMEDIATED":
                remediated = date_part(event["remediated_at"])
                if remediated is not None and remediated < dated:
                    continue
        candidates.append(event)
    candidates.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    return [e["id"] for e in candidates]


def apply_lookback(statement):
    required = lookback_required_ids(statement)
    disclosed = set(statement["disclosed_event_ids"])
    adequacy = "ADEQUATE" if all(i in disclosed for i in required) else "INCOMPLETE"
    if (statement["required_disclosure_event_ids"] != required
            or statement["required_disclosure_event_count"] != len(required)
            or statement["disclosure_adequacy"] != adequacy):
        touch(statement)
        statement["required_disclosure_event_ids"] = required
        statement["required_disclosure_event_count"] = len(required)
        statement["disclosure_adequacy"] = adequacy
    return required, adequacy


def rerun_program_lookbacks(program_code):
    if program_code is None:
        return
    for statement in by_seq(DB.official_statements.values()):
        if statement["status"] != "COMPLIANCE_REVIEW":
            continue
        issue = DB.bond_issues.get(statement["issue_id"])
        if issue is None or issue["issuer_program_code"] != program_code:
            continue
        apply_lookback(statement)


def program_code_of_undertaking(undertaking):
    if undertaking is None:
        return None
    issue = DB.bond_issues.get(undertaking["issue_id"])
    return issue["issuer_program_code"] if issue else None


def stamp_statement_on_event(event, statement_id):
    ids = event["disclosed_in_official_statement_ids"]
    if statement_id in ids:
        return
    touch(event)
    event["disclosed_in_official_statement_ids"] = ids + [statement_id]


# ------------------------------------------------------- timeliness assessment
def assess_cycle_timeliness(cycle, undertaking, filing):
    variant = undertaking["timeliness_basis"] if undertaking else "SUBMISSION_BASIS"
    if variant == "CONFIRMATION_BASIS":
        basis_instant = filing["repository_confirmed_at"]
    else:
        basis_instant = filing["submitted_at"]
    basis_date = date_part(basis_instant)
    due_date = parse_date_str(cycle["due_date"])
    timely = basis_date is not None and due_date is not None and basis_date <= due_date
    touch(cycle)
    cycle["filed_at"] = basis_instant
    cycle["timeliness_basis_applied"] = variant
    cycle["filed_filing_id"] = filing["id"]
    cycle["status"] = "FILED_TIMELY" if timely else "FILED_LATE"
    cycle["days_late"] = 0 if timely else day_diff(basis_date, due_date)
    return timely


def assess_notice_timeliness(notice, filing):
    submitted_date = date_part(filing["submitted_at"])
    deadline = parse_date_str(notice["filing_deadline_date"])
    timely = (submitted_date is not None and deadline is not None
              and submitted_date <= deadline)
    touch(notice)
    notice["status"] = "FILED_TIMELY" if timely else "FILED_LATE"
    notice["days_late"] = 0 if timely else day_diff(submitted_date, deadline)
    notice["filed_filing_id"] = filing["id"]
    return timely


def settle_cycle_failure_events(cycle, late):
    """Hop 2 of the confirmation cascade — only a FILED_LATE cycle mints one."""
    existing = failure_events_of_cycle(cycle["id"])
    created = None
    if late:
        if not existing:
            created = create_failure_event(
                cycle["undertaking_id"], "ANNUAL_REPORT_LATE",
                parse_date_str(cycle["due_date"]), cycle["days_late"],
                cycle_id=cycle["id"])
        else:
            for event in existing:
                touch(event)
                event["days_late"] = cycle["days_late"]
                if event["status"] == "OPEN":
                    event["status"] = "REMEDIATION_PENDING"
    else:
        for event in existing:
            if event["status"] == "OPEN":
                touch(event)
                event["status"] = "REMEDIATION_PENDING"
    return created


# ------------------------------------------------------------- calendar sweep
def run_sweep():
    today = clock_date()
    counts = {
        "matured_issue_count": 0,
        "delinquent_cycle_count": 0,
        "missed_event_count": 0,
        "suspended_engagement_count": 0,
        "failure_event_created_count": 0,
    }
    touched = []

    def mark(undertaking):
        if undertaking is None:
            return
        for known in touched:
            if known is undertaking:
                return
        touched.append(undertaking)

    # step 1 — maturity
    for issue in by_seq(list(DB.bond_issues.values())):
        if issue["status"] != "OUTSTANDING":
            continue
        maturity = parse_date_str(issue["final_maturity_date"])
        if maturity is None or not maturity < today:
            continue
        terminate_issue(issue, "MATURITY")
        counts["matured_issue_count"] += 1
        mark(undertaking_for_issue(issue["id"]))

    # step 2 — delinquency
    for cycle in by_seq(list(DB.cycles.values())):
        if cycle["status"] not in ("DRAFTING", "READY_TO_FILE"):
            continue
        due_date = parse_date_str(cycle["due_date"])
        if due_date is None or not due_date < today:
            continue
        touch(cycle)
        cycle["status"] = "DELINQUENT"
        cycle["assembled_by_user_id"] = None
        cycle["assembled_at"] = None
        create_failure_event(cycle["undertaking_id"], "ANNUAL_REPORT_MISSED",
                             due_date, day_diff(today, due_date),
                             cycle_id=cycle["id"])
        counts["delinquent_cycle_count"] += 1
        counts["failure_event_created_count"] += 1
        mark(DB.undertakings.get(cycle["undertaking_id"]))

    # step 3 — missed listed events
    for notice in by_seq(list(DB.notices.values())):
        if notice["status"] != "MATERIAL":
            continue
        deadline = parse_date_str(notice["filing_deadline_date"])
        if deadline is None or not deadline < today:
            continue
        touch(notice)
        notice["status"] = "MISSED"
        notice["days_late"] = day_diff(today, deadline)
        undertaking = undertaking_for_issue(notice["issue_id"])
        create_failure_event(undertaking["id"] if undertaking else None,
                             "MATERIAL_EVENT_MISSED", deadline,
                             day_diff(today, deadline),
                             material_event_id=notice["id"])
        counts["missed_event_count"] += 1
        counts["failure_event_created_count"] += 1
        mark(undertaking)
        recompute_open_material_event_count(DB.bond_issues.get(notice["issue_id"]))

    # step 4 — monitoring lapse
    for engagement in by_seq(list(DB.engagements.values())):
        if engagement["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        refresh_monitoring_lapse(engagement)
        if (engagement["status"] == "ACTIVE"
                and engagement["monitoring_lapse_days"] > calc.MONITORING_ACK_MAX_GAP_DAYS):
            touch(engagement)
            engagement["status"] = "SUSPENDED"
            counts["suspended_engagement_count"] += 1
            mark(DB.undertakings.get(engagement["undertaking_id"]))

    # step 5 — recomputation, once per touched undertaking
    for undertaking in touched:
        undertaking_recompute_all(undertaking)

    result = {"swept_at": clock_stamp()}
    result.update(counts)
    return result
