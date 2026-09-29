"""Inductions, travel funding, artifact intake and exhibit installations
(PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import db
import derive
import lookup
import payload
import response
import serialize
from auth import ROLE_ADMIN, ROLE_AUDITOR, ROLE_CURATOR
from errors import fail

bp = Blueprint("ceremony", __name__)

VARIANT_FOR_DELEGATION = {
    "LIVING": "LIVING_INDUCTEE",
    "POSTHUMOUS_DELEGATION": "POSTHUMOUS_DELEGATION",
}


def _settle_induction(induction, cycle):
    """Re-derive readiness on the induction and the cycle's ready count."""
    derive.refresh_induction_readiness(induction)
    db.touch(induction)
    if cycle is not None and derive.refresh_cycle_ready_count(cycle):
        db.touch(cycle)


# ------------------------------------------------------------------ inductions


@bp.route("/inductions", methods=["GET"])
def list_inductions():
    auth.caller(*auth.ALL_ROLES)
    return lookup.listing(
        db.inductions,
        [
            ("cycle_id", "cycle_id", "str"),
            ("candidacy_id", "candidacy_id", "str"),
            ("candidate_id", "candidate_id", "str"),
            ("status", "status", "str"),
            ("travel_status", "travel_status", "str"),
            ("artifact_status", "artifact_status", "str"),
            ("exhibit_status", "exhibit_status", "str"),
        ],
        serialize.induction,
    )


@bp.route("/inductions/<row_id>", methods=["GET"])
def read_induction(row_id):
    auth.caller(*auth.ALL_ROLES)
    return response.ok(serialize.induction(lookup.induction(row_id)))


@bp.route("/inductions/<row_id>/artifact-intake", methods=["POST"])
def artifact_intake(row_id):
    """AWAITED -> RECEIVED, or AWAITED -> EXEMPT."""
    auth.caller(ROLE_CURATOR)
    data = payload.body()
    artifact_count = payload.opt_int(data, "artifact_count", default=None)
    is_exempt = payload.opt_bool(data, "is_exempt", default=False)
    if not ((artifact_count is not None and artifact_count >= 1) or is_exempt is True):
        fail(
            "ERR_INVALID_REQUEST",
            "Supply an 'artifact_count' of at least 1 or set 'is_exempt' to true.",
        )

    induction = lookup.induction(row_id)
    if induction["status"] != "ANNOUNCED":
        fail("ERR_INVALID_INDUCTION_STATE", "An enshrined induction accepts no mutation.")
    if induction["artifact_status"] != "AWAITED":
        fail("ERR_INVALID_INDUCTION_STATE", "Artifact intake requires the AWAITED state.")

    if is_exempt:
        induction["artifact_status"] = "EXEMPT"
    else:
        induction["artifact_status"] = "RECEIVED"
        induction["artifact_count"] = artifact_count

    _settle_induction(induction, db.cycles.get(induction["cycle_id"]))
    return response.ok(serialize.induction(induction))


# --------------------------------------------------------------- travel grants


