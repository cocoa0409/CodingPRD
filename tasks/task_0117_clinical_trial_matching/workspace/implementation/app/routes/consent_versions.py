"""Consent version publishing & listing under a Trial."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_COORD, ROLE_IRB, ROLE_PI, require_roles
from ..clock import now
from ..errors import err_invalid_input, err_invalid_state
from ..helpers import (
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing
from ..services.lookups import consent_versions_for_trial, get_trial
from ..services.serialize import serialize_consent_version
from ..store import store

bp = Blueprint("consent_versions", __name__)


PUBLISH_ALLOWED_STATES = {"DRAFT", "IRB_PENDING", "APPROVED", "OPEN_FOR_ENROLLMENT"}


@bp.post("/trials/<trial_id>/consent-versions")
@require_roles(ROLE_PI)
def publish_consent_version(trial_id: str, **_caller):
    body = require_json_object()
    with store().lock:
        trial = get_trial(trial_id)
        if trial["status"] not in PUBLISH_ALLOWED_STATES:
            raise err_invalid_state(
                "ConsentVersion may only be published from DRAFT, IRB_PENDING, APPROVED, or OPEN_FOR_ENROLLMENT"
            )

        document_uri = assert_string(body.get("document_uri"), "document_uri", required=True, min_len=1, max_len=500)

        existing_versions = consent_versions_for_trial(trial_id)
        next_version = (existing_versions[-1]["version"] + 1) if existing_versions else 1

        change_summary = body.get("change_summary")
        if next_version >= 2:
            change_summary = assert_string(
                change_summary,
                "change_summary",
                required=True,
                min_len=1,
                max_len=500,
            )
        else:
            change_summary = assert_string(
                change_summary, "change_summary", required=False, min_len=1, max_len=500
            )

        requires_re_consent = body.get("requires_re_consent", False)
        if not isinstance(requires_re_consent, bool):
            raise err_invalid_input("requires_re_consent must be a boolean")

        ts = now()
        cv_id = new_uuid()
        cv = {
            "id": cv_id,
            "trial_id": trial_id,
            "version": next_version,
            "document_uri": document_uri,
            "change_summary": change_summary,
            "requires_re_consent": requires_re_consent,
            "published_at": ts,
            "created_at": ts,
        }
        store().consent_versions[cv_id] = cv

        # Atomically: set Trial.active_consent_version.
        trial["active_consent_version"] = next_version
        trial["updated_at"] = ts
        trial["version"] = trial["version"] + 1

        # If requires_re_consent, mark stale-versioned participants. The "marking" is
        # implicit because the re-consent gate compares signed_consent_version to
        # active_consent_version directly — no flag needed. We still bump those
        # participants' version + updated_at to reflect a server-side cascade.
        # PRD §2.10 says: when requires_re_consent=true, every previously ENROLLED
        # participant whose signed_consent_version < new version is marked stale.
        # We surface this as a no-op-but-bookkeeping update.
        if requires_re_consent:
            for p in list(store().participants.values()):
                if (
                    p["trial_id"] == trial_id
                    and p["status"] == "ENROLLED"
                    and (p["signed_consent_version"] is None or p["signed_consent_version"] < next_version)
                ):
                    p["updated_at"] = ts
                    p["version"] = p["version"] + 1

    return created(serialize_consent_version(cv))


@bp.get("/trials/<trial_id>/consent-versions")
@require_roles(ROLE_PI, ROLE_IRB, ROLE_COORD)
def list_consent_versions(trial_id: str, **_caller):
    limit, offset = parse_pagination()
    with store().lock:
        get_trial(trial_id)
        rows = consent_versions_for_trial(trial_id)
        # consent_versions_for_trial sorts by version ascending; that matches "creation order" because
        # versions are assigned monotonically.
        total = len(rows)
        page = paginate(rows, limit, offset)
        items = [serialize_consent_version(c) for c in page]
    return listing(items, total, limit, offset)
