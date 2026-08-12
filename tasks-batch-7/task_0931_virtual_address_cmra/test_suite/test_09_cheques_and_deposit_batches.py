"""Cheques and deposit batches: the intake window, the caps, payee matching and the money partition."""

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    accept_form_1583,
    assert_check_deposit,
    assert_deposit_batch,
    assert_deposit_money_partition,
    check_payload,
    deposit_batch_version,
    log_and_match_letter,
    log_check,
    open_deposit_batch,
    read_deposit_batch,
    read_recipient,
    set_clock,
    setup_releasable_box,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

# The un-adjudicated point in PRD §2.8 leaves it open whether the Form 1583 gate is
# evaluated at all on POST /deposit-batches/{id}/checks, so the blocked-member case
# below is asserted only on the outcome both readings share: the cheque is refused and
# nothing is written.  The cheque's amount is deliberately above the per-cheque cap so
# that the request is refused under either reading.
BLOCKED_MEMBER_REFUSALS = [
    ApiErrorId.ERR_FORM_1583_INCOMPLETE.value,
    ApiErrorId.ERR_DEPOSIT_CAP_EXCEEDED.value,
]


def _setup_batch_with_blocked_member():
    ctx = setup_releasable_box(
        "J-1001", "Nia Check", holder_email="nia@example.com", accept_form=False
    )
    item = log_and_match_letter(ctx)
    batch = open_deposit_batch(ctx["box_id"], "2026-05-01")
    ctx["item_id"] = item["id"]
    ctx["batch"] = batch
    ctx["batch_id"] = batch["id"]
    return ctx


def test_an_oversized_cheque_for_a_blocked_member_writes_nothing(api):
    """PRD §3.9: "Then the caps, all of which produce `ERR_DEPOSIT_CAP_EXCEEDED`: a
    single cheque's `amount_cents` may not be **strictly greater than** 500,000 cents, so
    a cheque of exactly 500,000 is accepted; the batch's `received_amount_cents` plus the
    incoming `amount_cents` may not be **strictly greater than** 2,500,000 cents; and the
    batch's `check_count` must be **strictly less than** 25, so a batch already holding
    exactly 25 cheques rejects the next one."
    PRD §2.9 rung 17: "The matched roster member holds no Form 1583 in status
    `ACCEPTED`. Then `ERR_FORM_1583_INCOMPLETE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/form_1583_safety_rung_preempts_deposit_cap_fiscal_rung
    """
    ctx = _setup_batch_with_blocked_member()
    assert read_recipient(ctx["recipient_id"])["release_eligibility"] == "BLOCKED"

    response = api.create_check_deposit(
        ctx["batch_id"],
        check_payload(ctx["item_id"], "Nia Check", 600000, ctx["batch"]["version"], True),
        CMRA_OPERATOR,
    )
    assert response.status_code >= 400, (
        f"Expected the cheque to be refused, got {response.status_code}"
    )
    validate_error_is_one_of(response, BLOCKED_MEMBER_REFUSALS)

    batch = read_deposit_batch(ctx["batch_id"])
    assert batch["check_count"] == 0
    assert batch["received_amount_cents"] == 0
    assert_deposit_money_partition(batch)


def test_an_oversized_cheque_for_a_releasable_member_breaches_the_per_cheque_cap(api):
    """PRD §3.9: "Then the caps, all of which produce `ERR_DEPOSIT_CAP_EXCEEDED`: a
    single cheque's `amount_cents` may not be **strictly greater than** 500,000 cents, so
    a cheque of exactly 500,000 is accepted; the batch's `received_amount_cents` plus the
    incoming `amount_cents` may not be **strictly greater than** 2,500,000 cents; and the
    batch's `check_count` must be **strictly less than** 25, so a batch already holding
    exactly 25 cheques rejects the next one."
    PRD §2.9 rung 31: "The per-check amount, the per-batch total and the per-batch count
    all stay inside their caps. Otherwise `ERR_DEPOSIT_CAP_EXCEEDED` (422)."

    600,000 cents sits above the strictly-greater per-cheque cap of 500,000.

    Design: Difficulty/priority_pair_validation_conflict/form_1583_safety_rung_preempts_deposit_cap_fiscal_rung
    """
    ctx = _setup_batch_with_blocked_member()
    accept_form_1583(ctx["form_id"], "co-1")
    assert read_recipient(ctx["recipient_id"])["release_eligibility"] == "RELEASABLE"

    response = api.create_check_deposit(
        ctx["batch_id"],
        check_payload(
            ctx["item_id"], "Nia Check", 600000, deposit_batch_version(ctx["batch_id"]), True
        ),
        CMRA_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_DEPOSIT_CAP_EXCEEDED.value)

    batch = read_deposit_batch(ctx["batch_id"])
    assert batch["check_count"] == 0
    assert batch["received_amount_cents"] == 0


