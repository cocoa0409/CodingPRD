"""Channel disclosure profiles: creation, scoring, deployment, audit, remediation
(PRD 3.3)."""

import datetime as dt

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

bp = Blueprint("profiles", __name__)

PLACEMENTS = ("FIRST_QUOTE", "RATE_DETAILS", "CHECKOUT", "CONFIRMATION_ONLY", "ABSENT")
PROFILE_STATUSES = ("DRAFT", "DEPLOYED", "FLAGGED", "REMEDIATED", "RETIRED")
CUTOVER_BUFFER = dt.timedelta(hours=24)
BUFFERED_STATUSES = ("DEPLOYED", "FLAGGED", "REMEDIATED", "RETIRED")


def _capability_check(channel, first_quote_shows_total, itemized_at_first_quote):
    """Rank 21 — a profile may never claim a behaviour its channel cannot perform."""
    if first_quote_shows_total and not channel["supports_total_price_display"]:
        raise ApiError("ERR_CHANNEL_CAPABILITY_MISMATCH",
                       "The channel cannot display a total price at first quote.")
    if itemized_at_first_quote and not channel["supports_itemization"]:
        raise ApiError("ERR_CHANNEL_CAPABILITY_MISMATCH",
                       "The channel cannot itemise at first quote.")


def _total_price_check(jurisdiction, first_quote_shows_total):
    """Rank 20 — the jurisdictional total-price-display mandate."""
    if jurisdiction is not None and jurisdiction["first_quote_total_required"] \
            and not first_quote_shows_total:
        raise ApiError("ERR_TOTAL_PRICE_DISPLAY_REQUIRED",
                       "The jurisdiction requires the all-in total at first quote.")


def _cutover_check(profile_id, property_id, channel_id, deployed_from, deployed_to):
    """Rank 28 — the 24-hour cutover buffer on each side of the closed window."""
    for other in store.profiles.values():
        if other["id"] == profile_id:
            continue
        if other["property_id"] != property_id or other["channel_id"] != channel_id:
            continue
        if other["status"] not in BUFFERED_STATUSES:
            continue
        if deployed_from < other["deployed_to"] + CUTOVER_BUFFER \
                and other["deployed_from"] < deployed_to + CUTOVER_BUFFER:
            raise ApiError("ERR_CUTOVER_BUFFER_VIOLATION",
                           "The deployment window collides with the cutover buffer of "
                           "another profile on the same property and channel.")


@bp.post("/channel-disclosure-profiles")
def create_profile():
    user_id, role = auth.require([auth.REVENUE_MANAGER, auth.CHANNEL_OPERATOR])

    # rank 4 — a ChannelOperator may only create a profile for its own channel
    if role == auth.CHANNEL_OPERATOR:
        auth.channel_owns(user_id, shape.peek_body().get("channel_id"))

    payload = shape.body()
    property_id = shape.identifier(payload, "property_id")
    channel_id = shape.identifier(payload, "channel_id")
    fee_program_id = shape.identifier(payload, "fee_program_id")
    first_quote_shows_total = shape.boolean(payload, "first_quote_shows_total")
    itemized_at_first_quote = shape.boolean(payload, "itemized_at_first_quote")
    disclosure_placement = shape.enum(payload, "disclosure_placement", PLACEMENTS)
    deployed_from = shape.timestamp(payload, "deployed_from")
    deployed_to = shape.timestamp(payload, "deployed_to")
    expected_fee_program_version = shape.integer(payload, "expected_fee_program_version")
    if deployed_to <= deployed_from:
        raise ApiError("ERR_INVALID_REQUEST", "deployed_to must be after deployed_from.")

    # rank 8 — body references in declared order
    prop = resolve.property_(property_id)
    channel = resolve.channel(channel_id)
    program = resolve.fee_program(fee_program_id)

    # rank 11 — optimistic concurrency on the fee program version
    if expected_fee_program_version != program["version"]:
        raise ApiError("ERR_STALE_FEE_PROGRAM_VERSION",
                       "expected_fee_program_version does not match the program version.")

    # rank 14 — the bound program must be PUBLISHED
    if program["status"] != "PUBLISHED":
        raise ApiError("ERR_FEE_PROGRAM_NOT_PUBLISHED",
                       "A disclosure profile may only bind a PUBLISHED fee program.")

    # rank 21 — channel capability
    _capability_check(channel, first_quote_shows_total, itemized_at_first_quote)

    # rank 28 — cutover buffer
    _cutover_check(None, prop["id"], channel["id"], deployed_from, deployed_to)

    row = {
        "property_id": prop["id"],
        "channel_id": channel["id"],
        "fee_program_id": program["id"],
        "first_quote_shows_total": first_quote_shows_total,
        "itemized_at_first_quote": itemized_at_first_quote,
        "disclosure_placement": disclosure_placement,
        "deployed_from": deployed_from,
        "deployed_to": deployed_to,
        "status": "DRAFT",
        "disclosure_score": 0,
        "confirmed_undisclosed_count": 0,
        "remediation_round": 0,
        "last_audited_at": None,
    }
    store.stamp_new(row)
    store.profiles[row["id"]] = row
    row["disclosure_score"] = calc.disclosure_score(row)

    store.touch(program)  # a successful create increments FeeProgram.version by 1
    return envelope.created(serialize.profile(row))


