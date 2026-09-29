"""Eligible gains, deferral elections, inclusion events and step-up elections."""

from decimal import Decimal

from flask import Blueprint

import calc
import derive
from core import (
    API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_FUND_MANAGER, ROLE_INVESTOR,
    ROLE_PLATFORM_ADMIN, ZERO2, ZERO4, authenticate, fail, get, insert,
    must_get, must_ref, now_logical, pagination, q4, rows, touch, whole_days,
)
from schema import F, parse_body
from support import guard_state, guard_transition, investor_scope, listing, one

bp = Blueprint("gain_routes", __name__, url_prefix=API_PREFIX)

GAIN_CHARACTERS = ("SHORT_TERM_CAPITAL", "LONG_TERM_CAPITAL",
                   "SECTION_1231_NET", "ORDINARY")
DEADLINE_BASES = ("SALE_DATE", "PARTNERSHIP_YEAR_END", "SECTION_1231_YEAR_END")
REVOKE_REASONS = ("INVESTOR_WITHDRAWAL", "FUND_REJECTED", "ADMIN_CORRECTION")
EVENT_TYPES = ("SALE_OF_INTEREST", "GIFT_TRANSFER", "FUND_DECERTIFICATION",
               "PARTIAL_REDEMPTION", "DEC_31_2026_STATUTORY")
ONE4 = Decimal("1.0000")


def _gain_character_gate(gain_character, deadline_basis):
    if gain_character == "ORDINARY":
        fail("ERR_GAIN_NOT_ELIGIBLE", "Ordinary income is never deferrable")
    if (deadline_basis == "SECTION_1231_YEAR_END"
            and gain_character != "SECTION_1231_NET"):
        fail("ERR_GAIN_NOT_ELIGIBLE",
             "SECTION_1231_YEAR_END requires gain_character SECTION_1231_NET")


# ---------------------------------------------------------------------------
# Eligible gains
# ---------------------------------------------------------------------------

@bp.post("/eligible-gains")
def create_gain():
    authenticate((ROLE_INVESTOR, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("investor_id", "string", non_blank=True),
        F("gain_character", "enum", enum=GAIN_CHARACTERS),
        F("eligible_amount", "money", gt="0.00"),
        F("realization_date", "datetime"),
        F("deadline_basis", "enum", enum=DEADLINE_BASES),
        F("pass_through_year_end", "datetime", required=False),
    ])
    supplied = "pass_through_year_end" in body["_present"]
    if body["deadline_basis"] == "SALE_DATE":
        if supplied:
            fail("ERR_INVALID_REQUEST",
                 "pass_through_year_end is forbidden when deadline_basis is SALE_DATE")
    elif not supplied:
        fail("ERR_INVALID_REQUEST",
             "pass_through_year_end is required when deadline_basis is not SALE_DATE")
    investor = must_ref("investors", body["investor_id"])
    investor_scope(body["investor_id"])
    _gain_character_gate(body["gain_character"], body["deadline_basis"])
    basis_date = calc.window_basis_date(body["deadline_basis"],
                                        body["realization_date"],
                                        body["pass_through_year_end"])
    gain = insert("eligible_gains", {
        "investor_id": investor["id"],
        "gain_character": body["gain_character"],
        "eligible_amount": body["eligible_amount"],
        "realization_date": body["realization_date"],
        "deadline_basis": body["deadline_basis"],
        "pass_through_year_end": body["pass_through_year_end"],
        "window_basis_date": basis_date,
        "investment_deadline": calc.investment_deadline(basis_date),
        "elected_amount": ZERO2,
        "unelected_amount": body["eligible_amount"],
        "status": "ELIGIBLE",
        "expired_at": None,
    })
    derive.recompute_investor(investor)
    return one(gain, 201)


