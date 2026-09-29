"""The endpoint surface itself: the fee ledger's create-read-list-collect round
trip, the report's two-step action chain over a frozen snapshot, the partial
bulk sweep, the polymorphic consultation link, the purely derived asset business
plan read, and the waiver that releases an accrual period.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ASSET_MANAGER,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    PLATFORM_ADMIN,
    TRUSTEE,
    make_borrower_headers,
    make_controlling_class_representative_headers,
)


# ==========================================================================
# The fee ledger: create, read, list, collect
# ==========================================================================
def _loan_on_the_default_fee_convention(api, deal_name, loan_number):
    """A 10,000,000.00 loan under a trust on the 0.25% STATED_PRINCIPAL default."""
    trust = fx.create_trust(api, deal_name=deal_name)
    loan = fx.create_mid_size_loan(api, trust["id"], loan_number=loan_number)
    a.assert_money(loan["fees_payable_usd"], 0.00, "fees_payable_usd")
    return trust["id"], loan["id"]


def _monthly_accrual(api, loan_id, period_start, period_end, headers):
    return validate_success(
        api.create_fee_accrual(
            f.special_servicing_fee_payload(
                loan_id, period_start=period_start, period_end=period_end
            ),
            headers,
        ),
        201,
    )


def test_two_monthly_accruals_are_created_read_back_and_paged_one_by_one(api):
    """Either fee-creating role may accrue, and the list pages in creation order.

    The PRD: "Accruals are created by either the `MasterServicer` or the
    `SpecialServicerAssetManager`, naming the `loan_id` and the `fee_type`, and
    the remaining body fields are conditional on the type."

    Design: Corner/endpoints/fee_accrual_create_read_list_and_collect_round_trip
    """
    _, loan_id = _loan_on_the_default_fee_convention(api, "CMBS 2026-V28", "L-V28")

    june = _monthly_accrual(
        api, loan_id, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", MASTER_SERVICER
    )
    july = _monthly_accrual(
        api, loan_id, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", ASSET_MANAGER
    )
    for accrual, accruer in ((june, "ms-001"), (july, "amgr-001")):
        a.assert_status(accrual, "ACCRUED")
        a.assert_money(accrual["basis_amount_usd"], 10000000.00, "basis_amount_usd")
        a.assert_rate_pct(accrual["rate_pct"], 0.020833)
        a.assert_money(accrual["amount_usd"], 2083.33, "amount_usd")
        assert accrual["accrued_by_user_id"] == accruer
        a.assert_fields_null(accrual, "collected_on", "waived_reason")

    loan = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_money(loan["fees_payable_usd"], 4166.66, "fees_payable_usd")

    read_back = validate_success(api.get_fee_accrual(june["id"], MASTER_SERVICER))
    assert read_back["id"] == june["id"]
    assert read_back["period_start"].startswith("2026-06-01")
    assert read_back["period_end"].startswith("2026-06-30")
    a.assert_money(read_back["amount_usd"], 2083.33, "amount_usd")

    first_page, first_meta = validate_paginated(
        api.list_fee_accruals(MASTER_SERVICER, {"loan_id": loan_id, "limit": 1, "offset": 0})
    )
    assert a.ids_of(first_page) == [june["id"]]
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_fee_accruals(MASTER_SERVICER, {"loan_id": loan_id, "limit": 1, "offset": 1})
    )
    assert a.ids_of(second_page) == [july["id"]]
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False


def test_collecting_one_accrual_leaves_only_the_other_one_payable(api):
    """The status endpoint is the only mutation path, and it moves the ledger.

    The PRD: "The `MasterServicer` collects it, `ACCRUED → COLLECTED`, which
    stamps `collected_on` with the current logical clock and removes the fee from
    the loan's `fees_payable_usd`; both the accrual's and the loan's `version`
    advance by one."

    Design: Corner/endpoints/fee_accrual_create_read_list_and_collect_round_trip
    """
    _, loan_id = _loan_on_the_default_fee_convention(api, "CMBS 2026-V28", "L-V28")
    june = _monthly_accrual(
        api, loan_id, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", MASTER_SERVICER
    )
    july = _monthly_accrual(
        api, loan_id, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", ASSET_MANAGER
    )

    collected = validate_success(
        api.set_fee_accrual_status(
            june["id"], f.status_payload("COLLECTED"), MASTER_SERVICER
        )
    )
    a.assert_status(collected, "COLLECTED")
    assert collected["collected_on"].startswith("2026-08-01")
    a.assert_money(collected["amount_usd"], 2083.33, "amount_usd")
    a.assert_version_advanced_by(june, collected, 1, "fee accrual")

    loan = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_money(loan["fees_payable_usd"], 2083.33, "fees_payable_usd")

    still_accrued = validate_success(api.get_fee_accrual(july["id"], MASTER_SERVICER))
    a.assert_status(still_accrued, "ACCRUED")
    a.assert_fields_null(still_accrued, "collected_on")


# ==========================================================================
# The report's action chain over a snapshot that must not move
# ==========================================================================
def _report_in_draft_over_one_special_serviced_loan(api):
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V29"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V29"},
        event_factory=lambda client, loan_id: fx.record_bankruptcy_event(
            client, loan_id, occurred_on="2026-07-01T00:00:00Z"
        ),
    )
    report = fx.create_distribution_report(
        api, built["trust_id"], period_end="2026-07-31T00:00:00Z"
    )
    return built["trust_id"], built["loan_id"], report


def test_the_five_snapshot_figures_do_not_track_later_trust_activity(api):
    """A 60,000.00 advance moves the trust and leaves the report where it was.

    The PRD: "At creation the service freezes five figures off the trust row so
    that later trust activity cannot retroactively change what was reported:
    `loans_in_special_count` from the trust's count of loans in special servicing,
    `total_ara_snapshot_usd` from its `total_ara_usd`,
    `total_advances_outstanding_snapshot_usd` from its
    `total_advances_outstanding_usd`, `realized_loss_snapshot_usd` from its
    `realized_loss_usd`, and `control_status_snapshot` from its `control_status`,
    which is therefore either `CONTROLLING` or `CONSULTING_ONLY`."

    Design: Corner/endpoints/distribution_report_certify_then_distribute_action_chain
    """
    trust_id, loan_id, report = _report_in_draft_over_one_special_serviced_loan(api)
    a.assert_status(report, "DRAFT")
    assert report["loans_in_special_count"] == 1
    a.assert_money(report["total_ara_snapshot_usd"], 0.00, "total_ara_snapshot_usd")
    a.assert_money(
        report["total_advances_outstanding_snapshot_usd"],
        0.00,
        "total_advances_outstanding_snapshot_usd",
    )
    a.assert_money(report["realized_loss_snapshot_usd"], 0.00, "realized_loss_snapshot_usd")
    a.assert_status(report, "CONTROLLING", "control_status_snapshot")
    a.assert_fields_null(report, "recipients", "certified_by_user_id", "distributed_at")

    fx.record_advance(
        api,
        loan_id,
        advance_type="PI_ADVANCE",
        amount_usd=60000,
        advanced_on="2026-07-01T00:00:00Z",
    )
    trust = fx.read_trust(api, trust_id, TRUSTEE)
    a.assert_money(
        trust["total_advances_outstanding_usd"], 60000.00, "total_advances_outstanding_usd"
    )

    frozen = validate_success(api.get_distribution_report(report["id"], TRUSTEE))
    a.assert_money(
        frozen["total_advances_outstanding_snapshot_usd"],
        0.00,
        "total_advances_outstanding_snapshot_usd",
    )
    assert frozen["version"] == report["version"], (
        "trust activity does not write to the report row"
    )


def test_an_empty_recipient_list_is_refused_between_certify_and_distribute(api):
    """The action chain runs certify then distribute, and the empty array fails.

    The PRD: "Distribution, `CERTIFIED → DISTRIBUTED`, requires a `recipients`
    array in the body that is present, non-empty, and drawn entirely from
    `TRUSTEE`, `RATING_AGENCIES`, `CERTIFICATE_HOLDERS` and
    `CONTROLLING_CLASS_REPRESENTATIVE`; an empty array or an unrecognised member
    is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/distribution_report_certify_then_distribute_action_chain
    """
    trust_id, _, report = _report_in_draft_over_one_special_serviced_loan(api)

    certified = fx.set_report_status(api, report["id"], "CERTIFIED")
    a.assert_status(certified, "CERTIFIED")
    assert certified["certified_by_user_id"] == "trustee-001"
    a.assert_version_advanced_by(report, certified, 1, "distribution report")
    a.assert_money(
        certified["total_advances_outstanding_snapshot_usd"],
        0.00,
        "total_advances_outstanding_snapshot_usd",
    )

    response = api.set_distribution_report_status(
        report["id"], f.status_payload("DISTRIBUTED", recipients=[]), TRUSTEE
    )
    validate_error(response, e.ERR_INVALID_REQUEST, 400)
    unchanged = validate_success(api.get_distribution_report(report["id"], TRUSTEE))
    a.assert_status(unchanged, "CERTIFIED")
    a.assert_fields_null(unchanged, "recipients", "distributed_at")
    assert unchanged["version"] == certified["version"]

    recipients = ["TRUSTEE", "RATING_AGENCIES", "CERTIFICATE_HOLDERS"]
    distributed = validate_success(
        api.set_distribution_report_status(
            report["id"], f.status_payload("DISTRIBUTED", recipients=recipients), TRUSTEE
        )
    )
    a.assert_status(distributed, "DISTRIBUTED")
    assert distributed["distributed_at"].startswith("2026-08-01")
    assert distributed["recipients"] == recipients
    a.assert_version_advanced_by(certified, distributed, 1, "distribution report")

    rows, meta = validate_paginated(
        api.list_distribution_reports(
            make_controlling_class_representative_headers(trust_id),
            {"trust_id": trust_id, "status": "DISTRIBUTED"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == report["id"]


# ==========================================================================
# The bulk sweep: partial application, ordered, idempotent
# ==========================================================================
def _consultation_on_a_recommended_plan(api, trust_id, loan_number, builder, **loan_overrides):
    """Board a loan, recommend a plan on it and issue the consultation."""
    loan = fx.create_mid_size_loan(api, trust_id, loan_number=loan_number, **loan_overrides)
    fx.record_bankruptcy_event(api, loan["id"], occurred_on="2026-08-01T00:00:00Z")
    fx.transfer_to_special_servicing(api, loan["id"])
    built = fx.scored_plan(api, loan["id"], alternative_builders=[builder])
    fx.recommend_plan(api, built["plan_id"], built["alternative_ids"][0])
    consultation = fx.issue_plan_consultation(api, trust_id, built["plan_id"])
    return built["plan_id"], consultation


def _modification_route(cash_flows, upfront_cost_usd):
    return lambda client, plan_id: fx.add_modification_alternative(
        client,
        plan_id,
        projected_cash_flows=cash_flows,
        upfront_cost_usd=upfront_cost_usd,
    )


def _three_pending_consultations_across_two_trusts(api):
    """Trust A holds two consultations expiring 09-16 and 09-17; trust B one at 09-24."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    trust_a = fx.create_trust(api, deal_name="CMBS 2026-V30")
    trust_b = fx.create_trust(
        api,
        deal_name="CMBS 2026-V31",
        closing_date="2026-02-15T00:00:00Z",
        original_controlling_class_balance_usd=30000000,
    )

    plan_a1, consult_a1 = _consultation_on_a_recommended_plan(
        api,
        trust_a["id"],
        "L-V30-A1",
        _modification_route(
            [
                {"period_index": 1, "amount_usd": 900000},
                {"period_index": 2, "amount_usd": 9100000},
            ],
            120000,
        ),
    )

    fx.set_clock(api, "2026-09-02T00:00:00Z")
    plan_a2, consult_a2 = _consultation_on_a_recommended_plan(
        api,
        trust_a["id"],
        "L-V30-A2",
        lambda client, plan_id: fx.add_note_sale_alternative(
            client,
            plan_id,
            projected_cash_flows=[{"period_index": 1, "amount_usd": 6500000}],
            upfront_cost_usd=70000,
        ),
        original_balance_usd=8000000,
        current_principal_balance_usd=7000000,
        note_rate_pct=5.75,
        monthly_debt_service_usd=45000,
        maturity_date="2029-09-01T00:00:00Z",
        securitization_value_usd=9000000,
    )

    fx.set_clock(api, "2026-09-10T00:00:00Z")
    plan_b1, consult_b1 = _consultation_on_a_recommended_plan(
        api,
        trust_b["id"],
        "L-V31-B1",
        _modification_route(
            [
                {"period_index": 1, "amount_usd": 500000},
                {"period_index": 2, "amount_usd": 4600000},
            ],
            60000,
        ),
        original_balance_usd=6000000,
        current_principal_balance_usd=5000000,
        note_rate_pct=5.5,
        monthly_debt_service_usd=31000,
        maturity_date="2030-01-01T00:00:00Z",
        securitization_value_usd=7000000,
    )
    return {
        "trust_b_id": trust_b["id"],
        "plans": {"a1": plan_a1, "a2": plan_a2, "b1": plan_b1},
        "consultations": {"a1": consult_a1, "a2": consult_a2, "b1": consult_b1},
    }


