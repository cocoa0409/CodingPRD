"""Gift declaration caps, intake cascades, and receive-window rules."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_gift_payload, ApiErrorId,
    set_clock, get_family, get_child, get_adoption, get_wish_item,
    setup_matched_family, setup_gift_in_state,
    make_donor_headers, make_volunteer_headers, make_platform_admin_headers,
)


class TestGiftValueCap:
    def test_declared_value_at_exact_cap_succeeds(self, api):
        """PRD §3.7: "The declared value is audited against the campaign's
        per-item cap: `declared_value_cents` may not exceed
        `max_gift_value_cents`, else the create is rejected with
        `ERR_GIFT_VALUE_EXCEEDED` (HTTP 422)." At exactly the cap the value does
        not exceed it, so the create succeeds.

        Design: Difficulty/boundary_precision_check/gift_value_at_exact_cap_vs_one_over
        """
        ctx = setup_matched_family()  # default cap 20000
        res = api.create_gift(
            create_gift_payload(ctx["adoption"]["id"], ctx["children"][0]["id"],
                                declared_value_cents=20000),
            make_donor_headers(ctx["donor"]["id"]))
        gift = validate_success(res, 201)
        assert gift["status"] == "COMMITTED"
        assert gift["declared_value_cents"] == 20000

    def test_declared_value_one_cent_over_cap_rejected(self, api):
        """PRD §3.7: "The declared value is audited against the campaign's
        per-item cap: `declared_value_cents` may not exceed
        `max_gift_value_cents`, else the create is rejected with
        `ERR_GIFT_VALUE_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/gift_value_at_exact_cap_vs_one_over
        """
        ctx = setup_matched_family()  # default cap 20000
        res = api.create_gift(
            create_gift_payload(ctx["adoption"]["id"], ctx["children"][0]["id"],
                                declared_value_cents=20001),
            make_donor_headers(ctx["donor"]["id"]))
        validate_error(res, ApiErrorId.ERR_GIFT_VALUE_EXCEEDED,
                       expected_status=422)


class TestReceiveCascade:
    def test_receive_fans_out_four_hop_cascade(self, api, admin_headers):
        """PRD §3.7: "A successful receive stamps `received_at` and fans out a
        five-way cascade: the adoption moves from `CONFIRMED` to
        `PARTIALLY_RECEIVED` if this is its first gift; the child moves from
        `ADOPTED` to `GIFT_RECEIVED`; the referenced wish item moves from
        `COMMITTED` to `RECEIVED`; the family moves from `MATCHED` to
        `PARTIALLY_FULFILLED` with `fulfilled_children_count` recomputed; and the
        donor's `giving_history_cents` increases by the gift's
        `declared_value_cents`."

        Design: Difficulty/transitive_cascade/gift_receive_four_hop_cascade
        """
        ctx = setup_gift_in_state("COMMITTED", declared_value_cents=4500)
        gift = validate_success(api.receive_gift(
            ctx["gift"]["id"], make_volunteer_headers("vol_1")))
        assert gift["status"] == "RECEIVED"
        assert gift["received_at"], "receive stamps received_at"
        assert get_wish_item(ctx["wish_item"]["id"])["status"] == "RECEIVED"
        assert get_child(ctx["child"]["id"])["status"] == "GIFT_RECEIVED"
        assert get_adoption(ctx["adoption"]["id"])["status"] == \
            "PARTIALLY_RECEIVED"
        assert get_family(ctx["family"]["id"])["status"] == "PARTIALLY_FULFILLED"
        donor = validate_success(api.get_donor(ctx["donor"]["id"], admin_headers))
        assert donor["giving_history_cents"] == 4500

    def test_receive_from_in_transit_runs_same_cascade(self, api, admin_headers):
        """PRD §3.7: "Receiving is permitted from either `COMMITTED` or
        `IN_TRANSIT`" and "the donor's `giving_history_cents` increases by the
        gift's `declared_value_cents`."

        Design: Difficulty/transitive_cascade/gift_receive_four_hop_cascade
        """
        ctx = setup_gift_in_state("IN_TRANSIT", declared_value_cents=2500)
        gift = validate_success(api.receive_gift(
            ctx["gift"]["id"], make_volunteer_headers("vol_1")))
        assert gift["status"] == "RECEIVED"
        assert get_child(ctx["child"]["id"])["status"] == "GIFT_RECEIVED"
        assert get_adoption(ctx["adoption"]["id"])["status"] == \
            "PARTIALLY_RECEIVED"
        donor = validate_success(api.get_donor(ctx["donor"]["id"], admin_headers))
        assert donor["giving_history_cents"] == 2500


class TestParallelGiftAndAdoptionAxes:
    def _two_child_family_one_gift_received(self, api):
        # Family with two children; whole-family adoption; one gift received
        # for the first child only.
        ctx = setup_matched_family(children_specs=[{}, {"dob": "2019-01-01"}],
                                   wish_specs={0: [{}], 1: [{}]},
                                   approve_wishes=True)
        child1, child2 = ctx["children"]
        gift = validate_success(api.create_gift(
            create_gift_payload(ctx["adoption"]["id"], child1["id"],
                                wish_item_id=ctx["wish_items"][0]["id"],
                                declared_value_cents=3000),
            make_donor_headers(ctx["donor"]["id"])), 201)
        validate_success(api.receive_gift(gift["id"],
                                          make_volunteer_headers("vol_1")))
        return ctx, child1, child2

    def test_first_gift_moves_only_its_own_child(self, api):
        """PRD §3.7: "the child moves from `ADOPTED` to `GIFT_RECEIVED`" — only
        the child named on the received gift transitions; the sibling stays
        `ADOPTED`. PRD §3.6: "The first gift that reaches `RECEIVED` under the
        adoption transitions it to `PARTIALLY_RECEIVED`."

        Design: Difficulty/non_linear_state_machine/gift_parallel_dimensions_via_adoption_and_slot
        """
        ctx, child1, child2 = self._two_child_family_one_gift_received(api)
        assert get_child(child1["id"])["status"] == "GIFT_RECEIVED"
        assert get_child(child2["id"])["status"] == "ADOPTED"
        assert get_adoption(ctx["adoption"]["id"])["status"] == \
            "PARTIALLY_RECEIVED"

    def test_received_does_not_count_toward_fulfilled_rollup(self, api):
        """PRD §3.10: "`fulfilled_children_count` is the count of the family's
        children in `DELIVERED` or `BACKFILL_PURCHASED`." A child in
        `GIFT_RECEIVED` is counted in neither, so the count stays 0 even though
        the family moved to `PARTIALLY_FULFILLED` (PRD §3.7).

        Design: Difficulty/non_linear_state_machine/gift_parallel_dimensions_via_adoption_and_slot
        """
        ctx, _, _ = self._two_child_family_one_gift_received(api)
        family = get_family(ctx["family"]["id"])
        assert family["status"] == "PARTIALLY_FULFILLED"
        assert family["fulfilled_children_count"] == 0
        assert get_adoption(ctx["adoption"]["id"])["status"] != "FULFILLED"


class TestReceiveWindowRules:
    def test_receive_already_received_gift_rejected(self, api):
        """PRD §3.7: "Receiving is permitted from either `COMMITTED` or
        `IN_TRANSIT`" — a gift already in `RECEIVED` is in neither state, so the
        transition is undefined and the error catalogue maps it to
        `ERR_INVALID_STATE` (HTTP 409). The clock still sits before the
        return deadline, so the return-window rule is not in play.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_gift_receive
        """
        ctx = setup_gift_in_state("RECEIVED")
        received_at = ctx["gift"]["received_at"]
        res = api.receive_gift(ctx["gift"]["id"],
                               make_volunteer_headers("vol_2"),
                               override_note="second scan attempt")
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        gift = validate_success(api.get_gift(
            ctx["gift"]["id"], make_platform_admin_headers("admin_1")))
        assert gift["received_at"] == received_at, \
            "a rejected receive must not re-stamp received_at"

    def test_receive_after_return_deadline_rejected(self, api):
        """PRD §3.7: "the current instant must be at or before the adoption's
        snapshotted `return_deadline`, or — if
        `SeasonSettings.late_donor_grace_hours` is non-zero — within that many
        hours after the deadline and accompanied by a non-empty `override_note`.
        A violation is rejected with `ERR_RETURN_DEADLINE_PASSED` (HTTP 409)."
        The gift here is in `IN_TRANSIT` (a receivable state) and the grace
        window is the default 0, so only the deadline rule can fail.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_gift_receive
        """
        ctx = setup_gift_in_state("IN_TRANSIT")
        set_clock("2026-12-15T00:00:00Z")  # past the 2026-12-10 deadline
        res = api.receive_gift(ctx["gift"]["id"],
                               make_volunteer_headers("vol_1"),
                               override_note="late arrival")
        validate_error(res, ApiErrorId.ERR_RETURN_DEADLINE_PASSED,
                       expected_status=409)
        gift = validate_success(api.get_gift(
            ctx["gift"]["id"], make_platform_admin_headers("admin_1")))
        assert gift["status"] == "IN_TRANSIT"
