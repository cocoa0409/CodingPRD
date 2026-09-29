"""Certificates, appeals, appeal votes and vessel watches."""

from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
import validation
from auth import (
    ANY_ROLE,
    APPLICANT_USER,
    AUDITOR,
    LICENSED_INSPECTOR,
    SERVICE_ADMIN,
    SUPERVISING_INSPECTOR,
    acting_applicant_id,
    assert_applicant_scope,
    endpoint,
)
from envelope import apply_filters, created, listing, ok
from errors import ApiError
from routes_ops import scope_rows, scope_via_request
from store import db, new_row, ordered, serialize, touch

bp = Blueprint("final", __name__)

PREFIX = "/grain-inspection"

INSPECTOR_ROLES = (LICENSED_INSPECTOR, SUPERVISING_INSPECTOR)
CERTIFICATE_TYPES = ("GRADE", "WEIGHT", "COMBINED", "EXPORT_CARGO", "APPEAL_GRADE")
APPEAL_TYPES = ("REINSPECTION", "APPEAL", "BOARD_APPEAL")
VOTES = ("UPHOLD", "REVISE", "ABSTAIN")

GRADE_CONTENT = ("GRADE", "COMBINED", "EXPORT_CARGO", "APPEAL_GRADE")
WEIGHT_CONTENT = ("WEIGHT", "COMBINED", "EXPORT_CARGO")
TRAVEL_BUFFER = timedelta(minutes=45)
BOARD_APPEAL_WINDOW = timedelta(days=20)
LATE_CERTIFICATE_CUTOFF = timedelta(hours=calc.LATE_CERTIFICATE_THRESHOLD_HOURS)


# ==========================================================================
# certificates
# ==========================================================================

