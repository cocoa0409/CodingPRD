"""Stale-revision guards, a re-stamped derived field, and same-response visibility.

Covers the two optimistic-concurrency parents and their distinct errors, the
shop's stored coverage figure being rewritten as its source appears and
disappears, and the ledger and seat counters being readable in the very
responses that moved them.
"""

import pytest

from test_helpers import (
    CONTENT_PUBLISHER_1_USER_ID,
    CONTENT_PUBLISHER_2_USER_ID,
    ApiErrorId,
    CellState,
    CoverageBasis,
    DistributionStatus,
    EntitlementStatus,
    ReviewStatus,
    SeatStatus,
    SettlementStatus,
    assert_coverage_map,
    assert_coverage_partition,
    assert_entitlement,
    assert_gaps_sorted,
    assert_publication,
    assert_publication_version,
    assert_seat_assignment,
    assert_seat_counts,
    assert_shop,
    factories,
    fixtures,
    make_content_publisher_headers,
    make_platform_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheEntitlementRevisionGuardsTheSeatMap:
    """A version observed before the first seat is no longer good for the second."""

    def test_replaying_the_pre_seat_version_is_refused_and_the_re_read_succeeds(
        self, api
    ):
        """412 on the stale replay, 201 on the retry, and the ledger moves once.

        PRD 2.5: "Seating a technician on an entitlement requires a non-optional
        `expected_entitlement_version` field in the request body, carrying the
        client's last observed `version` of the target `ShopEntitlement`. If that
        value does not equal the entitlement's current `version`, the create is
        rejected with `ERR_STALE_ENTITLEMENT_VERSION` (HTTP 412)." PRD 3.5: "A
        successful seating recomputes the entitlement's seat ledger, advances the
        entitlement's `version` by 1", where "`seats_assigned` is the count of seat
        rows on that entitlement whose status is `ACTIVE`".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_entitlement_version_rejected_on_seat_create
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), seats_total=3
        )
        fixtures.add_technician(api, ctx, key="first", full_name="Tina Tech")
        fixtures.add_technician(
            api,
            ctx,
            key="second",
            full_name="Raj Wrench",
            identity_document_ref="DL-88456",
        )
        manager = ctx["manager_headers"]
        entitlement = fixtures.refresh_entitlement(api, ctx)
        stale_version = entitlement["version"]
        assert stale_version == 2

        validate_success(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    entitlement["id"],
                    ctx["technicians"]["first"]["id"],
                    stale_version,
                ),
                manager,
            ),
            201,
        )

        validate_error(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    entitlement["id"],
                    ctx["technicians"]["second"]["id"],
                    stale_version,
                ),
                manager,
            ),
            ApiErrorId.STALE_ENTITLEMENT_VERSION,
            412,
        )

        re_read = fixtures.refresh_entitlement(api, ctx)
        assert re_read["version"] == 3
        assert_seat_counts(re_read, 1, 2)

        retried = validate_success(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    entitlement["id"],
                    ctx["technicians"]["second"]["id"],
                    re_read["version"],
                ),
                manager,
            ),
            201,
        )
        assert_seat_assignment(retried)
        assert retried["status"] == SeatStatus.ACTIVE

        after = fixtures.refresh_entitlement(api, ctx)
        assert after["version"] == 4
        assert_seat_counts(after, 2, 1)

        _rows, meta = validate_paginated(
            api.list_seat_assignments(
                manager,
                {"entitlement_id": entitlement["id"], "status": SeatStatus.ACTIVE},
            )
        )
        assert meta["total_count"] == 2


class TestThePublicationRevisionGuardsVersionMinting:
    """The second OCC parent answers with its own error id at its own priority."""

    def test_replaying_the_pre_ingest_publication_version_is_refused(self, api):
        """The stale mint is 412 with the publication-parent error, not the seat one.

        PRD 2.5: "Minting a new version under a publication requires a non-optional
        `expected_publication_version` field, carrying the client's last observed
        `version` of the target `Publication`. A mismatch with the publication's
        current `version` is rejected with `ERR_STALE_PUBLICATION_PARENT_VERSION`
        (HTTP 412)." PRD 3.6: the minted row "takes a `version_no` of the
        publication's `current_version_no` plus 1", "the publication's
        `current_version_no` is advanced to match, and the publication's own
        `version` advances by 1", and it "opens with `review_status` of `DRAFT`,
        `distribution_status` of `WITHHELD`".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_publication_parent_version_rejected_on_version_mint
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        author = make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)
        publication = validate_success(
            api.create_publication(
                factories.publication_payload(
                    ctx["vehicle_model"]["id"], ctx["areas"]["POWERTRAIN"]["id"]
                ),
                author,
            ),
            201,
        )
        stale_version = publication["version"]
        assert stale_version == 1

        validate_success(
            api.create_publication_version(
                publication["id"],
                factories.publication_version_payload(
                    stale_version, source_tsb_ref="TSB-0001"
                ),
                author,
            ),
            201,
        )

        validate_error(
            api.create_publication_version(
                publication["id"],
                factories.publication_version_payload(
                    stale_version, source_tsb_ref="TSB-0002"
                ),
                author,
            ),
            ApiErrorId.STALE_PUBLICATION_PARENT_VERSION,
            412,
        )

        re_read = validate_success(api.get_publication(publication["id"], author))
        assert_publication(re_read)
        assert re_read["version"] == 2
        assert re_read["current_version_no"] == 1

        retried = validate_success(
            api.create_publication_version(
                publication["id"],
                factories.publication_version_payload(
                    re_read["version"], source_tsb_ref="TSB-0002"
                ),
                author,
            ),
            201,
        )
        assert_publication_version(retried)
        assert retried["version_no"] == 2
        assert retried["review_status"] == ReviewStatus.DRAFT
        assert retried["distribution_status"] == DistributionStatus.WITHHELD

        after = validate_success(api.get_publication(publication["id"], author))
        assert after["current_version_no"] == 2
        assert after["version"] == 3
        assert after["published_version_id"] is None

        _rows, meta = validate_paginated(
            api.list_publication_versions(publication["id"], author, {"limit": 100})
        )
        assert meta["total_count"] == 2


