"""Routes: donation offers and tax receipts."""
from flask import Blueprint, request

import db
from errors import ApiError, err_not_owner, err_invalid_request
from response import success_obj, success_list
from services import (
    guidance_valuation,
    receipt_item_sum,
    receipt_requires_appraisal,
    recompute_donor_standing,
)
from util import (
    authenticate,
    require_role,
    get_body,
    req_str,
    opt_str,
    req_enum,
    req_num,
    opt_num,
    req_bool,
    opt_fk,
    opt_int,
    req_int,
    lookup,
    paginate,
    serialize,
)

bp = Blueprint("offers", __name__)

SOURCE_TYPES = {"DROPOFF", "PICKUP", "DECONSTRUCTION"}
QUANTITY_UNITS = {"UNIT", "SQFT", "LINEAR_FT"}
CONDITION_GRADES = {"A", "B", "C", "D"}

OFFER_NONTERMINAL_FOR_CANCEL = {"OFFERED", "UNDER_REVIEW", "NEEDS_INFO", "ACCEPTED"}
RECEIPT_NONTERMINAL = {"DRAFT", "ISSUED", "VOID_REQUESTED"}


def _get_offer_or_404(offer_id):
    return lookup(db.offers, "offer", offer_id)


def _check_offer_owner(ctx, offer):
    if ctx.role == "Donor" and offer["donor_id"] != ctx.user_id:
        raise err_not_owner("Donor may only act on own offers")


# ---------------------------------------------------------------------------
# Donation offers
# ---------------------------------------------------------------------------


@bp.post("/reuse/donation-offers")
def create_offer():
    data = get_body()
    donor_id = req_str(data, "donor_id")
    source_type = req_enum(data, "source_type", SOURCE_TYPES)
    category_id = req_str(data, "category_id")
    description_text = req_str(data, "description_text")
    estimated_quantity = req_num(data, "estimated_quantity", gt=0)
    quantity_unit = req_enum(data, "quantity_unit", QUANTITY_UNITS)
    condition_grade = req_enum(data, "condition_grade", CONDITION_GRADES)
    pre_1978_flag = req_bool(data, "pre_1978_flag")
    deconstruction_job_id = opt_fk(data, "deconstruction_job_id")
    ctx = authenticate()
    require_role(ctx, ["Donor", "IntakeStaff"])
    if ctx.role == "Donor" and donor_id != ctx.user_id:
        raise err_not_owner("Donor may only create offers for themselves")
    # Body FK existence (priority 5)
    lookup(db.donors, "donor", donor_id)
    lookup(db.categories, "category", category_id)
    job = None
    if deconstruction_job_id is not None:
        job = lookup(db.jobs, "job", deconstruction_job_id)
    # Referential linkage (priority 12)
    if source_type == "DECONSTRUCTION":
        if deconstruction_job_id is None:
            raise ApiError(
                "ERR_JOB_CANCELLED",
                409,
                "DECONSTRUCTION offer requires a deconstruction_job_id",
            )
        if job["status"] == "CANCELLED":
            raise ApiError(
                "ERR_JOB_CANCELLED", 409, "Linked deconstruction job is CANCELLED"
            )
    else:
        deconstruction_job_id = None
    offer = {
        **db.base_fields(),
        "donor_id": donor_id,
        "source_type": source_type,
        "category_id": category_id,
        "description_text": description_text,
        "estimated_quantity": estimated_quantity,
        "quantity_unit": quantity_unit,
        "condition_grade": condition_grade,
        "pre_1978_flag": pre_1978_flag,
        "deconstruction_job_id": deconstruction_job_id,
        "status": "OFFERED",
        "review_notes": "",
        "decision_reason": "",
        "received_by_user_id": "",
        "estimated_value_cents": 0,
        "final_value_cents": 0,
    }
    db.offers[offer["id"]] = offer
    return success_obj(serialize(offer), 201)


