"""Inspection results and the safety cascades: imminent-hazard depth-3 suspension,
overdue-escalation depth-2, open-violation-count conservation, the MAJOR->YELLOW
placard drop, abatement deadlines, terminal-inspection lockdown, and OCC.
"""
from test_helpers import (
    validate_error,
    setup_certificate_suspended_by_imminent, setup_major_violation_with_order,
    create_failed_inspection_with_violations, schedule_inspection,
    record_inspection_result, issue_abatement_order, comply_abatement_order,
    create_property, create_certificate, finding,
    get_certificate, get_property, get_violation, get_abatement_order,
    record_result_payload, abatement_order_payload,
    set_clock, process_overdue_orders,
    api_client,
    TEST_USERS,
)

INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Difficulty/transitive_cascade/imminent_hazard_cascade_depth3 ──────────
def test_imminent_hazard_suspends_certificate(api):
    """PRD §3.7: "its creation triggers cascade C1, which auto-creates an
    `AbatementOrder` in the `ISSUED` state with `is_active` true for that violation,
    and (as the certificate side of the same cascade) suspends the property's
    certificate — setting `occupancy_status` to `SUSPENDED` and `placard_status` to
    `RED`."

    Design: Difficulty/transitive_cascade/imminent_hazard_cascade_depth3
    """
    _prop, cert, _insp, _viol = setup_certificate_suspended_by_imminent(address="7 G St")
    after = get_certificate(cert["id"])
    assert after["occupancy_status"] == "SUSPENDED"
    assert after["placard_status"] == "RED"


def test_imminent_hazard_auto_issues_abatement_order(api):
    """PRD §3.6: "for each violation created, the property's `open_violation_count`
    increments by one." PRD §3.7: "auto-creates an `AbatementOrder` in the `ISSUED`
    state with `is_active` true for that violation"

    Design: Difficulty/transitive_cascade/imminent_hazard_cascade_depth3
    """
    prop, _cert, _insp, viol = setup_certificate_suspended_by_imminent(address="7 G2 St")
    assert get_property(prop["id"])["open_violation_count"] == 1
    body = api.list_abatement_orders(INSPECTOR, params={"violation_id": viol["id"]}).json()
    orders = body["data"]
    assert len(orders) == 1, f"exactly one auto-issued order expected, got {len(orders)}"
    assert orders[0]["status"] == "ISSUED"
    assert orders[0]["is_active"] is True


# ─── Difficulty/transitive_cascade/overdue_escalation_cascade_depth2 ───────
def test_overdue_order_escalates_violation(api):
    """PRD §3.7: "the order moves `ISSUED` to `OVERDUE` and, in the same sweep, on to
    `ESCALATED`; its violation moves from `OPEN` to `ESCALATED` (cascade C2 hop 1)"

    Design: Difficulty/transitive_cascade/overdue_escalation_cascade_depth2
    """
    _prop, _cert, _insp, viol, order = setup_major_violation_with_order(address="8 H St")
    set_clock("2026-05-01T00:00:00Z")
    process_overdue_orders()
    assert get_abatement_order(order["id"])["status"] == "ESCALATED"
    assert get_violation(viol["id"])["status"] == "ESCALATED"


def test_overdue_escalation_suspends_certificate(api):
    """PRD §3.7: "the certificate for that property (reached through the violation's
    inspection's `property_id`) has its `occupancy_status` set to `SUSPENDED` and
    `placard_status` set to `RED` (cascade C2 hop 2)."

    Design: Difficulty/transitive_cascade/overdue_escalation_cascade_depth2
    """
    _prop, cert, _insp, _viol, _order = setup_major_violation_with_order(address="8 H2 St")
    set_clock("2026-05-01T00:00:00Z")
    process_overdue_orders()
    after = get_certificate(cert["id"])
    assert after["placard_status"] == "RED"
    assert after["occupancy_status"] == "SUSPENDED"


# ─── Difficulty/compensating_invariant/open_violation_count_conserved_on_reopen
def _setup_abated_then_failed_reinspection(address):
    prop = create_property(address=address)
    insp, violations = create_failed_inspection_with_violations(
        prop["id"], [finding("IFC_9001", "MAJOR")])
    viol = violations[0]
    order = issue_abatement_order(viol["id"], viol["version"])
    comply_abatement_order(order["id"])  # violation -> ABATED, count -> 0
    reinsp = schedule_inspection(prop["id"], inspection_type="RE_INSPECTION",
                                 scheduled_date="2026-03-25T00:00:00Z")
    api_client.record_result(reinsp["id"], record_result_payload("FAILED"), INSPECTOR)
    return prop, viol


