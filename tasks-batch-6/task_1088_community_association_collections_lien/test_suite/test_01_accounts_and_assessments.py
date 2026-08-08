"""Account creation/read, assessment input validation, aging, and the
receivable-conservation invariant."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_account, assert_assessment,
    create_account_payload, create_assessment_payload,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]


def test_account_creation_defaults(api):
    """PRD §3.1: "A new account begins in `CURRENT` with a `total_balance_cents` of zero."
    PRD §2.4: "The `version` begins at 1 on creation and increments by 1 on every mutation of the resource"
    PRD §4: "Creating a new resource returns HTTP 201"

    Design: Corner/entities/account_creation_success
    """
    assoc = fixtures.create_association(api, name="Rowan HOA", state_code="CA")
    resp = api.create_account(create_account_payload(assoc["id"], unit_number="100",
                                                     owner_name="Pat Kerr"), AGENT)
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["status"] == "CURRENT"
    assert data["total_balance_cents"] == 0
    assert data["version"] == 1


def test_get_account_non_existent_returns_not_found(api):
    """PRD §2.4: "any path id or referenced FK id that does not resolve to a live resource
    yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/account_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_assessment_missing_amount_returns_validation(api):
    """PRD §2.7: "**Presence and typing** — every required input field is present and
    well-typed, else `ERR_VALIDATION` (422)."

    Design: Corner/entities/assessment_missing_required_amount_returns_422
    """
    assoc, acct = fixtures.setup_account(api, {"name": "Teak HOA"})
    payload = {"account_id": acct["id"], "charge_type": "REGULAR",
               "due_date": "2026-01-01T00:00:00Z"}
    resp = api.create_assessment(payload, AGENT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_assessment_invalid_charge_type_enum(api):
    """PRD §2.7: "**Enum membership** — every enum input carries a declared member, else
    `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/assessment_invalid_enum_charge_type
    """
    assoc, acct = fixtures.setup_account(api, {"name": "Yew HOA"})
    payload = create_assessment_payload(acct["id"], 1000, charge_type="BOGUS")
    resp = api.create_assessment(payload, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_assessment_zero_amount_rejected(api):
    """PRD §3.2: "`amount_cents` must be greater than zero, else `ERR_INVALID_AMOUNT`."

    Design: Corner/entities/assessment_invalid_amount_zero
    """
    assoc, acct = fixtures.setup_account(api, {"name": "Ash HOA"})
    payload = create_assessment_payload(acct["id"], 0)
    resp = api.create_assessment(payload, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


def test_account_aging_buckets_computed(api):
    """PRD §3.2: "A charge with a day count of zero or less contributes to `bucket_current`;
    from 1 through 30 days to `bucket_1_30`; from 31 through 60 to `bucket_31_60`; from 61
    through 90 to `bucket_61_90`; and 91 or more to `bucket_91_plus`."

    Design: Corner/entities/account_aging_buckets_computed
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Bay HOA"})
    fixtures.create_assessment(api, acct["id"], 5000, due_date="2026-05-15T00:00:00Z")
    fixtures.create_assessment(api, acct["id"], 10000, due_date="2026-04-10T00:00:00Z")
    fixtures.create_assessment(api, acct["id"], 20000, due_date="2026-03-15T00:00:00Z")
    fixtures.create_assessment(api, acct["id"], 30000, due_date="2026-02-20T00:00:00Z")
    fixtures.create_assessment(api, acct["id"], 40000, due_date="2026-01-01T00:00:00Z")
    data = get_success_data(api.get_account(acct["id"], AGENT))
    assert data["total_balance_cents"] == 105000
    aging = data["aging"]
    assert aging["bucket_current"] == 5000, aging
    assert aging["bucket_1_30"] == 10000, aging
    assert aging["bucket_31_60"] == 20000, aging
    assert aging["bucket_61_90"] == 30000, aging
    assert aging["bucket_91_plus"] == 40000, aging


# --- compensating_invariant / ci_receivable_conservation (queue A, >=2 tests) ---

def test_receivable_rises_on_charge(api):
    """PRD §2.8: "an account's `total_balance_cents` always equals the sum of the unpaid
    remainders of its live charges; every allocation, reversal, and waiver recomputes it."

    Design: Difficulty/compensating_invariant/ci_receivable_conservation
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Knoll HOA"})
    asm = fixtures.create_assessment(api, acct["id"], 30000, charge_type="ATTORNEY_COST",
                                     due_date="2026-05-01T00:00:00Z")
    assert_assessment(asm)
    data = get_success_data(api.get_account(acct["id"], AGENT))
    assert data["total_balance_cents"] == 30000


def test_receivable_returns_to_zero_after_waive(api):
    """PRD §3.2: "Waiving drives the assessment's `balance_cents` to zero, moves it to
    `WAIVED`, and recomputes the account's `total_balance_cents`."

    Design: Difficulty/compensating_invariant/ci_receivable_conservation
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Knoll HOA"})
    asm = fixtures.create_assessment(api, acct["id"], 30000, charge_type="ATTORNEY_COST",
                                     due_date="2026-05-01T00:00:00Z")
    before = get_success_data(api.get_account(acct["id"], AGENT))
    assert before["total_balance_cents"] == 30000
    waived = validate_success(api.waive_assessment(asm["id"], AGENT))
    assert waived["status"] == "WAIVED"
    after = get_success_data(api.get_account(acct["id"], AGENT))
    assert after["total_balance_cents"] == 0
