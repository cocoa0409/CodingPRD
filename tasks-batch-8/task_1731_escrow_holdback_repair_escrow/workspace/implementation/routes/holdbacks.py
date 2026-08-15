"""Holdback endpoints: create/get/submit/amend/expire/close + scoped lists."""

from datetime import timedelta

from db import store, now, today
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, req_string, opt_string, req_int, opt_int,
    req_bool, opt_bool, req_enum, opt_enum, req_date, opt_date,
    get_file_or_404, get_holdback_or_404, holdback_of_file, work_order_of,
    file_of_holdback, new_entity, touch, append_ledger, rhu_mul_div, rhu_half,
    refresh_file_status,
    ser_holdback, ser_approval, ser_bid, ser_work_order, ser_inspection,
    ser_draw, ser_extension, ser_dispute, ser_pledge, ser_ledger_entry,
    paginated, sorted_default,
)
from middleware import authenticate, authorize, ALL_ROLES
from response import success

from . import bp

FUNDING_SOURCES = {"SELLER_PROCEEDS", "BUYER_DEPOSIT", "SPLIT_EQUAL"}
OVERRUN_RESP = {"BUYER", "SELLER", "SPLIT_EQUAL"}
EXPIRATION_TERMS = {"RETURN_TO_SELLER", "RELEASE_TO_BUYER", "SPLIT_EQUAL"}

_TERM_FIELDS = {
    "repair_scope", "repair_estimate_cents", "contingency_pct", "funding_source",
    "overrun_responsibility", "expiration_terms", "work_deadline_date",
    "hard_stop_date", "exterior_work_flag",
}


def _mk_approval(hb, approver_role):
    a = new_entity()
    a.update({
        "holdback_id": hb["id"],
        "approver_role": approver_role,
        "status": "REQUESTED",
        "approver_user_id": None,
        "holdback_version_at_decision": None,
        "decided_at": None,
        "rejection_reason": None,
    })
    store.approvals[a["id"]] = a
    return a


@bp.post("/escrow/holdbacks")
def create_holdback():
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    data = get_body()
    # Ladder rung 3 (existence) for the body-referenced parent, when usable.
    raw_fid = data.get("escrow_file_id")
    if isinstance(raw_fid, str) and raw_fid not in store.files:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found: %s" % raw_fid)
    # Rung 4: input shape.
    check_allowed_fields(data, {"escrow_file_id"} | _TERM_FIELDS)
    fid = req_string(data, "escrow_file_id")
    f = get_file_or_404(fid)
    scope = req_string(data, "repair_scope")
    estimate = req_int(data, "repair_estimate_cents", lo=1)
    pct = req_int(data, "contingency_pct", lo=10, hi=25)
    funding = req_enum(data, "funding_source", FUNDING_SOURCES)
    overrun = req_enum(data, "overrun_responsibility", OVERRUN_RESP)
    expiry = req_enum(data, "expiration_terms", EXPIRATION_TERMS)
    wd = req_date(data, "work_deadline_date")
    hs = req_date(data, "hard_stop_date")
    ext_flag = req_bool(data, "exterior_work_flag")
    if wd > hs:
        raise ApiError("ERR_VALIDATION", "work_deadline_date must be on or before hard_stop_date")
    # Rung 10: one holdback per escrow file.
    if holdback_of_file(fid) is not None:
        raise ApiError("ERR_HOLDBACK_ALREADY_EXISTS", "The escrow file already has a holdback")

    amount = rhu_mul_div(estimate, 100 + pct, 100)
    hb = new_entity()
    hb.update({
        "escrow_file_id": fid,
        "repair_scope": scope,
        "repair_estimate_cents": estimate,
        "contingency_pct": pct,
        "holdback_amount_cents": amount,
        "commitment_basis_cents": None,
        "funding_source": funding,
        "overrun_responsibility": overrun,
        "expiration_terms": expiry,
        "work_deadline_date": wd,
        "hard_stop_date": hs,
        "exterior_work_flag": ext_flag,
        "granted_extension_days": 0,
        "effective_deadline_date": wd,
        "lender_approval_required": True,
        "insurer_approval_required": f["insurer_user_id"] is not None,
        "selected_bid_id": None,
        "status": "DRAFT",
        "trust_balance_cents": 0,
        "reserved_cents": 0,
        "total_disbursed_cents": 0,
        "total_shortfall_deposited_cents": 0,
        "work_verified": False,
        "disbursement_frozen": False,
        "closeout_status": "NOT_READY",
        "disposition_override": None,
    })
    store.holdbacks[hb["id"]] = hb
    # Funds are withheld at creation: FUNDING entry is ledger seq 1.
    append_ledger(hb, "FUNDING", amount, "Initial holdback funding withheld at creation")
    return success(ser_holdback(hb), response_type="object", status=201)


