"""Shared cascade helpers and regulatory-prerequisite lookups."""

import constants as K
from errors import fail
from store import add_days, db, new_record, ordered, touch


# --- lookups ----------------------------------------------------------------

def program_of_asset(asset):
    return db.programs.get(asset["program_id"])


def program_of_vendor(vendor):
    return db.programs.get(vendor["program_id"])


def program_of_contract(contract):
    vendor = db.vendors.get(contract["vendor_id"])
    if vendor is None:
        return None
    return db.programs.get(vendor["program_id"])


def consents_for_asset(asset_id, statuses):
    return ordered(
        [c for c in db.consents.values() if c["asset_id"] == asset_id and c["status"] in statuses]
    )


def accommodations_for_asset(asset_id, statuses):
    return ordered(
        [
            a
            for a in db.accommodations.values()
            if a["asset_id"] == asset_id and a["status"] in statuses
        ]
    )


def accommodations_for_consent(consent_id, statuses):
    return ordered(
        [
            a
            for a in db.accommodations.values()
            if a["created_from_consent_id"] == consent_id and a["status"] in statuses
        ]
    )


def executed_contracts_for_vendor(vendor_id):
    return [
        c
        for c in db.contracts.values()
        if c["vendor_id"] == vendor_id and c["status"] == "EXECUTED"
    ]


# --- regulatory prerequisites (PRD 2.5 step 10) -----------------------------

def published_in_scope_policy(program_id, jurisdiction_id):
    """The single PUBLISHED policy of the program listing this jurisdiction."""
    for policy in ordered(list(db.policies.values())):
        if (
            policy["program_id"] == program_id
            and policy["status"] == "PUBLISHED"
            and jurisdiction_id in policy["jurisdiction_scope"]
        ):
            return policy
    return None


def published_notices(jurisdiction_id, audience):
    return ordered(
        [
            n
            for n in db.notices.values()
            if n["status"] == "PUBLISHED"
            and n["jurisdiction_id"] == jurisdiction_id
            and n["audience"] == audience
        ]
    )


def require_notice_coverage(juris, audience, check_lead=False):
    """Steps 10 and 11 for the notice stack.  Returns the covering packet."""
    candidates = published_notices(juris["id"], audience)
    if not candidates:
        fail(
            "ERR_NOTICE_NOT_PUBLISHED",
            "No published notice packet covers this jurisdiction and audience.",
        )
    if juris["translation_required"]:
        required = set(juris["required_locales"])
        translated = [n for n in candidates if required.issubset(set(n["locales"]))]
        if not translated:
            fail(
                "ERR_TRANSLATION_LOCALE_MISSING",
                "The published notice packet does not cover every required locale.",
            )
        candidates = translated
    if check_lead:
        eligible = [
            n
            for n in candidates
            if n["consent_eligible_from"] is not None and db.clock >= n["consent_eligible_from"]
        ]
        if not eligible:
            fail(
                "ERR_NOTICE_LEAD_NOT_MET",
                "The statutory notice lead time has not yet elapsed.",
            )
        candidates = eligible
    return candidates[0]


# --- accommodation creation -------------------------------------------------

def new_accommodation(
    subject_id, asset_id, method, starts_at, ends_at, origin, consent_id=None
):
    rec = new_record()
    rec.update(
        {
            "data_subject_id": subject_id,
            "asset_id": asset_id,
            "created_from_consent_id": consent_id,
            "method": method,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": "REQUESTED",
            "sla_due_at": add_days(db.clock, K.ACCOMMODATION_SLA_DAYS),
            "sla_breached": False,
            "origin": origin,
        }
    )
    db.accommodations[rec["id"]] = rec
    return rec


def auto_accommodation(consent, origin):
    """The AUTO_* compensating accommodation (PRD 3.7)."""
    asset = db.assets.get(consent["asset_id"])
    method = K.ACCOMMODATION_METHOD_MAP[asset["system_category"]]
    starts_at = db.clock
    return new_accommodation(
        consent["data_subject_id"],
        consent["asset_id"],
        method,
        starts_at,
        add_days(starts_at, K.AUTO_ACCOMMODATION_WINDOW_DAYS),
        origin,
        consent["id"],
    )


def end_accommodation(accommodation):
    accommodation["status"] = "ENDED"
    touch(accommodation)


# --- cascade A (PRD 3.2) ----------------------------------------------------

def cascade_a(contract):
    """Hops 2-5 of the vendor-contract termination cascade."""
    vendor_id = contract["vendor_id"]
    assets = ordered(
        [
            a
            for a in db.assets.values()
            if a.get("vendor_id") == vendor_id and a["status"] == "ACTIVE"
        ]
    )
    # hop 2: each affected asset ACTIVE -> GATED
    for asset in assets:
        asset["status"] = "GATED"
        touch(asset)

    # hop 3: every GRANTED consent on those assets GRANTED -> EXPIRED
    asset_ids = set(a["id"] for a in assets)
    granted = ordered(
        [
            c
            for c in db.consents.values()
            if c["asset_id"] in asset_ids and c["status"] == "GRANTED"
        ]
    )
    for consent in granted:
        consent["status"] = "EXPIRED"
        touch(consent)

    # hop 4: EMPLOYEE subjects get an AUTO_CONSENT_EXPIRY accommodation
    for consent in granted:
        subject = db.subjects.get(consent["data_subject_id"])
        if subject is not None and subject["subject_type"] == "EMPLOYEE":
            auto_accommodation(consent, "AUTO_CONSENT_EXPIRY")

    # hop 5: the program's counters and posture are rewritten (a real mutation)
    program = program_of_contract(contract)
    if program is not None:
        touch(program)


# --- cascade B (PRD 3.3) ----------------------------------------------------

def cascade_b(new_policy):
    """Hops 1-4 of the policy supersession cascade."""
    from calc import refresh_destruction_due_at

    program_id = new_policy["program_id"]
    superseded = None
    for policy in ordered(list(db.policies.values())):
        if (
            policy["program_id"] == program_id
            and policy["status"] == "PUBLISHED"
            and policy["id"] != new_policy["id"]
        ):
            superseded = policy
            break

    if superseded is None:
        return

    # hop 1
    superseded["status"] = "SUPERSEDED"
    touch(superseded)

    # hop 2: every consent pinned to the superseded policy loses its grant.
    # ALL consents move before ANY asset repins.
    consents = ordered(
        [
            c
            for c in db.consents.values()
            if c["pinned_policy_id"] == superseded["id"] and c["status"] == "GRANTED"
        ]
    )
    for consent in consents:
        consent["status"] = "RESOLICIT_REQUIRED"
        touch(consent)

    # hop 3: ACTIVE assets pinned to the superseded policy gate and repin
    assets = ordered(
        [
            a
            for a in db.assets.values()
            if a["pinned_policy_id"] == superseded["id"] and a["status"] == "ACTIVE"
        ]
    )
    for asset in assets:
        asset["status"] = "GATED"
        if asset["jurisdiction_id"] in new_policy["jurisdiction_scope"]:
            asset["pinned_policy_id"] = new_policy["id"]
        refresh_destruction_due_at(asset)
        touch(asset)

    # hop 4 (posture) is handled by the program version bump in the caller
