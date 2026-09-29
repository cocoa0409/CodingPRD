"""Force placement: eligibility, the two premium figures, and the escrow ledger.

Force placement is the lender's last resort and it is fenced in on every side —
by the notice deadline, by the lender's own authorisations, by the folio's
coverage dimension and finally by the cash in escrow.  The premium appears twice
in the system, as a forward-looking estimate frozen on the notice and as the
chronological charge drawn from escrow, and the two are deliberately different
numbers.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_compliance_notice,
    assert_escrow_conservation,
    assert_loan_folio,
    correct_geocode,
    create_lender,
    force_place,
    issue_determination,
    make_analyst_headers,
    make_lender_headers,
    open_folio,
    read_folio,
    report_insurance,
    send_notice,
    set_clock,
    setup_base_chain,
    setup_folio_with_mandatory_notice,
)

CLOCK = "2026-08-01T00:00:00Z"
DEADLINE = "2026-09-15T00:00:00Z"


def assert_instant(actual, expected_utc):
    """Compare a timestamp field to an instant.

    PRD 2.4 fixes the wire format at three fractional digits, so an instant the
    test supplied as ``...T00:00:00Z`` is read back as ``...T00:00:00.000Z``.
    """
    assert actual is not None, f"expected the instant {expected_utc}, got null"
    assert actual.replace(".000Z", "Z") == expected_utc, (
        f"{actual!r} is not the instant {expected_utc}"
    )


def test_notice_estimate_rolls_the_policy_anniversary_past_its_anchor():
    """An anniversary that falls on or before the notice deadline is advanced by a
    full calendar year — exactly once — so a date a month before the anchor buys
    eleven whole months of premium rather than none.

    PRD §3.6: "Both premium figures start from the same anniversary roll."
    PRD §3.6: "Take the folio's `policy_anniversary_date`; while that date is at or before the variant's own anchor instant, advance it by exactly one calendar year, repeating until it is strictly after the anchor."
    PRD §3.6: "Its anchor is the notice's own `response_deadline_at`."
    PRD §3.6: "It counts whole calendar months between anchor and rolled anniversary: take twelve times the difference in years, add the difference in months, then subtract one if the anniversary's day-of-month is earlier than the anchor's day-of-month, and floor the result at zero."
    PRD §3.6: "The estimate is `annual_premium_rate_cents` multiplied by that whole-month count, divided by 12, and rounded half-up to a whole cent."

    Design: Corner/calculations/corner_force_place_estimate_rolls_anniversary_past_the_anchor
    """
    chain = setup_base_chain(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        folio_overrides={"policy_anniversary_date": "2026-08-15T00:00:00Z"},
    )
    folio_id = chain["folio"]["id"]

    rolled = send_notice(
        folio_id, chain["determination"]["id"], chain["lender"]["id"],
        annual_premium_rate_cents=288000,
    )
    assert_compliance_notice(rolled)
    assert_instant(rolled["response_deadline_at"], DEADLINE)
    # 2026-08-15 is at or before the 2026-09-15 anchor, so it rolls once to
    # 2027-08-15: 12 * 1 + (8 - 9) == 11 whole months, and 15 < 15 is false.
    assert rolled["estimated_force_place_premium_cents"] == 264000
    assert rolled["required_coverage_snapshot_cents"] == 25000000

    # A second folio whose anniversary is already past the anchor does not roll,
    # so the same rate buys only the six months that actually remain.
    unrolled_folio = open_folio(
        chain["lender"]["id"],
        chain["property"]["id"],
        loan_number="LN-4402",
        borrower_user_id="borrower-b",
        policy_anniversary_date="2027-03-15T00:00:00Z",
    )
    unrolled_determination = issue_determination(
        unrolled_folio["id"], chain["structure"]["id"]
    )
    unrolled = send_notice(
        unrolled_folio["id"], unrolled_determination["id"], chain["lender"]["id"],
        annual_premium_rate_cents=288000,
    )
    assert_instant(unrolled["response_deadline_at"], DEADLINE)
    assert unrolled["estimated_force_place_premium_cents"] == 144000

    assert read_folio(folio_id)["compliance_posture"] == "NOTICE_PENDING"


def test_force_placement_is_refused_for_a_lender_that_is_not_authorized_to_place():
    """With every earlier gate satisfied — coverage available, deadline lapsed —
    the refusal isolates the lender's own authorisation flag, and no money is
    drawn on the way out.

    PRD §3.1: "A `ProviderAnalyst` supplies the institution `name` and a `contact_email` used as the delivery address for compliance notices, and may override two flags that both default to true: `force_placement_authorized_flag` is false when the lender's servicing agreement forbids force placement, and `escrow_servicing_flag` is false when the lender does not escrow and therefore may not have force-placed premiums debited."
    PRD §3.6: "The owning lender must have `force_placement_authorized_flag` true, or the request is rejected with `ERR_FORCE_PLACEMENT_NOT_AUTHORIZED` (HTTP 403), and must have `escrow_servicing_flag` true, since a non-escrowing lender may not have premiums debited."
    PRD §3.6: "Finally the folio's `escrow_balance_cents` must be at or above the computed `force_placed_premium_cents`, or the request is rejected with `ERR_ESCROW_INSUFFICIENT` (HTTP 402) and nothing is drawn."
    PRD §3.1: "A newly registered lender has `open_force_placement_count` initialised to 0; thereafter that field is a re-count of the loan folios naming this lender whose `insurance_status` is `FORCE_PLACED`, and it is re-derived whenever a force placement is executed or settled."

    Design: Corner/validations/corner_force_placement_rejected_for_unauthorized_lender
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        lender_overrides={
            "name": "Unauthorized Servicer",
            "contact_email": "ops@unauth.example",
            "force_placement_authorized_flag": False,
            "escrow_servicing_flag": True,
        },
        folio_overrides={"escrow_balance_cents": 500000},
    )
    folio_id = chain["folio"]["id"]
    notice = chain["notice"]

    # The clock is now strictly past the notice's 45-day response deadline, so
    # the notice sweep force placement runs before evaluating eligibility finds
    # the folio force-place eligible and the ladder reaches rung 14.  PRD 3.6
    # pins the posture refresh to writes ("The posture is recomputed on every
    # write that touches the folio, its current determination, its notice set,
    # or its property's community"), so no posture is asserted on a bare read.
    set_clock("2026-09-16T00:00:00Z")

    validate_error(
        api_client.force_place(folio_id, {}, headers=chain["lender_headers"]),
        ApiErrorId.ERR_FORCE_PLACEMENT_NOT_AUTHORIZED.value,
        403,
    )

    after = read_folio(folio_id)
    assert after["insurance_status"] == "NONE"
    assert after["force_placed_at"] is None
    assert after["force_placed_premium_cents"] == 0
    assert after["force_placed_coverage_days"] == 0
    # The fiscal draw never ran.
    assert after["escrow_balance_cents"] == 500000
    assert_escrow_conservation(after)

    lender = validate_success(
        api_client.get_lender(chain["lender"]["id"], headers=chain["lender_headers"])
    )
    assert lender["open_force_placement_count"] == 0
    # PRD 3.6 runs the notice sweep unconditionally ahead of the eligibility
    # rung — "Before evaluating eligibility it first sweeps the folio's notices:
    # any notice still in `SENT` whose `response_deadline_at` has passed is moved
    # `SENT → EXPIRED` with `closed_at` set to the current logical instant" — and
    # the authorisation rung (14) sits below the eligibility rung (13), so the
    # lapsed notice is already closed when the refusal is issued.  What the
    # refusal spares is the money, not the sweep.
    swept = validate_success(
        api_client.get_compliance_notice(notice["id"], headers=chain["lender_headers"])
    )
    assert swept["status"] == "EXPIRED"
    assert_instant(swept["closed_at"], "2026-09-16T00:00:00Z")
    assert after["open_notice_count"] == 0


