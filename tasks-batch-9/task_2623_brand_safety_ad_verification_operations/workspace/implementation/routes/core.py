"""Logical clock, advertisers, publishers, methodology versions, campaigns."""

from flask import Blueprint

import calc
import db
import middleware as mw
import response
import services as svc
import validators as v
from errors import fail
from middleware import (
    ROLE_ACCREDITATION_AUDITOR,
    ROLE_ADVERTISER,
    ROLE_CLASSIFICATION_ANALYST,
    ROLE_DISPUTE_OFFICER,
    ROLE_MEASUREMENT_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER,
)
from routes.helpers import build_filters, filtered, respond_list

bp = Blueprint("core", __name__)


# --------------------------------------------------------------------------- #
# logical clock                                                               #
# --------------------------------------------------------------------------- #
@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.clock_caller()
    payload = mw.body()
    instant = v.req_datetime(payload, "to_iso8601")
    db.clock_set(instant)
    return response.object_response({"current_utc": db.now_iso()})


# --------------------------------------------------------------------------- #
# advertisers                                                                 #
# --------------------------------------------------------------------------- #
@bp.post("/advertisers")
def create_advertiser():
    mw.require(ROLE_PLATFORM_ADMIN)
    payload = mw.body()
    name = v.req_string(payload, "name", 1, 120)
    credit_cap_cents = v.req_int(payload, "credit_cap_cents", minimum=0, default=1000000)
    record = db.new_record(
        {
            "name": name,
            "credit_cap_cents": credit_cap_cents,
            "credit_received_cents_total": 0,
            "settled_claim_count": 0,
        }
    )
    db.advertisers[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/advertisers/<advertiser_id>")
def read_advertiser(advertiser_id):
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER, ROLE_DISPUTE_OFFICER)
    mw.own_advertiser(caller, advertiser_id)
    record = svc.require_path(db.advertisers, advertiser_id, "ERR_ADVERTISER_NOT_FOUND")
    return response.object_response(record)


