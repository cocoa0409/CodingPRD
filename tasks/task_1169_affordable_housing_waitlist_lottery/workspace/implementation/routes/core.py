"""All API route handlers."""

from datetime import timedelta

import db
import errors
import helpers as H
import response as R
import services as S
from middleware import authenticate, require_roles, require_action_role, STAFF_ROLES

from . import bp

BEDROOM_COUNTS = {"STUDIO", "ONE_BR", "TWO_BR", "THREE_BR"}
AMI_TIERS = {"AMI_30", "AMI_50", "AMI_60", "AMI_80"}
ACCESSIBILITY_FEATURES = {"NONE", "MOBILITY", "HEARING_VISION"}
MARKETING_CHANNELS = {
    "COMMUNITY_MEETING",
    "LOCAL_NEWSPAPER",
    "SOCIAL_MEDIA",
    "HOUSING_AUTHORITY_WEBSITE",
    "MAILERS",
}
PREFERENCE_CATEGORIES = {"LOCAL_RESIDENT", "VETERAN", "ACCESSIBILITY"}
PERIOD_MODES = {"CALENDAR_QUARTER", "ROLLING_90_DAY"}

STAFF = STAFF_ROLES  # alias


def _pub(rec):
    """Return a JSON-serializable shallow copy."""
    return dict(rec)


# =====================================================================
# Logical clock
# =====================================================================

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    to_dt = H.req_datetime(body, "to_iso8601")
    db.set_current_utc(to_dt)
    return R.success({"current_utc": db.get_current_utc()})


# =====================================================================
# Properties
# =====================================================================

@bp.route("/properties", methods=["POST"])
def create_property():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    name = H.req_str(body, "name")
    address_line = H.req_str(body, "address_line")
    city = H.req_str(body, "city")
    state_code = H.req_str(body, "state_code")
    rec = db.new_record()
    rec.update(
        {
            "name": name,
            "address_line": address_line,
            "city": city,
            "state_code": state_code,
            "units_total": 0,
            "units_available_count": 0,
            "units_reserved_count": 0,
            "units_leased_count": 0,
            "units_out_of_service_count": 0,
        }
    )
    db.store.properties[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


@bp.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.properties, pid, "property")
    H.recompute_property_counters(pid)
    return R.success(_pub(rec))


# =====================================================================
# Units
# =====================================================================

@bp.route("/units", methods=["POST"])
def create_unit():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    property_id = body.get("property_id")
    if not isinstance(property_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "property_id required")
    unit_number = H.req_str(body, "unit_number")
    bedroom_count = H.req_enum(body, "bedroom_count", BEDROOM_COUNTS)
    ami_tier = H.req_enum(body, "ami_tier", AMI_TIERS)
    accessibility_feature = H.opt_enum(body, "accessibility_feature", ACCESSIBILITY_FEATURES, "NONE")
    H.must_exist(db.store.properties, property_id, "property")

    rec = db.new_record()
    rec.update(
        {
            "property_id": property_id,
            "unit_number": unit_number,
            "bedroom_count": bedroom_count,
            "ami_tier": ami_tier,
            "accessibility_feature": accessibility_feature,
            "status": "AVAILABLE",
        }
    )
    db.store.units[rec["id"]] = rec
    H.recompute_property_counters(property_id)
    return R.success(_pub(rec), status=201)


@bp.route("/units", methods=["GET"])
def list_units():
    caller = authenticate()
    require_roles(caller, STAFF)
    items = list(db.store.units.values())
    pid = _q("property_id")
    status = _q("status")
    br = _q("bedroom_count")
    if pid is not None:
        items = [u for u in items if u["property_id"] == pid]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    if br is not None:
        items = [u for u in items if u["bedroom_count"] == br]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(u) for u in page], limit, offset, total)


@bp.route("/units/<uid>", methods=["GET"])
def get_unit(uid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.units, uid, "unit")
    return R.success(_pub(rec))


@bp.route("/units/<uid>/service", methods=["POST"])
def unit_service(uid):
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"PLACE_OUT_OF_SERVICE", "RETURN_TO_SERVICE"})
    unit = H.must_exist(db.store.units, uid, "unit")
    if action == "PLACE_OUT_OF_SERVICE":
        if unit["status"] != "AVAILABLE":
            raise errors.err(errors.ERR_INVALID_STATE, "unit is not AVAILABLE")
        pend = [
            o
            for o in db.store.unit_offers.values()
            if o["unit_id"] == uid and o["status"] == "PENDING"
        ]
        if pend:
            raise errors.err(errors.ERR_INVALID_STATE, "unit has a PENDING offer")
        unit["status"] = "OUT_OF_SERVICE"
    else:
        if unit["status"] != "OUT_OF_SERVICE":
            raise errors.err(errors.ERR_INVALID_STATE, "unit is not OUT_OF_SERVICE")
        unit["status"] = "AVAILABLE"
    db.touch(unit)
    H.recompute_property_counters(unit["property_id"])
    return R.success(_pub(unit))


# =====================================================================
# Occupancy standards
# =====================================================================

@bp.route("/occupancy-standards", methods=["POST"])
def create_occupancy_standard():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    property_id = body.get("property_id")
    if not isinstance(property_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "property_id required")
    bedroom_count = H.req_enum(body, "bedroom_count", BEDROOM_COUNTS)
    min_occupants = H.req_int(body, "min_occupants")
    max_occupants = H.req_int(body, "max_occupants")
    if min_occupants < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "min_occupants must be >= 1")
    if max_occupants < min_occupants:
        raise errors.err(errors.ERR_INVALID_REQUEST, "max_occupants must be >= min_occupants")
    H.must_exist(db.store.properties, property_id, "property")
    for r in db.store.occupancy_standards.values():
        if r["property_id"] == property_id and r["bedroom_count"] == bedroom_count:
            raise errors.err(errors.ERR_CONFIG_CONFLICT, "duplicate occupancy standard")
    rec = db.new_record()
    rec.update(
        {
            "property_id": property_id,
            "bedroom_count": bedroom_count,
            "min_occupants": min_occupants,
            "max_occupants": max_occupants,
            "uniqueness_scope": f"{property_id}:{bedroom_count}",
        }
    )
    db.store.occupancy_standards[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


@bp.route("/occupancy-standards", methods=["GET"])
def list_occupancy_standards():
    caller = authenticate()
    require_roles(caller, STAFF)
    items = list(db.store.occupancy_standards.values())
    pid = _q("property_id")
    if pid is not None:
        items = [r for r in items if r["property_id"] == pid]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(r) for r in page], limit, offset, total)


@bp.route("/occupancy-standards/<oid>", methods=["GET"])
def get_occupancy_standard(oid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.occupancy_standards, oid, "occupancy standard")
    return R.success(_pub(rec))


# =====================================================================
# AMI limits
# =====================================================================

