"""Reference resolution -- rungs 4 and 5 of the ladder (PRD 2.5).

Path identifiers are checked left to right; body references are checked in the
order the endpoint declares its input fields. Both use the same
identifier-to-error map, and every one of the thirteen codes is HTTP 404.
"""

import store
from errors import fail

NOT_FOUND = {
    "jurisdiction": "ERR_JURISDICTION_NOT_FOUND",
    "plan_cycle": "ERR_PLAN_CYCLE_NOT_FOUND",
    "hazard_profile": "ERR_HAZARD_PROFILE_NOT_FOUND",
    "asset": "ERR_ASSET_NOT_FOUND",
    "assessment": "ERR_ASSESSMENT_NOT_FOUND",
    "project": "ERR_PROJECT_NOT_FOUND",
    "link": "ERR_LINK_NOT_FOUND",
    "analysis": "ERR_ANALYSIS_NOT_FOUND",
    "program": "ERR_PROGRAM_NOT_FOUND",
    "session": "ERR_SESSION_NOT_FOUND",
    "endorsement": "ERR_ENDORSEMENT_NOT_FOUND",
    "pact": "ERR_PACT_NOT_FOUND",
    "commitment": "ERR_COMMITMENT_NOT_FOUND",
}

COLLECTION = {
    "jurisdiction": store.jurisdictions,
    "plan_cycle": store.plan_cycles,
    "hazard_profile": store.hazard_profiles,
    "asset": store.assets,
    "assessment": store.assessments,
    "project": store.projects,
    "link": store.links,
    "analysis": store.analyses,
    "program": store.programs,
    "session": store.sessions,
    "endorsement": store.endorsements,
    "pact": store.pacts,
    "commitment": store.commitments,
}


def need(kind, identifier):
    """Resolve an identifier or raise the kind's not-found error."""
    collection = COLLECTION[kind]
    if not isinstance(identifier, str):
        fail(NOT_FOUND[kind], "%s does not resolve to an existing row." % kind)
    row = collection.get(identifier)
    if row is None:
        fail(NOT_FOUND[kind], "%s %s was not found." % (kind, identifier))
    return row


def need_ref(kind, body, field):
    """Resolve a body reference when it is supplied; absence is a shape concern."""
    if field not in body or body.get(field) is None:
        return None
    return need(kind, body.get(field))


def links_of(project_id):
    rows = [row for row in store.ordered(store.links) if row["project_id"] == project_id]
    return sorted(rows, key=lambda row: row["link_sequence"])


def analyses_of(project_id):
    return [row for row in store.ordered(store.analyses) if row["project_id"] == project_id]


def certified_analysis(project_id):
    for row in analyses_of(project_id):
        if row["status"] == "CERTIFIED":
            return row
    return None


def assessments_of_asset(asset_id, status=None):
    rows = [row for row in store.ordered(store.assessments) if row["asset_id"] == asset_id]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return rows


def sessions_of_cycle(plan_cycle_id, status=None):
    rows = [row for row in store.ordered(store.sessions) if row["plan_cycle_id"] == plan_cycle_id]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return rows


def endorsements_of_cycle(plan_cycle_id, round_number=None):
    rows = [
        row for row in store.ordered(store.endorsements)
        if row["plan_cycle_id"] == plan_cycle_id
    ]
    if round_number is not None:
        rows = [row for row in rows if row["round_number"] == round_number]
    return rows


def projects_of_cycle(plan_cycle_id):
    return [row for row in store.ordered(store.projects) if row["plan_cycle_id"] == plan_cycle_id]


def projects_of_program(program_id):
    return [
        row for row in store.ordered(store.projects)
        if row["capital_program_id"] == program_id
    ]


def commitments_of_pact(pact_id, statuses=None):
    rows = [row for row in store.ordered(store.commitments) if row["pact_id"] == pact_id]
    if statuses is not None:
        rows = [row for row in rows if row["status"] in statuses]
    return rows
