"""Enrollment lifecycle routes."""
from flask import request

import domain
import serializers as S
from common import (
    get_user_context, require_role, get_json_body, check_string, check_enum,
    check_int, touch,
)
from domain import LEVELS_ORDER
from errors import err
from lookups import (
    get_dog, get_series, get_enrollment, get_package, list_response,
)
from response import success
from store import db, new_id, now_iso


def _create_attendance_for_enrollment(enrollment, series):
    """Create EXPECTED AttendanceRecord for each non-makeup session of the series."""
    sessions = [s for s in db.class_sessions.values()
                if s["series_id"] == series["id"] and not s["is_makeup_slot"]]
    for sess in sessions:
        aid = new_id()
        ts = now_iso()
        rec = {
            "id": aid, "created_at": ts, "updated_at": ts, "version": 1,
            "enrollment_id": enrollment["id"], "session_id": sess["id"],
            "state": "EXPECTED", "makeup_eligible": False,
        }
        db.attendance_records[aid] = rec


def _delete_attendance_for_enrollment(enrollment_id, states=None):
    to_del = []
    for aid, a in db.attendance_records.items():
        if a["enrollment_id"] != enrollment_id:
            continue
        if states is None or a["state"] in states:
            to_del.append(aid)
    for aid in to_del:
        del db.attendance_records[aid]


def _settle_payment(enrollment, series):
    """Apply CASH charge or PACKAGE debit. Caller has validated package."""
    if enrollment["payment_method"] == "CASH":
        enrollment["price_charged_cents"] = series["list_price_cents"]
        enrollment["credits_debited"] = 0
    else:  # PACKAGE
        package = db.packages[enrollment["package_id"]]
        rid = new_id()
        ts = now_iso()
        red = {
            "id": rid, "created_at": ts,
            "package_id": package["id"], "enrollment_id": enrollment["id"],
            "kind": "DEBIT", "credits": series["credit_cost"],
        }
        db.package_redemptions[rid] = red
        domain.recompute_package(package)
        enrollment["price_charged_cents"] = 0
        enrollment["credits_debited"] = series["credit_cost"]


def _activate(enrollment, series):
    """Common ACTIVE side effects: attendance creation + payment settlement."""
    _create_attendance_for_enrollment(enrollment, series)
    _settle_payment(enrollment, series)
    domain.refresh_enrollment_progress(enrollment)


