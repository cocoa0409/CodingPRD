"""Transitive safety cascades (inspection FAIL-critical and accident
investigation) and the closed-interval out-of-service overlap rule."""
import test_helpers as th
from test_helpers import ApiErrorId


# --------------------------------------------------------------------------
# Difficulty: transitive_cascade / inspection_fail_critical_cascade_depth3
# --------------------------------------------------------------------------
def test_fail_critical_cascade_out_of_service_and_suspends_certificate(api):
    """PRD §3.5: "A failing inspection additionally triggers a safety cascade: for
    each CRITICAL deficiency it created, the system auto-issues a citation against
    that deficiency (moving the deficiency from OPEN to CITED), and that citation in
    turn auto-creates an ACTIVE out-of-service order with reason CRITICAL_DEFICIENCY
    ... that order then drives the device to OUT_OF_SERVICE and suspends its active
    certificate exactly as described in §2.8."

    Design: Difficulty/transitive_cascade/inspection_fail_critical_cascade_depth3
    """
    ctx = th.setup_posted_certificate(api, category="PASSENGER_ELEVATOR")
    ins2 = th.inspection_in_progress(api, ctx["device"]["id"], ctx["inspector"]["id"],
                                     itype="PERIODIC", start=5, end=6)
    resp = api.complete_inspection(
        ins2["id"], th.complete_payload("FAIL", [th.deficiency_entry("CR-2", "CRITICAL", "cable fray")]),
        th.make_licensed_inspector_headers(ctx["inspector"]["id"]))
    failed = th.validate_success(resp)
    assert failed["status"] == "FAILED"
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["status"] == "OUT_OF_SERVICE"
    cert = th.validate_success(api.get_certificate(ctx["certificate"]["id"], th.REG))
    assert cert["status"] == "SUSPENDED"


def test_fail_critical_cascade_creates_citation_and_order(api):
    """PRD §3.5: "the system auto-issues a citation against that deficiency ... and
    that citation in turn auto-creates an ACTIVE out-of-service order with reason
    CRITICAL_DEFICIENCY".

    Design: Difficulty/transitive_cascade/inspection_fail_critical_cascade_depth3
    """
    ctx = th.setup_posted_certificate(api, category="PASSENGER_ELEVATOR")
    ins2 = th.inspection_in_progress(api, ctx["device"]["id"], ctx["inspector"]["id"],
                                     itype="PERIODIC", start=5, end=6)
    th.complete_inspection(api, ins2["id"], ctx["inspector"]["id"], "FAIL",
                           [th.deficiency_entry("CR-2", "CRITICAL", "cable fray")])
    citations = th.validate_success(api.list_citations(th.REG, params={"device_id": ctx["device"]["id"]}))
    issued = [c for c in citations if c["status"] == "ISSUED"]
    assert len(issued) == 1, "exactly one auto-issued citation for the CRITICAL deficiency"
    orders = th.validate_success(api.list_oos_orders(th.REG, params={"device_id": ctx["device"]["id"]}))
    active = [o for o in orders if o["status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["reason"] == "CRITICAL_DEFICIENCY"


# --------------------------------------------------------------------------
# Difficulty: transitive_cascade / accident_investigation_cascade_depth2
# --------------------------------------------------------------------------
def test_open_investigation_cascade_out_of_service_and_suspends(api):
    """PRD §3.9: "On success the lead_investigator_id is set and a safety cascade
    fires: an ACTIVE out-of-service order with reason ACCIDENT is auto-created ...
    which then drives the device to OUT_OF_SERVICE and suspends its active
    certificate."

    Design: Difficulty/transitive_cascade/accident_investigation_cascade_depth2
    """
    ctx = th.setup_posted_certificate(api, category="PASSENGER_ELEVATOR")
    lead = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    report = th.file_accident_report(api, ctx["device"]["id"], severity="SEVERE", occurred_period=3)
    opened = th.open_investigation(api, report["id"], lead["id"])
    assert opened["status"] == "UNDER_INVESTIGATION"
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["status"] == "OUT_OF_SERVICE"
    cert = th.validate_success(api.get_certificate(ctx["certificate"]["id"], th.REG))
    assert cert["status"] == "SUSPENDED"


def test_open_investigation_creates_accident_reason_order(api):
    """PRD §3.9: "an ACTIVE out-of-service order with reason ACCIDENT is
    auto-created, with effective_start_period at the current period and
    effective_end_period at the current period plus the device-category interval".

    Design: Difficulty/transitive_cascade/accident_investigation_cascade_depth2
    """
    ctx = th.setup_posted_certificate(api, category="PASSENGER_ELEVATOR")
    lead = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    report = th.file_accident_report(api, ctx["device"]["id"], severity="SEVERE", occurred_period=3)
    th.open_investigation(api, report["id"], lead["id"])
    orders = th.validate_success(api.list_oos_orders(th.REG, params={"device_id": ctx["device"]["id"]}))
    active = [o for o in orders if o["status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["reason"] == "ACCIDENT"


# --------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / oos_order_closed_interval_touch
# --------------------------------------------------------------------------
def test_oos_orders_touching_at_endpoint_overlap(api):
    """PRD §3.8: "the occupation window as an effective_start_period and
    effective_end_period (a closed interval, both endpoints inclusive) ... The new
    window must not overlap, on that closed interval, any order already ACTIVE on
    the same device; an overlap is rejected with ERR_OOS_ORDER_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/oos_order_closed_interval_touch
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    th.create_oos_order(api, ctx["device"]["id"], reason="NONPAYMENT", start=10, end=20)
    resp = api.create_oos_order(
        th.create_oos_order_payload(ctx["device"]["id"], reason="ACCIDENT",
                                    effective_start_period=20, effective_end_period=25), th.SAFETY)
    th.validate_error(resp, ApiErrorId.ERR_OOS_ORDER_OVERLAP.value)


def test_oos_orders_disjoint_by_one_period_allowed(api):
    """PRD §3.8: "The new window must not overlap, on that closed interval, any
    order already ACTIVE on the same device" — a window starting one period past the
    existing close (21 vs 20) shares no point and is accepted.

    Design: Difficulty/resource_temporal_overlap/oos_order_closed_interval_touch
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    th.create_oos_order(api, ctx["device"]["id"], reason="NONPAYMENT", start=10, end=20)
    resp = api.create_oos_order(
        th.create_oos_order_payload(ctx["device"]["id"], reason="ACCIDENT",
                                    effective_start_period=21, effective_end_period=25), th.SAFETY)
    order = th.validate_success(resp, expected_status=201)
    assert order["status"] == "ACTIVE"