def test_an_unlapsed_notice_period_is_reported_ahead_of_the_authorization_failure():
    """One request breaks three rules at once — the deadline has not lapsed, the
    lender may not place, and the escrow could not fund it — and only the
    smallest priority number is allowed to answer.

    PRD §2.5: "Requests are checked against a single ordered ladder, and the ladder is evaluated strictly from the lowest priority number upward."
    PRD §2.5: "When one request violates two rules, the violation with the smaller priority number supplies both the `error_id` and the HTTP status of the response, and the lower-priority violation is never reported."
    PRD §2.5: "Thirteenth (13) force placement requires a lapsed mandatory-purchase notice and no pending re-determination, reporting `ERR_NOTICE_PERIOD_NOT_EXPIRED`; fourteenth (14) the lender must be authorised to force place, reporting `ERR_FORCE_PLACEMENT_NOT_AUTHORIZED`; fifteenth (15) a mandatory-purchase notice requires a determination that actually triggers the mandatory purchase requirement, reporting `ERR_MANDATORY_PURCHASE_NOT_TRIGGERED`."
    PRD §3.6: "Force placement then requires the folio's `insurance_status` to be `NONE` — attempting it on a folio already `FORCE_PLACED` or `BORROWER_PROVIDED`, or on a folio whose `monitoring_status` is `SUSPENDED`, is rejected with `ERR_INVALID_FOLIO_STATE` (HTTP 409) — and requires `compliance_posture` to be exactly `FORCE_PLACE_ELIGIBLE`, failing which the rejection is `ERR_NOTICE_PERIOD_NOT_EXPIRED`: either no mandatory-purchase notice was ever sent, or its deadline has not passed, or a pending re-determination is holding the folio in `REVIEW_PENDING`."

    Design: Corner/validations/corner_force_placement_reports_notice_period_before_authorization
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        lender_overrides={
            "name": "Unauthorized Servicer",
            "contact_email": "ops@unauth.example",
            "force_placement_authorized_flag": False,
            "escrow_servicing_flag": True,
        },
        folio_overrides={"escrow_balance_cents": 100},
    )
    folio_id = chain["folio"]["id"]

    # The clock is still the send instant, so the deadline is 45 days away.
    pending = read_folio(folio_id)
    assert pending["compliance_posture"] == "NOTICE_PENDING"
    assert pending["escrow_balance_cents"] == 100

    error = validate_error(
        api_client.force_place(folio_id, {}, headers=chain["lender_headers"]),
        ApiErrorId.ERR_NOTICE_PERIOD_NOT_EXPIRED.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_FORCE_PLACEMENT_NOT_AUTHORIZED.value
    assert error["error_id"] != ApiErrorId.ERR_ESCROW_INSUFFICIENT.value

    after = read_folio(folio_id)
    assert after["insurance_status"] == "NONE"
    assert after["escrow_balance_cents"] == 100


def test_a_pending_re_determination_outranks_a_lapsed_notice_in_the_posture_ladder():
    """One folio walks three postures without a single write to itself: the clock
    alone lapses its notice, and a geocode correction two entities away then
    masks that lapse because the earlier clause fires first.

    PRD §3.6: "Sixth, if a compliance notice exists on this folio whose `notice_type` is `MANDATORY_PURCHASE`, whose `status` is `SENT`, and whose `response_deadline_at` is at or after the current logical instant, the posture is `NOTICE_PENDING`."
    PRD §3.6: "Fifth, if a compliance notice exists on this folio whose `notice_type` is `MANDATORY_PURCHASE`, whose `status` is `SENT` or `EXPIRED`, and whose `response_deadline_at` is strictly earlier than the current logical instant, the posture is `FORCE_PLACE_ELIGIBLE`."
    PRD §3.6: "Third, if `pending_redetermination_count` is greater than zero the posture is `REVIEW_PENDING`."
    PRD §3.6: "The clause order is load-bearing: a folio that has both a lapsed notice and a pending re-determination reports `REVIEW_PENDING`, not `FORCE_PLACE_ELIGIBLE`, so an in-flight map revision blocks force placement."
    PRD §3.4: "In the second hop, because the parcel has effectively moved, every determination in `status` `ISSUED` that was issued against a structure of this property moves `ISSUED → FLAGGED_FOR_REVIEW` with `flagged_reason` set to `GEOCODE_CORRECTION`, and each affected folio re-counts `pending_redetermination_count` and recomputes `compliance_posture`."

    Design: Corner/calculations/corner_posture_review_pending_outranks_force_place_eligible
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK, community_overrides={"participation_status": "REGULAR"}
    )
    folio_id = chain["folio"]["id"]
    notice_id = chain["notice"]["id"]

    assert read_folio(folio_id)["compliance_posture"] == "NOTICE_PENDING"

    # Only the clock moves past the response deadline; PRD 3.6 pins the posture
    # refresh to writes ("The posture is recomputed on every write that touches
    # the folio, its current determination, its notice set, or its property's
    # community"), so the lapse is not asserted through a bare read here — the
    # force placement at the end of the test is what proves the notice lapsed
    # and that clause 3 masked it.
    set_clock("2026-09-16T00:00:00Z")

    correct_geocode(
        chain["property"]["id"],
        latitude=25.7618,
        longitude=-80.1919,
        geocode_method="ROOFTOP",
        geocode_confidence_score=0.99,
    )
    masked = read_folio(folio_id)
    assert masked["pending_redetermination_count"] == 1
    assert masked["compliance_posture"] == "REVIEW_PENDING"
    # Clause 4 cannot be what fired: the obligation is still unmet.
    assert masked["required_coverage_cents"] == 25000000
    assert masked["reported_coverage_cents"] == 0

    flagged = validate_success(
        api_client.get_determination(
            chain["determination"]["id"], headers=make_analyst_headers()
        )
    )
    assert flagged["status"] == "FLAGGED_FOR_REVIEW"
    assert flagged["flagged_reason"] == "GEOCODE_CORRECTION"

    # The earlier clause masks the lapsed notice; it does not resolve it.
    unchanged = validate_success(
        api_client.get_compliance_notice(notice_id, headers=chain["lender_headers"])
    )
    assert unchanged["status"] == "SENT"
    assert_instant(unchanged["response_deadline_at"], DEADLINE)

    # And the masking is what blocks the placement.
    validate_error(
        api_client.force_place(folio_id, {}, headers=chain["lender_headers"]),
        ApiErrorId.ERR_NOTICE_PERIOD_NOT_EXPIRED.value,
        409,
    )


