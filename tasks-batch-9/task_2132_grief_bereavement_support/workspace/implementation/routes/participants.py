"""Participants, assessments, outcome measurement, withdrawal and holds (§3.2, §3.8)."""

from flask import Blueprint, request

from core import calc
from core.auth import authenticate, own_participant
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import ASSESSMENT_KINDS, INSTRUMENTS, body, opt_bool, req_bool, req_enum, req_int
from core.store import public, store
from services import cascade, derive
from services.state import must_exist, require_participant_active, transition

bp = Blueprint("participants", __name__)


@bp.route("/bereavement/participants/<pid>", methods=["GET"])
def read_participant(pid):
    ctx = authenticate(["IntakeCoordinator", "ProgramDirector", "Counselor", "Participant"])
    participant = must_exist("Participant", pid)
    own_participant(ctx, participant)
    return ok(public(participant))


@bp.route("/bereavement/participants", methods=["GET"])
def list_participants():
    authenticate(["IntakeCoordinator", "ProgramDirector"])
    rows = store.all("Participant")
    for key in ("referral_id", "service_status", "risk_tier", "loss_type"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


def _participant_assessments(pid):
    return store.find("Assessment", participant_id=pid)


@bp.route("/bereavement/participants/<pid>/assessments", methods=["POST"])
def record_assessment(pid):
    authenticate(["IntakeCoordinator", "Counselor"])
    participant = must_exist("Participant", pid)
    data = body()
    kind = req_enum(data, "kind", ASSESSMENT_KINDS)
    instrument = req_enum(data, "instrument", INSTRUMENTS)
    grief = req_int(data, "grief_severity", 0, 40)
    isolation = req_int(data, "isolation_index", 0, 20)
    functional = req_int(data, "functional_impairment", 0, 20)
    suicidality = opt_bool(data, "suicidality_flag", False)

    require_participant_active(participant)

    existing = _participant_assessments(pid)
    if kind in ("MIDPOINT", "EXIT"):
        if not any(a["kind"] == "BASELINE" for a in existing):
            raise ApiError("ERR_ASSESSMENT_SEQUENCE_INVALID",
                           "A BASELINE assessment must exist before a %s assessment." % kind)

    raw_total = grief + isolation + functional
    assessment = store.create("Assessment", {
        "participant_id": pid,
        "kind": kind,
        "instrument": instrument,
        "grief_severity": grief,
        "isolation_index": isolation,
        "functional_impairment": functional,
        "suicidality_flag": suicidality,
        "raw_total": raw_total,
        "normalized_score": calc.normalized_score(raw_total),
        "recorded_at": store.now_iso(),
        "sequence_index": len(existing) + 1,
    })

    changed = False
    if kind == "NEEDS":
        composite = calc.composite_need_index(grief, isolation, functional, suicidality)
        participant["composite_need_index"] = composite
        derive.apply_tier(participant, calc.risk_tier(composite))
        if participant["service_status"] == "INTAKE":
            participant["service_status"] = "ASSESSED"
        changed = True
    elif kind == "BASELINE":
        participant["baseline_score"] = assessment["normalized_score"]
        changed = True
    else:
        participant["latest_score"] = assessment["normalized_score"]
        if kind == "EXIT" and participant["service_status"] == "MAINTENANCE":
            participant["service_status"] = "DISCHARGED"
        changed = True
    if changed:
        store.touch(participant)
    return created(public(assessment))


@bp.route("/bereavement/participants/<pid>/assessments", methods=["GET"])
def list_assessments(pid):
    authenticate(["IntakeCoordinator", "ProgramDirector", "Counselor"])
    must_exist("Participant", pid)
    rows = _participant_assessments(pid)
    kind = request.args.get("kind")
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    return listing(rows, public)


def _sort_key_recorded(rec):
    return (rec["recorded_at"], rec["created_at"], rec["_seq"])


@bp.route("/bereavement/participants/<pid>/outcome-summary", methods=["GET"])
def outcome_summary(pid):
    authenticate(["IntakeCoordinator", "ProgramDirector", "Counselor"])
    participant = must_exist("Participant", pid)
    rows = _participant_assessments(pid)

    baselines = sorted([r for r in rows if r["kind"] == "BASELINE"], key=_sort_key_recorded)
    if not baselines:
        raise ApiError("ERR_NO_BASELINE_ASSESSMENT",
                       "The participant has no BASELINE assessment on file.")
    baseline = baselines[0]
    laters = sorted([r for r in rows if r["kind"] in ("MIDPOINT", "EXIT")],
                    key=_sort_key_recorded, reverse=True)
    latest = laters[0] if laters else None

    ratio = calc.attendance_ratio_capped(participant["sessions_attended_total"])
    summary = {
        "participant_id": pid,
        "baseline_score": baseline["normalized_score"],
        "latest_score": None,
        "raw_delta": None,
        "rtm_correction": None,
        "attendance_ratio_capped": ratio,
        "attendance_adjusted_delta": None,
        "sessions_attended_total": participant["sessions_attended_total"],
    }
    if latest is not None:
        raw = calc.raw_delta(latest["normalized_score"], baseline["normalized_score"])
        correction = calc.rtm_correction(baseline["normalized_score"])
        summary["latest_score"] = latest["normalized_score"]
        summary["raw_delta"] = raw
        summary["rtm_correction"] = correction
        summary["attendance_adjusted_delta"] = calc.attendance_adjusted_delta(raw, correction, ratio)
    return ok(summary)


@bp.route("/bereavement/participants/<pid>/withdraw", methods=["POST"])
def withdraw(pid):
    ctx = authenticate(["IntakeCoordinator", "Participant"])
    participant = must_exist("Participant", pid)
    own_participant(ctx, participant)
    body()
    require_participant_active(participant)
    if participant["service_status"] == "DISCHARGED":
        raise ApiError("ERR_INVALID_STATE", "A discharged participant cannot be withdrawn.")
    cascade.withdraw_participant(participant)
    return ok(public(participant))


@bp.route("/bereavement/participants/<pid>/outreach-hold", methods=["POST"])
def outreach_hold(pid):
    ctx = authenticate(["IntakeCoordinator", "Participant"])
    participant = must_exist("Participant", pid)
    own_participant(ctx, participant)
    data = body()
    hold = req_bool(data, "hold")
    require_participant_active(participant)
    if hold:
        if participant["outreach_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Outreach is not in SCHEDULED state.")
        participant["outreach_status"] = "ON_HOLD"
    else:
        if participant["outreach_status"] != "ON_HOLD":
            raise ApiError("ERR_INVALID_STATE", "Outreach is not on hold.")
        participant["outreach_status"] = "SCHEDULED"
    store.touch(participant)
    return ok(public(participant))


@bp.route("/bereavement/participants/<pid>/anniversary-outreaches", methods=["GET"])
def list_outreaches(pid):
    authenticate(["IntakeCoordinator", "ProgramDirector", "VolunteerCompanion"])
    must_exist("Participant", pid)
    rows = store.find("AnniversaryOutreach", participant_id=pid)
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (derive.occasion_rank(r), r["_seq"]))
    return listing(rows, public)
