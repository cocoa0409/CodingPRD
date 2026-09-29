"""Methodology documents, probes, measurement runs and attestations.

PRD §3.2, §3.3 and §3.4.
"""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import lookup
import response
import serializers
import validators
from errors import fail
from middleware import (ALL_ROLES, COMPLIANCE_OFFICER, NETWORK_ENGINEER,
                        authorize)
from services import calculations as calc
from services import reconcile

bp = Blueprint("measurement", __name__)

METRIC_VARIANTS = ("PEAK_HOUR_MEDIAN", "ALL_HOUR_P20")
SNAPSHOT_FIELDS = ("version_label", "peak_hours_start_utc_hour",
                   "peak_hours_end_utc_hour", "min_samples_required",
                   "max_run_duration_days", "methodology_url")
COMPLAINT_TERMINAL_FOR_GAP = ("UPHELD", "DISMISSED", "WITHDRAWN")


# ---------------------------------------------------------------------------
# MethodologyDocument
# ---------------------------------------------------------------------------

@bp.route("/methodology-documents", methods=["POST"])
def create_methodology_document():
    authorize(NETWORK_ENGINEER)
    body = validators.json_body()

    doc_code = validators.get_str(body, "doc_code", 1, 32)
    version_label = validators.get_str(body, "version_label", 1, 16)
    url = validators.get_str(body, "methodology_url", 1, 300)
    start_hour = validators.get_int(body, "peak_hours_start_utc_hour",
                                    minimum=0, maximum=23)
    end_hour = validators.get_int(body, "peak_hours_end_utc_hour",
                                  minimum=1, maximum=24)
    min_samples = validators.get_int(body, "min_samples_required", minimum=1)
    max_duration = validators.get_int(body, "max_run_duration_days",
                                      minimum=1, maximum=30)
    if end_hour <= start_hour:
        validators.bad("Field 'peak_hours_end_utc_hour' must be greater than "
                       "'peak_hours_start_utc_hour'.")

    for existing in db.store.methodology_documents.values():
        if existing["doc_code"] == doc_code:
            validators.bad("Field 'doc_code' is already in use.")

    doc = db.new_record()
    doc.update({
        "doc_code": doc_code,
        "version_label": version_label,
        "methodology_url": url,
        "peak_hours_start_utc_hour": start_hour,
        "peak_hours_end_utc_hour": end_hour,
        "min_samples_required": min_samples,
        "max_run_duration_days": max_duration,
        "status": "DRAFT",
        "published_at": None,
    })
    db.store.methodology_documents[doc["id"]] = doc
    return response.success(serializers.methodology_document(doc), 201)


@bp.route("/methodology-documents/<doc_id>", methods=["GET"])
def read_methodology_document(doc_id):
    authorize(*ALL_ROLES)
    doc = lookup.methodology_document(doc_id)
    return response.success(serializers.methodology_document(doc), 200)


@bp.route("/methodology-documents/<doc_id>/publish", methods=["POST"])
def publish_methodology_document(doc_id):
    authorize(COMPLIANCE_OFFICER)
    doc = lookup.methodology_document(doc_id)
    if doc["status"] != "DRAFT":
        fail(errors.ERR_METHODOLOGY_ALREADY_PUBLISHED)
    if doc["peak_hours_end_utc_hour"] <= doc["peak_hours_start_utc_hour"]:
        validators.bad("The document's peak window is not well-formed.")
    doc["status"] = "PUBLISHED"
    doc["published_at"] = db.now_iso()
    db.touch(doc)
    return response.success(serializers.methodology_document(doc), 200)


# ---------------------------------------------------------------------------
# MeasurementProbe
# ---------------------------------------------------------------------------

