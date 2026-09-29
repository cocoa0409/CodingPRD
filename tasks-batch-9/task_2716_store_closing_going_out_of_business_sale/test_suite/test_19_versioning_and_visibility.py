"""Optimistic concurrency, threshold boundaries and same-request visibility.

These cases hold the two version-pinned creates to the version they were
authored against, walk the compliance posture across both of its inclusive
boundaries, and check that a derived figure is visible in the very response that
caused it.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    RETAILER_CONTROLLER_ID,
    api_client,
    assert_instant_equals,
    consignment_payload,
    engagement_version,
    expense_item_payload,
    file_sales_day,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    markdown_stage_payload,
    read_engagement,
    read_store,
    settlement_payload,
    setup_selling_engagement,
    setup_selling_store,
    store_version,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_DAY_ONE = "2026-09-15T00:00:00Z"

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "augmentation_prohibited": False, "prohibited_claim_codes": [],
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}

LICENSE_PERIOD = {
    "period_start_date": "2026-09-15", "period_end_date": "2026-10-14",
}

FIRST_STAGE = {
    "stage_index": 1, "discount_pct": 0.2, "sell_through_target_pct": 0.25,
    "window_start_date": "2026-09-16", "window_end_date": "2026-10-01",
}

SECOND_STAGE = {
    "stage_index": 2, "discount_pct": 0.3, "sell_through_target_pct": 0.5,
    "window_start_date": "2026-10-01", "window_end_date": "2026-10-14",
}

FORTY_UNIT_DAY = {
    "business_date": "2026-09-15", "original_net_sales_cents": 120000,
    "augmentation_net_sales_cents": 0, "original_units_sold": 40,
    "augmentation_units_sold": 0,
}


def _selling_store(store_code, license_number):
    """One selling NY store on an ACTIVE engagement, holding 1,000 APPAREL units."""
    return setup_selling_store(
        clock=CLOCK_DAY_ONE,
        jurisdiction_overrides=NY_RULES,
        store_overrides={
            "store_code": store_code,
            "address_line": f"{store_code} Liquidation Row",
        },
        lot_overrides=APPAREL_LOT,
        license_overrides=dict(LICENSE_PERIOD, license_number=license_number),
    )


def _create_settlement(engagement_id, expected_version, **extra):
    return api_client.create_settlement(
        engagement_id,
        settlement_payload(expected_version, **extra),
        make_consultant_headers(),
    )


def _read_settlement(settlement_id):
    return validate_success(
        api_client.get_settlement(settlement_id, make_consultant_headers())
    )


class TestSettlementCreateIsSerializedByTheEngagementVersion:
    def test_replaying_the_consumed_version_is_refused_before_the_open_worksheet_rule(
        self,
    ):
        """The first create spent the pinned version, so its replay fails the pin rather
        than the incumbent check.

        The PRD says: "A new worksheet opens at `settlement_status` of `DRAFT` with every
        split figure unset, and the create increments the engagement's `version` — which
        is exactly why a second create replaying the same `expected_engagement_version`
        fails the version pin."

        Design: Corner/cross_cutting_layers/settlement_create_rejects_the_stale_engagement_version_before_the_open_worksheet_check
        """
        scenario = _selling_store("S-8001", "NY-GOB-8001")
        engagement_id = scenario["engagement"]["id"]
        first_version = engagement_version(engagement_id)
        incumbent = validate_success(
            _create_settlement(engagement_id, first_version), 201
        )
        assert incumbent["settlement_status"] == "DRAFT"
        second_version = engagement_version(engagement_id)
        assert second_version == first_version + 1
        validate_error(
            _create_settlement(engagement_id, first_version, supersede_open=True),
            ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value,
            412,
        )
        assert _read_settlement(incumbent["id"])["settlement_status"] == "DRAFT"
        assert engagement_version(engagement_id) == second_version

    def test_the_refreshed_version_supersedes_the_open_incumbent(self):
        """Refreshing the pin is all the second worksheet needed; the first is
        superseded.

        The PRD says: "At most one worksheet per engagement may be open at a time:
        creating one while an incumbent sits in `DRAFT`, `PROPOSED`, or `DISPUTED`
        requires `supersede_open` to be exactly true, which drives the incumbent to
        `SUPERSEDED`; without the flag the request is refused with
        `ERR_SETTLEMENT_ALREADY_OPEN`, and an incumbent already in `ACCEPTED` is refused
        even with the flag, because `ACCEPTED` has no transition to `SUPERSEDED` and an
        accepted settlement may only move forward to `FINALIZED`."

        Design: Corner/cross_cutting_layers/settlement_create_rejects_the_stale_engagement_version_before_the_open_worksheet_check
        """
        scenario = _selling_store("S-8001", "NY-GOB-8001")
        engagement_id = scenario["engagement"]["id"]
        first_version = engagement_version(engagement_id)
        incumbent = validate_success(
            _create_settlement(engagement_id, first_version), 201
        )
        second_version = engagement_version(engagement_id)
        validate_error(
            _create_settlement(engagement_id, first_version, supersede_open=True),
            ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value,
            412,
        )
        successor = validate_success(
            _create_settlement(engagement_id, second_version, supersede_open=True), 201
        )
        assert successor["settlement_status"] == "DRAFT"
        assert _read_settlement(incumbent["id"])["settlement_status"] == "SUPERSEDED"
        assert engagement_version(engagement_id) == second_version + 1
        rows, meta = validate_paginated(
            api_client.list_settlements(engagement_id, make_consultant_headers())
        )
        assert meta["total_count"] == 2
        drafts = [row for row in rows if row["settlement_status"] == "DRAFT"]
        assert len(drafts) == 1
        assert drafts[0]["id"] == successor["id"]


def _author_stage(store_id, expected_version, stage):
    return api_client.create_markdown_stage(
        store_id,
        markdown_stage_payload(expected_version, **stage),
        make_consultant_headers(),
    )


class TestMarkdownStageCreateIsSerializedByTheStoreVersion:
    def test_the_stale_second_stage_is_refused_and_the_cadence_is_untouched(self):
        """Authoring stage one spent the version, so stage two replaying it writes
        nothing.

        The PRD says: "If the store's current `version` differs, the create is refused
        with `ERR_STALE_STORE_VERSION` (HTTP 412) and no stage is authored."

        Design: Corner/cross_cutting_layers/markdown_stage_create_rejects_the_stale_store_version_and_writes_nothing
        """
        scenario = _selling_store("S-8002", "NY-GOB-8002")
        store_id = scenario["store"]["id"]
        first_version = store_version(store_id)
        first_stage = validate_success(
            _author_stage(store_id, first_version, FIRST_STAGE), 201
        )
        assert first_stage["stage_status"] == "ARMED"
        second_version = store_version(store_id)
        assert second_version == first_version + 1
        validate_error(
            _author_stage(store_id, first_version, SECOND_STAGE),
            ApiErrorId.ERR_STALE_STORE_VERSION.value,
            412,
        )
        _rows, meta = validate_paginated(
            api_client.list_markdown_stages(store_id, make_consultant_headers())
        )
        assert meta["total_count"] == 1
        assert read_store(store_id)["planned_avg_discount_pct"] == pytest.approx(
            0.2000, abs=0.00001
        )
        assert store_version(store_id) == second_version

    def test_the_refreshed_store_version_authors_the_second_stage(self):
        """Nothing but the pin was wrong: the retry lands and moves the planned average.

        The PRD says: "Authoring recomputes the store's planned average discount and
        projection and the engagement roll-up, and increments the store's `version` by
        1."

        Design: Corner/cross_cutting_layers/markdown_stage_create_rejects_the_stale_store_version_and_writes_nothing
        """
        scenario = _selling_store("S-8002", "NY-GOB-8002")
        store_id = scenario["store"]["id"]
        first_version = store_version(store_id)
        validate_success(_author_stage(store_id, first_version, FIRST_STAGE), 201)
        second_version = store_version(store_id)
        validate_error(
            _author_stage(store_id, first_version, SECOND_STAGE),
            ApiErrorId.ERR_STALE_STORE_VERSION.value,
            412,
        )
        second_stage = validate_success(
            _author_stage(store_id, second_version, SECOND_STAGE), 201
        )
        assert second_stage["stage_status"] == "ARMED"
        assert second_stage["stage_index"] == 2
        store = read_store(store_id)
        assert store["version"] == second_version + 1
        assert store["planned_avg_discount_pct"] == pytest.approx(0.2500, abs=0.00001)
        assert store["projected_gross_recovery_cents"] == 3187500


REVOCATION_REASONS = (
    "no licence displayed at store A",
    "prohibited signage at store B",
    "false price comparison at store C",
)


def _four_selling_stores_with_a_stage_on_the_fourth():
    """Stores A-D all selling under their own licences; D also holds an ARMED stage."""
    suffixes = ("A", "B", "C", "D")
    scenario = setup_selling_engagement(
        clock=CLOCK_DAY_ONE,
        jurisdiction_overrides=NY_RULES,
        store_specs=[
            {
                "store": {
                    "store_code": f"S-8003{suffix}",
                    "address_line": f"S-8003{suffix} Liquidation Row",
                },
                "lots": [APPAREL_LOT],
                "license": dict(
                    LICENSE_PERIOD, license_number=f"NY-GOB-8003{suffix}"
                ),
            }
            for suffix in suffixes
        ],
    )
    store_d = scenario["stores"][3]
    scenario["stage_d"] = validate_success(
        _author_stage(store_d["id"], store_version(store_d["id"]), FIRST_STAGE), 201
    )
    return scenario


def _revoke(license_row, reason):
    return validate_success(
        api_client.revoke_gob_license(
            license_row["id"], {"revoked_reason": reason}, make_compliance_headers()
        ),
        200,
    )


class TestComplianceStrikesCrossBothInclusiveBoundaries:
    def test_one_strike_restricts_and_two_strikes_still_permit_an_activation(self):
        """The counter reaches two, the posture is still RESTRICTED, and the armed stage
        may run.

        The PRD says: "The posture is derived from the count and nothing else: `OPEN`
        when the count is exactly 0, `RESTRICTED` when the count is 1 or 2, and `FROZEN`
        when the count is 3 or more. … Activation is refused while the posture is
        `FROZEN` but remains permitted while it is `RESTRICTED`: a cadence already
        authored may be run, even though a new one may not be written."

        Design: Corner/cross_cutting_layers/compliance_strikes_cross_the_restricted_and_frozen_boundaries_at_one_and_three
        """
        scenario = _four_selling_stores_with_a_stage_on_the_fourth()
        engagement_id = scenario["engagement"]["id"]
        _revoke(scenario["licenses"][0], REVOCATION_REASONS[0])
        after_one = read_engagement(engagement_id)
        assert after_one["compliance_strike_count"] == 1
        assert after_one["compliance_posture"] == "RESTRICTED"
        _revoke(scenario["licenses"][1], REVOCATION_REASONS[1])
        after_two = read_engagement(engagement_id)
        assert after_two["compliance_strike_count"] == 2
        assert after_two["compliance_posture"] == "RESTRICTED"
        activated = validate_success(
            api_client.activate_markdown_stage(
                scenario["stage_d"]["id"], make_consultant_headers()
            ),
            200,
        )
        assert activated["stage_status"] == "ACTIVE"

    def test_the_third_strike_freezes_and_widens_the_gate(self):
        """At three strikes a proposal and an expense submission are both refused.

        The PRD says: "While the posture is `FROZEN`, a wider set of five operations is
        refused with `ERR_ENGAGEMENT_COMPLIANCE_FROZEN`: authoring a new markdown stage,
        activating a stage, proposing a new augmentation consignment, receiving an
        augmentation consignment, and submitting a new expense item."

        Design: Corner/cross_cutting_layers/compliance_strikes_cross_the_restricted_and_frozen_boundaries_at_one_and_three
        """
        scenario = _four_selling_stores_with_a_stage_on_the_fourth()
        engagement_id = scenario["engagement"]["id"]
        store_d = scenario["stores"][3]
        for license_row, reason in zip(scenario["licenses"][:3], REVOCATION_REASONS):
            _revoke(license_row, reason)
        frozen = read_engagement(engagement_id)
        assert frozen["compliance_strike_count"] == 3
        assert frozen["compliance_posture"] == "FROZEN"
        validate_error(
            api_client.create_augmentation_consignment(
                store_d["id"],
                consignment_payload(
                    units_supplied=50, unit_cost_cents=2000, unit_retail_cents=5000,
                    delivery_window_start_date="2026-09-16",
                    delivery_window_end_date="2026-09-20",
                ),
                make_consultant_headers(),
            ),
            ApiErrorId.ERR_ENGAGEMENT_COMPLIANCE_FROZEN.value,
            409,
        )
        validate_error(
            api_client.create_expense_item(
                engagement_id,
                expense_item_payload(
                    store_id=store_d["id"], expense_category="SECURITY",
                    amount_cents=50000, incurred_date="2026-09-15",
                ),
                make_consultant_headers(),
            ),
            ApiErrorId.ERR_ENGAGEMENT_COMPLIANCE_FROZEN.value,
            409,
        )

    def test_the_counter_never_decreases_and_the_struck_stores_stay_off_the_floor(self):
        """A resume that cannot find a live licence is refused and lowers nothing.

        The PRD says: "A licence denial never produces a strike, a discretionary
        compliance suspension never produces a strike, and the counter never decreases:
        resuming a suspended store leaves it exactly where it was."

        Design: Corner/cross_cutting_layers/compliance_strikes_cross_the_restricted_and_frozen_boundaries_at_one_and_three
        """
        scenario = _four_selling_stores_with_a_stage_on_the_fourth()
        engagement_id = scenario["engagement"]["id"]
        store_a, store_b, store_c, store_d = scenario["stores"]
        for license_row, reason in zip(scenario["licenses"][:3], REVOCATION_REASONS):
            _revoke(license_row, reason)
        validate_error(
            api_client.resume_store(store_a["id"], make_compliance_headers()),
            ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value,
            409,
        )
        engagement = read_engagement(engagement_id)
        assert engagement["compliance_strike_count"] == 3
        assert engagement["compliance_posture"] == "FROZEN"
        for store in (store_a, store_b, store_c):
            struck = read_store(store["id"])
            assert struck["store_status"] == "SUSPENDED"
            assert struck["suspension_reason"] == "LICENSE_REVOKED"
        assert read_store(store_d["id"])["store_status"] == "SELLING"


class TestEveryDerivedFigureIsVisibleInTheSameRequest:
    def test_the_review_response_already_carries_the_allocation_result(self):
        """The posting answers with its own stamps, and the lot read agrees at once.

        The PRD says: "A posting takes the day `PENDING_REVIEW → POSTED`, stamps
        `posted_at` with the current logical-clock instant, records
        `reviewed_by_user_id`, and consumes inventory. … Derived figures in this service
        are never stale."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        scenario = _selling_store("S-9001", "NY-GOB-9001")
        store_id = scenario["store"]["id"]
        day = file_sales_day(store_id, **FORTY_UNIT_DAY)
        assert day["day_status"] == "PENDING_REVIEW"
        posted = validate_success(
            api_client.review_sales_day(
                day["id"], {"decision": "POST"}, make_controller_headers()
            ),
            200,
        )
        assert posted["day_status"] == "POSTED"
        assert_instant_equals(posted["posted_at"], CLOCK_DAY_ONE, "posted_at")
        assert posted["reviewed_by_user_id"] == RETAILER_CONTROLLER_ID
        lot = validate_success(
            api_client.get_inventory_lot(
                scenario["lot"]["id"], make_consultant_headers()
            )
        )
        assert lot["units_sold"] == 40
        assert lot["units_on_hand"] == 960
        assert lot["lot_status"] == "ON_FLOOR"

    def test_the_store_the_engagement_and_the_summary_all_agree_with_no_re_read_delay(
        self,
    ):
        """One posting, and three independent reads carry the same realized money.

        The PRD says: "The store's `units_sold_total`, `realized_sell_through_pct`,
        `realized_gross_recovery_cents`, and `realized_recovery_ratio` are recomputed as
        defined in §3.2, and then the engagement's `original_net_sales_cents` and
        `augmentation_net_sales_cents` are re-summed over its posted days with
        `gross_recovery_cents` set to the two added together. … That read — available to
        the `LiquidationConsultant` and the `RetailerController` — is the one place both
        variants sit side by side, and it recomputes both before answering."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        scenario = _selling_store("S-9001", "NY-GOB-9001")
        store_id = scenario["store"]["id"]
        engagement_id = scenario["engagement"]["id"]
        day = file_sales_day(store_id, **FORTY_UNIT_DAY)
        validate_success(
            api_client.review_sales_day(
                day["id"], {"decision": "POST"}, make_controller_headers()
            ),
            200,
        )
        store = read_store(store_id)
        assert store["realized_gross_recovery_cents"] == 120000
        assert store["realized_recovery_ratio"] == pytest.approx(0.0600, abs=0.00001)
        assert store["realized_sell_through_pct"] == pytest.approx(0.0400, abs=0.00001)
        assert store["units_sold_total"] == 40
        engagement = read_engagement(engagement_id)
        assert engagement["original_net_sales_cents"] == 120000
        assert engagement["augmentation_net_sales_cents"] == 0
        assert engagement["gross_recovery_cents"] == 120000
        summary = validate_success(
            api_client.get_recovery_summary(engagement_id, make_controller_headers())
        )
        assert summary["realized_gross_recovery_cents"] == 120000
        assert summary["realized_recovery_ratio"] == pytest.approx(
            0.0600, abs=0.00001
        )
        assert summary["original_cost_value_cents"] == 2000000
        assert summary["store_count"] == 1
