"""PerCapitaReport lifecycle actions: approve, submit, mark-paid."""
from flask import Blueprint

import db
import errors
import serializers
from middleware import require_roles
from response import ok

bp = Blueprint("per_capita", __name__, url_prefix="/api/per-capita-reports")


def get_report_or_404(report_id):
    r = db.store.per_capita_reports.get(report_id)
    if r is None:
        raise errors.per_capita_report_not_found()
    return r


@bp.route("/<report_id>/approve", methods=["POST"])
@require_roles("LocalAdmin")
def approve(user_id, role, report_id):
    report = get_report_or_404(report_id)
    if report["status"] != "DRAFT":
        raise errors.report_state_forbidden()
    if user_id == report["created_by_user_id"]:
        raise errors.segregation_of_duties()
    local = db.store.locals[report["local_id"]]
    if local["per_capita_rate_cents"] != report["rate_cents"]:
        raise errors.stale_per_capita_rate()
    report["status"] = "APPROVED"
    report["approved_by_user_id"] = user_id
    db.touch(report)
    return ok(serializers.per_capita_report(report), 200)


@bp.route("/<report_id>/submit", methods=["POST"])
@require_roles("SecretaryTreasurer")
def submit(user_id, role, report_id):
    report = get_report_or_404(report_id)
    if report["status"] != "APPROVED":
        raise errors.report_state_forbidden()
    report["status"] = "SUBMITTED"
    db.touch(report)
    return ok(serializers.per_capita_report(report), 200)


@bp.route("/<report_id>/mark-paid", methods=["POST"])
@require_roles("SecretaryTreasurer")
def mark_paid(user_id, role, report_id):
    report = get_report_or_404(report_id)
    if report["status"] != "SUBMITTED":
        raise errors.report_state_forbidden()
    report["status"] = "PAID"
    db.touch(report)
    return ok(serializers.per_capita_report(report), 200)