def test_failed_reinspection_reopens_abated_violation(api):
    """PRD §3.6: "If a `RE_INSPECTION` fails, every violation on the property currently
    in `ABATED` reopens to `OPEN`, and the property's `open_violation_count` increments
    by one for each reopened violation."

    Design: Difficulty/compensating_invariant/open_violation_count_conserved_on_reopen
    """
    _prop, viol = _setup_abated_then_failed_reinspection("19 S St")
    assert get_violation(viol["id"])["status"] == "OPEN"


def test_open_violation_count_restored_after_comply_then_reopen(api):
    """PRD §3.7: "the property's `open_violation_count` decrements by one." PRD §3.6:
    "the property's `open_violation_count` increments by one for each reopened violation."

    Design: Difficulty/compensating_invariant/open_violation_count_conserved_on_reopen
    """
    prop, _viol = _setup_abated_then_failed_reinspection("19 S2 St")
    assert get_property(prop["id"])["open_violation_count"] == 1, \
        "comply (-1) then failed re-inspection (+1) must return open_violation_count to 1"


# ─── Corner/cross_cutting_complexity_layers/corner_failed_inspection_major_sets_placard_yellow
def test_failed_inspection_major_only_sets_placard_yellow(api):
    """PRD §3.6: "if the failed inspection produced or reopened no `IMMINENT_HAZARD`
    violation and a certificate exists for the property, that certificate's
    `placard_status` is set to `YELLOW`."
    PRD §3.8: "The compliance axis is driven to `SUSPENDED` (and the placard to `RED`)
    by the safety cascades — either the auto-issue of an `IMMINENT_HAZARD` abatement
    order (cascade C1) or the escalation of a violation (cascade C2)."

    Design: Corner/cross_cutting_complexity_layers/corner_failed_inspection_major_sets_placard_yellow
    """
    prop = create_property(address="38 LL St")
    cert = create_certificate(prop["id"])
    create_failed_inspection_with_violations(prop["id"], [finding("IFC_9001", "MAJOR")])
    after = get_certificate(cert["id"])
    assert after["placard_status"] == "YELLOW"
    assert after["occupancy_status"] == "VALID"
    assert get_property(prop["id"])["open_violation_count"] == 1


# ─── Corner/calculations/corner_abatement_deadline_major_30_days ───────────
def test_abatement_deadline_major_is_thirty_days(api):
    """PRD §3.7: "Every order's `deadline` is its `issued_at` plus a grace period keyed
    to the parent violation's `severity`: 3 days for `IMMINENT_HAZARD`, 30 days for
    `MAJOR`, and 90 days for `MINOR`."

    Design: Corner/calculations/corner_abatement_deadline_major_30_days
    """
    prop = create_property(address="27 AA St")
    insp, violations = create_failed_inspection_with_violations(
        prop["id"], [finding("IFC_9001", "MAJOR")], scheduled_date="2026-03-02T00:00:00Z")
    viol = violations[0]
    order = issue_abatement_order(viol["id"], viol["version"])
    # Logical clock at its startup default 2026-03-01; issued_at + 30 days = 2026-03-31.
    assert order["deadline"].startswith("2026-03-31"), \
        f"MAJOR deadline expected 2026-03-31, got {order['deadline']}"
    assert order["status"] == "ISSUED"


# ─── Corner/state_machines/corner_record_result_on_passed_inspection_returns_409
def test_record_result_on_passed_inspection_rejected(api):
    """PRD §3.6: "Recording is legal only while the inspection is `SCHEDULED`."

    Design: Corner/state_machines/corner_record_result_on_passed_inspection_returns_409
    """
    prop = create_property(address="25 Y St")
    insp = schedule_inspection(prop["id"])
    record_inspection_result(insp["id"], "PASSED")
    res = api.record_result(insp["id"], record_result_payload("PASSED"), INSPECTOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner/cross_cutting_complexity_layers/corner_abatement_order_stale_version_returns_412
def test_second_abatement_order_with_stale_version_rejected(api):
    """PRD §2.8: "The server compares `expected_violation_version` against the
    violation's current `version`. If they do not match — meaning another writer has
    advanced the violation since the client read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)." PRD §2.8: "A successful issuance increments the
    violation's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/corner_abatement_order_stale_version_returns_412
    """
    prop = create_property(address="37 KK St")
    _insp, violations = create_failed_inspection_with_violations(
        prop["id"], [finding("IFC_9001", "MAJOR")])
    viol = violations[0]
    stale_version = viol["version"]
    issue_abatement_order(viol["id"], stale_version)  # advances violation.version
    res = api.create_abatement_order(
        viol["id"], abatement_order_payload(stale_version), INSPECTOR)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
