"""Containers: placement, satellite limits, moves, deadlines, voids, labels,
inspections, staging gates, and the monthly generation ledger."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, create_container_payload, move_container_payload,
    label_container_payload, create_inspection_payload,
    create_site, create_stream, create_active_stream, create_area,
    create_container, get_container, move_container, label_container,
    inspect_container, stage_container, set_clock, get_site, get_stream,
    setup_site_stream_areas, ehs_headers, wc_headers,
    assert_container, assert_instant_equals, assert_site_category_invariants,
)


class TestContainerCreation:
    def test_container_unknown_field_rejected_input_ignored(self, api):
        """PRD §2.9: "fifth, request shape — required fields present, types
        matching, enum members valid, unknown request fields rejected, quantities
        strictly positive, `coverage_to` strictly later than `coverage_from`
        (`ERR_INVALID_REQUEST`)". A client-supplied `version` is an unknown
        request field; the server mints it.

        Design: Corner/entities/container_unknown_field_rejected_input_ignored
        """
        env = setup_site_stream_areas()
        payload = create_container_payload(
            env["stream"]["id"], env["central"]["id"], 10, 50.0)
        payload["version"] = 99
        res = api.create_container(payload, wc_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_container_central_create_computed_fields(self, api):
        """PRD §3.2: "A container created into a `CENTRAL_90DAY` area enters
        `IN_CENTRAL_ACCUMULATION` immediately: `accumulation_start_date` is set to
        the current logical instant and `accumulation_deadline_at` is computed from
        it." PRD §3.3: "`SQG` or `VSQG` grants 180 days" and
        "`accumulation_deadline_at` is the start instant plus `deadline_days`
        whole days." PRD §3.2: "The container's own `site_id` is derived from the
        area's site, never taken from the request".

        Design: Corner/entities/container_central_create_computed_fields
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 50.0, "wc-1")
        assert_container(container)
        assert container["status"] == "IN_CENTRAL_ACCUMULATION"
        assert_instant_equals(container["accumulation_start_date"],
                              "2026-08-01T00:00:00Z", "accumulation_start_date")
        assert container["deadline_days"] == 180
        assert_instant_equals(container["accumulation_deadline_at"],
                              "2027-01-28T00:00:00Z", "accumulation_deadline_at")
        assert container["is_labeled"] is False
        assert container["is_inspection_overdue"] is False
        assert container["is_accumulation_overdue"] is False
        assert container["site_id"] == env["site"]["id"]

    def test_container_initial_state_satellite_vs_central(self, api):
        """PRD §3.2: "A container created into a `SATELLITE` area enters
        `ACCUMULATING_AT_SATELLITE` with no central clock running —
        `accumulation_start_date` stays null" and "A container created into a
        `CENTRAL_90DAY` area enters `IN_CENTRAL_ACCUMULATION` immediately".

        Design: Corner/state_machines/container_initial_state_satellite_vs_central
        """
        env = setup_site_stream_areas(with_satellite=True)
        sat = create_container(env["stream"]["id"], env["satellite"]["id"], 10, 50.0)
        cen = create_container(env["stream"]["id"], env["central"]["id"], 10, 50.0)
        assert sat["status"] == "ACCUMULATING_AT_SATELLITE"
        assert sat["accumulation_start_date"] is None
        assert cen["status"] == "IN_CENTRAL_ACCUMULATION"
        assert_instant_equals(cen["accumulation_start_date"],
                              "2026-08-01T00:00:00Z", "accumulation_start_date")

    def test_container_create_cross_site_area_rejected(self, api):
        """PRD §3.2: "Creation requires the stream to be `ACTIVE` (otherwise
        `ERR_STREAM_NOT_ACTIVE`) and the area to belong to the same site as the
        stream (otherwise `ERR_CROSS_SITE_REFERENCE`)".

        Design: Corner/entities/container_create_cross_site_area_rejected
        """
        site_a = create_site("Site A", "EPA-SITE-A")
        site_b = create_site("Site B", "EPA-SITE-B")
        stream = create_active_stream(site_a["id"])
        area_b = create_area(site_b["id"], "Central B")
        res = api.create_container(
            create_container_payload(stream["id"], area_b["id"], 10, 50.0),
            wc_headers())
        validate_error(res, ApiErrorId.ERR_CROSS_SITE_REFERENCE)
        _, meta = validate_paginated(
            api.list_containers(ehs_headers(), params={"site_id": site_a["id"]}))
        assert meta["total_count"] == 0

    def test_container_create_on_inactive_stream_rejected(self, api):
        """PRD §3.2: "Creation requires the stream to be `ACTIVE` (otherwise
        `ERR_STREAM_NOT_ACTIVE`)".

        Design: Corner/validations/container_create_on_inactive_stream_rejected
        """
        site = create_site()
        stream = create_stream(site["id"])  # stays DRAFT
        area = create_area(site["id"])
        res = api.create_container(
            create_container_payload(stream["id"], area["id"], 10, 50.0),
            wc_headers())
        validate_error(res, ApiErrorId.ERR_STREAM_NOT_ACTIVE)


