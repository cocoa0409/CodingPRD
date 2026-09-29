"""Collateral assets, lien occupation and the release buffer (PRD section 3.4)."""

from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import CREDIT_ANALYST, INSTITUTION_REP, READ_ALL
from errors import ApiError

bp = Blueprint("collateral", __name__)

ASSET_TYPES = ("SANCTUARY", "EDUCATION_WING", "PARSONAGE", "LAND",
               "FELLOWSHIP_HALL", "DONOR_RESTRICTED_ENDOWMENT")


@bp.route("/collateral-assets", methods=["POST"])
def create_asset():
    ctx = auth.authenticate((CREDIT_ANALYST, INSTITUTION_REP))
    b = shapes.body()
    auth.scope(ctx, b.get("institution_id"))
    institution = resolve.institution(b.get("institution_id"))
    if institution is None:
        shapes.req_id_field(b, "institution_id")

    asset_type = shapes.req_enum(b, "asset_type", ASSET_TYPES)
    label = shapes.req_str(b, "description_label")
    value = shapes.req_int(b, "appraised_value_cents", exclusive_minimum=0)
    appraisal_raw, appraisal_dt = shapes.req_dt(b, "appraisal_date")
    score = shapes.req_int(b, "alternative_use_score", minimum=1, maximum=5)

    row = store.base_record()
    row.update({
        "institution_id": institution["id"],
        "asset_type": asset_type,
        "description_label": label,
        "appraised_value_cents": value,
        "appraisal_date": appraisal_raw,
        "alternative_use_score": score,
        "assigned_loan_application_id": None,
        "lien_position": None,
        "lien_effective_from": None,
        "lien_effective_to": None,
        "lien_history": [],
        "lending_value_cents": 0,
        "release_note": None,
        "_appraisal_date_dt": appraisal_dt,
    })
    calc.revalue_asset(row)
    store.collateral_assets[row["id"]] = row
    store.mark_created(row)
    return envelope.created(serializers.collateral_asset(row))


@bp.route("/collateral-assets/<collateral_asset_id>", methods=["GET"])
def get_asset(collateral_asset_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.collateral_asset(collateral_asset_id)
    auth.scope(ctx, row.get("institution_id"))
    return envelope.ok(serializers.collateral_asset(row))


@bp.route("/collateral-assets", methods=["GET"])
def list_assets():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(
        list(store.collateral_assets.values()),
        {"institution_id": "institution_id",
         "assigned_loan_application_id": "assigned_loan_application_id",
         "asset_type": "asset_type"})
    return envelope.listing(envelope.sort_created_asc(rows),
                            serializers.collateral_asset)


def _prior_occupations(asset):
    priors = []
    for entry in asset.get("lien_history", []):
        start = store.parse_dt(entry.get("effective_from"))
        end = store.parse_dt(entry.get("effective_to"))
        if start is not None and end is not None:
            priors.append((start, end))
    if asset.get("assigned_loan_application_id") is not None:
        start = store.parse_dt(asset.get("lien_effective_from"))
        end = store.parse_dt(asset.get("lien_effective_to"))
        if start is not None and end is not None:
            priors.append((start, end))
    return priors


@bp.route("/collateral-assets/<collateral_asset_id>/assignments",
          methods=["POST"])
def assign_asset(collateral_asset_id):
    auth.authenticate((CREDIT_ANALYST,))
    asset = resolve.collateral_asset(collateral_asset_id)
    b = shapes.body()
    application = resolve.loan_application(b.get("loan_application_id"))
    if application is None:
        shapes.req_id_field(b, "loan_application_id")
    position = shapes.req_int(b, "lien_position", minimum=1)
    from_raw, from_dt = shapes.req_dt(b, "lien_effective_from")
    to_raw, to_dt = shapes.req_dt(b, "lien_effective_to")
    if to_dt <= from_dt:
        shapes.bad("lien_effective_to", "must be after lien_effective_from")

    # ladder 34
    if asset["asset_type"] == "DONOR_RESTRICTED_ENDOWMENT":
        raise ApiError("ERR_ENDOWMENT_COLLATERAL_INELIGIBLE")
    # ladder 35
    if calc.appraisal_age_days(asset) > calc.APPRAISAL_STALE_DAYS:
        raise ApiError("ERR_COLLATERAL_APPRAISAL_STALE")
    # ladder 37 — every prior occupation extended by the 30-day release buffer
    for prior_from, prior_to in _prior_occupations(asset):
        extended = store.plus_days(prior_to, calc.LIEN_RELEASE_BUFFER_DAYS)
        if from_dt < extended and prior_from < to_dt:
            raise ApiError("ERR_COLLATERAL_LIEN_WINDOW_CONFLICT")
    # ladder 39
    if asset["institution_id"] != application["institution_id"]:
        raise ApiError("ERR_INSTITUTION_MISMATCH")
    # ladder 40
    if asset.get("assigned_loan_application_id") is not None:
        raise ApiError("ERR_COLLATERAL_ALREADY_ASSIGNED")

    asset["assigned_loan_application_id"] = application["id"]
    asset["lien_position"] = position
    asset["lien_effective_from"] = from_raw
    asset["lien_effective_to"] = to_raw
    calc.revalue_asset(asset)
    store.touch(asset)
    return envelope.ok(serializers.collateral_asset(asset))


def release_occupation(asset):
    """Append the occupation just ended to lien_history and clear the four
    current-occupation fields, re-valuing at the first-lien factor."""
    asset.setdefault("lien_history", []).append({
        "loan_application_id": asset.get("assigned_loan_application_id"),
        "lien_position": asset.get("lien_position"),
        "effective_from": asset.get("lien_effective_from"),
        "effective_to": asset.get("lien_effective_to"),
        "released_at": store.iso_ms(store.clock_now()),
    })
    asset["assigned_loan_application_id"] = None
    asset["lien_position"] = None
    asset["lien_effective_from"] = None
    asset["lien_effective_to"] = None
    calc.revalue_asset(asset)
    store.touch(asset)


@bp.route("/collateral-assets/<collateral_asset_id>/release", methods=["POST"])
def release_asset(collateral_asset_id):
    auth.authenticate((CREDIT_ANALYST,))
    asset = resolve.collateral_asset(collateral_asset_id)
    b = shapes.body()
    note = shapes.req_str(b, "release_note")
    if asset.get("assigned_loan_application_id") is None:
        raise ApiError("ERR_COLLATERAL_ALREADY_ASSIGNED")
    asset["release_note"] = note
    release_occupation(asset)
    return envelope.ok(serializers.collateral_asset(asset))
