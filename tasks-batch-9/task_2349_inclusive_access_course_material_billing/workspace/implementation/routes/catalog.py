"""PublisherAgreement, CourseMaterialTitle and PricingTier endpoints (PRD 3.2)."""

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_FACULTY, ROLE_PROGRAM_ADMIN,
                  authenticate)
from calc import D
from domain import (adoptions_of_section, agreement_json, get_agreement,
                    get_tier, get_title, run_json, tier_json, tiers_of_title,
                    title_json, titles_of_agreement)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order, touch
from validate import bad, f_date, f_enum, f_int, f_num, f_str, get_body

bp = Blueprint("catalog", __name__)

CATALOG_READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_FACULTY, ROLE_BURSAR, ROLE_COMPLIANCE)

AGREEMENT_FIELDS = ("publisher_name", "agreement_code", "effective_from",
                    "effective_to", "admin_fee_pct", "bookstore_margin_pct",
                    "price_floor_cents", "rebate_threshold_cents", "rebate_pct",
                    "max_list_price_pct")


# ---------------------------------------------------------------------------
# PublisherAgreement
# ---------------------------------------------------------------------------


@bp.post("/agreements")
def create_agreement():
    authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(AGREEMENT_FIELDS)
    publisher_name = f_str(body, "publisher_name")
    agreement_code = f_str(body, "agreement_code")
    effective_from = f_date(body, "effective_from")
    effective_to = f_date(body, "effective_to")
    admin_fee_pct = f_num(body, "admin_fee_pct", minimum=0, maximum=0.25)
    bookstore_margin_pct = f_num(body, "bookstore_margin_pct", minimum=0, maximum=0.50)
    price_floor_cents = f_int(body, "price_floor_cents", minimum=0)
    rebate_threshold_cents = f_int(body, "rebate_threshold_cents", minimum=0)
    rebate_pct = f_num(body, "rebate_pct", minimum=0, maximum=0.20)
    max_list_price_pct = f_num(body, "max_list_price_pct", required=False, default=0.60,
                               exclusive_minimum=0, maximum=1)

    if effective_to <= effective_from:
        bad("effective_to must be strictly later than effective_from")

    for existing in db.agreements.values():
        if existing["agreement_code"] == agreement_code:
            fail("ERR_DUPLICATE_RESOURCE_KEY")

    agreement = base_record()
    agreement.update({
        "publisher_name": publisher_name,
        "agreement_code": agreement_code,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "admin_fee_pct": D(admin_fee_pct),
        "bookstore_margin_pct": D(bookstore_margin_pct),
        "price_floor_cents": price_floor_cents,
        "max_list_price_pct": D(max_list_price_pct),
        "rebate_threshold_cents": rebate_threshold_cents,
        "rebate_pct": D(rebate_pct),
        "status": "DRAFT",
        "reconciliation_status": "NOT_STARTED",
        "settled_amount_cents": None,
        "suspend_reason_note": None,
    })
    db.agreements[agreement["id"]] = agreement
    return object_response(agreement_json(agreement), 201)


@bp.get("/agreements/<agreement_id>")
def read_agreement(agreement_id):
    authenticate(*CATALOG_READ_ROLES)
    return object_response(agreement_json(get_agreement(agreement_id)))


@bp.get("/agreements")
def list_agreements():
    authenticate(*CATALOG_READ_ROLES)
    items = apply_filters(in_order(db.agreements.values()), [
        ("agreement_code", "agreement_code"),
        ("status", "status"),
        ("reconciliation_status", "reconciliation_status"),
    ])
    return paginate(items, agreement_json)


