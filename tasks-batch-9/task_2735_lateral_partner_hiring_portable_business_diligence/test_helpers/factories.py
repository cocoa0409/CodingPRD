"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PRACTICE_GROUP_NAME": "Corporate & Securities",
    "SECOND_PRACTICE_GROUP_NAME": "Litigation",
    "GUARANTEE_BUDGET_TOTAL_USD": 5000000.00,
    "ONBOARDING_CAPACITY": 2,
    "LEVERAGE_RATIO": 3.20,
    "TARGET_STANDARD_RATE_USD": 950.00,
    "SEARCH_FIRM_NAME": "Meridian Legal Search",
    "SECOND_SEARCH_FIRM_NAME": "Halcyon Partner Search",
    "MAX_FEE_PCT": 0.3000,
    "MAX_CONCURRENT_ENGAGEMENTS": 2,
    "FEE_PCT": 0.2500,
    "FEE_CAP_USD": 400000.00,
    "EXCLUSIVITY_START_DATE": "2026-08-01T00:00:00.000Z",
    "EXCLUSIVITY_END_DATE": "2026-12-01T00:00:00.000Z",
    "TAIL_OFF_DAYS": 90,
    "CANDIDATE_FULL_NAME": "Dana Whitfield",
    "SECOND_CANDIDATE_FULL_NAME": "Priya Raghavan",
    "PRIOR_FIRM_NAME": "Ashworth & Pine LLP",
    "SPONSOR_USER_ID": "user-sponsor-1",
    "CURRENT_STANDARD_RATE_USD": 875.00,
    "NOTICE_PERIOD_DAYS": 45,
    "NON_SOLICIT_DAYS": 30,
    "DECLARED_PRIOR_YEAR_BILLINGS_USD": 3000000.00,
    "DECLARED_PRIOR_YEAR_COLLECTIONS_USD": 2600000.00,
    "DECLARED_REALIZATION_RATE": 0.8700,
    "PRIMARY_MATTER_TYPES": ["M_AND_A", "LITIGATION", "TAX"],
    "BASELINE_DATE": "2026-07-01T00:00:00.000Z",
    "GUARANTEED_COMP_USD": 500000.00,
    "SIGNING_BONUS_USD": 50000.00,
    "PLANNED_STANDARD_RATE_USD": 900.00,
    "CROSS_SELL_TARGET_COUNT": 3,
    "ONBOARDING_START_DATE": "2026-10-01T00:00:00.000Z",
    "ONBOARDING_END_DATE": "2027-06-30T00:00:00.000Z",
}


def create_practice_group_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PRACTICE_GROUP_NAME"],
        "guarantee_budget_total_usd": DEFAULTS["GUARANTEE_BUDGET_TOTAL_USD"],
        "onboarding_capacity": DEFAULTS["ONBOARDING_CAPACITY"],
        "leverage_ratio": DEFAULTS["LEVERAGE_RATIO"],
        "target_standard_rate_usd": DEFAULTS["TARGET_STANDARD_RATE_USD"],
    }
    payload.update(overrides)
    return payload


def freeze_practice_group_payload(**overrides) -> dict:
    payload = {"reason": "Lateral hiring paused pending partnership review."}
    payload.update(overrides)
    return payload


def create_search_firm_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SEARCH_FIRM_NAME"],
        "max_fee_pct": DEFAULTS["MAX_FEE_PCT"],
        "max_concurrent_engagements": DEFAULTS["MAX_CONCURRENT_ENGAGEMENTS"],
    }
    payload.update(overrides)
    return payload


def create_engagement_payload(search_firm_id, practice_group_id, **overrides) -> dict:
    payload = {
        "search_firm_id": search_firm_id,
        "practice_group_id": practice_group_id,
        "fee_pct": DEFAULTS["FEE_PCT"],
        "fee_cap_usd": DEFAULTS["FEE_CAP_USD"],
        "exclusivity_start_date": DEFAULTS["EXCLUSIVITY_START_DATE"],
        "exclusivity_end_date": DEFAULTS["EXCLUSIVITY_END_DATE"],
        "tail_off_days": DEFAULTS["TAIL_OFF_DAYS"],
    }
    payload.update(overrides)
    return payload


def terminate_engagement_payload(**overrides) -> dict:
    payload = {"reason": "Search mandate withdrawn after the lateral stalled."}
    payload.update(overrides)
    return payload


def create_candidate_payload(practice_group_id, engagement_id, **overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CANDIDATE_FULL_NAME"],
        "prior_firm_name": DEFAULTS["PRIOR_FIRM_NAME"],
        "target_practice_group_id": practice_group_id,
        "sourcing_engagement_id": engagement_id,
        "sponsor_user_id": DEFAULTS["SPONSOR_USER_ID"],
        "current_standard_rate_usd": DEFAULTS["CURRENT_STANDARD_RATE_USD"],
        "notice_period_days": DEFAULTS["NOTICE_PERIOD_DAYS"],
        "non_solicit_days": DEFAULTS["NON_SOLICIT_DAYS"],
        "approach_confidential": True,
    }
    payload.update(overrides)
    return payload


def withdraw_candidate_payload(**overrides) -> dict:
    payload = {"withdrawal_reason": "Candidate accepted a counter-offer in place."}
    payload.update(overrides)
    return payload


