"""Ownership, referential coherence, regulatory standing, temporal window,
verification-method and affirmation-prerequisite behaviour of the CLE
accreditation API.

Every test builds its own state from an empty register, with the logical clock
at its default instant of 2026-08-01T00:00:00Z.
"""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    accreditation_action,
    api_client,
    assert_attendance_code_shape,
    assert_version_unchanged,
    certification_payload,
    create_accredited_provider,
    create_affirmation_payload,
    create_attorney,
    create_credit_record_payload,
    create_cycle,
    create_probationary_provider,
    create_provider_audit_payload,
    create_self_certified_course,
    change_attorney_status,
    credit_allocation_entry,
    disposition_payload,
    file_affirmation,
    file_complaint,
    file_credit_record,
    list_affirmations,
    list_applications,
    list_audits,
    list_credit_records,
    make_attorney_headers,
    make_board_admin_headers,
    make_provider_admin_headers,
    read_attorney,
    read_complaint,
    read_course,
    read_credit_record,
    read_cycle,
    read_provider,
    setup_attorney_with_cycle,
    submit_application,
    validate_error,
    validate_success,
)

# The logical clock starts every test here.
CLOCK_START = "2026-08-01T00:00:00Z"

# Two distinct board operators, so that the identity comparison behind
# segregation of duties has something to compare.
FILING_BOARD_USER = "11111111-1111-4111-8111-111111111111"
DISPOSING_BOARD_USER = "22222222-2222-4222-8222-222222222222"

FINAL_STATEMENT = "I affirm my compliance report for this period is complete and accurate."
ATTENDANCE_STATEMENT = "I affirm I attended the recorded programme in full."


def parse_instant(value: str) -> datetime:
    """Timestamps are rendered with three fractional digits, so compare the
    instants rather than the strings."""
    text = value[:-1] if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def credit_payload(attorney, course_id, **overrides) -> dict:
    """A credit claim carrying only the fields its verification method needs."""
    payload = create_credit_record_payload(attorney["id"], course_id, **overrides)
    if payload.get("verification_method") != "CERTIFICATE":
        payload.pop("certificate_reference", None)
    return {key: value for key, value in payload.items() if value is not None}


def post_credit_record(attorney, course_id, **overrides):
    """The raw claim response, so refusals can be inspected."""
    return api_client.create_credit_record(
        credit_payload(attorney, course_id, **overrides),
        make_attorney_headers(attorney["id"]),
    )


def on_demand_course(provider, title, total_minutes, presented_at,
                     verification_method="CERTIFICATE"):
    return create_self_certified_course(
        provider,
        title=title,
        delivery_format="ON_DEMAND",
        total_minutes=total_minutes,
        presented_at=presented_at,
        attendance_verification_method=verification_method,
        credit_allocations=[credit_allocation_entry("GENERAL", total_minutes)],
    )


def live_approval_course(provider, title, presented_at):
    """A course of a sponsor that cannot self-certify, so it waits in
    PENDING_APPROVAL until an application is decided."""
    return create_self_certified_course(
        provider,
        title=title,
        delivery_format="LIVE_IN_PERSON",
        total_minutes=300,
        presented_at=presented_at,
        attendance_verification_method="ROSTER",
        credit_allocations=[credit_allocation_entry("GENERAL", 300)],
    )


def test_an_attorney_cannot_file_an_affirmation_on_another_attorneys_cycle():
    """When `X-User-Role` is `Attorney`, `X-User-ID` is the `id` of the acting `Attorney`; ownership checks compare `X-User-ID` to the `attorney_id` of the compliance cycle, credit record, reciprocity claim or fee assessment being touched, and to the `attorney_id` of the cycle behind an affirmation or a certification.
    An entity-backed role addressing a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); the same code covers a supplement or an appeal attempted by anyone other than the application's own `applicant_user_id`.
    **Resource ownership** for the entity-backed roles, as described in §2.1 — otherwise `ERR_NOT_RESOURCE_OWNER` (403).
    The affirmation is bound to the cycle it is filed against by `cycle_id`, and `affirmed_by_user_id` records the acting `X-User-ID`, which must equal that cycle's `attorney_id`.

    Design: Corner/validations/an_attorney_cannot_file_an_affirmation_or_read_a_summary_on_another_attorneys_cycle
    """
    attorney_a = create_attorney(bar_number="V4-0001", full_name="Ana Restrepo",
                                 admission_date="2011-01-10T00:00:00Z")
    attorney_b = create_attorney(bar_number="V4-0002", full_name="Bo Lindqvist",
                                 admission_date="2012-02-20T00:00:00Z")
    cycle_a = create_cycle(attorney_a["id"], "2026-02-01T00:00:00Z", "2028-02-01T00:00:00Z")

    body = create_affirmation_payload(
        "FINAL_COMPLIANCE_AFFIRMATION",
        statement="I affirm the credits reported for this period are accurate.",
    )

    # Attorney B holds a permitted role and the cycle identifier exists; only
    # the ownership comparison stands in the way.
    validate_error(
        api_client.create_affirmation(
            cycle_a["id"], body, make_attorney_headers(attorney_b["id"])
        ),
        "ERR_NOT_RESOURCE_OWNER",
    )
    assert list_affirmations(cycle_a["id"]) == []

    affirmation = validate_success(
        api_client.create_affirmation(
            cycle_a["id"], body, make_attorney_headers(attorney_a["id"])
        ),
        expected_status=201,
    )
    assert affirmation["cycle_id"] == cycle_a["id"]
    assert affirmation["affirmed_by_user_id"] == attorney_a["id"]
    assert len(list_affirmations(cycle_a["id"])) == 1


