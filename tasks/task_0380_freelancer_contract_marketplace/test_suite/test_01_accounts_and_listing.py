"""Account creation, defaults, listing, immutability, FK integrity, RBAC, and error wiring.

Translates queue B (Corner) instances from sections: entities, errors, rbac, endpoints
(deposit). Each test cites the verbatim PRD sentence that fixes the asserted behavior.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_client_payload, create_freelancer_payload, create_job_posting_payload,
    create_proposal_payload, deposit_payload,
    assert_client, assert_freelancer, assert_escrow_transaction,
    make_client_headers, make_freelancer_headers, make_admin_headers,
    create_client, create_freelancer, setup_funded_milestone,
)


def test_create_client_returns_201_with_defaults(api):
    """PRD §3.1: "Creating a Client takes a display_name and an email that is unique
    among clients; the new client opens with status of ACTIVE and a wallet_balance_cents
    of zero."
    PRD §2.4: "The version field is an integer that begins at its initial value and
    increments by one on every modification to the resource".

    Design: Corner/entities/create_client_returns_201_with_defaults
    """
    res = api.create_client(create_client_payload(display_name="Acme Co"), make_admin_headers())
    client = validate_success(res, 201)
    assert_client(client)
    assert client["status"] == "ACTIVE"
    assert client["wallet_balance_cents"] == 0
    assert client["escrow_held_cents"] == 0
    assert client["version"] == 1


def test_create_freelancer_default_tax_id_false(api):
    """PRD §3.1: "an optional tax_id_on_file flag indicating whether a W-9 or TIN is on
    record; when omitted the flag defaults to false. A new freelancer opens ACTIVE with
    every lifetime field at zero and a reputation_score of zero."

    Design: Corner/entities/create_freelancer_default_tax_id_false
    """
    res = api.create_freelancer(
        create_freelancer_payload(display_name="Solo", skills=["x"]), make_admin_headers())
    freelancer = validate_success(res, 201)
    assert_freelancer(freelancer)
    assert freelancer["tax_id_on_file"] is False
    assert freelancer["reputation_score"] == 0.0
    assert freelancer["fee_tier"] == "TIER_A"
    assert freelancer["lifetime_earnings_cents"] == 0


def test_get_freelancer_not_found(api):
    """PRD §2.5: "Each entity has its own not-found code in this family:
    ERR_CLIENT_NOT_FOUND, ERR_FREELANCER_NOT_FOUND, ERR_JOB_POSTING_NOT_FOUND".

    Design: Corner/entities/get_freelancer_not_found
    """
    res = api.get_freelancer(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(res, "ERR_FREELANCER_NOT_FOUND", expected_status=404)


def test_create_job_posting_missing_required_field(api):
    """PRD §2.6: "fourth, structural request validity — required fields present and
    well-typed, enums in range, ratings within one through five, and amounts and minute
    values within their declared bounds (ERR_INVALID_REQUEST)."
    PRD §3.2: "a billing_type of either FIXED or HOURLY that pins how every contract
    under the posting will bill".

    Design: Corner/entities/create_job_posting_missing_required_field
    """
    client = create_client()
    ch = make_client_headers(client["id"])
    payload = create_job_posting_payload(client["id"])
    del payload["billing_type"]
    res = api.create_job_posting(payload, ch)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_computed_fee_tier_ignores_client_input(api):
    """PRD §3.1: "A freelancer's fee_tier is one of TIER_A, TIER_B, or TIER_C and is
    derived from cumulative earnings as the fee workflow in §3.6 explains."
    PRD §3.6: "if those pre-payout lifetime earnings are below fifty thousand dollars —
    five million cents — the base rate is twenty percent, which is TIER_A".

    Design: Corner/entities/computed_fee_tier_ignores_client_input
    """
    freelancer = create_freelancer(skills=["x"])
    res = api.get_freelancer(freelancer["id"], make_admin_headers())
    fetched = validate_success(res, 200)
    assert fetched["lifetime_earnings_cents"] == 0
    assert fetched["fee_tier"] == "TIER_A"


def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "Every list-based response carries the pagination bookkeeping in the meta
    object of the envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_clients_pagination_envelope
    """
    create_client()
    create_client()
    res = api.list_clients(make_admin_headers())
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert meta["total_count"] >= 2
    assert isinstance(meta["has_more"], bool)


