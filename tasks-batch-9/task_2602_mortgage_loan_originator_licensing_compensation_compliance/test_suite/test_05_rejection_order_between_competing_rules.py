"""Requests that break two rules at once, and which rule is allowed to answer.

Each pair is set up so the same call violates both rules, then relaxed so the
loser can be observed on its own. That two-call shape is what proves the order
rather than merely the existence of a rejection.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.fixtures import (
    activate_license,
    claim_sponsorship,
    close_loan,
    create_originator,
    file_license,
    get_license,
    get_loan,
    get_originator,
    list_records_for_loan,
    lock_loan,
    setup_originator_with_plan,
    take_loan,
)
from test_helpers.test_users import analyst_headers, loan_ops_headers

_BACK_DATED_INSTANT = "2026-07-15T00:00:00Z"

# --- local scenario builders ------------------------------------------------


def _build_licence_with_one_active_sponsorship(api):
    """An ACTIVE CA licence sponsored by INST-ALPHA from 2026-08-01.

    The licence version captured before the claim is the stale value; the
    version after it is the fresh one.
    """
    originator = create_originator(api)
    licence = file_license(api, originator["id"], state_code=TEST_DEFAULTS["STATE_CODE"])
    licence = activate_license(api, licence["id"])
    stale_version = licence["version"]
    sponsorship = claim_sponsorship(
        api,
        licence["id"],
        stale_version,
        sponsoring_institution_code=TEST_DEFAULTS["INSTITUTION_CODE"],
        effective_at="2026-08-01T00:00:00Z",
    )
    fresh = get_license(api, licence["id"])
    return {
        "originator": originator,
        "license": fresh,
        "sponsorship": sponsorship,
        "stale_version": stale_version,
        "fresh_version": fresh["version"],
    }


def _claim_back_dated_transfer(api, license_id, expected_version):
    """Claim INST-BETA sponsorship from before the existing interval opens."""
    payload = factories.build_sponsorship_transfer(
        expected_version,
        sponsoring_institution_code=TEST_DEFAULTS["SECOND_INSTITUTION_CODE"],
        effective_at=_BACK_DATED_INSTANT,
    )
    return api.create_sponsorship_transfer(license_id, payload, analyst_headers())


def _sponsorships_for_license(api, license_id):
    """Every sponsorship row on one licence, read straight from the collection."""
    response = api.list_sponsorship_transfers(
        analyst_headers(), params={"license_registration_id": license_id}
    )
    data, _meta = validate_paginated(response)
    return data


def _build_elevated_originator_with_a_second_locked_loan(api):
    """One dual-paid closed loan that lifts the originator to ELEVATED, plus a locked loan.

    The first loan closes while supervision still reads STANDARD, which is the
    only window in which a dual-paid close is permitted at all.
    """
    context = setup_originator_with_plan(
        api,
        plan_overrides={
            "base_basis_points": 200,
            "min_fee_cents": 100_000,
            "max_fee_cents": 900_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
    )
    originator_id = context["originator"]["id"]
    state_code = context["state_code"]

    first = take_loan(
        api,
        originator_id,
        state_code=state_code,
        requested_amount_cents=20_000_000,
        par_rate_bps=650,
    )
    lock_loan(api, first["id"], originator_id, note_rate_bps=750, locked_amount_cents=20_000_000)
    context["first_loan"] = close_loan(
        api,
        first["id"],
        funded_amount_cents=20_000_000,
        funded_at="2026-09-01T00:00:00Z",
        lender_paid_comp_cents=400_000,
        borrower_paid_comp_cents=100_000,
    )
    context["originator_after_close"] = get_originator(api, originator_id)

    second = take_loan(
        api,
        originator_id,
        state_code=state_code,
        requested_amount_cents=20_000_000,
        par_rate_bps=650,
    )
    context["second_loan"] = lock_loan(
        api, second["id"], originator_id, note_rate_bps=700, locked_amount_cents=20_000_000
    )
    return context


def _attempt_close(api, loan_id, lender_paid_comp_cents, borrower_paid_comp_cents):
    """Close a loan without asserting success, so a rejection can be inspected."""
    payload = factories.build_loan_close(
        funded_amount_cents=20_000_000,
        funded_at="2026-09-10T00:00:00Z",
        lender_paid_comp_cents=lender_paid_comp_cents,
        borrower_paid_comp_cents=borrower_paid_comp_cents,
    )
    return api.close_loan_application(loan_id, payload, loan_ops_headers())


# --- Rule 10 (stale licence version) outranks rule 29 (sponsorship overlap) --


def test_stale_licence_version_answers_before_the_back_dated_overlap(api):
    """PRD §2.9: "The system evaluates them in one fixed order and **the first failing rule alone
    decides the response** — later failures are never reported and never mask an earlier one."
    PRD §2.9: "10. The optimistic-concurrency check of §2.7 — otherwise
    `ERR_STALE_LICENSE_VERSION` on a sponsorship claim, or `ERR_STALE_ORIGINATOR_VERSION` on a
    plan assignment."
    PRD §2.7: "Both version checks are evaluated **before** any state precondition on the parent
    row is examined, so a stale version always surfaces as the 412 rather than being masked by an
    invalid-state rejection."

    Design: Difficulty/priority_pair_validation_conflict/stale_license_version_outranks_sponsorship_period_overlap
    """
    scenario = _build_licence_with_one_active_sponsorship(api)

    assert scenario["fresh_version"] > scenario["stale_version"], (
        "the successful claim moved the licence version, which is what makes the first "
        "expected_license_registration_version stale"
    )

    response = _claim_back_dated_transfer(
        api, scenario["license"]["id"], scenario["stale_version"]
    )
    validate_error(response, ApiErrorId.ERR_STALE_LICENSE_VERSION.value)


def test_the_fresh_version_lets_the_back_dated_overlap_answer(api):
    """PRD §3.1: "An incoming `effective_at` is rejected with `ERR_SPONSORSHIP_PERIOD_OVERLAP`
    (HTTP 409) in two situations: when it falls inside the half-open interval of an
    already-closed sponsorship on the same licence — that is, when some row whose `status` is
    `RELINQUISHED` or `SUPERSEDED` has an `effective_at` at or before the incoming instant and a
    `relinquished_at` strictly after it — and when it is back-dated, meaning it falls strictly
    before the `effective_at` of some existing sponsorship row on that licence."
    PRD §2.9: "29. An incoming sponsorship interval does not collide with an existing one on the
    same licence — otherwise `ERR_SPONSORSHIP_PERIOD_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/stale_license_version_outranks_sponsorship_period_overlap
    """
    scenario = _build_licence_with_one_active_sponsorship(api)

    stale = _claim_back_dated_transfer(api, scenario["license"]["id"], scenario["stale_version"])
    validate_error(stale, ApiErrorId.ERR_STALE_LICENSE_VERSION.value)

    fresh = _claim_back_dated_transfer(api, scenario["license"]["id"], scenario["fresh_version"])
    validate_error(fresh, ApiErrorId.ERR_SPONSORSHIP_PERIOD_OVERLAP.value)


def test_neither_rejected_sponsorship_claim_leaves_a_trace(api):
    """PRD §2.9: "The system evaluates them in one fixed order and **the first failing rule alone
    decides the response** — later failures are never reported and never mask an earlier one."
    PRD §2.7: "If that value does not equal the licence's current `version`, the request is
    rejected with `ERR_STALE_LICENSE_VERSION` (HTTP 412), because a client working from a stale
    view of the licence would otherwise overwrite an authority interval it never read."

    Design: Difficulty/priority_pair_validation_conflict/stale_license_version_outranks_sponsorship_period_overlap
    """
    scenario = _build_licence_with_one_active_sponsorship(api)
    license_id = scenario["license"]["id"]

    validate_error(
        _claim_back_dated_transfer(api, license_id, scenario["stale_version"]),
        ApiErrorId.ERR_STALE_LICENSE_VERSION.value,
    )
    validate_error(
        _claim_back_dated_transfer(api, license_id, scenario["fresh_version"]),
        ApiErrorId.ERR_SPONSORSHIP_PERIOD_OVERLAP.value,
    )

    rows = _sponsorships_for_license(api, license_id)
    assert len(rows) == 1, f"a rejected claim must not create a sponsorship row: {rows}"
    assert rows[0]["id"] == scenario["sponsorship"]["id"]
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["sponsoring_institution_code"] == TEST_DEFAULTS["INSTITUTION_CODE"]
    assert rows[0]["relinquished_at"] is None

    licence = get_license(api, license_id)
    assert licence["active_sponsoring_institution_code"] == TEST_DEFAULTS["INSTITUTION_CODE"]
    assert licence["version"] == scenario["fresh_version"], (
        "neither rejection may move the licence version"
    )
    originator = get_originator(api, scenario["originator"]["id"])
    assert originator["authorized_state_codes"] == [TEST_DEFAULTS["STATE_CODE"]]


# --- Rule 20 (dual compensation) outranks rule 35 (compensation cap) --------


def test_a_single_dual_paid_close_lands_exposure_exactly_on_the_threshold(api):
    """PRD §3.5: "It is permitted-but-monitored while the originator's `monitoring_status` is
    `STANDARD`, and hard-blocked while that status is `ELEVATED`, where the close is rejected
    with `ERR_DUAL_COMPENSATION_PROHIBITED` (HTTP 422)."
    PRD §3.7: "Finally, `monitoring_status` is set to `ELEVATED` when `exposure_score` is sixty
    or more, and to `STANDARD` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/dual_compensation_outranks_comp_cap_exceeded_at_close
    """
    context = _build_elevated_originator_with_a_second_locked_loan(api)

    assert context["first_loan"]["status"] == "CLOSED", (
        "the first dual-paid close is permitted because supervision still read STANDARD"
    )
    assert context["first_loan"]["compensation_status"] == "ACCRUED"

    originator = context["originator_after_close"]
    assert originator["exposure_score"] == 60, (
        "one dual-paid loan a hundred basis points above par scores 0.35*100 + 0.25*100 = 60: "
        f"got {originator['exposure_score']}"
    )
    assert originator["monitoring_status"] == "ELEVATED", "sixty is on the escalation threshold"
    assert originator["lifetime_accrued_cents"] == 400_000


def test_dual_compensation_answers_before_the_fee_cap(api):
    """PRD §3.5: "Per §2.9, the dual-compensation rejection is reported ahead of the cap
    rejection when both apply."
    PRD §2.9: "20. Dual compensation is not being reported at close under enhanced supervision —
    otherwise `ERR_DUAL_COMPENSATION_PROHIBITED`."
    PRD §2.9: "35. Reported compensation at close does not exceed the plan's ceiling — otherwise
    `ERR_COMP_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/dual_compensation_outranks_comp_cap_exceeded_at_close
    """
    context = _build_elevated_originator_with_a_second_locked_loan(api)

    response = _attempt_close(api, context["second_loan"]["id"], 700_000, 300_000)
    validate_error(response, ApiErrorId.ERR_DUAL_COMPENSATION_PROHIBITED.value)


def test_dropping_the_borrower_paid_leg_lets_the_fee_cap_answer(api):
    """PRD §3.5: "Separately, the sum of `lender_paid_comp_cents` and
    `borrower_paid_comp_cents` must not exceed the assigned plan's `max_fee_cents`; exceeding it
    is rejected with `ERR_COMP_CAP_EXCEEDED` (HTTP 422)."
    PRD §3.5: "Reporting **both** a positive `lender_paid_comp_cents` and a positive
    `borrower_paid_comp_cents` on the same file is dual compensation."
    PRD §2.9: "The system evaluates them in one fixed order and **the first failing rule alone
    decides the response** — later failures are never reported and never mask an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/dual_compensation_outranks_comp_cap_exceeded_at_close
    """
    context = _build_elevated_originator_with_a_second_locked_loan(api)
    loan_id = context["second_loan"]["id"]

    validate_error(
        _attempt_close(api, loan_id, 700_000, 300_000),
        ApiErrorId.ERR_DUAL_COMPENSATION_PROHIBITED.value,
    )
    validate_error(
        _attempt_close(api, loan_id, 1_000_000, 0),
        ApiErrorId.ERR_COMP_CAP_EXCEEDED.value,
    )

    loan = get_loan(api, loan_id)
    assert loan["status"] == "LOCKED", "neither rejected close may advance the loan"
    assert loan["compensation_status"] == "NOT_APPLICABLE"
    assert loan["funded_amount_cents"] is None
    assert list_records_for_loan(api, loan_id) == [], (
        "a rejected close writes no ledger line"
    )
    assert get_originator(api, context["originator"]["id"])["lifetime_accrued_cents"] == 400_000
