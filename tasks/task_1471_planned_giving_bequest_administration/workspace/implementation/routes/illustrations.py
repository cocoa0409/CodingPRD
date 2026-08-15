"""Illustrations: create (with supersede + rate pin), list, read, book (PRD 3.2)."""
from flask import Blueprint, g

import store
from domain import (
    FREQUENCIES,
    VEHICLES,
    active_table_covering,
    lookup,
    matches,
    paginate,
    sort_created,
    view,
)
from envelope import success
from errors import ApiError
from giftcalc import check_vehicle_fields, economics
from security import ALL_ROLES, require_roles
from store import base_fields, touch
from validate import funding_month_start, get_body, validate_body

bp = Blueprint("illustrations", __name__)


@bp.post("/giving/illustrations")
@require_roles("GiftOfficer")
def create_illustration():
    body = get_body()
    validate_body(
        body,
        {
            "donor_id": ("str", True, None),
            "vehicle_type": ("str", True, VEHICLES),
            "gift_amount_cents": ("int", True, None),
            "payout_rate_bps": ("int", False, None),
            "payment_frequency": ("str", False, FREQUENCIES),
            "lives": ("int", False, None),
            "annuitant_1_age": ("int", False, None),
            "annuitant_2_age": ("int", False, None),
            "funding_month": ("funding_month", True, None),
            "supersedes_illustration_id": ("str", False, None),
        },
    )
    # existence (path n/a, then body FKs)
    donor = lookup(store.donors, body["donor_id"], "Donor")
    predecessor = None
    if body.get("supersedes_illustration_id") is not None:
        predecessor = lookup(
            store.illustrations, body["supersedes_illustration_id"], "Illustration"
        )
        # supersede is a transition on the predecessor: it must be OPEN
        if predecessor["status"] != "OPEN":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "supersedes_illustration_id target is not OPEN",
            )
    # donor vital state
    if donor["vital_status"] != "LIVING":
        raise ApiError(
            "ERR_DONOR_STATE_MISMATCH", 409, "Donor must be LIVING to illustrate"
        )

    lives = body.get("lives", 1)
    if lives not in (1, 2):
        raise ApiError("ERR_INVALID_REQUEST", 400, "lives must be 1 or 2")
    payload = {
        "payout_rate_bps": body.get("payout_rate_bps"),
        "lives": lives,
        "annuitant_1_age": body.get("annuitant_1_age"),
        "annuitant_2_age": body.get("annuitant_2_age"),
    }
    check_vehicle_fields(body["vehicle_type"], payload)

    # pin the ACTIVE rate table covering funding_month
    table = active_table_covering(funding_month_start(body["funding_month"]))
    if table is None:
        raise ApiError(
            "ERR_RATE_TABLE_NOT_ACTIVE",
            409,
            "No ACTIVE rate table covers funding_month",
        )

    annual, pv, deduction = economics(
        body["vehicle_type"],
        body["gift_amount_cents"],
        body.get("payout_rate_bps"),
        lives,
        body.get("annuitant_1_age"),
        body.get("annuitant_2_age"),
        table["discount_rate_bps"],
    )

    illustration = base_fields()
    illustration.update(
        {
            "donor_id": donor["id"],
            "vehicle_type": body["vehicle_type"],
            "gift_amount_cents": body["gift_amount_cents"],
            "payout_rate_bps": body.get("payout_rate_bps"),
            "payment_frequency": body.get("payment_frequency", "QUARTERLY"),
            "lives": lives,
            "annuitant_1_age": body.get("annuitant_1_age"),
            "annuitant_2_age": body.get("annuitant_2_age"),
            "funding_month": body["funding_month"],
            "rate_table_id": table["id"],
            "illustrated_annual_annuity_cents": annual,
            "illustrated_deduction_cents": deduction,
            "status": "OPEN",
            "supersedes_illustration_id": body.get("supersedes_illustration_id"),
            "created_by_user_id": g.user_id,
        }
    )
    store.illustrations[illustration["id"]] = illustration

    # side effect: the OPEN predecessor flips to SUPERSEDED
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        touch(predecessor)

    return success(view(illustration), 201)


@bp.get("/giving/illustrations")
@require_roles(*ALL_ROLES)
def list_illustrations():
    items = [
        i
        for i in sort_created(store.illustrations.values())
        if matches(
            i,
            {
                "donor_id": None,
                "rate_table_id": None,
                "supersedes_illustration_id": None,
                "status": None,
            },
        )
    ]
    page, meta = paginate(items)
    return success([view(i) for i in page], 200, meta)


@bp.get("/giving/illustrations/<illustration_id>")
@require_roles(*ALL_ROLES)
def get_illustration(illustration_id):
    return success(
        view(lookup(store.illustrations, illustration_id, "Illustration")), 200
    )


@bp.post("/giving/illustrations/<illustration_id>/book")
@require_roles("GiftOfficer")
def book_illustration(illustration_id):
    illustration = lookup(store.illustrations, illustration_id, "Illustration")
    validate_body(get_body(), {})  # no input fields
    if illustration["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only an OPEN illustration can be booked",
        )
    donor = store.donors.get(illustration["donor_id"])
    if donor is None or donor["vital_status"] != "LIVING":
        raise ApiError(
            "ERR_DONOR_STATE_MISMATCH", 409, "Donor must be LIVING to book"
        )

    # creates a DRAFT GiftAgreement prefilled from the illustration
    agreement = base_fields()
    agreement.update(
        {
            "donor_id": illustration["donor_id"],
            "illustration_id": illustration["id"],
            "vehicle_type": illustration["vehicle_type"],
            "gift_amount_cents": illustration["gift_amount_cents"],
            "payout_rate_bps": illustration["payout_rate_bps"],
            "payment_frequency": illustration["payment_frequency"],
            "lives": illustration["lives"],
            "annuitant_1_age": illustration["annuitant_1_age"],
            "annuitant_2_age": illustration["annuitant_2_age"],
            "funding_month": illustration["funding_month"],
            "rate_table_id": illustration["rate_table_id"],
            "status": "DRAFT",
            "executed_at": None,
            "executed_by_user_id": None,
            "annual_annuity_cents": None,
            "booked_deduction_cents": None,
            "corpus_value_cents": None,
            "actuarial_liability_cents": None,
            "remainder_value_cents": None,
            "reserve_requirement_cents": 0,
            "surrender_value_cents": None,
            "fund_id": None,
            "restriction_type": "UNRESTRICTED",
            "restriction_text": None,
        }
    )
    store.agreements[agreement["id"]] = agreement

    illustration["status"] = "BOOKED"
    touch(illustration)

    from domain import agreement_view

    return success(agreement_view(agreement), 201)
