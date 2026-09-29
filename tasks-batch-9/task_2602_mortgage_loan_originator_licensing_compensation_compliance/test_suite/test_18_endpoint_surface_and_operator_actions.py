"""Endpoint surface and operator-only actions.

The endpoints in this file are the ones whose whole behaviour lives in the
request/response contract rather than in a calculation: the employment PATCH
that recomputes a projection, the computed authority read and its `as_of`
parameter, the compliance withdrawal of advertising copy, the operator sweep
that must be safe to run twice, the manual investigation that derives its
parent link from the loan it names, and the optimistic-concurrency guard on a
plan assignment (PRD 2.7, 2.8, 3.1, 3.3, 3.8, 3.9).

Every test builds its own preconditions: the server is restarted with an empty
store before each one, and the logical clock reads exactly
`2026-08-01T00:00:00Z` until a test moves it.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_STARTUP_INSTANT
from test_helpers.fixtures import (
    create_originator,
    draft_advertisement,
    lock_loan,
    set_clock,
    setup_approved_plan,
    setup_authorized_originator,
    submit_advertisement,
    take_loan,
)
from test_helpers.test_users import (
    admin_headers,
    analyst_headers,
    make_originator_headers,
    officer_headers,
)

SWEEP_REPORT_ARRAYS = (
    "expired_license_ids",
    "relinquished_sponsorship_ids",
    "suspended_loan_ids",
    "opened_investigation_ids",
    "escalated_inquiry_ids",
    "unassigned_originator_ids",
)


def _instant(value):
    """Parse an ISO 8601 UTC instant.

    A local helper rather than a test_helpers addition: the framework offers a
    format check (`is_iso8601_timestamp`) but no value comparison, and PRD 2.5
    fixes the wire format at three fractional digits while the instants a test
    supplies are written without them. Comparing parsed instants keeps the
    assertion exact on the instant itself.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_employment_round_trip_strips_then_restores_authority_leaving_the_licence_active(api):
    """SUSPENDED strips the state authority, EMPLOYED restores it, the licence never moves.

    PRD 3.1: "A `LicensingAnalyst` updating an originator supplies a new
    `employment_status`, and because employment is an input to the authority
    computation, `authorized_state_codes` is recomputed immediately: moving an
    originator to `SUSPENDED` or `TERMINATED` strips every state authority it
    held, even though its licences remain untouched and still read `ACTIVE`. The
    update increments the originator's `version` by one."

    Design: Corner/endpoints/patch_originator_employment_status_round_trip_restores_authority
    """
    context = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    originator = context["originator"]
    originator_id = originator["id"]
    assert originator["employment_status"] == "EMPLOYED"
    assert originator["authorized_state_codes"] == ["CA"]
    version_at_start = originator["version"]

    suspended = validate_success(
        api.update_originator(originator_id, {"employment_status": "SUSPENDED"}, analyst_headers())
    )
    assert suspended["employment_status"] == "SUSPENDED"
    assert suspended["authorized_state_codes"] == []
    assert suspended["legal_name"] == originator["legal_name"]
    assert suspended["nmls_unique_id"] == originator["nmls_unique_id"]
    assert suspended["version"] == version_at_start + 1

    # The licence and the sponsorship are untouched by an employment change.
    licence = validate_success(
        api.get_license_registration(context["license"]["id"], analyst_headers())
    )
    assert licence["status"] == "ACTIVE"
    sponsorship = validate_success(
        api.get_sponsorship_transfer(context["sponsorship"]["id"], analyst_headers())
    )
    assert sponsorship["status"] == "ACTIVE"

    restored = validate_success(
        api.update_originator(originator_id, {"employment_status": "EMPLOYED"}, analyst_headers())
    )
    assert restored["employment_status"] == "EMPLOYED"
    assert restored["authorized_state_codes"] == ["CA"]
    assert restored["version"] == version_at_start + 2

    licence_after = validate_success(
        api.get_license_registration(context["license"]["id"], analyst_headers())
    )
    assert licence_after["status"] == "ACTIVE"
    assert _instant(licence_after["authority_effective_at"]) == _instant(CLOCK_STARTUP_INSTANT)


