"""PRD 3.3 subsidy contracts and the monthly claim ledger, 3.4 remittance waterfall."""
from flask import Blueprint

import auth
import calculations as calc
import clock
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("subsidy", __name__)

DAYS_MAX = 22


def _contract(actor, contract_id):
    contract = services.contract_or_404(contract_id)
    auth.scope_provider(actor, contract["provider_id"])
    return contract


def _claim(actor, claim_id):
    claim = services.find_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND", "subsidy claim")
    contract = db.contracts[claim["contract_id"]]
    auth.scope_provider(actor, contract["provider_id"])
    return claim, contract


def _require_contract_active(contract):
    if contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE",
            "The subsidy contract is %s rather than ACTIVE." % contract["status"],
        )


# --- contract registration -------------------------------------------------

@bp.post("/fccn/subsidy-contracts")
def register_contract():
    auth.require_auth(("NetworkAdmin",))
    body = v.get_body()
    provider_id = v.req_str(body, "provider_id")
    provider = services.provider_or_404(provider_id)

    agency_code = v.req_str(body, "agency_code")
    daily_rate_cents = v.req_int(body, "daily_rate_cents", 1)
    contracted_slots = v.req_int(body, "contracted_slots", 1)
    authorized_amount_cents = v.req_int(body, "authorized_amount_cents", 1)
    period_start_on = v.req_instant(body, "period_start_on")
    absence_rate_pct = v.opt_number(body, "absence_rate_pct", 50, 0, 100)
    v.reject_unversioned(body)

    row = db.make_row(
        provider_id=provider["id"],
        agency_code=agency_code,
        daily_rate_cents=daily_rate_cents,
        absence_rate_pct=absence_rate_pct,
        contracted_slots=contracted_slots,
        committed_slots=0,
        available_slots=contracted_slots,
        authorized_amount_cents=authorized_amount_cents,
        claimed_amount_cents=0,
        remitted_cents=0,
        unallocated_credit_cents=0,
        status="ACTIVE",
        period_start_on=period_start_on,
    )
    services.register_new(row)
    db.contracts[row["id"]] = row
    return response.created(row)


# --- claim drafting and the fiscal ladder ---------------------------------

@bp.post("/fccn/subsidy-claims")
def draft_claim():
    actor = auth.require_auth(("Provider",))
    body = v.get_body()
    contract_id = v.req_str(body, "contract_id")
    contract = services.contract_or_404(contract_id)
    auth.scope_provider(actor, contract["provider_id"])
    provider = db.providers[contract["provider_id"]]

    raw_lines = v.req_array(body, "lines")
    referenced = []
    for item in raw_lines:
        referenced.append(services.enrollment_or_404(v.obj_str(item, "enrollment_id", "lines")))

    period_month = v.req_period_month(body, "period_month")
    lines = []
    for item in raw_lines:
        lines.append({
            "enrollment_id": item["enrollment_id"],
            "attended_days": v.obj_int(item, "attended_days", "lines", 0, DAYS_MAX),
            "absent_days": v.obj_int(item, "absent_days", "lines", 0, DAYS_MAX),
        })
    expected_contract_version = v.req_int(body, "expected_contract_version", 0)

    if expected_contract_version != contract["version"]:
        raise ApiError(
            "ERR_STALE_CONTRACT_VERSION",
            "The contract's version has advanced since it was last observed.",
        )
    if contract["status"] not in ("ACTIVE", "SUSPENDED_FOR_QUALITY"):
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE",
            "No claim may be drafted against a %s contract." % contract["status"],
        )
    services.check_posture(provider, restricted_blocks=True)
    services.check_license_current(provider)

    clash = [
        c for c in services.contract_children(db.claims, contract["id"])
        if c["period_month"] == period_month and c["status"] != "REJECTED"
    ]
    if clash:
        raise ApiError(
            "ERR_CLAIM_PERIOD_DUPLICATE",
            "A non-rejected claim already exists for %s on this contract." % period_month,
        )
    for enrollment in referenced:
        if enrollment["provider_id"] != contract["provider_id"] or not enrollment["subsidy_certified"]:
            raise ApiError(
                "ERR_CLAIM_LINE_ENROLLMENT_MISMATCH",
                "Every claim line must name a subsidy-certified enrollment of the contract's provider.",
            )

    row = db.make_row(
        contract_id=contract["id"],
        period_month=period_month,
        lines=lines,
        provisional_amount_cents=0,
        final_amount_cents=0,
        advance_paid_cents=0,
        paid_cents=0,
        settlement_delta_cents=0,
        status="DRAFT",
        held_from_status=None,
        hold_reason=None,
        rejection_reason=None,
    )
    services.register_new(row)
    db.claims[row["id"]] = row
    services.touch(contract)
    return response.created(row)


