"""Flat top-level GET endpoints (FK reverse-reachability forms). All read-only."""

from flask import Blueprint

import db
from core import serialize_cycle, serialize_fundraiser
from errors import ERR_NOT_FOUND, ApiError
from middleware import auth, require_roles
from response import apply_filters, list_response, serialize, serialize_many, sorted_items, success

bp = Blueprint("flat", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")
AD_ADV = ("ActivitiesDirector", "Advisor")

# (collection, store, filterable fields, read roles, serializer)
SPECS = [
    ("members", db.members, ["chapter_id", "inducted_cycle_id", "status"], ALL, serialize),
    ("membership-cycles", db.cycles, ["chapter_id", "status"], ALL, serialize_cycle),
    ("cycle-applications", db.applications,
     ["chapter_id", "cycle_id", "member_id", "status"], ALL, serialize),
    ("service-hour-entries", db.service_entries,
     ["chapter_id", "member_id", "status"], ALL, serialize),
    ("officer-elections", db.elections, ["chapter_id", "cycle_id", "status"], ALL, serialize),
    ("election-votes", db.votes,
     ["chapter_id", "election_id", "voter_member_id", "candidate_member_id", "status"],
     AD_ADV, serialize),
    ("officer-roles", db.officer_roles,
     ["chapter_id", "election_id", "member_id", "office", "status"], ALL, serialize),
    ("meeting-minutes", db.meeting_minutes,
     ["chapter_id", "called_by_officer_id", "submitted_by_officer_id", "status"], ALL, serialize),
    ("fundraiser-requests", db.fundraisers,
     ["chapter_id", "requested_by_officer_id", "status"], ALL, serialize_fundraiser),
    ("fund-ledger-entries", db.ledger_entries,
     ["chapter_id", "fundraiser_id", "entry_type", "status"], AD_ADV, serialize),
    ("dues-payments", db.dues_payments,
     ["chapter_id", "member_id", "academic_year", "status"], ALL, serialize),
    ("probation-cases", db.probation_cases,
     ["chapter_id", "member_id", "status", "reason_code"], ALL, serialize),
    ("athletics-blocks", db.athletics_blocks,
     ["chapter_id", "member_id", "status", "priority"], ALL, serialize),
]

# Per PRD section 4: flat single-fetch of fund-ledger-entries also allows Officer.
FETCH_ROLES = {
    "members": ALL,
    "membership-cycles": ALL,
    "cycle-applications": ALL,
    "service-hour-entries": ALL,
    "officer-elections": ALL,
    "election-votes": AD_ADV,
    "officer-roles": ALL,
    "meeting-minutes": ALL,
    "fundraiser-requests": ALL,
    "fund-ledger-entries": ("ActivitiesDirector", "Advisor", "Officer"),
    "dues-payments": ALL,
    "probation-cases": ALL,
    "athletics-blocks": ALL,
}


def _make_fetch(collection, store, serializer):
    def fetch(rid):
        _, role = auth()
        require_roles(role, FETCH_ROLES[collection])
        rec = store.get(rid)
        if rec is None:
            raise ApiError(ERR_NOT_FOUND, 404, f"{collection} record not found: {rid}")
        return success(serializer(rec), 200)
    fetch.__name__ = f"flat_fetch_{collection.replace('-', '_')}"
    return fetch


def _make_list(collection, store, filterable, serializer):
    def listing():
        _, role = auth()
        require_roles(role, AD_ADV)
        items = apply_filters(store.values(), filterable)
        return list_response([serializer(o) for o in sorted_items(items)])
    listing.__name__ = f"flat_list_{collection.replace('-', '_')}"
    return listing


for _collection, _store, _filterable, _roles, _serializer in SPECS:
    bp.add_url_rule(f"/{_collection}/<rid>", view_func=_make_fetch(_collection, _store, _serializer),
                    methods=["GET"])
    bp.add_url_rule(f"/{_collection}", view_func=_make_list(_collection, _store, _filterable, _serializer),
                    methods=["GET"])
