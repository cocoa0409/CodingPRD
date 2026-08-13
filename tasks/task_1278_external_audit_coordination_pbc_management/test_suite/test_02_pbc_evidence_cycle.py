"""The PBC cycle: ownership, evidence versions, review, and counters."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_engagement,
    assert_evidence_upload,
    assert_pbc_request,
    create_accepted_pbc,
    create_engagement,
    create_evidence_upload_payload,
    create_fieldwork_engagement,
    create_pbc,
    create_pbc_request_payload,
    create_rejected_pbc,
    create_submitted_pbc,
    engagement_version,
    get_engagement,
    make_preparer_headers,
    review_pbc,
    submit_pbc,
    upload_evidence,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import VALID_SHA256_A, VALID_SHA256_B

CONTROLLER = TEST_USERS["controller_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _get_pbc(pbc_id):
    resp = api_client.get_pbc_request(pbc_id, CONTROLLER)
    return validate_success(resp)


def _get_upload(upload_id):
    resp = api_client.get_evidence_upload(upload_id, CONTROLLER)
    return validate_success(resp)


class TestRejectLoopCycle:

    def test_rejected_pbc_reopens_on_next_upload(self):
        """PRD §3.2: "On `REJECT`, every `PENDING_REVIEW` upload becomes
        `REJECTED` and the request's `rejection_count` increments by one,
        returning the request to `REJECTED` — from which the owner may upload
        again and repeat the cycle."
        PRD §3.2: "assigned a `version_seq` equal to one more than the highest
        existing `version_seq` on that request (the first upload therefore
        takes sequence 1)."

        Design: Difficulty/non_linear_state_machine/pbc_request_reject_loop_cycle
        """
        eng, _loc = create_fieldwork_engagement(client_name="EpsilonLtd")
        pbc, _u1 = create_rejected_pbc(eng["id"], owner="prep1")
        assert pbc["rejection_count"] == 1

        resp = api_client.upload_evidence(
            pbc["id"],
            create_evidence_upload_payload(
                engagement_version(eng["id"]),
                file_name="gl_v2.csv", file_size_bytes=2048,
                sha256=VALID_SHA256_B),
            make_preparer_headers("prep1"),
        )
        upload2 = validate_success(resp, expected_status=201)
        assert_evidence_upload(upload2)
        assert upload2["version_seq"] == 2, (
            f"second upload must take version_seq 2, got "
            f"{upload2['version_seq']}"
        )
        after = _get_pbc(pbc["id"])
        assert after["status"] == "IN_PROGRESS", (
            f"REJECTED request must cycle back to IN_PROGRESS on upload, "
            f"got {after['status']}"
        )
        assert after["rejection_count"] == 1, (
            "upload leaves rejection_count unchanged (PRD §3.2: "
            "\"its `rejection_count` is left unchanged\")"
        )

    def test_second_reject_increments_rejection_count(self):
        """PRD §3.2: "On `REJECT`, every `PENDING_REVIEW` upload becomes
        `REJECTED` and the request's `rejection_count` increments by one,
        returning the request to `REJECTED` — from which the owner may upload
        again and repeat the cycle."

        Design: Difficulty/non_linear_state_machine/pbc_request_reject_loop_cycle
        """
        eng, _loc = create_fieldwork_engagement(client_name="EpsilonLtd")
        pbc, _u1 = create_rejected_pbc(eng["id"], owner="prep1")
        # Second cycle: upload again (REJECTED -> IN_PROGRESS), submit, reject.
        upload_evidence(pbc["id"], eng["id"], owner="prep1",
                        file_name="gl_v2.pdf", sha256=VALID_SHA256_B)
        submit_pbc(pbc["id"], owner="prep1")
        pbc2 = review_pbc(pbc["id"], "REJECT", rationale="Still insufficient")
        assert pbc2["status"] == "REJECTED"
        assert pbc2["rejection_count"] == 2, (
            f"each REJECT increments rejection_count by one, got "
            f"{pbc2['rejection_count']}"
        )


class TestOpenPbcCountInvariant:

    def test_accept_decrements_open_pbc_count_to_zero(self):
        """PRD §3.2: "A new request starts `OPEN` with `rejection_count` at
        zero, and the engagement's `open_pbc_count` increments by one."
        PRD §3.2: "On `ACCEPT`, every `PENDING_REVIEW` upload becomes
        `ACCEPTED`, any earlier `ACCEPTED` uploads for the same request become
        `SUPERSEDED` so only the latest survives, `current_evidence_id` is set
        to the latest accepted upload's `id`, `rejection_count` resets to
        zero, and the engagement's `open_pbc_count` decrements by one."

        Design: Difficulty/compensating_invariant/pbc_accept_decrements_open_count_to_zero
        """
        eng, _loc = create_fieldwork_engagement(client_name="SigmaCo")
        assert eng["open_pbc_count"] == 0
        pbc = create_pbc(eng["id"], owner="prep1", title="GL")
        after_create = get_engagement(eng["id"])
        assert after_create["open_pbc_count"] == 1, (
            f"creation increments open_pbc_count by one, got "
            f"{after_create['open_pbc_count']}"
        )
        upload_evidence(pbc["id"], eng["id"], owner="prep1",
                        file_name="gl.pdf", sha256=VALID_SHA256_A)
        submit_pbc(pbc["id"], owner="prep1")
        accepted = review_pbc(pbc["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        after_accept = get_engagement(eng["id"])
        assert after_accept["open_pbc_count"] == 0, (
            f"accept decrements open_pbc_count back to baseline, got "
            f"{after_accept['open_pbc_count']}"
        )

    def test_reject_keeps_open_pbc_count(self):
        """PRD §3.2: "On `REJECT`, every `PENDING_REVIEW` upload becomes
        `REJECTED` and the request's `rejection_count` increments by one,
        returning the request to `REJECTED` — from which the owner may upload
        again and repeat the cycle."
        PRD §3.8: "no PBC request may remain in `OPEN`, `IN_PROGRESS`,
        `SUBMITTED`, or `REJECTED` (`ERR_UNRESOLVED_PBC_REQUESTS`)".

        Design: Difficulty/compensating_invariant/pbc_accept_decrements_open_count_to_zero
        """
        eng, _loc = create_fieldwork_engagement(client_name="SigmaCo")
        pbc = create_pbc(eng["id"], owner="prep1", title="GL")
        upload_evidence(pbc["id"], eng["id"], owner="prep1",
                        file_name="gl.pdf", sha256=VALID_SHA256_A)
        submit_pbc(pbc["id"], owner="prep1")
        rejected = review_pbc(pbc["id"], "REJECT", rationale="Needs more")
        assert rejected["status"] == "REJECTED"
        after = get_engagement(eng["id"])
        assert after["open_pbc_count"] == 1, (
            "REJECT decrements nothing — a REJECTED request still counts as "
            f"open (it blocks fieldwork completion), got "
            f"{after['open_pbc_count']}"
        )


class TestUploadEngagementDependency:

    def test_upload_rejected_when_engagement_in_planning(self):
        """PRD §3.2: "Uploading a new evidence version is a `Preparer` action
        permitted only while the request is `OPEN` or `REJECTED` — otherwise
        `ERR_PBC_NOT_OPEN_FOR_UPLOAD` — and only while the engagement is in
        `FIELDWORK` (`ERR_ENGAGEMENT_NOT_IN_FIELDWORK`) with posture `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/evidence_upload_requires_engagement_in_fieldwork
        """
        eng = create_engagement(client_name="NuInc")
        pbc = create_pbc(eng["id"], owner="prep1", title="Bank recs")
        resp = api_client.upload_evidence(
            pbc["id"],
            create_evidence_upload_payload(
                engagement_version(eng["id"]), file_name="rec.pdf",
                sha256=VALID_SHA256_A),
            make_preparer_headers("prep1"),
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_IN_FIELDWORK)
        after = _get_pbc(pbc["id"])
        assert after["status"] == "OPEN", (
            f"failed upload must not move the request, got {after['status']}"
        )

    def test_upload_succeeds_when_engagement_in_fieldwork(self):
        """PRD §3.2: "A successful upload creates an `EvidenceUpload` in
        `PENDING_REVIEW`, stamped with the logical clock as `uploaded_at`,
        recorded with the uploader's `X-User-ID` as `uploader_user_id`, and
        assigned a `version_seq` equal to one more than the highest existing
        `version_seq` on that request (the first upload therefore takes
        sequence 1). The request moves to `IN_PROGRESS`, its `rejection_count`
        is left unchanged".

        Design: Difficulty/cross_entity_state_dependency/evidence_upload_requires_engagement_in_fieldwork
        """
        eng, _loc = create_fieldwork_engagement(client_name="NuInc")
        pbc = create_pbc(eng["id"], owner="prep1", title="Bank recs")
        resp = api_client.upload_evidence(
            pbc["id"],
            create_evidence_upload_payload(
                engagement_version(eng["id"]), file_name="rec.pdf",
                sha256=VALID_SHA256_A),
            make_preparer_headers("prep1"),
        )
        upload = validate_success(resp, expected_status=201)
        assert_evidence_upload(upload)
        assert upload["status"] == "PENDING_REVIEW"
        assert upload["version_seq"] == 1
        assert upload["uploader_user_id"] == "prep1"
        assert upload["pbc_request_id"] == pbc["id"]
        assert upload["engagement_id"] == eng["id"]
        after = _get_pbc(pbc["id"])
        assert after["status"] == "IN_PROGRESS"
        assert after["rejection_count"] == 0


class TestUploadFieldShape:

    def test_upload_invalid_sha256_rejected(self):
        """PRD §3.2: "a `sha256` content hash of exactly 64 lowercase
        hexadecimal characters (else `ERR_INVALID_HASH`)".

        Design: Corner/entities/evidence_upload_invalid_sha256_rejected
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        pbc = create_pbc(eng["id"], owner="prep1", title="T")
        resp = api_client.upload_evidence(
            pbc["id"],
            create_evidence_upload_payload(
                engagement_version(eng["id"]), file_name="f.pdf",
                file_size_bytes=100, sha256="not_a_valid_hash"),
            make_preparer_headers("prep1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_HASH)


class TestSubmitAndTerminalStates:

    def test_submit_from_open_returns_invalid_state(self):
        """PRD §3.2: "submitting from any state other than `IN_PROGRESS` is
        rejected with `ERR_PBC_NOT_SUBMITTABLE`, submitting without pending
        evidence with `ERR_NO_PENDING_EVIDENCE`, and submitting as anyone but
        the owner with `ERR_NOT_REQUEST_OWNER`."

        Design: Corner/state_machines/pbc_submit_from_open_returns_invalid_state
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        pbc = create_pbc(eng["id"], owner="prep1", title="T")
        resp = api_client.submit_pbc_request(
            pbc["id"], make_preparer_headers("prep1"))
        validate_error(resp, ApiErrorId.ERR_PBC_NOT_SUBMITTABLE)
        after = _get_pbc(pbc["id"])
        assert after["status"] == "OPEN"

    def test_accepted_pbc_rejects_further_upload(self):
        """PRD §3.2: "Uploading a new evidence version is a `Preparer` action
        permitted only while the request is `OPEN` or `REJECTED` — otherwise
        `ERR_PBC_NOT_OPEN_FOR_UPLOAD`".
        PRD §3.2: "`ACCEPTED` is terminal for the request".

        Design: Corner/state_machines/pbc_terminal_accepted_rejects_further_upload
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        pbc, _u1 = create_accepted_pbc(eng["id"], owner="prep1")
        resp = api_client.upload_evidence(
            pbc["id"],
            create_evidence_upload_payload(
                engagement_version(eng["id"]), file_name="f2.pdf",
                file_size_bytes=200, sha256=VALID_SHA256_B),
            make_preparer_headers("prep1"),
        )
        validate_error(resp, ApiErrorId.ERR_PBC_NOT_OPEN_FOR_UPLOAD)
        after = _get_pbc(pbc["id"])
        assert after["status"] == "ACCEPTED"


class TestSecondCycleAcceptance:

    def test_second_cycle_accept_updates_current_evidence(self):
        """PRD §3.2: "On `REJECT`, every `PENDING_REVIEW` upload becomes
        `REJECTED` and the request's `rejection_count` increments by one".
        PRD §3.2: "On `ACCEPT`, every `PENDING_REVIEW` upload becomes
        `ACCEPTED`, any earlier `ACCEPTED` uploads for the same request become
        `SUPERSEDED` so only the latest survives, `current_evidence_id` is set
        to the latest accepted upload's `id`, `rejection_count` resets to
        zero, and the engagement's `open_pbc_count` decrements by one."

        Design: Corner/state_machines/evidence_superseded_on_second_acceptance
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        pbc = create_pbc(eng["id"], owner="prep1", title="T")
        u1 = upload_evidence(pbc["id"], eng["id"], owner="prep1",
                             file_name="v1.pdf", file_size_bytes=100,
                             sha256=VALID_SHA256_A)
        submit_pbc(pbc["id"], owner="prep1")
        review_pbc(pbc["id"], "REJECT", rationale="needs more")
        u2 = upload_evidence(pbc["id"], eng["id"], owner="prep1",
                             file_name="v2.pdf", file_size_bytes=200,
                             sha256=VALID_SHA256_B)
        submit_pbc(pbc["id"], owner="prep1")
        accepted = review_pbc(pbc["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["current_evidence_id"] == u2["id"], (
            f"current_evidence_id must point at the latest accepted upload "
            f"{u2['id']}, got {accepted['current_evidence_id']}"
        )
        assert accepted["rejection_count"] == 0, \
            "rejection_count resets to zero on ACCEPT"
        u1_after = _get_upload(u1["id"])
        assert u1_after["status"] == "REJECTED", (
            f"first upload was rejected in the prior cycle and stays "
            f"REJECTED, got {u1_after['status']}"
        )
        u2_after = _get_upload(u2["id"])
        assert u2_after["status"] == "ACCEPTED"


class TestOwnershipAndDeadline:

    def test_non_owner_cannot_upload_evidence(self):
        """PRD §3.2: "The uploader must be the request's owner: `X-User-ID` is
        compared to `owner_user_id`, and a mismatch is rejected with
        `ERR_NOT_REQUEST_OWNER`."

        Design: Corner/validations/non_owner_cannot_upload_evidence
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        pbc = create_pbc(eng["id"], owner="prep1", title="T")
        resp = api_client.upload_evidence(
            pbc["id"],
            create_evidence_upload_payload(
                engagement_version(eng["id"]), file_name="x.pdf",
                file_size_bytes=100, sha256=VALID_SHA256_A),
            make_preparer_headers("prep2"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_REQUEST_OWNER)

    def test_due_date_after_filing_deadline_rejected(self):
        """PRD §3.2: "The due date must fall on or before the engagement's
        `filing_deadline`; a later date is rejected with
        `ERR_DEADLINE_AFTER_FILING`."

        Design: Corner/validations/pbc_due_date_after_filing_deadline_rejected
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        resp = api_client.create_pbc_request(
            create_pbc_request_payload(eng["id"], title="T",
                                       owner_user_id="prep1",
                                       due_date="2027-01-15"),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_AFTER_FILING)


class TestPbcLookupAndListing:

    def test_pbc_not_found_returns_404(self):
        """PRD §2.5: "The server confirms the existence of each identifier in
        path order and rejects the request immediately with the 404 error
        corresponding to the first identifier that does not resolve:
        `ERR_ENGAGEMENT_NOT_FOUND` for engagements, `ERR_LOCATION_NOT_FOUND`
        for locations, `ERR_PBC_NOT_FOUND` for PBC requests".

        Design: Corner/errors/error_pbc_not_found
        """
        create_fieldwork_engagement(client_name="C")
        resp = api_client.get_pbc_request(NON_EXISTENT_UUID, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_PBC_NOT_FOUND)

    def test_pbc_requests_list_filtered_by_status(self):
        """PRD §3.2: "The request list can be filtered by `engagement_id` and
        `status`, and each open item in the list response carries a computed
        `pbc_aging_score` (below)."

        Design: Corner/endpoints/pbc_requests_list_filtered_by_status
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        p1 = create_pbc(eng["id"], owner="prep1", title="T1")
        p2, _u = create_accepted_pbc(eng["id"], owner="prep1", title="T2")

        data, meta = validate_paginated(
            api_client.list_pbc_requests(
                CONTROLLER, params={"engagement_id": eng["id"]}))
        assert {p["id"] for p in data} == {p1["id"], p2["id"]}, \
            "unfiltered list must return both requests"
        assert meta["total_count"] == 2

        data_open, meta_open = validate_paginated(
            api_client.list_pbc_requests(
                CONTROLLER,
                params={"engagement_id": eng["id"], "status": "OPEN"}))
        assert [p["id"] for p in data_open] == [p1["id"]], \
            "status=OPEN must return only the OPEN request"
        assert meta_open["total_count"] == 1

        data_acc, meta_acc = validate_paginated(
            api_client.list_pbc_requests(
                CONTROLLER,
                params={"engagement_id": eng["id"], "status": "ACCEPTED"}))
        assert [p["id"] for p in data_acc] == [p2["id"]], \
            "status=ACCEPTED must return only the ACCEPTED request"
        assert meta_acc["total_count"] == 1
        for item in data:
            assert_pbc_request(item)