def test_an_attorney_cannot_read_another_attorneys_cycle_summary():
    """When `X-User-Role` is `Attorney`, `X-User-ID` is the `id` of the acting `Attorney`; ownership checks compare `X-User-ID` to the `attorney_id` of the compliance cycle, credit record, reciprocity claim or fee assessment being touched, and to the `attorney_id` of the cycle behind an affirmation or a certification.
    An entity-backed role addressing a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); the same code covers a supplement or an appeal attempted by anyone other than the application's own `applicant_user_id`.
    This step applies to course creation, application filing, roster filing, appellant actions, credit-record creation, affirmation filing, certification, reciprocity-claim filing, fee settlement, reinstatement and the cycle summary read.
    It echoes `cycle_id`, `credit_status`, `administrative_status` and the four requirement figures `required_total_minutes`, `required_ethics_minutes`, `required_technology_minutes` and `required_bias_minutes`.

    Design: Corner/validations/an_attorney_cannot_file_an_affirmation_or_read_a_summary_on_another_attorneys_cycle
    """
    attorney_a = create_attorney(bar_number="V4-0001", full_name="Ana Restrepo",
                                 admission_date="2011-01-10T00:00:00Z")
    attorney_b = create_attorney(bar_number="V4-0002", full_name="Bo Lindqvist",
                                 admission_date="2012-02-20T00:00:00Z")
    cycle_a = create_cycle(attorney_a["id"], "2026-02-01T00:00:00Z", "2028-02-01T00:00:00Z")

    # The ownership rule guards the computed read exactly as it guards a write.
    validate_error(
        api_client.get_cycle_summary(
            cycle_a["id"], make_attorney_headers(attorney_b["id"])
        ),
        "ERR_NOT_RESOURCE_OWNER",
    )

    summary = validate_success(
        api_client.get_cycle_summary(
            cycle_a["id"], make_attorney_headers(attorney_a["id"])
        ),
        expected_status=200,
    )
    assert summary["cycle_id"] == cycle_a["id"]


def test_a_completion_one_second_before_period_start_finds_no_owning_cycle():
    """The owning period is never supplied by the client.
    The server resolves `cycle_id` to the one cycle of that attorney whose half-open window from `period_start` inclusive to `period_end` exclusive contains `completion_date`.
    If no cycle of that attorney covers the completion instant, the claim is rejected with `ERR_OUTSIDE_COMPLIANCE_PERIOD`; if the resolved cycle turns out to belong to a different attorney than the claim's `attorney_id`, that is `ERR_CYCLE_ATTORNEY_MISMATCH`.

    Design: Corner/validations/a_completion_date_outside_the_half_open_cycle_window_finds_no_owning_cycle
    """
    provider = create_accredited_provider(name="Statehouse Law School",
                                          provider_type="LAW_SCHOOL")
    course = on_demand_course(provider, "Recorded Ethics Survey", 600,
                              "2025-06-01T00:00:00Z")
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V6-0001", "full_name": "Iris Vandermeer",
                            "admission_date": "2009-09-09T00:00:00Z"},
    )

    validate_error(
        post_credit_record(
            attorney, course["id"], verification_method="CERTIFICATE",
            certificate_reference="CERT-A", attended_minutes=600,
            completion_date="2025-12-31T23:59:59Z",
        ),
        "ERR_OUTSIDE_COMPLIANCE_PERIOD",
    )
    assert list_credit_records(cycle_id=cycle["id"]) == []


def test_a_completion_at_period_end_finds_no_owning_cycle():
    """The server resolves `cycle_id` to the one cycle of that attorney whose half-open window from `period_start` inclusive to `period_end` exclusive contains `completion_date`.
    If no cycle of that attorney covers the completion instant, the claim is rejected with `ERR_OUTSIDE_COMPLIANCE_PERIOD`; if the resolved cycle turns out to belong to a different attorney than the claim's `attorney_id`, that is `ERR_CYCLE_ATTORNEY_MISMATCH`.
    The period is the half-open interval running from `period_start` inclusive to `period_end` exclusive, and `period_start` must be strictly earlier than `period_end`.

    Design: Corner/validations/a_completion_date_outside_the_half_open_cycle_window_finds_no_owning_cycle
    """
    provider = create_accredited_provider(name="Statehouse Law School",
                                          provider_type="LAW_SCHOOL")
    course = on_demand_course(provider, "Recorded Ethics Survey", 600,
                              "2025-06-01T00:00:00Z")
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V6-0001", "full_name": "Iris Vandermeer",
                            "admission_date": "2009-09-09T00:00:00Z"},
    )

    # period_end itself is excluded, so the instant that ends the window
    # belongs to no cycle.
    validate_error(
        post_credit_record(
            attorney, course["id"], verification_method="CERTIFICATE",
            certificate_reference="CERT-B", attended_minutes=600,
            completion_date="2028-01-01T00:00:00Z",
        ),
        "ERR_OUTSIDE_COMPLIANCE_PERIOD",
    )
    assert list_credit_records(cycle_id=cycle["id"]) == []


