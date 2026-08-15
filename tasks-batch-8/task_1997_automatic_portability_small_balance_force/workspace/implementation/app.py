"""Automatic Portability & Small-Balance Force-Out API — Flask entry point.

Implements the full PRD contract: recordkeeper network, plans, participants,
force-out batches/cases, notices & election window, checks, safe-harbor IRAs,
fee ledger, match candidates, transfers, fiduciary reviews, sweep and the
test-driving logical clock.

Storage is in-memory only; the store starts empty on every boot.
"""

import os
from datetime import timedelta

from flask import Flask

from core import (
    ALL_ROLES, MISSING, ApiError, DB,
    accrued_fee, auth, batch_counters, cases_of_batch, compute_match_score,
    confirmed_match_of_ira, current_notice, delivered_notice, err_400, err_404,
    err_409, err_422, error_response, escheat_warning_matured, fee_day_count,
    fee_for_days, fmt_dt, force_out_path, get_body, get_or_404, ira_of_case,
    list_response, mark_bad_address, net_check_withholding, new_id, now,
    parse_dt, recompute_reachable, require_roles, rhu_product, ser_batch,
    ser_case, ser_check, ser_election, ser_fee, ser_ira, ser_match, ser_notice,
    ser_participant, ser_plan, ser_recordkeeper, ser_review, ser_transfer,
    set_clock, stamp_new, submitted_election, success, touch, v_opt_bool,
    v_opt_int, v_opt_num, v_opt_str, v_req_bool, v_req_date, v_req_dt,
    v_req_enum, v_req_int, v_req_num, v_req_str, v_req_version, vested_balance,
    AUTO_CONFIRM, CONFIRM_FLOOR, REVIEW_FLOOR,
    CHECK_STALE_DAYS, ESCHEAT_DORMANCY_DAYS, ESCHEAT_WARNING_LEAD_DAYS,
    MATCH_EXPIRY_DAYS, NOTICE_WINDOW_DAYS,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handlers — every error uses the standard envelope (PRD §2.2).
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_response(ApiError("ERR_INTERNAL", 500, f"Internal error: {e}"))


# ===========================================================================
# Recordkeepers
# ===========================================================================
@app.post("/recordkeepers")
def create_recordkeeper():
    require_roles("ProviderOps")
    b = get_body()
    code = v_req_str(b, "recordkeeper_code")
    legal_name = v_req_str(b, "legal_name")
    for r in DB.recordkeepers.values():
        if r["recordkeeper_code"] == code:
            raise err_400("recordkeeper_code must be unique across the recordkeeper registry")
    rec = stamp_new({
        "recordkeeper_code": code,
        "legal_name": legal_name,
        "network_status": "PENDING_ONBOARD",
        "exited_at": None,
    })
    DB.recordkeepers[rec["id"]] = rec
    return success(ser_recordkeeper(rec), "object", 201)


@app.get("/recordkeepers")
def list_recordkeepers():
    require_roles(*ALL_ROLES)
    return list_response(DB.recordkeepers.values(), ser_recordkeeper, ["network_status"])


@app.get("/recordkeepers/<rid>")
def get_recordkeeper(rid):
    require_roles(*ALL_ROLES)
    return success(ser_recordkeeper(get_or_404(DB.recordkeepers, rid, "Recordkeeper")))


def _recompute_plans_of_recordkeeper(rk_id):
    """Recompute network_reachable for every plan of the recordkeeper; bump
    the version of each plan whose value actually changes. Returns the set of
    plan ids that flipped from reachable to unreachable."""
    flipped_off = set()
    for p in DB.plans.values():
        if p["recordkeeper_id"] != rk_id:
            continue
        new_val = recompute_reachable(p)
        if p["network_reachable"] != new_val:
            if p["network_reachable"] and not new_val:
                flipped_off.add(p["id"])
            p["network_reachable"] = new_val
            touch(p)
    return flipped_off


@app.post("/recordkeepers/<rid>/activate")
def activate_recordkeeper(rid):
    require_roles("ProviderOps")
    rec = get_or_404(DB.recordkeepers, rid, "Recordkeeper")
    if rec["network_status"] not in ("PENDING_ONBOARD", "SUSPENDED"):
        raise err_409(f"Recordkeeper in {rec['network_status']} cannot be activated")
    rec["network_status"] = "ACTIVE"
    touch(rec)
    _recompute_plans_of_recordkeeper(rid)
    return success(ser_recordkeeper(rec))


@app.post("/recordkeepers/<rid>/suspend")
def suspend_recordkeeper(rid):
    require_roles("ProviderOps")
    rec = get_or_404(DB.recordkeepers, rid, "Recordkeeper")
    if rec["network_status"] != "ACTIVE":
        raise err_409(f"Recordkeeper in {rec['network_status']} cannot be suspended")
    rec["network_status"] = "SUSPENDED"
    touch(rec)
    _recompute_plans_of_recordkeeper(rid)
    return success(ser_recordkeeper(rec))


@app.post("/recordkeepers/<rid>/exit")
def exit_recordkeeper(rid):
    require_roles("ProviderOps")
    rec = get_or_404(DB.recordkeepers, rid, "Recordkeeper")
    if rec["network_status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_409(f"Recordkeeper in {rec['network_status']} cannot exit")
    rec["network_status"] = "EXITED"
    rec["exited_at"] = now()
    touch(rec)
    # §2.8 three-link cascade.
    flipped_off = _recompute_plans_of_recordkeeper(rid)          # link 1: plans lose reachability
    just_expired_confirmed = []
    for m in DB.matches.values():                                # link 2: matches on darkened plans expire
        if (m["match_status"] in ("CANDIDATE", "CONFIRMED")
                and m["new_plan_id"] in flipped_off):
            was_confirmed = m["match_status"] == "CONFIRMED"
            m["match_status"] = "EXPIRED"
            touch(m)
            if was_confirmed:
                just_expired_confirmed.append(m)
    for m in just_expired_confirmed:                             # link 3: IRAs matched on them reopen
        ira = DB.iras.get(m["safe_harbor_ira_id"])
        if ira is not None and ira["ira_status"] == "MATCHED":
            ira["ira_status"] = "OPEN"
            touch(ira)  # last_activity_at deliberately unchanged
    return success(ser_recordkeeper(rec))


# ===========================================================================
# Plans
# ===========================================================================
@app.post("/plans")
def create_plan():
    require_roles("PlanSponsor")
    b = get_body()
    plan_name = v_req_str(b, "plan_name")
    sponsor_ein = v_req_str(b, "sponsor_ein")
    recordkeeper_id = v_req_str(b, "recordkeeper_id")
    cash_out = v_opt_int(b, "cash_out_threshold_cents", 100000)
    rollover = v_opt_int(b, "rollover_threshold_cents", 700000)
    rate = v_opt_num(b, "state_withholding_rate", 0)
    basis = v_req_enum(b, "valuation_basis", ("SEPARATION_DATE", "PROCESSING_DATE")) \
        if "valuation_basis" in b else "PROCESSING_DATE"
    auto_port = v_opt_bool(b, "auto_portability_enabled", True)
    accepts = v_opt_bool(b, "accepts_incoming_transfers", True)
    if cash_out < 1 or cash_out > rollover or rate < 0 or rate > 0.15:
        raise err_400("Invalid force-out configuration: 1 <= cash_out_threshold_cents "
                      "<= rollover_threshold_cents and 0 <= state_withholding_rate <= 0.15")
    get_or_404(DB.recordkeepers, recordkeeper_id, "Recordkeeper")
    plan = stamp_new({
        "plan_name": plan_name,
        "sponsor_ein": sponsor_ein,
        "recordkeeper_id": recordkeeper_id,
        "cash_out_threshold_cents": cash_out,
        "rollover_threshold_cents": rollover,
        "state_withholding_rate": rate,
        "valuation_basis": basis,
        "auto_portability_enabled": auto_port,
        "accepts_incoming_transfers": accepts,
        "network_reachable": False,
        "plan_status": "ACTIVE",
    })
    plan["network_reachable"] = recompute_reachable(plan)
    DB.plans[plan["id"]] = plan
    return success(ser_plan(plan), "object", 201)


@app.get("/plans")
def list_plans():
    require_roles(*ALL_ROLES)
    return list_response(DB.plans.values(), ser_plan, ["recordkeeper_id", "plan_status"])


@app.get("/plans/<pid>")
def get_plan(pid):
    require_roles(*ALL_ROLES)
    return success(ser_plan(get_or_404(DB.plans, pid, "Plan")))


@app.patch("/plans/<pid>")
def patch_plan(pid):
    require_roles("PlanSponsor")
    b = get_body()
    expected = v_req_version(b, "expected_plan_version")
    # Shape-check optional fields before applying anything.
    cash_out = v_opt_int(b, "cash_out_threshold_cents", MISSING)
    rollover = v_opt_int(b, "rollover_threshold_cents", MISSING)
    rate = v_opt_num(b, "state_withholding_rate", MISSING)
    basis = MISSING
    if "valuation_basis" in b:
        basis = v_req_enum(b, "valuation_basis", ("SEPARATION_DATE", "PROCESSING_DATE"))
    auto_port = v_opt_bool(b, "auto_portability_enabled", MISSING)
    accepts = v_opt_bool(b, "accepts_incoming_transfers", MISSING)

    plan = get_or_404(DB.plans, pid, "Plan")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_plan_version does not match the plan's current version")

    merged_cash = plan["cash_out_threshold_cents"] if cash_out is MISSING else cash_out
    merged_roll = plan["rollover_threshold_cents"] if rollover is MISSING else rollover
    merged_rate = plan["state_withholding_rate"] if rate is MISSING else rate
    if merged_cash < 1 or merged_cash > merged_roll or merged_rate < 0 or merged_rate > 0.15:
        raise err_422("ERR_THRESHOLD_CONFIG_INVALID",
                      "cash_out_threshold_cents must be >= 1 and <= rollover_threshold_cents; "
                      "state_withholding_rate must lie in [0, 0.15]")

    if cash_out is not MISSING:
        plan["cash_out_threshold_cents"] = cash_out
    if rollover is not MISSING:
        plan["rollover_threshold_cents"] = rollover
    if rate is not MISSING:
        plan["state_withholding_rate"] = rate
    if basis is not MISSING:
        plan["valuation_basis"] = basis
    if auto_port is not MISSING:
        plan["auto_portability_enabled"] = auto_port
    if accepts is not MISSING:
        plan["accepts_incoming_transfers"] = accepts
    plan["network_reachable"] = recompute_reachable(plan)
    touch(plan)
    return success(ser_plan(plan))


@app.post("/plans/<pid>/terminate")
def terminate_plan(pid):
    require_roles("PlanSponsor")
    plan = get_or_404(DB.plans, pid, "Plan")
    if plan["plan_status"] != "ACTIVE":
        raise err_409(f"Plan in {plan['plan_status']} cannot be terminated")
    for bt in DB.batches.values():
        if bt["plan_id"] == pid and bt["batch_status"] in ("OPEN", "LOCKED", "EXECUTED", "RECON_EXCEPTION"):
            raise err_409("Plan has a distribution batch in flight; termination is blocked")
    plan["plan_status"] = "TERMINATED"
    plan["network_reachable"] = False
    touch(plan)
    return success(ser_plan(plan))


# ===========================================================================
# Participants
# ===========================================================================
@app.post("/participants")
def create_participant():
    require_roles("PlanSponsor", "ProviderOps")
    b = get_body()
    ssn_hash = v_req_str(b, "ssn_hash")
    full_name = v_req_str(b, "full_name")
    dob = v_req_date(b, "date_of_birth")
    line1 = v_req_str(b, "mailing_address_line1")
    city = v_req_str(b, "mailing_city")
    state = v_req_str(b, "mailing_state")
    zipcode = v_req_str(b, "mailing_zip")
    email = b.get("email", None)
    if email is not None and not isinstance(email, str):
        raise err_400("email must be a string or null")
    for p in DB.participants.values():
        if p["ssn_hash"] == ssn_hash:
            raise err_400("ssn_hash must be unique across the participant registry")
    # Client-supplied system fields (id/created_at/version) are ignored.
    part = stamp_new({
        "ssn_hash": ssn_hash,
        "full_name": full_name,
        "date_of_birth": dob,
        "mailing_address_line1": line1,
        "mailing_city": city,
        "mailing_state": state,
        "mailing_zip": zipcode,
        "email": email,
        "address_quality": "UNVERIFIED",
    })
    DB.participants[part["id"]] = part
    return success(ser_participant(part), "object", 201)


@app.get("/participants")
def list_participants():
    require_roles(*ALL_ROLES)
    return list_response(DB.participants.values(), ser_participant, ["ssn_hash", "address_quality"])


@app.get("/participants/<pid>")
def get_participant(pid):
    require_roles(*ALL_ROLES)
    return success(ser_participant(get_or_404(DB.participants, pid, "Participant")))


@app.patch("/participants/<pid>")
def patch_participant(pid):
    uid, role = require_roles("PlanSponsor", "ProviderOps", "Participant")
    if role == "Participant" and uid != pid:
        raise ApiError("ERR_PARTICIPANT_OWNERSHIP_MISMATCH", 403,
                       "A Participant may only update their own record")
    part = get_or_404(DB.participants, pid, "Participant")
    b = get_body()
    for field in ("mailing_address_line1", "mailing_city", "mailing_state", "mailing_zip"):
        v = b.get(field, MISSING)
        if v is not MISSING:
            if not isinstance(v, str):
                raise err_400(f"Field must be a string: {field}")
            part[field] = v
    if "email" in b:
        v = b["email"]
        if v is not None and not isinstance(v, str):
            raise err_400("email must be a string or null")
        part["email"] = v
    part["address_quality"] = "VALID"
    touch(part)
    return success(ser_participant(part))


# ===========================================================================
# Distribution batches
# ===========================================================================
@app.post("/distribution-batches")
def create_batch():
    require_roles("PlanSponsor")
    b = get_body()
    plan_id = v_req_str(b, "plan_id")
    plan = get_or_404(DB.plans, plan_id, "Plan")
    if plan["plan_status"] != "ACTIVE":
        raise err_422("ERR_PLAN_NOT_ACTIVE", "Plan is TERMINATED; batch creation is blocked")
    for bt in DB.batches.values():
        if bt["plan_id"] == plan_id and bt["batch_status"] in ("OPEN", "LOCKED", "EXECUTED", "RECON_EXCEPTION"):
            raise ApiError("ERR_DUPLICATE_OPEN_BATCH", 409,
                           "Plan already has a distribution batch in flight")
    batch = stamp_new({
        "plan_id": plan_id,
        "batch_status": "OPEN",
        "executed_by_user_id": None,
        "locked_at": None,
        "executed_at": None,
        "reconciled_at": None,
    })
    DB.batches[batch["id"]] = batch
    return success(ser_batch(batch), "object", 201)


@app.get("/distribution-batches")
def list_batches():
    require_roles(*ALL_ROLES)
    return list_response(DB.batches.values(), ser_batch, ["plan_id", "batch_status"])


@app.get("/distribution-batches/<bid>")
def get_batch(bid):
    require_roles(*ALL_ROLES)
    return success(ser_batch(get_or_404(DB.batches, bid, "DistributionBatch")))


@app.post("/distribution-batches/<bid>/lock")
def lock_batch(bid):
    require_roles("PlanSponsor")
    batch = get_or_404(DB.batches, bid, "DistributionBatch")
    if batch["batch_status"] != "OPEN":
        raise err_409(f"Batch in {batch['batch_status']} cannot be locked")
    batch_cases = cases_of_batch(bid)
    if len(batch_cases) < 1:
        raise err_409("Batch has no attached cases; locking an empty batch is not permitted")
    plan = DB.plans[batch["plan_id"]]
    for c in batch_cases:
        if c["case_status"] != "IDENTIFIED":
            continue
        selected = (c["separation_date_balance_cents"]
                    if plan["valuation_basis"] == "SEPARATION_DATE"
                    else c["processing_date_balance_cents"])
        c["vested_balance_cents"] = vested_balance(selected, c["vesting_percent"])
        c["force_out_path"] = force_out_path(c["vested_balance_cents"], plan)
        if c["force_out_path"] == "INELIGIBLE_REMAINS":
            c["case_status"] = "SETTLED"
            c["executed_path"] = "REMAIN_IN_PLAN"
        # Batch-lock finalization does not advance the case OCC version.
    batch["locked_at"] = now()
    batch["batch_status"] = "LOCKED"
    touch(batch)
    return success(ser_batch(batch))


@app.post("/distribution-batches/<bid>/execute")
def execute_batch(bid):
    uid, _ = require_roles("ProviderOps")
    batch = get_or_404(DB.batches, bid, "DistributionBatch")
    if batch["batch_status"] != "LOCKED":
        raise err_409(f"Batch in {batch['batch_status']} cannot be executed")
    batch_cases = cases_of_batch(bid)
    for c in batch_cases:
        if c["case_status"] == "IDENTIFIED":
            raise err_422("ERR_CASE_NOTICE_OUTSTANDING",
                          "A case is still IDENTIFIED; its force-out notice was never delivered")
    for c in batch_cases:
        if c["case_status"] == "NOTIFIED":
            n = current_notice(c)
            if n is not None and n["response_deadline"] is not None and n["response_deadline"] >= now():
                raise err_422("ERR_CASE_WINDOW_STILL_OPEN",
                              "A NOTIFIED case's election window has not yet closed")
    batch["batch_status"] = "EXECUTED"
    batch["executed_by_user_id"] = uid
    batch["executed_at"] = now()
    touch(batch)
    return success(ser_batch(batch))


@app.post("/distribution-batches/<bid>/reconcile")
def reconcile_batch(bid):
    require_roles("ProviderOps")
    batch = get_or_404(DB.batches, bid, "DistributionBatch")
    if batch["batch_status"] != "EXECUTED":
        raise err_409(f"Batch in {batch['batch_status']} cannot be reconciled")
    case_count, settled, _total = batch_counters(batch)
    if case_count >= 1 and case_count == settled:
        batch["batch_status"] = "RECONCILED"
        batch["reconciled_at"] = now()
    else:
        batch["batch_status"] = "RECON_EXCEPTION"
    touch(batch)
    return success(ser_batch(batch))


@app.post("/distribution-batches/<bid>/resume")
def resume_batch(bid):
    require_roles("ProviderOps")
    batch = get_or_404(DB.batches, bid, "DistributionBatch")
    if batch["batch_status"] != "RECON_EXCEPTION":
        raise err_409(f"Batch in {batch['batch_status']} cannot be resumed")
    batch["batch_status"] = "EXECUTED"
    touch(batch)
    return success(ser_batch(batch))


# ===========================================================================
# Distribution cases
# ===========================================================================
@app.post("/distribution-cases")
def create_case():
    require_roles("PlanSponsor")
    b = get_body()
    batch_id = v_req_str(b, "distribution_batch_id")
    plan_id = v_req_str(b, "plan_id")
    participant_id = v_req_str(b, "participant_id")
    separation_date = v_req_dt(b, "separation_date")
    sep_balance = v_req_int(b, "separation_date_balance_cents", minv=0)
    proc_balance = v_req_int(b, "processing_date_balance_cents", minv=0)
    vesting = v_opt_int(b, "vesting_percent", 100, minv=0, maxv=100)
    # FK existence, left to right (PRD §2.10).
    batch = get_or_404(DB.batches, batch_id, "DistributionBatch")
    plan = get_or_404(DB.plans, plan_id, "Plan")
    get_or_404(DB.participants, participant_id, "Participant")
    if plan_id != batch["plan_id"]:
        raise err_400("plan_id must equal the batch's plan_id")
    if batch["batch_status"] != "OPEN":
        raise err_409("Cases may only attach to an OPEN batch")
    if plan["plan_status"] != "ACTIVE":
        raise err_422("ERR_PLAN_NOT_ACTIVE", "Plan is TERMINATED; case creation is blocked")
    case = stamp_new({
        "distribution_batch_id": batch_id,
        "plan_id": plan_id,
        "participant_id": participant_id,
        "separation_date": separation_date,
        "separation_date_balance_cents": sep_balance,
        "processing_date_balance_cents": proc_balance,
        "vesting_percent": vesting,
        "quoted_balance_cents": vested_balance(sep_balance, vesting),
        "vested_balance_cents": None,
        "force_out_path": None,
        "case_status": "IDENTIFIED",
        "executed_path": None,
        "current_notice_id": None,
    })
    DB.cases[case["id"]] = case
    return success(ser_case(case), "object", 201)


@app.get("/distribution-cases")
def list_cases():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.cases.values(), ser_case,
        ["distribution_batch_id", "plan_id", "participant_id", "case_status"],
    )


@app.get("/distribution-cases/<cid>")
def get_case(cid):
    require_roles(*ALL_ROLES)
    return success(ser_case(get_or_404(DB.cases, cid, "DistributionCase")))


@app.post("/distribution-cases/<cid>/cancel")
def cancel_case(cid):
    require_roles("PlanSponsor")
    case = get_or_404(DB.cases, cid, "DistributionCase")
    if case["case_status"] not in ("IDENTIFIED", "NOTIFIED"):
        raise err_409(f"Case in {case['case_status']} cannot be cancelled")
    case["case_status"] = "CANCELLED"
    touch(case)
    return success(ser_case(case))


@app.post("/distribution-cases/<cid>/settle-direct-rollover")
def settle_direct_rollover(cid):
    require_roles("ProviderOps")
    case = get_or_404(DB.cases, cid, "DistributionCase")
    election = submitted_election(cid)
    if (case["case_status"] != "ELECTED" or election is None
            or election["election_type"] != "DIRECT_ROLLOVER_NEW_PLAN"):
        raise err_409("Case must be ELECTED with a SUBMITTED DIRECT_ROLLOVER_NEW_PLAN election")
    batch = DB.batches[case["distribution_batch_id"]]
    if batch["batch_status"] not in ("EXECUTED", "RECON_EXCEPTION"):
        raise err_409("Batch must be EXECUTED or RECON_EXCEPTION to settle a case")
    dest = DB.plans.get(election["destination_plan_id"])
    if dest is None or not dest["network_reachable"]:
        raise err_422("ERR_DESTINATION_PLAN_NOT_ACCEPTING",
                      "Destination plan is not network-reachable")
    case["case_status"] = "SETTLED"
    case["executed_path"] = "DIRECT_NEW_PLAN"
    touch(case)
    election["election_status"] = "EXECUTED"
    touch(election)
    return success(ser_case(case))


# ===========================================================================
# Notices
# ===========================================================================
NOTICE_TYPES = ("FORCE_OUT_ELECTION", "FEE_DISCLOSURE", "AUTO_PORTABILITY_PRENOTICE", "ESCHEAT_WARNING")


@app.post("/distribution-cases/<cid>/notices")
def create_notice(cid):
    require_roles("ProviderOps")
    b = get_body()
    notice_type = v_req_enum(b, "notice_type", NOTICE_TYPES)
    case = get_or_404(DB.cases, cid, "DistributionCase")
    if notice_type == "FORCE_OUT_ELECTION":
        batch = DB.batches[case["distribution_batch_id"]]
        if case["case_status"] != "IDENTIFIED" or batch["batch_status"] != "LOCKED":
            raise err_409("FORCE_OUT_ELECTION requires the case IDENTIFIED and its batch LOCKED")
    elif notice_type == "FEE_DISCLOSURE":
        if case["case_status"] not in ("NOTIFIED", "ELECTED", "WINDOW_EXPIRED", "EXECUTED", "SETTLED"):
            raise err_409("FEE_DISCLOSURE requires the case in NOTIFIED, ELECTED, WINDOW_EXPIRED, EXECUTED or SETTLED")
    elif notice_type == "AUTO_PORTABILITY_PRENOTICE":
        if not (case["case_status"] == "SETTLED" and case["executed_path"] == "SAFE_HARBOR_IRA"):
            raise err_409("AUTO_PORTABILITY_PRENOTICE requires a case SETTLED via the safe-harbor IRA path")
    elif notice_type == "ESCHEAT_WARNING":
        # A case in EXECUTED always has an uncashed obligation outstanding
        # (a cashed check would have settled it); voided-but-uncashed checks
        # still count as unclaimed property.
        ira = ira_of_case(cid)
        if not (case["case_status"] == "EXECUTED"
                or (ira is not None and ira["ira_status"] == "OPEN")):
            raise err_409("ESCHEAT_WARNING requires a case EXECUTED with an uncashed check or an OPEN IRA")
    notice = stamp_new({
        "distribution_case_id": cid,
        "notice_type": notice_type,
        "delivery_status": "SENT",
        "sent_at": now(),
        "delivered_at": None,
        "response_deadline": None,
    })
    DB.notices[notice["id"]] = notice
    return success(ser_notice(notice), "object", 201)


@app.get("/notices")
def list_notices():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.notices.values(), ser_notice,
        ["distribution_case_id", "notice_type", "delivery_status"],
    )