@bp.route("/travel-grants", methods=["POST"])
def create_grant():
    auth.caller(ROLE_ADMIN, ROLE_CURATOR)
    data = payload.body()
    induction_id = payload.req_id(data, "induction_id")
    nights = payload.req_int(data, "nights", minimum=1)
    requested_airfare_cents = payload.req_int(data, "requested_airfare_cents", minimum=0)
    expected_cycle_version = payload.req_int(data, "expected_cycle_version")
    escort_from = payload.opt_ts(data, "escort_from", default=None)
    escort_to = payload.opt_ts(data, "escort_to", default=None)
    declared_cycle_id = payload.opt_id(data, "cycle_id", default=None)

    if declared_cycle_id is not None:
        lookup.cycle(declared_cycle_id)
    induction = lookup.induction(induction_id)
    cycle = lookup.cycle(induction["cycle_id"])

    if cycle["status"] != "CEREMONY_PLANNED":
        fail("ERR_CEREMONY_NOT_PLANNED", "The funding cycle is not in CEREMONY_PLANNED.")
    if induction["status"] != "ANNOUNCED":
        fail("ERR_INVALID_INDUCTION_STATE", "An enshrined induction accepts no mutation.")
    if induction["travel_status"] != "PENDING":
        fail("ERR_INVALID_INDUCTION_STATE", "A travel request requires the PENDING state.")

    if expected_cycle_version != cycle["version"]:
        fail("ERR_STALE_CYCLE_VERSION", "The cycle has advanced since it was read.")

    if declared_cycle_id is not None and declared_cycle_id != induction["cycle_id"]:
        fail("ERR_INDUCTION_CYCLE_MISMATCH", "The declared cycle is not the induction's cycle.")

    variant = VARIANT_FOR_DELEGATION.get(induction["delegation_type"], "LIVING_INDUCTEE")
    if variant == "POSTHUMOUS_DELEGATION":
        if escort_from is None or escort_to is None or escort_from > escort_to:
            fail(
                "ERR_INVALID_ESCORT_INTERVAL",
                "A posthumous delegation requires a well-formed escort interval.",
            )
    elif escort_from is not None and escort_to is not None and escort_from > escort_to:
        fail("ERR_INVALID_ESCORT_INTERVAL", "The escort interval is inverted.")

    tier = derive.austerity_tier_for(cycle["travel_committed_cents"], cycle["travel_budget_cents"])
    award_cents, traveler_count = calc.travel_award(
        tier, induction["delegation_type"], nights, requested_airfare_cents
    )

    remaining = cycle["travel_budget_cents"] - cycle["travel_committed_cents"]
    if award_cents > remaining:
        fail("ERR_TRAVEL_BUDGET_EXCEEDED", "The award does not fit the remaining travel budget.")

    row = db.stamp(
        {
            "cycle_id": cycle["id"],
            "induction_id": induction["id"],
            "nights": nights,
            "requested_airfare_cents": requested_airfare_cents,
            "escort_from": escort_from,
            "escort_to": escort_to,
            "variant": variant,
            "traveler_count": traveler_count,
            "austerity_tier_applied": tier,
            "award_cents": award_cents,
            "status": "REQUESTED",
            "cycle_version_after": cycle["version"],
            "cancellation_reason": None,
        }
    )
    db.travel_grants[row["id"]] = row

    induction["travel_status"] = "REQUESTED"
    derive.refresh_induction_readiness(induction)
    db.touch(induction)

    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    row["cycle_version_after"] = cycle["version"]

    return response.created(serialize.travel_grant(row))


@bp.route("/travel-grants", methods=["GET"])
def list_grants():
    auth.caller(ROLE_ADMIN, ROLE_AUDITOR, ROLE_CURATOR)
    return lookup.listing(
        db.travel_grants,
        [
            ("cycle_id", "cycle_id", "str"),
            ("induction_id", "induction_id", "str"),
            ("status", "status", "str"),
            ("variant", "variant", "str"),
        ],
        serialize.travel_grant,
    )


@bp.route("/travel-grants/<row_id>", methods=["GET"])
def read_grant(row_id):
    auth.caller(ROLE_ADMIN, ROLE_AUDITOR, ROLE_CURATOR)
    return response.ok(serialize.travel_grant(lookup.travel_grant(row_id)))


