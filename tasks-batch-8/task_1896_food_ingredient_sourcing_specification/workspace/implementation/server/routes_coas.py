"""Certificates of analysis, out-of-spec findings, review close (PRD §3.6, §3.7)."""
from decimal import Decimal

from flask import Blueprint, g, request

from .envelope import (
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_DEVIATION_SCORE_TOO_HIGH,
    ERR_DUPLICATE,
    ERR_FINDINGS_REQUIRE_REJECTION,
    ERR_FINDINGS_UNDISPOSITIONED,
    ERR_INVALID_STATE,
    ERR_MEASURED_VALUES_INCOMPLETE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SOURCE_NOT_ACTIVE,
    body,
    err,
    invalid,
    is_number,
    list_page,
    not_found,
    pagination_params,
    require_roles,
    respond_object,
)
from .services import (
    DISPOSITIONS,
    compute_excess_ratio,
    coas_of_source,
    deviation_score,
    findings_of_coa,
    params_of_spec,
    recompute_risk,
    tier_unit_price,
)
from .store import STORE, new_record, parse_dt, ser_coa, ser_finding, set_dt, touch

bp = Blueprint("coas", __name__)

READERS_NO_AUTHOR = (
    "ProcurementManager",
    "QualityManager",
    "SupplierQualityEngineer",
    "RegulatoryAffairs",
    "PlatformAdmin",
)

ACCEPT_BLOCK_THRESHOLD = Decimal("150")


def get_source_or_404(source_id):
    src = STORE.sources.get(source_id)
    if src is None:
        not_found("approved source not found")
    return src


def get_coa_or_404(source_id, coa_id):
    coa = STORE.coas.get(coa_id)
    if coa is None or coa["approved_source_id"] != source_id:
        not_found("CoA not found")
    return coa


def get_finding_or_404(coa_id, finding_id):
    finding = STORE.findings.get(finding_id)
    if finding is None or finding["coa_id"] != coa_id:
        not_found("finding not found")
    return finding


# ---------------------------------------------------------------------------
# CoA registration
# ---------------------------------------------------------------------------

@bp.post("/sourcing/approved-sources/<source_id>/coas")
@require_roles("SupplierQualityEngineer")
def register_coa(source_id):
    src = get_source_or_404(source_id)
    data = body()

    # Body-FK existence (4) then cross-reference coherence (5).
    contract_id = data.get("contract_id")
    contract = None
    if isinstance(contract_id, str):
        contract = STORE.contracts.get(contract_id)
        if contract is None:
            not_found("contract_id does not reference an existing contract")
    if contract is not None and contract["approved_source_id"] != src["id"]:
        err(ERR_CROSS_REFERENCE_MISMATCH, 422, "contract_id must belong to the path source")

    # State (6): source ACTIVE; contract ACTIVE.
    if src["status"] != "ACTIVE":
        err(ERR_SOURCE_NOT_ACTIVE, 409, "approved source is not ACTIVE")
    if contract is not None and contract["status"] != "ACTIVE":
        err(ERR_INVALID_STATE, 409, "referenced contract is not ACTIVE")

    # Uniqueness (12): lot_number unique within the approved source.
    lot_number = data.get("lot_number")
    if isinstance(lot_number, str):
        for other in coas_of_source(src["id"]):
            if other["lot_number"] == lot_number:
                err(ERR_DUPLICATE, 409, "lot_number already exists for this source")

    # Measured-values completeness (15): every pinned-spec parameter exactly once.
    spec = STORE.specs.get(src["pinned_spec_id"])
    spec_params = params_of_spec(spec["id"]) if spec is not None else []
    measured = data.get("measured_values")
    observed_by_name = {}
    measured_ok = isinstance(measured, list)
    if measured_ok:
        for item in measured:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("parameter_name"), str)
                or not is_number(item.get("observed_value"))
            ):
                measured_ok = False
                break
            if item["parameter_name"] in observed_by_name:
                measured_ok = False
                break
            observed_by_name[item["parameter_name"]] = item["observed_value"]
    if measured_ok:
        spec_names = {p["parameter_name"] for p in spec_params}
        if set(observed_by_name.keys()) != spec_names:
            measured_ok = False
    if not measured_ok:
        err(
            ERR_MEASURED_VALUES_INCOMPLETE,
            422,
            "measured_values must cover every spec parameter exactly once",
        )

    # Basic request shape (23).
    if not isinstance(contract_id, str) or contract_id == "":
        invalid("contract_id is required")
    if not isinstance(lot_number, str) or lot_number == "":
        invalid("lot_number is required")
    qty = data.get("shipped_qty_kg")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)):
        invalid("shipped_qty_kg is required and must be a positive integer")
    if isinstance(qty, float) and not qty.is_integer():
        invalid("shipped_qty_kg must be an integer")
    if qty <= 0:
        invalid("shipped_qty_kg must be > 0")
    received_raw = data.get("received_at")
    if not isinstance(received_raw, str):
        invalid("received_at is required and must be an ISO8601 string")
    try:
        parse_dt(received_raw)
    except ValueError:
        invalid("received_at must be a valid ISO8601 timestamp")

    rec = new_record()
    rec.update(
        {
            "approved_source_id": src["id"],
            "contract_id": contract_id,
            "lot_number": lot_number,
            "shipped_qty_kg": qty,
            "measured_values": measured,
            "registered_by_user_id": g.user_id,
            "provisional_deviation_score": 0,
            "final_deviation_score": None,
            "unit_price_applied": None,
            "status": "REGISTERED",
        }
    )
    set_dt(rec, "received_at", received_raw)
    STORE.coas[rec["id"]] = rec
    return respond_object(ser_coa(rec), 201)


