"""Volume reports and counterparty reconciliation."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import common as C
import domain as D
import store as S
import validators as V
from common import dec, new_id, now_iso, parse_date_str, pct, vol
from errors import ApiError
from response import created, listing, ok
from store import ordered, touch_once

bp = Blueprint("reports", __name__)

SELLER_BASIS_FILTER = {"verification": ("VERIFIED",), "settlement": ("SETTLED",)}
BUYER_BASIS_FILTER = {"verification": ("VERIFIED", "DISPUTED"),
                      "settlement": ("PENDING", "SETTLED")}


@bp.post("/volume-reports")
def file_report():
    from auth import authorize
    user_id, role = authorize("ProducerRepresentative", "BrandLicensee")
    data = V.body()
    holder_id = V.req_id(data, "holder_id")
    counterparty_holder_id = V.req_id(data, "counterparty_holder_id")
    period_start = V.req_date(data, "period_start")
    period_end = V.req_date(data, "period_end")
    declared_volume_kg = V.req_number(data, "declared_volume_kg", 3, minimum=0)
    if not period_end > period_start:
        V.fail("period_end must fall strictly after period_start")

    S.holder_or_404(holder_id)
    S.holder_or_404(counterparty_holder_id)
    if user_id != holder_id:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID does not own this certificate holder")

    for existing in ordered(list(S.reports.values())):
        if existing["holder_id"] != holder_id:
            continue
        if existing["counterparty_holder_id"] != counterparty_holder_id:
            continue
        if existing["reconciliation_status"] not in C.RECONCILIATION_STATUSES:
            continue
        other_start = parse_date_str(existing["period_start"])
        other_end = parse_date_str(existing["period_end"])
        if period_start < other_end and other_start < period_end:
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP",
                           "the requested period overlaps report %s" % existing["id"])

    report = {
        "id": new_id(),
        "holder_id": holder_id,
        "counterparty_holder_id": counterparty_holder_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "declared_volume_kg": declared_volume_kg,
        "basis": None,
        "counterparty_volume_kg": vol(0),
        "variance_pct": pct(0),
        "reconciliation_status": "SUBMITTED",
        "reconciled_at": None,
    }
    S.stamp_new(report)
    S.reports[report["id"]] = report
    return created(report)


def _counterparty_volume(report, basis):
    holder_nodes = {n["id"] for n in S.nodes_of(report["holder_id"])}
    counterparty_nodes = {n["id"] for n in S.nodes_of(report["counterparty_holder_id"])}
    period_start = parse_date_str(report["period_start"])
    period_end = parse_date_str(report["period_end"])
    rule = SELLER_BASIS_FILTER if basis == "SELLER_BASIS" else BUYER_BASIS_FILTER

    total = Decimal(0)
    for tx in ordered(list(S.transactions.values())):
        if tx["seller_node_id"] not in holder_nodes:
            continue
        if tx["buyer_node_id"] not in counterparty_nodes:
            continue
        contract_date = parse_date_str(tx["contract_date"])
        if contract_date < period_start or contract_date >= period_end:
            continue
        if tx["verification_status"] not in rule["verification"]:
            continue
        if tx["settlement_status"] not in rule["settlement"]:
            continue
        total += dec(tx["volume_kg"])
    return total


@bp.post("/volume-reports/<report_id>/reconcile")
def reconcile_report(report_id):
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    basis = V.req_enum(data, "basis", C.BASES)
    report = S.report_or_404(report_id)
    if report["reconciliation_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "reconciliation_status is %s" % report["reconciliation_status"])

    counterparty_volume = _counterparty_volume(report, basis)
    counterparty_volume, variance = calc.reconciliation_variance(
        report["declared_volume_kg"], counterparty_volume)
    outcome = calc.reconciliation_outcome(variance)
    if outcome == "EXCEEDED":
        raise ApiError("ERR_VOLUME_VARIANCE_EXCEEDED",
                       "variance of %s%% exceeds the hard cap" % variance)

    report["basis"] = basis
    report["counterparty_volume_kg"] = counterparty_volume
    report["variance_pct"] = variance
    report["reconciliation_status"] = outcome
    report["reconciled_at"] = now_iso()
    touch_once(report)

    if outcome == "VARIANCE_FLAGGED":
        holder = S.holders.get(report["holder_id"])
        if holder is not None and holder["certificate_status"] == "CERTIFIED":
            D.suspend_holder(holder, "VOLUME_VARIANCE")
    return ok(report)


@bp.get("/certificate-holders/<holder_id>/volume-reports")
def list_holder_reports(holder_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative",
              "BrandLicensee")
    status = V.enum_filter("reconciliation_status", C.RECONCILIATION_STATUSES)
    role_in_report = request.args.get("role_in_report")
    side = None
    if role_in_report is not None:
        token = role_in_report.strip().upper()
        if "COUNTER" in token:
            side = "counterparty"
        elif ("FILER" in token or "FILED" in token
                or token in ("HOLDER", "SELF", "OWN", "SELLER", "REPORTER")):
            side = "filer"
        else:
            V.fail("role_in_report must select the filer or the counterparty side")
    S.holder_or_404(holder_id)

    rows = []
    for report in ordered(list(S.reports.values())):
        is_filer = report["holder_id"] == holder_id
        is_counterparty = report["counterparty_holder_id"] == holder_id
        if side == "filer" and not is_filer:
            continue
        if side == "counterparty" and not is_counterparty:
            continue
        if side is None and not (is_filer or is_counterparty):
            continue
        rows.append(report)
    if status:
        rows = [r for r in rows if r["reconciliation_status"] == status]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/volume-reports/<report_id>")
def read_report(report_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative",
              "BrandLicensee")
    return ok(S.report_or_404(report_id))