# --------------------------------------------------------------------------- #
# publishers                                                                  #
# --------------------------------------------------------------------------- #
@bp.post("/publishers")
def create_publisher():
    mw.require(ROLE_PLATFORM_ADMIN)
    payload = mw.body()
    name = v.req_string(payload, "name", 1, 120)
    primary_domain = v.req_string(payload, "primary_domain", 1, 300)
    sourced_traffic_pct = v.req_decimal(
        payload, "sourced_traffic_pct", minimum=0, maximum=1, default="0.0"
    )
    for existing in db.publishers.values():
        if existing["primary_domain"] == primary_domain:
            fail("ERR_DUPLICATE_PUBLISHER_DOMAIN")
    record = db.new_record(
        {
            "name": name,
            "primary_domain": primary_domain,
            "sourced_traffic_pct": calc.plain(sourced_traffic_pct),
            "publisher_status": "ACTIVE",
            "status_reason": None,
            "mfa_page_count": 0,
            "quarantined_batch_count": 0,
            "certified_batch_count": 0,
            "decided_appeal_count": 0,
            "overturned_appeal_count": 0,
            "credit_issued_cents_total": 0,
        }
    )
    db.publishers[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/publishers/<publisher_id>")
def read_publisher(publisher_id):
    caller = mw.require(
        ROLE_PLATFORM_ADMIN,
        ROLE_PUBLISHER,
        ROLE_CLASSIFICATION_ANALYST,
        ROLE_MEASUREMENT_OPERATOR,
        ROLE_DISPUTE_OFFICER,
        ROLE_ACCREDITATION_AUDITOR,
    )
    mw.own_publisher(caller, publisher_id)
    record = svc.require_path(db.publishers, publisher_id, "ERR_PUBLISHER_NOT_FOUND")
    return response.object_response(record)


@bp.post("/publishers/<publisher_id>/status")
def change_publisher_status(publisher_id):
    mw.require(ROLE_PLATFORM_ADMIN)
    record = svc.require_path(db.publishers, publisher_id, "ERR_PUBLISHER_NOT_FOUND")
    payload = mw.body()
    new_status = v.req_enum(payload, "new_status", {"ACTIVE", "RESTRICTED", "DELISTED"})
    v.opt_string(payload, "reason")
    current = record["publisher_status"]
    if current == "DELISTED":
        fail("ERR_PUBLISHER_DELISTED")
    if new_status == "ACTIVE":
        if current != "RESTRICTED":
            fail("ERR_INVALID_PUBLISHER_STATE")
        if (
            int(record["quarantined_batch_count"]) >= calc.PUBLISHER_QUARANTINE_LIMIT
            or int(record["mfa_page_count"]) >= calc.PUBLISHER_MFA_LIMIT
        ):
            fail("ERR_RESTRICTION_STILL_JUSTIFIED")
        record["publisher_status"] = "ACTIVE"
        record["status_reason"] = "ADMIN_REINSTATEMENT"
    elif new_status == "DELISTED":
        record["publisher_status"] = "DELISTED"
        record["status_reason"] = "ADMIN_ACTION"
    else:
        # RESTRICTED is imposed by the platform, never requested by a client.
        fail("ERR_INVALID_PUBLISHER_STATE")
    db.touch(record)
    return response.object_response(record)


@bp.get("/publishers/<publisher_id>/scorecard")
def read_scorecard(publisher_id):
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_PUBLISHER, ROLE_DISPUTE_OFFICER)
    mw.own_publisher(caller, publisher_id)
    record = svc.require_path(db.publishers, publisher_id, "ERR_PUBLISHER_NOT_FOUND")
    adjudicated = [
        batch
        for batch in db.measurement_batches.values()
        if batch["publisher_id"] == publisher_id
        and batch["scoring_status"] in ("CERTIFIED", "QUARANTINED", "DECERTIFIED")
    ]
    figures = calc.quality_index(record, adjudicated)
    return response.object_response(
        {
            "publisher_id": publisher_id,
            "adjudicated_batch_count": len(adjudicated),
            "ivt_rate_avg": calc.num4(figures["ivt_rate_avg"]),
            "viewability_rate_avg": calc.num4(figures["viewability_rate_avg"]),
            "overturn_rate": calc.num4(figures["overturn_rate"]),
            "mfa_page_count": int(record["mfa_page_count"]),
            "quarantined_batch_count": int(record["quarantined_batch_count"]),
            "quality_index": calc.num2(figures["quality_index"]),
            "tier_band": figures["tier_band"],
        }
    )


# --------------------------------------------------------------------------- #
# methodology versions                                                        #
# --------------------------------------------------------------------------- #
_THRESHOLD_SPECS = (
    ("display_in_view_seconds", 0, None, True, False),
    ("video_in_view_seconds", 0, None, True, False),
    ("display_pixel_pct", 0, 1, True, False),
    ("large_display_pixel_pct", 0, 1, True, False),
    ("video_pixel_pct", 0, 1, True, False),
    ("coverage_rate_floor", 0, 1, True, False),
    ("ivt_rate_ceiling", 0, 1, False, True),
)


