"""Donors, adoptions, and gifts."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from domain import (
    make_row, touch, sort_rows, audit, get_settings,
    donor_concurrent_count, adoption_covered_children, family_rollup,
    recompute_child_estimate, expire_adoption_cascade, family_revert_after_cancel,
    PLEDGE_WINDOW,
    ser_donor, ser_adoption, ser_gift,
)
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, err_forbidden,
    err_duplicate, err_stale_version, err_pledge_expired, err_adoption_cap,
    err_coverage, err_commitment_low, err_deadline_passed,
    err_gift_wish_mismatch, err_gift_value,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import (
    get_body, req_field, opt_field, as_int, as_str, as_bool, as_str_list,
    as_enum, EMAIL_RE,
)

bp = Blueprint("adoptions", __name__)

AGE_BANDS = ("INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE", "PRETEEN", "TEEN")


def _get_donor(did):
    row = db.donors.get(did)
    if row is None:
        raise err_not_found("Donor not found")
    return row


def _get_adoption(aid):
    row = db.adoptions.get(aid)
    if row is None:
        raise err_not_found("Adoption not found")
    return row


def _get_gift(gid):
    row = db.gifts.get(gid)
    if row is None:
        raise err_not_found("Gift not found")
    return row


# ---------------------------------------------------------------------------
# Donor
# ---------------------------------------------------------------------------

@bp.route("/donors", methods=["POST"])
@require_roles("PlatformAdmin")
def create_donor(actor):
    body = get_body(required=True)
    email = as_str(req_field(body, "email"), "email")
    if not EMAIL_RE.match(email):
        raise err_invalid_request("email must be RFC 5322 compliant")
    display_name = as_str(req_field(body, "display_name"), "display_name")
    max_adoptions = opt_field(body, "max_adoptions_per_season", 5)
    max_adoptions = as_int(max_adoptions, "max_adoptions_per_season")
    if max_adoptions < 1 or max_adoptions > 50:
        raise err_invalid_request("max_adoptions_per_season must be between 1 and 50")
    preferred = opt_field(body, "preferred_age_bands", [])
    preferred = as_str_list(preferred, "preferred_age_bands")
    for b in preferred:
        if b not in AGE_BANDS:
            raise err_invalid_request("preferred_age_bands entries must be valid age bands")
    opt_in = opt_field(body, "thank_you_opt_in", True)
    opt_in = as_bool(opt_in, "thank_you_opt_in")
    for d in db.donors.values():
        if d["email"] == email:
            raise err_duplicate("email must be unique")
    row = make_row()
    row.update(
        email=email,
        display_name=display_name,
        status="ACTIVE",
        max_adoptions_per_season=max_adoptions,
        preferred_age_bands=preferred,
        giving_history_cents=0,
        thank_you_opt_in=opt_in,
    )
    db.donors[row["id"]] = row
    return success_created(ser_donor(row))


@bp.route("/donors", methods=["GET"])
@require_roles("PlatformAdmin")
def list_donors(actor):
    rows = list(db.donors.values())
    status = request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return success_list(sort_rows(rows), ser_donor)


@bp.route("/donors/<did>", methods=["GET"])
@require_roles("PlatformAdmin", "Donor")
def get_donor(actor, did):
    row = _get_donor(did)
    if actor.role == "Donor" and actor.user_id != row["id"]:
        raise err_forbidden("Donors may only fetch their own record")
    return success_object(ser_donor(row))


# ---------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------

@bp.route("/adoptions", methods=["POST"])
@require_roles("Donor")
def create_adoption(actor):
    from domain import lazy_time_sweep
    lazy_time_sweep()
    body = get_body(required=True)
    campaign_id = as_str(req_field(body, "campaign_id"), "campaign_id")
    donor_id = as_str(req_field(body, "donor_id"), "donor_id")
    family_id = as_str(req_field(body, "family_id"), "family_id")
    scope = as_enum(req_field(body, "scope"), "scope", ("WHOLE_FAMILY", "CHILD_LIST"))
    child_ids = opt_field(body, "child_ids", [])
    if not isinstance(child_ids, list) or any(not isinstance(x, str) for x in child_ids):
        raise err_invalid_request("child_ids must be a list of strings")
    expected_family_version = req_field(body, "expected_family_version")
    if isinstance(expected_family_version, bool) or not isinstance(expected_family_version, int):
        raise err_invalid_request("expected_family_version must be an integer")

    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err_not_found("Campaign not found")
    donor = db.donors.get(donor_id)
    if donor is None:
        raise err_not_found("Donor not found")
    family = db.families.get(family_id)
    if family is None:
        raise err_not_found("Family not found")
    if donor_id != actor.user_id:
        raise err_forbidden("Donors may only pledge their own adoptions")

    # OCC (priority 6)
    if expected_family_version != family["version"]:
        raise err_stale_version("expected_family_version does not match current family version")

    # donor concurrent cap (priority 18)
    if donor_concurrent_count(donor_id, campaign_id) >= donor["max_adoptions_per_season"]:
        raise err_adoption_cap()

    # coverage (priority 21)
    if scope == "WHOLE_FAMILY":
        covered = [
            c for c in db.children.values()
            if c["family_id"] == family_id and c["status"] == "WISH_LOCKED"
        ]
        if not covered:
            raise err_coverage("WHOLE_FAMILY adoption requires at least one WISH_LOCKED child")
        covered_ids = [c["id"] for c in sort_rows(covered)]
        stored_child_ids = []
    else:
        seen = set()
        covered = []
        for cid in child_ids:
            child = db.children.get(cid)
            if child is None:
                raise err_not_found("Child %s not found" % cid)
            if child["family_id"] != family_id or child["status"] != "WISH_LOCKED":
                raise err_coverage(
                    "Every child_id must belong to the family and be WISH_LOCKED"
                )
            if cid not in seen:
                seen.add(cid)
                covered.append(child)
        if not covered:
            raise err_coverage("CHILD_LIST adoption requires at least one child")
        covered_ids = [c["id"] for c in covered]
        stored_child_ids = list(covered_ids)

    commitment = sum(c["gift_estimate_cents"] for c in covered)
    row = make_row()
    row.update(
        campaign_id=campaign_id,
        donor_id=donor_id,
        family_id=family_id,
        scope=scope,
        child_ids=stored_child_ids,
        commitment_cents=commitment,
        status="PLEDGED",
        pledged_at=clock.now(),
        confirmed_at=None,
        return_deadline=None,
        _covered_child_ids=covered_ids,
    )
    db.adoptions[row["id"]] = row
    touch(family)  # pledge bumps family version (OCC guard)
    return success_created(ser_adoption(row))


@bp.route("/adoptions", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "Donor")
def list_adoptions(actor):
    rows = list(db.adoptions.values())
    if actor.role == "Donor":
        rows = [a for a in rows if a["donor_id"] == actor.user_id]
    for param in ("donor_id", "campaign_id", "family_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [a for a in rows if str(a.get(param)) == val]
    return success_list(sort_rows(rows), ser_adoption)


@bp.route("/adoptions/<aid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "Donor")
def get_adoption(actor, aid):
    row = _get_adoption(aid)
    if actor.role == "Donor" and row["donor_id"] != actor.user_id:
        raise err_forbidden("Donors may only read their own adoptions")
    return success_object(ser_adoption(row))


@bp.route("/adoptions/<aid>/gifts", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "Donor", "DistributionVolunteer")
def adoption_gifts(actor, aid):
    adoption = _get_adoption(aid)
    if actor.role == "Donor" and adoption["donor_id"] != actor.user_id:
        raise err_forbidden("Donors may only read their own adoptions")
    rows = [g for g in db.gifts.values() if g["adoption_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    return success_list(sort_rows(rows), ser_gift)


@bp.route("/adoptions/<aid>/confirm", methods=["POST"])
@require_roles("Donor")
def confirm_adoption(actor, aid):
    adoption = _get_adoption(aid)
    get_body()
    if adoption["donor_id"] != actor.user_id:
        raise err_forbidden("Only the pledging donor may confirm this adoption")
    now = clock.now()
    if adoption["status"] == "PLEDGED" and now > adoption["pledged_at"] + PLEDGE_WINDOW:
        # lazy pledge expiry, surfaced with the dedicated error per catalog
        adoption["status"] = "EXPIRED"
        touch(adoption)
        raise err_pledge_expired()
    if adoption["status"] != "PLEDGED":
        raise err_invalid_state("confirm requires adoption in PLEDGED")
    family = db.families[adoption["family_id"]]
    if family["status"] != "VERIFIED":
        raise err_invalid_state("Family must be VERIFIED at confirm time")
    donor = db.donors[adoption["donor_id"]]
    if (
        donor_concurrent_count(adoption["donor_id"], adoption["campaign_id"],
                               exclude_adoption_id=adoption["id"])
        >= donor["max_adoptions_per_season"]
    ):
        raise err_adoption_cap()
    campaign = db.campaigns[adoption["campaign_id"]]
    covered = adoption_covered_children(adoption)
    if adoption["commitment_cents"] < campaign["min_gift_value_cents"] * len(covered):
        raise err_commitment_low()

    adoption["status"] = "CONFIRMED"
    adoption["confirmed_at"] = now
    adoption["return_deadline"] = campaign["gift_return_deadline"]
    touch(adoption)
    for child in covered:
        if child["status"] == "WISH_LOCKED":
            child["status"] = "ADOPTED"
            touch(child)
        for w in db.wish_items.values():
            if w["child_id"] == child["id"] and w["status"] == "APPROVED":
                w["status"] = "COMMITTED"
                touch(w)
        recompute_child_estimate(child)
    family["status"] = "MATCHED"
    touch(family)
    audit(family["id"], actor.role, actor.user_id, "STATUS_CHANGE",
          {"from": "VERIFIED", "to": "MATCHED", "adoption_id": adoption["id"]})
    return success_object(ser_adoption(adoption))


@bp.route("/adoptions/<aid>/cancel", methods=["POST"])
@require_roles("Donor")
def cancel_adoption(actor, aid):
    adoption = _get_adoption(aid)
    body = get_body()
    if adoption["donor_id"] != actor.user_id:
        raise err_forbidden("Only the pledging donor may cancel this adoption")
    if adoption["status"] != "CONFIRMED":
        raise err_invalid_state("cancel requires adoption in CONFIRMED")
    now = clock.now()
    reason = opt_field(body, "reason", None)
    if reason is not None and not isinstance(reason, str):
        raise err_invalid_request("reason must be a string")
    late = adoption["return_deadline"] is not None and now > adoption["return_deadline"]
    if late:
        if reason != "LATE":
            raise err_invalid_state(
                "Cancel past return_deadline requires reason=LATE"
            )
        new_status = "LATE_CANCELLED"
    else:
        new_status = "DONOR_CANCELLED"
    blocked = any(
        g["adoption_id"] == aid and g["status"] in ("RECEIVED", "SORTED", "STAGED", "DELIVERED")
        for g in db.gifts.values()
    )
    if blocked:
        raise err_invalid_state("Cannot cancel an adoption with received or delivered gifts")
    adoption["status"] = new_status
    touch(adoption)
    expire_adoption_cascade(adoption, actor)
    family_revert_after_cancel(adoption, actor)
    return success_object(ser_adoption(adoption))


@bp.route("/adoptions/<aid>/admin-cancel", methods=["POST"])
@require_roles("PlatformAdmin")
def admin_cancel_adoption(actor, aid):
    adoption = _get_adoption(aid)
    body = get_body(required=True)
    reason = as_str(req_field(body, "reason"), "reason")
    if adoption["status"] not in ("CONFIRMED", "PARTIALLY_RECEIVED"):
        raise err_invalid_state("admin-cancel requires adoption in CONFIRMED or PARTIALLY_RECEIVED")
    adoption["status"] = "ADMIN_CANCELLED"
    touch(adoption)
    # gifts COMMITTED/IN_TRANSIT -> RETURNED_TO_DONOR; RECEIVED stay RECEIVED
    for g in db.gifts.values():
        if g["adoption_id"] == aid and g["status"] in ("COMMITTED", "IN_TRANSIT"):
            g["status"] = "RETURNED_TO_DONOR"
            touch(g)
    for child in adoption_covered_children(adoption):
        has_received = any(
            g["child_id"] == child["id"] and g["adoption_id"] == aid
            and g["status"] in ("RECEIVED", "SORTED", "STAGED", "DELIVERED")
            for g in db.gifts.values()
        )
        if child["status"] == "ADOPTED" and not has_received:
            child["status"] = "BACKFILL_ELIGIBLE"
            touch(child)
        for w in db.wish_items.values():
            if w["child_id"] == child["id"] and w["status"] == "COMMITTED":
                # keep COMMITTED if a received gift references it
                w["status"] = "APPROVED"
                touch(w)
        recompute_child_estimate(child)
    family = db.families.get(adoption["family_id"])
    if family is not None:
        family_rollup(family, adjust_status=True)
    return success_object(ser_adoption(adoption))


# ---------------------------------------------------------------------------
# Gift
# ---------------------------------------------------------------------------

@bp.route("/gifts", methods=["POST"])
@require_roles("Donor")
def create_gift(actor):
    body = get_body(required=True)
    adoption_id = as_str(req_field(body, "adoption_id"), "adoption_id")
    child_id = as_str(req_field(body, "child_id"), "child_id")
    wish_item_id = opt_field(body, "wish_item_id", None)
    description = as_str(req_field(body, "description"), "description")
    declared = as_int(req_field(body, "declared_value_cents"), "declared_value_cents")
    if declared < 0:
        raise err_invalid_request("declared_value_cents must be >= 0")

    adoption = db.adoptions.get(adoption_id)
    if adoption is None:
        raise err_not_found("Adoption not found")
    child = db.children.get(child_id)
    if child is None:
        raise err_not_found("Child not found")
    wish_item = None
    if wish_item_id is not None:
        wish_item = db.wish_items.get(wish_item_id)
        if wish_item is None:
            raise err_not_found("WishItem not found")
    if adoption["donor_id"] != actor.user_id:
        raise err_forbidden("Donors may only declare gifts under their own adoptions")
    if adoption["status"] not in ("CONFIRMED", "PARTIALLY_RECEIVED"):
        raise err_invalid_state("Adoption must be CONFIRMED before gifts are declared")
    if wish_item is not None:
        if wish_item["child_id"] != child_id or wish_item["status"] not in ("APPROVED", "COMMITTED"):
            raise err_gift_wish_mismatch()
    campaign = db.campaigns[adoption["campaign_id"]]
    if declared > campaign["max_gift_value_cents"]:
        raise err_gift_value()

    row = make_row()
    row.update(
        adoption_id=adoption_id,
        child_id=child_id,
        wish_item_id=wish_item_id,
        description=description,
        declared_value_cents=declared,
        status="COMMITTED",
        received_at=None,
        sorted_at=None,
        slot_id=None,
    )
    db.gifts[row["id"]] = row
    if wish_item is not None and wish_item["status"] == "APPROVED":
        wish_item["status"] = "COMMITTED"
        touch(wish_item)
        recompute_child_estimate(child)
    return success_created(ser_gift(row))


@bp.route("/gifts/<gid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "Donor", "DistributionVolunteer")
def get_gift(actor, gid):
    gift = _get_gift(gid)
    if actor.role == "Donor":
        adoption = db.adoptions.get(gift["adoption_id"])
        if adoption is None or adoption["donor_id"] != actor.user_id:
            raise err_forbidden("Donors may only read their own gifts")
    return success_object(ser_gift(gift))


@bp.route("/gifts/<gid>/ship", methods=["POST"])
@require_roles("Donor")
def ship_gift(actor, gid):
    gift = _get_gift(gid)
    get_body()
    adoption = db.adoptions.get(gift["adoption_id"])
    if adoption is None or adoption["donor_id"] != actor.user_id:
        raise err_forbidden("Only the adoption's donor may ship this gift")
    if gift["status"] != "COMMITTED":
        raise err_invalid_state("ship requires gift in COMMITTED")
    gift["status"] = "IN_TRANSIT"
    touch(gift)
    return success_object(ser_gift(gift))


@bp.route("/gifts/<gid>/receive", methods=["POST"])
@require_roles("DistributionVolunteer")
def receive_gift(actor, gid):
    gift = _get_gift(gid)
    body = get_body()
    if gift["status"] not in ("COMMITTED", "IN_TRANSIT"):
        raise err_invalid_state("receive requires gift in COMMITTED or IN_TRANSIT")
    adoption = db.adoptions[gift["adoption_id"]]
    campaign = db.campaigns[adoption["campaign_id"]]
    settings = get_settings()
    now = clock.now()
    deadline = adoption["return_deadline"]
    in_window = deadline is not None and now <= deadline
    if not in_window:
        grace = settings["late_donor_grace_hours"]
        override_note = opt_field(body, "override_note", None)
        has_note = isinstance(override_note, str) and override_note.strip() != ""
        if not (
            grace > 0
            and deadline is not None
            and now <= deadline + timedelta(hours=grace)
            and has_note
        ):
            raise err_deadline_passed()

    gift["status"] = "RECEIVED"
    gift["received_at"] = now
    touch(gift)

    if adoption["status"] == "CONFIRMED":
        adoption["status"] = "PARTIALLY_RECEIVED"
        touch(adoption)

    child = db.children.get(gift["child_id"])
    family = None
    if child is not None:
        if child["status"] == "ADOPTED":
            child["status"] = "GIFT_RECEIVED"
            touch(child)
        family = db.families.get(child["family_id"])

    if gift.get("wish_item_id"):
        item = db.wish_items.get(gift["wish_item_id"])
        if item is not None and item["status"] == "COMMITTED":
            item["status"] = "RECEIVED"
            touch(item)

    if family is not None:
        if family["status"] == "MATCHED":
            family["status"] = "PARTIALLY_FULFILLED"
        family_rollup(family, adjust_status=False)

    donor = db.donors.get(adoption["donor_id"])
    if donor is not None:
        donor["giving_history_cents"] += gift["declared_value_cents"]
        touch(donor)
    return success_object(ser_gift(gift))


@bp.route("/gifts/<gid>/sort", methods=["POST"])
@require_roles("DistributionVolunteer")
def sort_gift(actor, gid):
    gift = _get_gift(gid)
    get_body()
    if gift["status"] != "RECEIVED":
        raise err_invalid_state("sort requires gift in RECEIVED")
    adoption = db.adoptions[gift["adoption_id"]]
    campaign = db.campaigns[adoption["campaign_id"]]
    if campaign["status"] not in ("DISTRIBUTION_PREP", "DISTRIBUTION"):
        raise err_invalid_state("Campaign must be in DISTRIBUTION_PREP or DISTRIBUTION to sort")
    qualifying = any(
        e["campaign_id"] == campaign["id"] and e["status"] in ("SORTING", "LOCKED", "COMPLETED")
        for e in db.distribution_events.values()
    )
    if not qualifying:
        raise err_invalid_state("No DistributionEvent under campaign is in SORTING or later")
    gift["status"] = "SORTED"
    gift["sorted_at"] = clock.now()
    touch(gift)
    return success_object(ser_gift(gift))


@bp.route("/gifts/<gid>/stage", methods=["POST"])
@require_roles("DistributionVolunteer")
def stage_gift(actor, gid):
    gift = _get_gift(gid)
    body = get_body(required=True)
    slot_id = as_str(req_field(body, "slot_id"), "slot_id")
    slot = db.distribution_slots.get(slot_id)
    if slot is None:
        raise err_not_found("DistributionSlot not found")
    if gift["status"] != "SORTED":
        raise err_invalid_state("stage requires gift in SORTED")
    child = db.children.get(gift["child_id"])
    child_family_id = child["family_id"] if child else None
    event = db.distribution_events.get(slot["event_id"])
    if slot["status"] not in ("RESERVED", "CHECKED_IN"):
        raise err_stage_mismatch("Target slot must be RESERVED or CHECKED_IN")
    if slot["family_id"] != child_family_id:
        raise err_stage_mismatch("Slot family does not match gift child's family")
    if event is None or event["status"] != "SORTING":
        raise err_stage_mismatch("Slot event must be in SORTING")
    gift["status"] = "STAGED"
    gift["slot_id"] = slot_id
    touch(gift)
    touch(slot)
    return success_object(ser_gift(gift))
