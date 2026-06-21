"""Appeals and record transmittal."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc

bp = Blueprint("appeals", __name__)


@bp.post("/appeals")
def create_appeal():
    _, role = get_actor()
    require_role(role, {"Attorney"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    judgment_id = validate.require_str(data, "judgment_id")
    appellant_party_id = validate.require_str(data, "appellant_party_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    judgment = domain.get_or_404(db.judgments, judgment_id)
    party = domain.get_or_404(db.parties, appellant_party_id)

    validate.require(data, "filed_on")
    filed_on = data["filed_on"]
    if calc.parse_dt(filed_on) is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid filed_on")
    record_page_count = validate.non_negative_int(data, "record_page_count", required=False, default=0)
    validate.require(data, "expected_case_version")
    expected_case_version = data["expected_case_version"]
    if not isinstance(expected_case_version, int) or isinstance(expected_case_version, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_case_version must be an integer")

    # Same-case referential integrity (priority 5).
    if judgment["case_id"] != case_id or party["case_id"] != case_id:
        raise errors.err(errors.ERR_CROSS_CASE_REFERENCE, "FK belongs to a different case")

    # OCC check (priority 6).
    if expected_case_version != case["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale case version")

    # State check (priority 7).
    if case["status"] != "JUDGMENT_ENTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not JUDGMENT_ENTERED")

    # Appeal-window check (priority 13): filed_on within appeal_window_days of
    # judgment.entered_at, inclusive.
    court = db.courts[case["court_id"]]
    entered_date = calc.to_date(judgment["entered_at"])
    deadline_date = entered_date + timedelta(days=court["appeal_window_days"])
    filed_date = calc.to_date(filed_on)
    if filed_date > deadline_date:
        raise errors.err(errors.ERR_APPEAL_WINDOW_CLOSED, "Appeal window has closed")

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "judgment_id": judgment_id,
        "appellant_party_id": appellant_party_id,
        "filed_on": filed_on,
        "status": "NOTICE_FILED",
        "record_page_count": record_page_count,
        "transmittal_fee_cents": None,
        "transmitted_at": None,
    })
    db.appeals[rec["id"]] = rec

    # Cascade: judgment ENTERED -> APPEALED; case JUDGMENT_ENTERED -> ON_APPEAL.
    judgment["status"] = "APPEALED"
    db.touch(judgment)
    case["status"] = "ON_APPEAL"
    domain.bump_case(case)

    return success(domain._clean(rec), status=201)


@bp.get("/appeals/<appeal_id>")
def get_appeal(appeal_id):
    get_actor()
    rec = domain.get_or_404(db.appeals, appeal_id)
    return success(domain._clean(rec), status=200)


@bp.get("/appeals")
def list_appeals():
    get_actor()
    args = request.args
    items = list(db.appeals.values())
    for field in ("case_id", "judgment_id", "appellant_party_id", "status"):
        val = args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(a) for a in window], status=200, pagination=pagination)


@bp.post("/appeals/<appeal_id>/prepare-record")
def prepare_record(appeal_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    data = validate.body(request)
    a = domain.get_or_404(db.appeals, appeal_id)
    if a["status"] != "NOTICE_FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appeal is not NOTICE_FILED")
    record_page_count = validate.non_negative_int(data, "record_page_count", required=True)
    if record_page_count <= 0:
        raise errors.err(errors.ERR_EMPTY_RECORD, "Record is empty")
    a["record_page_count"] = record_page_count
    a["status"] = "RECORD_PREPARED"
    a["transmittal_fee_cents"] = calc.appeal_transmittal_fee(record_page_count)
    db.touch(a)
    return success(domain._clean(a), status=200)


@bp.post("/appeals/<appeal_id>/transmit")
def transmit(appeal_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    a = domain.get_or_404(db.appeals, appeal_id)
    if a["status"] != "RECORD_PREPARED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appeal is not RECORD_PREPARED")
    a["status"] = "TRANSMITTED"
    a["transmitted_at"] = _clock_iso()
    db.touch(a)
    return success(domain._clean(a), status=200)


@bp.post("/appeals/<appeal_id>/dismiss")
def dismiss(appeal_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    a = domain.get_or_404(db.appeals, appeal_id)
    if a["status"] not in ("NOTICE_FILED", "RECORD_PREPARED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Appeal cannot be dismissed from its state")
    a["status"] = "DISMISSED"
    db.touch(a)

    # Cascade: if no other non-terminal appeal remains, restore judgment + case.
    others_active = any(
        other["id"] != a["id"] and other["status"] not in ("TRANSMITTED", "DISMISSED")
        for other in domain.appeals_for_case(a["case_id"])
    )
    if not others_active:
        judgment = db.judgments.get(a["judgment_id"])
        if judgment and judgment["status"] == "APPEALED":
            judgment["status"] = "ENTERED"
            db.touch(judgment)
        case = db.cases.get(a["case_id"])
        if case and case["status"] == "ON_APPEAL":
            case["status"] = "JUDGMENT_ENTERED"
            domain.bump_case(case)
    return success(domain._clean(a), status=200)


def _clock_iso():
    dt = db.now_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
