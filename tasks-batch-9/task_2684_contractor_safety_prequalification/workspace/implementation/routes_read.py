"""Every read endpoint. Rows are narrowed by the caller's identity (PRD 2.1)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import derive
import response
import serialize
import validators as V
from store import S, fmt_dt, sort_created, sort_created_id

bp = Blueprint("read", __name__)

READ = auth.READ_ROLES


def _page(rows, serializer, limit, offset):
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([serializer(r) for r in window], total, limit, offset)


@bp.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_client(client_id)
    auth.check_owner(role, user_id, client_id=row["id"])
    return response.ok(serialize.client(row))


@bp.route("/clients/<client_id>/sites", methods=["GET"])
def list_sites(client_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    client = V.get_client(client_id)
    auth.check_owner(role, user_id, client_id=client["id"])
    rows = sort_created(derive.sites_of(client["id"]))
    return _page(rows, serialize.site, limit, offset)


@bp.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_site(site_id)
    auth.check_owner(role, user_id, client_id=row["client_id"])
    return response.ok(serialize.site(row))


@bp.route("/contractors/<contractor_id>", methods=["GET"])
def get_contractor(contractor_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_contractor(contractor_id)
    auth.check_owner(role, user_id, contractor_id=row["id"])
    return response.ok(serialize.contractor(row))


@bp.route("/contractors/<contractor_id>/insurance-certificates", methods=["GET"])
def list_certificates(contractor_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    coverage_type = V.query_enum("coverage_type", calc.COVERAGE_TYPES)
    contractor = V.get_contractor(contractor_id)
    auth.check_owner(role, user_id, contractor_id=contractor["id"])
    rows = derive.certs_of(contractor["id"])
    if coverage_type is not None:
        rows = [r for r in rows if r["coverage_type"] == coverage_type]
    return _page(sort_created(rows), serialize.insurance_certificate, limit, offset)


@bp.route("/contractors/<contractor_id>/workers", methods=["GET"])
def list_workers(contractor_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    trade_code = V.query_enum("trade_code", calc.TRADE_CODES)
    contractor = V.get_contractor(contractor_id)
    auth.check_owner(role, user_id, contractor_id=contractor["id"])
    rows = derive.workers_of(contractor["id"])
    if trade_code is not None:
        rows = [r for r in rows if r["trade_code"] == trade_code]
    return _page(sort_created(rows), serialize.worker, limit, offset)


@bp.route("/workers/<worker_id>", methods=["GET"])
def get_worker(worker_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_worker(worker_id)
    auth.check_owner(role, user_id, contractor_id=row["contractor_id"])
    return response.ok(serialize.worker(row))


@bp.route("/workers/<worker_id>/qualifications", methods=["GET"])
def list_qualifications(worker_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    qualification_code = V.query_enum("qualification_code", calc.QUALIFICATION_CODES)
    worker = V.get_worker(worker_id)
    auth.check_owner(role, user_id, contractor_id=worker["contractor_id"])
    rows = derive.quals_of(worker["id"])
    if qualification_code is not None:
        rows = [r for r in rows if r["qualification_code"] == qualification_code]
    return _page(sort_created(rows), serialize.worker_qualification, limit, offset)


@bp.route("/prequalifications", methods=["GET"])
def list_prequalifications():
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_contractor = V.query_str("contractor_id")
    f_client = V.query_str("client_id")
    f_status = V.query_enum("status", calc.PREQUAL_STATUSES)
    f_cycle_year = V.query_int("cycle_year")
    f_audit_state = V.query_enum("audit_state", calc.AUDIT_STATES)

    rows = []
    for row in S.prequalifications.values():
        if not auth.visible(role, user_id, row["contractor_id"], row["client_id"]):
            continue
        if f_contractor is not None and row["contractor_id"] != f_contractor:
            continue
        if f_client is not None and row["client_id"] != f_client:
            continue
        if f_status is not None and row["status"] != f_status:
            continue
        if f_cycle_year is not None and row["cycle_year"] != f_cycle_year:
            continue
        if f_audit_state is not None and row["audit_state"] != f_audit_state:
            continue
        rows.append(row)
    return _page(sort_created_id(rows), serialize.prequalification, limit, offset)


@bp.route("/prequalifications/<prequalification_id>", methods=["GET"])
def get_prequalification(prequalification_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, contractor_id=row["contractor_id"], client_id=row["client_id"])
    return response.ok(serialize.prequalification(row))


def _owned_prequal(prequalification_id, user_id, role):
    row = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, contractor_id=row["contractor_id"], client_id=row["client_id"])
    return row


@bp.route("/prequalifications/<prequalification_id>/safety-statistics", methods=["GET"])
def list_safety_statistics(prequalification_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_status = V.query_enum("verification_status", calc.STAT_VERIFICATION_STATUSES)
    preq = _owned_prequal(prequalification_id, user_id, role)
    rows = derive.stats_of(preq["id"])
    if f_status is not None:
        rows = [r for r in rows if r["verification_status"] == f_status]
    rows = sorted(
        rows, key=lambda r: (r["reporting_year"], r["created_at"], r["_seq"]), reverse=True
    )
    return _page(rows, serialize.safety_statistic, limit, offset)


@bp.route("/prequalifications/<prequalification_id>/written-programs", methods=["GET"])
def list_written_programs(prequalification_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_status = V.query_enum("review_status", calc.PROGRAM_REVIEW_STATUSES)
    preq = _owned_prequal(prequalification_id, user_id, role)
    rows = derive.programs_of(preq["id"])
    if f_status is not None:
        rows = [r for r in rows if r["review_status"] == f_status]
    return _page(sort_created(rows), serialize.written_program, limit, offset)


@bp.route("/prequalifications/<prequalification_id>/improvement-plans", methods=["GET"])
def list_improvement_plans(prequalification_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_status = V.query_enum("status", calc.PLAN_STATUSES)
    preq = _owned_prequal(prequalification_id, user_id, role)
    rows = derive.plans_of(preq["id"])
    if f_status is not None:
        rows = [r for r in rows if derive.plan_projected_status(r) == f_status]
    return _page(sort_created(rows), serialize.improvement_plan, limit, offset)


@bp.route("/prequalifications/<prequalification_id>/variances", methods=["GET"])
def list_variances(prequalification_id):
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_status = V.query_enum("status", calc.VARIANCE_STATUSES)
    preq = _owned_prequal(prequalification_id, user_id, role)
    rows = derive.variances_of(preq["id"])
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    return _page(sort_created(rows), serialize.variance, limit, offset)


@bp.route("/prequalifications/<prequalification_id>/scorecard", methods=["GET"])
def get_scorecard(prequalification_id):
    user_id, role = auth.authenticate(READ)
    preq = _owned_prequal(prequalification_id, user_id, role)
    client = S.clients[preq["client_id"]]
    contractor = S.contractors[preq["contractor_id"]]

    governing = derive.governing_statistic(preq["id"], ("VERIFIED",))
    provisional = None
    final = None
    metrics_out = {"trir": None, "dart_rate": None, "emr": None, "citation_points": None}
    governing_year = None
    rank = derive.client_scoped_severity_rank(contractor["id"], client["id"])
    tier = calc.hazard_tier(contractor["hazard_profile"], rank)
    if governing is not None:
        governing_year = governing["reporting_year"]
        metrics_out = {
            "trir": governing["trir"],
            "dart_rate": governing["dart_rate"],
            "emr": governing["emr"],
            "citation_points": governing["citation_points"],
        }
        metrics = derive.metrics_from(governing)
        thresholds_p, _f, _t = derive.resolve_thresholds(preq, True)
        provisional, _subs = calc.composite_score(
            metrics, thresholds_p, derive.weights_of(client)
        )
        thresholds_f, _f2, _t2 = derive.resolve_thresholds(preq, False)
        final, _subs2 = calc.composite_score(metrics, thresholds_f, derive.weights_of(client))

    return response.ok(
        {
            "prequalification_id": preq["id"],
            "contractor_id": preq["contractor_id"],
            "client_id": preq["client_id"],
            "status": preq["status"],
            "grade": preq["grade"],
            "provisional_composite_score": provisional,
            "final_composite_score": final,
            "governing_reporting_year": governing_year,
            "hazard_tier": tier,
            "normalized_metrics": metrics_out,
            "effective_thresholds": preq["effective_thresholds"],
            "deficiency_codes": list(preq["deficiency_codes"]),
            "conditional_expires_at": fmt_dt(preq["conditional_expires_at"]),
            "expires_at": fmt_dt(preq["expires_at"]),
        }
    )


# ----------------------------------------------------------- site access -------


def _grant_scope(grant):
    preq = S.prequalifications[grant["prequalification_id"]]
    site = S.sites[grant["site_id"]]
    return preq["contractor_id"], site["client_id"]


@bp.route("/site-access-grants", methods=["GET"])
def list_site_access_grants():
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_worker = V.query_str("worker_id")
    f_site = V.query_str("site_id")
    f_prequal = V.query_str("prequalification_id")
    f_status = V.query_enum("status", calc.GRANT_STATUSES)

    rows = []
    for row in S.site_access_grants.values():
        contractor_id, client_id = _grant_scope(row)
        if not auth.visible(role, user_id, contractor_id, client_id):
            continue
        if f_worker is not None and row["worker_id"] != f_worker:
            continue
        if f_site is not None and row["site_id"] != f_site:
            continue
        if f_prequal is not None and row["prequalification_id"] != f_prequal:
            continue
        if f_status is not None and row["status"] != f_status:
            continue
        rows.append(row)
    return _page(sort_created_id(rows), serialize.site_access_grant, limit, offset)


@bp.route("/site-access-grants/<grant_id>", methods=["GET"])
def get_site_access_grant(grant_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_leaf(S.site_access_grants, grant_id)
    contractor_id, client_id = _grant_scope(row)
    auth.check_owner(role, user_id, contractor_id=contractor_id, client_id=client_id)
    return response.ok(serialize.site_access_grant(row))


# -------------------------------------------------------------- incidents ------


@bp.route("/incident-reports", methods=["GET"])
def list_incident_reports():
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_contractor = V.query_str("contractor_id")
    f_site = V.query_str("site_id")
    f_review = V.query_enum("review_status", calc.INCIDENT_REVIEW_STATUSES)
    f_severity = V.query_enum("severity", calc.SEVERITIES)

    rows = []
    for row in S.incident_reports.values():
        client_id = S.sites[row["site_id"]]["client_id"]
        if not auth.visible(role, user_id, row["contractor_id"], client_id):
            continue
        if f_contractor is not None and row["contractor_id"] != f_contractor:
            continue
        if f_site is not None and row["site_id"] != f_site:
            continue
        if f_review is not None and row["review_status"] != f_review:
            continue
        if f_severity is not None and row["severity"] != f_severity:
            continue
        rows.append(row)
    rows = sorted(rows, key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]), reverse=True)
    return _page(rows, serialize.incident_report, limit, offset)


@bp.route("/incident-reports/<incident_id>", methods=["GET"])
def get_incident_report(incident_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_leaf(S.incident_reports, incident_id)
    client_id = S.sites[row["site_id"]]["client_id"]
    auth.check_owner(role, user_id, contractor_id=row["contractor_id"], client_id=client_id)
    return response.ok(serialize.incident_report(row))


# ------------------------------------------------------- subcontractor ---------


def _link_scope(link):
    preq = S.prequalifications[link["prequalification_id"]]
    return (
        [link["parent_contractor_id"], link["child_contractor_id"], preq["contractor_id"]],
        preq["client_id"],
    )


@bp.route("/subcontractor-links", methods=["GET"])
def list_subcontractor_links():
    user_id, role = auth.authenticate(READ)
    limit, offset = V.pagination()
    f_parent = V.query_str("parent_contractor_id")
    f_child = V.query_str("child_contractor_id")
    f_prequal = V.query_str("prequalification_id")
    f_status = V.query_enum("status", calc.LINK_STATUSES)

    rows = []
    for row in S.subcontractor_links.values():
        contractor_ids, client_id = _link_scope(row)
        if not auth.visible_any_contractor(role, user_id, contractor_ids, client_id):
            continue
        if f_parent is not None and row["parent_contractor_id"] != f_parent:
            continue
        if f_child is not None and row["child_contractor_id"] != f_child:
            continue
        if f_prequal is not None and row["prequalification_id"] != f_prequal:
            continue
        if f_status is not None and row["status"] != f_status:
            continue
        rows.append(row)
    rows = sorted(rows, key=lambda r: (r["depth"], r["created_at"], r["_seq"]))
    return _page(rows, serialize.subcontractor_link, limit, offset)


@bp.route("/subcontractor-links/<link_id>", methods=["GET"])
def get_subcontractor_link(link_id):
    user_id, role = auth.authenticate(READ)
    row = V.get_leaf(S.subcontractor_links, link_id)
    contractor_ids, client_id = _link_scope(row)
    auth.check_owner_any_contractor(role, user_id, contractor_ids, client_id=client_id)
    return response.ok(serialize.subcontractor_link(row))
