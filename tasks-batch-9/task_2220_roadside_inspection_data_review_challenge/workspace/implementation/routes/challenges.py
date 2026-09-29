"""Data challenges, their evidence, and citation adjudications."""

from flask import Blueprint

from db import base_record, get_or_404, serialize, store, touch
from errors import err
from middleware import ALL_ROLES, actor, scope, scope_rows
from response import created, ok
from routes.helpers import filtered, listing, rows_of, view_violation
from services import cascade
from services.calc import (CHALLENGE_FILING_WINDOW_DAYS, INFO_RESPONSE_DAYS,
                           MAX_INFO_ROUNDS, whole_days)
from validation import (body, get_dt, get_enum, get_int, get_str, pagination,
                        q_bool, q_enum, q_str)

bp = Blueprint("challenges", __name__)

CHALLENGE_TYPES = ("WRONG_CARRIER", "DUPLICATE_REPORT",
                   "INCORRECT_VIOLATION_CODE", "VIOLATION_NOT_SUPPORTED")
CHALLENGE_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
                      "RESOLVED_ACCEPTED", "RESOLVED_REJECTED", "WITHDRAWN")
EVIDENCE_TYPES = ("BILL_OF_LADING", "LEASE_AGREEMENT", "GPS_LOG", "ELD_RECORD",
                  "PHOTO", "COURT_DOCUMENT", "OTHER")
COURT_STATUSES = ("PENDING", "CONVICTED", "DISMISSED", "REDUCED", "NOT_GUILTY")
COURT_RESULTS = ("CONVICTED", "DISMISSED", "REDUCED", "NOT_GUILTY")
RECORD_UPDATE_STATUSES = ("NOT_APPLIED", "APPLIED", "NOT_APPLICABLE")
REVIEW_ACTIONS = ("ASSIGN", "REQUEST_INFO", "RESOLVE_ACCEPT", "RESOLVE_REJECT")
REJECT_DISPOSITIONS = ("INSUFFICIENT_EVIDENCE", "NOT_SUBSTANTIATED")
OPEN_CHALLENGE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
UNRESOLVED_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
CHALLENGEABLE_REPORT_STATUSES = ("VALIDATED", "SCORED", "AMENDED")
SEVERITY_FACTORS = {
    "PENDING": 1.0,
    "CONVICTED": 1.0,
    "DISMISSED": 0.0,
    "REDUCED": 0.5,
    "NOT_GUILTY": 0.0,
}


def evidence_of(challenge_id):
    rows = [e for e in store.evidence.values()
            if e["challenge_id"] == challenge_id]
    return sorted(rows, key=lambda e: (e["created_at"].dt, e["_seq"]))


def refresh_evidence_count(challenge):
    count = len(evidence_of(challenge["id"]))
    if challenge.get("evidence_count") != count:
        challenge["evidence_count"] = count
        touch(challenge)


def duplicate_target_ok(report, target_id):
    target = store.reports.get(target_id) if target_id else None
    if target is None:
        return False
    if target["id"] == report["id"]:
        return False
    if target["status"] == "RESCINDED":
        return False
    if target["vehicle_vin"] != report["vehicle_vin"]:
        return False
    return target["attributed_carrier_id"] == report["attributed_carrier_id"]


def evidence_sufficient(challenge):
    rows = evidence_of(challenge["id"])
    kind = challenge["challenge_type"]
    if kind == "WRONG_CARRIER":
        wanted = ("BILL_OF_LADING", "LEASE_AGREEMENT")
    elif kind == "INCORRECT_VIOLATION_CODE":
        wanted = ("PHOTO", "ELD_RECORD", "COURT_DOCUMENT")
    else:
        return len(rows) >= 1
    return any(row["evidence_type"] in wanted for row in rows)


# ---------------------------------------------------------------------------
# data challenges
# ---------------------------------------------------------------------------

