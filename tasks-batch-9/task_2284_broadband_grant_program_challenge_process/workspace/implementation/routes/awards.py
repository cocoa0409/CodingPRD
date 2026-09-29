"""Award endpoints: the pinned nine-step obligation waterfall (PRD section 3.7)."""

from flask import Blueprint, request

from db import db, new_record, serialize
from errors import ApiError
from middleware import authenticate, get_str, json_body, pagination
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import calculations as calc
from services import cascades, domain

bp = Blueprint("awards", __name__)

READ_ROLES = ("ProgramAdmin", "ScoringOfficer", "EnvironmentalReviewer", "AuditOfficer",
              "Subgrantee")
LIST_ROLES = ("ProgramAdmin", "EnvironmentalReviewer", "AuditOfficer", "Subgrantee")
LEDGER_READ_ROLES = ("ProgramAdmin", "AuditOfficer", "Subgrantee")
TERMINABLE_STATES = ("OBLIGATED", "CONSTRUCTION_AUTHORIZED", "IN_CONSTRUCTION")


@bp.post("/broadband/awards")
def create_award():
    authenticate("ProgramAdmin")
    body = json_body()
    application_id = get_str(body, "application_id")                    # priority 14

    application = domain.require_application(application_id)            # priority 24
    program = domain.program_of_application(application)
    subgrantee = db.subgrantees.get(application["subgrantee_id"])

    if program["program_state"] == "ALLOCATION_CLOSED":                  # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if application["application_state"] != "SELECTED":                  # priority 44
        raise ApiError("ERR_APPLICATION_NOT_SELECTED")
    if program["scoring_posture"] != "OPEN":                             # priority 49
        raise ApiError("ERR_SCORING_POSTURE_RESTRICTED")
    if subgrantee is None or subgrantee["capability_state"] != "QUALIFIED":  # priority 82
        raise ApiError("ERR_SUBGRANTEE_NOT_QUALIFIED")

    claims = domain.claims_of_application(application["id"])
    base = [c for c in claims if c["claim_state"] == "CLAIMED_ELIGIBLE"]  # step 1

    for existing in domain.awards_of_application(application["id"]):     # priority 85
        if existing["award_state"] != "TERMINATED":
            raise ApiError("ERR_AWARD_ALREADY_EXISTS")
    for claim in base:
        location = db.locations.get(claim["location_id"])
        if location is not None and location.get("awarded_award_id"):
            raise ApiError("ERR_AWARD_ALREADY_EXISTS")

    if not base:
        raise ApiError("ERR_NO_ELIGIBLE_LOCATIONS")

    base_count = len(base)
    base_cost = sum(int(c["claimed_cost_cents"]) for c in base)
    # step 2: the preliminary per-location cost is recorded for audit only.
    calc.cents(calc.D(base_cost) / calc.D(base_count))

    # step 3: the extremely-high-cost flag, strictly greater than the threshold.
    threshold = int(program["ehcl_threshold_cents"])
    flags = dict((c["id"], int(c["claimed_cost_cents"]) > threshold) for c in base)

    # step 4: deferral only when the waiver is enabled and something is flagged.
    flagged = [c for c in base if flags[c["id"]]]
    if program.get("ehcl_waiver_enabled") and flagged:
        deferred = flagged
        retained = [c for c in base if not flags[c["id"]]]
    else:
        deferred = []
        retained = list(base)

    if not retained:                                                     # priority 90
        raise ApiError("ERR_ALL_LOCATIONS_EHCL_DEFERRED")

    # step 6
    total_eligible = sum(int(c["claimed_cost_cents"]) for c in retained)
    final_per_location = calc.cents(calc.D(total_eligible) / calc.D(len(retained)))

    # step 7: round each share, then sum exactly.  Summing first is wrong.
    shares = []
    match_requirement = 0
    for claim in retained:
        share = calc.match_share(claim["claimed_cost_cents"], program["min_match_pct"])
        shares.append((claim, share))
        match_requirement += share

    # step 8
    obligation = total_eligible - match_requirement
    holdback_cap = calc.cents(calc.D(obligation)
                              * (calc.D(100) - calc.D(program["holdback_pct"]))
                              / calc.D(100))

    if obligation > int(program["uncommitted_balance_cents"]):            # priority 91
        raise ApiError("ERR_PROGRAM_FUNDS_EXHAUSTED")

    award = new_record({
        "application_id": application["id"],
        "award_state": "OBLIGATED",
        "compliance_state": "COMPLIANT",
        "confirmed_location_count": len(retained),
        "total_eligible_cost_cents": total_eligible,
        "match_requirement_cents": match_requirement,
        "obligation_amount_cents": obligation,
        "holdback_cap_cents": holdback_cap,
        "final_per_location_cost_cents": final_per_location,
        "ehcl_deferred_count": len(deferred),
        "disbursed_to_date_cents": 0,
        "certified_location_count": 0,
        "failed_location_count": 0,
        "last_verifier_user_id": None,
        "terminated_reason": None,
    })
    db.awards[award["id"]] = award

    for claim in base:
        if assign(claim, "is_ehcl", flags[claim["id"]]):
            touch(claim)

    for claim in deferred:
        assign(claim, "claim_state", "EHCL_DEFERRED")
        touch(claim)
        location = db.locations.get(claim["location_id"])
        if location is not None:
            assign(location, "eligibility_state", "DEFERRED_HIGH_COST")
            touch(location)

    for claim, share in shares:
        assign(claim, "claim_state", "AWARD_BOUND")
        assign(claim, "match_share_cents", share)
        touch(claim)
        location = db.locations.get(claim["location_id"])
        if location is not None:
            assign(location, "eligibility_state", "AWARD_BOUND")
            assign(location, "awarded_award_id", award["id"])
            touch(location)

    assign(application, "application_state", "AWARDED")
    domain.refresh_application(application)
    touch(application)

    domain.append_ledger(award, "OBLIGATION", obligation,
                         "application:%s" % application["id"],
                         "Obligation of the federal share to the selected application")
    if domain.refresh_award(award):
        touch(award)
    return object_response(serialize(award), 201)


