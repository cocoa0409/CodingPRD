"""Routes: antibiograms, empiric guidelines, DOT metric snapshots, regulatory reports."""

import json
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import db
from errors import (
    err_antibiogram_empty,
    err_antibiogram_not_draft,
    err_antibiogram_not_published,
    err_antibiogram_window_overlap,
    err_duplicate_snapshot_period,
    err_first_line_below_threshold,
    err_guideline_not_draft,
    err_guideline_not_retirable,
    err_invalid_period,
    err_invalid_request,
    err_invalid_supersession,
    err_not_found,
    err_period_not_closed,
    err_report_already_submitted,
    err_report_not_draft,
    err_report_not_submitted,
    err_snapshot_not_final,
    err_snapshot_not_finalized,
    err_snapshot_not_open,
    err_snapshot_pinned_by_report,
    err_stale_version,
    err_cross_facility,
)
from middleware import ALL_ROLES, auth_context, require_role
from response import success_object
from services import core
from services.core import ADOPTION_MIN_PCT, BENCHMARK_FLOORS
from services.listing import list_response
from services.serializers import serialize
from util import (
    body_json,
    fnv1a_32_hex,
    month_label,
    new_id,
    parse_iso,
    require_enum,
    require_fields,
    require_int,
    require_string,
    valid_period_label,
)

bp = Blueprint("surveillance_reporting", __name__)

REPORT_TYPES = {"NHSN_AUR", "STATE_MANDATE"}
ACKS = {"ACCEPTED", "REJECTED"}


def get_antibiogram_or_404(aid):
    ab = db.antibiograms.get(aid)
    if ab is None:
        raise err_not_found("Antibiogram not found")
    return ab


def get_guideline_or_404(gid):
    gl = db.empiric_guidelines.get(gid)
    if gl is None:
        raise err_not_found("EmpiricGuideline not found")
    return gl


def get_snapshot_or_404(sid):
    snap = db.dot_snapshots.get(sid)
    if snap is None:
        raise err_not_found("DOTMetricSnapshot not found")
    return snap


def get_report_or_404(rid):
    rep = db.regulatory_reports.get(rid)
    if rep is None:
        raise err_not_found("RegulatoryReport not found")
    return rep


# --- Antibiograms ------------------------------------------------------------------


def _compute_antibiogram_rows(antibiogram, hospital):
    """Compute AntibiogramRow children per antibiogram_susceptibility_rate:
    round-per-row then aggregate (pinned order)."""
    start = parse_iso(antibiogram["period_start"])
    end = parse_iso(antibiogram["period_end"])
    # (organism, antimicrobial_id) -> [isolate_count, susceptible_count]
    buckets = {}
    for culture in db.culture_reports.values():
        if culture.get("_hospital_id") != hospital["id"]:
            continue
        if culture["status"] not in ("FINAL", "AMENDED"):
            continue
        if not culture["is_first_isolate"]:
            continue
        collected = parse_iso(culture["collected_at"])
        if not (start <= collected < end):
            continue
        per_drug = {}
        for row in db.susceptibility_results.values():
            if row["culture_report_id"] != culture["id"]:
                continue
            entry = per_drug.setdefault(row["antimicrobial_id"], False)
            if row["interpretation"] == "S":
                per_drug[row["antimicrobial_id"]] = True
            else:
                per_drug[row["antimicrobial_id"]] = entry
        for drug_id, susceptible in per_drug.items():
            key = (culture["organism"], drug_id)
            bucket = buckets.setdefault(key, [0, 0])
            bucket[0] += 1
            if susceptible:
                bucket[1] += 1
    row_ids = []
    for (organism, drug_id), (isolate_count, susceptible_count) in sorted(
        buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])
    ):
        pct = core.round2(Decimal(100 * susceptible_count) / Decimal(isolate_count))
        row = {
            "id": new_id(),
            "antibiogram_id": antibiogram["id"],
            "organism": organism,
            "antimicrobial_id": drug_id,
            "isolate_count": isolate_count,
            "susceptible_count": susceptible_count,
            "pct_susceptible": pct,
            "is_reportable": isolate_count >= hospital["antibiogram_min_isolates"],
            "_hospital_id": hospital["id"],
        }
        core.stamp_new(row)
        db.antibiogram_rows[row["id"]] = row
        row_ids.append(row["id"])
    antibiogram["_row_ids"] = row_ids
    antibiogram["row_count"] = sum(
        1 for rid in row_ids if db.antibiogram_rows[rid]["is_reportable"]
    )


