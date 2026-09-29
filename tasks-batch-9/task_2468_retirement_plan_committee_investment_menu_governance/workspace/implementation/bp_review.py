"""Quarterly reviews, fund scorecards, and the finalize / reopen cascades."""
from flask import Blueprint

import calc
from core import (D, as_bool, as_dec, as_int, as_str, authenticate, body, clock,
                  fail, new_row, ok, ok_list, opt_field, paginate, public, q_int,
                  q_str, req_field, require_actor_plan,
                  resolve_committee_identity, store, touch)
from helpers import filter_rows, get_row, resolve_body_refs

bp = Blueprint("review", __name__)

COVERAGE_SLOT_STATES = ("ACTIVE", "AT_RISK", "PENDING_REPLACEMENT")


def _first(payload, *names):
    for name in names:
        if payload.get(name) is not None:
            return payload[name]
    return None


def _submitted_cards(review_id):
    return [c for c in store.scorecards.values()
            if c["review_id"] == review_id and c["status"] == "SUBMITTED"]


def _recount_review(review):
    cards = [c for c in store.scorecards.values() if c["review_id"] == review["id"]]
    review["scorecard_count"] = len([c for c in cards if c["status"] != "VOID"])
    review["submitted_scorecard_count"] = len([c for c in cards
                                               if c["status"] == "SUBMITTED"])


# --------------------------------------------------------------------------- #
# Quarterly reviews
# --------------------------------------------------------------------------- #

@bp.route("/governance/quarterly-reviews", methods=["POST"])
def create_review():
    authenticate(("InvestmentConsultant",))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans", "meeting_id": "meetings"})
    plan = refs.get("plan_id")
    meeting = refs.get("meeting_id")
    quarter_index = as_int(req_field(payload, "quarter_index"), "quarter_index", 0)

    adopted = calc.adopted_ips(plan["id"])
    if adopted is None:
        fail("ERR_NO_ADOPTED_IPS",
             "the plan has no ADOPTED investment policy statement")
    for other in calc.plan_reviews(plan["id"]):
        if other["status"] != "VOID" and other["quarter_index"] == quarter_index:
            fail("ERR_DUPLICATE_RESOURCE",
                 "the plan already has a review for that quarter")

    review = new_row({
        "plan_id": plan["id"],
        "ips_id": adopted["id"],
        "meeting_id": meeting["id"] if meeting else None,
        "quarter_index": quarter_index,
        "status": "DRAFT",
        "scoring_variant": adopted["scoring_variant"],
        "scorecard_count": 0,
        "submitted_scorecard_count": 0,
        "watch_additions_count": 0,
        "reopen_count": 0,
        "finalized_quarter_index": None,
        "finalized_at": None,
    })
    store.reviews[review["id"]] = review
    return ok(public(review), 201)


