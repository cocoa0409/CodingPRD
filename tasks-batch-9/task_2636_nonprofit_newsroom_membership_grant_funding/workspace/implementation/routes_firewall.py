"""Coverage areas, funders, firewall disclosures and influence contacts
(§3.4 and §3.5)."""

from flask import Blueprint

import calc
import derive
import guards
from core import (
    DB, ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
    ROLE_FINANCE_CONTROLLER, ROLE_MEMBER, acting_user, apply_changes,
    authenticate, body, fail, iso_ms, list_response, lookup, lookup_fk, new_row,
    now_clock, object_response, pagination, paginate, public, q_enum,
    q_str, rows, touch, v_bool, v_bps, v_enum, v_instant, v_int, v_str,
)
from routes_fiscal import finalize_create

bp = Blueprint("firewall", __name__)

AREA_READ_ROLES = (ROLE_EDITORIAL_DIRECTOR, ROLE_DEVELOPMENT_OFFICER,
                   ROLE_FINANCE_CONTROLLER, ROLE_BOARD_OVERSIGHT, ROLE_MEMBER)
FUNDER_READ_ROLES = (ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
                     ROLE_FINANCE_CONTROLLER, ROLE_BOARD_OVERSIGHT)
DISCLOSURE_READ_ROLES = (ROLE_EDITORIAL_DIRECTOR, ROLE_DEVELOPMENT_OFFICER,
                         ROLE_BOARD_OVERSIGHT, ROLE_FINANCE_CONTROLLER)
CONTACT_READ_ROLES = (ROLE_EDITORIAL_DIRECTOR, ROLE_DEVELOPMENT_OFFICER,
                      ROLE_BOARD_OVERSIGHT)


def get_area(area_id):
    return lookup("coverage_areas", area_id, "ERR_COVERAGE_AREA_NOT_FOUND")


def get_funder(funder_id):
    return lookup("funders", funder_id, "ERR_FUNDER_NOT_FOUND")


def get_disclosure(disclosure_id):
    return lookup("firewall_disclosures", disclosure_id, "ERR_DISCLOSURE_NOT_FOUND")


# ---------------------------------------------------------------------------
# Coverage areas
# ---------------------------------------------------------------------------

@bp.post("/coverage-areas")
def create_coverage_area():
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    data = body()
    area_code = v_str(data, "area_code", min_len=2, max_len=32, pattern=r"^[A-Z_]+$")
    guards.require_unique("coverage_areas", "area_code", area_code,
                          "area_code must be unique")
    name = v_str(data, "name", min_len=1)
    editorial_lead_user_id = v_str(data, "editorial_lead_user_id", min_len=1)
    area = new_row("coverage_areas", {
        "area_code": area_code,
        "name": name,
        "editorial_lead_user_id": editorial_lead_user_id,
        "disclosure_status": "CURRENT",
        "publication_gate": "OPEN",
        "restricted_grant_count": 0,
        "disclosed_funder_count": 0,
    })
    return object_response(public(area), 201)


@bp.get("/coverage-areas/<area_id>")
def read_coverage_area(area_id):
    authenticate(*AREA_READ_ROLES)
    return object_response(public(get_area(area_id)))


@bp.get("/coverage-areas")
def list_coverage_areas():
    authenticate(*AREA_READ_ROLES)
    gate = q_enum("publication_gate", calc.PUBLICATION_GATES)
    freshness = q_enum("disclosure_status", calc.DISCLOSURE_FRESHNESS)
    limit, offset = pagination()
    items = [a for a in rows("coverage_areas")
             if (gate is None or a["publication_gate"] == gate)
             and (freshness is None or a["disclosure_status"] == freshness)]
    page, total = paginate(items, limit, offset)
    return list_response([public(a) for a in page], total, limit, offset)


@bp.get("/coverage-areas/<area_id>/transparency-report")
def coverage_area_transparency_report(area_id):
    authenticate(*AREA_READ_ROLES)
    area = get_area(area_id)
    pagination()
    funder_ids = derive.disclosed_funder_ids(area["id"])
    total_committed = 0
    for funder_id in funder_ids:
        funder = DB["funders"].get(funder_id)
        if funder is not None:
            total_committed += int(funder.get("lifetime_committed_cents") or 0)
    return object_response({
        "area_code": area["area_code"],
        "publication_gate": area["publication_gate"],
        "disclosure_status": area["disclosure_status"],
        "disclosed_funder_count": area["disclosed_funder_count"],
        "restricted_grant_count": area["restricted_grant_count"],
        "disclosed_funder_ids": funder_ids,
        "total_committed_cents": total_committed,
    })


