"""Data Breach Incident Response API — Flask entry point."""
import os
import re

from flask import Flask, request

import clock
import errors
from db import store, new_id
from errors import ApiError
from middleware import require_role, current_user
from response import success, success_list, error as err_response
import services

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

ALL_READ_ROLES = (
    "IncidentCommander", "ForensicLead", "PrivacyCounsel",
    "GeneralCounsel", "DataAnalyst", "Auditor",
)

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(errors.not_found())


@app.errorhandler(405)
def handle_405(e):
    return err_response(errors.not_found())


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError(errors.ERR_INVALID_REQUEST, str(e), 422))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.is_json:
        raise errors.invalid_request("request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise errors.invalid_request("request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise errors.invalid_request(f"{field} is required and must be a non-empty string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"{field} is required and must be an integer")
    return v


def req_dt(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise errors.invalid_request(f"{field} is required and must be an ISO8601 string")
    try:
        return clock.parse_iso(v)
    except Exception:
        raise errors.invalid_request(f"{field} must be a valid ISO8601 timestamp")


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise errors.invalid_request(f"{field} is required and must be an array")
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise errors.invalid_request(f"{field} must be a string")
    return v


def paginate(items):
    """Sort by created_at asc, apply limit/offset query params, return response."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0")
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    window = items[offset:offset + limit]
    return success_list(window, limit, offset, total)


def get_incident_or_404(incident_id):
    inc = store.incidents.get(incident_id)
    if inc is None:
        raise errors.not_found("incident not found")
    return inc


def get_child_or_404(table, row_id, incident_id, label):
    row = table.get(row_id)
    if row is None or row.get("incident_id") != incident_id:
        raise errors.not_found(f"{label} not found")
    return row


def get_flat_or_404(table, row_id, label):
    row = table.get(row_id)
    if row is None:
        raise errors.not_found(f"{label} not found")
    return row


def stamp_new(row, with_version=True):
    now_s = clock.iso(clock.now())
    row["id"] = new_id()
    row["created_at"] = now_s
    if with_version:
        row["updated_at"] = now_s
        row["version"] = 1
    return row


def current_scope_for_subset_check(incident_id):
    """Current ForensicScope for subset validation: latest scope in {BASELINED, AMENDED, FINAL}."""
    return services._latest_risk_scope(incident_id)


def check_subset(incident_id, elements):
    scope = current_scope_for_subset_check(incident_id)
    if scope is None:
        return
    if not set(elements).issubset(set(scope["data_elements_at_risk"])):
        raise errors.out_of_scope()


def expire_offers_passed_deadline():
    """Time-triggered: ISSUED offers whose expires_at <= now transition to EXPIRED."""
    now = clock.now()
    for offer in store.credit_monitoring_offers.values():
        if offer["status"] != "ISSUED":
            continue
        exp = clock.parse_iso(offer["expires_at"])
        if now >= exp:
            offer["status"] = "EXPIRED"
            services.bump_row(offer)
            subject = store.affected_subjects.get(offer["affected_subject_id"])
            if subject and subject["credit_monitoring_status"] == "OFFERED_PENDING":
                subject["credit_monitoring_status"] = "EXPIRED"
                services.bump_row(subject)
            incident = store.incidents.get(offer["incident_id"])
            if incident:
                services.recompute_incident_counters(incident)


# ---------------------------------------------------------------------------
# clock endpoint
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("IncidentCommander")
    body = get_body()
    to = req_dt(body, "to_iso8601")
    clock.set_now(to)
    expire_offers_passed_deadline()
    return success({"now": clock.iso(clock.now())}, status=200)


# ---------------------------------------------------------------------------
# incidents
# ---------------------------------------------------------------------------
SOURCE_CHANNELS = {"INTERNAL_DETECTION", "THIRD_PARTY_REPORT", "LAW_ENFORCEMENT",
                   "CUSTOMER_COMPLAINT", "AUDIT"}


@app.route("/incidents", methods=["POST"])
def create_incident():
    require_role("IncidentCommander")
    body = get_body()
    title = req_str(body, "title")
    discovered_at = req_dt(body, "discovered_at")
    occurred_at = req_dt(body, "occurred_at")
    source_channel = req_str(body, "source_channel")
    if source_channel not in SOURCE_CHANNELS:
        raise errors.invalid_request("invalid source_channel")
    inc = stamp_new({
        "title": title,
        "discovered_at": clock.iso(discovered_at),
        "occurred_at": clock.iso(occurred_at),
        "source_channel": source_channel,
        "severity": "UNCLASSIFIED",
        "investigation_status": "INTAKE",
        "notification_status": "NOT_REQUIRED",
        "risk_score_conservative": 0,
        "risk_score_likelihood_adjusted": 0,
        "total_affected_subjects": 0,
        "total_notified_subjects": 0,
        "total_pending_subjects": 0,
        "credit_monitoring_offered": 0,
        "credit_monitoring_enrolled": 0,
        "credit_monitoring_declined": 0,
        "remediation_status": "NOT_STARTED",
    })
    store.incidents[inc["id"]] = inc
    return success(inc, status=201)


@app.route("/incidents", methods=["GET"])
def list_incidents():
    require_role(*ALL_READ_ROLES)
    items = list(store.incidents.values())
    sev = request.args.get("severity")
    if sev:
        items = [i for i in items if i["severity"] == sev]
    inv = request.args.get("investigation_status")
    if inv:
        items = [i for i in items if i["investigation_status"] == inv]
    notif = request.args.get("notification_status")
    if notif:
        items = [i for i in items if i["notification_status"] == notif]
    return paginate(items)


@app.route("/incidents/<id>", methods=["GET"])
def get_incident(id):
    require_role(*ALL_READ_ROLES)
    inc = get_incident_or_404(id)
    return success(inc)


@app.route("/incidents/<id>/confirm", methods=["POST"])
def confirm_incident(id):
    require_role("IncidentCommander")
    inc = get_incident_or_404(id)
    if inc["investigation_status"] != "INVESTIGATING":
        raise errors.invalid_state("incident must be INVESTIGATING to confirm")
    sealed = any(
        e for e in store.evidence_items.values()
        if e["incident_id"] == id and e["status"] == "SEALED"
    )
    if not sealed:
        raise errors.evidence_not_sealed()
    services.recompute_incident_counters(inc)
    if inc["total_affected_subjects"] <= 0:
        raise errors.no_subjects()
    inc["investigation_status"] = "CONFIRMED"
    inc["notification_status"] = "EVALUATING"
    now = clock.now()
    inc["_confirmed_at"] = clock.iso(now)
    for je in store.jurisdiction_evaluations.values():
        if je["incident_id"] != id or je["status"] != "PENDING":
            continue
        je["status"] = "TRIGGERED"
        je["deadline_at"] = clock.iso(
            services.compute_deadline(now, je["deadline_days"], je["deadline_kind"])
        )
        services.bump_row(je)
    services.recompute_risk_scores(inc)
    services.recompute_jurisdiction_counters(inc)
    services.bump_incident(inc)
    return success(inc)


@app.route("/incidents/<id>/contain", methods=["POST"])
def contain_incident(id):
    require_role("IncidentCommander")
    inc = get_incident_or_404(id)
    if inc["investigation_status"] != "CONFIRMED":
        raise errors.invalid_state("incident must be CONFIRMED to contain")
    tech_open = any(
        a for a in store.remediation_actions.values()
        if a["incident_id"] == id and a["category"] == "TECHNICAL"
        and a["status"] not in ("COMPLETED", "VERIFIED", "CANCELLED")
    )
    if tech_open:
        raise errors.remediation_incomplete()
    inc["investigation_status"] = "CONTAINED"
    inc["remediation_status"] = "IN_PROGRESS"
    services.bump_incident(inc)
    return success(inc)


@app.route("/incidents/<id>/close", methods=["POST"])
def close_incident(id):
    require_role("IncidentCommander")
    inc = get_incident_or_404(id)
    if inc["investigation_status"] != "CONTAINED":
        raise errors.invalid_state("incident must be CONTAINED to close")
    if inc["notification_status"] not in ("COMPLETED", "WAIVED", "NOT_REQUIRED"):
        raise errors.invalid_state("notification_status not in terminal/idle posture")
    unfinished = any(
        a for a in store.remediation_actions.values()
        if a["incident_id"] == id and a["status"] not in ("VERIFIED", "CANCELLED")
    )
    if unfinished:
        raise errors.remediation_incomplete()
    open_subs = any(
        s for s in store.regulator_submissions.values()
        if s["incident_id"] == id and s["status"] not in ("CLOSED", "ACKNOWLEDGED")
    )
    if open_subs:
        raise errors.invalid_state("regulator submissions not all closed/acknowledged")
    if inc["remediation_status"] != "VERIFIED":
        raise errors.invalid_state("remediation_status must be VERIFIED")
    inc["investigation_status"] = "CLOSED"
    services.bump_incident(inc)
    return success(inc)


# ---------------------------------------------------------------------------
# forensic scopes
# ---------------------------------------------------------------------------
@app.route("/incidents/<id>/forensic-scopes", methods=["POST"])
def create_scope(id):
    require_role("IncidentCommander", "ForensicLead")
    inc = get_incident_or_404(id)
    body = get_body()
    statement = req_str(body, "scope_statement")
    systems = req_list(body, "systems_in_scope")
    elements = req_list(body, "data_elements_at_risk")
    pct = req_int(body, "exfiltration_likelihood_pct")
    if pct < 0 or pct > 100:
        raise errors.invalid_request("exfiltration_likelihood_pct must be 0-100")
    for e in elements:
        if e not in services.PII_CATEGORIES:
            raise errors.invalid_request(f"invalid data element: {e}")
    scope = stamp_new({
        "incident_id": id,
        "scope_statement": statement,
        "systems_in_scope": systems,
        "data_elements_at_risk": elements,
        "exfiltration_likelihood_pct": pct,
        "status": "DRAFT",
    })
    store.forensic_scopes[scope["id"]] = scope
    # incident transition precondition
    if inc["investigation_status"] == "INTAKE":
        if not systems or not elements:
            raise errors.invalid_request("systems_in_scope and data_elements_at_risk must be non-empty")
        inc["investigation_status"] = "SCOPED"
        services.recompute_risk_scores(inc)
        services.bump_incident(inc)
    return success(scope, status=201)


@app.route("/incidents/<id>/forensic-scopes", methods=["GET"])
def list_scopes(id):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [s for s in store.forensic_scopes.values() if s["incident_id"] == id]
    return paginate(items)


@app.route("/incidents/<id>/forensic-scopes/<scopeId>", methods=["GET"])
def get_scope(id, scopeId):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    scope = get_child_or_404(store.forensic_scopes, scopeId, id, "scope")
    return success(scope)


@app.route("/incidents/<id>/forensic-scopes/<scopeId>/baseline", methods=["POST"])
def baseline_scope(id, scopeId):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    scope = get_child_or_404(store.forensic_scopes, scopeId, id, "scope")
    if scope["status"] != "DRAFT":
        raise errors.invalid_state("scope must be DRAFT to baseline")
    if not scope["systems_in_scope"]:
        raise errors.invalid_state("systems_in_scope must be non-empty")
    if not scope["data_elements_at_risk"]:
        raise errors.invalid_state("data_elements_at_risk must be non-empty")
    scope["status"] = "BASELINED"
    services.bump_row(scope)
    if inc["investigation_status"] == "SCOPED":
        inc["investigation_status"] = "INVESTIGATING"
    services.recompute_risk_scores(inc)
    services.bump_incident(inc)
    return success(scope)


@app.route("/incidents/<id>/forensic-scopes/<scopeId>/amend", methods=["POST"])
def amend_scope(id, scopeId):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    scope = get_child_or_404(store.forensic_scopes, scopeId, id, "scope")
    if scope["status"] != "BASELINED":
        raise errors.invalid_state("scope must be BASELINED to amend")
    if inc["investigation_status"] != "INVESTIGATING":
        raise errors.invalid_state("incident must be INVESTIGATING to amend scope")
    body = get_body() if request.data else {}
    if "scope_statement" in body and body["scope_statement"] is not None:
        if not isinstance(body["scope_statement"], str):
            raise errors.invalid_request("scope_statement must be a string")
        scope["scope_statement"] = body["scope_statement"]
    if "systems_in_scope" in body and body["systems_in_scope"] is not None:
        if not isinstance(body["systems_in_scope"], list):
            raise errors.invalid_request("systems_in_scope must be an array")
        scope["systems_in_scope"] = body["systems_in_scope"]
    if "data_elements_at_risk" in body and body["data_elements_at_risk"] is not None:
        if not isinstance(body["data_elements_at_risk"], list):
            raise errors.invalid_request("data_elements_at_risk must be an array")
        for e in body["data_elements_at_risk"]:
            if e not in services.PII_CATEGORIES:
                raise errors.invalid_request(f"invalid data element: {e}")
        scope["data_elements_at_risk"] = body["data_elements_at_risk"]
    if "exfiltration_likelihood_pct" in body and body["exfiltration_likelihood_pct"] is not None:
        v = body["exfiltration_likelihood_pct"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 100:
            raise errors.invalid_request("exfiltration_likelihood_pct must be int 0-100")
        scope["exfiltration_likelihood_pct"] = v
    scope["status"] = "AMENDED"
    services.bump_row(scope)
    services.recompute_risk_scores(inc)
    services.bump_incident(inc)
    return success(scope)


@app.route("/incidents/<id>/forensic-scopes/<scopeId>/re-baseline", methods=["POST"])
def rebaseline_scope(id, scopeId):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    scope = get_child_or_404(store.forensic_scopes, scopeId, id, "scope")
    if scope["status"] != "AMENDED":
        raise errors.invalid_state("scope must be AMENDED to re-baseline")
    scope["status"] = "BASELINED"
    services.bump_row(scope)
    services.recompute_risk_scores(inc)
    services.bump_incident(inc)
    return success(scope)


@app.route("/incidents/<id>/forensic-scopes/<scopeId>/finalize", methods=["POST"])
def finalize_scope(id, scopeId):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    scope = get_child_or_404(store.forensic_scopes, scopeId, id, "scope")
    if scope["status"] != "BASELINED":
        raise errors.invalid_state("scope must be BASELINED to finalize")
    if inc["investigation_status"] not in ("CONFIRMED", "CONTAINED"):
        raise errors.invalid_state("incident must be CONFIRMED or CONTAINED to finalize scope")
    scope["status"] = "FINAL"
    services.bump_row(scope)
    services.bump_incident(inc)
    return success(scope)


# ---------------------------------------------------------------------------
# evidence items
# ---------------------------------------------------------------------------
EVIDENCE_TYPES = {"LOG", "DISK_IMAGE", "MEMORY_DUMP", "EMAIL", "NETWORK_PCAP", "DOCUMENT", "PHOTO"}


@app.route("/incidents/<id>/evidence-items", methods=["POST"])
def create_evidence(id):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    body = get_body()
    label = req_str(body, "label")
    etype = req_str(body, "evidence_type")
    if etype not in EVIDENCE_TYPES:
        raise errors.invalid_request("invalid evidence_type")
    collected_at = req_dt(body, "collected_at")
    collected_by = req_str(body, "collected_by_user_id")
    phash = req_str(body, "preservation_hash")
    item = stamp_new({
        "incident_id": id,
        "label": label,
        "evidence_type": etype,
        "collected_at": clock.iso(collected_at),
        "collected_by_user_id": collected_by,
        "preservation_hash": phash,
        "status": "COLLECTED",
    })
    store.evidence_items[item["id"]] = item
    services.bump_incident(inc)
    return success(item, status=201)


@app.route("/incidents/<id>/evidence-items", methods=["GET"])
def list_evidence(id):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [e for e in store.evidence_items.values() if e["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    return paginate(items)


@app.route("/incidents/<id>/evidence-items/<itemId>", methods=["GET"])
def get_evidence(id, itemId):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    item = get_child_or_404(store.evidence_items, itemId, id, "evidence item")
    return success(item)


@app.route("/incidents/<id>/evidence-items/<itemId>/seal", methods=["POST"])
def seal_evidence(id, itemId):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    item = get_child_or_404(store.evidence_items, itemId, id, "evidence item")
    if item["status"] != "COLLECTED":
        raise errors.invalid_state("evidence item must be COLLECTED to seal")
    phash = item.get("preservation_hash")
    if not phash or not HASH_RE.match(phash):
        raise errors.custody_overlap("preservation_hash must be 64 lowercase hex chars")
    now = clock.now()
    if services.custody_has_overlap(itemId, now, None):
        raise errors.custody_overlap("overlapping custody interval exists")
    item["status"] = "SEALED"
    services.bump_row(item)
    services.bump_incident(inc)
    return success(item)


@app.route("/incidents/<id>/evidence-items/<itemId>/release", methods=["POST"])
def release_evidence(id, itemId):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    item = get_child_or_404(store.evidence_items, itemId, id, "evidence item")
    if item["status"] != "SEALED":
        raise errors.invalid_state("evidence item must be SEALED to release")
    if inc["investigation_status"] not in ("CONFIRMED", "CONTAINED"):
        raise errors.invalid_state("incident must be CONFIRMED or CONTAINED to release evidence")
    item["status"] = "RELEASED"
    services.bump_row(item)
    services.bump_incident(inc)
    return success(item)


@app.route("/incidents/<id>/evidence-items/<itemId>/destroy", methods=["POST"])
def destroy_evidence(id, itemId):
    require_role("ForensicLead")
    inc = get_incident_or_404(id)
    item = get_child_or_404(store.evidence_items, itemId, id, "evidence item")
    if item["status"] != "SEALED":
        raise errors.invalid_state("evidence item must be SEALED to destroy")
    if inc["investigation_status"] != "CLOSED":
        raise errors.invalid_state("incident must be CLOSED to destroy evidence")
    item["status"] = "DESTROYED"
    services.bump_row(item)
    return success(item)


# ---------------------------------------------------------------------------
# custody logs
# ---------------------------------------------------------------------------
@app.route("/incidents/<id>/custody-logs", methods=["POST"])
def create_custody_log(id):
    require_role("ForensicLead")
    get_incident_or_404(id)
    body = get_body()
    item_id = req_str(body, "evidence_item_id")
    item = store.evidence_items.get(item_id)
    if item is None or item["incident_id"] != id:
        raise errors.not_found("evidence_item_id not found in this incident")
    custodian = req_str(body, "custodian_user_id")
    start_at = req_dt(body, "start_at")
    end_at = None
    if body.get("end_at") is not None:
        end_at = req_dt(body, "end_at")
    purpose = req_str(body, "purpose")
    if services.custody_has_overlap(item_id, start_at, end_at):
        raise errors.custody_overlap("custody interval overlaps an existing interval")
    log = stamp_new({
        "incident_id": id,
        "evidence_item_id": item_id,
        "custodian_user_id": custodian,
        "start_at": clock.iso(start_at),
        "end_at": clock.iso(end_at) if end_at else None,
        "purpose": purpose,
    }, with_version=False)
    store.custody_logs[log["id"]] = log
    return success(log, status=201)


@app.route("/incidents/<id>/custody-logs", methods=["GET"])
def list_custody_logs_nested(id):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [c for c in store.custody_logs.values() if c["incident_id"] == id]
    eid = request.args.get("evidence_item_id")
    if eid:
        items = [c for c in items if c["evidence_item_id"] == eid]
    return paginate(items)


@app.route("/custody-logs", methods=["GET"])
def list_custody_logs_flat():
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    items = list(store.custody_logs.values())
    eid = request.args.get("evidence_item_id")
    if eid:
        items = [c for c in items if c["evidence_item_id"] == eid]
    iid = request.args.get("incident_id")
    if iid:
        items = [c for c in items if c["incident_id"] == iid]
    return paginate(items)


@app.route("/custody-logs/<id>", methods=["GET"])
def get_custody_log_flat(id):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    log = get_flat_or_404(store.custody_logs, id, "custody log")
    return success(log)


# ---------------------------------------------------------------------------
# affected subjects
# ---------------------------------------------------------------------------
@app.route("/incidents/<id>/affected-subjects", methods=["POST"])
def create_subject(id):
    require_role("DataAnalyst")
    inc = get_incident_or_404(id)
    body = get_body()
    ref = req_str(body, "external_subject_ref")
    name = req_str(body, "full_name")
    state_code = req_str(body, "residence_state_code")
    elements = req_list(body, "data_elements_exposed")
    record_count = req_int(body, "record_count")
    for e in elements:
        if e not in services.PII_CATEGORIES:
            raise errors.invalid_request(f"invalid data element: {e}")
    check_subset(id, elements)
    dup = any(
        s for s in store.affected_subjects.values()
        if s["incident_id"] == id and s["external_subject_ref"] == ref and s["status"] != "EXCLUDED"
    )
    if dup:
        raise errors.duplicate_subject()
    subj = stamp_new({
        "incident_id": id,
        "external_subject_ref": ref,
        "full_name": name,
        "residence_state_code": state_code,
        "data_elements_exposed": elements,
        "record_count": record_count,
        "status": "IDENTIFIED",
        "credit_monitoring_status": "NOT_OFFERED",
        "offered_at": None,
    })
    store.affected_subjects[subj["id"]] = subj
    services.recompute_incident_counters(inc)
    services.recompute_risk_scores(inc)
    services.bump_incident(inc)
    return success(subj, status=201)


@app.route("/incidents/<id>/affected-subjects", methods=["GET"])
def list_subjects(id):
    require_role(*ALL_READ_ROLES)
    get_incident_or_404(id)
    items = [s for s in store.affected_subjects.values() if s["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    st = request.args.get("residence_state_code")
    if st:
        items = [s for s in items if s["residence_state_code"] == st]
    return paginate(items)


@app.route("/incidents/<id>/affected-subjects/<subjectId>", methods=["GET"])
def get_subject(id, subjectId):
    require_role(*ALL_READ_ROLES)
    get_incident_or_404(id)
    subj = get_child_or_404(store.affected_subjects, subjectId, id, "affected subject")
    return success(subj)


@app.route("/incidents/<id>/affected-subjects/<subjectId>/verify", methods=["POST"])
def verify_subject(id, subjectId):
    require_role("DataAnalyst")
    inc = get_incident_or_404(id)
    subj = get_child_or_404(store.affected_subjects, subjectId, id, "affected subject")
    if subj["status"] != "IDENTIFIED":
        raise errors.invalid_state("subject must be IDENTIFIED to verify")
    if not subj["data_elements_exposed"]:
        raise errors.invalid_state("data_elements_exposed must be non-empty to verify")
    check_subset(id, subj["data_elements_exposed"])
    subj["status"] = "VERIFIED"
    services.bump_row(subj)
    services.recompute_incident_counters(inc)
    services.recompute_risk_scores(inc)
    services.bump_incident(inc)
    return success(subj)


@app.route("/incidents/<id>/affected-subjects/<subjectId>/exclude", methods=["POST"])
def exclude_subject(id, subjectId):
    require_role("DataAnalyst")
    inc = get_incident_or_404(id)
    subj = get_child_or_404(store.affected_subjects, subjectId, id, "affected subject")
    if subj["status"] != "IDENTIFIED":
        raise errors.invalid_state("subject must be IDENTIFIED to exclude")
    if inc["notification_status"] in ("DISPATCHING", "COMPLETED"):
        raise errors.invalid_state("cannot exclude while notification is DISPATCHING or COMPLETED")
    check_subset(id, subj["data_elements_exposed"])
    subj["status"] = "EXCLUDED"
    services.bump_row(subj)
    services.recompute_incident_counters(inc)
    services.recompute_risk_scores(inc)
    services.bump_incident(inc)
    return success(subj)


# ---------------------------------------------------------------------------
# jurisdiction evaluations
# ---------------------------------------------------------------------------
@app.route("/incidents/<id>/jurisdiction-evaluations", methods=["POST"])
def create_je(id):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    body = get_body()
    state_code = req_str(body, "state_code")
    statute = req_str(body, "statute_reference")
    threshold = req_int(body, "record_count_threshold")
    deadline_days = req_int(body, "deadline_days")
    kind = req_str(body, "deadline_kind")
    if kind not in ("CALENDAR_DAYS", "BUSINESS_DAYS"):
        raise errors.invalid_request("deadline_kind must be CALENDAR_DAYS or BUSINESS_DAYS")
    req_ag = body.get("requires_ag_notification")
    req_cra = body.get("requires_credit_agencies")
    if not isinstance(req_ag, bool) or not isinstance(req_cra, bool):
        raise errors.invalid_request("requires_ag_notification and requires_credit_agencies must be booleans")
    je = stamp_new({
        "incident_id": id,
        "state_code": state_code,
        "statute_reference": statute,
        "record_count_threshold": threshold,
        "deadline_days": deadline_days,
        "deadline_kind": kind,
        "requires_ag_notification": req_ag,
        "requires_credit_agencies": req_cra,
        "subjects_in_jurisdiction": 0,
        "notification_required": False,
        "deadline_at": None,
        "status": "PENDING",
    })
    store.jurisdiction_evaluations[je["id"]] = je
    services.recompute_jurisdiction_counters(inc)
    services.bump_incident(inc)
    return success(je, status=201)


@app.route("/incidents/<id>/jurisdiction-evaluations", methods=["GET"])
def list_je(id):
    require_role(*ALL_READ_ROLES)
    get_incident_or_404(id)
    items = [j for j in store.jurisdiction_evaluations.values() if j["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [j for j in items if j["status"] == status]
    return paginate(items)


@app.route("/incidents/<id>/jurisdiction-evaluations/<evaluationId>", methods=["GET"])
def get_je(id, evaluationId):
    require_role(*ALL_READ_ROLES)
    get_incident_or_404(id)
    je = get_child_or_404(store.jurisdiction_evaluations, evaluationId, id, "jurisdiction evaluation")
    return success(je)


# ---------------------------------------------------------------------------
# notices
# ---------------------------------------------------------------------------
def _check_supersession_cycle(new_notice_id, supersedes_id):
    """Walk chain from supersedes_id; if we reach new_notice_id -> cycle.
    For creation, the new notice has no id yet in the chain; check that walking
    supersedes chain never loops (guard) — creation cycle means supersedes_id's
    chain already references the (not yet created) notice, which is impossible.
    A true cycle risk: supersedes_notice_id points at a notice that itself
    (transitively) supersedes... the new notice. Since new notice doesn't exist,
    no cycle is possible at creation unless supersedes chain itself is cyclic.
    Per spec, we check: following supersedes links from supersedes_id must not
    return to supersedes_id."""
    seen = set()
    cur = supersedes_id
    while cur is not None:
        if cur in seen:
            raise errors.supersession_cycle()
        seen.add(cur)
        nxt_notice = store.notices.get(cur)
        if nxt_notice is None:
            break
        cur = nxt_notice.get("supersedes_notice_id")


def _update_notification_status_after_notice_change(inc):
    """DRAFTING -> APPROVED when every TRIGGERED JE has an APPROVED or LOCKED_FOR_MAIL notice."""
    if inc["notification_status"] != "DRAFTING":
        return
    triggered = [
        j for j in store.jurisdiction_evaluations.values()
        if j["incident_id"] == inc["id"] and j["status"] == "TRIGGERED"
    ]
    if not triggered:
        return
    for je in triggered:
        ok = any(
            n for n in store.notices.values()
            if n["incident_id"] == inc["id"]
            and n["jurisdiction_evaluation_id"] == je["id"]
            and n["status"] in ("APPROVED", "LOCKED_FOR_MAIL")
        )
        if not ok:
            return
    inc["notification_status"] = "APPROVED"


@app.route("/incidents/<id>/notices", methods=["POST"])
def create_notice(id):
    user_id, _ = require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    body = get_body()
    je_id = req_str(body, "jurisdiction_evaluation_id")
    je = store.jurisdiction_evaluations.get(je_id)
    if je is None or je["incident_id"] != id:
        raise errors.not_found("jurisdiction_evaluation_id not found in this incident")
    body_text = req_str(body, "body_text")
    language = opt_str(body, "language", "en")
    supersedes_id = body.get("supersedes_notice_id")
    if supersedes_id is not None:
        if not isinstance(supersedes_id, str):
            raise errors.invalid_request("supersedes_notice_id must be a string")
        prior = store.notices.get(supersedes_id)
        if prior is None or prior["incident_id"] != id:
            raise errors.not_found("supersedes_notice_id not found in this incident")
    # supersession acyclicity
    if supersedes_id is not None:
        _check_supersession_cycle(None, supersedes_id)
    # OCC check (priority 17 per scaffold; PRD lists it last)
    expected = body.get("expected_incident_version")
    if expected is None:
        raise errors.invalid_request("expected_incident_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_incident_version must be an integer")
    if expected != inc["version"]:
        raise errors.stale_version()
    notice = stamp_new({
        "incident_id": id,
        "jurisdiction_evaluation_id": je_id,
        "version_label": 1,
        "body_text": body_text,
        "language": language,
        "approved_by_user_id": None,
        "approved_at": None,
        "supersedes_notice_id": supersedes_id,
        "status": "DRAFT",
        "created_by_user_id": user_id,
    })
    store.notices[notice["id"]] = notice
    if inc["notification_status"] == "REQUIRED":
        inc["notification_status"] = "DRAFTING"
    services.bump_incident(inc)
    return success(notice, status=201)


@app.route("/incidents/<id>/notices", methods=["GET"])
def list_notices(id):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [n for n in store.notices.values() if n["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [n for n in items if n["status"] == status]
    return paginate(items)


@app.route("/incidents/<id>/notices/<noticeId>", methods=["GET"])
def get_notice(id, noticeId):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    notice = get_child_or_404(store.notices, noticeId, id, "notice")
    return success(notice)


@app.route("/incidents/<id>/notices/<noticeId>/submit-for-review", methods=["POST"])
def submit_notice(id, noticeId):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    notice = get_child_or_404(store.notices, noticeId, id, "notice")
    if notice["status"] != "DRAFT":
        raise errors.invalid_state("notice must be DRAFT to submit for review")
    if len(notice["body_text"]) < 200:
        raise errors.invalid_request("body_text must be at least 200 characters")
    if inc["notification_status"] not in ("DRAFTING", "REQUIRED"):
        raise errors.invalid_state("incident notification_status must be DRAFTING or REQUIRED")
    notice["status"] = "LEGAL_REVIEW"
    services.bump_row(notice)
    # supersession cascade: if this notice supersedes an APPROVED notice, supersede it
    sup_id = notice.get("supersedes_notice_id")
    if sup_id:
        prior = store.notices.get(sup_id)
        if prior and prior["status"] == "APPROVED":
            prior["status"] = "SUPERSEDED"
            services.bump_row(prior)
            for batch in store.mailing_batches.values():
                if batch["notice_id"] == prior["id"] and batch["status"] == "QUEUED":
                    batch["status"] = "FAILED"
                    services.bump_row(batch)
    services.bump_incident(inc)
    return success(notice)


@app.route("/incidents/<id>/notices/<noticeId>/approve", methods=["POST"])
def approve_notice(id, noticeId):
    user_id, _ = require_role("GeneralCounsel")
    inc = get_incident_or_404(id)
    notice = get_child_or_404(store.notices, noticeId, id, "notice")
    if notice["status"] != "LEGAL_REVIEW":
        raise errors.invalid_state("notice must be LEGAL_REVIEW to approve")
    if inc["investigation_status"] != "CONFIRMED":
        raise errors.invalid_state("incident must be CONFIRMED to approve notice")
    je = store.jurisdiction_evaluations.get(notice["jurisdiction_evaluation_id"])
    if je is not None and je.get("deadline_at"):
        if clock.parse_iso(je["deadline_at"]) <= clock.now():
            raise errors.deadline_passed("jurisdiction deadline has passed")
    if notice.get("created_by_user_id") == user_id:
        raise errors.segregation("approver must differ from notice author")
    notice["status"] = "APPROVED"
    notice["approved_by_user_id"] = user_id
    notice["approved_at"] = clock.iso(clock.now())
    services.bump_row(notice)
    services.bump_incident(inc)
    _update_notification_status_after_notice_change(inc)
    return success(notice)


@app.route("/incidents/<id>/notices/<noticeId>/request-changes", methods=["POST"])
def request_changes(id, noticeId):
    require_role("GeneralCounsel")
    get_incident_or_404(id)
    notice = get_child_or_404(store.notices, noticeId, id, "notice")
    if notice["status"] != "LEGAL_REVIEW":
        raise errors.invalid_state("notice must be LEGAL_REVIEW to request changes")
    notice["status"] = "DRAFT"
    notice["version_label"] += 1
    services.bump_row(notice)
    return success(notice)


@app.route("/incidents/<id>/notices/<noticeId>/lock-for-mail", methods=["POST"])
def lock_notice(id, noticeId):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    notice = get_child_or_404(store.notices, noticeId, id, "notice")
    if notice["status"] != "APPROVED":
        raise errors.invalid_state("notice must be APPROVED to lock for mail")
    active_batch = any(
        b for b in store.mailing_batches.values()
        if b["notice_id"] == noticeId and b["status"] in ("QUEUED", "IN_PRODUCTION")
    )
    if active_batch:
        raise errors.invalid_state("an active mailing batch exists for this notice")
    notice["status"] = "LOCKED_FOR_MAIL"
    services.bump_row(notice)
    services.bump_incident(inc)
    _update_notification_status_after_notice_change(inc)
    return success(notice)


# ---------------------------------------------------------------------------
# mailing batches
# ---------------------------------------------------------------------------
@app.route("/incidents/<id>/mailing-batches", methods=["POST"])
def create_batch(id):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    body = get_body()
    notice_id = req_str(body, "notice_id")
    notice = store.notices.get(notice_id)
    if notice is None or notice["incident_id"] != id:
        raise errors.not_found("notice_id not found in this incident")
    vendor = req_str(body, "vendor_code")
    ship_date = req_dt(body, "scheduled_ship_date")
    expected = body.get("expected_incident_version")
    if expected is None:
        raise errors.invalid_request("expected_incident_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_incident_version must be an integer")
    if expected != inc["version"]:
        raise errors.stale_version()
    batch = stamp_new({
        "incident_id": id,
        "notice_id": notice_id,
        "vendor_code": vendor,
        "recipient_count": 0,
        "scheduled_ship_date": clock.iso(ship_date),
        "status": "QUEUED",
    })
    store.mailing_batches[batch["id"]] = batch
    if inc["notification_status"] == "APPROVED":
        inc["notification_status"] = "DISPATCHING"
    services.bump_incident(inc)
    return success(batch, status=201)


@app.route("/incidents/<id>/mailing-batches", methods=["GET"])
def list_batches(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [b for b in store.mailing_batches.values() if b["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    return paginate(items)


@app.route("/incidents/<id>/mailing-batches/<batchId>", methods=["GET"])
def get_batch(id, batchId):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    batch = get_child_or_404(store.mailing_batches, batchId, id, "mailing batch")
    return success(batch)


@app.route("/incidents/<id>/mailing-batches/<batchId>/start-production", methods=["POST"])
def start_production(id, batchId):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    batch = get_child_or_404(store.mailing_batches, batchId, id, "mailing batch")
    if batch["status"] != "QUEUED":
        raise errors.invalid_state("batch must be QUEUED to start production")
    notice = store.notices.get(batch["notice_id"])
    if notice is None or notice["status"] != "LOCKED_FOR_MAIL":
        raise errors.invalid_state("notice must be LOCKED_FOR_MAIL")
    if inc["notification_status"] != "DISPATCHING":
        raise errors.invalid_state("incident notification_status must be DISPATCHING")
    # transition VERIFIED subjects in batch scope -> NOTICE_QUEUED
    # batch scope: subjects whose jurisdiction matches the notice's jurisdiction
    je_id = notice["jurisdiction_evaluation_id"]
    je = store.jurisdiction_evaluations.get(je_id)
    state_code = je["state_code"] if je else None
    transitioned = 0
    for subj in store.affected_subjects.values():
        if subj["incident_id"] != id or subj["status"] != "VERIFIED":
            continue
        if state_code is not None and subj["residence_state_code"] != state_code:
            continue
        subj["status"] = "NOTICE_QUEUED"
        subj["_queued_by_batch"] = batchId
        services.bump_row(subj)
        transitioned += 1
    batch["recipient_count"] = transitioned
    batch["status"] = "IN_PRODUCTION"
    services.bump_row(batch)
    services.recompute_incident_counters(inc)
    services.recompute_active_plan_seats(inc)
    services.bump_incident(inc)
    return success(batch)


@app.route("/incidents/<id>/mailing-batches/<batchId>/mark-shipped", methods=["POST"])
def mark_shipped(id, batchId):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    batch = get_child_or_404(store.mailing_batches, batchId, id, "mailing batch")
    if batch["status"] != "IN_PRODUCTION":
        raise errors.invalid_state("batch must be IN_PRODUCTION to mark shipped")
    if clock.parse_iso(batch["scheduled_ship_date"]) > clock.now():
        raise errors.deadline_passed("scheduled_ship_date is in the future")
    for subj in store.affected_subjects.values():
        if subj["incident_id"] == id and subj.get("_queued_by_batch") == batchId and subj["status"] == "NOTICE_QUEUED":
            subj["status"] = "NOTIFIED"
            services.bump_row(subj)
    batch["status"] = "SHIPPED"
    services.bump_row(batch)
    services.recompute_incident_counters(inc)
    if (inc["total_pending_subjects"] == 0
            and inc["total_affected_subjects"] == inc["total_notified_subjects"]
            and inc["notification_status"] == "DISPATCHING"):
        inc["notification_status"] = "COMPLETED"
    services.bump_incident(inc)
    return success(batch)


@app.route("/incidents/<id>/mailing-batches/<batchId>/confirm-delivery", methods=["POST"])
def confirm_delivery(id, batchId):
    require_role("PrivacyCounsel")
    get_incident_or_404(id)
    batch = get_child_or_404(store.mailing_batches, batchId, id, "mailing batch")
    if batch["status"] != "SHIPPED":
        raise errors.invalid_state("batch must be SHIPPED to confirm delivery")
    batch["status"] = "DELIVERED_CONFIRMED"
    services.bump_row(batch)
    return success(batch)


@app.route("/incidents/<id>/mailing-batches/<batchId>/fail", methods=["POST"])
def fail_batch(id, batchId):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    batch = get_child_or_404(store.mailing_batches, batchId, id, "mailing batch")
    if batch["status"] != "QUEUED":
        raise errors.invalid_state("batch must be QUEUED to fail")
    batch["status"] = "FAILED"
    services.bump_row(batch)
    # if no other active batch pins the notice, notice returns to APPROVED
    notice = store.notices.get(batch["notice_id"])
    if notice and notice["status"] == "LOCKED_FOR_MAIL":
        still_pinned = any(
            b for b in store.mailing_batches.values()
            if b["notice_id"] == notice["id"] and b["id"] != batchId
            and b["status"] in ("QUEUED", "IN_PRODUCTION")
        )
        if not still_pinned:
            notice["status"] = "APPROVED"
            services.bump_row(notice)
    services.bump_incident(inc)
    return success(batch)


# ---------------------------------------------------------------------------
# credit monitoring offers
# ---------------------------------------------------------------------------
@app.route("/incidents/<id>/credit-monitoring-offers", methods=["POST"])
def create_offer(id):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    body = get_body()
    subject_id = req_str(body, "affected_subject_id")
    subject = store.affected_subjects.get(subject_id)
    if subject is None or subject["incident_id"] != id:
        raise errors.not_found("affected_subject_id not found in this incident")
    vendor = req_str(body, "vendor_code")
    term = req_int(body, "term_months")
    unit_cost = req_int(body, "unit_cost_cents")
    if term not in (12, 24):
        raise errors.invalid_request("term_months must be 12 or 24")
    if unit_cost <= 0:
        raise errors.invalid_request("unit_cost_cents must be > 0")
    active = any(
        o for o in store.credit_monitoring_offers.values()
        if o["affected_subject_id"] == subject_id and o["status"] == "ISSUED"
    )
    if active:
        raise errors.offer_active()
    # expires_at = determination_at + 90 days; determination_at = incident confirm time.
    # Track incident confirmed timestamp; fall back to now if not confirmed yet.
    det = inc.get("_confirmed_at")
    base = clock.parse_iso(det) if det else clock.now()
    from datetime import timedelta
    expires = base + timedelta(days=90)
    offer = stamp_new({
        "incident_id": id,
        "affected_subject_id": subject_id,
        "vendor_code": vendor,
        "term_months": term,
        "unit_cost_cents": unit_cost,
        "offer_code": "OFFER-" + new_id().replace("-", "")[:16].upper(),
        "expires_at": clock.iso(expires),
        "status": "ISSUED",
    })
    store.credit_monitoring_offers[offer["id"]] = offer
    subject["credit_monitoring_status"] = "OFFERED_PENDING"
    subject["offered_at"] = clock.iso(clock.now())
    services.bump_row(subject)
    services.recompute_incident_counters(inc)
    services.bump_incident(inc)
    return success(offer, status=201)


def _offer_viewable(offer, user_id, role):
    if role == "AffectedSubjectRole":
        return offer["affected_subject_id"] == user_id
    return True


@app.route("/incidents/<id>/credit-monitoring-offers", methods=["GET"])
def list_offers(id):
    user_id, role = require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "AffectedSubjectRole")
    get_incident_or_404(id)
    items = [o for o in store.credit_monitoring_offers.values() if o["incident_id"] == id]
    if role == "AffectedSubjectRole":
        items = [o for o in items if o["affected_subject_id"] == user_id]
    sid = request.args.get("affected_subject_id")
    if sid:
        items = [o for o in items if o["affected_subject_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [o for o in items if o["status"] == status]
    return paginate(items)


@app.route("/incidents/<id>/credit-monitoring-offers/<offerId>", methods=["GET"])
def get_offer(id, offerId):
    user_id, role = require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "AffectedSubjectRole")
    get_incident_or_404(id)
    offer = get_child_or_404(store.credit_monitoring_offers, offerId, id, "offer")
    if not _offer_viewable(offer, user_id, role):
        raise errors.not_found("offer not found")
    return success(offer)


@app.route("/incidents/<id>/credit-monitoring-offers/<offerId>/redeem", methods=["POST"])
def redeem_offer(id, offerId):
    user_id, role = require_role("AffectedSubjectRole")
    inc = get_incident_or_404(id)
    offer = get_child_or_404(store.credit_monitoring_offers, offerId, id, "offer")
    if offer["affected_subject_id"] != user_id:
        raise errors.forbidden("subjects may only redeem their own offers")
    if offer["status"] != "ISSUED":
        raise errors.invalid_state("offer must be ISSUED to redeem")
    if clock.parse_iso(offer["expires_at"]) <= clock.now():
        raise errors.deadline_passed("offer has expired")
    offer["status"] = "REDEEMED"
    services.bump_row(offer)
    subject = store.affected_subjects.get(offer["affected_subject_id"])
    if subject:
        subject["credit_monitoring_status"] = "ENROLLED"
        services.bump_row(subject)
    services.recompute_incident_counters(inc)
    services.bump_incident(inc)
    return success(offer)


@app.route("/incidents/<id>/credit-monitoring-offers/<offerId>/decline", methods=["POST"])
def decline_offer(id, offerId):
    user_id, role = require_role("AffectedSubjectRole")
    inc = get_incident_or_404(id)
    offer = get_child_or_404(store.credit_monitoring_offers, offerId, id, "offer")
    if offer["affected_subject_id"] != user_id:
        raise errors.forbidden("subjects may only decline their own offers")
    if offer["status"] != "ISSUED":
        raise errors.invalid_state("offer must be ISSUED to decline")
    offer["status"] = "DECLINED"
    services.bump_row(offer)
    subject = store.affected_subjects.get(offer["affected_subject_id"])
    if subject:
        subject["credit_monitoring_status"] = "DECLINED"
        services.bump_row(subject)
    services.recompute_incident_counters(inc)
    services.bump_incident(inc)
    return success(offer)


@app.route("/incidents/<id>/credit-monitoring-offers/<offerId>/cancel", methods=["POST"])
def cancel_offer(id, offerId):
    require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    offer = get_child_or_404(store.credit_monitoring_offers, offerId, id, "offer")
    if offer["status"] != "ISSUED":
        raise errors.invalid_state("offer must be ISSUED to cancel")
    if inc["notification_status"] == "COMPLETED":
        raise errors.invalid_state("cannot cancel after notification COMPLETED")
    offer["status"] = "CANCELLED"
    offer["cancelled_at"] = clock.iso(clock.now())
    services.bump_row(offer)
    subject = store.affected_subjects.get(offer["affected_subject_id"])
    if subject:
        subject["credit_monitoring_status"] = "NOT_OFFERED"
        services.bump_row(subject)
    services.recompute_incident_counters(inc)
    return success(offer)


# ---------------------------------------------------------------------------
# call center staffing plans
# ---------------------------------------------------------------------------
def _intervals_overlap_strict(a_from, a_until, b_from, b_until):
    return a_from < b_until and b_from < a_until


@app.route("/incidents/<id>/call-center-staffing-plans", methods=["POST"])
def create_plan(id):
    require_role("IncidentCommander")
    inc = get_incident_or_404(id)
    body = get_body()
    eff_from = req_dt(body, "effective_from")
    eff_until = req_dt(body, "effective_until")
    langs = req_list(body, "languages_supported")
    if not eff_from < eff_until:
        raise errors.staffing_overlap("effective_from must be strictly earlier than effective_until")
    # strict-overlap rejection against other ACTIVE plans
    for p in store.call_center_plans.values():
        if p["incident_id"] != id or p["status"] != "ACTIVE":
            continue
        p_from = clock.parse_iso(p["effective_from"])
        p_until = clock.parse_iso(p["effective_until"])
        if _intervals_overlap_strict(eff_from, eff_until, p_from, p_until):
            raise errors.staffing_overlap("plan interval overlaps an existing ACTIVE plan")
    seats = services.compute_seats(inc["total_pending_subjects"], inc["severity"], langs)
    if seats < 2:
        raise errors.invalid_request("seats_required must be >= 2")
    plan = stamp_new({
        "incident_id": id,
        "effective_from": clock.iso(eff_from),
        "effective_until": clock.iso(eff_until),
        "seats_required": seats,
        "languages_supported": langs,
        "status": "ACTIVE",
    })
    store.call_center_plans[plan["id"]] = plan
    # supersede strictly-overlapping ACTIVE plans (new from >= cur from and new from < cur until)
    for p in store.call_center_plans.values():
        if p["incident_id"] != id or p["status"] != "ACTIVE" or p["id"] == plan["id"]:
            continue
        p_from = clock.parse_iso(p["effective_from"])
        p_until = clock.parse_iso(p["effective_until"])
        if eff_from >= p_from and eff_from < p_until:
            p["status"] = "SUPERSEDED"
            services.bump_row(p)
    services.bump_incident(inc)
    return success(plan, status=201)


@app.route("/incidents/<id>/call-center-staffing-plans", methods=["GET"])
def list_plans(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [p for p in store.call_center_plans.values() if p["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    return paginate(items)


@app.route("/incidents/<id>/call-center-staffing-plans/<planId>", methods=["GET"])
def get_plan(id, planId):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    plan = get_child_or_404(store.call_center_plans, planId, id, "staffing plan")
    return success(plan)


@app.route("/incidents/<id>/call-center-staffing-plans/<planId>/close", methods=["POST"])
def close_plan(id, planId):
    require_role("IncidentCommander")
    inc = get_incident_or_404(id)
    plan = get_child_or_404(store.call_center_plans, planId, id, "staffing plan")
    if plan["status"] != "ACTIVE":
        raise errors.invalid_state("plan must be ACTIVE to close")
    if inc["notification_status"] != "COMPLETED":
        raise errors.invalid_state("incident notification_status must be COMPLETED to close plan")
    plan["status"] = "CLOSED"
    services.bump_row(plan)
    return success(plan)


# ---------------------------------------------------------------------------
# regulator submissions
# ---------------------------------------------------------------------------
SUBMISSION_CHANNELS = {"PORTAL", "EMAIL", "CERTIFIED_MAIL"}


@app.route("/incidents/<id>/regulator-submissions", methods=["POST"])
def create_submission(id):
    user_id, _ = require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    body = get_body()
    je_id = req_str(body, "jurisdiction_evaluation_id")
    je = store.jurisdiction_evaluations.get(je_id)
    if je is None or je["incident_id"] != id:
        raise errors.not_found("jurisdiction_evaluation_id not found in this incident")
    notice_id = req_str(body, "notice_id")
    notice = store.notices.get(notice_id)
    if notice is None or notice["incident_id"] != id:
        raise errors.not_found("notice_id not found in this incident")
    channel = req_str(body, "submission_channel")
    if channel not in SUBMISSION_CHANNELS:
        raise errors.invalid_request("invalid submission_channel")
    sub = stamp_new({
        "incident_id": id,
        "jurisdiction_evaluation_id": je_id,
        "notice_id": notice_id,
        "submission_channel": channel,
        "submitted_at": None,
        "status": "DRAFT",
        "_submitted_by_user_id": None,
    })
    store.regulator_submissions[sub["id"]] = sub
    services.bump_incident(inc)
    return success(sub, status=201)


@app.route("/incidents/<id>/regulator-submissions", methods=["GET"])
def list_submissions(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [s for s in store.regulator_submissions.values() if s["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return paginate(items)


@app.route("/incidents/<id>/regulator-submissions/<subId>", methods=["GET"])
def get_submission(id, subId):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    sub = get_child_or_404(store.regulator_submissions, subId, id, "regulator submission")
    return success(sub)


@app.route("/incidents/<id>/regulator-submissions/<subId>/submit", methods=["POST"])
def submit_submission(id, subId):
    user_id, _ = require_role("PrivacyCounsel")
    inc = get_incident_or_404(id)
    sub = get_child_or_404(store.regulator_submissions, subId, id, "regulator submission")
    if sub["status"] != "DRAFT":
        raise errors.invalid_state("submission must be DRAFT to submit")
    notice = store.notices.get(sub["notice_id"])
    if notice is None or notice["status"] not in ("APPROVED", "LOCKED_FOR_MAIL"):
        raise errors.invalid_state("attached notice must be APPROVED or LOCKED_FOR_MAIL")
    je = store.jurisdiction_evaluations.get(sub["jurisdiction_evaluation_id"])
    if je is None or not je["requires_ag_notification"]:
        raise errors.invalid_state("jurisdiction does not require AG notification")
    if je["status"] != "TRIGGERED":
        raise errors.invalid_state("jurisdiction evaluation must be TRIGGERED")
    sub["status"] = "SUBMITTED"
    sub["submitted_at"] = clock.iso(clock.now())
    sub["_submitted_by_user_id"] = user_id
    services.bump_row(sub)
    services.bump_incident(inc)
    return success(sub)


@app.route("/incidents/<id>/regulator-submissions/<subId>/acknowledge", methods=["POST"])
def ack_submission(id, subId):
    require_role("PrivacyCounsel")
    get_incident_or_404(id)
    sub = get_child_or_404(store.regulator_submissions, subId, id, "regulator submission")
    if sub["status"] != "SUBMITTED":
        raise errors.invalid_state("submission must be SUBMITTED to acknowledge")
    sub["status"] = "ACKNOWLEDGED"
    services.bump_row(sub)
    return success(sub)


@app.route("/incidents/<id>/regulator-submissions/<subId>/open-inquiry", methods=["POST"])
def open_inquiry(id, subId):
    require_role("PrivacyCounsel")
    get_incident_or_404(id)
    sub = get_child_or_404(store.regulator_submissions, subId, id, "regulator submission")
    if sub["status"] != "ACKNOWLEDGED":
        raise errors.invalid_state("submission must be ACKNOWLEDGED to open inquiry")
    sub["status"] = "INQUIRY_OPEN"
    services.bump_row(sub)
    return success(sub)


@app.route("/incidents/<id>/regulator-submissions/<subId>/respond-inquiry", methods=["POST"])
def respond_inquiry(id, subId):
    user_id, _ = require_role("GeneralCounsel")
    get_incident_or_404(id)
    sub = get_child_or_404(store.regulator_submissions, subId, id, "regulator submission")
    if sub["status"] != "INQUIRY_OPEN":
        raise errors.invalid_state("submission must be INQUIRY_OPEN to respond")
    if sub.get("_submitted_by_user_id") == user_id:
        raise errors.segregation("responder must differ from original submitter")
    sub["status"] = "INQUIRY_RESPONDED"
    services.bump_row(sub)
    return success(sub)


@app.route("/incidents/<id>/regulator-submissions/<subId>/close", methods=["POST"])
def close_submission(id, subId):
    require_role("PrivacyCounsel")
    get_incident_or_404(id)
    sub = get_child_or_404(store.regulator_submissions, subId, id, "regulator submission")
    if sub["status"] not in ("ACKNOWLEDGED", "INQUIRY_RESPONDED"):
        raise errors.invalid_state("submission must be ACKNOWLEDGED or INQUIRY_RESPONDED to close")
    sub["status"] = "CLOSED"
    services.bump_row(sub)
    return success(sub)


# ---------------------------------------------------------------------------
# remediation actions
# ---------------------------------------------------------------------------
REMEDIATION_CATEGORIES = {"TECHNICAL", "PROCESS", "TRAINING", "VENDOR", "LEGAL"}


@app.route("/incidents/<id>/remediation-actions", methods=["POST"])
def create_action(id):
    require_role("IncidentCommander")
    inc = get_incident_or_404(id)
    body = get_body()
    title = req_str(body, "title")
    category = req_str(body, "category")
    if category not in REMEDIATION_CATEGORIES:
        raise errors.invalid_request("invalid category")
    owner = req_str(body, "owner_user_id")
    due_at = req_dt(body, "due_at")
    action = stamp_new({
        "incident_id": id,
        "title": title,
        "category": category,
        "owner_user_id": owner,
        "due_at": clock.iso(due_at),
        "completed_at": None,
        "status": "OPEN",
    })
    store.remediation_actions[action["id"]] = action
    services.bump_incident(inc)
    return success(action, status=201)


@app.route("/incidents/<id>/remediation-actions", methods=["GET"])
def list_actions(id):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    items = [a for a in store.remediation_actions.values() if a["incident_id"] == id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    cat = request.args.get("category")
    if cat:
        items = [a for a in items if a["category"] == cat]
    return paginate(items)


@app.route("/incidents/<id>/remediation-actions/<actionId>", methods=["GET"])
def get_action(id, actionId):
    require_role("IncidentCommander", "ForensicLead", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    action = get_child_or_404(store.remediation_actions, actionId, id, "remediation action")
    return success(action)


@app.route("/incidents/<id>/remediation-actions/<actionId>/start", methods=["POST"])
def start_action(id, actionId):
    require_role("IncidentCommander")
    get_incident_or_404(id)
    action = get_child_or_404(store.remediation_actions, actionId, id, "remediation action")
    if action["status"] != "OPEN":
        raise errors.invalid_state("action must be OPEN to start")
    action["status"] = "IN_PROGRESS"
    services.bump_row(action)
    return success(action)


@app.route("/incidents/<id>/remediation-actions/<actionId>/complete", methods=["POST"])
def complete_action(id, actionId):
    require_role("IncidentCommander")
    get_incident_or_404(id)
    action = get_child_or_404(store.remediation_actions, actionId, id, "remediation action")
    if action["status"] != "IN_PROGRESS":
        raise errors.invalid_state("action must be IN_PROGRESS to complete")
    action["status"] = "COMPLETED"
    action["completed_at"] = clock.iso(clock.now())
    services.bump_row(action)
    return success(action)


@app.route("/incidents/<id>/remediation-actions/<actionId>/verify", methods=["POST"])
def verify_action(id, actionId):
    user_id, _ = require_role("GeneralCounsel")
    inc = get_incident_or_404(id)
    action = get_child_or_404(store.remediation_actions, actionId, id, "remediation action")
    if action["status"] != "COMPLETED":
        raise errors.invalid_state("action must be COMPLETED to verify")
    if action["owner_user_id"] == user_id:
        raise errors.segregation("verifier must differ from action owner")
    action["status"] = "VERIFIED"
    services.bump_row(action)
    all_done = all(
        a["status"] in ("VERIFIED", "CANCELLED")
        for a in store.remediation_actions.values()
        if a["incident_id"] == id
    )
    if all_done:
        inc["remediation_status"] = "VERIFIED"
        services.bump_incident(inc)
    return success(action)


@app.route("/incidents/<id>/remediation-actions/<actionId>/cancel", methods=["POST"])
def cancel_action(id, actionId):
    require_role("IncidentCommander")
    get_incident_or_404(id)
    action = get_child_or_404(store.remediation_actions, actionId, id, "remediation action")
    if action["status"] != "OPEN":
        raise errors.invalid_state("action must be OPEN to cancel")
    action["status"] = "CANCELLED"
    services.bump_row(action)
    return success(action)


# ---------------------------------------------------------------------------
# cost summary
# ---------------------------------------------------------------------------
@app.route("/incidents/<id>/cost-summary", methods=["GET"])
def cost_summary(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    get_incident_or_404(id)
    total, count = services.credit_monitoring_cost(id)
    return success({"credit_monitoring_cost_cents": total, "offer_count": count})


# ---------------------------------------------------------------------------
# flat read-only endpoints
# ---------------------------------------------------------------------------
@app.route("/notices", methods=["GET"])
def flat_notices():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    items = list(store.notices.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [n for n in items if n["incident_id"] == iid]
    je = request.args.get("jurisdiction_evaluation_id")
    if je:
        items = [n for n in items if n["jurisdiction_evaluation_id"] == je]
    sup = request.args.get("supersedes_notice_id")
    if sup:
        items = [n for n in items if n.get("supersedes_notice_id") == sup]
    status = request.args.get("status")
    if status:
        items = [n for n in items if n["status"] == status]
    return paginate(items)


@app.route("/notices/<id>", methods=["GET"])
def flat_notice(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    return success(get_flat_or_404(store.notices, id, "notice"))


@app.route("/mailing-batches", methods=["GET"])
def flat_batches():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    items = list(store.mailing_batches.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [b for b in items if b["incident_id"] == iid]
    nid = request.args.get("notice_id")
    if nid:
        items = [b for b in items if b["notice_id"] == nid]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    return paginate(items)


@app.route("/mailing-batches/<id>", methods=["GET"])
def flat_batch(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    return success(get_flat_or_404(store.mailing_batches, id, "mailing batch"))


@app.route("/credit-monitoring-offers", methods=["GET"])
def flat_offers():
    user_id, role = require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "AffectedSubjectRole")
    items = list(store.credit_monitoring_offers.values())
    if role == "AffectedSubjectRole":
        items = [o for o in items if o["affected_subject_id"] == user_id]
    iid = request.args.get("incident_id")
    if iid:
        items = [o for o in items if o["incident_id"] == iid]
    sid = request.args.get("affected_subject_id")
    if sid:
        items = [o for o in items if o["affected_subject_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [o for o in items if o["status"] == status]
    return paginate(items)


@app.route("/credit-monitoring-offers/<id>", methods=["GET"])
def flat_offer(id):
    user_id, role = require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "AffectedSubjectRole")
    offer = get_flat_or_404(store.credit_monitoring_offers, id, "offer")
    if not _offer_viewable(offer, user_id, role):
        raise errors.not_found("offer not found")
    return success(offer)


@app.route("/regulator-submissions", methods=["GET"])
def flat_submissions():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    items = list(store.regulator_submissions.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [s for s in items if s["incident_id"] == iid]
    je = request.args.get("jurisdiction_evaluation_id")
    if je:
        items = [s for s in items if s["jurisdiction_evaluation_id"] == je]
    nid = request.args.get("notice_id")
    if nid:
        items = [s for s in items if s["notice_id"] == nid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return paginate(items)


@app.route("/regulator-submissions/<id>", methods=["GET"])
def flat_submission(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    return success(get_flat_or_404(store.regulator_submissions, id, "regulator submission"))


@app.route("/jurisdiction-evaluations", methods=["GET"])
def flat_jes():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "DataAnalyst", "ForensicLead")
    items = list(store.jurisdiction_evaluations.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [j for j in items if j["incident_id"] == iid]
    status = request.args.get("status")
    if status:
        items = [j for j in items if j["status"] == status]
    return paginate(items)


@app.route("/jurisdiction-evaluations/<id>", methods=["GET"])
def flat_je(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "DataAnalyst", "ForensicLead")
    return success(get_flat_or_404(store.jurisdiction_evaluations, id, "jurisdiction evaluation"))


@app.route("/affected-subjects", methods=["GET"])
def flat_subjects():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "DataAnalyst")
    items = list(store.affected_subjects.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [s for s in items if s["incident_id"] == iid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    st = request.args.get("residence_state_code")
    if st:
        items = [s for s in items if s["residence_state_code"] == st]
    return paginate(items)


@app.route("/affected-subjects/<id>", methods=["GET"])
def flat_subject(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "DataAnalyst")
    return success(get_flat_or_404(store.affected_subjects, id, "affected subject"))


@app.route("/evidence-items", methods=["GET"])
def flat_evidence():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "ForensicLead")
    items = list(store.evidence_items.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [e for e in items if e["incident_id"] == iid]
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    return paginate(items)


@app.route("/evidence-items/<id>", methods=["GET"])
def flat_evidence_item(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "ForensicLead")
    return success(get_flat_or_404(store.evidence_items, id, "evidence item"))


@app.route("/forensic-scopes", methods=["GET"])
def flat_scopes():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "ForensicLead")
    items = list(store.forensic_scopes.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [s for s in items if s["incident_id"] == iid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return paginate(items)


@app.route("/forensic-scopes/<id>", methods=["GET"])
def flat_scope(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "ForensicLead")
    return success(get_flat_or_404(store.forensic_scopes, id, "forensic scope"))


@app.route("/remediation-actions", methods=["GET"])
def flat_actions():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "ForensicLead")
    items = list(store.remediation_actions.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [a for a in items if a["incident_id"] == iid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    cat = request.args.get("category")
    if cat:
        items = [a for a in items if a["category"] == cat]
    return paginate(items)


@app.route("/remediation-actions/<id>", methods=["GET"])
def flat_action(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor", "ForensicLead")
    return success(get_flat_or_404(store.remediation_actions, id, "remediation action"))


@app.route("/call-center-staffing-plans", methods=["GET"])
def flat_plans():
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    items = list(store.call_center_plans.values())
    iid = request.args.get("incident_id")
    if iid:
        items = [p for p in items if p["incident_id"] == iid]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    return paginate(items)


@app.route("/call-center-staffing-plans/<id>", methods=["GET"])
def flat_plan(id):
    require_role("IncidentCommander", "PrivacyCounsel", "GeneralCounsel", "Auditor")
    return success(get_flat_or_404(store.call_center_plans, id, "staffing plan"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
