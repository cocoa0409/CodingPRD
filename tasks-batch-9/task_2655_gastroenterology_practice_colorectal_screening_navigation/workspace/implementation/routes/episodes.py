"""Screening episodes: creation, closure, navigation and surveillance recommendations."""
from decimal import Decimal
from flask import Blueprint

from core import by_seq, db, dec, fail, new_record, now_iso, touch
from core import respond_list, respond_object
from calcs import (
    CLOSED_CLINICAL_STATUSES,
    MAX_OVERRIDE_DELTA_MONTHS,
    MAX_OVERRIDE_INTERVAL_MONTHS,
    MIN_INTERVAL_MONTHS,
    PREP_AT_RISK_THRESHOLD,
    PREP_CONFIRMED_THRESHOLD,
    computed_interval_months,
    finalized_pathology_aggregate,
)
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    opt_bool,
    opt_id,
    opt_int,
    opt_string,
    pagination,
    req_bool,
    req_date,
    req_enum,
    req_id,
    req_int,
)
from services import (
    build_episode,
    create_recommendation,
    episode_anchor_booking,
    get_episode,
    get_patient,
    get_referral,
    get_report,
    recompute_patient_counts,
    refresh_prep_score,
)

bp = Blueprint("episodes", __name__)

INDICATIONS = (
    "SCREENING_AVERAGE_RISK", "SCREENING_HIGH_RISK", "SURVEILLANCE", "DIAGNOSTIC_FOLLOWUP",
)
CLINICAL_STATUSES = (
    "OPEN", "PROCEDURE_SCHEDULED", "PATHOLOGY_PENDING",
    "CLOSED_SURVEILLANCE_SET", "CLOSED_DECLINED", "CLOSED_SUPERSEDED",
)
NAVIGATION_STATUSES = (
    "NOT_STARTED", "OUTREACH_ACTIVE", "PREP_AT_RISK", "PREP_CONFIRMED", "NAVIGATION_COMPLETE",
)
CLOSURE_REASONS = ("PATIENT_DECLINED", "LOST_TO_FOLLOW_UP", "SUPERSEDED_BY_OTHER_PATHWAY")
CHANNELS = ("PHONE", "SMS", "PORTAL", "MAIL")
ACCEPTED_REFERRAL_STATUSES = ("ACCEPTED_OPEN_ACCESS", "ACCEPTED_OFFICE_VISIT")


def _navigation_open(episode):
    if episode["clinical_status"] in CLOSED_CLINICAL_STATUSES:
        fail("ERR_INVALID_EPISODE_STATE",
             "The episode's clinical dimension has closed (%s)." % episode["clinical_status"])
    if episode["navigation_status"] == "NAVIGATION_COMPLETE":
        fail("ERR_INVALID_EPISODE_STATE", "Navigation on this episode is complete.")


@bp.post("/screening-episodes")
def create_episode():
    auth("ReferralCoordinator", "PatientNavigator")
    data = body()
    patient_id = req_id(data, "patient_id")
    indication = req_enum(data, "indication", INDICATIONS)
    referral_id = opt_id(data, "referral_id")
    preceding_episode_id = opt_id(data, "preceding_episode_id")

    patient = get_patient(patient_id)
    referral = get_referral(referral_id) if referral_id is not None else None
    if preceding_episode_id is not None:
        get_episode(preceding_episode_id)

    if referral is not None and referral["status"] not in ACCEPTED_REFERRAL_STATUSES:
        fail("ERR_REFERRAL_NOT_ACCEPTED",
             "Referral %s is in %s." % (referral_id, referral["status"]))

    for other in db.episodes.values():
        if other["patient_id"] == patient_id and other["indication"] == indication and \
                other["clinical_status"] in ("OPEN", "PROCEDURE_SCHEDULED", "PATHOLOGY_PENDING"):
            fail("ERR_DUPLICATE_OPEN_EPISODE",
                 "The patient already holds a live %s episode." % indication)

    if referral_id is not None:
        origin = "REFERRAL"
    elif preceding_episode_id is not None:
        origin = "SURVEILLANCE_RECALL"
    else:
        origin = "DIRECT"

    episode = build_episode(patient, indication, referral_id, preceding_episode_id, origin)
    recompute_patient_counts(patient)
    return respond_object(episode, 201)


