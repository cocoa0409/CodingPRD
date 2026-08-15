"""TransparencyReport endpoints: immutable public queue snapshots."""
from flask import Blueprint

from db import DB, new_id, next_seq, pub, stamp_new_immutable
from errors import ApiError
from middleware import READ_ROLES, auth
from response import ok
from services import transparency_snapshot
from util import body, req_str

bp = Blueprint("transparency", __name__)


@bp.route("/interconnection/transparency-reports", methods=["POST"])
def create_transparency_report():
    auth(["QueueAdministrator"])
    data = body()
    reporting_period = req_str(data, "reporting_period")

    # The reporting-period label is unique across all published snapshots.
    for existing in DB["transparency_reports"].values():
        if existing["reporting_period"] == reporting_period:
            raise ApiError(
                "ERR_REPORTING_PERIOD_CONFLICT", 409,
                "A TransparencyReport already exists for this reporting_period",
            )

    report = {"id": new_id(), "_seq": next_seq(), "reporting_period": reporting_period}
    report.update(transparency_snapshot())
    stamp_new_immutable(report)
    DB["transparency_reports"][report["id"]] = report
    return ok(pub(report), 201)


@bp.route("/interconnection/transparency-reports/<report_id>", methods=["GET"])
def get_transparency_report(report_id):
    auth(READ_ROLES)
    report = DB["transparency_reports"].get(report_id)
    if report is None:
        raise ApiError(
            "ERR_TRANSPARENCY_REPORT_NOT_FOUND", 404,
            "TransparencyReport id does not exist",
        )
    return ok(pub(report))
