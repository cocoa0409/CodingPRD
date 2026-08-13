"""Visit scheduling geometry: half-open unit-entry overlap and half-open
batch-window containment."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    api_client,
    create_property, create_building, create_unit, create_asset,
    create_template, create_plan, create_batch, add_visit,
    setup_property_scaffold,
    create_visit_payload,
)

TEST_PM = TEST_USERS["property_manager_headers"]

WINDOW_START = "2026-08-10T08:00:00Z"
WINDOW_END = "2026-08-10T18:00:00Z"


class TestUnitEntryHalfOpenIntervalOverlap:
    """One unit, two component templates of 60 minutes each, first visit
    occupying [09:00, 10:00)."""

    def _setup(self):
        prop = create_property()
        building = create_building(prop["id"])
        unit = create_unit(building["id"], occupancy_status="VACANT")
        asset1 = create_asset(unit["id"], component_type="HVAC")
        asset2 = create_asset(unit["id"], component_type="WATER_HEATER")
        t1 = create_template(prop["id"], component_type="HVAC", estimated_labor_minutes=60)
        t2 = create_template(prop["id"], component_type="WATER_HEATER",
                             task_name="WH svc", estimated_labor_minutes=60)
        plan = create_plan(prop["id"], adopt=True)
        batch = create_batch(prop["id"], window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-10T20:00:00Z")
        add_visit(batch["id"], unit["id"], t1["id"], asset1["id"], plan["id"],
                  scheduled_start="2026-08-10T09:00:00Z")
        return prop, unit, asset2, t2, plan, batch

    def test_overlapping_second_visit_rejected(self, api):
        """PRD §3.3: "A unit may never hold two non-`CANCELLED` visits whose
        occupied intervals intersect — each visit occupies the span from its
        `scheduled_start` through its `scheduled_start` plus its template's
        `estimated_labor_minutes`, with the end instant itself excluded, so
        visits that merely touch at an endpoint are allowed; any intersection,
        regardless of which batches the visits belong to, is rejected with
        `ERR_UNIT_ENTRY_OVERLAP`." A 09:59 start intersects [09:00, 10:00).

        Design: Difficulty/resource_temporal_overlap/unit_entry_half_open_interval_overlap
        """
        _prop, unit, asset2, t2, plan, batch = self._setup()
        resp = api.create_visit(
            create_visit_payload(batch["id"], unit["id"], t2["id"], asset2["id"], plan["id"],
                                 scheduled_start="2026-08-10T09:59:00Z"),
            TEST_PM,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_ENTRY_OVERLAP)

    def test_touching_endpoint_second_visit_allowed(self, api):
        """PRD §3.3: "with the end instant itself excluded, so visits that merely
        touch at an endpoint are allowed". A 10:00 start touches the end of
        [09:00, 10:00) without intersecting it.

        Design: Difficulty/resource_temporal_overlap/unit_entry_half_open_interval_overlap
        """
        _prop, unit, asset2, t2, plan, batch = self._setup()
        resp = api.create_visit(
            create_visit_payload(batch["id"], unit["id"], t2["id"], asset2["id"], plan["id"],
                                 scheduled_start="2026-08-10T10:00:00Z"),
            TEST_PM,
        )
        visit = validate_success(resp, expected_status=201)
        assert visit["visit_status"] == "SCHEDULED"


class TestVisitWindowContainmentHalfOpen:
    """Batch window [2026-08-10T08:00Z, 2026-08-10T18:00Z)."""

    def _setup(self):
        prop = create_property()
        building = create_building(prop["id"])
        unit1 = create_unit(building["id"], unit_number="101", occupancy_status="VACANT")
        unit2 = create_unit(building["id"], unit_number="102", occupancy_status="VACANT")
        asset1 = create_asset(unit1["id"])
        asset2 = create_asset(unit2["id"])
        template = create_template(prop["id"], estimated_labor_minutes=60)
        plan = create_plan(prop["id"], adopt=True)
        batch = create_batch(prop["id"], window_start=WINDOW_START, window_end=WINDOW_END)
        return prop, unit1, unit2, asset1, asset2, template, plan, batch

    def test_visit_at_exactly_window_start_accepted(self, api):
        """PRD §3.3: "the `scheduled_start` must lie within the batch window — on
        or after `window_start` and strictly before `window_end` — or the request
        fails with `ERR_VISIT_OUTSIDE_WINDOW`". The lower bound is inclusive.

        Design: Difficulty/resource_temporal_overlap/visit_window_containment_half_open
        """
        _prop, unit1, _u2, asset1, _a2, template, plan, batch = self._setup()
        resp = api.create_visit(
            create_visit_payload(batch["id"], unit1["id"], template["id"], asset1["id"],
                                 plan["id"], scheduled_start=WINDOW_START),
            TEST_PM,
        )
        visit = validate_success(resp, expected_status=201)
        assert visit["scheduled_start"].startswith("2026-08-10T08:00")

    def test_visit_at_exactly_window_end_rejected(self, api):
        """PRD §3.3: "the `scheduled_start` must lie within the batch window — on
        or after `window_start` and strictly before `window_end` — or the request
        fails with `ERR_VISIT_OUTSIDE_WINDOW`". The upper bound is exclusive, so a
        start at exactly `window_end` is outside the window.

        Design: Difficulty/resource_temporal_overlap/visit_window_containment_half_open
        """
        _prop, _u1, unit2, _a1, asset2, template, plan, batch = self._setup()
        resp = api.create_visit(
            create_visit_payload(batch["id"], unit2["id"], template["id"], asset2["id"],
                                 plan["id"], scheduled_start=WINDOW_END),
            TEST_PM,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_OUTSIDE_WINDOW)