@bp.route("/travel-grants/<row_id>/approve", methods=["POST"])
def approve_grant(row_id):
    """Commit the frozen award against the budget and the escort pool."""
    auth.caller(ROLE_ADMIN)
    grant = lookup.travel_grant(row_id)
    cycle = lookup.cycle(grant["cycle_id"])
    induction = lookup.induction(grant["induction_id"])

    if cycle["status"] != "CEREMONY_PLANNED":
        fail("ERR_CEREMONY_NOT_PLANNED", "The funding cycle is not in CEREMONY_PLANNED.")
    if grant["status"] != "REQUESTED":
        fail("ERR_INVALID_GRANT_STATE", "Only a REQUESTED grant may be approved.")
    if induction["status"] != "ANNOUNCED" or induction["travel_status"] != "REQUESTED":
        fail("ERR_INVALID_INDUCTION_STATE", "The induction's travel dimension is not REQUESTED.")

    calc.escort_pool_check(cycle, grant)

    remaining = cycle["travel_budget_cents"] - cycle["travel_committed_cents"]
    if grant["award_cents"] > remaining:
        fail("ERR_TRAVEL_BUDGET_EXCEEDED", "The award does not fit the remaining travel budget.")

    grant["status"] = "APPROVED"
    induction["travel_status"] = "APPROVED"
    derive.refresh_induction_readiness(induction)
    db.touch(induction)

    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    grant["cycle_version_after"] = cycle["version"]
    db.touch(grant)
    return response.ok(serialize.travel_grant(grant))


@bp.route("/travel-grants/<row_id>/deny", methods=["POST"])
def deny_grant(row_id):
    """REQUESTED -> DENIED; the inductee travels unfunded and stops blocking."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    reason = payload.req_str(data, "cancellation_reason", allow_empty=False)

    grant = lookup.travel_grant(row_id)
    cycle = lookup.cycle(grant["cycle_id"])
    induction = lookup.induction(grant["induction_id"])

    if cycle["status"] != "CEREMONY_PLANNED":
        fail("ERR_CEREMONY_NOT_PLANNED", "The funding cycle is not in CEREMONY_PLANNED.")
    if grant["status"] != "REQUESTED":
        fail("ERR_INVALID_GRANT_STATE", "Only a REQUESTED grant may be denied.")
    if induction["status"] != "ANNOUNCED" or induction["travel_status"] != "REQUESTED":
        fail("ERR_INVALID_INDUCTION_STATE", "The induction's travel dimension is not REQUESTED.")

    grant["status"] = "DENIED"
    grant["cancellation_reason"] = reason
    induction["travel_status"] = "WAIVED"
    derive.refresh_induction_readiness(induction)
    db.touch(induction)

    if derive.recompute_cycle(cycle, bump=False):
        db.touch(cycle)
    grant["cycle_version_after"] = cycle["version"]
    db.touch(grant)
    return response.ok(serialize.travel_grant(grant))


@bp.route("/travel-grants/<row_id>/cancel", methods=["POST"])
def cancel_grant(row_id):
    """APPROVED -> CANCELLED: a true compensating reversal."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    reason = payload.req_str(data, "cancellation_reason", allow_empty=False)

    grant = lookup.travel_grant(row_id)
    cycle = lookup.cycle(grant["cycle_id"])
    induction = lookup.induction(grant["induction_id"])

    if cycle["status"] != "CEREMONY_PLANNED":
        fail("ERR_CEREMONY_NOT_PLANNED", "The funding cycle is not in CEREMONY_PLANNED.")
    if grant["status"] != "APPROVED":
        fail("ERR_INVALID_GRANT_STATE", "Only an APPROVED grant may be cancelled.")
    if induction["status"] != "ANNOUNCED" or induction["travel_status"] != "APPROVED":
        fail("ERR_INVALID_INDUCTION_STATE", "The induction's travel dimension is not APPROVED.")

    grant["status"] = "CANCELLED"
    grant["cancellation_reason"] = reason
    induction["travel_status"] = "PENDING"
    derive.refresh_induction_readiness(induction)
    db.touch(induction)

    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    grant["cycle_version_after"] = cycle["version"]
    db.touch(grant)
    return response.ok(serialize.travel_grant(grant))


# --------------------------------------------------------- exhibit installations


def _recompute_case(case):
    total = 0
    for row in db.exhibit_installations.values():
        if row["exhibit_case_id"] == case["id"] and row["status"] == "INSTALLED":
            total += row["artifact_count"]
    if case["artifacts_installed"] != total:
        case["artifacts_installed"] = total
        db.touch(case)


