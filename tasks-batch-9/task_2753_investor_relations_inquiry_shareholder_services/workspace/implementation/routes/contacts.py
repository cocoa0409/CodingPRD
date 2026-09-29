"""Contact register, servicing and estimate filing (PRD §3.2, §3.3, §3.7)."""
from decimal import Decimal

from flask import Blueprint

import calc
import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import contact_out, estimate_out
from store import (ACTIVIST_STAKE_THRESHOLD_PCT, CONTACT_TYPES, COVERAGE_STATUSES,
                   ESTIMATE_STATUSES, HOLDER_TYPES, METRICS, TARGET_TIERS,
                   THREAT_LEVELS, new_row, sorted_rows, store, touch)

bp = Blueprint("contacts", __name__)

SERVICING_ACTIONS = ["GRANT_MODEL_ACCESS", "REVOKE_MODEL_ACCESS", "SET_THREAT_LEVEL"]


@bp.post("/contacts")
def create_contact():
    V.authorize("IRAdmin")
    b = V.body()
    company_id = V.f_str(b, "company_id", required=True)
    contact_type = V.f_enum(b, "contact_type", CONTACT_TYPES, required=True)
    display_name = V.f_str(b, "display_name", required=True, max_len=160)
    email = V.f_str(b, "email", required=True)
    if "@" not in email:
        V.bad("email must contain '@'")
    shares_held = V.f_int(b, "shares_held", default=0, minimum=0)
    nda_on_file = V.f_bool(b, "nda_on_file", default=False)
    coverage_status = V.f_enum(b, "coverage_status", COVERAGE_STATUSES, default="NOT_COVERING")
    activist_flag = V.f_bool(b, "activist_flag", default=False)

    company = V.get_company(company_id)

    contact = new_row({
        "company_id": company["id"],
        "contact_type": contact_type,
        "display_name": display_name,
        "email": email,
        "shares_held": shares_held,
        "ownership_pct": Decimal("0.0000"),
        "target_tier": "UNTIERED",
        "nda_on_file": nda_on_file,
        "model_access_status": "NONE",
        "coverage_status": coverage_status,
        "activist_flag": activist_flag,
        "threat_level": "NONE",
        "dividend_received_cents": 0,
    })
    calc.apply_ownership(contact, company)
    store.contacts[contact["id"]] = contact
    return created(contact_out(contact))


@bp.get("/contacts")
def list_contacts():
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "TransferAgentLiaison")
    limit, offset = V.q_pagination()
    company_id = V.q_str("company_id")
    contact_type = V.q_enum("contact_type", CONTACT_TYPES)
    tier = V.q_enum("target_tier", TARGET_TIERS)
    coverage_status = V.q_enum("coverage_status", COVERAGE_STATUSES)
    activist_flag = V.q_bool("activist_flag")
    rows = sorted_rows(store.contacts)
    if company_id is not None:
        rows = [r for r in rows if r["company_id"] == company_id]
    if contact_type is not None:
        rows = [r for r in rows if r["contact_type"] == contact_type]
    if tier is not None:
        rows = [r for r in rows if r["target_tier"] == tier]
    if coverage_status is not None:
        rows = [r for r in rows if r["coverage_status"] == coverage_status]
    if activist_flag is not None:
        rows = [r for r in rows if r["activist_flag"] == activist_flag]
    page, total = paginate(rows, limit, offset)
    return ok_list([contact_out(r) for r in page], limit, offset, total)


@bp.get("/contacts/<contact_id>")
def read_contact(contact_id):
    actor = V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "TransferAgentLiaison", "Investor")
    contact = V.get_contact(contact_id)
    V.own_contact(actor, contact_id)
    return ok(contact_out(contact))


@bp.patch("/contacts/<contact_id>/position")
def update_position(contact_id):
    V.authorize("IRAdmin")
    b = V.body()
    shares_held = V.f_int(b, "shares_held", required=True, minimum=0)
    expected_company_version = V.f_int(b, "expected_company_version", required=True, minimum=0)

    contact = V.get_contact(contact_id)
    company = store.companies.get(contact["company_id"])

    if company is None or expected_company_version != company["version"]:
        raise ApiError("ERR_STALE_COMPANY_VERSION",
                       "expected_company_version does not match the issuer's current version")

    total = shares_held if contact["contact_type"] in HOLDER_TYPES else 0
    for other in store.contacts.values():
        if other["id"] == contact["id"]:
            continue
        if other["company_id"] != company["id"]:
            continue
        if other["contact_type"] in HOLDER_TYPES:
            total += other["shares_held"]
    if total > company["shares_outstanding"]:
        raise ApiError("ERR_SHARES_EXCEED_OUTSTANDING",
                       "summed holder positions would exceed shares_outstanding")

    contact["shares_held"] = shares_held
    calc.apply_ownership(contact, company)
    # §3.2 activist stake escalation, read by the posture re-derivation below
    if (contact["activist_flag"]
            and contact["ownership_pct"] >= ACTIVIST_STAKE_THRESHOLD_PCT
            and contact["threat_level"] in ("NONE", "WATCH")):
        contact["threat_level"] = "ELEVATED"
    touch(contact)
    calc.posture_write(company, recount=False)
    return ok(contact_out(contact))