@bp.get("/sourcing/approved-sources/<source_id>/coas")
@require_roles(*READERS_NO_AUTHOR)
def list_coas(source_id):
    get_source_or_404(source_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    contract_id = request.args.get("contract_id")
    rows = coas_of_source(source_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    return list_page(rows, ser_coa, limit, offset)


@bp.get("/sourcing/approved-sources/<source_id>/coas/<coa_id>")
@require_roles(*READERS_NO_AUTHOR)
def get_coa(source_id, coa_id):
    get_source_or_404(source_id)
    return respond_object(ser_coa(get_coa_or_404(source_id, coa_id)))


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

@bp.post("/sourcing/approved-sources/<source_id>/coas/<coa_id>/start-review")
@require_roles("QualityManager")
def start_review(source_id, coa_id):
    src = get_source_or_404(source_id)
    coa = get_coa_or_404(source_id, coa_id)
    if coa["status"] != "REGISTERED":
        err(ERR_INVALID_STATE, 409, "CoA is not REGISTERED")

    spec = STORE.specs.get(src["pinned_spec_id"])
    spec_params = params_of_spec(spec["id"]) if spec is not None else []
    observed_by_name = {}
    for item in coa["measured_values"]:
        observed_by_name[item["parameter_name"]] = item["observed_value"]

    # One finding per out-of-spec measured parameter, in spec parameter creation order.
    for param in spec_params:
        observed = observed_by_name.get(param["parameter_name"])
        if observed is None:
            continue
        if param["min_value"] <= observed <= param["max_value"]:
            continue
        bound = param["min_value"] if observed < param["min_value"] else param["max_value"]
        ratio = compute_excess_ratio(observed, bound, param["min_value"], param["max_value"])
        finding = new_record()
        finding.update(
            {
                "coa_id": coa["id"],
                "parameter_name": param["parameter_name"],
                "observed_value": observed,
                "violated_bound": bound,
                "excess_ratio": float(ratio),
                "criticality_at_finding": param["criticality"],
                "disposition": "REPORTED",
                "disposition_note": None,
            }
        )
        STORE.findings[finding["id"]] = finding

    findings = findings_of_coa(coa["id"])
    coa["provisional_deviation_score"] = float(deviation_score(findings, "provisional"))
    coa["status"] = "UNDER_REVIEW"
    touch(coa)
    return respond_object(ser_coa(coa))


@bp.get("/sourcing/approved-sources/<source_id>/coas/<coa_id>/findings")
@require_roles(*READERS_NO_AUTHOR)
def list_findings(source_id, coa_id):
    get_source_or_404(source_id)
    coa = get_coa_or_404(source_id, coa_id)
    limit, offset = pagination_params()
    disposition = request.args.get("disposition")
    rows = findings_of_coa(coa["id"])
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    return list_page(rows, ser_finding, limit, offset)


@bp.post("/sourcing/approved-sources/<source_id>/coas/<coa_id>/findings/<finding_id>/disposition")
@require_roles("QualityManager")
def disposition_finding(source_id, coa_id, finding_id):
    get_source_or_404(source_id)
    coa = get_coa_or_404(source_id, coa_id)
    finding = get_finding_or_404(coa["id"], finding_id)
    if coa["status"] != "UNDER_REVIEW":
        err(ERR_INVALID_STATE, 409, "CoA is not UNDER_REVIEW")
    data = body()
    disposition = data.get("disposition")
    if disposition not in DISPOSITIONS:
        invalid("disposition must be ACCEPT_AS_IS, DOWNGRADED_TO_MINOR, or REJECT_LOT")
    note = data.get("disposition_note")
    if not isinstance(note, str) or len(note) < 10:
        invalid("disposition_note must be at least 10 characters")
    finding["disposition"] = disposition
    finding["disposition_note"] = note
    touch(finding)
    return respond_object(ser_finding(finding))


@bp.post("/sourcing/approved-sources/<source_id>/coas/<coa_id>/close-review")
@require_roles("QualityManager")
def close_review(source_id, coa_id):
    src = get_source_or_404(source_id)
    coa = get_coa_or_404(source_id, coa_id)
    if coa["status"] != "UNDER_REVIEW":
        err(ERR_INVALID_STATE, 409, "CoA is not UNDER_REVIEW")
    if g.user_id == coa["registered_by_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "registrar cannot close own CoA review")

    findings = findings_of_coa(coa["id"])
    if any(f["disposition"] == "REPORTED" for f in findings):
        err(ERR_FINDINGS_UNDISPOSITIONED, 409, "all findings must be dispositioned first")

    data = body()
    outcome = data.get("outcome")
    if outcome not in ("ACCEPT", "REJECT"):
        invalid("outcome must be ACCEPT or REJECT")

    final_score = deviation_score(findings, "final")
    if outcome == "ACCEPT":
        if any(f["disposition"] == "REJECT_LOT" for f in findings):
            err(ERR_FINDINGS_REQUIRE_REJECTION, 422, "a REJECT_LOT finding forbids ACCEPT")
        provisional = Decimal(str(coa["provisional_deviation_score"]))
        if provisional < ACCEPT_BLOCK_THRESHOLD:
            pass
        else:
            all_accept_as_is = all(f["disposition"] == "ACCEPT_AS_IS" for f in findings)
            if not (all_accept_as_is and final_score < ACCEPT_BLOCK_THRESHOLD):
                err(
                    ERR_DEVIATION_SCORE_TOO_HIGH,
                    422,
                    "deviation score must be strictly below 150 to accept",
                )

    coa["final_deviation_score"] = float(final_score)
    supplier = STORE.suppliers.get(src["supplier_id"])
    if outcome == "ACCEPT":
        contract = STORE.contracts.get(coa["contract_id"])
        unit_price = tier_unit_price(contract, coa["shipped_qty_kg"])
        coa["unit_price_applied"] = float(unit_price)
        contract["cumulative_shipped_kg"] += coa["shipped_qty_kg"]
        touch(contract)
        if any(f["disposition"] == "ACCEPT_AS_IS" for f in findings):
            coa["status"] = "CONDITIONALLY_ACCEPTED"
        else:
            coa["status"] = "ACCEPTED"
    else:
        coa["status"] = "REJECTED"
    touch(coa)
    if supplier is not None:
        recompute_risk(supplier)  # the decided lot enters the 12-month CoA window
    return respond_object(ser_coa(coa))