def test_a_completion_at_period_start_resolves_the_owning_cycle():
    """The server resolves `cycle_id` to the one cycle of that attorney whose half-open window from `period_start` inclusive to `period_end` exclusive contains `completion_date`.
    With `CERTIFICATE` or `AFFIRMATION`, the record is created in `PENDING_VERIFICATION` and waits: a certificate claim waits for board adjudication, an affirmation claim waits for the attorney's own sworn affirmation.
    An `ON_DEMAND` course always yields `ON_DEMAND`, and a `SELF_STUDY` course always yields `SELF_STUDY`.

    Design: Corner/validations/a_completion_date_outside_the_half_open_cycle_window_finds_no_owning_cycle
    """
    provider = create_accredited_provider(name="Statehouse Law School",
                                          provider_type="LAW_SCHOOL")
    course = on_demand_course(provider, "Recorded Ethics Survey", 600,
                              "2025-06-01T00:00:00Z")
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V6-0001", "full_name": "Iris Vandermeer",
                            "admission_date": "2009-09-09T00:00:00Z"},
    )

    # period_start is included, so the first instant of the window is creditable.
    record = validate_success(
        post_credit_record(
            attorney, course["id"], verification_method="CERTIFICATE",
            certificate_reference="CERT-C", attended_minutes=600,
            completion_date="2026-01-01T00:00:00Z",
        ),
        expected_status=201,
    )
    assert record["cycle_id"] == cycle["id"]
    assert record["status"] == "PENDING_VERIFICATION"
    assert record["effective_format"] == "ON_DEMAND"
    assert len(list_credit_records(cycle_id=cycle["id"])) == 1


def test_the_complaint_filer_cannot_substantiate_its_own_complaint():
    """The operator who issued a review action on an application (recorded as `reviewer_user_id`) may not decide that application's appeal, and the operator who filed a complaint (recorded as `complainant_user_id`) may not substantiate or dismiss it. Either violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    Recording the filer has a purpose: it disqualifies them.
    A board member who files a complaint and then tries to dispose of it is rejected with `ERR_SEGREGATION_OF_DUTIES`.
    `SUBSTANTIATE` is available only from `UNDER_REVIEW` — substantiating a complaint nobody has opened for review is `ERR_INVALID_STATE_TRANSITION` — and likewise requires a `disposition_reason`.
    Against a provider, the provider's `substantiated_complaint_count` rises by one, its `risk_score` is recomputed, and the provider itself moves `ACCREDITED → PROBATIONARY`.
    The complaint is created in `RECEIVED` with `escalated` false, and the filer is recorded in two fields — `complainant_role`, which takes the value `ATTORNEY` or `BOARD_ADMIN` (note that these are the recorded enumeration labels, not the header spellings of the roles), and `complainant_user_id`, which holds the acting `X-User-ID`.

    Design: Corner/validations/the_complaint_filer_cannot_dispose_of_its_own_complaint
    """
    provider = create_accredited_provider(name="Northgate CLE Partners",
                                          provider_type="GOVERNMENT")
    complaint = file_complaint(
        "PROVIDER", provider["id"], filer_user_id=FILING_BOARD_USER,
        allegation="Marketing claims 6.0 ethics hours for a 60-minute segment.",
        allegation_category="MISREPRESENTED_CREDIT",
    )
    assert complaint["complainant_user_id"] == FILING_BOARD_USER
    assert complaint["complainant_role"] == "BOARD_ADMIN"

    opened = validate_success(
        api_client.complaint_disposition(
            complaint["id"], disposition_payload("OPEN_REVIEW"),
            make_board_admin_headers(DISPOSING_BOARD_USER),
        ),
        expected_status=200,
    )
    assert opened["status"] == "UNDER_REVIEW"

    # UNDER_REVIEW -> SUBSTANTIATED is a legal transition and the reason is
    # supplied, so only the filer's identity blocks the disposition.
    validate_error(
        api_client.complaint_disposition(
            complaint["id"],
            disposition_payload(
                "SUBSTANTIATE",
                disposition_reason="Marketing copy overstated the ethics allocation.",
            ),
            make_board_admin_headers(FILING_BOARD_USER),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
    )

    dismissed = validate_success(
        api_client.complaint_disposition(
            complaint["id"],
            disposition_payload(
                "DISMISS",
                disposition_reason=(
                    "The disputed segment was corrected before any attorney relied on it."
                ),
            ),
            make_board_admin_headers(DISPOSING_BOARD_USER),
        ),
        expected_status=200,
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["disposition_reason"] == (
        "The disputed segment was corrected before any attorney relied on it."
    )

    # The refused substantiation cascaded nothing.
    sponsor = read_provider(provider["id"])
    assert sponsor["substantiated_complaint_count"] == 0
    assert sponsor["accreditation_status"] == "ACCREDITED"
    assert read_complaint(complaint["id"])["complainant_user_id"] == FILING_BOARD_USER


def test_an_inactive_attorney_cannot_file_credit_until_the_board_restores_the_status():
    """**Regulatory standing** of the entities a credit-bearing write depends on: the course is `APPROVED` (`ERR_COURSE_NOT_APPROVED`), the sponsoring provider is `ACCREDITED` or `PROBATIONARY` (`ERR_PROVIDER_NOT_IN_GOOD_STANDING`), and the attorney's `status` is `ACTIVE` or `EXEMPT` rather than `ADMIN_SUSPENDED` or `INACTIVE` (`ERR_ATTORNEY_NOT_IN_GOOD_STANDING`) — all HTTP 409.
    The claim also requires the course to be `APPROVED` (otherwise `ERR_COURSE_NOT_APPROVED`), the `completion_date` to be no later than the course's `expires_at` (otherwise `ERR_COURSE_APPROVAL_EXPIRED`), and the attorney's `status` to be `ACTIVE` or `EXEMPT` (otherwise `ERR_ATTORNEY_NOT_IN_GOOD_STANDING`).
    Board staff may move an attorney between `ACTIVE`, `EXEMPT` and `INACTIVE` by supplying the target `status` and an optional `reason`; this is the only actor-driven writer of that field.
    The **provisional** variant includes the cycle's records in `PENDING_VERIFICATION` and `VERIFIED`.
    While a cycle's `credit_status` is `OPEN`, the provisional result is what gets persisted into the cycle's `earned_*` fields and into each record's `countable_minutes`.

    Design: Corner/validations/an_inactive_attorney_cannot_file_credit_until_the_board_restores_the_status
    """
    provider = create_accredited_provider(name="Riverbend Bar Institute",
                                          provider_type="BAR_ASSOCIATION")
    course = on_demand_course(provider, "Recorded Discovery Practice", 300,
                              "2026-02-01T00:00:00Z")
    assert course["status"] == "APPROVED"

    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V9-0001", "full_name": "Marek Sowinski",
                            "admission_date": "2008-04-04T00:00:00Z"},
    )
    inactive = change_attorney_status(attorney["id"], "INACTIVE",
                                     reason="Resigned from active practice.")
    assert inactive["status"] == "INACTIVE"

    claim = {
        "verification_method": "CERTIFICATE",
        "certificate_reference": "CERT-9A",
        "attended_minutes": 300,
        "completion_date": "2026-06-01T00:00:00Z",
    }

    # The course is APPROVED and its sponsor is ACCREDITED, so the attorney
    # clause is the only standing clause that can bind.
    validate_error(
        post_credit_record(attorney, course["id"], **claim),
        "ERR_ATTORNEY_NOT_IN_GOOD_STANDING",
    )
    assert list_credit_records(attorney_id=attorney["id"]) == []

    restored = change_attorney_status(attorney["id"], "ACTIVE",
                                      reason="Returned to active practice.")
    assert restored["status"] == "ACTIVE"

    record = validate_success(
        post_credit_record(attorney, course["id"], **claim),
        expected_status=201,
    )
    assert record["cycle_id"] == cycle["id"]
    assert record["status"] == "PENDING_VERIFICATION"
    assert len(list_credit_records(attorney_id=attorney["id"])) == 1

    # The provisional run counts the pending record straight away.
    assert read_cycle(cycle["id"])["earned_countable_minutes"] == 300


