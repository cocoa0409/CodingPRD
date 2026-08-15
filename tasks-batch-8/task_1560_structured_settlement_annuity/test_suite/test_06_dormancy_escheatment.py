"""Check staling, dormancy, escheatment sweeps, and owner reclaim (PRD §3.4, §3.8)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_active_case, issue_payment, issue_and_return,
    create_profile,
    get_agreement, get_payment, get_batch,
    set_clock, open_batch, finalize_batch, reclaim_escheat,
    TEST_USERS, make_compliance_officer_headers,
)

READER = TEST_USERS["reader_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

OR_PROFILE = {"state_code": "OR", "sspa_max_discount_rate_bps": 1500,
              "disclosure_cooling_off_days": 15, "ipa_required": False,
              "dormancy_years": 1}
OR_PAYEE = {"address_state_code": "OR", "address_city": "Salem", "address_postal_code": "97301"}


def _setup_issued_check():
    """Funded agreement; one payment 75000 due 2026-08-02, issued by CHECK that day."""
    ctx = setup_active_case(
        payments=[{"due_date": "2026-08-02", "base_amount_cents": 75000}],
        clock_to="2026-08-02T00:00:00Z",
        agreement_overrides={"case_number": "BD-003"},
        payee_overrides={"full_name": "Stan Le", "date_of_birth": "1970-03-03",
                         "tax_id": "303-03-0303"})
    issue_payment(ctx["payments"][0]["id"], method="CHECK", user_id="ops-1")
    return ctx


def test_stale_check_remains_issued_at_day_180(api):
    """PRD §3.4: "during a clock sweep, an `ISSUED` payment whose `last_issue_method`
    is `CHECK` becomes `STALE_DATED` once the clock date is more than 180 days past
    `last_issued_at` — exactly 180 days leaves it `ISSUED`, and `EFT` issuances never
    go stale."

    Design: Difficulty/boundary_precision_check/stale_check_day_180_vs_181
    """
    ctx = _setup_issued_check()
    payment_id = ctx["payments"][0]["id"]
    # 2027-01-29 is exactly 180 days after the 2026-08-02 issuance: strict > not met.
    set_clock("2027-01-29T00:00:00Z")
    assert get_payment(payment_id)["status"] == "ISSUED"


def test_stale_check_flips_at_day_181(api):
    """PRD §3.4: "during a clock sweep, an `ISSUED` payment whose `last_issue_method`
    is `CHECK` becomes `STALE_DATED` once the clock date is more than 180 days past
    `last_issued_at`".
    PRD §3.4: "Staling sets the payment's `return_reason` to `UNCASHED_STALE` but opens
    no case."

    Design: Difficulty/boundary_precision_check/stale_check_day_180_vs_181
    """
    ctx = _setup_issued_check()
    payment_id = ctx["payments"][0]["id"]
    set_clock("2027-01-29T00:00:00Z")
    assert get_payment(payment_id)["status"] == "ISSUED"
    set_clock("2027-01-30T00:00:00Z")
    stale = get_payment(payment_id)
    assert stale["status"] == "STALE_DATED", "181 days crosses the threshold"
    assert stale["return_reason"] == "UNCASHED_STALE"


def test_escalate_escheat_before_dormancy_returns_error(api):
    """PRD §3.8: "escalation requires the case `OPEN` (`ERR_CASE_INVALID_STATE`) and
    the same dormancy condition already satisfied, else `ERR_DORMANCY_NOT_MET`."

    Design: Corner/validations/escalate_escheat_before_dormancy_returns_error
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2026-09-01", "base_amount_cents": 40000}],
        clock_to="2026-09-01T00:00:00Z",
        profile_overrides=OR_PROFILE, payee_overrides=OR_PAYEE,
        agreement_overrides={"case_number": "VL-004", "court_state_code": "OR"})
    payment = ctx["payments"][0]
    _payment, case = issue_and_return(payment["id"], method="CHECK", user_id="ops-1")

    # Dormancy anniversary of due 2026-09-01 with dormancy 1 year is 2027-09-01;
    # the clock at 2027-06-01 has not passed it.
    set_clock("2027-06-01T00:00:00Z")
    resp = api.escalate_escheat(case["id"], make_compliance_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_DORMANCY_NOT_MET)
    refreshed = validate_success(api.get_returned_payment_case(case["id"], READER))
    assert refreshed["status"] == "OPEN", "case unchanged by the failed escalation"