class TestSatelliteLimit:
    def test_satellite_55_gallon_boundary_and_late_move(self, api):
        """PRD §3.3: "When a newly created container pushes that per-stream total
        strictly over 55.0 gallons, the incoming container alone transitions to
        `SATELLITE_LIMIT_EXCEEDED`; `satellite_exceeded_at` is stamped with the
        current instant and `move_deadline_at` is set to three days after it. At
        exactly 55.0 gallons the limit is not exceeded, and pre-existing
        containers in the area are untouched — only the container whose arrival
        crossed the line flips." and "computes `is_move_late`: true when the
        container is leaving `SATELLITE_LIMIT_EXCEEDED` and the move happens
        strictly after `move_deadline_at`, false in every other case."

        Design: Corner/state_machines/satellite_55_gallon_boundary_and_late_move
        """
        env = setup_site_stream_areas(with_satellite=True)
        stream_id, saa, cen = (env["stream"]["id"], env["satellite"]["id"],
                               env["central"]["id"])
        c1 = create_container(stream_id, saa, 30.0, 100.0)
        c2 = create_container(stream_id, saa, 25.0, 80.0)
        # Exactly 55.0 gallons: the boundary is not exceeded.
        assert get_container(c1["id"])["status"] == "ACCUMULATING_AT_SATELLITE"
        assert get_container(c2["id"])["status"] == "ACCUMULATING_AT_SATELLITE"
        # 55.0 + 0.1 > 55.0: only the incoming container flips.
        c3 = create_container(stream_id, saa, 0.1, 1.0)
        assert c3["status"] == "SATELLITE_LIMIT_EXCEEDED"
        assert_instant_equals(c3["satellite_exceeded_at"],
                              "2026-08-01T00:00:00Z", "satellite_exceeded_at")
        assert_instant_equals(c3["move_deadline_at"],
                              "2026-08-04T00:00:00Z", "move_deadline_at")
        # Move after the 3-day grace: the move is late.
        set_clock("2026-08-05T00:00:00Z")
        moved = move_container(c3["id"], cen, mover="wc-7")
        assert moved["status"] == "IN_CENTRAL_ACCUMULATION"
        assert moved["is_move_late"] is True
        # Pre-existing containers are untouched by the exceedance.
        assert get_container(c1["id"])["status"] == "ACCUMULATING_AT_SATELLITE"
        assert get_container(c2["id"])["status"] == "ACCUMULATING_AT_SATELLITE"


class TestContainerMove:
    def test_move_to_satellite_area_rejected_then_central_succeeds(self, api):
        """PRD §3.3: "The target area must exist, must have `area_type`
        `CENTRAL_90DAY` (otherwise `ERR_AREA_TYPE_MISMATCH`)" and "The move
        rewrites `accumulation_area_id`, sets `accumulation_start_date` to the
        current instant, snapshots the accumulation allowance".

        Design: Difficulty/cross_entity_state_dependency/container_move_requires_central_area_type
        """
        env = setup_site_stream_areas(with_satellite=True)
        container = create_container(
            env["stream"]["id"], env["satellite"]["id"], 20, 50.0, "wc-1")
        assert container["status"] == "ACCUMULATING_AT_SATELLITE"
        res = api.move_container(
            container["id"], move_container_payload(env["satellite"]["id"]),
            wc_headers())
        validate_error(res, ApiErrorId.ERR_AREA_TYPE_MISMATCH)
        moved = move_container(container["id"], env["central"]["id"])
        assert moved["status"] == "IN_CENTRAL_ACCUMULATION"
        assert_instant_equals(moved["accumulation_start_date"],
                              "2026-08-01T00:00:00Z", "accumulation_start_date")
        assert moved["deadline_days"] == 180, "site is VSQG at 50 kg"
        assert moved["is_move_late"] is False

    def test_move_to_other_sites_area_rejected(self, api):
        """PRD §3.3: "The target area must exist, must have `area_type`
        `CENTRAL_90DAY` (otherwise `ERR_AREA_TYPE_MISMATCH`), and must belong to
        the same site as the container (otherwise `ERR_CROSS_SITE_REFERENCE`)".

        Design: Difficulty/cross_entity_state_dependency/container_move_requires_central_area_type
        """
        env = setup_site_stream_areas(with_satellite=True)
        other = create_site("Site B", "EPA-SITE-B")
        foreign_central = create_area(other["id"], "Central B")
        container = create_container(
            env["stream"]["id"], env["satellite"]["id"], 20, 50.0, "wc-1")
        res = api.move_container(
            container["id"], move_container_payload(foreign_central["id"]),
            wc_headers())
        validate_error(res, ApiErrorId.ERR_CROSS_SITE_REFERENCE)
        assert get_container(container["id"])["status"] == "ACCUMULATING_AT_SATELLITE"


