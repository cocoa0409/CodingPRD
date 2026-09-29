"""Pledges, donor designations, remittance and write-off (PRD 3.3, 3.4, 3.5)."""

from flask import Blueprint

from auth import (ALL_ROLES, authenticate, coordinator_of_employer, get_agency,
                  get_campaign, get_pledge, ownership_violation)
from envelope import created, filter_str, ok, paginate
from errors import ApiError
from store import D, ZERO, base_entity, db, q2, touch
from validators import (bad, body, get_date, get_designations, get_enum, get_id,
                        get_int, get_money, get_str)

from services import aggregates, calc

bp = Blueprint("pledges", __name__)

GIVING_METHODS = ("PAYROLL_DEDUCTION", "ONE_TIME_CHECK", "CREDIT_CARD", "STOCK_GIFT")
WRITE_OFF_REASONS = ("TERMINATION", "LEAVE_OF_ABSENCE", "DONOR_REVOKED", "EMPLOYER_DEFAULT")
DESIGNATION_ELIGIBLE = ("GOOD_STANDING", "PROBATION")


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #


def _resolve_designation_agencies(designations):
    """Gate 5: every designations[].agency_id must resolve."""
    return [get_agency(line["agency_id"]) for line in designations]


def _check_designation_rules(designations, agencies, gross_amount):
    # Gate 26 -> 31 -> 32, in ladder order across the whole array.
    for agency in agencies:
        if agency["membership_status"] not in DESIGNATION_ELIGIBLE:
            raise ApiError("ERR_DESIGNATION_TARGET_INELIGIBLE")
    for line in designations:
        if D(line["designated_amount"]) < calc.MIN_DESIGNATION_AMOUNT:
            raise ApiError("ERR_DESIGNATION_BELOW_MINIMUM")
    total = ZERO
    for line in designations:
        total = total + D(line["designated_amount"])
    if total > D(gross_amount):
        raise ApiError("ERR_DESIGNATION_EXCEEDS_GROSS")


def _create_lines(pledge, designations):
    rows = []
    for index, line in enumerate(designations):
        row = base_entity()
        row.update({
            "pledge_id": pledge["id"],
            "agency_id": line["agency_id"],
            "designation_sequence": index + 1,
            "designated_amount": q2(line["designated_amount"]),
            "processing_fee": ZERO,
            "net_designated_amount": ZERO,
            "collected_designated_amount": ZERO,
            "status": "ACTIVE",
        })
        db.designations[row["id"]] = row
        rows.append(row)
    return rows


def _coordinator_pledge_ownership(role, user_id, pledge, campaign):
    """Gate 6 for writes against an existing pledge."""
    if role != "CampaignCoordinator":
        return
    coordinator_of_employer(user_id, campaign["employer_id"])
    if pledge.get("recorded_by_coordinator_id") != user_id:
        ownership_violation()


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #


@bp.get("/pledges/<pledge_id>")
def read_pledge(pledge_id):
    authenticate(ALL_ROLES)
    return ok(get_pledge(pledge_id))


@bp.get("/pledges")
def list_pledges():
    authenticate(ALL_ROLES)
    rows = list(db.pledges.values())
    campaign_id = filter_str("campaign_id")
    coordinator_id = filter_str("recorded_by_coordinator_id")
    giving_method = filter_str("giving_method")
    designation_status = filter_str("designation_status")
    collection_status = filter_str("collection_status")
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if coordinator_id is not None:
        rows = [r for r in rows if r.get("recorded_by_coordinator_id") == coordinator_id]
    if giving_method is not None:
        rows = [r for r in rows if r["giving_method"] == giving_method]
    if designation_status is not None:
        rows = [r for r in rows if r["designation_status"] == designation_status]
    if collection_status is not None:
        rows = [r for r in rows if r["collection_status"] == collection_status]
    # PRD 2.3: created_at ASC then donor_reference ASC.
    rows.sort(key=lambda r: (r["created_at"], r["donor_reference"]))
    return paginate(rows)