@bp.post(PREFIX + "/certificates")
@endpoint(INSPECTOR_ROLES)
def issue_certificate():
    body = validation.parse(
        {
            "inspection_request_id": {"required": True},
            "issuing_inspector_id": {"required": True},
            "certificate_type": {"type": "enum", "values": CERTIFICATE_TYPES, "required": True},
        }
    )
    request_row = svc.request(body["inspection_request_id"])
    inspector = svc.inspector(body["issuing_inspector_id"])
    area = svc.area(request_row["service_area_id"])
    applicant = svc.applicant(request_row["applicant_id"])
    cert_type = body["certificate_type"]

    svc.assert_same_area(inspector, request_row)
    if cert_type == "EXPORT_CARGO":
        svc.assert_service_requested(request_row, "EXPORT_SUPERVISION")

    svc.assert_area_active(area)
    svc.assert_licence(inspector, svc.LINE_LICENCE_STATES)

    same_type = [
        c
        for c in db.certificates.values()
        if c["inspection_request_id"] == request_row["id"] and c["certificate_type"] == cert_type
    ]
    if any(c["status"] == "UNDER_APPEAL" for c in same_type):
        raise ApiError("ERR_CERTIFICATE_UNDER_APPEAL")

    weighing_record = None
    if cert_type in WEIGHT_CONTENT:
        weighing_record = svc.operative_weighing_record(request_row["id"])
        needs_supervision = area["supervision_required"] or cert_type == "EXPORT_CARGO"
        if weighing_record is None:
            raise ApiError("ERR_WEIGHING_SUPERVISION_REQUIRED")
        if needs_supervision and weighing_record["status"] != "SUPERVISED":
            raise ApiError("ERR_WEIGHING_SUPERVISION_REQUIRED")

    if cert_type == "EXPORT_CARGO":
        closed = [
            w
            for w in db.vessel_watches.values()
            if w["inspection_request_id"] == request_row["id"]
            and w["status"] == "CLOSED"
            and w["stowage_certified"]
        ]
        if not closed:
            raise ApiError("ERR_VESSEL_WATCH_NOT_CLOSED")

    grading_result = None
    if cert_type in GRADE_CONTENT:
        grading_result = svc.final_grading_result(request_row["id"])
        if grading_result is None:
            raise ApiError("ERR_GRADING_RESULT_MISSING")

    prior = ordered([c for c in same_type if c["status"] == "ISSUED"])
    prior = prior[-1] if prior else None
    if prior is not None and request_row["grade_revision_count"] == 0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if cert_type in GRADE_CONTENT:
        svc.assert_endorsement(inspector, "GRADING")
    if cert_type in WEIGHT_CONTENT:
        svc.assert_endorsement(inspector, "WEIGHING")
    if cert_type == "EXPORT_CARGO":
        svc.assert_endorsement(inspector, "SUPERVISION")
        if area["authority_type"] != "DESIGNATED":
            raise ApiError("ERR_EXPORT_REQUIRES_DESIGNATED_AREA")

    analysis = None
    if "PROTEIN" in request_row["requested_services"] and cert_type != "WEIGHT":
        analysis = svc.operative_analysis(request_row["id"])

    classes = calc.applicable_classes(cert_type, request_row["requested_services"])
    schedules = []
    for service_class in classes:
        schedule = svc.active_schedule(area["id"], service_class)
        if schedule is None:
            raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE")
        schedules.append(schedule)

    overtime = calc.is_overtime(db.now) if classes else False
    fee = (
        calc.fee_assessment(
            schedules,
            request_row["certified_quantity_bushels"],
            overtime,
            area["fee_multiplier_bp"],
        )
        if classes
        else 0
    )

    if applicant["open_balance_cents"] + fee > applicant["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    superseded_id = None
    if prior is not None:
        svc.reverse_certificate(prior, "SUPERSEDED")
        superseded_id = prior["id"]

    cert = svc.build_certificate(
        request_row,
        cert_type,
        inspector["id"],
        fee,
        overtime,
        grading_result=grading_result,
        weighing_record=weighing_record,
        analysis=analysis,
        superseded_certificate_id=superseded_id,
    )

    if cert["issued_at"] - request_row["created_at"] > LATE_CERTIFICATE_CUTOFF:
        inspector["late_certificate_count"] += 1
        svc.recompute_performance(inspector)
        touch(inspector)

    changed = False
    if cert_type in ("GRADE", "COMBINED", "EXPORT_CARGO"):
        if request_row["grading_status"] != "GRADE_CERTIFIED":
            request_row["grading_status"] = "GRADE_CERTIFIED"
            changed = True
    if cert_type in WEIGHT_CONTENT:
        if request_row["weighing_status"] != "WEIGHT_CERTIFIED":
            request_row["weighing_status"] = "WEIGHT_CERTIFIED"
            changed = True
    if changed:
        touch(request_row)

    return created(serialize(cert))


@bp.get(PREFIX + "/certificates")
@endpoint(ANY_ROLE)
def list_certificates():
    rows = apply_filters(
        db.certificates.values(),
        (
            "inspection_request_id",
            "issuing_inspector_id",
            "superseded_certificate_id",
            "appeal_id",
            "certificate_type",
            "status",
            "fee_settlement_status",
        ),
    )
    return listing(scope_rows(rows))


@bp.get(PREFIX + "/certificates/<row_id>")
@endpoint(ANY_ROLE)
def get_certificate(row_id):
    row = svc.certificate(row_id)
    scope_via_request(row)
    return ok(serialize(row))


@bp.get(PREFIX + "/certificates/<row_id>/appeals")
@endpoint(ANY_ROLE)
def list_certificate_appeals(row_id):
    cert = svc.certificate(row_id)
    scope_via_request(cert)
    rows = [a for a in db.appeals.values() if a["certificate_id"] == cert["id"]]
    rows = apply_filters(rows, ("appeal_type", "status"))
    return listing(rows)


# ==========================================================================
# appeals
# ==========================================================================

@bp.post(PREFIX + "/appeals")
@endpoint((APPLICANT_USER, SERVICE_ADMIN))
def file_appeal():
    body = validation.parse(
        {
            "certificate_id": {"required": True},
            "applicant_id": {"required": True},
            "appeal_type": {"type": "enum", "values": APPEAL_TYPES, "required": True},
            "expected_certificate_version": {"type": "int", "min": 0, "required": True},
        }
    )
    assert_applicant_scope(body["applicant_id"])
    cert = svc.certificate(body["certificate_id"])
    applicant = svc.applicant(body["applicant_id"])
    request_row = db.inspection_requests[cert["inspection_request_id"]]
    area = svc.area(request_row["service_area_id"])
    appeal_type = body["appeal_type"]

    if body["expected_certificate_version"] != cert["version"]:
        raise ApiError("ERR_CERTIFICATE_VERSION_CONFLICT")

    if cert["status"] == "UNDER_APPEAL":
        raise ApiError("ERR_CERTIFICATE_UNDER_APPEAL")
    if cert["status"] != "ISSUED" or cert["certificate_type"] == "APPEAL_GRADE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if svc.non_terminal_appeal_for_certificate(cert["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_OPERATIVE_RECORD")

    if appeal_type == "REINSPECTION":
        if db.now > cert["reinspection_deadline_at"]:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")
    elif appeal_type == "APPEAL":
        if db.now > cert["appeal_deadline_at"]:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")
    else:
        prior = [
            a
            for a in db.appeals.values()
            if a["certificate_id"] == cert["id"]
            and a["appeal_type"] == "APPEAL"
            and a["status"] == "DECIDED_UPHELD"
        ]
        if not prior:
            raise ApiError("ERR_APPEAL_ESCALATION_INVALID")
        latest = ordered(prior)[-1]
        if latest["decided_at"] is None or db.now > latest["decided_at"] + BOARD_APPEAL_WINDOW:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")

    schedule = svc.active_schedule(area["id"], "APPEAL")
    if schedule is None:
        raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE")
    deposit = schedule["base_fee_cents"]

    row = new_row(
        {
            "certificate_id": cert["id"],
            "applicant_id": applicant["id"],
            "assigned_sample_id": None,
            "appeal_type": appeal_type,
            "round_number": calc.ROUND_NUMBERS[appeal_type],
            "required_panel_size": calc.PANEL_SIZES[appeal_type],
            "votes_cast_count": 0,
            "revise_votes_count": 0,
            "uphold_votes_count": 0,
            "abstain_votes_count": 0,
            "effective_votes_count": 0,
            "deposit_cents": deposit,
            "refund_cents": 0,
            "outcome_grade": None,
            "decided_at": None,
            "status": "FILED",
        }
    )
    db.appeals[row["id"]] = row

    cert["status"] = "UNDER_APPEAL"
    touch(cert)
    request_row["grading_status"] = "UNDER_APPEAL"
    touch(request_row)
    if deposit:
        svc.charge(applicant, deposit)

    return created(serialize(row))


@bp.post(PREFIX + "/appeals/<row_id>/assign-sample")
@endpoint((SUPERVISING_INSPECTOR, SERVICE_ADMIN))
def assign_appeal_sample(row_id):
    appeal = svc.appeal(row_id)
    body = validation.parse({"sample_id": {"required": True}})
    sample = svc.sample(body["sample_id"])
    cert = db.certificates[appeal["certificate_id"]]

    if sample["inspection_request_id"] != cert["inspection_request_id"]:
        raise ApiError("ERR_SAMPLE_REQUEST_MISMATCH")

    svc.assert_sample_intact(sample)
    if appeal["status"] != "FILED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    if svc.available_portions(sample) < 1:
        raise ApiError("ERR_SAMPLE_PORTIONS_EXHAUSTED")

    svc.retain_portion(sample)
    appeal["assigned_sample_id"] = sample["id"]
    appeal["status"] = "SAMPLE_ASSIGNED"
    touch(appeal)
    return ok(serialize(appeal))


@bp.post(PREFIX + "/appeals/<row_id>/decide")
@endpoint((SUPERVISING_INSPECTOR, SERVICE_ADMIN))
def decide_appeal(row_id):
    appeal = svc.appeal(row_id)
    validation.parse({})
    if appeal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    if appeal["effective_votes_count"] < appeal["required_panel_size"]:
        raise ApiError("ERR_APPEAL_QUORUM_NOT_MET")

    cert = db.certificates[appeal["certificate_id"]]
    request_row = db.inspection_requests[cert["inspection_request_id"]]
    applicant = db.applicants[request_row["applicant_id"]]
    regrade = svc.appeal_regrade(appeal["id"])
    original = svc.original_final_grading_result(request_row["id"])

    majority = appeal["revise_votes_count"] * 2 > appeal["effective_votes_count"]
    grade_changed = regrade is not None and regrade["assigned_grade"] != cert["grade_snapshot"]
    revised = majority and grade_changed

    appeal["outcome_grade"] = regrade["assigned_grade"] if regrade else None
    appeal["decided_at"] = db.now

    if revised:
        appeal["status"] = "DECIDED_REVISED"
        appeal["refund_cents"] = appeal["deposit_cents"]

        if original is not None:
            original["status"] = "SUPERSEDED"
            touch(original)
            regrade["supersedes_grading_result_id"] = original["id"]
        regrade["status"] = "FINAL"
        touch(regrade)

        svc.reverse_certificate(cert, "VOIDED")

        analysis = None
        if "PROTEIN" in request_row["requested_services"]:
            analysis = svc.operative_analysis(request_row["id"])
        svc.build_certificate(
            request_row,
            "APPEAL_GRADE",
            regrade["inspector_id"],
            0,
            False,
            grading_result=regrade,
            analysis=analysis,
            superseded_certificate_id=cert["id"],
            appeal_id=appeal["id"],
        )

        request_row["grade_revision_count"] += 1
        request_row["grading_status"] = "GRADE_CERTIFIED"
        touch(request_row)

        if original is not None:
            faulted = db.inspectors.get(original["inspector_id"])
            if faulted is not None:
                faulted["appeal_reversal_count"] += 1
                svc.recompute_performance(faulted)
                touch(faulted)
    else:
        appeal["status"] = "DECIDED_UPHELD"
        appeal["refund_cents"] = 0
        cert["status"] = "ISSUED"
        touch(cert)
        request_row["grading_status"] = "GRADE_CERTIFIED"
        touch(request_row)

    if appeal["refund_cents"]:
        svc.credit(applicant, appeal["refund_cents"])
    if appeal["assigned_sample_id"]:
        sample = db.samples.get(appeal["assigned_sample_id"])
        if sample is not None:
            svc.release_retained_portion(sample)
    touch(appeal)
    return ok(serialize(appeal))


@bp.post(PREFIX + "/appeals/<row_id>/dismiss")
@endpoint((SERVICE_ADMIN,))
def dismiss_appeal(row_id):
    appeal = svc.appeal(row_id)
    validation.parse({"reason": {"nullable": True, "default": None}})
    if appeal["status"] not in ("FILED", "SAMPLE_ASSIGNED"):
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    cert = db.certificates[appeal["certificate_id"]]
    request_row = db.inspection_requests[cert["inspection_request_id"]]
    applicant = db.applicants[request_row["applicant_id"]]

    had_sample = appeal["status"] == "SAMPLE_ASSIGNED"
    appeal["status"] = "DISMISSED"
    appeal["refund_cents"] = appeal["deposit_cents"] // 2
    touch(appeal)

    if cert["status"] == "UNDER_APPEAL":
        cert["status"] = "ISSUED"
        touch(cert)
    if request_row["grading_status"] == "UNDER_APPEAL":
        request_row["grading_status"] = "GRADE_CERTIFIED"
        touch(request_row)
    if appeal["refund_cents"]:
        svc.credit(applicant, appeal["refund_cents"])
    if had_sample and appeal["assigned_sample_id"]:
        sample = db.samples.get(appeal["assigned_sample_id"])
        if sample is not None:
            svc.release_retained_portion(sample)
    return ok(serialize(appeal))


@bp.get(PREFIX + "/appeals")
@endpoint(ANY_ROLE)
def list_appeals():
    rows = apply_filters(
        db.appeals.values(),
        ("certificate_id", "applicant_id", "assigned_sample_id", "appeal_type", "status"),
    )
    acting = acting_applicant_id()
    if acting is not None:
        rows = [row for row in rows if row["applicant_id"] == acting]
    return listing(rows)


@bp.get(PREFIX + "/appeals/<row_id>")
@endpoint(ANY_ROLE)
def get_appeal(row_id):
    row = svc.appeal(row_id)
    assert_applicant_scope(row["applicant_id"])
    return ok(serialize(row))


# ==========================================================================
# appeal votes
# ==========================================================================

@bp.post(PREFIX + "/appeal-votes")
@endpoint((SUPERVISING_INSPECTOR, SERVICE_ADMIN))
def cast_appeal_vote():
    body = validation.parse(
        {
            "appeal_id": {"required": True},
            "inspector_id": {"required": True},
            "vote": {"type": "enum", "values": VOTES, "required": True},
            "rationale": {"nullable": True, "default": None},
            "expected_appeal_version": {"type": "int", "min": 0, "required": True},
        }
    )
    appeal = svc.appeal(body["appeal_id"])
    inspector = svc.inspector(body["inspector_id"])
    cert = db.certificates[appeal["certificate_id"]]
    request_row = db.inspection_requests[cert["inspection_request_id"]]

    if body["expected_appeal_version"] != appeal["version"]:
        raise ApiError("ERR_APPEAL_VERSION_CONFLICT")

    svc.assert_licence(inspector, ("ACTIVE",))

    original = svc.original_final_grading_result(request_row["id"])
    if original is None:
        original = next(
            (
                r
                for r in ordered(
                    [
                        g
                        for g in db.grading_results.values()
                        if g["inspection_request_id"] == request_row["id"]
                        and g["appeal_id"] is None
                    ]
                )
            ),
            None,
        )
    if original is not None and original["inspector_id"] == inspector["id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    for existing in db.appeal_votes.values():
        if existing["appeal_id"] == appeal["id"] and existing["inspector_id"] == inspector["id"]:
            raise ApiError("ERR_DUPLICATE_PANEL_VOTE")

    if appeal["appeal_type"] == "BOARD_APPEAL":
        if inspector["service_area_id"] == request_row["service_area_id"]:
            raise ApiError("ERR_BOARD_PANEL_COMPOSITION_INVALID")

    row = new_row(
        {
            "appeal_id": appeal["id"],
            "inspector_id": inspector["id"],
            "vote": body["vote"],
            "rationale": body["rationale"],
        },
        common_fields=False,
    )
    db.appeal_votes[row["id"]] = row

    appeal["votes_cast_count"] += 1
    if body["vote"] == "REVISE":
        appeal["revise_votes_count"] += 1
    elif body["vote"] == "UPHOLD":
        appeal["uphold_votes_count"] += 1
    else:
        appeal["abstain_votes_count"] += 1
    appeal["effective_votes_count"] = appeal["revise_votes_count"] + appeal["uphold_votes_count"]
    touch(appeal)

    return created(serialize(row))


@bp.get(PREFIX + "/appeal-votes")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, LICENSED_INSPECTOR, AUDITOR))
def list_appeal_votes():
    rows = apply_filters(db.appeal_votes.values(), ("appeal_id", "inspector_id"))
    return listing(rows)


