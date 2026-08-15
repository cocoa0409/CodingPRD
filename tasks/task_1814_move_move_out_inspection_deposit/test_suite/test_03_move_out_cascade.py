"""Move-out completion: the depth-3 deduction cascade, the NOTICE_GIVEN gate,
unit occupancy derivation, and the logical-clock default."""
import test_helpers as th
from test_helpers import (
    add_item,
    api_client,
    complete_inspection,
    create_jurisdiction,
    create_property,
    create_statement_for,
    create_tenancy,
    create_unit,
    get_success_data,
    get_statement,
    get_tenancy,
    get_unit,
    make_manager_admin_headers,
    make_property_manager_headers,
    schedule_inspection,
    setup_notice_given,
    setup_occupied_tenancy,
    setup_vacated_tenancy,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


class TestMoveOutCompletionCascadeDepth3:
    def _setup_draft_statement_then_damage(self):
        """Tenancy in NOTICE_GIVEN with keys fully returned and a pre-existing
        DRAFT statement (projections 0); MOVE_OUT carries one PAINT
        TENANT_DAMAGE item (replacement 90,000c)."""
        ctx = setup_notice_given(
            keys_returned=2, fobs_returned=1,
            move_in_item_overrides={},
        )
        ten = ctx["tenancy"]
        stmt = create_statement_for(ten["id"])
        mo = schedule_inspection(ten["id"], "MOVE_OUT")
        add_item(mo["id"], area_name="bedroom_paint", category="PAINT",
                 condition="DAMAGED", photo_count=4, determination="TENANT_DAMAGE",
                 linked_move_in_item_id=ctx["move_in_item"]["id"],
                 replacement_cost_cents=90_000)
        ctx["statement"] = stmt
        ctx["move_out"] = mo
        return ctx

    def test_cascade_creates_deduction_and_updates_pending(self):
        """PRD §3.4: "Completion sets `completed_at`, sets the tenancy's
        `move_out_on` to the logical clock's date — the anchor for both the
        statutory deadline and the interest cutoff — moves the tenancy from
        `NOTICE_GIVEN` to `VACATED`, recomputes the unit back to `AVAILABLE`,
        and then fires a three-link deduction cascade. First, the system
        creates deduction lines: one per item whose determination is
        `TENANT_DAMAGE` and whose computed charge is greater than zero, plus
        the key, fob, and lock lines derived from the unreturned counts.
        Second, each created line recomputes the tenancy's
        `pending_deductions_cents`, the running sum of `DRAFT` deduction
        amounts."

        Paint age 365d of 1,095d => residual 730/1095 => charge 60,000c in
        DRAFT; pending_deductions_cents becomes 60,000.

        Design: Difficulty/transitive_cascade/moveout_completion_cascade_depth3
        """
        ctx = self._setup_draft_statement_then_damage()
        complete_inspection(ctx["move_out"]["id"])
        ten = get_tenancy(ctx["tenancy"]["id"])
        assert ten["status"] == "VACATED"
        assert ten["move_out_on"] == "2026-08-01"
        deductions = th.list_tenancy_deductions(ten["id"])
        damage = [d for d in deductions if d["source"] == "MOVE_OUT_DAMAGE"]
        assert len(damage) == 1, f"expected one damage line, got {deductions}"
        assert damage[0]["amount_cents"] == 60_000
        assert damage[0]["status"] == "DRAFT"
        assert ten["pending_deductions_cents"] == 60_000

    def test_cascade_reaches_draft_statement_projections_and_interest(self):
        """PRD §3.4: "Third, that change cascades into the tenancy's `DRAFT`
        statement when one exists, refreshing its `projected_deductions_cents`
        (which mirrors the tenancy's pending total while the statement is in
        draft) and its `projected_refund_cents` (the deposit plus accrued
        interest minus the projected deductions)." And: "The same completion
        also runs deposit interest accrual."

        After completion: interest 9,337c accrued (ACTUAL_DAYS, 568 days);
        DRAFT statement projections read 60,000c and 149,337c.

        Design: Difficulty/transitive_cascade/moveout_completion_cascade_depth3
        """
        ctx = self._setup_draft_statement_then_damage()
        complete_inspection(ctx["move_out"]["id"])
        ten = get_tenancy(ctx["tenancy"]["id"])
        assert ten["interest_accrued_cents"] == 9_337
        stmt = get_statement(ctx["statement"]["id"])
        assert stmt["status"] == "DRAFT"
        assert stmt["projected_deductions_cents"] == 60_000, (
            f"draft projection must mirror pending deductions, "
            f"got {stmt['projected_deductions_cents']}"
        )
        assert stmt["projected_refund_cents"] == 149_337, (
            f"projected refund = 200000 + 9337 - 60000 = 149337, "
            f"got {stmt['projected_refund_cents']}"
        )


class TestMoveOutRequiresNoticeGiven:
    def _setup_occupied_only(self):
        """Tenancy OCCUPIED (move-in completed), notice NOT yet given."""
        return setup_occupied_tenancy()

    def test_move_out_rejected_while_occupied(self):
        """PRD §3.4: "An `Inspector` completes a `DRAFT` inspection of kind
        `MOVE_OUT` only while its tenancy is `NOTICE_GIVEN`; completion against
        any other tenancy state is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Creating/completing the MOVE_OUT inspection is gated on the tenancy's
        state; while OCCUPIED the request fails, and after give_notice the
        identical request succeeds.

        Design: Difficulty/cross_entity_state_dependency/moveout_completion_requires_notice_given
        """
        ctx = self._setup_occupied_only()
        ten = ctx["tenancy"]
        resp = api_client.create_inspection(
            {"tenancy_id": ten["id"], "kind": "MOVE_OUT",
             "inspector_user_id": "insp-1",
             "scheduled_start_at": "2025-01-11T10:00:00Z",
             "scheduled_end_at": "2025-01-11T11:00:00Z"},
            PM,
        )
        if resp.status_code == 201:
            # Inspection creation is not state-gated; completing it while the
            # tenancy is OCCUPIED must be rejected instead.
            mo = get_success_data(resp)
            err_resp = api_client.complete_inspection(mo["id"], th.make_inspector_headers())
            validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        else:
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_move_out_succeeds_after_notice(self):
        """PRD §3.3: "When the tenant gives notice, a `PropertyManager` records
        it against an `OCCUPIED` tenancy: the tenancy moves from `OCCUPIED` to
        `NOTICE_GIVEN`". PRD §3.4: "An `Inspector` completes a `DRAFT`
        inspection of kind `MOVE_OUT` only while its tenancy is
        `NOTICE_GIVEN`".

        After give_notice the tenancy is NOTICE_GIVEN and a MOVE_OUT
        inspection can be scheduled (201, born DRAFT).

        Design: Difficulty/cross_entity_state_dependency/moveout_completion_requires_notice_given
        """
        ctx = self._setup_occupied_only()
        ten = ctx["tenancy"]
        get_success_data(api_client.give_notice(ten["id"], PM))
        resp = api_client.create_inspection(
            {"tenancy_id": ten["id"], "kind": "MOVE_OUT",
             "inspector_user_id": "insp-1",
             "scheduled_start_at": "2025-01-11T10:00:00Z",
             "scheduled_end_at": "2025-01-11T11:00:00Z"},
            PM,
        )
        mo = validate_success(resp, expected_status=201)
        assert mo["status"] == "DRAFT"


class TestUnitOccupancyDerivation:
    def test_occupancy_status_tracks_lifecycle(self):
        """PRD §3.1: "A unit also exposes a derived `occupancy_status`,
        recomputed on tenancy creation and on every tenancy status change,
        considering only that unit's tenancies that have not reached `SETTLED`
        or `ESCHEATED`: if any such tenancy is `OCCUPIED` the unit is
        `OCCUPIED`; otherwise, if any such tenancy is `NOTICE_GIVEN` or
        `PENDING_MOVE_IN` the unit is `RESERVED`; otherwise the unit is
        `AVAILABLE`. A freshly created unit therefore reads `AVAILABLE`."

        AVAILABLE before any tenancy; RESERVED after tenancy creation;
        OCCUPIED after move-in completion; AVAILABLE again after move-out
        completion.

        Design: Corner/entities/unit_occupancy_status_derived_through_lifecycle
        """
        api_client.set_clock({"to_iso8601": "2025-01-10T00:00:00Z"}, ADMIN)
        jur = create_jurisdiction()
        prop = create_property(jur["id"])
        unit = create_unit(prop["id"])
        assert get_unit(unit["id"])["occupancy_status"] == "AVAILABLE"

        ten = create_tenancy(unit["id"])
        assert get_unit(unit["id"])["occupancy_status"] == "RESERVED", (
            "a PENDING_MOVE_IN tenancy already counts as RESERVED"
        )

        mi = schedule_inspection(ten["id"], "MOVE_IN")
        complete_inspection(mi["id"])
        assert get_unit(unit["id"])["occupancy_status"] == "OCCUPIED"

        api_client.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN)
        get_success_data(api_client.give_notice(ten["id"], PM))
        get_success_data(api_client.record_key_return(
            ten["id"], {"keys_returned": 2, "fobs_returned": 1}, PM))
        mo = schedule_inspection(ten["id"], "MOVE_OUT")
        complete_inspection(mo["id"])
        assert get_unit(unit["id"])["occupancy_status"] == "AVAILABLE"


