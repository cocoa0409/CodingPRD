"""Outcome records, the adopter-return reversal's counterpart, and the
live-release report."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import gates
import services
from errors import ApiError
from routing import listing, must, must_fk, query_filters
from store import DB
from validation import (ENUM_MEMBERS, Field, LIVE_OUTCOME_TYPES, NON_LIVE_OUTCOME_TYPES,
                        parse_body, parse_date)

bp = Blueprint("outcomes", __name__)

# Gate 3's scope on this endpoint is exactly these three outcome types; a
# non-live outcome is NOT blocked by a legal hold (PRD 2.6).
LEGAL_HOLD_GATED_OUTCOMES = ("ADOPTION", "TRANSFER_OUT", "RETURN_TO_OWNER")


@bp.post("/rescue/animals/<animal_id>/outcomes")
def record_outcome(animal_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer"])
    body = parse_body(request, [
        Field("outcome_type", "string", required=True, enum="outcome_type"),
        Field("partner_commitment_id", "string", default=None),
        Field("counterparty_person_id", "string", default=None),
    ])
    if body["outcome_type"] == "TRANSFER_OUT" and not body["partner_commitment_id"]:
        raise ApiError("ERR_VALIDATION",
                       "partner_commitment_id is required when outcome_type is TRANSFER_OUT.")
    animal = must("Animal", animal_id)
    must_fk("PartnerCommitment", body["partner_commitment_id"])
    must_fk("Person", body["counterparty_person_id"])

    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True,
                    gate3=body["outcome_type"] in LEGAL_HOLD_GATED_OUTCOMES)

    episode = derive.open_episode(animal)
    if animal["lifecycle_status"] != "IN_CUSTODY" or episode is None:
        raise ApiError("ERR_INVALID_STATE",
                       "The animal must be IN_CUSTODY with its current episode still OPEN.")

    outcome = services.write_outcome(
        animal, body["outcome_type"],
        counterparty_person_id=body["counterparty_person_id"],
        partner_commitment_id=body["partner_commitment_id"])
    return envelope.created(derive.outcome_record(outcome))


@bp.get("/rescue/outcomes/<outcome_id>")
def read_outcome(outcome_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "AdoptionCounselor", "FinanceOfficer"])
    return envelope.ok(derive.outcome_record(must("OutcomeRecord", outcome_id)))


@bp.get("/rescue/outcomes")
def list_outcomes():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "AdoptionCounselor", "FinanceOfficer"])
    return listing("OutcomeRecord", DB.all("OutcomeRecord"),
                   query_filters(["animal_id", "intake_record_id", "adoption_id",
                                  "partner_commitment_id", "counterparty_person_id",
                                  "outcome_type"]))


@bp.get("/rescue/reports/live-release-rate")
def live_release_rate():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "FinanceOfficer"])
    from_raw = request.args.get("from_date")
    to_raw = request.args.get("to_date")
    if not from_raw or not to_raw:
        raise ApiError("ERR_VALIDATION", "from_date and to_date are required.")
    methodology = request.args.get("methodology")
    organization_id = request.args.get("organization_id")
    # PRD 2.9 names `methodology` as the ONE query parameter that routes to
    # ERR_INVALID_ENUM; every other list filter is silent about bad values.
    if methodology is not None and methodology != "":
        if methodology not in ENUM_MEMBERS["methodology"]:
            raise ApiError("ERR_INVALID_ENUM", "methodology carries an undeclared enum member.")
    else:
        methodology = None
    from_date = parse_date(from_raw, "from_date")
    to_date = parse_date(to_raw, "to_date")

    if methodology is None:
        org = DB.get("Organization", organization_id) if organization_id else None
        methodology = org["default_methodology"] if org else "SAC"

    pool = []
    for outcome in DB.all("OutcomeRecord"):
        if outcome["reversed_at"] is not None:
            continue
        recorded = clock.parse(outcome["recorded_at"]).date().isoformat()
        if recorded < from_date or recorded > to_date:
            continue
        if organization_id:
            animal = DB.get("Animal", outcome["animal_id"])
            if animal is None or animal["current_organization_id"] != organization_id:
                continue
        pool.append(outcome)

    live = sum(1 for o in pool if o["outcome_type"] in LIVE_OUTCOME_TYPES)
    non_live = sum(1 for o in pool if o["outcome_type"] in NON_LIVE_OUTCOME_TYPES)
    owner_req = sum(1 for o in pool if o["outcome_type"] == "EUTHANASIA_OWNER_REQUESTED")
    denominator = live + non_live if methodology == "SAC" else live + non_live - owner_req
    if denominator <= 0:
        rate = None
    else:
        rate = float(calc.round_dp(Decimal(live) / Decimal(denominator),
                                   calc.LIVE_RELEASE_RATE_PRECISION_DP))
    return envelope.ok({
        "methodology": methodology,
        "from_date": from_date,
        "to_date": to_date,
        "live_outcome_count": live,
        "non_live_outcome_count": non_live,
        "owner_requested_euthanasia_count": owner_req,
        "denominator": denominator,
        "live_release_rate": rate,
    })