@bp.route("/ami-limits", methods=["POST"])
def create_ami_limit():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    property_id = body.get("property_id")
    if not isinstance(property_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "property_id required")
    household_size = H.req_int(body, "household_size")
    ami_tier = H.req_enum(body, "ami_tier", AMI_TIERS)
    annual_limit_cents = H.req_int(body, "annual_limit_cents")
    if not (1 <= household_size <= 12):
        raise errors.err(errors.ERR_INVALID_REQUEST, "household_size out of range")
    if annual_limit_cents <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "annual_limit_cents must be > 0")
    H.must_exist(db.store.properties, property_id, "property")
    for r in db.store.ami_limits.values():
        if (
            r["property_id"] == property_id
            and r["household_size"] == household_size
            and r["ami_tier"] == ami_tier
        ):
            raise errors.err(errors.ERR_CONFIG_CONFLICT, "duplicate AMI limit")
    rec = db.new_record()
    rec.update(
        {
            "property_id": property_id,
            "household_size": household_size,
            "ami_tier": ami_tier,
            "annual_limit_cents": annual_limit_cents,
            "uniqueness_scope": f"{property_id}:{household_size}:{ami_tier}",
        }
    )
    db.store.ami_limits[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


@bp.route("/ami-limits", methods=["GET"])
def list_ami_limits():
    caller = authenticate()
    require_roles(caller, STAFF)
    items = list(db.store.ami_limits.values())
    pid = _q("property_id")
    hs = _q("household_size")
    tier = _q("ami_tier")
    if pid is not None:
        items = [r for r in items if r["property_id"] == pid]
    if hs is not None:
        try:
            hsi = int(hs)
        except ValueError:
            raise errors.err(errors.ERR_INVALID_REQUEST, "invalid household_size filter")
        items = [r for r in items if r["household_size"] == hsi]
    if tier is not None:
        items = [r for r in items if r["ami_tier"] == tier]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(r) for r in page], limit, offset, total)


@bp.route("/ami-limits/<aid>", methods=["GET"])
def get_ami_limit(aid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.ami_limits, aid, "AMI limit")
    return R.success(_pub(rec))


# =====================================================================
# Campaigns
# =====================================================================

def _window_overlaps(property_id, open_at, close_at, exclude_id=None):
    """Half-open overlap against sibling campaigns not PURGED."""
    for c in db.store.campaigns.values():
        if c["property_id"] != property_id:
            continue
        if exclude_id and c["id"] == exclude_id:
            continue
        if c["status"] == "PURGED":
            continue
        other_open = db.parse_iso(c["application_open_at"])
        other_close = db.parse_iso(c["application_close_at"])
        if open_at < other_close and other_open < close_at:
            return True
    return False


@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    property_id = body.get("property_id")
    if not isinstance(property_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "property_id required")
    name = H.req_str(body, "name")
    open_at = H.req_datetime(body, "application_open_at")
    close_at = H.req_datetime(body, "application_close_at")
    channels = H.req_str_list(body, "marketing_channels")
    for ch in channels:
        if ch not in MARKETING_CHANNELS:
            raise errors.err(errors.ERR_INVALID_REQUEST, "invalid marketing channel")
    summary = H.req_str(body, "marketing_plan_summary")
    target_ami_tier = H.opt_enum(body, "target_ami_tier", AMI_TIERS, "AMI_60")
    H.must_exist(db.store.properties, property_id, "property")
    if not (close_at > open_at):
        raise errors.err(errors.ERR_INVALID_REQUEST, "application_close_at must be after application_open_at")
    if _window_overlaps(property_id, open_at, close_at):
        raise errors.err(errors.ERR_CAMPAIGN_WINDOW_OVERLAP, "campaign window overlaps sibling")

    rec = db.new_record()
    rec.update(
        {
            "property_id": property_id,
            "name": name,
            "application_open_at": db.format_iso(open_at),
            "application_close_at": db.format_iso(close_at),
            "marketing_channels": channels,
            "marketing_plan_summary": summary,
            "target_ami_tier": target_ami_tier,
            "status": "DRAFT",
            "applications_received_count": 0,
            "waitlist_active_count": 0,
            "entries_leased_count": 0,
            "reopen_count": 0,
        }
    )
    db.store.campaigns[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


@bp.route("/campaigns", methods=["GET"])
def list_campaigns():
    caller = authenticate()
    require_roles(caller, STAFF)
    items = list(db.store.campaigns.values())
    pid = _q("property_id")
    status = _q("status")
    if pid is not None:
        items = [c for c in items if c["property_id"] == pid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    for c in items:
        H.recompute_campaign_counters(c["id"])
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(c) for c in page], limit, offset, total)


