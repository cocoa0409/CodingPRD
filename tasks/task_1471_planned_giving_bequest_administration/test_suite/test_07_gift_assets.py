"""Gift assets: parentage XOR, appraisal gate, FMV rounding, valuation bases,
and the received-value reconciliation."""
from test_helpers import (
    ApiErrorId,
    create_gift_asset_payload,
    make_active_rate_table,
    make_deceased_donor,
    make_donor,
    make_draft_agreement,
    make_estate,
    make_executed_agreement,
    validate_error,
    validate_success,
)


class TestAssetParentage:
    def test_gift_asset_orphan_xor_enforced(self, api, estate_manager_headers, gift_officer_headers):
        """PRD §3.5: "Every asset has exactly one parent: pledging supplies
        either a `gift_agreement_id` (a lifetime gift against an agreement) or
        an `estate_id` (a testamentary asset of an estate) — supplying neither
        or both is rejected with `ERR_ASSET_ORPHAN` (HTTP 422)."

        Design: Corner/entities/gift_asset_orphan_xor_enforced
        """
        deceased = make_deceased_donor(full_name="Dead", date_of_birth="1930-01-01T00:00:00Z")
        estate = make_estate(deceased["id"])
        living = make_donor(full_name="Alive")
        make_active_rate_table()
        agreement = make_draft_agreement(
            living["id"], vehicle_type="BEQUEST", gift_amount_cents=1000000
        )

        resp = api.create_gift_asset(
            create_gift_asset_payload(pledged_value_cents=100000), estate_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_ORPHAN)
        assert resp.status_code == 422

        resp = api.create_gift_asset(
            create_gift_asset_payload(
                pledged_value_cents=100000,
                gift_agreement_id=agreement["id"],
                estate_id=estate["id"],
            ),
            estate_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_ORPHAN)
        assert resp.status_code == 422

        ok = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    pledged_value_cents=100000, gift_agreement_id=agreement["id"]
                ),
                estate_manager_headers,
            ),
            201,
        )
        assert ok["status"] == "PLEDGED"
        assert ok["gift_agreement_id"] == agreement["id"]


class TestAppraisalGate:
    def test_real_estate_liquidation_requires_appraisal(
        self, api, estate_manager_headers
    ):
        """PRD §3.5: "Liquidation moves an asset from `RECEIVED` or `APPRAISED`
        to `LIQUIDATED`, with `gross_proceeds_cents` and `liquidation_costs_cents`
        (defaulting to zero) supplied in the payload; real estate must reach
        `APPRAISED` before it may be liquidated, else
        `ERR_ASSET_KIND_REQUIRES_APPRAISAL` (HTTP 409)."
        PRD §3.5: "Appraisal exists only for real estate: appraising supplies
        `appraised_value_cents` and moves a `RECEIVED` real-estate asset to
        `APPRAISED`; attempting it on cash or securities is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/real_estate_liquidation_requires_appraisal
        """
        donor = make_donor(full_name="Appraisal", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_executed_agreement(donor["id"])
        real_estate = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    gift_agreement_id=agreement["id"],
                    asset_kind="REAL_ESTATE",
                    pledged_value_cents=10000000,
                ),
                estate_manager_headers,
            ),
            201,
        )
        cash = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    gift_agreement_id=agreement["id"],
                    asset_kind="CASH",
                    pledged_value_cents=5000,
                ),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(
                real_estate["id"], {"action": "RECEIVE"}, estate_manager_headers
            )
        )

        # Real estate cannot liquidate straight from RECEIVED.
        resp = api.transition_gift_asset(
            real_estate["id"],
            {
                "action": "LIQUIDATE",
                "gross_proceeds_cents": 10500000,
                "liquidation_costs_cents": 300000,
            },
            estate_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_KIND_REQUIRES_APPRAISAL)
        assert resp.status_code == 409

        # Appraisal exists only for real estate.
        resp = api.transition_gift_asset(
            cash["id"],
            {"action": "APPRAISE", "appraised_value_cents": 5000},
            estate_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        appraised = validate_success(
            api.transition_gift_asset(
                real_estate["id"],
                {"action": "APPRAISE", "appraised_value_cents": 10000000},
                estate_manager_headers,
            )
        )
        assert appraised["status"] == "APPRAISED"

        liquidated = validate_success(
            api.transition_gift_asset(
                real_estate["id"],
                {
                    "action": "LIQUIDATE",
                    "gross_proceeds_cents": 10500000,
                    "liquidation_costs_cents": 300000,
                },
                estate_manager_headers,
            )
        )
        assert liquidated["status"] == "LIQUIDATED"
        assert liquidated["net_proceeds_cents"] == 10200000


class TestSecuritiesFmv:
    def test_securities_fmv_rounding_half_up(self, api, estate_manager_headers):
        """PRD §3.5: "At receipt the system computes `fmv_cents` for securities
        as the mean of the selected high/low pair, rounded half-up to whole
        cents".

        Design: Corner/calculations/securities_fmv_rounding_half_up
        """
        donor = make_donor(full_name="FMV Rounding")
        make_active_rate_table()
        agreement = make_draft_agreement(donor["id"])
        asset = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    gift_agreement_id=agreement["id"],
                    asset_kind="SECURITIES",
                    pledged_value_cents=100000,
                ),
                estate_manager_headers,
            ),
            201,
        )
        received = validate_success(
            api.transition_gift_asset(
                asset["id"],
                {
                    "action": "RECEIVE",
                    "dod_high_price_cents": 100001,
                    "dod_low_price_cents": 100000,
                },
                estate_manager_headers,
            )
        )
        # mean (100001 + 100000) / 2 = 100000.5 rounds half-up to 100001.
        assert received["fmv_cents"] == 100001


