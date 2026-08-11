"""Member routes: register, get, list, verify, resign, expel, terms, benefits, directory, revenue."""
from flask import Blueprint, request

import db
import errors
import middleware
from response import success
from services import lifecycle, pricing

bp = Blueprint("members", __name__)


def _body():
    return request.get_json(silent=True) or {}


def _paginate(rows):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": (offset + limit) < total}


def _get_member(mid):
    m = db.members.get(mid)
    if not m:
        raise errors.not_found()
    return m


@bp.post("/api/members")
def register_member():
    middleware.require_roles("Member")
    b = _body()
    # body-id existence (priority 3)
    cat = db.membership_categories.get(b.get("category_id"))
    ch = db.chapters.get(b.get("home_chapter_id"))
    pol = db.renewal_cycle_policies.get(b.get("cycle_policy_id"))
    if not cat or not ch or not pol:
        raise errors.not_found()
    # email uniqueness (priority 4)
    for m in db.members.values():
        if m["email"] == b.get("email"):
            raise errors.ApiError(errors.ERR_DUPLICATE_EMAIL,
                                  "Member with email already exists", 409)
    # active-reference (priority 10)
    if cat["status"] != "ACTIVE" or ch["status"] != "ACTIVE" or pol["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INACTIVE_REFERENCE,
                              "Referenced category, chapter, or cycle policy is not ACTIVE", 422)

    m = lifecycle.new_entity({
        "email": b.get("email"),
        "full_name": b.get("full_name"),
        "category_id": b.get("category_id"),
        "home_chapter_id": b.get("home_chapter_id"),
        "cycle_policy_id": b.get("cycle_policy_id"),
        "joined_at": db.iso(db.parse_dt(b.get("joined_at"))) if b.get("joined_at") else db.iso(db.now_utc()),
        "status": "PENDING_VERIFICATION",
        "current_period_start": None,
        "current_period_end": None,
        "lifetime_dues_paid_cents": 0,
        "risk_score": 0,
    })
    db.members[m["id"]] = m
    # opening term + initial invoice, computed at join instant (logical now)
    term, inv = lifecycle.open_term_and_invoice(m, "JOIN", db.now_utc())
    return success(lifecycle.member_out(m), status=201)


