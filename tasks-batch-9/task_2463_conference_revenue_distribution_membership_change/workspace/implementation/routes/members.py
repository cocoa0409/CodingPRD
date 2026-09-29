"""Member institutions: seating, entry fees, the phased ladder and departure."""

import re

from flask import Blueprint

import calc
import clock
import response
import serializers
import validation
from db import base_record, db, ordered, touch
from errors import ApiError
from middleware import api, current_user_id, own_path_member, raw_body
from routes import common
from services import compliance, member_service

bp = Blueprint("members", __name__)

READ_ALL_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "ComplianceOfficer",
    "ScheduleCoordinator",
    "PlatformAdmin",
    "MemberRepresentative",
)

INSTITUTION_CODE_PATTERN = re.compile(r"^[A-Z0-9]{2,8}$")

MEMBER_STATUSES = (
    "PETITIONED",
    "ADMISSION_DENIED",
    "ADMITTED_PHASING",
    "FULL_SHARE",
    "WITHDRAWAL_NOTICED",
    "DEPARTED",
)

WRITE_BLOCKED_STATUSES = ("DEPARTED", "ADMISSION_DENIED")


# ---------------------------------------------------------------------------
# POST /members
# ---------------------------------------------------------------------------


@bp.route("/members", methods=["POST"])
@api(("Commissioner", "PlatformAdmin"))
def create_member():
    conference = db.conference
    body = raw_body()

    conference_id = validation.get_id(body, "conference_id")
    name = validation.get_str(body, "name")
    institution_code = validation.get_str(body, "institution_code")
    admission_path = validation.get_enum(body, "admission_path", ("CHARTER", "PETITIONED"))
    home_venue_id = validation.get_id(body, "home_venue_id")
    grant_of_rights = validation.get_int(
        body, "grant_of_rights_through_fiscal_year", minimum=None
    )
    entry_fee_cents = validation.get_int(
        body, "entry_fee_cents", required=False, default=0
    )
    travel_partner_member_id = validation.get_nullable_id(body, "travel_partner_member_id")
    primary_contact_email = validation.get_optional_str(body, "primary_contact_email")

    if not INSTITUTION_CODE_PATTERN.match(institution_code):
        validation.invalid("institution_code")

    # Body foreign keys, left to right.
    common.get_venue(home_venue_id)
    if travel_partner_member_id is not None:
        common.get_member(travel_partner_member_id)

    for existing in db.members.values():
        if (
            existing["conference_id"] == conference_id
            and existing["institution_code"] == institution_code
        ):
            raise ApiError("ERR_DUPLICATE_INSTITUTION_CODE")

    member = base_record()

    if travel_partner_member_id is not None and travel_partner_member_id == member["id"]:
        raise ApiError("ERR_MEMBER_PAIR_INVALID")

    if admission_path == "CHARTER" and conference["governance_status"] != "FORMING":
        raise ApiError("ERR_CHARTER_WINDOW_CLOSED")

    if admission_path == "CHARTER":
        status = "FULL_SHARE"
        phase_year = calc.CHARTER_PHASE_YEAR
        distribution_phase_bps = calc.FULL_BPS
        voting_weight_bps = calc.FULL_BPS
        entry_fee_cents = 0
    else:
        status = "PETITIONED"
        phase_year = 0
        distribution_phase_bps = 0
        voting_weight_bps = 0

    member.update(
        {
            "conference_id": conference_id,
            "name": name,
            "institution_code": institution_code,
            "admission_path": admission_path,
            "status": status,
            "home_venue_id": home_venue_id,
            "travel_partner_member_id": travel_partner_member_id,
            "primary_contact_email": primary_contact_email,
            "grant_of_rights_through_fiscal_year": grant_of_rights,
            "entry_fee_cents": entry_fee_cents,
            "entry_fee_paid_cents": 0,
            "phase_year": phase_year,
            "distribution_phase_bps": distribution_phase_bps,
            "voting_weight_bps": voting_weight_bps,
            "withdrawal_notice_at": None,
            "withdrawal_effective_fiscal_year": None,
            "notice_days": None,
            "last_full_annual_distribution_cents": 0,
            "exit_settlement_total_cents": 0,
            "exit_settlement_paid_cents": 0,
            "schedule_compliance_score": calc.COMPLIANCE_BASE_SCORE,
            # Exit-assessment working values, reported by GET
            # /members/{id}/exit-settlement.
            "notice_multiplier_bps": 0,
            "base_assessment_cents": 0,
            "surcharge_bracket_bps": 0,
            "surcharge_cents": 0,
        }
    )
    db.members[member["id"]] = member
    return response.single(serializers.member(member), 201)


# ---------------------------------------------------------------------------
# GET /members/{id}  |  GET /members
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>", methods=["GET"])
@api(READ_ALL_ROLES)
def read_member(member_id):
    return response.single(serializers.member(common.get_member(member_id)))


