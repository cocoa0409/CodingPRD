"""Entity-shape probes: what a create returns, what a read returns, what a list
returns, and what a malformed or dangling body is refused with.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    DEFAULT_CONSULTATION_RESPONSE_BUSINESS_DAYS,
    DEFAULT_ADVANCE_INTEREST_RATE_PCT,
    DEFAULT_FEE_BASIS_CONVENTION,
    DEFAULT_LIQUIDATION_FEE_RATE_PCT,
    DEFAULT_SPECIAL_SERVICING_FEE_ANNUAL_PCT,
    DEFAULT_WORKOUT_FEE_RATE_PCT,
)
from test_helpers.test_users import (
    ASSET_MANAGER,
    MASTER_SERVICER,
    PLATFORM_ADMIN,
)

ABSENT_LOAN_ID = "00000000-0000-4000-8000-000000000001"
ABSENT_TRUST_ID = "00000000-0000-4000-8000-000000000003"
CLIENT_SUPPLIED_ID = "00000000-0000-4000-8000-000000000002"


def test_boarding_a_trust_returns_the_whole_row_with_its_ledgers_zeroed(api):
    """The three echoed inputs, the four common fields and every ledger.

    The PRD: "On creation the control test runs once and yields `control_status` of
    `CONTROLLING`; `controlling_class_notional_usd` therefore starts equal to
    `original_controlling_class_balance_usd`, while `total_ara_usd`,
    `realized_loss_usd`, `total_advances_outstanding_usd`,
    `excess_liquidation_proceeds_usd` and `loans_in_special_servicing_count` all
    start at zero."

    Design: Corner/entities/trust_creation_returns_201_with_every_declared_field
    """
    response = api.create_trust(
        f.trust_payload(deal_name="CMBS 2026-E1"), PLATFORM_ADMIN
    )
    trust = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    a.assert_request_id_format(body["meta"])
    a.assert_millisecond_timestamp(
        body["meta"]["api_request_timestamp"], "api_request_timestamp"
    )

    assert trust["deal_name"] == "CMBS 2026-E1"
    assert trust["closing_date"].startswith("2026-01-15")
    a.assert_money(
        trust["original_controlling_class_balance_usd"],
        40000000.00,
        "original_controlling_class_balance_usd",
    )
    a.assert_common_fields(trust, "Trust")
    a.assert_id_has_no_prefix(trust["id"])
    a.assert_version_is(trust, 1, "Trust")
    assert trust["created_at"] == trust["updated_at"]
    a.assert_millisecond_timestamp(trust["created_at"], "created_at")

    a.assert_money(
        trust["controlling_class_notional_usd"],
        40000000.00,
        "controlling_class_notional_usd",
    )
    a.assert_status(trust, "CONTROLLING", "control_status")
    a.assert_money(trust["total_ara_usd"], 0.00, "total_ara_usd")
    a.assert_money(trust["realized_loss_usd"], 0.00, "realized_loss_usd")
    a.assert_money(
        trust["total_advances_outstanding_usd"], 0.00, "total_advances_outstanding_usd"
    )
    a.assert_money(
        trust["excess_liquidation_proceeds_usd"],
        0.00,
        "excess_liquidation_proceeds_usd",
    )
    assert trust["loans_in_special_servicing_count"] == 0


def test_reading_a_loan_returns_exactly_what_boarding_it_stored(api):
    """A GET is not a write, so version stays at 1.

    The PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every mutation of the row, and `version`, an integer that
    starts at 1 when the row is created and increases by exactly 1 on every write
    that touches the row."

    Design: Corner/entities/loan_retrieval_returns_the_stored_row_unchanged
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-E2")
    created = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-E01",
        maturity_date="2029-06-01T00:00:00Z",
    )

    loan = validate_success(api.get_loan(created["id"], MASTER_SERVICER))
    assert loan["id"] == created["id"]
    assert loan["trust_id"] == trust["id"]
    assert loan["loan_number"] == "L-E01"
    a.assert_money(
        loan["current_principal_balance_usd"], 10000000.00, "current_principal_balance_usd"
    )
    a.assert_rate_pct(loan["note_rate_pct"], 6.0, "note_rate_pct")
    a.assert_money(
        loan["monthly_debt_service_usd"], 65000.00, "monthly_debt_service_usd"
    )
    assert loan["maturity_date"].startswith("2029-06-01")
    a.assert_status(loan, "MASTER_SERVICING", "servicing_status")
    a.assert_status(loan, "CURRENT", "payment_status")
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        65000.00,
        "required_monthly_pi_advance_usd",
    )
    a.assert_version_is(loan, 1, "Loan")


