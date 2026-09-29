"""Respondent onboarding, licensing, scoring, committee and restriction (PRD 3.2, 3.6)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import clock
import store
from common import ALL, OPS, arg, eq, need, need_respondent, paged, start, PREFIX
from errors import fail
from response import ok, ok_list
from validate import (body, fbool, fenum, fint, fnum, fstr, q2, validate)

bp = Blueprint("respondents", __name__)

DD_STATES = ("PROSPECT", "DD_IN_PROGRESS", "PENDING_COMMITTEE", "APPROVED",
             "REFRESH_DUE", "UNDER_REFRESH", "REFRESH_OVERDUE", "RESTRICTED",
             "EXITING", "TERMINATED", "DECLINED")
POSTURES = ("OPEN", "SCREEN_ONLY", "WIND_DOWN_ONLY", "BLOCKED")
LICENSE = ("UNVERIFIED", "ACTIVE", "CONDITIONAL", "SUSPENDED", "REVOKED")
STANDING = ("UNVERIFIED", "GOOD_STANDING", "UNDER_ENFORCEMENT", "DEREGISTERED")
RESTRICTION_REASONS = ("UNRESPONSIVE_STRIKES", "ADVERSE_MEDIA", "SANCTIONS_EXPOSURE",
                       "PROHIBITED_NESTING", "REFRESH_LAPSED", "LICENSE_LAPSE",
                       "OFFICER_ACTION")
VARIANTS = ("ONBOARDING_PROVISIONAL", "REFRESH_FINAL")
APPROVED_FAMILY = cascade.APPROVED_FAMILY

CREATORS = ("FIGRelationshipManager", "PlatformAdmin")

CREATE_SPEC = [
    fstr("legal_name", True, 1, 160),
    fstr("swift_bic", True, 8, 11),
    fstr("home_jurisdiction_code", True, 1, None),
    fstr("relationship_manager_user_id", True, 1, None),
    fnum("expected_monthly_volume_usd", True, 0),
    fint("expected_monthly_count", True, 0),
    fenum("license_status", LICENSE, False),
    fstr("regulator_name", False, 0, 160),
    fenum("regulator_standing", STANDING, False),
    fbool("nested_activity_permitted", False),
]

PATCH_SPEC = [
    fstr("legal_name", False, 1, 160),
    fnum("expected_monthly_volume_usd", False, 0),
    fint("expected_monthly_count", False, 0),
    fbool("nested_activity_permitted", False),
    fstr("relationship_manager_user_id", False, 1, None),
    fenum("payment_posture", POSTURES, False),
]


def require_jurisdiction(code):
    profile = store.jurisdiction_by_code(code)
    if profile is None:
        fail("ERR_JURISDICTION_PROFILE_NOT_FOUND",
             "Jurisdiction code %s does not resolve." % code)
    return profile


@bp.post(PREFIX + "/respondents")
def onboard():
    start(CREATORS)
    data = body()
    validate(data, CREATE_SPEC)
    bic = data["swift_bic"]
    if len(bic) not in (8, 11) or not bic.isalnum() or bic != bic.upper():
        fail("ERR_INVALID_REQUEST_BODY",
             "swift_bic must be 8 or 11 uppercase alphanumeric characters.")
    profile = require_jurisdiction(data["home_jurisdiction_code"])
    if profile["sanctions_status"] == "COMPREHENSIVELY_SANCTIONED":
        fail("ERR_HOME_JURISDICTION_SANCTIONED",
             "A respondent in a comprehensively sanctioned jurisdiction cannot be opened.")
    for other in store.all_rows("respondents"):
        if other["swift_bic"] == bic:
            fail("ERR_DUPLICATE_RESOURCE", "swift_bic %s already exists." % bic)
    row = store.insert("respondents", {
        "legal_name": data["legal_name"],
        "swift_bic": bic,
        "home_jurisdiction_code": data["home_jurisdiction_code"],
        "relationship_manager_user_id": data["relationship_manager_user_id"],
        "dd_state": "PROSPECT",
        "payment_posture": "BLOCKED",
        "license_status": data.get("license_status") or "UNVERIFIED",
        "regulator_name": data.get("regulator_name"),
        "regulator_standing": data.get("regulator_standing") or "UNVERIFIED",
        "license_verified_at": None,
        "expected_monthly_volume_usd": q2(data["expected_monthly_volume_usd"]),
        "expected_monthly_count": int(data["expected_monthly_count"]),
        "nested_activity_permitted": bool(data.get("nested_activity_permitted", False)),
        "verified_ownership_pct": Decimal("0.00"),
        "control_chain_complete": False,
        "ownership_verified": False,
        "disclosed_nested_count": 0,
        "undisclosed_nested_count": 0,
        "max_nested_depth": 0,
        "nested_exposure_units": 0,
        "inherent_risk_score": Decimal("0.00"),
        "control_score": Decimal("0.00"),
        "control_credit": Decimal("0.0000"),
        "adverse_media_uplift": Decimal("0.00"),
        "residual_risk_score": Decimal("0.00"),
        "risk_rating": "UNRATED",
        "risk_assessment_variant": "NONE",
        "assessed_by_user_id": None,
        "approved_by_user_id": None,
        "approved_risk_rating": "UNRATED",
        "last_approved_at": None,
        "refresh_due_date": None,
        "unresponsive_strikes": 0,
        "escalation_units": 0,
        "restriction_reason": None,
        "last_risk_assessed_at": None,
    })
    return ok(row, 201)


@bp.get(PREFIX + "/respondents")
def list_respondents():
    start(OPS)
    rows = store.by_seq(store.all_rows("respondents"))
    rows = eq(rows, "dd_state", arg("dd_state"))
    rows = eq(rows, "payment_posture", arg("payment_posture"))
    rows = eq(rows, "risk_rating", arg("risk_rating"))
    rows = eq(rows, "home_jurisdiction_code", arg("home_jurisdiction_code"))
    rows = eq(rows, "license_status", arg("license_status"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/respondents/<respondent_id>")
def read_respondent(respondent_id):
    start(ALL, respondent_id)
    return ok(need_respondent(respondent_id))


@bp.patch(PREFIX + "/respondents/<respondent_id>")
def amend(respondent_id):
    start(CREATORS)
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, PATCH_SPEC)
    cascade.guard_not_closed(resp)
    posture = data.get("payment_posture")
    if posture == "OPEN" and resp["payment_posture"] != "OPEN":
        if resp["dd_state"] != "APPROVED" or int(resp["undisclosed_nested_count"]) != 0:
            fail("ERR_UNDISCLOSED_NESTING_OUTSTANDING",
                 "The posture may only widen to OPEN from APPROVED with no undisclosed nesting.")
    if calc.home_sanctioned(resp):
        fail("ERR_HOME_JURISDICTION_SANCTIONED",
             "A respondent in a comprehensively sanctioned jurisdiction cannot be amended.")
    expectations_moved = False
    if data.get("legal_name") is not None:
        resp["legal_name"] = data["legal_name"]
    if data.get("relationship_manager_user_id") is not None:
        resp["relationship_manager_user_id"] = data["relationship_manager_user_id"]
    if data.get("expected_monthly_volume_usd") is not None:
        new_value = q2(data["expected_monthly_volume_usd"])
        if new_value != resp["expected_monthly_volume_usd"]:
            expectations_moved = True
        resp["expected_monthly_volume_usd"] = new_value
    if data.get("expected_monthly_count") is not None:
        new_count = int(data["expected_monthly_count"])
        if new_count != resp["expected_monthly_count"]:
            expectations_moved = True
        resp["expected_monthly_count"] = new_count
    if data.get("nested_activity_permitted") is not None:
        resp["nested_activity_permitted"] = bool(data["nested_activity_permitted"])
    if posture is not None:
        resp["payment_posture"] = posture
    store.touch(resp)
    if expectations_moved:
        cascade.require_recalibration(resp, "OFFICER_ACTION")
    return ok(resp)


# ------------------------------------------------- licensing verification ----

LICENSE_SPEC = [
    fenum("license_status", LICENSE, True),
    fenum("regulator_standing", STANDING, True),
    fstr("regulator_name", False, 0, 160),
]


@bp.post(PREFIX + "/respondents/<respondent_id>/licensing-verification")
def licensing_verification(respondent_id):
    start(("ComplianceAnalyst", "PlatformAdmin"))
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, LICENSE_SPEC)
    cascade.guard_not_closed(resp)
    status = data["license_status"]
    standing = data["regulator_standing"]
    bad = status in ("SUSPENDED", "REVOKED") or standing == "DEREGISTERED"
    if resp["dd_state"] == "PROSPECT" and bad:
        fail("ERR_LICENSE_NOT_IN_GOOD_STANDING",
             "An unlicensed respondent cannot enter due diligence.")
    resp["license_status"] = status
    resp["regulator_standing"] = standing
    if data.get("regulator_name") is not None:
        resp["regulator_name"] = data["regulator_name"]
    store.set_dt(resp, "license_verified_at", clock.now())
    store.touch(resp)
    if resp["dd_state"] == "PROSPECT":
        if (status in ("ACTIVE", "CONDITIONAL")
                and standing in ("GOOD_STANDING", "UNDER_ENFORCEMENT")
                and not calc.home_sanctioned(resp)):
            resp["dd_state"] = "DD_IN_PROGRESS"
    elif resp["dd_state"] in APPROVED_FAMILY and bad:
        posture = "SCREEN_ONLY" if resp["payment_posture"] != "BLOCKED" else "BLOCKED"
        cascade.restrict(resp, "LICENSE_LAPSE", posture)
    return ok(resp)


# ------------------------------------------------------- risk assessment -----

VARIANT_STATES = {
    "ONBOARDING_PROVISIONAL": ("PROSPECT", "DD_IN_PROGRESS", "PENDING_COMMITTEE"),
    "REFRESH_FINAL": ("APPROVED", "REFRESH_DUE", "UNDER_REFRESH",
                      "REFRESH_OVERDUE", "RESTRICTED"),
}


@bp.post(PREFIX + "/respondents/<respondent_id>/risk-assessment")
def risk_assessment(respondent_id):
    ctx = start(("ComplianceAnalyst",))
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, [fenum("variant", VARIANTS, True)])
    if resp["dd_state"] in ("DECLINED", "TERMINATED"):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "A declined or terminated respondent cannot be scored.")
    cascade.guard_not_closed(resp)
    variant = data["variant"]
    if resp["dd_state"] not in VARIANT_STATES[variant]:
        fail("ERR_INVALID_RESPONDENT_STATE",
             "Variant %s is not permitted while dd_state is %s."
             % (variant, resp["dd_state"]))
    cascade.run_risk_assessment(resp, variant, ctx.user_id)
    if variant == "ONBOARDING_PROVISIONAL" and resp["dd_state"] == "DD_IN_PROGRESS":
        if _ready_for_committee(resp):
            resp["dd_state"] = "PENDING_COMMITTEE"
    return ok(resp)


def _ready_for_committee(resp):
    if not resp["ownership_verified"]:
        return False
    if not any(q["state"] == "ASSESSED" for q in store.questionnaires_of(resp["id"])):
        return False
    if resp["license_verified_at"] is None:
        return False
    if resp["license_status"] not in ("ACTIVE", "CONDITIONAL"):
        return False
    for row in store.nested_of(resp["id"]):
        if row["state"] == "UNDISCLOSED_DETECTED":
            return False
    return True


# ----------------------------------------------------- committee decision ----

NOTCH_UP = {"PROHIBITED": "HIGH", "HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}


@bp.post(PREFIX + "/respondents/<respondent_id>/approval")
def approval(respondent_id):
    ctx = start(("CommitteeApprover",))
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, [
        fenum("action", ("APPROVE", "DECLINE", "RETURN"), True),
        fstr("decision_note", False, 0, 2000),
    ])
    if resp["dd_state"] != "PENDING_COMMITTEE":
        fail("ERR_INVALID_RESPONDENT_STATE",
             "A committee decision requires dd_state PENDING_COMMITTEE.")
    if resp["assessed_by_user_id"] is not None and ctx.user_id == resp["assessed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approver may not be the analyst who scored the respondent.")
    action = data["action"]
    rating = resp["risk_rating"]
    if data.get("override_risk_rating") is not None:
        rating = NOTCH_UP.get(rating, rating)
    if action == "APPROVE":
        _approve(resp, ctx, rating)
    elif action == "DECLINE":
        resp["dd_state"] = "DECLINED"
        resp["payment_posture"] = "BLOCKED"
        store.touch(resp)
        cascade.terminate_all_nested(resp)
        cascade.abandon_open_rfis(resp)
    else:
        resp["dd_state"] = "DD_IN_PROGRESS"
        store.touch(resp)
    return ok(resp)


def _approve(resp, ctx, rating):
    for rfi in store.rfis_of(resp["id"]):
        if rfi["state"] in ("OVERDUE", "ESCALATED"):
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "An outstanding overdue information request blocks approval.")
    if (resp["license_status"] not in ("ACTIVE", "CONDITIONAL")
            or resp["regulator_standing"] != "GOOD_STANDING"
            or resp["license_verified_at"] is None):
        fail("ERR_LICENSE_NOT_IN_GOOD_STANDING",
             "Approval requires a verified licence in good standing.")
    if not resp["ownership_verified"]:
        fail("ERR_OWNERSHIP_CHAIN_INCOMPLETE",
             "Approval requires a verified ownership chain.")
    profile = calc.home_profile(resp)
    ceiling = profile["max_permitted_risk_rating"] if profile else "HIGH"
    if rating in ("PROHIBITED", "UNRATED") or \
            calc.RATING_RANK.get(rating, 99) > calc.RATING_RANK.get(ceiling, 0):
        fail("ERR_RATING_EXCEEDS_JURISDICTION_CEILING",
             "The rating exceeds the jurisdiction ceiling.")
    if int(resp["undisclosed_nested_count"]) != 0 or \
            any(r["state"] == "PROHIBITED" for r in store.nested_of(resp["id"])):
        fail("ERR_UNDISCLOSED_NESTING_OUTSTANDING",
             "Undisclosed or prohibited nesting blocks approval.")
    if calc.home_sanctioned(resp):
        fail("ERR_HOME_JURISDICTION_SANCTIONED",
             "A comprehensively sanctioned home jurisdiction blocks approval.")
    resp["dd_state"] = "APPROVED"
    resp["approved_risk_rating"] = rating
    resp["approved_by_user_id"] = ctx.user_id
    store.set_dt(resp, "last_approved_at", clock.now())
    if resp["payment_posture"] == "BLOCKED":
        resp["payment_posture"] = "OPEN" if rating in ("LOW", "MEDIUM") else "SCREEN_ONLY"
    store.touch(resp)
    cascade.write_refresh_due_date(resp)


# ------------------------------------------------------------ restriction ----

RESTRICTION_SPEC = [
    fenum("action", ("RESTRICT", "LIFT", "CLEAR_SCREENING"), True),
    fenum("restriction_reason", RESTRICTION_REASONS, False),
    fenum("payment_posture", POSTURES, False),
]


@bp.post(PREFIX + "/respondents/<respondent_id>/restriction")
def restriction(respondent_id):
    start(("SanctionsOfficer", "ComplianceAnalyst"))
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, RESTRICTION_SPEC)
    action = data["action"]
    if action == "RESTRICT":
        if data.get("restriction_reason") is None:
            fail("ERR_INVALID_REQUEST_BODY", "restriction_reason is required to restrict.")
        if resp["dd_state"] not in APPROVED_FAMILY:
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "A restriction requires an approved-family dd_state.")
        cascade.guard_not_closed(resp)
        posture = data.get("payment_posture")
        if posture not in ("SCREEN_ONLY", "BLOCKED"):
            posture = "BLOCKED"
        cascade.restrict(resp, data["restriction_reason"], posture)
    elif action == "LIFT":
        _lift(resp)
    else:
        _clear_screening(resp)
    return ok(resp)


def _lift(resp):
    if resp["dd_state"] != "RESTRICTED":
        fail("ERR_INVALID_RESPONDENT_STATE", "A lift requires dd_state RESTRICTED.")
    cascade.guard_not_closed(resp)
    if int(resp["unresponsive_strikes"]) != 0:
        fail("ERR_INVALID_RESPONDENT_STATE",
             "A lift requires unresponsive_strikes to be 0.")
    for event in store.media_of(resp["id"]):
        if event["adjudication_state"] == "NEW":
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "An untriaged adverse-media item blocks the lift.")
    for row in store.nested_of(resp["id"]):
        if row["state"] == "PROHIBITED":
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "A prohibited nested relationship blocks the lift.")
    if resp["license_status"] not in ("ACTIVE", "CONDITIONAL"):
        fail("ERR_INVALID_RESPONDENT_STATE", "A lift requires a live licence.")
    if resp["regulator_standing"] not in ("GOOD_STANDING", "UNDER_ENFORCEMENT"):
        fail("ERR_INVALID_RESPONDENT_STATE", "A lift requires regulator standing.")
    if calc.home_sanctioned(resp):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "A lift is impossible from a comprehensively sanctioned jurisdiction.")
    if resp["last_approved_at"] is None:
        fail("ERR_INVALID_RESPONDENT_STATE",
             "A lift requires a prior approval.")
    for row in store.nested_of(resp["id"]):
        if row["state"] == "UNDISCLOSED_DETECTED":
            fail("ERR_UNDISCLOSED_NESTING_OUTSTANDING",
                 "Undisclosed nesting blocks the lift.")
    resp["dd_state"] = "APPROVED"
    resp["restriction_reason"] = None
    if resp["payment_posture"] == "BLOCKED":
        resp["payment_posture"] = "SCREEN_ONLY"
    store.touch(resp)
    for row in store.nested_of(resp["id"]):
        if row["state"] != "SUSPENDED":
            continue
        reason, _err = cascade.prohibition_ladder(row, resp)
        if reason is None:
            row["state"] = "CONFIRMED"
            store.touch(row)
    cascade.nested_rollup(resp)


def _clear_screening(resp):
    if resp["dd_state"] not in ("APPROVED", "REFRESH_DUE", "UNDER_REFRESH"):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "Clearing screening requires an approved or in-refresh dd_state.")
    cascade.guard_not_closed(resp)
    for rfi in store.rfis_of(resp["id"]):
        if rfi["severity"] == "CRITICAL" and rfi["state"] in ("SENT", "OVERDUE", "ESCALATED"):
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "An open critical information request blocks clearing screening.")
    last_approved = store.dt(resp, "last_approved_at")
    for cycle in store.refreshes_of(resp["id"]):
        if cycle["state"] != "LAPSED":
            continue
        due = store.dt(cycle, "scheduled_due_date")
        if last_approved is None or (due is not None and due >= last_approved):
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "A lapsed refresh cycle blocks clearing screening.")
    if resp["payment_posture"] == "SCREEN_ONLY":
        resp["payment_posture"] = "OPEN"
    store.touch(resp)
