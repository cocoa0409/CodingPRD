"""Relief applications: review/info cycle, exemption vs abatement, overlap, lockdown."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_tax_year, create_parcel, setup_first_installment_paid,
    submit_relief, review_relief, request_info, resubmit_relief, decide_relief,
    installment_seq, get_bill,
    create_relief_application_payload, decide_payload,
    TEST_USERS,
)

CASHIER = TEST_USERS["cashier_headers"]
RELIEF = TEST_USERS["relief_headers"]


# ---- Difficulty: relief_review_info_request_cycle (test 1 of 2) ----
def test_relief_info_request_increments_count_each_cycle(api):
    """PRD 3.3: "From `UNDER_REVIEW` the officer may request additional information,
    advancing it to `INFO_REQUESTED` and incrementing `info_request_count`
    by one."

    Design: Difficulty/non_linear_state_machine/relief_review_info_request_cycle
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-D5", assessed_value_cents=15000000)
    app = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "HOMESTEAD",
                        claimed_amount_cents=50000)
    review_relief(api, app["id"])
    after1 = request_info(api, app["id"])
    assert after1["info_request_count"] == 1
    resubmit_relief(api, app["id"])
    after2 = request_info(api, app["id"])
    assert after2["info_request_count"] == 2


# ---- Difficulty: relief_review_info_request_cycle (test 2 of 2) ----
def test_relief_two_cycles_then_denied_terminal(api):
    """PRD 3.3: "This review/request-info/resubmit loop may repeat any number of times."
    PRD 3.3: "A denial simply records `decided_by_user_id` and applies no credit."

    Design: Difficulty/non_linear_state_machine/relief_review_info_request_cycle
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-D5", assessed_value_cents=15000000)
    app = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "HOMESTEAD",
                        claimed_amount_cents=50000)
    review_relief(api, app["id"])
    request_info(api, app["id"])
    resubmit_relief(api, app["id"])
    request_info(api, app["id"])
    resubmit_relief(api, app["id"])
    decided = decide_relief(api, app["id"], "DENY")
    assert decided["status"] == "DENIED"
    assert decided["info_request_count"] == 2


# ---- Difficulty: relief_exemption_vs_abatement_distribution (test 1 of 2) ----
def test_abatement_credit_distributes_to_unpaid_installment_only(api):
    """PRD 3.3: "For an `ABATEMENT`, the ceiling is the sum of the bill's unpaid
    installment balances, and the approved credit is distributed as
    `ABATEMENT` ledger entries across the unpaid installments in ascending
    `sequence` order, with already-paid installments receiving nothing"

    Design: Difficulty/dual_variant_calc/relief_exemption_vs_abatement_distribution
    """
    ty, parcel, bill = setup_first_installment_paid(api, assessed_value_cents=20000000)
    app = submit_relief(api, parcel["id"], ty["id"], "ABATEMENT", "HARDSHIP",
                        claimed_amount_cents=100000)
    review_relief(api, app["id"])
    decided = decide_relief(api, app["id"], "APPROVE")
    assert decided["approved_credit_cents"] == 100000
    assert installment_seq(api, bill["id"], 2)["balance_cents"] == 100000
    assert installment_seq(api, bill["id"], 1)["balance_cents"] == 0


# ---- Difficulty: relief_exemption_vs_abatement_distribution (test 2 of 2) ----
def test_abatement_credit_recorded_on_bill(api):
    """PRD 3.2: "`abatement_credit_cents`, the absolute sum of `ABATEMENT` entries posted
    after issuance"
    PRD 2.11: "a bill's `balance_cents` is exactly the sum of every one of its
    `LedgerEntry` amounts, with none excluded."

    Design: Difficulty/dual_variant_calc/relief_exemption_vs_abatement_distribution
    """
    ty, parcel, bill = setup_first_installment_paid(api, assessed_value_cents=20000000)
    app = submit_relief(api, parcel["id"], ty["id"], "ABATEMENT", "HARDSHIP",
                        claimed_amount_cents=100000)
    review_relief(api, app["id"])
    decide_relief(api, app["id"], "APPROVE")
    refreshed = get_bill(api, bill["id"])
    assert refreshed["abatement_credit_cents"] == 100000
    assert refreshed["balance_cents"] == 100000


# ---- Difficulty: abatement_approval_marks_installment_paid (test 1 of 2) ----
def test_abatement_zeroes_installment_marks_paid(api):
    """PRD 3.3: "as each installment's balance is recomputed, an installment that reaches a
    zero balance becomes `PAID`."

    Design: Difficulty/transitive_cascade/abatement_approval_marks_installment_paid
    """
    ty, parcel, bill = setup_first_installment_paid(api, assessed_value_cents=20000000)
    app = submit_relief(api, parcel["id"], ty["id"], "ABATEMENT", "SENIOR",
                        claimed_amount_cents=200000)
    review_relief(api, app["id"])
    decide_relief(api, app["id"], "APPROVE")
    inst2 = installment_seq(api, bill["id"], 2)
    assert inst2["balance_cents"] == 0
    assert inst2["status"] == "PAID"


# ---- Difficulty: abatement_approval_marks_installment_paid (test 2 of 2) ----
def test_abatement_bubbles_bill_to_paid(api):
    """PRD 3.4: "a payment that clears the balance to zero with all installments paid
    yields `PAID`."
    PRD 3.2: "`abatement_credit_cents`, the absolute sum of `ABATEMENT` entries posted
    after issuance"

    Design: Difficulty/transitive_cascade/abatement_approval_marks_installment_paid
    """
    ty, parcel, bill = setup_first_installment_paid(api, assessed_value_cents=20000000)
    app = submit_relief(api, parcel["id"], ty["id"], "ABATEMENT", "SENIOR",
                        claimed_amount_cents=200000)
    review_relief(api, app["id"])
    decide_relief(api, app["id"], "APPROVE")
    refreshed = get_bill(api, bill["id"])
    assert refreshed["collection_status"] == "PAID"
    assert refreshed["abatement_credit_cents"] == 200000


# ---- Difficulty: relief_effective_period_closed_overlap (test 1 of 2) ----
def test_touching_relief_intervals_rejected_as_overlap(api):
    """PRD 3.3: "An approval first checks that no other active or approved application on
    the same parcel has an effective interval overlapping this one — the
    two closed intervals `[effective_from, effective_to]` are treated as
    overlapping even when they merely touch at an endpoint — and a
    conflict is rejected with `ERR_RELIEF_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/relief_effective_period_closed_overlap
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-D15", assessed_value_cents=20000000)
    app1 = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "HOMESTEAD",
                         claimed_amount_cents=50000,
                         effective_from="2025-01-01T00:00:00Z", effective_to="2025-12-31T00:00:00Z")
    review_relief(api, app1["id"])
    decide_relief(api, app1["id"], "APPROVE")
    app2 = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "SENIOR",
                         claimed_amount_cents=40000,
                         effective_from="2025-12-31T00:00:00Z", effective_to="2026-06-30T00:00:00Z")
    review_relief(api, app2["id"])
    resp = api.decide_relief(app2["id"], decide_payload("APPROVE"), RELIEF)
    validate_error(resp, ApiErrorId.ERR_RELIEF_PERIOD_OVERLAP.value)


# ---- Difficulty: relief_effective_period_closed_overlap (test 2 of 2) ----
def test_relief_overlap_leaves_application_under_review(api):
    """PRD 3.3: "the two closed intervals `[effective_from, effective_to]` are treated as
    overlapping even when they merely touch at an endpoint — and a
    conflict is rejected with `ERR_RELIEF_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/relief_effective_period_closed_overlap
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-D15", assessed_value_cents=20000000)
    app1 = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "HOMESTEAD",
                         claimed_amount_cents=50000,
                         effective_from="2025-01-01T00:00:00Z", effective_to="2025-12-31T00:00:00Z")
    review_relief(api, app1["id"])
    decide_relief(api, app1["id"], "APPROVE")
    app2 = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "SENIOR",
                         claimed_amount_cents=40000,
                         effective_from="2025-12-31T00:00:00Z", effective_to="2026-06-30T00:00:00Z")
    review_relief(api, app2["id"])
    api.decide_relief(app2["id"], decide_payload("APPROVE"), RELIEF)
    after = validate_success(api.get_relief_application(app2["id"], RELIEF))
    assert after["status"] == "UNDER_REVIEW"


