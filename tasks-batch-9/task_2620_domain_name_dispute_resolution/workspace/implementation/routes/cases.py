"""The proceeding itself: filing, the ledger, compliance review, registrar
verification, notification and the respondent's answer."""

from flask import Blueprint, request

import db
import response
import validate as v
from errors import ApiError
from middleware import auth, body
from services import calc, logic

bp = Blueprint("cases", __name__)

WITHDRAWABLE = ("FILED", "DEFICIENT", "VERIFICATION_PENDING",
                "NOTIFICATION_PENDING", "COMMENCED", "RESPONSE_RECEIVED",
                "DEFAULT")


def _domain_cases(domain_id):
    return db.ordered(db.cases, lambda r: r["domain_id"] == domain_id)


def _overdue_open_verifications(case):
    """Withdrawal / administrative closure leaves no live verification behind."""
    for row in db.ordered(db.verifications, lambda r: r["case_id"] == case["id"]):
        if row["status"] == "REQUESTED":
            row["status"] = "OVERDUE"
            db.touch(row)
            registrar = logic.case_registrar(case)
            if registrar is not None:
                registrar["overdue_verification_count"] += 1
                db.touch(registrar)


def _expire_open_notices(case):
    for row in db.ordered(db.notices, lambda r: r["case_id"] == case["id"]):
        if row["status"] == "OPEN":
            row["status"] = "EXPIRED"
            db.touch(row)


# ------------------------------------------------------------------- filing
@bp.post("/udrp/cases")
def create_case():
    user_id, role = auth("Complainant", "CaseManager")
    payload = body()
    if role == "Complainant" and isinstance(payload.get("complainant_id"), str) \
            and payload["complainant_id"] != user_id:
        raise ApiError("ERR_NOT_OWNER")
    if v.present(payload, "complainant_id"):
        logic.resource_or_404(db.complainants, payload["complainant_id"])
    if v.present(payload, "domain_id"):
        logic.resource_or_404(db.domains, payload["domain_id"])
    complainant_id = v.req_str(payload, "complainant_id")
    domain_id = v.req_str(payload, "domain_id")
    mutual_jurisdiction = v.req_country(payload, "mutual_jurisdiction")
    remedy = v.req_enum(payload, "remedy_requested", ("TRANSFER", "CANCELLATION"))
    panel_election = v.opt_enum(payload, "panel_election", ("SINGLE", "THREE"), "SINGLE")
    expedited = v.opt_bool(payload, "expedited_requested", False)

    clock = db.now()
    for other in _domain_cases(domain_id):
        if other["status"] in logic.NON_TERMINAL_CASE_STATUSES:
            raise ApiError("ERR_DOMAIN_PROCEEDING_OVERLAP")
    for other in _domain_cases(domain_id):
        # Cooling-off intervals are never merged: every closed case is tested
        # on its own and both endpoints are inclusive.
        if not other.get("closed_at") or not other.get("refiling_bar_until"):
            continue
        if db.parse_dt(other["closed_at"]) <= clock <= db.parse_dt(other["refiling_bar_until"]):
            raise ApiError("ERR_REFILING_BAR_ACTIVE")

    row = db.base_row(
        case_number=db.next_case_number(),
        complainant_id=complainant_id,
        domain_id=domain_id,
        status="FILED",
        panel_election=panel_election,
        respondent_panel_election="NONE",
        required_seat_count=3 if panel_election == "THREE" else 1,
        mutual_jurisdiction=mutual_jurisdiction,
        remedy_requested=remedy,
        expedited_requested=expedited,
        assessed_fee_cents=0,
        complainant_share_cents=0,
        respondent_share_cents=0,
        fee_variant_applied="PROVISIONAL",
        honoraria_pool_cents=0,
        paid_cents=0,
        complainant_paid_cents=0,
        respondent_paid_cents=0,
        deficiency_round_count=0,
        last_deficiency_issuer_user_id=None,
        compliance_cleared_by_user_id=None,
        verified_registrant_name=None,
        verified_registrant_email=None,
        commenced_at=None,
        provisional_response_due_at=None,
        response_due_at=None,
        deadline_variant_applied="PROVISIONAL",
        default_recorded=False,
        closed_at=None,
        refiling_bar_until=None,
    )
    logic.reprice(row, "PROVISIONAL")
    db.cases[row["id"]] = row
    complainant = db.complainants[complainant_id]
    complainant["open_case_count"] += 1
    db.touch(complainant)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>")