@bp.post("/methodology-versions")
def create_methodology_version():
    caller = mw.require(ROLE_ACCREDITATION_AUDITOR)
    payload = mw.body()
    standard_family = v.req_enum(payload, "standard_family", calc.STANDARD_FAMILY_SET)
    version_code = v.req_string(payload, "version_code", 1, 40)
    effective_from = v.req_datetime(payload, "effective_from")
    effective_to = v.req_datetime(payload, "effective_to")
    if effective_to <= effective_from:
        fail("ERR_INVALID_REQUEST", "effective_to must be strictly after effective_from.")
    thresholds = {}
    for field, minimum, maximum, exclusive_min, exclusive_max in _THRESHOLD_SPECS:
        thresholds[field] = v.req_decimal(
            payload,
            field,
            minimum=minimum,
            maximum=maximum,
            exclusive_min=exclusive_min,
            exclusive_max=exclusive_max,
            default=calc.METHODOLOGY_DEFAULTS[field],
        )
    family_peers = [
        record
        for record in db.ordered(list(db.methodology_versions.values()))
        if record["standard_family"] == standard_family
    ]
    for peer in family_peers:
        if peer["version_code"] == version_code:
            fail("ERR_DUPLICATE_VERSION_CODE")
    for peer in family_peers:
        peer_from = db.parse_dt(peer["effective_from"])
        peer_to = db.parse_dt(peer["effective_to"])
        # Half-open windows overlap unless one ends exactly where the other starts.
        if effective_from < peer_to and peer_from < effective_to:
            fail("ERR_METHODOLOGY_WINDOW_OVERLAP")
    record = db.new_record(
        {
            "standard_family": standard_family,
            "version_code": version_code,
            "effective_from": db.fmt_dt(effective_from),
            "effective_to": db.fmt_dt(effective_to),
            "accreditation_status": "PROVISIONAL",
            "authored_by_user_id": caller.user_id,
            "lead_auditor_user_id": None,
            "audit_outcome": None,
            "audit_finding_rate": None,
            "deficiency_note": None,
            "decertified_batch_count": 0,
        }
    )
    for field, value in thresholds.items():
        record[field] = calc.plain(value)
    db.methodology_versions[record["id"]] = record
    return response.object_response(record, 201)


_METHODOLOGY_READERS = (
    ROLE_PLATFORM_ADMIN,
    ROLE_ACCREDITATION_AUDITOR,
    ROLE_MEASUREMENT_OPERATOR,
    ROLE_CLASSIFICATION_ANALYST,
    ROLE_DISPUTE_OFFICER,
)


@bp.get("/methodology-versions/<version_id>")
def read_methodology_version(version_id):
    mw.require(*_METHODOLOGY_READERS)
    record = svc.require_path(
        db.methodology_versions, version_id, "ERR_METHODOLOGY_VERSION_NOT_FOUND"
    )
    return response.object_response(record)


@bp.get("/methodology-versions")
def list_methodology_versions():
    mw.require(*_METHODOLOGY_READERS)
    predicates = build_filters(
        {"standard_family": "standard_family", "accreditation_status": "accreditation_status"}
    )
    return respond_list(filtered(db.methodology_versions, predicates))


@bp.post("/methodology-versions/<version_id>/audit-conclusion")
def conclude_audit(version_id):
    caller = mw.require(ROLE_ACCREDITATION_AUDITOR)
    record = svc.require_path(
        db.methodology_versions, version_id, "ERR_METHODOLOGY_VERSION_NOT_FOUND"
    )
    payload = mw.body()
    outcome = v.req_enum(payload, "outcome", {"PASSED", "DEFICIENT"})
    finding_rate = v.req_decimal(payload, "audit_finding_rate", minimum=0, maximum=1)
    note = v.opt_string(payload, "deficiency_note")
    status = record["accreditation_status"]
    # priority 7 -- state reachability
    if outcome == "PASSED" and status != "PROVISIONAL":
        fail("ERR_INVALID_METHODOLOGY_STATE")
    if outcome == "DEFICIENT" and status not in ("PROVISIONAL", "ACCREDITED"):
        fail("ERR_INVALID_METHODOLOGY_STATE")
    # priority 11 -- segregation of duties on audits
    author = record.get("authored_by_user_id")
    if author is not None and caller.user_id == author:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if outcome == "PASSED":
        if finding_rate > calc.AUDIT_MAX_FINDING_RATE:
            fail("ERR_AUDIT_FINDING_RATE_TOO_HIGH")
        record["accreditation_status"] = "ACCREDITED"
        record["audit_outcome"] = "PASSED"
        record["lead_auditor_user_id"] = caller.user_id
        record["audit_finding_rate"] = calc.plain(finding_rate)
        db.touch(record)
        return response.object_response(record)
    if note is None or not note.strip():
        fail("ERR_DEFICIENCY_NOTE_REQUIRED")
    record["accreditation_status"] = "SUSPENDED"
    record["audit_outcome"] = "DEFICIENT"
    record["lead_auditor_user_id"] = caller.user_id
    record["audit_finding_rate"] = calc.plain(finding_rate)
    record["deficiency_note"] = note
    db.touch(record)
    _decertify_cascade(record)
    return response.object_response(record)


