"""Compensating actions that must leave their ledgers exactly balanced: voiding a
verified log and clawing back a paid stipend.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.assertions import assert_money_cents, assert_two_decimals
from test_helpers.fixtures import (
    approve_disbursement,
    build_program,
    draft_disbursement,
    pay_disbursement,
    read_disbursement,
    read_match,
    read_mentor,
    read_novice,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, APPROVER, make_site_lead_headers

VOID_REASON = "Model lesson was delivered by a different mentor"
CLAWBACK_REASON = "District audit reversed the quarter after a duplicate payment was found"


class TestVoidRestoresVerifiedMinuteLedger:
    """After the void the three minute ledgers agree with the surviving logs."""

    @staticmethod
    def _two_verified_logs(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-07T12:00:00Z")
        first = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-05T09:00:00Z",
            minutes=120,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        verify_contact_log(api, first["id"], lead)
        second = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T09:00:00Z",
            minutes=80,
            contact_type="MODEL_LESSON",
            mentor_id=program["mentor_id"],
            description="Model lesson delivered in the novice classroom for one period",
        )
        verify_contact_log(api, second["id"], lead)
        program["kept_log_id"] = first["id"]
        program["voided_log_id"] = second["id"]
        return program

    def test_every_minute_ledger_equals_the_surviving_verified_logs(
        self, api: InductionApiClient
    ):
        """220 credited minutes fall back to the 120 that remain, on all three ledgers.

        The PRD lists exactly which ledgers the compensating action rewrites:
        "*Hop one* resets the log's own `credited_minutes` and `stipend_cents` to
        zero while `void_reason` preserves the audit trail, and recomputes the
        match's `verified_minutes_total` and `accrued_stipend_cents`, the mentor's
        `verified_minutes_lifetime` and `stipend_accrued_cents`, the novice's
        `verified_contact_minutes`, and the novice's `readiness_index_live`."

        Design: Difficulty/compensating_invariant/void_restores_verified_minute_ledger
        """
        program = self._two_verified_logs(api)
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 220, (
            "120 plus the weighted 100 of the model lesson is 220 before the void"
        )

        validate_success(
            api.void_contact_log(
                program["voided_log_id"], f.void_payload(void_reason=VOID_REASON), ADMIN
            )
        )

        voided = validate_success(api.get_contact_log(program["voided_log_id"], ADMIN))
        assert voided["verification_status"] == "VOIDED"
        assert voided["credited_minutes"] == 0, "no minute residue is left on the voided row"
        assert voided["stipend_cents"] == 0, "no cash residue is left on the voided row"
        assert voided["void_reason"] == VOID_REASON, (
            f"the audit trail is preserved, got {voided['void_reason']}"
        )

        kept = validate_success(api.get_contact_log(program["kept_log_id"], ADMIN))
        surviving_minutes = kept["credited_minutes"]
        assert surviving_minutes == 120

        assert read_match(api, program["match_id"])["verified_minutes_total"] == (
            surviving_minutes
        ), "the match ledger must equal the sum over the remaining VERIFIED logs"
        assert read_mentor(api, program["mentor_id"])["verified_minutes_lifetime"] == (
            surviving_minutes
        ), "the mentor's lifetime ledger must equal the same sum"
        assert read_novice(api, program["novice_id"])["verified_contact_minutes"] == (
            surviving_minutes
        ), "the novice's ledger must equal the same sum"

    def test_the_cash_ledgers_and_readiness_follow_the_minutes_down(
        self, api: InductionApiClient
    ):
        """8400 cents and a 9.00 readiness index are what 120 surviving minutes support.

        Voiding is the designated reversal, and the PRD says so: "`VOIDED` is
        terminal, and voiding is the designated compensating action for a
        verification."

        Design: Difficulty/compensating_invariant/void_restores_verified_minute_ledger
        """
        program = self._two_verified_logs(api)
        assert_money_cents(
            read_match(api, program["match_id"])["accrued_stipend_cents"],
            15400,
            "accrued_stipend_cents before the void",
        )

        validate_success(
            api.void_contact_log(
                program["voided_log_id"], f.void_payload(void_reason=VOID_REASON), ADMIN
            )
        )

        assert_money_cents(
            read_match(api, program["match_id"])["accrued_stipend_cents"],
            8400,
            "accrued_stipend_cents",
        )
        assert_money_cents(
            read_mentor(api, program["mentor_id"])["stipend_accrued_cents"],
            8400,
            "stipend_accrued_cents",
        )
        assert_two_decimals(
            read_novice(api, program["novice_id"])["readiness_index_live"],
            9.00,
            "readiness_index_live",
        )


class TestClawbackConservesStipendCents:
    """A clawback moves cents between two fields without creating or destroying any."""

    @staticmethod
    def _paid_disbursement(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-04T12:00:00Z")
        log = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-03T09:00:00Z",
            minutes=120,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        verify_contact_log(api, log["id"], lead)
        set_clock(api, "2026-10-05T00:00:00Z")
        mentor_version = read_mentor(api, program["mentor_id"])["version"]
        disbursement = draft_disbursement(api, program["mentor_id"], mentor_version)
        approve_disbursement(api, disbursement["id"], APPROVER)
        pay_disbursement(api, disbursement["id"], APPROVER)
        program["disbursement_id"] = disbursement["id"]
        return program

    def test_paid_plus_clawed_back_is_conserved(self, api: InductionApiClient):
        """The 8400 cents move from paid to clawed back and the sum never drifts.

        The PRD states the invariant in so many words: "Clawing back requires the
        row to be `PAID` and a `clawback_reason`; it stamps `clawed_back_at` and
        `clawback_reason`, subtracts `net_cents` from `stipend_paid_cents` and
        adds the identical amount to `stipend_clawed_back_cents`, so the mentor's
        paid-plus-clawed-back total is conserved and never drifts."

        Design: Difficulty/compensating_invariant/clawback_conserves_stipend_cents
        """
        program = self._paid_disbursement(api)
        before = read_mentor(api, program["mentor_id"])
        assert_money_cents(before["stipend_paid_cents"], 8400, "stipend_paid_cents")
        assert_money_cents(
            before["stipend_clawed_back_cents"], 0, "stipend_clawed_back_cents"
        )

        validate_success(
            api.set_disbursement_status(
                program["disbursement_id"],
                f.disbursement_status_payload(
                    "CLAWED_BACK", clawback_reason=CLAWBACK_REASON
                ),
                ADMIN,
            )
        )

        after = read_mentor(api, program["mentor_id"])
        assert_money_cents(after["stipend_paid_cents"], 0, "stipend_paid_cents")
        assert_money_cents(
            after["stipend_clawed_back_cents"], 8400, "stipend_clawed_back_cents"
        )
        assert after["stipend_paid_cents"] + after["stipend_clawed_back_cents"] == (
            before["stipend_paid_cents"] + before["stipend_clawed_back_cents"]
        ), "the paid-plus-clawed-back total must be identical either side of the reversal"
        assert_money_cents(
            after["stipend_accrued_cents"], 8400, "stipend_accrued_cents"
        )

    def test_the_reversed_row_keeps_its_figures_rather_than_being_zeroed(
        self, api: InductionApiClient
    ):
        """The disbursement records the reversal without erasing the amount reversed.

        Clawback is a terminal, recorded reversal rather than a deletion:
        "`CLAWED_BACK` and `SUPERSEDED` are both terminal, and clawback is the
        designated compensating action for a payment."

        Design: Difficulty/compensating_invariant/clawback_conserves_stipend_cents
        """
        program = self._paid_disbursement(api)

        clawed_back = validate_success(
            api.set_disbursement_status(
                program["disbursement_id"],
                f.disbursement_status_payload(
                    "CLAWED_BACK", clawback_reason=CLAWBACK_REASON
                ),
                ADMIN,
            )
        )
        assert clawed_back["status"] == "CLAWED_BACK", (
            f"the row lands on its terminal status, got {clawed_back['status']}"
        )
        assert clawed_back["clawback_reason"] == CLAWBACK_REASON, (
            f"the reason is recorded, got {clawed_back['clawback_reason']}"
        )

        stored = read_disbursement(api, program["disbursement_id"])
        assert_money_cents(stored["gross_cents"], 8400, "gross_cents")
        assert_money_cents(stored["net_cents"], 8400, "net_cents")
        assert stored["clawed_back_at"] is not None, (
            "the reversal instant is stamped on the row"
        )
