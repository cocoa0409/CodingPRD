"""Regulator inquiries (PRD 3.8) and revenue-impact models (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import resolve
import serialize
import shape
import store
from errors import ApiError
from routes_config import CHANNEL_TYPES

bp = Blueprint("regulator", __name__)

INQUIRY_READERS = [auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER, auth.REGULATORY_LIAISON]
MODEL_READERS = [auth.PLATFORM_ADMIN, auth.REVENUE_MANAGER, auth.COMPLIANCE_OFFICER]
WITHDRAWABLE_FROM = ("RECEIVED", "RESPONSE_DRAFTED", "RESPONSE_SUBMITTED",
                     "REMEDIATION_REQUIRED")
SCENARIOS = ("STATUS_QUO", "FULL_ROLL_IN", "PARTIAL_ROLL_IN")
VARIANTS = ("RATE_PARITY", "TAX_ABSORBED")


def _channel_type_of(booking):
    channel = store.channels.get(booking["channel_id"])
    return channel["channel_type"] if channel is not None else None


def exposure_cents(inquiry):
    """PRD 3.8: the plain integer sum of the in-scope gap-bearing bookings' gaps."""
    scope = inquiry["channel_scope"]
    total = 0
    for booking in store.bookings_of_property(inquiry["property_id"]):
        if _channel_type_of(booking) not in scope:
            continue
        if booking["disclosure_status"] not in derive.GAP_BEARING_BOOKING_STATUSES:
            continue
        total += booking["quote_disclosure_gap_cents"]
    return total


def _refresh_exposure(inquiry):
    inquiry["exposure_cents"] = exposure_cents(inquiry)
    return inquiry["exposure_cents"]


def _in_scope_profiles(inquiry):
    """The property's profiles on channels the docket names, oldest first."""
    out = []
    for profile in store.profiles_of_property(inquiry["property_id"]):
        channel = store.channels.get(profile["channel_id"])
        if channel is not None and channel["channel_type"] in inquiry["channel_scope"]:
            out.append(profile)
    return store.sort_created(out)


def _due(inquiry):
    if clock.now() > inquiry["response_due_at"]:
        raise ApiError("ERR_RESPONSE_WINDOW_EXPIRED", "The response window has lapsed.")


# ------------------------------------------------------------------ inquiries

