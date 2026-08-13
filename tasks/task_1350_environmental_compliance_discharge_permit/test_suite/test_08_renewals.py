"""Permit renewal applications: submission window, one-open-application rule,
the review/info-request cycle, and the four-link approval cascade with its
permit-version OCC guard (PRD §2.7, §3.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_permit,
    create_active_plan,
    create_renewal_application,
    create_renewal_under_review,
    get_permit_state,
    get_permit_version,
    schedule_sample,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.fixtures import EM, REG

ANY_HEADERS = TEST_USERS["compliance_officer_headers"]  # reads open to all (PRD §2.1)

NEW_PERMIT = {
    "new_permit_number": "NPDES-REN-SUCCESSOR",
    "new_effective_date": "2026-12-31T00:00:00Z",
    "new_expiration_date": "2031-12-31T00:00:00Z",
}

def _renewable_permit(api, permit_number):
    """ACTIVE permit expiring 2026-12-31: the startup clock (2026-08-01) sits
    inside the 180-day pre-expiration renewal window (PRD §3.7)."""
    return create_active_permit(
        permit_number=permit_number, expiration_date="2026-12-31T00:00:00Z"
    )

class TestRenewalSubmission:
    def test_renewal_outside_window_rejected(self, api):
        """PRD §3.7: "Submission is only possible inside the renewal window — the
        logical clock must sit at or after the instant 180 days before the permit's
        `expiration_date` and strictly before the expiration itself, otherwise
        `ERR_RENEWAL_WINDOW_CLOSED`".

        Design: Corner/validations/renewal_outside_window_rejected
        """
        env = create_active_permit(permit_number="NPDES-VAL4")  # expires 2030-12-31
        resp = api.create_renewal_application(
            {"permit_id": env["permit"]["id"],
             "proposed_expiration_date": "2035-12-31T00:00:00Z"},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)

    def test_renewal_already_pending_rejected(self, api):
        """PRD §3.7: "a permit may carry at most one open application, that is one
        in `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED`
        (`ERR_RENEWAL_ALREADY_PENDING`)."

        Design: Corner/validations/renewal_already_pending_rejected
        """
        env = _renewable_permit(api, "NPDES-VAL3")
        create_renewal_application(env["permit"]["id"], "2031-12-31T00:00:00Z")

        resp = api.create_renewal_application(
            {"permit_id": env["permit"]["id"],
             "proposed_expiration_date": "2032-12-31T00:00:00Z"},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_ALREADY_PENDING)

class TestRenewalReviewCycle:
    def test_renewal_info_request_resume_cycle(self, api):
        """PRD §3.7: "Starting review moves the application `SUBMITTED →
        UNDER_REVIEW` (`ERR_RENEWAL_NOT_SUBMITTED`; `RENEWAL_UNDER_REVIEW`). When
        the agency needs more from the facility, requesting information moves
        `UNDER_REVIEW → INFO_REQUESTED` (`ERR_RENEWAL_NOT_UNDER_REVIEW`) and records
        the supplied `info_request_note` on the application (`RENEWAL_INFO_REQUESTED`);
        resuming review returns `INFO_REQUESTED → UNDER_REVIEW`
        (`ERR_RENEWAL_NOT_INFO_REQUESTED`; `RENEWAL_REVIEW_RESUMED`)."

        Design: Corner/state_machines/renewal_info_request_resume_cycle
        """
        env = _renewable_permit(api, "NPDES-SM31")
        renewal = create_renewal_application(env["permit"]["id"], "2031-12-31T00:00:00Z")
        assert renewal["status"] == "SUBMITTED"
        assert renewal["submitted_at"] is not None

        under_review = validate_success(api.start_renewal_review(renewal["id"], REG))
        assert under_review["status"] == "UNDER_REVIEW"

        info_requested = validate_success(api.request_renewal_info(
            renewal["id"], {"info_request_note": "provide sludge disposal records"}, REG
        ))
        assert info_requested["status"] == "INFO_REQUESTED"

        resumed = validate_success(api.resume_renewal_review(renewal["id"], REG))
        assert resumed["status"] == "UNDER_REVIEW"
        assert resumed["info_request_note"] == "provide sludge disposal records", (
            "the most recent info request text is recorded on the application"
        )

    def test_error_renewal_start_review_twice(self, api):
        """PRD §3.7: "Starting review moves the application `SUBMITTED →
        UNDER_REVIEW` (`ERR_RENEWAL_NOT_SUBMITTED`; `RENEWAL_UNDER_REVIEW`)."

        Design: Corner/errors/error_renewal_start_review_twice
        """
        env = _renewable_permit(api, "NPDES-ERR8")
        renewal = create_renewal_application(env["permit"]["id"], "2031-12-31T00:00:00Z")
        validate_success(api.start_renewal_review(renewal["id"], REG))

        resp = api.start_renewal_review(renewal["id"], REG)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_SUBMITTED)

    def test_error_renewal_resume_from_under_review(self, api):
        """PRD §3.7: "resuming review returns `INFO_REQUESTED → UNDER_REVIEW`
        (`ERR_RENEWAL_NOT_INFO_REQUESTED`; `RENEWAL_REVIEW_RESUMED`)."

        Design: Corner/errors/error_renewal_resume_from_under_review
        """
        env = _renewable_permit(api, "NPDES-ERR9")
        renewal = create_renewal_application(env["permit"]["id"], "2031-12-31T00:00:00Z")
        validate_success(api.start_renewal_review(renewal["id"], REG))

        resp = api.resume_renewal_review(renewal["id"], REG)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_INFO_REQUESTED)

    def test_error_renewal_not_found_on_start_review(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_RENEWAL_NOT_FOUND` ..."

        Design: Corner/errors/error_renewal_not_found_on_start_review
        """
        resp = api.start_renewal_review(NON_EXISTENT_UUID, REG)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_FOUND)

class TestRenewalApproval:
    def test_renewal_approve_from_submitted_rejected(self, api):
        """PRD §3.7: "It requires the application `UNDER_REVIEW`
        (`ERR_RENEWAL_NOT_UNDER_REVIEW`) and the permit-version guard of §2.7".

        Design: Corner/state_machines/renewal_approve_from_submitted_rejected
        """
        env = _renewable_permit(api, "NPDES-SM32")
        renewal = create_renewal_application(env["permit"]["id"], "2031-12-31T00:00:00Z")
        payload = dict(NEW_PERMIT, new_permit_number="NPDES-SM32-R")
        payload["expected_permit_version"] = get_permit_version(env["permit"]["id"])

        resp = api.approve_renewal(renewal["id"], payload, REG)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_UNDER_REVIEW)

    def test_occ_renewal_approve_stale_permit_version(self, api):
        """PRD §2.7: "Approving a renewal application likewise requires
        `expected_permit_version` matching the subject permit's current `version`.
        Approval supersedes the permit and increments its `version`; an approval
        carrying an older observed version reflects a stale view of the permit's
        renewal state and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_renewal_approve_stale_permit_version
        """
        env = _renewable_permit(api, "NPDES-OCC3")
        renewal = create_renewal_application(env["permit"]["id"], "2031-12-31T00:00:00Z")
        validate_success(api.start_renewal_review(renewal["id"], REG))
        stale_version = get_permit_version(env["permit"]["id"])
        create_active_plan(env["permit"]["id"], plan_title="Plan A")  # bumps Permit.version
        assert get_permit_version(env["permit"]["id"]) != stale_version

        payload = dict(NEW_PERMIT, new_permit_number="NPDES-OCC3-R")
        payload["expected_permit_version"] = stale_version
        resp = api.approve_renewal(renewal["id"], payload, REG)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_cascade_renewal_approval_supersedes_permit_tree(self, api):
        """PRD §3.7: "Approval then executes a four-link cascade: first, a successor
        Permit is created in `ACTIVE` status from those three values and its
        identifier is recorded as the application's `resulting_permit_id`; second,
        the old permit — whether it still stands `ACTIVE` or has already lapsed to
        `EXPIRED` — moves to `SUPERSEDED` with its `superseded_by_permit_id` pointing
        at the successor and its `version` incremented; third, every outfall of the
        old permit still `ACTIVE` moves to `INACTIVE`; fourth, every sampling event
        of those outfalls still `SCHEDULED` moves to `CANCELLED`."

        Design: Corner/cross_cutting_layers/cascade_renewal_approval_supersedes_permit_tree
        """
        env = _renewable_permit(api, "NPDES-LAY3")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-20T08:00:00Z")
        renewal = create_renewal_under_review(env["permit"]["id"], "2031-12-31T00:00:00Z")

        payload = dict(NEW_PERMIT, new_permit_number="NPDES-LAY3-R")
        payload["expected_permit_version"] = get_permit_version(env["permit"]["id"])
        approved = validate_success(api.approve_renewal(renewal["id"], payload, REG))
        assert approved["status"] == "APPROVED"
        successor_id = approved["resulting_permit_id"]
        assert successor_id, "the successor permit id is recorded (link 1)"

        old_permit = get_permit_state(env["permit"]["id"])
        assert old_permit["status"] == "SUPERSEDED"
        assert old_permit["superseded_by_permit_id"] == successor_id, "link 2"

        outfall = validate_success(api.get_outfall(env["outfall"]["id"], ANY_HEADERS))
        assert outfall["status"] == "INACTIVE", "link 3"
        sample_after = validate_success(api.get_sampling_event(sample["id"], ANY_HEADERS))
        assert sample_after["schedule_status"] == "CANCELLED", "link 4"

        successor = get_permit_state(successor_id)
        assert successor["status"] == "ACTIVE"
        assert successor["permit_number"] == "NPDES-LAY3-R"