@bp.post("/fccn/subsidy-claims/<claim_id>/submit")
def submit_claim(claim_id):
    actor = auth.require_auth(("Provider",))
    claim, contract = _claim(actor, claim_id)
    provider = db.providers[contract["provider_id"]]

    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a DRAFT claim may be submitted.")
    _require_contract_active(contract)
    services.check_posture(provider, restricted_blocks=False)
    for line in claim["lines"]:
        enrollment = db.enrollments.get(line["enrollment_id"])
        if enrollment is None or enrollment["provider_id"] != contract["provider_id"]:
            raise ApiError(
                "ERR_CLAIM_LINE_ENROLLMENT_MISMATCH",
                "Every claim line must still name an enrollment of the contract's provider.",
            )

    provisional = calc.provisional_amount(claim, contract)
    if contract["claimed_amount_cents"] + provisional > contract["authorized_amount_cents"]:
        raise ApiError(
            "ERR_CONTRACT_AUTHORIZATION_EXCEEDED",
            "The claim would exceed the contract's authorized amount.",
        )

    claim["provisional_amount_cents"] = provisional
    claim["status"] = "SUBMITTED"
    services.touch(claim)
    contract["claimed_amount_cents"] += provisional
    services.touch(contract)
    return response.ok(claim)


@bp.post("/fccn/subsidy-claims/<claim_id>/advance")
def advance_claim(claim_id):
    actor = auth.require_auth(("FiscalOfficer",))
    claim, contract = _claim(actor, claim_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a SUBMITTED claim may be advanced.")
    _require_contract_active(contract)

    claim["advance_paid_cents"] = calc.advance_amount(claim["provisional_amount_cents"])
    claim["status"] = "ADVANCE_PAID"
    services.touch(claim)
    return response.ok(claim)


@bp.post("/fccn/subsidy-claims/<claim_id>/reconcile")
def reconcile_claim(claim_id):
    actor = auth.require_auth(("FiscalOfficer",))
    claim, contract = _claim(actor, claim_id)
    if claim["status"] != "ADVANCE_PAID":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only an ADVANCE_PAID claim may be reconciled.")

    final = calc.final_amount(claim, contract)
    claim["final_amount_cents"] = final
    claim["settlement_delta_cents"] = final - claim["advance_paid_cents"]
    claim["status"] = "RECONCILED"
    services.touch(claim)
    contract["claimed_amount_cents"] += final - claim["provisional_amount_cents"]
    services.touch(contract)
    return response.ok(claim)


@bp.post("/fccn/subsidy-claims/<claim_id>/reject")
def reject_claim(claim_id):
    actor = auth.require_auth(("FiscalOfficer",))
    claim, contract = _claim(actor, claim_id)
    body = v.get_body()
    v.reject_unversioned(body)
    rejection_reason = v.req_str(body, "rejection_reason")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a SUBMITTED claim may be rejected.")

    claim["status"] = "REJECTED"
    claim["rejection_reason"] = rejection_reason
    services.touch(claim)
    contract["claimed_amount_cents"] -= claim["provisional_amount_cents"]
    services.touch(contract)
    return response.ok(claim)


# --- remittances and the allocation waterfall -----------------------------

@bp.post("/fccn/remittances")
def post_remittance():
    auth.require_auth(("FiscalOfficer",))
    body = v.get_body()
    contract_id = v.req_str(body, "contract_id")
    contract = services.contract_or_404(contract_id)

    agency_reference = v.req_str(body, "agency_reference")
    amount_cents = v.req_int(body, "amount_cents", 1)
    received_on = v.req_instant(body, "received_on")
    v.reject_unversioned(body)
    duplicate = [
        r for r in services.contract_children(db.remittances, contract["id"])
        if r["status"] == "POSTED" and r["agency_reference"] == agency_reference
    ]
    if duplicate:
        v.bad("agency_reference must be unique among this contract's POSTED remittances.")

    _require_contract_active(contract)

    row = db.make_row(
        contract_id=contract["id"],
        agency_reference=agency_reference,
        amount_cents=amount_cents,
        received_on=received_on,
        allocations=[],
        unallocated_cents=0,
        status="POSTED",
        reversal_reason=None,
    )
    services.register_new(row)

    remaining = amount_cents
    for claim in calc.allocation_candidates(contract["id"]):
        if remaining <= 0:
            break
        take = min(remaining, claim["final_amount_cents"] - claim["paid_cents"])
        if take <= 0:
            continue
        claim["paid_cents"] += take
        row["allocations"].append({"claim_id": claim["id"], "allocated_cents": take})
        remaining -= take
        if claim["paid_cents"] >= claim["final_amount_cents"]:
            claim["status"] = "SETTLED"
        services.touch(claim)
    row["unallocated_cents"] = remaining

    contract["remitted_cents"] += amount_cents
    contract["unallocated_credit_cents"] += remaining
    services.touch(contract)

    db.remittances[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/remittances/<remittance_id>/reverse")
def reverse_remittance(remittance_id):
    auth.require_auth(("FiscalOfficer",))
    remittance = services.find_or_404(
        db.remittances, remittance_id, "ERR_REMITTANCE_NOT_FOUND", "remittance"
    )
    body = v.get_body()
    v.reject_unversioned(body)
    reversal_reason = v.req_str(body, "reversal_reason")

    if remittance["status"] != "POSTED":
        raise ApiError("ERR_INVALID_REMITTANCE_STATE", "Only a POSTED remittance may be reversed.")

    remittance["status"] = "REVERSED"
    remittance["reversal_reason"] = reversal_reason
    services.touch(remittance)

    for entry in remittance["allocations"]:
        claim = db.claims.get(entry["claim_id"])
        if claim is None:
            continue
        claim["paid_cents"] -= entry["allocated_cents"]
        if claim["status"] == "SETTLED" and claim["paid_cents"] < claim["final_amount_cents"]:
            claim["status"] = "RECONCILED"
        services.touch(claim)

    contract = db.contracts[remittance["contract_id"]]
    contract["remitted_cents"] -= remittance["amount_cents"]
    contract["unallocated_credit_cents"] -= remittance["unallocated_cents"]
    services.touch(contract)
    return response.ok(remittance)


# --- reads -----------------------------------------------------------------

@bp.get("/fccn/subsidy-contracts/<contract_id>")
def read_contract(contract_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    return response.ok(_contract(actor, contract_id))


@bp.get("/fccn/subsidy-contracts/<contract_id>/claims")
def list_contract_claims(contract_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    contract = _contract(actor, contract_id)
    limit, offset = v.pagination()
    rows = v.filtered(
        services.contract_children(db.claims, contract["id"]),
        status="status",
        period_month="period_month",
    )
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/fccn/subsidy-contracts/<contract_id>/remittances")
def list_contract_remittances(contract_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    contract = _contract(actor, contract_id)
    limit, offset = v.pagination()
    rows = v.filtered(services.contract_children(db.remittances, contract["id"]), status="status")
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/fccn/subsidy-claims/<claim_id>")
def read_claim(claim_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    claim, _ = _claim(actor, claim_id)
    return response.ok(claim)
