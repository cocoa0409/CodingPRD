"""The rebuild decision (override justification) and quote computation
(per-line pinned rounding, sum of pinned lines, send preconditions)."""

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    create_decision_payload,
    validate_error,
    validate_success,
)


class TestQuoteNestedRoundingOrder:
    PARTS_SPEC = [
        {"oem_status": "ACTIVE", "unit_cost_cents": 1_250_000, "stock_quantity": 10,
         "quantity": 2, "description": "Ball screw"},
        {"oem_status": "OBSOLETE", "unit_cost_cents": 1_333_333, "stock_quantity": 0,
         "quantity": 1, "lead_time_days": 60, "description": "NC board"},
        {"oem_status": "OBSOLETE", "unit_cost_cents": 1_333_333, "stock_quantity": 0,
         "quantity": 1, "lead_time_days": 60, "description": "NC board"},
    ]

    def test_per_line_rounding_pinned_at_line_creation(self, api):
        """PRD §3.4: "At creation the line snapshots its commercial terms: `unit_price_cents` is pinned to the part's current `unit_cost_cents`, `obs_multiplier` is pinned to 1.8 when the part is `OBSOLETE` at that moment and 1.0 otherwise, and `line_total_cents` is pinned to the quantity times the pinned unit price times the pinned multiplier, rounded half-up to a whole cent."
        PRD §2.5: "Rounding is always the round-half-up method, applied only at explicitly pinned rounding points: each part line's total is rounded half-up to a whole cent when the line is created; the volume discount is rounded half-up to a whole cent when a quote is computed; the two trade-in valuations are rounded half-up to whole cents when an offer is created; and each rework surcharge is rounded half-up to a whole cent when it is applied."

        Design: Difficulty/combinatorial_formula/quote_nested_rounding_order
        """
        ctx = fx.setup_project_decided(parts_spec=self.PARTS_SPEC)
        active_line, obsolete_line_1, obsolete_line_2 = ctx.lines

        assert active_line["unit_price_cents"] == 1_250_000
        assert active_line["obs_multiplier"] == 1.0
        assert active_line["line_total_cents"] == 2_500_000  # 2 * 1_250_000 * 1.0

        for line in (obsolete_line_1, obsolete_line_2):
            assert line["unit_price_cents"] == 1_333_333
            assert line["obs_multiplier"] == 1.8
            # round_half_up(1 * 1_333_333 * 1.8) = round_half_up(2_399_999.4)
            assert line["line_total_cents"] == 2_399_999
            fx.assert_part_line(line)

    def test_quote_sums_pinned_per_line_amounts_without_reRounding(self, api):
        """PRD §3.3: "First, `parts_total_cents` is formed by summing the `line_total_cents` of every part line of the project whose `status` is not `CANCELLED`; each line's total was already rounded half-up to a whole cent when the line was created, and the quote sums those pinned per-line amounts rather than re-rounding the aggregate."

        Design: Difficulty/combinatorial_formula/quote_nested_rounding_order
        """
        ctx = fx.setup_project_decided(parts_spec=self.PARTS_SPEC)
        project = fx.compute_quote(ctx.project["id"])

        # 2_500_000 + 2_399_999 + 2_399_999; a sum-then-round implementation
        # would produce 7_299_999 instead — the one-cent divergence pins the order.
        assert project["parts_total_cents"] == 7_299_998
        fx.assert_project(project)
        fx.assert_quote_conservation(project)


def test_decision_override_requires_reason(api):
    """PRD §3.3: "When the chosen `decision` differs from the accepted assessment's `recommended_path`, a non-empty `decision_reason` is mandatory; omitting the justification on an override is rejected with `ERR_DECISION_OVERRIDE_NEEDS_REASON`, while a matching decision needs no reason."

    Design: Corner/validations/decision_override_requires_reason
    """
    # Default assessment (10/8/6) computes wear 57.00 -> MECHANICAL_REBUILD.
    ctx = fx.setup_project_scoped()
    project_id = ctx.project["id"]

    bare = api.record_decision(
        project_id,
        create_decision_payload(decision="FULL_REBUILD", assigned_engineer_id="eng-1"),
        PM,
    )
    validate_error(bare, ApiErrorId.ERR_DECISION_OVERRIDE_NEEDS_REASON.value)

    justified = validate_success(
        api.record_decision(
            project_id,
            create_decision_payload(
                decision="FULL_REBUILD", assigned_engineer_id="eng-1",
                decision_reason="customer mandated full rebuild regardless of wear band",
            ),
            PM,
        ),
        200,
    )
    assert justified["work_status"] == "DECIDED"
    assert justified["decision"] == "FULL_REBUILD"


def test_quote_send_before_compute_rejected(api):
    """PRD §3.3: "Sending the quote to the customer requires that at least one computation exists (`quote_revision` of zero is rejected with `ERR_QUOTE_REQUIRED`) and that the snapshot is current (`quote_stale` must be `false`, else `ERR_QUOTE_STALE`); a successful send moves `commercial_status` from `QUOTE_DRAFT` to `QUOTE_SENT`."

    Design: Corner/validations/quote_send_before_compute_rejected
    """
    ctx = fx.setup_project_decided()
    assert ctx.project["quote_revision"] == 0

    res = api.send_quote(ctx.project["id"], PM)
    validate_error(res, ApiErrorId.ERR_QUOTE_REQUIRED.value)

    after = fx.get_project(ctx.project["id"])
    assert after["commercial_status"] == "QUOTE_DRAFT"