@bp.post("/data-challenges")
def create_challenge():
    act = actor("CarrierAnalyst")
    b = body()
    report_id = get_str(b, "report_id")
    challenge_type = get_enum(b, "challenge_type", CHALLENGE_TYPES)
    narrative = get_str(b, "narrative", max_len=4000)
    target_violation_id = get_str(b, "target_violation_id", required=False)
    asserted_correct_carrier_id = get_str(b, "asserted_correct_carrier_id",
                                         required=False)
    duplicate_of_report_id = get_str(b, "duplicate_of_report_id", required=False)
    asserted_correct_violation_code_id = get_str(
        b, "asserted_correct_violation_code_id", required=False)

    report = get_or_404(store.reports, report_id, "ERR_REPORT_NOT_FOUND")
    target = None
    if target_violation_id is not None:
        target = get_or_404(store.violations, target_violation_id,
                            "ERR_VIOLATION_NOT_FOUND")
    if asserted_correct_carrier_id is not None:
        get_or_404(store.carriers, asserted_correct_carrier_id,
                   "ERR_CARRIER_NOT_FOUND")
    if duplicate_of_report_id is not None:
        get_or_404(store.reports, duplicate_of_report_id, "ERR_REPORT_NOT_FOUND")
    if asserted_correct_violation_code_id is not None:
        get_or_404(store.violation_codes, asserted_correct_violation_code_id,
                   "ERR_VIOLATION_CODE_NOT_FOUND")

    carrier_id = report["attributed_carrier_id"]
    scope(act, carrier_id)

    if challenge_type == "WRONG_CARRIER":
        if asserted_correct_carrier_id is None:
            raise err("ERR_CHALLENGE_PAYLOAD_INCOMPLETE",
                      "WRONG_CARRIER requires asserted_correct_carrier_id.")
        if asserted_correct_carrier_id == carrier_id:
            raise err("ERR_CHALLENGE_PAYLOAD_INCOMPLETE",
                      "asserted_correct_carrier_id must differ from the filing "
                      "carrier.")
    elif challenge_type == "DUPLICATE_REPORT":
        if duplicate_of_report_id is None:
            raise err("ERR_CHALLENGE_PAYLOAD_INCOMPLETE",
                      "DUPLICATE_REPORT requires duplicate_of_report_id.")
    elif challenge_type == "INCORRECT_VIOLATION_CODE":
        if target is None or asserted_correct_violation_code_id is None:
            raise err("ERR_CHALLENGE_PAYLOAD_INCOMPLETE",
                      "INCORRECT_VIOLATION_CODE requires target_violation_id and "
                      "asserted_correct_violation_code_id.")
    else:  # VIOLATION_NOT_SUPPORTED
        if target is None:
            raise err("ERR_CHALLENGE_PAYLOAD_INCOMPLETE",
                      "VIOLATION_NOT_SUPPORTED requires target_violation_id.")
    if target is not None and target["report_id"] != report["id"]:
        raise err("ERR_CHALLENGE_TARGET_MISMATCH",
                  "target_violation_id does not belong to report_id.")
    if (challenge_type == "DUPLICATE_REPORT"
            and not duplicate_target_ok(report, duplicate_of_report_id)):
        raise err("ERR_DUPLICATE_TARGET_INVALID",
                  "duplicate_of_report_id is not a valid surviving report.")

    challenge = base_record()
    challenge.update({
        "report_id": report["id"],
        "carrier_id": carrier_id,
        "challenge_type": challenge_type,
        "target_violation_id": target["id"] if target else None,
        "asserted_correct_carrier_id": asserted_correct_carrier_id,
        "duplicate_of_report_id": duplicate_of_report_id,
        "asserted_correct_violation_code_id": asserted_correct_violation_code_id,
        "narrative": narrative,
        "status": "DRAFT",
        "info_request_count": 0,
        "info_response_deadline": None,
        "submitted_at": None,
        "resolved_at": None,
        "resolution_disposition": None,
        "resolved_by_user_id": None,
        "evidence_count": 0,
        "filing_age_days_at_submit": None,
    })
    store.challenges[challenge["id"]] = challenge
    return created(serialize(challenge))


@bp.get("/data-challenges")
def list_challenges():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.challenges), [
        ("report_id", q_str("report_id")),
        ("carrier_id", q_str("carrier_id")),
        ("status", q_enum("status", CHALLENGE_STATUSES)),
        ("challenge_type", q_enum("challenge_type", CHALLENGE_TYPES)),
        ("target_violation_id", q_str("target_violation_id")),
        ("asserted_correct_carrier_id", q_str("asserted_correct_carrier_id")),
        ("duplicate_of_report_id", q_str("duplicate_of_report_id")),
        ("asserted_correct_violation_code_id",
         q_str("asserted_correct_violation_code_id")),
    ])
    rows = scope_rows(act, rows, "carrier_id")
    return listing(rows, limit, offset)


