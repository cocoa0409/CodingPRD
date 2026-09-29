"""Cost certification, final credit allocation and credit delivery (PRD 3.8)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_delivery, own_project
from envelope import object_response
from errors import fail
from store import db, new_row, now_clock_iso, touch

bp = Blueprint("certs_credit", __name__)

PLACED_STATUSES = ("PLACED_IN_SERVICE", "STABILIZED")


# --------------------------------------------------------------------------
# cost certification
# --------------------------------------------------------------------------

@bp.post("/cost-certifications")
def create_cost_cert():
    caller = guard("POST /cost-certifications")
    body = v.body()
    own_project(caller, domain.soft_get(db.projects, body.get("project_id")))

    project_id = v.req_id(body, "project_id")
    land = v.req_int(body, "certified_land_cost_cents", minimum=0)
    depreciable = v.req_int(body, "certified_depreciable_basis_cents", minimum=1)
    eligible = v.req_int(body, "certified_eligible_basis_cents", minimum=1)
    v.req_str(body, "preparer_name", allow_empty=False)
    if eligible > depreciable:
        fail("ERR_INVALID_REQUEST",
             "certified_eligible_basis_cents may not exceed "
             "certified_depreciable_basis_cents.")

    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(caller, project)

    row = new_row(db.cost_certs, {
        "project_id": project_id,
        "certified_land_cost_cents": land,
        "certified_depreciable_basis_cents": depreciable,
        "certified_eligible_basis_cents": eligible,
        "preparer_name": body.get("preparer_name"),
        "certified_aggregate_basis_cents": land + depreciable,
        "status": "DRAFT",
        "submission_round": 0,
        "deficiency_notes": None,
        "reviewed_by_user_id": None,
        "accepted_at": None,
    })
    return object_response(serialize.cost_cert(row), 201)


@bp.post("/cost-certifications/<row_id>/submit")
def submit_cost_cert(row_id):
    caller = guard("POST /cost-certifications/{id}/submit")
    cert = domain.soft_get(db.cost_certs, row_id)
    own_project(caller, domain.project_of_row(cert))

    body = v.body()
    land = v.opt_int(body, "certified_land_cost_cents", minimum=0)
    depreciable = v.opt_int(body, "certified_depreciable_basis_cents", minimum=1)
    eligible = v.opt_int(body, "certified_eligible_basis_cents", minimum=1)

    cert = domain.get_or_404(db.cost_certs, row_id, "ERR_COST_CERT_NOT_FOUND")
    project = domain.project_of_row(cert)
    own_project(caller, project)

    effective_land = land if land is not None else cert.get("certified_land_cost_cents")
    effective_dep = (depreciable if depreciable is not None
                     else cert.get("certified_depreciable_basis_cents"))
    effective_elig = (eligible if eligible is not None
                      else cert.get("certified_eligible_basis_cents"))
    if effective_elig > effective_dep:
        fail("ERR_INVALID_REQUEST",
             "certified_eligible_basis_cents may not exceed "
             "certified_depreciable_basis_cents.")

    domain.require_developer_active(project)

    if cert.get("status") not in ("DRAFT", "RETURNED_FOR_REVISION"):
        fail("ERR_COST_CERT_STATE_INVALID",
             "A certification in %s cannot be submitted." % cert.get("status"))

    if project is not None and project.get("development_status") not in PLACED_STATUSES:
        fail("ERR_PROJECT_NOT_PLACED_IN_SERVICE",
             "The development must be placed in service before certification.")

    cert["certified_land_cost_cents"] = effective_land
    cert["certified_depreciable_basis_cents"] = effective_dep
    cert["certified_eligible_basis_cents"] = effective_elig
    cert["certified_aggregate_basis_cents"] = effective_land + effective_dep
    cert["status"] = "SUBMITTED"
    cert["submission_round"] = (cert.get("submission_round") or 0) + 1
    cert["deficiency_notes"] = None
    touch(cert)
    return object_response(serialize.cost_cert(cert))


@bp.post("/cost-certifications/<row_id>/review")
def review_cost_cert(row_id):
    caller = guard("POST /cost-certifications/{id}/review")
    body = v.body()
    decision = v.req_enum(body, "decision", ("ACCEPT", "RETURN"))
    deficiency_notes = v.opt_str(body, "deficiency_notes")

    cert = domain.get_or_404(db.cost_certs, row_id, "ERR_COST_CERT_NOT_FOUND")
    if cert.get("status") != "SUBMITTED":
        fail("ERR_COST_CERT_STATE_INVALID",
             "A certification in %s cannot be reviewed." % cert.get("status"))

    project = domain.project_of_row(cert)

    if decision == "RETURN":
        cert["status"] = "RETURNED_FOR_REVISION"
        cert["deficiency_notes"] = deficiency_notes
        cert["reviewed_by_user_id"] = caller.user_id
        touch(cert)
        return object_response(serialize.cost_cert(cert))

    cert["status"] = "ACCEPTED"
    cert["deficiency_notes"] = deficiency_notes
    cert["reviewed_by_user_id"] = caller.user_id
    cert["accepted_at"] = now_clock_iso()
    touch(cert)

    if project is not None:
        funded_total = 0
        for issue in calc.project_issues(project["id"]):
            funded_total += sum((d.get("approved_amount_cents") or 0)
                                for d in calc.issue_draws(issue["id"])
                                if d.get("status") == "FUNDED")
        ratio = calc.fifty_percent_ratio(
            funded_total, cert.get("certified_aggregate_basis_cents") or 0)
        project["final_fifty_percent_ratio_bps"] = ratio
        project["automatic_credit_triggered"] = calc.fifty_percent_passes(ratio)
        touch(project)

    return object_response(serialize.cost_cert(cert))


# --------------------------------------------------------------------------
# credit allocation
# --------------------------------------------------------------------------

@bp.post("/credit-allocations")
def create_credit_allocation():
    caller = guard("POST /credit-allocations")
    body = v.body()
    project_id = v.req_id(body, "project_id")
    cost_certification_id = v.req_id(body, "cost_certification_id")
    credit_percentage_bps = v.req_int(body, "credit_percentage_bps", minimum=1, maximum=1000)
    pis_raw, _pis_dt = v.req_dt(body, "placed_in_service_date")

    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    cert = domain.get_or_404(db.cost_certs, cost_certification_id, "ERR_COST_CERT_NOT_FOUND")

    if project.get("development_status") not in PLACED_STATUSES:
        fail("ERR_PROJECT_NOT_PLACED_IN_SERVICE",
             "The development must be placed in service before a credit allocation.")
    if cert.get("status") != "ACCEPTED":
        fail("ERR_COST_CERT_NOT_ACCEPTED",
             "The referenced cost certification is %s, not ACCEPTED." % cert.get("status"))
    if cert.get("project_id") != project_id:
        fail("ERR_COST_CERT_PROJECT_MISMATCH",
             "The certification belongs to a different development.")
    if any(a.get("status") in ("PENDING", "ISSUED", "RECAPTURE_PENDING")
           for a in calc.project_credit_allocations(project_id)):
        fail("ERR_ALLOCATION_ALREADY_EXISTS",
             "The development already holds a live credit allocation.")

    solved = calc.qualified_basis_and_annual_credit(project, cert, credit_percentage_bps)
    row = new_row(db.credit_allocations, {
        "project_id": project_id,
        "cost_certification_id": cost_certification_id,
        "credit_percentage_bps": credit_percentage_bps,
        "placed_in_service_date": pis_raw,
        "qualified_basis_cents": solved["qualified_basis_cents"],
        "applicable_fraction_bps": calc.applicable_fraction(project)["applicable_fraction_bps"],
        "annual_credit_cents": solved["annual_credit_cents"],
        "total_credit_cents": solved["total_credit_cents"],
        "status": "PENDING",
        "form_8609_number": None,
        "issued_by_user_id": caller.user_id,
        "recapture_amount_cents": 0,
    })
    return object_response(serialize.credit_allocation(row), 201)


@bp.post("/credit-allocations/<row_id>/issue")
def issue_credit_allocation(row_id):
    caller = guard("POST /credit-allocations/{id}/issue")
    body = v.body()
    form_number = v.req_str(body, "form_8609_number", allow_empty=False)

    allocation = domain.get_or_404(db.credit_allocations, row_id,
                                   "ERR_CREDIT_ALLOCATION_NOT_FOUND")
    if allocation.get("status") != "PENDING":
        fail("ERR_CREDIT_ALLOCATION_STATE_INVALID",
             "A credit allocation in %s cannot be issued." % allocation.get("status"))

    project = domain.project_of_row(allocation)
    if project is None or not project.get("automatic_credit_triggered"):
        fail("ERR_FIFTY_PERCENT_TEST_FAILED",
             "The fifty-percent aggregate basis test has not been satisfied.")

    # Segregation of duties (PRD 2.10).
    cap_award = None
    for candidate in calc.project_allocations(project["id"]):
        if candidate.get("decided_by_user_id") and candidate.get("status") in (
                "AWARDED", "COMMITTED", "RELEASED", "EXPIRED"):
            cap_award = candidate
            break
    cert = domain.soft_get(db.cost_certs, allocation.get("cost_certification_id"))
    blocked = set()
    if cap_award is not None and cap_award.get("decided_by_user_id"):
        blocked.add(cap_award["decided_by_user_id"])
    if cert is not None and cert.get("reviewed_by_user_id"):
        blocked.add(cert["reviewed_by_user_id"])
    if caller.user_id in blocked:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The issuing officer must differ from the cap-award and cost-certification "
             "reviewers.")

    allocation["status"] = "ISSUED"
    allocation["form_8609_number"] = form_number
    allocation["issued_by_user_id"] = caller.user_id
    touch(allocation)
    return object_response(serialize.credit_allocation(allocation))


# --------------------------------------------------------------------------
# investor delivery
# --------------------------------------------------------------------------

@bp.post("/investor-deliveries")
def create_delivery():
    caller = guard("POST /investor-deliveries")
    body = v.body()
    allocation = domain.soft_get(db.credit_allocations, body.get("credit_allocation_id"))
    own_project(caller, domain.project_of_row(allocation))

    credit_allocation_id = v.req_id(body, "credit_allocation_id")
    investor_id = v.req_id(body, "investor_id")
    requested_credit_cents = v.req_int(body, "requested_credit_cents", minimum=1)
    capital_contribution_cents = v.req_int(body, "capital_contribution_cents", minimum=1)
    expected_version = v.req_int(body, "expected_credit_allocation_version")

    # Investor is declared before CreditAllocation, so its 404 surfaces first.
    domain.get_or_404(db.investors, investor_id, "ERR_INVESTOR_NOT_FOUND")
    allocation = domain.get_or_404(db.credit_allocations, credit_allocation_id,
                                   "ERR_CREDIT_ALLOCATION_NOT_FOUND")
    own_project(caller, domain.project_of_row(allocation))

    if expected_version != allocation.get("version"):
        fail("ERR_STALE_CREDIT_ALLOCATION_VERSION",
             "expected_credit_allocation_version %s does not match the allocation's "
             "current version %s." % (expected_version, allocation.get("version")))

    if allocation.get("status") not in ("ISSUED", "RECAPTURE_PENDING"):
        fail("ERR_CREDIT_ALLOCATION_STATE_INVALID",
             "A credit allocation in %s cannot be delivered." % allocation.get("status"))

    remainder = calc.allocation_ledger(allocation)["undelivered_credit_cents"]
    if remainder <= 0:
        fail("ERR_NO_UNDELIVERED_CREDIT",
             "The allocation has no undelivered credit left.")

    delivered = min(requested_credit_cents, remainder)
    row = new_row(db.deliveries, {
        "credit_allocation_id": credit_allocation_id,
        "investor_id": investor_id,
        "requested_credit_cents": requested_credit_cents,
        "capital_contribution_cents": capital_contribution_cents,
        "delivered_credit_cents": delivered,
        "price_per_credit_dollar_bps": calc.price_per_credit_dollar_bps(
            capital_contribution_cents, delivered),
        "status": "DELIVERED",
        "accepted_at": None,
        "rescind_reason": None,
    })
    touch(allocation)
    return object_response(serialize.delivery(row), 201)


@bp.post("/investor-deliveries/<row_id>/accept")
def accept_delivery(row_id):
    caller = guard("POST /investor-deliveries/{id}/accept")
    delivery = domain.soft_get(db.deliveries, row_id)
    own_delivery(caller, delivery)

    delivery = domain.get_or_404(db.deliveries, row_id, "ERR_DELIVERY_NOT_FOUND")
    own_delivery(caller, delivery)

    if delivery.get("status") != "DELIVERED":
        fail("ERR_DELIVERY_STATE_INVALID",
             "A delivery in %s cannot be accepted." % delivery.get("status"))

    delivery["status"] = "ACCEPTED"
    delivery["accepted_at"] = now_clock_iso()
    touch(delivery)

    investor = domain.soft_get(db.investors, delivery.get("investor_id"))
    if investor is not None:
        investor["total_credit_accepted_cents"] = (
            (investor.get("total_credit_accepted_cents") or 0)
            + (delivery.get("delivered_credit_cents") or 0))
        touch(investor)
    return object_response(serialize.delivery(delivery))


@bp.post("/investor-deliveries/<row_id>/rescind")
def rescind_delivery(row_id):
    caller = guard("POST /investor-deliveries/{id}/rescind")
    delivery = domain.soft_get(db.deliveries, row_id)
    own_delivery(caller, delivery, domain.project_of_delivery(delivery))

    body = v.body()
    rescind_reason = v.req_str(body, "rescind_reason", allow_empty=False)

    delivery = domain.get_or_404(db.deliveries, row_id, "ERR_DELIVERY_NOT_FOUND")
    own_delivery(caller, delivery, domain.project_of_delivery(delivery))

    previous = delivery.get("status")
    if previous not in ("DELIVERED", "ACCEPTED"):
        fail("ERR_DELIVERY_STATE_INVALID",
             "A delivery in %s cannot be rescinded." % previous)

    delivery["status"] = "RESCINDED"
    delivery["rescind_reason"] = rescind_reason
    touch(delivery)

    allocation = domain.soft_get(db.credit_allocations,
                                 delivery.get("credit_allocation_id"))
    if allocation is not None:
        touch(allocation)
    if previous == "ACCEPTED":
        investor = domain.soft_get(db.investors, delivery.get("investor_id"))
        if investor is not None:
            investor["total_credit_accepted_cents"] = (
                (investor.get("total_credit_accepted_cents") or 0)
                - (delivery.get("delivered_credit_cents") or 0))
            touch(investor)
    return object_response(serialize.delivery(delivery))