@bp.get("/pledges/<pledge_id>/designations")
def list_pledge_designations(pledge_id):
    authenticate(ALL_ROLES)
    get_pledge(pledge_id)
    rows = aggregates.pledge_lines(pledge_id)
    status = filter_str("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # PRD 2.3: ascending designation_sequence, superseded and uncollected included.
    rows.sort(key=lambda r: (r["designation_sequence"], r["_seq"]))
    return paginate(rows)


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #


@bp.post("/campaigns/<campaign_id>/pledges")
def record_pledge(campaign_id):
    role, user_id = authenticate(("UnitedFundAdmin", "CampaignCoordinator"))
    data = body()
    donor_reference = get_str(data, "donor_reference", min_len=1, max_len=40)
    giving_method = get_enum(data, "giving_method", GIVING_METHODS)
    gross_amount = get_money(data, "gross_amount", exclusive_min=0)
    designations = get_designations(data, "designations", required=False)
    if designations is None:
        designations = []

    campaign = get_campaign(campaign_id)
    agencies = _resolve_designation_agencies(designations)

    if role == "CampaignCoordinator":
        coordinator_of_employer(user_id, campaign["employer_id"])

    if campaign["posture"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")

    _check_designation_rules(designations, agencies, gross_amount)

    # Gate 33 before gate 42 (PRD 2.10).
    for other in aggregates.campaign_pledges(campaign_id):
        if other["donor_reference"] == donor_reference:
            raise ApiError("ERR_DUPLICATE_DONOR_REFERENCE")

    employer = db.employers[campaign["employer_id"]]
    if giving_method == "PAYROLL_DEDUCTION" and employer["payroll_periods_per_year"] == 0:
        raise ApiError("ERR_PAYROLL_METHOD_UNAVAILABLE")

    pledge = base_entity()
    pledge.update({
        "campaign_id": campaign_id,
        "recorded_by_coordinator_id": user_id if role == "CampaignCoordinator" else None,
        "donor_reference": donor_reference,
        "giving_method": giving_method,
        "gross_amount": q2(gross_amount),
        "designation_status": "DRAFT",
        "collection_status": "PENDING",
        "designated_amount_total": ZERO,
        "undesignated_amount": ZERO,
        "designation_fee_total": ZERO,
        "net_designated_total": ZERO,
        "collected_amount": ZERO,
        "uncollected_amount": ZERO,
        "amend_count": 0,
        "write_off_reason_code": None,
    })
    db.pledges[pledge["id"]] = pledge
    lines = _create_lines(pledge, designations)
    calc.allocate_designation_fees(pledge, lines)
    if role == "CampaignCoordinator":
        aggregates.recompute_coordinator_pledge_count(db.coordinators.get(user_id))
    return created(pledge)


@bp.post("/pledges/<pledge_id>/confirm")
def confirm_pledge(pledge_id):
    role, user_id = authenticate(("UnitedFundAdmin", "CampaignCoordinator"))
    body()
    pledge = get_pledge(pledge_id)
    campaign = db.campaigns[pledge["campaign_id"]]
    _coordinator_pledge_ownership(role, user_id, pledge, campaign)
    if campaign["posture"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")
    if pledge["designation_status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_PLEDGE_NOT_CONFIRMED")

    pledge["designation_status"] = "CONFIRMED"
    touch("pledge", pledge)
    aggregates.recompute_campaign_totals(campaign)
    aggregates.recompute_coordinator_pledge_count(
        db.coordinators.get(pledge.get("recorded_by_coordinator_id"))
    )
    aggregates.recompute_agency_passthrough_for_ids(
        [line["agency_id"] for line in aggregates.active_lines(pledge_id)]
    )
    return ok(pledge)


@bp.post("/pledges/<pledge_id>/designations:amend")
def amend_designations(pledge_id):
    role, user_id = authenticate(("UnitedFundAdmin", "CampaignCoordinator"))
    data = body()
    expected_version = get_int(data, "expected_pledge_version", minimum=0)
    designations = get_designations(data, "designations", required=True)

    pledge = get_pledge(pledge_id)
    agencies = _resolve_designation_agencies(designations)
    campaign = db.campaigns[pledge["campaign_id"]]
    _coordinator_pledge_ownership(role, user_id, pledge, campaign)

    # Gate 8 precedes the campaign and pledge state gates (PRD 2.10).
    if expected_version != pledge["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if campaign["posture"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")
    if pledge["designation_status"] != "CONFIRMED":
        raise ApiError("ERR_PLEDGE_NOT_CONFIRMED")

    _check_designation_rules(designations, agencies, pledge["gross_amount"])

    losing_agency_ids = []
    for line in aggregates.active_lines(pledge_id):
        losing_agency_ids.append(line["agency_id"])
        line["status"] = "SUPERSEDED"
        line["collected_designated_amount"] = ZERO
        touch("designation", line)

    fresh = _create_lines(pledge, designations)
    calc.allocate_designation_fees(pledge, fresh)
    pledge["amend_count"] = pledge["amend_count"] + 1
    pledge["designation_status"] = "AMENDED"
    touch("pledge", pledge)

    aggregates.recompute_campaign_totals(campaign)
    aggregates.recompute_agency_passthrough_for_ids(
        losing_agency_ids + [line["agency_id"] for line in fresh]
    )
    return ok(pledge)


@bp.post("/pledges/<pledge_id>/collections")
def record_collection(pledge_id):
    authenticate(("UnitedFundAdmin", "FinanceReviewer"))
    data = body()
    amount = get_money(data, "amount", exclusive_min=0)
    get_date(data, "remitted_on")

    pledge = get_pledge(pledge_id)
    campaign = db.campaigns[pledge["campaign_id"]]
    if campaign["posture"] not in ("OPEN", "SOLICITATION_CLOSED"):
        raise ApiError("ERR_CAMPAIGN_INVALID_STATE")
    if pledge["designation_status"] not in ("CONFIRMED", "AMENDED"):
        raise ApiError("ERR_PLEDGE_NOT_CONFIRMED")
    if pledge["collection_status"] in ("COLLECTED", "WRITTEN_OFF"):
        raise ApiError("ERR_PLEDGE_COLLECTION_TERMINAL")

    outstanding = D(pledge["gross_amount"]) - D(pledge["collected_amount"])
    if D(amount) > outstanding:
        raise ApiError("ERR_COLLECTION_EXCEEDS_OUTSTANDING")

    if D(amount) == outstanding:
        pledge["collected_amount"] = q2(pledge["gross_amount"])
        pledge["uncollected_amount"] = ZERO
        pledge["collection_status"] = "COLLECTED"
    else:
        pledge["collected_amount"] = q2(D(pledge["collected_amount"]) + D(amount))
        pledge["uncollected_amount"] = q2(
            D(pledge["gross_amount"]) - D(pledge["collected_amount"])
        )
        pledge["collection_status"] = "PARTIAL"
    touch("pledge", pledge)

    lines = aggregates.active_lines(pledge_id)
    calc.scale_collected_designated(pledge, lines)
    for line in lines:
        touch("designation", line)
    aggregates.recompute_agency_passthrough_for_ids([l["agency_id"] for l in lines])
    return ok(pledge)


@bp.post("/pledges/<pledge_id>/write-off")
def write_off_pledge(pledge_id):
    authenticate(("UnitedFundAdmin", "FinanceReviewer"))
    data = body()
    reason_code = get_enum(data, "reason_code", WRITE_OFF_REASONS)

    pledge = get_pledge(pledge_id)
    campaign = db.campaigns[pledge["campaign_id"]]
    if campaign["posture"] not in ("OPEN", "SOLICITATION_CLOSED"):
        raise ApiError("ERR_CAMPAIGN_INVALID_STATE")
    if pledge["designation_status"] not in ("CONFIRMED", "AMENDED"):
        raise ApiError("ERR_PLEDGE_NOT_CONFIRMED")
    if pledge["collection_status"] in ("COLLECTED", "WRITTEN_OFF"):
        raise ApiError("ERR_PLEDGE_COLLECTION_TERMINAL")

    # Write-off cascade link 1.
    pledge["collection_status"] = "WRITTEN_OFF"
    pledge["write_off_reason_code"] = reason_code
    pledge["uncollected_amount"] = q2(
        D(pledge["gross_amount"]) - D(pledge["collected_amount"])
    )
    touch("pledge", pledge)

    # Link 2: every ACTIVE line becomes UNCOLLECTED with nothing collected.
    affected = []
    for line in aggregates.active_lines(pledge_id):
        affected.append(line["agency_id"])
        line["status"] = "UNCOLLECTED"
        line["collected_designated_amount"] = ZERO
        touch("designation", line)

    # Link 3: the agency passthrough ledger drops the now-uncollected lines.
    aggregates.recompute_agency_passthrough_for_ids(affected)
    return ok(pledge)