def test_authority_read_evaluates_at_the_supplied_as_of_instant(api):
    """The computed authority read answers for the instant asked about, not for "now".

    PRD 2.8: "It is read whenever an application is taken or locked, whenever an
    advertisement is published, and by the computed authority read, which reports
    `originator_id`, the instant it evaluated as `as_of`, the resulting
    `authorized_state_codes`, and the originator's `employment_status`. That read
    evaluates at the instant supplied as `as_of_iso8601` when the caller supplies
    one, and otherwise at the current logical clock instant."

    PRD 2.8 also fixes the geometry the three probes below straddle: "Both
    intervals — the licence interval running from `authority_effective_at` up to
    `expiration_date`, and the sponsorship interval running from `effective_at`
    up to `relinquished_at` — are **half-open**: the start instant is inside the
    interval and the end instant is outside it."

    Design: Corner/endpoints/authority_read_as_of_past_instant_excludes_later_sponsorship
    """
    context = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    originator_id = context["originator"]["id"]
    # Activation stamped authority from the clock, so authority starts here.
    assert _instant(context["license"]["authority_effective_at"]) == _instant(CLOCK_STARTUP_INSTANT)
    assert _instant(context["license"]["expiration_date"]) == _instant("2027-01-31T00:00:00Z")

    probes = (
        # Before authority_effective_at: the licence interval has not opened.
        ("2026-06-15T00:00:00Z", []),
        # Inside both intervals.
        ("2026-08-05T00:00:00Z", ["CA"]),
        # Exactly at expiration_date, which is outside the half-open interval.
        ("2027-01-31T00:00:00Z", []),
    )
    for as_of, expected_states in probes:
        data = validate_success(
            api.get_originator_authority(
                originator_id, officer_headers(), params={"as_of_iso8601": as_of}
            )
        )
        assert data["originator_id"] == originator_id
        assert _instant(data["as_of"]) == _instant(as_of), (
            f"the read must echo the instant it evaluated: asked {as_of}, got {data['as_of']}"
        )
        assert data["authorized_state_codes"] == expected_states, (
            f"authority at {as_of} should read {expected_states}"
        )
        assert data["employment_status"] == "EMPLOYED"

    # Omitting the parameter falls back to the current logical clock instant,
    # which is the start instant of the licence interval and therefore inside it.
    at_clock = validate_success(api.get_originator_authority(originator_id, officer_headers()))
    assert _instant(at_clock["as_of"]) == _instant(CLOCK_STARTUP_INSTANT)
    assert at_clock["authorized_state_codes"] == ["CA"]
    assert at_clock["employment_status"] == "EMPLOYED"


