"""Multi-hop cascades and shared state transitions (PRD 2.8, 3.3, 3.6, 3.7, 3.8)."""

from decimal import Decimal

import calc
import errors
from calc import (LIVE_ENGAGEMENT_STATES, claims_of, dec, engagements_of_claim,
                  sections_of)
from db import new_row, now_iso, round2, store, touch
from errors import ApiError


# --------------------------------------------------------------------------
# application status / remediation counter
# --------------------------------------------------------------------------

def set_application_status(application, new_status):
    previous = application["status"]
    application["status"] = new_status
    if previous != new_status:
        account = store.insured_accounts.get(application["insured_account_id"])
        if account is not None:
            if previous == "REMEDIATION_REQUIRED":
                account["open_remediation_count"] = max(0, account["open_remediation_count"] - 1)
                touch(account)
            elif new_status == "REMEDIATION_REQUIRED":
                account["open_remediation_count"] = account["open_remediation_count"] + 1
                touch(account)
    if new_status in ("SUBMITTED", "REMEDIATION_REQUIRED"):
        application["premium_usd"] = None
    touch(application)


def refresh_attested(application):
    score, _gaps = calc.control_posture_score(application, "attested")
    application["attested_control_score"] = score
    return score


# --------------------------------------------------------------------------
# engagement termination
# --------------------------------------------------------------------------

def _terminate(engagement):
    engagement["status"] = "TERMINATED"
    touch(engagement)
    vendor = store.panel_vendors.get(engagement["panel_vendor_id"])
    if vendor is not None:
        vendor["active_engagement_count"] = max(0, vendor["active_engagement_count"] - 1)
        touch(vendor)


def terminate_claim_engagements(claim):
    for engagement in calc.sorted_by_created(engagements_of_claim(claim["id"])):
        if engagement["status"] in LIVE_ENGAGEMENT_STATES:
            _terminate(engagement)


def terminate_policy_engagements(policy):
    for claim in calc.sorted_by_created(claims_of(policy["id"])):
        terminate_claim_engagements(claim)


# --------------------------------------------------------------------------
# limit status
# --------------------------------------------------------------------------

def recompute_limit_status(policy):
    remaining = dec(policy["aggregate_limit_remaining_usd"])
    aggregate = dec(policy["aggregate_limit_usd"])
    if remaining == aggregate:
        new_status = "INTACT"
    elif remaining <= 0:
        new_status = "EXHAUSTED"
    else:
        new_status = "PARTIALLY_ERODED"
    if new_status != policy["limit_status"]:
        policy["limit_status"] = new_status
        touch(policy)
        if new_status == "EXHAUSTED":
            terminate_policy_engagements(policy)


# --------------------------------------------------------------------------
# the tower allocation waterfall
# --------------------------------------------------------------------------

def eligible_sections(claim, policy, eligible_keys):
    covered = set(claim["covered_section_keys"] or [])
    keys = [key for key in eligible_keys if key in covered]
    if not keys:
        raise ApiError(errors.ERR_NO_ELIGIBLE_COVERAGE_SECTION, 422,
                       "no confirmed coverage section is eligible for this loss")
    rows = [row for row in sections_of(policy["id"]) if row["section_key"] in keys]
    rows.sort(key=lambda row: (row["erosion_priority"], row["created_at"], row["_seq"]))
    return rows


def run_waterfall(claim, policy, loss_amount, eligible_keys, loss_source):
    sections = eligible_sections(claim, policy, eligible_keys)
    loss = round2(loss_amount)

    available_retention = max(Decimal("0"),
                              dec(policy["retention_usd"]) - dec(claim["retention_absorbed_usd"]))
    absorbed = round2(min(available_retention, loss))
    claim["retention_absorbed_usd"] = round2(dec(claim["retention_absorbed_usd"]) + absorbed)
    remainder = round2(loss - absorbed)

    policy_changed = False
    first_row = True
    for section in sections:
        if remainder <= 0:
            break
        allocated = round2(min(remainder, dec(section["sublimit_remaining_usd"])))
        if allocated <= 0:
            continue
        coinsurance = round2(allocated * dec(section["coinsurance_pct"]))
        payable = round2(allocated - coinsurance)
        net_paid = round2(min(payable, dec(policy["aggregate_limit_remaining_usd"])))
        payment = new_row({
            "incident_claim_id": claim["id"],
            "coverage_section_id": section["id"],
            "loss_source": loss_source,
            "gross_amount_usd": allocated,
            "retention_applied_usd": absorbed if first_row else round2(0),
            "coinsurance_deduction_usd": coinsurance,
            "net_paid_usd": net_paid,
            "payment_status": "POSTED",
            "reversal_reason": None,
        })
        store.claim_payments[payment["id"]] = payment
        first_row = False
        section["sublimit_remaining_usd"] = round2(dec(section["sublimit_remaining_usd"]) - allocated)
        touch(section)
        policy["aggregate_limit_remaining_usd"] = round2(
            dec(policy["aggregate_limit_remaining_usd"]) - net_paid)
        policy_changed = policy_changed or net_paid != 0
        claim["paid_total_usd"] = round2(dec(claim["paid_total_usd"]) + net_paid)
        remainder = round2(remainder - allocated)

    if remainder > 0:
        claim["unallocated_loss_usd"] = round2(dec(claim["unallocated_loss_usd"]) + remainder)
    touch(claim)
    if policy_changed:
        touch(policy)
    recompute_limit_status(policy)


# --------------------------------------------------------------------------
# claim closure paths
# --------------------------------------------------------------------------

def deny_claim(claim, denial_reason):
    claim["status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    claim["reserved_amount_usd"] = round2(0)
    touch(claim)
    terminate_claim_engagements(claim)


def cancel_policy_cascade(policy, cancellation_reason):
    policy["lifecycle_status"] = "CANCELLED"
    policy["cancelled_at"] = now_iso()
    policy["cancellation_reason"] = cancellation_reason
    touch(policy)
    closable = ("NOTIFIED", "TRIAGE", "COVERAGE_CONFIRMED", "RESPONSE_ACTIVE")
    for claim in calc.sorted_by_created(claims_of(policy["id"])):
        if claim["status"] not in closable:
            continue
        claim["status"] = "CLOSED_NO_COVERAGE"
        claim["reserved_amount_usd"] = round2(0)
        touch(claim)
        terminate_claim_engagements(claim)
