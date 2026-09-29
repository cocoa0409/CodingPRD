"""Commercial surface: change orders, spares, acceptance and disputes."""

from flask import Blueprint

from auth import ALL_ROLES, authenticate
from errors import ApiError
from lookups import get_certificate, get_change_order, get_dispute, get_project
from response import list_response, object_response
from serializers import (
    acceptance_certificate_out,
    change_order_out,
    performance_dispute_out,
    spare_part_line_out,
)
from services import calculations as calc
from services.cascade import reopen_design
from store import (
    change_orders_of,
    disputes_of,
    iso,
    new_record,
    now,
    parse_iso,
    plus_days,
    store,
    touch,
)
from validate import (
    body,
    opt_str,
    pagination,
    paginate,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("commercial", __name__)

DECISIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")
CRITICALITIES = ("CRITICAL", "MAJOR", "MINOR")
DAMAGES_BASES = ("NAMEPLATE", "OBSERVED_AVAILABILITY")
OPEN_ORDER_STATUSES = ("SUBMITTED", "REVISION_REQUESTED")


def _open_orders(project):
    """Change orders of the project still awaiting a customer decision."""
    return [
        order
        for order in change_orders_of(project["id"])
        if order["status"] in OPEN_ORDER_STATUSES
    ]


@bp.post("/change-orders")
def create_change_order():
    authenticate(("ProjectDirector",))
    data = body()

    project_id = req_str(data, "project_id")
    title = req_str(data, "title")
    scope_delta_cph = req_int(data, "scope_delta_cph")
    price_delta_cents = req_int(data, "price_delta_cents")
    schedule_delta_days = req_int(data, "schedule_delta_days")

    project = get_project(project_id)

    order = new_record()
    order.update(
        {
            "project_id": project["id"],
            "title": title,
            "scope_delta_cph": scope_delta_cph,
            "price_delta_cents": price_delta_cents,
            "schedule_delta_days": schedule_delta_days,
            "round_no": 1,
            "decision_comment": None,
            "reviewed_by_user_id": None,
            "status": "DRAFT",
        }
    )
    store.change_orders[order["id"]] = order
    touch(project)
    return object_response(change_order_out(order), 201)


@bp.post("/change-orders/<order_id>/submit")
def submit_change_order(order_id):
    authenticate(("ProjectDirector",))
    order = get_change_order(order_id)

    if order["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_CHANGE_ORDER_INVALID_STATE",
            "Only a DRAFT or REVISION_REQUESTED order may be submitted; this one is %s."
            % order["status"],
        )

    project = get_project(order["project_id"])
    order["status"] = "SUBMITTED"
    touch(order)

    if project["commercial_status"] == "CLEAN":
        project["commercial_status"] = "CHANGE_PENDING"
    touch(project)

    return object_response(change_order_out(order))


@bp.post("/change-orders/<order_id>/review-decision")
def review_change_order(order_id):
    user_id, _role = authenticate(("CustomerRep",))
    order = get_change_order(order_id)
    project = get_project(order["project_id"])

    # Band 3 - only the project's nominated representative may decide.
    if user_id != project["customer_rep_user_id"]:
        raise ApiError(
            "ERR_NOT_PROJECT_CUSTOMER",
            "Only the project's nominated customer representative may record a decision.",
        )

    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    expected = req_int(data, "expected_project_version")
    decision_comment = opt_str(data, "decision_comment")

    # Band 7 - optimistic concurrency on the pricing baseline.
    if expected != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version %d does not match the project's version %d."
            % (expected, project["version"]),
        )

    # Band 8 - the order's own state.
    if order["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_CHANGE_ORDER_INVALID_STATE",
            "A decision may only be recorded against a SUBMITTED order; this one is %s."
            % order["status"],
        )

    if decision == "REQUEST_REVISION":
        if order["round_no"] + 1 > calc.CHANGE_ORDER_MAX_ROUNDS:
            raise ApiError(
                "ERR_CHANGE_ORDER_ROUND_LIMIT",
                "Negotiation is bounded at %d rounds." % calc.CHANGE_ORDER_MAX_ROUNDS,
            )
    elif decision == "APPROVE":
        # Band 15 - the money gate, evaluated last and before anything persists.
        _subtotal, fee, value = calc.contract_value_recompute(
            project, including_order_id=order["id"]
        )
        if value > project["authorized_ceiling_cents"]:
            raise ApiError(
                "ERR_CONTRACT_CEILING_EXCEEDED",
                "The repriced contract value %d exceeds the authorized ceiling %d."
                % (value, project["authorized_ceiling_cents"]),
            )

    order["decision_comment"] = decision_comment
    order["reviewed_by_user_id"] = user_id

    if decision == "REQUEST_REVISION":
        order["status"] = "REVISION_REQUESTED"
        order["round_no"] += 1
    elif decision == "REJECT":
        order["status"] = "REJECTED"
    else:
        order["status"] = "APPROVED"
        project["escalation_fee_cents"] = fee
        project["contract_value_cents"] = value
    touch(order)

    if project["commercial_status"] == "CHANGE_PENDING" and not _open_orders(project):
        project["commercial_status"] = "CLEAN"
    touch(project)

    if decision == "APPROVE" and order["scope_delta_cph"] != 0:
        reopen_design(project)

    return object_response(change_order_out(order))