class TestTheStoredCoverageFigureIsRestampedThreeTimes:
    """Zero with nothing published, one hundred once published, zero again on recall."""

    def test_publishing_then_recalling_rewrites_the_shops_stored_completeness(
        self, api
    ):
        """The denormalized percentage tracks its single source in both directions.

        PRD 3.9: "The effective-basis value is additionally **stored** on the shop
        as `coverage_completeness_pct`, and that stored figure is recomputed at
        every point where the inputs could have moved: at every entitlement status
        change — activation, cancellation and the lapse cascade alike — and at every
        version validation, publication and recall touching a covered cell." Under
        the effective basis "the numerator is `covered_cells` alone, so an
        unvalidated-but-published procedure earns nothing", a cell is `COVERED`
        "when the repair-procedure set passes the strict test and, if the system
        area requires a calibration document, the calibration set also passes the
        strict test", and "Versions in `WITHHELD`, `SUPERSEDED` or `RECALLED`
        satisfy neither test."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_shop_coverage_pct_restamped_on_publish_and_recall
        """
        ctx = fixtures.build_entitled_shop(
            api, area_codes=("POWERTRAIN",), covered_area_codes=("POWERTRAIN",)
        )
        fixtures.add_publication_version(api, ctx, validate=True, publish=False)
        version_id = ctx["versions"]["main"]["id"]
        admin = make_platform_admin_headers()

        before = validate_success(api.get_shop(ctx["shop"]["id"], admin))
        assert_shop(before)
        assert before["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)

        published = validate_success(
            api.publish_publication_version(
                version_id, make_content_publisher_headers(CONTENT_PUBLISHER_2_USER_ID)
            )
        )
        assert published["distribution_status"] == DistributionStatus.PUBLISHED

        covered = validate_success(api.get_shop(ctx["shop"]["id"], admin))
        assert covered["coverage_completeness_pct"] == pytest.approx(100.00, abs=0.005)

        recalled = validate_success(
            api.recall_publication_version(
                version_id,
                factories.reason_payload("OEM withdrew the bulletin"),
                make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID),
            )
        )
        assert recalled["distribution_status"] == DistributionStatus.RECALLED

        after = validate_success(api.get_shop(ctx["shop"]["id"], admin))
        assert after["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)

        coverage = validate_success(api.get_coverage_map(ctx["shop"]["id"], admin, None))
        assert_coverage_map(coverage)
        assert_coverage_partition(coverage)
        assert coverage["basis"] == CoverageBasis.EFFECTIVE
        assert coverage["total_cells"] == 1
        assert coverage["covered_cells"] == 0
        assert coverage["gap_cells"] == 1
        assert coverage["completeness_pct"] == pytest.approx(0.00, abs=0.005)
        assert_gaps_sorted(coverage["gaps"])
        assert coverage["gaps"][0]["system_area_code"] == "POWERTRAIN"
        assert coverage["gaps"][0]["cell_state"] == CellState.GAP


class TestThePurchaseResponseAlreadyCarriesItsArithmetic:
    """The charge and the seat ledger are in the create response, not a later read."""

    def test_the_entitlement_create_response_and_the_next_shop_read_agree(self, api):
        """Charge, settlement and seat fields are stamped before the response leaves.

        PRD 3.3: "On success the platform stamps `charged_cents`, debits the shop's
        `data_credit_balance_cents` by that amount and advances the shop's `version`
        by 1, and the new entitlement opens with `status` of `PENDING`,
        `settlement_status` of `UNSETTLED`, `settled_cents` of 0, `seats_assigned`
        of 0 and `seats_available` equal to `seats_total`." The funded total is
        untouched, because "`funded_credit_total_cents` is a lifetime total and
        never decreases for any reason."

        Design: Corner/consistency_model/immediate_consistency_ledger_and_seat_counters_visible_in_same_response
        """
        ctx = fixtures.build_funded_shop(api, covered_area_codes=("POWERTRAIN",))

        entitlement = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"]
                ),
                ctx["manager_headers"],
            ),
            201,
        )

        assert_entitlement(entitlement)
        assert entitlement["charged_cents"] == 85000
        assert entitlement["settled_cents"] == 0
        assert entitlement["settlement_status"] == SettlementStatus.UNSETTLED
        assert entitlement["seats_total"] == 3
        assert_seat_counts(entitlement, 0, 3)

        shop = validate_success(
            api.get_shop(ctx["shop"]["id"], ctx["manager_headers"])
        )
        assert shop["funded_credit_total_cents"] == 200000
        assert shop["data_credit_balance_cents"] == 115000


