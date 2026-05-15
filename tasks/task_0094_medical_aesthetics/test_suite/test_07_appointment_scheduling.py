"""Appointment scheduling — PRD §3.4.

Covers:
  - prep_lead_time formula (per-SKU ceil_to_5 first, then MAX,
    then +30 if SURGICAL).
  - Four-way resource matching with distinct interval semantics:
      * room uses [prep_window_start, scheduled_end + 15)
      * doctor/nurse/equipment use [prep_window_start, scheduled_end)
      * anesthesia uses [scheduled_start, scheduled_end) — no prep, no gap.
  - Branching from SCHEDULED: reschedule self-loop, CANCEL, NO_SHOW
    via clock advance.
  - Reschedule limit boundary (<3).
  - Priority-pair (business_referential vs business_temporal).
  - Plan stale reference (Project.version drift after approval).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ATTENDING_PHYSICIAN_ID,
    ATTENDING_PHYSICIAN_ID_ALT,
    ApiErrorId,
    NO_SHOW_GRACE_MINUTES,
    NURSE_ID,
    PREP_CONSUMABLE,
    PREP_DRUG,
    RESCHEDULE_LIMIT,
    ROUNDING_STEP_MINUTES,
    SECONDS_PER_MINUTE,
    STERILIZATION_GAP_MINUTES,
    SURGICAL_PAD_MINUTES,
    TEST_USERS,
    advance_clock,
    api_client,
    approve_project,
    assert_appointment,
    create_appointment,
    create_consumable_sku,
    create_kyc_verified_customer,
    create_on_shelf_project,
    create_room,
    get_appointment,
    iso_offset,
    iso_utc,
    make_attending_physician_headers,
    plan_item,
    random_suffix,
    return_project_to_shelf,
    setup_approved_plan_simple,
    setup_scheduled_appointment,
    sign_consent,
    submit_plan,
    take_project_off_shelf,
    utcnow,
    validate_error,
    validate_success,
)


def _parse_iso(ts: str) -> datetime:
    """Best-effort ISO 8601 parser tolerant of trailing 'Z'."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _build_surgical_approved_plan_with_bom(
    *,
    bom_skus: list,
    duration_minutes: int = 60,
    base_price_cents: int = 100000,
) -> dict:
    """End-to-end: create SKU(s) → SURGICAL project on shelf → DRAFT
    plan → submit → consent → approve. The bom mirrors `bom_skus`,
    each entry shaped {"kind": "DRUG"|"CONSUMABLE", "quantity": int,
    "requires_lot": True/False}.

    Returns dict with: skus (list of dicts with id+spec), project,
    customer, plan, attending_doctor_id.
    """
    # 1) SKUs.
    skus = []
    for spec in bom_skus:
        s = create_consumable_sku(
            kind=spec["kind"],
            requires_lot_tracking=spec.get("requires_lot", True),
        )
        skus.append({**spec, "id": s["id"]})

    bom = [{"sku_id": s["id"], "quantity": int(s["quantity"])} for s in skus]

    # 2) SURGICAL project ON_SHELF.
    from test_helpers import (
        create_project_draft, submit_project, approve_project,
    )
    draft = create_project_draft(
        sku_id=skus[0]["id"],
        bom=bom,
        category="SURGICAL",
        risk_level="LOW",
        duration_minutes=int(duration_minutes),
        pricing_tiers=[
            {"tier_code": "T0",
             "base_price_cents": int(base_price_cents),
             "min_quantity": 1},
        ],
        qualified_doctor_ids=[ATTENDING_PHYSICIAN_ID],
    )
    submit_project(draft["id"])
    project = approve_project(draft["id"])

    # 3) Customer + plan + approve.
    customer = create_kyc_verified_customer(age_years=30)
    from test_helpers import (
        approve_plan_via_attending, create_draft_plan, sign_consent,
        submit_plan as _submit,
    )
    plan = create_draft_plan(
        customer_id=customer["id"],
        items=[plan_item(project["id"], "T0", 1)],
        attending_physician_id=ATTENDING_PHYSICIAN_ID,
    )
    plan = _submit(plan["id"])
    plan = sign_consent(plan["id"], customer["id"])
    plan = approve_plan_via_attending(plan["id"])
    return {
        "skus": skus,
        "project": project,
        "customer": customer,
        "plan": plan,
        "attending_doctor_id": ATTENDING_PHYSICIAN_ID,
    }


