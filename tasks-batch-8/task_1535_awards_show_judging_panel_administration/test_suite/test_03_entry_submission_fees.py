"""Entry submission gates, fee-tier boundaries, withdrawal bookkeeping, and the
season's derived entry count (PRD §3.1-§3.3).
"""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    assert_entry,
    assert_invoice,
    make_entrant_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


def _hours_later(iso: str, hours: int) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=hours)


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class TestFeeTierBoundaries:
    def test_submit_at_early_fee_boundary_pays_standard(self, api):
        """PRD §3.3: "The boundary instants are pinned: a submission exactly at
        `early_fee_ends_at` pays the standard fee"
        PRD §3.3: "The invoice is created `ISSUED` with the computed
        `amount_cents` and `tier`, and a `due_at` seventy-two hours after
        creation"

        Design: Difficulty/combinatorial_formula/entry_fee_tier_boundary_interaction
        """
        bundle = fx.setup_submitted_entry("GALA-T1", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        fx.set_clock("2026-08-20T00:00:00Z")  # exactly early_fee_ends_at
        submitted = validate_success(
            api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["payment_status"] == "INVOICED"
        assert submitted["fee_tier_applied"] == "STANDARD"
        invoice = fx.get_only_invoice(entry["id"])
        assert_invoice(invoice)
        assert invoice["tier"] == "STANDARD"
        assert invoice["amount_cents"] == 15000
        assert _parse(invoice["due_at"]) == _hours_later("2026-08-20T00:00:00Z", 72)

    def test_submit_at_submission_close_pays_standard(self, api):
        """PRD §3.3: "The boundary instants are pinned: a submission exactly at
        `early_fee_ends_at` pays the standard fee, one exactly at
        `submission_closes_at` still pays the standard fee, and one a single
        second later pays the late fee."
        PRD §3.3: "The fee tier is chosen by the clock at submission time:
        strictly before `early_fee_ends_at` the `EARLY` tier charges
        `early_fee_cents`; from `early_fee_ends_at` up to and including
        `submission_closes_at` the `STANDARD` tier charges `standard_fee_cents`;
        and inside the late window after `submission_closes_at` the `LATE` tier
        charges `late_fee_cents`."

        Design: Difficulty/combinatorial_formula/entry_fee_tier_boundary_interaction
        """
        bundle = fx.setup_submitted_entry("GALA-T2", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        fx.set_clock("2026-09-01T00:00:00Z")  # exactly submission_closes_at
        submitted = validate_success(
            api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert submitted["fee_tier_applied"] == "STANDARD"
        invoice = fx.get_only_invoice(entry["id"])
        assert invoice["tier"] == "STANDARD"
        assert invoice["amount_cents"] == 15000
        assert _parse(invoice["due_at"]) == _hours_later("2026-09-01T00:00:00Z", 72)

    def test_submit_one_second_after_close_pays_late(self, api):
        """PRD §3.3: "The boundary instants are pinned: a submission exactly at
        `early_fee_ends_at` pays the standard fee, one exactly at
        `submission_closes_at` still pays the standard fee, and one a single
        second later pays the late fee."
        PRD §3.3: "The fee tier is chosen by the clock at submission time:
        strictly before `early_fee_ends_at` the `EARLY` tier charges
        `early_fee_cents`; from `early_fee_ends_at` up to and including
        `submission_closes_at` the `STANDARD` tier charges `standard_fee_cents`;
        and inside the late window after `submission_closes_at` the `LATE` tier
        charges `late_fee_cents`."

        Design: Difficulty/combinatorial_formula/entry_fee_tier_boundary_interaction
        """
        bundle = fx.setup_submitted_entry("GALA-T3", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        fx.set_clock("2026-09-01T00:00:01Z")  # one second into the late window
        submitted = validate_success(
            api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert submitted["fee_tier_applied"] == "LATE"
        invoice = fx.get_only_invoice(entry["id"])
        assert invoice["tier"] == "LATE"
        assert invoice["amount_cents"] == 20000
        assert _parse(invoice["due_at"]) == _hours_later("2026-09-01T00:00:01Z", 72)


class TestSeasonOpenGate:
    def test_submit_rejected_while_season_draft(self, api):
        """PRD §3.3: "The entry must be `DRAFT`, its category `PUBLISHED`, and
        its season `OPEN`."
        PRD §2.5: "State gate: the target entity's state must permit the requested
        transition, and child-creating operations carry parent state gates — a
        ballot requires an `OPEN` round, an entry requires a season in `DRAFT` or
        `OPEN` with a `PUBLISHED` category, and a panel assignment requires a
        `CONFIGURING` round — otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/entry_submit_requires_season_open
        """
        season = fx.create_season("GALA-X1")
        category = fx.create_published_category(season["id"], code="CAT_X1")
        entrant = fx.register_entrant("e1@x.com", "Entrant 1")
        entry = fx.create_draft_entry(category["id"], entrant["id"])
        fx.attach_accepted_material(entry["id"], entrant["id"])
        fx.set_clock("2026-08-10T00:00:00Z")  # inside the submission window
        resp = api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = fx.get_entry(entry["id"])
        assert fetched["status"] == "DRAFT"

    def test_submit_succeeds_after_season_opens(self, api):
        """PRD §3.3: "The entry must be `DRAFT`, its category `PUBLISHED`, and
        its season `OPEN`."
        PRD §3.3: "the entry moves to `SUBMITTED`, its `payment_status` becomes
        `INVOICED`"

        Design: Difficulty/cross_entity_state_dependency/entry_submit_requires_season_open
        """
        season = fx.create_season("GALA-X1B")
        category = fx.create_published_category(season["id"], code="CAT_X1")
        entrant = fx.register_entrant("e1@x.com", "Entrant 1")
        entry = fx.create_draft_entry(category["id"], entrant["id"])
        fx.attach_accepted_material(entry["id"], entrant["id"])
        fx.open_season(season["id"])
        submitted = validate_success(
            api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert_entry(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["payment_status"] == "INVOICED"


class TestResubmitPrecedence:
    def test_resubmit_after_late_window_reports_state_error(self, api):
        """PRD §2.5: "Every request is evaluated against a fixed validation
        pipeline. Checks run in the order below, and the first failure
        short-circuits the remainder, so an earlier error always masks a later
        one." (state gate precedes clock windows)
        PRD §3.8: "any action whose source state does not permit the transition
        is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_resubmit
        """
        bundle = fx.setup_submitted_entry("GALA-PRIO1")
        entry, entrant = bundle["entry"], bundle["entrant"]
        fx.set_clock("2026-09-05T00:00:00Z")  # past the 48h late window
        resp = api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = fx.get_entry(entry["id"])
        assert fetched["status"] == "SUBMITTED"
        invoices = fx.list_entry_invoices(entry["id"])
        assert len(invoices) == 1, "a rejected resubmit must not create a second invoice"

    def test_resubmit_within_window_reports_state_error(self, api):
        """PRD §3.3: "The entry must be `DRAFT`, its category `PUBLISHED`, and
        its season `OPEN`."
        PRD §3.8: "any action whose source state does not permit the transition
        is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_resubmit
        """
        bundle = fx.setup_submitted_entry("GALA-PRIO1B")
        entry, entrant = bundle["entry"], bundle["entrant"]
        fx.set_clock("2026-08-11T00:00:00Z")  # still inside the window
        resp = api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestActiveEntriesCount:
    def test_submit_then_withdraw_restores_baseline_count(self, api):
        """PRD §3.3: "The invoice is created `ISSUED` with the computed
        `amount_cents` and `tier`, and a `due_at` seventy-two hours after
        creation; the entry moves to `SUBMITTED`, its `payment_status` becomes
        `INVOICED`, `fee_tier_applied` records the tier, the season's
        `active_entries_count` is incremented by one, and an `ENTRY_SUBMIT`
        audit row is appended."
        PRD §3.3: "Withdrawing voids any still-`ISSUED` invoice and returns
        `payment_status` to `UNPAID`."
        PRD §3.3: "Withdrawing a `SUBMITTED` or `UNDER_REVIEW` entry decrements
        the season's `active_entries_count` by one; withdrawing a `DRAFT` entry
        does not, since a draft was never counted."

        Design: Difficulty/compensating_invariant/active_entries_count_submit_withdraw_conservation
        """
        bundle = fx.setup_submitted_entry("GALA-INV1", submit=False)
        season, entry, entrant = bundle["season"], bundle["entry"], bundle["entrant"]
        assert fx.get_season(season["id"])["active_entries_count"] == 0
        fx.submit_entry(entry["id"], entrant["id"])
        assert fx.get_season(season["id"])["active_entries_count"] == 1
        withdrawn = validate_success(
            api.withdraw_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["payment_status"] == "UNPAID"
        assert fx.get_season(season["id"])["active_entries_count"] == 0
        invoice = fx.get_only_invoice(entry["id"])
        assert invoice["status"] == "VOIDED"

    def test_draft_withdrawal_leaves_count_unchanged(self, api):
        """PRD §3.3: "withdrawing a `DRAFT` entry does not, since a draft was
        never counted."

        Design: Difficulty/compensating_invariant/active_entries_count_submit_withdraw_conservation
        """
        bundle = fx.setup_submitted_entry("GALA-INV1C", submit=False)
        season, entry, entrant = bundle["season"], bundle["entry"], bundle["entrant"]
        assert fx.get_season(season["id"])["active_entries_count"] == 0
        withdrawn = validate_success(
            api.withdraw_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert fx.get_season(season["id"])["active_entries_count"] == 0


class TestSubmissionWindowAndEligibility:
    def test_submit_outside_eligibility_window_rejected(self, api):
        """PRD §3.3: "The completed-work instant `work_completed_at` must fall
        within the season's eligibility window — on or after
        `eligibility_window_start` and strictly before `eligibility_window_end`
        — or the submission fails with `ERR_ELIGIBILITY_WINDOW`."

        Design: Corner/validations/eligibility_window_violation
        """
        season, category = fx.setup_open_season_with_category("GALA-ELI")
        entrant = fx.register_entrant("e1@x.com", "Entrant 1")
        entry = fx.create_draft_entry(
            category["id"], entrant["id"], work_completed_at="2025-12-31T23:59:59Z"
        )
        fx.attach_accepted_material(entry["id"], entrant["id"])
        resp = api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_WINDOW)

    def test_submit_at_late_window_end_rejected(self, api):
        """PRD §3.3: "The clock must not have passed the late deadline:
        submissions remain accepted for 48 hours after `submission_closes_at`,
        and any later attempt fails with `ERR_OUTSIDE_WINDOW`."

        Design: Corner/validations/late_window_expired_submit_rejected
        """
        bundle = fx.setup_submitted_entry("GALA-LATE", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        fx.set_clock("2026-09-03T00:00:00Z")  # submission_closes_at + 48h exactly
        resp = api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)

    def test_double_submit_rejected_and_single_invoice(self, api):
        """PRD §3.3: "The entry must be `DRAFT`, its category `PUBLISHED`, and
        its season `OPEN`."
        PRD §3.8: "any action whose source state does not permit the transition
        is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invalid_transition_entry_submit_twice
        """
        bundle = fx.setup_submitted_entry("GALA-IVT")
        entry, entrant = bundle["entry"], bundle["entrant"]
        resp = api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        invoices = fx.list_entry_invoices(entry["id"])
        assert len(invoices) == 1

    def test_withdrawn_entry_is_terminal(self, api):
        """PRD §3.8: "Throughout the lifecycle, every state change on an entity
        already in a terminal state is refused with `ERR_ALREADY_TERMINAL`"
        PRD §3.3: "Withdrawal is the entrant's exit from a `DRAFT`, `SUBMITTED`,
        or `UNDER_REVIEW` entry." (no outbound transition from WITHDRAWN exists)

        Design: Corner/state_machines/terminal_state_lockdown_withdrawn_entry
        """
        bundle = fx.setup_submitted_entry("GALA-TRM", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        withdrawn = validate_success(
            api.withdraw_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_fee_waived_entry_skips_invoice(self, api):
        """PRD §3.3: "When such an entry is submitted, no invoice is created at
        all: `payment_status` becomes `WAIVED`, and the entry passes straight
        through `SUBMITTED` to `UNDER_REVIEW` without waiting for settlement."
        PRD §3.2: "New entries are `DRAFT` with `payment_status` `UNPAID`,
        `revision_count` zero, `fee_waived` false, `fee_tier_applied` null"

        Design: Corner/endpoints/waive_fee_variant_flow
        """
        bundle = fx.setup_submitted_entry("GALA-WV", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        waived = validate_success(api.waive_fee(entry["id"], ADMIN))
        assert waived["fee_waived"] is True
        submitted = validate_success(
            api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["payment_status"] == "WAIVED"
        assert submitted.get("fee_tier_applied") is None
        invoices = fx.list_entry_invoices(entry["id"])
        assert invoices == [], "a waived entry must not create a FeeInvoice"