def test_advertisement_withdrawal_is_reachable_from_submitted_but_not_from_draft(api):
    """Compliance can pull copy once it has left draft, and only once.

    PRD 3.8: "Compliance can pull an advertisement at any point after it leaves
    draft: a `ComplianceOfficer` may withdraw one whose `status` is `SUBMITTED`,
    `APPROVED` or `PUBLISHED`, optionally supplying a `reason`, advancing it to
    `WITHDRAWN` and appending an `AD_DECIDED` audit entry whose `detail` records
    the withdrawal. `WITHDRAWN` is terminal."

    PRD 2.9 supplies the two distinct rejections: "The target row's current state
    has an outgoing transition matching the requested action — otherwise
    `ERR_INVALID_STATE_TRANSITION`." and "The target row is not already in one of
    its state machine's terminal states — otherwise `ERR_ALREADY_TERMINAL`."

    Design: Corner/endpoints/advertisement_withdraw_allowed_from_submitted_but_not_from_draft
    """
    originator = create_originator(api)
    originator_id = originator["id"]
    still_draft = draft_advertisement(
        api,
        originator_id,
        medium="WEB",
        content_text="Refinance options reviewed with you personally. APR varies by term.",
        target_state_codes=["CA"],
        disclosed_nmls_ids=[originator["nmls_unique_id"]],
    )
    to_withdraw = draft_advertisement(
        api,
        originator_id,
        medium="WEB",
        content_text="Purchase financing guidance from a licensed originator. APR varies by term.",
        target_state_codes=["CA"],
        disclosed_nmls_ids=[originator["nmls_unique_id"]],
    )
    assert still_draft["status"] == "DRAFT"
    submitted = submit_advertisement(api, to_withdraw["id"], originator_id)
    assert submitted["status"] == "SUBMITTED"

    # DRAFT has no outgoing withdrawal transition, and DRAFT is not terminal.
    validate_error(
        api.withdraw_advertisement(
            still_draft["id"], officer_headers(), {"reason": "Pulled before review."}
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    withdrawn = validate_success(
        api.withdraw_advertisement(
            to_withdraw["id"], officer_headers(), {"reason": "Disclosure review outstanding."}
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["reviewed_by_user_id"] is None
    assert withdrawn["published_at"] is None

    # WITHDRAWN is terminal, so the second attempt reports the terminal rejection.
    validate_error(
        api.withdraw_advertisement(
            to_withdraw["id"], officer_headers(), {"reason": "Pulled again."}
        ),
        ApiErrorId.ERR_ALREADY_TERMINAL.value,
    )

    assert (
        validate_success(api.get_advertisement(still_draft["id"], officer_headers()))["status"]
        == "DRAFT"
    )
    assert (
        validate_success(api.get_advertisement(to_withdraw["id"], officer_headers()))["status"]
        == "WITHDRAWN"
    )


def test_sweep_reports_empty_arrays_when_idle_and_never_applies_an_expiry_twice(api):
    """The operator sweep is safe to run with nothing to do, and safe to run again.

    PRD 3.9: "The sweep reports what it did so that a caller can verify the epoch
    advance without polling every collection: `swept_at` gives the instant it ran,
    and `expired_license_ids`, `relinquished_sponsorship_ids`, `suspended_loan_ids`,
    `opened_investigation_ids`, `escalated_inquiry_ids` and
    `unassigned_originator_ids` list the identifiers touched by each of the three
    sweeps. A sweep that finds nothing to do still succeeds, returning empty lists."

    PRD 3.9 also fixes what the licence arm does once the deadline has passed:
    "First, every licence whose `status` is `ACTIVE` or `RENEWAL_PENDING` and whose
    `expiration_date` is at or before the logical clock instant moves to `EXPIRED`
    and runs the full five-hop authority-lapse cascade of §3.1 — relinquish the
    `ACTIVE` sponsorship with `relinquished_at` stamped from the clock, clear the
    licence's denormalised sponsorship fields and recompute
    `authorized_state_codes`, suspend the originator's `TAKEN` and `LOCKED` loans
    in that state by setting `authority_flag` to `SUSPENDED`, open one `CASCADE`
    investigation with `trigger_reason` `AUTHORITY_LAPSE` per suspended loan, and
    recompute `open_investigation_count`"

    Design: Corner/endpoints/daily_license_sweep_reports_empty_arrays_and_does_not_double_apply
    """
    context = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    originator_id = context["originator"]["id"]
    licence_id = context["license"]["id"]
    sponsorship_id = context["sponsorship"]["id"]
    loan = take_loan(api, originator_id, state_code="CA")
    assert loan["status"] == "TAKEN"
    assert loan["authority_flag"] == "VERIFIED"

    idle = validate_success(api.run_daily_license_sweep(admin_headers()))
    assert _instant(idle["swept_at"]) == _instant(CLOCK_STARTUP_INSTANT)
    for field in SWEEP_REPORT_ARRAYS:
        assert idle[field] == [], f"an idle sweep must report {field} as an empty list"

    # Move past the licence's expiration_date and let the epoch advance.
    set_clock(api, "2027-02-01T00:00:00Z")
    applied = validate_success(api.run_daily_license_sweep(admin_headers()))
    assert _instant(applied["swept_at"]) == _instant("2027-02-01T00:00:00Z")
    assert applied["expired_license_ids"] == [licence_id]
    assert applied["relinquished_sponsorship_ids"] == [sponsorship_id]
    assert applied["suspended_loan_ids"] == [loan["id"]]
    assert len(applied["opened_investigation_ids"]) == 1, (
        "exactly one CASCADE investigation is opened per suspended loan: "
        f"{applied['opened_investigation_ids']}"
    )
    assert applied["escalated_inquiry_ids"] == []
    assert applied["unassigned_originator_ids"] == []
    investigation_id = applied["opened_investigation_ids"][0]

    # Nothing is left to expire, so the second run reports nothing at all.
    replayed = validate_success(api.run_daily_license_sweep(admin_headers()))
    assert _instant(replayed["swept_at"]) == _instant("2027-02-01T00:00:00Z")
    for field in SWEEP_REPORT_ARRAYS:
        assert replayed[field] == [], f"a replayed sweep must report {field} as an empty list"

    investigations, meta = validate_paginated(
        api.list_investigations(officer_headers(), params={"loan_application_id": loan["id"]})
    )
    assert meta["total_count"] == 1, "the replay must not open a second investigation"
    assert investigations[0]["id"] == investigation_id
    assert investigations[0]["opened_by"] == "CASCADE"
    assert investigations[0]["trigger_reason"] == "AUTHORITY_LAPSE"
    assert investigations[0]["status"] == "OPEN"
    assert investigations[0]["originator_id"] == originator_id

    licence_after = validate_success(
        api.get_license_registration(licence_id, analyst_headers())
    )
    assert licence_after["status"] == "EXPIRED"
    assert licence_after["active_sponsoring_institution_code"] is None
    assert licence_after["active_sponsorship_effective_at"] is None
    sponsorship_after = validate_success(
        api.get_sponsorship_transfer(sponsorship_id, analyst_headers())
    )
    assert sponsorship_after["status"] == "RELINQUISHED"
    assert _instant(sponsorship_after["relinquished_at"]) == _instant("2027-02-01T00:00:00Z")

    loan_after = validate_success(api.get_loan_application(loan["id"], officer_headers()))
    assert loan_after["status"] == "TAKEN", "the sweep touches authority, not the origination state"
    assert loan_after["authority_flag"] == "SUSPENDED"

    originator_after = validate_success(api.get_originator(originator_id, officer_headers()))
    assert originator_after["authorized_state_codes"] == []
    assert originator_after["open_investigation_count"] == 1


def test_manual_investigation_takes_its_originator_from_the_loan_it_names(api):
    """The parent link is derived from the named loan, and an unknown loan is a 404.

    PRD 3.9: "A manually opened investigation records `opened_by` as `MANUAL`,
    copies its `originator_id` from the named loan rather than accepting one from
    the caller, stamps `detected_at` from the logical clock, starts in `status`
    `OPEN`, and triggers a recompute of the originator's
    `open_investigation_count` — which at all times equals the number of that
    originator's investigations whose `status` is `OPEN` or `SUBSTANTIATED`."

    PRD 2.9 supplies the rejection for a body reference that resolves to nothing:
    "Every foreign-key id in the request body — `originator_id`, `ce_course_id`,
    `compensation_plan_id`, `loan_application_id` — resolves to an existing row,
    otherwise `ERR_REFERENCED_RESOURCE_NOT_FOUND`. This applies when filing a
    licence, filing a CE credit, taking an application, drafting an
    advertisement, recording an examination inquiry, assigning a compensation
    plan, and opening an investigation manually."

    Design: Corner/endpoints/manual_investigation_copies_originator_from_the_referenced_loan
    """
    context = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    originator_id = context["originator"]["id"]
    loan = take_loan(api, originator_id, state_code="CA")
    locked = lock_loan(api, loan["id"], originator_id)
    assert locked["status"] == "LOCKED"

    validate_error(
        api.create_investigation(
            {"loan_application_id": NON_EXISTENT_UUID, "trigger_reason": "MANUAL_REFERRAL"},
            officer_headers(),
        ),
        ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value,
    )

    created = validate_success(
        api.create_investigation(
            {"loan_application_id": loan["id"], "trigger_reason": "MANUAL_REFERRAL"},
            officer_headers(),
        ),
        201,
    )
    assert created["loan_application_id"] == loan["id"]
    assert created["originator_id"] == originator_id, (
        "the investigation's originator is copied from the loan, never supplied"
    )
    assert created["opened_by"] == "MANUAL"
    assert created["trigger_reason"] == "MANUAL_REFERRAL"
    assert created["status"] == "OPEN"
    assert _instant(created["detected_at"]) == _instant(CLOCK_STARTUP_INSTANT)
    assert created["finding_by_user_id"] is None
    assert created["remediated_at"] is None

    listed, meta = validate_paginated(
        api.list_investigations(
            officer_headers(), params={"originator_id": originator_id, "opened_by": "MANUAL"}
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == created["id"]

    originator_after = validate_success(api.get_originator(originator_id, officer_headers()))
    assert originator_after["open_investigation_count"] == 1

    # The loan itself is untouched by opening the investigation by hand.
    loan_after = validate_success(
        api.get_loan_application(loan["id"], make_originator_headers(originator_id))
    )
    assert loan_after["status"] == "LOCKED"
    assert loan_after["authority_flag"] == "VERIFIED"


def test_stale_expected_originator_version_rejects_the_assignment_and_writes_nothing(api):
    """Two employment writes drift the version; the 412 changes nothing and the replay succeeds.

    PRD 2.7: "The request must therefore carry `expected_originator_version` —
    again required, not optional — holding the `version` the client last observed
    on the parent `Originator`. If that value does not equal the originator's
    current `version`, the request is rejected with
    `ERR_STALE_ORIGINATOR_VERSION` (HTTP 412), because a stale writer would
    otherwise re-point `compensation_plan_id` across an assignment interval it
    never observed."

    PRD 3.3 fixes what the accepted write does: "A successful assignment writes
    `assigned_originator_id`, `assignment_effective_from` and
    `assignment_effective_to` onto the plan, sets the originator's
    `compensation_plan_id` to the assigned plan, and increments the originator's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_originator_version_on_plan_assignment_returns_412_and_fresh_read_succeeds
    """
    originator = create_originator(api)
    originator_id = originator["id"]
    version_at_create = originator["version"]
    plan = setup_approved_plan(
        api,
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
        volume_tier_enabled=False,
        concession_absorption_enabled=False,
    )
    assert plan["status"] == "ACTIVE"
    assert plan["assigned_originator_id"] is None

    # The version the client last observed.
    observed = validate_success(api.get_originator(originator_id, officer_headers()))
    assert observed["version"] == version_at_create
    assert observed["compensation_plan_id"] is None

    first_patch = validate_success(
        api.update_originator(originator_id, {"employment_status": "SUSPENDED"}, analyst_headers())
    )
    assert first_patch["version"] == version_at_create + 1
    second_patch = validate_success(
        api.update_originator(originator_id, {"employment_status": "EMPLOYED"}, analyst_headers())
    )
    assert second_patch["version"] == version_at_create + 2

    assignment = {
        "compensation_plan_id": plan["id"],
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-12-31T00:00:00Z",
        "expected_originator_version": observed["version"],
    }
    validate_error(
        api.assign_compensation_plan(originator_id, assignment, officer_headers()),
        ApiErrorId.ERR_STALE_ORIGINATOR_VERSION.value,
    )

    # The rejection wrote nothing at all, not even a version bump.
    after_412 = validate_success(api.get_originator(originator_id, officer_headers()))
    assert after_412["version"] == version_at_create + 2
    assert after_412["compensation_plan_id"] is None
    plan_after_412 = validate_success(api.get_compensation_plan(plan["id"], officer_headers()))
    assert plan_after_412["assigned_originator_id"] is None
    assert plan_after_412["assignment_effective_from"] is None
    assert plan_after_412["assignment_effective_to"] is None

    replay = dict(assignment, expected_originator_version=after_412["version"])
    assigned = validate_success(
        api.assign_compensation_plan(originator_id, replay, officer_headers())
    )
    assert assigned["id"] == originator_id, "the response to an assignment is the updated originator"
    assert assigned["compensation_plan_id"] == plan["id"]
    assert assigned["version"] == version_at_create + 3

    plan_after = validate_success(api.get_compensation_plan(plan["id"], officer_headers()))
    assert plan_after["status"] == "ACTIVE"
    assert plan_after["assigned_originator_id"] == originator_id
    assert _instant(plan_after["assignment_effective_from"]) == _instant("2026-08-01T00:00:00Z")
    assert _instant(plan_after["assignment_effective_to"]) == _instant("2026-12-31T00:00:00Z")