# ---- Corner: state_machines/review_twice_invalid_state ----
def test_review_already_under_review_invalid_state(api):
    """PRD 3.3: "attempting a transition from a state that is legal for the machine but
    wrong for the requested action (for example deciding an application
    still in `SUBMITTED`) is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/review_twice_invalid_state
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-C8", assessed_value_cents=15000000)
    app = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "HOMESTEAD",
                        claimed_amount_cents=50000)
    review_relief(api, app["id"])
    resp = api.review_relief(app["id"], RELIEF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---- Corner: state_machines/decide_denied_application_already_decided ----
def test_decide_denied_application_already_decided(api):
    """PRD 3.3: "Attempting review, request-info, resubmit, or decide on an application
    that has already reached the terminal `APPROVED` or `DENIED` state is
    rejected with `ERR_RELIEF_ALREADY_DECIDED`"

    Design: Corner/state_machines/decide_denied_application_already_decided
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-C9", assessed_value_cents=15000000)
    app = submit_relief(api, parcel["id"], ty["id"], "ABATEMENT", "HARDSHIP",
                        claimed_amount_cents=50000)
    review_relief(api, app["id"])
    decide_relief(api, app["id"], "DENY")
    resp = api.decide_relief(app["id"], decide_payload("APPROVE"), RELIEF)
    validate_error(resp, ApiErrorId.ERR_RELIEF_ALREADY_DECIDED.value)


# ---- Corner: validations/relief_class_invalid_enum_rejected ----
def test_relief_class_invalid_enum_rejected(api):
    """PRD 2.6: "An enum field whose value lies outside its declared domain yields
    `ERR_INVALID_ENUM` (422)."

    Design: Corner/validations/relief_class_invalid_enum_rejected
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-C20", assessed_value_cents=15000000)
    payload = create_relief_application_payload(parcel["id"], ty["id"], "TAXCUT",
                                                "HOMESTEAD", claimed_amount_cents=50000)
    resp = api.create_relief_application(payload, CASHIER)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)