@bp.get("/reuse/donation-offers")
def list_offers():
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "StoreManager", "WarehouseAdmin", "Donor"])
    records = list(db.offers.values())
    if ctx.role == "Donor":
        records = [o for o in records if o["donor_id"] == ctx.user_id]
    for param in ("donor_id", "status", "category_id", "deconstruction_job_id"):
        v = request.args.get(param)
        if v is not None:
            if ctx.role == "Donor" and param == "donor_id" and v != ctx.user_id:
                raise err_not_owner("Donor may only list own offers")
            records = [o for o in records if o.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(o) for o in page], meta)


@bp.get("/reuse/donation-offers/<offerId>")
def get_offer(offerId):
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "StoreManager", "WarehouseAdmin", "Donor"])
    offer = _get_offer_or_404(offerId)
    _check_offer_owner(ctx, offer)
    return success_obj(serialize(offer))


@bp.post("/reuse/donation-offers/<offerId>/review")
def review_offer(offerId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    offer = _get_offer_or_404(offerId)
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409, "review requires OFFERED")
    offer["status"] = "UNDER_REVIEW"
    db.touch(offer)
    return success_obj(serialize(offer))


@bp.post("/reuse/donation-offers/<offerId>/request-info")
def request_info_offer(offerId):
    data = get_body()
    notes = req_str(data, "review_notes")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    offer = _get_offer_or_404(offerId)
    if offer["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409, "request-info requires UNDER_REVIEW")
    offer["status"] = "NEEDS_INFO"
    offer["review_notes"] = notes
    db.touch(offer)
    return success_obj(serialize(offer))


@bp.post("/reuse/donation-offers/<offerId>/resubmit")
def resubmit_offer(offerId):
    data = get_body()
    description_text = opt_str(data, "description_text")
    estimated_quantity = opt_num(data, "estimated_quantity", gt=0)
    condition_grade = opt_str(data, "condition_grade")
    if condition_grade is not None and condition_grade not in CONDITION_GRADES:
        raise err_invalid_request("condition_grade must be one of A, B, C, D")
    ctx = authenticate()
    require_role(ctx, ["Donor", "IntakeStaff"])
    offer = _get_offer_or_404(offerId)
    _check_offer_owner(ctx, offer)
    if offer["status"] != "NEEDS_INFO":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409, "resubmit requires NEEDS_INFO")
    if description_text is not None:
        offer["description_text"] = description_text
    if estimated_quantity is not None:
        offer["estimated_quantity"] = estimated_quantity
    if condition_grade is not None:
        offer["condition_grade"] = condition_grade
    offer["status"] = "UNDER_REVIEW"
    db.touch(offer)
    return success_obj(serialize(offer))


