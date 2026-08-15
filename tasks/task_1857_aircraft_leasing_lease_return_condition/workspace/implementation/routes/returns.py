"""Return cases, inspection bookings, checklist items, negotiation, settlement."""
from flask import Blueprint, g

from db import CLOCK, STORE, base_entity, touch
from errors import (
    ERR_BOOKING_REQUIRED,
    ERR_CHECKLIST_INCOMPLETE,
    ERR_INSPECTOR_DOUBLE_BOOKED,
    ERR_PROPOSER_ALTERNATION,
    ERR_RECORDS_INCOMPLETE,
    ERR_REINSPECTION_LIMIT,
    ERR_STALE_VERSION,
    ApiError,
    bad_request,
    invalid_state,
    not_found,
)
from middleware import require_lease_ownership, require_roles
from response import paginated, success
from services.calculations import (
    MAX_REINSPECTIONS,
    provisional_estimate,
    records_completeness,
)
from services.cascades import auto_confirm_covering_slot, claims_of_lease, items_of_case
from validators import get_body, req_date, req_enum, req_int, req_str

bp = Blueprint("returns", __name__)

CASE_READ_ROLES = (
    "LessorAdmin",
    "CreditOfficer",
    "LegalApprover",
    "FinanceManager",
    "LesseeRep",
    "TechInspector",
)


def get_case_or_404(case_id):
    c = STORE["return_cases"].get(case_id)
    if c is None:
        raise not_found("Return case not found")
    return c


def lease_of_case(case):
    return STORE["leases"][case["lease_id"]]


