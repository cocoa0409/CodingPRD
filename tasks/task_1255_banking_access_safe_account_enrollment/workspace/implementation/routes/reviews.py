"""CertificationReview endpoints, including scoring, finalization, and decert cascade."""

from datetime import timedelta

import db
from errors import (
    err_not_found, err_invalid_state, err_validation, raise_err,
    ERR_STALE_VERSION, ERR_SOD_VIOLATION, ERR_STANDARD_NOT_EFFECTIVE,
    ERR_REVIEW_GAP_VIOLATION,
)
from middleware import require_roles, get_json_body, require_fields, check_string, check_int
from response import success_object, success_list, parse_pagination
from services.common import new_entity, touch, recompute_pipeline
from services.calculations import compute_weighted_score, compute_outcome, CRITERIA
from flask import request

MIN_REVIEW_GAP_DAYS = 30


def _serialize(rev):
    out = dict(rev)
    if out.get("weighted_score") is not None:
        out["weighted_score"] = float(out["weighted_score"])
    return out


def _run_decert_cascade(inst):
    """Four-link decertification cascade per PRD §3.1."""
    # link 2: cancel every SCHEDULED event of the institution
    for ev in db.account_opening_events.values():
        if ev["institution_id"] != inst["id"] or ev["status"] != "SCHEDULED":
            continue
        ev["status"] = "CANCELLED"
        touch(ev)
        # link 3: booked referrals -> DOCS_COMPLETE, clear booking
        for ref in db.referrals.values():
            if ref.get("booked_event_id") == ev["id"] and ref["status"] == "BOOKED":
                ref["status"] = "DOCS_COMPLETE"
                ref["booked_event_id"] = None
                touch(ref)
                if ev["booked_count"] > 0:
                    ev["booked_count"] -= 1
                # link 4: participant pipeline recompute
                recompute_pipeline(ref["participant_id"])
    inst["current_review_id"] = None


