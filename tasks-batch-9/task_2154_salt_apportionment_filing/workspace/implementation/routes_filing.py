"""State returns: opening, factor computation, review workflow, modifications
and credit claims."""
from flask import Blueprint

from calc import (claims_of, compute_factors, derive_posture, factors_are_stale,
                  factors_of, group_of_filing, modifications_of,
                  payments_applied_to, recompute_balance, recompute_liability_chain,
                  recompute_registration_pools, registration_of_filing,
                  resequence_modifications, reverse_credit_waterfall,
                  run_credit_waterfall)
from errors import ApiError, invalid
from models import (find_credit, find_election, find_filing, find_legal_entity,
                    find_registration, ser_credit, ser_factor, ser_filing,
                    ser_modification)
from routes_reg import guard_not_withdrawn, ELECTION_BASES
from store import db
from util import (money, midnight_utc, opt_bool, opt_int, opt_num, opt_str, req_enum,
                  req_int, req_num, req_str, D, ZERO)
from web import (ANY_ROLE, body_json, bump, created, current_user_id, endpoint,
                 mark_dirty, new_record, ok, paginate, query_int, query_str,
                 sort_created)

bp = Blueprint("filings", __name__)

VARIANTS = ("JOYCE", "FINNIGAN")
DIRECTIONS = ("ADDITION", "SUBTRACTION")
EDITABLE_STATES = ("DRAFT", "AMENDED")


def guard_filing_state(filing, allowed):
    if filing["preparation_status"] not in allowed:
        raise ApiError("ERR_INVALID_FILING_STATE",
                       "The return's preparation_status is %s, which is not a legal source state "
                       "for this operation." % filing["preparation_status"])


# --------------------------------------------------------------------------
# StateFiling
# --------------------------------------------------------------------------
@bp.route("/salt/registrations/<rid>/filings", methods=["POST"])
@endpoint(["StateAnalyst", "TaxManager"])
def create_filing(rid):
    reg = find_registration(rid)
    body = body_json()

    raw_election = body.get("election_id")
    election = find_election(raw_election) if raw_election is not None else None
    raw_primary = body.get("primary_legal_entity_id")
    primary = find_legal_entity(raw_primary) if raw_primary is not None else None

    tax_year = req_int(body, "tax_year")
    filing_basis = req_enum(body, "filing_basis", ELECTION_BASES)
    federal_taxable_income = req_num(body, "federal_taxable_income")

    guard_not_withdrawn(reg)

    if primary is not None and primary["group_id"] != reg["group_id"]:
        raise ApiError("ERR_ENTITY_NOT_IN_GROUP",
                       "The named member entity does not belong to this registration's group.")
    if filing_basis == "SEPARATE_ENTITY" and primary is None:
        raise ApiError("ERR_PRIMARY_ENTITY_REQUIRED",
                       "A separate-entity return requires primary_legal_entity_id.")
    if election is not None:
        if (election["registration_id"] != reg["id"]
                or election["status"] != "ELECTED"
                or not (election["effective_tax_year"] <= tax_year <= election["expires_after_tax_year"])):
            raise ApiError("ERR_ELECTION_NOT_GOVERNING",
                           "The referenced election does not govern this return.")

    filing = new_record()
    filing.update({
        "registration_id": reg["id"],
        "election_id": election["id"] if election is not None else None,
        "primary_legal_entity_id": primary["id"] if primary is not None else None,
        "tax_year": tax_year,
        "filing_basis": filing_basis,
        "federal_taxable_income": federal_taxable_income,
        "apportionment_variant": None,
        "preparation_status": "DRAFT",
        "payment_status": "UNPAID",
        "apportionment_percentage": money(ZERO),
        "modification_total": money(ZERO),
        "state_taxable_income": money(ZERO),
        "tax_before_credits": money(ZERO),
        "credits_applied_total": money(ZERO),
        "estimated_credits_applied": money(ZERO),
        "assessment_added_total": money(ZERO),
        "balance_due": money(ZERO),
        "original_due_date": midnight_utc(tax_year + 1, reg["due_month"], reg["due_day"]),
        "extended_due_date": None,
        "preparer_user_id": None,
        "approver_user_id": None,
        "confirmation_number": None,
        "filed_on_date": None,
        "amendment_count": 0,
        "_factors_seq": None,
    })
    db.filings[filing["id"]] = filing
    return created(ser_filing(filing))


