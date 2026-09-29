"""Serialization, derived-field recomputation, ledgers and cascades."""

from datetime import timedelta
from decimal import Decimal

import calc
import store as K
from errors import ApiError
from store import by_seq, create_row, store, touch
from validate import d, ds

# ---------------------------------------------------------------- lookups


def rows_of(collection, **filters):
    out = []
    for row in collection.values():
        keep = True
        for key, value in filters.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return by_seq(out)


def cycle_disciplines(cycle_id):
    return rows_of(store.disciplines, cycle_id=cycle_id)


def discipline_by_code(cycle_id, code):
    for row in cycle_disciplines(cycle_id):
        if row["code"] == code:
            return row
    return None


def residency_discipline(res):
    if res.get("discipline_code") is None:
        return None
    return discipline_by_code(res["cycle_id"], res["discipline_code"])


def source_application(res):
    app_id = res.get("application_id")
    if app_id is None:
        return None
    return store.applications.get(app_id)


def residency_hazmat(res):
    app = source_application(res)
    if app is None:
        return False
    return bool(application_hazmat(app))


def visa_case_of(residency_id):
    for row in by_seq(list(store.visa_cases.values())):
        if row["residency_id"] == residency_id:
            return row
    return None


# ---------------------------------------------------------------- Applicant derived
def applicant_is_international(applicant):
    return applicant["citizenship_country"] != K.HOST_COUNTRY


def applicant_completed_residency_count(applicant_id):
    count = 0
    for res in store.residencies.values():
        if res["applicant_id"] == applicant_id and res["status"] == "COMPLETED":
            count += 1
    return count


# ---------------------------------------------------------------- Application derived
def application_portfolio_items(application_id):
    return rows_of(store.portfolio_items, application_id=application_id)


def application_media_types(application_id):
    types = set()
    for item in application_portfolio_items(application_id):
        types.add(item["media_type"])
    return sorted(types)


def application_hazmat(app):
    for item in application_portfolio_items(app["id"]):
        if item["hazardous_materials_declared"]:
            return True
    return False


def application_assignments(application_id):
    return rows_of(store.panel_assignments, application_id=application_id)


def scored_totals(application_id):
    totals = []
    for pa in application_assignments(application_id):
        if pa["status"] == "SCORED" and pa.get("panelist_total_100") is not None:
            totals.append(pa["panelist_total_100"])
    return totals


def assigned_panelist_count(application_id):
    """Assignments that still count as live panel seats."""
    return len([pa for pa in application_assignments(application_id)
                if pa["status"] in ("ASSIGNED", "SCORED")])


def refresh_application_scores(app):
    """Recompute the score legs; promote across quorum or demote back.

    Returns the number of cycle-level state changes (quorum edges) observed.
    """
    cycle = store.cycles[app["cycle_id"]]
    totals = scored_totals(app["id"])
    provisional = calc.provisional_screening_score(totals)
    app["provisional_screening_score"] = provisional

    edges = 0
    n = len(totals)
    quorum = cycle["panel_quorum"]
    if app["status"] == "PANEL_REVIEW" and n >= quorum:
        app["status"] = "SCORED"
        edges += 1
    elif app["status"] == "SCORED" and n < quorum:
        app["status"] = "PANEL_REVIEW"
        edges += 1

    if app["status"] == "SCORED":
        final = calc.final_panel_score(totals, quorum)
        app["final_panel_score"] = final
    else:
        app["final_panel_score"] = None
        app["rank_in_discipline"] = None
    recompute_ranks(app["discipline_id"])
    return edges


def recompute_ranks(discipline_id):
    """1-based merit position inside the discipline over SCORED applications."""
    pool = [a for a in rows_of(store.applications, discipline_id=discipline_id)
            if a["status"] == "SCORED" and a.get("final_panel_score") is not None]
    pool.sort(key=lambda a: (-a["final_panel_score"], a["_seq"]))
    for index, app in enumerate(pool, start=1):
        app["rank_in_discipline"] = index


