"""ParentalNotice endpoints (PRD §3.4)."""
from flask import Blueprint

import calculations as calc
from constants import (
    DELIVERY_CHANNELS,
    REQUIRED_NOTICE_CONTENT_KEYS,
    ROLE_COMPLIANCE_OFFICER,
)
from db import db, now, touch
from errors import fail
from helpers import (
    base_row,
    bump_service,
    check_service_version,
    resolve,
    resolve_body_fk,
)
from middleware import authenticate, body, opt_enum_list, req_enum, req_enum_list, req_string
from response import created, ok
from serializers import notice_out

bp = Blueprint("notices", __name__)


@bp.post("/parental-notices")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_notice():
    data = body()
    service = resolve_body_fk("service", data, "service_id")
    check_service_version(data, service)

    notice_label = req_string(data, "notice_label")
    delivery_channel = req_enum(data, "delivery_channel", DELIVERY_CHANNELS)
    content_keys = req_enum_list(
        data, "content_keys", REQUIRED_NOTICE_CONTENT_KEYS, non_empty=False
    )
    vendors = data.get("disclosed_integration_vendors")
    if vendors is None:
        vendors = []
    else:
        from middleware import req_string_list

        vendors = req_string_list(data, "disclosed_integration_vendors")

    notice = base_row()
    notice.update(
        {
            "service_id": service["id"],
            "notice_label": notice_label,
            "delivery_channel": delivery_channel,
            "content_keys": content_keys,
            "disclosed_integration_vendors": vendors,
            "status": "DRAFT",
            "published_at": None,
        }
    )
    db.parental_notices[notice["id"]] = notice
    bump_service(service)
    return created(notice_out(notice))


@bp.post("/parental-notices/<notice_id>/publish")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def publish_notice(notice_id):
    notice = resolve("notice", notice_id)
    if notice["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    if calc.missing_content_keys(notice["content_keys"]):
        fail("ERR_NOTICE_CONTENT_INCOMPLETE")

    for other in db.parental_notices.values():
        if (
            other["id"] != notice["id"]
            and other["service_id"] == notice["service_id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)

    notice["status"] = "PUBLISHED"
    notice["published_at"] = now()
    touch(notice)

    # disclosed_in_notice is derived from the currently PUBLISHED notice, so every
    # integration of the service picks the new disclosure list up immediately.
    service = db.online_services[notice["service_id"]]
    bump_service(service)
    return ok(notice_out(notice))