@bp.route("/measurement-probes", methods=["POST"])
def create_measurement_probe():
    authorize(NETWORK_ENGINEER)
    body = validators.json_body()

    probe_code = validators.get_str(body, "probe_code", 1, 32)
    market_code = validators.get_str(body, "market_code", 1, 16)
    panel_size = validators.get_int(body, "panel_size", minimum=1)
    capacity = validators.get_int(body, "max_concurrent_windows", minimum=1)

    for existing in db.store.measurement_probes.values():
        if existing["probe_code"] == probe_code:
            validators.bad("Field 'probe_code' is already in use.")

    probe = db.new_record()
    probe.update({
        "probe_code": probe_code,
        "market_code": market_code,
        "panel_size": panel_size,
        "max_concurrent_windows": capacity,
    })
    db.store.measurement_probes[probe["id"]] = probe
    return response.success(serializers.measurement_probe(probe), 201)


@bp.route("/measurement-probes/<probe_id>", methods=["GET"])
def read_measurement_probe(probe_id):
    authorize(*ALL_ROLES)
    probe = lookup.measurement_probe(probe_id)
    return response.success(serializers.measurement_probe(probe), 200)


# ---------------------------------------------------------------------------
# TestRun
# ---------------------------------------------------------------------------

@bp.route("/test-runs", methods=["POST"])
def create_test_run():
    authorize(NETWORK_ENGINEER)
    body = validators.json_body()

    probe_ref = validators.get_id_ref(body, "probe_id")
    plan_ref = validators.get_id_ref(body, "plan_id")
    doc_ref = validators.get_id_ref(body, "methodology_doc_id")
    window_start_raw = validators.get_datetime(body, "window_start")
    window_end_raw = validators.get_datetime(body, "window_end")
    samples = validators.get_samples(body)

    window_start = db.parse_iso(window_start_raw)
    window_end = db.parse_iso(window_end_raw)
    if not window_end > window_start:
        validators.bad("Field 'window_end' must be after 'window_start'.")

    # Body foreign keys resolve in declaration order (PRD §2.6).
    probe = lookup.measurement_probe(probe_ref)
    plan = lookup.service_plan(plan_ref)
    doc = lookup.methodology_document(doc_ref)

    # Step 11 — temporal admissibility.
    if window_end > db.now():
        fail(errors.ERR_MEASUREMENT_WINDOW_FUTURE)

    # Step 13 — interval geometry.
    overlapping = 0
    for other in db.store.test_runs.values():
        if other["probe_id"] != probe["id"] or other["status"] != "INCLUDED":
            continue
        other_start = db.dt_of(other, "window_start")
        other_end = db.dt_of(other, "window_end")
        buffered_end = other_end + timedelta(
            minutes=calc.PROBE_COOLDOWN_MINUTES)
        if window_start <= buffered_end and other_start <= window_end:
            overlapping += 1
    if overlapping >= probe["max_concurrent_windows"]:
        fail(errors.ERR_PROBE_COOLDOWN_CONFLICT)

    if (window_end - window_start) > timedelta(
            days=doc["max_run_duration_days"]):
        fail(errors.ERR_RUN_DURATION_EXCEEDED)

    for sample in samples:
        observed = db.parse_iso(sample["observed_at"])
        if observed < window_start or observed > window_end:
            fail(errors.ERR_SAMPLE_OUTSIDE_WINDOW)

    # Step 15 — referential prerequisites.
    if doc["status"] != "PUBLISHED":
        fail(errors.ERR_METHODOLOGY_NOT_PUBLISHED)

    run = db.new_record()
    run.update({
        "probe_id": probe["id"],
        "plan_id": plan["id"],
        "methodology_doc_id": doc["id"],
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "samples": samples,
        "sample_count": len(samples),
        "status": "INCLUDED",
        "invalidated_at": None,
        "invalidation_reason": None,
    })
    db.store.test_runs[run["id"]] = run

    reconcile.recompute_evidence_sample_total(plan)
    db.touch(plan)
    return response.success(serializers.test_run(run), 201)