@bp.post("/regulator-inquiries")
def create_inquiry():
    auth.require([auth.PLATFORM_ADMIN, auth.REGULATORY_LIAISON])
    payload = shape.body()
    jurisdiction_id = shape.identifier(payload, "jurisdiction_id")
    property_id = shape.identifier(payload, "property_id")
    docket_number = shape.string(payload, "docket_number", min_len=1, max_len=64)
    scope = shape.string_array(payload, "channel_scope", allow_empty=True)
    response_due_at = shape.timestamp(payload, "response_due_at")
    # rank 7 — the deadline must be strictly in the logical future
    if response_due_at <= clock.now():
        raise ApiError("ERR_INVALID_REQUEST",
                       "response_due_at must be strictly after the logical clock.")

    # rank 8 — body references, in the order the endpoint declares its inputs
    jurisdiction = resolve.jurisdiction(jurisdiction_id)
    prop = resolve.property_(property_id)

    if prop["jurisdiction_id"] != jurisdiction["id"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The inquiring jurisdiction must be the property's own jurisdiction.")

    # rank 26 — uniqueness of (jurisdiction_id, docket_number)
    for existing in store.inquiries.values():
        if existing["jurisdiction_id"] == jurisdiction["id"] \
                and existing["docket_number"] == docket_number:
            raise ApiError("ERR_DUPLICATE_DOCKET_NUMBER",
                           "That docket number already exists in this jurisdiction.")

    # rank 35 — the scope must be non-empty and every member a channel_type literal
    if not scope or any(value not in CHANNEL_TYPES for value in scope):
        raise ApiError("ERR_INQUIRY_SCOPE_EMPTY",
                       "channel_scope must be a non-empty array of channel_type literals.")

    row = {
        "jurisdiction_id": jurisdiction["id"],
        "property_id": prop["id"],
        "docket_number": docket_number,
        "channel_scope": list(scope),
        "response_due_at": response_due_at,
        "status": "RECEIVED",
        "response_summary": None,
        "remediation_directive": None,
        "remediation_summary": None,
        "rejection_reason": None,
        "withdrawal_reason": None,
        "drafted_by_user_id": None,
        "submitted_by_user_id": None,
        "flagged_profile_ids": [],
        "remediation_round": 0,
        "exposure_cents": 0,
    }
    store.stamp_new(row)
    store.inquiries[row["id"]] = row
    _refresh_exposure(row)
    derive.recompute_property(prop)
    return envelope.created(serialize.inquiry(row))


@bp.get("/regulator-inquiries/<identifier>")
def read_inquiry(identifier):
    auth.require(INQUIRY_READERS)
    return envelope.ok(serialize.inquiry(resolve.inquiry(identifier)))


@bp.get("/regulator-inquiries")
def list_inquiries():
    auth.require(INQUIRY_READERS)
    rows = envelope.apply_filters(
        store.sort_default(store.inquiries.values()),
        [("jurisdiction_id", envelope.str_filter("jurisdiction_id")),
         ("property_id", envelope.str_filter("property_id")),
         ("status", envelope.str_filter("status")),
         ("docket_number", envelope.str_filter("docket_number"))],
    )
    return envelope.page(rows, serialize.inquiry)


@bp.post("/regulator-inquiries/<identifier>/draft-response")
def draft_response(identifier):
    user_id, _role = auth.require([auth.REGULATORY_LIAISON])
    inquiry = resolve.inquiry(identifier)
    payload = shape.body()
    summary = shape.string(payload, "response_summary", min_len=None)

    if inquiry["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED docket may be drafted.")
    _due(inquiry)

    inquiry["status"] = "RESPONSE_DRAFTED"
    inquiry["response_summary"] = summary
    inquiry["drafted_by_user_id"] = user_id
    store.touch(inquiry)
    return envelope.ok(serialize.inquiry(inquiry))


@bp.post("/regulator-inquiries/<identifier>/submit-response")
def submit_response(identifier):
    user_id, _role = auth.require([auth.REGULATORY_LIAISON])
    inquiry = resolve.inquiry(identifier)

    # rank 9 — segregation of duties precedes the state gate
    if inquiry["drafted_by_user_id"] is not None and user_id == inquiry["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The submitter must differ from the drafter.")
    if inquiry["status"] != "RESPONSE_DRAFTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a RESPONSE_DRAFTED docket may be submitted.")
    _due(inquiry)

    inquiry["status"] = "RESPONSE_SUBMITTED"
    inquiry["submitted_by_user_id"] = user_id
    _refresh_exposure(inquiry)
    store.touch(inquiry)
    return envelope.ok(serialize.inquiry(inquiry))


@bp.post("/regulator-inquiries/<identifier>/require-remediation")
def require_remediation(identifier):
    auth.require([auth.PLATFORM_ADMIN])
    inquiry = resolve.inquiry(identifier)
    payload = shape.body()
    directive = shape.string(payload, "remediation_directive", min_len=None)

    if inquiry["status"] not in ("RESPONSE_SUBMITTED", "REMEDIATION_SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Remediation is ordered from RESPONSE_SUBMITTED or REMEDIATION_SUBMITTED.")

    prop = store.properties.get(inquiry["property_id"])

    # link one — the directive and the round counter
    inquiry["status"] = "REMEDIATION_REQUIRED"
    inquiry["remediation_directive"] = directive
    inquiry["remediation_round"] = inquiry["remediation_round"] + 1

    # link two — flag every in-scope DEPLOYED path, oldest first
    for profile in _in_scope_profiles(inquiry):
        if profile["status"] == "DEPLOYED":
            profile["status"] = "FLAGGED"
            store.touch(profile)
            inquiry["flagged_profile_ids"].append(profile["id"])

    # link three — the property's minimum and posture
    prop["min_channel_disclosure_score"] = derive.min_channel_disclosure_score(prop)
    prop["disclosure_posture"] = calc.posture_for(prop["min_channel_disclosure_score"])

    # link four — sweep the property's still-unaudited quotes
    derive.sweep_unaudited_quotes(prop)

    derive.recompute_property(prop, force=True)
    _refresh_exposure(inquiry)
    store.touch(inquiry)
    return envelope.ok(serialize.inquiry(inquiry))


