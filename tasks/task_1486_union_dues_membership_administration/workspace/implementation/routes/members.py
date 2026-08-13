"""Member endpoints: registration, reads, payments, withdrawal,
reinstatement quote/reinstate, assessments/ledger/remittance-lines listings,
delinquency notices, objector-case filing, transfer initiation, eligibilities.
"""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles, check_member_ownership, ALL_ROLES
from response import ok, ok_list
from services import ledger as ledger_svc
from services import sweep as sweep_svc

bp = Blueprint("members", __name__, url_prefix="/api/members")

TERMINAL_MEMBER_STATES = ("WITHDRAWN", "EXPELLED")


def get_member_or_404(member_id):
    member = db.store.members.get(member_id)
    if member is None:
        raise errors.member_not_found()
    return member


def reinstatement_quote(member):
    """reinstatement_due (scaffold calculations[3]): pinned evaluation order —
    arrears BEFORE any fee posting; fee = base * suspension_count (the count
    was incremented at suspension time and is not modified by the quote);
    total = arrears + fee."""
    local = db.store.locals[member["local_id"]]
    arrears, _ = ledger_svc.balances(member["id"])
    fee = local["reinstatement_base_fee_cents"] * member["suspension_count"]
    return {
        "arrears_cents": arrears,
        "reinstatement_fee_cents": fee,
        "total_due_cents": arrears + fee,
    }


