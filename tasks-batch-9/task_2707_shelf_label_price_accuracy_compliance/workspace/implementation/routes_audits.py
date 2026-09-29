"""Scanner audits, scan lines and promotional signage."""
from datetime import timedelta
from fractions import Fraction

from flask import Blueprint

import calc
import services
import views
from auth import actor, roles
from core import (
    AISLE_AUDIT_COOLDOWN_MINUTES,
    AUDIT_OUTCOMES,
    AUDIT_STATUSES,
    AUDIT_TYPES,
    CLASSIFICATIONS,
    DB,
    RATE_VARIANTS,
    R_COMPLIANCE_OFFICER,
    R_CUSTOMER_SERVICE_DESK,
    R_LABEL_ASSOCIATE,
    R_PRICE_AUDITOR,
    R_PRICING_ADMIN,
    R_STORE_MANAGER,
    SIGNAGE_COMPLIANCE_STATES,
    SIGNAGE_STATUSES,
    apply_changes,
    arg_bool,
    arg_enum,
    arg_str,
    body,
    fail,
    insert,
    must,
    now,
    ok,
    opt_bool,
    opt_enum,
    opt_str,
    opt_str_array,
    pagination,
    req_dt,
    req_enum,
    req_int,
    req_str,
    req_str_array,
    rows,
    touch,
)

bp = Blueprint("audits", __name__)


def require_certified():
    """Priority 51 — the acting associate must be currently certified."""
    me = actor()
    if me is None:
        return None
    if (
        me["training_status"] != "CERTIFIED"
        or me["certification_expires_at"] is None
        or not me["certification_expires_at"] > now()
    ):
        fail("ERR_ASSOCIATE_NOT_CERTIFIED", "the acting associate is not currently certified")
    return me


# ---------------------------------------------------------------- audits
@bp.post("/price-integrity/scanner-audits")
@roles(R_PRICE_AUDITOR, R_COMPLIANCE_OFFICER)
def create_audit():
    data = body()
    store_id = req_str(data, "store_id")
    aisle_id = req_str(data, "aisle_id")
    auditor_associate_id = req_str(data, "auditor_associate_id")
    audit_type = req_enum(data, "audit_type", AUDIT_TYPES)
    window_start = req_dt(data, "scan_window_start")
    window_end = req_dt(data, "scan_window_end")
    # priority 32 — body references, in declared input order
    store = must("stores", store_id)
    aisle = must("aisles", aisle_id)
    auditor = must("associates", auditor_associate_id)
    # priority 51 — actor certification
    require_certified()
    # priority 52 — ROUTINE audits are blocked while the store is FROZEN
    if audit_type == "ROUTINE" and store["compliance_posture"] == "FROZEN":
        fail("ERR_STORE_POSTURE_BLOCKED", "the store is frozen")
    # priority 58 — well-formed interval
    if not window_start < window_end:
        fail("ERR_INVALID_WINDOW", "scan_window_start must precede scan_window_end")
    # priority 60 — aisle occupation with a 60-minute cooldown
    cooldown = timedelta(minutes=AISLE_AUDIT_COOLDOWN_MINUTES)
    for other in rows("scanner_audits"):
        if other["aisle_id"] != aisle_id or other["status"] == "CLOSED":
            continue
        if window_start < other["scan_window_end"] + cooldown and (
            other["scan_window_start"] < window_end
        ):
            fail("ERR_AISLE_AUDIT_WINDOW_CONFLICT", "the aisle is already occupied")
    # priority 66 — aisle/store agreement
    if aisle["store_id"] != store["id"]:
        fail("ERR_AISLE_STORE_MISMATCH", "the aisle belongs to another store")
    # priority 67 — associate/store agreement
    if auditor["store_id"] != store["id"]:
        fail("ERR_ASSOCIATE_STORE_MISMATCH", "the auditor belongs to another store")
    audit = insert(
        "scanner_audits",
        {
            "store_id": store["id"],
            "aisle_id": aisle["id"],
            "auditor_associate_id": auditor["id"],
            "audit_type": audit_type,
            "scan_window_start": window_start,
            "scan_window_end": window_end,
            "status": "OPEN",
            "outcome": "PENDING",
            "gross_error_rate_pct": None,
            "net_overcharge_rate_pct": None,
            "error_rate_pct": None,
            "rate_variant_applied": None,
            "closed_at": None,
            "reopen_count": 0,
        },
    )
    return ok(views.scanner_audit(audit), 201)


@bp.get("/price-integrity/scanner-audits/<aid>")
@roles(
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_PRICE_AUDITOR,
    R_CUSTOMER_SERVICE_DESK,
)
def get_audit(aid):
    return ok(views.scanner_audit(must("scanner_audits", aid)))


