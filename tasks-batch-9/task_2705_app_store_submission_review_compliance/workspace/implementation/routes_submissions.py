"""Submissions, their metadata locales, age rating, privacy label and review."""
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import flows
from common import (DISCLOSURE_PASS_THRESHOLD, PRE_REVIEW_FRESHNESS_HOURS,
                    arg_bool, arg_filter, body_json, endpoint, fail, fmt_iso,
                    get_row, hours, new_row, now_dt, now_iso, ok, paginate,
                    parse_iso, public, resolve, rows, scope_rows, touch)
from valid import (check_unknown, opt_array, opt_bool, opt_int, opt_str,
                   req_array, req_bool, req_id, req_int, req_object, req_str)

bp = Blueprint("submissions", __name__)

RELEASE_MODES = {"IMMEDIATE", "PHASED", "MANUAL"}
RATING_BANDS = [0, 4, 9, 12, 17, 18]
DATA_TYPES = {"PRECISE_LOCATION", "CONTACTS", "DEVICE_ID", "EMAIL",
              "PURCHASE_HISTORY", "HEALTH", "USAGE_DATA"}
PURPOSES = {"ANALYTICS", "ADVERTISING", "APP_FUNCTIONALITY", "PERSONALIZATION",
            "THIRD_PARTY_SHARING"}
USABLE_CREDENTIAL_STATES = ("ACTIVE", "EXPIRING_SOON")
READ_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
              "PlatformReviewer", "PlatformAppealBoard", "PlatformPolicyAdmin",
              "Auditor"]
LOCALE_READ_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
                     "PlatformReviewer", "PlatformPolicyAdmin", "Auditor"]


# --------------------------------------------------------------------------
# Shared content rules (priority 55/60), used as hard errors and in report mode
# --------------------------------------------------------------------------
def credential_problem(app, credential):
    """Return (error_id, message) for an unusable credential, else None."""
    if credential is None:
        return ("ERR_SIGNING_CREDENTIAL_INVALID", "no signing credential")
    if credential["credential_type"] != "PROVISIONING_PROFILE":
        return ("ERR_SIGNING_CREDENTIAL_INVALID",
                "a PROVISIONING_PROFILE is required")
    if credential["status"] not in USABLE_CREDENTIAL_STATES:
        return ("ERR_SIGNING_CREDENTIAL_INVALID",
                "the credential status is %s" % credential["status"])
    if credential["platform"] != app["platform"]:
        return ("ERR_CREDENTIAL_PLATFORM_MISMATCH",
                "credential platform differs from the app platform")
    if parse_iso(credential["not_before"]) > now_dt():
        return ("ERR_CREDENTIAL_NOT_YET_VALID", "not_before is in the future")
    linked = get_row("signing_credential", credential.get("linked_cert_id"))
    if linked is None or linked["status"] not in USABLE_CREDENTIAL_STATES:
        return ("ERR_LINKED_CERT_NOT_ACTIVE",
                "the linked certificate is not usable")
    return None


def check_credential(app, credential):
    problem = credential_problem(app, credential)
    if problem is not None:
        fail(problem[0], problem[1])


def mapping_coverage_complete(app):
    mappings = calc.mappings_of_app(app["id"])
    effective_ids = set()
    for rule in rows("guideline_rule"):
        if rule["status"] != "EFFECTIVE":
            continue
        effective_ids.add(rule["id"])
        if rule["requires_feature_mapping"]:
            if not any(m["guideline_rule_id"] == rule["id"] for m in mappings):
                return False
    covered = [m for m in mappings if m["guideline_rule_id"] in effective_ids]
    if not covered:
        return False
    for mapping in covered:
        if mapping["self_review_status"] not in ("PASSED", "WAIVED_BY_PLATFORM"):
            return False
    return True


def locales_of(submission_id):
    return [r for r in rows("metadata_locale")
            if r["submission_id"] == submission_id]


