"""Donation recording, void compensation, balance reconciliation, listing, and the
computed client summary roll-up."""
from test_helpers import (
    validate_success, validate_paginated,
    create_contribution_payload,
    assert_contribution,
    TEST_USERS,
)
from test_helpers.fixtures import intake_client

INTAKE = TEST_USERS["intake_coordinator_headers"]
CLERK = TEST_USERS["contribution_clerk_headers"]


# ---------------------------------------------------------------------------
# Compensating invariant: record then void conserves donation balance
# ---------------------------------------------------------------------------
def test_recording_contribution_increases_balance(api):
    """PRD §3.8: "A recorded donation is created in `RECORDED` status; recording it adds its
    `amount_cents` to the client's `donation_balance_cents` and increments the client's
    `version` by 1."

    Design: Difficulty/compensating_invariant/donation_balance_conserved_on_record_then_void
    """
    client = intake_client(api)
    contribution = validate_success(
        api.create_contribution(client["id"], create_contribution_payload(amount_cents=5000), CLERK), 201
    )
    assert_contribution(contribution)
    assert contribution["status"] == "RECORDED"
    refreshed = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert refreshed["donation_balance_cents"] == 5000


def test_voiding_contribution_returns_balance_to_zero(api):
    """PRD §3.8: "Voiding is allowed only from `RECORDED`; it moves the contribution
    `RECORDED → VOIDED`, subtracts its `amount_cents` back out of the client's
    `donation_balance_cents`, and increments the contribution's `version` and the client's
    `version` each by 1."

    Design: Difficulty/compensating_invariant/donation_balance_conserved_on_record_then_void
    """
    client = intake_client(api)
    contribution = validate_success(
        api.create_contribution(client["id"], create_contribution_payload(amount_cents=5000), CLERK), 201
    )
    voided = validate_success(api.void_contribution(contribution["id"], CLERK), 200)
    assert voided["status"] == "VOIDED"
    refreshed = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert refreshed["donation_balance_cents"] == 0, "void compensation returns balance to 0"


# ---------------------------------------------------------------------------
# Reconciliation across multiple contributions
# ---------------------------------------------------------------------------
def test_donation_balance_reconciles_across_contributions(api):
    """PRD §3.8: "The authoritative `donation_balance_cents` is always the reconciled sum of
    `amount_cents` over the client's contributions whose status is `RECORDED`; voided
    contributions are never counted."

    Design: Corner/cross_cutting_complexity_layers/donation_balance_reconciles_across_contributions
    """
    client = intake_client(api)
    c1 = validate_success(api.create_contribution(client["id"], create_contribution_payload(amount_cents=5000), CLERK), 201)
    validate_success(api.create_contribution(client["id"], create_contribution_payload(amount_cents=2500), CLERK), 201)
    before = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert before["donation_balance_cents"] == 7500, "5000 + 2500 both RECORDED"
    validate_success(api.void_contribution(c1["id"], CLERK), 200)
    after = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert after["donation_balance_cents"] == 2500, "only the remaining RECORDED 2500 counts"


# ---------------------------------------------------------------------------
# Listing / pagination
# ---------------------------------------------------------------------------
def test_contributions_list_pagination_meta(api):
    """PRD §2.3: "`total_count` reports the total number of records matching the query before
    paging, and `has_more` is a boolean that is true exactly when records remain beyond the
    current page."

    Design: Corner/entities/contributions_list_pagination
    """
    client = intake_client(api)
    validate_success(api.create_contribution(client["id"], create_contribution_payload(amount_cents=5000), CLERK), 201)
    validate_success(api.create_contribution(client["id"], create_contribution_payload(amount_cents=2500), CLERK), 201)
    data, meta = validate_paginated(api.list_contributions(CLERK, params={"client_id": client["id"], "limit": 1}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Computed client summary read
# ---------------------------------------------------------------------------
def test_client_summary_aggregates_donation_and_units(api):
    """PRD §3.1: "It reports the client's `income_tier`, `oaa_eligible` flag, current monthly
    `suggested_contribution_cents`, reconciled `donation_balance_cents`, the
    `provisioned_monthly_units` and `delivered_units` OAA figures, and the
    `lifetime_oaa_units` total."
    PRD §3.4: "If a client has no `ACTIVE` plan, the monthly `suggested_contribution_cents`
    is 0."

    Design: Corner/endpoints/client_summary_computed_read
    """
    client = intake_client(api)
    validate_success(api.create_contribution(client["id"], create_contribution_payload(amount_cents=5000), CLERK), 201)
    summary = validate_success(api.get_client_summary(client["id"], CLERK), 200)
    assert summary["donation_balance_cents"] == 5000
    assert summary["delivered_units"] == 0
    assert summary["provisioned_monthly_units"] == 0
