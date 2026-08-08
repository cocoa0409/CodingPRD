"""Renewal-application routes — PRD §3.9."""

from flask import Blueprint

import calc
import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_establishment
from envelope import array_response, force, send, watch
from errors import ApiError

bp = Blueprint("renewals", __name__)

READ_ROLES = ["HealthOfficer", "RecordsClerk", "EstablishmentOperator"]


@bp.post("/body-art/renewal-applications")
def create_renewal_application():
    caller = authenticate(["EstablishmentOperator"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    requested_term_start_on = V.req_datetime(data, "requested_term_start_on")
    attested_bbp_current = V.req_bool(data, "attested_bbp_current")
    attested_sterilization_logs_complete = V.req_bool(
        data, "attested_sterilization_logs_complete"
    )
    expedite_requested = V.opt_bool(data, "expedite_requested", False)
    expected_version = V.req_int(data, "expected_establishment_version")

    est = V.get_establishment(establishment_id)
    require_owns_establishment(caller, establishment_id)

    if expected_version != est["version"]:
        raise ApiError("ERR_STALE_ESTABLISHMENT_VERSION")

    for prior in domain.rows_for(
        store.renewal_applications, establishment_id=est["id"]
    ):
        if prior["status"] in ("DRAFT", "SUBMITTED", "DEFICIENT"):
            watch(prior)
            prior["status"] = "SUPERSEDED"

    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "status": "DRAFT",
            "requested_term_start_on": requested_term_start_on,
            "expedite_requested": expedite_requested,
            "attested_bbp_current": attested_bbp_current,
            "attested_sterilization_logs_complete": attested_sterilization_logs_complete,
            "submitted_at": None,
            "artist_count_at_submit": None,
            "fee_estimate_cents": None,
            "fee_final_cents": None,
            "fee_balance_due_cents": 0,
            "fee_paid_cents": 0,
            "fee_refunded_cents": 0,
            "payment_status": "UNPAID",
            "late_fee_applied": False,
            "deficiency_code": None,
            "decided_by_user_id": None,
            "decided_at": None,
            "cycle_count": 0,
        }
    )
    store.renewal_applications[rec["id"]] = rec
    force(est)
    return send(lambda: serialize.renewal_application(rec), 201)


@bp.get("/body-art/renewal-applications/<renewal_application_id>")
def read_renewal_application(renewal_application_id):
    authenticate(READ_ROLES)
    rec = V.get_renewal_application(renewal_application_id)
    return send(lambda: serialize.renewal_application(rec), 200)