@bp.route("/campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.campaigns, cid, "campaign")
    H.recompute_campaign_counters(cid)
    return R.success(_pub(rec))


@bp.route("/campaigns/<cid>/transition", methods=["POST"])
def campaign_transition(cid):
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper", "MarketingCoordinator"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"ANNOUNCE", "OPEN", "CLOSE", "REOPEN"})
    require_action_role(
        caller,
        action,
        {
            "ANNOUNCE": {"MarketingCoordinator"},
            "OPEN": {"HousingDeveloper"},
            "CLOSE": {"HousingDeveloper"},
            "REOPEN": {"HousingDeveloper"},
        },
    )
    campaign = H.must_exist(db.store.campaigns, cid, "campaign")
    now = db.now_dt()

    if action == "ANNOUNCE":
        if campaign["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "campaign is not DRAFT")
        if len(campaign["marketing_channels"]) < 2:
            raise errors.err(
                errors.ERR_MARKETING_PLAN_INSUFFICIENT, "announcement requires >= 2 channels"
            )
        campaign["status"] = "ANNOUNCED"
    elif action == "OPEN":
        if campaign["status"] != "ANNOUNCED":
            raise errors.err(errors.ERR_INVALID_STATE, "campaign is not ANNOUNCED")
        if now < db.parse_iso(campaign["application_open_at"]):
            raise errors.err(
                errors.ERR_APPLICATION_WINDOW_NOT_OPEN, "application window not yet open"
            )
        campaign["status"] = "OPEN"
    elif action == "CLOSE":
        if campaign["status"] != "OPEN":
            raise errors.err(errors.ERR_INVALID_STATE, "campaign is not OPEN")
        if now < db.parse_iso(campaign["application_close_at"]):
            raise errors.err(errors.ERR_INVALID_STATE, "application window not yet closed")
        campaign["status"] = "CLOSED"
    else:  # REOPEN
        if campaign["status"] != "PURGED":
            raise errors.err(errors.ERR_INVALID_STATE, "campaign is not PURGED")
        new_open = H.req_datetime(body, "new_application_open_at")
        new_close = H.req_datetime(body, "new_application_close_at")
        if not (new_close > new_open):
            raise errors.err(errors.ERR_INVALID_REQUEST, "new close must be after new open")
        if _window_overlaps(campaign["property_id"], new_open, new_close, exclude_id=cid):
            raise errors.err(errors.ERR_CAMPAIGN_WINDOW_OVERLAP, "new window overlaps sibling")
        campaign["application_open_at"] = db.format_iso(new_open)
        campaign["application_close_at"] = db.format_iso(new_close)
        campaign["reopen_count"] = campaign.get("reopen_count", 0) + 1
        campaign["status"] = "OPEN"

    db.touch(campaign)
    return R.success(_pub(campaign))


# =====================================================================
# Applicants
# =====================================================================

@bp.route("/applicants", methods=["POST"])
def create_applicant():
    caller = authenticate()
    require_roles(caller, {"Anonymous"})
    body = H.get_body()
    full_name = H.req_str(body, "full_name")
    email = H.req_str(body, "email")
    rec = db.new_record()
    rec.update({"full_name": full_name, "email": email})
    db.store.applicants[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


@bp.route("/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    rec = H.must_exist(db.store.applicants, aid, "applicant")
    if caller.role == "Applicant" and caller.user_id != aid:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "applicant may only fetch own record")
    return R.success(_pub(rec))


# =====================================================================
# Applications
# =====================================================================

@bp.route("/applications", methods=["POST"])
def create_application():
    caller = authenticate()
    require_roles(caller, {"Applicant"})
    body = H.get_body()
    applicant_id = body.get("applicant_id")
    if not isinstance(applicant_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "applicant_id required")
    campaign_id = body.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "campaign_id required")
    household_size = H.req_int(body, "household_size")
    income = H.req_int(body, "self_reported_annual_income_cents")
    if income < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "income must be >= 0")

    # existence left-to-right: applicant then campaign
    H.must_exist(db.store.applicants, applicant_id, "applicant")
    campaign = H.must_exist(db.store.campaigns, campaign_id, "campaign")

    # ownership: applicant_id must equal X-User-ID
    if caller.user_id != applicant_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "applicant_id must equal X-User-ID")

    # state: campaign must be OPEN
    if campaign["status"] != "OPEN":
        raise errors.err(errors.ERR_CAMPAIGN_NOT_OPEN, "campaign is not OPEN")

    # clock: submit requires now < application_close_at
    if db.now_dt() >= db.parse_iso(campaign["application_close_at"]):
        raise errors.err(errors.ERR_APPLICATION_WINDOW_CLOSED, "application window closed")

    # household size bound
    if not (1 <= household_size <= 12):
        raise errors.err(errors.ERR_HOUSEHOLD_SIZE_INVALID, "household_size must be 1..12")

    # duplicate active application
    for a in db.store.applications.values():
        if (
            a["applicant_id"] == applicant_id
            and a["campaign_id"] == campaign_id
            and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "VERIFIED")
        ):
            raise errors.err(errors.ERR_DUPLICATE_APPLICATION, "active application exists")

    rec = db.new_record()
    rec.update(
        {
            "applicant_id": applicant_id,
            "campaign_id": campaign_id,
            "household_size": household_size,
            "self_reported_annual_income_cents": income,
            "confirmation_code": db.new_id(),
            "provisional_determination": "UNASSESSED",
            "verified_preference_categories": [],
            "status": "SUBMITTED",
            "verified_at": None,
            "rejection_reason": None,
        }
    )
    rec["provisional_determination"] = S.provisional_screen(rec, campaign)
    db.store.applications[rec["id"]] = rec
    H.recompute_campaign_counters(campaign_id)
    return R.success(_pub(rec), status=201)


def _own_applications_only(caller, items):
    if caller.role == "Applicant":
        items = [a for a in items if a["applicant_id"] == caller.user_id]
    return items


@bp.route("/applications", methods=["GET"])
def list_applications():
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    items = list(db.store.applications.values())
    items = _own_applications_only(caller, items)
    cid = _q("campaign_id")
    aid = _q("applicant_id")
    status = _q("status")
    if cid is not None:
        items = [a for a in items if a["campaign_id"] == cid]
    if aid is not None:
        items = [a for a in items if a["applicant_id"] == aid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(a) for a in page], limit, offset, total)


@bp.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    rec = H.must_exist(db.store.applications, aid, "application")
    if caller.role == "Applicant" and rec["applicant_id"] != caller.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "applicant may only fetch own application")
    return R.success(_pub(rec))


