"""Family budget forecast: dual variants and per-line rounding (PRD §3.9, §2.7)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_ep_world_with_authorized_y1,
    setup_world_with_granted_app,
    create_rule,
    create_client,
    create_family,
    create_granted_application,
    list_obligations,
    get_family,
    EP_RULE_PAYLOAD,
    create_us_rule,
    create_pending_application,
    create_application,
    create_docket_entry_payload,
    create_office_action_payload,
    set_clock,
)

ANY = TEST_USERS["any_headers"]
CLERK = TEST_USERS["clerk_headers"]
MGR = TEST_USERS["manager_headers"]


class TestBudgetForecastCommittedVsProjected:
    def test_committed_variant_counts_actuals_only(self):
        """PRD §3.9: "Under `variant` value `COMMITTED`, obligations in
        `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or `CONFIRMATION_QUERY` contribute
        their `authorized_amount_cents` and `PAID_CONFIRMED` obligations
        contribute their `paid_amount_cents`, while `SCHEDULED` and
        `PENDING_AUTHORIZATION` obligations contribute nothing."

        Design: Difficulty/dual_variant_calc/budget_forecast_committed_vs_projected_diverge
        """
        world = setup_ep_world_with_authorized_y1()
        resp = api_client.get_budget_forecast(world["family"]["id"], ANY, params={"variant": "COMMITTED"})
        data = validate_success(resp, 200)
        assert data["variant"] == "COMMITTED"
        # y1 AUTHORIZED at 10255; y2/y3 SCHEDULED contribute nothing.
        assert data["total_usd_cents"] == 10255, (
            f"COMMITTED must include only the authorized 10255, got {data['total_usd_cents']}"
        )
        # The stored rollup reflects the same committed amount.
        family = get_family(world["family"]["id"])
        assert family["committed_forecast_cents"] == 10255

    def test_projected_variant_adds_estimates(self):
        """PRD §3.9: "Under `variant` value `PROJECTED`, `SCHEDULED` and
        `PENDING_AUTHORIZATION` obligations additionally contribute their
        `estimated_amount_usd_cents`."

        Design: Difficulty/dual_variant_calc/budget_forecast_committed_vs_projected_diverge
        """
        world = setup_ep_world_with_authorized_y1()
        resp = api_client.get_budget_forecast(world["family"]["id"], ANY, params={"variant": "PROJECTED"})
        data = validate_success(resp, 200)
        assert data["variant"] == "PROJECTED"
        # 10255 (authorized y1) + 1026 (est y2) + 3077 (est y3) = 14358.
        assert data["total_usd_cents"] == 14358, (
            f"PROJECTED must add per-line estimates to the committed figure, got {data['total_usd_cents']}"
        )


class TestBudgetForecastPerLineRounding:
    def test_per_line_estimates_are_individually_rounded(self):
        """PRD §3.4: "the USD amount converts it by multiplying by the rule's
        `fx_to_usd_cents_bps`, dividing by ten thousand, and rounding half up."

        Design: Difficulty/combinatorial_formula/budget_forecast_per_line_rounding_beats_sum_then_round
        """
        create_rule(EP_RULE_PAYLOAD)
        client = create_client("RoundCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_granted_application(
            family["id"], grant_date="2026-03-01", jurisdiction="EP", application_number="EP-R"
        )
        obligations = list_obligations(app["id"])
        assert [o["period_year"] for o in obligations] == [1, 2, 3]
        # round_half_up(local * 10255 / 10000) per line: 10255, 1026, 3077.
        assert obligations[0]["estimated_amount_usd_cents"] == 10255
        assert obligations[1]["estimated_amount_usd_cents"] == 1026
        assert obligations[2]["estimated_amount_usd_cents"] == 3077

    def test_forecast_sums_per_line_rounded_integers(self):
        """PRD §3.9: "the `total_usd_cents` — the sum of the contributed
        per-obligation amounts, summed as already-rounded integer cents and
        never re-rounded".

        Design: Difficulty/combinatorial_formula/budget_forecast_per_line_rounding_beats_sum_then_round
        """
        create_rule(EP_RULE_PAYLOAD)
        client = create_client("RoundCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_granted_application(
            family["id"], grant_date="2026-03-01", jurisdiction="EP", application_number="EP-R"
        )
        resp = api_client.get_budget_forecast(family["id"], ANY, params={"variant": "PROJECTED"})
        data = validate_success(resp, 200)
        # Per-line-then-sum: 10255 + 1026 + 3077 = 14358. The forbidden
        # sum-then-round order would yield round(14000 * 1.0255) = 14357.
        assert data["total_usd_cents"] == 14358
        committed = api_client.get_budget_forecast(family["id"], ANY, params={"variant": "COMMITTED"})
        assert validate_success(committed, 200)["total_usd_cents"] == 0


class TestBudgetForecastVariantValidation:
    def test_unknown_variant_rejected(self):
        """PRD §3.9: "The **family budget forecast** requires a `variant` query
        value"; PRD §2.9: "Required fields present, no undeclared fields, enum
        values within their declared sets, date fields in ISO YYYY-MM-DD form,
        integers where integers are declared, and — on docket audits —
        `window_start` strictly earlier than `window_end`; violations are
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/computed_read_variant_param_validated
        """
        world = setup_world_with_granted_app(client_name="VarCo2")
        resp = api_client.get_budget_forecast(world["family"]["id"], ANY, params={"variant": "WILD"})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def _risk_world():
    """Clock pinned at 2026-08-01; one PENDING application carrying:
    STATUTORY due 2026-08-05, ANNUITY due 2026-09-25, RECORDATION due
    2027-06-01, and an OA-response entry due 2026-08-20."""
    set_clock("2026-08-01T00:00:00Z")
    create_us_rule()
    client = create_client("RiskCo")
    family = create_family(client["id"], budget_cap_cents=1000000)
    app = create_pending_application(family["id"], application_number="US-1")
    api_client.create_docket_entry(
        app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="Stat bar",
                                               base_due_date="2026-08-05"), CLERK)
    api_client.create_docket_entry(
        app["id"], create_docket_entry_payload(entry_type="ANNUITY", title="Ann reminder",
                                               base_due_date="2026-09-25"), CLERK)
    api_client.create_docket_entry(
        app["id"], create_docket_entry_payload(entry_type="RECORDATION", title="Record assignment",
                                               base_due_date="2027-06-01"), CLERK)
    api_client.create_office_action(
        app["id"], create_office_action_payload(mail_date="2026-05-20"), CLERK)
    return client, app


class TestClientRiskScoreVariants:
    def test_statutory_only_variant_counts_statutory_entries(self):
        """PRD §3.9: "under `variant` value `STATUTORY_ONLY` only `STATUTORY`
        entries contribute" and "Each entry contributes a weight by type —
        `STATUTORY` ten, `OFFICE_ACTION_RESPONSE` four, `PARIS_PRIORITY` eight,
        `PCT_PHASE` eight, `ANNUITY` six, `RECORDATION` two — multiplied by an
        urgency factor driven by the calendar days between today and the
        entry's `current_due_date`"

        Design: Difficulty/dual_variant_calc/client_risk_score_statutory_vs_all_diverge
        """
        client, _ = _risk_world()
        resp = api_client.get_client_risk_score(client["id"], ANY, params={"variant": "STATUTORY_ONLY"})
        data = validate_success(resp, 200)
        # STATUTORY weight 10, due 2026-08-05 vs today 2026-08-01 -> 4 days -> x4 -> 40.
        assert float(data["score"]) == pytest.approx(40.0)
        # PRD §3.9: "ELEVATED for a score of at least twenty but below fifty".
        assert data["tier"] == "ELEVATED"

    def test_all_deadlines_variant_counts_all_types(self):
        """PRD §3.9: "under `ALL_DEADLINES` all six types do" and "The reported
        `tier` is `CRITICAL` for a score of fifty or more, `ELEVATED` for a
        score of at least twenty but below fifty, and `NORMAL` below twenty."

        Design: Difficulty/dual_variant_calc/client_risk_score_statutory_vs_all_diverge
        """
        client, _ = _risk_world()
        resp = api_client.get_client_risk_score(client["id"], ANY, params={"variant": "ALL_DEADLINES"})
        data = validate_success(resp, 200)
        # 40 (STATUTORY x4) + 8 (OA response: 4 x2 at 19 days) + 6 (ANNUITY x1
        # at 55 days) + 1 (RECORDATION 2 x0.5 at 304 days) = 55.
        assert float(data["score"]) == pytest.approx(55.0)
        assert data["tier"] == "CRITICAL"


class TestClientRiskScoreInputSet:
    def test_cancelled_and_withdrawn_application_entries_excluded(self):
        """PRD §3.9: "It considers every docket entry in `PENDING` or
        `IN_PROGRESS` whose parent application is non-terminal and belongs to a
        family of this client."

        Design: Corner/calculations/risk_score_excludes_closed_and_terminal_entries
        """
        set_clock("2026-08-01T00:00:00Z")
        create_us_rule()
        client = create_client("FiltCo")
        fam1 = create_family(client["id"], title="F1")
        fam2 = create_family(client["id"], title="F2")
        a1 = create_pending_application(fam1["id"], application_number="US-F1")
        api_client.create_docket_entry(
            a1["id"], create_docket_entry_payload(entry_type="STATUTORY", title="open",
                                                  base_due_date="2026-08-05"), CLERK)
        to_cancel = validate_success(api_client.create_docket_entry(
            a1["id"], create_docket_entry_payload(entry_type="STATUTORY", title="to-cancel",
                                                  base_due_date="2026-08-05"), CLERK), 201)
        validate_success(api_client.cancel_docket_entry(to_cancel["id"], MGR), 200)
        # Second family's application stays DRAFT (entries can be created on a
        # non-terminal application) and is then withdrawn.
        a2 = create_application(fam2["id"], application_number="US-F2")
        api_client.create_docket_entry(
            a2["id"], create_docket_entry_payload(entry_type="STATUTORY", title="orphan",
                                                  base_due_date="2026-08-05"), CLERK)
        validate_success(api_client.withdraw_application(a2["id"], CLERK), 200)

        resp = api_client.get_client_risk_score(client["id"], ANY, params={"variant": "ALL_DEADLINES"})
        data = validate_success(resp, 200)
        # Only the open STATUTORY entry on the live PENDING application counts:
        # weight 10, 4 days out -> x4 -> 40.
        assert float(data["score"]) == pytest.approx(40.0)