def test_one_unfiltered_sweep_deems_the_expired_rows_and_skips_the_live_one(api):
    """The sweep applies partially, in deadline order, and never twice.

    The PRD: "The sweep may be narrowed to one trust by supplying `trust_id`,
    processes matching consultations in `deadline_at` ascending order with
    `created_at` ascending as the tie-break, and reports `swept_count` together
    with `deemed_consented_ids`, the identifiers it swept."

    Design: Corner/endpoints/consultation_sweep_deems_only_the_expired_pending_rows
    """
    scenario = _three_pending_consultations_across_two_trusts(api)
    consultations = scenario["consultations"]
    assert consultations["a1"]["deadline_at"].startswith("2026-09-16T23:59:59.999")
    assert consultations["a2"]["deadline_at"].startswith("2026-09-17T23:59:59.999")
    assert consultations["b1"]["deadline_at"].startswith("2026-09-24T23:59:59.999")

    early = validate_success(
        api.sweep_consultations({"trust_id": scenario["trust_b_id"]}, PLATFORM_ADMIN)
    )
    assert early["swept_count"] == 0
    assert early["deemed_consented_ids"] == []

    fx.set_clock(api, "2026-09-18T00:00:00Z")
    swept = validate_success(api.sweep_consultations({}, PLATFORM_ADMIN))
    assert swept["swept_count"] == 2
    assert swept["deemed_consented_ids"] == [
        consultations["a1"]["id"],
        consultations["a2"]["id"],
    ]

    for key in ("a1", "a2"):
        deemed = validate_success(
            api.get_consultation(consultations[key]["id"], ASSET_MANAGER)
        )
        a.assert_status(deemed, "DEEMED_CONSENTED")
        plan = validate_success(api.get_workout_plan(scenario["plans"][key], ASSET_MANAGER))
        a.assert_status(plan, "CONSENT_SATISFIED")

    untouched = validate_success(
        api.get_consultation(consultations["b1"]["id"], ASSET_MANAGER)
    )
    a.assert_status(untouched, "PENDING")
    a.assert_fields_null(untouched, "responded_at", "responded_by_user_id")
    live_plan = validate_success(
        api.get_workout_plan(scenario["plans"]["b1"], ASSET_MANAGER)
    )
    a.assert_status(live_plan, "CONSULTATION")

    again = validate_success(api.sweep_consultations({}, PLATFORM_ADMIN))
    assert again["swept_count"] == 0, "an already swept row is no longer PENDING"
    assert again["deemed_consented_ids"] == []


