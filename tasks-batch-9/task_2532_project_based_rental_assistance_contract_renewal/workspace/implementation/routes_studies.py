"""Rent comparability studies, comparables and the bounded challenge cycle
(PRD 3.4)."""
from flask import Blueprint, g

from core import (
    ROLE_CA, ROLE_HFO, ROLE_OWNER, ROLE_PHA, clock_date_str, create, fail,
    filter_arg, json_body, need_enum, need_id_list, need_int, need_str, opt_str,
    respond_object, rows, table, touch,
)
import calcs
from guards import (
    body_fk, deny_transition, endpoint, eq_filter, list_response, own_case,
    own_study, require_state, resolve,
)

bp = Blueprint("studies", __name__)

ALL_ROLES = (ROLE_OWNER, ROLE_CA, ROLE_HFO, ROLE_PHA)


# --------------------------------------------------------------------------
# Studies
# --------------------------------------------------------------------------
@bp.post("/rent-comparability-studies")
@endpoint(ROLE_OWNER)
def create_study():
    body = json_body()
    case = body_fk(body, "renewal_case_id", "cases")
    if case is not None:
        own_case(case)
    predecessor = body_fk(body, "supersedes_study_id", "studies")
    need_str(body, "renewal_case_id")
    appraiser_name = need_str(body, "appraiser_name")
    opt_str(body, "supersedes_study_id")
    track = case["rent_track_status"]
    advances = False
    if track == "OPTION_SELECTED" and case["adjustment_method"] is not None:
        advances = True
    elif track != "RCS_IN_PROGRESS":
        deny_transition("A study cannot be filed while the rent track is %s." % track)
    if predecessor is not None:
        if predecessor["state"] != "REJECTED" \
                or predecessor["renewal_case_id"] != case["id"]:
            deny_transition("supersedes_study_id must name a REJECTED study of the same case.")
    study = create("studies", {
        "renewal_case_id": case["id"],
        "supersedes_study_id": predecessor["id"] if predecessor else None,
        "state": "DRAFT",
        "appraiser_name": appraiser_name,
        "challenge_round": 0,
        "estimated_market_rent_cents": 0,
        "accepted_comparable_count": 0,
        "last_challenge_reason": None,
        "submitted_on_date": None,
    })
    if predecessor is not None:
        predecessor["state"] = "SUPERSEDED"
        touch(predecessor)
    if advances:
        case["rent_track_status"] = "RCS_IN_PROGRESS"
        touch(case)
    return respond_object(study, 201)


@bp.get("/rent-comparability-studies/<study_id>")
@endpoint(*ALL_ROLES)
def read_study(study_id):
    return respond_object(resolve("studies", study_id), 200)


@bp.get("/rent-comparability-studies")
@endpoint(*ALL_ROLES)
def list_studies():
    items = rows("studies")
    items = eq_filter(items, "renewal_case_id")
    items = eq_filter(items, "supersedes_study_id")
    items = eq_filter(items, "state")
    return list_response(items)


@bp.get("/rent-comparability-studies/<study_id>/comparables")
@endpoint(*ALL_ROLES)
def list_study_comparables(study_id):
    study = resolve("studies", study_id)
    return list_response(eq_filter(calcs.comparables_of(study["id"]), "status"))


# --------------------------------------------------------------------------
# Comparables
# --------------------------------------------------------------------------
@bp.post("/comparables")
@endpoint(ROLE_OWNER)
def create_comparable():
    body = json_body()
    study = body_fk(body, "study_id", "studies")
    if study is not None:
        own_study(study)
    need_str(body, "study_id")
    address_label = need_str(body, "address_label")
    raw_rent = need_int(body, "raw_rent_cents", minimum=1)
    adjustment_total = need_int(body, "adjustment_total_cents")
    utility_adjustment = need_int(body, "utility_adjustment_cents")
    weight = need_int(body, "weight", minimum=1, maximum=5)
    require_state(study, "state", "DRAFT")
    comparable = create("comparables", {
        "study_id": study["id"],
        "address_label": address_label,
        "raw_rent_cents": raw_rent,
        "adjustment_total_cents": adjustment_total,
        "utility_adjustment_cents": utility_adjustment,
        "weight": weight,
        "adjusted_rent_cents": calcs.comparable_adjusted_rent(
            raw_rent, adjustment_total, utility_adjustment),
        "status": "ACCEPTED",
    })
    calcs.recompute_study_estimate(study)
    touch(study)
    return respond_object(comparable, 201)


