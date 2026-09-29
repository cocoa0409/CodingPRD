"""Composite formulas whose input order, rounding position and penalty terms are
all part of the contract.

Each test drives one figure that is built from several independent inputs and
pins the arithmetic that a simpler reading of the same rule would get wrong.
"""

import pytest

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient


class TestManifestedPostageRoundsPerPiece:
    """Two identical mixed-AADC first-class pieces, discounted at 850 bp."""

    @staticmethod
    def _sealed_midbrook(api: ApiClient):
        pipeline = fx.sealed_batches(
            api,
            client_code="CLMB",
            client_overrides={"name": "Midbrook Card Services"},
            template_code="T-MB",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 3,
            },
            press_line_code="PL-MB",
            press_line_overrides={"sheets_per_hour": 600, "daily_sheet_capacity": 9000},
            with_facility=True,
            facility_code="EF-MB",
            facility_overrides={
                "discount_bp_first_class": 850,
                "discount_bp_marketing": 400,
            },
            file_name="mb-cycle-01.csv",
            specs=[
                fx.record_spec(
                    "ABC2001",
                    1,
                    50000,
                    address_line1="410 Lexington Avenue",
                    city="New York",
                    region_code="NY",
                    postal_code="10001",
                    postal_code_plus4="1234",
                ),
                fx.record_spec(
                    "ABC2002",
                    2,
                    50000,
                    address_line1="88 Spear Street",
                    city="San Francisco",
                    region_code="CA",
                    postal_code="94105",
                    postal_code_plus4="5678",
                ),
            ],
        )
        return pipeline

    def test_estimated_postage_sums_the_base_and_surcharge_of_every_piece(
        self, api: ApiClient
    ):
        """PRD §3.8: "On top of the base each piece attracts a weight surcharge: the first
        3 sheets travel free, and every sheet beyond the third costs a further 3 cents,
        so the surcharge is the piece's `sheet_count` less 3, floored at zero,
        multiplied by 3 cents."

        Each piece's gross is a table lookup on mail class and bucket plus a
        surcharge on the sheets beyond the third, and the estimate is those gross
        figures summed with no discount and no rounding.

        Design: Difficulty/combinatorial_formula/manifested_postage_rounds_per_piece_before_summing
        """
        pipeline = self._sealed_midbrook(api)
        batch = pipeline.batch

        assert batch["mail_class"] == "FIRST_CLASS"
        assert batch["presort_bucket"] == "MIXED_AADC"
        assert batch["piece_count"] == 2
        for piece in pipeline.pieces:
            assert piece["sheet_count"] == 3
            assert a.expected_gross_postage_cents("FIRST_CLASS", "MIXED_AADC", 3) == 62
        assert batch["estimated_postage_cents"] == 124

    def test_manifested_postage_rounds_each_piece_before_the_sum(self, api: ApiClient):
        """PRD §3.8: "Second, the discount is applied **per piece** — a piece's net postage
        is its gross postage multiplied by the quantity ten thousand minus the
        applicable discount in basis points, divided by 10,000, and rounded half up to
        whole cents."

        Discounting and rounding each piece before summing yields 114, one cent
        above the 113 that a single rounding of the batch gross would produce.

        Design: Difficulty/combinatorial_formula/manifested_postage_rounds_per_piece_before_summing
        """
        pipeline = self._sealed_midbrook(api)
        manifested = fx.manifest_batch(
            api,
            pipeline.batch["id"],
            pipeline.facility["id"],
            "2026-08-03T08:00:00Z",
            "2026-08-03T12:00:00Z",
        )

        per_piece = a.expected_net_postage_cents(62, 850)
        assert per_piece == 57
        assert manifested["manifested_postage_cents"] == 2 * per_piece == 114
        assert manifested["postage_variance_cents"] == -10

        batch_rounded_once = a.expected_net_postage_cents(124, 850)
        assert batch_rounded_once == 113
        assert manifested["manifested_postage_cents"] != batch_rounded_once, (
            "the per-piece rounding position is observable and lands above a "
            "single rounding of the batch total"
        )

    def test_manifested_figure_is_what_the_client_escrow_carries(self, api: ApiClient):
        """PRD §3.8: "The client's `postage_committed_cents` is increased by
        `postage_variance_cents` and its `postage_escrow_available_cents` decreased by
        the same signed amount, with the client's `version` incremented by 1 — so a
        negative variance, the ordinary outcome when the facility discount bites,
        returns escrow to the client."

        The variance is booked against the client, so the committed leg ends on
        the manifested figure rather than the estimate.

        Design: Difficulty/combinatorial_formula/manifested_postage_rounds_per_piece_before_summing
        """
        pipeline = self._sealed_midbrook(api)
        fx.manifest_batch(
            api,
            pipeline.batch["id"],
            pipeline.facility["id"],
            "2026-08-03T08:00:00Z",
            "2026-08-03T12:00:00Z",
        )

        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 114
        assert client["postage_escrow_available_cents"] == 99886
        a.assert_escrow_ledger(client)