def recompute_panelist_counters(panelist):
    assigned = 0
    conflicts = 0
    for pa in store.panel_assignments.values():
        if pa["panelist_id"] != panelist["id"]:
            continue
        if pa["status"] in ("ASSIGNED", "SCORED"):
            assigned += 1
        if pa["status"] == "CONFLICT_DECLARED":
            conflicts += 1
    panelist["assigned_count"] = assigned
    panelist["conflict_count"] = conflicts


# ---------------------------------------------------------------- Cycle ledgers
AWARDED_STATUSES = ("SCHEDULED", "IN_RESIDENCE", "COMPLETED", "TERMINATED")


def cycle_residencies(cycle_id):
    return rows_of(store.residencies, cycle_id=cycle_id)


def cycle_ledger(cycle):
    committed = 0
    filled = 0
    for res in cycle_residencies(cycle["id"]):
        if res["status"] in AWARDED_STATUSES:
            committed += int(res.get("stipend_total_cents") or 0)
            filled += 1
    uncommitted = int(cycle["stipend_pool_cents"]) - committed
    open_count = cycle["cohort_target_size"] - filled
    if open_count < 0:
        open_count = 0
    return committed, uncommitted, filled, open_count


def cycle_applications(cycle_id):
    return rows_of(store.applications, cycle_id=cycle_id)


def cycle_slate_ready_count(cycle_id):
    return len([a for a in cycle_applications(cycle_id) if a["status"] == "SCORED"])


def cycle_panel_review_complete(cycle_id):
    apps = cycle_applications(cycle_id)
    scored = [a for a in apps if a["status"] == "SCORED"]
    in_review = [a for a in apps if a["status"] == "PANEL_REVIEW"]
    return len(scored) >= 1 and len(in_review) == 0


# ---------------------------------------------------------------- Residency derived
def residency_visa_required(res):
    applicant = store.applicants.get(res["applicant_id"])
    if applicant is None:
        return False
    return applicant_is_international(applicant)


def residency_tax_form_type(res):
    return "1042S" if residency_visa_required(res) else "W9"


def residency_disbursements(residency_id):
    return rows_of(store.disbursements, residency_id=residency_id)


def residency_obligations(residency_id):
    return rows_of(store.obligations, residency_id=residency_id)


def recompute_residency_stipend_ledgers(res):
    paid = [x for x in residency_disbursements(res["id"]) if x["status"] == "PAID"]
    res["stipend_paid_gross_cents"] = sum(int(x["gross_cents"]) for x in paid)
    res["withholding_to_date_cents"] = sum(int(x["withholding_cents"] or 0) for x in paid)


def recompute_obligation_counters(res):
    required = 0
    completed = 0
    breached = 0
    for ob in residency_obligations(res["id"]):
        if ob["status"] != "WAIVED":
            required += int(ob["required_count"])
            completed += int(ob["completed_count"])
        if ob["status"] == "BREACHED":
            breached += 1
    res["obligations_required_total"] = required
    res["obligations_completed_total"] = completed
    res["obligations_breached_count"] = breached


def derive_required_training_types(res):
    types = set(["SAFETY_ORIENTATION"])
    discipline = residency_discipline(res)
    if discipline is not None:
        for tag in discipline["required_capability_tags"]:
            types.add("EQUIPMENT_" + tag)
        if discipline["requires_hazmat_review"] and residency_hazmat(res):
            types.add("HAZMAT_HANDLING")
    return sorted(types)


def residency_weeks_planned(res):
    if res.get("session_length_weeks") is not None:
        return int(res["session_length_weeks"])
    app = source_application(res)
    if app is not None:
        return int(app["requested_session_length_weeks"])
    return 0


# ---------------------------------------------------------------- Facility ledgers
def studio_assignments_of(studio_id):
    return rows_of(store.studio_assignments, studio_id=studio_id)


