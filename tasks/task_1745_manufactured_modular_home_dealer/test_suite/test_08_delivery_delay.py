"""Transport delays, buyer delay notices, set completion, and title records (PRD §2.8, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_evaluation,
    assert_delay_notice,
    assert_instant_equals,
    book_transport,
    canonical_community_scenario,
    confirm_order,
    create_application,
    create_model,
    create_title_record_payload,
    create_unit,
    decide_application,
    fund_application,
    get_success_data,
    issue_title_for_order,
    make_site_evaluator_headers,
    new_order_scenario,
    progress_to_financing_approved,
    schedule_evaluation,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
INSTALLER = TEST_USERS["installer_headers"]


def _booked_canonical_scenario():
    """Canonical community order at FINANCING_APPROVED with a double-wide job
    booked for 2026-08-20 (crew capacity 2)."""
    scn = canonical_community_scenario()
    progress_to_financing_approved(scn)
    book_transport(scn, distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z")
    return scn


# --- delay/reschedule cycle ---------------------------------------------------

def test_delay_creates_notice_and_marks_job_delayed(api, coordinator_headers):
    """PRD §3.6: "A delay moves the job `SCHEDULED` → `DELAYED`, writes the new
    start date onto the job, creates a `DelayNotice` pinned to the job (its
    `transport_job_id` set, its `sales_order_id` null, `original_date` taken from
    the prior start and `new_date` from the new start), stamps the job's
    `buyer_notified_at` when the buyer was notified, and recomputes the owning
    order's `delay_compensation_cents`."
    PRD §3.6: "from the third day the notice earns $75.00 per day (7,500 cents)
    for each day beyond the two grace days, capped at $750.00 (75,000 cents) per
    notice".

    Design: Difficulty/non_linear_state_machine/transport_delay_reschedule_cycle
    """
    scn = _booked_canonical_scenario()
    job = scn["job"]

    delayed = validate_success(
        api.delay_transport_job(
            job["id"],
            {"reason": "WEATHER", "new_scheduled_start_date": "2026-08-27T08:00:00Z", "buyer_notified": True},
            coordinator_headers,
        )
    )
    assert delayed["status"] == "DELAYED"
    assert delayed.get("buyer_notified_at") is not None, "buyer_notified_at stamped when the buyer was notified"

    notices, meta = validate_paginated(api.list_job_delay_notices(job["id"], coordinator_headers))
    assert meta["total_count"] == 1
    notice = notices[0]
    assert_delay_notice(notice)
    assert notice["transport_job_id"] == job["id"] and notice["sales_order_id"] is None
    assert notice["delay_days"] == 7, f"08-20 -> 08-27 is 7 whole days, got {notice['delay_days']}"
    assert notice["compensation_cents"] == 37_500, "(7 - 2) x 7,500 = 37,500"


def test_reschedule_returns_delayed_job_to_scheduled(api, consultant_headers, coordinator_headers):
    """PRD §3.6: "A booked job cycles `SCHEDULED` ↔ `DELAYED` any number of times
    before it runs."
    PRD §3.6: "Rescheduling confirms the new window: the job moves `DELAYED` →
    `SCHEDULED` only if the `new_scheduled_start_date` is not in the past
    (`ERR_SCHEDULE_IN_PAST`) and the crew-window capacity check passes for the
    new window (`ERR_CREW_WINDOW_CONFLICT`)."

    Design: Difficulty/non_linear_state_machine/transport_delay_reschedule_cycle
    """
    scn = _booked_canonical_scenario()
    job = scn["job"]
    validate_success(
        api.delay_transport_job(
            job["id"],
            {"reason": "WEATHER", "new_scheduled_start_date": "2026-08-27T08:00:00Z", "buyer_notified": True},
            coordinator_headers,
        )
    )

    rescheduled = validate_success(
        api.reschedule_transport_job(job["id"], {"new_scheduled_start_date": "2026-08-27T08:00:00Z"}, coordinator_headers)
    )
    assert rescheduled["status"] == "SCHEDULED", "the cycle DELAYED -> SCHEDULED completes"
    assert_instant_equals(rescheduled["scheduled_start_date"], "2026-08-27T08:00:00Z")

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["delay_compensation_cents"] == 37_500, "the notice's compensation aggregates onto the order"


# --- delay compensation chain ---------------------------------------------------

def test_transport_delay_notice_compensation_hop(api, coordinator_headers):
    """PRD §3.6: "The `delay_days` of a notice is the whole number of days from
    `original_date` to `new_date` — the elapsed seconds divided by 86,400,
    rounded down. The first two days are a grace period: fewer than three days of
    delay earns nothing; from the third day the notice earns $75.00 per day
    (7,500 cents) for each day beyond the two grace days, capped at $750.00
    (75,000 cents) per notice".

    Design: Difficulty/transitive_cascade/delay_notice_compensation_chain
    """
    scn = _booked_canonical_scenario()
    validate_success(
        api.delay_transport_job(
            scn["job"]["id"],
            {"reason": "ESCORT_UNAVAILABLE", "new_scheduled_start_date": "2026-08-27T08:00:00Z", "buyer_notified": True},
            coordinator_headers,
        )
    )
    notices, _ = validate_paginated(api.list_job_delay_notices(scn["job"]["id"], coordinator_headers))
    assert len(notices) == 1
    assert notices[0]["delay_days"] == 7
    assert notices[0]["compensation_cents"] == 37_500


def test_order_level_notice_adds_to_same_aggregate(api, consultant_headers, coordinator_headers):
    """PRD §3.6: "The order's `delay_compensation_cents` is the sum of
    `compensation_cents` over every notice linked to the order — both notices
    pinned directly to the order and those pinned to its transport jobs.
    Order-level notices are created by a `SalesConsultant` with a `reason`, an
    `original_date`, a `new_date` (which must be after `original_date`), and a
    `buyer_notified` flag, and likewise recompute the order's compensation."

    Design: Difficulty/transitive_cascade/delay_notice_compensation_chain
    """
    scn = _booked_canonical_scenario()
    validate_success(
        api.delay_transport_job(
            scn["job"]["id"],
            {"reason": "ESCORT_UNAVAILABLE", "new_scheduled_start_date": "2026-08-27T08:00:00Z", "buyer_notified": True},
            coordinator_headers,
        )
    )
    notice2 = validate_success(
        api.create_order_delay_notice(
            scn["order"]["id"],
            {
                "reason": "FACTORY_DELAY",
                "original_date": "2026-08-27T08:00:00Z",
                "new_date": "2026-08-30T08:00:00Z",
                "buyer_notified": True,
            },
            consultant_headers,
        ),
        expected_status=201,
    )
    assert_delay_notice(notice2)
    assert notice2["sales_order_id"] == scn["order"]["id"] and notice2["transport_job_id"] is None
    assert notice2["delay_days"] == 3
    assert notice2["compensation_cents"] == 7_500, "(3 - 2) x 7,500 = 7,500"

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["delay_compensation_cents"] == 45_000, "37,500 (job notice) + 7,500 (order notice)"


def test_delay_compensation_threshold_steps(api, consultant_headers, coordinator_headers):
    """PRD §3.6: "The first two days are a grace period: fewer than three days of
    delay earns nothing; from the third day the notice earns $75.00 per day
    (7,500 cents) for each day beyond the two grace days, capped at $750.00
    (75,000 cents) per notice — so a five-day slip earns three days of per-diem,
    and a twelve-day slip hits the cap."

    Design: Corner/calculations/delay_compensation_threshold_steps
    """
    scn = _booked_canonical_scenario()
    job = scn["job"]

    # Two-day slip: under the threshold, compensates nothing.
    validate_success(
        api.delay_transport_job(
            job["id"],
            {"reason": "WEATHER", "new_scheduled_start_date": "2026-08-22T08:00:00Z", "buyer_notified": False},
            coordinator_headers,
        )
    )
    validate_success(
        api.reschedule_transport_job(job["id"], {"new_scheduled_start_date": "2026-08-22T08:00:00Z"}, coordinator_headers)
    )
    # Three-day slip from the rescheduled base: exactly at the threshold.
    validate_success(
        api.delay_transport_job(
            job["id"],
            {"reason": "PERMIT_HOLD", "new_scheduled_start_date": "2026-08-25T08:00:00Z", "buyer_notified": True},
            coordinator_headers,
        )
    )

    notices, meta = validate_paginated(api.list_job_delay_notices(job["id"], coordinator_headers))
    assert meta["total_count"] == 2
    by_original = {n["original_date"][:10]: n for n in notices}
    assert by_original["2026-08-20"]["compensation_cents"] == 0, "2-day delay is inside the grace period"
    assert by_original["2026-08-22"]["compensation_cents"] == 7_500, "3-day delay earns (3 - 2) x 7,500"

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["delay_compensation_cents"] == 7_500


def test_delay_over_3_days_requires_notification(api, coordinator_headers):
    """PRD §3.6: "Declaring a delay requires a `new_scheduled_start_date`
    strictly after the current `scheduled_start_date` (otherwise
    `ERR_VALIDATION`), a `reason`, and a `buyer_notified` flag; when the slip
    exceeds three whole days, `buyer_notified` must be true or the declaration is
    rejected with `ERR_DELAY_NOTIFICATION_REQUIRED`."

    Design: Corner/validations/delay_over_3_days_requires_notification
    """
    scn = _booked_canonical_scenario()
    job = scn["job"]

    resp = api.delay_transport_job(
        job["id"],
        {"reason": "WEATHER", "new_scheduled_start_date": "2026-08-27T08:00:00Z", "buyer_notified": False},
        coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DELAY_NOTIFICATION_REQUIRED)
    view = get_success_data(api.get_transport_job(job["id"], coordinator_headers))
    assert view["status"] == "SCHEDULED", "a rejected declaration leaves the job scheduled"

    delayed = validate_success(
        api.delay_transport_job(
            job["id"],
            {"reason": "WEATHER", "new_scheduled_start_date": "2026-08-27T08:00:00Z", "buyer_notified": True},
            coordinator_headers,
        )
    )
    assert delayed["status"] == "DELAYED"
    assert delayed.get("buyer_notified_at") is not None


def test_order_level_notice_polymorphic_subject(api, consultant_headers):
    """PRD §3.6: "Every notice, whichever way it is created, has a `reason` of
    `WEATHER`, `PERMIT_HOLD`, `FACTORY_DELAY`, `SITE_NOT_READY`, or
    `ESCORT_UNAVAILABLE`, and must carry exactly one of `transport_job_id` or
    `sales_order_id` — both or neither is rejected with `ERR_VALIDATION`."
    PRD §3.6: "from the third day the notice earns $75.00 per day (7,500 cents)
    for each day beyond the two grace days, capped at $750.00 (75,000 cents) per
    notice".

    Design: Corner/errors/delay_notice_polymorphic_subject
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    notice = validate_success(
        api.create_order_delay_notice(
            scn["order"]["id"],
            {
                "reason": "FACTORY_DELAY",
                "original_date": "2026-08-20T08:00:00Z",
                "new_date": "2026-09-03T08:00:00Z",
                "buyer_notified": True,
            },
            consultant_headers,
        ),
        expected_status=201,
    )
    assert_delay_notice(notice)
    assert notice["sales_order_id"] == scn["order"]["id"] and notice["transport_job_id"] is None
    assert notice["delay_days"] == 14
    # (14 - 2) x 7,500 = 90,000, clamped to the 75,000 cap.
    assert notice["compensation_cents"] == 75_000, f"cap clamps 90,000 to 75,000, got {notice['compensation_cents']}"

    notices, meta = validate_paginated(api.list_order_delay_notices(scn["order"]["id"], consultant_headers))
    assert meta["total_count"] == 1 and notices[0]["id"] == notice["id"]
    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["delay_compensation_cents"] == 75_000