def register(bp):
    @bp.route("/certification-reviews", methods=["POST"])
    def create_review():
        require_roles("CoalitionAdmin")
        body = get_json_body()
        require_fields(body, ["institution_id", "standard_id", "period_start", "period_end", "expected_institution_version"])
        check_string(body["institution_id"], "institution_id")
        check_string(body["standard_id"], "standard_id")
        check_string(body["period_start"], "period_start")
        check_string(body["period_end"], "period_end")
        check_int(body["expected_institution_version"], "expected_institution_version")
        if db.parse_date(body["period_start"]) > db.parse_date(body["period_end"]):
            err_validation("period_start must be on or before period_end")

        # existence: body FKs in input order
        inst = db.partner_institutions.get(body["institution_id"])
        if inst is None:
            err_not_found("PartnerInstitution not found")
        std = db.account_standards.get(body["standard_id"])
        if std is None:
            err_not_found("AccountStandard not found")

        # institution state: review creation allowed from APPLIED, LAPSED, CERTIFIED,
        # or UNDER_REVIEW (supersede of the live review per PRD §3.1)
        if inst["certification_status"] not in ("APPLIED", "LAPSED", "CERTIFIED", "UNDER_REVIEW"):
            err_invalid_state("Institution state does not allow opening a review")

        # OCC check
        if body["expected_institution_version"] != inst["version"]:
            raise_err(ERR_STALE_VERSION, "expected_institution_version does not match current institution version")

        # temporal: review gap check (against non-SUPERSEDED prior reviews)
        prior = [
            r for r in db.certification_reviews.values()
            if r["institution_id"] == inst["id"] and r["status"] != "SUPERSEDED"
        ]
        if prior:
            latest_end = max(db.parse_date(r["period_end"]) for r in prior)
            min_start = latest_end + timedelta(days=MIN_REVIEW_GAP_DAYS)
            if db.parse_date(body["period_start"]) < min_start:
                raise_err(ERR_REVIEW_GAP_VIOLATION, "New review period_start violates the 30-day minimum gap")

        # cross-entity: standard must be EFFECTIVE
        if std["status"] != "EFFECTIVE":
            raise_err(ERR_STANDARD_NOT_EFFECTIVE, "Pinned standard must be EFFECTIVE")

        # supersede live DRAFT/SCORED review
        live_id = inst.get("current_review_id")
        if live_id:
            live = db.certification_reviews.get(live_id)
            if live is not None and live["status"] in ("DRAFT", "SCORED"):
                live["status"] = "SUPERSEDED"
                touch(live)

        rev = new_entity()
        rev.update({
            "institution_id": inst["id"],
            "standard_id": std["id"],
            "period_start": body["period_start"],
            "period_end": body["period_end"],
            "criteria_ratings": None,
            "mandatory_floor_failed": None,
            "weighted_score": None,
            "outcome": None,
            "scored_by_user_id": None,
            "finalized_by_user_id": None,
            "status": "DRAFT",
        })
        db.certification_reviews[rev["id"]] = rev

        # institution transitions to UNDER_REVIEW
        inst["certification_status"] = "UNDER_REVIEW"
        inst["current_review_id"] = rev["id"]
        touch(inst)

        return success_object(_serialize(rev), status=201)

    @bp.route("/certification-reviews", methods=["GET"])
    def list_reviews():
        require_roles("CoalitionAdmin", "InstitutionOfficer")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.certification_reviews.values(), key=lambda x: db.parse_dt(x["created_at"]))
        iid = request.args.get("institution_id")
        sid = request.args.get("standard_id")
        st = request.args.get("status")
        if iid is not None:
            items = [r for r in items if r["institution_id"] == iid]
        if sid is not None:
            items = [r for r in items if r["standard_id"] == sid]
        if st is not None:
            items = [r for r in items if r["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(r) for r in page], limit, offset, total)

    @bp.route("/certification-reviews/<rid>", methods=["GET"])
    def get_review(rid):
        require_roles("CoalitionAdmin", "InstitutionOfficer")
        rev = db.certification_reviews.get(rid)
        if rev is None:
            err_not_found("CertificationReview not found")
        return success_object(_serialize(rev))

    @bp.route("/certification-reviews/<rid>/score", methods=["POST"])
    def score_review(rid):
        user_id, _ = require_roles("CoalitionAdmin")
        rev = db.certification_reviews.get(rid)
        if rev is None:
            err_not_found("CertificationReview not found")
        if rev["status"] != "DRAFT":
            err_invalid_state("Review must be DRAFT to score")
        body = get_json_body()
        require_fields(body, ["criteria_ratings"])
        ratings = body["criteria_ratings"]
        if not isinstance(ratings, list):
            err_validation("criteria_ratings must be an array")
        seen = {}
        for entry in ratings:
            if not isinstance(entry, dict) or "criterion" not in entry or "rating" not in entry:
                err_validation("Each criteria_ratings entry must have criterion and rating")
            crit = entry["criterion"]
            rating = entry["rating"]
            if crit not in CRITERIA:
                err_validation("Unknown criterion: %s" % crit)
            if isinstance(rating, bool) or not isinstance(rating, int) or rating < 0 or rating > 4:
                err_validation("rating must be an integer 0..4")
            seen[crit] = rating
        if set(seen.keys()) != set(CRITERIA):
            err_validation("criteria_ratings must cover all 5 criteria")

        normalized = [{"criterion": c, "rating": seen[c]} for c in CRITERIA]
        weighted, floor_failed = compute_weighted_score(normalized)

        rev["criteria_ratings"] = normalized
        rev["weighted_score"] = weighted
        rev["mandatory_floor_failed"] = floor_failed
        rev["scored_by_user_id"] = user_id
        rev["status"] = "SCORED"
        touch(rev)
        return success_object(_serialize(rev))

    @bp.route("/certification-reviews/<rid>/finalize", methods=["POST"])
    def finalize_review(rid):
        user_id, _ = require_roles("CoalitionAdmin")
        rev = db.certification_reviews.get(rid)
        if rev is None:
            err_not_found("CertificationReview not found")
        if rev["status"] != "SCORED":
            err_invalid_state("Review must be SCORED to finalize")
        if user_id == rev["scored_by_user_id"]:
            raise_err(ERR_SOD_VIOLATION, "Finalizer must differ from scorer")

        std = db.account_standards.get(rev["standard_id"])
        outcome = compute_outcome(std["rubric_mode"], rev["weighted_score"], rev["mandatory_floor_failed"])
        rev["outcome"] = outcome
        rev["finalized_by_user_id"] = user_id
        if outcome == "PASS":
            rev["status"] = "FINALIZED_PASS"
        elif outcome == "CONDITIONAL":
            rev["status"] = "FINALIZED_CONDITIONAL"
        else:
            rev["status"] = "FINALIZED_FAIL"
        touch(rev)

        inst = db.partner_institutions.get(rev["institution_id"])
        if inst is not None:
            if outcome in ("PASS", "CONDITIONAL"):
                now = db.parse_dt(db.get_clock())
                inst["certification_status"] = "CERTIFIED"
                inst["certified_at"] = db.now_iso()
                inst["certification_expires_at"] = db.add_months(now, 24).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                inst["certified_standard_id"] = rev["standard_id"]
                inst["current_review_id"] = None
                touch(inst)
            else:
                # FAIL -> DECERTIFIED with cascade
                inst["certification_status"] = "DECERTIFIED"
                _run_decert_cascade(inst)
                touch(inst)

        return success_object(_serialize(rev))