@bp.route("/stewardship/antibiograms", methods=["POST"])
def create_antibiogram():
    _, role = auth_context()
    require_role(role, {"Microbiologist"})
    payload = body_json()
    require_fields(payload, ["hospital_id", "period_start", "period_end"])
    hospital = db.hospitals.get(payload["hospital_id"])
    if hospital is None:
        raise err_not_found("Hospital not found")
    start = parse_iso(payload["period_start"], "period_start")
    end = parse_iso(payload["period_end"], "period_end")
    if end <= start:
        raise err_invalid_period()
    for other in db.antibiograms.values():
        if other["hospital_id"] != hospital["id"]:
            continue
        o_start = parse_iso(other["period_start"])
        o_end = parse_iso(other["period_end"])
        # Half-open windows: touching endpoints allowed.
        if start < o_end and o_start < end:
            raise err_antibiogram_window_overlap()
    antibiogram = {
        "id": new_id(),
        "hospital_id": hospital["id"],
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
        "generated_at": core.clock_iso(hospital),
        "row_count": 0,
        "status": "DRAFT",
    }
    core.stamp_new(antibiogram)
    db.antibiograms[antibiogram["id"]] = antibiogram
    _compute_antibiogram_rows(antibiogram, hospital)
    return success_object(serialize(antibiogram), status=201)


@bp.route("/stewardship/antibiograms/<aid>", methods=["GET"])
def get_antibiogram(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_antibiogram_or_404(aid)))


@bp.route("/stewardship/antibiograms", methods=["GET"])
def list_antibiograms():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.antibiograms.values(), ["hospital_id", "status"])


@bp.route("/stewardship/antibiograms/<aid>/rows", methods=["GET"])
def list_antibiogram_rows(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_antibiogram_or_404(aid)
    rows = [r for r in db.antibiogram_rows.values() if r["antibiogram_id"] == aid]
    return list_response(rows, [])


@bp.route("/stewardship/antibiogram-rows", methods=["GET"])
def list_all_antibiogram_rows():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.antibiogram_rows.values(), ["antibiogram_id", "antimicrobial_id", "organism"]
    )


