"""/nil-deals endpoints."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.models import make_entity, mark_mutated, serialize, serialize_list
from core.store import STORE, lock
from core.validation import (
    require_body,
    require_field,
    require_enum,
    parse_pagination,
    check_version,
)
from services.aggregates import recompute_athlete_nil_lifetime
from services.calculations import compute_fmv_cents, compute_pay_for_play


bp = Blueprint("nil_deals", __name__)


VALID_CATEGORIES = {
    "ENDORSEMENT",
    "APPEARANCE",
    "SOCIAL_MEDIA_POST",
    "AUTOGRAPH_SIGNING",
    "CAMP_INSTRUCTION",
}
VALID_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "SUSPENDED", "REVOKED"}


def _recompute_deal_derivations(deal):
    """Recompute fmv + pay_for_play from current fields."""
    deal["fmv_calculated_cents"] = compute_fmv_cents(deal)
    athlete = STORE.athletes.get(deal["athlete_id"])
    deal["pay_for_play_flag"] = compute_pay_for_play(deal, athlete)


@bp.route("/nil-deals", methods=["POST"])
@require_roles("Athlete", "Booster", "ComplianceOfficer")
def create_deal():
    body = require_body(request)
    athlete_id = require_field(body, "athlete_id", kind="string")
    sponsor_name = require_field(body, "sponsor_name", kind="string")
    sponsor_is_booster = require_field(body, "sponsor_is_booster", kind="bool")
    deal_category = require_enum(body, "deal_category", VALID_CATEGORIES)
    stated_value = require_field(body, "stated_value_cents", kind="int")
    deliverables_hours = require_field(body, "deliverables_hours", kind="number")
    market_rate = require_field(body, "market_rate_cents_per_hour", kind="int")

    with lock():
        athlete = STORE.athletes.get(athlete_id)
        if athlete is None:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")
        # Athlete role ownership
        if g.user_role == "Athlete" and g.user_id != athlete_id:
            raise_error("ERR_FORBIDDEN", "Athlete may only submit own deals")

        # Body shape: stated_value>0, deliverables_hours>0, market_rate>0
        if isinstance(stated_value, bool) or int(stated_value) <= 0:
            raise_error("ERR_VALIDATION_FAILED", "stated_value_cents must be > 0")
        if isinstance(deliverables_hours, bool) or float(deliverables_hours) <= 0:
            raise_error("ERR_VALIDATION_FAILED", "deliverables_hours must be > 0")
        if isinstance(market_rate, bool) or int(market_rate) <= 0:
            raise_error("ERR_VALIDATION_FAILED", "market_rate_cents_per_hour must be > 0")

        deal = make_entity("NILDeal", {
            "athlete_id": athlete_id,
            "sponsor_name": sponsor_name,
            "sponsor_is_booster": bool(sponsor_is_booster),
            "deal_category": deal_category,
            "stated_value_cents": int(stated_value),
            "deliverables_hours": float(deliverables_hours),
            "market_rate_cents_per_hour": int(market_rate),
            "fmv_calculated_cents": 0,
            "pay_for_play_flag": False,
            "approved_value_cents": None,
            "status": "SUBMITTED",
            "review_started_at": None,
            "_submitter_user_id": g.user_id,  # private — for SoD
            "_reviewer_user_id": None,
        })
        _recompute_deal_derivations(deal)
        STORE.nil_deals[deal["id"]] = deal
        return success_object(_serialize_deal(deal), status=201)


def _serialize_deal(d):
    out = dict(d)
    out.pop("_submitter_user_id", None)
    out.pop("_reviewer_user_id", None)
    out.pop("_seq", None)
    return out


@bp.route("/nil-deals/<deal_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Athlete", "Auditor")
def get_deal(deal_id):
    with lock():
        d = STORE.nil_deals.get(deal_id)
        if not d:
            raise_error("ERR_NOT_FOUND", "NILDeal not found")
        if g.user_role == "Athlete" and d.get("athlete_id") != g.user_id:
            raise_error("ERR_FORBIDDEN", "Athlete may only read own deals")
        return success_object(_serialize_deal(d))


@bp.route("/nil-deals", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor", "Athlete", "Booster")
def list_deals():
    limit, offset = parse_pagination(request)
    athlete_id = request.args.get("athlete_id")
    status = request.args.get("status")
    p4p = request.args.get("pay_for_play_flag")

    with lock():
        items = list(STORE.nil_deals.values())
        if g.user_role == "Athlete":
            items = [d for d in items if d.get("athlete_id") == g.user_id]
        elif g.user_role == "Booster":
            items = [d for d in items if d.get("_submitter_user_id") == g.user_id]
        if athlete_id:
            items = [d for d in items if d.get("athlete_id") == athlete_id]
        if status:
            items = [d for d in items if d.get("status") == status]
        if p4p is not None:
            want = p4p.lower() == "true"
            items = [d for d in items if bool(d.get("pay_for_play_flag")) == want]
        items.sort(key=lambda d: (d["created_at"], d["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array([_serialize_deal(d) for d in page], limit, offset, total)


@bp.route("/nil-deals/<deal_id>", methods=["PATCH"])
@require_roles("Athlete", "Booster", "ComplianceOfficer")
def patch_deal(deal_id):
    body = require_body(request)
    with lock():
        d = STORE.nil_deals.get(deal_id)
        if not d:
            raise_error("ERR_NOT_FOUND", "NILDeal not found")

        # Athlete ownership
        if g.user_role == "Athlete" and d.get("athlete_id") != g.user_id:
            raise_error("ERR_FORBIDDEN", "Athlete may only edit own deals")
        # State must be SUBMITTED
        if d["status"] != "SUBMITTED":
            raise_error("ERR_INVALID_STATE", "Deal not in SUBMITTED state")
        # OCC
        check_version(body, d["version"])

        # Update permitted fields
        if "deliverables_hours" in body and body["deliverables_hours"] is not None:
            v = body["deliverables_hours"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or float(v) <= 0:
                raise_error("ERR_VALIDATION_FAILED", "deliverables_hours must be > 0")
            d["deliverables_hours"] = float(v)
        if "market_rate_cents_per_hour" in body and body["market_rate_cents_per_hour"] is not None:
            v = body["market_rate_cents_per_hour"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise_error("ERR_VALIDATION_FAILED", "market_rate_cents_per_hour must be > 0")
            d["market_rate_cents_per_hour"] = int(v)
        if "stated_value_cents" in body and body["stated_value_cents"] is not None:
            v = body["stated_value_cents"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise_error("ERR_VALIDATION_FAILED", "stated_value_cents must be > 0")
            d["stated_value_cents"] = int(v)

        _recompute_deal_derivations(d)
        mark_mutated(d)
        return success_object(_serialize_deal(d))


@bp.route("/nil-deals/<deal_id>/state", methods=["POST"])
@require_roles("ComplianceOfficer")
def transition_deal(deal_id):
    body = require_body(request)
    to_status = require_enum(body, "to_status", VALID_STATUSES)

    with lock():
        d = STORE.nil_deals.get(deal_id)
        if not d:
            raise_error("ERR_NOT_FOUND", "NILDeal not found")
        cur = d["status"]
        valid = {
            ("SUBMITTED", "UNDER_REVIEW"),
            ("UNDER_REVIEW", "APPROVED"),
            ("UNDER_REVIEW", "REJECTED"),
            ("APPROVED", "SUSPENDED"),
            ("APPROVED", "REVOKED"),
            ("SUSPENDED", "APPROVED"),
        }
        if (cur, to_status) not in valid:
            raise_error("ERR_INVALID_STATE", f"Invalid transition {cur} -> {to_status}")

        # OCC priority 7
        check_version(body, d["version"])

        # Segregation of duties priority 8
        if (cur, to_status) == ("SUBMITTED", "UNDER_REVIEW"):
            if g.user_id == d.get("_submitter_user_id"):
                raise_error("ERR_SEGREGATION_OF_DUTIES", "Submitter cannot review own deal")

        athlete = STORE.athletes.get(d["athlete_id"])

        if (cur, to_status) == ("SUBMITTED", "UNDER_REVIEW"):
            d["status"] = "UNDER_REVIEW"
            d["review_started_at"] = CLOCK.now_iso()
            d["_reviewer_user_id"] = g.user_id
            mark_mutated(d)
            return success_object(_serialize_deal(d))

        if (cur, to_status) == ("UNDER_REVIEW", "APPROVED"):
            # Priority 10 (amateur status), 11 (pay-for-play), business: athlete_not_enrolled
            # Order per §2.8:
            # 9 elig (N/A here), 10 amateur, 11 pay_for_play, then ERR_ATHLETE_NOT_ENROLLED
            # Re-read PRD §3.6: pay-for-play check first per §2.8 priority 11; amateur lost priority 10; athlete_enrolled comes after.
            # Per §3.6 prose: pay_for_play must be false, athlete COMMITTED|ENROLLED, amateur AMATEUR.
            # §2.8 order: amateur (10) -> pay_for_play (11) -> business (athlete not enrolled is implicit business)
            if athlete is None:
                raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")
            if athlete.get("amateur_status") != "AMATEUR":
                raise_error("ERR_AMATEUR_STATUS_LOST", "Athlete amateur_status lost")
            if d.get("pay_for_play_flag"):
                raise_error("ERR_PAY_FOR_PLAY_DETECTED", "Deal flagged pay-for-play")
            if athlete.get("status") not in ("COMMITTED", "ENROLLED"):
                raise_error("ERR_ATHLETE_NOT_ENROLLED", "Athlete is not COMMITTED or ENROLLED")
            d["status"] = "APPROVED"
            d["approved_value_cents"] = min(int(d["stated_value_cents"]), int(d["fmv_calculated_cents"]))
            mark_mutated(d)
            recompute_athlete_nil_lifetime(d["athlete_id"])
            return success_object(_serialize_deal(d))

        if (cur, to_status) == ("UNDER_REVIEW", "REJECTED"):
            d["status"] = "REJECTED"
            mark_mutated(d)
            return success_object(_serialize_deal(d))

        if (cur, to_status) == ("APPROVED", "SUSPENDED"):
            d["status"] = "SUSPENDED"
            mark_mutated(d)
            recompute_athlete_nil_lifetime(d["athlete_id"])
            return success_object(_serialize_deal(d))

        if (cur, to_status) == ("SUSPENDED", "APPROVED"):
            if athlete is None:
                raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")
            if athlete.get("amateur_status") != "AMATEUR":
                raise_error("ERR_AMATEUR_STATUS_LOST", "Athlete amateur_status lost")
            if athlete.get("status") not in ("COMMITTED", "ENROLLED"):
                raise_error("ERR_ATHLETE_NOT_ENROLLED", "Athlete is not COMMITTED or ENROLLED")
            d["status"] = "APPROVED"
            mark_mutated(d)
            recompute_athlete_nil_lifetime(d["athlete_id"])
            return success_object(_serialize_deal(d))

        if (cur, to_status) == ("APPROVED", "REVOKED"):
            # Requires linked SUSTAINED NIL_COLLECTIVE_PAYFORPLAY violation
            # Match by related_deal_id or related_athlete_id with violation_type NIL_COLLECTIVE_PAYFORPLAY
            aid = d["athlete_id"]
            has_link = any(
                v.get("violation_type") == "NIL_COLLECTIVE_PAYFORPLAY"
                and v.get("outcome") == "SUSTAINED"
                and (v.get("related_deal_id") == d["id"] or v.get("related_athlete_id") == aid)
                for v in STORE.compliance_violations.values()
            )
            if not has_link:
                raise_error(
                    "ERR_NO_SUSTAINED_VIOLATION",
                    "No SUSTAINED NIL_COLLECTIVE_PAYFORPLAY violation linked to this deal",
                )
            d["status"] = "REVOKED"
            mark_mutated(d)
            recompute_athlete_nil_lifetime(d["athlete_id"])
            return success_object(_serialize_deal(d))
