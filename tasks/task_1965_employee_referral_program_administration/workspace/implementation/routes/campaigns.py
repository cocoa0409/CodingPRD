"""Campaign lifecycle: DRAFT / ACTIVE / PAUSED / EXHAUSTED / ENDED / CANCELLED,
with OCC-guarded edits and closed-window overlap enforcement."""

from flask import Blueprint, request

from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_STALE_VERSION,
                    ERR_NO_ACTIVE_POLICY, ERR_CAMPAIGN_WINDOW_CONFLICT,
                    ERR_CAMPAIGN_WINDOW_EXPIRED, ERR_CAMPAIGN_BUDGET_EXCEEDED)
from middleware import require_role
import services as svc
from services import new_entity, touch
from util import (req_str, opt_str, req_int, opt_int, req_dt, respond_object,
                  respond_list, parse_pagination, paginate, is_int)
from views import campaign_view

bp = Blueprint("campaigns", __name__)

READ_ROLES = ("PlatformAdmin", "TalentAdmin", "Recruiter", "HiringManager",
              "PayrollProcessor", "ComplianceOfficer")

# Campaigns in these states block overlapping windows for the same requisition.
OVERLAP_STATES = ("DRAFT", "ACTIVE", "PAUSED", "EXHAUSTED")


def _get_campaign(campaign_id):
    c = store.campaigns.get(campaign_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Campaign not found")
    return c


def _check_window_overlap(job_requisition_id, window_start, window_end, exclude_id=None):
    """Closed-interval semantics: touching endpoints DO overlap."""
    for c in store.campaigns.values():
        if c["id"] == exclude_id:
            continue
        if c["job_requisition_id"] != job_requisition_id:
            continue
        if c["status"] not in OVERLAP_STATES:
            continue
        if window_start <= c["window_end"] and c["window_start"] <= window_end:
            raise ApiError(ERR_CAMPAIGN_WINDOW_CONFLICT, 409,
                           "Campaign window overlaps another campaign for this requisition")


@bp.post("/erp/campaigns")
def create_campaign():
    body = request.get_json(silent=True) or {}
    name = req_str(body, "name")
    job_requisition_id = req_str(body, "job_requisition_id")
    multiplier_bps = req_int(body, "multiplier_bps")
    flat_addon_cents = req_int(body, "flat_addon_cents")
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    budget_cents = req_int(body, "budget_cents")
    max_payouts = opt_int(body, "max_payouts", None)
    require_role("TalentAdmin")
    if job_requisition_id not in store.requisitions:
        raise ApiError(ERR_NOT_FOUND, 404, "Job requisition not found")
    _check_window_overlap(job_requisition_id, window_start, window_end)
    c = new_entity(store.campaigns, {
        "name": name,
        "job_requisition_id": job_requisition_id,
        "multiplier_bps": multiplier_bps,
        "flat_addon_cents": flat_addon_cents,
        "window_start": window_start,
        "window_end": window_end,
        "budget_cents": budget_cents,
        "max_payouts": max_payouts,
        "reserved_cents": 0,
        "spent_cents": 0,
        "status": "DRAFT",
    })
    return respond_object(campaign_view(c), status=201)


@bp.get("/erp/campaigns")
def list_campaigns():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.campaigns.values())
    status = request.args.get("status")
    req_id = request.args.get("job_requisition_id")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if req_id is not None:
        items = [c for c in items if c["job_requisition_id"] == req_id]
    page, total = paginate(items, limit, offset)
    return respond_list([campaign_view(c) for c in page], total, limit, offset)