class TestImmediateConsistency:
    def test_writes_visible_immediately(self, api):
        """PRD §2.7: "The system is a web of derived state rather than a set of
        isolated records, and mutations cascade through it immediately." PRD §2.2:
        "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/writes_visible_immediately
        """
        env = setup_site_stream_areas()
        created = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 50.0)
        assert_instant_equals(created["accumulation_deadline_at"],
                              "2027-01-28T00:00:00Z", "accumulation_deadline_at")
        fetched = get_container(created["id"])
        assert fetched["deadline_days"] == 180
        assert_instant_equals(fetched["accumulation_deadline_at"],
                              created["accumulation_deadline_at"],
                              "accumulation_deadline_at")
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == 50.0


class TestMonthlyLedger:
    def test_month_rollover_resets_totals(self, api):
        """PRD §2.5: "First, calendar-month rollover: any site whose logical month
        has changed resets its monthly generation total to zero, updates its
        `current_month_key` to the new month in `YYYY-MM` format, and re-evaluates
        its generator category from that zeroed total."

        Design: Corner/calculations/month_rollover_resets_totals
        """
        env = setup_site_stream_areas()
        create_container(env["stream"]["id"], env["central"]["id"], 10, 700.0)
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == 700.0
        assert site["generator_category"] == "SQG"
        set_clock("2026-09-01T00:00:00Z")
        site = get_site(env["site"]["id"])
        assert site["current_month_key"] == "2026-09"
        assert site["current_month_generated_kg"] == 0.0
        assert site["generator_category"] == "VSQG"
        stream = get_stream(env["stream"]["id"])
        assert stream["total_generated_kg"] == 700.0, "lifetime total not reset"

    def test_generator_category_exactly_1000kg(self, api):
        """PRD §2.6: "When the total reaches at least 1000.0 kilograms the
        category is `LQG`; when the total is strictly above 100.0 kilograms but
        below 1000.0 the category is `SQG`; otherwise the category is `VSQG`.
        Boundaries are exact: a site at exactly 100.0 kilograms remains `VSQG`,
        and a site at exactly 1000.0 kilograms is `LQG`."

        Design: Difficulty/boundary_precision_check/generator_category_exactly_1000kg
        """
        env = setup_site_stream_areas()
        create_container(env["stream"]["id"], env["central"]["id"], 10, 999.9)
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == pytest.approx(999.9, abs=1e-6)
        assert site["generator_category"] == "SQG", "1000.0 not yet reached"
        create_container(env["stream"]["id"], env["central"]["id"], 1, 0.1)
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == pytest.approx(1000.0, abs=1e-6)
        assert site["generator_category"] == "LQG", ">= boundary inclusive"

    def test_generator_category_exactly_100kg(self, api):
        """PRD §2.6: "a site at exactly 100.0 kilograms remains `VSQG`" and "when
        the total is strictly above 100.0 kilograms but below 1000.0 the category
        is `SQG`".

        Design: Difficulty/boundary_precision_check/generator_category_exactly_1000kg
        """
        env = setup_site_stream_areas()
        create_container(env["stream"]["id"], env["central"]["id"], 10, 100.0)
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == pytest.approx(100.0, abs=1e-6)
        assert site["generator_category"] == "VSQG", "exclusive lower bound"
        create_container(env["stream"]["id"], env["central"]["id"], 1, 0.1)
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == pytest.approx(100.1, abs=1e-6)
        assert site["generator_category"] == "SQG"