@bp.get("/body-art/renewal-applications")
def list_renewal_applications():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    status = V.filter_enum("status", config.RENEWAL_STATUSES)
    payment_status = V.filter_enum("payment_status", config.RENEWAL_PAYMENT_STATUSES)

    rows = store.sorted_rows(store.renewal_applications)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if payment_status is not None:
        rows = [r for r in rows if r["payment_status"] == payment_status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.renewal_application(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/renewal-applications/<renewal_application_id>/submit")
def submit_renewal_application(renewal_application_id):
    caller = authenticate(["EstablishmentOperator"])
    rec = V.get_renewal_application(renewal_application_id)
    require_owns_establishment(caller, rec["establishment_id"])

    if rec["status"] not in ("DRAFT", "DEFICIENT"):
        raise ApiError("ERR_RENEWAL_STATE_INVALID")
    if rec["status"] == "DEFICIENT" and rec["cycle_count"] >= config.RENEWAL_MAX_CYCLES:
        raise ApiError("ERR_RENEWAL_CYCLE_LIMIT")

    est = store.establishments.get(rec["establishment_id"])
    submitted_at = store.now()

    watch(rec)
    rec["status"] = "SUBMITTED"
    rec["submitted_at"] = submitted_at
    rec["deficiency_code"] = None
    rec["artist_count_at_submit"] = est["active_artist_count"] if est else 0
    rec["cycle_count"] += 1
    total, is_late = calc.renewal_fee_total(
        rec["artist_count_at_submit"],
        rec["expedite_requested"],
        est["permit_expires_on"] if est else None,
        submitted_at,
    )
    rec["fee_estimate_cents"] = total
    rec["late_fee_applied"] = is_late
    return send(lambda: serialize.renewal_application(rec), 200)


@bp.post("/body-art/renewal-applications/<renewal_application_id>/payment")
def pay_renewal_application(renewal_application_id):
    caller = authenticate(["EstablishmentOperator", "RecordsClerk"])
    rec = V.get_renewal_application(renewal_application_id)
    data = V.body()
    amount_cents = V.req_int(data, "amount_cents")
    require_owns_establishment(caller, rec["establishment_id"])

    if rec["status"] not in ("SUBMITTED", "DEFICIENT", "APPROVED"):
        raise ApiError("ERR_RENEWAL_STATE_INVALID")

    if rec["status"] == "APPROVED":
        outstanding = rec["fee_balance_due_cents"]
    else:
        outstanding = (rec["fee_estimate_cents"] or 0) - rec["fee_paid_cents"]
    if amount_cents != outstanding:
        raise ApiError("ERR_FEE_AMOUNT_MISMATCH")

    watch(rec)
    rec["fee_paid_cents"] += amount_cents
    rec["payment_status"] = "PAID"
    if rec["fee_final_cents"] is None:
        rec["fee_balance_due_cents"] = 0
    else:
        rec["fee_balance_due_cents"] = max(
            0, rec["fee_final_cents"] - rec["fee_paid_cents"]
        )

    est = store.establishments.get(rec["establishment_id"])
    if est is not None:
        force(est)
        domain.recompute_fees(est)
    return send(lambda: serialize.renewal_application(rec), 200)


@bp.post("/body-art/renewal-applications/<renewal_application_id>/review")
def review_renewal_application(renewal_application_id):
    caller = authenticate(["HealthOfficer"])
    rec = V.get_renewal_application(renewal_application_id)
    data = V.body()
    decision = V.req_enum(data, "decision", config.RENEWAL_DECISIONS)
    deficiency_code = V.opt_enum(data, "deficiency_code", config.DEFICIENCY_CODES)

    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_RENEWAL_STATE_INVALID")

    est = store.establishments.get(rec["establishment_id"])
    decided_at = store.now()

    if decision == "APPROVE":
        if est is not None and est["open_critical_violation_count"] > 0:
            raise ApiError("ERR_OPEN_CRITICAL_VIOLATION_BLOCKS_RENEWAL")
        if est is not None and est["sterilization_compliance_status"] == "NONCOMPLIANT":
            raise ApiError("ERR_STERILIZATION_NONCOMPLIANT")
        if (
            est is not None
            and domain.active_enforcement_for_establishment(est["id"]) is not None
        ):
            raise ApiError("ERR_ACTIVE_ENFORCEMENT_BLOCKS_RENEWAL")
        if not rec["attested_bbp_current"] or not rec[
            "attested_sterilization_logs_complete"
        ]:
            raise ApiError("ERR_RENEWAL_ATTESTATION_MISSING")
        if rec["payment_status"] != "PAID":
            raise ApiError("ERR_RENEWAL_FEE_UNPAID")

        watch(rec)
        rec["status"] = "APPROVED"
        rec["decided_by_user_id"] = caller.user_id
        rec["decided_at"] = decided_at
        total, is_late = calc.renewal_fee_total(
            est["active_artist_count"] if est else 0,
            rec["expedite_requested"],
            est["permit_expires_on"] if est else None,
            decided_at,
        )
        rec["fee_final_cents"] = total
        rec["late_fee_applied"] = is_late
        rec["fee_balance_due_cents"] = max(0, total - rec["fee_paid_cents"])
        if est is not None:
            domain.renew_establishment(est, decided_at)
    elif decision == "MARK_DEFICIENT":
        watch(rec)
        rec["status"] = "DEFICIENT"
        rec["deficiency_code"] = deficiency_code
        rec["decided_by_user_id"] = caller.user_id
        rec["decided_at"] = decided_at
    else:  # DENY
        watch(rec)
        rec["status"] = "DENIED"
        rec["decided_by_user_id"] = caller.user_id
        rec["decided_at"] = decided_at

    return send(lambda: serialize.renewal_application(rec), 200)


@bp.post("/body-art/renewal-applications/<renewal_application_id>/refund")
def refund_renewal_application(renewal_application_id):
    authenticate(["RecordsClerk"])
    rec = V.get_renewal_application(renewal_application_id)

    if rec["payment_status"] != "PAID" or rec["status"] not in (
        "DENIED",
        "SUPERSEDED",
    ):
        raise ApiError("ERR_REFUND_NOT_ALLOWED")

    watch(rec)
    rec["fee_refunded_cents"] = rec["fee_paid_cents"]
    rec["payment_status"] = "REFUNDED"

    est = store.establishments.get(rec["establishment_id"])
    if est is not None:
        force(est)
        domain.recompute_fees(est)
    return send(lambda: serialize.renewal_application(rec), 200)