def recompute_studio_ledger(studio):
    days = 0
    count = 0
    for sa in studio_assignments_of(studio["id"]):
        if sa["status"] == "ACTIVE":
            days += int(sa["occupied_days"])
            count += 1
    studio["reserved_resident_days"] = days
    studio["active_assignment_count"] = count


def recompute_housing_ledger(unit):
    nights = 0
    for ha in rows_of(store.housing_assignments, housing_unit_id=unit["id"]):
        if ha["status"] == "ACTIVE":
            nights += int(ha["bed_nights"])
    unit["occupied_bed_nights"] = nights


# ---------------------------------------------------------------- Visa timeline
def visa_timeline(case):
    """Re-derived on every read; never stored beyond backlog_days/case_type."""
    res = store.residencies.get(case["residency_id"])
    applicant = None
    if res is not None:
        applicant = store.applicants.get(res["applicant_id"])
    country = applicant["citizenship_country"] if applicant else None
    backlog = calc.backlog_days_for(country)
    start = d(res.get("session_start_date")) if res is not None else None
    if start is None:
        return backlog, None, None, None
    filing_deadline = start - timedelta(days=(K.VISA_LEAD_DAYS + backlog))
    earliest_entry = start - timedelta(days=K.VISA_EARLIEST_ENTRY_LEAD_DAYS)
    days_to = (filing_deadline - store.today()).days
    return backlog, filing_deadline, earliest_entry, days_to


# ---------------------------------------------------------------- serializers
def _num(value):
    """Render a stored Decimal as a JSON number (None-safe)."""
    if value is None:
        return None
    return float(value)


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_cycle(row):
    committed, uncommitted, filled, open_count = cycle_ledger(row)
    out = _common(row)
    out.update({
        "code": row["code"],
        "open_at": row["open_at"],
        "close_at": row["close_at"],
        "application_fee_cents": row["application_fee_cents"],
        "panel_quorum": row["panel_quorum"],
        "cohort_target_size": row["cohort_target_size"],
        "alumni_reserve_pct": _num(row["alumni_reserve_pct"]),
        "stipend_pool_cents": row["stipend_pool_cents"],
        "slate_min_score": _num(row["slate_min_score"]),
        "stipend_weekly_rate_cents": row["stipend_weekly_rate_cents"],
        "session_length_options_weeks": list(row["session_length_options_weeks"]),
        "status": row["status"],
        "stipend_committed_cents": committed,
        "stipend_uncommitted_cents": uncommitted,
        "slots_filled_count": filled,
        "slots_open_count": open_count,
        "slate_ready_count": cycle_slate_ready_count(row["id"]),
        "alumni_reserved_slots": row["alumni_reserved_slots"],
        "panel_review_complete": cycle_panel_review_complete(row["id"]),
    })
    return out


def ser_discipline(row):
    # Discipline exposes only id and created_at from the common block.
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "cycle_id": row["cycle_id"],
        "code": row["code"],
        "name": row["name"],
        "portfolio_min_items": row["portfolio_min_items"],
        "portfolio_max_items": row["portfolio_max_items"],
        "required_media_types": list(row["required_media_types"]),
        "requires_hazmat_review": row["requires_hazmat_review"],
        "cohort_min_slots": row["cohort_min_slots"],
        "cohort_max_slots": row["cohort_max_slots"],
        "required_capability_tags": list(row["required_capability_tags"]),
        "required_ventilation_class": row["required_ventilation_class"],
    }


def ser_applicant(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "email": row["email"],
        "affiliation_org": row["affiliation_org"],
        "citizenship_country": row["citizenship_country"],
        "treaty_country": row["treaty_country"],
        "declared_annual_income_cents": row["declared_annual_income_cents"],
        "is_international": applicant_is_international(row),
        "completed_residency_count": applicant_completed_residency_count(row["id"]),
    })
    return out


