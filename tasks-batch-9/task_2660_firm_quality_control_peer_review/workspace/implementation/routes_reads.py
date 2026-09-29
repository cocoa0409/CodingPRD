"""The thirty-one read endpoints (PRD 2.3, 4).

List reads are ordered by ``created_at`` ascending, the single documented exception being
``/inspection-selections`` filtered by ``inspection_id``, which is ordered by
``selected_rank`` ascending.
"""

from flask import Blueprint, request

import auth
import calc
import response
import shapes
import store

bp = Blueprint("reads", __name__)

A = auth.SYSTEM_ADMIN
FMP = auth.FIRM_MANAGING_PARTNER
EP = auth.ENGAGEMENT_PARTNER
QCD = auth.QUALITY_CONTROL_DIRECTOR
EQR = auth.ENGAGEMENT_QUALITY_REVIEWER
PR = auth.PEER_REVIEWER
PRC = auth.PEER_REVIEW_COMMITTEE


def _bool_arg(raw):
    text = str(raw).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    return None


def _matches(row, filters):
    for name, kind in filters.items():
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        actual = row.get(name)
        if kind == "bool":
            wanted = _bool_arg(raw)
            if wanted is None or bool(actual) != wanted:
                return False
        elif kind == "int":
            try:
                wanted = int(str(raw).strip())
            except (TypeError, ValueError):
                return False
            if actual != wanted:
                return False
        else:
            if actual != raw:
                return False
    return True


def list_rows(collection, filters, sort_key=None):
    rows = [row for row in store.rows(collection) if _matches(row, filters)]
    rows.sort(key=sort_key or store.order_key)
    limit, offset = response.pagination(request.args)
    page, total = response.paginate(rows, limit, offset)
    return response.array_response(
        store.serialize_many(collection, page), limit, offset, total)


def read_one(collection, row, isolate=True):
    if isolate:
        actor = getattr(request, "prd_actor", None)
        if actor is not None:
            firm_id = calc.firm_of(collection, row)
            if firm_id is not None:
                auth.require_same_firm(actor, firm_id)
    return response.object_response(store.serialize(collection, row))


def begin(roles):
    actor = auth.authenticate(roles)
    request.prd_actor = actor
    return actor


# --------------------------------------------------------------------------- #
# Firms
# --------------------------------------------------------------------------- #

@bp.get("/firms")
def get_firms():
    begin((A, PRC, FMP, QCD))
    return list_rows(store.FIRMS, {"enrolled_program": "str", "risk_posture": "str"})


@bp.get("/firms/<firm_id>")
def get_firm(firm_id):
    begin((A, PRC, FMP, QCD, PR))
    firm = shapes.need_firm(firm_id)
    return read_one(store.FIRMS, firm)


@bp.get("/firms/<firm_id>/quality-management-summary")
def get_firm_summary(firm_id):
    actor = begin((A, FMP, QCD, PRC))
    firm = shapes.need_firm(firm_id)
    auth.require_same_firm(actor, firm["id"])
    inspections = [row for row in store.rows(store.INSPECTIONS)
                   if row["firm_id"] == firm["id"]]
    latest = None
    if inspections:
        inspections.sort(key=lambda r: (r["inspection_year"], store.order_key(r)))
        latest = inspections[-1]
    data = store.serialize(store.FIRMS, firm)
    data["firm_id"] = firm["id"]
    data["must_select_categories"] = calc.firm_must_select_categories(
        firm, firm["peer_review_year_end"])
    data["latest_inspection_id"] = latest["id"] if latest else None
    data["latest_inspection_year"] = latest["inspection_year"] if latest else None
    data["latest_inspection_state"] = latest["state"] if latest else None
    return response.object_response(data)


# --------------------------------------------------------------------------- #
# Partners / engagements
# --------------------------------------------------------------------------- #

@bp.get("/partners")
def get_partners():
    begin((A, FMP, QCD, PR, PRC))
    return list_rows(store.PARTNERS,
                     {"firm_id": "str", "status": "str", "eqr_eligible": "bool"})


@bp.get("/partners/<partner_id>")
def get_partner(partner_id):
    begin((A, FMP, QCD, EQR, PR))
    return read_one(store.PARTNERS, shapes.need_partner(partner_id))


@bp.get("/engagements")
def get_engagements():
    begin((A, FMP, QCD, EP, EQR, PR))
    return list_rows(store.ENGAGEMENTS, {
        "firm_id": "str", "engagement_partner_id": "str", "workflow_state": "str",
        "file_state": "str", "engagement_type": "str", "eqr_required": "bool",
    })


@bp.get("/engagements/<engagement_id>")
def get_engagement(engagement_id):
    begin((A, FMP, QCD, EP, EQR, PR))
    return read_one(store.ENGAGEMENTS, shapes.need_engagement(engagement_id))


# --------------------------------------------------------------------------- #
# Quality risks and responses
# --------------------------------------------------------------------------- #

@bp.get("/quality-risks")
def get_quality_risks():
    begin((A, FMP, QCD, PR))
    return list_rows(store.QUALITY_RISKS, {
        "firm_id": "str", "component": "str", "state": "str", "severity_band": "str"})


@bp.get("/quality-risks/<risk_id>")
def get_quality_risk(risk_id):
    begin((A, FMP, QCD, PR))
    return read_one(store.QUALITY_RISKS, shapes.need_risk(risk_id))


@bp.get("/risk-responses")
def get_risk_responses():
    begin((A, FMP, QCD, PR))
    return list_rows(store.RISK_RESPONSES, {
        "quality_risk_id": "str", "status": "str", "response_type": "str"})


