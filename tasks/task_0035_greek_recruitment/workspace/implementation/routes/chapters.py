from __future__ import annotations

"""Chapter routes."""
from flask import Blueprint, request

import db
import errors as E
import response
import serializers as S
from middleware import require_auth
from services import chapter_service as cs
from services import pagination as P
from services import validation as V


bp = Blueprint("chapters", __name__)


GREEK_TYPES = {"SORORITY", "FRATERNITY"}


def _chapter_or_404(chapter_id: str) -> dict:
    if chapter_id not in db.chapters:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"Chapter {chapter_id} not found")
    return db.chapters[chapter_id]


@bp.route("/rush/chapters", methods=["POST"])
@require_auth(["PanhellenicAdmin"])
def create_chapter():
    body = request.get_json(silent=True) or {}

    name = V.require_string(body, "name", min_len=1, max_len=80)
    greek_type = V.require_enum(body, "greek_type", GREEK_TYPES)
    quota_total = V.require_int(body, "quota_total", min_val=1)
    dues = V.require_int(body, "dues_per_member_cents", min_val=0)
    legacy_slots = V.require_int(body, "legacy_priority_slots", min_val=0)
    if legacy_slots > quota_total:
        raise E.APIError(
            E.ERR_INVALID_REQUEST,
            "legacy_priority_slots must be <= quota_total",
        )

    # Uniqueness (case-insensitive) on name.
    for c in db.chapters.values():
        if c["name"].lower() == name.lower():
            raise E.APIError(E.ERR_INVALID_REQUEST, "Chapter name must be unique")

    now = db.now_utc()
    cid = db.new_id()
    chapter = {
        "id": cid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "name": name,
        "greek_type": greek_type,
        "quota_total": quota_total,
        "dues_per_member_cents": dues,
        "legacy_priority_slots": legacy_slots,
        "risk_status": "GOOD_STANDING",
        "risk_points": 0,
        "pledged_count": 0,
        "legacy_pledged_count": 0,
        "dues_balance_cents": 0,
    }
    db.chapters[cid] = chapter
    return response.success_object(S.chapter(chapter), status=201)


@bp.route("/rush/chapters/<chapter_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "RiskOfficer", "PNM"])
def get_chapter(chapter_id):
    c = _chapter_or_404(chapter_id)
    return response.success_object(S.chapter(c))


@bp.route("/rush/chapters", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "RiskOfficer", "PNM"])
def list_chapters():
    limit, offset = P.parse_limit_offset()
    greek_type = request.args.get("greek_type")
    rows = list(db.chapters.values())
    if greek_type is not None:
        rows = [c for c in rows if c["greek_type"] == greek_type]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.chapter(c) for c in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/chapters/<chapter_id>", methods=["PUT"])
@require_auth(["PanhellenicAdmin"])
def update_chapter(chapter_id):
    c = _chapter_or_404(chapter_id)
    body = request.get_json(silent=True) or {}

    new_dues = V.optional_int(body, "dues_per_member_cents", min_val=0)
    new_quota = V.optional_int(body, "quota_total", min_val=1)
    new_legacy = V.optional_int(body, "legacy_priority_slots", min_val=0)

    # Compute effective values to apply post-validation.
    eff_quota = new_quota if new_quota is not None else c["quota_total"]
    eff_legacy = new_legacy if new_legacy is not None else c["legacy_priority_slots"]
    if eff_legacy > eff_quota:
        raise E.APIError(
            E.ERR_INVALID_REQUEST,
            "legacy_priority_slots must be <= quota_total",
        )

    changed = False
    if new_dues is not None and new_dues != c["dues_per_member_cents"]:
        c["dues_per_member_cents"] = new_dues
        changed = True
    if new_quota is not None and new_quota != c["quota_total"]:
        c["quota_total"] = new_quota
        changed = True
    if new_legacy is not None and new_legacy != c["legacy_priority_slots"]:
        c["legacy_priority_slots"] = new_legacy
        changed = True

    if changed:
        cs.bump_chapter_version(chapter_id)
    return response.success_object(S.chapter(c))


@bp.route("/rush/chapters/<chapter_id>/parties", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "RiskOfficer", "PNM"])
def list_chapter_parties(chapter_id):
    _chapter_or_404(chapter_id)
    limit, offset = P.parse_limit_offset()
    round_id = request.args.get("round_id")
    status = request.args.get("status")
    rows = [p for p in db.parties.values() if p["chapter_id"] == chapter_id]
    if round_id is not None:
        rows = [p for p in rows if p["round_id"] == round_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.party(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/chapters/<chapter_id>/risk-incidents", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RiskOfficer"])
def list_chapter_risk_incidents(chapter_id):
    _chapter_or_404(chapter_id)
    limit, offset = P.parse_limit_offset()
    status = request.args.get("status")
    rows = [r for r in db.risk_incidents.values() if r["chapter_id"] == chapter_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.risk_incident(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/chapters/<chapter_id>/dues-ledger", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer"])
def list_chapter_dues_ledger(chapter_id):
    _chapter_or_404(chapter_id)
    limit, offset = P.parse_limit_offset()
    # Recompute running balances to keep MODE A reconciled with MODE B.
    cs.recompute_running_balances(chapter_id)
    rows = [e for e in db.dues_ledger_entries.values() if e["chapter_id"] == chapter_id]
    rows.sort(key=lambda e: (e["created_at"], e["_insertion_seq"]))
    page = rows[offset:offset + limit]
    total = len(rows)
    return response.success_array(
        [S.dues_ledger_entry(e) for e in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/chapters/<chapter_id>/preferences", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer"])
def list_chapter_preferences(chapter_id):
    _chapter_or_404(chapter_id)
    limit, offset = P.parse_limit_offset()
    side = request.args.get("side")
    round_id = request.args.get("round_id")
    rows = [p for p in db.preferences.values() if p["chapter_id"] == chapter_id]
    if side is not None:
        rows = [p for p in rows if p["side"] == side]
    if round_id is not None:
        rows = [p for p in rows if p["round_id"] == round_id]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.preference(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )
