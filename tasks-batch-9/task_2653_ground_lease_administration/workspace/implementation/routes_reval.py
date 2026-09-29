"""Rent revaluation: opening, appraisal exchange, settlement and arbitration."""

from flask import Blueprint

import auth
import calc
import cascades
import serialize
import store
import validate as v
from errors import ApiError
from response import object_response

bp = Blueprint("reval", __name__)

OPEN_REVALUATION_STATUSES = ("OPEN_FOR_APPRAISALS", "PROPOSALS_EXCHANGED",
                             "ARBITRATION_REFERRED")
APPRAISAL_SIDES = {"LESSOR", "LESSEE"}
VALUATION_METHODS = {"COMPARABLE_LAND", "RESIDUAL_LAND", "INCOME_CAP"}


def _lease_of(revaluation):
    return store.leases.get(revaluation["lease_id"])


def _appraisals_for(revaluation_id):
    rows = [a for a in store.appraisals.values()
            if a["revaluation_id"] == revaluation_id]
    return store.sort_rows(rows)


def _apply_resolution(lease, revaluation, resolved, method):
    """The identical cascade fired by both resolution routes (PRD 3.3)."""
    revaluation["status"] = "RESOLVED"
    revaluation["resolution_method"] = method
    revaluation["resolved_annual_base_rent_cents"] = resolved
    store.touch(revaluation)

    lease["current_annual_base_rent_cents"] = resolved
    lease["next_revaluation_date"] = store.add_years(
        lease["next_revaluation_date"], lease["revaluation_interval_years"]
    )
    lease["rent_status"] = "RESET_APPLIED"
    store.touch(lease)
    cascades.refresh_submitted_statement_credits(lease)


# ===========================================================================
# Opening a revaluation
# ===========================================================================
@bp.post("/leases/<lease_id>/rent-revaluations")
def open_revaluation(lease_id):
    lease = cascades.fetch("lease", lease_id)
    auth.require({"LessorAdmin"})
    payload = v.body()
    valuation_date = v.req_dt(payload, "valuation_date")

    for row in store.by_lease(store.revaluations, lease_id):
        if row["status"] in OPEN_REVALUATION_STATUSES:
            raise ApiError("ERR_DUPLICATE_RECORD",
                           "The lease already carries an open revaluation.")

    if lease["lease_status"] in cascades.NON_OPERATIVE:
        cascades.require_operative(lease)
    if lease["rent_status"] not in ("BASE_ONLY", "REVALUATION_DUE",
                                    "RESET_APPLIED"):
        raise cascades.invalid_state(
            "The lease rent axis is in %s and cannot open a revaluation."
            % lease["rent_status"]
        )
    if lease["lease_status"] not in ("ACTIVE", "IN_DEFAULT"):
        raise cascades.invalid_state(
            "The lease tenancy axis is in %s and cannot open a revaluation."
            % lease["lease_status"]
        )
    runway_opens = store.add_days(lease["next_revaluation_date"],
                                 -calc.REVALUATION_ADVANCE_NOTICE_DAYS)
    if store.now() < runway_opens:
        raise cascades.invalid_state(
            "The 180-day advance-notice runway before next_revaluation_date "
            "has not yet opened."
        )

    if valuation_date < store.add_days(store.now(),
                                      calc.REVALUATION_ADVANCE_NOTICE_DAYS):
        raise ApiError("ERR_CHRONOLOGY_VIOLATION",
                       "valuation_date must be at least 180 days after the "
                       "current logical instant.")

    record = {
        "lease_id": lease_id,
        "valuation_date": valuation_date,
        "status": "OPEN_FOR_APPRAISALS",
        "round_number": 1,
        "prior_annual_base_rent_cents": lease["current_annual_base_rent_cents"],
        "lessor_appraised_rent_cents": None,
        "lessee_appraised_rent_cents": None,
        "divergence_bps": None,
        "resolution_method": None,
        "resolved_annual_base_rent_cents": None,
    }
    store.stamp(record)
    store.revaluations[record["id"]] = record

    lease["rent_status"] = "REVALUATION_OPEN"
    store.touch(lease)
    return object_response(serialize.revaluation(record), 201)