@bp.post("/regulator-inquiries/<identifier>/submit-remediation")
def submit_remediation(identifier):
    auth.require([auth.REGULATORY_LIAISON])
    inquiry = resolve.inquiry(identifier)
    payload = shape.body()
    summary = shape.string(payload, "remediation_summary", min_len=None)

    if inquiry["status"] != "REMEDIATION_REQUIRED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REMEDIATION_REQUIRED docket may report remediation.")

    # rank 40 — every path the docket flagged must have left FLAGGED
    for profile_id in inquiry["flagged_profile_ids"]:
        profile = store.profiles.get(profile_id)
        if profile is not None and profile["status"] == "FLAGGED":
            raise ApiError("ERR_REMEDIATION_INCOMPLETE",
                           "A booking path this docket flagged is still FLAGGED.")

    inquiry["status"] = "REMEDIATION_SUBMITTED"
    inquiry["remediation_summary"] = summary
    _refresh_exposure(inquiry)
    store.touch(inquiry)

    prop = store.properties.get(inquiry["property_id"])
    derive.recompute_property(prop)
    return envelope.ok(serialize.inquiry(inquiry))


@bp.post("/regulator-inquiries/<identifier>/reject-remediation")
def reject_remediation(identifier):
    auth.require([auth.PLATFORM_ADMIN])
    inquiry = resolve.inquiry(identifier)
    payload = shape.body()
    reason = shape.string(payload, "rejection_reason", min_len=None)

    if inquiry["status"] != "REMEDIATION_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REMEDIATION_SUBMITTED docket may be rejected.")

    inquiry["status"] = "REMEDIATION_REQUIRED"
    inquiry["rejection_reason"] = reason
    inquiry["remediation_round"] = inquiry["remediation_round"] + 1

    # the list is never re-appended, so it accumulates no duplicates
    for profile_id in inquiry["flagged_profile_ids"]:
        profile = store.profiles.get(profile_id)
        if profile is not None and profile["status"] in ("DEPLOYED", "REMEDIATED"):
            profile["status"] = "FLAGGED"
            store.touch(profile)

    prop = store.properties.get(inquiry["property_id"])
    derive.recompute_property(prop, force=True)
    _refresh_exposure(inquiry)
    store.touch(inquiry)
    return envelope.ok(serialize.inquiry(inquiry))


@bp.post("/regulator-inquiries/<identifier>/accept")
def accept_inquiry(identifier):
    auth.require([auth.PLATFORM_ADMIN])
    inquiry = resolve.inquiry(identifier)

    if inquiry["status"] not in ("REMEDIATION_SUBMITTED", "RESPONSE_SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Acceptance is taken from REMEDIATION_SUBMITTED or RESPONSE_SUBMITTED.")

    inquiry["status"] = "ACCEPTED"
    # acceptance clears the list without un-flagging anything
    inquiry["flagged_profile_ids"] = []
    store.touch(inquiry)

    prop = store.properties.get(inquiry["property_id"])
    derive.recompute_property(prop, force=True)
    return envelope.ok(serialize.inquiry(inquiry))


