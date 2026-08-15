"""Excavation permit track and its interaction with dispatch (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_crew,
    set_clock,
    setup_granted_permit,
    setup_repair_order,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_apply_permit_payload


class TestPermitGrantDeny:
    def test_excavation_permit_grant_twice_rejected(self, api):
        """PRD §3.6: "granting requires the permit to be `APPLIED`
        (`ERR_PERMIT_NOT_APPLIED`), stamps `granted_at`."

        Design: Corner/state_machines/excavation_permit_grant_twice_rejected
        """
        ctx = setup_granted_permit(route_code="R-PG")
        permit = ctx["permit"]
        assert permit["status"] == "GRANTED"
        granted_at_first = permit["granted_at"]

        resp = api.grant_permit(permit["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPLIED)
        after = get_success_data(api.get_excavation_permit(permit["id"], ctx["co_h"]))
        assert after["granted_at"] == granted_at_first

    def test_excavation_permit_deny_updates_order_status(self, api):
        """PRD §3.6: "denying likewise requires `APPLIED` and flips the order to
        `PERMIT_DENIED`" while "The repair order carries two independent state
        dimensions" — the dispatch dimension is untouched.

        Design: Corner/state_machines/excavation_permit_deny_updates_order_status
        """
        ctx = setup_repair_order(repair_method="CUT_AND_REPLACE", route_code="R-PD2")
        permit = get_success_data(api.apply_permit(
            ctx["order"]["id"],
            create_apply_permit_payload(permit_number="PERMIT-PD"),
            ctx["co_h"],
        ))
        denied = validate_success(api.deny_permit(permit["id"], ctx["co_h"]))
        assert denied["status"] == "DENIED"
        order = get_success_data(api.get_repair_order(ctx["order"]["id"], ctx["dc_h"]))
        assert order["excavation_permit_status"] == "PERMIT_DENIED"
        assert order["dispatch_status"] == "PENDING_DISPATCH"


class TestParallelDimensions:
    def test_permit_grant_leaves_dispatch_dimension_untouched(self, api):
        """PRD §3.6: "The repair order carries two independent state dimensions."
        and "`excavation_permit_status` runs `NOT_REQUIRED | PERMIT_REQUIRED |
        PERMIT_APPLIED | PERMIT_GRANTED | PERMIT_DENIED | PERMIT_EXPIRED` and
        evolves independently of dispatch progress" — granting the permit advances
        only the permit dimension.

        Design: Difficulty/non_linear_state_machine/repair_order_parallel_dimensions
        """
        ctx = setup_granted_permit(route_code="R-PD")
        order = ctx["order"]
        assert order["dispatch_status"] == "PENDING_DISPATCH"
        assert order["excavation_permit_status"] == "PERMIT_GRANTED"
        assert ctx["permit"]["status"] == "GRANTED"
        assert ctx["permit"]["granted_at"] is not None

    def test_apply_permit_flips_only_permit_dimension(self, api):
        """PRD §3.6: "Success creates an `ExcavationPermit` in `APPLIED` status
        with `applied_at` stamped from the logical clock, and flips the order's
        `excavation_permit_status` to `PERMIT_APPLIED`" — again without disturbing
        `dispatch_status`.

        Design: Difficulty/non_linear_state_machine/repair_order_parallel_dimensions
        """
        ctx = setup_repair_order(repair_method="CUT_AND_REPLACE", route_code="R-PD3")
        permit = validate_success(api.apply_permit(
            ctx["order"]["id"],
            create_apply_permit_payload(permit_number="PERMIT-PD3"),
            ctx["co_h"],
        ), expected_status=201)
        assert permit["status"] == "APPLIED"
        assert permit["applied_at"] is not None
        order = get_success_data(api.get_repair_order(ctx["order"]["id"], ctx["dc_h"]))
        assert order["excavation_permit_status"] == "PERMIT_APPLIED"
        assert order["dispatch_status"] == "PENDING_DISPATCH"


class TestPermitExpiry:
    def test_permit_expiry_unwinds_repair_and_leak(self, api):
        """PRD §3.6: "If the logical clock passes a granted permit's `expires_at`
        while the parent order is not yet `WORK_COMPLETE`, the permit
        automatically becomes `EXPIRED`, the order's `excavation_permit_status`
        flips to `PERMIT_EXPIRED`, and — if the order was `DISPATCHED` or
        `ON_SITE` at the time — the system performs a compensating unwind: the
        order returns to `PENDING_DISPATCH`, the crew's `open_order_count`
        decrements (recomputing crew `status`), and the leak reverts to
        `REPAIR_SCHEDULED`."

        Design: Difficulty/transitive_cascade/permit_expiry_unwinds_repair_and_leak
        """
        ctx = setup_granted_permit(expires_at="2026-08-05T00:00:00Z", route_code="R-EXP")
        crew = make_crew(ctx, crew_code="CR-EXP", is_qualified_excavation=True)
        get_success_data(api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        get_success_data(api.arrive_on_site(ctx["order"]["id"], ctx["dc_h"]))
        leak_mid = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["ia_h"]))
        assert leak_mid["status"] == "UNDER_REPAIR"

        set_clock(ctx, "2026-08-06T00:00:00Z")
        permit = get_success_data(api.get_excavation_permit(ctx["permit"]["id"], ctx["co_h"]))
        assert permit["status"] == "EXPIRED"
        order = get_success_data(api.get_repair_order(ctx["order"]["id"], ctx["dc_h"]))
        assert order["dispatch_status"] == "PENDING_DISPATCH"
        assert order["excavation_permit_status"] == "PERMIT_EXPIRED"
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["ia_h"]))
        assert leak["status"] == "REPAIR_SCHEDULED"
        crew_after = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert crew_after["open_order_count"] == 0

    def test_permit_expiry_without_dispatch_has_nothing_to_unwind(self, api):
        """PRD §3.6: the compensating unwind applies "if the order was
        `DISPATCHED` or `ON_SITE` at the time" — for an order still
        `PENDING_DISPATCH` the permit expires and the order's permit status flips,
        but dispatch status and leak status are untouched.

        Design: Difficulty/transitive_cascade/permit_expiry_unwinds_repair_and_leak
        """
        ctx = setup_granted_permit(expires_at="2026-08-05T00:00:00Z", route_code="R-EXP2")
        set_clock(ctx, "2026-08-06T00:00:00Z")
        permit = get_success_data(api.get_excavation_permit(ctx["permit"]["id"], ctx["co_h"]))
        assert permit["status"] == "EXPIRED"
        order = get_success_data(api.get_repair_order(ctx["order"]["id"], ctx["dc_h"]))
        assert order["dispatch_status"] == "PENDING_DISPATCH"
        assert order["excavation_permit_status"] == "PERMIT_EXPIRED"
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["ia_h"]))
        assert leak["status"] == "REPAIR_SCHEDULED"

    def test_dispatch_succeeds_before_permit_expiry(self, api):
        """PRD §3.6: "a permit must exist in `GRANTED` status with `expires_at`
        later than the current logical clock (`ERR_NO_VALID_EXCAVATION_PERMIT`)" —
        one second before expiry the permit still qualifies.

        Design: Difficulty/resource_temporal_overlap/excavation_permit_expiry_exclusive_bound
        """
        ctx = setup_granted_permit(expires_at="2026-08-10T00:00:00Z", route_code="R-EXB")
        crew = make_crew(ctx, crew_code="CR-EXB", is_qualified_excavation=True)
        set_clock(ctx, "2026-08-09T23:59:59Z")
        data = validate_success(api.dispatch_repair_order(
            ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"],
        ))
        assert data["dispatch_status"] == "DISPATCHED"

    def test_dispatch_rejected_at_and_after_permit_expiry(self, api):
        """PRD §3.6: "a permit must exist in `GRANTED` status with `expires_at`
        later than the current logical clock (`ERR_NO_VALID_EXCAVATION_PERMIT`)" —
        `expires_at` equal to the clock is not "later than" it, and one second
        past is likewise rejected.

        Design: Difficulty/resource_temporal_overlap/excavation_permit_expiry_exclusive_bound
        """
        ctx = setup_granted_permit(expires_at="2026-08-10T00:00:00Z", route_code="R-EXB2")
        crew = make_crew(ctx, crew_code="CR-EXB2", is_qualified_excavation=True)

        set_clock(ctx, "2026-08-10T00:00:00Z")  # exactly expires_at
        resp = api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_NO_VALID_EXCAVATION_PERMIT)

        set_clock(ctx, "2026-08-10T00:00:01Z")  # one second past
        resp = api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_NO_VALID_EXCAVATION_PERMIT)
