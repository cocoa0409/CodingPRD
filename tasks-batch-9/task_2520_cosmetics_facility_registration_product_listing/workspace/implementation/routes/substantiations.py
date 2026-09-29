"""Safety-substantiation dossiers, evidence items and the two review variants."""

from decimal import Decimal

from flask import Blueprint, request

import access
import calc
import domain
import envelope
import schema
import store
from access import Checks, Ctx

bp = Blueprint("substantiations", __name__)

ZERO = Decimal("0.00")


def _listing_of(sub):
    return domain.listing_of_substantiation(sub)


def _facility_of(sub):
    listing = _listing_of(sub)
    return domain.facility_of_listing(listing) if listing else None


def _owner_of_substantiation(auth, sub):
    listing = _listing_of(sub)
    if listing is not None:
        access.owner_of_listing(auth, listing)


# ------------------------------------------------------------------- dossiers
@bp.post("/cosmetics/listings/<lid>/substantiations")
def open_substantiation(lid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))

    def validate():
        payload = body if body is not None else {}
        ctx.assessor = schema.string_field(payload, "assessor_name", max_len=200)
        ctx.basis = schema.enum_field(payload, "assessment_basis", domain.ASSESSMENT_BASES)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_LISTING, lambda: access.state_error(
        ctx.listing["listing_status"] != "DELISTED", "ERR_INVALID_LISTING_STATE"))
    checks.run()

    listing = ctx.listing
    # PRD §3.4: opening a dossier supersedes every live predecessor.
    for predecessor in store.by_created(domain.substantiations_of_listing(lid)):
        if predecessor["status"] != "SUPERSEDED":
            predecessor["status"] = "SUPERSEDED"
            store.touch(predecessor)
    listing["safety_status"] = "UNSUBSTANTIATED"
    store.touch(listing)

    dossier = store.insert("substantiations", {
        "listing_id": lid,
        "assessor_name": ctx.assessor,
        "assessment_basis": ctx.basis,
        "status": "DRAFT",
        "review_mode": None,
        "adequacy_score": None,
        "screening_reviewer_user_id": None,
        "full_reviewer_user_id": None,
        "revision_round": 0,
        "data_gap_present": domain.listing_data_gap(lid),
        "decided_at": None,
    })
    return envelope.created(domain.substantiation_json(dossier))


@bp.get("/cosmetics/listings/<lid>/substantiations")
def list_substantiations(lid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))
    checks.run()
    records = domain.substantiations_of_listing(lid)
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    # PRD §3.4: a listing's dossiers are listed newest first.
    return envelope.paginate(store.by_created_desc(records), domain.substantiation_json)


@bp.get("/cosmetics/substantiations/<sid>")
def get_substantiation(sid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_SUBSTANTIATION,
               lambda: ctx.set("sub", access.need_substantiation(sid)))
    checks.add(access.R_OWNER, lambda: _owner_of_substantiation(auth, ctx.sub))
    checks.run()
    return envelope.ok(domain.substantiation_json(ctx.sub))


# -------------------------------------------------------------- evidence items
@bp.post("/cosmetics/substantiations/<sid>/review-items")
def add_review_item(sid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_SUBSTANTIATION,
               lambda: ctx.set("sub", access.need_substantiation(sid)))
    checks.add(access.R_OWNER, lambda: _owner_of_substantiation(auth, ctx.sub))

    def validate():
        payload = body if body is not None else {}
        ctx.evidence_type = schema.enum_field(payload, "evidence_type", domain.EVIDENCE_TYPES)
        ctx.credential = schema.enum_field(payload, "reviewer_credential",
                                           domain.REVIEWER_CREDENTIALS)
        ctx.citation = schema.string_field(payload, "citation", max_len=500)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_SUBSTANTIATION, lambda: access.state_error(
        ctx.sub["status"] in ("DRAFT", "DEFICIENT", "REVALIDATION_REQUIRED"),
        "ERR_INVALID_SUBSTANTIATION_STATE"))
    checks.run()

    item = store.insert("review_items", {
        "substantiation_id": sid,
        "evidence_type": ctx.evidence_type,
        "reviewer_credential": ctx.credential,
        "citation": ctx.citation,
        "screening_contribution": ZERO,
        "full_contribution": ZERO,
    })
    return envelope.created(domain.review_item_json(item))


