"""Projects, milestones, staged funding draws and dispute cases."""
from datetime import timedelta

from flask import Blueprint

import calc
import ops
import serialize as ser
import validate as v
from errors import fail
from response import created, listing, ok
from store import db
from util import fmt_date, midnight, parse_date

bp = Blueprint("project", __name__)

ALL_READ_ROLES = ("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                  "ServicingAgent", "Merchant", "Consumer")
OPERATOR_READ_ROLES = ("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                       "ServicingAgent", "Merchant")


def project_consumer_id(project):
    """A consumer's book reaches a project through its originating application."""
    app = db.applications.get(project["application_id"])
    if app is not None:
        return app["consumer_id"]
    acct = db.loan_accounts.get(project["loan_account_id"])
    return acct["consumer_id"] if acct else None


def merchant_trade_rule(merchant_id):
    merchant = db.merchants.get(merchant_id)
    return calc.trade_rule_for(merchant["trade_type"]) if merchant else None


# =============================================================================
# Projects (PRD 3.6)
# =============================================================================
@bp.post("/projects")
def create_project():
    ctx = v.authorize(("Merchant",))
    body = v.read_body(ctx)
    application_id = v.req_str(body, "application_id")
    scope_description = v.req_str(body, "scope_description")
    contract_amount = v.req_money(body, "contract_amount_cents", positive=True)
    app = v.get_application(application_id)
    v.resolve_identity(ctx, ("Merchant",))
    v.merchant_scope(ctx, app["merchant_id"])
    # Band 16 — a project may only be opened against an activated offer.
    if app["decision"] != "ACTIVATED":
        fail("ERR_INVALID_APPLICATION_STATE",
             "Only an activated application may open a project.")
    # Band 39
    for existing in db.ordered(db.projects):
        if existing["application_id"] == application_id:
            fail("ERR_PROJECT_ALREADY_EXISTS",
                 "Application %s already has a project." % application_id)
    acct = None
    for candidate in db.ordered(db.loan_accounts):
        if candidate["application_id"] == application_id:
            acct = candidate
            break
    if acct is None:
        fail("ERR_LOAN_ACCOUNT_NOT_FOUND",
             "No loan account was originated from application %s." % application_id)
    # Band 49
    if contract_amount > acct["credit_limit_cents"]:
        fail("ERR_CONTRACT_EXCEEDS_CREDIT_LIMIT",
             "The contract amount exceeds the account's credit limit.")
    rec = db.new_record()
    rec.update({
        "application_id": application_id,
        "merchant_id": app["merchant_id"],
        "loan_account_id": acct["id"],
        "scope_description": scope_description,
        "contract_amount_cents": contract_amount,
        "completion_status": "IN_PROGRESS",
        "completion_certificate_ref": None,
        "certified_on": None,
    })
    db.projects[rec["id"]] = rec
    return created(ser.project(rec))


@bp.get("/projects/<project_id>")
def read_project(project_id):
    ctx = v.authorize(ALL_READ_ROLES)
    rec = v.get_project(project_id)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    v.merchant_scope(ctx, rec["merchant_id"])
    v.consumer_scope(ctx, project_consumer_id(rec))
    return ok(ser.project(rec))


@bp.get("/projects")
def list_projects():
    ctx = v.authorize(ALL_READ_ROLES)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    limit, offset = v.pagination()
    application_id = v.filter_arg("application_id")
    merchant_id = v.filter_arg("merchant_id")
    account_id = v.filter_arg("loan_account_id")
    completion_status = v.filter_arg("completion_status")
    rows = []
    for rec in db.ordered(db.projects):
        if ctx.role == "Merchant" and rec["merchant_id"] != ctx.user_id:
            continue
        if ctx.role == "Consumer" and project_consumer_id(rec) != ctx.user_id:
            continue
        if application_id is not None and rec["application_id"] != application_id:
            continue
        if merchant_id is not None and rec["merchant_id"] != merchant_id:
            continue
        if account_id is not None and rec["loan_account_id"] != account_id:
            continue
        if completion_status is not None and rec["completion_status"] != completion_status:
            continue
        rows.append(rec)
    page = v.paginate(rows, limit, offset)
    return listing([ser.project(r) for r in page], limit, offset, len(rows))


# =============================================================================
# Milestones (PRD 3.6)
# =============================================================================
@bp.post("/projects/<project_id>/milestones")
def create_milestone(project_id):
    ctx = v.authorize(("Merchant",))
    body = v.read_body(ctx)
    sequence_no = v.req_int(body, "sequence_no", minimum=1)
    name = v.req_str(body, "name")
    release_pct_bps = v.req_money(body, "release_pct_bps")
    requires_signoff = v.opt_bool(body, "requires_consumer_signoff", True)
    project = v.get_project(project_id)
    v.resolve_identity(ctx, ("Merchant",))
    v.merchant_scope(ctx, project["merchant_id"])
    # Band 20
    if project["completion_status"] == "ABANDONED":
        fail("ERR_INVALID_PROJECT_STATE",
             "An abandoned project accepts no further milestones.")
    siblings = calc.project_milestones(project_id)
    # Band 37
    for other in siblings:
        if other["sequence_no"] == sequence_no:
            fail("ERR_DUPLICATE_MILESTONE_SEQUENCE",
                 "Sequence %d already exists on this project." % sequence_no)
    # Band 38
    total = sum(m["release_pct_bps"] for m in siblings) + release_pct_bps
    if total > calc.BPS:
        fail("ERR_MILESTONE_RELEASE_TOTAL_EXCEEDED",
             "The project's release shares would total %d basis points." % total)
    rec = db.new_record()
    rec.update({
        "project_id": project_id,
        "sequence_no": sequence_no,
        "name": name,
        "release_pct_bps": release_pct_bps,
        "requires_consumer_signoff": requires_signoff,
        "status": "PENDING",
        "claimed_at": None,
        "verified_at": None,
        "rejection_count": 0,
        "evidence_ref": None,
    })
    db.milestones[rec["id"]] = rec
    return created(ser.milestone(rec))


@bp.get("/projects/<project_id>/milestones")
def list_milestones(project_id):
    ctx = v.authorize(ALL_READ_ROLES)
    project = v.get_project(project_id)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    v.merchant_scope(ctx, project["merchant_id"])
    v.consumer_scope(ctx, project_consumer_id(project))
    limit, offset = v.pagination()
    status = v.filter_arg("status")
    rows = [m for m in calc.project_milestones(project_id)
            if status is None or m["status"] == status]
    page = v.paginate(rows, limit, offset)
    return listing([ser.milestone(r) for r in page], limit, offset, len(rows))


@bp.post("/projects/<project_id>/milestones/<milestone_id>/claim")
def claim_milestone(project_id, milestone_id):
    ctx = v.authorize(("Merchant",))
    body = v.read_body(ctx)
    evidence_ref = v.req_str(body, "evidence_ref")
    project = v.get_project(project_id)
    milestone = v.get_milestone(project_id, milestone_id)
    v.resolve_identity(ctx, ("Merchant",))
    v.merchant_scope(ctx, project["merchant_id"])
    # Band 17
    if milestone["status"] not in ("PENDING", "REJECTED"):
        fail("ERR_INVALID_MILESTONE_STATE",
             "A milestone standing at %s may not be claimed." % milestone["status"])
    # Band 20
    if project["completion_status"] == "ABANDONED":
        fail("ERR_INVALID_PROJECT_STATE",
             "An abandoned project accepts no milestone claims.")
    merchant = db.merchants.get(project["merchant_id"])
    if merchant is None or merchant["enrollment_status"] != "APPROVED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only an approved merchant may claim a milestone.")
    milestone["status"] = "CLAIMED"
    milestone["claimed_at"] = db.now()
    milestone["evidence_ref"] = evidence_ref
    ops.bump(milestone)
    return ok(ser.milestone(milestone))


@bp.post("/projects/<project_id>/milestones/<milestone_id>/verification")
def verify_milestone(project_id, milestone_id):
    roles = ("Consumer", "ServicingAgent")
    ctx = v.authorize(roles)
    body = v.read_body(ctx)
    outcome = v.req_enum(body, "outcome", ("VERIFY", "REJECT"))
    project = v.get_project(project_id)
    milestone = v.get_milestone(project_id, milestone_id)
    v.resolve_identity(ctx, roles)
    owner_consumer_id = project_consumer_id(project)
    v.consumer_scope(ctx, owner_consumer_id)
    # Band 17 — state admission, then the signoff rule.
    if outcome == "VERIFY" and milestone["status"] != "CLAIMED":
        fail("ERR_INVALID_MILESTONE_STATE",
             "Only a claimed milestone may be verified.")
    if outcome == "REJECT" and milestone["status"] not in ("CLAIMED", "VERIFIED"):
        fail("ERR_INVALID_MILESTONE_STATE",
             "A milestone standing at %s carries no verification decision."
             % milestone["status"])
    rescission = outcome == "REJECT" and milestone["status"] == "VERIFIED"
    if (milestone["requires_consumer_signoff"] or rescission) and ctx.role != "Consumer":
        fail("ERR_CONSUMER_SIGNOFF_REQUIRED",
             "Only the owning consumer may render this decision.")
    # Band 18 — a funded milestone may not have its verification rescinded.
    if rescission and calc.milestone_is_funded(milestone):
        fail("ERR_MILESTONE_ALREADY_FUNDED",
             "A funded milestone's verification may not be rescinded.")
    if outcome == "VERIFY":
        milestone["status"] = "VERIFIED"
        milestone["verified_at"] = db.now()
    else:
        milestone["status"] = "REJECTED"
        milestone["rejection_count"] += 1
        milestone["verified_at"] = None
    ops.bump(milestone)
    # The parent's compound state is re-derived from the aggregate release share.
    released = calc.verified_release_bps(project)
    if (outcome == "VERIFY" and project["completion_status"] == "IN_PROGRESS"
            and released >= calc.SUBSTANTIAL_COMPLETION_BPS):
        project["completion_status"] = "SUBSTANTIALLY_COMPLETE"
    elif (outcome == "REJECT" and project["completion_status"] == "SUBSTANTIALLY_COMPLETE"
            and released < calc.SUBSTANTIAL_COMPLETION_BPS):
        project["completion_status"] = "IN_PROGRESS"
    ops.bump(project)
    return ok(ser.milestone(milestone))


@bp.post("/projects/<project_id>/completion-certification")
def certify_project(project_id):
    ctx = v.authorize(("Consumer",))
    body = v.read_body(ctx)
    certificate_ref = v.opt_str(body, "completion_certificate_ref")
    project = v.get_project(project_id)
    v.resolve_identity(ctx, ("Consumer",))
    v.consumer_scope(ctx, project_consumer_id(project))
    # Band 20
    if project["completion_status"] not in ("IN_PROGRESS", "SUBSTANTIALLY_COMPLETE"):
        fail("ERR_INVALID_PROJECT_STATE",
             "A project standing at %s may not be certified."
             % project["completion_status"])
    # Band 29 — both clauses are enforced only when the trade demands a certificate.
    rule = merchant_trade_rule(project["merchant_id"])
    if rule is not None and rule["requires_completion_certificate"]:
        if not certificate_ref:
            fail("ERR_COMPLETION_CERTIFICATE_REQUIRED",
                 "This trade requires a signed completion certificate.")
        for milestone in calc.project_milestones(project_id):
            if milestone["status"] not in ("CLAIMED", "VERIFIED"):
                fail("ERR_COMPLETION_CERTIFICATE_REQUIRED",
                     "Every milestone must stand at CLAIMED or VERIFIED.")
    project["completion_certificate_ref"] = certificate_ref
    project["certified_on"] = db.now()
    project["completion_status"] = "CERTIFIED_COMPLETE"
    ops.bump(project)
    return ok(ser.project(project))


# =============================================================================
# Staged funding draws (PRD 3.7, 3.8)
# =============================================================================
SETTLEMENT_SPEEDS = ("NEXT_DAY", "STANDARD_3DAY")


@bp.post("/funding-draws")
def create_draw():
    ctx = v.authorize(("Merchant",))
    body = v.read_body(ctx)
    account_id = v.req_str(body, "loan_account_id")
    milestone_id = v.req_str(body, "project_milestone_id")
    requested = v.req_money(body, "requested_amount_cents", positive=True)
    speed = v.req_enum(body, "settlement_speed", SETTLEMENT_SPEEDS)
    expected = body.get("expected_loan_account_version")
    if expected is not None and not isinstance(expected, bool) and (
            not isinstance(expected, int)):
        fail("ERR_INVALID_REQUEST", "expected_loan_account_version must be a whole number.")
    # Band 6 — body foreign keys in payload-declaration order, trade rule last.
    acct = v.get_loan_account(account_id)
    milestone = v.get_milestone_by_id(milestone_id)
    project = calc.project_for_milestone(milestone)
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND", "The milestone's project no longer exists.")
    merchant = v.get_merchant(project["merchant_id"])
    rule = v.get_trade_rule(merchant["trade_type"])
    v.resolve_identity(ctx, ("Merchant",))
    v.merchant_scope(ctx, project["merchant_id"])
    # Band 13 — optimistic concurrency on the loan account.
    if expected is not None and expected != acct["version"]:
        fail("ERR_STALE_LOAN_ACCOUNT_VERSION",
             "The loan account has moved on since it was read.")
    # Band 14
    if merchant["enrollment_status"] != "APPROVED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only an approved merchant may draw program funds.")
    # Band 17
    if milestone["status"] != "VERIFIED":
        fail("ERR_INVALID_MILESTONE_STATE",
             "A draw may only be taken against a verified milestone.")
    # Band 18
    if calc.milestone_is_funded(milestone):
        fail("ERR_MILESTONE_ALREADY_FUNDED",
             "This milestone already backs a live draw.")
    # Band 20
    if project["completion_status"] == "ABANDONED":
        fail("ERR_INVALID_PROJECT_STATE",
             "An abandoned project may not be drawn against.")
    # Band 23
    if acct["balance_status"] in ("PAID_OFF", "CHARGED_OFF"):
        fail("ERR_LOAN_CLOSED", "The account is closed to further money movement.")
    # Band 32
    if project["loan_account_id"] != account_id:
        fail("ERR_MILESTONE_PROJECT_MISMATCH",
             "The milestone's project is funded by a different loan account.")
    # Band 50 — the headroom boundary is inclusive.
    headroom = calc.max_fundable_now_cents(project)
    if requested > headroom:
        fail("ERR_STAGED_FUNDING_LIMIT_EXCEEDED",
             "The request exceeds the %d cents of verified headroom." % headroom)
    plan = db.promotion_plans.get(acct["promotion_plan_id"])
    if plan is None:
        fail("ERR_PROMOTION_PLAN_NOT_FOUND", "The account's promotion plan is missing.")
    # The provisional view: plan and trade rates only, no negotiation, speed or tier.
    prov_discount, prov_holdback, prov_net = calc.provisional_economics(
        requested, plan, rule)
    rec = db.new_record()
    rec.update({
        "loan_account_id": account_id,
        "project_milestone_id": milestone_id,
        "merchant_id": project["merchant_id"],
        "requested_amount_cents": requested,
        "settlement_speed": speed,
        "status": "REQUESTED",
        "funded_amount_cents": requested,
        "provisional_discount_cents": prov_discount,
        "provisional_holdback_cents": prov_holdback,
        "provisional_net_settlement_cents": prov_net,
        "effective_discount_bps": None,
        "volume_tier_credit_bps": None,
        "merchant_discount_cents": None,
        "holdback_withheld_cents": None,
        "net_settlement_cents": None,
        "settled_on": None,
        "released_by_user_id": None,
        "denial_reason_code": None,
        "reversal_reason_code": None,
    })
    db.draws[rec["id"]] = rec
    # Creation flips the milestone's is_funded and reserves project headroom.
    ops.bump(milestone)
    ops.bump(project)
    return created(ser.draw(rec))