@bp.get("/screening-episodes/<episode_id>")
def read_episode(episode_id):
    user_id, role = auth(
        "PracticeAdmin", "ReferralCoordinator", "PatientNavigator", "Endoscopist", "Patient"
    )
    episode = get_episode(episode_id)
    if role == "Patient" and user_id != episode["patient_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A Patient may read only their own episodes.")
    return respond_object(episode)


@bp.get("/screening-episodes")
def list_episodes():
    auth("PracticeAdmin", "ReferralCoordinator", "PatientNavigator", "Endoscopist")
    limit, offset = pagination()
    patient_id = filter_value("patient_id")
    referral_id = filter_value("referral_id")
    preceding_episode_id = filter_value("preceding_episode_id")
    clinical_status = filter_enum("clinical_status", CLINICAL_STATUSES)
    navigation_status = filter_enum("navigation_status", NAVIGATION_STATUSES)
    indication = filter_enum("indication", INDICATIONS)
    rows = by_seq(list(db.episodes.values()))
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if preceding_episode_id is not None:
        rows = [r for r in rows if r["preceding_episode_id"] == preceding_episode_id]
    if clinical_status is not None:
        rows = [r for r in rows if r["clinical_status"] == clinical_status]
    if navigation_status is not None:
        rows = [r for r in rows if r["navigation_status"] == navigation_status]
    if indication is not None:
        rows = [r for r in rows if r["indication"] == indication]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


@bp.post("/screening-episodes/<episode_id>/close")
def close_episode(episode_id):
    auth("PatientNavigator", "ReferralCoordinator")
    data = body()
    reason = req_enum(data, "reason", CLOSURE_REASONS)
    episode = get_episode(episode_id)
    if episode["clinical_status"] != "OPEN":
        fail("ERR_INVALID_EPISODE_STATE",
             "Only an OPEN episode may be closed, not %s." % episode["clinical_status"])
    episode["closure_reason"] = reason
    episode["clinical_status"] = (
        "CLOSED_SUPERSEDED" if reason == "SUPERSEDED_BY_OTHER_PATHWAY" else "CLOSED_DECLINED"
    )
    touch(episode)
    patient = db.patients.get(episode["patient_id"])
    if patient is not None:
        recompute_patient_counts(patient)
    return respond_object(episode)


@bp.post("/screening-episodes/<episode_id>/outreach")
def record_outreach(episode_id):
    auth("PatientNavigator")
    data = body()
    channel = req_enum(data, "channel", CHANNELS)
    acknowledged = opt_bool(data, "acknowledged", False)

    episode = get_episode(episode_id)
    _navigation_open(episode)

    episode["outreach_log"].append({
        "channel": channel,
        "occurred_at": now_iso(),
        "acknowledged": acknowledged,
    })
    score = refresh_prep_score(episode)
    if dec(score) >= PREP_AT_RISK_THRESHOLD:
        if episode["navigation_status"] in ("NOT_STARTED", "OUTREACH_ACTIVE", "PREP_AT_RISK"):
            episode["navigation_status"] = "OUTREACH_ACTIVE"
    else:
        if episode["navigation_status"] in ("NOT_STARTED", "OUTREACH_ACTIVE", "PREP_AT_RISK"):
            episode["navigation_status"] = "PREP_AT_RISK"
    touch(episode)
    return respond_object(episode)


@bp.post("/screening-episodes/<episode_id>/prep-attestation")
def prep_attestation(episode_id):
    user_id, _role = auth("Patient")
    data = body()
    regimen_completed = req_bool(data, "regimen_completed")

    episode = get_episode(episode_id)
    if user_id != episode["patient_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A Patient may attest only on their own episode.")
    _navigation_open(episode)

    episode["prep_attestation"] = "COMPLETED" if regimen_completed else "NOT_COMPLETED"
    score = refresh_prep_score(episode)
    if dec(score) >= PREP_CONFIRMED_THRESHOLD:
        episode["navigation_status"] = "PREP_CONFIRMED"
    else:
        episode["navigation_status"] = "PREP_AT_RISK"
    touch(episode)
    return respond_object(episode)


