"""Warranty claims, failure analysis and supplier quality (PRD 3.9)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import routes_suppliers as sup
import store
import validation
from errors import ApiError
from validation import BOOLEAN, DATETIME, INTEGER, STRING, f

bp = Blueprint("warranty", __name__)

ROOT_CAUSES = ["SUPPLIER_DEFECT", "WORKMANSHIP", "MISAPPLICATION",
               "TRANSPORT_DAMAGE", "UNDETERMINED"]
WARRANTABLE_CAUSES = ("SUPPLIER_DEFECT", "WORKMANSHIP")
ZERO_BUCKETS = {"PARTS": 0, "LABOR": 0, "FREIGHT": 0, "CONSEQUENTIAL": 0}


def _score_supplier(supplier_id):
    supplier = store.get("supplier", supplier_id)
    if supplier is None:
        return
    calc.refresh_supplier_indices(supplier)
    sup.apply_probation_cycle(supplier)
    store.touch("supplier", supplier)


# --------------------------------------------------------------------------- #
# warranty claims
# --------------------------------------------------------------------------- #

@bp.route("/engineered-orders/<oid>/warranty-claims", methods=["POST"])
def create_claim(oid):
    rbac.authenticate("POST /engineered-orders/{id}/warranty-claims")
    order = common.resolve("order", oid)
    payload = validation.body()
    component = None
    if payload.get("suspect_component_id") is not None:
        component = common.resolve_body_ref("component", payload, "suspect_component_id")
    data = validation.validate(payload, [
        f("claim_number", STRING, required=True),
        f("suspect_component_id", STRING),
        f("failure_reported_at", DATETIME, required=True),
        f("parts_claim_cents", INTEGER, required=True, minimum=0),
        f("labor_claim_cents", INTEGER, required=True, minimum=0),
        f("freight_claim_cents", INTEGER, required=True, minimum=0),
        f("consequential_claim_cents", INTEGER, minimum=0, default=0),
        f("consequential_covered", BOOLEAN, default=False),
    ])
    common.check_order_not_cancelled(order)
    for c in store.all_rows("claim"):
        if c.get("claim_number") == data["claim_number"]:
            raise ApiError("ERR_DUPLICATE_CODE", "claim_number already exists")
    if data["consequential_claim_cents"] and not data["consequential_covered"]:
        raise ApiError("ERR_CONSEQUENTIAL_NOT_COVERED",
                       "the contract carries no consequential loss rider")
    claim = {
        "engineered_order_id": oid,
        "suspect_component_id": component["id"] if component is not None else None,
        "claim_number": data["claim_number"],
        "status": "SUBMITTED",
        "failure_reported_at": data["failure_reported_at"],
        "rma_number": None,
        "parts_claim_cents": data["parts_claim_cents"],
        "labor_claim_cents": data["labor_claim_cents"],
        "freight_claim_cents": data["freight_claim_cents"],
        "consequential_claim_cents": data["consequential_claim_cents"],
        "consequential_covered": data["consequential_covered"],
        "liability_cap_cents": 0,
        "credit_issued_cents": 0,
        "bucket_allocation": dict(ZERO_BUCKETS),
        "analysis_round": 0,
        "settled_by_user_id": None,
    }
    store.insert("claim", claim)
    posture.refresh(order)
    return envelope.created(store.public(claim))


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    rbac.authenticate("GET /warranty-claims")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("claim"), {
        "engineered_order_id": common.qstr("engineered_order_id"),
        "suspect_component_id": common.qstr("suspect_component_id"),
        "status": common.qstr("status"),
        "claim_number": common.qstr("claim_number"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/warranty-claims/<cid>", methods=["GET"])
def get_claim(cid):
    rbac.authenticate("GET /warranty-claims/{id}")
    return envelope.ok(store.public(common.resolve("claim", cid)))


@bp.route("/warranty-claims/<cid>/issue-rma", methods=["POST"])
def issue_rma(cid):
    rbac.authenticate("POST /warranty-claims/{id}/issue-rma")
    claim = common.resolve("claim", cid)
    order = common.resolve("order", claim.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("rma_number", STRING, required=True)])
    common.check_state("claim", claim, ("SUBMITTED",))
    common.check_order_not_cancelled(order)
    expiry = calc.warranty_window_expiry(order)
    if expiry is None:
        raise ApiError("ERR_WARRANTY_WINDOW_UNAVAILABLE",
                       "no COMPLETE commissioning job anchors a warranty window")
    reported = clock.sec(clock.parse(claim.get("failure_reported_at")))
    if reported is None or reported >= clock.sec(expiry):
        raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED",
                       "failure_reported_at is not strictly before the window expiry")
    claim["status"] = "RMA_ISSUED"
    claim["rma_number"] = data["rma_number"]
    claim["liability_cap_cents"] = calc.liability_cap_cents(order)
    store.touch("claim", claim)
    posture.refresh(order)
    return envelope.ok(store.public(claim))


@bp.route("/warranty-claims/<cid>/receive-unit", methods=["POST"])
def receive_unit(cid):
    rbac.authenticate("POST /warranty-claims/{id}/receive-unit")
    claim = common.resolve("claim", cid)
    order = common.resolve("order", claim.get("engineered_order_id"))
    common.check_state("claim", claim, ("RMA_ISSUED",))
    common.check_order_not_cancelled(order)
    claim["status"] = "UNIT_RECEIVED"
    store.touch("claim", claim)
    return envelope.ok(store.public(claim))


@bp.route("/warranty-claims/<cid>/settle", methods=["POST"])
def settle_claim(cid):
    actor = rbac.authenticate("POST /warranty-claims/{id}/settle")
    claim = common.resolve("claim", cid)
    order = common.resolve("order", claim.get("engineered_order_id"))
    published = [r for r in store.where("failure_report", warranty_claim_id=cid)
                 if r.get("status") == "PUBLISHED"]
    for report in published:
        rbac.check_sod(actor, report.get("authored_by_user_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("settled_by_user_id", STRING, required=True)])
    for report in published:
        if data["settled_by_user_id"] == report.get("authored_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the settling user authored a published analysis")
    common.check_state("claim", claim, ("WARRANTABLE",))
    common.check_order_not_cancelled(order)
    credit, buckets = calc.credit_waterfall(claim)
    if credit > (claim.get("liability_cap_cents") or 0):
        raise ApiError("ERR_WARRANTY_CAP_EXCEEDED",
                       "the credit exceeds the pinned liability cap")
    claim["status"] = "SETTLED"
    claim["credit_issued_cents"] = credit
    claim["bucket_allocation"] = buckets
    claim["settled_by_user_id"] = data["settled_by_user_id"]
    store.touch("claim", claim)
    store.touch("order", order)
    posture.refresh(order)
    common.rebill_stages(order)
    return envelope.ok(store.public(claim))


@bp.route("/warranty-claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    rbac.authenticate("POST /warranty-claims/{id}/reject")
    claim = common.resolve("claim", cid)
    order = common.resolve("order", claim.get("engineered_order_id"))
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    common.check_state("claim", claim, ("SUBMITTED", "NON_WARRANTABLE"))
    claim["status"] = "REJECTED"
    claim["credit_issued_cents"] = 0
    if isinstance(payload.get("reason"), str):
        claim["reject_reason"] = payload["reason"]
    store.touch("claim", claim)
    posture.refresh(order)
    return envelope.ok(store.public(claim))


# --------------------------------------------------------------------------- #
# failure analysis reports
# --------------------------------------------------------------------------- #

@bp.route("/warranty-claims/<cid>/failure-analysis-reports", methods=["POST"])
def create_failure_report(cid):
    rbac.authenticate("POST /warranty-claims/{id}/failure-analysis-reports")
    claim = common.resolve("claim", cid)
    order = common.resolve("order", claim.get("engineered_order_id"))
    payload = validation.body()
    supplier = None
    if payload.get("attributed_supplier_id") is not None:
        supplier = common.resolve_body_ref("supplier", payload, "attributed_supplier_id")
    data = validation.validate(payload, [
        f("attributed_supplier_id", STRING),
        f("root_cause_code", STRING, required=True, enum=ROOT_CAUSES),
        f("authored_by_user_id", STRING, required=True),
        f("quarantine_recommended", BOOLEAN, default=False),
        f("defect_weight", INTEGER, required=True, minimum=1, maximum=10),
    ])
    common.check_state("claim", claim, ("UNIT_RECEIVED", "ANALYSIS_IN_PROGRESS"))
    common.check_order_not_cancelled(order)
    for other in store.where("failure_report", warranty_claim_id=cid):
        if other.get("status") == "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "report %s on the claim is still DRAFT" % other["id"])
    report = {
        "warranty_claim_id": cid,
        "attributed_supplier_id": supplier["id"] if supplier is not None else None,
        "root_cause_code": data["root_cause_code"],
        "authored_by_user_id": data["authored_by_user_id"],
        "quarantine_recommended": data["quarantine_recommended"],
        "defect_weight": data["defect_weight"],
        "status": "DRAFT",
        "published_at": None,
        "retraction_reason": None,
    }
    store.insert("failure_report", report)
    if claim.get("status") != "ANALYSIS_IN_PROGRESS":
        claim["status"] = "ANALYSIS_IN_PROGRESS"
        store.touch("claim", claim)
    return envelope.created(store.public(report))


@bp.route("/warranty-claims/<cid>/failure-analysis-reports", methods=["GET"])
def list_claim_failure_reports(cid):
    rbac.authenticate("GET /warranty-claims/{id}/failure-analysis-reports")
    common.resolve("claim", cid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("failure_report", warranty_claim_id=cid), {
        "status": common.qstr("status"),
        "root_cause_code": common.qstr("root_cause_code"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/failure-analysis-reports", methods=["GET"])
def list_failure_reports():
    rbac.authenticate("GET /failure-analysis-reports")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("failure_report"), {
        "warranty_claim_id": common.qstr("warranty_claim_id"),
        "attributed_supplier_id": common.qstr("attributed_supplier_id"),
        "status": common.qstr("status"),
        "root_cause_code": common.qstr("root_cause_code"),
        "quarantine_recommended": common.qbool("quarantine_recommended"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/failure-analysis-reports/<rid>", methods=["GET"])
def get_failure_report(rid):
    rbac.authenticate("GET /failure-analysis-reports/{id}")
    return envelope.ok(store.public(common.resolve("failure_report", rid)))


@bp.route("/failure-analysis-reports/<rid>/publish", methods=["POST"])
def publish_failure_report(rid):
    rbac.authenticate("POST /failure-analysis-reports/{id}/publish")
    report = common.resolve("failure_report", rid)
    claim = common.resolve("claim", report.get("warranty_claim_id"))
    order = common.resolve("order", claim.get("engineered_order_id"))
    common.check_state("failure_report", report, ("DRAFT",))
    if claim.get("status") != "ANALYSIS_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the claim is %s" % claim.get("status"))
    cause = report.get("root_cause_code")
    if cause == "SUPPLIER_DEFECT" and not report.get("attributed_supplier_id"):
        raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                       "attributed_supplier_id is mandatory for SUPPLIER_DEFECT")
    if cause != "SUPPLIER_DEFECT" and report.get("attributed_supplier_id"):
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                       "attributed_supplier_id may only accompany SUPPLIER_DEFECT")
    report["status"] = "PUBLISHED"
    report["published_at"] = clock.now_str()
    store.touch("failure_report", report)

    # hop 1 -- the claim is decided
    if cause in WARRANTABLE_CAUSES:
        claim["status"] = "WARRANTABLE"
        credit, buckets = calc.credit_waterfall(claim)
        claim["credit_issued_cents"] = credit
        claim["bucket_allocation"] = buckets
    else:
        claim["status"] = "NON_WARRANTABLE"
        claim["credit_issued_cents"] = 0
        claim["bucket_allocation"] = dict(ZERO_BUCKETS)
    store.touch("claim", claim)

    # hops 2-4 -- quarantine the suspect component and unwind its reservations
    component = store.get("component", claim.get("suspect_component_id"))
    if (claim.get("status") == "WARRANTABLE" and report.get("quarantine_recommended")
            and cause == "SUPPLIER_DEFECT" and component is not None
            and component.get("status") == "ACTIVE"):
        component["status"] = "QUARANTINED"
        component["quarantine_reason"] = "FAILURE_ANALYSIS"
        store.touch("component", component)
        common.release_component_reservations(component)

    # hops 5-6 -- score the attributed supplier and run the probation cycle
    if report.get("attributed_supplier_id"):
        supplier = store.get("supplier", report["attributed_supplier_id"])
        if supplier is not None:
            supplier["attributed_failure_count"] = (supplier.get("attributed_failure_count") or 0) + 1
            _score_supplier(supplier["id"])
    posture.refresh(order)
    return envelope.ok(store.public(report))


@bp.route("/failure-analysis-reports/<rid>/retract", methods=["POST"])
def retract_failure_report(rid):
    rbac.authenticate("POST /failure-analysis-reports/{id}/retract")
    report = common.resolve("failure_report", rid)
    claim = common.resolve("claim", report.get("warranty_claim_id"))
    order = common.resolve("order", claim.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("retraction_reason", STRING, required=True)])
    if not data["retraction_reason"].strip():
        raise ApiError("ERR_MISSING_REQUIRED_FIELD", "retraction_reason must be non-empty")
    was_published = report.get("status") == "PUBLISHED"
    common.check_state("failure_report", report, ("DRAFT", "PUBLISHED"))
    if was_published and claim.get("status") not in ("WARRANTABLE", "NON_WARRANTABLE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the claim is %s" % claim.get("status"))
    report["status"] = "RETRACTED"
    report["retraction_reason"] = data["retraction_reason"]
    store.touch("failure_report", report)
    if was_published:
        claim["status"] = "ANALYSIS_IN_PROGRESS"
        claim["analysis_round"] = (claim.get("analysis_round") or 0) + 1
        claim["credit_issued_cents"] = 0
        claim["bucket_allocation"] = dict(ZERO_BUCKETS)
        store.touch("claim", claim)
        if report.get("attributed_supplier_id"):
            supplier = store.get("supplier", report["attributed_supplier_id"])
            if supplier is not None:
                supplier["attributed_failure_count"] = max(
                    0, (supplier.get("attributed_failure_count") or 0) - 1)
                _score_supplier(supplier["id"])
        component = store.get("component", claim.get("suspect_component_id"))
        if component is not None and component.get("status") == "QUARANTINED":
            still = False
            for claim_row in store.where("claim", suspect_component_id=component["id"]):
                for other in store.where("failure_report", warranty_claim_id=claim_row["id"]):
                    if other["id"] == rid:
                        continue
                    if other.get("status") == "PUBLISHED" and other.get("quarantine_recommended"):
                        still = True
                        break
                if still:
                    break
            if not still:
                component["status"] = "ACTIVE"
                component["quarantine_reason"] = None
                calc.refresh_component_buckets(component)
                store.touch("component", component)
    posture.refresh(order)
    return envelope.ok(store.public(report))