@bp.route("/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    caller = authenticate()
    require_roles(caller, {"Applicant"})
    rec = H.must_exist(db.store.applications, aid, "application")
    if rec["applicant_id"] != caller.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "only the owning applicant may withdraw")
    if rec["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
        raise errors.err(errors.ERR_INVALID_STATE, "application not withdrawable")
    rec["status"] = "WITHDRAWN"
    db.touch(rec)
    H.recompute_campaign_counters(rec["campaign_id"])
    return R.success(_pub(rec))


@bp.route("/applications/<aid>/review", methods=["POST"])
def review_application(aid):
    caller = authenticate()
    require_roles(caller, {"ApplicationClerk", "Applicant"})
    body = H.get_body()
    action = H.req_enum(
        body, "action", {"BEGIN_REVIEW", "REQUEST_INFO", "SUBMIT_INFO", "COMPLETE_VERIFICATION", "REJECT"}
    )
    require_action_role(
        caller,
        action,
        {
            "BEGIN_REVIEW": {"ApplicationClerk"},
            "REQUEST_INFO": {"ApplicationClerk"},
            "SUBMIT_INFO": {"Applicant"},
            "COMPLETE_VERIFICATION": {"ApplicationClerk"},
            "REJECT": {"ApplicationClerk"},
        },
    )
    rec = H.must_exist(db.store.applications, aid, "application")

    if action == "BEGIN_REVIEW":
        if rec["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_INVALID_STATE, "application is not SUBMITTED")
        rec["status"] = "UNDER_REVIEW"
    elif action == "REQUEST_INFO":
        if rec["status"] != "UNDER_REVIEW":
            raise errors.err(errors.ERR_INVALID_STATE, "application is not UNDER_REVIEW")
        rec["status"] = "NEEDS_INFO"
    elif action == "SUBMIT_INFO":
        if rec["applicant_id"] != caller.user_id:
            raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "only the owning applicant may submit info")
        if rec["status"] != "NEEDS_INFO":
            raise errors.err(errors.ERR_INVALID_STATE, "application is not NEEDS_INFO")
        rec["status"] = "UNDER_REVIEW"
    elif action == "COMPLETE_VERIFICATION":
        if rec["status"] != "UNDER_REVIEW":
            raise errors.err(errors.ERR_INVALID_STATE, "application is not UNDER_REVIEW")
        pending = [
            c
            for c in db.store.preference_claims.values()
            if c["application_id"] == aid and c["status"] == "PENDING"
        ]
        if pending:
            raise errors.err(errors.ERR_PREFERENCE_CLAIMS_PENDING, "preference claims still PENDING")
        rec["status"] = "VERIFIED"
        rec["verified_at"] = db.now_iso()
        H.recompute_verified_preference_categories(aid)
    else:  # REJECT
        if rec["status"] != "UNDER_REVIEW":
            raise errors.err(errors.ERR_INVALID_STATE, "application is not UNDER_REVIEW")
        reason = body.get("rejection_reason")
        if not isinstance(reason, str) or not reason:
            raise errors.err(errors.ERR_INVALID_REQUEST, "rejection_reason required")
        rec["status"] = "REJECTED"
        rec["rejection_reason"] = reason
        H.recompute_campaign_counters(rec["campaign_id"])

    db.touch(rec)
    if action in ("COMPLETE_VERIFICATION",):
        H.recompute_campaign_counters(rec["campaign_id"])
    return R.success(_pub(rec))


# =====================================================================
# Preference claims
# =====================================================================

@bp.route("/preference-claims", methods=["POST"])
def create_preference_claim():
    caller = authenticate()
    require_roles(caller, {"Applicant"})
    body = H.get_body()
    application_id = body.get("application_id")
    if not isinstance(application_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "application_id required")
    category = H.req_enum(body, "category", PREFERENCE_CATEGORIES)
    evidence_ref = body.get("evidence_ref")
    if evidence_ref is None:
        raise errors.err(errors.ERR_PREFERENCE_EVIDENCE_REQUIRED, "evidence_ref required")
    if not isinstance(evidence_ref, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "evidence_ref must be a string")
    if evidence_ref == "":
        raise errors.err(errors.ERR_PREFERENCE_EVIDENCE_REQUIRED, "evidence_ref must be non-empty")

    app = H.must_exist(db.store.applications, application_id, "application")
    if app["applicant_id"] != caller.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "only the owning applicant may file a claim")
    if app["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
        raise errors.err(errors.ERR_INVALID_STATE, "application not in a reviewable state")

    for c in db.store.preference_claims.values():
        if c["application_id"] == application_id and c["category"] == category:
            raise errors.err(errors.ERR_DUPLICATE_CLAIM, "claim already exists for category")

    rec = db.new_record()
    rec.update(
        {
            "application_id": application_id,
            "category": category,
            "evidence_ref": evidence_ref,
            "status": "PENDING",
            "denial_reason": None,
            "decided_at": None,
            "decided_by": None,
        }
    )
    db.store.preference_claims[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


@bp.route("/preference-claims", methods=["GET"])
def list_preference_claims():
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    items = list(db.store.preference_claims.values())
    if caller.role == "Applicant":
        items = [
            c
            for c in items
            if db.store.applications.get(c["application_id"], {}).get("applicant_id") == caller.user_id
        ]
    aid = _q("application_id")
    status = _q("status")
    category = _q("category")
    if aid is not None:
        items = [c for c in items if c["application_id"] == aid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if category is not None:
        items = [c for c in items if c["category"] == category]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(c) for c in page], limit, offset, total)


@bp.route("/preference-claims/<cid>", methods=["GET"])
def get_preference_claim(cid):
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    rec = H.must_exist(db.store.preference_claims, cid, "preference claim")
    if caller.role == "Applicant":
        app = db.store.applications.get(rec["application_id"])
        if not app or app["applicant_id"] != caller.user_id:
            raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "applicant may only fetch own claims")
    return R.success(_pub(rec))


