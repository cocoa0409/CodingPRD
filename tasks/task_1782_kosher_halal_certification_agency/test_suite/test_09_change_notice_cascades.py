"""The ingredient change-notice freeze cascade and its compensation."""
from test_helpers import (
    create_approved_ingredient,
    create_certifiable_product,
    make_client_contact_headers,
    setup_certified_client,
    validate_paginated,
    validate_success,
)


class TestChangeNoticeFreezeCascade:
    def test_change_notice_freeze_cascade_depth4(self, api, officer_headers,
                                                 reviewer_headers):
        """PRD section 3.3: "Hop 1: every `ProductIngredient` junction
        referencing this ingredient with status `ACTIVE` flips to
        `PENDING_REAPPROVAL`. Hop 2: each product that owns a flipped junction
        and is currently `CERTIFIABLE` drops to `REVIEW_HOLD` — caused by the
        junction flip, not by the notice directly. Hop 3: each
        `CertificateProduct` entry whose product flipped in hop 2 and whose
        status is `INCLUDED` freezes to `FROZEN`. Hop 4: every certificate
        owning a frozen entry recomputes — `scope_status` becomes
        `PARTIAL_FROZEN`, and `active_product_count` is recomputed as the count
        of its `INCLUDED` entries."

        Design: Difficulty/transitive_cascade/change_notice_freeze_cascade_depth4
        """
        ctx = setup_certified_client(legal_name="Casc Co", num_products=2)
        cid = ctx["client"]["id"]
        ing1, ing2 = ctx["ingredients"]
        p1, p2 = ctx["products"]
        cert = ctx["certificate"]
        assert cert["active_product_count"] == 2
        assert cert["scope_status"] == "FULL"

        cc = make_client_contact_headers(cid)
        noticed = validate_success(
            api.file_change_notice(ing1["id"], "new supplier for IngK1", cc),
            201)
        assert noticed["status"] == "CHANGE_PENDING"

        j1, _ = validate_paginated(api.list_product_ingredients(p1["id"], cc))
        j2, _ = validate_paginated(api.list_product_ingredients(p2["id"], cc))
        assert j1[0]["status"] == "PENDING_REAPPROVAL", "hop 1 on the notice"
        assert j2[0]["status"] == "ACTIVE", "sibling junction untouched"

        prod1 = validate_success(api.get_product(p1["id"], cc))
        prod2 = validate_success(api.get_product(p2["id"], cc))
        assert prod1["status"] == "REVIEW_HOLD", "hop 2 caused by the flip"
        assert prod2["status"] == "CERTIFIABLE"

        entries, _ = validate_paginated(
            api.list_certificate_products(cert["id"], officer_headers))
        by_product = {e["product_id"]: e["status"] for e in entries}
        assert by_product[p1["id"]] == "FROZEN", "hop 3 caused by hop 2"
        assert by_product[p2["id"]] == "INCLUDED"

        reread = validate_success(api.get_certificate(cert["id"],
                                                      officer_headers))
        assert reread["scope_status"] == "PARTIAL_FROZEN"
        assert reread["active_product_count"] == 1, "hop 4 recompute"
        assert reread["status"] == "ACTIVE"

    def test_change_notice_freezes_product_without_certificate_too(
            self, api, reviewer_headers):
        """PRD section 3.3: "Hop 1: every `ProductIngredient` junction
        referencing this ingredient with status `ACTIVE` flips to
        `PENDING_REAPPROVAL`. Hop 2: each product that owns a flipped junction
        and is currently `CERTIFIABLE` drops to `REVIEW_HOLD`".

        Design: Difficulty/transitive_cascade/change_notice_freeze_cascade_depth4
        """
        # Client with an APPROVED ingredient and a CERTIFIABLE product that is
        # not listed on any certificate: hops 1-2 still fire.
        ctx = setup_certified_client(legal_name="Casc Co 2", num_products=1)
        cid = ctx["client"]["id"]
        extra_ing = create_approved_ingredient(cid, name="IngX")
        loose = create_certifiable_product(cid, [extra_ing["id"]],
                                           name="Loose")

        cc = make_client_contact_headers(cid)
        validate_success(api.file_change_notice(extra_ing["id"],
                                                "supplier swap", cc), 201)
        junctions, _ = validate_paginated(
            api.list_product_ingredients(loose["id"], cc))
        assert junctions[0]["status"] == "PENDING_REAPPROVAL"
        assert validate_success(api.get_product(loose["id"], cc))[
            "status"] == "REVIEW_HOLD"

        listed = validate_success(api.get_product(ctx["products"][0]["id"],
                                                  cc))
        assert listed["status"] == "CERTIFIABLE", (
            "the certificate-listed product is unaffected by the other "
            "ingredient's notice")


