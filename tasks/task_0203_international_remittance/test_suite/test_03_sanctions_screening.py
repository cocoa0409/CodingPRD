"""Sanctions screening: scoring, the clear/hold threshold, hit creation, and the
compliance-case escalation guard.

The strict-vs-base name-matching divergence (Difficulty
dual_variant_calc/sanctions_score_strict_vs_base_variant_diverges) is NOT
translated: the PRD describes a "high-risk country list" that selects the strict
variant but never enumerates it, so a PRD-only implementer cannot derive that any
particular country (e.g. RU) is high-risk, and the asserted strict-only score of
100 is not uniquely derivable. The inputs used in the tests below score
identically under both variants (zero token overlap, or exact equality, or a
half-match with no extra prefix-containment), so they remain uniquely derivable.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_corridor, setup_sender, setup_recipient, add_sanctions_entry,
    setup_funded_transfer, setup_held_transfer_with_case,
    create_locked_quote, create_transfer_from_quote,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── empty sanctions list -> score 0 -> auto-CLEAR (boundary precision) ─────

def test_empty_sanctions_list_screens_to_zero_and_clears(api):
    """PRD §3.5: "The transfer's `sanctions_score` is the maximum pairwise score over
    every (party, list entry) pair, or 0 when there are no list entries."
    PRD §3.5: "a score strictly below 60 auto-clears the transfer, moving
    `compliance_status` from `SCREENING` to `CLEARED` with no case opened."

    Design: Difficulty/boundary_precision_check/empty_sanctions_list_yields_zero_score_auto_clear
    """
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=50000, recipient_verified=False)
    screened = validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    assert screened["sanctions_score"] == 0, screened["sanctions_score"]
    assert screened["compliance_status"] == "CLEARED", screened["compliance_status"]


def test_empty_sanctions_list_opens_no_case(api):
    """PRD §3.5: "a score strictly below 60 auto-clears the transfer, moving
    `compliance_status` from `SCREENING` to `CLEARED` with no case opened."

    Design: Difficulty/boundary_precision_check/empty_sanctions_list_yields_zero_score_auto_clear
    """
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=50000, recipient_verified=False)
    validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    data, meta = validate_paginated(
        api.list_compliance_cases(OFFICER, params={"transfer_id": transfer["id"]}))
    assert meta["total_count"] == 0, meta["total_count"]


# ─── parallel state axes (non-linear state machine) ─────────────────────────

def test_screen_clears_compliance_axis_without_touching_delivery(api):
    """PRD §3.5: "a score strictly below 60 auto-clears the transfer, moving
    `compliance_status` from `SCREENING` to `CLEARED` with no case opened."

    Design: Difficulty/non_linear_state_machine/transfer_parallel_axes_compliance_and_delivery_independent
    """
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=50000, recipient_verified=True)
    screened = validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    assert screened["compliance_status"] == "CLEARED", screened["compliance_status"]
    # The delivery axis is untouched by screening.
    assert screened["delivery_status"] == "PENDING", screened["delivery_status"]
    assert screened["sanctions_score"] == 0, screened["sanctions_score"]


def test_dispatch_advances_delivery_axis_without_touching_compliance(api):
    """PRD §3.6: "A dispatch from `delivery_status` of `PENDING` creates a
    `PayoutAttempt` and moves the transfer to `IN_TRANSIT`."

    Design: Difficulty/non_linear_state_machine/transfer_parallel_axes_compliance_and_delivery_independent
    """
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=50000, recipient_verified=True)
    validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    dispatched = validate_success(
        api.dispatch_transfer(transfer["id"], TEST_USERS["payout_operator_headers"]), 200)
    assert dispatched["delivery_status"] == "IN_TRANSIT", dispatched["delivery_status"]
    # Compliance axis remains CLEARED — the two axes evolve independently.
    assert dispatched["compliance_status"] == "CLEARED", dispatched["compliance_status"]


# ─── partial name match below threshold (corner: calculations) ──────────────

def test_country_only_match_scores_30_and_clears(api):
    """PRD §3.5: "The country component contributes the entry's `weight_country_bps`
    divided by 100 when the party's `country` equals the entry's `listed_country`, and
    zero otherwise."
    PRD §3.5: "a score strictly below 60 auto-clears the transfer, moving
    `compliance_status` from `SCREENING` to `CLEARED` with no case opened."

    Design: Corner/calculations/sanctions_partial_name_match_scores_below_threshold_clears
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    add_sanctions_entry("Ivan Petrov", "PH")
    sender = setup_sender(kyc_tier="TIER1")
    # "Maria Cruz" shares no name tokens (and no token prefix) with "Ivan Petrov";
    # name = 0 under both variants, country PH==PH = 30 -> total 30 < 60.
    recipient = setup_recipient(sender["id"], full_name="Maria Cruz", country="PH")
    quote = create_locked_quote(corridor["id"], sender["id"], 50000)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    validate_success(api.fund_transfer(transfer["id"], AGENT), 200)
    screened = validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    assert screened["sanctions_score"] == 30, screened["sanctions_score"]
    assert screened["compliance_status"] == "CLEARED", screened["compliance_status"]


# ─── HELD path creates a hit discoverable by transfer (corner: cross-cutting)

def test_held_screen_creates_sanctions_hit_for_recipient(api):
    """PRD §3.5: "the system writes a `SanctionsHit` row for every (subject, list
    entry) pair whose pairwise score is at or above 60 ... The full hit set for a
    transfer is discoverable by listing sanctions hits filtered by `transfer_id`."

    Design: Corner/cross_cutting_complexity_layers/sanctions_hit_reverse_lookup_by_transfer
    """
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        listed_name="Ivan Petrov", listed_country="PH",
        recipient_name="Ivan Petrov", recipient_country="PH")
    # Exact name match (70) + country PH (30) = 100 on the RECIPIENT subject.
    data, meta = validate_paginated(
        api.list_sanctions_hits(OFFICER, params={"transfer_id": transfer["id"]}))
    assert len(data) >= 1, "expected at least one sanctions hit"
    recipient_hits = [h for h in data if h["subject_kind"] == "RECIPIENT"]
    assert recipient_hits, "expected a RECIPIENT-subject hit"
    assert any(h["score"] == 100 for h in recipient_hits), [h["score"] for h in recipient_hits]


# ─── escalation guard below threshold (corner: validations) ─────────────────

def test_escalate_below_escalation_threshold_rejected(api):
    """PRD §3.5: "From `OPEN`, an officer may also escalate the case to `ESCALATED`,
    but only when the transfer's `sanctions_score` is at or above the escalation
    threshold of 85; an escalation attempted below that score is rejected with
    `ERR_ESCALATION_NOT_WARRANTED`."

    Design: Corner/validations/escalate_below_threshold_returns_not_warranted
    """
    # "Ivan Reyes" PH vs listed "Ivan Petrov" PH: overlap {ivan}=1 of 2 listed tokens
    # -> name ratio 0.5 -> name points round_half_up(0.5*7000/100)=35; country 30 -> 65.
    # 65 >= 60 -> HELD; 65 < 85 -> escalation not warranted.
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        listed_name="Ivan Petrov", listed_country="PH",
        recipient_name="Ivan Reyes", recipient_country="PH")
    assert transfer["sanctions_score"] == 65, transfer["sanctions_score"]
    res = api.escalate_compliance_case(case["id"], OFFICER)
    validate_error(res, "ERR_ESCALATION_NOT_WARRANTED")
    after = validate_success(api.get_compliance_case(case["id"], OFFICER), 200)
    assert after["status"] == "OPEN", after["status"]
