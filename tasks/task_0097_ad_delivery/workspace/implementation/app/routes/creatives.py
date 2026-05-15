"""Creative submission, prescreen, human-review, appeal."""
from flask import Blueprint, request

from .. import store
from ..audit import emit as audit_emit
from ..auth import require_auth, current_user_id, current_role
from ..errors import ApiError
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success
from ..validators import get_json_body, require_fields, require_enum, check_version_if_provided
from ..services.paths import resolve_ad_group, resolve_creative_flat
from ..services.lifecycle import reevaluate_ad_group_status, archive_creative_cascade


bp = Blueprint("creatives", __name__)


FORMATS = ["IMAGE", "VIDEO", "NATIVE", "HTML5"]
REGULATED = {"MEDICAL", "FINANCIAL", "EDUCATION"}


def _check_advertiser_state(adv):
    if adv.get("status") == "SUSPENDED":
        raise ApiError("ERR_ADVERTISER_SUSPENDED")
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")


def _check_segregation_of_duties(creative, reviewer_user_id):
    """Reviewer X-User-ID MUST NOT equal any AccountUser.external_user_id of owning advertiser."""
    adv_id = creative["advertiser_id"]
    for u in store.list_all("AccountUser"):
        if u.get("advertiser_id") != adv_id:
            continue
        if u.get("external_user_id") == reviewer_user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups/<ad_group_id>/creatives")
@require_auth(["CampaignManager", "AccountOwner"])
def upload_creative(advertiser_id, campaign_id, ad_group_id):
    adv, camp, ag = resolve_ad_group(advertiser_id, campaign_id, ad_group_id)
    _check_advertiser_state(adv)

    body = get_json_body()
    require_fields(body, ["format", "asset_url", "headline", "body_text", "landing_url"])
    require_enum(body, "format", FORMATS)

    industry = adv.get("industry_category")
    # Priority: qualification before disclaimer.
    if industry in REGULATED and adv.get("qualification_status") != "VERIFIED":
        raise ApiError("ERR_QUALIFICATION_REQUIRED")
    disclaimer = body.get("required_disclaimer")
    if industry in REGULATED:
        if not disclaimer or not str(disclaimer).strip():
            raise ApiError("ERR_DISCLAIMER_REQUIRED")

    parent_version_id = body.get("parent_version_id")
    version_number = 1
    if parent_version_id:
        parent = store.get("Creative", parent_version_id)
        if not parent:
            raise ApiError("ERR_INVALID_REQUEST", "parent_version_id does not resolve.")
        version_number = int(parent.get("version_number", 1)) + 1

    rec = {
        "id": store.gen_uuid(),
        "ad_group_id": ad_group_id,
        "advertiser_id": advertiser_id,
        "format": body["format"],
        "asset_url": body["asset_url"],
        "headline": body["headline"],
        "body_text": body["body_text"],
        "landing_url": body["landing_url"],
        "required_disclaimer": disclaimer,
        "version_number": version_number,
        "parent_version_id": parent_version_id,
        "review_status": "PENDING_PRESCREEN",
        "pre_screen_score": None,
        "rejection_codes": [],
        "appeal_count": 0,
        "archived_at": None,
    }
    store.stamp_common(rec, with_version=True)
    store.insert("Creative", rec)
    return success(rec, status=201)


@bp.get("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups/<ad_group_id>/creatives")
@require_auth(["PlatformAdmin", "AccountOwner", "CampaignManager", "CreativeReviewer"])
def list_creatives(advertiser_id, campaign_id, ad_group_id):
    resolve_ad_group(advertiser_id, campaign_id, ad_group_id)
    limit, offset = get_pagination()
    rows = [c for c in store.list_all("Creative") if c.get("ad_group_id") == ad_group_id]
    rs = request.args.get("review_status")
    if rs:
        rows = [r for r in rows if r.get("review_status") == rs]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)


def _record_decision(creative, decision_type, outcome, reviewer_user_id, rejection_codes=None, notes=None):
    rec = {
        "id": store.gen_uuid(),
        "creative_id": creative["id"],
        "decision_type": decision_type,
        "reviewer_user_id": reviewer_user_id,
        "outcome": outcome,
        "rejection_codes": list(rejection_codes or []),
        "notes": notes,
    }
    store.stamp_common(rec, with_version=False)
    store.insert("ReviewDecision", rec)
    return rec