def ser_application(row):
    out = _common(row)
    out.update({
        "cycle_id": row["cycle_id"],
        "applicant_id": row["applicant_id"],
        "discipline_id": row["discipline_id"],
        "requested_session_length_weeks": row["requested_session_length_weeks"],
        "project_statement": row["project_statement"],
        "fee_waiver_requested": row["fee_waiver_requested"],
        "fee_status": row["fee_status"],
        "fee_waiver_reason": row["fee_waiver_reason"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "portfolio_item_count": len(application_portfolio_items(row["id"])),
        "portfolio_media_types": application_media_types(row["id"]),
        "hazardous_materials_declared": application_hazmat(row),
        "assigned_panelist_count": assigned_panelist_count(row["id"]),
        "scored_panelist_count": len(scored_totals(row["id"])),
        "provisional_screening_score": _num(row["provisional_screening_score"]),
        "final_panel_score": _num(row["final_panel_score"]),
        "rank_in_discipline": row["rank_in_discipline"],
        "waitlist_rank": row["waitlist_rank"],
    })
    return out


def ser_portfolio_item(row):
    # PortfolioItem exposes only id and created_at from the common block.
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "application_id": row["application_id"],
        "media_type": row["media_type"],
        "title": row["title"],
        "file_size_mb": _num(row["file_size_mb"]),
        "hazardous_materials_declared": row["hazardous_materials_declared"],
    }


def ser_panelist(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "email": row["email"],
        "affiliation_org": row["affiliation_org"],
        "discipline_expertise": list(row["discipline_expertise"]),
        "chair_eligible": row["chair_eligible"],
        "status": row["status"],
        "recused_cycle_id": row["recused_cycle_id"],
        "assigned_count": row["assigned_count"],
        "conflict_count": row["conflict_count"],
    })
    return out


def ser_panel_assignment(row):
    out = _common(row)
    out.update({
        "application_id": row["application_id"],
        "panelist_id": row["panelist_id"],
        "status": row["status"],
        "conflict_type": row["conflict_type"],
        "conflict_detail": row["conflict_detail"],
        "score_artistic_merit": row["score_artistic_merit"],
        "score_feasibility": row["score_feasibility"],
        "score_community_fit": row["score_community_fit"],
        "score_technical_readiness": row["score_technical_readiness"],
        "notes": row["notes"],
        "scored_at": row["scored_at"],
        "expertise_matched": row["expertise_matched"],
        "panelist_total_100": _num(row["panelist_total_100"]),
    })
    return out


def ser_residency(row):
    out = _common(row)
    out.update({
        "cycle_id": row["cycle_id"],
        "application_id": row["application_id"],
        "applicant_id": row["applicant_id"],
        "predecessor_residency_id": row["predecessor_residency_id"],
        "discipline_code": row["discipline_code"],
        "session_start_date": row["session_start_date"],
        "session_end_date": row["session_end_date"],
        "session_length_weeks": row["session_length_weeks"],
        "status": row["status"],
        "compliance_status": row["compliance_status"],
        "required_training_types": list(row["required_training_types"]),
        "completed_training_types": list(row["completed_training_types"]),
        "visa_required": residency_visa_required(row),
        "stipend_basis": row["stipend_basis"],
        "stipend_weekly_rate_cents": row["stipend_weekly_rate_cents"],
        "stipend_total_cents": row["stipend_total_cents"],
        "stipend_paid_gross_cents": row["stipend_paid_gross_cents"],
        "withholding_to_date_cents": row["withholding_to_date_cents"],
        "tax_form_type": residency_tax_form_type(row),
        "actual_weeks_in_residence": row["actual_weeks_in_residence"],
        "assigned_studio_code": row["assigned_studio_code"],
        "assigned_housing_unit_code": row["assigned_housing_unit_code"],
        "obligations_required_total": row["obligations_required_total"],
        "obligations_completed_total": row["obligations_completed_total"],
        "obligations_breached_count": row["obligations_breached_count"],
    })
    return out


