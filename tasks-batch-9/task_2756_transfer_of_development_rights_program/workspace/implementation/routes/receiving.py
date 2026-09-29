"""Receiving site application and redemption endpoints (PRD 3.8)."""

from flask import Blueprint

import serializers
from core import db, new_record, now, respond_object, touch
from errors import fail
from listing import match, paged
from middleware import ADMIN, ALL_ROLES, BOARD, DEVELOPER, require_owner, require_roles, require_suspension_clear
from routes.areas import get_receiving_area_or_404
from routes.certificates import assert_transferable, get_certificate_or_404
from routes.parties import get_party_or_404
from services import calc
from services.derive import (append_transfer, available_units, certificate_easement,
                             easement_compliance_ok, recompute_application_backing,
                             recompute_certificate_units, recompute_easement_units,
                             recompute_party_holdings, recompute_receiving_area_units,
                             redemptions_of_application)
from validators import body, field_decimal, field_enum, field_int, field_str, filter_enum, filter_str

bp = Blueprint("receiving", __name__)

APP_STATUSES = ("SUBMITTED", "DESIGN_REVIEW", "REVISIONS_REQUIRED", "DESIGN_APPROVED",
                "BACKING_DEFICIENT", "FINALIZED", "DENIED")
TERMINAL_APP_STATUSES = ("FINALIZED", "DENIED")
DESIGN_DECISIONS = ("APPROVE", "REQUIRE_REVISIONS", "DENY")
REDEMPTION_STATUSES = ("ALLOCATED", "HELD_PENDING_COMPLIANCE", "CONFIRMED", "RELEASED")
OPEN_REDEMPTION_STATUSES = ("ALLOCATED", "HELD_PENDING_COMPLIANCE")
MAX_DESIGN_ROUNDS = 2


def get_site_application_or_404(app_id):
    app = db.receiving_site_applications.get(app_id)
    if app is None:
        fail("ERR_RECEIVING_SITE_APPLICATION_NOT_FOUND", "receiving site application %s does not exist" % app_id)
    return app


def get_redemption_or_404(redemption_id):
    red = db.certificate_redemptions.get(redemption_id)
    if red is None:
        fail("ERR_CERTIFICATE_REDEMPTION_NOT_FOUND", "certificate redemption %s does not exist" % redemption_id)
    return red


def _apply_provisional_sizing(app, area):
    base_units, max_bonus, required, provisional = calc.bonus_sizing(
        area, app["site_acres"], app["requested_bonus_units"]
    )
    app["base_units"] = base_units
    app["max_bonus_units"] = max_bonus
    app["required_backing_units"] = required
    app["provisional_bonus_units"] = provisional


def _release_redemption(red, app, area):
    red["status"] = "RELEASED"
    red["released_at"] = now()
    touch(red)
    cert = db.certificates.get(red["certificate_id"])
    if cert is not None:
        cert["units_encumbered"] = max(0, int(cert["units_encumbered"]) - int(red["units"]))
        touch(cert)
    recompute_application_backing(app)
    if area is not None:
        recompute_receiving_area_units(area)


# ---------------------------------------------------------------------------
# Receiving site applications
# ---------------------------------------------------------------------------
@bp.post("/tdr/receiving-site-applications")
def create_site_application():
    user_id, role = require_roles(DEVELOPER)
    data = body()
    site_acres = field_decimal(data, "site_acres", minimum=0, places=2, exclusive_min=True)
    requested_bonus_units = field_int(data, "requested_bonus_units", minimum=1)
    developer_id = field_str(data, "developer_party_id", min_len=1)
    area_id = field_str(data, "receiving_area_id", min_len=1)

    developer = get_party_or_404(developer_id)
    area = get_receiving_area_or_404(area_id)

    require_owner(user_id, role, developer_id)
    if developer["kind"] != "DEVELOPER":
        fail("ERR_PARTY_KIND_MISMATCH", "developer_party_id must reference a DEVELOPER party")
    require_suspension_clear(developer_id)
    if area["status"] != "ACTIVE":
        fail("ERR_RECEIVING_AREA_NOT_ACTIVE", "receiving area is %s" % area["status"])

    rec = new_record(
        {
            "developer_party_id": developer_id,
            "receiving_area_id": area_id,
            "site_acres": site_acres,
            "requested_bonus_units": requested_bonus_units,
            "base_units": 0,
            "max_bonus_units": 0,
            "required_backing_units": 0,
            "provisional_bonus_units": 0,
            "allocated_bonus_units": 0,
            "backed_units": 0,
            "pending_backed_units": 0,
            "design_review_round": 0,
            "design_reviewed_by_user_id": None,
            "status": "DESIGN_REVIEW" if area["design_review_required"] else "DESIGN_APPROVED",
            "finalized_at": None,
            "denial_reason": None,
        }
    )
    _apply_provisional_sizing(rec, area)
    db.receiving_site_applications[rec["id"]] = rec
    return respond_object(serializers.receiving_site_application(rec), 201)


