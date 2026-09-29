"""Fund replacement proposals: draft, review loop, approval, notice, mapping."""
from datetime import timedelta
from flask import Blueprint

import calc
from core import (as_enum, as_int, as_str, authenticate, body, clock, fail,
                  new_row, ok, ok_list, paginate, parse_dt, public, q_str,
                  req_field, require_actor_plan, resolve_committee_identity,
                  store, touch)
from helpers import filter_rows, get_row, require_posture, resolve_body_refs

bp = Blueprint("replacement", __name__)

SUPERSEDABLE = ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "BLOCKED")


def _refresh(plan):
    calc.recompute_posture(plan)
    touch(plan)


def _slot_of(proposal):
    return store.slots.get(proposal["slot_id"])


def _notice_deadline(proposal):
    delivered = parse_dt(proposal["notice_delivered_at"], "notice_delivered_at")
    return delivered + timedelta(days=proposal["notice_lead_days_required"])


@bp.route("/governance/fund-replacements", methods=["POST"])
def create_proposal():
    authenticate(("InvestmentConsultant",))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans", "!slot_id": "slots",
                                       "!outgoing_fund_id": "funds",
                                       "!incoming_fund_id": "funds"})
    plan = refs.get("plan_id")
    slot = refs.get("slot_id")
    outgoing = refs.get("outgoing_fund_id")
    incoming = refs.get("incoming_fund_id")
    rationale = as_str(req_field(payload, "rationale"), "rationale", 10, 500)
    strategy = as_enum(req_field(payload, "mapping_strategy"), "mapping_strategy",
                       calc.MAPPING_STRATEGIES)
    expected = as_int(req_field(payload, "expected_plan_version"),
                      "expected_plan_version", 0)

    require_posture(plan, slot)
    if expected != plan["version"]:
        fail("ERR_STALE_PLAN_VERSION", "expected_plan_version is stale")
    if incoming["asset_class_code"] != slot["asset_class_code"]:
        fail("ERR_ASSET_CLASS_MISMATCH",
             "the incoming fund's asset class does not match the slot")
    if slot["designation"] == "QDIA" and not incoming.get("is_target_date_suite"):
        fail("ERR_ASSET_CLASS_MISMATCH",
             "a QDIA slot accepts only a target-date suite")
    adopted = calc.adopted_ips(plan["id"])
    if adopted is None:
        fail("ERR_NO_ADOPTED_IPS",
             "the plan has no ADOPTED investment policy statement")

    proposal = new_row({
        "plan_id": plan["id"],
        "slot_id": slot["id"],
        "outgoing_fund_id": outgoing["id"],
        "incoming_fund_id": incoming["id"],
        "approving_motion_id": None,
        "superseded_by_proposal_id": None,
        "rationale": rationale,
        "mapping_strategy": strategy,
        "status": "DRAFT",
        "revision_round": 0,
        "pre_block_status": None,
        "notice_lead_days_required": calc.notice_lead_days(plan, {
            "mapping_strategy": strategy}, slot),
        "notice_delivered_at": None,
        "blackout_start_at": None,
        "blackout_end_at": None,
        "mapped_assets_cents": 0,
        "pinned_plan_version": expected,
        "pinned_ips_id": adopted["id"],
    })
    store.proposals[proposal["id"]] = proposal

    for prior in calc.sort_created(calc.plan_proposals(plan["id"])):
        if prior["id"] == proposal["id"] or prior["slot_id"] != slot["id"]:
            continue
        if prior["status"] == "DRAFT":
            prior["status"] = "WITHDRAWN"
            prior["superseded_by_proposal_id"] = proposal["id"]
            touch(prior)
    calc.recompute_posture(plan)
    touch(plan)
    return ok(public(proposal), 201)


@bp.route("/governance/fund-replacements", methods=["GET"])
def list_proposals():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "Recordkeeper", "PlanAuditor"))
    rows = filter_rows(list(store.proposals.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("slot_id"), "slot_id"),
                        (q_str("outgoing_fund_id"), "outgoing_fund_id"),
                        (q_str("incoming_fund_id"), "incoming_fund_id"),
                        (q_str("approving_motion_id"), "approving_motion_id"),
                        (q_str("superseded_by_proposal_id"),
                         "superseded_by_proposal_id"),
                        (q_str("pinned_ips_id"), "pinned_ips_id"),
                        (q_str("mapping_strategy"), "mapping_strategy"),
                        (q_str("status"), "status")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/fund-replacements/<proposal_id>", methods=["GET"])
def get_proposal(proposal_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "Recordkeeper", "PlanAuditor"))
    return ok(public(get_row("proposals", proposal_id, "proposalId")))


