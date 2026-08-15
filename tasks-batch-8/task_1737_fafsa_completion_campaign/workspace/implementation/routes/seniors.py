"""Senior records, aid records, status events, match links, consent records."""

from flask import Blueprint, request
from decimal import Decimal

import dates
import errors
import middleware
import validate
from db import store, make_common, touch
from response import success_object, success_list
from services import core

bp = Blueprint("seniors", __name__)

SENIOR_READ_ROLES = ["CampaignAdmin", "SchoolCoordinator", "Specialist", "MatchReviewer"]
AID_READ_ROLES = ["CampaignAdmin", "MatchReviewer", "DataImporter"]


# ---------------------------------------------------------------------------
# Senior records
# ---------------------------------------------------------------------------

@bp.route("/fafsa/senior-records", methods=["POST"])
def create_senior():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    body = validate.get_json_body(required=True)
    validate.check_fields(
        body,
        required=["school_id", "student_ref", "full_name", "dob", "home_language"],
        optional=["subgroup_tags", "efc_band"],
    )
    school_id = validate.req_string(body, "school_id")
    student_ref = validate.req_string(body, "student_ref")
    full_name = validate.req_string(body, "full_name")
    dob = validate.req_date(body, "dob")
    home_language = validate.req_string(body, "home_language")
    subgroup_tags = validate.req_array(body, "subgroup_tags", required=False, default=[])
    efc_band = validate.req_enum(body, "efc_band", core.EFC_BANDS, required=False, default="MID")

    school = core.get_school_or_404(school_id)
    middleware.require_school_scope(auth, school["id"])
    campaign = core.get_campaign_or_404(school["campaign_id"])
    # State gate: school ENROLLED, campaign OPEN or STATE_GRACE
    if school["status"] != "ENROLLED":
        errors.raise_error(errors.ERR_SCHOOL_NOT_ENROLLED, "School must be ENROLLED")
    if campaign["status"] not in ("OPEN", "STATE_GRACE"):
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_OPEN, "Campaign must be OPEN or STATE_GRACE")
    # Uniqueness: student_ref per school
    for s in store.senior_records.values():
        if s["school_id"] == school_id and s["student_ref"] == student_ref:
            errors.raise_error(errors.ERR_DUPLICATE_STUDENT_REF, "student_ref already exists for this school")

    common = make_common()
    senior = {
        **common,
        "school_id": school_id,
        "student_ref": student_ref,
        "full_name": full_name,
        "dob": dob,
        "home_language": home_language,
        "subgroup_tags": subgroup_tags or [],
        "efc_band": efc_band or "MID",
        "dependency_status": "DEPENDENT",
        "match_status": "UNMATCHED",
        "fafsa_status": "NO_RECORD",
        "submitted_at": None,
        "deadline_classification": "NOT_SUBMITTED",
        "current_match_link_id": None,
        "data_visibility": "RESTRICTED",
        "_seq": store.next_seq(),
    }
    store.senior_records[senior["id"]] = senior
    return success_object(core.serialize(senior, "senior_records"), 201)


@bp.route("/fafsa/senior-records", methods=["GET"])
def list_seniors():
    auth = middleware.get_auth()
    middleware.require_roles(auth, SENIOR_READ_ROLES)
    limit, offset = validate.parse_pagination()
    school_id = request.args.get("school_id")
    match_status = request.args.get("match_status")
    fafsa_status = request.args.get("fafsa_status")
    subgroup_tag = request.args.get("subgroup_tag")
    items = list(store.senior_records.values())
    if auth.role == "SchoolCoordinator":
        items = [s for s in items if s["school_id"] == auth.user_id]
    if school_id is not None:
        items = [s for s in items if s["school_id"] == school_id]
    if match_status is not None:
        items = [s for s in items if s["match_status"] == match_status]
    if fafsa_status is not None:
        items = [s for s in items if s["fafsa_status"] == fafsa_status]
    if subgroup_tag is not None:
        items = [s for s in items if subgroup_tag in (s.get("subgroup_tags") or [])]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(s, "senior_records") for s in page], limit, offset, total)


@bp.route("/fafsa/senior-records/<sid>", methods=["GET"])
def get_senior(sid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, SENIOR_READ_ROLES)
    senior = core.get_senior_or_404(sid)
    middleware.require_school_scope(auth, senior["school_id"])
    return success_object(core.serialize(senior, "senior_records"))


# ---------------------------------------------------------------------------
# Aid records + status events
# ---------------------------------------------------------------------------

