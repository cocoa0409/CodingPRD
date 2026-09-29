"""Payload factories — one per created resource, client-supplied fields only.

Every monetary amount is an integer number of whole cents and every proportion
is an integer number of basis points; nothing here is ever a decimal string.
"""

DEFAULTS = {
    "CALL_SIGN": "WXYZ",
    "MARKET_CODE": "SEA",
    "DMA_RANK": 12,
    "MARKET_TV_HOUSEHOLDS": 1800000,
    "NETWORK_AFFILIATION": "CBS",
    "AFFILIATION_TERM_END_UTC": "2032-01-01T00:00:00Z",
    "REVERSE_COMP_FLOOR_PER_SUB_CENTS": 90,
    "SPLIT_PREMIUM_BP": 500,
    "DISTRIBUTOR_NAME": "Cascade Cable",
    "DISTRIBUTOR_TYPE": "CABLE",
    "SUBSCRIBER_MEASUREMENT_METHOD": "BILLED_HOUSEHOLDS",
    "VIDEO_HOUSEHOLD_COUNT": 240000,
    "CYCLE_LABEL": "2027-2029",
    "ELECTION_TYPE": "RETRANS_CONSENT",
    "REQUESTED_TIER": "EXPANDED_BASIC",
    "INCUMBENT_EXPIRY_UTC": "2027-01-01T00:00:00Z",
    "INCUMBENT_RATE_PER_SUB_CENTS": 220,
    "PERIOD_LABEL": "2027-01",
    "PERIOD_START_UTC": "2027-01-01T00:00:00Z",
    "PERIOD_END_UTC": "2027-02-01T00:00:00Z",
    "REPORTED_SUBSCRIBER_COUNT": 100000,
    "EXCLUDED_FREE_TRIAL_COUNT": 0,
    "BASE_RATE_PER_SUB_CENTS": 250,
    "ESCALATOR_BP_PER_YEAR": 700,
    "TERM_MONTHS": 36,
    "TIER": "EXPANDED_BASIC",
    "PENETRATION_COMMITMENT_BP": 4200,
    "EFFECTIVE_START_UTC": "2027-01-01T00:00:00Z",
    "EFFECTIVE_END_UTC": "2030-01-01T00:00:00Z",
    "EXTENSION_DAYS": 60,
    "EXTENSION_START_UTC": "2030-01-01T00:00:00Z",
    "EXTENSION_RATE_BASIS": "PRIOR_RATE",
}


def create_station_payload(**overrides) -> dict:
    payload = {
        "call_sign": DEFAULTS["CALL_SIGN"],
        "market_code": DEFAULTS["MARKET_CODE"],
        "dma_rank": DEFAULTS["DMA_RANK"],
        "market_tv_households": DEFAULTS["MARKET_TV_HOUSEHOLDS"],
        "network_affiliation": DEFAULTS["NETWORK_AFFILIATION"],
    }
    payload.update(overrides)
    return payload


def create_affiliation_agreement_payload(**overrides) -> dict:
    payload = {
        "network_name": DEFAULTS["NETWORK_AFFILIATION"],
        "term_end_utc": DEFAULTS["AFFILIATION_TERM_END_UTC"],
        "reverse_comp_floor_per_sub_cents": DEFAULTS[
            "REVERSE_COMP_FLOOR_PER_SUB_CENTS"
        ],
        "split_premium_bp": DEFAULTS["SPLIT_PREMIUM_BP"],
        "permitted_tiers": ["BROADCAST_BASIC", "EXPANDED_BASIC"],
        "digital_rights_grantable": True,
        "ooh_rights_grantable": False,
        "streaming_rights_grantable": True,
    }
    payload.update(overrides)
    return payload