@bp.get("/funding-draws/<draw_id>")
def read_draw(draw_id):
    ctx = v.authorize(OPERATOR_READ_ROLES)
    rec = v.get_draw(draw_id)
    v.resolve_identity(ctx, OPERATOR_READ_ROLES)
    v.merchant_scope(ctx, rec["merchant_id"])
    return ok(ser.draw(rec))


@bp.get("/funding-draws")
def list_draws():
    ctx = v.authorize(OPERATOR_READ_ROLES)
    v.resolve_identity(ctx, OPERATOR_READ_ROLES)
    limit, offset = v.pagination()
    account_id = v.filter_arg("loan_account_id")
    milestone_id = v.filter_arg("project_milestone_id")
    merchant_id = v.filter_arg("merchant_id")
    status = v.filter_arg("status")
    speed = v.filter_arg("settlement_speed")
    rows = []
    for rec in db.ordered(db.draws):
        if ctx.role == "Merchant" and rec["merchant_id"] != ctx.user_id:
            continue
        if account_id is not None and rec["loan_account_id"] != account_id:
            continue
        if milestone_id is not None and rec["project_milestone_id"] != milestone_id:
            continue
        if merchant_id is not None and rec["merchant_id"] != merchant_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if speed is not None and rec["settlement_speed"] != speed:
            continue
        rows.append(rec)
    page = v.paginate(rows, limit, offset)
    return listing([ser.draw(r) for r in page], limit, offset, len(rows))


