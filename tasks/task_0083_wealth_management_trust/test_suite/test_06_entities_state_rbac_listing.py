"""Entity CRUD/validation, state-machine preconditions, RBAC denials, and listing.

Covers the Corner queue entities, state_machines, rbac, and endpoints sections.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_active_trust, make_grantor_headers, make_trustee_headers,
    propose_distribution, create_approved_distribution,
    NON_EXISTENT_UUID, TEST_USERS,
)
from test_helpers.constants import DEFAULT_GST_EXEMPTION_TOTAL_CENTS

ADMIN = TEST_USERS["trust_admin_headers"]


# ─────────────────────────────────────────────────────────────
# Corner / entities
# ─────────────────────────────────────────────────────────────

def test_create_trust_minimal_returns_draft(api):
    """PRD §3.2: "A trust is created in DRAFT status with a name, the settlor's grantor_id,
    and a trust_type of either REVOCABLE or IRREVOCABLE." "On creation the trust's balances
    are zero, its gst_exemption_allocated_cents is 0, and its version is 1."

    Design: Corner/entities/create_trust_minimal_required_fields_returns_201
    """
    g = get_success_data(api.create_grantor({"full_name": "G Min", "generation_level": 0}, ADMIN))
    res = api.create_trust(
        {"name": "Min Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN)
    trust = validate_success(res, 201)
    assert trust["status"] == "DRAFT"
    assert trust["version"] == 1
    assert trust["principal_balance_cents"] == 0
    assert trust["income_balance_cents"] == 0


def test_create_trust_missing_grantor_id_validation(api):
    """PRD §3.2: "A trust is created in DRAFT status with a name, the settlor's grantor_id,
    and a trust_type of either REVOCABLE or IRREVOCABLE."
    PRD §2.10: "Malformed request bodies — a missing required field, a wrong type, or an
    unrecognized enum value — are rejected with ERR_VALIDATION."

    Design: Corner/entities/create_trust_missing_grantor_id_returns_validation
    """
    res = api.create_trust({"name": "No Grantor", "trust_type": "IRREVOCABLE"}, ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_create_trust_invalid_trust_type_validation(api):
    """PRD §2.10: "Malformed request bodies — a missing required field, a wrong type, or an
    unrecognized enum value — are rejected with ERR_VALIDATION."

    Design: Corner/entities/create_trust_invalid_trust_type_enum_returns_validation
    """
    g = get_success_data(api.create_grantor({"full_name": "G Enum", "generation_level": 0}, ADMIN))
    res = api.create_trust(
        {"name": "Bad Enum", "grantor_id": g["id"], "trust_type": "PERPETUAL"}, ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_trust_default_flags_false_when_omitted(api):
    """PRD §3.2: "Two governing-instrument elections may be set at creation, each defaulting
    to false: is_grantor_trust, the IRC subpart-E grantor-trust election under which the
    trust pays no income tax at the trust level and income character instead flows to the
    grantor; and capital_gains_to_income, which when true allocates realized capital gains
    to the income sub-ledger and when false (the default) leaves them in principal."

    Design: Corner/entities/trust_default_flags_applied_when_omitted
    """
    g = get_success_data(api.create_grantor({"full_name": "G Def", "generation_level": 0}, ADMIN))
    trust = validate_success(api.create_trust(
        {"name": "Default Trust", "grantor_id": g["id"], "trust_type": "REVOCABLE"}, ADMIN), 201)
    assert trust["is_grantor_trust"] is False
    assert trust["capital_gains_to_income"] is False


def test_get_nonexistent_trust_not_found(api):
    """PRD §2.6: "the request fails with ERR_NOT_FOUND against the first path segment that
    does not resolve to an existing resource, before any inner segment or body is
    considered."

    Design: Corner/entities/get_trust_nonexistent_returns_not_found
    """
    res = api.get_trust(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_beneficiary_skip_person_computed(api):
    """PRD §3.1: "From these the system computes is_skip_person: a beneficiary is a skip
    person — true — exactly when their generation_level minus the grantor's generation_level
    is at least 2."

    Design: Corner/entities/beneficiary_is_skip_person_computed_true_for_generation_two
    """
    g = get_success_data(api.create_grantor({"full_name": "G Skip", "generation_level": 0}, ADMIN))
    skip = validate_success(api.create_beneficiary(
        {"full_name": "Grandchild", "grantor_id": g["id"], "generation_level": 2}, ADMIN), 201)
    child = validate_success(api.create_beneficiary(
        {"full_name": "Child", "grantor_id": g["id"], "generation_level": 1}, ADMIN), 201)
    assert skip["is_skip_person"] is True
    assert child["is_skip_person"] is False


def test_grantor_remaining_initialized_to_total(api):
    """PRD §3.1: "At creation the grantor's gst_exemption_remaining_cents is initialized
    equal to gst_exemption_total_cents".

    Design: Corner/entities/grantor_gst_exemption_remaining_initialized_to_total
    """
    g = validate_success(api.create_grantor(
        {"full_name": "G Pool", "generation_level": 0,
         "gst_exemption_total_cents": 5_000_000}, ADMIN), 201)
    assert g["gst_exemption_remaining_cents"] == 5_000_000


def test_receipt_amount_zero_rejected(api):
    """PRD §3.3: "A receipt records money coming in: its account_id, an amount_cents greater
    than zero". "An amount_cents of zero or less is rejected with ERR_INVALID_AMOUNT."

    Design: Corner/entities/create_amount_zero_rejected_invalid_amount
    """
    g = get_success_data(api.create_grantor({"full_name": "G Zero", "generation_level": 0}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "Zero Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    acct = get_success_data(api.create_account(trust["id"], {
        "tax_year": 2025, "period_start": "2025-01-01T00:00:00.000Z",
        "period_end": "2026-01-01T00:00:00.000Z"}, ADMIN))
    res = api.create_receipt(acct["id"], {"amount_cents": 0, "receipt_kind": "INTEREST"}, ADMIN)
    validate_error(res, "ERR_INVALID_AMOUNT")


# ─────────────────────────────────────────────────────────────
# Corner / state_machines
# ─────────────────────────────────────────────────────────────

def test_activate_draft_trust_invalid_state(api):
    """PRD §3.2: "Activation then moves it from FUNDED to ACTIVE, permitted only while the
    trust is FUNDED and only once principal_balance_cents is greater than zero".

    Design: Corner/state_machines/activate_trust_from_draft_skips_funded_returns_invalid_state
    """
    g = get_success_data(api.create_grantor({"full_name": "G Inv", "generation_level": 0}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "Inv Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    res = api.activate_trust(trust["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_reject_already_rejected_distribution_invalid_state(api):
    """PRD §3.5: "Rejection is the alternative branch out of PROPOSED: a trustee rejects a
    still-PROPOSED distribution, moving it to the terminal REJECTED state".

    Design: Corner/state_machines/reject_already_rejected_distribution_returns_invalid_state
    """
    ctx = setup_active_trust(contribution_cents=100000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    t1 = ctx["trustees"][0]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    dist = propose_distribution(ctx["account"]["id"], ben_a["id"], 1000, t1, "DISCRETIONARY")
    validate_success(api.reject_distribution(dist["id"], make_trustee_headers(t1)), 200)
    res = api.reject_distribution(dist["id"], make_trustee_headers(t1))
    validate_error(res, "ERR_INVALID_STATE")


def test_amend_irrevocable_trust_rejected(api):
    """PRD §3.9: "It is permitted only while the trust is ACTIVE, and an attempt to amend an
    IRREVOCABLE trust is rejected with ERR_TRUST_IRREVOCABLE."

    Design: Corner/state_machines/amend_irrevocable_trust_returns_trust_irrevocable
    """
    ctx = setup_active_trust(trust_type="IRREVOCABLE", contribution_cents=100000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    res = api.open_amendment(ctx["trust"]["id"], {"set_capital_gains_to_income": True},
                            make_grantor_headers(g_id))
    validate_error(res, "ERR_TRUST_IRREVOCABLE")


def test_post_receipt_to_closed_account_period_frozen(api):
    """PRD §3.3: "Posting either entry to a period that is not OPEN — one that has been
    CLOSED or FILED and is therefore frozen against further entries — is rejected with
    ERR_PERIOD_FROZEN."

    Design: Corner/state_machines/post_receipt_to_closed_account_returns_period_frozen
    """
    ctx = setup_active_trust(contribution_cents=100000, num_trustees=1)
    validate_success(api.close_account(ctx["account"]["id"], ADMIN), 200)
    res = api.create_receipt(ctx["account"]["id"],
                            {"amount_cents": 50000, "receipt_kind": "INTEREST"}, ADMIN)
    validate_error(res, "ERR_PERIOD_FROZEN")


def test_terminate_with_approved_distribution_unsettled(api):
    """PRD §3.9: "Beginning termination moves a trust from ACTIVE to TERMINATING; it is
    permitted only while the trust is ACTIVE and only when no distribution on any of the
    trust's periods is still PROPOSED or APPROVED (an unsettled distribution blocks
    termination with ERR_UNSETTLED_DISTRIBUTION)".

    Design: Corner/state_machines/terminate_trust_with_approved_distribution_returns_unsettled
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=2)
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    create_approved_distribution(ctx["account"]["id"], ben_a["id"], 10000,
                                 t_prop, t_appr, "MANDATORY")
    res = api.terminate_trust(ctx["trust"]["id"], ADMIN)
    validate_error(res, "ERR_UNSETTLED_DISTRIBUTION")