@bp.post("/screening-episodes/<episode_id>/noninvasive-tests")
def order_test(episode_id):
    auth("ReferralCoordinator", "PatientNavigator")
    data = body()
    test_type = req_enum(data, "test_type", ("FIT", "MT_SDNA"))
    collected_date = req_date(data, "collected_date")

    episode = get_episode(episode_id)
    if episode["clinical_status"] in CLOSED_CLINICAL_STATUSES:
        fail("ERR_INVALID_EPISODE_STATE",
             "The episode is closed (%s)." % episode["clinical_status"])

    test = new_record({
        "episode_id": episode["id"],
        "test_type": test_type,
        "collected_date": collected_date,
        "result": "PENDING",
        "resulted_at": None,
        "follow_up_episode_id": None,
    })
    db.tests[test["id"]] = test
    return respond_object(test, 201)


@bp.post("/screening-episodes/<episode_id>/surveillance-recommendations")
def create_surveillance_recommendation(episode_id):
    user_id, _role = auth("Endoscopist", "PracticeAdmin")
    data = body()
    pathology_report_id = opt_id(data, "pathology_report_id")
    override_interval_months = opt_int(data, "override_interval_months")
    override_reason = opt_string(data, "override_reason", minlen=0)
    expected_episode_version = req_int(data, "expected_episode_version")

    episode = get_episode(episode_id)
    report = get_report(pathology_report_id) if pathology_report_id is not None else None

    if episode["clinical_status"] != "CLOSED_SURVEILLANCE_SET":
        fail("ERR_INVALID_EPISODE_STATE",
             "A recommendation requires clinical_status CLOSED_SURVEILLANCE_SET, not %s."
             % episode["clinical_status"])

    if expected_episode_version != episode["version"]:
        fail("ERR_STALE_EPISODE_VERSION",
             "expected_episode_version %s does not match %s."
             % (expected_episode_version, episode["version"]))

    anchor = episode_anchor_booking(episode["id"])
    if report is not None:
        report_booking = db.bookings.get(report["booking_id"])
        if report["status"] != "FINALIZED" or report_booking is None or \
                report_booking["episode_id"] != episode["id"]:
            fail("ERR_PATHOLOGY_NOT_FINALIZED",
                 "The anchoring pathology report is not FINALIZED on this episode's booking.")
        anchor = report_booking
    if anchor is None:
        fail("ERR_INVALID_EPISODE_STATE", "The episode has no anchoring procedure booking.")

    computed = computed_interval_months(
        finalized_pathology_aggregate(anchor["id"]),
        episode["risk_tier_snapshot"],
        anchor.get("prep_quality_bbps"),
    )

    if override_interval_months is not None:
        if override_interval_months < MIN_INTERVAL_MONTHS or \
                override_interval_months > MAX_OVERRIDE_INTERVAL_MONTHS:
            fail("ERR_OVERRIDE_OUT_OF_RANGE",
                 "override_interval_months must be between %d and %d."
                 % (MIN_INTERVAL_MONTHS, MAX_OVERRIDE_INTERVAL_MONTHS))
        if abs(override_interval_months - computed) > MAX_OVERRIDE_DELTA_MONTHS:
            fail("ERR_OVERRIDE_OUT_OF_RANGE",
                 "override_interval_months may differ from the computed interval by at most %d."
                 % MAX_OVERRIDE_DELTA_MONTHS)
        if override_reason is None or override_reason.strip() == "":
            fail("ERR_OVERRIDE_OUT_OF_RANGE", "An override requires a non-empty override_reason.")
        if user_id == anchor["performing_endoscopist_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The performing endoscopist may not attest the override.")

    rec = create_recommendation(
        episode, anchor, pathology_report_id, override_interval_months, override_reason, user_id
    )
    touch(episode)
    return respond_object(rec, 201)