@app.get("/notices/<nid>")
def get_notice(nid):
    require_roles(*ALL_ROLES)
    return success(ser_notice(get_or_404(DB.notices, nid, "Notice")))


@app.post("/notices/<nid>/record-delivery")
def record_delivery(nid):
    require_roles("ProviderOps")
    b = get_body()
    outcome = v_req_enum(b, "outcome", ("DELIVERED", "BOUNCED", "RETURNED_MAIL"))
    notice = get_or_404(DB.notices, nid, "Notice")
    if outcome == "DELIVERED":
        if notice["delivery_status"] != "SENT":
            raise err_409(f"Notice in {notice['delivery_status']} cannot be recorded DELIVERED")
        notice["delivery_status"] = "DELIVERED"
        notice["delivered_at"] = now()
        notice["response_deadline"] = now() + timedelta(days=NOTICE_WINDOW_DAYS)
        case = DB.cases.get(notice["distribution_case_id"])
        if (case is not None and notice["notice_type"] == "FORCE_OUT_ELECTION"
                and case["case_status"] == "IDENTIFIED"):
            case["case_status"] = "NOTIFIED"
            case["current_notice_id"] = notice["id"]
            touch(case)
    elif outcome == "BOUNCED":
        if notice["delivery_status"] != "SENT":
            raise err_409(f"Notice in {notice['delivery_status']} cannot be recorded BOUNCED")
        notice["delivery_status"] = "BOUNCED"
        case = DB.cases.get(notice["distribution_case_id"])
        if case is not None:
            participant = DB.participants.get(case["participant_id"])
            if participant is not None:
                mark_bad_address(participant)
    else:  # RETURNED_MAIL
        if notice["delivery_status"] not in ("SENT", "DELIVERED"):
            raise err_409(f"Notice in {notice['delivery_status']} cannot be recorded RETURNED_MAIL")
        notice["delivery_status"] = "RETURNED_MAIL"
        case = DB.cases.get(notice["distribution_case_id"])
        if case is not None:
            participant = DB.participants.get(case["participant_id"])
            if participant is not None:
                mark_bad_address(participant)
            if case["current_notice_id"] == notice["id"] and case["case_status"] == "NOTIFIED":
                case["case_status"] = "IDENTIFIED"
                case["current_notice_id"] = None
                touch(case)
    touch(notice)
    return success(ser_notice(notice))