class TestVoidCompensation:
    def test_container_void_restores_month_mass(self, api):
        """PRD §3.3: "Voiding is a compensating reversal through the same
        three-hop cascade as creation: the month's total is decremented by the
        container's `quantity_kg` (only when the container was created in the
        site's current month), the category is re-evaluated and flips downward on
        a threshold crossing, every `DRAFT` BiennialReport of the site recomputes
        its provisional fee, and the stream's `total_generated_kg` is
        decremented."

        Design: Difficulty/compensating_invariant/container_void_restores_month_mass
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 250.0, "wc-1")
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == 250.0
        assert site["generator_category"] == "SQG"
        voided = validate_success(
            api.void_container(container["id"], wc_headers("wc-1")))
        assert voided["status"] == "VOIDED"
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == 0.0, "no drift after the pair"
        assert site["generator_category"] == "VSQG"
        assert get_stream(env["stream"]["id"])["total_generated_kg"] == 0.0

    def test_container_void_in_later_month_leaves_current_month_untouched(self, api):
        """PRD §2.6: "voiding a container subtracts it (only when the voided
        container was created in the current month — containers created in
        earlier months belong to those months forever)". PRD §3.3: "the stream's
        `total_generated_kg` is decremented."

        Design: Difficulty/compensating_invariant/container_void_restores_month_mass
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 100.0, "wc-1")
        set_clock("2026-09-01T00:00:00Z")  # rollover zeroes the site month total
        validate_success(api.void_container(container["id"], wc_headers("wc-1")))
        site = get_site(env["site"]["id"])
        assert site["current_month_key"] == "2026-09"
        assert site["current_month_generated_kg"] == 0.0, (
            "August's container belongs to August forever")
        assert get_stream(env["stream"]["id"])["total_generated_kg"] == 0.0
        assert get_container(container["id"])["status"] == "VOIDED"


class TestAccumulationDeadlineSnapshot:
    def _setup_three_containers(self):
        """A (500 kg) and B (500 kg) in August; rollover; C (1000 kg) in October."""
        env = setup_site_stream_areas()
        a = create_container(env["stream"]["id"], env["central"]["id"], 20, 500.0)
        b = create_container(env["stream"]["id"], env["central"]["id"], 20, 500.0)
        set_clock("2026-10-01T00:00:00Z")
        c = create_container(env["stream"]["id"], env["central"]["id"], 20, 1000.0)
        return env, a, b, c

    def test_deadline_snapshotted_at_accumulation_start_not_current(self, api):
        """PRD §3.3: "The accumulation allowance is snapshotted from the site's
        `generator_category` at the exact moment `accumulation_start_date` is set
        — a site category of `LQG` at that moment grants 90 days; `SQG` or `VSQG`
        grants 180 days. This is the category-at-start rule: once `deadline_days`
        is snapshotted, later flips of the site's category never move an existing
        container's deadline."

        Design: Difficulty/dual_variant_calc/accumulation_deadline_category_at_start_vs_current
        """
        env, a, _, _ = self._setup_three_containers()
        set_clock("2026-10-31T00:00:00Z")
        container_a = get_container(a["id"])
        assert container_a["deadline_days"] == 180, "SQG at accumulation start"
        assert_instant_equals(container_a["accumulation_deadline_at"],
                              "2027-01-28T00:00:00Z", "accumulation_deadline_at")
        assert container_a["is_accumulation_overdue"] is False, (
            "the later flip to LQG must not shorten A's window")
        site = get_site(env["site"]["id"])
        assert site["generator_category"] == "LQG", "October total is 1000.0 kg"

    def test_creation_whose_own_mass_tips_category_gets_90_days(self, api):
        """PRD §3.3: "For container creation specifically, evaluation order is
        pinned: the creation's own month-total increment and category
        re-evaluation are applied first, and only then is the new container's
        `deadline_days` snapshotted — so a container whose own mass tips the site
        into `LQG` receives the 90-day allowance, not 180."

        Design: Difficulty/dual_variant_calc/accumulation_deadline_category_at_start_vs_current
        """
        _, _, b, c = self._setup_three_containers()
        # B's own arrival tipped August to exactly 1000.0 kg (LQG) first.
        assert get_container(b["id"])["deadline_days"] == 90
        # C entered central accumulation during an LQG month.
        assert get_container(c["id"])["deadline_days"] == 90