@bp.post("/reuse/donation-offers/<offerId>/accept")
def accept_offer(offerId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    offer = _get_offer_or_404(offerId)
    if offer["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409, "accept requires UNDER_REVIEW")
    category = db.categories[offer["category_id"]]
    if category["acceptance_status"] != "ACCEPTING":
        raise ApiError(
            "ERR_CATEGORY_NOT_ACCEPTING", 409, "Category is not accepting material"
        )
    if offer["condition_grade"] not in ("A", "B", "C"):
        raise ApiError(
            "ERR_CONDITION_BELOW_ACCEPTANCE",
            422,
            "Condition grade D is below acceptance criteria",
        )
    if offer["source_type"] == "DECONSTRUCTION":
        job = db.jobs.get(offer.get("deconstruction_job_id") or "")
        if job is None or job["status"] == "CANCELLED":
            raise ApiError(
                "ERR_JOB_CANCELLED", 409, "Linked deconstruction job is CANCELLED"
            )
    offer["status"] = "ACCEPTED"
    offer["estimated_value_cents"] = guidance_valuation(offer, category)
    db.touch(offer)
    return success_obj(serialize(offer))


@bp.post("/reuse/donation-offers/<offerId>/reject")
def reject_offer(offerId):
    data = get_body()
    reason = req_str(data, "decision_reason")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    offer = _get_offer_or_404(offerId)
    if offer["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409, "reject requires UNDER_REVIEW")
    offer["status"] = "REJECTED"
    offer["decision_reason"] = reason
    db.touch(offer)
    return success_obj(serialize(offer))


@bp.post("/reuse/donation-offers/<offerId>/receive")
def receive_offer(offerId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    offer = _get_offer_or_404(offerId)
    if offer["status"] != "ACCEPTED":
        raise ApiError("ERR_OFFER_NOT_ACCEPTED", 409, "receive requires ACCEPTED")
    if offer["source_type"] == "PICKUP":
        completed = any(
            a["subject_type"] == "DONATION_OFFER"
            and a["subject_id"] == offer["id"]
            and a["status"] == "COMPLETED"
            for a in db.appointments.values()
        )
        if not completed:
            raise ApiError(
                "ERR_OFFER_NOT_RECEIVABLE_SOURCE",
                409,
                "PICKUP offer lacks a COMPLETED pickup appointment",
            )
    elif offer["source_type"] == "DECONSTRUCTION":
        job = db.jobs.get(offer.get("deconstruction_job_id") or "")
        if job is None or job["status"] != "COMPLETED":
            raise ApiError(
                "ERR_OFFER_NOT_RECEIVABLE_SOURCE",
                409,
                "DECONSTRUCTION offer's job is not COMPLETED",
            )
    offer["status"] = "RECEIVED"
    offer["received_by_user_id"] = ctx.user_id
    db.touch(offer)
    return success_obj(serialize(offer))


@bp.post("/reuse/donation-offers/<offerId>/cancel")
def cancel_offer(offerId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["Donor", "IntakeStaff"])
    offer = _get_offer_or_404(offerId)
    _check_offer_owner(ctx, offer)
    if offer["status"] not in OFFER_NONTERMINAL_FOR_CANCEL:
        raise ApiError(
            "ERR_INVALID_OFFER_STATE", 409, "Offer cannot be cancelled from this state"
        )
    if offer["status"] == "ACCEPTED":
        booked = any(
            a["subject_type"] == "DONATION_OFFER"
            and a["subject_id"] == offer["id"]
            and a["status"] == "BOOKED"
            for a in db.appointments.values()
        )
        if booked:
            raise ApiError(
                "ERR_ACTIVE_APPOINTMENT_EXISTS",
                409,
                "A BOOKED pickup appointment references this offer",
            )
    offer["status"] = "CANCELLED"
    db.touch(offer)
    return success_obj(serialize(offer))


# ---------------------------------------------------------------------------
# Tax receipts
# ---------------------------------------------------------------------------


def _next_receipt_number():
    year = db.now().year
    seq = sum(1 for r in db.receipts.values() if r["_year"] == year) + 1
    return "R-%d-%d" % (year, seq), year


def _get_receipt_or_404(receipt_id):
    return lookup(db.receipts, "receipt", receipt_id)


def _check_receipt_owner(ctx, receipt):
    if ctx.role == "Donor" and receipt["donor_id"] != ctx.user_id:
        raise err_not_owner("Donor may only read own receipts")


def _apply_issue(receipt, appraisal_reference, appraisal_value_cents, issuer_id):
    """Pin valuation per receipt_final_valuation and mark the receipt ISSUED."""
    offer = db.offers[receipt["offer_id"]]
    item_sum = receipt_item_sum(receipt["offer_id"])
    if receipt_requires_appraisal(offer, item_sum):
        if appraisal_reference is None or appraisal_value_cents is None:
            raise ApiError(
                "ERR_APPRAISAL_REQUIRED",
                422,
                "Valued total at/above the appraisal threshold (or appraisal-review "
                "category) requires appraisal_reference and appraisal_value_cents",
            )
        receipt["valuation_method"] = "QUALIFIED_APPRAISAL"
        receipt["valued_total_cents"] = appraisal_value_cents
    else:
        receipt["valuation_method"] = "ESTIMATED_GUIDANCE"
        receipt["valued_total_cents"] = item_sum
    if appraisal_reference is not None:
        receipt["appraisal_reference"] = appraisal_reference
    if appraisal_value_cents is not None:
        receipt["appraisal_value_cents"] = appraisal_value_cents
    receipt["status"] = "ISSUED"
    receipt["issued_by_user_id"] = issuer_id
    receipt["issued_at"] = db.now()


@bp.post("/reuse/tax-receipts")
def create_receipt():
    data = get_body()
    offer_id = req_str(data, "offer_id")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    offer = lookup(db.offers, "offer", offer_id)
    # Referential linkage (priority 12)
    if offer["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_OFFER_STATE", 409, "Receipt drafting requires offer RECEIVED"
        )
    for r in db.receipts.values():
        if r["offer_id"] == offer_id and r["status"] in RECEIPT_NONTERMINAL:
            raise ApiError(
                "ERR_ACTIVE_RECEIPT_EXISTS",
                409,
                "A non-terminal receipt already exists for this offer",
            )
    number, year = _next_receipt_number()
    receipt = {
        **db.base_fields(),
        "donor_id": offer["donor_id"],
        "offer_id": offer_id,
        "receipt_number": number,
        "status": "DRAFT",
        "valuation_method": None,
        "valued_total_cents": 0,
        "appraisal_reference": None,
        "appraisal_value_cents": None,
        "received_by_user_id": offer["received_by_user_id"],
        "issued_by_user_id": "",
        "issued_at": None,
        "supersedes_receipt_id": None,
        "void_reason": "",
        "_year": year,
    }
    db.receipts[receipt["id"]] = receipt
    return success_obj(serialize(receipt), 201)


@bp.get("/reuse/tax-receipts")
def list_receipts():
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "WarehouseAdmin", "Donor"])
    records = list(db.receipts.values())
    if ctx.role == "Donor":
        records = [r for r in records if r["donor_id"] == ctx.user_id]
    for param in ("donor_id", "offer_id", "status", "supersedes_receipt_id"):
        v = request.args.get(param)
        if v is not None:
            if ctx.role == "Donor" and param == "donor_id" and v != ctx.user_id:
                raise err_not_owner("Donor may only list own receipts")
            records = [r for r in records if r.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(r) for r in page], meta)


@bp.get("/reuse/tax-receipts/<receiptId>")
def get_receipt(receiptId):
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "WarehouseAdmin", "Donor"])
    receipt = _get_receipt_or_404(receiptId)
    _check_receipt_owner(ctx, receipt)
    return success_obj(serialize(receipt))


