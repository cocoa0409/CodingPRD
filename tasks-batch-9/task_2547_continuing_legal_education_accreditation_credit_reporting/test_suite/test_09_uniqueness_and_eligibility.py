"""Uniqueness, cardinality and eligibility refusals across the CLE register.

Every test builds its own register from scratch through the endpoints the PRD
declares, because the database is empty and the logical clock reads
2026-08-01T00:00:00Z when each test begins.
"""
from datetime import datetime

from test_helpers import (
    api_client,
    factories as fac,
    fixtures as fx,
    make_attorney_headers,
    make_provider_admin_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)

BOARD = TEST_USERS["board_admin_headers"]


def _instant(value):
    """Parses an ISO 8601 UTC timestamp into a comparable datetime."""
    assert value and type(value) is str, f"expected a timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


# --- the bar number is unique on its own ----------------------------------

def test_a_second_attorney_with_the_same_bar_number_is_refused(api):
    """Board staff register an attorney with a `bar_number` (1 to 20 characters, required, and unique across the whole register — a collision is `ERR_DUPLICATE_BAR_NUMBER`), a `full_name` (1 to 200 characters), an `admission_date`, a `compliance_group`, and a `principal_office_jurisdiction` given as exactly two uppercase letters.

    Design: Corner/errors/a_second_attorney_with_the_same_bar_number_is_refused
    """
    original = validate_success(
        api.create_attorney(
            fac.create_attorney_payload(
                bar_number="DUP-7001",
                full_name="Original Registrant",
                admission_date="2000-01-01T00:00:00Z",
                compliance_group="GROUP_1",
                principal_office_jurisdiction="ST",
            ),
            BOARD,
        ),
        expected_status=201,
    )

    colliding = fac.create_attorney_payload(
        bar_number="DUP-7001",
        full_name="Different Person Entirely",
        admission_date="2019-09-09T00:00:00Z",
        compliance_group="GROUP_3",
        principal_office_jurisdiction="NY",
    )
    validate_error(
        api.create_attorney(colliding, BOARD),
        "ERR_DUPLICATE_BAR_NUMBER",
        expected_status=409,
    )

    # Every other field is identical to the refused body, so the bar number
    # alone carries the constraint.
    accepted_payload = dict(colliding, bar_number="DUP-7002")
    accepted = validate_success(
        api.create_attorney(accepted_payload, BOARD), expected_status=201
    )
    assert accepted["bar_number"] == "DUP-7002"
    assert accepted["id"] != original["id"]

    unchanged = fx.read_attorney(original["id"])
    assert unchanged["bar_number"] == "DUP-7001"
    assert unchanged["full_name"] == "Original Registrant", (
        "the refused create must overwrite nothing"
    )
    assert unchanged["version"] == original["version"]


# --- one live application per course --------------------------------------

def _setup_sponsor_with_two_pending_courses():
    provider = fx.create_probationary_provider(
        name="Twin Course Sponsors", provider_type="LAW_FIRM"
    )
    first = fx.create_self_certified_course(
        provider,
        title="First Pending Course",
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at="2026-08-15T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 180)],
    )
    second = fx.create_self_certified_course(
        provider,
        title="Second Pending Course",
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at="2026-08-16T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 180)],
    )
    return provider, first, second


def test_a_course_may_have_only_one_live_application_at_a_time(api):
    """Only one live application may exist per course, so if that course already has an application sitting in `SUBMITTED`, `INFO_REQUESTED` or `APPEALED`, the filing is rejected with `ERR_DUPLICATE_APPLICATION` — note that an application already in a terminal disposition does not block a re-filing.
    A nested collection also enforces containment: a sub-collection returns only rows belonging to the addressed parent, never a global list filtered client-side.
    Every other course is created in `PENDING_APPROVAL` and stays there until an application is decided; if it names a sponsor, only that sponsor's `courses_total_count` rises.

    Design: Corner/errors/a_course_may_have_only_one_live_application_at_a_time
    """
    provider, first, second = _setup_sponsor_with_two_pending_courses()
    sponsor_headers = make_provider_admin_headers(provider["id"])

    first_application = validate_success(
        api.create_course_application(first["id"], sponsor_headers),
        expected_status=201,
    )
    assert first_application["status"] == "SUBMITTED", first_application["status"]

    validate_error(
        api.create_course_application(first["id"], sponsor_headers),
        "ERR_DUPLICATE_APPLICATION",
        expected_status=409,
    )

    second_application = validate_success(
        api.create_course_application(second["id"], sponsor_headers),
        expected_status=201,
    )

    assert [row["id"] for row in fx.list_applications(first["id"])] == [
        first_application["id"]
    ]
    assert [row["id"] for row in fx.list_applications(second["id"])] == [
        second_application["id"]
    ]

    assert fx.read_course(first["id"])["status"] == "PENDING_APPROVAL"
    assert fx.read_course(second["id"])["status"] == "PENDING_APPROVAL"


