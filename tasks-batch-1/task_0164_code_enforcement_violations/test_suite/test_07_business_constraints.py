"""Business constraints: substantiation and demolition eligibility gates, the
exclusive-occupancy single-active-case rule and the hearing-buffer rule, plus the
fiscal / temporal / precondition guards (nothing-to-lien, balance outstanding,
fee-schedule presence, foreclosure ripeness, missing actual cost, reinspection
target, duplicate parcel).
"""
from test_helpers import validate_error, get_success_data, ApiErrorId
from test_helpers import fixtures as F
from test_helpers.test_users import make_registrant_headers


OFFICER = F.OFFICER
CLERK = F.CLERK


# ==========================================================================
# Difficulty: cross_entity_state_dependency / notice_issue_requires_inspection_violation_found
# ==========================================================================
def test_issue_notice_without_violation_found_inspection_rejected(api):
    """PRD §3.4: "the named `source_inspection_id` must point to an inspection on
    this same case whose outcome is `VIOLATION_FOUND`, failing which the issue is
    rejected with `ERR_NO_SUBSTANTIATION`"

    Design: Difficulty/cross_entity_state_dependency/notice_issue_requires_inspection_violation_found
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    _owner, _prop, case = F.setup_owner_property_case()
    insp = get_success_data(
        api.create_inspection({"case_id": case["id"], "kind": "INITIAL"}, OFFICER)
    )
    get_success_data(api.submit_inspection(insp["id"], {"outcome": "NO_VIOLATION"}, OFFICER))

    resp = api.create_notice(
        {"case_id": case["id"], "source_inspection_id": insp["id"], "violation_class": "MAJOR"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_SUBSTANTIATION.value)


def test_issue_notice_with_violation_found_inspection_succeeds(api):
    """PRD §3.4: "the named `source_inspection_id` must point to an inspection on
    this same case whose outcome is `VIOLATION_FOUND`, failing which the issue is
    rejected with `ERR_NO_SUBSTANTIATION`"
    PRD §3.4: "Issuance takes the notice from `DRAFT` straight to `ISSUED` in the
    single call."

    Design: Difficulty/cross_entity_state_dependency/notice_issue_requires_inspection_violation_found
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    _owner, _prop, case, insp = F.setup_case_with_substantiation()
    # The substantiating inspection has outcome VIOLATION_FOUND, so issuance succeeds.
    notice = get_success_data(
        api.create_notice(
            {"case_id": case["id"], "source_inspection_id": insp["id"], "violation_class": "MAJOR"},
            OFFICER,
        )
    )
    assert notice["status"] == "ISSUED", f"expected ISSUED, got {notice['status']}"


# ==========================================================================
# Difficulty: cross_entity_state_dependency / demolition_requires_property_vacant
# ==========================================================================
def test_demolition_on_occupied_property_rejected(api):
    """PRD §3.11: "ordering a `DEMOLITION` requires that the property's `occupancy`
    be `VACANT` and that the case carry a `HAZARD`-class notice in either `OVERDUE`
    or `UPHELD` status; otherwise the order is rejected with
    `ERR_DEMOLITION_NOT_PERMITTED`."

    Design: Difficulty/cross_entity_state_dependency/demolition_requires_property_vacant
    """
    # OCCUPIED property with a HAZARD notice driven OVERDUE; demolition blocked by occupancy.
    ctx = F.setup_issued_notice("HAZARD", occupancy="OCCUPIED", clock="2026-01-01T00:00:00Z")
    F.set_clock("2026-01-20T00:00:00Z")  # HAZARD cure 7 -> deadline 2026-01-08 -> OVERDUE
    resp = api.create_abatement_order(
        {"case_id": ctx["case"]["id"], "action_kind": "DEMOLITION", "estimated_cost_cents": 500000},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_DEMOLITION_NOT_PERMITTED.value)


