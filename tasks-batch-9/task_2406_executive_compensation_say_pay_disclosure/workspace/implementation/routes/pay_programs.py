"""Pay programs: design, mix, approval, alignment read and the vote (PRD §3.3, §3.8)."""

from flask import Blueprint, request

import calc
from db import apply_changes, insert, now, ordered, sec, store, touch
from errors import ApiError
from middleware import (
    ROLE_CHAIR,
    ROLE_COMP_CONSULTANT,
    ROLE_COUNSEL,
    ROLE_IR_LEAD,
    authenticate,
)
from response import object_response
from routes.common import body_fk, fetch, paginated
from services import domain
from validation import Body

bp = Blueprint("pay_programs", __name__)

MIX_COMPONENTS = {"SALARY", "STI", "LTI"}


def _mix_total(program):
    return calc.money(
        calc.dec(program["salary_pct"])
        + calc.dec(program["sti_pct"])
        + calc.dec(program["lti_pct"])
    )


@bp.post("/exec-comp/pay-programs")
def create_program():
    authenticate([ROLE_COMP_CONSULTANT])
    body = Body()
    issuer = body_fk(body, "issuer_company_id", "companies")
    if issuer is None:
        raise ApiError("ERR_INVALID_REQUEST", "issuer_company_id is required")
    group = body_fk(body, "peer_group_id", "peer_groups")
    if group is None:
        raise ApiError("ERR_INVALID_REQUEST", "peer_group_id is required")
    executive = body_fk(body, "ceo_executive_id", "executives")
    if executive is None:
        raise ApiError("ERR_INVALID_REQUEST", "ceo_executive_id is required")

    fiscal_year = body.integer("fiscal_year", required=True, minimum=2020, maximum=2035)
    salary_pct = body.number("salary_pct", required=True, places=2)
    sti_pct = body.number("sti_pct", required=True, places=2)
    lti_pct = body.number("lti_pct", required=True, places=2)
    lti_performance_share_pct = body.number(
        "lti_performance_share_pct", required=True, minimum=0, maximum=100, places=2
    )
    sti_max_multiple = body.number(
        "sti_max_multiple", default=calc.dec("2.0"), minimum=1, maximum=3
    )
    tsr_percentile_rank = body.number(
        "tsr_percentile_rank", default=calc.money(0), minimum=0, maximum=100, places=2
    )
    meeting_date = body.instant("meeting_date", required=True)

    if not issuer["is_issuer"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "issuer_company_id must name the filing issuer"
        )
    if group["issuer_company_id"] != issuer["id"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "the peer group benchmarks a different issuer"
        )
    if executive["company_id"] != issuer["id"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "the officer is not employed by the issuer"
        )

    if sec(meeting_date) <= sec(now()):
        raise ApiError("ERR_MEETING_DATE_NOT_FUTURE")

    total = calc.money(salary_pct + sti_pct + lti_pct)
    if total != calc.MIX_TOTAL:
        raise ApiError("ERR_PAY_MIX_MUST_TOTAL_100")
    for value in (salary_pct, sti_pct, lti_pct):
        if value < calc.MIX_COMPONENT_MIN or value > calc.MIX_COMPONENT_MAX:
            raise ApiError("ERR_MIX_COMPONENT_OUT_OF_BOUNDS")

    program = insert(
        store.pay_programs,
        {
            "issuer_company_id": issuer["id"],
            "peer_group_id": group["id"],
            "ceo_executive_id": executive["id"],
            "fiscal_year": fiscal_year,
            "salary_pct": salary_pct,
            "sti_pct": sti_pct,
            "lti_pct": lti_pct,
            "lti_performance_share_pct": lti_performance_share_pct,
            "sti_max_multiple": sti_max_multiple,
            "tsr_percentile_rank": tsr_percentile_rank,
            "meeting_date": meeting_date,
            "performance_based_pct": None,
            "fixed_leg_usd": None,
            "benchmark_ratio": None,
            "lti_multiple": None,
            "lti_target_usd": None,
            "target_tdc_usd": None,
            "benchmark_posture": "UNBENCHMARKED",
            "realized_pay_total_usd": calc.money(0),
            "realizable_pay_total_usd": calc.money(0),
            "pay_percentile_rank": None,
            "degree_of_alignment": None,
            "alignment_status": "UNRATED",
            "design_status": "DRAFT",
            "vote_status": "NOT_VOTED",
            "votes_for": None,
            "votes_against": None,
            "abstentions": None,
            "support_pct": None,
            "enhanced_engagement_required": False,
            "outreach_coverage_pct": calc.money(0),
            "approved_by_user_id": None,
        },
    )
    values = calc.target_direct_comp(program, executive, group["benchmark_target_tdc_usd"])
    program.update(values)
    return object_response(program, 201)