# ==========================================================================
# The intake window
# ==========================================================================
def _setup_batch_with_two_letters():
    ctx = setup_releasable_box("R-1801", "Ray Payee", holder_email="ray@example.com")
    first = log_and_match_letter(ctx)
    second = log_and_match_letter(ctx)
    batch = open_deposit_batch(ctx["box_id"], "2026-05-01")
    ctx["first_item_id"] = first["id"]
    ctx["second_item_id"] = second["id"]
    ctx["batch_id"] = batch["id"]
    ctx["batch_version"] = batch["version"]
    return ctx


def test_a_cheque_logged_one_second_before_the_cutoff_is_accepted(api):
    """PRD §3.9: "First the cutoff: cheques may only be logged while the logical clock's
    UTC hour is **strictly less than 21**, so a request at exactly 21:00:00Z is already
    too late and is `ERR_BATCH_CUTOFF_PASSED`."
    PRD §3.9: "If the exact set is non-empty, the match is its first member in ascending
    `created_at` order and `match_mode` is `EXACT_LEGAL`; the alias set is then **never
    consulted**, even if an alias on a different member would also have matched."

    20:59:59Z is inside the half-open intake window, one second below the closed edge.

    Design: Difficulty/resource_temporal_overlap/deposit_batch_intake_window_closes_at_cutoff_hour
    """
    ctx = _setup_batch_with_two_letters()
    set_clock("2026-05-01T20:59:59Z")

    response = api.create_check_deposit(
        ctx["batch_id"],
        check_payload(
            ctx["first_item_id"], "Ray Payee", 10000, deposit_batch_version(ctx["batch_id"]), True
        ),
        CMRA_OPERATOR,
    )
    cheque = validate_success(response, 201)
    assert_check_deposit(cheque)
    assert cheque["status"] == "MATCHED"
    assert cheque["match_mode"] == "EXACT_LEGAL"
    assert cheque["matched_recipient_id"] == ctx["recipient_id"]


def test_a_cheque_logged_exactly_at_the_cutoff_hour_is_refused(api):
    """PRD §3.9: "First the cutoff: cheques may only be logged while the logical clock's
    UTC hour is **strictly less than 21**, so a request at exactly 21:00:00Z is already
    too late and is `ERR_BATCH_CUTOFF_PASSED`."
    PRD §2.9 rung 29: "The logical clock's UTC hour is strictly less than 21. Otherwise
    `ERR_BATCH_CUTOFF_PASSED` (409)."

    21:00:00Z lands exactly ON the closed edge of the intake window.

    Design: Difficulty/resource_temporal_overlap/deposit_batch_intake_window_closes_at_cutoff_hour
    """
    ctx = _setup_batch_with_two_letters()
    set_clock("2026-05-01T20:59:59Z")
    log_check(ctx["batch_id"], ctx["first_item_id"], "Ray Payee", 10000)

    set_clock("2026-05-01T21:00:00Z")
    response = api.create_check_deposit(
        ctx["batch_id"],
        check_payload(
            ctx["second_item_id"], "Ray Payee", 10000, deposit_batch_version(ctx["batch_id"]), True
        ),
        CMRA_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_BATCH_CUTOFF_PASSED.value)

    batch = read_deposit_batch(ctx["batch_id"])
    assert batch["check_count"] == 1
    assert batch["received_amount_cents"] == 10000


# ==========================================================================
# Payee matching, holds and the money partition
# ==========================================================================
def _setup_batch_with_three_cheques():
    ctx = setup_releasable_box("U-2101", "Ray Payee", holder_email="ray2@example.com")
    first = log_and_match_letter(ctx)
    second = log_and_match_letter(ctx)
    third = log_and_match_letter(ctx)
    batch = open_deposit_batch(ctx["box_id"], "2026-05-01")
    ctx["batch_id"] = batch["id"]
    ctx["cheque_a"] = log_check(batch["id"], first["id"], "Ray Payee", 12000)
    ctx["cheque_b"] = log_check(batch["id"], second["id"], "R. Payee", 8000)
    ctx["cheque_c"] = log_check(batch["id"], third["id"], "Zed Nomatch", 5000)
    return ctx


def test_returning_a_held_cheque_and_closing_the_batch_conserves_the_money(api):
    """PRD §2.11: "For one deposit batch, `received_amount_cents` equals
    `deposited_amount_cents` plus `returned_amount_cents` plus `held_amount_cents`, at
    all times."
    PRD §3.9: "Throughout, `held_amount_cents` is the sum of `amount_cents` over the
    batch's cheques in `RECEIVED`, `MATCHED` or `HELD` — that is, everything neither
    banked nor returned — which is what makes the money partition of §2.11 hold at every
    instant."

    Design: Difficulty/compensating_invariant/deposit_batch_money_partition_survives_return_and_close
    """
    ctx = _setup_batch_with_three_cheques()

    validate_success(api.return_check_deposit(ctx["cheque_c"]["id"], CMRA_OPERATOR))
    validate_success(api.close_deposit_batch(ctx["batch_id"], CMRA_OPERATOR))

    batch = read_deposit_batch(ctx["batch_id"])
    assert_deposit_batch(batch)
    assert batch["check_count"] == 3
    assert batch["received_amount_cents"] == 25000
    assert batch["deposited_amount_cents"] == 12000
    assert batch["returned_amount_cents"] == 5000
    assert batch["held_amount_cents"] == 8000
    assert_deposit_money_partition(batch)
    assert batch["status"] == "CLOSED"