def test_demolition_on_vacant_property_with_overdue_hazard_permitted(api):
    """PRD §3.11: "ordering a `DEMOLITION` requires that the property's `occupancy`
    be `VACANT` and that the case carry a `HAZARD`-class notice in either `OVERDUE`
    or `UPHELD` status; otherwise the order is rejected with
    `ERR_DEMOLITION_NOT_PERMITTED`."

    Design: Difficulty/cross_entity_state_dependency/demolition_requires_property_vacant
    """
    # VACANT property + HAZARD notice driven OVERDUE: both demolition conditions hold.
    ctx = F.setup_issued_notice("HAZARD", occupancy="VACANT", clock="2026-01-01T00:00:00Z")
    F.set_clock("2026-01-20T00:00:00Z")  # past the HAZARD deadline (cure 7) -> OVERDUE
    order = get_success_data(
        api.create_abatement_order(
            {
                "case_id": ctx["case"]["id"],
                "action_kind": "DEMOLITION",
                "estimated_cost_cents": 500000,
            },
            OFFICER,
        )
    )
    assert order["status"] == "ORDERED", f"expected ORDERED, got {order['status']}"
    assert order["action_kind"] == "DEMOLITION", "expected DEMOLITION order"


# ==========================================================================
# Difficulty: resource_temporal_overlap / property_exclusive_open_case_overlap
# ==========================================================================
def test_second_case_on_property_with_open_case_rejected(api):
    """PRD §3.2: "Opening a case on a property that already has a case whose posture
    is anything other than `CLOSED` is rejected with `ERR_PROPERTY_HAS_OPEN_CASE`."

    Design: Difficulty/resource_temporal_overlap/property_exclusive_open_case_overlap
    """
    # First case made ACTIVE by issuing a MAJOR notice.
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    prop_id = ctx["prop"]["id"]
    resp = api.create_case({"property_id": prop_id}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_HAS_OPEN_CASE.value)


def test_back_to_back_case_after_close_is_permitted(api):
    """PRD §3.2: "Because the closing instant frees the parcel, a new case opened at
    or after the prior case's close is permitted — back-to-back cases are fine — but
    two open intervals may never overlap."

    Design: Difficulty/resource_temporal_overlap/property_exclusive_open_case_overlap
    """
    F.set_clock("2026-01-01T00:00:00Z")
    owner = F.create_owner()
    prop = F.create_property(owner["id"])
    # First case opened then closed (no notices -> benign, balance 0 -> closeable).
    case1 = F.create_case(prop["id"])
    closed = get_success_data(api.close_case(case1["id"], CLERK))
    assert closed["posture"] == "CLOSED", f"setup expected CLOSED, got {closed['posture']}"
    # A second case on the now-freed parcel is permitted.
    case2 = get_success_data(api.create_case({"property_id": prop["id"]}, OFFICER))
    assert case2["posture"] == "INTAKE", f"expected INTAKE, got {case2['posture']}"
    assert case2["id"] != case1["id"], "second case should be a distinct record"


