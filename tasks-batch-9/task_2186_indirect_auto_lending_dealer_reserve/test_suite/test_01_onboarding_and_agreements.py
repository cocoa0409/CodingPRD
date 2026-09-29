"""Dealer onboarding, the agreement chain, and the dealer lifecycle."""
from test_helpers import (
    ADMIN, ANALYST, ApiErrorId, CLOCK_START, api_client, assert_agreement,
    assert_dealer, countersign_agreement, dealer_status_action, decision_application,
    draft_agreement, is_iso8601_timestamp, make_dealer_principal_headers,
    onboard_dealer, read_application, read_dealer, set_clock, setup_program,
    submit_application, validate_error, validate_paginated, validate_success,
)


def test_dealer_onboarding_applies_declared_defaults(api):
    """PRD 3.1: "`program_code` names the rate-sheet program the dealership buys
    under and defaults to `PS-STANDARD` when omitted; it is the value matched
    against published rate sheets at decision time."
    PRD 3.1: "`funding_line_cents` sets the maximum aggregate unpaid principal the
    lender is willing to carry for this dealership at any one moment, must be zero
    or greater, and defaults to 50,000,000 cents"
    PRD 2.8: "A newly onboarded dealership is created with every counter and every
    derived amount at zero, `compliance_hold` false, `suspension_reason` null,
    `latest_scorecard_grade` null, `scorecard_stale` false, and `version` 1."

    Design: Corner/entities/dealer_creation_applies_declared_defaults_and_system_fields
    """
    set_clock(CLOCK_START)
    response = api.create_dealer(
        {"legal_name": "Basin Auto Group", "state_code": "AZ"}, ADMIN
    )
    dealer = validate_success(response, 201)
    assert_dealer(dealer)

    assert dealer["program_code"] == "PS-STANDARD"
    assert dealer["funding_line_cents"] == 50_000_000
    assert dealer["status"] == "PROSPECT"
    assert dealer["compliance_hold"] is False
    assert dealer["version"] == 1
    assert dealer["reserve_balance_cents"] == 0
    assert dealer["outstanding_principal_cents"] == 0
    assert dealer["funded_contract_count"] == 0
    assert dealer["total_funded_ever_count"] == 0
    assert dealer["early_payoff_count"] == 0
    assert dealer["default_count"] == 0
    assert dealer["repurchase_count"] == 0
    assert dealer["chargeback_count"] == 0
    assert dealer["early_payoff_rate_bps"] == 0
    assert dealer["latest_scorecard_grade"] is None
    assert dealer["suspension_reason"] is None
    assert dealer["scorecard_stale"] is False

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_dealer_read_returns_the_stored_row(api):
    """PRD 3.1: "The onboarding payload names the store's `legal_name` — between 1
    and 120 characters, and not blank — and its `state_code`, exactly two uppercase
    letters identifying the US state where the dealership is licensed."
    PRD 2.4: "Every resource also carries a `created_at` timestamp, an ISO 8601 UTC
    string with three fractional digits, stamped at insertion and never changed."

    Design: Corner/entities/dealer_get_by_id_returns_stored_entity
    """
    set_clock(CLOCK_START)
    created = onboard_dealer(legal_name="Basin Auto Group", state_code="AZ")

    response = api.get_dealer(created["id"], ANALYST)
    dealer = validate_success(response, 200)

    assert response.json()["response_type"] == "object"
    assert dealer["id"] == created["id"]
    assert dealer["legal_name"] == "Basin Auto Group"
    assert dealer["state_code"] == "AZ"
    assert is_iso8601_timestamp(dealer["created_at"])
    assert dealer["created_at"] == created["created_at"]


