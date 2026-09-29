"""Access-control corners: authentication, role exclusivity, confidentiality, duties.

The four rungs of PRD 2.6 that run before any business rule are pinned here in
order: malformed identity headers are 401, a well-formed but unauthorised role is
403 even when the addressed row does not exist, the two respondent-level read
surfaces of PRD 2.1 are closed to client-facing roles, and a ``ClientUser`` is
scoped to its own client. The file closes on PRD 2.10, whose two-operator gates
are a second, independent 409 on top of the role list.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import MISSING_UUID
from test_helpers.factories import (
    accreditation_audit_payload,
    edit_rule_set_payload,
    market_payload,
    methodology_change_payload,
)
from test_helpers.fixtures import PanelHarness
from test_helpers.test_users import (
    AUDITOR_FINALIZER_USER_ID,
    STATISTICIAN_PUBLISHER_USER_ID,
    make_client_user_headers,
    make_field_tech_headers,
    make_headers,
    make_headers_with_empty_role,
    make_headers_with_empty_user_id,
    make_headers_without_role,
    make_headers_without_user_id,
)


class TestUnauthenticatedAndUnknownRoles:
    """PRD 2.1's 401 surface: the headers themselves, before any role list."""

    def test_malformed_identity_headers_are_unauthenticated(self, panel: PanelHarness):
        """Absent or empty id, absent or unknown role: all four are 401.

        PRD 2.1: "If `X-User-ID` is missing or empty, or if `X-User-Role` is
        absent or does not name one of the seven roles below, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_and_unknown_role_requests_are_rejected
        """
        for headers in (
            make_headers_without_user_id(),
            make_headers_with_empty_user_id(),
            make_headers_without_role(),
            make_headers_with_empty_role(),
        ):
            validate_error(panel.client.list_markets(headers), "ERR_UNAUTHENTICATED")

    def test_an_unknown_role_name_is_unauthenticated_not_unauthorized(
        self, panel: PanelHarness
    ):
        """A role outside the seven is a 401, never a 403.

        PRD 2.1: "The seven recognised roles are `PanelOperationsManager`,
        `FieldTechnician`, `MethodologyStatistician`, `ClientServiceRep`,
        `ClientUser`, `AccreditationAuditor` and `GovernanceDirector`."

        Design: Corner/rbac/unauthenticated_and_unknown_role_requests_are_rejected
        """
        intern = make_headers("AuditIntern", "audit-intern-001")
        validate_error(panel.client.list_markets(intern), "ERR_UNAUTHENTICATED")
        validate_error(
            panel.client.create_market(intern, **market_payload()), "ERR_UNAUTHENTICATED"
        )

    def test_a_rejected_write_leaves_no_row_behind(self, panel: PanelHarness):
        """Authentication runs before the write, so nothing is persisted.

        PRD 2.6: "Every request walks a fixed ladder of generic checks before any
        endpoint-specific business rule is consulted, and the first failure on the
        ladder is the error the caller sees".

        Design: Corner/rbac/unauthenticated_and_unknown_role_requests_are_rejected
        """
        validate_error(
            panel.client.create_market(make_headers_with_empty_user_id(), **market_payload()),
            "ERR_UNAUTHENTICATED",
        )
        rows, meta = validate_paginated(panel.client.list_markets(panel.ops))
        assert rows == []
        assert meta["total_count"] == 0


