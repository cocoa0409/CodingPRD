"""The certification docket: six tests, a bounded information-request cycle and
the signature that certifies the institution."""
from datetime import timedelta

import calc
import services as svc
import shape
from auth import authenticate, scope, segregation
from envelope import created, ok, page, pagination, qs
from errors import fail
from flask import Blueprint
from store import base_row, db, fmt_dt, now, ordered, touch

bp = Blueprint("certification", __name__)

APP_READ_ROLES = ("InstitutionOfficer", "CertificationReviewer", "ComplianceAnalyst")
APP_LIST_ROLES = ("CertificationReviewer", "ComplianceAnalyst")
TEST_CODES = ("PRIMARY_MISSION", "FINANCING_ENTITY", "TARGET_MARKET",
              "DEVELOPMENT_SERVICES", "ACCOUNTABILITY", "NON_GOVERNMENT")
VERDICTS = ("PASSED", "FAILED", "WAIVED")
TEST_FIELD = {
    "PRIMARY_MISSION": "test_primary_mission_state",
    "FINANCING_ENTITY": "test_financing_entity_state",
    "TARGET_MARKET": "test_target_market_state",
    "DEVELOPMENT_SERVICES": "test_development_services_state",
    "ACCOUNTABILITY": "test_accountability_state",
    "NON_GOVERNMENT": "test_non_government_state",
}
MISSION_MIN_LEN = 40
SERVICES_MIN_LEN = 20
FINANCING_ACTIVITY_MIN_PCT = calc.Decimal("60.00")
MAX_REVISION_ROUND = 2


def _owning(application_id):
    row = db.cert_apps.get(application_id)
    return row["institution_id"] if row else None


@bp.post("/institutions/<institution_id>/certification-applications")
def create_application(institution_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, institution_id)
    inst = svc.get_institution(institution_id)
    data = shape.body()
    expected = shape.req_int(data, "expected_institution_version")
    mission = shape.req_str(data, "primary_mission_statement", MISSION_MIN_LEN)
    claimed = shape.req_dec(data, "financing_activity_pct_claimed", places=2,
                            minimum=0, maximum=100)
    services_desc = shape.req_str(data, "development_services_description",
                                 SERVICES_MIN_LEN)
    if expected != inst["version"]:
        fail("ERR_STALE_INSTITUTION_VERSION")
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "primary_mission_statement": mission,
        "financing_activity_pct_claimed": claimed,
        "development_services_description": services_desc,
        "state": "DRAFT",
        "revision_round": 0,
        "accountability_score_snapshot": inst["accountability_score"],
        "test_primary_mission_state": "PENDING",
        "test_financing_entity_state": "PENDING",
        "test_target_market_state": "PENDING",
        "test_development_services_state": "PENDING",
        "test_accountability_state": "PENDING",
        "test_non_government_state": "PENDING",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "info_requested_reason": None,
        "decided_at": None,
    })
    db.cert_apps[row["id"]] = row
    touch(inst)
    return created(row)


@bp.get("/certification-applications/<application_id>")
def read_application(application_id):
    caller = authenticate(APP_READ_ROLES)
    scope(caller, _owning(application_id))
    return ok(svc.get_cert_app(application_id))


@bp.get("/institutions/<institution_id>/certification-applications")
def list_institution_applications(institution_id):
    caller = authenticate(APP_READ_ROLES)
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    limit, offset = pagination()
    rows = ordered([a for a in db.cert_apps.values()
                    if a["institution_id"] == institution_id])
    state = qs("state")
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return page(rows, limit, offset)


@bp.get("/certification-applications")
def list_applications():
    authenticate(APP_LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.cert_apps.values())
    institution_id = qs("institution_id")
    state = qs("state")
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return page(rows, limit, offset)


