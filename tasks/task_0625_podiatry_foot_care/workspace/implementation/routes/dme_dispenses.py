"""DME dispensing and rent-to-own charges (PRD §3.8)."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
import services
import validate as v

bp = Blueprint("dme_dispenses", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


@bp.route("/podiatry/dme-dispenses", methods=["POST"])
def create_dme_dispense():
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    body = mw.get_body()
    with db.lock():
        prior_authorization_id = v.as_str(body, "prior_authorization_id", required=True)
        encounter_id = v.as_str(body, "encounter_id", required=True)
        pa = db.prior_authorizations.get(prior_authorization_id)
        if pa is None:
            raise errors.fk_not_found(
                "prior_authorization_id references a non-existent prior authorization.")
        encounter = db.encounters.get(encounter_id)
        if encounter is None:
            raise errors.fk_not_found("encounter_id references a non-existent encounter.")

        # Structural validation (priority 5).
        hcpcs_code = v.as_str(body, "hcpcs_code", required=True)
        acquisition_mode = v.as_enum(body, "acquisition_mode",
                                     {"PURCHASE", "RENTAL"}, required=True)
        units = v.as_int(body, "units", required=True, minimum=1)
        purchase_price = v.as_int(body, "purchase_price_cents", required=True, minimum=0)
        monthly_rental = v.as_int(body, "monthly_rental_cents", required=False, default=None)
        if acquisition_mode == "RENTAL" and monthly_rental is None:
            raise errors.invalid_request(
                "monthly_rental_cents is required when acquisition_mode is RENTAL.")
        expected_version = v.as_int(body, "expected_prior_authorization_version",
                                    required=True)

        # OCC check (priority 6) — before any business rule (PRD §2.10).
        if expected_version != pa["version"]:
            raise errors.ApiError(errors.ERR_PA_VERSION_STALE, 412,
                                  "expected_prior_authorization_version is stale.")

        # PA draw business chain (priorities 9, 10, 11, 14) for DME category.
        services.check_pa_drawable(pa, "DME", units)

        # Rent-to-own waterfall (PRD §3.8).
        this_period, cumulative = _compute_charge(
            acquisition_mode, purchase_price, monthly_rental,
            prior_authorization_id, hcpcs_code)

        entity = {
            "prior_authorization_id": prior_authorization_id,
            "encounter_id": encounter_id,
            "patient_id": encounter["patient_id"],
            "hcpcs_code": hcpcs_code,
            "acquisition_mode": acquisition_mode,
            "units": units,
            "purchase_price_cents": purchase_price,
            "monthly_rental_cents": monthly_rental,
            "cumulative_rental_paid_cents": cumulative,
            "this_period_charge_cents": this_period,
            "status": "DISPENSED",
        }
        db.stamp_common(entity)
        db.dme_dispenses[entity["id"]] = entity
        # Draw units (bumps PA version per PRD §3.8).
        services.draw_pa_units(pa, units)
        return resp.success(entity, 201)


def _compute_charge(mode, purchase_price, monthly_rental, pa_id, hcpcs_code):
    if mode == "PURCHASE":
        return purchase_price, purchase_price
    # RENTAL: prior cumulative = sum of charges of earlier RENTAL dispenses for
    # the same hcpcs_code under the same PA, chronological by created_at asc.
    prior_cum = 0
    earlier = [d for d in db.dme_dispenses.values()
               if d["prior_authorization_id"] == pa_id
               and d["hcpcs_code"] == hcpcs_code
               and d["acquisition_mode"] == "RENTAL"]
    earlier.sort(key=lambda d: (d["created_at"], d.get("_seq", 0)))
    for d in earlier:
        prior_cum += d["this_period_charge_cents"]
    remaining_to_cap = purchase_price - prior_cum
    if remaining_to_cap <= 0:
        this_period = 0
    else:
        this_period = min(monthly_rental, remaining_to_cap)
    cumulative = prior_cum + this_period
    return this_period, cumulative


@bp.route("/podiatry/dme-dispenses", methods=["GET"])
def list_dme_dispenses():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    pa_id = request.args.get("prior_authorization_id")
    encounter_id = request.args.get("encounter_id")
    items = []
    for d in db.dme_dispenses.values():
        if pa_id is not None and d["prior_authorization_id"] != pa_id:
            continue
        if encounter_id is not None and d["encounter_id"] != encounter_id:
            continue
        items.append(d)
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/dme-dispenses/<dispense_id>", methods=["GET"])
def get_dme_dispense(dispense_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.dme_dispenses.get(dispense_id)
    if entity is None:
        raise errors.not_found("DME dispense not found.")
    return resp.success(entity, 200)


@bp.route("/podiatry/dme-dispenses/<dispense_id>/return", methods=["POST"])
def return_dme_dispense(dispense_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    with db.lock():
        d = db.dme_dispenses.get(dispense_id)
        if d is None:
            raise errors.not_found("DME dispense not found.")
        if d["status"] != "DISPENSED":
            raise errors.ApiError(errors.ERR_DME_BAD_STATE, 409,
                                  "return requires status DISPENSED.")
        d["status"] = "RETURNED"
        db.touch(d)
        # Compensation: restore PA units; revive EXHAUSTED; bump PA version.
        pa = db.prior_authorizations.get(d["prior_authorization_id"])
        if pa is not None:
            services.restore_pa_units(pa, d["units"])
        return resp.success(d, 200)
