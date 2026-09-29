"""Validation corners: numeric bounds, composite uniqueness keys, configuration-keyed
conditions, the disclosure-safety cascade and the all-or-nothing review pass."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant, assert_event_count, assert_page_ledger
from test_helpers.test_users import ANALYST_1, INTAKE_1, PLATFORM_ADMIN, REVIEWER_1


def test_a_redaction_one_page_over_the_segment_is_refused_and_equality_is_accepted(api):
    """41 of 40 pages is a 422; 40 of 40 is legal and zeroes the billable count on approval.

    PRD: "A `redacted_page_count` strictly greater than `page_count` is refused with `ERR_REDACTION_PAGE_COUNT_INVALID`; a `redacted_page_count` exactly equal to `page_count` is accepted and leaves that segment contributing zero billable pages."

    Design: Corner/validations/redaction_page_count_above_segment_page_count_rejected
    """
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"]
    )
    ids = fx.walk_to_sensitive_review(
        api, request["id"], [{"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 40}]
    )
    fx.run_sensitive_review(
        api, request["id"], [f.include_decision(ids["bh"], redaction_required=True)]
    )
    assert fx.read_request(api, request["id"])["fulfillment_status"] == "REDACTION"
    before = fx.read_segment(api, ids["bh"])
    assert before["sensitivity_status"] == "AUTHORIZED_INCLUDE"
    assert before["redaction_status"] == "OPEN"

    validate_error(
        api.apply_redaction(ids["bh"], f.redaction_payload(41), ANALYST_1),
        e.ERR_REDACTION_PAGE_COUNT_INVALID,
        422,
    )
    rejected = fx.read_segment(api, ids["bh"])
    assert rejected["redaction_status"] == "OPEN"
    assert rejected["redacted_page_count"] == 0

    applied = validate_success(
        api.apply_redaction(ids["bh"], f.redaction_payload(40), ANALYST_1), 200
    )
    assert applied["redaction_status"] == "APPLIED"
    assert applied["redacted_page_count"] == 40
    assert_page_ledger(
        fx.read_request(api, request["id"]), total=40, billable=40, withheld=0, redacted=0
    )

    fx.approve_redaction(api, ids["bh"])
    approved = fx.read_request(api, request["id"])
    assert_page_ledger(approved, total=40, billable=0, withheld=0, redacted=40)
    assert approved["fulfillment_status"] == "RELEASE_READY"


def test_the_mrn_uniqueness_key_is_the_pair_not_the_mrn_alone(api):
    """The same MRN is a 409 at one facility and a 201 at the next.

    PRD: "The pair of `facility_id` and `mrn` must be unique: repeating it is refused with `ERR_DUPLICATE_MRN`."

    Design: Corner/validations/duplicate_mrn_is_scoped_to_one_facility_rejected
    """
    fx.set_clock(api)
    fee_rule = fx.make_fee_rule(api)
    facility_a = fx.make_facility(api, fee_rule["id"])
    facility_b = fx.make_facility(api, fee_rule["id"])
    patient_a = fx.make_patient(api, facility_a["id"], mrn="MRN-3001")

    validate_error(
        api.create_patient(
            f.patient_payload(facility_a["id"], mrn="MRN-3001", full_name="Someone Else"),
            PLATFORM_ADMIN,
        ),
        e.ERR_DUPLICATE_MRN,
        409,
    )

    twin = validate_success(
        api.create_patient(f.patient_payload(facility_b["id"], mrn="MRN-3001"), PLATFORM_ADMIN),
        201,
    )
    assert twin["id"] != patient_a["id"]

    _, scoped = validate_paginated(
        api.list_patients(
            PLATFORM_ADMIN, {"facility_id": facility_a["id"], "mrn": "MRN-3001", "limit": 10}
        )
    )
    assert scoped["total_count"] == 1
    _, across = validate_paginated(
        api.list_patients(PLATFORM_ADMIN, {"mrn": "MRN-3001", "limit": 10})
    )
    assert across["total_count"] == 2


def _accepted_request_at(api, fee_rule_id, **facility_overrides):
    """One accepted third-party request on a facility configured as asked."""
    facility = fx.make_facility(api, fee_rule_id, **facility_overrides)
    patient = fx.make_patient(api, facility["id"])
    attorney = fx.make_attorney(api)
    authorization = fx.make_authorization(api, patient["id"], attorney["id"])
    request = get_success_data(
        api.create_request(
            f.third_party_request_payload(
                facility["id"], patient["id"], attorney["id"], authorization["id"]
            ),
            INTAKE_1,
        )
    )
    fx.accept_request(api, request["id"])
    return {"facility": facility, "request_id": request["id"]}


def test_the_legacy_flag_gates_only_the_legacy_source_system(api):
    """The identical body is a 422 at the defaulted facility and a 201 at the enabled one.

    PRD: "A legacy segment may only be opened when the governing facility's `legacy_archive_enabled` is true; otherwise the creation is refused with `ERR_LEGACY_ARCHIVE_DISABLED`."

    Design: Corner/validations/legacy_archive_segment_on_facility_without_the_flag_rejected
    """
    fx.set_clock(api)
    fee_rule = fx.make_fee_rule(api)
    disabled = _accepted_request_at(
        api, fee_rule["id"], legacy_archive_enabled=False, legacy_retrieval_surcharge_cents=0
    )
    enabled = _accepted_request_at(api, fee_rule["id"])

    facility = disabled["facility"]
    assert facility["legacy_archive_enabled"] is False
    assert facility["legacy_retrieval_surcharge_cents"] == 0
    assert facility["legacy_gateway_job_minutes"] == 30
    assert facility["legacy_gateway_buffer_minutes"] == 10

    legacy_body = f.record_segment_payload(
        disabled["request_id"],
        "GENERAL_MEDICAL",
        "LEGACY_ARCHIVE",
        legacy_job_start_at="2026-08-03T09:00:00Z",
    )
    validate_error(
        api.create_record_segment(legacy_body, ANALYST_1), e.ERR_LEGACY_ARCHIVE_DISABLED, 422
    )

    validate_success(
        api.create_record_segment(
            f.record_segment_payload(disabled["request_id"], "GENERAL_MEDICAL", "EHR_CURRENT"),
            ANALYST_1,
        ),
        201,
    )

    job = validate_success(
        api.create_record_segment(
            f.record_segment_payload(
                enabled["request_id"],
                "GENERAL_MEDICAL",
                "LEGACY_ARCHIVE",
                legacy_job_start_at="2026-08-03T09:00:00Z",
            ),
            ANALYST_1,
        ),
        201,
    )
    assert job["legacy_job_start_at"] == Instant("2026-08-03T09:00:00Z")
    assert job["legacy_job_end_at"] == Instant("2026-08-03T09:30:00Z")

    _, meta = fx.list_segments_for(api, disabled["request_id"])
    assert meta["total_count"] == 1


def test_an_amendment_needs_both_a_released_parent_and_a_retrieved_segment(api):
    """RELEASE_READY is not released, and a released parent does not rescue a missing segment.

    PRD: "The target must actually have been disclosed: if the parent request's `released_at` is still null, or the named segment's `retrieval_status` is anything other than `RETRIEVED`, the submission is refused with `ERR_AMENDMENT_TARGET_NOT_RELEASED`."

    Design: Corner/validations/amendment_request_before_release_rejected
    """
    world = fx.patient_access_world(api)
    unreleased = fx.simple_patient_access_request_at_release_ready(
        api, world, 10, date_range_start="2022-01-01", date_range_end="2022-12-31"
    )
    released_request = fx.open_patient_access_request(api, world)
    ids = fx.walk_to_sensitive_review(
        api,
        released_request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 10},
            {
                "label": "gone",
                "category": "GENERAL_MEDICAL",
                "page_count": 0,
                "source_system": "SCANNED_PAPER",
                "disposition": "UNAVAILABLE",
            },
        ],
    )
    fx.run_sensitive_review(api, released_request["id"], [])
    invoice = fx.invoice_and_pay(api, released_request["id"])
    assert invoice["amount_due_cents"] == 100
    fx.release_request(api, released_request["id"])
    assert fx.read_request(api, unreleased["request_id"])["released_at"] is None

    validate_error(
        api.create_amendment_request(
            f.amendment_payload(
                unreleased["request_id"],
                world["patient_id"],
                unreleased["segment_ids"]["gen"],
            ),
            world["requester_headers"],
        ),
        e.ERR_AMENDMENT_TARGET_NOT_RELEASED,
        422,
    )
    validate_error(
        api.create_amendment_request(
            f.amendment_payload(released_request["id"], world["patient_id"], ids["gone"]),
            world["requester_headers"],
        ),
        e.ERR_AMENDMENT_TARGET_NOT_RELEASED,
        422,
    )

    amendment = validate_success(
        api.create_amendment_request(
            f.amendment_payload(released_request["id"], world["patient_id"], ids["gen"]),
            world["requester_headers"],
        ),
        201,
    )
    assert amendment["status"] == "SUBMITTED"
    assert amendment["submission_count"] == 1
    assert amendment["decision_due_at"].startswith("2026-09-30T00:00:00")


def test_psychotherapy_notes_are_barred_even_when_the_authorization_names_them(api):
    """Priorities 21 and 22 are satisfied, so the 422 can only be the outright bar at 20.

    PRD: "First, a segment whose `category` is `PSYCHOTHERAPY_NOTES` may never be included: psychotherapy notes are excluded from the right of access outright and no authorization can unlock them, so the decision is refused with `ERR_PSYCHOTHERAPY_NOTES_NOT_RELEASABLE`."

    Design: Corner/validations/psychotherapy_notes_include_decision_rejected
    """
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "PSYCHOTHERAPY_NOTES"],
        sensitive_categories_authorized=["PSYCHOTHERAPY_NOTES"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "PSYCHOTHERAPY_NOTES"]
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 30},
            {"label": "psy", "category": "PSYCHOTHERAPY_NOTES", "page_count": 8},
        ],
    )
    assert fx.read_segment(api, ids["gen"])["sensitivity_status"] == "NOT_SENSITIVE"
    assert fx.read_segment(api, ids["psy"])["sensitivity_status"] == "SEGREGATED_PENDING_REVIEW"
    version_before = fx.read_request(api, request["id"])["version"]

    validate_error(
        api.sensitive_review(
            request["id"], f.sensitive_review_payload([f.include_decision(ids["psy"])]), REVIEWER_1
        ),
        e.ERR_PSYCHOTHERAPY_NOTES_NOT_RELEASABLE,
        422,
    )
    stalled = fx.read_request(api, request["id"])
    assert stalled["fulfillment_status"] == "SENSITIVE_REVIEW"
    assert stalled["version"] == version_before
    assert fx.read_segment(api, ids["psy"])["sensitivity_status"] == "SEGREGATED_PENDING_REVIEW"

    validate_success(
        api.sensitive_review(
            request["id"], f.sensitive_review_payload([f.withhold_decision(ids["psy"])]), REVIEWER_1
        ),
        200,
    )

    assert fx.read_segment(api, ids["psy"])["sensitivity_status"] == "WITHHELD"
    final = fx.read_request(api, request["id"])
    assert final["fulfillment_status"] == "RELEASE_READY"
    assert_page_ledger(final, total=38, billable=30, withheld=8, redacted=0)
    assert_event_count(fx.read_events(api, request["id"]), "SENSITIVE_WITHHOLD", 1)


def test_the_coverage_rule_is_reached_before_the_part_two_acknowledgement_rule(api):
    """Both rules are violated at once and the earlier one answers; withholding HIV unmasks 22.

    PRD: "The cascade matters: because the category-coverage rule is evaluated before the Part 2 acknowledgement rule, a `SUD_PART2` segment that is *also* outside `sensitive_categories_authorized` reports the coverage failure, not the missing acknowledgement."

    Design: Corner/validations/part2_include_reports_authorization_scope_before_missing_ack_rejected
    """
    world = fx.third_party_world(
        api,
        scope_categories=["HIV", "SUD_PART2"],
        sensitive_categories_authorized=["SUD_PART2"],
    )
    assert world["authorization"]["part2_redisclosure_prohibition_ack"] is False
    request = fx.open_third_party_request(
        api, world, requested_categories=["HIV", "SUD_PART2"]
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "hiv", "category": "HIV", "page_count": 11},
            {"label": "sud", "category": "SUD_PART2", "page_count": 12},
        ],
    )
    version_before = fx.read_request(api, request["id"])["version"]

    validate_error(
        api.sensitive_review(
            request["id"],
            f.sensitive_review_payload(
                [f.include_decision(ids["hiv"]), f.include_decision(ids["sud"])]
            ),
            REVIEWER_1,
        ),
        e.ERR_SENSITIVE_CATEGORY_NOT_AUTHORIZED,
        422,
    )
    validate_error(
        api.sensitive_review(
            request["id"],
            f.sensitive_review_payload(
                [f.withhold_decision(ids["hiv"]), f.include_decision(ids["sud"])]
            ),
            REVIEWER_1,
        ),
        e.ERR_PART2_ACK_MISSING,
        422,
    )

    for label in ("hiv", "sud"):
        assert fx.read_segment(api, ids[label])["sensitivity_status"] == (
            "SEGREGATED_PENDING_REVIEW"
        )
    assert fx.read_request(api, request["id"])["version"] == version_before

    validate_success(
        api.sensitive_review(
            request["id"],
            f.sensitive_review_payload(
                [f.withhold_decision(ids["hiv"]), f.withhold_decision(ids["sud"])]
            ),
            REVIEWER_1,
        ),
        200,
    )
    final = fx.read_request(api, request["id"])
    assert final["fulfillment_status"] == "RELEASE_READY"
    assert_page_ledger(final, total=23, billable=0, withheld=23, redacted=0)


# --------------------------------------------------------------------------
# access_basis_and_requester_type_mismatches_rejected
# --------------------------------------------------------------------------
def _intake_gate_world(api):
    """One facility and patient with two requesting parties — an ATTORNEY holding a VALID
    authorization, and the patient themself — so every access-basis pairing is available."""
    world = fx.third_party_world(api)
    patient_requester = fx.make_patient_requester(api, world["patient_id"])
    return world, patient_requester["id"]


def _third_party_body(world, **overrides):
    # The overrides are applied after the defaults rather than forwarded as
    # keyword arguments, so that an override of a field the factory takes
    # positionally — `authorization_id=None` for the missing-authorization leg —
    # replaces the default instead of colliding with it.
    payload = f.third_party_request_payload(
        world["facility_id"],
        world["patient_id"],
        world["requester_id"],
        world["authorization_id"],
        date_range_start="2024-01-01",
        date_range_end="2024-12-31",
    )
    payload.update(overrides)
    return payload


def test_the_right_of_access_is_closed_to_an_attorney_who_may_still_use_an_authorization(api):
    """One requesting party, two access bases: refused on the first, accepted on the second.

    PRD: "Second, a `PATIENT_RIGHT_OF_ACCESS` request is only open to a requesting party whose `requester_type` is `PATIENT` or `PERSONAL_REPRESENTATIVE`; any other type is refused with `ERR_ACCESS_BASIS_REQUESTER_MISMATCH`."

    Design: Corner/validations/access_basis_and_requester_type_mismatches_rejected
    """
    world, _ = _intake_gate_world(api)

    validate_error(
        api.create_request(
            f.patient_access_request_payload(
                world["facility_id"],
                world["patient_id"],
                world["requester_id"],
                date_range_start="2024-01-01",
                date_range_end="2024-12-31",
            ),
            INTAKE_1,
        ),
        e.ERR_ACCESS_BASIS_REQUESTER_MISMATCH,
        422,
    )

    accepted = validate_success(api.create_request(_third_party_body(world), INTAKE_1), 201)
    assert accepted["fulfillment_status"] == "INTAKE_REVIEW"
    assert accepted["authorization_id"] == world["authorization_id"]

    _, meta = validate_paginated(
        api.list_requests(INTAKE_1, {"patient_id": world["patient_id"], "limit": 10})
    )
    assert meta["total_count"] == 1


def test_the_agreement_rule_bars_a_superfluous_authorization_as_well_as_a_missing_one(api):
    """A right-of-access request carrying one and a third-party request lacking one share a code.

    PRD: "Third, the access basis and the authorization must agree: a `THIRD_PARTY_AUTHORIZATION` request with a null `authorization_id`, a `PATIENT_RIGHT_OF_ACCESS` request with a non-null `authorization_id`, or a referenced authorization whose own `patient_id` or `requester_id` differs from the body's, are all refused with `ERR_AUTHORIZATION_REQUIRED`."

    Design: Corner/validations/access_basis_and_requester_type_mismatches_rejected
    """
    world, patient_requester_id = _intake_gate_world(api)

    validate_error(
        api.create_request(
            f.patient_access_request_payload(
                world["facility_id"],
                world["patient_id"],
                patient_requester_id,
                authorization_id=world["authorization_id"],
                date_range_start="2024-01-01",
                date_range_end="2024-12-31",
            ),
            INTAKE_1,
        ),
        e.ERR_AUTHORIZATION_REQUIRED,
        422,
    )
    validate_error(
        api.create_request(_third_party_body(world, authorization_id=None), INTAKE_1),
        e.ERR_AUTHORIZATION_REQUIRED,
        422,
    )

    accepted = validate_success(api.create_request(_third_party_body(world), INTAKE_1), 201)
    assert accepted["access_basis"] == "THIRD_PARTY_AUTHORIZATION"

    _, meta = validate_paginated(
        api.list_requests(INTAKE_1, {"patient_id": world["patient_id"], "limit": 10})
    )
    assert meta["total_count"] == 1
    assert fx.read_request(api, accepted["id"])["predecessor_request_id"] is None


# --------------------------------------------------------------------------
# duplicate_inflight_request_key_and_its_two_escapes
# --------------------------------------------------------------------------
def _in_flight_sibling(api):
    """One accepted, therefore non-terminal, third-party request over 2024-01-01..2024-12-31."""
    world = fx.third_party_world(api)
    first = get_success_data(api.create_request(_third_party_body(world), INTAKE_1))
    fx.accept_request(api, first["id"])
    return world, first["id"]


def test_an_identical_five_tuple_is_refused_and_one_shifted_bound_escapes(api):
    """The key is exact-match on both date bounds, so a single day of difference is a new request.

    PRD: "Fourth, duplicate work is refused: if another request already shares this one's `facility_id`, `patient_id`, `requester_id`, `date_range_start` and `date_range_end`, and that other request's `fulfillment_status` is neither `CLOSED` nor `CANCELLED`, and it is not the request named by this one's `predecessor_request_id`, the creation is refused with `ERR_DUPLICATE_INFLIGHT_REQUEST`."

    Design: Corner/validations/duplicate_inflight_request_key_and_its_two_escapes
    """
    world, first_id = _in_flight_sibling(api)
    assert fx.read_request(api, first_id)["fulfillment_status"] == "COMPILATION"

    validate_error(
        api.create_request(_third_party_body(world), INTAKE_1),
        e.ERR_DUPLICATE_INFLIGHT_REQUEST,
        409,
    )

    shifted = validate_success(
        api.create_request(
            _third_party_body(world, date_range_end="2024-12-30"), INTAKE_1
        ),
        201,
    )
    assert shifted["date_range_end"] == "2024-12-30"
    assert shifted["fulfillment_status"] == "INTAKE_REVIEW"

    _, meta = validate_paginated(
        api.list_requests(
            INTAKE_1,
            {
                "patient_id": world["patient_id"],
                "requester_id": world["requester_id"],
                "limit": 10,
            },
        )
    )
    assert meta["total_count"] == 2


def test_naming_the_in_flight_sibling_as_predecessor_is_the_second_escape(api):
    """The same five-tuple is legal precisely when it re-files the sibling that blocks it.

    PRD: "Three inputs are optional: `authorization_id`, defaulting to null; `predecessor_request_id`, defaulting to null and naming the earlier request this one re-files after a denial or a withdrawal; and `certification_requested`, defaulting to false."

    Design: Corner/validations/duplicate_inflight_request_key_and_its_two_escapes
    """
    world, first_id = _in_flight_sibling(api)
    validate_error(
        api.create_request(_third_party_body(world), INTAKE_1),
        e.ERR_DUPLICATE_INFLIGHT_REQUEST,
        409,
    )

    refiled = validate_success(
        api.create_request(
            _third_party_body(world, predecessor_request_id=first_id), INTAKE_1
        ),
        201,
    )
    assert refiled["predecessor_request_id"] == first_id
    assert refiled["date_range_start"] == "2024-01-01"
    assert refiled["date_range_end"] == "2024-12-31"
    assert refiled["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")

    rows, meta = validate_paginated(
        api.list_requests(INTAKE_1, {"predecessor_request_id": first_id, "limit": 10})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [refiled["id"]]

    original = fx.read_request(api, first_id)
    assert original["version"] == 2
    assert original["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")


# --------------------------------------------------------------------------
# sensitive_review_requires_every_segregated_segment_decided_exactly_once
#
# The design's third failure leg names the NOT_SENSITIVE segment with an
# INCLUDE decision, but per PRD §2.8 the disclosure-safety rules sit at 20-24,
# ahead of the completeness rule, so such a body reports
# ERR_SENSITIVE_CATEGORY_NOT_AUTHORIZED instead.  The extra-segment shape is
# therefore driven with a WITHHOLD decision, which no safety rule polices.
# --------------------------------------------------------------------------
def _three_segment_request_in_sensitive_review(api):
    """8 general-medical pages classified NOT_SENSITIVE beside 20 behavioural-health and 12 HIV
    pages awaiting review, with only HIV covered by the authorization."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"],
        sensitive_categories_authorized=["HIV"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"]
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gm", "category": "GENERAL_MEDICAL", "page_count": 8},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 20},
            {"label": "hiv", "category": "HIV", "page_count": 12},
        ],
    )
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def test_the_review_pass_is_refused_unless_it_names_each_segregated_segment_once(api):
    """An omission, a repetition and an extra segment all fail; the exact set then passes.

    PRD: "Every segment of the request whose `sensitivity_status` is `SEGREGATED_PENDING_REVIEW` must appear in `segment_decisions` exactly once; a segregated segment omitted from the array, a segment named twice, or a decision naming a segment whose `sensitivity_status` is not `SEGREGATED_PENDING_REVIEW`, is each refused with `ERR_SEGREGATION_REVIEW_INCOMPLETE`."

    Design: Corner/validations/sensitive_review_requires_every_segregated_segment_decided_exactly_once
    """
    scenario = _three_segment_request_in_sensitive_review(api)
    request_id = scenario["request_id"]
    ids = scenario["segment_ids"]
    before = fx.read_request(api, request_id)
    assert_page_ledger(before, total=40, billable=8, withheld=0, redacted=0)

    omitted = f.sensitive_review_payload([f.withhold_decision(ids["bh"])])
    repeated = f.sensitive_review_payload(
        [
            f.withhold_decision(ids["bh"]),
            f.withhold_decision(ids["bh"]),
            f.include_decision(ids["hiv"]),
        ]
    )
    extra = f.sensitive_review_payload(
        [
            f.withhold_decision(ids["bh"]),
            f.include_decision(ids["hiv"]),
            f.withhold_decision(ids["gm"]),
        ]
    )
    for body in (omitted, repeated, extra):
        validate_error(
            api.sensitive_review(request_id, body, REVIEWER_1),
            e.ERR_SEGREGATION_REVIEW_INCOMPLETE,
            409,
        )

    for label in ("bh", "hiv"):
        assert fx.read_segment(api, ids[label])["sensitivity_status"] == (
            "SEGREGATED_PENDING_REVIEW"
        )
    assert fx.read_request(api, request_id)["version"] == before["version"]

    moved = validate_success(
        api.sensitive_review(
            request_id,
            f.sensitive_review_payload(
                [f.withhold_decision(ids["bh"]), f.include_decision(ids["hiv"])]
            ),
            REVIEWER_1,
        ),
        200,
    )
    assert moved["fulfillment_status"] == "RELEASE_READY"


