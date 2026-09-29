"""Carrier registration, standing changes, review opening and scorecard drafting —
PRD §3.1 and §3.2."""
import re
from decimal import Decimal

from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError, bad_request
from numeric import q2
from services import bidding, scoring

bp = Blueprint("carriers", __name__)

SERVICE_MODES = ("DRY_VAN", "REEFER", "FLATBED")
DIVERSITY_CLASSIFICATIONS = ("NONE", "MWBE", "VETERAN_OWNED", "SMALL_BUSINESS")
CARRIER_STATUSES = ("REGISTERED", "SCREENING", "QUALIFIED", "CONDITIONALLY_QUALIFIED",
                    "WATCHLIST", "SUSPENDED", "DISQUALIFIED")
SUSPENDABLE_FROM = ("REGISTERED", "SCREENING", "QUALIFIED", "WATCHLIST",
                    "CONDITIONALLY_QUALIFIED")
IN_FLIGHT_REVIEW_STATUSES = ("SUBMITTED", "SCREENED", "REMEDIATION")

SCAC_PATTERN = re.compile(r"^[A-Z]{4}$")
DEFAULT_MIN_AUTO_LIABILITY_USD = Decimal("1000000.00")
DEFAULT_MIN_CARGO_USD = Decimal("100000.00")


def _carrier_row(**fields):
    return store.new_row(**fields)


@bp.post("/freight-procurement/carriers")
@auth.roles_required("ProcurementAnalyst")
def register_carrier():
    payload = v.body()
    legal_name = v.string_field(payload, "legal_name", min_len=1, max_len=120)
    scac_code = v.string_field(payload, "scac_code", min_len=4, max_len=4,
                               pattern=SCAC_PATTERN)
    diversity = v.enum_field(payload, "diversity_classification",
                             DIVERSITY_CLASSIFICATIONS, required=False, default="NONE")
    service_modes = v.enum_list_field(payload, "service_modes", SERVICE_MODES)
    fleet = v.int_field(payload, "fleet_power_units", minimum=1)
    auto = v.dec_field(payload, "auto_liability_limit_usd")
    cargo = v.dec_field(payload, "cargo_limit_usd")
    expiry = v.dt_field(payload, "insurance_expiry_date")

    for other in store.carriers.values():
        if other["scac_code"] == scac_code:
            raise ApiError("ERR_DUPLICATE_SCAC")

    carrier = _carrier_row(
        legal_name=legal_name,
        scac_code=scac_code,
        status="REGISTERED",
        status_reason=None,
        diversity_classification=diversity,
        service_modes=service_modes,
        fleet_power_units=fleet,
        auto_liability_limit_usd=q2(auto),
        cargo_limit_usd=q2(cargo),
        insurance_expiry_date=expiry,
        capability_score=Decimal("0.00"),
        composite_score=Decimal("0.00"),
        composite_score_variant="PROVISIONAL_SCREENING",
        published_scorecard_count=0,
        active_primary_lane_count=0,
        committed_volume_loads=0,
        qualified_at=None,
    )
    scoring.recompute_composite(carrier)
    store.carriers[carrier["id"]] = carrier
    return responses.created(carrier)


@bp.get("/freight-procurement/carriers/<carrier_id>")
@auth.roles_required(*auth.ALL_ROLES)
def get_carrier(carrier_id):
    return responses.ok(helpers.get_carrier(carrier_id))


@bp.get("/freight-procurement/carriers")
@auth.roles_required("ProcurementAnalyst", "ComplianceOfficer", "CategoryManager",
                     "ContractAdmin")
def list_carriers():
    rows = store.sorted_rows(store.carriers.values())
    rows = helpers.filter_rows(rows, {"status": "status",
                                      "diversity_classification":
                                          "diversity_classification"})
    return responses.listing(rows)


@bp.post("/freight-procurement/carriers/<carrier_id>/status-change")
@auth.roles_required("ComplianceOfficer")
def status_change(carrier_id):
    carrier = helpers.get_carrier(carrier_id)
    payload = v.body()
    to_status = v.enum_field(payload, "to_status", CARRIER_STATUSES)
    reason = v.string_field(payload, "reason", min_len=1)

    current = carrier["status"]
    if to_status == "SUSPENDED" and current in SUSPENDABLE_FROM:
        pass
    elif to_status == "QUALIFIED" and current == "SUSPENDED":
        expiry = store.dt_of(carrier["insurance_expiry_date"])
        if expiry is None or expiry <= store.now():
            raise ApiError("ERR_CARRIER_INSURANCE_EXPIRED")
    elif to_status == "DISQUALIFIED" and current != "DISQUALIFIED":
        pass
    else:
        raise ApiError("ERR_CARRIER_NOT_QUALIFIED")

    carrier["status"] = to_status
    carrier["status_reason"] = reason
    if to_status == "QUALIFIED":
        carrier["qualified_at"] = store.now_iso()

    if to_status == "DISQUALIFIED":
        for invitation in store.sorted_rows(store.invitations.values()):
            if (invitation["carrier_id"] == carrier["id"]
                    and invitation["status"] in ("SENT", "ACCEPTED")):
                invitation["status"] = "REVOKED"
                store.touch(invitation)
                event = helpers.event_of(invitation)
                if event is not None:
                    _recount_invitations(event)
                    store.touch(event)
        bidding.withdrawal_cascade(carrier["id"])

    scoring.recompute_composite(carrier)
    store.touch(carrier)
    return responses.ok(carrier)


