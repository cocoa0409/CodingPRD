"""Partner agencies, family referrals, children, wish items, duplicate flags."""

from flask import Blueprint, request

import clock
import db
from domain import (
    make_row, touch, sort_rows, audit,
    compute_duplicate_hash, raise_auto_flags, family_has_open_flag,
    compute_child_age_band, recompute_child_estimate, family_rollup,
    cascade_family_rejected, cascade_children_closed, agency_referral_used_count,
    FAMILY_TERMINAL, PII_FIELDS,
    ser_agency, ser_family, ser_child, ser_wish_item, ser_flag, ser_audit,
    ser_gift, ser_backfill,
)
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, err_forbidden,
    err_duplicate, err_intake_closed, err_agency_suspended, err_quota,
    err_child_cap, err_child_too_old, err_wish_value, err_dup_flag_open,
    err_sod, err_privacy,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import (
    get_body, req_field, opt_field, as_int, as_str, as_enum, as_str_list,
    parse_date, AGENCY_CODE_RE, EMAIL_RE, PHONE4_RE,
)

bp = Blueprint("intake", __name__)

WISH_CATEGORIES = ("TOY", "CLOTHING", "BOOK", "SPORTS", "ELECTRONICS", "ART", "OTHER")
GENDERS = ("F", "M", "X")


def _get_agency(aid):
    row = db.agencies.get(aid)
    if row is None:
        raise err_not_found("PartnerAgency not found")
    return row


def _get_family(fid):
    row = db.families.get(fid)
    if row is None:
        raise err_not_found("Family not found")
    return row


def _get_child(cid):
    row = db.children.get(cid)
    if row is None:
        raise err_not_found("Child not found")
    return row


def _get_wish_item(wid):
    row = db.wish_items.get(wid)
    if row is None:
        raise err_not_found("WishItem not found")
    return row


def _check_donor_pii_params(actor):
    if actor.role == "Donor":
        for p in PII_FIELDS:
            if p in request.args:
                raise err_privacy("Donor requests may not filter on PII field %s" % p)


def _check_agency_ownership(actor, agency_id):
    if actor.role == "AgencyCoordinator" and actor.user_id != agency_id:
        raise err_forbidden("AgencyCoordinator may only access own agency's resources")


# ---------------------------------------------------------------------------
# PartnerAgency
# ---------------------------------------------------------------------------

@bp.route("/agencies", methods=["POST"])
@require_roles("PlatformAdmin")
def create_agency(actor):
    body = get_body(required=True)
    code = as_str(req_field(body, "agency_code"), "agency_code")
    if not AGENCY_CODE_RE.match(code):
        raise err_invalid_request("agency_code must be 3-16 uppercase alphanumerics")
    legal_name = as_str(req_field(body, "legal_name"), "legal_name")
    quota = as_int(req_field(body, "referral_quota"), "referral_quota")
    if quota < 1 or quota > 500:
        raise err_invalid_request("referral_quota must be between 1 and 500")
    contact = as_str(req_field(body, "contact_email"), "contact_email")
    for a in db.agencies.values():
        if a["agency_code"] == code:
            raise err_duplicate("agency_code must be unique")
    row = make_row()
    row.update(
        agency_code=code,
        legal_name=legal_name,
        status="ACTIVE",
        referral_quota=quota,
        contact_email=contact,
    )
    db.agencies[row["id"]] = row
    return success_created(ser_agency(row))