class TestStagingGates:
    def test_accumulation_overdue_blocks_stage(self, api):
        """PRD §3.4: "the accumulation deadline must not have passed (otherwise
        `ERR_ACCUMULATION_LIMIT_EXCEEDED`)". PRD §3.3: "at the deadline instant
        itself the container is not overdue".

        Design: Corner/calculations/accumulation_overdue_blocks_stage
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 50.0, "wc-1")
        label_container(container, labeler="wc-1")
        inspect_container(container["id"], "PASS", inspector="wc-2")
        # At the deadline instant itself the container is not overdue.
        set_clock("2027-01-28T00:00:00Z")
        assert get_container(container["id"])["is_accumulation_overdue"] is False
        # Past the 180-day deadline: overdue. Re-inspect so only the
        # accumulation gate can fail at stage time.
        set_clock("2027-01-29T00:00:00Z")
        assert get_container(container["id"])["is_accumulation_overdue"] is True
        inspect_container(container["id"], "PASS", inspector="wc-2")
        res = api.stage_container(container["id"], wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_ACCUMULATION_LIMIT_EXCEEDED)

    def test_inspection_overdue_exactly_7_days(self, api):
        """PRD §3.4: "A container's `is_inspection_overdue` flag is true when it
        sits in `IN_CENTRAL_ACCUMULATION` or `STAGED_FOR_SHIPMENT` and the logical
        clock is strictly more than seven days past the most recent inspection —
        or past `accumulation_start_date` if the container has never been
        inspected. At exactly seven days the container is not overdue." and "the
        inspection clock must be current (otherwise `ERR_INSPECTION_OVERDUE`)".

        Design: Corner/calculations/inspection_overdue_exactly_7_days
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 50.0, "wc-1")
        label_container(container, labeler="wc-1")
        inspect_container(container["id"], "PASS", inspector="wc-2")
        # Exactly 7 days after the 2026-08-01T00:00:00Z inspection: not overdue.
        set_clock("2026-08-08T00:00:00Z")
        assert get_container(container["id"])["is_inspection_overdue"] is False
        # One second later the stage gate fires.
        set_clock("2026-08-08T00:00:01Z")
        res = api.stage_container(container["id"], wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_INSPECTION_OVERDUE)

    def test_stage_unlabeled_container_rejected(self, api):
        """PRD §3.4: "the container must be labeled (otherwise
        `ERR_CONTAINER_NOT_LABELED`)".

        Design: Corner/validations/stage_unlabeled_container_rejected
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 50.0, "wc-1")
        inspect_container(container["id"], "PASS", inspector="wc-2")
        res = api.stage_container(container["id"], wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_CONTAINER_NOT_LABELED)
        assert get_container(container["id"])["status"] == "IN_CENTRAL_ACCUMULATION"


class TestLabelAndInspectionRecords:
    def test_label_content_validation_pair(self, api):
        """PRD §3.4: "The label text must contain the exact substring "Hazardous
        Waste" — a label lacking it is rejected with
        `ERR_LABEL_MISSING_HAZARD_TEXT` — and the marked start date must equal the
        container's `accumulation_start_date` exactly, to the millisecond, or the
        call is rejected with `ERR_LABEL_START_DATE_MISMATCH`. A successful label
        sets `is_labeled` to true".

        Design: Corner/validations/label_content_validation_pair
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 50.0, "wc-1")
        start = container["accumulation_start_date"]
        res = api.label_container(
            container["id"],
            label_container_payload("Waste only", start), wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_LABEL_MISSING_HAZARD_TEXT)
        res = api.label_container(
            container["id"],
            label_container_payload("Hazardous Waste — D001",
                                    "2026-08-02T00:00:00Z"),
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_LABEL_START_DATE_MISMATCH)
        labeled = label_container(container, labeler="wc-1")
        assert labeled["is_labeled"] is True

    def test_fail_inspection_without_note_returns_error(self, api):
        """PRD §3.4: "a `FAIL` result must carry a `deficiency_note` (otherwise
        `ERR_INSPECTION_NOTE_REQUIRED`), while the note is ignored on a `PASS`"
        and "Each inspection stamps `inspected_at` with the logical instant and
        refreshes the container's `last_inspected_at`."

        Design: Corner/validations/fail_inspection_without_note_returns_error
        """
        env = setup_site_stream_areas()
        container = create_container(
            env["stream"]["id"], env["central"]["id"], 10, 50.0, "wc-1")
        res = api.create_inspection(
            container["id"], create_inspection_payload("FAIL"), wc_headers("wc-2"))
        validate_error(res, ApiErrorId.ERR_INSPECTION_NOTE_REQUIRED)
        inspection = inspect_container(
            container["id"], "FAIL", deficiency_note="drum rusted at seam",
            inspector="wc-2")
        assert inspection["inspector_user_id"] == "wc-2"
        assert_instant_equals(inspection["inspected_at"],
                              "2026-08-01T00:00:00Z", "inspected_at")
        assert_instant_equals(get_container(container["id"])["last_inspected_at"],
                              "2026-08-01T00:00:00Z", "last_inspected_at")
