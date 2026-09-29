"""The two multi-level cascades: an implemented amendment freezing a study, and
an audit refund moving a receivable from the payer to the sponsor.
"""

from test_helpers import (
    LIAISON_TWO,
    MANAGER_ONE,
    REVIEWER_ONE,
    api_client,
    build_budget,
    charge_review_payload,
    file_amendment,
    implement_amendment,
    item_spec,
    make_liaison_headers,
    make_manager_headers,
    make_reviewer_headers,
    post_charge,
    raise_invoice,
    read_calendar,
    read_charge,
    read_study,
    read_summary,
    resolve_finding,
    resolve_finding_payload,
    route_spec,
    set_clock,
    setup_open_to_accrual,
    setup_refundable_finding,
    validate_error,
    validate_paginated,
    visit_spec,
)

SPONSOR_ITEM = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    expected_occurrences=1,
)


def _study_ready_for_an_amendment(protocol_number, registry_number):
    """A protocol open to accrual with one published calendar, an executed
    budget and one interface charge still sitting unrouted and unbilled."""
    ctx = setup_open_to_accrual(
        [SPONSOR_ITEM],
        [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
        [route_spec("Cycle 1 Day 1", "J9999")],
        indirect_rate_pct=32.0,
        qct_registry_number=registry_number,
        study_overrides={
            "protocol_number": protocol_number,
            "funding_source": "INDUSTRY_SPONSORED",
        },
    )
    ctx["charge"] = post_charge(
        ctx["study"]["id"],
        charge_code="J9999",
        service_date="2026-08-01",
        amount_cents=40000,
    )
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


def _refundable(protocol_number="AMC-2390-H", registry_number="NCT10000010"):
    """A 9,000-cent payer-billed charge with a responded finding naming it, on a
    study whose indirect rate has been settled at 32.0 percent."""
    ctx = setup_refundable_finding(
        clock="2026-08-18T00:00:00Z",
        service_date="2026-08-18",
        amount_cents=9000,
        qct_registry_number=registry_number,
        study_overrides={
            "protocol_number": protocol_number,
            "funding_source": "INDUSTRY_SPONSORED",
        },
    )
    build_budget(ctx["study"]["id"], ctx["analysis"]["id"], indirect_rate_pct=32.0)
    ctx["study"] = read_study(ctx["study"]["id"])
    return ctx


class TestAmendmentImplementationFiresFiveLinks:
    """Each link is caused by the one before it, the last through a counter."""

    def test_01_an_item_and_schedule_change_walks_all_five_links(self):
        """Amendment, lifecycle and budget, calendar, counter and posture, then
        the charge hold — in one request.

        PRD §3.9: "The third link fires only when `calendar_rebuild_required` is
        also true: every calendar of the study whose `status` is `PUBLISHED`
        moves `PUBLISHED → REBUILD_REQUIRED`. The fourth link follows from the
        third: `rebuild_required_calendar_count` rises by one for each such
        calendar and the posture recomputes to `ALL_BLOCKED`. The fifth link
        follows from the fourth: every charge of the study whose `billing_state`
        is `UNBILLED` and whose `routing_state` is `UNROUTED`, walked
        oldest-created first, gets `hold_reason` set to `CALENDAR_REBUILD` and
        `hold_applied_at` set to the current logical instant."

        Design: Difficulty/transitive_cascade/amendment_implementation_five_level_rebuild_cascade
        """
        ctx = _study_ready_for_an_amendment("AMC-2390-E", "NCT10000009")
        assert ctx["calendar"]["status"] == "PUBLISHED"
        assert ctx["study"]["billing_hold_posture"] == "OPEN"
        assert ctx["study"]["budget_status"] == "EXECUTED"
        assert ctx["charge"]["hold_reason"] == "NONE"
        published_at = ctx["calendar"]["published_at"]

        set_clock("2026-08-15T08:00:00Z")
        amendment = file_amendment(
            ctx["study"]["id"],
            scope="ITEM_AND_SCHEDULE_CHANGE",
            effective_date="2026-08-14",
        )
        implemented = implement_amendment(amendment["id"])

        # Link 1.
        assert implemented["status"] == "IMPLEMENTED"
        assert implemented["reanalysis_required"] is True
        assert implemented["calendar_rebuild_required"] is True

        # Link 2.
        study = read_study(ctx["study"]["id"])
        assert study["lifecycle_status"] == "COVERAGE_PENDING"
        assert study["budget_status"] == "SUPERSEDED"

        # Link 3.
        calendar = read_calendar(ctx["calendar"]["id"])
        assert calendar["status"] == "REBUILD_REQUIRED"
        assert calendar["published_at"] == published_at

        # Link 4.
        assert study["rebuild_required_calendar_count"] == 1
        assert study["billing_hold_posture"] == "ALL_BLOCKED"

        # Link 5.
        charge = read_charge(ctx["charge"]["id"])
        assert charge["hold_reason"] == "CALENDAR_REBUILD"
        assert charge["hold_applied_at"] == "2026-08-15T08:00:00.000Z"
        assert charge["routing_state"] == "UNROUTED"
        assert charge["billing_state"] == "UNBILLED"

        # The consequence of link 4: the study is frozen for charge review.
        validate_error(
            api_client.review_charge(
                charge["id"],
                charge_review_payload("HOLD_FOR_SPONSOR"),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            "ERR_STUDY_BILLING_BLOCKED",
            409,
        )

    def test_02_an_item_change_stops_after_the_second_link(self):
        """`calendar_rebuild_required` is false, so links three through five
        never fire and the charge keeps its clean hold.

        PRD §3.9: "`calendar_rebuild_required` is true only for
        `VISIT_SCHEDULE_CHANGE` and `ITEM_AND_SCHEDULE_CHANGE`."

        Design: Difficulty/transitive_cascade/amendment_implementation_five_level_rebuild_cascade
        """
        ctx = _study_ready_for_an_amendment("AMC-2390-F", "NCT10000011")

        set_clock("2026-08-15T08:00:00Z")
        amendment = file_amendment(
            ctx["study"]["id"], scope="ITEM_CHANGE", effective_date="2026-08-14"
        )
        implemented = implement_amendment(amendment["id"])

        assert implemented["status"] == "IMPLEMENTED"
        assert implemented["reanalysis_required"] is True
        assert implemented["calendar_rebuild_required"] is False

        study = read_study(ctx["study"]["id"])
        assert study["lifecycle_status"] == "COVERAGE_PENDING"
        assert study["budget_status"] == "SUPERSEDED"

        assert read_calendar(ctx["calendar"]["id"])["status"] == "PUBLISHED"
        assert study["rebuild_required_calendar_count"] == 0
        # Clause 3 of the posture rule cannot fire either: the study is
        # determined, so the posture is exactly OPEN.
        assert study["billing_hold_posture"] == "OPEN"

        charge = read_charge(ctx["charge"]["id"])
        assert charge["hold_reason"] == "NONE"


class TestAuditRefundReroutesAndRebalances:
    """A refund creates a row rather than blocking rows."""

    def test_03_the_resolution_refunds_replaces_and_recomputes(self):
        """Finding, charge, replacement row, ledger and posture, in one request.

        PRD §3.9: "A replacement charge is then created carrying `source`
        `REFUND_REPLACEMENT` and `replaces_charge_id` pointing at the refunded
        row, copying that row's `charge_code`, `service_date`, `amount_cents`,
        `study_id`, and `coverage_item_id`, opening at `routing_state`
        `ROUTED_SPONSOR` and `billing_state` `UNBILLED` with `unbilled_since` set
        to the current logical instant and `hold_reason` `NONE` — so the money
        moves off the payer and onto the sponsor's invoiceable pool in the same
        request."

        Design: Difficulty/transitive_cascade/audit_refund_resolution_reroutes_and_rebalances_ledger
        """
        ctx = _refundable()
        assert ctx["charge"]["billing_state"] == "BILLED_PAYER"
        assert ctx["study"]["open_finding_count"] == 1
        assert ctx["study"]["billing_hold_posture"] == "ALL_BLOCKED"
        assert ctx["study"]["effective_indirect_rate_pct"] == 32.0

        set_clock("2026-08-20T10:30:00Z")
        resolved = resolve_finding(ctx["finding"]["id"], "REFUND_AND_REROUTE")

        # Link 1.
        assert resolved["status"] == "CLOSED_REFUNDED"
        assert resolved["refund_amount_cents"] == 9000

        # Link 2.
        refunded = read_charge(ctx["charge"]["id"])
        assert refunded["billing_state"] == "REFUNDED"
        assert refunded["refunded_amount_cents"] == 9000
        assert refunded["routing_state"] == "ROUTED_PAYER"

        # Link 3.
        rows, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={
                    "study_id": ctx["study"]["id"],
                    "replaces_charge_id": ctx["charge"]["id"],
                },
            )
        )
        assert meta["total_count"] == 1
        replacement = rows[0]
        assert replacement["source"] == "REFUND_REPLACEMENT"
        assert replacement["replaces_charge_id"] == ctx["charge"]["id"]
        assert replacement["routing_state"] == "ROUTED_SPONSOR"
        assert replacement["billing_state"] == "UNBILLED"
        assert replacement["amount_cents"] == 9000
        assert replacement["charge_code"] == "80053"
        assert replacement["service_date"] == "2026-08-18"
        assert replacement["hold_reason"] == "NONE"
        assert replacement["unbilled_since"] == "2026-08-20T10:30:00.000Z"
        assert replacement["coverage_item_id"] == refunded["coverage_item_id"]

        # Link 4.
        study = read_study(ctx["study"]["id"])
        assert study["payer_billed_cents"] == 0
        assert study["payer_refunded_cents"] == 9000
        assert study["sponsor_unbilled_cents"] == 9000
        assert study["open_finding_count"] == 0
        assert study["billing_hold_posture"] == "OPEN"

        # The replacement is invoiceable the moment it exists.
        invoice = raise_invoice(study["id"], period_end_date="2026-08-31")
        assert invoice["line_count"] == 1
        assert invoice["subtotal_cents"] == 9000
        assert invoice["indirect_cents"] == 2880
        assert invoice["gross_total_cents"] == 11880
        assert invoice["volume_credit_cents"] == 0
        assert invoice["net_total_cents"] == 11880

    def test_04_a_no_action_disposition_mutates_no_charge_at_all(self):
        """The other fork of the resolution shares only the posture recompute.

        PRD §3.9: "A `disposition` of `NO_ACTION` moves the finding `RESPONDED →
        CLOSED_NO_ACTION`, leaves `refund_amount_cents` at zero, and mutates no
        charge whatsoever."

        Design: Difficulty/transitive_cascade/audit_refund_resolution_reroutes_and_rebalances_ledger
        """
        ctx = _refundable(protocol_number="AMC-2390-H2", registry_number="NCT10000012")
        before = read_charge(ctx["charge"]["id"])

        set_clock("2026-08-20T10:30:00Z")
        resolved = resolve_finding(ctx["finding"]["id"], "NO_ACTION")

        assert resolved["status"] == "CLOSED_NO_ACTION"
        assert resolved["refund_amount_cents"] == 0

        after = read_charge(ctx["charge"]["id"])
        assert after["billing_state"] == "BILLED_PAYER"
        assert after["routing_state"] == "ROUTED_PAYER"
        assert after["refunded_amount_cents"] == before["refunded_amount_cents"]
        assert after["version"] == before["version"]

        rows, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["charge"]["id"]

        study = read_study(ctx["study"]["id"])
        assert study["payer_billed_cents"] == 9000
        assert study["payer_refunded_cents"] == 0
        assert study["open_finding_count"] == 0
        assert study["billing_hold_posture"] == "OPEN"


