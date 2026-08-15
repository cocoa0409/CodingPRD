"""Field fixes and backcharges: pinned per-line rounding, the approve-time
backcharge cascade, the fiscal cap, the state-over-fiscal ladder, and the
resolve gate."""
from test_helpers import (
    ADMIN,
    FOREMAN,
    GC_PM,
    ApiErrorId,
    api_client,
    approve_field_fix,
    create_drawing,
    create_field_fix,
    create_job,
    create_piece,
    create_sequence,
    create_shipped_piece,
    get_backcharge_for_fix,
    respond_backcharge,
    setup_approved_fix_with_backcharge,
    setup_fabrication_ready,
    settle_backcharge,
    validate_error,
    validate_success,
)

# Two lines of 2.5 h at 3333 cents/h: per-line labor rounds to 8333 each.
ROUNDING_LINES = [
    {"labor_hours": 2.5, "labor_rate_cents": 3333, "material_cents": 0},
    {"labor_hours": 2.5, "labor_rate_cents": 3333, "material_cents": 0},
]

# 10 h at 10000 cents/h plus 5000 material: subtotal 105000, markup 15750.
CASCADE_LINES = [
    {"labor_hours": 10, "labor_rate_cents": 10000, "material_cents": 5000},
]

# 1 h at 100 cents: subtotal 100, markup 15, amount 115.
SMALL_LINES = [{"labor_hours": 1, "labor_rate_cents": 100, "material_cents": 0}]


class TestBackchargeRoundingOrder:

    def _approved_fix(self, name="Job R", lines=ROUNDING_LINES):
        ctx = setup_fabrication_ready(name)
        piece, _load = create_shipped_piece(ctx, "R-P1", 1000)
        fix = create_field_fix(ctx["job"]["id"], piece["id"], lines,
                               description="Misaligned shear tab")
        return ctx, fix

    def test_amount_uses_per_line_rounding(self):
        """PRD section 3.8: "The amount is computed in a pinned rounding order.
        For each repair line, the labor component is the line's `labor_hours`
        multiplied by its `labor_rate_cents`, rounded half up to whole cents;
        the line total is that rounded labor component plus the line's
        `material_cents`. The subtotal is the plain sum of all line totals. The
        markup is fifteen percent of the subtotal, rounded half up to whole
        cents. The fix's `amount_cents` is the subtotal plus the markup.
        Rounding labor only once after summing across lines — or computing the
        markup on unrounded labor — produces different cents and is not
        permitted."

        Design: Difficulty/combinatorial_formula/backcharge_per_line_rounding_order
        """
        _ctx, fix = self._approved_fix()
        resp = api_client.approve_field_fix(fix["id"], GC_PM)
        approved = validate_success(resp)
        # Per-line: round(2.5 * 3333) = 8333 each; subtotal 16666;
        # markup round(16666 * 0.15) = 2500; total 19166.
        assert approved["amount_cents"] == 19166, (
            f"per-line rounding then markup must yield 19166, "
            f"got {approved['amount_cents']}"
        )
        assert approved["status"] == "APPROVED"

    def test_backcharge_created_with_computed_amount(self):
        """PRD section 3.8: "The same approval creates the money claim: a
        backcharge springs into existence in `PENDING` status with its
        `amount_cents` copied from the fix's freshly computed `amount_cents`,
        its `field_fix_id` pointing at the fix, and its `job_id` copied from
        the fix's job; the job's `pending_backcharge_cents` is recomputed to
        include it."

        Design: Difficulty/combinatorial_formula/backcharge_per_line_rounding_order
        """
        ctx, fix = self._approved_fix("Job R2")
        approve_field_fix(fix["id"])
        backcharge = get_backcharge_for_fix(fix["id"])
        assert backcharge["status"] == "PENDING"
        assert backcharge["amount_cents"] == 19166, (
            f"the backcharge must copy the fix's computed amount, "
            f"got {backcharge['amount_cents']}"
        )
        assert backcharge["field_fix_id"] == fix["id"]
        assert backcharge["job_id"] == ctx["job"]["id"]