class TestTheSeatResponseAlreadyMovedTheCounters:
    """The recomputed ledger is readable on the very next request."""

    def test_seating_shows_up_immediately_without_re_pricing_the_entitlement(
        self, api
    ):
        """Counters and version move on the seat write; the charge does not.

        PRD 3.5: "The **seat ledger** is a derived pair maintained on the
        entitlement after every seat mutation", and "A successful seating recomputes
        the entitlement's seat ledger, advances the entitlement's `version` by 1,
        appends a `SEAT_ASSIGNED` audit row, and answers 201." PRD 3.3 charges once,
        at purchase: "The purchase then prices itself with the **provisional**
        variant of the entitlement charge."

        Design: Corner/consistency_model/immediate_consistency_ledger_and_seat_counters_visible_in_same_response
        """
        ctx = fixtures.build_funded_shop(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_technician(api, ctx, key="main", full_name="Tina Tech")
        manager = ctx["manager_headers"]

        purchased = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"]
                ),
                manager,
            ),
            201,
        )
        activated = validate_success(
            api.activate_entitlement(purchased["id"], manager)
        )
        assert activated["status"] == EntitlementStatus.ACTIVE
        assert activated["version"] == 2

        seat = validate_success(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    purchased["id"],
                    ctx["technicians"]["main"]["id"],
                    activated["version"],
                ),
                manager,
            ),
            201,
        )
        assert_seat_assignment(seat)
        assert seat["status"] == SeatStatus.ACTIVE

        immediate = validate_success(api.get_entitlement(purchased["id"], manager))
        assert_seat_counts(immediate, 1, 2)
        assert immediate["version"] == 3
        assert immediate["charged_cents"] == 85000