def read_case(case_id):
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent", "Panelist",
         "RegistrarAgent")
    return response.ok(db.public(logic.case_or_404(case_id)))


@bp.get("/udrp/cases")
def list_cases():
    auth("ProviderAdmin", "CaseManager")
    limit, offset = v.pagination(request.args)
    complainant_id = request.args.get("complainant_id")
    domain_id = request.args.get("domain_id")
    status = v.query_enum(request.args, "status", logic.CASE_STATUSES)
    rows = db.ordered(db.cases)
    if complainant_id:
        rows = [r for r in rows if r["complainant_id"] == complainant_id]
    if domain_id:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


@bp.post("/udrp/cases/<case_id>/withdraw")
def withdraw_case(case_id):
    user_id, role = auth("Complainant", "CaseManager")
    case = logic.case_or_404(case_id)
    logic.ensure_case_owner(case, user_id, role)
    payload = body()
    v.opt_str(payload, "reason", 1, 2000)
    if case["status"] not in WITHDRAWABLE:
        raise ApiError("ERR_WITHDRAWAL_WINDOW_CLOSED")
    pct = calc.refund_pct(case["status"])
    _expire_open_notices(case)
    _overdue_open_verifications(case)
    logic.close_case(case, "WITHDRAWN", refund_pct=pct,
                     refund_reference="WITHDRAWAL-REFUND")
    return response.ok(db.public(case))