# ===========================================================================
# Elections
# ===========================================================================
ELECTION_TYPES = ("LUMP_SUM_CASH", "SAFE_HARBOR_IRA", "DIRECT_ROLLOVER_NEW_PLAN")


@app.post("/distribution-cases/<cid>/elections")
def submit_election(cid):
    uid, _ = require_roles("Participant")
    case = get_or_404(DB.cases, cid, "DistributionCase")
    if uid != case["participant_id"]:
        raise ApiError("ERR_PARTICIPANT_OWNERSHIP_MISMATCH", 403,
                       "A Participant may only elect on their own case")
    b = get_body()
    election_type = v_req_enum(b, "election_type", ELECTION_TYPES)
    expected = v_req_version(b, "expected_case_version")
    dest = b.get("destination_plan_id", None)
    if election_type == "DIRECT_ROLLOVER_NEW_PLAN":
        if dest is None or not isinstance(dest, str):
            raise err_400("destination_plan_id is required for DIRECT_ROLLOVER_NEW_PLAN")
    else:
        if dest is not None:
            raise err_400("destination_plan_id must be null unless election_type is DIRECT_ROLLOVER_NEW_PLAN")
    if dest is not None:
        get_or_404(DB.plans, dest, "Plan")
    if case["case_status"] not in ("NOTIFIED", "ELECTED"):
        raise err_409(f"Case in {case['case_status']} cannot accept an election")
    n = current_notice(case)
    if n is None or n["response_deadline"] is None or now() > n["response_deadline"]:
        raise err_422("ERR_ELECTION_WINDOW_CLOSED",
                      "The election window of the case's current notice has closed")
    if expected != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_case_version does not match the case's current version")
    prior = submitted_election(cid)
    if prior is not None:
        prior["election_status"] = "SUPERSEDED"
        touch(prior)
    election = stamp_new({
        "distribution_case_id": cid,
        "participant_id": case["participant_id"],
        "election_type": election_type,
        "destination_plan_id": dest,
        "election_status": "SUBMITTED",
        "submitted_at": now(),
    })
    DB.elections[election["id"]] = election
    case["case_status"] = "ELECTED"
    touch(case)
    return success(ser_election(election), "object", 201)


