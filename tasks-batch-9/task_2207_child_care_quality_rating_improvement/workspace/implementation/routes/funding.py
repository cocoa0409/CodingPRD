"""Improvement grants, expenditure compliance and recovery (PRD §3.8)."""

from flask import Blueprint, request

import calculations as calc
import cascades
import lookups
import response
import serializers
import store
import validation as v
from auth import require
from errors import fail
from validation import as_date, body

bp = Blueprint("funding", __name__)

GRANT_DECISIONS = ["ACCEPT", "DECLINE", "REMEDIATE", "REOPEN"]
PROVIDER_DECISIONS = ("ACCEPT", "DECLINE", "REMEDIATE")
ADMIN_DECISIONS = ("REOPEN",)

# The compliance dimension is cyclic (PRD §3.8): a rejection walks it forward from
# COMPLIANT and REMEDIATED, and a second rejection issues the finding.
REJECTION_COMPLIANCE_HOP = {
    "COMPLIANT": "UNDER_REVIEW",
    "UNDER_REVIEW": "FINDING_ISSUED",
    "REMEDIATED": "UNDER_REVIEW",
}


def _zero_categories():
    return {category: 0 for category in v.GRANT_CATEGORIES}


def _funding_cycle(grant):
    """The rating cycle whose award justified the grant."""
    return store.DB.rating_cycles.get(grant.get("rating_cycle_id"))


def _require_active_provider(provider):
    """PRD §2.7 step 11: the owning provider's own standing."""
    if provider is None or provider["status"] != "ACTIVE":
        fail("ERR_PROVIDER_STATE_INVALID",
             "the owning provider must be ACTIVE for this grant decision")


# ------------------------------------------------------------------- grants


@bp.post("/providers/<provider_id>/improvement-grants")
def offer_grant(provider_id):
    require("StateAdministrator")
    provider = lookups.get_provider(provider_id)
    data = body()
    rating_cycle_id = v.req_str(data, "rating_cycle_id")
    awarded_amount_cents = v.req_int(data, "awarded_amount_cents", 1)
    spend_deadline = v.req_instant(data, "spend_deadline")

    # Body foreign key (PRD §2.7 step 7).
    cycle = lookups.get_cycle(rating_cycle_id)

    rec = store.base_record(
        provider_id=provider["id"],
        rating_cycle_id=cycle["id"],
        awarded_amount_cents=awarded_amount_cents,
        spend_deadline=spend_deadline,
        committed_cents=0,
        reimbursed_cents=0,
        available_cents=0,
        category_spend_cents={},
        status="OFFERED",
        compliance_status="COMPLIANT",
        recovery_amount_cents=0,
    )
    store.DB.improvement_grants[rec["id"]] = rec
    return response.created(serializers.dump("improvement_grant", rec))


@bp.get("/improvement-grants")
def list_grants():
    require("StateAdministrator", "Provider", "Coach")
    records = store.sort_created(list(store.DB.improvement_grants.values()))
    for field in ("provider_id", "rating_cycle_id", "status", "compliance_status"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("improvement_grant"))


@bp.get("/improvement-grants/<improvement_grant_id>")
def read_grant(improvement_grant_id):
    principal = require("StateAdministrator", "Provider", "Coach")
    grant = lookups.get_grant(improvement_grant_id)
    lookups.own_provider_id(principal, grant["provider_id"])
    return response.ok(serializers.dump("improvement_grant", grant))


