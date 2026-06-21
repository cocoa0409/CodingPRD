"""StatementOfUse routes (PRD §2.6, §3.4). Filing is OCC-guarded; acceptance
mints a Registration (ALLOWED -> REGISTERED).
"""

from flask import Blueprint

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services import models
from services.body import (
    get_json_body,
    require_nonempty_string,
    require_datetime,
    require_int,
    optional_int,
)
from services.pagination import parse_pagination, slice_sorted
from services.ownership import check_application_owner

bp = Blueprint("statements_of_use", __name__)


@bp.post("/statements-of-use")
@require_roles("Attorney", "Applicant")
def file_statement_of_use(_user_id, _role):
    body = get_json_body()
    application_id = require_nonempty_string(body, "application_id")
    specimen_url = require_nonempty_string(body, "specimen_url")
    first_use_date = require_datetime(body, "first_use_date")
    extension_number = optional_int(body, "extension_number", 0)
    # expected_application_version is a non-optional OCC field.
    expected_version = require_int(body, "expected_application_version")

    app = models.get_or_404(db.applications, application_id, "TrademarkApplication")

    # Ownership (priority 4).
    check_application_owner(app, _role, _user_id)

    # OCC (priority 7): expected_application_version must equal current version.
    if expected_version != app["version"]:
        raise_api("ERR_STALE_VERSION", "Application version is stale")

    # Business constraint (priority 15): INTENT + ALLOWED, and extension_number
    # must not exceed the application's granted-extension count.
    if app["filing_basis"] != "INTENT" or app["status"] != "ALLOWED":
        raise_api(
            "ERR_SOU_NOT_PERMITTED",
            "SOU permitted only for an ALLOWED INTENT application",
        )
    if extension_number < 0 or extension_number > 5:
        raise_api("ERR_VALIDATION", "extension_number must be an integer 0..5")
    granted = app.get("granted_extension_count", 0)
    if extension_number > granted:
        raise_api(
            "ERR_SOU_NOT_PERMITTED",
            "extension_number exceeds the application's granted extensions",
        )

    from db import iso_from_datetime
    rec = models.make_record({
        "application_id": application_id,
        "specimen_url": specimen_url,
        "first_use_date": iso_from_datetime(first_use_date),
        "extension_number": extension_number,
        "status": "SUBMITTED",
    })
    db.statements_of_use[rec["id"]] = rec

    # Filing increments the application's version (so a later stale-version SOU
    # create is rejected).
    models.touch(app)
    return success(models.ser_statement_of_use(rec), 201)


@bp.post("/statements-of-use/<rid>/accept")
@require_roles("Examiner")
def accept_statement_of_use(rid, _user_id, _role):
    sou = models.get_or_404(db.statements_of_use, rid, "StatementOfUse")
    app = db.applications[sou["application_id"]]

    # State: application must be ALLOWED and this SOU SUBMITTED.
    if app["status"] != "ALLOWED":
        raise_api("ERR_INVALID_STATE", "Application is not ALLOWED")
    if sou["status"] != "SUBMITTED":
        raise_api("ERR_INVALID_STATE", "Statement of use is not SUBMITTED")

    sou["status"] = "ACCEPTED"
    models.touch(sou)
    # Flip every goods/services item to IN_USE.
    for g in db.goods_services.values():
        if g["application_id"] == app["id"]:
            g["use_status"] = "IN_USE"
            models.touch(g)

    # Mint registration (reuse the applications helper).
    from routes.applications import _mint_registration
    reg = _mint_registration(app)

    models.set_docket_status("SOU", app["id"], "MET", only_pending=True)
    app["status"] = "REGISTERED"
    models.touch(app)
    return success(models.ser_registration(reg), 201)
