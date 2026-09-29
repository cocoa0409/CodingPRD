"""State machines that are not a straight line: a real cycle, and two axes.

The cycle is closed by a side door - appending evidence, not an explicit reopen -
and the two axes are proved independent by observing all four combinations of
their values on one row.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_credential_axes, assert_field_values
from test_helpers.fixtures import (
    adjudicate_session,
    append_evidence,
    create_active_credential,
    create_holder,
    create_profile,
    first_delivery_of,
    open_address_change,
    open_proofing_session,
    submit_session,
)
from test_helpers.test_users import ADMIN, PROOFING_AGENT

_TWO_STRONG_ITEMS = [
    {
        "evidence_type": "DOCUMENT_SCAN",
        "quality": "STRONG",
        "captured_at": "2026-07-20T09:00:00Z",
        "source_reference": "doc-1",
    },
    {
        "evidence_type": "BIOMETRIC_MATCH",
        "quality": "STRONG",
        "captured_at": "2026-07-20T09:05:00Z",
        "source_reference": "bio-1",
    },
]

_KNOWLEDGE_CHECK = {
    "evidence_type": "KNOWLEDGE_CHECK",
    "quality": "STRONG",
    "captured_at": "2026-07-30T09:00:00Z",
    "source_reference": "kbv-1",
}


class TestReturnedProofingSessionReopensAndVerifiesOnTheSecondLap:
    """COLLECTING -> SUBMITTED -> RETURNED -> COLLECTING is a genuine cycle."""

    @staticmethod
    def _returned_session(api):
        create_profile(api)
        holder = create_holder(api)
        session = open_proofing_session(api, holder["id"])
        append_evidence(api, session["id"], _TWO_STRONG_ITEMS)
        submit_session(api, session["id"])
        return adjudicate_session(
            api, session["id"], "RETURN", "knowledge check missing"
        )

    def test_appending_evidence_is_what_reopens_the_returned_session(self, api):
        """No reopen call exists: the append itself drives RETURNED back to
        COLLECTING and clears the return reason.

        PRD 3.2: "The proofing lifecycle is a genuine cycle, and appending
        evidence is what closes it. Appending an evidence item to a session
        sitting in `RETURNED` reopens the session: its state returns to
        `COLLECTING`, its `return_reason` is cleared to null, and its
        `evidence_count` increments by 1 as it would for any append - completing
        the loop `COLLECTING` -> `SUBMITTED` -> `RETURNED` -> `COLLECTING`."

        Design: Difficulty/non_linear_state_machine/proofing_session_returned_reopens_collecting_and_reverifies
        """
        returned = self._returned_session(api)
        assert_field_values(
            returned,
            {
                "state": "RETURNED",
                "return_reason": "knowledge check missing",
                "submission_count": 1,
            },
        )

        append_evidence(api, returned["id"], [_KNOWLEDGE_CHECK])

        reopened = validate_success(
            api.get_proofing_session(returned["id"], PROOFING_AGENT)
        )
        assert_field_values(
            reopened,
            {"state": "COLLECTING", "return_reason": None, "evidence_count": 3},
        )

    def test_the_second_lap_pays_the_resubmission_penalty_and_still_verifies(self, api):
        """The second trip round the loop is charged 25 points, so the score is
        515 rather than 540, and the session verifies at IAL2.

        PRD 3.2: "The second and every subsequent trip through that loop is what
        the 25-point-per-resubmission penalty in the strict score is charging
        for."
        PRD 3.2: "`assurance_expires_at` is set to that instant advanced by the
        profile's `proofing_validity_days` (180 days by default)"

        Design: Difficulty/non_linear_state_machine/proofing_session_returned_reopens_collecting_and_reverifies
        """
        returned = self._returned_session(api)
        append_evidence(api, returned["id"], [_KNOWLEDGE_CHECK])

        resubmitted = submit_session(api, returned["id"])
        assert_field_values(
            resubmitted, {"state": "SUBMITTED", "submission_count": 2}
        )

        verified = adjudicate_session(api, returned["id"], "VERIFY")
        assert_field_values(
            verified,
            {
                "state": "VERIFIED",
                "adjudication_score": 515,
                "achieved_assurance_level": "IAL2",
                "assurance_expires_at": "2027-01-28T00:00:00Z",
            },
        )


class TestCredentialAxesMoveIndependently:
    """Four observations that no single enum could produce."""

    @staticmethod
    def _active_in_sync_credential(api):
        return create_active_credential(api)

    def test_all_four_combinations_of_the_two_axes_are_reachable(self, api):
        """Lifecycle and sync are driven by different operations and every
        combination of their values shows up on the same row.

        PRD 2.8: "The two axes are genuinely orthogonal. A credential may be
        `ACTIVE` and `UPDATE_PENDING` at the same time; it may be `SUSPENDED` and
        `IN_SYNC` at the same time. Reading one axis tells you nothing about the
        other."

        Design: Difficulty/non_linear_state_machine/credential_lifecycle_and_sync_axes_move_independently
        """
        bundle = self._active_in_sync_credential(api)
        credential_id = bundle["credential"]["id"]
        holder_id = bundle["holder"]["id"]

        first_order = open_address_change(api, holder_id)
        assert_credential_axes(
            validate_success(api.get_credential(credential_id, ADMIN)),
            "ACTIVE",
            "UPDATE_PENDING",
        )

        delivery = first_delivery_of(api, first_order["id"])
        validate_success(
            api.deliver_update(
                delivery["id"], {"device_receipt_token": "receipt-a1"}, ADMIN
            )
        )
        assert_credential_axes(
            validate_success(api.get_credential(credential_id, ADMIN)),
            "ACTIVE",
            "IN_SYNC",
        )

        validate_success(
            api.patch_physical_credential(
                holder_id, {"physical_credential_status": "SUSPENDED"}, ADMIN
            )
        )
        suspended = validate_success(api.get_credential(credential_id, ADMIN))
        assert_credential_axes(suspended, "SUSPENDED", "IN_SYNC")
        assert suspended["suspend_reason"] == "PHYSICAL_CREDENTIAL_SUSPENDED"

        open_address_change(api, holder_id, address_line1="77 Juniper Court")
        assert_credential_axes(
            validate_success(api.get_credential(credential_id, ADMIN)),
            "SUSPENDED",
            "UPDATE_PENDING",
        )

    def test_a_suspended_credential_still_takes_a_new_delivery(self, api):
        """The lifecycle suspension does not stop the sync axis: the second order
        still opens a delivery and pins the newer address version.

        PRD 3.5: "every created delivery drives its target credential's
        `sync_state` to `UPDATE_PENDING` and increments that credential's
        `pending_update_count` by 1. A credential in `IN_SYNC` or in
        `UPDATE_FAILED` moves to `UPDATE_PENDING`; a credential in `STALE` moves
        to `UPDATE_PENDING` as well"
        PRD 3.5: "when that leaves no outstanding delivery - that is, when the
        count had been exactly 1 - the credential's sync axis moves
        `UPDATE_PENDING` -> `IN_SYNC`, its `doc_version` increments by 1, its
        `address_version_synced` takes the owning order's
        `target_address_version`"

        Design: Difficulty/non_linear_state_machine/credential_lifecycle_and_sync_axes_move_independently
        """
        bundle = self._active_in_sync_credential(api)
        credential_id = bundle["credential"]["id"]
        holder_id = bundle["holder"]["id"]

        first_order = open_address_change(api, holder_id)
        delivery = first_delivery_of(api, first_order["id"])
        delivered = validate_success(
            api.deliver_update(
                delivery["id"], {"device_receipt_token": "receipt-a1"}, ADMIN
            )
        )
        assert_field_values(
            delivered, {"status": "DELIVERED", "resulting_doc_version": 2}
        )

        synced = validate_success(api.get_credential(credential_id, ADMIN))
        assert_field_values(synced, {"doc_version": 2, "address_version_synced": 2})

        validate_success(
            api.patch_physical_credential(
                holder_id, {"physical_credential_status": "SUSPENDED"}, ADMIN
            )
        )
        second_order = open_address_change(
            api, holder_id, address_line1="77 Juniper Court"
        )
        assert_field_values(
            second_order, {"delivery_count": 1, "target_address_version": 3}
        )

        pending = validate_success(api.get_credential(credential_id, ADMIN))
        assert pending["pending_update_count"] == 1