@bp.post("/funding-draws/<draw_id>/settlement")
def settle_draw(draw_id):
    ctx = v.authorize(("ServicingAgent",))
    body = v.read_body(ctx)
    decision = v.req_enum(body, "decision", ("SETTLE", "DENY"))
    denial_reason = v.opt_str(body, "denial_reason_code")
    draw = v.get_draw(draw_id)
    merchant = v.get_merchant(draw["merchant_id"])
    # Band 6 — the governing trade rule must exist.
    rule = v.get_trade_rule(merchant["trade_type"])
    # Band 14
    if merchant["enrollment_status"] != "APPROVED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only an approved merchant may receive a settlement.")
    # Band 19
    if draw["status"] != "REQUESTED":
        fail("ERR_INVALID_DRAW_STATE",
             "A draw standing at %s carries no settlement decision." % draw["status"])
    milestone = db.milestones.get(draw["project_milestone_id"])
    project = calc.project_for_milestone(milestone) if milestone else None
    if decision == "SETTLE":
        certified = project is not None and (
            project["completion_status"] == "CERTIFIED_COMPLETE")
        admitted = milestone is not None and (
            milestone["status"] == "VERIFIED"
            or (milestone["status"] == "CLAIMED" and certified))
        if not admitted:
            fail("ERR_INVALID_MILESTONE_STATE",
                 "The backing milestone no longer supports a release.")
    acct = v.get_loan_account(draw["loan_account_id"])
    # Band 23
    if acct["balance_status"] in ("PAID_OFF", "CHARGED_OFF"):
        fail("ERR_LOAN_CLOSED", "The account is closed to further money movement.")
    funded = draw["funded_amount_cents"]
    if decision == "DENY":
        # The mirror image: no money moves and the headroom is released upward.
        ops.deny_draw(draw, denial_reason)
        return ok(ser.draw(draw))
    # Band 51 — the velocity budget, before any ledger movement at all.
    window = calc.velocity_window_volume(merchant["id"], draw["id"]) + funded
    if window > rule["velocity_cap_cents"]:
        fail("ERR_FUNDING_VELOCITY_EXCEEDED",
             "The rolling seven-day volume of %d cents exceeds the cap." % window)
    plan = db.promotion_plans.get(acct["promotion_plan_id"])
    enrollment = calc.governing_enrollment(merchant["id"], acct["promotion_plan_id"])
    negotiated = enrollment["negotiated_discount_bps"] if enrollment else None
    effective_bps = negotiated if negotiated is not None else plan["merchant_discount_bps"]
    speed_bps = calc.SPEED_SURCHARGE_BPS[draw["settlement_speed"]]
    credit_bps = calc.volume_tier_credit_bps(
        calc.trailing_tier_volume(merchant["id"], draw["id"]))
    discount = calc.final_discount(funded, effective_bps, speed_bps, credit_bps)
    withheld, target_after = calc.holdback_reserve_target(
        merchant, funded, rule, draw["id"])
    draw["effective_discount_bps"] = effective_bps
    draw["volume_tier_credit_bps"] = credit_bps
    draw["merchant_discount_cents"] = discount
    draw["holdback_withheld_cents"] = withheld
    draw["net_settlement_cents"] = funded - discount - withheld
    draw["status"] = "SETTLED"
    draw["settled_on"] = fmt_date(db.today())
    draw["released_by_user_id"] = ctx.user_id
    ops.bump(draw)
    # The ledger, synchronised in both directions.
    if not acct.get("first_funding_on"):
        acct["first_funding_on"] = draw["settled_on"]
    ops.bump(acct)
    merchant["holdback_reserve_cents"] += withheld
    merchant["holdback_target_cents"] = target_after
    ops.bump(merchant)
    consumer = db.consumers.get(acct["consumer_id"])
    if consumer is not None:
        ops.bump(consumer)
    if project is not None:
        ops.bump(project)
        # Settlement is also when the phantom-project detector runs (PRD 3.11).
        ops.run_pre_completion_detector(project, rule)
    return ok(ser.draw(draw))


