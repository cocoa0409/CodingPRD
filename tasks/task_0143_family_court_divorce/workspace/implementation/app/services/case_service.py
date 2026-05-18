"""Cross-resource helpers used by route handlers.

Kept thin: the canonical PRD logic lives in the per-route handler, while this
module owns helpers that touch multiple tables (e.g. "is the petitioner's
disclosure accepted?", "auto-supersede older support orders of the same type").
"""
from app import store


# ---------- disclosures / parties -----------------------------------------

def disclosures_for_case(case_id):
    return [d for d in store.disclosures.values() if d["case_id"] == case_id]


def latest_accepted_disclosure(case_id, party_id):
    """Most recent ACCEPTED disclosure for the (case, party)."""
    items = [
        d for d in store.disclosures.values()
        if d["case_id"] == case_id and d["party_id"] == party_id and d["status"] == "ACCEPTED"
    ]
    if not items:
        return None
    items.sort(key=lambda d: d["updated_at"], reverse=True)
    return items[0]


def latest_disclosure(case_id, party_id):
    items = [
        d for d in store.disclosures.values()
        if d["case_id"] == case_id and d["party_id"] == party_id
    ]
    if not items:
        return None
    items.sort(key=lambda d: d["created_at"], reverse=True)
    return items[0]


def both_disclosures_accepted(case_id) -> bool:
    case = store.cases.get(case_id)
    if not case:
        return False
    p = latest_accepted_disclosure(case_id, case["petitioner_party_id"])
    r = latest_accepted_disclosure(case_id, case["respondent_party_id"])
    return p is not None and r is not None


# ---------- plans ---------------------------------------------------------

def plans_for_case(case_id):
    return [p for p in store.parenting_plans.values() if p["case_id"] == case_id]


def latest_active_plan(case_id):
    """Most recently created plan still in PROPOSED or COUNTERED."""
    items = [
        p for p in plans_for_case(case_id)
        if p["status"] in {"PROPOSED", "COUNTERED"}
    ]
    if not items:
        return None
    items.sort(key=lambda p: p["created_at"], reverse=True)
    return items[0]


# ---------- support orders ------------------------------------------------

def issue_support_order(so, ts):
    """Mark `so` as ISSUED; supersede any older ISSUED orders of the same type."""
    case_id = so["case_id"]
    s_type = so["support_type"]
    # Find existing ISSUED order of same type, supersede it.
    for other in list(store.support_orders.values()):
        if (
            other["id"] != so["id"]
            and other["case_id"] == case_id
            and other["support_type"] == s_type
            and other["status"] == "ISSUED"
        ):
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = so["id"]
            other["updated_at"] = ts
            other["version"] += 1
    so["status"] = "ISSUED"
    so["effective_from"] = ts
    so["updated_at"] = ts
    so["version"] += 1


# ---------- case status transitions ---------------------------------------

def maybe_advance_to_awaiting_judgment(case, ts):
    """If preconditions are met after a temp order issues, move to AWAITING_JUDGMENT."""
    if case["status"] != "TEMP_ORDERED":
        return
    if not case["has_minor_children"]:
        case["status"] = "AWAITING_JUDGMENT"
        case["updated_at"] = ts
        case["version"] += 1
        return
    plans = plans_for_case(case["id"])
    if any(p["status"] in {"AGREED", "COURT_IMPOSED"} for p in plans):
        case["status"] = "AWAITING_JUDGMENT"
        case["updated_at"] = ts
        case["version"] += 1


def maybe_advance_mediation_to_judgment(case, ts):
    """Per §3.4: MEDIATION → AWAITING_JUDGMENT once a plan is AGREED, or after
    the cap is hit and a COURT_IMPOSED plan exists."""
    if case["status"] != "MEDIATION":
        return
    plans = plans_for_case(case["id"])
    if any(p["status"] == "AGREED" for p in plans):
        case["status"] = "AWAITING_JUDGMENT"
        case["updated_at"] = ts
        case["version"] += 1
        return
    if case["mediation_round"] >= 3 and any(p["status"] == "COURT_IMPOSED" for p in plans):
        case["status"] = "AWAITING_JUDGMENT"
        case["updated_at"] = ts
        case["version"] += 1


def bump_case_status_on_first_submit(case, ts):
    """ANSWERED → DISCLOSURE when first disclosure on the case is submitted."""
    if case["status"] == "ANSWERED":
        case["status"] = "DISCLOSURE"
        case["updated_at"] = ts
        case["version"] += 1


def maybe_defaulted_petitioner_accepted(case, accepted_disclosure, ts):
    """If a DEFAULTED case sees the petitioner's disclosure ACCEPTED, move it
    straight to AWAITING_JUDGMENT (skipping mediation)."""
    if case["status"] != "DEFAULTED":
        return
    if accepted_disclosure["party_id"] != case["petitioner_party_id"]:
        return
    case["status"] = "AWAITING_JUDGMENT"
    case["updated_at"] = ts
    case["version"] += 1


# ---------- party-scope helpers used by sub-resource routes ---------------

def attorney_represents(party, attorney_id):
    return party is not None and party.get("counsel_user_id") == attorney_id


def assert_party_scope_for_party_id(case, party_id, role_name, uid):
    """Used when a body field names the acting party (e.g. proposing_party_id).

    Petitioner/Respondent: X-User-ID must equal the acting party id, and the
        named party must be of the correct role on the case.
    AttorneyOfRecord: must be counsel for the acting party.
    """
    from app.errors import forbidden
    party = store.parties.get(party_id)
    if party is None or party["case_id"] != case["id"]:
        raise forbidden("Party does not belong to this case")
    if role_name == "Petitioner":
        if uid != party["id"] or party["id"] != case["petitioner_party_id"]:
            raise forbidden("Caller is not the named petitioner")
    elif role_name == "Respondent":
        if uid != party["id"] or party["id"] != case["respondent_party_id"]:
            raise forbidden("Caller is not the named respondent")
    elif role_name == "AttorneyOfRecord":
        if party.get("counsel_user_id") != uid:
            raise forbidden("Attorney does not represent that party")
    return party