# --- an audit whose window holds no eligible course -----------------------

def test_an_audit_with_no_eligible_course_in_its_window_cannot_draw_a_sample(api):
    """An empty pool *is* an error: the request is rejected with `ERR_NO_SAMPLE_POPULATION` and nothing at all is written, so `sampled_course_ids` stays empty, `sample_size` stays zero and `status` stays `OPENED`.
    The eligible pool is the audited provider's courses whose `status` is `APPROVED`, `EXPIRED` or `SUSPENDED_PENDING_REVIEW` and whose `presented_at` falls inside the audit's closed window, both endpoints included.
    A redraw recomputes the whole list from scratch rather than appending to it, and the provider's `courses_sampled_lifetime` is adjusted by the difference between the new and prior `sample_size` — on a first draw that difference is simply the new sample size.

    Design: Corner/errors/an_audit_with_no_eligible_course_in_its_window_cannot_draw_a_sample
    """
    provider = fx.create_accredited_provider(
        name="Off Window Academy", provider_type="LAW_SCHOOL"
    )
    course = fx.create_self_certified_course(
        provider,
        title="Next Year Recorded Programme",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2027-05-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 300)],
    )
    assert course["status"] == "APPROVED", course["status"]

    audit = fx.open_audit(
        provider["id"],
        audit_period_start="2026-01-01T00:00:00Z",
        audit_period_end="2026-12-31T00:00:00Z",
        trigger_type="RANDOM",
    )
    assert audit["status"] == "OPENED", audit["status"]

    for _attempt in range(2):
        validate_error(
            api.provider_audit_action(
                audit["id"],
                fac.audit_action_payload("DRAW_SAMPLE", audit["version"]),
                BOARD,
            ),
            "ERR_NO_SAMPLE_POPULATION",
            expected_status=409,
        )

    after = fx.read_audit(audit["id"])
    assert after["status"] == "OPENED", after["status"]
    assert after["sample_size"] == 0
    assert after["sampled_course_ids"] == []
    assert after["version"] == audit["version"], (
        "a refused draw must write nothing at all, including the version"
    )
    assert fx.read_provider(provider["id"])["courses_sampled_lifetime"] == 0
    # The course exists and is sampleable, just not inside the audited window.
    assert fx.read_course(course["id"])["status"] == "APPROVED"


# --- findings against the drawn sample ------------------------------------

def _setup_audit_sampled_over_two_courses():
    """A sponsor with two approved recorded courses inside a 2026 window and an
    audit that has drawn its sample over both."""
    provider = fx.create_accredited_provider(
        name="Two Course Sponsors", provider_type="GOVERNMENT"
    )
    spring = fx.create_self_certified_course(
        provider,
        title="Spring Recorded Seminar",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 300)],
    )
    autumn = fx.create_self_certified_course(
        provider,
        title="Autumn Recorded Seminar",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-10-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 300)],
    )
    audit = fx.open_audit(
        provider["id"],
        audit_period_start="2026-01-01T00:00:00Z",
        audit_period_end="2026-12-31T00:00:00Z",
        trigger_type="RANDOM",
    )
    sampled = fx.audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    return provider, spring, autumn, sampled


def test_findings_above_the_drawn_sample_size_are_refused(api):
    """The target size comes from the frozen score in three tiers: ten courses when `risk_score_at_open` is 0.60 or above, five when it is 0.30 or above but below 0.60, and two otherwise. `sample_size` is then the smaller of the target and the pool size — a pool smaller than the target simply yields a short sample and is not an error — and `sampled_course_ids` is the identifiers of the first `sample_size` entries of the sorted pool, in that order.
    The pool is ordered by `presented_at` ascending and then `created_at` ascending — never by identifier, and never randomly, so the same engagement over the same data always draws the same courses.
    **Findings and closure.** `ISSUE_FINDINGS` moves `SAMPLED → FINDINGS_ISSUED` and records a `findings_count` that must be at least zero and no greater than the audit's `sample_size`; more findings than courses examined is `ERR_FINDINGS_EXCEED_SAMPLE`.

    Design: Corner/errors/findings_cannot_exceed_the_sample_and_a_findings_heavy_audit_cannot_be_cleared
    """
    provider, spring, autumn, sampled = _setup_audit_sampled_over_two_courses()

    assert sampled["status"] == "SAMPLED", sampled["status"]
    assert sampled["sample_size"] == 2
    assert sampled["sampled_course_ids"] == [spring["id"], autumn["id"]]
    assert fx.read_provider(provider["id"])["courses_sampled_lifetime"] == 2

    validate_error(
        api.provider_audit_action(
            sampled["id"],
            fac.audit_action_payload(
                "ISSUE_FINDINGS", sampled["version"], findings_count=3
            ),
            BOARD,
        ),
        "ERR_FINDINGS_EXCEED_SAMPLE",
        expected_status=409,
    )
    after = fx.read_audit(sampled["id"])
    assert after["version"] == sampled["version"], (
        "a refused findings action must not bump the audit version"
    )
    assert after["status"] == "SAMPLED", after["status"]
    assert after["findings_count"] == 0