def test_the_trust_scoped_sweep_reaches_only_its_own_expired_row(api):
    """Narrowing by trust_id sweeps the one row that has since expired.

    The PRD: "The `PlatformAdmin` runs a sweep capability that finds every
    `PENDING` consultation whose `deadline_at` is **strictly** before the current
    logical clock — a consultation whose `deadline_at` is exactly equal to the
    clock is left `PENDING`, and a response is still accepted at that instant —
    and moves each `PENDING → DEEMED_CONSENTED`."

    Design: Corner/endpoints/consultation_sweep_deems_only_the_expired_pending_rows
    """
    scenario = _three_pending_consultations_across_two_trusts(api)
    consultations = scenario["consultations"]

    fx.set_clock(api, "2026-09-25T00:00:00Z")
    swept = validate_success(
        api.sweep_consultations({"trust_id": scenario["trust_b_id"]}, PLATFORM_ADMIN)
    )
    assert swept["swept_count"] == 1
    assert swept["deemed_consented_ids"] == [consultations["b1"]["id"]]

    deemed = validate_success(
        api.get_consultation(consultations["b1"]["id"], ASSET_MANAGER)
    )
    a.assert_status(deemed, "DEEMED_CONSENTED")
    plan = validate_success(api.get_workout_plan(scenario["plans"]["b1"], ASSET_MANAGER))
    a.assert_status(plan, "CONSENT_SATISFIED")

    for key in ("a1", "a2"):
        outside = validate_success(
            api.get_consultation(consultations[key]["id"], ASSET_MANAGER)
        )
        a.assert_status(outside, "PENDING")