def create_questionnaire_payload(**overrides) -> dict:
    payload = {
        "declared_prior_year_billings_usd": DEFAULTS[
            "DECLARED_PRIOR_YEAR_BILLINGS_USD"
        ],
        "declared_prior_year_collections_usd": DEFAULTS[
            "DECLARED_PRIOR_YEAR_COLLECTIONS_USD"
        ],
        "declared_realization_rate": DEFAULTS["DECLARED_REALIZATION_RATE"],
        "primary_matter_types": list(DEFAULTS["PRIMARY_MATTER_TYPES"]),
    }
    payload.update(overrides)
    return payload


def request_revision_payload(**overrides) -> dict:
    payload = {"revision_note": "Please disclose the remaining client relationships."}
    payload.update(overrides)
    return payload


def create_client_book_entry_payload(**overrides) -> dict:
    payload = {
        "client_name": "Northwind Holdings",
        "relationship_role": "BILLING_ATTORNEY",
        "client_consent_status": "CONSENT_CONFIRMED",
        "claimed_annual_billings_usd": 1600000.00,
        "claimed_portability_pct": 0.8000,
        "claimed_realization_rate": 1.0000,
        "matter_types": ["M_AND_A", "SECURITIES"],
    }
    payload.update(overrides)
    return payload


def create_collection_record_payload(client_book_entry_id=None, **overrides) -> dict:
    payload = {
        "record_type": "HISTORICAL",
        "period_end_date": "2023-12-31T00:00:00.000Z",
        "amount_usd": 1410000.00,
        "status": "VERIFIED",
        "source": "PRIOR_FIRM_STATEMENT",
    }
    if client_book_entry_id is not None:
        payload["client_book_entry_id"] = client_book_entry_id
    payload.update(overrides)
    return payload


def create_assessment_payload(expected_questionnaire_version, **overrides) -> dict:
    payload = {
        "baseline_date": DEFAULTS["BASELINE_DATE"],
        "governing_basis": "VALIDATED",
        "expected_questionnaire_version": expected_questionnaire_version,
    }
    payload.update(overrides)
    return payload


def create_conflict_check_payload(**overrides) -> dict:
    payload = {
        "adverse_party_name": "Vertex Capital",
        "affected_matter_types": ["M_AND_A"],
        "severity": "POSITIONAL",
    }
    payload.update(overrides)
    return payload


def clear_conflict_check_payload(**overrides) -> dict:
    payload = {"resolution_note": "Positional only; no substantive adversity."}
    payload.update(overrides)
    return payload


def create_conflict_waiver_payload(**overrides) -> dict:
    payload = {
        "waiver_strategy": "ADVANCE_CONSENT",
        "requested_from_client": "Vertex Capital",
        "response_deadline_date": "2026-09-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def grant_waiver_payload(**overrides) -> dict:
    payload = {"resolution_note": "Client signed the advance-consent letter."}
    payload.update(overrides)
    return payload


def refuse_waiver_payload(**overrides) -> dict:
    payload = {"resolution_note": "Client declined to sign the waiver."}
    payload.update(overrides)
    return payload


def rescind_declination_payload(**overrides) -> dict:
    payload = {"rescission_note": "Matter reassigned; the conflict no longer bites."}
    payload.update(overrides)
    return payload


def create_offer_payload(
    portability_assessment_id, expected_candidate_version, **overrides
) -> dict:
    payload = {
        "portability_assessment_id": portability_assessment_id,
        "guaranteed_comp_usd": DEFAULTS["GUARANTEED_COMP_USD"],
        "signing_bonus_usd": DEFAULTS["SIGNING_BONUS_USD"],
        "expected_candidate_version": expected_candidate_version,
    }
    payload.update(overrides)
    return payload


def redraft_offer_payload(**overrides) -> dict:
    payload = {
        "guaranteed_comp_usd": 460000.00,
        "signing_bonus_usd": 40000.00,
    }
    payload.update(overrides)
    return payload


def submit_offer_payload(**overrides) -> dict:
    payload = {"eligible_voter_count": 3}
    payload.update(overrides)
    return payload


def counter_offer_payload(**overrides) -> dict:
    payload = {"counter_note": "Committee wants a lower guarantee."}
    payload.update(overrides)
    return payload


def cast_vote_payload(**overrides) -> dict:
    payload = {"decision": "APPROVE", "round_number": 1}
    payload.update(overrides)
    return payload


def create_integration_plan_payload(practice_group_id, offer_id, **overrides) -> dict:
    payload = {
        "practice_group_id": practice_group_id,
        "offer_id": offer_id,
        "onboarding_start_date": DEFAULTS["ONBOARDING_START_DATE"],
        "onboarding_end_date": DEFAULTS["ONBOARDING_END_DATE"],
        "planned_standard_rate_usd": DEFAULTS["PLANNED_STANDARD_RATE_USD"],
        "cross_sell_target_count": DEFAULTS["CROSS_SELL_TARGET_COUNT"],
    }
    payload.update(overrides)
    return payload


def abandon_plan_payload(**overrides) -> dict:
    payload = {"abandonment_reason": "Partner deferred the move by a quarter."}
    payload.update(overrides)
    return payload


def create_introduction_payload(**overrides) -> dict:
    payload = {
        "target_client_name": "Northwind Holdings",
        "introducing_partner_name": "Marcus Reyes",
        "slot_start_at": "2026-10-05T09:00:00.000Z",
        "slot_end_at": "2026-10-05T10:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_performance_review_payload(integration_plan_id, **overrides) -> dict:
    payload = {
        "integration_plan_id": integration_plan_id,
        "period_start_date": "2027-01-04T00:00:00.000Z",
        "period_end_date": "2027-04-04T00:00:00.000Z",
        "variance_basis": "PLAN_BASIS",
        "realized_standard_rate_usd": 900.00,
    }
    payload.update(overrides)
    return payload