# --- set completion permit gate ----------------------------------------------------

def test_complete_set_permit_missing_rejected(api, installer_headers):
    """PRD §3.6: "Set completion is certified by an `InstallationManager`, not
    the transport coordinator, and only when the order's latest non-`SUPERSEDED`
    evaluation is `APPROVED` and carries a non-null `permit_number` — otherwise
    `ERR_PERMIT_MISSING`."
    PRD §3.4: "Note that `permit_number` is optional at findings time but becomes
    mandatory before set completion (§3.6)."

    Design: Corner/state_machines/complete_set_permit_missing_rejected
    """
    scn = canonical_community_scenario()
    confirm_order(scn, 473_600)
    evaluation = schedule_evaluation(scn)
    # Findings recorded WITHOUT a permit number (optional at findings time).
    validate_success(
        api.record_findings(
            evaluation["id"],
            {
                "foundation_type": "PIERS",
                "utilities_verified": True,
                "findings_result": "PASS",
                "install_estimate_cents": 350_000,
            },
            make_site_evaluator_headers("eval-1"),
        )
    )
    approve_evaluation(scn)
    create_application(scn)
    submit_application(scn)
    decide_application(scn, "APPROVE", 725)
    # PRD §3.6 gates booking on deal_status exactly FINANCING_APPROVED, and
    # §3.5 funding bubbles the order to AWAITING_DELIVERY, so the booking is
    # placed before funding.
    book_transport(scn, distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z")
    issue_title_for_order(scn)
    fund_application(scn)
    set_clock("2026-08-20T10:00:00Z")
    validate_success(api.dispatch_transport_job(scn["job"]["id"], COORDINATOR))
    delivered = validate_success(api.deliver_transport_job(scn["job"]["id"], COORDINATOR))
    assert delivered["status"] == "DELIVERED"

    resp = api.complete_set_transport_job(scn["job"]["id"], installer_headers)
    validate_error(resp, ApiErrorId.ERR_PERMIT_MISSING)

    job_view = get_success_data(api.get_transport_job(scn["job"]["id"], COORDINATOR))
    assert job_view["status"] == "DELIVERED", "a permit-rejected set completion leaves the job DELIVERED"
    unit_view = get_success_data(api.get_home_unit(scn["unit"]["id"], ADMIN))
    assert unit_view["status"] == "ON_SITE"


# --- title record uniqueness ---------------------------------------------------------

def test_second_title_record_rejected(api, admin_headers):
    """PRD §3.7: "A unit may carry at most one open title record — status
    `APPLIED` or `ISSUED` — at a time; a second application is rejected with
    `ERR_TITLE_ALREADY_ACTIVE`."

    Design: Corner/validations/second_title_record_rejected
    """
    model = create_model()
    unit_id = create_unit(model["id"])["id"]

    title = get_success_data(api.create_title_record(unit_id, create_title_record_payload(), admin_headers))
    assert title["status"] == "APPLIED"

    resp = api.create_title_record(unit_id, create_title_record_payload(title_type="REAL_PROPERTY_AFFIXED"), admin_headers)
    validate_error(resp, ApiErrorId.ERR_TITLE_ALREADY_ACTIVE)

    issued = get_success_data(api.issue_title_record(title["id"], admin_headers))
    assert issued["status"] == "ISSUED"

    resp2 = api.create_title_record(unit_id, create_title_record_payload(title_type="REAL_PROPERTY_AFFIXED"), admin_headers)
    validate_error(resp2, ApiErrorId.ERR_TITLE_ALREADY_ACTIVE)
