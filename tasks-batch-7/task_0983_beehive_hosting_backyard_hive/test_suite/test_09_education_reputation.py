"""Education course gating and incident-driven host reputation."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    complete_course,
    complete_enrollment,
    create_active_host,
    create_agreement_payload,
    create_incident_payload,
    create_site_for,
    create_subscription_payload,
    enroll,
    make_host_headers,
    resolve_incident_payload,
    setup_host_with_site,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]
MGR = TEST_USERS["manager_headers"]


class TestEducationGates:
    def test_premium_without_host101_rejected(self, api):
        """PRD §3.9: "Choosing `PREMIUM` at creation — and likewise when
        scheduling a change into `PREMIUM` — requires the host to hold a
        `COMPLETED` `HOST-101` enrollment, else
        `ERR_COURSE_PREREQUISITE_NOT_MET`."

        Design: Corner/errors/premium_without_host101_rejected
        """
        host = create_active_host()
        res = api.create_subscription(
            create_subscription_payload(host["id"], "PREMIUM"), OPS,
        )
        validate_error(res, "ERR_COURSE_PREREQUISITE_NOT_MET")

    def test_adv201_requires_completed_host101(self, api):
        """PRD §3.9: "`ADV-201` requires a `COMPLETED` `HOST-101`, and
        `QUEEN-301` requires a `COMPLETED` `ADV-201`, with violations rejected
        as `ERR_COURSE_PREREQUISITE_NOT_MET`."
        PRD §3.9: "`PlatformOps` records the quiz outcome by submitting the
        `quiz_score` (0 to 100): a score of at least 80 completes the course,
        stamping `completed_at`; below 80 fails it."

        Design: Corner/errors/enroll_adv201_without_host101_rejected
        """
        host = create_active_host()
        failed = complete_course(host, "HOST-101", quiz_score=60)
        assert failed["status"] == "FAILED", "quiz 60 < 80 fails the course"
        res = api.create_enrollment(
            {"host_id": host["id"], "course_code": "ADV-201"},
            make_host_headers(host["id"]),
        )
        validate_error(res, "ERR_COURSE_PREREQUISITE_NOT_MET")

    def test_complete_completed_enrollment_rejected(self, api):
        """PRD §3.9: "a score of at least 80 completes the course, stamping
        `completed_at`; below 80 fails it. Both outcomes are terminal,
        completing an already-terminal enrollment fails with
        `ERR_ENROLLMENT_NOT_COMPLETABLE`, and retakes simply create a new
        enrollment row."

        Design: Corner/errors/complete_completed_enrollment_rejected
        """
        host = create_active_host()
        completed = complete_course(host, "HOST-101", quiz_score=80)
        assert completed["status"] == "COMPLETED", (
            "exactly 80 completes (pass boundary inclusive)"
        )
        res = api.complete_enrollment(
            completed["id"], {"quiz_score": 100}, OPS,
        )
        validate_error(res, "ERR_ENROLLMENT_NOT_COMPLETABLE")


class TestReputation:
    def test_reputation_decrements_on_at_fault(self, api):
        """PRD §3.1: "An `AT_FAULT` resolution decrements the host's
        `reputation_score` — by 15 for a `SEVERE` incident, by 5 for a `MINOR`
        one, never below zero — while `NO_FAULT` and `DISMISSED` leave
        reputation untouched."

        Design: Corner/calculations/host_reputation_decrement_on_at_fault
        """
        host, site = setup_host_with_site()
        severe = validate_success(
            api.create_incident(
                create_incident_payload(site["id"], severity="SEVERE"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        validate_success(
            api.resolve_incident(
                severe["id"],
                resolve_incident_payload("AT_FAULT", liability_cents=5000),
                MGR,
            ),
            200,
        )
        # The SEVERE report auto-blocked the site; with no REPORTED incident
        # left, the manager can clear it.
        unblocked = validate_success(api.unblock_site(site["id"], MGR), 200)
        assert unblocked["status"] == "CLEAR"

        minor = validate_success(
            api.create_incident(
                create_incident_payload(site["id"], severity="MINOR"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        validate_success(
            api.resolve_incident(
                minor["id"], resolve_incident_payload("AT_FAULT"), MGR,
            ),
            200,
        )
        host_now = validate_success(api.get_host(host["id"], OPS))
        assert host_now["reputation_score"] == 80, "100 - 15 SEVERE - 5 MINOR"

    def test_reputation_gate_blocks_new_agreement(self, api):
        """PRD §3.1: "Reputation gates new business: a host whose
        `reputation_score` has fallen below 50 cannot have new agreements
        created for them, failing with `ERR_HOST_REPUTATION_TOO_LOW`."

        Design: Corner/calculations/reputation_gate_blocks_new_agreement
        """
        host, site = setup_host_with_site()
        for day in ("2026-05-02T00:00:00Z", "2026-05-03T00:00:00Z",
                    "2026-05-04T00:00:00Z", "2026-05-05T00:00:00Z"):
            incident = validate_success(
                api.create_incident(
                    create_incident_payload(
                        site["id"], severity="SEVERE", occurred_at=day,
                    ),
                    make_host_headers(host["id"]),
                ),
                201,
            )
            validate_success(
                api.resolve_incident(
                    incident["id"], resolve_incident_payload("AT_FAULT"), MGR,
                ),
                200,
            )
            validate_success(api.unblock_site(site["id"], MGR), 200)

        host_now = validate_success(api.get_host(host["id"], OPS))
        assert host_now["reputation_score"] == 40, (
            "100 - 4 x 15 SEVERE at-fault"
        )
        res = api.create_agreement(
            create_agreement_payload(
                host["id"], site["id"],
                term_start_date="2026-06-01T00:00:00Z",
            ),
            OPS,
        )
        validate_error(res, "ERR_HOST_REPUTATION_TOO_LOW")