@bp.get("/cosmetics/substantiations/<sid>/review-items")
def list_review_items(sid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_SUBSTANTIATION,
               lambda: ctx.set("sub", access.need_substantiation(sid)))
    checks.add(access.R_OWNER, lambda: _owner_of_substantiation(auth, ctx.sub))
    checks.run()
    records = domain.review_items_of(sid)
    evidence_type = request.args.get("evidence_type")
    if evidence_type:
        records = [r for r in records if r["evidence_type"] == evidence_type]
    return envelope.paginate(store.by_created(records), domain.review_item_json)


# ------------------------------------------------------------ submit / decide
@bp.post("/cosmetics/substantiations/<sid>/submit")
def submit_substantiation(sid):
    auth = access.authorize("ResponsiblePersonAgent")
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_SUBSTANTIATION,
               lambda: ctx.set("sub", access.need_substantiation(sid)))
    checks.add(access.R_OWNER, lambda: _owner_of_substantiation(auth, ctx.sub))
    checks.add(access.R_FROZEN, lambda: access.state_error(
        _facility_of(ctx.sub)["compliance_posture"] != "FROZEN",
        "ERR_FACILITY_POSTURE_FROZEN"))
    checks.add(access.R_STATE_SUBSTANTIATION, lambda: access.state_error(
        ctx.sub["status"] in ("DRAFT", "DEFICIENT", "REVALIDATION_REQUIRED"),
        "ERR_INVALID_SUBSTANTIATION_STATE"))
    checks.add(access.R_NO_REVIEW_ITEMS, lambda: access.state_error(
        len(domain.review_items_of(sid)) > 0, "ERR_NO_REVIEW_ITEMS"))
    checks.run()

    dossier = ctx.sub
    listing = _listing_of(dossier)
    dossier["status"] = "SUBMITTED"
    dossier["revision_round"] = int(dossier["revision_round"]) + 1
    dossier["data_gap_present"] = domain.listing_data_gap(listing["id"])
    store.touch(dossier)
    listing["safety_status"] = "UNDER_SUBSTANTIATION"
    store.touch(listing)
    return envelope.ok(domain.substantiation_json(dossier))


@bp.post("/cosmetics/substantiations/<sid>/review-decision")
def review_decision(sid):
    auth = access.authorize("RegulatoryReviewer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_SUBSTANTIATION,
               lambda: ctx.set("sub", access.need_substantiation(sid)))

    def validate():
        payload = body if body is not None else {}
        ctx.mode = schema.enum_field(payload, "review_mode", domain.REVIEW_MODES)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_SUBSTANTIATION, lambda: access.state_error(
        ctx.sub["status"] == "SUBMITTED", "ERR_INVALID_SUBSTANTIATION_STATE"))

    def segregation():
        # PRD §2.12: the screening reviewer may not also issue the FULL decision.
        if ctx.mode != "FULL":
            return
        screener = ctx.sub["screening_reviewer_user_id"]
        access.state_error(screener is None or screener != auth.user_id,
                          "ERR_SEGREGATION_OF_DUTIES")

    checks.add(access.R_SEGREGATION, segregation)
    checks.add(access.R_FULL_REVIEW_REQUIRED, lambda: access.state_error(
        not (ctx.sub["data_gap_present"] and ctx.mode == "SCREENING"),
        "ERR_FULL_REVIEW_REQUIRED_FOR_DATA_GAP"))
    checks.run()

    dossier = ctx.sub
    listing = _listing_of(dossier)
    facility = domain.facility_of_listing(listing)
    items = store.by_created(domain.review_items_of(sid))
    score = calc.adequacy_score(items, ctx.mode, dossier["data_gap_present"])

    for item in items:
        item["screening_contribution"] = calc.item_base_value(item)
        item["full_contribution"] = calc.item_full_value(item)
        item["updated_at"] = store.now_iso_ms()

    dossier["adequacy_score"] = score
    dossier["review_mode"] = ctx.mode
    dossier["decided_at"] = store.now()
    if ctx.mode == "SCREENING":
        dossier["screening_reviewer_user_id"] = auth.user_id
    else:
        dossier["full_reviewer_user_id"] = auth.user_id

    adequate = score >= calc.ADEQUACY_PASS_MARK
    dossier["status"] = "ADEQUATE" if adequate else "DEFICIENT"
    store.touch(dossier)
    listing["safety_status"] = "SUBSTANTIATED" if adequate else "SUBSTANTIATION_FAILED"
    store.touch(listing)
    domain.ledger_append(
        facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
        "substantiation adequate" if adequate else "substantiation deficient")
    return envelope.ok(domain.substantiation_json(dossier))
