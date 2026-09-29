"""Investor interests, the pass-through election and credit claims (PRD 3.7, 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from auth import acting_interest, own_project, require
from clock import clock
from db import base_record, public, store, touch
from errors import ApiError
from response import created_response, object_response
from support import fetch
from validate import as_date, body, req_enum, req_int, req_pct, req_str

bp = Blueprint("investors", __name__)

KINDS = ("MASTER_LEASE_LESSEE", "DIRECT_PARTNER")
TAX_STATUSES = ("TAXABLE_C_CORP", "PARTNERSHIP", "TAX_EXEMPT_ORG", "GOVERNMENTAL_UNIT")
DISQUALIFYING_TAX_STATUSES = ("TAX_EXEMPT_ORG", "GOVERNMENTAL_UNIT")

LEDGER_READ_ROLES = ("PlatformAdmin", "Developer", "InvestorAdmin", "ComplianceMonitor")


def _allocation_total(project_id):
    total = Decimal("0")
    for interest in services.project_interests(project_id):
        if interest["status"] == "ADMITTED":
            total += interest["_pct"]
    return total


def _lessee_of(project_id):
    for interest in services.project_interests(project_id):
        if interest["kind"] == "MASTER_LEASE_LESSEE":
            return interest
    return None


# --------------------------------------------------------------------------
# investor interests
# --------------------------------------------------------------------------


@bp.post("/investor-interests")
def create_interest():
    uid, role = require("InvestorAdmin", "Developer")
    data = body()
    project_id = req_str(data, "project_id")
    kind = req_enum(data, "kind", KINDS)
    party_legal_name = req_str(data, "party_legal_name", min_len=1, max_len=120)
    party_tax_status = req_enum(data, "party_tax_status", TAX_STATUSES)
    capital = req_int(data, "capital_committed_cents", min_v=1)
    pct = req_pct(data, "credit_allocation_pct")
    lease_term = req_int(data, "lease_term_years", min_v=1, max_v=99, required=False)

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    if role == "Developer":
        own_project(project, uid)

    # --- band 10: structure coherence, then party status, then risk ----------
    master_lease = project["structure_type"] == "MASTER_LEASE"
    if kind == "MASTER_LEASE_LESSEE":
        if not master_lease:
            raise ApiError(
                "ERR_STRUCTURE_TYPE_MISMATCH",
                "A single-tier project admits only DIRECT_PARTNER interests.",
            )
        if lease_term is None:
            raise ApiError(
                "ERR_STRUCTURE_TYPE_MISMATCH",
                "A master-lease lessee requires lease_term_years.",
            )
        if _lessee_of(project_id) is not None:
            raise ApiError(
                "ERR_STRUCTURE_TYPE_MISMATCH",
                "A master-lease project admits exactly one MASTER_LEASE_LESSEE.",
            )
    else:
        if master_lease:
            raise ApiError(
                "ERR_STRUCTURE_TYPE_MISMATCH",
                "A master-lease project admits only MASTER_LEASE_LESSEE interests.",
            )
        if lease_term is not None:
            raise ApiError(
                "ERR_STRUCTURE_TYPE_MISMATCH",
                "lease_term_years may only be supplied for a master-lease lessee.",
            )

    if kind == "MASTER_LEASE_LESSEE" and party_tax_status in DISQUALIFYING_TAX_STATUSES:
        raise ApiError("ERR_DISQUALIFIED_PARTY")

    election = "PENDING" if kind == "MASTER_LEASE_LESSEE" else "NOT_APPLICABLE"
    candidate = {
        "kind": kind,
        "party_tax_status": party_tax_status,
        "lease_term_years": lease_term,
        "pass_through_election": election,
    }
    score = calc.risk_score(candidate, "ADMISSION")
    if score >= calc.HIGH_RISK_THRESHOLD:
        raise ApiError("ERR_DISQUALIFICATION_RISK_TOO_HIGH")

    # --- band 12: the aggregate allocation ceiling --------------------------
    if _allocation_total(project_id) + pct > calc.MAX_ALLOCATION_PCT:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_LIMIT")

    record = base_record()
    record.update(
        {
            "project_id": project_id,
            "kind": kind,
            "party_legal_name": party_legal_name,
            "party_tax_status": party_tax_status,
            "capital_committed_cents": capital,
            "credit_allocation_pct": float(pct),
            "lease_term_years": lease_term,
            "pass_through_election": election,
            "election_at": None,
            "status": "ADMITTED",
            "disqualification_risk_score": score,
            "risk_variant_applied": "ADMISSION",
            "_pct": pct,
        }
    )
    store.investor_interests[record["id"]] = record

    services.refresh_max_risk(project)
    touch(project)
    return created_response(public(record))


@bp.post("/investor-interests/<interest_id>/elect-pass-through")
def elect_pass_through(interest_id):
    uid, _role = require("InvestorAdmin")
    body()
    interest = fetch(store.investor_interests, interest_id, "ERR_INVESTOR_INTEREST_NOT_FOUND")
    acting_interest(uid, interest["project_id"])

    if interest["pass_through_election"] != "PENDING":
        raise ApiError(
            "ERR_ELECTION_WINDOW_CLOSED",
            "The pass-through election is only available while it reads PENDING.",
        )

    project = store.projects[interest["project_id"]]
    interest["pass_through_election"] = "ELECTED"
    interest["election_at"] = clock.now_iso()
    interest["disqualification_risk_score"] = services.score_of(
        interest, "ADMISSION", project["id"]
    )
    interest["risk_variant_applied"] = "ADMISSION"
    touch(interest)

    services.refresh_max_risk(project)
    touch(project)
    return object_response(public(interest))


@bp.get("/investor-interests/<interest_id>")
def read_interest(interest_id):
    require(*LEDGER_READ_ROLES)
    record = fetch(store.investor_interests, interest_id, "ERR_INVESTOR_INTEREST_NOT_FOUND")
    return object_response(public(record))


# --------------------------------------------------------------------------
# credit claims
# --------------------------------------------------------------------------


@bp.post("/credit-claims")
def create_claim():
    uid, _role = require("InvestorAdmin")
    data = body()
    project_id = req_str(data, "project_id")
    tax_year = req_int(data, "tax_year", min_v=2000, max_v=2100)

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    acting_interest(uid, project_id)

    if project["certification_status"] != "PART3_CERTIFIED":
        raise ApiError("ERR_PROJECT_NOT_CERTIFIED")
    if project["placed_in_service_date"] is None:
        raise ApiError("ERR_PROJECT_NOT_PLACED_IN_SERVICE")
    if project["compliance_status"] == "RECAPTURED":
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "No credit may be claimed on a project whose credit has been recaptured.",
        )

    first_year = as_date(project["placed_in_service_date"]).year
    if not first_year <= tax_year <= first_year + calc.RATABLE_YEARS - 1:
        raise ApiError("ERR_CLAIM_YEAR_OUT_OF_WINDOW")

    siblings = services.project_claims(project_id)
    if any(c["tax_year"] == tax_year for c in siblings):
        raise ApiError("ERR_CLAIM_YEAR_DUPLICATE")

    sequence = 1 + sum(1 for c in siblings if c["tax_year"] < tax_year)

    record = base_record()
    record.update(
        {
            "project_id": project_id,
            "tax_year": tax_year,
            "claim_sequence": sequence,
            "gross_credit_cents": project["annual_credit_cents"],
            "recapture_offset_cents": 0,
            "net_claim_cents": 0,
            "status": "DRAFT",
            "filed_at": None,
            "filed_by_user_id": None,
        }
    )
    store.credit_claims[record["id"]] = record
    return created_response(public(record))


@bp.post("/credit-claims/<claim_id>/file")
def file_claim(claim_id):
    uid, _role = require("InvestorAdmin")
    body()
    claim = fetch(store.credit_claims, claim_id, "ERR_CREDIT_CLAIM_NOT_FOUND")
    project = store.projects[claim["project_id"]]
    acting_interest(uid, claim["project_id"])

    # --- band 8: the claim's own state, then the project's two dimensions ---
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_CREDIT_CLAIM_ALREADY_FILED")
    if project["certification_status"] != "PART3_CERTIFIED":
        raise ApiError("ERR_PROJECT_NOT_CERTIFIED")
    if project["compliance_status"] == "RECAPTURED":
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "No credit may be filed on a project whose credit has been recaptured.",
        )

    # --- band 10: standing risk, then the pass-through election -------------
    if project["max_investor_risk_score"] >= calc.HIGH_RISK_THRESHOLD:
        raise ApiError("ERR_DISQUALIFICATION_RISK_TOO_HIGH")
    if project["structure_type"] == "MASTER_LEASE":
        lessee = _lessee_of(project["id"])
        if lessee is None or lessee["pass_through_election"] != "ELECTED":
            raise ApiError("ERR_PASS_THROUGH_ELECTION_REQUIRED")

    # --- band 12: the fiscal check runs last -------------------------------
    if project["substantial_test_status"] != "MET":
        raise ApiError("ERR_SUBSTANTIAL_TEST_NOT_MET")

    # --- calculations.claim_settlement, in its pinned order ----------------
    gross = claim["gross_credit_cents"]                                    # step 1
    offset = min(gross, project["recapture_balance_cents"])                # step 2
    net = gross - offset                                                   # step 3

    claim["recapture_offset_cents"] = offset
    claim["net_claim_cents"] = net
    claim["status"] = "FILED"
    claim["filed_at"] = clock.now_iso()
    claim["filed_by_user_id"] = uid
    touch(claim)

    project["credit_claimed_to_date_cents"] += net                          # step 4
    project["credit_recaptured_cents"] += offset
    project["recapture_balance_cents"] -= offset
    services.refresh_unclaimed(project)

    services.settle_recapture_events(project)                               # step 5
    services.leave_cure_pending(project)                                    # step 6
    touch(project)
    return object_response(public(claim))


@bp.get("/credit-claims/<claim_id>")
def read_claim(claim_id):
    require(*LEDGER_READ_ROLES)
    record = fetch(store.credit_claims, claim_id, "ERR_CREDIT_CLAIM_NOT_FOUND")
    return object_response(public(record))