@bp.route("/fafsa/aid-records", methods=["POST"])
def create_aid_record():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["DataImporter"])
    body = validate.get_json_body(required=True)
    validate.check_fields(
        body,
        required=["campaign_id", "external_ref", "full_name", "dob", "school_code", "district_code", "initial_status", "effective_date"],
        optional=[],
    )
    campaign_id = validate.req_string(body, "campaign_id")
    external_ref = validate.req_string(body, "external_ref")
    full_name = validate.req_string(body, "full_name")
    dob = validate.req_date(body, "dob")
    school_code = validate.req_string(body, "school_code")
    district_code = validate.req_string(body, "district_code")
    initial_status = validate.req_enum(body, "initial_status", core.AID_STATUSES)
    effective_date = validate.req_date(body, "effective_date")

    core.get_campaign_or_404(campaign_id)
    for a in store.aid_records.values():
        if a["campaign_id"] == campaign_id and a["external_ref"] == external_ref:
            errors.raise_error(errors.ERR_DUPLICATE_EXTERNAL_REF, "external_ref already exists for this campaign")

    common = make_common()
    record = {
        **common,
        "campaign_id": campaign_id,
        "external_ref": external_ref,
        "full_name": full_name,
        "dob": dob,
        "school_code": school_code,
        "district_code": district_code,
        "current_status": initial_status,
        "last_effective_date": effective_date,
        "_seq": store.next_seq(),
    }
    store.aid_records[record["id"]] = record
    # First status event
    ev = {
        "id": __import__("db").new_id(),
        "created_at": record["created_at"],
        "aid_record_id": record["id"],
        "fafsa_status": initial_status,
        "effective_date": effective_date,
        "source": "IMPORT",
        "_seq": store.next_seq(),
    }
    store.aid_status_events[ev["id"]] = ev
    core.apply_aid_record_projection(record)
    return success_object(core.serialize(record), 201)


@bp.route("/fafsa/aid-records", methods=["GET"])
def list_aid_records():
    auth = middleware.get_auth()
    middleware.require_roles(auth, AID_READ_ROLES)
    limit, offset = validate.parse_pagination()
    campaign_id = request.args.get("campaign_id")
    current_status = request.args.get("current_status")
    items = list(store.aid_records.values())
    if campaign_id is not None:
        items = [a for a in items if a["campaign_id"] == campaign_id]
    if current_status is not None:
        items = [a for a in items if a["current_status"] == current_status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(a) for a in page], limit, offset, total)


@bp.route("/fafsa/aid-records/<aid>", methods=["GET"])
def get_aid_record(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, AID_READ_ROLES)
    record = core.get_aid_record_or_404(aid)
    return success_object(core.serialize(record))


@bp.route("/fafsa/aid-records/<aid>/status-events", methods=["POST"])
def add_status_event(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["DataImporter"])
    record = core.get_aid_record_or_404(aid)
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["fafsa_status", "effective_date"], optional=["source"])
    fafsa_status = validate.req_enum(body, "fafsa_status", core.AID_STATUSES)
    effective_date = validate.req_date(body, "effective_date")
    source = validate.req_string(body, "source", required=False) or "IMPORT"

    from db import new_id, now_iso

    ev = {
        "id": new_id(),
        "created_at": now_iso(),
        "aid_record_id": record["id"],
        "fafsa_status": fafsa_status,
        "effective_date": effective_date,
        "source": source,
        "_seq": store.next_seq(),
    }
    store.aid_status_events[ev["id"]] = ev
    # Projection: moves only when effective_date >= last_effective_date
    last_d = dates.to_utc_date(record["last_effective_date"])
    new_d = dates.to_utc_date(effective_date)
    if new_d >= last_d:
        core.apply_aid_record_projection(record)
    out = {k: v for k, v in ev.items() if not k.startswith("_")}
    return success_object(out, 201)


