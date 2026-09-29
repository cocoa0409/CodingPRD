"""Usage licenses: issuance, billing, disclosure, go-live and removal."""

from flask import Blueprint, g

import calc
import guards
import services
from core import (
    ALL_ROLES, authorize, body_json, collection, db, fail, invalid, new_id, now,
    public, respond, touch, want_code_list, want_dt, want_enum, want_int, want_str,
)

bp = Blueprint("licenses", __name__)

PLACEMENTS = ("METADATA_ONLY", "END_CARD", "PRE_ROLL", "PERSISTENT_BUG")


def _windows_overlap_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.post("/usage-licenses")
def issue_license():
    authorize("LicenseeProducer")
    body = body_json()
    generated_performance_id = want_str(body, "generated_performance_id", 1, None)
    channel = want_enum(body, "channel", calc.CHANNELS)
    territory_codes = want_code_list(body, "territory_codes", 20)
    distribution_start = want_dt(body, "distribution_start")
    distribution_end = want_dt(body, "distribution_end")
    actual_impressions = want_int(body, "actual_impressions", 0)
    expected_replica_version = want_int(body, "expected_replica_version", 0)
    if distribution_end < distribution_start:
        invalid("distribution_end must be at or after distribution_start")

    performance = guards.need_performance(generated_performance_id)
    replica = db.digital_replicas[performance["digital_replica_id"]]
    grant = db.consent_grants[replica["consent_grant_id"]]
    talent = db.talents[replica["talent_id"]]

    profile = guards.need_profile(talent["domicile_state_code"])
    floor = guards.need_union_per_use_floor(grant, performance["media_type"])

    guards.licensee_ownership(performance["licensee_user_id"], g.user_id)

    if expected_replica_version != int(replica["version"]):
        fail("ERR_REPLICA_VERSION_STALE",
             "expected_replica_version %s does not match the replica's current version %s"
             % (expected_replica_version, replica["version"]))

    if grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the governing consent grant is not ACTIVE")
    if performance["review_status"] != "APPROVED":
        fail("ERR_INVALID_PERFORMANCE_STATE",
             "only an APPROVED performance may be licensed")
    guards.block_frozen(talent)
    guards.block_restricted(talent)

    mapped_media = "ADVERTISING" if channel == "ADVERTISING" else performance["media_type"]
    if mapped_media not in grant["permitted_media_types"]:
        fail("ERR_MEDIA_TYPE_OUT_OF_SCOPE",
             "the %s channel maps to %s, outside the grant's permitted media types"
             % (channel, mapped_media))
    for code in territory_codes:
        if code not in grant["territory_codes"] or code not in performance["territory_codes"]:
            fail("ERR_TERRITORY_OUT_OF_SCOPE",
                 "territory %s is outside the grant's or the performance's scope" % code)

    if distribution_start < grant["effective_from"] or distribution_end >= grant["effective_until"]:
        fail("ERR_WINDOW_EXCEEDS_CONSENT_TERM",
             "the distribution window must lie entirely inside the consent term")

    overlapping = 0
    for other in services.licenses_of_replica(replica["id"]):
        if other["distribution_status"] not in ("ISSUED", "LIVE"):
            continue
        if not _windows_overlap_closed(distribution_start, distribution_end,
                                      other["distribution_start"], other["distribution_end"]):
            continue
        if not set(territory_codes).intersection(set(other["territory_codes"])):
            continue
        overlapping += 1
    if overlapping >= calc.MAX_OVERLAPPING_LICENSES:
        fail("ERR_REPLICA_OVERLAP_CAP_EXCEEDED",
             "at most %d overlapping licenses may share a replica and a territory"
             % calc.MAX_OVERLAPPING_LICENSES)

    disclosure_required = bool(
        profile["disclosure_required_advertising"] if channel == "ADVERTISING"
        else profile["disclosure_required_entertainment"])
    per_use_final = calc.per_use_compensation(grant, performance["media_type"],
                                             actual_impressions, territory_codes, floor)
    surcharge, total = calc.license_total_cost(per_use_final, disclosure_required, channel)

    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "generated_performance_id": performance["id"],
        "licensee_user_id": performance["licensee_user_id"],
        "channel": channel,
        "territory_codes": territory_codes,
        "distribution_start": distribution_start,
        "distribution_end": distribution_end,
        "actual_impressions": actual_impressions,
        "distribution_reference": None,
        "distribution_status": "ISSUED",
        "compliance_status": "PENDING_LABEL" if disclosure_required else "VERIFIED",
        "disclosure_required": disclosure_required,
        "disclosure_placement": None,
        "disclosure_label_text": None,
        "disclosure_verified_by_user_id": None,
        "per_use_final_cents": per_use_final,
        "compliance_surcharge_cents": surcharge,
        "license_total_cents": total,
        "removal_deadline": None,
        "removal_reason": None,
        "removal_confirmed_at": None,
        "issued_by_user_id": g.user_id,
        "_seq": db.next_seq(),
    }
    db.usage_licenses[row["id"]] = row
    services.append_entry(grant, "PER_USE_FINAL", per_use_final,
                          license_id=row["id"],
                          memo="Final per-use royalty at license issuance")
    services.recompute_grant_total(grant)
    services.recompute_replica_open_count(replica)
    touch(replica)
    services.recompute_talent(talent)
    touch(talent)
    return respond(public(row), 201)


