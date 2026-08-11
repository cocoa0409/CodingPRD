"""Immediate consistency and one-agreement-per-client invariant."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box,
    get_box,
    make_intake_clerk_headers, make_platform_admin_headers,
    CLERK, ADMIN,
)


class TestImmediateConsistencyMutationVisibleInNextRead:
    """Corner: immediate_consistency_mutation_visible_in_next_read."""

    def test_create_response_and_immediate_read_agree_version_bump_visible(self, api):
        """PRD §2.4: "`version`, an integer that increments by exactly 1 on
        every mutation of the resource." PRD §3.4: "Each of these transitions,
        like every batch transition, increments the batch's `version` by 1."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_next_read
        """
        client, _ = create_client_with_agreement(name="Imm Co", hipaa_covered=False)
        batch = create_batch(client["id"])
        # Create box -> visible in the next GET with status RECEIVED.
        box_resp = api_client.create_box(
            batch["id"], {"box_label": "BX-1", "intake_weight_grams": 600},
            make_intake_clerk_headers(CLERK),
        )
        box = validate_success(box_resp, expected_status=201)
        assert box["status"] == "RECEIVED"
        box_read = get_box(box["id"])
        assert box_read["status"] == "RECEIVED"

        # start-prep increments version; immediate read confirms.
        prep_resp = api_client.start_prep(batch["id"], make_intake_clerk_headers(CLERK))
        prep_data = validate_success(prep_resp, expected_status=200)
        assert prep_data["version"] == 2
        after = get_success_data(api_client.get_batch(batch["id"], make_intake_clerk_headers(CLERK)))
        assert after["version"] == 2
        assert after["status"] == "PREPPING"


class TestErrorSecondAgreementRejected:
    """Corner: error_second_agreement_rejected."""

    def test_second_agreement_rejected(self, api):
        """PRD §3.1: "Attempting to create a second agreement for a client
        that already has one is rejected with `ERR_AGREEMENT_EXISTS`
        (HTTP 409)."

        Design: Corner/errors/error_second_agreement_rejected
        """
        client, _ = create_client_with_agreement(name="Ag Co", hipaa_covered=False)
        resp = api_client.create_service_agreement(
            client["id"],
            {
                "price_tier": "VOLUME",
                "rush_multiplier": 2.0,
                "storage_free_days": 5,
                "storage_daily_rate_cents": 40,
                "retention_days": 15,
                "max_boxes_per_batch": 10,
            },
            make_platform_admin_headers(ADMIN),
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXISTS, expected_status=409)
        # Still exactly one agreement, still STANDARD.
        from test_helpers import validate_paginated
        agreements, meta = validate_paginated(api_client.list_service_agreements(
            client["id"], make_platform_admin_headers(ADMIN),
        ))
        assert meta["total_count"] == 1
        assert agreements[0]["price_tier"] == "STANDARD"