@bp.route("/fafsa/aid-records/<aid>/status-events", methods=["GET"])
def list_status_events(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, AID_READ_ROLES)
    record = core.get_aid_record_or_404(aid)
    limit, offset = validate.parse_pagination()
    items = [e for e in store.aid_status_events.values() if e["aid_record_id"] == record["id"]]
    # Chronological: effective_date ASC, then created_at, then _seq
    items.sort(key=lambda e: (dates.to_utc_date(e["effective_date"]), e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([{k: v for k, v in e.items() if not k.startswith("_")} for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Match links
# ---------------------------------------------------------------------------

@bp.route("/fafsa/match-links", methods=["POST"])
def create_match_link():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["MatchReviewer"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["senior_record_id", "aid_record_id", "expected_senior_record_version"], optional=[])
    senior_record_id = validate.req_string(body, "senior_record_id")
    aid_record_id = validate.req_string(body, "aid_record_id")
    expected_version = validate.req_int(body, "expected_senior_record_version")

    senior = core.get_senior_or_404(senior_record_id)
    aid_record = core.get_aid_record_or_404(aid_record_id)

    # OCC: evaluated with existence-and-state checks, before business rules (§2.9)
    if senior["version"] != expected_version:
        errors.raise_error(errors.ERR_STALE_VERSION, "Senior record version mismatch")

    # State: one non-terminal link per senior
    for l in store.match_links.values():
        if l["senior_record_id"] == senior["id"] and l["status"] in core.NON_TERMINAL_LINK_STATUSES:
            errors.raise_error(errors.ERR_LINK_ALREADY_EXISTS, "A non-terminal MatchLink already exists for this senior")

    # Cross-campaign referential integrity
    school = store.schools.get(senior["school_id"])
    if school is None or school["campaign_id"] != aid_record["campaign_id"]:
        errors.raise_error(errors.ERR_CROSS_CAMPAIGN_REFERENCE, "Senior and aid record belong to different campaigns")

    campaign = store.campaigns.get(aid_record["campaign_id"])

    # Scoring
    score, components = core.compute_match_score(senior, aid_record)
    score_f = float(score)
    auto_confirm = Decimal(str(campaign["auto_confirm_threshold"]))
    review_floor = Decimal(str(campaign["review_floor"]))
    if score >= auto_confirm:
        initial = "AUTO_CONFIRMED"
    elif score >= review_floor:
        initial = "SUGGESTED"
    else:
        initial = "AUTO_REJECTED"

    common = make_common()
    link = {
        **common,
        "senior_record_id": senior["id"],
        "aid_record_id": aid_record["id"],
        "match_score": score_f,
        "score_components": components,
        "status": initial,
        "_seq": store.next_seq(),
    }
    store.match_links[link["id"]] = link

    # Every link creation increments the senior's version by one.
    touch(senior)
    if initial == "AUTO_CONFIRMED":
        # UNMATCHED -> MATCHED cascade
        core.matched_cascade(senior, link, aid_record)
    elif initial == "SUGGESTED":
        senior["match_status"] = "SUGGESTED"
        touch(senior)
    # AUTO_REJECTED: terminal on arrival; senior match axis unchanged (version already bumped)

    return success_object(core.serialize(link), 201)


@bp.route("/fafsa/match-links", methods=["GET"])
def list_match_links():
    auth = middleware.get_auth()
    middleware.require_roles(auth, AID_READ_ROLES)
    limit, offset = validate.parse_pagination()
    senior_record_id = request.args.get("senior_record_id")
    aid_record_id = request.args.get("aid_record_id")
    status = request.args.get("status")
    items = list(store.match_links.values())
    if senior_record_id is not None:
        items = [l for l in items if l["senior_record_id"] == senior_record_id]
    if aid_record_id is not None:
        items = [l for l in items if l["aid_record_id"] == aid_record_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(l) for l in page], limit, offset, total)


@bp.route("/fafsa/match-links/<lid>", methods=["GET"])
def get_match_link(lid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, AID_READ_ROLES)
    link = core.get_match_link_or_404(lid)
    return success_object(core.serialize(link))


@bp.route("/fafsa/match-links/<lid>/confirm", methods=["POST"])
def confirm_match_link(lid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["MatchReviewer"])
    link = core.get_match_link_or_404(lid)
    if link["status"] != "SUGGESTED":
        errors.raise_error(errors.ERR_MATCH_LINK_NOT_SUGGESTED, "confirm requires SUGGESTED")
    link["status"] = "CONFIRMED"
    touch(link)
    senior = core.get_senior_or_404(link["senior_record_id"])
    aid_record = core.get_aid_record_or_404(link["aid_record_id"])
    core.matched_cascade(senior, link, aid_record)
    return success_object(core.serialize(link))


@bp.route("/fafsa/match-links/<lid>/reject", methods=["POST"])
def reject_match_link(lid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["MatchReviewer"])
    link = core.get_match_link_or_404(lid)
    if link["status"] != "SUGGESTED":
        errors.raise_error(errors.ERR_MATCH_LINK_NOT_SUGGESTED, "reject requires SUGGESTED")
    link["status"] = "REJECTED"
    touch(link)
    senior = core.get_senior_or_404(link["senior_record_id"])
    if senior["match_status"] == "SUGGESTED":
        senior["match_status"] = "UNMATCHED"
        touch(senior)
    return success_object(core.serialize(link))


@bp.route("/fafsa/match-links/<lid>/invalidate", methods=["POST"])
def invalidate_match_link(lid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["MatchReviewer"])
    link = core.get_match_link_or_404(lid)
    if link["status"] not in ("CONFIRMED", "AUTO_CONFIRMED"):
        errors.raise_error(errors.ERR_MATCH_LINK_NOT_CONFIRMED, "invalidate requires CONFIRMED or AUTO_CONFIRMED")
    link["status"] = "INVALIDATED"
    touch(link)
    senior = core.get_senior_or_404(link["senior_record_id"])
    if senior.get("current_match_link_id") == link["id"]:
        core.unmatched_cascade(senior)
    return success_object(core.serialize(link))


# ---------------------------------------------------------------------------
# Consent records
# ---------------------------------------------------------------------------

CONSENT_READ_ROLES = ["CampaignAdmin", "SchoolCoordinator", "Specialist", "MatchReviewer"]


@bp.route("/fafsa/consent-records", methods=["POST"])
def create_consent():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["senior_record_id", "scopes", "granted_by"], optional=["expires_at"])
    senior_record_id = validate.req_string(body, "senior_record_id")
    scopes = validate.req_array(body, "scopes")
    granted_by = validate.req_enum(body, "granted_by", core.GRANTED_BY)
    expires_at = validate.req_datetime(body, "expires_at", required=False, default=None)

    if not scopes:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "scopes must be non-empty")
    for s in scopes:
        if s not in core.CONSENT_SCOPES:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Invalid scope: {s}")

    senior = core.get_senior_or_404(senior_record_id)
    middleware.require_school_scope(auth, senior["school_id"])

    if core.any_granted_consent(senior["id"]):
        errors.raise_error(errors.ERR_CONSENT_ALREADY_ACTIVE, "A GRANTED ConsentRecord already exists for this senior")

    common = make_common()
    consent = {
        **common,
        "senior_record_id": senior["id"],
        "scopes": scopes,
        "granted_by": granted_by,
        "status": "GRANTED",
        "expires_at": expires_at,
        "_seq": store.next_seq(),
    }
    store.consent_records[consent["id"]] = consent
    was_restricted = senior["data_visibility"] == "RESTRICTED"
    core.recompute_visibility(senior)
    if was_restricted and senior["data_visibility"] == "NORMAL" and "STATUS_DETAIL" in scopes:
        # Visibility restored -> resume PAUSED cases (§3.6).
        core.consent_restore_cascade(senior["id"])
    return success_object(core.serialize(consent), 201)


@bp.route("/fafsa/consent-records", methods=["GET"])
def list_consents():
    auth = middleware.get_auth()
    middleware.require_roles(auth, CONSENT_READ_ROLES)
    limit, offset = validate.parse_pagination()
    senior_record_id = request.args.get("senior_record_id")
    status = request.args.get("status")
    items = list(store.consent_records.values())
    if auth.role == "SchoolCoordinator":
        items = [
            c
            for c in items
            if store.senior_records.get(c["senior_record_id"], {}).get("school_id") == auth.user_id
        ]
    if senior_record_id is not None:
        items = [c for c in items if c["senior_record_id"] == senior_record_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(c) for c in page], limit, offset, total)


