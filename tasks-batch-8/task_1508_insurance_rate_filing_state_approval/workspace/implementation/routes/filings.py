"""RateFiling routes plus FilingComponent and Deviation routes."""
from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import compute_deemer_date
from envelope import list_response, serialize, success
from errors import (
    err,
    ERR_CHANGE_EXCEEDS_MAX,
    ERR_COMPONENT_INCOMPLETE,
    ERR_DEVIATION_NOT_USABLE,
    ERR_DISAPPROVAL_WINDOW_CLOSED,
    ERR_DUPLICATE_OPEN_FILING,
    ERR_EFFECTIVE_DATE_NOT_REACHED,
    ERR_EFFECTIVE_LEAD_VIOLATION,
    ERR_INDICATION_NOT_LOCKED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OPEN_OBJECTIONS,
    ERR_PROFILE_INACTIVE,
    ERR_RATEBOOK_OVERLAP,
    ERR_WAVE_NOT_REVERSIBLE,
)
from fields import DEVIATION, FILING_COMPONENT, RATE_FILING
from store import db, now, touch
from timeutil import end_of_day_utc, parse_date
from validate import (
    apply_filters, get_json_body, paginate, v_date, v_enum, v_number,
    v_pos_number, v_state_code, v_string, validate_body,
)
from workflows import (
    base_entity,
    cascade_filing_withdrawn,
    cancel_wave,
    create_calendar_entry,
    entry_mark_met,
    entry_waive,
    find_entries,
    get_or_404,
    reanchor_effective_date_entry,
    recompute_filing_objections,
    reverse_wave,
    approve_filing_common,
    _withdraw_objection,
    _supersede_components,
)

bp = Blueprint("filings", __name__)

FILING_TYPES = {"RATE_CHANGE", "RATE_RULE_FORM", "RULE_ONLY", "FORM_ONLY"}
OPEN_FILING_STATUSES = {
    "DRAFT", "READY", "SUBMITTED", "UNDER_OBJECTION", "APPROVED", "DEEMED_APPROVED",
}
REQUIRED_FINAL_COMPONENT = {
    "RATE_CHANGE": "RATE",
    "RATE_RULE_FORM": "RATE",
    "RULE_ONLY": "RULE",
    "FORM_ONLY": "FORM",
}
DEVIATION_TYPES = {"RATE_FACTOR", "RULE_TEXT", "FORM_TEXT"}
COMPONENT_TYPES = {"RATE", "RULE", "FORM"}


def _find_profile(product_id, state_code):
    for p in db.state_profiles.values():
        if p["product_id"] == product_id and p["state_code"] == state_code:
            return p
    return None


# --- filings --------------------------------------------------------------------

@bp.route("/filings", methods=["POST"])
def create_filing():
    authenticate({"FilingAnalyst"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "product_id": (True, v_string),
        "state_code": (True, v_state_code),
        "filing_type": (True, v_enum(FILING_TYPES)),
        "proposed_change_pct": (True, v_number),
        "proposed_effective_date": (True, v_date),
        "indication_id": (True, v_string),
    })
    with db.lock:
        # existence, left to right: product -> resolved profile -> indication
        get_or_404(db.products, data["product_id"])
        profile = _find_profile(data["product_id"], data["state_code"])
        if profile is None:
            raise err(ERR_NOT_FOUND)
        indication = get_or_404(db.rate_indications, data["indication_id"])
        # referenced configuration usability
        if profile["status"] != "ACTIVE":
            raise err(ERR_PROFILE_INACTIVE)
        if indication["status"] != "LOCKED":
            raise err(ERR_INDICATION_NOT_LOCKED)
        # structural: at most one open filing per (product, state)
        for f in db.rate_filings.values():
            if (
                f["product_id"] == data["product_id"]
                and f["state_code"] == data["state_code"]
                and f["status"] in OPEN_FILING_STATUSES
            ):
                raise err(ERR_DUPLICATE_OPEN_FILING)
        # monetary ceiling
        if data["proposed_change_pct"] > profile["max_single_change_pct"]:
            raise err(ERR_CHANGE_EXCEEDS_MAX)
        filing = base_entity()
        filing.update({
            "product_id": data["product_id"],
            "profile_id": profile["id"],
            "indication_id": data["indication_id"],
            "state_code": data["state_code"],
            "filing_type": data["filing_type"],
            "proposed_change_pct": data["proposed_change_pct"],
            "proposed_effective_date": data["proposed_effective_date"],
            "filing_number": None,
            "status": "DRAFT",
            "submitted_at": None,
            "approved_at": None,
            "actual_effective_date": None,
            "deemer_date": None,
            "superseded_at_date": None,
            "open_objection_count": 0,
        })
        db.rate_filings[filing["id"]] = filing
    return success(serialize(filing, RATE_FILING), code=201)