def ser_studio(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "capability_tags": list(row["capability_tags"]),
        "ventilation_class": row["ventilation_class"],
        "max_concurrent_residents": row["max_concurrent_residents"],
        "status": row["status"],
        "reserved_resident_days": row["reserved_resident_days"],
        "active_assignment_count": row["active_assignment_count"],
    })
    return out


def ser_studio_assignment(row):
    out = _common(row)
    out.update({
        "studio_id": row["studio_id"],
        "residency_id": row["residency_id"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "occupied_days": row["occupied_days"],
        "status": row["status"],
        "selection_mode": row["selection_mode"],
        "released_reason": row["released_reason"],
    })
    return out


def ser_housing_unit(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "bed_count": row["bed_count"],
        "meal_plan_included": row["meal_plan_included"],
        "accessibility_features": list(row["accessibility_features"]),
        "status": row["status"],
        "occupied_bed_nights": row["occupied_bed_nights"],
    })
    return out


def ser_housing_assignment(row):
    out = _common(row)
    out.update({
        "housing_unit_id": row["housing_unit_id"],
        "residency_id": row["residency_id"],
        "check_in_date": row["check_in_date"],
        "check_out_date": row["check_out_date"],
        "meal_plan_selected": row["meal_plan_selected"],
        "bed_nights": row["bed_nights"],
        "status": row["status"],
        "released_reason": row["released_reason"],
    })
    return out


def ser_visa_case(row):
    backlog, filing_deadline, earliest_entry, days_to = visa_timeline(row)
    out = _common(row)
    out.update({
        "residency_id": row["residency_id"],
        "case_type": row["case_type"],
        "status": row["status"],
        "requested_doc_list": list(row["requested_doc_list"]),
        "submitted_doc_list": list(row["submitted_doc_list"]),
        "consulate_appointment_date": row["consulate_appointment_date"],
        "rfe_round": row["rfe_round"],
        "backlog_days": backlog,
        "filing_deadline_date": ds(filing_deadline),
        "earliest_entry_date": ds(earliest_entry),
        "days_to_filing_deadline": days_to,
    })
    return out


def ser_disbursement(row):
    out = _common(row)
    out.update({
        "residency_id": row["residency_id"],
        "period_index": row["period_index"],
        "period_start_date": row["period_start_date"],
        "period_end_date": row["period_end_date"],
        "weeks_in_period": row["weeks_in_period"],
        "gross_cents": row["gross_cents"],
        "withholding_cents": row["withholding_cents"],
        "net_cents": row["net_cents"],
        "withholding_rate": _num(row["withholding_rate"]),
        "cumulative_taxable_cents": row["cumulative_taxable_cents"],
        "tax_form_type": row["tax_form_type"],
        "status": row["status"],
        "paid_on_date": row["paid_on_date"],
        "scheduled_by_user_id": row["scheduled_by_user_id"],
        "paid_by_user_id": row["paid_by_user_id"],
    })
    return out


def ser_obligation(row):
    out = _common(row)
    out.update({
        "residency_id": row["residency_id"],
        "obligation_type": row["obligation_type"],
        "required_count": row["required_count"],
        "completed_count": row["completed_count"],
        "total_attendance": row["total_attendance"],
        "due_date": row["due_date"],
        "status": row["status"],
        "waived_reason": row["waived_reason"],
    })
    return out