@bp.get("/eligible-gains/<gain_id>")
def read_gain(gain_id):
    authenticate((ROLE_INVESTOR, ROLE_COMPLIANCE_OFFICER, ROLE_PLATFORM_ADMIN))
    gain = must_get("eligible_gains", gain_id)
    investor_scope(gain["investor_id"])
    return one(gain)


@bp.get("/eligible-gains")
def list_gains():
    authenticate((ROLE_INVESTOR, ROLE_COMPLIANCE_OFFICER, ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("eligible_gains", [("investor_id", "investor_id"),
                                      ("status", "status"),
                                      ("deadline_basis", "deadline_basis")],
                   page)


@bp.get("/eligible-gains/<gain_id>/deferral-elections")
def gain_elections(gain_id):
    authenticate((ROLE_INVESTOR, ROLE_COMPLIANCE_OFFICER, ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("eligible_gains", gain_id)
    return listing("deferral_elections", [("status", "status")], page,
                   extra=lambda r: r["eligible_gain_id"] == gain_id)


# ---------------------------------------------------------------------------
# Deferral elections
# ---------------------------------------------------------------------------

@bp.post("/deferral-elections")
def create_election():
    authenticate((ROLE_INVESTOR, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("eligible_gain_id", "string", non_blank=True),
        F("fund_id", "string", non_blank=True),
        F("elected_amount", "money", gt="0.00"),
        F("expected_fund_version", "integer"),
    ])
    gain = must_ref("eligible_gains", body["eligible_gain_id"])
    fund = must_ref("funds", body["fund_id"])
    investor_scope(gain["investor_id"])
    if fund["certification_status"] == "DECERTIFIED":
        fail("ERR_FUND_DECERTIFIED", "Fund is decertified")
    if fund["certification_status"] != "SELF_CERTIFIED":
        fail("ERR_FUND_NOT_CERTIFIED", "Fund is not self-certified")
    if body["expected_fund_version"] != fund["version"]:
        fail("ERR_STALE_FUND_VERSION",
             "expected_fund_version %s does not match current version %s"
             % (body["expected_fund_version"], fund["version"]))
    investor = get("investors", gain["investor_id"])
    if investor is None or investor["compliance_attestation_status"] != "ATTESTED":
        fail("ERR_INVESTOR_NOT_ATTESTED", "Investor is not ATTESTED")
    _gain_character_gate(gain["gain_character"], gain["deadline_basis"])
    investment_date = now_logical()
    days = calc.days_from_basis(investment_date, gain["window_basis_date"])
    if days > calc.DEFERRAL_WINDOW_DAYS:
        fail("ERR_180_DAY_WINDOW_CLOSED",
             "The 180-day window closed %d days ago"
             % (days - calc.DEFERRAL_WINDOW_DAYS))
    if days < 0:
        fail("ERR_180_DAY_WINDOW_NOT_OPEN", "The 180-day window is not open yet")
    if body["elected_amount"] > gain["unelected_amount"]:
        fail("ERR_ELECTED_AMOUNT_EXCEEDS_GAIN",
             "elected_amount exceeds the gain's unelected_amount")
    election = insert("deferral_elections", {
        "eligible_gain_id": gain["id"],
        "fund_id": fund["id"],
        "investor_id": gain["investor_id"],
        "elected_amount": body["elected_amount"],
        "investment_date": investment_date,
        "days_from_basis": days,
        "initial_basis": ZERO2,
        "current_basis": ZERO2,
        "step_up_applied_pct": ZERO4,
        "holding_tier": "UNDER_FIVE",
        "included_amount": ZERO2,
        "included_fraction_total": ZERO4,
        "deferred_remaining": body["elected_amount"],
        "status": "DEFERRED",
        "revoked_reason_code": "NONE",
    })
    derive.recompute_gain(gain)
    derive.recompute_fund_committed(fund)
    touch(fund)
    derive.recompute_investor(investor)
    return one(election, 201)


@bp.get("/deferral-elections/<election_id>")
def read_election(election_id):
    authenticate((ROLE_INVESTOR, ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("deferral_elections", election_id))


@bp.get("/deferral-elections")
def list_elections():
    authenticate((ROLE_INVESTOR, ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("deferral_elections", [("fund_id", "fund_id"),
                                          ("investor_id", "investor_id"),
                                          ("eligible_gain_id", "eligible_gain_id"),
                                          ("status", "status")], page)


@bp.post("/deferral-elections/<election_id>/revoke")
def revoke_election(election_id):
    authenticate((ROLE_INVESTOR, ROLE_PLATFORM_ADMIN))
    body = parse_body([F("revoked_reason_code", "enum", enum=REVOKE_REASONS)])
    election = must_get("deferral_elections", election_id)
    investor_scope(election["investor_id"])
    guard_state(election["status"], ("DEFERRED",),
                ("REVOKED", "INCLUDED_FULL"))
    if rows("inclusion_events",
            lambda v: v["deferral_election_id"] == election_id):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An election carrying inclusion events may not be revoked")
    election["status"] = "REVOKED"
    election["revoked_reason_code"] = body["revoked_reason_code"]
    election["deferred_remaining"] = ZERO2
    touch(election)
    gain = get("eligible_gains", election["eligible_gain_id"])
    if gain is not None:
        derive.recompute_gain(gain)
    fund = get("funds", election["fund_id"])
    if fund is not None:
        derive.recompute_fund_committed(fund)
    derive.recompute_investor_of(election)
    return one(election)


# ---------------------------------------------------------------------------
# Inclusion events
# ---------------------------------------------------------------------------

@bp.post("/deferral-elections/<election_id>/inclusion-events")
def create_inclusion_event(election_id):
    authenticate((ROLE_INVESTOR, ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("event_type", "enum", enum=EVENT_TYPES),
        F("included_fraction", "pct", gt="0.0000", lte="1.0000"),
    ])
    election = must_get("deferral_elections", election_id)
    investor_scope(election["investor_id"])
    guard_state(election["status"],
                ("DEFERRED", "INCLUDED_PARTIAL", "STEPPED_UP"),
                ("INCLUDED_FULL", "REVOKED"))
    fraction = body["included_fraction"]
    if election["status"] == "STEPPED_UP" and fraction != ONE4:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A stepped-up election may only be included in full")
    if q4(election["included_fraction_total"] + fraction) > ONE4:
        fail("ERR_INCLUSION_FRACTION_EXCEEDS_REMAINING",
             "included_fraction exceeds the fraction still outstanding")
    event_date = now_logical()
    amounts = calc.inclusion_amounts(election, fraction, event_date)
    event = insert("inclusion_events", {
        "deferral_election_id": election["id"],
        "event_type": body["event_type"],
        "included_fraction": fraction,
        "event_date": event_date,
        "holding_days": amounts["holding_days"],
        "holding_tier_applied": amounts["holding_tier_applied"],
        "gross_inclusion_amount": amounts["gross_inclusion_amount"],
        "basis_offset_amount": amounts["basis_offset_amount"],
        "net_inclusion_amount": amounts["net_inclusion_amount"],
        "is_full": amounts["is_full"],
    })
    election["status"] = "INCLUDED_FULL" if amounts["is_full"] else "INCLUDED_PARTIAL"
    touch(election)
    derive.recompute_election(election)
    derive.recompute_investor_of(election)
    return one(event, 201)


@bp.get("/deferral-elections/<election_id>/inclusion-events")
def list_inclusion_events(election_id):
    authenticate((ROLE_INVESTOR, ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("deferral_elections", election_id)
    return listing("inclusion_events", [("event_type", "event_type")], page,
                   extra=lambda r: r["deferral_election_id"] == election_id)


# ---------------------------------------------------------------------------
# Step-up elections
# ---------------------------------------------------------------------------

@bp.post("/deferral-elections/<election_id>/step-up-elections")
def create_step_up(election_id):
    authenticate((ROLE_INVESTOR, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("claimed_fmv", "money", gt="0.00"),
        F("disposition_sequence", "string_array", required=False),
    ])
    election = must_get("deferral_elections", election_id)
    sequence = body["disposition_sequence"]
    supplied = "disposition_sequence" in body["_present"]
    assets = []
    if supplied:
        for asset_id in sequence:
            assets.append(must_ref("fund_assets", asset_id))
    investor_scope(election["investor_id"])
    investor = get("investors", election["investor_id"])
    if investor is None or investor["compliance_attestation_status"] != "ATTESTED":
        fail("ERR_INVESTOR_NOT_ATTESTED", "Investor is not ATTESTED")
    election_date = now_logical()
    if election["investment_date"] > election_date:
        fail("ERR_TEN_YEAR_HOLD_NOT_MET",
             "The holding period cannot be evaluated before the investment date")
    if supplied:
        if not sequence:
            fail("ERR_DISPOSITION_SEQUENCE_INVALID",
                 "disposition_sequence must not be empty when supplied")
        if len(set(sequence)) != len(sequence):
            fail("ERR_DISPOSITION_SEQUENCE_INVALID",
                 "disposition_sequence may not repeat an asset")
        for asset in assets:
            if asset["fund_id"] != election["fund_id"]:
                fail("ERR_DISPOSITION_SEQUENCE_INVALID",
                     "Asset '%s' belongs to another fund" % asset["id"])
            if asset["status"] != "HELD":
                fail("ERR_DISPOSITION_SEQUENCE_INVALID",
                     "Asset '%s' is not HELD" % asset["id"])
    if election["status"] == "REVOKED":
        fail("ERR_ELECTION_REVOKED",
             "A revoked election has no qualifying investment to step up")

    holding_days = whole_days(election_date, election["investment_date"])
    fund = get("funds", election["fund_id"])
    prior_full = rows("inclusion_events", lambda v: (
        v["deferral_election_id"] == election["id"] and v["is_full"] is True))
    if holding_days < calc.TEN_YEAR_DAYS:
        status, reason = "DENIED", "HOLD_UNDER_TEN_YEARS"
    elif fund is not None and fund["certification_status"] == "DECERTIFIED":
        status, reason = "DENIED", "FUND_DECERTIFIED"
    elif prior_full:
        status, reason = "DENIED", "PRIOR_FULL_INCLUSION"
    else:
        status, reason = "GRANTED", "NONE"

    step_up = insert("step_up_elections", {
        "deferral_election_id": election["id"],
        "claimed_fmv": body["claimed_fmv"],
        "disposition_sequence": list(sequence) if supplied else None,
        "election_date": election_date,
        "holding_period_days": holding_days,
        "stepped_up_basis": body["claimed_fmv"] if status == "GRANTED" else ZERO2,
        "status": status,
        "denial_reason": reason,
    })

    if status == "GRANTED":
        if election["status"] == "DEFERRED":
            election["status"] = "STEPPED_UP"
        election["current_basis"] = body["claimed_fmv"]
        election["step_up_applied_pct"] = ONE4
        election["holding_tier"] = "TEN_YEAR"
        touch(election)
        if supplied:
            listed = dict((asset["id"], i)
                          for i, asset in enumerate(assets, start=1))
            for asset in rows("fund_assets",
                              lambda a: a["fund_id"] == election["fund_id"]):
                position = listed.get(asset["id"])
                if asset["disposition_sequence_index"] != position:
                    asset["disposition_sequence_index"] = position
                    touch(asset)
        derive.recompute_election(election)
        derive.recompute_investor_of(election)
    return one(step_up, 201)


@bp.get("/deferral-elections/<election_id>/step-up-elections")
def list_step_ups(election_id):
    authenticate((ROLE_INVESTOR, ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("deferral_elections", election_id)
    return listing("step_up_elections", [("status", "status")], page,
                   extra=lambda r: r["deferral_election_id"] == election_id)
