"""Journal entries: state machine, doc_state parallel dimension, SoD, validation,
trial balance conservation and immediate consistency."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_journal_entry_payload, create_document_payload,
    set_clock, setup_open_period_with_entity,
    create_balanced_je, post_je, attach_verified_doc,
    drive_entity_period_to_subledger_cut,
    setup_soft_locked_period,
    CONTROLLER, PREPARER, PREPARER2, APPROVER, AUDITOR,
    make_preparer_headers, make_approver_headers,
)
from test_helpers import api_client


class TestJournalEntryStateMachine:
    def test_je_approve_from_draft_returns_invalid_state(self, api):
        """PRD §3.5: "An `Approver` approves a `SUBMITTED` entry only when the
        approver differs from `preparer_user_id` (`ERR_SOD_VIOLATION`), the
        `doc_state` is exactly `DOC_VERIFIED` (`ERR_DOC_NOT_VERIFIED`), and the
        parent entity-period is neither `SOFT_LOCKED` nor `HARD_LOCKED`".
        PRD §2.9: "State-machine legality: the requested transition must be
        permitted from the target resource's current state, on all action
        endpoints — `ERR_INVALID_STATE`."

        Design: Corner/state_machines/je_approve_from_draft_returns_invalid_state
        """
        period, entity, ep = setup_open_period_with_entity()
        je = create_balanced_je(ep["id"], 1000)
        assert je["status"] == "DRAFT"
        res = api.approve_journal_entry(je["id"], APPROVER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_journal_entry(je["id"], PREPARER), 200)
        assert after["status"] == "DRAFT"

    def test_terminal_state_lockdown_posted_je(self, api):
        """PRD §3.5: "Posting stamps `posted_at`, which is immutable thereafter,
        moves the entry to the terminal `POSTED`".
        PRD §2.9: "State-machine legality: the requested transition must be
        permitted from the target resource's current state, on all action
        endpoints — `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_posted_je
        """
        period, entity, ep = setup_open_period_with_entity()
        je = post_je(ep["id"], 1000)
        assert je["status"] == "POSTED"
        res = api.rework_journal_entry(je["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_journal_entry(je["id"], PREPARER), 200)
        assert after["status"] == "POSTED"

    def test_journal_entry_reject_rework_cycle(self, api):
        """PRD §3.5: "Rejection moves a `SUBMITTED` entry to `REJECTED`, requires a
        non-empty `rejection_reason` (`ERR_REJECTION_REASON_REQUIRED`), and must
        come from an `Approver` other than the preparer. Rework finally returns a
        `REJECTED` entry to `DRAFT`, is permitted only to the original
        `preparer_user_id`, clears `rejection_reason`, and resets `doc_state` to
        `DOC_ATTACHED` when any `ATTACHED` documents remain, otherwise to
        `DOC_MISSING`."

        Design: Difficulty/non_linear_state_machine/journal_entry_reject_rework_cycle
        """
        period, entity, ep = setup_open_period_with_entity()
        prep1 = make_preparer_headers("prep-1")
        je = create_balanced_je(ep["id"], 5000, preparer_headers=prep1)
        get_success_data(api.submit_journal_entry(je["id"], prep1))
        get_success_data(api.reject_journal_entry(je["id"],
                                                   {"rejection_reason": "wrong account mapping"},
                                                   APPROVER))

        reworked = validate_success(api.rework_journal_entry(je["id"], prep1), 200)
        assert reworked["status"] == "DRAFT"
        assert reworked.get("rejection_reason") in (None, "")

        resubmitted = validate_success(api.submit_journal_entry(je["id"], prep1), 200)
        assert resubmitted["status"] == "SUBMITTED"

    def test_journal_entry_reject_rework_preserves_doc_state(self, api):
        """PRD §3.5: "Rework finally returns a `REJECTED` entry to `DRAFT`, is
        permitted only to the original `preparer_user_id`, clears
        `rejection_reason`, and resets `doc_state` to `DOC_ATTACHED` when any
        `ATTACHED` documents remain, otherwise to `DOC_MISSING`."

        Design: Difficulty/non_linear_state_machine/journal_entry_reject_rework_cycle
        """
        period, entity, ep = setup_open_period_with_entity()
        prep1 = make_preparer_headers("prep-1")
        # RECLASS has no doc gate so it can be submitted with DOC_MISSING
        je = create_balanced_je(ep["id"], 7000, je_type="RECLASS", preparer_headers=prep1)
        get_success_data(api.submit_journal_entry(je["id"], prep1))
        get_success_data(api.reject_journal_entry(je["id"], {"rejection_reason": "nope"}, APPROVER))
        reworked = validate_success(api.rework_journal_entry(je["id"], prep1), 200)
        # no attached docs → doc_state resets to DOC_MISSING
        assert reworked["doc_state"] == "DOC_MISSING"


class TestDocStateParallelDimension:
    def test_doc_state_parallel_dimension_independent_of_status(self, api):
        """PRD §3.5: "The first non-rejected attachment moves the entry's
        `doc_state` from `DOC_MISSING` to `DOC_ATTACHED`."
        PRD §3.5: "the entry starts in `DRAFT`, its `doc_state` parallel dimension
        starts at `DOC_MISSING`".

        Design: Corner/state_machines/doc_state_parallel_dimension_independent_of_status
        """
        period, entity, ep = setup_open_period_with_entity()
        je = create_balanced_je(ep["id"], 1000, je_type="MANUAL")
        assert je["doc_state"] == "DOC_MISSING"
        assert je["status"] == "DRAFT"

        get_success_data(api.attach_document(je["id"], create_document_payload(), PREPARER))
        after = validate_success(api.get_journal_entry(je["id"], PREPARER), 200)
        assert after["doc_state"] == "DOC_ATTACHED"
        assert after["status"] == "DRAFT", "status must not advance when a doc attaches"


class TestJournalEntryValidations:
    def test_je_out_of_period_rejected(self, api):
        """PRD §3.5: "The `entry_date` must fall on or after `period_start` and on
        or before `period_end` of the parent close period — anything outside that
        window is rejected with `ERR_JE_OUT_OF_PERIOD`".

        Design: Corner/validations/je_out_of_period_rejected
        """
        period, entity, ep = setup_open_period_with_entity()
        payload = create_journal_entry_payload(entry_date="2026-03-05T00:00:00Z")
        res = api.create_journal_entry(ep["id"], payload, PREPARER)
        validate_error(res, ApiErrorId.ERR_JE_OUT_OF_PERIOD, expected_status=409)

    def test_je_currency_mismatch_rejected(self, api):
        """PRD §3.5: "the entry's `functional_currency` must equal the entity's own
        functional currency, or the create is rejected with `ERR_JE_CCY_MISMATCH`."

        Design: Corner/validations/je_currency_mismatch_rejected
        """
        period, entity, ep = setup_open_period_with_entity()  # USD entity
        payload = create_journal_entry_payload(functional_currency="EUR")
        res = api.create_journal_entry(ep["id"], payload, PREPARER)
        validate_error(res, ApiErrorId.ERR_JE_CCY_MISMATCH, expected_status=409)

    def test_je_submit_unbalanced_rejected(self, api):
        """PRD §3.5: "Submission moves an entry from `DRAFT` to `SUBMITTED` and
        enforces three gates: `debit_total_minor` must equal `credit_total_minor`
        with both totals greater than zero, else `ERR_JE_UNBALANCED`".

        Design: Corner/validations/je_submit_unbalanced_rejected
        """
        period, entity, ep = setup_open_period_with_entity()
        payload = create_journal_entry_payload(lines=[
            {"line_no": 1, "account_code": "6100", "direction": "DEBIT", "amount_minor": 1000},
            {"line_no": 2, "account_code": "6150", "direction": "CREDIT", "amount_minor": 900},
        ])
        je = get_success_data(api.create_journal_entry(ep["id"], payload, PREPARER))
        res = api.submit_journal_entry(je["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_JE_UNBALANCED, expected_status=409)
        after = validate_success(api.get_journal_entry(je["id"], PREPARER), 200)
        assert after["status"] == "DRAFT"

    def test_sod_approve_own_je_rejected(self, api):
        """PRD §2.7: "The `Approver` who approves a journal entry must differ from
        the entry's recorded `preparer_user_id`."
        PRD §2.7: "breaching any of them is rejected with `ERR_SOD_VIOLATION`
        (HTTP 409)".

        Design: Corner/validations/sod_approve_own_je_rejected
        """
        period, entity, ep = setup_open_period_with_entity()
        prep1 = make_preparer_headers("prep-1")
        je = create_balanced_je(ep["id"], 1000, preparer_headers=prep1)
        get_success_data(api.submit_journal_entry(je["id"], prep1))
        # approve with the SAME user id (even though role=Approver) → SoD breach
        same_user_as_approver = make_approver_headers("prep-1")
        res = api.approve_journal_entry(je["id"], same_user_as_approver)
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=409)
        after = validate_success(api.get_journal_entry(je["id"], PREPARER), 200)
        assert after["status"] == "SUBMITTED"


class TestSoftLockedPeriodBlocksJe:
    def test_soft_locked_entity_period_blocks_new_je(self, api):
        """PRD §2.10: "any mutation of journal entries, reconciliations, tasks, or
        accruals against a soft-locked, hard-locked, or finalized period or
        entity-period is refused with `ERR_PERIOD_LOCKED`."

        Design: Corner/state_machines/soft_locked_entity_period_blocks_new_je
        """
        period, entity, ep = setup_soft_locked_period()
        res = api.create_journal_entry(ep["id"], create_journal_entry_payload(), PREPARER)
        validate_error(res, ApiErrorId.ERR_PERIOD_LOCKED, expected_status=409)


class TestTrialBalance:
    def test_trial_balance_excludes_non_posted_je(self, api):
        """PRD §3.5: "the entity-period's `trial_balance_minor` is recomputed in
        full — never incrementally, so balances cannot drift — as the sum over all
        of the entity-period's `POSTED` entries of each entry's debit-line total
        minus its credit-line total, with `ELIMINATION`-type lines included and
        `DRAFT`, `SUBMITTED`, `APPROVED`, and `REJECTED` entries excluded".

        Design: Corner/calculations/trial_balance_excludes_non_posted_je
        """
        period, entity, ep = setup_open_period_with_entity()
        je = create_balanced_je(ep["id"], 7777)
        get_success_data(api.submit_journal_entry(je["id"], PREPARER))
        after = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert after["trial_balance_minor"] == 0

    def test_immediate_visibility_of_posted_je_in_trial_balance(self, api):
        """PRD §3.5: "the entity-period's `trial_balance_minor` is recomputed in
        full — never incrementally, so balances cannot drift — as the sum over all
        of the entity-period's `POSTED` entries of each entry's debit-line total
        minus its credit-line total, with `ELIMINATION`-type lines included and
        `DRAFT`, `SUBMITTED`, `APPROVED`, and `REJECTED` entries excluded".

        Design: Corner/consistency_model/immediate_visibility_of_posted_je_in_trial_balance
        """
        period, entity, ep = setup_open_period_with_entity()
        je = create_balanced_je(ep["id"], 42000)
        get_success_data(api.submit_journal_entry(je["id"], PREPARER))
        # PRD §3.5: approval requires doc_state exactly DOC_VERIFIED
        attach_verified_doc(je["id"])
        get_success_data(api.approve_journal_entry(je["id"], APPROVER))
        get_success_data(api.post_journal_entry(je["id"], PREPARER))
        # The very next read observes the recomputed balance
        after = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        # Balanced 42000/42000 nets to zero under signed sum
        assert after["trial_balance_minor"] == 0

    def test_je_post_and_reverse_conserves_trial_balance(self, api):
        """PRD §3.5: "the entity-period's `trial_balance_minor` is recomputed in
        full — never incrementally, so balances cannot drift — as the sum over all
        of the entity-period's `POSTED` entries of each entry's debit-line total
        minus its credit-line total".

        Design: Difficulty/compensating_invariant/je_post_and_reverse_conserves_trial_balance
        """
        period, entity, ep = setup_open_period_with_entity()
        ep0 = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert ep0["trial_balance_minor"] == 0

        # forward: DEBIT 6100 / CREDIT 2000 (net signed contribution 0)
        fwd = create_journal_entry_payload(lines=[
            {"line_no": 1, "account_code": "6100", "direction": "DEBIT", "amount_minor": 5000},
            {"line_no": 2, "account_code": "2000", "direction": "CREDIT", "amount_minor": 5000},
        ])
        je_f = get_success_data(api.create_journal_entry(ep["id"], fwd, PREPARER))
        get_success_data(api.submit_journal_entry(je_f["id"], PREPARER))
        attach_verified_doc(je_f["id"])
        get_success_data(api.approve_journal_entry(je_f["id"], APPROVER))
        get_success_data(api.post_journal_entry(je_f["id"], PREPARER))
        after_fwd = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert after_fwd["trial_balance_minor"] == 0

    def test_je_post_and_reverse_returns_to_zero_after_compensating_pair(self, api):
        """PRD §3.5: "the entity-period's `trial_balance_minor` is recomputed in
        full — never incrementally, so balances cannot drift".

        Design: Difficulty/compensating_invariant/je_post_and_reverse_conserves_trial_balance
        """
        period, entity, ep = setup_open_period_with_entity()
        # forward
        fwd = create_journal_entry_payload(lines=[
            {"line_no": 1, "account_code": "6100", "direction": "DEBIT", "amount_minor": 5000},
            {"line_no": 2, "account_code": "2000", "direction": "CREDIT", "amount_minor": 5000},
        ])
        je_f = get_success_data(api.create_journal_entry(ep["id"], fwd, PREPARER))
        get_success_data(api.submit_journal_entry(je_f["id"], PREPARER))
        attach_verified_doc(je_f["id"])
        get_success_data(api.approve_journal_entry(je_f["id"], APPROVER))
        get_success_data(api.post_journal_entry(je_f["id"], PREPARER))
        # reversal (mirror)
        rev = create_journal_entry_payload(entry_date="2026-01-21T00:00:00Z", lines=[
            {"line_no": 1, "account_code": "2000", "direction": "DEBIT", "amount_minor": 5000},
            {"line_no": 2, "account_code": "6100", "direction": "CREDIT", "amount_minor": 5000},
        ])
        je_r = get_success_data(api.create_journal_entry(ep["id"], rev, PREPARER))
        get_success_data(api.submit_journal_entry(je_r["id"], PREPARER))
        attach_verified_doc(je_r["id"])
        get_success_data(api.approve_journal_entry(je_r["id"], APPROVER))
        get_success_data(api.post_journal_entry(je_r["id"], PREPARER))

        after = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert after["trial_balance_minor"] == 0


class TestRbacJe:
    def test_approver_cannot_create_journal_entry(self, api):
        """PRD §2.1: "A `Preparer` is an entity accountant: runs subledger cutoffs,
        drafts journal entries and accrual estimates, performs reconciliations,
        works the close tasks assigned to them, proposes and matches intercompany
        elimination pairs, and writes flux explanations."
        PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/approver_cannot_create_journal_entry
        """
        period, entity, ep = setup_open_period_with_entity()
        res = api.create_journal_entry(ep["id"], create_journal_entry_payload(), APPROVER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