@bp.post("/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    agreement = get_agreement(agreement_id)
    if agreement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    active_titles = [t for t in titles_of_agreement(agreement["id"])
                     if t["status"] == "ACTIVE"]
    if not active_titles:
        fail("ERR_AGREEMENT_NOT_ACTIVATABLE")
    for title in active_titles:
        if not tiers_of_title(title["id"]):
            fail("ERR_AGREEMENT_NOT_ACTIVATABLE")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return object_response(agreement_json(agreement))


@bp.post("/agreements/<agreement_id>/suspend")
def suspend_agreement(agreement_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(("suspend_reason_note",))
    note = f_str(body, "suspend_reason_note")
    agreement = get_agreement(agreement_id)
    if agreement["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    agreement["status"] = "SUSPENDED"
    agreement["suspend_reason_note"] = note
    touch(agreement)
    return object_response(agreement_json(agreement))


@bp.get("/agreements/<agreement_id>/titles")
def list_agreement_titles(agreement_id):
    authenticate(*CATALOG_READ_ROLES)
    agreement = get_agreement(agreement_id)
    items = apply_filters(titles_of_agreement(agreement["id"]), [("status", "status")])
    return paginate(items, title_json)


@bp.get("/agreements/<agreement_id>/reconciliation-runs")
def list_agreement_runs(agreement_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE)
    agreement = get_agreement(agreement_id)
    items = in_order([r for r in db.runs.values()
                      if r["agreement_id"] == agreement["id"]])
    items = apply_filters(items, [("term_id", "term_id"), ("status", "status")])
    return paginate(items, run_json)


# ---------------------------------------------------------------------------
# CourseMaterialTitle
# ---------------------------------------------------------------------------


@bp.post("/titles")
def create_title():
    authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(("agreement_id", "isbn", "title", "list_price_cents", "format"))
    agreement_id = f_str(body, "agreement_id")
    isbn = f_str(body, "isbn")
    name = f_str(body, "title")
    list_price_cents = f_int(body, "list_price_cents", minimum=1)
    fmt = f_enum(body, "format", ("DIGITAL", "DIGITAL_PLUS_PRINT"))

    agreement = get_agreement(agreement_id)
    for existing in db.titles.values():
        if existing["agreement_id"] == agreement["id"] and existing["isbn"] == isbn:
            fail("ERR_DUPLICATE_RESOURCE_KEY")

    title = base_record()
    title.update({
        "agreement_id": agreement["id"],
        "isbn": isbn,
        "title": name,
        "list_price_cents": list_price_cents,
        "format": fmt,
        "status": "ACTIVE",
    })
    db.titles[title["id"]] = title
    return object_response(title_json(title), 201)


@bp.get("/titles/<title_id>")
def read_title(title_id):
    authenticate(*CATALOG_READ_ROLES)
    return object_response(title_json(get_title(title_id)))


@bp.get("/titles")
def list_titles():
    authenticate(*CATALOG_READ_ROLES)
    items = apply_filters(in_order(db.titles.values()), [
        ("agreement_id", "agreement_id"),
        ("isbn", "isbn"),
        ("status", "status"),
        ("format", "format"),
    ])
    return paginate(items, title_json)


@bp.post("/titles/<title_id>/withdraw")
def withdraw_title(title_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    title = get_title(title_id)
    if title["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    for adoption in db.adoptions.values():
        if adoption["title_id"] != title["id"] or adoption["status"] != "APPROVED":
            continue
        section = db.sections.get(adoption["section_id"])
        if section is not None and section["ia_status"] in ("BILLED", "AT_RISK"):
            fail("ERR_TITLE_ALREADY_BILLED")
    title["status"] = "WITHDRAWN"
    touch(title)
    return object_response(title_json(title))


# ---------------------------------------------------------------------------
# PricingTier
# ---------------------------------------------------------------------------


@bp.post("/titles/<title_id>/pricing-tiers")
def create_tier(title_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(("min_enrollment", "max_enrollment", "per_student_price_cents"))
    min_enrollment = f_int(body, "min_enrollment", minimum=1)
    max_enrollment = f_int(body, "max_enrollment", required=False, default=None, minimum=1)
    per_student_price_cents = f_int(body, "per_student_price_cents", minimum=1)
    if max_enrollment is not None and max_enrollment < min_enrollment:
        bad("max_enrollment must not be smaller than min_enrollment")

    title = get_title(title_id)

    cand_hi = max_enrollment
    for tier in tiers_of_title(title["id"]):
        other_hi = tier["max_enrollment"]
        lower_le_other_hi = other_hi is None or min_enrollment <= other_hi
        other_lo_le_cand_hi = cand_hi is None or tier["min_enrollment"] <= cand_hi
        if lower_le_other_hi and other_lo_le_cand_hi:
            fail("ERR_TIER_BAND_OVERLAP")

    tier = base_record()
    tier.update({
        "title_id": title["id"],
        "min_enrollment": min_enrollment,
        "max_enrollment": max_enrollment,
        "per_student_price_cents": per_student_price_cents,
    })
    db.tiers[tier["id"]] = tier
    return object_response(tier_json(tier), 201)


@bp.get("/titles/<title_id>/pricing-tiers")
def list_title_tiers(title_id):
    authenticate(*CATALOG_READ_ROLES)
    title = get_title(title_id)
    return paginate(tiers_of_title(title["id"]), tier_json)


@bp.get("/pricing-tiers/<tier_id>")
def read_tier(tier_id):
    authenticate(*CATALOG_READ_ROLES)
    return object_response(tier_json(get_tier(tier_id)))


@bp.get("/pricing-tiers")
def list_tiers():
    authenticate(*CATALOG_READ_ROLES)
    items = apply_filters(in_order(db.tiers.values()), [("title_id", "title_id")])
    return paginate(items, tier_json)