# ==========================================================================
# The polymorphic consultation link on its borrower-request arm
# ==========================================================================
def _recommended_modification_request(api):
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V32"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V32"},
        event_factory=lambda client, loan_id: fx.record_bankruptcy_event(
            client, loan_id, occurred_on="2026-06-15T00:00:00Z"
        ),
    )
    fx.accepted_appraisal(
        api,
        built["loan_id"],
        value_usd=9000000,
        as_of_date="2026-07-01T00:00:00Z",
        ordered_on="2026-06-20T00:00:00Z",
        appraiser_firm="Meridian Valuation",
    )
    request = fx.recommended_request(
        api,
        built["loan_id"],
        analysis=f.analysis_payload(
            npv_recovery_with_request_usd=12000000,
            npv_recovery_without_request_usd=11900000,
            analysis_discount_rate_pct=8.0,
        ),
        headers=make_borrower_headers(built["loan_id"]),
    )
    return built["trust_id"], built["loan_id"], request


def test_an_absent_subject_is_a_not_found_before_any_consultation_is_written(api):
    """The borrower-request arm resolves its subject before storing anything.

    The PRD: "Every foreign key in the request body resolves to a stored row, or
    the 404 not-found error naming that entity: a dangling `trust_id` gives
    `ERR_TRUST_NOT_FOUND`, a dangling `loan_id` gives `ERR_LOAN_NOT_FOUND`"

    Design: Corner/endpoints/consultation_links_a_borrower_request_to_its_trust_and_unblocks_approval
    """
    trust_id, _, request = _recommended_modification_request(api)
    a.assert_status(request, "RECOMMENDED")
    a.assert_money(
        request["servicing_standard_margin_usd"], 100000.00, "servicing_standard_margin_usd"
    )
    a.assert_status(request, "SERVICING_STANDARD_MET", "servicing_standard_conclusion")

    response = api.create_consultation(
        f.request_consultation_payload(trust_id, NON_EXISTENT_UUID), ASSET_MANAGER
    )
    validate_error(response, e.ERR_BORROWER_REQUEST_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_consultations(ASSET_MANAGER, {"trust_id": trust_id})
    )
    assert rows == [], "the refused issue writes no consultation"
    assert meta["total_count"] == 0

    unchanged = validate_success(api.get_borrower_request(request["id"], ASSET_MANAGER))
    a.assert_status(unchanged, "RECOMMENDED")


