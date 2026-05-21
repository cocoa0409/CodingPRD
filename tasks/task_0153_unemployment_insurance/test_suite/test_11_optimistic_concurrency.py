"""Optimistic concurrency control — PRD §2.5.

Tests that supplying a stale `version` on action endpoints yields
ERR_VERSION_CONFLICT and that omitting `version` skips the check.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate_claim_payload,
    create_claim,
    create_claimant,
    create_employer,
    repay_overpayment_payload,
    make_adjudicator_headers,
    make_claimant_headers,
    setup_outstanding_overpayment,
    stage_eligible_wages,
    submit_claim,
    validate_error,
    validate_success,
)


class TestVersionConflict:

    def test_stale_version_on_adjudicate_rejected(self, api):
        """PRD §2.5: "When the client supplies version, the server
        compares it against the current version of the targeted
        resource; a mismatch is rejected with ERR_VERSION_CONFLICT."
        """
        cm = create_claimant()
        emp = create_employer()
        stage_eligible_wages(cm["id"], emp["id"])
        claim = create_claim(cm)
        claim = submit_claim(claim, cm["id"])
        # Supply a stale-but-valid version. PRD §2.4: "The version is a
        # non-negative integer that starts at 1 on creation". A negative
        # value would surface as ERR_VALIDATION_FAILED (a body-shape
        # error per §2.10); to isolate the OCC check we pick a
        # non-negative value that cannot match the current version.
        assert claim["version"] >= 1
        stale_v = 0  # valid non-negative, but < claim.version after submit
        assert stale_v != claim["version"]
        resp = api.adjudicate_claim(
            claim["id"],
            adjudicate_claim_payload("ELIGIBLE", version=stale_v),
            make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_matching_version_accepted(self, api):
        """PRD §2.5: "When the client supplies version, the server
        compares it against the current version of the targeted
        resource."

        Supplying the correct version proceeds.
        """
        cm = create_claimant()
        emp = create_employer()
        stage_eligible_wages(cm["id"], emp["id"])
        claim = create_claim(cm)
        claim = submit_claim(claim, cm["id"])
        resp = api.adjudicate_claim(
            claim["id"],
            adjudicate_claim_payload("ELIGIBLE", version=claim["version"]),
            make_adjudicator_headers(),
        )
        validate_success(resp)

    def test_omitted_version_skips_occ_check(self, api):
        """PRD §2.5: "Omitting the field skips the check, and the
        operation proceeds against whatever the current version happens
        to be."
        """
        cm = create_claimant()
        emp = create_employer()
        stage_eligible_wages(cm["id"], emp["id"])
        claim = create_claim(cm)
        claim = submit_claim(claim, cm["id"])
        # Omit version entirely.
        resp = api.adjudicate_claim(
            claim["id"],
            adjudicate_claim_payload("ELIGIBLE"),  # no version key
            make_adjudicator_headers(),
        )
        validate_success(resp)

    def test_stale_version_on_repay_rejected(self, api):
        """PRD §2.5: "Action endpoints that mutate a resource (notably
        claim adjudication, claim extension, certification audit,
        overpayment repayment, overpayment waiver and write-off, and
        appeal decision) accept an optional version field in their
        request body."
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        cm = bundle["claimant"]
        # Supply a stale-but-valid version. PRD §2.4: version is a
        # non-negative integer starting at 1; a negative value would
        # trip ERR_VALIDATION_FAILED (body-shape, §2.10) before the OCC
        # check could run. Pick a non-negative value != op.version.
        assert op["version"] >= 1
        stale_v = 0
        assert stale_v != op["version"]
        resp = api.repay_overpayment(
            op["id"],
            repay_overpayment_payload(
                amount_cents=1, version=stale_v,
            ),
            make_claimant_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)