@bp.get("/data-challenges/<challenge_id>")
def get_challenge(challenge_id):
    act = actor(*ALL_ROLES)
    challenge = get_or_404(store.challenges, challenge_id,
                           "ERR_CHALLENGE_NOT_FOUND")
    scope(act, challenge["carrier_id"])
    return ok(serialize(challenge))


@bp.post("/data-challenges/<challenge_id>/evidence")
def add_evidence(challenge_id):
    act = actor("CarrierAnalyst")
    b = body()
    evidence_type = get_enum(b, "evidence_type", EVIDENCE_TYPES)
    document_uri = get_str(b, "document_uri", max_len=500)
    description = get_str(b, "description", max_len=1000)
    challenge = get_or_404(store.challenges, challenge_id,
                           "ERR_CHALLENGE_NOT_FOUND")
    scope(act, challenge["carrier_id"])
    if challenge["status"] not in UNRESOLVED_STATUSES:
        raise err("ERR_INVALID_CHALLENGE_STATE",
                  "Evidence cannot be attached to a resolved challenge.")
    record = base_record(with_version=False)
    record.update({
        "challenge_id": challenge["id"],
        "evidence_type": evidence_type,
        "document_uri": document_uri,
        "description": description,
        "submitted_round": challenge["info_request_count"],
    })
    store.evidence[record["id"]] = record
    refresh_evidence_count(challenge)
    return created(serialize(record))


@bp.get("/data-challenges/<challenge_id>/evidence")
def list_evidence(challenge_id):
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    challenge = get_or_404(store.challenges, challenge_id,
                           "ERR_CHALLENGE_NOT_FOUND")
    scope(act, challenge["carrier_id"])
    return listing(evidence_of(challenge["id"]), limit, offset)


@bp.post("/data-challenges/<challenge_id>/submit")
def submit_challenge(challenge_id):
    act = actor("CarrierAnalyst")
    challenge = get_or_404(store.challenges, challenge_id,
                           "ERR_CHALLENGE_NOT_FOUND")
    scope(act, challenge["carrier_id"])
    if challenge["status"] not in ("DRAFT", "INFO_REQUESTED"):
        raise err("ERR_INVALID_CHALLENGE_STATE",
                  "Only a DRAFT or INFO_REQUESTED challenge can be submitted.")
    report = store.reports.get(challenge["report_id"])
    carrier = store.carriers.get(challenge["carrier_id"])
    now = store.now_ts()
    first_submit = challenge["status"] == "DRAFT"

    if first_submit:
        if report is None or report["status"] not in CHALLENGEABLE_REPORT_STATUSES:
            raise err("ERR_INVALID_REPORT_STATE",
                      "The report is not in a challengeable state.")
        age = whole_days(now.dt, report["inspection_start"].dt)
        if age > CHALLENGE_FILING_WINDOW_DAYS:
            raise err("ERR_CHALLENGE_FILING_WINDOW_CLOSED",
                      "The challenge filing window has closed.")
        if not evidence_sufficient(challenge):
            raise err("ERR_EVIDENCE_REQUIRED",
                      "The challenge type requires supporting evidence.")
        for other in store.challenges.values():
            if other["id"] == challenge["id"]:
                continue
            if (other["report_id"] == challenge["report_id"]
                    and other["challenge_type"] == challenge["challenge_type"]
                    and other.get("target_violation_id")
                    == challenge.get("target_violation_id")
                    and other["status"] in OPEN_CHALLENGE_STATUSES):
                raise err("ERR_DUPLICATE_OPEN_CHALLENGE",
                          "An open challenge already covers this target.")
        if carrier is not None and (carrier["challenge_quota_used"]
                                    >= carrier["challenge_quota_limit"]):
            raise err("ERR_CHALLENGE_QUOTA_EXCEEDED",
                      "The rolling challenge quota is exhausted.")
    else:
        deadline = challenge.get("info_response_deadline")
        if deadline is not None and now.dt > deadline.dt:
            raise err("ERR_INFO_RESPONSE_WINDOW_CLOSED",
                      "The information-response window has closed.")
        rounds = [row for row in evidence_of(challenge["id"])
                  if row["submitted_round"] == challenge["info_request_count"]]
        if not rounds:
            raise err("ERR_EVIDENCE_REQUIRED",
                      "This round requires at least one new evidence row.")

    challenge["status"] = "SUBMITTED"
    challenge["submitted_at"] = now
    if report is not None:
        challenge["filing_age_days_at_submit"] = whole_days(
            now.dt, report["inspection_start"].dt)
    touch(challenge)

    if first_submit:
        if carrier is not None:
            carrier["challenge_quota_used"] = carrier["challenge_quota_used"] + 1
        cascade.set_under_challenge(challenge, True)
        cascade.cascade_carrier_id(challenge["carrier_id"])
    return ok(serialize(challenge))