@bp.get("/api/members/<mid>")
def get_member(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator", "DuesAdministrator")
    m = _get_member(mid)
    return success(lifecycle.member_out(m))


@bp.get("/api/members")
def list_members():
    middleware.require_roles("MembershipAdministrator", "DuesAdministrator")
    rows = list(db.members.values())
    f_status = request.args.get("status")
    f_cat = request.args.get("category_id")
    f_ch = request.args.get("home_chapter_id")
    f_pol = request.args.get("cycle_policy_id")
    if f_status:
        rows = [m for m in rows if m["status"] == f_status]
    if f_cat:
        rows = [m for m in rows if m["category_id"] == f_cat]
    if f_ch:
        rows = [m for m in rows if m["home_chapter_id"] == f_ch]
    if f_pol:
        rows = [m for m in rows if m["cycle_policy_id"] == f_pol]
    rows.sort(key=lambda m: m["created_at"])
    page, meta = _paginate(rows)
    return success([lifecycle.member_out(m) for m in page], response_type="array", pagination=meta)


@bp.post("/api/members/<mid>/verify")
def verify_member(mid):
    middleware.require_owner_or_roles(mid)
    m = _get_member(mid)
    if m["status"] != "PENDING_VERIFICATION":
        raise errors.invalid_state("Member is not PENDING_VERIFICATION")
    # initial invoice settled?
    initial = None
    for inv in db.dues_invoices.values():
        if inv["member_id"] == mid:
            term = db.membership_terms.get(inv["membership_term_id"])
            if term and term["opened_by"] == "JOIN":
                initial = inv
                break
    if initial is None or initial["payment_status"] != "SETTLED":
        raise errors.ApiError(errors.ERR_VERIFICATION_BLOCKED,
                              "Initial invoice not yet settled", 422)

    term = db.membership_terms.get(initial["membership_term_id"])
    m["status"] = "ACTIVE"
    m["current_period_start"] = term["period_start"]
    m["current_period_end"] = term["period_end"]
    m["lifetime_dues_paid_cents"] = initial["amount_cents"]
    db.touch(m)

    # entitlements per category defaults
    cat = db.membership_categories[m["category_id"]]
    codes = ["JOURNAL_ACCESS", "CONFERENCE_DISCOUNT", "CERTIFICATION_REGISTRY", "DIRECTORY_LISTING"]
    if cat["is_voting"]:
        codes.append("VOTING_BALLOT")
    now_iso = db.iso(db.now_utc())
    for code in codes:
        e = lifecycle.new_entity({
            "member_id": mid,
            "benefit_code": code,
            "granted_at": now_iso,
            "suspended_at": None,
            "status": "ACTIVE",
        })
        db.benefit_entitlements[e["id"]] = e

    # directory listing
    listing = lifecycle.new_entity({
        "member_id": mid,
        "display_name": m["full_name"],
        "specialty_tags": [],
        "is_public": False,
        "visibility_state": "HIDDEN_OPT_OUT",
    })
    db.directory_listings[listing["id"]] = listing
    lifecycle.recompute_listing_visibility(listing, m)

    lifecycle.recompute_risk_score(m)
    return success(lifecycle.member_out(m))


@bp.post("/api/members/<mid>/resign")
def resign_member(mid):
    middleware.require_owner_or_roles(mid)
    m = _get_member(mid)
    if m["status"] not in ("ACTIVE", "GRACE"):
        raise errors.invalid_state("Member cannot resign from current state")
    b = _body()
    expected = b.get("expected_member_version")
    if expected is not None and int(expected) != m["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION,
                              "expected_member_version does not match current Member.version", 412)
    m["status"] = "RESIGNED"
    lifecycle.revoke_auto_renew(m)
    lifecycle.propagate_benefits(m, "RESIGNED")
    lifecycle.write_off_open_invoices(m)
    for l in db.directory_listings.values():
        if l["member_id"] == mid:
            l["visibility_state"] = "HIDDEN_OPT_OUT"
            db.touch(l)
    db.touch(m)
    return success(lifecycle.member_out(m))


@bp.post("/api/members/<mid>/expel")
def expel_member(mid):
    middleware.require_roles("MembershipAdministrator")
    m = _get_member(mid)
    if m["status"] not in ("ACTIVE", "GRACE", "LAPSED"):
        raise errors.invalid_state("Member cannot be expelled from current state")
    m["status"] = "EXPELLED"
    lifecycle.revoke_auto_renew(m)
    lifecycle.propagate_benefits(m, "EXPELLED")
    lifecycle.write_off_open_invoices(m)
    for l in db.directory_listings.values():
        if l["member_id"] == mid:
            l["visibility_state"] = "HIDDEN_OPT_OUT"
            db.touch(l)
    db.touch(m)
    return success(lifecycle.member_out(m))


@bp.get("/api/members/<mid>/membership-terms")
def list_terms(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator", "DuesAdministrator")
    _get_member(mid)
    rows = [t for t in db.membership_terms.values() if t["member_id"] == mid]
    rows.sort(key=lambda t: t["created_at"])
    return success([lifecycle.term_out(t) for t in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.get("/api/members/<mid>/benefit-entitlements")
def list_entitlements(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator")
    _get_member(mid)
    rows = [e for e in db.benefit_entitlements.values() if e["member_id"] == mid]
    rows.sort(key=lambda e: e["created_at"])
    return success([lifecycle.entitlement_out(e) for e in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.get("/api/members/<mid>/directory-listing")
def get_listing(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator")
    _get_member(mid)
    rows = [l for l in db.directory_listings.values() if l["member_id"] == mid]
    rows.sort(key=lambda l: l["created_at"])
    return success([lifecycle.listing_out(l) for l in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.patch("/api/directory-listings/<lid>")
def update_listing(lid):
    l = db.directory_listings.get(lid)
    if not l:
        raise errors.not_found()
    middleware.require_owner_or_roles(l["member_id"])
    b = _body()
    if "display_name" in b:
        l["display_name"] = b["display_name"]
    if "specialty_tags" in b:
        l["specialty_tags"] = b["specialty_tags"]
    if "is_public" in b:
        l["is_public"] = bool(b["is_public"])
    db.touch(l)
    member = db.members.get(l["member_id"])
    if member:
        lifecycle.recompute_listing_visibility(l, member)
    return success(lifecycle.listing_out(l))


@bp.post("/api/members/<mid>/revenue-attributions")
def create_revenue(mid):
    middleware.require_roles("MembershipAdministrator", "DuesAdministrator")
    m = _get_member(mid)
    b = _body()
    kind = b.get("revenue_kind")
    amount = b.get("amount_cents")
    valid_kinds = {"CONFERENCE_REGISTRATION", "PUBLICATION_SALE", "CERTIFICATION_FEE", "DONATION"}
    try:
        amount_int = int(amount)
    except (TypeError, ValueError):
        amount_int = 0
    if kind not in valid_kinds or amount_int <= 0:
        raise errors.ApiError(errors.ERR_INVALID_REVENUE_KIND,
                              "Invalid revenue_kind or non-positive amount_cents", 422)
    occurred = db.parse_dt(b.get("occurred_at")) if b.get("occurred_at") else db.now_utc()
    r = lifecycle.new_entity({
        "member_id": mid,
        "revenue_kind": kind,
        "amount_cents": amount_int,
        "occurred_at": db.iso(occurred),
        "fiscal_period": occurred.strftime("%Y-%m"),
    })
    db.revenue_attributions[r["id"]] = r
    return success(lifecycle.revenue_out(r), status=201)


@bp.get("/api/members/<mid>/revenue-attributions")
def list_revenue(mid):
    middleware.require_owner_or_roles(mid, "MembershipAdministrator", "DuesAdministrator")
    _get_member(mid)
    rows = [r for r in db.revenue_attributions.values() if r["member_id"] == mid]
    fp = request.args.get("fiscal_period")
    if fp:
        rows = [r for r in rows if r["fiscal_period"] == fp]
    rows.sort(key=lambda r: r["created_at"])
    return success([lifecycle.revenue_out(r) for r in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})