@bp.route("/stewardship/antibiogram-rows/<rid>", methods=["GET"])
def get_antibiogram_row(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    row = db.antibiogram_rows.get(rid)
    if row is None:
        raise err_not_found("AntibiogramRow not found")
    return success_object(serialize(row))


@bp.route("/stewardship/antibiograms/<aid>/publish", methods=["POST"])
def publish_antibiogram(aid):
    _, role = auth_context()
    require_role(role, {"Microbiologist", "StewardshipDirector"})
    antibiogram = get_antibiogram_or_404(aid)
    if antibiogram["status"] != "DRAFT":
        raise err_antibiogram_not_draft()
    if antibiogram["row_count"] <= 0:
        raise err_antibiogram_empty()
    payload = body_json()
    if "expected_hospital_version" not in payload or payload["expected_hospital_version"] is None:
        raise err_invalid_request("expected_hospital_version is required")
    hospital = db.hospitals.get(antibiogram["hospital_id"])
    expected = payload["expected_hospital_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_hospital_version must be an integer")
    if expected != hospital["version"]:
        raise err_stale_version()
    antibiogram["status"] = "PUBLISHED"
    core.touch(antibiogram)
    for other in db.antibiograms.values():
        if (
            other["id"] != antibiogram["id"]
            and other["hospital_id"] == hospital["id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            core.touch(other)
    core.touch(hospital)  # publication increments Hospital.version by 1
    core.reevaluate_guideline_staleness(hospital, antibiogram)
    return success_object(serialize(antibiogram))


# --- Empiric guidelines -------------------------------------------------------------


@bp.route("/stewardship/empiric-guidelines", methods=["POST"])
def create_guideline():
    _, role = auth_context()
    require_role(role, {"StewardshipDirector", "IDPharmacist"})
    payload = body_json()
    require_fields(
        payload,
        ["hospital_id", "syndrome", "first_line_antimicrobial_id", "source_antibiogram_id"],
    )
    hospital = db.hospitals.get(payload["hospital_id"])
    if hospital is None:
        raise err_not_found("Hospital not found")
    drug = db.antimicrobials.get(payload["first_line_antimicrobial_id"])
    if drug is None:
        raise err_not_found("Antimicrobial not found")
    antibiogram = db.antibiograms.get(payload["source_antibiogram_id"])
    if antibiogram is None:
        raise err_not_found("Antibiogram not found")
    if antibiogram["hospital_id"] != hospital["id"]:
        raise err_cross_facility("Source antibiogram belongs to a different hospital")
    supersedes_id = payload.get("supersedes_guideline_id")
    if supersedes_id is not None:
        prior = db.empiric_guidelines.get(supersedes_id)
        if prior is None:
            raise err_invalid_supersession("supersedes_guideline_id does not resolve")
        if (
            prior["hospital_id"] != hospital["id"]
            or prior["syndrome"] != payload["syndrome"]
            or prior["status"] not in ("ADOPTED", "STALE")
        ):
            raise err_invalid_supersession()
    guideline = {
        "id": new_id(),
        "hospital_id": hospital["id"],
        "syndrome": require_string(payload, "syndrome"),
        "first_line_antimicrobial_id": drug["id"],
        "source_antibiogram_id": antibiogram["id"],
        "supersedes_guideline_id": supersedes_id,
        "pct_susceptible_at_adoption": None,
        "status": "DRAFT",
    }
    core.stamp_new(guideline)
    db.empiric_guidelines[guideline["id"]] = guideline
    return success_object(serialize(guideline), status=201)


@bp.route("/stewardship/empiric-guidelines/<gid>", methods=["GET"])
def get_guideline(gid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_guideline_or_404(gid)))


@bp.route("/stewardship/empiric-guidelines", methods=["GET"])
def list_guidelines():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.empiric_guidelines.values(),
        [
            "hospital_id",
            "syndrome",
            "status",
            "first_line_antimicrobial_id",
            "source_antibiogram_id",
            "supersedes_guideline_id",
        ],
    )


@bp.route("/stewardship/empiric-guidelines/<gid>/adopt", methods=["POST"])
def adopt_guideline(gid):
    _, role = auth_context()
    require_role(role, {"StewardshipDirector"})
    guideline = get_guideline_or_404(gid)
    payload = body_json()
    # OCC first for adoption (PRD 3.7 narration order).
    if "expected_hospital_version" not in payload or payload["expected_hospital_version"] is None:
        raise err_invalid_request("expected_hospital_version is required")
    expected = payload["expected_hospital_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_hospital_version must be an integer")
    hospital = db.hospitals.get(guideline["hospital_id"])
    if expected != hospital["version"]:
        raise err_stale_version()
    if guideline["status"] != "DRAFT":
        raise err_guideline_not_draft()
    antibiogram = db.antibiograms.get(guideline["source_antibiogram_id"])
    if (
        antibiogram is None
        or antibiogram["status"] != "PUBLISHED"
        or antibiogram["hospital_id"] != hospital["id"]
    ):
        raise err_antibiogram_not_published()
    row = core.guideline_row_for(
        antibiogram["id"], guideline["first_line_antimicrobial_id"], guideline["syndrome"]
    )
    if row is None or not row["is_reportable"]:
        raise err_first_line_below_threshold()
    pct = Decimal(str(row["pct_susceptible"]))
    if pct < ADOPTION_MIN_PCT:
        raise err_first_line_below_threshold()
    guideline["status"] = "ADOPTED"
    guideline["pct_susceptible_at_adoption"] = row["pct_susceptible"]
    core.touch(guideline)
    for other in db.empiric_guidelines.values():
        if (
            other["id"] != guideline["id"]
            and other["hospital_id"] == hospital["id"]
            and other["syndrome"] == guideline["syndrome"]
            and other["status"] == "ADOPTED"
        ):
            other["status"] = "RETIRED"
            core.touch(other)
    core.touch(hospital)  # adoption increments Hospital.version by 1
    return success_object(serialize(guideline))


@bp.route("/stewardship/empiric-guidelines/<gid>/retire", methods=["POST"])
def retire_guideline(gid):
    _, role = auth_context()
    require_role(role, {"StewardshipDirector"})
    guideline = get_guideline_or_404(gid)
    if guideline["status"] not in ("DRAFT", "STALE"):
        raise err_guideline_not_retirable()
    guideline["status"] = "RETIRED"
    core.touch(guideline)
    return success_object(serialize(guideline))


# --- DOT metric snapshots --------------------------------------------------------------


def _compute_snapshot_metrics(snapshot):
    """Recompute DOT totals, per-1000 rates, and benchmark percentile."""
    hospital_id = snapshot["hospital_id"]
    label = snapshot["period_label"]
    patient_days = snapshot["patient_days"]
    total_cal = 0
    total_dose = Decimal("0")
    for order in db.antibiotic_orders.values():
        if order.get("_hospital_id") != hospital_id:
            continue
        if order["therapy_status"] == "AWAITING_APPROVAL":
            continue
        if not core.order_intersects_month(order, label):
            continue
        cal, dose = core.order_dot_slice_in_month(order, label)
        total_cal += cal
        total_dose += dose
    total_dose = core.round2(total_dose)
    per1000_cal = core.round2(Decimal(1000 * total_cal) / Decimal(patient_days))
    per1000_dose = core.round2(Decimal(1000) * total_dose / Decimal(patient_days))
    percentile = 10
    for floor, pct in BENCHMARK_FLOORS:
        if per1000_cal >= Decimal(floor):
            percentile = pct
            break
    snapshot["total_dot_calendar"] = total_cal
    snapshot["total_dot_dose"] = total_dose
    snapshot["dot_per_1000_pd_calendar"] = per1000_cal
    snapshot["dot_per_1000_pd_dose"] = per1000_dose
    snapshot["benchmark_percentile"] = percentile


def _snapshot_view(snapshot):
    """Serialize; OPEN snapshots are live projections (recomputed on read),
    FINALIZED snapshots return their frozen values."""
    if snapshot["status"] == "OPEN":
        view = dict(snapshot)
        _compute_snapshot_metrics(view)
        return serialize(view)
    return serialize(snapshot)


@bp.route("/stewardship/dot-snapshots", methods=["POST"])
def create_snapshot():
    _, role = auth_context()
    require_role(role, {"InfectionPreventionist"})
    payload = body_json()
    require_fields(payload, ["hospital_id", "period_label", "patient_days"])
    hospital = db.hospitals.get(payload["hospital_id"])
    if hospital is None:
        raise err_not_found("Hospital not found")
    if not valid_period_label(payload["period_label"]):
        raise err_invalid_request("period_label must be a calendar month label YYYY-MM")
    patient_days = require_int(payload, "patient_days", minimum=1)
    for other in db.dot_snapshots.values():
        if (
            other["hospital_id"] == hospital["id"]
            and other["period_label"] == payload["period_label"]
        ):
            raise err_duplicate_snapshot_period()
    snapshot = {
        "id": new_id(),
        "hospital_id": hospital["id"],
        "period_label": payload["period_label"],
        "patient_days": patient_days,
        "total_dot_calendar": 0,
        "total_dot_dose": Decimal("0.00"),
        "dot_per_1000_pd_calendar": Decimal("0.00"),
        "dot_per_1000_pd_dose": Decimal("0.00"),
        "benchmark_percentile": 10,
        "status": "OPEN",
    }
    core.stamp_new(snapshot)
    db.dot_snapshots[snapshot["id"]] = snapshot
    _compute_snapshot_metrics(snapshot)
    return success_object(serialize(snapshot), status=201)


@bp.route("/stewardship/dot-snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(_snapshot_view(get_snapshot_or_404(sid)))


@bp.route("/stewardship/dot-snapshots", methods=["GET"])
def list_snapshots():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.dot_snapshots.values(), ["hospital_id", "period_label", "status"])


@bp.route("/stewardship/dot-snapshots/<sid>/finalize", methods=["POST"])
def finalize_snapshot(sid):
    _, role = auth_context()
    require_role(role, {"InfectionPreventionist", "StewardshipDirector"})
    snapshot = get_snapshot_or_404(sid)
    if snapshot["status"] != "OPEN":
        raise err_snapshot_not_open()
    hospital = db.hospitals.get(snapshot["hospital_id"])
    clock_month = month_label(core.hospital_clock(hospital))
    if not snapshot["period_label"] < clock_month:
        raise err_period_not_closed()
    _compute_snapshot_metrics(snapshot)
    snapshot["status"] = "FINALIZED"
    core.touch(snapshot)
    return success_object(serialize(snapshot))


@bp.route("/stewardship/dot-snapshots/<sid>/reopen", methods=["POST"])
def reopen_snapshot(sid):
    _, role = auth_context()
    require_role(role, {"StewardshipDirector"})
    snapshot = get_snapshot_or_404(sid)
    if snapshot["status"] != "FINALIZED":
        raise err_snapshot_not_finalized()
    for rep in db.regulatory_reports.values():
        if rep["dot_snapshot_id"] == snapshot["id"] and rep["status"] in ("SUBMITTED", "ACCEPTED"):
            raise err_snapshot_pinned_by_report()
    snapshot["status"] = "OPEN"
    core.touch(snapshot)
    return success_object(serialize(snapshot))


# --- Regulatory reports ------------------------------------------------------------------


def _fmt2(value) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fmt_total_dose(value) -> str:
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d == d.to_integral_value():
        return str(int(d))
    return str(d)


def assemble_payload(report, snapshot, hospital):
    """Canonical JSON (keys sorted, no whitespace); per-thousand values with
    exactly 2 decimals; totals as integers (PRD 3.8)."""
    parts = [
        '"benchmark_percentile":' + str(int(snapshot["benchmark_percentile"])),
        '"dot_per_1000_pd_calendar":' + _fmt2(snapshot["dot_per_1000_pd_calendar"]),
        '"dot_per_1000_pd_dose":' + _fmt2(snapshot["dot_per_1000_pd_dose"]),
        '"nhsn_facility_id":' + json.dumps(hospital["nhsn_facility_id"]),
        '"patient_days":' + str(int(snapshot["patient_days"])),
        '"period_label":' + json.dumps(report["period_label"]),
        '"report_type":' + json.dumps(report["report_type"]),
        '"total_dot_calendar":' + str(int(snapshot["total_dot_calendar"])),
        '"total_dot_dose":' + _fmt_total_dose(snapshot["total_dot_dose"]),
    ]
    return "{" + ",".join(parts) + "}"


@bp.route("/stewardship/regulatory-reports", methods=["POST"])
def create_report():
    _, role = auth_context()
    require_role(role, {"InfectionPreventionist"})
    payload = body_json()
    require_fields(payload, ["hospital_id", "report_type", "period_label", "dot_snapshot_id"])
    hospital = db.hospitals.get(payload["hospital_id"])
    if hospital is None:
        raise err_not_found("Hospital not found")
    report_type = require_enum(payload, "report_type", REPORT_TYPES)
    if not valid_period_label(payload["period_label"]):
        raise err_invalid_request("period_label must be a calendar month label YYYY-MM")
    snapshot = db.dot_snapshots.get(payload["dot_snapshot_id"])
    if snapshot is None:
        raise err_not_found("DOTMetricSnapshot not found")
    if (
        snapshot["status"] != "FINALIZED"
        or snapshot["hospital_id"] != hospital["id"]
        or snapshot["period_label"] != payload["period_label"]
    ):
        raise err_snapshot_not_final()
    report = {
        "id": new_id(),
        "hospital_id": hospital["id"],
        "report_type": report_type,
        "period_label": payload["period_label"],
        "dot_snapshot_id": snapshot["id"],
        "payload_json": None,
        "checksum": None,
        "submitted_at": None,
        "status": "DRAFT",
    }
    core.stamp_new(report)
    db.regulatory_reports[report["id"]] = report
    return success_object(serialize(report), status=201)


@bp.route("/stewardship/regulatory-reports/<rid>", methods=["GET"])
def get_report(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_report_or_404(rid)))


