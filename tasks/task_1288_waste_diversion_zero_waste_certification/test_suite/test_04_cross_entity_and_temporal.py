"""Cross-entity state dependencies, validation priority pairs, and temporal
overlap semantics (PRD §2.8, §3.2, §3.6, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_period_scenario, setup_closed_period_with_rate,
    create_site, create_vendor, create_contract, create_active_contract,
    create_period, create_goal, create_ticket, validate_ticket, reject_ticket,
    set_clock, create_application_payload,
    ApiErrorId, TEST_USERS, make_vendor_user_headers, make_manager_headers,
)

OFFICER = TEST_USERS["officer_headers"]
MGR = TEST_USERS["manager_headers"]
STEWARD = TEST_USERS["steward_headers"]


# ============================================================ priority_pair_validation_conflict

def test_validate_rejected_future_ticket_state_error_wins(api):
    """PRD §2.8: "Every request passes through an ordered pipeline of
    validation layers, and a failure in an earlier layer surfaces before any
    later check is evaluated."
    PRD §2.8 layer 6: "Target-state legality — the target resource's own state
    must permit the requested transition, with state-specific rejections such
    as ERR_TICKET_NOT_PENDING ..."
    PRD §2.8 layer 10: "Window validity and clock — ... future-dated tickets
    (ERR_TICKET_DATE_FUTURE, HTTP 422) ..."

    Design: Difficulty/priority_pair_validation_conflict/validate_rejected_future_ticket_state_wins
    """
    site, vendor, contract, period = setup_open_period_scenario("Site PC")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, ticket_date="2026-08-20",
                       external_ticket_ref="PC-T1")
    reject_ticket(t1["id"], "scale calibration overdue")
    # Both the state precondition (not PENDING) and the temporal precondition
    # (future-dated) fail; the state layer is earlier, so its error surfaces.
    err = validate_error(api.validate_ticket(t1["id"], STEWARD),
                         ApiErrorId.ERR_TICKET_NOT_PENDING)
    t = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t["validation_status"] == "REJECTED"


def test_future_dated_ticket_alone_yields_date_future(api):
    """PRD §3.3: "the ticket_date must not be later than the logical clock date
    (ERR_TICKET_DATE_FUTURE, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/validate_rejected_future_ticket_state_wins
    """
    site, vendor, contract, period = setup_open_period_scenario("Site PC2")
    t1 = create_ticket(site["id"], vendor["id"], contract["id"],
                       disposal_route="RECYCLING", gross_weight_lbs=3000,
                       tare_weight_lbs=1000, ticket_date="2026-08-20",
                       external_ticket_ref="PC2-T1")
    validate_error(api.validate_ticket(t1["id"], STEWARD),
                   ApiErrorId.ERR_TICKET_DATE_FUTURE)
    t = get_success_data(api.get_ticket(t1["id"], OFFICER))
    assert t["validation_status"] == "PENDING"


def test_contract_overlap_wins_over_rate_cap(api):
    """PRD §2.8 layer 8: "Uniqueness, overlap, and payload-internal consistency
    — duplicate ticket references, overlapping contract or goal windows ..."
    PRD §2.8 layer 11: "Fiscal and performance gates — the rebate-rate policy
    cap and the certification threshold (ERR_REBATE_RATE_CAP_EXCEEDED and
    ERR_CERTIFICATION_THRESHOLD_NOT_MET, both HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/activate_contract_overlap_wins_over_rate_cap
    """
    site = create_site("Site OV")
    vendor = create_vendor()
    c1 = create_active_contract(site["id"], vendor["id"],
                                material_stream="CARDBOARD",
                                window_start="2026-01-01", window_end="2026-12-31")
    c2 = create_contract(site["id"], vendor["id"], material_stream="CARDBOARD",
                         rebate_per_ton_cents=15000,
                         window_start="2026-06-01", window_end="2027-05-31")
    # Both overlap (layer 8) and over-cap (layer 11) fail; layer 8 surfaces.
    validate_error(api.activate_contract(c2["id"], MGR),
                   ApiErrorId.ERR_CONTRACT_STREAM_OVERLAP)
    c = get_success_data(api.get_contract(c2["id"], OFFICER))
    assert c["status"] == "DRAFT"


def test_rate_cap_fires_when_no_overlap(api):
    """PRD §3.2: "Fourth, the fiscal guard: `rebate_per_ton_cents` must not
    exceed the site's `max_rebate_rate_per_ton_cents` policy cap, or
    activation is rejected with `ERR_REBATE_RATE_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/activate_contract_overlap_wins_over_rate_cap
    """
    site = create_site("Site OV2")
    vendor = create_vendor()
    c = create_contract(site["id"], vendor["id"], material_stream="COMPOST_ORGANICS",
                        rebate_per_ton_cents=15000,
                        window_start="2026-01-01", window_end="2026-12-31")
    validate_error(api.activate_contract(c["id"], MGR),
                   ApiErrorId.ERR_REBATE_RATE_CAP_EXCEEDED)
    assert get_success_data(api.get_contract(c["id"], OFFICER))["status"] == "DRAFT"


# ============================================================ cross_entity_state_dependency

def test_submit_requires_reporting_period_closed(api):
    """PRD §3.8: "Submission moves the application from DRAFT to SUBMITTED
    through four gates, evaluated in order: the application must be DRAFT
    (ERR_APPLICATION_NOT_DRAFT); the site's program_standing must not be
    PROBATION (ERR_STANDING_PROBATION, HTTP 409); the reporting period must
    belong to the same site (ERR_CROSS_SITE_REFERENCE); and that period must
    be CLOSED (ERR_PERIOD_NOT_CLOSED, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_reporting_period_closed
    """
    set_clock()
    site = create_site("Site XD")
    period = create_period(site["id"])
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site["version"]), MGR,
    ))
    validate_error(api.submit_application(app["id"], MGR),
                   ApiErrorId.ERR_PERIOD_NOT_CLOSED)
    a = get_success_data(api.get_application(app["id"], OFFICER))
    assert a["status"] == "DRAFT"


def test_submit_succeeds_once_period_closed(api):
    """PRD §3.8: "and that period must be CLOSED (ERR_PERIOD_NOT_CLOSED,
    HTTP 409). A successful submission records the caller's X-User-ID as
    submitted_by."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_reporting_period_closed
    """
    site, vendor, contract, period = setup_closed_period_with_rate("Site XD2")
    site_now = get_success_data(api.get_site(site["id"], OFFICER))
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site_now["version"]), MGR,
    ))
    submitted = get_success_data(
        api.submit_application(app["id"], make_manager_headers("mgr-9"))
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by"] == "mgr-9"


def test_contract_activate_requires_vendor_active(api):
    """PRD §3.2: "Third, the contracted vendor must be ACTIVE; activating
    against a suspended vendor is rejected with ERR_VENDOR_NOT_ACTIVE
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_vendor_active
    """
    site = create_site("Site XV")
    vendor = create_vendor()
    get_success_data(api.set_vendor_status(vendor["id"], {"to_status": "SUSPENDED"}, OFFICER))
    c = create_contract(site["id"], vendor["id"], material_stream="CARDBOARD")
    validate_error(api.activate_contract(c["id"], MGR), ApiErrorId.ERR_VENDOR_NOT_ACTIVE)
    assert get_success_data(api.get_contract(c["id"], OFFICER))["status"] == "DRAFT"


def test_contract_activate_succeeds_after_vendor_reactivated(api):
    """PRD §3.1: "Setting `to_status` back to `ACTIVE` — permitted only from
    `SUSPENDED` — returns the vendor's `SUSPENDED` contracts to `ACTIVE`."
    PRD §3.2: "Third, the contracted vendor must be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_vendor_active
    """
    site = create_site("Site XV2")
    vendor = create_vendor()
    get_success_data(api.set_vendor_status(vendor["id"], {"to_status": "SUSPENDED"}, OFFICER))
    c = create_contract(site["id"], vendor["id"], material_stream="CARDBOARD")
    validate_error(api.activate_contract(c["id"], MGR), ApiErrorId.ERR_VENDOR_NOT_ACTIVE)
    get_success_data(api.set_vendor_status(vendor["id"], {"to_status": "ACTIVE"}, OFFICER))
    activated = get_success_data(api.activate_contract(c["id"], MGR))
    assert activated["status"] == "ACTIVE"


# ============================================================ resource_temporal_overlap

def test_contract_closed_interval_endpoint_touch_is_overlap(api):
    """PRD §3.2: "Second, no other ACTIVE contract for the same site and
    material_stream may have a window overlapping the candidate's closed
    interval — because both intervals are closed, two windows that merely
    touch at an endpoint do overlap, and the activation fails with
    ERR_CONTRACT_STREAM_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/contract_window_closed_interval_touch
    """
    site = create_site("Site TO")
    vendor = create_vendor()
    create_active_contract(site["id"], vendor["id"],
                           window_start="2026-01-01", window_end="2026-12-31")
    c2 = create_contract(site["id"], vendor["id"], rebate_per_ton_cents=9000,
                         window_start="2026-12-31", window_end="2027-06-30")
    validate_error(api.activate_contract(c2["id"], MGR),
                   ApiErrorId.ERR_CONTRACT_STREAM_OVERLAP)
    assert get_success_data(api.get_contract(c2["id"], OFFICER))["status"] == "DRAFT"


def test_contract_strictly_disjoint_window_activates(api):
    """PRD §3.2: "no other ACTIVE contract for the same site and
    material_stream may have a window overlapping the candidate's closed
    interval."

    Design: Difficulty/resource_temporal_overlap/contract_window_closed_interval_touch
    """
    site = create_site("Site TO2")
    vendor = create_vendor()
    create_active_contract(site["id"], vendor["id"],
                           window_start="2026-01-01", window_end="2026-12-31")
    c3 = create_contract(site["id"], vendor["id"], rebate_per_ton_cents=9000,
                         window_start="2027-01-01", window_end="2027-06-30")
    activated = get_success_data(api.activate_contract(c3["id"], MGR))
    assert activated["status"] == "ACTIVE"


def test_goal_half_open_adjacency_allowed(api):
    """PRD §3.6: "Two ACTIVE goals of the same site and metric may not have
    overlapping windows, rejected with ERR_GOAL_WINDOW_OVERLAP (HTTP 409) —
    but because goal windows are half-open, adjacency is allowed, so one
    goal's window_end may equal another's window_start."

    Design: Difficulty/resource_temporal_overlap/goal_window_half_open_adjacency
    """
    site = create_site("Site GO")
    g1 = create_goal(site["id"], metric="DIVERSION_RATE", target_value=80,
                     window_start="2026-01-01", window_end="2026-07-01")
    g2 = get_success_data(api.create_goal(
        {"site_id": site["id"], "metric": "DIVERSION_RATE", "target_value": 85,
         "window_start": "2026-07-01", "window_end": "2027-01-01"}, MGR,
    ))
    assert g2["status"] == "ACTIVE"


def test_goal_one_day_earlier_overlaps(api):
    """PRD §3.6: "Two ACTIVE goals of the same site and metric may not have
    overlapping windows, rejected with ERR_GOAL_WINDOW_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/goal_window_half_open_adjacency
    """
    site = create_site("Site GO2")
    create_goal(site["id"], metric="DIVERSION_RATE", target_value=80,
                window_start="2026-01-01", window_end="2026-07-01")
    validate_error(api.create_goal(
        {"site_id": site["id"], "metric": "DIVERSION_RATE", "target_value": 90,
         "window_start": "2026-06-30", "window_end": "2026-12-31"}, MGR,
    ), ApiErrorId.ERR_GOAL_WINDOW_OVERLAP)
