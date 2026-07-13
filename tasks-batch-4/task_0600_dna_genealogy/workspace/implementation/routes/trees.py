"""Family trees and tree people (PRD §3.9)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate
from routes.common import body, require_int, require_string

bp = Blueprint("trees", __name__)


def _tier_limit(customer_id):
    return calc.TIER_TREE_PERSON_LIMIT[S.tier_of(customer_id)]


def _creates_cycle(tree_id, parent_id, new_person_id=None):
    """Walk up the parent graph from parent_id; a cycle exists if we reach the new person."""
    seen = set()
    frontier = [parent_id]
    while frontier:
        current = frontier.pop()
        if current is None or current in seen:
            continue
        seen.add(current)
        if new_person_id is not None and current == new_person_id:
            return True
        person = db.db.persons.get(current)
        if not person:
            continue
        frontier.append(person["father_id"])
        frontier.append(person["mother_id"])
    return False


@bp.post("/dna/family-trees")
@endpoint(["Customer"])
def create_tree():
    payload = body()
    S.require_fields(payload, ["customer_id", "name"])
    customer = S.get("customers", payload["customer_id"])
    require_owner(customer["id"])
    name = require_string(payload["name"], "name")
    S.require_not_purged(customer)

    tree = db.new_record(
        {"customer_id": customer["id"], "name": name, "status": "ACTIVE", "person_count": 0}
    )
    db.db.trees[tree["id"]] = tree
    return ok(S.tree_json(tree), 201)


@bp.get("/dna/family-trees/<tree_id>")
@endpoint(["Customer", "PlatformAdmin"])
def read_tree(tree_id):
    tree = S.get("trees", tree_id)
    require_owner(tree["customer_id"])
    return ok(S.tree_json(tree))


@bp.get("/dna/family-trees")
@endpoint(["Customer", "PlatformAdmin"])
def list_trees():
    records = S.all_of("trees")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.tree_json)


@bp.post("/dna/tree-people")
@endpoint(["Customer"])
def create_person():
    payload = body()
    S.require_fields(payload, ["tree_id", "given_name", "surname"])

    tree = S.get("trees", payload["tree_id"])
    father = S.get("persons", payload["father_id"]) if payload.get("father_id") else None
    mother = S.get("persons", payload["mother_id"]) if payload.get("mother_id") else None
    linked = (
        S.get("customers", payload["linked_customer_id"])
        if payload.get("linked_customer_id")
        else None
    )

    require_owner(tree["customer_id"])

    given_name = require_string(payload["given_name"], "given_name")
    surname = require_string(payload["surname"], "surname")
    birth_year = payload.get("birth_year")
    if birth_year is not None:
        birth_year = require_int(birth_year, "birth_year", exclusive_min=0)

    owner = db.db.customers[tree["customer_id"]]
    S.require_not_purged(owner)

    for parent in (father, mother):
        if parent is None:
            continue
        if parent["tree_id"] != tree["id"]:
            raise ApiError("ERR_TREE_CYCLE", "A parent link must point inside the same tree.")
        if _creates_cycle(tree["id"], parent["id"]):
            raise ApiError("ERR_TREE_CYCLE")

    if tree["person_count"] + 1 > _tier_limit(tree["customer_id"]):
        raise ApiError("ERR_TREE_PERSON_LIMIT")

    person = db.new_record(
        {
            "tree_id": tree["id"],
            "father_id": father["id"] if father else None,
            "mother_id": mother["id"] if mother else None,
            "linked_customer_id": linked["id"] if linked else None,
            "given_name": given_name,
            "surname": surname,
            "birth_year": birth_year,
            "status": "ACTIVE",
            "hint_count": 0,
        }
    )
    db.db.persons[person["id"]] = person

    tree["person_count"] = tree["person_count"] + 1
    db.touch(tree)
    return ok(S.person_json(person), 201)


@bp.get("/dna/tree-people/<person_id>")
@endpoint(["Customer", "PlatformAdmin"])
def read_person(person_id):
    person = S.get("persons", person_id)
    owner = S.owner_of_tree_person(person)
    if owner is not None:
        require_owner(owner)
    return ok(S.person_json(person))


@bp.get("/dna/tree-people")
@endpoint(["Customer", "PlatformAdmin"])
def list_persons():
    records = S.all_of("persons")
    for field in ("tree_id", "father_id", "mother_id", "linked_customer_id", "status"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r[field] == value]
    return paginate(records, S.person_json)
