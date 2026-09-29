"""The tag inventory: what commits units, what releases them, what activates."""

from test_helpers import (
    AUDITOR,
    BREEDER,
    OFFICER,
    ApiErrorId,
    assert_quota_inventory_invariant,
    create_tag_order_payload,
    licensed_quota,
    read_version,
    reconcile_tag_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _quota_chain(api, denomination, breeder_code, propagator_name, allocated_units):
    return licensed_quota(
        api,
        quality_tier="TIER_B",
        territory_class="DOMESTIC",
        allocated_units=allocated_units,
        season_code="2026S1",
        basis="PER_PLANT",
        variety_overrides={
            "denomination": denomination,
            "species": "Rubus idaeus",
            "breeder_code": breeder_code,
            "base_royalty_cents_per_plant": 35,
            "base_royalty_cents_per_acre": 1200,
        },
        territory_codes=["US-WA"],
        propagator_name=propagator_name,
    )


def _request_tags(api, chain, requested_units):
    quota_version = read_version(api, api.get_production_quota, chain["quota_id"], OFFICER)
    return validate_success(
        api.create_tag_order(
            create_tag_order_payload(chain["quota_id"], quota_version,
                                     requested_units=requested_units),
            chain["propagator_headers"],
        ),
        201,
    )


class TestVoidingAnIssuedOrderRestoresTheInventory:
    """An issue-and-void lap leaves the quota exactly where it started."""

    def _requested_order(self, api):
        chain = _quota_chain(api, "Kettle Ridge Apple", "KR", "Kettle Ridge Growers", 20000)
        chain["tag_order"] = _request_tags(api, chain, 12000)
        return chain

    def test_a_merely_requested_order_commits_nothing(self, api):
        """A request is not an authorization, so the fresh order leaves all three
        derived fields where a new quota starts them.

        PRD 3.6: "A new quota starts `ACTIVE` with `tags_committed_units` 0, `tags_activated_units` 0, `units_available` equal to `allocated_units`, and `version` 1."

        Design: Difficulty/compensating_invariant/voiding_an_issued_tag_order_restores_quota_unit_inventory_exactly
        """
        chain = self._requested_order(api)

        assert chain["tag_order"]["status"] == "REQUESTED"
        assert chain["tag_order"]["serial_prefix"] is None
        assert chain["tag_order"]["voided_units"] == 0

        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["allocated_units"] == 20000
        assert quota["tags_committed_units"] == 0
        assert quota["units_available"] == 20000
        assert quota["tags_activated_units"] == 0
        assert_quota_inventory_invariant(quota)

    def test_issuance_commits_the_requested_units_and_mints_the_prefix(self, api):
        """Issuing moves the 12000 units into the committed set, dropping the
        available figure by exactly that amount, and stamps the first ordinal of
        the quota's series onto the batch.

        PRD 3.6: "That ordinal is the count of this quota's tag orders already in status `ISSUED` or `RECONCILED`, plus one — so the first batch issued against a quota ends in `0001`, the second in `0002`, and so on."

        Design: Difficulty/compensating_invariant/voiding_an_issued_tag_order_restores_quota_unit_inventory_exactly
        """
        chain = self._requested_order(api)

        issued = validate_success(api.issue_tag_order(chain["tag_order"]["id"], OFFICER))
        assert issued["status"] == "ISSUED"
        assert issued["serial_prefix"] == "KR-2026S1-0001"

        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_committed_units"] == 12000
        assert quota["units_available"] == 8000
        assert quota["tags_activated_units"] == 0
        assert_quota_inventory_invariant(quota)

    def test_voiding_returns_the_available_units_to_their_exact_prior_value(self, api):
        """The void captures 12000 as the compensating quantity and the available
        figure returns to 20000 with no drift; a second void is refused because
        VOIDED is terminal.

        PRD 3.6: "From `ISSUED`, the order drops out of the committed set and `units_available` rises by exactly `voided_units`, restoring the invariant with no drift."

        Design: Difficulty/compensating_invariant/voiding_an_issued_tag_order_restores_quota_unit_inventory_exactly
        """
        chain = self._requested_order(api)
        validate_success(api.issue_tag_order(chain["tag_order"]["id"], OFFICER))

        voided = validate_success(api.void_tag_order(chain["tag_order"]["id"], OFFICER))
        assert voided["status"] == "VOIDED"
        assert voided["voided_units"] == 12000

        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_committed_units"] == 0
        assert quota["units_available"] == 20000
        assert quota["tags_activated_units"] == 0
        assert_quota_inventory_invariant(quota)

        validate_error(
            api.void_tag_order(chain["tag_order"]["id"], OFFICER),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )


class TestQuotaInventoryReadAfterAMixedHistory:
    """The read surface agrees with the derivation across all three statuses."""

    def _mixed_history(self, api):
        chain = _quota_chain(api, "Northbank Bramble", "NK", "Northbank Nursery", 5000)
        first = _request_tags(api, chain, 400)
        validate_success(api.issue_tag_order(first["id"], OFFICER))
        validate_success(
            api.reconcile_tag_order(first["id"], reconcile_tag_order_payload(250),
                                    chain["propagator_headers"])
        )
        second = _request_tags(api, chain, 600)
        validate_success(api.issue_tag_order(second["id"], OFFICER))
        third = _request_tags(api, chain, 900)
        return chain, first, second, third

    def test_the_three_derived_fields_agree_with_the_order_history(self, api):
        """A reconciled order stays in the committed set alongside the issued one,
        while the still-requested 900 units are not committed at all.

        PRD 3.6: "`tags_committed_units` is the sum of `requested_units` over the quota's tag orders whose status is `ISSUED` or `RECONCILED`."

        Design: Corner/endpoints/quota_computed_read_matches_the_tag_inventory_calculation
        """
        chain, _first, _second, _third = self._mixed_history(api)

        quota = validate_success(api.get_production_quota(chain["quota_id"], AUDITOR))
        assert quota["allocated_units"] == 5000
        assert quota["tags_committed_units"] == 1000
        assert quota["units_available"] == 4000
        assert quota["tags_activated_units"] == 250
        assert_quota_inventory_invariant(quota)

    def test_only_issued_batches_carry_a_serial_prefix_in_series(self, api):
        """The two issued batches take the first two ordinals of the quota's
        series and the untouched request has no prefix at all, while the order
        collection remains browsable by quota and by status.

        PRD 3.6: "A new order starts in `REQUESTED` with `activated_units` 0, `voided_units` 0, `version` 1, and null `serial_prefix` and `issued_at`."

        Design: Corner/endpoints/quota_computed_read_matches_the_tag_inventory_calculation
        """
        chain, first, second, third = self._mixed_history(api)

        assert validate_success(api.get_tag_order(first["id"], AUDITOR))["serial_prefix"] == (
            "NK-2026S1-0001"
        )
        assert validate_success(api.get_tag_order(second["id"], AUDITOR))["serial_prefix"] == (
            "NK-2026S1-0002"
        )
        assert validate_success(api.get_tag_order(third["id"], AUDITOR))["serial_prefix"] is None

        _all_orders, all_meta = validate_paginated(
            api.list_tag_orders(AUDITOR, {"quota_id": chain["quota_id"]})
        )
        assert all_meta["total_count"] == 3
        _issued, issued_meta = validate_paginated(
            api.list_tag_orders(AUDITOR, {"quota_id": chain["quota_id"], "status": "ISSUED"})
        )
        assert issued_meta["total_count"] == 1


class TestIssueBindsOnLiveAvailability:
    """The fiscal ceiling is checked at issue time against the live figure."""

    def _one_issued_and_two_pending(self, api):
        chain = _quota_chain(api, "Oakbend Bramble", "OK", "Oakbend Nursery", 5000)
        first = _request_tags(api, chain, 4000)
        oversized = _request_tags(api, chain, 1500)
        exact = _request_tags(api, chain, 1000)
        validate_success(api.issue_tag_order(first["id"], OFFICER))
        return chain, first, oversized, exact

    def test_the_oversized_pending_order_is_refused_at_issue_time(self, api):
        """Requesting 1500 was itself accepted; only the issue call measures the
        order against the freshly re-derived 1000 units that are left.

        PRD 3.6: "The fiscal ceiling is then checked: the order's `requested_units` must not exceed the quota's `units_available` as freshly re-derived, and an over-request is rejected with `ERR_QUOTA_UNITS_EXCEEDED` (HTTP 422)."

        Design: Corner/endpoints/tag_issue_is_allowed_only_while_the_quota_has_units_available
        """
        chain, _first, oversized, _exact = self._one_issued_and_two_pending(api)
        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_committed_units"] == 4000
        assert quota["units_available"] == 1000

        validate_error(
            api.issue_tag_order(oversized["id"], OFFICER),
            ApiErrorId.ERR_QUOTA_UNITS_EXCEEDED.value,
            422,
        )

        unchanged = validate_success(api.get_tag_order(oversized["id"], OFFICER))
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["serial_prefix"] is None

    def test_an_order_for_exactly_the_remainder_is_issued(self, api):
        """1000 does not exceed 1000, so the boundary is inclusive: the batch is
        issued as the second of the series and drains the quota to zero.

        PRD 3.6: "Issuance also stamps `issued_at` with the logical clock's present instant, re-derives the quota's `tags_committed_units` and `units_available`, and increments both the order's `version` and the quota's `version`."

        Design: Corner/endpoints/tag_issue_is_allowed_only_while_the_quota_has_units_available
        """
        chain, _first, _oversized, exact = self._one_issued_and_two_pending(api)

        issued = validate_success(api.issue_tag_order(exact["id"], OFFICER))
        assert issued["status"] == "ISSUED"
        assert issued["serial_prefix"] == "OK-2026S1-0002"

        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_committed_units"] == 5000
        assert quota["units_available"] == 0
        assert_quota_inventory_invariant(quota)


class TestActivationIsBoundedByTheIssuedBatch:
    """More activations than were issued is a traceability breach."""

    def _issued_batch_of_four_hundred(self, api):
        chain = _quota_chain(api, "Zinnia Bramble", "ZN", "Zinnia Nursery", 5000)
        order = _request_tags(api, chain, 400)
        chain["tag_order"] = validate_success(api.issue_tag_order(order["id"], OFFICER))
        return chain

    def test_reporting_more_activations_than_tags_is_refused(self, api):
        """401 against a 400-unit batch is rejected and nothing is written: the
        order stays ISSUED with no activations recorded anywhere.

        PRD 3.6: "The payload carries `activated_units`, a non-negative integer that must not exceed the order's `requested_units`; more activations than were issued is rejected with `ERR_ACTIVATION_EXCEEDS_ISSUED` (HTTP 422)."

        Design: Corner/errors/reconciling_more_tags_than_were_issued_rejected
        """
        chain = self._issued_batch_of_four_hundred(api)

        validate_error(
            api.reconcile_tag_order(
                chain["tag_order"]["id"], reconcile_tag_order_payload(401),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_ACTIVATION_EXCEEDS_ISSUED.value,
            422,
        )

        order = validate_success(api.get_tag_order(chain["tag_order"]["id"], BREEDER))
        assert order["status"] == "ISSUED"
        assert order["activated_units"] == 0
        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_activated_units"] == 0

    def test_activating_exactly_the_issued_count_is_accepted(self, api):
        """The bound is inclusive at 400, and the reconciliation moves only the
        activated figure: the committed and available units are untouched because
        RECONCILED stays in the committed set.

        PRD 3.6: "Reconciliation writes `activated_units`, re-derives the quota's `tags_activated_units` while leaving `tags_committed_units` and `units_available` untouched, and increments both the order's `version` and the quota's `version`."

        Design: Corner/errors/reconciling_more_tags_than_were_issued_rejected
        """
        chain = self._issued_batch_of_four_hundred(api)

        reconciled = validate_success(
            api.reconcile_tag_order(
                chain["tag_order"]["id"], reconcile_tag_order_payload(400),
                chain["propagator_headers"],
            )
        )
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["activated_units"] == 400

        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_activated_units"] == 400
        assert quota["tags_committed_units"] == 400
        assert quota["units_available"] == 4600
        assert_quota_inventory_invariant(quota)