# ---------------------------------------------------------------------------
# Return case reads
# ---------------------------------------------------------------------------
@bp.get("/leasing/leases/<lease_id>/return-cases")
@require_roles(
    "LessorAdmin", "CreditOfficer", "LegalApprover", "FinanceManager", "LesseeRep"
)
def list_return_cases(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    require_lease_ownership(lease)
    items = [c for c in STORE["return_cases"].values() if c["lease_id"] == lease["id"]]
    items.sort(key=lambda c: c["created_at"])
    return paginated(items)


@bp.get("/leasing/return-cases/<case_id>")
@require_roles(*CASE_READ_ROLES)
def get_return_case(case_id):
    case = get_case_or_404(case_id)
    require_lease_ownership(lease_of_case(case))
    return success(case)


# ---------------------------------------------------------------------------
# Workflow advance
# ---------------------------------------------------------------------------
@bp.post("/leasing/return-cases/<case_id>/advance")
@require_roles("LessorAdmin")
def advance_return_case(case_id):
    case = get_case_or_404(case_id)
    b = get_body()
    to = req_enum(b, "to", {"RECORDS_VERIFIED", "INSPECTION", "NEGOTIATION"})
    lease = lease_of_case(case)

    if to == "RECORDS_VERIFIED":
        if case["status"] != "OPEN":
            raise invalid_state("Only an OPEN return case can advance to RECORDS_VERIFIED")
        count, _ = records_completeness(lease["aircraft_id"])
        if count < 4:
            raise ApiError(
                ERR_RECORDS_INCOMPLETE,
                "All four required doc types must hold a VERIFIED document",
                409,
            )
        case["status"] = "RECORDS_VERIFIED"
    elif to == "INSPECTION":
        if case["status"] != "RECORDS_VERIFIED":
            raise invalid_state(
                "Only a RECORDS_VERIFIED return case can advance to INSPECTION"
            )
        case["status"] = "INSPECTION"
    else:  # NEGOTIATION
        if case["status"] != "INSPECTION":
            raise invalid_state("Only an INSPECTION return case can advance to NEGOTIATION")
        items = items_of_case(case["id"])
        if any(i["status"] in ("PENDING", "RECTIFIED") for i in items):
            raise ApiError(
                ERR_CHECKLIST_INCOMPLETE,
                "Checklist items remain PENDING or RECTIFIED",
                409,
            )
        case["provisional_estimate_cents"] = provisional_estimate(items)
        case["status"] = "NEGOTIATION"

    touch(case)
    return success(case)


# ---------------------------------------------------------------------------
# Inspection bookings
# ---------------------------------------------------------------------------
@bp.post("/leasing/return-cases/<case_id>/inspection-bookings")
@require_roles("LessorAdmin")
def create_booking(case_id):
    case = get_case_or_404(case_id)
    b = get_body()
    inspector_id = req_str(b, "inspector_id")
    if inspector_id not in STORE["inspectors"]:
        raise bad_request("inspector_id does not reference an existing inspector")
    booking_date = req_date(b, "booking_date")
    for bk in STORE["inspection_bookings"].values():
        if bk["inspector_id"] == inspector_id and bk["booking_date"] == booking_date:
            raise ApiError(
                ERR_INSPECTOR_DOUBLE_BOOKED,
                "Inspector already holds a booking on this calendar date",
                409,
            )
    bk = base_entity(with_version=False)
    bk.update(
        {
            "return_case_id": case["id"],
            "inspector_id": inspector_id,
            "booking_date": booking_date,
        }
    )
    STORE["inspection_bookings"][bk["id"]] = bk
    return success(bk, status=201)


@bp.get("/leasing/return-cases/<case_id>/inspection-bookings")
@require_roles(*CASE_READ_ROLES)
def list_case_bookings(case_id):
    case = get_case_or_404(case_id)
    require_lease_ownership(lease_of_case(case))
    items = [
        bk
        for bk in STORE["inspection_bookings"].values()
        if bk["return_case_id"] == case["id"]
    ]
    items.sort(key=lambda bk: (bk["booking_date"], bk["created_at"]))
    return paginated(items)


# ---------------------------------------------------------------------------
# Checklist items
# ---------------------------------------------------------------------------
@bp.get("/leasing/return-cases/<case_id>/checklist-items")
@require_roles(*CASE_READ_ROLES)
def list_checklist_items(case_id):
    case = get_case_or_404(case_id)
    require_lease_ownership(lease_of_case(case))
    items = items_of_case(case["id"])
    items.sort(key=lambda i: i["item_code"])
    return paginated(items)


def get_item_or_404(item_id):
    i = STORE["checklist_items"].get(item_id)
    if i is None:
        raise not_found("Checklist item not found")
    return i


@bp.post("/leasing/checklist-items/<item_id>/inspect")
@require_roles("TechInspector")
def inspect_item(item_id):
    item = get_item_or_404(item_id)
    b = get_body()
    outcome = req_enum(b, "outcome", {"COMPLIANT", "NON_COMPLIANT"})
    estimate = None
    if outcome == "NON_COMPLIANT":
        estimate = req_int(b, "rectification_cost_estimate_cents", min_v=1)

    case = STORE["return_cases"][item["return_case_id"]]
    if case["status"] != "INSPECTION":
        raise invalid_state("The parent return case is not in INSPECTION")
    if item["status"] not in ("PENDING", "RECTIFIED"):
        raise invalid_state("Only a PENDING or RECTIFIED item can be inspected")

    today = CLOCK.date_str()
    booked = any(
        bk["return_case_id"] == item["return_case_id"]
        and bk["inspector_id"] == g.user_id
        and bk["booking_date"] == today
        for bk in STORE["inspection_bookings"].values()
    )
    if not booked:
        raise ApiError(
            ERR_BOOKING_REQUIRED,
            "Inspecting TechInspector holds no booking for this return case on the current date",
            403,
        )

    if outcome == "COMPLIANT":
        item["status"] = "COMPLIANT"
    else:
        item["status"] = "NON_COMPLIANT"
        item["rectification_cost_estimate_cents"] = estimate
    item["inspected_by_id"] = g.user_id
    touch(item)
    return success(item)


@bp.post("/leasing/checklist-items/<item_id>/waive")
@require_roles("LessorAdmin")
def waive_item(item_id):
    item = get_item_or_404(item_id)
    get_body()  # optional reason; no persisted field for it
    if item["status"] != "NON_COMPLIANT":
        raise invalid_state("Only a NON_COMPLIANT item can be waived")
    item["status"] = "WAIVED"
    touch(item)
    return success(item)


@bp.post("/leasing/checklist-items/<item_id>/rectify")
@require_roles("LesseeRep")
def rectify_item(item_id):
    item = get_item_or_404(item_id)
    case = STORE["return_cases"][item["return_case_id"]]
    require_lease_ownership(lease_of_case(case))
    if item["status"] != "NON_COMPLIANT":
        raise invalid_state("Only a NON_COMPLIANT item can be marked rectified")
    item["status"] = "RECTIFIED"
    touch(item)
    return success(item)


# ---------------------------------------------------------------------------
# Negotiation: proposals, agree, re-inspection
# ---------------------------------------------------------------------------
def _actor_side():
    return "LESSOR" if g.role == "LessorAdmin" else "LESSEE"


@bp.post("/leasing/return-cases/<case_id>/proposals")
@require_roles("LessorAdmin", "LesseeRep")
def propose(case_id):
    case = get_case_or_404(case_id)
    require_lease_ownership(lease_of_case(case))
    b = get_body()
    amount_cents = req_int(b, "amount_cents", min_v=0)
    if case["status"] != "NEGOTIATION":
        raise invalid_state("Proposals may be tabled only while the case is in NEGOTIATION")
    side = _actor_side()
    if case["round_count"] == 0:
        if side != "LESSOR":
            raise ApiError(
                ERR_PROPOSER_ALTERNATION,
                "The first proposal must come from the LESSOR side",
                409,
            )
    elif case["current_proposer_side"] == side:
        raise ApiError(
            ERR_PROPOSER_ALTERNATION,
            "The proposing side must differ from the side that made the standing proposal",
            409,
        )
    case["round_count"] += 1
    case["current_proposal_cents"] = amount_cents
    case["current_proposer_side"] = side
    touch(case)
    return success(case)


@bp.post("/leasing/return-cases/<case_id>/agree")
@require_roles("LessorAdmin", "LesseeRep")
def agree(case_id):
    case = get_case_or_404(case_id)
    require_lease_ownership(lease_of_case(case))
    b = get_body()
    expected = b.get("expected_return_case_version")
    if expected is None:
        raise bad_request("Missing required field: expected_return_case_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_return_case_version must be an integer")
    if case["status"] != "NEGOTIATION":
        raise invalid_state("Agreement may be recorded only while the case is in NEGOTIATION")
    side = _actor_side()
    if case["round_count"] < 1:
        raise ApiError(
            ERR_PROPOSER_ALTERNATION,
            "No standing proposal exists to agree to",
            409,
        )
    if case["current_proposer_side"] == side:
        raise ApiError(
            ERR_PROPOSER_ALTERNATION,
            "The agreeing side must differ from the side that made the standing proposal",
            409,
        )
    if expected != case["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_return_case_version does not match the return case's current version",
            412,
        )
    case["agreed_total_cents"] = case["current_proposal_cents"]
    case["status"] = "AGREED"
    touch(case)
    return success(case)


@bp.post("/leasing/return-cases/<case_id>/request-reinspection")
@require_roles("LesseeRep")
def request_reinspection(case_id):
    case = get_case_or_404(case_id)
    require_lease_ownership(lease_of_case(case))
    if case["status"] != "NEGOTIATION":
        raise invalid_state("Re-inspection may be requested only from NEGOTIATION")
    if case["reinspection_count"] >= MAX_REINSPECTIONS:
        raise ApiError(
            ERR_REINSPECTION_LIMIT,
            "The re-inspection hard cap (1) has been reached",
            409,
        )
    case["reinspection_count"] += 1
    for item in items_of_case(case["id"]):
        if item["status"] == "NON_COMPLIANT":
            item["status"] = "PENDING"
            touch(item)
    case["status"] = "INSPECTION"
    touch(case)
    return success(case)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
@bp.post("/leasing/return-cases/<case_id>/settle")
@require_roles("FinanceManager")
def settle(case_id):
    case = get_case_or_404(case_id)
    if case["status"] != "AGREED":
        raise invalid_state("Only an AGREED return case can be settled")
    lease = lease_of_case(case)

    # settlement_netting — pinned evaluation order:
    # 1. balance; 2. reserve_applied = min(balance, agreed); 3. cash due;
    # 4. forfeited = balance - applied; 5. forfeited accrued, balance zeroed
    #    (explicit zero assignment per the normative pinned order — NOT a
    #    recompute; the applied portion leaves the ledger via settlement).
    balance = lease["reserve_balance_cents"]
    reserve_applied = min(balance, case["agreed_total_cents"])
    cash_due = case["agreed_total_cents"] - reserve_applied
    forfeited = balance - reserve_applied
    lease["reserve_forfeited_cents"] += forfeited
    lease["reserve_balance_cents"] = 0
    case["reserve_applied_cents"] = reserve_applied
    case["settlement_cash_due_cents"] = cash_due

    # Conditional cascades: NON_COMPLIANT items -> COMPENSATED; open claims -> REJECTED.
    for item in items_of_case(case["id"]):
        if item["status"] == "NON_COMPLIANT":
            item["status"] = "COMPENSATED"
            touch(item)
    for claim in claims_of_lease(lease["id"]):
        if claim["status"] in ("SUBMITTED", "APPROVED"):
            claim["status"] = "REJECTED"
            touch(claim)

    # Handback cascade: lease RETURN_INITIATED -> RETURNED, then aircraft
    # ON_LEASE -> IN_TRANSITION, then slot auto-confirm.
    if lease["status"] == "RETURN_INITIATED":
        lease["status"] = "RETURNED"
        touch(lease)
        aircraft = STORE["aircraft"].get(lease["aircraft_id"])
        if aircraft is not None and aircraft["status"] == "ON_LEASE":
            aircraft["status"] = "IN_TRANSITION"
            touch(aircraft)
            auto_confirm_covering_slot(aircraft["id"], CLOCK.date_str())

    case["status"] = "SETTLED"
    touch(case)
    return success(case)