@bp.get("/price-integrity/scanner-audits")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER, R_PRICE_AUDITOR)
def list_audits():
    store_id = arg_str("store_id")
    aisle_id = arg_str("aisle_id")
    auditor_associate_id = arg_str("auditor_associate_id")
    status = arg_enum("status", AUDIT_STATUSES)
    outcome = arg_enum("outcome", AUDIT_OUTCOMES)
    audit_type = arg_enum("audit_type", AUDIT_TYPES)
    limit, offset = pagination()
    items = [
        r
        for r in rows("scanner_audits")
        if (store_id is None or r["store_id"] == store_id)
        and (aisle_id is None or r["aisle_id"] == aisle_id)
        and (
            auditor_associate_id is None
            or r["auditor_associate_id"] == auditor_associate_id
        )
        and (status is None or r["status"] == status)
        and (outcome is None or r["outcome"] == outcome)
        and (audit_type is None or r["audit_type"] == audit_type)
    ]
    return views.paged(items, views.scanner_audit, limit, offset)


# ---------------------------------------------------------------- scan lines
@bp.post("/price-integrity/scanner-audits/<aid>/scan-lines")
@roles(R_PRICE_AUDITOR)
def create_scan_line(aid):
    data = body()
    item_upc = req_str(data, "item_upc", 8, 14, r"\d{8,14}")
    shelf_price_cents = req_int(data, "shelf_price_cents", 0)
    register_price_cents = req_int(data, "register_price_cents", 0)
    audit = must("scanner_audits", aid)
    # priority 40 — only OPEN, SCANNING or REOPENED audits accept evidence
    if audit["status"] == "CLOSED":
        fail("ERR_AUDIT_INVALID_STATE", "a closed audit accepts no further evidence")
    # priority 51 — actor certification
    require_certified()
    # priority 63 — one UPC per audit
    if any(
        r["scanner_audit_id"] == aid and r["item_upc"] == item_upc
        for r in DB["scan_lines"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "the UPC was already scanned in this audit")
    aisle = DB["aisles"][audit["aisle_id"]]
    variance = register_price_cents - shelf_price_cents
    if variance == 0:
        classification = "MATCH"
    elif variance > 0:
        classification = "OVERCHARGE"
    else:
        classification = "UNDERCHARGE"
    line = insert(
        "scan_lines",
        {
            "scanner_audit_id": audit["id"],
            "item_upc": item_upc,
            "shelf_price_cents": shelf_price_cents,
            "register_price_cents": register_price_cents,
            "variance_cents": variance,
            "classification": classification,
            "category_code": aisle["category_code"],
        },
        audit=False,
    )
    if audit["status"] in ("OPEN", "REOPENED"):
        apply_changes(audit, {"status": "SCANNING"})
    return ok(views.scan_line(line), 201)


@bp.get("/price-integrity/scan-lines/<sid>")
@roles(
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_PRICE_AUDITOR,
    R_CUSTOMER_SERVICE_DESK,
)
def get_scan_line(sid):
    return ok(views.scan_line(must("scan_lines", sid)))


@bp.get("/price-integrity/scanner-audits/<aid>/scan-lines")
@roles(
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_PRICE_AUDITOR,
    R_CUSTOMER_SERVICE_DESK,
)
def list_scan_lines(aid):
    classification = arg_enum("classification", CLASSIFICATIONS)
    limit, offset = pagination()
    must("scanner_audits", aid)
    items = [
        r
        for r in rows("scan_lines")
        if r["scanner_audit_id"] == aid
        and (classification is None or r["classification"] == classification)
    ]
    return views.paged(items, views.scan_line, limit, offset)


# ---------------------------------------------------------------- close / reopen
@bp.post("/price-integrity/scanner-audits/<aid>/close")
@roles(R_PRICE_AUDITOR, R_COMPLIANCE_OFFICER)
def close_audit(aid):
    data = body()
    rate_variant = opt_enum(data, "rate_variant", RATE_VARIANTS)
    audit = must("scanner_audits", aid)
    # priority 41 — a second close is a repeat transition
    if audit["status"] == "CLOSED":
        fail("ERR_TRANSITION_ALREADY_APPLIED", "the audit is already closed")
    # priority 40 — an OPEN audit falls through to the empty-sample rule below
    if audit["status"] not in ("OPEN", "SCANNING", "REOPENED"):
        fail("ERR_AUDIT_INVALID_STATE", "the audit cannot be closed from this state")
    # priority 51 — actor certification
    require_certified()
    sample, over, under = services.audit_counts(audit["id"])
    # priority 63 — empty sample
    if sample < 1:
        fail("ERR_AUDIT_SAMPLE_EMPTY", "the audit has no scan lines")
    store = DB["stores"][audit["store_id"]]
    juris = services.jurisdiction_of_store(store)
    gross, net = calc.error_rates(sample, over, under)
    variant = rate_variant or juris["default_rate_variant"]
    applied = gross if variant == "GROSS_MISMATCH" else net
    threshold = juris["scanner_error_rate_threshold_pct"]
    outcome = (
        "FAIL" if Fraction(str(applied)) >= Fraction(str(threshold)) else "PASS"
    )
    apply_changes(
        audit,
        {
            "gross_error_rate_pct": gross,
            "net_overcharge_rate_pct": net,
            "rate_variant_applied": variant,
            "error_rate_pct": applied,
            "outcome": outcome,
            "status": "CLOSED",
            "closed_at": now(),
        },
    )
    touch(audit)
    aisle = DB["aisles"][audit["aisle_id"]]
    apply_changes(aisle, {"last_audit_closed_at": now()})
    if outcome == "FAIL":
        services.audit_failure_cascade(audit, juris)
    services.recompute_store(store)
    return ok(views.scanner_audit(audit))


@bp.post("/price-integrity/scanner-audits/<aid>/reopen")
@roles(R_COMPLIANCE_OFFICER)
def reopen_audit(aid):
    data = body()
    req_str(data, "reopen_reason", 1, 500)
    audit = must("scanner_audits", aid)
    # priority 40 — only a CLOSED audit reopens, and never once adjudicated
    if audit["status"] != "CLOSED":
        fail("ERR_AUDIT_INVALID_STATE", "only a closed audit can be reopened")
    for inspection in services.inspections_for_audit(audit["id"]):
        if inspection["status"] == "CLOSED":
            fail("ERR_AUDIT_INVALID_STATE", "the evidence has already been adjudicated")
    apply_changes(
        audit,
        {
            "status": "REOPENED",
            "outcome": "PENDING",
            "error_rate_pct": None,
            "rate_variant_applied": None,
            "gross_error_rate_pct": None,
            "net_overcharge_rate_pct": None,
            "closed_at": None,
            "reopen_count": audit["reopen_count"] + 1,
        },
    )
    services.recompute_store(DB["stores"][audit["store_id"]])
    return ok(views.scanner_audit(audit))


# ---------------------------------------------------------------- signage
@bp.post("/price-integrity/promo-signage")
@roles(R_STORE_MANAGER, R_PRICING_ADMIN)
def create_signage():
    data = body()
    store_id = req_str(data, "store_id")
    aisle_id = req_str(data, "aisle_id")
    sign_code = req_str(data, "sign_code", 1, 24)
    promo_start_at = req_dt(data, "promo_start_at")
    promo_end_at = req_dt(data, "promo_end_at")
    disclosure_codes = req_str_array(data, "disclosure_codes", 0, None, True, 1)
    price_change_line_id = opt_str(data, "price_change_line_id")
    # priority 32 — body references, in declared input order
    store = must("stores", store_id)
    aisle = must("aisles", aisle_id)
    if price_change_line_id is not None:
        must("price_change_lines", price_change_line_id)
    # priority 58 — well-formed interval
    if not promo_start_at < promo_end_at:
        fail("ERR_INVALID_WINDOW", "promo_start_at must precede promo_end_at")
    # priority 63 — one sign_code per store
    if any(
        r["store_id"] == store_id and r["sign_code"] == sign_code
        for r in DB["promo_signage"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "sign_code already used in this store")
    # priority 66 — aisle/store agreement
    if aisle["store_id"] != store["id"]:
        fail("ERR_AISLE_STORE_MISMATCH", "the aisle belongs to another store")
    juris = services.jurisdiction_of_store(store)
    draft = {
        "store_id": store["id"],
        "aisle_id": aisle["id"],
        "price_change_line_id": price_change_line_id,
        "sign_code": sign_code,
        "promo_start_at": promo_start_at,
        "promo_end_at": promo_end_at,
        "disclosure_codes": disclosure_codes,
        "status": "DRAFT",
        "posted_at": None,
        "removed_at": None,
    }
    draft["missing_disclosure_codes"] = calc.missing_disclosures(draft, juris)
    draft["compliance_state"] = calc.signage_compliance_state("DRAFT")
    return ok(views.promo_signage(insert("promo_signage", draft)), 201)


@bp.get("/price-integrity/promo-signage/<gid>")
@roles(
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_LABEL_ASSOCIATE,
    R_PRICE_AUDITOR,
)
def get_signage(gid):
    return ok(views.promo_signage(must("promo_signage", gid)))


@bp.get("/price-integrity/promo-signage")
@roles(
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_LABEL_ASSOCIATE,
    R_PRICE_AUDITOR,
)
def list_signage():
    store_id = arg_str("store_id")
    aisle_id = arg_str("aisle_id")
    price_change_line_id = arg_str("price_change_line_id")
    status = arg_enum("status", SIGNAGE_STATUSES)
    compliance_state = arg_enum("compliance_state", SIGNAGE_COMPLIANCE_STATES)
    limit, offset = pagination()
    items = [
        r
        for r in rows("promo_signage")
        if (store_id is None or r["store_id"] == store_id)
        and (aisle_id is None or r["aisle_id"] == aisle_id)
        and (
            price_change_line_id is None
            or r["price_change_line_id"] == price_change_line_id
        )
        and (status is None or r["status"] == status)
        and (compliance_state is None or r["compliance_state"] == compliance_state)
    ]
    return views.paged(items, views.promo_signage, limit, offset)


@bp.post("/price-integrity/promo-signage/<gid>/post")
@roles(R_STORE_MANAGER, R_LABEL_ASSOCIATE)
def post_signage(gid):
    data = body()
    override_acknowledged = opt_bool(data, "override_acknowledged", False)
    sign = must("promo_signage", gid)
    # priority 41 — a second post is a repeat transition
    if sign["status"] == "POSTED":
        fail("ERR_TRANSITION_ALREADY_APPLIED", "the sign is already posted")
    # priority 40 — only a DRAFT sign, and only while the promotion still runs
    if sign["status"] != "DRAFT":
        fail("ERR_SIGNAGE_INVALID_STATE", "only a draft sign can be posted")
    if not now() < sign["promo_end_at"]:
        fail("ERR_SIGNAGE_INVALID_STATE", "the promotion has already ended")
    store = DB["stores"][sign["store_id"]]
    # priority 52 — posture gate
    if store["compliance_posture"] == "FROZEN":
        fail("ERR_STORE_POSTURE_BLOCKED", "the store is frozen")
    if store["compliance_posture"] == "RESTRICTED" and not (
        override_acknowledged and sign["price_change_line_id"] is not None
    ):
        fail("ERR_STORE_POSTURE_BLOCKED", "the store is restricted")
    # priority 62 — required disclosures
    missing = services.missing_for(sign)
    if missing:
        fail("ERR_MISSING_DISCLOSURE", "the sign is missing a required disclosure")
    apply_changes(
        sign,
        {
            "status": "POSTED",
            "posted_at": now(),
            "missing_disclosure_codes": missing,
            "compliance_state": calc.signage_compliance_state("POSTED"),
        },
    )
    services.recompute_store(store)
    return ok(views.promo_signage(sign))


@bp.post("/price-integrity/promo-signage/<gid>/remove")
@roles(R_STORE_MANAGER, R_LABEL_ASSOCIATE)
def remove_signage(gid):
    sign = must("promo_signage", gid)
    # priority 41 — a second removal is a repeat transition
    if sign["status"] == "REMOVED":
        fail("ERR_TRANSITION_ALREADY_APPLIED", "the sign is already removed")
    # priority 40 — a draft sign was never on the floor
    if sign["status"] not in ("POSTED", "EXPIRED_PENDING_REMOVAL", "NON_COMPLIANT"):
        fail("ERR_SIGNAGE_INVALID_STATE", "the sign is not on the floor")
    apply_changes(
        sign,
        {
            "status": "REMOVED",
            "removed_at": now(),
            "compliance_state": calc.signage_compliance_state("REMOVED"),
        },
    )
    services.recompute_store(DB["stores"][sign["store_id"]])
    return ok(views.promo_signage(sign))


@bp.post("/price-integrity/stores/<sid>/signage-sweep")
@roles(R_STORE_MANAGER, R_COMPLIANCE_OFFICER)
def signage_sweep(sid):
    store = must("stores", sid)
    swept = 0
    expired = 0
    non_compliant = 0
    for sign in rows("promo_signage"):
        if sign["store_id"] != sid or sign["status"] == "REMOVED":
            continue
        swept += 1
        if sign["status"] != "POSTED":
            continue
        # pinned order: the expiry test runs first, then the disclosure test
        if now() >= sign["promo_end_at"]:
            apply_changes(
                sign,
                {
                    "status": "EXPIRED_PENDING_REMOVAL",
                    "compliance_state": calc.signage_compliance_state(
                        "EXPIRED_PENDING_REMOVAL"
                    ),
                },
            )
            expired += 1
            continue
        missing = services.missing_for(sign)
        if missing:
            apply_changes(
                sign,
                {
                    "status": "NON_COMPLIANT",
                    "missing_disclosure_codes": missing,
                    "compliance_state": calc.signage_compliance_state("NON_COMPLIANT"),
                },
            )
            non_compliant += 1
    services.recompute_store(store)
    return ok(
        {
            "swept_count": swept,
            "expired_count": expired,
            "non_compliant_count": non_compliant,
            "compliance_posture": store["compliance_posture"],
        }
    )
