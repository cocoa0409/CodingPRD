"""Lien recording, negotiation, dispute, and the seven lien_type catalog.

PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_lien,
    create_lien,
    create_lien_payload,
    dispute_lien,
    negotiate_then_reduce_lien,
    patch_lien_payload,
    setup_case_with_fee,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestLienRecording:

    def test_create_lien_returns_asserted_with_nulls(self, api):
        """PRD §3.8: "A newly recorded lien enters ASSERTED with
        negotiated_amount_cents null, final_paid_amount_cents null,
        and priority_rank null."

        Claim: new lien is ASSERTED with the three null fields.
        """
        _, case, _ = setup_case_with_fee()
        lien = create_lien(case["id"], "MEDICARE", 1_500_000)
        assert_lien(lien)
        assert lien["status"] == "ASSERTED"
        assert lien["negotiated_amount_cents"] is None
        assert lien["final_paid_amount_cents"] is None
        assert lien["priority_rank"] is None

    def test_face_amount_zero_rejected(self, api, paralegal_headers):
        """PRD §3.8: "face_amount_cents (strictly greater than zero)".

        Claim: face_amount_cents == 0 → 4xx.
        """
        _, case, _ = setup_case_with_fee()
        bad = create_lien_payload("MEDICARE", 0)
        resp = api.create_lien(case["id"], bad, paralegal_headers)
        assert resp.status_code >= 400


class TestNonStatutoryNegotiation:

    @pytest.mark.parametrize(
        "lien_type",
        ["PROVIDER_NEGOTIATED", "HOSPITAL_STATUTORY",
         "ATTORNEY_PRIOR_COUNSEL"],
    )
    def test_negotiate_opens_negotiating_state(
        self, api, lien_type, paralegal_headers,
    ):
        """PRD §3.8: "Liens of type PROVIDER_NEGOTIATED,
        HOSPITAL_STATUTORY, or ATTORNEY_PRIOR_COUNSEL are negotiable: a
        Paralegal opens negotiation by invoking the negotiate action
        against the lien, which moves it from ASSERTED to
        NEGOTIATING."

        Claim: After POST /negotiate, status == NEGOTIATING.
        """
        _, case, _ = setup_case_with_fee()
        lien = create_lien(case["id"], lien_type, 1_000_000)
        resp = api.negotiate_lien(
            case["id"], lien["id"], paralegal_headers,
        )
        negotiating = validate_success(resp)
        assert negotiating["status"] == "NEGOTIATING"

    def test_patch_negotiated_amount_moves_to_reduced(
        self, api, paralegal_headers,
    ):
        """PRD §3.8: "A subsequent patch supplying negotiated_amount_cents
        (which must be strictly greater than zero and at most
        face_amount_cents; otherwise ERR_LIEN_NEGOTIATION_INVALID)
        moves the lien from NEGOTIATING to REDUCED."

        Claim: After PATCH with valid negotiated_amount,
        status==REDUCED.
        """
        _, case, _ = setup_case_with_fee()
        lien = create_lien(case["id"], "PROVIDER_NEGOTIATED", 1_000_000)
        reduced = negotiate_then_reduce_lien(
            case["id"], lien["id"], 600_000,
        )
        assert reduced["status"] == "REDUCED"
        assert reduced["negotiated_amount_cents"] == 600_000

    def test_negotiated_above_face_rejected(
        self, api, paralegal_headers,
    ):
        """PRD §3.8: "must be strictly greater than zero and at most
        face_amount_cents; otherwise ERR_LIEN_NEGOTIATION_INVALID".

        Claim: negotiated_amount > face → ERR_LIEN_NEGOTIATION_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        lien = create_lien(case["id"], "PROVIDER_NEGOTIATED", 1_000_000)
        api.negotiate_lien(case["id"], lien["id"], paralegal_headers)
        resp = api.patch_lien(
            case["id"], lien["id"],
            patch_lien_payload(negotiated_amount_cents=1_000_001),
            paralegal_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_LIEN_NEGOTIATION_INVALID.value,
        )

    def test_negotiated_zero_rejected(self, api, paralegal_headers):
        """PRD §3.8: "must be strictly greater than zero".

        Claim: negotiated_amount_cents=0 → ERR_LIEN_NEGOTIATION_INVALID.
        """
        _, case, _ = setup_case_with_fee()
        lien = create_lien(case["id"], "PROVIDER_NEGOTIATED", 1_000_000)
        api.negotiate_lien(case["id"], lien["id"], paralegal_headers)
        resp = api.patch_lien(
            case["id"], lien["id"],
            patch_lien_payload(negotiated_amount_cents=0),
            paralegal_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_LIEN_NEGOTIATION_INVALID.value,
        )


class TestDispute:

    def test_attorney_dispute_flips_to_disputed(
        self, api, attorney_headers,
    ):
        """PRD §3.8: "Any lien — statutory or negotiable — may be
        disputed by an Attorney, moving it directly from ASSERTED to
        DISPUTED; a disputed lien is excluded from disbursement
        payment but is still recorded."

        Claim: dispute → status==DISPUTED.
        """
        _, case, _ = setup_case_with_fee()
        lien = create_lien(case["id"], "MEDICARE", 1_500_000)
        disputed = dispute_lien(case["id"], lien["id"])
        assert disputed["status"] == "DISPUTED"

    def test_paralegal_cannot_dispute(
        self, api, paralegal_headers,
    ):
        """PRD §2.1: "If the role is recognized but is not authorized
        for the requested endpoint (per the RBAC implied by §4 and the
        workflow narratives in §3), the request is rejected with
        ERR_FORBIDDEN (HTTP 403)."

        Claim: Paralegal POST /liens/{lid}/dispute → ERR_FORBIDDEN.
        PRD §4 endpoint table restricts the dispute action to Attorney.
        """
        _, case, _ = setup_case_with_fee()
        lien = create_lien(case["id"], "MEDICARE", 1_000_000)
        resp = api.dispute_lien(case["id"], lien["id"], paralegal_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
