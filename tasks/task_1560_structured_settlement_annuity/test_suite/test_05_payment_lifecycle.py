"""Payment issuance, return, reissue, and the outstanding-liability ledger
(PRD §3.3, §3.4)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_active_case, issue_payment, report_returned,
    get_returned_case_for_payment, get_agreement, get_payment,
    set_clock, create_and_activate_guardianship,
    TEST_USERS, make_operations_specialist_headers,
)

READER = TEST_USERS["reader_headers"]
OPS = TEST_USERS["operations_specialist_headers"]


def _setup_single_payable_payment(amount=120000, due_date="2026-09-01",
                                  clock_to="2026-09-01T00:00:00Z", case_number="CY-001",
                                  payee_overrides=None):
    """Funded agreement with an ACTIVE schedule; one payment matured to PAYABLE."""
    return setup_active_case(
        payments=[{"due_date": due_date, "base_amount_cents": amount}],
        clock_to=clock_to,
        agreement_overrides={"case_number": case_number},
        payee_overrides=payee_overrides)


# --- The ISSUED -> RETURNED -> PAYABLE -> ISSUED reissue loop (PRD §3.4) ---------

def test_issue_return_opens_case_with_reporter_as_anchor(api):
    """PRD §3.4: "Reporting a return — supplying a `return_reason` of `BAD_ADDRESS`,
    `EFT_REJECTED`, or `UNCASHED_STALE` — likewise requires `ISSUED`
    (`ERR_PAYMENT_NOT_ISSUED`), moves the payment to `RETURNED` with the reason recorded,
    and automatically opens a `ReturnedPaymentCase`".

    Design: Difficulty/non_linear_state_machine/payment_issue_return_reissue_cycle
    """
    ctx = _setup_single_payable_payment()
    payment = ctx["payments"][0]

    issued = issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    assert issued["status"] == "ISSUED"

    returned = report_returned(payment["id"], return_reason="BAD_ADDRESS", user_id="ops-1")
    assert returned["status"] == "RETURNED"
    assert returned["return_reason"] == "BAD_ADDRESS"

    case = get_returned_case_for_payment(payment["id"])
    assert case["status"] == "OPEN"
    assert case["scheduled_payment_id"] == payment["id"]
    assert case["return_reason"] == "BAD_ADDRESS"
    assert case["opened_by_user_id"] == "ops-1", (
        "opened_by_user_id captures the reporting X-User-ID as the SoD anchor"
    )


def test_reissue_cycle_closes_case_and_second_issuance_records_method(api):
    """PRD §3.4: "Success moves the case `OPEN` → `RESOLVED_REISSUE` with
    `resolution_note` set to `REISSUE_AUTHORIZED` and cascades the payment `RETURNED` →
    `PAYABLE`, ready to be issued again".
    PRD §3.4: "A successful issue moves `PAYABLE` → `ISSUED`, increments `issue_count`
    (which starts at zero on a new payment), records `last_issue_method` and the clock
    date as `last_issued_at`".

    Design: Difficulty/non_linear_state_machine/payment_issue_return_reissue_cycle
    """
    ctx = _setup_single_payable_payment()
    payment = ctx["payments"][0]
    issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    report_returned(payment["id"], user_id="ops-1")
    case = get_returned_case_for_payment(payment["id"])

    resolved = validate_success(api.authorize_reissue(
        case["id"], make_operations_specialist_headers("ops-2")))
    assert resolved["status"] == "RESOLVED_REISSUE"
    assert get_payment(payment["id"])["status"] == "PAYABLE", "loop-closing transition"

    reissued = issue_payment(payment["id"], method="EFT", user_id="ops-2")
    assert reissued["status"] == "ISSUED"
    assert reissued["issue_count"] == 2, "the cycle completed with a second issuance"
    assert reissued["last_issue_method"] == "EFT"


def test_issue_from_cleared_returns_not_payable(api):
    """PRD §3.4: "the payment must be `PAYABLE` (`ERR_PAYMENT_NOT_PAYABLE` otherwise)".
    PRD §3.4: "Marking cleared — an operations specialist confirming the funds were
    honored — requires `ISSUED` (`ERR_PAYMENT_NOT_ISSUED`) and moves the payment to
    `CLEARED`: the agreement's `paid_total_cents` grows by the payment's `amount_cents`,
    `outstanding_liability_cents` shrinks by the same, the agreement's `version`
    increments, and the exhaustion check runs — if no non-terminal payments remain, the
    linked policy becomes `EXHAUSTED` and the agreement follows to `CLOSED`."

    Design: Corner/state_machines/issue_from_cleared_returns_not_payable
    """
    ctx = _setup_single_payable_payment(amount=40000, due_date="2026-08-10",
                                        clock_to="2026-08-10T00:00:00Z",
                                        case_number="EN-003")
    payment = ctx["payments"][0]
    issue_payment(payment["id"], method="EFT", user_id="ops-1")
    cleared = validate_success(api.mark_payment_cleared(payment["id"], OPS))
    assert cleared["status"] == "CLEARED"

    resp_issue = api.issue_payment(payment["id"], {"method": "CHECK"}, OPS)
    validate_error(resp_issue, ApiErrorId.ERR_PAYMENT_NOT_PAYABLE)
    resp_clear = api.mark_payment_cleared(payment["id"], OPS)
    validate_error(resp_clear, ApiErrorId.ERR_PAYMENT_NOT_ISSUED)

    policy = validate_success(api.get_annuity_policy(ctx["policy"]["id"], READER))
    assert policy["status"] == "EXHAUSTED"
    assert get_agreement(ctx["agreement"]["id"])["status"] == "CLOSED", (
        "the exhaustion cascade fired at the clear"
    )


def test_sod_reissue_same_user_rejected(api):
    """PRD §3.4: "critically, the authorizer's `X-User-ID` must differ from the case's
    `opened_by_user_id`, or the request fails with `ERR_SOD_VIOLATION`."

    Design: Corner/rbac/sod_reissue_same_user_rejected
    """
    ctx = _setup_single_payable_payment(amount=60000, due_date="2026-08-10",
                                        clock_to="2026-08-10T00:00:00Z",
                                        case_number="RB-002")
    payment = ctx["payments"][0]
    issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    report_returned(payment["id"], user_id="ops-1")
    case = get_returned_case_for_payment(payment["id"])

    resp = api.authorize_reissue(case["id"], make_operations_specialist_headers("ops-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    resolved = validate_success(api.authorize_reissue(
        case["id"], make_operations_specialist_headers("ops-2")))
    assert resolved["status"] == "RESOLVED_REISSUE"


def test_authorize_reissue_twice_returns_case_invalid_state(api):
    """PRD §3.4: "Authorizing reissue is an operations-specialist action requiring the
    case `OPEN` (`ERR_CASE_INVALID_STATE`) and the linked payment still `RETURNED`
    (`ERR_PAYMENT_NOT_RETURNED`)".

    Design: Corner/errors/authorize_reissue_twice_returns_case_invalid_state
    """
    ctx = _setup_single_payable_payment(amount=60000, due_date="2026-08-10",
                                        clock_to="2026-08-10T00:00:00Z",
                                        case_number="ER-008")
    payment = ctx["payments"][0]
    issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    report_returned(payment["id"], user_id="ops-1")
    case = get_returned_case_for_payment(payment["id"])
    validate_success(api.authorize_reissue(case["id"], make_operations_specialist_headers("ops-2")))

    resp = api.authorize_reissue(case["id"], make_operations_specialist_headers("ops-3"))
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


def test_payment_not_returned_after_escheat_sweep(api):
    """PRD §3.4: "Authorizing reissue is an operations-specialist action requiring the
    case `OPEN` (`ERR_CASE_INVALID_STATE`) and the linked payment still `RETURNED`
    (`ERR_PAYMENT_NOT_RETURNED`)".
    PRD §3.8: "The sweep never touches the payment's returned-payment case — the case
    stays `OPEN`."

    Design: Corner/errors/payment_not_returned_after_escheat_sweep
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2026-09-01", "base_amount_cents": 80000},
                  {"due_date": "2027-09-01", "base_amount_cents": 90000}],
        profile_overrides={"state_code": "OR", "sspa_max_discount_rate_bps": 1500,
                           "disclosure_cooling_off_days": 15, "ipa_required": False,
                           "dormancy_years": 1},
        payee_overrides={"address_state_code": "OR", "address_city": "Salem",
                         "address_postal_code": "97302"},
        agreement_overrides={"case_number": "ER-012", "court_state_code": "OR"})
    payment = ctx["payments"][0]
    set_clock("2026-09-05T00:00:00Z")
    issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    report_returned(payment["id"], user_id="ops-1")
    case = get_returned_case_for_payment(payment["id"])

    set_clock("2027-09-06T00:00:00Z")
    swept = get_payment(payment["id"])
    assert swept["status"] == "ESCHEATABLE", (
        "dormancy anniversary 2027-09-01 strictly passed: the clock sweep moved the "
        "RETURNED payment to ESCHEATABLE while the case remained OPEN"
    )

    resp = api.authorize_reissue(case["id"], make_operations_specialist_headers("ops-2"))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_RETURNED)