# ==========================================================================
# Difficulty: resource_temporal_overlap / hearing_buffer_window_overlap
# ==========================================================================
def test_second_contest_within_hearing_buffer_rejected(api):
    """PRD §3.8: "the chosen `scheduled_for` must be at least seven whole days away —
    in either direction — from the `scheduled_for` of any other hearing on the same
    case that is currently `SCHEDULED` or `CONTINUED`. Adjacency within seven whole
    days is forbidden; a violation is rejected with `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hearing_buffer_window_overlap
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner, _prop, case = F.setup_owner_property_case()

    insp1 = F.add_violation_found_inspection(case["id"])
    notice1 = F.issue_notice(case["id"], insp1["id"], "MAJOR")
    F.contest_notice(notice1["id"], owner["id"], "2026-01-10T00:00:00Z")

    insp2 = F.add_violation_found_inspection(case["id"])
    notice2 = F.issue_notice(case["id"], insp2["id"], "MAJOR")
    headers = make_registrant_headers(owner["id"])
    # 2026-01-13 is only 3 days from the first hearing's 2026-01-10 slot (< 7-day buffer).
    resp = api.contest_notice(notice2["id"], {"scheduled_for": "2026-01-13T00:00:00Z"}, headers)
    validate_error(resp, ApiErrorId.ERR_HEARING_SLOT_CONFLICT.value)


def test_second_contest_outside_hearing_buffer_permitted(api):
    """PRD §3.8: "the chosen `scheduled_for` must be at least seven whole days away —
    in either direction — from the `scheduled_for` of any other hearing on the same
    case that is currently `SCHEDULED` or `CONTINUED`."

    Design: Difficulty/resource_temporal_overlap/hearing_buffer_window_overlap
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner, _prop, case = F.setup_owner_property_case()

    insp1 = F.add_violation_found_inspection(case["id"])
    notice1 = F.issue_notice(case["id"], insp1["id"], "MAJOR")
    F.contest_notice(notice1["id"], owner["id"], "2026-01-10T00:00:00Z")

    insp2 = F.add_violation_found_inspection(case["id"])
    notice2 = F.issue_notice(case["id"], insp2["id"], "MAJOR")
    headers = make_registrant_headers(owner["id"])
    # 2026-01-20 is 10 days from 2026-01-10 — outside the 7-day buffer — so it is allowed.
    hearing2 = get_success_data(
        api.contest_notice(notice2["id"], {"scheduled_for": "2026-01-20T00:00:00Z"}, headers)
    )
    assert hearing2["status"] == "SCHEDULED", f"expected SCHEDULED, got {hearing2['status']}"


# ==========================================================================
# Corner: validations / nothing_to_lien_on_zero_balance_case
# ==========================================================================
def test_lien_on_zero_balance_case_returns_nothing_to_lien(api):
    """PRD §3.12: "the case's `outstanding_balance_cents` must be greater than zero,
    or the record is rejected with `ERR_NOTHING_TO_LIEN`"

    Design: Corner/validations/nothing_to_lien_on_zero_balance_case
    """
    F.set_clock("2026-01-01T00:00:00Z")
    _owner, _prop, case = F.setup_owner_property_case()
    version = F.case_version(case["id"])
    resp = api.create_lien({"case_id": case["id"], "expected_case_version": version}, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_LIEN.value)


