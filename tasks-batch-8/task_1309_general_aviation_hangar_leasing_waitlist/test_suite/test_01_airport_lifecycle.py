"""Airport onboarding, suspension cascade, decommissioning, and manager-role gates."""
from test_helpers import (
    ApiErrorId,
    add_hangar,
    add_rate_schedule,
    api_client,
    assert_airport,
    create_airport,
    create_airport_payload,
    create_hangar_payload,
    create_offer_payload,
    extend_offer,
    get_application,
    get_hangar,
    get_offer,
    parse_instant,
    setup_lease,
    setup_offer,
    submit_application,
    validate_error,
    validate_success,
)


def test_airport_creation_applies_active_status_and_default_clock(api, manager_headers):
    """PRD §3.1: "A new airport starts in `ACTIVE` status."
    PRD §2.5: "Before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time."

    Design: Corner/entities/airport_creation_applies_defaults_and_system_fields
    """
    resp = api.create_airport(
        create_airport_payload(
            airport_code="KENT", name="Entity Field", escalation_pct=0.05,
            escalation_policy="ANNIVERSARY_COMPOUND", offer_acceptance_window_hours=48,
            cure_window_days=14, late_fee_grace_days=3,
        ),
        manager_headers,
    )
    airport = validate_success(resp, expected_status=201)
    assert_airport(airport)
    assert airport["status"] == "ACTIVE", f"new airport must start ACTIVE, got {airport['status']}"
    assert airport["airport_code"] == "KENT"
    # created_at is stamped from the logical clock, which reads exactly
    # 2026-08-01T00:00:00Z before any clock-setting call.
    assert parse_instant(airport["created_at"]) == parse_instant("2026-08-01T00:00:00Z"), (
        f"created_at must equal the default logical clock, got {airport['created_at']}"
    )