def test_each_cheque_lands_in_the_status_its_payee_line_earned(api):
    """PRD §3.9: "It goes `RECEIVED → MATCHED` when payee matching resolves a member on
    the same mailbox **and** `endorsed` is true, which sets `matched_recipient_id` and
    `match_mode`."
    PRD §3.9: "It goes `RECEIVED → HELD` when matching resolves nobody, or when
    `endorsed` is false, which sets `hold_reason` to `PAYEE_MISMATCH` or `NOT_ENDORSED`
    respectively."
    PRD §3.9: "Every cheque in `MATCHED` moves to `DEPOSITED`, its `amount_cents` moves
    out of `held_amount_cents` and into `deposited_amount_cents`, and its `version` is
    bumped by one."

    Design: Difficulty/compensating_invariant/deposit_batch_money_partition_survives_return_and_close
    """
    ctx = _setup_batch_with_three_cheques()

    validate_success(api.return_check_deposit(ctx["cheque_c"]["id"], CMRA_OPERATOR))
    validate_success(api.close_deposit_batch(ctx["batch_id"], CMRA_OPERATOR))

    banked = validate_success(api.get_check_deposit(ctx["cheque_a"]["id"], CMRA_OPERATOR))
    assert banked["status"] == "DEPOSITED"
    assert banked["match_mode"] == "EXACT_LEGAL"

    held = validate_success(api.get_check_deposit(ctx["cheque_b"]["id"], CMRA_OPERATOR))
    assert held["status"] == "HELD"
    assert held["hold_reason"] == "PAYEE_MISMATCH"

    returned = validate_success(api.get_check_deposit(ctx["cheque_c"]["id"], CMRA_OPERATOR))
    assert returned["status"] == "RETURNED"
    assert returned["hold_reason"] == "PAYEE_MISMATCH"


def test_a_held_cheque_re_enters_matched_once_the_roster_gains_the_alias(api):
    """PRD §3.9: "Re-running the match — a `CmraOperator` act, typically after the roster
    gained the alias the payee line used — takes it `HELD → MATCHED` when matching now
    resolves a member and `endorsed` is true, setting `matched_recipient_id`,
    `match_mode` and `hold_reason` `NONE`, and bumping `CheckDeposit.version` by one."
    PRD §3.9: "If the exact set is empty but the alias set is not, the match is the alias
    set's first member in ascending `created_at` order and `match_mode` is `ALIAS`."

    Design: Corner/state_machines/held_check_reenters_matched_after_an_alias_is_added
    """
    ctx = setup_releasable_box("Z-1008", "Pia Trade", holder_email="pia@example.com")
    item = log_and_match_letter(ctx)
    batch = open_deposit_batch(ctx["box_id"], "2026-05-01")
    cheque = log_check(batch["id"], item["id"], "Pia Ventures", 4000)

    assert cheque["status"] == "HELD"
    assert cheque["hold_reason"] == "PAYEE_MISMATCH"

    validate_success(
        api.patch_recipient(
            ctx["recipient_id"], {"dba_aliases": ["Pia Ventures"]}, CMRA_OPERATOR
        )
    )
    rematched = validate_success(
        api.rematch_check_deposit(cheque["id"], CMRA_OPERATOR)
    )
    assert rematched["status"] == "MATCHED"
    assert rematched["match_mode"] == "ALIAS"
    assert rematched["matched_recipient_id"] == ctx["recipient_id"]
    assert rematched["hold_reason"] == "NONE"


def test_rematching_a_cheque_whose_payee_still_resolves_to_nobody_is_rejected(api):
    """PRD §3.9: "If matching still resolves nobody, the request is
    `ERR_PAYEE_MISMATCH`."
    PRD §2.9 rung 30: "Payee matching resolves a roster member. Otherwise
    `ERR_PAYEE_MISMATCH` (422). Applies to `POST /check-deposits/{id}/rematch`."

    Design: Corner/errors/error_payee_mismatch_on_rematch
    """
    ctx = setup_releasable_box("Z-5004", "Xan Payee", holder_email="xan@example.com")
    item = log_and_match_letter(ctx)
    batch = open_deposit_batch(ctx["box_id"], "2026-05-01")
    cheque = log_check(batch["id"], item["id"], "Unknown Corp", 3000)

    response = api.rematch_check_deposit(cheque["id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_PAYEE_MISMATCH.value)

    unchanged = validate_success(api.get_check_deposit(cheque["id"], CMRA_OPERATOR))
    assert unchanged["status"] == "HELD"
    assert unchanged["hold_reason"] == "PAYEE_MISMATCH"
    assert unchanged["match_mode"] == "NONE"
    assert read_deposit_batch(batch["id"])["held_amount_cents"] == 3000
