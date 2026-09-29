"""Cross-cutting layers: version tokens and the engagement's hour budget.

Two planners racing on one plan, two unrelated endpoints sharing one engagement
token, and a budget filled to the last hour and then freed again.
"""

from test_helpers import (
    assert_error_id,
    assert_exact_int,
    assert_hour_ledger,
    assert_page,
    assert_score,
    build_scenario,
    created_data,
    engagement_version,
    factories,
    make_tester_headers,
    success_data,
)
from test_helpers.api_errors import (
    ERR_ENGAGEMENT_HOURS_EXCEEDED,
    ERR_STALE_ENGAGEMENT_VERSION,
    ERR_STALE_PLAN_VERSION,
)

T_FIELDWORK_OPENING = "2026-09-08T09:00:00Z"
BOOKING_START = "2026-09-05T00:00:00Z"
BOOKING_END = "2026-09-20T00:00:00Z"


def _book(client, engagement_id, tester_id, asset_id, version, **overrides):
    """Request one booking over the standard fortnight interval."""
    return client.create_tester_assignment(
        factories.tester_assignment_payload(
            engagement_id,
            tester_id,
            version,
            [asset_id],
            interval_start=BOOKING_START,
            interval_end=BOOKING_END,
            **overrides,
        )
    )


def _register_tester(client, name):
    return created_data(client.create_tester(factories.tester_payload(full_name=name)))


class TestPlanVersionTokens:
    """The plan's version token is consumed by one write and must be re-read."""

    def test_a_stale_expected_test_plan_version_blocks_the_second_candidate(
        self, client, other_program_manager
    ):
        """Two planners hold token 1; the loser is refused and succeeds once it re-reads.

        PRD: "`POST /pentest/scope-items` requires `expected_test_plan_version`, carrying the client's last observed `version` of the target `TestPlan`. If it does not equal the plan's current `version`, the proposal is rejected with `ERR_STALE_PLAN_VERSION` and HTTP 412."
        PRD: "The reason is that every accepted candidate rescores and re-ranks the plan's whole candidate population and advances the plan's `version`, so a client holding an older version is scoring its candidate against a ranking population that no longer exists."
        PRD: "Two managers may both legitimately propose different assets into the same plan, so no state precondition orders them — the stale-version guard is what does."

        Design: Corner/cross_cutting_layers/a_stale_expected_test_plan_version_blocks_the_second_candidate
        """
        scenario = build_scenario(client, stage="plan")
        plan_id = scenario["plan_id"]
        second_asset = created_data(
            client.create_asset(factories.partner_portal_asset_payload())
        )
        assert_exact_int(scenario["plan"]["version"], 1, "version")

        first = created_data(
            client.create_scope_item(
                factories.scope_item_payload(
                    plan_id,
                    scenario["asset_id"],
                    1,
                    justification="Payments coverage",
                )
            )
        )

        after_first = success_data(client.get_test_plan(plan_id))
        assert_exact_int(after_first["version"], 2, "version")
        assert after_first["status"] == "DRAFT", (
            f"status: expected DRAFT, got {after_first['status']}"
        )

        assert_error_id(
            client.create_scope_item(
                factories.scope_item_payload(
                    plan_id,
                    second_asset["id"],
                    1,
                    justification="Portal coverage",
                    requested_engagement_hours=40,
                ),
                headers=other_program_manager,
            ),
            ERR_STALE_PLAN_VERSION,
        )

        after_refusal = success_data(
            client.get_test_plan(plan_id, headers=other_program_manager)
        )
        assert_exact_int(after_refusal["version"], 2, "version")

        created_data(
            client.create_scope_item(
                factories.scope_item_payload(
                    plan_id,
                    second_asset["id"],
                    after_refusal["version"],
                    justification="Portal coverage",
                    requested_engagement_hours=40,
                ),
                headers=other_program_manager,
            )
        )

        after_retry = success_data(client.get_test_plan(plan_id))
        assert_exact_int(after_retry["version"], 3, "version")
        assert_exact_int(after_retry["total_risk_points"], 0, "total_risk_points")

        rows, _ = assert_page(
            client.list_scope_items(
                params={"test_plan_id": plan_id, "limit": 10, "offset": 0}
            ),
            total_count=2,
            has_more=False,
            row_count=2,
        )
        assert rows[0]["id"] == first["id"], (
            f"first row: expected {first['id']}, got {rows[0]['id']}"
        )