@bp.route("", methods=["POST"])
@require_roles("OfficeClerk")
def create_member(user_id, role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    local_id = utils.require_field(body, "local_id")
    classification_id = utils.require_field(body, "classification_id")
    full_name = utils.require_field(body, "full_name")
    member_number = utils.require_field(body, "member_number")
    joined_at = utils.require_field(body, "joined_at")
    employer_id = body.get("employer_id")

    local = db.store.locals.get(local_id)
    if local is None:
        raise errors.local_not_found_body()
    classification = db.store.classifications.get(classification_id)
    if classification is None or classification["local_id"] != local_id:
        raise errors.classification_not_found_body()
    if employer_id is not None and employer_id not in db.store.employers:
        raise errors.employer_not_found_body()
    for m in db.store.members.values():
        if m["local_id"] == local_id and m["member_number"] == member_number:
            raise errors.duplicate_member_number()

    ts = db.fmt_ts(db.now())
    member = {
        "id": utils.new_id(),
        "local_id": local_id,
        "classification_id": classification_id,
        "employer_id": employer_id,
        "full_name": full_name,
        "member_number": member_number,
        "joined_at": joined_at,
        "status": "ACTIVE",
        "suspension_count": 0,
        "suspended_since": None,
        "last_suspension_ended_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.members[member["id"]] = member
    return ok(serializers.member(member), 201)


@bp.route("", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_members(user_id, role):
    rows = list(db.store.members.values())
    for f in ("local_id", "classification_id", "employer_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [m for m in rows if m.get(f) == v]
    rows.sort(key=lambda m: m["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.member(m) for m in page], meta)


@bp.route("/<member_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_member(user_id, role, member_id):
    return ok(serializers.member(get_member_or_404(member_id)), 200)


@bp.route("/<member_id>/payments", methods=["POST"])
@require_roles("SecretaryTreasurer", "Member")
def record_payment(user_id, role, member_id):
    check_member_ownership(user_id, role, member_id)
    member = get_member_or_404(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    amount = utils.require_int(body, "amount_cents")
    if amount <= 0:
        raise errors.payment_invalid_amount()
    entry = ledger_svc.post_entry(
        member_id, "DIRECT_PAYMENT", -amount, db.current_period(),
        memo="direct payment")
    ledger_svc.auto_cure(member)
    db.touch(member)
    return ok(serializers.ledger_entry(entry), 201)


@bp.route("/<member_id>/withdraw", methods=["POST"])
@require_roles("Member")
def withdraw_member(user_id, role, member_id):
    check_member_ownership(user_id, role, member_id)
    member = get_member_or_404(member_id)
    if member["status"] in TERMINAL_MEMBER_STATES:
        raise errors.member_terminal_state()
    if member["status"] == "SUSPENDED":
        raise errors.member_state_forbidden()
    arrears, _ = ledger_svc.balances(member_id)
    if arrears != 0:
        raise errors.arrears_outstanding()
    member["status"] = "WITHDRAWN"
    sweep_svc.cancel_transfers(member_id, sweep_svc.NON_TERMINAL_TRANSFER_STATES)
    for n in list(db.store.notices.values()):
        if n["member_id"] != member_id:
            continue
        if n["status"] == "DRAFT":
            del db.store.notices[n["id"]]
        elif n["status"] == "SENT":
            n["status"] = "CURED"
            db.touch(n)
    db.touch(member)
    return ok(serializers.member(member), 200)


@bp.route("/<member_id>/reinstatement-quote", methods=["GET"])
@require_roles("SecretaryTreasurer")
def get_reinstatement_quote(user_id, role, member_id):
    member = get_member_or_404(member_id)
    if member["status"] != "SUSPENDED":
        raise errors.member_not_suspended()
    return ok(reinstatement_quote(member), 200)


@bp.route("/<member_id>/reinstate", methods=["POST"])
@require_roles("SecretaryTreasurer")
def reinstate_member(user_id, role, member_id):
    member = get_member_or_404(member_id)
    if member["status"] != "SUSPENDED":
        raise errors.member_not_suspended()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    amount = utils.require_int(body, "amount_cents")
    quote = reinstatement_quote(member)
    if amount != quote["total_due_cents"]:
        raise errors.reinstatement_amount_mismatch()
    period = db.current_period()
    ledger_svc.post_entry(member_id, "REINSTATEMENT_FEE",
                          quote["reinstatement_fee_cents"], period,
                          memo="reinstatement fee")
    ledger_svc.post_entry(member_id, "DIRECT_PAYMENT", -amount, period,
                          memo="reinstatement payment")
    member["status"] = "ACTIVE"
    member["suspended_since"] = None
    member["last_suspension_ended_at"] = db.fmt_ts(db.now())
    db.touch(member)
    return ok(serializers.member(member), 200)


@bp.route("/<member_id>/assessments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_member_assessments(user_id, role, member_id):
    get_member_or_404(member_id)
    rows = [a for a in db.store.assessments.values()
            if a["member_id"] == member_id]
    period = request.args.get("period")
    status = request.args.get("status")
    if period is not None:
        rows = [a for a in rows if a["period"] == period]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=lambda a: a["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.assessment(a) for a in page], meta)


@bp.route("/<member_id>/ledger", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_member_ledger(user_id, role, member_id):
    get_member_or_404(member_id)
    rows = ledger_svc.member_entries(member_id)
    period = request.args.get("period")
    entry_type = request.args.get("entry_type")
    if period is not None:
        rows = [e for e in rows if e["period"] == period]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    page, meta = utils.paginate(rows)
    return ok_list([serializers.ledger_entry(e) for e in page], meta)


@bp.route("/<member_id>/remittance-lines", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_member_remittance_lines(user_id, role, member_id):
    get_member_or_404(member_id)
    rows = [l for l in db.store.remittance_lines.values()
            if l["member_id"] == member_id]
    period = request.args.get("period")
    if period is not None:
        rows = [l for l in rows
                if db.store.remittances[l["remittance_id"]]["period"] == period]
    rows.sort(key=lambda l: l["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.remittance_line(l) for l in page], meta)


# --- Delinquency notices (member-scoped) ------------------------------------

@bp.route("/<member_id>/notices", methods=["POST"])
@require_roles("OfficeClerk")
def create_notice(user_id, role, member_id):
    member = get_member_or_404(member_id)
    if member["status"] != "DELINQUENT":
        raise errors.member_state_forbidden()
    for n in db.store.notices.values():
        if n["member_id"] == member_id and n["status"] == "DRAFT":
            raise errors.notice_window_open()
    arrears, _ = ledger_svc.balances(member_id)
    notice = sweep_svc._create_draft_notice(member, arrears)
    return ok(serializers.notice(notice), 201)


@bp.route("/<member_id>/notices", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_notices(user_id, role, member_id):
    get_member_or_404(member_id)
    rows = [n for n in db.store.notices.values() if n["member_id"] == member_id]
    status = request.args.get("status")
    if status is not None:
        rows = [n for n in rows if n["status"] == status]
    rows.sort(key=lambda n: n["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.notice(n) for n in page], meta)


@bp.route("/<member_id>/notices/<notice_id>/send", methods=["POST"])
@require_roles("OfficeClerk")
def send_notice(user_id, role, member_id, notice_id):
    get_member_or_404(member_id)
    notice = db.store.notices.get(notice_id)
    if notice is None or notice["member_id"] != member_id:
        raise errors.notice_not_found()
    if notice["status"] != "DRAFT":
        raise errors.notice_state_forbidden()
    now = db.now()
    for n in db.store.notices.values():
        if (n["member_id"] == member_id and n["status"] == "SENT"
                and n["id"] != notice_id):
            # Half-open window [sent_at, cure_deadline): send refused while it
            # contains the current clock time.
            if utils.parse_datetime(n["sent_at"]) <= now < utils.parse_datetime(n["cure_deadline"]):
                raise errors.notice_window_open()
    member = db.store.members[member_id]
    local = db.store.locals[member["local_id"]]
    notice["sent_at"] = db.fmt_ts(now)
    notice["cure_deadline"] = db.fmt_ts(
        utils.deadline_plus_days(now, local["notice_cure_days"]))
    notice["status"] = "SENT"
    db.touch(notice)
    return ok(serializers.notice(notice), 200)


# --- Objector-case filing (member-scoped) -----------------------------------

@bp.route("/<member_id>/objector-cases", methods=["POST"])
@require_roles("Member")
def file_objector_case(user_id, role, member_id):
    check_member_ownership(user_id, role, member_id)
    member = get_member_or_404(member_id)
    if member["status"] in TERMINAL_MEMBER_STATES:
        raise errors.member_terminal_state()
    if member["status"] == "SUSPENDED":
        raise errors.member_state_forbidden()
    for c in db.store.objector_cases.values():
        if c["member_id"] == member_id and c["status"] != "CLOSED":
            raise errors.objector_case_exists()
    ts = db.fmt_ts(db.now())
    case = {
        "id": utils.new_id(),
        "member_id": member_id,
        "filed_at": ts,
        "status": "FILED",
        "chargeable_share_pct": None,
        "rate_set_at": None,
        "last_rebated_period": None,
        "cumulative_rebate_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.objector_cases[case["id"]] = case
    return ok(serializers.objector_case(case), 201)


# --- Transfer initiation (member-scoped, OCC on Member.version) --------------

@bp.route("/<member_id>/transfers", methods=["POST"])
@require_roles("Member", "OfficeClerk")
def initiate_transfer(user_id, role, member_id):
    check_member_ownership(user_id, role, member_id)
    member = get_member_or_404(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    expected = utils.require_int(body, "expected_member_version")
    if expected != member["version"]:
        raise errors.stale_member_version()
    arrears, _ = ledger_svc.balances(member_id)
    if member["status"] != "ACTIVE" or arrears != 0:
        raise errors.not_good_standing()
    to_local_id = utils.require_field(body, "to_local_id")
    target = db.store.locals.get(to_local_id)
    if (target is None or target["status"] != "ACTIVE"
            or to_local_id == member["local_id"]):
        raise errors.target_local_unavailable()
    effective_period = utils.require_field(body, "effective_period")
    utils.parse_period(effective_period)
    if utils.period_key(effective_period) < utils.period_key(db.current_period()):
        raise errors.invalid_period()
    # A fresh create supersedes any non-terminal transfer of the member.
    for t in db.store.transfers.values():
        if (t["member_id"] == member_id
                and t["status"] in sweep_svc.NON_TERMINAL_TRANSFER_STATES):
            t["status"] = "SUPERSEDED"
            db.touch(t)
    ts = db.fmt_ts(db.now())
    transfer = {
        "id": utils.new_id(),
        "member_id": member_id,
        "from_local_id": member["local_id"],
        "to_local_id": to_local_id,
        "effective_period": effective_period,
        "status": "INITIATED",
        "reject_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.transfers[transfer["id"]] = transfer
    db.touch(member)  # initiation increments Member.version
    return ok(serializers.transfer(transfer), 201)


# --- Member eligibility history ----------------------------------------------

@bp.route("/<member_id>/eligibilities", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_member_eligibilities(user_id, role, member_id):
    get_member_or_404(member_id)
    rows = [e for e in db.store.eligibilities.values()
            if e["member_id"] == member_id]
    election_id = request.args.get("election_id")
    if election_id is not None:
        rows = [e for e in rows if e["election_id"] == election_id]
    rows.sort(key=lambda e: e["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.eligibility(e) for e in page], meta)