@bp.post("/improvement-grants/<improvement_grant_id>/accept")
def grant_decision(improvement_grant_id):
    principal = require("Provider", "StateAdministrator")
    grant = lookups.get_grant(improvement_grant_id)
    lookups.own_provider_id(principal, grant["provider_id"])
    provider = store.DB.providers.get(grant["provider_id"])
    data = body()
    decision = v.req_enum(data, "decision", GRANT_DECISIONS)

    # The endpoint admits two roles but the permitted decisions differ by role.
    if decision in PROVIDER_DECISIONS and principal.role != "Provider":
        fail("ERR_FORBIDDEN_ROLE", "only the owning provider may take decision %s" % decision)
    if decision in ADMIN_DECISIONS and principal.role != "StateAdministrator":
        fail("ERR_FORBIDDEN_ROLE",
             "only a StateAdministrator may take decision %s" % decision)

    if decision == "ACCEPT":
        if grant["status"] != "OFFERED":
            fail("ERR_GRANT_NOT_OPEN", "acceptance is available only from OFFERED")
        _require_active_provider(provider)
        cycle = _funding_cycle(grant)
        if cycle is None or cycle["status"] != "ACTIVE" or \
                cycle["publication_status"] == "WITHDRAWN":
            fail("ERR_CYCLE_STATE_INVALID",
                 "the funding cycle must be ACTIVE with a publication state other than WITHDRAWN")
        grant["available_cents"] = int(grant["awarded_amount_cents"])
        grant["category_spend_cents"] = _zero_categories()
        grant["status"] = "ACCEPTED"
        # Acceptance continues straight into OPEN while the spend window is live.
        if store.today() <= as_date(grant["spend_deadline"]):
            grant["status"] = "OPEN"
        store.touch(grant)

    elif decision == "DECLINE":
        if grant["status"] != "OFFERED":
            fail("ERR_GRANT_NOT_OPEN", "a decline is available only from OFFERED")
        _require_active_provider(provider)
        grant["status"] = "DECLINED"
        grant["available_cents"] = 0
        store.touch(grant)
        cascades.void_allocations_for_declined_grant(grant)

    elif decision == "REMEDIATE":
        if grant["compliance_status"] != "FINDING_ISSUED":
            fail("ERR_GRANT_NOT_OPEN",
                 "remediation is available only while the compliance status is FINDING_ISSUED")
        _require_active_provider(provider)
        grant["compliance_status"] = "REMEDIATED"
        store.touch(grant)

    else:  # REOPEN
        if grant["status"] != "FROZEN":
            fail("ERR_GRANT_NOT_OPEN", "a reopen is available only from FROZEN")
        _require_active_provider(provider)
        cycle = _funding_cycle(grant)
        if cycle is None or cycle["status"] != "ACTIVE":
            fail("ERR_CYCLE_STATE_INVALID", "the funding cycle must be ACTIVE to reopen a grant")
        if store.today() > as_date(grant["spend_deadline"]):
            fail("ERR_GRANT_SPEND_DEADLINE_PASSED",
                 "the grant's spend deadline has already passed")
        grant["status"] = "OPEN"
        store.touch(grant)

    return response.ok(serializers.dump("improvement_grant", grant))


# -------------------------------------------------------------- expenditures


@bp.post("/improvement-grants/<improvement_grant_id>/expenditures")
def submit_expenditure(improvement_grant_id):
    principal = require("Provider")
    grant = lookups.get_grant(improvement_grant_id)
    lookups.own_provider_id(principal, grant["provider_id"])
    data = body()
    category = v.req_enum(data, "category", v.GRANT_CATEGORIES)
    amount_cents = v.req_int(data, "amount_cents", 1)
    invoice_date = v.req_instant(data, "invoice_date")
    expected = v.req_int(data, "expected_grant_version")

    # The six checks of PRD §3.8, in the order the PRD pins them.
    if expected != int(grant["version"]):
        fail("ERR_STALE_VERSION", "expected_grant_version does not match the grant version")
    if grant["status"] != "OPEN":
        fail("ERR_GRANT_NOT_OPEN", "expenditures may be submitted only against an OPEN grant")
    if grant["compliance_status"] == "FINDING_ISSUED":
        fail("ERR_GRANT_COMPLIANCE_HOLD",
             "the outstanding compliance finding must be remediated first")
    deadline = as_date(grant["spend_deadline"])
    if as_date(invoice_date) > deadline or store.today() > deadline:
        fail("ERR_GRANT_SPEND_DEADLINE_PASSED",
             "the invoice date and the clock date must be on or before the spend deadline")

    ceilings = calc.category_ceilings(grant)
    spend = dict(grant["category_spend_cents"] or {})
    already = int(spend.get(category, 0) or 0)
    if already + amount_cents > ceilings[category]:
        fail("ERR_GRANT_CATEGORY_CEILING_EXCEEDED",
             "the %s category ceiling of %d cents would be exceeded"
             % (category, ceilings[category]))
    if amount_cents > int(grant["available_cents"]):
        fail("ERR_GRANT_FUNDS_EXHAUSTED",
             "only %d cents remain available on this grant" % int(grant["available_cents"]))

    rec = store.base_record(
        improvement_grant_id=grant["id"],
        category=category,
        amount_cents=amount_cents,
        invoice_date=invoice_date,
        status="SUBMITTED",
        reimbursable_cents=0,
        disallowed_cents=0,
    )
    store.DB.grant_expenditures[rec["id"]] = rec

    grant["committed_cents"] = int(grant["committed_cents"]) + amount_cents
    grant["available_cents"] = int(grant["available_cents"]) - amount_cents
    spend[category] = already + amount_cents
    grant["category_spend_cents"] = spend
    store.touch(grant)

    return response.created(serializers.dump("grant_expenditure", rec))


