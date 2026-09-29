"""The immediate recompute chain (PRD 2.8) plus the derived-metric formulas."""

from decimal import Decimal

import store as st
from store import apply_changes, store
from calcs import add_days, pct, round_half_up

COMPLIANT_MIN_PCT = Decimal("95.00")
AT_RISK_MIN_PCT = Decimal("80.00")
DOCUMENTATION_FLOOR_PCT = Decimal("80.00")
LOCATION_EMPTY_RATE_PCT = Decimal("100.00")
ACCOUNT_EMPTY_RATE_PCT = Decimal("0.00")

LIVE_ASSIGNMENT_STATES = ("ACTIVE", "WORK_RESTRICTED")


# --- lookups ---------------------------------------------------------------

def jurisdiction(jurisdiction_id):
    return st.get("state_jurisdictions", jurisdiction_id)


def training_requirement_for(location):
    jur = jurisdiction(location["state_jurisdiction_id"])
    tracks = jur["mandated_tracks"] if jur else []
    return "MANDATED" if location["premise_type"] in tracks else "VOLUNTARY"


def live_assignments_of_server(server_id):
    return [
        a for a in st.rows("server_assignments")
        if a["alcohol_server_id"] == server_id
        and a["assignment_state"] in LIVE_ASSIGNMENT_STATES
    ]


def live_assignments_at_location(location_id):
    return [
        a for a in st.rows("server_assignments")
        if a["employer_location_id"] == location_id
        and a["assignment_state"] in LIVE_ASSIGNMENT_STATES
    ]


def locations_of_account(account_id):
    return [
        l for l in st.rows("employer_locations")
        if l["employer_account_id"] == account_id
    ]


def certificates_of_server(server_id):
    return [c for c in st.rows("certificates") if c["alcohol_server_id"] == server_id]


# --- certificate selectors -------------------------------------------------