# ---------------------------------------------------------------------------
# Funders
# ---------------------------------------------------------------------------

@bp.post("/funders")
def create_funder():
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    data = body()
    area = lookup_fk("coverage_areas", data.get("affiliated_coverage_area_id"),
                     "ERR_COVERAGE_AREA_NOT_FOUND")
    legal_name = v_str(data, "legal_name", min_len=1)
    guards.require_unique("funders", "legal_name", legal_name,
                          "legal_name must be unique")
    funder_type = v_enum(data, "funder_type", calc.FUNDER_TYPES)
    self_attested_advocacy = v_bool(data, "self_attested_advocacy", required=False,
                                    default=False)
    funder = new_row("funders", {
        "legal_name": legal_name,
        "funder_type": funder_type,
        "affiliated_coverage_area_id": area["id"] if area else None,
        "self_attested_advocacy": self_attested_advocacy,
        "audited_advocacy_index": None,
        "risk_basis": "SELF_ATTESTED",
        "prior_editorial_requests_count": 0,
        "reporting_reliability_bps": 10000,
        "independence_risk_score": 0,
        "status": "PROSPECT",
        "cultivated_by_user_id": acting_user(),
        "cleared_by_user_id": None,
        "lifetime_committed_cents": 0,
        "restricted_at": None,
    })
    derive.recompute_funder(funder)
    return object_response(public(finalize_create(funder)), 201)


@bp.get("/funders/<funder_id>")
def read_funder(funder_id):
    authenticate(*FUNDER_READ_ROLES)
    return object_response(public(get_funder(funder_id)))


@bp.get("/funders")
def list_funders():
    authenticate(*FUNDER_READ_ROLES)
    area_id = q_str("affiliated_coverage_area_id")
    status = q_enum("status", calc.FUNDER_STATUSES)
    funder_type = q_enum("funder_type", calc.FUNDER_TYPES)
    risk_basis = q_enum("risk_basis", calc.RISK_BASES)
    limit, offset = pagination()
    items = []
    for funder in rows("funders"):
        if area_id is not None and funder["affiliated_coverage_area_id"] != area_id:
            continue
        if status is not None and funder["status"] != status:
            continue
        if funder_type is not None and funder["funder_type"] != funder_type:
            continue
        if risk_basis is not None and funder["risk_basis"] != risk_basis:
            continue
        items.append(funder)
    page, total = paginate(items, limit, offset)
    return list_response([public(f) for f in page], total, limit, offset)


@bp.post("/funders/<funder_id>/independence-clearance")
def funder_independence_clearance(funder_id):
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    funder = get_funder(funder_id)
    data = body()
    decision = v_enum(data, "decision", ("CLEAR", "RESTRICT"))
    basis = v_enum(data, "basis", calc.RISK_BASES)
    audited_advocacy_index = v_bps(data, "audited_advocacy_index", required=False,
                                   default=None, minimum=0, maximum=10)
    v_str(data, "reason", required=False, default=None, min_len=0)
    if basis == "AUDITED" and audited_advocacy_index is None:
        fail("ERR_INVALID_REQUEST", "the AUDITED basis requires audited_advocacy_index")

    if decision == "CLEAR":
        guards.require_state(funder["status"], ("PROSPECT", "RESTRICTED"), "funder")
    else:
        guards.require_state(funder["status"], ("PROSPECT", "CLEARED"), "funder")
    guards.require_dual_control(funder.get("cultivated_by_user_id"))

    overrides = {"risk_basis": basis}
    if basis == "AUDITED":
        overrides["audited_advocacy_index"] = audited_advocacy_index
    score, _reliability, _requests = derive.funder_risk_preview(funder, overrides)

    if decision == "CLEAR":
        guards.require_risk_below_hard_bar(score)
        if score >= calc.RISK_DISCLOSURE_FLOOR:
            guards.require_active_disclosure(
                funder["id"], funder.get("affiliated_coverage_area_id"))
        if funder["status"] == "RESTRICTED":
            guards.require_no_stale_disclosure(funder["id"])
        overrides["status"] = "CLEARED"
        overrides["cleared_by_user_id"] = acting_user()
        derive.recompute_funder(funder, overrides)
    else:
        derive.restrict_funder(funder, "FUNDER_RESTRICTED", extra=overrides)
    return object_response(public(funder))


