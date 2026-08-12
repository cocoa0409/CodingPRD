"""Transfer guide publication pinning: immutable entries snapshot and the
computed staleness flag."""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]


class TestGuideEntriesSnapshotImmuneToLaterAgreementEdits:
    def _setup_published_guide_then_new_equivalency(self):
        """Agreement ACTIVE with EQ1; guide published (pinning the agreement at
        its then-current version); EQ2 added afterwards, bumping the agreement
        version."""
        partner = fixtures.create_partner(name="Pin College", code="PI")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        eq1 = fixtures.add_equivalency(
            agreement["id"], course["id"], "M-101", external_title="Calc", external_credit_hours=4.0
        )

        guide = fixtures.create_guide(partner["id"])
        guide = get_success_data(api_client.publish_transfer_guide(guide["id"], ADMIN))
        pinned_version = guide["pinned_agreement_version"]
        assert guide["pinned_agreement_id"] == agreement["id"]

        eq2 = fixtures.add_equivalency(
            agreement["id"], course["id"], "M-102", external_title="Calc II", external_credit_hours=4.0
        )
        agreement_after = fixtures.get_agreement(agreement["id"])
        assert agreement_after["version"] == pinned_version + 1, "EQ2 create bumped the version"
        return partner, agreement, guide, eq1, eq2, pinned_version

    def test_entries_snapshot_frozen_at_publish_time(self):
        """PRD §3.9: "captures an immutable `entries_snapshot` of the pinned
        agreement's equivalency rows — each row preserving its
        `external_course_code`, `external_title`, `external_credit_hours`,
        `internal_course_id`, `equivalency_type`, `effective_from`, and
        `effective_until` exactly as they stood at publish time".
        PRD §3.9: "later edits, suspensions, or supersessions of the agreement
        never rewrite a published guide — they merely mark it."

        Design: Corner/endpoints/guide_entries_snapshot_immune_to_later_agreement_edits
        """
        partner, agreement, guide, eq1, eq2, pinned_version = (
            self._setup_published_guide_then_new_equivalency()
        )

        entries_resp = api_client.get_transfer_guide_entries(guide["id"], ADMIN)
        data = validate_success(entries_resp)
        assert data["pinned_agreement_id"] == agreement["id"]
        assert data["pinned_agreement_version"] == pinned_version
        codes = [row["external_course_code"] for row in data["entries"]]
        assert codes == ["M-101"], "snapshot frozen at publish: no M-102 entry"

    def test_is_stale_after_later_agreement_edit(self):
        """PRD §3.9: "A guide's computed `is_stale` flag is true exactly when a
        `pinned_agreement_id` is set and the pinned agreement is no longer
        `ACTIVE` or its current version no longer equals
        `pinned_agreement_version`."

        Design: Corner/endpoints/guide_entries_snapshot_immune_to_later_agreement_edits
        """
        partner, agreement, guide, eq1, eq2, pinned_version = (
            self._setup_published_guide_then_new_equivalency()
        )

        stored = get_success_data(api_client.get_transfer_guide(guide["id"], ADMIN))
        assert stored["is_stale"] is True, (
            "agreement version advanced past pinned_agreement_version"
        )
        assert stored["pinned_agreement_version"] == pinned_version


class TestGuideIsStaleAfterPinnedAgreementSuperseded:
    def test_guide_is_stale_after_pinned_agreement_superseded(self):
        """PRD §3.9: "A guide's computed `is_stale` flag is true exactly when a
        `pinned_agreement_id` is set and the pinned agreement is no longer
        `ACTIVE` or its current version no longer equals
        `pinned_agreement_version`."
        PRD §3.2: "Supersession, finally, fires whenever another agreement with
        the same partner and scope completes a `DRAFT` to `ACTIVE` transition:
        the previously active agreement moves to `SUPERSEDED`".

        Design: Corner/cross_cutting_complexity_layers/guide_is_stale_after_pinned_agreement_superseded
        """
        partner = fixtures.create_partner(name="Stale College", code="SL")
        a1 = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(a1["id"])
        guide = fixtures.create_guide(partner["id"])
        guide = get_success_data(api_client.publish_transfer_guide(guide["id"], ADMIN))
        pin_v = guide["pinned_agreement_version"]
        assert guide["pinned_agreement_id"] == a1["id"]

        amendment = get_success_data(api_client.create_amendment(
            a1["id"], {"effective_start": "2027-07-31", "effective_end": "2029-07-31"}, ADMIN
        ))
        get_success_data(api_client.activate_agreement(amendment["id"], ADMIN))

        a1_after = fixtures.get_agreement(a1["id"])
        assert a1_after["status"] == "SUPERSEDED"

        stored = get_success_data(api_client.get_transfer_guide(guide["id"], ADMIN))
        assert stored["pinned_agreement_id"] == a1["id"], "pin is immutable"
        assert stored["pinned_agreement_version"] == pin_v
        assert stored["is_stale"] is True, "pinned agreement no longer ACTIVE"