@bp.get("/exec-comp/pay-programs")
def list_programs():
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL, ROLE_IR_LEAD])
    rows = ordered(list(store.pay_programs.values()))
    for field in (
        "issuer_company_id",
        "peer_group_id",
        "ceo_executive_id",
        "design_status",
        "vote_status",
    ):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginated(rows)


@bp.get("/exec-comp/pay-programs/<pid>")
def read_program(pid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL, ROLE_IR_LEAD])
    return object_response(fetch("pay_programs", pid))


@bp.get("/exec-comp/pay-programs/<pid>/pay-for-performance")
def pay_for_performance(pid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL, ROLE_IR_LEAD])
    program = fetch("pay_programs", pid)
    return object_response(
        {
            "realized_pay_total_usd": program["realized_pay_total_usd"],
            "realizable_pay_total_usd": program["realizable_pay_total_usd"],
            "pay_percentile_rank": program["pay_percentile_rank"],
            "tsr_percentile_rank": program["tsr_percentile_rank"],
            "degree_of_alignment": program["degree_of_alignment"],
            "alignment_status": program["alignment_status"],
            "accepted_peer_count": len(
                domain.group_members(program["peer_group_id"], accepted_only=True)
            ),
        }
    )


@bp.post("/exec-comp/pay-programs/<pid>/mix-reallocation")
def mix_reallocation(pid):
    authenticate([ROLE_COMP_CONSULTANT])
    program = fetch("pay_programs", pid)
    body = Body()
    from_component = body.enum("from_component", MIX_COMPONENTS, required=True)
    to_component = body.enum("to_component", MIX_COMPONENTS, required=True)
    points = body.number("points", required=True, places=2)
    expected_version = body.integer("expected_pay_program_version", required=True)
    if from_component == to_component:
        raise ApiError(
            "ERR_INVALID_REQUEST", "from_component and to_component must differ"
        )
    if points <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "points must be strictly positive")

    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PAY_PROGRAM_VERSION")
    if program["design_status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_MUTABLE")

    from_field = calc.MIX_FIELDS[from_component]
    to_field = calc.MIX_FIELDS[to_component]
    candidate = {
        "salary_pct": calc.dec(program["salary_pct"]),
        "sti_pct": calc.dec(program["sti_pct"]),
        "lti_pct": calc.dec(program["lti_pct"]),
    }
    candidate[from_field] = calc.money(candidate[from_field] - points)
    candidate[to_field] = calc.money(candidate[to_field] + points)

    total = calc.money(
        candidate["salary_pct"] + candidate["sti_pct"] + candidate["lti_pct"]
    )
    if total != calc.MIX_TOTAL:
        raise ApiError("ERR_PAY_MIX_MUST_TOTAL_100")
    for value in candidate.values():
        if value < calc.MIX_COMPONENT_MIN or value > calc.MIX_COMPONENT_MAX:
            raise ApiError("ERR_MIX_COMPONENT_OUT_OF_BOUNDS")

    apply_changes(program, candidate)
    domain.recompute_program_target(program)
    touch(program)
    domain.mark_screens_stale(program)
    return object_response(program)