class TestApproveCascade:

    def _approved_fix(self, name="Job F"):
        ctx = setup_fabrication_ready(name)
        piece, _load = create_shipped_piece(ctx, "F-P1", 1000)
        fix = create_field_fix(ctx["job"]["id"], piece["id"], CASCADE_LINES,
                               description="Clip angle rework")
        return ctx, fix

    def test_approve_creates_pending_backcharge(self):
        """PRD section 3.8: "The same approval creates the money claim: a
        backcharge springs into existence in `PENDING` status with its
        `amount_cents` copied from the fix's freshly computed `amount_cents`,
        its `field_fix_id` pointing at the fix, and its `job_id` copied from
        the fix's job; the job's `pending_backcharge_cents` is recomputed to
        include it. The fix itself moves from `PRICED` to `APPROVED`."

        Design: Difficulty/transitive_cascade/field_fix_approve_backcharge_cascade
        """
        _ctx, fix = self._approved_fix()
        approved, backcharge = approve_field_fix(fix["id"])
        assert approved["status"] == "APPROVED"
        # subtotal 105000; markup round(105000 * 0.15) = 15750; total 120750.
        assert approved["amount_cents"] == 120750
        assert backcharge["status"] == "PENDING"
        assert backcharge["amount_cents"] == 120750, (
            f"backcharge amount must be copied from the fix, "
            f"got {backcharge['amount_cents']}"
        )

    def test_approve_recomputes_job_pending_backcharge(self):
        """PRD section 3.8: "The same approval creates the money claim: a
        backcharge springs into existence in `PENDING` status with its
        `amount_cents` copied from the fix's freshly computed `amount_cents`,
        its `field_fix_id` pointing at the fix, and its `job_id` copied from
        the fix's job; the job's `pending_backcharge_cents` is recomputed to
        include it."
        PRD section 3.1: "`pending_backcharge_cents` sums `amount_cents` over
        the job's backcharges in `PENDING`, `ACCEPTED`, or `DISPUTED`."

        Design: Difficulty/transitive_cascade/field_fix_approve_backcharge_cascade
        """
        ctx, fix = self._approved_fix("Job F2")
        approve_field_fix(fix["id"])
        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["pending_backcharge_cents"] == 120750, (
            f"the job must recompute pending backcharges to include the new "
            f"claim, got {job['pending_backcharge_cents']}"
        )


