"""Campaign lifecycle: windows, posture, shrinkage accounting (PRD 3.2, 3.5)."""

from decimal import Decimal

from flask import Blueprint

from auth import ALL_ROLES, authenticate, get_campaign, get_employer
from envelope import created, ok
from errors import ApiError
from store import (D, ZERO, base_entity, db, now, now_iso, q2, touch)
from validators import (bad, body, get_date, get_id, get_int, get_money,
                        iso_date_str)

from services import aggregates, calc

bp = Blueprint("campaigns", __name__)


def _campaign_employer(campaign):
    return db.employers[campaign["employer_id"]]


@bp.get("/campaigns/<campaign_id>")
def read_campaign(campaign_id):
    authenticate(ALL_ROLES)
    return ok(get_campaign(campaign_id))


@bp.post("/campaigns")
def create_campaign():
    authenticate(("UnitedFundAdmin", "CampaignCoordinator"))
    data = body()
    employer_id = get_id(data, "employer_id")
    campaign_year = get_int(data, "campaign_year", minimum=2020, maximum=2100)
    start = get_date(data, "solicitation_start_date")
    end = get_date(data, "solicitation_end_date")
    if not (end > start):
        bad("Field 'solicitation_end_date' must be strictly later than 'solicitation_start_date'.")
    reserve = get_money(
        data, "loss_reserve_amount", minimum=0, required=False, default=ZERO
    )

    employer = get_employer(employer_id)

    # Gate 27: half-open [start, end) exclusivity across the employer's campaigns.
    for other in db.campaigns.values():
        if other["employer_id"] != employer_id:
            continue
        if other["posture"] == "ESCROW_HOLD":
            continue
        other_start = other["solicitation_start_date"]
        other_end = other["solicitation_end_date"]
        if start.isoformat() < other_end and other_start < end.isoformat():
            raise ApiError("ERR_CAMPAIGN_WINDOW_OVERLAP")

    row = base_entity()
    row.update({
        "employer_id": employer_id,
        "campaign_year": campaign_year,
        "solicitation_start_date": iso_date_str(start),
        "solicitation_end_date": iso_date_str(end),
        "loss_reserve_amount": q2(reserve),
        "posture": "PLANNED",
        "confirmed_gross_total": ZERO,
        "designated_gross_total": ZERO,
        "undesignated_gross_total": ZERO,
        "designation_fee_total": ZERO,
        "projected_payroll_pledge_total": ZERO,
        "provisional_estimated_loss": None,
        "provisional_net_expected_revenue": None,
        "reserve_absorbed_amount": None,
        "final_actual_loss": None,
        "final_net_expected_revenue": None,
        "realized_shrinkage_rate_bps": None,
        "solicitation_closed_at": None,
        "reconciled_at": None,
    })
    db.campaigns[row["id"]] = row
    aggregates.recompute_employer_active_campaign_count(employer)
    return created(row)


@bp.post("/campaigns/<campaign_id>/open")
def open_campaign(campaign_id):
    authenticate(("UnitedFundAdmin", "CampaignCoordinator"))
    body()
    campaign = get_campaign(campaign_id)
    employer = _campaign_employer(campaign)
    # Gate 10 precedes gate 12 (PRD 2.10).
    if employer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_NOT_ACTIVE")
    if campaign["posture"] != "PLANNED":
        raise ApiError("ERR_CAMPAIGN_INVALID_STATE")
    campaign["posture"] = "OPEN"
    touch("campaign", campaign)
    aggregates.recompute_employer_active_campaign_count(employer)
    return ok(campaign)


@bp.post("/campaigns/<campaign_id>/close-solicitation")
def close_solicitation(campaign_id):
    authenticate(("UnitedFundAdmin",))
    body()
    campaign = get_campaign(campaign_id)
    if campaign["posture"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_INVALID_STATE")
    employer = _campaign_employer(campaign)

    campaign["posture"] = "SOLICITATION_CLOSED"
    campaign["solicitation_closed_at"] = now_iso()
    aggregates.recompute_projected_payroll_total(campaign)
    loss = calc.provisional_loss(
        campaign["projected_payroll_pledge_total"],
        employer["historical_shrinkage_rate_bps"],
    )
    campaign["provisional_estimated_loss"] = loss
    campaign["provisional_net_expected_revenue"] = q2(
        D(campaign["confirmed_gross_total"]) - loss
    )
    touch("campaign", campaign)
    return ok(campaign)


@bp.post("/campaigns/<campaign_id>/reconcile")
def reconcile_campaign(campaign_id):
    authenticate(("UnitedFundAdmin", "FinanceReviewer"))
    body()
    campaign = get_campaign(campaign_id)
    if campaign["posture"] != "SOLICITATION_CLOSED":
        raise ApiError("ERR_CAMPAIGN_INVALID_STATE")

    pledges = aggregates.campaign_pledges(campaign_id)
    for pledge in pledges:
        if (pledge["designation_status"] in ("CONFIRMED", "AMENDED")
                and pledge["collection_status"] == "PENDING"):
            raise ApiError("ERR_CAMPAIGN_NOT_FULLY_REMITTED")

    # FINAL variant: candidate set walked created_at ASC, gross_amount DESC,
    # donor_reference ASC (PRD 3.5). No property of `id` is consulted.
    candidates = [
        p for p in pledges
        if p["designation_status"] in aggregates.CONFIRMED_LIKE
        and p["collection_status"] in ("PARTIAL", "WRITTEN_OFF")
        and D(p["uncollected_amount"]) > 0
    ]
    candidates.sort(key=lambda p: (p["created_at"], -D(p["gross_amount"]), p["donor_reference"]))
    absorbed, final_loss = calc.final_loss(candidates, campaign["loss_reserve_amount"])
    campaign["reserve_absorbed_amount"] = absorbed
    campaign["final_actual_loss"] = final_loss
    campaign["final_net_expected_revenue"] = q2(
        D(campaign["confirmed_gross_total"]) - final_loss
    )
    bps = calc.realized_shrinkage_bps(final_loss, campaign["confirmed_gross_total"])
    campaign["realized_shrinkage_rate_bps"] = bps

    for pledge in pledges:
        if pledge["designation_status"] in ("CONFIRMED", "AMENDED"):
            pledge["designation_status"] = "LOCKED"
            touch("pledge", pledge)

    campaign["reconciled_at"] = now_iso()
    employer = _campaign_employer(campaign)
    if bps < calc.SHRINKAGE_ESCROW_THRESHOLD_BPS:
        campaign["posture"] = "RECONCILED"
        touch("campaign", campaign)
    else:
        campaign["posture"] = "ESCROW_HOLD"
        touch("campaign", campaign)
        # Escrow-hold cascade (PRD 2.8): employer SUSPENDED, coordinators INACTIVE.
        employer["status"] = "SUSPENDED"
        employer["suspended_reason"] = "ESCROW_HOLD_SHRINKAGE"
        touch("employer", employer)
        for coordinator in db.coordinators.values():
            if coordinator["employer_id"] == employer["id"] and coordinator["status"] == "ACTIVE":
                coordinator["status"] = "INACTIVE"
                touch("coordinator", coordinator)
    aggregates.recompute_employer_active_campaign_count(employer)
    return ok(campaign)