@bp.post("/exec-comp/pay-programs/<pid>/approve")
def approve_program(pid):
    user_id, _ = authenticate([ROLE_CHAIR])
    program = fetch("pay_programs", pid)
    if program["design_status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_MUTABLE")
    group = store.peer_groups[program["peer_group_id"]]
    if group["status"] != "APPROVED":
        raise ApiError("ERR_PEER_GROUP_NOT_APPROVED")
    if _mix_total(program) != calc.MIX_TOTAL:
        raise ApiError("ERR_PAY_MIX_MUST_TOTAL_100")

    metrics = domain.program_metrics(program["id"])
    for vehicle in ("ANNUAL_INCENTIVE", "LONG_TERM_PSU"):
        vehicle_metrics = [m for m in metrics if m["vehicle"] == vehicle]
        if not vehicle_metrics:
            continue
        weights = calc.money(
            sum((calc.dec(m["weight_pct"]) for m in vehicle_metrics), calc.dec(0))
        )
        if weights != calc.money(100):
            raise ApiError("ERR_METRIC_WEIGHTS_NOT_100")

    if (
        program["target_tdc_usd"] is not None
        and group["benchmark_target_tdc_usd"] is not None
    ):
        cap = calc.money(
            calc.dec(group["benchmark_target_tdc_usd"]) * calc.BENCHMARK_CAP_MULTIPLE
        )
        if calc.dec(program["target_tdc_usd"]) > cap:
            raise ApiError("ERR_TDC_EXCEEDS_BENCHMARK_CAP")

    apply_changes(
        program, {"design_status": "COMMITTEE_APPROVED", "approved_by_user_id": user_id}
    )
    touch(program)
    for metric in metrics:
        if metric["status"] == "DRAFT":
            apply_changes(
                metric,
                {"status": "LOCKED", "locked_target_value": metric["target_value"]},
            )
            touch(metric)
    return object_response(program)


@bp.post("/exec-comp/pay-programs/<pid>/vote-certification")
def vote_certification(pid):
    authenticate([ROLE_CHAIR])
    program = fetch("pay_programs", pid)
    body = Body()
    votes_for = body.integer("votes_for", required=True, minimum=0)
    votes_against = body.integer("votes_against", required=True, minimum=0)
    abstentions = body.integer("abstentions", required=True, minimum=0)
    if votes_for + votes_against == 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "votes_for and votes_against may not both be zero"
        )

    if program["design_status"] != "DISCLOSED":
        raise ApiError("ERR_PROGRAM_NOT_DISCLOSED")
    if program["vote_status"] != "NOT_VOTED":
        raise ApiError("ERR_VOTE_ALREADY_CERTIFIED")
    cda = next(
        (
            d
            for d in domain.program_drafts(program["id"])
            if d["section_code"] == "CD_AND_A"
        ),
        None,
    )
    if cda is None or cda["status"] != "FILED":
        raise ApiError("ERR_CDA_NOT_FILED")

    support = calc.support_pct(votes_for, votes_against)
    enhanced = support < calc.RESPONSIVENESS_FLOOR
    changes = {
        "votes_for": votes_for,
        "votes_against": votes_against,
        "abstentions": abstentions,
        "support_pct": support,
        "enhanced_engagement_required": enhanced,
    }
    before = domain.watched(program)
    if support >= calc.PASS_FLOOR:
        changes["vote_status"] = "PASSED"
        if support >= calc.RESPONSIVENESS_FLOOR:
            changes["design_status"] = "CLOSED"
        apply_changes(program, changes)
        touch(program)
        domain.stale_if_watched_changed(program, before)
    else:
        changes["vote_status"] = "FAILED"
        changes["alignment_status"] = "MISALIGNED"
        apply_changes(program, changes)
        touch(program)
        domain.mark_screens_stale(program)
        domain.bounce_legal_cleared(program)
        for draft in domain.program_drafts(program["id"]):
            if draft["status"] == "FILED" and draft["section_code"] != "CD_AND_A":
                apply_changes(
                    draft,
                    {
                        "status": "DRAFTING",
                        "revision_round": draft["revision_round"] + 1,
                        "cleared_by_user_id": None,
                        "filed_at": None,
                    },
                )
    return object_response(program)


@bp.post("/exec-comp/pay-programs/<pid>/remediation")
def remediation(pid):
    authenticate([ROLE_CHAIR])
    program = fetch("pay_programs", pid)
    body = Body()
    body.string("feedback_summary", required=True, max_len=2000)

    if program["vote_status"] != "FAILED":
        raise ApiError("ERR_VOTE_NOT_FAILED")
    if calc.dec(program["outreach_coverage_pct"]) < calc.REMEDIATION_COVERAGE_FLOOR:
        raise ApiError("ERR_OUTREACH_COVERAGE_INSUFFICIENT")

    before = domain.watched(program)
    apply_changes(
        program,
        {
            "vote_status": "REMEDIATED",
            "design_status": "CLOSED",
            "enhanced_engagement_required": False,
        },
    )
    touch(program)
    domain.stale_if_watched_changed(program, before)
    return object_response(program)