@bp.post("/reuse/tax-receipts/<receiptId>/issue")
def issue_receipt(receiptId):
    data = get_body()
    appraisal_reference = opt_str(data, "appraisal_reference")
    appraisal_value_cents = opt_int(data, "appraisal_value_cents", min_value=0)
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    receipt = _get_receipt_or_404(receiptId)
    if receipt["status"] != "DRAFT":
        raise ApiError("ERR_RECEIPT_NOT_DRAFT", 409, "issue requires DRAFT")
    offer = db.offers[receipt["offer_id"]]
    if offer["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_OFFER_STATE", 409, "Offer must stand RECEIVED at issue"
        )
    # Segregation of duties (priority 8): issuer != receiver
    if ctx.user_id == receipt["received_by_user_id"]:
        raise ApiError(
            "ERR_RECEIPT_ISSUER_IS_RECEIVER",
            403,
            "The operator who received the goods may not issue the receipt",
        )
    _apply_issue(receipt, appraisal_reference, appraisal_value_cents, ctx.user_id)
    db.touch(receipt)
    # Cross-entity: offer RECEIVED -> RECEIPTED
    offer["status"] = "RECEIPTED"
    offer["final_value_cents"] = receipt["valued_total_cents"]
    db.touch(offer)
    # Donor standing recompute (cascade hop 2)
    donor = db.donors[offer["donor_id"]]
    recompute_donor_standing(donor)
    db.touch(donor)
    return success_obj(serialize(receipt))


@bp.post("/reuse/tax-receipts/<receiptId>/request-void")
def request_void_receipt(receiptId):
    data = get_body()
    reason = req_str(data, "void_reason")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    receipt = _get_receipt_or_404(receiptId)
    if receipt["status"] != "ISSUED":
        raise ApiError("ERR_RECEIPT_NOT_ISSUED", 409, "request-void requires ISSUED")
    receipt["status"] = "VOID_REQUESTED"
    receipt["void_reason"] = reason
    db.touch(receipt)
    return success_obj(serialize(receipt))