@bp.route("/stewardship/regulatory-reports", methods=["GET"])
def list_reports():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.regulatory_reports.values(), ["hospital_id", "report_type", "dot_snapshot_id", "status"]
    )


@bp.route("/stewardship/regulatory-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    _, role = auth_context()
    require_role(role, {"InfectionPreventionist"})
    report = get_report_or_404(rid)
    if report["status"] != "DRAFT":
        raise err_report_not_draft()
    snapshot = db.dot_snapshots.get(report["dot_snapshot_id"])
    if (
        snapshot is None
        or snapshot["status"] != "FINALIZED"
        or snapshot["hospital_id"] != report["hospital_id"]
        or snapshot["period_label"] != report["period_label"]
    ):
        raise err_snapshot_not_final()
    for other in db.regulatory_reports.values():
        if (
            other["id"] != report["id"]
            and other["hospital_id"] == report["hospital_id"]
            and other["report_type"] == report["report_type"]
            and other["period_label"] == report["period_label"]
            and other["status"] in ("SUBMITTED", "ACCEPTED")
        ):
            raise err_report_already_submitted()
    hospital = db.hospitals.get(report["hospital_id"])
    payload_json = assemble_payload(report, snapshot, hospital)
    report["payload_json"] = payload_json
    report["checksum"] = fnv1a_32_hex(payload_json)
    report["submitted_at"] = core.clock_iso(hospital)
    report["status"] = "SUBMITTED"
    core.touch(report)
    return success_object(serialize(report))


@bp.route("/stewardship/regulatory-reports/<rid>/acknowledge", methods=["POST"])
def acknowledge_report(rid):
    _, role = auth_context()
    require_role(role, {"StewardshipDirector"})
    report = get_report_or_404(rid)
    payload = body_json()
    require_fields(payload, ["ack"])
    ack = payload["ack"]
    if ack not in ACKS:
        raise err_invalid_request("ack must be ACCEPTED or REJECTED")
    if report["status"] != "SUBMITTED":
        raise err_report_not_submitted()
    report["status"] = ack
    core.touch(report)
    return success_object(serialize(report))
