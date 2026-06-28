"""Corner-queue tests: list endpoints + pagination, reverse-reachability filters,
OCC stale-`version`, RBAC denials, versioning, derived-field reconciliation,
delinquency cure, and immediate consistency."""
import pytest
from test_helpers import (
    ApiErrorId, TEST_USERS, make_client_headers, validate_success, validate_error,
    validate_paginated, get_success_data,
    create_debt_payload, create_offer_payload, accept_offer_payload,
    create_settlement_payload,
    set_clock, create_client, create_program, create_debt, create_offer, accept_offer,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


# ---- endpoints ----------------------------------------------------------
def test_list_debts_filtered_by_program_paginated(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §4: "GET | `/debts` | List debts, filtered by program_id, settled_offer_id, or
    status"

    Design: Corner/endpoints/list_debts_filtered_by_program_paginated
    """
    client = create_client(full_name="C", email="c16@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    create_debt(program["id"], creditor_name="C1", account_number="L-1",
               original_balance=4000)
    create_debt(program["id"], creditor_name="C2", account_number="L-2",
               original_balance=5000)
    res = api.list_debts(ADMIN, params={"program_id": program["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_settlements_filtered_by_offer(api):
    """PRD §4: "GET | `/settlements` | List settlements, filtered by program_id, offer_id,
    debt_id, or status"

    Design: Corner/endpoints/list_settlements_filtered_by_offer_reverse_reachability
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c17@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="RS-1",
                      original_balance=5000)
    activated = get_success_data(api.activate_program(program["id"], ADMIN))
    v1 = activated["version"]
    # Fund enough to cover settlement_amount (2000) + projected_fee (2000*0.25=500)
    # + reserve_floor (0) per PRD §3.7 funding reserve check: 5 * 600 = 3000 >= 2500.
    for m in (4, 5, 6, 7, 8):
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-10T00:00:00Z",
             "amount": 600}, make_client_headers(client["id"]))
    offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                        due_date="2026-12-01T00:00:00Z")
    accept_offer(offer["id"], v1)
    settle = get_success_data(api.create_settlement(
        create_settlement_payload(program["id"], offer["id"]), AGENT))
    res = api.list_settlements(AGENT, params={"offer_id": offer["id"]})
    data, _ = validate_paginated(res)
    assert len(data) == 1
    assert data[0]["id"] == settle["id"]
    assert data[0]["offer_id"] == offer["id"]


# ---- errors: OCC --------------------------------------------------------
def test_occ_stale_program_version_on_offer_accept(api):
    """PRD §2.10: "If `expected_program_version` does not match the program's current `version`, the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.10: "because accepting any offer on a debt bumps the program's `version`, a prior acceptance on a sibling offer renders every other in-flight acceptor's observed version stale, and the stale acceptor is turned away rather than allowed to fund a second settlement the account cannot cover."

    Design: Corner/errors/occ_stale_program_version_on_offer_accept
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c18@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
    debt_a = create_debt(program["id"], creditor_name="Cred A", account_number="OC-A",
                        original_balance=4000)
    debt_b = create_debt(program["id"], creditor_name="Cred B", account_number="OC-B",
                        original_balance=5000)
    activated = get_success_data(api.activate_program(program["id"], ADMIN))
    v_stale = activated["version"]
    ch = make_client_headers(client["id"])
    for m in (2, 3, 4, 5):
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-10T00:00:00Z",
             "amount": 600}, ch)
    api.create_deposit(
        {"program_id": program["id"], "scheduled_for": "2026-06-09T00:00:00Z",
         "amount": 600}, ch)
    offer_a = create_offer(program["id"], debt_a["id"], offer_pct=0.40,
                          due_date="2026-12-01T00:00:00Z")
    offer_b = create_offer(program["id"], debt_b["id"], offer_pct=0.40,
                          due_date="2026-12-01T00:00:00Z")
    accept_offer(offer_a["id"], v_stale)  # bumps Program.version
    res = api.accept_offer(offer_b["id"], accept_offer_payload(v_stale), AGENT)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


# ---- rbac ---------------------------------------------------------------
def test_client_cannot_create_debt_forbidden(api):
    """PRD §2.1: "When a known, authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A `ProgramAdmin` is an operator who creates clients, enrolls programs and
    debts"

    Design: Corner/rbac/client_cannot_create_debt_returns_forbidden
    """
    client = create_client(full_name="C", email="c19@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    res = api.create_debt(
        create_debt_payload(program["id"], creditor_name="Cred",
                           account_number="FB-1", original_balance=5000),
        make_client_headers(client["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_program_admin_cannot_accept_offer_forbidden(api):
    """PRD §2.1: "When a known, authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A `NegotiationAgent` is a settlement specialist who records creditor offers, accepts or rejects them, funds settlements, and completes them."

    Design: Corner/rbac/program_admin_cannot_accept_offer_returns_forbidden
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c20@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="PA-1",
                      original_balance=5000)
    activated = get_success_data(api.activate_program(program["id"], ADMIN))
    v1 = activated["version"]
    offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                        due_date="2026-12-01T00:00:00Z")
    res = api.accept_offer(offer["id"], accept_offer_payload(v1), ADMIN)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles: `ProgramAdmin`, `NegotiationAgent`, and `Client`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    client = create_client(full_name="C", email="c21@x.com", state_code="CA")
    res = api.get_client(client["id"], TEST_USERS["anonymous_headers"])
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


