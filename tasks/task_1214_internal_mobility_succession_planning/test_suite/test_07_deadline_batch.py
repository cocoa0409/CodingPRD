"""Deadline batch processing: deemed consent and hold expiry."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_manager, setup_employee,
    setup_vacancy_scenario, setup_open_posting, setup_application,
    set_clock, make_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _env(api, **posting_overrides):
    ctx = setup_vacancy_scenario()
    ctx["posting"] = setup_open_posting(
        ctx["vacancy"]["id"], ctx["hrbp_headers"], **posting_overrides,
    )
    return ctx


class TestDeemedConsent:
    def test_deemed_consent_via_deadline_batch(self, api):
        """PRD §3.5: "An `HRAdmin` runs a batch deadline-processing capability
        that advances every application still in `PENDING_MANAGER_CONSENT`
        whose `consent_deadline` has been reached or passed to
        `CONSENT_GRANTED` — manager silence is deemed consent — and every
        application in `MANAGER_HOLD` whose `hold_expires_at` has been reached
        or passed to `CONSENT_GRANTED`, recomputing each affected applicant's
        `active_hold_count` downward. The batch reports how many applications
        it advanced along each path as `advanced_consent_count` and
        `advanced_hold_count`."

        Design: Corner/endpoints/deemed_consent_via_deadline_batch
        """
        ctx = _env(api, min_tenure_months=12,
                   planned_open_date="2026-05-04", planned_close_date="2026-06-30")
        manager, _ = setup_manager()
        applicant_a = setup_employee(hire_date="2024-05-01", job_level=5,
                                     performance_rating="SOLID",
                                     current_manager_id=manager["id"])
        applicant_b = setup_employee(hire_date="2024-05-01", job_level=5,
                                     performance_rating="SOLID",
                                     current_manager_id=manager["id"])
        # APP_A at the startup clock 2026-05-01 -> deadline 2026-05-15.
        app_a = setup_application(ctx["posting"]["id"], applicant_a)
        assert app_a["status"] == "PENDING_MANAGER_CONSENT"
        # APP_B after moving the clock to 2026-05-10 -> deadline 2026-05-24.
        set_clock("2026-05-10T00:00:00Z")
        app_b = setup_application(ctx["posting"]["id"], applicant_b)
        assert app_b["status"] == "PENDING_MANAGER_CONSENT"

        set_clock("2026-05-20T00:00:00Z")
        report = validate_success(api.process_consent_deadlines(ADMIN), 200)
        assert report["advanced_consent_count"] == 1
        assert report["advanced_hold_count"] == 0

        app_a = get_success_data(api.get_application(app_a["id"], ADMIN))
        assert app_a["status"] == "CONSENT_GRANTED", "silence past the deadline is deemed consent"
        app_b = get_success_data(api.get_application(app_b["id"], ADMIN))
        assert app_b["status"] == "PENDING_MANAGER_CONSENT", (
            "window still open until 2026-05-24: the batch must not touch it"
        )


class TestHoldExpiry:
    def test_hold_expiry_via_deadline_batch(self, api):
        """PRD §2.4: "A hold's `hold_expires_at` is its `hold_at` instant plus
        30 days."
        PRD §3.5: "and every application in `MANAGER_HOLD` whose
        `hold_expires_at` has been reached or passed to `CONSENT_GRANTED`,
        recomputing each affected applicant's `active_hold_count` downward. The
        batch reports how many applications it advanced along each path as
        `advanced_consent_count` and `advanced_hold_count`."

        Design: Corner/endpoints/hold_expiry_via_deadline_batch
        """
        ctx = _env(api, min_tenure_months=12,
                   planned_open_date="2026-05-04", planned_close_date="2026-06-30")
        manager, _ = setup_manager()
        holder = setup_employee(hire_date="2024-05-01", job_level=5,
                                performance_rating="SOLID",
                                current_manager_id=manager["id"])
        application = setup_application(ctx["posting"]["id"], holder)
        held = validate_success(api.hold_application(
            application["id"], {"hold_reason": "CRITICAL_PROJECT"},
            make_manager_headers(manager["id"]),
        ), 200)
        assert held["status"] == "MANAGER_HOLD"
        # hold_at 2026-05-01T00:00:00Z -> hold_expires_at 2026-05-31T00:00:00Z.

        employee = get_success_data(api.get_employee(holder["id"], ADMIN))
        assert employee["active_hold_count"] == 1

        set_clock("2026-06-01T00:00:00Z")
        report = validate_success(api.process_consent_deadlines(ADMIN), 200)
        assert report["advanced_hold_count"] == 1
        assert report["advanced_consent_count"] == 0

        application = get_success_data(api.get_application(application["id"], ADMIN))
        assert application["status"] == "CONSENT_GRANTED"
        employee = get_success_data(api.get_employee(holder["id"], ADMIN))
        assert employee["active_hold_count"] == 0, (
            "expiring the hold recomputes the applicant's active_hold_count downward"
        )
