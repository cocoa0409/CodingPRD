"""Transitive cascades on bind and decline:
  bind -> Application BOUND -> Policy created -> PENDING endorsements APPLIED -> ledger.
  decline -> Application DECLINED -> DRAFT/PENDING endorsements REJECTED.
Queue A — rule transitive_cascade.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_underwriter_headers,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestBindCascade:
    def _bind_with_one_peril_add(self, api):
        """UNDER_REVIEW app + one PENDING WATER_BACKUP PERIL_ADD (cov 20000, delta +80),
        PASSED inspection, FINAL low wildfire — then bind."""
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property()
        fx.setup_passed_inspection(prop["id"])
        app = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
        e1 = fx.create_endorsement(app["id"], "PERIL_ADD", "WATER_BACKUP", 20000)
        e1 = fx.attach_endorsement(e1["id"])
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        bound = validate_success(
            api.bind_application(
                app["id"],
                f.bind_application_payload(1751000000, 1782536000, app["version"]),
                make_underwriter_headers(uw["id"]),
            )
        )
        return prop, e1, bound

    def test_bind_sets_bound_and_creates_pending_payment_policy_with_balance(self, api):
        """PRD §3.6: "First a policy is created in `PENDING_PAYMENT`, carrying the
        application's `property_id`, an `annual_premium` copied from the latest
        `BOUND_OFFER` quote's `annual_premium`, and a starting `premium_balance` of 0."
        PRD §3.6: "each newly applied endorsement posts to the new policy's ledger: a
        peril-add posts a DEBIT for its `premium_delta` ... the policy's
        `premium_balance` is recomputed from the ledger after these postings."

        Design: Difficulty/transitive_cascade/bind_cascade_application_policy_endorsement_ledger
        """
        prop, e1, bound = self._bind_with_one_peril_add(api)
        assert bound["status"] == "BOUND"
        policy = fx.get_policy_for_application(bound["id"])
        assert policy["status"] == "PENDING_PAYMENT"
        assert policy["premium_balance"] == 80.00, (
            f"Applied PERIL_ADD DEBIT 80.00 should be the only ledger posting; "
            f"got premium_balance {policy['premium_balance']}"
        )

    def test_bind_applies_endorsement_and_raises_total_insured_value(self, api):
        """PRD §3.6: "Second, every endorsement on the application that is in `PENDING`
        transitions to `APPLIED`."
        PRD §3.6: "Each applied peril-add additionally raises the property's
        `total_insured_value` by its `coverage_limit`."

        Design: Difficulty/transitive_cascade/bind_cascade_application_policy_endorsement_ledger
        """
        prop, e1, bound = self._bind_with_one_peril_add(api)
        endo_after = fx.get_endorsement(e1["id"])
        assert endo_after["status"] == "APPLIED"
        prop_after = fx.get_property(prop["id"])
        assert prop_after["total_insured_value"] == 294200.00, (
            f"replacement_cost 274200.00 + coverage_limit 20000; "
            f"got total_insured_value {prop_after['total_insured_value']}"
        )


class TestDeclineCascade:
    def _decline_with_two_endorsements(self, api):
        """UNDER_REVIEW app with one PENDING and one DRAFT endorsement, then decline."""
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property()
        app = fx.create_application(prop["id"], 300000)
        e_pending = fx.create_endorsement(app["id"], "PERIL_ADD", "WATER_BACKUP", 20000)
        e_pending = fx.attach_endorsement(e_pending["id"])
        e_draft = fx.create_endorsement(app["id"], "EXCLUSION", "MOLD")
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        declined = validate_success(
            api.decline_application(
                app["id"], f.decline_application_payload("INSPECTION_FAILED"),
                make_underwriter_headers(uw["id"]),
            )
        )
        return declined, e_pending, e_draft

    def test_decline_sets_declined_and_reason(self, api):
        """PRD §3.6: "A decline moves the application to `DECLINED`, records the
        supplied reason in `decline_reason`, and rejects every endorsement on the
        application that is still in `DRAFT` or `PENDING`, moving each to `REJECTED`."

        Design: Difficulty/transitive_cascade/decline_cascade_application_endorsements_rejected
        """
        declined, e_pending, e_draft = self._decline_with_two_endorsements(api)
        assert declined["status"] == "DECLINED"
        assert declined["decline_reason"] == "INSPECTION_FAILED"

    def test_decline_rejects_pending_and_draft_endorsements(self, api):
        """PRD §3.6: "rejects every endorsement on the application that is still in
        `DRAFT` or `PENDING`, moving each to `REJECTED`."
        PRD §3.5: "When an application is instead declined, every endorsement on it
        that is still in `DRAFT` or in `PENDING` is moved to `REJECTED`."

        Design: Difficulty/transitive_cascade/decline_cascade_application_endorsements_rejected
        """
        declined, e_pending, e_draft = self._decline_with_two_endorsements(api)
        assert fx.get_endorsement(e_pending["id"])["status"] == "REJECTED"
        assert fx.get_endorsement(e_draft["id"])["status"] == "REJECTED"
