"""Console firmware builds and connectivity certification (PRD 3.3)."""

from flask import Blueprint, g

import calc
from auth import get_certification, get_release, get_revision, require
from constants import CERT_STATUSES, CONSOLE_PLATFORMS
from envelope import created, ok, ok_list
from errors import ApiError
from store import mutate, new_entity, store
from validation import (
    field_bool,
    field_enum,
    field_id,
    field_str,
    get_body,
    paginate,
    paging,
    query_enum,
    query_str,
)

bp = Blueprint("firmware", __name__)


# ---------------------------------------------------------------------------
# firmware releases
# ---------------------------------------------------------------------------
@bp.post("/firmware-releases")
@require("ProductEngineer")
def create_firmware_release():
    body = get_body()
    version_string = field_str(body, "version_string", min_len=1, max_len=40)
    console_platform = field_enum(body, "console_platform", CONSOLE_PLATFORMS)
    mandatory_security = field_bool(
        body, "mandatory_security", required=False, default=False
    )

    for row in store.firmware_releases.values():
        if row["version_string"] == version_string:
            raise ApiError(
                "ERR_DUPLICATE_REVISION_CODE",
                "A firmware release version string must be unique.",
            )

    release = new_entity(
        {
            "version_string": version_string,
            "console_platform": console_platform,
            "mandatory_security": mandatory_security,
            "status": "ACTIVE",
            "certified_revision_count": 0,
            "withdrawn_at": None,
        }
    )
    store.firmware_releases[release["id"]] = release
    return created(release)


@bp.get("/firmware-releases/<release_id>")
@require("ProductEngineer", "ComplianceOfficer", "ServiceOpsAdmin", "ServicePartnerTech")
def read_firmware_release(release_id):
    return ok(get_release(release_id))


@bp.post("/firmware-releases/<release_id>/withdraw")
@require("ComplianceOfficer")
def withdraw_firmware_release(release_id):
    release = get_release(release_id)
    body = get_body()
    field_str(body, "withdraw_reason", min_len=1)

    if release["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE release may be withdrawn."
        )

    with mutate(release):
        release["status"] = "WITHDRAWN"
        release["withdrawn_at"] = store.now_iso()
    calc.withdrawal_cascade(release)
    return ok(release)


# ---------------------------------------------------------------------------
# firmware certifications
# ---------------------------------------------------------------------------
@bp.post("/firmware-certifications")
@require("ProductEngineer", "ComplianceOfficer")
def create_firmware_certification():
    body = get_body()
    firmware_release_id = field_id(body, "firmware_release_id")
    model_revision_id = field_id(body, "model_revision_id")
    test_report_ref = field_str(body, "test_report_ref", min_len=1, max_len=80)

    # rung 9
    release = get_release(firmware_release_id)
    revision = get_revision(model_revision_id)

    # rung 22 — console platform compatibility
    model = calc.model_of_revision(revision)
    if not model["connected"] or release["console_platform"] != model["console_platform"]:
        raise ApiError(
            "ERR_PLATFORM_INCOMPATIBLE",
            "The build's console platform does not match a connected model.",
        )

    # rung 23 — certification uniqueness
    for cert in calc.release_certifications(release["id"]):
        if cert["model_revision_id"] == revision["id"] and cert["cert_status"] in (
            "SUBMITTED",
            "CERTIFIED",
        ):
            raise ApiError(
                "ERR_DUPLICATE_CERTIFICATION",
                "This build and revision pairing is already certified or submitted.",
            )

    cert = new_entity(
        {
            "firmware_release_id": release["id"],
            "model_revision_id": revision["id"],
            "test_report_ref": test_report_ref,
            "cert_status": "SUBMITTED",
            "submitted_by_user_id": g.user_id,
            "certified_by_user_id": None,
            "certified_at": None,
        }
    )
    store.firmware_certifications[cert["id"]] = cert
    return created(cert)


@bp.get("/firmware-certifications")
@require("ProductEngineer", "ComplianceOfficer", "ServiceOpsAdmin")
def list_firmware_certifications():
    limit, offset = paging()
    firmware_release_id = query_str("firmware_release_id")
    model_revision_id = query_str("model_revision_id")
    cert_status = query_enum("cert_status", CERT_STATUSES)

    rows = list(store.firmware_certifications.values())
    if firmware_release_id is not None:
        rows = [r for r in rows if r["firmware_release_id"] == firmware_release_id]
    if model_revision_id is not None:
        rows = [r for r in rows if r["model_revision_id"] == model_revision_id]
    if cert_status is not None:
        rows = [r for r in rows if r["cert_status"] == cert_status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/firmware-certifications/<cert_id>")
@require("ProductEngineer", "ComplianceOfficer", "ServiceOpsAdmin")
def read_firmware_certification(cert_id):
    return ok(get_certification(cert_id))


def _check_segregation(cert):
    if g.user_id == cert["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The signing officer may not be the submitter.",
        )


@bp.post("/firmware-certifications/<cert_id>/certify")
@require("ComplianceOfficer")
def certify_firmware_certification(cert_id):
    cert = get_certification(cert_id)
    _check_segregation(cert)
    get_body()

    if cert["cert_status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SUBMITTED certification may be certified.",
        )
    release = store.firmware_releases[cert["firmware_release_id"]]
    if release["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "The owning firmware release is withdrawn."
        )
    revision = store.model_revisions[cert["model_revision_id"]]
    if revision["status"] not in ("QUALIFIED", "RELEASED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The target revision must be QUALIFIED or RELEASED.",
        )

    with mutate(cert):
        cert["cert_status"] = "CERTIFIED"
        cert["certified_by_user_id"] = g.user_id
        cert["certified_at"] = store.now_iso()
    calc.recompute_release(release)
    return ok(cert)


@bp.post("/firmware-certifications/<cert_id>/reject")
@require("ComplianceOfficer")
def reject_firmware_certification(cert_id):
    cert = get_certification(cert_id)
    _check_segregation(cert)
    body = get_body()
    field_str(body, "rejection_note", min_len=1)

    if cert["cert_status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SUBMITTED certification may be rejected.",
        )

    with mutate(cert):
        cert["cert_status"] = "REJECTED"
    return ok(cert)
