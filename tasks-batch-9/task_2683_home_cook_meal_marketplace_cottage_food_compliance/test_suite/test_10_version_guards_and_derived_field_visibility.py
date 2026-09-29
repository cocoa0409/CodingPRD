"""The two optimistic-concurrency guards, and the requirement that the derived
consequences of a write are already visible when it returns.

Every test builds its own world from scratch: the harness restarts the API
server before each test, so nothing here may rely on another test's data.
"""

from test_helpers import (
    ADMIN_HEADERS,
    FINANCE_ONE_HEADERS,
    assert_fields,
    assert_refund_three_bucket_identity,
    factories,
    fixtures as fx,
    is_iso8601_timestamp,
    make_cook_headers,
    validate_error,
    validate_paginated,
)


# ==========================================================================
# Guard one: expected_cook_version on onboarding-document submission
# ==========================================================================
def test_01_onboarding_document_submission_rejects_a_spent_cook_version(api):
    """Re-using the cook version that the first submission consumed is a 412, and it writes nothing.

    PRD: "If it does not equal that cook's current `version`, the submission is rejected with `ERR_STALE_COOK_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_complexity_layers/onboarding_document_write_rejects_a_stale_cook_version
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    assert_fields(cook, version=1, onboarding_status="DRAFT")
    token = cook["version"]

    first = fx.submit_food_handler_cert(
        api,
        cook,
        expected_version=token,
        certificate_number="FH-A",
        issued_on="2026-01-15",
        expires_on="2028-01-15",
    )
    assert_fields(first, review_status="SUBMITTED", superseded_by_document_id=None)

    # The accepted write moved the parent, which is exactly what spends the token.
    after_first = fx.read_cook(api, cook["id"])
    assert_fields(after_first, onboarding_status="DOCS_SUBMITTED", version=token + 1)

    resp = api.create_onboarding_document(
        factories.food_handler_cert_payload(
            cook["id"],
            token,
            certificate_number="FH-B",
            issued_on="2026-02-15",
            expires_on="2028-02-15",
        ),
        make_cook_headers(cook["id"]),
    )
    validate_error(resp, "ERR_STALE_COOK_VERSION", 412)

    # The refused write superseded nothing and created no row.
    assert_fields(
        fx.read_document(api, first["id"]),
        review_status="SUBMITTED",
        superseded_by_document_id=None,
    )
    rows, meta = validate_paginated(
        api.list_onboarding_documents(ADMIN_HEADERS, {"cook_id": cook["id"]})
    )
    assert meta["total_count"] == 1, f"the 412 attempt must not have created a row: {rows}"


def test_02_resubmission_with_a_re_read_cook_version_supersedes_the_prior_document(api):
    """Once the caller re-reads the cook version the submission lands and supersedes the older row.

    PRD: "Submission is also a **superseding** write: if the cook already holds a document of that same `doc_type` in any of `SUBMITTED`, `VERIFIED`, `REJECTED`, `PASSED`, `FAILED` or `WAIVED`, that older row moves to `SUPERSEDED` and its `superseded_by_document_id` is set to the new row's `id`, forming a self-referential supersession chain that remains fully queryable."
    Design: Corner/cross_cutting_complexity_layers/onboarding_document_write_rejects_a_stale_cook_version
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")

    first = fx.submit_food_handler_cert(
        api,
        cook,
        expected_version=cook["version"],
        certificate_number="FH-A",
        issued_on="2026-01-15",
        expires_on="2028-01-15",
    )
    fresh_token = fx.cook_version(api, cook["id"])
    assert fresh_token == cook["version"] + 1

    second = fx.submit_food_handler_cert(
        api,
        cook,
        expected_version=fresh_token,
        certificate_number="FH-B",
        issued_on="2026-02-15",
        expires_on="2028-02-15",
    )
    assert_fields(second, review_status="SUBMITTED", superseded_by_document_id=None)

    assert_fields(
        fx.read_document(api, first["id"]),
        review_status="SUPERSEDED",
        superseded_by_document_id=second["id"],
    )
    # The token is single-use: the accepted write advanced the cook again.
    assert fx.cook_version(api, cook["id"]) > fresh_token

    rows, meta = validate_paginated(
        api.list_onboarding_documents(
            ADMIN_HEADERS, {"cook_id": cook["id"], "superseded_by_document_id": second["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


# ==========================================================================
# Guard two: expected_production_window_version on payout-statement creation
# ==========================================================================
def test_03_payout_statement_creation_rejects_a_spent_window_version(api):
    """Drafting bumps the window version, so a second draft on the same token is a 412.

    PRD: "If it does not equal that window's current `version`, the creation is rejected with `ERR_STALE_WINDOW_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_complexity_layers/payout_statement_creation_rejects_a_stale_window_version
    """
    fx.reset_clock(api)
    setup = fx.handed_off_order_scenario(
        api, quantity=2, item_overrides={"unit_price_cents": 400}
    )
    fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)
    window = fx.read_window(api, setup.window["id"])
    assert window["status"] == "CLOSED"
    token = window["version"]

    first = fx.draft_payout_statement(
        api, setup.cook_id, window["id"], basis="ACCRUAL_WINDOW", expected_version=token
    )
    assert_fields(
        first,
        status="DRAFT",
        included_order_count=1,
        gross_sales_cents=800,
        tier_rate=0.225,
        commission_cents=180,
        refund_chargeback_cents=0,
        safety_hold_cents=0,
        net_payout_cents=620,
        finalized_at=None,
        paid_at=None,
        superseded_at=None,
    )

    resp = api.create_payout_statement(
        factories.payout_statement_payload(
            setup.cook_id, window["id"], token, basis="CASH_HANDOFF"
        ),
        FINANCE_ONE_HEADERS,
    )
    validate_error(resp, "ERR_STALE_WINDOW_VERSION", 412)

    # The refused draft neither superseded the live one nor created a second row.
    assert_fields(fx.read_statement(api, first["id"]), status="DRAFT", superseded_at=None)
    assert fx.window_version(api, window["id"]) == token + 1
    rows, meta = validate_paginated(
        api.list_payout_statements(
            FINANCE_ONE_HEADERS,
            {"cook_id": setup.cook_id, "production_window_id": window["id"]},
        )
    )
    assert meta["total_count"] == 1, f"the 412 attempt must not have created a row: {rows}"


def test_04_redrafting_with_a_re_read_window_version_supersedes_the_prior_draft(api):
    """The retry on a fresh token lands and moves the earlier DRAFT to SUPERSEDED with a stamp.

    PRD: "A new statement is created in `status` `DRAFT` with null `finalized_at`, `paid_at` and `superseded_at`, and it supersedes its predecessors: any prior statement for the same cook-and-window pair sitting in `DRAFT` moves `DRAFT → SUPERSEDED` and stamps `superseded_at` from the logical clock."
    Design: Corner/cross_cutting_complexity_layers/payout_statement_creation_rejects_a_stale_window_version
    """
    fx.reset_clock(api)
    setup = fx.handed_off_order_scenario(
        api, quantity=2, item_overrides={"unit_price_cents": 400}
    )
    fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)
    window = fx.read_window(api, setup.window["id"])

    first = fx.draft_payout_statement(
        api,
        setup.cook_id,
        window["id"],
        basis="ACCRUAL_WINDOW",
        expected_version=window["version"],
    )
    fresh_token = fx.window_version(api, window["id"])
    assert fresh_token == window["version"] + 1

    second = fx.draft_payout_statement(
        api, setup.cook_id, window["id"], basis="CASH_HANDOFF", expected_version=fresh_token
    )
    assert_fields(
        second,
        status="DRAFT",
        basis="CASH_HANDOFF",
        gross_sales_cents=800,
        net_payout_cents=620,
        superseded_at=None,
    )

    superseded = fx.read_statement(api, first["id"])
    assert_fields(superseded, status="SUPERSEDED")
    assert is_iso8601_timestamp(superseded["superseded_at"]), (
        f"superseded_at must be stamped: {superseded['superseded_at']!r}"
    )

    rows, meta = validate_paginated(
        api.list_payout_statements(
            FINANCE_ONE_HEADERS,
            {"cook_id": setup.cook_id, "production_window_id": window["id"]},
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert {row["status"] for row in rows} == {"SUPERSEDED", "DRAFT"}


# ==========================================================================
# Every derived field is already visible in the response that caused it
# ==========================================================================
def test_05_adjudication_response_and_the_rescored_cook_agree_on_the_first_read(api):
    """SUBSTANTIATE returns the terminal incident and the cook is already re-scored.

    PRD: "A `decision` of `SUBSTANTIATE` moves the report `TRIAGED → SUBSTANTIATED`, stamps `adjudicated_by_user_id`, `adjudicated_at` and `resolution_note`, recomputes the cook's authoritative `safety_score`, and lets the recomputed score drive the cook's standing dimension along whichever of `CLEAR → WARNED`, `CLEAR → SUSPENDED` or `WARNED → SUSPENDED` the new score selects; when the score selects suspension, the full suspension cascade of §2.9 follows — approved dishes delisted, open windows cancelled, their orders cancelled and voided, `pending_payout_cents` recomputed — and the cook's `version` is incremented."
    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_response_that_caused_it
    """
    fx.reset_clock(api)
    setup = fx.handed_off_order_scenario(
        api, quantity=2, item_overrides={"unit_price_cents": 400}
    )
    order = fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)
    order = fx.read_order(api, order["id"])
    assert_fields(
        order,
        fulfillment_status="DELIVERED",
        payment_status="CAPTURED",
        subtotal_cents=800,
        platform_commission_cents=180,
        cook_earnings_cents=620,
        total_charge_cents=872,
    )

    incident = fx.report_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=order["id"],
        category="FOODBORNE_ILLNESS",
        severity="MODERATE",
        description="diner reported illness",
        occurred_at="2026-08-08T19:00:00Z",
    )
    fx.triage_incident(api, incident["id"], "ACCEPT")

    adjudicated = fx.adjudicate_incident(
        api, incident["id"], "SUBSTANTIATE", resolution_note="confirmed by the state lab"
    )
    assert_fields(
        adjudicated,
        status="SUBSTANTIATED",
        severity_points=12,
        resolution_note="confirmed by the state lab",
    )
    assert is_iso8601_timestamp(adjudicated["adjudicated_at"]), (
        f"adjudicated_at must be stamped on the adjudication response: {adjudicated}"
    )

    # First read of a different entity: the re-score is not deferred.
    assert_fields(
        fx.read_cook(api, setup.cook_id), safety_score=88, compliance_standing="CLEAR"
    )


def test_06_refund_response_carries_its_own_three_bucket_split(api):
    """A PLATFORM-fault refund returns its split immediately, sparing the cook bucket entirely.

    PRD: "When `fault_party` is `PLATFORM`, the cook is spared entirely: `cook_chargeback_cents` is zero, `commission_reversed_cents` is the lesser of the full refund amount and the commission bucket's capacity, and `platform_absorbed_cents` takes the remainder."
    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_response_that_caused_it
    """
    fx.reset_clock(api)
    setup = fx.handed_off_order_scenario(
        api, quantity=2, item_overrides={"unit_price_cents": 400}
    )
    order = fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)
    incident = fx.substantiated_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=order["id"],
        category="FOODBORNE_ILLNESS",
        severity="MODERATE",
    )

    refund = fx.record_refund(
        api,
        order["id"],
        reason="SAFETY",
        fault_party="PLATFORM",
        refund_amount_cents=100,
        settle_immediately=True,
        safety_incident_id=incident["id"],
    )
    assert_fields(
        refund,
        status="SETTLED",
        fault_party="PLATFORM",
        refund_amount_cents=100,
        cook_chargeback_cents=0,
        commission_reversed_cents=100,
        platform_absorbed_cents=0,
        created_by_user_id="fin-1",
    )
    assert_refund_three_bucket_identity(refund)
    assert is_iso8601_timestamp(refund["settled_at"]), (
        f"settle_immediately must stamp settled_at: {refund['settled_at']!r}"
    )