def metadata_problem(submission):
    """None, 'METADATA_INCOMPLETE' or 'SCREENSHOT_SET_EMPTY'."""
    locales = locales_of(submission["id"])
    if not locales:
        return "METADATA_INCOMPLETE"
    if len([l for l in locales if l.get("is_primary")]) != 1:
        return "METADATA_INCOMPLETE"
    for locale in locales:
        if not locale.get("is_complete"):
            return "SCREENSHOT_SET_EMPTY"
    return None


def age_rating_understated(submission):
    derived = submission.get("derived_age_rating")
    attested = submission.get("attested_age_rating")
    if derived is None or attested is None:
        return True
    return attested < derived


def tracking_prompt_missing(submission):
    for item in submission.get("declared_privacy_items") or []:
        if isinstance(item, dict) and item.get("used_for_tracking"):
            if not submission.get("tracking_consent_prompt_present"):
                return True
    return False


def critical_finding_open(submission):
    return any(f["severity"] == "CRITICAL" and f["status"] in ("OPEN", "DISPUTED")
               for f in calc.findings_of_submission(submission["id"]))


def refund_expedites(submission):
    for req in rows("expedite_request"):
        if req["submission_id"] != submission["id"]:
            continue
        if req["state"] not in ("REQUESTED", "GRANTED", "CONSUMED"):
            continue
        req["state"] = "REFUNDED"
        req["refunded_at"] = now_iso()
        touch(req)
    app = get_row("app_record", submission["app_record_id"])
    account = calc.account_of_app(app) if app is not None else None
    if account is not None:
        calc.recompute_account_standing(account)


def void_attestation(submission):
    """Void the attestation: clear pre_review_passed, pre_review_checked_at and
    attested_by_user_id, and drive a PRE_REVIEW_PASSED build back to DRAFT."""
    submission["pre_review_passed"] = False
    submission["pre_review_checked_at"] = None
    submission["attested_by_user_id"] = None
    if submission["state"] == "PRE_REVIEW_PASSED":
        submission["state"] = "DRAFT"


# --------------------------------------------------------------------------
# Submission create / read
# --------------------------------------------------------------------------
@bp.route("/submissions", methods=["POST"])
@endpoint(["ReleaseManager"])
def create_submission():
    body = body_json()
    check_unknown(body, {"expected_app_record_version", "app_record_id",
                         "signing_credential_id", "build_number",
                         "version_string", "release_mode"})
    app, credential = resolve([
        ("app_record", body.get("app_record_id")),
        ("signing_credential", body.get("signing_credential_id")),
    ])
    expected = req_int(body, "expected_app_record_version")
    req_id(body, "app_record_id")
    req_id(body, "signing_credential_id")
    build_number = req_int(body, "build_number", minimum=1)
    version_string = req_str(body, "version_string", 1, 40)
    release_mode = opt_str(body, "release_mode", enum=RELEASE_MODES,
                           default="PHASED", nullable=False)
    if expected != app["version"]:
        fail("ERR_STALE_APP_RECORD_VERSION",
             "expected_app_record_version does not match")
    flows.posture_gate(app)
    flows.program_gate(calc.account_of_app(app))
    check_credential(app, credential)
    for existing in calc.submissions_of_app(app["id"]):
        if existing["state"] == "DEVELOPER_WITHDRAWN":
            continue
        if build_number <= existing["build_number"]:
            fail("ERR_DUPLICATE_BUILD_NUMBER",
                 "build_number must exceed every live build of this app")
    row = new_row("submission", {
        "app_record_id": app["id"],
        "signing_credential_id": credential["id"],
        "review_window_id": None,
        "build_number": build_number,
        "version_string": version_string,
        "release_mode": release_mode,
        "submission_channel": "STANDARD",
        "state": "DRAFT",
        "age_rating_answers": None,
        "attested_age_rating": None,
        "derived_age_rating": None,
        "age_rating_driving_dimension": None,
        "declared_privacy_items": [],
        "tracking_consent_prompt_present": False,
        "disclosure_accuracy_score_provisional": None,
        "disclosure_accuracy_score_final": None,
        "pre_review_passed": False,
        "pre_review_blocking_reasons": [],
        "pre_review_checked_at": None,
        "attested_by_user_id": None,
        "queued_at": None,
        "provisional_deadline_at": None,
        "priority_score": None,
        "priority_band": None,
        "effective_review_deadline_at": None,
        "reviewed_by_user_id": None,
        "decided_at": None,
        "rejected_at": None,
        "resubmission_count": 0,
        "metadata_locale_count": 0,
    })
    for other in calc.submissions_of_app(app["id"]):
        if other["id"] == row["id"] or other["state"] != "DRAFT":
            continue
        other["state"] = "DEVELOPER_WITHDRAWN"
        touch(other)
        refund_expedites(other)
    touch(app)
    return ok(public(row), 201)