@bp.post("/funding-draws/<draw_id>/reversal")
def reverse_draw(draw_id):
    ctx = v.authorize(("ServicingAgent",))
    body = v.read_body(ctx)
    reason_code = v.req_str(body, "reversal_reason_code")
    draw = v.get_draw(draw_id)
    # Band 19
    if draw["status"] != "SETTLED":
        fail("ERR_INVALID_DRAW_STATE",
             "Only a settled draw may be reversed; this one stands at %s."
             % draw["status"])
    acct = v.get_loan_account(draw["loan_account_id"])
    # Band 23
    if acct["balance_status"] in ("PAID_OFF", "CHARGED_OFF"):
        fail("ERR_LOAN_CLOSED", "The account is closed to further money movement.")
    merchant = v.get_merchant(draw["merchant_id"])
    withheld = draw["holdback_withheld_cents"] or 0
    draw["status"] = "REVERSED"
    draw["reversal_reason_code"] = reason_code
    # The reversal date drives the accrual timeline; settled_on stays populated.
    draw["_reversed_on"] = fmt_date(db.today())
    ops.bump(draw)
    ops.bump(acct)
    merchant["holdback_reserve_cents"] -= withheld
    calc.recompute_holdback_target(merchant)
    ops.bump(merchant)
    consumer = db.consumers.get(acct["consumer_id"])
    if consumer is not None:
        ops.bump(consumer)
    milestone = db.milestones.get(draw["project_milestone_id"])
    if milestone is not None:
        ops.bump(milestone)
        project = calc.project_for_milestone(milestone)
        if project is not None:
            ops.bump(project)
    return ok(ser.draw(draw))