@bp.route("/preference-claims/<cid>/transition", methods=["POST"])
def transition_preference_claim(cid):
    caller = authenticate()
    require_roles(caller, {"ApplicationClerk", "Applicant"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"VERIFY", "DENY", "APPEAL"})
    require_action_role(
        caller,
        action,
        {
            "VERIFY": {"ApplicationClerk"},
            "DENY": {"ApplicationClerk"},
            "APPEAL": {"Applicant"},
        },
    )
    rec = H.must_exist(db.store.preference_claims, cid, "preference claim")
    app = H.must_exist(db.store.applications, rec["application_id"], "application")

    if action == "APPEAL" and app["applicant_id"] != caller.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "only the owning applicant may appeal")

    if action == "VERIFY":
        if rec["status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "claim is not PENDING")
        if app["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            raise errors.err(errors.ERR_INVALID_STATE, "application not in a reviewable state")
        rec["status"] = "VERIFIED"
        rec["decided_at"] = db.now_iso()
        rec["decided_by"] = caller.user_id
        rec["denial_reason"] = None
        H.recompute_verified_preference_categories(rec["application_id"])
    elif action == "DENY":
        if rec["status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "claim is not PENDING")
        if app["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            raise errors.err(errors.ERR_INVALID_STATE, "application not in a reviewable state")
        reason = body.get("denial_reason")
        if not isinstance(reason, str) or not reason:
            raise errors.err(errors.ERR_INVALID_REQUEST, "denial_reason required")
        rec["status"] = "DENIED"
        rec["denial_reason"] = reason
        rec["decided_at"] = db.now_iso()
        rec["decided_by"] = caller.user_id
    else:  # APPEAL
        if rec["status"] != "DENIED":
            raise errors.err(errors.ERR_INVALID_STATE, "claim is not DENIED")
        new_ev = body.get("new_evidence_ref")
        if not isinstance(new_ev, str) or not new_ev:
            raise errors.err(errors.ERR_INVALID_REQUEST, "new_evidence_ref required")
        if app["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            raise errors.err(errors.ERR_INVALID_STATE, "application not in a reviewable state")
        rec["status"] = "PENDING"
        rec["evidence_ref"] = new_ev
        rec["denial_reason"] = None

    db.touch(rec)
    return R.success(_pub(rec))


# =====================================================================
# Income certifications
# =====================================================================

@bp.route("/income-certifications", methods=["POST"])
def create_income_certification():
    caller = authenticate()
    require_roles(caller, {"ComplianceOfficer"})
    body = H.get_body()
    application_id = body.get("application_id")
    if not isinstance(application_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "application_id required")
    app = H.must_exist(db.store.applications, application_id, "application")
    if app["status"] != "VERIFIED":
        raise errors.err(errors.ERR_APPLICATION_NOT_VERIFIED, "application is not VERIFIED")
    live = [
        c
        for c in db.store.income_certifications.values()
        if c["application_id"] == application_id and c["status"] != "DENIED"
    ]
    if live:
        raise errors.err(errors.ERR_INVALID_STATE, "a live certification already exists")
    rec = db.new_record()
    rec.update(
        {
            "application_id": application_id,
            "status": "INITIATED",
            "required_docs": [],
            "income_sources": [],
            "certified_annual_income_cents": None,
            "ami_percentage_bp": None,
            "determination": None,
            "certified_at": None,
            "certified_by": None,
            "valid_until": None,
            "denial_reason": None,
        }
    )
    db.store.income_certifications[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


def _filter_certs_for_applicant(caller, items):
    if caller.role == "Applicant":
        items = [
            c
            for c in items
            if db.store.applications.get(c["application_id"], {}).get("applicant_id") == caller.user_id
        ]
    return items


@bp.route("/income-certifications", methods=["GET"])
def list_income_certifications():
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    items = list(db.store.income_certifications.values())
    items = _filter_certs_for_applicant(caller, items)
    aid = _q("application_id")
    status = _q("status")
    if aid is not None:
        items = [c for c in items if c["application_id"] == aid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(c) for c in page], limit, offset, total)


@bp.route("/income-certifications/<cid>", methods=["GET"])
def get_income_certification(cid):
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    rec = H.must_exist(db.store.income_certifications, cid, "income certification")
    if caller.role == "Applicant":
        app = db.store.applications.get(rec["application_id"])
        if not app or app["applicant_id"] != caller.user_id:
            raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "applicant may only fetch own certification")
    return R.success(_pub(rec))


@bp.route("/income-certifications/<cid>/advance", methods=["POST"])
def advance_income_certification(cid):
    caller = authenticate()
    require_roles(caller, {"ComplianceOfficer", "Applicant"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"REQUEST_DOCS", "SUBMIT_DOCS", "CERTIFY", "DENY"})
    require_action_role(
        caller,
        action,
        {
            "REQUEST_DOCS": {"ComplianceOfficer"},
            "SUBMIT_DOCS": {"Applicant"},
            "CERTIFY": {"ComplianceOfficer"},
            "DENY": {"ComplianceOfficer"},
        },
    )
    rec = H.must_exist(db.store.income_certifications, cid, "income certification")
    app = H.must_exist(db.store.applications, rec["application_id"], "application")
    campaign = H.must_exist(db.store.campaigns, app["campaign_id"], "campaign")

    if action == "REQUEST_DOCS":
        if rec["status"] not in ("INITIATED", "DOCS_RECEIVED"):
            raise errors.err(errors.ERR_INVALID_STATE, "certification not in a docs-requestable state")
        docs = body.get("required_docs")
        if not isinstance(docs, list) or not docs or any(not isinstance(d, str) for d in docs):
            raise errors.err(errors.ERR_INVALID_REQUEST, "required_docs must be a non-empty array")
        rec["required_docs"] = docs
        rec["status"] = "DOCS_REQUESTED"
    elif action == "SUBMIT_DOCS":
        if app["applicant_id"] != caller.user_id:
            raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "only the owning applicant may submit docs")
        if rec["status"] != "DOCS_REQUESTED":
            raise errors.err(errors.ERR_INVALID_STATE, "certification is not DOCS_REQUESTED")
        sources = body.get("income_sources")
        if not isinstance(sources, list) or not sources:
            raise errors.err(errors.ERR_INVALID_REQUEST, "income_sources must be a non-empty array")
        for s in sources:
            if not isinstance(s, dict):
                raise errors.err(errors.ERR_INVALID_REQUEST, "income source must be an object")
            st = s.get("source_type")
            amt = s.get("amount_per_period_cents")
            ppy = s.get("periods_per_year")
            if not isinstance(st, str) or not st:
                raise errors.err(errors.ERR_INVALID_REQUEST, "source_type required")
            if isinstance(amt, bool) or not isinstance(amt, (int, float)):
                raise errors.err(errors.ERR_INVALID_REQUEST, "amount_per_period_cents must be a number")
            if isinstance(ppy, bool) or not isinstance(ppy, int):
                raise errors.err(errors.ERR_INVALID_REQUEST, "periods_per_year must be an integer")
        rec["income_sources"] = rec.get("income_sources", []) + sources
        rec["status"] = "DOCS_RECEIVED"
    elif action == "CERTIFY":
        if rec["status"] != "DOCS_RECEIVED":
            raise errors.err(errors.ERR_INVALID_STATE, "certification is not DOCS_RECEIVED")
        # 1. segregation of duties
        for r in db.store.lottery_runs.values():
            if r["campaign_id"] != campaign["id"]:
                continue
            if caller.user_id in (
                r.get("sealed_by"),
                r.get("executed_by"),
                r.get("published_by"),
            ):
                raise errors.err(
                    errors.ERR_SEGREGATION_OF_DUTIES,
                    "certifying officer performed lottery operations on this campaign",
                )
        # 2. doc coverage
        covered = {s["source_type"] for s in rec.get("income_sources", [])}
        for d in rec.get("required_docs", []):
            if d not in covered:
                raise errors.err(errors.ERR_CERT_DOCS_INCOMPLETE, "required docs not covered")
        # 3. AMI limit exists
        limit_row = S._ami_limit_for(
            campaign["property_id"], app["household_size"], campaign["target_ami_tier"]
        )
        if limit_row is None:
            raise errors.err(errors.ERR_AMI_LIMIT_NOT_DEFINED, "AMI limit row missing")
        # compute
        certified_cents = S.annualize_income(rec["income_sources"])
        # 4. income ceiling
        if certified_cents > limit_row["annual_limit_cents"]:
            raise errors.err(errors.ERR_OVER_INCOME, "certified income exceeds limit")
        now = db.now_dt()
        rec["certified_annual_income_cents"] = certified_cents
        rec["ami_percentage_bp"] = S.ami_percentage_bp(
            certified_cents, limit_row["annual_limit_cents"]
        )
        rec["determination"] = "ELIGIBLE"
        rec["certified_at"] = db.format_iso(now)
        rec["certified_by"] = caller.user_id
        rec["valid_until"] = db.format_iso(now + timedelta(days=S.CERTIFICATION_VALID_DAYS))
        rec["status"] = "CERTIFIED"
    else:  # DENY
        if rec["status"] != "DOCS_RECEIVED":
            raise errors.err(errors.ERR_INVALID_STATE, "certification is not DOCS_RECEIVED")
        reason = body.get("denial_reason")
        if not isinstance(reason, str) or not reason:
            raise errors.err(errors.ERR_INVALID_REQUEST, "denial_reason required")
        rec["status"] = "DENIED"
        rec["denial_reason"] = reason

    db.touch(rec)
    return R.success(_pub(rec))


# =====================================================================
# Lottery runs
# =====================================================================

@bp.route("/lottery-runs", methods=["POST"])
def create_lottery_run():
    caller = authenticate()
    require_roles(caller, {"LotteryAdministrator"})
    body = H.get_body()
    campaign_id = body.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "campaign_id required")
    seed = H.req_str(body, "seed")
    expected_version = body.get("expected_campaign_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_campaign_version required")

    campaign = H.must_exist(db.store.campaigns, campaign_id, "campaign")

    # OCC (priority 5)
    if expected_version != campaign["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "stale campaign version")

    # state preconditions (priority 6)
    if campaign["status"] != "CLOSED":
        raise errors.err(errors.ERR_INVALID_STATE, "campaign is not CLOSED")
    live = [
        r
        for r in db.store.lottery_runs.values()
        if r["campaign_id"] == campaign_id and r["status"] != "VOIDED"
    ]
    if live:
        raise errors.err(errors.ERR_ACTIVE_LOTTERY_EXISTS, "an active lottery run exists")

    rec = db.new_record()
    rec.update(
        {
            "campaign_id": campaign_id,
            "seed": seed,
            "status": "DRAFT",
            "eligible_application_count": 0,
            "entries_generated": 0,
            "sealed_by": None,
            "executed_by": None,
            "published_by": None,
            "sealed_at": None,
            "executed_at": None,
            "published_at": None,
            "void_reason": None,
        }
    )
    db.store.lottery_runs[rec["id"]] = rec
    db.touch(campaign)  # creation bumps campaign version
    return R.success(_pub(rec), status=201)


@bp.route("/lottery-runs", methods=["GET"])
def list_lottery_runs():
    caller = authenticate()
    require_roles(caller, STAFF)
    items = list(db.store.lottery_runs.values())
    cid = _q("campaign_id")
    status = _q("status")
    if cid is not None:
        items = [r for r in items if r["campaign_id"] == cid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(r) for r in page], limit, offset, total)


@bp.route("/lottery-runs/<rid>", methods=["GET"])
def get_lottery_run(rid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.lottery_runs, rid, "lottery run")
    return R.success(_pub(rec))


def _lottery_segregation_check(caller, campaign_id):
    for c in db.store.income_certifications.values():
        app = db.store.applications.get(c["application_id"])
        if not app or app["campaign_id"] != campaign_id:
            continue
        if c.get("certified_by") == caller.user_id:
            raise errors.err(
                errors.ERR_SEGREGATION_OF_DUTIES,
                "operator certified income on this campaign",
            )


@bp.route("/lottery-runs/<rid>/transition", methods=["POST"])
def transition_lottery_run(rid):
    caller = authenticate()
    require_roles(caller, {"LotteryAdministrator"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"SEAL", "EXECUTE", "PUBLISH", "VOID"})
    rec = H.must_exist(db.store.lottery_runs, rid, "lottery run")
    campaign = H.must_exist(db.store.campaigns, rec["campaign_id"], "campaign")

    if action == "SEAL":
        if rec["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "run is not DRAFT")
        _lottery_segregation_check(caller, rec["campaign_id"])
        eligible_ids = [
            a["id"]
            for a in db.store.applications.values()
            if a["campaign_id"] == rec["campaign_id"] and a["status"] == "VERIFIED"
        ]
        db.store.lottery_snapshots[rec["id"]] = eligible_ids
        rec["eligible_application_count"] = len(eligible_ids)
        rec["sealed_by"] = caller.user_id
        rec["sealed_at"] = db.now_iso()
        rec["status"] = "SEALED"
    elif action == "EXECUTE":
        if rec["status"] != "SEALED":
            raise errors.err(errors.ERR_INVALID_STATE, "run is not SEALED")
        _lottery_segregation_check(caller, rec["campaign_id"])
        S.execute_lottery(rec)
        rec["executed_by"] = caller.user_id
        rec["executed_at"] = db.now_iso()
        rec["status"] = "EXECUTED"
    elif action == "PUBLISH":
        if rec["status"] != "EXECUTED":
            raise errors.err(errors.ERR_INVALID_STATE, "run is not EXECUTED")
        _lottery_segregation_check(caller, rec["campaign_id"])
        rec["published_by"] = caller.user_id
        rec["published_at"] = db.now_iso()
        rec["status"] = "PUBLISHED"
        # campaign CLOSED -> LOTTERY_COMPLETED
        if campaign["status"] == "CLOSED":
            campaign["status"] = "LOTTERY_COMPLETED"
            db.touch(campaign)
    else:  # VOID
        if rec["status"] not in ("DRAFT", "SEALED", "EXECUTED", "PUBLISHED"):
            raise errors.err(errors.ERR_INVALID_STATE, "run is not voidable")
        reason = body.get("void_reason")
        if not isinstance(reason, str) or not reason:
            raise errors.err(errors.ERR_INVALID_REQUEST, "void_reason required")
        prev = rec["status"]
        rec["status"] = "VOIDED"
        rec["void_reason"] = reason
        if prev in ("EXECUTED", "PUBLISHED"):
            S.void_lottery_cascade(rec)
        if prev == "PUBLISHED" and campaign["status"] in ("LOTTERY_COMPLETED", "LEASING"):
            campaign["status"] = "CLOSED"
            db.touch(campaign)

    db.touch(rec)
    return R.success(_pub(rec))


# =====================================================================
# Waitlist entries
# =====================================================================

def _filter_entries_for_applicant(caller, items):
    if caller.role == "Applicant":
        out = []
        for e in items:
            app = db.store.applications.get(e["application_id"])
            if app and app["applicant_id"] == caller.user_id:
                out.append(e)
        return out
    return items


@bp.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    items = list(db.store.waitlist_entries.values())
    items = _filter_entries_for_applicant(caller, items)
    cid = _q("campaign_id")
    rid = _q("lottery_run_id")
    aid = _q("application_id")
    status = _q("status")
    if cid is not None:
        items = [e for e in items if e["campaign_id"] == cid]
    if rid is not None:
        items = [e for e in items if e["lottery_run_id"] == rid]
    if aid is not None:
        items = [e for e in items if e["application_id"] == aid]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(e) for e in page], limit, offset, total)


@bp.route("/waitlist-entries/<eid>", methods=["GET"])
def get_waitlist_entry(eid):
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    rec = H.must_exist(db.store.waitlist_entries, eid, "waitlist entry")
    if caller.role == "Applicant":
        app = db.store.applications.get(rec["application_id"])
        if not app or app["applicant_id"] != caller.user_id:
            raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "applicant may only fetch own entry")
    return R.success(_pub(rec))


