"""Casting call design, publish/lock gates, ratio waivers, compliance index."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_casting_call,
    assert_look_requirement,
    assert_ratio_waiver,
    confirm_booking,
    create_actor,
    create_booking,
    create_casting_call,
    create_look_requirement_payload,
    create_production,
    create_ratio_waiver,
    create_standby_entry,
    decline_booking,
    get_case_for_call,
    lock_call,
    make_director_headers,
    make_union_rep_headers,
    publish_call,
    set_clock,
    setup_no_show_case,
    setup_published_call,
    validate_error,
    validate_success,
)


class TestCastingCallCreation:
    def test_casting_call_computed_fields_init(self, api, director_headers):
        """PRD §3.2: "The call is born in `DRAFT`, its computed slot and ratio
        fields initialize with `slots_available` equal to the two headcounts
        combined, `approved_waiver_reduction` at zero, and `actual_compliant` null
        until the day the call wraps."
        PRD §2.6: "`required_union_slots` is the call's `union_slots` minus its
        `approved_waiver_reduction`."

        Design: Corner/entities/casting_call_computed_fields_init
        """
        prod = create_production(active=True)
        res = api.create_casting_call(
            {
                "production_id": prod["id"],
                "shoot_date": "2026-08-10",
                "general_call_time": "2026-08-10T07:00:00Z",
                "scheduled_duration_minutes": 600,
                "location": "Lot 30",
                "union_slots": 2,
                "nonunion_slots": 1,
                "union_rate_cents": 10000,
                "nonunion_rate_cents": 9000,
            },
            director_headers,
        )
        call = validate_success(res, 201)
        assert_casting_call(call)
        assert call["status"] == "DRAFT"
        assert call["slots_available"] == 3
        assert call["required_union_slots"] == 2
        assert call["approved_waiver_reduction"] == 0
        assert call["actual_compliant"] is None

    def test_look_requirement_immutable_no_version(self, api, director_headers):
        """PRD §2.4: "A LookRequirement is immutable once created, and a TimeEvent
        is an append-only ledger record; both carry only `id` and `created_at` —
        `updated_at` and `version` are absent from these two resources."

        Design: Corner/entities/look_requirement_immutable_no_version
        """
        prod = create_production(active=True)
        call = create_casting_call(
            prod["id"], union_slots=1, nonunion_slots=1, nonunion_rate_cents=9000
        )
        res = api.create_look_requirement(
            create_look_requirement_payload(
                call["id"],
                category="PERIOD_COSTUME",
                description="1920s tuxedo",
                bump_amount_cents=2500,
                mandatory=True,
            ),
            director_headers,
        )
        look = validate_success(res, 201)
        assert_look_requirement(look)
        assert "version" not in look and "updated_at" not in look

        fetched = validate_success(
            api.get_look_requirement(look["id"], director_headers), 200
        )
        assert_look_requirement(fetched)
        assert fetched["id"] == look["id"]
        assert fetched["description"] == "1920s tuxedo"
        assert "version" not in fetched and "updated_at" not in fetched


class TestProductionPhaseGates:
    def test_production_not_active_gate(self, api, director_headers):
        """PRD §2.10: "The production-phase gate: planning-phase mutations
        (creating a casting call, publishing, adding look requirements, creating
        holding areas, registering standby entries, creating bookings) require the
        production `ACTIVE`, failing with `ERR_PRODUCTION_NOT_ACTIVE`"

        Design: Corner/validations/production_not_active_gate
        """
        prod = create_production(active=False)
        assert prod["status"] == "SETUP"
        res = api.create_casting_call(
            {
                "production_id": prod["id"],
                "shoot_date": "2026-08-10",
                "general_call_time": "2026-08-10T07:00:00Z",
                "scheduled_duration_minutes": 600,
                "location": "Lot 90",
                "union_slots": 1,
                "nonunion_slots": 0,
                "union_rate_cents": 10000,
                "nonunion_rate_cents": 10000,
            },
            director_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRODUCTION_NOT_ACTIVE)

    def test_publish_twice_returns_call_invalid_state(self, api, director_headers):
        """PRD §3.3: "the call itself must still be `DRAFT`, failing with
        `ERR_CALL_INVALID_STATE`"

        Design: Corner/errors/publish_twice_returns_call_invalid_state
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        assert call["status"] == "PUBLISHED"
        res = api.publish_casting_call(call["id"], director_headers)
        validate_error(res, ApiErrorId.ERR_CALL_INVALID_STATE)

    def test_shoot_date_mismatch_rejected(self, api, associate_headers):
        """PRD §3.4: "The call must be `LOCKED` (`ERR_CALL_INVALID_STATE`
        otherwise), and the logical clock's calendar date must equal the call's
        `shoot_date`, failing with `ERR_SHOOT_DATE_MISMATCH`"

        Design: Corner/validations/shoot_date_mismatch_rejected
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        lock_call(call["id"])
        set_clock("2026-08-09T23:00:00Z")
        res = api.start_shooting(call["id"], associate_headers)
        validate_error(res, ApiErrorId.ERR_SHOOT_DATE_MISMATCH)
        call_after = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_after["status"] == "LOCKED"


class TestRatioLock:
    def test_lock_with_shortfall_returns_422(self, api, director_headers):
        """PRD §3.3: "Locking requires the call to be `PUBLISHED` and the live
        `projected_union_count` to reach `required_union_slots` — exactly equal
        passes — and a shortfall is rejected with `ERR_UNION_RATIO_SHORTFALL`
        (HTTP 422)."

        Design: Corner/validations/lock_with_shortfall_returns_422
        """
        prod, call = setup_published_call(union_slots=2, nonunion_slots=0)
        actor = create_actor("SAG_AFTRA")
        create_booking(call["id"], actor["id"])
        res = api.lock_casting_call(call["id"], director_headers)
        validate_error(res, ApiErrorId.ERR_UNION_RATIO_SHORTFALL)
        call_after = validate_success(
            api.get_casting_call(call["id"], director_headers), 200
        )
        assert call_after["status"] == "PUBLISHED"

    def test_union_ratio_exactly_at_requirement_locks(self, api, director_headers):
        """PRD §2.6: "A count exactly equal to the requirement passes, in either
        tense."
        PRD §3.3: "Success moves the call `PUBLISHED` → `LOCKED` and stores
        `projected_compliant` as true; that stored verdict is a snapshot and does
        not move with later booking mutations, even if a subsequent no-show
        hollows out the union contingent it certified."

        Design: Difficulty/boundary_precision_check/union_ratio_exactly_at_requirement_locks
        """
        prod, call = setup_published_call(union_slots=2, nonunion_slots=1)
        u1 = create_actor("SAG_AFTRA")
        u2 = create_actor("SAG_AFTRA")
        create_booking(call["id"], u1["id"])
        create_booking(call["id"], u2["id"])

        res = api.lock_casting_call(call["id"], director_headers)
        locked = validate_success(res, 200)
        assert locked["status"] == "LOCKED"
        assert locked["projected_union_count"] == 2
        assert locked["required_union_slots"] == 2
        assert locked["projected_compliant"] is True

    def test_union_ratio_boundary_call_state_after_lock(self, api, director_headers):
        """PRD §3.3: "Locking requires the call to be `PUBLISHED` and the live
        `projected_union_count` to reach `required_union_slots` — exactly equal
        passes — and a shortfall is rejected with `ERR_UNION_RATIO_SHORTFALL`
        (HTTP 422)."
        PRD §2.6: "`projected_compliant` — whether that count reaches
        `required_union_slots` — is evaluated and stored at lock time as a frozen
        verdict that later booking changes do not alter."

        Design: Difficulty/boundary_precision_check/union_ratio_exactly_at_requirement_locks
        """
        prod, call = setup_published_call(union_slots=2, nonunion_slots=1)
        u1 = create_actor("SAG_AFTRA")
        u2 = create_actor("SAG_AFTRA")
        b1 = create_booking(call["id"], u1["id"])
        create_booking(call["id"], u2["id"])
        lock_call(call["id"])

        # Frozen-verdict readback: even after a union booking leaves the active
        # set, the stored lock-time verdict does not move.
        decline_booking(b1["id"], u1["id"])
        stored = validate_success(api.get_casting_call(call["id"], director_headers), 200)
        assert stored["status"] == "LOCKED"
        assert stored["projected_compliant"] is True
        assert stored["required_union_slots"] == 2
        assert stored["projected_union_count"] == 1

    def test_projected_frozen_actual_false_at_wrap(self, api, associate_headers):
        """PRD §2.6: "`projected_compliant` — whether that count reaches
        `required_union_slots` — is evaluated and stored at lock time as a frozen
        verdict that later booking changes do not alter."
        PRD §2.6: "The actual side is measured once, at wrap:
        `actual_union_checkins` freezes as the count of union bookings in
        `CHECKED_IN` or `WRAPPED`, `actual_compliant` records whether that count
        reaches `required_union_slots`, and both stay null-free but immutable
        thereafter (`actual_compliant` itself is null until wrap)."

        Design: Difficulty/dual_variant_calc/union_ratio_projected_vs_actual_divergence
        """
        prod, call, actor, booking, case = self._no_show_setup(api)
        res = api.wrap_casting_call(call["id"], associate_headers)
        wrapped = validate_success(res, 200)
        assert wrapped["status"] == "WRAPPED"
        assert wrapped["projected_compliant"] is True
        assert wrapped["actual_compliant"] is False
        assert wrapped["actual_union_checkins"] == 0

    def test_projected_actual_divergence_drops_compliance_index(
        self, api, director_headers, associate_headers
    ):
        """PRD §2.6: "Each production carries a `compliance_index` that starts at
        100. Every casting call that wraps with `actual_compliant` false subtracts
        15 from it, never driving it below zero."

        Design: Difficulty/dual_variant_calc/union_ratio_projected_vs_actual_divergence
        """
        prod, call, actor, booking, case = self._no_show_setup(api)
        res = api.wrap_casting_call(call["id"], associate_headers)
        wrapped = validate_success(res, 200)
        assert wrapped["actual_compliant"] is False
        prod_after = validate_success(api.get_production(prod["id"], director_headers), 200)
        assert prod_after["compliance_index"] == 85

    def _no_show_setup(self, api):
        """Union booking CONFIRMED on a u1/n0 call; LOCKED (projected compliant);
        SHOOTING; no-show at 08:05; case expired so the call can wrap."""
        prod, call, actor, booking, case, _sb_actors, _sb_entries = setup_no_show_case(
            standby_union_statuses=()
        )
        assert case["status"] == "OPEN"
        validate_success(
            api.expire_case(case["id"], TEST_USERS["associate_headers"]), 200
        )
        return prod, call, actor, booking, case


class TestRatioWaivers:
    def test_waiver_reduction_exceeds_slots_returns_422(self, api, director_headers):
        """PRD §3.2: "A reduction exceeding the call's `union_slots` is rejected
        with `ERR_WAIVER_REDUCTION_INVALID` (HTTP 422)"

        Design: Corner/validations/waiver_reduction_exceeds_slots_returns_422
        """
        prod = create_production(active=True)
        call = create_casting_call(prod["id"], union_slots=2, nonunion_slots=0)
        res = api.create_ratio_waiver(
            {
                "casting_call_id": call["id"],
                "union_slot_reduction": 3,
                "justification": "too large",
            },
            make_director_headers("dir-1"),
        )
        validate_error(res, ApiErrorId.ERR_WAIVER_REDUCTION_INVALID)

    def test_waiver_approve_then_lock_passes(self, api, director_headers):
        """PRD §3.2: "Approval stamps `decided_by_user_id` from the
        representative's header, writes the waiver's `union_slot_reduction` onto
        the call as its `approved_waiver_reduction`, recomputes
        `required_union_slots`, and increments the call's `version` alongside the
        waiver's own."
        PRD §3.3: "Locking requires the call to be `PUBLISHED` and the live
        `projected_union_count` to reach `required_union_slots` — exactly equal
        passes — and a shortfall is rejected with `ERR_UNION_RATIO_SHORTFALL`
        (HTTP 422)."

        Design: Corner/state_machines/waiver_approve_then_lock_passes
        """
        prod, call = setup_published_call(union_slots=2, nonunion_slots=0)
        actor = create_actor("SAG_AFTRA")
        create_booking(call["id"], actor["id"])
        waiver = create_ratio_waiver(call["id"], union_slot_reduction=1)

        shortfall = api.lock_casting_call(call["id"], director_headers)
        validate_error(shortfall, ApiErrorId.ERR_UNION_RATIO_SHORTFALL)

        approved = validate_success(
            api.approve_waiver(waiver["id"], make_union_rep_headers("union-1")), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "union-1"
        assert_ratio_waiver(approved)

        locked = validate_success(
            api.lock_casting_call(call["id"], director_headers), 200
        )
        assert locked["status"] == "LOCKED"
        assert locked["approved_waiver_reduction"] == 1
        assert locked["required_union_slots"] == 1
        assert locked["projected_compliant"] is True

    def test_waiver_approve_forbidden_for_director(self, api, director_headers):
        """PRD §2.1: "Each operation restricts which roles may invoke it; a caller
        whose role is not on the endpoint's authorized list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: waiver approve is authorized for UnionRepresentative only.

        Design: Corner/rbac/waiver_approve_forbidden_for_director
        """
        prod = create_production(active=True)
        call = create_casting_call(prod["id"], union_slots=2, nonunion_slots=0)
        waiver = create_ratio_waiver(call["id"], union_slot_reduction=1)
        res = api.approve_waiver(waiver["id"], make_director_headers("dir-2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
        waiver_after = validate_success(
            api.get_ratio_waiver(waiver["id"], director_headers), 200
        )
        assert waiver_after["status"] == "REQUESTED"

    def test_waiver_deny_after_approve_rejected(self, api, director_headers):
        """PRD §3.2: "Deciding a waiver no longer `REQUESTED` fails with
        `ERR_WAIVER_INVALID_STATE`."

        Design: Corner/errors/waiver_deny_after_approve_rejected
        """
        prod = create_production(active=True)
        call = create_casting_call(prod["id"], union_slots=2, nonunion_slots=0)
        waiver = create_ratio_waiver(call["id"], union_slot_reduction=1)
        validate_success(
            api.approve_waiver(waiver["id"], make_union_rep_headers("union-1")), 200
        )
        res = api.deny_waiver(waiver["id"], make_union_rep_headers("union-1"))
        validate_error(res, ApiErrorId.ERR_WAIVER_INVALID_STATE)

    def test_call_create_forbidden_for_associate(self, api, associate_headers):
        """PRD §2.1: "Each operation restricts which roles may invoke it; a caller
        whose role is not on the endpoint's authorized list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: casting-call creation is authorized for CastingDirector only.

        Design: Corner/rbac/call_create_forbidden_for_associate
        """
        prod = create_production(active=True)
        res = api.create_casting_call(
            {
                "production_id": prod["id"],
                "shoot_date": "2026-08-10",
                "general_call_time": "2026-08-10T07:00:00Z",
                "scheduled_duration_minutes": 600,
                "location": "Lot 70",
                "union_slots": 1,
                "nonunion_slots": 1,
                "union_rate_cents": 10000,
                "nonunion_rate_cents": 10000,
            },
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestCallCancel:
    def test_casting_call_cancel_cascades(self, api, director_headers, associate_headers):
        """PRD §3.3: "Cancellation moves the call to `CANCELLED`, moves every
        booking still `OFFERED` or `CONFIRMED` to `CANCELLED` with each releasing
        its slot, moves every `ACTIVE` standby entry to `EXPIRED`, revokes every
        `REQUESTED` ratio waiver to `REVOKED`, and increments the call's
        `version`."

        Design: Corner/state_machines/casting_call_cancel_cascades
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=0)
        a1 = create_actor("SAG_AFTRA")
        a2 = create_actor("SAG_AFTRA")
        booking = create_booking(call["id"], a1["id"])
        entry = create_standby_entry(call["id"], a2["id"])
        waiver = create_ratio_waiver(call["id"], union_slot_reduction=1)

        cancelled = validate_success(
            api.cancel_casting_call(call["id"], {"reason": "scene cut"}, director_headers),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["slots_available"] == 1

        booking_after = validate_success(
            api.get_booking(booking["id"], associate_headers), 200
        )
        assert booking_after["status"] == "CANCELLED"
        entry_after = validate_success(
            api.get_standby_entry(entry["id"], associate_headers), 200
        )
        assert entry_after["status"] == "EXPIRED"
        waiver_after = validate_success(
            api.get_ratio_waiver(waiver["id"], associate_headers), 200
        )
        assert waiver_after["status"] == "REVOKED"


class TestComplianceIndex:
    def test_compliance_index_blocks_publish_after_bad_wraps(
        self, api, director_headers, associate_headers
    ):
        """PRD §2.6: "Every casting call that wraps with `actual_compliant` false
        subtracts 15 from it, never driving it below zero. The index gates future
        publishing: a production whose `compliance_index` has fallen below 30 may
        not publish further calls, while an index of exactly 30 still passes."

        Design: Corner/cross_cutting_complexity_layers/compliance_index_blocks_publish_after_bad_wraps
        """
        prod = create_production(active=True, title="Film CI")
        actor_a = create_actor("SAG_AFTRA", legal_name="U CiA")
        actor_b = create_actor("SAG_AFTRA", legal_name="U CiB")
        actor_c = create_actor("SAG_AFTRA", legal_name="U CiC")

        def run_noncompliant_call(shoot_date, actor, lot):
            """u1/n0 call -> publish -> CONFIRMED -> lock -> shoot -> no-show at
            08:05 -> expire case -> wrap (actual 0 < required 1)."""
            call = create_casting_call(
                prod["id"],
                shoot_date=shoot_date,
                general_call_time=f"{shoot_date}T07:00:00Z",
                location=lot,
                union_slots=1,
                nonunion_slots=0,
            )
            publish_call(call["id"])
            booking = confirm_booking(call["id"], actor["id"])
            lock_call(call["id"])
            set_clock(f"{shoot_date}T06:55:00Z")
            validate_success(api.start_shooting(call["id"], associate_headers), 200)
            set_clock(f"{shoot_date}T08:05:00Z")
            validate_success(api.mark_no_show(booking["id"], associate_headers), 200)
            case = get_case_for_call(call["id"])
            validate_success(api.expire_case(case["id"], associate_headers), 200)
            wrapped = validate_success(
                api.wrap_casting_call(call["id"], associate_headers), 200
            )
            assert wrapped["actual_compliant"] is False
            return call["id"]

        run_noncompliant_call("2026-08-10", actor_a, "Lot C1")
        run_noncompliant_call("2026-08-11", actor_a, "Lot C2")
        run_noncompliant_call("2026-08-12", actor_b, "Lot C3")
        run_noncompliant_call("2026-08-13", actor_b, "Lot C4")

        prod_mid = validate_success(api.get_production(prod["id"], director_headers), 200)
        assert prod_mid["compliance_index"] == 40

        # 40 >= 30: publish still passes at the boundary side.
        call6 = create_casting_call(
            prod["id"],
            shoot_date="2026-08-15",
            general_call_time="2026-08-15T07:00:00Z",
            location="Lot C6",
            union_slots=1,
            nonunion_slots=0,
        )
        published6 = publish_call(call6["id"])
        assert published6["status"] == "PUBLISHED"

        run_noncompliant_call("2026-08-14", actor_c, "Lot C5")
        prod_low = validate_success(api.get_production(prod["id"], director_headers), 200)
        assert prod_low["compliance_index"] == 25

        call7 = create_casting_call(
            prod["id"],
            shoot_date="2026-08-16",
            general_call_time="2026-08-16T07:00:00Z",
            location="Lot C7",
            union_slots=1,
            nonunion_slots=0,
        )
        res = api.publish_casting_call(call7["id"], director_headers)
        validate_error(res, ApiErrorId.ERR_COMPLIANCE_INDEX_TOO_LOW)
