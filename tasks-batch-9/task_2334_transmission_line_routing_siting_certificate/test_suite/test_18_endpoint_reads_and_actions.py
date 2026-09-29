"""Endpoint shapes: filtered listings, reading orders and releasing actions.

These exercise the read side of the contract — pagination metadata, documented
collection ordering — together with the writes whose whole point is to release
a counter that some earlier write had reserved.
"""

from test_helpers import (
    assert_is_null,
    assert_timestamp_equals,
    get_success_data,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestFilteredListing:
    """Domain filters narrow the count before the pagination window is applied."""

    def test_projects_filtered_by_state_and_windowed_report_the_full_count(self, api):
        """PRD §2.3: "The four pagination fields reported in `meta` are `limit`,
        `offset`, `total_count` (the number of rows matching the filters before the
        window is applied) and `has_more` (true when rows remain beyond the current
        window)." Projects accept a `jurisdiction_state` filter.

        Design: Corner/endpoints/projects_listing_filtered_by_state_and_paginated
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.create_project(
            api, ctx, key="proj_other", name="Unrelated Clay Loop",
            voltage_class="KV_138", jurisdiction_state="KY",
            target_energization_at="2030-04-01T00:00:00Z",
        )

        data, meta = validate_paginated(
            api.list_projects(
                fx.COMMISSION_STAFF_HEADERS,
                {"jurisdiction_state": "KY", "limit": 1, "offset": 1},
            )
        )

        assert meta["total_count"] == 2, (
            f"Both Kentucky projects match the filter, got {meta['total_count']}"
        )
        assert meta["limit"] == 1, f"The supplied limit is echoed, got {meta['limit']}"
        assert meta["offset"] == 1, f"The supplied offset is echoed, got {meta['offset']}"
        assert meta["has_more"] is False, (
            f"The second row is the last one, so nothing remains beyond it, got "
            f"{meta['has_more']}"
        )
        assert len(data) == 1, (
            f"A limit of 1 returns a single row, got {len(data)}"
        )


class TestLogicalClockDrivenWindow:
    """Every minted instant is measured from the logical clock, never wall time."""

    def test_the_comment_window_closes_days_after_the_clock_reading(self, api):
        """PRD §3.4: "Publication moves the route `CONSTRAINT_MAPPED →
        PUBLISHED_FOR_COMMENT` and sets `comment_window_closes_at` to the logical clock
        reading plus that many days." PRD §2.6: "Adding a comment window of
        `comment_window_days` days ... means adding that many whole days to the
        reference instant."

        Design: Corner/endpoints/logical_clock_drives_the_published_comment_window
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.build_route_a(api, ctx)
        fx.set_clock(api, "2026-09-15T00:00:00Z")

        route = validate_success(
            api.publish_route(
                ctx["routeA"], f.publication_payload(comment_window_days=90),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert route["status"] == "PUBLISHED_FOR_COMMENT", (
            f"Publication lands the corridor in comment, got {route['status']}"
        )
        assert_timestamp_equals(
            route["comment_window_closes_at"], "2026-12-14T00:00:00Z",
            "comment_window_closes_at",
        )


class TestEscrowLedger:
    """Deposits accumulate on two of the four figures and on neither of the others."""

    def test_two_deposits_accumulate_on_the_funded_total_and_the_balance(self, api):
        """PRD §2.9: "A conservation invariant holds after every single operation: the
        funded total always equals the undisbursed balance plus the disbursed total.
        Depositing into escrow adds the deposited `amount_cents` to both the funded
        total and the balance, recording the client-supplied `reference` for audit."

        Design: Corner/endpoints/escrow_deposits_accumulate_on_the_conservation_triple
        """
        ctx = {}
        fx.create_project(api, ctx)

        get_success_data(
            api.create_escrow_deposit(
                ctx["proj"],
                f.escrow_deposit_payload(amount_cents=400_000_000, reference="ESCROW-A"),
                fx.DEVELOPER_HEADERS,
            )
        )
        validate_success(
            api.create_escrow_deposit(
                ctx["proj"],
                f.escrow_deposit_payload(amount_cents=300_000_000, reference="ESCROW-B"),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        project = fx.read_project(api, ctx)
        assert project["escrow_funded_cents"] == 700_000_000, (
            f"Both deposits are on the funded total, got "
            f"{project['escrow_funded_cents']}"
        )
        assert project["escrow_balance_cents"] == 700_000_000, (
            f"Nothing has been disbursed, so the whole sum is available, got "
            f"{project['escrow_balance_cents']}"
        )
        assert project["escrow_disbursed_cents"] == 0, (
            f"A deposit never touches the disbursed total, got "
            f"{project['escrow_disbursed_cents']}"
        )
        assert (
            project["escrow_funded_cents"]
            == project["escrow_balance_cents"] + project["escrow_disbursed_cents"]
        ), "The conservation invariant holds after the second deposit"


class TestCommentDisposition:
    """Answering a comment is how the nomination blocker is cleared."""

    def test_dismissing_a_material_comment_releases_the_segment_counter(self, api):
        """PRD §3.4: "Disposing of a `MATERIAL` comment out of `RECEIVED` decrements the
        named segment's material comment count, which is how an analyst clears the
        nomination blocker by answering comments rather than by redesigning."

        Design: Corner/endpoints/comment_dismissal_releases_the_material_count
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.build_route_a(api, ctx)
        fx.publish_route_a(api, ctx)
        comment = get_success_data(
            api.create_public_comment(
                f.public_comment_payload(
                    ctx["routeA"], commenter_kind="PUBLIC", commenter_name="Nell Ford",
                    body="Shift the alignment off the ridge above the school",
                    materiality="MATERIAL", segment_id=ctx["seg1"],
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )

        dispositioned = validate_success(
            api.disposition_public_comment(
                comment["id"],
                f.comment_disposition_payload(
                    disposition="DISMISS",
                    disposition_note="Alignment already avoids the school parcel",
                ),
                fx.ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert dispositioned["status"] == "DISMISSED", (
            f"A dismissal is terminal for the comment, got {dispositioned['status']}"
        )
        assert dispositioned["disposition_note"] == (
            "Alignment already avoids the school parcel"
        ), f"The written answer is stored, got {dispositioned['disposition_note']!r}"
        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["material_comment_count"] == 0, (
            f"The dismissal released the blocker on segment 1, got "
            f"{segment['material_comment_count']}"
        )
        assert segment["survey_status"] == "FIELD_VERIFIED", (
            "Answering a comment is not a refinement, so no survey upgrade happened"
        )
        route = fx.read_route(api, ctx["routeA"])
        assert route["status"] == "PUBLISHED_FOR_COMMENT", (
            f"The corridor is still in its comment window, got {route['status']}"
        )
        assert route["refinement_round"] == 0, (
            f"No refinement cycle was run, got {route['refinement_round']}"
        )


class TestConditionReadOrder:
    """The order's condition array is the reading order of the collection."""

    def test_conditions_read_back_in_the_order_the_order_supplied_them(self, api):
        """PRD §2.3: "a certificate's conditions are returned `created_at` ascending,
        which is the order in which the order's condition array supplied them."

        Design: Corner/endpoints/certificate_conditions_read_back_in_order_supplied
        """
        ctx = fx.setup_issued_certificate(api)

        conditions, meta = validate_paginated(
            api.list_certificate_conditions(
                fx.COMPLIANCE_MONITOR_HEADERS, {"certificate_id": ctx["cert"]}
            )
        )

        assert meta["total_count"] == 3, (
            f"The order carried three conditions, got {meta['total_count']}"
        )
        assert conditions[0]["code"] == "ENV-BLACKOUT-1", (
            f"The first supplied condition reads back first, got "
            f"{conditions[0]['code']!r}"
        )
        assert conditions[0]["blackout_start_mmdd"] == "04-01", (
            f"The blackout window is stored on the first condition, got "
            f"{conditions[0]['blackout_start_mmdd']!r}"
        )
        assert conditions[0].get("crew_limit") is None, (
            f"A seasonal blackout carries no crew ceiling, got "
            f"{conditions[0].get('crew_limit')!r}"
        )
        assert conditions[1]["code"] == "CUL-MON-1", (
            f"The second supplied condition reads back second, got "
            f"{conditions[1]['code']!r}"
        )
        assert conditions[1].get("blackout_start_mmdd") is None, (
            f"A monitoring condition carries no blackout window, got "
            f"{conditions[1].get('blackout_start_mmdd')!r}"
        )
        assert conditions[2]["code"] == "ENG-CREW-1", (
            f"The third supplied condition reads back third, got "
            f"{conditions[2]['code']!r}"
        )
        assert conditions[2]["crew_limit"] == 9, (
            f"The crew ceiling is stored on the third condition, got "
            f"{conditions[2]['crew_limit']}"
        )
        assert conditions[2]["status"] == "ACTIVE", (
            f"Every minted condition opens ACTIVE, got {conditions[2]['status']}"
        )


class TestActivityCancellation:
    """Cancellation hands the crew slots back to the segment."""

    def test_cancelling_a_scheduled_activity_releases_the_committed_crew(self, api):
        """PRD §3.9: "**Cancellation** — carrying a `cancellation_reason` — moves an
        activity `SCHEDULED → CANCELLED` or `SUSPENDED → CANCELLED` and releases the
        segment's committed crew by that activity's crew count."

        Design: Corner/endpoints/activity_cancellation_releases_the_committed_crew
        """
        ctx = fx.setup_issued_certificate(api)
        activity = get_success_data(
            api.create_construction_activity(
                f.construction_activity_payload(
                    ctx["cert"], ctx["seg2"], activity_kind="CLEARING", crew_count=6,
                    window_start_at="2027-09-01T00:00:00Z",
                    window_end_at="2027-09-10T00:00:00Z",
                ),
                fx.DEVELOPER_HEADERS,
            )
        )

        cancelled = validate_success(
            api.cancel_activity(
                activity["id"],
                f.activity_cancellation_payload(
                    cancellation_reason="Crew reassigned to the water crossing"
                ),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert cancelled["status"] == "CANCELLED", (
            f"Cancellation is terminal for the activity, got {cancelled['status']}"
        )
        assert_is_null(cancelled, "started_at", "ConstructionActivity")
        segment = fx.read_segment(api, ctx["seg2"])
        assert segment["committed_crew_count"] == 0, (
            f"The reserved crew slots were handed back, got "
            f"{segment['committed_crew_count']}"
        )
        assert segment["construction_state"] == "PENDING", (
            f"No activity ever started, so the segment never opened, got "
            f"{segment['construction_state']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "CERTIFICATED", (
            "The project never reached CONSTRUCTION"
        )


class TestFederalPermitIssuance:
    """The permit dimension comes to rest at ISSUED, segment by segment."""

    def test_issuing_the_waterway_permit_reaches_the_terminal_state(self, api):
        """PRD §3.3: "From `APPLIED`, issuing the permit moves the segment to the
        terminal `ISSUED` ... `NOT_REQUIRED` and `ISSUED` are the two terminal resting
        places of this dimension."

        Design: Corner/endpoints/federal_permit_issuance_reaches_the_terminal_permit_state
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.create_route(api, ctx, key="routeA")
        for index, spec in enumerate(fx.ROUTE_A_SEGMENTS[:2], start=1):
            fx.add_segment(api, ctx, "routeA", f"seg{index}", **dict(spec))
        fx.apply_for_federal_permit(api, ctx, segment_key="seg2", agency="USACE")

        issuance = f.federal_permit_action_payload(
            action="ISSUE",
            determination_note="Section 10 authorization granted",
        )
        issuance.pop("agency")

        segment = validate_success(
            api.record_federal_permit_action(
                ctx["seg2"], issuance, fx.FEDERAL_PERMIT_OFFICER_HEADERS
            ),
            expected_status=201,
        )

        assert segment["federal_permit_status"] == "ISSUED", (
            f"The waterway crossing is permitted, got "
            f"{segment['federal_permit_status']}"
        )
        assert segment["federal_permit_agency"] == "USACE", (
            f"The acting agency is retained, got {segment['federal_permit_agency']!r}"
        )
        assert fx.read_segment(api, ctx["seg1"])["federal_permit_status"] == (
            "NOT_REQUIRED"
        ), "The segment with no crossing needs no permit at all"