# --------------------------------------------------------------------------
# Submit, challenge, decide
# --------------------------------------------------------------------------
@bp.post("/rent-comparability-studies/<study_id>/submit")
@endpoint(ROLE_OWNER)
def submit_study(study_id):
    study = own_study(resolve("studies", study_id))
    require_state(study, "state", "DRAFT", "CHALLENGED")
    accepted = [c for c in calcs.comparables_of(study["id"]) if c["status"] == "ACCEPTED"]
    if len(accepted) < 1:
        fail("ERR_NO_ELIGIBLE_COMPARABLES",
             "A study needs at least one ACCEPTED comparable to be submitted.")
    calcs.recompute_study_estimate(study)
    study["state"] = "SUBMITTED"
    study["submitted_on_date"] = clock_date_str()
    touch(study)
    case = table("cases").get(study["renewal_case_id"])
    if case is not None:
        case["comparable_market_rent_cents"] = study["estimated_market_rent_cents"]
        touch(case)
    return respond_object(study, 200)


@bp.post("/rent-comparability-studies/<study_id>/challenge")
@endpoint(ROLE_CA)
def challenge_study(study_id):
    study = resolve("studies", study_id)
    body = json_body()
    raw_ids = body.get("struck_comparable_ids")
    named = []
    if isinstance(raw_ids, list) and all(isinstance(v, str) and v.strip() for v in raw_ids):
        for comparable_id in raw_ids:
            comparable = resolve("comparables", comparable_id)
            if comparable["study_id"] != study["id"]:
                fail("ERR_COMPARABLE_NOT_FOUND",
                     "The comparable does not belong to this study.")
            named.append(comparable)
    reason = need_str(body, "reason")
    need_id_list(body, "struck_comparable_ids")
    require_state(study, "state", "SUBMITTED")
    if study["challenge_round"] >= calcs.MAX_CHALLENGE_ROUNDS:
        fail("ERR_MAX_CHALLENGE_ROUNDS",
             "This study has exhausted its challenge budget.")
    for comparable in named:
        if comparable["status"] != "ACCEPTED":
            fail("ERR_COMPARABLE_NOT_FOUND",
                 "Only an ACCEPTED comparable of this study may be struck.")
    study["state"] = "CHALLENGED"
    study["challenge_round"] = study["challenge_round"] + 1
    study["last_challenge_reason"] = reason
    for comparable in named:
        comparable["status"] = "STRUCK"
        touch(comparable)
    calcs.recompute_study_estimate(study)
    touch(study)
    case = table("cases").get(study["renewal_case_id"])
    if case is not None:
        case["comparable_market_rent_cents"] = study["estimated_market_rent_cents"]
        case["challenge_reviewer_user_id"] = g.user_id
        touch(case)
    return respond_object(study, 200)


@bp.post("/rent-comparability-studies/<study_id>/decide")
@endpoint(ROLE_CA)
def decide_study(study_id):
    study = resolve("studies", study_id)
    body = json_body()
    decision = need_enum(body, "decision", ("ACCEPT", "REJECT"))
    reason = opt_str(body, "reason")
    require_state(study, "state", "SUBMITTED")
    if decision == "ACCEPT":
        study["state"] = "ACCEPTED"
        touch(study)
        return respond_object(study, 200)
    study["state"] = "REJECTED"
    if reason is not None:
        study["last_challenge_reason"] = reason
    touch(study)
    case = table("cases").get(study["renewal_case_id"])
    contract = calcs.contract_of_case(case) if case else None
    prop = calcs.property_of(contract) if contract else None
    owner = table("owners").get(prop["owner_id"]) if prop else None
    if owner is not None:
        owner["compliance_flag"] = "REVIEW_REQUIRED"
        touch(owner)
    return respond_object(study, 200)
