"""Quoting, binding, renewing and ending a term (PRD 3.3 / 3.4)."""

from flask import Blueprint

import calc
import envelope
import guards
import store
from errors import ApiError

bp = Blueprint("policies", __name__)

MORATORIUM_EVENT_STATUSES = ("DECLARED", "LOSS_AGGREGATION",
                             "CAPACITY_EXHAUSTED", "ASSESSMENT_LEVIED")
GRANT_CASCADE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO", "APPROVED")


def _live_policy_on_dwelling(dwelling_id, statuses, exclude_id=None):
    for policy in store.DB["policies"].values():
        if exclude_id is not None and policy["id"] == exclude_id:
            continue
        if policy["dwelling_id"] == dwelling_id and policy["lifecycle_status"] in statuses:
            return policy
    return None


def _offer_authorises(offer, insurer_id, dwelling_id):
    """Rung 45: ACCEPTED, and its insurer and dwelling match the policy's."""
    return (offer is not None
            and offer["status"] == "ACCEPTED"
            and offer["insurer_id"] == insurer_id
            and offer["dwelling_id"] == dwelling_id)


def _moratorium_in_force(policy):
    """Rung 68: half-open [occurred_at, occurred_at + 60 days) in the
    policyholder's county, for any event that has been declared or beyond."""
    policyholder = store.DB["policyholders"].get(policy["policyholder_id"])
    if policyholder is None:
        return False
    county = policyholder["county_code"]
    now = store.clock_now()
    for event in store.DB["events"].values():
        if event["status"] not in MORATORIUM_EVENT_STATUSES:
            continue
        if event["epicenter_county_code"] != county:
            continue
        occurred = store.dt_of(event, "occurred_at")
        if occurred is None:
            continue
        if occurred <= now < store.plus_days(occurred, calc.MORATORIUM_DAYS):
            return True
    return False


def _cascade_grants_on_policy(policy):
    """Cancellation and lapse both withdraw the policy's pre-reservation grants;
    FUNDS_RESERVED and VERIFIED_COMPLETE grants are left exactly as they are."""
    for grant in store.all_rows("grants"):
        if grant["policy_id"] != policy["id"]:
            continue
        if grant["status"] not in GRANT_CASCADE_STATUSES:
            continue
        grant["status"] = "WITHDRAWN"
        store.touch(grant)


@bp.post("/policies")
def quote_policy():
    role = guards.auth(("ParticipatingInsurer", "ProgramAdmin"))
    body = guards.body()
    fks = guards.body_fks(body, ("insurer_id", "dwelling_id", "accepted_offer_id"))
    insurer = fks.get("insurer_id")
    if role == "ParticipatingInsurer" and insurer is not None:
        guards.owner_must_be(insurer["id"])
    guards.required(body, ("dwelling_id", "insurer_id", "accepted_offer_id",
                           "deductible_pct", "contents_sublimit_cents",
                           "loss_of_use_sublimit_cents"))
    deductible_pct = guards.enum(body, "deductible_pct", "deductible_pct")
    contents = guards.integer(body, "contents_sublimit_cents", exclusive_min=0)
    loss_of_use = guards.integer(body, "loss_of_use_sublimit_cents", exclusive_min=0)
    dwelling = fks["dwelling_id"]
    offer = fks["accepted_offer_id"]
    if insurer["compliance_status"] == "SANCTIONED":
        raise ApiError("ERR_INSURER_SANCTIONED")
    if insurer["status"] != "ACTIVE":
        raise ApiError("ERR_INSURER_WITHDRAWN")
    if not _offer_authorises(offer, insurer["id"], dwelling["id"]):
        raise ApiError("ERR_MANDATORY_OFFER_NOT_ACCEPTED")
    if _live_policy_on_dwelling(dwelling["id"], ("ACTIVE", "QUOTED")) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_POLICY")
    if (contents > dwelling["dwelling_limit_cents"]
            or loss_of_use > dwelling["dwelling_limit_cents"]):
        raise ApiError("ERR_SUBLIMIT_EXCEEDS_LIMIT")
    base_premium = calc.hazard_base_premium(dwelling, deductible_pct, "QUOTE_TIME")
    created = store.clock_now()
    row = store.insert("policies", {
        "dwelling_id": dwelling["id"],
        "insurer_id": insurer["id"],
        "policyholder_id": dwelling["policyholder_id"],
        "accepted_offer_id": offer["id"],
        "deductible_pct": deductible_pct,
        "contents_sublimit_cents": contents,
        "loss_of_use_sublimit_cents": loss_of_use,
        "rated_dwelling_limit_cents": dwelling["dwelling_limit_cents"],
        "base_premium_cents": base_premium,
        "rating_variant": "QUOTE_TIME",
        "mitigation_discount_cents": 0,
        "annual_premium_cents": base_premium,
        "prorated_credit_cents": 0,
        "lifecycle_status": "QUOTED",
        "mitigation_status": "UNMITIGATED",
        "quote_expires_at": store.iso(store.plus_days(created, calc.QUOTE_VALID_DAYS)),
        "effective_at": None,
        "expires_at": None,
        "term_number": 1,
    })
    return envelope.created(store.public(row))