def _decertify_cascade(methodology):
    """PRD section 3.2 severe branch: four synchronous hops."""
    affected = {}
    moved = 0
    for batch in db.ordered(list(db.measurement_batches.values())):
        if batch["methodology_version_id"] != methodology["id"]:
            continue
        if batch["scoring_status"] != "CERTIFIED":
            continue
        # hop 1 -- repudiate the certification
        batch["scoring_status"] = "DECERTIFIED"
        db.touch(batch)
        moved += 1
        publisher = db.publishers.get(batch["publisher_id"])
        if publisher is not None:
            publisher["certified_batch_count"] = max(
                0, int(publisher["certified_batch_count"]) - 1
            )
            db.touch(publisher)
        campaign = db.campaigns.get(batch["campaign_id"])
        if campaign is not None:
            # hop 2 -- withdraw the batch's contribution to campaign coverage
            campaign["certified_measured_impressions"] = max(
                0,
                int(campaign["certified_measured_impressions"])
                - int(batch["measured_impressions"]),
            )
            campaign["certified_measurable_impressions"] = max(
                0,
                int(campaign["certified_measurable_impressions"])
                - int(batch["measurable_impressions"]),
            )
            affected[campaign["id"]] = campaign
    methodology["decertified_batch_count"] = moved
    for campaign in db.ordered(list(affected.values())):
        # hops 3 and 4 -- remediation and segment staling
        svc.refresh_coverage_after_decertify(campaign)


# --------------------------------------------------------------------------- #
# campaigns                                                                   #
# --------------------------------------------------------------------------- #
_CAMPAIGN_READERS = (
    ROLE_PLATFORM_ADMIN,
    ROLE_ADVERTISER,
    ROLE_DISPUTE_OFFICER,
    ROLE_MEASUREMENT_OPERATOR,
)


@bp.post("/campaigns")
def create_campaign():
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER)
    payload = mw.body()
    advertiser_id = payload.get("advertiser_id")
    # priority 3 ownership precedes priority 5 reference existence
    mw.own_advertiser(caller, advertiser_id if isinstance(advertiser_id, str) else None)
    advertiser = svc.require_ref(db.advertisers, advertiser_id, "ERR_ADVERTISER_NOT_FOUND")
    name = v.req_string(payload, "name", 1, 120)
    cpm_cents = v.req_int(payload, "cpm_cents", minimum=1)
    min_suitability_tier = v.req_enum(payload, "min_suitability_tier", calc.TIER_SET)
    target_coverage_rate = v.req_decimal(
        payload, "target_coverage_rate", minimum=0, maximum=1, exclusive_min=True,
        default="0.75",
    )
    fmt = v.req_enum(payload, "format", calc.FORMAT_SET)
    record = db.new_record(
        {
            "advertiser_id": advertiser["id"],
            "name": name,
            "cpm_cents": cpm_cents,
            "min_suitability_tier": min_suitability_tier,
            "target_coverage_rate": calc.plain(target_coverage_rate),
            "format": fmt,
            "status": "ACTIVE",
            "coverage_status": "UNKNOWN",
            "certified_measured_impressions": 0,
            "certified_measurable_impressions": 0,
            "open_claim_count": 0,
        }
    )
    db.campaigns[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/campaigns/<campaign_id>")
def read_campaign(campaign_id):
    caller = mw.require(*_CAMPAIGN_READERS)
    record = svc.find(db.campaigns, campaign_id)
    mw.own_campaign(caller, record)
    if record is None:
        fail("ERR_CAMPAIGN_NOT_FOUND")
    return response.object_response(record)


@bp.get("/campaigns")
def list_campaigns():
    caller = mw.require(*_CAMPAIGN_READERS)
    predicates = build_filters({"advertiser_id": "advertiser_id", "status": "status"})
    if caller.is_advertiser:
        predicates.append(lambda record: record["advertiser_id"] == caller.user_id)
    return respond_list(filtered(db.campaigns, predicates))