def test_a_two_finding_audit_cannot_be_cleared_but_can_be_sanctioned(api):
    """`CLOSE_CLEARED` requires `findings_count` of at most one, stamps `closed_at` with the current instant, sets `sanction_type` to `NONE`, writes that instant into the provider's `last_audit_closed_at` — which resets the staleness term of the score — and unlocks the sponsor's `PROBATIONARY → ACCREDITED` gate described in §3.1.
    The addressed resource is in a state from which the requested trigger is declared, and every cross-entity state precondition of that transition holds — otherwise `ERR_INVALID_STATE_TRANSITION` (409).
    `CLOSE_SANCTIONED` requires `findings_count` of at least one and a supplied `sanction_type` of `PROBATION` or `SUSPENSION`; it stamps `closed_at`, records the sanction, writes `last_audit_closed_at`, and assesses a `FeeAssessment` of `fee_type` `AUDIT_SANCTION` against the provider for 250000 cents.
    `PROBATION` then moves the provider `ACCREDITED → PROBATIONARY`; `SUSPENSION` moves it to `SUSPENDED` from either `ACCREDITED` or `PROBATIONARY`, which suspends that sponsor's self-certified courses, which in turn rejects those courses' credit records still awaiting verification — the same chain §3.1 describes.
    The count is added to the provider's `audit_findings_count` and the risk score is recomputed.
    Throughout all of this, `self_certification_enabled` is not an independent switch: it is true exactly when `accreditation_status` is `ACCREDITED`, and false in every other state.

    Design: Corner/errors/findings_cannot_exceed_the_sample_and_a_findings_heavy_audit_cannot_be_cleared
    """
    provider, _spring, _autumn, sampled = _setup_audit_sampled_over_two_courses()

    with_findings = validate_success(
        api.provider_audit_action(
            sampled["id"],
            fac.audit_action_payload(
                "ISSUE_FINDINGS", sampled["version"], findings_count=2
            ),
            BOARD,
        ),
        expected_status=200,
    )
    assert with_findings["status"] == "FINDINGS_ISSUED", with_findings["status"]
    assert with_findings["findings_count"] == 2
    assert fx.read_provider(provider["id"])["audit_findings_count"] == 2

    validate_error(
        api.provider_audit_action(
            sampled["id"],
            fac.audit_action_payload("CLOSE_CLEARED", with_findings["version"]),
            BOARD,
        ),
        "ERR_INVALID_STATE_TRANSITION",
        expected_status=409,
    )

    sanctioned = validate_success(
        api.provider_audit_action(
            sampled["id"],
            fac.audit_action_payload(
                "CLOSE_SANCTIONED",
                with_findings["version"],
                sanction_type="PROBATION",
            ),
            BOARD,
        ),
        expected_status=200,
    )
    assert sanctioned["status"] == "SANCTIONED", sanctioned["status"]
    assert sanctioned["sanction_type"] == "PROBATION"
    _same_instant(sanctioned["closed_at"], "2026-08-01T00:00:00Z", "the closing instant")

    provider_after = fx.read_provider(provider["id"])
    assert provider_after["accreditation_status"] == "PROBATIONARY", (
        provider_after["accreditation_status"]
    )
    assert provider_after["self_certification_enabled"] is False
    _same_instant(
        provider_after["last_audit_closed_at"], "2026-08-01T00:00:00Z",
        "the sponsor's most recent audit closing instant",
    )

    sanction_fees = fx.list_fee_assessments(
        provider_id=provider["id"], fee_type="AUDIT_SANCTION"
    )
    assert len(sanction_fees) == 1, sanction_fees
    assert sanction_fees[0]["status"] == "ASSESSED", sanction_fees[0]["status"]
    assert sanction_fees[0]["amount_cents"] == 250000


# --- a complaint seeds at most one audit ----------------------------------