def test_unknown_dealer_id_returns_dealer_not_found(api):
    """PRD 2.7: "Each entity type has its own not-found code:
    `ERR_DEALER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_RATE_SHEET_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BUYBACK_NOT_FOUND`, `ERR_SCORECARD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, and
    `ERR_RESERVE_ENTRY_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/dealer_get_unknown_id_not_found_returns_404
    """
    set_clock(CLOCK_START)
    response = api.get_dealer("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)

    error = validate_error(response, ApiErrorId.ERR_DEALER_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_countersigning_an_active_agreement_is_rejected(api):
    """PRD 3.1: "The agreement must genuinely be in `PENDING_COUNTERSIGN` —
    countersigning one that is already `ACTIVE`, `SUPERSEDED`, or `TERMINATED` is
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/countersign_twice_second_call_returns_invalid_state
    """
    program = setup_program()
    version_before = read_dealer(program["dealer_id"])["version"]
    countersigned_at_before = program["agreement"]["countersigned_at"]

    response = api.countersign_agreement(
        program["agreement"]["id"], {"signer_name": "R. Ridge"},
        make_dealer_principal_headers(program["dealer_id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    agreement = validate_success(
        api.get_agreement(program["agreement"]["id"], ADMIN), 200
    )
    assert agreement["status"] == "ACTIVE"
    assert agreement["countersigned_at"] == countersigned_at_before
    assert read_dealer(program["dealer_id"])["version"] == version_before


def test_terminated_dealer_refuses_further_lifecycle_actions(api):
    """PRD 3.9: "`REINSTATE` is permitted only from `SUSPENDED`, and it is gated
    twice: the dealership's `compliance_hold` must be false, and no fair-lending
    review of this dealership may remain in `REMEDIATION_ORDERED`."
    PRD 3.9: "the dealership advances to `TERMINATED`, which is terminal and from
    which nothing returns"

    Design: Corner/state_machines/terminated_dealer_rejects_further_status_actions
    """
    program = setup_program()
    dealer_status_action(program["dealer_id"], "TERMINATE", "PROGRAM_EXIT")

    response = api.dealer_status_action(
        program["dealer_id"], {"action": "REINSTATE", "reason": "APPEAL"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert read_dealer(program["dealer_id"])["status"] == "TERMINATED"


def test_reinstatement_restores_the_held_application_status(api):
    """PRD 3.9: "every application of the dealership in `SUBMITTED`, `CONDITIONED`,
    `RESUBMITTED`, or `APPROVED` captures its current status into `held_from_status`
    and moves to `ON_HOLD`, and `Dealer.version` advances by one."
    PRD 3.9: "the dealership advances `SUSPENDED → ACTIVE`, `suspension_reason` is
    cleared to null, and every application in `ON_HOLD` is restored to whichever of
    `SUBMITTED`, `CONDITIONED`, `RESUBMITTED`, or `APPROVED` its `held_from_status`
    recorded, with `held_from_status` then cleared to null."

    Design: Corner/state_machines/dealer_reinstatement_restores_held_application_status
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-rh",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )
    decision_application(
        application["id"], "CONDITION", stipulation_count=1,
        decision_note="PROOF_OF_INCOME",
    )

    dealer_status_action(program["dealer_id"], "SUSPEND", "AUDIT")
    dealer = read_dealer(program["dealer_id"])
    assert dealer["status"] == "SUSPENDED"
    assert dealer["suspension_reason"] == "AUDIT"
    held = read_application(application["id"])
    assert held["status"] == "ON_HOLD"
    assert held["held_from_status"] == "CONDITIONED"

    dealer_status_action(program["dealer_id"], "REINSTATE", "AUDIT_CLEARED")
    dealer = read_dealer(program["dealer_id"])
    assert dealer["status"] == "ACTIVE"
    assert dealer["suspension_reason"] is None
    restored = read_application(application["id"])
    assert restored["status"] == "CONDITIONED"
    assert restored["held_from_status"] is None


def test_successor_agreement_touching_the_incumbent_end_is_rejected(api):
    """PRD 3.1: "the draft must respect a mandatory notice buffer of 30 days against
    every existing agreement of the same dealership whose status is
    `PENDING_COUNTERSIGN` or `ACTIVE`: the new agreement's `effective_from` must be
    at or after that existing agreement's `effective_to` plus 30 days."
    PRD 3.1: "Windows that merely touch — a new agreement starting on the day the
    incumbent ends — are **rejected**, because the buffer is mandatory rather than a
    mere non-overlap requirement."

    Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_notice_buffer_adjacency_rejected
    """
    program = setup_program()
    version_before = read_dealer(program["dealer_id"])["version"]

    response = api.create_agreement(
        {
            "dealer_id": program["dealer_id"],
            "participation_method": "RATE_PARTICIPATION",
            "max_participation_bps": 150,
            "chargeback_window_days": 360,
            "effective_from": "2027-02-01T00:00:00Z",
            "effective_to": "2028-02-01T00:00:00Z",
            "expected_dealer_version": version_before,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_WINDOW_CONFLICT.value, 409)

    assert read_dealer(program["dealer_id"])["version"] == version_before, (
        "the rejected draft must not advance Dealer.version"
    )
    agreements, meta = validate_paginated(
        api.list_agreements(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 1


def test_successor_agreement_beyond_the_notice_buffer_is_accepted(api):
    """PRD 3.1: "the new agreement's `effective_from` must be at or after that
    existing agreement's `effective_to` plus 30 days."
    PRD 3.1: "A freshly drafted agreement sits in `PENDING_COUNTERSIGN` with
    `countersigned_at` and `signer_name` both null."

    Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_notice_buffer_adjacency_rejected
    """
    program = setup_program()
    version_before = read_dealer(program["dealer_id"])["version"]

    response = api.create_agreement(
        {
            "dealer_id": program["dealer_id"],
            "participation_method": "RATE_PARTICIPATION",
            "max_participation_bps": 150,
            "chargeback_window_days": 360,
            "effective_from": "2027-03-05T00:00:00Z",
            "effective_to": "2028-03-05T00:00:00Z",
            "expected_dealer_version": version_before,
        },
        ADMIN,
    )
    successor = validate_success(response, 201)
    assert_agreement(successor)
    assert successor["status"] == "PENDING_COUNTERSIGN"
    assert successor["countersigned_at"] is None
    assert successor["signer_name"] is None

    agreements, meta = validate_paginated(
        api.list_agreements(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 2
    incumbent = validate_success(
        api.get_agreement(program["agreement"]["id"], ADMIN), 200
    )
    assert incumbent["status"] == "ACTIVE", (
        "an accepted successor does not supersede until it is countersigned"
    )


def test_second_agreement_draft_from_a_stale_dealer_version_is_rejected(api):
    """PRD 2.6: "Drafting a dealer agreement (`POST /lending/dealer-agreements`)
    requires a non-optional `expected_dealer_version` field in the request body,
    carrying the `version` value the client last observed on that `Dealer`. If it
    does not equal the dealership's current `version`, the request is rejected with
    `ERR_STALE_DEALER_VERSION` (HTTP 412)."
    PRD 3.1: "drafting an agreement itself advances `Dealer.version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_dealer_version_rejects_second_agreement_create
    """
    program = setup_program()
    observed_version = read_dealer(program["dealer_id"])["version"]

    first = validate_success(
        api.create_agreement(
            {
                "dealer_id": program["dealer_id"],
                "participation_method": "RATE_PARTICIPATION",
                "max_participation_bps": 150,
                "chargeback_window_days": 360,
                "effective_from": "2027-03-05T00:00:00Z",
                "effective_to": "2028-03-05T00:00:00Z",
                "expected_dealer_version": observed_version,
            },
            ADMIN,
        ),
        201,
    )
    assert first["status"] == "PENDING_COUNTERSIGN"

    stale_payload = {
        "dealer_id": program["dealer_id"],
        "participation_method": "RATE_PARTICIPATION",
        "max_participation_bps": 150,
        "chargeback_window_days": 360,
        "effective_from": "2028-04-10T00:00:00Z",
        "effective_to": "2029-04-10T00:00:00Z",
        "expected_dealer_version": observed_version,
    }
    validate_error(
        api.create_agreement(stale_payload, ADMIN),
        ApiErrorId.ERR_STALE_DEALER_VERSION.value, 412,
    )

    _, meta = validate_paginated(
        api.list_agreements(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 2

    stale_payload["expected_dealer_version"] = read_dealer(program["dealer_id"])["version"]
    retried = validate_success(api.create_agreement(stale_payload, ADMIN), 201)
    assert retried["status"] == "PENDING_COUNTERSIGN"