class TestBillingDiscountTierKey:
    """A twelve-sheet insert-bearing job whose subtotal sits one tier above the
    figure its own discount would have keyed."""

    @staticmethod
    def _closed_bridgecrest(api: ApiClient):
        fx.set_clock(api)
        fx.register_insert_stock(
            api,
            insert_code="REG-BC",
            description="Annual privacy notice",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
            sheets_per_insert=2,
            received_count=100,
        )
        pipeline = fx.closed_job(
            api,
            clock=None,
            client_code="CLBC",
            client_overrides={"name": "Bridgecrest Utilities"},
            template_code="T-BC",
            template_overrides={
                "sheets_per_document": 10,
                "required_insert_codes": ["REG-BC"],
                "mail_class_preference": "FIRST_CLASS",
            },
            press_line_code="PL-BC",
            press_line_overrides={"sheets_per_hour": 600, "daily_sheet_capacity": 9000},
            facility_code="EF-BC",
            facility_overrides={
                "facility_type": "DDU",
                "discount_bp_first_class": 0,
                "discount_bp_marketing": 0,
            },
            file_name="bc-cycle-01.csv",
            specs=fx.record_specs(2, statement_amount_cents=70000),
            rush_requested=False,
        )
        return pipeline

    def test_composition_writes_the_two_sheet_bases_the_invoice_consumes(
        self, api: ApiClient
    ):
        """PRD §3.4: "Three billing bases are summed over **billable** pieces only, that is
        pieces whose `billable` is true: `total_sheet_count` is the sum of
        `sheet_count`, `insert_sheet_total` is the sum of `insert_sheet_count`, and the
        job's own `color_page_count` is the sum of the pieces' `color_page_count`."

        Each piece carries the template's ten sheets plus the two sheets its one
        insert contributes, and the job's billing bases sum those figures over its
        billable pieces.

        Design: Difficulty/combinatorial_formula/billing_discount_tier_keyed_on_pre_discount_subtotal
        """
        pipeline = self._closed_bridgecrest(api)

        for piece in pipeline.pieces:
            assert piece["sheet_count"] == 12
            assert piece["insert_sheet_count"] == 2
            assert piece["insert_codes"] == ["REG-BC"]
        job = pipeline.job
        assert job["total_sheet_count"] == 24
        assert job["insert_sheet_total"] == 4
        assert pipeline.batch["estimated_postage_cents"] == 166

    def test_volume_discount_tier_is_keyed_on_the_pre_discount_subtotal(
        self, api: ApiClient
    ):
        """PRD §3.8: "Step four looks up a volume discount rate keyed **on
        `pre_discount_subtotal_cents` alone**: a pre-discount subtotal of 400 cents or
        more earns 1,200 basis points; failing that, 230 cents or more earns 800 basis
        points; failing that, 200 cents or more earns 400 basis points; and anything
        below 200 cents earns nothing."

        The tier is selected from the step-three subtotal of 232 cents, which
        earns 800 basis points; re-keying it on the discounted figure would select
        400 basis points and land the invoice on 223 instead of 213.

        Design: Difficulty/combinatorial_formula/billing_discount_tier_keyed_on_pre_discount_subtotal
        """
        pipeline = self._closed_bridgecrest(api)
        job = pipeline.job

        assert job["status"] == "CLOSED"
        assert job["composition_charge_cents"] == 216
        assert job["insert_charge_cents"] == 16
        assert job["pre_discount_subtotal_cents"] == 232
        assert job["volume_discount_cents"] == a.round_half_up_int(232 * 800 / 10000) == 19
        assert job["expedite_fee_cents"] == 0
        assert job["billing_total_cents"] == 213

        rekeyed_on_the_discounted_figure = 232 - a.round_half_up_int(213 * 400 / 10000)
        assert rekeyed_on_the_discounted_figure == 223
        assert job["billing_total_cents"] != rekeyed_on_the_discounted_figure, (
            "the discount tier must be keyed on the pre-discount subtotal"
        )