def test_the_accepted_pass_moves_only_the_two_segregated_segments(api):
    """The NOT_SENSITIVE segment is untouched while its 8 pages stay billable beside HIV's 12.

    PRD: "An accepted `INCLUDE` moves the segment's `sensitivity_status` from `SEGREGATED_PENDING_REVIEW` to `AUTHORIZED_INCLUDE`, and when that entry carried `redaction_required` true the segment's `redaction_status` moves from `NOT_REQUIRED` to `OPEN` in the same call."

    Design: Corner/validations/sensitive_review_requires_every_segregated_segment_decided_exactly_once
    """
    scenario = _three_segment_request_in_sensitive_review(api)
    request_id = scenario["request_id"]
    ids = scenario["segment_ids"]

    fx.run_sensitive_review(
        api,
        request_id,
        [f.withhold_decision(ids["bh"]), f.include_decision(ids["hiv"])],
    )

    assert fx.read_segment(api, ids["bh"])["sensitivity_status"] == "WITHHELD"
    hiv = fx.read_segment(api, ids["hiv"])
    assert hiv["sensitivity_status"] == "AUTHORIZED_INCLUDE"
    assert hiv["redaction_status"] == "NOT_REQUIRED"
    assert fx.read_segment(api, ids["gm"])["sensitivity_status"] == "NOT_SENSITIVE"

    final = fx.read_request(api, request_id)
    assert final["fulfillment_status"] == "RELEASE_READY"
    assert_page_ledger(final, total=40, billable=20, withheld=20, redacted=0)
    assert_event_count(fx.read_events(api, request_id), "SENSITIVE_WITHHOLD", 1)