@bp.route("/fafsa/consent-records/<cid>", methods=["GET"])
def get_consent(cid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, CONSENT_READ_ROLES)
    consent = core.get_consent_or_404(cid)
    senior = core.get_senior_or_404(consent["senior_record_id"])
    middleware.require_school_scope(auth, senior["school_id"])
    return success_object(core.serialize(consent))


@bp.route("/fafsa/consent-records/<cid>/revoke", methods=["POST"])
def revoke_consent(cid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    consent = core.get_consent_or_404(cid)
    senior = core.get_senior_or_404(consent["senior_record_id"])
    middleware.require_school_scope(auth, senior["school_id"])
    if consent["status"] != "GRANTED":
        errors.raise_error(errors.ERR_CONSENT_NOT_GRANTED, "revoke requires GRANTED")
    consent["status"] = "REVOKED"
    touch(consent)
    core.consent_loss_cascade(consent["senior_record_id"])
    return success_object(core.serialize(consent))


@bp.route("/fafsa/consent-records/<cid>/regrant", methods=["POST"])
def regrant_consent(cid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    consent = core.get_consent_or_404(cid)
    senior = core.get_senior_or_404(consent["senior_record_id"])
    middleware.require_school_scope(auth, senior["school_id"])
    if consent["status"] != "REVOKED":
        errors.raise_error(errors.ERR_CONSENT_NOT_REVOKED, "regrant requires REVOKED")
    # No other GRANTED consent for this senior
    for c in store.consent_records.values():
        if c["id"] != consent["id"] and c["senior_record_id"] == consent["senior_record_id"] and c["status"] == "GRANTED":
            errors.raise_error(errors.ERR_CONSENT_ALREADY_ACTIVE, "Another GRANTED consent exists for this senior")
    consent["status"] = "GRANTED"
    touch(consent)
    core.consent_restore_cascade(consent["senior_record_id"])
    return success_object(core.serialize(consent))