class TestFiscalCap:

    def _accepted_backcharge(self, name):
        ctx = setup_fabrication_ready(name)
        piece, _load = create_shipped_piece(ctx, "P1", 1000)
        _fix, backcharge = setup_approved_fix_with_backcharge(
            ctx, piece["id"], SMALL_LINES
        )
        respond_backcharge(backcharge["id"], "ACCEPT")
        return ctx, backcharge

    def test_settle_exceeding_billed_rejected(self):
        """PRD section 3.8: "The fiscal cap guards settlement: the job's
        current `settled_backcharge_cents` plus the new `settled_amount_cents`
        must not exceed the job's `billed_to_date_cents` — the shop cannot
        settle backcharges out of money it has not yet billed — with violations
        rejected as `ERR_BACKCHARGE_EXCEEDS_EARNED`."

        Design: Corner/errors/settle_exceeding_billed_rejected
        """
        ctx, backcharge = self._accepted_backcharge("Job ER1")
        # Nothing has been billed: billed_to_date_cents == 0.
        resp = api_client.settle_backcharge(
            backcharge["id"], {"settled_amount_cents": 999999}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_BACKCHARGE_EXCEEDS_EARNED)
        after = validate_success(api_client.get_backcharge(backcharge["id"], ADMIN))
        assert after["status"] == "ACCEPTED", \
            "a rejected settle must leave the backcharge ACCEPTED"

    def test_settle_at_zero_boundary_accepted(self):
        """PRD section 3.8: "The fiscal cap guards settlement: the job's
        current `settled_backcharge_cents` plus the new `settled_amount_cents`
        must not exceed the job's `billed_to_date_cents` — the shop cannot
        settle backcharges out of money it has not yet billed — with violations
        rejected as `ERR_BACKCHARGE_EXCEEDS_EARNED`."
        PRD section 3.8: "A successful settle moves the money between the job's
        aggregates: `pending_backcharge_cents` drops by the backcharge's
        `amount_cents` and `settled_backcharge_cents` rises by
        `settled_amount_cents`; then the job's compound completion check of
        §3.9 runs."

        Design: Difficulty/priority_pair_validation_conflict/settle_state_over_fiscal
        """
        ctx, backcharge = self._accepted_backcharge("Job T0")
        # 0 + 0 <= 0: the cap is not exceeded, so the settle proceeds.
        settled = settle_backcharge(backcharge["id"], 0)
        assert settled["status"] == "SETTLED"
        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["pending_backcharge_cents"] == 0, (
            f"settle must drop pending by the claim amount, "
            f"got {job['pending_backcharge_cents']}"
        )
        assert job["settled_backcharge_cents"] == 0

    def test_double_settle_reports_state_error(self):
        """PRD section 2.8: "Every request walks a fixed ladder of checks, and
        the first failing rung produces the response — later rungs are never
        evaluated."
        PRD section 2.8 (rung 6 before rung 10): "State legality. The target
        entity must be in a valid from-state for the requested transition —
        including a mill order placed only against a job that is not
        `ESTIMATING`, load line edits only while the load is `STAGING` or
        `LOADING`, and a field fix reported only on a `SHIPPED` or `ERECTED`
        piece — failing as `ERR_INVALID_STATE` (HTTP 409)."
        PRD section 3.8: "Settlement is the fabricator's act — a
        `FABRICATOR_ADMIN` records the negotiated `settled_amount_cents`,
        moving the backcharge from `ACCEPTED` or `DISPUTED` to `SETTLED`."

        Design: Difficulty/priority_pair_validation_conflict/settle_state_over_fiscal
        """
        _ctx, backcharge = self._accepted_backcharge("Job T")
        settle_backcharge(backcharge["id"], 0)
        # The second settle is both state-illegal (SETTLED is terminal) and a
        # fiscal violation (0 + 5 > billed 0); the earlier rung must win.
        resp = api_client.settle_backcharge(
            backcharge["id"], {"settled_amount_cents": 5}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_backcharge(backcharge["id"], ADMIN))
        assert after["status"] == "SETTLED"


class TestFieldFixGates:

    def test_field_fix_requires_shipped_piece(self):
        """PRD section 3.8: "A `FOREMAN` reports a field fix with a `job_id`,
        the `piece_id` in question — the piece must be `SHIPPED` or `ERECTED`,
        since a fix is by definition discovered after the steel has left the
        shop, and any other status fails `ERR_INVALID_STATE` — a free-text
        `description`, and a non-empty `repair_lines` array."

        Design: Corner/endpoints/field_fix_requires_shipped_piece
        """
        job = create_job("Job EP7")
        drawing = create_drawing(job["id"], "D-1")
        sequence = create_sequence(job["id"], 1)
        piece = create_piece(job["id"], drawing["id"], sequence["id"],
                             "P1", 800)  # DETAILED
        resp = api_client.create_field_fix(
            {
                "job_id": job["id"], "piece_id": piece["id"],
                "description": "Premature fix", "repair_lines": SMALL_LINES,
            },
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fix_resolve_blocked_by_open_backcharge(self):
        """PRD section 3.8: "A fix is closed by resolving it, a `FOREMAN`
        action moving it from `APPROVED` to `RESOLVED` — but only once the
        linked backcharge stands in `SETTLED`; resolving while the claim is
        still open fails with `ERR_BACKCHARGE_OPEN`."

        Design: Corner/endpoints/fix_resolve_blocked_by_open_backcharge
        """
        ctx = setup_fabrication_ready("Job EP8")
        piece, _load = create_shipped_piece(ctx, "P1", 1000)
        fix = create_field_fix(
            ctx["job"]["id"], piece["id"],
            [{"labor_hours": 2, "labor_rate_cents": 5000, "material_cents": 1000}],
            description="Shim pack",
        )
        approve_field_fix(fix["id"])  # backcharge left PENDING
        resp = api_client.resolve_field_fix(fix["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_BACKCHARGE_OPEN)
        after = validate_success(api_client.get_field_fix(fix["id"], FOREMAN))
        assert after["status"] == "APPROVED", \
            "a rejected resolve must leave the fix APPROVED"
