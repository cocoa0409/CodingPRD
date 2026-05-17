"""UDAAPReview service (PRD §3.9)."""

import db
from config import DISCLOSURE_KIND_CD, DISCLOSURE_KIND_LE, UDAAP_OUTCOMES
from errors import ERR_UDAAP_SOD_VIOLATION, ERR_VALIDATION, raise_error
from services import lookups
from services.common import init_append_only
from services.validation import require_enum, require_string


def create(application: dict, actor_user_id: str, body: dict) -> dict:
    outcome = require_enum(body, "outcome", UDAAP_OUTCOMES)
    notes = None
    if "notes" in body and body["notes"] is not None:
        notes = require_string(body, "notes", allow_empty=False)
    if outcome in {"FLAG", "BLOCK"} and not notes:
        raise_error(ERR_VALIDATION, "notes required for FLAG or BLOCK outcomes.")

    # SoD: actor must equal application.compliance_reviewer_id.
    if application.get("compliance_reviewer_id") != actor_user_id:
        raise_error(
            ERR_UDAAP_SOD_VIOLATION,
            "Acting ComplianceOfficer must be the assigned compliance_reviewer_id.",
        )

    # PRD §3.9 + §3.8/§3.10: a UDAAP review "applies to" the latest LE
    # and latest CD versions on file at the moment of submission. Since
    # the payload does not carry a disclosure-version selector, snapshot
    # the current latest LE.version and CD.version onto the review so
    # the gate checks at conditional-approval (uses latest LE) and
    # clear-to-close (uses latest CD) can perform an exact version
    # match. SystemClock vs wall-clock time is unreliable for this
    # because business-clock advancement does not affect created_at.
    latest_le = lookups.latest_non_voided_disclosure(
        application["id"], DISCLOSURE_KIND_LE
    )
    latest_cd = lookups.latest_non_voided_disclosure(
        application["id"], DISCLOSURE_KIND_CD
    )

    review = init_append_only(
        {
            "application_id": application["id"],
            "reviewer_user_id": actor_user_id,
            "outcome": outcome,
            "notes": notes,
            # Internal snapshot fields (not part of the public response
            # envelope per PRD §2.4 append-only contract — see
            # services/serializers.py for the projection).
            "_snapshot_le_version": (
                latest_le["version"] if latest_le is not None else None
            ),
            "_snapshot_cd_version": (
                latest_cd["version"] if latest_cd is not None else None
            ),
        }
    )
    db.udaap_reviews[review["id"]] = review
    return review


def list_for_app(application_id: str):
    items = [r for r in db.udaap_reviews.values() if r["application_id"] == application_id]
    items.sort(key=lambda r: r["created_at"])
    return items