# =============================================================================
# Dispute cases, the chargeback waterfall and the four-hop cascade (PRD 3.10)
# =============================================================================
RESPONSE_TYPES = ("WORK_COMPLETE_EVIDENCE", "CONCEDE")


@bp.post("/dispute-cases")
def file_dispute():
    ctx = v.authorize(("Consumer",))
    body = v.read_body(ctx)
    account_id = v.req_str(body, "loan_account_id")
    project_id = v.req_str(body, "project_id")
    claimed = v.req_money(body, "claimed_incomplete_amount_cents", positive=True)
    description = v.req_str(body, "description")
    reopens_case_id = v.opt_str(body, "reopens_case_id")
    # Band 6 — loan account, then project, then the reopen target.
    acct = v.get_loan_account(account_id)
    project = v.get_project(project_id)
    reopened = v.get_dispute(reopens_case_id) if reopens_case_id else None
    v.resolve_identity(ctx, ("Consumer",))
    v.consumer_scope(ctx, acct["consumer_id"])
    # Band 20
    if project["completion_status"] == "ABANDONED":
        fail("ERR_INVALID_PROJECT_STATE",
             "An abandoned project carries no further disputes.")
    # Band 33
    if project["loan_account_id"] != account_id:
        fail("ERR_DISPUTE_PROJECT_MISMATCH",
             "The disputed project is funded by a different loan account.")
    # Band 40
    for case in calc.project_disputes(project_id):
        if case["status"] in calc.NON_TERMINAL_DISPUTE:
            fail("ERR_DISPUTE_ALREADY_OPEN",
                 "A case on this project is still open.")
    # Band 41 — the thirty-day reopen boundary is inclusive.
    if reopened is not None:
        eligible = (reopened["project_id"] == project_id
                    and reopened["status"] == "RESOLVED_MERCHANT_FAVOR"
                    and reopened["resolved_on"] is not None
                    and (db.today() - parse_date(reopened["resolved_on"])).days
                    <= calc.REOPEN_WINDOW_DAYS)
        if not eligible:
            fail("ERR_DISPUTE_NOT_REOPENABLE",
                 "Case %s is not reopenable." % reopens_case_id)
    # Band 53 — there is also nothing to dispute before any draw has settled.
    settled_funded = calc.settled_funded_cents(project)
    if claimed > settled_funded:
        fail("ERR_DISPUTE_CLAIM_EXCEEDS_FUNDED",
             "The claim exceeds the %d cents advanced on this project." % settled_funded)
    opened_on = db.today()
    rec = db.new_record()
    rec.update({
        "loan_account_id": account_id,
        "project_id": project_id,
        "merchant_id": project["merchant_id"],
        "reopens_case_id": reopens_case_id,
        "claimed_incomplete_amount_cents": claimed,
        "description": description,
        # The filing carries the case straight through SUBMITTED in one operation.
        "status": "MERCHANT_RESPONSE_PENDING",
        "opened_on": fmt_date(opened_on),
        "response_due_at": midnight(opened_on + timedelta(days=calc.MERCHANT_RESPONSE_DAYS)),
        "merchant_responded_at": None,
        "response_type": None,
        "evidence_ref": None,
        "chargeback_amount_cents": 0,
        "chargeback_absorbed_from_reserve_cents": 0,
        "chargeback_receivable_cents": 0,
        "chargeback_write_off_cents": 0,
        "resolved_by_user_id": None,
        "resolved_on": None,
    })
    db.disputes[rec["id"]] = rec
    ops.bump(project)
    merchant = db.merchants.get(project["merchant_id"])
    if merchant is not None:
        ops.bump(merchant)
    return created(ser.dispute(rec))