def test_a_suspended_sponsor_blocks_its_own_pending_courses_from_seeking_approval():
    """**Regulatory standing** of the entities a credit-bearing write depends on: the course is `APPROVED` (`ERR_COURSE_NOT_APPROVED`), the sponsoring provider is `ACCREDITED` or `PROBATIONARY` (`ERR_PROVIDER_NOT_IN_GOOD_STANDING`), and the attorney's `status` is `ACTIVE` or `EXEMPT` rather than `ADMIN_SUSPENDED` or `INACTIVE` (`ERR_ATTORNEY_NOT_IN_GOOD_STANDING`) — all HTTP 409. Applies to credit-record creation, roster filing, application filing and reciprocity-claim filing.
    The course must still be in `PENDING_APPROVAL`; filing against a course in any other status is `ERR_COURSE_NOT_APPROVED`.
    It is `PROVIDER_ACCREDITED` when `provider_id` is supplied *and* that sponsor's `self_certification_enabled` is true at the moment of creation; in every other case — no sponsor at all, or a sponsor that is not fully accredited — it is `INDIVIDUAL_APPROVAL`.
    Every other course is created in `PENDING_APPROVAL` and stays there until an application is decided; if it names a sponsor, only that sponsor's `courses_total_count` rises.
    `SUSPEND` may be applied to a sponsor in either `ACCREDITED` or `PROBATIONARY`, moving it to `SUSPENDED`, and the same two transitions also fire automatically when an audit closes with a suspension sanction.
    Both branches set `self_certification_enabled` to false and both run the sponsor-suspension cascade: every course of that sponsor that is currently `APPROVED`, was approved through the self-certification pathway, and has not yet reached its `expires_at` moves `APPROVED → SUSPENDED_PENDING_REVIEW`.

    Design: Corner/validations/a_suspended_sponsor_blocks_its_own_pending_courses_from_seeking_approval
    """
    provider = create_probationary_provider(
        name="Pinehill Seminars", provider_type="COMMERCIAL",
    )
    assert provider["accreditation_status"] == "PROBATIONARY"
    assert provider["self_certification_enabled"] is False

    sponsor_headers = make_provider_admin_headers(provider["id"])
    first = live_approval_course(provider, "Cross Examination Clinic",
                                "2026-09-10T09:00:00Z")
    second = live_approval_course(provider, "Settlement Negotiation Clinic",
                                 "2026-11-10T09:00:00Z")
    assert first["approval_pathway"] == "INDIVIDUAL_APPROVAL"
    assert second["approval_pathway"] == "INDIVIDUAL_APPROVAL"

    # A PROBATIONARY sponsor is in good standing, so this application lands.
    application = submit_application(first["id"], sponsor_headers)
    assert application["status"] == "SUBMITTED"

    # Registering the two courses bumped the sponsor's courses_total_count, and
    # every cascade-touched row has its version incremented, so the accreditation
    # action must carry the sponsor's currently observed version.
    suspended = accreditation_action(
        provider["id"], "SUSPEND", read_provider(provider["id"])["version"],
        probation_reason="Ongoing investigation into attendance records.",
    )
    assert suspended["accreditation_status"] == "SUSPENDED"

    validate_error(
        api_client.create_course_application(second["id"], sponsor_headers),
        "ERR_PROVIDER_NOT_IN_GOOD_STANDING",
    )

    # The suspension cascade touches only self-certified APPROVED courses, so
    # neither pending course moved.
    assert read_course(first["id"])["status"] == "PENDING_APPROVAL"
    assert read_course(second["id"])["status"] == "PENDING_APPROVAL"
    assert list_applications(second["id"]) == []
    assert len(list_applications(first["id"])) == 1


