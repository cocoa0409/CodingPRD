"""Sourcing-request lifecycle, the sample review/resubmit cycle with its
revision cap, and cancellation cascade to child samples and quotations."""
from test_helpers import (
    ApiErrorId,
    create_agent,
    create_buyer,
    create_quotation,
    create_sample,
    create_sourcing_request,
    get_sample,
    get_sourcing_request,
    make_buyer_manager_headers,
    make_grade_a_factory,
    make_sourcing_agent_headers,
    resubmit_sample,
    review_sample,
    validate_error,
    validate_success,
)


def _sr_with_sample():
    """Buyer + agent + OPEN sourcing request + one SUBMITTED sample."""
    buyer = create_buyer()
    agent = create_agent()
    sr = create_sourcing_request(buyer["id"], agent["id"], title="Samples")
    sample = create_sample(sr["id"], agent["id"], notes="v0")
    return buyer, agent, sr, sample


class TestSampleCreation:
    def test_sample_creation_initial_state(self, api):
        """PRD: "The agent submits samples with free-text `notes`; a fresh sample has `revision_count` 0 and status `SUBMITTED`."
        PRD: "The first `Sample` or `Quotation` created under the request flips it from `OPEN` to `IN_PROGRESS`; this transition is system-driven and needs no explicit call."

        Design: Corner/entities/sample_creation_initial_state
        """
        buyer = create_buyer()
        agent = create_agent()
        sr = create_sourcing_request(buyer["id"], agent["id"], title="S")
        assert sr["status"] == "OPEN"
        sample = create_sample(sr["id"], agent["id"], notes="first")
        assert sample["status"] == "SUBMITTED"
        assert sample["revision_count"] == 0
        sr_after = get_sourcing_request(sr["id"])
        assert sr_after["status"] == "IN_PROGRESS"