@bp.get(PREFIX + "/appeal-votes/<row_id>")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, LICENSED_INSPECTOR, AUDITOR))
def get_appeal_vote(row_id):
    return ok(serialize(svc.find("appeal_votes", row_id, "ERR_APPEAL_VOTE_NOT_FOUND")))


# ==========================================================================
# vessel watches
# ==========================================================================

@bp.post(PREFIX + "/vessel-watches")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR))
def create_vessel_watch():
    body = validation.parse(
        {
            "inspection_request_id": {"required": True},
            "supervisor_inspector_id": {"required": True},
            "vessel_name": {"required": True},
            "window_start_at": {"type": "datetime", "required": True},
            "window_end_at": {"type": "datetime", "required": True},
            "holds_declared": {"type": "int", "min": 1, "required": True},
        }
    )
    request_row = svc.request(body["inspection_request_id"])
    inspector = svc.inspector(body["supervisor_inspector_id"])
    area = svc.area(request_row["service_area_id"])

    svc.assert_service_requested(request_row, "EXPORT_SUPERVISION")
    svc.assert_area_active(area)
    svc.assert_licence(inspector, ("ACTIVE",))

    start = body["window_start_at"]
    end = body["window_end_at"]
    if end <= start:
        raise ApiError("ERR_WATCH_WINDOW_INVALID")

    for other in db.vessel_watches.values():
        if other["supervisor_inspector_id"] != inspector["id"]:
            continue
        if other["status"] not in svc.NON_TERMINAL_WATCH:
            continue
        if start < other["window_end_at"] + TRAVEL_BUFFER and other["window_start_at"] < end + TRAVEL_BUFFER:
            raise ApiError("ERR_INSPECTOR_WATCH_OVERLAP")

    intersecting = 0
    for other in db.vessel_watches.values():
        if other["service_area_id"] != area["id"]:
            continue
        if other["status"] not in svc.NON_TERMINAL_WATCH:
            continue
        if other["window_start_at"] <= end and start <= other["window_end_at"]:
            intersecting += 1
    if intersecting >= area["concurrent_watch_capacity"]:
        raise ApiError("ERR_AREA_WATCH_CAPACITY_EXCEEDED")

    row = new_row(
        {
            "inspection_request_id": request_row["id"],
            "service_area_id": area["id"],
            "supervisor_inspector_id": inspector["id"],
            "vessel_name": body["vessel_name"],
            "window_start_at": start,
            "window_end_at": end,
            "holds_declared": body["holds_declared"],
            "stowage_certified": False,
            "started_at": None,
            "closed_at": None,
            "supervision_minutes": None,
            "status": "SCHEDULED",
        }
    )
    db.vessel_watches[row["id"]] = row
    area["open_watch_count"] += 1
    touch(area)
    return created(serialize(row))


