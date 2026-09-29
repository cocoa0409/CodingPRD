"""Advisor onboarding, agreement terms, lifecycle and departure (PRD 3.2, 3.9)."""

from flask import Blueprint

import calc
from envelope import created, ok
from errors import ApiError
from guards import (authenticate, field_dt, field_number, field_state_code,
                    field_str, field_int, read_body)
from listing import list_response
from lookup import get_advisor, get_consortium, get_schedule
from store import new_row, ordered, serialize, store, touch

bp = Blueprint("advisor", __name__)

ALL_ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor",
             "SupplierPortal")
OPERATOR_ROLES = ("HostOperations", "HostController", "ComplianceOfficer")
AGREEMENT_READ_ROLES = ("HostOperations", "HostController", "ComplianceOfficer",
                        "Advisor")


# --------------------------------------------------------------------------
# onboarding
# --------------------------------------------------------------------------

@bp.post("/advisors")
def create_advisor():
    authenticate(("HostOperations",))
    body = read_body(("legal_name", "email", "seller_of_travel_state",
                      "consortium_id"))
    legal_name = field_str(body, "legal_name", max_len=200)
    email = field_str(body, "email", max_len=320)
    state_code = field_state_code(body, "seller_of_travel_state")
    consortium_id = field_str(body, "consortium_id", required=False)

    if consortium_id is not None:
        get_consortium(consortium_id)

    for existing in store.advisors.values():
        if existing["email"] == email:
            raise ApiError("ERR_ADVISOR_EMAIL_DUPLICATE")

    row = new_row({
        "legal_name": legal_name,
        "email": email,
        "seller_of_travel_state": state_code,
        "consortium_id": consortium_id,
        "status": "DRAFT",
        "trust_account_required": False,
        "production_ytd_provisional_cents": 0,
        "production_ytd_final_cents": 0,
        "split_tier_provisional": 1,
        "split_tier_final": 1,
        "eo_coverage_verified_cents": 0,
        "lifetime_settled_share_cents": 0,
        "lifetime_chargeback_cents": 0,
        "carryforward_chargeback_cents": 0,
        "activated_by_user_id": None,
        "departure_effective_date": None,
        "transition_advisor_id": None,
    })
    calc.derive_trust_requirement(row)
    store.advisors[row["id"]] = row
    return created(serialize(row))


@bp.get("/advisors/<advisor_id>")
def read_advisor(advisor_id):
    authenticate(ALL_ROLES)
    return ok(serialize(get_advisor(advisor_id)))


@bp.get("/advisors")
def list_advisors():
    authenticate(OPERATOR_ROLES)
    return list_response(store.advisors.values(),
                         (("consortium_id", "consortium_id"),
                          ("transition_advisor_id", "transition_advisor_id"),
                          ("status", "status"),
                          ("seller_of_travel_state", "seller_of_travel_state")))


# --------------------------------------------------------------------------
# agreements
# --------------------------------------------------------------------------

@bp.post("/advisors/<advisor_id>/agreements")
def create_agreement(advisor_id):
    authenticate(("HostOperations",))
    body = read_body(("split_schedule_id", "effective_date",
                      "post_departure_advisor_pct", "expected_advisor_version"))
    schedule_id = field_str(body, "split_schedule_id")
    effective_date = field_dt(body, "effective_date")
    post_pct = field_number(body, "post_departure_advisor_pct", minimum=0,
                            maximum=1)
    expected_version = field_int(body, "expected_advisor_version")

    advisor = get_advisor(advisor_id)
    get_schedule(schedule_id)

    if expected_version != advisor["version"]:
        raise ApiError("ERR_ADVISOR_VERSION_STALE")

    prior = calc.active_agreement(advisor["id"])

    row = new_row({
        "advisor_id": advisor["id"],
        "split_schedule_id": schedule_id,
        "effective_date": effective_date,
        "signed_at": store.clock,
        "post_departure_advisor_pct": post_pct,
        "status": "ACTIVE",
    })
    store.agreements[row["id"]] = row

    # The supersession transition is declared only where the new terms start at
    # or after the terms they replace (PRD 3.2).
    if prior is not None and row["effective_date"] >= prior["effective_date"]:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    touch(advisor)
    return created(serialize(row))


@bp.get("/advisor-agreements/<agreement_id>")
def read_agreement(agreement_id):
    authenticate(AGREEMENT_READ_ROLES)
    from lookup import get_agreement
    return ok(serialize(get_agreement(agreement_id)))


@bp.get("/advisor-agreements")
def list_agreements():
    authenticate(AGREEMENT_READ_ROLES)
    return list_response(store.agreements.values(),
                         (("advisor_id", "advisor_id"),
                          ("split_schedule_id", "split_schedule_id"),
                          ("status", "status")))


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------

@bp.post("/advisors/<advisor_id>/activate")
def activate_advisor(advisor_id):
    caller = authenticate(("HostOperations",))
    read_body((), required_body=False)
    advisor = get_advisor(advisor_id)

    if advisor["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ADVISOR_STATE")
    if len(calc.active_agreements(advisor["id"])) != 1:
        raise ApiError("ERR_ACTIVE_AGREEMENT_MISSING")
    if not calc.has_seller_of_travel(advisor, store.clock):
        raise ApiError("ERR_SELLER_OF_TRAVEL_INVALID")
    if not calc.has_eo_coverage(advisor, store.clock):
        raise ApiError("ERR_EO_COVERAGE_INSUFFICIENT")
    if not calc.has_training_cert(advisor, store.clock):
        raise ApiError("ERR_TRAINING_CERT_MISSING")

    advisor["status"] = "ACTIVE"
    advisor["activated_by_user_id"] = caller.user_id
    calc.derive_trust_requirement(advisor)
    calc.recompute_eo_coverage(advisor)

    schedule = calc.schedule_of(calc.active_agreement(advisor["id"]))
    seed = calc.select_tier(schedule["tiers"], 0) if schedule else None
    if seed is None:
        raise ApiError("ERR_SPLIT_TIER_UNRESOLVED")
    advisor["split_tier_provisional"] = seed["tier_level"]
    advisor["split_tier_final"] = seed["tier_level"]

    touch(advisor)
    return ok(serialize(advisor))