@bp.get("/channel-disclosure-profiles/<identifier>")
def read_profile(identifier):
    user_id, role = auth.require(auth.OPERATORS)
    if role == auth.CHANNEL_OPERATOR:
        auth.acting_channel(user_id)
        existing = resolve.peek("profile", identifier)
        if existing is not None:
            auth.channel_owns(user_id, existing["channel_id"])
    return envelope.ok(serialize.profile(resolve.profile(identifier)))


@bp.get("/channel-disclosure-profiles")
def list_profiles():
    auth.require(auth.OPERATORS)
    rows = envelope.apply_filters(
        store.sort_default(store.profiles.values()),
        [("property_id", envelope.str_filter("property_id")),
         ("channel_id", envelope.str_filter("channel_id")),
         ("fee_program_id", envelope.str_filter("fee_program_id")),
         ("status", envelope.str_filter("status")),
         ("disclosure_placement", envelope.str_filter("disclosure_placement"))],
    )
    return envelope.page(rows, serialize.profile)


@bp.post("/channel-disclosure-profiles/<identifier>/deploy")
def deploy_profile(identifier):
    user_id, role = auth.require([auth.COMPLIANCE_OFFICER, auth.CHANNEL_OPERATOR])
    if role == auth.CHANNEL_OPERATOR:
        auth.acting_channel(user_id)
        existing = resolve.peek("profile", identifier)
        if existing is not None:
            auth.channel_owns(user_id, existing["channel_id"])
    profile = resolve.profile(identifier)

    program = store.fee_programs.get(profile["fee_program_id"])
    prop = store.properties.get(profile["property_id"])
    jurisdiction = store.jurisdictions.get(prop["jurisdiction_id"]) if prop else None

    if profile["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT profile may be deployed.")
    if program is None or program["status"] != "PUBLISHED":
        raise ApiError("ERR_FEE_PROGRAM_NOT_PUBLISHED",
                       "The bound fee program is no longer PUBLISHED.")
    if prop is None or prop["status"] != "ACTIVE":
        raise ApiError("ERR_PROPERTY_NOT_ACTIVE", "The property is not ACTIVE.")

    _total_price_check(jurisdiction, profile["first_quote_shows_total"])
    _cutover_check(profile["id"], profile["property_id"], profile["channel_id"],
                   profile["deployed_from"], profile["deployed_to"])

    profile["status"] = "DEPLOYED"
    profile["disclosure_score"] = calc.disclosure_score(profile)
    profile["last_audited_at"] = clock.now()

    for other in store.sort_created(store.profiles_of_property(profile["property_id"])):
        if other["id"] == profile["id"] or other["channel_id"] != profile["channel_id"]:
            continue
        if other["status"] == "DEPLOYED":
            derive.retire_profile(other)

    store.touch(profile)
    derive.recompute_property(prop, force=True)
    return envelope.ok(serialize.profile(profile))


