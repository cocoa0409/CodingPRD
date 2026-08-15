"""Delinquency notice endpoints (PRD 3.7): OCC-guarded create-with-supersede
drafting, ISSUE (freezes the demand, sets the cure deadline, rejects coverage
overlap), and SERVE (statutory service documentation within the window)."""

from datetime import timedelta

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V
from services import calc

bp = Blueprint("notices", __name__)

DRAFT_ROLES = {"LeasingAgent", "PropertyManager"}
SERVICE_METHODS = {"PERSONAL", "POSTED_AND_MAILED", "CERTIFIED_MAIL"}


def get_notice_or_404(notice_id):
    notice = db.notices.get(notice_id)
    if notice is None:
        errors.fail(errors.ERR_NOT_FOUND, "Notice %s does not exist." % notice_id)
    return notice


def _overlaps_closed(a_start, a_end, b_start, b_end):
    """Closed calendar-day windows share a day iff each starts on or before
    the other ends (PRD 3.7)."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/notices")
def create_notice():
    _uid, role = middleware.current_user()
    middleware.require_role(role, DRAFT_ROLES)
    data = V.json_body()
    V.check_unknown(data, {"lease_id", "charge_ids", "expected_lease_version"})
    lease_id = V.req_str(data, "lease_id")
    charge_ids = V.req_id_array(data, "charge_ids")
    # Tier 4: body FK references must exist.
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    covered = []
    for cid in charge_ids:
        charge = db.charges.get(cid)
        if charge is None:
            errors.fail(errors.ERR_NOT_FOUND, "Charge %s does not exist." % cid)
        covered.append(charge)
    # Tier 5: OCC — the client must hold the lease's current version.
    expected = V.req_version(data, "expected_lease_version")
    if expected != lease["version"]:
        errors.fail(
            errors.ERR_STALE_VERSION,
            "expected_lease_version %s does not match the lease's current version %d."
            % (expected, lease["version"]),
        )
    # Tier 6: notice creation requires an ACTIVE lease.
    if lease["status"] == "DRAFT":
        errors.fail(errors.ERR_LEASE_NOT_ACTIVE, "Notices require an ACTIVE lease.")
    if lease["status"] == "ENDED":
        errors.fail(
            errors.ERR_LEASE_ALREADY_ENDED,
            "Notices cannot be created on an ENDED lease.",
        )
    # Tier 9: every covered charge must belong to the named lease.
    for charge in covered:
        if charge["lease_id"] != lease["id"]:
            errors.fail(
                errors.ERR_CHARGE_NOT_ON_LEASE,
                "Charge %s does not belong to lease %s." % (charge["id"], lease["id"]),
            )
    # Create-with-supersede: any existing DRAFT notice on the lease is
    # cancelled with cancel_reason SUPERSEDED; the lease version advances.
    for other in db.notices.values():
        if other["lease_id"] == lease["id"] and other["status"] == "DRAFT":
            other["status"] = "CANCELLED"
            other["cancel_reason"] = "SUPERSEDED"
            db.touch(other)
    notice = db.init_common({
        "lease_id": lease["id"],
        "charge_ids": charge_ids,
        "period_start_date": min(c["period_start_date"] for c in covered),
        "period_end_date": max(c["period_end_date"] for c in covered),
        "amount_demanded_cents": 0,
        "status": "DRAFT",
        "issued_date": None,
        "cure_deadline_date": None,
        "service_method": None,
        "served_date": None,
        "served_by_user_id": None,
        "cancel_reason": None,
    })
    db.notices[notice["id"]] = notice
    # The demand is a live figure while DRAFT (provisional late fees included).
    notice["amount_demanded_cents"] = calc.notice_demand(notice)
    db.touch(lease)
    return response.success_object(serializers.notice_view(notice), 201)


@bp.get("/leases/<lease_id>/notices")
def list_notices(lease_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    if role == "Tenant":
        middleware.require_owns_lease(uid, lease)
    rows = [n for n in db.notices.values() if n["lease_id"] == lease["id"]]
    page, limit, offset, total = V.sorted_page(rows, [
        ("status", V.query_filter("status")),
    ])
    return response.success_list(
        [serializers.notice_view(n) for n in page], limit, offset, total
    )


@bp.post("/notices/<notice_id>/transition")
def transition_notice(notice_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.PM)
    notice = get_notice_or_404(notice_id)
    data = V.json_body()
    V.check_unknown(data, {"action", "service_method", "served_date"})
    action = V.req_enum(data, "action", {"ISSUE", "SERVE"})
    lease = db.leases[notice["lease_id"]]

    if action == "ISSUE":
        # Tier 7: issuing from any status other than DRAFT is rejected.
        if notice["status"] != "DRAFT":
            errors.fail(
                errors.ERR_NOTICE_INVALID_TRANSITION,
                "ISSUE requires a notice in DRAFT status.",
            )
        # Tier 6: the lease must still be ACTIVE.
        if lease["status"] == "DRAFT":
            errors.fail(errors.ERR_LEASE_NOT_ACTIVE, "Issuance requires an ACTIVE lease.")
        if lease["status"] == "ENDED":
            errors.fail(
                errors.ERR_LEASE_ALREADY_ENDED,
                "Notices cannot be issued on an ENDED lease.",
            )
        # Tier 13: the closed-day coverage window must not share a calendar
        # day with any other ISSUED or SERVED notice of the same lease.
        start = calc.parse_d(notice["period_start_date"])
        end = calc.parse_d(notice["period_end_date"])
        for other in db.notices.values():
            if (
                other["id"] != notice["id"]
                and other["lease_id"] == lease["id"]
                and other["status"] in ("ISSUED", "SERVED")
                and _overlaps_closed(
                    start, end,
                    calc.parse_d(other["period_start_date"]),
                    calc.parse_d(other["period_end_date"]),
                )
            ):
                errors.fail(
                    errors.ERR_NOTICE_PERIOD_OVERLAP,
                    "The coverage window overlaps another open notice on this lease.",
                )
        today = db.clock_date()
        prop = calc.property_of(lease)
        notice["status"] = "ISSUED"
        notice["issued_date"] = today.isoformat()
        notice["cure_deadline_date"] = (
            today + timedelta(days=prop["notice_cure_period_days"])
        ).isoformat()
        # amount_demanded_cents freezes forever at its current (issued) value.
        db.touch(notice)
        return response.success_object(serializers.notice_view(notice))

    # SERVE
    if notice["status"] != "ISSUED":
        errors.fail(
            errors.ERR_NOTICE_INVALID_TRANSITION,
            "SERVE requires a notice in ISSUED status.",
        )
    service_method = V.req_enum(data, "service_method", SERVICE_METHODS)
    served_date = V.req_date(data, "served_date")
    # Tier 11: the full service window is inclusive at both ends.
    if not (
        calc.parse_d(notice["issued_date"])
        <= served_date
        <= calc.parse_d(notice["cure_deadline_date"])
    ):
        errors.fail(
            errors.ERR_NOTICE_SERVICE_WINDOW,
            "served_date must lie within [issued_date, cure_deadline_date].",
        )
    notice["status"] = "SERVED"
    notice["service_method"] = service_method
    notice["served_date"] = served_date.isoformat()
    notice["served_by_user_id"] = uid
    db.touch(notice)
    return response.success_object(serializers.notice_view(notice))
