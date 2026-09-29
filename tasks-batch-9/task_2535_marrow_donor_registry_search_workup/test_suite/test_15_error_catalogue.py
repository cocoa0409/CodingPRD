"""Error catalogue triggerability: every refusal the PRD names must be reachable.

Each scenario below is built so that exactly one rejection rule is violated, so
the returned `error_id` identifies that rule rather than the evaluation ladder of
§2.9. Where the PRD itself pins the precedence between two simultaneously
violated rungs, the docstring quotes that ordering sentence.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assertions,
    constants,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value: str) -> datetime:
    """An instant-valued field parsed for exact-to-the-second comparison (§2.4)."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _patient_version(api, ctx) -> int:
    """The patient's current `version`, so a conditioning call never trips §2.7."""
    return validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )["version"]


def test_donor_list_rejects_out_of_range_pagination(api, operations_headers):
    """`limit` 0, `limit` 101 and a negative `offset` are all ERR_INVALID_PAGINATION.

    PRD §2.3: "The `limit` parameter caps the number of rows returned; when
    omitted it defaults to 10, its minimum accepted value is 1 and its maximum
    accepted value is 100."
    PRD §2.3: "A `limit` outside the range 1 to 100, a non-integer `limit` or
    `offset`, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`
    (HTTP 400)."

    Design: Corner/errors/pagination_uniqueness_and_grade_errors_are_all_triggerable
    """
    ctx = fixtures.setup_programme(with_center=False)
    fixtures.add_donor(ctx)

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        response = api.list_donors(operations_headers, params=params)
        validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value)

    rows, meta = validate_paginated(
        api.list_donors(operations_headers, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1, "the accepted maximum limit returns the single donor"
    assert meta["has_more"] is False
    assert len(rows) == 1


def test_releasing_an_unknown_calendar_window_is_a_window_not_found(api):
    """The window is the second path identifier, so an unknown one names the window.

    PRD §2.8: "The donor calendar window release path carries two identifiers:
    the donor is resolved first, and the window second, so a window identifier
    that does not exist — or that exists but belongs to a donor other than the
    one named earlier in the path — yields `ERR_UNAVAILABILITY_WINDOW_NOT_FOUND`."

    Design: Corner/errors/pagination_uniqueness_and_grade_errors_are_all_triggerable
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)

    response = api.release_unavailability_window(
        donor["id"], NON_EXISTENT_UUID, ctx["liaison_headers"]
    )
    validate_error(response, ApiErrorId.ERR_UNAVAILABILITY_WINDOW_NOT_FOUND.value)

    donor_after = validate_success(api.get_donor(donor["id"], ctx["liaison_headers"]))
    assert donor_after["blocked_day_count"] == 0


def test_follow_up_grade_must_agree_with_the_event_type(api, physician_headers):
    """A graded contact and an ungraded adverse event are both refused.

    PRD §3.9: "Grade and event type must agree: a scheduled contact row must
    carry `severity_grade` exactly 0, while an `ADVERSE_EVENT` row must carry a
    grade from 1 through 5, and any other combination is refused with
    `ERR_ADVERSE_EVENT_GRADE_INVALID`."

    Design: Corner/errors/pagination_uniqueness_and_grade_errors_are_all_triggerable
    """
    ctx = fixtures.setup_programme(with_center=False)
    donor = fixtures.add_donor(ctx)

    ungraded_event = api.create_follow_up(
        donor["id"], f.create_follow_up_payload("ADVERSE_EVENT", 0), physician_headers
    )
    validate_error(ungraded_event, ApiErrorId.ERR_ADVERSE_EVENT_GRADE_INVALID.value)

    graded_contact = api.create_follow_up(
        donor["id"], f.create_follow_up_payload("DAY_30_CONTACT", 2), physician_headers
    )
    validate_error(graded_contact, ApiErrorId.ERR_ADVERSE_EVENT_GRADE_INVALID.value)

    _rows, meta = validate_paginated(
        api.list_follow_ups(donor["id"], ctx["liaison_headers"])
    )
    assert meta["total_count"] == 0, "neither refused row was filed"
    donor_after = validate_success(api.get_donor(donor["id"], ctx["liaison_headers"]))
    assert donor_after["adverse_event_count"] == 0
    assert donor_after["last_followup_at"] is None


def test_registry_code_must_be_unique_across_all_registries(api, operations_headers):
    """A second registry claiming the same code is refused.

    PRD §3.1: "A `RegistryOperations` operator registers a registry with a `code`
    of one to sixteen characters drawn from uppercase letters, digits and the
    hyphen, which must be unique across all registries — a repeat is refused with
    `ERR_REGISTRY_CODE_ALREADY_EXISTS` — together with a legal `name` of one to
    one hundred and twenty characters, a `country_code` of exactly two uppercase
    letters, a `currency_code` of exactly three uppercase letters naming the
    currency the registry invoices in, and an `fx_rate_to_usd` giving the United
    States dollar value of one unit of that currency, expressed as a positive
    number with exactly four decimal places."

    Design: Corner/errors/pagination_uniqueness_and_grade_errors_are_all_triggerable
    """
    first = fixtures.create_registry(code="NMDP-US")
    assert first["code"] == "NMDP-US"

    duplicate = api.create_registry(
        f.create_registry_payload(code="NMDP-US", name="Another Programme"),
        operations_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_REGISTRY_CODE_ALREADY_EXISTS.value)


def test_donor_code_is_unique_only_inside_its_own_registry(api, liaison_headers_for):
    """The same donor code repeats across registries but never inside one.

    PRD §3.2: "Within that registry the `donor_code` must be unique, one to
    twenty-four characters long; a repeat inside the same registry is refused
    with `ERR_DONOR_CODE_ALREADY_EXISTS`, while the same code under a different
    registry is perfectly legal."

    Design: Corner/errors/pagination_uniqueness_and_grade_errors_are_all_triggerable
    """
    home = fixtures.create_registry(code="NMDP-US")
    partner = fixtures.create_international_registry(code="DKMS-DE")

    fixtures.create_donor(home["id"], donor_code="D-0001")

    duplicate = api.create_donor(
        f.create_donor_payload(home["id"], donor_code="D-0001"),
        liaison_headers_for(home["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DONOR_CODE_ALREADY_EXISTS.value)

    elsewhere = validate_success(
        api.create_donor(
            f.create_donor_payload(partner["id"], donor_code="D-0001"),
            liaison_headers_for(partner["id"]),
        ),
        expected_status=201,
    )
    assertions.assert_donor_profile(elsewhere)
    assert elsewhere["donor_code"] == "D-0001"
    assert elsewhere["registry_id"] == partner["id"]


def test_patient_mrn_must_be_unique_across_all_patients(
    api, coordinator_headers, other_coordinator_headers
):
    """A second patient claiming the same medical-record number is refused.

    PRD §3.3: "A `TransplantCoordinator` registers the recipient with an `mrn` of
    one to thirty-two characters that must be unique across all patients — a
    repeat is refused with `ERR_MRN_ALREADY_EXISTS` — a `transplant_center_code`
    of one to sixteen characters naming the owning centre as a free-form label
    with no entity behind it, a `country_code` of exactly two uppercase letters,
    and a `diagnosis_code` of one to sixteen characters."

    Design: Corner/errors/pagination_uniqueness_and_grade_errors_are_all_triggerable
    """
    first = fixtures.create_patient(headers=coordinator_headers, mrn="MRN-9001")
    assert first["mrn"] == "MRN-9001"

    duplicate = api.create_patient(
        f.create_patient_payload(mrn="MRN-9001"), other_coordinator_headers
    )
    validate_error(duplicate, ApiErrorId.ERR_MRN_ALREADY_EXISTS.value)


def test_typing_response_refuses_an_antigen_level_locus(api):
    """One colon-free locus refuses the whole response; the corrected one is taken.

    PRD §3.4: "`reported_hla_typing` is an object with exactly the five keys `A`,
    `B`, `C`, `DRB1` and `DQB1`, each an array of exactly two strings, and every
    one of those ten strings must be allele-level: if any string at any of the
    five loci is antigen-level, meaning it contains no colon, the response is
    refused with `ERR_CT_TYPING_NOT_ALLELE_LEVEL`."
    PRD §3.4: "Alongside the score, the response computes the allele-level
    matched count — the sum across the five loci of the allele-level matched
    counts, a whole number from 0 through 10 — and renders it as a grade string
    of that number followed by a slash and ten."

    Design: Corner/errors/typing_and_screening_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("typing_requested", num_donors=1, with_center=False)

    antigen_level = api.respond_typing_request(
        ctx["typing_request_id"],
        f.typing_response_payload(
            reported_hla_typing=dict(f.REPORTED_HLA_ALLELE, C=["07", "07"])
        ),
        ctx["liaison_headers"],
    )
    validate_error(antigen_level, ApiErrorId.ERR_CT_TYPING_NOT_ALLELE_LEVEL.value)

    still_open = validate_success(
        api.get_match_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert still_open["status"] == "TYPING_REQUESTED", "the refused response wrote nothing"

    corrected = validate_success(
        api.respond_typing_request(
            ctx["typing_request_id"], f.typing_response_payload(), ctx["liaison_headers"]
        )
    )
    assertions.assert_typing_request(corrected)
    assert corrected["status"] == "RESPONDED"
    assert corrected["reported_match_grade"] == "9/10"


def test_a_typing_request_may_be_answered_only_once(api):
    """A RESPONDED request is closed to any further answer.

    PRD §3.4: "The typing request must still be in `REQUESTED` status — a request
    that is already `RESPONDED`, `EXPIRED` or `CANCELLED` is refused with
    `ERR_TYPING_REQUEST_NOT_OPEN` — and the acting liaison must be the donor's
    own registry."

    Design: Corner/errors/typing_and_screening_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("typing_responded", num_donors=1, with_center=False)

    again = api.respond_typing_request(
        ctx["typing_request_id"], f.typing_response_payload(), ctx["liaison_headers"]
    )
    validate_error(again, ApiErrorId.ERR_TYPING_REQUEST_NOT_OPEN.value)


def test_a_passing_screening_needs_an_available_donor(api):
    """A PASS against a temporarily deferred donor is refused.

    PRD §3.5: "A passing screening additionally requires that the donor's
    `availability_status` is `AVAILABLE` at that moment; a `PASS` recorded
    against a donor who is `TEMPORARILY_DEFERRED`, `PERMANENTLY_DEFERRED` or
    `WITHDRAWN` is refused with `ERR_DONOR_NOT_AVAILABLE`."
    PRD §3.5: "The candidate must be in `TYPING_RESPONDED` or `DEFERRED` status,
    and the acting liaison must own the donor's registry."

    Design: Corner/errors/typing_and_screening_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("typing_responded", num_donors=1, with_center=False)
    fixtures.advance_to_screening_passed(
        ctx, outcome="DEFER", deferral_type="TEMPORARY", deferral_until="2026-09-15"
    )
    deferred_donor = validate_success(
        api.get_donor(ctx["donor_id"], ctx["liaison_headers"])
    )
    assert deferred_donor["availability_status"] == "TEMPORARILY_DEFERRED"

    refused = api.record_screening(
        ctx["candidate_id"], f.screening_payload(), ctx["liaison_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_DONOR_NOT_AVAILABLE.value)

    candidate = validate_success(
        api.get_match_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert candidate["status"] == "DEFERRED", "the refused PASS left the deferral standing"
    assert candidate["screening_outcome"] == "DEFER"


def test_a_third_typing_request_exhausts_the_attempt_budget(api, operations_headers):
    """Two expired attempts on a backup leave the third request refused.

    PRD §3.4: "The candidate must be in `IDENTIFIED` or `TYPING_EXPIRED` status,
    its search must not be terminal or stalled, the donor's registry must have
    `cooperation_status` of `ACTIVE` — a suspended or terminated partner is
    refused with `ERR_REGISTRY_NOT_COOPERATING` — and the candidate's
    `ct_attempt_count` must be strictly below the ceiling of two attempts."
    PRD §3.4: "A third request against the same candidate is refused with
    `ERR_CT_ATTEMPTS_EXHAUSTED`."
    PRD §3.4: "A `BACKUP` candidate at two attempts is deliberately *not*
    auto-excluded: it rests in `TYPING_EXPIRED`, which is precisely how a later
    third request against it becomes reachable and is refused with
    `ERR_CT_ATTEMPTS_EXHAUSTED`."
    PRD §3.4: "When the candidate carrying the request is the search's `PRIMARY`,
    the search itself advances `SEARCHING → PRIMARY_ENGAGED`; when the candidate
    is a newly promoted primary, the same act moves the search `BACKUP_REQUIRED →
    PRIMARY_ENGAGED`, and that cycle may repeat once for each available backup."

    Design: Corner/errors/typing_and_screening_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_primary_candidate(num_donors=2, with_center=False)
    backup_id = fixtures.candidate_by_rank(ctx, 2)["id"]

    first = fixtures.advance_to_typing_requested(ctx, backup_id)
    assert first["attempt_number"] == 1
    assert _instant(first["deadline_at"]) == _instant("2026-08-08T00:00:00Z")

    fixtures.set_clock("2026-08-08T00:00:01Z")
    validate_success(api.run_deadline_sweep(ctx["search_id"], operations_headers))
    once_expired = validate_success(
        api.get_match_candidate(backup_id, ctx["coordinator_headers"])
    )
    assert once_expired["status"] == "TYPING_EXPIRED"
    assert once_expired["ct_attempt_count"] == 1

    second = fixtures.advance_to_typing_requested(ctx, backup_id)
    assert second["attempt_number"] == 2
    assert _instant(second["deadline_at"]) == _instant("2026-08-15T00:00:01Z")

    fixtures.set_clock("2026-08-15T00:00:02Z")
    search = validate_success(
        api.run_deadline_sweep(ctx["search_id"], operations_headers)
    )
    assert search["status"] == "SEARCHING", (
        "the untouched rank-1 PRIMARY keeps the search out of every terminal state"
    )

    twice_expired = validate_success(
        api.get_match_candidate(backup_id, ctx["coordinator_headers"])
    )
    assert twice_expired["status"] == "TYPING_EXPIRED", "a BACKUP is not auto-excluded"
    assert twice_expired["ct_attempt_count"] == 2
    assert twice_expired["candidate_role"] == "BACKUP"

    third = api.create_typing_request(
        backup_id, f.create_typing_request_payload(), ctx["coordinator_headers"]
    )
    validate_error(third, ApiErrorId.ERR_CT_ATTEMPTS_EXHAUSTED.value)


def _stall_the_search():
    """Burn the only candidate's two typing attempts so the sweep stalls the search."""
    ctx = fixtures.setup_primary_candidate(num_donors=1, with_center=False)
    fixtures.advance_to_typing_requested(ctx)
    fixtures.set_clock("2026-08-08T00:00:01Z")
    fixtures.sweep(ctx)
    fixtures.advance_to_typing_requested(ctx)
    fixtures.set_clock("2026-08-15T00:00:02Z")
    fixtures.sweep(ctx)
    return ctx


def test_the_sweep_stalls_a_search_whose_only_primary_is_exhausted(api):
    """A twice-expired primary with no promotable backup leaves the search STALLED.

    PRD §3.4: "If that candidate is the `PRIMARY` and its `ct_attempt_count` has
    already reached two, the candidate is additionally moved `TYPING_EXPIRED →
    EXCLUDED` and the promotion cascade runs."
    PRD §3.5: "If no promotable backup exists when the cascade is invoked, no
    promotion occurs and the search is left for the sweep to move to `STALLED`."
    PRD §3.4: "After processing, if the search has no candidate in the `PRIMARY`
    role sitting in a non-terminal status and no promotable backup remains — its
    `backup_candidate_count` having fallen to zero — the search moves to
    `STALLED`."
    PRD §3.4: "Every sweep stamps the search's `last_sweep_at` with the sweep
    instant, whether or not anything expired."

    Design: Corner/errors/a_stalled_search_refuses_every_further_candidate_operation
    """
    ctx = fixtures.setup_primary_candidate(num_donors=1, with_center=False)
    assert ctx["search"]["match_pool_size"] == 1
    assert ctx["search"]["backup_candidate_count"] == 0

    fixtures.advance_to_typing_requested(ctx)
    fixtures.set_clock("2026-08-08T00:00:01Z")
    after_first = validate_success(
        api.run_deadline_sweep(ctx["search_id"], ctx["operations_headers"])
    )
    assert after_first["status"] == "PRIMARY_ENGAGED", (
        "one attempt left, so the primary still rests in TYPING_EXPIRED"
    )

    retry = fixtures.advance_to_typing_requested(ctx)
    assert _instant(retry["deadline_at"]) == _instant("2026-08-15T00:00:01Z")

    fixtures.set_clock("2026-08-15T00:00:02Z")
    after_second = validate_success(
        api.run_deadline_sweep(ctx["search_id"], ctx["operations_headers"])
    )
    assert after_second["status"] == "STALLED"
    assert _instant(after_second["last_sweep_at"]) == _instant("2026-08-15T00:00:02Z")

    candidate = validate_success(
        api.get_match_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert candidate["status"] == "EXCLUDED"
    assert candidate["ct_attempt_count"] == 2


def test_a_stalled_search_refuses_a_further_typing_request(api):
    """A typing request against a stalled search's candidate is refused.

    PRD §3.4: "A stalled search accepts no further workflow operations:
    subsequent typing requests and workup opens against its candidates are
    refused with `ERR_SEARCH_ALREADY_TERMINAL`, exactly as they are for a
    `NO_MATCH_FOUND` or `FULFILLED` search."

    Design: Corner/errors/a_stalled_search_refuses_every_further_candidate_operation
    """
    ctx = _stall_the_search()
    assert ctx["search"]["status"] == "STALLED"

    refused = api.create_typing_request(
        ctx["candidate_id"], f.create_typing_request_payload(), ctx["coordinator_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_SEARCH_ALREADY_TERMINAL.value)


def test_a_stalled_search_refuses_a_workup_open(api):
    """Opening a workup against a stalled search's candidate is refused.

    PRD §3.4: "A stalled search accepts no further workflow operations:
    subsequent typing requests and workup opens against its candidates are
    refused with `ERR_SEARCH_ALREADY_TERMINAL`, exactly as they are for a
    `NO_MATCH_FOUND` or `FULFILLED` search."
    PRD §3.6: "The candidate's search must not be terminal or stalled — an
    attempt against a candidate of a `NO_MATCH_FOUND`, `FULFILLED` or `STALLED`
    search is refused with `ERR_SEARCH_ALREADY_TERMINAL`, exactly as a typing
    request would be."

    Design: Corner/errors/a_stalled_search_refuses_every_further_candidate_operation
    """
    ctx = _stall_the_search()
    assert ctx["search"]["status"] == "STALLED"

    refused = api.open_workup_case(ctx["candidate_id"], ctx["coordinator_headers"])
    validate_error(refused, ApiErrorId.ERR_SEARCH_ALREADY_TERMINAL.value)


def test_start_is_an_illegal_conditioning_action_while_nothing_is_scheduled(api):
    """START from NOT_SCHEDULED is refused by the action-legality gate.

    PRD §3.8: "Each action is legal only from certain states — `SCHEDULE` from
    `NOT_SCHEDULED` or `SCHEDULED`, `START` from `SCHEDULED`, `INFUSE` from
    `STARTED`, and `ABORT` from `SCHEDULED` or `STARTED` — and an action requested
    from any other state is refused with `ERR_INVALID_CONDITIONING_ACTION`."
    PRD §2.9: "Rungs eleven through thirty-two are the state-machine gates, in
    exactly this order: search not terminal and not stalled
    (`ERR_SEARCH_ALREADY_TERMINAL`); candidate status admits the operation
    (`ERR_INVALID_CANDIDATE_STATE`); candidate is the primary
    (`ERR_CANDIDATE_NOT_PRIMARY`); typing request still open
    (`ERR_TYPING_REQUEST_NOT_OPEN`); donor available for a passing screening
    (`ERR_DONOR_NOT_AVAILABLE`); workup case still open
    (`ERR_WORKUP_CASE_NOT_OPEN`); clearance item not yet resulted
    (`ERR_CLEARANCE_ITEM_ALREADY_RESULTED`); clearance items resulted in their
    pinned order (`ERR_CLEARANCE_ORDER_VIOLATION`); method not yet decided
    (`ERR_METHOD_ALREADY_DECIDED`); method already decided
    (`ERR_METHOD_NOT_DECIDED`); clearance complete
    (`ERR_CLEARANCE_NOT_COMPLETE`); booking held (`ERR_BOOKING_NOT_HELD`);
    booking cancellable (`ERR_BOOKING_NOT_CANCELLABLE`); booking confirmed and
    unharvested (`ERR_BOOKING_NOT_CONFIRMED`); conditioning already started
    (`ERR_CONDITIONING_NOT_STARTED`); conditioning action legal from the current
    conditioning state (`ERR_INVALID_CONDITIONING_ACTION`); conditioning
    cross-entity precondition met (`ERR_CONDITIONING_PRECONDITION_UNMET`);
    product delivered (`ERR_PRODUCT_NOT_DELIVERED`); shipment event legal from
    the shipment's status (`ERR_SHIPMENT_EVENT_NOT_ALLOWED`); claim still
    provisional (`ERR_CLAIM_NOT_PROVISIONAL`); claim finalizable
    (`ERR_CLAIM_NOT_FINALIZABLE`); and calendar window manually releasable
    (`ERR_WINDOW_NOT_RELEASABLE`)."

    Design: Corner/errors/workup_and_conditioning_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("workup_open", num_donors=1, with_center=False)
    patient = validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )
    assert patient["conditioning_status"] == "NOT_SCHEDULED"

    refused = api.drive_conditioning(
        ctx["patient_id"],
        f.conditioning_payload("START", patient["version"]),
        ctx["coordinator_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_CONDITIONING_ACTION.value)

    unchanged = validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )
    assert unchanged["conditioning_status"] == "NOT_SCHEDULED"
    assert unchanged["version"] == patient["version"]


def test_conditioning_cannot_be_scheduled_in_the_past(api):
    """A conditioning start date earlier than today is refused.

    PRD §3.8: "The supplied `conditioning_start_date` must not be earlier than
    the current logical UTC date; a date in the past is refused with
    `ERR_CONDITIONING_DATE_IN_PAST`, while today's date is accepted."
    PRD §3.8: "Scheduling from `NOT_SCHEDULED → SCHEDULED` requires that the
    patient already has a search in `WORKUP_ACTIVE` status — conditioning is
    never scheduled speculatively, and a schedule without such a search is
    refused with `ERR_CONDITIONING_PRECONDITION_UNMET`."

    Design: Corner/errors/workup_and_conditioning_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("workup_open", num_donors=1, with_center=False)
    search = validate_success(
        api.get_search_request(ctx["search_id"], ctx["coordinator_headers"])
    )
    assert search["status"] == "WORKUP_ACTIVE", "the cross-entity precondition is met"

    version = _patient_version(api, ctx)
    refused = api.drive_conditioning(
        ctx["patient_id"],
        f.conditioning_payload("SCHEDULE", version, conditioning_start_date="2026-07-01"),
        ctx["coordinator_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_CONDITIONING_DATE_IN_PAST.value)

    unchanged = validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )
    assert unchanged["conditioning_status"] == "NOT_SCHEDULED"
    assert unchanged["conditioning_start_date"] is None
    assert unchanged["version"] == version


def test_a_second_workup_open_for_the_same_candidate_is_refused(api):
    """The duplicate open falls through the candidate-status gate to the duplicate rule.

    PRD §3.6: "The candidate must not already hold another workup case in
    `case_status` `OPEN`, and a second attempt is refused with
    `ERR_DUPLICATE_OPEN_WORKUP`."
    PRD §2.9: "Finally, one deliberate exception to the state ladder: for the
    purpose of the candidate-status gate, a candidate already in `WORKUP_OPEN` is
    treated as permitted, so that a second attempt to open a workup for the same
    candidate falls all the way through to `ERR_DUPLICATE_OPEN_WORKUP` instead of
    being masked as an invalid candidate state."

    Design: Corner/errors/workup_and_conditioning_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("workup_open", num_donors=1, with_center=False)

    duplicate = api.open_workup_case(ctx["candidate_id"], ctx["coordinator_headers"])
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_OPEN_WORKUP.value)

    cases, meta = validate_paginated(
        api.list_workup_cases(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert meta["total_count"] == 1, "the refused open created no second case"
    assert cases[0]["id"] == ctx["workup_case_id"]


def test_the_collection_method_cannot_be_decided_twice(api, second_physician_headers):
    """A case whose logistics dimension has left UNSCHEDULED refuses a new method.

    PRD §3.6: "The method must not already have been decided: a case whose
    `collection_method` is already set — whose `logistics_status` has already left
    `UNSCHEDULED` — is refused with `ERR_METHOD_ALREADY_DECIDED`."

    Design: Corner/errors/workup_and_conditioning_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("method_set", num_donors=1, with_center=False)
    decided = ctx["workup_case"]
    assert decided["collection_method"] == "PBSC"
    assert decided["logistics_status"] == "METHOD_SET"

    again = api.decide_collection_method(
        ctx["workup_case_id"],
        f.collection_method_payload(method="MARROW"),
        second_physician_headers,
    )
    validate_error(again, ApiErrorId.ERR_METHOD_ALREADY_DECIDED.value)

    unchanged = validate_success(
        api.get_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    )
    assert unchanged["collection_method"] == "PBSC", "the refused decision changed nothing"
    assert unchanged["logistics_status"] == "METHOD_SET"
    assert unchanged["version"] == decided["version"]


def test_a_booking_after_the_idm_panel_expiry_day_is_refused(api):
    """A collection date past the panel's expiry day is refused before capacity.

    PRD §3.6: "A passing `IDM_PANEL` sets that item's `expires_at` to its
    `resulted_at` plus thirty days — infectious-disease results are considered
    valid for one month and no longer — and surfaces the same instant as the
    case's `idm_resulted_at`, which stays null unless the panel actually passed."
    PRD §3.7: "The infectious-disease panel result must still be valid on the day
    of collection: the booking's `collection_date` must fall on or before the UTC
    calendar date of the `IDM_PANEL` clearance item's `expires_at`."
    PRD §3.7: "A collection date after that day is refused with
    `ERR_IDM_RESULT_EXPIRED` — a booking sitting exactly on the expiry day is
    accepted."
    PRD §2.9: "On booking creation, the infectious-disease validity check
    precedes the conditioning-window check, which in turn precedes the centre
    capacity check — so a booking that is simultaneously past the panel's
    validity, outside the legal window and into a full centre reports
    `ERR_IDM_RESULT_EXPIRED`."

    Design: Corner/errors/workup_and_conditioning_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("workup_open", num_donors=1)
    fixtures.advance_to_cleared(ctx, clearance_at=constants.CLOCK_EPOCH)
    idm = ctx["clearance"]["IDM_PANEL"]
    assert _instant(idm["resulted_at"]) == _instant(constants.CLOCK_EPOCH)
    assert _instant(idm["expires_at"]) == _instant("2026-08-31T00:00:00Z")
    assert ctx["workup_case"]["clearance_status"] == "CLEARED"

    fixtures.advance_to_method_set(ctx, method="PBSC")
    fixtures.advance_to_conditioning_scheduled(ctx, conditioning_start_date="2026-08-28")

    case = validate_success(
        api.get_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    )
    refused = api.create_collection_booking(
        f.create_booking_payload(
            ctx["workup_case_id"],
            ctx["center_id"],
            "2026-09-03T08:00:00Z",
            case["version"],
        ),
        ctx["center_ops_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_IDM_RESULT_EXPIRED.value)

    center = validate_success(
        api.get_collection_center(ctx["center_id"], ctx["center_ops_headers"])
    )
    assert center["committed_slot_minutes"] == 0, "the refused booking holds no minutes"
    unchanged = validate_success(
        api.get_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    )
    assert unchanged["logistics_status"] == "METHOD_SET"
    assert unchanged["version"] == case["version"]


def test_a_conditioning_abort_moves_the_workup_case_to_aborted(api):
    """The abort cascade closes the case and records its own abort reason.

    PRD §3.8: "The workup case moves `case_status` `OPEN → ABORTED` with
    `abort_reason` `CONDITIONING_ABORTED`, and its match candidate is moved to
    `CLOSED` from either `WORKUP_OPEN` or `COLLECTED`, whichever it held."
    PRD §3.8: "The supplied reason is recorded as the patient's
    `conditioning_aborted_reason`."

    Design: Corner/errors/workup_and_conditioning_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("workup_open", num_donors=1, with_center=False)
    fixtures.advance_to_conditioning_scheduled(ctx, conditioning_start_date="2026-08-28")

    patient = fixtures.drive_conditioning(
        ctx, "ABORT", reason="Recipient clinical deterioration"
    )
    assert patient["conditioning_status"] == "ABORTED"
    assert patient["conditioning_aborted_reason"] == "Recipient clinical deterioration"

    case = validate_success(
        api.get_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    )
    assert case["case_status"] == "ABORTED"
    assert case["abort_reason"] == "CONDITIONING_ABORTED"

    candidate = validate_success(
        api.get_match_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert candidate["status"] == "CLOSED"


def test_a_method_decision_against_a_closed_case_is_refused(api, second_physician_headers):
    """Once the case is no longer OPEN, the method decision is refused.

    PRD §3.6: "The case must be `OPEN`."
    PRD §3.6: "The case must be in `case_status` `OPEN`, or the write is refused
    with `ERR_WORKUP_CASE_NOT_OPEN`."
    PRD §3.6: "The case moves `case_status` `OPEN → ABORTED` with
    `clearance_status` `FAILED` and `abort_reason` recorded."
    PRD §3.6: "The promotion cascade runs, and the search moves `WORKUP_ACTIVE →
    BACKUP_REQUIRED`."

    Design: Corner/errors/workup_and_conditioning_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("workup_open", num_donors=1, with_center=False)
    fixtures.result_clearance_item(ctx, "PHYSICAL_EXAM", "FAIL")
    case = ctx["workup_case"]
    assert case["case_status"] == "ABORTED"
    assert case["clearance_status"] == "FAILED"
    assert case["collection_method"] is None, "no method was ever decided on this case"
    assert case["physical_cleared_by_user_id"] is None, "a failed physical clears nobody"

    search = validate_success(
        api.get_search_request(ctx["search_id"], ctx["coordinator_headers"])
    )
    assert search["status"] == "BACKUP_REQUIRED", "the search is neither terminal nor stalled"

    refused = api.decide_collection_method(
        ctx["workup_case_id"], f.collection_method_payload(), second_physician_headers
    )
    validate_error(refused, ApiErrorId.ERR_WORKUP_CASE_NOT_OPEN.value)


def test_no_product_may_be_recorded_before_conditioning_starts(api):
    """The harvest interlock refuses a product while the recipient is only SCHEDULED.

    PRD §3.7: "The booking must be in `CONFIRMED` status with no shipment already
    recorded, or the request is refused with `ERR_BOOKING_NOT_CONFIRMED`, and the
    recipient's conditioning must already be under way — `conditioning_status`
    `STARTED` — or the request is refused with `ERR_CONDITIONING_NOT_STARTED`."
    PRD §3.7: "The shipment records its `collection_booking_id`, stamps
    `collected_at` from the logical clock as the moment collection ended, and
    derives `must_infuse_by` as that instant advanced by the method's viability
    allowance — 72 hours, three full days, for a `PBSC` product, and 48 hours, two
    full days, for a `MARROW` product."
    PRD §3.7: "It also derives `dose_adequacy`, which is `ADEQUATE` when
    `collected_cd34_e6_per_kg` is greater than or equal to two million cells per
    kilogram — the threshold expressed in the same units of one million as the
    field itself, namely 2.00 — and `INADEQUATE` otherwise."

    Design: Corner/errors/product_handling_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("booking_confirmed", num_donors=1)
    patient = validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )
    assert patient["conditioning_status"] == "SCHEDULED"
    assert ctx["booking"]["status"] == "CONFIRMED"

    too_early = api.create_shipment(
        ctx["booking_id"],
        f.create_shipment_payload(collected_cd34_e6_per_kg=1.50),
        ctx["center_ops_headers"],
    )
    validate_error(too_early, ApiErrorId.ERR_CONDITIONING_NOT_STARTED.value)

    fixtures.advance_to_conditioning_started(ctx)
    fixtures.set_clock(constants.TIMELINE["COLLECTED_AT"])
    shipment = validate_success(
        api.create_shipment(
            ctx["booking_id"],
            f.create_shipment_payload(collected_cd34_e6_per_kg=1.50),
            ctx["center_ops_headers"],
        ),
        expected_status=201,
    )
    assertions.assert_product_shipment(shipment)
    assert _instant(shipment["collected_at"]) == _instant("2026-10-11T13:00:00Z")
    assert _instant(shipment["must_infuse_by"]) == _instant("2026-10-14T13:00:00Z")
    assert shipment["dose_adequacy"] == "INADEQUATE"
    assert shipment["status"] == "SCHEDULED"
    assert shipment["transit_event_count"] == 0


def test_courier_events_must_be_legal_from_the_shipments_status(api, operations_headers):
    """DELIVERED before departure and a repeated DEPARTED are both refused.

    PRD §3.7: "The shipment's status must admit the event: `DEPARTED` is legal
    only from `SCHEDULED`, and `DELIVERED` and `LOST` are legal only from
    `IN_TRANSIT`; anything else is refused with `ERR_SHIPMENT_EVENT_NOT_ALLOWED`."
    PRD §3.7: "Every accepted event increments the shipment's
    `transit_event_count` by one."
    PRD §3.7: "A `DEPARTED` event stamps `departed_at` from the logical clock and
    moves the shipment `SCHEDULED → IN_TRANSIT`, carrying the case `COLLECTED →
    IN_TRANSIT`."
    PRD §3.7: "A `DELIVERED` event filed at or before `must_infuse_by` stamps
    `delivered_at` and moves the shipment `IN_TRANSIT → DELIVERED`, carrying the
    case `IN_TRANSIT → DELIVERED`, at which point the recipient may be infused."

    Design: Corner/errors/product_handling_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("collected", num_donors=1)
    assert ctx["shipment"]["status"] == "SCHEDULED"

    out_of_order = api.create_shipment_event(
        ctx["shipment_id"], f.shipment_event_payload("DELIVERED"), operations_headers
    )
    validate_error(out_of_order, ApiErrorId.ERR_SHIPMENT_EVENT_NOT_ALLOWED.value)
    still_scheduled = validate_success(
        api.get_shipment(ctx["shipment_id"], operations_headers)
    )
    assert still_scheduled["status"] == "SCHEDULED"
    assert still_scheduled["transit_event_count"] == 0

    departed = validate_success(
        api.create_shipment_event(
            ctx["shipment_id"], f.shipment_event_payload("DEPARTED"), operations_headers
        )
    )
    assert departed["status"] == "IN_TRANSIT"
    assert _instant(departed["departed_at"]) == _instant("2026-10-11T13:00:00Z")
    assert departed["transit_event_count"] == 1

    twice = api.create_shipment_event(
        ctx["shipment_id"], f.shipment_event_payload("DEPARTED"), operations_headers
    )
    validate_error(twice, ApiErrorId.ERR_SHIPMENT_EVENT_NOT_ALLOWED.value)

    fixtures.set_clock("2026-10-11T20:00:00Z")
    delivered = validate_success(
        api.create_shipment_event(
            ctx["shipment_id"], f.shipment_event_payload("DELIVERED"), operations_headers
        )
    )
    assert delivered["status"] == "DELIVERED"
    assert _instant(delivered["delivered_at"]) == _instant("2026-10-11T20:00:00Z")
    assert delivered["transit_event_count"] == 2


def test_infusion_refuses_an_underdosed_delivered_product(api):
    """A DELIVERED but INADEQUATE product cannot be infused.

    PRD §3.8: "That delivered product's `dose_adequacy` must be `ADEQUATE`, or the
    request is refused with `ERR_PRODUCT_DOSE_INADEQUATE`."
    PRD §3.8: "Every successful action increments the patient's `version` by one."

    Design: Corner/errors/product_handling_refusals_are_all_triggerable
    """
    ctx = fixtures.setup_pipeline("conditioning_started", num_donors=1)
    fixtures.advance_to_collected(ctx, collected_cd34_e6_per_kg=1.50)
    fixtures.advance_shipment_departed(ctx)
    delivered = fixtures.advance_shipment_delivered(ctx)
    assert delivered["status"] == "DELIVERED"
    assert delivered["dose_adequacy"] == "INADEQUATE"

    version = _patient_version(api, ctx)
    refused = api.drive_conditioning(
        ctx["patient_id"],
        f.conditioning_payload("INFUSE", version),
        ctx["coordinator_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_PRODUCT_DOSE_INADEQUATE.value)

    patient = validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )
    assert patient["conditioning_status"] == "STARTED"
    assert patient["version"] == version, "a refused infusion increments nothing"


def test_infusion_refuses_a_product_still_in_transit(api):
    """A product that has departed but not arrived cannot be infused.

    PRD §3.8: "It requires that a product shipment of the patient's workup case
    is in `DELIVERED` status, or the request is refused with
    `ERR_PRODUCT_NOT_DELIVERED`."

    Design: Corner/errors/product_viability_expiry_refusal_is_triggerable
    """
    ctx = fixtures.setup_pipeline("in_transit", num_donors=1)
    assert ctx["shipment"]["status"] == "IN_TRANSIT"
    assert ctx["shipment"]["dose_adequacy"] == "ADEQUATE"

    version = _patient_version(api, ctx)
    refused = api.drive_conditioning(
        ctx["patient_id"],
        f.conditioning_payload("INFUSE", version),
        ctx["coordinator_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_PRODUCT_NOT_DELIVERED.value)

    patient = validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )
    assert patient["conditioning_status"] == "STARTED"
    assert patient["version"] == version


def test_infusion_one_second_past_the_viability_deadline_is_refused(api):
    """An adequate delivered product still expires one second past must_infuse_by.

    PRD §3.8: "And the current logical UTC instant must not be after that
    shipment's `must_infuse_by`, or the request is refused with
    `ERR_PRODUCT_VIABILITY_EXPIRED`; an infusion recorded at exactly the viability
    deadline is accepted."

    Design: Corner/errors/product_viability_expiry_refusal_is_triggerable
    """
    ctx = fixtures.setup_pipeline("delivered", num_donors=1)
    shipment = ctx["shipment"]
    assert shipment["status"] == "DELIVERED"
    assert shipment["dose_adequacy"] == "ADEQUATE"
    assert _instant(shipment["must_infuse_by"]) == _instant("2026-10-14T13:00:00Z")

    version = _patient_version(api, ctx)
    fixtures.set_clock("2026-10-14T13:00:01Z")
    refused = api.drive_conditioning(
        ctx["patient_id"],
        f.conditioning_payload("INFUSE", version),
        ctx["coordinator_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_PRODUCT_VIABILITY_EXPIRED.value)

    after = validate_success(api.get_shipment(ctx["shipment_id"], ctx["center_ops_headers"]))
    assert after["status"] == "DELIVERED", "the refused infusion discards nothing"
    assert _instant(after["must_infuse_by"]) == _instant("2026-10-14T13:00:00Z")

    patient = validate_success(
        api.get_patient(ctx["patient_id"], ctx["coordinator_headers"])
    )
    assert patient["conditioning_status"] == "STARTED"
    assert patient["version"] == version


def test_infusion_exactly_at_the_viability_deadline_is_accepted(api):
    """The deadline instant itself is inside the viability allowance.

    PRD §3.8: "And the current logical UTC instant must not be after that
    shipment's `must_infuse_by`, or the request is refused with
    `ERR_PRODUCT_VIABILITY_EXPIRED`; an infusion recorded at exactly the viability
    deadline is accepted."
    PRD §3.8: "Infusion moves `STARTED → INFUSED` and closes the case."

    Design: Corner/errors/product_viability_expiry_refusal_is_triggerable
    """
    ctx = fixtures.setup_pipeline("delivered", num_donors=1)
    assert _instant(ctx["shipment"]["must_infuse_by"]) == _instant("2026-10-14T13:00:00Z")

    version = _patient_version(api, ctx)
    fixtures.set_clock("2026-10-14T13:00:00Z")
    patient = validate_success(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload("INFUSE", version),
            ctx["coordinator_headers"],
        )
    )
    assert patient["conditioning_status"] == "INFUSED"
    assert patient["version"] == version + 1