@bp.route("/submissions", methods=["GET"])
@endpoint(READ_ROLES)
def list_submissions():
    items = rows("submission")
    for field in ("app_record_id", "signing_credential_id", "review_window_id",
                  "state", "priority_band", "submission_channel"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/submissions/<submission_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_submission(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    return ok(public(submission))


@bp.route("/submissions/<submission_id>/metadata-locales", methods=["GET"])
@endpoint(LOCALE_READ_ROLES)
def read_submission_locales(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    items = locales_of(submission["id"])
    locale = arg_filter("locale")
    if locale is not None:
        items = [r for r in items if r["locale"] == locale]
    primary = arg_bool("is_primary")
    if primary is not None:
        items = [r for r in items if bool(r.get("is_primary")) is primary]
    return paginate(items)


# --------------------------------------------------------------------------
# Content mutations: age rating and privacy declaration
# --------------------------------------------------------------------------
BOOLEAN_ANSWER_KEYS = ["real_money_gambling", "unrestricted_web_access",
                       "user_generated_content", "ugc_moderation_enabled",
                       "contests"]


def _validate_answers(answers):
    allowed = set(calc.DIMENSIONS) | set(BOOLEAN_ANSWER_KEYS)
    for key in answers.keys():
        if key not in allowed:
            fail("ERR_VALIDATION", "unknown age_rating_answers key %r" % key)
    for key in calc.DIMENSIONS:
        if key not in answers:
            fail("ERR_VALIDATION", "age_rating_answers.%s is required" % key)
        value = answers[key]
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_VALIDATION",
                 "age_rating_answers.%s must be an integer" % key)
        if value < 0 or value > 3:
            fail("ERR_VALIDATION",
                 "age_rating_answers.%s must be between 0 and 3" % key)
    for key in BOOLEAN_ANSWER_KEYS:
        if key not in answers:
            fail("ERR_VALIDATION", "age_rating_answers.%s is required" % key)
        if not isinstance(answers[key], bool):
            fail("ERR_VALIDATION",
                 "age_rating_answers.%s must be a boolean" % key)


@bp.route("/submissions/<submission_id>/age-rating", methods=["PUT"])
@endpoint(["ComplianceOfficer", "ReleaseManager"])
def set_age_rating(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    body = body_json()
    check_unknown(body, {"age_rating_answers", "attested_age_rating"})
    answers = req_object(body, "age_rating_answers")
    _validate_answers(answers)
    attested = req_int(body, "attested_age_rating")
    if attested not in RATING_BANDS:
        fail("ERR_VALIDATION",
             "attested_age_rating must be one of %s" % RATING_BANDS)
    if submission["state"] not in ("DRAFT", "PRE_REVIEW_PASSED"):
        fail("ERR_INVALID_SUBMISSION_STATE",
             "a %s submission is not editable" % submission["state"])
    app = get_row("app_record", submission["app_record_id"])
    flows.posture_gate(app)
    rating, dimension = calc.derived_age_rating(answers)
    submission["age_rating_answers"] = dict(answers)
    submission["attested_age_rating"] = attested
    submission["derived_age_rating"] = rating
    submission["age_rating_driving_dimension"] = dimension
    void_attestation(submission)
    touch(submission)
    return ok(public(submission))


@bp.route("/submissions/<submission_id>/privacy-declaration", methods=["PUT"])
@endpoint(["ComplianceOfficer"])
def set_privacy_declaration(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    body = body_json()
    check_unknown(body, {"declared_privacy_items", "tracking_consent_prompt_present"})
    items = req_array(body, "declared_privacy_items", member_type=dict)
    for item in items:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION",
                 "declared_privacy_items members must be objects")
        for key in item.keys():
            if key not in ("data_type", "purpose", "linked_to_user",
                           "used_for_tracking"):
                fail("ERR_VALIDATION",
                     "unknown declared_privacy_items key %r" % key)
        if item.get("data_type") not in DATA_TYPES:
            fail("ERR_VALIDATION",
                 "declared_privacy_items.data_type must be one of %s"
                 % sorted(DATA_TYPES))
        if item.get("purpose") not in PURPOSES:
            fail("ERR_VALIDATION",
                 "declared_privacy_items.purpose must be one of %s"
                 % sorted(PURPOSES))
        for key in ("linked_to_user", "used_for_tracking"):
            if not isinstance(item.get(key), bool):
                fail("ERR_VALIDATION",
                     "declared_privacy_items.%s must be a boolean" % key)
    prompt = req_bool(body, "tracking_consent_prompt_present")
    if submission["state"] not in ("DRAFT", "PRE_REVIEW_PASSED"):
        fail("ERR_INVALID_SUBMISSION_STATE",
             "a %s submission is not editable" % submission["state"])
    app = get_row("app_record", submission["app_record_id"])
    flows.posture_gate(app)
    submission["declared_privacy_items"] = [dict(i) for i in items]
    submission["tracking_consent_prompt_present"] = prompt
    void_attestation(submission)
    # A declaration mutation rewrites the provisional score only; the final variant is
    # rewritten when a reviewer claims the build and again at the decision gate.
    calc.recompute_provisional_score(submission, bump=False)
    touch(submission)
    return ok(public(submission))


# --------------------------------------------------------------------------
# The self-review report and queue entry
# --------------------------------------------------------------------------
def blocking_reasons(submission, app, credential):
    """The report-mode codes, in the fixed §3.7 sequence."""
    codes = []
    meta = metadata_problem(submission)
    if meta is not None:
        codes.append(meta)
    if age_rating_understated(submission):
        codes.append("AGE_RATING_UNDERSTATED")
    if tracking_prompt_missing(submission):
        codes.append("TRACKING_CONSENT_PROMPT_MISSING")
    score = submission.get("disclosure_accuracy_score_provisional")
    if score is None or Decimal(str(score)) < DISCLOSURE_PASS_THRESHOLD:
        codes.append("PRIVACY_DISCLOSURE_INACCURATE")
    if critical_finding_open(submission):
        codes.append("CRITICAL_FINDING_UNRESOLVED")
    if not mapping_coverage_complete(app):
        codes.append("GUIDELINE_MAPPING_INCOMPLETE")
    if credential_problem(app, credential) is not None:
        codes.append("SIGNING_CREDENTIAL_INVALID")
    return codes


@bp.route("/submissions/<submission_id>/pre-review-check", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def pre_review_check(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    if submission["state"] != "DRAFT":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "only a DRAFT submission may run the self-review check")
    app = get_row("app_record", submission["app_record_id"])
    flows.posture_gate(app)
    flows.program_gate(calc.account_of_app(app))
    submission["pre_review_checked_at"] = now_iso()
    calc.recompute_provisional_score(submission, bump=False)
    credential = get_row("signing_credential", submission["signing_credential_id"])
    codes = blocking_reasons(submission, app, credential)
    submission["pre_review_blocking_reasons"] = codes
    if codes:
        submission["pre_review_passed"] = False
        submission["attested_by_user_id"] = None
    else:
        submission["pre_review_passed"] = True
        submission["attested_by_user_id"] = g.user_id
        submission["state"] = "PRE_REVIEW_PASSED"
    touch(submission)
    return ok(public(submission))


@bp.route("/submissions/<submission_id>/queue", methods=["POST"])
@endpoint(["ReleaseManager"])
def queue_submission(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    body = body_json()
    check_unknown(body, {"expedite_request_id"})
    expedite = None
    if body.get("expedite_request_id") is not None:
        (expedite,) = resolve([("expedite_request", body.get("expedite_request_id"))])
    if submission["state"] != "PRE_REVIEW_PASSED":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "only a PRE_REVIEW_PASSED submission may be queued")
    app = get_row("app_record", submission["app_record_id"])
    account = calc.account_of_app(app)
    flows.posture_gate(app, release_advancing=True)
    flows.program_gate(account)
    # --- priority 55: content safety -------------------------------------
    if age_rating_understated(submission):
        fail("ERR_AGE_RATING_UNDERSTATED",
             "attested_age_rating is below the derived rating")
    if tracking_prompt_missing(submission):
        fail("ERR_TRACKING_CONSENT_PROMPT_MISSING",
             "declared tracking requires a consent prompt")
    score = submission.get("disclosure_accuracy_score_provisional")
    if score is None or Decimal(str(score)) < DISCLOSURE_PASS_THRESHOLD:
        fail("ERR_PRIVACY_DISCLOSURE_INACCURATE",
             "the provisional disclosure accuracy score is below the threshold")
    if critical_finding_open(submission):
        fail("ERR_CRITICAL_FINDING_UNRESOLVED",
             "a CRITICAL behaviour finding is still unresolved")
    # --- priority 60: referential integrity -------------------------------
    meta = metadata_problem(submission)
    if meta == "METADATA_INCOMPLETE":
        fail("ERR_METADATA_INCOMPLETE",
             "the submission needs exactly one primary metadata locale")
    if meta == "SCREENSHOT_SET_EMPTY":
        fail("ERR_SCREENSHOT_SET_INCOMPLETE",
             "a locale is short of the required screenshots")
    if not mapping_coverage_complete(app):
        fail("ERR_GUIDELINE_MAPPING_INCOMPLETE",
             "guideline mapping coverage is incomplete")
    for assessment in calc.assessments_of_app(app["id"]):
        if assessment["status"] not in ("REMEDIATED", "ACCEPTED_NO_CHANGE"):
            fail("ERR_REMEDIATION_INCOMPLETE",
                 "an impact assessment of this app is still %s"
                 % assessment["status"])
    credential = get_row("signing_credential", submission["signing_credential_id"])
    check_credential(app, credential)
    # --- priority 65: attestation freshness --------------------------------
    if not submission.get("pre_review_passed"):
        fail("ERR_PRE_REVIEW_NOT_PASSED", "the self-review has not passed")
    checked = parse_iso(submission.get("pre_review_checked_at"))
    if checked is None or now_dt() - checked > hours(PRE_REVIEW_FRESHNESS_HOURS):
        fail("ERR_PRE_REVIEW_STALE", "the self-review attestation is stale")
    if expedite is not None:
        if (expedite["submission_id"] != submission["id"]
                or expedite["state"] != "GRANTED"):
            fail("ERR_INVALID_EXPEDITE_STATE",
                 "the cited expedite request is not a GRANTED request of this build")
    # --- capacity, then the pinned forward pass ----------------------------
    window = calc.select_capacity_window(app)
    if window is None:
        fail("ERR_NO_REVIEW_CAPACITY", "no review capacity window is eligible")
    scratch = dict(submission)
    if expedite is not None:
        scratch["submission_channel"] = "EXPEDITED"
    calc.priority_pass(scratch, account, first_time=True)
    if parse_iso(credential["not_after"]) <= parse_iso(
            scratch["effective_review_deadline_at"]):
        fail("ERR_CREDENTIAL_EXPIRES_BEFORE_DEADLINE",
             "the signing credential expires at or before the review deadline")
    for field in ("submission_channel", "queued_at", "provisional_deadline_at",
                  "priority_score", "priority_band",
                  "effective_review_deadline_at"):
        submission[field] = scratch[field]
    submission["state"] = "WAITING_FOR_REVIEW"
    submission["review_window_id"] = window["id"]
    touch(submission)
    if expedite is not None:
        expedite["state"] = "CONSUMED"
        expedite["consumed_at"] = now_iso()
        touch(expedite)
    calc.sync_window(window, bump=True)
    return ok(public(submission))


# --------------------------------------------------------------------------
# Withdrawal, claim and the decision gate
# --------------------------------------------------------------------------
@bp.route("/submissions/<submission_id>/withdraw", methods=["POST"])
@endpoint(["ReleaseManager"])
def withdraw_submission(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    body = body_json()
    check_unknown(body, {"reason_code"})
    opt_str(body, "reason_code", 1, 80)
    if submission["state"] not in ("DRAFT", "PRE_REVIEW_PASSED",
                                   "WAITING_FOR_REVIEW"):
        fail("ERR_INVALID_SUBMISSION_STATE",
             "a %s submission cannot be withdrawn" % submission["state"])
    submission["state"] = "DEVELOPER_WITHDRAWN"
    flows.release_slot(submission)
    touch(submission)
    refund_expedites(submission)
    return ok(public(submission))


@bp.route("/submissions/<submission_id>/claim", methods=["POST"])
@endpoint(["PlatformReviewer"])
def claim_submission(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    if submission["state"] != "WAITING_FOR_REVIEW":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "only a WAITING_FOR_REVIEW submission may be claimed")
    window = get_row("review_capacity_window", submission.get("review_window_id"))
    now = now_dt()
    if (window is None or window["status"] != "OPEN"
            or not (parse_iso(window["starts_at"]) <= now
                    < parse_iso(window["ends_at"]))):
        fail("ERR_REVIEW_WINDOW_CLOSED",
             "the assigned review capacity window is no longer usable")
    credential = get_row("signing_credential", submission["signing_credential_id"])
    if credential is None or credential["status"] not in USABLE_CREDENTIAL_STATES:
        fail("ERR_SIGNING_CREDENTIAL_INVALID",
             "the signing credential is no longer usable")
    submission["state"] = "IN_REVIEW"
    submission["reviewed_by_user_id"] = g.user_id
    calc.recompute_final_score(submission, bump=False)
    touch(submission)
    return ok(public(submission))


REASON_SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}


def _reason_entries(body, metadata_only):
    entries = req_array(body, "rejection_reasons", min_items=1, member_type=dict)
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "rejection_reasons members must be objects")
        for key in entry.keys():
            if key not in ("guideline_rule_id", "reason_code", "severity",
                           "detail"):
                fail("ERR_VALIDATION", "unknown rejection_reasons key %r" % key)
        rule_id = req_id(entry, "guideline_rule_id")
        reason_code = req_str(entry, "reason_code", 1, 60)
        severity = req_str(entry, "severity", enum=REASON_SEVERITIES)
        detail = req_str(entry, "detail", 1, 1000)
        if metadata_only and severity != "MINOR":
            fail("ERR_VALIDATION",
                 "a metadata rejection may only cite MINOR reasons")
        out.append((rule_id, reason_code, severity, detail))
    return out


@bp.route("/submissions/<submission_id>/decision", methods=["POST"])
@endpoint(["PlatformReviewer"])
def decide_submission(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    body = body_json()
    check_unknown(body, {"outcome", "rejection_reasons"})
    for entry in (body.get("rejection_reasons") or []):
        if isinstance(entry, dict) and isinstance(entry.get("guideline_rule_id"), str):
            resolve([("guideline_rule", entry["guideline_rule_id"])])
    outcome = req_str(body, "outcome",
                      enum={"APPROVE", "REJECT", "METADATA_REJECT"})
    entries = []
    if outcome in ("REJECT", "METADATA_REJECT"):
        entries = _reason_entries(body, outcome == "METADATA_REJECT")
    if submission["state"] != "IN_REVIEW":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "only an IN_REVIEW submission may be decided")
    flows.sod_must_equal(submission.get("reviewed_by_user_id"))
    flows.sod_must_differ(submission.get("attested_by_user_id"))
    app = get_row("app_record", submission["app_record_id"])
    account = calc.account_of_app(app)
    if outcome == "APPROVE":
        calc.recompute_final_score(submission, bump=False)
        score = submission.get("disclosure_accuracy_score_final")
        if score is None or Decimal(str(score)) < DISCLOSURE_PASS_THRESHOLD:
            fail("ERR_PRIVACY_DISCLOSURE_INACCURATE",
                 "the final disclosure accuracy score is below the threshold")
        if critical_finding_open(submission):
            fail("ERR_CRITICAL_FINDING_UNRESOLVED",
                 "a CRITICAL behaviour finding is still unresolved")
        if age_rating_understated(submission):
            fail("ERR_AGE_RATING_UNDERSTATED",
                 "attested_age_rating is below the derived rating")
        for item in rows("commerce_item"):
            if (item["app_record_id"] == app["id"]
                    and item["status"] == "SUBMITTED"):
                fail("ERR_INVALID_COMMERCE_ITEM_STATE",
                     "a commerce item of this app is still SUBMITTED")
        others = [s for s in calc.submissions_of_app(app["id"])
                  if s["id"] != submission["id"] and s["state"] == "APPROVED"]
        for other in others:
            for plan in calc.plans_of_app(app["id"]):
                if (plan["submission_id"] == other["id"]
                        and plan["state"] == "PHASE_ACTIVE"):
                    fail("ERR_INVALID_ROLLOUT_STATE",
                         "the previously approved build has an active rollout")
        submission["state"] = "APPROVED"
        submission["decided_at"] = now_iso()
        touch(submission)
        for other in others:
            other["state"] = "SUPERSEDED"
            touch(other)
            for plan in calc.plans_of_app(app["id"]):
                if (plan["submission_id"] == other["id"]
                        and plan["state"] == "SCHEDULED"):
                    plan["state"] = "CANCELLED"
                    plan["terminated_at"] = now_iso()
                    touch(plan)
    else:
        for rule_id, _code, _sev, _detail in entries:
            rule = get_row("guideline_rule", rule_id)
            if rule is None or rule["status"] != "EFFECTIVE":
                fail("ERR_GUIDELINE_RULE_NOT_EFFECTIVE",
                     "a cited guideline rule is not EFFECTIVE")
        submission["state"] = ("REJECTED" if outcome == "REJECT"
                               else "METADATA_REJECTED")
        submission["rejected_at"] = now_iso()
        submission["decided_at"] = now_iso()
        touch(submission)
        cited = []
        for rule_id, reason_code, severity, detail in entries:
            new_row("rejection_reason", {
                "submission_id": submission["id"],
                "guideline_rule_id": rule_id,
                "reason_code": reason_code,
                "severity": severity,
                "detail": detail,
                "recorded_at": now_iso(),
                "recorded_by_user_id": g.user_id,
                "developer_response": None,
                "disposition": "PENDING",
                "appeal_disposition": "PENDING",
            })
            if severity in ("CRITICAL", "MAJOR"):
                cited.append(rule_id)
        if outcome == "REJECT":
            flows.rejection_cascade(app, set(cited))
    window = get_row("review_capacity_window", submission.get("review_window_id"))
    if window is not None:
        calc.sync_window(window, bump=True)
    if account is not None:
        calc.recompute_account_standing(account)
    return ok(public(submission))


@bp.route("/submissions/<submission_id>/return-to-draft", methods=["POST"])
@endpoint(["ReleaseManager"])
def return_to_draft(submission_id):
    (submission,) = resolve([("submission", submission_id)])
    body = body_json()
    check_unknown(body, {"signing_credential_id"})
    credential = None
    if body.get("signing_credential_id") is not None:
        (credential,) = resolve([("signing_credential",
                                  body.get("signing_credential_id"))])
    state = submission["state"]
    if state not in ("REJECTED", "METADATA_REJECTED", "BLOCKED_INVALID_SIGNING"):
        fail("ERR_INVALID_SUBMISSION_STATE",
             "a %s submission cannot be returned to draft" % state)
    if state == "BLOCKED_INVALID_SIGNING" and credential is None:
        fail("ERR_VALIDATION",
             "signing_credential_id is required for a signing-blocked build")
    for reason in rows("rejection_reason"):
        if (reason["submission_id"] == submission["id"]
                and reason["disposition"] == "PENDING"):
            fail("ERR_REJECTION_RESPONSE_REQUIRED",
                 "every rejection reason must be answered first")
    for appeal in rows("appeal_request"):
        if (appeal["submission_id"] == submission["id"]
                and appeal["state"] in ("SUBMITTED", "BOARD_REVIEW")):
            fail("ERR_INVALID_APPEAL_STATE", "an appeal of this build is live")
    app = get_row("app_record", submission["app_record_id"])
    if credential is not None:
        check_credential(app, credential)
        submission["signing_credential_id"] = credential["id"]
    window = get_row("review_capacity_window", submission.get("review_window_id"))
    submission["state"] = "DRAFT"
    submission["resubmission_count"] = submission.get("resubmission_count", 0) + 1
    submission["pre_review_passed"] = False
    submission["pre_review_checked_at"] = None
    submission["attested_by_user_id"] = None
    submission["review_window_id"] = None
    touch(submission)
    if window is not None:
        calc.sync_window(window, bump=True)
    return ok(public(submission))


# --------------------------------------------------------------------------
# MetadataLocale
# --------------------------------------------------------------------------
@bp.route("/metadata-locales", methods=["POST"])
@endpoint(["ReleaseManager"])
def create_locale():
    body = body_json()
    check_unknown(body, {"submission_id", "locale", "title", "screenshot_counts",
                         "is_primary", "subtitle", "keywords", "promotional_text"})
    (submission,) = resolve([("submission", body.get("submission_id"))])
    req_id(body, "submission_id")
    locale = req_str(body, "locale", 2, 20)
    title = req_str(body, "title", 1, 30)
    counts = req_object(body, "screenshot_counts")
    for key, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_VALIDATION",
                 "screenshot_counts.%s must be an integer" % key)
        if value < 0:
            fail("ERR_VALIDATION",
                 "screenshot_counts.%s must be at least 0" % key)
    is_primary = opt_bool(body, "is_primary", default=False)
    subtitle = opt_str(body, "subtitle", 0, 30)
    keywords = opt_str(body, "keywords", 0, 100, default="")
    promotional_text = opt_str(body, "promotional_text", 0, 170)
    if submission["state"] not in ("DRAFT", "PRE_REVIEW_PASSED"):
        fail("ERR_INVALID_SUBMISSION_STATE",
             "a %s submission is not editable" % submission["state"])
    app = get_row("app_record", submission["app_record_id"])
    flows.posture_gate(app)
    for existing in locales_of(submission["id"]):
        if is_primary and existing.get("is_primary"):
            fail("ERR_DUPLICATE_PRIMARY_LOCALE",
                 "this submission already has a primary locale")
        if existing["locale"] == locale:
            fail("ERR_DUPLICATE_PRIMARY_LOCALE",
                 "locale %s is already attached to this submission" % locale)
    row = new_row("metadata_locale", {
        "submission_id": submission["id"],
        "locale": locale,
        "is_primary": is_primary,
        "title": title,
        "subtitle": subtitle,
        "keywords": keywords if keywords is not None else "",
        "promotional_text": promotional_text,
        "screenshot_counts": dict(counts),
        "required_device_classes": calc.required_device_classes(app["platform"]),
        "is_complete": False,
    })
    row["is_complete"] = calc.locale_is_complete(row, app["platform"])
    submission["metadata_locale_count"] = submission.get("metadata_locale_count", 0) + 1
    void_attestation(submission)
    touch(submission)
    return ok(public(row), 201)


@bp.route("/metadata-locales", methods=["GET"])
@endpoint(LOCALE_READ_ROLES)
def list_locales():
    items = rows("metadata_locale")
    for field in ("submission_id", "locale"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    primary = arg_bool("is_primary")
    if primary is not None:
        items = [r for r in items if bool(r.get("is_primary")) is primary]
    return paginate(scope_rows(items))


@bp.route("/metadata-locales/<locale_id>", methods=["GET"])
@endpoint(LOCALE_READ_ROLES)
def read_locale(locale_id):
    (locale,) = resolve([("metadata_locale", locale_id)])
    return ok(public(locale))