class TestExclusiveOperationsRejectPeerRoles:
    """PRD 2.1's 403 surface: priority 2 precedes existence at priorities 4 and 5."""

    def test_market_and_rule_set_writes_are_exclusive(self, panel: PanelHarness):
        """The market surface and the measurement surface do not overlap.

        PRD 2.1: "If the headers are well-formed but the named role is not
        authorised for the operation being attempted, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/exclusive_operations_are_rejected_for_peer_roles_unauthorized
        """
        validate_error(
            panel.client.create_market(panel.tech, **market_payload()), "ERR_UNAUTHORIZED"
        )
        validate_error(
            panel.client.create_edit_rule_set(panel.ops, **edit_rule_set_payload()),
            "ERR_UNAUTHORIZED",
        )
        # Priority 2 also outranks priority 5: an unresolvable body reference is
        # never reached.
        validate_error(
            panel.client.adjust_market_budget(
                panel.tech, MISSING_UUID, delta_cents=1000, memo="Not this role's call."
            ),
            "ERR_UNAUTHORIZED",
        )

    def test_field_operations_are_exclusive_to_the_field_technician(
        self, panel: PanelHarness
    ):
        """Metering and enumeration belong to the FieldTechnician alone.

        PRD 2.1: "A `FieldTechnician` owns the field surface: shipping,
        installing, fault-reporting, repairing and removing meters, and performing
        household enumerations."

        Design: Corner/rbac/exclusive_operations_are_rejected_for_peer_roles_unauthorized
        """
        # Both calls name an unresolvable household, so a 404 would prove the
        # ladder ran out of order.
        validate_error(
            panel.client.create_meter(
                panel.ops, household_id=MISSING_UUID, meter_type="TV_TUNER"
            ),
            "ERR_UNAUTHORIZED",
        )
        validate_error(
            panel.client.create_enumeration(
                panel.ops, MISSING_UUID, roster_persons_count=2, tv_sets_count=1
            ),
            "ERR_UNAUTHORIZED",
        )

    def test_commercial_and_governance_writes_are_exclusive(self, panel: PanelHarness):
        """Client records, changes, audits and revisions each have one owner.

        PRD 2.1: "A `ClientServiceRep` owns the commercial surface: client
        records, tier assignment, suspension and reinstatement, the delivery
        schedule, and the analyst side of deliverables."

        Design: Corner/rbac/exclusive_operations_are_rejected_for_peer_roles_unauthorized
        """
        validate_error(
            panel.client.create_client(
                panel.director, name="Alder Broadcasting Group", tier="STANDARD",
                contract_market_ids=[MISSING_UUID],
            ),
            "ERR_UNAUTHORIZED",
        )
        validate_error(
            panel.client.create_methodology_change(
                panel.rep,
                **methodology_change_payload(MISSING_UUID, MISSING_UUID, [MISSING_UUID]),
            ),
            "ERR_UNAUTHORIZED",
        )
        validate_error(
            panel.client.create_accreditation_audit(
                panel.statistician, **accreditation_audit_payload(MISSING_UUID, MISSING_UUID)
            ),
            "ERR_UNAUTHORIZED",
        )
        # Requesting a revision on a deliverable is the ClientUser's own verb.
        validate_error(
            panel.client.request_deliverable_revision(
                panel.rep, MISSING_UUID, reason="The analyst may not do this."
            ),
            "ERR_UNAUTHORIZED",
        )
        validate_error(
            panel.client.acknowledge_notification(panel.rep, MISSING_UUID),
            "ERR_UNAUTHORIZED",
        )

    def test_the_clock_is_open_to_every_role(self, panel: PanelHarness):
        """Exclusivity is per operation: the clock is shared by all seven roles.

        PRD 2.4: "All seven roles may advance the clock, because every role's
        workflow needs to be able to move time forward."

        Design: Corner/rbac/exclusive_operations_are_rejected_for_peer_roles_unauthorized
        """
        by_tech = validate_success(
            panel.client.set_logical_clock(
                make_field_tech_headers(), current_utc="2026-08-03T00:00:00Z"
            ),
            200,
        )
        assert by_tech["current_utc"].startswith("2026-08-03T00:00:00")
        # A ClientUser carries a client id that resolves to nothing here, and the
        # clock references no client, so the call still succeeds.
        by_subscriber = validate_success(
            panel.client.set_logical_clock(
                make_client_user_headers(MISSING_UUID), current_utc="2026-08-04T00:00:00Z"
            ),
            200,
        )
        assert by_subscriber["current_utc"].startswith("2026-08-04T00:00:00")


class TestConfidentialReadsAreClosedToClientFacingRoles:
    """PRD 2.1's two respondent-level read surfaces."""

    def test_tuning_interval_reads_are_confidential(self, panel: PanelHarness):
        """Only three roles may read tuning intervals; the rest get 403.

        PRD 2.1: "Two read surfaces are confidential because they expose
        respondent-level records: tuning intervals and household weights may only
        be read by a `PanelOperationsManager`, a `MethodologyStatistician` or an
        `AccreditationAuditor`. Any other role attempting those reads receives
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/confidential_reads_are_rejected_for_client_facing_roles
        """
        outsiders = [
            make_client_user_headers(MISSING_UUID),
            panel.tech,
            panel.rep,
            panel.director,
        ]
        for headers in outsiders:
            validate_error(panel.client.list_tuning_intervals(headers), "ERR_UNAUTHORIZED")
            # 403 and not 404: the role check precedes path existence.
            validate_error(
                panel.client.get_tuning_interval(headers, MISSING_UUID), "ERR_UNAUTHORIZED"
            )

    def test_household_weight_reads_are_confidential(self, panel: PanelHarness):
        """The weight surface is closed to exactly the same four roles.

        PRD 2.1: "tuning intervals and household weights may only be read by a
        `PanelOperationsManager`, a `MethodologyStatistician` or an
        `AccreditationAuditor`. Any other role attempting those reads receives
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/confidential_reads_are_rejected_for_client_facing_roles
        """
        outsiders = [
            make_client_user_headers(MISSING_UUID),
            panel.tech,
            panel.rep,
            panel.director,
        ]
        for headers in outsiders:
            validate_error(panel.client.list_household_weights(headers), "ERR_UNAUTHORIZED")
            validate_error(
                panel.client.get_household_weight(headers, MISSING_UUID), "ERR_UNAUTHORIZED"
            )

    def test_the_three_admitted_roles_are_served_and_ordinary_reads_stay_open(
        self, panel: PanelHarness
    ):
        """The confidential set is served an empty page, and markets stay open to all.

        PRD 2.1: "All seven roles may advance the logical clock, and all seven
        roles may read markets, quota cells, universe vintages, editing rule sets,
        households, meters, processing runs, clients, deliverables, notifications
        and accreditation audits."

        Design: Corner/rbac/confidential_reads_are_rejected_for_client_facing_roles
        """
        for headers in (panel.ops, panel.statistician, panel.auditor):
            rows, meta = validate_paginated(panel.client.list_tuning_intervals(headers))
            assert rows == []
            assert meta["total_count"] == 0
            rows, meta = validate_paginated(panel.client.list_household_weights(headers))
            assert rows == []
            assert meta["total_count"] == 0
        # A ClientUser is refused the confidential surfaces but not the open ones.
        subscriber = make_client_user_headers(MISSING_UUID)
        rows, meta = validate_paginated(panel.client.list_markets(subscriber))
        assert rows == []
        assert meta["total_count"] == 0


