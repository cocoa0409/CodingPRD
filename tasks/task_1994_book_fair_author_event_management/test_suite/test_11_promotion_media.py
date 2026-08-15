"""Media blasts: embargo gate, promo budget gate, revision loop."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_media_blast_payload,
    make_school,
    make_fair,
    make_school_coordinator_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]


class TestEmbargo:
    def test_embargo_blocks_publish_until_lifted(self, api):
        """PRD §3.9: "Publishing an `APPROVED` blast is the organizer's move and
        is embargo-gated: the logical clock must have reached `embargo_until`,
        otherwise `ERR_EMBARGO_ACTIVE` (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/embargo_blocks_publish_until_lifted
        """
        school = make_school()
        fair = make_fair(school["id"], promo_budget_cents=500)
        blast = validate_success(api.create_media_blast(
            create_media_blast_payload(
                fair_id=fair["id"], spend_cents=300,
                embargo_until="2026-08-05T00:00:00Z",
                content_summary="Weekend feature piece",
            ), ORG,
        ), expected_status=201)
        validate_success(api.submit_media_blast(blast["id"], ORG))
        validate_success(api.approve_media_blast(
            blast["id"], make_school_coordinator_headers(school["id"])
        ))
        # Default clock 2026-08-01 is before embargo 2026-08-05
        resp = api.publish_media_blast(blast["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)
        # At exactly embargo_until the publish succeeds (>= semantics)
        validate_success(api.set_clock({"to_iso8601": "2026-08-05T00:00:00Z"}, ORG))
        ok = validate_success(api.publish_media_blast(blast["id"], ORG))
        assert ok["status"] == "PUBLISHED"

    def test_embargo_boundary_one_second_before(self, api):
        """PRD §3.9: "the logical clock must have reached `embargo_until`,
        otherwise `ERR_EMBARGO_ACTIVE` (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/embargo_blocks_publish_until_lifted
        """
        school = make_school()
        fair = make_fair(school["id"], promo_budget_cents=500)
        blast = validate_success(api.create_media_blast(
            create_media_blast_payload(
                fair_id=fair["id"], spend_cents=300,
                embargo_until="2026-08-05T00:00:00Z",
            ), ORG,
        ), expected_status=201)
        validate_success(api.submit_media_blast(blast["id"], ORG))
        validate_success(api.approve_media_blast(
            blast["id"], make_school_coordinator_headers(school["id"])
        ))
        validate_success(api.set_clock({"to_iso8601": "2026-08-04T23:59:59Z"}, ORG))
        resp = api.publish_media_blast(blast["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)


class TestPromoBudget:
    def test_promo_budget_cumulative_gate(self, api):
        """PRD §3.9: "approval is the fiscal gate where the budget bites: the
        sum of `spend_cents` over the fair's blasts already `APPROVED` or
        `PUBLISHED`, plus the candidate's own `spend_cents`, must stay within
        the fair's `promo_budget_cents` (`ERR_PROMO_BUDGET_EXCEEDED`, HTTP
        409)."

        Design: Corner/cross_cutting_complexity_layers/promo_budget_cumulative_gate
        """
        school = make_school()
        fair = make_fair(school["id"], promo_budget_cents=500)
        blast_a = validate_success(api.create_media_blast(
            create_media_blast_payload(fair_id=fair["id"], spend_cents=300,
                                       content_summary="Feature piece"), ORG,
        ), expected_status=201)
        validate_success(api.submit_media_blast(blast_a["id"], ORG))
        validate_success(api.approve_media_blast(
            blast_a["id"], make_school_coordinator_headers(school["id"])
        ))

        blast_b = validate_success(api.create_media_blast(
            create_media_blast_payload(fair_id=fair["id"], channel="RADIO",
                                       spend_cents=300,
                                       embargo_until="2026-08-06T00:00:00Z",
                                       content_summary="Morning radio spot"), ORG,
        ), expected_status=201)
        validate_success(api.submit_media_blast(blast_b["id"], ORG))

        blast_c = validate_success(api.create_media_blast(
            create_media_blast_payload(fair_id=fair["id"], channel="SOCIAL",
                                       spend_cents=200,
                                       embargo_until="2026-08-07T00:00:00Z",
                                       content_summary="Social countdown"), ORG,
        ), expected_status=201)
        validate_success(api.submit_media_blast(blast_c["id"], ORG))

        # 300 + 300 = 600 > 500 — rejected
        resp_b = api.approve_media_blast(
            blast_b["id"], make_school_coordinator_headers(school["id"])
        )
        validate_error(resp_b, ApiErrorId.ERR_PROMO_BUDGET_EXCEEDED)
        after_b = validate_success(api.get_media_blast(blast_b["id"], ORG))
        assert after_b["status"] == "PENDING_APPROVAL"

        # 300 + 200 = 500 <= 500 — exact boundary succeeds
        ok_c = validate_success(api.approve_media_blast(
            blast_c["id"], make_school_coordinator_headers(school["id"])
        ))
        assert ok_c["status"] == "APPROVED"
        after_a = validate_success(api.get_media_blast(blast_a["id"], ORG))
        assert after_a["status"] == "APPROVED"

    def test_promo_budget_rejected_blast_does_not_count(self, api):
        """PRD §3.9: "the sum of `spend_cents` over the fair's blasts already
        `APPROVED` or `PUBLISHED`, plus the candidate's own `spend_cents`, must
        stay within the fair's `promo_budget_cents` (`ERR_PROMO_BUDGET_EXCEEDED`,
        HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/promo_budget_cumulative_gate
        """
        school = make_school()
        fair = make_fair(school["id"], promo_budget_cents=500)
        blast_a = validate_success(api.create_media_blast(
            create_media_blast_payload(fair_id=fair["id"], spend_cents=400), ORG,
        ), expected_status=201)
        validate_success(api.submit_media_blast(blast_a["id"], ORG))
        # Reject blast A; its spend must not count
        validate_success(api.reject_media_blast(
            blast_a["id"], make_school_coordinator_headers(school["id"])
        ))
        blast_b = validate_success(api.create_media_blast(
            create_media_blast_payload(fair_id=fair["id"], channel="RADIO", spend_cents=500,
                                       embargo_until="2026-08-06T00:00:00Z"), ORG,
        ), expected_status=201)
        validate_success(api.submit_media_blast(blast_b["id"], ORG))
        ok = validate_success(api.approve_media_blast(
            blast_b["id"], make_school_coordinator_headers(school["id"])
        ))
        assert ok["status"] == "APPROVED"
