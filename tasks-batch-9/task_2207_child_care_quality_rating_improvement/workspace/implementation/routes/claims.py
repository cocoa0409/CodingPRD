"""Tiered subsidy reimbursement and retroactive reconciliation (PRD §3.7)."""

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
from validation import as_date, body, month_first_day

bp = Blueprint("claims", __name__)

def _service_units(claim):
    return sum(int(value or 0) for value in (claim["child_days"] or {}).values())


def _covers_first_day(cycle, service_month):
    """The cycle's validity window contains the first calendar day of the month."""
    first = month_first_day(service_month)
    start = as_date(cycle.get("effective_date"))
    end = as_date(cycle.get("expires_on"))
    if start is None or end is None:
        return False
    return start <= first <= end


# -------------------------------------------------------------------- claims


@bp.post("/providers/<provider_id>/subsidy-claims")
def submit_claim(provider_id):
    principal = require("Provider")
    provider = lookups.get_provider(provider_id)
    lookups.own_provider(principal, provider)
    data = body()
    service_month = v.req_service_month(data, "service_month")
    child_days = v.req_child_days(data, "child_days")

    # PRD §2.7 step 11: the provider's own standing precedes the business constraint.
    if provider["status"] != "ACTIVE":
        fail("ERR_PROVIDER_STATE_INVALID", "only an ACTIVE provider may submit a subsidy claim")

    for existing in cascades.claims_of(provider["id"]):
        if existing["service_month"] == service_month and existing["status"] != "REJECTED":
            fail("ERR_DUPLICATE_CLAIM_PERIOD",
                 "a live claim already exists for %s" % service_month)

    cycle = calc.covering_cycle(provider["id"], month_first_day(service_month))
    rec = store.base_record(
        provider_id=provider["id"],
        rating_cycle_id=cycle["id"] if cycle else None,
        service_month=service_month,
        child_days=child_days,
        base_amount_cents=calc.compute_base_amount_cents(child_days),
        tier_multiplier_applied=None,
        reimbursement_cents=None,
        variant_applied=None,
        status="SUBMITTED",
        paid_on=None,
    )
    store.DB.subsidy_claims[rec["id"]] = rec
    return response.created(serializers.dump("subsidy_claim", rec))


@bp.get("/subsidy-claims")
def list_claims():
    require("StateAdministrator", "Provider")
    records = store.sort_created(list(store.DB.subsidy_claims.values()))
    for field in ("provider_id", "rating_cycle_id", "status", "service_month"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("subsidy_claim"))


@bp.get("/subsidy-claims/<subsidy_claim_id>")
def read_claim(subsidy_claim_id):
    principal = require("StateAdministrator", "Provider")
    claim = lookups.get_claim(subsidy_claim_id)
    lookups.own_provider_id(principal, claim["provider_id"])
    return response.ok(serializers.dump("subsidy_claim", claim))


@bp.post("/subsidy-claims/<subsidy_claim_id>/adjudicate")
def adjudicate_claim(subsidy_claim_id):
    require("StateAdministrator")
    claim = lookups.get_claim(subsidy_claim_id)
    provider = lookups.get_provider(claim["provider_id"])
    data = body()
    decision = v.req_enum(data, "decision", ["APPROVE", "REJECT"])
    variant = v.opt_enum(data, "variant", v.CLAIM_VARIANTS)

    if decision == "APPROVE":
        if claim["status"] != "SUBMITTED":
            fail("ERR_CLAIM_STATE_INVALID", "approval requires the claim in SUBMITTED")

        # Check 1: the coverage rule.
        cycle = store.DB.rating_cycles.get(claim.get("rating_cycle_id"))
        if cycle is None or not _covers_first_day(cycle, claim["service_month"]) or \
                cycle["status"] != "ACTIVE" or cycle["publication_status"] != "PUBLISHED":
            fail("ERR_CLAIM_MONTH_NOT_COVERED",
                 "no ACTIVE published rating cycle covers %s" % claim["service_month"])
        # Check 2: the open-appeal rule.
        if cascades.has_open_appeal(cycle["id"]):
            fail("ERR_OPEN_APPEAL_BLOCKS_ACTION", "an appeal of the covering cycle is still open")
        # Check 3: the service-units rule.
        if _service_units(claim) <= 0:
            fail("ERR_ZERO_SERVICE_UNITS", "the claim carries no subsidised child-days")

        # The interim variant is the default at first approval.
        applied = variant or "INTERIM"
        multiplier, reimbursement = calc.compute_subsidy(provider, claim, applied)
        claim["base_amount_cents"] = calc.compute_base_amount_cents(claim["child_days"])
        claim["tier_multiplier_applied"] = multiplier
        claim["reimbursement_cents"] = reimbursement
        claim["variant_applied"] = applied
        claim["status"] = "APPROVED"
        store.touch(claim)
    else:
        if claim["status"] not in ("SUBMITTED", "RECONCILE_REQUIRED"):
            fail("ERR_CLAIM_STATE_INVALID",
                 "rejection is available only from SUBMITTED or RECONCILE_REQUIRED")
        claim["status"] = "REJECTED"
        claim["reimbursement_cents"] = 0
        store.touch(claim)

    return response.ok(serializers.dump("subsidy_claim", claim))


@bp.post("/subsidy-claims/<subsidy_claim_id>/pay")
def pay_claim(subsidy_claim_id):
    require("StateAdministrator")
    claim = lookups.get_claim(subsidy_claim_id)
    provider = lookups.get_provider(claim["provider_id"])
    body()

    if claim["status"] not in ("APPROVED", "RECONCILE_REQUIRED"):
        fail("ERR_CLAIM_STATE_INVALID",
             "payment is available only from APPROVED or RECONCILE_REQUIRED")

    if claim["status"] == "APPROVED" and int(claim.get("reimbursement_cents") or 0) <= 0:
        fail("ERR_ZERO_SERVICE_UNITS", "the claim carries no payable reimbursement")

    # A provider that lost its rating between approval and payment is never paid at
    # the stale multiplier (PRD §3.7).
    if provider.get("current_tier") is None:
        fail("ERR_PROVIDER_UNRATED", "the provider holds no current tier at payment time")
    if provider["status"] != "ACTIVE":
        fail("ERR_PROVIDER_STATE_INVALID", "the provider must be ACTIVE to be paid")

    if claim["status"] == "RECONCILE_REQUIRED":
        if cascades.has_open_appeal(claim.get("rating_cycle_id")):
            fail("ERR_OPEN_APPEAL_BLOCKS_ACTION", "an appeal of the claim's cycle is still open")
        paid_before = claim.pop("_paid_reimbursement_cents", None)
        if paid_before is None:
            paid_before = int(claim.get("reimbursement_cents") or 0)
        multiplier, reconciled = calc.compute_subsidy(provider, claim, "RECONCILED")
        claim["tier_multiplier_applied"] = multiplier
        claim["reimbursement_cents"] = reconciled
        claim["variant_applied"] = "RECONCILED"
        # PRD §2.10: the reconciled payment returns the correction balance to exactly
        # its pre-cascade value, so the reversal uses the delta the cascade recorded.
        delta = claim.pop("_reconcile_adjustment_cents", None)
        if delta is None:
            delta = reconciled - int(paid_before)
        if delta:
            # The flag-then-repay pair leaves the conserved correction unchanged.
            provider["reimbursement_adjustment_cents"] = \
                int(provider["reimbursement_adjustment_cents"]) - delta
            store.touch(provider)

    claim["status"] = "PAID"
    claim["paid_on"] = store.now()
    store.touch(claim)
    return response.ok(serializers.dump("subsidy_claim", claim))
