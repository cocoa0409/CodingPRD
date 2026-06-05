"""Entity CRUD, defaults, system fields, referential integrity, listing,
basic Claim/Appeal lifecycle transitions, and RBAC gates."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_employer_payload, create_claimant_payload, create_wage_record_payload,
    create_claim_payload, create_determination_payload,
    create_employer, create_claimant, add_wage_record, create_draft_claim,
    submit_claim,
    assert_employer, assert_claim, assert_claimant, assert_wage_record,
    make_claimant_headers,
    NONEXISTENT_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
ADJ = TEST_USERS["adjudicator_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ── Corner: entities / create_employer_returns_201_with_seeded_reserve ──

def test_create_employer_seeds_reserve(api):
    """PRD §3.1: "On creation the system seeds the employer's
    reserve_account_balance_cents equal to the supplied reserve_opening_balance_cents
    and sets charge_protest_count to 0."
    PRD §2.4: "an integer version that begins at its initial value".

    Design: Corner/entities/create_employer_returns_201_with_seeded_reserve
    """
    res = api.create_employer(
        create_employer_payload(legal_name="Fresh Co", reserve_opening_balance_cents=5000000),
        ADMIN)
    emp = validate_success(res, 201)
    assert_employer(emp)
    assert emp["reserve_account_balance_cents"] == 5000000
    assert emp["charge_protest_count"] == 0
    assert emp["version"] == 1


# ── Corner: entities / get_claim_returns_stored_entity ──

def test_get_claim_returns_stored_entity(api):
    """PRD §3.2: "A new claim is created in DRAFT status".
    PRD §3.2: "A Claimant (or a ProgramAdmin acting on their behalf) opens a Claim
    by supplying the claimant_id and the filed_date."

    Design: Corner/entities/get_claim_returns_stored_entity
    """
    claimant = create_claimant()
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    res = api.get_claim(claim["id"], make_claimant_headers(claimant["id"]))
    fetched = validate_success(res, 200)
    assert_claim(fetched)
    assert fetched["status"] == "DRAFT"
    assert fetched["filed_date"] == "2026-04-05"


# ── Corner: entities / list_employers_paginated_envelope ──

def test_list_employers_paginated(api):
    """PRD §2.3: "The limit parameter caps the number of items returned ... Each
    list response carries limit, offset, total_count, and has_more in the meta
    object of the envelope."

    Design: Corner/entities/list_employers_paginated_envelope
    """
    create_employer(legal_name="L1")
    create_employer(legal_name="L2")
    data, meta = validate_paginated(
        api.list_employers(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ── Corner: entities / get_employer_not_found ──

def test_get_employer_not_found(api):
    """PRD §2.5: "a missing target yields ERR_NOT_FOUND."

    Design: Corner/entities/get_employer_not_found
    """
    res = api.get_employer(NONEXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ── Corner: entities / create_claimant_missing_required_field ──

def test_create_claimant_missing_full_name(api):
    """PRD §3.1: "A Claimant may be self-registered by an anonymous caller or
    created by a ProgramAdmin, supplying full_name, ssn_last4, date_of_birth, and
    optionally is_able_and_available."
    PRD §2.10: "then the presence and well-formedness of input fields
    (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_claimant_missing_required_field
    """
    payload = create_claimant_payload()
    del payload["full_name"]
    res = api.create_claimant(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ── Corner: entities / claimant_able_available_default_true ──

def test_claimant_able_available_defaults_true(api):
    """PRD §3.1: "The is_able_and_available attestation defaults to true".

    Design: Corner/entities/claimant_able_available_default_true
    """
    payload = create_claimant_payload(full_name="Def Ault")
    payload.pop("is_able_and_available", None)
    claimant = validate_success(api.create_claimant(payload, ADMIN), 201)
    assert_claimant(claimant)
    assert claimant["is_able_and_available"] is True


# ── Corner: entities / claim_system_fields_generated ──

def test_claim_system_fields_generated(api):
    """PRD §2.4: "Each such resource exposes an id (a server-minted UUID with no
    type prefix), a created_at timestamp ... an updated_at timestamp ... and an
    integer version that begins at its initial value".
    PRD §3.2: "A new claim is created in DRAFT status".

    Design: Corner/entities/claim_system_fields_generated
    """
    claimant = create_claimant()
    res = api.create_claim(create_claim_payload(claimant["id"], "2026-04-05"),
                           make_claimant_headers(claimant["id"]))
    claim = validate_success(res, 201)
    assert_claim(claim)
    assert claim["status"] == "DRAFT"
    assert claim["version"] == 1


# ── Corner: entities / wage_record_bad_quarter_format_rejected ──

def test_wage_record_bad_quarter_rejected(api):
    """PRD §3.1: "The calendar_quarter must match the pattern of a four-digit year,
    a hyphen, the letter Q, and a quarter number 1 through 4 (for example, 2025-Q1)".

    Design: Corner/entities/wage_record_bad_quarter_format_rejected
    """
    employer = create_employer()
    claimant = create_claimant()
    res = api.create_wage_record(
        create_wage_record_payload(claimant["id"], employer["id"], "2025-Q9", 10000),
        ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ── Corner: entities / wage_record_immutable_no_version_field ──

def test_wage_record_has_no_version_field(api):
    """PRD §2.4: "A WageRecord and a WorkSearchContact are immutable ledger lines:
    each carries only an id and a created_at. Neither exposes updated_at and neither
    exposes version, because once written they are never mutated in place."

    Design: Corner/entities/wage_record_immutable_no_version_field
    """
    employer = create_employer()
    claimant = create_claimant()
    res = api.create_wage_record(
        create_wage_record_payload(claimant["id"], employer["id"], "2025-Q1", 10000),
        ADMIN)
    wr = validate_success(res, 201)
    assert_wage_record(wr)
    assert "version" not in wr
    assert wr["is_disputed"] is False


# ── Corner: entities / wage_record_bad_employer_reference ──

def test_wage_record_nonexistent_employer_not_found(api):
    """PRD §2.5: "any resource named in the path or referenced by a foreign key in
    the body must exist at all; a missing target yields ERR_NOT_FOUND."

    Design: Corner/entities/wage_record_bad_employer_reference
    """
    claimant = create_claimant()
    res = api.create_wage_record(
        create_wage_record_payload(claimant["id"], NONEXISTENT_UUID, "2025-Q1", 10000),
        ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ── Corner: errors / duplicate_employer_account_number_rejected ──

def test_duplicate_employer_account_number_rejected(api):
    """PRD §3.1: "The state_account_number must be unique across all employers; a
    collision is rejected with ERR_DUPLICATE_RESOURCE."

    Design: Corner/errors/duplicate_employer_account_number_rejected
    """
    api.create_employer(create_employer_payload(state_account_number="DUP-1"), ADMIN)
    res = api.create_employer(
        create_employer_payload(legal_name="Second", state_account_number="DUP-1"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


# ── Corner: state_machines / claim_initial_state_is_draft ──

def test_claim_initial_state_is_draft(api):
    """PRD §3.2: "A new claim is created in DRAFT status with its monetary fields at
    their defaults".

    Design: Corner/state_machines/claim_initial_state_is_draft
    """
    claimant = create_claimant()
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    assert claim["status"] == "DRAFT"


# ── Corner: state_machines / submit_claim_from_draft_valid_transition ──

def test_submit_claim_draft_to_pending(api):
    """PRD §3.2: "Submitting a draft claim advances it from DRAFT to
    MONETARY_PENDING ... and the claim's version increments by one."

    Design: Corner/state_machines/submit_claim_from_draft_valid_transition
    """
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 780000)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submitted = get_success_data(api_client.submit_claim(
        claim["id"], {}, make_claimant_headers(claimant["id"])))
    assert submitted["status"] == "MONETARY_PENDING"
    assert submitted["version"] == 2


# ── Corner: state_machines / submit_claim_without_wages_rejected ──

def test_submit_claim_without_wages_rejected(api):
    """PRD §3.2: "requires that at least one non-disputed WageRecord exists for that
    claimant; a submission with no qualifying wages is rejected with
    ERR_NO_QUALIFYING_WAGES."

    Design: Corner/state_machines/submit_claim_without_wages_rejected
    """
    claimant = create_claimant()
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    res = api.submit_claim(claim["id"], {}, make_claimant_headers(claimant["id"]))
    validate_error(res, "ERR_NO_QUALIFYING_WAGES", expected_status=422)


# ── Corner: state_machines / submit_already_submitted_claim_invalid_state ──

def test_submit_already_submitted_claim_invalid_state(api):
    """PRD §3.2: "Submission is permitted only while the claim is DRAFT".
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (ERR_INVALID_STATE)."

    Design: Corner/state_machines/submit_already_submitted_claim_invalid_state
    """
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 780000)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    res = api.submit_claim(claim["id"], {}, make_claimant_headers(claimant["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ── Corner: rbac / claimant_cannot_issue_determination ──

def test_claimant_cannot_issue_determination(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."
    PRD §3.2: "An Adjudicator issues a Determination by supplying the claim_id and a
    determination_type of either MONETARY or NONMONETARY."

    Design: Corner/rbac/claimant_cannot_issue_determination
    """
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 780000)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    res = api.create_determination(
        create_determination_payload(claim["id"], "MONETARY"),
        make_claimant_headers(claimant["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ── Corner: rbac / missing_auth_headers_unauthenticated ──

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header on a protected endpoint is
    rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 780000)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    # POST /ui/determinations with no auth headers at all.
    res = api.create_determination(
        create_determination_payload(claim["id"], "MONETARY"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