@bp.route("/exhibit-installations", methods=["POST"])
def create_installation():
    auth.caller(ROLE_CURATOR)
    data = payload.body()
    induction_id = payload.req_id(data, "induction_id")
    exhibit_case_id = payload.req_id(data, "exhibit_case_id")
    display_starts_on = payload.req_ts(data, "display_starts_on")
    display_ends_on = payload.req_ts(data, "display_ends_on")
    artifact_count = payload.req_int(data, "artifact_count", minimum=1)

    induction = lookup.induction(induction_id)
    case = lookup.exhibit_case(exhibit_case_id)

    if induction["status"] != "ANNOUNCED":
        fail("ERR_INVALID_INDUCTION_STATE", "An enshrined induction accepts no mutation.")

    if display_starts_on >= display_ends_on:
        fail(
            "ERR_INVALID_TIME_WINDOW",
            "'display_starts_on' must be strictly before 'display_ends_on'.",
        )
    if induction["artifact_status"] != "RECEIVED":
        fail("ERR_ARTIFACTS_NOT_RECEIVED", "The induction's artifacts are not in hand.")

    calc.exhibit_window_check(case, induction["id"], display_starts_on, display_ends_on)

    if case["artifacts_installed"] + artifact_count > case["capacity_artifacts"]:
        fail("ERR_CASE_CAPACITY_EXCEEDED", "The case cannot hold that many more artifacts.")

    row = db.stamp(
        {
            "induction_id": induction["id"],
            "exhibit_case_id": case["id"],
            "display_starts_on": display_starts_on,
            "display_ends_on": display_ends_on,
            "artifact_count": artifact_count,
            "status": "INSTALLED",
        }
    )
    db.exhibit_installations[row["id"]] = row

    _recompute_case(case)
    if induction["exhibit_status"] != "INSTALLED":
        induction["exhibit_status"] = "INSTALLED"
    _settle_induction(induction, db.cycles.get(induction["cycle_id"]))
    return response.created(serialize.exhibit_installation(row))


@bp.route("/exhibit-installations", methods=["GET"])
def list_installations():
    auth.caller(ROLE_ADMIN, ROLE_CURATOR, ROLE_AUDITOR)
    return lookup.listing(
        db.exhibit_installations,
        [
            ("induction_id", "induction_id", "str"),
            ("exhibit_case_id", "exhibit_case_id", "str"),
            ("status", "status", "str"),
        ],
        serialize.exhibit_installation,
    )


@bp.route("/exhibit-installations/<row_id>", methods=["GET"])
def read_installation(row_id):
    auth.caller(ROLE_ADMIN, ROLE_CURATOR, ROLE_AUDITOR)
    return response.ok(serialize.exhibit_installation(lookup.exhibit_installation(row_id)))


@bp.route("/exhibit-installations/<row_id>/withdraw", methods=["POST"])
def withdraw_installation(row_id):
    """INSTALLED -> WITHDRAWN, releasing both the window and the occupancy."""
    auth.caller(ROLE_CURATOR)
    row = lookup.exhibit_installation(row_id)
    induction = lookup.induction(row["induction_id"])
    case = lookup.exhibit_case(row["exhibit_case_id"])

    if induction["status"] != "ANNOUNCED":
        fail("ERR_INVALID_INDUCTION_STATE", "An enshrined induction accepts no mutation.")
    if row["status"] != "INSTALLED":
        fail("ERR_INVALID_INDUCTION_STATE", "Only an INSTALLED installation may be withdrawn.")

    row["status"] = "WITHDRAWN"
    db.touch(row)
    _recompute_case(case)

    survivors = [
        other
        for other in db.exhibit_installations.values()
        if other["induction_id"] == induction["id"] and other["status"] == "INSTALLED"
    ]
    if not survivors:
        induction["exhibit_status"] = "NOT_PLANNED"
        _settle_induction(induction, db.cycles.get(induction["cycle_id"]))
    return response.ok(serialize.exhibit_installation(row))