class TestSampleReviewCycle:
    def test_sample_approve_from_submitted_valid_transition(self, api):
        """PRD: "Review requires the sample to be `SUBMITTED` (`ERR_SAMPLE_NOT_REVIEWABLE` otherwise), the caller to own the parent sourcing request, and the request itself to be `OPEN` or `IN_PROGRESS` (`ERR_SR_NOT_ACTIVE` otherwise)."
        PRD: "Approval moves the sample to `APPROVED`."

        Design: Corner/state_machines/sample_approve_from_submitted_valid_transition
        """
        buyer, agent, sr, sample = _sr_with_sample()
        approved = review_sample(sample["id"], buyer["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        validate_error(
            api.review_sample(
                sample["id"], {"decision": "APPROVE"},
                make_buyer_manager_headers(buyer["id"]),
            ),
            ApiErrorId.ERR_SAMPLE_NOT_REVIEWABLE,
        )

    def test_sample_resubmit_from_submitted_rejected(self, api):
        """PRD: "The agent resubmits a `REVISION_REQUESTED` sample with fresh `notes`, which increments `revision_count` by 1 and returns the sample to `SUBMITTED`; resubmission requires the sample to be `REVISION_REQUESTED` (`ERR_SAMPLE_NOT_RESUBMITTABLE` otherwise) and the caller to be the request's `assigned_agent_id`."

        Design: Corner/state_machines/sample_resubmit_from_submitted_rejected
        """
        buyer, agent, sr, sample = _sr_with_sample()
        validate_error(
            api.resubmit_sample(
                sample["id"], {"notes": "premature"},
                make_sourcing_agent_headers(agent["id"]),
            ),
            ApiErrorId.ERR_SAMPLE_NOT_RESUBMITTABLE,
        )
        after = get_sample(sample["id"])
        assert after["status"] == "SUBMITTED"
        assert after["revision_count"] == 0

    def test_sample_revision_cycle_three_resubmits(self, api):
        """PRD: "Requesting a revision moves the sample to `REVISION_REQUESTED` — unless the sample's `revision_count` has already reached the revision cap of 3, in which case the review call still succeeds with HTTP 200 but the sample body shows status `REJECTED`; the 4th revision request is refused and the sample is terminally rejected."
        PRD: "The agent resubmits a `REVISION_REQUESTED` sample with fresh `notes`, which increments `revision_count` by 1 and returns the sample to `SUBMITTED`"
        Three full request/resubmit cycles succeed, landing revision_count at 3.

        Design: Difficulty/non_linear_state_machine/sample_revision_cycle_loops_until_cap
        """
        buyer, agent, sr, sample = _sr_with_sample()
        for expected_count in (1, 2, 3):
            revised = review_sample(sample["id"], buyer["id"], "REQUEST_REVISION")
            assert revised["status"] == "REVISION_REQUESTED"
            resubmitted = resubmit_sample(
                sample["id"], agent["id"], notes=f"v{expected_count}"
            )
            assert resubmitted["status"] == "SUBMITTED"
            assert resubmitted["revision_count"] == expected_count

    def test_sample_fourth_revision_request_rejects_terminally(self, api):
        """PRD: "Requesting a revision moves the sample to `REVISION_REQUESTED` — unless the sample's `revision_count` has already reached the revision cap of 3, in which case the review call still succeeds with HTTP 200 but the sample body shows status `REJECTED`; the 4th revision request is refused and the sample is terminally rejected."

        Design: Difficulty/non_linear_state_machine/sample_revision_cycle_loops_until_cap
        """
        buyer, agent, sr, sample = _sr_with_sample()
        for i in (1, 2, 3):
            review_sample(sample["id"], buyer["id"], "REQUEST_REVISION")
            resubmit_sample(sample["id"], agent["id"], notes=f"v{i}")
        resp = api.review_sample(
            sample["id"], {"decision": "REQUEST_REVISION"},
            make_buyer_manager_headers(buyer["id"]),
        )
        final = validate_success(resp, expected_status=200)
        assert final["revision_count"] == 3
        assert final["status"] == "REJECTED"


class TestSourcingRequestCancel:
    def test_sr_cancel_cascades_to_samples_and_quotations(self, api):
        """PRD: "The buyer may cancel a request while it is `OPEN` or `IN_PROGRESS` — anything else is rejected with `ERR_SR_NOT_CANCELLABLE`."
        PRD: "Cancelling cascades: every non-terminal `Sample` (statuses `SUBMITTED`, `REVISION_REQUESTED`) flips to `REJECTED`, and every non-terminal `Quotation` (statuses `OPEN`, `COUNTERED`) flips to `REJECTED`."

        Design: Corner/state_machines/sr_cancel_cascades_to_samples_and_quotations
        """
        buyer = create_buyer()
        agent = create_agent()
        factory = make_grade_a_factory(agent["id"])
        sr = create_sourcing_request(buyer["id"], agent["id"], title="C")
        sample = create_sample(sr["id"], agent["id"], notes="x")
        quotation = create_quotation(sr["id"], factory["id"])

        cancelled = validate_success(
            api.cancel_sourcing_request(
                sr["id"], make_buyer_manager_headers(buyer["id"])
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_sample(sample["id"])["status"] == "REJECTED"
        assert api.get_quotation(quotation["id"], make_buyer_manager_headers(buyer["id"])) \
            .json()["data"]["status"] == "REJECTED"


class TestSampleAuthorization:
    def test_ownership_scope_buyer_cannot_touch_other_buyers_sr(self, api):
        """PRD: "Ownership scoping (`BuyerManager` checks `buyer_id`, `SourcingAgent` checks `assigned_agent_id`, `FactoryRep` checks `factory_id`, `Inspector` checks `inspector_id`) is enforced on every role-scoped write endpoint. A violation is rejected with `ERR_OWNERSHIP_SCOPE_VIOLATION` (HTTP 403)."
        PRD: "Review requires the sample to be `SUBMITTED` (`ERR_SAMPLE_NOT_REVIEWABLE` otherwise), the caller to own the parent sourcing request, and the request itself to be `OPEN` or `IN_PROGRESS` (`ERR_SR_NOT_ACTIVE` otherwise)."

        Design: Corner/validations/ownership_scope_buyer_cannot_touch_other_buyers_sr
        """
        buyer, agent, sr, sample = _sr_with_sample()
        other_buyer = create_buyer("Buyer Two")
        validate_error(
            api.review_sample(
                sample["id"], {"decision": "APPROVE"},
                make_buyer_manager_headers(other_buyer["id"]),
            ),
            ApiErrorId.ERR_OWNERSHIP_SCOPE_VIOLATION,
        )
        assert get_sample(sample["id"])["status"] == "SUBMITTED"

    def test_rbac_agent_cannot_review_sample(self, api):
        """PRD: "If the role named in `X-User-Role` is not in the endpoint's permitted role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD endpoint table: "Buyer reviews a SUBMITTED sample: APPROVE or REQUEST_REVISION (4th revision request auto-rejects) | BuyerManager".

        Design: Corner/roles/rbac_agent_cannot_review_sample
        """
        buyer, agent, sr, sample = _sr_with_sample()
        validate_error(
            api.review_sample(
                sample["id"], {"decision": "APPROVE"},
                make_sourcing_agent_headers(agent["id"]),
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