@bp.post("/data-challenges/<challenge_id>/withdraw")
def withdraw_challenge(challenge_id):
    act = actor("CarrierAnalyst")
    b = body()
    get_str(b, "withdraw_note", required=False, max_len=2000)
    challenge = get_or_404(store.challenges, challenge_id,
                           "ERR_CHALLENGE_NOT_FOUND")
    scope(act, challenge["carrier_id"])
    if challenge["status"] not in ("DRAFT", "SUBMITTED", "INFO_REQUESTED"):
        raise err("ERR_INVALID_CHALLENGE_STATE",
                  "This challenge can no longer be withdrawn.")
    consumed_quota = challenge["status"] in ("SUBMITTED", "INFO_REQUESTED")
    challenge["status"] = "WITHDRAWN"
    touch(challenge)
    if consumed_quota:
        carrier = store.carriers.get(challenge["carrier_id"])
        if carrier is not None and carrier["challenge_quota_used"] > 0:
            carrier["challenge_quota_used"] = carrier["challenge_quota_used"] - 1
        cascade.set_under_challenge(challenge, False)
        cascade.cascade_carrier_id(challenge["carrier_id"])
    return ok(serialize(challenge))


@bp.post("/data-challenges/<challenge_id>/review")
def review_challenge(challenge_id):
    act = actor("FmcsaReviewOfficer")
    b = body()
    action = get_enum(b, "action", REVIEW_ACTIONS)
    get_str(b, "review_note", max_len=2000)
    disposition = get_enum(b, "resolution_disposition", REJECT_DISPOSITIONS,
                           required=False)
    if action != "RESOLVE_REJECT" and disposition is not None:
        raise err("ERR_INVALID_REQUEST",
                  "'resolution_disposition' is only valid for RESOLVE_REJECT.")
    if action == "RESOLVE_REJECT" and disposition is None:
        raise err("ERR_INVALID_REQUEST",
                  "RESOLVE_REJECT requires 'resolution_disposition'.")
    challenge = get_or_404(store.challenges, challenge_id,
                           "ERR_CHALLENGE_NOT_FOUND")

    if action == "ASSIGN":
        if challenge["status"] != "SUBMITTED":
            raise err("ERR_INVALID_CHALLENGE_STATE",
                      "Only a SUBMITTED challenge can be assigned.")
        challenge["status"] = "UNDER_REVIEW"
        touch(challenge)
        return ok(serialize(challenge))

    if action == "REQUEST_INFO":
        if challenge["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_CHALLENGE_STATE",
                      "Information can only be requested while UNDER_REVIEW.")
        if challenge["info_request_count"] >= MAX_INFO_ROUNDS:
            raise err("ERR_CHALLENGE_ROUND_LIMIT_EXCEEDED",
                      "The information-request round limit is exhausted.")
        challenge["info_request_count"] = challenge["info_request_count"] + 1
        challenge["info_response_deadline"] = store.now_ts().plus_days(
            INFO_RESPONSE_DAYS)
        challenge["status"] = "INFO_REQUESTED"
        touch(challenge)
        return ok(serialize(challenge))

    if challenge["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_CHALLENGE_STATE",
                  "Only a challenge UNDER_REVIEW can be resolved.")

    if action == "RESOLVE_REJECT":
        challenge["status"] = "RESOLVED_REJECTED"
        challenge["resolution_disposition"] = disposition
        challenge["resolved_at"] = store.now_ts()
        challenge["resolved_by_user_id"] = act.user_id
        touch(challenge)
        cascade.set_under_challenge(challenge, False)
        cascade.cascade_carrier_id(challenge["carrier_id"])
        return ok(serialize(challenge))

    return resolve_accept(act, challenge)