def test_force_placement_eligibility_flips_one_second_after_the_deadline():
    """The eligibility threshold is instantaneous and one-sided: at the deadline
    instant itself the folio is still inside its notice window, and one second
    later the identical call succeeds and draws the premium.

    PRD §3.6: "That instant is the right-hand end of a closed response window, so an action taken exactly at the deadline is still inside it."
    PRD §3.6: "Before evaluating eligibility it first sweeps the folio's notices: any notice still in `SENT` whose `response_deadline_at` has passed is moved `SENT → EXPIRED` with `closed_at` set to the current logical instant and the folio's `open_notice_count` re-counted, which is what allows the posture ladder to read `FORCE_PLACE_ELIGIBLE` rather than `NOTICE_PENDING`."
    PRD §3.6: "`force_placed_coverage_days` is the exact number of days from that anchor up to but not including the rolled anniversary, and `force_placed_premium_cents` is `annual_premium_rate_cents` multiplied by `force_placed_coverage_days`, divided by 365, and rounded half-up to a whole cent — so the actual figure charges precisely the day-level remainder the estimate threw away, and the two numbers, living on two different entities, are both observable and normally differ."
    PRD §3.6: "On success the folio's coverage dimension moves `NONE → FORCE_PLACED`."
    PRD §3.6: "`force_placed_premium_cents` and `force_placed_coverage_days` are computed and stored, `force_placed_at` is set to the current logical instant, `escrow_balance_cents` is reduced by `force_placed_premium_cents` while `cumulative_earned_premium_cents` is deliberately left untouched (nothing has been earned yet), `uninsured_exposure_cents` is set to 0, `compliance_posture` becomes `FORCE_PLACED`, the citing notice is left in `EXPIRED` with its `closed_at` recorded, `open_notice_count` is re-counted, the owning lender's `open_force_placement_count` is re-counted, and the folio's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_force_placement_threshold_flips_one_second_after_the_deadline
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        folio_overrides={"escrow_balance_cents": 500000},
    )
    folio_id = chain["folio"]["id"]
    notice_id = chain["notice"]["id"]
    lender_headers = chain["lender_headers"]

    assert_instant(chain["notice"]["response_deadline_at"], DEADLINE)
    assert chain["notice"]["estimated_force_place_premium_cents"] == 144000
    before = read_folio(folio_id)

    set_clock("2026-09-14T23:59:59Z")
    validate_error(
        api_client.force_place(folio_id, {}, headers=lender_headers),
        ApiErrorId.ERR_NOTICE_PERIOD_NOT_EXPIRED.value,
        409,
    )

    set_clock(DEADLINE)
    validate_error(
        api_client.force_place(folio_id, {}, headers=lender_headers),
        ApiErrorId.ERR_NOTICE_PERIOD_NOT_EXPIRED.value,
        409,
    )
    at_deadline = read_folio(folio_id)
    assert at_deadline["compliance_posture"] == "NOTICE_PENDING"
    # Neither refusal consumed anything.
    assert at_deadline["version"] == before["version"]
    assert at_deadline["open_notice_count"] == 1
    assert validate_success(
        api_client.get_compliance_notice(notice_id, headers=lender_headers)
    )["status"] == "SENT"

    set_clock("2026-09-15T00:00:01Z")
    placed = validate_success(
        api_client.force_place(folio_id, {}, headers=lender_headers), 200
    )
    assert_loan_folio(placed)
    assert placed["insurance_status"] == "FORCE_PLACED"
    assert placed["compliance_posture"] == "FORCE_PLACED"
    # 2026-09-15T00:00:01 up to but not including 2027-03-15 is 180 whole days,
    # and 288000 * 180 / 365 rounds half-up to 142027.
    assert placed["force_placed_coverage_days"] == 180
    assert placed["force_placed_premium_cents"] == 142027
    assert placed["escrow_balance_cents"] == 500000 - 142027 == 357973
    assert placed["cumulative_earned_premium_cents"] == 0
    assert placed["uninsured_exposure_cents"] == 0
    assert placed["open_notice_count"] == 0

    expired = validate_success(
        api_client.get_compliance_notice(notice_id, headers=lender_headers)
    )
    assert expired["status"] == "EXPIRED"
    assert_instant(expired["closed_at"], "2026-09-15T00:00:01Z")


def test_foreign_lender_is_refused_ownership_before_any_folio_state_is_examined():
    """A lender that owns nothing on the folio is answered by the ownership rung
    alone, whatever state the folio happens to be in, and the refusal leaks no
    field of the folio it was aimed at.

    PRD §2.5: "Seventh (7) a `Lender` caller's ownership of the target folio is checked, reporting `ERR_FOLIO_NOT_OWNED`; and eighth (8) a `Borrower` caller's presence on the target folio is checked, reporting `ERR_BORROWER_NOT_ON_LOAN`."
    PRD §2.5: "Eleventh (11), the target entity must be in a state from which the requested transition is declared, reporting the invalid-state error for that entity type at HTTP 409."
    PRD §3.6: "Force placement is a `Lender` action on its own folio and takes no body fields at all; everything it needs it derives."
    PRD §2.1: "`X-User-ID` must be present and non-empty on every request that is not a `GET`; read-only requests may omit it."

    Design: Difficulty/priority_pair_validation_conflict/lender_ownership_precedes_folio_state_on_foreign_force_placement
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        folio_overrides={"escrow_balance_cents": 500000},
    )
    owner_id = chain["lender"]["id"]
    folio_id = chain["folio"]["id"]

    intruder = create_lender(
        name="Second Harbor Credit Union",
        contact_email="ops@secondharbor.example",
        force_placement_authorized_flag=True,
        escrow_servicing_flag=True,
    )
    intruder_headers = make_lender_headers(intruder["id"])

    # A folio of the owner's that is still uninsured: the ownership answer must
    # not depend on the state of the target.
    quiet_folio = open_folio(
        owner_id, chain["property"]["id"], loan_number="LN-4402", borrower_user_id="borrower-b"
    )
    validate_error(
        api_client.force_place(quiet_folio["id"], {}, headers=intruder_headers),
        ApiErrorId.ERR_FOLIO_NOT_OWNED.value,
        403,
    )

    set_clock("2026-09-16T00:00:00Z")
    placed = force_place(folio_id, owner_id)
    assert placed["insurance_status"] == "FORCE_PLACED"
    assert placed["force_placed_premium_cents"] == 142027

    error = validate_error(
        api_client.force_place(folio_id, {}, headers=intruder_headers),
        ApiErrorId.ERR_FOLIO_NOT_OWNED.value,
        403,
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_FOLIO_STATE.value
    # Nothing about the folio is echoed to a lender that does not own it.
    assert set(error) == {"error_id", "message"}

    # The gate is on the write path only; the read stays open.
    visible = validate_success(
        api_client.get_loan_folio(folio_id, headers=intruder_headers)
    )
    assert visible["escrow_balance_cents"] == 357973
    assert visible["force_placed_premium_cents"] == 142027


def test_estimate_and_actual_premium_are_two_different_numbers_on_two_entities():
    """The same rate and the same anniversary produce two premiums: a whole-month
    estimate frozen on the notice and a day-level charge drawn from escrow, and
    the day-level remainder the estimate discarded is exactly the gap.

    PRD §3.6: "Both premium figures start from the same anniversary roll."
    PRD §3.6: "The forward-looking estimate is computed once, at notice send time, and stored on the notice as `estimated_force_place_premium_cents`."
    PRD §3.6: "The actual premium is computed at force placement and stored on the folio as `force_placed_premium_cents`."
    PRD §3.6: "Its anchor is the current logical instant at placement."
    PRD §3.6: "`force_placed_coverage_days` is the exact number of days from that anchor up to but not including the rolled anniversary, and `force_placed_premium_cents` is `annual_premium_rate_cents` multiplied by `force_placed_coverage_days`, divided by 365, and rounded half-up to a whole cent — so the actual figure charges precisely the day-level remainder the estimate threw away, and the two numbers, living on two different entities, are both observable and normally differ."
    PRD §3.6: "The `annual_premium_rate_cents` used at placement comes from the notice that made the folio eligible: among the folio's notices with `notice_type` `MANDATORY_PURCHASE` and `status` `SENT` or `EXPIRED`, the one with the greatest `sent_at`, breaking a tie on `created_at` ascending."

    Design: Difficulty/dual_variant_calc/force_place_premium_forward_estimate_vs_chronological_actual
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        folio_overrides={
            "escrow_balance_cents": 500000,
            "policy_anniversary_date": "2027-03-15T00:00:00Z",
        },
        notice_overrides={"annual_premium_rate_cents": 288000},
    )
    folio_id = chain["folio"]["id"]
    lender_id = chain["lender"]["id"]

    # Variant one, anchored on the deadline: whole months only.  2026-09-15 to
    # 2027-03-15 is 6 whole months, and 288000 * 6 / 12 == 144000.
    estimate = chain["notice"]["estimated_force_place_premium_cents"]
    assert estimate == 144000

    set_clock("2026-09-16T00:00:00Z")
    placed = force_place(folio_id, lender_id)
    assert_loan_folio(placed)
    # Variant two, anchored on the placement instant: whole days.  2026-09-16 to
    # 2027-03-15 is 180 days, and 288000 * 180 / 365 == 142027.397... -> 142027.
    assert placed["force_placed_coverage_days"] == 180
    actual = placed["force_placed_premium_cents"]
    assert actual == 142027
    assert estimate - actual == 1973
    assert actual != estimate

    assert placed["insurance_status"] == "FORCE_PLACED"
    assert placed["compliance_posture"] == "FORCE_PLACED"
    assert placed["escrow_balance_cents"] == 500000 - actual
    assert placed["uninsured_exposure_cents"] == 0
    assert placed["required_coverage_cents"] == 25000000
    assert_instant(placed["force_placed_at"], "2026-09-16T00:00:00Z")

    lender = validate_success(
        api_client.get_lender(lender_id, headers=chain["lender_headers"])
    )
    assert lender["open_force_placement_count"] == 1
    assert validate_success(
        api_client.get_compliance_notice(
            chain["notice"]["id"], headers=chain["lender_headers"]
        )
    )["status"] == "EXPIRED"


def test_the_notices_frozen_estimate_survives_the_actual_premium_being_written():
    """Writing the actual premium does not correct the estimate that preceded it:
    the notice keeps the number it was sent with, so both variants are readable
    side by side after the placement.

    PRD §3.6: "The forward-looking estimate is computed once, at notice send time, and stored on the notice as `estimated_force_place_premium_cents`."
    PRD §3.6: "The actual premium is computed at force placement and stored on the folio as `force_placed_premium_cents`."
    PRD §3.6: "`force_placed_premium_cents` and `force_placed_coverage_days` are computed and stored, `force_placed_at` is set to the current logical instant, `escrow_balance_cents` is reduced by `force_placed_premium_cents` while `cumulative_earned_premium_cents` is deliberately left untouched (nothing has been earned yet), `uninsured_exposure_cents` is set to 0, `compliance_posture` becomes `FORCE_PLACED`, the citing notice is left in `EXPIRED` with its `closed_at` recorded, `open_notice_count` is re-counted, the owning lender's `open_force_placement_count` is re-counted, and the folio's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_both_premium_variants_persist_side_by_side
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        folio_overrides={
            "escrow_balance_cents": 500000,
            "policy_anniversary_date": "2027-03-15T00:00:00Z",
        },
        notice_overrides={"annual_premium_rate_cents": 288000},
    )
    folio_id = chain["folio"]["id"]
    notice_id = chain["notice"]["id"]
    lender_headers = chain["lender_headers"]

    set_clock("2026-09-15T00:00:01Z")
    placed = force_place(folio_id, chain["lender"]["id"])
    assert placed["force_placed_premium_cents"] == 142027
    assert placed["escrow_balance_cents"] == 357973
    # Nothing has been earned yet, so the draw is still entirely refundable and
    # the whole premium sits in `force_placed_premium_cents`: PRD 3.6 has escrow
    # "reduced by `force_placed_premium_cents` while `cumulative_earned_premium_cents`
    # is deliberately left untouched (nothing has been earned yet)", so mid-flight
    # the cash is conserved across the balance plus the in-flight premium.
    assert placed["cumulative_earned_premium_cents"] == 0
    assert (
        placed["escrow_balance_cents"] + placed["force_placed_premium_cents"]
        == placed["initial_escrow_balance_cents"]
        == 500000
    )

    frozen = validate_success(
        api_client.get_compliance_notice(notice_id, headers=lender_headers)
    )
    assert_compliance_notice(frozen)
    # The estimate is a record of what was disclosed, not a running figure.
    assert frozen["estimated_force_place_premium_cents"] == 144000
    assert frozen["status"] == "EXPIRED"
    assert_instant(frozen["closed_at"], "2026-09-15T00:00:01Z")
    assert frozen["required_coverage_snapshot_cents"] == 25000000

    # Both numbers remain readable, on their two separate entities.
    assert read_folio(folio_id)["force_placed_premium_cents"] == 142027
    assert validate_success(
        api_client.get_compliance_notice(notice_id, headers=lender_headers)
    )["estimated_force_place_premium_cents"] == 144000


