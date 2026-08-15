"""
BIM Coordination & Clash Detection API — reference implementation.

Single-module Flask app; in-memory store. Boots cleanly from a fresh process.
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Enums / constants
# ---------------------------------------------------------------------------

PHASES = [
    "SCHEMATIC_DESIGN",
    "DESIGN_DEVELOPMENT",
    "CONSTRUCTION_DOCUMENTS",
    "CONSTRUCTION_ADMINISTRATION",
    "CLOSEOUT",
]

DISCIPLINES = [
    "ARCHITECTURAL",
    "STRUCTURAL",
    "MECHANICAL",
    "ELECTRICAL",
    "PLUMBING",
    "FIRE_PROTECTION",
]

SOFTWARE_PLATFORMS = ["REVIT", "TEKLA", "ARCHICAD", "IFC_ONLY"]
FILE_FORMATS = ["RVT", "IFC", "NWC", "DWG"]
TARGET_FORMATS = ["IFC", "NWC"]
FREEZE_PURPOSES = ["COORDINATION_FREEZE", "FABRICATION_HOLD", "HANDOVER_FREEZE"]
MIN_LOD_VALUES = [100, 200, 300, 350, 400, 500]
EXTRACTION_MODES = ["GROSS", "NET"]
HANDOVER_DECISIONS = ["ACCEPT", "REJECT"]

ROLES = [
    "VDCManager",
    "BIMCoordinator",
    "TradeModelAuthor",
    "LeadEngineer",
    "FabricationLead",
    "FacilitiesManager",
]

INTEROP_MATRIX = {
    "REVIT":    {"RVT": "NATIVE", "IFC": "CONVERTIBLE", "NWC": "CONVERTIBLE", "DWG": "INCOMPATIBLE"},
    "TEKLA":    {"IFC": "NATIVE", "NWC": "CONVERTIBLE", "DWG": "CONVERTIBLE", "RVT": "INCOMPATIBLE"},
    "ARCHICAD": {"IFC": "NATIVE", "DWG": "CONVERTIBLE", "RVT": "INCOMPATIBLE", "NWC": "INCOMPATIBLE"},
    "IFC_ONLY": {"IFC": "NATIVE", "RVT": "INCOMPATIBLE", "NWC": "INCOMPATIBLE", "DWG": "INCOMPATIBLE"},
}

CRITICAL_OVERLAP_MM = Decimal("50.0")
AS_BUILT_TOLERANCE_MM = Decimal("25.0")
AUDIT_ACCEPT_THRESHOLD = Decimal("70.0")
CRI_RELEASE_THRESHOLD = 85
CRI_HOLD_THRESHOLD = 60

BASE_HOURS = {"CRITICAL": Decimal("40"), "MAJOR": Decimal("16"), "MINOR": Decimal("4")}
SPANS_MULTIPLIER = Decimal("1.5")

TIER_A_FLOOR = Decimal("80")
TIER_B_FLOOR = Decimal("50")
PENALTY_A = Decimal("5")
PENALTY_B = Decimal("10")
PENALTY_C = Decimal("20")
PROBATION_THRESHOLD = Decimal("40")

FREEZE_GAP_SECONDS = 3600

W_LIFE_SAFETY = Decimal("0.5")
W_ENVELOPE = Decimal("0.3")
W_FINISH = Decimal("0.2")

W_CRITICAL = 25
W_MAJOR = 10
W_MINOR_UNASSIGNED = 5
W_OVERDUE_COMMITMENT = 15

OPEN_CLASH_STATUSES = {"NEW", "ASSIGNED", "RESOLVED", "REOPENED"}
UNASSIGNED_CLASH_STATUSES = {"NEW", "REOPENED"}

# ---------------------------------------------------------------------------
# In-memory data store (fresh on every boot)
# ---------------------------------------------------------------------------


class DB:
    def __init__(self):
        self.projects = {}
        self.lod_requirements = {}
        self.trade_partners = {}
        self.trade_models = {}
        self.federated_models = {}
        self.federated_model_members = {}
        self.freeze_windows = {}
        self.clash_runs = {}
        self.clash_issues = {}
        self.coordination_meetings = {}
        self.resolution_commitments = {}
        self.fabrication_packages = {}
        self.sign_offs = {}
        self.as_built_models = {}
        self.quantity_takeoffs = {}
        self.handover_packages = {}
        # Logical clock
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = DB()

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope helpers
# ---------------------------------------------------------------------------


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _now_iso():
    """ISO 8601 UTC with 3 fractional digits (wall clock for meta timestamps)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _logical_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(e):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def touch(rec):
    """Bump version + updated_at on mutation."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = _now_iso()


def init_common(rec):
    rec["id"] = new_id()
    rec["created_at"] = _now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    return rec


def parse_iso(s, field="timestamp"):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be an ISO 8601 string")
    txt = s.strip()
    # Accept trailing Z or +00:00
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
    except Exception:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # truncate to second precision for comparison purposes
    return dt


def parse_decimal(v, field="value"):
    if isinstance(v, bool) or v is None:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be a number")
    if isinstance(v, (int, float, Decimal)):
        try:
            return Decimal(str(v))
        except Exception:
            raise err("ERR_INVALID_REQUEST", 400, f"{field} must be a number")
    raise err("ERR_INVALID_REQUEST", 400, f"{field} must be a number")


def round_half_up_int(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1(d):
    return float(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_half_up_3(d):
    return d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


def get_auth():
    """Returns (user_id, role) or raises."""
    uid = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not uid or not role:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in ROLES:
        raise err("ERR_UNAUTHORIZED_ROLE", 403, f"Role {role} is not recognized")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED_ROLE", 403, f"Role {role} not admitted for this operation")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(items):
    """Apply limit/offset from query args, sorted by created_at ASC."""
    try:
        limit = int(request.args.get("limit", "10"))
    except Exception:
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except Exception:
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items_sorted = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items_sorted)
    page = items_sorted[offset : offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Project derived state (CRI, posture)
# ---------------------------------------------------------------------------


def recompute_project(project):
    """Recompute open_critical_count, open_major_count, unassigned_minor_count,
    overdue_commitment_count, coordination_readiness_index, coordination_posture.
    Mutates the project record (bumps version/updated_at)."""
    pid = project["id"]
    open_crit = 0
    open_maj = 0
    unass_min = 0
    for c in db.clash_issues.values():
        if c["project_id"] != pid:
            continue
        if c["status"] not in OPEN_CLASH_STATUSES:
            continue
        if c["severity"] == "CRITICAL":
            open_crit += 1
        elif c["severity"] == "MAJOR":
            open_maj += 1
        elif c["severity"] == "MINOR":
            if c["status"] in UNASSIGNED_CLASH_STATUSES:
                unass_min += 1
    overdue = 0
    now = db.logical_clock
    for cm in db.resolution_commitments.values():
        if cm["project_id"] != pid:
            continue
        if cm["status"] == "COMMITTED" and cm["_due_at"] < now:
            overdue += 1
    cri = 100 - W_CRITICAL * open_crit - W_MAJOR * open_maj - W_MINOR_UNASSIGNED * unass_min - W_OVERDUE_COMMITMENT * overdue
    if cri < 0:
        cri = 0
    # posture
    hold = cri < CRI_HOLD_THRESHOLD
    if not hold:
        # probation partner with >=1 assigned clash in {ASSIGNED, RESOLVED, REOPENED}
        prob_partner_ids = {
            p["id"] for p in db.trade_partners.values()
            if p["project_id"] == pid and p["status"] == "PROBATION"
        }
        if prob_partner_ids:
            for c in db.clash_issues.values():
                if c["project_id"] != pid:
                    continue
                if (
                    c.get("assigned_trade_partner_id") in prob_partner_ids
                    and c["status"] in ("ASSIGNED", "RESOLVED", "REOPENED")
                ):
                    hold = True
                    break
    posture = "COORDINATION_HOLD" if hold else "NORMAL"
    project["open_critical_count"] = open_crit
    project["open_major_count"] = open_maj
    project["unassigned_minor_count"] = unass_min
    project["overdue_commitment_count"] = overdue
    project["coordination_readiness_index"] = cri
    project["coordination_posture"] = posture
    touch(project)


def recompute_fed_open_critical(fed):
    cnt = 0
    for c in db.clash_issues.values():
        if c["federated_model_id"] == fed["id"] and c["status"] in OPEN_CLASH_STATUSES and c["severity"] == "CRITICAL":
            cnt += 1
    if fed.get("open_critical_count") != cnt:
        fed["open_critical_count"] = cnt
        touch(fed)


def project_by_id(pid):
    p = db.projects.get(pid)
    if not p:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "Project not found")
    return p


def trade_partner_by_id(tid):
    p = db.trade_partners.get(tid)
    if not p:
        raise err("ERR_TRADE_PARTNER_NOT_FOUND", 404, "TradePartner not found")
    return p


def trade_model_by_id(tid):
    m = db.trade_models.get(tid)
    if not m:
        raise err("ERR_TRADE_MODEL_NOT_FOUND", 404, "TradeModel not found")
    return m


def fed_model_by_id(fid):
    m = db.federated_models.get(fid)
    if not m:
        raise err("ERR_FEDERATED_MODEL_NOT_FOUND", 404, "FederatedModel not found")
    return m


def clash_run_by_id(rid):
    r = db.clash_runs.get(rid)
    if not r:
        raise err("ERR_CLASH_RUN_NOT_FOUND", 404, "ClashDetectionRun not found")
    return r


def clash_issue_by_id(cid):
    c = db.clash_issues.get(cid)
    if not c:
        raise err("ERR_CLASH_ISSUE_NOT_FOUND", 404, "ClashIssue not found")
    return c


def meeting_by_id(mid):
    m = db.coordination_meetings.get(mid)
    if not m:
        raise err("ERR_MEETING_NOT_FOUND", 404, "CoordinationMeeting not found")
    return m


def commitment_by_id(cid):
    c = db.resolution_commitments.get(cid)
    if not c:
        raise err("ERR_COMMITMENT_NOT_FOUND", 404, "ResolutionCommitment not found")
    return c


def package_by_id(pid):
    p = db.fabrication_packages.get(pid)
    if not p:
        raise err("ERR_PACKAGE_NOT_FOUND", 404, "FabricationPackage not found")
    return p


def signoff_by_id(sid):
    s = db.sign_offs.get(sid)
    if not s:
        raise err("ERR_SIGNOFF_NOT_FOUND", 404, "SignOff not found")
    return s


def as_built_by_id(aid):
    a = db.as_built_models.get(aid)
    if not a:
        raise err("ERR_AS_BUILT_NOT_FOUND", 404, "AsBuiltModel not found")
    return a


def takeoff_by_id(tid):
    t = db.quantity_takeoffs.get(tid)
    if not t:
        raise err("ERR_TAKEOFF_NOT_FOUND", 404, "QuantityTakeoff not found")
    return t


def handover_by_id(hid):
    h = db.handover_packages.get(hid)
    if not h:
        raise err("ERR_HANDOVER_NOT_FOUND", 404, "HandoverPackage not found")
    return h


# ---------------------------------------------------------------------------
# Serializers (strip internal fields starting with _)
# ---------------------------------------------------------------------------


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def compute_interop_status(platform, file_format):
    return INTEROP_MATRIX[platform][file_format]


def compute_severity(overlap_mm):
    """overlap_mm: Decimal"""
    if overlap_mm > CRITICAL_OVERLAP_MM:
        return "CRITICAL"
    if overlap_mm > Decimal("0.0"):
        return "MAJOR"
    return "MINOR"


def compute_submission_score(model):
    total = (
        model["life_safety_elements"]
        + model["envelope_elements"]
        + model["finish_elements"]
    )
    compliant = (
        model["life_safety_compliant"]
        + model["envelope_compliant"]
        + model["finish_compliant"]
    )
    if total == 0:
        return None
    score = Decimal("100") * Decimal(compliant) / Decimal(total)
    return round_half_up_1(score)


def compute_audit_score(model):
    classes = [
        (model["life_safety_elements"], model["life_safety_compliant"], W_LIFE_SAFETY),
        (model["envelope_elements"], model["envelope_compliant"], W_ENVELOPE),
        (model["finish_elements"], model["finish_compliant"], W_FINISH),
    ]
    included = [(e, c, w) for (e, c, w) in classes if e > 0]
    if not included:
        return None
    num = Decimal("0")
    den = Decimal("0")
    for e, c, w in included:
        num += w * (Decimal(c) / Decimal(e))
        den += w
    score = Decimal("100") * num / den
    return round_half_up_1(score)


def compute_provisional_cost(severity, spans_disciplines, hourly_rate_cents):
    base = BASE_HOURS[severity]
    mult = SPANS_MULTIPLIER if spans_disciplines else Decimal("1.0")
    cost = base * mult * Decimal(hourly_rate_cents)
    return round_half_up_int(cost)


def compute_actual_cost(actual_labor_hours, hourly_rate_cents):
    cost = Decimal(str(actual_labor_hours)) * Decimal(hourly_rate_cents)
    return round_half_up_int(cost)


def compute_quantity_total(extraction_mode, elements):
    """elements: list of dicts with Decimal gross_qty/deduction_qty.
    Returns a float with 3 decimal places (rendered)."""
    if extraction_mode == "GROSS":
        total = sum(e["_gross"] for e in elements)
        return round_half_up_3(total)
    # NET
    total = Decimal("0")
    for e in elements:
        net = e["_gross"] - e["_deduction"]
        total += round_half_up_3(net)
    return total  # already at 3 decimals


def apply_reliability_decay(partner):
    """Tier read from score BEFORE the breach."""
    before = Decimal(str(partner["reliability_score"]))
    if before >= TIER_A_FLOOR:
        penalty = PENALTY_A
    elif before >= TIER_B_FLOOR:
        penalty = PENALTY_B
    else:
        penalty = PENALTY_C
    after = before - penalty
    if after < 0:
        after = Decimal("0")
    partner["reliability_score"] = float(after.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    partner["breach_count"] = partner.get("breach_count", 0) + 1
    if after < PROBATION_THRESHOLD and partner["status"] == "ACTIVE":
        partner["status"] = "PROBATION"
    touch(partner)


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------


def packages_pinning_fed(fed_id):
    return [p for p in db.fabrication_packages.values() if p["federated_model_id"] == fed_id]


def recompute_package_signed_count(pkg):
    cnt = sum(
        1
        for s in db.sign_offs.values()
        if s["fabrication_package_id"] == pkg["id"] and s["status"] == "SIGNED"
    )
    if pkg.get("signed_count") != cnt:
        pkg["signed_count"] = cnt
        touch(pkg)
    return cnt


def maybe_regress_package(pkg):
    """If signed_count < required and status == READY_FOR_RELEASE, regress."""
    if pkg["status"] == "READY_FOR_RELEASE":
        if pkg["signed_count"] < pkg["required_signoff_count"]:
            pkg["status"] = "SIGNOFF_IN_PROGRESS"
            touch(pkg)


def maybe_advance_package(pkg):
    if pkg["status"] == "SIGNOFF_IN_PROGRESS":
        if pkg["signed_count"] >= pkg["required_signoff_count"]:
            pkg["status"] = "READY_FOR_RELEASE"
            touch(pkg)


def revoke_signed_signoffs_for_fed(fed_id):
    """CASCADE A link 3: every SIGNED SignOff whose fabrication_package pins this fed -> REVOKED."""
    affected_pkgs = set()
    for s in db.sign_offs.values():
        if s["status"] != "SIGNED":
            continue
        pkg = db.fabrication_packages.get(s["fabrication_package_id"])
        if not pkg:
            continue
        if pkg["federated_model_id"] != fed_id:
            continue
        s["status"] = "REVOKED"
        touch(s)
        affected_pkgs.add(pkg["id"])
    for pid in affected_pkgs:
        pkg = db.fabrication_packages[pid]
        recompute_package_signed_count(pkg)
        maybe_regress_package(pkg)


def unfreeze_fed(fed):
    """FROZEN -> ASSEMBLED, set is_stale, run sign-off revocation cascade."""
    if fed["status"] == "FROZEN":
        fed["status"] = "ASSEMBLED"
    fed["is_stale"] = True
    touch(fed)
    revoke_signed_signoffs_for_fed(fed["id"])


def supersede_fed(old_fed):
    """Supersede a non-terminal federated model. RELEASED keeps sign-offs (no revocation);
    FROZEN runs the unfreeze cascade (revocation + regression) before supersede."""
    st = old_fed["status"]
    if st in ("DRAFT", "ASSEMBLED"):
        old_fed["status"] = "SUPERSEDED"
        touch(old_fed)
    elif st == "FROZEN":
        # Same revocation cascade as unfreeze
        revoke_signed_signoffs_for_fed(old_fed["id"])
        old_fed["status"] = "SUPERSEDED"
        touch(old_fed)
    elif st == "RELEASED":
        # No revocation — issued record preserved
        old_fed["status"] = "SUPERSEDED"
        touch(old_fed)


def bubble_up_draft_fed(fed):
    """A DRAFT fed whose members are now all ACCEPTED advances to ASSEMBLED."""
    if fed["status"] != "DRAFT":
        return
    members = [
        m for m in db.federated_model_members.values()
        if m["federated_model_id"] == fed["id"]
    ]
    if not members:
        return
    for m in members:
        tm = db.trade_models.get(m["trade_model_id"])
        if not tm or tm["status"] != "ACCEPTED":
            return
    fed["status"] = "ASSEMBLED"
    touch(fed)


def cascade_on_accept(new_model):
    """Run CASCADE A after a TradeModel is accepted."""
    pid = new_model["project_id"]
    disc = new_model["discipline"]
    # Link 1: prior ACCEPTED revision of same (project, discipline) -> SUPERSEDED
    prior = None
    for m in db.trade_models.values():
        if (
            m["id"] != new_model["id"]
            and m["project_id"] == pid
            and m["discipline"] == disc
            and m["status"] == "ACCEPTED"
        ):
            prior = m
            break
    if prior:
        prior["status"] = "SUPERSEDED"
        touch(prior)
        new_model["supersedes_model_id"] = prior["id"]
        # Link 2: re-point members; mark fed stale; FROZEN -> ASSEMBLED
        affected_fed_ids = set()
        for mem in db.federated_model_members.values():
            if mem["trade_model_id"] == prior["id"]:
                mem["trade_model_id"] = new_model["id"]
                mem["discipline"] = new_model["discipline"]
                touch(mem)
                affected_fed_ids.add(mem["federated_model_id"])
        # Note: pinned_model_version is KEPT as previously pinned per PRD §2.7
        for fid in affected_fed_ids:
            fed = db.federated_models[fid]
            if fed["status"] == "FROZEN":
                unfreeze_fed(fed)  # handles link 3 revocation cascade
            else:
                # DRAFT / ASSEMBLED / RELEASED keep status, set stale
                fed["is_stale"] = True
                touch(fed)
    # Bubble-up: DRAFT feds with all members ACCEPTED -> ASSEMBLED
    for fed in list(db.federated_models.values()):
        if fed["project_id"] == pid:
            bubble_up_draft_fed(fed)


# ---------------------------------------------------------------------------
# Commitment cascades
# ---------------------------------------------------------------------------


def fulfill_commitments_for_clash(clash):
    """CASCADE C: linked commitment in COMMITTED with due_at >= clock -> FULFILLED."""
    now = db.logical_clock
    meeting_ids = set()
    for cm in db.resolution_commitments.values():
        if cm["clash_issue_id"] != clash["id"]:
            continue
        if cm["status"] != "COMMITTED":
            continue
        if cm["_due_at"] < now:
            continue
        cm["status"] = "FULFILLED"
        cm["fulfilled_at"] = _logical_iso(now)
        touch(cm)
        meeting_ids.add(cm["meeting_id"])
    for mid in meeting_ids:
        recompute_meeting_counts(db.coordination_meetings[mid])


def breach_commitments_for_clash(clash):
    """CASCADE B link 2: linked commitment in FULFILLED -> BREACHED, reliability applied."""
    partners = set()
    meeting_ids = set()
    for cm in db.resolution_commitments.values():
        if cm["clash_issue_id"] != clash["id"]:
            continue
        if cm["status"] != "FULFILLED":
            continue
        cm["status"] = "BREACHED"
        touch(cm)
        partners.add(cm["committed_by_partner_id"])
        meeting_ids.add(cm["meeting_id"])
    for pid in partners:
        partner = db.trade_partners.get(pid)
        if partner:
            apply_reliability_decay(partner)
    for mid in meeting_ids:
        recompute_meeting_counts(db.coordination_meetings[mid])


def recompute_meeting_counts(meeting):
    cms = [c for c in db.resolution_commitments.values() if c["meeting_id"] == meeting["id"]]
    meeting["commitment_count"] = len(cms)
    meeting["fulfilled_commitment_count"] = sum(1 for c in cms if c["status"] == "FULFILLED")
    meeting["breached_commitment_count"] = sum(1 for c in cms if c["status"] == "BREACHED")
    touch(meeting)


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be a non-empty string")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be one of {allowed}")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    return v


def require_number(body, field):
    return parse_decimal(body.get(field), field)


def optional_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be a string")
    return v


# ---------------------------------------------------------------------------
# Flask app & error handler
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err("ERR_INVALID_REQUEST", 404, "Route not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(err("ERR_INVALID_REQUEST", 405, "Method not allowed"))


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(err("ERR_INVALID_REQUEST", 500, f"Internal error: {e}"))


# ---------------------------------------------------------------------------
# Project endpoints
# ---------------------------------------------------------------------------


@app.route("/api/projects", methods=["POST"])
def create_project():
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    body = request.get_json(silent=True) or {}
    name = require_str(body, "name")
    rec = init_common({})
    rec.update(
        {
            "name": name,
            "current_phase": "SCHEMATIC_DESIGN",
            "coordination_posture": "NORMAL",
            "coordination_readiness_index": 100,
            "open_critical_count": 0,
            "open_major_count": 0,
            "unassigned_minor_count": 0,
            "overdue_commitment_count": 0,
            "ops_sweep_index": 0,
        }
    )
    db.projects[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/projects/<pid>", methods=["GET"])
def get_project(pid):
    get_auth()
    p = project_by_id(pid)
    return success_object(serialize(p))


@app.route("/api/projects/<pid>/advance-phase", methods=["POST"])
def advance_phase(pid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    p = project_by_id(pid)
    cur = p["current_phase"]
    if cur == "CLOSEOUT":
        raise err("ERR_INVALID_PHASE_TRANSITION", 409, "Cannot advance beyond CLOSEOUT")
    idx = PHASES.index(cur)
    p["current_phase"] = PHASES[idx + 1]
    touch(p)
    return success_object(serialize(p))


@app.route("/api/projects/<pid>/run-coordination-sweep", methods=["POST"])
def run_sweep(pid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    p = project_by_id(pid)
    now = db.logical_clock
    overdue = [
        c
        for c in db.resolution_commitments.values()
        if c["project_id"] == pid and c["status"] == "COMMITTED" and c["_due_at"] < now
    ]
    # Order: created_at ASC, tie-break due_at ASC
    overdue.sort(key=lambda c: (c["created_at"], c["_due_at"]))
    affected_meetings = set()
    for cm in overdue:
        cm["status"] = "BREACHED"
        touch(cm)
        partner = db.trade_partners.get(cm["committed_by_partner_id"])
        if partner:
            apply_reliability_decay(partner)
        affected_meetings.add(cm["meeting_id"])
    for mid in affected_meetings:
        recompute_meeting_counts(db.coordination_meetings[mid])
    recompute_project(p)
    p["ops_sweep_index"] = p.get("ops_sweep_index", 0) + 1
    touch(p)
    return success_object(serialize(p))


# ---------------------------------------------------------------------------
# LodRequirement
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/lod-requirements", methods=["POST"])
def create_lod_requirement(pid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    p = project_by_id(pid)
    body = request.get_json(silent=True) or {}
    discipline = require_enum(body, "discipline", DISCIPLINES)
    phase = require_enum(body, "phase", PHASES)
    min_lod = require_int(body, "min_lod")
    if min_lod not in MIN_LOD_VALUES:
        raise err("ERR_INVALID_REQUEST", 400, f"min_lod must be one of {MIN_LOD_VALUES}")
    clearance = require_number(body, "clearance_requirement_mm")
    if clearance <= 0:
        raise err("ERR_INVALID_REQUEST", 400, "clearance_requirement_mm must be > 0")
    # uniqueness
    for r in db.lod_requirements.values():
        if (
            r["project_id"] == pid
            and r["discipline"] == discipline
            and r["phase"] == phase
        ):
            raise err(
                "ERR_DUPLICATE_LOD_REQUIREMENT",
                409,
                "LodRequirement for (project, discipline, phase) already exists",
            )
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "discipline": discipline,
            "phase": phase,
            "min_lod": min_lod,
            "clearance_requirement_mm": float(clearance),
        }
    )
    db.lod_requirements[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/projects/<pid>/lod-requirements", methods=["GET"])
def list_lod_requirements(pid):
    get_auth()
    project_by_id(pid)
    items = [r for r in db.lod_requirements.values() if r["project_id"] == pid]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# TradePartner
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/trade-partners", methods=["POST"])
def create_trade_partner(pid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    p = project_by_id(pid)
    body = request.get_json(silent=True) or {}
    company_name = require_str(body, "company_name")
    discipline = require_enum(body, "discipline", DISCIPLINES)
    hourly_rate_cents = require_int(body, "hourly_rate_cents")
    if hourly_rate_cents <= 0:
        raise err("ERR_INVALID_REQUEST", 400, "hourly_rate_cents must be > 0")
    budget = require_number(body, "coordination_budget_hours")
    if budget < 0:
        raise err("ERR_INVALID_REQUEST", 400, "coordination_budget_hours must be >= 0")
    platform = require_enum(body, "software_platform", SOFTWARE_PLATFORMS)
    for tp in db.trade_partners.values():
        if tp["project_id"] == pid and tp["company_name"] == company_name:
            raise err("ERR_DUPLICATE_TRADE_PARTNER", 409, "company_name already exists in this project")
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "company_name": company_name,
            "discipline": discipline,
            "hourly_rate_cents": hourly_rate_cents,
            "coordination_budget_hours": float(budget),
            "consumed_resolution_hours": 0,
            "reliability_score": 100.0,
            "breach_count": 0,
            "software_platform": platform,
            "status": "ACTIVE",
        }
    )
    db.trade_partners[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/projects/<pid>/trade-partners", methods=["GET"])
def list_trade_partners(pid):
    get_auth()
    project_by_id(pid)
    items = [r for r in db.trade_partners.values() if r["project_id"] == pid]
    status = request.args.get("status")
    discipline = request.args.get("discipline")
    if status:
        items = [r for r in items if r["status"] == status]
    if discipline:
        items = [r for r in items if r["discipline"] == discipline]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# TradeModel
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/trade-models", methods=["POST"])
def create_trade_model(pid):
    uid, role = get_auth()
    require_role(role, ["TradeModelAuthor"])
    p = project_by_id(pid)
    body = request.get_json(silent=True) or {}
    trade_partner_id = body.get("trade_partner_id")
    if not isinstance(trade_partner_id, str) or not trade_partner_id:
        raise err("ERR_INVALID_REQUEST", 400, "trade_partner_id is required")
    # Ownership: X-User-ID must equal trade_partner_id AND be a partner of the project
    if trade_partner_id != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal trade_partner_id")
    tp = db.trade_partners.get(trade_partner_id)
    if not tp:
        raise err("ERR_TRADE_PARTNER_NOT_FOUND", 404, "TradePartner not found")
    if tp["project_id"] != pid:
        raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "trade_partner_id belongs to a different project")
    file_format = require_enum(body, "file_format", FILE_FORMATS)
    declared_lod = require_int(body, "declared_lod")
    if declared_lod < 0 or declared_lod > 500:
        raise err("ERR_INVALID_REQUEST", 400, "declared_lod must be in [0, 500]")
    ls_e = require_int(body, "life_safety_elements")
    ls_c = require_int(body, "life_safety_compliant")
    env_e = require_int(body, "envelope_elements")
    env_c = require_int(body, "envelope_compliant")
    fin_e = require_int(body, "finish_elements")
    fin_c = require_int(body, "finish_compliant")
    for nm, e, c in [
        ("life_safety", ls_e, ls_c),
        ("envelope", env_e, env_c),
        ("finish", fin_e, fin_c),
    ]:
        if e < 0 or c < 0 or c > e:
            raise err("ERR_INVALID_REQUEST", 400, f"{nm} element counts invalid")
    if ls_e + env_e + fin_e < 1:
        raise err("ERR_INVALID_REQUEST", 400, "total element count must be >= 1")
    # revision number: per (project, discipline) monotonic
    disc = tp["discipline"]
    existing = [
        m for m in db.trade_models.values()
        if m["project_id"] == pid and m["discipline"] == disc
    ]
    rev = 1 + max((m["revision_number"] for m in existing), default=0)
    interop = compute_interop_status(tp["software_platform"], file_format)
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "trade_partner_id": trade_partner_id,
            "discipline": disc,
            "revision_number": rev,
            "file_format": file_format,
            "interop_status": interop,
            "declared_lod": declared_lod,
            "life_safety_elements": ls_e,
            "life_safety_compliant": ls_c,
            "envelope_elements": env_e,
            "envelope_compliant": env_c,
            "finish_elements": fin_e,
            "finish_compliant": fin_c,
            "submission_score": None,
            "audit_score": None,
            "supersedes_model_id": None,
            "submitted_by_user_id": None,
            "status": "DRAFT",
        }
    )
    db.trade_models[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/trade-models", methods=["GET"])
def list_trade_models():
    get_auth()
    items = list(db.trade_models.values())
    for f in ("project_id", "trade_partner_id", "supersedes_model_id", "status", "discipline"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/trade-models/<mid>", methods=["GET"])
def get_trade_model(mid):
    get_auth()
    m = trade_model_by_id(mid)
    return success_object(serialize(m))


@app.route("/api/trade-models/<mid>/submit", methods=["POST"])
def submit_trade_model(mid):
    uid, role = get_auth()
    require_role(role, ["TradeModelAuthor"])
    m = trade_model_by_id(mid)
    if m["trade_partner_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal trade_partner_id")
    if m["status"] not in ("DRAFT", "REJECTED"):
        raise err("ERR_MODEL_NOT_SUBMITTABLE", 409, "submit requires status DRAFT or REJECTED")
    # LOD gate
    project = db.projects[m["project_id"]]
    req = None
    for r in db.lod_requirements.values():
        if (
            r["project_id"] == m["project_id"]
            and r["discipline"] == m["discipline"]
            and r["phase"] == project["current_phase"]
        ):
            req = r
            break
    if req is not None and m["declared_lod"] < req["min_lod"]:
        raise err("ERR_LOD_BELOW_PHASE_REQUIREMENT", 422, "declared_lod below required min_lod")
    # Interop gate
    if m["interop_status"] == "INCOMPATIBLE":
        raise err("ERR_INTEROP_INCOMPATIBLE_FORMAT", 422, "file_format is INCOMPATIBLE")
    m["status"] = "SUBMITTED"
    m["submitted_by_user_id"] = uid
    m["submission_score"] = compute_submission_score(m)
    touch(m)
    return success_object(serialize(m))


@app.route("/api/trade-models/<mid>/accept", methods=["POST"])
def accept_trade_model(mid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    m = trade_model_by_id(mid)
    if m["status"] != "SUBMITTED":
        raise err("ERR_MODEL_NOT_SUBMITTED", 409, "accept requires status SUBMITTED")
    m["status"] = "ACCEPTED"
    m["audit_score"] = compute_audit_score(m)
    touch(m)
    cascade_on_accept(m)
    return success_object(serialize(m))


@app.route("/api/trade-models/<mid>/reject", methods=["POST"])
def reject_trade_model(mid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    m = trade_model_by_id(mid)
    if m["status"] != "SUBMITTED":
        raise err("ERR_MODEL_NOT_SUBMITTED", 409, "reject requires status SUBMITTED")
    m["status"] = "REJECTED"
    touch(m)
    return success_object(serialize(m))


# ---------------------------------------------------------------------------
# FederatedModel
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/federated-models", methods=["POST"])
def create_federated_model(pid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    p = project_by_id(pid)
    body = request.get_json(silent=True) or {}
    label = require_str(body, "label")
    target_format = require_enum(body, "target_format", TARGET_FORMATS)
    member_ids = body.get("member_trade_model_ids")
    if not isinstance(member_ids, list) or not member_ids:
        raise err("ERR_INVALID_REQUEST", 400, "member_trade_model_ids must be a non-empty array")
    # OCC check (priority 5, before business rules but after shape/existence per spec:
    # "evaluated before any business rule" — shape validation already done above)
    expected_version = body.get("expected_project_version")
    if expected_version is None or isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", 400, "expected_project_version is required and must be an integer")
    if expected_version != p["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", 412, "expected_project_version mismatch")
    # Resolve members
    members = []
    for mid in member_ids:
        if not isinstance(mid, str):
            raise err("ERR_INVALID_REQUEST", 400, "member_trade_model_ids must be strings")
        m = db.trade_models.get(mid)
        if not m:
            raise err("ERR_TRADE_MODEL_NOT_FOUND", 404, "TradeModel not found")
        members.append(m)
    # Same project
    for m in members:
        if m["project_id"] != pid:
            raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "member model belongs to a different project")
    # One member per discipline
    seen = set()
    for m in members:
        if m["discipline"] in seen:
            raise err("ERR_DUPLICATE_DISCIPLINE_IN_ASSEMBLY", 409, "two member models share a discipline")
        seen.add(m["discipline"])
    # Supersede current non-terminal fed in this project
    for fed in list(db.federated_models.values()):
        if fed["project_id"] == pid and fed["status"] in ("DRAFT", "ASSEMBLED", "FROZEN", "RELEASED"):
            supersede_fed(fed)
    # Assembly index
    existing = [f for f in db.federated_models.values() if f["project_id"] == pid]
    idx = 1 + max((f["assembly_index"] for f in existing), default=0)
    rec = init_common({})
    all_accepted = all(m["status"] == "ACCEPTED" for m in members)
    rec.update(
        {
            "project_id": pid,
            "label": label,
            "assembly_index": idx,
            "target_format": target_format,
            "status": "ASSEMBLED" if all_accepted else "DRAFT",
            "is_stale": False,
            "open_critical_count": 0,
        }
    )
    db.federated_models[rec["id"]] = rec
    # Create members with pinned versions
    for m in members:
        mem = init_common({})
        mem.update(
            {
                "federated_model_id": rec["id"],
                "trade_model_id": m["id"],
                "discipline": m["discipline"],
                "pinned_model_version": m["version"],
            }
        )
        db.federated_model_members[mem["id"]] = mem
    # Assembly create increments Project.version
    touch(p)
    return success_object(serialize(rec), 201)


@app.route("/api/federated-models", methods=["GET"])
def list_federated_models():
    get_auth()
    items = list(db.federated_models.values())
    for f in ("project_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/federated-models/<fid>", methods=["GET"])
def get_federated_model(fid):
    get_auth()
    f = fed_model_by_id(fid)
    return success_object(serialize(f))


@app.route("/api/federated-models/<fid>/freeze", methods=["POST"])
def freeze_federated_model(fid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    fed = fed_model_by_id(fid)
    if fed["status"] != "ASSEMBLED":
        raise err("ERR_FED_NOT_ASSEMBLED", 409, "freeze requires status ASSEMBLED")
    members = [
        m for m in db.federated_model_members.values() if m["federated_model_id"] == fid
    ]
    for mem in members:
        tm = db.trade_models.get(mem["trade_model_id"])
        if tm is None:
            raise err("ERR_MEMBER_COMPLIANCE_BELOW_THRESHOLD", 422, "member model missing")
        score = tm.get("audit_score")
        if score is None or Decimal(str(score)) < AUDIT_ACCEPT_THRESHOLD:
            raise err(
                "ERR_MEMBER_COMPLIANCE_BELOW_THRESHOLD",
                422,
                "a member model's audit_score is below 70.0",
            )
    # Re-pin
    for mem in members:
        tm = db.trade_models[mem["trade_model_id"]]
        if mem["pinned_model_version"] != tm["version"]:
            mem["pinned_model_version"] = tm["version"]
            touch(mem)
    fed["status"] = "FROZEN"
    fed["is_stale"] = False
    touch(fed)
    return success_object(serialize(fed))


@app.route("/api/federated-models/<fid>/unfreeze", methods=["POST"])
def unfreeze_federated_model(fid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    fed = fed_model_by_id(fid)
    if fed["status"] != "FROZEN":
        raise err("ERR_FED_NOT_FROZEN", 409, "unfreeze requires status FROZEN")
    unfreeze_fed(fed)
    return success_object(serialize(fed))


@app.route("/api/federated-models/<fid>/release", methods=["POST"])
def release_federated_model(fid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    fed = fed_model_by_id(fid)
    if fed["status"] != "FROZEN":
        raise err("ERR_FED_NOT_FROZEN", 409, "release requires status FROZEN")
    project = db.projects[fed["project_id"]]
    # posture gate evaluated BEFORE open-clash gate
    if project["coordination_posture"] != "NORMAL":
        raise err("ERR_PROJECT_IN_COORDINATION_HOLD", 409, "project is in COORDINATION_HOLD")
    # recompute fed's open critical count
    recompute_fed_open_critical(fed)
    if fed["open_critical_count"] != 0:
        raise err("ERR_OPEN_CLASHES_REMAIN", 409, "open CRITICAL clashes remain")
    fed["status"] = "RELEASED"
    touch(fed)
    return success_object(serialize(fed))


@app.route("/api/federated-models/<fid>/members", methods=["GET"])
def list_federated_members(fid):
    get_auth()
    fed_model_by_id(fid)
    items = [m for m in db.federated_model_members.values() if m["federated_model_id"] == fid]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/trade-models/<mid>/federated-model-members", methods=["GET"])
def list_memberships_of_model(mid):
    get_auth()
    trade_model_by_id(mid)
    items = [m for m in db.federated_model_members.values() if m["trade_model_id"] == mid]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# FreezeWindow
# ---------------------------------------------------------------------------


@app.route("/api/federated-models/<fid>/freeze-windows", methods=["POST"])
def create_freeze_window(fid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    fed = fed_model_by_id(fid)
    body = request.get_json(silent=True) or {}
    s_raw = body.get("starts_at")
    e_raw = body.get("ends_at")
    purpose = require_enum(body, "purpose", FREEZE_PURPOSES)
    s_dt = parse_iso(s_raw, "starts_at")
    e_dt = parse_iso(e_raw, "ends_at")
    if e_dt <= s_dt:
        raise err("ERR_INVALID_TIME_RANGE", 422, "ends_at must be strictly after starts_at")
    # gap check: closed intervals with 3600s buffer
    for w in db.freeze_windows.values():
        if w["federated_model_id"] != fid:
            continue
        s1 = w["_starts_at"]
        e1 = w["_ends_at"]
        ok = (
            (s_dt - e1).total_seconds() >= FREEZE_GAP_SECONDS
            or (s1 - e_dt).total_seconds() >= FREEZE_GAP_SECONDS
        )
        if not ok:
            raise err(
                "ERR_FREEZE_WINDOW_GAP_VIOLATION",
                409,
                "freeze window overlaps or sits within 3600s of another window",
            )
    rec = init_common({})
    rec.update(
        {
            "federated_model_id": fid,
            "starts_at": _logical_iso(s_dt),
            "ends_at": _logical_iso(e_dt),
            "purpose": purpose,
            "_starts_at": s_dt,
            "_ends_at": e_dt,
        }
    )
    db.freeze_windows[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/federated-models/<fid>/freeze-windows", methods=["GET"])
def list_freeze_windows(fid):
    get_auth()
    fed_model_by_id(fid)
    items = [w for w in db.freeze_windows.values() if w["federated_model_id"] == fid]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# ClashDetectionRun / ClashIssue
# ---------------------------------------------------------------------------


@app.route("/api/federated-models/<fid>/clash-runs", methods=["POST"])
def create_clash_run(fid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    fed = fed_model_by_id(fid)
    body = request.get_json(silent=True) or {}
    tolerance = require_number(body, "tolerance_mm")
    if tolerance <= 0:
        raise err("ERR_INVALID_REQUEST", 400, "tolerance_mm must be > 0")
    if fed["status"] != "FROZEN":
        raise err("ERR_FED_NOT_FROZEN", 409, "clash-run create requires federated model FROZEN")
    existing = [r for r in db.clash_runs.values() if r["federated_model_id"] == fid]
    run_index = 1 + max((r["run_index"] for r in existing), default=0)
    rec = init_common({})
    rec.update(
        {
            "project_id": fed["project_id"],
            "federated_model_id": fid,
            "run_index": run_index,
            "tolerance_mm": float(tolerance),
            "status": "QUEUED",
            "total_clash_count": 0,
            "open_clash_count": 0,
            "closed_clash_count": 0,
            "started_at": None,
            "completed_at": None,
        }
    )
    db.clash_runs[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/clash-runs", methods=["GET"])
def list_clash_runs():
    get_auth()
    items = list(db.clash_runs.values())
    for f in ("project_id", "federated_model_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/clash-runs/<rid>", methods=["GET"])
def get_clash_run(rid):
    get_auth()
    r = clash_run_by_id(rid)
    return success_object(serialize(r))


@app.route("/api/clash-runs/<rid>/start", methods=["POST"])
def start_clash_run(rid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    run = clash_run_by_id(rid)
    if run["status"] != "QUEUED":
        raise err("ERR_RUN_NOT_QUEUED", 409, "start requires run status QUEUED")
    fed = db.federated_models[run["federated_model_id"]]
    if fed["status"] != "FROZEN":
        raise err("ERR_FED_NOT_FROZEN", 409, "federated model must be FROZEN")
    members = [
        m for m in db.federated_model_members.values()
        if m["federated_model_id"] == fed["id"]
    ]
    for mem in members:
        tm = db.trade_models.get(mem["trade_model_id"])
        if not tm or tm["status"] != "ACCEPTED":
            raise err("ERR_MODEL_NOT_ACCEPTED", 409, "all member models must be ACCEPTED")
    now = db.logical_clock
    for w in db.freeze_windows.values():
        if w["federated_model_id"] != fed["id"]:
            continue
        if w["purpose"] != "COORDINATION_FREEZE":
            continue
        if w["_starts_at"] <= now <= w["_ends_at"]:
            raise err("ERR_FREEZE_WINDOW_ACTIVE", 409, "an active COORDINATION_FREEZE blocks run start")
    run["status"] = "RUNNING"
    run["started_at"] = _logical_iso(now)
    touch(run)
    return success_object(serialize(run))


@app.route("/api/clash-runs/<rid>/clashes", methods=["POST"])
def import_clash(rid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    run = clash_run_by_id(rid)
    body = request.get_json(silent=True) or {}
    element_pair = require_str(body, "element_pair")
    overlap = require_number(body, "overlap_mm")
    if overlap < 0:
        raise err("ERR_INVALID_REQUEST", 400, "overlap_mm must be >= 0")
    spans = body.get("spans_disciplines")
    if not isinstance(spans, bool):
        raise err("ERR_INVALID_REQUEST", 400, "spans_disciplines must be a boolean")
    if run["status"] != "RUNNING":
        raise err("ERR_RUN_NOT_RUNNING", 409, "clash import requires run status RUNNING")
    severity = compute_severity(overlap)
    rec = init_common({})
    rec.update(
        {
            "clash_run_id": rid,
            "federated_model_id": run["federated_model_id"],
            "project_id": run["project_id"],
            "element_pair": element_pair,
            "overlap_mm": float(overlap),
            "spans_disciplines": spans,
            "severity": severity,
            "assigned_trade_partner_id": None,
            "assigned_by_user_id": None,
            "provisional_cost_cents": None,
            "actual_labor_hours": None,
            "resolved_by_user_id": None,
            "actual_cost_cents": None,
            "cycle_count": 0,
            "status": "NEW",
        }
    )
    db.clash_issues[rec["id"]] = rec
    run["total_clash_count"] += 1
    run["open_clash_count"] += 1
    touch(run)
    fed = db.federated_models[run["federated_model_id"]]
    recompute_fed_open_critical(fed)
    project = db.projects[run["project_id"]]
    recompute_project(project)
    return success_object(serialize(rec), 201)


@app.route("/api/clash-runs/<rid>/complete", methods=["POST"])
def complete_clash_run(rid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    run = clash_run_by_id(rid)
    if run["status"] != "RUNNING":
        raise err("ERR_RUN_NOT_RUNNING", 409, "complete requires run status RUNNING")
    new_count = sum(
        1
        for c in db.clash_issues.values()
        if c["clash_run_id"] == rid and c["status"] == "NEW"
    )
    if new_count > 0:
        raise err("ERR_RUN_HAS_UNASSIGNED_CLASHES", 409, "clashes still in NEW status")
    run["status"] = "COMPLETED"
    run["completed_at"] = _logical_iso(db.logical_clock)
    touch(run)
    return success_object(serialize(run))


@app.route("/api/clash-issues", methods=["GET"])
def list_clash_issues():
    get_auth()
    items = list(db.clash_issues.values())
    for f in ("clash_run_id", "federated_model_id", "assigned_trade_partner_id", "status", "severity"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/clash-issues/<cid>", methods=["GET"])
def get_clash_issue(cid):
    get_auth()
    c = clash_issue_by_id(cid)
    return success_object(serialize(c))


@app.route("/api/clash-issues/<cid>/assign", methods=["POST"])
def assign_clash(cid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    clash = clash_issue_by_id(cid)
    body = request.get_json(silent=True) or {}
    tp_id = body.get("trade_partner_id")
    if not isinstance(tp_id, str) or not tp_id:
        raise err("ERR_INVALID_REQUEST", 400, "trade_partner_id is required")
    if clash["status"] not in ("NEW", "REOPENED"):
        raise err("ERR_CLASH_NOT_ASSIGNABLE", 409, "assign requires status NEW or REOPENED")
    partner = db.trade_partners.get(tp_id)
    if not partner:
        raise err("ERR_TRADE_PARTNER_NOT_FOUND", 404, "TradePartner not found")
    # PRD §2.8 fixed order: the Eighth-layer probation bar fires before the
    # Ninth-layer same-project referential check.
    if partner["status"] != "ACTIVE":
        raise err("ERR_TRADE_PARTNER_ON_PROBATION", 403, "assigned TradePartner must be ACTIVE")
    if partner["project_id"] != clash["project_id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "trade_partner_id belongs to a different project")
    clash["assigned_trade_partner_id"] = tp_id
    clash["assigned_by_user_id"] = uid
    clash["provisional_cost_cents"] = compute_provisional_cost(
        clash["severity"], clash["spans_disciplines"], partner["hourly_rate_cents"]
    )
    clash["status"] = "ASSIGNED"
    touch(clash)
    fed = db.federated_models[clash["federated_model_id"]]
    recompute_fed_open_critical(fed)
    project = db.projects[clash["project_id"]]
    recompute_project(project)
    return success_object(serialize(clash))


@app.route("/api/clash-issues/<cid>/resolve", methods=["POST"])
def resolve_clash(cid):
    uid, role = get_auth()
    require_role(role, ["TradeModelAuthor"])
    clash = clash_issue_by_id(cid)
    # Ownership (priority 3) comes before state (priority 6) per validation order
    if clash.get("assigned_trade_partner_id") != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal assigned_trade_partner_id")
    body = request.get_json(silent=True) or {}
    if clash["status"] != "ASSIGNED":
        raise err("ERR_CLASH_NOT_RESOLVABLE", 409, "resolve requires status ASSIGNED")
    hours = parse_decimal(body.get("actual_labor_hours"), "actual_labor_hours")
    if hours <= 0:
        raise err("ERR_INVALID_REQUEST", 400, "actual_labor_hours must be > 0")
    partner = db.trade_partners[clash["assigned_trade_partner_id"]]
    remaining = Decimal(str(partner["coordination_budget_hours"])) - Decimal(
        str(partner["consumed_resolution_hours"])
    )
    if hours > remaining:
        raise err(
            "ERR_COORDINATION_BUDGET_EXCEEDED",
            402,
            "resolve hours exceed remaining coordination budget",
        )
    clash["actual_labor_hours"] = float(hours)
    clash["resolved_by_user_id"] = uid
    clash["status"] = "RESOLVED"
    touch(clash)
    partner["consumed_resolution_hours"] = float(
        Decimal(str(partner["consumed_resolution_hours"])) + hours
    )
    touch(partner)
    project = db.projects[clash["project_id"]]
    recompute_project(project)
    return success_object(serialize(clash))


@app.route("/api/clash-issues/<cid>/verify", methods=["POST"])
def verify_clash(cid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    clash = clash_issue_by_id(cid)
    body = request.get_json(silent=True) or {}
    if clash["status"] != "RESOLVED":
        raise err("ERR_CLASH_NOT_VERIFIABLE", 409, "verify requires status RESOLVED")
    if clash.get("assigned_by_user_id") == uid:
        raise err("ERR_SOD_VERIFY_EQUALS_ASSIGN", 403, "verifier must differ from assigner")
    re_inspect = parse_decimal(body.get("re_inspection_overlap_mm"), "re_inspection_overlap_mm")
    if re_inspect < 0:
        raise err("ERR_INVALID_REQUEST", 400, "re_inspection_overlap_mm must be >= 0")
    run = db.clash_runs[clash["clash_run_id"]]
    tolerance = Decimal(str(run["tolerance_mm"]))
    fed = db.federated_models[clash["federated_model_id"]]
    project = db.projects[clash["project_id"]]
    if re_inspect <= tolerance:
        # VERIFIED
        partner = db.trade_partners[clash["assigned_trade_partner_id"]]
        clash["actual_cost_cents"] = compute_actual_cost(
            clash["actual_labor_hours"], partner["hourly_rate_cents"]
        )
        clash["status"] = "VERIFIED"
        touch(clash)
        run["open_clash_count"] -= 1
        run["closed_clash_count"] += 1
        touch(run)
        fulfill_commitments_for_clash(clash)
    else:
        # failed re-inspection -> REOPENED
        clash["cycle_count"] = clash.get("cycle_count", 0) + 1
        clash["status"] = "REOPENED"
        touch(clash)
    recompute_fed_open_critical(fed)
    recompute_project(project)
    return success_object(serialize(clash))


@app.route("/api/clash-issues/<cid>/reopen", methods=["POST"])
def reopen_clash(cid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    clash = clash_issue_by_id(cid)
    if clash["status"] != "VERIFIED":
        raise err("ERR_CLASH_NOT_REOPENABLE", 409, "reopen requires status VERIFIED")
    clash["cycle_count"] = clash.get("cycle_count", 0) + 1
    clash["status"] = "REOPENED"
    touch(clash)
    run = db.clash_runs[clash["clash_run_id"]]
    run["open_clash_count"] += 1
    run["closed_clash_count"] -= 1
    touch(run)
    breach_commitments_for_clash(clash)
    fed = db.federated_models[clash["federated_model_id"]]
    recompute_fed_open_critical(fed)
    project = db.projects[clash["project_id"]]
    recompute_project(project)
    return success_object(serialize(clash))


# ---------------------------------------------------------------------------
# CoordinationMeeting / ResolutionCommitment
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/coordination-meetings", methods=["POST"])
def create_meeting(pid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    project_by_id(pid)
    body = request.get_json(silent=True) or {}
    room_id = require_str(body, "room_id")
    s_dt = parse_iso(body.get("starts_at"), "starts_at")
    e_dt = parse_iso(body.get("ends_at"), "ends_at")
    if e_dt <= s_dt:
        raise err("ERR_INVALID_TIME_RANGE", 422, "ends_at must be strictly after starts_at")
    # half-open overlap: conflict iff s < e1 AND s1 < e
    for m in db.coordination_meetings.values():
        if m["project_id"] != pid or m["room_id"] != room_id:
            continue
        if m["status"] not in ("SCHEDULED", "IN_SESSION"):
            continue
        s1 = m["_starts_at"]
        e1 = m["_ends_at"]
        if s_dt < e1 and s1 < e_dt:
            raise err("ERR_ROOM_WINDOW_CONFLICT", 409, "meeting window overlaps an existing booking")
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "room_id": room_id,
            "starts_at": _logical_iso(s_dt),
            "ends_at": _logical_iso(e_dt),
            "status": "SCHEDULED",
            "commitment_count": 0,
            "fulfilled_commitment_count": 0,
            "breached_commitment_count": 0,
            "_starts_at": s_dt,
            "_ends_at": e_dt,
        }
    )
    db.coordination_meetings[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/coordination-meetings", methods=["GET"])
def list_meetings():
    get_auth()
    items = list(db.coordination_meetings.values())
    for f in ("project_id", "room_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/coordination-meetings/<mid>", methods=["GET"])
def get_meeting(mid):
    get_auth()
    m = meeting_by_id(mid)
    return success_object(serialize(m))


@app.route("/api/coordination-meetings/<mid>/start", methods=["POST"])
def start_meeting(mid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    m = meeting_by_id(mid)
    if m["status"] != "SCHEDULED":
        raise err("ERR_MEETING_NOT_SCHEDULED", 409, "start requires status SCHEDULED")
    now = db.logical_clock
    if not (m["_starts_at"] <= now < m["_ends_at"]):
        raise err("ERR_MEETING_WINDOW_NOT_ACTIVE", 409, "logical clock outside meeting window")
    m["status"] = "IN_SESSION"
    touch(m)
    return success_object(serialize(m))


@app.route("/api/coordination-meetings/<mid>/adjourn", methods=["POST"])
def adjourn_meeting(mid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    m = meeting_by_id(mid)
    if m["status"] != "IN_SESSION":
        raise err("ERR_MEETING_NOT_IN_SESSION", 409, "adjourn requires status IN_SESSION")
    m["status"] = "ADJOURNED"
    touch(m)
    return success_object(serialize(m))


@app.route("/api/coordination-meetings/<mid>/commitments", methods=["POST"])
def create_commitment(mid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    m = meeting_by_id(mid)
    body = request.get_json(silent=True) or {}
    clash_id = body.get("clash_issue_id")
    partner_id = body.get("committed_by_partner_id")
    due_at_raw = body.get("due_at")
    if not isinstance(clash_id, str) or not clash_id:
        raise err("ERR_INVALID_REQUEST", 400, "clash_issue_id is required")
    if not isinstance(partner_id, str) or not partner_id:
        raise err("ERR_INVALID_REQUEST", 400, "committed_by_partner_id is required")
    # existence
    clash = db.clash_issues.get(clash_id)
    if not clash:
        raise err("ERR_CLASH_ISSUE_NOT_FOUND", 404, "ClashIssue not found")
    partner = db.trade_partners.get(partner_id)
    if not partner:
        raise err("ERR_TRADE_PARTNER_NOT_FOUND", 404, "TradePartner not found")
    due_dt = parse_iso(due_at_raw, "due_at")
    # state
    if m["status"] != "IN_SESSION":
        raise err("ERR_MEETING_NOT_IN_SESSION", 409, "commitments require meeting IN_SESSION")
    if clash["status"] != "ASSIGNED":
        raise err("ERR_CLASH_NOT_ASSIGNABLE", 409, "clash must be ASSIGNED")
    # cross-project
    if clash["project_id"] != m["project_id"] or partner["project_id"] != m["project_id"]:
        raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "referenced resources must belong to meeting project")
    if clash["assigned_trade_partner_id"] != partner_id:
        raise err(
            "ERR_COMMITMENT_TRADE_MISMATCH",
            422,
            "committed_by_partner_id must equal clash's assigned_trade_partner_id",
        )
    rec = init_common({})
    rec.update(
        {
            "meeting_id": mid,
            "project_id": m["project_id"],
            "clash_issue_id": clash_id,
            "committed_by_partner_id": partner_id,
            "due_at": _logical_iso(due_dt),
            "status": "COMMITTED",
            "fulfilled_at": None,
            "_due_at": due_dt,
        }
    )
    db.resolution_commitments[rec["id"]] = rec
    m["commitment_count"] = m.get("commitment_count", 0) + 1
    touch(m)
    project = db.projects[m["project_id"]]
    recompute_project(project)
    return success_object(serialize(rec), 201)


@app.route("/api/commitments", methods=["GET"])
def list_commitments():
    get_auth()
    items = list(db.resolution_commitments.values())
    for f in ("meeting_id", "clash_issue_id", "committed_by_partner_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/commitments/<cid>", methods=["GET"])
def get_commitment(cid):
    get_auth()
    c = commitment_by_id(cid)
    return success_object(serialize(c))


@app.route("/api/commitments/<cid>/waive", methods=["POST"])
def waive_commitment(cid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    c = commitment_by_id(cid)
    if c["status"] != "COMMITTED":
        raise err("ERR_COMMITMENT_NOT_OPEN", 409, "waive requires status COMMITTED")
    c["status"] = "WAIVED"
    touch(c)
    project = db.projects[c["project_id"]]
    recompute_project(project)
    return success_object(serialize(c))


# ---------------------------------------------------------------------------
# FabricationPackage / SignOff
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/fabrication-packages", methods=["POST"])
def create_fab_package(pid):
    uid, role = get_auth()
    require_role(role, ["FabricationLead"])
    p = project_by_id(pid)
    body = request.get_json(silent=True) or {}
    fed_id = body.get("federated_model_id")
    scope = body.get("scope_disciplines")
    if not isinstance(fed_id, str) or not fed_id:
        raise err("ERR_INVALID_REQUEST", 400, "federated_model_id is required")
    if not isinstance(scope, list) or not scope:
        raise err("ERR_INVALID_REQUEST", 400, "scope_disciplines must be a non-empty array")
    if len(scope) > 3:
        raise err("ERR_INVALID_REQUEST", 400, "scope_disciplines must contain 1..3 unique disciplines")
    if len(set(scope)) != len(scope):
        raise err("ERR_INVALID_REQUEST", 400, "scope_disciplines must be unique")
    for d in scope:
        if d not in DISCIPLINES:
            raise err("ERR_INVALID_REQUEST", 400, "scope_disciplines entries must be valid disciplines")
    # Caller must be an existing trade partner of the project (ownership)
    partner = db.trade_partners.get(uid)
    if not partner or partner["project_id"] != pid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must be a TradePartner of this project")
    fed = db.federated_models.get(fed_id)
    if not fed:
        raise err("ERR_FEDERATED_MODEL_NOT_FOUND", 404, "FederatedModel not found")
    if fed["project_id"] != pid:
        raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "federated model belongs to a different project")
    if fed["status"] != "FROZEN":
        raise err("ERR_FED_NOT_FROZEN", 409, "federated model must be FROZEN")
    members = [
        m for m in db.federated_model_members.values() if m["federated_model_id"] == fed_id
    ]
    member_discs = {m["discipline"] for m in members}
    for d in scope:
        if d not in member_discs:
            raise err(
                "ERR_SCOPE_DISCIPLINE_NOT_IN_ASSEMBLY",
                422,
                f"scope discipline {d} has no member in the federated model",
            )
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "federated_model_id": fed_id,
            "requesting_partner_id": uid,
            "scope_disciplines": list(scope),
            "required_signoff_count": len(scope),
            "signed_count": 0,
            "pinned_fed_model_version": fed["version"],
            "status": "DRAFT",
            "released_at": None,
        }
    )
    db.fabrication_packages[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/fabrication-packages", methods=["GET"])
def list_fab_packages():
    get_auth()
    items = list(db.fabrication_packages.values())
    for f in ("project_id", "federated_model_id", "requesting_partner_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/fabrication-packages/<pid>", methods=["GET"])
def get_fab_package(pid):
    get_auth()
    p = package_by_id(pid)
    return success_object(serialize(p))


@app.route("/api/fabrication-packages/<pid>/submit-for-signoff", methods=["POST"])
def submit_for_signoff(pid):
    uid, role = get_auth()
    require_role(role, ["FabricationLead"])
    pkg = package_by_id(pid)
    if pkg["requesting_partner_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal requesting_partner_id")
    if pkg["status"] not in ("DRAFT", "SIGNOFF_IN_PROGRESS"):
        raise err("ERR_PACKAGE_NOT_DRAFT", 409, "submit-for-signoff requires DRAFT or SIGNOFF_IN_PROGRESS")
    if pkg["status"] == "DRAFT":
        # create one REQUESTED SignOff per scope discipline
        members = [
            m
            for m in db.federated_model_members.values()
            if m["federated_model_id"] == pkg["federated_model_id"]
        ]
        by_disc = {m["discipline"]: m for m in members}
        for d in pkg["scope_disciplines"]:
            mem = by_disc.get(d)
            if not mem:
                continue
            tm = db.trade_models.get(mem["trade_model_id"])
            if not tm:
                continue
            s = init_common({})
            s.update(
                {
                    "fabrication_package_id": pid,
                    "discipline": d,
                    "trade_model_id": tm["id"],
                    "pinned_model_version": tm["version"],
                    "signer_user_id": None,
                    "status": "REQUESTED",
                }
            )
            db.sign_offs[s["id"]] = s
        pkg["status"] = "SIGNOFF_IN_PROGRESS"
        touch(pkg)
    else:
        # SIGNOFF_IN_PROGRESS: re-request DECLINED / REVOKED
        for s in db.sign_offs.values():
            if s["fabrication_package_id"] != pid:
                continue
            if s["status"] in ("DECLINED", "REVOKED"):
                s["status"] = "REQUESTED"
                touch(s)
    recompute_package_signed_count(pkg)
    return success_object(serialize(pkg))


@app.route("/api/fabrication-packages/<pid>/release", methods=["POST"])
def release_fab_package(pid):
    uid, role = get_auth()
    require_role(role, ["FabricationLead"])
    pkg = package_by_id(pid)
    if pkg["requesting_partner_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal requesting_partner_id")
    if pkg["status"] != "READY_FOR_RELEASE":
        raise err("ERR_PACKAGE_NOT_RELEASABLE", 409, "release requires status READY_FOR_RELEASE")
    fed = db.federated_models[pkg["federated_model_id"]]
    if fed["status"] not in ("FROZEN", "RELEASED"):
        raise err("ERR_FED_NOT_FROZEN", 409, "federated model must be FROZEN or RELEASED")
    project = db.projects[pkg["project_id"]]
    if project["current_phase"] not in ("CONSTRUCTION_DOCUMENTS", "CONSTRUCTION_ADMINISTRATION"):
        raise err(
            "ERR_PHASE_TOO_EARLY_FOR_FABRICATION",
            409,
            "phase must be CONSTRUCTION_DOCUMENTS or CONSTRUCTION_ADMINISTRATION",
        )
    if project["coordination_posture"] != "NORMAL":
        raise err("ERR_PROJECT_IN_COORDINATION_HOLD", 409, "project is in COORDINATION_HOLD")
    if project["coordination_readiness_index"] < CRI_RELEASE_THRESHOLD:
        raise err("ERR_CRI_BELOW_RELEASE_THRESHOLD", 409, "coordination_readiness_index below 85")
    pkg["status"] = "RELEASED"
    pkg["released_at"] = _logical_iso(db.logical_clock)
    touch(pkg)
    return success_object(serialize(pkg))


@app.route("/api/fabrication-packages/<pid>/void", methods=["POST"])
def void_fab_package(pid):
    uid, role = get_auth()
    require_role(role, ["FabricationLead"])
    pkg = package_by_id(pid)
    if pkg["requesting_partner_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal requesting_partner_id")
    if pkg["status"] in ("RELEASED", "VOID"):
        raise err("ERR_PACKAGE_ALREADY_FINAL", 409, "package is already final")
    pkg["status"] = "VOID"
    touch(pkg)
    for s in db.sign_offs.values():
        if s["fabrication_package_id"] == pid and s["status"] != "REVOKED":
            s["status"] = "REVOKED"
            touch(s)
    return success_object(serialize(pkg))


@app.route("/api/fabrication-packages/<pid>/signoffs", methods=["GET"])
def list_package_signoffs(pid):
    get_auth()
    package_by_id(pid)
    items = [s for s in db.sign_offs.values() if s["fabrication_package_id"] == pid]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/trade-models/<mid>/signoffs", methods=["GET"])
def list_model_signoffs(mid):
    get_auth()
    trade_model_by_id(mid)
    items = [s for s in db.sign_offs.values() if s["trade_model_id"] == mid]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/signoffs/<sid>", methods=["GET"])
def get_signoff(sid):
    get_auth()
    s = signoff_by_id(sid)
    return success_object(serialize(s))


def _signoff_sod_check(s, uid):
    tm = db.trade_models.get(s["trade_model_id"])
    if tm and tm.get("submitted_by_user_id") == uid:
        raise err(
            "ERR_SOD_SIGNOFF_AUTHOR_CONFLICT",
            403,
            "signer must differ from the pinned model's submitter",
        )


@app.route("/api/signoffs/<sid>/sign", methods=["POST"])
def sign_signoff(sid):
    uid, role = get_auth()
    require_role(role, ["LeadEngineer"])
    s = signoff_by_id(sid)
    if s["status"] != "REQUESTED":
        raise err("ERR_SIGNOFF_NOT_REQUESTED", 409, "sign requires status REQUESTED")
    _signoff_sod_check(s, uid)
    s["status"] = "SIGNED"
    s["signer_user_id"] = uid
    touch(s)
    pkg = db.fabrication_packages[s["fabrication_package_id"]]
    recompute_package_signed_count(pkg)
    maybe_advance_package(pkg)
    return success_object(serialize(s))


@app.route("/api/signoffs/<sid>/decline", methods=["POST"])
def decline_signoff(sid):
    uid, role = get_auth()
    require_role(role, ["LeadEngineer"])
    s = signoff_by_id(sid)
    if s["status"] != "REQUESTED":
        raise err("ERR_SIGNOFF_NOT_REQUESTED", 409, "decline requires status REQUESTED")
    _signoff_sod_check(s, uid)
    s["status"] = "DECLINED"
    touch(s)
    return success_object(serialize(s))


# ---------------------------------------------------------------------------
# AsBuiltModel
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/as-built-models", methods=["POST"])
def create_as_built(pid):
    uid, role = get_auth()
    require_role(role, ["TradeModelAuthor"])
    p = project_by_id(pid)
    body = request.get_json(silent=True) or {}
    tm_id = body.get("trade_model_id")
    notes = body.get("field_verification_notes")
    if not isinstance(tm_id, str) or not tm_id:
        raise err("ERR_INVALID_REQUEST", 400, "trade_model_id is required")
    if not isinstance(notes, str):
        raise err("ERR_INVALID_REQUEST", 400, "field_verification_notes must be a string")
    tm = db.trade_models.get(tm_id)
    if not tm:
        raise err("ERR_TRADE_MODEL_NOT_FOUND", 404, "TradeModel not found")
    # Ownership: basis partner must equal caller
    if tm["trade_partner_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal the basis model's trade_partner_id")
    if tm["project_id"] != pid:
        raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "basis model belongs to a different project")
    if p["current_phase"] not in ("CONSTRUCTION_ADMINISTRATION", "CLOSEOUT"):
        raise err(
            "ERR_PHASE_REQUIREMENT_NOT_MET",
            409,
            "as-built create requires phase CONSTRUCTION_ADMINISTRATION or CLOSEOUT",
        )
    if tm["status"] not in ("ACCEPTED", "SUPERSEDED"):
        raise err("ERR_MODEL_NOT_ACCEPTED", 409, "basis model must be ACCEPTED or SUPERSEDED")
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "trade_model_id": tm_id,
            "trade_partner_id": tm["trade_partner_id"],
            "field_verification_notes": notes,
            "verification_deviation_mm": None,
            "status": "DRAFT",
        }
    )
    db.as_built_models[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/as-built-models", methods=["GET"])
def list_as_built():
    get_auth()
    items = list(db.as_built_models.values())
    for f in ("project_id", "trade_model_id", "trade_partner_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/as-built-models/<aid>", methods=["GET"])
def get_as_built(aid):
    get_auth()
    a = as_built_by_id(aid)
    return success_object(serialize(a))


@app.route("/api/as-built-models/<aid>/submit", methods=["POST"])
def submit_as_built(aid):
    uid, role = get_auth()
    require_role(role, ["TradeModelAuthor"])
    a = as_built_by_id(aid)
    if a["trade_partner_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", 403, "X-User-ID must equal trade_partner_id")
    if a["status"] not in ("DRAFT", "REJECTED"):
        raise err("ERR_AS_BUILT_NOT_SUBMITTABLE", 409, "submit requires status DRAFT or REJECTED")
    a["status"] = "SUBMITTED"
    touch(a)
    return success_object(serialize(a))


@app.route("/api/as-built-models/<aid>/verify", methods=["POST"])
def verify_as_built(aid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    a = as_built_by_id(aid)
    body = request.get_json(silent=True) or {}
    if a["status"] != "SUBMITTED":
        raise err("ERR_AS_BUILT_NOT_SUBMITTED", 409, "verify requires status SUBMITTED")
    dev = parse_decimal(body.get("verification_deviation_mm"), "verification_deviation_mm")
    a["verification_deviation_mm"] = float(dev)
    if dev <= AS_BUILT_TOLERANCE_MM:
        a["status"] = "FIELD_VERIFIED"
    else:
        a["status"] = "REJECTED"
    touch(a)
    return success_object(serialize(a))


# ---------------------------------------------------------------------------
# QuantityTakeoff
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/quantity-takeoffs", methods=["POST"])
def create_takeoff(pid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    p = project_by_id(pid)
    body = request.get_json(silent=True) or {}
    fed_id = body.get("federated_model_id")
    extraction_mode = body.get("extraction_mode")
    elements = body.get("elements")
    discipline_filter = body.get("discipline_filter")
    expected_version = body.get("expected_project_version")
    if not isinstance(fed_id, str) or not fed_id:
        raise err("ERR_INVALID_REQUEST", 400, "federated_model_id is required")
    if extraction_mode not in EXTRACTION_MODES:
        raise err("ERR_INVALID_REQUEST", 400, "extraction_mode must be GROSS or NET")
    if discipline_filter is not None and discipline_filter not in DISCIPLINES:
        raise err("ERR_INVALID_REQUEST", 400, "discipline_filter must be a valid discipline")
    if not isinstance(elements, list) or not elements:
        raise err("ERR_INVALID_REQUEST", 400, "elements must be a non-empty array")
    # validate elements
    parsed_elements = []
    for e in elements:
        if not isinstance(e, dict):
            raise err("ERR_INVALID_REQUEST", 400, "each element must be an object")
        eref = e.get("element_ref")
        if not isinstance(eref, str) or not eref:
            raise err("ERR_INVALID_REQUEST", 400, "element_ref is required")
        gross = parse_decimal(e.get("gross_qty"), "gross_qty")
        deduct = parse_decimal(e.get("deduction_qty"), "deduction_qty")
        if gross < 0 or deduct < 0:
            raise err("ERR_INVALID_REQUEST", 400, "quantities must be >= 0")
        if gross < deduct:
            raise err("ERR_INVALID_REQUEST", 400, "gross_qty must be >= deduction_qty")
        parsed_elements.append(
            {"element_ref": eref, "gross_qty": float(gross), "deduction_qty": float(deduct), "_gross": gross, "_deduction": deduct}
        )
    # OCC
    if expected_version is None or isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", 400, "expected_project_version is required and must be an integer")
    if expected_version != p["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", 412, "expected_project_version mismatch")
    fed = db.federated_models.get(fed_id)
    if not fed:
        raise err("ERR_FEDERATED_MODEL_NOT_FOUND", 404, "FederatedModel not found")
    if fed["project_id"] != pid:
        raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "federated model belongs to a different project")
    if fed["status"] not in ("FROZEN", "RELEASED"):
        raise err("ERR_FED_NOT_FROZEN", 409, "federated model must be FROZEN or RELEASED")
    # supersede same-key takeoff
    for t in db.quantity_takeoffs.values():
        if (
            t["federated_model_id"] == fed_id
            and t["extraction_mode"] == extraction_mode
            and t.get("discipline_filter") == discipline_filter
            and t["status"] in ("EXTRACTED", "APPROVED")
        ):
            t["status"] = "SUPERSEDED"
            touch(t)
    total = compute_quantity_total(extraction_mode, parsed_elements)
    # store elements without internal keys
    stored_elements = [
        {"element_ref": e["element_ref"], "gross_qty": e["gross_qty"], "deduction_qty": e["deduction_qty"]}
        for e in parsed_elements
    ]
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "federated_model_id": fed_id,
            "extraction_mode": extraction_mode,
            "discipline_filter": discipline_filter,
            "elements": stored_elements,
            "element_count": len(stored_elements),
            "total_quantity": float(total),
            "status": "EXTRACTED",
        }
    )
    db.quantity_takeoffs[rec["id"]] = rec
    touch(p)
    return success_object(serialize(rec), 201)


@app.route("/api/quantity-takeoffs", methods=["GET"])
def list_takeoffs():
    get_auth()
    items = list(db.quantity_takeoffs.values())
    for f in ("project_id", "federated_model_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/quantity-takeoffs/<tid>", methods=["GET"])
def get_takeoff(tid):
    get_auth()
    t = takeoff_by_id(tid)
    return success_object(serialize(t))


@app.route("/api/quantity-takeoffs/<tid>/approve", methods=["POST"])
def approve_takeoff(tid):
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    t = takeoff_by_id(tid)
    if t["status"] != "EXTRACTED":
        raise err("ERR_TAKEOFF_NOT_EXTRACTED", 409, "approve requires status EXTRACTED")
    fed = db.federated_models[t["federated_model_id"]]
    if fed["status"] != "RELEASED":
        raise err("ERR_FED_NOT_RELEASED", 409, "approve requires federated model RELEASED")
    t["status"] = "APPROVED"
    touch(t)
    return success_object(serialize(t))


# ---------------------------------------------------------------------------
# HandoverPackage
# ---------------------------------------------------------------------------


@app.route("/api/projects/<pid>/handover-packages", methods=["POST"])
def create_handover(pid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    project_by_id(pid)
    body = request.get_json(silent=True) or {}
    label = require_str(body, "label")
    takeoff_id = body.get("includes_takeoff_id")
    if not isinstance(takeoff_id, str) or not takeoff_id:
        raise err("ERR_INVALID_REQUEST", 400, "includes_takeoff_id is required")
    t = db.quantity_takeoffs.get(takeoff_id)
    if not t:
        raise err("ERR_TAKEOFF_NOT_FOUND", 404, "QuantityTakeoff not found")
    if t["project_id"] != pid:
        raise err("ERR_CROSS_PROJECT_REFERENCE", 422, "takeoff belongs to a different project")
    rec = init_common({})
    rec.update(
        {
            "project_id": pid,
            "label": label,
            "includes_takeoff_id": takeoff_id,
            "status": "ASSEMBLING",
            "transmitted_at": None,
            "fm_decision_by_user_id": None,
        }
    )
    db.handover_packages[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/api/handover-packages", methods=["GET"])
def list_handover():
    get_auth()
    items = list(db.handover_packages.values())
    for f in ("project_id", "includes_takeoff_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items)
    return success_list([serialize(r) for r in page], limit, offset, total)


@app.route("/api/handover-packages/<hid>", methods=["GET"])
def get_handover(hid):
    get_auth()
    h = handover_by_id(hid)
    return success_object(serialize(h))


@app.route("/api/handover-packages/<hid>/mark-ready", methods=["POST"])
def mark_ready_handover(hid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    h = handover_by_id(hid)
    if h["status"] not in ("ASSEMBLING", "FM_REJECTED"):
        raise err("ERR_HANDOVER_NOT_ASSEMBLING", 409, "mark-ready requires status ASSEMBLING or FM_REJECTED")
    project = db.projects[h["project_id"]]
    if project["current_phase"] != "CLOSEOUT":
        raise err("ERR_PHASE_REQUIREMENT_NOT_MET", 409, "mark-ready requires phase CLOSEOUT")
    t = db.quantity_takeoffs[h["includes_takeoff_id"]]
    if t["status"] != "APPROVED":
        raise err("ERR_TAKEOFF_NOT_APPROVED", 409, "referenced takeoff must be APPROVED")
    as_builts = [a for a in db.as_built_models.values() if a["project_id"] == h["project_id"]]
    if not as_builts:
        raise err("ERR_AS_BUILTS_NOT_VERIFIED", 409, "no as-built models exist in the project")
    for a in as_builts:
        if a["status"] != "FIELD_VERIFIED":
            raise err("ERR_AS_BUILTS_NOT_VERIFIED", 409, "all as-built models must be FIELD_VERIFIED")
    for c in db.clash_issues.values():
        if c["project_id"] == h["project_id"] and c["status"] in OPEN_CLASH_STATUSES:
            raise err("ERR_OPEN_CLASHES_REMAIN", 409, "open clashes remain in the project")
    h["status"] = "READY"
    touch(h)
    return success_object(serialize(h))


@app.route("/api/handover-packages/<hid>/transmit", methods=["POST"])
def transmit_handover(hid):
    uid, role = get_auth()
    require_role(role, ["BIMCoordinator"])
    h = handover_by_id(hid)
    if h["status"] != "READY":
        raise err("ERR_HANDOVER_NOT_READY", 409, "transmit requires status READY")
    h["status"] = "TRANSMITTED"
    h["transmitted_at"] = _logical_iso(db.logical_clock)
    touch(h)
    return success_object(serialize(h))


@app.route("/api/handover-packages/<hid>/respond", methods=["POST"])
def respond_handover(hid):
    uid, role = get_auth()
    require_role(role, ["FacilitiesManager"])
    h = handover_by_id(hid)
    body = request.get_json(silent=True) or {}
    # PRD §2.8 fixed order: the Fifth-layer shape check (decision enum range)
    # fires before the Seventh-layer from-state check.
    decision = body.get("decision")
    if decision not in HANDOVER_DECISIONS:
        raise err("ERR_INVALID_REQUEST", 400, "decision must be ACCEPT or REJECT")
    if h["status"] != "TRANSMITTED":
        raise err("ERR_HANDOVER_NOT_TRANSMITTED", 409, "respond requires status TRANSMITTED")
    h["status"] = "FM_ACCEPTED" if decision == "ACCEPT" else "FM_REJECTED"
    h["fm_decision_by_user_id"] = uid
    touch(h)
    return success_object(serialize(h))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_auth()
    require_role(role, ["VDCManager"])
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    new_dt = parse_iso(to_iso, "to_iso8601")
    if new_dt < db.logical_clock:
        raise err("ERR_INVALID_TIME_RANGE", 422, "clock cannot move backwards")
    db.logical_clock = new_dt
    # recompute clock-dependent fields on every project
    for p in db.projects.values():
        recompute_project(p)
    return success_object({"current_utc": _logical_iso(db.logical_clock)})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