def resolve_accept(act, challenge):
    report = store.reports.get(challenge["report_id"])
    target = store.violations.get(challenge.get("target_violation_id") or "")
    kind = challenge["challenge_type"]

    if kind in ("VIOLATION_NOT_SUPPORTED", "INCORRECT_VIOLATION_CODE"):
        if target is not None and target.get("out_of_service"):
            cleared = False
            for adj in cascade.adjudications_of_violation(target["id"]):
                if adj.get("superseded"):
                    continue
                if adj["court_status"] in ("DISMISSED", "NOT_GUILTY"):
                    cleared = True
                    break
            if not cleared:
                raise err("ERR_OOS_REMOVAL_REQUIRES_ADJUDICATION",
                          "An out-of-service violation needs a dismissal on "
                          "record before it can be removed or recoded.")
    if kind == "DUPLICATE_REPORT":
        if report is None or not duplicate_target_ok(
                report, challenge.get("duplicate_of_report_id")):
            raise err("ERR_DUPLICATE_TARGET_INVALID",
                      "duplicate_of_report_id is not a valid surviving report.")

    now = store.now_ts()
    challenge["status"] = "RESOLVED_ACCEPTED"
    challenge["resolved_at"] = now
    challenge["resolved_by_user_id"] = act.user_id
    touch(challenge)
    cascade.set_under_challenge(challenge, False)

    was_scored = report is not None and report["status"] == "SCORED"
    old_carrier_id = challenge["carrier_id"]
    driver_ids = []

    if kind == "WRONG_CARRIER":
        challenge["resolution_disposition"] = "REATTRIBUTED"
        new_carrier_id = challenge["asserted_correct_carrier_id"]
        report["original_carrier_id"] = report["attributed_carrier_id"]
        report["attributed_carrier_id"] = new_carrier_id
        report["reattributed"] = True
        touch(report)
        for violation in cascade.violations_of_report(report["id"]):
            violation["attributed_carrier_id"] = new_carrier_id
            driver_id = violation.get("driver_id")
            if driver_id:
                driver = store.drivers.get(driver_id)
                if driver is None or driver["carrier_id"] != new_carrier_id:
                    violation["driver_id"] = None
                    cascade.waive_for_attribution_change(violation["id"],
                                                        driver_id)
                driver_ids.append(driver_id)
            touch(violation)
        snapshot = cascade.epoch_for(old_carrier_id)
        cascade.cascade_carrier_id(old_carrier_id, snapshot_ts=snapshot,
                                  create=was_scored)
        cascade.cascade_carrier_id(new_carrier_id, snapshot_ts=snapshot,
                                  create=was_scored)
        cascade.recompute_drivers(driver_ids)
        return ok(serialize(challenge))

    if kind == "DUPLICATE_REPORT":
        challenge["resolution_disposition"] = "REPORT_RESCINDED"
        report["status"] = "RESCINDED"
        report["duplicate_master_report_id"] = challenge["duplicate_of_report_id"]
        for violation in cascade.violations_of_report(report["id"]):
            if violation["status"] != "REMOVED":
                violation["status"] = "REMOVED"
                violation["removal_reason"] = "DUPLICATE_RESCINDED"
                violation["time_weighted_severity"] = 0.0
                touch(violation)
                cascade.waive_for_removed_violation(violation["id"])
            if violation.get("driver_id"):
                driver_ids.append(violation["driver_id"])
        cascade.rollup_report(report)
        touch(report)
        cascade.cascade_carrier_id(old_carrier_id)
        cascade.recompute_drivers(driver_ids)
        return ok(serialize(challenge))

    if kind == "INCORRECT_VIOLATION_CODE":
        challenge["resolution_disposition"] = "CODE_CORRECTED"
        version_before = report["version"]
        target["effective_violation_code_id"] = \
            challenge["asserted_correct_violation_code_id"]
        target["status"] = "RECODED"
        basis = report.get("severity_basis_utc")
        cascade.pin_violation(target, report, basis.dt if basis else store.now())
        touch(target)
        cascade.rollup_report(report)
        touch(report)
        amendment = base_record(with_version=False)
        amendment.update({
            "report_id": report["id"],
            "amendment_type": "VIOLATION_CODE_CORRECTION",
            "target_violation_id": target["id"],
            "corrected_violation_code_id":
                challenge["asserted_correct_violation_code_id"],
            "corrected_driver_id": None,
            "corrected_carrier_id": None,
            "source_challenge_id": challenge["id"],
            "rationale": challenge["narrative"],
            "applied_at": now,
            "report_version_before": version_before,
            "report_version_after": report["version"],
        })
        store.amendments[amendment["id"]] = amendment
        cascade.cascade_carrier_id(old_carrier_id)
        if target.get("driver_id"):
            driver_ids.append(target["driver_id"])
        cascade.recompute_drivers(driver_ids)
        return ok(serialize(challenge))

    # VIOLATION_NOT_SUPPORTED
    challenge["resolution_disposition"] = "VIOLATION_REMOVED"
    target["status"] = "REMOVED"
    target["removal_reason"] = "CHALLENGE_ACCEPTED"
    target["time_weighted_severity"] = 0.0
    touch(target)
    cascade.waive_for_removed_violation(target["id"])
    cascade.rollup_report(report)
    touch(report)
    cascade.cascade_carrier_id(old_carrier_id)
    if target.get("driver_id"):
        driver_ids.append(target["driver_id"])
    cascade.recompute_drivers(driver_ids)
    return ok(serialize(challenge))


