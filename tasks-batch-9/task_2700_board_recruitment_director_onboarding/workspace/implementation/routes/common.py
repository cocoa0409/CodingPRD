"""Helpers shared by every blueprint: 404 resolution, filters and list emission."""

from flask import request

from calc import sorted_rows
from envelope import created, ok, paginate
from errors import fail
from store import db, public, public_list

NOT_FOUND = {
    "policy": ("ERR_POLICY_NOT_FOUND", "policy"),
    "skill_category": ("ERR_SKILL_CATEGORY_NOT_FOUND", "skill category"),
    "search_firm": ("ERR_SEARCH_FIRM_NOT_FOUND", "search firm"),
    "external_company": ("ERR_EXTERNAL_COMPANY_NOT_FOUND", "external company"),
    "director": ("ERR_DIRECTOR_NOT_FOUND", "director"),
    "skill_rating": ("ERR_SKILL_RATING_NOT_FOUND", "skill rating"),
    "candidate": ("ERR_CANDIDATE_NOT_FOUND", "candidate"),
    "screen": ("ERR_SCREEN_NOT_FOUND", "independence screen"),
    "directorship": ("ERR_DIRECTORSHIP_NOT_FOUND", "external directorship"),
    "interview": ("ERR_INTERVIEW_NOT_FOUND", "interview session"),
    "committee": ("ERR_COMMITTEE_NOT_FOUND", "committee"),
    "assignment": ("ERR_ASSIGNMENT_NOT_FOUND", "committee assignment"),
    "slate": ("ERR_SLATE_NOT_FOUND", "nomination slate"),
    "nominee": ("ERR_NOMINEE_NOT_FOUND", "slate nominee"),
    "vote": ("ERR_VOTE_NOT_FOUND", "committee vote"),
    "onboarding_item": ("ERR_ONBOARDING_ITEM_NOT_FOUND", "onboarding item"),
    "comp_award": ("ERR_COMP_AWARD_NOT_FOUND", "compensation award"),
}

COLLECTION_OF = {
    "policy": "policies",
    "skill_category": "skill_categories",
    "search_firm": "search_firms",
    "external_company": "external_companies",
    "director": "directors",
    "skill_rating": "skill_ratings",
    "candidate": "candidates",
    "screen": "screens",
    "directorship": "directorships",
    "interview": "interviews",
    "committee": "committees",
    "assignment": "assignments",
    "slate": "slates",
    "nominee": "nominees",
    "vote": "votes",
    "onboarding_item": "onboarding_items",
    "comp_award": "comp_awards",
}


def need(kind, row_id):
    """Resolve one identifier or raise that identifier type's own 404."""
    error_id, label = NOT_FOUND[kind]
    collection = getattr(db, COLLECTION_OF[kind])
    if row_id is None:
        fail(error_id, "No %s identifier was supplied." % label)
    row = collection.get(row_id)
    if row is None:
        fail(error_id, "No %s exists with id %s." % (label, row_id))
    return row


def truthy(raw):
    return str(raw).strip().lower() in ("true", "1", "yes", "y")


def apply_filters(rows, spec):
    """spec maps a query-parameter name onto (row field, coercion)."""
    for param, pair in spec.items():
        field, kind = pair
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "int":
            try:
                value = int(str(raw).strip())
            except (TypeError, ValueError):
                return []
            rows = [r for r in rows if r.get(field) == value]
        elif kind == "bool":
            value = truthy(raw)
            rows = [r for r in rows if bool(r.get(field)) is value]
        else:
            rows = [r for r in rows if r.get(field) == raw]
    return rows


def emit(row, status=200):
    if status == 201:
        return created(public(row))
    return ok(public(row))


def emit_list(rows):
    return paginate(public_list(rows))


def by_created_at(rows):
    return sorted_rows(rows)


def by_field(rows, field, reverse=False):
    return sorted_rows(rows, key=lambda r: r.get(field), reverse=reverse)


def by_created_desc(rows):
    return sorted_rows(rows, reverse=True)
