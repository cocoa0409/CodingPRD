"""Tax bill validation (evaluation order, segregation of duties) and payment
scheduling (split, cancel, pay, and the state gates around them)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_bill_allocation_invariant,
    assert_date_is,
    audit_event_types,
    client_headers_for,
    create_appeal_payload,
    create_decision_payload,
    create_exemption_application_payload,
    create_hearing_payload,
    create_notice_payload,
    create_payment_schedule_payload,
    create_review_payload,
    create_tax_bill_payload,
    file_it,
    find_installment,
    generate,
    list_audit_events,
    new_manager,
    open_rendition,
    setup_classified_asset,
    setup_notice_for_filed,
    setup_validated_bill,
    api_client,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["assessor_clerk_headers"]


def _setup_exemption_capped_bill():
    """Approved 80% FREEPORT exemption on the only asset (assessed 800000);
    ACCEPTED notice 800000; bill billed 10000 at rate 0.025, still PENDING.
    Returns ctx with client/analyst/manager/exemption/bill."""
    ctx = setup_classified_asset(
        jurisdiction_overrides={"tax_rate": 0.025, "max_exemption_pct": 100},
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "E1", "acquisition_cost_cents": 800000},
        with_manager=True,
    )
    exemption = validate_success(api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=80,
            effective_date="2026-06-01", expiration_date="2028-06-01"),
        ctx["analyst"]["headers"]), 201)
    validate_success(api_client.submit_exemption_application(
        exemption["id"], ctx["analyst"]["headers"]), 200)
    ctx["exemption"] = validate_success(api_client.review_exemption_application(
        exemption["id"], create_review_payload("APPROVE"), CLERK), 200)

    rendition = open_rendition(ctx["client"]["id"], ctx["jurisdiction"]["id"], 2027,
                               ctx["analyst"]["headers"])
    generate(rendition["id"], ctx["analyst"]["headers"])
    ctx["rendition"] = file_it(rendition["id"], ctx["analyst"]["headers"])
    notice = validate_success(api_client.create_notice(
        ctx["rendition"]["id"], create_notice_payload(notice_value_cents=800000),
        CLERK), 201)
    ctx["notice"] = validate_success(api_client.accept_notice(
        notice["id"], ctx["analyst"]["headers"]), 200)
    ctx["bill"] = validate_success(api_client.create_tax_bill(
        ctx["notice"]["id"],
        create_tax_bill_payload(billed_amount_cents=10000, tax_rate=0.025,
                                due_date="2027-06-30"),
        ctx["analyst"]["headers"]), 201)
    return ctx


def test_exemption_credit_capped_at_half_the_gross_tax(api):
    """PRD §3.6: "Step two computes the exemption credit as the smaller of two
    figures: the qualifying exemption's line share multiplied by its
    `exemption_pct`, divided by 100 and rounded half-up to whole cents, then
    multiplied by the bill's `tax_rate` and rounded half-up again; and fifty
    percent of the gross tax, rounded half-up to whole cents." and "The bill's
    `validated_amount_cents` is then the gross tax minus the exemption credit
    minus the abatement credit plus the late component, and `variance_cents` is
    the `billed_amount_cents` minus the `validated_amount_cents`. An absolute
    variance of no more than 100 cents — one dollar — lands the bill in `MATCHED`;
    anything larger lands it in `DISCREPANCY`."

    Design: Difficulty/combinatorial_formula/exemption_cap_evaluation_order
    """
    ctx = _setup_exemption_capped_bill()
    bill = validate_success(api_client.validate_bill(
        ctx["bill"]["id"], ctx["manager"]["headers"]), 200)
    # gross = round(800000 * 0.025) = 20000; raw exemption credit 16000 exceeds
    # the fifty-percent cap round(20000 * 50 / 100) = 10000, so credit = 10000.
    assert bill["validated_amount_cents"] == 10000
    assert bill["variance_cents"] == 0
    assert bill["validation_status"] == "MATCHED"


def test_validation_sets_unscheduled_amount_and_validator(api):
    """PRD §3.6: "Validation also sets `unscheduled_amount_cents` to the validated
    amount, records `validated_by_operator_id`, and appends `BILL_VALIDATED`."

    Design: Difficulty/combinatorial_formula/exemption_cap_evaluation_order
    """
    ctx = _setup_exemption_capped_bill()
    bill = validate_success(api_client.validate_bill(
        ctx["bill"]["id"], ctx["manager"]["headers"]), 200)
    assert bill["unscheduled_amount_cents"] == 10000
    assert bill["validated_by_operator_id"] == ctx["manager"]["id"]
    assert bill["payment_status"] == "UNSCHEDULED"

    events = list_audit_events(ctx["client"]["id"])
    assert "BILL_VALIDATED" in audit_event_types(events)


def _setup_settled_appeal_scenario():
    """Validated MATCHED bill (20000) with a 2-installment schedule whose first
    installment the client has PAID, plus an appeal DECIDED at 600000."""
    ctx = setup_validated_bill(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "S1", "acquisition_cost_cents": 800000},
        bill_overrides={"billed_amount_cents": 20000, "tax_rate": 0.025,
                        "due_date": "2027-06-30"},
    )
    bill = validate_success(api_client.create_payment_schedule(
        ctx["bill"]["id"], create_payment_schedule_payload(installment_count=2),
        ctx["analyst"]["headers"]), 200)
    assert [i["amount_cents"] for i in bill["installments"]] == [10000, 10000]
    bill = validate_success(api_client.pay_installment(
        ctx["bill"]["id"], {"installment_no": 1},
        client_headers_for(ctx["client"])), 200)
    assert find_installment(bill, 1)["installment_status"] == "PAID"

    appeal = validate_success(api_client.create_appeal(
        ctx["notice"]["id"], create_appeal_payload(claimed_value_cents=600000),
        ctx["analyst"]["headers"]), 201)
    validate_success(api_client.schedule_hearing(appeal["id"],
                                                 create_hearing_payload(), CLERK), 200)
    ctx["appeal"] = validate_success(api_client.record_decision(
        appeal["id"],
        create_decision_payload(decision="GRANTED_REDUCTION",
                                decided_value_cents=600000),
        CLERK), 200)
    return ctx


def test_appeal_accept_finalizes_notice_at_decided_value(api):
    """PRD §3.5: "Accepting (`resolution` of `ACCEPT`) moves the appeal from
    `DECIDED` to `ACCEPTED` and applies the decided value: the notice finalizes at
    `final_value_cents` equal to `decided_value_cents`, firing the finalization
    cascade described below, and `APPEAL_RESOLVED` is appended." and "The linked
    rendition moves from `FILED` to `ACCEPTED`."

    Design: Difficulty/transitive_cascade/appeal_settle_cascade_notice_bill_installments
    """
    ctx = _setup_settled_appeal_scenario()
    resolved = validate_success(api_client.resolve_appeal(
        ctx["appeal"]["id"], {"resolution": "ACCEPT"},
        client_headers_for(ctx["client"])), 200)
    assert resolved["appeal_status"] == "ACCEPTED"

    notice = validate_success(api_client.get_notice(ctx["notice"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert notice["notice_status"] == "FINALIZED"
    assert notice["final_value_cents"] == 600000

    rendition = validate_success(api_client.get_rendition(
        ctx["rendition"]["id"], ctx["analyst"]["headers"]), 200)
    assert rendition["rendition_status"] == "ACCEPTED"

    events = list_audit_events(ctx["client"]["id"])
    assert "APPEAL_RESOLVED" in audit_event_types(events)
    assert "NOTICE_FINALIZED" in audit_event_types(events)


def test_appeal_accept_revalidates_bill_and_cancels_unpaid_installments(api):
    """PRD §3.5: "Every tax bill of the notice whose `validation_status` is not
    `PENDING` is revalidated under the validation computation of §3.6 (each
    appending `BILL_REVALIDATED`), and each revalidated bill cancels its
    installments in `SCHEDULED` or `LATE` status, resets its
    `unscheduled_amount_cents` to the new validated amount minus the sum of its
    `PAID` installments, and recomputes its `payment_status`; bills still
    `PENDING` are left untouched."

    Design: Difficulty/transitive_cascade/appeal_settle_cascade_notice_bill_installments
    """
    ctx = _setup_settled_appeal_scenario()
    validate_success(api_client.resolve_appeal(
        ctx["appeal"]["id"], {"resolution": "ACCEPT"},
        client_headers_for(ctx["client"])), 200)

    bill = validate_success(api_client.get_tax_bill(ctx["bill"]["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert bill["validated_amount_cents"] == 15000, "round_half_up(600000 * 0.025)"
    assert bill["validation_status"] == "DISCREPANCY"
    assert bill["variance_cents"] == 5000, "20000 billed - 15000 validated"
    assert find_installment(bill, 1)["installment_status"] == "PAID"
    assert find_installment(bill, 2)["installment_status"] == "CANCELLED"
    assert bill["unscheduled_amount_cents"] == 5000, "15000 - 10000 paid"
    assert bill["payment_status"] == "PARTIALLY_PAID"
    assert_bill_allocation_invariant(bill)

    events = list_audit_events(ctx["client"]["id"])
    assert "BILL_REVALIDATED" in audit_event_types(events)


def test_installment_split_pushes_remainder_to_first(api):
    """PRD §3.6: "The split divides the `validated_amount_cents` by the
    installment count using floor division to obtain a base amount, and the
    remainder — the validated amount minus the base times the count — is added to
    the first installment only: installment number 1 carries base plus remainder,
    and installments 2 onward carry the base, so the amounts sum to exactly the
    validated amount. Due dates are spaced thirty days apart starting at the
    bill's `due_date`, so installment number i falls due (i − 1) times thirty days
    after it." and "Scheduling drops `unscheduled_amount_cents` to zero, moves
    `payment_status` to `SCHEDULED`, and appends `SCHEDULE_CREATED`."

    Design: Difficulty/compensating_invariant/schedule_cancel_conserves_bill_allocation
    """
    ctx = setup_validated_bill(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "L1", "acquisition_cost_cents": 800000},
        bill_overrides={"billed_amount_cents": 20000, "tax_rate": 0.025,
                        "due_date": "2027-06-30"},
    )
    bill = validate_success(api_client.create_payment_schedule(
        ctx["bill"]["id"], create_payment_schedule_payload(installment_count=3),
        ctx["analyst"]["headers"]), 200)
    # 20000 = 6666 * 3 + 2 -> the 2 remainder cents land on installment 1.
    amounts = [i["amount_cents"] for i in bill["installments"]]
    assert amounts == [6668, 6666, 6666]
    dues = [i["due_date"] for i in bill["installments"]]
    assert_date_is(dues[0], "2027-06-30", "installment 1 due_date")
    assert_date_is(dues[1], "2027-07-30", "installment 2 due_date")
    assert_date_is(dues[2], "2027-08-29", "installment 3 due_date")
    for inst in bill["installments"]:
        assert inst["installment_status"] == "SCHEDULED"
    assert bill["unscheduled_amount_cents"] == 0
    assert bill["payment_status"] == "SCHEDULED"
    assert_bill_allocation_invariant(bill)

    events = list_audit_events(ctx["client"]["id"])
    assert "SCHEDULE_CREATED" in audit_event_types(events)


def test_schedule_cancel_restores_unscheduled_amount(api):
    """PRD §3.6: "A `TaxAnalyst` may cancel the schedule while the bill is
    `SCHEDULED`, `PARTIALLY_PAID`, or `DELINQUENT`: installments in `SCHEDULED` or
    `LATE` move to `CANCELLED` while `PAID` installments are kept,
    `unscheduled_amount_cents` is reset to the validated amount minus the sum of
    the paid installments, and the payment status is recomputed — `UNSCHEDULED`
    when nothing has been paid, otherwise `PARTIALLY_PAID`. A
    `SCHEDULE_CANCELLED` event is appended."

    Design: Difficulty/compensating_invariant/schedule_cancel_conserves_bill_allocation
    """
    ctx = setup_validated_bill(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "L1", "acquisition_cost_cents": 800000},
        bill_overrides={"billed_amount_cents": 20000, "tax_rate": 0.025,
                        "due_date": "2027-06-30"},
    )
    validate_success(api_client.create_payment_schedule(
        ctx["bill"]["id"], create_payment_schedule_payload(installment_count=3),
        ctx["analyst"]["headers"]), 200)

    bill = validate_success(api_client.cancel_payment_schedule(
        ctx["bill"]["id"], ctx["analyst"]["headers"]), 200)
    assert all(i["installment_status"] == "CANCELLED" for i in bill["installments"])
    assert bill["unscheduled_amount_cents"] == 20000
    assert bill["payment_status"] == "UNSCHEDULED"
    assert bill["validated_amount_cents"] == 20000, "cancel does not revalidate"
    assert_bill_allocation_invariant(bill)

    events = list_audit_events(ctx["client"]["id"])
    assert "SCHEDULE_CANCELLED" in audit_event_types(events)


def test_bill_validate_by_importing_operator_rejected(api):
    """PRD §2.8: "The `SeniorManager` who validates a tax bill must not be the
    operator who imported it — the acting `X-User-ID` is compared against the
    bill's `created_by_operator_id`." and "Either violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." and "Senior managers are permitted to
    file renditions and to import bills, but doing so bars them from the
    corresponding check on their own work."

    Design: Corner/state_machines/bill_validate_by_importing_operator_rejected
    """
    ctx = setup_notice_for_filed(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "SB1", "acquisition_cost_cents": 800000},
        accept=True, with_manager=True,
    )
    second_manager = new_manager("Manny Two")
    bill = validate_success(api_client.create_tax_bill(
        ctx["notice"]["id"],
        create_tax_bill_payload(billed_amount_cents=20000, tax_rate=0.025,
                                due_date="2027-06-30"),
        ctx["manager"]["headers"]), 201)
    assert bill["created_by_operator_id"] == ctx["manager"]["id"]

    res = api_client.validate_bill(bill["id"], ctx["manager"]["headers"])
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    validated = validate_success(api_client.validate_bill(
        bill["id"], second_manager["headers"]), 200)
    assert validated["validation_status"] == "MATCHED"
    assert validated["validated_amount_cents"] == 20000
    assert validated["validated_by_operator_id"] == second_manager["id"]


def test_analyst_cannot_validate_bill_forbidden(api):
    """PRD §3.6: "Validation is a `SeniorManager` act on a `PENDING` bill —
    validating a bill in any other validation state yields
    `ERR_BILL_NOT_ACTIONABLE`" and PRD §2.1: "Authorization is then enforced per
    endpoint: a role outside the endpoint's permitted set, or a `Client` whose
    `X-User-ID` does not own the addressed resource through the foreign-key chain
    described below, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/analyst_cannot_validate_bill_forbidden
    """
    ctx = setup_notice_for_filed(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "RB1", "acquisition_cost_cents": 800000},
        accept=True, with_manager=True,
    )
    bill = validate_success(api_client.create_tax_bill(
        ctx["notice"]["id"],
        create_tax_bill_payload(billed_amount_cents=20000, tax_rate=0.025,
                                due_date="2027-06-30"),
        ctx["analyst"]["headers"]), 201)

    res = api_client.validate_bill(bill["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    after = validate_success(api_client.get_tax_bill(bill["id"],
                                                     ctx["analyst"]["headers"]), 200)
    assert after["validation_status"] == "PENDING"


def test_schedule_zero_validated_amount_rejected(api):
    """PRD §3.6: "A validated amount of zero cannot be scheduled and is rejected
    with `ERR_ZERO_SCHEDULE_AMOUNT` (HTTP 422)." and "An absolute variance of no
    more than 100 cents — one dollar — lands the bill in `MATCHED`; anything
    larger lands it in `DISCREPANCY`."

    Design: Corner/validations/schedule_zero_validated_amount_rejected
    """
    ctx = setup_validated_bill(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "Z1", "acquisition_cost_cents": 800000},
        bill_overrides={"billed_amount_cents": 20000, "tax_rate": 0.0,
                        "due_date": "2027-06-30"},
    )
    bill = ctx["bill"]
    assert bill["validated_amount_cents"] == 0, "gross is 800000 * 0.0 = 0"
    assert bill["validation_status"] == "DISCREPANCY", "variance 20000 exceeds 100"
    assert bill["payment_status"] == "UNSCHEDULED"

    res = api_client.create_payment_schedule(
        bill["id"], create_payment_schedule_payload(installment_count=2),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_ZERO_SCHEDULE_AMOUNT, expected_status=422)

    after = validate_success(api_client.get_tax_bill(bill["id"],
                                                     ctx["analyst"]["headers"]), 200)
    assert after["payment_status"] == "UNSCHEDULED"
    assert after["installments"] == []


def test_schedule_before_validate_rejected(api):
    """PRD §3.6: "Scheduling requires `validation_status` of `MATCHED` or
    `DISCREPANCY` — paying under protest is explicitly allowed, so the linked
    notice may still be `PROTESTED` — together with `payment_status`
    `UNSCHEDULED`; the wrong state in either dimension yields
    `ERR_BILL_NOT_ACTIONABLE`."

    Design: Corner/validations/schedule_before_validate_rejected
    """
    ctx = setup_notice_for_filed(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "PN1", "acquisition_cost_cents": 800000},
        accept=True, with_manager=True,
    )
    bill = validate_success(api_client.create_tax_bill(
        ctx["notice"]["id"],
        create_tax_bill_payload(billed_amount_cents=20000, tax_rate=0.025,
                                due_date="2027-06-30"),
        ctx["analyst"]["headers"]), 201)
    assert bill["validation_status"] == "PENDING"

    res = api_client.create_payment_schedule(
        bill["id"], create_payment_schedule_payload(installment_count=2),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_BILL_NOT_ACTIONABLE, expected_status=409)

    after = validate_success(api_client.get_tax_bill(bill["id"],
                                                     ctx["analyst"]["headers"]), 200)
    assert after["payment_status"] == "UNSCHEDULED"
    assert after["installments"] == []