# ---------------------------------------------------------------------------
# Firewall disclosures
# ---------------------------------------------------------------------------

@bp.post("/firewall-disclosures")
def create_firewall_disclosure():
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    data = body()
    funder = lookup_fk("funders", data.get("funder_id"), "ERR_FUNDER_NOT_FOUND")
    if funder is None:
        fail("ERR_INVALID_REQUEST", "funder_id is required")
    area = lookup_fk("coverage_areas", data.get("coverage_area_id"),
                     "ERR_COVERAGE_AREA_NOT_FOUND")
    if area is None:
        fail("ERR_INVALID_REQUEST", "coverage_area_id is required")
    target = lookup_fk("firewall_disclosures", data.get("supersedes_disclosure_id"),
                       "ERR_DISCLOSURE_NOT_FOUND")
    disclosure_text = v_str(data, "disclosure_text", min_len=20, max_len=2000)
    expected_funder_version = v_int(data, "expected_funder_version")

    if target is not None:
        if (target["status"] not in ("ACTIVE", "REATTESTATION_REQUIRED")
                or target["funder_id"] != funder["id"]
                or target["coverage_area_id"] != area["id"]):
            fail("ERR_SUPERSEDE_TARGET_INVALID",
                 "the superseded disclosure is not a live disclosure of the same pair")
    if expected_funder_version != int(funder["version"]):
        fail("ERR_STALE_FUNDER_VERSION",
             "expected_funder_version %s does not match %s"
             % (expected_funder_version, funder["version"]))
    guards.require_dual_control(funder.get("cultivated_by_user_id"))

    disclosure = new_row("firewall_disclosures", {
        "funder_id": funder["id"],
        "coverage_area_id": area["id"],
        "supersedes_disclosure_id": target["id"] if target else None,
        "disclosure_text": disclosure_text,
        "status": "ACTIVE",
        "attested_by_user_id": acting_user(),
        "attested_at": iso_ms(now_clock()),
        "reattestation_reason": None,
    })
    if target is not None:
        apply_changes(target, {"status": "SUPERSEDED"})
    derive.recompute_funder(funder)
    if int(funder["version"]) == expected_funder_version:
        # The funder's version increments by exactly 1 on every filing, even
        # when no computed funder field moved.
        touch(funder)
    derive.recompute_coverage_area(area)
    return object_response(public(disclosure), 201)


@bp.get("/firewall-disclosures/<disclosure_id>")
def read_firewall_disclosure(disclosure_id):
    authenticate(*DISCLOSURE_READ_ROLES)
    return object_response(public(get_disclosure(disclosure_id)))


@bp.get("/firewall-disclosures")
def list_firewall_disclosures():
    authenticate(*DISCLOSURE_READ_ROLES)
    funder_id = q_str("funder_id")
    area_id = q_str("coverage_area_id")
    supersedes_id = q_str("supersedes_disclosure_id")
    status = q_enum("status", calc.DISCLOSURE_STATUSES)
    limit, offset = pagination()
    items = []
    for disclosure in rows("firewall_disclosures"):
        if funder_id is not None and disclosure["funder_id"] != funder_id:
            continue
        if area_id is not None and disclosure["coverage_area_id"] != area_id:
            continue
        if supersedes_id is not None and disclosure["supersedes_disclosure_id"] != supersedes_id:
            continue
        if status is not None and disclosure["status"] != status:
            continue
        items.append(disclosure)
    page, total = paginate(items, limit, offset)
    return list_response([public(d) for d in page], total, limit, offset)