def test_an_affirmation_targeting_another_attorneys_credit_record_is_a_mismatch():
    """**Referential coherence between two rows that both exist**: the cycle named by a request belongs to the same attorney as the request's `attorney_id`, and an affirmation's target credit record belongs to the addressed cycle (`ERR_CYCLE_ATTORNEY_MISMATCH`); a roster's course belongs to the acting provider (`ERR_COURSE_PROVIDER_MISMATCH`); an escalating audit names the same provider its originating complaint resolves to (`ERR_COURSE_PROVIDER_MISMATCH`) — HTTP 409.
    An attendance affirmation cascades: the targeted record must be in `PENDING_VERIFICATION` with a `verification_method` of `AFFIRMATION`, and it must belong to the same cycle the affirmation is filed against — a target in another cycle is `ERR_CYCLE_ATTORNEY_MISMATCH`, and a target that resolves to nothing is `ERR_CREDIT_RECORD_NOT_FOUND`.
    On acceptance the record moves `PENDING_VERIFICATION → VERIFIED`, its `affirmation_id` is set to the new affirmation (this reverse link on the record, not the forward link on the affirmation, is the queryable side of the association), the course's `verified_credit_record_count` rises by one, and the cycle's credit application is re-run.
    `ATTENDANCE_AFFIRMATION` verifies exactly one credit record and therefore requires `target_credit_record_id`; the two other types forbid it, and supplying it anyway — or omitting it on an attendance affirmation — is `ERR_INVALID_REQUEST`.

    Design: Corner/validations/two_foreign_keys_that_name_different_owners_are_refused_as_mismatches
    """
    provider = create_accredited_provider(name="Alpha Legal Education",
                                          provider_type="BAR_ASSOCIATION")
    course = on_demand_course(provider, "Recorded Trust Accounting", 300,
                              "2026-02-01T00:00:00Z",
                              verification_method="AFFIRMATION_ONLY")

    attorney_a, cycle_a = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V10-0001", "full_name": "Nadia Farouk",
                            "admission_date": "2007-07-07T00:00:00Z"},
    )
    attorney_b, cycle_b = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V10-0002", "full_name": "Owen Bracknell",
                            "admission_date": "2007-08-08T00:00:00Z"},
    )

    record_b = file_credit_record(
        attorney_b, course["id"], verification_method="AFFIRMATION",
        attended_minutes=300, completion_date="2026-06-01T00:00:00Z",
        certificate_reference=None,
    )
    assert record_b["cycle_id"] == cycle_b["id"]
    assert record_b["status"] == "PENDING_VERIFICATION"

    # Attorney A owns the addressed cycle, so ownership is satisfied; the two
    # rows simply disagree about whose credit is being affirmed.
    validate_error(
        api_client.create_affirmation(
            cycle_a["id"],
            create_affirmation_payload(
                "ATTENDANCE_AFFIRMATION",
                statement=ATTENDANCE_STATEMENT,
                target_credit_record_id=record_b["id"],
            ),
            make_attorney_headers(attorney_a["id"]),
        ),
        "ERR_CYCLE_ATTORNEY_MISMATCH",
    )

    # The refused affirmation verified nothing.
    untouched = read_credit_record(record_b["id"])
    assert untouched["status"] == "PENDING_VERIFICATION"
    assert untouched["affirmation_id"] is None
    assert list_affirmations(cycle_a["id"]) == []
    assert read_course(course["id"])["verified_credit_record_count"] == 0


