"""Every cascade that can be undone must land back on its exact starting value.

These tests read the counter before the forward action, run the compensating
action, and demand the identical value back - not merely a plausible one - while
also demanding that the audit trail of both moves survives.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_cents, assert_field_values, assert_row_count
from test_helpers.fixtures import (
    create_active_credential,
    create_presentation_ready_world,
    disclose,
    grant_consent,
    open_presentation_session,
    publish_trust_list,
    read_profile,
)
from test_helpers.test_users import ADMIN, PRIVACY_AUDITOR, make_holder_headers


class TestHandsetRecoveryRestoresTheActiveCredentialCount:
    """Report-lost then recover must leave the counter exactly where it began."""

    @staticmethod
    def _world(api):
        bundle = create_active_credential(api)
        publish_trust_list(api, bundle["profile"]["id"])
        return bundle

    def test_the_counter_returns_to_its_pre_loss_value_with_no_drift(self, api):
        """The holder's active-credential count goes 1, 0, 1 across the loss and
        the recovery, and the handset comes back BOUND with its stamp cleared.

        PRD 3.4: "**Recovering a handset** is the exact compensating action, and
        it must restore the counters with no drift. It carries a
        `reattestation_token`; without one the request fails with
        `ERR_INVALID_REQUEST`. The handset moves `LOST_REPORTED` -> `BOUND`,
        `lost_reported_at` is cleared to null"

        Design: Difficulty/compensating_invariant/device_recovery_restores_holder_active_credential_count_exactly
        """
        bundle = self._world(api)
        holder_headers = make_holder_headers(bundle["holder"]["id"])

        before = validate_success(api.get_holder(bundle["holder"]["id"], ADMIN))
        assert before["active_credential_count"] == 1

        lost = validate_success(
            api.report_device_lost(bundle["device"]["id"], holder_headers)
        )
        assert lost["state"] == "LOST_REPORTED"
        during = validate_success(api.get_holder(bundle["holder"]["id"], ADMIN))
        assert during["active_credential_count"] == 0

        recovered = validate_success(
            api.recover_device(
                bundle["device"]["id"],
                {"reattestation_token": "reattest-tok-a1"},
                holder_headers,
            )
        )
        assert_field_values(
            recovered, {"state": "BOUND", "lost_reported_at": None}
        )

        after = validate_success(api.get_holder(bundle["holder"]["id"], ADMIN))
        assert after["active_credential_count"] == before["active_credential_count"]

    def test_both_moves_are_recorded_and_the_credential_reads_valid_again(self, api):
        """The ledger keeps the suspension and the reinstatement as two entries
        and each one made the published snapshot need republishing.

        PRD 3.4: "every credential on that handset that is `SUSPENDED` **with
        `suspend_reason` exactly `DEVICE_LOST`** moves `SUSPENDED` -> `ACTIVE`
        with `suspend_reason` cleared to null; each such reinstatement appends a
        ledger entry with status `REINSTATED` and reason `RECOVERY` and
        increments the holder's `active_credential_count` by 1; and each appended
        entry again marks the newest snapshot `revocation_pointer_stale`,
        increments its `pending_delta_count` by 1 and increments the profile's
        `pending_republish_count` by 1."

        Design: Difficulty/compensating_invariant/device_recovery_restores_holder_active_credential_count_exactly
        """
        bundle = self._world(api)
        holder_headers = make_holder_headers(bundle["holder"]["id"])

        api.report_device_lost(bundle["device"]["id"], holder_headers)
        validate_success(
            api.recover_device(
                bundle["device"]["id"],
                {"reattestation_token": "reattest-tok-a1"},
                holder_headers,
            )
        )

        credential = validate_success(
            api.get_credential(bundle["credential"]["id"], ADMIN)
        )
        assert_field_values(
            credential, {"lifecycle_state": "ACTIVE", "suspend_reason": None}
        )

        entries = assert_row_count(
            api.list_revocation_entries(bundle["credential"]["id"], ADMIN), 2
        )
        assert entries[0]["status"] == "SUSPENDED"
        assert entries[1]["status"] == "REINSTATED"
        assert entries[1]["sequence"] == 2

        status = validate_success(
            api.get_revocation_status(bundle["credential"]["id"], PRIVACY_AUDITOR)
        )
        assert status["status"] == "VALID"

        profile = read_profile(api, bundle["profile"]["id"])
        assert profile["pending_republish_count"] == 2


class TestVoidingBillingReturnsTheBalanceExactly:
    """The balance is conserved and the void is credited rather than hidden."""

    @staticmethod
    def _billed_session(api):
        world = create_presentation_ready_world(
            api, reader_app_overrides={"base_rate_cents": 30}
        )
        session = open_presentation_session(api, world)
        grant_consent(api, session["id"], world["holder"]["id"])
        completed = disclose(api, session["id"], world["verifier"]["id"])
        return world, completed

    def test_the_balance_returns_to_zero_while_the_credit_records_the_amount(self, api):
        """Disclosure raises the balance by the base rate and the void removes
        exactly that amount, accumulating it as a credit instead.

        PRD 2.9: "Billing a disclosure raises the verifier's outstanding balance;
        voiding that billing removes exactly the same amount, so the balance
        returns to its exact pre-disclosure value. `credited_amount_cents` on a
        verifier accumulates every amount so removed as the audit counterpart of
        the conserved balance, and is never subtracted from the balance a second
        time."

        Design: Difficulty/compensating_invariant/void_billing_returns_verifier_balance_to_pre_disclosure_value
        """
        world, completed = self._billed_session(api)
        verifier_id = world["verifier"]["id"]

        assert_field_values(
            completed, {"billing_state": "BILLED", "billed_amount_cents": 30}
        )
        billed_verifier = validate_success(api.get_verifier(verifier_id, ADMIN))
        assert_cents(billed_verifier, "billable_query_balance_cents", 30)
        assert_cents(billed_verifier, "credited_amount_cents", 0)
        assert billed_verifier["exposure_index"] == 0

        voided = validate_success(
            api.void_presentation_billing(completed["id"], PRIVACY_AUDITOR)
        )
        assert_field_values(
            voided, {"billing_state": "VOIDED", "billed_amount_cents": 30}
        )

        after = validate_success(api.get_verifier(verifier_id, ADMIN))
        assert_cents(after, "billable_query_balance_cents", 0)
        assert_cents(after, "credited_amount_cents", 30)
        assert after["exposure_index"] == 0

    def test_the_log_entry_and_the_invoice_agree_after_the_void(self, api):
        """The session's log entry is restamped VOIDED while keeping the amount,
        and the invoice still charges the served query against a zero balance.

        PRD 3.9: "The session's `billing_state` moves `BILLED` -> `VOIDED` while
        `billed_amount_cents` is left intact as the audit record of what was
        voided; every log entry of that session has its `billing_state` set to
        `VOIDED`"
        PRD 3.9: "The computation returns `invoice_amount_cents`, the
        `line_count` of applications that contributed a line, the
        `surcharge_pct` in force, and the verifier's current
        `billable_query_balance_cents`."

        Design: Difficulty/compensating_invariant/void_billing_returns_verifier_balance_to_pre_disclosure_value
        """
        world, completed = self._billed_session(api)

        validate_success(
            api.void_presentation_billing(completed["id"], PRIVACY_AUDITOR)
        )

        entries = assert_row_count(
            api.list_presentation_log_entries(completed["id"], PRIVACY_AUDITOR), 1
        )
        assert_field_values(
            entries[0], {"billing_state": "VOIDED", "billed_amount_cents": 30}
        )

        invoice = validate_success(
            api.get_invoice(world["verifier"]["id"], ADMIN)
        )
        assert_cents(invoice, "billable_query_balance_cents", 0)
        assert_cents(invoice, "invoice_amount_cents", 30)
