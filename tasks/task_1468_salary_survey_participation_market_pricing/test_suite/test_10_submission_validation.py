"""Submission package content gates: vendor data-use scope and snapshot
content (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    analyst_headers,
    bootstrap_org,
    create_active_vendor,
    create_draft_submission,
    create_open_survey,
    validate_error,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]


class TestSubmissionContentGates:
    def test_vendor_scope_forbids_submission(self, api):
        """PRD §3.4: "the vendor's `data_use_scope` must be
        `FULL_PARTICIPATION`, since a `BENCHMARK_ONLY` contract forbids
        incumbent submissions (`ERR_VENDOR_SCOPE_FORBIDS_SUBMISSION`)".

        Design: Corner/validations/vendor_scope_forbids_submission
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle, data_use_scope="BENCHMARK_ONLY")
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        resp = api.mark_submission_ready(submission["id"],
                                         analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_VENDOR_SCOPE_FORBIDS_SUBMISSION)

    def test_empty_submission_rejected(self, api):
        """PRD §3.4: "the `incumbent_snapshot` must contain at least one entry
        (`ERR_EMPTY_SUBMISSION`)".

        Design: Corner/validations/empty_submission_rejected
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey, entries=[])
        resp = api.mark_submission_ready(submission["id"],
                                         analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_EMPTY_SUBMISSION)