@bp.post("/regulator-inquiries/<identifier>/withdraw")
def withdraw_inquiry(identifier):
    auth.require([auth.PLATFORM_ADMIN])
    inquiry = resolve.inquiry(identifier)
    payload = shape.body()
    reason = shape.string(payload, "withdrawal_reason", min_len=None)

    if inquiry["status"] not in WITHDRAWABLE_FROM:
        raise ApiError("ERR_INVALID_STATE", "The docket cannot be withdrawn from that state.")

    inquiry["status"] = "WITHDRAWN"
    inquiry["withdrawal_reason"] = reason

    # restore exactly the paths this docket flagged and nothing else
    for profile_id in inquiry["flagged_profile_ids"]:
        profile = store.profiles.get(profile_id)
        if profile is not None and profile["status"] == "FLAGGED":
            profile["status"] = "DEPLOYED"
            store.touch(profile)
    inquiry["flagged_profile_ids"] = []
    store.touch(inquiry)

    prop = store.properties.get(inquiry["property_id"])
    derive.recompute_property(prop, force=True)
    return envelope.ok(serialize.inquiry(inquiry))


# ------------------------------------------------------- revenue impact models

@bp.post("/revenue-impact-models")
def create_revenue_model():
    auth.require([auth.REVENUE_MANAGER, auth.COMPLIANCE_OFFICER])
    payload = shape.body()
    property_id = shape.identifier(payload, "property_id")
    program_id = shape.identifier(payload, "fee_program_id")
    scenario = shape.enum(payload, "scenario", SCENARIOS)
    variant = shape.enum(payload, "variant", VARIANTS)
    roll_in = shape.string_array(payload, "roll_in_fee_codes", allow_empty=True)

    prop = resolve.property_(property_id)
    program = resolve.fee_program(program_id)

    if program["property_id"] != prop["id"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The fee program does not belong to the modelled property.")

    # rank 14 — only a published inventory may be modelled
    if program["status"] != "PUBLISHED":
        raise ApiError("ERR_FEE_PROGRAM_NOT_PUBLISHED",
                       "The fee program is not PUBLISHED.")

    mandatory_codes = [f["code"] for f in store.mandatory_fees_of_program(program["id"])]

    # rank 33 — every rolled code must name a MANDATORY fee of that program
    for code in roll_in:
        if code not in mandatory_codes:
            raise ApiError("ERR_ROLL_IN_FEE_NOT_MANDATORY",
                           "%s is not a mandatory fee of the program." % code)

    # rank 34 — the set must agree with the declared scenario
    rolled = set(roll_in)
    every = set(mandatory_codes)
    if scenario == "STATUS_QUO":
        mismatch = bool(rolled)
    elif scenario == "FULL_ROLL_IN":
        mismatch = rolled != every
    else:
        mismatch = (not rolled) or rolled == every
    if mismatch:
        raise ApiError("ERR_ROLL_IN_SCENARIO_MISMATCH",
                       "roll_in_fee_codes does not agree with the declared scenario.")

    jurisdiction = store.jurisdictions.get(prop["jurisdiction_id"])
    row = {
        "property_id": prop["id"],
        "fee_program_id": program["id"],
        "scenario": scenario,
        "variant": variant,
        "roll_in_fee_codes": list(roll_in),
    }
    row.update(calc.revenue_figures(prop, jurisdiction, program, scenario, variant, rolled))
    store.stamp_new(row, versioned=False)
    store.revenue_models[row["id"]] = row
    return envelope.created(serialize.revenue_model(row))


@bp.get("/revenue-impact-models/<identifier>")
def read_revenue_model(identifier):
    auth.require(MODEL_READERS)
    return envelope.ok(serialize.revenue_model(resolve.revenue_model(identifier)))


@bp.get("/revenue-impact-models")
def list_revenue_models():
    auth.require(MODEL_READERS)
    rows = envelope.apply_filters(
        store.sort_default(store.revenue_models.values()),
        [("property_id", envelope.str_filter("property_id")),
         ("fee_program_id", envelope.str_filter("fee_program_id")),
         ("scenario", envelope.str_filter("scenario")),
         ("variant", envelope.str_filter("variant"))],
    )
    return envelope.page(rows, serialize.revenue_model)
