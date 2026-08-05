"""Shared route helpers: scope rules, filters and small lookups."""

from core import constants, store
from core.errors import ApiError


def scope_rule(participant_of=None, employer_of=None, visit_provider_of=None):
    """Build a rung-5 identity-scope check (PRD 2.1).

    `participant_of` / `employer_of` / `visit_provider_of` are callables that
    return the identifier the acting role's `X-User-ID` must match, or None
    when the rule does not engage for this request.
    """

    def check(ctx):
        if participant_of is not None and ctx.role == constants.ROLE_PARTICIPANT:
            owner = participant_of(ctx)
            if owner is not None and owner != ctx.user_id:
                raise ApiError("ERR_SCOPE_VIOLATION")
        if employer_of is not None and ctx.role == constants.ROLE_EMPLOYER_BENEFITS_ADMIN:
            owner = employer_of(ctx)
            if owner is not None and owner != ctx.user_id:
                raise ApiError("ERR_SCOPE_VIOLATION")
        if visit_provider_of is not None and ctx.role == constants.ROLE_CLINICIAN:
            owner = visit_provider_of(ctx)
            if owner is not None and owner != ctx.user_id:
                raise ApiError("ERR_SCOPE_VIOLATION")

    return check


def employer_id_of_participant(participant):
    if participant is None:
        return None
    return participant.get("employer_id")


def participant_of_visit(visit):
    if visit is None:
        return None
    return store.get("participant", visit.get("participant_id"))


def employer_of_visit(visit):
    return employer_id_of_participant(participant_of_visit(visit))


def filter_rows(rows, filters):
    """Apply exact-match query filters; an absent parameter never filters."""
    out = rows
    for field, value in filters.items():
        if value is None or value == "":
            continue
        out = [r for r in out if r.get(field) == value]
    return out


def contracts_of_employer(employer_id):
    return [c for c in store.all_rows("contract") if c["employer_id"] == employer_id]


def participants_of_employer(employer_id):
    return [p for p in store.all_rows("participant") if p["employer_id"] == employer_id]


def visits_of_employer(employer_id):
    ids = {p["id"] for p in participants_of_employer(employer_id)}
    return [v for v in store.all_rows("visit") if v["participant_id"] in ids]
