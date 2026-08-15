"""Pest treatment exclusion windows: closed-interval move-in conflicts,
premature clears, and merged exclusion ends."""
import pytest

from test_helpers import (
    ApiErrorId,
    apply_pest_treatment,
    create_pest_treatment,
    create_tenancy,
    get_unit,
    set_clock,
    setup_certified_site,
    setup_eligible_household,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
MANAGER = TEST_USERS["site_manager_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestPestExclusionClosedBuffer:
    """Difficulty instance: treatment applied 2026-08-10 with a 3-day buffer
    excludes move-ins through 2026-08-13 (closed interval); 2026-08-14 is the
    first legal day; clearing before the buffer elapses is rejected."""

    def _setup(self, api):
        ctx = setup_certified_site(site_name="Site PX")
        unit_id = ctx["unit"]["id"]
        h1 = setup_eligible_household(name="Fam P1")["household"]
        h2 = setup_eligible_household(name="Fam P2",
                                      members=(("P2", "1991-01-01", "HEAD"),),
                                      )["household"]
        treatment = apply_pest_treatment(
            unit_id, "FUMIGATION", "2026-08-10", 3,
            apply_clock="2026-08-10T08:00:00Z")
        assert treatment["status"] == "APPLIED", "Setup failed"
        t1 = create_tenancy(h1["id"], unit_id, move_in_date="2026-08-13")
        t2 = create_tenancy(h2["id"], unit_id, move_in_date="2026-08-14")
        return ctx, treatment, t1, t2

    def test_movein_on_exclusion_end_rejected_next_day_allowed(
            self, api, intake_coordinator_headers):
        """PRD §3.6: "The exclusion is a closed interval: both the applied
        date and the end date are unoccupiable, so the unit's
        `under_pest_exclusion` holds while the clock date is on or before the
        `exclusion_end_date`, and a move-in whose `move_in_date` falls on or
        before any applied treatment's end date is refused per §3.4."
        PRD §3.4: "if any `APPLIED` treatment on the unit has an
        `exclusion_end_date` on or after the `move_in_date`, activation is
        rejected with `ERR_UNIT_UNDER_PEST_EXCLUSION`, while a move-in date
        later than every such end date is allowed."

        Design: Difficulty/resource_temporal_overlap/pest_exclusion_closed_buffer_vs_movein
        """
        ctx, treatment, t1, t2 = self._setup(api)
        assert treatment["exclusion_end_date"] == "2026-08-13", (
            "applied 2026-08-10 + 3 buffer days, closed interval")

        blocked = api.update_tenancy(t1["id"], {"status": "ACTIVE"}, INTAKE)
        validate_error(blocked, ApiErrorId.ERR_UNIT_UNDER_PEST_EXCLUSION)

        allowed = validate_success(api.update_tenancy(
            t2["id"], {"status": "ACTIVE"}, INTAKE))
        assert allowed["status"] == "ACTIVE", (
            "move_in 2026-08-14 > exclusion end is the first legal day")

    def test_clear_before_buffer_elapsed_rejected(
            self, api, site_manager_headers):
        """PRD §3.6: "Clearing — `APPLIED → CLEARED` — requires the clock date
        to be strictly past the `exclusion_end_date`; the buffer's final day
        is still excluded, and an early clear is rejected with
        `ERR_REENTRY_BUFFER_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/pest_exclusion_closed_buffer_vs_movein
        """
        _, treatment, _, _ = self._setup(api)
        # The clock still reads 2026-08-10, which is not > 2026-08-13.
        resp = api.update_pest_treatment(treatment["id"],
                                         {"status": "CLEARED"},
                                         site_manager_headers)
        validate_error(resp, ApiErrorId.ERR_REENTRY_BUFFER_ACTIVE)


class TestPestExclusionMerge:
    def test_pest_exclusion_merges_max_end(self, api, operator_admin_headers):
        """PRD §3.6: "With several applied treatments, the unit's
        `pest_exclusion_end_date` is the latest of their end dates — and null
        when no treatment is applied."

        Design: Corner/calculations/pest_exclusion_merges_max_end
        """
        ctx = setup_certified_site(site_name="S")
        unit_id = ctx["unit"]["id"]
        first = create_pest_treatment(unit_id, "ROUTINE", "2026-08-10", 3)
        second = create_pest_treatment(unit_id, "TARGETED", "2026-08-11", 5)

        set_clock("2026-08-10T08:00:00Z")
        applied1 = validate_success(api.update_pest_treatment(
            first["id"], {"status": "APPLIED"}, MANAGER))
        assert applied1["exclusion_end_date"] == "2026-08-13"

        set_clock("2026-08-11T08:00:00Z")
        applied2 = validate_success(api.update_pest_treatment(
            second["id"], {"status": "APPLIED"}, MANAGER))
        assert applied2["exclusion_end_date"] == "2026-08-16"

        unit = get_unit(unit_id)
        assert unit["under_pest_exclusion"] is True
        assert unit["pest_exclusion_end_date"] == "2026-08-16", (
            "Merged exclusion takes the max end across APPLIED treatments")