@bp.post(PREFIX + "/vessel-watches/<row_id>/start")
@endpoint((SUPERVISING_INSPECTOR,))
def start_vessel_watch(row_id):
    row = svc.find("vessel_watches", row_id, "ERR_VESSEL_WATCH_NOT_FOUND")
    inspector = db.inspectors.get(row["supervisor_inspector_id"])
    if inspector is None:
        raise ApiError("ERR_INSPECTOR_NOT_FOUND")

    # Rung 9 is the State rung: the watch must be in a state the action is
    # declared from before the holder's licence is consulted.
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    svc.assert_licence(inspector, ("ACTIVE",))
    svc.assert_endorsement(inspector, "SUPERVISION")
    if not (row["window_start_at"] <= db.now < row["window_end_at"]):
        raise ApiError("ERR_WATCH_WINDOW_INVALID")

    row["started_at"] = db.now
    row["status"] = "IN_PROGRESS"
    touch(row)
    return ok(serialize(row))


@bp.post(PREFIX + "/vessel-watches/<row_id>/close")
@endpoint((SUPERVISING_INSPECTOR,))
def close_vessel_watch(row_id):
    row = svc.find("vessel_watches", row_id, "ERR_VESSEL_WATCH_NOT_FOUND")
    body = validation.parse(
        {
            "holds_supervised": {"type": "int", "min": 0, "required": True},
            "stowage_certified": {"type": "bool", "required": True},
        }
    )
    if row["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if body["holds_supervised"] != row["holds_declared"]:
        raise ApiError("ERR_HOLDS_NOT_FULLY_SUPERVISED")

    row["stowage_certified"] = body["stowage_certified"]
    row["closed_at"] = db.now
    started = row["started_at"] or db.now
    row["supervision_minutes"] = int((row["closed_at"] - started).total_seconds() // 60)
    row["status"] = "CLOSED"
    touch(row)

    area = db.service_areas.get(row["service_area_id"])
    if area is not None and area["open_watch_count"] > 0:
        area["open_watch_count"] -= 1
        touch(area)
    return ok(serialize(row))


@bp.post(PREFIX + "/vessel-watches/<row_id>/abort")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR))
def abort_vessel_watch(row_id):
    row = svc.find("vessel_watches", row_id, "ERR_VESSEL_WATCH_NOT_FOUND")
    validation.parse({"reason": {"nullable": True, "default": None}})
    if row["status"] not in svc.NON_TERMINAL_WATCH:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["status"] = "ABORTED"
    touch(row)
    area = db.service_areas.get(row["service_area_id"])
    if area is not None and area["open_watch_count"] > 0:
        area["open_watch_count"] -= 1
        touch(area)
    return ok(serialize(row))


@bp.get(PREFIX + "/vessel-watches")
@endpoint(ANY_ROLE)
def list_vessel_watches():
    rows = apply_filters(
        db.vessel_watches.values(),
        ("inspection_request_id", "service_area_id", "supervisor_inspector_id", "status"),
    )
    return listing(scope_rows(rows))


@bp.get(PREFIX + "/vessel-watches/<row_id>")
@endpoint(ANY_ROLE)
def get_vessel_watch(row_id):
    row = svc.find("vessel_watches", row_id, "ERR_VESSEL_WATCH_NOT_FOUND")
    scope_via_request(row)
    return ok(serialize(row))