@bp.route("/governance/fund-replacements/<proposal_id>/submit", methods=["POST"])
def submit_proposal(proposal_id):
    authenticate(("InvestmentConsultant",))
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    slot = _slot_of(proposal)
    incoming = store.funds.get(proposal["incoming_fund_id"])

    if proposal["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "only a DRAFT proposal may be submitted")
    require_posture(plan, slot)
    adopted = calc.adopted_ips(plan["id"])
    if adopted is None:
        fail("ERR_NO_ADOPTED_IPS",
             "the plan has no ADOPTED investment policy statement")
    if len(proposal["rationale"]) < 40:
        fail("ERR_INVALID_REQUEST",
             "rationale must be at least 40 characters at submission")
    if incoming["menu_status"] != "CANDIDATE" or \
            incoming["asset_class_code"] != slot["asset_class_code"]:
        fail("ERR_ASSET_CLASS_MISMATCH",
             "the incoming fund is not an eligible candidate for this slot")
    calc.require_ips_eligible(incoming, adopted)
    if slot.get("current_fund_id") != proposal["outgoing_fund_id"]:
        fail("ERR_OUTGOING_FUND_MISMATCH",
             "the outgoing fund is no longer seated in the slot")

    proposal["status"] = "UNDER_REVIEW"
    proposal["pinned_ips_id"] = adopted["id"]
    proposal["notice_lead_days_required"] = calc.notice_lead_days(plan, proposal, slot)
    # PRD 3.7 pins `pinned_plan_version` to "the plan's current `version`" -- the
    # same phrase the revision loop uses -- so the token records the version a
    # client reading the plan straight after this write would see, that is after
    # this write's own `draft_proposal_count` decrement has bumped it.
    _refresh(plan)
    proposal["pinned_plan_version"] = plan["version"]
    touch(proposal)
    return ok(public(proposal))


@bp.route("/governance/fund-replacements/<proposal_id>/request-revision",
          methods=["POST"])
def request_revision(proposal_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    require_actor_plan(actor, plan["id"])
    payload = body()
    note = as_str(req_field(payload, "revision_note"), "revision_note", 1)

    if proposal["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an UNDER_REVIEW proposal may be sent back")
    if proposal["revision_round"] >= 3:
        fail("ERR_REVISION_LIMIT_REACHED", "the revision limit has been reached")

    proposal["status"] = "REVISION_REQUESTED"
    proposal["revision_round"] = proposal["revision_round"] + 1
    proposal["revision_note"] = note
    touch(proposal)
    _refresh(plan)
    return ok(public(proposal))


@bp.route("/governance/fund-replacements/<proposal_id>/revise", methods=["POST"])
def revise_proposal(proposal_id):
    authenticate(("InvestmentConsultant",))
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    slot = _slot_of(proposal)
    payload = body()
    refs = resolve_body_refs(payload, {"incoming_fund_id": "funds"},
                             extra_rows={"_proposal": ("proposals", proposal)})
    incoming = refs.get("incoming_fund_id") or store.funds.get(
        proposal["incoming_fund_id"])
    strategy = payload.get("mapping_strategy")
    if strategy is not None:
        strategy = as_enum(strategy, "mapping_strategy", calc.MAPPING_STRATEGIES)
    rationale = payload.get("rationale")
    if rationale is not None:
        rationale = as_str(rationale, "rationale", 10, 500)

    if proposal["status"] != "REVISION_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a REVISION_REQUESTED proposal may be revised")
    require_posture(plan, slot)
    pinned = store.ips.get(proposal["pinned_ips_id"])
    if pinned is None:
        fail("ERR_NO_ADOPTED_IPS", "the proposal's pinned statement is unknown")
    if incoming["asset_class_code"] != slot["asset_class_code"]:
        fail("ERR_ASSET_CLASS_MISMATCH",
             "the incoming fund's asset class does not match the slot")
    calc.require_ips_eligible(incoming, pinned)

    proposal["incoming_fund_id"] = incoming["id"]
    if strategy is not None:
        proposal["mapping_strategy"] = strategy
    if rationale is not None:
        proposal["rationale"] = rationale
    proposal["status"] = "UNDER_REVIEW"
    proposal["notice_lead_days_required"] = calc.notice_lead_days(plan, proposal, slot)
    # PRD 3.7: revision "refreshes `pinned_plan_version` to the plan's current
    # `version`", read after this write settles, exactly as submission does.
    _refresh(plan)
    proposal["pinned_plan_version"] = plan["version"]
    touch(proposal)
    return ok(public(proposal))


@bp.route("/governance/fund-replacements/<proposal_id>/approve", methods=["POST"])
def approve_proposal(proposal_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    slot = _slot_of(proposal)
    require_actor_plan(actor, plan["id"])
    payload = body()
    refs = resolve_body_refs(payload, {"!approving_motion_id": "motions"},
                             extra_rows={"_proposal": ("proposals", proposal)})
    motion = refs.get("approving_motion_id")

    if proposal["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an UNDER_REVIEW proposal may be approved")
    require_posture(plan, slot)
    if motion["subject_type"] != "FUND_REPLACEMENT" or \
            motion["subject_id"] != proposal["id"] or motion["status"] != "CARRIED":
        fail("ERR_MOTION_NOT_CARRIED",
             "the motion is not a carried FUND_REPLACEMENT motion for this proposal")
    calc.require_minutes_approved(motion)
    adopted = calc.adopted_ips(plan["id"])
    if adopted is None:
        fail("ERR_NO_ADOPTED_IPS",
             "the plan has no ADOPTED investment policy statement")
    if proposal["pinned_ips_id"] != adopted["id"]:
        fail("ERR_IPS_VERSION_STALE",
             "the proposal is pinned to a superseded policy statement")
    if slot["status"] not in ("ACTIVE", "AT_RISK"):
        fail("ERR_SLOT_NOT_REPLACEABLE", "the slot cannot be replaced now")
    for other in calc.plan_proposals(plan["id"]):
        if other["id"] == proposal["id"] or other["slot_id"] != slot["id"]:
            continue
        if other["status"] in ("APPROVED", "NOTICE_ISSUED"):
            fail("ERR_SLOT_HAS_OPEN_PROPOSAL",
                 "another proposal already holds this slot")
    if plan["available_menu_slots"] < 1:
        fail("ERR_MENU_CAPACITY_EXHAUSTED", "no available menu slot remains")

    proposal["status"] = "APPROVED"
    proposal["approving_motion_id"] = motion["id"]
    touch(proposal)
    slot["status"] = "PENDING_REPLACEMENT"
    touch(slot)
    for other in calc.sort_created(calc.plan_proposals(plan["id"])):
        if other["id"] == proposal["id"] or other["slot_id"] != slot["id"]:
            continue
        if other["status"] in SUPERSEDABLE:
            other["status"] = "WITHDRAWN"
            other["superseded_by_proposal_id"] = proposal["id"]
            touch(other)
    _refresh(plan)
    return ok(public(proposal))


@bp.route("/governance/fund-replacements/<proposal_id>/rescind-approval",
          methods=["POST"])
def rescind_approval(proposal_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    slot = _slot_of(proposal)
    require_actor_plan(actor, plan["id"])
    payload = body()
    reason = as_str(req_field(payload, "reason"), "reason", 1)

    # PRD 3.7: once `notice_delivered_at` is set the rescission is refused with
    # ERR_NOTICE_ALREADY_ISSUED, the specific priority-42 error that PRD 2.12
    # prefers over the generic ERR_INVALID_STATE_TRANSITION.
    if proposal.get("notice_delivered_at"):
        fail("ERR_NOTICE_ALREADY_ISSUED", "the participant notice has gone out")
    if proposal["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an APPROVED proposal may be rescinded")

    proposal["status"] = "UNDER_REVIEW"
    proposal["approving_motion_id"] = None
    proposal["rescind_reason"] = reason
    touch(proposal)
    seated = store.funds.get(slot.get("current_fund_id"))
    if seated is not None and seated["watch_status"] == "CLEAR":
        slot["status"] = "ACTIVE"
    else:
        slot["status"] = "AT_RISK"
    touch(slot)
    _refresh(plan)
    return ok(public(proposal))


@bp.route("/governance/fund-replacements/<proposal_id>/notice-issue",
          methods=["POST"])
def notice_issue(proposal_id):
    authenticate(("Recordkeeper",))
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    payload = body()
    start = parse_dt(req_field(payload, "blackout_start_at"), "blackout_start_at")
    end = parse_dt(req_field(payload, "blackout_end_at"), "blackout_end_at")

    if proposal["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an APPROVED proposal may issue notice")
    if plan["fee_disclosure_status"] == "RESTATEMENT_REQUIRED":
        fail("ERR_FEE_DISCLOSURE_RESTATEMENT_REQUIRED",
             "the plan's fee disclosure is under restatement")
    if not start < end:
        fail("ERR_INVALID_REQUEST",
             "blackout_start_at must precede blackout_end_at")

    buffer_days = timedelta(days=plan["blackout_buffer_days"])
    for other in calc.sort_created(calc.plan_proposals(plan["id"])):
        if other["id"] == proposal["id"]:
            continue
        if other["status"] not in ("NOTICE_ISSUED", "EXECUTED"):
            continue
        if not other.get("blackout_start_at") or not other.get("blackout_end_at"):
            continue
        o_start = parse_dt(other["blackout_start_at"], "blackout_start_at")
        o_end = parse_dt(other["blackout_end_at"], "blackout_end_at") + buffer_days
        if start < o_end and o_start < end:
            fail("ERR_BLACKOUT_WINDOW_CONFLICT",
                 "the blackout window collides with another proposal")

    delivered = clock.now
    earliest = delivered + timedelta(days=proposal["notice_lead_days_required"])
    if start < earliest:
        fail("ERR_NOTICE_PERIOD_NOT_ELAPSED",
             "blackout_start_at is inside the notice period")

    proposal["notice_delivered_at"] = clock.iso()
    proposal["blackout_start_at"] = payload["blackout_start_at"]
    proposal["blackout_end_at"] = payload["blackout_end_at"]
    proposal["status"] = "NOTICE_ISSUED"
    touch(proposal)
    _refresh(plan)
    return ok(public(proposal))


@bp.route("/governance/fund-replacements/<proposal_id>/execute", methods=["POST"])
def execute_proposal(proposal_id):
    authenticate(("Recordkeeper",))
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    slot = _slot_of(proposal)
    outgoing = store.funds.get(proposal["outgoing_fund_id"])
    incoming = store.funds.get(proposal["incoming_fund_id"])

    if proposal["status"] != "NOTICE_ISSUED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a NOTICE_ISSUED proposal may be executed")
    require_posture(plan, slot)
    now = clock.now
    if now < _notice_deadline(proposal):
        fail("ERR_NOTICE_PERIOD_NOT_ELAPSED", "the notice period has not elapsed")
    start = parse_dt(proposal["blackout_start_at"], "blackout_start_at")
    end = parse_dt(proposal["blackout_end_at"], "blackout_end_at")
    if now < start or now >= end:
        fail("ERR_BLACKOUT_WINDOW_CONFLICT",
             "the clock is outside the blackout window")
    if slot["status"] != "PENDING_REPLACEMENT":
        fail("ERR_INVALID_STATE_TRANSITION", "the slot is not PENDING_REPLACEMENT")

    receiver = incoming
    if proposal["mapping_strategy"] == "REENROLLMENT":
        qdia = calc.qdia_slot(plan["id"])
        qdia_fund = store.funds.get(qdia.get("current_fund_id")) if qdia else None
        if qdia is None or qdia_fund is None:
            fail("ERR_QDIA_REQUIRES_TARGET_DATE_SUITE",
                 "the plan has no qualified-default fund to re-enrol into")
        receiver = qdia_fund

    mapped = outgoing["plan_assets_cents"]
    proposal["mapped_assets_cents"] = mapped
    proposal["_receiving_fund_id"] = receiver["id"]
    receiver["plan_assets_cents"] = receiver["plan_assets_cents"] + mapped
    if receiver["id"] != outgoing["id"]:
        outgoing["plan_assets_cents"] = 0
    touch(receiver)

    slot["current_fund_id"] = incoming["id"]
    slot["status"] = "ACTIVE"
    slot["at_risk_since_quarter_index"] = None
    touch(slot)
    incoming["menu_status"] = "ACTIVE"
    incoming["credit_accrual_status"] = "ACCRUING"
    incoming["qdia_flag"] = slot["designation"] == "QDIA"
    touch(incoming)

    # hops 0 and 1 — the outgoing fund leaves the menu.
    outgoing["menu_status"] = "REMOVED"
    outgoing["credit_accrual_status"] = "CLOSED_OUT"
    outgoing["qdia_flag"] = False
    touch(outgoing)

    # hop 2 — approved levelization runs whose pool included the removed fund.
    for run in calc.sort_created(calc.plan_runs(plan["id"])):
        if run["status"] == "APPROVED" and \
                outgoing["id"] in (run.get("pool_fund_ids") or []):
            run["status"] = "RECALC_REQUIRED"
            touch(run)
    # hop 3 — the fee disclosure goes stale on every execution, because the
    # credit-pool basis the disclosure rested on has gone stale (PRD 3.7).
    if plan["fee_disclosure_status"] == "COMPLIANT":
        plan["fee_disclosure_status"] = "RESTATEMENT_REQUIRED"
        # hop 4 — open fee-levelization motions are tabled.
        for motion in calc.sort_created(calc.plan_motions(plan["id"])):
            if motion["status"] == "OPEN" and \
                    motion["subject_type"] == "FEE_LEVELIZATION":
                motion["status"] = "TABLED"
                motion["closed_at"] = clock.iso()
                touch(motion)

    proposal["status"] = "EXECUTED"
    touch(proposal)
    _refresh(plan)
    return ok(public(proposal))


@bp.route("/governance/fund-replacements/<proposal_id>/unwind", methods=["POST"])
def unwind_proposal(proposal_id):
    authenticate(("PlanSponsorAdmin",))
    proposal = get_row("proposals", proposal_id, "proposalId")
    plan = store.plans.get(proposal["plan_id"])
    slot = _slot_of(proposal)
    payload = body()
    reason = as_str(req_field(payload, "reason"), "reason", 1)

    if proposal["status"] != "EXECUTED":
        fail("ERR_INVALID_STATE_TRANSITION", "only an EXECUTED proposal may unwind")
    end = parse_dt(proposal["blackout_end_at"], "blackout_end_at")
    if clock.now >= end:
        fail("ERR_UNWIND_WINDOW_CLOSED", "the blackout window has closed")

    outgoing = store.funds.get(proposal["outgoing_fund_id"])
    incoming = store.funds.get(proposal["incoming_fund_id"])
    receiver = store.funds.get(proposal.get("_receiving_fund_id")) or incoming
    mapped = proposal["mapped_assets_cents"]
    receiver["plan_assets_cents"] = receiver["plan_assets_cents"] - mapped
    touch(receiver)
    outgoing["plan_assets_cents"] = mapped
    outgoing["menu_status"] = "ACTIVE"
    outgoing["credit_accrual_status"] = "ACCRUING"
    touch(outgoing)
    if incoming["id"] != outgoing["id"]:
        incoming["menu_status"] = "CANDIDATE"
        incoming["credit_accrual_status"] = "NOT_ACCRUING"
        incoming["qdia_flag"] = False
        touch(incoming)
    slot["current_fund_id"] = outgoing["id"]
    slot["status"] = "ACTIVE"
    touch(slot)
    outgoing["qdia_flag"] = slot["designation"] == "QDIA"

    proposal["status"] = "UNWOUND"
    proposal["unwind_reason"] = reason
    touch(proposal)

    if plan["fee_disclosure_status"] == "RESTATEMENT_REQUIRED":
        inside = False
        now = clock.now
        for other in calc.plan_proposals(plan["id"]):
            if other["id"] == proposal["id"] or other["status"] != "EXECUTED":
                continue
            if not other.get("blackout_end_at"):
                continue
            if now < parse_dt(other["blackout_end_at"], "blackout_end_at"):
                inside = True
                break
        if not inside:
            plan["fee_disclosure_status"] = "COMPLIANT"
    _refresh(plan)
    return ok(public(proposal))