@bp.get("/dispute-cases/<case_id>")
def read_dispute(case_id):
    ctx = v.authorize(ALL_READ_ROLES)
    rec = v.get_dispute(case_id)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    v.merchant_scope(ctx, rec["merchant_id"])
    acct = db.loan_accounts.get(rec["loan_account_id"])
    v.consumer_scope(ctx, acct["consumer_id"] if acct else None)
    return ok(ser.dispute(rec))


@bp.get("/dispute-cases")
def list_disputes():
    ctx = v.authorize(ALL_READ_ROLES)
    v.resolve_identity(ctx, ALL_READ_ROLES)
    limit, offset = v.pagination()
    account_id = v.filter_arg("loan_account_id")
    project_id = v.filter_arg("project_id")
    merchant_id = v.filter_arg("merchant_id")
    reopens_case_id = v.filter_arg("reopens_case_id")
    status = v.filter_arg("status")
    rows = []
    for rec in db.ordered(db.disputes):
        if ctx.role == "Merchant" and rec["merchant_id"] != ctx.user_id:
            continue
        if ctx.role == "Consumer":
            acct = db.loan_accounts.get(rec["loan_account_id"])
            if acct is None or acct["consumer_id"] != ctx.user_id:
                continue
        if account_id is not None and rec["loan_account_id"] != account_id:
            continue
        if project_id is not None and rec["project_id"] != project_id:
            continue
        if merchant_id is not None and rec["merchant_id"] != merchant_id:
            continue
        if reopens_case_id is not None and rec["reopens_case_id"] != reopens_case_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    page = v.paginate(rows, limit, offset)
    return listing([ser.dispute(r) for r in page], limit, offset, len(rows))


