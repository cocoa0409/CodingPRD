"""Postage and service-level penalty each computed twice from one rate structure.

Both quantities in this module are specified as a pair of variants over the same
inputs, and the point of each test is that the two variants land on different
figures for one and the same row.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.test_users import POSTAGE_USER_ID


MARKETING_THREE_DIGIT_GROSS = a.expected_gross_postage_cents(
    "MARKETING", "THREE_DIGIT", 1
)


def _marketing_pair_verified(api: ApiClient):
    """A verified job of two marketing pieces that presort into one THREE_DIGIT
    batch, with the escrow funded and an entry facility discounting 850 bp."""
    pipeline = fx.verified_job(
        api,
        client_code="CLPV",
        client_overrides={"name": "Pinecrest Variance Mutual"},
        fund_cents=100000,
        template_code="T-PV",
        template_overrides={"mail_class_preference": "MARKETING", "sheets_per_document": 1},
        press_line_code="PL-PV",
        press_line_overrides={"sheets_per_hour": 600, "daily_sheet_capacity": 9000},
        with_facility=True,
        facility_code="EF-PV",
        facility_overrides={"discount_bp_marketing": 850, "discount_bp_first_class": 850},
        file_name="pv-cycle-01.csv",
        specs=fx.record_specs(2, statement_amount_cents=100000),
    )
    assert pipeline.job["status"] == "VERIFIED"
    return pipeline


class TestPostageEstimateAndManifestVariants:
    """The estimated variant at seal against the manifested variant at induction."""

    def test_seal_estimate_counts_every_non_void_piece_at_undiscounted_gross(
        self, api: ApiClient
    ):
        """PRD §3.8: "The estimated variant of the postage computation then runs:
        `estimated_postage_cents` is the sum, over every piece of the batch whose
        `piece_status` is not `VOID`, of that piece's gross postage."

        At seal no entry facility has been chosen, so the estimate is the sum of
        gross postage over every non-void piece with no discount and no per-piece
        rounding.

        Design: Difficulty/dual_variant_calc/postage_estimate_and_manifest_variants_diverge_on_one_batch
        """
        pipeline = _marketing_pair_verified(api)
        batch = pipeline.batch
        assert batch["mail_class"] == "MARKETING"
        assert batch["presort_bucket"] == "THREE_DIGIT"
        assert batch["piece_count"] == 2
        assert batch["tray_count"] == a.expected_tray_count(2) == 1
        assert batch["estimated_postage_cents"] is None
        assert batch["manifested_postage_cents"] is None
        assert batch["postage_variance_cents"] is None

        client_before = pipeline.refresh_client()
        sealed = fx.seal_batch(api, batch["id"], client_before["version"])

        assert sealed["status"] == "SEALED"
        assert sealed["estimated_postage_cents"] == 2 * MARKETING_THREE_DIGIT_GROSS == 60
        assert sealed["sealed_by_user_id"] == POSTAGE_USER_ID
        assert sealed["manifested_postage_cents"] is None
        assert sealed["postage_variance_cents"] is None

        client_after = pipeline.refresh_client()
        assert client_after["postage_committed_cents"] == 60
        assert client_after["postage_escrow_available_cents"] == 99940
        a.assert_escrow_conserved(client_before, client_after, 60)

    def test_manifest_discounts_and_rounds_once_per_piece_before_summing(
        self, api: ApiClient
    ):
        """PRD §3.8: "Second, the discount is applied **per piece** — a piece's net postage
        is its gross postage multiplied by the quantity ten thousand minus the
        applicable discount in basis points, divided by 10,000, and rounded half up to
        whole cents."

        The manifested variant discounts each piece by the facility rate,
        rounds each piece half up, and only then sums, so it lands on 54 where a
        single rounding of the batch gross would land on 55.

        Design: Difficulty/dual_variant_calc/postage_estimate_and_manifest_variants_diverge_on_one_batch
        """
        pipeline = _marketing_pair_verified(api)
        batch = pipeline.batch
        fx.seal_batch(api, batch["id"], pipeline.refresh_client()["version"])

        manifested = fx.manifest_batch(
            api,
            batch["id"],
            pipeline.facility["id"],
            "2026-08-03T08:00:00Z",
            "2026-08-03T12:00:00Z",
        )

        per_piece_net = a.expected_net_postage_cents(MARKETING_THREE_DIGIT_GROSS, 850)
        assert per_piece_net == 27
        assert manifested["status"] == "MANIFESTED"
        assert manifested["manifested_postage_cents"] == 2 * per_piece_net == 54
        assert manifested["estimated_postage_cents"] == 60
        assert manifested["postage_variance_cents"] == 54 - 60 == -6
        assert manifested["manifested_postage_cents"] != manifested[
            "estimated_postage_cents"
        ], "the estimated and manifested variants must diverge on identical piece data"

        rounded_once_on_the_batch = a.expected_net_postage_cents(
            2 * MARKETING_THREE_DIGIT_GROSS, 850
        )
        assert rounded_once_on_the_batch == 55
        assert manifested["manifested_postage_cents"] != rounded_once_on_the_batch, (
            "rounding the batch total once instead of each piece is observable"
        )

    def test_manifest_variance_settles_the_escrow_and_bubbles_the_job_up(
        self, api: ApiClient
    ):
        """PRD §3.8: "The client's `postage_committed_cents` is increased by
        `postage_variance_cents` and its `postage_escrow_available_cents` decreased by
        the same signed amount, with the client's `version` incremented by 1 — so a
        negative variance, the ordinary outcome when the facility discount bites,
        returns escrow to the client."

        The negative variance returns escrow to the client, and because the
        batch was the job's only batch the job bubbles up to MANIFESTED.

        Design: Difficulty/dual_variant_calc/postage_estimate_and_manifest_variants_diverge_on_one_batch
        """
        pipeline = _marketing_pair_verified(api)
        batch = pipeline.batch
        fx.seal_batch(api, batch["id"], pipeline.refresh_client()["version"])
        fx.manifest_batch(
            api,
            batch["id"],
            pipeline.facility["id"],
            "2026-08-03T08:00:00Z",
            "2026-08-03T12:00:00Z",
        )

        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 54
        assert client["postage_escrow_available_cents"] == 99946
        assert client["postage_deposited_cents"] == 100000
        a.assert_escrow_ledger(client)

        assert pipeline.refresh_job()["status"] == "MANIFESTED"


def _southline_job(api: ApiClient):
    """A two-piece first-class job whose file is accepted at 2026-08-01T08:00:00Z
    under a 96-hour turnaround, scheduled into a window that already misses that
    deadline."""
    fx.set_clock(api, "2026-08-01T08:00:00Z")
    client = fx.register_client(
        api,
        client_code="CLSL",
        name="Southline Savings Trust",
        sla_turnaround_hours=96,
        sla_penalty_rate_cents_per_hour=2500,
        sla_penalty_cap_cents=500000,
        dr_readiness_required=False,
    )
    template = fx.create_active_template(
        api,
        client["id"],
        template_code="T-SL",
        mail_class_preference="FIRST_CLASS",
        sheets_per_document=1,
    )
    line = fx.register_press_line(
        api, line_code="PL-SL", sheets_per_hour=600, daily_sheet_capacity=9000
    )
    facility = fx.register_entry_facility(
        api,
        facility_code="EF-SL",
        facility_type="NDC",
        discount_bp_first_class=0,
        discount_bp_marketing=0,
    )
    bundle = fx.accepted_file(
        api,
        client["id"],
        fx.record_specs(2, statement_amount_cents=100000),
        file_name="sl-cycle-01.csv",
    )
    job = fx.compose_job(api, bundle.id, template["id"])
    job = fx.presort_job(api, job["id"])
    pieces = fx.list_pieces(api, job["id"])
    batches = fx.list_batches(api, job["id"])
    fx.set_clock(api, "2026-08-06T08:00:00Z")
    run = fx.schedule_job(api, job["id"], "2026-08-06T09:00:00Z", line["id"])
    return {
        "client": client,
        "template": template,
        "line": line,
        "facility": facility,
        "bundle": bundle,
        "job": fx.read_job(api, job["id"]),
        "pieces": pieces,
        "batch": batches[0],
        "run": run,
    }


def _southline_held(api: ApiClient, ctx):
    """Carry the Southline job to INTEGRITY_HELD at 2026-08-06T11:00:00Z with its
    second piece never read at induction."""
    fx.set_clock(api, "2026-08-06T09:00:00Z")
    fx.start_run(api, ctx["run"]["id"])
    first, second = ctx["pieces"]
    fx.scan_piece_fully(api, first)
    fx.scan_stage(api, second["id"], "PRINT", second["imb_barcode"])
    fx.scan_stage(api, second["id"], "INSERT", second["imb_barcode"])
    fx.set_clock(api, "2026-08-06T10:00:00Z")
    fx.complete_run(api, ctx["run"]["id"])
    fx.set_clock(api, "2026-08-06T11:00:00Z")
    return fx.reconcile(api, ctx["job"]["id"])


def _southline_closed(api: ApiClient, ctx):
    """Reprint the unread piece an hour into the hold, scan the replacement
    clean, manifest the batch and close the job at 2026-08-06T14:00:00Z."""
    held = _southline_held(api, ctx)
    fx.set_clock(api, "2026-08-06T12:00:00Z")
    replacement = fx.reprint_piece(
        api, ctx["pieces"][1]["id"], held["version"], "MISSING_INDUCT_SCAN"
    )
    fx.scan_piece_fully(api, replacement)
    fx.reconcile(api, ctx["job"]["id"])
    client = fx.fund_client(api, ctx["client"]["id"], 100000)
    fx.seal_batch(api, ctx["batch"]["id"], client["version"])
    fx.manifest_batch(
        api,
        ctx["batch"]["id"],
        ctx["facility"]["id"],
        "2026-08-06T13:00:00Z",
        "2026-08-06T13:30:00Z",
    )
    fx.set_clock(api, "2026-08-06T14:00:00Z")
    return fx.close_job(api, ctx["job"]["id"])


class TestSlaProjectedAndAssessedVariants:
    """The projected exposure written at scheduling against the penalty actually
    assessed at closure."""

    def test_projected_penalty_reads_the_projected_completion_instant(
        self, api: ApiClient
    ):
        """PRD §3.8: "The **projected** variant, written at scheduling, takes the number of
        minutes from `sla_due_at` to `projected_completion_at`, floored at zero, and
        knows nothing about integrity holds; it is written once and never recomputed."

        Scheduling writes projected_completion_at as the run window end plus the
        120-minute fulfilment lag and prices the projected variant off it, knowing
        nothing about integrity holds.

        Design: Difficulty/dual_variant_calc/sla_projected_and_assessed_variants_diverge_on_one_job
        """
        ctx = _southline_job(api)
        job = ctx["job"]

        a.assert_instant(
            ctx["bundle"].data_file["accepted_at"],
            "2026-08-01T08:00:00Z",
            "data_file.accepted_at",
        )
        a.assert_instant(job["sla_due_at"], "2026-08-05T08:00:00Z", "job.sla_due_at")
        a.assert_instant(
            ctx["run"]["window_end"], "2026-08-06T10:00:00Z", "run.window_end"
        )
        a.assert_instant(
            job["projected_completion_at"],
            "2026-08-06T12:00:00Z",
            "job.projected_completion_at",
        )
        assert job["projected_penalty_cents"] == 70000
        assert job["sla_hold_minutes"] == 0
        assert job["assessed_penalty_cents"] is None

    def test_assessed_penalty_credits_the_accrued_hold_minutes(self, api: ApiClient):
        """PRD §3.8: "The **assessed** variant, written at closure, takes the number of
        minutes from `sla_due_at` to `sla_completed_at`, subtracts the job's accumulated
        `sla_hold_minutes`, and floors the result at zero — so a job held for a genuine
        integrity investigation is credited for that hold, and the two variants diverge
        precisely when a reprint occurred."

        Closure measures lateness from the deadline to the real completion
        instant and subtracts the accrued hold, so the assessed variant lands on
        72500 where the projected variant read 70000 and an uncredited hold would
        have read 75000.

        Design: Difficulty/dual_variant_calc/sla_projected_and_assessed_variants_diverge_on_one_job
        """
        ctx = _southline_job(api)
        closed = _southline_closed(api, ctx)

        assert closed["status"] == "CLOSED"
        assert closed["sla_hold_minutes"] == 60
        a.assert_instant(
            closed["sla_completed_at"],
            "2026-08-06T14:00:00Z",
            "job.sla_completed_at",
        )
        assert closed["assessed_penalty_cents"] == 72500
        assert closed["projected_penalty_cents"] == 70000
        assert closed["assessed_penalty_cents"] != closed["projected_penalty_cents"], (
            "the two penalty variants must diverge once a hold has accrued"
        )
        uncredited = a.ceil_div(1800, 60) * 2500
        assert uncredited == 75000
        assert closed["assessed_penalty_cents"] != uncredited, (
            "the hold credit is observable in the assessed figure"
        )

    def test_reprint_leaves_the_invoice_bases_untouched(self, api: ApiClient):
        """PRD §3.8: "Only billable pieces feed the sheet bases, so a reprint replacement
        contributes nothing while the voided original it replaced remains billable — a
        reprint therefore never changes the invoice."

        The voided original stays billable while its replacement is not, so the
        sheet bases and the invoice are exactly what they were before the reprint.

        Design: Difficulty/dual_variant_calc/sla_projected_and_assessed_variants_diverge_on_one_job
        """
        ctx = _southline_job(api)
        closed = _southline_closed(api, ctx)

        assert closed["total_sheet_count"] == 2
        assert closed["billing_total_cents"] == 18
        assert closed["accountable_piece_count"] == 2
        assert closed["void_piece_count"] == 1
        assert closed["reprint_piece_count"] == 1
