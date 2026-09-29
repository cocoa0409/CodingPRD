"""Federal disposition requests, the grantor's determination and withdrawal."""

from flask import Blueprint

import authz
import calc
import common
import enums
import envelope
import shape
import store
from errors import fail

bp = Blueprint("federal", __name__)

REJECTION_PREFIX = "federal disposition rejected: "


def _release_encumbrance(site, amount):
    """The compensating half of a filing: exactly the same cents move back."""
    site["federal_interest_encumbered_cents"] -= amount
    site["federal_interest_unencumbered_cents"] += amount
    store.touch(site)


@bp.post("/jda/agreements/<agreement_id>/disposition-requests")
def file_disposition(agreement_id):
    authz.authorize("GrantsComplianceOfficer")
    body = shape.body()
    narrative = shape.as_str(body, "narrative")
    agreement = store.require("agreement", agreement_id)
    if agreement["negotiation_status"] not in ("AGENCY_REVIEW", "BOARD_APPROVED"):
        fail("ERR_AGREEMENT_NOT_IN_REVIEW",
             "Filing requires the agreement to be in AGENCY_REVIEW or BOARD_APPROVED")
    if agreement["federal_approval_status"] != "NOT_SUBMITTED":
        fail("ERR_FEDERAL_APPROVAL_PENDING",
             "Federal approval status is %s" % agreement["federal_approval_status"])
    site = store.require("site", agreement["site_id"])
    amount = calc.federal_interest_amount(site["federal_interest_basis_cents"],
                                          agreement["site_area_share_pct"])
    if site["federal_interest_unencumbered_cents"] < amount:
        fail("ERR_FEDERAL_INTEREST_INSUFFICIENT",
             "Only %d cents of federal interest remain unencumbered against %d required"
             % (site["federal_interest_unencumbered_cents"], amount))
    request_rec = store.create("disposition_request", {
        "jda_id": agreement_id,
        "narrative": narrative,
        "federal_interest_amount_cents": amount,
        "determination": "PENDING",
        "condition_notes": None,
        "determined_at": None,
    })
    agreement["federal_approval_status"] = "SUBMITTED"
    store.touch(agreement)
    site["federal_interest_encumbered_cents"] += amount
    site["federal_interest_unencumbered_cents"] -= amount
    store.touch(site)
    return envelope.created(common.public(request_rec))


@bp.post("/jda/disposition-requests/<request_id>/determination")
def record_determination(request_id):
    authz.authorize("GrantsComplianceOfficer")
    body = shape.body()
    determination = shape.as_enum(body, "determination", enums.DETERMINATION_INPUT)
    condition_notes = shape.as_str(body, "condition_notes", required=False, default=None)
    if determination in ("APPROVED_WITH_CONDITIONS", "REJECTED"):
        if not condition_notes or not condition_notes.strip():
            fail("ERR_INVALID_REQUEST",
                 "condition_notes is required for %s" % determination)
    request_rec = store.require("disposition_request", request_id)
    if request_rec["determination"] != "PENDING":
        fail("ERR_DISPOSITION_ALREADY_DETERMINED",
             "This disposition request is already %s" % request_rec["determination"])
    agreement = store.get("agreement", request_rec["jda_id"])

    # hop 1 — the request records the grantor's answer
    request_rec["determination"] = determination
    request_rec["determined_at"] = store.now_iso()
    if condition_notes is not None:
        request_rec["condition_notes"] = condition_notes
    store.touch(request_rec)

    if determination in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
        # An approved disposition consumes the pledged federal interest; the site
        # ledger and negotiation_status are both untouched.
        if agreement is not None:
            agreement["federal_approval_status"] = "FTA_APPROVED"
            store.touch(agreement)
        return envelope.ok(common.public(request_rec))

    # ---- the rejection cascade ----
    was_board_approved = False
    if agreement is not None:
        was_board_approved = agreement["negotiation_status"] == "BOARD_APPROVED"
        # hop 2
        agreement["federal_approval_status"] = "FTA_REJECTED"
        if was_board_approved:
            agreement["negotiation_status"] = "REVISION_REQUESTED"
            agreement["revision_notes"] = REJECTION_PREFIX + (request_rec["condition_notes"] or "")
            agreement["board_resolution_number"] = None
        store.touch(agreement)
        if was_board_approved:
            # hop 3a — the appraisal behind the deal is no longer certified
            valuation = store.get("valuation", agreement["valuation_id"])
            if valuation is not None and valuation["status"] == "CERTIFIED":
                valuation["status"] = "SUPERSEDED"
                store.touch(valuation)
            # hop 3b/4 — unauthorised construction must not keep bus bays out of
            # service; each window releases its bays exactly once
            for window in store.by_seq(common.windows_of_agreement(agreement["id"])):
                if window["status"] != "APPROVED":
                    continue
                window["status"] = "SUSPENDED"
                window["capacity_released"] = True
                store.touch(window)
                facility = store.get("shared_facility", window["shared_facility_id"])
                if facility is not None:
                    common.refresh_available_bays(facility)
                    store.touch(facility)
    # hop 5 — unconditional: the ledger identity is restored
    site = store.get("site", agreement["site_id"]) if agreement is not None else None
    if site is not None:
        _release_encumbrance(site, request_rec["federal_interest_amount_cents"])
    return envelope.ok(common.public(request_rec))


@bp.post("/jda/disposition-requests/<request_id>/withdraw")
def withdraw_disposition(request_id):
    authz.authorize("GrantsComplianceOfficer")
    body = shape.body()
    withdraw_reason = shape.as_str(body, "withdraw_reason")
    request_rec = store.require("disposition_request", request_id)
    if request_rec["determination"] != "PENDING":
        fail("ERR_DISPOSITION_ALREADY_DETERMINED",
             "This disposition request is already %s" % request_rec["determination"])
    request_rec["determination"] = "WITHDRAWN"
    request_rec["condition_notes"] = withdraw_reason
    request_rec["determined_at"] = store.now_iso()
    store.touch(request_rec)
    agreement = store.get("agreement", request_rec["jda_id"])
    if agreement is not None:
        agreement["federal_approval_status"] = "NOT_SUBMITTED"
        store.touch(agreement)
        site = store.get("site", agreement["site_id"])
        if site is not None:
            _release_encumbrance(site, request_rec["federal_interest_amount_cents"])
    return envelope.ok(common.public(request_rec))
