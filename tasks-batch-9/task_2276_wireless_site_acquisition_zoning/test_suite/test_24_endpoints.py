"""Three endpoints read on their own terms: a survey patch, a computed read, a create."""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant, created, failed, ok
from test_helpers.constants import iso

PATCHED_RSRP_DBM = -92
PATCHED_DISTANCE_M = 240

BY_RIGHT_REVIEW_DAYS = 60
SHOT_CLOCK_DEADLINE = iso("2026-09-30")
ONE_DAY_PAST_DEADLINE = iso("2026-10-01")

UNKNOWN_PROVIDER_ID = "00000000-0000-0000-0000-0000000000aa"
WINDOW_START = iso("2026-09-01")
WINDOW_END = iso("2026-09-05")
CREW_DAYS = 4


def test_patching_survey_inputs_stores_them_without_scoring_the_candidate(
    api: ApiClient,
) -> None:
    """The patch rewrites only the supplied inputs and leaves the screen unrun.

    PRD: "While a candidate is still `UNSCREENED` on the feasibility dimension, its
    owning agent may revise the survey inputs, supplying any subset of
    `distance_from_center_m`, `agl_m`, `months_to_availability`, `measured_rsrp_dbm` and
    `offered_capacity_gbps`."

    PRD: "Alongside them the record carries `outreach_event_count` (starting at 0),
    `environmental_cleared` (starting false), `permit_issued` (starting false), and
    `rf_qualification_score`, which is null until the candidate is scored."

    PRD: "`version` (integer): a counter that increments by one on every mutation of
    that record."

    Design: Corner/endpoints/corner_candidate_patch_updates_survey_inputs_without_rescoring
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])

    patched = ok(
        api.patch_candidate(
            candidate["id"],
            {
                "measured_rsrp_dbm": PATCHED_RSRP_DBM,
                "distance_from_center_m": PATCHED_DISTANCE_M,
            },
            headers=S.agent(),
        )
    )

    assert_fields(
        patched,
        measured_rsrp_dbm=PATCHED_RSRP_DBM,
        distance_from_center_m=PATCHED_DISTANCE_M,
        agl_m=C.CANDIDATE_AGL_M,
        offered_capacity_gbps=C.CANDIDATE_CAPACITY_GBPS,
        feasibility_status="UNSCREENED",
        version=2,
    )
    assert patched["rf_qualification_score"] is None, "a patch does not score the site"


def test_deemed_granted_is_refused_on_the_deadline_and_allowed_the_day_after(
    api: ApiClient,
) -> None:
    """A clock resting exactly on the deadline has not run out; one day later it has.

    PRD: "This is accepted from `SUBMITTED`, `UNDER_REVIEW`, `INCOMPLETE`,
    `HEARING_SCHEDULED` or `HEARING_HELD`, and requires the logical clock to be
    **strictly after** `shot_clock_deadline_date`; a clock resting exactly on the
    deadline has not yet run out, and the attempt is refused with
    `ERR_SHOT_CLOCK_NOT_EXPIRED`."

    PRD: "It reports `review_days`, the nominal review-day count the jurisdiction
    publishes for this application's `application_type`; `tolled_days`, the accumulated
    tolling; `shot_clock_deadline_date` as stored; `days_remaining`, the whole days from
    the current logical clock to that deadline, which goes negative once the deadline has
    passed; and `deemed_grantable`, true exactly when the logical clock is strictly after
    `shot_clock_deadline_date`."

    PRD: "On success `decision_date` is stamped with the logical clock, the status
    becomes `DEEMED_GRANTED`, and the candidate is promoted `STRUCTURALLY_CLEARED →
    ENTITLED` when it is in `STRUCTURALLY_CLEARED`."

    Design: Corner/endpoints/corner_deem_granted_blocked_at_deadline_equality_then_allowed
    """
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api, requires_visual_simulation=False)
    ring = S.create_open_ring(api)
    landlord = S.create_landlord(api)
    candidate = S.create_candidate(api, ring["id"], landlord["id"], jurisdiction["id"])
    S.engage_landlord(api, candidate["id"])
    lease = S.create_lease(api, candidate["id"], landlord["id"])
    S.accept_lease(api, lease["id"])
    S.execute_lease(api, lease["id"])
    application = S.create_zoning_application(
        api, candidate["id"], application_type="BY_RIGHT"
    )
    S.submit_zoning_application(api, application["id"])
    S.set_completeness(api, application["id"], "COMPLETE")

    S.set_clock(api, SHOT_CLOCK_DEADLINE)
    position = ok(api.get_shot_clock(application["id"], headers=S.director()))
    assert_fields(
        position,
        review_days=BY_RIGHT_REVIEW_DAYS,
        tolled_days=0,
        days_remaining=0,
        deemed_grantable=False,
    )
    assert_instant(
        position["shot_clock_deadline_date"],
        SHOT_CLOCK_DEADLINE,
        "shot_clock_deadline_date",
    )

    refused = api.deem_granted(application["id"], headers=S.director())
    failed(refused, ApiError.SHOT_CLOCK_NOT_EXPIRED, expected_status=409)
    still_open = ok(api.get_zoning_application(application["id"], headers=S.planner()))
    assert_fields(still_open, status="UNDER_REVIEW")
    assert still_open["decision_date"] is None, "nothing was decided"

    S.set_clock(api, ONE_DAY_PAST_DEADLINE)
    granted = ok(api.deem_granted(application["id"], headers=S.director()))
    assert_fields(granted, status="DEEMED_GRANTED")
    assert_instant(granted["decision_date"], ONE_DAY_PAST_DEADLINE, "decision_date")

    unscreened = ok(api.get_candidate(candidate["id"], headers=S.director()))
    assert_fields(unscreened, feasibility_status="UNSCREENED")


def test_an_order_resolves_its_provider_before_it_books_any_crew_days(
    api: ApiClient,
) -> None:
    """An unknown provider is a 404 that books nothing; the real one books four days.

    PRD: "Existence of body identifiers, in declaration order — the matching 404, on the
    nine create operations named in §2.8."

    PRD: "Power and fiber are ordered per candidate against a registered provider:
    `candidate_id` names the site, `provider_id` the provider, `order_type` declares
    `POWER` or `FIBER`, and `window_start` and `window_end` bound the crew window."

    PRD: "A new order begins in `REQUESTED` with `delivered_date` null."

    PRD: "Any change the server makes to a record — including a change to a *computed*
    field such as a ring's `committed_capex_usd`, a landlord's `executed_lease_count`, a
    provider's `committed_crew_days` or a candidate's `feasibility_status` — is a
    mutation of that record: it refreshes `updated_at` and increments `version` on the
    record that changed."

    Design: Corner/endpoints/corner_backhaul_order_links_candidate_and_provider
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    provider = S.create_provider(api, concurrent_crew_capacity=1)

    refused = api.create_backhaul_order(
        F.backhaul_order_payload(
            candidate["id"], UNKNOWN_PROVIDER_ID, "FIBER", WINDOW_START, WINDOW_END
        ),
        headers=S.cm(),
    )
    failed(refused, ApiError.UTILITY_PROVIDER_NOT_FOUND, expected_status=404)

    untouched = ok(api.get_utility_provider(provider["id"], headers=S.cm()))
    assert_fields(untouched, committed_crew_days=0, version=1)

    order = created(
        api.create_backhaul_order(
            F.backhaul_order_payload(
                candidate["id"], provider["id"], "FIBER", WINDOW_START, WINDOW_END
            ),
            headers=S.cm(),
        )
    )
    assert_fields(order, status="REQUESTED", crew_days=CREW_DAYS, order_type="FIBER")
    assert order["delivered_date"] is None, "a fresh order has not been delivered"

    booked = ok(api.get_utility_provider(provider["id"], headers=S.cm()))
    assert_fields(booked, committed_crew_days=CREW_DAYS, version=2)
