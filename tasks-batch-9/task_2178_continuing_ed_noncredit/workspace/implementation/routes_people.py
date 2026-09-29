"""Learners, marketing memberships, instructors, corporate sponsor accounts
and the voucher ledger."""
from flask import Blueprint, request

import calc
import domain
from core import (DB, D, base_record, body, as_str, as_int, as_bool, as_dt,
                  as_enum, as_id, authenticate, envelope_object, fail,
                  get_account, get_instructor, get_learner, get_voucher, now,
                  own, paginate, qfilter, touch)

bp = Blueprint("people", __name__)

ALL_AUTH = ("ProgramAdmin", "Registrar", "Learner", "Instructor", "CorporateSponsor")
CREDENTIAL_LEVELS = ("ADJUNCT", "SENIOR", "MASTER")


# ---------------------------------------------------------------------------
# Learners
# ---------------------------------------------------------------------------

@bp.post("/learners")
def create_learner():
    authenticate(("Anonymous", "Registrar", "ProgramAdmin"))
    payload = body()
    email = as_str(payload, "email")
    full_name = as_str(payload, "full_name")
    marketing_opt_in = as_bool(payload, "marketing_opt_in", required=False, default=True)
    for existing in DB.learners.values():
        if existing["email"].lower() == email.lower():
            fail("ERR_INVALID_REQUEST", "email must be unique")
    rec = base_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "marketing_opt_in": marketing_opt_in,
        "marketing_status": "SUBSCRIBED" if marketing_opt_in else "UNSUBSCRIBED",
        "lifetime_completed_count": 0,
        "lifetime_ceu_total": D("0.0"),
        "loyalty_tier": "NEW",
    })
    DB.learners[rec["id"]] = rec
    domain.marketing_segment_recompute(rec)
    return envelope_object(domain.ser_learner(rec)), 201


@bp.get("/learners/<lid>")
def read_learner(lid):
    actor = authenticate(("Learner", "Registrar", "ProgramAdmin"))
    learner = get_learner(lid)
    if actor.role == "Learner":
        own(actor.user_id == lid)
    return envelope_object(domain.ser_learner(learner)), 200


@bp.get("/learners/<lid>/marketing-memberships")
def list_memberships(lid):
    authenticate(("Registrar", "ProgramAdmin", "Learner"))
    get_learner(lid)
    rows = [m for m in DB.marketing_memberships.values() if m["learner_id"] == lid]
    rows = qfilter(rows, "segment")
    rows = qfilter(rows, "state")
    return paginate(rows, domain.ser_membership), 200


@bp.post("/learners/<lid>/marketing-preference")
def marketing_preference(lid):
    actor = authenticate(("Learner", "Registrar"))
    payload = body()
    marketing_opt_in = as_bool(payload, "marketing_opt_in")
    learner = get_learner(lid)
    if actor.role == "Learner":
        own(actor.user_id == lid)
    learner["marketing_status"] = "SUBSCRIBED" if marketing_opt_in else "UNSUBSCRIBED"
    touch(learner)
    domain.marketing_segment_recompute(learner)
    return envelope_object(domain.ser_learner(learner)), 200


# ---------------------------------------------------------------------------
# Instructors
# ---------------------------------------------------------------------------

@bp.post("/instructors")
def create_instructor():
    authenticate(("ProgramAdmin",))
    payload = body()
    email = as_str(payload, "email")
    full_name = as_str(payload, "full_name")
    credential_level = as_enum(payload, "credential_level", CREDENTIAL_LEVELS)
    for existing in DB.instructors.values():
        if existing["email"].lower() == email.lower():
            fail("ERR_INVALID_REQUEST", "email must be unique")
    rec = base_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "credential_level": credential_level,
        "active_contract_count": 0,
    })
    DB.instructors[rec["id"]] = rec
    return envelope_object(domain.ser_instructor(rec)), 201


@bp.get("/instructors/<iid>")
def read_instructor(iid):
    authenticate(("ProgramAdmin", "Registrar", "Instructor"))
    return envelope_object(domain.ser_instructor(get_instructor(iid))), 200


# ---------------------------------------------------------------------------
# Corporate accounts
# ---------------------------------------------------------------------------

@bp.post("/corporate-accounts")
def create_account():
    authenticate(("ProgramAdmin",))
    payload = body()
    org_name = as_str(payload, "org_name")
    billing_email = as_str(payload, "billing_email")
    rec = base_record()
    rec.update({
        "org_name": org_name,
        "billing_email": billing_email,
        "status": "ACTIVE",
        "funded_cents": 0,
        "available_cents": 0,
        "unallocated_voucher_cents": 0,
        "committed_cents": 0,
        "consumed_cents": 0,
    })
    DB.corporate_accounts[rec["id"]] = rec
    return envelope_object(domain.ser_account(rec)), 201


@bp.get("/corporate-accounts/<aid>")
def read_account(aid):
    authenticate(("ProgramAdmin", "Registrar", "CorporateSponsor"))
    return envelope_object(domain.ser_account(get_account(aid))), 200