def test_proposer_cannot_approve_own_distribution(api):
    """PRD §3.5: "the approving trustee, identified by X-User-ID, must not equal the
    distribution's proposer_trustee_id, and an attempt by the proposer to approve their own
    distribution is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/state_machines/error_segregation_of_duties_on_approve
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    t1 = ctx["trustees"][0]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    dist = propose_distribution(ctx["account"]["id"], ben_a["id"], 10000, t1, "MANDATORY")
    res = api.approve_distribution(dist["id"], make_trustee_headers(t1))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ─────────────────────────────────────────────────────────────
# Corner / rbac
# ─────────────────────────────────────────────────────────────

def test_beneficiary_cannot_create_trust(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted to perform the
    requested operation (per the authorization column of the endpoint table in §4) is
    rejected with ERR_FORBIDDEN_ROLE." (POST /trusts is TrustAdmin-only per §4.)

    Design: Corner/rbac/beneficiary_cannot_create_trust_forbidden_role
    """
    g = get_success_data(api.create_grantor({"full_name": "G RB", "generation_level": 0}, ADMIN))
    ben = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g["id"], "generation_level": 1}, ADMIN))
    from test_helpers import make_beneficiary_headers
    res = api.create_trust(
        {"name": "Sneaky Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"},
        make_beneficiary_headers(ben["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_grantor_not_owner_cannot_revoke_other_trust(api):
    """PRD §2.1: "When X-User-Role is Grantor, X-User-ID is the id of the acting Grantor;
    any operation scoped to a trust verifies that the trust's grantor_id equals X-User-ID."
    "In all three cases, when the entity-backed actor's X-User-ID does not match the owning
    entity the resource references, the request is rejected with ERR_NOT_OWNER."

    Design: Corner/rbac/grantor_not_owner_cannot_revoke_other_trust
    """
    ctx = setup_active_trust(trust_type="REVOCABLE", contribution_cents=100000, num_trustees=1)
    g2 = get_success_data(api.create_grantor({"full_name": "G2 Stranger", "generation_level": 0}, ADMIN))
    res = api.revoke_trust(ctx["trust"]["id"], make_grantor_headers(g2["id"]))
    validate_error(res, "ERR_NOT_OWNER")


def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an X-User-Role that is not
    one of these four, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    g = get_success_data(api.create_grantor({"full_name": "G Auth", "generation_level": 0}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "Auth Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    res = api.get_trust(trust["id"], {})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─────────────────────────────────────────────────────────────
# Corner / endpoints — listing / pagination / reverse-reachability
# ─────────────────────────────────────────────────────────────

def test_list_trusts_pagination_envelope(api):
    """PRD §2.3: "limit caps the number of items returned; it defaults to 10, with a minimum
    of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes limit, offset, total_count, and has_more in the
    meta object of the envelope."

    Design: Corner/endpoints/list_trusts_pagination_envelope
    """
    g = get_success_data(api.create_grantor({"full_name": "G List", "generation_level": 0}, ADMIN))
    get_success_data(api.create_trust(
        {"name": "List Trust 1", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    get_success_data(api.create_trust(
        {"name": "List Trust 2", "grantor_id": g["id"], "trust_type": "REVOCABLE"}, ADMIN))
    data, meta = validate_paginated(
        api.list_trusts(ADMIN, params={"grantor_id": g["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_accounts_by_trust(api):
    """PRD §3.3: "Periods on a trust may be listed, and a single period fetched, exposing
    those computed figures."

    Design: Corner/endpoints/list_accounts_by_trust_reverse_reachability
    """
    g = get_success_data(api.create_grantor({"full_name": "G AcctList", "generation_level": 0}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "AcctList Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    acct = get_success_data(api.create_account(trust["id"], {
        "tax_year": 2025, "period_start": "2025-01-01T00:00:00.000Z",
        "period_end": "2026-01-01T00:00:00.000Z"}, ADMIN))
    data, meta = validate_paginated(api.list_trust_accounts(trust["id"], ADMIN))
    assert meta["total_count"] == 1
    assert data[0]["id"] == acct["id"]


def test_list_distributions_by_beneficiary(api):
    """PRD §3.5: "Distributions may be fetched individually, listed per account (filterable
    by beneficiary_id), and listed globally filtered by beneficiary_id, proposer_trustee_id,
    or approver_trustee_id."

    Design: Corner/endpoints/list_distributions_by_beneficiary_reverse_reachability
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    t1 = ctx["trustees"][0]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    dist = propose_distribution(ctx["account"]["id"], ben_a["id"], 1000, t1, "DISCRETIONARY")
    data, meta = validate_paginated(
        api.list_distributions(ADMIN, params={"beneficiary_id": ben_a["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == dist["id"]


def test_list_trustee_appointments_by_trustee(api):
    """PRD §3.2: "Appointments on a trust may be listed, a single appointment may be fetched,
    and appointments may also be listed filtered by trustee_id."

    Design: Corner/endpoints/list_trustee_appointments_by_trustee_reverse_reachability
    """
    g = get_success_data(api.create_grantor({"full_name": "G TAList", "generation_level": 0}, ADMIN))
    t1 = get_success_data(api.create_trustee({"full_name": "T A"}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "TAList Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    app = get_success_data(api.create_trustee_appointment(trust["id"], {
        "trustee_id": t1["id"], "term_start": "2025-01-01T00:00:00.000Z",
        "term_end": "2030-01-01T00:00:00.000Z"}, ADMIN))
    data, meta = validate_paginated(
        api.list_trustee_appointments(ADMIN, params={"trustee_id": t1["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == app["id"]


def test_list_filings_by_account(api):
    """PRD §3.7: "A filing may be fetched, filings may be listed per account, and filings
    may be listed globally filtered by account_id or by supersedes_filing_id."

    Design: Corner/endpoints/list_filings_by_account_reverse_reachability
    """
    ctx = setup_active_trust(contribution_cents=100000, num_trustees=1, is_grantor_trust=False)
    validate_success(api.close_account(ctx["account"]["id"], ADMIN), 200)
    filing = get_success_data(api.create_filing(ctx["account"]["id"], {}, ADMIN))
    data, meta = validate_paginated(api.list_account_filings(ctx["account"]["id"], ADMIN))
    assert meta["total_count"] == 1
    assert data[0]["id"] == filing["id"]


def test_list_gst_allocations_by_grantor(api):
    """PRD §3.8: "Allocations may be listed per trust, fetched individually, and listed
    globally filtered by grantor_id."

    Design: Corner/endpoints/list_gst_allocations_by_grantor_reverse_reachability
    """
    from test_helpers import allocate_gst_exemption
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    alloc = allocate_gst_exemption(ctx["trust"]["id"], g_id, 1_000_000, ctx["trust"]["version"])
    data, meta = validate_paginated(
        api.list_gst_exemption_allocations(ADMIN, params={"grantor_id": g_id}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == alloc["id"]


def test_list_gst_events_by_beneficiary(api):
    """PRD §3.8: "GST events may be listed per trust (filterable by beneficiary_id), fetched
    individually, and listed globally filtered by beneficiary_id or distribution_id."

    Design: Corner/endpoints/list_gst_events_by_beneficiary_reverse_reachability
    """
    from test_helpers import allocate_gst_exemption, create_paid_distribution
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(1_500_000, "INTEREST")],
        num_trustees=2)
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    skip = get_success_data(api.create_beneficiary(
        {"full_name": "Grandchild", "grantor_id": g_id, "generation_level": 2}, ADMIN))
    allocate_gst_exemption(ctx["trust"]["id"], g_id, 2_000_000, ctx["trust"]["version"])
    create_paid_distribution(ctx["account"]["id"], skip["id"], 1_000_000,
                             t_prop, t_appr, "MANDATORY")
    data, meta = validate_paginated(
        api.list_gst_events(ADMIN, params={"beneficiary_id": skip["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["event_type"] == "TAXABLE_DISTRIBUTION"
    assert data[0]["taxable_amount_cents"] == 1_000_000
