"""Certification listings, publication and firmware revisions (PRD 3.9)."""

from flask import Blueprint

import cascade
import common as C
import enums as E
import middleware as M
import queries as Q
import shape as S
from db import new_row, now, ordered, plus_days, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("listings", __name__)


@bp.post("/listings")
def create_listing():
    M.auth([M.PROGRAM_ADMIN])
    body = S.body_obj()
    # rung 5
    submission = C.body_fk("submission", body, "submission_id")
    # rung 6
    S.req_str(body, "submission_id")
    # rung 16
    if submission["state"] not in ("REVIEW_COMPLETE", "CERTIFIED"):
        raise ApiError("ERR_INVALID_SUBMISSION_STATE",
                       "a listing requires a REVIEW_COMPLETE or CERTIFIED submission")
    # rung 36
    if Q.listing_for_submission(submission["id"]) is not None:
        raise ApiError("ERR_LISTING_ALREADY_EXISTS", "this submission already has a listing")

    listing = new_row(
        submission_id=submission["id"],
        member_id=submission["member_id"],
        listing_reference=cascade.next_listing_reference(),
        declared_features=cascade.resolve_declared_features(submission),
        publication_status="UNPUBLISHED",
        compliance_status="COMPLIANT",
        recertification_due_at=None,
        recert_trigger_reason=None,
        latest_firmware_version=None,
        recert_classification=None,
        firmware_revision_count=0,
        published_at=None,
    )
    store.listings[listing["id"]] = listing
    return object_response(public(listing), 201)


@bp.get("/listings/<listing_id>")
def get_listing(listing_id):
    M.auth(M.ALL_ROLES)
    return object_response(public(C.must("listing", listing_id)), 200)


@bp.get("/listings")
def list_listings():
    M.auth(M.ALL_ROLES)
    limit, offset = S.paging()
    submission_id = S.q_str("submission_id")
    member_id = S.q_str("member_id")
    publication_status = S.q_str("publication_status")
    compliance_status = S.q_str("compliance_status")
    rows = ordered(store.listings.values())
    if submission_id is not None:
        rows = [r for r in rows if r["submission_id"] == submission_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if publication_status is not None:
        rows = [r for r in rows if r["publication_status"] == publication_status]
    if compliance_status is not None:
        rows = [r for r in rows if r["compliance_status"] == compliance_status]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/listings/<listing_id>/publish")
def publish_listing(listing_id):
    M.auth([M.PROGRAM_ADMIN])
    listing = C.must("listing", listing_id)
    submission = store.submissions[listing["submission_id"]]
    member = store.members[listing["member_id"]]
    # rung 16
    if submission["dac_state"] != "ISSUED":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE",
                       "publication requires an ISSUED device attestation credential")
    # rung 22
    if (listing["publication_status"] not in ("UNPUBLISHED", "SUPPRESSED")
            or listing["compliance_status"] not in ("COMPLIANT", "REMEDIATED")):
        raise ApiError("ERR_INVALID_LISTING_STATE", "the listing cannot be published in its state")
    # rung 25
    if not member["good_standing"]:
        raise ApiError("ERR_MEMBER_NOT_IN_GOOD_STANDING", "the member is not in good standing")

    set_fields(listing,
               publication_status="PUBLISHED",
               published_at=now(),
               declared_features=cascade.resolve_declared_features(submission))
    return object_response(public(listing), 200)


@bp.post("/listings/<listing_id>/withdraw")
def withdraw_listing(listing_id):
    M.auth([M.COMPLIANCE_OFFICER])
    listing = C.must("listing", listing_id)
    body = S.body_obj()
    S.req_str(body, "reason", 1, 500)
    # rung 22
    if listing["publication_status"] == "WITHDRAWN":
        raise ApiError("ERR_INVALID_LISTING_STATE", "the listing is already WITHDRAWN")
    set_fields(listing, publication_status="WITHDRAWN", compliance_status="NONCOMPLIANT")
    cascade.revoke_credential(store.submissions.get(listing["submission_id"]))
    return object_response(public(listing), 200)


@bp.post("/listings/<listing_id>/firmware-revisions")
def report_firmware_revision(listing_id):
    M.auth([M.PROGRAM_ADMIN, M.MEMBER])
    listing = C.must("listing", listing_id)
    submission = store.submissions[listing["submission_id"]]
    spec = store.specifications[submission["specification_id"]]
    body = S.body_obj()
    # rung 6
    firmware_version = S.req_str(body, "firmware_version", 1, 40)
    changed_codes = S.req_str_array(body, "changed_feature_codes", allow_empty=True)
    security_change = S.req_bool(body, "security_change")
    expected_version = S.req_int(body, "expected_listing_version")
    # rung 12
    if expected_version != listing["version"]:
        raise ApiError("ERR_STALE_LISTING_VERSION",
                       "expected_listing_version does not match the stored version")
    # rung 22
    if listing["publication_status"] == "WITHDRAWN":
        raise ApiError("ERR_INVALID_LISTING_STATE",
                       "a revision cannot be reported against a WITHDRAWN listing")
    # rung 33
    catalogue = {fs["feature_code"]: fs
                 for fs in Q.feature_sets_for(spec["id"], submission["device_type"])}
    for code in changed_codes:
        if code not in catalogue:
            raise ApiError("ERR_UNKNOWN_FEATURE_CODE", "feature_code %s is unknown" % code)

    # classification -- five ordered rules, first match decides
    overlap = [code for code in changed_codes if code in listing["declared_features"]]
    security_sets = [code for code in overlap if catalogue[code]["security_relevant"]]
    if security_change and spec["security_baseline_level"] in ("SB2", "SB3"):
        classification, reason = "FULL", "FIRMWARE_SECURITY_CHANGE"
    elif len(security_sets) >= 1:
        classification, reason = "FULL", "FIRMWARE_SECURITY_CHANGE"
    elif len(overlap) > 2:
        classification, reason = "FULL", "FIRMWARE_FEATURE_DELTA"
    elif len(overlap) >= 1:
        classification, reason = "DELTA", "FIRMWARE_FEATURE_DELTA"
    else:
        classification, reason = "NONE", listing["recert_trigger_reason"]

    fields = {
        "latest_firmware_version": firmware_version,
        "firmware_revision_count": listing["firmware_revision_count"] + 1,
        "recert_classification": classification,
        "recert_trigger_reason": reason,
    }
    if classification == "FULL":
        fields["recertification_due_at"] = plus_days(now(), 30)
        if listing["publication_status"] == "PUBLISHED":
            fields["publication_status"] = "SUPPRESSED"
    elif classification == "DELTA":
        fields["recertification_due_at"] = plus_days(now(), 90)
    set_fields(listing, **fields)
    if classification == "FULL":
        cascade.revoke_credential(submission)
    return object_response(public(listing), 200)