def create_distributor_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DISTRIBUTOR_NAME"],
        "distributor_type": DEFAULTS["DISTRIBUTOR_TYPE"],
        "subscriber_measurement_method": DEFAULTS["SUBSCRIBER_MEASUREMENT_METHOD"],
        "video_household_count": DEFAULTS["VIDEO_HOUSEHOLD_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_election_payload(station_id: str, distributor_id: str, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "distributor_id": distributor_id,
        "cycle_label": DEFAULTS["CYCLE_LABEL"],
        "election_type": DEFAULTS["ELECTION_TYPE"],
        "requested_tier": DEFAULTS["REQUESTED_TIER"],
        "incumbent_expiry_utc": DEFAULTS["INCUMBENT_EXPIRY_UTC"],
        "incumbent_rate_per_sub_cents": DEFAULTS["INCUMBENT_RATE_PER_SUB_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_subscriber_report_payload(station_id: str, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "period_label": DEFAULTS["PERIOD_LABEL"],
        "period_start_utc": DEFAULTS["PERIOD_START_UTC"],
        "period_end_utc": DEFAULTS["PERIOD_END_UTC"],
        "reported_subscriber_count": DEFAULTS["REPORTED_SUBSCRIBER_COUNT"],
        "excluded_free_trial_count": DEFAULTS["EXCLUDED_FREE_TRIAL_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_offer_payload(subscriber_report_id: str, **overrides) -> dict:
    payload = {
        "subscriber_report_id": subscriber_report_id,
        "base_rate_per_sub_cents": DEFAULTS["BASE_RATE_PER_SUB_CENTS"],
        "escalator_bp_per_year": DEFAULTS["ESCALATOR_BP_PER_YEAR"],
        "term_months": DEFAULTS["TERM_MONTHS"],
        "tier": DEFAULTS["TIER"],
        "penetration_commitment_bp": DEFAULTS["PENETRATION_COMMITMENT_BP"],
        "includes_digital_rights": True,
        "includes_ooh_rights": False,
        "includes_streaming_rights": True,
    }
    payload.update(overrides)
    return payload


def accept_offer_payload(expected_negotiation_version: int, **overrides) -> dict:
    payload = {
        "expected_negotiation_version": expected_negotiation_version,
        "effective_start_utc": DEFAULTS["EFFECTIVE_START_UTC"],
        "effective_end_utc": DEFAULTS["EFFECTIVE_END_UTC"],
    }
    payload.update(overrides)
    return payload


def reject_offer_payload(**overrides) -> dict:
    payload = {"rejection_reason": "Rate is above what the market will bear"}
    payload.update(overrides)
    return payload


def create_audit_finding_payload(**overrides) -> dict:
    payload = {
        "adjustment_subscribers": 6000,
        "basis_note": "Bulk-billed MDU accounts omitted",
    }
    payload.update(overrides)
    return payload


def resolve_audit_finding_payload(resolution: str = "SUBSTANTIATED", **overrides) -> dict:
    payload = {
        "resolution": resolution,
        "resolution_note": "Sampling confirms the omission",
    }
    payload.update(overrides)
    return payload


def create_good_faith_log_payload(**overrides) -> dict:
    payload = {
        "event_type": "MEETING_HELD",
        "occurred_at_utc": "2026-08-01T00:00:00Z",
        "summary": "Parties met to exchange rate positions",
    }
    payload.update(overrides)
    return payload


def declare_impasse_payload(**overrides) -> dict:
    payload = {"impasse_statement": "Positions are irreconcilable on rate and term"}
    payload.update(overrides)
    return payload


def create_blackout_notice_payload(**overrides) -> dict:
    payload = {
        "subscriber_notice_count": 240000,
        "notice_channel": "ON_AIR_CRAWL",
    }
    payload.update(overrides)
    return payload


def network_approval_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {
        "decision": decision,
        "decision_note": "Rights scope within affiliation grant",
    }
    payload.update(overrides)
    return payload


def execute_agreement_payload(**overrides) -> dict:
    payload = {"execution_note": "Countersigned by second counsel"}
    payload.update(overrides)
    return payload


def create_interim_extension_payload(expected_agreement_version: int, **overrides) -> dict:
    payload = {
        "expected_agreement_version": expected_agreement_version,
        "extension_days": DEFAULTS["EXTENSION_DAYS"],
        "extension_start_utc": DEFAULTS["EXTENSION_START_UTC"],
        "extension_rate_basis": DEFAULTS["EXTENSION_RATE_BASIS"],
    }
    payload.update(overrides)
    return payload


def create_rights_dispute_payload(disputed_term: str = "STREAMING", **overrides) -> dict:
    payload = {
        "disputed_term": disputed_term,
        "claimed_definition": "Streaming means in-market authenticated app delivery only",
    }
    payload.update(overrides)
    return payload


def resolve_rights_dispute_payload(resolution: str = "EXCLUDED", **overrides) -> dict:
    payload = {
        "resolution": resolution,
        "resolution_note": "The claimed definition is outside the grant",
    }
    payload.update(overrides)
    return payload


def create_fee_settlement_payload(subscriber_report_id: str, **overrides) -> dict:
    payload = {
        "period_label": DEFAULTS["PERIOD_LABEL"],
        "period_start_utc": DEFAULTS["PERIOD_START_UTC"],
        "period_end_utc": DEFAULTS["PERIOD_END_UTC"],
        "subscriber_report_id": subscriber_report_id,
    }
    payload.update(overrides)
    return payload


def true_up_payload(**overrides) -> dict:
    payload = {"true_up_note": "Re-settled against the audited basis"}
    payload.update(overrides)
    return payload


def void_settlement_payload(**overrides) -> dict:
    payload = {"void_reason": "Issued against the wrong period"}
    payload.update(overrides)
    return payload


def withdraw_election_payload(**overrides) -> dict:
    payload = {
        "withdrawal_reason": "Station group elects must-carry in this market instead"
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
