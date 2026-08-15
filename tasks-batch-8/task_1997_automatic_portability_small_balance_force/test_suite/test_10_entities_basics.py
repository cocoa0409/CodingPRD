"""Queue B corner tests: entity creation defaults, system fields, not-found, FK integrity."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    setup_ira_with_fee_disclosure,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


def test_recordkeeper_create_defaults_and_initial_state():
    """PRD §3.1: "New recordkeepers begin `PENDING_ONBOARD`"
    PRD §2.5: "a unique, server-generated identifier formatted as a UUID, with no type
    prefix"
    PRD §2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/entities/recordkeeper_create_defaults_and_initial_state
    """
    from test_helpers import assert_recordkeeper
    rk = validate_success(api_client.create_recordkeeper(
        {"recordkeeper_code": "RK-A", "legal_name": "Recordkeeper A"}, OPS), 201)
    assert_recordkeeper(rk)
    assert rk["network_status"] == "PENDING_ONBOARD"
    assert rk["version"] == 1
    assert rk["exited_at"] is None
    assert rk["created_at"] == "2026-08-01T00:00:00.000Z"


def test_plan_create_applies_defaults_and_computes_reachability():
    """PRD §3.1: "The force-out configuration is optional at registration and defaults as
    follows: `cash_out_threshold_cents` defaults to 100,000 cents ($1,000),
    `rollover_threshold_cents` to 700,000 cents ($7,000), `state_withholding_rate` to 0,
    `valuation_basis` to `PROCESSING_DATE`, and both `auto_portability_enabled` and
    `accepts_incoming_transfers` to true."
    PRD §2.8: "A plan's `network_reachable` flag is derived, never stored by hand: it is
    true exactly when the plan's recordkeeper has `network_status` `ACTIVE` and the plan's
    own `accepts_incoming_transfers` flag is true."
    PRD §3.1: "New plans begin with `plan_status` `ACTIVE`"

    Design: Corner/entities/plan_create_applies_defaults_and_computes_reachability
    """
    rk = create_active_recordkeeper()
    plan = validate_success(api_client.create_plan(
        {"plan_name": "Plan X", "sponsor_ein": "11-1111111",
         "recordkeeper_id": rk["id"]}, SPONSOR), 201)
    assert plan["cash_out_threshold_cents"] == 100000
    assert plan["rollover_threshold_cents"] == 700000
    assert plan["state_withholding_rate"] == 0
    assert plan["valuation_basis"] == "PROCESSING_DATE"
    assert plan["auto_portability_enabled"] is True
    assert plan["accepts_incoming_transfers"] is True
    assert plan["network_reachable"] is True
    assert plan["plan_status"] == "ACTIVE"


def test_participant_create_system_fields_input_ignored():
    """PRD §2.5: "a unique, server-generated identifier formatted as a UUID, with no type
    prefix"
    PRD §2.5: "an ISO 8601 UTC timestamp with three fractional digits recording when the
    resource was created"
    PRD §3.2: "New participants start with `address_quality` `UNVERIFIED`."
    PRD §2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/entities/participant_create_system_fields_input_ignored
    """
    participant = validate_success(api_client.create_participant(
        {"id": "00000000-0000-0000-0000-000000000000",
         "created_at": "2001-01-01T00:00:00Z",
         "ssn_hash": "hash-a", "full_name": "Ann A",
         "date_of_birth": "1980-01-01",
         "mailing_address_line1": "1 Main St", "mailing_city": "Springfield",
         "mailing_state": "IL", "mailing_zip": "62701"},
        SPONSOR,
    ), 201)
    assert participant["id"] != "00000000-0000-0000-0000-000000000000"
    assert participant["created_at"] == "2026-08-01T00:00:00.000Z"
    assert participant["version"] == 1
    assert participant["address_quality"] == "UNVERIFIED"


def test_plan_get_not_found_returns_404():
    """PRD §2.9: "5. **Existence** — path identifiers and body foreign-key references
    (plan, batch, case, notice, election, IRA, check, match, transfer, review,
    recordkeeper, participant) must exist; failure is `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/plan_get_not_found_returns_404
    """
    res = api_client.get_plan(NON_EXISTENT_UUID, OPS)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)


def test_case_create_with_unknown_batch_returns_not_found():
    """PRD §2.10: "Requests that carry several resource identifiers — whether in the path
    or as foreign keys in the body — are validated left to right: the system confirms each
    identifier in the order it appears and rejects the request with `ERR_NOT_FOUND` (404)
    at the first identifier that does not correspond to an existing resource"

    Design: Corner/entities/case_create_with_unknown_batch_returns_not_found
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    participant = create_participant()
    res = api_client.create_distribution_case({
        "distribution_batch_id": NON_EXISTENT_UUID,
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "separation_date": "2026-07-15T00:00:00Z",
        "separation_date_balance_cents": 50000,
        "processing_date_balance_cents": 50000,
    }, SPONSOR)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)


def test_fee_assessment_immutable_event_entity():
    """PRD §2.5: "An `IRAFeeAssessment` row is append-only: it carries `id` and
    `created_at` only, has neither `updated_at` nor `version`, and is never modified after
    posting."
    PRD §3.6: "an August-1-to-September-1 period bills 510 cents under `ACTUAL_365`
    (thirty-one days)"

    Design: Corner/entities/fee_assessment_immutable_event_entity
    """
    ctx = setup_ira_with_fee_disclosure(balance=300000)
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
    fee = validate_success(api_client.assess_ira_fee(ctx["ira"]["id"], OPS), 201)
    fetched = validate_success(api_client.get_fee_assessment(fee["id"], OPS))
    assert "version" not in fetched
    assert "updated_at" not in fetched
    assert fetched["id"] == fee["id"]
    assert fetched["amount_cents"] == 510
    assert fetched["days_in_period"] == 31
    assert fetched["day_count_convention"] == "ACTUAL_365"
    assert fetched["period_end"] == "2026-09-01T00:00:00.000Z"