def test_an_escalating_audit_must_name_the_provider_its_complaint_resolves_to():
    """**Referential coherence between two rows that both exist**: the cycle named by a request belongs to the same attorney as the request's `attorney_id`, and an affirmation's target credit record belongs to the addressed cycle (`ERR_CYCLE_ATTORNEY_MISMATCH`); a roster's course belongs to the acting provider (`ERR_COURSE_PROVIDER_MISMATCH`); an escalating audit names the same provider its originating complaint resolves to (`ERR_COURSE_PROVIDER_MISMATCH`) — HTTP 409.
    Where that complaint reference is supplied, `trigger_type` must be `COMPLAINT_ESCALATION`, the named complaint must not already have `escalated` true — otherwise `ERR_COMPLAINT_ALREADY_ESCALATED` — and the complaint must resolve to the same provider the audit names, a mismatch being `ERR_COURSE_PROVIDER_MISMATCH`.
    Accepting the audit sets that complaint's `escalated` to true, so a single complaint can seed at most one audit.
    The complaint is created in `RECEIVED` with `escalated` false, and the filer is recorded in two fields — `complainant_role`, which takes the value `ATTORNEY` or `BOARD_ADMIN` (note that these are the recorded enumeration labels, not the header spellings of the roles), and `complainant_user_id`, which holds the acting `X-User-ID`.

    Design: Corner/validations/two_foreign_keys_that_name_different_owners_are_refused_as_mismatches
    """
    first = create_accredited_provider(name="Alpha Legal Education",
                                       provider_type="BAR_ASSOCIATION")
    second = create_accredited_provider(name="Beta Legal Education",
                                        provider_type="LAW_SCHOOL")
    complaint = file_complaint(
        "PROVIDER", second["id"], filer_user_id=FILING_BOARD_USER,
        allegation="Faculty listed on the agenda never appeared.",
        allegation_category="NO_SHOW_FACULTY",
    )
    assert complaint["escalated"] is False

    # Both identifiers exist and the trigger type is the declared one; the
    # complaint simply names a different sponsor than the audit does.
    validate_error(
        api_client.create_provider_audit(
            create_provider_audit_payload(
                first["id"],
                audit_period_start="2026-01-01T00:00:00Z",
                audit_period_end="2026-12-31T00:00:00Z",
                trigger_type="COMPLAINT_ESCALATION",
                originating_complaint_id=complaint["id"],
            ),
            TEST_USERS["board_admin_headers"],
        ),
        "ERR_COURSE_PROVIDER_MISMATCH",
    )

    assert list_audits(provider_id=first["id"]) == []
    assert read_complaint(complaint["id"])["escalated"] is False


def test_a_method_the_course_did_not_commit_to_is_not_permitted():
    """**Verification methods must match the sponsor's commitment.** A record's `verification_method` is one of `ROSTER`, `ATTENDANCE_CODE`, `CERTIFICATE` or `AFFIRMATION`, and it must be the declared partner of the course's `attendance_verification_method` under a fixed pairing: a course committed to `ROSTER` accepts only `ROSTER`, one committed to `ATTENDANCE_CODE` accepts only `ATTENDANCE_CODE`, one committed to `CERTIFICATE` accepts only `CERTIFICATE`, and one committed to `AFFIRMATION_ONLY` accepts only `AFFIRMATION`. Any other combination is `ERR_VERIFICATION_METHOD_NOT_PERMITTED`.
    Where and only where the sponsor commits to `ATTENDANCE_CODE`, the system mints a six-character `attendance_code` at creation; for the other three methods `attendance_code` is null.

    Design: Corner/validations/only_the_courses_own_verification_method_and_its_exact_code_admit_a_credit_record
    """
    provider = create_accredited_provider(name="Cedar Valley Bar CLE",
                                          provider_type="BAR_ASSOCIATION")
    course = create_self_certified_course(
        provider,
        title="Webcast Evidence Update",
        delivery_format="LIVE_WEBCAST",
        total_minutes=300,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 300)],
    )
    assert_attendance_code_shape(course)
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V11-0001",
                            "full_name": "Priya Raghunathan",
                            "admission_date": "2006-06-06T00:00:00Z"},
    )

    # CERTIFICATE is a declared enum value but is not the method this course
    # committed to.
    validate_error(
        post_credit_record(
            attorney, course["id"], verification_method="CERTIFICATE",
            certificate_reference="CERT-11", attended_minutes=300,
            completion_date="2026-03-01T13:00:00Z",
        ),
        "ERR_VERIFICATION_METHOD_NOT_PERMITTED",
    )
    assert list_credit_records(course_id=course["id"]) == []