# ---------------------------------------------------------------- creation helpers
def new_residency(cycle_id, applicant_id, discipline_code, application_id=None,
                  predecessor_residency_id=None, weekly_rate_cents=0,
                  stipend_total_cents=0):
    return create_row(store.residencies, {
        "cycle_id": cycle_id,
        "application_id": application_id,
        "applicant_id": applicant_id,
        "predecessor_residency_id": predecessor_residency_id,
        "discipline_code": discipline_code,
        "session_start_date": None,
        "session_end_date": None,
        "session_length_weeks": None,
        "status": "SCHEDULED",
        "compliance_status": "TRAINING_PENDING",
        "required_training_types": [],
        "completed_training_types": [],
        "stipend_basis": "PROVISIONAL",
        "stipend_weekly_rate_cents": int(weekly_rate_cents),
        "stipend_total_cents": int(stipend_total_cents),
        "stipend_paid_gross_cents": 0,
        "withholding_to_date_cents": 0,
        "actual_weeks_in_residence": None,
        "assigned_studio_code": None,
        "assigned_housing_unit_code": None,
        "obligations_required_total": 0,
        "obligations_completed_total": 0,
        "obligations_breached_count": 0,
    })


def new_visa_case(residency_id):
    return create_row(store.visa_cases, {
        "residency_id": residency_id,
        "case_type": "B1_SHORT_TERM",
        "status": "INITIATED",
        "requested_doc_list": [],
        "submitted_doc_list": [],
        "consulate_appointment_date": None,
        "rfe_round": 0,
    })


def provision_obligations(res):
    """Provision or re-derive the engagement obligations from the session length."""
    weeks = int(res["session_length_weeks"])
    due = res["session_end_date"]
    existing = residency_obligations(res["id"])
    for obligation_type, required_count in calc.obligation_plan(weeks):
        rows = [o for o in existing if o["obligation_type"] == obligation_type]
        pending = [o for o in rows if o["status"] == "PENDING"]
        if pending:
            for row in pending:
                row["required_count"] = required_count
                row["due_date"] = due
                touch(row)
        elif not rows:
            create_row(store.obligations, {
                "residency_id": res["id"],
                "obligation_type": obligation_type,
                "required_count": required_count,
                "completed_count": 0,
                "total_attendance": 0,
                "due_date": due,
                "status": "PENDING",
                "waived_reason": None,
            })
    recompute_obligation_counters(res)


def release_studio_assignments(res, reason, clear_code):
    """Move every ACTIVE studio assignment of the residency to RELEASED."""
    for sa in rows_of(store.studio_assignments, residency_id=res["id"]):
        if sa["status"] != "ACTIVE":
            continue
        sa["status"] = "RELEASED"
        sa["released_reason"] = reason
        touch(sa)
        studio = store.studios.get(sa["studio_id"])
        if studio is not None:
            recompute_studio_ledger(studio)
            touch(studio)
    if clear_code:
        res["assigned_studio_code"] = None


def release_housing_assignments(res, reason, clear_code):
    for ha in rows_of(store.housing_assignments, residency_id=res["id"]):
        if ha["status"] != "ACTIVE":
            continue
        ha["status"] = "RELEASED"
        ha["released_reason"] = reason
        touch(ha)
        unit = store.housing_units.get(ha["housing_unit_id"])
        if unit is not None:
            recompute_housing_ledger(unit)
            touch(unit)
    if clear_code:
        res["assigned_housing_unit_code"] = None


def void_scheduled_disbursements(res):
    for row in residency_disbursements(res["id"]):
        if row["status"] != "SCHEDULED":
            continue
        row["status"] = "VOIDED"
        row["withholding_cents"] = 0
        row["net_cents"] = 0
        touch(row)


def deny_visa_case_on_withdrawal(residency_id):
    case = visa_case_of(residency_id)
    if case is None:
        return
    if case["status"] in ("APPROVED", "DENIED"):
        return
    case["status"] = "DENIED"
    touch(case)


def merit_order(apps):
    """final_panel_score DESC, then created_at ASC."""
    return sorted(apps, key=lambda a: (-a["final_panel_score"], a["_seq"]))


def rerank_waitlist(cycle_id):
    waitlisted = [a for a in cycle_applications(cycle_id) if a["status"] == "WAITLISTED"
                  and a.get("final_panel_score") is not None]
    for index, app in enumerate(merit_order(waitlisted), start=1):
        app["waitlist_rank"] = index