# --- Minority and guardianship at issuance (PRD §3.4) -----------------------------

def _setup_minor_payable_payment(case_number="XD-002"):
    return _setup_single_payable_payment(
        amount=60000, due_date="2026-08-10", clock_to="2026-08-10T00:00:00Z",
        case_number=case_number,
        payee_overrides={"full_name": "Min Or", "date_of_birth": "2012-03-10",
                         "tax_id": "888-99-0000"})


def test_issue_to_minor_requires_guardianship(api):
    """PRD §3.4: "When the payee is a minor at the current clock date, an `ACTIVE`
    guardianship case must exist for them or issuance is refused with
    `ERR_GUARDIANSHIP_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_active_guardianship_for_minor
    """
    ctx = _setup_minor_payable_payment()
    payment = ctx["payments"][0]
    resp = api.issue_payment(payment["id"], {"method": "CHECK"}, OPS)
    validate_error(resp, ApiErrorId.ERR_GUARDIANSHIP_REQUIRED)


def test_issue_to_minor_pays_guardian_name(api):
    """PRD §3.4: "resolves `payee_name_on_check` — the `guardian_full_name` of the
    payee's active guardianship when the payee is a minor, otherwise the payee's own
    `full_name`."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_active_guardianship_for_minor
    """
    ctx = _setup_minor_payable_payment()
    payment = ctx["payments"][0]
    case = create_and_activate_guardianship(ctx["payee"]["id"],
                                            guardian_full_name="Grace Guardian")
    assert case["status"] == "ACTIVE"

    issued = issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    assert issued["status"] == "ISSUED"
    assert issued["payee_name_on_check"] == "Grace Guardian", (
        "payments to a minor are made payable to the court-appointed guardian"
    )


