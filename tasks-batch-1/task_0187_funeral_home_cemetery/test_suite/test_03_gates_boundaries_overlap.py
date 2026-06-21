"""Validation-priority conflicts, numeric/empty-set boundaries, cross-entity
state gating, and resource scheduling overlap.

Covers priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, and resource_temporal_overlap.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_funeral_home, create_gpl_item, create_venue, create_plot,
    create_case, create_disclosed_case, add_line, create_contract,
    setup_arranged_case, post_principal, submit_for_funding,
    current_contract_version, reserve_plot, apply_permit, issue_permit,
    setup_case_interment_ready, schedule_chapel, schedule_graveside,
)

ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]
TRUST = TEST_USERS["trust_officer_headers"]
CLERK = TEST_USERS["cemetery_clerk_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ==========================================================================
# priority_pair_validation_conflict / state_beats_fiscal_on_mark_funded
# ==========================================================================
def test_mark_funded_draft_underfunded_returns_invalid_state(api):
    """PRD §2.9: "Whether the target is in a state from which the requested
    transition is defined is checked sixth, yielding ERR_INVALID_STATE (HTTP 409)
    when it is not."
    PRD §3.6: "The contract must be PENDING_FUNDING, or the request is rejected
    with ERR_INVALID_STATE."

    A DRAFT (not submitted) AT_NEED contract with zero deposits is both
    out-of-state (priority 6) and underfunded (priority 12); the state check wins.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_mark_funded
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "AT_NEED_DIRECT")

    resp = api.mark_funded(contract["id"], {"expected_contract_version": contract["version"]}, TRUST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_contract(contract["id"], TRUST))
    assert after["status"] == "DRAFT"