@bp.get("/change-orders/<order_id>")
def read_change_order(order_id):
    authenticate(ALL_ROLES)
    order = get_change_order(order_id)
    return object_response(change_order_out(order))


@bp.post("/spare-part-lines")
def create_spare_part_line():
    authenticate(("ProjectDirector",))
    data = body()

    project_id = req_str(data, "project_id")
    part_no = req_str(data, "part_no")
    criticality = req_enum(data, "criticality", CRITICALITIES)
    unit_cost_cents = req_int(data, "unit_cost_cents", minimum=1)
    min_stock_qty = req_int(data, "min_stock_qty", minimum=1)
    lead_time_days = req_int(data, "lead_time_days", minimum=0)

    project = get_project(project_id)

    line = new_record()
    line.update(
        {
            "project_id": project["id"],
            "part_no": part_no,
            "criticality": criticality,
            "unit_cost_cents": unit_cost_cents,
            "min_stock_qty": min_stock_qty,
            "lead_time_days": lead_time_days,
            "allocated_cents": 0,
            "status": "DRAFT",
        }
    )
    requested, weighted = calc.spare_line_targets(line)
    line["requested_cents"] = requested
    line["weighted_target_cents"] = weighted
    store.spare_part_lines[line["id"]] = line

    touch(project)
    return object_response(spare_part_line_out(line), 201)


@bp.post("/acceptance-certificates")
def create_acceptance_certificate():
    user_id, _role = authenticate(("ProjectDirector",))
    data = body()
    project_id = req_str(data, "project_id")
    project = get_project(project_id)

    # Band 8 - the acceptance prerequisites, then the commercial dimension.
    if not calc.acceptance_ready(project):
        raise ApiError(
            "ERR_ACCEPTANCE_PREREQ_NOT_MET",
            "Every ramp step must have passed and every zone must be live before acceptance.",
        )
    if project["commercial_status"] != "CLEAN":
        raise ApiError(
            "ERR_OPEN_CHANGE_ORDER",
            "The commercial dimension must be CLEAN before a certificate may be issued.",
        )

    full_rate = calc.passing_full_rate_ramp(project)

    # Band 9 - segregation of duties.
    if full_rate is not None and full_rate["recorded_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The issuer may not be the operator who recorded the full-rate ramp step.",
        )

    degraded = calc.degraded_complete_run(project)

    certificate = new_record()
    certificate.update(
        {
            "project_id": project["id"],
            "accepted_throughput_cph": full_rate["measured_cph"] if full_rate else None,
            "bottleneck_availability_pct": (
                degraded["bottleneck_availability_pct"] if degraded else None
            ),
            "retention_amount_cents": calc.retention_amount(project),
            "retention_release_cents": 0,
            "issued_by_user_id": user_id,
            "dispute_deadline_utc": iso(
                plus_days(certificate["_created_dt"], calc.DISPUTE_WINDOW_DAYS)
            ),
            "status": "ISSUED",
        }
    )
    store.acceptance_certificates[certificate["id"]] = certificate

    if project["delivery_status"] == "COMMISSIONING":
        project["delivery_status"] = "ACCEPTED"
    touch(project)

    return object_response(acceptance_certificate_out(certificate), 201)


@bp.get("/acceptance-certificates/<certificate_id>")
def read_acceptance_certificate(certificate_id):
    authenticate(ALL_ROLES)
    certificate = get_certificate(certificate_id)
    return object_response(acceptance_certificate_out(certificate))