# ===========================================================================
# Appraisal lodgement
# ===========================================================================
@bp.post("/rent-revaluations/<revaluation_id>/appraisals")
def lodge_appraisal(revaluation_id):
    revaluation = cascades.fetch("revaluation", revaluation_id)
    user_id, role = auth.require({"LessorAdmin", "GroundTenant"})
    auth.owns_lease(user_id, role, _lease_of(revaluation))

    payload = v.body()
    side = payload.get("appointed_by")
    if side in APPRAISAL_SIDES:
        if side == "LESSOR" and role == "GroundTenant":
            raise ApiError("ERR_APPRAISAL_SIDE_MISMATCH",
                           "A GroundTenant may not lodge the lessor-side "
                           "appraisal.")
        if side == "LESSEE" and role == "LessorAdmin":
            raise ApiError("ERR_APPRAISAL_SIDE_MISMATCH",
                           "A LessorAdmin may not lodge the lessee-side "
                           "appraisal.")

    appointed_by = v.req_enum(payload, "appointed_by", APPRAISAL_SIDES)
    appraised = v.req_int(payload, "appraised_annual_rent_cents", minimum=1)
    method = v.req_enum(payload, "valuation_method_code", VALUATION_METHODS)

    round_number = revaluation["round_number"]
    for row in _appraisals_for(revaluation_id):
        if (row["appointed_by"] == appointed_by
                and row["round_number"] == round_number):
            raise ApiError(
                "ERR_DUPLICATE_RECORD",
                "That side has already lodged an appraisal for this round.",
            )

    if revaluation["status"] != "OPEN_FOR_APPRAISALS":
        raise cascades.invalid_state(
            "The revaluation is in %s and accepts no appraisals."
            % revaluation["status"]
        )

    record = {
        "revaluation_id": revaluation_id,
        "appointed_by": appointed_by,
        "appraiser_user_id": user_id,
        "appraised_annual_rent_cents": appraised,
        "valuation_method_code": method,
        "round_number": round_number,
    }
    store.stamp(record, versioned=False)
    store.appraisals[record["id"]] = record
    return object_response(serialize.appraisal(record), 201)


# ===========================================================================
# Exchange, further rounds, midpoint settlement
# ===========================================================================
@bp.post("/rent-revaluations/<revaluation_id>/exchange")
def exchange_appraisals(revaluation_id):
    revaluation = cascades.fetch("revaluation", revaluation_id)
    auth.require({"LessorAdmin"})

    if revaluation["status"] != "OPEN_FOR_APPRAISALS":
        raise cascades.invalid_state(
            "The revaluation is in %s and cannot exchange appraisals."
            % revaluation["status"]
        )

    round_number = revaluation["round_number"]
    lessor_rows = [a for a in _appraisals_for(revaluation_id)
                   if a["appointed_by"] == "LESSOR"
                   and a["round_number"] == round_number]
    lessee_rows = [a for a in _appraisals_for(revaluation_id)
                   if a["appointed_by"] == "LESSEE"
                   and a["round_number"] == round_number]
    if len(lessor_rows) != 1 or len(lessee_rows) != 1:
        raise ApiError("ERR_APPRAISALS_INCOMPLETE",
                       "Both party appraisals for the current round must be "
                       "lodged before they can be exchanged.")

    lessor_rent = lessor_rows[0]["appraised_annual_rent_cents"]
    lessee_rent = lessee_rows[0]["appraised_annual_rent_cents"]
    revaluation["lessor_appraised_rent_cents"] = lessor_rent
    revaluation["lessee_appraised_rent_cents"] = lessee_rent
    revaluation["divergence_bps"] = calc.divergence_bps(lessor_rent,
                                                        lessee_rent)
    revaluation["status"] = "PROPOSALS_EXCHANGED"
    store.touch(revaluation)
    return object_response(serialize.revaluation(revaluation), 200)


@bp.post("/rent-revaluations/<revaluation_id>/rounds")
def open_round(revaluation_id):
    revaluation = cascades.fetch("revaluation", revaluation_id)
    auth.require({"LessorAdmin"})

    if revaluation["status"] != "PROPOSALS_EXCHANGED":
        raise cascades.invalid_state(
            "The revaluation is in %s and cannot open a further round."
            % revaluation["status"]
        )
    divergence = revaluation.get("divergence_bps") or 0
    if divergence <= calc.ARBITRATION_DIVERGENCE_THRESHOLD_BPS:
        raise ApiError("ERR_DIVERGENCE_BELOW_THRESHOLD",
                       "The divergence has narrowed to 1000 basis points or "
                       "less; no further round is available.")
    if revaluation["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_MAX_ROUNDS_REACHED",
                       "The lease allows at most 2 negotiation rounds.")

    revaluation["round_number"] = revaluation["round_number"] + 1
    revaluation["lessor_appraised_rent_cents"] = None
    revaluation["lessee_appraised_rent_cents"] = None
    revaluation["divergence_bps"] = None
    revaluation["status"] = "OPEN_FOR_APPRAISALS"
    store.touch(revaluation)
    return object_response(serialize.revaluation(revaluation), 200)