@bp.post("/reuse/tax-receipts/<receiptId>/confirm-void")
def confirm_void_receipt(receiptId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    receipt = _get_receipt_or_404(receiptId)
    if receipt["status"] != "VOID_REQUESTED":
        raise ApiError(
            "ERR_RECEIPT_NOT_VOID_REQUESTED", 409, "confirm-void requires VOID_REQUESTED"
        )
    receipt["status"] = "VOIDED"
    db.touch(receipt)
    # Revert the offer RECEIPTED -> RECEIVED
    offer = db.offers[receipt["offer_id"]]
    if offer["status"] == "RECEIPTED":
        offer["status"] = "RECEIVED"
        offer["final_value_cents"] = 0
        db.touch(offer)
    donor = db.donors[receipt["donor_id"]]
    recompute_donor_standing(donor)
    db.touch(donor)
    return success_obj(serialize(receipt))


@bp.post("/reuse/tax-receipts/<receiptId>/reject-void")
def reject_void_receipt(receiptId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    receipt = _get_receipt_or_404(receiptId)
    if receipt["status"] != "VOID_REQUESTED":
        raise ApiError(
            "ERR_RECEIPT_NOT_VOID_REQUESTED", 409, "reject-void requires VOID_REQUESTED"
        )
    receipt["status"] = "ISSUED"
    receipt["void_reason"] = ""
    db.touch(receipt)
    return success_obj(serialize(receipt))


@bp.post("/reuse/tax-receipts/<receiptId>/amend")
def amend_receipt(receiptId):
    data = get_body()
    expected_version = req_int(data, "expected_receipt_version")
    appraisal_reference = opt_str(data, "appraisal_reference")
    appraisal_value_cents = opt_int(data, "appraisal_value_cents", min_value=0)
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    receipt = _get_receipt_or_404(receiptId)
    # OCC (priority 6) precedes the state check (priority 7)
    if expected_version != receipt["version"]:
        raise ApiError(
            "ERR_STALE_RECEIPT_VERSION",
            412,
            "expected_receipt_version does not match the receipt's current version",
        )
    if receipt["status"] != "ISSUED":
        raise ApiError("ERR_RECEIPT_NOT_ISSUED", 409, "amend requires ISSUED")
    if ctx.user_id == receipt["received_by_user_id"]:
        raise ApiError(
            "ERR_RECEIPT_ISSUER_IS_RECEIVER",
            403,
            "The operator who received the goods may not amend the receipt",
        )
    # Validate the appraisal mandate BEFORE mutating anything (atomicity):
    offer = db.offers[receipt["offer_id"]]
    item_sum = receipt_item_sum(receipt["offer_id"])
    if receipt_requires_appraisal(offer, item_sum) and (
        appraisal_reference is None or appraisal_value_cents is None
    ):
        raise ApiError(
            "ERR_APPRAISAL_REQUIRED",
            422,
            "Valued total at/above the appraisal threshold (or appraisal-review "
            "category) requires appraisal_reference and appraisal_value_cents",
        )
    # Supersede the amended receipt
    receipt["status"] = "SUPERSEDED"
    db.touch(receipt)
    # Create the replacement directly in ISSUED
    number, year = _next_receipt_number()
    replacement = {
        **db.base_fields(),
        "donor_id": receipt["donor_id"],
        "offer_id": receipt["offer_id"],
        "receipt_number": number,
        "status": "DRAFT",
        "valuation_method": None,
        "valued_total_cents": 0,
        "appraisal_reference": None,
        "appraisal_value_cents": None,
        "received_by_user_id": receipt["received_by_user_id"],
        "issued_by_user_id": "",
        "issued_at": None,
        "supersedes_receipt_id": receipt["id"],
        "void_reason": "",
        "_year": year,
    }
    _apply_issue(replacement, appraisal_reference, appraisal_value_cents, ctx.user_id)
    db.receipts[replacement["id"]] = replacement
    donor = db.donors[receipt["donor_id"]]
    recompute_donor_standing(donor)
    db.touch(donor)
    return success_obj(serialize(replacement), 201)