@bp.post("/firewall-disclosures/<disclosure_id>/attest")
def attest_firewall_disclosure(disclosure_id):
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    disclosure = get_disclosure(disclosure_id)
    data = body()
    void = v_bool(data, "void", required=False, default=False)
    funder = DB["funders"].get(disclosure["funder_id"])
    area = DB["coverage_areas"].get(disclosure["coverage_area_id"])

    guards.require_not_terminal(disclosure["status"], calc.DISCLOSURE_TERMINAL,
                                "firewall disclosure")
    if void:
        guards.require_state(disclosure["status"], ("ACTIVE", "REATTESTATION_REQUIRED"),
                             "firewall disclosure")
    else:
        guards.require_state(disclosure["status"], ("REATTESTATION_REQUIRED",),
                             "firewall disclosure")
        if funder is not None:
            guards.require_dual_control(funder.get("cultivated_by_user_id"))

    if void:
        for proposal in rows("grant_proposals"):
            if (proposal.get("status") == "AWARDED"
                    and proposal.get("funder_id") == disclosure["funder_id"]
                    and proposal.get("coverage_area_id") == disclosure["coverage_area_id"]):
                fail("ERR_DISCLOSURE_IN_USE",
                     "an AWARDED proposal still references this funder and beat")
        apply_changes(disclosure, {"status": "VOID"})
    else:
        apply_changes(disclosure, {
            "status": "ACTIVE",
            "reattestation_reason": None,
            "attested_by_user_id": acting_user(),
            "attested_at": iso_ms(now_clock()),
        })
    if area is not None:
        derive.recompute_coverage_area(area)
    return object_response(public(disclosure))


# ---------------------------------------------------------------------------
# Influence contacts
# ---------------------------------------------------------------------------

@bp.post("/influence-contacts")
def create_influence_contact():
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR)
    data = body()
    funder = lookup_fk("funders", data.get("funder_id"), "ERR_FUNDER_NOT_FOUND")
    if funder is None:
        fail("ERR_INVALID_REQUEST", "funder_id is required")
    area = lookup_fk("coverage_areas", data.get("coverage_area_id"),
                     "ERR_COVERAGE_AREA_NOT_FOUND")
    contact_type = v_enum(data, "contact_type", calc.CONTACT_TYPES)
    occurred_at = v_instant(data, "occurred_at")
    if occurred_at > now_clock():
        fail("ERR_INVALID_REQUEST", "occurred_at may not be later than the logical clock")
    summary = v_str(data, "summary", min_len=10, max_len=1000)

    contact = new_row("influence_contacts", {
        "funder_id": funder["id"],
        "coverage_area_id": area["id"] if area else None,
        "contact_type": contact_type,
        "occurred_at": iso_ms(occurred_at),
        "summary": summary,
        "logged_by_user_id": acting_user(),
        "severity_weight": calc.SEVERITY_WEIGHT[contact_type],
        "triggered_restriction": False,
    }, versioned=False)

    derive.recompute_funder(funder)
    restricts = (contact_type == "EDITORIAL_DIRECTION_REQUEST"
                 or int(funder["independence_risk_score"]) >= calc.RISK_HARD_BAR)
    if restricts and funder["status"] in ("PROSPECT", "CLEARED"):
        contact["triggered_restriction"] = True
        derive.restrict_funder(funder, "INFLUENCE_CONTACT")
    return object_response(public(contact), 201)


@bp.get("/influence-contacts/<contact_id>")
def read_influence_contact(contact_id):
    authenticate(*CONTACT_READ_ROLES)
    return object_response(public(
        lookup("influence_contacts", contact_id, "ERR_INFLUENCE_CONTACT_NOT_FOUND")))


@bp.get("/influence-contacts")
def list_influence_contacts():
    authenticate(*CONTACT_READ_ROLES)
    funder_id = q_str("funder_id")
    area_id = q_str("coverage_area_id")
    contact_type = q_enum("contact_type", calc.CONTACT_TYPES)
    limit, offset = pagination()
    items = []
    for contact in rows("influence_contacts"):
        if funder_id is not None and contact["funder_id"] != funder_id:
            continue
        if area_id is not None and contact["coverage_area_id"] != area_id:
            continue
        if contact_type is not None and contact["contact_type"] != contact_type:
            continue
        items.append(contact)
    # occurred_at ascending, created_at ascending as the tie-break.
    items.sort(key=lambda c: (c["occurred_at"], c["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_response([public(c) for c in page], total, limit, offset)