def test_resume_non_suspended_airport_rejected(api, manager_headers):
    """PRD §3.1: "Resuming requires the airport to be `SUSPENDED` (otherwise `ERR_AIRPORT_NOT_SUSPENDED`, HTTP 409) and returns it to `ACTIVE`."

    Design: Corner/state_machines/resume_non_suspended_airport_rejected
    """
    airport = create_airport(airport_code="KRSM")
    resp = api.resume_airport(airport["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_AIRPORT_NOT_SUSPENDED)
    after = validate_success(api.get_airport(airport["id"], manager_headers))
    assert after["status"] == "ACTIVE", "rejected resume must not change airport status"


def test_offer_on_suspended_airport_rejected(api, manager_headers):
    """PRD §3.1: "More broadly, while an airport is `SUSPENDED`, five operations are rejected with `ERR_AIRPORT_NOT_ACTIVE` (HTTP 409): submitting a waitlist application, extending an offer, accepting an offer, recording a lease payment, and filing an audit finding."

    Design: Corner/validations/offer_on_suspended_airport_rejected
    """
    airport = create_airport(airport_code="KSAU")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    hangar = add_hangar(airport["id"], hangar_code="T-140", size_class="T_HANGAR")
    application = submit_application(airport["id"], applicant_name="Sue Au")
    validate_success(api.suspend_airport(airport["id"], manager_headers))

    resp = api.create_offer(
        create_offer_payload(
            airport_id=airport["id"], hangar_id=hangar["id"], application_id=application["id"]
        ),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AIRPORT_NOT_ACTIVE)
    assert get_application(application["id"])["status"] == "QUEUED"


def test_suspend_cancels_open_offer(api, manager_headers):
    """PRD §3.1: "Suspension cascades: every `OPEN` offer at the airport moves to `CANCELLED`, and while `QUEUED` and `OFFERED` applications remain in place, none of them can receive new offers during the suspension."

    Design: Difficulty/transitive_cascade/airport_suspend_cancels_open_offer_and_frees_hangar
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KSUS"}, size_class="BOX", rate=75000,
                      hangar_code="B-4")
    validate_success(api.suspend_airport(ctx["airport"]["id"], manager_headers))

    airport = validate_success(api.get_airport(ctx["airport"]["id"], manager_headers))
    assert airport["status"] == "SUSPENDED"
    offer = get_offer(ctx["offer"]["id"])
    assert offer["status"] == "CANCELLED", (
        f"OPEN offer must move to CANCELLED on suspension, got {offer['status']}"
    )


def test_suspend_frees_hangar_and_keeps_application_offered(api, manager_headers):
    """PRD §3.1: "Suspension cascades: every `OPEN` offer at the airport moves to `CANCELLED`, and while `QUEUED` and `OFFERED` applications remain in place, none of them can receive new offers during the suspension."
    PRD §3.3: "When the sweep does expire an offer, the application moves to `EXPIRED_OFFER` and the hangar's posture is recomputed, returning to `AVAILABLE` when no other lease or offer holds it."

    Design: Difficulty/transitive_cascade/airport_suspend_cancels_open_offer_and_frees_hangar
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KSU2"}, size_class="BOX", rate=75000,
                      hangar_code="B-5")
    validate_success(api.suspend_airport(ctx["airport"]["id"], manager_headers))

    # With the offer CANCELLED, no lease or OPEN offer holds the hangar, so
    # its derived posture returns to AVAILABLE.
    hangar = get_hangar(ctx["hangar"]["id"])
    assert hangar["posture"] == "AVAILABLE", (
        f"cancelled offer must release the hangar to AVAILABLE, got {hangar['posture']}"
    )
    # OFFERED applications remain in place through the suspension.
    application = get_application(ctx["application"]["id"])
    assert application["status"] == "OFFERED", (
        f"OFFERED application must remain in place, got {application['status']}"
    )


def test_decommission_hangar_with_active_lease_rejected(api, manager_headers):
    """PRD §3.1: "Decommissioning is terminal: it requires that no lease in `ACTIVE`, `DELINQUENT`, `CURE_PERIOD`, or `EVICTION_PENDING` occupies the hangar (`ERR_HANGAR_OCCUPIED`, HTTP 409) and that no `OPEN` offer exists on it (`ERR_OPEN_OFFER_EXISTS`, HTTP 409)."

    Design: Corner/state_machines/decommission_hangar_with_active_lease_rejected
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KDEC"}, rate=90000, hangar_code="T-60")
    resp = api.decommission_hangar(ctx["hangar"]["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_HANGAR_OCCUPIED)
    hangar = get_hangar(ctx["hangar"]["id"])
    assert hangar["status"] == "OPERATIONAL", "rejected decommission must leave hangar OPERATIONAL"


def test_decommission_with_open_offer_and_offer_without_schedule(api, manager_headers):
    """PRD §3.1: "Decommissioning is terminal: it requires that no lease in `ACTIVE`, `DELINQUENT`, `CURE_PERIOD`, or `EVICTION_PENDING` occupies the hangar (`ERR_HANGAR_OCCUPIED`, HTTP 409) and that no `OPEN` offer exists on it (`ERR_OPEN_OFFER_EXISTS`, HTTP 409)."
    PRD §3.1: "If no schedule covers the instant, the operation is rejected with `ERR_NO_ACTIVE_RATE_SCHEDULE` (HTTP 409)."

    Design: Corner/errors/error_open_offer_exists_and_no_active_rate_schedule
    """
    airport = create_airport(airport_code="KERR")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    hangar1 = add_hangar(airport["id"], hangar_code="T-300", size_class="T_HANGAR")
    hangar2 = add_hangar(airport["id"], hangar_code="E-300", size_class="EXECUTIVE",
                         door_type="HYDRAULIC")
    app1 = submit_application(airport["id"], applicant_name="Er One",
                              size_class_requested="T_HANGAR")
    app2 = submit_application(airport["id"], applicant_name="Er Two",
                              size_class_requested="EXECUTIVE")
    extend_offer(airport["id"], hangar1["id"], app1["id"])

    resp = api.decommission_hangar(hangar1["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_OFFER_EXISTS)

    # EXECUTIVE has no covering rate schedule at this airport.
    resp = api.create_offer(
        create_offer_payload(airport_id=airport["id"], hangar_id=hangar2["id"],
                             application_id=app2["id"]),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_SCHEDULE)
    assert get_hangar(hangar1["id"])["status"] == "OPERATIONAL"


def test_applicant_cannot_create_hangar_or_offer(api, manager_headers, applicant_headers):
    """PRD §2.1: "Once the headers are accepted, the named role must be permitted on the target endpoint per the authorization table in §4; otherwise the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_create_hangar_or_offer
    """
    airport = create_airport(airport_code="KRBC")
    application = submit_application(airport["id"], applicant_name="Rob Backs")

    resp = api.create_hangar(
        create_hangar_payload(airport_id=airport["id"], hangar_code="T-200",
                              size_class="T_HANGAR", door_type="SLIDING"),
        applicant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    # Role authorization (second pipeline stage) precedes path-resource
    # existence, so a nonexistent hangar id still yields 403 for this role.
    resp = api.create_offer(
        create_offer_payload(airport_id=airport["id"],
                             hangar_id="8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                             application_id=application["id"]),
        applicant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