def register(app):

    @app.route("/enrollments", methods=["POST"])
    def create_enrollment():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        body = get_json_body()
        dog_id = check_string(body, "dog_id")
        series_id = check_string(body, "series_id")
        payment_method = check_enum(body, "payment_method", {"CASH", "PACKAGE"})
        package_id = body.get("package_id")
        if package_id is not None and not isinstance(package_id, str):
            raise err("ERR_INVALID_REQUEST", "package_id must be a string or null")
        expected_series_version = check_int(body, "expected_series_version")

        # priority 3: existence (series, then ... dog; package only when relevant)
        series = get_series(series_id)
        if payment_method == "PACKAGE" and package_id is not None:
            get_package(package_id)
        dog = get_dog(dog_id)

        # priority 4: ownership
        if role == "Owner" and dog["owner_id"] != user_id:
            raise err("ERR_NOT_DOG_OWNER", "Acting owner does not own this dog")

        # priority 5: series state
        if series["status"] != "OPEN":
            raise err("ERR_SERIES_NOT_OPEN", "Series must be OPEN to enroll")

        # priority 6 (business constraints): payment shape, private-first, duplicate
        if payment_method == "PACKAGE" and package_id is None:
            raise err("ERR_PACKAGE_REQUIRED_FOR_CREDIT",
                      "package_id required for PACKAGE payment")
        if payment_method == "CASH" and package_id is not None:
            raise err("ERR_PACKAGE_REQUIRED_FOR_CREDIT",
                      "package_id must be null for CASH payment")

        # private-first gate (GROUP + FLAGGED dog)
        intake_status = domain.compute_intake_status(dog_id)
        if series["modality"] == "GROUP" and intake_status == "FLAGGED":
            has_private_grad = any(
                e["dog_id"] == dog_id and e["status"] == "GRADUATED"
                and db.class_series.get(e["series_id"], {}).get("modality") == "PRIVATE"
                for e in db.enrollments.values()
            )
            if not has_private_grad:
                raise err("ERR_PRIVATE_FIRST_REQUIRED",
                          "FLAGGED dog must complete a PRIVATE series before GROUP")

        # duplicate enrollment (non-terminal) for (dog, series)
        for e in db.enrollments.values():
            if (e["dog_id"] == dog_id and e["series_id"] == series_id
                    and e["status"] not in ("WITHDRAWN", "GRADUATED")):
                raise err("ERR_DUPLICATE_ENROLLMENT",
                          "A non-terminal enrollment already exists")

        # priority 7: vaccination prerequisite (against first non-makeup session date)
        ref_date = domain.series_first_session_date(series_id)
        if ref_date is not None:
            posture = domain.compute_vaccination_posture(dog_id, ref_date)
        else:
            posture = domain.dog_posture_now(dog_id)
        if posture != "COMPLIANT":
            raise err("ERR_VACCINATION_PREREQUISITE",
                      "Dog vaccination posture not COMPLIANT")

        # priority 9: level prerequisite
        highest = domain.compute_highest_completed_level(dog_id)
        if LEVELS_ORDER[highest] < LEVELS_ORDER[series["prerequisite_level"]]:
            raise err("ERR_PREREQUISITE_LEVEL_NOT_MET",
                      "Dog highest_completed_level below prerequisite")

        # priority 11: dog temporal overlap (candidate = series non-makeup sessions)
        candidate_session_ids = [s["id"] for s in db.class_sessions.values()
                                 if s["series_id"] == series_id and not s["is_makeup_slot"]]
        committed = domain.dog_committed_intervals(dog_id)
        candidate_intervals = []
        for sid in candidate_session_ids:
            sess = db.class_sessions.get(sid)
            if sess and sess["status"] != "CANCELLED":
                candidate_intervals.append(
                    (domain.parse_dt(sess["starts_at"]), domain.parse_dt(sess["ends_at"])))
        if domain.intervals_strictly_overlap(committed, candidate_intervals):
            raise err("ERR_DOG_SESSION_OVERLAP", "Dog has overlapping sessions")

        # priority 12: package credit checks (PACKAGE)
        if payment_method == "PACKAGE":
            package = db.packages[package_id]
            if package["owner_id"] != dog["owner_id"]:
                raise err("ERR_PACKAGE_NOT_OWNED",
                          "Package does not belong to the dog's owner")
            domain.recompute_package(package)
            if package["status"] != "ACTIVE":
                raise err("ERR_PACKAGE_NOT_ACTIVE", "Package is not ACTIVE")
            if package["credits_remaining"] < series["credit_cost"]:
                raise err("ERR_INSUFFICIENT_CREDITS", "Not enough package credits")

        # priority 13 already handled (duplicate) above per priority list

        # priority (final): OCC stale-version check
        if expected_series_version != series["version"]:
            raise err("ERR_STALE_SERIES_VERSION",
                      "expected_series_version does not match current series version")

        # All gates pass — decide ACTIVE vs WAITLISTED
        seats_raw = domain.seats_available_raw(series)
        eid = new_id()
        ts = now_iso()
        enrollment = {
            "id": eid, "created_at": ts, "updated_at": ts, "version": 1,
            "dog_id": dog_id, "series_id": series_id,
            "payment_method": payment_method, "package_id": package_id,
            "price_charged_cents": 0, "credits_debited": 0,
            "sessions_attended": 0, "sessions_remaining": series["session_count"],
            "graduation_eligible": False, "refund_cents": 0, "credits_refunded": 0,
            "status": "PENDING_PREREQS",
        }
        db.enrollments[eid] = enrollment

        if seats_raw >= 1:
            enrollment["status"] = "ACTIVE"
            _activate(enrollment, series)
        else:
            enrollment["status"] = "WAITLISTED"

        # PRD §3.6: "the series' enrolled_count and seats_available are recomputed, and the
        # series version is incremented by one." That single +1 IS the seat recompute (PRD
        # §2.4 "increments by exactly 1 on every mutation"); recompute_series_seats performs
        # the lone touch when enrolled_count/seats_available change. No separate transition
        # bump — a duplicate touch() here would advance the version by 2 on one enrollment.
        domain.recompute_series_seats(series)
        return success(S.ser_enrollment(enrollment), 201)

    @app.route("/enrollments", methods=["GET"])
    def list_enrollments():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
        rows = list(db.enrollments.values())
        dog_id = request.args.get("dog_id")
        series_id = request.args.get("series_id")
        package_id = request.args.get("package_id")
        status = request.args.get("status")
        if dog_id is not None:
            rows = [e for e in rows if e["dog_id"] == dog_id]
        if series_id is not None:
            rows = [e for e in rows if e["series_id"] == series_id]
        if package_id is not None:
            rows = [e for e in rows if e["package_id"] == package_id]
        if status is not None:
            rows = [e for e in rows if e["status"] == status]
        if role == "Owner":
            owned = {d["id"] for d in db.dogs.values() if d["owner_id"] == user_id}
            rows = [e for e in rows if e["dog_id"] in owned]
        return list_response(rows, lambda e: S.ser_enrollment(e, refresh=True))

    @app.route("/enrollments/<enrollment_id>", methods=["GET"])
    def get_enrollment_ep(enrollment_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
        enrollment = get_enrollment(enrollment_id)
        if role == "Owner":
            dog = db.dogs.get(enrollment["dog_id"])
            if not dog or dog["owner_id"] != user_id:
                raise err("ERR_NOT_DOG_OWNER", "Not owner of this enrollment's dog")
        return success(S.ser_enrollment(enrollment, refresh=True), 200)

    @app.route("/enrollments/<enrollment_id>/promote", methods=["POST"])
    def promote_enrollment(enrollment_id):
        user_id, role = get_user_context()
        require_role(role, {"FrontDesk", "AdminManager"})
        enrollment = get_enrollment(enrollment_id)
        if enrollment["status"] != "WAITLISTED":
            raise err("ERR_INVALID_STATE", "Enrollment must be WAITLISTED to promote")
        series = db.class_series.get(enrollment["series_id"])
        if domain.seats_available_raw(series) < 1:
            raise err("ERR_NO_SEAT_AVAILABLE", "No seat available")
        # re-check vaccination posture
        ref_date = domain.series_first_session_date(series["id"])
        if ref_date is not None:
            posture = domain.compute_vaccination_posture(enrollment["dog_id"], ref_date)
        else:
            posture = domain.dog_posture_now(enrollment["dog_id"])
        if posture != "COMPLIANT":
            raise err("ERR_VACCINATION_PREREQUISITE",
                      "Dog vaccination posture not COMPLIANT")
        enrollment["status"] = "ACTIVE"
        _activate(enrollment, series)
        touch(enrollment)
        domain.recompute_series_seats(series)
        return success(S.ser_enrollment(enrollment), 200)

    @app.route("/enrollments/<enrollment_id>/reinstate", methods=["POST"])
    def reinstate_enrollment(enrollment_id):
        user_id, role = get_user_context()
        require_role(role, {"FrontDesk", "AdminManager"})
        enrollment = get_enrollment(enrollment_id)
        if enrollment["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", "Enrollment must be SUSPENDED to reinstate")
        posture = domain.dog_posture_now(enrollment["dog_id"])
        if posture != "COMPLIANT":
            raise err("ERR_VACCINATION_PREREQUISITE",
                      "Dog vaccination posture not COMPLIANT")
        enrollment["status"] = "ACTIVE"
        touch(enrollment)
        series = db.class_series.get(enrollment["series_id"])
        if series:
            domain.recompute_series_seats(series)
        return success(S.ser_enrollment(enrollment), 200)

    @app.route("/enrollments/<enrollment_id>/graduate", methods=["POST"])
    def graduate_enrollment(enrollment_id):
        user_id, role = get_user_context()
        require_role(role, {"AdminManager"})
        enrollment = get_enrollment(enrollment_id)
        if enrollment["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Enrollment must be ACTIVE to graduate")
        series = db.class_series.get(enrollment["series_id"])
        domain.refresh_enrollment_progress(enrollment)
        if not enrollment["graduation_eligible"]:
            raise err("ERR_NOT_GRADUATION_ELIGIBLE",
                      "Enrollment is not graduation-eligible")
        enrollment["status"] = "GRADUATED"
        touch(enrollment)
        # Certificate
        cid = new_id()
        ts = now_iso()
        epoch = int(domain.parse_dt(ts).timestamp())
        cert = {
            "id": cid, "created_at": ts,
            "enrollment_id": enrollment["id"], "dog_id": enrollment["dog_id"],
            "level": series["level"],
            "serial": "CERT-%s-%d" % (series["level"], epoch),
        }
        db.certificates[cid] = cert
        # Dog highest_completed_level recompute happens at read; nothing to store.
        domain.recompute_series_seats(series)
        return success(S.ser_enrollment(enrollment), 200)

    @app.route("/enrollments/<enrollment_id>/withdraw", methods=["POST"])
    def withdraw_enrollment(enrollment_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        enrollment = get_enrollment(enrollment_id)
        if enrollment["status"] not in ("PENDING_PREREQS", "ACTIVE", "WAITLISTED", "SUSPENDED"):
            raise err("ERR_INVALID_STATE", "Enrollment cannot be withdrawn from its state")
        dog = db.dogs.get(enrollment["dog_id"])
        if role == "Owner" and (not dog or dog["owner_id"] != user_id):
            raise err("ERR_NOT_DOG_OWNER", "Acting owner does not own this enrollment's dog")
        series = db.class_series.get(enrollment["series_id"])

        was_active_holding = enrollment["status"] in ("ACTIVE", "SUSPENDED")
        had_payment = enrollment["status"] in ("ACTIVE", "SUSPENDED")

        # Refund cascade only applies when the enrollment actually settled payment
        # (ACTIVE/SUSPENDED). WAITLISTED/PENDING_PREREQS never charged.
        refund_cents = 0
        credits_refunded = 0
        if had_payment:
            refund = domain.compute_refund(enrollment, series)
            if enrollment["payment_method"] == "CASH":
                refund_cents = refund["refund_cents"]
            else:  # PACKAGE
                credits_refunded = refund["credits_refunded"]
                if credits_refunded > 0 and enrollment["package_id"]:
                    package = db.packages.get(enrollment["package_id"])
                    if package:
                        rid = new_id()
                        ts = now_iso()
                        red = {
                            "id": rid, "created_at": ts,
                            "package_id": package["id"], "enrollment_id": enrollment["id"],
                            "kind": "REVERSAL", "credits": credits_refunded,
                        }
                        db.package_redemptions[rid] = red
                        domain.recompute_package(package)

        enrollment["refund_cents"] = refund_cents
        enrollment["credits_refunded"] = credits_refunded
        enrollment["status"] = "WITHDRAWN"
        # delete outstanding EXPECTED/MAKEUP_PENDING attendance rows
        _delete_attendance_for_enrollment(enrollment_id, states=("EXPECTED", "MAKEUP_PENDING"))
        touch(enrollment)
        if series:
            domain.recompute_series_seats(series)
        return success(S.ser_enrollment(enrollment), 200)
