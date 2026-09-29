"""Non-admitted insurers and their market security reviews (PRD 3.2)."""

from flask import Blueprint

import auth
import clock
import serialize
import store
import validation
from calc import market_security
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("carriers", __name__)

DOMICILE_TYPES = ("US_STATE", "ALIEN")
RATINGS = tuple(market_security.RATING_POINTS.keys())
DECISIONS = ("APPROVE", "CONDITION", "DECLINE")


@bp.post("/carriers")
def create_carrier():
    auth.require("PlatformAdmin")
    data = validation.body()
    naic_number = validation.req_str(data, "naic_number")
    legal_name = validation.req_str(data, "legal_name")
    domicile_type = validation.req_enum(data, "domicile_type", DOMICILE_TYPES)
    capital = validation.req_int(data, "capital_surplus_cents", minimum=0)
    rating = validation.req_enum(data, "am_best_rating", RATINGS)
    trust = validation.opt_int(data, "trust_fund_cents", default=0, minimum=0)
    listing = validation.opt_bool(data, "naic_quarterly_listing", default=False)

    if store.carrier_by_naic(naic_number) is not None:
        raise ApiError("ERR_CARRIER_DUPLICATE",
                       "A carrier with NAIC number %s already exists." % naic_number)

    rec = db.insert("carriers", {
        "naic_number": naic_number,
        "legal_name": legal_name,
        "domicile_type": domicile_type,
        "capital_surplus_cents": capital,
        "am_best_rating": rating,
        "trust_fund_cents": trust,
        "naic_quarterly_listing": listing,
        "security_status": "UNREVIEWED",
    })
    return created(serialize.public(rec))


@bp.get("/carriers/<rec_id>")
def get_carrier(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("carriers", "carrier", rec_id)
    return ok(serialize.public(rec))


@bp.patch("/carriers/<rec_id>")
def patch_carrier(rec_id):
    """The only way a carrier's version advances outside a security decision —
    and therefore the thing that makes a pending decision stale."""
    auth.require("PlatformAdmin")
    rec = auth.path_entity("carriers", "carrier", rec_id)
    data = validation.body()

    if validation.present(data, "capital_surplus_cents"):
        rec["capital_surplus_cents"] = validation.req_int(
            data, "capital_surplus_cents", minimum=0)
    if validation.present(data, "am_best_rating"):
        rec["am_best_rating"] = validation.req_enum(data, "am_best_rating", RATINGS)
    if validation.present(data, "trust_fund_cents"):
        rec["trust_fund_cents"] = validation.req_int(data, "trust_fund_cents",
                                                     minimum=0)
    if validation.present(data, "naic_quarterly_listing"):
        rec["naic_quarterly_listing"] = validation.req_bool(
            data, "naic_quarterly_listing")

    # security_status is deliberately NOT re-derived here.
    touch(rec)
    return ok(serialize.public(rec))


# --- market security reviews ---------------------------------------------

@bp.post("/carriers/<rec_id>/security-reviews")
def open_review(rec_id):
    auth.require("ComplianceOfficer")
    carrier = auth.path_entity("carriers", "carrier", rec_id)
    rec = db.insert("market_security_reviews", {
        "carrier_id": carrier["id"],
        "status": "DRAFT",
        "score": 0,
        "variant_applied": None,
        "capital_surplus_at_review_cents": None,
        "rating_at_review": None,
        "reviewer_user_id": None,
        "conditions_note": None,
    })
    return created(serialize.public(rec))


@bp.get("/carriers/<rec_id>/security-reviews")
def list_reviews(rec_id):
    auth.require(auth.ANY)
    carrier = auth.path_entity("carriers", "carrier", rec_id)
    rows = store.reviews_of_carrier(carrier["id"])
    rows = filtered(rows, status=arg("status"))
    return list_response(rows)


@bp.post("/market-security-reviews/<rec_id>/start")
def start_review(rec_id):
    auth.require("ComplianceOfficer")
    review = auth.path_entity("market_security_reviews", "market_security_review",
                              rec_id)
    if review.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT review may be started.")
    carrier = db.get("carriers", review.get("carrier_id"))
    for other in store.reviews_of_carrier(review.get("carrier_id")):
        if other["id"] != review["id"] and other.get("status") == "UNDER_REVIEW":
            raise ApiError("ERR_REVIEW_ALREADY_OPEN",
                           "Another review of this carrier is already open.")
    if carrier is None or carrier.get("capital_surplus_cents") is None:
        raise ApiError("ERR_INVALID_STATE",
                       "The carrier has no capital and surplus on record.")

    variant, score = market_security.compute(carrier)
    review["variant_applied"] = variant
    review["score"] = score
    review["status"] = "UNDER_REVIEW"
    touch(review)
    return ok(serialize.public(review))


def _decline_cascade(carrier):
    """Hop 3 of the depth-3 cascade: strike the carrier from every white list,
    processed in ascending state_code of the program each entry points at."""
    rows = store.eligibilities_of(carrier["id"])
    keyed = []
    for row in rows:
        program = db.get("state_programs", row.get("state_program_id"))
        keyed.append(((program or {}).get("state_code") or "", row))
    for _code, row in sorted(keyed, key=lambda pair: pair[0]):
        if row.get("listing_status") != "WHITE_LISTED":
            continue
        row["listing_status"] = "REMOVED"
        row["removed_on"] = clock.now_raw()
        row["_removed_at"] = clock.now()
        touch(row)


@bp.post("/market-security-reviews/<rec_id>/decide")
def decide_review(rec_id):
    auth.require("ComplianceOfficer")
    review = auth.path_entity("market_security_reviews", "market_security_review",
                              rec_id)
    data = validation.body()
    decision = validation.req_enum(data, "decision", DECISIONS)
    expected = validation.req_int(data, "expected_carrier_version")
    # conditions_note is optional at rung 6; its non-emptiness is a rung-16
    # documentary check on the CONDITION branch, reported as
    # ERR_CONDITIONS_NOTE_REQUIRED rather than ERR_INVALID_REQUEST.
    note = validation.opt_str(data, "conditions_note", allow_blank=True)

    carrier = db.get("carriers", review.get("carrier_id"))
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")

    # Rung 8: the decision pins the carrier's figures, so a stale view is fatal.
    auth.check_version(expected, carrier, "ERR_STALE_CARRIER_VERSION")

    if review.get("status") != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an UNDER_REVIEW review may be decided.")

    if not market_security.decision_matches_band(decision, review.get("score")):
        raise ApiError("ERR_DECISION_SCORE_MISMATCH",
                       "The score of %s does not support a %s decision."
                       % (review.get("score"), decision))
    if decision == "CONDITION" and (note is None or note.strip() == ""):
        raise ApiError("ERR_CONDITIONS_NOTE_REQUIRED",
                       "A CONDITIONAL decision requires a conditions_note.")

    status = market_security.DECISION_STATUS[decision]
    review["reviewer_user_id"] = auth.user_id()
    review["capital_surplus_at_review_cents"] = carrier.get("capital_surplus_cents")
    review["rating_at_review"] = carrier.get("am_best_rating")
    if decision == "CONDITION":
        review["conditions_note"] = note
    review["status"] = status
    touch(review)

    # Hop 2: the carrier mirrors the outcome.
    carrier["security_status"] = status
    touch(carrier)

    if decision == "DECLINE":
        _decline_cascade(carrier)

    return ok(serialize.public(review))
