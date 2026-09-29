"""Cross-cutting request plumbing: RBAC, path resolution, scope, pagination."""

from functools import wraps

from flask import request

import errors
from db import db
from validators import Body, query_int

ROLE_NAMES = ("SystemAdmin", "ReimbursementAnalyst", "ReimbursementManager", "MacAuditor",
              "ReviewBoardClerk")
PROVIDER_SCOPED_ROLES = ("ReimbursementAnalyst", "ReimbursementManager")
READ_ROLES = ("SystemAdmin", "ReimbursementAnalyst", "ReimbursementManager", "MacAuditor")
READ_ROLES_WITH_BOARD = READ_ROLES + ("ReviewBoardClerk",)

TABLE_OF = {
    "Provider": "providers",
    "CostReport": "cost_reports",
    "CostCenter": "cost_centers",
    "TrialBalanceLine": "trial_balance_lines",
    "WorkpaperEntry": "workpaper_entries",
    "StepdownRun": "stepdown_runs",
    "WageIndexSubmission": "wage_index_submissions",
    "OccMixResponse": "occ_mix_responses",
    "Resident": "residents",
    "RotationAssignment": "rotation_assignments",
    "UccDataSet": "ucc_data_sets",
    "Settlement": "settlements",
    "AuditAdjustment": "audit_adjustments",
    "AppealCase": "appeal_cases",
    "InterimRateRequest": "interim_rate_requests",
}


def endpoint(roles):
    """Validation bands 1 and 2."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if role not in ROLE_NAMES:
                raise errors.unauthenticated()
            if role not in roles:
                raise errors.forbidden_role()
            return view(*args, **kwargs)
        return wrapper
    return decorator


def current_role():
    return request.headers.get("X-User-Role")


def current_user_id():
    value = request.headers.get("X-User-ID")
    if value is None:
        return None
    value = value.strip()
    return value or None


def body():
    """Validation band 3 entry point."""
    return Body(request.get_json(silent=True))


def find(entity, row_id):
    """Validation band 4."""
    row = getattr(db, TABLE_OF[entity]).get(row_id)
    if row is None:
        raise errors.not_found(entity)
    return row


def reference(entity, row_id):
    """Validation band 5."""
    row = getattr(db, TABLE_OF[entity]).get(row_id)
    if row is None:
        raise errors.referenced_not_found("Referenced %s does not exist." % entity)
    return row


def check_scope(provider_id):
    """Validation band 6."""
    if current_role() in PROVIDER_SCOPED_ROLES:
        user_id = current_user_id()
        if user_id is not None and user_id != provider_id:
            raise errors.scope_violation()


def provider_of_report(report):
    return report["provider_id"]


def report_of_center(center):
    return db.cost_reports[center["cost_report_id"]]


EDITABLE_REPORT_STATUSES = ("DRAFT", "REOPENED")
GME_REPORT_FIELDS = ("unweighted_fte_days_total", "unweighted_fte_total", "capped_unweighted_fte",
                     "weighted_fte_total", "rolling_average_fte")


def require_editable(report):
    """Validation band 9 — ERR_COST_REPORT_NOT_EDITABLE."""
    if report["status"] not in EDITABLE_REPORT_STATUSES:
        raise errors.not_editable(
            "The cost report is in %s; its accounting children are frozen." % report["status"])


def gme_refresh(report):
    """Recompute the GME figures, bumping the report only when a figure moved."""
    import services.calc as calc
    from db import touch

    before = dict((key, report[key]) for key in GME_REPORT_FIELDS)
    period_days, prior_count = calc.recompute_gme(report)
    if any(report[key] != before[key] for key in GME_REPORT_FIELDS):
        touch(report)
    return period_days, prior_count


def pagination():
    limit = query_int(request.args, "limit", 10, minimum=1, maximum=100)
    offset = query_int(request.args, "offset", 0, minimum=0)
    return limit, offset


def window(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


def ok_list_of(rows, limit, offset):
    """Serialize the requested window of an already-ordered, already-filtered list."""
    from response import ok_list

    items = [public(row) for row in rows[offset:offset + limit]]
    return ok_list(items, limit, offset, len(rows))


def public(row):
    return dict((key, value) for key, value in row.items() if not key.startswith("_"))


def public_list(rows):
    return [public(row) for row in rows]
