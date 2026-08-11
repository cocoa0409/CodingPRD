"""MeasureRun + PopulationEntry + Sample + ChartChase routes."""
import math

from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import require_roles, get_json_body, require_fields, require_str
from response import success_object, success_list, parse_pagination
from serializers import (run_view, entry_view, sample_view, chase_view,
                         engagement_view, gap_view, batch_view)
from services.core import (touch, find_run, find_season, find_spec, find_sample,
                           find_chase, find_entry, identify_population,
                           recompute_run_counters, compute_rates,
                           regenerate_gap_list, run_sample, selector_top_up,
                           sample_of_run, abstractions_of_sample)

bp = Blueprint("runs", __name__)

ANALYST = ["QualityAnalyst"]
ALL = ["QualityAdmin", "QualityAnalyst", "Abstractor", "OverReader",
       "ProviderRelations", "Auditor", "QualityDirector"]
GAP_LIST_ROLES = ["QualityAdmin", "QualityAnalyst", "ProviderRelations", "Auditor", "QualityDirector"]
AUDIT_LIST_ROLES = ["QualityAdmin", "QualityAnalyst", "Auditor", "QualityDirector"]


# ---------------------------------------------------------------- runs
@bp.post("/hedis/measure-runs")
def create_run():
    require_roles(ANALYST)
    body = get_json_body()
    require_fields(body, ["season_id", "spec_id"])
    season = find_season(body.get("season_id") if isinstance(body.get("season_id"), str) else "")
    spec = find_spec(body.get("spec_id") if isinstance(body.get("spec_id"), str) else "")
    rec = {
        "id": new_id(),
        "season_id": season["id"],
        "spec_id": spec["id"],
        "spec_version_label": spec["version_label"],
        "collection_method": spec["collection_method"],
        "reporting_status": "POPULATION_PENDING",
        "audit_status": "UNAUDITED",
        "denominator_count": 0,
        "exclusion_count": 0,
        "admin_numerator_count": 0,
        "sample_exclusion_count": 0,
        "sample_numerator_count": 0,
        "admin_rate": None,
        "hybrid_rate": None,
        "final_rate": None,
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.runs[rec["id"]] = rec
    return success_object(run_view(rec), 201)


@bp.get("/hedis/measure-runs/<runId>")
def get_run(runId):
    require_roles(ALL)
    r = find_run(runId)
    return success_object(run_view(r))


@bp.get("/hedis/measure-runs")
def list_runs():
    require_roles(ALL)
    items = list(db.runs.values())
    season_id = request.args.get("season_id")
    spec_id = request.args.get("spec_id")
    reporting_status = request.args.get("reporting_status")
    if season_id is not None:
        items = [r for r in items if r["season_id"] == season_id]
    if spec_id is not None:
        items = [r for r in items if r["spec_id"] == spec_id]
    if reporting_status is not None:
        items = [r for r in items if r["reporting_status"] == reporting_status]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([run_view(r) for r in page], limit, offset, total)


@bp.post("/hedis/measure-runs/<runId>/identify-population")
def identify_population_ep(runId):
    require_roles(ANALYST)
    run = find_run(runId)
    if run["reporting_status"] != "POPULATION_PENDING":
        raise errors.invalid_state("Run must be POPULATION_PENDING")
    spec = db.specs.get(run["spec_id"])
    if spec is None or spec["status"] != "ACTIVE":
        raise errors.invalid_state("Pinned spec must be ACTIVE")
    count = identify_population(run, spec)
    run["denominator_count"] = count
    run["reporting_status"] = "POPULATED"
    touch(run)
    return success_object(run_view(run))


@bp.post("/hedis/measure-runs/<runId>/compute-rate")
def compute_rate(runId):
    require_roles(ANALYST)
    body = get_json_body()
    require_fields(body, ["expected_measure_run_version"])
    run = find_run(runId)
    expected = body.get("expected_measure_run_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_measure_run_version must be an integer")
    # OCC (priority 5) — checked before state machine per §2.9 note
    if expected != run["version"]:
        raise errors.stale_version()
    if run["reporting_status"] != "POPULATED":
        raise errors.invalid_state("Run must be POPULATED to compute the rate")
    if run["collection_method"] == "HYBRID":
        sample = sample_of_run(run)
        if sample is None or sample["status"] != "FINALIZED":
            raise errors.invalid_state("HYBRID run's sample must be FINALIZED")
    if run["denominator_count"] <= 0:
        raise errors.ApiError(errors.ERR_DENOMINATOR_ZERO, 422,
                              "denominator_count must be greater than zero")

    recompute_run_counters(run)
    compute_rates(run)
    regenerate_gap_list(run)
    run["reporting_status"] = "RATE_COMPUTED"
    touch(run)
    return success_object(run_view(run))


@bp.post("/hedis/measure-runs/<runId>/submit")
def submit_run(runId):
    user_id, _ = require_roles(ANALYST)
    get_json_body()
    run = find_run(runId)
    # priority 6.1 — run state first
    if run["reporting_status"] != "RATE_COMPUTED":
        raise errors.ApiError(errors.ERR_RUN_NOT_SUBMITTABLE, 409,
                              "Run must be RATE_COMPUTED to submit")
    # priority 7 — season state
    season = db.seasons.get(run["season_id"])
    if season is None or season["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_SEASON_NOT_OPEN, 409,
                              "Run's season must be OPEN to submit")
    # priority 9 — deadline (submissions accepted at or before the deadline)
    if db.clock > season["submission_deadline"]:
        raise errors.ApiError(errors.ERR_SUBMISSION_DEADLINE_PASSED, 422,
                              "Submission deadline has passed")

    run["submitted_by_user_id"] = user_id
    run["reporting_status"] = "SUBMITTED"
    if run["collection_method"] == "HYBRID":
        sample = sample_of_run(run)
        if sample is not None and sample["status"] == "FINALIZED":
            sample["status"] = "LOCKED"
            touch(sample)
    touch(run)
    return success_object(run_view(run))


@bp.post("/hedis/measure-runs/<runId>/certify")
def certify_run(runId):
    user_id, _ = require_roles(["QualityDirector"])
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = body.get("decision")
    if decision not in ("CERTIFIED", "FAILED"):
        raise errors.invalid_request("decision must be CERTIFIED or FAILED")
    run = find_run(runId)
    if run["reporting_status"] != "SUBMITTED":
        raise errors.invalid_state("Run must be SUBMITTED to certify")
    # segregation of duties (priority 8.1)
    if user_id == run["submitted_by_user_id"]:
        raise errors.ApiError(errors.ERR_SOD_SUBMITTER_CERTIFY, 403,
                              "Certifier must differ from submitter")

    if decision == "CERTIFIED":
        if run["audit_status"] != "AUDIT_PASSED":
            raise errors.ApiError(errors.ERR_RUN_NOT_CERTIFIABLE, 422,
                                  "Run audit_status must be AUDIT_PASSED")
        # no OPEN CRITICAL finding linked via engagement
        for eng in db.engagements.values():
            if eng["measure_run_id"] != run["id"]:
                continue
            for f in db.findings.values():
                if (f["engagement_id"] == eng["id"] and f["severity"] == "CRITICAL"
                        and f["status"] == "OPEN"):
                    raise errors.ApiError(errors.ERR_RUN_NOT_CERTIFIABLE, 422,
                                          "OPEN CRITICAL finding blocks certification")
        run["reporting_status"] = "CERTIFIED"
        run["certified_by_user_id"] = user_id
        # cascade link 1: season certified_run_count
        season = db.seasons.get(run["season_id"])
        if season is not None:
            season["certified_run_count"] += 1
            # cascade link 2: season auto-close when all its runs certified
            total_runs = sum(1 for r in db.runs.values() if r["season_id"] == season["id"])
            if (season["certified_run_count"] == total_runs
                    and season["status"] == "OPEN"):
                season["status"] = "SUBMISSION_CLOSED"
            touch(season)
    else:
        run["reporting_status"] = "CERTIFICATION_FAILED"
    touch(run)
    return success_object(run_view(run))


@bp.post("/hedis/measure-runs/<runId>/reopen")
def reopen_run(runId):
    require_roles(ANALYST)
    get_json_body()
    run = find_run(runId)
    if run["reporting_status"] != "CERTIFICATION_FAILED":
        raise errors.invalid_state("Run must be CERTIFICATION_FAILED to reopen")
    run["reporting_status"] = "POPULATED"
    run["audit_status"] = "UNAUDITED"
    if run["collection_method"] == "HYBRID":
        sample = sample_of_run(run)
        if sample is not None and sample["status"] == "LOCKED":
            sample["status"] = "FINALIZED"
            touch(sample)
    touch(run)
    return success_object(run_view(run))


# ---------------------------------------------------------------- run sub-listings
@bp.get("/hedis/measure-runs/<id>/samples")
def list_run_samples(id):
    require_roles(ALL)
    find_run(id)
    items = [s for s in db.samples.values() if s["run_id"] == id]
    items.sort(key=lambda s: s["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([sample_view(s) for s in page], limit, offset, total)


@bp.get("/hedis/measure-runs/<id>/population-entries")
def list_run_entries(id):
    require_roles(ALL)
    find_run(id)
    items = [e for e in db.population_entries.values() if e["run_id"] == id]
    is_sampled = request.args.get("is_sampled")
    if is_sampled is not None:
        want = is_sampled.lower() == "true"
        items = [e for e in items if e["is_sampled"] == want]
    admin_compliant = request.args.get("admin_compliant")
    if admin_compliant is not None:
        want = admin_compliant.lower() == "true"
        items = [e for e in items if e["admin_compliant"] == want]
    items.sort(key=lambda e: e["member_ref"])  # business-key ordering
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([entry_view(e) for e in page], limit, offset, total)


@bp.get("/hedis/measure-runs/<id>/supplemental-batches")
def list_run_batches(id):
    require_roles(ALL)
    find_run(id)
    items = [b for b in db.batches.values() if b["run_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: b["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([batch_view(b) for b in page], limit, offset, total)


@bp.get("/hedis/measure-runs/<id>/gap-items")
def list_run_gaps(id):
    require_roles(GAP_LIST_ROLES)
    find_run(id)
    items = [g for g in db.gap_items.values() if g["run_id"] == id]
    provider_ref = request.args.get("provider_ref")
    status = request.args.get("status")
    member_ref = request.args.get("member_ref")
    if provider_ref is not None:
        items = [g for g in items if g["provider_ref"] == provider_ref]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    if member_ref is not None:
        items = [g for g in items if g["member_ref"] == member_ref]
    items.sort(key=lambda g: g["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([gap_view(g) for g in page], limit, offset, total)


@bp.get("/hedis/measure-runs/<id>/audit-engagements")
def list_run_engagements(id):
    require_roles(AUDIT_LIST_ROLES)
    find_run(id)
    items = [e for e in db.engagements.values() if e["measure_run_id"] == id]
    items.sort(key=lambda e: e["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([engagement_view(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------- population entries
@bp.post("/hedis/population-entries/<entryId>/exclude")
def exclude_entry(entryId):
    require_roles(ANALYST)
    body = get_json_body()
    require_fields(body, ["reason"])
    reason = body.get("reason")
    if not isinstance(reason, str):
        raise errors.invalid_request("reason must be a string")
    entry = find_entry(entryId)
    run = db.runs.get(entry["run_id"])
    if run is None:
        raise errors.not_found()
    if entry["is_excluded"]:
        raise errors.invalid_state("Entry is already excluded")
    # hybrid gate (priority 10.4): once the hybrid run's sample exists
    if run["collection_method"] == "HYBRID" and sample_of_run(run) is not None:
        raise errors.ApiError(errors.ERR_EXCLUSION_NOT_ALLOWED, 422,
                              "Exclusion forbidden once the hybrid run's sample exists")
    entry["is_excluded"] = True
    entry["exclusion_reason"] = reason
    touch(entry)
    run["exclusion_count"] += 1
    run["denominator_count"] -= 1
    touch(run)
    return success_object(entry_view(entry))


# ---------------------------------------------------------------- samples
@bp.post("/hedis/samples")
def create_sample():
    require_roles(ANALYST)
    body = get_json_body()
    require_fields(body, ["run_id"])
    run = find_run(body.get("run_id") if isinstance(body.get("run_id"), str) else "")
    # method gate (priority 10.3)
    if run["collection_method"] != "HYBRID":
        raise errors.ApiError(errors.ERR_METHOD_NOT_HYBRID, 422,
                              "Sample draw requires a HYBRID run")
    if sample_of_run(run) is not None:
        raise errors.ApiError(errors.ERR_SAMPLE_ALREADY_EXISTS, 409,
                              "Run already has a sample")
    spec = db.specs.get(run["spec_id"])
    pool = sorted(
        (e for e in db.population_entries.values()
         if e["run_id"] == run["id"] and not e["is_excluded"]),
        key=lambda e: e["member_ref"],
    )
    if len(pool) < spec["sample_size_floor"]:
        raise errors.ApiError(errors.ERR_SAMPLE_BELOW_FLOOR, 422,
                              "Eligible pool below the sample size floor")
    drawn_size = min(spec["sample_size_floor"], len(pool))
    draw_step = len(pool) / drawn_size

    sample = {
        "id": new_id(),
        "run_id": run["id"],
        "drawn_size": drawn_size,
        "draw_step": draw_step,
        "status": "DRAWN",
        "irr_state": "PENDING",
        "irr_ratio": None,
        "remediation_count": 0,
        "required_overread_fraction": 0.10,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.samples[sample["id"]] = sample

    member_by_ref = {m["member_ref"]: m for m in db.members.values()}
    for i in range(drawn_size):
        idx = math.floor(i * draw_step)
        entry = pool[idx]
        entry["is_sampled"] = True
        touch(entry)
        member = member_by_ref.get(entry["member_ref"])
        provider_ref = member["attributed_provider_ref"] if member else None
        chase = {
            "id": new_id(),
            "sample_id": sample["id"],
            "member_ref": entry["member_ref"],
            "provider_ref": provider_ref,
            "status": "REQUESTED",
            "chase_round": 1,
            "created_at": db.clock,
            "updated_at": db.clock,
            "version": 1,
        }
        db.chases[chase["id"]] = chase
    return success_object(sample_view(sample), 201)


@bp.get("/hedis/samples/<sampleId>")
def get_sample(sampleId):
    require_roles(ALL)
    s = find_sample(sampleId)
    return success_object(sample_view(s))


@bp.post("/hedis/samples/<sampleId>/finalize")
def finalize_sample(sampleId):
    require_roles(ANALYST)
    get_json_body()
    sample = find_sample(sampleId)
    if sample["status"] != "DRAWN":
        raise errors.invalid_state("Sample must be DRAWN to finalize")
    chases = [c for c in db.chases.values() if c["sample_id"] == sample["id"]]
    # gate 1: chases in flight
    if any(c["status"] in ("REQUESTED", "REJECTED_UNREADABLE") for c in chases):
        raise errors.ApiError(errors.ERR_CHASES_IN_FLIGHT, 422,
                              "Chases still in flight")
    # gate 2: every RECEIVED chase has a counted abstraction
    chase_abstractions = {}
    for a in abstractions_of_sample(sample["id"]):
        chase_abstractions.setdefault(a["chase_id"], []).append(a)
    for c in chases:
        if c["status"] == "RECEIVED":
            if not any(a["status"] in ("SUBMITTED", "CONFIRMED", "OVERREAD_PASSED")
                       for a in chase_abstractions.get(c["id"], [])):
                raise errors.ApiError(errors.ERR_UNABSTRACTED_CHARTS, 422,
                                      "A RECEIVED chase lacks a submitted abstraction")
    # gate 3: outstanding over-reads
    abstractions = abstractions_of_sample(sample["id"])
    for a in abstractions:
        if a["status"] == "SUBMITTED" and a["requires_overread"]:
            has_review = any(o["abstraction_id"] == a["id"]
                             and o["resubmission_count"] == a["resubmission_count"]
                             for o in db.over_reads.values())
            if not has_review:
                raise errors.ApiError(errors.ERR_OVERREADS_OUTSTANDING, 422,
                                      "A flagged abstraction lacks an over-read")
    # gate 4: IRR must be PASSED whenever any abstraction is flagged
    if any(a["requires_overread"] for a in abstractions):
        if sample["irr_state"] != "PASSED":
            raise errors.ApiError(errors.ERR_IRR_NOT_PASSED, 422,
                                  "IRR must be PASSED to finalize")

    # side effects: bulk auto-confirm non-flagged SUBMITTED abstractions
    for a in abstractions:
        if a["status"] == "SUBMITTED" and not a["requires_overread"]:
            a["status"] = "CONFIRMED"
            touch(a)
    sample["status"] = "FINALIZED"
    touch(sample)
    run = db.runs.get(sample["run_id"])
    if run is not None:
        recompute_run_counters(run)
    return success_object(sample_view(sample))


@bp.post("/hedis/samples/<sampleId>/evaluate-irr")
def evaluate_irr(sampleId):
    require_roles(ANALYST)
    get_json_body()
    sample = find_sample(sampleId)
    abstractions = abstractions_of_sample(sample["id"])

    # latest over-read per abstraction (latest submission round)
    latest = []
    for a in abstractions:
        reviews = [o for o in db.over_reads.values() if o["abstraction_id"] == a["id"]]
        if not reviews:
            continue
        reviews.sort(key=lambda o: (o["resubmission_count"], o["created_at"]))
        latest.append(reviews[-1])

    if latest:
        agreements = sum(1 for o in latest if o["outcome"] == "AGREE")
        from services.core import round4
        from decimal import Decimal
        ratio = round4(Decimal(agreements) / Decimal(len(latest)))
        sample["irr_ratio"] = ratio
        sample["irr_state"] = "PASSED" if ratio >= 0.95 else "FAILED"
    else:
        ratio = None

    # tier selection (top-down)
    if sample["remediation_count"] >= 2:
        sample["required_overread_fraction"] = 1.0
    elif ratio is None:
        pass  # fraction unchanged
    elif ratio >= 0.95:
        sample["required_overread_fraction"] = 0.10
    elif ratio >= 0.90:
        sample["required_overread_fraction"] = 0.25
    else:
        sample["required_overread_fraction"] = 1.0

    selector_top_up(sample)
    touch(sample)
    return success_object(sample_view(sample))


@bp.get("/hedis/samples/<id>/chart-chases")
def list_sample_chases(id):
    require_roles(ALL)
    find_sample(id)
    items = [c for c in db.chases.values() if c["sample_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["member_ref"])  # business-key ordering
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([chase_view(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------- chart chases
def _require_sample_drawn(chase):
    sample = db.samples.get(chase["sample_id"])
    if sample is None or sample["status"] != "DRAWN":
        raise errors.invalid_state("Chase's sample must be DRAWN")


@bp.get("/hedis/chart-chases/<chaseId>")
def get_chase(chaseId):
    require_roles(ALL)
    c = find_chase(chaseId)
    return success_object(chase_view(c))


@bp.post("/hedis/chart-chases/<chaseId>/receive")
def receive_chase(chaseId):
    require_roles(ANALYST)
    get_json_body()
    c = find_chase(chaseId)
    if c["status"] != "REQUESTED":
        raise errors.invalid_state("Chase must be REQUESTED to receive")
    _require_sample_drawn(c)
    c["status"] = "RECEIVED"
    touch(c)
    return success_object(chase_view(c))


@bp.post("/hedis/chart-chases/<chaseId>/reject-unreadable")
def reject_chase(chaseId):
    require_roles(ANALYST)
    get_json_body()
    c = find_chase(chaseId)
    if c["status"] != "RECEIVED":
        raise errors.invalid_state("Chase must be RECEIVED to reject")
    _require_sample_drawn(c)
    c["status"] = "REJECTED_UNREADABLE"
    touch(c)
    return success_object(chase_view(c))


@bp.post("/hedis/chart-chases/<chaseId>/rechase")
def rechase_chase(chaseId):
    require_roles(ANALYST)
    get_json_body()
    c = find_chase(chaseId)
    if c["status"] not in ("REJECTED_UNREADABLE", "WITHDRAWN"):
        raise errors.invalid_state("Chase must be REJECTED_UNREADABLE or WITHDRAWN to rechase")
    _require_sample_drawn(c)
    c["status"] = "REQUESTED"
    c["chase_round"] += 1
    touch(c)
    return success_object(chase_view(c))


@bp.post("/hedis/chart-chases/<chaseId>/withdraw")
def withdraw_chase(chaseId):
    require_roles(ANALYST)
    get_json_body()
    c = find_chase(chaseId)
    if c["status"] != "REQUESTED":
        raise errors.invalid_state("Chase must be REQUESTED to withdraw")
    _require_sample_drawn(c)
    c["status"] = "WITHDRAWN"
    touch(c)
    return success_object(chase_view(c))


@bp.post("/hedis/chart-chases/<chaseId>/mark-excluded")
def mark_excluded_chase(chaseId):
    require_roles(ANALYST)
    body = get_json_body()
    require_fields(body, ["reason"])
    if not isinstance(body.get("reason"), str):
        raise errors.invalid_request("reason must be a string")
    c = find_chase(chaseId)
    if c["status"] not in ("REQUESTED", "RECEIVED", "REJECTED_UNREADABLE"):
        raise errors.invalid_state("Chase cannot be excluded from its current state")
    _require_sample_drawn(c)
    if any(a["chase_id"] == c["id"] for a in db.abstractions.values()):
        raise errors.invalid_state("An abstraction already exists for this chase")
    c["status"] = "EXCLUDED_VALID"
    touch(c)
    sample = db.samples.get(c["sample_id"])
    if sample is not None:
        run = db.runs.get(sample["run_id"])
        if run is not None:
            run["sample_exclusion_count"] += 1
            touch(run)
    return success_object(chase_view(c))


@bp.get("/hedis/chart-chases/<id>/abstractions")
def list_chase_abstractions(id):
    require_roles(ALL)
    find_chase(id)
    from serializers import abstraction_view
    items = [a for a in db.abstractions.values() if a["chase_id"] == id]
    items.sort(key=lambda a: a["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([abstraction_view(a) for a in page], limit, offset, total)
