"""TestBench, BenchReservation, TestCampaign and LoadTest endpoints (PRD 3.4, 3.5)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import fail
from routes._common import paged
from store import db, mark_dirty, now

bp = Blueprint("lab", __name__)

CAMPAIGN_READERS = (
    "TestLabTechnician",
    "DesignEngineer",
    "DesignApprover",
    "ComplianceOfficer",
    "CertificationBody",
    "SafetyDirector",
)


# =========================================================================
# TestBench
# =========================================================================
@bp.post("/test-benches")
@authorize("TestLabTechnician")
def create_test_bench():
    data = validate.body()
    bench_code = validate.req_str(data, "bench_code")
    max_load_capacity_lb = validate.req_number(
        data, "max_load_capacity_lb", minimum=0, exclusive_min=True
    )
    cooldown_minutes = validate.req_int(data, "cooldown_minutes", minimum=0, maximum=480)

    for existing in db.test_benches.values():
        if existing["bench_code"] == bench_code:
            fail("ERR_DUPLICATE_KEY", "bench_code already exists: %s" % bench_code)

    bench = store.base_record()
    bench.update(
        {
            "bench_code": bench_code,
            "max_load_capacity_lb": max_load_capacity_lb,
            "cooldown_minutes": cooldown_minutes,
            "reserved_minutes_total": 0,
        }
    )
    db.test_benches[bench["id"]] = bench
    store.register_new(bench)
    return response.created(bench, serialize.test_bench)


@bp.get("/test-benches/<bench_id>")
@authorize("TestLabTechnician", "ComplianceOfficer", "SafetyDirector")
def get_test_bench(bench_id):
    bench = lookup.test_bench(bench_id)
    return response.obj(bench, serialize.test_bench)


# =========================================================================
# BenchReservation
# =========================================================================
@bp.post("/bench-reservations")
@authorize("TestLabTechnician")
def create_bench_reservation():
    data = validate.body()

    bench = None
    if validate.present(data, "test_bench_id"):
        bench = lookup.test_bench(data["test_bench_id"])
    campaign = None
    if validate.present(data, "test_campaign_id"):
        campaign = lookup.test_campaign(data["test_campaign_id"])

    validate.req_id(data, "test_bench_id")
    validate.req_id(data, "test_campaign_id")
    start_at = validate.req_instant(data, "start_at")
    end_at = validate.req_instant(data, "end_at")

    # step 8
    validate.check_window(start_at, end_at)

    # step 55 — half-open buffered occupancy
    cooldown = timedelta(minutes=bench["cooldown_minutes"])
    for existing in lookup.where(db.bench_reservations, test_bench_id=bench["id"]):
        if existing["status"] not in ("HELD", "CONSUMED"):
            continue
        if start_at < existing["end_at"] + cooldown and end_at > existing["start_at"]:
            fail("ERR_BENCH_WINDOW_CONFLICT", "the bench is occupied for that window")

    duration_minutes = int((end_at - start_at).total_seconds() // 60)
    reservation = store.base_record()
    reservation.update(
        {
            "test_bench_id": bench["id"],
            "test_campaign_id": campaign["id"],
            "start_at": start_at,
            "end_at": end_at,
            "duration_minutes": duration_minutes,
            "status": "HELD",
        }
    )
    db.bench_reservations[reservation["id"]] = reservation
    store.register_new(reservation)
    bench["reserved_minutes_total"] = bench["reserved_minutes_total"] + duration_minutes
    mark_dirty(bench)
    return response.created(reservation, serialize.bench_reservation)


@bp.get("/bench-reservations/<reservation_id>")
@authorize("TestLabTechnician", "ComplianceOfficer", "SafetyDirector")
def get_bench_reservation(reservation_id):
    reservation = lookup.bench_reservation(reservation_id)
    return response.obj(reservation, serialize.bench_reservation)


@bp.get("/bench-reservations")
@authorize("TestLabTechnician", "ComplianceOfficer", "SafetyDirector")
def list_bench_reservations():
    spec = {
        "test_bench_id": "test_bench_id",
        "test_campaign_id": "test_campaign_id",
        "status": "status",
    }
    return paged(lookup.rows(db.bench_reservations), spec, serialize.bench_reservation)


@bp.post("/bench-reservations/<reservation_id>/cancel")
@authorize("TestLabTechnician")
def cancel_bench_reservation(reservation_id):
    reservation = lookup.bench_reservation(reservation_id)

    if reservation["status"] != "HELD":
        fail("ERR_RESERVATION_NOT_HELD", "status must be HELD to cancel")

    reservation["status"] = "CANCELLED"
    mark_dirty(reservation)
    bench = db.test_benches.get(reservation["test_bench_id"])
    if bench is not None:
        bench["reserved_minutes_total"] = (
            bench["reserved_minutes_total"] - reservation["duration_minutes"]
        )
        mark_dirty(bench)
    return response.obj(reservation, serialize.bench_reservation)


# =========================================================================
# TestCampaign
# =========================================================================
def _select_prior_audit(listing_record_id):
    candidates = [
        campaign
        for campaign in db.test_campaigns.values()
        if campaign["listing_record_id"] == listing_record_id
        and campaign["purpose"] == "PERIODIC_AUDIT"
        and campaign["status"] in ("PASSED", "FAILED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row["sample_window_end"], row["created_at"]), reverse=True)
    return candidates[0]


@bp.post("/test-campaigns")
@authorize("TestLabTechnician", "ComplianceOfficer")
def create_test_campaign():
    data = validate.body()

    product = None
    if validate.present(data, "product_id"):
        product = lookup.product(data["product_id"])
    revision = None
    if validate.present(data, "design_revision_id"):
        revision = lookup.design_revision(data["design_revision_id"])
    record = None
    if validate.present(data, "listing_record_id"):
        record = lookup.listing_record(data["listing_record_id"])
    lot = None
    if validate.present(data, "sampled_lot_id"):
        lot = lookup.production_lot(data["sampled_lot_id"])

    validate.req_id(data, "product_id")
    validate.req_id(data, "design_revision_id")
    purpose = validate.req_enum(data, "purpose", calc.CAMPAIGN_PURPOSES)
    validate.opt_id(data, "listing_record_id")
    validate.opt_id(data, "sampled_lot_id")
    window_start = validate.opt_instant(data, "sample_window_start")
    window_end = validate.opt_instant(data, "sample_window_end")

    # step 8
    validate.check_window(window_start, window_end)

    # step 32
    if revision["product_id"] != product["id"]:
        fail("ERR_REVISION_PRODUCT_MISMATCH", "revision belongs to another product")

    # step 33
    if purpose == "PERIODIC_AUDIT":
        if record is not None and record["product_id"] != product["id"]:
            fail("ERR_AUDIT_SCOPE_MISMATCH", "listing record belongs to another product")
        if lot is not None and lot["product_id"] != product["id"]:
            fail("ERR_AUDIT_SCOPE_MISMATCH", "sampled lot belongs to another product")

    # step 34
    audit_fields = (record, lot, window_start, window_end)
    if purpose == "PERIODIC_AUDIT":
        if any(value is None for value in audit_fields):
            fail(
                "ERR_AUDIT_FIELDS_MISMATCH",
                "PERIODIC_AUDIT requires listing_record_id, sampled_lot_id and both window bounds",
            )
    else:
        if any(value is not None for value in audit_fields):
            fail(
                "ERR_AUDIT_FIELDS_MISMATCH",
                "the four audit fields must be null for this purpose",
            )

    audit_sample_size = None
    escalation_tier = None
    prior_failure_rate_pct = None
    if purpose == "PERIODIC_AUDIT":
        # step 56 — closed-interval overlap on the same listing record
        for existing in db.test_campaigns.values():
            if existing["listing_record_id"] != record["id"]:
                continue
            if existing["purpose"] != "PERIODIC_AUDIT":
                continue
            if existing["status"] not in ("PLANNED", "IN_PROGRESS", "PASSED", "FAILED"):
                continue
            if (
                window_start <= existing["sample_window_end"]
                and window_end >= existing["sample_window_start"]
            ):
                fail("ERR_AUDIT_WINDOW_OVERLAP", "an audit window already covers that interval")

        prior = _select_prior_audit(record["id"])
        prior_failure_rate_pct, escalation_tier, audit_sample_size = calc.audit_escalation(prior)

    campaign = store.base_record()
    campaign.update(
        {
            "product_id": product["id"],
            "design_revision_id": revision["id"],
            "purpose": purpose,
            "listing_record_id": record["id"] if record is not None else None,
            "sampled_lot_id": lot["id"] if lot is not None else None,
            "sample_window_start": window_start,
            "sample_window_end": window_end,
            "status": "PLANNED",
            "audit_sample_size": audit_sample_size,
            "escalation_tier": escalation_tier,
            "prior_failure_rate_pct": prior_failure_rate_pct,
            "load_test_count": 0,
            "failed_test_count": 0,
            "started_at": None,
            "concluded_at": None,
        }
    )
    db.test_campaigns[campaign["id"]] = campaign
    store.register_new(campaign)
    return response.created(campaign, serialize.test_campaign)


@bp.get("/test-campaigns/<campaign_id>")
@authorize(*CAMPAIGN_READERS)
def get_test_campaign(campaign_id):
    campaign = lookup.test_campaign(campaign_id)
    return response.obj(campaign, serialize.test_campaign)


@bp.get("/test-campaigns")
@authorize(*CAMPAIGN_READERS)
def list_test_campaigns():
    spec = {
        "product_id": "product_id",
        "design_revision_id": "design_revision_id",
        "listing_record_id": "listing_record_id",
        "sampled_lot_id": "sampled_lot_id",
        "purpose": "purpose",
        "status": "status",
    }
    return paged(lookup.rows(db.test_campaigns), spec, serialize.test_campaign)


@bp.post("/test-campaigns/<campaign_id>/start")
@authorize("TestLabTechnician")
def start_test_campaign(campaign_id):
    campaign = lookup.test_campaign(campaign_id)
    data = validate.body()

    reservation = None
    if validate.present(data, "bench_reservation_id"):
        reservation = lookup.bench_reservation(data["bench_reservation_id"])
    validate.req_id(data, "bench_reservation_id")

    if campaign["status"] != "PLANNED":
        fail("ERR_CAMPAIGN_STATE_INVALID", "status must be PLANNED to start")
    if reservation["test_campaign_id"] != campaign["id"] or reservation["status"] != "HELD":
        fail("ERR_RESERVATION_NOT_HELD", "the reservation must belong to this campaign and be HELD")

    product = db.products[campaign["product_id"]]
    bench = db.test_benches[reservation["test_bench_id"]]
    if bench["max_load_capacity_lb"] < product["required_test_load_lb"]:
        fail(
            "ERR_BENCH_CAPACITY_INSUFFICIENT",
            "bench capacity is below the model's required test load",
        )

    campaign["status"] = "IN_PROGRESS"
    campaign["started_at"] = now()
    mark_dirty(campaign)
    reservation["status"] = "CONSUMED"
    mark_dirty(reservation)
    return response.obj(campaign, serialize.test_campaign)


@bp.post("/test-campaigns/<campaign_id>/load-tests")
@authorize("TestLabTechnician")
def create_load_test(campaign_id):
    campaign = lookup.test_campaign(campaign_id)
    data = validate.body()
    test_code = validate.req_enum(data, "test_code", calc.TEST_CODES)
    applied_load_lb = validate.req_number(data, "applied_load_lb", minimum=0, exclusive_min=True)
    measured_deflection_in = validate.req_number(data, "measured_deflection_in", minimum=0)
    permanent_set_in = validate.req_number(data, "permanent_set_in", minimum=0)

    if campaign["status"] != "IN_PROGRESS":
        fail("ERR_CAMPAIGN_STATE_INVALID", "status must be IN_PROGRESS to record a load test")

    product = db.products[campaign["product_id"]]
    outcome, failure_reason_code = calc.load_test_verdict(
        product, applied_load_lb, measured_deflection_in, permanent_set_in
    )

    test = store.base_record(versioned=False)
    test.update(
        {
            "test_campaign_id": campaign["id"],
            "test_code": test_code,
            "applied_load_lb": applied_load_lb,
            "measured_deflection_in": measured_deflection_in,
            "permanent_set_in": permanent_set_in,
            "outcome": outcome,
            "failure_reason_code": failure_reason_code,
        }
    )
    db.load_tests[test["id"]] = test
    store.register_new(test)
    cascade.recompute_campaign_counters(campaign)
    return response.created(test, serialize.load_test)


@bp.get("/test-campaigns/<campaign_id>/load-tests")
@authorize(*CAMPAIGN_READERS)
def list_load_tests(campaign_id):
    campaign = lookup.test_campaign(campaign_id)
    spec = {"outcome": "outcome", "test_code": "test_code"}
    return paged(lookup.load_tests_of_campaign(campaign["id"]), spec, serialize.load_test)


def _required_test_codes(campaign):
    product = db.products[campaign["product_id"]]
    codes = list(calc.REQUIRED_TEST_CODES_BY_PRODUCT_TYPE[product["product_type"]])
    revision = db.design_revisions.get(campaign["design_revision_id"])
    if revision is not None and revision["joint_type"] == "RIVETED":
        if "RIVET_SHEAR" not in codes:
            codes.append("RIVET_SHEAR")
    return codes


@bp.post("/test-campaigns/<campaign_id>/conclude")
@authorize("TestLabTechnician")
def conclude_test_campaign(campaign_id):
    campaign = lookup.test_campaign(campaign_id)

    if campaign["status"] != "IN_PROGRESS":
        fail("ERR_CAMPAIGN_STATE_INVALID", "status must be IN_PROGRESS to conclude")

    if campaign["purpose"] != "PERIODIC_AUDIT":
        # step 45 — evidence coverage before a verdict of either polarity
        recorded = set(
            test["test_code"] for test in lookup.load_tests_of_campaign(campaign["id"])
        )
        for code in _required_test_codes(campaign):
            if code not in recorded:
                fail("ERR_REQUIRED_TESTS_MISSING", "missing load test for code %s" % code)
    else:
        # step 46
        if campaign["load_test_count"] < (campaign["audit_sample_size"] or 0):
            fail(
                "ERR_AUDIT_SAMPLE_SHORT",
                "load_test_count is below the audit sample size",
            )

    passed = campaign["failed_test_count"] == 0
    campaign["status"] = "PASSED" if passed else "FAILED"
    campaign["concluded_at"] = now()
    mark_dirty(campaign)

    if campaign["purpose"] == "PERIODIC_AUDIT":
        if passed:
            record = db.listing_records.get(campaign["listing_record_id"])
            if record is not None:
                body = db.listing_bodies.get(record["listing_body_id"])
                if body is not None:
                    record["audit_due_at"] = calc.add_days(now(), body["audit_interval_days"])
                    mark_dirty(record)
        else:
            cascade.audit_failure_cascade(campaign)

    return response.obj(campaign, serialize.test_campaign)