@bp.get("/risk-responses/<response_id>")
def get_risk_response(response_id):
    begin((A, FMP, QCD, PR))
    return read_one(store.RISK_RESPONSES, shapes.need_response(response_id))


# --------------------------------------------------------------------------- #
# Engagement quality reviews
# --------------------------------------------------------------------------- #

@bp.get("/quality-reviews")
def get_quality_reviews():
    begin((A, FMP, QCD, EP, EQR, PR))
    return list_rows(store.QUALITY_REVIEWS, {
        "engagement_id": "str", "reviewer_partner_id": "str", "state": "str"})


@bp.get("/quality-reviews/<eqr_id>")
def get_quality_review(eqr_id):
    begin((A, FMP, QCD, EP, EQR))
    return read_one(store.QUALITY_REVIEWS, shapes.need_review(eqr_id))


# --------------------------------------------------------------------------- #
# Internal inspections
# --------------------------------------------------------------------------- #

@bp.get("/internal-inspections")
def get_inspections():
    begin((A, FMP, QCD, PR, PRC))
    return list_rows(store.INSPECTIONS, {
        "firm_id": "str", "inspection_year": "int", "state": "str"})


@bp.get("/internal-inspections/<inspection_id>")
def get_inspection(inspection_id):
    begin((A, FMP, QCD, PR, PRC))
    return read_one(store.INSPECTIONS, shapes.need_inspection(inspection_id))


@bp.get("/inspection-selections")
def get_inspection_selections():
    begin((A, FMP, QCD, PR))
    sort_key = None
    if request.args.get("inspection_id"):
        sort_key = lambda row: (row["selected_rank"], store.order_key(row))
    return list_rows(store.INSPECTION_SELECTIONS, {
        "inspection_id": "str", "engagement_id": "str", "is_must_select": "bool",
    }, sort_key=sort_key)


@bp.get("/inspection-selections/<selection_id>")
def get_inspection_selection(selection_id):
    begin((A, FMP, QCD, PR))
    return read_one(store.INSPECTION_SELECTIONS, shapes.need_selection(selection_id))


@bp.get("/inspection-findings")
def get_findings():
    begin((A, FMP, QCD, EP, PR))
    return list_rows(store.FINDINGS, {
        "selection_id": "str", "state": "str", "classification": "str",
        "sqm_component": "str"})


@bp.get("/inspection-findings/<finding_id>")
def get_finding(finding_id):
    begin((A, FMP, QCD, EP, PR))
    return read_one(store.FINDINGS, shapes.need_finding(finding_id))


@bp.get("/root-cause-analyses")
def get_rcas():
    begin((A, FMP, QCD, EP))
    return list_rows(store.RCAS, {
        "finding_id": "str", "method": "str", "root_cause_category": "str",
        "state": "str"})


@bp.get("/root-cause-analyses/<rca_id>")
def get_rca(rca_id):
    begin((A, FMP, QCD, EP))
    return read_one(store.RCAS, shapes.need_rca(rca_id))


@bp.get("/remediation-plans")
def get_plans():
    begin((A, FMP, QCD, EP))
    return list_rows(store.PLANS, {
        "finding_id": "str", "root_cause_analysis_id": "str", "owner_partner_id": "str",
        "state": "str", "completeness_tier": "str"})


@bp.get("/remediation-plans/<plan_id>")
def get_plan(plan_id):
    begin((A, FMP, QCD, EP))
    return read_one(store.PLANS, shapes.need_plan(plan_id))


# --------------------------------------------------------------------------- #
# Peer review roster and lifecycle
# --------------------------------------------------------------------------- #

@bp.get("/peer-reviewers")
def get_reviewers():
    begin((A, PRC, FMP))
    return list_rows(store.PEER_REVIEWERS, {
        "status": "str", "license_state": "str", "accepts_out_of_state": "bool"})


@bp.get("/peer-reviewers/<reviewer_id>")
def get_reviewer(reviewer_id):
    begin((A, PRC, FMP, PR))
    return read_one(store.PEER_REVIEWERS, shapes.need_reviewer(reviewer_id))


@bp.get("/peer-reviews")
def get_peer_reviews():
    begin((A, PRC, FMP, QCD, PR))
    return list_rows(store.PEER_REVIEWS, {
        "firm_id": "str", "prior_peer_review_id": "str", "assigned_reviewer_id": "str",
        "state": "str", "rating": "str", "is_follow_up": "bool"})


@bp.get("/peer-reviews/<peer_review_id>")
def get_peer_review(peer_review_id):
    begin((A, PRC, FMP, QCD, PR))
    return read_one(store.PEER_REVIEWS, shapes.need_peer_review(peer_review_id))


@bp.get("/peer-review-selections")
def get_pr_selections():
    begin((A, PRC, FMP, QCD, PR))
    return list_rows(store.PR_SELECTIONS, {
        "peer_review_id": "str", "engagement_id": "str", "status": "str",
        "must_select_category": "str"})


@bp.get("/peer-review-selections/<selection_id>")
def get_pr_selection(selection_id):
    begin((A, PRC, FMP, QCD, PR))
    return read_one(store.PR_SELECTIONS, shapes.need_pr_selection(selection_id))


@bp.get("/corrective-action-plans")
def get_caps():
    begin((A, PRC, FMP, QCD, PR))
    return list_rows(store.CAPS, {
        "peer_review_id": "str", "status": "str", "action_code": "str"})


@bp.get("/corrective-action-plans/<cap_id>")
def get_cap(cap_id):
    begin((A, PRC, FMP, QCD))
    return read_one(store.CAPS, shapes.need_cap(cap_id))