def certificate_selector(server_id):
    """The governing certificate: expires_at DESC, tie-break created_at ASC."""
    candidates = [
        c for c in certificates_of_server(server_id)
        if c["validity_state"] != "SUPERSEDED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))
    candidates.sort(key=lambda c: c["expires_at"], reverse=True)
    return candidates[0]


def certificate_renewal_selector(server_id, jurisdiction_id, track):
    candidates = [
        c for c in certificates_of_server(server_id)
        if c["state_jurisdiction_id"] == jurisdiction_id
        and c["track"] == track
        and c["validity_state"] in ("ACTIVE", "GRACE", "LAPSED", "SUSPENDED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))
    candidates.sort(key=lambda c: c["expires_at"], reverse=True)
    return candidates[0]


# --- stage one -------------------------------------------------------------

ELIGIBILITY_BY_VALIDITY = {
    "ACTIVE": "ELIGIBLE",
    "GRACE": "GRACE",
    "LAPSED": "RESTRICTED",
    "SUSPENDED": "RESTRICTED",
}


def stage_one(server):
    """Governing certificate and derived work eligibility."""
    governing = certificate_selector(server["id"])
    if governing is None:
        eligibility = "UNCERTIFIED"
        certificate_id = None
    else:
        eligibility = ELIGIBILITY_BY_VALIDITY[governing["validity_state"]]
        certificate_id = governing["id"]
    changes = {
        "active_certificate_id": certificate_id,
        "work_eligibility": eligibility,
        "certification_count": len(certificates_of_server(server["id"])),
    }
    if eligibility == "RESTRICTED" and server["work_eligibility"] != "RESTRICTED":
        changes["restricted_since"] = store.clock
    return apply_changes(server, changes)


# --- stage two -------------------------------------------------------------

def stage_two(server, counters=None, changed=None):
    """Work restrictions. Returns the set of touched location ids.

    When ``changed`` is a set, the ids of locations where an assignment
    actually transitioned are collected into it.
    """
    touched = set()
    eligibility = server["work_eligibility"]
    governing = st.get("certificates", server["active_certificate_id"]) \
        if server["active_certificate_id"] else None
    for assignment in live_assignments_of_server(server["id"]):
        location = st.get("employer_locations", assignment["employer_location_id"])
        if location is None:
            continue
        touched.add(location["id"])
        if location["training_requirement"] != "MANDATED":
            continue
        state = assignment["assignment_state"]
        if eligibility == "RESTRICTED":
            reason = "CERTIFICATE_LAPSED"
            if governing is not None and governing["validity_state"] == "SUSPENDED":
                reason = "REGISTRY_SUSPENDED"
            if state != "WORK_RESTRICTED":
                apply_changes(assignment, {
                    "assignment_state": "WORK_RESTRICTED",
                    "restriction_reason": reason,
                    "restricted_at": store.clock,
                })
                if counters is not None:
                    counters["assignments_restricted_count"] += 1
                if changed is not None:
                    changed.add(location["id"])
            else:
                apply_changes(assignment, {"restriction_reason": reason})
        elif eligibility == "UNCERTIFIED":
            jur = jurisdiction(location["state_jurisdiction_id"])
            deadline = add_days(assignment["assigned_at"], jur["new_hire_training_days"])
            if store.clock >= deadline and state != "WORK_RESTRICTED":
                apply_changes(assignment, {
                    "assignment_state": "WORK_RESTRICTED",
                    "restriction_reason": "NO_CERTIFICATE",
                    "restricted_at": store.clock,
                })
                if counters is not None:
                    counters["assignments_restricted_count"] += 1
                if changed is not None:
                    changed.add(location["id"])
        elif eligibility in ("ELIGIBLE", "GRACE") and state == "WORK_RESTRICTED":
            apply_changes(assignment, {
                "assignment_state": "ACTIVE",
                "restriction_reason": "NONE",
                "restricted_at": None,
            })
            if counters is not None:
                counters["assignments_restored_count"] += 1
            if changed is not None:
                changed.add(location["id"])
    return touched


# --- stage three -----------------------------------------------------------

def recompute_location(location):
    live = live_assignments_at_location(location["id"])
    assigned = len(live)
    compliant = 0
    grace = 0
    restricted = 0
    for assignment in live:
        server = st.get("alcohol_servers", assignment["alcohol_server_id"])
        eligibility = server["work_eligibility"] if server else "UNCERTIFIED"
        if eligibility == "ELIGIBLE":
            compliant += 1
        elif eligibility == "GRACE":
            grace += 1
        if assignment["assignment_state"] == "WORK_RESTRICTED":
            restricted += 1

    if assigned == 0:
        strict = LOCATION_EMPTY_RATE_PCT
        grace_inclusive = LOCATION_EMPTY_RATE_PCT
    else:
        strict = pct(compliant, assigned)
        grace_inclusive = pct(compliant + grace, assigned)

    requirement = training_requirement_for(location)
    if requirement == "VOLUNTARY":
        posture = "NOT_APPLICABLE"
    elif grace_inclusive >= COMPLIANT_MIN_PCT:
        posture = "COMPLIANT"
    elif grace_inclusive >= AT_RISK_MIN_PCT:
        posture = "AT_RISK"
    else:
        posture = "NON_COMPLIANT"

    return apply_changes(location, {
        "training_requirement": requirement,
        "assigned_server_count": assigned,
        "compliant_server_count": compliant,
        "grace_server_count": grace,
        "restricted_server_count": restricted,
        "compliance_rate_strict_pct": round_half_up(strict, 2),
        "compliance_rate_grace_inclusive_pct": round_half_up(grace_inclusive, 2),
        "compliance_posture": posture,
    })


def stage_three(location_ids):
    for location_id in sorted(location_ids):
        location = st.get("employer_locations", location_id)
        if location is not None:
            recompute_location(location)


# --- stage four ------------------------------------------------------------

def recompute_account(account):
    locations = locations_of_account(account["id"])
    total_live = sum(l["assigned_server_count"] for l in locations)
    compliant = sum(l["compliant_server_count"] for l in locations)
    if total_live == 0:
        rate = ACCOUNT_EMPTY_RATE_PCT
    else:
        rate = pct(compliant, total_live)
    changes = {
        "location_count": len(locations),
        "account_compliance_rate_pct": round_half_up(rate, 2),
    }
    if (account["dram_shop_discount_status"] == "NOT_DOCUMENTED"
            and rate >= DOCUMENTATION_FLOOR_PCT):
        changes["dram_shop_discount_status"] = "ELIGIBLE"
    return apply_changes(account, changes)


# --- stage five ------------------------------------------------------------

def documentation_floor(account, counters=None):
    if account["account_compliance_rate_pct"] >= DOCUMENTATION_FLOOR_PCT:
        return False
    voided = False
    for document in st.rows("dram_shop_documents"):
        if (document["employer_account_id"] == account["id"]
                and document["document_state"] == "ISSUED"):
            apply_changes(document, {
                "document_state": "VOIDED",
                "void_reason": "COMPLIANCE_RATE_FELL_BELOW_FLOOR",
            })
            voided = True
            if counters is not None:
                counters["documents_voided_count"] += 1
    if voided:
        apply_changes(account, {"dram_shop_discount_status": "EXPIRED"})
    return voided


def stage_four_five(account_ids, counters=None):
    for account_id in sorted(account_ids):
        account = st.get("employer_accounts", account_id)
        if account is None:
            continue
        recompute_account(account)
        documentation_floor(account, counters)


def accounts_of_locations(location_ids):
    accounts = set()
    for location_id in location_ids:
        location = st.get("employer_locations", location_id)
        if location is not None:
            accounts.add(location["employer_account_id"])
    return accounts


# --- the full chain --------------------------------------------------------

def recompute_chain(server, counters=None):
    """Stages one through five for one server."""
    stage_one(server)
    touched = stage_two(server, counters)
    stage_three(touched)
    stage_four_five(accounts_of_locations(touched), counters)
    return touched


def recompute_location_and_account(location, counters=None):
    """Stage three for one location, then stages four and five."""
    recompute_location(location)
    stage_four_five({location["employer_account_id"]}, counters)


# --- trainer teaching metrics ---------------------------------------------

def recompute_trainer_metrics(trainer):
    completed = [
        s for s in st.rows("class_sessions")
        if s["trainer_id"] == trainer["id"] and s["session_status"] == "COMPLETED"
    ]
    completed_ids = {s["id"] for s in completed}
    graded = [
        e for e in st.rows("enrollments")
        if e["class_session_id"] in completed_ids
        and e["enrollment_state"] in ("PASSED", "EXAM_FAILED")
    ]
    passed = [e for e in graded if e["enrollment_state"] == "PASSED"]
    if not graded:
        rate = Decimal("0.00")
    else:
        rate = pct(len(passed), len(graded))
    return apply_changes(trainer, {
        "sessions_taught_count": len(completed),
        "graded_enrollments_count": len(graded),
        "pass_rate_pct": round_half_up(rate, 2),
    })