def test_an_attorney_may_never_self_assert_a_roster_record():
    """**Verification methods must match the sponsor's commitment.** A record's `verification_method` is one of `ROSTER`, `ATTENDANCE_CODE`, `CERTIFICATE` or `AFFIRMATION`, and it must be the declared partner of the course's `attendance_verification_method` under a fixed pairing: a course committed to `ROSTER` accepts only `ROSTER`, one committed to `ATTENDANCE_CODE` accepts only `ATTENDANCE_CODE`, one committed to `CERTIFICATE` accepts only `CERTIFICATE`, and one committed to `AFFIRMATION_ONLY` accepts only `AFFIRMATION`. Any other combination is `ERR_VERIFICATION_METHOD_NOT_PERMITTED`.
    That same code also rejects an attorney who names `ROSTER` on a self-filed claim: roster records may only be minted by the sponsor's roster cascade, never claimed directly.

    Design: Corner/validations/only_the_courses_own_verification_method_and_its_exact_code_admit_a_credit_record
    """
    provider = create_accredited_provider(name="Cedar Valley Bar CLE",
                                          provider_type="BAR_ASSOCIATION")
    course = create_self_certified_course(
        provider,
        title="Webcast Evidence Update",
        delivery_format="LIVE_WEBCAST",
        total_minutes=300,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 300)],
    )
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V11-0001",
                            "full_name": "Priya Raghunathan",
                            "admission_date": "2006-06-06T00:00:00Z"},
    )

    validate_error(
        post_credit_record(
            attorney, course["id"], verification_method="ROSTER",
            certificate_reference=None, attended_minutes=300,
            completion_date="2026-03-01T13:00:00Z",
        ),
        "ERR_VERIFICATION_METHOD_NOT_PERMITTED",
    )
    assert list_credit_records(course_id=course["id"]) == []


def test_an_attendance_code_that_does_not_match_the_courses_code_is_refused():
    """The method decides whether the record is born verified.
    With `ATTENDANCE_CODE`, the supplied `attendance_code` must equal the course's minted code — an absent or mismatched code is `ERR_ATTENDANCE_CODE_INVALID` — and a matching code transitions the new record `PENDING_VERIFICATION → VERIFIED` in the same request, raising the course's `verified_credit_record_count` by one and re-running the owning cycle's credit application.

    Design: Corner/validations/only_the_courses_own_verification_method_and_its_exact_code_admit_a_credit_record
    """
    provider = create_accredited_provider(name="Cedar Valley Bar CLE",
                                          provider_type="BAR_ASSOCIATION")
    course = create_self_certified_course(
        provider,
        title="Webcast Evidence Update",
        delivery_format="LIVE_WEBCAST",
        total_minutes=300,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 300)],
    )
    assert course["attendance_code"] != "ZZZZZZ"
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V11-0001",
                            "full_name": "Priya Raghunathan",
                            "admission_date": "2006-06-06T00:00:00Z"},
    )

    # The right method with a code that does not equal the course's code.
    validate_error(
        post_credit_record(
            attorney, course["id"], verification_method="ATTENDANCE_CODE",
            attendance_code="ZZZZZZ", certificate_reference=None,
            attended_minutes=300, completion_date="2026-03-01T13:00:00Z",
        ),
        "ERR_ATTENDANCE_CODE_INVALID",
    )
    assert list_credit_records(course_id=course["id"]) == []
    assert read_course(course["id"])["verified_credit_record_count"] == 0


def test_the_minted_attendance_code_creates_a_record_born_verified():
    """With `ATTENDANCE_CODE`, the supplied `attendance_code` must equal the course's minted code — an absent or mismatched code is `ERR_ATTENDANCE_CODE_INVALID` — and a matching code transitions the new record `PENDING_VERIFICATION → VERIFIED` in the same request, raising the course's `verified_credit_record_count` by one and re-running the owning cycle's credit application.
    A `LIVE_WEBCAST` course yields `LIVE` only when attendance was verified by `ATTENDANCE_CODE` or by `ROSTER` — the two methods that prove someone was actually watching in real time — and otherwise yields `ON_DEMAND`.
    Live minutes are never capped.
    While a cycle's `credit_status` is `OPEN`, the provisional result is what gets persisted into the cycle's `earned_*` fields and into each record's `countable_minutes`.

    Design: Corner/validations/only_the_courses_own_verification_method_and_its_exact_code_admit_a_credit_record
    """
    provider = create_accredited_provider(name="Cedar Valley Bar CLE",
                                          provider_type="BAR_ASSOCIATION")
    course = create_self_certified_course(
        provider,
        title="Webcast Evidence Update",
        delivery_format="LIVE_WEBCAST",
        total_minutes=300,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 300)],
    )
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V11-0001",
                            "full_name": "Priya Raghunathan",
                            "admission_date": "2006-06-06T00:00:00Z"},
    )

    record = validate_success(
        post_credit_record(
            attorney, course["id"], verification_method="ATTENDANCE_CODE",
            attendance_code=course["attendance_code"], certificate_reference=None,
            attended_minutes=300, completion_date="2026-03-01T13:00:00Z",
        ),
        expected_status=201,
    )
    assert record["status"] == "VERIFIED"
    assert record["effective_format"] == "LIVE"
    assert record["credited_general_minutes"] == 300
    assert record["credited_minutes"] == 300
    assert read_course(course["id"])["verified_credit_record_count"] == 1
    assert len(list_credit_records(course_id=course["id"])) == 1

    settled = read_cycle(cycle["id"])
    assert settled["earned_countable_minutes"] == 300
    assert settled["earned_live_minutes"] == 300