def test_the_link_drags_the_request_along_and_then_unblocks_its_approval(api):
    """Issuing moves the subject; only the consent lets the committee decide.

    The PRD: "The subject advances at the same time: a workout plan moves
    `RECOMMENDED → CONSULTATION` and takes the consultation's `rights_type` as its
    own `consent_requirement`, while a borrower request moves `RECOMMENDED →
    CONSULTATION_PENDING`."

    Design: Corner/endpoints/consultation_links_a_borrower_request_to_its_trust_and_unblocks_approval
    """
    trust_id, loan_id, request = _recommended_modification_request(api)

    consultation = validate_success(
        api.create_consultation(
            f.request_consultation_payload(trust_id, request["id"]), ASSET_MANAGER
        ),
        201,
    )
    a.assert_status(consultation, "PENDING")
    a.assert_status(consultation, "CONSENT_RIGHT", "rights_type")
    assert consultation["borrower_request_id"] == request["id"]
    a.assert_fields_null(consultation, "workout_plan_id", "responded_at", "response_note")
    assert consultation["issued_at"].startswith("2026-08-01")
    assert consultation["deadline_at"].startswith("2026-08-14T23:59:59.999")

    linked = validate_success(api.get_borrower_request(request["id"], ASSET_MANAGER))
    a.assert_status(linked, "CONSULTATION_PENDING")

    premature = api.set_borrower_request_status(
        request["id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
    )
    validate_error(premature, e.ERR_CONSULTATION_NOT_SATISFIED, 409)
    still_pending = validate_success(api.get_borrower_request(request["id"], ASSET_MANAGER))
    a.assert_status(still_pending, "CONSULTATION_PENDING")
    a.assert_fields_null(still_pending, "decided_on", "decided_by_user_id")

    consented = fx.respond_to_consultation(
        api, consultation["id"], trust_id, "CONSENTED"
    )
    a.assert_status(consented, "CONSENTED")
    assert consented["responded_by_user_id"] == trust_id
    assert consented["responded_at"].startswith("2026-08-01")

    approved = validate_success(
        api.set_borrower_request_status(
            request["id"], f.status_payload("APPROVED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(approved, "APPROVED")
    assert approved["decided_by_user_id"] == "cmte-001"
    assert approved["decided_on"].startswith("2026-08-01")

    loan = fx.read_loan(api, loan_id, MASTER_SERVICER)
    assert loan["is_modified"] is True

    reduction = fx.provisional_reduction(api, loan_id)
    a.assert_money(reduction["ara_amount_usd"], 1900000.00, "ara_amount_usd")

    rows, meta = validate_paginated(
        api.list_consultations(
            make_controlling_class_representative_headers(trust_id),
            {"borrower_request_id": request["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == consultation["id"]


# ==========================================================================
# The asset business plan: a purely derived read
# ==========================================================================
def _loan_with_a_scored_plan_and_a_sixty_day_countdown(api):
    trust = fx.create_trust(api, deal_name="CMBS 2026-V33")
    loan = fx.create_mid_size_loan(api, trust["id"], loan_number="L-V33")
    fx.record_transfer_event(
        api,
        loan["id"],
        event_code="IMMINENT_DEFAULT",
        occurred_on="2026-07-20T00:00:00Z",
        evidence_note="borrower notice of imminent monetary default",
        days_delinquent_at_event=None,
        imminent_default_certified=True,
    )
    transferred = fx.transfer_to_special_servicing(api, loan["id"])
    built = fx.scored_plan(
        api,
        loan["id"],
        discount_rate_pct=8.0,
        alternative_builders=[
            _modification_route(
                [
                    {"period_index": 1, "amount_usd": 1000000},
                    {"period_index": 2, "amount_usd": 1000000},
                    {"period_index": 3, "amount_usd": 8000000},
                ],
                100000,
            ),
            lambda client, plan_id: fx.add_note_sale_alternative(
                client,
                plan_id,
                projected_cash_flows=[{"period_index": 1, "amount_usd": 8500000}],
                upfront_cost_usd=90000,
            ),
        ],
    )
    return loan["id"], transferred, built


def test_the_countdown_and_the_overdue_flag_move_with_the_clock_alone(api):
    """Two reads of the same row, no write in between, opposite answers.

    The PRD: "plus two derived figures: `days_until_due`, the whole-day difference
    between the current logical clock's date and the due date, which turns negative
    once the deadline has passed; and `is_overdue`, which is true exactly when the
    clock is strictly past the due date."

    Design: Corner/endpoints/asset_business_plan_read_derives_countdown_and_flips_overdue
    """
    loan_id, transferred, built = _loan_with_a_scored_plan_and_a_sixty_day_countdown(api)
    assert transferred["transferred_to_special_on"].startswith("2026-08-01")
    assert transferred["asset_business_plan_due_date"].startswith("2026-09-30")
    version_before = fx.loan_version(api, loan_id)

    on_time = validate_success(api.get_asset_business_plan(loan_id, TRUSTEE))
    assert on_time["loan_id"] == loan_id
    assert on_time["transferred_to_special_on"].startswith("2026-08-01")
    assert on_time["asset_business_plan_due_date"].startswith("2026-09-30")
    assert on_time["days_until_due"] == 60
    assert on_time["is_overdue"] is False
    assert on_time["active_workout_plan_id"] == built["plan_id"]
    assert on_time["recommended_alternative_type"] == "MODIFICATION"
    a.assert_money(on_time["ara_amount_usd"], 0.00, "ara_amount_usd")
    a.assert_money(
        on_time["required_monthly_pi_advance_usd"],
        65000.00,
        "required_monthly_pi_advance_usd",
    )

    fx.set_clock(api, "2026-10-05T00:00:00Z")
    late = validate_success(api.get_asset_business_plan(loan_id, TRUSTEE))
    assert late["days_until_due"] == -5
    assert late["is_overdue"] is True
    assert late["asset_business_plan_due_date"] == on_time["asset_business_plan_due_date"]
    assert fx.loan_version(api, loan_id) == version_before, (
        "the asset business plan endpoint is a computed read, not a write"
    )


# ==========================================================================
# The waiver releases the accrual period it was holding
# ==========================================================================
def test_the_waived_month_may_be_accrued_afresh_by_the_other_role(api):
    """The identical body is refused, then accepted, once the slot is released.

    The PRD: "Waiving compensates the loan's `fees_payable_usd` back to exactly
    its pre-accrual value and releases the combination of loan, fee type and
    accrual period so that the same month may be accrued afresh; both the
    accrual's and the loan's `version` advance by one."

    Design: Corner/endpoints/waiving_a_fee_accrual_releases_the_month_for_re_accrual
    """
    trust_id, loan_id = _loan_on_the_default_fee_convention(api, "CMBS 2026-V34", "L-V34")
    first = _monthly_accrual(
        api, loan_id, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", MASTER_SERVICER
    )
    a.assert_money(first["amount_usd"], 2083.33, "amount_usd")
    a.assert_money(
        fx.read_loan(api, loan_id, MASTER_SERVICER)["fees_payable_usd"],
        2083.33,
        "fees_payable_usd",
    )

    clash = api.create_fee_accrual(
        f.special_servicing_fee_payload(
            loan_id,
            period_start="2026-07-10T00:00:00Z",
            period_end="2026-07-31T00:00:00Z",
        ),
        ASSET_MANAGER,
    )
    validate_error(clash, e.ERR_FEE_PERIOD_OVERLAP, 409)
    a.assert_status(
        validate_success(api.get_fee_accrual(first["id"], MASTER_SERVICER)), "ACCRUED"
    )

    waived = validate_success(
        api.set_fee_accrual_status(
            first["id"],
            f.status_payload(
                "WAIVED",
                waived_reason="period accrued against the wrong servicing convention",
            ),
            COMMITTEE_OFFICER,
        )
    )
    a.assert_status(waived, "WAIVED")
    a.assert_money(
        fx.read_loan(api, loan_id, MASTER_SERVICER)["fees_payable_usd"],
        0.00,
        "fees_payable_usd",
    )

    re_accrual = _monthly_accrual(
        api, loan_id, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", ASSET_MANAGER
    )
    a.assert_status(re_accrual, "ACCRUED")
    a.assert_money(re_accrual["amount_usd"], 2083.33, "amount_usd")
    assert re_accrual["accrued_by_user_id"] == "amgr-001"
    a.assert_money(
        fx.read_loan(api, loan_id, MASTER_SERVICER)["fees_payable_usd"],
        2083.33,
        "fees_payable_usd",
    )

    rows, meta = validate_paginated(
        api.list_fee_accruals(
            MASTER_SERVICER, {"loan_id": loan_id, "fee_type": "SPECIAL_SERVICING_FEE"}
        )
    )
    assert meta["total_count"] == 2, "nothing is deleted by a waiver"
    assert a.ids_of(rows) == [first["id"], re_accrual["id"]]

    trust = fx.read_trust(api, trust_id, TRUSTEE)
    a.assert_money(trust["total_ara_usd"], 0.00, "total_ara_usd")
    a.assert_money(
        trust["total_advances_outstanding_usd"], 0.00, "total_advances_outstanding_usd"
    )
    a.assert_money(trust["realized_loss_usd"], 0.00, "realized_loss_usd")
