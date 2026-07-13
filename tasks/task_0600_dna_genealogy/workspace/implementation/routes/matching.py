"""DNA-relative matching (PRD §3.8)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import acting_id, endpoint, is_customer, require_owner
from errors import ApiError
from response import ok, ok_list, paginate

bp = Blueprint("matching", __name__)


def _chip_of(sample):
    kit = db.db.kits.get(sample["kit_id"])
    return kit["chip_version"] if kit else None


def _existing_match(a_id, b_id):
    pair = {a_id, b_id}
    for match in db.db.matches.values():
        if {match["customer_a_id"], match["customer_b_id"]} == pair:
            return match
    return None


def _order_pair(one, two):
    """customer_a is the earlier created_at; tie-break the lexicographically lower email.
    Customer.id is never an ordering input."""
    ranked = sorted([one, two], key=lambda c: (c["created_at"], c["email"]))
    return ranked[0], ranked[1]


def _plant_hint(customer, match):
    person = S.root_person_for(customer["id"])
    if person is None:
        return
    hint = db.new_record(
        {
            "person_id": person["id"],
            "source_match_id": match["id"],
            "hint_type": "DNA_TREE",
            "status": "PENDING",
            "confidence": match["confidence_score"],
        }
    )
    db.db.hints[hint["id"]] = hint
    person["hint_count"] = person["hint_count"] + 1
    db.touch(person)


@bp.post("/dna/customers/<customer_id>/matches/recompute")
@endpoint(["Customer", "PlatformAdmin"])
def recompute(customer_id):
    customer = S.get("customers", customer_id)
    require_owner(customer["id"])

    S.require_not_purged(customer)

    actor_sample = S.source_sample(customer["id"])
    if customer["dna_status"] != "DNA_READY" or actor_sample is None:
        raise ApiError("ERR_DNA_NOT_READY")

    if not S.matching_opt_in(customer["id"]):
        raise ApiError("ERR_CONSENT_REQUIRED")

    actor_chip = _chip_of(actor_sample)

    for other in db.by_creation(list(db.db.customers.values())):
        if other["id"] == customer["id"]:
            continue
        if other["account_status"] != "ACTIVE" or other["dna_status"] != "DNA_READY":
            continue
        if not S.matching_opt_in(other["id"]):
            continue
        other_sample = S.source_sample(other["id"])
        if other_sample is None:
            continue  # silently skipped, not an error

        shared_cm, segment_count = calc.shared_segment_scan(
            actor_sample["genotype_markers"], other_sample["genotype_markers"]
        )
        if shared_cm < calc.MATCH_MIN_CM:
            continue

        relationship = calc.predicted_relationship(shared_cm)
        chip_mismatch = actor_chip != _chip_of(other_sample)
        confidence = calc.relative_match_confidence(
            shared_cm, segment_count, relationship, chip_mismatch
        )

        match = _existing_match(customer["id"], other["id"])
        if match is not None:
            match["shared_cm"] = float(shared_cm)
            match["segment_count"] = segment_count
            match["predicted_relationship"] = relationship
            match["confidence_score"] = float(confidence)
            db.touch(match)
            continue

        side_a, side_b = _order_pair(customer, other)
        match = db.new_record(
            {
                "customer_a_id": side_a["id"],
                "customer_b_id": side_b["id"],
                "shared_cm": float(shared_cm),
                "segment_count": segment_count,
                "predicted_relationship": relationship,
                "confidence_score": float(confidence),
                "status": "ACTIVE",
            }
        )
        db.db.matches[match["id"]] = match

        for side in (side_a, side_b):
            side["visible_match_count"] = side["visible_match_count"] + 1
            db.touch(side)
            _plant_hint(side, match)

    mine = [
        m
        for m in db.db.matches.values()
        if customer["id"] in (m["customer_a_id"], m["customer_b_id"])
    ]
    return ok_list([S.match_json(m) for m in db.by_creation(mine)])


@bp.get("/dna/relative-matches/<match_id>")
@endpoint(["Customer", "PlatformAdmin"])
def read_match(match_id):
    match = S.get("matches", match_id)
    if is_customer() and acting_id() not in (match["customer_a_id"], match["customer_b_id"]):
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return ok(S.match_json(match))


@bp.get("/dna/relative-matches")
@endpoint(["Customer", "PlatformAdmin"])
def list_matches():
    records = S.all_of("matches")
    a = request.args.get("customer_a_id")
    b = request.args.get("customer_b_id")
    status = request.args.get("status")
    if a:
        records = [r for r in records if r["customer_a_id"] == a]
    if b:
        records = [r for r in records if r["customer_b_id"] == b]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.match_json)