class TestAuditRefundConservesThePayerPosition:
    """The refund is a compensating action, not a deletion."""

    def test_05_the_payer_position_sum_survives_the_refund(self):
        """9,000 cents move from one component of the payer position to the
        other, and an equal sponsor obligation opens.

        PRD §2.8: "The **payer position** — `payer_billed_cents` plus
        `payer_refunded_cents` — is unchanged by refunding a payer-billed
        charge."

        Design: Difficulty/compensating_invariant/audit_refund_conserves_total_payer_position
        """
        ctx = _refundable(protocol_number="AMC-2390-H3", registry_number="NCT10000013")
        before = read_summary(ctx["study"]["id"])
        assert before["payer_billed_cents"] == 9000
        assert before["payer_refunded_cents"] == 0
        assert before["sponsor_unbilled_cents"] == 0
        payer_position = before["payer_billed_cents"] + before["payer_refunded_cents"]
        assert payer_position == 9000

        set_clock("2026-08-20T10:30:00Z")
        resolved = resolve_finding(ctx["finding"]["id"], "REFUND_AND_REROUTE")
        assert resolved["status"] == "CLOSED_REFUNDED"
        assert resolved["refund_amount_cents"] == 9000

        after = read_summary(ctx["study"]["id"])
        assert after["payer_billed_cents"] == 0
        assert after["payer_refunded_cents"] == 9000
        assert after["payer_billed_cents"] + after["payer_refunded_cents"] == payer_position
        assert after["sponsor_unbilled_cents"] == 9000

    def test_06_the_original_row_survives_and_the_compensation_cannot_replay(self):
        """Nothing is deleted or overwritten, and a second resolution attempt is
        refused, so the invariant cannot be broken by replaying it.

        PRD §3.9: "Resolution then takes a `disposition` and forks into two
        disjoint outcomes; resolving a finding that is not `RESPONDED` is
        `ERR_FINDING_NOT_RESPONDED`."

        Design: Difficulty/compensating_invariant/audit_refund_conserves_total_payer_position
        """
        ctx = _refundable(protocol_number="AMC-2390-H4", registry_number="NCT10000020")
        set_clock("2026-08-20T10:30:00Z")
        resolve_finding(ctx["finding"]["id"], "REFUND_AND_REROUTE")

        original = read_charge(ctx["charge"]["id"])
        assert original["id"] == ctx["charge"]["id"]
        assert original["routing_state"] == "ROUTED_PAYER"
        assert original["billing_state"] == "REFUNDED"
        assert original["amount_cents"] == 9000
        assert original["refunded_amount_cents"] == 9000

        validate_error(
            api_client.resolve_audit_finding(
                ctx["finding"]["id"],
                resolve_finding_payload("REFUND_AND_REROUTE"),
                make_liaison_headers(LIAISON_TWO),
            ),
            "ERR_FINDING_NOT_RESPONDED",
            409,
        )

        after = read_summary(ctx["study"]["id"])
        assert after["payer_billed_cents"] == 0
        assert after["payer_refunded_cents"] == 9000
        assert after["sponsor_unbilled_cents"] == 9000

        _, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={
                    "study_id": ctx["study"]["id"],
                    "replaces_charge_id": ctx["charge"]["id"],
                },
            )
        )
        assert meta["total_count"] == 1