# ==========================================================================
# Corner: validations / close_case_with_outstanding_balance_returns_error
# ==========================================================================
def test_close_case_with_outstanding_balance_rejected(api):
    """PRD §3.2: "every `ViolationNotice` on the case must be in a benign terminal
    state — `COMPLIED`, `DISMISSED`, or `SETTLED` — and the case's
    `outstanding_balance_cents` must be exactly zero ... If the balance is still
    nonzero, the close is rejected with `ERR_BALANCE_OUTSTANDING`."

    Design: Corner/validations/close_case_with_outstanding_balance_returns_error
    """
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    resp = api.close_case(ctx["case"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)


# ==========================================================================
# Corner: validations / fee_schedule_missing_blocks_notice_issue
# ==========================================================================
def test_issue_notice_without_fee_schedule_rejected(api):
    """PRD §3.4: "a `FeeSchedule` row must exist for the notice's `violation_class`,
    failing which it is rejected with `ERR_FEE_SCHEDULE_MISSING`."

    Design: Corner/validations/fee_schedule_missing_blocks_notice_issue
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")  # only MAJOR seeded; HAZARD intentionally absent
    _owner, _prop, case, insp = F.setup_case_with_substantiation(occupancy="VACANT")
    resp = api.create_notice(
        {"case_id": case["id"], "source_inspection_id": insp["id"], "violation_class": "HAZARD"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_FEE_SCHEDULE_MISSING.value)


# ==========================================================================
# Corner: state_machines / foreclose_before_wait_period_returns_not_ripe
# ==========================================================================
def test_foreclose_before_wait_period_not_ripe(api):
    """PRD §3.12: "a `RECORDED` lien may be foreclosed by a finance clerk, but only
    once the current clock is at or after ninety days from the lien's `created_at`;
    foreclosing earlier is rejected with `ERR_FORECLOSURE_NOT_RIPE`."

    Design: Corner/state_machines/foreclose_before_wait_period_returns_not_ripe
    """
    ctx = F.setup_recorded_lien(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    F.set_clock("2026-02-01T00:00:00Z")  # only 7 days from the 2026-01-25 recording
    resp = api.foreclose_lien(ctx["lien"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_FORECLOSURE_NOT_RIPE.value)


# ==========================================================================
# Corner: state_machines / complete_abatement_without_actual_cost_returns_error
# ==========================================================================
def test_complete_abatement_without_actual_cost_rejected(api):
    """PRD §3.11: "From `IN_PROGRESS`, the officer completes the order, but only when
    the body supplies `actual_cost_cents` — completing without it is rejected with
    `ERR_MISSING_ACTUAL_COST`."

    Design: Corner/state_machines/complete_abatement_without_actual_cost_returns_error
    """
    ctx = F.setup_issued_notice("MAJOR", occupancy="VACANT", clock="2026-01-01T00:00:00Z")
    order = F.order_abatement(ctx["case"]["id"], "BOARD_UP", estimated_cost_cents=30000)
    get_success_data(api.start_abatement_order(order["id"], OFFICER))
    resp = api.complete_abatement_order(order["id"], {}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_MISSING_ACTUAL_COST.value)


# ==========================================================================
# Corner: state_machines / reinspection_notice_id_invalid_on_inspection
# ==========================================================================
def test_reinspection_without_notice_id_rejected(api):
    """PRD §3.3: "A re-inspection-kind inspection is only valid when its `notice_id`
    references a notice on the same case that is currently `ISSUED` or `OVERDUE`;
    otherwise the schedule is rejected with `ERR_REINSPECTION_TARGET_INVALID`."

    Design: Corner/state_machines/reinspection_notice_id_invalid_on_inspection
    """
    F.set_clock("2026-01-01T00:00:00Z")
    _owner, _prop, case = F.setup_owner_property_case()
    resp = api.create_inspection({"case_id": case["id"], "kind": "REINSPECTION"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_REINSPECTION_TARGET_INVALID.value)


# ==========================================================================
# Corner: entities / duplicate_parcel_number_returns_conflict
# ==========================================================================
def test_duplicate_parcel_number_rejected(api):
    """PRD §3.1: "The `parcel_number` must be unique among non-`ARCHIVED`
    properties — an attempt to register a parcel number already held by an active
    property is rejected with `ERR_DUPLICATE_PARCEL`."

    Design: Corner/entities/duplicate_parcel_number_returns_conflict
    """
    F.set_clock("2026-01-01T00:00:00Z")
    owner = F.create_owner()
    F.create_property(owner["id"], parcel_number="APN-DUP", occupancy="OCCUPIED")
    resp = api.create_property(
        {
            "owner_id": owner["id"],
            "parcel_number": "APN-DUP",
            "street_address": "4 X St",
            "occupancy": "VACANT",
        },
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARCEL.value)


# ==========================================================================
# Corner: state_machines / triage_already_triaged_complaint_returns_invalid_state
# ==========================================================================
def test_triage_already_triaged_complaint_invalid_state(api):
    """PRD §3.3: "a code officer may triage it — moving it to `TRIAGED`"
    PRD §2.9: "State-machine legality is then checked: a transition requested from a
    state where it is not defined yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/triage_already_triaged_complaint_returns_invalid_state
    """
    F.set_clock("2026-01-01T00:00:00Z")
    _owner, _prop, case = F.setup_owner_property_case()
    comp = get_success_data(
        api.create_complaint(
            {"case_id": case["id"], "reporter_kind": "RESIDENT", "narrative": "weeds"}, OFFICER
        )
    )
    get_success_data(api.triage_complaint(comp["id"], OFFICER))
    resp = api.triage_complaint(comp["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