@bp.post("/performance-disputes")
def create_performance_dispute():
    user_id, _role = authenticate(("CustomerRep",))
    data = body()

    certificate_id = req_str(data, "acceptance_certificate_id")
    claimed_cph = req_int(data, "claimed_cph", minimum=0)
    damages_basis = req_enum(data, "damages_basis", DAMAGES_BASES)

    certificate = get_certificate(certificate_id)
    project = get_project(certificate["project_id"])

    # Band 3 - only the project's nominated representative may file.
    if user_id != project["customer_rep_user_id"]:
        raise ApiError(
            "ERR_NOT_PROJECT_CUSTOMER",
            "Only the project's nominated customer representative may file a dispute.",
        )

    # Band 8 - the certificate's own state.
    if certificate["status"] != "ISSUED":
        raise ApiError(
            "ERR_CERTIFICATE_ALREADY_DISPUTED",
            "The certificate is %s; only an ISSUED certificate may be disputed."
            % certificate["status"],
        )

    # The filing comparison is inclusive on the deadline instant.
    deadline = parse_iso(certificate["dispute_deadline_utc"])
    if deadline is not None and now() > deadline:
        raise ApiError(
            "ERR_DISPUTE_WINDOW_EXPIRED",
            "The 30-day dispute window closed at %s." % certificate["dispute_deadline_utc"],
        )

    nameplate = calc.liquidated_damages(project, certificate, "NAMEPLATE", claimed_cph)
    observed = calc.liquidated_damages(
        project, certificate, "OBSERVED_AVAILABILITY", claimed_cph
    )
    bound = nameplate if damages_basis == "NAMEPLATE" else observed

    dispute = new_record()
    dispute.update(
        {
            "acceptance_certificate_id": certificate["id"],
            "claimed_cph": claimed_cph,
            "damages_basis": damages_basis,
            "provisional_nameplate_cents": nameplate,
            "provisional_observed_cents": observed,
            "bound_provisional_cents": bound,
            "retest_measured_cph": None,
            "final_damages_cents": None,
            "sla_credit_cents": None,
            "filed_by_user_id": user_id,
            "retest_by_user_id": None,
            "retest_recorded_at": None,
            "status": "OPEN",
        }
    )
    store.performance_disputes[dispute["id"]] = dispute

    certificate["status"] = "DISPUTED"
    touch(certificate)

    if project["commercial_status"] == "CLEAN":
        project["commercial_status"] = "DISPUTED"
    touch(project)

    return object_response(performance_dispute_out(dispute), 201)


@bp.post("/performance-disputes/<dispute_id>/joint-retest")
def joint_retest(dispute_id):
    user_id, _role = authenticate(("SiteManager",))
    dispute = get_dispute(dispute_id)
    data = body()
    retest_measured_cph = req_int(data, "retest_measured_cph", minimum=0)

    if dispute["status"] != "OPEN":
        raise ApiError(
            "ERR_DISPUTE_INVALID_STATE",
            "The dispute is %s; only an OPEN dispute may be settled." % dispute["status"],
        )

    certificate = get_certificate(dispute["acceptance_certificate_id"])
    project = get_project(certificate["project_id"])

    instant = now()
    final_damages = calc.liquidated_damages(
        project, certificate, dispute["damages_basis"], retest_measured_cph
    )
    elapsed_minutes = int((instant - dispute["_created_dt"]).total_seconds() // 60)
    sla_credit = calc.sla_response_credit(project, elapsed_minutes)

    dispute["retest_measured_cph"] = retest_measured_cph
    dispute["retest_by_user_id"] = user_id
    dispute["retest_recorded_at"] = iso(instant)
    dispute["final_damages_cents"] = final_damages
    dispute["sla_credit_cents"] = sla_credit
    dispute["status"] = "RESOLVED_UPHELD" if final_damages == 0 else "RESOLVED_CREDITED"
    touch(dispute)

    if final_damages == 0:
        certificate["status"] = "UPHELD"
        certificate["retention_release_cents"] = certificate["retention_amount_cents"]
    else:
        certificate["status"] = "REVISED"
        certificate["retention_release_cents"] = max(
            0, certificate["retention_amount_cents"] - final_damages - sla_credit
        )
    touch(certificate)

    if project["commercial_status"] == "DISPUTED":
        project["commercial_status"] = "SETTLED"
    touch(project)

    return object_response(performance_dispute_out(dispute))


@bp.get("/acceptance-certificates/<certificate_id>/disputes")
def list_certificate_disputes(certificate_id):
    authenticate(ALL_ROLES)
    certificate = get_certificate(certificate_id)
    limit, offset = pagination()
    records = disputes_of(certificate["id"])
    page, total = paginate(records, limit, offset)
    return list_response([performance_dispute_out(r) for r in page], limit, offset, total)
