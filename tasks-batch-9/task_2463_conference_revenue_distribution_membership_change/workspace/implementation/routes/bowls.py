"""Bowl appearances, the review loop and postseason units (PRD section 3.6)."""

from flask import Blueprint

import calc
import response
import serializers
import validation
from db import db, touch
from errors import ApiError
from middleware import api, own_appearance_member, raw_body
from routes import common
from routes.members import mint_postseason_units

bp = Blueprint("bowls", __name__)

APPEARANCE_READ_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "ComplianceOfficer",
    "PlatformAdmin",
    "MemberRepresentative",
)

UNIT_READ_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Auditor",
    "ComplianceOfficer",
    "PlatformAdmin",
    "MemberRepresentative",
)


def _units_of(appearance_id):
    return [
        unit
        for unit in db.postseason_units.values()
        if unit["bowl_appearance_id"] == appearance_id
    ]


@bp.route("/bowl-appearances/<appearance_id>", methods=["GET"])
@api(APPEARANCE_READ_ROLES)
def read_appearance(appearance_id):
    return response.single(
        serializers.bowl_appearance(common.get_appearance(appearance_id))
    )


@bp.route("/bowl-appearances/<appearance_id>/begin-review", methods=["POST"])
@api(("ComplianceOfficer",))
def begin_review(appearance_id):
    appearance = common.get_appearance(appearance_id)
    if appearance["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEARANCE_STATE_INVALID")
    appearance["status"] = "UNDER_REVIEW"
    touch(appearance)
    return response.single(serializers.bowl_appearance(appearance))


@bp.route("/bowl-appearances/<appearance_id>/request-revision", methods=["POST"])
@api(("ComplianceOfficer",))
def request_revision(appearance_id):
    appearance = common.get_appearance(appearance_id)
    body = raw_body()
    validation.get_optional_str(body, "note")
    if appearance["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPEARANCE_STATE_INVALID")
    appearance["status"] = "REVISION_REQUESTED"
    appearance["revision_round"] += 1
    touch(appearance)
    return response.single(serializers.bowl_appearance(appearance))


@bp.route("/bowl-appearances/<appearance_id>/resubmit", methods=["POST"])
@api(("ComplianceOfficer", "MemberRepresentative"), owner=own_appearance_member)
def resubmit_appearance(appearance_id):
    appearance = common.get_appearance(appearance_id)
    body = raw_body()
    submitted_expense_cents = validation.get_int(body, "submitted_expense_cents")
    travel_miles = validation.get_int(body, "travel_miles")
    units_claimed = validation.get_int(body, "units_claimed", required=False)

    if appearance["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_APPEARANCE_STATE_INVALID")

    appearance["submitted_expense_cents"] = submitted_expense_cents
    appearance["travel_miles"] = travel_miles
    if units_claimed is not None:
        appearance["units_claimed"] = units_claimed
    appearance["status"] = "UNDER_REVIEW"
    touch(appearance)

    # The appearance's units are discarded and re-minted so that exactly
    # units_claimed PROVISIONAL units exist again.
    for unit in _units_of(appearance["id"]):
        del db.postseason_units[unit["id"]]
    mint_postseason_units(appearance)

    return response.single(serializers.bowl_appearance(appearance))


@bp.route("/bowl-appearances/<appearance_id>/approve", methods=["POST"])
@api(("ComplianceOfficer",))
def approve_appearance(appearance_id):
    appearance = common.get_appearance(appearance_id)
    conference = db.conference

    if appearance["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPEARANCE_STATE_INVALID")

    figures = calc.bowl_reimbursement(
        appearance["payout_cents"],
        appearance["submitted_expense_cents"],
        appearance["travel_miles"],
    )
    appearance.update(figures)
    appearance["status"] = "APPROVED"
    touch(appearance)

    conference["escrow_balance_cents"] += figures["residual_to_pool_cents"]
    for unit in _units_of(appearance["id"]):
        if unit["status"] == "PROVISIONAL":
            unit["status"] = "VALIDATED"
    conference["validated_postseason_unit_count"] += appearance["units_claimed"]
    touch(conference)

    return response.single(serializers.bowl_appearance(appearance))


@bp.route("/bowl-appearances/<appearance_id>/void", methods=["POST"])
@api(("ComplianceOfficer", "Commissioner"))
def void_appearance(appearance_id):
    appearance = common.get_appearance(appearance_id)
    conference = db.conference
    body = raw_body()
    validation.get_optional_str(body, "reason")

    if appearance["status"] == "VOIDED":
        raise ApiError("ERR_APPEARANCE_STATE_INVALID")

    was_approved = appearance["status"] == "APPROVED"
    if was_approved and _units_already_distributed(appearance):
        raise ApiError("ERR_UNITS_ALREADY_DISTRIBUTED")

    appearance["status"] = "VOIDED"
    touch(appearance)

    for unit in _units_of(appearance["id"]):
        unit["status"] = "VOIDED"

    if was_approved:
        # An exact compensation for the approval (PRD section 2.9).
        conference["escrow_balance_cents"] -= appearance["residual_to_pool_cents"]
        conference["validated_postseason_unit_count"] -= appearance["units_claimed"]
        touch(conference)

    return response.single(serializers.bowl_appearance(appearance))


def _units_already_distributed(appearance):
    """A unit of this appearance has been distributed on a posted run.

    A distribution line carries no unit-level foreign key, so the reference is
    read through the allocation that consumes validated units: a POSTED run over
    a UNIT_BASED pool for the appearance's fiscal year that credited a line to
    the appearance's member.
    """
    for line in db.distribution_lines.values():
        if line["member_id"] != appearance["member_id"]:
            continue
        run = db.distribution_runs.get(line["distribution_run_id"])
        if run is None or run["status"] != "POSTED":
            continue
        pool = db.revenue_pools.get(run["revenue_pool_id"])
        if pool is None:
            continue
        if pool["allocation_method"] != "UNIT_BASED":
            continue
        if pool["fiscal_year"] != appearance["fiscal_year"]:
            continue
        return True
    return False


@bp.route("/bowl-appearances/<appearance_id>/postseason-units", methods=["GET"])
@api(UNIT_READ_ROLES)
def list_appearance_units(appearance_id):
    common.get_appearance(appearance_id)
    criteria = {"status": common.string_filter("status")}
    return common.listing(
        _units_of(appearance_id), serializers.postseason_unit, criteria=criteria
    )
