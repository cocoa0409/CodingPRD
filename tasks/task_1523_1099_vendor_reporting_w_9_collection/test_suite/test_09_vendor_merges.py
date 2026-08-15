"""Duplicate-vendor merge approval: re-parenting cascades, return invalidation,
key-collision voiding, and B-notice / balance inheritance."""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    IRS,
    SPEC,
    ApiErrorId,
    approve_merge,
    create_b_notice,
    create_matched_vendor,
    create_mismatched_vendor,
    create_merge_request,
    create_payment,
    create_tax_year,
    generate_returns,
    get_single_return,
    get_vendor,
    make_tax_admin_headers,
    record_match,
    submit_w9,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMergeCascade:
    def test_merge_approve_reparents_and_invalidates_returns(self, api):
        """PRD §3.9: "Its payments are re-parented to the target — `vendor_id`
        rewritten, while `tax_year`, `is_reportable`, and `reportable_box` stay as
        frozen at posting."
        PRD §3.9: "Its returns are re-parented as well — except that a source return
        in `DRAFT` or `VALIDATED` whose year-and-form key collides with an existing
        non-terminal target return is `VOIDED` instead of re-parented, and the
        target's own surviving `DRAFT` or `VALIDATED` returns are invalidated back to
        `DRAFT` with their box amounts recomputed."
        PRD §3.9: "The source vendor becomes `MERGED` with `merged_into_vendor_id`
        pointing at the target."

        Design: Difficulty/transitive_cascade/merge_approve_reparents_and_invalidates_returns
        """
        create_tax_year()
        source, _ws = create_matched_vendor(legal_name="Dup S", tin="123456789")
        # Below the NEC threshold alone: no return is generated for the source.
        create_payment(source["id"], amount_cents=50000, payment_date="2025-04-01T00:00:00Z",
                       source_system="CORP_CARD")
        target, _wg = create_matched_vendor(legal_name="Dup G", tin="123456789")
        create_payment(target["id"], amount_cents=100000, payment_date="2025-05-01T00:00:00Z")
        generate_returns(2025)
        target_return = get_single_return(target["id"], tax_year=2025)
        assert target_return["box_amounts"]["box_1_cents"] == 100000
        validate_success(api.validate_return(target_return["id"], SPEC), 200)

        merge_request = create_merge_request(source["id"], target["id"], requester_id="clerk-1")
        approved = validate_success(
            api.approve_merge_request(merge_request["id"], make_tax_admin_headers("admin-1")),
            200,
        )
        assert approved["status"] == "EXECUTED"

        merged_source = get_vendor(source["id"], ADMIN)
        assert merged_source["status"] == "MERGED"
        assert merged_source["merged_into_vendor_id"] == target["id"]

        # Source payments now ride on the target.
        payments, meta = validate_paginated(
            api.list_payments(ADMIN, params={"vendor_id": target["id"]})
        )
        assert meta["total_count"] == 2
        assert all(p["vendor_id"] == target["id"] for p in payments)

        # The target's VALIDATED return is invalidated to DRAFT and recomputed on
        # the final basis over the combined (re-parented) ledger.
        target_return_after = validate_success(api.get_return(target_return["id"], ADMIN), 200)
        assert target_return_after["federal_status"] == "DRAFT"
        assert target_return_after["box_amounts"]["box_1_cents"] == 150000
        assert target_return_after["amount_basis"] == "FINAL"

    def test_merge_key_collision_voids_source_return(self, api):
        """PRD §3.9: "Its returns are re-parented as well — except that a source
        return in `DRAFT` or `VALIDATED` whose year-and-form key collides with an
        existing non-terminal target return is `VOIDED` instead of re-parented, and
        the target's own surviving `DRAFT` or `VALIDATED` returns are invalidated
        back to `DRAFT` with their box amounts recomputed."

        Design: Difficulty/transitive_cascade/merge_approve_reparents_and_invalidates_returns
        """
        create_tax_year()
        source, _ws = create_matched_vendor(legal_name="DupS2", tin="123456789")
        create_payment(source["id"], amount_cents=70000, payment_date="2025-04-01T00:00:00Z")
        target, _wg = create_matched_vendor(legal_name="DupG2", tin="123456789")
        create_payment(target["id"], amount_cents=100000, payment_date="2025-05-01T00:00:00Z")
        generate_returns(2025)

        # Both vendors now hold a non-terminal NEC return for 2025: a key collision.
        source_return = get_single_return(source["id"], tax_year=2025)
        target_return = get_single_return(target["id"], tax_year=2025)
        assert source_return["federal_status"] == "DRAFT"
        assert target_return["federal_status"] == "DRAFT"

        merge_request = create_merge_request(source["id"], target["id"], requester_id="clerk-1")
        validate_success(
            api.approve_merge_request(merge_request["id"], make_tax_admin_headers("admin-1")),
            200,
        )

        source_return_after = validate_success(api.get_return(source_return["id"], ADMIN), 200)
        assert source_return_after["federal_status"] == "VOIDED"

        target_return_after = validate_success(api.get_return(target_return["id"], ADMIN), 200)
        assert target_return_after["federal_status"] == "DRAFT"
        # Recomputed over the combined POSTED set: 100000 + 70000.
        assert target_return_after["box_amounts"]["box_1_cents"] == 170000

    def test_cascade_merge_reparents_bnotices_and_balance(self, api):
        """PRD §3.9: "Its withholding entries move to the target, whose
        `withholding_balance_cents` is recomputed as the combined sum. Its B-notices
        move, and the target's `b_notice_stage` becomes the higher of the two
        vendors' stages under the `NONE`-then-`FIRST`-then-`SECOND` ordering."

        Design: Corner/cross_cutting_layers/c_cascade_merge_reparents_bnotices_and_balance
        """
        create_tax_year()
        # Source: first W-9 MATCHED, second W-9 MISMATCHED (flag on), then a
        # withheld payment and a FIRST B-notice (mismatch count 1, no prior notice).
        source = validate_success(
            api.create_vendor(
                {
                    "legal_name": "Mrg S",
                    "entity_classification": "INDIVIDUAL_SOLE_PROP",
                    "address_line1": "12 X",
                    "address_city": "Boerne",
                    "address_state": "TX",
                    "address_postal": "78006",
                },
                CLERK,
            ),
            201,
        )
        w1 = submit_w9(source["id"], submitted_tin="123456789", signature_name="S")
        record_match(w1["id"], "MATCHED")
        w2 = submit_w9(source["id"], submitted_tin="123456789", signature_name="S2")
        record_match(w2["id"], "MISMATCHED", mismatch_reason_code="IRS_CODE_1")
        create_payment(source["id"], amount_cents=100000, payment_date="2025-06-01T00:00:00Z")
        source_notice = create_b_notice(source["id"], notice_year=2025)
        assert source_notice["stage"] == "FIRST"
        assert get_vendor(source["id"])["withholding_balance_cents"] == 24000

        target, _wg = create_matched_vendor(legal_name="Mrg G", tin="123456789")
        create_payment(target["id"], amount_cents=50000, payment_date="2025-06-02T00:00:00Z")

        merge_request = create_merge_request(
            source["id"], target["id"], reason="duplicate account", requester_id="clerk-1"
        )
        validate_success(
            api.approve_merge_request(merge_request["id"], make_tax_admin_headers("admin-1")),
            200,
        )

        target_after = get_vendor(target["id"], ADMIN)
        # The target inherits the source's UNREMITTED balance...
        assert target_after["withholding_balance_cents"] == 24000
        # ...and the higher of the two B-notice stages (max of NONE and FIRST).
        assert target_after["b_notice_stage"] == "FIRST"

        entries, entries_meta = validate_paginated(
            api.list_withholding_entries(ADMIN, params={"vendor_id": target["id"]})
        )
        assert entries_meta["total_count"] == 1
        assert entries[0]["amount_cents"] == 24000

        notices, notices_meta = validate_paginated(
            api.list_b_notices(ADMIN, params={"vendor_id": target["id"]})
        )
        assert notices_meta["total_count"] == 1
