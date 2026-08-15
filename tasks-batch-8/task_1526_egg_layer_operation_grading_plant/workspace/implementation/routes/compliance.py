"""Salmonella tests (quarantine cascade), compliance audits, recalls."""
from flask import Blueprint, request

from db import STORE, new_record, today, touch
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_SOD_VIOLATION,
    ERR_SAMPLING_TOO_SOON, ERR_AUDIT_INTERVAL_TOO_SOON, ERR_RECALL_ACTIVE,
)
from middleware import endpoint, ALL_ROLES
from response import ok, paginate, pub
from util import req_str, req_int, req_enum, req_date, opt_str
from services.domain import (
    get_entity, farm_of_flock, suspend_contract, recompute_posture,
    contract_held_allocated_dozen, COLLECT_MIN_GAP_DAYS,
)

bp = Blueprint("compliance", __name__)

TEST_TYPES = {"ENVIRONMENTAL", "EGG_POOL"}
RESULTS = {"NEGATIVE", "POSITIVE"}
STANDARDS = {"USDA_CAGE_FREE", "PASTURE_RAISED", "FDA_EGG_SAFETY"}
OUTCOMES = {"PASSED", "FAILED"}
REASONS = {"SALMONELLA", "QUALITY", "LABELING"}
COLLECTED_PLUS = ("COLLECTED", "RESULTED", "CLEARED", "RESOLVED")


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Salmonella tests
# ---------------------------------------------------------------------------
@bp.route("/api/salmonella-tests", methods=["POST"])
@endpoint(["QualityGrader", "ComplianceOfficer"])
def create_salmonella_test(actor):
    body = _body()
    flock_id = body.get("flock_id")
    if isinstance(flock_id, str) and flock_id:
        get_entity("flocks", flock_id, "Flock")
    flock_id = req_str(body, "flock_id")
    get_entity("flocks", flock_id, "Flock")
    test_type = req_enum(body, "test_type", TEST_TYPES)
    scheduled_date = req_date(body, "scheduled_date")
    if scheduled_date < today():
        raise ApiError(ERR_VALIDATION, 400, "scheduled_date must not be earlier than the clock date")
    rec = new_record()
    rec.update({
        "flock_id": flock_id,
        "test_type": test_type,
        "scheduled_date": scheduled_date,
        "status": "SCHEDULED",
        "collected_date": None,
        "collected_by": None,
        "result": None,
        "resulted_by": None,
    })
    STORE["salmonella_tests"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.route("/api/salmonella-tests/<salmonellaTestId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_salmonella_test(salmonellaTestId, actor):
    return ok(pub(get_entity("salmonella_tests", salmonellaTestId, "SalmonellaTest")), status=200)


@bp.route("/api/salmonella-tests", methods=["GET"])
@endpoint(ALL_ROLES)
def list_salmonella_tests(actor):
    items = list(STORE["salmonella_tests"].values())
    flock_id = request.args.get("flock_id")
    status = request.args.get("status")
    test_type = request.args.get("test_type")
    if flock_id is not None:
        items = [t for t in items if t["flock_id"] == flock_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if test_type is not None:
        items = [t for t in items if t["test_type"] == test_type]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    return paginate(items, pub)


@bp.route("/api/salmonella-tests/<salmonellaTestId>/collect", methods=["POST"])
@endpoint(["QualityGrader"])
def collect_salmonella_test(salmonellaTestId, actor):
    test = get_entity("salmonella_tests", salmonellaTestId, "SalmonellaTest")
    if test["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Test must be SCHEDULED to collect")
    today_d = today()
    if today_d < test["scheduled_date"]:
        raise ApiError(ERR_VALIDATION, 400, "Clock date is before scheduled_date")
    # 7-day minimum gap between collections on the same house (7 exactly allowed).
    flock = STORE["flocks"][test["flock_id"]]
    house_id = flock["house_id"]
    house_flock_ids = {f["id"] for f in STORE["flocks"].values() if f["house_id"] == house_id}
    prior = [
        t for t in STORE["salmonella_tests"].values()
        if t["flock_id"] in house_flock_ids and t["id"] != test["id"]
        and t["status"] in COLLECTED_PLUS and t.get("collected_date") is not None
    ]
    if prior:
        last = max(t["collected_date"] for t in prior)
        if (today_d - last).days < COLLECT_MIN_GAP_DAYS:
            raise ApiError(ERR_SAMPLING_TOO_SOON, 409, "Collections on one house must be at least 7 days apart")
    test["status"] = "COLLECTED"
    test["collected_date"] = today_d
    test["collected_by"] = actor
    touch(test)
    return ok(pub(test), status=200)


@bp.route("/api/salmonella-tests/<salmonellaTestId>/record-result", methods=["POST"])
@endpoint(["QAManager"])
def record_salmonella_result(salmonellaTestId, actor):
    test = get_entity("salmonella_tests", salmonellaTestId, "SalmonellaTest")
    # Tier 3: SoD — result recorder must differ from collector.
    if test.get("collected_by") is not None and actor == test["collected_by"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Result recorder must differ from collector")
    body = _body()
    result = req_enum(body, "result", RESULTS)
    # Tier 6: COLLECTED -> RESULTED.
    if test["status"] != "COLLECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Test must be COLLECTED to record a result")
    test["result"] = result
    test["resulted_by"] = actor
    test["status"] = "RESULTED"
    touch(test)
    if result == "NEGATIVE":
        # RESULTED -> CLEARED automatically in the same request.
        test["status"] = "CLEARED"
        touch(test)
        return ok(pub(test), status=200)
    # POSITIVE: six-link cascade fires immediately in the same request.
    flock = STORE["flocks"][test["flock_id"]]
    farm = farm_of_flock(flock)
    # Link 1: flock quarantine.
    if flock["quarantine_status"] == "CLEAR":
        flock["quarantine_status"] = "QUARANTINED"
        touch(flock)
    # Link 2: every open lot of the flock with hold CLEAR -> HELD.
    held_lots = []
    for lot in sorted(STORE["lots"].values(), key=lambda l: l["_seq"]):
        if lot["flock_id"] == flock["id"] \
                and lot["lifecycle_status"] in ("FRESH", "RELEASED", "ALLOCATED") \
                and lot["hold_status"] == "CLEAR":
            lot["hold_status"] = "HELD"
            touch(lot)
            held_lots.append(lot)
    # Links 3-4: contracts with held allocated dozens suspend; DRAFT settlements void.
    for contract in list(STORE["contracts"].values()):
        if contract_held_allocated_dozen(contract) > 0:
            suspend_contract(contract)
    # Link 5: auto-create the recall scoped to this flock.
    rec = new_record()
    if held_lots:
        pack_dates = [l["pack_date"] for l in held_lots]
        win_start, win_end = min(pack_dates), max(pack_dates)
    else:
        win_start = win_end = today()
    rec.update({
        "farm_id": farm["id"],
        "salmonella_test_id": test["id"],
        "scope_flock_id": flock["id"],
        "reason": "SALMONELLA",
        "pack_window_start": win_start,
        "pack_window_end": win_end,
        "status": "INITIATED",
        "scoped_lot_count": None,
    })
    STORE["recalls"][rec["id"]] = rec
    # Link 6: farm posture -> SUSPENDED (cascades remaining ACTIVE contracts).
    recompute_posture(farm)
    return ok(pub(test), status=200)


# ---------------------------------------------------------------------------
# Compliance audits
# ---------------------------------------------------------------------------
@bp.route("/api/compliance-audits", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def create_audit(actor):
    body = _body()
    farm_id = body.get("farm_id")
    if isinstance(farm_id, str) and farm_id:
        get_entity("farms", farm_id, "Farm")
    farm_id = req_str(body, "farm_id")
    get_entity("farms", farm_id, "Farm")
    standard = req_enum(body, "standard", STANDARDS)
    audit_date = req_date(body, "audit_date")
    # Tier 10: >= 30 days from every non-terminal audit of the farm (30 allowed).
    for a in STORE["compliance_audits"].values():
        if a["farm_id"] != farm_id or a["status"] in ("CLOSED_PASSED", "CLOSED_FAILED"):
            continue
        if abs((audit_date - a["audit_date"]).days) < 30:
            raise ApiError(ERR_AUDIT_INTERVAL_TOO_SOON, 409, "audit_date is within 30 days of another non-terminal audit")
    rec = new_record()
    rec.update({
        "farm_id": farm_id,
        "standard": standard,
        "audit_date": audit_date,
        "status": "SCHEDULED",
        "findings_count": None,
        "corrective_actions_open": None,
        "outcome": None,
        "closed_date": None,
        "_closed_tick": 0,
    })
    STORE["compliance_audits"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.route("/api/compliance-audits/<complianceAuditId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_audit(complianceAuditId, actor):
    return ok(pub(get_entity("compliance_audits", complianceAuditId, "ComplianceAudit")), status=200)


@bp.route("/api/compliance-audits", methods=["GET"])
@endpoint(ALL_ROLES)
def list_audits(actor):
    items = list(STORE["compliance_audits"].values())
    farm_id = request.args.get("farm_id")
    status = request.args.get("status")
    if farm_id is not None:
        items = [a for a in items if a["farm_id"] == farm_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return paginate(items, pub)


@bp.route("/api/compliance-audits/<complianceAuditId>/start", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def start_audit(complianceAuditId, actor):
    audit = get_entity("compliance_audits", complianceAuditId, "ComplianceAudit")
    if audit["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Audit must be SCHEDULED to start")
    if today() < audit["audit_date"]:
        raise ApiError(ERR_VALIDATION, 400, "Clock date is before audit_date")
    audit["status"] = "IN_PROGRESS"
    touch(audit)
    return ok(pub(audit), status=200)


@bp.route("/api/compliance-audits/<complianceAuditId>/record-findings", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def record_findings(complianceAuditId, actor):
    audit = get_entity("compliance_audits", complianceAuditId, "ComplianceAudit")
    body = _body()
    findings_count = req_int(body, "findings_count", min_v=0)
    corrective_open = req_int(body, "corrective_actions_open", min_v=0)
    if audit["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Audit must be IN_PROGRESS to record findings")
    audit["findings_count"] = findings_count
    audit["corrective_actions_open"] = corrective_open
    audit["status"] = "FINDINGS_RECORDED"
    touch(audit)
    # Open corrective actions raise posture to WATCH (unless already SUSPENDED).
    recompute_posture(get_entity("farms", audit["farm_id"], "Farm"))
    return ok(pub(audit), status=200)


@bp.route("/api/compliance-audits/<complianceAuditId>/close", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def close_audit(complianceAuditId, actor):
    audit = get_entity("compliance_audits", complianceAuditId, "ComplianceAudit")
    body = _body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    if audit["status"] != "FINDINGS_RECORDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Audit must be FINDINGS_RECORDED to close")
    if outcome == "PASSED" and (audit.get("corrective_actions_open") or 0) != 0:
        raise ApiError(ERR_VALIDATION, 400, "corrective_actions_open must be 0 to close PASSED")
    audit["outcome"] = outcome
    audit["closed_date"] = today()
    audit["status"] = "CLOSED_PASSED" if outcome == "PASSED" else "CLOSED_FAILED"
    touch(audit)
    from db import next_tick
    audit["_closed_tick"] = next_tick()
    # FAILED: posture -> SUSPENDED cascades ACTIVE contracts (via recompute).
    recompute_posture(get_entity("farms", audit["farm_id"], "Farm"))
    return ok(pub(audit), status=200)


# ---------------------------------------------------------------------------
# Recalls
# ---------------------------------------------------------------------------
@bp.route("/api/recalls", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def create_recall(actor):
    body = _body()
    farm_id = body.get("farm_id")
    if isinstance(farm_id, str) and farm_id:
        get_entity("farms", farm_id, "Farm")
    scope_flock_id = body.get("scope_flock_id")
    if isinstance(scope_flock_id, str) and scope_flock_id:
        get_entity("flocks", scope_flock_id, "Flock")
    farm_id = req_str(body, "farm_id")
    get_entity("farms", farm_id, "Farm")
    reason = req_enum(body, "reason", REASONS)
    win_start = req_date(body, "pack_window_start")
    win_end = req_date(body, "pack_window_end")
    if win_start > win_end:
        raise ApiError(ERR_VALIDATION, 400, "pack_window_start must not be after pack_window_end")
    scope_flock_id = opt_str(body, "scope_flock_id")
    if scope_flock_id is not None:
        get_entity("flocks", scope_flock_id, "Flock")
    # Tier 9: one open recall per farm.
    for r in STORE["recalls"].values():
        if r["farm_id"] == farm_id and r["status"] in ("INITIATED", "SCOPED"):
            raise ApiError(ERR_RECALL_ACTIVE, 409, "Farm already has an open recall")
    rec = new_record()
    rec.update({
        "farm_id": farm_id,
        "salmonella_test_id": None,
        "scope_flock_id": scope_flock_id,
        "reason": reason,
        "pack_window_start": win_start,
        "pack_window_end": win_end,
        "status": "INITIATED",
        "scoped_lot_count": None,
    })
    STORE["recalls"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.route("/api/recalls/<recallId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_recall(recallId, actor):
    return ok(pub(get_entity("recalls", recallId, "Recall")), status=200)


@bp.route("/api/recalls", methods=["GET"])
@endpoint(ALL_ROLES)
def list_recalls(actor):
    items = list(STORE["recalls"].values())
    for param, field in (
        ("farm_id", "farm_id"), ("salmonella_test_id", "salmonella_test_id"),
        ("scope_flock_id", "scope_flock_id"), ("status", "status"),
    ):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(items, pub)


@bp.route("/api/recalls/<recallId>/scope", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def scope_recall(recallId, actor):
    recall = get_entity("recalls", recallId, "Recall")
    if recall["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Recall must be INITIATED to scope")
    # Sweep selector: farm match, optional flock scope, inclusive pack window,
    # lifecycle in {FRESH, RELEASED, ALLOCATED}; pack_date ASC, created_at ASC.
    swept = [
        l for l in STORE["lots"].values()
        if l["farm_id"] == recall["farm_id"]
        and (recall["scope_flock_id"] is None or l["flock_id"] == recall["scope_flock_id"])
        and recall["pack_window_start"] <= l["pack_date"] <= recall["pack_window_end"]
        and l["lifecycle_status"] in ("FRESH", "RELEASED", "ALLOCATED")
    ]
    swept.sort(key=lambda l: (l["pack_date"], l["created_at"], l["_seq"]))
    for lot in swept:
        if lot["lifecycle_status"] == "ALLOCATED" and lot.get("contract_id"):
            contract = STORE["contracts"].get(lot["contract_id"])
            lot["contract_id"] = None
            if contract is not None:
                touch(contract)
        lot["lifecycle_status"] = "RECALLED"
        lot["recall_id"] = recall["id"]
        touch(lot)
    recall["status"] = "SCOPED"
    recall["scoped_lot_count"] = len(swept)
    touch(recall)
    return ok(pub(recall), status=200)


@bp.route("/api/recalls/<recallId>/close", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def close_recall(recallId, actor):
    recall = get_entity("recalls", recallId, "Recall")
    if recall["status"] != "SCOPED":
        raise ApiError(ERR_INVALID_STATE, 409, "Recall must be SCOPED to close")
    # Unwind the quarantine: linked POSITIVE test -> RESOLVED; flock -> CLEAR.
    if recall.get("salmonella_test_id"):
        test = STORE["salmonella_tests"].get(recall["salmonella_test_id"])
        if test is not None and test["status"] == "RESULTED" and test.get("result") == "POSITIVE":
            test["status"] = "RESOLVED"
            touch(test)
            flock = STORE["flocks"].get(test["flock_id"])
            if flock is not None and flock["quarantine_status"] == "QUARANTINED":
                flock["quarantine_status"] = "CLEAR"
                touch(flock)
    recall["status"] = "CLOSED"
    touch(recall)
    recompute_posture(get_entity("farms", recall["farm_id"], "Farm"))
    return ok(pub(recall), status=200)
