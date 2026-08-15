"""Completion preconditions: sign-off gate, photo gate, and their fixed order."""
from test_helpers import (
    ApiErrorId,
    complete_payload,
    get_work_order,
    make_technician_headers,
    setup_in_progress_work_order,
    sign_off,
    validate_error,
)


class TestCompletionGates:
    def test_complete_without_signoff_rejected(self, api):
        """PRD §3.4: "`resident_signoff` must be true; otherwise the completion is rejected with `ERR_RESIDENT_SIGNOFF_REQUIRED` (HTTP 409)."

        Design: Corner/validations/complete_without_signoff_rejected
        """
        bundle = setup_in_progress_work_order("So2 Property", unit_number="417")
        wo = bundle["work_order"]
        resp = api.complete_work_order(
            wo["id"],
            complete_payload(photo_urls=["https://x/y1.jpg"], damage_reported=False),
            make_technician_headers(bundle["technician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENT_SIGNOFF_REQUIRED)
        assert get_work_order(wo["id"])["status"] == "IN_PROGRESS"

    def test_signoff_violation_outranks_photo_violation(self, api):
        """PRD §3.4: "Five preconditions gate the transition from `IN_PROGRESS` to `COMPLETED`, evaluated in a fixed order: the state check comes first (a completion attempted on a work order that is not `IN_PROGRESS` is `ERR_INVALID_STATE`), then ownership, then the open-purchase-request block, then the sign-off requirement, then the photo requirement, and finally the damage-estimate shape check."

        Design: Difficulty/priority_pair_validation_conflict/signoff_beats_photos_on_complete
        """
        bundle = setup_in_progress_work_order("Prio2 Property", unit_number="110")
        wo = bundle["work_order"]
        # Both the sign-off rule (not signed off) and the photo rule (empty
        # photo_urls) are violated; the sign-off requirement is judged first.
        resp = api.complete_work_order(
            wo["id"],
            complete_payload(photo_urls=[], damage_reported=False),
            make_technician_headers(bundle["technician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENT_SIGNOFF_REQUIRED)

    def test_photo_violation_surfaces_once_signoff_recorded(self, api):
        """PRD §3.4: "At least one photo URL must be supplied; an empty `photo_urls` array is rejected with `ERR_COMPLETION_PHOTOS_REQUIRED` (HTTP 422)."
        PRD §3.4: "Five preconditions gate the transition from `IN_PROGRESS` to `COMPLETED`, evaluated in a fixed order: the state check comes first (a completion attempted on a work order that is not `IN_PROGRESS` is `ERR_INVALID_STATE`), then ownership, then the open-purchase-request block, then the sign-off requirement, then the photo requirement, and finally the damage-estimate shape check."

        Design: Difficulty/priority_pair_validation_conflict/signoff_beats_photos_on_complete
        """
        bundle = setup_in_progress_work_order("Prio2b Property", unit_number="110")
        wo = bundle["work_order"]
        sign_off(wo["id"], bundle["resident"]["id"])
        resp = api.complete_work_order(
            wo["id"],
            complete_payload(photo_urls=[], damage_reported=False),
            make_technician_headers(bundle["technician"]["id"]),
        )
        # With the sign-off requirement satisfied, the next gate — the photo
        # requirement — is the one that fires.
        validate_error(resp, ApiErrorId.ERR_COMPLETION_PHOTOS_REQUIRED)
        assert get_work_order(wo["id"])["status"] == "IN_PROGRESS"
