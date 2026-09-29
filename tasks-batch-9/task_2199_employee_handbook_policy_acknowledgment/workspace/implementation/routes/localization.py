"""Localization tracks and the accessibility index."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import db
import services
import validate
import web
from errors import fail

bp = Blueprint("localization", __name__)

TRANSLATION_READ = ["HRComplianceAdmin", "PolicyAuthor", "LocalizationSpecialist", "LegalCounsel", "Employee"]


@bp.post("/policy-versions/<policy_version_id>/translations")
def create_translation(policy_version_id):
    auth.authorize(["LocalizationSpecialist"])
    version = validate.path_row("policy_versions", policy_version_id)
    data = validate.body()
    language_code = validate.req_lang(data, "language_code")
    for row in services.rows_where("translations", policy_version_id=version["id"],
                                   language_code=language_code):
        fail("ERR_DUPLICATE_RESOURCE", "a track already exists for this language")
    row = db.base_row()
    row.update({
        "policy_version_id": version["id"],
        "language_code": language_code,
        "status": "PENDING",
        "section_scores": [],
        "a11y_index": None,
        "a11y_round_no": 0,
        "conformance_level": None,
    })
    db.insert("translations", row)
    return web.created("translations", row)


@bp.get("/translations")
def list_translations():
    auth.authorize(TRANSLATION_READ)
    rows = db.all_rows("translations")
    rows = validate.query_filter(rows, "policy_version_id")
    rows = validate.query_filter(rows, "language_code")
    rows = validate.query_filter(rows, "status")
    return web.paged("translations", rows)


@bp.get("/translations/<translation_id>")
def read_translation(translation_id):
    auth.authorize(TRANSLATION_READ)
    row = validate.path_row("translations", translation_id)
    return web.one("translations", row)


@bp.post("/translations/<translation_id>/start")
def start_translation(translation_id):
    auth.authorize(["LocalizationSpecialist"])
    track = validate.path_row("translations", translation_id)
    if track["status"] != "PENDING":
        fail("ERR_TRANSLATION_INVALID_STATE", "track is %s" % track["status"])
    version = db.get("policy_versions", track["policy_version_id"])
    if version is None or version["status"] not in ("DRAFT", "IN_LEGAL_REVIEW", "APPROVED"):
        fail("ERR_VERSION_INVALID_STATE", "owning version is not open for localization")
    track["status"] = "IN_TRANSLATION"
    db.touch(track)
    return web.one("translations", track)


@bp.post("/translations/<translation_id>/submit-a11y")
def submit_a11y(translation_id):
    auth.authorize(["LocalizationSpecialist"])
    track = validate.path_row("translations", translation_id)
    data = validate.body()
    if "section_scores" not in data:
        fail("ERR_VALIDATION", "section_scores is required")
    scores = data["section_scores"]
    if not isinstance(scores, list):
        fail("ERR_VALIDATION", "section_scores must be an array")
    if track["status"] != "IN_TRANSLATION":
        fail("ERR_TRANSLATION_INVALID_STATE", "track is %s" % track["status"])
    version = db.get("policy_versions", track["policy_version_id"])
    section_count = version["section_count"]
    if len(scores) != section_count:
        fail("ERR_SECTION_SCORE_SHAPE", "section_scores must carry exactly %d entries" % section_count)
    for value in scores:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("ERR_SECTION_SCORE_SHAPE", "section_scores entries must be numbers in [0, 1]")
        if Decimal(str(value)) < Decimal(0) or Decimal(str(value)) > Decimal(1):
            fail("ERR_SECTION_SCORE_SHAPE", "section_scores entries must be numbers in [0, 1]")
    track["section_scores"] = list(scores)
    index = calc.a11y_index(scores, section_count)
    track["a11y_index"] = index
    track["conformance_level"] = calc.conformance_level(index)
    track["status"] = "A11Y_REVIEW"
    db.touch(track)
    return web.one("translations", track)


@bp.post("/translations/<translation_id>/rework")
def rework_translation(translation_id):
    auth.authorize(["LocalizationSpecialist"])
    track = validate.path_row("translations", translation_id)
    if track["status"] != "A11Y_REVIEW":
        fail("ERR_TRANSLATION_INVALID_STATE", "track is %s" % track["status"])
    track["status"] = "IN_TRANSLATION"
    track["a11y_round_no"] = track["a11y_round_no"] + 1
    db.touch(track)
    return web.one("translations", track)


@bp.post("/translations/<translation_id>/publish")
def publish_translation(translation_id):
    auth.authorize(["LocalizationSpecialist"])
    track = validate.path_row("translations", translation_id)
    if track["status"] != "A11Y_REVIEW":
        fail("ERR_TRANSLATION_INVALID_STATE", "track is %s" % track["status"])
    if track["conformance_level"] not in ("AA", "AAA"):
        fail("ERR_A11Y_GATE_NOT_MET", "conformance level is %s" % track["conformance_level"])
    track["status"] = "PUBLISHED"
    db.touch(track)
    return web.one("translations", track)


@bp.post("/translations/<translation_id>/abandon")
def abandon_translation(translation_id):
    auth.authorize(["LocalizationSpecialist"])
    track = validate.path_row("translations", translation_id)
    if track["status"] not in ("PENDING", "IN_TRANSLATION"):
        fail("ERR_TRANSLATION_INVALID_STATE", "track is %s" % track["status"])
    track["status"] = "ABANDONED"
    db.touch(track)
    return web.one("translations", track)
