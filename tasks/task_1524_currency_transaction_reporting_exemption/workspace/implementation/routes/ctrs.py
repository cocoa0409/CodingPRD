"""CTR lifecycle endpoints: validate, return-to-draft, file, amend, acknowledge."""
from flask import Blueprint, request

from db import (
    AMENDMENT_WINDOW_DAYS,
    CTR_THRESHOLD_CENTS,
    due_instant_end,
    now,
    now_iso,
    parse_date_strict,
    stamp_new,
    store,
    today,
    touch,
)
from errors import (
    ERR_AMENDMENT_WINDOW_EXPIRED,
    ERR_CTR_INCOMPLETE,
    ERR_CTR_NOT_AMENDABLE,
    ERR_CTR_NOT_FOUND,
    ERR_CTR_SNAPSHOT_STALE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ApiError,
)
from middleware import authenticate, body, f_enum, f_str, f_version, sorted_page
from response import ok, ok_list
from serializers import serialize_ctr
from services.audit import add_fx, main_event
from services.domain import create_ctr
from datetime import timedelta

bp = Blueprint("ctrs", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]


def get_ctr_or_404(ctr_id):
    c = store.ctrs.get(ctr_id)
    if c is None:
        raise ApiError(ERR_CTR_NOT_FOUND, "CTR not found", 404)
    return c


def current_totals(ctr):
    row = store.aggregations.get((ctr["customer_id"], ctr["business_date"]))
    if row is None:
        return 0, 0
    return row["total_cash_in_cents"], row["total_cash_out_cents"]


@bp.get("/ctrs")
def list_ctrs():
    authenticate(ALL_ROLES)
    items = list(store.ctrs.values())
    for param in ("customer_id", "business_date", "status", "prior_ctr_id"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_ctr(c) for c in page], limit, offset, total)


@bp.get("/ctrs/<ctr_id>")
def get_ctr(ctr_id):
    authenticate(ALL_ROLES)
    return ok(serialize_ctr(get_ctr_or_404(ctr_id)))


