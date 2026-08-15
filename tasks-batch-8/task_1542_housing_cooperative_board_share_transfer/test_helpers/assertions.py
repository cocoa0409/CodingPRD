"""Entity assertions and domain invariant checkers.

Each assert_* validates the fields the PRD guarantees on a resource: the
common system-managed properties of section 2.4 (id, created_at, updated_at,
version) plus the entity's own declared fields.
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD section 2.4: created_at / updated_at are "ISO 8601 UTC values rendered
# with three fractional digits".
_ISO8601_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def is_iso8601_millis(value: str) -> bool:
    """True when value is an ISO 8601 UTC timestamp with exactly 3 fractional digits."""
    return bool(_ISO8601_MILLIS_RE.match(value)) if isinstance(value, str) else False


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_cooperative(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["total_shares"], int) and data["total_shares"] >= 0
    assert isinstance(data["underlying_mortgage_principal_cents"], int)
    assert isinstance(data["underlying_mortgage_rate_bps"], int)
    assert data["flip_tax_policy"] in ("GROSS_PERCENT", "PER_SHARE")
    assert isinstance(data["flip_tax_percent_bps"], int)
    assert isinstance(data["flip_tax_per_share_cents"], int)
    assert isinstance(data["sublet_policy_years_max"], int)
    assert isinstance(data["sublet_policy_gap_years"], int)
    assert isinstance(data["arrears_late_fee_flat_cents"], int)
    assert isinstance(data["arrears_interest_rate_bps"], int)
    assert isinstance(data["arrears_grace_days"], int)
    assert isinstance(data["arrears_termination_threshold_cents"], int)
    assert isinstance(data["annual_meeting_quorum_percent_bps"], int)
    assert isinstance(data["current_utc"], str)


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["unit_label"], str) and len(data["unit_label"]) > 0
    assert isinstance(data["shares_allocated"], int) and data["shares_allocated"] > 0
    assert data["occupancy_status"] in ("OWNER_OCCUPIED", "SUBLET", "VACANT")
    assert data.get("last_sublet_end_date") is None or \
        isinstance(data["last_sublet_end_date"], str)


def assert_shareholder(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["standing"] in ("GOOD_STANDING", "DELINQUENT", "TERMINATED")
    assert isinstance(data["arrears_balance_cents"], int) and \
        data["arrears_balance_cents"] >= 0


def assert_share_ledger_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["shareholder_id"], str)
    assert isinstance(data["shares_held"], int) and data["shares_held"] > 0
    assert data["entry_status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["effective_at"], str)


def assert_charge_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["annual_operating_budget_cents"], int)
    assert data["allocation_method"] in ("PRO_RATA_SHARES", "EQUAL_SPLIT")
    assert data["schedule_status"] in ("DRAFT", "APPROVED", "SUPERSEDED")
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data.get("approving_resolution_id") is None or \
        isinstance(data["approving_resolution_id"], str)


def assert_maintenance_charge(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["schedule_id"], str)
    assert isinstance(data["billing_month"], str)
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["interest_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["charge_status"] in ("PENDING", "ISSUED", "PARTIALLY_PAID", "PAID",
                                     "PAST_DUE", "WAIVED")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["shareholder_id"], str)
    assert isinstance(data["charge_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["posted_at"], str)
    assert data["payment_status"] in ("POSTED", "VOIDED")


def assert_arrears_action(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["shareholder_id"], str)
    assert data["action_type"] in ("LATE_NOTICE", "DEMAND_LETTER", "TERMINATION_NOTICE")
    assert data["action_status"] in ("ISSUED", "CURED", "ESCALATED", "WITHDRAWN")
    assert isinstance(data["issued_at"], str)
    assert isinstance(data["cure_deadline"], str)
    assert isinstance(data["cure_amount_cents"], int)


def assert_purchase_application(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["seller_shareholder_id"], str)
    assert isinstance(data["buyer_full_name"], str) and len(data["buyer_full_name"]) > 0
    assert isinstance(data["buyer_email"], str) and len(data["buyer_email"]) > 0
    assert isinstance(data["gross_sale_price_cents"], int)
    assert isinstance(data["financing_percent_bps"], int)
    assert isinstance(data["debt_to_income_bps"], int)
    assert isinstance(data["post_closing_liquidity_cents"], int)
    assert data["application_status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "INTERVIEW_SCHEDULED",
        "APPROVED", "REJECTED", "WITHDRAWN", "TRANSFERRED")
    assert data.get("flip_tax_cents") is None or isinstance(data["flip_tax_cents"], int)
    assert data.get("submitted_at") is None or isinstance(data["submitted_at"], str)
    assert data.get("deciding_resolution_id") is None or \
        isinstance(data["deciding_resolution_id"], str)
    assert data.get("transferred_at") is None or isinstance(data["transferred_at"], str)


def assert_interview(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["scheduled_at"], str)
    assert isinstance(data["panel_member_user_ids"], list)
    assert data["interview_outcome"] in ("PENDING", "FAVORABLE", "UNFAVORABLE", "WAIVED")
    assert data["interview_status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data.get("completed_at") is None or isinstance(data["completed_at"], str)


def assert_resolution(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert data["resolution_kind"] in (
        "APPROVE_PURCHASE", "REJECT_PURCHASE", "APPROVE_SCHEDULE", "APPROVE_REFINANCE",
        "APPROVE_SUBLET", "APPROVE_ALTERATION", "ISSUE_ARREARS_ACTION", "SET_POLICY")
    assert data["subject_entity_kind"] in (
        "PurchaseApplication", "ChargeSchedule", "SubletAgreement",
        "AlterationAgreement", "Shareholder", "Cooperative")
    assert isinstance(data["subject_entity_id"], str)
    assert isinstance(data["payload_json"], dict)
    assert isinstance(data["votes_required"], int)
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)
    assert isinstance(data["votes_abstain"], int)
    assert data["resolution_status"] in ("OPEN", "PASSED", "FAILED", "WITHDRAWN")
    assert isinstance(data["opened_at"], str)
    assert data.get("closed_at") is None or isinstance(data["closed_at"], str)


def assert_resolution_vote(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["resolution_id"], str)
    assert isinstance(data["voter_user_id"], str)
    assert data["vote_choice"] in ("FOR", "AGAINST", "ABSTAIN")
    assert isinstance(data["cast_at"], str)


def assert_sublet_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["shareholder_id"], str)
    assert isinstance(data["subtenant_name"], str)
    assert isinstance(data["sublet_start_date"], str)
    assert isinstance(data["sublet_end_date"], str)
    assert data.get("monthly_sublet_fee_cents") is None or \
        isinstance(data["monthly_sublet_fee_cents"], int)
    assert data["sublet_status"] in ("DRAFT", "SUBMITTED", "APPROVED", "ACTIVE",
                                     "COMPLETED", "REJECTED", "TERMINATED_EARLY")


def assert_alteration_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["shareholder_id"], str)
    assert isinstance(data["scope_description"], str)
    assert isinstance(data["contractor_name"], str)
    assert isinstance(data["contractor_insurance_cents"], int)
    assert isinstance(data["work_window_start"], str)
    assert isinstance(data["work_window_end"], str)
    assert isinstance(data["contractor_bid_cents"], int)
    assert isinstance(data["involves_wet_over_dry"], bool)
    assert data.get("security_deposit_cents") is None or \
        isinstance(data["security_deposit_cents"], int)
    assert data["alteration_status"] in ("DRAFT", "SUBMITTED", "APPROVED", "IN_PROGRESS",
                                         "COMPLETED", "REJECTED", "ABANDONED")


def assert_meeting(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert data["meeting_kind"] in ("ANNUAL", "SPECIAL")
    assert isinstance(data["scheduled_at"], str)
    assert data["preparation_state"] in ("PREPARING", "NOTICE_SENT", "ADJOURNED")
    assert data["quorum_state"] in ("QUORUM_PENDING", "QUORUM_MET", "QUORUM_FAILED")
    assert isinstance(data["shares_represented"], int) and data["shares_represented"] >= 0
    assert data["meeting_status"] in ("SCHEDULED", "IN_SESSION", "ADJOURNED_NO_QUORUM",
                                      "COMPLETED")


def assert_ballot(data: dict):
    _assert_common(data)
    assert isinstance(data["cooperative_id"], str)
    assert isinstance(data["meeting_id"], str)
    assert isinstance(data["shareholder_id"], str)
    assert data["ballot_kind"] in ("IN_PERSON", "PROXY")
    assert isinstance(data["shares_voted"], int) and data["shares_voted"] >= 0
    assert isinstance(data["candidate_user_ids"], list)
    assert data["ballot_status"] in ("SUBMITTED", "COUNTED", "INVALIDATED")


def assert_charge_money_conservation(charge: dict):
    """PRD section 3.3: a charge's outstanding_cents is always the base plus
    late fee plus interest minus payments, never less than zero."""
    expected = (charge["base_amount_cents"] + charge["late_fee_cents"]
                + charge["interest_cents"] - charge["paid_cents"])
    assert charge["outstanding_cents"] == expected, (
        f"outstanding_cents {charge['outstanding_cents']} != base "
        f"{charge['base_amount_cents']} + late_fee {charge['late_fee_cents']} + "
        f"interest {charge['interest_cents']} - paid {charge['paid_cents']}")
    assert charge["outstanding_cents"] >= 0, "outstanding_cents never less than zero"


def assert_shares_conserved(cooperative: dict, active_entries: list):
    """PRD section 2.7 (INV-SHARES): total_shares must equal the sum of
    shares_allocated over units; the ACTIVE ledger entries reconcile exactly."""
    active_sum = sum(e["shares_held"] for e in active_entries
                     if e["entry_status"] == "ACTIVE")
    assert active_sum == cooperative["total_shares"], (
        f"ACTIVE ledger shares {active_sum} != total_shares "
        f"{cooperative['total_shares']}")