@bp.get("/tdr/receiving-site-applications/<app_id>")
def get_site_application(app_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.receiving_site_application(get_site_application_or_404(app_id)))


@bp.get("/tdr/receiving-site-applications")
def list_site_applications():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.receiving_site_applications.values()),
        developer_party_id=filter_str("developer_party_id"),
        receiving_area_id=filter_str("receiving_area_id"),
        status=filter_enum("status", APP_STATUSES),
    )
    return paged(rows, serializers.receiving_site_application)


@bp.post("/tdr/receiving-site-applications/<app_id>/design-review-decision")
def design_review_decision(app_id):
    user_id, role = require_roles(BOARD)
    app = get_site_application_or_404(app_id)
    data = body()
    decision = field_enum(data, "decision", DESIGN_DECISIONS)
    review_note = field_str(data, "review_note", required=False)

    if app["status"] != "DESIGN_REVIEW":
        fail("ERR_DESIGN_REVIEW_STATE_INVALID", "application is %s" % app["status"])
    if decision == "REQUIRE_REVISIONS" and int(app["design_review_round"]) >= MAX_DESIGN_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "the two-round design revision limit is exhausted")

    app["design_reviewed_by_user_id"] = user_id
    if decision == "APPROVE":
        app["status"] = "DESIGN_APPROVED"
    elif decision == "REQUIRE_REVISIONS":
        app["status"] = "REVISIONS_REQUIRED"
    else:
        app["status"] = "DENIED"
        app["denial_reason"] = review_note if review_note is not None else "DESIGN_REVIEW_DENIED"
        area = db.receiving_areas.get(app["receiving_area_id"])
        for red in redemptions_of_application(app["id"]):
            if red["status"] in OPEN_REDEMPTION_STATUSES:
                _release_redemption(red, app, area)
    touch(app)
    return respond_object(serializers.receiving_site_application(app))


@bp.post("/tdr/receiving-site-applications/<app_id>/resubmit-design")
def resubmit_design(app_id):
    user_id, role = require_roles(DEVELOPER)
    app = get_site_application_or_404(app_id)
    data = body()
    requested_bonus_units = field_int(data, "requested_bonus_units", minimum=1)
    field_str(data, "revision_note", required=False)

    require_owner(user_id, role, app["developer_party_id"])
    if app["status"] != "REVISIONS_REQUIRED":
        fail("ERR_DESIGN_REVIEW_STATE_INVALID", "application is %s" % app["status"])
    if int(app["design_review_round"]) + 1 > MAX_DESIGN_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "the two-round design revision limit is exhausted")
    if requested_bonus_units > int(app["max_bonus_units"]):
        fail("ERR_BONUS_EXCEEDS_MAX", "requested_bonus_units exceeds max_bonus_units")

    area = db.receiving_areas.get(app["receiving_area_id"])
    app["design_review_round"] = int(app["design_review_round"]) + 1
    app["requested_bonus_units"] = requested_bonus_units
    if area is not None:
        _apply_provisional_sizing(app, area)
    app["status"] = "DESIGN_REVIEW"
    touch(app)
    return respond_object(serializers.receiving_site_application(app))


