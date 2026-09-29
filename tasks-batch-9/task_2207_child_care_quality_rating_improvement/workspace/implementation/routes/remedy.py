"""Appeals of an award and disputes of published data (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import calculations as calc
import cascades
import lookups
import response
import serializers
import store
import validation as v
from auth import require
from errors import fail
from validation import as_date, body

bp = Blueprint("remedy", __name__)

REVIEW_ACTIONS = ["START", "REQUEST_INFO", "SUSTAIN", "DENY"]
PROVIDER_ACTIONS = ["RESPOND", "WITHDRAW"]
TRIAGE_ACTIONS = ["OPEN_TRIAGE", "REQUEST_INFO", "ESCALATE", "APPLY_CORRECTION",
                  "REJECT", "WITHDRAW"]

APPEAL_FILING_WINDOW_DAYS = 30
APPEAL_OPEN_STATES = ("FILED", "UNDER_REVIEW", "INFO_REQUESTED")
DISPUTE_OPEN_STATES = ("FILED", "TRIAGE", "INFO_REQUESTED", "ESCALATED")
ESCALATABLE_FIELDS = ("PUBLISHED_TIER", "PUBLISHED_SCORE", "DOMAIN_POINTS")
APPEAL_BACKED_FIELDS = ("PUBLISHED_TIER", "PUBLISHED_SCORE")
TRIAGE_ROUND_LIMIT = 3


# ------------------------------------------------------------------- helpers


def _restore_cycle_after_appeal(cycle):
    """Deny and withdraw restore the status quo identically (PRD §3.6)."""
    cycle["status"] = "ACTIVE"
    cycle["publication_status"] = "PUBLISHED" if cycle.get("published_at") else "UNPUBLISHED"
    store.touch(cycle)
    provider = store.DB.providers.get(cycle["provider_id"])
    if provider is not None:
        cascades.refresh_public_listing(provider)
        store.touch(provider)


def _sustained_appeal_of(cycle_id):
    """The SUSTAINED appeal of this cycle decided on or before the logical clock date."""
    found = None
    for appeal in store.sort_created(cascades.appeals_of(cycle_id)):
        if appeal["status"] != "SUSTAINED":
            continue
        decided = as_date(appeal.get("decided_on"))
        if decided is None or decided > store.today():
            continue
        found = appeal
    return found


def _claimed_capacity(claimed_value):
    """A LICENSED_CAPACITY correction carries an integer even when quoted."""
    if isinstance(claimed_value, bool):
        return claimed_value
    if isinstance(claimed_value, int):
        return claimed_value
    try:
        return int(str(claimed_value).strip())
    except (TypeError, ValueError):
        fail("ERR_VALIDATION", "claimed_value must be an integer for LICENSED_CAPACITY")


# -------------------------------------------------------------------- appeals


@bp.post("/rating-cycles/<rating_cycle_id>/appeals")
def file_appeal(rating_cycle_id):
    principal = require("Provider")
    cycle = lookups.get_cycle(rating_cycle_id)
    lookups.own_cycle(principal, cycle)
    data = body()
    grounds = v.req_enum(data, "grounds", v.APPEAL_GROUNDS)
    narrative = v.req_str(data, "narrative")

    if cycle["status"] not in ("AWARDED", "ACTIVE"):
        fail("ERR_CYCLE_STATE_INVALID", "an appeal may be filed only from AWARDED or ACTIVE")

    award_date = as_date(cycle.get("awarded_on"))
    if award_date is None or \
            store.today() > award_date + timedelta(days=APPEAL_FILING_WINDOW_DAYS):
        fail("ERR_APPEAL_FILING_WINDOW_CLOSED",
             "the 30-day appeal filing window has closed")

    if cascades.has_open_appeal(cycle["id"]):
        fail("ERR_OPEN_APPEAL_BLOCKS_ACTION", "an appeal of this cycle is already open")

    rec = store.base_record(
        rating_cycle_id=cycle["id"],
        grounds=grounds,
        narrative=narrative,
        filed_on=store.now(),
        status="FILED",
        info_request_count=0,
        reviewer_user_id=None,
        adjusted_tier=None,
        decided_on=None,
    )
    store.DB.appeals[rec["id"]] = rec

    cycle["status"] = "UNDER_APPEAL"
    cycle["publication_status"] = "SUPPRESSED"
    store.touch(cycle)
    provider = store.DB.providers.get(cycle["provider_id"])
    if provider is not None:
        provider["public_listing_visible"] = False
        store.touch(provider)

    return response.created(serializers.dump("appeal", rec))


@bp.get("/appeals")
def list_appeals():
    require("StateAdministrator", "AppealReviewer", "Provider")
    records = store.sort_created(list(store.DB.appeals.values()))
    for field in ("rating_cycle_id", "status", "grounds"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("appeal"))


@bp.get("/appeals/<appeal_id>")
def read_appeal(appeal_id):
    principal = require("StateAdministrator", "AppealReviewer", "Provider")
    appeal = lookups.get_appeal(appeal_id)
    lookups.own_via_cycle(principal, appeal["rating_cycle_id"])
    return response.ok(serializers.dump("appeal", appeal))


@bp.post("/appeals/<appeal_id>/review-actions")
def review_action(appeal_id):
    principal = require("AppealReviewer")
    appeal = lookups.get_appeal(appeal_id)
    cycle = lookups.get_cycle(appeal["rating_cycle_id"])

    # Step 5 of the ladder: segregation of duties runs before the body is read.
    if cycle.get("awarded_by_user_id") and \
            principal.user_id == cycle["awarded_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the awarding administrator may not review the appeal of that award")
    if appeal.get("reviewer_user_id") and principal.user_id != appeal["reviewer_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "this appeal is already assigned to another reviewer")

    data = body()
    action = v.req_enum(data, "action", REVIEW_ACTIONS)
    adjusted_tier = v.opt_int(data, "adjusted_tier", 1, 5)
    v.opt_str(data, "note")

    if action == "START":
        if appeal["status"] != "FILED":
            fail("ERR_APPEAL_STATE_INVALID", "a review may be started only from FILED")
        appeal["status"] = "UNDER_REVIEW"
        appeal["reviewer_user_id"] = principal.user_id
        store.touch(appeal)

    elif action == "REQUEST_INFO":
        if appeal["status"] != "UNDER_REVIEW":
            fail("ERR_APPEAL_STATE_INVALID",
                 "information may be requested only from UNDER_REVIEW")
        if int(appeal["info_request_count"]) >= 2:
            fail("ERR_APPEAL_INFO_ROUND_LIMIT",
                 "this appeal has already used both information-request rounds")
        appeal["status"] = "INFO_REQUESTED"
        appeal["info_request_count"] = int(appeal["info_request_count"]) + 1
        store.touch(appeal)

    elif action == "SUSTAIN":
        if appeal["status"] != "UNDER_REVIEW":
            fail("ERR_APPEAL_STATE_INVALID", "an appeal may be sustained only from UNDER_REVIEW")
        if adjusted_tier is None:
            fail("ERR_VALIDATION", "adjusted_tier is required when sustaining an appeal")
        if cycle.get("awarded_tier") is not None and \
                adjusted_tier == int(cycle["awarded_tier"]):
            fail("ERR_VALIDATION",
                 "adjusted_tier must differ from the cycle's current awarded_tier")
        if appeal["grounds"] != "OBSERVER_RELIABILITY":
            ceiling = calc.BLOCK_TIER_CEILING[int(cycle.get("highest_block_cleared") or 0)]
            if adjusted_tier > ceiling:
                fail("ERR_BLOCK_GATE_NOT_MET",
                     "adjusted_tier exceeds the ceiling implied by highest_block_cleared")
        _sustain(appeal, cycle, adjusted_tier)

    else:
        if appeal["status"] != "UNDER_REVIEW":
            fail("ERR_APPEAL_STATE_INVALID", "an appeal may be denied only from UNDER_REVIEW")
        appeal["status"] = "DENIED"
        appeal["decided_on"] = store.now()
        store.touch(appeal)
        _restore_cycle_after_appeal(cycle)

    return response.ok(serializers.dump("appeal", appeal))


def _sustain(appeal, cycle, adjusted_tier):
    """SUSTAINED plus its three-hop cascade onto the cycle, claims and provider."""
    appeal["status"] = "SUSTAINED"
    appeal["adjusted_tier"] = adjusted_tier
    appeal["decided_on"] = store.now()
    store.touch(appeal)

    # Hop 1: the cycle returns to AWARDED carrying the ordered tier, and the
    # validity arithmetic reruns on the ORIGINAL effective_date.
    validity = calc.compute_validity(store.now(), adjusted_tier, cycle.get("effective_date"))
    cycle["awarded_tier"] = adjusted_tier
    cycle["appeal_adjusted"] = True
    cycle["effective_date"] = validity["effective_date"]
    cycle["validity_months"] = validity["validity_months"]
    cycle["expires_on"] = validity["expires_on"]
    cycle["rerating_window_opens_on"] = validity["rerating_window_opens_on"]
    cycle["status"] = "AWARDED"
    cycle["publication_status"] = "UNPUBLISHED"
    store.touch(cycle)

    # Hops 2 and 3: paid claims inside the validity window are flagged for
    # reconciliation and the provider's correction balance moves.
    provider = store.DB.providers.get(cycle["provider_id"])
    if provider is not None:
        cascades.flag_paid_claims_for_reconciliation(cycle, provider)


@bp.post("/appeals/<appeal_id>/provider-actions")
def provider_action(appeal_id):
    principal = require("Provider")
    appeal = lookups.get_appeal(appeal_id)
    lookups.own_via_cycle(principal, appeal["rating_cycle_id"])
    cycle = lookups.get_cycle(appeal["rating_cycle_id"])
    data = body()
    action = v.req_enum(data, "action", PROVIDER_ACTIONS)
    narrative = v.opt_str(data, "narrative")

    if action == "RESPOND":
        if appeal["status"] != "INFO_REQUESTED":
            fail("ERR_APPEAL_STATE_INVALID",
                 "a response is accepted only from INFO_REQUESTED")
        appeal["status"] = "UNDER_REVIEW"
        if narrative:
            existing = appeal.get("narrative") or ""
            appeal["narrative"] = (existing + "\n" + narrative) if existing else narrative
        store.touch(appeal)
    else:
        if appeal["status"] not in APPEAL_OPEN_STATES:
            fail("ERR_APPEAL_STATE_INVALID",
                 "an appeal in %s may not be withdrawn" % appeal["status"])
        appeal["status"] = "WITHDRAWN"
        appeal["decided_on"] = store.now()
        store.touch(appeal)
        _restore_cycle_after_appeal(cycle)

    return response.ok(serializers.dump("appeal", appeal))


# ------------------------------------------------------------------- disputes


def _req_claimed_value(data):
    if "claimed_value" not in data or data["claimed_value"] is None:
        fail("ERR_VALIDATION", "claimed_value is required")
    value = data["claimed_value"]
    if isinstance(value, bool) or isinstance(value, (dict, list)):
        fail("ERR_VALIDATION", "claimed_value must be a string or a number")
    if isinstance(value, str) and value.strip() == "":
        fail("ERR_VALIDATION", "claimed_value must be a non-empty string")
    return value


@bp.post("/rating-cycles/<rating_cycle_id>/data-disputes")
def file_dispute(rating_cycle_id):
    principal = require("Provider")
    cycle = lookups.get_cycle(rating_cycle_id)
    lookups.own_cycle(principal, cycle)
    data = body()
    disputed_field = v.req_enum(data, "disputed_field", v.DISPUTED_FIELDS)
    claimed_value = _req_claimed_value(data)

    rec = store.base_record(
        rating_cycle_id=cycle["id"],
        disputed_field=disputed_field,
        claimed_value=claimed_value,
        linked_appeal_id=None,
        status="FILED",
        triage_round=0,
        filed_on=store.now(),
        resolved_on=None,
    )
    store.DB.data_disputes[rec["id"]] = rec
    # Filing a dispute does not suspend publication (PRD §3.6).
    return response.created(serializers.dump("data_dispute", rec))


@bp.get("/data-disputes")
def list_disputes():
    require("StateAdministrator", "Provider")
    records = store.sort_created(list(store.DB.data_disputes.values()))
    for field in ("rating_cycle_id", "linked_appeal_id", "status", "disputed_field"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("data_dispute"))


@bp.get("/data-disputes/<data_dispute_id>")
def read_dispute(data_dispute_id):
    principal = require("StateAdministrator", "Provider")
    dispute = lookups.get_dispute(data_dispute_id)
    lookups.own_via_cycle(principal, dispute["rating_cycle_id"])
    return response.ok(serializers.dump("data_dispute", dispute))


@bp.post("/data-disputes/<data_dispute_id>/triage-actions")
def triage_action(data_dispute_id):
    principal = require("StateAdministrator", "Provider")
    dispute = lookups.get_dispute(data_dispute_id)
    lookups.own_via_cycle(principal, dispute["rating_cycle_id"])
    cycle = lookups.get_cycle(dispute["rating_cycle_id"])
    data = body()
    action = v.req_enum(data, "action", TRIAGE_ACTIONS)
    v.opt_str(data, "resolution_note")

    # Every triage action belongs to the state except withdrawal, which is the
    # provider's (PRD §3.6).
    if action == "WITHDRAW":
        if not principal.is_provider:
            fail("ERR_FORBIDDEN_ROLE", "only the provider may withdraw its own dispute")
    elif not principal.is_admin:
        fail("ERR_FORBIDDEN_ROLE", "only a StateAdministrator may take this triage action")

    if action == "OPEN_TRIAGE":
        if dispute["status"] == "FILED":
            if cycle.get("publication_status") != "PUBLISHED":
                fail("ERR_CYCLE_STATE_INVALID",
                     "triage may open only against a PUBLISHED cycle")
        elif dispute["status"] in ("INFO_REQUESTED", "ESCALATED"):
            if int(dispute["triage_round"]) >= TRIAGE_ROUND_LIMIT:
                fail("ERR_DISPUTE_TRIAGE_LIMIT",
                     "this dispute has already used all three triage rounds")
        else:
            fail("ERR_DISPUTE_STATE_INVALID",
                 "triage may not be opened from %s" % dispute["status"])
        dispute["status"] = "TRIAGE"
        dispute["triage_round"] = int(dispute["triage_round"]) + 1
        store.touch(dispute)

    elif action == "REQUEST_INFO":
        if dispute["status"] != "TRIAGE":
            fail("ERR_DISPUTE_STATE_INVALID",
                 "information may be requested only from TRIAGE")
        dispute["status"] = "INFO_REQUESTED"
        store.touch(dispute)

    elif action == "ESCALATE":
        if dispute["status"] != "TRIAGE":
            fail("ERR_DISPUTE_STATE_INVALID", "a dispute may be escalated only from TRIAGE")
        if dispute["disputed_field"] not in ESCALATABLE_FIELDS:
            fail("ERR_VALIDATION",
                 "a %s dispute is never escalated" % dispute["disputed_field"])
        dispute["status"] = "ESCALATED"
        store.touch(dispute)

    elif action == "APPLY_CORRECTION":
        if dispute["status"] not in ("TRIAGE", "ESCALATED"):
            fail("ERR_DISPUTE_STATE_INVALID",
                 "a correction may be applied only from TRIAGE or ESCALATED")
        _apply_correction(dispute, cycle)

    elif action == "REJECT":
        if dispute["status"] not in ("TRIAGE", "ESCALATED"):
            fail("ERR_DISPUTE_STATE_INVALID",
                 "a dispute may be rejected only from TRIAGE or ESCALATED")
        dispute["status"] = "REJECTED"
        dispute["resolved_on"] = store.now()
        store.touch(dispute)

    else:
        if dispute["status"] not in DISPUTE_OPEN_STATES:
            fail("ERR_DISPUTE_STATE_INVALID",
                 "a dispute in %s may not be withdrawn" % dispute["status"])
        dispute["status"] = "WITHDRAWN"
        dispute["resolved_on"] = store.now()
        store.touch(dispute)

    return response.ok(serializers.dump("data_dispute", dispute))


def _apply_correction(dispute, cycle):
    field = dispute["disputed_field"]
    if field in APPEAL_BACKED_FIELDS:
        appeal = _sustained_appeal_of(cycle["id"])
        if appeal is None:
            fail("ERR_DISPUTE_REQUIRES_SUSTAINED_APPEAL",
                 "a %s correction requires a sustained appeal of the same cycle" % field)
        dispute["linked_appeal_id"] = appeal["id"]
    elif field in ("LICENSED_CAPACITY", "COUNTY_CODE"):
        provider = store.DB.providers.get(cycle["provider_id"])
        if provider is not None:
            if field == "LICENSED_CAPACITY":
                provider["licensed_capacity"] = _claimed_capacity(dispute["claimed_value"])
            else:
                provider["county_code"] = dispute["claimed_value"]
            store.touch(provider)
            snapshot = cycle.get("published_snapshot")
            if isinstance(snapshot, dict):
                snapshot["licensed_capacity"] = provider["licensed_capacity"]
                snapshot["county_code"] = provider["county_code"]
                store.touch(cycle)

    dispute["status"] = "CORRECTION_APPLIED"
    dispute["resolved_on"] = store.now()
    store.touch(dispute)