@bp.post("/contacts/<contact_id>/servicing")
def servicing(contact_id):
    V.authorize("IRAdmin", "DisclosureOfficer")
    b = V.body()
    action = V.f_enum(b, "action", SERVICING_ACTIONS, required=True)
    threat_level = V.f_enum(b, "threat_level", THREAT_LEVELS,
                            required=(action == "SET_THREAT_LEVEL"))

    contact = V.get_contact(contact_id)
    company = store.companies.get(contact["company_id"])

    if action == "GRANT_MODEL_ACCESS":
        if contact["contact_type"] != "SELL_SIDE_ANALYST":
            raise ApiError("ERR_MODEL_ACCESS_NOT_ELIGIBLE",
                           "model access is only available to a SELL_SIDE_ANALYST")
        if not contact["nda_on_file"]:
            raise ApiError("ERR_NDA_REQUIRED", "a signed NDA must be on file")
        if company is not None and company["disclosure_posture"] == "BLACKOUT":
            raise ApiError("ERR_DISCLOSURE_BLACKOUT",
                           "the issuer's disclosure posture is BLACKOUT")
        contact["model_access_status"] = "GRANTED"
        touch(contact)
    elif action == "REVOKE_MODEL_ACCESS":
        if contact["model_access_status"] != "GRANTED":
            raise ApiError("ERR_MODEL_ACCESS_NOT_ELIGIBLE",
                           "model access is not currently GRANTED")
        contact["model_access_status"] = "REVOKED"
        touch(contact)
    else:
        contact["threat_level"] = threat_level
        touch(contact)
        if company is not None:
            calc.posture_write(company, recount=False)
    return ok(contact_out(contact))


@bp.get("/contacts/<contact_id>/estimates")
def list_contact_estimates(contact_id):
    actor = V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "Investor")
    limit, offset = V.q_pagination()
    metric = V.q_enum("metric", METRICS)
    period_label = V.q_str("period_label")
    status = V.q_enum("status", ESTIMATE_STATUSES)

    V.get_contact(contact_id)
    V.own_contact(actor, contact_id)

    rows = [r for r in sorted_rows(store.estimates) if r["contact_id"] == contact_id]
    if metric is not None:
        rows = [r for r in rows if r["metric"] == metric]
    if period_label is not None:
        rows = [r for r in rows if r["period_label"] == period_label]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([estimate_out(r) for r in page], limit, offset, total)


@bp.post("/estimates")
def create_estimate():
    actor = V.authorize("Investor")
    b = V.body()
    contact_id = V.f_str(b, "contact_id", required=True)
    metric = V.f_enum(b, "metric", METRICS, required=True)
    period_label = V.f_str(b, "period_label", required=True, max_len=20)
    value = V.f_num(b, "value", required=True, exclusive_min=0)
    expected_contact_version = V.f_int(b, "expected_contact_version", required=True, minimum=0)

    contact = V.get_contact(contact_id)
    V.own_contact(actor, contact_id)

    if expected_contact_version != contact["version"]:
        raise ApiError("ERR_STALE_CONTACT_VERSION",
                       "expected_contact_version does not match the contact's current version")

    if contact["model_access_status"] != "GRANTED":
        raise ApiError("ERR_MODEL_ACCESS_REQUIRED", "the filing contact has no model access")
    if contact["contact_type"] != "SELL_SIDE_ANALYST" or contact["coverage_status"] != "INITIATED":
        raise ApiError("ERR_COVERAGE_NOT_INITIATED",
                       "the filing contact must be a SELL_SIDE_ANALYST with coverage INITIATED")

    for prior in sorted_rows(store.estimates):
        if (prior["contact_id"] == contact["id"] and prior["metric"] == metric
                and prior["period_label"] == period_label and prior["status"] == "ACCEPTED"):
            prior["status"] = "SUPERSEDED"
            touch(prior)

    estimate = new_row({
        "contact_id": contact["id"],
        "metric": metric,
        "period_label": period_label,
        "value": value,
        "submitted_at": store.now(),
        "status": "ACCEPTED",
    })
    store.estimates[estimate["id"]] = estimate
    touch(contact)
    return created(estimate_out(estimate))