@bp.route("/waitlist-entries/<eid>/confirm-interest", methods=["POST"])
def confirm_interest(eid):
    caller = authenticate()
    require_roles(caller, {"Applicant"})
    rec = H.must_exist(db.store.waitlist_entries, eid, "waitlist entry")
    app = H.must_exist(db.store.applications, rec["application_id"], "application")
    if app["applicant_id"] != caller.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "only the owning applicant may confirm")
    if rec["status"] != "RANKED":
        raise errors.err(errors.ERR_INVALID_STATE, "entry is not RANKED")
    active_purge = any(
        p
        for p in db.store.purge_runs.values()
        if p["campaign_id"] == rec["campaign_id"] and p["status"] == "NOTICES_SENT"
    )
    if not active_purge:
        raise errors.err(errors.ERR_INVALID_STATE, "no purge notice window active")
    rec["last_confirmed_at"] = db.now_iso()
    db.touch(rec)
    return R.success(_pub(rec))


@bp.route("/waitlist-entries/<eid>/remove", methods=["POST"])
def remove_waitlist_entry(eid):
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    removal_reason = body.get("removal_reason")
    if not isinstance(removal_reason, str) or not removal_reason:
        raise errors.err(errors.ERR_INVALID_REQUEST, "removal_reason required")
    if removal_reason not in ("MAX_REFUSALS", "PURGED", "LOTTERY_VOIDED", "ADMIN_REMOVED"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "invalid removal_reason")
    rec = H.must_exist(db.store.waitlist_entries, eid, "waitlist entry")
    if rec["status"] != "RANKED":
        raise errors.err(errors.ERR_INVALID_STATE, "entry is not RANKED")
    rec["status"] = "REMOVED"
    rec["removal_reason"] = removal_reason
    rec["removed_at"] = db.now_iso()
    db.touch(rec)
    H.recompute_campaign_counters(rec["campaign_id"])
    return R.success(_pub(rec))