@bp.route("/governance/quarterly-reviews", methods=["GET"])
def list_reviews():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    rows = filter_rows(list(store.reviews.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("ips_id"), "ips_id"),
                        (q_str("meeting_id"), "meeting_id"),
                        (q_int("quarter_index"), "quarter_index"),
                        (q_str("status"), "status")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/quarterly-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    return ok(public(get_row("reviews", review_id, "reviewId")))


@bp.route("/governance/quarterly-reviews/<review_id>/present", methods=["POST"])
def present_review(review_id):
    authenticate(("InvestmentConsultant",))
    review = get_row("reviews", review_id, "reviewId")
    payload = body()
    plan = store.plans.get(review["plan_id"])
    refs = resolve_body_refs(payload, {"meeting_id": "meetings"},
                             extra_rows={"_review": ("reviews", review)})
    supplied = refs.get("meeting_id")

    if review["status"] != "SCORING":
        fail("ERR_INVALID_STATE_TRANSITION", "only a SCORING review may be presented")
    meeting_id = supplied["id"] if supplied else review.get("meeting_id")
    if not meeting_id:
        fail("ERR_REVIEW_MEETING_MISSING", "the review has no meeting attached")
    meeting = store.meetings.get(meeting_id)
    if meeting is None:
        fail("ERR_RESOURCE_NOT_FOUND", "meeting_id does not resolve")
    if meeting["status"] != "IN_SESSION":
        fail("ERR_MEETING_NOT_IN_SESSION", "the meeting is not in session")
    if not meeting["quorum_met"]:
        fail("ERR_QUORUM_NOT_MET", "the meeting is inquorate")

    scored = set(c["fund_id"] for c in _submitted_cards(review["id"]))
    for slot in calc.slot_order(calc.plan_slots(plan["id"])):
        if slot["status"] not in COVERAGE_SLOT_STATES:
            continue
        if slot.get("current_fund_id") not in scored:
            fail("ERR_SCORECARD_COVERAGE_INCOMPLETE",
                 "slot %d has no submitted scorecard" % slot["slot_index"])
    _recount_review(review)
    if review["submitted_scorecard_count"] < 1:
        fail("ERR_NO_SCORECARDS", "the review carries no submitted scorecard")

    review["meeting_id"] = meeting_id
    review["status"] = "PENDING_MINUTES"
    touch(review)
    return ok(public(review))


@bp.route("/governance/quarterly-reviews/<review_id>/finalize", methods=["POST"])
def finalize_review(review_id):
    actor = authenticate(("CommitteeChair",))
    resolve_committee_identity(actor)
    review = get_row("reviews", review_id, "reviewId")
    plan = store.plans.get(review["plan_id"])
    require_actor_plan(actor, plan["id"])

    if review["status"] != "PENDING_MINUTES":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a PENDING_MINUTES review may be finalized")
    meeting = store.meetings.get(review.get("meeting_id"))
    if meeting is None:
        fail("ERR_REVIEW_MEETING_MISSING", "the review has no meeting attached")
    if meeting["status"] != "MINUTES_APPROVED":
        fail("ERR_MINUTES_NOT_APPROVED", "the meeting's minutes are not approved")
    adopted = calc.adopted_ips(plan["id"])
    if adopted is None:
        fail("ERR_NO_ADOPTED_IPS",
             "the plan has no ADOPTED investment policy statement")
    if review["ips_id"] != adopted["id"]:
        fail("ERR_IPS_VERSION_STALE",
             "the review is pinned to a superseded policy statement")
    if actor.member["fiduciary_training_status"] != "CURRENT" or \
            not actor.member.get("acceptance_signed_at"):
        fail("ERR_TRAINING_NOT_CURRENT", "the acting chair's training is not current")

    quarter = review["quarter_index"]
    cards = {}
    for card in _submitted_cards(review["id"]):
        cards[card["fund_id"]] = card

    # ---- hop 0: finalize and write scores -------------------------------- #
    review["status"] = "FINALIZED"
    review["finalized_at"] = clock.iso()
    review["finalized_quarter_index"] = plan["fiscal_quarter_index"]
    for fund_id, card in cards.items():
        fund = store.funds.get(fund_id)
        if fund is None:
            continue
        fund["latest_composite_score"] = card["composite_score"]
        fund["last_scored_quarter_index"] = quarter
        touch(fund)

    # ---- iteration order: seated funds by slot_index, then unseated ------ #
    ordered = []
    seen = set()
    for slot in calc.slot_order(calc.plan_slots(plan["id"])):
        fund_id = slot.get("current_fund_id")
        if fund_id and fund_id in cards and fund_id not in seen:
            ordered.append((store.funds[fund_id], slot))
            seen.add(fund_id)
    for fund in calc.sort_created([store.funds[f] for f in cards
                                   if f in store.funds]):
        if fund["id"] not in seen:
            ordered.append((fund, None))
            seen.add(fund["id"])

    # ---- hops 1 and 2 ---------------------------------------------------- #
    additions = 0
    for fund, slot in ordered:
        card = cards[fund["id"]]
        recommendation = card["watch_recommendation"]
        before = fund["watch_status"]
        menu_before = fund["menu_status"]
        moved_out_of_clear = False
        cured = False
        nxt = fund["consecutive_breach_quarters"] + 1

        if before == "CLEAR" and recommendation in ("WATCH", "REMEDIATION",
                                                    "TERMINATE"):
            # PRD 3.5 hop 1 moves the fund "according to that fund's
            # watch_recommendation": a remediation-grade measurement lands on
            # REMEDIATION in a single hop rather than by way of WATCH.
            fund["watch_status"] = ("WATCH" if recommendation == "WATCH"
                                    else "REMEDIATION")
            fund["watch_started_quarter_index"] = quarter
            fund["consecutive_breach_quarters"] = nxt
            moved_out_of_clear = True
        elif before == "WATCH" and recommendation in ("WATCH", "REMEDIATION",
                                                      "TERMINATE"):
            if recommendation in ("REMEDIATION", "TERMINATE") or nxt >= 2:
                fund["watch_status"] = "REMEDIATION"
            fund["consecutive_breach_quarters"] = nxt
        elif before == "REMEDIATION" and recommendation == "TERMINATE":
            fund["watch_status"] = "TERMINATION_PENDING"
            fund["consecutive_breach_quarters"] = nxt
            if fund["menu_status"] == "ACTIVE":
                fund["menu_status"] = "PENDING_REMOVAL"
        elif before == "REMEDIATION" and recommendation in ("WATCH",
                                                            "REMEDIATION"):
            fund["consecutive_breach_quarters"] = nxt
        elif before in ("WATCH", "REMEDIATION", "TERMINATION_PENDING") and \
                recommendation == "NONE" and \
                calc.clears_cure_margin(card, adopted):
            fund["watch_status"] = "CLEAR"
            fund["watch_started_quarter_index"] = None
            fund["consecutive_breach_quarters"] = 0
            cured = True
        elif before == "CLEAR" and recommendation == "NONE":
            fund["consecutive_breach_quarters"] = 0
        # PRD 3.5 hop 1: the snapshot records what the dimension held *before
        # each change*, and the menu dimension only "where it is touched" -- a
        # dimension this review never moved carries no snapshot at all.
        fund["watch_status_before_last_review"] = (
            before if fund["watch_status"] != before else None)
        fund["menu_status_before_last_review"] = (
            menu_before if fund["menu_status"] != menu_before else None)
        touch(fund)
        if moved_out_of_clear:
            additions += 1

        if slot is not None:
            if moved_out_of_clear and slot["status"] == "ACTIVE":
                slot["status_before_last_review"] = "ACTIVE"
                slot["status"] = "AT_RISK"
                slot["at_risk_since_quarter_index"] = quarter
                touch(slot)
            elif cured and slot["status"] == "AT_RISK":
                slot["status_before_last_review"] = "AT_RISK"
                slot["status"] = "ACTIVE"
                slot["at_risk_since_quarter_index"] = None
                touch(slot)
            elif slot.get("status_before_last_review") is not None:
                # PRD 3.5 hop 2 only snapshots a slot it actually moves.
                slot["status_before_last_review"] = None
                touch(slot)
    review["watch_additions_count"] = additions
    touch(review)

    # ---- hops 3 and 4 ---------------------------------------------------- #
    posture = calc.recompute_posture(plan)
    calc.block_proposals_for_posture(plan, posture)
    touch(plan)
    return ok(public(review))


@bp.route("/governance/quarterly-reviews/<review_id>/reopen", methods=["POST"])
def reopen_review(review_id):
    authenticate(("PlanSponsorAdmin",))
    review = get_row("reviews", review_id, "reviewId")
    payload = body()
    # PRD 2.8: `reason` is required on reopening a finalized review.
    reason = as_str(req_field(payload, "reason"), "reason", 1)
    plan = store.plans.get(review["plan_id"])

    if review["status"] != "FINALIZED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a FINALIZED review may be reopened")
    if plan["fiscal_quarter_index"] - review["quarter_index"] > 1:
        fail("ERR_QUARTER_CLOSED", "the review's quarter is closed")
    if review["reopen_count"] >= 2:
        fail("ERR_REOPEN_LIMIT_REACHED", "the review has been reopened twice")
    for proposal in calc.plan_proposals(plan["id"]):
        if proposal["status"] not in ("APPROVED", "NOTICE_ISSUED", "EXECUTED"):
            continue
        motion = store.motions.get(proposal.get("approving_motion_id"))
        if motion is not None and motion["meeting_id"] == review.get("meeting_id"):
            fail("ERR_REVIEW_DECISIONS_EXECUTED",
                 "a decision from that meeting has already been acted upon")

    quarter = review["quarter_index"]
    review["status"] = "REOPENED"
    review["reopen_count"] = review["reopen_count"] + 1
    review["finalized_at"] = None
    touch(review)

    for fund in calc.sort_created(calc.plan_funds(plan["id"])):
        if fund.get("last_scored_quarter_index") != quarter:
            continue
        if fund.get("watch_status_before_last_review") is not None:
            fund["watch_status"] = fund["watch_status_before_last_review"]
        if fund.get("menu_status_before_last_review") is not None:
            fund["menu_status"] = fund["menu_status_before_last_review"]
        fund["consecutive_breach_quarters"] = max(
            0, fund["consecutive_breach_quarters"] - 1)
        if fund["watch_status"] == "CLEAR":
            fund["watch_started_quarter_index"] = None
        fund["latest_composite_score"] = _prior_score(plan, fund, quarter)
        touch(fund)

    for slot in calc.slot_order(calc.plan_slots(plan["id"])):
        if slot.get("status_before_last_review") is None:
            continue
        seated = store.funds.get(slot.get("current_fund_id"))
        if seated is None or seated.get("last_scored_quarter_index") != quarter:
            continue
        if slot["status"] != slot["status_before_last_review"]:
            slot["status"] = slot["status_before_last_review"]
            if slot["status"] != "AT_RISK":
                slot["at_risk_since_quarter_index"] = None
            touch(slot)

    calc.recompute_posture(plan)
    touch(plan)
    return ok(public(review))