@bp.get("/erp/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    require_role(*READ_ROLES)
    return respond_object(campaign_view(_get_campaign(campaign_id)))


@bp.patch("/erp/campaigns/<campaign_id>")
def patch_campaign(campaign_id):
    body = request.get_json(silent=True) or {}
    # Step 2: shape — expected_campaign_version is non-optional (PRD 2.7).
    expected = body.get("expected_campaign_version")
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_campaign_version is required and must be an integer")
    new_fields = {}
    if "name" in body:
        new_fields["name"] = req_str(body, "name")
    for fname in ("multiplier_bps", "flat_addon_cents", "budget_cents"):
        if fname in body:
            new_fields[fname] = req_int(body, fname)
    if "max_payouts" in body:
        new_fields["max_payouts"] = opt_int(body, "max_payouts", None)
    window_edited = False
    if "window_start" in body:
        new_fields["window_start"] = req_dt(body, "window_start")
        window_edited = True
    if "window_end" in body:
        new_fields["window_end"] = req_dt(body, "window_end")
        window_edited = True
    require_role("TalentAdmin")
    c = _get_campaign(campaign_id)
    # State legality: edits permitted only from DRAFT / ACTIVE / PAUSED.
    if c["status"] in svc.CAMPAIGN_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Campaign is in terminal state %s" % c["status"])
    if c["status"] == "EXHAUSTED":
        raise ApiError(ERR_INVALID_STATE, 409, "An EXHAUSTED campaign cannot be edited")
    # OCC (PRD 2.7): stale check before the window-overlap and budget rules.
    if expected != c["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_campaign_version %s does not match current version %s"
                       % (expected, c["version"]))
    # Window edits re-run the closed-interval overlap check.
    if window_edited:
        _check_window_overlap(c["job_requisition_id"],
                              new_fields.get("window_start", c["window_start"]),
                              new_fields.get("window_end", c["window_end"]),
                              exclude_id=c["id"])
    # Budget floor: may not drop below what is already spoken for.
    if "budget_cents" in new_fields:
        if new_fields["budget_cents"] < c["reserved_cents"] + c["spent_cents"]:
            raise ApiError(ERR_CAMPAIGN_BUDGET_EXCEEDED, 422,
                           "budget_cents may not be lower than reserved_cents + spent_cents")
    for k, v in new_fields.items():
        c[k] = v
    touch(c)
    return respond_object(campaign_view(c))


@bp.post("/erp/campaigns/<campaign_id>/activate")
def activate_campaign(campaign_id):
    require_role("TalentAdmin")
    c = _get_campaign(campaign_id)
    if c["status"] in svc.CAMPAIGN_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Campaign is in terminal state %s" % c["status"])
    if c["status"] == "DRAFT":
        # Gate 1: an ACTIVE policy must exist. Gate 2: window not elapsed.
        if svc.active_policy() is None:
            raise ApiError(ERR_NO_ACTIVE_POLICY, 422, "No ACTIVE policy version exists")
        if c["window_end"] < store.clock:
            raise ApiError(ERR_CAMPAIGN_WINDOW_EXPIRED, 422,
                           "Campaign window has already elapsed")
    elif c["status"] == "PAUSED":
        # Re-activation re-checks only the window.
        if c["window_end"] < store.clock:
            raise ApiError(ERR_CAMPAIGN_WINDOW_EXPIRED, 422,
                           "Campaign window has already elapsed")
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Campaign cannot be activated from %s" % c["status"])
    c["status"] = "ACTIVE"
    touch(c)
    return respond_object(campaign_view(c))


@bp.post("/erp/campaigns/<campaign_id>/pause")
def pause_campaign(campaign_id):
    require_role("TalentAdmin")
    c = _get_campaign(campaign_id)
    if c["status"] in svc.CAMPAIGN_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Campaign is in terminal state %s" % c["status"])
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE campaign can be paused (currently %s)" % c["status"])
    c["status"] = "PAUSED"
    touch(c)
    return respond_object(campaign_view(c))


@bp.post("/erp/campaigns/<campaign_id>/end")
def end_campaign(campaign_id):
    require_role("TalentAdmin")
    c = _get_campaign(campaign_id)
    if c["status"] in svc.CAMPAIGN_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Campaign is in terminal state %s" % c["status"])
    # DRAFT / ACTIVE / PAUSED / EXHAUSTED -> CANCELLED with reservation release.
    svc.end_campaign_releases(c)
    c["status"] = "CANCELLED"
    touch(c)
    return respond_object(campaign_view(c))