@bp.post("/corporate-accounts/<aid>/suspend")
def suspend_account(aid):
    authenticate(("ProgramAdmin",))
    account = get_account(aid)
    if account["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Account is not ACTIVE")
    account["status"] = "SUSPENDED"
    touch(account)
    return envelope_object(domain.ser_account(account)), 200


@bp.post("/corporate-accounts/<aid>/reinstate")
def reinstate_account(aid):
    authenticate(("ProgramAdmin",))
    account = get_account(aid)
    if account["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Account is not SUSPENDED")
    account["status"] = "ACTIVE"
    touch(account)
    return envelope_object(domain.ser_account(account)), 200


@bp.post("/corporate-accounts/<aid>/deposits")
def create_deposit(aid):
    actor = authenticate(("ProgramAdmin", "CorporateSponsor"))
    payload = body()
    amount_cents = as_int(payload, "amount_cents", minimum=0)
    account = get_account(aid)
    if actor.role == "CorporateSponsor":
        own(actor.user_id == aid)
    account["funded_cents"] += amount_cents
    domain.recompute_account_ledger(account)
    touch(account)
    return envelope_object(domain.ser_account(account)), 201


@bp.post("/corporate-accounts/<aid>/vouchers")
def issue_voucher(aid):
    actor = authenticate(("CorporateSponsor", "ProgramAdmin"))
    payload = body()
    face_value_cents = as_int(payload, "face_value_cents", minimum=1)
    expires_at = as_dt(payload, "expires_at")
    expected_version = as_int(payload, "expected_corporate_account_version")
    account = get_account(aid)
    if actor.role == "CorporateSponsor":
        own(actor.user_id == aid)
    if expected_version != account["version"]:
        fail("ERR_STALE_VERSION", "expected_corporate_account_version does not match")
    if account["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Sponsor account is SUSPENDED")
    if account["available_cents"] < face_value_cents:
        fail("ERR_ACCOUNT_FUNDS_INSUFFICIENT", "Sponsor budget is insufficient")
    rec = base_record()
    rec.update({
        "corporate_account_id": aid,
        "assigned_learner_id": None,
        "face_value_cents": face_value_cents,
        "remaining_cents": face_value_cents,
        "committed_cents": 0,
        "consumed_cents": 0,
        "expires_at": expires_at,
        "status": "ISSUED",
    })
    DB.vouchers[rec["id"]] = rec
    domain.recompute_account_ledger(account)
    touch(account)
    return envelope_object(domain.ser_voucher(rec)), 201


# ---------------------------------------------------------------------------
# Vouchers
# ---------------------------------------------------------------------------

@bp.get("/vouchers")
def list_vouchers():
    authenticate(("ProgramAdmin", "Registrar", "CorporateSponsor", "Learner"))
    rows = list(DB.vouchers.values())
    rows = qfilter(rows, "corporate_account_id")
    rows = qfilter(rows, "assigned_learner_id")
    rows = qfilter(rows, "status")
    return paginate(rows, domain.ser_voucher), 200


@bp.get("/vouchers/<vid>")
def read_voucher(vid):
    authenticate(("ProgramAdmin", "Registrar", "CorporateSponsor", "Learner"))
    return envelope_object(domain.ser_voucher(get_voucher(vid))), 200


@bp.post("/vouchers/<vid>/assign")
def assign_voucher(vid):
    actor = authenticate(("CorporateSponsor",))
    payload = body()
    learner_id = as_id(payload, "learner_id")
    voucher = get_voucher(vid)
    learner = get_learner(learner_id)
    own(actor.user_id == voucher["corporate_account_id"])
    if voucher["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Voucher is not ISSUED")
    account = DB.corporate_accounts[voucher["corporate_account_id"]]
    if account["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Sponsor account is SUSPENDED")
    if not now() < voucher["expires_at"]:
        fail("ERR_INVALID_STATE", "Voucher has expired")
    voucher["assigned_learner_id"] = learner_id
    voucher["status"] = "ASSIGNED"
    touch(voucher)
    domain.marketing_segment_recompute(learner)
    return envelope_object(domain.ser_voucher(voucher)), 200


@bp.post("/vouchers/<vid>/void")
def void_voucher(vid):
    actor = authenticate(("CorporateSponsor",))
    voucher = get_voucher(vid)
    own(actor.user_id == voucher["corporate_account_id"])
    if voucher["status"] not in ("ISSUED", "ASSIGNED"):
        fail("ERR_INVALID_STATE", "Voucher is not ISSUED or ASSIGNED")
    if voucher["committed_cents"] != 0 or voucher["consumed_cents"] != 0:
        fail("ERR_INVALID_STATE", "Voucher value has already been spent or reserved")
    voucher["status"] = "VOIDED"
    voucher["remaining_cents"] = 0
    touch(voucher)
    account = DB.corporate_accounts[voucher["corporate_account_id"]]
    domain.recompute_account_ledger(account)
    touch(account)
    return envelope_object(domain.ser_voucher(voucher)), 200