@bp.route("/members", methods=["GET"])
@api(READ_ALL_ROLES)
def list_members():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "home_venue_id": common.string_filter("home_venue_id"),
        "travel_partner_member_id": common.string_filter("travel_partner_member_id"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.members.values()), serializers.member, criteria=criteria
    )


# ---------------------------------------------------------------------------
# PATCH /members/{id}
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>", methods=["PATCH"])
@api(("Commissioner", "PlatformAdmin", "MemberRepresentative"), owner=own_path_member)
def amend_member(member_id):
    member = common.get_member(member_id)
    body = raw_body()

    expected_version = validation.get_int(body, "expected_member_version", minimum=None)
    home_venue_id = validation.get_nullable_id(body, "home_venue_id", default=Ellipsis)
    travel_partner_member_id = validation.get_nullable_id(
        body, "travel_partner_member_id", default=Ellipsis
    )
    grant_of_rights = Ellipsis
    if "grant_of_rights_through_fiscal_year" in body:
        grant_of_rights = validation.get_int(
            body, "grant_of_rights_through_fiscal_year", minimum=None
        )

    if home_venue_id is not Ellipsis and home_venue_id is not None:
        common.get_venue(home_venue_id)
    if travel_partner_member_id is not Ellipsis and travel_partner_member_id is not None:
        common.get_member(travel_partner_member_id)

    if travel_partner_member_id not in (Ellipsis, None) and (
        travel_partner_member_id == member["id"]
    ):
        raise ApiError("ERR_MEMBER_PAIR_INVALID")

    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")

    if member["status"] in WRITE_BLOCKED_STATUSES:
        raise ApiError("ERR_MEMBER_STATE_INVALID")

    if home_venue_id is not Ellipsis:
        member["home_venue_id"] = home_venue_id
    if travel_partner_member_id is not Ellipsis:
        member["travel_partner_member_id"] = travel_partner_member_id
    if grant_of_rights is not Ellipsis:
        member["grant_of_rights_through_fiscal_year"] = grant_of_rights

    touch(member)
    return response.single(serializers.member(member))


# ---------------------------------------------------------------------------
# POST /members/{id}/entry-fee-payments
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/entry-fee-payments", methods=["POST"])
@api(("Treasurer", "MemberRepresentative"), owner=own_path_member)
def record_entry_fee_payment(member_id):
    member = common.get_member(member_id)
    body = raw_body()
    amount_cents = validation.get_int(body, "amount_cents")
    validation.get_optional_str(body, "reference")

    if member["status"] != "PETITIONED":
        raise ApiError("ERR_MEMBER_STATE_INVALID")
    if member["entry_fee_paid_cents"] + amount_cents > member["entry_fee_cents"]:
        raise ApiError("ERR_ENTRY_FEE_OVERPAYMENT")

    member["entry_fee_paid_cents"] += amount_cents
    touch(member)
    return response.single(serializers.member(member))


# ---------------------------------------------------------------------------
# POST /members/{id}/phase-advance
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/phase-advance", methods=["POST"])
@api(("Commissioner", "FinanceOfficer"))
def advance_phase(member_id):
    member = common.get_member(member_id)
    conference = db.conference

    if member["status"] != "ADMITTED_PHASING":
        raise ApiError("ERR_MEMBER_STATE_INVALID")
    if member["entry_fee_paid_cents"] < member["entry_fee_cents"]:
        raise ApiError("ERR_ENTRY_FEE_OUTSTANDING")

    member["phase_year"] += 1
    if member["phase_year"] >= conference["phase_schedule_years"] + 1:
        member["status"] = "FULL_SHARE"
    member_service.apply_phase_schedule(member)
    touch(member)
    return response.single(serializers.member(member))


# ---------------------------------------------------------------------------
# POST /members/{id}/withdrawal-notice
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/withdrawal-notice", methods=["POST"])
@api(("Commissioner",))
def file_withdrawal_notice(member_id):
    member = common.get_member(member_id)
    conference = db.conference
    body = raw_body()

    effective_year = validation.get_int(
        body, "withdrawal_effective_fiscal_year", minimum=None
    )
    notice_days = validation.get_int(body, "notice_days", required=False)
    validation.get_optional_str(body, "reason")

    if member["status"] != "FULL_SHARE":
        raise ApiError("ERR_MEMBER_STATE_INVALID")
    if effective_year <= conference["current_fiscal_year"]:
        raise ApiError("ERR_INVALID_EFFECTIVE_YEAR")

    member["status"] = "WITHDRAWAL_NOTICED"
    member["withdrawal_notice_at"] = clock.now()
    if notice_days is None:
        # PRD section 3.1 step one: the whole number of days from the notice
        # instant to the first day of the effective fiscal year.
        notice_days = _days_of_notice(
            member["withdrawal_notice_at"],
            effective_year,
            conference["fiscal_year_start_month"],
        )
    member["withdrawal_effective_fiscal_year"] = effective_year
    member["notice_days"] = notice_days
    member_service.apply_phase_schedule(member)

    assessment = calc.exit_settlement(
        notice_days, member["last_full_annual_distribution_cents"]
    )
    member.update(assessment)
    touch(member)
    return response.single(serializers.member(member))


