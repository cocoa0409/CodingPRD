"""Development documentation standards and review decisions (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    approve_model,
    create_documentation_payload,
    create_model,
    decide_documentation,
    submit_documentation,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]


class TestDocumentationCreation:
    def test_documentation_creation_stamps_submitter_and_status(self, api):
        """PRD §3.2: "Submission is impossible on a retired model
        (`ERR_MODEL_ALREADY_RETIRED`), and the server records the submitter's
        `X-User-ID` as `submitted_by_user_id`. A new package starts in `SUBMITTED`."
        PRD §2.4: "Every resource except one also carries a `version`, an integer that
        increments on every mutation of that resource."

        Design: Corner/entities/documentation_creation_stamps_submitter_and_status
        """
        model = create_model(name="Doc M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        doc = validate_success(
            api.submit_documentation(model["id"], create_documentation_payload(version_label="2.1"), OWNER_A),
            expected_status=201,
        )
        assert doc["status"] == "SUBMITTED"
        assert doc["submitted_by_user_id"] == "u_own_a"
        assert isinstance(doc["version"], int), "a documentation package carries an integer version"
        assert doc["model_id"] == model["id"]

    def test_documentation_missing_evidence_flag_rejected(self, api):
        """PRD §3.2: "The owning `ModelOwner` submits a package carrying a free-form
        `version_label` and three evidence flags — `has_development_evidence`,
        `has_testing_evidence`, and `has_data_lineage` — all three of which must be
        present and true at creation; a package missing any of them is rejected with
        `ERR_DOCUMENTATION_INCOMPLETE` (HTTP 409)."

        Design: Corner/entities/documentation_missing_evidence_flag_rejected
        """
        model = create_model(name="DocInc M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        payload = create_documentation_payload(has_data_lineage=False)
        err = validate_error(
            api.submit_documentation(model["id"], payload, OWNER_A),
            ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE,
        )
        assert err["error_id"] == "ERR_DOCUMENTATION_INCOMPLETE"
        docs, meta = validate_paginated(api.list_documentations(model["id"], OFFICER))
        assert docs == [], "no documentation row may be persisted after the rejection"


class TestDocumentationDecisions:
    def test_documentation_rejection_leaves_no_approved_doc(self, api):
        """PRD §3.2: "Rejection moves the package to `REJECTED`."
        PRD §3.5: "at least one `APPROVED` documentation package must exist, else
        `ERR_NO_APPROVED_DOCUMENTATION`".

        Design: Corner/state_machines/documentation_rejection_leaves_no_approved_doc
        """
        model = create_model(name="Rej M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        doc = submit_documentation(model["id"])
        decided = validate_success(
            api.decide_documentation(model["id"], doc["id"], {"decision": "REJECT"}, OFFICER)
        )
        assert decided["status"] == "REJECTED"
        err = validate_error(api.approve_model(model["id"], OFFICER), ApiErrorId.ERR_NO_APPROVED_DOCUMENTATION)
        assert err["error_id"] == "ERR_NO_APPROVED_DOCUMENTATION"

    def test_documentation_decide_twice_returns_not_submitted(self, api):
        """PRD §3.2: "Two gates apply, in pipeline order: the package must still be
        `SUBMITTED` — deciding an already-decided package fails with
        `ERR_DOCUMENTATION_NOT_SUBMITTED` — and then the segregation-of-duties gate of
        §2.9 forbids the officer from deciding their own submission."

        Design: Corner/state_machines/documentation_decide_twice_returns_not_submitted
        """
        model = create_model(name="Dec M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        doc = submit_documentation(model["id"])
        validate_success(api.decide_documentation(model["id"], doc["id"], {"decision": "APPROVE"}, OFFICER))
        err = validate_error(
            api.decide_documentation(model["id"], doc["id"], {"decision": "REJECT"}, OFFICER),
            ApiErrorId.ERR_DOCUMENTATION_NOT_SUBMITTED,
        )
        assert err["error_id"] == "ERR_DOCUMENTATION_NOT_SUBMITTED"

    def test_documentation_supersede_on_second_approval(self, api):
        """PRD §3.2: "Approval moves the package to `APPROVED` and, in the same
        operation, moves every other `APPROVED` package of the same model to
        `SUPERSEDED`, so at most one approved package exists per model at any time."
        PRD §3.2: "The documentation list for a model can be filtered by `status`."

        Design: Corner/state_machines/documentation_supersede_on_second_approval
        """
        model = create_model(name="Sup M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        d1 = submit_documentation(model["id"], version_label="1.0")
        decide_documentation(model["id"], d1["id"], "APPROVE")
        d2 = submit_documentation(model["id"], version_label="2.0")
        decided = validate_success(
            api.decide_documentation(model["id"], d2["id"], {"decision": "APPROVE"}, OFFICER)
        )
        assert decided["status"] == "APPROVED"

        docs, _ = validate_paginated(api.list_documentations(model["id"], OFFICER))
        by_id = {d["id"]: d for d in docs}
        assert by_id[d1["id"]]["status"] == "SUPERSEDED", "prior APPROVED package must be superseded"

        approved, meta = validate_paginated(
            api.list_documentations(model["id"], OFFICER, params={"status": "APPROVED"})
        )
        assert len(approved) == 1 and approved[0]["id"] == d2["id"], (
            "exactly one APPROVED package per model at any time"
        )
