"""Transfer petition adjudication: filing guards, cooling-off/IPA, court orders,
effectuation, expiry, and withdrawal (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_active_case, create_petition, file_petition, setup_filed_petition,
    progress_petition_to_hearing, record_court_order, setup_court_approved_petition,
    set_clock, get_petition, get_payment, get_agreement,
    TEST_USERS, make_case_manager_headers, make_judicial_recorder_headers,
)

READER = TEST_USERS["reader_headers"]
CASE_MGR = TEST_USERS["case_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

NY_PROFILE = {"state_code": "NY", "age_of_majority": 21, "sspa_max_discount_rate_bps": 2000,
              "disclosure_cooling_off_days": 20, "ipa_required": False, "dormancy_years": 5,
              "commutation_permitted": False}
NY_PAYEE = {"address_state_code": "NY", "address_city": "Albany", "address_postal_code": "12201"}


def _setup_two_payment_petition(price=185000, case_number="FX-001"):
    """CA case, payments 100000 due 2030-01-01 / 2031-01-01, clock 2029-01-01, and a
    petition priced under PV whose IRR (536 bps) passes the 700 cap."""
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000},
                  {"due_date": "2031-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": case_number})
    petition = create_petition(ctx, price, "2030-01-01", "2031-12-31")
    return ctx, petition


# --- Filing: safety cap vs fiscal price sanity (PRD §2.10, §3.6) -------------------

def _setup_dual_failure_petition():
    """Policy rate 900 bps (above the 700 cap): PV 175911 and IRR 900, so a price of
    175912 violates BOTH the rate cap and the price<=PV guard."""
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000},
                  {"due_date": "2031-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "PR-002"},
        policy_overrides={"contract_discount_rate_bps": 900})
    petition = create_petition(ctx, 175912, "2030-01-01", "2031-12-31")
    return ctx, petition


def test_dual_failure_petition_arms_both_safety_and_fiscal_guards(api):
    """PRD §3.6: "`present_value_cents` discounts each matched payment at the linked
    policy's `contract_discount_rate_bps`".
    PRD §3.6: "The `effective_annual_rate_bps`, the statutory figure, is ten thousand
    times the single positive rate at which the matched payments' discounted
    `amount_cents` exactly equal `purchase_price_cents`, rounded half up".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_file
    """
    _ctx, petition = _setup_dual_failure_petition()
    # round(100000/1.09) + round(100000/1.1881) = 91743 + 84168
    assert petition["present_value_cents"] == 175911, "price 175912 violates price<=PV"
    assert petition["effective_annual_rate_bps"] == 900, "900 > 700 violates the rate cap"


def test_safety_error_precedes_fiscal_error_on_file(api):
    """PRD §2.10: "Every request is validated in a fixed global order, and the first
    failing check determines the error returned:" — business guards list the SSPA
    effective-rate cap before price sanity.
    PRD §2.10: "the SSPA effective-rate cap (`ERR_EFFECTIVE_RATE_EXCEEDS_CAP`); the
    disclosure cooling-off period (`ERR_COOLING_OFF_NOT_ELAPSED`)".
    PRD §2.10: "and price sanity (`ERR_PRICE_EXCEEDS_PRESENT_VALUE`)".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_file
    """
    _ctx, petition = _setup_dual_failure_petition()
    resp = api.file_petition(petition["id"], make_case_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_EFFECTIVE_RATE_EXCEEDS_CAP)
    assert get_petition(petition["id"])["status"] == "DRAFT"


# --- Filing: transfer-window overlap over discrete payment sets (PRD §3.6) ----------

def _setup_five_payment_ny_case():
    return setup_active_case(
        payments=[{"due_date": f"{year}-06-01", "base_amount_cents": 40000}
                  for year in range(2027, 2032)],
        profile_overrides=NY_PROFILE, payee_overrides=NY_PAYEE,
        agreement_overrides={"case_number": "OV-001", "court_state_code": "NY"},
        policy_overrides={"contract_discount_rate_bps": 300})


def test_petition_window_overlap_rejected_on_shared_payment(api):
    """PRD §3.6: "the matched payment set must be disjoint from the matched sets of
    every other petition on the same agreement in `FILED`, `DISCLOSURE_SERVED`,
    `HEARING_SCHEDULED`, `COURT_APPROVED`, or `EFFECTIVE` (`ERR_TRANSFER_WINDOW_OVERLAP`)".
    PRD §3.6: "a due-date window from `transfer_start_date` through `transfer_end_date`,
    both dates inclusive".

    Design: Difficulty/resource_temporal_overlap/petition_window_discrete_set_overlap
    """
    ctx = _setup_five_payment_ny_case()
    # Window 2027-01-01..2029-12-31 matches the 2027/2028/2029 payments (inclusive).
    petition_a = create_petition(ctx, 90000, "2027-01-01", "2029-12-31")
    assert petition_a["transferred_payment_count"] == 3
    filed_a = file_petition(petition_a["id"], filer_user_id="cm-1")
    assert filed_a["status"] == "FILED"

    # Window 2029-06-01..2030-12-31 matches {2029-06-01, 2030-06-01} — intersects A.
    petition_b = create_petition(ctx, 50000, "2029-06-01", "2030-12-31")
    resp = api.file_petition(petition_b["id"], make_case_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)


def test_adjacent_window_with_disjoint_payment_set_allowed(api):
    """PRD §3.6: "the matched payment set must be disjoint from the matched sets of
    every other petition on the same agreement in `FILED`, `DISCLOSURE_SERVED`,
    `HEARING_SCHEDULED`, `COURT_APPROVED`, or `EFFECTIVE` (`ERR_TRANSFER_WINDOW_OVERLAP`)"
    — only the payment sets matter, not the date ranges.

    Design: Difficulty/resource_temporal_overlap/petition_window_discrete_set_overlap
    """
    ctx = _setup_five_payment_ny_case()
    petition_a = create_petition(ctx, 90000, "2027-01-01", "2029-12-31")
    file_petition(petition_a["id"], filer_user_id="cm-1")

    # Window 2030-01-01..2031-12-31 matches {2030-06-01, 2031-06-01} — disjoint from A.
    petition_c = create_petition(ctx, 50000, "2030-01-01", "2031-12-31")
    filed_c = file_petition(petition_c["id"], filer_user_id="cm-1")
    assert filed_c["status"] == "FILED", (
        "adjacency is allowed at the payment-set level"
    )


# --- Withdrawal, expiry, hearing gates, refile bar (PRD §3.6) ------------------------

def test_petition_withdraw_then_effectuate_rejected(api):
    """PRD §3.6: "Either the payee (self only, `ERR_FORBIDDEN_ROLE`) or a `CaseManager`
    may withdraw a petition — from `FILED`, from `DISCLOSURE_SERVED`, or from
    `HEARING_SCHEDULED` alike, each moving it to `WITHDRAWN`, while a withdrawal attempt
    from any other state fails with `ERR_PETITION_INVALID_STATE`."
    PRD §3.6: "An approved transfer is consummated when a `ComplianceOfficer`
    effectuates the petition, moving it `COURT_APPROVED` → `EFFECTIVE`."

    Design: Corner/state_machines/petition_withdraw_then_effectuate_rejected
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        profile_overrides=NY_PROFILE, payee_overrides=NY_PAYEE,
        agreement_overrides={"case_number": "EN-004", "court_state_code": "NY"})
    petition = create_petition(ctx, 90000, "2030-01-01", "2030-01-01")
    file_petition(petition["id"], filer_user_id="cm-1")
    withdrawn = validate_success(api.withdraw_petition(
        petition["id"], make_case_manager_headers("cm-1")))
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.effectuate_petition(petition["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_PETITION_INVALID_STATE)
    assert get_payment(ctx["payments"][0]["id"])["status"] == "SCHEDULED", (
        "no payment changes hands after a withdrawn petition"
    )


def test_petition_expires_after_effectuation_window(api):
    """PRD §3.6: "the clock sweep moves a `COURT_APPROVED` petition to `EXPIRED` once
    the clock date is more than 60 days past its `court_order_date` without
    effectuation."

    Design: Corner/state_machines/petition_expires_after_effectuation_window
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000},
                  {"due_date": "2031-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "EN-006"})
    petition = setup_filed_petition(ctx, 185000, "2030-01-01", "2031-12-31")
    petition = progress_petition_to_hearing(petition, ipa_completed_at="2029-01-05",
                                            cool_clock_to="2029-01-11T00:00:00Z")
    set_clock("2029-02-01T00:00:00Z")
    approved = record_court_order(petition["id"], "APPROVED", "2029-02-01")
    assert approved["status"] == "COURT_APPROVED"

    # 2029-04-02 is exactly court_order_date + 60 days: strict > not yet met.
    set_clock("2029-04-02T00:00:00Z")
    assert get_petition(petition["id"])["status"] == "COURT_APPROVED"
    # The 61st day fires the expiry sweep.
    set_clock("2029-04-03T00:00:00Z")
    assert get_petition(petition["id"])["status"] == "EXPIRED"

    resp = api.effectuate_petition(petition["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_PETITION_INVALID_STATE)
    assert get_payment(ctx["payments"][0]["id"])["status"] == "SCHEDULED"


def test_ipa_and_cooling_off_gates_at_hearing(api):
    """PRD §3.6: "the clock date must be on or after `disclosure_served_at` plus the
    governing profile's `disclosure_cooling_off_days` (`ERR_COOLING_OFF_NOT_ELAPSED`),
    and when the profile's `ipa_required` is set, `ipa_completed_at` must be supplied
    (`ERR_IPA_REQUIRED`)."

    Design: Corner/validations/ipa_and_cooling_off_gates_at_hearing
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000},
                  {"due_date": "2031-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "VL-003"})
    petition = setup_filed_petition(ctx, 185000, "2030-01-01", "2031-12-31")
    validate_success(api.serve_disclosure(petition["id"], CASE_MGR))

    # Disclosure served 2029-01-01; at 2029-01-10 only 9 days have elapsed (< 10).
    set_clock("2029-01-10T00:00:00Z")
    resp = api.schedule_hearing(petition["id"], {"hearing_date": "2029-02-01"}, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_COOLING_OFF_NOT_ELAPSED)

    # At exactly 10 days the cooling gate passes; the missing IPA then fails.
    set_clock("2029-01-11T00:00:00Z")
    resp = api.schedule_hearing(petition["id"], {"hearing_date": "2029-02-01"}, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_IPA_REQUIRED)

    scheduled = validate_success(api.schedule_hearing(
        petition["id"], {"hearing_date": "2029-02-01", "ipa_completed_at": "2029-01-05"},
        CASE_MGR))
    assert scheduled["status"] == "HEARING_SCHEDULED"


def test_refile_bar_with_prejudice_blocks_and_expires(api):
    """PRD §3.6: "no earlier `COURT_DENIED` petition for the same payee with `prejudice`
    = `WITH` may have a `court_order_date` within the prior 365 days — while the clock
    date remains earlier than one year after that order, refiling is barred
    (`ERR_REFILE_BARRED_WITH_PREJUDICE`)".

    Design: Corner/validations/refile_bar_with_prejudice_blocks_and_expires
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2031-06-01", "base_amount_cents": 100000},
                  {"due_date": "2032-06-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        profile_overrides=NY_PROFILE, payee_overrides=NY_PAYEE,
        agreement_overrides={"case_number": "VL-002", "court_state_code": "NY"})
    petition1 = setup_filed_petition(ctx, 170000, "2031-01-01", "2032-12-31")
    petition1 = progress_petition_to_hearing(petition1, cool_clock_to="2029-01-21T00:00:00Z")
    set_clock("2029-02-01T00:00:00Z")
    denied = record_court_order(petition1["id"], "DENIED", "2029-02-01", prejudice="WITH")
    assert denied["status"] == "COURT_DENIED"
    assert denied["prejudice"] == "WITH"

    petition2 = create_petition(ctx, 170000, "2031-01-01", "2032-12-31")

    # 2029-06-01 is earlier than one year after the 2029-02-01 order: barred.
    set_clock("2029-06-01T00:00:00Z")
    resp = api.file_petition(petition2["id"], make_case_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_REFILE_BARRED_WITH_PREJUDICE)

    # 2030-02-01 is exactly court_order_date + 365 days: the bar has lapsed.
    set_clock("2030-02-01T00:00:00Z")
    filed = file_petition(petition2["id"], filer_user_id="cm-1")
    assert filed["status"] == "FILED"


def test_sod_court_order_recorded_by_filer_rejected(api):
    """PRD §3.6: "The judicial outcome is recorded by a `JudicialRecorder` — never by
    the petitioner: the recorder's `X-User-ID` must differ from the petition's
    `filed_by_user_id` (`ERR_SOD_VIOLATION`)".
    PRD §3.6: "`approved_price_cents` is set — for `APPROVED_MODIFIED` from the input,
    which must be present and strictly below `purchase_price_cents` (else
    `ERR_INVALID_REQUEST`), and otherwise mirrored from `purchase_price_cents`."

    Design: Corner/rbac/sod_court_order_recorded_by_filer_rejected
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000},
                  {"due_date": "2031-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "RB-003"})
    petition = setup_filed_petition(ctx, 185000, "2030-01-01", "2031-12-31",
                                    filer_user_id="cm-1")
    petition = progress_petition_to_hearing(petition, ipa_completed_at="2029-01-05",
                                            cool_clock_to="2029-01-11T00:00:00Z")
    set_clock("2029-02-01T00:00:00Z")

    # A JudicialRecorder presenting the filer's user id is rejected.
    resp = api.record_court_order(
        petition["id"], {"outcome": "APPROVED", "court_order_date": "2029-02-01"},
        make_judicial_recorder_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    recorded = record_court_order(petition["id"], "APPROVED", "2029-02-01",
                                  recorder_user_id="jr-1")
    assert recorded["status"] == "COURT_APPROVED"
    assert recorded["approved_price_cents"] == 185000, (
        "an unmodified outcome mirrors the purchase price"
    )


# --- Effectuation cascade (PRD §3.6) -------------------------------------------------

def test_court_order_then_effectuate_transfers_windowed_payments(api):
    """PRD §3.6: "Every payment of the agreement's `ACTIVE` schedule in `SCHEDULED` or
    `PAYABLE` whose `due_date` still falls inside the window moves to `TRANSFERRED` with
    `transferred_by_petition_id` recording the petition".

    Design: Difficulty/transitive_cascade/court_approval_effectuation_chain
    """
    ctx, petition = _setup_two_payment_petition()
    petition = file_petition(petition["id"], filer_user_id="cm-1")
    petition = progress_petition_to_hearing(petition, ipa_completed_at="2029-01-05",
                                            cool_clock_to="2029-01-11T00:00:00Z")
    set_clock("2029-02-01T00:00:00Z")
    approved = record_court_order(petition["id"], "APPROVED", "2029-02-01")
    assert approved["status"] == "COURT_APPROVED"

    effective = validate_success(api.effectuate_petition(petition["id"], COMPLIANCE))
    assert effective["status"] == "EFFECTIVE"
    for payment in ctx["payments"]:
        row = get_payment(payment["id"])
        assert row["status"] == "TRANSFERRED"
        assert row["transferred_by_petition_id"] == petition["id"]


def test_effectuate_exhausts_policy_and_closes_agreement(api):
    """PRD §3.6: "Each transferred payment shrinks the agreement's
    `outstanding_liability_cents` by its `amount_cents` and grows
    `transferred_total_cents` by the same, bumping the agreement's `version`; the
    exhaustion cascade then runs, so a transfer covering every remaining payment leaves
    the policy `EXHAUSTED` and the agreement `CLOSED`."

    Design: Difficulty/transitive_cascade/court_approval_effectuation_chain
    """
    ctx, _petition = _setup_two_payment_petition()
    petition = setup_court_approved_petition(
        ctx, 185000, "2030-01-01", "2031-12-31",
        ipa_completed_at="2029-01-05", cool_clock_to="2029-01-11T00:00:00Z",
        order_date="2029-02-01")
    validate_success(api.effectuate_petition(petition["id"], COMPLIANCE))

    policy = validate_success(api.get_annuity_policy(ctx["policy"]["id"], READER))
    assert policy["status"] == "EXHAUSTED", "link 3: the last non-terminal payment left"
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "CLOSED", "link 4: exhaustion closes the agreement"
    assert agreement["transferred_total_cents"] == 200000
    assert agreement["outstanding_liability_cents"] == 0
