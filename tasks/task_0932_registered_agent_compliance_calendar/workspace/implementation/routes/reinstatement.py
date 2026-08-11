"""Reinstatement cases (PRD 3.11)."""

import envelope
import lookup
import serializers
import timeutil
from constants import OPEN_OBLIGATION_STATUSES
from dispatch import endpoint
from errors import ApiError
from services import obligations as obligation_service
from services import rollups, rules
from store import DB, touch


@endpoint(
    "POST", "/reinstatement-cases/{id}/assess-fees", roles=["ComplianceOfficer"], success_code=200
)
def assess_fees(context):
    case = context.row
    registration = DB.registrations.get(case["registration_id"])
    clock_date = timeutil.today()
    if case["status"] not in ("OPEN", "DENIED"):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    current_rule = rules.select(registration["state_code"], clock_date)  # rung 18
    if case["window_close_date"] is None or clock_date > case["window_close_date"]:  # rung 42
        raise ApiError("ERR_REINSTATEMENT_WINDOW_CLOSED")

    entity = lookup.entity_of_registration(registration)
    missed = [
        o
        for o in lookup.obligations_of_registration(registration["id"])
        if o["status"] in ("IN_GRACE", "DELINQUENT")
    ]
    missed.sort(key=lambda o: (o["period_year"], o["due_date"], o["created_at"], o["_seq"]))

    per_period_total = 0
    for obligation in missed:
        # PINNED: each period is priced under ITS OWN governing rule version,
        # never under the rule that happens to be open today.
        pinned_rule = DB.state_rules.get(obligation["governing_rule_id"])
        if pinned_rule is None:  # pragma: no cover - defensive
            continue
        franchise_tax = obligation_service.franchise_tax_for(
            obligation["obligation_type"], entity, pinned_rule
        )
        late_fee = obligation_service.late_fee_for(
            obligation["state_fee_cents"],
            franchise_tax,
            obligation["grace_end_date"],
            pinned_rule,
            clock_date,
        )
        per_period_total += obligation["state_fee_cents"] + franchise_tax + late_fee

    case["status"] = "FEES_ASSESSED"
    case["assessment_date"] = clock_date
    case["missed_period_count"] = len(missed)
    # only the reinstatement filing fee itself uses today's rule
    case["back_fee_total_cents"] = per_period_total + current_rule["reinstatement_fee_cents"]
    case["_assessed_obligation_ids"] = [o["id"] for o in missed]
    touch(case)
    return envelope.object_response(serializers.reinstatement_case(case))


@endpoint("POST", "/reinstatement-cases/{id}/grant", roles=["FilingAgent"], success_code=200)
def grant_case(context):
    case = context.row
    registration = DB.registrations.get(case["registration_id"])
    clock_date = timeutil.today()
    if case["status"] != "FILED" or registration is None or registration["status"] != "ADMIN_DISSOLVED":
        raise ApiError("ERR_INVALID_STATE")  # rung 16
    if case["window_close_date"] is None or clock_date > case["window_close_date"]:  # rung 42
        raise ApiError("ERR_REINSTATEMENT_WINDOW_CLOSED")

    case["status"] = "GRANTED"
    case["obligations_cured_count"] = case["missed_period_count"]
    touch(case)

    registration["status"] = "ACTIVE"
    registration["admin_dissolved_on"] = None
    for obligation_id in case.get("_assessed_obligation_ids", []):
        obligation = DB.obligations.get(obligation_id)
        if obligation is None or obligation["status"] not in OPEN_OBLIGATION_STATUSES:
            continue
        obligation_service.to_terminal(obligation, "SATISFIED", zero_total=False)
    rollups.recompute_registration_rank(registration)
    touch(registration)
    rollups.cascade_from_registration(registration)
    return envelope.object_response(serializers.reinstatement_case(case))


@endpoint("POST", "/reinstatement-cases/{id}/deny", roles=["FilingAgent"], success_code=200)
def deny_case(context):
    case = context.row
    denial_reason = context.body.string("denial_reason", required=True, non_empty=False)
    if case["status"] != "FILED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    case["status"] = "DENIED"
    case["denial_reason"] = denial_reason
    touch(case)
    return envelope.object_response(serializers.reinstatement_case(case))