def _setup_escheatable_pair(case_number="IV-002"):
    """OR case: p1 80000 due 2026-09-01 issued CHECK; p2 90000 due 2027-09-01.
    After clock 2027-09-06, p1 is ESCHEATABLE and p2 merely PAYABLE."""
    ctx = setup_active_case(
        payments=[{"due_date": "2026-09-01", "base_amount_cents": 80000},
                  {"due_date": "2027-09-01", "base_amount_cents": 90000}],
        profile_overrides=OR_PROFILE, payee_overrides=OR_PAYEE,
        agreement_overrides={"case_number": case_number, "court_state_code": "OR"})
    set_clock("2026-09-05T00:00:00Z")
    issue_payment(ctx["payments"][0]["id"], method="CHECK", user_id="ops-1")
    set_clock("2027-09-06T00:00:00Z")
    ctx["payments"] = [get_payment(p["id"]) for p in ctx["payments"]]
    return ctx


def test_reclaim_without_open_batch_returns_error(api):
    """PRD §3.8: "Reclaiming is an `OperationsSpecialist` action requiring the payment
    `ESCHEATED` (`ERR_PAYMENT_NOT_ESCHEATED`), an `OPEN` escheatment batch for the
    payee's `address_state_code` (`ERR_NO_OPEN_ESCHEAT_BATCH`)".

    Design: Corner/validations/reclaim_without_open_batch_returns_error
    """
    ctx = _setup_escheatable_pair(case_number="VL-005")
    payment_id = ctx["payments"][0]["id"]
    batch = open_batch("OR", "2027-09", opener_user_id="co-1")
    finalize_batch(batch["id"], finalizer_user_id="co-2")
    assert get_payment(payment_id)["status"] == "ESCHEATED"

    # The sweeping batch is FINALIZED; an OPEN batch is required to absorb a reclaim.
    resp = api.reclaim_payment_escheat(payment_id, TEST_USERS["operations_specialist_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_OPEN_ESCHEAT_BATCH)
    assert get_payment(payment_id)["status"] == "ESCHEATED"


def test_reclaim_payable_payment_returns_not_escheated(api):
    """PRD §3.8: "Reclaiming is an `OperationsSpecialist` action requiring the payment
    `ESCHEATED` (`ERR_PAYMENT_NOT_ESCHEATED`)".

    Design: Corner/errors/reclaim_payable_payment_returns_not_escheated
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2026-08-10", "base_amount_cents": 40000}],
        clock_to="2026-08-10T00:00:00Z",
        agreement_overrides={"case_number": "ER-007"})
    payment = ctx["payments"][0]
    assert payment["status"] == "PAYABLE"
    resp = api.reclaim_payment_escheat(payment["id"], TEST_USERS["operations_specialist_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_ESCHEATED)


def test_open_batch_unique_per_state(api):
    """PRD §3.8: "at most one `OPEN` batch may exist per state, and a second attempt
    fails with `ERR_OPEN_BATCH_EXISTS`."

    Design: Corner/validations/open_batch_unique_per_state
    """
    create_profile(**OR_PROFILE)
    create_profile()
    open_batch("OR", "2027-09", opener_user_id="co-1")

    resp = api.create_escheatment_batch(
        {"state_code": "OR", "batch_period": "2027-10"},
        make_compliance_officer_headers("co-2"))
    validate_error(resp, ApiErrorId.ERR_OPEN_BATCH_EXISTS)

    other = open_batch("CA", "2027-10", opener_user_id="co-2")
    assert other["status"] == "OPEN", "a different state is independent"


def test_sod_batch_finalize_by_opener_rejected(api):
    """PRD §2.9: "The compliance officer finalizing an escheatment batch must not be
    the user who opened it — the batch's `opened_by_user_id`."
    PRD §2.9: "every violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_batch_finalize_by_opener_rejected
    """
    create_profile(**OR_PROFILE)
    batch = open_batch("OR", "2027-09", opener_user_id="co-1")

    resp = api.finalize_escheatment_batch(batch["id"], make_compliance_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    finalized = finalize_batch(batch["id"], finalizer_user_id="co-2")
    assert finalized["status"] == "FINALIZED"


def test_batch_finalize_twice_returns_invalid_state(api):
    """PRD §3.8: "Finalizing is likewise a compliance-officer act but must not be
    performed by the opener (`ERR_SOD_VIOLATION`) and requires the batch `OPEN`
    (`ERR_BATCH_INVALID_STATE`)."

    Design: Corner/errors/batch_finalize_twice_returns_invalid_state
    """
    create_profile(**OR_PROFILE)
    batch = open_batch("OR", "2027-09", opener_user_id="co-1")
    finalize_batch(batch["id"], finalizer_user_id="co-2")
    resp = api.finalize_escheatment_batch(batch["id"], make_compliance_officer_headers("co-3"))
    validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)


def test_batch_finalize_empty_sweep_allowed(api):
    """PRD §3.8: "`swept_count` and `swept_amount_cents` record the count and the
    summed `amount_cents` of the sweep — finalizing an empty batch is allowed and
    records zeros."

    Design: Corner/state_machines/batch_finalize_empty_sweep_allowed
    """
    create_profile(**OR_PROFILE)
    batch = open_batch("OR", "2027-09", opener_user_id="co-1")
    finalized = finalize_batch(batch["id"], finalizer_user_id="co-2")
    assert finalized["status"] == "FINALIZED"
    assert finalized["swept_count"] == 0
    assert finalized["swept_amount_cents"] == 0


def test_finalize_moves_outstanding_to_escheated_conserving_total(api):
    """PRD §3.8: "Finalization sweeps every `ESCHEATABLE` payment whose payee's
    `address_state_code` equals the batch's `state_code` into `ESCHEATED`".
    PRD §3.8: "Each swept payment moves its `amount_cents` from the agreement's
    `outstanding_liability_cents` to its `escheated_total_cents` with a version bump".

    Design: Difficulty/compensating_invariant/finalize_reclaim_conserve_tracked
    """
    ctx = _setup_escheatable_pair()
    p1 = ctx["payments"][0]
    assert p1["status"] == "ESCHEATABLE", (
        "dormancy anniversary 2027-09-01 strictly passed before finalize"
    )
    agreement_id = ctx["agreement"]["id"]

    before = get_agreement(agreement_id)
    assert (before["paid_total_cents"], before["outstanding_liability_cents"],
            before["escheated_total_cents"]) == (0, 170000, 0)

    batch = open_batch("OR", "2027-09", opener_user_id="co-1")
    finalized = finalize_batch(batch["id"], finalizer_user_id="co-2")
    assert finalized["status"] == "FINALIZED"
    assert finalized["swept_count"] == 1
    assert finalized["swept_amount_cents"] == 80000

    after = get_agreement(agreement_id)
    assert (after["paid_total_cents"], after["outstanding_liability_cents"],
            after["escheated_total_cents"]) == (0, 90000, 80000)
    assert (after["paid_total_cents"] + after["outstanding_liability_cents"]
            + after["escheated_total_cents"]) == 170000, (
        "the tracked-liability sum is conserved across the sweep"
    )


def test_reclaim_restores_outstanding_and_credits_open_batch(api):
    """PRD §3.8: "Success returns the payment to `PAYABLE`: the agreement's
    `escheated_total_cents` shrinks and its `outstanding_liability_cents` grows by the
    payment's `amount_cents` with a version bump, the payment's `escheated_in_batch_id`
    and `return_reason` clear to null, and the open batch for that state is credited —
    its `reclaimed_count` grows by one and its `reclaimed_amount_cents` by the payment's
    amount".

    Design: Difficulty/compensating_invariant/finalize_reclaim_conserve_tracked
    """
    ctx = _setup_escheatable_pair()
    p1_id = ctx["payments"][0]["id"]
    agreement_id = ctx["agreement"]["id"]

    batch = open_batch("OR", "2027-09", opener_user_id="co-1")
    finalize_batch(batch["id"], finalizer_user_id="co-2")
    assert get_payment(p1_id)["status"] == "ESCHEATED"

    batch2 = open_batch("OR", "2027-10", opener_user_id="co-1")
    reclaimed = reclaim_escheat(p1_id, user_id="ops-1")
    assert reclaimed["status"] == "PAYABLE"

    agreement = get_agreement(agreement_id)
    assert (agreement["paid_total_cents"], agreement["outstanding_liability_cents"],
            agreement["escheated_total_cents"]) == (0, 170000, 0), (
        "the compensating reclaim restores the tracked sum exactly"
    )
    batch2_after = get_batch(batch2["id"])
    assert batch2_after["reclaimed_count"] == 1
    assert batch2_after["reclaimed_amount_cents"] == 80000