@bp.post("/dispute-cases/<case_id>/merchant-response")
def respond_to_dispute(case_id):
    ctx = v.authorize(("Merchant",))
    body = v.read_body(ctx)
    response_type = v.req_enum(body, "response_type", RESPONSE_TYPES)
    evidence_ref = v.opt_str(body, "evidence_ref")
    case = v.get_dispute(case_id)
    v.resolve_identity(ctx, ("Merchant",))
    v.merchant_scope(ctx, case["merchant_id"])
    # Band 21
    if case["status"] != "MERCHANT_RESPONSE_PENDING":
        fail("ERR_INVALID_DISPUTE_STATE",
             "A case standing at %s takes no merchant response." % case["status"])
    # Band 45 — the response must arrive strictly before the deadline.
    if db.now() >= case["response_due_at"]:
        fail("ERR_RESPONSE_WINDOW_CLOSED",
             "The ten-day response window has closed.")
    case["merchant_responded_at"] = db.now()
    case["response_type"] = response_type
    case["evidence_ref"] = evidence_ref
    ops.bump(case)
    return ok(ser.dispute(case))


@bp.post("/dispute-cases/<case_id>/resolution")
def resolve_dispute(case_id):
    ctx = v.authorize(("ServicingAgent",))
    body = v.read_body(ctx)
    outcome = v.req_enum(body, "outcome", ("MERCHANT_FAVOR", "CONSUMER_FAVOR"))
    expected = v.req_int(body, "expected_merchant_version")
    case = v.get_dispute(case_id)
    merchant = v.get_merchant(case["merchant_id"])
    project = db.projects.get(case["project_id"])
    # Band 11 — no agent may resolve a case over money they released themselves.
    if project is not None:
        for draw in calc.project_draws(project):
            if draw["status"] == "SETTLED" and draw["released_by_user_id"] == ctx.user_id:
                fail("ERR_SEGREGATION_OF_DUTIES",
                     "The releasing agent may not resolve this case.")
    # Band 12
    if expected != merchant["version"]:
        fail("ERR_STALE_MERCHANT_VERSION",
             "The merchant record has moved on since it was read.")
    # Band 21
    if outcome == "MERCHANT_FAVOR":
        if (case["status"] != "MERCHANT_RESPONSE_PENDING"
                or not case["merchant_responded_at"]
                or case["response_type"] != "WORK_COMPLETE_EVIDENCE"):
            fail("ERR_INVALID_DISPUTE_STATE",
                 "A merchant-favour resolution requires a recorded evidence response.")
    elif case["status"] not in ("MERCHANT_RESPONSE_PENDING", "ESCALATED_NO_RESPONSE"):
        fail("ERR_INVALID_DISPUTE_STATE",
             "A case standing at %s takes no resolution." % case["status"])
    resolved_on = db.today()
    case["resolved_by_user_id"] = ctx.user_id
    case["resolved_on"] = fmt_date(resolved_on)
    if outcome == "MERCHANT_FAVOR":
        # The merchant keeps the funds: no reserve, receivable or write-off movement.
        case["status"] = "RESOLVED_MERCHANT_FAVOR"
        ops.bump(case)
        if project is not None:
            ops.bump(project)
        ops.bump(merchant)
        return ok(ser.dispute(case))
    # Hop one — the chargeback allocation, measured before the reserve is drawn down.
    claim = case["claimed_incomplete_amount_cents"]
    absorbed, receivable, write_off = calc.chargeback_waterfall(
        merchant, claim, resolved_on)
    case["status"] = "RESOLVED_CONSUMER_FAVOR"
    case["chargeback_amount_cents"] = claim
    case["chargeback_absorbed_from_reserve_cents"] = absorbed
    case["chargeback_receivable_cents"] = receivable
    case["chargeback_write_off_cents"] = write_off
    ops.bump(case)
    # Hop two — caused by hop one: the merchant ledger, the account and the project.
    merchant["holdback_reserve_cents"] -= absorbed
    merchant["settlement_offset_receivable_cents"] += receivable
    merchant["program_write_off_cents"] += write_off
    ops.bump(merchant)
    acct = db.loan_accounts.get(case["loan_account_id"])
    if acct is not None:
        ops.bump(acct)
        consumer = db.consumers.get(acct["consumer_id"])
        if consumer is not None:
            ops.bump(consumer)
    if project is not None:
        project["completion_status"] = "ABANDONED"
        ops.bump(project)
    # Hop three — caused by hop two: coverage below half the target suspends.
    if (calc.reserve_coverage_bps(merchant) < calc.RESERVE_SUSPENSION_BPS
            and merchant["enrollment_status"] == "APPROVED"):
        # Hop four is the cascade inside suspend_merchant.
        ops.suspend_merchant(merchant, "RESERVE_COVERAGE")
    return ok(ser.dispute(case))