def test_one_complaint_can_be_escalated_into_only_one_audit_ever(api):
    """Where that complaint reference is supplied, `trigger_type` must be `COMPLAINT_ESCALATION`, the named complaint must not already have `escalated` true — otherwise `ERR_COMPLAINT_ALREADY_ESCALATED` — and the complaint must resolve to the same provider the audit names, a mismatch being `ERR_COURSE_PROVIDER_MISMATCH`. Accepting the audit sets that complaint's `escalated` to true, so a single complaint can seed at most one audit.
    Two structural constraints apply. A provider may hold only one live engagement at a time: opening a second while an existing audit of that provider is in `OPENED`, `SAMPLED` or `FINDINGS_ISSUED` is `ERR_AUDIT_ENGAGEMENT_ACTIVE`. And audit windows of the same provider may neither overlap nor abut — because the audit window is closed at both ends, a new window whose start equals an existing window's end shares that instant and collides, giving `ERR_AUDIT_PERIOD_OVERLAP`.
    Against a provider, the provider's `substantiated_complaint_count` rises by one, its `risk_score` is recomputed, and the provider itself moves `ACCREDITED → PROBATIONARY`.
    The audit list accepts `provider_id`, `originating_complaint_id`, `status` and `trigger_type`.

    Design: Corner/errors/one_complaint_can_be_escalated_into_only_one_audit_ever
    """
    provider = fx.create_accredited_provider(
        name="Escalation Test Sponsors", provider_type="GOVERNMENT"
    )
    first_window_course = fx.create_self_certified_course(
        provider,
        title="First Window Programme",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 300)],
    )
    fx.create_self_certified_course(
        provider,
        title="Second Window Programme",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-09-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 300)],
    )
    complaint = fx.file_complaint(
        "PROVIDER", provider["id"],
        filer_user_id="board-intake-11",
        allegation="Attendance records for the spring programme cannot be produced.",
        allegation_category="ATTENDANCE_FRAUD",
    )
    fx.substantiate_complaint(
        complaint["id"],
        disposer_user_id="board-review-12",
        disposition_reason="The sponsor produced no roster for the audited session.",
    )

    first_audit = fx.open_audit(
        provider["id"],
        audit_period_start="2026-01-01T00:00:00Z",
        audit_period_end="2026-06-30T00:00:00Z",
        trigger_type="COMPLAINT_ESCALATION",
        originating_complaint_id=complaint["id"],
    )
    spent = fx.read_complaint(complaint["id"])
    assert spent["status"] == "SUBSTANTIATED", spent["status"]
    assert spent["escalated"] is True

    sampled = fx.audit_action(first_audit["id"], "DRAW_SAMPLE", first_audit["version"])
    assert sampled["sample_size"] == 1
    assert sampled["sampled_course_ids"] == [first_window_course["id"]], (
        "only the first-window course sits inside the audited window"
    )
    with_findings = fx.audit_action(
        sampled["id"], "ISSUE_FINDINGS", sampled["version"], findings_count=0
    )
    cleared = fx.audit_action(
        with_findings["id"], "CLOSE_CLEARED", with_findings["version"]
    )
    assert cleared["status"] == "CLEARED", cleared["status"]
    assert cleared["sanction_type"] == "NONE", cleared["sanction_type"]
    assert cleared["closed_at"], "a cleared engagement stamps its closing instant"

    # The later window neither overlaps nor abuts the closed one, and the first
    # engagement is terminal, so only the spent complaint can explain this.
    validate_error(
        api.create_provider_audit(
            fac.create_provider_audit_payload(
                provider["id"],
                audit_period_start="2026-08-01T00:00:00Z",
                audit_period_end="2026-12-31T00:00:00Z",
                trigger_type="COMPLAINT_ESCALATION",
                originating_complaint_id=complaint["id"],
            ),
            BOARD,
        ),
        "ERR_COMPLAINT_ALREADY_ESCALATED",
        expected_status=409,
    )

    second_audit = validate_success(
        api.create_provider_audit(
            fac.create_provider_audit_payload(
                provider["id"],
                audit_period_start="2026-08-01T00:00:00Z",
                audit_period_end="2026-12-31T00:00:00Z",
                trigger_type="RISK_BASED",
            ),
            BOARD,
        ),
        expected_status=201,
    )
    assert second_audit["originating_complaint_id"] is None

    escalated_audits = fx.list_audits(originating_complaint_id=complaint["id"])
    assert [row["id"] for row in escalated_audits] == [first_audit["id"]]
    assert {row["id"] for row in fx.list_audits(provider_id=provider["id"])} == {
        first_audit["id"], second_audit["id"],
    }

    provider_after = fx.read_provider(provider["id"])
    assert provider_after["accreditation_status"] == "PROBATIONARY", (
        provider_after["accreditation_status"]
    )
    assert provider_after["substantiated_complaint_count"] == 1
    assert provider_after["courses_sampled_lifetime"] == 1


