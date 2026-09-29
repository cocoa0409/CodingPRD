"""Read endpoints — PRD section 4 (16 reads, including the dossier)."""

from decimal import Decimal

from flask import Blueprint

import enums
import services
from auth import ALL_ROLES, authenticate
from calc import rhu
from db import (FUNDS, LETTERS, ORGANIZATIONS, PROGRAMS, RESTRUCTURINGS, TASKS,
                by_created, serialize)
from response import ok, ok_list, ok_row, paginate
from validate import pagination, query_enum, query_str

bp = Blueprint("read", __name__)


@bp.get("/organizations/<org_id>")
def get_organization(org_id):
    authenticate(ALL_ROLES)
    org = services.find_org(org_id)
    return ok_row(org)


@bp.get("/organizations")
def list_organizations():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    parent_org_id = query_str("parent_org_id")
    affiliation_role = query_enum("affiliation_role", enums.AFFILIATION_ROLES)
    state_code = query_str("state_code")
    rows = by_created(list(ORGANIZATIONS.values()))
    if parent_org_id is not None:
        rows = [r for r in rows if r["parent_org_id"] == parent_org_id]
    if affiliation_role is not None:
        rows = [r for r in rows if r["affiliation_role"] == affiliation_role]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/organizations/<org_id>/programs")
