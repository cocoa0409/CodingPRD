"""Writing a child against a parent you have not re-read, and a counter that must
be recomputed rather than nudged."""

from test_helpers import (
    BREEDER,
    OFFICER,
    ApiErrorId,
    active_agreement,
    add_line_item,
    create_production_quota_payload,
    create_propagator_agreement_payload,
    create_propagator,
    create_royalty_line_item_payload,
    create_sublicense_grant_payload,
    create_tag_order_payload,
    draft_report,
    licensed_quota,
    make_propagator_headers,
    read_version,
    released_variety,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestATagOrderMustCarryTheQuotasCurrentVersion:
    """A 5000-unit quota that has already taken one 400-unit order."""

    def _quota_with_one_order(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Highfield Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "HF",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Highfield Nursery",
            home_territory_code="US-WA",
        )
        chain["quota_version_at_creation"] = chain["quota"]["version"]
        chain["first_order"] = validate_success(
            api.create_tag_order(
                create_tag_order_payload(
                    chain["quota_id"], chain["quota_version_at_creation"],
                    requested_units=400,
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        return chain

    def test_the_first_order_alone_moves_the_quota_past_the_captured_version(self, api):
        """Requesting tags advances the quota even though a requested batch commits
        nothing, which is exactly why the captured version goes stale.

        PRD 3.6: "Creating it increments the quota's `version` by 1 even though none of the quota's derived tag fields change — a `REQUESTED` order is not yet committed — which is precisely why the next requester's `expected_quota_version` must be refreshed."

        Design: Corner/cross_cutting_complexity_layers/tag_order_create_with_a_stale_quota_version_rejected
        """
        chain = self._quota_with_one_order(api)

        assert chain["quota_version_at_creation"] == 1
        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["version"] == 2
        assert quota["tags_committed_units"] == 0

    def test_replaying_the_captured_version_is_refused_and_writes_nothing(self, api):
        """A second order carrying the same version is working from a view the quota
        has left behind, so it is refused and no row is created.

        PRD 2.7: "If `expected_quota_version` does not equal the quota's current `version`, the request is rejected with `ERR_STALE_QUOTA_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/tag_order_create_with_a_stale_quota_version_rejected
        """
        chain = self._quota_with_one_order(api)

        validate_error(
            api.create_tag_order(
                create_tag_order_payload(
                    chain["quota_id"], chain["quota_version_at_creation"],
                    requested_units=600,
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_STALE_QUOTA_VERSION.value,
            412,
        )

        _rows, meta = validate_paginated(
            api.list_tag_orders(OFFICER, {"quota_id": chain["quota_id"]})
        )
        assert meta["total_count"] == 1
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "version"
        ] == 2

    def test_re_reading_the_quota_makes_the_identical_request_succeed(self, api):
        """The refusal was about the view and not about the batch, so resubmitting
        the same 600 units against the freshly read version is accepted and moves
        the quota on again.

        PRD 3.6: "A new order starts in `REQUESTED` with `activated_units` 0, `voided_units` 0, `version` 1, and null `serial_prefix` and `issued_at`."

        Design: Corner/cross_cutting_complexity_layers/tag_order_create_with_a_stale_quota_version_rejected
        """
        chain = self._quota_with_one_order(api)
        validate_error(
            api.create_tag_order(
                create_tag_order_payload(
                    chain["quota_id"], chain["quota_version_at_creation"],
                    requested_units=600,
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_STALE_QUOTA_VERSION.value,
            412,
        )

        fresh = read_version(api, api.get_production_quota, chain["quota_id"], OFFICER)
        second = validate_success(
            api.create_tag_order(
                create_tag_order_payload(chain["quota_id"], fresh,
                                         requested_units=600),
                chain["propagator_headers"],
            ),
            201,
        )
        assert second["status"] == "REQUESTED"
        assert second["version"] == 1
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "version"
        ] == 3


class TestALineItemMustCarryTheReportsCurrentVersion:
    """Two quotas in two territories, and a draft report that has taken one line."""

    def _report_with_one_line(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Ivythorn Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "IV",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA", "US-OR"], propagator_name="Ivythorn Nursery",
            home_territory_code="US-WA",
        )
        chain["second_quota"] = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"],
                    season_code="2026S1", basis="PER_PLANT",
                    territory_code="US-OR", territory_class="DOMESTIC",
                    allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        chain["report_id"] = report["id"]
        chain["report_version_at_creation"] = report["version"]
        chain["first_line"] = add_line_item(api, chain, report["id"], 100)
        return chain

    def test_the_first_line_alone_moves_the_report_past_the_captured_version(self, api):
        """Every appended line changes the report, so the version captured when the
        report was drafted no longer describes it.

        PRD 3.7: "A new line is created with `billable_units` 0, `effective_rate_cents` 0.0000, `provisional_amount_cents` 0, `final_amount_cents` 0, `overrun_flagged` false and `version` 1 — all of its money is computed later, at submission and again at acceptance — and creating it increments the report's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/line_item_create_with_a_stale_report_version_rejected
        """
        chain = self._report_with_one_line(api)

        assert chain["report_version_at_creation"] == 1
        assert chain["first_line"]["version"] == 1
        report = validate_success(
            api.get_royalty_report(chain["report_id"], OFFICER)
        )
        assert report["version"] == 2

    def test_the_second_line_replaying_that_version_is_refused(self, api):
        """A line against the other quota would be perfectly legitimate, so the only
        thing rejecting it is the stale view, and the collection is untouched.

        PRD 2.7: "A mismatch against the report's current `version` is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/line_item_create_with_a_stale_report_version_rejected
        """
        chain = self._report_with_one_line(api)

        validate_error(
            api.create_royalty_line_item(
                chain["report_id"],
                create_royalty_line_item_payload(
                    chain["second_quota"]["id"], 200,
                    chain["report_version_at_creation"],
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_STALE_REPORT_VERSION.value,
            412,
        )

        rows, meta = validate_paginated(
            api.list_royalty_line_items(OFFICER,
                                        {"report_id": chain["report_id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == chain["first_line"]["id"]

    def test_only_the_accepted_lines_are_priced_at_submission(self, api):
        """The refused line contributed nothing to the reported basis, and after it
        is resubmitted against the fresh version both lines price together.

        PRD 3.7: "The report's `provisional_total_cents` is then the sum of those already-rounded per-line amounts."

        Design: Corner/cross_cutting_complexity_layers/line_item_create_with_a_stale_report_version_rejected
        """
        chain = self._report_with_one_line(api)
        validate_error(
            api.create_royalty_line_item(
                chain["report_id"],
                create_royalty_line_item_payload(
                    chain["second_quota"]["id"], 200,
                    chain["report_version_at_creation"],
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_STALE_REPORT_VERSION.value,
            412,
        )

        add_line_item(api, chain, chain["report_id"], 200,
                      quota_id=chain["second_quota"]["id"])
        submitted = validate_success(
            api.submit_royalty_report(chain["report_id"],
                                      chain["propagator_headers"])
        )
        assert submitted["provisional_total_cents"] == 10500


class TestAGrantMustObserveTheCountersignature:
    """Here the parent's version was moved by a state transition, not a child write."""

    def _countersigned_agreement(self, api):
        variety = validate_success(
            api.create_variety(
                {
                    "denomination": "Juniper Bramble",
                    "species": "Rubus idaeus",
                    "breeder_code": "JP",
                    "royalty_basis_default": "PER_PLANT",
                    "base_royalty_cents_per_plant": 35,
                    "base_royalty_cents_per_acre": 1200,
                },
                BREEDER,
            ),
            201,
        )
        propagator = create_propagator(api, legal_name="Juniper Nursery",
                                       home_territory_code="US-WA")
        drafted = validate_success(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    propagator["id"], quality_tier="TIER_B",
                    territory_codes=["US-WA"],
                ),
                OFFICER,
            ),
            201,
        )
        validate_success(api.countersign_agreement(drafted["id"], OFFICER))
        return {
            "variety_id": variety["id"],
            "propagator_id": propagator["id"],
            "propagator_headers": make_propagator_headers(propagator["id"]),
            "agreement_id": drafted["id"],
            "agreement_version_at_draft": drafted["version"],
        }

    def test_countersigning_is_what_made_the_captured_version_stale(self, api):
        """The version the officer saw when drafting predates the activation, so a
        grant carrying it is refused and nothing is proposed.

        PRD 2.7: "The agreement's `version` advances on countersign, suspend, reinstate and terminate, each of which changes whether and where a sublicense may be granted."

        Design: Corner/cross_cutting_complexity_layers/sublicense_create_with_a_stale_agreement_version_rejected
        """
        setup = self._countersigned_agreement(api)

        assert setup["agreement_version_at_draft"] == 1
        agreement = validate_success(
            api.get_propagator_agreement(setup["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "ACTIVE"
        assert agreement["version"] == 2

        validate_error(
            api.create_sublicense_grant(
                create_sublicense_grant_payload(
                    setup["agreement_id"], setup["variety_id"],
                    setup["agreement_version_at_draft"],
                    sublicensee_name="Juniper Retail", territory_code="US-WA",
                    jurisdiction_code="US", exclusivity="NON_EXCLUSIVE",
                    effective_date="2026-10-01T00:00:00Z",
                    expiry_date="2026-12-31T00:00:00Z",
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
            412,
        )

        _rows, meta = validate_paginated(
            api.list_sublicense_grants(OFFICER,
                                       {"agreement_id": setup["agreement_id"]})
        )
        assert meta["total_count"] == 0
        assert validate_success(
            api.get_propagator_agreement(setup["agreement_id"], OFFICER)
        )["version"] == 2

    def test_the_stale_view_outranks_a_business_defect_in_the_same_body(self, api):
        """The concurrency guard is judged before any business check, so a body that
        is both stale and aimed at an unlicensed territory is told about the view.

        PRD 2.8: "Placing it here, after existence and ownership but before any state or business check, means a client working from a stale view learns that fact rather than receiving a business verdict computed against data it has never seen."

        Design: Corner/cross_cutting_complexity_layers/sublicense_create_with_a_stale_agreement_version_rejected
        """
        setup = self._countersigned_agreement(api)

        validate_error(
            api.create_sublicense_grant(
                create_sublicense_grant_payload(
                    setup["agreement_id"], setup["variety_id"],
                    setup["agreement_version_at_draft"],
                    sublicensee_name="Juniper Retail", territory_code="US-ID",
                    jurisdiction_code="US", exclusivity="NON_EXCLUSIVE",
                    effective_date="2026-10-01T00:00:00Z",
                    expiry_date="2026-12-31T00:00:00Z",
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
            412,
        )

    def test_the_refreshed_version_carries_the_proposal_through(self, api):
        """Observing the countersignature is all that was required, and the grant is
        then created in the proposal state.

        PRD 3.8: "A new grant is created in `PROPOSED` with null `activated_at` and null `revocation_reason` and `version` 1, and creating it increments the agreement's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/sublicense_create_with_a_stale_agreement_version_rejected
        """
        setup = self._countersigned_agreement(api)
        fresh = read_version(api, api.get_propagator_agreement,
                             setup["agreement_id"], OFFICER)

        grant = validate_success(
            api.create_sublicense_grant(
                create_sublicense_grant_payload(
                    setup["agreement_id"], setup["variety_id"], fresh,
                    sublicensee_name="Juniper Retail", territory_code="US-WA",
                    jurisdiction_code="US", exclusivity="NON_EXCLUSIVE",
                    effective_date="2026-10-01T00:00:00Z",
                    expiry_date="2026-12-31T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        assert grant["status"] == "PROPOSED"
        assert grant["activated_at"] is None
        assert validate_success(
            api.get_propagator_agreement(setup["agreement_id"], OFFICER)
        )["version"] == 3


class TestTheActiveSublicenseCounterIsRecomputedFromStatus:
    """Two proposals over a released variety, then one activation lap each and a
    revocation."""

    def _two_proposed_grants(self, api):
        released = released_variety(
            api, denomination="Kestrel Bramble", species="Rubus idaeus",
            breeder_code="KS", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        variety_id = released["variety"]["id"]
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA", "US-OR"],
            propagator_name="Kestrel Nursery", home_territory_code="US-WA",
        )
        grants = []
        for name, territory in (("Kestrel Retail West", "US-WA"),
                                ("Kestrel Retail South", "US-OR")):
            version = read_version(api, api.get_propagator_agreement,
                                   chain["agreement_id"], OFFICER)
            grants.append(validate_success(
                api.create_sublicense_grant(
                    create_sublicense_grant_payload(
                        chain["agreement_id"], variety_id, version,
                        sublicensee_name=name, territory_code=territory,
                        jurisdiction_code="US", exclusivity="NON_EXCLUSIVE",
                        effective_date="2026-10-01T00:00:00Z",
                        expiry_date="2026-12-31T00:00:00Z",
                    ),
                    OFFICER,
                ),
                201,
            ))
        chain.update({"variety_id": variety_id, "grants": grants,
                      "first_grant_id": grants[0]["id"],
                      "second_grant_id": grants[1]["id"]})
        return chain

    def test_proposals_are_not_counted_at_all(self, api):
        """The counter tracks the active population, so two existing grants leave it
        at zero on a variety that is released and protected.

        PRD 3.8: "From `PROPOSED`, `active_sublicense_count` is unchanged because a proposed grant was never counted in it, so only the grant's `version` increments; the variety's `version` increments only when the count actually changed."

        Design: Corner/cross_cutting_complexity_layers/active_sublicense_count_reconciles_across_activation_and_revocation
        """
        chain = self._two_proposed_grants(api)

        variety = validate_success(api.get_variety(chain["variety_id"], BREEDER))
        assert variety["lifecycle_state"] == "RELEASED"
        assert variety["protection_posture"] == "PROTECTED"
        assert variety["active_sublicense_count"] == 0

    def test_each_activation_raises_the_count_by_exactly_one(self, api):
        """Activation re-derives the counter rather than adjusting it, and the two
        laps are observable one at a time.

        PRD 3.8: "Activation stamps `activated_at` with the present instant, re-derives the variety's `active_sublicense_count` — the count of that variety's grants whose status is `ACTIVE` — and increments both the grant's `version` and the variety's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/active_sublicense_count_reconciles_across_activation_and_revocation
        """
        chain = self._two_proposed_grants(api)

        validate_success(api.activate_sublicense_grant(chain["first_grant_id"],
                                                       OFFICER))
        assert validate_success(api.get_variety(chain["variety_id"], BREEDER))[
            "active_sublicense_count"
        ] == 1

        validate_success(api.activate_sublicense_grant(chain["second_grant_id"],
                                                       OFFICER))
        assert validate_success(api.get_variety(chain["variety_id"], BREEDER))[
            "active_sublicense_count"
        ] == 2

    def test_revoking_one_lowers_the_count_while_the_row_survives(self, api):
        """Row count and active count are different quantities: the revoked grant is
        still there to be read, and the counter agrees with the active filter.

        PRD 3.8: "From `ACTIVE`, the variety's `active_sublicense_count` is re-derived and drops, and both the grant's `version` and the variety's `version` increment by 1."

        Design: Corner/cross_cutting_complexity_layers/active_sublicense_count_reconciles_across_activation_and_revocation
        """
        chain = self._two_proposed_grants(api)
        validate_success(api.activate_sublicense_grant(chain["first_grant_id"],
                                                       OFFICER))
        validate_success(api.activate_sublicense_grant(chain["second_grant_id"],
                                                       OFFICER))

        revoked = validate_success(
            api.revoke_sublicense_grant(chain["first_grant_id"], OFFICER)
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason"] == "MANUAL"
        assert validate_success(api.get_variety(chain["variety_id"], BREEDER))[
            "active_sublicense_count"
        ] == 1

        _all_rows, all_meta = validate_paginated(
            api.list_sublicense_grants(OFFICER,
                                       {"variety_id": chain["variety_id"]})
        )
        assert all_meta["total_count"] == 2
        _active_rows, active_meta = validate_paginated(
            api.list_sublicense_grants(OFFICER, {"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 1

    def test_a_second_revocation_is_terminal_and_cannot_double_decrement(self, api):
        """The revoked grant is in a terminal state of its machine, so the repeat is
        refused on that ground and the counter cannot drift.

        PRD 2.8: "Before the generic transition check, the server asks whether the target is already in a terminal state of the machine this action drives, so that a terminal resource yields the specific terminal code."

        Design: Corner/cross_cutting_complexity_layers/active_sublicense_count_reconciles_across_activation_and_revocation
        """
        chain = self._two_proposed_grants(api)
        validate_success(api.activate_sublicense_grant(chain["first_grant_id"],
                                                       OFFICER))
        validate_success(api.activate_sublicense_grant(chain["second_grant_id"],
                                                       OFFICER))
        validate_success(api.revoke_sublicense_grant(chain["first_grant_id"],
                                                     OFFICER))

        validate_error(
            api.revoke_sublicense_grant(chain["first_grant_id"], OFFICER),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )
        assert validate_success(api.get_variety(chain["variety_id"], BREEDER))[
            "active_sublicense_count"
        ] == 1
