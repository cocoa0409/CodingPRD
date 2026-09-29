"""Entity assertions and domain invariant checkers for the retransmission API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASIS_POINT_WHOLE,
    MAX_RATE_PER_SUB_CENTS,
    MAX_REVERSE_COMP_SPLIT_BP,
)


def assert_identity_fields(data: dict, versioned: bool = True):
    """Every resource is addressed by a server-minted UUID and carries created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    if versioned:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_station(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["call_sign"], str) and len(data["call_sign"]) == 4
    assert data["call_sign"].isupper()
    assert isinstance(data["market_code"], str) and len(data["market_code"]) == 3
    assert 1 <= data["dma_rank"] <= 210, "dma_rank must be between 1 and 210"
    assert data["market_tv_households"] >= 1
    assert data["network_affiliation"] in [
        "ABC",
        "CBS",
        "NBC",
        "FOX",
        "CW",
        "INDEPENDENT",
    ]
    assert isinstance(data["filed_election_count"], int)
    assert data["filed_election_count"] >= 0


def assert_affiliation_agreement(data: dict):
    assert_identity_fields(data)
    assert data["network_name"] in ["ABC", "CBS", "NBC", "FOX", "CW"]
    assert is_iso8601_timestamp(data["term_end_utc"])
    assert 0 <= data["reverse_comp_floor_per_sub_cents"] <= 400
    assert 0 <= data["split_premium_bp"] <= 2000
    assert isinstance(data["digital_rights_grantable"], bool)
    assert isinstance(data["ooh_rights_grantable"], bool)
    assert isinstance(data["streaming_rights_grantable"], bool)
    assert isinstance(data["permitted_tiers"], list) and data["permitted_tiers"]
    for tier in data["permitted_tiers"]:
        assert tier in ["BROADCAST_BASIC", "EXPANDED_BASIC", "DIGITAL_TIER"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "EXPIRED"]