# ===========================================================================
# prep_lead_time — per-sku ceil_to_5 FIRST, then MAX (Rule 2 instance 2)
# ===========================================================================
# difficulty: combinatorial_formula/prep_lead_time_nested_rounding_mode_b
class TestPrepLeadTimeNestedRounding:
    """PRD §3.4: "For every BOM entry the system multiplies the
    quantity by that per-unit constant to produce a raw figure, then
    rounds that raw figure up to the next whole multiple of 5 minutes
    — this per-SKU ceiling is taken first. Then the maximum across
    all per-SKU ceilings is taken; the alternatives of summing before
    ceiling, or taking the max of the raw values before ceiling, are
    explicitly not used. If the project's category is SURGICAL, a
    fixed surgical pad of 30 minutes is added to the maximum."
    """

    def test_surgical_drug_3_consumable_2_yields_prep_lead_45(self, api):
        """PRD §3.4: "drugs contribute 4 minutes per unit and
        consumables 2 minutes per unit ... Per-SKU raw figure rounded
        UP to the next multiple of 5 minutes BEFORE the max-across-
        SKUs step. SURGICAL category adds a +30 minute pad."

        Claim: bom = [{DRUG_X, qty=3}, {CONSUMABLE_Y, qty=2}],
        SURGICAL. Per-sku raw: DRUG=3×4=12 → ceil_5=15; CONSUMABLE=
        2×2=4 → ceil_5=5. Max=15, plus SURGICAL pad 30 = 45.
        prep_window_start = scheduled_start − 45 minutes.

        # difficulty: combinatorial_formula/prep_lead_time_nested_rounding_mode_b
        """
        bundle = _build_surgical_approved_plan_with_bom(
            bom_skus=[
                {"kind": "DRUG", "quantity": 3, "requires_lot": True},
                {"kind": "CONSUMABLE", "quantity": 2, "requires_lot": False},
            ],
            duration_minutes=60,
        )
        # SURGICAL must have a SURGICAL_OR room and anesthesia.
        room = create_room(room_kind="SURGICAL_OR")
        start = utcnow() + timedelta(days=7)
        start = start.replace(second=0, microsecond=0)
        appt = create_appointment(
            plan_id=bundle["plan"]["id"],
            project_id=bundle["project"]["id"],
            scheduled_start_iso=iso_utc(start),
            room_id=room["id"],
            doctor_id=bundle["attending_doctor_id"],
            anesthesia_resource_id=f"anes-{random_suffix(4)}",
        )
        assert_appointment(appt)

        scheduled_start = _parse_iso(appt["scheduled_start"])
        prep_window_start = _parse_iso(appt["prep_window_start"])
        prep_lead = int(
            (scheduled_start - prep_window_start).total_seconds()
            / SECONDS_PER_MINUTE
        )
        assert prep_lead == 45, (
            f"PRD §3.4 prep_lead must be 45 minutes "
            f"(DRUG ceil=15, CONSUMABLE ceil=5, max=15, +SURGICAL_PAD=30); "
            f"got {prep_lead}"
        )


