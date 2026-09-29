"""The decertification cascade (PRD 3.5) and the activation cascade (PRD 3.4)."""

import clock
import db
from services import derive

REMANDABLE = ("NEXUS_CERTIFIED", "NOTICE_PUBLISHED")


def void_notice_and_protests(study):
    """Hop four: the remand out of NOTICE_PUBLISHED voids notice and protests."""
    study["notice_method"] = None
    study["notice_days"] = None
    study["notice_published_at"] = None
    study["protest_window_ends_at"] = None
    for filing in derive.filings_of_study(study["id"]):
        if filing["status"] == "RECORDED":
            filing["status"] = "VOIDED"
            db.touch(filing)
    study["protest_weight_bp"] = 0
    study["protest_count"] = 0


def remand_to_draft(study):
    """Hop three: a certified or noticed study goes back to DRAFT."""
    if study is None or study["status"] not in REMANDABLE:
        return False
    was_noticed = study["status"] == "NOTICE_PUBLISHED"
    study["status"] = "DRAFT"
    study["revision_round"] += 1
    study["certified_by_user_id"] = None
    study["certified_at"] = None
    if was_noticed:
        void_notice_and_protests(study)
    db.touch(study)
    return True


def sustain_protest(study):
    """Closing the window with the tally at or above the threshold (PRD 3.4)."""
    study["status"] = "DRAFT"
    study["revision_round"] += 1
    study["certified_by_user_id"] = None
    study["certified_at"] = None
    void_notice_and_protests(study)
    db.touch(study)


def decertify_from_component(component):
    """Hops two through four, triggered by a VALID component going STALE."""
    for item in derive.items_of_component(component["id"]):
        item["schedule_status"] = "STALE"
        item["fee_per_unit_cents"] = None
        db.touch(item)
    remand_to_draft(derive.study_of_component(component))


def revalidate_schedule_items(component):
    """Repair path: lines return to VALID with recomputed fees (PRD 3.5)."""
    from services import calc

    for item in derive.items_of_component(component["id"]):
        item["schedule_status"] = "VALID"
        item["fee_per_unit_cents"] = calc.fee_per_unit_cents(component, item["conversion_factor"])
        db.touch(item)


def activate_study(study, program):
    """Activation: effective, supersede the incumbent, flag unpaid applications."""
    prior = derive.effective_study(program["id"])
    if prior is not None and prior["id"] == study["id"]:
        prior = None

    study["status"] = "EFFECTIVE"
    study["activated_at"] = clock.now()
    db.touch(study)

    if prior is not None:
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_fee_study_id"] = study["id"]
        db.touch(prior)
        for application in db.ordered(db.development_applications):
            if application.get("pinned_fee_study_id") != prior["id"]:
                continue
            if application["assessment_status"] not in ("ASSESSED", "REASSESSED"):
                continue
            if application["collection_status"] not in ("NOT_DUE", "DUE", "DEFERRED", "DELINQUENT"):
                continue
            application["reassessment_required"] = True
            db.touch(application)

    db.touch(program)
    return study