class TestFreezeCompensationConservation:
    def test_certificate_product_count_conserved_under_freeze_unfreeze_cycle(
            self, api, officer_headers, reviewer_headers):
        """PRD section 3.3: "Approval now runs the compensation cascade: every
        `PENDING_REAPPROVAL` junction for this ingredient returns to `ACTIVE`;
        each product whose junctions were restored, which is in `REVIEW_HOLD`,
        and which has no remaining junctions in `PENDING_REAPPROVAL` or
        `BLOCKED` returns to `CERTIFIABLE`; each `FROZEN` certificate entry for
        those restored products returns to `INCLUDED`; and each owning
        certificate recomputes `scope_status` (`FULL` when no `FROZEN` entries
        remain) and `active_product_count`."

        Design: Difficulty/compensating_invariant/certificate_product_count_conserved_under_freeze_unfreeze_cycle
        """
        ctx = setup_certified_client(legal_name="Count Co", num_products=2)
        cid = ctx["client"]["id"]
        ing1 = ctx["ingredients"][0]
        cert_id = ctx["certificate"]["id"]
        assert ctx["certificate"]["active_product_count"] == 2
        assert ctx["certificate"]["scope_status"] == "FULL"

        cc = make_client_contact_headers(cid)
        validate_success(api.file_change_notice(ing1["id"], "supplier swap",
                                                cc), 201)
        mid = validate_success(api.get_certificate(cert_id, officer_headers))
        assert mid["active_product_count"] == 1
        assert mid["scope_status"] == "PARTIAL_FROZEN"

        validate_success(api.resubmit_ingredient(ing1["id"], cc))
        validate_success(api.approve_ingredient(ing1["id"], reviewer_headers))
        end = validate_success(api.get_certificate(cert_id, officer_headers))
        assert end["active_product_count"] == 2, (
            "the compensating cascade restores the conserved count exactly")
        assert end["scope_status"] == "FULL"
        assert end["status"] == "ACTIVE", "freeze never suspends"

    def test_rejection_after_change_notice_blocks_junctions(
            self, api, officer_headers, reviewer_headers):
        """PRD section 3.3: "Rejection instead flips every `PENDING_REAPPROVAL`
        junction to `BLOCKED`, and affected products stay in `REVIEW_HOLD` until
        the client removes the blocked junction (§3.4)."

        Design: Difficulty/compensating_invariant/certificate_product_count_conserved_under_freeze_unfreeze_cycle
        """
        ctx = setup_certified_client(legal_name="Count Co 2", num_products=2)
        cid = ctx["client"]["id"]
        cc = make_client_contact_headers(cid)
        ing1 = ctx["ingredients"][0]
        p1 = ctx["products"][0]
        cert_id = ctx["certificate"]["id"]

        validate_success(api.file_change_notice(ing1["id"], "bad formulation",
                                                cc), 201)
        validate_success(api.resubmit_ingredient(ing1["id"], cc))
        rejected = validate_success(api.reject_ingredient(ing1["id"],
                                                          reviewer_headers))
        assert rejected["status"] == "REJECTED"

        junctions, _ = validate_paginated(
            api.list_product_ingredients(p1["id"], cc))
        assert junctions[0]["status"] == "BLOCKED"
        assert validate_success(api.get_product(p1["id"], cc))[
            "status"] == "REVIEW_HOLD", "a BLOCKED junction holds the product"
        mid = validate_success(api.get_certificate(cert_id, officer_headers))
        assert mid["active_product_count"] == 1
        assert mid["scope_status"] == "PARTIAL_FROZEN"

        # Manual release valve: removing the blocked junction restores the
        # product and unfreezes the certificate entry.
        validate_success(api.delete_product_ingredient(junctions[0]["id"], cc))
        assert validate_success(api.get_product(p1["id"], cc))[
            "status"] == "CERTIFIABLE"
        end = validate_success(api.get_certificate(cert_id, officer_headers))
        assert end["active_product_count"] == 2
        assert end["scope_status"] == "FULL"
