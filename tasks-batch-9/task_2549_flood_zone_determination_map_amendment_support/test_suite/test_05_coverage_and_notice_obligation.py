"""The mandatory purchase obligation: how much coverage, and the notices that chase it.

The obligation amount is a three-way minimum computed from the folio, the
structure and the community, and the notice machinery that pursues it is gated
by the determination's own flag, by the community's standing in the national
program, and by a cooldown window whose ends are both inclusive.  Every check
here drives those rules through the declared endpoints only.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_compliance_notice,
    assert_determination,
    assert_escrow_conservation,
    assert_loan_folio,
    change_participation,
    create_compliance_notice_payload,
    create_dispute_payload,
    create_property,
    create_structure,
    issue_determination,
    make_analyst_headers,
    make_borrower_headers,
    open_folio,
    read_folio,
    send_notice,
    set_clock,
    setup_base_chain,
    setup_folio_with_mandatory_notice,
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


def test_required_coverage_is_the_smallest_of_principal_replacement_and_cap():
    """Two folios in the same community each pick a different binding argument of
    the three-way minimum: one is held down by the loan principal, the other by
    the building's replacement cost, and the statutory cap binds neither.

    PRD §3.6: "When it is true, the system first picks a statutory cap from the structure's `occupancy_type`: in a community whose `coverage_availability` is `EMERGENCY_LIMITS_ONLY` the cap is 3,500,000 cents (thirty-five thousand dollars) for a `SINGLE_FAMILY` or `TWO_TO_FOUR_FAMILY` building and 10,000,000 cents (one hundred thousand dollars) for an `OTHER_RESIDENTIAL` or `NON_RESIDENTIAL` building, while in a community at any other availability the cap is 25,000,000 cents (two hundred and fifty thousand dollars) for a `SINGLE_FAMILY` or `TWO_TO_FOUR_FAMILY` building and 50,000,000 cents (five hundred thousand dollars) for an `OTHER_RESIDENTIAL` or `NON_RESIDENTIAL` building."
    PRD §3.6: "`required_coverage_cents` is then the smallest of three integer amounts: the folio's `principal_balance_cents`, the structure's `replacement_cost_cents`, and that cap."
    PRD §3.6: "`uninsured_exposure_cents` is 0 whenever the folio's `insurance_status` is `FORCE_PLACED`, because a force-placed folio has no gap by construction; otherwise it is `required_coverage_cents` minus `reported_coverage_cents`, floored at 0 so that over-reported coverage never produces a negative exposure."
    PRD §3.6: "Seventh and otherwise, the posture is `NOTICE_DUE`."

    Design: Corner/calculations/corner_required_coverage_is_min_of_principal_replacement_and_cap
    """
    chain = setup_base_chain(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        structure_overrides={"replacement_cost_cents": 32000000},
        folio_overrides={"principal_balance_cents": 18000000},
    )
    community = chain["community"]
    # A REGULAR community is at FULL availability, so the regular caps apply and
    # the SINGLE_FAMILY cap is 25,000,000 cents for both folios below.
    assert community["coverage_availability"] == "FULL"

    property_b = create_property(
        community["id"],
        street_address="27 Bayfront Rd",
        latitude=25.7620,
        longitude=-80.1920,
        geocode_confidence_score=0.96,
    )
    structure_b = create_structure(
        property_b["id"],
        foundation_type="CRAWLSPACE",
        replacement_cost_cents=21000000,
    )
    folio_b = open_folio(
        chain["lender"]["id"],
        property_b["id"],
        loan_number="LN-4402",
        borrower_user_id="borrower-b",
        principal_balance_cents=40000000,
    )
    determination_b = issue_determination(folio_b["id"], structure_b["id"])

    determination_a = chain["determination"]
    assert_determination(determination_a)
    assert_determination(determination_b)
    assert determination_a["sfha_flag"] is True
    assert determination_a["mandatory_purchase_flag"] is True
    assert determination_b["mandatory_purchase_flag"] is True

    folio_a = read_folio(chain["folio"]["id"])
    folio_b = read_folio(folio_b["id"])
    assert_loan_folio(folio_a)
    assert_loan_folio(folio_b)

    # min(18000000 principal, 32000000 replacement, 25000000 cap) -> principal.
    assert folio_a["required_coverage_cents"] == 18000000
    # min(40000000 principal, 21000000 replacement, 25000000 cap) -> replacement.
    assert folio_b["required_coverage_cents"] == 21000000

    # Nothing has been reported yet, so the whole requirement is exposure.
    assert folio_a["reported_coverage_cents"] == 0
    assert folio_b["reported_coverage_cents"] == 0
    assert folio_a["uninsured_exposure_cents"] == 18000000
    assert folio_b["uninsured_exposure_cents"] == 21000000

    for folio in (folio_a, folio_b):
        assert folio["insurance_status"] == "NONE"
        assert folio["compliance_posture"] == "NOTICE_DUE"
        assert folio["open_notice_count"] == 0


def test_mandatory_purchase_notice_is_refused_for_a_structure_outside_the_hazard_area():
    """A building the determination placed outside the special flood hazard area
    carries no obligation, so the mandatory-purchase notice is refused on the
    determination's own flag rather than on anything about the community.

    PRD §3.5: "An `OUTSIDE` classification sets `zone_code` to `X` and `sfha_flag` false — `X` is a determination-only zone value that no panel ever carries, so the determination's `zone_code` ranges over `A`, `AE`, `AO`, `AH`, `VE` and `X`."
    PRD §3.5: "The determination's `base_flood_elevation_ft` is a snapshot of the governing panel's `base_flood_elevation_ft` when `sfha_flag` is true, and null when `sfha_flag` is false."
    PRD §3.5: "A folio whose `insurance_status` is `NONE` moves `NONE → NOT_REQUIRED` when the incoming current determination has `mandatory_purchase_flag` false; that transition sets `required_coverage_cents` to 0, sets `uninsured_exposure_cents` to 0, and recomputes `compliance_posture` to `COMPLIANT`."
    PRD §3.6: "A notice may not be sent into a community whose `coverage_availability` is `UNAVAILABLE`, which is rejected with `ERR_COVERAGE_UNAVAILABLE`, and a `MANDATORY_PURCHASE` notice specifically requires that the folio's current determination carry `mandatory_purchase_flag` true, failing which the request is rejected with `ERR_MANDATORY_PURCHASE_NOT_TRIGGERED`."

    Design: Corner/validations/corner_mandatory_purchase_notice_rejected_outside_sfha
    """
    chain = setup_base_chain(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        property_overrides={
            "street_address": "27 Bayfront Rd",
            "latitude": 25.7640,
            "longitude": -80.1950,
            "geocode_confidence_score": 0.96,
        },
        structure_overrides={"foundation_type": "CRAWLSPACE", "sfha_offset_ft": 30.0},
        folio_overrides={
            "loan_number": "LN-4402",
            "borrower_user_id": "borrower-b",
            "principal_balance_cents": 19000000,
        },
    )
    determination = chain["determination"]
    # A rooftop geocode contributes no buffer, so +30.0 ft resolves cleanly outside.
    assert determination["position_class"] == "OUTSIDE"
    assert determination["zone_code"] == "X"
    assert determination["sfha_flag"] is False
    assert determination["mandatory_purchase_flag"] is False
    assert determination["base_flood_elevation_ft"] is None

    folio = read_folio(chain["folio"]["id"])
    assert folio["insurance_status"] == "NOT_REQUIRED"
    assert folio["required_coverage_cents"] == 0
    assert folio["uninsured_exposure_cents"] == 0
    assert folio["compliance_posture"] == "COMPLIANT"

    validate_error(
        api_client.create_compliance_notice(
            create_compliance_notice_payload(folio["id"], determination["id"]),
            headers=chain["lender_headers"],
        ),
        ApiErrorId.ERR_MANDATORY_PURCHASE_NOT_TRIGGERED.value,
        409,
    )

    # The refusal wrote nothing at all.
    rows, meta = validate_paginated(
        api_client.list_compliance_notices(
            headers=chain["lender_headers"], params={"loan_folio_id": folio["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_folio(folio["id"])["open_notice_count"] == 0


def test_notice_issuance_is_gated_by_the_communitys_participation_standing():
    """The notice is written on the folio but the gate lives on the community two
    hops away: withdrawing the community from the program refuses the notice, and
    reinstating it lets the identical payload through untouched.

    PRD §2.9: "Each community carries a `participation_status` describing its standing in the national program and a `cbrs_flag` recording whether it sits inside a Coastal Barrier Resources System unit, and from those two inputs the system derives `coverage_availability` by evaluating the following clauses from top to bottom and taking the first that matches: if `cbrs_flag` is true the availability is `UNAVAILABLE`; otherwise if `participation_status` is `SUSPENDED`, `NON_PARTICIPATING` or `WITHDRAWN` the availability is `UNAVAILABLE`; otherwise if `participation_status` is `EMERGENCY` the availability is `EMERGENCY_LIMITS_ONLY`; otherwise if `participation_status` is `PROBATION` the availability is `FULL_WITH_SURCHARGE`; otherwise — that is, when `participation_status` is `REGULAR` — the availability is `FULL`."
    PRD §2.9: "An `UNAVAILABLE` community blocks force placement and blocks the issuance of mandatory-purchase notices, both with `ERR_COVERAGE_UNAVAILABLE`; an `EMERGENCY_LIMITS_ONLY` community sharply lowers the coverage caps described in Section 3.6; and a `PROBATION` community carries the annual `probation_surcharge_cents` amount recorded on the community row, which is meaningful only while `participation_status` is `PROBATION`."
    PRD §3.1: "Each such folio has its monitoring dimension re-evaluated: a folio whose `monitoring_status` is `ACTIVE` moves `ACTIVE → SUSPENDED` when the community's new `coverage_availability` is `UNAVAILABLE`, and a folio whose `monitoring_status` is `SUSPENDED` moves `SUSPENDED → ACTIVE` when the new availability is anything other than `UNAVAILABLE` — that is, when the community has been restored to `REGULAR`, `EMERGENCY` or `PROBATION` standing."
    PRD §3.6: "First, if the community's `coverage_availability` is `UNAVAILABLE` the posture is `COVERAGE_UNAVAILABLE`."
    PRD §3.6: "A notice that survives all of that is created in `status` `SENT` with `sent_at` at the current logical instant, and its `response_deadline_at` is computed as `sent_at` plus a response window that depends on the type: 45 days for `MANDATORY_PURCHASE`, 30 days for `FORCE_PLACEMENT_WARNING`, 30 days for `RE_DETERMINATION` and 15 days for `COVERAGE_UNAVAILABLE`."
    PRD §3.6: "The notice snapshots the folio's obligation as `required_coverage_snapshot_cents`, taken at the instant the notice was sent, and it stores a forward-looking premium estimate in `estimated_force_place_premium_cents`."

    Design: Difficulty/cross_entity_state_dependency/notice_issuance_gated_by_community_participation_status
    """
    chain = setup_base_chain(
        clock=CLOCK, community_overrides={"participation_status": "REGULAR"}
    )
    community, folio_id = chain["community"], chain["folio"]["id"]
    determination = chain["determination"]
    assert determination["mandatory_purchase_flag"] is True

    withdrawn = change_participation(community["id"], "NON_PARTICIPATING")
    assert withdrawn["participation_status"] == "NON_PARTICIPATING"
    assert withdrawn["coverage_availability"] == "UNAVAILABLE"

    suspended_folio = read_folio(folio_id)
    assert suspended_folio["monitoring_status"] == "SUSPENDED"
    assert suspended_folio["compliance_posture"] == "COVERAGE_UNAVAILABLE"

    payload = create_compliance_notice_payload(folio_id, determination["id"])
    validate_error(
        api_client.create_compliance_notice(payload, headers=chain["lender_headers"]),
        ApiErrorId.ERR_COVERAGE_UNAVAILABLE.value,
        409,
    )

    # Creating a notice is not a folio transition, so the suspended monitoring
    # dimension is not what refused it, and nothing was written.
    _, meta = validate_paginated(
        api_client.list_compliance_notices(
            headers=chain["lender_headers"], params={"loan_folio_id": folio_id}
        )
    )
    assert meta["total_count"] == 0
    assert read_folio(folio_id)["open_notice_count"] == 0

    reinstated = change_participation(community["id"], "REGULAR")
    assert reinstated["coverage_availability"] == "FULL"
    revived_folio = read_folio(folio_id)
    assert revived_folio["monitoring_status"] == "ACTIVE"
    assert revived_folio["required_coverage_cents"] == 25000000

    notice = validate_success(
        api_client.create_compliance_notice(payload, headers=chain["lender_headers"]),
        201,
    )
    assert_compliance_notice(notice)
    assert notice["status"] == "SENT"
    assert_instant(notice["sent_at"], CLOCK)
    # 2026-08-01 plus the 45-day MANDATORY_PURCHASE window.
    assert_instant(notice["response_deadline_at"], "2026-09-15T00:00:00Z")
    assert notice["required_coverage_snapshot_cents"] == 25000000

    final_folio = read_folio(folio_id)
    assert final_folio["open_notice_count"] == 1
    assert final_folio["compliance_posture"] == "NOTICE_PENDING"

    # The gate read the community throughout; the determination never moved.
    live_determination = validate_success(
        api_client.get_determination(determination["id"], headers=make_analyst_headers())
    )
    assert live_determination["status"] == "ISSUED"
    assert live_determination["mandatory_purchase_flag"] is True


def test_reported_coverage_outside_the_admissible_band_is_refused():
    """One rule guards a two-sided band: a cent short of the requirement and a
    cent above the building's replacement cost are both refused with the same
    error, and neither attempt touches the folio.

    PRD §3.6: "`required_coverage_cents` is then the smallest of three integer amounts: the folio's `principal_balance_cents`, the structure's `replacement_cost_cents`, and that cap."
    PRD §3.6: "The figure must be at or above the folio's `required_coverage_cents` and must not exceed the structure's `replacement_cost_cents`; either violation — under-insurance or an uninsurable over-report — is rejected with `ERR_COVERAGE_BELOW_REQUIRED` (HTTP 422)."
    PRD §2.4: "`version` starts at 1 when the row is created and increases by exactly 1 on every mutation of that row; `updated_at` is refreshed to the current logical instant on every mutation."

    Design: Corner/validations/corner_insurance_report_outside_the_admissible_band_rejected
    """
    chain = setup_base_chain(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        structure_overrides={"replacement_cost_cents": 32000000},
        folio_overrides={"principal_balance_cents": 28000000},
    )
    folio_id = chain["folio"]["id"]
    lender_headers = chain["lender_headers"]

    before = read_folio(folio_id)
    # min(28000000 principal, 32000000 replacement, 25000000 cap) -> the cap binds.
    assert before["required_coverage_cents"] == 25000000

    validate_error(
        api_client.report_insurance(
            folio_id, {"reported_coverage_cents": 24999999}, headers=lender_headers
        ),
        ApiErrorId.ERR_COVERAGE_BELOW_REQUIRED.value,
        422,
    )
    # The upper end of the band is the building's replacement cost, and it is
    # policed by the very same error.
    validate_error(
        api_client.report_insurance(
            folio_id, {"reported_coverage_cents": 32000001}, headers=lender_headers
        ),
        ApiErrorId.ERR_COVERAGE_BELOW_REQUIRED.value,
        422,
    )

    after = read_folio(folio_id)
    assert after["reported_coverage_cents"] == 0
    assert after["insurance_status"] == "NONE"
    assert after["uninsured_exposure_cents"] == 25000000
    assert after["compliance_posture"] == "NOTICE_DUE"
    assert after["version"] == before["version"], "a refused report is not a mutation"


def test_coverage_reported_at_exactly_the_required_amount_closes_the_notice():
    """Reporting exactly the required amount is the passing edge of a non-strict
    comparison, and the accepted report supersedes the outstanding notice in the
    same response, driving the open count back to zero.

    PRD §3.6: "The figure must be at or above the folio's `required_coverage_cents` and must not exceed the structure's `replacement_cost_cents`; either violation — under-insurance or an uninsurable over-report — is rejected with `ERR_COVERAGE_BELOW_REQUIRED` (HTTP 422)."
    PRD §3.6: "From `NONE` the folio moves `NONE → BORROWER_PROVIDED`: `reported_coverage_cents` is stored, `uninsured_exposure_cents` recomputes to 0, `compliance_posture` recomputes to `COMPLIANT`, and every notice on the folio in `status` `SENT` whose `notice_type` is `MANDATORY_PURCHASE` or `FORCE_PLACEMENT_WARNING` moves `SENT → SUPERSEDED` with `closed_at` set, after which `open_notice_count` is re-counted."
    PRD §3.6: "The folio's `version` increments by 1."
    PRD §2.10: "`open_notice_count` on a folio is defined as the number of compliance notices on that folio whose `status` is `SENT`, counted across every notice type and with no time window applied, and it is recomputed by full re-count after every notice creation and after every notice transition out of `SENT`."

    Design: Corner/validations/corner_insurance_report_at_exactly_required_accepted
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        structure_overrides={"replacement_cost_cents": 32000000},
        folio_overrides={"principal_balance_cents": 28000000},
    )
    folio_id = chain["folio"]["id"]
    notice = chain["notice"]
    before = read_folio(folio_id)
    assert before["required_coverage_cents"] == 25000000
    assert before["open_notice_count"] == 1
    assert before["compliance_posture"] == "NOTICE_PENDING"

    reported = validate_success(
        api_client.report_insurance(
            folio_id,
            {"reported_coverage_cents": 25000000},
            headers=chain["lender_headers"],
        ),
        200,
    )
    assert_loan_folio(reported)
    assert reported["insurance_status"] == "BORROWER_PROVIDED"
    assert reported["reported_coverage_cents"] == 25000000
    assert reported["uninsured_exposure_cents"] == 0
    assert reported["compliance_posture"] == "COMPLIANT"
    assert reported["open_notice_count"] == 0
    assert reported["version"] == before["version"] + 1

    closed_notice = validate_success(
        api_client.get_compliance_notice(notice["id"], headers=chain["lender_headers"])
    )
    assert closed_notice["status"] == "SUPERSEDED"
    assert_instant(closed_notice["closed_at"], CLOCK)
    assert closed_notice["acknowledged_at"] is None
    assert closed_notice["acknowledged_by_role"] is None

    # Satisfying the obligation says nothing about where the building sits.
    determination = validate_success(
        api_client.get_determination(
            chain["determination"]["id"], headers=make_analyst_headers()
        )
    )
    assert determination["status"] == "ISSUED"
    assert determination["sfha_flag"] is True