# ---- cross-cutting complexity layers ------------------------------------
def test_version_increments_on_activate(api):
    """PRD §2.4: "an integer `version` that begins at 1 and increments by one on every mutation of that resource."
    PRD §3.4: "Activation increments `Program.version` by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    client = create_client(full_name="C", email="c22@x.com", state_code="CA")
    res = api.create_program({"client_id": client["id"], "monthly_deposit_amount": 600}, ADMIN)
    program = validate_success(res, 201)
    assert program["version"] == 1
    create_debt(program["id"], creditor_name="Cred", account_number="VI-1",
               original_balance=5000)
    activated = get_success_data(api.activate_program(program["id"], ADMIN))
    assert activated["version"] == 2


def test_account_balance_reconciles_after_deposit(api):
    """PRD §2.8: "Its `balance` is always the sum of every cleared deposit's `amount`
    (deposits in `CLEARED` status), minus the `funded_amount` of every settlement that is
    `FUNDED` or `COMPLETED`, minus the `amount` of every settlement fee that is `PAID`. The account
    also exposes `lifetime_deposited` — the sum of `amount` over `CLEARED` deposits"

    Design: Corner/cross_cutting_complexity_layers/derived_account_balance_reconciles_after_deposit
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c23@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    ch = make_client_headers(client["id"])
    api.create_deposit(
        {"program_id": program["id"], "scheduled_for": "2026-04-10T00:00:00Z",
         "amount": 600}, ch)
    api.create_deposit(
        {"program_id": program["id"], "scheduled_for": "2026-05-10T00:00:00Z",
         "amount": 600}, ch)
    acct = get_success_data(api.list_accounts(ADMIN, params={"program_id": program["id"]}))[0]
    assert acct["balance"] == pytest.approx(1200.00, abs=0.01)
    assert acct["lifetime_deposited"] == pytest.approx(1200.00, abs=0.01)


def test_delinquent_then_cured_back_to_current(api):
    """PRD §2.9: "The moment the missed count reaches at least one but stays below three
    (a count of 1 or 2), standing becomes `DELINQUENT`"
    PRD §2.9: "when the missed count reaches zero, the program returns to `CURRENT` (from either `DELINQUENT` or `DEFAULTED`)."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_delinquent_then_cured_back_to_current
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c24@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    dep = get_success_data(api.create_deposit(
        {"program_id": program["id"], "scheduled_for": "2026-06-15T00:00:00Z",
         "amount": 600, "status": "MISSED"}, ADMIN))
    before = get_success_data(api.get_program(program["id"], ADMIN))
    assert before["account_standing"] == "DELINQUENT"
    get_success_data(api.cure_deposit(dep["id"], ADMIN))
    after = get_success_data(api.get_program(program["id"], ADMIN))
    assert after["account_standing"] == "CURRENT"
    assert after["missed_deposit_count"] == 0


# ---- consistency model --------------------------------------------------
def test_immediate_consistency_computed_fields(api):
    """PRD §3.2: "The program's own `total_enrolled_balance` and `fee_tier_pct` are recomputed over the same set of statuses."
    PRD §3.2: "a total of at least 10,000 but below 30,000 dollars yields 0.22"

    Design: Corner/consistency_model/immediate_consistency_computed_fields_in_same_response
    """
    client = create_client(full_name="C", email="c25@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    create_debt(program["id"], creditor_name="Cred", account_number="IC-1",
               original_balance=12000)
    prog = get_success_data(api.get_program(program["id"], ADMIN))
    assert prog["total_enrolled_balance"] == pytest.approx(12000, abs=0.01)
    assert prog["fee_tier_pct"] == pytest.approx(0.22, abs=0.0001)
