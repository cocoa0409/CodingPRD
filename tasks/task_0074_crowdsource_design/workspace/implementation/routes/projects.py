"""Project routes: CRUD + lifecycle actions (submit-for-review, approve, reject, cancel, award, close)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import format_iso, get_now, parse_iso
from common import check_version, get_json_body, paginate, stamp_new, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import emit_audit
from services.calculations import (
    compute_withholding,
    originality_score_final,
)
from services.similarity import peer_similarity, public_similarity


bp = Blueprint("projects", __name__)


HTTPS_RE = None
import re as _re  # noqa: E402

HTTPS_RE = _re.compile(r"^https://[^\s]+$")


# --- Helpers ----------------------------------------------------------------


def _validate_timeline(opens_at, submission_deadline, final_decision_deadline):
    """ERR_TIMELINE_TOO_TIGHT if 72h or 168h minimum gap is violated.

    Raises api_error.
    """
    if not (opens_at and submission_deadline and final_decision_deadline):
        raise api_error("ERR_TIMELINE_TOO_TIGHT", "missing timeline fields")
    if submission_deadline < opens_at + timedelta(hours=72):
        raise api_error("ERR_TIMELINE_TOO_TIGHT", "submission_deadline must be >= opens_at + 72h")
    if final_decision_deadline < submission_deadline + timedelta(hours=168):
        raise api_error("ERR_TIMELINE_TOO_TIGHT", "final_decision_deadline must be >= submission_deadline + 168h")


def _project_stages(project_id):
    return [s for s in db.review_stages.values() if s.get("project_id") == project_id]


def _stage_by_kind(project_id, kind):
    for s in db.review_stages.values():
        if s.get("project_id") == project_id and s.get("stage_kind") == kind:
            return s
    return None


def _project_tiers(project_id):
    return [t for t in db.prize_tiers.values() if t.get("project_id") == project_id]


def _project_submissions(project_id):
    return [s for s in db.submissions.values() if s.get("project_id") == project_id]


# --- POST /projects ---------------------------------------------------------


@bp.route("/projects", methods=["POST"])
def create_project():
    user_id, _ = require_roles({"Client"})
    body = get_json_body()

    client_id = body.get("client_id")
    category_code = body.get("category_code")
    title = body.get("title")
    brief = body.get("brief")
    ref_urls = body.get("reference_material_urls", [])
    prize_pool_cents = body.get("prize_pool_cents")
    opens_at_s = body.get("opens_at")
    sub_deadline_s = body.get("submission_deadline")
    final_dl_s = body.get("final_decision_deadline")
    max_per_designer = body.get("max_submissions_per_designer", 3)
    client_part_final = body.get("client_participates_final", False)

    # FK checks: client_id (must equal acting user) and category_code
    if client_id not in db.clients:
        raise api_error("ERR_FK_NOT_FOUND", "client_id not found")
    if user_id != client_id:
        raise api_error("ERR_FORBIDDEN", "Clients can only create projects for themselves")
    if category_code not in db.design_categories_by_code:
        raise api_error("ERR_FK_NOT_FOUND", "category_code not found")

    if not isinstance(title, str) or not (1 <= len(title) <= 200):
        raise api_error("ERR_VALIDATION", "title length 1..200")
    if not isinstance(brief, str) or not (1 <= len(brief) <= 5000):
        raise api_error("ERR_VALIDATION", "brief length 1..5000")
    if not isinstance(ref_urls, list) or len(ref_urls) > 20:
        raise api_error("ERR_VALIDATION", "reference_material_urls must be a list of <= 20 items")
    for u in ref_urls:
        if not (isinstance(u, str) and HTTPS_RE.match(u)):
            raise api_error("ERR_VALIDATION", "reference_material_urls must each be valid HTTPS")
    try:
        prize_pool_cents = int(prize_pool_cents)
    except (TypeError, ValueError):
        raise api_error("ERR_PRIZE_AMOUNT_INVALID", "prize_pool_cents must be integer")
    if prize_pool_cents < 100_000:
        raise api_error("ERR_PRIZE_AMOUNT_INVALID", "prize_pool_cents must be >= 100000 (1000.00)")
    try:
        max_per_designer = int(max_per_designer)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "max_submissions_per_designer must be integer")
    if not (1 <= max_per_designer <= 10):
        raise api_error("ERR_VALIDATION", "max_submissions_per_designer 1..10")
    if not isinstance(client_part_final, bool):
        raise api_error("ERR_VALIDATION", "client_participates_final must be boolean")

    opens_at = parse_iso(opens_at_s)
    sub_deadline = parse_iso(sub_deadline_s)
    final_dl = parse_iso(final_dl_s)
    if not (opens_at and sub_deadline and final_dl):
        raise api_error("ERR_VALIDATION", "opens_at/submission_deadline/final_decision_deadline required ISO-8601")
    _validate_timeline(opens_at, sub_deadline, final_dl)

    project = stamp_new({
        "client_id": client_id,
        "category_code": category_code,
        "title": title,
        "brief": brief,
        "reference_material_urls": list(ref_urls),
        "prize_pool_cents": prize_pool_cents,
        "opens_at": format_iso(opens_at),
        "submission_deadline": format_iso(sub_deadline),
        "final_decision_deadline": format_iso(final_dl),
        "status": "DRAFT",
        "max_submissions_per_designer": max_per_designer,
        "client_participates_final": client_part_final,
        "anonymity_unmasked_at": None,
        "published_winner_list": [],
    })
    db.projects[project["id"]] = project
    return success(project, status=201)


@bp.route("/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    require_roles({"PlatformOps", "Client", "Designer", "Reviewer"})
    p = db.projects.get(project_id)
    if not p:
        raise api_error("ERR_NOT_FOUND", "project not found")
    return success(p)


@bp.route("/projects", methods=["GET"])
def list_projects():
    require_roles({"PlatformOps", "Client", "Designer", "Reviewer"})
    status = request.args.get("status")
    category_code = request.args.get("category_code")
    client_id = request.args.get("client_id")
    items = list(db.projects.values())
    if status:
        items = [p for p in items if p.get("status") == status]
    if category_code:
        items = [p for p in items if p.get("category_code") == category_code]
    if client_id:
        items = [p for p in items if p.get("client_id") == client_id]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


# --- POST /projects/{id}/prize-tiers ----------------------------------------


@bp.route("/projects/<project_id>/prize-tiers", methods=["POST"])
def create_prize_tier(project_id):
    user_id, _ = require_roles({"Client"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    if project.get("client_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "Clients can only modify their own projects")
    if project.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "prize tiers can only be added while project is DRAFT")

    body = get_json_body()
    rank = body.get("rank")
    gross = body.get("gross_amount_cents")
    tier_kind = body.get("tier_kind")
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "rank must be integer")
    if rank < 1:
        raise api_error("ERR_VALIDATION", "rank must be >= 1")
    try:
        gross = int(gross)
    except (TypeError, ValueError):
        raise api_error("ERR_PRIZE_AMOUNT_INVALID", "gross_amount_cents must be integer")
    if gross < 0:
        raise api_error("ERR_PRIZE_AMOUNT_INVALID", "gross_amount_cents must be >= 0")
    if tier_kind not in {"MAIN", "CONSOLATION"}:
        raise api_error("ERR_VALIDATION", "tier_kind must be MAIN or CONSOLATION")
    # Uniqueness of rank within project
    for t in _project_tiers(project_id):
        if t.get("rank") == rank:
            raise api_error("ERR_VALIDATION", f"rank {rank} already used on this project")

    tier = stamp_new({
        "project_id": project_id,
        "rank": rank,
        "gross_amount_cents": gross,
        "tier_kind": tier_kind,
        "winner_submission_id": None,
    })
    db.prize_tiers[tier["id"]] = tier
    return success(tier, status=201)


# --- POST /projects/{id}/review-stages --------------------------------------


@bp.route("/projects/<project_id>/review-stages", methods=["POST"])
def create_review_stage(project_id):
    user_id, _ = require_roles({"Client"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    if project.get("client_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "Clients can only modify their own projects")
    if project.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "review stages can only be added while project is DRAFT")

    body = get_json_body()
    stage_kind = body.get("stage_kind")
    passing_threshold = body.get("passing_threshold")
    reviewer_quorum = body.get("reviewer_quorum")
    rubric = body.get("rubric")
    starts_at_s = body.get("starts_at")
    ends_at_s = body.get("ends_at")

    if stage_kind not in {"PRELIMINARY", "SEMIFINAL", "FINAL"}:
        raise api_error("ERR_VALIDATION", "stage_kind invalid")
    if _stage_by_kind(project_id, stage_kind) is not None:
        raise api_error("ERR_VALIDATION", f"stage {stage_kind} already exists for this project")
    try:
        passing_threshold = float(passing_threshold)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "passing_threshold must be number")
    if not (0.0 <= passing_threshold <= 100.0):
        raise api_error("ERR_VALIDATION", "passing_threshold must be 0..100")
    try:
        reviewer_quorum = int(reviewer_quorum)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "reviewer_quorum must be integer")
    if reviewer_quorum < 3:
        raise api_error("ERR_VALIDATION", "reviewer_quorum must be >= 3")

    if not isinstance(rubric, dict) or not (1 <= len(rubric) <= 8):
        raise api_error("ERR_RUBRIC_WEIGHTS_INVALID", "rubric must have 1..8 entries")
    weight_sum = 0.0
    for code, w in rubric.items():
        if not isinstance(code, str) or not code:
            raise api_error("ERR_RUBRIC_WEIGHTS_INVALID", "rubric keys must be non-empty strings")
        if not isinstance(w, (int, float)) or w < 0:
            raise api_error("ERR_RUBRIC_WEIGHTS_INVALID", "rubric weights must be non-negative numbers")
        weight_sum += float(w)
    # Allow small float-arithmetic noise; spec says sum exactly equal to 100.
    if abs(weight_sum - 100.0) > 1e-6:
        raise api_error("ERR_RUBRIC_WEIGHTS_INVALID", "rubric weights must sum to exactly 100")

    starts_at = parse_iso(starts_at_s)
    ends_at = parse_iso(ends_at_s)
    if not (starts_at and ends_at):
        raise api_error("ERR_VALIDATION", "starts_at/ends_at required")
    if not (starts_at < ends_at):
        raise api_error("ERR_VALIDATION", "starts_at must be < ends_at")

    # Stage overlap check: validate ordering with siblings present so far.
    siblings = _project_stages(project_id)
    candidate = {"stage_kind": stage_kind, "starts_at": format_iso(starts_at), "ends_at": format_iso(ends_at)}
    siblings_plus = siblings + [candidate]
    by_kind = {s.get("stage_kind"): s for s in siblings_plus}
    prelim = by_kind.get("PRELIMINARY")
    semi = by_kind.get("SEMIFINAL")
    final = by_kind.get("FINAL")
    if prelim and semi:
        if parse_iso(prelim["ends_at"]) > parse_iso(semi["starts_at"]):
            raise api_error("ERR_STAGE_OVERLAP", "PRELIMINARY.ends_at must be <= SEMIFINAL.starts_at")
    if semi and final:
        if parse_iso(semi["ends_at"]) > parse_iso(final["starts_at"]):
            raise api_error("ERR_STAGE_OVERLAP", "SEMIFINAL.ends_at must be <= FINAL.starts_at")

    stage = stamp_new({
        "project_id": project_id,
        "stage_kind": stage_kind,
        "passing_threshold": float(passing_threshold),
        "reviewer_quorum": reviewer_quorum,
        "rubric": dict(rubric),
        "starts_at": format_iso(starts_at),
        "ends_at": format_iso(ends_at),
        "status": "PENDING",
        "advancing_submission_ids": [],
    })
    db.review_stages[stage["id"]] = stage
    return success(stage, status=201)


# --- POST /projects/{id}/submit-for-review ----------------------------------


@bp.route("/projects/<project_id>/submit-for-review", methods=["POST"])
def submit_for_review(project_id):
    user_id, _ = require_roles({"Client"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    if project.get("client_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "only project owner can submit for review")
    if project.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "project not in DRAFT")
    body = get_json_body()

    # Validation priority §2.9: prize-pool sum is evaluated after timeline + stage-overlap.
    # Timeline check
    opens_at = parse_iso(project["opens_at"])
    sub_dl = parse_iso(project["submission_deadline"])
    fin_dl = parse_iso(project["final_decision_deadline"])
    _validate_timeline(opens_at, sub_dl, fin_dl)

    # Three stages with starts_at < ends_at, and non-overlapping
    stages = _project_stages(project_id)
    by_kind = {s.get("stage_kind"): s for s in stages}
    if not all(k in by_kind for k in ("PRELIMINARY", "SEMIFINAL", "FINAL")):
        raise api_error("ERR_INVALID_STATE", "project must have PRELIMINARY/SEMIFINAL/FINAL stages")
    for s in stages:
        if parse_iso(s["starts_at"]) >= parse_iso(s["ends_at"]):
            raise api_error("ERR_VALIDATION", "stage starts_at must be < ends_at")
    prelim = by_kind["PRELIMINARY"]
    semi = by_kind["SEMIFINAL"]
    final = by_kind["FINAL"]
    if parse_iso(prelim["ends_at"]) > parse_iso(semi["starts_at"]):
        raise api_error("ERR_STAGE_OVERLAP", "PRELIMINARY.ends_at must be <= SEMIFINAL.starts_at")
    if parse_iso(semi["ends_at"]) > parse_iso(final["starts_at"]):
        raise api_error("ERR_STAGE_OVERLAP", "SEMIFINAL.ends_at must be <= FINAL.starts_at")

    # Prize pool: sum tiers, >= 1 MAIN with rank=1
    tiers = _project_tiers(project_id)
    if not tiers:
        raise api_error("ERR_PRIZE_POOL_MISMATCH", "no prize tiers configured")
    total = sum(int(t["gross_amount_cents"]) for t in tiers)
    if total != int(project["prize_pool_cents"]):
        raise api_error("ERR_PRIZE_POOL_MISMATCH",
                        f"sum of tier amounts {total} does not equal prize_pool_cents {project['prize_pool_cents']}")
    if not any(t["tier_kind"] == "MAIN" and t["rank"] == 1 for t in tiers):
        raise api_error("ERR_INVALID_STATE", "project must include at least one MAIN tier with rank=1")

    check_version(project, body)
    project["status"] = "UNDER_PLATFORM_REVIEW"
    stamp_update(project)
    return success(project)


# --- POST /projects/{id}/approve --------------------------------------------


@bp.route("/projects/<project_id>/approve", methods=["POST"])
def approve_project(project_id):
    require_roles({"PlatformOps"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    if project.get("status") != "UNDER_PLATFORM_REVIEW":
        raise api_error("ERR_INVALID_STATE", "project must be UNDER_PLATFORM_REVIEW to approve")
    body = get_json_body()
    check_version(project, body)
    if get_now() >= parse_iso(project["opens_at"]):
        raise api_error("ERR_INVALID_STATE", "approval must occur strictly before Project.opens_at")
    project["status"] = "ON_SHELF"
    stamp_update(project)
    prelim = _stage_by_kind(project_id, "PRELIMINARY")
    if prelim:
        prelim["status"] = "PENDING"
        stamp_update(prelim)
    return success(project)


# --- POST /projects/{id}/reject ---------------------------------------------


@bp.route("/projects/<project_id>/reject", methods=["POST"])
def reject_project(project_id):
    require_roles({"PlatformOps"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    if project.get("status") != "UNDER_PLATFORM_REVIEW":
        raise api_error("ERR_INVALID_STATE", "project must be UNDER_PLATFORM_REVIEW to reject")
    body = get_json_body()
    check_version(project, body)
    project["status"] = "REJECTED"
    project["reject_reason"] = body.get("reason")
    stamp_update(project)
    return success(project)


# --- POST /projects/{id}/cancel ---------------------------------------------


@bp.route("/projects/<project_id>/cancel", methods=["POST"])
def cancel_project(project_id):
    user_id, role = require_roles({"Client", "PlatformOps"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    body = get_json_body()
    check_version(project, body)

    status = project.get("status")
    if role == "Client":
        if project.get("client_id") != user_id:
            raise api_error("ERR_FORBIDDEN", "Clients can only cancel their own projects")
        if status != "ON_SHELF":
            raise api_error("ERR_INVALID_STATE", "Client cancellation only allowed while ON_SHELF")
        # No submission past DRAFT/WITHDRAWN
        for s in _project_submissions(project_id):
            if s.get("status") not in {"DRAFT", "WITHDRAWN"}:
                raise api_error("ERR_INVALID_STATE",
                                "cannot cancel: there are submissions past DRAFT/WITHDRAWN")
    else:  # PlatformOps
        if status not in {"IN_PRELIMINARY", "ON_SHELF"}:
            raise api_error("ERR_INVALID_STATE", "PlatformOps cancel allowed in IN_PRELIMINARY or ON_SHELF")
        # PlatformOps cancellation in IN_PRELIMINARY requires an upheld PLAGIARISM dispute on this project
        if status == "IN_PRELIMINARY":
            has_upheld = any(
                d.get("project_id") == project_id
                and d.get("dispute_type") == "PLAGIARISM"
                and d.get("status") == "RESOLVED_UPHELD"
                for d in db.disputes.values()
            )
            if not has_upheld:
                raise api_error(
                    "ERR_INVALID_STATE",
                    "PlatformOps cancel from IN_PRELIMINARY requires an UPHELD PLAGIARISM dispute",
                )

    # Cascade: ReviewStages -> EXPIRED, ReviewAssignments -> VOIDED (only active ones)
    project["status"] = "CANCELLED"
    project["cancel_reason"] = body.get("reason")
    stamp_update(project)
    for stage in _project_stages(project_id):
        if stage.get("status") in {"PENDING", "OPEN", "AGGREGATING"}:
            stage["status"] = "EXPIRED"
            stamp_update(stage)
    if status == "IN_PRELIMINARY":
        for asn in db.review_assignments.values():
            stage = db.review_stages.get(asn.get("review_stage_id"))
            if stage and stage.get("project_id") == project_id and asn.get("status") in {"PENDING", "SUBMITTED"}:
                asn["status"] = "VOIDED"
                stamp_update(asn)
                emit_audit(
                    "REVIEW_VOIDED",
                    "SYSTEM",
                    user_id,
                    "REVIEW_ASSIGNMENT",
                    asn["id"],
                    {"reason": "project_cancelled"},
                )
    return success(project)


# --- POST /projects/{id}/award -----------------------------------------------


@bp.route("/projects/<project_id>/award", methods=["POST"])
def award_project(project_id):
    user_id, _ = require_roles({"PlatformOps"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    if project.get("status") != "IN_FINAL":
        raise api_error("ERR_INVALID_STATE", "project must be IN_FINAL to award")
    final_stage = _stage_by_kind(project_id, "FINAL")
    if not final_stage or final_stage.get("status") != "AGGREGATING":
        raise api_error("ERR_INVALID_STATE", "FINAL stage must be AGGREGATING")

    body = get_json_body()
    check_version(project, body)
    tier_assignments = body.get("tier_assignments")
    if not isinstance(tier_assignments, list) or not tier_assignments:
        raise api_error("ERR_VALIDATION", "tier_assignments required as non-empty list")

    tiers = _project_tiers(project_id)
    tiers_by_id = {t["id"]: t for t in tiers}
    if set(t["id"] for t in tiers) != set(item.get("prize_tier_id") for item in tier_assignments):
        raise api_error("ERR_INVALID_STATE", "every PrizeTier must have a winning submission")
    if len(tier_assignments) != len(tiers):
        raise api_error("ERR_INVALID_STATE", "duplicate or missing tier assignments")

    # Validate each entry references existing tier (on this project) and a submission
    submission_by_id = {}
    for item in tier_assignments:
        tid = item.get("prize_tier_id")
        sid = item.get("submission_id")
        if tid not in tiers_by_id:
            raise api_error("ERR_FK_NOT_FOUND", f"prize_tier_id {tid} not found in this project")
        sub = db.submissions.get(sid)
        if not sub or sub.get("project_id") != project_id:
            raise api_error("ERR_FK_NOT_FOUND", f"submission_id {sid} not found in this project")
        if sub.get("status") != "ADVANCING_FINAL":
            raise api_error("ERR_INVALID_STATE", f"submission {sid} not ADVANCING_FINAL")
        submission_by_id[sid] = sub

    # ERR_DISPUTE_PENDING if any DISPUTED assignment on any ADVANCING_FINAL submission
    advancing_final_ids = {s["id"] for s in _project_submissions(project_id) if s.get("status") == "ADVANCING_FINAL"}
    for asn in db.review_assignments.values():
        if asn.get("status") == "DISPUTED":
            stage = db.review_stages.get(asn.get("review_stage_id"))
            if stage and stage.get("project_id") == project_id and asn.get("submission_id") in advancing_final_ids:
                raise api_error("ERR_DISPUTE_PENDING", "DISPUTED assignment exists on final-stage submission")

    now_iso = format_iso(get_now())
    project["status"] = "AWARDED"
    project["anonymity_unmasked_at"] = now_iso

    # Order winner list by tier rank ascending.
    ordered = sorted(tier_assignments, key=lambda x: tiers_by_id[x["prize_tier_id"]]["rank"])
    project["published_winner_list"] = [item["submission_id"] for item in ordered]
    stamp_update(project)

    final_stage["status"] = "PUBLISHED"
    stamp_update(final_stage)

    selected_ids = set(submission_by_id.keys())

    # First: flip selected submissions to WINNER/RUNNER_UP and pin prize_tier_id.
    for item in tier_assignments:
        tid = item["prize_tier_id"]
        sid = item["submission_id"]
        tier = tiers_by_id[tid]
        sub = submission_by_id[sid]
        sub["prize_tier_id"] = tid
        sub["status"] = "WINNER" if tier["tier_kind"] == "MAIN" else "RUNNER_UP"
        stamp_update(sub)
        tier["winner_submission_id"] = sid
        stamp_update(tier)

    # All other ADVANCING_FINAL submissions -> ELIMINATED
    for s in _project_submissions(project_id):
        if s.get("status") == "ADVANCING_FINAL" and s["id"] not in selected_ids:
            s["status"] = "ELIMINATED"
            stamp_update(s)

    # Recompute originality (FINAL_CROSSCHECK) for winners/runners
    cat = db.design_categories.get(db.design_categories_by_code.get(project["category_code"]))
    corpus_id = cat.get("similarity_corpus_id") if cat else ""
    eligible_peers = [
        s for s in _project_submissions(project_id)
        if s.get("status") in {"WINNER", "RUNNER_UP", "ADVANCING_FINAL"}
    ]
    for sid in selected_ids:
        sub = db.submissions[sid]
        peers = [p["asset_urls"] for p in eligible_peers if p["id"] != sid]
        public_sim = public_similarity(sub.get("asset_urls", []), corpus_id)
        peer_sim = peer_similarity(sub.get("asset_urls", []), peers)
        sub["originality_score"] = originality_score_final(public_sim, peer_sim)
        sub["originality_variant"] = "FINAL_CROSSCHECK"
        stamp_update(sub)

    # Auto-create CopyrightTransfer (DRAFTED) and PrizePayment (SCHEDULED) for each winner
    for item in tier_assignments:
        tid = item["prize_tier_id"]
        sid = item["submission_id"]
        tier = tiers_by_id[tid]
        sub = submission_by_id[sid]
        designer = db.designers[sub["designer_id"]]

        transfer = stamp_new({
            "project_id": project_id,
            "submission_id": sid,
            "scope": "FULL",
            "usage_rights": [],
            "signers": [
                {"party_kind": "CLIENT", "party_id": project["client_id"], "signed_at": None},
                {"party_kind": "DESIGNER", "party_id": sub["designer_id"], "signed_at": None},
                {"party_kind": "PLATFORM_NOTARY", "party_id": None, "signed_at": None},
            ],
            "status": "DRAFTED",
            "registration_ref": None,
            "registered_at": None,
        })
        db.copyright_transfers[transfer["id"]] = transfer

        amounts = compute_withholding(tier["gross_amount_cents"], designer["tax_residency"])
        payment = stamp_new({
            "project_id": project_id,
            "prize_tier_id": tid,
            "designer_id": sub["designer_id"],
            "gross_amount_cents": amounts["gross_amount_cents"],
            "withholding_cents": amounts["withholding_cents"],
            "net_amount_cents": amounts["net_amount_cents"],
            "status": "SCHEDULED",
            "external_payment_ref": None,
            "idempotency_key": None,
        })
        db.prize_payments[payment["id"]] = payment

    return success(project)


# --- POST /projects/{id}/close ----------------------------------------------


@bp.route("/projects/<project_id>/close", methods=["POST"])
def close_project(project_id):
    require_roles({"PlatformOps"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    if project.get("status") != "AWARDED":
        raise api_error("ERR_INVALID_STATE", "project must be AWARDED to close")
    body = get_json_body()
    check_version(project, body)

    # All PrizePayment in {PAID, REVERSED}
    for p in db.prize_payments.values():
        if p.get("project_id") == project_id and p.get("status") not in {"PAID", "REVERSED"}:
            raise api_error("ERR_INVALID_STATE", "all PrizePayment rows must be PAID or REVERSED")
    # All CopyrightTransfer in {REGISTERED, VOIDED}
    for t in db.copyright_transfers.values():
        if t.get("project_id") == project_id and t.get("status") not in {"REGISTERED", "VOIDED"}:
            raise api_error("ERR_INVALID_STATE", "all CopyrightTransfer rows must be REGISTERED or VOIDED")
    # All open disputes in resolved terminal state
    for d in db.disputes.values():
        if d.get("project_id") == project_id and d.get("status") not in {
            "RESOLVED_UPHELD", "RESOLVED_REJECTED", "WITHDRAWN",
        }:
            raise api_error("ERR_INVALID_STATE", "all disputes must be in a resolved terminal state")

    project["status"] = "CLOSED"
    stamp_update(project)
    return success(project)