@bp.route("/test-runs/<run_id>", methods=["GET"])
def read_test_run(run_id):
    authorize(*ALL_ROLES)
    run = lookup.test_run(run_id)
    return response.success(serializers.test_run(run), 200)


@bp.route("/test-runs", methods=["GET"])
def list_test_runs():
    authorize(*ALL_ROLES)
    validators.pagination_params()
    filters = {
        "probe_id": request.args.get("probe_id"),
        "plan_id": request.args.get("plan_id"),
        "methodology_doc_id": request.args.get("methodology_doc_id"),
        "status": request.args.get("status"),
    }
    rows = []
    for run in db.store.test_runs.values():
        if all(value is None or run[field] == value
               for field, value in filters.items()):
            rows.append(run)
    items, meta = validators.paginate(db.ordered(rows), serializers.test_run)
    return response.success_list(items, meta, 200)


@bp.route("/test-runs/<run_id>/invalidate", methods=["POST"])
def invalidate_test_run(run_id):
    authorize(NETWORK_ENGINEER)
    body = validators.json_body()
    reason = validators.get_str(body, "reason", 1, None)

    run = lookup.test_run(run_id)
    if run["status"] != "INCLUDED":
        fail(errors.ERR_TEST_RUN_ALREADY_INVALIDATED)

    # Hop 1.
    run["status"] = "INVALIDATED"
    run["invalidated_at"] = db.now_iso()
    run["invalidation_reason"] = reason
    db.touch(run)

    plan = db.store.service_plans.get(run["plan_id"])
    if plan is not None:
        # Hop 2.
        total = reconcile.recompute_evidence_sample_total(plan)

        # Hop 3.
        revoked_ids = []
        for attestation in db.ordered(db.store.attestations.values()):
            if attestation["plan_id"] != plan["id"]:
                continue
            if attestation["status"] not in ("DRAFT", "CERTIFIED"):
                continue
            if attestation["methodology_snapshot"]["min_samples_required"] > total:
                attestation["status"] = "REVOKED"
                attestation["revoked_reason"] = "EVIDENCE_BELOW_MINIMUM"
                db.touch(attestation)
                revoked_ids.append(attestation["id"])

        # Hop 4.
        for label in db.ordered(db.store.label_versions.values()):
            if label["attestation_id"] not in revoked_ids:
                continue
            if label["publication_state"] != "PUBLISHED":
                continue
            label["substantiation_status"] = "UNSUBSTANTIATED"
            db.touch(label)
            # Non-chain consequence of hop 4.
            for complaint in db.ordered(db.store.complaints.values()):
                if complaint["disputed_label_version_id"] != label["id"]:
                    continue
                if complaint["state"] in COMPLAINT_TERMINAL_FOR_GAP:
                    continue
                if not complaint["evidence_gap"]:
                    complaint["evidence_gap"] = True
                    db.touch(complaint)

        # Hop 5.
        calc.recompute_plan_posture(plan)
        db.touch(plan)

    return response.success(serializers.test_run(run), 200)


# ---------------------------------------------------------------------------
# PerformanceAttestation
# ---------------------------------------------------------------------------