def test_mark_funded_draft_underfunded_does_not_report_shortfall(api):
    """PRD §2.9: "Optimistic-concurrency staleness is checked fifth ... Whether
    the target is in a state from which the requested transition is defined is
    checked sixth".

    The same DRAFT + underfunded contract must NOT surface ERR_FUNDING_SHORTFALL
    (priority 12) — the earlier state check pre-empts it.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_mark_funded
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "AT_NEED_DIRECT")

    resp = api.mark_funded(contract["id"], {"expected_contract_version": contract["version"]}, TRUST)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_FUNDING_SHORTFALL.value


# ==========================================================================
# priority_pair_validation_conflict / disclosure_safety_beats_referential_on_issue_gfs
# ==========================================================================
def test_issue_gfs_undisclosed_empty_returns_disclosure_required(api):
    """PRD §3.2: "an attempt to add a line or issue the statement before
    disclosure has been acknowledged is rejected with ERR_DISCLOSURE_REQUIRED
    (HTTP 409)."
    PRD §2.9: "where two business rules guard the same endpoint the lower-numbered
    concern is evaluated first: the FTC disclosure gate (seventh) ... empty-set
    guards ... (eleventh)".

    A case at INTAKE (no disclosure) with zero selected lines, issuing GFS, hits
    the disclosure gate (priority 7) before the empty-statement guard (priority 11).

    Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_beats_referential_on_issue_gfs
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")

    resp = api.issue_gfs(case["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_REQUIRED.value)

    after = validate_success(api.get_case(case["id"], ARRANGER))
    assert after["arrangement_status"] == "INTAKE"


def test_issue_gfs_undisclosed_does_not_report_empty_statement(api):
    """PRD §3.3: "issuing with zero selected lines is rejected with
    ERR_EMPTY_STATEMENT (HTTP 409)".
    PRD §2.9: "the FTC disclosure gate (seventh) ... empty-set guards ...
    (eleventh)".

    The undisclosed empty case must NOT surface ERR_EMPTY_STATEMENT — the
    earlier disclosure gate pre-empts it.

    Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_beats_referential_on_issue_gfs
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")

    resp = api.issue_gfs(case["id"], ARRANGER)
    err = validate_error(resp, ApiErrorId.ERR_DISCLOSURE_REQUIRED.value)
    assert err["error_id"] != ApiErrorId.ERR_EMPTY_STATEMENT.value


# ==========================================================================
# boundary_precision_check / funding_sufficiency_exact_equality_passes
# ==========================================================================
def test_mark_funded_exact_equality_passes(api):
    """PRD §3.6: "The contract must be sufficiently funded: funded_amount_cents
    must be at least contract_amount_cents, and a shortfall is rejected with
    ERR_FUNDING_SHORTFALL (HTTP 409)."

    funded_amount 100000 == contract_amount 100000 satisfies ">= contract_amount"
    so the contract becomes FUNDED (boundary uses >=, not >).

    Design: Difficulty/boundary_precision_check/funding_sufficiency_exact_equality_passes
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=100000)
    post_principal(contract["id"], 100000)
    submit_for_funding(contract["id"])
    c_v = current_contract_version(contract["id"])

    funded = validate_success(api.mark_funded(
        contract["id"], {"expected_contract_version": c_v}, TRUST))
    assert funded["funded_amount_cents"] == 100000
    assert funded["contract_amount_cents"] == 100000
    assert funded["status"] == "FUNDED"


def test_mark_funded_one_cent_short_returns_funding_shortfall(api):
    """PRD §3.6: "funded_amount_cents must be at least contract_amount_cents, and
    a shortfall is rejected with ERR_FUNDING_SHORTFALL (HTTP 409)."

    funded_amount 99999 < contract_amount 100000 fails the boundary (X-1 case).

    Design: Difficulty/boundary_precision_check/funding_sufficiency_exact_equality_passes
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=100000)
    post_principal(contract["id"], 99999)
    submit_for_funding(contract["id"])
    c_v = current_contract_version(contract["id"])

    resp = api.mark_funded(contract["id"], {"expected_contract_version": c_v}, TRUST)
    validate_error(resp, ApiErrorId.ERR_FUNDING_SHORTFALL.value)


# ==========================================================================
# boundary_precision_check / issue_gfs_empty_selected_set_rejected
# ==========================================================================
def test_issue_gfs_with_zero_selected_lines_rejected(api):
    """PRD §3.3: "issuing with zero selected lines is rejected with
    ERR_EMPTY_STATEMENT (HTTP 409)".

    A DISCLOSED case with a contract and exactly one PROPOSED (not SELECTED) line
    has zero SELECTED lines — the zero-cardinality edge.

    Design: Difficulty/boundary_precision_check/issue_gfs_empty_selected_set_rejected
    """
    home = create_funeral_home()
    casket = create_gpl_item(home["id"], code="CASKET-A", name="Oak casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             preneed_trustable=True, unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], casket["id"])  # left PROPOSED
    contract = create_contract(case["id"], "AT_NEED_DIRECT")

    resp = api.issue_gfs(case["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_STATEMENT.value)

    after = validate_success(api.get_case(case["id"], ARRANGER))
    assert after["arrangement_status"] == "DISCLOSED"
    assert after["gfs_issued"] is False


def test_issue_gfs_with_one_selected_line_succeeds(api):
    """PRD §3.3: "Issuing the Goods & Services Statement (GFS) ... is allowed
    only when the case is DISCLOSED, disclosure_acknowledged is true, at least one
    SELECTED statement line exists, and a contract already exists for the case."

    Exactly one SELECTED line (X=1) is the passing side of the empty-set boundary.

    Design: Difficulty/boundary_precision_check/issue_gfs_empty_selected_set_rejected
    """
    home = create_funeral_home()
    casket = create_gpl_item(home["id"], code="CASKET-A", name="Oak casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             preneed_trustable=True, unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    line = add_line(case["id"], casket["id"])
    get_success_data(api.select_statement_line(case["id"], line["id"], ARRANGER))
    create_contract(case["id"], "AT_NEED_DIRECT")

    issued = validate_success(api.issue_gfs(case["id"], ARRANGER))
    assert issued["arrangement_status"] == "ARRANGED"
    assert issued["gfs_issued"] is True


# ==========================================================================
# cross_entity_state_dependency / plot_interment_requires_case_interment_ready
# ==========================================================================
def test_inter_blocked_when_case_not_ready(api):
    """PRD §3.8: "Interment ... is allowed only when the plot is RESERVED
    (otherwise ERR_PLOT_NOT_RESERVED) and the interment axis of the case holding
    that plot is READY (otherwise ERR_INTERMENT_NOT_READY, HTTP 409)."

    A RESERVED plot whose case is still NOT_READY (no issued permits) cannot inter.

    Design: Difficulty/cross_entity_state_dependency/plot_interment_requires_case_interment_ready
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-20", current_price_cents=80000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    reserve_plot(plot["id"], case["id"], plot["version"])

    resp = api.inter_plot(plot["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INTERMENT_NOT_READY.value)

    plot_after = validate_success(api.get_plot(plot["id"], CLERK))
    assert plot_after["status"] == "RESERVED"
    case_after = validate_success(api.get_case(case["id"], ARRANGER))
    assert case_after["interment_status"] == "NOT_READY"


def test_inter_succeeds_once_case_ready(api):
    """PRD §3.8: "Interment ... is allowed only when the plot is RESERVED ... and
    the interment axis of the case holding that plot is READY".

    The satisfied side of the Plot->Case dependency: once both permits are issued
    (case READY), interment of the RESERVED plot proceeds.

    Design: Difficulty/cross_entity_state_dependency/plot_interment_requires_case_interment_ready
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-21", current_price_cents=80000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    setup_case_interment_ready(home["id"], case["id"])
    reserve_plot(plot["id"], case["id"], plot["version"])

    interred = validate_success(api.inter_plot(plot["id"], CLERK))
    assert interred["status"] == "INTERRED"


# ==========================================================================
# cross_entity_state_dependency / burial_transit_issue_requires_issued_death_certificate
# ==========================================================================
def test_issue_burial_transit_without_issued_death_cert_rejected(api):
    """PRD §3.7: "A burial-transit permit carries an extra prerequisite: an
    ISSUED DEATH_CERTIFICATE permit must already exist for the same case, and
    attempting to issue a burial-transit permit without one is rejected with
    ERR_DEATH_CERT_REQUIRED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/burial_transit_issue_requires_issued_death_certificate
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    apply_permit(case["id"], "DEATH_CERTIFICATE")  # left APPLIED, not issued
    bt = apply_permit(case["id"], "BURIAL_TRANSIT")

    resp = api.issue_permit(bt["id"], {"reference_number": "BT-9"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_DEATH_CERT_REQUIRED.value)

    bt_after = validate_success(api.get_permit(bt["id"], REGISTRAR))
    assert bt_after["status"] == "APPLIED"


def test_issue_burial_transit_succeeds_after_death_cert_issued(api):
    """PRD §3.7: "A burial-transit permit carries an extra prerequisite: an
    ISSUED DEATH_CERTIFICATE permit must already exist for the same case".

    The satisfied side of the prerequisite: once the DEATH_CERTIFICATE is ISSUED,
    the BURIAL_TRANSIT issuance proceeds.

    Design: Difficulty/cross_entity_state_dependency/burial_transit_issue_requires_issued_death_certificate
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")
    issue_permit(dc["id"], "DC-1")
    bt = apply_permit(case["id"], "BURIAL_TRANSIT")

    bt_issued = validate_success(api.issue_permit(bt["id"], {"reference_number": "BT-9"}, REGISTRAR))
    assert bt_issued["status"] == "ISSUED"


# ==========================================================================
# resource_temporal_overlap / chapel_buffered_half_open_overlap_rejected
# ==========================================================================
def test_chapel_booking_within_buffer_conflicts(api):
    """PRD §3.9: "two chapel bookings on the same venue conflict if their
    intervals overlap once each interval is extended by the home's
    chapel_buffer_minutes of cleanup buffer between consecutive bookings ... A
    conflicting booking is rejected with ERR_SCHEDULE_CONFLICT (HTTP 409)."

    First event 15:00-16:00; a second starting 16:15 is within the 30-min buffer
    after the 16:00 end => conflict.

    Design: Difficulty/resource_temporal_overlap/chapel_buffered_half_open_overlap_rejected
    """
    home = create_funeral_home(chapel_buffer_minutes=30)
    venue = create_venue(home["id"], name="Main Chapel", capacity=120)
    case1 = create_case(home["id"], decedent_name="Case One", case_mode="AT_NEED",
                        date_of_death="2026-06-01T00:00:00.000Z")
    schedule_chapel(case1["id"], venue["id"],
                    "2026-06-10T15:00:00.000Z", "2026-06-10T16:00:00.000Z")
    case2 = create_case(home["id"], decedent_name="Case Two", case_mode="AT_NEED",
                        date_of_death="2026-06-02T00:00:00.000Z")

    resp = api.create_event(case2["id"], {
        "resource_kind": "CHAPEL", "resource_id": venue["id"],
        "starts_at": "2026-06-10T16:15:00.000Z", "ends_at": "2026-06-10T17:00:00.000Z"
    }, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value)


def test_chapel_booking_beyond_buffer_succeeds(api):
    """PRD §3.9: "two chapel bookings on the same venue conflict if their
    intervals overlap once each interval is extended by the home's
    chapel_buffer_minutes of cleanup buffer between consecutive bookings".

    A second booking starting 16:30 — a full 30 minutes after the 16:00 end —
    clears the buffer and succeeds (the non-conflicting side of the boundary).

    Design: Difficulty/resource_temporal_overlap/chapel_buffered_half_open_overlap_rejected
    """
    home = create_funeral_home(chapel_buffer_minutes=30)
    venue = create_venue(home["id"], name="Main Chapel", capacity=120)
    case1 = create_case(home["id"], decedent_name="Case One", case_mode="AT_NEED",
                        date_of_death="2026-06-01T00:00:00.000Z")
    schedule_chapel(case1["id"], venue["id"],
                    "2026-06-10T15:00:00.000Z", "2026-06-10T16:00:00.000Z")
    case2 = create_case(home["id"], decedent_name="Case Two", case_mode="AT_NEED",
                        date_of_death="2026-06-02T00:00:00.000Z")

    ev2 = validate_success(api.create_event(case2["id"], {
        "resource_kind": "CHAPEL", "resource_id": venue["id"],
        "starts_at": "2026-06-10T16:30:00.000Z", "ends_at": "2026-06-10T17:30:00.000Z"
    }, ARRANGER), expected_status=201)
    assert ev2["status"] == "SCHEDULED"


# ==========================================================================
# resource_temporal_overlap / graveside_whole_day_exclusivity_rejected
# ==========================================================================
def test_graveside_same_day_same_plot_conflicts(api):
    """PRD §3.9: "two graveside bookings on the same plot conflict if they fall
    on the same calendar date ... A conflicting booking is rejected with
    ERR_SCHEDULE_CONFLICT (HTTP 409)."

    Two graveside events on plot B-1 on 2026-06-12 at 09:00 and 14:00 collide on
    the calendar date despite different clock times.

    Design: Difficulty/resource_temporal_overlap/graveside_whole_day_exclusivity_rejected
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="B", plot_code="B-1", current_price_cents=90000)
    case1 = create_case(home["id"], decedent_name="Case One", case_mode="AT_NEED",
                        date_of_death="2026-06-01T00:00:00.000Z")
    schedule_graveside(case1["id"], plot["id"], "2026-06-12T09:00:00.000Z")
    case2 = create_case(home["id"], decedent_name="Case Two", case_mode="AT_NEED",
                        date_of_death="2026-06-02T00:00:00.000Z")

    resp = api.create_event(case2["id"], {
        "resource_kind": "GRAVESIDE", "resource_id": plot["id"],
        "starts_at": "2026-06-12T14:00:00.000Z"
    }, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value)


def test_graveside_different_day_same_plot_succeeds(api):
    """PRD §3.9: "A GRAVESIDE event uses only the calendar date of starts_at and
    ignores ends_at, occupying the whole day exclusively."

    A second graveside on the same plot but the next calendar date (2026-06-13)
    does not collide — the non-conflicting side of whole-day exclusivity.

    Design: Difficulty/resource_temporal_overlap/graveside_whole_day_exclusivity_rejected
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="B", plot_code="B-2", current_price_cents=90000)
    case1 = create_case(home["id"], decedent_name="Case One", case_mode="AT_NEED",
                        date_of_death="2026-06-01T00:00:00.000Z")
    schedule_graveside(case1["id"], plot["id"], "2026-06-12T09:00:00.000Z")
    case2 = create_case(home["id"], decedent_name="Case Two", case_mode="AT_NEED",
                        date_of_death="2026-06-02T00:00:00.000Z")

    ev2 = validate_success(api.create_event(case2["id"], {
        "resource_kind": "GRAVESIDE", "resource_id": plot["id"],
        "starts_at": "2026-06-13T14:00:00.000Z"
    }, ARRANGER), expected_status=201)
    assert ev2["status"] == "SCHEDULED"
