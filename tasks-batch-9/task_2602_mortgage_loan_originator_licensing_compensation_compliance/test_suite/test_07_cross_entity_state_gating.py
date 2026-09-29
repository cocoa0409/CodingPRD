"""Gates that read another aggregate's state.

In both scenarios below the acting entity is in a state that normally permits
the call and nothing about it changes; what decides the outcome is the state of
a neighbouring row — the licence that authorises a loan, and the investigation
that names it.
"""
from datetime import datetime

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    enter_finding,
    get_loan,
    get_originator,
    license_status_action,
    list_investigations,
    list_records_for_loan,
    release_compensation,
    remediate,
    run_sweep,
    set_clock,
    setup_authorized_originator,
    setup_originator_with_plan,
    take_loan,
    lock_loan,
    close_loan,
)
from test_helpers.test_users import (
    OFFICER_USER_ID,
    analyst_headers,
    make_originator_headers,
    officer_headers,
)

LOCK_AMOUNT_CENTS = 20_000_000


def _instant(value):
    """Parse an ISO 8601 UTC instant, tolerating the optional fractional part."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _one_locked_and_one_taken_loan(api):
    """Two loans under one ACTIVE licence: one already locked, one still TAKEN."""
    context = setup_authorized_originator(api)
    originator_id = context["originator"]["id"]
    set_clock(api, "2026-08-05T00:00:00Z")

    control = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        borrower_reference="BW-2602-81",
        requested_amount_cents=19_000_000,
        par_rate_bps=648,
    )
    control = lock_loan(
        api, control["id"], originator_id, note_rate_bps=655, locked_amount_cents=19_000_000
    )
    subject = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        borrower_reference="BW-2602-82",
        requested_amount_cents=21_000_000,
        par_rate_bps=648,
    )
    context["control"] = control
    context["subject"] = subject
    return context


def _withheld_compensation_with_open_investigation(api):
    """A CLOSED loan whose commission was withheld, plus the cascade's investigation."""
    context = setup_originator_with_plan(
        api,
        license_overrides={
            "expiration_date": "2026-09-01T00:00:00Z",
            "renewal_window_opens_at": "2026-07-01T00:00:00Z",
        },
    )
    originator_id = context["originator"]["id"]
    set_clock(api, "2026-08-05T00:00:00Z")

    loan = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        borrower_reference="BW-2602-91",
        requested_amount_cents=LOCK_AMOUNT_CENTS,
        par_rate_bps=650,
    )
    lock_loan(
        api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=LOCK_AMOUNT_CENTS
    )

    set_clock(api, "2026-09-02T00:00:00Z")
    context["sweep"] = run_sweep(api)

    context["loan"] = close_loan(
        api,
        loan["id"],
        funded_amount_cents=LOCK_AMOUNT_CENTS,
        funded_at="2026-09-02T00:00:00Z",
        lender_paid_comp_cents=400_000,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    open_rows = list_investigations(
        api, loan_application_id=loan["id"], status="OPEN", limit=10, offset=0
    )
    assert len(open_rows) == 1, (
        f"the cascade opens exactly one investigation for the suspended loan, got {open_rows}"
    )
    context["investigation"] = open_rows[0]
    return context


def test_lock_is_legal_while_the_authorising_licence_is_active(api):
    """PRD 3.4: "Locking the rate advances the loan `TAKEN → LOCKED`."
    PRD 3.4: "A successfully taken application stamps `application_taken_at` from the
    logical clock — this is the instant the authority window check was evaluated
    against, and it is recorded so that a later examination can reconstruct the decision
    — and initialises `status` to `TAKEN`, `compensation_status` to `NOT_APPLICABLE` and
    `authority_flag` to `VERIFIED`."
    PRD 3.1: "Because the state dropped out of `authorized_state_codes`, every loan
    application belonging to that originator, carrying that `state_code`, and sitting in
    `status` `TAKEN` or `LOCKED` has its `authority_flag` set to `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/lock_rejected_after_owning_license_revoked
    """
    context = _one_locked_and_one_taken_loan(api)

    assert context["control"]["status"] == "LOCKED", (
        "the identical lock request is accepted while the licence is ACTIVE, "
        f"got {context['control']['status']}"
    )
    assert context["control"]["authority_flag"] == "VERIFIED"
    assert context["subject"]["status"] == "TAKEN"
    assert context["subject"]["authority_flag"] == "VERIFIED", (
        "intake initialises authority_flag to VERIFIED, "
        f"got {context['subject']['authority_flag']}"
    )

    license_status_action(
        api,
        context["license"]["id"],
        "REVOKE",
        note="State order revoking the licence for cause.",
    )

    locked_after = get_loan(api, context["control"]["id"])
    assert locked_after["status"] == "LOCKED", (
        f"the revocation does not move the loan's own status, got {locked_after['status']}"
    )
    assert locked_after["authority_flag"] == "SUSPENDED", (
        "the cascade reaches LOCKED loans as well as TAKEN ones, "
        f"got {locked_after['authority_flag']}"
    )


def test_lock_rejected_with_license_not_active_after_the_revocation(api):
    """PRD 2.9: "A licence exists for the pair of originator and state with `status` in
    `ACTIVE` or `RENEWAL_PENDING` — otherwise `ERR_LICENSE_NOT_ACTIVE`. Checked when
    taking and when locking an application."
    PRD 3.4: "Locking requires the loan to be `TAKEN`, requires its `authority_flag` to
    read `VERIFIED`, and **re-verifies** authority from scratch at the current logical
    clock instant: all three of the licence-active, state-authorised and
    sponsorship-covered checks above are evaluated again, with the same three error
    codes."
    PRD 3.4: "Its `note_rate_bps` and `locked_amount_cents` read null while the loan is
    `TAKEN`"

    Design: Difficulty/cross_entity_state_dependency/lock_rejected_after_owning_license_revoked
    """
    context = _one_locked_and_one_taken_loan(api)
    originator_id = context["originator"]["id"]
    subject_id = context["subject"]["id"]

    license_status_action(
        api,
        context["license"]["id"],
        "REVOKE",
        note="State order revoking the licence for cause.",
    )

    response = api.lock_loan_application(
        subject_id,
        factories.build_loan_lock(note_rate_bps=655, locked_amount_cents=21_000_000),
        make_originator_headers(originator_id),
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value)

    unchanged = get_loan(api, subject_id)
    assert unchanged["status"] == "TAKEN", (
        f"the rejected lock wrote nothing to the loan, got {unchanged['status']}"
    )
    assert unchanged["locked_amount_cents"] is None, (
        f"locked_amount_cents stays null on a TAKEN loan, got {unchanged['locked_amount_cents']}"
    )
    assert unchanged["note_rate_bps"] is None
    assert unchanged["authority_flag"] == "SUSPENDED", (
        "the SUSPENDED flag came from the revocation cascade, not from the failed lock, "
        f"got {unchanged['authority_flag']}"
    )


def test_revocation_cascade_strips_authority_and_opens_one_investigation_per_loan(api):
    """PRD 3.1: "The licence's `ACTIVE` sponsorship moves to `RELINQUISHED` with
    `relinquished_at` stamped from the logical clock."
    PRD 3.1: "Because that sponsorship closed, the licence's
    `active_sponsoring_institution_code` and `active_sponsorship_effective_at` go null
    and the originator's `authorized_state_codes` is recomputed, losing that
    `state_code`."
    PRD 3.1: "Because those loans were suspended, one unlicensed-activity investigation
    is opened for each of them, with `opened_by` set to `CASCADE`, `trigger_reason`
    forced to `AUTHORITY_LAPSE`, and `status` `OPEN`."
    PRD 3.9: "triggers a recompute of the originator's `open_investigation_count` — which
    at all times equals the number of that originator's investigations whose `status` is
    `OPEN` or `SUBSTANTIATED`"

    Design: Difficulty/cross_entity_state_dependency/lock_rejected_after_owning_license_revoked
    """
    context = _one_locked_and_one_taken_loan(api)
    originator_id = context["originator"]["id"]

    revoked = license_status_action(
        api,
        context["license"]["id"],
        "REVOKE",
        note="State order revoking the licence for cause.",
    )
    assert revoked["status"] == "REVOKED", f"got {revoked['status']}"
    assert revoked["active_sponsoring_institution_code"] is None, (
        "the closed sponsorship leaves the denormalised code null, "
        f"got {revoked['active_sponsoring_institution_code']}"
    )
    assert revoked["active_sponsorship_effective_at"] is None

    sponsorship = validate_success(
        api.get_sponsorship_transfer(context["sponsorship"]["id"], analyst_headers())
    )
    assert sponsorship["status"] == "RELINQUISHED", (
        f"hop one closes the sponsorship row, got {sponsorship['status']}"
    )
    assert _instant(sponsorship["relinquished_at"]) == _instant("2026-08-05T00:00:00Z"), (
        f"relinquished_at is stamped from the logical clock, got {sponsorship['relinquished_at']}"
    )

    originator = get_originator(api, originator_id)
    assert originator["authorized_state_codes"] == [], (
        f"the revoked state is the only one, so the list empties, got {originator['authorized_state_codes']}"
    )
    assert originator["open_investigation_count"] == 2, (
        "one investigation per suspended loan, and both are OPEN, "
        f"got {originator['open_investigation_count']}"
    )

    investigations = list_investigations(api, originator_id=originator_id, limit=10, offset=0)
    assert len(investigations) == 2, f"got {len(investigations)} investigations"
    for investigation in investigations:
        assert investigation["status"] == "OPEN"
        assert investigation["opened_by"] == "CASCADE"
        assert investigation["trigger_reason"] == "AUTHORITY_LAPSE"


def test_release_blocked_while_the_investigation_on_the_loan_is_open(api):
    """PRD 3.5: "**Branch B — authority in doubt.** When `authority_flag` reads anything
    other than `VERIFIED` — that is, `SUSPENDED` or `UNAUTHORIZED` —
    `compensation_status` is set to `PENDING` and **no** ledger line is created at all."
    PRD 3.5: "Release requires that `compensation_status` is `PENDING`, that the loan's
    `status` is `CLOSED` or `PAID_OFF`, and — the cross-aggregate guard — that **every**
    unlicensed-activity investigation naming that loan has reached `UNSUBSTANTIATED` or
    `REMEDIATED`. While any such investigation is still `OPEN` or `SUBSTANTIATED`, the
    release is rejected with `ERR_UNLICENSED_ACTIVITY_OPEN` (HTTP 422)."
    PRD 3.9: "`swept_at` gives the instant it ran, and `expired_license_ids`,
    `relinquished_sponsorship_ids`, `suspended_loan_ids`, `opened_investigation_ids`,
    `escalated_inquiry_ids` and `unassigned_originator_ids` list the identifiers touched
    by each of the three sweeps."

    Design: Difficulty/cross_entity_state_dependency/compensation_release_blocked_until_investigation_remediated
    """
    context = _withheld_compensation_with_open_investigation(api)
    loan = context["loan"]

    assert loan["status"] == "CLOSED", f"got {loan['status']}"
    assert loan["authority_flag"] == "SUSPENDED", (
        f"the expiry sweep suspended the loan before it closed, got {loan['authority_flag']}"
    )
    assert loan["compensation_status"] == "PENDING", (
        "authority was not VERIFIED at close, so commission is withheld, "
        f"got {loan['compensation_status']}"
    )
    assert list_records_for_loan(api, loan["id"]) == [], (
        "Branch B creates no ledger line at all"
    )
    assert context["investigation"]["id"] in context["sweep"]["opened_investigation_ids"], (
        "the sweep reports the investigation it opened: "
        f"{context['sweep']['opened_investigation_ids']}"
    )

    response = api.release_loan_compensation(loan["id"], officer_headers())
    validate_error(response, ApiErrorId.ERR_UNLICENSED_ACTIVITY_OPEN.value)

    unchanged = get_loan(api, loan["id"])
    assert unchanged["compensation_status"] == "PENDING", (
        f"the rejected release changes nothing, got {unchanged['compensation_status']}"
    )
    assert list_records_for_loan(api, loan["id"]) == []


def test_release_still_blocked_after_a_substantiated_finding(api):
    """PRD 3.9: "A substantiated finding advances the investigation `OPEN →
    SUBSTANTIATED`, records the ordered borrower restitution in `restitution_cents`, and
    sets the referenced loan's `authority_flag` to `UNAUTHORIZED`."
    PRD 3.5: "While any such investigation is still `OPEN` or `SUBSTANTIATED`, the
    release is rejected with `ERR_UNLICENSED_ACTIVITY_OPEN` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/compensation_release_blocked_until_investigation_remediated
    """
    context = _withheld_compensation_with_open_investigation(api)
    loan_id = context["loan"]["id"]

    found = enter_finding(api, context["investigation"]["id"], "SUBSTANTIATED", 50_000)
    assert found["status"] == "SUBSTANTIATED", f"got {found['status']}"
    assert found["restitution_cents"] == 50_000, (
        f"the ordered restitution is recorded as filed, got {found['restitution_cents']}"
    )
    assert found["finding_by_user_id"] == OFFICER_USER_ID, (
        f"the deciding officer is stamped, got {found['finding_by_user_id']}"
    )

    loan = get_loan(api, loan_id)
    assert loan["authority_flag"] == "UNAUTHORIZED", (
        f"a substantiated finding rewrites the loan's authority record, got {loan['authority_flag']}"
    )

    response = api.release_loan_compensation(loan_id, officer_headers())
    validate_error(response, ApiErrorId.ERR_UNLICENSED_ACTIVITY_OPEN.value)
    assert get_loan(api, loan_id)["compensation_status"] == "PENDING", (
        "SUBSTANTIATED is not one of the two cleared statuses, so the release fails again"
    )
    assert get_originator(api, context["originator"]["id"])["open_investigation_count"] == 1, (
        "a SUBSTANTIATED investigation still counts as unresolved"
    )


def test_remediation_unblocks_release_and_mints_the_withheld_ledger_line(api):
    """PRD 3.9: "the investigation advances `SUBSTANTIATED → REMEDIATED` provided its
    `restitution_cents` is at least 1; `remediated_at` is stamped from the logical clock,
    the referenced loan's `authority_flag` returns to `VERIFIED`, and
    `open_investigation_count` is recomputed."
    PRD 3.5: "On release the loan's `authority_flag` is set to `VERIFIED`, one ledger
    line with `variant` `PROVISIONAL` is created using exactly the provisional inputs
    described above, the originator's `lifetime_accrued_cents` and
    `net_compensation_cents` are recomputed along with `exposure_score` and
    `monitoring_status`, a `COMP_ACCRUED` audit entry is appended, and the loan's
    `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/compensation_release_blocked_until_investigation_remediated
    """
    context = _withheld_compensation_with_open_investigation(api)
    loan_id = context["loan"]["id"]
    originator_id = context["originator"]["id"]

    enter_finding(api, context["investigation"]["id"], "SUBSTANTIATED", 50_000)
    remediated = remediate(
        api,
        context["investigation"]["id"],
        remediation_note=(
            "Restitution paid to the borrower and the file re-underwritten by a "
            "licensed originator."
        ),
    )
    assert remediated["status"] == "REMEDIATED", f"got {remediated['status']}"
    assert _instant(remediated["remediated_at"]) == _instant("2026-09-02T00:00:00Z"), (
        f"remediated_at is stamped from the logical clock, got {remediated['remediated_at']}"
    )
    assert get_loan(api, loan_id)["authority_flag"] == "VERIFIED", (
        "remediation returns the loan's authority_flag to VERIFIED"
    )

    released = release_compensation(api, loan_id)
    assert released["compensation_status"] == "ACCRUED", (
        f"the identical release now succeeds, got {released['compensation_status']}"
    )
    assert released["authority_flag"] == "VERIFIED"

    records = list_records_for_loan(api, loan_id)
    assert len(records) == 1, f"release mints exactly one ledger line, got {len(records)}"
    assert records[0]["variant"] == "PROVISIONAL"
    assert records[0]["status"] == "ACCRUED"
    assert records[0]["accrued_cents"] == 400_000, (
        "200 bps of the locked 20000000 cents is 400000 cents, "
        f"got {records[0]['accrued_cents']}"
    )

    originator = get_originator(api, originator_id)
    assert originator["lifetime_accrued_cents"] == 400_000, (
        f"got {originator['lifetime_accrued_cents']}"
    )
    assert originator["net_compensation_cents"] == 400_000
    assert originator["open_investigation_count"] == 0, (
        "REMEDIATED is terminal and no longer counts, "
        f"got {originator['open_investigation_count']}"
    )
