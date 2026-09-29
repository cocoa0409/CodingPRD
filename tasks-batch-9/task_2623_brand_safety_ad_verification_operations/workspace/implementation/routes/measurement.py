"""Post-bid measurement batches, their scoring and branching certification,
plus the invalid-traffic findings that feed them."""

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
    ROLE_DISPUTE_OFFICER,
    ROLE_MEASUREMENT_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER,
)
from routes.helpers import build_filters, filtered, respond_list

bp = Blueprint("measurement", __name__)

BATCH_READERS = (
    ROLE_PLATFORM_ADMIN,
    ROLE_MEASUREMENT_OPERATOR,
    ROLE_ADVERTISER,
    ROLE_PUBLISHER,
    ROLE_DISPUTE_OFFICER,
    ROLE_ACCREDITATION_AUDITOR,
)
FINDING_READERS = (
    ROLE_PLATFORM_ADMIN,
    ROLE_MEASUREMENT_OPERATOR,
    ROLE_PUBLISHER,
    ROLE_DISPUTE_OFFICER,
    ROLE_ACCREDITATION_AUDITOR,
)
BATCH_UNADJUDICATED = ("INGESTED", "SCORED")


def _own_batch(caller, batch):
    if batch is None:
        return
    mw.own_publisher(caller, batch["publisher_id"])
    mw.own_campaign(caller, db.campaigns.get(batch["campaign_id"]))