@bp.get("/usage-licenses/<row_id>")
def read_license(row_id):
    authorize(*ALL_ROLES)
    return respond(public(guards.need_license(row_id)))


@bp.get("/usage-licenses")
def list_licenses():
    authorize(*ALL_ROLES)
    return collection(db.usage_licenses.values(), {
        "generated_performance_id": "generated_performance_id",
        "licensee_user_id": "licensee_user_id",
        "distribution_status": "distribution_status",
        "compliance_status": "compliance_status",
        "channel": "channel",
    })


@bp.post("/usage-licenses/<row_id>/disclosure")
def attest_disclosure(row_id):
    authorize("LicenseeProducer")
    body = body_json()
    placement = want_enum(body, "disclosure_placement", PLACEMENTS)
    label_text = want_str(body, "disclosure_label_text", 1, 200)
    license_row = guards.need_license(row_id)
    talent = services.talent_of_license(license_row)
    profile = guards.need_profile(talent["domicile_state_code"])
    guards.licensee_ownership(license_row["licensee_user_id"], g.user_id)
    if license_row["compliance_status"] not in ("PENDING_LABEL", "NON_COMPLIANT"):
        fail("ERR_INVALID_DISCLOSURE_STATE",
             "this license's disclosure has already been attested")
    minimum = (profile["min_disclosure_rank_advertising"]
               if license_row["channel"] == "ADVERTISING"
               else profile["min_disclosure_rank_entertainment"])
    if calc.DISCLOSURE_RANK[placement] < int(minimum):
        fail("ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT",
             "%s ranks below this state's minimum disclosure placement" % placement)
    license_row["compliance_status"] = "LABELED"
    license_row["disclosure_placement"] = placement
    license_row["disclosure_label_text"] = label_text
    license_row["disclosure_verified_by_user_id"] = None
    touch(license_row)
    return respond(public(license_row))


@bp.post("/usage-licenses/<row_id>/disclosure-verification")
def verify_disclosure(row_id):
    authorize("ComplianceOfficer")
    body = body_json()
    decision = want_enum(body, "decision", ("ACCEPT", "REJECT"))
    license_row = guards.need_license(row_id)
    if license_row["compliance_status"] != "LABELED":
        fail("ERR_INVALID_DISCLOSURE_STATE",
             "only a LABELED disclosure may be reviewed")
    if decision == "ACCEPT":
        license_row["compliance_status"] = "VERIFIED"
        license_row["disclosure_verified_by_user_id"] = g.user_id
    else:
        license_row["compliance_status"] = "NON_COMPLIANT"
        license_row["disclosure_verified_by_user_id"] = None
    touch(license_row)
    return respond(public(license_row))


@bp.post("/usage-licenses/<row_id>/go-live")
def go_live(row_id):
    authorize("LicenseeProducer")
    body = body_json()
    reference = want_str(body, "distribution_reference", 1, 300)
    license_row = guards.need_license(row_id)
    grant = services.grant_of_license(license_row)
    talent = services.talent_of_license(license_row)
    guards.licensee_ownership(license_row["licensee_user_id"], g.user_id)
    if grant is not None and grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the governing consent grant is not ACTIVE")
    if license_row["distribution_status"] != "ISSUED":
        fail("ERR_INVALID_LICENSE_STATE", "only an ISSUED license may go live")
    guards.block_frozen(talent)
    guards.block_restricted(talent)
    if license_row["compliance_status"] != "VERIFIED":
        fail("ERR_DISCLOSURE_NOT_VERIFIED",
             "the synthetic-content disclosure has not been verified")
    instant = now()
    if instant < license_row["distribution_start"] or instant > license_row["distribution_end"]:
        fail("ERR_OUTSIDE_DISTRIBUTION_WINDOW",
             "the current logical instant lies outside the distribution window")
    license_row["distribution_status"] = "LIVE"
    license_row["distribution_reference"] = reference
    touch(license_row)
    return respond(public(license_row))


@bp.post("/usage-licenses/<row_id>/confirm-removal")
def confirm_removal(row_id):
    authorize("LicenseeProducer")
    body_json()
    license_row = guards.need_license(row_id)
    talent = services.talent_of_license(license_row)
    replica = services.replica_of_license(license_row)
    guards.licensee_ownership(license_row["licensee_user_id"], g.user_id)
    if license_row["distribution_status"] != "REMOVAL_PENDING":
        fail("ERR_INVALID_LICENSE_STATE",
             "only a REMOVAL_PENDING license may confirm removal")
    license_row["distribution_status"] = "REMOVAL_CONFIRMED"
    license_row["removal_confirmed_at"] = now()
    touch(license_row)
    services.recompute_replica_open_count(replica)
    touch(replica)
    services.recompute_talent(talent)
    touch(talent)
    return respond(public(license_row))