@bp.post("/advisors/<advisor_id>/suspend")
def suspend_advisor(advisor_id):
    authenticate(("ComplianceOfficer",))
    body = read_body(("reason",))
    field_str(body, "reason")
    advisor = get_advisor(advisor_id)

    if advisor["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ADVISOR_STATE")

    advisor["status"] = "SUSPENDED"
    touch(advisor)
    return ok(serialize(advisor))


@bp.post("/advisors/<advisor_id>/reinstate")
def reinstate_advisor(advisor_id):
    authenticate(("ComplianceOfficer",))
    read_body((), required_body=False)
    advisor = get_advisor(advisor_id)

    if advisor["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_ADVISOR_STATE")
    if not calc.has_seller_of_travel(advisor, store.clock):
        raise ApiError("ERR_SELLER_OF_TRAVEL_INVALID")
    if not calc.has_eo_coverage(advisor, store.clock):
        raise ApiError("ERR_EO_COVERAGE_INSUFFICIENT")

    advisor["status"] = "ACTIVE"
    calc.recompute_eo_coverage(advisor)
    calc.recompute_provisional(advisor)
    touch(advisor)
    return ok(serialize(advisor))


# --------------------------------------------------------------------------
# departure (PRD 3.9)
# --------------------------------------------------------------------------

@bp.post("/advisors/<advisor_id>/departure")
def declare_departure(advisor_id):
    caller = authenticate(("Advisor", "HostOperations"))
    body = read_body(("effective_date", "transition_advisor_id"))
    effective_date = field_dt(body, "effective_date")
    successor_id = field_str(body, "transition_advisor_id")

    advisor = get_advisor(advisor_id)
    if caller.is_advisor and advisor["id"] != caller.user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    successor = get_advisor(successor_id)

    if advisor["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_ADVISOR_STATE")
    if successor["id"] == advisor["id"] or successor["status"] != "ACTIVE":
        raise ApiError("ERR_TRANSITION_ADVISOR_INVALID")

    advisor["status"] = "DEPARTING"
    advisor["departure_effective_date"] = effective_date
    advisor["transition_advisor_id"] = successor["id"]
    touch(advisor)
    return ok(serialize(advisor))


@bp.post("/advisors/<advisor_id>/departure/finalize")
def finalize_departure(advisor_id):
    authenticate(("ComplianceOfficer",))
    read_body((), required_body=False)
    advisor = get_advisor(advisor_id)

    if advisor["status"] != "DEPARTING":
        raise ApiError("ERR_INVALID_ADVISOR_STATE")

    # Wind-down gates: open claims, unrefunded trust money, ineligible successor.
    for claim in store.claims.values():
        if claim["advisor_id"] == advisor["id"] and claim["status"] in ("SUBMITTED", "DENIED"):
            raise ApiError("ERR_DEPARTURE_BLOCKED",
                           "A commission claim of this advisor is still open.")

    owned_clients = [c for c in ordered(store.clients.values())
                     if c["owner_advisor_id"] == advisor["id"]]
    for client in owned_clients:
        calc.recompute_client_balance(client)
        if client["trust_balance_cents"] != 0:
            raise ApiError("ERR_DEPARTURE_BLOCKED",
                           "A client of this advisor still holds trust funds.")

    successor = store.advisors.get(advisor["transition_advisor_id"])
    if (successor is None or successor["status"] != "ACTIVE"
            or len(calc.active_agreements(successor["id"])) != 1):
        raise ApiError("ERR_DEPARTURE_BLOCKED",
                       "The recorded successor advisor is no longer eligible.")

    successor_agreement = calc.active_agreement(successor["id"])

    # LEVEL 1 — the advisor departs and its live terms terminate.
    advisor["status"] = "DEPARTED"
    touch(advisor)
    for agreement in calc.advisor_agreements(advisor["id"]):
        if agreement["status"] == "ACTIVE":
            agreement["status"] = "TERMINATED"
            touch(agreement)

    # LEVEL 2 — caused by level 1: the book of business is re-homed or released.
    rehomed = []
    for client in owned_clients:
        if client["ownership_mode"] == "HOST_OWNED":
            client["owner_advisor_id"] = successor["id"]
            rehomed.append(client)
        else:
            client["portability_status"] = "RELEASED"
        touch(client)

    # LEVEL 3 — caused by level 2: in-flight work follows the client.
    moved = False
    for client in rehomed:
        for booking in ordered(store.bookings.values()):
            if booking["client_id"] != client["id"]:
                continue
            if booking["booking_status"] not in ("SUBMITTED", "CONFIRMED"):
                continue
            booking["advisor_id"] = successor["id"]
            booking["agreement_id"] = successor_agreement["id"]
            if booking["commission_status"] == "PENDING":
                supplier = store.suppliers.get(booking["supplier_id"])
                if supplier is not None:
                    calc.price_booking(booking, successor, supplier)
            touch(booking)
            moved = True

    # LEVEL 4 — caused by level 3: both advisors' provisional standing moves.
    if moved:
        calc.recompute_provisional(advisor)
        calc.recompute_provisional(successor)
        touch(successor)

    return ok(serialize(advisor))