@bp.get("/broadband/awards/<award_id>")
def get_award(award_id):
    authenticate(*READ_ROLES)
    award = domain.require_award(award_id)
    return object_response(serialize(award))


@bp.get("/broadband/awards")
def list_awards():
    authenticate(*LIST_ROLES)
    limit, offset = pagination()
    rows = list(db.awards.values())
    for field in ("application_id", "award_state", "compliance_state"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    return paginated(rows, limit, offset)


@bp.post("/broadband/awards/<award_id>/authorize-construction")
def authorize_construction(award_id):
    authenticate("ProgramAdmin")
    award = domain.require_award(award_id)                               # priority 25
    if award["award_state"] != "OBLIGATED":                              # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    review = domain.find_env_review(award)
    if review is None or review["ehp_state"] != "CLEARED":               # priority 55
        raise ApiError("ERR_EHP_NOT_CLEARED")

    assign(award, "award_state", "CONSTRUCTION_AUTHORIZED")
    touch(award)
    for location in domain.locations_of_award(award["id"]):
        if (location["eligibility_state"] == "AWARD_BOUND"
                and location["service_state"] == "NOT_BUILT"):
            assign(location, "service_state", "UNDER_CONSTRUCTION")
            touch(location)
    return object_response(serialize(award))


@bp.post("/broadband/awards/<award_id>/terminate")
def terminate_award(award_id):
    authenticate("ProgramAdmin")
    body = json_body()
    reason = get_str(body, "terminated_reason")                          # priority 14

    award = domain.require_award(award_id)                               # priority 25
    if award["award_state"] not in TERMINABLE_STATES:                    # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if (award["award_state"] == "IN_CONSTRUCTION"
            and award["compliance_state"] != "NONCOMPLIANT"):
        raise ApiError("ERR_AWARD_STATE_INVALID")

    cascades.termination_cascade(award, reason)
    return object_response(serialize(award))


@bp.get("/broadband/awards/<award_id>/ledger-entries")
def list_ledger_entries(award_id):
    authenticate(*LEDGER_READ_ROLES)
    limit, offset = pagination()
    award = domain.require_award(award_id)
    return paginated(domain.ledger_of_award(award["id"]), limit, offset)
