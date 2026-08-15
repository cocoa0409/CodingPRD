"""Subscription review pipeline: minimum-commitment boundary, document and
accreditation gates, reject/resubmit cycle, terminal lockdown, versioning."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_subscription,
    make_accreditation_verified_subscription,
    make_active_syndication,
    make_draft_subscription,
    make_investor,
    make_investor_headers,
    make_open_offering,
    make_submitted_subscription,
    setup_funded_offering,
    upload_and_review_documents,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]
OFFICER_1 = TEST_USERS["compliance_officer_headers"]
OFFICER_2 = TEST_USERS["compliance_officer_2_headers"]
REQUIRED_DOCS = ("SUBSCRIPTION_AGREEMENT", "W9", "SUITABILITY_QUESTIONNAIRE")


def _submitted_sub(committed_cents, min_subscription_cents=1_000_000,
                   investor_class="ACCREDITED", accept_types=REQUIRED_DOCS,
                   upload_types=REQUIRED_DOCS):
    """Open offering + investor + SUBMITTED subscription (documents accepted
    per accept_types). Returns (syn, off, inv, sub)."""
    syn = make_active_syndication()
    off = make_open_offering(syn["id"],
                             min_subscription_cents=min_subscription_cents)
    inv = make_investor(investor_class=investor_class)
    sub = make_submitted_subscription(
        off, inv, committed_cents, syn["id"], doc_upload_types=upload_types,
        doc_accept_types=accept_types)
    return syn, off, inv, sub


class TestMinSubscriptionBoundary:
    def test_submit_at_min_subscription_accepted(self, api):
        """PRD §3.3: "Only then is the commitment measured against the floor:
        `committed_cents` at least `min_subscription_cents`, else
        `ERR_BELOW_MIN_SUBSCRIPTION`." A commitment exactly equal to the floor
        satisfies "at least", so the submission succeeds.

        Design: Difficulty/boundary_precision_check/min_subscription_boundary_inclusive
        """
        syn, off, inv, sub = _submitted_sub(1_000_000)
        assert sub["status"] == "SUBMITTED", (
            f"boundary commitment must be accepted, got {sub['status']}")

    def test_submit_below_min_subscription_rejected(self, api):
        """PRD §3.3: "Only then is the commitment measured against the floor:
        `committed_cents` at least `min_subscription_cents`, else
        `ERR_BELOW_MIN_SUBSCRIPTION`." One cent below the floor is rejected.

        Design: Difficulty/boundary_precision_check/min_subscription_boundary_inclusive
        """
        syn = make_active_syndication()
        off = make_open_offering(syn["id"], min_subscription_cents=1_000_000)
        inv = make_investor()
        sub = make_draft_subscription(off, inv, 999_999, syn["id"])
        upload_and_review_documents(syn["id"], off["id"], sub["id"], inv["id"],
                                    upload_types=REQUIRED_DOCS)
        resp = api.submit_subscription(syn["id"], off["id"], sub["id"],
                                       make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_SUBSCRIPTION, 422)
        assert get_subscription(syn["id"], off["id"], sub["id"])["status"] == "DRAFT"

    def test_submit_above_min_subscription_accepted(self, api):
        """PRD §3.3: "Only then is the commitment measured against the floor:
        `committed_cents` at least `min_subscription_cents`, else
        `ERR_BELOW_MIN_SUBSCRIPTION`." One cent above the floor succeeds.

        Design: Difficulty/boundary_precision_check/min_subscription_boundary_inclusive
        """
        syn, off, inv, sub = _submitted_sub(1_000_001)
        assert sub["status"] == "SUBMITTED"


class TestInvalidTransitions:
    def test_submit_twice_rejected_invalid_state(self, api, investor_headers):
        """PRD §3.3: "A clean submission moves the subscription from `DRAFT` to
        `SUBMITTED`." PRD §2.8: "State-transition attempts made against a
        resource that is not in a state from which the requested transition is
        allowed are rejected with `ERR_INVALID_STATE` (HTTP 409)." A second
        submit against a SUBMITTED subscription is such an attempt.

        Design: Corner/state_machines/subscription_submit_twice_rejected_invalid_state
        """
        syn, off, inv, sub = _submitted_sub(5_000_000)
        assert sub["status"] == "SUBMITTED"
        resp = api.submit_subscription(syn["id"], off["id"], sub["id"],
                                       make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_verify_accreditation_on_funded_subscription_rejected(self, api):
        """PRD §3.3 narrates accreditation verification as the step that moves
        a subscription from `SUBMITTED` to `ACCREDITATION_VERIFIED`; PRD §2.8:
        "State-transition attempts made against a resource that is not in a
        state from which the requested transition is allowed are rejected with
        `ERR_INVALID_STATE` (HTTP 409)." A FUNDED subscription is past the
        verification pipeline, so verification is rejected.

        Design: Corner/state_machines/subscription_funded_terminal_cannot_verify_accreditation
        """
        ctx = setup_funded_offering([5_000_000])
        sub = ctx["subs"][0]
        assert sub["status"] == "FUNDED"
        resp = api.verify_accreditation(ctx["syn"]["id"], ctx["off"]["id"],
                                        sub["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestSuitabilityRejectResubmitCycle:
    def test_reject_suitability_clears_verifier(self, api):
        """PRD §3.3: "the compliance desk can move the subscription from
        `ACCREDITATION_VERIFIED` to `SUITABILITY_REJECTED`, which clears
        `accreditation_verified_by` back to null, forcing a fresh accreditation
        verification if the investor tries again."

        Design: Difficulty/non_linear_state_machine/subscription_suitability_reject_resubmit_cycle
        """
        syn = make_active_syndication()
        off = make_open_offering(syn["id"])
        inv = make_investor()
        sub = make_accreditation_verified_subscription(off, inv, 5_000_000,
                                                       syn["id"])
        assert sub["status"] == "ACCREDITATION_VERIFIED"
        assert sub["accreditation_verified_by"] == "test-officer-1"

        rejected = validate_success(api.reject_suitability(
            syn["id"], off["id"], sub["id"], OFFICER_2))
        assert rejected["status"] == "SUITABILITY_REJECTED"
        assert rejected["accreditation_verified_by"] is None, (
            "reject-suitability must clear accreditation_verified_by to null")

    def test_resubmit_reenters_verification_pipeline(self, api):
        """PRD §3.3: "An investor whose subscription was rejected can resubmit
        — provided the offering is still `OPEN` — returning the subscription to
        `SUBMITTED` for another pass through the gauntlet." After resubmission
        a fresh verification moves the subscription to ACCREDITATION_VERIFIED
        again and re-records the verifying officer.

        Design: Difficulty/non_linear_state_machine/subscription_suitability_reject_resubmit_cycle
        """
        syn = make_active_syndication()
        off = make_open_offering(syn["id"])
        inv = make_investor()
        sub = make_accreditation_verified_subscription(off, inv, 5_000_000,
                                                       syn["id"])
        validate_success(api.reject_suitability(syn["id"], off["id"], sub["id"],
                                                OFFICER_2))
        resubmitted = validate_success(api.resubmit_subscription(
            syn["id"], off["id"], sub["id"], make_investor_headers(inv["id"])))
        assert resubmitted["status"] == "SUBMITTED"

        reverified = validate_success(api.verify_accreditation(
            syn["id"], off["id"], sub["id"], OFFICER_1))
        assert reverified["status"] == "ACCREDITATION_VERIFIED"
        assert reverified["accreditation_verified_by"] == "test-officer-1"


class TestAccreditationGateOrdering:
    def test_verify_accreditation_doc_missing_precedes_class_check(self, api):
        """PRD §3.3: "Three conditions must all hold, and the desk sees them
        surface in this order: the self-verification guard first, then the
        documentary requirement — an `ACCEPTED` document of type
        `ACCREDITATION_LETTER` must exist on the subscription, else
        `ERR_ACCREDITATION_DOC_MISSING` — and finally the investor-class rule,
        under which a commitment of 100000 dollars or more (that is,
        `committed_cents` of at least 10000000 cents) requires the investor to
        be `ACCREDITED` or `QUALIFIED_PURCHASER`, with anything less rejected
        as `ERR_INVESTOR_CLASS_INSUFFICIENT`." With the accreditation letter
        not yet ACCEPTED and the class rule also violated by a NON_ACCREDITED
        investor committing $200,000, the documentary requirement surfaces
        first.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_submit
        """
        syn, off, inv, sub = _submitted_sub(
            20_000_000, investor_class="NON_ACCREDITED",
            upload_types=REQUIRED_DOCS + ("ACCREDITATION_LETTER",),
            accept_types=REQUIRED_DOCS)
        resp = api.verify_accreditation(syn["id"], off["id"], sub["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_ACCREDITATION_DOC_MISSING, 422)

    def test_verify_accreditation_class_insufficient_after_doc_accepted(self, api):
        """PRD §3.3: "finally the investor-class rule, under which a commitment
        of 100000 dollars or more (that is, `committed_cents` of at least
        10000000 cents) requires the investor to be `ACCREDITED` or
        `QUALIFIED_PURCHASER`, with anything less rejected as
        `ERR_INVESTOR_CLASS_INSUFFICIENT`." Once an ACCEPTED accreditation
        letter exists, the class rule surfaces for a NON_ACCREDITED investor
        committing $200,000.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_submit
        """
        syn, off, inv, sub = _submitted_sub(
            20_000_000, investor_class="NON_ACCREDITED",
            upload_types=REQUIRED_DOCS + ("ACCREDITATION_LETTER",),
            accept_types=REQUIRED_DOCS + ("ACCREDITATION_LETTER",))
        resp = api.verify_accreditation(syn["id"], off["id"], sub["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_INVESTOR_CLASS_INSUFFICIENT, 422)


class TestSubscriptionVersioning:
    def test_subscription_version_increments_per_transition(
            self, api, sponsor_operator_headers):
        """PRD §2.4: "an integer `version` that increments by one on every
        mutation of that resource." PRD §4: "Every state-transition endpoint
        increments the affected resource's `version` by one unless otherwise
        noted." PRD §3.3: approval "chains the subscription straight through
        `SUITABILITY_APPROVED` into `AWAITING_FUNDING` within the same
        request".

        Design: Corner/cross_cutting_layers/occ_subscription_version_increments_on_transition
        """
        syn = make_active_syndication()
        off = make_open_offering(syn["id"])
        inv = make_investor()
        sub = make_draft_subscription(off, inv, 5_000_000, syn["id"])
        upload_and_review_documents(syn["id"], off["id"], sub["id"], inv["id"])
        v0 = sub["version"]

        submitted = validate_success(api.submit_subscription(
            syn["id"], off["id"], sub["id"], make_investor_headers(inv["id"])))
        assert submitted["version"] == v0 + 1, (
            f"submit must increment version by 1: {v0} -> {submitted['version']}")
        assert submitted["status"] == "SUBMITTED"

        verified = validate_success(api.verify_accreditation(
            syn["id"], off["id"], sub["id"], OFFICER_1))
        assert verified["version"] == v0 + 2, (
            f"verify-accreditation must increment version by 1: "
            f"{v0 + 1} -> {verified['version']}")
        assert verified["status"] == "ACCREDITATION_VERIFIED"

        approved = validate_success(api.approve_suitability(
            syn["id"], off["id"], sub["id"], OFFICER_2))
        assert approved["version"] == v0 + 3, (
            f"approve-suitability must increment version by 1: "
            f"{v0 + 2} -> {approved['version']}")
        assert approved["status"] == "AWAITING_FUNDING"
