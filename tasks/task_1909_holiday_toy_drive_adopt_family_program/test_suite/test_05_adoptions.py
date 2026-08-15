"""Adoption pledge: OCC guard, caps, expiry window, confirm gating, cancel."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_adoption_payload, ApiErrorId,
    set_clock, get_family, get_child, get_adoption, get_wish_item,
    setup_verified_family, setup_matched_family, setup_campaign_intake_open,
    create_family, add_child, verify_family, create_donor,
    pledge_adoption, pledge_and_confirm, confirm_adoption,
    make_donor_headers, make_platform_admin_headers,
)


class TestAdoptionOcc:
    def test_stale_family_version_rejected(self, api):
        """PRD §2.7: "A pledge to create an `Adoption` must carry
        `expected_family_version` matching the target `Family` row's current
        `version`. If a duplicate-flag resolution or a sibling adoption confirm
        has advanced the family's version since the donor last read it, the create
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_adoption_create_stale_family_version
        """
        ctx = setup_verified_family()
        family = get_family(ctx["family"]["id"])
        stale_version = family["version"]
        donor1 = create_donor()
        # First pledge succeeds and advances the family's version (PRD §3.5: "A
        # successful pledge increments the family's `version`").
        pledge_adoption(ctx["campaign"], family["id"], donor1)
        donor2 = create_donor()
        res = api.create_adoption(
            create_adoption_payload(ctx["campaign"]["id"], donor2["id"],
                                    family["id"], stale_version),
            make_donor_headers(donor2["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestAdoptionCap:
    def test_second_pledge_over_cap_rejected(self, api):
        """PRD §3.5: "Pledging also enforces the donor's concurrent-adoption cap:
        the count of this donor's adoptions in this campaign that are in
        `PLEDGED`, `CONFIRMED`, or `PARTIALLY_RECEIVED` must be strictly less than
        `max_adoptions_per_season`; otherwise the pledge is rejected with
        `ERR_ADOPTION_CAP_EXCEEDED` (HTTP 409)."

        Design: Corner/errors/error_adoption_cap_exceeded_covered
        """
        # Two verified families under one campaign, donor capped at 1.
        campaign, agency = setup_campaign_intake_open()
        fam1 = create_family(agency, campaign)
        add_child(fam1["id"], agency["id"])
        verify_family(fam1["id"])
        fam2 = create_family(agency, campaign)
        add_child(fam2["id"], agency["id"])
        verify_family(fam2["id"])
        donor = create_donor(max_adoptions_per_season=1)
        pledge_adoption(campaign, fam1["id"], donor)
        fam2 = get_family(fam2["id"])
        res = api.create_adoption(
            create_adoption_payload(campaign["id"], donor["id"], fam2["id"],
                                    fam2["version"]),
            make_donor_headers(donor["id"]))
        validate_error(res, ApiErrorId.ERR_ADOPTION_CAP_EXCEEDED,
                       expected_status=409)


class TestPledgeExpiryWindow:
    def test_confirm_after_72_hours_rejected(self, api):
        """PRD §3.6: "Confirming — `PLEDGED → CONFIRMED` — is permitted only to
        the donor whose `X-User-ID` equals the adoption's `donor_id`, only within
        72 hours of `pledged_at` (a later attempt yields `ERR_PLEDGE_EXPIRED`,
        HTTP 409)".

        Design: Corner/validations/adoption_pledge_expired_after_72h
        """
        ctx = setup_verified_family()
        donor = create_donor()
        adoption = pledge_adoption(ctx["campaign"], ctx["family"]["id"], donor)
        # Pledged at 2026-09-15 (fixture clock); jump 83 hours forward.
        set_clock("2026-09-18T11:00:00Z")
        res = api.confirm_adoption(adoption["id"], make_donor_headers(donor["id"]))
        validate_error(res, ApiErrorId.ERR_PLEDGE_EXPIRED, expected_status=409)


class TestConfirmGatedByFamilyState:
    def _two_pledges_one_family(self):
        # The confirm-time fiscal floor (PRD §3.6: commitment_cents >=
        # min_gift_value_cents x covered children) requires the verified
        # family's child to carry wish value, so the setup adds one wish item.
        ctx = setup_verified_family(wish_specs={0: [{}]})
        donor_a = create_donor()
        donor_b = create_donor()
        ad_a = pledge_adoption(ctx["campaign"], ctx["family"]["id"], donor_a)
        ad_b = pledge_adoption(ctx["campaign"], ctx["family"]["id"], donor_b)
        return ctx, donor_a, donor_b, ad_a, ad_b

    def test_confirm_rejected_once_family_left_verified(self, api):
        """PRD §3.6: "Confirming — `PLEDGED → CONFIRMED` — is permitted only to
        the donor whose `X-User-ID` equals the adoption's `donor_id`, only within
        72 hours of `pledged_at` (a later attempt yields `ERR_PLEDGE_EXPIRED`,
        HTTP 409), and only while the family is still `VERIFIED` (re-checked at
        confirm time) and the donor's concurrent-adoption count remains below
        `max_adoptions_per_season`." A sibling adoption's confirm moves the family
        `VERIFIED → MATCHED` (PRD §3.6: "transitions the family from `VERIFIED` to
        `MATCHED`"), so the second confirm's re-check fails; the transition is
        undefined for that family state and the error catalogue maps it to
        `ERR_INVALID_STATE` (HTTP 409).

        Design: Difficulty/cross_entity_state_dependency/adoption_confirm_gated_by_family_state
        """
        ctx, donor_a, donor_b, ad_a, ad_b = self._two_pledges_one_family()
        confirm_adoption(ad_a["id"], donor_a["id"])  # family -> MATCHED
        res = api.confirm_adoption(ad_b["id"], make_donor_headers(donor_b["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_adoption(ad_b["id"])["status"] == "PLEDGED"
        assert get_family(ctx["family"]["id"])["status"] == "MATCHED"

    def test_confirm_failure_is_family_state_not_pledge_expiry(self, api):
        """PRD §3.6: "Confirming — `PLEDGED → CONFIRMED` — is permitted only to
        the donor whose `X-User-ID` equals the adoption's `donor_id`, only within
        72 hours of `pledged_at` (a later attempt yields `ERR_PLEDGE_EXPIRED`,
        HTTP 409), and only while the family is still `VERIFIED` (re-checked at
        confirm time) and the donor's concurrent-adoption count remains below
        `max_adoptions_per_season`." With the clock well inside the 72-hour
        window, the rejection must be the family-state re-check, not the
        pledge-expiry rule.

        Design: Difficulty/cross_entity_state_dependency/adoption_confirm_gated_by_family_state
        """
        ctx, donor_a, donor_b, ad_a, ad_b = self._two_pledges_one_family()
        confirm_adoption(ad_a["id"], donor_a["id"])  # family -> MATCHED
        # Only minutes have passed since the pledge — far inside 72 hours.
        res = api.confirm_adoption(ad_b["id"], make_donor_headers(donor_b["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        # The confirmed sibling adoption bumped the family version (PRD §3.6:
        # "increments both the family's and the adoption's `version`").
        family = get_family(ctx["family"]["id"])
        pledge_time_version = ctx["family"]["version"]
        assert family["version"] > pledge_time_version


class TestDonorCancelInvariant:
    def _confirmed_with_approved_item(self):
        # One child, one APPROVED 5000-cent wish item, confirmed adoption.
        return setup_matched_family(
            wish_specs={0: [{"estimated_price_cents": 5000}]},
            approve_wishes=True, backfill_budget_cents=0)

    def test_cancel_restores_child_item_and_family_state(self, api):
        """PRD §3.6: "Both cascades are identical: every gift in `COMMITTED` or
        `IN_TRANSIT` moves to `RETURNED_TO_DONOR`, every covered child in
        `ADOPTED` moves to `BACKFILL_ELIGIBLE`, every `COMMITTED` wish item of
        covered children reverts to `APPROVED`, and the family reverts from
        `MATCHED` to `VERIFIED` if no other confirmed adoption covers it
        (otherwise the family's state is recomputed from remaining adoptions)."

        Design: Difficulty/compensating_invariant/adoption_confirm_then_donor_cancel_preserves_wish_value
        """
        ctx = self._confirmed_with_approved_item()
        child = ctx["children"][0]
        item = ctx["wish_items"][0]
        res = api.cancel_adoption(ctx["adoption"]["id"],
                                  make_donor_headers(ctx["donor"]["id"]),
                                  reason="changed mind")
        adoption = validate_success(res)
        assert adoption["status"] == "DONOR_CANCELLED"
        assert get_child(child["id"])["status"] == "BACKFILL_ELIGIBLE"
        assert get_wish_item(item["id"])["status"] == "APPROVED"
        assert get_family(ctx["family"]["id"])["status"] == "VERIFIED"

    def test_cancel_preserves_estimate_and_frozen_snapshot(self, api):
        """PRD §3.5: "At pledge time the server freezes a `commitment_cents`
        snapshot on the adoption: the sum of `gift_estimate_cents` over the
        covered children, captured at that instant and never recomputed even if a
        wish item is later edited." PRD §3.6 restores `COMMITTED` wish items to
        `APPROVED` on cancel, so the estimate (sum over `REQUESTED`/`APPROVED`
        items, PRD §3.4, which excludes `COMMITTED` items) returns to its
        pre-adoption value.

        Design: Difficulty/compensating_invariant/adoption_confirm_then_donor_cancel_preserves_wish_value
        """
        ctx = self._confirmed_with_approved_item()
        child = ctx["children"][0]
        # After confirm the sole wish item is COMMITTED, and PRD §3.4 excludes
        # COMMITTED items from gift_estimate_cents.
        estimate_before = get_child(child["id"])["gift_estimate_cents"]
        assert estimate_before == 0
        adoption = validate_success(api.cancel_adoption(
            ctx["adoption"]["id"], make_donor_headers(ctx["donor"]["id"]),
            reason="changed mind"))
        assert adoption["commitment_cents"] == 5000, \
            "the pledge-time snapshot is frozen and never recomputed"
        estimate_after = get_child(child["id"])["gift_estimate_cents"]
        assert estimate_after == 5000, \
            "restoring COMMITTED -> APPROVED returns the estimate to its " \
            "pre-adoption value bit-for-bit"

    def test_cancel_cascades_committed_gift_back_to_donor(self, api):
        """PRD §3.6: "Both cascades are identical: every gift in `COMMITTED` or
        `IN_TRANSIT` moves to `RETURNED_TO_DONOR`, every covered child in
        `ADOPTED` moves to `BACKFILL_ELIGIBLE`, every `COMMITTED` wish item of
        covered children reverts to `APPROVED`, and the family reverts from
        `MATCHED` to `VERIFIED` if no other confirmed adoption covers it
        (otherwise the family's state is recomputed from remaining adoptions)."

        Design: Corner/cross_cutting_layers/cascading_side_effects_multi_level
        """
        ctx = setup_matched_family(wish_specs={0: [{}]}, approve_wishes=True)
        child = ctx["children"][0]
        item = ctx["wish_items"][0]
        donor_headers = make_donor_headers(ctx["donor"]["id"])
        gift = validate_success(api.create_gift(
            {"adoption_id": ctx["adoption"]["id"], "child_id": child["id"],
             "wish_item_id": item["id"], "description": "t",
             "declared_value_cents": 2000}, donor_headers), 201)
        validate_success(api.cancel_adoption(ctx["adoption"]["id"],
                                             donor_headers, reason="cancel"))
        assert validate_success(api.get_gift(
            gift["id"], make_platform_admin_headers("admin_1"))
        )["status"] == "RETURNED_TO_DONOR"
        assert get_wish_item(item["id"])["status"] == "APPROVED"
        assert get_child(child["id"])["status"] == "BACKFILL_ELIGIBLE"
        assert get_family(ctx["family"]["id"])["status"] == "VERIFIED"
