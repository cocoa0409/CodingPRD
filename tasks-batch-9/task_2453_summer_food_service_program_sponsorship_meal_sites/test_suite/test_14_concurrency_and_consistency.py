"""Optimistic concurrency on the sponsor ledger, and the immediate-consistency contract.

Two write operations — requesting an advance payment and opening a monthly meal claim — are
guarded against the `Sponsor` row's `version`, and both of them advance that version on success,
so the guard is only satisfiable against a freshly-read view of the sponsor. The second half of
this module checks that a derived value is already carried by the response of the very write that
produced it, with no follow-up read needed to see it.

Every scenario is built from scratch against an empty database through PRD endpoints only.
"""

from test_helpers import (
    ApiErrorId,
    assert_advance_payment,
    assert_claim_line_item,
    assert_meal_claim,
    assert_meal_service_day,
    assert_sponsor,
    assert_status,
    assert_version_incremented,
    create_approved_budget,
    create_approved_sponsor,
    create_open_day,
    create_sponsor_payload,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    record_meal_count,
    set_clock,
    setup_june_claim_scenario,
    setup_program_baseline,
    sponsor_version,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = make_state_agency_reviewer_headers()

CLOCK_PROGRAM_INTAKE = "2026-06-01T00:00:00Z"
CLOCK_JUNE_CLAIM_WINDOW = "2026-07-06T00:00:00Z"

# One rural SELF_PREP site producing 150 LUNCH meals and serving 47 first meals: the attendance cap
# of 200 and the self-prep production availability of 150 both leave the 47 first meals intact, and
# second meals are never reimbursable off camp, so the day is worth 47 reimbursable meals and
# 150 - 47 = 103 leftovers. At the RURAL_OR_SELF_PREP lunch rate of 470.50 fractional cents,
# 47 * 470.50 = 22113.50, which rounds half-up once, per line item and meal type, to 22114 cents.
DAY_PRODUCTION_MEALS = 150
DAY_FIRST_MEALS = 47
DAY_REIMBURSABLE_MEALS = 47
DAY_LEFTOVER_MEALS = 103
LUNCH_LINE_VALUE_CENTS = 22_114


# --- Stale-version protection on the sponsor ledger ---------------------------


def test_replayed_expected_sponsor_version_rejects_a_second_advance_request(api):
    """PRD §2.8: "Requesting a new advance payment requires a non-optional
    `expected_sponsor_version` field carrying the client's last observed `version` of the target
    `Sponsor`. If that value does not match the sponsor's current `version`, the request is
    rejected with `ERR_STALE_SPONSOR_VERSION` (HTTP 412)."

    PRD §2.8: "Both of these operations also advance the sponsor's own `version` by 1 on success,
    so a client that creates two advances back to back must re-read the sponsor between them."

    Design: Corner/cross_cutting_complexity_layers/stale_sponsor_version_rejects_a_second_advance_request
    """
    set_clock(CLOCK_PROGRAM_INTAKE)
    sponsor = create_approved_sponsor()
    create_approved_budget(sponsor["id"])
    sponsor_headers = make_sponsor_admin_headers(sponsor["id"])

    # The version the client is holding, observed before either advance request is made.
    version_held = sponsor_version(sponsor["id"])

    first = validate_success(
        api.create_advance_payment(
            {
                "sponsor_id": sponsor["id"],
                "request_month": "2026-06",
                "requested_amount_cents": 1_000_000,
                "expected_sponsor_version": version_held,
            },
            sponsor_headers,
        ),
        201,
    )
    assert_advance_payment(first)
    assert_status(first, "REQUESTED")

    # Replaying the version the first request consumed must be refused: the guard reads the live
    # Sponsor.version, not the value echoed back when the application was approved.
    stale = api.create_advance_payment(
        {
            "sponsor_id": sponsor["id"],
            "request_month": "2026-07",
            "requested_amount_cents": 200_000,
            "expected_sponsor_version": version_held,
        },
        sponsor_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_SPONSOR_VERSION.value)

    advances, meta = validate_paginated(
        api.list_advance_payments(sponsor_headers, params={"sponsor_id": sponsor["id"]})
    )
    assert meta["total_count"] == 1, (
        "the rejected request must create nothing, so the sponsor still holds exactly one advance, "
        f"got total_count {meta['total_count']}"
    )
    assert len(advances) == 1, f"expected one advance row, got {len(advances)}"

    refreshed_version = sponsor_version(sponsor["id"])
    assert refreshed_version == version_held + 1, (
        "only the accepted request may advance the sponsor's version, so exactly one increment is "
        f"expected: {version_held} -> {version_held + 1}, got {refreshed_version}"
    )

    second = validate_success(
        api.create_advance_payment(
            {
                "sponsor_id": sponsor["id"],
                "request_month": "2026-07",
                "requested_amount_cents": 200_000,
                "expected_sponsor_version": refreshed_version,
            },
            sponsor_headers,
        ),
        201,
    )
    assert_advance_payment(second)
    assert_status(second, "REQUESTED")
    assert second["request_month"] == "2026-07", (
        f"the re-read request must be stored for 2026-07, got {second['request_month']}"
    )

    sponsor_after = validate_success(api.get_sponsor(sponsor["id"], sponsor_headers))
    assert_sponsor(sponsor_after)
    assert sponsor_after["version"] == version_held + 2, (
        "two accepted advance requests must leave the version two increments on from the held "
        f"value, expected {version_held + 2}, got {sponsor_after['version']}"
    )
    assert sponsor_after["advance_paid_cents"] == 0, (
        "requesting an advance never moves money: advance_paid_cents sums only advances that "
        f"reached DISBURSED, expected 0, got {sponsor_after['advance_paid_cents']}"
    )


def test_advance_request_makes_a_held_version_stale_for_claim_creation(api):
    """PRD §2.8: "Opening a monthly meal claim carries the same guard: the create request requires
    a non-optional `expected_sponsor_version` matching the target `Sponsor`'s current `version`,
    and a mismatch is rejected with `ERR_STALE_SPONSOR_VERSION` (HTTP 412)."

    PRD §3.8: "A new claim opens in `status` `DRAFT` with `revision_round` at 0, and its
    `deadline_date` is fixed at creation as the last calendar day of the second month following
    `claim_month` — a claim for June 2026 is therefore due by 31 August 2026 — which is the 60-day
    filing window the program allows."

    Design: Corner/cross_cutting_complexity_layers/stale_sponsor_version_rejects_claim_creation_after_an_advance
    """
    set_clock(CLOCK_PROGRAM_INTAKE)
    sponsor = create_approved_sponsor()
    sponsor_headers = make_sponsor_admin_headers(sponsor["id"])

    # The version the client read before it did anything else on the advance path.
    version_held = sponsor_version(sponsor["id"])

    validate_success(
        api.create_advance_payment(
            {
                "sponsor_id": sponsor["id"],
                "request_month": "2026-06",
                "requested_amount_cents": 1_000_000,
                "expected_sponsor_version": version_held,
            },
            sponsor_headers,
        ),
        201,
    )

    set_clock(CLOCK_JUNE_CLAIM_WINDOW)

    # A write on the advance path — not on the claim path — is what made this version stale.
    stale = api.create_meal_claim(
        {
            "sponsor_id": sponsor["id"],
            "claim_month": "2026-06",
            "expected_sponsor_version": version_held,
        },
        sponsor_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_SPONSOR_VERSION.value)

    claims, meta = validate_paginated(
        api.list_meal_claims(sponsor_headers, params={"sponsor_id": sponsor["id"]})
    )
    assert meta["total_count"] == 0, (
        "the refused claim create must leave no claim behind, got total_count "
        f"{meta['total_count']}"
    )
    assert claims == [], f"expected no claim rows, got {claims}"

    refreshed_version = sponsor_version(sponsor["id"])
    assert refreshed_version == version_held + 1, (
        "the advance request was the only intervening mutation of the sponsor row, so exactly one "
        f"increment is expected: {version_held} -> {version_held + 1}, got {refreshed_version}"
    )

    claim = validate_success(
        api.create_meal_claim(
            {
                "sponsor_id": sponsor["id"],
                "claim_month": "2026-06",
                "expected_sponsor_version": refreshed_version,
            },
            sponsor_headers,
        ),
        201,
    )
    assert_meal_claim(claim)
    assert_status(claim, "DRAFT")
    assert claim["revision_round"] == 0, (
        f"a new claim opens with revision_round 0, got {claim['revision_round']}"
    )
    assert claim["deadline_date"] == "2026-08-31", (
        "the deadline is the last calendar day of the second month following claim_month 2026-06, "
        f"which the PRD states outright is 31 August 2026, got {claim['deadline_date']}"
    )

    sponsor_after = validate_success(api.get_sponsor(sponsor["id"], sponsor_headers))
    assert_sponsor(sponsor_after)
    assert sponsor_after["version"] == version_held + 2, (
        "the advance request and the accepted claim create are two mutations, expected version "
        f"{version_held + 2}, got {sponsor_after['version']}"
    )


def test_sponsor_version_increments_once_per_mutation_and_never_on_a_read(api):
    """PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that begins at 1 when the row is created
    and increments by exactly 1 on every mutation of that row — including mutations the server
    performs on its own initiative, such as a cascade that voids a service day or a recomputation
    that rewrites a derived counter."

    PRD §3.1: "The new record begins in `application_status` `DRAFT` with `version` 1, and its four
    ledger counters — `advance_paid_cents`, `advance_recovered_cents`, `advance_outstanding_cents`
    and `reimbursement_paid_cents` — all begin at 0."

    Design: Corner/cross_cutting_complexity_layers/sponsor_version_increments_once_per_mutation
    """
    set_clock(CLOCK_PROGRAM_INTAKE)

    created = validate_success(api.create_sponsor(create_sponsor_payload(), REVIEWER), 201)
    assert_sponsor(created)
    sponsor_id = created["id"]
    sponsor_headers = make_sponsor_admin_headers(sponsor_id)
    assert created["version"] == 1, (
        f"a freshly registered sponsor row starts at version 1, got {created['version']}"
    )

    read_only = validate_success(api.get_sponsor(sponsor_id, sponsor_headers))
    assert read_only["version"] == 1, (
        "a GET is not a mutation, so it must leave the version untouched at 1, got "
        f"{read_only['version']}"
    )

    submitted = validate_success(api.submit_sponsor_application(sponsor_id, sponsor_headers))
    assert_version_incremented(submitted["version"], created["version"])
    assert submitted["version"] == 2, (
        f"the application submission is one mutation, expected version 2, got {submitted['version']}"
    )

    approved = validate_success(
        api.decide_sponsor_application(sponsor_id, {"decision": "APPROVED"}, REVIEWER)
    )
    assert_version_incremented(approved["version"], submitted["version"])
    assert approved["version"] == 3, (
        f"the application decision is one mutation, expected version 3, got {approved['version']}"
    )
    assert_status(approved, "APPROVED", "application_status")
    assert approved["approved_at"] == "2026-06-01T00:00:00.000Z", (
        "approved_at is stamped with the current logical instant, expected "
        f"2026-06-01T00:00:00.000Z, got {approved['approved_at']}"
    )

    validate_success(
        api.create_advance_payment(
            {
                "sponsor_id": sponsor_id,
                "request_month": "2026-06",
                "requested_amount_cents": 500_000,
                "expected_sponsor_version": approved["version"],
            },
            sponsor_headers,
        ),
        201,
    )
    after_advance = validate_success(api.get_sponsor(sponsor_id, sponsor_headers))
    assert_version_incremented(after_advance["version"], approved["version"])
    assert after_advance["version"] == 4, (
        "the successful advance request advances the sponsor's version by exactly 1, expected 4, "
        f"got {after_advance['version']}"
    )

    validate_success(
        api.create_meal_claim(
            {
                "sponsor_id": sponsor_id,
                "claim_month": "2026-06",
                "expected_sponsor_version": after_advance["version"],
            },
            sponsor_headers,
        ),
        201,
    )
    after_claim = validate_success(api.get_sponsor(sponsor_id, sponsor_headers))
    assert_version_incremented(after_claim["version"], after_advance["version"])
    assert after_claim["version"] == 5, (
        "the claim create advances the sponsor's version by exactly 1, so the four mutations walk "
        f"it from 1 to 5, expected 5, got {after_claim['version']}"
    )
    assert_sponsor(after_claim)


# --- Immediate consistency: derived fields in the writing response ------------


def test_day_write_responses_already_carry_reimbursable_and_leftover_counts(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return
    the created or updated resource object in the data field."

    PRD §3.6: "Closing the day is the supervisor's final act on it, moving `status` from `OPEN` to
    `CLOSED` and re-running the whole classification over every count entry the day accumulated, so
    that `reimbursable_meals`, `non_reimbursable_meals` and `leftover_meals` are all rewritten from
    the complete set."

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_writing_response_itself
    """
    scenario = setup_program_baseline()
    site = scenario["site"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
    supervisor_headers = make_site_supervisor_headers(site["id"])

    day = create_open_day(site["id"], production_counts={"LUNCH": DAY_PRODUCTION_MEALS})
    record_meal_count(day, first_meals=DAY_FIRST_MEALS)

    # The write that produces the classification must publish it in its own response.
    closed = validate_success(api.close_meal_service_day(day["id"], supervisor_headers))
    assert_meal_service_day(closed)
    assert_status(closed, "CLOSED")
    assert closed["reimbursable_meals"] == DAY_REIMBURSABLE_MEALS, (
        "the close response must already carry the reclassified reimbursable total of 47, got "
        f"{closed['reimbursable_meals']}"
    )
    assert closed["leftover_meals"] == DAY_LEFTOVER_MEALS, (
        "the close response must already carry the leftover total of 150 produced less 47 served, "
        f"expected 103, got {closed['leftover_meals']}"
    )

    finalized = validate_success(api.finalize_meal_service_day(day["id"], sponsor_headers))
    assert_meal_service_day(finalized)
    assert_status(finalized, "FINALIZED")
    assert finalized["reimbursable_meals"] == DAY_REIMBURSABLE_MEALS, (
        "the finalize response itself must carry the reimbursable count without a follow-up read, "
        f"expected 47, got {finalized['reimbursable_meals']}"
    )
    assert finalized["leftover_meals"] == DAY_LEFTOVER_MEALS, (
        "the finalize response itself must carry the leftover count, expected 103, got "
        f"{finalized['leftover_meals']}"
    )

    # An immediately following read agrees field for field: no retry, sleep or second read needed.
    read_back = validate_success(api.get_meal_service_day(day["id"], sponsor_headers))
    for field in ("status", "reimbursable_meals", "non_reimbursable_meals", "leftover_meals"):
        assert read_back[field] == finalized[field], (
            f"the immediate read must agree with the finalize response on {field}: wrote "
            f"{finalized[field]}, read {read_back[field]}"
        )


def test_line_item_write_response_and_immediate_claim_read_agree_on_derived_values(api):
    """PRD §3.8: "The new line starts with `edit_check_status` `PENDING`, `disallow_reason` `NONE`,
    `disallowed_counts_by_type` null, and `hold_flag` copied from the site's current `claim_hold`;
    adding it recomputes the claim's `meals_rate_value_cents` and its `blocking_hold_count`."

    PRD §3.8: "The line's `rate_class` is `RURAL_OR_SELF_PREP` when the site's `is_rural` is true
    **or** its `production_mode` is `SELF_PREP`, and `OTHER` otherwise — either condition alone is
    enough to earn the higher rate."

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_writing_response_itself
    """
    scenario = setup_june_claim_scenario(first_meals=DAY_FIRST_MEALS, add_line_items=False)
    claim = scenario["claim"]
    site = scenario["site"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    line_item = validate_success(
        api.create_claim_line_item(claim["id"], {"site_id": site["id"]}, sponsor_headers), 201
    )
    assert_claim_line_item(line_item)
    assert line_item["finalized_day_count"] == 1, (
        "the line-item creation response must already carry the aggregated finalized day count of "
        f"1, got {line_item['finalized_day_count']}"
    )
    assert line_item["rate_class"] == "RURAL_OR_SELF_PREP", (
        "a rural SELF_PREP site earns the higher rate class in the creating response itself, got "
        f"{line_item['rate_class']}"
    )
    assert line_item["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
        "the line-item creation response must already carry its rate value of 22114 cents, got "
        f"{line_item['meals_rate_value_cents']}"
    )

    # The parent aggregate was recomputed in the same write, so the immediate claim read shows it.
    claim_read = validate_success(api.get_meal_claim(claim["id"], sponsor_headers))
    assert_meal_claim(claim_read)
    assert claim_read["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
        "the claim read immediately after the line-item write must already sum the new line's "
        f"22114 cents, got {claim_read['meals_rate_value_cents']}"
    )

    line_item_read = validate_success(api.get_claim_line_item(line_item["id"], sponsor_headers))
    for field in ("finalized_day_count", "rate_class", "meals_rate_value_cents",
                  "edit_check_status", "disallow_reason"):
        assert line_item_read[field] == line_item[field], (
            f"the immediate line-item read must agree with the creating response on {field}: "
            f"wrote {line_item[field]}, read {line_item_read[field]}"
        )