class TestDefaultLogicalClock:
    def test_move_in_completion_uses_default_clock(self):
        """PRD §2.5: "At startup the clock reads exactly
        `2026-08-01T00:00:00Z`; before any clock-setting call the clock returns
        this default and never falls back to the host's wall-clock time."
        PRD §3.2: "Completion moves the inspection itself from `DRAFT` to
        `COMPLETED`, stamps `completed_at` from the logical clock, sets the
        tenancy's `move_in_on` to the clock's date".

        With no set_current_utc call at all, the completed move-in stamps
        move_in_on == 2026-08-01 and completed_at == 2026-08-01T00:00:00Z.

        Design: Corner/endpoints/move_in_completion_uses_default_clock
        """
        jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
        prop = create_property(jur["id"])
        unit = create_unit(prop["id"])
        ten = create_tenancy(unit["id"], lease_start_on="2026-08-01",
                             lease_end_on="2027-08-01")
        mi = schedule_inspection(ten["id"], "MOVE_IN",
                                 scheduled_start_at="2026-08-01T09:00:00Z",
                                 scheduled_end_at="2026-08-01T10:00:00Z")
        completed = validate_success(api_client.complete_inspection(
            mi["id"], th.make_inspector_headers()))
        assert completed["completed_at"] == "2026-08-01T00:00:00Z", (
            f"completed_at must come from the logical clock default, "
            f"got {completed['completed_at']}"
        )
        ten_seen = get_tenancy(ten["id"])
        assert ten_seen["move_in_on"] == "2026-08-01"
        assert ten_seen["status"] == "OCCUPIED"