# --------------------------------------------------------------------------- #
# ingestion (PRD section 3.7)                                                         #
# --------------------------------------------------------------------------- #
@bp.post("/measurement-batches")
def ingest_batch():
    mw.require(ROLE_MEASUREMENT_OPERATOR)
    payload = mw.body()
    # priority 5 -- body reference existence
    campaign = svc.require_ref(db.campaigns, payload.get("campaign_id"), "ERR_CAMPAIGN_NOT_FOUND")
    publisher = svc.require_ref(
        db.publishers, payload.get("publisher_id"), "ERR_PUBLISHER_NOT_FOUND"
    )
    page = svc.require_ref(db.pages, payload.get("page_id"), "ERR_PAGE_NOT_FOUND")
    methodology = svc.require_ref(
        db.methodology_versions,
        payload.get("methodology_version_id"),
        "ERR_METHODOLOGY_VERSION_NOT_FOUND",
    )
    # priority 6 -- request well-formedness
    fmt = v.req_enum(payload, "format", calc.FORMAT_SET)
    window_start = v.req_datetime(payload, "window_start")
    window_end = v.req_datetime(payload, "window_end")
    measured = v.req_int(payload, "measured_impressions", minimum=0)
    measurable = v.req_int(payload, "measurable_impressions", minimum=0)
    in_view = v.req_int(payload, "in_view_impressions", minimum=0)
    avg_seconds = v.req_decimal(payload, "avg_in_view_seconds", minimum=0)
    avg_pixel = v.req_decimal(payload, "avg_in_view_pixel_pct", minimum=0, maximum=1)
    # endpoint-local referential guard, evaluated with the other referential checks
    if methodology["standard_family"] != "VIEWABILITY":
        fail("ERR_METHODOLOGY_FAMILY_MISMATCH")
    # priority 21 -- format agreement
    if fmt != campaign["format"]:
        fail("ERR_FORMAT_MISMATCH")
    # priority 22 -- page ownership agreement
    if page["publisher_id"] != publisher["id"]:
        fail("ERR_PAGE_PUBLISHER_MISMATCH")
    # priority 23 -- counter consistency
    if measured <= 0 or measurable > measured or in_view > measurable:
        fail("ERR_IMPRESSION_COUNTS_INCONSISTENT")
    # priority 30 -- batch window separation
    buffer = db.seconds(calc.BATCH_WINDOW_BUFFER_SECONDS)
    for existing in db.ordered(list(db.measurement_batches.values())):
        if (
            existing["campaign_id"] != campaign["id"]
            or existing["page_id"] != page["id"]
            or existing["format"] != fmt
        ):
            continue
        other_start = db.parse_dt(existing["window_start"])
        other_end = db.parse_dt(existing["window_end"])
        if other_start is None or other_end is None:
            continue
        if window_start <= other_end + buffer and other_start <= window_end + buffer:
            fail("ERR_BATCH_WINDOW_COLLISION")
    # priority 31 -- batch window sanity
    if window_start >= window_end or window_end > db.clock_now():
        fail("ERR_BATCH_WINDOW_IN_FUTURE")
    record = db.new_record(
        {
            "campaign_id": campaign["id"],
            "publisher_id": publisher["id"],
            "page_id": page["id"],
            "methodology_version_id": methodology["id"],
            "format": fmt,
            "window_start": db.fmt_dt(window_start),
            "window_end": db.fmt_dt(window_end),
            "measured_impressions": measured,
            "measurable_impressions": measurable,
            "in_view_impressions": in_view,
            "avg_in_view_seconds": calc.plain(avg_seconds),
            "avg_in_view_pixel_pct": calc.plain(avg_pixel),
            "qualified_in_view_impressions": 0,
            "non_viewable_impressions": 0,
            "unmeasurable_impressions": 0,
            "coverage_rate": None,
            "viewability_rate": None,
            "ivt_impressions": 0,
            "ivt_rate": 0.0,
            "sophistication_flag": False,
            "net_billable_impressions": 0,
            "assessed_tier": None,
            "suitability_breach_flag": False,
            "scoring_status": "INGESTED",
            "settlement_status": "UNBILLED",
            "scored_at": None,
        }
    )
    db.measurement_batches[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/measurement-batches/<batch_id>")
def read_batch(batch_id):
    caller = mw.require(*BATCH_READERS)
    record = svc.find(db.measurement_batches, batch_id)
    _own_batch(caller, record)
    if record is None:
        fail("ERR_MEASUREMENT_BATCH_NOT_FOUND")
    return response.object_response(record)


@bp.get("/measurement-batches")
def list_batches():
    caller = mw.require(*BATCH_READERS)
    predicates = build_filters(
        {
            "campaign_id": "campaign_id",
            "publisher_id": "publisher_id",
            "page_id": "page_id",
            "methodology_version_id": "methodology_version_id",
            "format": "format",
            "scoring_status": "scoring_status",
            "settlement_status": "settlement_status",
        }
    )
    if caller.is_publisher:
        predicates.append(lambda record: record["publisher_id"] == caller.user_id)
    if caller.is_advertiser:
        owned = set(
            campaign["id"]
            for campaign in db.campaigns.values()
            if campaign["advertiser_id"] == caller.user_id
        )
        predicates.append(lambda record: record["campaign_id"] in owned)
    return respond_list(filtered(db.measurement_batches, predicates))


# --------------------------------------------------------------------------- #
# scoring                                                                     #
# --------------------------------------------------------------------------- #
@bp.post("/measurement-batches/<batch_id>/score")
def score_batch(batch_id):
    mw.require(ROLE_MEASUREMENT_OPERATOR)
    record = svc.require_path(
        db.measurement_batches, batch_id, "ERR_MEASUREMENT_BATCH_NOT_FOUND"
    )
    mw.body()
    # priority 7 -- state reachability
    if record["scoring_status"] != "INGESTED":
        fail("ERR_INVALID_BATCH_STATE")
    methodology = svc.methodology_of(record)
    # priorities 12 and 13 -- lapse, accreditation, then effectivity at window_start
    svc.guard_methodology_live(methodology)
    svc.guard_methodology_effective_at(methodology, db.parse_dt(record["window_start"]))
    figures = calc.viewability_and_coverage(record, methodology)
    record["qualified_in_view_impressions"] = figures["qualified_in_view_impressions"]
    record["unmeasurable_impressions"] = figures["unmeasurable_impressions"]
    record["non_viewable_impressions"] = figures["non_viewable_impressions"]
    record["coverage_rate"] = calc.num4(figures["coverage_rate"])
    record["viewability_rate"] = calc.num4(figures["viewability_rate"])
    svc.recompute_batch_ivt(record)
    svc.assess_batch_tier(record)
    record["scored_at"] = db.now_iso()
    record["scoring_status"] = "SCORED"
    db.touch(record)
    return response.object_response(record)


# --------------------------------------------------------------------------- #
# branching certification                                                     #
# --------------------------------------------------------------------------- #
@bp.post("/measurement-batches/<batch_id>/certify")
def certify_batch(batch_id):
    mw.require(ROLE_MEASUREMENT_OPERATOR)
    record = svc.require_path(
        db.measurement_batches, batch_id, "ERR_MEASUREMENT_BATCH_NOT_FOUND"
    )
    mw.body()
    # priority 7 -- state reachability
    if record["scoring_status"] != "SCORED":
        fail("ERR_INVALID_BATCH_STATE")
    methodology = svc.methodology_of(record)
    svc.guard_methodology_live(methodology)
    certifiable = (
        calc.D(record["coverage_rate"]) >= calc.D(methodology["coverage_rate_floor"])
        and calc.D(record["ivt_rate"]) <= calc.D(methodology["ivt_rate_ceiling"])
        and not record["sophistication_flag"]
        and not record["suitability_breach_flag"]
    )
    publisher = db.publishers.get(record["publisher_id"])
    campaign = db.campaigns.get(record["campaign_id"])
    if certifiable:
        record["scoring_status"] = "CERTIFIED"
        db.touch(record)
        if publisher is not None:
            publisher["certified_batch_count"] = int(publisher["certified_batch_count"]) + 1
            db.touch(publisher)
        if campaign is not None:
            campaign["certified_measured_impressions"] = int(
                campaign["certified_measured_impressions"]
            ) + int(record["measured_impressions"])
            campaign["certified_measurable_impressions"] = int(
                campaign["certified_measurable_impressions"]
            ) + int(record["measurable_impressions"])
            svc.refresh_coverage_after_certify(campaign)
        return response.object_response(record)
    # quarantine branch -- the campaign's certified counters stay untouched
    record["scoring_status"] = "QUARANTINED"
    db.touch(record)
    if publisher is not None:
        publisher["quarantined_batch_count"] = int(publisher["quarantined_batch_count"]) + 1
        db.touch(publisher)
        svc.maybe_restrict_publisher(publisher)
    return response.object_response(record)


# --------------------------------------------------------------------------- #
# invalid-traffic findings (PRD section 3.8)                                          #
# --------------------------------------------------------------------------- #
def _own_finding(caller, finding):
    if finding is None:
        return
    _own_batch(caller, db.measurement_batches.get(finding["batch_id"]))


@bp.post("/ivt-findings")
def create_finding():
    mw.require(ROLE_MEASUREMENT_OPERATOR)
    payload = mw.body()
    batch = svc.require_ref(
        db.measurement_batches, payload.get("batch_id"), "ERR_MEASUREMENT_BATCH_NOT_FOUND"
    )
    ivt_class = v.req_enum(payload, "ivt_class", calc.IVT_CLASS_SET)
    flagged = v.req_int(payload, "flagged_impressions", minimum=1)
    confidence = v.req_decimal(payload, "confidence", minimum=0, maximum=1)
    detector_note = v.opt_string(payload, "detector_note")
    # priority 24 -- finding magnitude
    if flagged > int(batch["measured_impressions"]):
        fail("ERR_IVT_CONFIDENCE_TOO_LOW")
    record = db.new_record(
        {
            "batch_id": batch["id"],
            "ivt_class": ivt_class,
            "ivt_family": calc.IVT_CLASS_TO_FAMILY[ivt_class],
            "flagged_impressions": flagged,
            "confidence": calc.plain(confidence),
            "detector_note": detector_note,
            "status": "PROPOSED",
            "retract_reason": None,
        }
    )
    db.ivt_findings[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/ivt-findings/<finding_id>")
def read_finding(finding_id):
    caller = mw.require(*FINDING_READERS)
    record = svc.find(db.ivt_findings, finding_id)
    _own_finding(caller, record)
    if record is None:
        fail("ERR_IVT_FINDING_NOT_FOUND")
    return response.object_response(record)


@bp.get("/measurement-batches/<batch_id>/ivt-findings")
def list_batch_findings(batch_id):
    caller = mw.require(*FINDING_READERS)
    batch = svc.find(db.measurement_batches, batch_id)
    _own_batch(caller, batch)
    if batch is None:
        fail("ERR_MEASUREMENT_BATCH_NOT_FOUND")
    predicates = [lambda record: record["batch_id"] == batch["id"]]
    predicates.extend(build_filters({"status": "status", "ivt_family": "ivt_family"}))
    return respond_list(filtered(db.ivt_findings, predicates))


@bp.post("/ivt-findings/<finding_id>/confirm")
def confirm_finding(finding_id):
    mw.require(ROLE_MEASUREMENT_OPERATOR)
    record = svc.require_path(db.ivt_findings, finding_id, "ERR_IVT_FINDING_NOT_FOUND")
    mw.body()
    # priority 7 -- state reachability
    if record["status"] != "PROPOSED":
        fail("ERR_INVALID_FINDING_STATE")
    # priority 24 -- detector confidence
    if calc.D(record["confidence"]) < calc.IVT_CONFIRM_CONFIDENCE_FLOOR:
        fail("ERR_IVT_CONFIDENCE_TOO_LOW")
    batch = db.measurement_batches.get(record["batch_id"])
    if batch is None or batch["scoring_status"] not in BATCH_UNADJUDICATED:
        fail("ERR_BATCH_ALREADY_ADJUDICATED")
    record["status"] = "CONFIRMED"
    db.touch(record)
    svc.recompute_batch_ivt(batch)
    return response.object_response(record)


@bp.post("/ivt-findings/<finding_id>/retract")
def retract_finding(finding_id):
    mw.require(ROLE_MEASUREMENT_OPERATOR)
    record = svc.require_path(db.ivt_findings, finding_id, "ERR_IVT_FINDING_NOT_FOUND")
    payload = mw.body()
    retract_reason = v.req_string(payload, "retract_reason", 1, 500)
    # priority 7 -- state reachability
    if record["status"] not in ("PROPOSED", "CONFIRMED"):
        fail("ERR_INVALID_FINDING_STATE")
    batch = db.measurement_batches.get(record["batch_id"])
    if batch is None or batch["scoring_status"] not in BATCH_UNADJUDICATED:
        fail("ERR_BATCH_ALREADY_ADJUDICATED")
    was_confirmed = record["status"] == "CONFIRMED"
    record["status"] = "RETRACTED"
    record["retract_reason"] = retract_reason
    db.touch(record)
    if was_confirmed:
        # restores the figures to exactly what they were before the confirmation
        svc.recompute_batch_ivt(batch)
    return response.object_response(record)
