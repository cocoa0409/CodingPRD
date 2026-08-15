"""Commission disclosure lifecycle: threshold, disclose, acknowledge."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    setup_approved_case,
    make_broker_headers,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestDisclosureThreshold:
    def test_disclose_when_not_required_fails(self):
        """PRD section 3.9: "if `requires_disclosure` is false, the disclose
        attempt is refused with `ERR_DISCLOSURE_NOT_REQUIRED`".
        PRD section 3.5: "when the per-enrollee commission reaches or exceeds
        5,000 cents — the $50-per-enrollee-per-year disclosure threshold —
        `commission_disclosure_required` is set true."

        Design: Corner/validations/disclose_when_not_required_fails
        """
        # commission_pct 0.01 -> total 256224 cents, per-enrollee 640.56 < 5000.
        broker, case, plan, quote, disc = setup_approved_case(commission_pct=0.01)
        assert disc["requires_disclosure"] is False
        resp = api_client.disclose_commission(disc["id"], UW)
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_REQUIRED)
        disc = get_success_data(
            api_client.get_commission_disclosure(disc["id"], UW)
        )
        assert disc["status"] == "PENDING"


class TestDisclosureFlow:
    def test_disclose_and_acknowledge_flow(self):
        """PRD section 3.9: "if the disclosure is not `PENDING` the attempt fails
        with `ERR_DISCLOSURE_NOT_PENDING`. Successful disclosure moves the record
        to `DISCLOSED` and stamps `disclosed_at` with the current timestamp. The
        broker of record then acknowledges receipt, moving the disclosure from
        `DISCLOSED` (else `ERR_DISCLOSURE_NOT_DISCLOSED`) to the terminal
        `ACKNOWLEDGED` state".
        PRD section 3.6: "The disclosure computes `total_commission_cents`
        (the accepted quote's annual broker commission), the effective
        `commission_pct`, the `per_enrollee_cents` figure, and compares the
        total against the system-held `disclosure_threshold_cents` — $50 per
        enrollee per year, i.e. 5,000 cents per enrollee — setting
        `requires_disclosure` true when the per-enrollee commission meets or
        exceeds that threshold."

        Design: Corner/validations/disclose_and_acknowledge_flow
        """
        # commission_pct 0.10 -> total 2562240 cents, per-enrollee 6405.6 >= 5000.
        broker, case, plan, quote, disc = setup_approved_case(commission_pct=0.10)
        assert disc["requires_disclosure"] is True
        assert disc["total_commission_cents"] == 2562240
        broker_headers = make_broker_headers(broker["id"])

        # Acknowledge before disclose fails.
        resp = api_client.acknowledge_disclosure(disc["id"], broker_headers)
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_DISCLOSED)

        # Disclose succeeds and stamps disclosed_at.
        data = validate_success(api_client.disclose_commission(disc["id"], UW))
        assert data["status"] == "DISCLOSED"
        assert data.get("disclosed_at") is not None

        # A second disclose fails: no longer PENDING.
        resp = api_client.disclose_commission(disc["id"], UW)
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_PENDING)

        # Acknowledge lands the terminal state.
        data = validate_success(
            api_client.acknowledge_disclosure(disc["id"], broker_headers)
        )
        assert data["status"] == "ACKNOWLEDGED"