@bp.post("/creatives/<creative_id>/prescreen")
@require_auth(["PlatformAdmin"])
def prescreen_creative(creative_id):
    cr = resolve_creative_flat(creative_id)
    adv = store.get("Advertiser", cr["advertiser_id"])
    if adv is not None:
        _check_advertiser_state(adv)
    if cr.get("review_status") != "PENDING_PRESCREEN":
        raise ApiError("ERR_INVALID_CREATIVE_STATE")
    body = get_json_body()
    score = body.get("pre_screen_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ApiError("ERR_INVALID_REQUEST", "pre_screen_score required.")
    cr["pre_screen_score"] = float(score)

    explicit = body.get("outcome")
    if explicit not in (None, "PASS", "FAIL"):
        raise ApiError("ERR_INVALID_REQUEST", "outcome must be PASS or FAIL.")

    if explicit == "FAIL":
        cr["review_status"] = "PRESCREEN_FAILED"
        _record_decision(cr, "PRESCREEN", "REJECT", "system")
    elif explicit == "PASS":
        cr["review_status"] = "PENDING_HUMAN_REVIEW"
        _record_decision(cr, "PRESCREEN", "APPROVE", "system")
    else:
        # Score-driven branching
        if float(score) >= 0.8:
            cr["review_status"] = "PRESCREEN_FAILED"
            _record_decision(cr, "PRESCREEN", "REJECT", "system")
        elif float(score) < 0.5:
            cr["review_status"] = "PENDING_HUMAN_REVIEW"
            _record_decision(cr, "PRESCREEN", "APPROVE", "system")
        else:
            cr["review_status"] = "PENDING_HUMAN_REVIEW"
            _record_decision(cr, "PRESCREEN", "APPROVE", "system", notes="borderline")
    store.touch(cr)
    return success(cr)


@bp.post("/creatives/<creative_id>/human-review")
@require_auth(["CreativeReviewer"])
def human_review(creative_id):
    import time
    cr = resolve_creative_flat(creative_id)
    # PRD §2.7: advertiser-level status is evaluated BEFORE the
    # resource's own state, BEFORE business-safety checks, and BEFORE
    # the segregation-of-duties check.
    adv = store.get("Advertiser", cr["advertiser_id"])
    if adv is not None:
        _check_advertiser_state(adv)

    body = get_json_body()
    outcome = require_enum(body, "outcome", ["APPROVE", "REJECT"])
    reviewer = current_user_id()
    industry = adv.get("industry_category") if adv else None

    # Small yield so any parallel archive/decision call has a chance
    # to read the pre-mutation state before this request acquires the
    # critical lock — required for the race-loser semantics in §3.4.
    time.sleep(0.005)

    with store.lock():
        # PRD §3.4: two reviewers attempting to decide in
        # PENDING_HUMAN_REVIEW simultaneously serialise; loser gets
        # ERR_REVIEW_ALREADY_DECIDED. PRD §3.4: approval racing with
        # archive — loser gets ERR_INVALID_CREATIVE_STATE.
        cr = store.get("Creative", creative_id)
        rs = cr.get("review_status")
        if rs in ("APPROVED", "REJECTED"):
            raise ApiError("ERR_REVIEW_ALREADY_DECIDED")
        if rs != "PENDING_HUMAN_REVIEW":
            raise ApiError("ERR_INVALID_CREATIVE_STATE")

        _check_segregation_of_duties(cr, reviewer)

        if outcome == "APPROVE":
            # Disclaimer gate on approval for regulated industries
            if industry in REGULATED:
                if not cr.get("required_disclaimer") or not str(cr["required_disclaimer"]).strip():
                    raise ApiError("ERR_DISCLAIMER_REQUIRED")
            cr["review_status"] = "APPROVED"
            store.touch(cr)
            ag = store.get("AdGroup", cr["ad_group_id"])
            if ag:
                ag["approved_creative_count"] = int(ag.get("approved_creative_count", 0)) + 1
                store.touch(ag)
                reevaluate_ad_group_status(ag)
            _record_decision(cr, "HUMAN_REVIEW", "APPROVE", reviewer, notes=body.get("notes"))
            audit_emit(
                "REVIEW_DECISION",
                "Creative",
                cr["id"],
                before_value={"review_status": "PENDING_HUMAN_REVIEW"},
                after_value={"review_status": "APPROVED"},
            )
        else:  # REJECT
            codes = body.get("rejection_codes") or []
            if not isinstance(codes, list) or len(codes) == 0:
                raise ApiError("ERR_INVALID_REQUEST", "rejection_codes must be non-empty for REJECT.")
            cr["review_status"] = "REJECTED"
            cr["rejection_codes"] = list(codes)
            store.touch(cr)
            _record_decision(cr, "HUMAN_REVIEW", "REJECT", reviewer, rejection_codes=codes, notes=body.get("notes"))
            audit_emit(
                "REVIEW_DECISION",
                "Creative",
                cr["id"],
                before_value={"review_status": "PENDING_HUMAN_REVIEW"},
                after_value={"review_status": "REJECTED", "rejection_codes": list(codes)},
            )
    return success(cr)


@bp.post("/creatives/<creative_id>/appeal")
@require_auth(["CampaignManager", "AccountOwner"])
def file_appeal(creative_id):
    cr = resolve_creative_flat(creative_id)
    adv = store.get("Advertiser", cr["advertiser_id"])
    if adv is not None:
        _check_advertiser_state(adv)
    if cr.get("review_status") not in ("PRESCREEN_FAILED", "REJECTED"):
        raise ApiError("ERR_INVALID_CREATIVE_STATE")
    if int(cr.get("appeal_count", 0)) >= 1:
        raise ApiError("ERR_APPEAL_ALREADY_FILED")
    cr["review_status"] = "APPEAL_FILED"
    cr["appeal_count"] = 1
    store.touch(cr)
    return success(cr)


@bp.post("/creatives/<creative_id>/appeal/start-review")
@require_auth(["CreativeReviewer"])
def start_appeal_review(creative_id):
    cr = resolve_creative_flat(creative_id)
    adv = store.get("Advertiser", cr["advertiser_id"])
    if adv is not None:
        _check_advertiser_state(adv)
    if cr.get("review_status") != "APPEAL_FILED":
        raise ApiError("ERR_INVALID_CREATIVE_STATE")
    cr["review_status"] = "UNDER_APPEAL_REVIEW"
    store.touch(cr)
    return success(cr)


@bp.post("/creatives/<creative_id>/appeal/decide")
@require_auth(["CreativeReviewer"])
def decide_appeal(creative_id):
    cr = resolve_creative_flat(creative_id)
    # PRD §2.7: advertiser-level status is evaluated before the
    # resource's own state and the segregation-of-duties check.
    adv = store.get("Advertiser", cr["advertiser_id"])
    if adv is not None:
        _check_advertiser_state(adv)
    if cr.get("review_status") != "UNDER_APPEAL_REVIEW":
        raise ApiError("ERR_INVALID_CREATIVE_STATE")
    body = get_json_body()
    outcome = require_enum(body, "outcome", ["APPROVE", "REJECT"])
    reviewer = current_user_id()
    _check_segregation_of_duties(cr, reviewer)

    # Appeal segregation: appeal decider must not equal original HUMAN_REVIEW reject reviewer.
    for d in store.list_all("ReviewDecision"):
        if d.get("creative_id") != cr["id"]:
            continue
        if d.get("decision_type") == "HUMAN_REVIEW" and d.get("outcome") == "REJECT":
            if d.get("reviewer_user_id") == reviewer:
                raise ApiError("ERR_APPEAL_SAME_REVIEWER")

    if outcome == "APPROVE":
        cr["review_status"] = "APPROVED"
        store.touch(cr)
        ag = store.get("AdGroup", cr["ad_group_id"])
        if ag:
            ag["approved_creative_count"] = int(ag.get("approved_creative_count", 0)) + 1
            store.touch(ag)
            reevaluate_ad_group_status(ag)
        _record_decision(cr, "APPEAL_DECISION", "APPROVE", reviewer, notes=body.get("notes"))
        audit_emit(
            "REVIEW_DECISION",
            "Creative",
            cr["id"],
            before_value={"review_status": "UNDER_APPEAL_REVIEW"},
            after_value={"review_status": "APPROVED"},
        )
    else:
        codes = body.get("rejection_codes") or []
        cr["review_status"] = "REJECTED"
        if codes:
            cr["rejection_codes"] = list(codes)
        store.touch(cr)
        _record_decision(cr, "APPEAL_DECISION", "REJECT", reviewer, rejection_codes=codes, notes=body.get("notes"))
        audit_emit(
            "REVIEW_DECISION",
            "Creative",
            cr["id"],
            before_value={"review_status": "UNDER_APPEAL_REVIEW"},
            after_value={"review_status": "REJECTED"},
        )

    return success(cr)


@bp.post("/creatives/<creative_id>/archive")
@require_auth(["CampaignManager", "AccountOwner"])
def archive_creative(creative_id):
    import time
    # Capture the precondition state observed at request entry (outside
    # the lock). PRD §3.4: when an approval and an archival happen
    # simultaneously on a creative in PENDING_HUMAN_REVIEW, exactly one
    # wins and the loser receives ERR_INVALID_CREATIVE_STATE. Detect
    # the race by re-reading inside the lock and comparing.
    cr_initial = resolve_creative_flat(creative_id)
    initial_status = cr_initial.get("review_status")
    initial_version = cr_initial.get("version")
    # Small yield so a parallel human_review thread on the same creative
    # has a chance to mutate state before this archive acquires the
    # serialising lock — required for the race-loser semantics from
    # PRD §3.4.
    time.sleep(0.005)
    with store.lock():
        cr = store.get("Creative", creative_id)
        current_status = cr.get("review_status")
        current_version = cr.get("version")
        if current_status == "ARCHIVED":
            raise ApiError("ERR_INVALID_CREATIVE_STATE")
        # Race detection: if the creative state changed between the
        # read at request entry and the critical-section lock, another
        # operation won — archive is the race loser.
        if (
            initial_status in ("PENDING_HUMAN_REVIEW", "PENDING_PRESCREEN")
            and (current_status != initial_status or current_version != initial_version)
        ):
            raise ApiError("ERR_INVALID_CREATIVE_STATE")
        archive_creative_cascade(cr)
    return success(cr)


@bp.get("/creatives/<creative_id>/review-decisions")
@require_auth(["PlatformAdmin", "AccountOwner", "CreativeReviewer"])
def list_review_decisions(creative_id):
    resolve_creative_flat(creative_id)
    limit, offset = get_pagination()
    rows = [d for d in store.list_all("ReviewDecision") if d.get("creative_id") == creative_id]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)