def test_immutable_escrow_transaction_no_version(api):
    """PRD §2.4: "An EscrowTransaction is an append-only ledger row: it carries only id
    and created_at and has neither an updated_at nor a version, because ledger rows are
    never modified after insertion."
    PRD §3.5: "writes a FUND EscrowTransaction in HELD status setting the milestone's
    funded_cents to amount_cents".

    Design: Corner/entities/immutable_escrow_transaction_no_version
    """
    ctx, milestone = setup_funded_milestone(amount_cents=20000)
    res = api.list_milestone_escrow(milestone["id"], make_admin_headers())
    data, _ = validate_paginated(res)
    funds = [row for row in data if row["txn_type"] == "FUND"]
    assert len(funds) == 1
    row = funds[0]
    assert_escrow_transaction(row)
    assert row["status"] == "HELD"
    assert row["amount_cents"] == 20000
    assert "version" not in row
    assert "updated_at" not in row


def test_fk_integrity_proposal_bad_freelancer(api):
    """PRD §2.5: "Identifiers passed in the request body are resolved the same way and in
    the same parent-before-child order."
    PRD §2.5: "ERR_FREELANCER_NOT_FOUND" is the freelancer not-found code.

    Design: Corner/entities/fk_integrity_proposal_bad_freelancer
    """
    client = create_client()
    ch = make_client_headers(client["id"])
    posting = validate_success(
        api.create_job_posting(create_job_posting_payload(client["id"], required_skills=["x"]), ch),
        201)
    bad_fl = NON_EXISTENT_UUID
    res = api.create_proposal(
        create_proposal_payload(posting["id"], bad_fl),
        make_freelancer_headers(bad_fl))
    validate_error(res, "ERR_FREELANCER_NOT_FOUND", expected_status=404)


def test_deposit_increases_wallet(api):
    """PRD §3.1: "A client's prepaid balance is topped up through an administrative deposit
    that adds a supplied amount_cents (which must be at least 1) to wallet_balance_cents."

    Design: Corner/endpoints/deposit_increases_wallet
    """
    client = create_client()
    res = api.deposit_wallet(client["id"], deposit_payload(12345), make_admin_headers())
    updated = validate_success(res, 200)
    assert updated["wallet_balance_cents"] == 12345


def test_error_contract_not_found(api):
    """PRD §2.5: "ERR_CONTRACT_NOT_FOUND" is the not-found code for a missing contract id.

    Design: Corner/errors/error_contract_not_found
    """
    res = api.get_contract(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(res, "ERR_CONTRACT_NOT_FOUND", expected_status=404)


def test_tax_record_get_not_found(api):
    """PRD §2.5: "ERR_TAX_RECORD_NOT_FOUND" is this entity's own not-found code.

    Design: Corner/endpoints/tax_record_get_not_found
    """
    res = api.get_tax_record(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(res, "ERR_TAX_RECORD_NOT_FOUND", expected_status=404)


def test_rbac_freelancer_cannot_create_posting(api):
    """PRD §2.1: "When a caller presents a role that is syntactically valid but not
    permitted to perform the requested operation — or presents an entity-backed role whose
    identity does not own the targeted resource — the request is rejected with
    ERR_FORBIDDEN_ROLE."
    PRD §4: POST /job-postings is authorized for Client only.

    Design: Corner/rbac/rbac_freelancer_cannot_create_posting
    """
    client = create_client()
    freelancer = create_freelancer(skills=["x"])
    res = api.create_job_posting(
        create_job_posting_payload(client["id"], required_skills=["x"]),
        make_freelancer_headers(freelancer["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_rbac_client_cannot_assign_arbitration(api):
    """PRD §2.1: a caller presenting "a role that is syntactically valid but not permitted
    to perform the requested operation ... is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4: POST /disputes/{id}/assign-arbitration is authorized for Arbitrator only.

    Design: Corner/rbac/rbac_client_cannot_assign_arbitration
    """
    from test_helpers import setup_disputed_milestone
    ctx, milestone, dispute = setup_disputed_milestone(amount_cents=20000, raised_by="CLIENT")
    res = api.assign_arbitration(dispute["id"], ctx["client_headers"])
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
    after = validate_success(api.get_dispute(dispute["id"], make_admin_headers()), 200)
    assert after["status"] == "OPEN"


def test_rbac_missing_user_context(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is rejected
    with ERR_MISSING_USER_CONTEXT."

    Design: Corner/rbac/rbac_missing_user_context
    """
    res = api.list_clients(headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", expected_status=400)