# --- the three-part comity gate -------------------------------------------

def _setup_new_york_attorney_with_two_comity_claims():
    attorney = fx.create_attorney(
        bar_number="CMT-8001",
        full_name="Yuki Tanaka",
        admission_date="2002-02-02T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="NY",
    )
    cycle = fx.create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    texan = fx.file_reciprocity_claim(
        attorney["id"],
        basis="COMITY",
        origin_jurisdiction="TX",
        origin_course_title="Texas Full Compliance Certificate",
        origin_credit_hours=15.0,
        origin_category="GENERAL",
        completion_date="2026-05-01T00:00:00Z",
    )
    illinoisan = fx.file_reciprocity_claim(
        attorney["id"],
        basis="COMITY",
        origin_jurisdiction="IL",
        origin_course_title="Illinois Full Compliance Certificate",
        origin_credit_hours=15.0,
        origin_category="GENERAL",
        completion_date="2026-06-01T00:00:00Z",
    )
    return attorney, cycle, texan, illinoisan


def _assert_comity_refusal_left_no_trace(attorney, cycle, claims):
    filed = validate_success(
        api_client.list_attorney_reciprocity_claims(
            attorney["id"], make_attorney_headers(attorney["id"])
        ),
        expected_status=200,
    )
    stored_by_id = {row["id"]: row for row in filed}
    for claim in claims:
        stored = stored_by_id[claim["id"]]
        assert stored["status"] == "SUBMITTED", stored["status"]
        assert stored["converted_minutes"] == 0
        assert stored["determination_reason"] is None
    cycle_after = fx.read_cycle(cycle["id"])
    assert cycle_after["credit_status"] == "OPEN", cycle_after["credit_status"]
    assert cycle_after["comity_claim_id"] is None
    assert cycle_after["version"] == cycle["version"]
    assert fx.list_credit_records(attorney_id=attorney["id"]) == []


def test_comity_from_a_jurisdiction_outside_the_comity_list_is_refused(api):
    """Instead it must pass a three-part jurisdiction gate, every part of which reports `ERR_COMITY_NOT_AVAILABLE` on failure: the claim's `origin_jurisdiction` must be one of the two comity jurisdictions `NY` or `IL`; the attorney's `principal_office_jurisdiction` must equal that same jurisdiction; and that jurisdiction must not be the home code `ST`.
    **The comity pathway.** Approval on the `COMITY` basis grants no minutes at all — `converted_minutes` stays 0 and `converted_category` stays at its `GENERAL` default, unused — and creates no credit record.

    Design: Corner/errors/comity_is_available_only_from_a_comity_jurisdiction_that_is_the_attorneys_own
    """
    attorney, cycle, texan, illinoisan = _setup_new_york_attorney_with_two_comity_claims()

    # TX is a reciprocity jurisdiction but not a comity jurisdiction.
    validate_error(
        api.reciprocity_claim_determination(
            texan["id"], fac.determination_payload("APPROVE"), BOARD
        ),
        "ERR_COMITY_NOT_AVAILABLE",
        expected_status=409,
    )
    _assert_comity_refusal_left_no_trace(attorney, cycle, [texan, illinoisan])


def test_comity_from_a_comity_jurisdiction_that_is_not_the_attorneys_own_is_refused(api):
    """Instead it must pass a three-part jurisdiction gate, every part of which reports `ERR_COMITY_NOT_AVAILABLE` on failure: the claim's `origin_jurisdiction` must be one of the two comity jurisdictions `NY` or `IL`; the attorney's `principal_office_jurisdiction` must equal that same jurisdiction; and that jurisdiction must not be the home code `ST`.
    In other words, comity is available only to an attorney whose principal office genuinely sits in a recognised comity jurisdiction outside this state.

    Design: Corner/errors/comity_is_available_only_from_a_comity_jurisdiction_that_is_the_attorneys_own
    """
    attorney, cycle, texan, illinoisan = _setup_new_york_attorney_with_two_comity_claims()

    # IL is a comity jurisdiction, but this attorney's principal office is NY.
    validate_error(
        api.reciprocity_claim_determination(
            illinoisan["id"], fac.determination_payload("APPROVE"), BOARD
        ),
        "ERR_COMITY_NOT_AVAILABLE",
        expected_status=409,
    )
    _assert_comity_refusal_left_no_trace(attorney, cycle, [texan, illinoisan])


# --- reciprocity only from a listed jurisdiction ---------------------------