@bp.route("/filings/<filingId>", methods=["GET"])
def get_filing(filingId):
    authenticate(ALL_ROLES)
    filing = get_or_404(db.rate_filings, filingId)
    return success(serialize(filing, RATE_FILING), code=200)


@bp.route("/filings", methods=["GET"])
def list_filings():
    authenticate(ALL_ROLES)
    filters = {
        "product_id": request.args.get("product_id"),
        "profile_id": request.args.get("profile_id"),
        "indication_id": request.args.get("indication_id"),
        "state_code": request.args.get("state_code"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.rate_filings.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(f, RATE_FILING) for f in page], total, limit, offset)


@bp.route("/filings/<filingId>/mark-ready", methods=["POST"])
def mark_ready(filingId):
    authenticate({"FilingAnalyst"})
    with db.lock:
        filing = get_or_404(db.rate_filings, filingId)
        if filing["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE)
        required = REQUIRED_FINAL_COMPONENT[filing["filing_type"]]
        complete = any(
            c["filing_id"] == filing["id"]
            and c["component_type"] == required
            and c["status"] == "FINAL"
            for c in db.filing_components.values()
        )
        if not complete:
            raise err(ERR_COMPONENT_INCOMPLETE)
        filing["status"] = "READY"
        touch(filing)
    return success(serialize(filing, RATE_FILING), code=200)


@bp.route("/filings/<filingId>/submit", methods=["POST"])
def submit_filing(filingId):
    authenticate({"ComplianceOfficer"})
    with db.lock:
        filing = get_or_404(db.rate_filings, filingId)
        if filing["status"] != "READY":
            raise err(ERR_INVALID_STATE)
        profile = db.state_profiles.get(filing["profile_id"])
        indication = db.rate_indications.get(filing["indication_id"])
        # referenced configuration usability
        if profile is None or profile["status"] != "ACTIVE":
            raise err(ERR_PROFILE_INACTIVE)
        if indication is None or indication["status"] != "LOCKED":
            raise err(ERR_INDICATION_NOT_LOCKED)
        for d in db.deviations.values():
            if d["filing_id"] == filing["id"] and d["status"] not in ("PROPOSED", "APPROVED"):
                raise err(ERR_DEVIATION_NOT_USABLE)
        # temporal: effective-date lead rule
        submit_date = now().date()
        proposed = parse_date(filing["proposed_effective_date"])
        if profile["filing_method"] == "PRIOR_APPROVAL":
            earliest = submit_date + timedelta(days=profile["min_effective_lead_days"])
            if proposed < earliest:
                raise err(ERR_EFFECTIVE_LEAD_VIOLATION)
        else:
            if proposed < submit_date:
                raise err(ERR_EFFECTIVE_LEAD_VIOLATION)
        # monetary ceiling re-check
        if filing["proposed_change_pct"] > profile["max_single_change_pct"]:
            raise err(ERR_CHANGE_EXCEEDS_MAX)
        # side effects
        filing["status"] = "SUBMITTED"
        filing["submitted_at"] = now()
        seq = db.filing_seq_by_state.get(filing["state_code"], 0) + 1
        db.filing_seq_by_state[filing["state_code"]] = seq
        filing["filing_number"] = f"FIL-{filing['state_code']}-{seq:06d}"
        filing["deemer_date"] = compute_deemer_date(profile, filing["submitted_at"])
        touch(filing)
        if filing["deemer_date"] is not None:
            create_calendar_entry(
                "DEEMER_DATE",
                end_of_day_utc(parse_date(filing["deemer_date"])),
                filing_id=filing["id"],
            )
        create_calendar_entry(
            "EFFECTIVE_DATE",
            end_of_day_utc(parse_date(filing["proposed_effective_date"])),
            filing_id=filing["id"],
        )
    return success(serialize(filing, RATE_FILING), code=200)


@bp.route("/filings/<filingId>/approve", methods=["POST"])
def approve_filing(filingId):
    authenticate({"StateRegulator"})
    with db.lock:
        filing = get_or_404(db.rate_filings, filingId)
        if filing["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE)
        if filing["open_objection_count"] != 0:
            raise err(ERR_OPEN_OBJECTIONS)
        profile = db.state_profiles.get(filing["profile_id"])
        filing["status"] = "APPROVED"
        touch(filing)
        approve_filing_common(filing, profile, now())
    return success(serialize(filing, RATE_FILING), code=200)


@bp.route("/filings/<filingId>/disapprove", methods=["POST"])
def disapprove_filing(filingId):
    authenticate({"StateRegulator"})
    with db.lock:
        filing = get_or_404(db.rate_filings, filingId)
        status = filing["status"]
        profile = db.state_profiles.get(filing["profile_id"])
        if status in ("SUBMITTED", "UNDER_OBJECTION"):
            if status == "UNDER_OBJECTION":
                for o in db.objections.values():
                    if o["filing_id"] == filing["id"]:
                        _withdraw_objection(o)
            for e in find_entries("DEEMER_DATE", filing_id=filing["id"]):
                entry_waive(e)
            for e in find_entries("EFFECTIVE_DATE", filing_id=filing["id"]):
                entry_waive(e)
            filing["status"] = "DISAPPROVED"
            touch(filing)
        elif status == "EFFECTIVE":
            # post-effective disapproval gates
            if profile["filing_method"] not in ("FILE_AND_USE", "USE_AND_FILE"):
                raise err(ERR_INVALID_STATE)
            deadline = parse_date(filing["actual_effective_date"]) + timedelta(
                days=profile["disapproval_window_days"]
            )
            if now().date() > deadline:
                raise err(ERR_DISAPPROVAL_WINDOW_CLOSED)
            for w in db.implementation_waves.values():
                if w["filing_id"] == filing["id"] and w["status"] == "COMPLETED":
                    raise err(ERR_WAVE_NOT_REVERSIBLE)
            # three-hop cascade
            for w in list(db.implementation_waves.values()):
                if w["filing_id"] != filing["id"]:
                    continue
                if w["status"] == "RELEASED":
                    reverse_wave(w)
                elif w["status"] == "SCHEDULED":
                    cancel_wave(w)
            _supersede_components(filing)
            for d in db.deviations.values():
                if d["filing_id"] == filing["id"] and d["status"] == "APPROVED":
                    d["status"] = "SUPERSEDED"
                    touch(d)
            filing["status"] = "DISAPPROVED"
            touch(filing)
        else:
            raise err(ERR_INVALID_STATE)
    return success(serialize(filing, RATE_FILING), code=200)


@bp.route("/filings/<filingId>/mark-effective", methods=["POST"])
def mark_effective(filingId):
    authenticate({"ComplianceOfficer"})
    with db.lock:
        filing = get_or_404(db.rate_filings, filingId)
        profile = db.state_profiles.get(filing["profile_id"])
        status = filing["status"]
        if status in ("APPROVED", "DEEMED_APPROVED"):
            if now().date() < parse_date(filing["actual_effective_date"]):
                raise err(ERR_EFFECTIVE_DATE_NOT_REACHED)
        elif status == "SUBMITTED":
            # use-and-file shortcut: effectiveness may precede approval
            if profile["filing_method"] != "USE_AND_FILE":
                raise err(ERR_INVALID_STATE)
            if now().date() < parse_date(filing["proposed_effective_date"]):
                raise err(ERR_EFFECTIVE_DATE_NOT_REACHED)
            filing["actual_effective_date"] = filing["proposed_effective_date"]
        else:
            raise err(ERR_INVALID_STATE)
        new_eff = filing["actual_effective_date"]
        # ratebook overlap: no EFFECTIVE filing of this book may have
        # actual_effective_date >= the incoming one (equality is an overlap)
        incumbent = None
        for other in db.rate_filings.values():
            if (
                other["id"] == filing["id"]
                or other["status"] != "EFFECTIVE"
                or other["product_id"] != filing["product_id"]
                or other["state_code"] != filing["state_code"]
            ):
                continue
            if other["actual_effective_date"] >= new_eff:
                raise err(ERR_RATEBOOK_OVERLAP)
            if incumbent is None or other["actual_effective_date"] > incumbent["actual_effective_date"]:
                incumbent = other
        filing["status"] = "EFFECTIVE"
        touch(filing)
        if incumbent is not None:
            incumbent["status"] = "SUPERSEDED"
            incumbent["superseded_at_date"] = new_eff
            touch(incumbent)
            _supersede_components(incumbent)
            for d in db.deviations.values():
                if d["filing_id"] == incumbent["id"] and d["status"] == "APPROVED":
                    d["status"] = "SUPERSEDED"
                    touch(d)
        for e in find_entries("EFFECTIVE_DATE", filing_id=filing["id"]):
            entry_mark_met(e)
    return success(serialize(filing, RATE_FILING), code=200)


@bp.route("/filings/<filingId>/withdraw", methods=["POST"])
def withdraw_filing(filingId):
    authenticate({"FilingAnalyst", "ComplianceOfficer"})
    with db.lock:
        filing = get_or_404(db.rate_filings, filingId)
        if filing["status"] not in (
            "DRAFT", "READY", "SUBMITTED", "UNDER_OBJECTION", "APPROVED", "DEEMED_APPROVED",
        ):
            raise err(ERR_INVALID_STATE)
        cascade_filing_withdrawn(filing, filing["status"])
    return success(serialize(filing, RATE_FILING), code=200)


# --- components -------------------------------------------------------------------

@bp.route("/filings/<filingId>/components", methods=["POST"])
def create_component(filingId):
    authenticate({"FilingAnalyst"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "component_type": (True, v_enum(COMPONENT_TYPES)),
        "name": (True, v_string),
        "content_ref": (True, v_string),
    })
    with db.lock:
        filing = get_or_404(db.rate_filings, filingId)
        if filing["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE)
        component = base_entity()
        component.update({
            "filing_id": filing["id"],
            "component_type": data["component_type"],
            "name": data["name"],
            "content_ref": data["content_ref"],
            "status": "DRAFT",
        })
        db.filing_components[component["id"]] = component
    return success(serialize(component, FILING_COMPONENT), code=201)


@bp.route("/components/<componentId>", methods=["GET"])
def get_component(componentId):
    authenticate(ALL_ROLES)
    component = get_or_404(db.filing_components, componentId)
    return success(serialize(component, FILING_COMPONENT), code=200)


@bp.route("/components", methods=["GET"])
def list_components():
    authenticate(ALL_ROLES)
    filters = {
        "filing_id": request.args.get("filing_id"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.filing_components.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(c, FILING_COMPONENT) for c in page], total, limit, offset)


@bp.route("/components/<componentId>/finalize", methods=["POST"])
def finalize_component(componentId):
    authenticate({"FilingAnalyst"})
    with db.lock:
        component = get_or_404(db.filing_components, componentId)
        if component["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE)
        filing = db.rate_filings.get(component["filing_id"])
        if filing is None or filing["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE)
        component["status"] = "FINAL"
        touch(component)
    return success(serialize(component, FILING_COMPONENT), code=200)


# --- deviations -------------------------------------------------------------------

@bp.route("/deviations", methods=["POST"])
def create_deviation():
    authenticate({"FilingAnalyst"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "filing_id": (True, v_string),
        "deviation_type": (True, v_enum(DEVIATION_TYPES)),
        "base_reference": (True, v_string),
        "deviation_factor": (True, v_pos_number),
        "justification": (True, v_string),
    })
    with db.lock:
        filing = get_or_404(db.rate_filings, data["filing_id"])
        if filing["status"] not in ("DRAFT", "READY", "SUBMITTED", "UNDER_OBJECTION"):
            raise err(ERR_INVALID_STATE)
        deviation = base_entity()
        deviation.update({
            "filing_id": data["filing_id"],
            "deviation_type": data["deviation_type"],
            "base_reference": data["base_reference"],
            "deviation_factor": data["deviation_factor"],
            "justification": data["justification"],
            "status": "PROPOSED",
        })
        db.deviations[deviation["id"]] = deviation
    return success(serialize(deviation, DEVIATION), code=201)


@bp.route("/deviations/<deviationId>", methods=["GET"])
def get_deviation(deviationId):
    authenticate(ALL_ROLES)
    deviation = get_or_404(db.deviations, deviationId)
    return success(serialize(deviation, DEVIATION), code=200)


@bp.route("/deviations", methods=["GET"])
def list_deviations():
    authenticate(ALL_ROLES)
    filters = {
        "filing_id": request.args.get("filing_id"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.deviations.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(d, DEVIATION) for d in page], total, limit, offset)


def _regulator_adjudicate(deviationId, target):
    authenticate({"StateRegulator"})
    with db.lock:
        deviation = get_or_404(db.deviations, deviationId)
        if deviation["status"] != "PROPOSED":
            raise err(ERR_INVALID_STATE)
        filing = db.rate_filings.get(deviation["filing_id"])
        if filing is None or filing["status"] not in ("SUBMITTED", "UNDER_OBJECTION"):
            raise err(ERR_INVALID_STATE)
        deviation["status"] = target
        touch(deviation)
    return success(serialize(deviation, DEVIATION), code=200)


@bp.route("/deviations/<deviationId>/approve", methods=["POST"])
def approve_deviation(deviationId):
    return _regulator_adjudicate(deviationId, "APPROVED")


@bp.route("/deviations/<deviationId>/reject", methods=["POST"])
def reject_deviation(deviationId):
    return _regulator_adjudicate(deviationId, "REJECTED")


@bp.route("/deviations/<deviationId>/withdraw", methods=["POST"])
def withdraw_deviation(deviationId):
    authenticate({"FilingAnalyst"})
    with db.lock:
        deviation = get_or_404(db.deviations, deviationId)
        if deviation["status"] != "PROPOSED":
            raise err(ERR_INVALID_STATE)
        deviation["status"] = "WITHDRAWN"
        touch(deviation)
    return success(serialize(deviation, DEVIATION), code=200)