@bp.route("/performance-attestations", methods=["POST"])
def create_attestation():
    authorize(NETWORK_ENGINEER)
    body = validators.json_body()

    plan_ref = validators.get_id_ref(body, "plan_id")
    doc_ref = validators.get_id_ref(body, "methodology_doc_id")
    variant = validators.get_enum(body, "metric_variant", METRIC_VARIANTS)
    expected = validators.get_int(body, "expected_plan_version")

    plan = lookup.service_plan(plan_ref)
    doc = lookup.methodology_document(doc_ref)

    # Step 7 — optimistic concurrency.
    if expected != plan["version"]:
        fail(errors.ERR_STALE_PLAN_VERSION)

    snapshot = {field: doc[field] for field in SNAPSHOT_FIELDS}

    # Step 14 — evidence sufficiency, then step 15 — referential prerequisite.
    runs = calc.eligible_runs(plan["id"], doc["id"])
    metrics = calc.typical_speed_metrics(plan, runs, variant, snapshot)
    if metrics is None:
        fail(errors.ERR_NO_ELIGIBLE_TEST_RUNS)

    if doc["status"] != "PUBLISHED":
        fail(errors.ERR_METHODOLOGY_NOT_PUBLISHED)

    attestation = db.new_record()
    attestation.update({
        "plan_id": plan["id"],
        "methodology_doc_id": doc["id"],
        "metric_variant": variant,
        "included_run_ids": [run["id"] for run in runs],
        "status": "DRAFT",
        "certified_at": None,
        "revoked_reason": None,
        "methodology_snapshot": snapshot,
    })
    attestation.update(metrics)
    db.store.attestations[attestation["id"]] = attestation

    # A new attestation supersedes the plan's certified one.
    for other in db.ordered(db.store.attestations.values()):
        if other["id"] == attestation["id"]:
            continue
        if other["plan_id"] == plan["id"] and other["status"] == "CERTIFIED":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    db.touch(plan)
    return response.success(serializers.attestation(attestation), 201)


@bp.route("/performance-attestations/<attestation_id>/certify",
          methods=["POST"])
def certify_attestation(attestation_id):
    authorize(COMPLIANCE_OFFICER)
    attestation = lookup.attestation(attestation_id)

    if attestation["status"] != "DRAFT":
        fail(errors.ERR_ATTESTATION_INVALID_STATE)

    snapshot = attestation["methodology_snapshot"]
    if attestation["pooled_sample_count"] < snapshot["min_samples_required"]:
        fail(errors.ERR_INSUFFICIENT_SAMPLES)

    minimum = calc.SUBSTANTIATION_MIN_MARGIN
    if (calc.dec(attestation["download_margin_pct"]) < minimum
            or calc.dec(attestation["upload_margin_pct"]) < minimum):
        fail(errors.ERR_SUBSTANTIATION_MARGIN_NOT_MET)

    attestation["status"] = "CERTIFIED"
    attestation["certified_at"] = db.now_iso()
    db.touch(attestation)

    plan = db.store.service_plans.get(attestation["plan_id"])
    if plan is not None:
        published = calc.published_label(plan["id"])
        repaired = (published is not None
                    and published["substantiation_status"] == "UNSUBSTANTIATED")
        if repaired:
            published["attestation_id"] = attestation["id"]
            published["typical_download_mbps"] = \
                attestation["typical_download_mbps"]
            published["typical_upload_mbps"] = \
                attestation["typical_upload_mbps"]
            published["typical_latency_ms"] = attestation["typical_latency_ms"]
            published["methodology_url_snapshot"] = \
                attestation["methodology_snapshot"]["methodology_url"]
            published["substantiation_status"] = "SUBSTANTIATED"
            db.touch(published)
        calc.recompute_plan_posture(plan)
        if repaired:
            db.touch(plan)

    return response.success(serializers.attestation(attestation), 200)


@bp.route("/performance-attestations/<attestation_id>", methods=["GET"])
def read_attestation(attestation_id):
    authorize(*ALL_ROLES)
    attestation = lookup.attestation(attestation_id)
    return response.success(serializers.attestation(attestation), 200)


@bp.route("/performance-attestations", methods=["GET"])
def list_attestations():
    authorize(*ALL_ROLES)
    validators.pagination_params()
    filters = {
        "plan_id": request.args.get("plan_id"),
        "methodology_doc_id": request.args.get("methodology_doc_id"),
        "status": request.args.get("status"),
    }
    rows = []
    for attestation in db.store.attestations.values():
        if all(value is None or attestation[field] == value
               for field, value in filters.items()):
            rows.append(attestation)
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.attestation)
    return response.success_list(items, meta, 200)