@bp.post("/certification-applications/<application_id>/submit")
def submit_application(application_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, _owning(application_id))
    app = svc.get_cert_app(application_id)
    if app["state"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")
    inst = svc.get_institution(app["institution_id"])
    if not svc.has_approved_market(inst["id"]):
        fail("ERR_TARGET_MARKET_NOT_APPROVED")
    if not inst["accountability_satisfied"]:
        fail("ERR_ACCOUNTABILITY_NOT_SATISFIED")
    if app["financing_activity_pct_claimed"] < FINANCING_ACTIVITY_MIN_PCT:
        fail("ERR_FINANCING_ACTIVITY_BELOW_MINIMUM")
    app["state"] = "SUBMITTED"
    app["submitted_by_user_id"] = caller.user_id
    touch(app)
    return ok(app)


@bp.post("/certification-applications/<application_id>/begin-review")
def begin_review(application_id):
    caller = authenticate(("CertificationReviewer",))
    app = svc.get_cert_app(application_id)
    if app["state"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    app["state"] = "UNDER_REVIEW"
    app["reviewed_by_user_id"] = caller.user_id
    touch(app)
    return ok(app)


@bp.post("/certification-applications/<application_id>/evaluate-test")
def evaluate_test(application_id):
    authenticate(("CertificationReviewer",))
    app = svc.get_cert_app(application_id)
    data = shape.body()
    test_code = shape.req_enum(data, "test_code", TEST_CODES)
    verdict = shape.req_enum(data, "verdict", VERDICTS)
    shape.opt_str(data, "evidence_note")
    if app["state"] != "UNDER_REVIEW":
        fail("ERR_APPLICATION_NOT_UNDER_REVIEW")
    inst = svc.get_institution(app["institution_id"])
    if test_code == "TARGET_MARKET" and not svc.has_approved_market(inst["id"]):
        fail("ERR_TARGET_MARKET_NOT_APPROVED")
    if test_code == "ACCOUNTABILITY" and not inst["accountability_satisfied"]:
        fail("ERR_ACCOUNTABILITY_NOT_SATISFIED")
    # A self-loop: the docket's own state stays UNDER_REVIEW.
    app[TEST_FIELD[test_code]] = verdict
    touch(app)
    return ok(app)


@bp.post("/certification-applications/<application_id>/request-info")
def request_info(application_id):
    authenticate(("CertificationReviewer",))
    app = svc.get_cert_app(application_id)
    data = shape.body()
    reason = shape.req_str(data, "info_requested_reason", 1)
    if app["state"] != "UNDER_REVIEW":
        fail("ERR_APPLICATION_NOT_UNDER_REVIEW")
    app["info_requested_reason"] = reason
    if app["revision_round"] < MAX_REVISION_ROUND:
        app["state"] = "INFO_REQUESTED"
        app["revision_round"] = app["revision_round"] + 1
    else:
        # The cycle is exhausted: the same action terminates the docket.
        app["state"] = "DENIED"
        app["revision_round"] = app["revision_round"] + 1
        app["decided_at"] = fmt_dt(now())
    touch(app)
    return ok(app)


@bp.post("/certification-applications/<application_id>/resubmit")
def resubmit_application(application_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, _owning(application_id))
    app = svc.get_cert_app(application_id)
    data = shape.body()
    mission = shape.opt_str(data, "primary_mission_statement", MISSION_MIN_LEN)
    claimed = shape.opt_dec(data, "financing_activity_pct_claimed", places=2,
                            minimum=0, maximum=100)
    services_desc = shape.opt_str(data, "development_services_description",
                                  SERVICES_MIN_LEN)
    if app["state"] != "INFO_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if mission is not None:
        app["primary_mission_statement"] = mission
    if claimed is not None:
        app["financing_activity_pct_claimed"] = claimed
    if services_desc is not None:
        app["development_services_description"] = services_desc
    if app["revision_round"] <= 1:
        app["state"] = "UNDER_REVIEW"
        app["info_requested_reason"] = None
        for field in svc.TEST_FIELDS:
            if app[field] == "FAILED":
                app[field] = "PENDING"
    else:
        app["state"] = "DENIED"
        app["decided_at"] = fmt_dt(now())
    touch(app)
    return ok(app)


@bp.post("/certification-applications/<application_id>/decide")
def decide_application(application_id):
    caller = authenticate(("CertificationReviewer",))
    existing = db.cert_apps.get(application_id)
    if existing is not None:
        segregation(caller, existing["reviewed_by_user_id"])
    app = svc.get_cert_app(application_id)
    if app["state"] != "UNDER_REVIEW":
        fail("ERR_APPLICATION_NOT_UNDER_REVIEW")
    verdicts = [app[field] for field in svc.TEST_FIELDS]
    if any(v == "PENDING" for v in verdicts):
        fail("ERR_TEST_VERDICT_PENDING")
    clock = now()
    if all(v in ("PASSED", "WAIVED") for v in verdicts):
        app["state"] = "CERTIFIED"
        app["decided_at"] = fmt_dt(clock)
        touch(app)
        inst = svc.get_institution(app["institution_id"])
        inst["certification_state"] = "CERTIFIED"
        inst["certified_at"] = fmt_dt(clock)
        inst["recertification_due_at"] = fmt_dt(
            clock + timedelta(days=calc.RECERTIFICATION_INTERVAL_DAYS))
        touch(inst)
    else:
        app["state"] = "DENIED"
        app["decided_at"] = fmt_dt(clock)
        touch(app)
    return ok(app)