@app.get("/elections")
def list_elections():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.elections.values(), ser_election,
        ["distribution_case_id", "participant_id", "destination_plan_id", "election_status"],
    )


@app.get("/elections/<eid>")
def get_election(eid):
    require_roles(*ALL_ROLES)
    return success(ser_election(get_or_404(DB.elections, eid, "Election")))


@app.post("/elections/<eid>/void")
def void_election(eid):
    uid, _ = require_roles("Participant")
    election = get_or_404(DB.elections, eid, "Election")
    if uid != election["participant_id"]:
        raise ApiError("ERR_PARTICIPANT_OWNERSHIP_MISMATCH", 403,
                       "A Participant may only void their own election")
    if election["election_status"] != "SUBMITTED":
        raise err_409(f"Election in {election['election_status']} cannot be voided")
    case = DB.cases[election["distribution_case_id"]]
    n = current_notice(case)
    if n is None or n["response_deadline"] is None or now() > n["response_deadline"]:
        raise err_422("ERR_ELECTION_WINDOW_CLOSED",
                      "The election window of the case's current notice has closed")
    election["election_status"] = "VOIDED"
    touch(election)
    if submitted_election(case["id"]) is None and case["case_status"] == "ELECTED":
        case["case_status"] = "NOTIFIED"
        touch(case)
    return success(ser_election(election))