class TestEngagementVersionTokens:
    """One engagement token guards both bookings and finding reports."""

    def test_both_engagement_scoped_writes_share_one_version_token(self, client):
        """A booking invalidates the token a tester was about to file a finding with.

        PRD: "`POST /pentest/findings` requires `expected_engagement_version`, carrying the client's last observed `version` of the target `Engagement`. A mismatch with the engagement's current `version` is rejected with `ERR_STALE_ENGAGEMENT_VERSION` and HTTP 412."
        PRD: "`POST /pentest/tester-assignments` also requires `expected_engagement_version` against the target `Engagement`, and a mismatch is likewise rejected with `ERR_STALE_ENGAGEMENT_VERSION` and HTTP 412."
        PRD: "Reserved, consumed and available hours all move with every assignment and every settlement, so a stale value means the planner is budgeting against hours another assignment has already taken."
        PRD: "Its `requested_hours` are added to the engagement's `hours_reserved`, `hours_available` is recomputed as the allocation minus reserved minus consumed, and the engagement's `version` advances."

        Design: Corner/cross_cutting_layers/both_engagement_scoped_writes_share_one_version_token
        """
        scenario = build_scenario(client, stage="engagement")
        engagement_id = scenario["engagement_id"]
        asset_id = scenario["asset_id"]
        assert_exact_int(scenario["engagement"]["version"], 1, "version")

        document = created_data(
            client.create_rules_of_engagement(
                factories.rules_of_engagement_payload(engagement_id)
            )
        )
        created_data(
            client.create_authorized_target(
                factories.authorized_target_payload(document["id"], asset_id)
            )
        )
        success_data(
            client.sign_rules_of_engagement(
                document["id"], signature_note="Authorized for FY2026 window"
            )
        )
        authorized = success_data(client.get_engagement(engagement_id))
        assert_exact_int(authorized["version"], 2, "version")

        lead = _register_tester(client, "Tester One")
        spare = _register_tester(client, "Tester Two")
        success_data(client.record_background_check(lead["id"], "CLEARED"))

        first_booking = created_data(
            _book(client, engagement_id, lead["id"], asset_id, 2)
        )

        assert_error_id(
            _book(
                client,
                engagement_id,
                spare["id"],
                asset_id,
                2,
                assignment_role="MEMBER",
                requested_hours=20,
            ),
            ERR_STALE_ENGAGEMENT_VERSION,
        )

        after_first = success_data(client.get_engagement(engagement_id))
        assert_exact_int(after_first["version"], 3, "version")
        assert_score(after_first["hours_reserved"], 40.00, "hours_reserved")

        created_data(
            _book(
                client,
                engagement_id,
                spare["id"],
                asset_id,
                3,
                assignment_role="MEMBER",
                requested_hours=20,
            )
        )

        success_data(client.set_access(first_booking["id"], "PROVISION"))
        success_data(client.set_clock(T_FIELDWORK_OPENING))
        started = success_data(client.drive_execution(engagement_id, "START"))
        tester_headers = make_tester_headers(lead["id"])

        assert_error_id(
            client.create_finding(
                factories.finding_payload(
                    engagement_id,
                    asset_id,
                    2,
                    title="Payments IDOR",
                    technical_base_score=6.0,
                ),
                tester_headers,
            ),
            ERR_STALE_ENGAGEMENT_VERSION,
        )

        created_data(
            client.create_finding(
                factories.finding_payload(
                    engagement_id,
                    asset_id,
                    started["version"],
                    title="Payments IDOR",
                    technical_base_score=6.0,
                ),
                tester_headers,
            )
        )

        final = success_data(client.get_engagement(engagement_id))
        assert final["version"] > started["version"], (
            f"version: expected more than {started['version']}, got {final['version']}"
        )
        assert_hour_ledger(final, reserved=60.00)


