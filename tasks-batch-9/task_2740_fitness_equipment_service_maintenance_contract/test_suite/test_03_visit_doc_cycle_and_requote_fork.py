"""
State machines that loop on themselves before they fork.

Neither of the two rows exercised here walks a straight line:

* a ``PreventiveVisit`` carries two dimensions at once, and its documentation dimension
  keeps cycling ``REJECTED`` -> ``SUBMITTED`` long after the execution dimension has
  reached ``COMPLETED``, with ``pm_credit_earned`` reading both at every step;
* a ``ServiceContract`` loops ``RENEWAL_QUOTED`` -> ``RENEWAL_QUOTED`` when a second
  quote supersedes the first, and only afterwards forks — and the decline branch
  carries a teardown the accept branch does not.

Every world below is built from scratch through declared endpoints, because the
server restarts with an empty database before each test.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    assignment_for_visit,
    assert_fields,
    assert_two_decimals,
    checklist_item,
    checklist_result_payload,
    contract_version,
    get_success_data,
    inspector_headers,
    manager_headers,
    new_active_contract,
    new_club,
    new_equipment,
    new_model,
    new_technician,
    quote_decline_payload,
    read_assignment,
    read_contract,
    read_equipment,
    read_quote,
    read_technician,
    read_visit,
    renewal_quote_payload,
    safety_doc_reject_payload,
    safety_doc_submit_payload,
    schedule_visit,
    set_clock,
    start_visit,
    technician_headers,
)

GOLD_FULL_TERM = {
    "coverage_tier": "GOLD",
    "parts_inclusion": "FULL",
    "pm_visits_per_year": 4,
    "annual_base_cents": 250000,
    "initial_parts_allowance_cents": 500000,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
}

REJECTION_REASON = "Estop test evidence missing from the summary."


def _completed_visit_world(api):
    """
    A GOLD/FULL club whose treadmill has just had a fully passed preventive visit
    completed on 2026-08-12, with the paperwork still unfiled. ``T1`` did the work and
    ``T2`` holds the inspector credential.
    """
    set_clock(api, "2026-08-12T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    model = new_model(
        api,
        manufacturer="Pacemaster",
        model_code="TM-900",
        category="TREADMILL",
        model_year=2019,
        pm_interval_hours=250,
        expected_service_life_hours=20000,
        base_annual_service_cents=120000,
        checklist_template=[
            checklist_item("BELT_TENSION", is_safety_critical=False, consumable=True),
            checklist_item("ESTOP_FUNCTION", is_safety_critical=True, consumable=False),
        ],
    )
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-PV-1",
        install_date="2024-03-01",
        initial_usage_hours=300,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    worker = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
    )
    inspector = new_technician(
        api,
        full_name="Ivo Marsh",
        region_code="NW",
        skill_categories=["TREADMILL"],
        is_safety_inspector=True,
    )
    visit = schedule_visit(
        api,
        contract["id"],
        unit["id"],
        "2026-08-12T09:00:00Z",
        "2026-08-12T10:30:00Z",
        worker["id"],
    )

    set_clock(api, "2026-08-12T09:00:00Z")
    start_visit(api, visit["id"], worker["id"])
    get_success_data(
        api.record_checklist_result(
            visit["id"],
            checklist_result_payload(
                "BELT_TENSION", result="PASS", consumable_replaced=True
            ),
            technician_headers(worker["id"]),
        )
    )
    get_success_data(
        api.record_checklist_result(
            visit["id"],
            checklist_result_payload("ESTOP_FUNCTION", result="PASS"),
            technician_headers(worker["id"]),
        )
    )
    set_clock(api, "2026-08-12T10:00:00Z")
    completion = get_success_data(
        api.complete_visit(visit["id"], technician_headers(worker["id"]))
    )
    return {
        "club_id": club["id"],
        "contract_id": contract["id"],
        "equipment_id": unit["id"],
        "visit_id": visit["id"],
        "worker_id": worker["id"],
        "inspector_id": inspector["id"],
        "completion": completion,
    }


def _submit_doc(api, world, summary):
    return get_success_data(
        api.submit_safety_doc(
            world["visit_id"],
            safety_doc_submit_payload(summary),
            technician_headers(world["worker_id"]),
        )
    )


def test_rejecting_the_paperwork_leaves_the_visit_completed_and_unpaid(api):
    """
    Completion alone never earns the preventive credit, and a rejected document keeps
    the credit at false while the execution dimension stays COMPLETED throughout.

    PRD 3.5: "It sets `safety_doc_status` to `REJECTED`, stores the supplied
    `rejection_reason` into `safety_doc_rejection_reason`, and forces `pm_credit_earned`
    back to `false` even if the visit had already completed and previously earned it."

    Design: Difficulty/non_linear_state_machine/preventive_visit_doc_dimension_cycles_after_visit_is_terminal
    """
    world = _completed_visit_world(api)

    at_completion = world["completion"]
    assert at_completion["visit_status"] == "COMPLETED", at_completion["visit_status"]
    # The paperwork has not even been filed, so the second of the two conditions is
    # unmet and the credit cannot be earned by completion on its own.
    assert at_completion["pm_credit_earned"] is False
    assert at_completion["safety_doc_status"] == "PENDING", (
        at_completion["safety_doc_status"]
    )
    assert at_completion["checklist_resolved_count"] == 2, (
        at_completion["checklist_resolved_count"]
    )
    assert at_completion["checklist_failed_count"] == 0, (
        at_completion["checklist_failed_count"]
    )
    assert at_completion["consumables_replaced_count"] == 1, (
        at_completion["consumables_replaced_count"]
    )

    submitted = _submit_doc(api, world, "Deck and estop inspected, belt dressing replaced.")
    assert submitted["safety_doc_status"] == "SUBMITTED", submitted["safety_doc_status"]
    assert submitted["visit_status"] == "COMPLETED", submitted["visit_status"]
    assert submitted["pm_credit_earned"] is False

    rejected = get_success_data(
        api.reject_safety_doc(
            world["visit_id"],
            safety_doc_reject_payload(REJECTION_REASON),
            inspector_headers(world["inspector_id"]),
        )
    )
    # The documentation dimension moved on its own trigger; the execution dimension is
    # untouched by it.
    assert rejected["safety_doc_status"] == "REJECTED", rejected["safety_doc_status"]
    assert rejected["visit_status"] == "COMPLETED", rejected["visit_status"]
    assert rejected["pm_credit_earned"] is False
    assert rejected["safety_doc_rejection_reason"] == REJECTION_REASON, (
        rejected["safety_doc_rejection_reason"]
    )

    # The rejection cascades onto the machine that was serviced.
    unit = read_equipment(api, world["equipment_id"])
    assert_fields(
        unit,
        lifecycle_status="TAGGED_OUT",
        safety_lockout_reason="SAFETY_DOC_REJECTED",
    )


def test_resubmitting_after_rejection_and_certifying_earns_the_credit(api):
    """
    The rejected document cycles back to SUBMITTED, clearing its rejection reason, and
    certification by the second technician flips the credit to true on a visit that was
    already COMPLETED — while the machine stays locked out.

    PRD 3.5: "`REJECTED` is not terminal: the documentation dimension has its own cycle,
    and a rejected document may be resubmitted, returning `REJECTED` → `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/preventive_visit_doc_dimension_cycles_after_visit_is_terminal
    """
    world = _completed_visit_world(api)

    _submit_doc(api, world, "Deck and estop inspected, belt dressing replaced.")
    get_success_data(
        api.reject_safety_doc(
            world["visit_id"],
            safety_doc_reject_payload(REJECTION_REASON),
            inspector_headers(world["inspector_id"]),
        )
    )

    # Round two of the documentation cycle, filed against a visit that has been in a
    # terminal execution state for the whole exchange.
    resubmitted = _submit_doc(
        api, world, "Estop test evidence attached; deck and belt re-verified."
    )
    assert resubmitted["safety_doc_status"] == "SUBMITTED", (
        resubmitted["safety_doc_status"]
    )
    assert resubmitted["visit_status"] == "COMPLETED", resubmitted["visit_status"]
    assert resubmitted["safety_doc_rejection_reason"] is None, (
        resubmitted["safety_doc_rejection_reason"]
    )
    assert resubmitted["pm_credit_earned"] is False

    certified = get_success_data(
        api.certify_safety_doc(
            world["visit_id"], inspector_headers(world["inspector_id"])
        )
    )
    assert certified["safety_doc_status"] == "CERTIFIED", certified["safety_doc_status"]
    assert certified["safety_doc_certified_by_id"] == world["inspector_id"], (
        certified["safety_doc_certified_by_id"]
    )

    visit = read_visit(api, world["visit_id"])
    # Four documentation transitions later, the execution dimension has not moved.
    assert visit["visit_status"] == "COMPLETED", visit["visit_status"]
    assert visit["safety_doc_status"] == "CERTIFIED", visit["safety_doc_status"]
    assert visit["safety_doc_rejection_reason"] is None, (
        visit["safety_doc_rejection_reason"]
    )
    assert visit["pm_credit_earned"] is True
    assert visit["consumables_replaced_count"] == 1, visit["consumables_replaced_count"]
    assert visit["checklist_resolved_count"] == 2, visit["checklist_resolved_count"]
    assert visit["checklist_failed_count"] == 0, visit["checklist_failed_count"]

    # Certifying the replacement document is not a clearance, so the lockout the
    # earlier rejection created still stands.
    unit = read_equipment(api, world["equipment_id"])
    assert_fields(
        unit,
        lifecycle_status="TAGGED_OUT",
        safety_lockout_reason="SAFETY_DOC_REJECTED",
    )

    contract = read_contract(api, world["contract_id"])
    assert contract["pm_visits_completed_count"] == 1, (
        contract["pm_visits_completed_count"]
    )
    assert_two_decimals(contract["pm_compliance_pct"], 100.00, "pm_compliance_pct")


DECLINE_REASON = "Club is relocating the cardio floor."


def _scheduled_forward_visit_world(api):
    """
    A GOLD/FULL club on a 140000-cent term with one treadmill and one preventive visit
    booked five days out, holding 90 of technician ``T1``'s minutes.
    """
    set_clock(api, "2026-08-20T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    model = new_model(
        api,
        manufacturer="Pacemaster",
        model_code="TM-900",
        category="TREADMILL",
        model_year=2019,
        pm_interval_hours=250,
        expected_service_life_hours=20000,
        base_annual_service_cents=120000,
    )
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-RC-1",
        install_date="2024-03-01",
        initial_usage_hours=4000,
    )
    contract = new_active_contract(
        api, club["id"], **dict(GOLD_FULL_TERM, annual_base_cents=140000)
    )
    technician = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
    )
    visit = schedule_visit(
        api,
        contract["id"],
        unit["id"],
        "2026-08-25T08:00:00Z",
        "2026-08-25T09:30:00Z",
        technician["id"],
    )
    return {
        "club_id": club["id"],
        "contract_id": contract["id"],
        "equipment_id": unit["id"],
        "technician_id": technician["id"],
        "visit_id": visit["id"],
        "assignment_id": assignment_for_visit(api, visit["id"])["id"],
    }


def _issue_quote(api, contract_id):
    """Issue one renewal quote against the contract's live version token."""
    return get_success_data(
        api.create_renewal_quote(
            contract_id,
            renewal_quote_payload(contract_version(api, contract_id)),
            CONTRACT_ADMIN,
        ),
        201,
    )


def test_requoting_supersedes_the_standing_quote_without_moving_the_contract(api):
    """
    The second quote leaves the contract exactly where the first put it — RENEWAL_QUOTED
    both times, one version higher — and retires the first quote to SUPERSEDED.

    PRD 3.9: "Any quote already `ISSUED` on the same contract moves to `SUPERSEDED`, its
    numbers frozen for audit — this legitimate re-quote is the reason the endpoint is
    guarded by the version token of §2.8 rather than by a state precondition, since
    `RENEWAL_QUOTED` → `RENEWAL_QUOTED` is a permitted cycle."

    Design: Difficulty/non_linear_state_machine/contract_requote_self_cycle_then_decline_fork_tears_down_schedule
    """
    world = _scheduled_forward_visit_world(api)

    version_before_first = contract_version(api, world["contract_id"])
    first_quote = _issue_quote(api, world["contract_id"])
    assert first_quote["status"] == "ISSUED", first_quote["status"]

    after_first = read_contract(api, world["contract_id"])
    assert after_first["status"] == "RENEWAL_QUOTED", after_first["status"]
    assert after_first["version"] == version_before_first + 1, after_first["version"]

    # The self-cycle: a second quote issued from RENEWAL_QUOTED, guarded only by the
    # version token the first quote left behind.
    second_quote = _issue_quote(api, world["contract_id"])
    assert second_quote["status"] == "ISSUED", second_quote["status"]
    assert second_quote["id"] != first_quote["id"]

    assert read_quote(api, first_quote["id"])["status"] == "SUPERSEDED", (
        read_quote(api, first_quote["id"])["status"]
    )

    after_second = read_contract(api, world["contract_id"])
    # The state did not move; only the version did.
    assert after_second["status"] == "RENEWAL_QUOTED", after_second["status"]
    assert after_second["version"] == after_first["version"] + 1, (
        after_second["version"]
    )


def test_declining_the_quote_expires_the_contract_and_tears_down_the_schedule(api):
    """
    Declining the standing quote forks the contract to EXPIRED and, unlike acceptance,
    cancels the forward visit, releases its reservation and returns the 90 minutes.

    PRD 3.9: "Decline sets the quote's `status` to `DECLINED`, records `decline_reason`
    from the supplied `reason`, moves the contract to `EXPIRED`, and advances `version` —
    and then tears the forward schedule down: every `PreventiveVisit` on the contract
    still in `visit_status` `SCHEDULED` moves to `CANCELLED` with `cancellation_reason`
    `CONTRACT_EXPIRED`, each such visit's `RESERVED` `TechnicianAssignment` moves to
    `RELEASED`, and every affected technician's `committed_minutes` falls by that
    assignment's `planned_minutes`."

    Design: Difficulty/non_linear_state_machine/contract_requote_self_cycle_then_decline_fork_tears_down_schedule
    """
    world = _scheduled_forward_visit_world(api)

    _issue_quote(api, world["contract_id"])
    standing_quote = _issue_quote(api, world["contract_id"])

    before = read_technician(api, world["technician_id"])
    # The 09:00-10:30 window was booked, so 90 minutes stand committed.
    assert before["committed_minutes"] == 90, before["committed_minutes"]

    declined = get_success_data(
        api.decline_renewal_quote(
            standing_quote["id"],
            quote_decline_payload(DECLINE_REASON),
            manager_headers(world["club_id"]),
        )
    )
    assert declined["status"] == "DECLINED", declined["status"]
    assert declined["decline_reason"] == DECLINE_REASON, declined["decline_reason"]

    contract = read_contract(api, world["contract_id"])
    assert contract["status"] == "EXPIRED", contract["status"]

    visit = read_visit(api, world["visit_id"])
    assert_fields(
        visit, visit_status="CANCELLED", cancellation_reason="CONTRACT_EXPIRED"
    )

    assert read_assignment(api, world["assignment_id"])["status"] == "RELEASED", (
        read_assignment(api, world["assignment_id"])["status"]
    )

    technician = read_technician(api, world["technician_id"])
    assert technician["committed_minutes"] == 0, technician["committed_minutes"]

    # A cancelled visit enters neither compliance counter, so perfect compliance stands.
    assert contract["pm_visits_completed_count"] == 0, (
        contract["pm_visits_completed_count"]
    )
    assert contract["pm_visits_missed_count"] == 0, contract["pm_visits_missed_count"]
    assert_two_decimals(contract["pm_compliance_pct"], 100.00, "pm_compliance_pct")