@bp.post("/tdr/receiving-site-applications/<app_id>/finalize")
def finalize_application(app_id):
    user_id, role = require_roles(DEVELOPER)
    app = get_site_application_or_404(app_id)
    data = body()
    field_str(data, "finalization_note", required=False)

    require_owner(user_id, role, app["developer_party_id"])
    if app["status"] != "DESIGN_APPROVED":
        fail("ERR_APPLICATION_NOT_DESIGN_APPROVED", "application is %s" % app["status"])

    redemptions = redemptions_of_application(app["id"])
    open_redemptions = [r for r in redemptions if r["status"] in OPEN_REDEMPTION_STATUSES]
    for red in open_redemptions:
        easement = db.conservation_easements.get(red["source_easement_id"])
        if not easement_compliance_ok(easement):
            fail("ERR_EASEMENT_NONCOMPLIANT", "a source easement is %s" % easement["compliance_status"])

    area = db.receiving_areas.get(app["receiving_area_id"])
    if area is None or area["status"] != "ACTIVE":
        fail("ERR_RECEIVING_AREA_NOT_ACTIVE", "receiving area is not ACTIVE")

    if int(app["backed_units"]) + int(app["pending_backed_units"]) < int(app["required_backing_units"]):
        fail("ERR_BACKING_INSUFFICIENT", "allocated backing is below required_backing_units")

    to_confirm = [r for r in redemptions if r["status"] == "ALLOCATED"]
    confirming_units = sum(int(r["units"]) for r in to_confirm)
    if int(area["absorbed_units"]) + confirming_units > int(area["absorption_cap_units"]):
        fail("ERR_ABSORPTION_CAP_EXCEEDED", "confirmation would exceed the absorption cap")

    to_confirm.sort(key=lambda r: (r["allocated_at"], r["created_at"], r["_seq"]))
    easements = {}
    for red in to_confirm:
        red["status"] = "CONFIRMED"
        red["confirmed_at"] = now()
        touch(red)
        cert = db.certificates.get(red["certificate_id"])
        if cert is not None:
            cert["units_encumbered"] = max(0, int(cert["units_encumbered"]) - int(red["units"]))
            cert["units_redeemed"] = int(cert["units_redeemed"]) + int(red["units"])
            recompute_certificate_units(cert)
            if int(cert["units_remaining"]) <= 0:
                cert["lifecycle_status"] = "REDEEMED"
            elif cert["lifecycle_status"] == "ISSUED":
                cert["lifecycle_status"] = "PARTIALLY_REDEEMED"
            append_transfer(cert, "REDEMPTION", cert["holder_party_id"], None, int(red["units"]))
            touch(cert)
            recompute_party_holdings(db.parties.get(cert["holder_party_id"]))
        easement = db.conservation_easements.get(red["source_easement_id"])
        if easement is not None:
            easements[easement["id"]] = easement

    recompute_receiving_area_units(area)
    recompute_application_backing(app)
    for easement in easements.values():
        recompute_easement_units(easement)
        touch(easement)

    app["allocated_bonus_units"] = calc.final_bonus_units(
        app["requested_bonus_units"], app["max_bonus_units"], app["backed_units"]
    )
    app["status"] = "FINALIZED"
    app["finalized_at"] = now()
    touch(app)

    if area["status"] == "ACTIVE" and int(area["absorbed_units"]) >= int(area["absorption_cap_units"]):
        area["status"] = "SUSPENDED"
    touch(area)
    return respond_object(serializers.receiving_site_application(app))