@bp.route("/agencies", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator")
def list_agencies(actor):
    rows = list(db.agencies.values())
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return success_list(sort_rows(rows), ser_agency)


@bp.route("/agencies/<aid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator")
def get_agency(actor, aid):
    row = _get_agency(aid)
    _check_agency_ownership(actor, row["id"])
    return success_object(ser_agency(row))


@bp.route("/agencies/<aid>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_agency(actor, aid):
    row = _get_agency(aid)
    get_body()
    if row["status"] != "ACTIVE":
        raise err_invalid_state("Agency is not ACTIVE")
    row["status"] = "SUSPENDED"
    touch(row)
    return success_object(ser_agency(row))


@bp.route("/agencies/<aid>/families", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator")
def agency_families(actor, aid):
    agency = _get_agency(aid)
    _check_agency_ownership(actor, agency["id"])
    rows = [f for f in db.families.values() if f["agency_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    return success_list(sort_rows(rows), lambda f: ser_family(f, actor))


# ---------------------------------------------------------------------------
# Family
# ---------------------------------------------------------------------------

@bp.route("/families", methods=["POST"])
@require_roles("AgencyCoordinator")
def create_family(actor):
    body = get_body(required=True)
    # presence/type of required fields
    agency_id = as_str(req_field(body, "agency_id"), "agency_id")
    campaign_id = as_str(req_field(body, "campaign_id"), "campaign_id")
    caregiver_name = as_str(req_field(body, "primary_caregiver_name"), "primary_caregiver_name")
    caregiver_dob = req_field(body, "caregiver_dob")
    household_size = as_int(req_field(body, "household_size"), "household_size")
    address_text = as_str(req_field(body, "address_text"), "address_text")
    phone_last4 = as_str(req_field(body, "phone_last4"), "phone_last4")

    # body referential existence
    agency = _get_agency(agency_id)
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err_not_found("Campaign not found")

    # ownership
    if actor.user_id != agency["id"]:
        raise err_forbidden("AgencyCoordinator may only refer families under own agency")

    # agency state
    if agency["status"] == "SUSPENDED":
        raise err_agency_suspended()

    # temporal intake window
    now = clock.now()
    if (
        campaign["status"] != "INTAKE_OPEN"
        or now < campaign["intake_open_at"]
        or now > campaign["intake_close_at"]
    ):
        raise err_intake_closed()

    # quota
    if agency_referral_used_count(agency["id"]) >= agency["referral_quota"]:
        raise err_quota()

    # body semantic constraints
    if household_size < 1 or household_size > 20:
        raise err_invalid_request("household_size must be between 1 and 20")
    if not PHONE4_RE.match(phone_last4):
        raise err_invalid_request("phone_last4 must be exactly 4 digits")
    parse_date(caregiver_dob, "caregiver_dob")

    dup_hash = compute_duplicate_hash(caregiver_dob, phone_last4, address_text)
    row = make_row()
    row.update(
        agency_id=agency_id,
        campaign_id=campaign_id,
        primary_caregiver_name=caregiver_name,
        caregiver_dob=caregiver_dob.strip() if isinstance(caregiver_dob, str) else caregiver_dob,
        household_size=household_size,
        address_text=address_text,
        phone_last4=phone_last4,
        duplicate_hash=dup_hash,
        status="REFERRED",
        verification_note="",
        verified_at=None,
        fulfilled_children_count=0,
        total_children_count=0,
        duplicate_of_family_id=None,
    )
    db.families[row["id"]] = row
    audit(row["id"], actor.role, actor.user_id, "STATUS_CHANGE",
          {"from": None, "to": "REFERRED"})
    raise_auto_flags(row)
    return success_created(ser_family(row))


@bp.route("/families", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator", "Donor")
def list_families(actor):
    _check_donor_pii_params(actor)
    rows = list(db.families.values())
    if actor.role == "AgencyCoordinator":
        rows = [f for f in rows if f["agency_id"] == actor.user_id]
    for param in ("campaign_id", "agency_id", "status", "duplicate_of_family_id"):
        val = request.args.get(param)
        if val is not None:
            rows = [f for f in rows if str(f.get(param)) == val]
    rows = sort_rows(rows)
    if actor.role == "Donor":
        from flask import jsonify
        from response import pagination_params, _meta
        limit, offset = pagination_params()
        page = rows[offset : offset + limit]
        for f in page:
            audit(f["id"], actor.role, actor.user_id, "PII_VIEW", {})
        meta = _meta()
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = len(rows)
        meta["has_more"] = (offset + len(page)) < len(rows)
        return jsonify({
            "meta": meta,
            "response_type": "array",
            "data": [ser_family(f, actor) for f in page],
        }), 200
    return success_list(rows, lambda f: ser_family(f, actor))


@bp.route("/families/<fid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator", "Donor")
def get_family(actor, fid):
    fam = _get_family(fid)
    if actor.role == "Donor":
        _check_donor_pii_params(actor)
        audit(fam["id"], actor.role, actor.user_id, "PII_VIEW", {})
    if actor.role == "AgencyCoordinator" and fam["agency_id"] != actor.user_id:
        raise err_forbidden("AgencyCoordinator may only read own agency's families")
    return success_object(ser_family(fam, actor))


@bp.route("/families/<fid>/children", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator", "Donor")
def family_children(actor, fid):
    fam = _get_family(fid)
    if actor.role == "AgencyCoordinator" and fam["agency_id"] != actor.user_id:
        raise err_forbidden("AgencyCoordinator may only read own agency's families")
    rows = [c for c in db.children.values() if c["family_id"] == fid]
    return success_list(sort_rows(rows), lambda c: ser_child(c, actor))


@bp.route("/families/<fid>/audit-events", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker")
def family_audit(actor, fid):
    _get_family(fid)
    rows = [e for e in db.family_audit_events.values() if e["family_id"] == fid]
    et = request.args.get("event_type")
    if et is not None:
        rows = [e for e in rows if e["event_type"] == et]
    return success_list(sort_rows(rows), ser_audit)


def _note_from_body(body):
    return opt_field(body, "verification_note", None)


@bp.route("/families/<fid>/begin-review", methods=["POST"])
@require_roles("CaseWorker")
def begin_review(actor, fid):
    fam = _get_family(fid)
    get_body()
    if fam["status"] != "REFERRED":
        raise err_invalid_state("begin-review requires family in REFERRED")
    if family_has_open_flag(fid):
        raise err_dup_flag_open()
    fam["status"] = "UNDER_REVIEW"
    touch(fam)
    audit(fid, actor.role, actor.user_id, "STATUS_CHANGE",
          {"from": "REFERRED", "to": "UNDER_REVIEW"})
    return success_object(ser_family(fam))


@bp.route("/families/<fid>/verify", methods=["POST"])
@require_roles("CaseWorker")
def verify_family(actor, fid):
    fam = _get_family(fid)
    body = get_body()
    if fam["status"] != "UNDER_REVIEW":
        raise err_invalid_state("verify requires family in UNDER_REVIEW")
    if family_has_open_flag(fid):
        raise err_dup_flag_open()
    # segregation of duties: the caseworker who began review must not verify
    begins = [
        ev for ev in db.family_audit_events.values()
        if ev["family_id"] == fid
        and ev["event_type"] == "STATUS_CHANGE"
        and ev["payload_json"].get("from") == "REFERRED"
        and ev["payload_json"].get("to") == "UNDER_REVIEW"
    ]
    if begins:
        latest = sort_rows(begins)[-1]
        if latest["actor_role"] == "CaseWorker" and latest["actor_id"] == actor.user_id:
            raise err_sod("The CaseWorker who began review may not verify this family")
    kids = [c for c in db.children.values() if c["family_id"] == fid and c["status"] != "CLOSED"]
    if fam["total_children_count"] < 1 or not kids:
        raise err_invalid_state("Family must have at least one child to verify")
    if any(c["age_band"] is None for c in kids):
        raise err_invalid_state("Every child must have a computed age_band")

    note = _note_from_body(body)
    if note is not None:
        if not isinstance(note, str):
            raise err_invalid_request("verification_note must be a string")
        fam["verification_note"] = note
    fam["status"] = "VERIFIED"
    fam["verified_at"] = clock.now()
    touch(fam)
    for c in db.children.values():
        if c["family_id"] == fid and c["status"] == "REGISTERED":
            c["status"] = "WISH_LOCKED"
            touch(c)
    audit(fid, actor.role, actor.user_id, "STATUS_CHANGE",
          {"from": "UNDER_REVIEW", "to": "VERIFIED"})
    return success_object(ser_family(fam))


@bp.route("/families/<fid>/reject", methods=["POST"])
@require_roles("CaseWorker")
def reject_family(actor, fid):
    fam = _get_family(fid)
    body = get_body()
    if fam["status"] != "UNDER_REVIEW":
        raise err_invalid_state("reject requires family in UNDER_REVIEW")
    note = _note_from_body(body)
    if note is not None:
        if not isinstance(note, str):
            raise err_invalid_request("verification_note must be a string")
        fam["verification_note"] = note
    cascade_family_rejected(fam, actor, "REJECTED_BY_CASEWORKER")
    audit(fid, actor.role, actor.user_id, "STATUS_CHANGE",
          {"from": "UNDER_REVIEW", "to": "REJECTED"})
    return success_object(ser_family(fam))


@bp.route("/families/<fid>/return-to-referral", methods=["POST"])
@require_roles("CaseWorker")
def return_to_referral(actor, fid):
    fam = _get_family(fid)
    body = get_body()
    if fam["status"] != "UNDER_REVIEW":
        raise err_invalid_state("return-to-referral requires family in UNDER_REVIEW")
    note = _note_from_body(body)
    if note is not None:
        if not isinstance(note, str):
            raise err_invalid_request("verification_note must be a string")
        fam["verification_note"] = note
    fam["status"] = "REFERRED"
    touch(fam)
    audit(fid, actor.role, actor.user_id, "STATUS_CHANGE",
          {"from": "UNDER_REVIEW", "to": "REFERRED"})
    return success_object(ser_family(fam))


@bp.route("/families/<fid>/withdraw", methods=["POST"])
@require_roles("CaseWorker")
def withdraw_family(actor, fid):
    fam = _get_family(fid)
    body = get_body()
    if fam["status"] != "VERIFIED":
        raise err_invalid_state("withdraw requires family in VERIFIED")
    active = any(
        a["family_id"] == fid and a["status"] in ("PLEDGED", "CONFIRMED", "PARTIALLY_RECEIVED")
        for a in db.adoptions.values()
    )
    if active:
        raise err_invalid_state("Family has an active adoption and may not be withdrawn")
    note = _note_from_body(body)
    if note is not None:
        if not isinstance(note, str):
            raise err_invalid_request("verification_note must be a string")
        fam["verification_note"] = note
    fam["status"] = "WITHDRAWN"
    touch(fam)
    cascade_children_closed(fam)
    audit(fid, actor.role, actor.user_id, "STATUS_CHANGE",
          {"from": "VERIFIED", "to": "WITHDRAWN"})
    return success_object(ser_family(fam))


# ---------------------------------------------------------------------------
# Child
# ---------------------------------------------------------------------------

@bp.route("/families/<fid>/children", methods=["POST"])
@require_roles("AgencyCoordinator", "CaseWorker")
def create_child(actor, fid):
    fam = _get_family(fid)
    if actor.role == "AgencyCoordinator" and fam["agency_id"] != actor.user_id:
        raise err_forbidden("AgencyCoordinator may only register children for own agency's families")
    body = get_body(required=True)
    first_name = as_str(req_field(body, "first_name"), "first_name")
    dob_raw = req_field(body, "dob")
    gender = as_enum(req_field(body, "gender"), "gender", GENDERS)
    clothing_size = as_str(req_field(body, "clothing_size"), "clothing_size")
    interest_tags = as_str_list(req_field(body, "interest_tags"), "interest_tags")
    dob = parse_date(dob_raw, "dob")

    campaign = db.campaigns.get(fam["campaign_id"])
    if fam["total_children_count"] >= campaign["max_children_per_family"]:
        raise err_child_cap()
    years, band = compute_child_age_band(dob, campaign)
    if years >= 19:
        raise err_child_too_old()

    row = make_row()
    row.update(
        family_id=fid,
        first_name=first_name,
        dob=dob_raw.strip() if isinstance(dob_raw, str) else dob_raw,
        _dob=dob,
        gender=gender,
        age_band=band,
        clothing_size=clothing_size,
        interest_tags=interest_tags,
        status="REGISTERED",
        gift_estimate_cents=0,
    )
    db.children[row["id"]] = row
    family_rollup(fam, adjust_status=False)
    return success_created(ser_child(row))


@bp.route("/children/<cid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator", "Donor")
def get_child(actor, cid):
    child = _get_child(cid)
    if actor.role == "AgencyCoordinator":
        fam = db.families.get(child["family_id"])
        if fam is None or fam["agency_id"] != actor.user_id:
            raise err_forbidden("AgencyCoordinator may only read own agency's children")
    return success_object(ser_child(child, actor))


@bp.route("/children/<cid>/gifts", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def child_gifts(actor, cid):
    _get_child(cid)
    rows = [g for g in db.gifts.values() if g["child_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    return success_list(sort_rows(rows), ser_gift)


@bp.route("/children/<cid>/wish-items", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator", "Donor")
def child_wish_items(actor, cid):
    child = _get_child(cid)
    if actor.role == "AgencyCoordinator":
        fam = db.families.get(child["family_id"])
        if fam is None or fam["agency_id"] != actor.user_id:
            raise err_forbidden("AgencyCoordinator may only read own agency's children")
    rows = [w for w in db.wish_items.values() if w["child_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    return success_list(sort_rows(rows), ser_wish_item)


# ---------------------------------------------------------------------------
# WishItem
# ---------------------------------------------------------------------------

@bp.route("/children/<cid>/wish-items", methods=["POST"])
@require_roles("AgencyCoordinator", "CaseWorker")
def create_wish_item(actor, cid):
    child = _get_child(cid)
    if actor.role == "AgencyCoordinator":
        fam = db.families.get(child["family_id"])
        if fam is None or fam["agency_id"] != actor.user_id:
            raise err_forbidden("AgencyCoordinator may only add wish items for own agency's children")
    body = get_body(required=True)
    description = as_str(req_field(body, "description"), "description")
    category = as_enum(req_field(body, "category"), "category", WISH_CATEGORIES)
    price = as_int(req_field(body, "estimated_price_cents"), "estimated_price_cents")
    rank = as_int(req_field(body, "priority_rank"), "priority_rank")
    if rank < 1 or rank > 10:
        raise err_invalid_request("priority_rank must be between 1 and 10")
    fam = db.families.get(child["family_id"])
    campaign = db.campaigns.get(fam["campaign_id"])
    if price < 100 or price > campaign["max_gift_value_cents"]:
        raise err_invalid_request(
            "estimated_price_cents must be between 100 and campaign.max_gift_value_cents"
        )
    for w in db.wish_items.values():
        if w["child_id"] == cid and w["priority_rank"] == rank:
            raise err_duplicate("priority_rank must be unique per child")
    active_sum = sum(
        w["estimated_price_cents"]
        for w in db.wish_items.values()
        if w["child_id"] == cid and w["status"] in ("REQUESTED", "APPROVED")
    )
    if active_sum + price > campaign["max_gift_value_cents"]:
        raise err_wish_value()
    row = make_row()
    row.update(
        child_id=cid,
        description=description,
        category=category,
        estimated_price_cents=price,
        priority_rank=rank,
        status="REQUESTED",
    )
    db.wish_items[row["id"]] = row
    recompute_child_estimate(child)
    return success_created(ser_wish_item(row))


@bp.route("/wish-items/<wid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "AgencyCoordinator", "Donor")
def get_wish_item(actor, wid):
    item = _get_wish_item(wid)
    if actor.role == "AgencyCoordinator":
        child = db.children.get(item["child_id"])
        fam = db.families.get(child["family_id"]) if child else None
        if fam is None or fam["agency_id"] != actor.user_id:
            raise err_forbidden("AgencyCoordinator may only read own agency's wish items")
    return success_object(ser_wish_item(item))


@bp.route("/wish-items/<wid>/gifts", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def wish_item_gifts(actor, wid):
    _get_wish_item(wid)
    rows = [g for g in db.gifts.values() if g.get("wish_item_id") == wid]
    status = request.args.get("status")
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    return success_list(sort_rows(rows), ser_gift)


@bp.route("/wish-items/<wid>/backfill-purchases", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def wish_item_backfills(actor, wid):
    _get_wish_item(wid)
    rows = [p for p in db.backfill_purchases.values() if p["wish_item_id"] == wid]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return success_list(sort_rows(rows), ser_backfill)


@bp.route("/wish-items/<wid>/approve", methods=["POST"])
@require_roles("CaseWorker")
def approve_wish_item(actor, wid):
    item = _get_wish_item(wid)
    get_body()
    if item["status"] != "REQUESTED":
        raise err_invalid_state("approve requires wish item in REQUESTED")
    child = db.children[item["child_id"]]
    if child["status"] not in ("REGISTERED", "WISH_LOCKED"):
        raise err_invalid_state("Child must be REGISTERED or WISH_LOCKED to approve items")
    fam = db.families[child["family_id"]]
    campaign = db.campaigns[fam["campaign_id"]]
    approved_sum = sum(
        w["estimated_price_cents"]
        for w in db.wish_items.values()
        if w["child_id"] == child["id"] and w["status"] == "APPROVED"
    )
    if approved_sum + item["estimated_price_cents"] > campaign["max_gift_value_cents"]:
        raise err_wish_value()
    item["status"] = "APPROVED"
    touch(item)
    recompute_child_estimate(child)
    return success_object(ser_wish_item(item))


@bp.route("/wish-items/<wid>/reject", methods=["POST"])
@require_roles("CaseWorker")
def reject_wish_item(actor, wid):
    item = _get_wish_item(wid)
    get_body()
    if item["status"] != "REQUESTED":
        raise err_invalid_state("reject requires wish item in REQUESTED")
    item["status"] = "REJECTED"
    touch(item)
    child = db.children[item["child_id"]]
    recompute_child_estimate(child)
    return success_object(ser_wish_item(item))


# ---------------------------------------------------------------------------
# DuplicateFlag
# ---------------------------------------------------------------------------

@bp.route("/duplicate-flags", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker")
def list_flags(actor):
    rows = list(db.duplicate_flags.values())
    for param in ("family_id", "other_family_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [f for f in rows if str(f.get(param)) == val]
    return success_list(sort_rows(rows), ser_flag)


@bp.route("/duplicate-flags/<fid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker")
def get_flag(actor, fid):
    row = db.duplicate_flags.get(fid)
    if row is None:
        raise err_not_found("DuplicateFlag not found")
    return success_object(ser_flag(row))


@bp.route("/duplicate-flags", methods=["POST"])
@require_roles("CaseWorker")
def create_flag(actor):
    body = get_body(required=True)
    family_id = as_str(req_field(body, "family_id"), "family_id")
    other_family_id = as_str(req_field(body, "other_family_id"), "other_family_id")
    fam = _get_family(family_id)
    other = _get_family(other_family_id)
    if fam["id"] == other["id"]:
        raise err_invalid_request("family_id and other_family_id must differ")
    row = make_row()
    row.update(
        family_id=fam["id"],
        other_family_id=other["id"],
        detected_by="MANUAL_REPORT",
        status="OPEN",
        resolution_note="",
    )
    db.duplicate_flags[row["id"]] = row
    audit(fam["id"], actor.role, actor.user_id, "DUPLICATE_FLAGGED",
          {"other_family_id": other["id"], "detected_by": "MANUAL_REPORT"})
    return success_created(ser_flag(row))


def _resolve_note(body):
    note = opt_field(body, "resolution_note", "")
    if note is not None and not isinstance(note, str):
        raise err_invalid_request("resolution_note must be a string")
    return note or ""


@bp.route("/duplicate-flags/<fid>/confirm", methods=["POST"])
@require_roles("CaseWorker")
def confirm_flag(actor, fid):
    flag = db.duplicate_flags.get(fid)
    if flag is None:
        raise err_not_found("DuplicateFlag not found")
    body = get_body()
    if flag["status"] != "OPEN":
        raise err_invalid_state("confirm requires flag in OPEN")
    flag["status"] = "CONFIRMED_DUPLICATE"
    flag["resolution_note"] = _resolve_note(body)
    touch(flag)
    fam = db.families.get(flag["family_id"])
    other = db.families.get(flag["other_family_id"])
    if fam is not None:
        if fam["status"] not in FAMILY_TERMINAL:
            cascade_family_rejected(fam, actor, "CONFIRMED_DUPLICATE")
        fam["duplicate_of_family_id"] = flag["other_family_id"]
        touch(fam)
        audit(fam["id"], actor.role, actor.user_id, "DUPLICATE_RESOLVED",
              {"resolution": "CONFIRMED_DUPLICATE", "other_family_id": flag["other_family_id"]})
    if other is not None:
        audit(other["id"], actor.role, actor.user_id, "DUPLICATE_RESOLVED",
              {"resolution": "CONFIRMED_DUPLICATE", "family_id": flag["family_id"]})
    return success_object(ser_flag(flag))


@bp.route("/duplicate-flags/<fid>/dismiss", methods=["POST"])
@require_roles("CaseWorker")
def dismiss_flag(actor, fid):
    flag = db.duplicate_flags.get(fid)
    if flag is None:
        raise err_not_found("DuplicateFlag not found")
    body = get_body()
    if flag["status"] != "OPEN":
        raise err_invalid_state("dismiss requires flag in OPEN")
    flag["status"] = "DISMISSED"
    flag["resolution_note"] = _resolve_note(body)
    touch(flag)
    fam = db.families.get(flag["family_id"])
    if fam is not None:
        audit(fam["id"], actor.role, actor.user_id, "DUPLICATE_RESOLVED",
              {"resolution": "DISMISSED", "other_family_id": flag["other_family_id"]})
    return success_object(ser_flag(flag))