@bp.post("/rent-revaluations/<revaluation_id>/settle")
def settle_revaluation(revaluation_id):
    revaluation = cascades.fetch("revaluation", revaluation_id)
    auth.require({"LessorAdmin"})
    lease = _lease_of(revaluation)

    if revaluation["status"] != "PROPOSALS_EXCHANGED":
        raise cascades.invalid_state(
            "The revaluation is in %s and cannot be settled."
            % revaluation["status"]
        )
    if lease is None or lease["lease_status"] not in ("ACTIVE", "IN_DEFAULT"):
        raise cascades.invalid_state(
            "Settlement requires the lease tenancy axis to be ACTIVE or "
            "IN_DEFAULT."
        )

    indicated = calc.midpoint_indicated(
        revaluation["lessor_appraised_rent_cents"],
        revaluation["lessee_appraised_rent_cents"],
    )
    resolved = calc.clamp_to_collar(
        indicated,
        revaluation["prior_annual_base_rent_cents"],
        lease["reval_collar_min_uplift_bps"],
        lease["reval_collar_max_uplift_bps"],
    )
    _apply_resolution(lease, revaluation, resolved, "MIDPOINT_SETTLEMENT")
    return object_response(serialize.revaluation(revaluation), 200)


# ===========================================================================
# Baseball arbitration
# ===========================================================================
@bp.post("/rent-revaluations/<revaluation_id>/arbitration-referrals")
def refer_to_arbitration(revaluation_id):
    revaluation = cascades.fetch("revaluation", revaluation_id)
    user_id, role = auth.require({"LessorAdmin"})
    payload = v.body()
    arbitrator_user_id = v.req_str(payload, "arbitrator_user_id")
    hearing_date = v.req_dt(payload, "hearing_date")

    for row in store.arbitrations.values():
        if row["revaluation_id"] == revaluation_id:
            raise ApiError("ERR_DUPLICATE_RECORD",
                           "That revaluation already has an arbitration "
                           "proceeding.")

    if revaluation["status"] != "PROPOSALS_EXCHANGED":
        raise cascades.invalid_state(
            "The revaluation is in %s and cannot be referred to arbitration."
            % revaluation["status"]
        )
    divergence = revaluation.get("divergence_bps") or 0
    if divergence <= calc.ARBITRATION_DIVERGENCE_THRESHOLD_BPS:
        raise ApiError("ERR_DIVERGENCE_BELOW_THRESHOLD",
                       "Arbitration requires a divergence strictly above 1000 "
                       "basis points.")
    for row in _appraisals_for(revaluation_id):
        if row["appraiser_user_id"] == arbitrator_user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The nominated arbitrator has already appraised "
                           "this revaluation.")

    lease = _lease_of(revaluation)
    if lease is not None and lease["lease_status"] == "IN_DEFAULT":
        raise ApiError("ERR_CROSS_ENTITY_BLOCKED",
                       "A revaluation may not be referred to arbitration "
                       "while the lease is IN_DEFAULT.")

    record = {
        "revaluation_id": revaluation_id,
        "arbitrator_user_id": arbitrator_user_id,
        "hearing_date": hearing_date,
        "status": "REFERRED",
        "independent_annual_rent_cents": None,
        "awarded_annual_rent_cents": None,
        "award_basis": None,
    }
    store.stamp(record)
    store.arbitrations[record["id"]] = record

    revaluation["status"] = "ARBITRATION_REFERRED"
    store.touch(revaluation)
    if lease is not None:
        lease["rent_status"] = "IN_ARBITRATION"
        store.touch(lease)
    return object_response(serialize.arbitration(record), 201)


@bp.post("/arbitrations/<arbitration_id>/award")
def issue_award(arbitration_id):
    proceeding = cascades.fetch("arbitration", arbitration_id)
    user_id, role = auth.require({"Arbitrator"})
    if user_id != proceeding["arbitrator_user_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the appointed arbitrator may issue this award.")

    payload = v.body()
    independent = v.req_int(payload, "independent_annual_rent_cents", minimum=1)

    if proceeding["status"] != "REFERRED":
        raise cascades.invalid_state(
            "The proceeding is in %s and cannot be awarded."
            % proceeding["status"]
        )

    revaluation = store.revaluations.get(proceeding["revaluation_id"])
    lease = _lease_of(revaluation) if revaluation else None

    indicated, basis = calc.baseball_selection(
        revaluation["lessor_appraised_rent_cents"],
        revaluation["lessee_appraised_rent_cents"],
        independent,
    )
    proceeding["independent_annual_rent_cents"] = independent
    # Stored before any clamping.
    proceeding["awarded_annual_rent_cents"] = indicated
    proceeding["award_basis"] = basis
    proceeding["status"] = "AWARDED"
    store.touch(proceeding)

    resolved = calc.clamp_to_collar(
        indicated,
        revaluation["prior_annual_base_rent_cents"],
        lease["reval_collar_min_uplift_bps"],
        lease["reval_collar_max_uplift_bps"],
    )
    _apply_resolution(lease, revaluation, resolved, "ARBITRATION_AWARD")
    return object_response(serialize.arbitration(proceeding), 200)