def test_state_error_precedes_guardianship_error_on_issue(api):
    """PRD §2.10: "Every request is validated in a fixed global order, and the first
    failing check determines the error returned:" — target-entity state guards (item 5)
    run before business guards (item 6).
    PRD §3.4: "the payment must be `PAYABLE` (`ERR_PAYMENT_NOT_PAYABLE` otherwise)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_issue
    """
    # Payment due 2027-01-01 with the clock untouched: still SCHEDULED, while the
    # minor payee has no guardianship — both guards are armed.
    ctx = setup_active_case(
        payments=[{"due_date": "2027-01-01", "base_amount_cents": 50000}],
        agreement_overrides={"case_number": "PR-001"},
        payee_overrides={"full_name": "Min Or", "date_of_birth": "2012-03-10",
                         "tax_id": "888-99-0000"})
    assert ctx["payee"]["is_minor"] is True, "minor: the safety violation is armed"
    payment = ctx["payments"][0]
    assert payment["status"] == "SCHEDULED"

    resp = api.issue_payment(payment["id"], {"method": "CHECK"}, OPS)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_PAYABLE)
    assert get_payment(payment["id"])["status"] == "SCHEDULED", "payment unchanged"


def test_guardianship_error_fires_when_state_guard_passes(api):
    """PRD §3.4: "When the payee is a minor at the current clock date, an `ACTIVE`
    guardianship case must exist for them or issuance is refused with
    `ERR_GUARDIANSHIP_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_issue
    """
    # Same minor payee but the payment has matured to PAYABLE, so the state guard
    # passes and the guardianship business guard is the one that fires.
    ctx = _setup_minor_payable_payment(case_number="PR-001B")
    payment = ctx["payments"][0]
    assert payment["status"] == "PAYABLE"
    resp = api.issue_payment(payment["id"], {"method": "CHECK"}, OPS)
    validate_error(resp, ApiErrorId.ERR_GUARDIANSHIP_REQUIRED)