# ---------------------------------------------------------------------------
# citation adjudications
# ---------------------------------------------------------------------------

@bp.post("/citation-adjudications")
def create_adjudication():
    actor("StateInspectionOfficer")
    b = body()
    violation_id = get_str(b, "violation_id")
    citation_number = get_str(b, "citation_number", max_len=60)
    court_date = get_dt(b, "court_date")
    expected_violation_version = get_int(b, "expected_violation_version",
                                        minimum=0)
    violation = get_or_404(store.violations, violation_id,
                           "ERR_VIOLATION_NOT_FOUND")
    if expected_violation_version != violation["version"]:
        raise err("ERR_STALE_VIOLATION_VERSION",
                  "The violation has advanced since it was read.")
    existing = cascade.adjudications_of_violation(violation["id"])
    for adj in existing:
        if not adj.get("superseded") and adj["court_status"] == "PENDING":
            raise err("ERR_ADJUDICATION_PENDING_EXISTS",
                      "This violation already has a pending adjudication.")
    record = base_record()
    record.update({
        "violation_id": violation["id"],
        "citation_number": citation_number,
        "court_date": court_date,
        "court_status": "PENDING",
        "record_update_status": "NOT_APPLIED",
        "reduced_to_violation_code_id": None,
        "severity_factor": 1.0,
        "court_result_recorded_at": None,
        "applied_at": None,
        "applied_by_user_id": None,
        "superseded": False,
    })
    for adj in existing:
        if not adj.get("superseded"):
            adj["superseded"] = True
            touch(adj)
    store.adjudications[record["id"]] = record
    touch(violation)
    return created(serialize(record))


@bp.get("/citation-adjudications")
def list_adjudications():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.adjudications), [
        ("violation_id", q_str("violation_id")),
        ("reduced_to_violation_code_id", q_str("reduced_to_violation_code_id")),
        ("court_status", q_enum("court_status", COURT_STATUSES)),
        ("record_update_status",
         q_enum("record_update_status", RECORD_UPDATE_STATUSES)),
        ("superseded", q_bool("superseded")),
    ])
    if act.is_carrier_side:
        rows = [r for r in rows if _adjudication_carrier(r) == act.user_id]
    return listing(rows, limit, offset)


def _adjudication_carrier(adjudication):
    violation = store.violations.get(adjudication["violation_id"])
    return violation["attributed_carrier_id"] if violation else None


@bp.get("/citation-adjudications/<adjudication_id>")
def get_adjudication(adjudication_id):
    act = actor(*ALL_ROLES)
    record = get_or_404(store.adjudications, adjudication_id,
                        "ERR_ADJUDICATION_NOT_FOUND")
    scope(act, _adjudication_carrier(record))
    return ok(serialize(record))