class TestPressLineSelectionScore:
    """Four commissioned lines, one duplex requirement and a surplus penalty that
    flips the winner."""

    @staticmethod
    def _parkside_presorted(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLPS",
            name="Parkside Insurance Group",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-PS",
            duplex_required=True,
            sheets_per_document=1,
            color_pages_per_document=0,
        )
        lines = {
            "PL-ALPHA": fx.register_press_line(
                api,
                line_code="PL-ALPHA",
                capabilities=["DUPLEX", "COLOR", "INSERT"],
                sheets_per_hour=600,
                daily_sheet_capacity=6600,
            ),
            "PL-DELTA": fx.register_press_line(
                api,
                line_code="PL-DELTA",
                capabilities=["DUPLEX"],
                sheets_per_hour=400,
                daily_sheet_capacity=6600,
            ),
            "PL-GAMMA": fx.register_press_line(
                api,
                line_code="PL-GAMMA",
                capabilities=["COLOR"],
                sheets_per_hour=2000,
                daily_sheet_capacity=20000,
            ),
            "PL-ECHO": fx.register_press_line(
                api,
                line_code="PL-ECHO",
                capabilities=["DUPLEX"],
                sheets_per_hour=2000,
                daily_sheet_capacity=20000,
                status="MAINTENANCE",
            ),
        }
        bundle = fx.accepted_file(
            api,
            client["id"],
            fx.record_specs(2, statement_amount_cents=30000),
            file_name="ps-cycle-01.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        job = fx.presort_job(api, job["id"])
        return client, lines, job

    def test_surplus_capability_penalty_flips_the_winner(self, api: ApiClient):
        """PRD §3.6: "The score is headroom weighted at 6,000 basis points — that is,
        headroom multiplied by 6,000 and divided by 10,000 — plus the line's
        `sheets_per_hour` weighted at 4,000 basis points, minus 500 points for each
        surplus capability, with the whole result rounded half up to two decimal
        places."

        The slower, exactly-capable line wins at 4120.00 because the faster line
        forfeits 500 points for each of the two capabilities the job does not
        require, dropping its 4200.00 raw score to 3200.00.

        Design: Difficulty/combinatorial_formula/press_line_selection_scores_headroom_speed_and_capability_surplus
        """
        _client, lines, job = self._parkside_presorted(api)

        run = fx.schedule_job(api, job["id"], "2026-08-02T09:00:00Z")

        assert run["press_line_id"] == lines["PL-DELTA"]["id"]
        assert run["selection_mode"] == "SELECTED"
        expected = a.expected_selection_score(6600, 400, 0)
        assert expected == pytest.approx(4120.00, abs=0.01)
        assert run["selection_score"] == pytest.approx(4120.00, abs=0.01)

        alpha_score = a.expected_selection_score(6600, 600, 2)
        assert alpha_score == pytest.approx(3200.00, abs=0.01)
        unpenalised_alpha = a.expected_selection_score(6600, 600, 0)
        assert unpenalised_alpha == pytest.approx(4200.00, abs=0.01)
        assert alpha_score < expected < unpenalised_alpha

    def test_lines_failing_an_eligibility_predicate_are_invisible(
        self, api: ApiClient
    ):
        """PRD §3.6: "If no line survives every eligibility predicate the request is
        refused with `ERR_NO_ELIGIBLE_PRESS_LINE` (HTTP 409); a line in `MAINTENANCE` is
        simply invisible to the selector."

        A line without the required capability and a line under maintenance take
        no part in the selection, even though either would outscore every eligible
        line, and only the chosen line takes the committed sheets.

        Design: Difficulty/combinatorial_formula/press_line_selection_scores_headroom_speed_and_capability_surplus
        """
        _client, lines, job = self._parkside_presorted(api)

        run = fx.schedule_job(api, job["id"], "2026-08-02T09:00:00Z")

        assert run["press_line_id"] == lines["PL-DELTA"]["id"]
        for excluded in ("PL-ALPHA", "PL-GAMMA", "PL-ECHO"):
            line = fx.read_press_line(api, lines[excluded]["id"])
            assert line["committed_sheet_count"] == 0
            assert line["utilization_bp"] == 0
        chosen = fx.read_press_line(api, lines["PL-DELTA"]["id"])
        assert chosen["committed_sheet_count"] == 2
        a.assert_press_ledger(chosen)

    def test_window_sizing_floors_the_run_at_the_minimum(self, api: ApiClient):
        """PRD §3.6: "The run's `run_minutes` is the larger of a 60-minute minimum and the
        quotient of `planned_sheet_count` multiplied by 60 divided by the line's
        `sheets_per_hour`, that quotient being rounded up to the next whole minute."

        Two sheets on a 400-sheet-an-hour line would need one minute, so the
        60-minute floor decides the window and the run opens as planned.

        Design: Difficulty/combinatorial_formula/press_line_selection_scores_headroom_speed_and_capability_surplus
        """
        _client, _lines, job = self._parkside_presorted(api)

        run = fx.schedule_job(api, job["id"], "2026-08-02T09:00:00Z")

        assert run["planned_sheet_count"] == 2
        assert run["run_minutes"] == a.expected_run_minutes(2, 400) == 60
        a.assert_instant(run["window_start"], "2026-08-02T09:00:00Z", "run.window_start")
        a.assert_instant(run["window_end"], "2026-08-02T10:00:00Z", "run.window_end")
        assert run["status"] == "PLANNED"
        assert fx.read_job(api, job["id"])["status"] == "SCHEDULED"
