"""Compensating actions and the conserved quantities they must restore exactly.

Two ledgers in this system carry a stated global identity: the identity index
conserves cluster membership across a merge and its compensating unmerge, and the
fee ledger conserves the outstanding balance across an issuance and its
compensating void. Each identity is checked before the forward action, while the
forward action stands, and after the compensation.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_membership_invariant,
    assert_outstanding_balance_invariant,
)
from test_helpers.factories import patient_record_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_privacy_officer_headers

TUNER_USER_ID = "privacy-tuner-1"
STEWARD_USER_ID = "privacy-steward-1"

CONFIRM_NOTE = "Same patient; confirmed against the state immunization registry."
UNLINK_REASON = (
    "Registry review found two distinct patients born the same day at the same "
    "address; merge reversed."
)


def _all_clusters(hie: HieHarness):
    """Every cluster row the exchange holds, in one page."""
    return validate_success(hie.client.list_identity_clusters(hie.admin, limit=100), 200)


def _all_records(hie: HieHarness):
    """Every patient record row the exchange holds, in one page."""
    return validate_success(hie.client.list_patient_records(hie.admin, limit=100), 200)


class TestUnlinkRestoresMembershipConservation:
    """The membership total is two before the merge, two during it, two after it."""

    LEFT_RECORD = patient_record_payload(
        source_mrn="U1-0001",
        given_name="Maria",
        family_name="Gonzalez",
        birth_date="1991-07-22",
        sex="F",
        ssn_last4="3321",
        postal_code="78701",
        phone_digits="5125550143",
    )
    RIGHT_RECORD = patient_record_payload(
        source_mrn="U2-0001",
        given_name="Mari",
        family_name="Gonzales",
        birth_date="1991-07-22",
        sex="F",
        ssn_last4="3321",
        postal_code="78701",
        phone_digits="2125550143",
    )

    @staticmethod
    def _pending_review_pair(hie: HieHarness):
        """Two clusters of one record each, joined by a link awaiting a steward."""
        hie.activate_threshold_config(
            config_label="REF-PROB-U",
            score_variant_mode="PROBABILISTIC_ONLY",
            headers=make_privacy_officer_headers(TUNER_USER_ID),
        )
        left_participant = hie.participant_in_conformance_testing(
            legal_name="Union Heights Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=84000,
            primary_contact_email="hie@unionheights.example",
        )
        right_participant = hie.participant_in_conformance_testing(
            legal_name="Underwood Street Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=24000,
            primary_contact_email="hie@underwood.example",
        )
        left_record = hie.contribute_record(
            left_participant["id"],
            headers=hie.admin,
            **TestUnlinkRestoresMembershipConservation.LEFT_RECORD,
        )
        right_record = hie.contribute_record(
            right_participant["id"],
            headers=hie.admin,
            **TestUnlinkRestoresMembershipConservation.RIGHT_RECORD,
        )
        link = hie.only_link_between(right_record["id"])
        assert link["match_score"] == pytest.approx(0.7700, abs=0.0001)
        assert link["status"] == "PENDING_REVIEW"
        return left_record, right_record, link

    @staticmethod
    def _confirm(hie: HieHarness, link_id: str, winner_cluster_id: str):
        return validate_success(
            hie.client.record_steward_decision(
                make_privacy_officer_headers(STEWARD_USER_ID),
                link_id,
                decision="CONFIRM",
                expected_cluster_version=hie.cluster_version(winner_cluster_id),
                review_note=CONFIRM_NOTE,
            ),
            200,
        )

    @staticmethod
    def _unlink(hie: HieHarness, link_id: str, cluster_id: str):
        return validate_success(
            hie.client.unlink_match_link(
                make_privacy_officer_headers(STEWARD_USER_ID),
                link_id,
                expected_cluster_version=hie.cluster_version(cluster_id),
                unlink_reason=UNLINK_REASON,
            ),
            200,
        )

    def test_unlinking_a_confirmed_merge_conserves_the_clustered_record_total(
        self, hie: HieHarness
    ):
        """Two clustered records before the merge, during it, and after the unlink.

        PRD 2.10: "The identity index maintains one global invariant that a
        correct implementation preserves through every merge and every
        compensating unmerge: the sum of `member_record_count` over all clusters
        whose `status` is `ACTIVE` always equals the total count of patient
        records whose `match_state` is `CLUSTERED`."

        PRD 2.10: "A confirm-then-unlink pair must leave that total identical and
        must restore every re-pointed record's `cluster_id` from its
        `prior_cluster_id`."

        Design: Difficulty/compensating_invariant/unlink_restores_cluster_membership_conservation_after_a_confirmed_merge
        """
        left_record, right_record, link = self._pending_review_pair(hie)
        winner_id = left_record["cluster_id"]
        loser_id = right_record["cluster_id"]
        assert winner_id != loser_id

        assert hie.get_cluster(winner_id)["member_record_count"] == 1
        assert hie.get_cluster(loser_id)["member_record_count"] == 1
        clusters_before = _all_clusters(hie)
        records_before = _all_records(hie)
        assert_membership_invariant(clusters_before, records_before)
        assert sum(1 for row in records_before if row["match_state"] == "CLUSTERED") == 2

        confirmed = self._confirm(hie, link["id"], winner_id)
        assert confirmed["status"] == "LINKED"
        assert confirmed["cluster_id"] == winner_id
        assert confirmed["merged_away_cluster_id"] == loser_id

        assert hie.get_cluster(winner_id)["member_record_count"] == 2
        assert hie.get_cluster(loser_id)["status"] == "MERGED_AWAY"
        clusters_merged = _all_clusters(hie)
        records_merged = _all_records(hie)
        assert_membership_invariant(clusters_merged, records_merged)
        assert (
            sum(
                row["member_record_count"]
                for row in clusters_merged
                if row["status"] == "ACTIVE"
            )
            == 2
        )
        assert hie.get_record(right_record["id"])["prior_cluster_id"] == loser_id

        unlinked = self._unlink(hie, link["id"], winner_id)
        assert unlinked["status"] == "UNLINKED"
        assert unlinked["cluster_id"] is None
        assert unlinked["merged_away_cluster_id"] is None
        assert unlinked["unlink_reason"] == UNLINK_REASON

        restored_winner = hie.get_cluster(winner_id)
        assert restored_winner["status"] == "ACTIVE"
        assert restored_winner["member_record_count"] == 1
        assert restored_winner["participant_count"] == 1
        restored_loser = hie.get_cluster(loser_id)
        assert restored_loser["status"] == "ACTIVE"
        assert restored_loser["member_record_count"] == 1
        assert restored_loser["merged_into_cluster_id"] is None

        restored_record = hie.get_record(right_record["id"])
        assert restored_record["cluster_id"] == loser_id
        assert restored_record["prior_cluster_id"] is None
        assert restored_record["match_state"] == "CLUSTERED"

        clusters_after = _all_clusters(hie)
        records_after = _all_records(hie)
        assert_membership_invariant(clusters_after, records_after)
        assert sum(1 for row in records_after if row["match_state"] == "CLUSTERED") == 2

    def test_the_compensation_advances_every_touched_row_and_clears_the_review_counter(
        self, hie: HieHarness
    ):
        """Each side of the pair moves by exactly one version, and the total never moves.

        PRD 3.5: "the membership recount re-runs on both clusters, restoring the
        conserved membership total described in §2.10; and the link's own
        `cluster_id` and `merged_away_cluster_id` are both cleared to null while
        `unlink_reason` is stored. Both clusters and the link increment `version`
        by 1."

        PRD 2.10: "each entity a cascade touches has its own `updated_at`
        refreshed and its own `version` incremented by exactly 1, including
        entities the caller never named."

        Design: Difficulty/compensating_invariant/unlink_restores_cluster_membership_conservation_after_a_confirmed_merge
        """
        left_record, right_record, link = self._pending_review_pair(hie)
        winner_id = left_record["cluster_id"]
        loser_id = right_record["cluster_id"]

        assert hie.get_cluster(winner_id)["pending_review_link_count"] == 1
        assert hie.get_cluster(loser_id)["pending_review_link_count"] == 1
        winner_version_before = hie.cluster_version(winner_id)
        loser_version_before = hie.cluster_version(loser_id)
        link_version_before = link["version"]

        confirmed = self._confirm(hie, link["id"], winner_id)
        assert confirmed["version"] == link_version_before + 1
        assert confirmed["reviewed_by_user_id"] == STEWARD_USER_ID
        assert confirmed["review_note"] == CONFIRM_NOTE
        winner_merged = hie.get_cluster(winner_id)
        loser_merged = hie.get_cluster(loser_id)
        assert winner_merged["version"] == winner_version_before + 1
        assert loser_merged["version"] == loser_version_before + 1
        assert winner_merged["pending_review_link_count"] == 0
        assert winner_merged["participant_count"] == 2
        assert_membership_invariant(_all_clusters(hie), _all_records(hie))

        unlinked = self._unlink(hie, link["id"], winner_id)
        assert unlinked["version"] == confirmed["version"] + 1
        assert unlinked["reviewed_by_user_id"] == STEWARD_USER_ID
        assert unlinked["review_note"] == CONFIRM_NOTE
        winner_after = hie.get_cluster(winner_id)
        loser_after = hie.get_cluster(loser_id)
        assert winner_after["version"] == winner_merged["version"] + 1
        assert loser_after["version"] == loser_merged["version"] + 1
        assert winner_after["pending_review_link_count"] == 0
        assert loser_after["pending_review_link_count"] == 0
        assert winner_after["primary_record_id"] == left_record["id"]
        assert loser_after["primary_record_id"] == right_record["id"]
        assert_membership_invariant(_all_clusters(hie), _all_records(hie))


class TestVoidRestoresTheOutstandingBalance:
    """Delinquency moves no money; voiding returns the balance to its pre-issue value."""

    DELINQUENCY_REASON = "Unpaid past the 2026-07-15 due date"
    VOID_REASON = (
        "Period billed in error; the participant was not yet contributing data in May."
    )
    RE_ISSUE_REASON = "Re-billing the May window after the erroneous invoice was voided"

    @staticmethod
    def _health_plan_without_feeds(hie: HieHarness):
        """A participant whose fee multiplier is 1.00 because it has no feeds at all."""
        participant = hie.participant_in_conformance_testing(
            legal_name="Vantage Ridge Health Alliance",
            org_type="HEALTH_PLAN",
            declared_annual_patient_volume=120000,
            primary_contact_email="hie@vantageridge.example",
        )
        assert participant["outstanding_balance_cents"] == 0
        assert participant["quality_grade"] == "UNGRADED"
        assert participant["provisional_monthly_fee_cents"] == 267500
        assert participant["fee_tier"] == "TIER_1"
        return participant

    @staticmethod
    def _invoices(hie: HieHarness, participant_id: str):
        return validate_success(
            hie.client.list_participant_participation_invoices(
                hie.admin, participant_id, limit=100
            ),
            200,
        )

    @staticmethod
    def _administer(hie: HieHarness, invoice_id: str, action: str, reason: str):
        return validate_success(
            hie.client.administer_participation_invoice(
                hie.admin, invoice_id, action=action, reason=reason
            ),
            200,
        )

    def test_delinquency_moves_no_money_and_the_void_restores_the_balance_exactly(
        self, hie: HieHarness
    ):
        """535000 with both invoices standing, 535000 once one is delinquent, 267500 after the void.

        PRD 2.10: "The fee ledger maintains the parallel fiscal invariant: a
        participant's `outstanding_balance_cents` always equals the sum of
        `total_cents` over that participant's invoices whose `status` is `ISSUED`
        or `DELINQUENT`."

        PRD 3.9: "Delinquency leaves `outstanding_balance_cents` unchanged,
        because `DELINQUENT` invoices stay inside the balance sum."

        PRD 3.9: "Voiding drives `ISSUED → VOID` and is the compensating action:
        it recomputes the balance back to its exact pre-issue value and releases
        the billed window for re-invoicing."

        Design: Difficulty/compensating_invariant/voiding_an_invoice_restores_the_outstanding_balance_identity_exactly
        """
        participant = self._health_plan_without_feeds(hie)

        june = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-07-15T00:00:00Z",
        )
        assert june["billable_volume_units"] == 10000
        assert june["volume_fee_cents"] == 17500
        assert june["quality_multiplier"] == pytest.approx(1.00, abs=0.01)
        assert june["quality_grade_snapshot"] == "UNGRADED"
        assert june["total_cents"] == 267500
        assert june["status"] == "ISSUED"

        may = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-05-01T00:00:00Z",
            billing_period_end="2026-06-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-06-15T00:00:00Z",
        )
        assert may["total_cents"] == 267500

        both_issued = hie.get_participant(participant["id"])
        assert both_issued["outstanding_balance_cents"] == 535000
        assert_outstanding_balance_invariant(
            both_issued, self._invoices(hie, participant["id"])
        )

        delinquent = self._administer(
            hie, june["id"], "DECLARE_DELINQUENT", self.DELINQUENCY_REASON
        )
        assert delinquent["status"] == "DELINQUENT"
        assert delinquent["status_reason"] == self.DELINQUENCY_REASON
        after_delinquency = hie.get_participant(participant["id"])
        assert after_delinquency["outstanding_balance_cents"] == 535000
        assert_outstanding_balance_invariant(
            after_delinquency, self._invoices(hie, participant["id"])
        )

        voided = self._administer(hie, may["id"], "VOID", self.VOID_REASON)
        assert voided["status"] == "VOID"
        assert voided["status_reason"] == self.VOID_REASON
        assert voided["amount_paid_cents"] == 0

        after_void = hie.get_participant(participant["id"])
        assert after_void["outstanding_balance_cents"] == 267500
        assert_outstanding_balance_invariant(
            after_void, self._invoices(hie, participant["id"])
        )
        assert hie.get_invoice(june["id"])["status"] == "DELINQUENT"

    def test_the_voided_row_leaves_the_sum_and_its_window_can_be_billed_again(
        self, hie: HieHarness
    ):
        """A void drops one invoice out of the identity; re-billing the freed window restores it.

        PRD 2.10: "Issuing an invoice and then voiding it returns the field to its
        exact pre-issue value."

        PRD 3.9: "The submitted half-open period must not overlap the period of
        any existing invoice for the same participant whose `status` is `ISSUED`,
        `PAID`, `DELINQUENT` or `WRITTEN_OFF`; `VOID` invoices are excluded from
        that test, so voiding an invoice frees its window for re-issue."

        Design: Difficulty/compensating_invariant/voiding_an_invoice_restores_the_outstanding_balance_identity_exactly
        """
        participant = self._health_plan_without_feeds(hie)

        may = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-05-01T00:00:00Z",
            billing_period_end="2026-06-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-06-15T00:00:00Z",
        )
        june = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-07-15T00:00:00Z",
        )
        assert hie.get_participant(participant["id"])["outstanding_balance_cents"] == 535000

        self._administer(hie, june["id"], "VOID", self.VOID_REASON)
        after_void = hie.get_participant(participant["id"])
        assert after_void["outstanding_balance_cents"] == 267500
        assert_outstanding_balance_invariant(
            after_void, self._invoices(hie, participant["id"])
        )
        still_billed = validate_success(
            hie.client.list_participant_participation_invoices(
                hie.admin, participant["id"], status="ISSUED", limit=100
            ),
            200,
        )
        assert [row["id"] for row in still_billed] == [may["id"]]

        rebilled = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-07-15T00:00:00Z",
        )
        assert rebilled["id"] != june["id"]
        assert rebilled["status"] == "ISSUED"
        assert rebilled["total_cents"] == 267500

        after_rebill = hie.get_participant(participant["id"])
        assert after_rebill["outstanding_balance_cents"] == 535000
        ledger = self._invoices(hie, participant["id"])
        assert_outstanding_balance_invariant(after_rebill, ledger)
        assert len(ledger) == 3
        assert sorted(row["status"] for row in ledger) == ["ISSUED", "ISSUED", "VOID"]