@bp.post("/citation-adjudications/<adjudication_id>/court-result")
def record_court_result(adjudication_id):
    actor("StateInspectionOfficer")
    b = body()
    court_status = get_enum(b, "court_status", COURT_RESULTS)
    reduced_to_violation_code_id = get_str(b, "reduced_to_violation_code_id",
                                          required=False)
    get_str(b, "court_note", required=False, max_len=2000)
    if court_status == "REDUCED" and reduced_to_violation_code_id is None:
        raise err("ERR_INVALID_REQUEST",
                  "REDUCED requires 'reduced_to_violation_code_id'.")
    record = get_or_404(store.adjudications, adjudication_id,
                        "ERR_ADJUDICATION_NOT_FOUND")
    if reduced_to_violation_code_id is not None:
        get_or_404(store.violation_codes, reduced_to_violation_code_id,
                   "ERR_VIOLATION_CODE_NOT_FOUND")
    if record["court_status"] != "PENDING":
        raise err("ERR_INVALID_ADJUDICATION_STATE",
                  "The court result has already been recorded.")
    if record.get("superseded"):
        raise err("ERR_ADJUDICATION_SUPERSEDED",
                  "This adjudication has been superseded.")
    record["court_status"] = court_status
    record["severity_factor"] = SEVERITY_FACTORS[court_status]
    if reduced_to_violation_code_id is not None:
        record["reduced_to_violation_code_id"] = reduced_to_violation_code_id
    record["court_result_recorded_at"] = store.now_ts()
    touch(record)
    violation = store.violations.get(record["violation_id"])
    if violation is not None and violation.get("driver_id"):
        cascade.recompute_driver_id(violation["driver_id"], adjudicated_only=True)
    return ok(serialize(record))


@bp.post("/citation-adjudications/<adjudication_id>/apply-to-record")
def apply_to_record(adjudication_id):
    act = actor("FmcsaReviewOfficer")
    record = get_or_404(store.adjudications, adjudication_id,
                        "ERR_ADJUDICATION_NOT_FOUND")
    if record["record_update_status"] != "NOT_APPLIED":
        raise err("ERR_ALREADY_APPLIED_TO_RECORD",
                  "This adjudication has already been applied.")
    if record.get("superseded"):
        raise err("ERR_ADJUDICATION_SUPERSEDED",
                  "This adjudication has been superseded.")
    court_status = record["court_status"]
    if court_status == "PENDING":
        raise err("ERR_INVALID_ADJUDICATION_STATE",
                  "The court result has not been recorded yet.")
    violation = store.violations.get(record["violation_id"])
    now = store.now_ts()

    if court_status == "CONVICTED":
        record["record_update_status"] = "NOT_APPLICABLE"
        record["applied_at"] = now
        record["applied_by_user_id"] = act.user_id
        touch(record)
        return ok(serialize(record))

    if violation is None or violation["status"] not in ("ACTIVE", "RECODED"):
        raise err("ERR_VIOLATION_NOT_ACTIVE",
                  "The linked violation is no longer active.")
    report = store.reports.get(violation["report_id"])
    driver_id = violation.get("driver_id")

    if court_status in ("DISMISSED", "NOT_GUILTY"):
        violation["status"] = "REMOVED"
        violation["removal_reason"] = "ADJUDICATION_DISMISSED"
        violation["time_weighted_severity"] = 0.0
        touch(violation)
        cascade.waive_for_removed_violation(violation["id"])
    else:  # REDUCED
        violation["effective_violation_code_id"] = \
            record["reduced_to_violation_code_id"]
        violation["status"] = "RECODED"
        basis = report.get("severity_basis_utc") if report else None
        cascade.pin_violation(violation, report, basis.dt if basis else now.dt)
        touch(violation)

    record["record_update_status"] = "APPLIED"
    record["applied_at"] = now
    record["applied_by_user_id"] = act.user_id
    touch(record)

    if report is not None:
        cascade.rollup_report(report)
    cascade.cascade_carrier_id(violation["attributed_carrier_id"])
    cascade.recompute_drivers([driver_id])
    return ok(serialize(record))