def list_org_programs(org_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "BoardSecretary",
                  "DiligenceLead", "IntegrationManager"])
    limit, offset = pagination()
    service_category = query_enum("service_category", enums.SERVICE_CATEGORIES)
    continuity_status = query_enum("continuity_status", enums.CONTINUITY_STATUSES)
    # PRD 2.9: resolve the organization first.
    services.find_org(org_id)
    rows = [p for p in PROGRAMS.values()
            if p["org_id"] == org_id or p["transferred_to_org_id"] == org_id]
    rows = by_created(rows)
    if service_category is not None:
        rows = [r for r in rows if r["service_category"] == service_category]
    if continuity_status is not None:
        rows = [r for r in rows if r["continuity_status"] == continuity_status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>")
def get_restructuring(deal_id):
    authenticate(ALL_ROLES)
    deal = services.find_deal(deal_id)
    return ok_row(deal)


@bp.get("/restructurings")
def list_restructurings():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    initiator_org_id = query_str("initiator_org_id")
    target_org_id = query_str("target_org_id")
    status = query_enum("status", enums.DEAL_STATUSES)
    structure_type = query_enum("structure_type", enums.STRUCTURE_TYPES)
    rows = by_created(list(RESTRUCTURINGS.values()))
    if initiator_org_id is not None:
        rows = [r for r in rows if r["initiator_org_id"] == initiator_org_id]
    if target_org_id is not None:
        rows = [r for r in rows if r["target_org_id"] == target_org_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if structure_type is not None:
        rows = [r for r in rows if r["structure_type"] == structure_type]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>/alignment-assessments")
def list_assessments(deal_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "BoardSecretary", "DiligenceLead"])
    limit, offset = pagination()
    variant = query_enum("variant", enums.ASSESSMENT_VARIANTS)
    services.find_deal(deal_id)
    rows = services.deal_assessments(deal_id)
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    rows = sorted(rows, key=lambda a: (a["sequence_no"], a["created_at"], a["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>/letters-of-intent")
def list_letters(deal_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "BoardSecretary"])
    limit, offset = pagination()
    status = query_enum("status", enums.LETTER_STATUSES)
    exclusivity_status = query_enum("exclusivity_status", enums.EXCLUSIVITY_STATUSES)
    services.find_deal(deal_id)
    rows = services.deal_letters(deal_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if exclusivity_status is not None:
        rows = [r for r in rows if r["exclusivity_status"] == exclusivity_status]
    rows = sorted(rows, key=lambda l: (l["round_no"], l["created_at"], l["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>/diligence-requests")
def list_findings(deal_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "DiligenceLead",
                  "CharitableTrustCounsel"])
    limit, offset = pagination()
    workstream = query_enum("workstream", enums.WORKSTREAMS)
    severity = query_enum("severity", enums.SEVERITIES)
    status = query_enum("status", enums.DILIGENCE_STATUSES)
    services.find_deal(deal_id)
    rows = services.deal_findings(deal_id)
    if workstream is not None:
        rows = [r for r in rows if r["workstream"] == workstream]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(by_created(rows), limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>/board-approvals")
def list_approvals(deal_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "BoardSecretary"])
    limit, offset = pagination()
    approving_party = query_enum("approving_party", enums.PARTIES)
    status = query_enum("status", enums.APPROVAL_STATUSES)
    services.find_deal(deal_id)
    rows = services.deal_approvals(deal_id)
    if approving_party is not None:
        rows = [r for r in rows if r["approving_party"] == approving_party]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(by_created(rows), limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>/ag-filings")
def list_filings(deal_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "CharitableTrustCounsel",
                  "StateCharitiesRegulator"])
    limit, offset = pagination()
    status = query_enum("status", enums.FILING_STATUSES)
    filing_type = query_enum("filing_type", enums.FILING_TYPES)
    services.find_deal(deal_id)
    rows = services.deal_filings(deal_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if filing_type is not None:
        rows = [r for r in rows if r["filing_type"] == filing_type]
    page, total = paginate(by_created(rows), limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>/restricted-funds")
def list_deal_funds(deal_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "CharitableTrustCounsel",
                  "StateCharitiesRegulator"])
    limit, offset = pagination()
    transfer_status = query_enum("transfer_status", enums.FUND_STATUSES)
    fund_type = query_enum("fund_type", enums.FUND_TYPES)
    deal = services.find_deal(deal_id)
    rows = services.party_funds(deal)
    if transfer_status is not None:
        rows = [r for r in rows if r["transfer_status"] == transfer_status]
    if fund_type is not None:
        rows = [r for r in rows if r["fund_type"] == fund_type]
    page, total = paginate(by_created(rows), limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restricted-funds/<fund_id>")
def get_fund(fund_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "CharitableTrustCounsel",
                  "StateCharitiesRegulator"])
    fund = services.find_fund(fund_id)
    return ok_row(fund)


@bp.get("/restricted-funds")
def list_funds():
    authenticate(["PlatformAdmin", "StrategyOfficer", "CharitableTrustCounsel",
                  "StateCharitiesRegulator"])
    limit, offset = pagination()
    org_id = query_str("org_id")
    transferred_to_org_id = query_str("transferred_to_org_id")
    transfer_restructuring_id = query_str("transfer_restructuring_id")
    transfer_status = query_enum("transfer_status", enums.FUND_STATUSES)
    fund_type = query_enum("fund_type", enums.FUND_TYPES)
    rows = by_created(list(FUNDS.values()))
    if org_id is not None:
        rows = [r for r in rows if r["org_id"] == org_id]
    if transferred_to_org_id is not None:
        rows = [r for r in rows if r["transferred_to_org_id"] == transferred_to_org_id]
    if transfer_restructuring_id is not None:
        rows = [r for r in rows
                if r["transfer_restructuring_id"] == transfer_restructuring_id]
    if transfer_status is not None:
        rows = [r for r in rows if r["transfer_status"] == transfer_status]
    if fund_type is not None:
        rows = [r for r in rows if r["fund_type"] == fund_type]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/integration-tasks/<task_id>")
def get_task(task_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "IntegrationManager"])
    task = services.find_task(task_id)
    return ok_row(task)


@bp.get("/integration-tasks")
def list_tasks():
    authenticate(["PlatformAdmin", "StrategyOfficer", "IntegrationManager"])
    limit, offset = pagination()
    restructuring_id = query_str("restructuring_id")
    depends_on_task_id = query_str("depends_on_task_id")
    crew_code = query_str("crew_code")
    workstream = query_enum("workstream", enums.TASK_WORKSTREAMS)
    status = query_enum("status", enums.TASK_STATUSES)
    rows = by_created(list(TASKS.values()))
    if restructuring_id is not None:
        rows = [r for r in rows if r["restructuring_id"] == restructuring_id]
    if depends_on_task_id is not None:
        rows = [r for r in rows if r["depends_on_task_id"] == depends_on_task_id]
    if crew_code is not None:
        rows = [r for r in rows if r["crew_code"] == crew_code]
    if workstream is not None:
        rows = [r for r in rows if r["workstream"] == workstream]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restructurings/<deal_id>/dossier")
def get_dossier(deal_id):
    authenticate(["PlatformAdmin", "StrategyOfficer", "BoardSecretary",
                  "CharitableTrustCounsel", "StateCharitiesRegulator"])
    deal = services.find_deal(deal_id)

    screening = services.latest_assessment(deal_id, "SCREENING")
    adjusted = services.latest_assessment(deal_id, "DILIGENCE_ADJUSTED")
    screening_score = Decimal(str(screening["composite_score"])) if screening else Decimal("0.00")
    adjusted_score = Decimal(str(adjusted["composite_score"])) if adjusted else Decimal("0.00")
    basis = adjusted if adjusted is not None else screening

    init = ORGANIZATIONS.get(deal["initiator_org_id"])
    tgt = ORGANIZATIONS.get(deal["target_org_id"])
    pair_corpus = 0
    for org in (init, tgt):
        if org is not None:
            pair_corpus += org["restricted_corpus_cents"]

    certified_total = services.certified_allocated_total(deal_id)
    data = {
        "restructuring_id": deal["id"],
        "deal_status": deal["status"],
        "structure_type": deal["structure_type"],
        "round_no": deal["round_no"],
        "screening_composite_score": float(rhu(screening_score, 2)),
        "diligence_adjusted_composite_score": float(rhu(adjusted_score, 2)),
        "composite_delta": float(rhu(adjusted_score - screening_score, 2)),
        "reserve_months": float(rhu(Decimal(str(basis["reserve_months"])), 2)) if basis else 0.00,
        "combined_monthly_expense_cents": basis["combined_monthly_expense_cents"] if basis else 0,
        "restricted_asset_posture": deal["restricted_asset_posture"],
        "unresolved_restricted_fund_count": deal["unresolved_restricted_fund_count"],
        "pair_restricted_corpus_cents": pair_corpus,
        "reserved_seat_pool": deal["reserved_seat_pool"],
        "certified_allocated_seats_total": certified_total,
        "seat_ledger_total": deal["reserved_seat_pool"] + certified_total,
        "combined_board_seats": deal["combined_board_seats"],
    }
    return ok(data)
