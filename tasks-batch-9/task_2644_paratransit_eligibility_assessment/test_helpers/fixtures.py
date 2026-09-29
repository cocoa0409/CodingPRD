"""Composite setup builders.

Every test starts against an empty database, so each of these builders drives
the real endpoints to bring the system to a named point in the certification
chain and returns the records it created. They use the lenient setup validator,
so a failure inside setup reads as a setup failure rather than as an assertion
about the behaviour under test.

The builders are ordinary functions rather than pytest fixtures: a test that
needs a two-rider or two-vehicle scenario simply calls the builder twice, and
nothing shares state between tests.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import DEFAULT_CLOCK
from .test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    SPECIALIST_2_HEADERS,
    SPECIALIST_HEADERS,
    TRAINER_HEADERS,
    make_applicant_headers,
)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
def set_clock(api, current_utc):
    """Move the server's logical clock to a named instant."""
    return get_success_data(
        api.set_clock(factories.clock_payload(current_utc=current_utc), ADMIN_HEADERS)
    )


def run_day_close(api):
    """Run the day-close sweep and return its counter report."""
    return get_success_data(api.day_close(ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1 — a bare rider
# ---------------------------------------------------------------------------
def create_applicant(api, **overrides):
    """Register one rider."""
    return get_success_data(
        api.create_applicant(factories.applicant_payload(**overrides), CLERK_HEADERS)
    )


def create_out_of_area_applicant(api, **overrides):
    """Register a rider certified by another agency and living outside the area."""
    return get_success_data(
        api.create_applicant(
            factories.out_of_area_applicant_payload(**overrides), CLERK_HEADERS
        )
    )


def create_vehicle(api, **overrides):
    """Register one accessible vehicle."""
    return get_success_data(
        api.create_vehicle(factories.vehicle_payload(**overrides), ADMIN_HEADERS)
    )


def create_slot(api, **overrides):
    """Publish one in-person assessment slot."""
    return get_success_data(
        api.create_assessment_slot(
            factories.assessment_slot_payload(**overrides), ADMIN_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — a rider with an intake packet
# ---------------------------------------------------------------------------
def draft_application(api, applicant=None, **overrides):
    """A rider plus a packet left in DRAFT."""
    applicant = applicant or create_applicant(api)
    application = get_success_data(
        api.create_application(
            factories.application_payload(applicant["id"], **overrides), CLERK_HEADERS
        )
    )
    return {"applicant": applicant, "application": application}


def submitted_application(api, applicant=None, submit_overrides=None, **overrides):
    """A packet carried to SUBMITTED, which starts the statutory clock."""
    context = draft_application(api, applicant=applicant, **overrides)
    context["application"] = get_success_data(
        api.submit_application(
            context["application"]["id"],
            factories.submit_payload(**(submit_overrides or {})),
            CLERK_HEADERS,
        )
    )
    return context


def verification_requested(api, applicant=None, **overrides):
    """A packet in PENDING_VERIFICATION with one outstanding request."""
    context = submitted_application(api, applicant=applicant, **overrides)
    context["verification"] = get_success_data(
        api.request_verification(
            context["application"]["id"],
            factories.verification_request_payload(),
            CLERK_HEADERS,
        )
    )
    return context


def assessment_required(api, applicant=None, attests_permanent=True, **overrides):
    """A packet in ASSESSMENT_REQUIRED after an accepted attestation."""
    context = verification_requested(api, applicant=applicant, **overrides)
    claimed = context["application"].get("claimed_conditions") or ["limited stamina"]
    context["verification"] = get_success_data(
        api.receive_verification(
            context["application"]["id"],
            context["verification"]["id"],
            factories.verification_accepted_payload(
                attests_conditions=claimed, attests_permanent=attests_permanent
            ),
            CLERK_HEADERS,
        )
    )
    context["application"] = get_success_data(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    return context


# ---------------------------------------------------------------------------
# Tier 3 — a rider with a booked assessment
# ---------------------------------------------------------------------------
def scheduled_assessment(
    api, applicant=None, slot=None, booking_overrides=None, attests_permanent=True,
    **overrides
):
    """A packet in ASSESSMENT_SCHEDULED with its assessment booked into a slot."""
    context = assessment_required(
        api, applicant=applicant, attests_permanent=attests_permanent, **overrides
    )
    context["slot"] = slot or create_slot(api)
    context["assessment"] = get_success_data(
        api.book_assessment(
            context["application"]["id"],
            factories.assessment_booking_payload(
                context["slot"]["id"], **(booking_overrides or {})
            ),
            CLERK_HEADERS,
        )
    )
    return context


def attended_assessment(
    api, applicant=None, slot=None, attendance_at="2026-08-05T09:30:00Z", **overrides
):
    """An assessment whose attendance dimension reads ATTENDED."""
    context = scheduled_assessment(api, applicant=applicant, slot=slot, **overrides)
    set_clock(api, attendance_at)
    context["assessment"] = get_success_data(
        api.record_attendance(
            context["assessment"]["id"],
            factories.attendance_payload("ATTENDED"),
            EVALUATOR_HEADERS,
        )
    )
    return context


def scored_assessment(api, applicant=None, score_overrides=None, **overrides):
    """An assessment scored but not yet signed off."""
    context = attended_assessment(api, applicant=applicant, **overrides)
    context["assessment"] = get_success_data(
        api.record_scores(
            context["assessment"]["id"],
            factories.scores_payload(**(score_overrides or {})),
            EVALUATOR_HEADERS,
        )
    )
    return context


def assessment_complete(api, applicant=None, signer_headers=None, **overrides):
    """A packet in ASSESSMENT_COMPLETE with the scores independently signed off."""
    context = scored_assessment(api, applicant=applicant, **overrides)
    context["assessment"] = get_success_data(
        api.sign_off_assessment(
            context["assessment"]["id"],
            factories.sign_off_payload(),
            signer_headers or SPECIALIST_2_HEADERS,
        )
    )
    context["application"] = get_success_data(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    return context


# ---------------------------------------------------------------------------
# Tier 4 — a rider holding a determination
# ---------------------------------------------------------------------------
def drafted_determination(
    api, applicant=None, draft_overrides=None, drafter_headers=None, **overrides
):
    """A determination sitting in DRAFT against a completed packet."""
    context = assessment_complete(api, applicant=applicant, **overrides)
    application = get_success_data(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    context["application"] = application
    context["determination"] = get_success_data(
        api.draft_determination(
            application["id"],
            factories.determination_draft_payload(
                application["version"], **(draft_overrides or {})
            ),
            drafter_headers or SPECIALIST_HEADERS,
        )
    )
    return context


def issued_determination(
    api, applicant=None, draft_overrides=None, drafter_headers=None, **overrides
):
    """A determination carried all the way to ISSUED."""
    context = drafted_determination(
        api,
        applicant=applicant,
        draft_overrides=draft_overrides,
        drafter_headers=drafter_headers,
        **overrides,
    )
    context["determination"] = get_success_data(
        api.issue_determination(
            context["determination"]["id"],
            factories.issue_payload(),
            drafter_headers or SPECIALIST_HEADERS,
        )
    )
    context["application"] = get_success_data(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    context["applicant"] = get_success_data(
        api.get_applicant(context["applicant"]["id"], CLERK_HEADERS)
    )
    return context


def conditional_determination(api, applicant=None, conditions=None, **overrides):
    """An issued CONDITIONAL grant, which also opens an automatic referral."""
    conditions = conditions or [factories.trip_condition_payload()]
    return issued_determination(
        api,
        applicant=applicant,
        draft_overrides={"category": "CONDITIONAL", "trip_conditions": conditions},
        **overrides,
    )


# ---------------------------------------------------------------------------
# Tier 4 — rides against a booked assessment
# ---------------------------------------------------------------------------
def reserved_ride(api, vehicle=None, booking_overrides=None, **overrides):
    """A scheduled assessment plus one reserved agency ride to it."""
    context = scheduled_assessment(api, **overrides)
    context["vehicle"] = vehicle or create_vehicle(api)
    context["booking"] = get_success_data(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                context["assessment"]["id"],
                context["vehicle"]["id"],
                **(booking_overrides or {}),
            ),
            CLERK_HEADERS,
        )
    )
    return context


# ---------------------------------------------------------------------------
# Tier 5 — appeals
# ---------------------------------------------------------------------------
def filed_appeal(api, context=None, appeal_overrides=None, **overrides):
    """An appeal in FILED against an issued determination."""
    context = context or issued_determination(api, **overrides)
    determination = context["determination"]
    context["appeal"] = get_success_data(
        api.create_appeal(
            factories.appeal_payload(determination["id"], **(appeal_overrides or {})),
            make_applicant_headers(context["applicant"]["id"]),
        )
    )
    return context


def appeal_with_reviewer(api, context=None, reviewer_user_id="rev-1", **overrides):
    """An appeal in REVIEWER_ASSIGNED."""
    context = filed_appeal(api, context=context, **overrides)
    context["appeal"] = get_success_data(
        api.assign_appeal_reviewer(
            context["appeal"]["id"],
            factories.assign_reviewer_payload(reviewer_user_id),
            ADMIN_HEADERS,
        )
    )
    context["reviewer_headers"] = _reviewer_headers(reviewer_user_id)
    return context


def heard_appeal_on_paper(api, context=None, reviewer_user_id="rev-1", **overrides):
    """An appeal carried to HEARD on the paper branch."""
    context = appeal_with_reviewer(
        api, context=context, reviewer_user_id=reviewer_user_id, **overrides
    )
    context["appeal"] = get_success_data(
        api.open_appeal_hearing(
            context["appeal"]["id"],
            factories.paper_hearing_payload(),
            context["reviewer_headers"],
        )
    )
    return context


def _reviewer_headers(reviewer_user_id):
    from .test_users import make_staff_headers
    from .types import UserRole

    return make_staff_headers(reviewer_user_id, UserRole.INDEPENDENT_REVIEWER.value)


# ---------------------------------------------------------------------------
# Tier 5 — trip conduct and suspension due process
# ---------------------------------------------------------------------------
def ingest_trip_event(api, applicant_id, **overrides):
    """Ingest one trip outcome for a rider."""
    return get_success_data(
        api.create_trip_event(
            factories.trip_event_payload(applicant_id, **overrides),
            CONDUCT_OFFICER_HEADERS,
        )
    )


def ingest_trip_events(api, applicant_id, events):
    """Ingest a stream of trip outcomes, given as (trip_date, event_type) pairs."""
    created = []
    for trip_date, event_type in events:
        created.append(
            ingest_trip_event(
                api, applicant_id, trip_date=trip_date, event_type=event_type
            )
        )
    return created


def auto_threshold_proceeding(api, applicant=None, events=None):
    """A rider whose conduct stream trips all three thresholds at once.

    Three unexcused no-shows inside the conduct window carry six points, three
    chargeable misses and a ratio above ten percent, which is what opens a
    proceeding on the system's own initiative.
    """
    applicant = applicant or create_applicant(api)
    events = events or [
        ("2026-06-01", "NO_SHOW"),
        ("2026-06-15", "NO_SHOW"),
        ("2026-07-01", "NO_SHOW"),
    ]
    trip_events = ingest_trip_events(api, applicant["id"], events)
    listing = api.list_suspension_proceedings(applicant["id"], CONDUCT_OFFICER_HEADERS)
    proceedings = listing.json()["data"]
    return {
        "applicant": get_success_data(api.get_applicant(applicant["id"], CLERK_HEADERS)),
        "trip_events": trip_events,
        "proceeding": proceedings[0] if proceedings else None,
    }


def notice_sent_proceeding(api, applicant=None, events=None):
    """A proceeding in NOTICE_SENT with its response deadline recorded."""
    context = auto_threshold_proceeding(api, applicant=applicant, events=events)
    context["proceeding"] = get_success_data(
        api.send_suspension_notice(
            context["proceeding"]["id"],
            factories.send_notice_payload(),
            CONDUCT_OFFICER_HEADERS,
        )
    )
    return context


def rider_responded_proceeding(api, applicant=None, events=None):
    """A proceeding in RIDER_RESPONDED, one of the two decidable states."""
    context = notice_sent_proceeding(api, applicant=applicant, events=events)
    context["proceeding"] = get_success_data(
        api.respond_to_suspension(
            context["proceeding"]["id"],
            factories.rider_response_payload(),
            make_applicant_headers(context["applicant"]["id"]),
        )
    )
    return context


# ---------------------------------------------------------------------------
# Tier 5 — travel training and visitor service
# ---------------------------------------------------------------------------
def auto_referral(api, applicant=None, **overrides):
    """The referral the system opens by itself when a conditional grant issues."""
    context = conditional_determination(api, applicant=applicant, **overrides)
    listing = api.list_travel_training_referrals(
        TRAINER_HEADERS, params={"applicant_id": context["applicant"]["id"]}
    )
    referrals = listing.json()["data"]
    context["referral"] = referrals[0] if referrals else None
    return context


def enrolled_referral(api, applicant=None, **overrides):
    """A referral the rider has accepted, ready for a competency score."""
    context = auto_referral(api, applicant=applicant, **overrides)
    context["referral"] = get_success_data(
        api.respond_to_referral(
            context["referral"]["id"],
            factories.referral_response_payload("ENROLLED"),
            TRAINER_HEADERS,
        )
    )
    return context


def visitor_record(api, applicant=None, **overrides):
    """An out-of-area rider holding one ACTIVE visitor-eligibility record."""
    applicant = applicant or create_out_of_area_applicant(api)
    record = get_success_data(
        api.create_visitor_eligibility(
            applicant["id"], factories.visitor_eligibility_payload(**overrides),
            CLERK_HEADERS,
        )
    )
    return {"applicant": applicant, "visitor_record": record}


def reset_clock(api):
    """Return the logical clock to the instant it reads before it is ever set."""
    return set_clock(api, DEFAULT_CLOCK)