@bp.get("/grant-expenditures")
def list_expenditures():
    require("StateAdministrator", "Provider")
    records = store.sort_created(list(store.DB.grant_expenditures.values()))
    for field in ("improvement_grant_id", "status", "category"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("grant_expenditure"))


@bp.get("/grant-expenditures/<grant_expenditure_id>")
def read_expenditure(grant_expenditure_id):
    principal = require("StateAdministrator", "Provider")
    line = lookups.get_expenditure(grant_expenditure_id)
    grant = lookups.get_grant(line["improvement_grant_id"])
    lookups.own_provider_id(principal, grant["provider_id"])
    return response.ok(serializers.dump("grant_expenditure", line))


@bp.post("/grant-expenditures/<grant_expenditure_id>/adjudicate")
def adjudicate_expenditure(grant_expenditure_id):
    require("StateAdministrator")
    line = lookups.get_expenditure(grant_expenditure_id)
    grant = lookups.get_grant(line["improvement_grant_id"])
    data = body()
    decision = v.req_enum(data, "decision", ["APPROVE", "REJECT"])
    v.opt_str(data, "note")

    if line["status"] != "SUBMITTED":
        fail("ERR_EXPENDITURE_STATE_INVALID",
             "only a SUBMITTED expenditure line may be adjudicated")
    if grant["compliance_status"] == "FINDING_ISSUED":
        fail("ERR_GRANT_COMPLIANCE_HOLD",
             "the outstanding compliance finding must be remediated first")

    if decision == "APPROVE":
        # The funds stay committed, so no money counter moves.
        line["status"] = "APPROVED"
        store.touch(line)
        store.touch(grant)
    else:
        amount = int(line["amount_cents"])
        category = line["category"]
        line["status"] = "REJECTED"
        store.touch(line)
        grant["committed_cents"] = int(grant["committed_cents"]) - amount
        grant["available_cents"] = int(grant["available_cents"]) + amount
        spend = dict(grant["category_spend_cents"] or {})
        spend[category] = int(spend.get(category, 0) or 0) - amount
        grant["category_spend_cents"] = spend
        hop = REJECTION_COMPLIANCE_HOP.get(grant["compliance_status"])
        if hop is not None:
            grant["compliance_status"] = hop
        store.touch(grant)

    return response.ok(serializers.dump("grant_expenditure", line))


# ------------------------------------------------------- reimburse and close


@bp.post("/improvement-grants/<improvement_grant_id>/reimburse")
def reimburse_grant(improvement_grant_id):
    require("StateAdministrator")
    grant = lookups.get_grant(improvement_grant_id)
    body()
    # A grant that never reached acceptance has released no funds and can carry no
    # expenditure line, so the waterfall would have nothing to settle.
    if grant["status"] not in ("OFFERED", "DECLINED"):
        calc.run_reimbursement_waterfall(grant)
    store.touch(grant)
    return response.ok(serializers.dump("improvement_grant", grant))


@bp.post("/improvement-grants/<improvement_grant_id>/close")
def close_grant(improvement_grant_id):
    require("StateAdministrator")
    grant = lookups.get_grant(improvement_grant_id)
    provider = store.DB.providers.get(grant["provider_id"])
    body()

    if grant["status"] not in ("OPEN", "FROZEN"):
        fail("ERR_GRANT_NOT_OPEN", "a grant may be closed only from OPEN or FROZEN")
    for line in cascades.expenditures_of(grant["id"]):
        if line["status"] == "SUBMITTED":
            fail("ERR_EXPENDITURE_STATE_INVALID",
                 "every expenditure line must be adjudicated before the grant is closed")

    recovery = calc.compute_recovery(grant)
    grant["recovery_amount_cents"] = recovery
    grant["status"] = "CLOSED"
    if recovery > 0:
        # The compliance dimension advances from wherever it stands, through
        # FINDING_ISSUED, to the terminal RECOVERY state (PRD §3.8).
        grant["compliance_status"] = "RECOVERY"
    store.touch(grant)

    if provider is not None:
        if recovery > 0:
            provider["reimbursement_adjustment_cents"] = \
                int(provider["reimbursement_adjustment_cents"]) - recovery
        store.touch(provider)

    cascades.close_allocations_for_grant(grant)
    return response.ok(serializers.dump("improvement_grant", grant))