def _recount_invitations(event):
    invitations = [i for i in store.invitations.values()
                   if i["bid_event_id"] == event["id"]]
    event["invited_carrier_count"] = sum(
        1 for i in invitations if i["status"] in ("SENT", "ACCEPTED", "DECLINED"))
    event["accepted_invitation_count"] = sum(
        1 for i in invitations if i["status"] == "ACCEPTED")


@bp.post("/freight-procurement/carriers/<carrier_id>/qualification-reviews")
@auth.roles_required("ComplianceOfficer")
def open_review(carrier_id):
    carrier = helpers.get_carrier(carrier_id)
    payload = v.body()
    required_modes = v.enum_list_field(payload, "required_modes", SERVICE_MODES)
    min_auto = v.dec_field(payload, "min_auto_liability_usd", required=False,
                           default=DEFAULT_MIN_AUTO_LIABILITY_USD)
    min_cargo = v.dec_field(payload, "min_cargo_usd", required=False,
                            default=DEFAULT_MIN_CARGO_USD)

    if carrier["status"] != "REGISTERED":
        raise ApiError("ERR_CARRIER_NOT_QUALIFIED")
    for review in store.reviews.values():
        if (review["carrier_id"] == carrier["id"]
                and review["status"] in IN_FLIGHT_REVIEW_STATUSES):
            raise ApiError("ERR_CARRIER_NOT_QUALIFIED")

    review = store.new_row(
        carrier_id=carrier["id"],
        status="SUBMITTED",
        required_modes=required_modes,
        min_auto_liability_usd=q2(min_auto),
        min_cargo_usd=q2(min_cargo),
        insurance_result="PENDING",
        capability_result="PENDING",
        verified_auto_liability_usd=None,
        verified_cargo_usd=None,
        verified_expiry_date=None,
        capability_score=None,
        insurance_verified_at=None,
        capability_screened_at=None,
        decision_outcome=None,
        decision_note=None,
        decision_by_user_id=None,
        remediation_count=0,
    )
    store.reviews[review["id"]] = review

    carrier["status"] = "SCREENING"
    store.touch(carrier)
    return responses.created(review)


@bp.get("/freight-procurement/carriers/<carrier_id>/qualification-reviews")
@auth.roles_required("ComplianceOfficer", "ProcurementAnalyst")
def list_reviews(carrier_id):
    carrier = helpers.get_carrier(carrier_id)
    rows = store.sorted_rows([r for r in store.reviews.values()
                              if r["carrier_id"] == carrier["id"]])
    return responses.listing(rows)


@bp.post("/freight-procurement/carriers/<carrier_id>/scorecards")
@auth.roles_required("CategoryManager")
def draft_scorecard(carrier_id):
    carrier = helpers.get_carrier(carrier_id)
    payload = v.body()
    period_start = v.dt_field(payload, "period_start")
    period_end = v.dt_field(payload, "period_end")
    v.interval(period_start, period_end, "period_start", "period_end")
    on_time = v.dec_field(payload, "on_time_pct", maximum=Decimal("100.00"))
    claims = v.dec_field(payload, "claims_ratio", maximum=Decimal("1.0000"))

    scorecard = store.new_row(
        carrier_id=carrier["id"],
        period_start=period_start,
        period_end=period_end,
        on_time_pct=q2(on_time),
        claims_ratio=claims,
        tender_acceptance_pct=Decimal("0.00"),
        period_tender_count=0,
        composite_score=Decimal("0.00"),
        status="DRAFT",
        published_at=None,
        disputed_reason=None,
    )
    scoring.scorecard_period_metrics(scorecard)
    store.scorecards[scorecard["id"]] = scorecard
    return responses.created(scorecard)


@bp.get("/freight-procurement/carriers/<carrier_id>/scorecards")
@auth.roles_required("CategoryManager", "ProcurementAnalyst", "CarrierRep")
def list_scorecards(carrier_id):
    carrier = helpers.get_carrier(carrier_id)
    rows = [s for s in store.scorecards.values() if s["carrier_id"] == carrier["id"]]
    rows.sort(key=lambda s: (scoring._neg_key(s["period_end"]), s["created_at"],
                             s["_seq"]))
    return responses.listing(rows)
