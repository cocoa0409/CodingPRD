"""/pbm/claims — claim submission, adjudication, payment, reversal.

This module concentrates the bulk of the PBM business logic:

- Channel/days_supply band enforcement (RETAIL_30 1..34, MAIL_ORDER_90 60..100,
  SPECIALTY 1..30)
- Forward-looking submission estimate (estimated_member_cost_cents)
- Chronological adjudication (re-reads Member YTD at adjudication time)
- Refill-too-soon half-open interval check
- Cross-entity preconditions: Member ACTIVE, PA window, step therapy, copay
  card matching, formulary coverage
- Side-effect order on adjudicate: deductible -> oop -> card; then
  CopayCard.status ACTIVE -> EXHAUSTED if cap reached
- Pay: parallel payment_status flip and rebate accrual ledger entry
- Reverse: refund member YTD, refund card, clawback ledger entry if within
  window; the per-claim ledger sum invariants to 0 after clawback
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from ..auth import require_roles
from ..envelope import success, list_success
from ..errors import (
    APIError,
    ERR_CHANNEL_DAYS_SUPPLY_MISMATCH,
    ERR_CLAWBACK_WINDOW_EXPIRED,
    ERR_COPAY_CARD_MISMATCH,
    ERR_DRUG_NOT_ON_FORMULARY,
    ERR_INVALID_STATE,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_PA_DENIED,
    ERR_PA_EXPIRED,
    ERR_PA_MISMATCH,
    ERR_PA_REQUIRED,
    ERR_PA_REVOKED,
    ERR_REFILL_TOO_SOON,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SPECIALTY_CHANNEL_REQUIRED,
    ERR_STEP_THERAPY_NOT_SATISFIED,
    ERR_VALIDATION,
)
from ..store import STORE
from ..validation import (
    as_int,
    check_version,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
    round_half_up_cents,
)
from ..services.pricing import compute_cost

bp = Blueprint("claims", __name__)


CHANNELS = {"RETAIL_30", "MAIL_ORDER_90", "SPECIALTY"}


def _serialize(c: dict) -> dict:
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "drug_id": c["drug_id"],
        "channel": c["channel"],
        "days_supply": c["days_supply"],
        "quantity": c["quantity"],
        "prior_auth_id": c.get("prior_auth_id"),
        "copay_card_id": c.get("copay_card_id"),
        "estimated_member_cost_cents": c["estimated_member_cost_cents"],
        "adjudicated_allowed_cents": c["adjudicated_allowed_cents"],
        "adjudicated_member_cost_cents": c["adjudicated_member_cost_cents"],
        "adjudicated_plan_paid_cents": c["adjudicated_plan_paid_cents"],
        "copay_card_paid_cents": c["copay_card_paid_cents"],
        "status": c["status"],
        "payment_status": c["payment_status"],
        "reject_reason": c.get("reject_reason"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _check_channel_days_supply(channel: str, days_supply: int, quantity: int) -> None:
    if channel not in CHANNELS:
        raise APIError(ERR_VALIDATION, f"channel must be one of {sorted(CHANNELS)}", 422)
    if quantity < 1:
        raise APIError(ERR_CHANNEL_DAYS_SUPPLY_MISMATCH, "quantity must be >= 1", 422)
    if channel == "RETAIL_30" and not (1 <= days_supply <= 34):
        raise APIError(ERR_CHANNEL_DAYS_SUPPLY_MISMATCH, "RETAIL_30 requires 1 <= days_supply <= 34", 422)
    if channel == "MAIL_ORDER_90" and not (60 <= days_supply <= 100):
        raise APIError(ERR_CHANNEL_DAYS_SUPPLY_MISMATCH, "MAIL_ORDER_90 requires 60 <= days_supply <= 100", 422)
    if channel == "SPECIALTY" and not (1 <= days_supply <= 30):
        raise APIError(ERR_CHANNEL_DAYS_SUPPLY_MISMATCH, "SPECIALTY requires 1 <= days_supply <= 30", 422)


def _parse_ts(ts_str: str) -> datetime:
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _find_active_formulary_entry(plan_id: str, drug_id: str):
    for fe in STORE.formulary_entries.values():
        if fe["plan_id"] == plan_id and fe["drug_id"] == drug_id and fe["status"] == "ACTIVE":
            return fe
    return None


def _find_active_rebate_agreement(drug_id: str):
    for a in STORE.rebate_agreements.values():
        if a["drug_id"] == drug_id and a["status"] == "ACTIVE":
            return a
    return None


# ----- POST /pbm/claims (submit) -----

@bp.post("/pbm/claims")
@require_roles("Prescriber", "ClaimsAdjudicator")
def submit_claim():
    body = get_json_body()
    member_id = require_field(body, "member_id")
    drug_id = require_field(body, "drug_id")
    channel = require_field(body, "channel")
    # PRD §2.8 rung 10 + §3.4: days_supply / quantity violations surface
    # ERR_CHANNEL_DAYS_SUPPLY_MISMATCH (422). We coerce to int here but
    # defer the >=1 / channel-band check to _check_channel_days_supply.
    days_supply = as_int(require_field(body, "days_supply"), "days_supply")
    quantity = as_int(require_field(body, "quantity"), "quantity")
    pa_id = body.get("prior_auth_id")
    card_id = body.get("copay_card_id")

    _check_channel_days_supply(channel, days_supply, quantity)

    with STORE.lock:
        # Existence resolution in left-to-right order per PRD §2.7.
        member = STORE.members.get(member_id)
        if member is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Member {member_id} not found", 404)
        drug = STORE.drugs.get(drug_id)
        if drug is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Drug {drug_id} not found", 404)
        pa = None
        if pa_id is not None:
            pa = STORE.prior_authorizations.get(pa_id)
            if pa is None:
                raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pa_id} not found", 404)
        card = None
        if card_id is not None:
            card = STORE.copay_cards.get(card_id)
            if card is None:
                raise APIError(ERR_RESOURCE_NOT_FOUND, f"CopayCard {card_id} not found", 404)

        plan = STORE.plans.get(member["plan_id"])
        # At creation, the formulary entry is *informational* for the estimate;
        # missing entry simply means we cannot project a tiered share — fall
        # back to coinsurance branch with tier=5 to keep the estimate sane.
        fe = _find_active_formulary_entry(member["plan_id"], drug_id) if plan else None

        if plan is None:
            # Plan should exist for any valid member but guard anyway.
            raise APIError(ERR_RESOURCE_NOT_FOUND, "Plan referenced by Member not found", 404)

        cost = compute_cost(
            drug=drug,
            plan=plan,
            formulary_entry=fe,
            member=member,
            claim_channel=channel,
            claim_quantity=quantity,
            copay_card=card,
            claim_drug_id=drug_id,
            claim_member_id=member_id,
        )

        claim = STORE.init_common_fields({
            "member_id": member_id,
            "drug_id": drug_id,
            "channel": channel,
            "days_supply": days_supply,
            "quantity": quantity,
            "prior_auth_id": pa_id,
            "copay_card_id": card_id,
            "estimated_member_cost_cents": cost["member_cost_cents"],
            "adjudicated_allowed_cents": 0,
            "adjudicated_member_cost_cents": 0,
            "adjudicated_plan_paid_cents": 0,
            "copay_card_paid_cents": 0,
            "status": "SUBMITTED",
            "payment_status": "UNPAID",
            "reject_reason": None,
            # bookkeeping — captured for refill check / reverse refunds
            "adjudicated_at": None,
            "adjudicated_deductible_portion": 0,
        })
        STORE.claims[claim["id"]] = claim
    return success(_serialize(claim), status=201)


# ----- GET /pbm/claims -----

@bp.get("/pbm/claims")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def list_claims():
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    drug_id = request.args.get("drug_id")
    status_filter = request.args.get("status")
    channel_filter = request.args.get("channel")
    with STORE.lock:
        items = list(STORE.claims.values())
    if member_id:
        items = [c for c in items if c["member_id"] == member_id]
    if drug_id:
        items = [c for c in items if c["drug_id"] == drug_id]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    if channel_filter:
        items = [c for c in items if c["channel"] == channel_filter]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, total = paginate(items, limit, offset)
    return list_success([_serialize(c) for c in page], limit=limit, offset=offset, total_count=total)


@bp.get("/pbm/claims/<cid>")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def get_claim(cid: str):
    with STORE.lock:
        claim = STORE.claims.get(cid)
    if claim is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, f"Claim {cid} not found", 404)
    return success(_serialize(claim))


# ----- POST /pbm/claims/{id}/adjudicate -----

def _check_pa(claim: dict, drug: dict, pa: dict | None, now: datetime) -> None:
    """Apply PA-related preconditions for adjudicate per PRD §3.5."""
    if not drug["requires_prior_auth"]:
        return
    # PA must exist and be valid.
    if pa is None:
        raise APIError(ERR_PA_REQUIRED, "Drug requires PA but no PA was supplied", 422)
    if pa["member_id"] != claim["member_id"] or pa["drug_id"] != claim["drug_id"]:
        raise APIError(ERR_PA_MISMATCH, "PA member_id/drug_id does not match the claim", 422)
    status = pa["status"]
    if status == "DENIED":
        raise APIError(ERR_PA_DENIED, "Referenced PA is DENIED", 422)
    if status == "REVOKED":
        raise APIError(ERR_PA_REVOKED, "Referenced PA is REVOKED", 422)
    if status == "EXPIRED":
        raise APIError(ERR_PA_EXPIRED, "Referenced PA is EXPIRED", 422)
    if status != "APPROVED":
        raise APIError(ERR_PA_REQUIRED, f"Referenced PA is {status}, must be APPROVED", 422)
    eff_start = _parse_ts(pa["effective_start"])
    eff_end = _parse_ts(pa["effective_end"])
    # closed-left, open-right: effective_start <= now < effective_end
    if not (eff_start <= now < eff_end):
        raise APIError(ERR_PA_EXPIRED, "PA not in effective window", 422)


def _check_step_therapy(claim: dict, drug: dict, has_approved_pa: bool, member: dict) -> None:
    if drug.get("step_therapy_predecessor_ndc") is None:
        return
    if has_approved_pa:
        return
    predecessor_ndc = drug["step_therapy_predecessor_ndc"]
    # Find the predecessor drug(s) (ACTIVE or otherwise — we resolve by ndc).
    predecessor_drug_ids = {d["id"] for d in STORE.drugs.values() if d["ndc"] == predecessor_ndc}
    if not predecessor_drug_ids:
        raise APIError(
            ERR_STEP_THERAPY_NOT_SATISFIED,
            f"No drug found with ndc {predecessor_ndc}",
            422,
        )
    benefit_year_start = _parse_ts(member["benefit_year_start"])
    for c in STORE.claims.values():
        if (
            c["member_id"] == member["id"]
            and c["drug_id"] in predecessor_drug_ids
            and c["status"] == "PAID"
        ):
            adjudicated_at = c.get("adjudicated_at")
            if adjudicated_at is None:
                continue
            adj_dt = _parse_ts(adjudicated_at)
            if adj_dt >= benefit_year_start:
                return
    raise APIError(
        ERR_STEP_THERAPY_NOT_SATISFIED,
        "No PAID predecessor claim for this member within the current benefit year",
        422,
    )


def _check_refill_too_soon(candidate: dict, now: datetime) -> None:
    """Half-open interval overlap [start, start + days_supply) at one-day granularity."""
    cand_start = now
    cand_end = now + timedelta(days=int(candidate["days_supply"]))
    for x in STORE.claims.values():
        if x["id"] == candidate["id"]:
            continue
        if x["member_id"] != candidate["member_id"] or x["drug_id"] != candidate["drug_id"]:
            continue
        if x["status"] not in ("ADJUDICATED", "PAID"):
            continue
        adjudicated_at = x.get("adjudicated_at")
        if adjudicated_at is None:
            continue
        start_x = _parse_ts(adjudicated_at)
        end_x = start_x + timedelta(days=int(x["days_supply"]))
        # Overlap if start_c < end_x AND start_x < end_c.
        if cand_start < end_x and start_x < cand_end:
            raise APIError(
                ERR_REFILL_TOO_SOON,
                "Candidate supply window overlaps an existing ADJUDICATED/PAID claim",
                409,
            )


@bp.post("/pbm/claims/<cid>/adjudicate")
@require_roles("ClaimsAdjudicator")
def adjudicate_claim(cid: str):
    body = get_json_body()
    with STORE.lock:
        claim = STORE.claims.get(cid)
        if claim is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Claim {cid} not found", 404)
        if claim["status"] != "SUBMITTED":
            raise APIError(
                ERR_INVALID_STATE,
                f"Claim must be SUBMITTED to adjudicate; current={claim['status']}",
                409,
            )
        member = STORE.members.get(claim["member_id"])
        drug = STORE.drugs.get(claim["drug_id"])
        if member is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, "Member referenced by claim not found", 404)
        if drug is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, "Drug referenced by claim not found", 404)
        plan = STORE.plans.get(member["plan_id"])
        if plan is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, "Plan referenced by member not found", 404)
        pa = STORE.prior_authorizations.get(claim["prior_auth_id"]) if claim.get("prior_auth_id") else None
        card = STORE.copay_cards.get(claim["copay_card_id"]) if claim.get("copay_card_id") else None

        check_version(body, claim)

        # ----- precondition ladder (PRD §2.8) -----
        # 5. cross-entity member state
        if member["enrollment_status"] != "ACTIVE":
            return _reject(claim, ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")

        # 6. specialty channel match
        if drug["is_specialty"] and claim["channel"] != "SPECIALTY":
            return _reject(claim, ERR_SPECIALTY_CHANNEL_REQUIRED, "Specialty drug requires SPECIALTY channel")

        # 7. prior authorization requirement
        now = STORE.clock.now()
        try:
            _check_pa(claim, drug, pa, now)
            has_approved_pa = bool(
                pa
                and pa["status"] == "APPROVED"
                and pa["member_id"] == claim["member_id"]
                and pa["drug_id"] == claim["drug_id"]
                and _parse_ts(pa["effective_start"]) <= now < _parse_ts(pa["effective_end"])
            )
        except APIError as e:
            return _reject(claim, e.error_id, e.message)

        # 8. step therapy
        try:
            _check_step_therapy(claim, drug, has_approved_pa, member)
        except APIError as e:
            return _reject(claim, e.error_id, e.message)

        # 9. refill-too-soon
        try:
            _check_refill_too_soon(claim, now)
        except APIError as e:
            return _reject(claim, e.error_id, e.message)

        # 10. channel/days_supply consistency (re-check at adjudicate)
        try:
            _check_channel_days_supply(claim["channel"], claim["days_supply"], claim["quantity"])
        except APIError as e:
            return _reject(claim, e.error_id, e.message)

        # 11. formulary coverage
        fe = _find_active_formulary_entry(member["plan_id"], drug["id"])
        if fe is None:
            return _reject(claim, ERR_DRUG_NOT_ON_FORMULARY, "No ACTIVE FormularyEntry for plan+drug")

        # 12. copay card matching
        if card is not None:
            if (
                card["member_id"] != claim["member_id"]
                or card["drug_id"] != claim["drug_id"]
                or card["status"] != "ACTIVE"
            ):
                return _reject(claim, ERR_COPAY_CARD_MISMATCH, "Copay card mismatch or not ACTIVE")

        # ----- all preconditions pass: compute and commit -----
        cost = compute_cost(
            drug=drug,
            plan=plan,
            formulary_entry=fe,
            member=member,
            claim_channel=claim["channel"],
            claim_quantity=claim["quantity"],
            copay_card=card,
            claim_drug_id=claim["drug_id"],
            claim_member_id=claim["member_id"],
        )

        # Write computed fields on the claim.
        claim["adjudicated_allowed_cents"] = cost["allowed_cents"]
        claim["adjudicated_member_cost_cents"] = cost["member_cost_cents"]
        claim["adjudicated_plan_paid_cents"] = cost["plan_paid_cents"]
        claim["copay_card_paid_cents"] = cost["card_payable"]
        claim["adjudicated_deductible_portion"] = cost["deductible_portion"]
        claim["status"] = "ADJUDICATED"
        claim["adjudicated_at"] = STORE.now_ts()
        STORE.bump(claim)

        # Side effects in pinned order: deductible -> oop -> card.
        if cost["deductible_portion"] > 0 or cost["member_pre_card"] > 0:
            member["ytd_deductible_paid_cents"] = int(member["ytd_deductible_paid_cents"]) + cost["deductible_portion"]
            member["ytd_oop_paid_cents"] = int(member["ytd_oop_paid_cents"]) + cost["member_pre_card"]
            STORE.bump(member)

        if card is not None and cost["card_payable"] > 0:
            card["used_cents"] = int(card["used_cents"]) + cost["card_payable"]
            # Hard cap; if at/over max, flip to EXHAUSTED.
            if card["used_cents"] >= int(card["max_benefit_cents"]):
                card["used_cents"] = int(card["max_benefit_cents"])
                card["status"] = "EXHAUSTED"
            STORE.bump(card)

        return success(_serialize(claim))


def _reject(claim: dict, error_id: str, message: str):
    """Reject a SUBMITTED claim with a deterministic reason and surface the error.

    State machine table specifies that a precondition failure transitions
    SUBMITTED -> REJECTED with reject_reason set, leaving Member YTD untouched.
    Per PRD §3.5 the response also surfaces the specific error id.
    """
    claim["status"] = "REJECTED"
    claim["reject_reason"] = error_id
    STORE.bump(claim)
    raise APIError(error_id, message)


# ----- POST /pbm/claims/{id}/pay -----

@bp.post("/pbm/claims/<cid>/pay")
@require_roles("ClaimsAdjudicator")
def pay_claim(cid: str):
    body = get_json_body()
    with STORE.lock:
        claim = STORE.claims.get(cid)
        if claim is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Claim {cid} not found", 404)
        if claim["status"] != "ADJUDICATED":
            raise APIError(
                ERR_INVALID_STATE,
                f"Claim must be ADJUDICATED to pay; current={claim['status']}",
                409,
            )
        check_version(body, claim)

        claim["status"] = "PAID"
        claim["payment_status"] = "PAID"
        STORE.bump(claim)

        # Post rebate accrual ledger entry when an ACTIVE agreement covers the drug.
        agreement = _find_active_rebate_agreement(claim["drug_id"])
        if agreement is not None:
            from decimal import Decimal
            accrued = round_half_up_cents(
                Decimal(str(claim["adjudicated_plan_paid_cents"])) * Decimal(str(agreement["rebate_rate"]))
            )
            entry_id = STORE.new_id()
            ts = STORE.now_ts()
            entry = {
                "id": entry_id,
                "claim_id": claim["id"],
                "rebate_agreement_id": agreement["id"],
                "entry_type": "REBATE_ACCRUED",
                "amount_cents": accrued,
                "posted_at": ts,
                "created_at": ts,
            }
            STORE.ledger_entries[entry_id] = entry

        return success(_serialize(claim))


# ----- POST /pbm/claims/{id}/reverse -----

@bp.post("/pbm/claims/<cid>/reverse")
@require_roles("ClaimsAdjudicator")
def reverse_claim(cid: str):
    body = get_json_body()
    with STORE.lock:
        claim = STORE.claims.get(cid)
        if claim is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Claim {cid} not found", 404)
        if claim["status"] != "PAID":
            raise APIError(
                ERR_INVALID_STATE,
                f"Claim must be PAID to reverse; current={claim['status']}",
                409,
            )
        check_version(body, claim)

        # Find the accrual ledger entry, if any.
        accrual = None
        for e in STORE.ledger_entries.values():
            if e["claim_id"] == claim["id"] and e["entry_type"] == "REBATE_ACCRUED":
                accrual = e
                break

        # Clawback-window gate: REVERSE requires clock_now() <
        # accrual.posted_at + agreement.clawback_window_days days (only when accrual exists).
        now = STORE.clock.now()
        within_window = True
        if accrual is not None:
            agreement = STORE.rebate_agreements.get(accrual["rebate_agreement_id"])
            if agreement is None:
                # Defensive: agreement should not vanish, but treat as outside window.
                within_window = False
            else:
                deadline = _parse_ts(accrual["posted_at"]) + timedelta(days=int(agreement["clawback_window_days"]))
                within_window = now < deadline
            if not within_window:
                raise APIError(
                    ERR_CLAWBACK_WINDOW_EXPIRED,
                    "Clawback window has expired; cannot reverse",
                    422,
                )

        # Apply reversal cascade.
        claim["status"] = "REVERSED"
        claim["payment_status"] = "REFUNDED"
        STORE.bump(claim)

        member = STORE.members.get(claim["member_id"])
        if member is not None:
            ded_portion = int(claim.get("adjudicated_deductible_portion", 0))
            member["ytd_deductible_paid_cents"] = max(
                int(member["ytd_deductible_paid_cents"]) - ded_portion, 0
            )
            # OOP was incremented by member_pre_card == member_cost + card_payable
            member_pre_card = int(claim["adjudicated_member_cost_cents"]) + int(claim["copay_card_paid_cents"])
            member["ytd_oop_paid_cents"] = max(
                int(member["ytd_oop_paid_cents"]) - member_pre_card, 0
            )
            STORE.bump(member)

        if claim.get("copay_card_id") and int(claim["copay_card_paid_cents"]) > 0:
            card = STORE.copay_cards.get(claim["copay_card_id"])
            if card is not None:
                card["used_cents"] = max(int(card["used_cents"]) - int(claim["copay_card_paid_cents"]), 0)
                if card["status"] == "EXHAUSTED" and card["used_cents"] < int(card["max_benefit_cents"]):
                    card["status"] = "ACTIVE"
                STORE.bump(card)

        # Clawback ledger entry, if accrual existed (within window only).
        if accrual is not None:
            entry_id = STORE.new_id()
            ts = STORE.now_ts()
            clawback = {
                "id": entry_id,
                "claim_id": claim["id"],
                "rebate_agreement_id": accrual["rebate_agreement_id"],
                "entry_type": "REBATE_CLAWBACK",
                "amount_cents": -int(accrual["amount_cents"]),
                "posted_at": ts,
                "created_at": ts,
            }
            STORE.ledger_entries[entry_id] = clawback

        return success(_serialize(claim))