# ===========================================================================
# Room overlap with sterilization gap (Rule 8 instance 1)
# ===========================================================================
# difficulty: resource_temporal_overlap/room_overlap_with_sterilization_gap
class TestRoomOverlapWithSterilizationGap:
    """PRD §3.4: "For the room, the candidate interval is the same on
    the start side but is extended on the end side by a sterilization
    gap of 15 minutes — so the room's effective occupation is
    [prep_window_start, scheduled_end + 15min); overlap there is
    ERR_ROOM_CONFLICT (HTTP 409)."
    """

    def _make_non_surgical_plan_and_room(self, duration_minutes: int = 30):
        """A NON_SURGICAL plan whose project has a single CONSUMABLE
        SKU with quantity=1 (per-sku raw=2, ceil_5=5 → prep_lead=5
        minutes; no SURGICAL_PAD). Plus a fresh PROCEDURE room.

        Returns project, plan_a, plan_b, room. Both plans reference
        the same on-shelf project; the project's qualified_doctor_ids
        carries BOTH ATTENDING_PHYSICIAN_ID and ATTENDING_PHYSICIAN_ID_ALT,
        plan_a's attending physician is ATTENDING_PHYSICIAN_ID, and
        plan_b's is ATTENDING_PHYSICIAN_ID_ALT. This lets the candidate
        appointment legitimately use a different doctor (PRD §3.4
        requires doctor_id to equal that appointment's plan's attending
        physician) while still hitting room/anesthesia overlap against
        the prior appointment.
        """
        from test_helpers import (
            create_project_draft, submit_project, approve_project,
            create_draft_plan, approve_plan_via_attending,
            sign_consent, submit_plan,
        )
        sku = create_consumable_sku(
            kind="CONSUMABLE", requires_lot_tracking=False,
        )
        draft = create_project_draft(
            sku_id=sku["id"],
            bom=[{"sku_id": sku["id"], "quantity": 1}],
            category="NON_SURGICAL",
            risk_level="LOW",
            duration_minutes=int(duration_minutes),
            pricing_tiers=[
                {"tier_code": "T0", "base_price_cents": 100000,
                 "min_quantity": 1},
            ],
            qualified_doctor_ids=[
                ATTENDING_PHYSICIAN_ID, ATTENDING_PHYSICIAN_ID_ALT,
            ],
        )
        submit_project(draft["id"])
        project = approve_project(draft["id"])
        customer_a = create_kyc_verified_customer(age_years=30)
        plan_a = create_draft_plan(
            customer_id=customer_a["id"],
            items=[plan_item(project["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        plan_a = submit_plan(plan_a["id"])
        plan_a = sign_consent(plan_a["id"], customer_a["id"])
        plan_a = approve_plan_via_attending(plan_a["id"])
        # Second plan, different attending physician, same project.
        customer_b = create_kyc_verified_customer(age_years=30)
        plan_b = create_draft_plan(
            customer_id=customer_b["id"],
            items=[plan_item(project["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID_ALT,
        )
        plan_b = submit_plan(plan_b["id"])
        plan_b = sign_consent(plan_b["id"], customer_b["id"])
        plan_b = approve_plan_via_attending(
            plan_b["id"],
            attending_doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
        )
        room = create_room(room_kind="PROCEDURE")
        return project, plan_a, plan_b, room

    def test_room_overlap_inside_sterilization_pad_rejected(self, api):
        """PRD §3.4: "For the room, the candidate interval is the same
        on the start side but is extended on the end side by a
        sterilization gap of 15 minutes — so the room's effective
        occupation is [prep_window_start, scheduled_end + 15min);
        overlap there is ERR_ROOM_CONFLICT (HTTP 409)."

        Claim: existing A0 with room occupation 09:55–10:45 (end+15);
        a candidate A1 whose prep window starts 10:35 (< 10:45) is
        rejected with ERR_ROOM_CONFLICT.

        # difficulty: resource_temporal_overlap/room_overlap_with_sterilization_gap
        """
        project, plan_a, plan_b, room = (
            self._make_non_surgical_plan_and_room(duration_minutes=30)
        )
        # A0: scheduled_start=10:00, scheduled_end=10:30,
        # prep_window=09:55, room-extended end = 10:45.
        a0_start = utcnow().replace(
            hour=10, minute=0, second=0, microsecond=0,
        ) + timedelta(days=10)
        appt0 = create_appointment(
            plan_id=plan_a["id"],
            project_id=project["id"],
            scheduled_start_iso=iso_utc(a0_start),
            room_id=room["id"],
            doctor_id=ATTENDING_PHYSICIAN_ID,
            nurse_id=NURSE_ID,
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        # A1 with scheduled_start=10:40 → prep_window=10:35 → overlaps
        # room's 09:55–10:45 effective interval.
        a1_start = a0_start + timedelta(minutes=40)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=plan_b["id"], project_id=project["id"],
            scheduled_start=iso_utc(a1_start),
            doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
            nurse_id="nurse-002",
            room_id=room["id"],  # same room — that's the conflict.
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ROOM_CONFLICT.value)

    def test_room_adjacent_at_sterilization_boundary_accepted(self, api):
        """PRD §3.4: "Two half-open intervals overlap when one starts
        strictly before the other ends and the other starts strictly
        before the first ends."

        Claim: existing A0 with room end+15 == 10:45; candidate A1
        with prep_window=10:45 is NOT < 10:45 (half-open boundary) and
        is accepted.

        # difficulty: resource_temporal_overlap/room_overlap_with_sterilization_gap
        """
        project, plan_a, plan_b, room = (
            self._make_non_surgical_plan_and_room(duration_minutes=30)
        )
        a0_start = utcnow().replace(
            hour=10, minute=0, second=0, microsecond=0,
        ) + timedelta(days=20)
        create_appointment(
            plan_id=plan_a["id"], project_id=project["id"],
            scheduled_start_iso=iso_utc(a0_start),
            room_id=room["id"],
            doctor_id=ATTENDING_PHYSICIAN_ID,
            nurse_id=NURSE_ID,
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        # A1: scheduled_start=10:50 → prep_window=10:45 (== A0's
        # extended end). Half-open semantics: no overlap.
        a1_start = a0_start + timedelta(minutes=50)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=plan_b["id"], project_id=project["id"],
            scheduled_start=iso_utc(a1_start),
            doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
            nurse_id="nurse-002",
            room_id=room["id"],
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        data = validate_success(res, 201)
        assert_appointment(data)


# ===========================================================================
# Anesthesia overlap — no prep, no gap (Rule 8 instance 2)
# ===========================================================================
# difficulty: resource_temporal_overlap/anesthesia_overlap_no_prep_no_gap
class TestAnesthesiaOverlapNoPrepNoGap:
    """PRD §3.4: "For the anesthesia resource when present, the
    interval is [scheduled_start, scheduled_end) with neither the
    prep window nor the sterilization gap applied."
    """

    def _surgical_plan_with_single_drug_bom(self):
        """SURGICAL project with one DRUG SKU quantity=1; required
        anesthesia. The 5-minute per-sku ceiling + 30-minute pad means
        prep_lead = 35.

        Returns project, plan_a, plan_b, sku. Both plans reference
        the same SURGICAL project; the project is qualified for BOTH
        ATTENDING_PHYSICIAN_ID and ATTENDING_PHYSICIAN_ID_ALT so that
        the candidate appointment (under plan_b) can legitimately use
        the alt doctor while sharing the same anesthesia resource as
        A0 (under plan_a). PRD §3.4 requires doctor_id to equal the
        candidate's plan's attending physician.
        """
        from test_helpers import (
            create_project_draft, submit_project, approve_project,
            create_draft_plan, approve_plan_via_attending,
            sign_consent, submit_plan,
        )
        sku = create_consumable_sku(kind="DRUG", requires_lot_tracking=True)
        draft = create_project_draft(
            sku_id=sku["id"],
            bom=[{"sku_id": sku["id"], "quantity": 1}],
            category="SURGICAL",
            risk_level="LOW",
            duration_minutes=30,
            pricing_tiers=[
                {"tier_code": "T0", "base_price_cents": 100000,
                 "min_quantity": 1},
            ],
            qualified_doctor_ids=[
                ATTENDING_PHYSICIAN_ID, ATTENDING_PHYSICIAN_ID_ALT,
            ],
        )
        submit_project(draft["id"])
        project = approve_project(draft["id"])
        customer_a = create_kyc_verified_customer(age_years=30)
        plan_a = create_draft_plan(
            customer_id=customer_a["id"],
            items=[plan_item(project["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        plan_a = submit_plan(plan_a["id"])
        plan_a = sign_consent(plan_a["id"], customer_a["id"])
        plan_a = approve_plan_via_attending(plan_a["id"])
        customer_b = create_kyc_verified_customer(age_years=30)
        plan_b = create_draft_plan(
            customer_id=customer_b["id"],
            items=[plan_item(project["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID_ALT,
        )
        plan_b = submit_plan(plan_b["id"])
        plan_b = sign_consent(plan_b["id"], customer_b["id"])
        plan_b = approve_plan_via_attending(
            plan_b["id"],
            attending_doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
        )
        return project, plan_a, plan_b, sku

    def test_anesthesia_overlap_rejected_no_prep_window(self, api):
        """PRD §3.4: "For the anesthesia resource when present, the
        interval is [scheduled_start, scheduled_end) with neither the
        prep window nor the sterilization gap applied; overlap is
        ERR_ANESTHESIA_CONFLICT (HTTP 409)."

        Claim: A0 anesthesia interval 10:00–10:30; candidate A2 with
        scheduled_start=10:25 overlaps by 5 minutes and yields
        ERR_ANESTHESIA_CONFLICT.

        # difficulty: resource_temporal_overlap/anesthesia_overlap_no_prep_no_gap
        """
        project, plan_a, plan_b, _ = (
            self._surgical_plan_with_single_drug_bom()
        )
        anes_id = f"anes-{random_suffix(6)}"
        a0_start = utcnow().replace(
            hour=10, minute=0, second=0, microsecond=0,
        ) + timedelta(days=15)

        # A0: 10:00–10:30, anesthesia=anes_id. Use unique
        # room/doctor/nurse/equipment so they cannot collide.
        room_a = create_room(room_kind="SURGICAL_OR")
        room_b = create_room(room_kind="SURGICAL_OR")
        create_appointment(
            plan_id=plan_a["id"], project_id=project["id"],
            scheduled_start_iso=iso_utc(a0_start),
            room_id=room_a["id"],
            doctor_id=ATTENDING_PHYSICIAN_ID,
            nurse_id=NURSE_ID,
            equipment_ids=[f"eq-A-{random_suffix(4)}"],
            anesthesia_resource_id=anes_id,
        )
        # A2: 10:25 → overlaps anesthesia by 5 minutes. New doctor +
        # nurse + room + equipment so only the anesthesia matters.
        a2_start = a0_start + timedelta(minutes=25)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=plan_b["id"], project_id=project["id"],
            scheduled_start=iso_utc(a2_start),
            doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
            nurse_id="nurse-002",
            room_id=room_b["id"],
            equipment_ids=[f"eq-B-{random_suffix(4)}"],
            anesthesia_resource_id=anes_id,
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ANESTHESIA_CONFLICT.value)

    def test_anesthesia_adjacent_at_boundary_accepted(self, api):
        """PRD §3.4: "For the anesthesia resource when present, the
        interval is [scheduled_start, scheduled_end) ..."

        Claim: half-open: candidate scheduled_start == previous
        scheduled_end is NOT < scheduled_end and is accepted.

        # difficulty: resource_temporal_overlap/anesthesia_overlap_no_prep_no_gap
        """
        project, plan_a, plan_b, _ = (
            self._surgical_plan_with_single_drug_bom()
        )
        anes_id = f"anes-{random_suffix(6)}"
        a0_start = utcnow().replace(
            hour=10, minute=0, second=0, microsecond=0,
        ) + timedelta(days=25)
        room_a = create_room(room_kind="SURGICAL_OR")
        room_b = create_room(room_kind="SURGICAL_OR")
        create_appointment(
            plan_id=plan_a["id"], project_id=project["id"],
            scheduled_start_iso=iso_utc(a0_start),
            room_id=room_a["id"],
            doctor_id=ATTENDING_PHYSICIAN_ID,
            nurse_id=NURSE_ID,
            equipment_ids=[f"eq-A-{random_suffix(4)}"],
            anesthesia_resource_id=anes_id,
        )
        # A1: scheduled_start = a0_end = a0_start + 30 minutes.
        a1_start = a0_start + timedelta(minutes=30)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=plan_b["id"], project_id=project["id"],
            scheduled_start=iso_utc(a1_start),
            doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
            nurse_id="nurse-002",
            room_id=room_b["id"],
            equipment_ids=[f"eq-B-{random_suffix(4)}"],
            anesthesia_resource_id=anes_id,
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_success(res, 201)


# ===========================================================================
# Anesthesia / room kind requirement gates
# ===========================================================================
class TestAnesthesiaAndRoomKindRequirements:

    def test_surgical_without_anesthesia_rejected(self, api):
        """PRD §3.4: "The anesthesia field is required if and only if
        the project's category is SURGICAL. Supplying
        anesthesia_resource_id for a non-surgical project, or omitting
        it for a surgical project, yields
        ERR_ANESTHESIA_REQUIREMENT_MISMATCH (HTTP 422)."

        Claim: SURGICAL plan + omitted anesthesia_resource_id →
        ERR_ANESTHESIA_REQUIREMENT_MISMATCH.
        """
        bundle = setup_approved_plan_simple(
            category="SURGICAL", duration_minutes=30,
        )
        room = create_room(room_kind="SURGICAL_OR")
        start = utcnow() + timedelta(days=7)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=bundle["plan"]["id"],
            project_id=bundle["project"]["id"],
            scheduled_start=iso_utc(start),
            doctor_id=bundle["attending_doctor_id"],
            nurse_id=NURSE_ID,
            room_id=room["id"],
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ANESTHESIA_REQUIREMENT_MISMATCH.value)

    def test_non_surgical_with_anesthesia_rejected(self, api):
        """PRD §3.4: "Supplying anesthesia_resource_id for a non-
        surgical project, or omitting it for a surgical project,
        yields ERR_ANESTHESIA_REQUIREMENT_MISMATCH (HTTP 422)."

        Claim: NON_SURGICAL plan + provided anesthesia → mismatch.
        """
        bundle = setup_approved_plan_simple(category="NON_SURGICAL")
        room = create_room(room_kind="PROCEDURE")
        start = utcnow() + timedelta(days=7)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=bundle["plan"]["id"],
            project_id=bundle["project"]["id"],
            scheduled_start=iso_utc(start),
            doctor_id=bundle["attending_doctor_id"],
            nurse_id=NURSE_ID,
            room_id=room["id"],
            equipment_ids=[f"eq-{random_suffix(4)}"],
            anesthesia_resource_id=f"anes-{random_suffix(4)}",
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ANESTHESIA_REQUIREMENT_MISMATCH.value)

    def test_non_surgical_with_surgical_or_room_rejected(self, api):
        """PRD §3.1: "The room_kind of SURGICAL_OR is required when
        (and only when) the project's category is SURGICAL; this is
        enforced when the appointment is created or rescheduled and
        surfaces as ERR_ROOM_KIND_MISMATCH (HTTP 422)."

        Claim: NON_SURGICAL plan booked into a SURGICAL_OR room →
        ERR_ROOM_KIND_MISMATCH.
        """
        bundle = setup_approved_plan_simple(category="NON_SURGICAL")
        room = create_room(room_kind="SURGICAL_OR")
        start = utcnow() + timedelta(days=7)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=bundle["plan"]["id"],
            project_id=bundle["project"]["id"],
            scheduled_start=iso_utc(start),
            doctor_id=bundle["attending_doctor_id"],
            nurse_id=NURSE_ID,
            room_id=room["id"],
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ROOM_KIND_MISMATCH.value)


# ===========================================================================
# Branching from SCHEDULED (Rule 3 instance 2)
# ===========================================================================
# difficulty: non_linear_state_machine/appointment_branching_to_terminals
class TestAppointmentBranching:
    """PRD §3.4: "Reschedule is a self-loop from SCHEDULED to
    SCHEDULED ... An appointment in SCHEDULED may also be cancelled
    by the consultant (state advances to terminal CANCELLED) or —
    through the scheduled-time-elapsed sweep — auto-transitioned to
    terminal NO_SHOW when the server clock crosses scheduled_end plus
    60 minutes while the appointment is still SCHEDULED."
    """

    def test_reschedule_self_loop_increments_count(self, api):
        """PRD §3.4: "It increments reschedule_count, recomputes
        scheduled_end and prep_window_start, and re-runs the four-way
        match."

        Claim: reschedule increments reschedule_count by 1 and leaves
        status SCHEDULED.

        # difficulty: non_linear_state_machine/appointment_branching_to_terminals
        """
        bundle = setup_scheduled_appointment()
        appt = bundle["appointment"]
        assert appt["reschedule_count"] == 0
        # Move start a few hours later, into a free window.
        new_start = _parse_iso(appt["scheduled_start"]) + timedelta(hours=4)
        from test_helpers import reschedule_appointment_payload
        res = api.reschedule_appointment(
            appt["id"],
            reschedule_appointment_payload(scheduled_start=iso_utc(new_start)),
            TEST_USERS["consultant_headers"],
        )
        rescheduled = validate_success(res, 200)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["reschedule_count"] == 1

    def test_cancel_appointment_moves_to_cancelled(self, api):
        """PRD §3.4: "An appointment in SCHEDULED may also be cancelled
        by the consultant (state advances to terminal CANCELLED)."

        Claim: cancel on SCHEDULED → status CANCELLED.

        # difficulty: non_linear_state_machine/appointment_branching_to_terminals
        """
        bundle = setup_scheduled_appointment()
        res = api.cancel_appointment(
            bundle["appointment"]["id"],
            TEST_USERS["consultant_headers"],
        )
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"

    def test_no_show_after_clock_advance_past_grace(self, api):
        """PRD §3.4: "auto-transitioned to terminal NO_SHOW when the
        server clock crosses scheduled_end plus 60 minutes while the
        appointment is still SCHEDULED."
        PRD §2.10: "appointments still SCHEDULED past their
        scheduled_end plus 60 minutes transition to NO_SHOW."

        Claim: advance clock past scheduled_end + 60 minutes →
        Appointment.status == 'NO_SHOW'.

        # difficulty: non_linear_state_machine/appointment_branching_to_terminals
        """
        # Build a SCHEDULED appointment whose scheduled_start is
        # measured against the server's LOGICAL clock (PRD §2.10),
        # not the test runner's wall clock. The advance_clock sweep
        # works on the logical clock; if scheduled_start is pinned to
        # real-world utcnow() while the logical clock starts at an
        # implementation-chosen epoch, no finite advance can cross
        # scheduled_end + 60min.
        from test_helpers import (
            setup_approved_plan_simple, server_now_iso,
        )
        bundle = setup_approved_plan_simple(
            category="NON_SURGICAL", duration_minutes=30,
        )
        room = create_room(room_kind="PROCEDURE")
        server_now = _parse_iso(server_now_iso())
        start = (server_now + timedelta(minutes=10)).replace(microsecond=0)
        appt = create_appointment(
            plan_id=bundle["plan"]["id"],
            project_id=bundle["project"]["id"],
            scheduled_start_iso=iso_utc(start),
            room_id=room["id"],
            doctor_id=bundle["attending_doctor_id"],
            nurse_id=NURSE_ID,
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        # Advance past scheduled_end + 60 minutes (10 + 30 + 60 = 100min
        # from server's current logical-clock time; add 5min safety).
        advance_clock(
            seconds=(10 + 30 + NO_SHOW_GRACE_MINUTES + 5) * 60,
        )
        appt_after = get_appointment(appt["id"])
        assert appt_after["status"] == "NO_SHOW", (
            f"PRD §2.10/§3.4: appointment must auto-transition to "
            f"NO_SHOW after scheduled_end + 60 minutes; got "
            f"{appt_after['status']}"
        )


# ===========================================================================
# Reschedule limit boundary (Rule 6 instance 1)
# ===========================================================================
# difficulty: boundary_precision_check/reschedule_count_strict_less_than_3
class TestRescheduleLimit:
    """PRD §3.4: "A reschedule attempt when reschedule_count is
    already 3 is rejected with ERR_RESCHEDULE_LIMIT (HTTP 422)."
    """

    def test_third_reschedule_succeeds_fourth_rejected(self, api):
        """PRD §3.4: "A reschedule attempt when `reschedule_count` is
        already 3 is rejected with `ERR_RESCHEDULE_LIMIT` (HTTP 422)."

        Claim: three successive reschedules succeed
        (reschedule_count 0→1→2→3); fourth fails with
        ERR_RESCHEDULE_LIMIT.

        # difficulty: boundary_precision_check/reschedule_count_strict_less_than_3
        """
        bundle = setup_scheduled_appointment()
        appt = bundle["appointment"]
        from test_helpers import reschedule_appointment_payload
        # First three reschedules push count to 3.
        for i in range(3):
            new_start = _parse_iso(appt["scheduled_start"]) + timedelta(
                hours=(i + 1) * 5,
            )
            res = api.reschedule_appointment(
                appt["id"],
                reschedule_appointment_payload(
                    scheduled_start=iso_utc(new_start),
                ),
                TEST_USERS["consultant_headers"],
            )
            appt = validate_success(res, 200)
            assert appt["reschedule_count"] == i + 1
        assert appt["reschedule_count"] == 3
        # Fourth must fail.
        new_start = _parse_iso(appt["scheduled_start"]) + timedelta(hours=99)
        res = api.reschedule_appointment(
            appt["id"],
            reschedule_appointment_payload(
                scheduled_start=iso_utc(new_start),
            ),
            TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_RESCHEDULE_LIMIT.value)


# ===========================================================================
# Priority pair: business_referential vs business_temporal (Rule 5 inst2)
# ===========================================================================
# difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_priority
class TestDoctorQualifiedVsConflictPriority:
    """PRD §2.6: "After these gates clear, business-safety checks
    run ... followed by business-referential checks (doctor-qualified,
    project-on-shelf, anesthesia requirement vs project category,
    room kind vs project category), then business-temporal checks
    (doctor / nurse / room / equipment / anesthesia overlap, check-in
    window) ..."
    """

    def test_doctor_not_qualified_wins_over_doctor_conflict(self, api):
        """PRD §2.6 names business_referential before business_temporal.
        PRD §3.4: "the doctor_id (which must equal the plan's
        attending physician at appointment-create time and must remain
        in the project's qualified_doctor_ids)."
        PRD §3.3: "When the chosen attending_physician_id is not
        present in Project.qualified_doctor_ids for every included
        project the request is rejected with ERR_DOCTOR_NOT_QUALIFIED
        (HTTP 422); this check fires at plan creation, plan
        submission, and appointment creation."

        Claim: an appointment whose doctor_id is BOTH unqualified for
        the project AND already double-booked surfaces
        ERR_DOCTOR_NOT_QUALIFIED (business_referential, higher
        priority), not ERR_DOCTOR_CONFLICT (business_temporal).

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_priority
        """
        # Build a plan where qualified_doctor_ids contains only D1.
        bundle = setup_approved_plan_simple(
            category="NON_SURGICAL", duration_minutes=30,
        )
        # The project's qualified_doctor_ids includes
        # ATTENDING_PHYSICIAN_ID (D1). D2 is not in there.
        room = create_room(room_kind="PROCEDURE")
        a0_start = utcnow().replace(
            hour=9, minute=0, second=0, microsecond=0,
        ) + timedelta(days=30)
        # First create A0 booking D2 9:00–9:30, on a separate plan to
        # keep the "qualified" check independent. Easiest: book A0
        # using D1 (qualified for THIS project) and a different room/
        # equipment. Then the second attempt below uses D1 in an
        # overlap window AND swaps doctor_id to D2 — but D2 isn't in
        # the qualified set. So the test must produce both ERRs from
        # the SAME attempted appointment.
        from test_helpers import create_appointment_payload
        # Step 1: book A0 under D2 ON A DIFFERENT plan where D2 is
        # qualified — we need a second project that includes D2 in
        # qualified_doctor_ids so the booking succeeds.
        sku2 = create_consumable_sku(
            kind="CONSUMABLE", requires_lot_tracking=False,
        )
        from test_helpers import (
            create_project_draft, submit_project, approve_project,
            create_draft_plan, approve_plan_via_attending,
            sign_consent, submit_plan,
        )
        other_draft = create_project_draft(
            sku_id=sku2["id"],
            bom=[{"sku_id": sku2["id"], "quantity": 1}],
            category="NON_SURGICAL",
            risk_level="LOW",
            duration_minutes=30,
            pricing_tiers=[
                {"tier_code": "T0", "base_price_cents": 100000,
                 "min_quantity": 1},
            ],
            qualified_doctor_ids=[ATTENDING_PHYSICIAN_ID_ALT],
        )
        submit_project(other_draft["id"])
        other_project = approve_project(other_draft["id"])
        customer2 = create_kyc_verified_customer(age_years=30)
        plan2 = create_draft_plan(
            customer_id=customer2["id"],
            items=[plan_item(other_project["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID_ALT,
        )
        plan2 = submit_plan(plan2["id"])
        plan2 = sign_consent(plan2["id"], customer2["id"])
        plan2 = approve_plan_via_attending(
            plan2["id"], attending_doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
        )
        # A0 books D2 from 9:00–9:30.
        create_appointment(
            plan_id=plan2["id"], project_id=other_project["id"],
            scheduled_start_iso=iso_utc(a0_start),
            room_id=create_room(room_kind="PROCEDURE")["id"],
            doctor_id=ATTENDING_PHYSICIAN_ID_ALT,
            nurse_id=NURSE_ID,
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        # Now try to book on the FIRST plan with doctor_id = D2 (not
        # qualified) and at an overlapping window (9:30 → so D2's
        # prep window starts before 9:30, overlapping 9:00–9:30).
        a1_start = a0_start + timedelta(minutes=30)
        payload = create_appointment_payload(
            plan_id=bundle["plan"]["id"],
            project_id=bundle["project"]["id"],
            scheduled_start=iso_utc(a1_start),
            doctor_id=ATTENDING_PHYSICIAN_ID_ALT,  # NOT qualified here.
            nurse_id=NURSE_ID,
            room_id=room["id"],
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        # Per PRD §2.6, business_referential (priority 12, doctor
        # qualification) fires BEFORE business_temporal (priority 16,
        # doctor conflict).
        validate_error(res, ApiErrorId.ERR_DOCTOR_NOT_QUALIFIED.value)


# ===========================================================================
# Plan stale reference (Rule 7 instance 2)
# ===========================================================================
# difficulty: cross_entity_state_dependency/appointment_create_requires_plan_approved_with_unstale_snapshot
class TestPlanStaleReference:
    """PRD §3.4: "Creating an appointment under an APPROVED plan first
    checks that no project in locked_project_versions has drifted —
    that is, every project's current version equals the value
    snapshotted at plan approval. If any project's version no longer
    matches the snapshot, the appointment request is rejected with
    ERR_PLAN_STALE_REFERENCE (HTTP 409)."
    """

    def test_appointment_create_blocked_after_project_version_drift(
        self, api,
    ):
        """PRD §3.4: "If any project's version no longer matches the
        snapshot, the appointment request is rejected with
        ERR_PLAN_STALE_REFERENCE (HTTP 409); the same check applies
        to reschedule operations."

        Claim: after take-off-shelf + return-to-shelf bumps
        Project.version twice, the next appointment-create under the
        previously-APPROVED plan yields ERR_PLAN_STALE_REFERENCE.

        # difficulty: cross_entity_state_dependency/appointment_create_requires_plan_approved_with_unstale_snapshot
        """
        bundle = setup_approved_plan_simple(category="NON_SURGICAL")
        project_id = bundle["project"]["id"]
        # Drift Project.version: take off shelf and return.
        take_project_off_shelf(project_id)
        return_project_to_shelf(project_id)

        # Now try to create an appointment under the plan: stale.
        room = create_room(room_kind="PROCEDURE")
        start = utcnow() + timedelta(days=7)
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=bundle["plan"]["id"],
            project_id=project_id,
            scheduled_start=iso_utc(start),
            doctor_id=bundle["attending_doctor_id"],
            nurse_id=NURSE_ID,
            room_id=room["id"],
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PLAN_STALE_REFERENCE.value)


# ===========================================================================
# Doctor conflict — basic temporal overlap on the doctor resource
# ===========================================================================
class TestDoctorConflict:

    def test_overlapping_doctor_yields_doctor_conflict(self, api):
        """PRD §3.4: "For the doctor, the nurse, and every equipment
        id, the candidate interval is [prep_window_start, scheduled_end);
        an overlap on any of these resources rejects the request with
        ERR_DOCTOR_CONFLICT, ERR_NURSE_CONFLICT, or
        ERR_EQUIPMENT_CONFLICT (all HTTP 409)."

        Claim: same doctor on overlapping windows → ERR_DOCTOR_CONFLICT.
        """
        bundle = setup_scheduled_appointment(category="NON_SURGICAL")
        appt0 = bundle["appointment"]
        # Same doctor, same time → overlap.
        from test_helpers import create_appointment_payload
        payload = create_appointment_payload(
            plan_id=bundle["plan"]["id"],
            project_id=bundle["project"]["id"],
            scheduled_start=appt0["scheduled_start"],
            doctor_id=appt0["doctor_id"],
            nurse_id="nurse-other",
            room_id=create_room(room_kind="PROCEDURE")["id"],
            equipment_ids=[f"eq-{random_suffix(4)}"],
        )
        res = api.create_appointment(
            payload, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DOCTOR_CONFLICT.value)
