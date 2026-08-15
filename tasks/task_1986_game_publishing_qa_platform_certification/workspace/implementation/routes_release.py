"""Age-rating filings, localization packs, release windows, blackout windows, hotfixes."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import require_role
from response import success_object, success_list
import helpers as H

bp = Blueprint("release", __name__)

PLATFORMS = ("PS5", "XSX", "SWITCH2", "PC")
TERRITORIES = ("ESRB", "PEGI", "CERO", "USK")
WINDOW_KINDS = ("LAUNCH", "DAY_ONE_PATCH", "HOTFIX_DEPLOY")

TERRITORY_FEE_CENTS = {"ESRB": 40000, "PEGI": 25000, "CERO": 18000, "USK": 15000}
WINDOW_RATE_CENTS_PER_HOUR = 5000
HOTFIX_CERT_FEE_CENTS = 50000
HOTFIX_QUOTA_MAX = 2
QUOTA_WINDOW_DAYS = 30


def _body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400)
    return b


def _req_str(b, field):
    v = b.get(field)
    if v is None or not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is required and must be a string.", 400)
    return v


ALL_ROLES = ("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
             "PlatformReviewer", "ComplianceManager", "PlatformAdmin")


# ---------------- age-rating filings ----------------

@bp.route("/qa-cert/age-rating-filings", methods=["POST"])
def create_filing():
    require_role("ReleaseManager")
    b = _body()
    title_id = _req_str(b, "title_id")
    t = db.titles.get(title_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    territory = _req_str(b, "territory")
    if territory not in TERRITORIES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown territory.", 400)
    descriptors = b.get("content_descriptors")
    if not isinstance(descriptors, list) or len(descriptors) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "content_descriptors must be a non-empty array.", 400)
    for f in db.filings.values():
        if f["title_id"] == title_id and f["territory"] == territory and \
                f["status"] in ("DRAFT", "FILED"):
            raise ApiError("ERR_DUPLICATE_FILING",
                           "A DRAFT or FILED filing already exists for (title, territory).", 409)
    f = {
        "title_id": title_id,
        "territory": territory,
        "content_descriptors": descriptors,
        "fee_cents": None,
        "filed_at": None,
        "status": "DRAFT",
    }
    H.init_common(f)
    db.filings[f["id"]] = f
    return success_object(H.public(f), 201)


@bp.route("/qa-cert/age-rating-filings/<filingId>", methods=["GET"])
def get_filing(filingId):
    require_role(*ALL_ROLES)
    f = db.filings.get(filingId)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Filing not found.", 404)
    return success_object(H.public(f))


@bp.route("/qa-cert/age-rating-filings", methods=["GET"])
def list_filings():
    require_role(*ALL_ROLES)
    title_id = request.args.get("title_id")
    territory = request.args.get("territory")
    status = request.args.get("status")
    items = list(db.filings.values())
    if title_id is not None:
        items = [f for f in items if f["title_id"] == title_id]
    if territory is not None:
        items = [f for f in items if f["territory"] == territory]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(f) for f in page], limit, offset, total)


@bp.route("/qa-cert/age-rating-filings/<filingId>/transition", methods=["POST"])
def filing_transition(filingId):
    user_id, role = require_role("ReleaseManager", "PlatformReviewer")
    f = db.filings.get(filingId)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Filing not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("FILED", "GRANTED", "CHALLENGED", "DRAFT"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    if to_status in ("FILED", "DRAFT") and role != "ReleaseManager":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only ReleaseManager may file or amend.", 403)
    if to_status in ("GRANTED", "CHALLENGED") and role != "PlatformReviewer":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only PlatformReviewer may decide filings.", 403)
    cur = f["status"]
    if to_status == "FILED":
        if cur != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Filing must be DRAFT.", 409)
        t = db.titles.get(f["title_id"])
        if t["status"] == "SUNSET":
            raise ApiError("ERR_INVALID_STATE", "Title must not be SUNSET.", 409)
        base = TERRITORY_FEE_CENTS[f["territory"]]
        other_active = sum(1 for x in db.filings.values()
                           if x["title_id"] == f["title_id"] and x["id"] != f["id"]
                           and x["status"] in ("FILED", "GRANTED"))
        discount = Decimal("0.10") if other_active >= 2 else Decimal("0.00")
        fee = int((Decimal(base) * (Decimal(1) - discount)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        view = H.title_view(t)
        if view["cert_budget_available_cents"] < fee:
            raise ApiError("ERR_CERT_BUDGET_EXCEEDED", "Budget does not cover the fee.", 402)
        f["fee_cents"] = fee
        f["filed_at"] = H.clock_iso()
        f["status"] = "FILED"
        H.touch(f)
    elif to_status == "GRANTED":
        if cur != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Filing must be FILED.", 409)
        f["status"] = "GRANTED"
        H.touch(f)
    elif to_status == "CHALLENGED":
        if cur != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Filing must be FILED.", 409)
        f["status"] = "CHALLENGED"
        H.touch(f)
    elif to_status == "DRAFT":
        if cur != "CHALLENGED":
            raise ApiError("ERR_INVALID_STATE", "Filing must be CHALLENGED.", 409)
        descriptors = b.get("content_descriptors")
        if not isinstance(descriptors, list) or len(descriptors) == 0:
            raise ApiError("ERR_INVALID_REQUEST", "content_descriptors must be non-empty.", 400)
        f["content_descriptors"] = descriptors
        f["fee_cents"] = None
        f["status"] = "DRAFT"
        H.touch(f)
    return success_object(H.public(f))


# ---------------- localization packs ----------------

@bp.route("/qa-cert/localization-packs", methods=["POST"])
def create_pack():
    require_role("ReleaseManager")
    b = _body()
    title_id = _req_str(b, "title_id")
    t = db.titles.get(title_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    locale = _req_str(b, "locale")
    is_required = b.get("is_required")
    if not isinstance(is_required, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_required must be a boolean.", 400)
    text_total = b.get("text_asset_total")
    audio_total = b.get("audio_asset_total")
    if not isinstance(text_total, int) or isinstance(text_total, bool) or text_total < 0:
        raise ApiError("ERR_INVALID_REQUEST", "text_asset_total must be an integer >= 0.", 400)
    if not isinstance(audio_total, int) or isinstance(audio_total, bool) or audio_total < 0:
        raise ApiError("ERR_INVALID_REQUEST", "audio_asset_total must be an integer >= 0.", 400)
    for pk in db.packs.values():
        if pk["title_id"] == title_id and pk["locale"] == locale:
            raise ApiError("ERR_DUPLICATE_LOCALE", "A pack already exists for (title, locale).", 409)
    pk = {
        "title_id": title_id,
        "locale": locale,
        "is_required": is_required,
        "text_asset_total": text_total,
        "audio_asset_total": audio_total,
        "translated_text_assets": 0,
        "translated_audio_assets": 0,
        "translation_status": "DRAFT",
        "signoff_status": "UNSIGNED",
    }
    H.init_common(pk)
    db.packs[pk["id"]] = pk
    return success_object(H.pack_view(pk), 201)


@bp.route("/qa-cert/localization-packs/<packId>", methods=["GET"])
def get_pack(packId):
    require_role(*ALL_ROLES)
    pk = db.packs.get(packId)
    if pk is None:
        raise ApiError("ERR_NOT_FOUND", "Localization pack not found.", 404)
    return success_object(H.pack_view(pk))


@bp.route("/qa-cert/localization-packs", methods=["GET"])
def list_packs():
    require_role(*ALL_ROLES)
    title_id = request.args.get("title_id")
    translation_status = request.args.get("translation_status")
    items = list(db.packs.values())
    if title_id is not None:
        items = [p for p in items if p["title_id"] == title_id]
    if translation_status is not None:
        items = [p for p in items if p["translation_status"] == translation_status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.pack_view(p) for p in page], limit, offset, total)


@bp.route("/qa-cert/localization-packs/<packId>/transition", methods=["POST"])
def pack_transition(packId):
    user_id, role = require_role("ReleaseManager", "QALead")
    pk = db.packs.get(packId)
    if pk is None:
        raise ApiError("ERR_NOT_FOUND", "Localization pack not found.", 404)
    b = _body()
    axis = _req_str(b, "axis")
    to_status = _req_str(b, "to_status")
    if axis not in ("TRANSLATION", "SIGNOFF"):
        raise ApiError("ERR_INVALID_REQUEST", "axis must be TRANSLATION or SIGNOFF.", 400)
    if axis == "TRANSLATION" and role != "ReleaseManager":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only ReleaseManager may advance the translation axis.", 403)
    if axis == "SIGNOFF" and role != "QALead":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only QALead may advance the signoff axis.", 403)
    if axis == "SIGNOFF":
        if to_status != "SIGNED":
            raise ApiError("ERR_INVALID_REQUEST", "SIGNOFF axis only supports SIGNED.", 400)
        if pk["signoff_status"] != "UNSIGNED":
            raise ApiError("ERR_INVALID_STATE", "Pack must be UNSIGNED.", 409)
        pk["signoff_status"] = "SIGNED"
        H.touch(pk)
        return success_object(H.pack_view(pk))
    # TRANSLATION axis
    if to_status not in ("TRANSLATING", "LQA", "LOCKED"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    legal = {
        ("DRAFT", "TRANSLATING"),
        ("TRANSLATING", "LQA"),
        ("LQA", "TRANSLATING"),
        ("LQA", "LOCKED"),
    }
    cur = pk["translation_status"]
    if (cur, to_status) not in legal:
        raise ApiError("ERR_INVALID_STATE", "Illegal translation-axis transition.", 409)
    # apply optional counts first
    tt = b.get("translated_text_assets")
    ta = b.get("translated_audio_assets")
    if tt is not None:
        if not isinstance(tt, int) or isinstance(tt, bool) or tt < 0:
            raise ApiError("ERR_INVALID_REQUEST", "translated_text_assets must be an integer >= 0.", 400)
        pk["translated_text_assets"] = tt
    if ta is not None:
        if not isinstance(ta, int) or isinstance(ta, bool) or ta < 0:
            raise ApiError("ERR_INVALID_REQUEST", "translated_audio_assets must be an integer >= 0.", 400)
        pk["translated_audio_assets"] = ta
    if to_status == "LOCKED":
        view = H.pack_view(pk)
        if view["text_coverage_pct"] < 98.00 or view["audio_coverage_pct"] < 95.00:
            raise ApiError("ERR_COVERAGE_BELOW_LOCK_THRESHOLD",
                           "LOCK requires text >= 98.00 and audio >= 95.00.", 409)
    pk["translation_status"] = to_status
    H.touch(pk)
    return success_object(H.pack_view(pk))


# ---------------- release windows ----------------

@bp.route("/qa-cert/release-windows", methods=["POST"])
def create_window():
    require_role("ReleaseManager")
    b = _body()
    title_id = _req_str(b, "title_id")
    t = db.titles.get(title_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    platform_code = _req_str(b, "platform_code")
    if platform_code not in PLATFORMS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown platform_code.", 400)
    kind = _req_str(b, "kind")
    if kind not in WINDOW_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown kind.", 400)
    start = H.parse_iso_dt(_req_str(b, "start_utc"), "start_utc")
    end = H.parse_iso_dt(_req_str(b, "end_utc"), "end_utc")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "end_utc must be strictly after start_utc.", 400)
    now = db.clock
    if start <= now:
        raise ApiError("ERR_WINDOW_IN_PAST", "Window start_utc must be strictly after the logical clock.", 400)
    for w in db.windows.values():
        if w["platform_code"] == platform_code and w["status"] in ("RESERVED", "CONFIRMED"):
            if w["_start"] < end and start < w["_end"]:
                raise ApiError("ERR_WINDOW_OVERLAP",
                               "Half-open overlap with an existing RESERVED/CONFIRMED window.", 409)
    w = {
        "title_id": title_id,
        "platform_code": platform_code,
        "kind": kind,
        "start_utc": _fmt_dt(start),
        "end_utc": _fmt_dt(end),
        "fee_cents": None,
        "status": "RESERVED",
        "_start": start,
        "_end": end,
    }
    H.init_common(w)
    db.windows[w["id"]] = w
    return success_object(H.public(w), 201)


def _fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _window_hours(w):
    return int((w["_end"] - w["_start"]).total_seconds() // 3600)


@bp.route("/qa-cert/release-windows/<windowId>", methods=["GET"])
def get_window(windowId):
    require_role(*ALL_ROLES)
    w = db.windows.get(windowId)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "Release window not found.", 404)
    return success_object(H.public(w))


@bp.route("/qa-cert/release-windows", methods=["GET"])
def list_windows():
    require_role(*ALL_ROLES)
    title_id = request.args.get("title_id")
    platform_code = request.args.get("platform_code")
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = list(db.windows.values())
    if title_id is not None:
        items = [w for w in items if w["title_id"] == title_id]
    if platform_code is not None:
        items = [w for w in items if w["platform_code"] == platform_code]
    if kind is not None:
        items = [w for w in items if w["kind"] == kind]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(w) for w in page], limit, offset, total)


@bp.route("/qa-cert/release-windows/<windowId>/transition", methods=["POST"])
def window_transition(windowId):
    require_role("ReleaseManager")
    w = db.windows.get(windowId)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "Release window not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("CONFIRMED", "CONSUMED", "RELEASED"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    cur = w["status"]
    t = db.titles.get(w["title_id"])
    if to_status == "CONFIRMED":
        if cur != "RESERVED":
            raise ApiError("ERR_INVALID_STATE", "Window must be RESERVED.", 409)
        if w["kind"] in ("LAUNCH", "DAY_ONE_PATCH"):
            if t["status"] != "CERT_APPROVED":
                raise ApiError("ERR_TITLE_NOT_CERT_APPROVED",
                               "LAUNCH/DAY_ONE_PATCH confirm requires CERT_APPROVED.", 409)
        elif w["kind"] == "HOTFIX_DEPLOY":
            if t["status"] != "LAUNCHED":
                raise ApiError("ERR_TITLE_NOT_LAUNCHED",
                               "HOTFIX_DEPLOY confirm requires LAUNCHED.", 409)
        # demand fee per pinned order
        window_hours = _window_hours(w)
        week_monday = H.week_monday_of(w["_start"])
        next_monday = week_monday + timedelta(days=7)
        existing = 0
        for other in db.windows.values():
            if other["id"] != w["id"] and other["platform_code"] == w["platform_code"] and \
                    other["status"] in ("RESERVED", "CONFIRMED"):
                o_monday = H.week_monday_of(other["_start"])
                if o_monday == week_monday:
                    existing += _window_hours(other)
        total_hours = existing + window_hours
        if total_hours < 40:
            mult = Decimal("1.00")
        elif total_hours < 100:
            mult = Decimal("1.25")
        else:
            mult = Decimal("1.50")
        fee = int((Decimal(window_hours) * Decimal(WINDOW_RATE_CENTS_PER_HOUR) * mult).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        view = H.title_view(t)
        if view["cert_budget_available_cents"] < fee:
            raise ApiError("ERR_CERT_BUDGET_EXCEEDED", "Budget does not cover the fee.", 402)
        w["fee_cents"] = fee
        w["status"] = "CONFIRMED"
        H.touch(w)
    elif to_status == "CONSUMED":
        if cur != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", "Window must be CONFIRMED.", 409)
        if db.clock < w["_start"]:
            raise ApiError("ERR_INVALID_STATE",
                           "Logical clock must be >= start_utc to consume.", 409)
        w["status"] = "CONSUMED"
        H.touch(w)
    elif to_status == "RELEASED":
        if cur not in ("RESERVED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", "Window must be RESERVED or CONFIRMED.", 409)
        w["status"] = "RELEASED"
        H.touch(w)
    return success_object(H.public(w))


# ---------------- blackout windows ----------------

@bp.route("/qa-cert/cert-blackout-windows", methods=["POST"])
def create_blackout():
    require_role("PlatformAdmin")
    b = _body()
    platform_code = _req_str(b, "platform_code")
    if platform_code not in PLATFORMS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown platform_code.", 400)
    start = H.parse_iso_dt(_req_str(b, "start_utc"), "start_utc")
    end = H.parse_iso_dt(_req_str(b, "end_utc"), "end_utc")
    buffer_hours = b.get("buffer_hours")
    if not isinstance(buffer_hours, int) or isinstance(buffer_hours, bool) or \
            buffer_hours < 0 or buffer_hours > 168:
        raise ApiError("ERR_INVALID_REQUEST", "buffer_hours must be an integer in 0..168.", 400)
    reason = _req_str(b, "reason")
    if end < start:
        raise ApiError("ERR_INVALID_REQUEST", "end_utc must be >= start_utc.", 400)
    w = {
        "platform_code": platform_code,
        "start_utc": _fmt_dt(start),
        "end_utc": _fmt_dt(end),
        "buffer_hours": buffer_hours,
        "reason": reason,
        "_start": start,
        "_end": end,
    }
    H.init_common(w)
    db.blackouts[w["id"]] = w
    return success_object(H.public(w), 201)


@bp.route("/qa-cert/cert-blackout-windows/<windowId>", methods=["GET"])
def get_blackout(windowId):
    require_role(*ALL_ROLES)
    w = db.blackouts.get(windowId)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "Blackout window not found.", 404)
    return success_object(H.public(w))


@bp.route("/qa-cert/cert-blackout-windows", methods=["GET"])
def list_blackouts():
    require_role(*ALL_ROLES)
    platform_code = request.args.get("platform_code")
    items = list(db.blackouts.values())
    if platform_code is not None:
        items = [w for w in items if w["platform_code"] == platform_code]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(w) for w in page], limit, offset, total)


@bp.route("/qa-cert/cert-blackout-windows/<windowId>", methods=["DELETE"])
def delete_blackout(windowId):
    require_role("PlatformAdmin")
    w = db.blackouts.get(windowId)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "Blackout window not found.", 404)
    del db.blackouts[windowId]
    return "", 204


# ---------------- hotfixes ----------------

@bp.route("/qa-cert/hotfixes", methods=["POST"])
def create_hotfix():
    require_role("ReleaseManager")
    b = _body()
    title_id = _req_str(b, "title_id")
    t = db.titles.get(title_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    platform_code = _req_str(b, "platform_code")
    if platform_code not in PLATFORMS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown platform_code.", 400)
    build_id = _req_str(b, "build_id")
    bd = db.builds.get(build_id)
    if bd is None:
        raise ApiError("ERR_NOT_FOUND", "Build not found.", 404)
    severity = _req_str(b, "severity")
    if severity not in ("S1", "S2"):
        raise ApiError("ERR_INVALID_REQUEST", "severity must be S1 or S2.", 400)
    incident_summary = _req_str(b, "incident_summary")
    if t["status"] != "LAUNCHED":
        raise ApiError("ERR_TITLE_NOT_LAUNCHED", "Title must be LAUNCHED.", 409)
    if t["embargoed"]:
        raise ApiError("ERR_TITLE_UNDER_EMBARGO", "Title is under embargo.", 403)
    if bd["title_id"] != t["id"]:
        raise ApiError("ERR_BUILD_TITLE_MISMATCH", "Build belongs to a different title.", 422)
    if bd["platform_code"] != platform_code:
        raise ApiError("ERR_BUILD_PLATFORM_MISMATCH", "Build targets a different platform.", 422)
    h = {
        "title_id": title_id,
        "platform_code": platform_code,
        "build_id": build_id,
        "severity": severity,
        "incident_summary": incident_summary,
        "fee_cents": None,
        "expedited_cert_entered_at": None,
        "status": "DECLARED",
    }
    H.init_common(h)
    db.hotfixes[h["id"]] = h
    return success_object(H.public(h), 201)


@bp.route("/qa-cert/hotfixes/<hotfixId>", methods=["GET"])
def get_hotfix(hotfixId):
    require_role(*ALL_ROLES)
    h = db.hotfixes.get(hotfixId)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", "Hotfix not found.", 404)
    return success_object(H.public(h))


@bp.route("/qa-cert/hotfixes", methods=["GET"])
def list_hotfixes():
    require_role(*ALL_ROLES)
    title_id = request.args.get("title_id")
    status = request.args.get("status")
    build_id = request.args.get("build_id")
    items = list(db.hotfixes.values())
    if title_id is not None:
        items = [h for h in items if h["title_id"] == title_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    if build_id is not None:
        items = [h for h in items if h["build_id"] == build_id]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(h) for h in page], limit, offset, total)


@bp.route("/qa-cert/hotfixes/<hotfixId>/transition", methods=["POST"])
def hotfix_transition(hotfixId):
    user_id, role = require_role("ReleaseManager", "PlatformReviewer")
    h = db.hotfixes.get(hotfixId)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", "Hotfix not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("IN_DEV", "READY_FOR_CERT", "EXPEDITED_CERT", "DEPLOYED", "ROLLED_BACK"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    rm_targets = ("IN_DEV", "READY_FOR_CERT", "DEPLOYED", "ROLLED_BACK")
    if to_status in rm_targets and role != "ReleaseManager":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only ReleaseManager may perform this hotfix transition.", 403)
    if to_status == "EXPEDITED_CERT" and role != "PlatformReviewer":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only PlatformReviewer may enter EXPEDITED_CERT.", 403)
    cur = h["status"]
    t = db.titles.get(h["title_id"])
    if to_status == "IN_DEV":
        if cur != "DECLARED":
            raise ApiError("ERR_INVALID_STATE", "Hotfix must be DECLARED.", 409)
        h["status"] = "IN_DEV"
        H.touch(h)
    elif to_status == "READY_FOR_CERT":
        if cur != "IN_DEV":
            raise ApiError("ERR_INVALID_STATE", "Hotfix must be IN_DEV.", 409)
        bd = db.builds.get(h["build_id"])
        if bd is None or bd["status"] not in ("TEST_PASSED", "CANDIDATE"):
            raise ApiError("ERR_FIX_BUILD_NOT_QUALIFIED",
                           "Fix build must be TEST_PASSED or CANDIDATE.", 409)
        h["status"] = "READY_FOR_CERT"
        H.touch(h)
    elif to_status == "EXPEDITED_CERT":
        if cur != "READY_FOR_CERT":
            raise ApiError("ERR_INVALID_STATE", "Hotfix must be READY_FOR_CERT.", 409)
        now = db.clock
        if h["severity"] == "S1":
            lower = now - timedelta(days=QUOTA_WINDOW_DAYS)
            count = 0
            for x in db.hotfixes.values():
                if x["title_id"] == h["title_id"] and x["severity"] == "S1" and \
                        x.get("_expedited_at") is not None:
                    if lower < x["_expedited_at"] <= now:
                        count += 1
            if count >= HOTFIX_QUOTA_MAX:
                raise ApiError("ERR_HOTFIX_QUOTA_EXCEEDED",
                               "Two S1 hotfixes already entered EXPEDITED_CERT within 30 days.", 409)
        covering = None
        for w in db.windows.values():
            if w["title_id"] == h["title_id"] and w["platform_code"] == h["platform_code"] and \
                    w["kind"] == "HOTFIX_DEPLOY" and w["status"] == "CONFIRMED" and \
                    w["_start"] <= now < w["_end"]:
                covering = w
                break
        if covering is None:
            raise ApiError("ERR_NO_HOTFIX_WINDOW",
                           "No CONFIRMED HOTFIX_DEPLOY window covers the current logical time.", 409)
        view = H.title_view(t)
        if view["cert_budget_available_cents"] < HOTFIX_CERT_FEE_CENTS:
            raise ApiError("ERR_CERT_BUDGET_EXCEEDED", "Budget does not cover the fee.", 402)
        h["fee_cents"] = HOTFIX_CERT_FEE_CENTS
        h["expedited_cert_entered_at"] = H.clock_iso()
        h["_expedited_at"] = now
        h["status"] = "EXPEDITED_CERT"
        H.touch(h)
    elif to_status == "DEPLOYED":
        if cur != "EXPEDITED_CERT":
            raise ApiError("ERR_INVALID_STATE", "Hotfix must be EXPEDITED_CERT.", 409)
        h["status"] = "DEPLOYED"
        H.touch(h)
        # consume the covering CONFIRMED HOTFIX_DEPLOY window
        now = db.clock
        for w in db.windows.values():
            if w["title_id"] == h["title_id"] and w["platform_code"] == h["platform_code"] and \
                    w["kind"] == "HOTFIX_DEPLOY" and w["status"] == "CONFIRMED" and \
                    w["_start"] <= now < w["_end"]:
                w["status"] = "CONSUMED"
                H.touch(w)
                break
    elif to_status == "ROLLED_BACK":
        if cur != "DEPLOYED":
            raise ApiError("ERR_INVALID_STATE", "Hotfix must be DEPLOYED.", 409)
        h["status"] = "ROLLED_BACK"
        H.touch(h)
        t["hotfix_rollback_count"] += 1
        if t["hotfix_rollback_count"] >= 2:
            t["embargoed"] = True
            t["embargo_reason"] = "AUTO_ROLLBACK_THRESHOLD"
        H.touch(t)
    return success_object(H.public(h))