def assert_distributor(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert data["distributor_type"] in ["CABLE", "DBS", "TELCO", "VMVPD"]
    assert data["subscriber_measurement_method"] in [
        "BILLED_HOUSEHOLDS",
        "WEIGHTED_STREAMING_DEVICES",
        "AVERAGE_MONTHLY_UNIQUE",
    ]
    assert data["video_household_count"] >= 1
    assert data["required_blackout_notice_days"] in [14, 30]
    assert data["open_true_up_count"] >= 0


def assert_carriage_election(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["distributor_id"])
    assert 1 <= len(data["cycle_label"]) <= 20
    assert data["election_type"] in ["MUST_CARRY", "RETRANS_CONSENT"]
    assert data["requested_tier"] in [
        "BROADCAST_BASIC",
        "EXPANDED_BASIC",
        "DIGITAL_TIER",
    ]
    assert is_iso8601_timestamp(data["incumbent_expiry_utc"])
    assert 0 <= data["incumbent_rate_per_sub_cents"] <= MAX_RATE_PER_SUB_CENTS
    assert data["status"] in [
        "DRAFT",
        "NEGOTIATING",
        "ELECTION_EFFECTIVE",
        "CONSENT_GRANTED",
        "ELECTION_LAPSED",
    ]


def assert_negotiation(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["election_id"])
    assert data["status"] in [
        "OPEN",
        "AWAITING_DISTRIBUTOR_RESPONSE",
        "AWAITING_STATION_OFFER",
        "IMPASSE",
        "CONSENTED",
        "CANCELLED",
    ]
    assert data["round_number"] >= 0
    assert data["station_offer_count"] >= 0
    assert data["distributor_offer_count"] >= 0
    assert data["good_faith_meeting_count"] >= 0
    assert (
        data["round_number"]
        == data["station_offer_count"] + data["distributor_offer_count"]
    ), "round_number counts the offers on the negotiation"
    assert data["notice_compliance_status"] in [
        "NOT_REQUIRED",
        "NOTICE_PENDING",
        "NOTICE_SERVED",
        "NOTICE_DEFICIENT",
    ]


def assert_offer(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["negotiation_id"])
    assert data["offered_by"] in ["STATION_GROUP", "DISTRIBUTOR"]
    assert data["round_number"] >= 1
    assert 1 <= data["base_rate_per_sub_cents"] <= MAX_RATE_PER_SUB_CENTS
    assert 0 <= data["escalator_bp_per_year"] <= 1000
    assert 12 <= data["term_months"] <= 120
    assert data["tier"] in ["BROADCAST_BASIC", "EXPANDED_BASIC", "DIGITAL_TIER"]
    assert 0 <= data["penetration_commitment_bp"] <= BASIS_POINT_WHOLE
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED", "EXPIRED"]
    assert isinstance(data["year_rate_schedule_compound_cents"], list)
    for rate in data["year_rate_schedule_compound_cents"]:
        assert isinstance(rate, int), "every ladder rate is an integer number of cents"
        assert rate <= MAX_RATE_PER_SUB_CENTS
    assert isinstance(data["projected_total_fee_cents"], int)


def assert_good_faith_log_entry(data: dict):
    """A good-faith entry carries only id and created_at; no updated_at, no version."""
    assert_identity_fields(data, versioned=False)
    assert "updated_at" not in data, "a good-faith entry carries no updated_at"
    assert "version" not in data, "a good-faith entry carries no version"
    assert data["event_type"] in [
        "MEETING_HELD",
        "PROPOSAL_EXCHANGED",
        "INFORMATION_REQUEST",
        "INFORMATION_RESPONSE",
        "DELAY_OBJECTION",
    ]
    assert is_iso8601_timestamp(data["occurred_at_utc"])
    assert 1 <= len(data["summary"]) <= 500
    assert data["actor_role"] in [
        "StationGroupNegotiator",
        "DistributorRep",
        "ComplianceOfficer",
    ]
    assert data["sequence_index"] >= 1, "sequence_index is a 1-based append position"


def assert_subscriber_report(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["distributor_id"])
    assert 1 <= len(data["period_label"]) <= 20
    assert is_iso8601_timestamp(data["period_start_utc"])
    assert is_iso8601_timestamp(data["period_end_utc"])
    assert data["reported_subscriber_count"] >= 0
    assert 0 <= data["excluded_free_trial_count"] <= data["reported_subscriber_count"]
    assert data["measurement_method_snapshot"] in [
        "BILLED_HOUSEHOLDS",
        "WEIGHTED_STREAMING_DEVICES",
        "AVERAGE_MONTHLY_UNIQUE",
    ]
    assert isinstance(data["audit_adjustment_subscribers"], int)
    assert data["billable_subscriber_basis"] >= 0, "the basis is floored at zero"
    assert data["as_reported_basis"] >= 0, "the basis is floored at zero"
    assert data["status"] in ["REPORTED", "UNDER_AUDIT", "ADJUSTED", "ACCEPTED"]


def assert_audit_finding(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["subscriber_report_id"])
    assert data["adjustment_subscribers"] != 0
    assert -500000 <= data["adjustment_subscribers"] <= 500000
    assert 1 <= len(data["basis_note"]) <= 500
    assert data["status"] in ["OPEN", "SUBSTANTIATED", "DISMISSED"]
    assert is_iso8601_timestamp(data["opened_at_utc"])


def assert_carriage_agreement(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["negotiation_id"])
    assert is_valid_uuid(data["accepted_offer_id"])
    assert is_iso8601_timestamp(data["effective_start_utc"])
    assert is_iso8601_timestamp(data["effective_end_utc"])
    assert data["execution_status"] in ["PENDING_EXECUTION", "EXECUTED", "EXPIRED"]
    assert data["network_approval_status"] in [
        "NOT_REQUIRED",
        "PENDING_NETWORK",
        "NETWORK_APPROVED",
        "NETWORK_REJECTED",
    ]
    assert isinstance(data["granted_rights_scope"], list)
    for term in data["granted_rights_scope"]:
        assert term in ["DIGITAL", "OUT_OF_HOME", "STREAMING"]
    assert data["rights_credit_bp_total"] >= 0
    assert isinstance(data["contract_year_rate_schedule_cents"], list)
    for rate in data["contract_year_rate_schedule_cents"]:
        assert isinstance(rate, int)
        assert rate <= MAX_RATE_PER_SUB_CENTS
    assert 0 <= data["consumed_extension_days"] <= 90
    assert isinstance(data["lifetime_gross_fee_cents"], int)
    assert isinstance(data["lifetime_net_retained_cents"], int)


def assert_interim_extension(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert 1 <= data["extension_days"] <= 90
    assert is_iso8601_timestamp(data["extension_start_utc"])
    assert is_iso8601_timestamp(data["extension_end_utc"])
    assert data["extension_rate_basis"] in [
        "PRIOR_RATE",
        "LAST_STATION_OFFER",
        "MIDPOINT",
    ]
    assert isinstance(data["effective_rate_per_sub_cents"], int)
    assert data["status"] in ["ACTIVE", "LAPSED", "SUPERSEDED"]


def assert_rights_dispute(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["disputed_term"] in ["DIGITAL", "OUT_OF_HOME", "STREAMING"]
    assert 1 <= len(data["claimed_definition"]) <= 500
    assert data["raised_by"] in ["STATION_GROUP", "DISTRIBUTOR"]
    assert data["status"] in [
        "RAISED",
        "IN_MEDIATION",
        "RESOLVED_INCLUDED",
        "RESOLVED_EXCLUDED",
    ]
    assert data["credit_bp_applied"] >= 0


def assert_blackout_notice(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["negotiation_id"])
    assert data["subscriber_notice_count"] >= 1
    assert data["notice_channel"] in [
        "ON_AIR_CRAWL",
        "BILL_INSERT",
        "EMAIL",
        "WEBSITE",
    ]
    assert is_iso8601_timestamp(data["served_at_utc"])
    assert data["required_notice_days_snapshot"] in [14, 30]
    assert data["status"] in ["SERVED", "SUPERSEDED"]


def assert_fee_settlement(data: dict):
    assert_identity_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["subscriber_report_id"])
    assert 1 <= len(data["period_label"]) <= 20
    assert data["contract_year_index"] >= 1
    assert isinstance(data["rate_per_sub_cents"], int)
    assert data["basis_variant"] in ["AS_REPORTED", "AUDITED"]
    assert data["billable_subscriber_basis_snapshot"] >= 0
    assert isinstance(data["gross_fee_cents"], int)
    assert isinstance(data["rights_credit_cents"], int)
    assert 0 <= data["reverse_comp_split_bp"] <= MAX_REVERSE_COMP_SPLIT_BP
    assert isinstance(data["reverse_comp_cents"], int)
    assert data["actual_penetration_bp"] >= 0
    assert data["penetration_shortfall_bp"] >= 0, "the shortfall is floored at zero"
    assert data["penetration_penalty_cents"] >= 0
    assert isinstance(data["net_retained_cents"], int)
    assert isinstance(data["true_up_required"], bool)
    assert data["status"] in ["ISSUED", "TRUED_UP", "VOIDED"]
    assert_settlement_conservation(data)


def assert_settlement_conservation(data: dict):
    """gross_fee_cents equals net + reverse comp + rights credit + penalty."""
    total = (
        data["net_retained_cents"]
        + data["reverse_comp_cents"]
        + data["rights_credit_cents"]
        + data["penetration_penalty_cents"]
    )
    assert data["gross_fee_cents"] == total, (
        "conservation invariant violated: gross_fee_cents "
        f"{data['gross_fee_cents']} != {total}"
    )