# ------------------------------------------------------------------- grounds
@bp.post("/udrp/cases/<case_id>/grounds")
def assert_ground(case_id):
    user_id, role = auth("Complainant", "CaseManager")
    case = logic.case_or_404(case_id)
    logic.ensure_case_owner(case, user_id, role)
    payload = body()
    if v.present(payload, "cited_decision_ids") and isinstance(
            payload["cited_decision_ids"], list):
        for cited in payload["cited_decision_ids"]:
            logic.resource_or_404(db.decisions, cited)
    ground_type = v.req_enum(payload, "ground_type", calc.REQUIRED_GROUND_TYPES)
    assertion_text = v.req_str(payload, "assertion_text", 10, 4000)
    evidence_count = v.req_int(payload, "evidence_count", 0, 200)
    cited = v.opt_str_list(payload, "cited_decision_ids", 0, None, distinct=False)
    mark_number = None
    mark_jurisdiction = None
    similarity = None
    if ground_type == "TRADEMARK_RIGHTS":
        mark_number = v.req_str(payload, "mark_registration_number", 1, 128)
        mark_jurisdiction = v.req_country(payload, "mark_jurisdiction")
        similarity = v.req_enum(payload, "similarity_claim",
                                ("IDENTICAL", "CONFUSINGLY_SIMILAR"))

    for existing in logic.case_grounds(case_id):
        if existing["ground_type"] == ground_type:
            raise ApiError("ERR_DUPLICATE_GROUND_TYPE")
    for cited_id in cited:
        if not logic.decision_is_citable(cited_id):
            raise ApiError("ERR_CITED_PRECEDENT_NOT_PUBLISHED")

    row = db.base_row(
        case_id=case_id,
        ground_type=ground_type,
        assertion_text=assertion_text,
        evidence_count=evidence_count,
        mark_registration_number=mark_number,
        mark_jurisdiction=mark_jurisdiction,
        similarity_claim=similarity,
        cited_decision_ids=cited,
        sufficiency_status=logic.grade_ground(evidence_count),
    )
    db.grounds[row["id"]] = row
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>/grounds")
def list_grounds(case_id):
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent", "Panelist")
    logic.case_or_404(case_id)
    limit, offset = v.pagination(request.args)
    window, total = response.paginate(logic.case_grounds(case_id), limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


# ------------------------------------------------------------- case ledger
@bp.post("/udrp/cases/<case_id>/fee-transactions")
def record_fee(case_id):
    auth("ProviderAdmin", "CaseManager")
    case = logic.case_or_404(case_id)
    payload = body()
    kind = v.req_enum(payload, "kind",
                      ("FILING_FEE", "PANEL_SUPPLEMENT", "REFUND", "WRITE_OFF"))
    payer = v.req_enum(payload, "payer", ("COMPLAINANT", "RESPONDENT", "PROVIDER"))
    amount = v.req_int(payload, "amount_cents", -10000000, 10000000)
    if amount == 0:
        v.bad("amount_cents may never be exactly 0.")
    if payer == "PROVIDER" and kind != "WRITE_OFF":
        v.bad("The PROVIDER attribution exists only for WRITE_OFF lines.")
    reference = v.opt_str(payload, "reference", 1, 255)
    row = db.event_row(
        case_id=case_id,
        kind=kind,
        payer=payer,
        amount_cents=amount,
        reference=reference,
        recorded_at=db.now_str(),
    )
    db.fees[row["id"]] = row
    logic.apply_ledger(case)
    db.touch(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>/fee-transactions")
def list_fees(case_id):
    auth("ProviderAdmin", "CaseManager", "Complainant")
    logic.case_or_404(case_id)
    limit, offset = v.pagination(request.args)
    window, total = response.paginate(logic.case_fee_rows(case_id), limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


# ------------------------------------------- administrative compliance review
@bp.post("/udrp/cases/<case_id>/deficiency-notices")
def issue_notice(case_id):
    user_id, _ = auth("CaseManager")
    case = logic.case_or_404(case_id)
    payload = body()
    codes = v.req_str_list(payload, "deficiency_codes", 1, 7,
                           allowed=calc.DEFICIENCY_CODES, distinct=True)
    correction_days = v.opt_int(payload, "correction_days", 1, 20,
                                calc.CORRECTION_PERIOD_DAYS)
    if case["status"] != "FILED":
        raise ApiError("ERR_INVALID_CASE_STATE")
    if case["deficiency_round_count"] >= calc.MAX_DEFICIENCY_ROUNDS:
        raise ApiError("ERR_DEFICIENCY_ROUND_LIMIT")
    issued_at = db.now()
    row = db.base_row(
        case_id=case_id,
        round_number=min(case["deficiency_round_count"] + 1,
                         calc.MAX_DEFICIENCY_ROUNDS),
        deficiency_codes=codes,
        issued_by_user_id=user_id,
        issued_at=db.fmt(issued_at),
        correction_days=correction_days,
        correction_deadline_at=db.fmt(db.add_days(issued_at, correction_days)),
        status="OPEN",
        cured_at=None,
    )
    db.notices[row["id"]] = row
    case["status"] = "DEFICIENT"
    case["deficiency_round_count"] += 1
    case["last_deficiency_issuer_user_id"] = user_id
    db.touch(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>/deficiency-notices")
def list_notices(case_id):
    auth("ProviderAdmin", "CaseManager", "Complainant")
    logic.case_or_404(case_id)
    limit, offset = v.pagination(request.args)
    rows = db.ordered(db.notices, lambda r: r["case_id"] == case_id)
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


@bp.post("/udrp/cases/<case_id>/corrections")
def cure_deficiency(case_id):
    user_id, role = auth("Complainant")
    case = logic.case_or_404(case_id)
    logic.ensure_case_owner(case, user_id, role)
    payload = body()
    if v.present(payload, "notice_id"):
        logic.resource_or_404(db.notices, payload["notice_id"])
    notice_id = v.req_str(payload, "notice_id")
    v.req_str(payload, "correction_notes", 1)
    if case["status"] != "DEFICIENT":
        raise ApiError("ERR_INVALID_CASE_STATE")
    notice = db.notices[notice_id]
    if notice["case_id"] != case_id or notice["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CASE_STATE")
    # The correction deadline is inclusive.
    if db.now() > db.parse_dt(notice["correction_deadline_at"]):
        raise ApiError("ERR_CORRECTION_PERIOD_EXPIRED")
    notice["status"] = "CURED"
    notice["cured_at"] = db.now_str()
    db.touch(notice)
    case["status"] = "FILED"
    db.touch(case)
    # The cured notice is the resource this operation targets and updates.
    return response.ok(db.public(notice))


@bp.post("/udrp/cases/<case_id>/compliance-clearance")
def clear_compliance(case_id):
    user_id, _ = auth("CaseManager")
    case = logic.case_or_404(case_id)
    payload = body()
    v.opt_str(payload, "reviewer_notes", 1, 4000)
    jurisdiction = case.get("mutual_jurisdiction") or ""
    if len(jurisdiction) != 2 or not jurisdiction.isalpha() or not jurisdiction.isupper():
        v.bad("mutual_jurisdiction must be present as exactly two uppercase letters.")
    if case["status"] != "FILED":
        raise ApiError("ERR_INVALID_CASE_STATE")
    if case["last_deficiency_issuer_user_id"] is not None \
            and case["last_deficiency_issuer_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    grounds = logic.case_grounds(case_id)
    if any(g["sufficiency_status"] != "SUFFICIENT" for g in grounds):
        raise ApiError("ERR_GROUND_EVIDENCE_INSUFFICIENT")
    if case["complainant_paid_cents"] < case["complainant_share_cents"]:
        raise ApiError("ERR_FILING_FEE_SHORTFALL")
    asserted = [g["ground_type"] for g in grounds]
    if sorted(asserted) != sorted(calc.REQUIRED_GROUND_TYPES):
        raise ApiError("ERR_MISSING_REQUIRED_GROUND")

    requested_at = db.now()
    registrar = logic.case_registrar(case)
    hours = registrar["verification_response_hours"] if registrar else 48
    verification = db.base_row(
        case_id=case_id,
        requested_at=db.fmt(requested_at),
        due_at=db.fmt(db.add_hours(requested_at, hours)),
        responded_at=None,
        verified_registrant_name=None,
        verified_registrant_email=None,
        lock_applied=False,
        registrar_remarks=None,
        status="REQUESTED",
        escalation_count=0,
    )
    db.verifications[verification["id"]] = verification
    case["compliance_cleared_by_user_id"] = user_id
    case["status"] = "VERIFICATION_PENDING"
    db.touch(case)
    return response.ok(db.public(case))


# ------------------------------------------------------ registrar verification
def _case_verifications(case_id):
    return db.ordered(db.verifications, lambda r: r["case_id"] == case_id)


@bp.post("/udrp/cases/<case_id>/registrar-verifications")
def rerequest_verification(case_id):
    auth("CaseManager")
    case = logic.case_or_404(case_id)
    body()
    if case["status"] != "VERIFICATION_PENDING":
        raise ApiError("ERR_INVALID_CASE_STATE")
    overdue = [r for r in _case_verifications(case_id) if r["status"] == "OVERDUE"]
    if not overdue:
        raise ApiError("ERR_INVALID_CASE_STATE")
    row = overdue[-1]
    requested_at = db.now()
    registrar = logic.case_registrar(case)
    hours = registrar["verification_response_hours"] if registrar else 48
    row["status"] = "REQUESTED"
    row["requested_at"] = db.fmt(requested_at)
    row["due_at"] = db.fmt(db.add_hours(requested_at, hours))
    db.touch(row)
    logic.credit_registrar_for_overdue(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>/registrar-verifications")
def list_verifications(case_id):
    auth("ProviderAdmin", "CaseManager", "RegistrarAgent")
    logic.case_or_404(case_id)
    limit, offset = v.pagination(request.args)
    window, total = response.paginate(_case_verifications(case_id), limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


@bp.post("/udrp/cases/<case_id>/registrar-verifications/<verification_id>/response")
def answer_verification(case_id, verification_id):
    user_id, _ = auth("RegistrarAgent")
    case = logic.case_or_404(case_id)
    logic.ensure_registrar_of_record(case, user_id)
    row = logic.resource_or_404(db.verifications, verification_id)
    if row["case_id"] != case_id:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    lock_applied = v.req_bool(payload, "lock_applied")
    registrant_name = v.req_str(payload, "verified_registrant_name", 1, 255)
    registrant_email = v.req_str(payload, "verified_registrant_email", 1, 320)
    remarks = v.opt_str(payload, "registrar_remarks", 1, 2000)
    if row["status"] not in ("REQUESTED", "OVERDUE"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    registrar = logic.case_registrar(case)
    if registrar is None or registrar["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRAR_SUSPENDED")
    if lock_applied is not True:
        raise ApiError("ERR_DOMAIN_LOCK_NOT_APPLIED")

    was_overdue = row["status"] == "OVERDUE"
    row["status"] = "RESPONDED"
    row["responded_at"] = db.now_str()
    row["lock_applied"] = True
    row["verified_registrant_name"] = registrant_name
    row["verified_registrant_email"] = registrant_email
    row["registrar_remarks"] = remarks
    db.touch(row)
    if was_overdue:
        logic.credit_registrar_for_overdue(case)
    domain = logic.case_domain(case)
    if domain["lock_status"] == "UNLOCKED":
        domain["lock_status"] = "LOCKED"
        domain["locked_at"] = db.now_str()
        db.touch(domain)
    case["verified_registrant_name"] = registrant_name
    case["verified_registrant_email"] = registrant_email
    case["status"] = "NOTIFICATION_PENDING"
    db.touch(case)
    return response.ok(db.public(row))


# ------------------------------------------------------------- notification
def _case_notifications(case_id):
    return db.ordered(db.notifications, lambda r: r["case_id"] == case_id)


@bp.post("/udrp/cases/<case_id>/notifications")
def dispatch_notification(case_id):
    auth("CaseManager")
    case = logic.case_or_404(case_id)
    payload = body()
    channel = v.req_enum(payload, "channel", ("EMAIL", "POSTAL", "COURIER"))
    address = v.req_str(payload, "address", 1, 512)
    attempts = _case_notifications(case_id)
    highest = logic.highest_notification(case_id)
    if case["status"] == "NOTIFICATION_PENDING":
        if any(r["status"] == "SENT" for r in attempts):
            raise ApiError("ERR_INVALID_CASE_STATE")
        first = True
    elif case["status"] == "COMMENCED":
        if highest is None or highest["status"] != "UNDELIVERABLE":
            raise ApiError("ERR_INVALID_CASE_STATE")
        first = False
    else:
        raise ApiError("ERR_INVALID_CASE_STATE")
    if first and logic.case_domain(case)["lock_status"] != "LOCKED":
        raise ApiError("ERR_DOMAIN_NOT_LOCKED")
    attempt_number = 1 if highest is None else highest["attempt_number"] + 1
    if attempt_number > calc.MAX_NOTIFICATION_ATTEMPTS:
        v.bad("attempt_number may not exceed %d." % calc.MAX_NOTIFICATION_ATTEMPTS)

    dispatched_at = db.now()
    row = db.base_row(
        case_id=case_id,
        attempt_number=attempt_number,
        channel=channel,
        address=address,
        dispatched_at=db.fmt(dispatched_at),
        deemed_received_at=None,
        status="SENT",
        failure_reason=None,
        transmission_allowance_days=calc.transmission_allowance(channel),
    )
    db.notifications[row["id"]] = row
    if first:
        case["status"] = "COMMENCED"
        case["commenced_at"] = db.fmt(dispatched_at)
    logic.project_provisional_deadline(case, row)
    db.touch(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>/notifications")
def list_notifications(case_id):
    auth("ProviderAdmin", "CaseManager", "Respondent")
    logic.case_or_404(case_id)
    limit, offset = v.pagination(request.args)
    window, total = response.paginate(_case_notifications(case_id), limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


@bp.post("/udrp/cases/<case_id>/notifications/<notification_id>/delivery")
def record_delivery(case_id, notification_id):
    auth("CaseManager")
    case = logic.case_or_404(case_id)
    row = logic.resource_or_404(db.notifications, notification_id)
    if row["case_id"] != case_id:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    payload = body()
    outcome = v.req_enum(payload, "outcome", ("DELIVERED", "UNDELIVERABLE"))
    received_raw, received = v.opt_dt(payload, "deemed_received_at")
    failure_reason = v.opt_str(payload, "failure_reason", 1, 2000)
    if received is not None and received < db.parse_dt(row["dispatched_at"]):
        v.bad("deemed_received_at may not precede the attempt's dispatched_at.")
    if row["status"] != "SENT":
        raise ApiError("ERR_INVALID_CASE_STATE")

    if outcome == "DELIVERED":
        if received is None:
            received = db.now()
            received_raw = db.fmt(received)
        row["status"] = "DELIVERED"
        row["deemed_received_at"] = received_raw
        db.touch(row)
        highest = logic.highest_notification(case_id)
        if highest is not None and highest["id"] == row["id"]:
            logic.project_final_deadline(case, received)
            db.touch(case)
    else:
        row["status"] = "UNDELIVERABLE"
        row["failure_reason"] = failure_reason
        db.touch(row)
    return response.ok(db.public(row))


# ---------------------------------------------------------------- the answer
@bp.post("/udrp/cases/<case_id>/responses")
def file_response(case_id):
    auth("Respondent")
    case = logic.case_or_404(case_id)
    payload = body()
    if isinstance(payload.get("respondent_email"), str):
        logic.ensure_respondent_identity(case, payload["respondent_email"])
    respondent_email = v.req_str(payload, "respondent_email", 1, 320)
    content_summary = v.req_str(payload, "content_summary", 10, 4000)
    wants_three = v.opt_bool(payload, "requests_three_member_panel", False)
    nominated = v.opt_str_list(payload, "nominated_panelist_ids", 0, None,
                               distinct=False)
    if logic.case_response(case_id) is not None:
        raise ApiError("ERR_RESPONSE_ALREADY_FILED")
    if case["status"] != "COMMENCED":
        raise ApiError("ERR_CASE_NOT_IN_RESPONSE_WINDOW")
    submitted_at = db.now()
    due = db.parse_dt(case["response_due_at"]) if case.get("response_due_at") else None
    if due is not None and submitted_at > calc.default_cutoff(due):
        raise ApiError("ERR_RESPONSE_DEADLINE_PASSED")

    row = db.base_row(
        case_id=case_id,
        respondent_email=respondent_email,
        content_summary=content_summary,
        requests_three_member_panel=wants_three,
        nominated_panelist_ids=nominated,
        submitted_at=db.fmt(submitted_at),
        timeliness="ON_TIME" if (due is None or submitted_at <= due) else "LATE",
    )
    db.responses[row["id"]] = row
    case["status"] = "RESPONSE_RECEIVED"
    if wants_three:
        case["respondent_panel_election"] = "THREE"
        case["required_seat_count"] = 3
        logic.reprice(case, "FINAL")
    db.touch(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>/responses")
def list_responses(case_id):
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent", "Panelist")
    logic.case_or_404(case_id)
    limit, offset = v.pagination(request.args)
    rows = db.ordered(db.responses, lambda r: r["case_id"] == case_id)
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)