@bp.post("/ctrs/<ctr_id>/validate")
def validate_ctr(ctr_id):
    authenticate(["ComplianceAnalyst"])
    from flask import g

    ctr = get_ctr_or_404(ctr_id)
    if ctr["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "CTR is not in DRAFT status", 409)
    # Completeness: customer TIN present and the (live) snapshot exceeds the
    # reporting threshold on at least one side.
    customer = store.customers.get(ctr["customer_id"])
    snap_in, snap_out = current_totals(ctr)
    tin_ok = customer is not None and customer.get("tin") is not None
    threshold_ok = snap_in > CTR_THRESHOLD_CENTS or snap_out > CTR_THRESHOLD_CENTS
    if not tin_ok or not threshold_ok:
        raise ApiError(
            ERR_CTR_INCOMPLETE,
            "CTR validation failed: customer TIN missing or snapshot does not exceed the reporting threshold",
            422,
        )
    before = serialize_ctr(ctr)
    ctr["status"] = "VALIDATED"
    ctr["validated_by_id"] = g.user_id
    # Snapshot freezes at validation.
    ctr["snapshot_cash_in_cents"] = snap_in
    ctr["snapshot_cash_out_cents"] = snap_out
    touch(ctr)
    main_event("POST /ctrs/{id}/validate", "CTR", ctr["id"], before, serialize_ctr(ctr))
    return ok(serialize_ctr(ctr))


@bp.post("/ctrs/<ctr_id>/return-to-draft")
def return_ctr_to_draft(ctr_id):
    authenticate(["ComplianceAnalyst"])
    ctr = get_ctr_or_404(ctr_id)
    if ctr["status"] != "VALIDATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "CTR is not in VALIDATED status", 409)
    before = serialize_ctr(ctr)
    ctr["status"] = "DRAFT"
    ctr["validated_by_id"] = None
    # Snapshot refreshes from the current aggregation.
    snap_in, snap_out = current_totals(ctr)
    ctr["snapshot_cash_in_cents"] = snap_in
    ctr["snapshot_cash_out_cents"] = snap_out
    touch(ctr)
    main_event(
        "POST /ctrs/{id}/return-to-draft", "CTR", ctr["id"], before, serialize_ctr(ctr)
    )
    return ok(serialize_ctr(ctr))


@bp.post("/ctrs/<ctr_id>/file")
def file_ctr(ctr_id):
    authenticate(["BSAOfficer"])
    from flask import g

    b = body()
    filing_channel = f_enum(b, "filing_channel", ("EFILE", "PAPER"))
    ctr = get_ctr_or_404(ctr_id)
    if ctr["status"] != "VALIDATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "CTR is not in VALIDATED status", 409)
    # Segregation of duties: filer must differ from validator.
    if g.user_id == ctr["validated_by_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The filing officer must differ from the validating analyst",
            422,
        )
    # Fiscal consistency: frozen snapshot must equal current aggregation totals.
    snap_in, snap_out = current_totals(ctr)
    if (
        ctr["snapshot_cash_in_cents"] != snap_in
        or ctr["snapshot_cash_out_cents"] != snap_out
    ):
        raise ApiError(
            ERR_CTR_SNAPSHOT_STALE,
            "The frozen snapshot no longer equals current aggregation totals",
            422,
        )
    before = serialize_ctr(ctr)
    filed_at = now()
    due = ctr["due_date_efile"] if filing_channel == "EFILE" else ctr["due_date_paper"]
    ctr["status"] = "FILED"
    ctr["filed_at"] = now_iso()
    ctr["filed_by_id"] = g.user_id
    ctr["filing_channel"] = filing_channel
    # Late exactly when filed strictly after 23:59:59.999 UTC on the due date;
    # filing on the due date itself is timely.
    ctr["filed_late"] = filed_at > due_instant_end(due)
    touch(ctr)
    main_event("POST /ctrs/{id}/file", "CTR", ctr["id"], before, serialize_ctr(ctr))
    return ok(serialize_ctr(ctr))


@bp.post("/ctrs/<ctr_id>/amendments")
def amend_ctr(ctr_id):
    authenticate(["BSAOfficer"])
    b = body()
    amendment_reason = f_str(b, "amendment_reason")
    expected = f_version(b, "expected_ctr_version")
    ctr = get_ctr_or_404(ctr_id)
    # OCC before state checks.
    if expected != ctr["version"]:
        raise ApiError(ERR_STALE_VERSION, "CTR version mismatch", 412)
    if ctr["status"] not in ("FILED", "ACKNOWLEDGED", "AMENDMENT_REQUIRED"):
        raise ApiError(
            ERR_CTR_NOT_AMENDABLE,
            "CTR is not in FILED, ACKNOWLEDGED, or AMENDMENT_REQUIRED status",
            409,
        )
    bd = parse_date_strict(ctr["business_date"])
    if bd is None or today() > bd + timedelta(days=AMENDMENT_WINDOW_DAYS):
        raise ApiError(
            ERR_AMENDMENT_WINDOW_EXPIRED,
            "Amendment is permitted only within 45 days of the business date",
            422,
        )
    before = serialize_ctr(ctr)
    ctr["status"] = "SUPERSEDED"
    touch(ctr)
    successor = create_ctr(
        ctr["customer_id"],
        ctr["business_date"],
        "CORRECTION",
        ctr["id"],
        amendment_reason,
    )
    add_fx({
        "type": "ctr_superseded",
        "ctr_id": ctr["id"],
        "successor_ctr_id": successor["id"],
    })
    main_event(
        "POST /ctrs/{id}/amendments", "CTR", successor["id"], before,
        serialize_ctr(successor),
    )
    return ok(serialize_ctr(successor), status=201)


@bp.post("/ctrs/<ctr_id>/acknowledge")
def acknowledge_ctr(ctr_id):
    authenticate(["SystemAdmin"])
    b = body()
    regulator_tracking_id = f_str(b, "regulator_tracking_id")
    ctr = get_ctr_or_404(ctr_id)
    if ctr["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "CTR is not in FILED status", 409)
    before = serialize_ctr(ctr)
    ctr["status"] = "ACKNOWLEDGED"
    ctr["acknowledged_at"] = now_iso()
    ctr["regulator_tracking_id"] = regulator_tracking_id
    touch(ctr)
    main_event(
        "POST /ctrs/{id}/acknowledge", "CTR", ctr["id"], before, serialize_ctr(ctr)
    )
    return ok(serialize_ctr(ctr))