def test_open_notice_count_returns_to_zero_after_acknowledgement():
    """Sending a notice and then acknowledging that same notice restores the
    folio's open-notice count and its posture to the exact values they held
    before the notice existed, and moves no money at all.

    PRD §2.10: "Consequently, sending a notice and then acknowledging that same notice must return `open_notice_count` to exactly the value it held before the notice was sent, for every folio, regardless of which cascades fired in between."
    PRD §3.6: "Sixth, if a compliance notice exists on this folio whose `notice_type` is `MANDATORY_PURCHASE`, whose `status` is `SENT`, and whose `response_deadline_at` is at or after the current logical instant, the posture is `NOTICE_PENDING`."
    PRD §3.6: "Acknowledgement moves the notice `SENT → ACKNOWLEDGED`, sets `acknowledged_at` and `closed_at` to the current logical instant, and records `acknowledged_by_role` as the acting role — the value is `Lender` or `Borrower` and is otherwise null."
    PRD §3.6: "The notice must be in `status` `SENT` — acknowledging one already `ACKNOWLEDGED`, `EXPIRED` or `SUPERSEDED` is rejected with `ERR_INVALID_NOTICE_STATE` — and the current logical instant must be at or before `response_deadline_at`, since the response window is closed at its right end."
    PRD §2.10: "Thereafter, at every point where the folio is at rest, the sum of `escrow_balance_cents` and `cumulative_earned_premium_cents` must equal `initial_escrow_balance_cents` — after the forward action of force placement, which draws a premium out of escrow, and after its compensating action of coverage replacement, which recognises the earned portion and refunds the rest."

    Design: Difficulty/compensating_invariant/open_notice_cardinality_returns_to_zero_after_acknowledgement
    """
    chain = setup_base_chain(
        clock=CLOCK,
        structure_overrides={"replacement_cost_cents": 32000000},
        folio_overrides={"principal_balance_cents": 28000000, "escrow_balance_cents": 500000},
    )
    folio_id = chain["folio"]["id"]
    borrower_headers = chain["borrower_headers"]

    pre = read_folio(folio_id)
    assert pre["required_coverage_cents"] == 25000000
    assert pre["reported_coverage_cents"] == 0
    assert pre["open_notice_count"] == 0
    assert pre["compliance_posture"] == "NOTICE_DUE"

    notice = send_notice(folio_id, chain["determination"]["id"], chain["lender"]["id"])
    forward = read_folio(folio_id)
    assert forward["open_notice_count"] == 1
    assert forward["compliance_posture"] == "NOTICE_PENDING"

    acknowledged = validate_success(
        api_client.acknowledge_compliance_notice(notice["id"], {}, headers=borrower_headers)
    )
    assert_compliance_notice(acknowledged)
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_instant(acknowledged["acknowledged_at"], CLOCK)
    assert_instant(acknowledged["closed_at"], CLOCK)
    assert acknowledged["acknowledged_by_role"] == "Borrower"

    restored = read_folio(folio_id)
    assert restored["open_notice_count"] == pre["open_notice_count"]
    assert restored["compliance_posture"] == pre["compliance_posture"]

    # The count is conserved over SENT status, not over row existence.
    rows, meta = validate_paginated(
        api_client.list_compliance_notices(
            headers=borrower_headers, params={"loan_folio_id": folio_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == notice["id"]
    assert rows[0]["status"] == "ACKNOWLEDGED"

    # No money moved anywhere along the way.
    assert restored["escrow_balance_cents"] == 500000
    assert restored["cumulative_earned_premium_cents"] == 0
    assert restored["force_placed_premium_cents"] == 0
    assert restored["insurance_status"] == "NONE"
    assert_escrow_conservation(restored)

    # The compensating action is not itself repeatable.
    validate_error(
        api_client.acknowledge_compliance_notice(notice["id"], {}, headers=borrower_headers),
        ApiErrorId.ERR_INVALID_NOTICE_STATE.value,
        409,
    )
    assert read_folio(folio_id)["open_notice_count"] == 0


def test_notice_cooldown_window_is_closed_at_its_upper_end():
    """The cooldown occupies a closed window whose upper end is inclusive, so the
    last blocked instant and the first free instant are one day apart, and a
    different notice type is a different obligation slot that never contends.

    PRD §3.6: "A cooldown prevents notice spam: a new notice of the same `notice_type` on the same folio is refused while an existing `SENT` notice of that type has a closed window — running from its `sent_at` through 5 days past its `response_deadline_at`, both ends inclusive — that contains the current logical instant, and the refusal is `ERR_NOTICE_WINDOW_ACTIVE`."
    PRD §3.6: "A notice that survives all of that is created in `status` `SENT` with `sent_at` at the current logical instant, and its `response_deadline_at` is computed as `sent_at` plus a response window that depends on the type: 45 days for `MANDATORY_PURCHASE`, 30 days for `FORCE_PLACEMENT_WARNING`, 30 days for `RE_DETERMINATION` and 15 days for `COVERAGE_UNAVAILABLE`."
    PRD §3.6: "Fifth, if a compliance notice exists on this folio whose `notice_type` is `MANDATORY_PURCHASE`, whose `status` is `SENT` or `EXPIRED`, and whose `response_deadline_at` is strictly earlier than the current logical instant, the posture is `FORCE_PLACE_ELIGIBLE`."
    PRD §2.10: "`open_notice_count` on a folio is defined as the number of compliance notices on that folio whose `status` is `SENT`, counted across every notice type and with no time window applied, and it is recomputed by full re-count after every notice creation and after every notice transition out of `SENT`."

    Design: Difficulty/resource_temporal_overlap/notice_cooldown_closed_window_inclusive_upper_bound
    """
    chain = setup_folio_with_mandatory_notice(clock=CLOCK)
    folio_id = chain["folio"]["id"]
    determination_id = chain["determination"]["id"]
    lender_headers = chain["lender_headers"]

    first = chain["notice"]
    assert_instant(first["sent_at"], CLOCK)
    assert_instant(first["response_deadline_at"], "2026-09-15T00:00:00Z")
    # The cooldown therefore runs [2026-08-01, 2026-09-20], both ends inclusive.

    mandatory_payload = create_compliance_notice_payload(folio_id, determination_id)
    warning_payload = create_compliance_notice_payload(
        folio_id, determination_id, notice_type="FORCE_PLACEMENT_WARNING"
    )

    before_refusal = read_folio(folio_id)
    set_clock("2026-09-20T00:00:00Z")
    validate_error(
        api_client.create_compliance_notice(mandatory_payload, headers=lender_headers),
        ApiErrorId.ERR_NOTICE_WINDOW_ACTIVE.value,
        409,
    )
    after_refusal = read_folio(folio_id)
    assert after_refusal["open_notice_count"] == 1
    assert after_refusal["version"] == before_refusal["version"]

    # Same folio, same instant, different obligation slot.
    warning = validate_success(
        api_client.create_compliance_notice(warning_payload, headers=lender_headers), 201
    )
    assert warning["notice_type"] == "FORCE_PLACEMENT_WARNING"
    assert_instant(warning["sent_at"], "2026-09-20T00:00:00Z")
    assert_instant(warning["response_deadline_at"], "2026-10-20T00:00:00Z")

    set_clock("2026-09-21T00:00:00Z")
    third = validate_success(
        api_client.create_compliance_notice(mandatory_payload, headers=lender_headers), 201
    )
    assert third["status"] == "SENT"
    assert_instant(third["sent_at"], "2026-09-21T00:00:00Z")
    assert_instant(third["response_deadline_at"], "2026-11-05T00:00:00Z")

    # The cooldown limits the issuance rate; it closes no prior notice.
    rows, meta = validate_paginated(
        api_client.list_compliance_notices(
            headers=lender_headers, params={"loan_folio_id": folio_id}
        )
    )
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {first["id"], warning["id"], third["id"]}
    assert all(row["status"] == "SENT" for row in rows)

    final = read_folio(folio_id)
    assert final["open_notice_count"] == 3
    # The lapsed first notice still wins the posture ladder over the fresh one.
    assert final["compliance_posture"] == "FORCE_PLACE_ELIGIBLE"


def test_a_superseded_determination_can_no_longer_be_named_by_a_dispute_or_a_notice():
    """A re-determination quietly retires its predecessor: the stale identifier
    keeps resolving on its detail read, while every write that names it is refused
    for its state rather than for being absent.

    PRD §3.5: "Any prior determination for the same folio and structure that was in `ISSUED` or `FLAGGED_FOR_REVIEW` is moved to `SUPERSEDED` with its `superseded_at` set to the current logical instant, and the new row names it in `supersedes_determination_id`; on the flagged path the retired row keeps the `flagged_reason` it was carrying and the folio's `pending_redetermination_count` is decremented, while on the plain issued path there is no flagged reason to carry."
    PRD §3.9: "The challenged determination must be in `status` `ISSUED`; a determination already `FLAGGED_FOR_REVIEW`, `UNDER_DISPUTE` or `SUPERSEDED` may not be disputed, and the attempt is rejected with `ERR_INVALID_DETERMINATION_STATE`."
    PRD §3.6: "The cited determination must be the folio's `current_determination_id`, or the request is rejected with `ERR_STRUCTURE_FOLIO_MISMATCH`; a determination already `SUPERSEDED` when a notice names it is rejected with `ERR_INVALID_DETERMINATION_STATE`."
    PRD §2.5: "When one request violates two rules, the violation with the smaller priority number supplies both the `error_id` and the HTTP status of the response, and the lower-priority violation is never reported."
    PRD §3.9: "The challenged determination simultaneously moves `ISSUED → UNDER_DISPUTE`, which locks it for the duration of the joint review, and the folio's `compliance_posture` is recomputed — force placement is blocked while the review is open."

    Design: Corner/errors/corner_superseded_determination_cannot_be_named_by_a_dispute_or_a_notice
    """
    chain = setup_base_chain(clock=CLOCK, community_overrides={"participation_status": "REGULAR"})
    folio_id = chain["folio"]["id"]
    retired = chain["determination"]
    live = issue_determination(
        folio_id, chain["structure"]["id"], determination_type="LIFE_OF_LOAN_REVIEW"
    )
    assert live["supersedes_determination_id"] == retired["id"]

    # The retired identifier still resolves; a not-found error would be wrong.
    stale = validate_success(
        api_client.get_determination(retired["id"], headers=make_analyst_headers())
    )
    assert stale["status"] == "SUPERSEDED"
    assert_instant(stale["superseded_at"], CLOCK)

    borrower_headers = make_borrower_headers(chain["folio"]["borrower_user_id"])
    validate_error(
        api_client.create_dispute(
            create_dispute_payload(retired["id"]), headers=borrower_headers
        ),
        ApiErrorId.ERR_INVALID_DETERMINATION_STATE.value,
        409,
    )
    # The notice would otherwise be permitted by the folio's posture, and the
    # citation is also not the folio's current determination; the state rung is
    # the lower priority number, so it is the one reported.
    validate_error(
        api_client.create_compliance_notice(
            create_compliance_notice_payload(folio_id, retired["id"]),
            headers=chain["lender_headers"],
        ),
        ApiErrorId.ERR_INVALID_DETERMINATION_STATE.value,
        409,
    )

    dispute = validate_success(
        api_client.create_dispute(create_dispute_payload(live["id"]), headers=borrower_headers),
        201,
    )
    assert dispute["status"] == "SUBMITTED"
    disputed = validate_success(
        api_client.get_determination(live["id"], headers=make_analyst_headers())
    )
    assert disputed["status"] == "UNDER_DISPUTE"
    assert validate_success(
        api_client.get_determination(retired["id"], headers=make_analyst_headers())
    )["status"] == "SUPERSEDED"

    # Neither refusal left a notice behind.
    _, meta = validate_paginated(
        api_client.list_compliance_notices(
            headers=chain["lender_headers"], params={"loan_folio_id": folio_id}
        )
    )
    assert meta["total_count"] == 0
    assert read_folio(folio_id)["open_notice_count"] == 0