# --- Outstanding-liability conservation across the reissue loop (PRD §3.3) ---------

def test_outstanding_constant_through_reissue_cycle(api):
    """PRD §3.3: "`outstanding_liability_cents` always equals the sum of `amount_cents`
    over payments of the agreement's `ACTIVE` schedule whose status is `SCHEDULED`,
    `PAYABLE`, `ISSUED`, `RETURNED`, `STALE_DATED`, or `ESCHEATABLE`".
    PRD §3.4: "both statuses belong to the outstanding set, so
    `outstanding_liability_cents` does not move."

    Design: Difficulty/compensating_invariant/reissue_cycle_conserves_outstanding
    """
    ctx = _setup_single_payable_payment(case_number="IV-001")
    payment = ctx["payments"][0]
    agreement_id = ctx["agreement"]["id"]

    issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    assert get_agreement(agreement_id)["outstanding_liability_cents"] == 120000, (
        "ISSUED is inside the outstanding set — issuance moves nothing"
    )
    report_returned(payment["id"], user_id="ops-1")
    assert get_agreement(agreement_id)["outstanding_liability_cents"] == 120000, (
        "RETURNED is also inside the outstanding set"
    )
    case = get_returned_case_for_payment(payment["id"])
    validate_success(api.authorize_reissue(case["id"], make_operations_specialist_headers("ops-2")))
    assert get_agreement(agreement_id)["outstanding_liability_cents"] == 120000
    issue_payment(payment["id"], method="EFT", user_id="ops-2")
    assert get_agreement(agreement_id)["outstanding_liability_cents"] == 120000, (
        "the reissue cycle conserves outstanding exactly"
    )


def test_mark_cleared_moves_money_to_paid(api):
    """PRD §3.4: "the agreement's `paid_total_cents` grows by the payment's
    `amount_cents`, `outstanding_liability_cents` shrinks by the same, the agreement's
    `version` increments".
    PRD §3.3: "`paid_total_cents` accumulates amounts reaching `CLEARED`."

    Design: Difficulty/compensating_invariant/reissue_cycle_conserves_outstanding
    """
    ctx = _setup_single_payable_payment(case_number="IV-001")
    payment = ctx["payments"][0]
    issue_payment(payment["id"], method="CHECK", user_id="ops-1")
    report_returned(payment["id"], user_id="ops-1")
    case = get_returned_case_for_payment(payment["id"])
    validate_success(api.authorize_reissue(case["id"], make_operations_specialist_headers("ops-2")))
    issue_payment(payment["id"], method="EFT", user_id="ops-2")

    validate_success(api.mark_payment_cleared(payment["id"], OPS))
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["outstanding_liability_cents"] == 0
    assert agreement["paid_total_cents"] == 120000
    assert (agreement["paid_total_cents"] + agreement["outstanding_liability_cents"]
            == agreement["total_scheduled_cents"] == 120000), (
        "no double count across the whole loop"
    )