class TestReceivedValueReconciliation:
    def test_derived_field_received_value_reconciles(self, api, estate_manager_headers):
        """PRD §3.5: "Every receipt, appraisal, or return recomputes the parent
        agreement's `received_value_cents`: the sum over linked assets whose
        status is `RECEIVED`, `APPRAISED`, `LIQUIDATED`, or `DISTRIBUTED`, where
        a `CASH` asset contributes its `pledged_value_cents`".
        PRD §3.5: "Return moves a `RECEIVED` asset to `RETURNED` and is
        permitted for agreement-linked assets only while the parent agreement
        is `EXECUTED` or `RESCINDED`".

        Design: Corner/cross_cutting_complexity_layers/derived_field_received_value_reconciles
        """
        donor = make_donor(full_name="Reconcile", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_executed_agreement(donor["id"])
        asset = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    gift_agreement_id=agreement["id"], pledged_value_cents=6000000
                ),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(asset["id"], {"action": "RECEIVE"}, estate_manager_headers)
        )
        mid = validate_success(api.get_gift_agreement(agreement["id"], estate_manager_headers))
        assert mid["received_value_cents"] == 6000000
        assert mid["status"] == "EXECUTED"

        validate_success(
            api.transition_gift_asset(asset["id"], {"action": "RETURN"}, estate_manager_headers)
        )
        after = validate_success(api.get_gift_agreement(agreement["id"], estate_manager_headers))
        assert after["received_value_cents"] == 0
        assert after["status"] == "EXECUTED"


class TestEstateSecuritiesBasis:
    def _setup_two_securities_assets(self, api, estate_manager_headers):
        """Deceased donor, NOTIFIED estate, two RECEIVED SECURITIES assets with
        identical date-of-death pairs (100000/90000); the second also carries
        the alternate pair (120000/110000)."""
        donor = make_deceased_donor(
            full_name="Estate Basis",
            date_of_birth="1940-01-01T00:00:00Z",
            deceased_on="2026-08-10T00:00:00Z",
        )
        estate = make_estate(donor["id"], notified_on="2026-08-12T00:00:00Z")
        dod_asset = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    estate_id=estate["id"],
                    asset_kind="SECURITIES",
                    pledged_value_cents=95000,
                ),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(
                dod_asset["id"],
                {
                    "action": "RECEIVE",
                    "dod_high_price_cents": 100000,
                    "dod_low_price_cents": 90000,
                },
                estate_manager_headers,
            )
        )
        alt_asset = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    estate_id=estate["id"],
                    asset_kind="SECURITIES",
                    pledged_value_cents=95000,
                ),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(
                alt_asset["id"],
                {
                    "action": "RECEIVE",
                    "dod_high_price_cents": 100000,
                    "dod_low_price_cents": 90000,
                    "alt_high_price_cents": 120000,
                    "alt_low_price_cents": 110000,
                },
                estate_manager_headers,
            )
        )
        return estate, dod_asset, alt_asset

    def test_dod_basis_before_election_and_retained_without_alt_pair(
        self, api, estate_manager_headers
    ):
        """PRD §3.5: "At receipt the system computes `fmv_cents` for securities
        as the mean of the selected high/low pair, rounded half-up to whole
        cents: agreement-linked assets always use the date-of-death pair, while
        estate-linked assets use the alternate pair once their estate has
        elected alternate valuation; assets missing the alternate pair keep the
        date-of-death basis even after the election."

        Design: Difficulty/dual_variant_calc/estate_securities_dod_vs_alternate_basis
        """
        estate, dod_asset, alt_asset = self._setup_two_securities_assets(
            api, estate_manager_headers
        )
        # Both assets report the DOD mean round_half_up((100000+90000)/2)=95000.
        for asset_id in (dod_asset["id"], alt_asset["id"]):
            data = validate_success(api.get_gift_asset(asset_id, estate_manager_headers))
            assert data["fmv_cents"] == 95000

        validate_success(
            api.transition_estate(
                estate["id"], {"action": "ELECT_ALTERNATE_VALUATION"}, estate_manager_headers
            )
        )
        dod_after = validate_success(
            api.get_gift_asset(dod_asset["id"], estate_manager_headers)
        )
        assert dod_after["fmv_cents"] == 95000

    def test_alternate_basis_applied_after_election(self, api, estate_manager_headers):
        """PRD §3.7: "While an estate is `NOTIFIED` or `PROBATE_OPEN`, the
        `EstateManager` may make the one-way alternate-valuation election
        (`ELECT_ALTERNATE_VALUATION`), permitted only while
        `alternate_valuation_elected` is false. The election changes no status,
        but flips the valuation basis: every linked securities asset not still
        `PLEDGED` has its `fmv_cents` recomputed as the mean of its alternate
        price pair — `alt_high_price_cents` and `alt_low_price_cents` — rounded
        half-up".

        Design: Difficulty/dual_variant_calc/estate_securities_dod_vs_alternate_basis
        """
        estate, _dod_asset, alt_asset = self._setup_two_securities_assets(
            api, estate_manager_headers
        )
        elected = validate_success(
            api.transition_estate(
                estate["id"], {"action": "ELECT_ALTERNATE_VALUATION"}, estate_manager_headers
            )
        )
        assert elected["alternate_valuation_elected"] is True
        assert elected["status"] == "NOTIFIED"

        alt_after = validate_success(
            api.get_gift_asset(alt_asset["id"], estate_manager_headers)
        )
        # Alternate basis: round_half_up((120000+110000)/2) = 115000.
        assert alt_after["fmv_cents"] == 115000