def _file_claim_response(attorney_id, **overrides):
    """Files an out-of-state claim, reading the attorney's live version first so
    the concurrency guard carries the value the board expects."""
    live = fx.read_attorney(attorney_id)
    payload = fac.create_reciprocity_claim_payload(
        attorney_id, live["version"], **overrides
    )
    return api_client.create_reciprocity_claim(
        payload, make_attorney_headers(attorney_id)
    )


def _setup_two_reciprocity_claims():
    attorney = fx.create_attorney(
        bar_number="RCP-8101",
        full_name="Declan Moore",
        admission_date="2002-03-03T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = fx.create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    ohio_response = _file_claim_response(
        attorney["id"],
        basis="RECIPROCITY",
        origin_jurisdiction="OH",
        origin_course_title="Ohio Professional Conduct Seminar",
        origin_credit_hours=2.0,
        origin_category="ETHICS",
        completion_date="2026-05-01T00:00:00Z",
    )
    californian_response = _file_claim_response(
        attorney["id"],
        basis="RECIPROCITY",
        origin_jurisdiction="CA",
        origin_course_title="California Professional Responsibility Intensive",
        origin_credit_hours=3.0,
        origin_category="PROFESSIONALISM",
        completion_date="2026-07-01T00:00:00Z",
    )
    return attorney, cycle, ohio_response, californian_response


def test_a_reciprocity_claim_from_an_unlisted_jurisdiction_is_refused(api):
    """A new claim is created in `SUBMITTED` with `converted_minutes` at zero, `converted_category` at `GENERAL` and `determination_reason` null, and the act of filing raises the attorney's own `version` by one.
    **The reciprocity pathway.** Approval on the `RECIPROCITY` basis first checks that the `origin_jurisdiction` is one the board has a reciprocal arrangement with — `NY`, `CA`, `TX`, `IL` or `FL`. Anything else is `ERR_JURISDICTION_NOT_RECIPROCAL`.

    Design: Corner/errors/a_reciprocity_claim_from_an_unlisted_jurisdiction_is_refused
    """
    attorney, _cycle, ohio_response, _californian = _setup_two_reciprocity_claims()

    # Filing does not consult the list of reciprocal jurisdictions.
    ohio = validate_success(ohio_response, expected_status=201)
    assert ohio["status"] == "SUBMITTED", ohio["status"]
    assert ohio["converted_minutes"] == 0

    validate_error(
        api.reciprocity_claim_determination(
            ohio["id"], fac.determination_payload("APPROVE"), BOARD
        ),
        "ERR_JURISDICTION_NOT_RECIPROCAL",
        expected_status=409,
    )

    filed = validate_success(
        api.list_attorney_reciprocity_claims(
            attorney["id"], make_attorney_headers(attorney["id"])
        ),
        expected_status=200,
    )
    stored = {row["id"]: row for row in filed}[ohio["id"]]
    assert stored["status"] == "SUBMITTED", stored["status"]
    assert stored["converted_minutes"] == 0
    assert fx.list_credit_records(reciprocity_claim_id=ohio["id"]) == []


def test_a_claim_from_a_listed_jurisdiction_converts_on_the_same_call_pattern(api):
    """Conversion then accounts for the fact that an "hour" is not the same length everywhere: `NY` and `FL` award credit in 50-minute hours, while `CA`, `TX` and `IL` use 60-minute hours. The origin minutes are `origin_credit_hours` multiplied by the origin jurisdiction's hour length, and `converted_minutes` is that product rounded **down** to a whole multiple of 15 minutes.
    `converted_category` is the home category the origin label maps onto: `GENERAL` stays `GENERAL`, both `PROFESSIONALISM` and `ETHICS` map to `ETHICS`, `TECHNOLOGY` stays `TECHNOLOGY`, and `DIVERSITY_INCLUSION` maps to `BIAS_ELIMINATION`.
    Its credited minutes for the mapped category equal `converted_minutes`, and its `credited_minutes` equals `converted_minutes` as well, the other three category figures being zero.

    Design: Corner/errors/a_reciprocity_claim_from_an_unlisted_jurisdiction_is_refused
    """
    _attorney, cycle, _ohio_response, californian_response = (
        _setup_two_reciprocity_claims()
    )
    californian = validate_success(californian_response, expected_status=201)

    approved = validate_success(
        api.reciprocity_claim_determination(
            californian["id"], fac.determination_payload("APPROVE"), BOARD
        ),
        expected_status=200,
    )
    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["converted_minutes"] == 180
    assert approved["converted_category"] == "ETHICS", approved["converted_category"]

    cascaded = fx.list_credit_records(reciprocity_claim_id=californian["id"])
    assert len(cascaded) == 1, cascaded
    assert cascaded[0]["status"] == "VERIFIED", cascaded[0]["status"]
    assert cascaded[0]["source"] == "RECIPROCITY", cascaded[0]["source"]
    assert cascaded[0]["credited_ethics_minutes"] == 180
    assert cascaded[0]["credited_minutes"] == 180

    cycle_after = fx.read_cycle(cycle["id"])
    assert cycle_after["earned_ethics_minutes"] == 180
    assert cycle_after["earned_countable_minutes"] == 180