def test_07_order_and_cook_ledger_have_already_moved_when_the_refund_returns(api):
    """The order's refund counters and the cook's recognised revenue are right on the first read.

    PRD: "Every one of those transitions accumulates `refunded_cents`, `cook_chargeback_cents`, `commission_reversed_cents` and `platform_absorbed_cents` on the order from this refund's own bucket allocations, and recomputes the cook's `ytd_cottage_revenue_cents`, `cap_status` and `pending_payout_cents`."
    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_response_that_caused_it
    """
    fx.reset_clock(api)
    setup = fx.handed_off_order_scenario(
        api, quantity=2, item_overrides={"unit_price_cents": 400}
    )
    order = fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)
    incident = fx.substantiated_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=order["id"],
        category="FOODBORNE_ILLNESS",
        severity="MODERATE",
    )
    fx.record_refund(
        api,
        order["id"],
        reason="SAFETY",
        fault_party="PLATFORM",
        refund_amount_cents=100,
        settle_immediately=True,
        safety_incident_id=incident["id"],
    )

    assert_fields(
        fx.read_order(api, order["id"]),
        fulfillment_status="DELIVERED",
        payment_status="PARTIALLY_REFUNDED",
        refunded_cents=100,
        cook_chargeback_cents=0,
        commission_reversed_cents=100,
        platform_absorbed_cents=0,
    )
    # 800 recognised less the 100 reversed commission; the cook bucket was untouched,
    # so pending_payout_cents stays at cook_earnings_cents.
    assert_fields(
        fx.read_cook(api, setup.cook_id),
        ytd_cottage_revenue_cents=700,
        ytd_gross_sales_cents=800,
        pending_payout_cents=620,
        cap_status="UNDER_CAP",
    )