def test_the_loan_listing_filters_before_it_paginates(api):
    """total_count reports the filtered population, not the table.

    The PRD: "Both values are echoed back in `meta`, alongside `total_count` — the
    number of rows matching the filter before the page window is applied — and
    `has_more`, which is true whenever rows remain beyond the current window."

    Design: Corner/entities/loans_listing_paginates_with_total_count_and_has_more
    """
    trust_x = fx.create_trust(api, deal_name="CMBS 2026-X1")
    trust_y = fx.create_trust(
        api,
        deal_name="CMBS 2026-Y1",
        closing_date="2026-02-15T00:00:00Z",
        original_controlling_class_balance_usd=20000000,
    )
    loan_x1 = fx.create_mid_size_loan(
        api, trust_x["id"], loan_number="L-X01", maturity_date="2029-06-01T00:00:00Z"
    )
    loan_x2 = fx.create_mid_size_loan(
        api,
        trust_x["id"],
        loan_number="L-X02",
        original_balance_usd=8000000,
        current_principal_balance_usd=7000000,
        note_rate_pct=5.5,
        monthly_debt_service_usd=45000,
        maturity_date="2030-06-01T00:00:00Z",
        securitization_value_usd=11000000,
    )
    loan_x3 = fx.create_mid_size_loan(
        api,
        trust_x["id"],
        loan_number="L-X03",
        original_balance_usd=6000000,
        current_principal_balance_usd=5500000,
        note_rate_pct=5.0,
        monthly_debt_service_usd=32000,
        maturity_date="2031-06-01T00:00:00Z",
        securitization_value_usd=9000000,
    )
    loan_y1 = fx.create_mid_size_loan(
        api,
        trust_y["id"],
        loan_number="L-Y01",
        original_balance_usd=4000000,
        current_principal_balance_usd=3800000,
        note_rate_pct=7.0,
        monthly_debt_service_usd=28000,
        maturity_date="2028-06-01T00:00:00Z",
        securitization_value_usd=6000000,
    )

    response = api.list_loans(PLATFORM_ADMIN, {"trust_id": trust_x["id"], "limit": 2, "offset": 0})
    page_one, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(page_one) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert a.ids_of(page_one) == [loan_x1["id"], loan_x2["id"]]

    page_two, meta_two = validate_paginated(
        api.list_loans(PLATFORM_ADMIN, {"trust_id": trust_x["id"], "limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert a.ids_of(page_two) == [loan_x3["id"]]

    a.assert_excludes_id(page_one, loan_y1["id"])
    a.assert_excludes_id(page_two, loan_y1["id"])


def test_a_well_formed_but_absent_loan_id_reports_the_loans_own_404(api):
    """The not-found code names the entity of the failing path segment.

    The PRD: "Every identifier appearing as a path segment resolves to a stored row,
    or the 404 not-found error naming the entity of the *failing segment*"

    Design: Corner/entities/loan_get_with_absent_uuid_returns_loan_not_found
    """
    response = api.get_loan(ABSENT_LOAN_ID, MASTER_SERVICER)
    validate_error(response, e.ERR_LOAN_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_omitting_one_required_loan_field_writes_nothing_anywhere(api):
    """securitization_value_usd has no default, so its absence is a 400.

    The PRD: "5. The request body parses; every required field is present; every
    field has its declared type; every enumerated value is a member of its declared
    set; every numeric constraint holds; and every conditionally-forbidden field is
    absent. Otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/loan_create_missing_required_securitization_value_rejected
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-E3")

    response = api.create_loan(
        f.mid_size_loan_payload(
            trust["id"],
            loan_number="L-E03",
            maturity_date="2029-06-01T00:00:00Z",
            securitization_value_usd=None,
        ),
        MASTER_SERVICER,
    )
    validate_error(response, e.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_loans(PLATFORM_ADMIN, {"trust_id": trust["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    a.assert_version_is(fx.read_trust(api, trust["id"], PLATFORM_ADMIN), 1, "Trust")


def test_a_minimal_trust_body_yields_every_declared_default(api):
    """All six economic parameters fall back to their stated defaults.

    The PRD: "Six economic parameters may be supplied and each has a default, so a
    minimal body is legal: `special_servicing_fee_annual_pct` defaults to a quarter
    of one percent per year, `workout_fee_rate_pct` and `liquidation_fee_rate_pct`
    both default to one percent, `advance_interest_rate_pct` defaults to five percent
    per year, `fee_basis_convention` defaults to `STATED_PRINCIPAL` (its only
    alternative being `ARA_ADJUSTED`), and `consultation_response_business_days`
    defaults to ten."

    Design: Corner/entities/trust_create_applies_every_declared_default
    """
    trust = validate_success(
        api.create_trust(f.trust_payload(deal_name="CMBS 2026-E4"), PLATFORM_ADMIN), 201
    )

    a.assert_rate_pct(
        trust["special_servicing_fee_annual_pct"],
        DEFAULT_SPECIAL_SERVICING_FEE_ANNUAL_PCT,
        "special_servicing_fee_annual_pct",
    )
    a.assert_rate_pct(
        trust["workout_fee_rate_pct"], DEFAULT_WORKOUT_FEE_RATE_PCT, "workout_fee_rate_pct"
    )
    a.assert_rate_pct(
        trust["liquidation_fee_rate_pct"],
        DEFAULT_LIQUIDATION_FEE_RATE_PCT,
        "liquidation_fee_rate_pct",
    )
    a.assert_rate_pct(
        trust["advance_interest_rate_pct"],
        DEFAULT_ADVANCE_INTEREST_RATE_PCT,
        "advance_interest_rate_pct",
    )
    a.assert_status(trust, DEFAULT_FEE_BASIS_CONVENTION, "fee_basis_convention")
    assert (
        trust["consultation_response_business_days"]
        == DEFAULT_CONSULTATION_RESPONSE_BUSINESS_DAYS
    )


def test_a_new_loan_starts_with_every_computed_ledger_at_zero(api):
    """The nine server-maintained figures are initialized, not left null.

    The PRD: "A new loan starts with `servicing_status` of `MASTER_SERVICING` and
    `payment_status` of `CURRENT`, has `required_monthly_pi_advance_usd` equal to its
    `monthly_debt_service_usd`, has `consecutive_timely_payments` at zero, has
    `ara_amount_usd`, `advances_outstanding_usd`, `fees_payable_usd` and
    `realized_loss_usd` at zero, has `appraisal_required` and `is_modified` both
    false, and leaves `transferred_to_special_on`, `transfer_event_code`,
    `asset_business_plan_due_date`, `last_appraised_value_usd`,
    `active_workout_plan_id` and `correction_source_plan_id` null."

    Design: Corner/entities/loan_create_computed_ledger_fields_start_at_zero
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-E5")
    loan = validate_success(
        api.create_loan(
            f.mid_size_loan_payload(
                trust["id"],
                loan_number="L-E05",
                maturity_date="2029-06-01T00:00:00Z",
            ),
            MASTER_SERVICER,
        ),
        201,
    )

    a.assert_money(
        loan["accrued_unpaid_interest_usd"], 0.00, "accrued_unpaid_interest_usd"
    )
    a.assert_money(loan["ara_amount_usd"], 0.00, "ara_amount_usd")
    a.assert_money(loan["advances_outstanding_usd"], 0.00, "advances_outstanding_usd")
    a.assert_money(loan["fees_payable_usd"], 0.00, "fees_payable_usd")
    a.assert_money(loan["realized_loss_usd"], 0.00, "realized_loss_usd")
    assert loan["consecutive_timely_payments"] == 0
    assert loan["appraisal_required"] is False
    assert loan["is_modified"] is False
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        65000.00,
        "required_monthly_pi_advance_usd",
    )
    a.assert_fields_null(
        loan,
        "transferred_to_special_on",
        "transfer_event_code",
        "asset_business_plan_due_date",
        "last_appraised_value_usd",
        "active_workout_plan_id",
        "correction_source_plan_id",
    )

    trust_after = fx.read_trust(api, trust["id"], PLATFORM_ADMIN)
    assert trust_after["loans_in_special_servicing_count"] == 0


def test_client_supplied_identity_and_ledger_fields_are_not_honoured(api):
    """The server mints its own id, version and created_at.

    The PRD: "Every stored resource carries an `id`, which is a server-minted UUID
    with no type prefix, and a `created_at`, which is an ISO 8601 UTC timestamp with
    three fractional digits. Client-supplied identifiers are never honoured."

    Design: Corner/entities/trust_create_with_client_supplied_system_fields_input_ignored
    """
    trust = validate_success(
        api.create_trust(
            f.trust_payload(
                deal_name="CMBS 2026-E6",
                id=CLIENT_SUPPLIED_ID,
                version=99,
                created_at="2020-01-01T00:00:00.000Z",
                total_ara_usd=5000000,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    assert trust["id"] != CLIENT_SUPPLIED_ID
    a.assert_id_has_no_prefix(trust["id"])
    a.assert_version_is(trust, 1, "Trust")
    assert not trust["created_at"].startswith("2020-01-01"), (
        "a client-supplied created_at is ignored, never stored"
    )
    a.assert_money(trust["total_ara_usd"], 0.00, "total_ara_usd")


def test_an_undeclared_transfer_event_code_records_nothing(api):
    """MONETARY_DEFAULT_30D is not one of the six declared codes.

    The PRD: "The six recognised event codes are `MONETARY_DEFAULT_60D`,
    `IMMINENT_DEFAULT`, `MATURITY_DEFAULT`, `BANKRUPTCY`, `RECEIVERSHIP` and
    `OTHER_MATERIAL_DEFAULT`."

    Design: Corner/entities/transfer_event_create_with_invalid_enum_event_code_rejected
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-E7")
    loan = fx.create_mid_size_loan(
        api, trust["id"], loan_number="L-E07", maturity_date="2029-06-01T00:00:00Z"
    )

    response = api.create_transfer_event(
        f.transfer_event_payload(
            loan["id"],
            event_code="MONETARY_DEFAULT_30D",
            evidence_note="one missed payment",
            days_delinquent_at_event=None,
        ),
        MASTER_SERVICER,
    )
    validate_error(response, e.ERR_INVALID_REQUEST, 400)

    events, meta = validate_paginated(
        api.list_loan_transfer_events(loan["id"], MASTER_SERVICER)
    )
    assert events == []
    assert meta["total_count"] == 0

    validate_error(
        api.set_loan_servicing_status(
            loan["id"], f.status_payload("SPECIAL_SERVICING"), MASTER_SERVICER
        ),
        e.ERR_NO_QUALIFYING_TRANSFER_EVENT,
        422,
    )


def test_a_transfer_event_carries_no_version_and_no_updated_at(api):
    """The event log is append-only; only the service marks it consumed.

    The PRD: "The servicing transfer event log is append-only and immutable: a
    `ServicingTransferEvent` row carries only `id` and `created_at`. It has no
    `updated_at` and no `version`, there is no endpoint that changes it, and the only
    mutation the service ever makes to an event is the internal marking of
    `consumed_by_transfer` when a transfer consumes it."

    Design: Corner/entities/transfer_event_is_immutable_with_no_version_and_no_status_endpoint
    """
    trust = fx.create_trust(api, deal_name="CMBS 2026-E8")
    loan = fx.create_mid_size_loan(
        api, trust["id"], loan_number="L-E08", maturity_date="2029-06-01T00:00:00Z"
    )
    event = fx.record_bankruptcy_event(
        api, loan["id"], evidence_note="chapter 11 petition"
    )
    a.assert_immutable_common_fields(event, "ServicingTransferEvent")

    fx.transfer_to_special_servicing(api, loan["id"])

    events, _ = validate_paginated(
        api.list_loan_transfer_events(
            loan["id"], MASTER_SERVICER, {"event_code": "BANKRUPTCY"}
        )
    )
    assert len(events) == 1
    recorded = events[0]
    a.assert_immutable_common_fields(recorded, "ServicingTransferEvent")
    assert recorded["id"] == event["id"]
    assert recorded["created_at"] == event["created_at"]
    a.assert_fields_present(
        recorded,
        "loan_id",
        "event_code",
        "occurred_on",
        "evidence_note",
        "triggers_transfer",
        "consumed_by_transfer",
    )
    assert recorded["triggers_transfer"] is True
    assert recorded["consumed_by_transfer"] is True


def test_a_loan_naming_an_absent_trust_reports_the_parents_404(api):
    """A body foreign key resolves at priority 6, not at schema time.

    The PRD: "6. Every foreign key in the request body resolves to a stored row, or
    the 404 not-found error naming that entity: a dangling `trust_id` gives
    `ERR_TRUST_NOT_FOUND`, a dangling `loan_id` gives `ERR_LOAN_NOT_FOUND`"

    Design: Corner/entities/loan_create_with_absent_trust_id_returns_trust_not_found
    """
    response = api.create_loan(
        f.mid_size_loan_payload(
            ABSENT_TRUST_ID,
            loan_number="L-E09",
            maturity_date="2029-06-01T00:00:00Z",
        ),
        MASTER_SERVICER,
    )
    validate_error(response, e.ERR_TRUST_NOT_FOUND, 404)

    rows, meta = validate_paginated(api.list_loans(PLATFORM_ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_consultation_may_only_be_issued_to_the_trust_that_owns_the_subject(api):
    """Both foreign keys resolve, yet the pairing is still wrong.

    The PRD: "7. Cross-references agree with one another, or
    `ERR_SUBJECT_REFERENCE_MISMATCH`. Both rows exist, so this is not a not-found
    condition; they simply do not belong together."

    Design: Corner/entities/consultation_subject_belonging_to_another_trust_rejected
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-P1"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-P01", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    unrelated = fx.create_trust(
        api,
        deal_name="CMBS 2026-Q1",
        closing_date="2026-03-15T00:00:00Z",
        original_controlling_class_balance_usd=25000000,
    )
    plan = fx.scored_plan(
        api, built["loan_id"], alternative_builders=[fx.add_modification_alternative]
    )
    fx.recommend_plan(api, plan["plan_id"], plan["plan"]["recommended_alternative_id"])

    response = api.create_consultation(
        f.plan_consultation_payload(unrelated["id"], plan["plan_id"]), ASSET_MANAGER
    )
    validate_error(response, e.ERR_SUBJECT_REFERENCE_MISMATCH, 422)

    unmoved = validate_success(api.get_workout_plan(plan["plan_id"], ASSET_MANAGER))
    a.assert_status(unmoved, "RECOMMENDED")

    consultation = validate_success(
        api.create_consultation(
            f.plan_consultation_payload(built["trust_id"], plan["plan_id"]),
            ASSET_MANAGER,
        ),
        201,
    )
    a.assert_status(consultation, "PENDING")
    a.assert_status(consultation, "CONSENT_RIGHT", "rights_type")
    assert consultation["trust_id"] == built["trust_id"]

    in_consultation = validate_success(
        api.get_workout_plan(plan["plan_id"], ASSET_MANAGER)
    )
    a.assert_status(in_consultation, "CONSULTATION")
    a.assert_status(in_consultation, "CONSENT_RIGHT", "consent_requirement")
