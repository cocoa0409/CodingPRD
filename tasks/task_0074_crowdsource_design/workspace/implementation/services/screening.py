"""Preliminary plagiarism screening service.

Drives the SCREENING -> ACCEPTED / SCREEN_REJECTED transition immediately after
a Submission enters SCREENING (whether via the project cascade or an explicit
submit). The trust_score on the owning Designer is updated.
"""
from decimal import Decimal

from common import stamp_update
from db import db
from services.audit import emit_audit
from services.calculations import (
    PRELIM_ORIGINALITY_FLOOR,
    TRUST_PENALTY_ON_REJECT,
    originality_score_preliminary,
    to_decimal,
    to_float_2dp,
)
from services.similarity import public_similarity


def run_preliminary_scan(submission: dict):
    """Compute originality_score, set the variant, update Designer.trust_score,
    and transition SCREENING -> ACCEPTED/SCREEN_REJECTED with required cascades."""
    project = db.projects.get(submission.get("project_id"))
    cat_id = db.design_categories_by_code.get(project.get("category_code")) if project else None
    cat = db.design_categories.get(cat_id) if cat_id else None
    corpus_id = cat.get("similarity_corpus_id") if cat else ""

    pub_sim = public_similarity(submission.get("asset_urls", []), corpus_id)
    score = originality_score_preliminary(pub_sim)
    submission["originality_score"] = score
    submission["originality_variant"] = "PRELIMINARY_SCAN"

    # Update Designer.trust_score: fold the score into the running trust score
    # by averaging with the prior value (simple deterministic update).
    designer = db.designers.get(submission.get("designer_id"))
    if designer is not None:
        prior = to_decimal(designer.get("trust_score", 100))
        new_score = to_decimal(score)
        designer["trust_score"] = to_float_2dp((prior + new_score) / Decimal("2"))
        stamp_update(designer)

    # Determine pass/fail
    if to_decimal(score) < PRELIM_ORIGINALITY_FLOOR:
        submission["status"] = "SCREEN_REJECTED"
        stamp_update(submission)
        if designer is not None:
            penalised = to_decimal(designer["trust_score"]) - TRUST_PENALTY_ON_REJECT
            if penalised < 0:
                penalised = Decimal("0")
            designer["trust_score"] = to_float_2dp(penalised)
            stamp_update(designer)
        # Emit REVIEW_VOIDED audit for any prior assignments (defensive: typically none yet)
        for asn in db.review_assignments.values():
            if asn.get("submission_id") == submission["id"] and asn.get("status") in {"PENDING", "SUBMITTED"}:
                asn["status"] = "VOIDED"
                stamp_update(asn)
                emit_audit(
                    "REVIEW_VOIDED",
                    "SYSTEM",
                    "system",
                    "REVIEW_ASSIGNMENT",
                    asn["id"],
                    {"reason": "submission_screen_rejected"},
                )
    else:
        submission["status"] = "ACCEPTED"
        stamp_update(submission)