def test_08_compliance_summary_reflects_the_refund_and_the_rescore_immediately(api):
    """The computed summary agrees with the writes on its first read, and re-reading changes nothing.

    PRD: "The response reports `cook_id`, the authoritative `safety_score` beside the advisory `provisional_safety_score`, the current `compliance_standing` and `cap_status`, the recognised `ytd_cottage_revenue_cents`, a `cap_remaining_cents` giving the headroom left under the state's annual cap, an `open_incident_count` covering incidents in `INTAKE` or `TRIAGED`, a `substantiated_incident_count`, and an `approved_menu_item_count`."
    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_response_that_caused_it
    """
    fx.reset_clock(api)
    setup = fx.handed_off_order_scenario(
        api, quantity=2, item_overrides={"unit_price_cents": 400}
    )
    order = fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)
    incident = fx.substantiated_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=order["id"],
        category="FOODBORNE_ILLNESS",
        severity="MODERATE",
    )
    fx.record_refund(
        api,
        order["id"],
        reason="SAFETY",
        fault_party="PLATFORM",
        refund_amount_cents=100,
        settle_immediately=True,
        safety_incident_id=incident["id"],
    )

    summary = fx.read_compliance_summary(api, setup.cook_id)
    assert_fields(
        summary,
        cook_id=setup.cook_id,
        safety_score=88,
        provisional_safety_score=88,
        compliance_standing="CLEAR",
        cap_status="UNDER_CAP",
        ytd_cottage_revenue_cents=700,
        cap_remaining_cents=4_999_300,
        open_incident_count=0,
        substantiated_incident_count=1,
        approved_menu_item_count=1,
    )

    # There is no lag to observe: a second read returns the identical projection.
    again = fx.read_compliance_summary(api, setup.cook_id)
    assert again == summary
