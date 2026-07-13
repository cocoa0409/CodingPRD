"""Validation precedence: when two conditions could reject a schedule, the
higher-priority check wins. Each pair is also confirmed by isolating the
lower/priority check so its error fires alone.

Difficulty instances: priority_pair_validation_conflict/{schedule_state_beats_category_referential,
schedule_safety_beats_capacity_fiscal}.
"""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    schedule_payload,
    create_request, add_item, schedule_request, route_version,
    setup_schedulable_request, setup_scheduled_request,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]

S10 = "2026-03-15T10:00:00Z"
E10 = "2026-03-15T10:30:00Z"
S11 = "2026-03-15T11:00:00Z"
E11 = "2026-03-15T11:30:00Z"


# ─── State (priority 6) beats category-referential (priority 11) ──────

def test_state_check_beats_category_on_rescheduled_request():
    """PRD §3.4: "The request must be REQUESTED; otherwise
    ERR_REQUEST_INVALID_STATE."
    PRD §2.10: "6. Transition legality — the target resource is in a state that
    admits the requested transition ... 8. through 16. — the business rules
    specific to the operation, in the order given in the relevant workflow
    subsection."

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_beats_category_referential
    """
    ctx = setup_scheduled_request(partner_categories=["FURNITURE"], capacity_cf=200,
                                  disposition="DONATION",
                                  items=[{"category": "FURNITURE", "volume_cf": 20}],
                                  slot_start=S10, slot_end=E10)
    # Partner stops accepting FURNITURE; the request is already SCHEDULED.
    validate_success(
        api.update_partner(ctx["partner"]["id"], {"accepted_categories": ["HOUSEHOLD"]}, PLATFORM),
        200,
    )
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], route_version(ctx["route"]["id"]),
                         "2026-03-15T12:00:00Z", "2026-03-15T12:30:00Z"),
        DISPATCHER,
    )
    validate_error(res, "ERR_REQUEST_INVALID_STATE", expected_status=409)


def test_category_not_accepted_fires_alone_when_state_is_valid():
    """PRD §3.4: "If the request's disposition is DONATION, every one of its
    items must have a category that is contained in the partner's
    accepted_categories; any item outside that set yields
    ERR_CATEGORY_NOT_ACCEPTED."

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_beats_category_referential
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=200,
                                    disposition="DONATION",
                                    items=[{"category": "ELECTRONICS", "volume_cf": 20}])
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"], S10, E10),
        DISPATCHER,
    )
    validate_error(res, "ERR_CATEGORY_NOT_ACCEPTED", expected_status=422)


# ─── Safety (priority 10) beats capacity-fiscal (priority 15) ─────────

def test_porch_attestation_beats_capacity_when_both_violated():
    """PRD §3.4: "If the request's pickup_mode is UNATTENDED, it must have a
    non-null porch_photo_url and a safety_attestation of true; otherwise
    ERR_PORCH_ATTESTATION_REQUIRED."
    PRD §2.10: "When more than one condition could reject a request, checks are
    evaluated in a fixed priority order so that failures are reported
    deterministically."

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_capacity_fiscal
    """
    ctx = setup_scheduled_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                  disposition="HAUL",
                                  items=[{"category": "FURNITURE", "volume_cf": 80}],
                                  slot_start=S10, slot_end=E10)
    # Unattended HAUL, no porch photo, attestation false, volume that also
    # overflows the truck (80 already reserved + 40 = 120 > 100).
    req_b = create_request(ctx["donor"]["id"], ctx["partner"]["id"],
                           pickup_mode="UNATTENDED", disposition="HAUL")
    add_item(req_b["id"], ctx["donor"]["id"], category="FURNITURE", volume_cf=40)
    res = api.schedule_pickup(
        req_b["id"],
        schedule_payload(ctx["route"]["id"], route_version(ctx["route"]["id"]), S11, E11),
        DISPATCHER,
    )
    validate_error(res, "ERR_PORCH_ATTESTATION_REQUIRED", expected_status=422)


def test_porch_attestation_fires_alone_when_capacity_ok():
    """PRD §3.4: "it must have a non-null `porch_photo_url` and a `safety_attestation` of true; otherwise `ERR_PORCH_ATTESTATION_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_capacity_fiscal
    """
    ctx = setup_schedulable_request(partner_categories=["FURNITURE"], capacity_cf=100,
                                    disposition="HAUL", pickup_mode="UNATTENDED",
                                    items=[{"category": "FURNITURE", "volume_cf": 20}])
    res = api.schedule_pickup(
        ctx["request"]["id"],
        schedule_payload(ctx["route"]["id"], ctx["route_version"], S10, E10),
        DISPATCHER,
    )
    validate_error(res, "ERR_PORCH_ATTESTATION_REQUIRED", expected_status=422)
