"""Surveillance recommendation reads."""
from flask import Blueprint

from core import by_seq, db
from core import respond_list, respond_object
from validation import apply_page, auth, filter_enum, filter_value, pagination
from services import get_recommendation

bp = Blueprint("recommendations", __name__)


@bp.get("/surveillance-recommendations/<recommendation_id>")
def read_recommendation(recommendation_id):
    auth("Endoscopist", "PracticeAdmin", "PatientNavigator")
    return respond_object(get_recommendation(recommendation_id))


@bp.get("/surveillance-recommendations")
def list_recommendations():
    auth("Endoscopist", "PracticeAdmin", "PatientNavigator")
    limit, offset = pagination()
    episode_id = filter_value("episode_id")
    pathology_report_id = filter_value("pathology_report_id")
    attesting_endoscopist_id = filter_value("attesting_endoscopist_id")
    status = filter_enum("status", ("ACTIVE", "SUPERSEDED"))
    rows = by_seq(list(db.recommendations.values()))
    if episode_id is not None:
        rows = [r for r in rows if r["episode_id"] == episode_id]
    if pathology_report_id is not None:
        rows = [r for r in rows if r["pathology_report_id"] == pathology_report_id]
    if attesting_endoscopist_id is not None:
        rows = [r for r in rows if r["attesting_endoscopist_id"] == attesting_endoscopist_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)