# ===========================================================================
# Safe harbor IRAs
# ===========================================================================
DAY_COUNT_CONVENTIONS = ("ACTUAL_365", "THIRTY_360")


@app.post("/safe-harbor-iras")
def create_ira():
    require_roles("ProviderOps")
    b = get_body()
    case_id = v_req_str(b, "distribution_case_id")
    convention = v_req_enum(b, "fee_day_count_convention", DAY_COUNT_CONVENTIONS) \
        if "fee_day_count_convention" in b else "ACTUAL_365"
    case = get_or_404(DB.cases, case_id, "DistributionCase")
    election = submitted_election(case_id)
    elected_ira = (case["case_status"] == "ELECTED" and election is not None
                   and election["election_type"] == "SAFE_HARBOR_IRA")
    window_expired = case["case_status"] == "WINDOW_EXPIRED"
    if not (elected_ira or window_expired):
        raise err_409("Case must be ELECTED with a SUBMITTED SAFE_HARBOR_IRA election, or WINDOW_EXPIRED")
    batch = DB.batches[case["distribution_batch_id"]]
    if batch["batch_status"] not in ("EXECUTED", "RECON_EXCEPTION"):
        raise err_409("Batch must be EXECUTED or RECON_EXCEPTION to establish an IRA")
    if window_expired and case["force_out_path"] != "SAFE_HARBOR_IRA":
        raise err_422("ERR_CASE_BALANCE_INELIGIBLE",
                      "Window-expired case's force-out path is not SAFE_HARBOR_IRA")
    ira = stamp_new({
        "distribution_case_id": case_id,
        "participant_id": case["participant_id"],
        "ira_origin": "ELECTED" if elected_ira else "AUTO_FORCE_OUT",
        "ira_status": "OPEN",
        "funded_amount_cents": case["vested_balance_cents"],
        "balance_cents": case["vested_balance_cents"],
        "in_flight_cents": 0,
        "total_fees_cents": 0,
        "total_transferred_out_cents": 0,
        "fee_day_count_convention": convention,
        "default_investment": "MONEY_MARKET_FDIC_INSURED",
        "last_fee_assessed_at": None,
        "last_activity_at": now(),
        "opened_at": now(),
    })
    DB.iras[ira["id"]] = ira
    case["case_status"] = "SETTLED"
    case["executed_path"] = "SAFE_HARBOR_IRA"
    touch(case)
    if election is not None:
        election["election_status"] = "EXECUTED"
        touch(election)
    return success(ser_ira(ira), "object", 201)


@app.get("/safe-harbor-iras")
def list_iras():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.iras.values(), ser_ira,
        ["distribution_case_id", "participant_id", "ira_status"],
    )


@app.get("/safe-harbor-iras/<iid>")
def get_ira(iid):
    require_roles(*ALL_ROLES)
    return success(ser_ira(get_or_404(DB.iras, iid, "SafeHarborIRA")))


