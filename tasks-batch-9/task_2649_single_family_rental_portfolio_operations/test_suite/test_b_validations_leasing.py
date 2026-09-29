"""Calendar publication and application intake: two rule sets read per call, per market.

The calendar rules are measured against the logical clock rather than any stored flag, and the
pet rules are read out of the prospect's own market row -- so the same payload is legal or
illegal depending only on where the clock and the market stand at the moment of the call.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_DUPLICATE_APPLICATION,
    ERR_MARKET_MISMATCH,
    ERR_PET_COUNT_EXCEEDED,
    ERR_RESTRICTED_BREED,
    ERR_SLOT_DURATION_INVALID,
    ERR_SLOT_IN_PAST,
)
from test_helpers.assertions import (
    assert_fields,
    assert_money_group,
    assert_page_meta,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import (
    ACCESS_AGENT_ESCORT,
    ADVERSE_ACTION_NONE,
    APP_SUBMITTED,
    CLOCK_AUG_01,
    SLOT_AVAILABLE,
)


def test_the_calendar_measures_the_past_against_the_logical_clock_not_the_wall(api):
    """Yesterday by the dial is refused; a short window is refused earlier still.

    PRD SS3.7: "Three calendar rules guard publication, and they are checked in this order. A
    window whose length in whole minutes is less than the market's `min_showing_duration_minutes`
    is refused with `ERR_SLOT_DURATION_INVALID`. A window whose `starts_at` is before the current
    logical-clock instant is refused with `ERR_SLOT_IN_PAST`."  What "current" means is PRD
    SS2.4's: "Every date and timestamp comparison the rules below make -- expiry checks, past-date
    checks, window comparisons, ageing -- is made against this logical clock and never against the
    host's wall clock."  A published window's shape is PRD SS3.7's: "A window is created with
    `status` `AVAILABLE` and both `prospect_id` and `cancel_reason` the empty string", the
    `access_mode` being one the agent chooses from "`SMART_LOCK`, `LOCKBOX` or `AGENT_ESCORT`".
    The count comes from the listing envelope -- PRD SS2.3: "`total_count` (the number of rows
    matching the filters before pagination)".

    Design: Corner/validations/showing_slot_creation_rejects_past_windows_and_accepts_future_ones
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])

    failed(
        api.create_showing_slot(
            f.showing_slot_payload(
                home["id"],
                starts_at="2026-07-31T15:00:00Z",
                ends_at="2026-07-31T15:30:00Z",
            ),
            x.AGENT,
        ),
        ERR_SLOT_IN_PAST,
    )
    failed(
        api.create_showing_slot(
            f.showing_slot_payload(home["id"], ends_at="2026-08-20T15:20:00Z"), x.AGENT
        ),
        ERR_SLOT_DURATION_INVALID,
    )

    slot = created(
        api.create_showing_slot(
            f.showing_slot_payload(home["id"], access_mode=ACCESS_AGENT_ESCORT), x.AGENT
        )
    )
    stored = ok(api.get_showing_slot(slot["id"], x.AGENT))
    assert_fields(stored, status=SLOT_AVAILABLE, access_mode=ACCESS_AGENT_ESCORT)

    rows, meta = page(api.list_showing_slots(x.AGENT, {"home_id": home["id"]}))
    assert_page_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [slot["id"]]


def test_every_pet_rule_reads_the_prospect_s_own_market_row(api):
    """Three pets, one Rottweiler, a miscounted array, a Dallas applicant -- then one legal filing.

    PRD SS3.8: "The prospect's `market_id` must equal the home's `market_id`, otherwise
    `ERR_MARKET_MISMATCH`. No declared breed may appear in the market's `restricted_breeds` list,
    otherwise `ERR_RESTRICTED_BREED`. And the pet declaration must be internally consistent and
    within policy: `ERR_PET_COUNT_EXCEEDED` is raised when `pet_count` is greater than the
    market's `max_pets` **or** when the length of `pet_breeds` is not equal to `pet_count`, so two
    pets must be named by two breed tokens. Finally, the same prospect may not have two live
    applications on the same home: a second application for the same `prospect_id` and `home_id`
    while one is still `SUBMITTED` is refused with `ERR_DUPLICATE_APPLICATION`."  Which refusal
    speaks first is PRD SS2.7's: "**Rank 160 -- cross-market reference.** `ERR_MARKET_MISMATCH`
    (422) on rental-application creation, slot booking and work-order dispatch" precedes both
    "**Rank 506 -- restricted breed.**" and "**Rank 508 -- pet count above the market cap.**", and
    "Evaluation stops at the first violated rule, and only that rule's error is reported."  PRD
    SS2.10 makes the dials market-scoped: "Every one of them is read from the market row that owns
    the entity under evaluation, never from a global default."  The accepted row's shape is PRD
    SS3.8's: "The application is created in `SUBMITTED` with `rent_to_income_bps`,
    `security_deposit_cents`, `pet_deposit_cents`, `total_move_in_deposit_cents` and
    `risk_multiplier_bps` all 0 and `adverse_action_reason` `NONE`."

    Design: Corner/validations/application_pet_and_market_policy_rules_are_rejected_per_market
    """
    x.set_clock(api, CLOCK_AUG_01)
    atl = x.create_market(api)
    dal = x.create_market(api, f.dallas_market_payload())
    home = x.create_home(api, atl["id"])
    local = x.verified_prospect(api, atl["id"])
    remote = x.verified_prospect(
        api,
        dal["id"],
        prospect_overrides={
            "email": "pd@example.com",
            "full_name": "Dana Dallas",
            "phone": "+1-214-555-0199",
            "credit_tier": "A",
        },
        verification_overrides={
            "document_type": "PASSPORT",
            "document_match_score_bps": 9600,
            "verified_monthly_income_cents": 800000,
            "device_reputation_bps": 9200,
            "ip_geo_distance_km": 5,
        },
    )

    failed(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"],
                local.prospect_id,
                requested_move_in_date="2026-10-01",
                pet_count=3,
                pet_breeds=["LABRADOR", "BEAGLE", "POODLE"],
            ),
            local.headers,
        ),
        ERR_PET_COUNT_EXCEEDED,
    )
    failed(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"],
                local.prospect_id,
                requested_move_in_date="2026-10-01",
                pet_breeds=["ROTTWEILER"],
            ),
            local.headers,
        ),
        ERR_RESTRICTED_BREED,
    )
    failed(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"],
                local.prospect_id,
                requested_move_in_date="2026-10-01",
                pet_count=2,
                pet_breeds=["LABRADOR"],
            ),
            local.headers,
        ),
        ERR_PET_COUNT_EXCEEDED,
    )
    failed(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"],
                remote.prospect_id,
                requested_move_in_date="2026-10-01",
                pet_count=0,
                pet_breeds=[],
            ),
            remote.headers,
        ),
        ERR_MARKET_MISMATCH,
    )

    application = created(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"], local.prospect_id, requested_move_in_date="2026-10-01"
            ),
            local.headers,
        )
    )
    assert_fields(
        application,
        status=APP_SUBMITTED,
        pet_count=1,
        adverse_action_reason=ADVERSE_ACTION_NONE,
        rent_to_income_bps=0,
        risk_multiplier_bps=0,
    )
    assert_money_group(
        application,
        security_deposit_cents=0,
        pet_deposit_cents=0,
        total_move_in_deposit_cents=0,
    )

    failed(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"], local.prospect_id, requested_move_in_date="2026-11-01"
            ),
            local.headers,
        ),
        ERR_DUPLICATE_APPLICATION,
    )
