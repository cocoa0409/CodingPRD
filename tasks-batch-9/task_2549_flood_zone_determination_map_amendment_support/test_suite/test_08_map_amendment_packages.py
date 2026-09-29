"""Map amendment packages: the fee schedule, the gates, and the agency cycle.

A LOMA or LOMR-F package is quoted before it is filed, gated on a sibling
document's review state, and only checked for elevation eligibility when it is
actually submitted.  The agency may send it back twice and no more.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_map_amendment_request,
    create_map_amendment_request_payload,
    decide_amendment,
    file_certificate,
    make_agency_headers,
    make_analyst_headers,
    prepare_amendment,
    review_certificate,
    set_clock,
    setup_amendment_draft,
    setup_amendment_submitted,
    setup_base_chain,
    setup_validated_certificate,
    submit_amendment,
)

CLOCK = "2026-08-01T00:00:00Z"


def assert_instant(actual, expected_utc):
    """Compare a timestamp field to an instant.

    PRD 2.4 fixes the wire format at three fractional digits, so an instant the
    test supplied as ``...T00:00:00Z`` is read back as ``...T00:00:00.000Z``.
    """
    assert actual is not None, f"expected the instant {expected_utc}, got null"
    assert actual.replace(".000Z", "Z") == expected_utc, (
        f"{actual!r} is not the instant {expected_utc}"
    )


def amendments_for(determination_id):
    data, meta = validate_paginated(
        api_client.list_map_amendment_requests(
            headers=make_analyst_headers(), params={"determination_id": determination_id}
        )
    )
    return data, meta


def test_a_loma_is_refused_for_a_structure_that_stands_on_placed_fill():
    """The request type is checked against the building's fill history, so a filled
    structure must take the LOMR-F route no matter how good its survey is — and
    the refusal leaves no draft behind.

    PRD §3.8: "The `request_type` must match the structure's fill history — `LOMA` requires `fill_placed_flag` false and `LOMR_F` requires `fill_placed_flag` true — and a mismatch is rejected with `ERR_AMENDMENT_TYPE_MISMATCH` (HTTP 422)."
    PRD §3.8: "The referenced certificate must be in `status` `VALIDATED`, or the request is rejected with `ERR_CERTIFICATE_NOT_VALIDATED` (HTTP 409)."
    PRD §3.8: "A package is created in `status` `DRAFT` with `resubmission_count` 0, `prepared_by_user_id` set to the acting `X-User-ID`, and `agency_case_number`, `additional_data_note`, `submitted_at` and `decided_at` all null."
    PRD §3.8: "`base_review_fee_cents` is the base fee for the `request_type` — nothing at all for a `LOMA`, and 50,000 cents (five hundred dollars) for a `LOMR_F` — plus 12,500 cents (one hundred and twenty-five dollars) for each resubmission already recorded, that is, 12,500 multiplied by `resubmission_count`."
    PRD §3.8: "`fee_tier` is then keyed on that pre-surcharge subtotal and never on the total: a `base_review_fee_cents` of zero or less is `TIER_1`, a value above zero but at or below 50,000 cents is `TIER_2`, and anything above 50,000 cents is `TIER_3`."

    Design: Corner/validations/corner_loma_rejected_for_structure_on_placed_fill
    """
    chain = setup_validated_certificate(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        structure_overrides={"fill_placed_flag": True},
    )
    determination_id = chain["determination"]["id"]
    certificate = chain["certificate"]

    # Every earlier gate is satisfied, so the type check is the first failure.
    assert certificate["status"] == "VALIDATED"
    assert certificate["freeboard_ft"] == 0.1
    assert chain["structure"]["fill_placed_flag"] is True

    validate_error(
        api_client.create_map_amendment_request(
            create_map_amendment_request_payload(
                determination_id, certificate["id"], request_type="LOMA"
            ),
            headers=make_analyst_headers(),
        ),
        ApiErrorId.ERR_AMENDMENT_TYPE_MISMATCH.value,
        422,
    )
    _, meta = amendments_for(determination_id)
    assert meta["total_count"] == 0

    correct = prepare_amendment(
        determination_id, certificate["id"], request_type="LOMR_F"
    )
    assert_map_amendment_request(correct)
    assert correct["status"] == "DRAFT"
    assert correct["request_type"] == "LOMR_F"
    assert correct["base_review_fee_cents"] == 50000
    assert correct["fee_tier"] == "TIER_2"
    assert correct["expedite_surcharge_cents"] == 0
    assert correct["total_fee_cents"] == 50000
    assert correct["resubmission_count"] == 0
    assert correct["submitted_at"] is None
    assert correct["decided_at"] is None
    assert correct["agency_case_number"] is None


def test_the_fee_tier_is_keyed_on_the_base_fee_and_never_on_the_total():
    """An expedited LOMR-F is the case where the two readings of the fee schedule
    are both self-consistent: keying the tier on the base charges thirty percent,
    keying it on the total would charge forty-five.

    PRD §3.8: "The fee is quoted on the draft and re-quoted on every submission, and it has a dependency that only looks circular."
    PRD §3.8: "`base_review_fee_cents` is the base fee for the `request_type` — nothing at all for a `LOMA`, and 50,000 cents (five hundred dollars) for a `LOMR_F` — plus 12,500 cents (one hundred and twenty-five dollars) for each resubmission already recorded, that is, 12,500 multiplied by `resubmission_count`."
    PRD §3.8: "`fee_tier` is then keyed on that pre-surcharge subtotal and never on the total: a `base_review_fee_cents` of zero or less is `TIER_1`, a value above zero but at or below 50,000 cents is `TIER_2`, and anything above 50,000 cents is `TIER_3`."
    PRD §3.8: "`expedite_surcharge_cents` is 0 when `expedite_flag` is false; when it is true, the surcharge is the tier's percentage of `base_review_fee_cents`, rounded half-up to a whole cent, where `TIER_1` carries no surcharge at all, `TIER_2` carries thirty percent, and `TIER_3` carries forty-five percent."
    PRD §3.8: "`total_fee_cents` is `base_review_fee_cents` plus `expedite_surcharge_cents`."
    PRD §3.8: "Keying the tier on the total instead of the base would push an expedited `LOMR_F` into the higher tier and inflate its surcharge; the tier is keyed on the base."

    Design: Difficulty/combinatorial_formula/amendment_fee_tier_keyed_on_pre_surcharge_base
    """
    chain = setup_validated_certificate(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        structure_overrides={"fill_placed_flag": True},
    )
    package = prepare_amendment(
        chain["determination"]["id"], chain["certificate"]["id"],
        request_type="LOMR_F", expedite_flag=True,
    )
    assert_map_amendment_request(package)

    # 50000 for the LOMR_F plus 12500 * 0 resubmissions.
    assert package["base_review_fee_cents"] == 50000
    # 50000 is at or below 50000, so the base lands in TIER_2, not TIER_3.
    assert package["fee_tier"] == "TIER_2"
    # Thirty percent of the base, not forty-five percent of it.
    assert package["expedite_surcharge_cents"] == 15000
    assert package["total_fee_cents"] == 65000
    # The circular reading would have keyed the tier on 65000: TIER_3, a 22500
    # surcharge, and a 72500 total.
    assert package["total_fee_cents"] != 72500
    assert package["expedite_flag"] is True
    assert package["status"] == "DRAFT"
    assert package["resubmission_count"] == 0

    # The certificate that quoted this fee had already published its elevations.
    assert chain["structure"]["lowest_floor_elevation_ft"] == 7.8
    assert chain["structure"]["elevation_source_certificate_id"] == chain["certificate"]["id"]


def test_a_package_may_only_name_a_certificate_that_has_been_validated():
    """The same payload is refused and then accepted with no change to itself: all
    that moved was a sibling document through its review, and a rejected review
    never opens the gate at all.

    PRD §3.8: "The referenced certificate must be in `status` `VALIDATED`, or the request is rejected with `ERR_CERTIFICATE_NOT_VALIDATED` (HTTP 409)."
    PRD §3.8: "A newly filed certificate is stored in `status` `SUBMITTED` with `submitted_by_user_id` set to the acting `X-User-ID` — the anchor of the certificate-review segregation-of-duties check — and with `rejection_reason` and `reviewed_by_user_id` null."
    PRD §3.8: "`VALIDATED` and `REJECTED` are both terminal."
    PRD §3.8: "A package is created in `status` `DRAFT` with `resubmission_count` 0, `prepared_by_user_id` set to the acting `X-User-ID`, and `agency_case_number`, `additional_data_note`, `submitted_at` and `decided_at` all null."
    PRD §3.8: "`base_review_fee_cents` is the base fee for the `request_type` — nothing at all for a `LOMA`, and 50,000 cents (five hundred dollars) for a `LOMR_F` — plus 12,500 cents (one hundred and twenty-five dollars) for each resubmission already recorded, that is, 12,500 multiplied by `resubmission_count`."

    Design: Difficulty/cross_entity_state_dependency/amendment_request_gated_by_certificate_review_state
    """
    chain = setup_base_chain(
        clock=CLOCK, community_overrides={"participation_status": "REGULAR"}
    )
    determination_id = chain["determination"]["id"]
    certificate = file_certificate(chain["structure"]["id"])
    payload = create_map_amendment_request_payload(
        determination_id, certificate["id"], request_type="LOMA"
    )

    assert certificate["status"] == "SUBMITTED"
    # The gate is about review state, not about missing arithmetic: the derived
    # figures are already on the row.
    assert certificate["converted_lowest_floor_ft"] == 7.8
    assert certificate["freeboard_ft"] == 0.1

    validate_error(
        api_client.create_map_amendment_request(
            payload, headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_CERTIFICATE_NOT_VALIDATED.value,
        409,
    )
    _, meta = amendments_for(determination_id)
    assert meta["total_count"] == 0

    validated = review_certificate(certificate["id"], decision="VALIDATED")
    assert validated["status"] == "VALIDATED"
    assert validated["rejection_reason"] is None

    package = validate_success(
        api_client.create_map_amendment_request(
            payload, headers=make_analyst_headers()
        ),
        201,
    )
    assert_map_amendment_request(package)
    assert package["status"] == "DRAFT"
    assert package["request_type"] == "LOMA"
    assert package["resubmission_count"] == 0
    # A LOMA costs nothing before any resubmission, so the base is zero.
    assert package["base_review_fee_cents"] == 0
    assert package["fee_tier"] == "TIER_1"
    assert package["expedite_surcharge_cents"] == 0
    assert package["total_fee_cents"] == 0

    # A terminally rejected certificate can never open the gate.
    rejected = review_certificate(
        file_certificate(chain["structure"]["id"])["id"],
        decision="REJECTED", rejection_reason="DATUM_MISMATCH",
    )
    assert rejected["status"] == "REJECTED"
    validate_error(
        api_client.create_map_amendment_request(
            create_map_amendment_request_payload(
                determination_id, rejected["id"], request_type="LOMA"
            ),
            headers=make_analyst_headers(),
        ),
        ApiErrorId.ERR_CERTIFICATE_NOT_VALIDATED.value,
        409,
    )


def test_elevation_eligibility_is_checked_at_submission_and_not_at_draft_creation():
    """A building half a foot below the panel may still be drafted; the refusal
    arrives only when the package is submitted, and a freeboard of exactly zero
    is refused too because the rule is strictly greater than zero.

    PRD §3.8: "Submission requires that the referenced certificate still be `VALIDATED` (otherwise `ERR_CERTIFICATE_NOT_VALIDATED`), that its `survey_date` still be within 365 days of the current logical instant (otherwise `ERR_CERTIFICATE_EXPIRED`), that the referenced determination be in `status` `ISSUED` or `FLAGGED_FOR_REVIEW`, that a resubmission not exceed the ceiling of two resubmissions, and that the structure actually sit above the base flood elevation: a `LOMA` submission requires the certificate's `freeboard_ft` to be strictly greater than 0.0 and a `LOMR_F` submission requires its `lag_freeboard_ft` to be strictly greater than 0.0, failing which the submission is rejected with `ERR_STRUCTURE_NOT_ABOVE_BFE` (HTTP 422)."
    PRD §3.8: "A package is created in `status` `DRAFT` with `resubmission_count` 0, `prepared_by_user_id` set to the acting `X-User-ID`, and `agency_case_number`, `additional_data_note`, `submitted_at` and `decided_at` all null."
    PRD §3.8: "Step four rounds each difference to 1 decimal place half-up, producing `freeboard_ft` from the lowest floor and `lag_freeboard_ft` from the lowest adjacent grade."
    PRD §3.8: "On `VALIDATED` the certificate moves `SUBMITTED → VALIDATED` and the surveyed elevations are published onto the structure: `lowest_floor_elevation_ft` takes the certificate's `converted_lowest_floor_ft`, `lowest_adjacent_grade_ft` takes its `converted_lag_ft`, and `elevation_source_certificate_id` is set to this certificate's identifier, recording which certificate is the source of truth for those numbers."

    Design: Corner/validations/corner_amendment_submission_rejected_when_floor_below_bfe
    """
    chain = setup_amendment_draft(
        request_type="LOMA",
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        panel_overrides={"base_flood_elevation_ft": 8.00},
        certificate_overrides={
            "raw_lowest_floor_elevation_ft": 8.65,
            "raw_lowest_adjacent_grade_ft": 8.55,
        },
    )
    certificate = chain["certificate"]
    package = chain["amendment"]

    # 8.65 - 1.15 == 7.50 -> 7.5, and 7.5 - 8.00 == -0.5: a negative freeboard is
    # stored, not clamped.
    assert certificate["converted_lowest_floor_ft"] == 7.5
    assert certificate["freeboard_ft"] == -0.5

    # The draft was accepted with the fee quoted anyway.
    assert package["status"] == "DRAFT"
    assert package["base_review_fee_cents"] == 0
    assert package["fee_tier"] == "TIER_1"
    assert package["total_fee_cents"] == 0
    assert package["submitted_at"] is None

    validate_error(
        api_client.submit_map_amendment_request(
            package["id"], {}, headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_STRUCTURE_NOT_ABOVE_BFE.value,
        422,
    )
    refused = validate_success(
        api_client.get_map_amendment_request(
            package["id"], headers=make_analyst_headers()
        )
    )
    assert refused["status"] == "DRAFT"
    assert refused["submitted_at"] is None
    # The elevation the earlier validation published is untouched by the refusal.
    assert validate_success(
        api_client.get_structure(chain["structure"]["id"], headers=make_analyst_headers())
    )["lowest_floor_elevation_ft"] == 7.5

    # Exactly level with the panel is not above it: 9.15 - 1.15 == 8.00 -> 8.0.
    level = review_certificate(
        file_certificate(
            chain["structure"]["id"],
            raw_lowest_floor_elevation_ft=9.15,
            raw_lowest_adjacent_grade_ft=9.15,
        )["id"],
        decision="VALIDATED",
    )
    assert level["converted_lowest_floor_ft"] == 8.0
    assert level["freeboard_ft"] == 0.0
    level_package = prepare_amendment(
        chain["determination"]["id"], level["id"], request_type="LOMA"
    )
    validate_error(
        api_client.submit_map_amendment_request(
            level_package["id"], {}, headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_STRUCTURE_NOT_ABOVE_BFE.value,
        422,
    )


def test_the_survey_validity_window_is_inclusive_of_its_last_day():
    """Staleness is measured from the survey date against the clock, so a package
    that was perfectly submittable in August fails a year and a day later — and
    on the 365th day itself it still goes through.

    PRD §3.8: "Submission requires that the referenced certificate still be `VALIDATED` (otherwise `ERR_CERTIFICATE_NOT_VALIDATED`), that its `survey_date` still be within 365 days of the current logical instant (otherwise `ERR_CERTIFICATE_EXPIRED`), that the referenced determination be in `status` `ISSUED` or `FLAGGED_FOR_REVIEW`, that a resubmission not exceed the ceiling of two resubmissions, and that the structure actually sit above the base flood elevation: a `LOMA` submission requires the certificate's `freeboard_ft` to be strictly greater than 0.0 and a `LOMR_F` submission requires its `lag_freeboard_ft` to be strictly greater than 0.0, failing which the submission is rejected with `ERR_STRUCTURE_NOT_ABOVE_BFE` (HTTP 422)."
    PRD §3.8: "Validation additionally requires that the survey still be current: the current logical instant must be at or before 365 days after `survey_date`, and a stale survey is rejected with `ERR_CERTIFICATE_EXPIRED` (HTTP 422)."
    PRD §3.8: "From `DRAFT` the package moves `DRAFT → SUBMITTED_TO_AGENCY`; from `ADDITIONAL_DATA_REQUESTED` it moves `ADDITIONAL_DATA_REQUESTED → SUBMITTED_TO_AGENCY` with `resubmission_count` incremented by 1 first, which is what makes the fee grow and can push the package across a tier boundary."
    PRD §3.8: "A successful submission sets `submitted_at` to the current logical instant and re-runs the fee schedule."
    PRD §2.4: "Advancing the clock is inert by itself: it does not expire notices, does not make panels effective, and does not re-determine anything."

    Design: Corner/validations/corner_amendment_submission_rejected_when_certificate_stale
    """
    chain = setup_amendment_draft(
        request_type="LOMA",
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
    )
    package_id = chain["amendment"]["id"]
    certificate_id = chain["certificate"]["id"]
    assert_instant(chain["certificate"]["survey_date"], "2026-07-01T00:00:00Z")
    assert chain["certificate"]["freeboard_ft"] == 0.1

    # One day past the window.
    set_clock("2027-07-02T00:00:00Z")
    validate_error(
        api_client.submit_map_amendment_request(
            package_id, {}, headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_CERTIFICATE_EXPIRED.value,
        422,
    )
    stale = validate_success(
        api_client.get_map_amendment_request(package_id, headers=make_analyst_headers())
    )
    assert stale["status"] == "DRAFT"
    assert stale["submitted_at"] is None
    # Staleness is about the survey and the clock, never about the review outcome.
    assert validate_success(
        api_client.get_elevation_certificate(
            certificate_id, headers=make_analyst_headers()
        )
    )["status"] == "VALIDATED"

    # Exactly 365 days after the survey: still inside.
    set_clock("2027-07-01T00:00:00Z")
    submitted = submit_amendment(package_id)
    assert_map_amendment_request(submitted)
    assert submitted["status"] == "SUBMITTED_TO_AGENCY"
    assert_instant(submitted["submitted_at"], "2027-07-01T00:00:00Z")
    # The fee is re-quoted on submission and still reflects zero resubmissions.
    assert submitted["base_review_fee_cents"] == 0
    assert submitted["fee_tier"] == "TIER_1"
    assert submitted["total_fee_cents"] == 0
    assert submitted["resubmission_count"] == 0


def test_the_agency_may_ask_for_more_data_twice_and_no_more():
    """The resubmission counter only moves on the way back out of the additional-data
    state, the fee grows with it, and once it reaches two the agency is forced to
    grant or deny rather than ask again.

    PRD §3.8: "From `DRAFT` the package moves `DRAFT → SUBMITTED_TO_AGENCY`; from `ADDITIONAL_DATA_REQUESTED` it moves `ADDITIONAL_DATA_REQUESTED → SUBMITTED_TO_AGENCY` with `resubmission_count` incremented by 1 first, which is what makes the fee grow and can push the package across a tier boundary."
    PRD §3.8: "On a `decision` of `ADDITIONAL_DATA_REQUESTED` the package moves `SUBMITTED_TO_AGENCY → ADDITIONAL_DATA_REQUESTED`, the agency's `additional_data_note` is stored, and `decided_at` is deliberately left null because the request has not terminated; that branch is available only while `resubmission_count` is below the ceiling of 2, and asking for additional data on a package already resubmitted twice is rejected with `ERR_RESUBMISSION_LIMIT` (HTTP 409), forcing the agency to grant or deny."
    PRD §3.8: "`resubmission_count` therefore never exceeds 2, `GRANTED` and `DENIED` are terminal, and the `ADDITIONAL_DATA_REQUESTED → SUBMITTED_TO_AGENCY` cycle can run at most twice."
    PRD §3.8: "`base_review_fee_cents` is the base fee for the `request_type` — nothing at all for a `LOMA`, and 50,000 cents (five hundred dollars) for a `LOMR_F` — plus 12,500 cents (one hundred and twenty-five dollars) for each resubmission already recorded, that is, 12,500 multiplied by `resubmission_count`."
    PRD §3.8: "On a `decision` of `GRANTED` the package moves `SUBMITTED_TO_AGENCY → GRANTED` with `agency_case_number` stored and `decided_at` set to the current logical instant — and, importantly, the structure's `sfha_offset_ft` is **not** modified: a granted amendment is evidence for a fresh determination, not a determination in itself, and its effect on future determinations is out of scope for this transition."

    Design: Corner/validations/corner_third_additional_data_request_rejected
    """
    chain = setup_amendment_submitted(
        request_type="LOMA",
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
    )
    package_id = chain["amendment"]["id"]
    # The first, plain submission left the counter alone.
    assert chain["amendment"]["resubmission_count"] == 0

    first_return = decide_amendment(
        package_id, "ADDITIONAL_DATA_REQUESTED",
        additional_data_note="Provide the signed FEMA form section C.",
    )
    assert first_return["status"] == "ADDITIONAL_DATA_REQUESTED"
    assert first_return["decided_at"] is None
    round_one = submit_amendment(package_id)
    assert round_one["resubmission_count"] == 1
    assert round_one["base_review_fee_cents"] == 12500
    assert round_one["fee_tier"] == "TIER_2"
    assert round_one["total_fee_cents"] == 12500

    second_return = decide_amendment(
        package_id, "ADDITIONAL_DATA_REQUESTED",
        additional_data_note="Photographs are illegible.",
    )
    assert second_return["status"] == "ADDITIONAL_DATA_REQUESTED"
    round_two = submit_amendment(package_id)
    assert round_two["resubmission_count"] == 2
    assert round_two["base_review_fee_cents"] == 25000
    assert round_two["fee_tier"] == "TIER_2"
    assert round_two["expedite_surcharge_cents"] == 0
    assert round_two["total_fee_cents"] == 25000

    validate_error(
        api_client.decide_map_amendment_request(
            package_id,
            {"decision": "ADDITIONAL_DATA_REQUESTED",
             "additional_data_note": "One more thing."},
            headers=make_agency_headers(),
        ),
        ApiErrorId.ERR_RESUBMISSION_LIMIT.value,
        409,
    )
    held = validate_success(
        api_client.get_map_amendment_request(package_id, headers=make_analyst_headers())
    )
    assert held["status"] == "SUBMITTED_TO_AGENCY"
    assert held["additional_data_note"] == "Photographs are illegible."
    assert held["decided_at"] is None
    assert held["resubmission_count"] == 2

    # The ceiling bans one decision value, not the endpoint.
    granted = decide_amendment(
        package_id, "GRANTED", agency_case_number="26-04-9002A"
    )
    assert granted["status"] == "GRANTED"
    assert_instant(granted["decided_at"], CLOCK)
    assert granted["resubmission_count"] == 2


def test_a_granted_package_is_locked_down_and_never_moved_the_geometry():
    """A grant is the end of the package's life: any further decision or submission
    is refused on state, and the building's recorded position on the map is
    exactly where it was, because the grant is evidence and not a determination.

    PRD §3.8: "On a `decision` of `GRANTED` the package moves `SUBMITTED_TO_AGENCY → GRANTED` with `agency_case_number` stored and `decided_at` set to the current logical instant — and, importantly, the structure's `sfha_offset_ft` is **not** modified: a granted amendment is evidence for a fresh determination, not a determination in itself, and its effect on future determinations is out of scope for this transition."
    PRD §3.8: "`resubmission_count` therefore never exceeds 2, `GRANTED` and `DENIED` are terminal, and the `ADDITIONAL_DATA_REQUESTED → SUBMITTED_TO_AGENCY` cycle can run at most twice."
    PRD §3.8: "An `AgencyOfficer` decides a package that is in `SUBMITTED_TO_AGENCY`, supplying a `decision` and optionally an `agency_case_number` and an `additional_data_note`; deciding a package in any other state is rejected with `ERR_INVALID_AMENDMENT_STATE`."
    PRD §3.8: "Submission from any other state — a package already `SUBMITTED_TO_AGENCY`, `GRANTED` or `DENIED` — is rejected with `ERR_INVALID_AMENDMENT_STATE` (HTTP 409)."
    PRD §2.5: "Eleventh (11), the target entity must be in a state from which the requested transition is declared, reporting the invalid-state error for that entity type at HTTP 409."

    Design: Corner/state_machines/corner_granted_amendment_is_terminal_lockdown
    """
    chain = setup_amendment_submitted(
        request_type="LOMA",
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
    )
    package_id = chain["amendment"]["id"]
    granted = decide_amendment(
        package_id, "GRANTED", agency_case_number="26-04-9001A"
    )
    assert granted["status"] == "GRANTED"
    assert granted["agency_case_number"] == "26-04-9001A"
    assert_instant(granted["decided_at"], CLOCK)
    assert_instant(granted["submitted_at"], CLOCK)
    assert granted["resubmission_count"] == 0

    validate_error(
        api_client.decide_map_amendment_request(
            package_id, {"decision": "DENIED"}, headers=make_agency_headers()
        ),
        ApiErrorId.ERR_INVALID_AMENDMENT_STATE.value,
        409,
    )
    validate_error(
        api_client.submit_map_amendment_request(
            package_id, {}, headers=make_analyst_headers()
        ),
        ApiErrorId.ERR_INVALID_AMENDMENT_STATE.value,
        409,
    )
    locked = validate_success(
        api_client.get_map_amendment_request(package_id, headers=make_analyst_headers())
    )
    assert locked["status"] == "GRANTED"
    assert locked["agency_case_number"] == "26-04-9001A"

    # The grant is evidence for a future determination, not a re-determination.
    structure = validate_success(
        api_client.get_structure(chain["structure"]["id"], headers=make_analyst_headers())
    )
    assert structure["sfha_offset_ft"] == -12.0
    determination = validate_success(
        api_client.get_determination(
            chain["determination"]["id"], headers=make_analyst_headers()
        )
    )
    assert determination["status"] == "ISSUED"
    assert determination["sfha_flag"] is True
    assert determination["zone_code"] == "AE"