@bp.get("/escrow/holdbacks/<hid>")
def get_holdback(hid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    hb = get_holdback_or_404(hid)
    return success(ser_holdback(hb), response_type="object", status=200)


@bp.post("/escrow/holdbacks/<hid>/submit")
def submit_holdback(hid):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    hb = get_holdback_or_404(hid)
    data = get_body()
    check_allowed_fields(data, set())
    if hb["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT holdback can be submitted")
    hb["status"] = "PENDING_APPROVALS"
    _mk_approval(hb, "LENDER")
    if hb["insurer_approval_required"]:
        _mk_approval(hb, "INSURER")
    touch(hb)
    return success(ser_holdback(hb), response_type="object", status=200)


@bp.post("/escrow/holdbacks/<hid>/amend")
def amend_holdback(hid):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    hb = get_holdback_or_404(hid)
    data = get_body()
    # Rung 4: input shape (merged term validation).
    check_allowed_fields(data, {"expected_holdback_version"} | _TERM_FIELDS)
    expected = req_int(data, "expected_holdback_version")
    new_scope = opt_string(data, "repair_scope", hb["repair_scope"])
    new_estimate = opt_int(data, "repair_estimate_cents", lo=1, default=hb["repair_estimate_cents"])
    new_pct = opt_int(data, "contingency_pct", lo=10, hi=25, default=hb["contingency_pct"])
    new_funding = opt_enum(data, "funding_source", FUNDING_SOURCES, hb["funding_source"])
    new_overrun = opt_enum(data, "overrun_responsibility", OVERRUN_RESP, hb["overrun_responsibility"])
    new_expiry = opt_enum(data, "expiration_terms", EXPIRATION_TERMS, hb["expiration_terms"])
    new_wd = opt_date(data, "work_deadline_date", hb["work_deadline_date"])
    new_hs = opt_date(data, "hard_stop_date", hb["hard_stop_date"])
    new_flag = opt_bool(data, "exterior_work_flag", hb["exterior_work_flag"])
    if new_wd > new_hs:
        raise ApiError("ERR_VALIDATION", "work_deadline_date must be on or before hard_stop_date")
    # Rung 6: optimistic concurrency (before the state precondition per ladder).
    if expected != hb["version"]:
        raise ApiError("ERR_STALE_VERSION", "Holdback version has advanced; amend rejected")
    # Rung 7: amendment only from DRAFT or PENDING_APPROVALS.
    if hb["status"] not in ("DRAFT", "PENDING_APPROVALS"):
        raise ApiError("ERR_INVALID_STATE", "Holdback can be amended only in DRAFT or PENDING_APPROVALS")

    hb["repair_scope"] = new_scope
    hb["repair_estimate_cents"] = new_estimate
    hb["contingency_pct"] = new_pct
    hb["funding_source"] = new_funding
    hb["overrun_responsibility"] = new_overrun
    hb["expiration_terms"] = new_expiry
    hb["work_deadline_date"] = new_wd
    hb["hard_stop_date"] = new_hs
    hb["exterior_work_flag"] = new_flag
    hb["holdback_amount_cents"] = rhu_mul_div(new_estimate, 100 + new_pct, 100)
    hb["effective_deadline_date"] = new_wd + timedelta(days=hb["granted_extension_days"])

    # Funding delta ledger entry against what the trust currently holds.
    delta = hb["holdback_amount_cents"] - hb["trust_balance_cents"]
    if delta > 0:
        append_ledger(hb, "FUNDING", delta, "Amendment funding top-up")
    elif delta < 0:
        append_ledger(hb, "REFUND_TO_SOURCE", delta, "Amendment refund to funding source")

    if hb["status"] == "PENDING_APPROVALS":
        # Stale the live approval set; re-approval required after resubmission.
        for a in store.approvals.values():
            if a["holdback_id"] == hb["id"] and a["status"] in ("REQUESTED", "APPROVED"):
                a["status"] = "STALE"
                touch(a)
        hb["status"] = "DRAFT"
    touch(hb)
    return success(ser_holdback(hb), response_type="object", status=200)


@bp.post("/escrow/holdbacks/<hid>/expire")
def expire_holdback(hid):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    hb = get_holdback_or_404(hid)
    data = get_body()
    check_allowed_fields(data, set())
    # Rung 7: generic state preconditions (ACTIVE from-state; work unverified).
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE holdback can be expired")
    if hb["work_verified"]:
        raise ApiError("ERR_INVALID_STATE", "Verified work must be closed, not expired")
    # Rung 14: clock date strictly after the effective deadline; equality does not expire.
    if not (today() > hb["effective_deadline_date"]):
        raise ApiError("ERR_NOT_EXPIRED", "Holdback has not passed its effective deadline")

    hb["status"] = "EXPIRED"
    for d in store.draws.values():
        if d["holdback_id"] == hid and d["status"] == "SUBMITTED":
            d["status"] = "CANCELLED"
            touch(d)
    for i in store.inspections.values():
        if i["holdback_id"] == hid and i["status"] == "PLANNED":
            i["status"] = "CANCELLED"
            touch(i)
    for e in store.extensions.values():
        if e["holdback_id"] == hid and e["status"] == "PENDING":
            e["status"] = "CANCELLED"
            touch(e)
    touch(hb)
    return success(ser_holdback(hb), response_type="object", status=200)


def _run_close_waterfall(hb, completed):
    # Step 1: pay each APPROVED draw, approved_at ASC, tie created_at ASC.
    approved = [
        d for d in store.draws.values()
        if d["holdback_id"] == hb["id"] and d["status"] == "APPROVED"
    ]
    approved.sort(key=lambda d: (d["approved_at"], d["created_at"], d["_ix"]))
    for d in approved:
        append_ledger(hb, "DRAW_DEBIT", -d["amount_cents"],
                      "Closing disbursement of approved draw %s" % d["id"])
        hb["total_disbursed_cents"] += d["amount_cents"]
        hb["reserved_cents"] -= d["amount_cents"]
        d["status"] = "PAID"
        d["paid_at"] = now()
        touch(d)
    # Step 2: remainder after draw payments.
    remainder = hb["trust_balance_cents"]
    if remainder != 0:
        # Step 3: disposition basis.
        if completed:
            basis = hb["funding_source"]
        else:
            basis = hb["disposition_override"] or hb["expiration_terms"]
        if basis in ("RETURN_TO_SELLER", "SELLER_PROCEEDS"):
            append_ledger(hb, "RETURN_TO_SELLER", -remainder,
                          "Remainder returned to seller at close")
        elif basis in ("RELEASE_TO_BUYER", "BUYER_DEPOSIT"):
            append_ledger(hb, "RELEASE_TO_BUYER", -remainder,
                          "Remainder released to buyer at close")
        else:  # SPLIT_EQUAL: seller rounded half-up first, buyer residual.
            seller_share = rhu_half(remainder)
            buyer_share = remainder - seller_share
            append_ledger(hb, "RETURN_TO_SELLER", -seller_share,
                          "Seller split share of remainder at close")
            append_ledger(hb, "RELEASE_TO_BUYER", -buyer_share,
                          "Buyer residual share of remainder at close")


@bp.post("/escrow/holdbacks/<hid>/close")
def close_holdback(hid):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    hb = get_holdback_or_404(hid)
    data = get_body()
    check_allowed_fields(data, set())
    # Rung 7: close runs from ACTIVE or EXPIRED only.
    if hb["status"] not in ("ACTIVE", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE or EXPIRED holdback can be closed")
    # Rung 16: closeout aggregate.
    if hb["status"] == "ACTIVE":
        if hb["closeout_status"] != "READY_TO_CLOSE":
            raise ApiError("ERR_CLOSE_NOT_READY", "Holdback is not ready to close")
    else:
        has_open_dispute = any(
            d["status"] == "OPEN" for d in store.disputes.values() if d["holdback_id"] == hid
        )
        has_pledged = any(
            p["status"] == "PLEDGED" for p in store.pledges.values() if p["holdback_id"] == hid
        )
        if has_open_dispute or has_pledged:
            raise ApiError("ERR_CLOSE_NOT_READY", "Open dispute or unfunded pledge blocks close")

    completed = hb["status"] == "ACTIVE"
    _run_close_waterfall(hb, completed)
    hb["status"] = "CLOSED_COMPLETED" if completed else "CLOSED_EXPIRED"
    touch(hb)
    f = file_of_holdback(hb)
    if f is not None:
        refresh_file_status(f)
    return success(ser_holdback(hb), response_type="object", status=200)


# ---------------------------------------------------------------------------
# Holdback-scoped list endpoints (all roles; created_at ASC, insertion order)
# ---------------------------------------------------------------------------

def _list_for_holdback(hid, table, serializer, sort_key=None):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    get_holdback_or_404(hid)
    items = [e for e in table.values() if e["holdback_id"] == hid]
    if sort_key is not None:
        items.sort(key=sort_key)
    else:
        items = sorted_default(items)
    return paginated(items, serializer)


@bp.get("/escrow/holdbacks/<hid>/approvals")
def list_approvals(hid):
    # created_at ASC, ties broken by approver_role ASC.
    return _list_for_holdback(
        hid, store.approvals, ser_approval,
        sort_key=lambda a: (a["created_at"], a["approver_role"], a["_ix"]),
    )


@bp.get("/escrow/holdbacks/<hid>/bids")
def list_bids(hid):
    return _list_for_holdback(hid, store.bids, ser_bid)


@bp.get("/escrow/holdbacks/<hid>/work-orders")
def list_work_orders(hid):
    return _list_for_holdback(hid, store.work_orders, ser_work_order)


@bp.get("/escrow/holdbacks/<hid>/inspections")
def list_inspections(hid):
    return _list_for_holdback(hid, store.inspections, ser_inspection)


@bp.get("/escrow/holdbacks/<hid>/draw-requests")
def list_draw_requests(hid):
    return _list_for_holdback(hid, store.draws, ser_draw)


@bp.get("/escrow/holdbacks/<hid>/extension-requests")
def list_extension_requests(hid):
    return _list_for_holdback(hid, store.extensions, ser_extension)


@bp.get("/escrow/holdbacks/<hid>/disputes")
def list_disputes(hid):
    return _list_for_holdback(hid, store.disputes, ser_dispute)


@bp.get("/escrow/holdbacks/<hid>/shortfall-pledges")
def list_shortfall_pledges(hid):
    return _list_for_holdback(hid, store.pledges, ser_pledge)


@bp.get("/escrow/holdbacks/<hid>/ledger-entries")
def list_ledger_entries(hid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    get_holdback_or_404(hid)
    items = sorted(store.ledger_by_hb.get(hid, []), key=lambda e: e["seq"])
    return paginated(items, ser_ledger_entry)