# ---------------------------------------------------------------------------
# Redemptions
# ---------------------------------------------------------------------------
@bp.post("/tdr/receiving-site-applications/<app_id>/redemptions")
def allocate_redemption(app_id):
    user_id, role = require_roles(DEVELOPER)
    app = get_site_application_or_404(app_id)
    data = body()
    units = field_int(data, "units", minimum=1)
    expected_version = field_int(data, "expected_receiving_site_application_version")
    certificate_id = field_str(data, "certificate_id", min_len=1)
    cert = get_certificate_or_404(certificate_id)

    require_owner(user_id, role, app["developer_party_id"])
    require_owner(user_id, role, cert["holder_party_id"])
    require_suspension_clear(app["developer_party_id"], cert["holder_party_id"])

    if app["status"] in TERMINAL_APP_STATUSES:
        fail("ERR_APPLICATION_NOT_DESIGN_APPROVED", "application is %s" % app["status"])

    assert_transferable(cert)

    if expected_version != app["version"]:
        fail("ERR_STALE_PARENT_VERSION", "receiving site application version is %s" % app["version"])

    easement = certificate_easement(cert)
    if not easement_compliance_ok(easement):
        fail("ERR_CERTIFICATE_FROZEN", "the source easement is %s" % easement["compliance_status"])
    if cert["market_status"] != "HELD":
        fail("ERR_CERTIFICATE_NOT_TRANSFERABLE", "certificate is %s" % cert["market_status"])

    area = db.receiving_areas.get(app["receiving_area_id"])
    if area is None or area["status"] != "ACTIVE":
        fail("ERR_RECEIVING_AREA_NOT_ACTIVE", "receiving area is not ACTIVE")

    eligible = area["eligible_sending_area_codes"]
    if eligible:
        origin_area = db.sending_areas.get(cert["origin_sending_area_id"])
        origin_code = origin_area["code"] if origin_area else None
        if origin_code not in eligible:
            fail("ERR_SENDING_RECEIVING_PAIR_NOT_ELIGIBLE",
                 "sending area %s is not eligible for this receiving area" % origin_code)

    if units > available_units(cert):
        fail("ERR_INSUFFICIENT_CERTIFICATE_UNITS", "only %d units are unencumbered" % available_units(cert))

    rec = new_record(
        {
            "receiving_site_application_id": app["id"],
            "certificate_id": cert["id"],
            "source_easement_id": cert["conservation_easement_id"],
            "units": units,
            "status": "ALLOCATED",
            "allocated_at": now(),
            "confirmed_at": None,
            "released_at": None,
        }
    )
    db.certificate_redemptions[rec["id"]] = rec

    cert["units_encumbered"] = int(cert["units_encumbered"]) + units
    touch(cert)
    recompute_receiving_area_units(area)
    touch(area)
    recompute_application_backing(app)
    if app["status"] == "BACKING_DEFICIENT" and (
        int(app["backed_units"]) + int(app["pending_backed_units"]) >= int(app["required_backing_units"])
    ):
        app["status"] = "DESIGN_APPROVED"
    touch(app)
    return respond_object(serializers.certificate_redemption(rec), 201)


@bp.get("/tdr/certificate-redemptions/<redemption_id>")
def get_redemption(redemption_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.certificate_redemption(get_redemption_or_404(redemption_id)))


@bp.get("/tdr/certificate-redemptions")
def list_redemptions():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.certificate_redemptions.values()),
        receiving_site_application_id=filter_str("receiving_site_application_id"),
        certificate_id=filter_str("certificate_id"),
        source_easement_id=filter_str("source_easement_id"),
        status=filter_enum("status", REDEMPTION_STATUSES),
    )
    return paged(rows, serializers.certificate_redemption)


@bp.post("/tdr/certificate-redemptions/<redemption_id>/release")
def release_redemption(redemption_id):
    user_id, role = require_roles(DEVELOPER, ADMIN)
    red = get_redemption_or_404(redemption_id)
    data = body()
    field_str(data, "reason", required=False)

    app = db.receiving_site_applications.get(red["receiving_site_application_id"])
    require_owner(user_id, role, app["developer_party_id"] if app else None)

    if red["status"] not in OPEN_REDEMPTION_STATUSES:
        fail("ERR_REDEMPTION_NOT_RELEASABLE", "redemption is %s" % red["status"])
    if app is not None and app["status"] == "FINALIZED":
        fail("ERR_REDEMPTION_NOT_RELEASABLE", "the application is already FINALIZED")

    area = db.receiving_areas.get(app["receiving_area_id"]) if app else None
    _release_redemption(red, app, area)
    if area is not None:
        touch(area)
    if app is not None:
        if app["status"] == "DESIGN_APPROVED" and (
            int(app["backed_units"]) + int(app["pending_backed_units"]) < int(app["required_backing_units"])
        ):
            app["status"] = "BACKING_DEFICIENT"
        touch(app)
    return respond_object(serializers.certificate_redemption(red))
