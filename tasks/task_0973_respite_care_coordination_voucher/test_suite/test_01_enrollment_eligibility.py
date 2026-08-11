"""Enrollment, eligibility applications, and approval-time allocation auto-creation."""
from test_helpers import (
    ANON,
    COORD,
    ApiErrorId,
    assert_allocation,
    assert_caregiver,
    assert_hours,
    assert_ts_equal,
    create_active_caregiver,
    create_application_payload,
    create_caregiver_payload,
    create_program,
    make_caregiver_headers,
    api_client,
    get_success_data,
    validate_error,
    validate_success,
)


def test_missing_email_rejected(api):
    """PRD §3.2: "The enrollment request carries `full_name`, `email`,
    `care_recipient_name`, and `care_recipient_condition`."
    PRD §2.9: "(4) request schema (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/caregiver_create_missing_email_returns_invalid_request
    """
    create_program()
    payload = create_caregiver_payload()
    del payload["email"]
    res = api.create_caregiver(payload, ANON)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_duplicate_email_rejected(api):
    """PRD §3.2: "The `email` must be unique across caregivers; a duplicate is
    rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/entities/caregiver_duplicate_email_rejected
    """
    create_program()
    first = validate_success(api.create_caregiver(create_caregiver_payload(), ANON), 201)
    assert_caregiver(first)
    res = api.create_caregiver(
        create_caregiver_payload(full_name="Ann Other", care_recipient_condition="als"), ANON)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_EMAIL, expected_status=409)


def test_system_fields_ignored_on_create(api):
    """PRD §3.2: "A new caregiver starts in `ENROLLED` status with
    `redetermination_due_at` null."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of the resource".

    Design: Corner/entities/caregiver_create_system_fields_input_ignored
    """
    create_program()
    payload = create_caregiver_payload()
    payload["status"] = "ACTIVE"
    payload["version"] = 99
    caregiver = validate_success(api.create_caregiver(payload, ANON), 201)
    assert caregiver["status"] == "ENROLLED"
    assert caregiver["version"] == 1
    assert caregiver["redetermination_due_at"] is None


def test_allocation_auto_created_on_approval(api):
    """PRD §3.2: "The auto-created allocation's `granted_hours` equals the program's
    `quarterly_cap_hours`, its `available_hours` equals `granted_hours`, all other
    buckets start at 0, and its status is `OPEN`. Its `period_start` and `period_end`
    are derived from the program's fiscal calendar at creation time."
    PRD §2.6: "Quarters are three-calendar-month blocks anchored to the program's
    `fiscal_year_start`."

    Design: Corner/entities/allocation_buckets_computed_on_approval
    """
    ctx = create_active_caregiver()
    alloc = ctx["allocation"]
    assert_allocation(alloc)
    assert_hours(alloc["granted_hours"], 80.00, "granted_hours")
    assert_hours(alloc["available_hours"], 80.00, "available_hours")
    assert_hours(alloc["reserved_hours"], 0.00, "reserved_hours")
    assert_hours(alloc["consumed_hours"], 0.00, "consumed_hours")
    assert alloc["status"] == "OPEN"
    # Clock default 2026-05-01 sits in the fiscal quarter 2026-04-01..2026-07-01.
    assert_ts_equal(alloc["period_start"], "2026-04-01T00:00:00Z", "period_start")
    assert_ts_equal(alloc["period_end"], "2026-07-01T00:00:00Z", "period_end")


def test_appeal_from_submitted_rejected(api):
    """PRD §3.2: "An application in `DENIED` can be appealed by its owning caregiver"
    PRD §2.9: "(7) generic state-machine validity (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/application_appeal_from_submitted_rejected
    """
    create_program()
    caregiver = validate_success(api.create_caregiver(create_caregiver_payload(), ANON), 201)
    cg_headers = make_caregiver_headers(caregiver["id"])
    application = validate_success(
        api.create_eligibility_application(
            caregiver["id"], create_application_payload(), cg_headers),
        201)
    res = api.appeal_application(application["id"], {"reason": "too soon"}, cg_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_eligibility_application(application["id"], COORD), 200)
    assert after["status"] == "SUBMITTED"


class TestInfoRequestResubmissionCycle:
    def test_info_request_cycle_status_and_revision(self, api):
        """PRD §3.2: "Posting `action` `REQUEST_INFO` moves the application to
        `INFO_REQUESTED` and records the note on `review_note`."
        PRD §3.2: "An application in `INFO_REQUESTED` can be resubmitted by its owning
        caregiver, which returns it to `SUBMITTED` and increments `revision_count` by 1."

        Design: Difficulty/non_linear_state_machine/eligibility_info_request_resubmission_cycle
        """
        create_program()
        caregiver = validate_success(api.create_caregiver(create_caregiver_payload(), ANON), 201)
        cg_headers = make_caregiver_headers(caregiver["id"])
        application = validate_success(
            api.create_eligibility_application(
                caregiver["id"], create_application_payload(need_score=5), cg_headers),
            201)
        assert application["status"] == "SUBMITTED"
        assert application["revision_count"] == 0

        info = validate_success(
            api.create_review_decision(
                application["id"], {"action": "REQUEST_INFO", "note": "need physician letter"},
                COORD),
            200)
        assert info["status"] == "INFO_REQUESTED"
        assert info["review_note"] == "need physician letter"

        resubmitted = validate_success(
            api.resubmit_application(
                application["id"], {"need_score": 7, "notes": "letter attached"}, cg_headers),
            200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1
        # Resubmit does not clear the coordinator's recorded review note.
        assert resubmitted["review_note"] == "need physician letter"

    def test_info_request_cycle_approval_activates_caregiver(self, api):
        """PRD §3.2: "Posting `action` `APPROVE` moves the application to `APPROVED`"
        PRD §3.2: "If the caregiver is currently `ENROLLED`, they move to `ACTIVE`"

        Design: Difficulty/non_linear_state_machine/eligibility_info_request_resubmission_cycle
        """
        create_program()
        caregiver = validate_success(api.create_caregiver(create_caregiver_payload(), ANON), 201)
        cg_headers = make_caregiver_headers(caregiver["id"])
        application = validate_success(
            api.create_eligibility_application(
                caregiver["id"], create_application_payload(need_score=5), cg_headers),
            201)
        validate_success(
            api.create_review_decision(
                application["id"], {"action": "REQUEST_INFO", "note": "need physician letter"},
                COORD),
            200)
        validate_success(
            api.resubmit_application(
                application["id"], {"need_score": 7, "notes": "letter attached"}, cg_headers),
            200)
        approved = validate_success(
            api.create_review_decision(application["id"], {"action": "APPROVE"}, COORD), 200)
        assert approved["status"] == "APPROVED"
        caregiver_after = validate_success(api.get_caregiver(caregiver["id"], COORD), 200)
        assert caregiver_after["status"] == "ACTIVE"