# =====================================================================
# Unit offers
# =====================================================================

@bp.route("/offers/generate", methods=["POST"])
def generate_offers():
    caller = authenticate()
    require_roles(caller, {"LotteryAdministrator"})
    body = H.get_body()
    campaign_id = body.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "campaign_id required")
    campaign = H.must_exist(db.store.campaigns, campaign_id, "campaign")

    offers, units_considered = S.offer_unit_selection(campaign)

    # first generation flips campaign LOTTERY_COMPLETED -> LEASING
    if offers and campaign["status"] == "LOTTERY_COMPLETED":
        campaign["status"] = "LEASING"
        db.touch(campaign)
    if offers:
        H.recompute_campaign_counters(campaign_id)

    return R.success(
        {
            "generated_count": len(offers),
            "generated_offer_ids": [o["id"] for o in offers],
            "units_considered": units_considered,
        }
    )


def _filter_offers_for_applicant(caller, items):
    if caller.role == "Applicant":
        out = []
        for o in items:
            entry = db.store.waitlist_entries.get(o["entry_id"])
            if not entry:
                continue
            app = db.store.applications.get(entry["application_id"])
            if app and app["applicant_id"] == caller.user_id:
                out.append(o)
        return out
    return items


@bp.route("/offers", methods=["GET"])
def list_offers():
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    items = list(db.store.unit_offers.values())
    items = _filter_offers_for_applicant(caller, items)
    cid = _q("campaign_id")
    uid = _q("unit_id")
    eid = _q("entry_id")
    status = _q("status")
    if cid is not None:
        items = [o for o in items if o["campaign_id"] == cid]
    if uid is not None:
        items = [o for o in items if o["unit_id"] == uid]
    if eid is not None:
        items = [o for o in items if o["entry_id"] == eid]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(o) for o in page], limit, offset, total)


@bp.route("/offers/<oid>", methods=["GET"])
def get_offer(oid):
    caller = authenticate()
    require_roles(caller, STAFF | {"Applicant"})
    rec = H.must_exist(db.store.unit_offers, oid, "offer")
    if caller.role == "Applicant":
        entry = db.store.waitlist_entries.get(rec["entry_id"])
        app = db.store.applications.get(entry["application_id"]) if entry else None
        if not app or app["applicant_id"] != caller.user_id:
            raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "applicant may only fetch own offer")
    return R.success(_pub(rec))


@bp.route("/offers/<oid>/respond", methods=["POST"])
def respond_offer(oid):
    caller = authenticate()
    require_roles(caller, {"Applicant"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"ACCEPT", "DECLINE"})
    offer = H.must_exist(db.store.unit_offers, oid, "offer")
    entry = H.must_exist(db.store.waitlist_entries, offer["entry_id"], "waitlist entry")
    app = H.must_exist(db.store.applications, entry["application_id"], "application")

    if app["applicant_id"] != caller.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "only the owning applicant may respond")

    if offer["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "offer is not PENDING")

    now = db.now_dt()
    if now > db.parse_iso(offer["response_deadline"]):
        raise errors.err(errors.ERR_OFFER_EXPIRED, "offer response deadline passed")

    if action == "ACCEPT":
        cert = S._current_certification(app["id"])
        if cert is None or db.parse_iso(cert["valid_until"]) < now:
            raise errors.err(errors.ERR_CERTIFICATION_EXPIRED, "certification expired")
        S.accept_offer(offer)
    else:
        S.decline_or_expire_offer(offer, "DECLINED")

    return R.success(_pub(offer))


@bp.route("/offers/expire-due", methods=["POST"])
def expire_due_offers():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    now = db.now_dt()
    due = [
        o
        for o in db.store.unit_offers.values()
        if o["status"] == "PENDING" and db.parse_iso(o["response_deadline"]) < now
    ]
    due.sort(key=lambda o: o["offered_at"])
    for o in due:
        S.decline_or_expire_offer(o, "EXPIRED")
    return R.success({"expired_count": len(due)})


# =====================================================================
# Purge runs
# =====================================================================

@bp.route("/purge-runs", methods=["POST"])
def create_purge_run():
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    campaign_id = body.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "campaign_id required")
    notice_days = H.opt_int(body, "notice_response_days", 30)
    if notice_days is not None and notice_days < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "notice_response_days invalid")
    expected_version = body.get("expected_campaign_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_campaign_version required")

    campaign = H.must_exist(db.store.campaigns, campaign_id, "campaign")

    if expected_version != campaign["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "stale campaign version")
    if campaign["status"] != "LEASING":
        raise errors.err(errors.ERR_INVALID_STATE, "campaign is not LEASING")

    rec = db.new_record()
    rec.update(
        {
            "campaign_id": campaign_id,
            "notice_response_days": notice_days if notice_days is not None else 30,
            "status": "SCHEDULED",
            "notice_sent_at": None,
            "response_deadline": None,
            "executed_at": None,
            "entries_removed_count": 0,
        }
    )
    db.store.purge_runs[rec["id"]] = rec

    # campaign LEASING -> PURGE_SCHEDULED
    campaign["status"] = "PURGE_SCHEDULED"
    db.touch(campaign)
    return R.success(_pub(rec), status=201)


@bp.route("/purge-runs", methods=["GET"])
def list_purge_runs():
    caller = authenticate()
    require_roles(caller, STAFF)
    items = list(db.store.purge_runs.values())
    cid = _q("campaign_id")
    status = _q("status")
    if cid is not None:
        items = [p for p in items if p["campaign_id"] == cid]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(p) for p in page], limit, offset, total)


@bp.route("/purge-runs/<pid>", methods=["GET"])
def get_purge_run(pid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.purge_runs, pid, "purge run")
    return R.success(_pub(rec))