def test_a_second_force_placement_reports_folio_state_before_the_escrow_shortfall():
    """A folio that is already force placed and has almost no escrow left breaks
    both the state rung and the fiscal rung; the state rung answers, and a
    control folio proves the fiscal rung would otherwise have fired.

    PRD §2.5: "Eleventh (11), the target entity must be in a state from which the requested transition is declared, reporting the invalid-state error for that entity type at HTTP 409."
    PRD §2.5: "The domain ordering behind the ladder is that regulatory and safety failures are reported ahead of referential failures, referential ahead of temporal, temporal ahead of structural constraints, and structural constraints ahead of money — telling a lender that coverage is unavailable in this community is more actionable than telling it that the escrow is short.

The ladder, in evaluation order, is as follows."
    PRD §3.6: "Force placement then requires the folio's `insurance_status` to be `NONE` — attempting it on a folio already `FORCE_PLACED` or `BORROWER_PROVIDED`, or on a folio whose `monitoring_status` is `SUSPENDED`, is rejected with `ERR_INVALID_FOLIO_STATE` (HTTP 409) — and requires `compliance_posture` to be exactly `FORCE_PLACE_ELIGIBLE`, failing which the rejection is `ERR_NOTICE_PERIOD_NOT_EXPIRED`: either no mandatory-purchase notice was ever sent, or its deadline has not passed, or a pending re-determination is holding the folio in `REVIEW_PENDING`."
    PRD §3.6: "Finally the folio's `escrow_balance_cents` must be at or above the computed `force_placed_premium_cents`, or the request is rejected with `ERR_ESCROW_INSUFFICIENT` (HTTP 402) and nothing is drawn."

    Design: Difficulty/priority_pair_validation_conflict/folio_state_precedes_escrow_fiscal_check_on_second_force_placement
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        folio_overrides={
            "escrow_balance_cents": 145000,
            "policy_anniversary_date": "2027-03-15T00:00:00Z",
        },
        notice_overrides={"annual_premium_rate_cents": 288000},
    )
    folio_id = chain["folio"]["id"]
    lender_id = chain["lender"]["id"]
    lender_headers = chain["lender_headers"]

    # A control folio under the same lender, noticed at the same instant, whose
    # escrow can never fund the premium.
    control = open_folio(
        lender_id,
        chain["property"]["id"],
        loan_number="LN-4402",
        borrower_user_id="borrower-b",
        escrow_balance_cents=100000,
        policy_anniversary_date="2027-03-15T00:00:00Z",
    )
    control_determination = issue_determination(control["id"], chain["structure"]["id"])
    send_notice(
        control["id"], control_determination["id"], lender_id,
        annual_premium_rate_cents=288000,
    )

    set_clock("2026-09-16T00:00:00Z")
    placed = force_place(folio_id, lender_id)
    assert placed["force_placed_premium_cents"] == 142027
    assert placed["escrow_balance_cents"] == 145000 - 142027 == 2973

    set_clock("2026-09-20T00:00:00Z")
    # 2026-09-20 to 2027-03-15 is 176 days: 288000 * 176 / 365 == 138871.23...,
    # so 138871 is wanted and only 2973 is left — yet the state rung is earlier.
    validate_error(
        api_client.force_place(folio_id, {}, headers=lender_headers),
        ApiErrorId.ERR_INVALID_FOLIO_STATE.value,
        409,
    )

    untouched = read_folio(folio_id)
    assert untouched["insurance_status"] == "FORCE_PLACED"
    assert untouched["escrow_balance_cents"] == 2973
    assert untouched["cumulative_earned_premium_cents"] == 0
    assert untouched["force_placed_premium_cents"] == 142027
    assert untouched["force_placed_coverage_days"] == 180
    assert_instant(untouched["force_placed_at"], "2026-09-16T00:00:00Z")
    assert validate_success(
        api_client.get_compliance_notice(
            chain["notice"]["id"], headers=lender_headers
        )
    )["status"] == "EXPIRED"

    # Same lender, same instant, same rate — but this folio is still `NONE`, so
    # it reaches the fiscal rung and is answered with the money-shaped error.
    validate_error(
        api_client.force_place(control["id"], {}, headers=lender_headers),
        ApiErrorId.ERR_ESCROW_INSUFFICIENT.value,
        402,
    )
    control_after = read_folio(control["id"])
    assert control_after["insurance_status"] == "NONE"
    assert control_after["escrow_balance_cents"] == 100000
    assert control_after["force_placed_premium_cents"] == 0
    assert_escrow_conservation(control_after)


def test_escrow_cash_is_conserved_across_placement_and_replacement():
    """Force placement draws cash out of escrow and the borrower's later policy
    hands the unearned part back; the refund absorbs the rounding remainder, so
    cash plus recognised premium returns to the opening balance exactly.

    PRD §2.10: "Thereafter, at every point where the folio is at rest, the sum of `escrow_balance_cents` and `cumulative_earned_premium_cents` must equal `initial_escrow_balance_cents` — after the forward action of force placement, which draws a premium out of escrow, and after its compensating action of coverage replacement, which recognises the earned portion and refunds the rest."
    PRD §3.6: "Settlement counts `days_in_force` as the number of days from `force_placed_at` up to but not including the current logical instant."
    PRD §3.6: "The earned premium is `force_placed_premium_cents` multiplied by `days_in_force`, divided by `force_placed_coverage_days`, rounded half-up to a whole cent."
    PRD §3.6: "The refund is `force_placed_premium_cents` minus that earned amount."
    PRD §3.6: "The refund is added to `escrow_balance_cents`, the earned amount is added to `cumulative_earned_premium_cents`, `force_placed_premium_cents` is reset to 0, `force_placed_coverage_days` is reset to 0, and `force_placed_at` is cleared to null."
    PRD §3.6: "Because the refund absorbs the rounding remainder, the conservation invariant of Section 2.10 holds exactly afterwards: `escrow_balance_cents` plus `cumulative_earned_premium_cents` equals `initial_escrow_balance_cents`."
    PRD §3.6: "The lender's `open_force_placement_count` is re-counted and `compliance_posture` recomputes to `COMPLIANT`."

    Design: Difficulty/compensating_invariant/escrow_cash_conserved_across_force_placement_and_replacement
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        community_overrides={"participation_status": "REGULAR"},
        folio_overrides={
            "escrow_balance_cents": 500000,
            "policy_anniversary_date": "2027-03-15T00:00:00Z",
        },
        notice_overrides={"annual_premium_rate_cents": 288000},
    )
    folio_id = chain["folio"]["id"]
    lender_id = chain["lender"]["id"]
    lender_headers = chain["lender_headers"]

    opening = read_folio(folio_id)
    assert opening["initial_escrow_balance_cents"] == 500000
    assert opening["cumulative_earned_premium_cents"] == 0
    assert_escrow_conservation(opening)

    set_clock("2026-09-16T00:00:00Z")
    placed = force_place(folio_id, lender_id)
    assert placed["force_placed_coverage_days"] == 180
    assert placed["force_placed_premium_cents"] == 142027
    assert placed["escrow_balance_cents"] == 357973
    assert placed["cumulative_earned_premium_cents"] == 0
    assert_instant(placed["force_placed_at"], "2026-09-16T00:00:00Z")
    # Mid-flight the invariant already holds: nothing has been recognised, and
    # the whole draw is still sitting in the premium field.
    assert placed["escrow_balance_cents"] + placed["force_placed_premium_cents"] == 500000
    assert validate_success(
        api_client.get_lender(lender_id, headers=lender_headers)
    )["open_force_placement_count"] == 1

    # One month in, the borrower buys a policy: 30 of the 180 days were used.
    set_clock("2026-10-16T00:00:00Z")
    settled = report_insurance(folio_id, lender_id, 25000000)
    assert_loan_folio(settled)
    assert settled["insurance_status"] == "BORROWER_PROVIDED"
    assert settled["compliance_posture"] == "COMPLIANT"
    # 142027 * 30 / 180 == 23671.166... -> 23671 earned, 118356 refunded.
    assert settled["cumulative_earned_premium_cents"] == 23671
    assert settled["escrow_balance_cents"] == 357973 + 118356 == 476329
    assert_escrow_conservation(settled)
    assert (
        settled["escrow_balance_cents"] + settled["cumulative_earned_premium_cents"]
        == settled["initial_escrow_balance_cents"]
        == 500000
    )
    # Every in-flight marker of the placement is cleared.
    assert settled["force_placed_premium_cents"] == 0
    assert settled["force_placed_coverage_days"] == 0
    assert settled["force_placed_at"] is None
    assert settled["reported_coverage_cents"] == 25000000
    assert settled["uninsured_exposure_cents"] == 0
    assert validate_success(
        api_client.get_lender(lender_id, headers=lender_headers)
    )["open_force_placement_count"] == 0

    # The notice is a historical record and settlement does not rewrite it.
    notice = validate_success(
        api_client.get_compliance_notice(chain["notice"]["id"], headers=lender_headers)
    )
    assert notice["status"] == "EXPIRED"
    assert notice["estimated_force_place_premium_cents"] == 144000
    assert_instant(notice["closed_at"], "2026-09-16T00:00:00Z")