@bp.post("/policies/<row_id>/bind")
def bind_policy(row_id):
    guards.auth(("ParticipatingInsurer",))
    policy = guards.path_row("policies", row_id)
    guards.owner_must_be(policy["insurer_id"])
    insurer = store.DB["insurers"].get(policy["insurer_id"])
    dwelling = store.DB["dwellings"].get(policy["dwelling_id"])
    offer = store.DB["offers"].get(policy["accepted_offer_id"])
    if policy["lifecycle_status"] != "QUOTED":
        raise ApiError("ERR_POLICY_NOT_QUOTED")
    if insurer["compliance_status"] == "SANCTIONED":
        raise ApiError("ERR_INSURER_SANCTIONED")
    if insurer["status"] != "ACTIVE":
        raise ApiError("ERR_INSURER_WITHDRAWN")
    if not _offer_authorises(offer, policy["insurer_id"], policy["dwelling_id"]):
        raise ApiError("ERR_MANDATORY_OFFER_NOT_ACCEPTED")
    if _live_policy_on_dwelling(policy["dwelling_id"], ("ACTIVE",),
                                exclude_id=policy["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_POLICY")
    now = store.clock_now()
    if now > store.dt_of(policy, "quote_expires_at"):
        raise ApiError("ERR_QUOTE_EXPIRED")
    if _moratorium_in_force(policy):
        raise ApiError("ERR_BINDING_MORATORIUM")
    policy["lifecycle_status"] = "ACTIVE"
    policy["effective_at"] = store.iso(now)
    policy["expires_at"] = store.iso(store.plus_days(now, calc.TERM_DAYS))
    # Re-snapshot the term's claim-side limit; binding does not re-rate.
    policy["rated_dwelling_limit_cents"] = dwelling["dwelling_limit_cents"]
    store.touch(policy)
    insurer["policies_bound_count"] += 1
    store.touch(insurer)
    return envelope.object_response(store.public(policy))


@bp.post("/policies/<row_id>/renew")
def renew_policy(row_id):
    role = guards.auth(("ParticipatingInsurer", "ProgramAdmin"))
    policy = guards.path_row("policies", row_id)
    if role == "ParticipatingInsurer":
        guards.owner_must_be(policy["insurer_id"])
    insurer = store.DB["insurers"].get(policy["insurer_id"])
    dwelling = store.DB["dwellings"].get(policy["dwelling_id"])
    offer = store.DB["offers"].get(policy["accepted_offer_id"])
    if policy["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if insurer["compliance_status"] == "SANCTIONED":
        raise ApiError("ERR_INSURER_SANCTIONED")
    if not _offer_authorises(offer, policy["insurer_id"], policy["dwelling_id"]):
        raise ApiError("ERR_MANDATORY_OFFER_NOT_ACCEPTED")
    # Rung 67: [expires_at - 45 days, expires_at).
    expiry = store.dt_of(policy, "expires_at")
    now = store.clock_now()
    if expiry is None:
        raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN")
    opens = store.plus_days(expiry, -calc.RENEWAL_WINDOW_DAYS)
    if not (opens <= now < expiry):
        raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN")
    policy["term_number"] += 1
    policy["effective_at"] = policy["expires_at"]
    policy["expires_at"] = store.iso(store.plus_days(expiry, calc.TERM_DAYS))
    policy["rated_dwelling_limit_cents"] = dwelling["dwelling_limit_cents"]
    base_premium = calc.hazard_base_premium(dwelling, policy["deductible_pct"],
                                            "RENEWAL_TIME")
    policy["base_premium_cents"] = base_premium
    policy["rating_variant"] = "RENEWAL_TIME"
    policy["mitigation_discount_cents"] = 0
    policy["prorated_credit_cents"] = 0
    policy["annual_premium_cents"] = base_premium
    if policy["mitigation_status"] == "DISCOUNT_APPLIED":
        policy["mitigation_status"] = "RETROFIT_VERIFIED"
    store.touch(policy)
    return envelope.object_response(store.public(policy))


@bp.post("/policies/<row_id>/cancel")
def cancel_policy(row_id):
    role = guards.auth(("ParticipatingInsurer", "ProgramAdmin", "Policyholder"))
    policy = guards.path_row("policies", row_id)
    if role == "Policyholder":
        guards.owner_must_be(policy["policyholder_id"])
    elif role == "ParticipatingInsurer":
        guards.owner_must_be(policy["insurer_id"])
    body = guards.body()
    guards.optional_string(body, "reason")
    if policy["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    policy["lifecycle_status"] = "CANCELLED"
    store.touch(policy)
    _cascade_grants_on_policy(policy)
    return envelope.object_response(store.public(policy))


@bp.post("/policies/<row_id>/lifecycle-action")
def lifecycle_action(row_id):
    guards.auth(("ProgramAdmin",))
    policy = guards.path_row("policies", row_id)
    body = guards.body()
    guards.required(body, ("action",))
    action = guards.enum(body, "action", "lifecycle_action")
    if action == "LAPSE":
        if policy["lifecycle_status"] != "ACTIVE":
            raise ApiError("ERR_POLICY_NOT_ACTIVE")
        policy["lifecycle_status"] = "LAPSED"
        store.touch(policy)
        _cascade_grants_on_policy(policy)
    else:
        if policy["lifecycle_status"] != "QUOTED":
            raise ApiError("ERR_POLICY_NOT_QUOTED")
        # Rung 64: strictly after quote_expires_at.
        if not store.clock_now() > store.dt_of(policy, "quote_expires_at"):
            raise ApiError("ERR_QUOTE_STILL_VALID")
        policy["lifecycle_status"] = "QUOTE_EXPIRED"
        store.touch(policy)
    return envelope.object_response(store.public(policy))


@bp.post("/policies/<row_id>/revoke-mitigation-discount")
def revoke_discount(row_id):
    guards.auth(("ProgramAdmin",))
    policy = guards.path_row("policies", row_id)
    body = guards.body()
    guards.optional_string(body, "reason")
    if policy["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if (policy["mitigation_status"] != "DISCOUNT_APPLIED"
            or policy["mitigation_discount_cents"] <= 0):
        raise ApiError("ERR_NO_MITIGATION_DISCOUNT")
    # An exact restoration: the premium ledger conserves.
    policy["mitigation_discount_cents"] = 0
    policy["prorated_credit_cents"] = 0
    policy["annual_premium_cents"] = policy["base_premium_cents"]
    policy["mitigation_status"] = "UNMITIGATED"
    store.touch(policy)
    return envelope.object_response(store.public(policy))


@bp.get("/policies/<row_id>")
def read_policy(row_id):
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer", "Policyholder",
                        "ClaimAdjuster", "GrantReviewer"))
    policy = guards.path_row("policies", row_id)
    if role == "Policyholder":
        guards.owner_must_be(policy["policyholder_id"])
    elif role == "ParticipatingInsurer":
        guards.owner_must_be(policy["insurer_id"])
    return envelope.object_response(store.public(policy))


@bp.get("/policies")
def list_policies():
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer", "Policyholder",
                        "ClaimAdjuster"))
    rows = store.all_rows("policies")
    acting = guards.acting_id()
    if role == "Policyholder":
        rows = [row for row in rows if row["policyholder_id"] == acting]
    elif role == "ParticipatingInsurer":
        rows = [row for row in rows if row["insurer_id"] == acting]
    rows = guards.filtered(rows, (("dwelling_id", "dwelling_id"),
                                  ("insurer_id", "insurer_id"),
                                  ("policyholder_id", "policyholder_id"),
                                  ("accepted_offer_id", "accepted_offer_id"),
                                  ("lifecycle_status", "lifecycle_status"),
                                  ("mitigation_status", "mitigation_status")))
    return envelope.list_response(rows)