@app.post("/safe-harbor-iras/<iid>/close")
def close_ira(iid):
    uid, role = require_roles("Participant", "ProviderOps")
    ira = get_or_404(DB.iras, iid, "SafeHarborIRA")
    if role == "Participant" and uid != ira["participant_id"]:
        raise ApiError("ERR_PARTICIPANT_OWNERSHIP_MISMATCH", 403,
                       "A Participant may only close their own IRA")
    if ira["ira_status"] not in ("OPEN", "MATCHED"):
        raise err_409(f"IRA in {ira['ira_status']} cannot be closed")
    if ira["ira_status"] == "MATCHED":
        m = confirmed_match_of_ira(iid)
        if m is not None:
            m["match_status"] = "EXPIRED"
            touch(m)
    # Pay the entire remaining balance by check: no withholding on IRA_CLOSE.
    gross = ira["balance_cents"]
    check = stamp_new({
        "distribution_case_id": ira["distribution_case_id"],
        "supersedes_check_id": None,
        "origin": "IRA_CLOSE",
        "gross_amount_cents": gross,
        "fed_withholding_cents": 0,
        "state_withholding_cents": 0,
        "amount_cents": gross,
        "check_status": "ISSUED",
        "issued_at": now(),
        "stale_after": now() + timedelta(days=CHECK_STALE_DAYS),
        "cashed_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    DB.checks[check["id"]] = check
    ira["balance_cents"] = 0
    ira["ira_status"] = "CLOSED_BY_PARTICIPANT"
    ira["last_activity_at"] = now()
    touch(ira)
    return success(ser_ira(ira))


@app.post("/safe-harbor-iras/<iid>/assess-fee")
def assess_fee(iid):
    require_roles("ProviderOps")
    get_body()
    ira = get_or_404(DB.iras, iid, "SafeHarborIRA")
    if ira["ira_status"] not in ("OPEN", "MATCHED"):
        raise err_409(f"IRA in {ira['ira_status']} cannot be assessed a fee")
    if delivered_notice(ira["distribution_case_id"], "FEE_DISCLOSURE") is None:
        raise err_422("ERR_FEE_DISCLOSURE_NOT_DELIVERED",
                      "A FEE_DISCLOSURE notice for the case must be DELIVERED before the first fee assessment")
    current = now()
    for f in DB.fees.values():
        pe = f["period_end"]
        if (f["safe_harbor_ira_id"] == iid
                and pe.year == current.year and pe.month == current.month):
            raise ApiError("ERR_DUPLICATE_FEE_PERIOD", 409,
                           "An assessment with period_end in the current UTC month already exists for this IRA")
    fee, anchor, days = accrued_fee(ira, current)
    amount = min(fee, ira["balance_cents"])
    entry = stamp_new({
        "safe_harbor_ira_id": iid,
        "period_start": anchor,
        "period_end": current,
        "days_in_period": days,
        "day_count_convention": ira["fee_day_count_convention"],
        "amount_cents": amount,
    }, common=False)
    DB.fees[entry["id"]] = entry
    ira["balance_cents"] -= amount
    ira["total_fees_cents"] += amount
    ira["last_fee_assessed_at"] = current
    ira["last_activity_at"] = current
    touch(ira)
    return success(ser_fee(entry), "object", 201)


# ===========================================================================
# Fee assessments (append-only ledger)
# ===========================================================================
@app.get("/fee-assessments")
def list_fees():
    require_roles(*ALL_ROLES)
    return list_response(DB.fees.values(), ser_fee, ["safe_harbor_ira_id"])


@app.get("/fee-assessments/<fid>")
def get_fee(fid):
    require_roles(*ALL_ROLES)
    return success(ser_fee(get_or_404(DB.fees, fid, "IRAFeeAssessment")))


# ===========================================================================
# Checks
# ===========================================================================
@app.post("/checks")
def create_check():
    require_roles("ProviderOps")
    b = get_body()
    case_id = v_req_str(b, "distribution_case_id")
    case = get_or_404(DB.cases, case_id, "DistributionCase")
    election = submitted_election(case_id)
    elected_cash = (case["case_status"] == "ELECTED" and election is not None
                    and election["election_type"] == "LUMP_SUM_CASH")
    window_expired = case["case_status"] == "WINDOW_EXPIRED"
    if not (elected_cash or window_expired):
        raise err_409("Case must be ELECTED with a SUBMITTED LUMP_SUM_CASH election, or WINDOW_EXPIRED")
    batch = DB.batches[case["distribution_batch_id"]]
    if batch["batch_status"] not in ("EXECUTED", "RECON_EXCEPTION"):
        raise err_409("Batch must be EXECUTED or RECON_EXCEPTION to issue a check")
    if window_expired and case["force_out_path"] != "CASH_OUT":
        raise err_422("ERR_CASE_BALANCE_INELIGIBLE",
                      "Window-expired case's force-out path is not CASH_OUT")
    plan = DB.plans[case["plan_id"]]
    gross = case["vested_balance_cents"]
    fed, state_wh, net = net_check_withholding(gross, plan["state_withholding_rate"])
    check = stamp_new({
        "distribution_case_id": case_id,
        "supersedes_check_id": None,
        "origin": "CASE_CASH_OUT",
        "gross_amount_cents": gross,
        "fed_withholding_cents": fed,
        "state_withholding_cents": state_wh,
        "amount_cents": net,
        "check_status": "ISSUED",
        "issued_at": now(),
        "stale_after": now() + timedelta(days=CHECK_STALE_DAYS),
        "cashed_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    DB.checks[check["id"]] = check
    case["case_status"] = "EXECUTED"
    case["executed_path"] = "CHECK_CASH_OUT"
    touch(case)
    if election is not None:
        election["election_status"] = "EXECUTED"
        touch(election)
    return success(ser_check(check), "object", 201)


@app.get("/checks")
def list_checks():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.checks.values(), ser_check,
        ["distribution_case_id", "check_status", "supersedes_check_id", "origin"],
    )


@app.get("/checks/<chid>")
def get_check(chid):
    require_roles(*ALL_ROLES)
    return success(ser_check(get_or_404(DB.checks, chid, "Check")))


@app.post("/checks/<chid>/record-cashed")
def record_cashed(chid):
    require_roles("ProviderOps")
    get_body()
    check = get_or_404(DB.checks, chid, "Check")
    if check["check_status"] != "ISSUED":
        raise err_409(f"Check in {check['check_status']} cannot be recorded cashed")
    if now() > check["stale_after"]:
        raise err_422("ERR_CHECK_STALE", "The check is past its stale_after instant")
    check["check_status"] = "CASHED"
    check["cashed_at"] = now()
    touch(check)
    if check["origin"] == "CASE_CASH_OUT":
        case = DB.cases.get(check["distribution_case_id"])
        if case is not None and case["case_status"] == "EXECUTED":
            case["case_status"] = "SETTLED"
            touch(case)
    return success(ser_check(check))


VOID_REASONS = ("DAMAGED", "STALE", "ESCHEATMENT")


@app.post("/checks/<chid>/void")
def void_check(chid):
    require_roles("ProviderOps")
    b = get_body()
    reason = v_req_enum(b, "void_reason", VOID_REASONS)
    check = get_or_404(DB.checks, chid, "Check")
    if check["check_status"] not in ("ISSUED", "STALE_DATED"):
        raise err_409(f"Check in {check['check_status']} cannot be voided")
    if reason == "ESCHEATMENT":
        if check["check_status"] != "STALE_DATED":
            raise err_422("ERR_ESCHEAT_WARNING_REQUIRED",
                          "Escheatment void requires a STALE_DATED check")
        if not escheat_warning_matured(check["distribution_case_id"], now()):
            raise err_422("ERR_ESCHEAT_WARNING_REQUIRED",
                          "An ESCHEAT_WARNING notice for the case must have been delivered at least 90 days earlier")
    check["check_status"] = "VOIDED"
    check["voided_at"] = now()
    check["void_reason"] = reason
    touch(check)
    if reason == "ESCHEATMENT" and check["origin"] == "CASE_CASH_OUT":
        case = DB.cases.get(check["distribution_case_id"])
        if case is not None and case["case_status"] == "EXECUTED":
            case["case_status"] = "ESCHEATED"
            touch(case)
    return success(ser_check(check))


@app.post("/checks/<chid>/reissue")
def reissue_check(chid):
    require_roles("ProviderOps")
    get_body()
    check = get_or_404(DB.checks, chid, "Check")
    if check["check_status"] != "VOIDED" or check["void_reason"] == "ESCHEATMENT":
        raise err_409("Only a VOIDED (non-escheatment) check can be reissued")
    case = DB.cases.get(check["distribution_case_id"])
    if case is None or case["case_status"] != "EXECUTED":
        raise err_409("The underlying case must still be EXECUTED to reissue its check")
    participant = DB.participants.get(case["participant_id"])
    if participant is not None and participant["address_quality"] == "BAD_ADDRESS":
        raise err_422("ERR_UNDELIVERABLE_ADDRESS",
                      "Participant address is BAD_ADDRESS; repair it before reissue")
    successor = stamp_new({
        "distribution_case_id": check["distribution_case_id"],
        "supersedes_check_id": check["id"],
        "origin": check["origin"],
        "gross_amount_cents": check["gross_amount_cents"],
        "fed_withholding_cents": check["fed_withholding_cents"],
        "state_withholding_cents": check["state_withholding_cents"],
        "amount_cents": check["amount_cents"],
        "check_status": "ISSUED",
        "issued_at": now(),
        "stale_after": now() + timedelta(days=CHECK_STALE_DAYS),
        "cashed_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    DB.checks[successor["id"]] = successor
    return success(ser_check(successor), "object", 201)


# ===========================================================================
# Match candidates (auto-portability network)
# ===========================================================================
def _confirm_match(m):
    """Shared confirm side effects: IRA OPEN -> MATCHED, sibling CANDIDATEs expire."""
    m["match_status"] = "CONFIRMED"
    touch(m)
    ira = DB.iras.get(m["safe_harbor_ira_id"])
    if ira is not None and ira["ira_status"] == "OPEN":
        ira["ira_status"] = "MATCHED"
        touch(ira)
    for other in DB.matches.values():
        if (other["id"] != m["id"] and other["safe_harbor_ira_id"] == m["safe_harbor_ira_id"]
                and other["match_status"] == "CANDIDATE"):
            other["match_status"] = "EXPIRED"
            touch(other)


@app.post("/safe-harbor-iras/<iid>/match-searches")
def match_search(iid):
    require_roles("ProviderOps")
    b = get_body()
    new_plan_id = v_req_str(b, "new_plan_id")
    new_rk_id = v_req_str(b, "new_recordkeeper_id")
    start_date = v_req_date(b, "employment_start_date")
    ssn_exact = v_req_bool(b, "ssn_exact")
    name_sim = v_req_num(b, "name_similarity")
    if name_sim < 0 or name_sim > 1:
        raise err_400("name_similarity must lie in [0, 1]")
    dob_match = v_req_bool(b, "dob_match")
    ira = get_or_404(DB.iras, iid, "SafeHarborIRA")
    if ira["ira_status"] != "OPEN":
        raise err_409(f"IRA in {ira['ira_status']} cannot run a match search")
    case = DB.cases[ira["distribution_case_id"]]
    source_plan = DB.plans[case["plan_id"]]
    if not source_plan["auto_portability_enabled"]:
        raise err_409("The source plan does not have auto_portability_enabled")
    new_plan = get_or_404(DB.plans, new_plan_id, "Plan")
    new_rk = get_or_404(DB.recordkeepers, new_rk_id, "Recordkeeper")
    if new_plan["recordkeeper_id"] != new_rk_id:
        raise err_422("ERR_RECORDKEEPER_PLAN_MISMATCH",
                      "new_plan.recordkeeper_id does not equal new_recordkeeper_id")
    if new_rk["network_status"] != "ACTIVE":
        raise err_422("ERR_RECORDKEEPER_NOT_ACTIVE",
                      "The new plan's recordkeeper is not ACTIVE")
    if not new_plan["network_reachable"]:
        raise err_422("ERR_DESTINATION_PLAN_NOT_ACCEPTING",
                      "The new plan is not network-reachable")
    score = compute_match_score(ssn_exact, name_sim, dob_match)
    if score < REVIEW_FLOOR:
        status = "REJECTED"
    elif score >= AUTO_CONFIRM and ssn_exact:
        status = "CONFIRMED"
    else:
        status = "CANDIDATE"
    m = stamp_new({
        "safe_harbor_ira_id": iid,
        "participant_id": ira["participant_id"],
        "new_plan_id": new_plan_id,
        "new_recordkeeper_id": new_rk_id,
        "employment_start_date": start_date,
        "ssn_exact": ssn_exact,
        "name_similarity": name_sim,
        "dob_match": dob_match,
        "match_score": score,
        "match_status": status,
    })
    DB.matches[m["id"]] = m
    if status == "CONFIRMED":
        # Auto-confirm at creation: the candidate is born CONFIRMED at v1;
        # apply the IRA/sibling side effects without re-versioning the match.
        ira2 = DB.iras.get(m["safe_harbor_ira_id"])
        if ira2 is not None and ira2["ira_status"] == "OPEN":
            ira2["ira_status"] = "MATCHED"
            touch(ira2)
        for other in DB.matches.values():
            if (other["id"] != m["id"] and other["safe_harbor_ira_id"] == m["safe_harbor_ira_id"]
                    and other["match_status"] == "CANDIDATE"):
                other["match_status"] = "EXPIRED"
                touch(other)
    return success(ser_match(m), "object", 201)


@app.get("/match-candidates")
def list_matches():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.matches.values(), ser_match,
        ["safe_harbor_ira_id", "participant_id", "new_plan_id", "new_recordkeeper_id", "match_status"],
    )


@app.get("/match-candidates/<mid>")
def get_match(mid):
    require_roles(*ALL_ROLES)
    return success(ser_match(get_or_404(DB.matches, mid, "MatchCandidate")))


@app.post("/match-candidates/<mid>/confirm")
def confirm_match(mid):
    require_roles("ProviderOps")
    get_body()
    m = get_or_404(DB.matches, mid, "MatchCandidate")
    if m["match_status"] != "CANDIDATE":
        raise err_409(f"Match in {m['match_status']} cannot be confirmed")
    if not m["ssn_exact"]:
        raise err_422("ERR_SSN_GATE_FAILED", "Manual confirm requires an exact SSN match")
    if m["match_score"] < CONFIRM_FLOOR:
        raise err_422("ERR_MATCH_SCORE_BELOW_THRESHOLD",
                      "Manual confirm requires match_score >= 0.650")
    _confirm_match(m)
    return success(ser_match(m))


@app.post("/match-candidates/<mid>/reject")
def reject_match(mid):
    require_roles("ProviderOps")
    get_body()
    m = get_or_404(DB.matches, mid, "MatchCandidate")
    if m["match_status"] != "CANDIDATE":
        raise err_409(f"Match in {m['match_status']} cannot be rejected")
    m["match_status"] = "REJECTED"
    touch(m)
    return success(ser_match(m))


# ===========================================================================
# Transfers
# ===========================================================================
@app.post("/safe-harbor-iras/<iid>/transfers")
def create_transfer(iid):
    require_roles("ProviderOps")
    b = get_body()
    expected = v_req_version(b, "expected_ira_version")
    match_id = b.get("match_candidate_id", None)
    if match_id is not None and not isinstance(match_id, str):
        raise err_400("match_candidate_id must be a string or null")
    ira = get_or_404(DB.iras, iid, "SafeHarborIRA")
    match = None
    if match_id is not None:
        match = get_or_404(DB.matches, match_id, "MatchCandidate")
    if ira["ira_status"] != "MATCHED":
        raise err_409(f"IRA in {ira['ira_status']} cannot initiate a transfer")
    if match is None:
        match = confirmed_match_of_ira(iid)
        if match is None:
            raise err_409("IRA has no CONFIRMED match to transfer against")
    elif match["safe_harbor_ira_id"] != iid or match["match_status"] != "CONFIRMED":
        raise err_409("match_candidate_id must name the IRA's unique CONFIRMED match")
    prenotice = delivered_notice(ira["distribution_case_id"], "AUTO_PORTABILITY_PRENOTICE")
    if prenotice is None:
        raise err_422("ERR_PRENOTICE_NOT_DELIVERED",
                      "An AUTO_PORTABILITY_PRENOTICE notice for the case must be DELIVERED before any transfer")
    if prenotice["response_deadline"] is None or prenotice["response_deadline"] >= now():
        raise err_422("ERR_PRENOTICE_WINDOW_OPEN",
                      "The prenotice opt-out window must have elapsed before a transfer")
    rk = DB.recordkeepers.get(match["new_recordkeeper_id"])
    if rk is None or rk["network_status"] != "ACTIVE":
        raise err_422("ERR_RECORDKEEPER_NOT_ACTIVE",
                      "The match's recordkeeper is not ACTIVE")
    if expected != ira["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_ira_version does not match the IRA's current version")
    # transfer_available_amount — pinned evaluation order: snapshot first,
    # then the uncapped accrual on the snapshot, then subtract.
    snapshot = ira["balance_cents"]
    accrued, _anchor, _days = accrued_fee(ira, now())
    amount = snapshot - accrued
    if amount <= 0:
        raise err_422("ERR_INSUFFICIENT_IRA_BALANCE",
                      "Transferable amount is not positive after the accrued-fee offset")
    transfer = stamp_new({
        "safe_harbor_ira_id": iid,
        "match_candidate_id": match["id"],
        "amount_cents": amount,
        "accrued_fee_offset_cents": accrued,
        "transfer_status": "SENT",
        "sent_at": now(),
        "settled_at": None,
        "rejection_reason": None,
    })
    DB.transfers[transfer["id"]] = transfer
    match["match_status"] = "EXECUTED"
    touch(match)
    ira["ira_status"] = "TRANSFER_PENDING"
    ira["balance_cents"] -= amount
    ira["in_flight_cents"] += amount
    ira["last_activity_at"] = now()
    touch(ira)
    return success(ser_transfer(transfer), "object", 201)


@app.get("/transfers")
def list_transfers():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.transfers.values(), ser_transfer,
        ["safe_harbor_ira_id", "match_candidate_id", "transfer_status"],
    )


@app.get("/transfers/<tid>")
def get_transfer(tid):
    require_roles(*ALL_ROLES)
    return success(ser_transfer(get_or_404(DB.transfers, tid, "Transfer")))


@app.post("/transfers/<tid>/record-response")
def record_transfer_response(tid):
    require_roles("ProviderOps")
    b = get_body()
    outcome = v_req_enum(b, "outcome", ("ACCEPTED", "REJECTED"))
    reason = b.get("rejection_reason", None)
    if outcome == "REJECTED" and (not isinstance(reason, str) or reason == ""):
        raise err_400("rejection_reason is required and must be non-empty when outcome is REJECTED")
    transfer = get_or_404(DB.transfers, tid, "Transfer")
    if transfer["transfer_status"] != "SENT":
        raise err_409(f"Transfer in {transfer['transfer_status']} cannot record a response")
    ira = DB.iras[transfer["safe_harbor_ira_id"]]
    amount = transfer["amount_cents"]
    if outcome == "ACCEPTED":
        transfer["transfer_status"] = "RECONCILED"
        transfer["settled_at"] = now()
        ira["in_flight_cents"] -= amount
        ira["total_transferred_out_cents"] += amount
        ira["last_activity_at"] = now()
        if ira["ira_status"] == "TRANSFER_PENDING":
            ira["ira_status"] = "TRANSFERRED_OUT"
        touch(ira)
    else:
        transfer["transfer_status"] = "RETURNED"
        transfer["settled_at"] = now()
        transfer["rejection_reason"] = reason
        ira["in_flight_cents"] -= amount
        ira["balance_cents"] += amount
        ira["last_activity_at"] = now()
        if ira["ira_status"] == "TRANSFER_PENDING":
            ira["ira_status"] = "OPEN"
        touch(ira)
        match = DB.matches.get(transfer["match_candidate_id"])
        if match is not None and match["match_status"] == "EXECUTED":
            match["match_status"] = "REJECTED"
            touch(match)
    touch(transfer)
    return success(ser_transfer(transfer))


# ===========================================================================
# Fiduciary reviews
# ===========================================================================
@app.post("/fiduciary-reviews")
def create_review():
    uid, _ = require_roles("FiduciaryReviewer")
    b = get_body()
    batch_id = v_req_str(b, "distribution_batch_id")
    period_start = v_req_dt(b, "period_start")
    period_end = v_req_dt(b, "period_end")
    batch = get_or_404(DB.batches, batch_id, "DistributionBatch")
    if batch["batch_status"] != "RECONCILED":
        raise err_409("Fiduciary review requires a RECONCILED batch")
    if uid == batch["executed_by_user_id"]:
        raise err_422("ERR_SEGREGATION_OF_DUTIES",
                      "The reviewer must not be the operator who executed the batch")
    if not period_start < period_end:
        raise err_422("ERR_REVIEW_PERIOD_INVALID", "period_start must be before period_end")
    for r in DB.reviews.values():
        if (r["plan_id"] == batch["plan_id"] and r["review_status"] != "CLOSED"
                and r["period_start"] < period_end and period_start < r["period_end"]):
            raise ApiError("ERR_REVIEW_PERIOD_OVERLAP", 409,
                           "Review period intersects an existing non-CLOSED review for the same plan")
    review = stamp_new({
        "distribution_batch_id": batch_id,
        "plan_id": batch["plan_id"],
        "period_start": period_start,
        "period_end": period_end,
        "reviewer_user_id": uid,
        "review_status": "OPEN",
        "findings_count": 0,
        "attested_at": None,
    })
    DB.reviews[review["id"]] = review
    return success(ser_review(review), "object", 201)


@app.get("/fiduciary-reviews")
def list_reviews():
    require_roles(*ALL_ROLES)
    return list_response(
        DB.reviews.values(), ser_review,
        ["distribution_batch_id", "plan_id", "review_status"],
    )


@app.get("/fiduciary-reviews/<rid>")
def get_review(rid):
    require_roles(*ALL_ROLES)
    return success(ser_review(get_or_404(DB.reviews, rid, "FiduciaryReview")))


def _load_own_review(rid, uid):
    review = get_or_404(DB.reviews, rid, "FiduciaryReview")
    if uid != review["reviewer_user_id"]:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Review actions require the named reviewer's X-User-ID")
    return review


@app.post("/fiduciary-reviews/<rid>/record-finding")
def record_finding(rid):
    uid, _ = require_roles("FiduciaryReviewer")
    get_body()
    review = _load_own_review(rid, uid)
    if review["review_status"] not in ("OPEN", "REMEDIATION_OPEN"):
        raise err_409(f"Review in {review['review_status']} cannot record findings")
    review["findings_count"] += 1
    review["review_status"] = "REMEDIATION_OPEN"
    touch(review)
    return success(ser_review(review))


@app.post("/fiduciary-reviews/<rid>/verify-remediation")
def verify_remediation(rid):
    uid, _ = require_roles("FiduciaryReviewer")
    get_body()
    review = _load_own_review(rid, uid)
    if review["review_status"] != "REMEDIATION_OPEN":
        raise err_409(f"Review in {review['review_status']} cannot verify remediation")
    review["review_status"] = "OPEN"
    touch(review)
    return success(ser_review(review))


@app.post("/fiduciary-reviews/<rid>/attest")
def attest_review(rid):
    uid, _ = require_roles("FiduciaryReviewer")
    get_body()
    review = _load_own_review(rid, uid)
    if review["review_status"] != "OPEN":
        raise err_409("Attestation requires the review OPEN with no unremediated findings")
    review["review_status"] = "CLOSED"
    review["attested_at"] = now()
    touch(review)
    batch = DB.batches.get(review["distribution_batch_id"])
    if batch is not None and batch["batch_status"] == "RECONCILED":
        batch["batch_status"] = "REVIEWED"
        touch(batch)
    return success(ser_review(review))


# ===========================================================================
# System / operations: sweep + logical clock
# ===========================================================================
@app.post("/sweeps/run")
def run_sweep():
    require_roles("ProviderOps")
    get_body()
    current = now()
    cases_window_expired = 0
    checks_staled = 0
    matches_expired = 0
    iras_escheated = 0
    for c in DB.cases.values():
        if c["case_status"] == "NOTIFIED":
            n = current_notice(c)
            if (n is not None and n["response_deadline"] is not None
                    and current > n["response_deadline"]
                    and submitted_election(c["id"]) is None):
                c["case_status"] = "WINDOW_EXPIRED"
                touch(c)
                cases_window_expired += 1
    for ch in DB.checks.values():
        if ch["check_status"] == "ISSUED" and current > ch["stale_after"]:
            ch["check_status"] = "STALE_DATED"
            touch(ch)
            checks_staled += 1
    for m in DB.matches.values():
        if (m["match_status"] == "CANDIDATE"
                and current - m["created_at"] > timedelta(days=MATCH_EXPIRY_DAYS)):
            m["match_status"] = "EXPIRED"
            touch(m)
            matches_expired += 1
    for ira in DB.iras.values():
        if (ira["ira_status"] == "OPEN"
                and current - ira["last_activity_at"] > timedelta(days=ESCHEAT_DORMANCY_DAYS)
                and escheat_warning_matured(ira["distribution_case_id"], current)):
            ira["ira_status"] = "ESCHEATED"
            ira["balance_cents"] = 0
            ira["last_activity_at"] = current
            touch(ira)
            iras_escheated += 1
    return success({
        "cases_window_expired": cases_window_expired,
        "checks_staled": checks_staled,
        "matches_expired": matches_expired,
        "iras_escheated": iras_escheated,
    })


@app.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("ProviderOps")
    b = get_body()
    target = v_req_dt(b, "to_iso8601")
    set_clock(target)
    return success({"current_utc": fmt_dt(target)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
