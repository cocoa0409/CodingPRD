"""SDS consistency, package placarding boundaries, UN-rating, and the
shipment loading dependency (PRD §3.7, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_package_config,
    assert_shipment,
    author_and_issue_sds,
    author_sds,
    create_package_config,
    create_shipment,
    setup_batch_context,
    setup_batch_in_hold_qa,
    setup_completed_batch,
    setup_released_batch,
    validate_error,
    validate_success,
)

SDS_AUTHOR = TEST_USERS["sds_author_headers"]
CLERK = TEST_USERS["shipping_clerk_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestSdsConsistency:
    def test_issue_inconsistent_signal_word_rejected(self, api):
        """PRD §3.7: "the `signal_word` is `DANGER` whenever the
        classification is `FLAMMABLE`, `OXIDIZER`, or `TOXIN`, and is
        `WARNING` or `NONE` otherwise" and "Issuance moves the document from
        `DRAFT` to `ISSUED` and is permitted only while that flag is true —
        an inconsistent document is rejected with `ERR_SDS_INCONSISTENT`
        (HTTP 422)."

        Design: Corner/errors/sds_inconsistent_signal_word_returns_err
        """
        ctx = setup_batch_context(ghs_class="FLAMMABLE", density=0.8,
                                  yield_pct=95, batch_size_l=50)
        sds = author_sds(ctx["customer"]["id"], ctx["batch"]["id"],
                         "FLAMMABLE", signal_word="NONE",
                         hazard_statements=["H225"])
        assert sds["authoring_consistency_flag"] is False

        resp = api.issue_sds(ctx["customer"]["id"], ctx["batch"]["id"],
                             sds["id"], SDS_AUTHOR)
        validate_error(resp, ApiErrorId.ERR_SDS_INCONSISTENT)


class TestPlacardThreshold:
    def _flammable_hold_qa(self, **batch_kw):
        return setup_batch_in_hold_qa(
            ghs_class="FLAMMABLE", density=0.8, yield_pct=95,
            batch_size_l=200, lot_quantity_kg=5000, charge_qty_kg=200,
            **batch_kw)

    def test_placard_not_required_below_threshold(self, api):
        """PRD §3.8: "`placard_required` is true when the classification is
        anything other than `NON_HAZ` and the `total_volume_l` reaches or
        exceeds the 454-litre DOT bulk-packaging threshold" and "When
        placarding is not required, `placard_class` is null."

        Design: Difficulty/combinatorial_formula/placard_threshold_at_454l_boundary
        """
        ctx = self._flammable_hold_qa()
        author_and_issue_sds(ctx["customer"]["id"], ctx["batch"]["id"],
                             "FLAMMABLE")

        # 1 drum = 205 L < 454: no placard.
        drum = create_package_config(ctx["customer"]["id"], ctx["batch"]["id"],
                                     package_type="DRUM_205L", un_rated=True,
                                     package_count=1)
        assert_package_config(drum)
        assert drum["total_volume_l"] == 205
        assert drum["placard_required"] is False
        assert drum["placard_class"] is None

        # 22 pails = 440 L < 454: still no placard, just under the line.
        ctx2 = self._flammable_hold_qa()
        author_and_issue_sds(ctx2["customer"]["id"], ctx2["batch"]["id"],
                             "FLAMMABLE")
        pails = create_package_config(ctx2["customer"]["id"],
                                      ctx2["batch"]["id"],
                                      package_type="PAIL_20L", un_rated=True,
                                      package_count=22)
        assert pails["total_volume_l"] == 440
        assert pails["placard_required"] is False
        assert pails["placard_class"] is None

    def test_placard_required_at_or_above_threshold(self, api):
        """PRD §3.8: "`placard_required` is true when the classification is
        anything other than `NON_HAZ` and the `total_volume_l` reaches or
        exceeds the 454-litre DOT bulk-packaging threshold — a configuration
        of exactly 454 litres therefore does require placarding. When
        required, `placard_class` is assigned from the classification:
        `FLAMMABLE` maps to `CLASS_3_FLAMMABLE`".

        Design: Difficulty/combinatorial_formula/placard_threshold_at_454l_boundary
        """
        ctx = self._flammable_hold_qa()
        author_and_issue_sds(ctx["customer"]["id"], ctx["batch"]["id"],
                             "FLAMMABLE")
        # 23 pails = 460 L >= 454: placarding required.
        pails = create_package_config(ctx["customer"]["id"],
                                      ctx["batch"]["id"],
                                      package_type="PAIL_20L", un_rated=True,
                                      package_count=23)
        assert_package_config(pails)
        assert pails["total_volume_l"] == 460
        assert pails["placard_required"] is True
        assert pails["placard_class"] == "CLASS_3_FLAMMABLE"


class TestUnRatedPackaging:
    def test_un_rated_package_for_hazmat_rejected(self, api):
        """PRD §3.8: "UN-rated packaging is mandatory whenever the batch's
        classification is anything other than `NON_HAZ`; the requirement is
        enforced both when the configuration is created and again at batch
        completion, and a violation is rejected with
        `ERR_UN_RATED_PACKAGE_REQUIRED`."

        Design: Corner/errors/un_rated_package_for_hazmat_returns_err
        """
        ctx = setup_batch_in_hold_qa(ghs_class="FLAMMABLE", density=0.8,
                                     yield_pct=95, batch_size_l=100,
                                     lot_quantity_kg=500, charge_qty_kg=80)
        author_and_issue_sds(ctx["customer"]["id"], ctx["batch"]["id"],
                             "FLAMMABLE")
        resp = api.create_package_config(
            ctx["customer"]["id"], ctx["batch"]["id"],
            {"package_type": "DRUM_205L", "un_rated": False,
             "package_count": 1},
            CLERK)
        validate_error(resp, ApiErrorId.ERR_UN_RATED_PACKAGE_REQUIRED)


class TestShipmentLoadingDependency:
    def test_start_loading_before_batch_completed_rejected(self, api):
        """PRD §3.8: "Loading may start — moving the shipment from `PLANNED`
        to `LOADING` — only once the batch itself stands at `COMPLETED`, and
        any attempt earlier is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/shipment_loading_depends_on_batch_completed
        """
        ctx = setup_released_batch()
        assert ctx["batch"]["status"] == "RELEASED"
        shipment = create_shipment(ctx["customer"]["id"], ctx["batch"]["id"],
                                   carrier_name="ChemTrans LLC",
                                   vehicle_placards=[],
                                   departure_at="2026-11-01T14:00:00Z")
        assert shipment["status"] == "PLANNED"

        resp = api.start_loading(ctx["customer"]["id"], ctx["batch"]["id"],
                                 CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        shipments = validate_success(api.get_shipment(
            ctx["customer"]["id"], ctx["batch"]["id"], QM))
        listing = shipments if isinstance(shipments, list) else [shipments]
        assert listing[0]["status"] == "PLANNED", "Rejected start-loading leaves PLANNED"

    def test_start_loading_after_batch_completed_succeeds(self, api):
        """PRD §3.8: "Loading may start — moving the shipment from `PLANNED`
        to `LOADING` — only once the batch itself stands at `COMPLETED`, and
        any attempt earlier is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/shipment_loading_depends_on_batch_completed
        """
        ctx = setup_completed_batch(actual_output_kg=95, charge_qty_kg=100,
                                    heel_returned_kg=5)
        assert ctx["batch"]["status"] == "COMPLETED"
        shipment = create_shipment(ctx["customer"]["id"], ctx["batch"]["id"])
        resp = api.start_loading(ctx["customer"]["id"], ctx["batch"]["id"],
                                 CLERK)
        loading = validate_success(resp)
        assert_shipment(loading)
        assert loading["status"] == "LOADING"
