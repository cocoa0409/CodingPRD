"""Read-your-write consistency: the intake response already carries every cascade."""

from test_helpers import (
    evidence_item_payload,
    setup_corner_base,
    validate_paginated,
    validate_success,
)


class TestIntakeConsistency:
    """Intake writes an item, a determination, a chain entry and two case counters."""

    def test_intake_response_reflects_all_cascaded_state_immediately(self, api):
        """The creating response, and the reads right after it, show the whole cascade.

        PRD 2.1: "Chain of custody entries record the acting role in `actor_role` in all
        cases, and populate `actor_custodian_id` only when the acting principal is an
        entity-backed custodian; entries produced by the nightly sweep or by a cascade
        record `SYSTEM` in `actor_role` and leave `actor_custodian_id` null."
        PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."
        PRD 3.2: "`intake_at` is set from the logical clock and becomes the anchor both of
        the preliminary retention variant and of storage-cost recovery at auction
        settlement."
        PRD 3.2: "`custody_state` starts at `LOGGED` and `disposition_state` at `RETAINED`,
        with `storage_location_id`, `current_holder_id` null and `open_transfer_count` at
        0."
        PRD 3.2: "Where the item must live is derived at intake and stored on the item as
        `required_storage_category`, and it is re-read on every storage assignment and on
        every relocation of a misplaced item."
        PRD 3.2: "A `GENERAL` item requires `HIGH_VALUE_VAULT` when its appraised value is
        at least 500000 cents — that is, five thousand dollars or more, with exactly 500000
        already qualifying — and `GENERAL` otherwise."
        PRD 3.2: "A preliminary retention determination is created immediately, writing
        `retention_release_at` and `retention_basis` onto the item."
        PRD 3.2: "The first chain of custody entry is appended with `event_type` of
        `INTAKE` and `sequence_no` of 1."
        PRD 3.2: "Finally the owning case has `item_count` and `undisposed_item_count` each
        incremented by 1 and its `version` incremented by 1."
        PRD 3.2: "For agency `CPD`, case `26-00001` and sequence 1, the barcode is
        `CPD-26-00001-0001-2`."
        PRD 3.4: "Under the `PRELIMINARY` variant the `anchor_at` is the item's
        `intake_at`, the `statute_days_applied` is the statute's full
        `statutory_retention_days`, and the release instant is the anchor plus those whole
        days; the appeal window and the ninety-day floor are both ignored."
        PRD 4: "Operations that bring a new resource into existence — registering a room,
        statute, location or custodian, opening a case, logging an evidence item, recording
        a retention determination, requesting a custody transfer, opening a disposition
        order, issuing an owner notice, or scheduling an audit session —
        return `201 Created`."

        Design: Corner/consistency_model/intake_response_reflects_all_cascaded_state_immediately
        """
        env = setup_corner_base()

        created = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    env["case1_id"],
                    item_description="Item whose cascade must be visible at once",
                    category="GENERAL",
                    packaging_type="PAPER_BAG",
                    appraised_value_cents=100,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                env["tech_headers"],
            ),
            201,
        )

        # Everything the intake cascade derived is already in the creating response.
        assert created["barcode"] == "CPD-26-00001-0001-2"
        assert created["item_sequence"] == 1
        assert created["intake_at"] == "2026-08-01T00:00:00.000Z"
        assert created["retention_basis"] == "PRELIMINARY"
        assert created["retention_release_at"] == "2027-08-01T00:00:00.000Z"
        assert created["custody_state"] == "LOGGED"
        assert created["disposition_state"] == "RETAINED"
        assert created["storage_location_id"] is None
        assert created["current_holder_id"] is None
        assert created["open_transfer_count"] == 0
        assert created["required_storage_category"] == "GENERAL"
        assert created["version"] == 1

        # The parent counters are not deferred to a sweep.
        case = validate_success(api.get_case(env["case1_id"], env["manager"]), 200)
        assert case["item_count"] == 1
        assert case["undisposed_item_count"] == 1

        # The preliminary determination is queryable in the very next request.
        determinations, determination_meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": created["id"]}
            )
        )
        assert determination_meta["total_count"] == 1
        assert determinations[0]["resolved_basis"] == "PRELIMINARY"
        assert determinations[0]["anchor_at"] == "2026-08-01T00:00:00.000Z"
        assert determinations[0]["statute_days_applied"] == 365
        assert determinations[0]["computed_release_at"] == "2027-08-01T00:00:00.000Z"
        assert determinations[0]["superseded"] is False

        # So is the chain of custody record.
        events, event_meta = validate_paginated(
            api.list_chain_events(
                env["aud_headers"], params={"evidence_item_id": created["id"]}
            )
        )
        assert event_meta["total_count"] == 1
        assert events[0]["event_type"] == "INTAKE"
        assert events[0]["sequence_no"] == 1
        assert events[0]["actor_role"] == "EvidenceTechnician"
        assert events[0]["actor_custodian_id"] == env["tech_id"]
        assert events[0]["occurred_at"] == "2026-08-01T00:00:00.000Z"