def _prior_score(plan, fund, quarter):
    """The composite_score from the most recent earlier FINALIZED review."""
    best = None
    for review in calc.plan_reviews(plan["id"]):
        if review["status"] != "FINALIZED" or review["quarter_index"] >= quarter:
            continue
        for card in _submitted_cards(review["id"]):
            if card["fund_id"] != fund["id"]:
                continue
            if best is None or review["quarter_index"] > best[0]:
                best = (review["quarter_index"], card["composite_score"])
    return best[1] if best else None


# --------------------------------------------------------------------------- #
# Fund scorecards
# --------------------------------------------------------------------------- #

@bp.route("/governance/fund-scorecards", methods=["POST"])
def create_scorecard():
    authenticate(("InvestmentConsultant",))
    payload = body()
    refs = resolve_body_refs(payload, {"!review_id": "reviews", "!fund_id": "funds"})
    review = refs.get("review_id")
    fund = refs.get("fund_id")
    plan = store.plans.get(review["plan_id"])
    if fund["plan_id"] != review["plan_id"]:
        fail("ERR_CROSS_PLAN_REFERENCE", "fund_id belongs to a different plan")

    expected = req_field(payload, "expected_review_version")
    expected = as_int(expected, "expected_review_version", 0)
    t3 = as_int(_require_any(payload, "trailing_return_3y_bps",
                             "trailing_3y_return_bps"), "trailing_return_3y_bps")
    t5 = as_int(_require_any(payload, "trailing_return_5y_bps",
                             "trailing_5y_return_bps"), "trailing_return_5y_bps")
    b3 = as_int(_require_any(payload, "benchmark_return_3y_bps",
                             "benchmark_3y_return_bps"), "benchmark_return_3y_bps")
    b5 = as_int(_require_any(payload, "benchmark_return_5y_bps",
                             "benchmark_5y_return_bps"), "benchmark_return_5y_bps")
    rolling = _first(payload, "rolling_since_watch_return_bps")
    rolling_bm = _first(payload, "rolling_since_watch_benchmark_bps")
    if rolling is not None:
        rolling = as_int(rolling, "rolling_since_watch_return_bps")
    if rolling_bm is not None:
        rolling_bm = as_int(rolling_bm, "rolling_since_watch_benchmark_bps")
    peer_rank = as_int(req_field(payload, "peer_rank_pct"), "peer_rank_pct", 1, 100)
    drift = as_dec(req_field(payload, "style_drift_r2"), "style_drift_r2", 4,
                   "0.0000", "1.0000")
    net = as_int(req_field(payload, "net_expense_ratio_bps"),
                 "net_expense_ratio_bps", 0)
    peer_median = as_int(req_field(payload, "peer_median_expense_bps"),
                         "peer_median_expense_bps", 1)
    tenure = as_int(req_field(payload, "manager_tenure_quarters"),
                    "manager_tenure_quarters", 0)
    change_flag = as_bool(opt_field(payload, "manager_change_flag", False),
                          "manager_change_flag")

    if review["status"] not in ("DRAFT", "SCORING", "REOPENED"):
        fail("ERR_REVIEW_NOT_SCORING", "the review no longer accepts scorecards")
    if expected != review["version"]:
        fail("ERR_STALE_REVIEW_VERSION", "expected_review_version is stale")

    variant = review["scoring_variant"]
    if variant == "ROLLING_SINCE_WATCH" and fund["watch_status"] != "CLEAR":
        if fund.get("watch_started_quarter_index") is None or rolling is None \
                or rolling_bm is None:
            fail("ERR_ROLLING_WINDOW_UNAVAILABLE",
                 "the rolling-since-watch window is unavailable")
    if variant == "ROLLING_SINCE_WATCH" and fund["watch_status"] == "CLEAR":
        fail("ERR_ROLLING_WINDOW_UNAVAILABLE",
             "a CLEAR fund has no rolling-since-watch window")

    ips = store.ips.get(review["ips_id"])
    card = new_row({
        "review_id": review["id"],
        "fund_id": fund["id"],
        "supersedes_scorecard_id": None,
        "trailing_3y_return_bps": t3,
        "trailing_5y_return_bps": t5,
        "benchmark_3y_return_bps": b3,
        "benchmark_5y_return_bps": b5,
        "rolling_since_watch_return_bps": rolling,
        "rolling_since_watch_benchmark_bps": rolling_bm,
        "peer_rank_pct": peer_rank,
        "style_drift_r2": drift,
        "net_expense_ratio_bps": net,
        "peer_median_expense_bps": peer_median,
        "manager_tenure_quarters": tenure,
        "manager_change_flag": change_flag,
        "status": "SUBMITTED",
    })
    card.update(calc.composite_components(card, ips, variant))
    card["watch_recommendation"] = calc.watch_recommendation(card, fund, ips)

    for prior in _submitted_cards(review["id"]):
        if prior["fund_id"] == fund["id"]:
            prior["status"] = "SUPERSEDED"
            touch(prior)
            card["supersedes_scorecard_id"] = prior["id"]
    store.scorecards[card["id"]] = card

    if review["status"] in ("DRAFT", "REOPENED"):
        review["status"] = "SCORING"
    _recount_review(review)
    touch(review)
    return ok(public(card), 201)


def _require_any(payload, *names):
    for name in names:
        if payload.get(name) is not None:
            return payload[name]
    fail("ERR_INVALID_REQUEST", "%s is required" % names[0])


@bp.route("/governance/fund-scorecards", methods=["GET"])
def list_scorecards():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    rows = filter_rows(list(store.scorecards.values()),
                       [(q_str("review_id"), "review_id"),
                        (q_str("fund_id"), "fund_id"),
                        (q_str("supersedes_scorecard_id"),
                         "supersedes_scorecard_id"),
                        (q_str("watch_recommendation"), "watch_recommendation"),
                        (q_str("status"), "status")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/fund-scorecards/<scorecard_id>", methods=["GET"])
def get_scorecard(scorecard_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    return ok(public(get_row("scorecards", scorecard_id, "scorecardId")))
