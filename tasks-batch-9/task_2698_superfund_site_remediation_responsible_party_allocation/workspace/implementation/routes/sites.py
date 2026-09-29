"""Site listing, oversight billing and the statutory five-year review."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import derive
import logical_clock
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from numeric import frac
from routes import common

bp = Blueprint("sites", __name__)

ZERO = Decimal("0.00")


@bp.post("/sites")
def create_site():
    require(K.ROLE_RPM)
    body = shape.get_body()
    name = shape.str_field(body, "name")
    epa_region = shape.int_field(body, "epa_region", lo=1, hi=10)
    hrs_score = shape.num_field(body, "hrs_score", scale=2, minimum=0, maximum=100)

    site = common.new_record(
        {
            "name": name,
            "epa_region": epa_region,
            "hrs_score": hrs_score,
            "listing_status": "PROPOSED",
            "listing_reference": None,
            "cost_posture": "OPEN",
            "oversight_direct_cents": 0,
            "oversight_indirect_rate_bp": 0,
            "oversight_indirect_cents": 0,
            "oversight_billed_cents": 0,
            "oversight_cap_utilization_pct": None,
            "total_response_cost_cents": 0,
            "recovered_cost_cents": 0,
            "orphan_write_off_cents": 0,
            "unrecovered_cost_cents": 0,
            "adopted_round_id": None,
            "verified_waste_volume_tons": ZERO,
            "construction_complete_at": None,
            "five_year_review_due_at": None,
            "last_five_year_review_at": None,
            "last_protectiveness_determination": None,
        }
    )
    store.sites[site["id"]] = site
    return common.respond(site, serialize.site, 201)


@bp.post("/sites/<site_id>/list-on-npl")
def list_on_npl(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    reference = shape.str_field(body, "listing_reference")
    site = common.get_site(site_id)
    common.state(site["listing_status"] == "PROPOSED")
    if frac(site["hrs_score"]) < frac(Decimal(K.HRS_LISTING_THRESHOLD)):
        raise ApiError("ERR_HRS_SCORE_BELOW_THRESHOLD")

    txn.watch(site)
    site["listing_status"] = "LISTED"
    site["listing_reference"] = reference
    derive.recompute_site_derived(site)
    return common.respond(site, serialize.site)


@bp.post("/sites/<site_id>/oversight-costs")
def post_oversight_cost(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    incurred = shape.money_field(body, "incurred_cents", minimum=0)
    category = shape.str_field(body, "cost_category")
    incurred_on = shape.date_field(body, "incurred_on")
    site = common.get_site(site_id)
    common.deny_frozen(site)
    common.deny_deleted(site)

    # Priority 39, and the last check of all: a refused posting leaves every
    # field exactly as it was, so the cap is tested prospectively.
    decree = derive.governing_decree(site)
    if decree is not None:
        _rate, _indirect, billed = derive.prospective_oversight(site, incurred)
        if billed > decree["oversight_cost_cap_cents"]:
            raise ApiError("ERR_OVERSIGHT_CAP_EXCEEDED")

    posting = common.new_record(
        {
            "site_id": site["id"],
            "incurred_cents": incurred,
            "cost_category": category,
            "incurred_on": incurred_on,
        },
        mutable=False,
    )
    store.oversight_postings[posting["id"]] = posting
    derive.recompute_site_derived(site)
    return common.respond(site, serialize.site)


@bp.post("/sites/<site_id>/five-year-review")
def five_year_review(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    determination = shape.enum_field(body, "protectiveness_determination", K.DETERMINATIONS)
    deletion = shape.bool_field(body, "deletion_recommended")
    summary = shape.str_field(body, "review_summary")
    site = common.get_site(site_id)

    # Priority 11 before priority 28: a site in the wrong phase reports the
    # phase error even when no review is due.
    common.require_phase(site, ["OM_PHASE"])
    due = site["five_year_review_due_at"]
    if due is None or logical_clock.now() < due:
        raise ApiError("ERR_FIVE_YEAR_REVIEW_NOT_DUE")

    retiring = determination == "PROTECTIVE" and deletion
    if determination == "NOT_PROTECTIVE":
        pass
    elif retiring:
        common.state(site["unrecovered_cost_cents"] <= 0)
    elif deletion:
        # PROTECTIVE_SHORT_TERM with deletion_recommended has no declared branch.
        common.state(False)

    txn.watch(site)
    site["last_protectiveness_determination"] = determination
    site["last_five_year_review_at"] = logical_clock.now()

    if determination == "PROTECTIVE":
        # A PROTECTIVE determination has a smaller cascade of its own: the
        # contract sitting in CONSTRUCTION_COMPLETE closes, nothing else changes.
        for contract in derive.site_contracts(site["id"]):
            if contract["status"] == "CONSTRUCTION_COMPLETE":
                txn.watch(contract)
                contract["status"] = "CLOSED"

    if determination == "NOT_PROTECTIVE":
        derive.advance_review_due(site)
        derive.not_protective_cascade(site)
    elif retiring:
        site["listing_status"] = "DELETED_FROM_NPL"
        # A site retired from the docket has no further review obligation.
        derive.recompute_site_derived(site)
    else:
        derive.advance_review_due(site)
        derive.recompute_site_derived(site)
    return common.respond(site, serialize.site)


@bp.post("/_clock/set_current_utc")
def set_clock():
    """Mutates no entity and increments no version."""
    require(*K.ALL_ROLES)
    body = shape.get_body()
    instant = shape.datetime_field(body, "current_utc")
    logical_clock.set_now(instant)
    return common.respond_raw({"current_utc": logical_clock.iso(instant)})