class TestEngagementHourBudget:
    """The budget admits equality, refuses one hour more, and is freed by revocation."""

    def test_cumulative_hour_reservations_stop_at_the_budget_and_a_revocation_resets_it(
        self, client
    ):
        """Two bookings fill 80 hours exactly, the next hour is refused, and a revocation reopens it.

        PRD: "Fourth and last comes the money: `requested_hours` must be no greater than the engagement's current `hours_available`, with equality passing, and an over-draw is refused with `ERR_ENGAGEMENT_HOURS_EXCEEDED`."
        PRD: "Its hour ledger opens with `hours_reserved` at 0, `hours_consumed` at 0 and `hours_available` equal to the full `hours_allocated`."
        PRD: "A revocation of an assignment that was **never provisioned** — one still at `REQUESTED` — settles `settled_hours` at 0, since no access ever existed and nothing was consumed; it stamps `revoked_at`, subtracts the assignment's `requested_hours` from the engagement's `hours_reserved`, and recomputes `hours_available`."
        PRD: "The **hour-ledger invariant** on an engagement is that `hours_allocated` always equals `hours_reserved` plus `hours_consumed` plus `hours_available`."

        Design: Corner/cross_cutting_layers/cumulative_hour_reservations_stop_at_the_budget_and_a_revocation_resets_it
        """
        scenario = build_scenario(client, stage="roe_signed")
        engagement_id = scenario["engagement_id"]
        asset_id = scenario["asset_id"]
        assert_hour_ledger(
            scenario["engagement"], reserved=0.00, consumed=0.00, available=80.00
        )

        first = _register_tester(client, "Tester One")
        second = _register_tester(client, "Tester Two")
        third = _register_tester(client, "Tester Three")

        first_booking = created_data(
            _book(
                client,
                engagement_id,
                first["id"],
                asset_id,
                engagement_version(client, engagement_id),
                assignment_role="MEMBER",
            )
        )
        after_first = success_data(client.get_engagement(engagement_id))
        assert_hour_ledger(after_first, reserved=40.00, available=40.00)

        created_data(
            _book(
                client,
                engagement_id,
                second["id"],
                asset_id,
                after_first["version"],
                assignment_role="MEMBER",
            )
        )
        after_second = success_data(client.get_engagement(engagement_id))
        assert_hour_ledger(after_second, reserved=80.00, available=0.00)

        assert_error_id(
            _book(
                client,
                engagement_id,
                third["id"],
                asset_id,
                after_second["version"],
                assignment_role="MEMBER",
                requested_hours=1,
            ),
            ERR_ENGAGEMENT_HOURS_EXCEEDED,
        )

        revoked = success_data(client.set_access(first_booking["id"], "REVOKE"))
        assert revoked["access_state"] == "REVOKED", (
            f"access_state: expected REVOKED, got {revoked['access_state']}"
        )
        assert_exact_int(revoked["settled_hours"], 0, "settled_hours")

        after_revocation = success_data(client.get_engagement(engagement_id))
        assert_hour_ledger(
            after_revocation, reserved=40.00, consumed=0.00, available=40.00
        )

        replacement = created_data(
            _book(
                client,
                engagement_id,
                third["id"],
                asset_id,
                after_revocation["version"],
                assignment_role="MEMBER",
            )
        )
        assert replacement["access_state"] == "REQUESTED", (
            f"access_state: expected REQUESTED, got {replacement['access_state']}"
        )
        final = success_data(client.get_engagement(engagement_id))
        assert_hour_ledger(final, reserved=80.00, consumed=0.00, available=0.00)