def test_certification_without_any_affirmation_is_refused():
    """A `FINAL_COMPLIANCE_AFFIRMATION` must already exist against this cycle; certifying without one is `ERR_AFFIRMATION_REQUIRED`.
    The addressed cycle's `credit_status` must still be `OPEN`.
    Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp recorded at insertion. Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity.

    Design: Corner/validations/certification_is_refused_until_a_final_compliance_affirmation_exists
    """
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V14-0001", "full_name": "Helena Krogh",
                            "admission_date": "2003-03-03T00:00:00Z"},
    )
    assert cycle["credit_status"] == "OPEN"
    assert list_affirmations(cycle["id"]) == []

    validate_error(
        api_client.certify_cycle(
            cycle["id"], certification_payload(),
            make_attorney_headers(attorney["id"]),
        ),
        "ERR_AFFIRMATION_REQUIRED",
    )

    refused = read_cycle(cycle["id"])
    assert refused["credit_status"] == "OPEN"
    assert refused["certified_at"] is None
    assert_version_unchanged(cycle, refused)
    assert read_attorney(attorney["id"])["open_deficiency_count"] == 0


def test_a_self_study_affirmation_does_not_satisfy_the_certification_prerequisite():
    """A `FINAL_COMPLIANCE_AFFIRMATION` must already exist against this cycle; certifying without one is `ERR_AFFIRMATION_REQUIRED`.
    `SELF_STUDY_AFFIRMATION` attests to unverified self-study and targets nothing. `FINAL_COMPLIANCE_AFFIRMATION` is the sworn statement that the period is complete, and it is the prerequisite for certification.

    Design: Corner/validations/certification_is_refused_until_a_final_compliance_affirmation_exists
    """
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V14-0001", "full_name": "Helena Krogh",
                            "admission_date": "2003-03-03T00:00:00Z"},
    )
    self_study = file_affirmation(
        cycle["id"], attorney["id"], "SELF_STUDY_AFFIRMATION",
        statement="I affirm the self-study hours were completed as reported.",
    )
    assert self_study["affirmation_type"] == "SELF_STUDY_AFFIRMATION"
    assert len(list_affirmations(cycle["id"])) == 1

    # An affirmation now exists, but not the one the gate names.
    validate_error(
        api_client.certify_cycle(
            cycle["id"], certification_payload(),
            make_attorney_headers(attorney["id"]),
        ),
        "ERR_AFFIRMATION_REQUIRED",
    )

    refused = read_cycle(cycle["id"])
    assert refused["credit_status"] == "OPEN"
    assert refused["certified_at"] is None


def test_certification_after_the_final_affirmation_lands_on_deficient():
    """A `FINAL_COMPLIANCE_AFFIRMATION` must already exist against this cycle; certifying without one is `ERR_AFFIRMATION_REQUIRED`.
    The resulting `earned_countable_minutes`, `earned_ethics_minutes`, `earned_technology_minutes`, `earned_bias_minutes` and `earned_live_minutes` are frozen into the cycle, every credit record in the cycle has its `countable_minutes` rewritten to its final-variant value, and `certified_at` is stamped with the current logical instant.
    The four deficiency figures of that final run then decide the outcome, and the fork is exhaustive: if the total deficiency is zero **and** all three specialty deficiencies are zero, `credit_status` moves `OPEN → SATISFIED`; if the total deficiency is above zero **or** any one specialty deficiency is above zero, `credit_status` moves `OPEN → DEFICIENT` and the attorney's `open_deficiency_count` rises by one.
    A deficient certification writes both `carryover_out_general_minutes` and `carryover_out_ethics_minutes` as zero: a period that fell short never carries anything forward, however large its raw total.
    A full 24-month cycle therefore requires exactly 1800 minutes, and a shortened one requires a whole number of hours' worth of minutes and never a fraction of an hour.

    Design: Corner/validations/certification_is_refused_until_a_final_compliance_affirmation_exists
    """
    attorney, cycle = setup_attorney_with_cycle(
        "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        attorney_overrides={"bar_number": "V14-0001", "full_name": "Helena Krogh",
                            "admission_date": "2003-03-03T00:00:00Z"},
    )
    assert cycle["required_total_minutes"] == 1800
    assert cycle["earned_countable_minutes"] == 0

    file_affirmation(
        cycle["id"], attorney["id"], "SELF_STUDY_AFFIRMATION",
        statement="I affirm the self-study hours were completed as reported.",
    )
    file_affirmation(
        cycle["id"], attorney["id"], "FINAL_COMPLIANCE_AFFIRMATION",
        statement=FINAL_STATEMENT,
    )
    assert len(list_affirmations(cycle["id"])) == 2

    # The gate decides whether the filing happens, not whether it passes: a
    # cycle with no credit at all certifies straight onto DEFICIENT.
    certified = validate_success(
        api_client.certify_cycle(
            cycle["id"], certification_payload(),
            make_attorney_headers(attorney["id"]),
        ),
        expected_status=200,
    )
    assert certified["credit_status"] == "DEFICIENT"
    assert parse_instant(certified["certified_at"]) == parse_instant(CLOCK_START)
    assert certified["carryover_out_general_minutes"] == 0
    assert certified["carryover_out_ethics_minutes"] == 0
    assert read_cycle(cycle["id"])["credit_status"] == "DEFICIENT"
    assert read_attorney(attorney["id"])["open_deficiency_count"] == 1