@bp.route("/purge-runs/<pid>/advance", methods=["POST"])
def advance_purge_run(pid):
    caller = authenticate()
    require_roles(caller, {"HousingDeveloper"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"SEND_NOTICES", "EXECUTE", "CANCEL"})
    rec = H.must_exist(db.store.purge_runs, pid, "purge run")
    campaign = H.must_exist(db.store.campaigns, rec["campaign_id"], "campaign")

    if action == "SEND_NOTICES":
        if rec["status"] != "SCHEDULED":
            raise errors.err(errors.ERR_INVALID_STATE, "purge is not SCHEDULED")
        now = db.now_dt()
        rec["notice_sent_at"] = db.format_iso(now)
        rec["response_deadline"] = db.format_iso(
            now + timedelta(days=rec["notice_response_days"])
        )
        rec["status"] = "NOTICES_SENT"
    elif action == "EXECUTE":
        if rec["status"] != "NOTICES_SENT":
            raise errors.err(errors.ERR_INVALID_STATE, "purge is not NOTICES_SENT")
        if db.now_dt() < db.parse_iso(rec["response_deadline"]):
            raise errors.err(errors.ERR_PURGE_NOT_EXECUTABLE, "response deadline not reached")
        S.execute_purge(rec)
        rec["status"] = "EXECUTED"
        H.recompute_campaign_counters(rec["campaign_id"])
        if campaign["status"] == "PURGE_SCHEDULED":
            if campaign["waitlist_active_count"] == 0:
                campaign["status"] = "PURGED"
            else:
                campaign["status"] = "LEASING"
            db.touch(campaign)
    else:  # CANCEL
        if rec["status"] not in ("SCHEDULED", "NOTICES_SENT"):
            raise errors.err(errors.ERR_INVALID_STATE, "purge is not cancellable")
        rec["status"] = "CANCELLED"
        if campaign["status"] == "PURGE_SCHEDULED":
            campaign["status"] = "LEASING"
            db.touch(campaign)

    db.touch(rec)
    return R.success(_pub(rec))


# =====================================================================
# Compliance reports
# =====================================================================

@bp.route("/compliance-reports", methods=["POST"])
def create_compliance_report():
    caller = authenticate()
    require_roles(caller, {"ComplianceOfficer"})
    body = H.get_body()
    campaign_id = body.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "campaign_id required")
    period_start = H.req_datetime(body, "period_start")
    period_end = H.req_datetime(body, "period_end")
    period_mode = H.req_enum(body, "period_mode", PERIOD_MODES)

    campaign = H.must_exist(db.store.campaigns, campaign_id, "campaign")

    if period_mode == "CALENDAR_QUARTER":
        if not S.validate_calendar_quarter(period_start, period_end):
            raise errors.err(
                errors.ERR_INVALID_REQUEST, "CALENDAR_QUARTER period not quarter-aligned"
            )
    else:
        if period_end < period_start:
            raise errors.err(errors.ERR_INVALID_REQUEST, "period_end before period_start")

    # closed-interval overlap against SUBMITTED/ACKNOWLEDGED reports on same campaign
    for r in db.store.compliance_reports.values():
        if r["campaign_id"] != campaign_id:
            continue
        if r["status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
            continue
        os_ = db.parse_iso(r["period_start"])
        oe = db.parse_iso(r["period_end"])
        if period_start <= oe and os_ <= period_end:
            raise errors.err(errors.ERR_REPORT_PERIOD_OVERLAP, "report period overlaps existing")

    rec = db.new_record()
    rec.update(
        {
            "campaign_id": campaign_id,
            "period_start": db.format_iso(period_start),
            "period_end": db.format_iso(period_end),
            "period_mode": period_mode,
            "applications_received_count": 0,
            "applications_verified_count": 0,
            "preference_claims_decided_count": 0,
            "preference_claims_verified_count": 0,
            "preference_verification_rate_bp": 0,
            "lottery_runs_executed_count": 0,
            "offers_made_count": 0,
            "offers_accepted_count": 0,
            "entries_removed_count": 0,
            "lease_up_rate_bp": 0,
            "status": "DRAFT",
            "submitted_by": None,
            "submitted_at": None,
            "return_reason": None,
        }
    )
    S.compute_report_aggregates(rec)
    db.store.compliance_reports[rec["id"]] = rec
    return R.success(_pub(rec), status=201)


@bp.route("/compliance-reports", methods=["GET"])
def list_compliance_reports():
    caller = authenticate()
    require_roles(caller, STAFF)
    items = list(db.store.compliance_reports.values())
    cid = _q("campaign_id")
    status = _q("status")
    if cid is not None:
        items = [r for r in items if r["campaign_id"] == cid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = H.paginate(items)
    return R.success_list([_pub(r) for r in page], limit, offset, total)


@bp.route("/compliance-reports/<rid>", methods=["GET"])
def get_compliance_report(rid):
    caller = authenticate()
    require_roles(caller, STAFF)
    rec = H.must_exist(db.store.compliance_reports, rid, "compliance report")
    return R.success(_pub(rec))


@bp.route("/compliance-reports/<rid>/transition", methods=["POST"])
def transition_compliance_report(rid):
    caller = authenticate()
    require_roles(caller, {"ComplianceOfficer", "FundingAgencyAuditor"})
    body = H.get_body()
    action = H.req_enum(body, "action", {"SUBMIT", "ACKNOWLEDGE", "RETURN"})
    require_action_role(
        caller,
        action,
        {
            "SUBMIT": {"ComplianceOfficer"},
            "ACKNOWLEDGE": {"FundingAgencyAuditor"},
            "RETURN": {"FundingAgencyAuditor"},
        },
    )
    rec = H.must_exist(db.store.compliance_reports, rid, "compliance report")
    campaign = H.must_exist(db.store.campaigns, rec["campaign_id"], "campaign")

    if action == "SUBMIT":
        if rec["status"] not in ("DRAFT", "RETURNED"):
            raise errors.err(errors.ERR_INVALID_STATE, "report is not submittable")
        published = any(
            r
            for r in db.store.lottery_runs.values()
            if r["campaign_id"] == rec["campaign_id"] and r["status"] == "PUBLISHED"
        )
        if not published:
            raise errors.err(
                errors.ERR_REPORT_INCOMPLETE_DATA, "campaign has no PUBLISHED lottery run"
            )
        if campaign["status"] not in ("LOTTERY_COMPLETED", "LEASING", "PURGE_SCHEDULED", "PURGED"):
            raise errors.err(
                errors.ERR_REPORT_INCOMPLETE_DATA, "campaign not in a post-lottery state"
            )
        if rec["status"] == "RETURNED":
            S.compute_report_aggregates(rec)
            rec["return_reason"] = None
        rec["submitted_by"] = caller.user_id
        rec["submitted_at"] = db.now_iso()
        rec["status"] = "SUBMITTED"
    elif action == "ACKNOWLEDGE":
        if rec["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_INVALID_STATE, "report is not SUBMITTED")
        rec["status"] = "ACKNOWLEDGED"
    else:  # RETURN
        if rec["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_INVALID_STATE, "report is not SUBMITTED")
        reason = body.get("return_reason")
        if not isinstance(reason, str) or not reason:
            raise errors.err(errors.ERR_INVALID_REQUEST, "return_reason required")
        rec["status"] = "RETURNED"
        rec["return_reason"] = reason

    db.touch(rec)
    return R.success(_pub(rec))


# =====================================================================
# helpers
# =====================================================================

def _q(name):
    v = None
    from flask import request

    v = request.args.get(name)
    return v
