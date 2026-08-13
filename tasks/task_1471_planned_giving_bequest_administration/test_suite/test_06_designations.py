"""Beneficiary designations: slot discipline, verification gates, resubmission."""
from test_helpers import (
    ApiErrorId,
    create_designation_payload,
    make_active_rate_table,
    make_donor,
    make_draft_agreement,
    make_verified_designation,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_agreement():
    donor = make_donor(full_name="Designation Donor")
    make_active_rate_table()
    return make_draft_agreement(donor["id"])


class TestSlotDiscipline:
    def test_slot_occupied_rejected(self, api, gift_officer_headers):
        """PRD §3.4: "Slot discipline is strict: at most one designation per
        (`gift_agreement_id`, `slot`) pair may be `SUBMITTED` at any moment, and
        the rule is enforced both at creation and at submission — a collision
        is rejected with `ERR_SLOT_OCCUPIED` (HTTP 409)."

        Design: Corner/validations/slot_occupied_rejected
        """
        agreement = _draft_agreement()
        first = validate_success(
            api.create_beneficiary_designation(
                create_designation_payload(
                    gift_agreement_id=agreement["id"], beneficiary_name="First"
                ),
                gift_officer_headers,
            ),
            201,
        )
        validate_success(
            api.transition_beneficiary_designation(
                first["id"], {"action": "SUBMIT"}, gift_officer_headers
            )
        )

        # Second designation on the same (agreement, slot) while SUBMITTED.
        resp = api.create_beneficiary_designation(
            create_designation_payload(
                gift_agreement_id=agreement["id"], beneficiary_name="Second"
            ),
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_OCCUPIED)
        assert resp.status_code == 409

        # Occupancy is per (agreement, slot): another slot accepts a designation.
        other = validate_success(
            api.create_beneficiary_designation(
                create_designation_payload(
                    gift_agreement_id=agreement["id"],
                    slot="CONTINGENT",
                    beneficiary_name="Other Slot",
                ),
                gift_officer_headers,
            ),
            201,
        )
        assert other["status"] == "DRAFT"
        assert other["slot"] == "CONTINGENT"


class TestVerificationGates:
    def test_document_not_received_rejected(self, api, gift_officer_headers, gift_admin_headers):
        """PRD §3.4: "Verifying a `SUBMITTED` designation requires
        `document_received` to be true — otherwise `ERR_DOCUMENT_NOT_RECEIVED`
        (HTTP 409)".

        Design: Corner/validations/document_not_received_rejected
        """
        agreement = _draft_agreement()
        designation = validate_success(
            api.create_beneficiary_designation(
                create_designation_payload(
                    gift_agreement_id=agreement["id"], document_received=False
                ),
                gift_officer_headers,
            ),
            201,
        )
        validate_success(
            api.transition_beneficiary_designation(
                designation["id"], {"action": "SUBMIT"}, gift_officer_headers
            )
        )
        resp = api.transition_beneficiary_designation(
            designation["id"], {"action": "VERIFY"}, gift_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_RECEIVED)
        assert resp.status_code == 409
        after = validate_success(
            api.get_beneficiary_designation(designation["id"], gift_admin_headers)
        )
        assert after["status"] == "SUBMITTED"

    def test_designation_verify_supersedes_prior_verified(
        self, api, gift_officer_headers, gift_admin_headers
    ):
        """PRD §3.4: "Verifying a `SUBMITTED` designation requires
        `document_received` to be true — otherwise `ERR_DOCUMENT_NOT_RECEIVED`
        (HTTP 409) — and moves it to `VERIFIED`; as a side effect, any **other**
        designation for the same agreement and slot currently in `VERIFIED`
        flips to `SUPERSEDED`, with its `version` incremented."

        Design: Corner/state_machines/designation_verify_supersedes_prior_verified
        """
        agreement = _draft_agreement()
        first = make_verified_designation(agreement["id"], beneficiary_name="First")
        assert first["status"] == "VERIFIED"

        # A VERIFIED designation does not block creation/submission of a rival.
        second = validate_success(
            api.create_beneficiary_designation(
                create_designation_payload(
                    gift_agreement_id=agreement["id"], beneficiary_name="Second"
                ),
                gift_officer_headers,
            ),
            201,
        )
        validate_success(
            api.transition_beneficiary_designation(
                second["id"], {"action": "SUBMIT"}, gift_officer_headers
            )
        )
        verified = validate_success(
            api.transition_beneficiary_designation(
                second["id"], {"action": "VERIFY"}, gift_admin_headers
            )
        )
        assert verified["status"] == "VERIFIED"

        superseded, meta = validate_paginated(
            api.list_beneficiary_designations(
                gift_admin_headers,
                params={
                    "gift_agreement_id": agreement["id"],
                    "slot": "PRIMARY_1",
                    "status": "SUPERSEDED",
                },
            )
        )
        assert meta["total_count"] == 1
        assert superseded[0]["id"] == first["id"]


class TestRejectResubmitLoop:
    def test_designation_reject_resubmit_loop(self, api, gift_officer_headers, gift_admin_headers):
        """PRD §3.4: "A `GiftOfficer` submits a designation from `DRAFT`, or
        resubmits one from `REJECTED` (the revise-and-resubmit loop, which
        clears the stored `rejection_reason`), via the `SUBMIT` action."
        PRD §3.4: "Rejecting a `SUBMITTED` designation moves it to `REJECTED`
        and stores the supplied `rejection_reason`."

        Design: Corner/state_machines/designation_reject_resubmit_loop
        """
        agreement = _draft_agreement()
        designation = validate_success(
            api.create_beneficiary_designation(
                create_designation_payload(
                    gift_agreement_id=agreement["id"],
                    slot="CONTINGENT",
                    beneficiary_name="Maybe",
                ),
                gift_officer_headers,
            ),
            201,
        )
        validate_success(
            api.transition_beneficiary_designation(
                designation["id"], {"action": "SUBMIT"}, gift_officer_headers
            )
        )
        rejected = validate_success(
            api.transition_beneficiary_designation(
                designation["id"],
                {"action": "REJECT", "rejection_reason": "illegible signature"},
                gift_admin_headers,
            )
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "illegible signature"

        resubmitted = validate_success(
            api.transition_beneficiary_designation(
                designation["id"], {"action": "SUBMIT"}, gift_officer_headers
            )
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted.get("rejection_reason") is None

        verified = validate_success(
            api.transition_beneficiary_designation(
                designation["id"], {"action": "VERIFY"}, gift_admin_headers
            )
        )
        assert verified["status"] == "VERIFIED"