@bp.post("/channel-disclosure-profiles/<identifier>/audit")
def audit_profile(identifier):
    auth.require([auth.COMPLIANCE_OFFICER])
    profile = resolve.profile(identifier)
    prop = store.properties.get(profile["property_id"])

    if profile["status"] not in ("DRAFT", "DEPLOYED", "REMEDIATED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT, DEPLOYED or REMEDIATED profile may be audited.")

    was_deployed = profile["status"] == "DEPLOYED"
    score = calc.disclosure_score(profile)
    profile["disclosure_score"] = score
    profile["last_audited_at"] = clock.now()
    flagged = was_deployed and score < calc.FLAG_SCORE_FLOOR
    if flagged:
        profile["status"] = "FLAGGED"
    store.touch(profile)
    derive.recompute_property(prop, force=flagged)
    return envelope.ok(serialize.profile(profile))


@bp.post("/channel-disclosure-profiles/<identifier>/remediate")
def remediate_profile(identifier):
    user_id, role = auth.require([auth.CHANNEL_OPERATOR, auth.REVENUE_MANAGER])
    if role == auth.CHANNEL_OPERATOR:
        auth.acting_channel(user_id)
        existing = resolve.peek("profile", identifier)
        if existing is not None:
            auth.channel_owns(user_id, existing["channel_id"])
    profile = resolve.profile(identifier)

    payload = shape.body()
    first_quote_shows_total = shape.boolean(payload, "first_quote_shows_total")
    itemized_at_first_quote = shape.boolean(payload, "itemized_at_first_quote")
    disclosure_placement = shape.enum(payload, "disclosure_placement", PLACEMENTS)

    if profile["status"] != "FLAGGED":
        raise ApiError("ERR_INVALID_STATE", "Only a FLAGGED profile may be remediated.")

    prop = store.properties.get(profile["property_id"])
    jurisdiction = store.jurisdictions.get(prop["jurisdiction_id"]) if prop else None
    channel = store.channels.get(profile["channel_id"])

    # both guard rails are re-evaluated against the NEW values
    _total_price_check(jurisdiction, first_quote_shows_total)
    _capability_check(channel, first_quote_shows_total, itemized_at_first_quote)

    profile["first_quote_shows_total"] = first_quote_shows_total
    profile["itemized_at_first_quote"] = itemized_at_first_quote
    profile["disclosure_placement"] = disclosure_placement
    profile["status"] = "REMEDIATED"
    profile["confirmed_undisclosed_count"] = 0
    profile["remediation_round"] = profile["remediation_round"] + 1
    profile["disclosure_score"] = calc.disclosure_score(profile)
    profile["last_audited_at"] = clock.now()
    store.touch(profile)
    derive.recompute_property(prop, force=True)
    return envelope.ok(serialize.profile(profile))


@bp.post("/channel-disclosure-profiles/<identifier>/confirm-remediation")
def confirm_remediation(identifier):
    auth.require([auth.COMPLIANCE_OFFICER])
    profile = resolve.profile(identifier)
    prop = store.properties.get(profile["property_id"])

    if profile["status"] != "REMEDIATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REMEDIATED profile may have its repair confirmed.")

    score = calc.disclosure_score(profile)
    if score < calc.CONFIRMATION_SCORE_FLOOR:
        raise ApiError("ERR_REMEDIATION_SCORE_INSUFFICIENT",
                       "The recomputed disclosure score is below the confirmation floor.")

    profile["disclosure_score"] = score
    profile["status"] = "DEPLOYED"
    profile["last_audited_at"] = clock.now()
    store.touch(profile)
    derive.recompute_property(prop, force=True)
    return envelope.ok(serialize.profile(profile))
