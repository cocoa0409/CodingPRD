"""DSH/UCC compilation, settlement stages, audit adjustments, appeals and
interim rate resets (PRD 3.7, 3.8 and 3.9)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import errors
import services.calc as calc
from common import (READ_ROLES, READ_ROLES_WITH_BOARD, body, check_scope, current_user_id, endpoint,
                    find, ok_list_of, pagination, public, reference, require_editable)
from db import (adjustments_of, apply_changes, completed_run, db, iso, new_row, ordered,
                settlements_of, touch, ucc_of)
from response import ok
from validators import query_enum, query_string

bp = Blueprint("settlement", __name__)

STAGES = ("TENTATIVE", "FINAL")
SETTLEMENT_STATUSES = ("ISSUED", "APPEALED", "SUPERSEDED", "RESETTLED")
ADJUSTMENT_STATUSES = ("PROPOSED", "ACCEPTED_BY_PROVIDER", "PROTESTED", "INCORPORATED",
                       "WITHDRAWN")
UNRESOLVED_STATUSES = ("PROPOSED", "ACCEPTED_BY_PROVIDER", "PROTESTED")
RESPONSES = ("ACCEPT", "PROTEST")
OUTCOMES = ("INCORPORATE", "WITHDRAW")
APPEAL_KINDS = ("REOPENING", "PRRB_APPEAL")
APPEAL_STATUSES = ("REQUESTED", "GRANTED", "DENIED", "HEARD", "DECIDED_FOR_PROVIDER",
                   "DECIDED_FOR_CONTRACTOR")
CONTRACTOR_OUTCOMES = ("GRANT", "DENY")
BOARD_OUTCOMES = ("HEAR", "DECIDE_FOR_PROVIDER", "DECIDE_FOR_CONTRACTOR")
APPEAL_OUTCOMES = CONTRACTOR_OUTCOMES + BOARD_OUTCOMES
REQUEST_STATUSES = ("PENDING", "APPROVED", "DENIED", "SUPERSEDED")
DECISIONS = ("APPROVE", "DENY")
SUPERSEDE_NOTE = "SUPERSEDED_BY_NEWER_REQUEST"


def _report_of_settlement(settlement):
    return db.cost_reports[settlement["cost_report_id"]]


def _issued_date(settlement):
    return calc.as_date(settlement["issued_at"][:10])


def _reopening_cascade(report, settlement):
    """The four-link reopening cascade of PRD 2.7."""
    apply_changes(settlement, {"status": "RESETTLED"})
    report["status"] = "REOPENED"
    calc.invalidate_allocation(report, calc.STALE_COST_CENTER)
    touch(report)


# ------------------------------------------------------------------ UccDataSet
@bp.post("/cost-reports/<report_id>/ucc-data-sets")
@endpoint(roles=["ReimbursementAnalyst"])
def create_ucc_data_set(report_id):
    payload = body()
    medicaid_days = payload.integer("medicaid_non_medicare_days", minimum=0)
    total_days = payload.integer("total_inpatient_days", minimum=1)
    ssi_days = payload.integer("ssi_days", minimum=0)
    part_a_days = payload.integer("medicare_part_a_days", minimum=1)
    charity = payload.integer("charity_care_charges_cents", minimum=0)
    bad_debt = payload.integer("non_medicare_bad_debt_cents", required=False, default=0, minimum=0)

    report = find("CostReport", report_id)
    check_scope(report["provider_id"])
    require_editable(report)
    if ucc_of(report["id"]):
        raise errors.business("ERR_DUPLICATE_CHILD_RECORD",
                             "This cost report already carries an uncompensated care data set.")

    data_set = new_row(
        cost_report_id=report["id"],
        medicaid_non_medicare_days=medicaid_days,
        total_inpatient_days=total_days,
        ssi_days=ssi_days,
        medicare_part_a_days=part_a_days,
        charity_care_charges_cents=charity,
        non_medicare_bad_debt_cents=bad_debt,
        medicaid_fraction=Decimal("0.0000"),
        ssi_fraction=Decimal("0.0000"),
        dsh_patient_percentage=Decimal("0.0000"),
        dsh_eligible=False,
        cost_to_charge_ratio=Decimal("0.000000"),
        uncompensated_care_cost_cents=0,
        ucc_payment_cents=0,
        recompute_required=False,
    )
    db.ucc_data_sets[data_set["id"]] = data_set

    calc.compile_ucc(report, data_set)
    data_set["version"] = 1
    data_set["updated_at"] = data_set["created_at"]
    return ok(public(data_set), 201)


@bp.get("/ucc-data-sets/<data_set_id>")
@endpoint(roles=list(READ_ROLES))
def read_ucc_data_set(data_set_id):
    return ok(public(find("UccDataSet", data_set_id)))


@bp.get("/cost-reports/<report_id>/ucc-data-sets")
@endpoint(roles=list(READ_ROLES))
def list_ucc_data_sets(report_id):
    limit, offset = pagination()
    report = find("CostReport", report_id)
    return ok_list_of(ucc_of(report["id"]), limit, offset)


@bp.post("/ucc-data-sets/<data_set_id>/recompute")
@endpoint(roles=["ReimbursementAnalyst", "MacAuditor"])
def recompute_ucc_data_set(data_set_id):
    data_set = find("UccDataSet", data_set_id)
    report = db.cost_reports[data_set["cost_report_id"]]
    check_scope(report["provider_id"])
    calc.compile_ucc(report, data_set)
    return ok(public(data_set))


# ------------------------------------------------------------------ Settlement
@bp.post("/cost-reports/<report_id>/settlements")
@endpoint(roles=["MacAuditor"])
def create_settlement(report_id):
    payload = body()
    stage = payload.enum("stage", STAGES)

    report = find("CostReport", report_id)
    existing = settlements_of(report["id"])
    issued_tentative = [s for s in existing
                        if s["stage"] == "TENTATIVE" and s["status"] == "ISSUED"]

    if stage == "TENTATIVE":
        if report["status"] != "FILED":
            raise errors.invalid_state(
                "A tentative settlement is only reachable from FILED, not %s." % report["status"])
        if issued_tentative:
            raise errors.invalid_state(
                "An ISSUED tentative settlement already exists for this report.")
    else:
        if report["status"] not in ("TENTATIVE_SETTLED", "AMENDED_FILED"):
            raise errors.invalid_state(
                "A final settlement is not reachable from %s." % report["status"])
        if report["status"] == "TENTATIVE_SETTLED" and not issued_tentative:
            raise errors.invalid_state(
                "The report has no ISSUED tentative settlement to settle against.")

    if report["allocation_status"] != "CURRENT":
        raise errors.business("ERR_ALLOCATION_NOT_CURRENT",
                             "The overhead allocation is not current.")
    basis_run = completed_run(report["id"])
    if basis_run is None:
        raise errors.business("ERR_ALLOCATION_NOT_CURRENT",
                             "The report has no COMPLETED stepdown run to settle from.")
    if stage == "FINAL":
        if basis_run["method"] != "DOUBLE_APPORTIONMENT":
            raise errors.business(
                "ERR_FINAL_REQUIRES_DOUBLE_APPORTIONMENT",
                "A final settlement requires a DOUBLE_APPORTIONMENT basis run.")
        if report["status"] == "TENTATIVE_SETTLED":
            for prior in existing:
                if prior["stage"] != "TENTATIVE":
                    continue
                for adjustment in adjustments_of(prior["id"]):
                    if adjustment["status"] in UNRESOLVED_STATUSES:
                        raise errors.business(
                            "ERR_AUDIT_ADJUSTMENT_UNRESOLVED",
                            "An audit adjustment of the tentative settlement is unresolved.")

    figures = calc.compute_settlement(report, stage, basis_run)
    settlement = new_row(
        cost_report_id=report["id"],
        stage=stage,
        status="ISSUED",
        recompute_required=False,
        issued_at=iso(db.clock),
        **figures)
    db.settlements[settlement["id"]] = settlement

    if stage == "TENTATIVE":
        report["status"] = "TENTATIVE_SETTLED"
    else:
        report["status"] = "FINAL_SETTLED"
        report["allowable_cost_per_discharge_cents"] = calc.allowable_cost_per_discharge(report)
    touch(report)
    return ok(public(settlement), 201)


@bp.get("/settlements/<settlement_id>")
@endpoint(roles=list(READ_ROLES_WITH_BOARD))
def read_settlement(settlement_id):
    return ok(public(find("Settlement", settlement_id)))


@bp.get("/cost-reports/<report_id>/settlements")
@endpoint(roles=list(READ_ROLES_WITH_BOARD))
def list_settlements(report_id):
    limit, offset = pagination()
    stage = query_enum(request.args, "stage", STAGES)
    status = query_enum(request.args, "status", SETTLEMENT_STATUSES)
    report = find("CostReport", report_id)
    rows = settlements_of(report["id"])
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list_of(rows, limit, offset)


# -------------------------------------------------------------- AuditAdjustment
@bp.post("/settlements/<settlement_id>/audit-adjustments")
@endpoint(roles=["MacAuditor"])
def create_audit_adjustment(settlement_id):
    payload = body()
    target_cost_center_id = payload.string("target_cost_center_id")
    code = payload.string("code")
    rationale = payload.string("rationale")
    proposed_amount = payload.integer("proposed_amount_cents", nonzero=True)
    user_id = current_user_id()
    if user_id is None:
        raise errors.invalid_request(
            "X-User-ID is required so the proposing auditor can be recorded.")

    settlement = find("Settlement", settlement_id)
    center = reference("CostCenter", target_cost_center_id)
    if settlement["status"] not in ("ISSUED", "APPEALED"):
        raise errors.invalid_state(
            "A settlement in %s accepts no audit adjustments." % settlement["status"])
    if center["cost_report_id"] != settlement["cost_report_id"]:
        raise errors.business("ERR_COST_CENTER_FOREIGN_TO_REPORT",
                             "That cost center belongs to a different cost report.")

    adjustment = new_row(
        settlement_id=settlement["id"],
        target_cost_center_id=center["id"],
        code=code,
        rationale=rationale,
        proposed_amount_cents=proposed_amount,
        status="PROPOSED",
        proposed_by_user_id=user_id,
        resolved_by_user_id=None,
        provider_response_note=None,
    )
    db.audit_adjustments[adjustment["id"]] = adjustment
    touch(settlement)
    return ok(public(adjustment), 201)


@bp.get("/audit-adjustments/<adjustment_id>")
@endpoint(roles=list(READ_ROLES))
def read_audit_adjustment(adjustment_id):
    return ok(public(find("AuditAdjustment", adjustment_id)))


@bp.get("/audit-adjustments")
@endpoint(roles=list(READ_ROLES))
def list_audit_adjustments():
    limit, offset = pagination()
    settlement_id = query_string(request.args, "settlement_id")
    target_cost_center_id = query_string(request.args, "target_cost_center_id")
    status = query_enum(request.args, "status", ADJUSTMENT_STATUSES)
    rows = ordered(list(db.audit_adjustments.values()))
    if settlement_id is not None:
        rows = [r for r in rows if r["settlement_id"] == settlement_id]
    if target_cost_center_id is not None:
        rows = [r for r in rows if r["target_cost_center_id"] == target_cost_center_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list_of(rows, limit, offset)


@bp.post("/audit-adjustments/<adjustment_id>/respond")
@endpoint(roles=["ReimbursementManager"])
def respond_audit_adjustment(adjustment_id):
    payload = body()
    response = payload.enum("response", RESPONSES)
    note = payload.string("provider_response_note")

    adjustment = find("AuditAdjustment", adjustment_id)
    settlement = db.settlements[adjustment["settlement_id"]]
    report = _report_of_settlement(settlement)
    check_scope(report["provider_id"])

    if adjustment["status"] != "PROPOSED":
        raise errors.invalid_state(
            "An adjustment in %s has no provider response to record." % adjustment["status"])
    if settlement["status"] not in ("ISSUED", "APPEALED"):
        raise errors.invalid_state(
            "The parent settlement is in %s." % settlement["status"])
    if response == "ACCEPT" and report["status"] != "TENTATIVE_SETTLED":
        raise errors.invalid_state(
            "An adjustment may only be accepted while the report is TENTATIVE_SETTLED.")

    adjustment["provider_response_note"] = note
    adjustment["status"] = "ACCEPTED_BY_PROVIDER" if response == "ACCEPT" else "PROTESTED"
    touch(adjustment)

    if response == "PROTEST":
        settlement["status"] = "APPEALED"
    touch(settlement)
    return ok(public(adjustment))


@bp.post("/audit-adjustments/<adjustment_id>/resolve")
@endpoint(roles=["MacAuditor"])
def resolve_audit_adjustment(adjustment_id):
    payload = body()
    outcome = payload.enum("outcome", OUTCOMES)
    payload.string("resolution_note", required=False, default=None)
    user_id = current_user_id()
    if user_id is None:
        raise errors.invalid_request(
            "X-User-ID is required so the resolving auditor can be recorded.")

    adjustment = find("AuditAdjustment", adjustment_id)
    if user_id == adjustment["proposed_by_user_id"]:
        raise errors.segregation_of_duties()
    if adjustment["status"] not in ("ACCEPTED_BY_PROVIDER", "PROTESTED"):
        raise errors.invalid_state(
            "An adjustment in %s may not be resolved." % adjustment["status"])

    settlement = db.settlements[adjustment["settlement_id"]]
    report = _report_of_settlement(settlement)
    from_protested = adjustment["status"] == "PROTESTED"

    adjustment["status"] = "INCORPORATED" if outcome == "INCORPORATE" else "WITHDRAWN"
    adjustment["resolved_by_user_id"] = user_id
    touch(adjustment)

    if outcome == "INCORPORATE":
        entry = new_row(
            cost_report_id=report["id"],
            entry_type="ADJUSTMENT",
            code=adjustment["code"],
            description=adjustment["rationale"],
            legs=[{"cost_center_id": adjustment["target_cost_center_id"],
                   "amount_cents": adjustment["proposed_amount_cents"]}],
            source="AUDIT",
            is_non_allowable=False,
            status="ACTIVE",
            source_audit_adjustment_id=adjustment["id"],
            reversed_at=None,
        )
        db.workpaper_entries[entry["id"]] = entry

        calc.rollup(report)
        calc.invalidate_allocation(report, calc.STALE_WORKPAPER)
        for other in settlements_of(report["id"]):
            if other["status"] in ("ISSUED", "APPEALED"):
                changes = {"recompute_required": True}
                if from_protested and other["id"] == settlement["id"]:
                    changes["status"] = "ISSUED"
                apply_changes(other, changes)
            elif from_protested and other["id"] == settlement["id"]:
                apply_changes(other, {"status": "ISSUED"})
        touch(report)
    elif from_protested:
        apply_changes(settlement, {"status": "ISSUED"})

    return ok(public(adjustment))


# ------------------------------------------------------------------ AppealCase
@bp.post("/cost-reports/<report_id>/appeal-cases")
@endpoint(roles=["ReimbursementManager"])
def create_appeal_case(report_id):
    payload = body()
    settlement_id = payload.string("settlement_id")
    kind = payload.enum("kind", APPEAL_KINDS)
    issue_description = payload.string("issue_description")
    amount_at_issue = payload.integer("amount_at_issue_cents", minimum=1)

    report = find("CostReport", report_id)
    settlement = reference("Settlement", settlement_id)
    check_scope(report["provider_id"])

    if kind == "PRRB_APPEAL":
        deadline = _issued_date(settlement) + timedelta(days=calc.PRRB_APPEAL_WINDOW_DAYS)
        if calc.clock_date() > deadline:
            raise errors.business("ERR_APPEAL_WINDOW_EXPIRED",
                                 "The 180-day board appeal window has closed.")
    if settlement["cost_report_id"] != report["id"]:
        raise errors.business("ERR_SETTLEMENT_FOREIGN_TO_REPORT",
                             "That settlement belongs to a different cost report.")
    if settlement["stage"] != "FINAL":
        raise errors.business("ERR_SETTLEMENT_STAGE_INVALID",
                             "Only a FINAL settlement may be disputed.")
    if kind == "PRRB_APPEAL" and amount_at_issue < calc.PRRB_MINIMUM_AMOUNT_CENTS:
        raise errors.business("ERR_PRRB_AMOUNT_BELOW_MINIMUM",
                             "A board appeal requires at least 1000000 cents at issue.")

    case = new_row(
        cost_report_id=report["id"],
        settlement_id=settlement["id"],
        kind=kind,
        issue_description=issue_description,
        amount_at_issue_cents=amount_at_issue,
        status="REQUESTED",
        decided_at=None,
        decision_note=None,
    )
    db.appeal_cases[case["id"]] = case
    return ok(public(case), 201)


@bp.get("/appeal-cases/<case_id>")
@endpoint(roles=list(READ_ROLES_WITH_BOARD))
def read_appeal_case(case_id):
    return ok(public(find("AppealCase", case_id)))


@bp.get("/appeal-cases")
@endpoint(roles=list(READ_ROLES_WITH_BOARD))
def list_appeal_cases():
    limit, offset = pagination()
    cost_report_id = query_string(request.args, "cost_report_id")
    settlement_id = query_string(request.args, "settlement_id")
    kind = query_enum(request.args, "kind", APPEAL_KINDS)
    status = query_enum(request.args, "status", APPEAL_STATUSES)
    rows = ordered(list(db.appeal_cases.values()))
    if cost_report_id is not None:
        rows = [r for r in rows if r["cost_report_id"] == cost_report_id]
    if settlement_id is not None:
        rows = [r for r in rows if r["settlement_id"] == settlement_id]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list_of(rows, limit, offset)


@bp.post("/appeal-cases/<case_id>/decide")
@endpoint(roles=["MacAuditor", "ReviewBoardClerk"])
def decide_appeal_case(case_id):
    payload = body()
    outcome = payload.enum("outcome", APPEAL_OUTCOMES)
    decision_note = payload.string("decision_note")

    case = find("AppealCase", case_id)
    role = request.headers.get("X-User-Role")
    allowed = CONTRACTOR_OUTCOMES if role == "MacAuditor" else BOARD_OUTCOMES
    if outcome not in allowed:
        raise errors.forbidden_role("The %s role may not record a %s outcome." % (role, outcome))

    settlement = db.settlements[case["settlement_id"]]
    report = db.cost_reports[case["cost_report_id"]]

    if outcome in CONTRACTOR_OUTCOMES:
        if case["kind"] != "REOPENING":
            raise errors.invalid_state("%s applies only to a REOPENING case." % outcome)
        if case["status"] != "REQUESTED":
            raise errors.invalid_state(
                "A case in %s may not be %sed." % (case["status"], outcome.lower()))
        if outcome == "GRANT":
            if settlement["stage"] != "FINAL" or settlement["status"] not in ("ISSUED", "APPEALED"):
                raise errors.invalid_state(
                    "The referenced settlement cannot be reopened from %s." % settlement["status"])
            if calc.clock_date() > calc.add_years(_issued_date(settlement),
                                                  calc.REOPENING_WINDOW_YEARS):
                raise errors.business("ERR_REOPENING_WINDOW_EXPIRED",
                                     "The three-year reopening window has closed.")
    else:
        if case["kind"] != "PRRB_APPEAL":
            raise errors.invalid_state("%s applies only to a PRRB_APPEAL case." % outcome)
        if outcome == "HEAR":
            if case["status"] != "REQUESTED":
                raise errors.invalid_state(
                    "A case in %s may not be heard." % case["status"])
            if settlement["status"] != "APPEALED":
                raise errors.invalid_state(
                    "The referenced settlement is not APPEALED.")
        elif case["status"] != "HEARD":
            raise errors.invalid_state(
                "A board decision is only available from HEARD, not %s." % case["status"])

    case["decision_note"] = decision_note
    if outcome == "HEAR":
        case["status"] = "HEARD"
    else:
        case["decided_at"] = iso(db.clock)
        case["status"] = {
            "GRANT": "GRANTED",
            "DENY": "DENIED",
            "DECIDE_FOR_PROVIDER": "DECIDED_FOR_PROVIDER",
            "DECIDE_FOR_CONTRACTOR": "DECIDED_FOR_CONTRACTOR",
        }[outcome]
    touch(case)

    if outcome in ("GRANT", "DECIDE_FOR_PROVIDER"):
        _reopening_cascade(report, settlement)
    elif outcome == "DECIDE_FOR_CONTRACTOR":
        apply_changes(settlement, {"status": "ISSUED"})
        report["status"] = "CLOSED"
        touch(report)
    return ok(public(case))


# ----------------------------------------------------------- InterimRateRequest
@bp.post("/interim-rate-requests")
@endpoint(roles=["ReimbursementManager"])
def create_interim_rate_request():
    payload = body()
    provider_id = payload.string("provider_id")
    expected_version = payload.integer("expected_provider_version")
    basis_cost_report_id = payload.string("basis_cost_report_id")
    projected_discharges = payload.integer("projected_discharges", minimum=1)
    trend_factor = payload.number("trend_factor", places=4, minimum=0, maximum=Decimal("0.5"))
    effective_from = payload.date("effective_from")
    effective_to = payload.date("effective_to")
    if effective_to <= effective_from:
        raise errors.invalid_request("effective_to must be later than effective_from.")

    provider = reference("Provider", provider_id)
    basis_report = reference("CostReport", basis_cost_report_id)
    check_scope(provider["id"])
    if expected_version != provider["version"]:
        raise errors.stale_provider_version()

    if basis_report["provider_id"] != provider["id"]:
        raise errors.business("ERR_BASIS_REPORT_FOREIGN_TO_PROVIDER",
                             "That basis cost report belongs to a different provider.")
    if calc.interim_period_conflict(provider["id"], effective_from, effective_to):
        raise errors.business(
            "ERR_INTERIM_PERIOD_OVERLAP",
            "The requested period comes within 30 days of an outstanding request.",
            status=409)
    if basis_report["status"] != "FINAL_SETTLED":
        raise errors.business("ERR_BASIS_REPORT_NOT_FINAL_SETTLED",
                             "The basis cost report is not FINAL_SETTLED.")
    if provider["current_interim_rate_cents"] <= 0:
        raise errors.business("ERR_NO_CURRENT_INTERIM_RATE",
                             "The provider has no current interim rate to measure against.")

    projection, variance, approved, adjustment = calc.project_interim_rate(
        provider, basis_report, trend_factor, projected_discharges)
    if variance < calc.INTERIM_VARIANCE_THRESHOLD:
        raise errors.business("ERR_INTERIM_VARIANCE_BELOW_THRESHOLD",
                             "The projected variance is below the ten percent threshold.")

    for other in db.interim_rate_requests.values():
        if other["provider_id"] == provider["id"] and other["status"] == "PENDING":
            other["status"] = "SUPERSEDED"
            other["decision_note"] = SUPERSEDE_NOTE
            touch(other)

    row = new_row(
        provider_id=provider["id"],
        basis_cost_report_id=basis_report["id"],
        projected_discharges=projected_discharges,
        trend_factor=trend_factor,
        effective_from=effective_from.isoformat(),
        effective_to=effective_to.isoformat(),
        status="PENDING",
        projected_cost_per_discharge_cents=projection,
        variance_ratio=variance,
        approved_rate_cents=approved,
        adjustment_amount_cents=adjustment,
        decision_note=None,
    )
    db.interim_rate_requests[row["id"]] = row
    touch(provider)
    return ok(public(row), 201)


@bp.get("/interim-rate-requests/<request_id>")
@endpoint(roles=list(READ_ROLES))
def read_interim_rate_request(request_id):
    return ok(public(find("InterimRateRequest", request_id)))


@bp.get("/interim-rate-requests")
@endpoint(roles=list(READ_ROLES))
def list_interim_rate_requests():
    limit, offset = pagination()
    provider_id = query_string(request.args, "provider_id")
    basis_cost_report_id = query_string(request.args, "basis_cost_report_id")
    status = query_enum(request.args, "status", REQUEST_STATUSES)
    rows = ordered(list(db.interim_rate_requests.values()))
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if basis_cost_report_id is not None:
        rows = [r for r in rows if r["basis_cost_report_id"] == basis_cost_report_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list_of(rows, limit, offset)


@bp.post("/interim-rate-requests/<request_id>/decide")
@endpoint(roles=["MacAuditor"])
def decide_interim_rate_request(request_id):
    payload = body()
    decision = payload.enum("decision", DECISIONS)
    decision_note = payload.string("decision_note")

    row = find("InterimRateRequest", request_id)
    if row["status"] != "PENDING":
        raise errors.invalid_state(
            "A request in %s may not be decided." % row["status"])
    basis_report = db.cost_reports[row["basis_cost_report_id"]]
    if decision == "APPROVE" and basis_report["status"] != "FINAL_SETTLED":
        raise errors.business("ERR_BASIS_REPORT_NOT_FINAL_SETTLED",
                             "The basis cost report is no longer FINAL_SETTLED.")

    row["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    row["decision_note"] = decision_note
    touch(row)

    if decision == "APPROVE":
        provider = db.providers[row["provider_id"]]
        provider["current_interim_rate_cents"] = row["approved_rate_cents"]
        provider["approved_interim_period_count"] = provider["approved_interim_period_count"] + 1
        touch(provider)
    return ok(public(row))