def _two_subscribers_of_one_market(panel: PanelHarness):
    """A PUBLISHED run, two contracted clients, a DELIVERED analysis for the first.

    Also drafts, assesses and notifies a methodology change over the run's own
    rule set so that both clients hold a `SENT` notification.
    """
    base = panel.published_run()
    market_id = base["market"]["id"]
    first = panel.create_client([market_id], name="Xenia Media Buying")
    second = panel.create_client([market_id], name="Yarrow Advertising")
    analysis = panel.delivered_custom_analysis(first["id"], base["run"]["id"])
    successor = panel.draft_rule_set(missing_interval_ascription_minutes=36)
    change = panel.draft_change(
        base["rule_set"]["id"], successor["id"], [market_id]
    )
    panel.assess_change(change["id"], base["run"]["id"])
    change = panel.notify_change(change["id"])
    rows, _meta = validate_paginated(
        panel.client.list_client_notifications(
            panel.rep, methodology_change_id=change["id"], limit=100
        )
    )
    notifications = {row["client_id"]: row for row in rows}
    return {
        "base": base,
        "first": first,
        "second": second,
        "analysis": analysis,
        "change": change,
        "notifications": notifications,
    }


class TestClientUserCrossClientWrites:
    """PRD 2.1's client-scoping check, evaluated right after the role check."""

    def test_a_subscriber_may_not_request_a_revision_on_a_peers_deliverable(
        self, panel: PanelHarness
    ):
        """The deliverable's own `client_id` is the only admitted caller.

        PRD 2.1: "a `ClientUser` requesting a revision on a deliverable is refused
        with `ERR_UNAUTHORIZED` unless `X-User-ID` equals that deliverable's
        `client_id`".

        Design: Corner/rbac/client_user_cross_client_writes_are_rejected_unauthorized
        """
        world = _two_subscribers_of_one_market(panel)
        analysis_id = world["analysis"]["id"]
        validate_error(
            panel.client.request_deliverable_revision(
                panel.client_headers(world["second"]["id"]),
                analysis_id,
                reason="Another subscriber's report, not ours.",
            ),
            "ERR_UNAUTHORIZED",
        )
        assert panel.read_deliverable(analysis_id)["state"] == "DELIVERED"
        revised = validate_success(
            panel.client.request_deliverable_revision(
                panel.client_headers(world["first"]["id"]),
                analysis_id,
                reason="The suburban cell breakdown is missing.",
            ),
            200,
        )
        assert revised["state"] == "REVISION_REQUESTED"
        assert revised["revision_count"] == 1

    def test_a_subscriber_may_not_acknowledge_a_peers_notification(
        self, panel: PanelHarness
    ):
        """The notification's own `client_id` is the only admitted caller.

        PRD 2.1: "a `ClientUser` acknowledging a notification is refused with
        `ERR_UNAUTHORIZED` unless `X-User-ID` equals that notification's
        `client_id`."

        Design: Corner/rbac/client_user_cross_client_writes_are_rejected_unauthorized
        """
        world = _two_subscribers_of_one_market(panel)
        first_id = world["first"]["id"]
        second_id = world["second"]["id"]
        assert set(world["notifications"]) == {first_id, second_id}
        mine = world["notifications"][first_id]
        validate_error(
            panel.client.acknowledge_notification(panel.client_headers(second_id), mine["id"]),
            "ERR_UNAUTHORIZED",
        )
        acknowledged = validate_success(
            panel.client.acknowledge_notification(panel.client_headers(first_id), mine["id"]),
            200,
        )
        assert acknowledged["state"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_at"] is not None
        change = panel.read_change(world["change"]["id"])
        assert change["notified_client_count"] == 2
        assert change["acknowledged_client_count"] == 1


class TestSegregationOfDutiesGates:
    """PRD 2.10's two-operator gates, keyed on `X-User-ID` alone."""

    def test_the_statistician_who_opened_a_run_may_not_publish_it(
        self, panel: PanelHarness, weighted_run
    ):
        """Self-publication is a 409, and a second operator then succeeds.

        PRD 3.7: "The acting `X-User-ID` must differ from the run's
        `opened_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The
        statistician who opened a run may not be the one who publishes it."

        Design: Corner/rbac/segregation_of_duties_gates_publish_and_finalize_by_user_id
        """
        run = weighted_run["run"]
        assert run["state"] == "WEIGHTED"
        opener = run["opened_by_user_id"]
        assert panel.statistician["X-User-ID"] == opener
        validate_error(
            panel.client.publish_processing_run(panel.statistician, run["id"]),
            "ERR_SEGREGATION_OF_DUTIES",
        )
        assert panel.read_run(run["id"])["state"] == "WEIGHTED"
        published = validate_success(
            panel.client.publish_processing_run(panel.publisher, run["id"]), 200
        )
        assert published["state"] == "PUBLISHED"
        assert published["published_by_user_id"] == STATISTICIAN_PUBLISHER_USER_ID
        assert published["published_by_user_id"] != opener

    def test_the_auditor_who_opened_an_audit_may_not_finalize_it(
        self, panel: PanelHarness, measurement_base
    ):
        """The duties gate is check 1, so it outranks the disclosure rule at check 3.

        PRD 3.9: "The acting `X-User-ID` must differ from the audit's
        `opened_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The auditor who
        opened an audit may not sign it off."

        Design: Corner/rbac/segregation_of_duties_gates_publish_and_finalize_by_user_id
        """
        audit = panel.open_audit(
            measurement_base["market"]["id"], measurement_base["rule_set"]["id"]
        )
        assert audit["state"] == "OPEN"
        assert audit["opened_by_user_id"] == panel.auditor["X-User-ID"]
        # A QUALIFIED outcome with no disclosures would fail check 3, but check 1
        # fires first for the opener.
        validate_error(
            panel.client.finalize_accreditation_audit(
                panel.auditor, audit["id"], outcome="QUALIFIED", limitation_disclosures=[]
            ),
            "ERR_SEGREGATION_OF_DUTIES",
        )
        assert panel.read_audit(audit["id"])["state"] == "OPEN"
        # A second auditor reaches check 3 with the same payload.
        validate_error(
            panel.client.finalize_accreditation_audit(
                panel.finalizer, audit["id"], outcome="QUALIFIED", limitation_disclosures=[]
            ),
            "ERR_DISCLOSURE_REQUIRED",
        )
        assert panel.read_audit(audit["id"])["state"] == "OPEN"

    def test_a_second_auditor_finalizes_and_the_freeze_is_released(
        self, panel: PanelHarness, measurement_base
    ):
        """An ACCREDITED outcome with an empty array is admitted from the peer.

        PRD 3.9: "For an `ACCREDITED` outcome the array may be empty."

        Design: Corner/rbac/segregation_of_duties_gates_publish_and_finalize_by_user_id
        """
        market_id = measurement_base["market"]["id"]
        audit = panel.open_audit(market_id, measurement_base["rule_set"]["id"])
        assert panel.read_market(market_id)["recruitment_posture"] == "FROZEN"
        finalized = validate_success(
            panel.client.finalize_accreditation_audit(
                panel.finalizer, audit["id"], outcome="ACCREDITED", limitation_disclosures=[]
            ),
            200,
        )
        assert finalized["state"] == "FINALIZED"
        assert finalized["outcome"] == "ACCREDITED"
        assert finalized["finalized_by_user_id"] == AUDITOR_FINALIZER_USER_ID
        assert finalized["finalized_by_user_id"] != finalized["opened_by_user_id"]
        # "the market's `open_audit_count` falls by one before the posture is
        # re-evaluated, which releases `FROZEN`" (PRD 3.9); the single cell is still
        # under target, so the posture lands back on OPEN.
        market = panel.read_market(market_id)
        assert market["open_audit_count"] == 0
        assert market["accreditation_status"] == "ACCREDITED"
        assert market["publication_blocked"] is False
        assert market["under_target_cell_count"] == 1
        assert market["recruitment_posture"] == "OPEN"
