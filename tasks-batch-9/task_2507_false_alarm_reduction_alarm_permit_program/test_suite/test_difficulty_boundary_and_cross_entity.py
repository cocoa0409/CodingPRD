"""Boundary-precision and cross-entity-state behaviour of the permit program.

Each test in this module pins one exact comparison boundary — a cap tested
strictly, an inclusive threshold, an inclusive distinct-contact minimum, an
inclusive delinquency day count — or one place where the state of a sibling
entity decides whether an otherwise legitimate transition is allowed.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, get_success_data, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

# The program's own conventions: the first permit is issued at this instant, so
# the 30-day new-installation grace runs through 2026-08-31 and a chargeable
# occurrence must fall strictly after it.
INSTALLED_AT = "2026-08-01T00:00:00Z"
FIRST_OCCURRENCE = "2026-09-15T02:00:00Z"
SECOND_OCCURRENCE = "2026-09-18T02:00:00Z"

# A schedule whose invoices are never allowed to age into dunning, so a test
# about something other than delinquency is not perturbed by it.
NEVER_DUE_DAYS = 3650

CAP_SCHEDULE_OVERRIDES = {
    "effective_from": INSTALLED_AT,
    "free_alarm_allowance": 0,
    "per_incident_fee_cap_cents": 15000,
    "invoice_due_days": NEVER_DUE_DAYS,
    "fee_tiers": [
        {"from_index": 1, "to_index": 1, "base_fee_cents": 12000},
        {"from_index": 2, "to_index": None, "base_fee_cents": 12800},
    ],
}


def _school_site_at_the_cap(api):
    """A SCHOOL premises with two permitted systems under the cap schedule."""
    return X.setup_program_baseline(
        api,
        clock=FIRST_OCCURRENCE,
        installed_at=INSTALLED_AT,
        schedule_overrides=dict(CAP_SCHEDULE_OVERRIDES),
        site_overrides={"occupancy_class": "SCHOOL"},
        contact_count=2,
        system_count=2,
    )


def test_school_fee_landing_exactly_on_the_per_incident_cap_is_not_flagged_capped(api):
    """A first SCHOOL occurrence priced at exactly the cap passes through uncapped.

    PRD §3.5: "Fourth, the cap and the aggravation: the cap is treated as
    applied only when the rounded amount is **strictly greater** than
    `per_incident_fee_cap_cents`, so an amount exactly equal to the cap passes
    through unchanged and is not flagged as capped; the amount is then clipped
    to the cap"

    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`,
    rounded half up once on the already-rounded subtotal, and clamped upward to
    `admin_fee_min_cents` and downward to `admin_fee_max_cents`"

    Occurrence 1 takes the 12000-cent tier; the free allowance is 0 so the tier
    base is not forced to zero. The SCHOOL occupancy multiplier is 1.25 and the
    two other factors are 1, so the single rounded product is 12000 x 1.25 =
    15000 cents. That equals `per_incident_fee_cap_cents` of 15000 and is not
    strictly greater than it, so `cap_applied` must be false. The invoice
    carries a 15000-cent subtotal, a 750-cent administrative fee (15000 x 0.05,
    inside the 500..5000 clamp) and a 15750-cent assessment.

    Design: Difficulty/boundary_precision_check/per_incident_cap_is_strict_so_a_fee_landing_exactly_on_the_cap_is_not_flagged_capped
    """
    bundle = _school_site_at_the_cap(api)

    incidents = X.accumulate_counted_incidents(
        api, bundle, [FIRST_OCCURRENCE], cause_code="EQUIPMENT_MALFUNCTION"
    )
    incident = X.get_incident(api, incidents[0].incident_id)

    assert incident["occurrence_index"] == 1, (
        f"the first chargeable occurrence must be index 1, got {incident['occurrence_index']!r}"
    )
    A.assert_money_cents(incident["assessed_fee_cents"], 15000, "assessed_fee_cents")
    A.assert_fee_basis(
        incident["fee_basis"],
        tier_base_cents=12000,
        occupancy_multiplier=1.25,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        aggravation_cents=0,
        cap_applied=False,
    )

    invoice = X.invoice_for_incident(api, incidents[0].incident_id)
    A.assert_invoice_totals(
        invoice, subtotal_cents=15000, admin_fee_cents=750, assessed_cents=15750
    )
    A.assert_outstanding_identity(invoice)


def test_school_fee_one_step_above_the_per_incident_cap_is_clamped_and_flagged_capped(api):
    """A second SCHOOL occurrence priced one step above the cap is clamped and flagged.

    PRD §3.5: "Fourth, the cap and the aggravation: the cap is treated as
    applied only when the rounded amount is **strictly greater** than
    `per_incident_fee_cap_cents`, so an amount exactly equal to the cap passes
    through unchanged and is not flagged as capped; the amount is then clipped
    to the cap"

    PRD §3.8: "and when the incident's `fee_basis` records `cap_applied`, that
    line's `extended_cents` is overridden to `per_incident_fee_cap_cents`"

    Occurrence 2 takes the open-ended 12800-cent tier, so the rounded product is
    12800 x 1.25 = 16000 cents, which is strictly greater than the 15000-cent
    cap: `cap_applied` must be true and the amount is clipped back to 15000, the
    identical money the uncapped first occurrence produced. The capped line is
    written at the cap, so the invoice is again 15000 + 750 = 15750 cents, and
    the premises then owes 2 x 15750 fee invoices plus 2 x 5500 permit-issue
    invoices, that is 42500 cents.

    Design: Difficulty/boundary_precision_check/per_incident_cap_is_strict_so_a_fee_landing_exactly_on_the_cap_is_not_flagged_capped
    """
    bundle = _school_site_at_the_cap(api)

    incidents = X.accumulate_counted_incidents(
        api, bundle, [FIRST_OCCURRENCE, SECOND_OCCURRENCE], cause_code="EQUIPMENT_MALFUNCTION"
    )
    second = X.get_incident(api, incidents[1].incident_id)

    assert second["occurrence_index"] == 2, (
        f"the second chargeable occurrence must be index 2, got {second['occurrence_index']!r}"
    )
    A.assert_money_cents(second["assessed_fee_cents"], 15000, "assessed_fee_cents")
    A.assert_fee_basis(
        second["fee_basis"],
        tier_base_cents=12800,
        occupancy_multiplier=1.25,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        aggravation_cents=0,
        cap_applied=True,
    )

    for incident_bundle in incidents:
        invoice = X.invoice_for_incident(api, incident_bundle.incident_id)
        A.assert_invoice_totals(
            invoice, subtotal_cents=15000, admin_fee_cents=750, assessed_cents=15750
        )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 42500, "outstanding_balance_cents")


PROBATION_SCHEDULE_OVERRIDES = {
    "effective_from": INSTALLED_AT,
    "free_alarm_allowance": 0,
    "probation_threshold_count": 2,
    "suspension_threshold_count": 6,
    "invoice_due_days": NEVER_DUE_DAYS,
    "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 10000}],
}


def _two_reported_incidents_under_a_threshold_of_two(api):
    """Two reported incidents standing before either determination is made.

    Both dispatch requests are submitted, validated and dispatched while the
    premises is still ``RESPONSE_ACTIVE``, so the raised call-back minimum that
    probation would impose can never interfere with the second request.
    """
    bundle = X.setup_program_baseline(
        api,
        clock=FIRST_OCCURRENCE,
        installed_at=INSTALLED_AT,
        schedule_overrides=dict(PROBATION_SCHEDULE_OVERRIDES),
        contact_count=2,
        system_count=2,
    )
    first = X.create_reported_incident(
        api, bundle, bundle.system_ids[0], FIRST_OCCURRENCE, cause_code="UNKNOWN"
    )
    second = X.create_reported_incident(
        api, bundle, bundle.system_ids[1], X.plus_hours(FIRST_OCCURRENCE, 3), cause_code="UNKNOWN"
    )
    return bundle, first, second


def test_one_counted_incident_below_the_probation_threshold_leaves_the_posture_active(api):
    """A window count of 1 against a probation threshold of 2 keeps the premises active.

    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above
    `probation_threshold_count`, the posture is `RESPONSE_PROBATION`."

    PRD §3.5: "Both thresholds are inclusive: with the defaults, a window count
    of 4 puts the premises on probation and 3 does not, and a count of 6
    proposes a suspension while 5 does not."

    With `probation_threshold_count` configured at 2, the first chargeable
    determination leaves `chargeable_count_window` at 1, and 1 is below 2, so
    the posture must still read `RESPONSE_ACTIVE` one step short of the flip.

    Design: Difficulty/boundary_precision_check/probation_threshold_is_inclusive_so_the_second_counted_incident_flips_the_posture
    """
    bundle, first, _second = _two_reported_incidents_under_a_threshold_of_two(api)

    X.determine_counted(api, first.incident_id)

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 1, (
        f"chargeable_count_window expected 1, got {site['chargeable_count_window']!r}"
    )
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")


def test_the_second_counted_incident_meets_the_inclusive_probation_threshold(api):
    """The determination that makes the window count exactly 2 flips the posture.

    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above
    `probation_threshold_count`, the posture is `RESPONSE_PROBATION`."

    PRD §3.5: "Both thresholds are inclusive: with the defaults, a window count
    of 4 puts the premises on probation and 3 does not, and a count of 6
    proposes a suspension while 5 does not."

    PRD §3.5: "And when `chargeable_count_window` reaches or exceeds
    `suspension_threshold_count`, an enforcement order is auto-proposed for the
    premises"

    The second chargeable determination takes `chargeable_count_window` to
    exactly 2, which is at the inclusive `probation_threshold_count` of 2, so
    the posture must become `RESPONSE_PROBATION`. The count of 2 is still well
    below `suspension_threshold_count` of 6, so no enforcement order may be
    proposed. Occurrence 2 sits in the single open-ended tier, so its fee is
    10000 x 1.00 = 10000 cents.

    Design: Difficulty/boundary_precision_check/probation_threshold_is_inclusive_so_the_second_counted_incident_flips_the_posture
    """
    bundle, first, second = _two_reported_incidents_under_a_threshold_of_two(api)

    X.determine_counted(api, first.incident_id)
    X.determine_counted(api, second.incident_id)

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 2, (
        f"chargeable_count_window expected 2, got {site['chargeable_count_window']!r}"
    )
    A.assert_status(site, "RESPONSE_PROBATION", field="response_status")

    A.assert_total_count(
        api.list_suspension_orders(U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id}), 0
    )

    incident = X.get_incident(api, second.incident_id)
    assert incident["occurrence_index"] == 2, (
        f"occurrence_index expected 2, got {incident['occurrence_index']!r}"
    )
    A.assert_money_cents(incident["assessed_fee_cents"], 10000, "assessed_fee_cents")


ECV_CLOCK = "2026-09-15T00:00:00Z"


def _site_with_exactly_two_callable_contacts(api):
    """A premises whose live callable roster is exactly the minimum of 2.

    Two permitted systems, so each dispatch request stays open on a system of
    its own and neither pre-empts the other.
    """
    return X.setup_program_baseline(
        api,
        clock=ECV_CLOCK,
        installed_at=INSTALLED_AT,
        schedule_overrides={"effective_from": INSTALLED_AT, "invoice_due_days": NEVER_DUE_DAYS},
        contact_count=2,
        system_count=2,
    )


def test_two_ecv_calls_to_one_contact_fall_one_short_of_the_distinct_minimum(api):
    """Two eligible attempts on a single contact leave the distinct count at 1.

    PRD §3.4: "Two consequences follow directly and are both intended: a log of
    two calls placed to the *same* contact yields a distinct count of 1 and is
    therefore insufficient for a two-call request even though two calls really
    were made, while a log of exactly two calls to *different* contacts yields
    2, meets the inclusive threshold and is sufficient."

    PRD §3.4: "Validation requires the frozen `ecv_sufficient` to be true, else
    `ERR_ECV_REQUIREMENT_NOT_MET`; the premises posture not to be
    `RESPONSE_SUSPENDED`, else `ERR_POLICE_RESPONSE_SUSPENDED`; the monitoring
    company to be `ACTIVE` or `PROBATION`, else
    `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED`; and the verified-response proof
    to match what the system demands — `audio_video_evidence` true when the
    system's `verified_response_mode` is `AUDIO_VIDEO_REQUIRED`,
    `guard_on_scene` true when it is `GUARD_REQUIRED` — else
    `ERR_VERIFIED_RESPONSE_NOT_CONFIRMED`."

    Both attempts name the first contact, and both `NO_ANSWER` and `VOICEMAIL`
    are declared eligible outcomes, so two attempts survive the filter but only
    1 distinct contact identifier does — one short of the inclusive minimum of 2
    that `TWO_CALL_ECV` demands. Validation must therefore be refused and the
    request must be left exactly as it was.

    Design: Difficulty/boundary_precision_check/two_ecv_calls_to_one_contact_fall_one_short_of_the_inclusive_distinct_minimum
    """
    bundle = _site_with_exactly_two_callable_contacts(api)
    occurred_at = "2026-09-15T01:00:00Z"

    request_id = X.submit_dispatch_request(
        api,
        bundle,
        bundle.system_ids[0],
        occurred_at,
        call_attempts=[
            F.call_attempt(bundle.contact_ids[0], "2026-09-15T01:01:00Z", "NO_ANSWER"),
            F.call_attempt(bundle.contact_ids[0], "2026-09-15T01:04:00Z", "VOICEMAIL"),
        ],
    )

    before = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    assert before["distinct_ecv_contact_count"] == 1, (
        f"distinct_ecv_contact_count expected 1, got {before['distinct_ecv_contact_count']!r}"
    )
    assert before["ecv_sufficient"] is False, (
        f"ecv_sufficient expected False, got {before['ecv_sufficient']!r}"
    )

    validate_error(
        api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR),
        E.ERR_ECV_REQUIREMENT_NOT_MET,
        expected_status=422,
    )

    after = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(after, "SUBMITTED")
    assert after["validated_at"] is None, (
        f"validated_at must stay null on a refused validation, got {after['validated_at']!r}"
    )


def test_two_ecv_calls_to_two_contacts_meet_the_inclusive_distinct_minimum(api):
    """The same two attempts split across two contacts reach the inclusive minimum of 2.

    PRD §3.4: "Two consequences follow directly and are both intended: a log of
    two calls placed to the *same* contact yields a distinct count of 1 and is
    therefore insufficient for a two-call request even though two calls really
    were made, while a log of exactly two calls to *different* contacts yields
    2, meets the inclusive threshold and is sufficient."

    PRD §3.4: "A `PoliceDispatchSupervisor` may validate it, moving `SUBMITTED →
    VALIDATED` and stamping `validated_at` with the logical clock and
    `validated_by_user_id` with the acting `X-User-ID`."

    One attempt against each of the two callable contacts yields a distinct
    count of exactly 2, which meets and does not exceed the inclusive threshold
    for `TWO_CALL_ECV`, so the frozen `ecv_sufficient` is true and the request
    validates, stamping `validated_at` at the logical clock of 2026-09-15.

    Design: Difficulty/boundary_precision_check/two_ecv_calls_to_one_contact_fall_one_short_of_the_inclusive_distinct_minimum
    """
    bundle = _site_with_exactly_two_callable_contacts(api)
    occurred_at = "2026-09-15T02:00:00Z"

    request_id = X.submit_dispatch_request(
        api,
        bundle,
        bundle.system_ids[1],
        occurred_at,
        call_attempts=[
            F.call_attempt(bundle.contact_ids[0], "2026-09-15T02:01:00Z", "NO_ANSWER"),
            F.call_attempt(bundle.contact_ids[1], "2026-09-15T02:04:00Z", "VOICEMAIL"),
        ],
    )

    before = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    assert before["distinct_ecv_contact_count"] == 2, (
        f"distinct_ecv_contact_count expected 2, got {before['distinct_ecv_contact_count']!r}"
    )
    assert before["ecv_sufficient"] is True, (
        f"ecv_sufficient expected True, got {before['ecv_sufficient']!r}"
    )

    validated = A.data_of(api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR), 200)
    A.assert_status(validated, "VALIDATED")
    assert validated["validated_at"] == ECV_CLOCK, (
        f"validated_at expected {ECV_CLOCK}, got {validated['validated_at']!r}"
    )


REFERRAL_SCHEDULE_OVERRIDES = {
    "effective_from": "2026-01-01T00:00:00Z",
    "permit_issue_fee_cents": 21645,
    "invoice_due_days": 30,
    "delinquency_days": 90,
    "collections_referral_threshold_cents": 25000,
}
REFERRAL_AGENCY = "Lakeside Recovery Partners"


def _invoice_at_final_notice_on_day_eighty_nine(api):
    """A permit-issue invoice sitting at exactly the referral threshold, 89 days late.

    Issued at 21645 + 1082 admin = 22727 cents due on 2026-01-31; the nightly run
    of 2026-02-01 adds the one-time late penalty of 2273 and moves the invoice to
    NOTICE, the run of 2026-03-05 moves it to FINAL_NOTICE, and the run of
    2026-04-30 leaves it one day short of the 90-day delinquency point.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides=dict(REFERRAL_SCHEDULE_OVERRIDES),
        contact_count=2,
        system_count=1,
    )
    invoices = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(invoices) == 1, f"expected one permit-issue invoice, got {len(invoices)}"
    invoice_id = invoices[0]["id"]

    for instant in ("2026-02-01T00:00:00Z", "2026-03-05T00:00:00Z", "2026-04-30T00:00:00Z"):
        X.set_clock(api, instant)
        X.run_nightly(api)

    return bundle, invoice_id


def test_collections_referral_is_refused_on_day_eighty_nine(api):
    """An invoice already at the referral threshold is still refused referral at 89 days.

    PRD §3.8: "Every criterion must hold together: `collections_stage` must be
    `FINAL_NOTICE`, `days_delinquent` at or above `delinquency_days`, and
    `outstanding_cents` at or above `collections_referral_threshold_cents`, else
    `ERR_REFERRAL_CRITERIA_NOT_MET`; the linked incident must not be `APPEALED`,
    else `ERR_INVOICE_UNDER_APPEAL`; and a written-off invoice may not be
    referred, else `ERR_INVOICE_WRITTEN_OFF`."

    PRD §2.6: "Because the run is idempotent with respect to money — the late
    penalty is applied at most once per invoice — running it twice on the same
    logical instant does not double-charge anyone."

    The invoice is assessed at 21645 plus round_half_up(21645 x 0.05) = 1082
    admin, that is 22727 cents, due 30 days after 2026-01-01, so 2026-01-31. The
    first nightly run adds round_half_up(22727 x 0.10) = 2273, taking both
    `assessed_cents` and `outstanding_cents` to exactly 25000 — already at the
    25000-cent referral threshold. Three nightly runs must still leave a single
    2273-cent late penalty. From 2026-01-31 to 2026-04-30 is 89 whole days,
    one short of `delinquency_days` of 90, so referral must be refused.

    Design: Difficulty/boundary_precision_check/collections_referral_needs_day_ninety_exactly_not_day_eighty_nine
    """
    _bundle, invoice_id = _invoice_at_final_notice_on_day_eighty_nine(api)

    before = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        before,
        subtotal_cents=21645,
        admin_fee_cents=1082,
        assessed_cents=25000,
        outstanding_cents=25000,
        collections_stage="FINAL_NOTICE",
    )
    A.assert_money_cents(before["late_penalty_cents"], 2273, "late_penalty_cents")
    assert X.same_instant(before["due_on"], "2026-01-31T00:00:00Z"), (
        f"due_on expected 2026-01-31T00:00:00Z, got {before['due_on']!r}"
    )
    assert before["days_delinquent"] == 89, (
        f"days_delinquent expected 89 at clock 2026-04-30, got {before['days_delinquent']!r}"
    )

    validate_error(
        api.refer_invoice_to_collections(
            invoice_id, {"referral_agency": REFERRAL_AGENCY}, U.BILLING_CLERK
        ),
        E.ERR_REFERRAL_CRITERIA_NOT_MET,
        expected_status=409,
    )

    after = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(after, collections_stage="FINAL_NOTICE")
    assert after["referred_on"] is None, (
        f"referred_on must stay null after a refused referral, got {after['referred_on']!r}"
    )
    A.assert_money_cents(after["late_penalty_cents"], 2273, "late_penalty_cents")


def test_collections_referral_is_accepted_on_day_ninety_exactly(api):
    """The same invoice becomes referable the moment days delinquent reaches exactly 90.

    PRD §3.8: "Every criterion must hold together: `collections_stage` must be
    `FINAL_NOTICE`, `days_delinquent` at or above `delinquency_days`, and
    `outstanding_cents` at or above `collections_referral_threshold_cents`, else
    `ERR_REFERRAL_CRITERIA_NOT_MET`; the linked incident must not be `APPEALED`,
    else `ERR_INVOICE_UNDER_APPEAL`; and a written-off invoice may not be
    referred, else `ERR_INVOICE_WRITTEN_OFF`."

    PRD §3.8: "Both tier bounds sit with the lower comparison: exactly 25000
    takes the 2000-cent flat charge, 25001 takes the 0.08 rate, exactly 100000
    still takes the 0.08 rate for 8000 cents, and 100001 takes the 10000-cent
    flat charge."

    PRD §3.8: "And `referral_total_cents` is what the agency is handed, not what
    the premises owes the city: it does not feed `outstanding_cents`, so the
    premises' `outstanding_balance_cents` is untouched by the collections
    charge."

    From 2026-01-31 to 2026-05-01 is exactly 90 whole days, which meets the
    inclusive `delinquency_days` of 90, so the referral is accepted. The interim
    total after the late penalty is 25000, which sits at the inclusive lower
    bound, so the collections charge is the flat 2000 cents and
    `referral_total_cents` is 25000 + 2000 = 27000, while `outstanding_cents`
    and the premises' balance both stay at 25000.

    Design: Difficulty/boundary_precision_check/collections_referral_needs_day_ninety_exactly_not_day_eighty_nine
    """
    bundle, invoice_id = _invoice_at_final_notice_on_day_eighty_nine(api)

    X.set_clock(api, "2026-05-01T00:00:00Z")
    X.run_nightly(api)

    referred = A.data_of(
        api.refer_invoice_to_collections(
            invoice_id, {"referral_agency": REFERRAL_AGENCY}, U.BILLING_CLERK
        ),
        200,
    )
    A.assert_invoice_totals(referred, collections_stage="REFERRED", outstanding_cents=25000)
    assert referred["referral_agency"] == REFERRAL_AGENCY, (
        f"referral_agency expected {REFERRAL_AGENCY!r}, got {referred['referral_agency']!r}"
    )
    assert referred["days_delinquent"] == 90, (
        f"days_delinquent expected 90 at clock 2026-05-01, got {referred['days_delinquent']!r}"
    )
    A.assert_money_cents(referred["referral_total_cents"], 27000, "referral_total_cents")
    A.assert_money_cents(referred["late_penalty_cents"], 2273, "late_penalty_cents")

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 25000, "outstanding_balance_cents")


SIBLING_SCHEDULE_OVERRIDES = {
    "effective_from": INSTALLED_AT,
    "free_alarm_allowance": 0,
    "probation_threshold_count": 4,
    "suspension_threshold_count": 1,
    "invoice_due_days": NEVER_DUE_DAYS,
    "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 10000}],
}
SIBLING_SUSPENDED_CLOCK = "2026-09-30T00:00:00Z"


def _validated_request_overtaken_by_a_sibling_suspension(api):
    """A request validated before an order that a different system's incident raised.

    Request R is validated on system B on 2026-09-15 while the premises is still
    RESPONSE_ACTIVE and is then left alone. System A's incident is ruled
    chargeable on 2026-09-16, which auto-proposes an order for
    2026-09-26 .. 2026-10-26; it is served on 2026-09-20 and the clock then moves
    to 2026-09-30, inside the interval.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-15T00:00:00Z",
        installed_at=INSTALLED_AT,
        schedule_overrides=dict(SIBLING_SCHEDULE_OVERRIDES),
        contact_count=2,
        system_count=2,
    )
    pending_id = X.submit_dispatch_request(
        api, bundle, bundle.system_ids[1], "2026-09-15T01:00:00Z"
    )
    validate_success(api.validate_dispatch_request(pending_id, U.DISPATCH_SUPERVISOR), 200)

    X.set_clock(api, "2026-09-16T00:00:00Z")
    triggering = X.create_reported_incident(
        api, bundle, bundle.system_ids[0], "2026-09-16T01:00:00Z", cause_code="UNKNOWN"
    )
    X.determine_counted(api, triggering.incident_id)

    proposed = A.assert_total_count(
        api.list_suspension_orders(
            U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id, "status": "PROPOSED"}
        ),
        1,
    )
    order_id = proposed[0]["id"]

    X.set_clock(api, "2026-09-20T00:00:00Z")
    validate_success(api.serve_suspension_order(order_id, U.PROGRAM_ADMIN), 200)
    X.set_clock(api, SIBLING_SUSPENDED_CLOCK)
    return bundle, pending_id, order_id


def test_sibling_system_suspension_order_blocks_recording_the_dispatch(api):
    """An order raised by another system's incident stops a patrol already validated.

    PRD §3.4: "Recording the dispatch moves `VALIDATED → DISPATCHED` and stamps
    `dispatched_at` with the logical clock; it requires that the premises posture
    is still not `RESPONSE_SUSPENDED` at the moment of dispatch, else
    `ERR_POLICE_RESPONSE_SUSPENDED`, because a suspension served between
    validation and dispatch must stop the patrol."

    PRD §3.5: "If the premises has a suspension order in `EFFECTIVE` or
    `REINSTATEMENT_PENDING` whose closed interval contains the current instant,
    the posture is `RESPONSE_SUSPENDED`."

    Nothing about the request itself changed between its validation on
    2026-09-15 and this call on 2026-09-30: the only new fact in the world is
    that an order raised from a different system's incident at the same premises
    became `EFFECTIVE` over the interval 2026-09-26 to 2026-10-26, which contains
    2026-09-30. The refusal must therefore leave the request exactly as it was.

    Design: Difficulty/cross_entity_state_dependency/record_dispatch_of_a_sibling_system_request_is_gated_by_the_sites_suspension_order
    """
    bundle, pending_id, _order_id = _validated_request_overtaken_by_a_sibling_suspension(api)

    A.assert_status(X.get_site(api, bundle.site_id), "RESPONSE_SUSPENDED", field="response_status")

    validate_error(
        api.record_dispatch(pending_id, U.DISPATCH_SUPERVISOR),
        E.ERR_POLICE_RESPONSE_SUSPENDED,
        expected_status=409,
    )

    after = A.data_of(api.get_dispatch_request(pending_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(after, "VALIDATED")
    assert after["dispatched_at"] is None, (
        f"dispatched_at must stay null on a refused dispatch, got {after['dispatched_at']!r}"
    )


def test_vacating_the_sibling_suspension_order_releases_the_same_record_dispatch(api):
    """Vacating that sibling order lets the identical call succeed a moment later.

    PRD §3.7: "From `EFFECTIVE` or `REINSTATEMENT_PENDING` the
    `REINSTATEMENT_FEE` invoice carrying that `suspension_order_id` is voided and
    its allocations reversed into the premises' `credit_balance_cents`."

    PRD §3.7: "In neither case is `lifted_suspension_count` incremented: a
    vacated order never counted as a suspension at all."

    PRD §3.5: "Orders in `VACATED` or `EXPIRED` are ignored entirely, and a
    premises with no pinned schedule is `RESPONSE_ACTIVE`."

    PRD §3.4: "Recording the dispatch moves `VALIDATED → DISPATCHED` and stamps
    `dispatched_at` with the logical clock; it requires that the premises posture
    is still not `RESPONSE_SUSPENDED` at the moment of dispatch, else
    `ERR_POLICE_RESPONSE_SUSPENDED`, because a suspension served between
    validation and dispatch must stop the patrol."

    Once the order is `VACATED` the posture cascade ignores it, and the premises'
    `chargeable_count_window` of 1 is below `probation_threshold_count` of 4, so
    the posture falls back to `RESPONSE_ACTIVE` and the same record-dispatch call
    that was refused now succeeds, stamping `dispatched_at` at the logical clock
    of 2026-09-30.

    Design: Difficulty/cross_entity_state_dependency/record_dispatch_of_a_sibling_system_request_is_gated_by_the_sites_suspension_order
    """
    bundle, pending_id, order_id = _validated_request_overtaken_by_a_sibling_suspension(api)

    validate_error(
        api.record_dispatch(pending_id, U.DISPATCH_SUPERVISOR),
        E.ERR_POLICE_RESPONSE_SUSPENDED,
        expected_status=409,
    )

    vacated = A.data_of(
        api.vacate_suspension_order(
            order_id,
            {
                "vacated_reason": (
                    "Order withdrawn by the program administrator after review of "
                    "the counting basis."
                )
            },
            U.PROGRAM_ADMIN,
        ),
        200,
    )
    A.assert_status(vacated, "VACATED")

    reinstatement_invoices = X.invoices_of_site(api, bundle.site_id, kind="REINSTATEMENT_FEE")
    assert len(reinstatement_invoices) == 1, (
        f"expected one reinstatement invoice, got {len(reinstatement_invoices)}"
    )
    A.assert_invoice_totals(reinstatement_invoices[0], payment_status="VOIDED")

    site = X.get_site(api, bundle.site_id)
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")
    assert site["lifted_suspension_count"] == 0, (
        f"a vacated order must not count as a lifted suspension, got "
        f"{site['lifted_suspension_count']!r}"
    )

    dispatched = A.data_of(api.record_dispatch(pending_id, U.DISPATCH_SUPERVISOR), 200)
    A.assert_status(dispatched, "DISPATCHED")
    assert dispatched["dispatched_at"] == SIBLING_SUSPENDED_CLOCK, (
        f"dispatched_at expected {SIBLING_SUSPENDED_CLOCK}, got {dispatched['dispatched_at']!r}"
    )


LIFT_SCHEDULE_OVERRIDES = {
    "effective_from": INSTALLED_AT,
    "free_alarm_allowance": 0,
    "probation_threshold_count": 4,
    "suspension_threshold_count": 1,
    "invoice_due_days": NEVER_DUE_DAYS,
    "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 10000}],
    "reinstatement_base_fee_cents": 60000,
    "reinstatement_escalation_pct": 0.50,
}
LIFT_INCIDENT_CLOCK = "2026-09-15T00:00:00Z"
LIFT_REQUEST_CLOCK = "2026-09-30T00:00:00Z"
LIFT_ATTEMPT_CLOCK = "2026-10-01T00:00:00Z"


def _reinstatement_pending_with_one_unpaid_permit_invoice(api):
    """An order in REINSTATEMENT_PENDING whose own two invoices are settled.

    The premises' PERMIT_ISSUE_FEE invoice of 5000 + 500 admin = 5500 is left
    unpaid on purpose. The counted incident of 2026-09-15 raises a 10000-cent fee
    with 500 admin = 10500 and, because `suspension_threshold_count` is 1, an
    order for 2026-09-25 .. 2026-10-25 that is served on 2026-09-20 for a
    reinstatement fee of 60000 * (1 + 0.50 * 0) = 60000 plus 3000 admin = 63000.
    A 73500-cent explicit tender settles exactly the fee and reinstatement
    invoices and deliberately leaves the permit invoice alone.
    """
    bundle = X.setup_program_baseline(
        api,
        clock=LIFT_INCIDENT_CLOCK,
        installed_at=INSTALLED_AT,
        schedule_overrides=dict(LIFT_SCHEDULE_OVERRIDES),
        contact_count=2,
        system_count=1,
    )
    permit_invoices = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(permit_invoices) == 1, (
        f"expected one permit-issue invoice, got {len(permit_invoices)}"
    )
    permit_invoice_id = permit_invoices[0]["id"]

    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, "2026-09-15T01:00:00Z", cause_code="OPERATOR_ERROR"
    )
    fee_invoice_id = X.invoice_for_incident(api, incident.incident_id)["id"]

    proposed = A.assert_total_count(
        api.list_suspension_orders(
            U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id, "status": "PROPOSED"}
        ),
        1,
    )
    order_id = proposed[0]["id"]

    X.set_clock(api, "2026-09-20T00:00:00Z")
    validate_success(api.serve_suspension_order(order_id, U.PROGRAM_ADMIN), 200)
    reinstatement_invoices = X.invoices_of_site(api, bundle.site_id, kind="REINSTATEMENT_FEE")
    assert len(reinstatement_invoices) == 1, (
        f"expected one reinstatement invoice, got {len(reinstatement_invoices)}"
    )
    reinstatement_invoice_id = reinstatement_invoices[0]["id"]

    X.set_clock(api, LIFT_REQUEST_CLOCK)
    pending = A.data_of(
        api.request_reinstatement(
            order_id,
            {
                "technician_inspection_date": "2026-09-28T00:00:00Z",
                "ecv_attestation": True,
                "corrective_action_summary": (
                    "Panel replaced, zone 3 contact re-seated, keyholder list re-verified."
                ),
            },
            bundle.holder_headers,
        ),
        200,
    )
    A.assert_status(pending, "REINSTATEMENT_PENDING")

    X.post_payment(
        api,
        bundle,
        73500,
        LIFT_REQUEST_CLOCK,
        method="ACH",
        allocation_mode="EXPLICIT",
        explicit_allocations=[
            {"penalty_invoice_id": fee_invoice_id, "amount_cents": 10500},
            {"penalty_invoice_id": reinstatement_invoice_id, "amount_cents": 63000},
        ],
    )
    return bundle, order_id, permit_invoice_id, fee_invoice_id, reinstatement_invoice_id


def test_lifting_a_suspension_is_blocked_by_an_unrelated_permit_issue_invoice(api):
    """A 5500-cent permit invoice with no bearing on the suspension still blocks the lift.

    PRD §3.7: "The money condition is absolute: every invoice for the premises
    whose `collections_stage` is not `WRITTEN_OFF` must have `payment_status` of
    `PAID`, so that the premises' outstanding penalty balance net of
    `credit_balance_cents` is zero, else
    `ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT`."

    The condition reaches across the whole premises account, not just the two
    invoices the suspension itself produced: the 10500-cent fee invoice and the
    63000-cent reinstatement invoice are both `PAID`, yet the untouched 5500-cent
    `PERMIT_ISSUE_FEE` invoice keeps `outstanding_balance_cents` at 5500 and the
    lift must be refused with the order left exactly where it stood.

    Design: Difficulty/cross_entity_state_dependency/lifting_a_suspension_is_blocked_by_an_unrelated_permit_issue_invoice_of_the_same_site
    """
    (
        bundle,
        order_id,
        permit_invoice_id,
        fee_invoice_id,
        reinstatement_invoice_id,
    ) = _reinstatement_pending_with_one_unpaid_permit_invoice(api)

    A.assert_invoice_totals(
        X.get_invoice(api, fee_invoice_id),
        assessed_cents=10500,
        paid_cents=10500,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_invoice_totals(
        X.get_invoice(api, reinstatement_invoice_id),
        subtotal_cents=60000,
        admin_fee_cents=3000,
        assessed_cents=63000,
        paid_cents=63000,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_invoice_totals(
        X.get_invoice(api, permit_invoice_id),
        assessed_cents=5500,
        paid_cents=0,
        outstanding_cents=5500,
        payment_status="UNPAID",
    )

    X.set_clock(api, LIFT_ATTEMPT_CLOCK)
    validate_error(
        api.lift_suspension_order(order_id, U.PROGRAM_ADMIN),
        E.ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT,
        expected_status=402,
    )

    order = X.get_order(api, order_id)
    A.assert_status(order, "REINSTATEMENT_PENDING")
    assert order["lifted_at"] is None, (
        f"lifted_at must stay null on a refused lift, got {order['lifted_at']!r}"
    )
    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 5500, "outstanding_balance_cents")
    A.assert_status(site, "RESPONSE_SUSPENDED", field="response_status")


def test_paying_exactly_that_permit_issue_invoice_releases_the_lift(api):
    """Settling the one unrelated invoice lets the identical lift succeed.

    PRD §3.9: "In `AUTO_WATERFALL` mode the candidate set is the paying premises'
    own invoices whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose
    `collections_stage` is not `WRITTEN_OFF`."

    PRD §3.7: "On success the order becomes `LIFTED`, terminal, with `lifted_at`
    stamped; the premises' `lifted_suspension_count` rises by 1, raising the next
    order's fee, probation and contact requirement; `response_status` is
    recomputed to `RESPONSE_PROBATION` for `probation_days` whole days measured
    from `lifted_at`, after which it falls back to `RESPONSE_ACTIVE`; and the
    premises' `version` rises by 1."

    The 5500-cent waterfall tender has exactly one candidate — the permit invoice
    is the only row still carrying outstanding money — so it lands there in full
    and drives `outstanding_balance_cents` to 0 with no remainder to credit. The
    lift then succeeds, stamping `lifted_at` at the logical clock of 2026-10-01,
    and the frozen `probation_days` of 90 * (0 + 1) = 90 whole days from that
    instant puts the premises on `RESPONSE_PROBATION`.

    Design: Difficulty/cross_entity_state_dependency/lifting_a_suspension_is_blocked_by_an_unrelated_permit_issue_invoice_of_the_same_site
    """
    (
        bundle,
        order_id,
        permit_invoice_id,
        _fee_invoice_id,
        _reinstatement_invoice_id,
    ) = _reinstatement_pending_with_one_unpaid_permit_invoice(api)

    X.set_clock(api, LIFT_ATTEMPT_CLOCK)
    validate_error(
        api.lift_suspension_order(order_id, U.PROGRAM_ADMIN),
        E.ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT,
        expected_status=402,
    )

    X.post_payment(api, bundle, 5500, LIFT_ATTEMPT_CLOCK, method="ACH")
    A.assert_invoice_totals(
        X.get_invoice(api, permit_invoice_id),
        assessed_cents=5500,
        paid_cents=5500,
        outstanding_cents=0,
        payment_status="PAID",
    )

    lifted = A.data_of(api.lift_suspension_order(order_id, U.PROGRAM_ADMIN), 200)
    A.assert_status(lifted, "LIFTED")
    assert lifted["lifted_at"] == LIFT_ATTEMPT_CLOCK, (
        f"lifted_at expected {LIFT_ATTEMPT_CLOCK}, got {lifted['lifted_at']!r}"
    )
    assert lifted["probation_days"] == 90, (
        f"probation_days expected 90 for a first suspension, got {lifted['probation_days']!r}"
    )

    site = X.get_site(api, bundle.site_id)
    assert site["lifted_suspension_count"] == 1, (
        f"lifted_suspension_count expected 1, got {site['lifted_suspension_count']!r}"
    )
    A.assert_status(site, "RESPONSE_PROBATION", field="response_status")
    A.assert_money_cents(site["outstanding_balance_cents"], 0, "outstanding_balance_cents")
    A.assert_money_cents(site["credit_balance_cents"], 0, "credit_balance_cents")


COMPANY_SCHEDULE_OVERRIDES = {
    "effective_from": INSTALLED_AT,
    "invoice_due_days": NEVER_DUE_DAYS,
    "company_probation_score_threshold": 0.70,
    "company_suspension_score_threshold": 0.50,
}
AUGUST_PERIOD_START = "2026-08-01T00:00:00Z"
AUGUST_PERIOD_END = "2026-08-31T00:00:00Z"
REVIEW_CLOCK = "2026-09-05T00:00:00Z"


def _understating_company_with_work_in_flight(api):
    """Company X with three refused August requests and two September requests.

    All four systems sit at one premises: X1, X2 and X3 are monitored by company
    X and Y1 by company Y. The three requests on X1 are refused across
    2026-08-05, 2026-08-06 and 2026-08-07 — a refused request still counts as an
    ask — so August's `system_dispatch_count` for company X is 3 and X1 carries
    no open request. On 2026-09-01, while company X is still `ACTIVE`, request V
    on X2 is validated and left there and request S on X3 is left `SUBMITTED`.
    The August report is then filed on 2026-09-05 claiming one dispatch and no
    ECV attempts.
    """
    bundle = X.setup_program_baseline(
        api,
        clock=INSTALLED_AT,
        installed_at=INSTALLED_AT,
        schedule_overrides=dict(COMPANY_SCHEDULE_OVERRIDES),
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        contact_count=2,
        system_count=3,
    )
    company_y = X.create_company(api, score_mode="PERIOD_EQUAL")
    system_y1, _permit_y1 = X.create_permitted_system(
        api, bundle.site_id, company_y, installed_at=INSTALLED_AT
    )

    for day in ("2026-08-05", "2026-08-06", "2026-08-07"):
        X.set_clock(api, f"{day}T00:00:00Z")
        refused_id = X.submit_dispatch_request(
            api, bundle, bundle.system_ids[0], f"{day}T01:00:00Z"
        )
        validate_success(
            api.refuse_dispatch_request(
                refused_id, {"refusal_reason": "DUPLICATE_SIGNAL"}, U.DISPATCH_SUPERVISOR
            ),
            200,
        )

    X.set_clock(api, "2026-09-01T00:00:00Z")
    validated_id = X.submit_dispatch_request(
        api, bundle, bundle.system_ids[1], "2026-09-01T01:00:00Z"
    )
    validate_success(api.validate_dispatch_request(validated_id, U.DISPATCH_SUPERVISOR), 200)
    submitted_id = X.submit_dispatch_request(
        api, bundle, bundle.system_ids[2], "2026-09-01T02:00:00Z"
    )

    X.set_clock(api, REVIEW_CLOCK)
    report_id = X.submit_compliance_report(
        api,
        bundle,
        AUGUST_PERIOD_START,
        AUGUST_PERIOD_END,
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=0,
    )
    return bundle, company_y, system_y1, validated_id, submitted_id, report_id


def test_one_flagged_report_suspends_the_company_and_blocks_validating_its_submitted_request(api):
    """Flagging a single understated period carries an ACTIVE company straight to SUSPENDED.

    PRD §3.10: "`variance_pct` is that count divided by the greater of 1 and
    `system_dispatch_count`, at four decimal places. `period_accuracy` is 1 minus
    the lesser of 1 and `variance_pct`, at four decimal places, so accuracy
    floors at zero however wild the claim."

    PRD §3.10: "`period_score` is 0.6 times `period_accuracy` plus 0.4 times
    `period_ecv_rate`, rounded half up to two decimal places."

    PRD §3.10: "A score that low can also skip probation entirely and carry an
    `ACTIVE` company straight to `SUSPENDED`, in which case `probation_started_at`
    is set to the logical clock so that reinstatement eligibility still has an
    anchor to measure from."

    PRD §3.4: "the monitoring company to be `ACTIVE` or `PROBATION`, else
    `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED`"

    PRD §3.10: "but requests already in `VALIDATED` may still be dispatched, and
    requests sitting in `SUBMITTED` may only be refused."

    Three refused August requests against a claim of one give a variance of 2,
    so variance_pct is 2/3 = 0.6667 and period_accuracy is 1 - 0.6667 = 0.3333;
    with no ECV attempts the rate is 0/1 = 0.0000, so the period score is
    0.6 * 0.3333 + 0.4 * 0.0000 = 0.19998, which rounds half up to 0.20. Under
    `PERIOD_EQUAL` that single entry is the whole score set, so the company's
    score is 0.20, which sits below the 0.50 suspension threshold and so never
    stops at probation.

    Design: Difficulty/cross_entity_state_dependency/company_suspension_from_one_flagged_report_blocks_validation_but_not_an_already_validated_dispatch
    """
    bundle, _company_y, _system_y1, _validated_id, submitted_id, report_id = (
        _understating_company_with_work_in_flight(api)
    )

    reviewed = X.review_compliance_report(
        api,
        report_id,
        "FLAG_VARIANCE",
        variance_notes="Reported 1 dispatch against 3 recorded requests and no ECV attempts.",
    )
    A.assert_status(reviewed, "VARIANCE_FLAGGED")
    assert reviewed["system_dispatch_count"] == 3, (
        f"system_dispatch_count expected 3 refused August asks, got "
        f"{reviewed['system_dispatch_count']!r}"
    )
    assert reviewed["variance_count"] == 2, (
        f"variance_count expected 2, got {reviewed['variance_count']!r}"
    )
    A.assert_ratio_4dp(reviewed["variance_pct"], 0.6667, "variance_pct")
    A.assert_ratio_4dp(reviewed["period_accuracy"], 0.3333, "period_accuracy")
    A.assert_ratio_4dp(reviewed["period_ecv_rate"], 0.0000, "period_ecv_rate")
    A.assert_score_2dp(reviewed["period_score"], 0.20, "period_score")

    company = X.get_company(api, bundle.company_id)
    A.assert_status(company, "SUSPENDED")
    A.assert_score_2dp(
        company["reporting_compliance_score"], 0.20, "reporting_compliance_score"
    )
    assert company["probation_started_at"] == REVIEW_CLOCK, (
        f"probation_started_at expected {REVIEW_CLOCK}, got "
        f"{company['probation_started_at']!r}"
    )

    validate_error(
        api.validate_dispatch_request(submitted_id, U.DISPATCH_SUPERVISOR),
        E.ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED,
    )
    A.assert_status(
        A.data_of(api.get_dispatch_request(submitted_id, U.DISPATCH_SUPERVISOR)), "SUBMITTED"
    )


def test_company_suspension_spares_a_validated_dispatch_and_another_companys_request(api):
    """The suspension is scoped to new asks by that company, not to work in flight.

    PRD §3.10: "Suspension has a precise scope. Every subsequent dispatch request
    for that company's systems is rejected with
    `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED`, and so is every incident report it
    lodges; but requests already in `VALIDATED` may still be dispatched, and
    requests sitting in `SUBMITTED` may only be refused."

    PRD §3.4: "Recording the dispatch moves `VALIDATED → DISPATCHED` and stamps
    `dispatched_at` with the logical clock; it requires that the premises posture
    is still not `RESPONSE_SUSPENDED` at the moment of dispatch, else
    `ERR_POLICE_RESPONSE_SUSPENDED`, because a suspension served between
    validation and dispatch must stop the patrol."

    PRD §3.10: "The company is created in `ACTIVE` with
    `reporting_compliance_score` at 1.00, `probation_started_at`, `status_reason`
    and `last_status_action_at` all null"

    No incident has been determined at this premises, so
    `chargeable_count_window` is 0 and the posture stays `RESPONSE_ACTIVE`; the
    only thing standing in the way is company X's own status. Request V, already
    `VALIDATED` before the review, therefore dispatches at the logical clock of
    2026-09-05, and company Y — which filed no reports and so still scores 1.00 —
    may lodge a brand-new request at that very same premises.

    Design: Difficulty/cross_entity_state_dependency/company_suspension_from_one_flagged_report_blocks_validation_but_not_an_already_validated_dispatch
    """
    bundle, company_y, system_y1, validated_id, _submitted_id, report_id = (
        _understating_company_with_work_in_flight(api)
    )

    reviewed = X.review_compliance_report(
        api,
        report_id,
        "FLAG_VARIANCE",
        variance_notes="Reported 1 dispatch against 3 recorded requests and no ECV attempts.",
    )
    A.assert_status(reviewed, "VARIANCE_FLAGGED")
    A.assert_status(X.get_company(api, bundle.company_id), "SUSPENDED")
    A.assert_status(X.get_site(api, bundle.site_id), "RESPONSE_ACTIVE", field="response_status")

    dispatched = A.data_of(api.record_dispatch(validated_id, U.DISPATCH_SUPERVISOR), 200)
    A.assert_status(dispatched, "DISPATCHED")
    assert dispatched["dispatched_at"] == REVIEW_CLOCK, (
        f"dispatched_at expected {REVIEW_CLOCK}, got {dispatched['dispatched_at']!r}"
    )

    company_y_headers = U.alarm_company_operator(company_y)
    fresh = A.data_of(
        api.create_dispatch_request(
            F.dispatch_request_payload(
                system_y1,
                "2026-09-05T01:00:00Z",
                [
                    F.call_attempt(bundle.contact_ids[0], "2026-09-05T01:01:00Z"),
                    F.call_attempt(bundle.contact_ids[1], "2026-09-05T01:03:00Z"),
                ],
            ),
            company_y_headers,
        ),
        201,
    )
    A.assert_status(fresh, "SUBMITTED")

    other_company = X.get_company(api, company_y)
    A.assert_status(other_company, "ACTIVE")
    A.assert_score_2dp(
        other_company["reporting_compliance_score"], 1.00, "reporting_compliance_score"
    )
