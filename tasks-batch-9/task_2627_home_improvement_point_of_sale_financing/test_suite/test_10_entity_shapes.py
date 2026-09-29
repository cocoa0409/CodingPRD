"""Entity shape, opening-value, immutability and identifier-resolution tests.

Every test here pins the *shape* of a record rather than a workflow outcome: the
fields a creation echoes back, the opening values a fresh row carries, the
defaults applied when optional inputs are omitted, the type constraints that
reject a malformed body, the versioning quartet every mutable resource carries
(and the one immutable event that carries only two of it), and the order in
which path and body identifiers are resolved.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import (
    assert_common_fields,
    assert_empty,
    assert_event_fields_only,
    assert_fields,
    assert_reason_codes,
    bps_of,
    ids_of,
    round_half_up,
)
from test_helpers.test_users import ADMIN_HEADERS, UNDERWRITER_ID, UNDERWRITER_HEADERS


# ─── entities/trade_rule_creation_returns_201_with_every_declared_field ───

def test_trade_rule_creation_echoes_every_declared_field_at_version_one(api):
    """Creating a trade rule answers 201 and echoes all seven declared fields at version 1.

    PRD: "Endpoints that bring a new resource into existence answer with HTTP 201; endpoints that read, modify, decide or drive the logical clock answer with HTTP 200."

    Design: Corner/entities/trade_rule_creation_returns_201_with_every_declared_field
    """
    before, before_meta = validate_paginated(api.list_trade_rules(ADMIN_HEADERS))
    assert before == []
    assert before_meta["total_count"] == 0

    created = validate_success(
        api.create_trade_rule(F.trade_rule_payload(), ADMIN_HEADERS), 201
    )
    assert_fields(created, **C.ROOFING_TRADE_RULE)
    assert_common_fields(created, expected_version=1)

    after, after_meta = validate_paginated(api.list_trade_rules(ADMIN_HEADERS))
    assert after_meta["total_count"] == 1
    assert ids_of(after) == [created["id"]]


# ─── entities/merchant_retrieval_returns_stored_and_computed_fields ───

def test_draft_merchant_opens_with_every_portfolio_figure_at_its_opening_value(api):
    """A freshly registered merchant reads back DRAFT with every derived figure at its opening value.

    PRD: "It begins life with `enrollment_status` set to `DRAFT` and with every portfolio and reserve figure at its opening value: `funded_volume_cents`, `holdback_reserve_cents`, `holdback_target_cents`, `settlement_offset_receivable_cents`, `program_write_off_cents`, `dispute_rate_bps`, `delinquency_rate_bps` and `phantom_risk_score` all at zero, `reserve_coverage_bps` at ten thousand, `portfolio_grade` at `A`, `risk_tier` at `STANDARD` and `termination_recommended` false."

    Design: Corner/entities/merchant_retrieval_returns_stored_and_computed_fields
    """
    merchant = S.register_merchant(api)
    read = validate_success(api.get_merchant(merchant["id"], ADMIN_HEADERS))

    assert_fields(read, id=merchant["id"], **C.CANONICAL_MERCHANT)
    assert_fields(
        read,
        enrollment_status="DRAFT",
        funded_volume_cents=0,
        holdback_reserve_cents=0,
        holdback_target_cents=0,
        settlement_offset_receivable_cents=0,
        program_write_off_cents=0,
        dispute_rate_bps=0,
        delinquency_rate_bps=0,
        phantom_risk_score=0,
        reserve_coverage_bps=10000,
        portfolio_grade="A",
        risk_tier="STANDARD",
        termination_recommended=False,
    )
    assert_empty(
        read,
        "attestation_ref",
        "approved_by_user_id",
        "approved_on",
        "suspension_reason_code",
        "termination_reason_code",
    )
    assert_common_fields(read, expected_version=1)


# ─── entities/merchant_listing_paginates_with_total_count_and_has_more ───

def test_merchant_listing_pages_report_total_count_and_has_more(api):
    """With three merchants stored, two pages of two report total_count 3 and flip has_more.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the number of records matching the filter before pagination is applied and `has_more` indicates whether records remain beyond the returned page."

    Design: Corner/entities/merchant_listing_paginates_with_total_count_and_has_more
    """
    first = S.register_merchant(api)
    second = S.register_merchant(api, legal_name="Bluebonnet Exteriors LLC",
                                 contact_email="ap@bluebonnet.example")
    third = S.register_merchant(api, legal_name="Lone Star Comfort Air",
                                trade_type="HVAC", contact_email="svc@lonestarair.example")

    page_one, meta_one = validate_paginated(
        api.list_merchants(ADMIN_HEADERS, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert_fields(meta_one, total_count=3, has_more=True, limit=2, offset=0)

    page_two, meta_two = validate_paginated(
        api.list_merchants(ADMIN_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert_fields(meta_two, total_count=3, has_more=False, limit=2, offset=2)

    seen = ids_of(page_one) + ids_of(page_two)
    assert len(seen) == len(set(seen))
    assert set(seen) == {first["id"], second["id"], third["id"]}


def test_merchant_listing_total_count_counts_only_the_filtered_trade_type(api):
    """A trade_type filter narrows total_count to the one matching merchant.

    PRD: "Merchants may be listed with filters on `enrollment_status`, `trade_type`, `risk_tier`, `portfolio_grade` and `termination_recommended`, which is how the risk desk finds the merchants the math has already condemned."

    Design: Corner/entities/merchant_listing_paginates_with_total_count_and_has_more
    """
    S.register_merchant(api)
    S.register_merchant(api, legal_name="Bluebonnet Exteriors LLC",
                        contact_email="ap@bluebonnet.example")
    hvac = S.register_merchant(api, legal_name="Lone Star Comfort Air",
                               trade_type="HVAC", contact_email="svc@lonestarair.example")

    rows, meta = validate_paginated(
        api.list_merchants(ADMIN_HEADERS, {"trade_type": "HVAC"})
    )
    assert_fields(meta, total_count=1, has_more=False)
    assert ids_of(rows) == [hvac["id"]]
    assert [row["trade_type"] for row in rows] == ["HVAC"]


# ─── entities/merchant_retrieval_of_unknown_id_returns_not_found ───

def test_merchant_retrieval_of_unknown_id_reports_merchant_not_found(api):
    """Reading a merchant id that was never minted is a 404 not-found, not an empty 200.

    PRD: "Identifiers are resolved strictly left to right, and the request fails on the first identifier that does not resolve, with the not-found code belonging to that identifier rather than to any identifier further right."

    Design: Corner/entities/merchant_retrieval_of_unknown_id_returns_not_found
    """
    real = S.register_merchant(api)

    response = api.get_merchant(NON_EXISTENT_UUID, ADMIN_HEADERS)
    validate_error(response, E.ERR_MERCHANT_NOT_FOUND)
    # PRD §2.2: the error envelope's `data` carries only `error_id` and `message`,
    # so no merchant resource leaks out of a not-found read.
    assert set(response.json()["data"]) == {"error_id", "message"}

    still_there = validate_success(api.get_merchant(real["id"], ADMIN_HEADERS))
    assert still_there["id"] == real["id"]


# ─── entities/promotion_plan_creation_missing_required_field_rejected ───

def test_promotion_plan_omitting_a_required_field_is_rejected_and_stores_nothing(api):
    """A plan body missing a required field is refused, and no plan row survives the attempt.

    PRD: "Payload well-formedness: the body parses, every required input field is present, every enumerated field carries a member of its declared set"

    Design: Corner/entities/promotion_plan_creation_missing_required_field_rejected
    """
    validate_error(
        api.create_promotion_plan(
            F.promotion_plan_payload(disclosure_template_version=None), ADMIN_HEADERS
        ),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_promotion_plan(
            F.promotion_plan_payload(max_ticket_cents=None), ADMIN_HEADERS
        ),
        E.ERR_INVALID_REQUEST,
    )

    rows, meta = validate_paginated(api.list_promotion_plans(ADMIN_HEADERS))
    assert rows == []
    assert meta["total_count"] == 0


# ─── entities/defaults_applied_when_optional_fields_are_omitted ───

def test_milestone_omitting_the_signoff_flag_defaults_it_to_true(api):
    """A milestone created without `requires_consumer_signoff` stores it as true.

    PRD: "It also carries `requires_consumer_signoff`, which defaults to true when omitted: when true, only the owning homeowner may sign the milestone off; when false, a `ServicingAgent` may sign it off as well."

    Design: Corner/entities/defaults_applied_when_optional_fields_are_omitted
    """
    scenario = S.project(api)

    created = validate_success(
        api.create_milestone(
            scenario.project_id, F.milestone_payload(), scenario.as_merchant
        ),
        201,
    )
    assert_fields(
        created,
        requires_consumer_signoff=True,
        sequence_no=1,
        release_pct_bps=3000,
        status="PENDING",
        rejection_count=0,
        is_funded=False,
    )
    assert_empty(created, "claimed_at", "verified_at", "evidence_ref")
    assert_common_fields(created, expected_version=1)


def test_project_opens_with_every_derived_figure_at_zero(api):
    """A project created with only its contract details opens with all five derived figures at zero.

    PRD: "A new project stands at `completion_status` `IN_PROGRESS`, with `verified_release_bps`, `settled_funded_cents`, `funded_pct_bps`, `max_fundable_now_cents` and `disputed_amount_cents` all at zero and both `completion_certificate_ref` and `certified_on` empty."

    Design: Corner/entities/defaults_applied_when_optional_fields_are_omitted
    """
    scenario = S.project(api)
    read = validate_success(api.get_project(scenario.project_id, ADMIN_HEADERS))

    assert_fields(
        read,
        completion_status="IN_PROGRESS",
        contract_amount_cents=C.CANONICAL_PROJECT["contract_amount_cents"],
        verified_release_bps=0,
        settled_funded_cents=0,
        funded_pct_bps=0,
        max_fundable_now_cents=0,
        disputed_amount_cents=0,
    )
    assert_empty(read, "completion_certificate_ref", "certified_on")
    assert_common_fields(read, expected_version=1)


def test_newly_filed_licence_stands_unverified_with_no_decision_recorded(api):
    """A licence filed alongside an existing one begins UNVERIFIED with no verifier recorded.

    PRD: "A newly filed licence stands at `verification_status` `UNVERIFIED`, with `verified_by_user_id` and `verified_on` empty."

    Design: Corner/entities/defaults_applied_when_optional_fields_are_omitted
    """
    scenario = S.approved_merchant(api)

    filed = validate_success(
        api.file_license(
            scenario.merchant_id,
            F.license_payload(
                license_number="TX-RCF-99001",
                effective_from="2027-06-30",
                expires_on="2028-06-30",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(
        filed,
        merchant_id=scenario.merchant_id,
        license_number="TX-RCF-99001",
        verification_status="UNVERIFIED",
        effective_from="2027-06-30",
        expires_on="2028-06-30",
    )
    assert_empty(filed, "verified_by_user_id", "verified_on")
    assert_common_fields(filed, expected_version=1)


def test_promotion_enrollment_is_born_active_at_the_negotiated_rate(api):
    """A promotion enrollment opens ACTIVE and keeps the negotiated discount it was given.

    PRD: "An enrollment is born `ACTIVE`."

    Design: Corner/entities/defaults_applied_when_optional_fields_are_omitted
    """
    scenario = S.enrolled_merchant(api)

    read = validate_success(
        api.get_promotion_enrollment(scenario.enrollment["id"], ADMIN_HEADERS)
    )
    assert_fields(
        read,
        status="ACTIVE",
        merchant_id=scenario.merchant_id,
        promotion_plan_id=scenario.plan_id,
        window_start_date=C.ENROLLMENT_WINDOW_START,
        window_end_date=C.ENROLLMENT_WINDOW_END,
        negotiated_discount_bps=C.NEGOTIATED_DISCOUNT_BPS,
    )
    assert_common_fields(read, expected_version=1)


# ─── entities/computed_decision_fields_are_absent_from_the_input_contract ───

def test_instant_decision_writes_the_tier_ceiling_rather_than_the_ticket(api):
    """The decision computes its own approval ceiling from the FICO tier, not from the ticket asked for.

    PRD: "When `project_amount_cents` is less than or equal to the ceiling, `decision` becomes `APPROVED`, `approved_limit_cents` is written as the **ceiling** rather than the ticket"

    Design: Corner/entities/computed_decision_fields_are_absent_from_the_input_contract
    """
    scenario = S.application(api)

    # FICO 742 lands in the 700-759 band: income factor 4500 bps, tier cap 5,000,000.
    ceiling = min(bps_of(C.CANONICAL_CONSUMER["annual_income_cents"], 4500), 5000000)
    assert ceiling == C.CANONICAL_APPROVED_LIMIT_CENTS  # 4,320,000

    assert_fields(
        scenario.application,
        merchant_id=scenario.merchant_id,
        consumer_id=scenario.consumer_id,
        promotion_plan_id=scenario.plan_id,
        project_amount_cents=C.CANONICAL_TICKET_CENTS,
        decision="APPROVED",
        approved_limit_cents=ceiling,
        disclosure_status="NOT_SENT",
    )
    assert_reason_codes(scenario.application, "WITHIN_LIMIT")
    assert_common_fields(scenario.application, expected_version=1)


def test_instant_decision_computes_the_dti_and_the_fourteen_day_offer_window(api):
    """The decision derives `decision_dti_bps` and an offer window fourteen days out from inputs alone.

    PRD: "The consumer's `existing_program_debt_cents` and the requested `project_amount_cents` are added together, multiplied by ten thousand, divided by `annual_income_cents`, and the quotient is rounded half up to a whole number of basis points; the result is written to `decision_dti_bps`."

    Design: Corner/entities/computed_decision_fields_are_absent_from_the_input_contract
    """
    scenario = S.application(api)

    # (0 + 3,500,000) * 10000 / 9,600,000 = 3645.83... -> 3646
    expected_dti = round_half_up(
        (0 + C.CANONICAL_TICKET_CENTS) * 10000,
        C.CANONICAL_CONSUMER["annual_income_cents"],
    )
    assert expected_dti == C.CANONICAL_DECISION_DTI_BPS

    assert_fields(scenario.application, decision_dti_bps=expected_dti)
    # The clock stands at 2026-08-01T00:00:00Z, so fourteen days out is 2026-08-15T00:00:00.
    assert scenario.application["offer_expires_at"][:19] == "2026-08-15T00:00:00"


# ─── entities/system_fields_are_server_minted_and_taken_from_the_path ───

def test_licence_parent_is_taken_from_the_path_and_never_from_the_body(api):
    """A licence body naming a different merchant is still filed under the merchant in the path.

    PRD: "The `merchant_id` recorded on the licence is always taken from the path and never from the body."

    Design: Corner/entities/system_fields_are_server_minted_and_taken_from_the_path
    """
    owner = S.register_merchant(api)
    other = S.register_merchant(api, legal_name="Bluebonnet Exteriors LLC",
                                contact_email="ap@bluebonnet.example")

    filed = validate_success(
        api.file_license(
            owner["id"], F.license_payload(merchant_id=other["id"]), ADMIN_HEADERS
        ),
        201,
    )
    assert_fields(filed, merchant_id=owner["id"], verification_status="UNVERIFIED")
    assert_common_fields(filed, expected_version=1)

    owned, _ = validate_paginated(api.list_licenses(owner["id"], ADMIN_HEADERS))
    assert ids_of(owned) == [filed["id"]]
    foreign, foreign_meta = validate_paginated(api.list_licenses(other["id"], ADMIN_HEADERS))
    assert foreign == []
    assert foreign_meta["total_count"] == 0

    # Filing a licence mutates no merchant, so the parent stays at its opening version.
    assert_fields(
        validate_success(api.get_merchant(owner["id"], ADMIN_HEADERS)),
        enrollment_status="DRAFT",
        version=1,
    )


# ─── entities/type_constraints_reject_bad_enums_negative_money_and_empty_intervals ───

def test_trade_rule_with_a_trade_type_outside_the_enum_is_rejected(api):
    """A trade_type that is not one of the five declared members is a malformed body.

    PRD: "The first is the **trade rule**, one row per trade the program serves, keyed by `trade_type`, which takes exactly one of `ROOFING`, `HVAC`, `SOLAR`, `WINDOWS` or `GENERAL_REMODEL`."

    Design: Corner/entities/type_constraints_reject_bad_enums_negative_money_and_empty_intervals
    """
    validate_error(
        api.create_trade_rule(
            F.trade_rule_payload(trade_type="PLUMBING"), ADMIN_HEADERS
        ),
        E.ERR_INVALID_REQUEST,
    )

    rows, meta = validate_paginated(api.list_trade_rules(ADMIN_HEADERS))
    assert rows == []
    assert meta["total_count"] == 0


def test_trade_rule_with_negative_money_is_rejected(api):
    """A negative `_cents` figure is refused as malformed rather than stored.

    PRD: "A request that supplies a negative value in any field whose name ends in `_cents` or `_bps` is rejected as malformed."

    Design: Corner/entities/type_constraints_reject_bad_enums_negative_money_and_empty_intervals
    """
    validate_error(
        api.create_trade_rule(F.trade_rule_payload(max_ticket_cents=-1), ADMIN_HEADERS),
        E.ERR_INVALID_REQUEST,
    )

    rows, meta = validate_paginated(api.list_trade_rules(ADMIN_HEADERS))
    assert rows == []
    assert meta["total_count"] == 0


def test_consumer_with_zero_annual_income_is_rejected(api):
    """A consumer whose stated income is zero is refused, since the field must exceed zero.

    PRD: "a stated `annual_income_cents` that must be strictly greater than zero"

    Design: Corner/entities/type_constraints_reject_bad_enums_negative_money_and_empty_intervals
    """
    validate_error(
        api.create_consumer(
            F.consumer_payload(full_name="Zero Income", annual_income_cents=0),
            ADMIN_HEADERS,
        ),
        E.ERR_INVALID_REQUEST,
    )


def test_licence_whose_interval_is_empty_is_a_date_range_error_not_a_malformed_body(api):
    """A licence whose `effective_from` equals its `expires_on` describes an empty half-open interval.

    PRD: "a licence must have `effective_from` strictly earlier than `expires_on`, because the interval is half-open and equal dates would describe an empty coverage period"

    Design: Corner/entities/type_constraints_reject_bad_enums_negative_money_and_empty_intervals
    """
    merchant = S.register_merchant(api)

    validate_error(
        api.file_license(
            merchant["id"],
            F.license_payload(effective_from="2026-06-01", expires_on="2026-06-01"),
            ADMIN_HEADERS,
        ),
        E.ERR_INVALID_DATE_RANGE,
    )

    rows, meta = validate_paginated(api.list_licenses(merchant["id"], ADMIN_HEADERS))
    assert rows == []
    assert meta["total_count"] == 0


# ─── entities/payment_is_immutable_with_no_version_and_no_mutation_endpoint ───

def test_payment_carries_only_id_and_created_at_with_no_version(api):
    """A posted payment is an event: it carries id and created_at and neither updated_at nor version.

    PRD: "The single exception is the `Payment` record, which is an immutable event rather than a mutable resource. A payment carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and no endpoint exists to modify or delete one."

    Design: Corner/entities/payment_is_immutable_with_no_version_and_no_mutation_endpoint
    """
    scenario = S.settled_draw(api, amount_cents=1050000)

    payment = validate_success(
        api.create_payment(
            F.payment_payload(scenario.loan_id, 400000), scenario.as_consumer
        ),
        201,
    )
    assert_event_fields_only(payment)

    rows, meta = validate_paginated(api.list_payments(scenario.loan_id, ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert ids_of(rows) == [payment["id"]]
    assert_event_fields_only(rows[0])


def test_payment_allocation_skips_unpayable_deferred_interest_and_bumps_the_account(api):
    """A payment on a promotional account allocates entirely to principal and increments the account.

    PRD: "The first bucket, `applied_to_capitalized_interest_cents`, takes the lesser of `amount_cents` and the account's `capitalized_interest_cents`; while `promo_status` is `PROMO_ACTIVE` this bucket is necessarily zero, since accrued promotional interest is not payable"

    Design: Corner/entities/payment_is_immutable_with_no_version_and_no_mutation_endpoint
    """
    scenario = S.settled_draw(api, amount_cents=1050000)

    # Origination minted the account at version 1; the settlement took it to 2.
    before = S.read_loan(api, scenario.loan_id)
    assert_fields(
        before,
        principal_balance_cents=1050000,
        capitalized_interest_cents=0,
        promo_status="PROMO_ACTIVE",
        version=2,
    )

    payment = validate_success(
        api.create_payment(
            F.payment_payload(scenario.loan_id, 400000), scenario.as_consumer
        ),
        201,
    )
    assert_fields(
        payment,
        loan_account_id=scenario.loan_id,
        amount_cents=400000,
        applied_to_capitalized_interest_cents=0,
        applied_to_principal_cents=400000,
        resulting_principal_balance_cents=1050000 - 400000,  # 650,000
        posted_on=C.DEFAULT_CLOCK_DATE,
        source_role="CONSUMER",
    )
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=650000,
        last_payment_on=C.DEFAULT_CLOCK_DATE,
        version=3,
    )


# ─── entities/license_under_unknown_merchant_and_cross_merchant_license_rejected ───

def test_licence_filed_under_an_unknown_merchant_reports_merchant_not_found(api):
    """Filing a licence under a merchant id that does not resolve fails on the path identifier.

    PRD: "A licence verification aimed at a merchant that does not exist therefore fails with `ERR_MERCHANT_NOT_FOUND` before the licence is ever looked up."

    Design: Corner/entities/license_under_unknown_merchant_and_cross_merchant_license_rejected
    """
    real = S.register_merchant(api)

    validate_error(
        api.file_license(NON_EXISTENT_UUID, F.license_payload(), ADMIN_HEADERS),
        E.ERR_MERCHANT_NOT_FOUND,
    )

    rows, meta = validate_paginated(api.list_licenses(real["id"], ADMIN_HEADERS))
    assert rows == []
    assert meta["total_count"] == 0


def test_verifying_a_licence_through_the_wrong_merchant_reports_licence_not_found(api):
    """A real licence reached through a different merchant's path does not resolve as that merchant's.

    PRD: "Containment counts as non-resolution: a `license_id` that names a real licence belonging to a different merchant fails with `ERR_LICENSE_NOT_FOUND`"

    Design: Corner/entities/license_under_unknown_merchant_and_cross_merchant_license_rejected
    """
    owner = S.register_merchant(api)
    other = S.register_merchant(api, legal_name="Bluebonnet Exteriors LLC",
                                contact_email="ap@bluebonnet.example")
    licence = S.file_license(api, owner["id"])

    validate_error(
        api.verify_license(
            other["id"],
            licence["id"],
            F.license_verification_payload("VERIFIED"),
            UNDERWRITER_HEADERS,
        ),
        E.ERR_LICENSE_NOT_FOUND,
    )

    rows, _ = validate_paginated(api.list_licenses(owner["id"], ADMIN_HEADERS))
    assert_fields(rows[0], id=licence["id"], verification_status="UNVERIFIED", version=1)
    assert_empty(rows[0], "verified_by_user_id", "verified_on")


def test_licence_verification_through_the_right_parent_records_the_deciding_underwriter(api):
    """Reached through its own merchant, the licence verifies and records who decided it and when.

    PRD: "Either decision writes `verified_by_user_id` from the acting operator's identifier and `verified_on` from the logical clock."

    Design: Corner/entities/license_under_unknown_merchant_and_cross_merchant_license_rejected
    """
    owner = S.register_merchant(api)
    licence = S.file_license(api, owner["id"])

    verified = validate_success(
        api.verify_license(
            owner["id"],
            licence["id"],
            F.license_verification_payload("VERIFIED"),
            UNDERWRITER_HEADERS,
        )
    )
    assert_fields(
        verified,
        id=licence["id"],
        merchant_id=owner["id"],
        verification_status="VERIFIED",
        verified_by_user_id=UNDERWRITER_ID,
        version=2,
    )
    # The clock stands at 2026-08-01T00:00:00Z on a freshly booted server.
    assert verified["verified_on"][:10] == C.DEFAULT_CLOCK_DATE


# ─── entities/flat_topology_body_foreign_keys_validated_in_declaration_order ───

def test_body_foreign_keys_resolve_in_declaration_order_reporting_the_consumer_first(api):
    """With both the consumer and the plan unknown, the consumer is reported because it is declared first.

    PRD: "Foreign keys carried in a request body are resolved after path identifiers, and among themselves in the order in which they are declared in the payload: `consumer_id`, then `merchant_id`, then `promotion_plan_id`, then `loan_account_id`, then `project_milestone_id`, then `project_id`, then `reopens_case_id`."

    Design: Corner/entities/flat_topology_body_foreign_keys_validated_in_declaration_order
    """
    scenario = S.enrolled_merchant(api)
    unknown_consumer = "00000000-0000-4000-8000-0000000000c1"
    unknown_plan = "00000000-0000-4000-8000-0000000000d1"

    validate_error(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id, unknown_consumer, unknown_plan
            ),
            scenario.as_merchant,
        ),
        E.ERR_CONSUMER_NOT_FOUND,
    )

    rows, meta = validate_paginated(api.list_credit_applications(ADMIN_HEADERS))
    assert rows == []
    assert meta["total_count"] == 0


def test_body_foreign_key_resolution_reports_the_plan_once_the_consumer_resolves(api):
    """With a real consumer and an unknown plan, resolution moves on and reports the plan.

    PRD: "Foreign keys carried in a request body are resolved after path identifiers, and among themselves in the order in which they are declared in the payload: `consumer_id`, then `merchant_id`, then `promotion_plan_id`, then `loan_account_id`, then `project_milestone_id`, then `project_id`, then `reopens_case_id`."

    Design: Corner/entities/flat_topology_body_foreign_keys_validated_in_declaration_order
    """
    scenario = S.enrolled_merchant(api)
    consumer = S.register_consumer(api, scenario.merchant_id)

    validate_error(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id,
                consumer["id"],
                "00000000-0000-4000-8000-0000000000d1",
            ),
            scenario.as_merchant,
        ),
        E.ERR_PROMOTION_PLAN_NOT_FOUND,
    )

    created = validate_success(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id, consumer["id"], scenario.plan_id
            ),
            scenario.as_merchant,
        ),
        201,
    )
    assert_fields(
        created,
        decision="APPROVED",
        approved_limit_cents=C.CANONICAL_APPROVED_LIMIT_CENTS,
    )
