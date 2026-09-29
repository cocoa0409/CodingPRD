"""Applicant reads, claim linkage and scope, submission gates, version guards."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_application,
    assert_location_claim,
    assert_subgrantee,
    claim_location,
    create_application,
    create_location_claim_payload,
    create_program,
    create_score_sheet_payload,
    current_application_version,
    ingest_canonical_location,
    make_subgrantee_headers,
    open_challenge_window,
    read_application,
    read_program,
    read_subgrantee,
    register_subgrantee,
    run_capability_review,
    set_clock,
    setup_challenge_open_program,
    setup_qualified_subgrantee,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, SCORER, advance_program_to_scoring


def test_the_applicant_read_publishes_its_three_components_and_their_sum():
    """A determination stamps four derived numbers onto the applicant and the read
    endpoint returns all of them: a technical score under its cap, a fully covered
    liquidity leg at its cap, a managerial leg at its cap, and the index that is
    exactly their sum.

    PRD 3.4: "The **technical component**, `technical_component`, is the smaller of
    40.00 and the supplied `technical_raw_score`, rounded half up to 2 decimals; it
    is capped at 40.00."
    PRD 3.4: "The **financial component**, `financial_component`, tests liquidity:
    the applicant's liquidity requirement is one quarter of
    `requested_amount_cents`; the coverage ratio is the applicable net-asset basis
    divided by that requirement, capped at 1.0 so that over-coverage earns nothing
    extra; 35.00 multiplied by that capped ratio, itself capped at 35.00, is then
    multiplied by the variant's haircut, and the product is rounded half up to 2
    decimals."
    PRD 3.4: "The **managerial component**, `managerial_component`, awards 5 points
    per person in the applicable personnel basis plus a flat 5 points when
    `has_prior_federal_award` is true, takes the smaller of that sum and 25.00, and
    rounds half up to 2 decimals; it is capped at 25.00."
    PRD 3.4: "Finally `capability_index` is the sum of the three rounded
    components, rounded half up to 2 decimals."

    Design: Corner/endpoints/subgrantee_computed_read_matches_capability_index
    """
    program = create_program()
    ingest_canonical_location(program["id"], "L3")
    set_clock("2026-08-10T00:00:00Z")
    open_challenge_window(program["id"])

    applicant = register_subgrantee(program["id"])
    assert applicant["net_assets_cents"] == 900000
    assert applicant["requested_amount_cents"] == 3000000
    assert applicant["key_personnel_count"] == 4
    assert applicant["has_prior_federal_award"] is True

    determined = run_capability_review(applicant["id"], technical_raw_score=30)
    fetched = read_subgrantee(applicant["id"])
    assert_subgrantee(fetched)
    assert fetched == determined, "The read returns the row the determination wrote"

    assert fetched["technical_raw_score"] == 30
    assert fetched["technical_component"] == 30.00, "Below the 40.00 cap, so unclipped"
    assert fetched["financial_component"] == 35.00, (
        "900000 covers the 750000 requirement, so the ratio caps at 1.0"
    )
    assert fetched["managerial_component"] == 25.00, (
        "Four people at 5 points plus the 5-point prior-award flat clips to 25.00"
    )
    assert fetched["capability_index"] == 90.00
    assert (
        fetched["technical_component"]
        + fetched["financial_component"]
        + fetched["managerial_component"]
    ) == fetched["capability_index"]
    assert fetched["capability_state"] == "QUALIFIED"
    assert fetched["review_variant"] == "INITIAL"
    assert fetched["capability_reviewer_user_id"] == "reviewer-1"


def test_a_claim_naming_a_location_of_another_program_is_a_scope_mismatch():
    """The named location exists and resolves cleanly, so this is not a lookup
    failure: it belongs to a different program than the application, which is the
    scope rule, and neither side of the linkage records anything.

    PRD 3.5: "A claim's location must belong to the application's program, or the
    request is refused with `ERR_PROGRAM_SCOPE_MISMATCH`; the same location may not
    be claimed twice by one application, or the request is refused with
    `ERR_DUPLICATE_LOCATION_ADDRESS`."
    PRD 2.12: "23. **Priority 61 — program scope.** A challenge's location must
    belong to the same program as the challenge, and a claim's location must belong
    to the application's program → `ERR_PROGRAM_SCOPE_MISMATCH`."

    Design: Corner/entities/location_claim_cross_program_location_rejected
    """
    other_program = create_program(name="BEAD Round 2")
    foreign_location = ingest_canonical_location(other_program["id"], "L3")

    ctx = setup_challenge_open_program(("L2",))
    applicant = setup_qualified_subgrantee(ctx["program_id"])
    application = create_application(ctx["program_id"], applicant["id"])

    refused = api_client.create_location_claim(
        create_location_claim_payload(application["id"], foreign_location["id"]),
        make_subgrantee_headers(applicant["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH)

    assert read_application(application["id"])["claim_count"] == 0
    on_application, application_meta = validate_paginated(
        api_client.list_application_location_claims(application["id"], ADMIN)
    )
    assert on_application == []
    assert application_meta["total_count"] == 0

    on_location, location_meta = validate_paginated(
        api_client.list_location_claims_of_location(foreign_location["id"], ADMIN)
    )
    assert on_location == []
    assert location_meta["total_count"] == 0


def test_a_claim_appears_on_both_of_its_parents_collections():
    """Two claims on the same draft — one on an unserved location, one on a served
    one — are reachable from the application and from each location, and the wider
    and narrower aggregates diverge exactly as the eligibility split dictates.

    PRD 3.5: "The claim's `claim_state` is decided at creation from the claimed
    location's classification: `CLAIMED_ELIGIBLE` when the location's
    `classification_status` is `UNSERVED` or `UNDERSERVED`, and
    `CLAIMED_INELIGIBLE` when it is `SERVED`."
    PRD 3.5: "Four aggregates on the application are re-derived after every claim
    change. `claim_count` counts claims in `CLAIMED_ELIGIBLE`,
    `CLAIMED_INELIGIBLE`, `AWARD_BOUND` or `EHCL_DEFERRED`;
    `confirmed_location_count` counts the narrower set of claims in
    `CLAIMED_ELIGIBLE` or `AWARD_BOUND`; `total_project_cost_cents` sums
    `claimed_cost_cents` over the wider set; and `eligible_project_cost_cents` sums
    it over the narrower set."
    PRD 3.5: "The preliminary denominator can never be zero at submission because
    at least one claim is required to submit; the final figure stays null while the
    application is unsubmitted, and a final denominator of zero at scoring time is
    refused with `ERR_NO_ELIGIBLE_LOCATIONS`."

    Design: Corner/endpoints/location_claim_links_both_reverse_lists
    """
    ctx = setup_challenge_open_program(("L1", "L3"))
    served = ctx["location_ids"]["L1"]
    unserved = ctx["location_ids"]["L3"]
    assert ctx["locations"]["L1"]["classification_status"] == "SERVED"
    assert ctx["locations"]["L3"]["classification_status"] == "UNSERVED"

    applicant = setup_qualified_subgrantee(ctx["program_id"])
    application = create_application(ctx["program_id"], applicant["id"])

    eligible_claim = claim_location(
        application["id"], unserved, applicant["id"], claimed_cost_cents=400000
    )
    ineligible_claim = claim_location(
        application["id"], served, applicant["id"], claimed_cost_cents=600000
    )
    for claim in (eligible_claim, ineligible_claim):
        assert_location_claim(claim)
        assert claim["application_id"] == application["id"]
    assert eligible_claim["claim_state"] == "CLAIMED_ELIGIBLE"
    assert ineligible_claim["claim_state"] == "CLAIMED_INELIGIBLE"

    on_application, application_meta = validate_paginated(
        api_client.list_application_location_claims(application["id"], ADMIN)
    )
    assert application_meta["total_count"] == 2
    assert {c["id"] for c in on_application} == {
        eligible_claim["id"],
        ineligible_claim["id"],
    }

    for location_id, claim in ((unserved, eligible_claim), (served, ineligible_claim)):
        rows, meta = validate_paginated(
            api_client.list_location_claims_of_location(location_id, ADMIN)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == claim["id"]
        assert rows[0]["location_id"] == location_id

    aggregated = read_application(application["id"])
    assert_application(aggregated)
    assert aggregated["claim_count"] == 2
    assert aggregated["confirmed_location_count"] == 1
    assert aggregated["total_project_cost_cents"] == 1000000
    assert aggregated["eligible_project_cost_cents"] == 400000
    assert aggregated["final_cost_per_location_cents"] is None, (
        "The final figure stays null while the application is unsubmitted"
    )


def test_the_speed_floor_is_reported_ahead_of_the_match_floor():
    """An offer that breaks both submission floors at once reports the speed floor,
    which sits at the lower priority number; with the speeds repaired the same
    offer reports the match floor, so the second rule was live all along.

    PRD 3.5: "Submitting outside the window is refused with
    `ERR_APPLICATION_WINDOW_CLOSED`; a speed commitment under those floors is
    refused with `ERR_SPEED_COMMITMENT_BELOW_MINIMUM`; a match under the program
    minimum is refused with `ERR_MATCH_BELOW_MINIMUM`."
    PRD 2.12: "35. **Priority 80 — minimum speed commitment** →
    `ERR_SPEED_COMMITMENT_BELOW_MINIMUM`."
    PRD 2.12: "36. **Priority 81 — minimum match** → `ERR_MATCH_BELOW_MINIMUM`."

    Design: Corner/validations/speed_minimum_beats_match_minimum_priority
    """
    ctx = setup_challenge_open_program(("L2", "L3"))
    applicant = setup_qualified_subgrantee(ctx["program_id"])
    owner = make_subgrantee_headers(applicant["id"])

    both_broken = create_application(
        ctx["program_id"],
        applicant["id"],
        committed_down_mbps=50,
        committed_up_mbps=10,
        match_offer_pct=20.0,
    )
    claim_location(both_broken["id"], ctx["location_ids"]["L3"], applicant["id"])

    refused = api_client.submit_application(both_broken["id"], owner)
    validate_error(refused, ApiErrorId.ERR_SPEED_COMMITMENT_BELOW_MINIMUM)

    held = read_application(both_broken["id"])
    assert held["application_state"] == "DRAFT"
    assert held["claim_count"] == 1
    assert held["preliminary_cost_per_location_cents"] is None
    assert held["final_cost_per_location_cents"] is None, (
        "Only submission stamps the cost-per-location variants"
    )

    match_only = create_application(
        ctx["program_id"],
        applicant["id"],
        match_offer_pct=20.0,
    )
    claim_location(match_only["id"], ctx["location_ids"]["L2"], applicant["id"])
    assert match_only["committed_down_mbps"] == 1000
    assert match_only["committed_up_mbps"] == 1000

    unmasked = api_client.submit_application(match_only["id"], owner)
    validate_error(unmasked, ApiErrorId.ERR_MATCH_BELOW_MINIMUM)
    assert read_application(match_only["id"])["application_state"] == "DRAFT"


def test_a_score_sheet_guarded_by_a_superseded_application_version_is_refused():
    """The cure cycle moves the application twice, so the version captured at first
    submission no longer describes the row; the guard rejects the scoring attempt and
    the same request succeeds once the caller re-reads the live version.

    PRD 2.10: "If `expected_application_version` does not equal the application's
    current `version`, the create is rejected with
    `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."
    PRD 3.6: "The request names `application_id` and the concurrency guard
    `expected_application_version`."
    PRD 3.5: "Re-submitting a cured application moves it
    `RETURNED_FOR_CURE → SUBMITTED`, again requires the caller to be the owning
    applicant, the clock to be inside the application window and `claim_count` to be
    at least 1 and `match_offer_pct` to be at least the program's minimum, and
    recomputes both cost-per-location variants."

    Design: Corner/cross-cutting complexity layers/occ_stale_application_version_on_score_sheet_rejected
    """
    ctx = setup_challenge_open_program(("L2", "L3", "L5"))
    applicant = setup_qualified_subgrantee(ctx["program_id"])
    application, _ = setup_submitted_application(
        ctx["program_id"],
        applicant["id"],
        [(ctx["location_ids"][key], 900002) for key in ("L2", "L3", "L5")],
    )
    stale_version = application["version"]

    returned = validate_success(
        api_client.return_application_for_cure(
            application["id"], {"cure_reason": "Attach the workforce annexe."}, ADMIN
        )
    )
    assert returned["application_state"] == "RETURNED_FOR_CURE"
    assert returned["returned_for_cure_count"] == 1

    resubmitted = submit_application(application["id"], applicant["id"])
    assert resubmitted["application_state"] == "SUBMITTED"
    assert resubmitted["version"] > stale_version, "The cure cycle mutated the row twice"

    advance_program_to_scoring(ctx["program_id"])

    refused = api_client.create_score_sheet(
        create_score_sheet_payload(application["id"], stale_version), SCORER
    )
    validate_error(refused, ApiErrorId.ERR_STALE_APPLICATION_VERSION, 412)

    sheets, meta = validate_paginated(
        api_client.list_application_score_sheets(application["id"], ADMIN)
    )
    assert sheets == []
    assert meta["total_count"] == 0
    assert read_application(application["id"])["application_state"] == "SUBMITTED"

    live_version = current_application_version(application["id"])
    sheet = validate_success(
        api_client.create_score_sheet(
            create_score_sheet_payload(application["id"], live_version), SCORER
        ),
        201,
    )
    assert sheet["score_state"] == "FINAL"
    assert sheet["total_score"] == 70.35
    assert read_application(application["id"])["application_state"] == "SCORED"


def test_reads_never_move_a_version_while_every_write_moves_exactly_one_row():
    """A fresh row opens at version 1; the phase advance that mutates the program
    increments it by one; repeated reads of that row leave it alone; and a write
    against the application moves the application's version without touching the
    program's.

    PRD 2.4: "`version` (integer): an integer that starts at 1 and increments by
    one on every mutation of the row."
    PRD 2.4: "Recomputing a derived field counts as a mutation."
    PRD 3.1: "Opening the challenge window moves the program
    `DRAFT → CHALLENGE_OPEN` and requires that `location_count_total` be at least 1
    and that the logical clock sit inside the half-open challenge window, at or
    after `challenge_window_start` and strictly before `challenge_window_end`; the
    posture is recomputed and remains `FROZEN`."

    Design: Corner/cross-cutting complexity layers/occ_version_increments_on_every_write_and_never_on_reads
    """
    program = create_program()
    assert program["version"] == 1, "A newly written row starts at version 1"
    ingest_canonical_location(program["id"], "L3")
    claimable = ingest_canonical_location(program["id"], "L2")["id"]

    set_clock("2026-08-10T00:00:00Z")
    before_phase_change = read_program(program["id"])["version"]
    opened = open_challenge_window(program["id"])
    assert opened["program_state"] == "CHALLENGE_OPEN"
    assert opened["version"] == before_phase_change + 1, (
        "The phase advance is one mutation of the program row"
    )

    for _ in range(3):
        assert read_program(program["id"])["version"] == opened["version"], (
            "A read is not a mutation"
        )

    applicant = setup_qualified_subgrantee(program["id"])
    program_version_after_applicant = read_program(program["id"])["version"]
    application = create_application(program["id"], applicant["id"])
    assert application["version"] == 1
    assert application["claim_count"] == 0

    claim_location(application["id"], claimable, applicant["id"])
    mutated = read_application(application["id"])
    assert mutated["claim_count"] == 1
    assert mutated["version"] == application["version"] + 1, (
        "Re-deriving the claim aggregates is a mutation of the application"
    )
    for _ in range(3):
        assert read_application(application["id"])["version"] == mutated["version"]
    assert read_program(program["id"])["version"] == program_version_after_applicant, (
        "The claim write moves the application's row, not the program's"
    )