@bp.route("/salt/filings/<fid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_filing(fid):
    return ok(ser_filing(find_filing(fid)))


@bp.route("/salt/filings", methods=["GET"])
@endpoint(ANY_ROLE)
def list_filings():
    registration_id = query_str("registration_id")
    election_id = query_str("election_id")
    primary_legal_entity_id = query_str("primary_legal_entity_id")
    tax_year = query_int("tax_year")
    preparation_status = query_str("preparation_status")
    rows = list(db.filings.values())
    if registration_id is not None:
        rows = [f for f in rows if f["registration_id"] == registration_id]
    if election_id is not None:
        rows = [f for f in rows if f["election_id"] == election_id]
    if primary_legal_entity_id is not None:
        rows = [f for f in rows if f["primary_legal_entity_id"] == primary_legal_entity_id]
    if tax_year is not None:
        rows = [f for f in rows if f["tax_year"] == tax_year]
    if preparation_status is not None:
        rows = [f for f in rows if f["preparation_status"] == preparation_status]
    return paginate(sort_created(rows), ser_filing)


@bp.route("/salt/filings/<fid>/compute-factors", methods=["POST"])
@endpoint(["StateAnalyst", "TaxManager"])
def compute_filing_factors(fid):
    filing = find_filing(fid)
    body = body_json()
    variant = req_enum(body, "apportionment_variant", VARIANTS)
    guard_filing_state(filing, EDITABLE_STATES)

    reg = registration_of_filing(filing)
    if reg["nexus_status"] == "NONE":
        raise ApiError("ERR_NEXUS_NOT_ESTABLISHED",
                       "Nexus has not been established for this state registration.")

    compute_factors(filing, variant)
    bump(filing)
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/lock-factors", methods=["POST"])
@endpoint(["StateAnalyst", "TaxManager"])
def lock_factors(fid):
    filing = find_filing(fid)
    guard_filing_state(filing, EDITABLE_STATES)
    reg = registration_of_filing(filing)
    if reg["nexus_status"] == "NONE":
        raise ApiError("ERR_NEXUS_NOT_ESTABLISHED",
                       "Nexus has not been established for this state registration.")
    if reg["nexus_status"] == "PROTECTED_PL86272":
        raise ApiError("ERR_PL86272_PROTECTED",
                       "A solicitation-protected state cannot be assessed net income tax.")
    if reg["registration_status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_COMPLETE",
                       "The state registration is not complete.")
    if factors_are_stale(filing):
        raise ApiError("ERR_FACTORS_STALE",
                       "The apportionment factors are missing or out of date.")

    filing["preparation_status"] = "FACTORS_LOCKED"
    bump(filing)
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/submit-review", methods=["POST"])
@endpoint(["StateAnalyst", "Controller", "TaxManager"])
def submit_review(fid):
    filing = find_filing(fid)
    body = body_json()
    opt_str(body, "preparer_note", None)
    guard_filing_state(filing, ("FACTORS_LOCKED",))

    filing["preparation_status"] = "IN_REVIEW"
    filing["preparer_user_id"] = current_user_id()
    bump(filing)
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/approve", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def approve_filing(fid):
    filing = find_filing(fid)
    body = body_json()
    opt_str(body, "approval_note", None)
    guard_filing_state(filing, ("IN_REVIEW",))

    if filing["preparer_user_id"] is not None and filing["preparer_user_id"] == current_user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver may not be the preparer of this return.")

    filing["preparation_status"] = "APPROVED"
    filing["approver_user_id"] = current_user_id()
    bump(filing)
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/reject", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def reject_filing(fid):
    filing = find_filing(fid)
    body = body_json()
    req_str(body, "rejection_reason")
    guard_filing_state(filing, ("IN_REVIEW",))

    filing["preparation_status"] = "DRAFT"
    filing["approver_user_id"] = None
    bump(filing)
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/file", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def file_filing(fid):
    filing = find_filing(fid)
    body = body_json()
    confirmation_number = req_str(body, "confirmation_number")
    guard_filing_state(filing, ("APPROVED",))

    if filing["election_id"] is not None:
        election = db.elections.get(filing["election_id"])
        if (election is None or election["status"] != "ELECTED"
                or election["election_basis"] != filing["filing_basis"]):
            raise ApiError("ERR_ELECTION_BASIS_MISMATCH",
                           "The return's basis no longer matches its governing election.")

    deadline = filing["extended_due_date"] or filing["original_due_date"]
    if db.clock > deadline:
        raise ApiError("ERR_FILING_DEADLINE_PASSED",
                       "The filing deadline for this return has passed.")

    filing["preparation_status"] = "FILED"
    filing["confirmation_number"] = confirmation_number
    filing["filed_on_date"] = db.clock
    bump(filing)
    derive_posture(group_of_filing(filing))
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/amend", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def amend_filing(fid):
    filing = find_filing(fid)
    body = body_json()
    req_str(body, "reason")
    replacement = opt_num(body, "federal_taxable_income", None)
    guard_filing_state(filing, ("FILED",))

    filing["preparation_status"] = "AMENDED"
    filing["amendment_count"] = filing["amendment_count"] + 1
    if replacement is not None:
        filing["federal_taxable_income"] = replacement
    reverse_credit_waterfall(filing)
    recompute_balance(filing)
    bump(filing)
    derive_posture(group_of_filing(filing))
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/claim-refund", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def claim_refund(fid):
    filing = find_filing(fid)
    body = body_json()
    opt_str(body, "refund_method", None)

    if filing["preparation_status"] not in ("FILED", "AMENDED"):
        raise ApiError("ERR_INVALID_FILING_STATE",
                       "A refund may only be claimed on a filed or amended return.")
    if filing["payment_status"] != "OVERPAID":
        raise ApiError("ERR_INVALID_FILING_STATE",
                       "A refund may only be claimed on an overpaid return.")

    applied = [p for p in payments_applied_to(filing) if p["status"] == "APPLIED"]
    if not applied:
        raise ApiError("ERR_REFUND_NOT_AVAILABLE",
                       "No applied estimated payment is available to refund.")

    filing["payment_status"] = "REFUND_CLAIMED"
    touched_registrations = set()
    for payment in payments_applied_to(filing):
        if payment["status"] != "REFUNDED":
            payment["status"] = "REFUNDED"
            mark_dirty(payment)
        touched_registrations.add(payment["registration_id"])
    for reg_id in touched_registrations:
        recompute_registration_pools(db.registrations[reg_id])
    bump(filing)
    derive_posture(group_of_filing(filing))
    return ok(ser_filing(filing))


@bp.route("/salt/filings/<fid>/factors", methods=["GET"])
@endpoint(ANY_ROLE)
def list_factors(fid):
    filing = find_filing(fid)
    return paginate(factors_of(filing), ser_factor)


# --------------------------------------------------------------------------
# Modification
# --------------------------------------------------------------------------
@bp.route("/salt/filings/<fid>/modifications", methods=["POST"])
@endpoint(["StateAnalyst", "TaxManager"])
def create_modification(fid):
    filing = find_filing(fid)
    body = body_json()
    modification_code = req_str(body, "modification_code")
    direction = req_enum(body, "direction", DIRECTIONS)
    raw_amount = req_num(body, "raw_amount", minv=0)
    allocation_ratio = req_num(body, "allocation_ratio", minv=0, maxv=1)
    guard_filing_state(filing, EDITABLE_STATES)

    line = new_record()
    line.update({
        "filing_id": filing["id"],
        "modification_code": modification_code,
        "direction": direction,
        "raw_amount": raw_amount,
        "allocation_ratio": allocation_ratio,
        "line_amount": money(raw_amount * allocation_ratio),
        "sequence_number": 1,
    })
    db.modifications[line["id"]] = line
    resequence_modifications(filing)
    recompute_liability_chain(filing)
    bump(filing)
    return created(ser_modification(line))


@bp.route("/salt/filings/<fid>/modifications", methods=["GET"])
@endpoint(ANY_ROLE)
def list_modifications(fid):
    filing = find_filing(fid)
    rows = sorted(modifications_of(filing), key=lambda m: (m["sequence_number"], m["_seq"]))
    return paginate(rows, ser_modification)


# --------------------------------------------------------------------------
# CreditClaim
# --------------------------------------------------------------------------
@bp.route("/salt/filings/<fid>/credit-claims", methods=["POST"])
@endpoint(["StateAnalyst", "TaxManager"])
def create_credit_claim(fid):
    filing = find_filing(fid)
    body = body_json()
    credit_code = req_str(body, "credit_code")
    granted_amount = req_num(body, "granted_amount")
    if granted_amount <= 0:
        raise invalid("'granted_amount' must be greater than zero")
    priority_order = req_int(body, "priority_order", minv=1)
    expected_filing_version = req_int(body, "expected_filing_version")
    refundable = opt_bool(body, "refundable", False)
    expires_after_years = opt_int(body, "expires_after_years", 5)

    if expected_filing_version != filing["version"]:
        raise ApiError("ERR_STALE_FILING_VERSION",
                       "expected_filing_version does not match the return's current version.")

    guard_filing_state(filing, EDITABLE_STATES)

    claim = new_record()
    claim.update({
        "filing_id": filing["id"],
        "credit_code": credit_code,
        "granted_amount": granted_amount,
        "refundable": refundable,
        "priority_order": priority_order,
        "expires_after_years": expires_after_years,
        "applied_amount": money(ZERO),
        "carryforward_amount": money(ZERO),
        "expired_amount": money(ZERO),
        "status": "PENDING",
        "_fresh": True,
    })
    db.credit_claims[claim["id"]] = claim

    run_credit_waterfall(filing)
    recompute_balance(filing)
    derive_posture(group_of_filing(filing))
    bump(filing)
    claim.pop("_fresh", None)
    return created(ser_credit(claim))


@bp.route("/salt/credit-claims/<cid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_credit_claim(cid):
    return ok(ser_credit(find_credit(cid)))


@bp.route("/salt/filings/<fid>/credit-claims", methods=["GET"])
@endpoint(ANY_ROLE)
def list_credit_claims(fid):
    filing = find_filing(fid)
    return paginate(claims_of(filing), ser_credit)
