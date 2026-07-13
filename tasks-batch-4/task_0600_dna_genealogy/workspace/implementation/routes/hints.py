"""Record hints and hint acceptance (PRD §3.9)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate

bp = Blueprint("hints", __name__)


@bp.get("/dna/record-hints/<hint_id>")
@endpoint(["Customer", "PlatformAdmin"])
def read_hint(hint_id):
    hint = S.get("hints", hint_id)
    person = db.db.persons.get(hint["person_id"])
    if person is not None:
        owner = S.owner_of_tree_person(person)
        if owner is not None:
            require_owner(owner)
    return ok(S.hint_json(hint))


@bp.get("/dna/record-hints")
@endpoint(["Customer", "PlatformAdmin"])
def list_hints():
    records = S.all_of("hints")
    for field in ("person_id", "source_match_id", "status"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r[field] == value]
    return paginate(records, S.hint_json)


@bp.post("/dna/record-hints/<hint_id>/accept")
@endpoint(["Customer"])
def accept_hint(hint_id):
    hint = S.get("hints", hint_id)
    person = db.db.persons.get(hint["person_id"])
    if person is None:
        raise ApiError("ERR_PERSON_NOT_FOUND")
    tree = db.db.trees.get(person["tree_id"])
    if tree is None:
        raise ApiError("ERR_TREE_NOT_FOUND")

    require_owner(tree["customer_id"])

    owner = db.db.customers[tree["customer_id"]]
    S.require_not_purged(owner)

    if hint["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    limit = calc.TIER_TREE_PERSON_LIMIT[S.tier_of(tree["customer_id"])]
    if tree["person_count"] + 1 > limit:
        raise ApiError("ERR_TREE_PERSON_LIMIT")

    # The counterpart is the other side of the hint's source match.
    counterpart = None
    match = db.db.matches.get(hint["source_match_id"]) if hint["source_match_id"] else None
    if match is not None:
        other_id = (
            match["customer_b_id"]
            if match["customer_a_id"] == tree["customer_id"]
            else match["customer_a_id"]
        )
        counterpart = db.db.customers.get(other_id)

    hint["status"] = "ACCEPTED"
    db.touch(hint)

    person["hint_count"] = max(0, person["hint_count"] - 1)
    db.touch(person)

    new_person = db.new_record(
        {
            "tree_id": tree["id"],
            "father_id": None,
            "mother_id": None,
            "linked_customer_id": counterpart["id"] if counterpart else None,
            "given_name": counterpart["display_name"] if counterpart else None,
            "surname": "DNA_MATCH",
            "birth_year": None,
            "status": "ACTIVE",
            "hint_count": 0,
        }
    )
    db.db.persons[new_person["id"]] = new_person

    tree["person_count"] = tree["person_count"] + 1
    db.touch(tree)

    return ok(S.hint_json(hint))
