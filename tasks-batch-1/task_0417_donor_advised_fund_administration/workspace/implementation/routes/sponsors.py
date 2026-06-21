"""Sponsor endpoints and the quarterly close (PRD 3.1, 3.7)."""
from flask import Blueprint

from db import db, common_create_fields, touch, LOCK
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import calc, serialize
from services.accounts import (
    recompute_account, active_allocations, post_ledger,
)
from services.lookup import get_or_404, require_string, optional_nonneg_int, filtered_sorted

bp = Blueprint("sponsors", __name__)

READ_ROLES = {"SponsorAdmin", "ComplianceOfficer", "ContributionAdmin", "GrantOfficer", "DonorAdvisor"}


@bp.post("/daf/sponsors")
def create_sponsor():
    _, role = get_identity()
    require_role(role, {"SponsorAdmin"})
    body = get_json_body()
    name = require_string(body, "name")
    ein = require_string(body, "ein")
    # Optional policy params with PRD 3.1 defaults.
    minimum_grant_cents = optional_nonneg_int(body, "minimum_grant_cents", 5000)
    inactivity_quarters = optional_nonneg_int(body, "inactivity_quarters", 8)
    admin_fee_bps_default = optional_nonneg_int(body, "admin_fee_bps_default", 50)

    with LOCK:
        sponsor = common_create_fields()
        sponsor.update({
            "name": name,
            "ein": ein,
            "minimum_grant_cents": minimum_grant_cents,
            "inactivity_quarters": inactivity_quarters,
            "admin_fee_bps_default": admin_fee_bps_default,
            "current_quarter_index": 0,  # fiscal clock starts at 0 (PRD 2.10/3.1)
        })
        db.sponsors[sponsor["id"]] = sponsor
    return object_response(serialize.sponsor(sponsor), status=201)


@bp.get("/daf/sponsors/<sponsor_id>")
def get_sponsor(sponsor_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    sponsor = get_or_404(db.sponsors, sponsor_id)
    return object_response(serialize.sponsor(sponsor))


@bp.post("/daf/sponsors/<sponsor_id>/close_quarter")
def close_quarter(sponsor_id):
    _, role = get_identity()
    require_role(role, {"SponsorAdmin"})
    with LOCK:
        sponsor = get_or_404(db.sponsors, sponsor_id)
        # PRD 3.7: increment current_quarter_index by one, THEN for each account
        # accrue the quarter's admin fee and re-evaluate the inactivity policy.
        sponsor["current_quarter_index"] += 1
        touch(sponsor)

        accounts = [a for a in db.accounts.values() if a["sponsor_id"] == sponsor_id]
        accounts.sort(key=lambda a: a["_seq"])
        for account in accounts:
            _accrue_admin_fee(account)
            _evaluate_inactivity(account, sponsor)
    return object_response(serialize.sponsor(sponsor))


def _accrue_admin_fee(account):
    """Quarterly admin fee (PRD 3.7): round each allocation's fee first, then sum."""
    account_fee = 0
    for a in active_allocations(account["id"]):
        pool = db.pools[a["investment_pool_id"]]
        invested = calc.allocation_value_cents(a["units_micro"], pool["nav_per_unit_cents"])
        account_fee += calc.per_allocation_quarterly_fee(invested, pool["fee_bps"])
    if account_fee != 0:
        account["admin_fee_accrued_cents"] += account_fee
        post_ledger(account, "ADMIN_FEE", -account_fee, "DonorAccount", account["id"])
    # grantable recomputed (PRD 3.7); always recompute so derived stays consistent.
    recompute_account(account)
    touch(account)


def _evaluate_inactivity(account, sponsor):
    """Inactivity policy (PRD 3.7): ACTIVE -> INACTIVE when inactive long enough
    AND grantable_balance_cents > 0."""
    if account["status"] != "ACTIVE":
        return
    last_paid = account["last_grant_paid_quarter"]
    long_enough = (
        last_paid is None
        or (sponsor["current_quarter_index"] - last_paid) >= sponsor["inactivity_quarters"]
    )
    if long_enough and account["grantable_balance_cents"] > 0:
        account["status"] = "INACTIVE"
        touch(account)