# --- the fiscal gate on reinstatement -------------------------------------

def _setup_admin_suspended_attorney(api):
    """Advances the clock past the filing deadline and then past the suspension
    interval, running the batch run at each stop. Returns the attorney, the
    cycle and the two runs."""
    attorney = fx.create_attorney(
        bar_number="FEE-9001",
        full_name="Ingrid Halvorsen",
        admission_date="2000-01-01T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = fx.create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    fx.set_clock("2028-02-01T00:00:00Z")
    first_run = validate_success(
        api.create_reporting_sweep(BOARD), expected_status=201
    )
    fx.set_clock("2028-04-05T00:00:00Z")
    second_run = validate_success(
        api.create_reporting_sweep(BOARD), expected_status=201
    )
    return attorney, cycle, first_run, second_run


def test_the_batch_run_suspends_and_reinstatement_is_refused_on_a_live_balance(api):
    """The first: a cycle whose `administrative_status` is `GOOD_STANDING`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `filing_deadline` is at or before the run's `as_of`, moves `administrative_status` from `GOOD_STANDING` to `DELINQUENT`.
    Compliance cycles are examined in `filing_deadline` ascending and then `created_at` ascending order, which makes the run reproducible and makes the ordering of the assessments it creates deterministic. `cycles_examined` counts the cycles the run considered.
    Step five picks a base amount from the rounded hour count: zero hours gives 15000 cents, one to five hours gives 25000, six to fifteen gives 40000, and sixteen or more gives 60000. Step six adds a surcharge of 2500 cents for each deficient hour, counting at most twenty hours. Step seven caps the total: `amount_cents` is the smaller of 100000 cents and the base plus surcharge.
    **Suspension.** The second enforcement step: a cycle whose `administrative_status` is `DELINQUENT`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `delinquent_since` is at least 60 days before the run's `as_of`, moves `administrative_status` from `DELINQUENT` to `ADMIN_SUSPENDED`.
    The run's `suspensions_issued` rises by one and its `late_fees_assessed_cents` rises by the reinstatement amount as well — that tally is the run's total money assessed, not its late-fee money alone.
    Both bases require the attorney's `status` to be `ADMIN_SUSPENDED` and require the attorney's `outstanding_fee_cents` to be exactly zero — every assessment paid, waived or voided — and a non-zero balance is rejected with `ERR_OUTSTANDING_FEE_BALANCE`, which is evaluated after every other check in the order of §2.8.

    Design: Corner/errors/reinstatement_is_refused_while_any_assessment_is_still_outstanding
    """
    attorney, cycle, first_run, second_run = _setup_admin_suspended_attorney(api)

    assert first_run["sweep_number"] == 1
    _same_instant(first_run["as_of"], "2028-02-01T00:00:00Z", "the first run's instant")
    assert first_run["cycles_examined"] == 1
    assert first_run["delinquencies_issued"] == 1
    assert first_run["suspensions_issued"] == 0
    # Deficiency 1800 + 180 + 60 + 120 = 2160 minutes, 36 hours: base 60000 plus
    # a twenty-hour-capped surcharge of 50000, trimmed by the overall ceiling.
    assert first_run["late_fees_assessed_cents"] == 100000

    assert second_run["sweep_number"] == 2
    _same_instant(second_run["as_of"], "2028-04-05T00:00:00Z", "the second run's instant")
    assert second_run["cycles_examined"] == 1
    assert second_run["delinquencies_issued"] == 0
    assert second_run["suspensions_issued"] == 1
    assert second_run["late_fees_assessed_cents"] == 50000

    suspended_cycle = fx.read_cycle(cycle["id"])
    assert suspended_cycle["administrative_status"] == "ADMIN_SUSPENDED", (
        suspended_cycle["administrative_status"]
    )
    _same_instant(
        suspended_cycle["delinquent_since"], "2028-02-01T00:00:00Z",
        "the delinquency instant",
    )

    suspended_attorney = fx.read_attorney(attorney["id"])
    assert suspended_attorney["status"] == "ADMIN_SUSPENDED", (
        suspended_attorney["status"]
    )
    assert suspended_attorney["outstanding_fee_cents"] == 150000

    validate_error(
        api.attorney_reinstatement(
            attorney["id"],
            fac.reinstatement_payload(
                cycle["id"], cure_basis="BOARD_ORDER",
                reason="Board order of 2028-04-05.",
            ),
            BOARD,
        ),
        "ERR_OUTSTANDING_FEE_BALANCE",
        expected_status=402,
    )
    assert fx.read_attorney(attorney["id"])["outstanding_fee_cents"] == 150000
    assert fx.read_cycle(cycle["id"])["administrative_status"] == "ADMIN_SUSPENDED"


def test_reinstatement_needs_a_zero_balance_not_merely_progress(api):
    """Both bases require the attorney's `status` to be `ADMIN_SUSPENDED` and require the attorney's `outstanding_fee_cents` to be exactly zero — every assessment paid, waived or voided — and a non-zero balance is rejected with `ERR_OUTSTANDING_FEE_BALANCE`, which is evaluated after every other check in the order of §2.8.
    Either action stamps `settled_at` with the current instant, moves `status` to `PAID` or `WAIVED` accordingly, and — when the assessment names an `attorney_id` — lowers that attorney's `outstanding_fee_cents` by exactly this assessment's `amount_cents`.
    On success the named cycle moves `administrative_status` from `ADMIN_SUSPENDED` to `REINSTATED` and its `delinquent_since` returns to null, and the attorney's `status` moves `ADMIN_SUSPENDED → ACTIVE`. Under `FEES_AND_CREDITS_CURED` the cycle's `credit_status` also moves to `SATISFIED`, since the cure evaluation just proved the requirement met; under `BOARD_ORDER` the `credit_status` is left exactly as it was, so a reinstated attorney may perfectly well hold a cycle that is `REINSTATED` and `DEFICIENT` at the same time.
    Action endpoints return the resource they acted upon, so a certification returns the updated compliance cycle and a settlement returns the settled assessment; reinstatement is the one exception, returning the reinstated `Attorney` rather than the cycle named in its body.

    Design: Corner/errors/reinstatement_is_refused_while_any_assessment_is_still_outstanding
    """
    attorney, cycle, _first_run, _second_run = _setup_admin_suspended_attorney(api)
    cure = fac.reinstatement_payload(
        cycle["id"], cure_basis="BOARD_ORDER", reason="Board order of 2028-04-05."
    )

    late_fees = fx.list_fee_assessments(
        attorney_id=attorney["id"], fee_type="LATE_COMPLIANCE"
    )
    assert len(late_fees) == 1, late_fees
    assert late_fees[0]["amount_cents"] == 100000
    validate_success(
        api.fee_settlement(
            late_fees[0]["id"],
            fac.settlement_payload("PAY"),
            make_attorney_headers(attorney["id"]),
        ),
        expected_status=200,
    )
    assert fx.read_attorney(attorney["id"])["outstanding_fee_cents"] == 50000

    # The gate demands a zero balance, not merely progress towards one.
    validate_error(
        api.attorney_reinstatement(attorney["id"], cure, BOARD),
        "ERR_OUTSTANDING_FEE_BALANCE",
        expected_status=402,
    )

    reinstatement_fees = fx.list_fee_assessments(
        attorney_id=attorney["id"], fee_type="REINSTATEMENT"
    )
    assert len(reinstatement_fees) == 1, reinstatement_fees
    assert reinstatement_fees[0]["amount_cents"] == 50000
    validate_success(
        api.fee_settlement(
            reinstatement_fees[0]["id"],
            fac.settlement_payload("PAY"),
            make_attorney_headers(attorney["id"]),
        ),
        expected_status=200,
    )

    reinstated = validate_success(
        api.attorney_reinstatement(attorney["id"], cure, BOARD),
        expected_status=200,
    )
    assert reinstated["id"] == attorney["id"], (
        "reinstatement answers with the attorney, not the cycle"
    )
    assert reinstated["status"] == "ACTIVE", reinstated["status"]
    assert reinstated["outstanding_fee_cents"] == 0

    cured_cycle = fx.read_cycle(cycle["id"])
    assert cured_cycle["administrative_status"] == "REINSTATED", (
        cured_cycle["administrative_status"]
    )
    assert cured_cycle["delinquent_since"] is None
    assert cured_cycle["credit_status"] == "OPEN", (
        "a BOARD_ORDER cure leaves the credit picture exactly as it was"
    )

    for settled in fx.list_fee_assessments(attorney_id=attorney["id"]):
        assert settled["status"] == "PAID", settled
        _same_instant(
            settled["settled_at"], "2028-04-05T00:00:00Z", "the settlement instant"
        )
    assert fx.list_fee_assessments(
        attorney_id=attorney["id"], status="ASSESSED"
    ) == []