def _days_of_notice(notice_at, effective_year, fiscal_year_start_month):
    """The fiscal year labelled N opens on its start month, day 1, of year N."""
    first_day = notice_at.replace(
        year=effective_year,
        month=fiscal_year_start_month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return (first_day - notice_at).days


# ---------------------------------------------------------------------------
# POST /members/{id}/withdrawal-notice/rescind
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/withdrawal-notice/rescind", methods=["POST"])
@api(("Commissioner",))
def rescind_withdrawal_notice(member_id):
    member = common.get_member(member_id)

    if member["status"] != "WITHDRAWAL_NOTICED":
        raise ApiError("ERR_MEMBER_STATE_INVALID")

    for action in db.membership_actions.values():
        if (
            action["member_id"] == member["id"]
            and action["action_type"] == "WITHDRAW"
            and action["status"] in ("VOTING", "APPROVED", "EXECUTED")
        ):
            raise ApiError("ERR_MEMBER_STATE_INVALID")
    if member["exit_settlement_paid_cents"] != 0:
        raise ApiError("ERR_MEMBER_STATE_INVALID")

    member["status"] = "FULL_SHARE"
    member_service.apply_phase_schedule(member)
    member["withdrawal_notice_at"] = None
    member["notice_days"] = None
    member["withdrawal_effective_fiscal_year"] = None
    member["notice_multiplier_bps"] = 0
    member["base_assessment_cents"] = 0
    member["surcharge_bracket_bps"] = 0
    member["surcharge_cents"] = 0
    member["exit_settlement_total_cents"] = 0
    member["exit_settlement_paid_cents"] = 0
    touch(member)
    return response.single(serializers.member(member))


# ---------------------------------------------------------------------------
# GET /members/{id}/schedule-compliance
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/schedule-compliance", methods=["GET"])
@api(
    (
        "Commissioner",
        "ComplianceOfficer",
        "ScheduleCoordinator",
        "Auditor",
        "PlatformAdmin",
        "MemberRepresentative",
    )
)
def read_schedule_compliance(member_id):
    member = common.get_member(member_id)
    return response.single(compliance.breakdown(member))


# ---------------------------------------------------------------------------
# GET /members/{id}/postseason-unit-valuation
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/postseason-unit-valuation", methods=["GET"])
@api(
    (
        "Commissioner",
        "FinanceOfficer",
        "Treasurer",
        "Auditor",
        "PlatformAdmin",
        "MemberRepresentative",
    )
)
def read_postseason_unit_valuation(member_id):
    member = common.get_member(member_id)
    conference = db.conference
    variant, window_start, window_end = calc.valuation_window(
        member["status"], conference["current_fiscal_year"]
    )
    count = member_service.validated_unit_count(
        member["id"], window=(window_start, window_end)
    )
    return response.single(
        {
            "member_id": member["id"],
            "variant": variant,
            "window_start_fiscal_year": window_start,
            "window_end_fiscal_year": window_end,
            "validated_unit_count": count,
            "valuation_cents": calc.valuation_cents(count, conference["unit_value_cents"]),
        }
    )


# ---------------------------------------------------------------------------
# GET /members/{id}/exit-settlement
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/exit-settlement", methods=["GET"])
@api(
    (
        "Commissioner",
        "FinanceOfficer",
        "Treasurer",
        "Auditor",
        "PlatformAdmin",
        "MemberRepresentative",
    )
)
def read_exit_settlement(member_id):
    member = common.get_member(member_id)
    total = member["exit_settlement_total_cents"]
    paid = member["exit_settlement_paid_cents"]
    return response.single(
        {
            "member_id": member["id"],
            "notice_days": member["notice_days"],
            "notice_multiplier_bps": member["notice_multiplier_bps"],
            "base_assessment_cents": member["base_assessment_cents"],
            "surcharge_bracket_bps": member["surcharge_bracket_bps"],
            "surcharge_cents": member["surcharge_cents"],
            "exit_settlement_total_cents": total,
            "exit_settlement_paid_cents": paid,
            "remaining_balance_cents": total - paid,
        }
    )


# ---------------------------------------------------------------------------
# GET /members/{id}/distribution-lines
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/distribution-lines", methods=["GET"])
@api(
    (
        "Commissioner",
        "FinanceOfficer",
        "Treasurer",
        "Auditor",
        "PlatformAdmin",
        "MemberRepresentative",
    )
)
def list_member_distribution_lines(member_id):
    common.get_member(member_id)
    lines = [
        line
        for line in db.distribution_lines.values()
        if line["member_id"] == member_id
    ]
    criteria = {"status": common.string_filter("status")}
    return common.listing(lines, serializers.distribution_line, criteria=criteria)


# ---------------------------------------------------------------------------
# GET /members/{id}/postseason-units
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/postseason-units", methods=["GET"])
@api(
    (
        "Commissioner",
        "FinanceOfficer",
        "Auditor",
        "ComplianceOfficer",
        "PlatformAdmin",
        "MemberRepresentative",
    )
)
def list_member_postseason_units(member_id):
    common.get_member(member_id)
    units = [
        unit for unit in db.postseason_units.values() if unit["member_id"] == member_id
    ]
    criteria = {
        "fiscal_year": common.int_filter("fiscal_year"),
        "status": common.string_filter("status"),
    }
    return common.listing(units, serializers.postseason_unit, criteria=criteria)


# ---------------------------------------------------------------------------
# GET /members/{id}/ballots
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/ballots", methods=["GET"])
@api(
    (
        "Commissioner",
        "ComplianceOfficer",
        "Auditor",
        "PlatformAdmin",
        "MemberRepresentative",
    )
)
def list_member_ballots(member_id):
    common.get_member(member_id)
    ballots = [
        ballot for ballot in db.ballots.values() if ballot["member_id"] == member_id
    ]
    criteria = {"status": common.string_filter("status")}
    return common.listing(ballots, serializers.ballot, criteria=criteria)


# ---------------------------------------------------------------------------
# POST /members/{id}/bowl-appearances  |  GET /members/{id}/bowl-appearances
# ---------------------------------------------------------------------------


@bp.route("/members/<member_id>/bowl-appearances", methods=["POST"])
@api(
    ("Commissioner", "ComplianceOfficer", "MemberRepresentative"), owner=own_path_member
)
def submit_bowl_appearance(member_id):
    member = common.get_member(member_id)
    body = raw_body()

    fiscal_year = validation.get_int(body, "fiscal_year", minimum=None)
    event_name = validation.get_str(body, "event_name")
    event_tier = validation.get_enum(body, "event_tier", ("BOWL", "TOURNAMENT"))
    payout_cents = validation.get_int(body, "payout_cents")
    submitted_expense_cents = validation.get_int(body, "submitted_expense_cents")
    travel_miles = validation.get_int(body, "travel_miles")
    units_claimed = validation.get_int(body, "units_claimed")

    if member["status"] in WRITE_BLOCKED_STATUSES:
        raise ApiError("ERR_MEMBER_STATE_INVALID")

    appearance = base_record()
    appearance.update(
        {
            "member_id": member["id"],
            "fiscal_year": fiscal_year,
            "event_name": event_name,
            "event_tier": event_tier,
            "payout_cents": payout_cents,
            "submitted_expense_cents": submitted_expense_cents,
            "travel_miles": travel_miles,
            "units_claimed": units_claimed,
            "allowable_expense_cents": 0,
            "travel_allowance_cents": 0,
            "reimbursement_ceiling_cents": 0,
            "reimbursed_cents": 0,
            "residual_to_pool_cents": 0,
            "status": "SUBMITTED",
            "revision_round": 0,
        }
    )
    db.bowl_appearances[appearance["id"]] = appearance
    mint_postseason_units(appearance)
    return response.single(serializers.bowl_appearance(appearance), 201)


def mint_postseason_units(appearance):
    """Mint units_claimed PROVISIONAL units with 1-based unit_index."""
    for index in range(1, appearance["units_claimed"] + 1):
        unit = base_record(versioned=False)
        unit.update(
            {
                "bowl_appearance_id": appearance["id"],
                "member_id": appearance["member_id"],
                "fiscal_year": appearance["fiscal_year"],
                "unit_index": index,
                "status": "PROVISIONAL",
            }
        )
        db.postseason_units[unit["id"]] = unit


@bp.route("/members/<member_id>/bowl-appearances", methods=["GET"])
@api(
    (
        "Commissioner",
        "FinanceOfficer",
        "Auditor",
        "ComplianceOfficer",
        "PlatformAdmin",
        "MemberRepresentative",
    )
)
def list_member_bowl_appearances(member_id):
    common.get_member(member_id)
    appearances = [
        appearance
        for appearance in db.bowl_appearances.values()
        if appearance["member_id"] == member_id
    ]
    criteria = {
        "fiscal_year": common.int_filter("fiscal_year"),
        "status": common.string_filter("status"),
    }
    return common.listing(appearances, serializers.bowl_appearance, criteria=criteria)
