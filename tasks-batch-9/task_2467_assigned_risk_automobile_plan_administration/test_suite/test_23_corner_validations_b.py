"""Corner validations: stranded licences, spent cure rounds, freezes, notice
windows, tier precedence, closure preconditions and the claim reserve ceiling."""
from test_helpers import (
    EXAMINER_ONE_USER_ID,
    EXAMINER_TWO_USER_ID,
    ApiErrorId,
    accept_assignment,
    acknowledge_claim,
    api_client,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_applicant_with_vehicle,
    create_certification_payload,
    create_claim_closure_payload,
    create_complaint_payload,
    create_cure_return_payload,
    create_deposit_payload,
    create_findings_payload,
    create_licensing_amendment_payload,
    create_non_renewal_payload,
    create_policy_payload,
    create_rescission_payload,
    docket_complaint,
    file_two_market_rejections,
    issue_policy,
    make_compliance_examiner_headers,
    make_plan_administrator_headers,
    make_producer_agent_headers,
    make_servicing_carrier_headers,
    place_and_accept,
    read_applicant,
    read_application,
    read_assignment,
    read_assignment_cycle,
    read_carrier,
    read_claim,
    read_complaint,
    read_plan_period,
    read_policy,
    record_deposit,
    record_findings,
    report_claim,
    resolve_complaint,
    resubmit,
    return_for_cure,
    run_cycle,
    schedule_cycle,
    set_clock,
    setup_policy_in_force,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verify_mvr,
)

ADMIN_HEADERS = make_plan_administrator_headers()

ISSUANCE_CLOCK = "2026-09-15T00:00:00Z"
CLEAN_T02_REQUIRED_DEPOSIT_CENTS = 38939


# ==========================================================================
# A licence amendment can strand a risk the carrier may no longer write
# ==========================================================================
def _accepted_assignment_whose_carrier_lost_the_territory():
    """Atlas accepts a T02 risk, then a state filing narrows it to T01 only."""
    env = bootstrap_plan()
    risk = bring_application_to_certified(env, document_prefix="DEC-23-1")
    atlas = env["carriers"][0]
    placed = place_and_accept(env, risk["application"]["id"], atlas["id"])
    assert placed["assignment"]["carrier_id"] == atlas["id"]
    assert placed["assignment"]["status"] == "ACCEPTED"

    set_clock(ISSUANCE_CLOCK)
    validate_success(api_client.file_carrier_licensing_amendment(
        atlas["id"], create_licensing_amendment_payload(["T01"]), ADMIN_HEADERS))

    env.update(risk)
    env.update(placed)
    env["atlas"] = atlas
    return env


def _attempt_issuance_of_the_stranded_risk(env):
    return api_client.create_policy(
        create_policy_payload(env["assignment"]["id"],
                              policy_number="AR-100014",
                              effective_date=ISSUANCE_CLOCK,
                              expiration_date="2027-09-15T00:00:00Z"),
        make_servicing_carrier_headers(env["atlas"]["id"]))


def test_issuance_is_refused_when_the_carrier_no_longer_writes_the_garaging_territory():
    """The selector picked a licensed carrier; the licence moved afterwards.

    Atlas was licensed in T02 when the cycle designated it and it accepted the
    designation, so nothing about the assignment is defective. The state filing
    then replaced its territories with T01 alone, and the vehicle is still garaged
    in T02 — so the issuance the carrier is otherwise entitled to make is refused,
    and no policy row comes into existence.

    PRD: "The issuing carrier must be licensed in the vehicle's
    `garaging_territory_code`, or the request is refused with
    `ERR_CARRIER_NOT_LICENSED_IN_TERRITORY` and HTTP 422."
    Design: Corner/validations/a_licence_amendment_can_strand_a_risk_the_carrier_may_no_longer_write
    """
    env = _accepted_assignment_whose_carrier_lost_the_territory()

    response = _attempt_issuance_of_the_stranded_risk(env)

    validate_error(response, ApiErrorId.ERR_CARRIER_NOT_LICENSED_IN_TERRITORY, 422)
    assert read_assignment(env["assignment"]["id"])["status"] == "ACCEPTED"
    assert read_application(env["application"]["id"])["status"] == "ASSIGNED"
    _, meta = validate_paginated(api_client.list_policies(ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_the_amendment_leaves_the_standing_book_and_the_quota_exactly_where_they_were():
    """The refusal — not a silent re-placement — is the observable outcome.

    The amendment replaces the territory list wholesale and stops there: Atlas is
    still ACTIVE, still carries the risk in its headcount and still holds the one
    apportioned unit, because neither the set of active carriers nor the market
    share denominator moved. The vehicle stays garaged in a territory its own
    servicing carrier may no longer write.

    PRD: "Deliberately, the plan does *not* reassign the book: existing assignment
    and policy rows are left exactly where they are, so a carrier can end up
    servicing a risk garaged in a territory it may no longer write, and only
    *future* candidate filtering reflects the amendment."
    Design: Corner/validations/a_licence_amendment_can_strand_a_risk_the_carrier_may_no_longer_write
    """
    env = _accepted_assignment_whose_carrier_lost_the_territory()

    validate_error(_attempt_issuance_of_the_stranded_risk(env),
                   ApiErrorId.ERR_CARRIER_NOT_LICENSED_IN_TERRITORY, 422)

    atlas = read_carrier(env["atlas"]["id"])
    assert atlas["licensed_territories"] == ["T01"]
    assert atlas["status"] == "ACTIVE"
    assert atlas["posture"] == "OPEN"
    assert atlas["assigned_risk_count"] == 1
    assert atlas["quota_target_units"] == 1
    beacon = read_carrier(env["carriers"][1]["id"])
    assert beacon["quota_target_units"] == 0
    assert read_assignment(env["assignment"]["id"])["carrier_id"] == atlas["id"]
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 1


# ==========================================================================
# The cure loop allows two rounds and no more
# ==========================================================================
def _application_with_both_cure_rounds_spent():
    """A clean T02 ADULT risk returned and resubmitted twice: cure_count is 2."""
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    file_two_market_rejections(application["id"], env["producer"]["id"],
                               document_prefix="DEC-23-2")
    verify_mvr(application["id"], [])
    record_deposit(application["id"], env["producer"]["id"],
                   CLEAN_T02_REQUIRED_DEPOSIT_CENTS)

    return_for_cure(application["id"], "Garaging address unproven.")
    resubmit(application["id"], env["producer"]["id"],
             requested_effective_date="2026-09-20T00:00:00Z")
    return_for_cure(application["id"], "Vehicle class still wrong.")
    resubmit(application["id"], env["producer"]["id"],
             requested_effective_date="2026-09-25T00:00:00Z")

    spent = read_application(application["id"])
    assert spent["status"] == "SUBMITTED"
    assert spent["cure_count"] == 2
    return env, spent


def test_the_third_cure_return_is_refused_on_the_accumulated_count_alone():
    """Two rounds are spent, and the row is otherwise an ordinary SUBMITTED one.

    Each individual return was lawful; what refuses the third is the counter the
    resubmissions raised. The refusal changes nothing: the application stays in
    SUBMITTED at two rounds, its two declinations are still inside the ninety-day
    lookback, and the money it posted is exactly the requirement re-derived against
    the current clock.

    PRD: "The plan tolerates at most two cure round-trips, so a return is only
    admissible while `cure_count` is less than 2; a third attempt is refused with
    `ERR_CURE_LIMIT_EXCEEDED` and HTTP 409."
    Design: Corner/validations/the_cure_loop_allows_two_rounds_and_no_more
    """
    _, application = _application_with_both_cure_rounds_spent()

    response = api_client.return_application_for_cure(
        application["id"], create_cure_return_payload("Third look."),
        make_compliance_examiner_headers())

    validate_error(response, ApiErrorId.ERR_CURE_LIMIT_EXCEEDED, 409)
    unchanged = read_application(application["id"])
    assert unchanged["cure_count"] == 2
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["distinct_rejection_count"] == 2
    assert unchanged["required_deposit_cents"] == CLEAN_T02_REQUIRED_DEPOSIT_CENTS
    assert unchanged["deposit_paid_total_cents"] == CLEAN_T02_REQUIRED_DEPOSIT_CENTS


def test_the_last_resubmission_voided_the_record_so_certification_is_refused_too():
    """The cure loop cannot smuggle a stale driving record past certification.

    The second resubmission cleared the verified array and its timestamp, so the
    examiner faces an unverified record even though the application looks ready in
    every other respect. The certification is therefore refused on the record, not
    on the cure counter, and the quota period gains no assignable unit.

    PRD: "Both branches require the application to be in `SUBMITTED`, and both
    require `mvr_verified_at` to be non-null — the plan may not dispose of an
    unverified driving record in either direction, and an attempt is refused with
    `ERR_MVR_NOT_VERIFIED` and HTTP 422."
    Design: Corner/validations/the_cure_loop_allows_two_rounds_and_no_more
    """
    env, application = _application_with_both_cure_rounds_spent()
    assert application["mvr_verified_at"] is None
    assert application["verified_violations"] is None

    response = api_client.decide_certification(
        application["id"], create_certification_payload("CERTIFY"),
        make_compliance_examiner_headers())

    error = validate_error(response, ApiErrorId.ERR_MVR_NOT_VERIFIED, 422)
    assert error["error_id"] != ApiErrorId.ERR_CURE_LIMIT_EXCEEDED
    unchanged = read_application(application["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["certified_at"] is None
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 0


# ==========================================================================
# A complaint must name the policy's own servicing carrier
# ==========================================================================
def _two_policies_with_different_servicing_carriers():
    """Two certified risks placed in one run land on two different carriers."""
    env = bootstrap_plan()
    first = bring_application_to_certified(env, document_prefix="DEC-23-3a")
    second = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Nadia Frost", "driver_license_number": "D-99012"},
        vehicle_overrides={"vin": "1HGCM82633A004361"},
        document_prefix="DEC-23-3b")

    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    first_assignment = assignment_for_application(first["application"]["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    assert first_assignment["carrier_id"] != second_assignment["carrier_id"]
    accept_assignment(first_assignment["id"], first_assignment["carrier_id"])
    accept_assignment(second_assignment["id"], second_assignment["carrier_id"])

    set_clock(ISSUANCE_CLOCK)
    first_policy = issue_policy(first_assignment["id"], first_assignment["carrier_id"],
                               policy_number="AR-100014")
    second_policy = issue_policy(second_assignment["id"], second_assignment["carrier_id"],
                                policy_number="AR-100015")
    return {
        "policy": first_policy,
        "carrier_id": first_assignment["carrier_id"],
        "other_policy": second_policy,
        "other_carrier_id": second_assignment["carrier_id"],
    }


def test_a_complaint_aimed_at_another_policys_carrier_is_refused():
    """Both rows exist and the named carrier services a policy — just not this one.

    The first policy is serviced by the carrier the cycle designated for it, and a
    complaint already stands against that carrier. Naming the other carrier — a
    perfectly real, active carrier servicing the sibling policy — on the same
    policy is refused, and nothing is docketed: the policy still shows exactly the
    one open complaint it had.

    PRD: "The named `carrier_id` must equal the policy's current servicing carrier
    at the moment of filing, or the request is refused with
    `ERR_COMPLAINT_CARRIER_MISMATCH` and HTTP 422 — a complaint cannot be aimed at
    a carrier that has already handed the risk on."
    Design: Corner/validations/a_complaint_must_name_the_policys_own_servicing_carrier
    """
    world = _two_policies_with_different_servicing_carriers()
    docket_complaint(world["policy"]["id"], world["carrier_id"],
                     complaint_type="CLAIM_HANDLING_DELAY",
                     narrative="Acknowledgement and contact standards not met.")

    response = api_client.create_complaint(
        create_complaint_payload(world["policy"]["id"], world["other_carrier_id"],
                                 complaint_type="RATING_DISPUTE",
                                 narrative="Wrong carrier named on purpose."),
        ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_COMPLAINT_CARRIER_MISMATCH, 422)
    policy = read_policy(world["policy"]["id"])
    assert policy["open_complaint_count"] == 1
    assert policy["complaint_freeze_active"] is True
    _, meta = validate_paginated(api_client.list_complaints(
        ADMIN_HEADERS, params={"policy_id": world["policy"]["id"]}))
    assert meta["total_count"] == 1


def test_findings_can_be_recorded_once_per_round_and_the_second_attempt_is_refused():
    """The first pull moves the complaint off OPEN, so the second has no transition.

    Recording findings is the transition out of OPEN, and it stamps the
    investigating examiner. Presented a second time on the same round the complaint
    is already in FINDINGS_RECORDED, so the request is refused on the complaint's
    own state machine, the stored note and examiner are the ones from the first
    call, and the insured stays protected by the freeze.

    PRD: "the target row is in a state from which the requested transition exists
    (`ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`,
    `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_CLAIM_STATE`,
    `ERR_INVALID_COMPLAINT_STATE`, `ERR_INVALID_CYCLE_STATE`,
    `ERR_INVALID_PERIOD_STATE`), and the carrier the operation designates has
    `status` equal to `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`) — all with HTTP 409."
    Design: Corner/validations/a_complaint_must_name_the_policys_own_servicing_carrier
    """
    world = _two_policies_with_different_servicing_carriers()
    complaint = docket_complaint(world["policy"]["id"], world["carrier_id"],
                                complaint_type="CLAIM_HANDLING_DELAY",
                                narrative="Acknowledgement and contact standards not met.")
    assert complaint["status"] == "OPEN"
    assert complaint["review_round"] == 1

    validate_success(api_client.record_complaint_findings(
        complaint["id"], create_findings_payload("Carrier records confirm the delay."),
        make_compliance_examiner_headers(EXAMINER_ONE_USER_ID)))
    investigated = read_complaint(complaint["id"])
    assert investigated["status"] == "FINDINGS_RECORDED"
    assert investigated["findings_recorded_by_user_id"] == EXAMINER_ONE_USER_ID

    response = api_client.record_complaint_findings(
        complaint["id"], create_findings_payload("Second attempt at the same round."),
        make_compliance_examiner_headers(EXAMINER_ONE_USER_ID))

    validate_error(response, ApiErrorId.ERR_INVALID_COMPLAINT_STATE, 409)
    unchanged = read_complaint(complaint["id"])
    assert unchanged["status"] == "FINDINGS_RECORDED"
    assert unchanged["findings_note"] == "Carrier records confirm the delay."
    assert unchanged["review_round"] == 1
    assert read_policy(world["policy"]["id"])["complaint_freeze_active"] is True


# ==========================================================================
# An unresolved complaint freezes adverse action until it is disposed
# ==========================================================================
def _policy_frozen_by_a_complaint_under_investigation():
    """One complaint in FINDINGS_RECORDED, so the freeze is on and unresolved."""
    env = setup_policy_in_force(policy_number="AR-100014")
    complaint = docket_complaint(env["policy"]["id"], env["carrier"]["id"],
                                complaint_type="CLAIM_HANDLING_DELAY",
                                narrative="Acknowledgement and contact standards not met.")
    record_findings(complaint["id"], EXAMINER_ONE_USER_ID)
    assert read_complaint(complaint["id"])["status"] == "FINDINGS_RECORDED"
    frozen = read_policy(env["policy"]["id"])
    assert frozen["open_complaint_count"] == 1
    assert frozen["complaint_freeze_active"] is True
    env["complaint"] = complaint
    return env


def _attempt_non_renewal_notice(env, reason_note):
    return api_client.serve_non_renewal_notice(
        env["policy"]["id"], create_non_renewal_payload(reason_note),
        make_servicing_carrier_headers(env["carrier"]["id"]))


def test_the_freeze_refuses_the_non_renewal_notice_while_the_complaint_is_pending():
    """A complaint under investigation is still unresolved, so the notice is barred.

    The notice is timely, the carrier has served none this period and the policy is
    in force, so the only obstacle is the complaint sitting in FINDINGS_RECORDED.
    The refusal leaves the coverage axis untouched and the carrier's per-period
    non-renewal counter at zero.

    PRD: "The policy's `complaint_freeze_active` must be false, or the notice is
    refused with `ERR_COMPLAINT_FREEZE_ACTIVE`."
    Design: Corner/validations/an_unresolved_complaint_freezes_adverse_action_until_it_is_disposed
    """
    env = _policy_frozen_by_a_complaint_under_investigation()

    response = _attempt_non_renewal_notice(env, "Loss experience.")

    validate_error(response, ApiErrorId.ERR_COMPLAINT_FREEZE_ACTIVE, 409)
    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "IN_FORCE"
    assert policy["non_renewal_notice_count"] == 0
    assert policy["non_renewal_effective_date"] is None
    assert read_carrier(env["carrier"]["id"])["non_renewal_count_current_period"] == 0


def test_a_not_upheld_disposition_lifts_the_freeze_without_costing_the_carrier_a_point():
    """Disposal is what lifts the freeze, and this disposal costs nothing.

    The second examiner disposes of the complaint as not upheld: there is no
    deduction, no upheld count and no cascade, so the carrier still scores 100 and
    stays OPEN. The policy side moves anyway — the last unresolved complaint is
    gone, so the count falls to zero and the freeze flag follows it.

    PRD: "The carrier's `performance_score`, `upheld_complaint_count` and `posture`
    are entirely unaffected — there is no deduction and no cascade — but the policy
    side behaves identically to the upheld case: `open_complaint_count` falls by 1
    and `complaint_freeze_active` is re-derived, so the freeze lifts once no
    complaint of that policy remains unresolved."
    Design: Corner/validations/an_unresolved_complaint_freezes_adverse_action_until_it_is_disposed
    """
    env = _policy_frozen_by_a_complaint_under_investigation()

    resolve_complaint(env["complaint"]["id"], "NOT_UPHELD", EXAMINER_TWO_USER_ID)

    complaint = read_complaint(env["complaint"]["id"])
    assert complaint["status"] == "RESOLVED_NOT_UPHELD"
    assert complaint["resolved_by_user_id"] == EXAMINER_TWO_USER_ID
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["performance_score"] == 100
    assert carrier["upheld_complaint_count"] == 0
    assert carrier["posture"] == "OPEN"
    policy = read_policy(env["policy"]["id"])
    assert policy["open_complaint_count"] == 0
    assert policy["complaint_freeze_active"] is False
    assert policy["policy_status"] == "IN_FORCE"


def test_the_identical_notice_is_accepted_the_moment_the_complaint_is_disposed():
    """Nothing changes but the flag, and the same request flips from 409 to 200.

    The very notice the freeze refused is served again after the disposal and now
    succeeds: the coverage axis moves to NON_RENEWAL_PENDING, the per-term notice
    count is set to one, the maturation date is the policy's own expiration, and
    the carrier spends one of its three per-period non-renewals.

    PRD: "A served notice moves the policy `IN_FORCE → NON_RENEWAL_PENDING`, sets
    `non_renewal_notice_count` to 1, records `non_renewal_effective_date` as the
    policy's `expiration_date`, and raises the carrier's
    `non_renewal_count_current_period` by 1."
    Design: Corner/validations/an_unresolved_complaint_freezes_adverse_action_until_it_is_disposed
    """
    env = _policy_frozen_by_a_complaint_under_investigation()
    validate_error(_attempt_non_renewal_notice(env, "Loss experience."),
                   ApiErrorId.ERR_COMPLAINT_FREEZE_ACTIVE, 409)
    resolve_complaint(env["complaint"]["id"], "NOT_UPHELD", EXAMINER_TWO_USER_ID)
    assert read_policy(env["policy"]["id"])["complaint_freeze_active"] is False

    validate_success(_attempt_non_renewal_notice(env, "Loss experience."))

    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "NON_RENEWAL_PENDING"
    assert policy["non_renewal_notice_count"] == 1
    assert policy["non_renewal_effective_date"] == policy["expiration_date"]
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["non_renewal_count_current_period"] == 1
    assert carrier["upheld_complaint_count"] == 0


# ==========================================================================
# Forty-five days notice is measured inclusively from expiration
# ==========================================================================
def _unfrozen_policy_expiring_2027_09_15():
    env = setup_policy_in_force(policy_number="AR-100016")
    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "IN_FORCE"
    assert policy["complaint_freeze_active"] is False
    assert policy["non_renewal_notice_count"] == 0
    return env


def test_a_notice_served_exactly_forty_five_days_before_expiration_is_timely():
    """Expiration less 45 days is 2027-08-01, and the notice served that day stands.

    The window is measured at or before 45 days ahead of expiration, so the last
    admissible instant is itself admissible: served on 2027-08-01 against a term
    ending 2027-09-15, the notice is accepted and the policy moves onto the
    non-renewal track with its maturation date set to the expiration.

    PRD: "The clock must be at or before 45 days ahead of the policy's
    `expiration_date`, so that the insured has at least 45 days' warning; a later
    notice is refused with `ERR_NON_RENEWAL_NOTICE_TOO_LATE` and HTTP 422."
    Design: Corner/validations/forty_five_days_notice_is_measured_inclusively_from_expiration
    """
    env = _unfrozen_policy_expiring_2027_09_15()
    set_clock("2027-08-01T00:00:00Z")

    response = api_client.serve_non_renewal_notice(
        env["policy"]["id"], create_non_renewal_payload("Timely."),
        make_servicing_carrier_headers(env["carrier"]["id"]))

    validate_success(response)
    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "NON_RENEWAL_PENDING"
    assert policy["non_renewal_notice_count"] == 1
    assert policy["non_renewal_effective_date"] == policy["expiration_date"]
    assert read_carrier(env["carrier"]["id"])["non_renewal_count_current_period"] == 1


def test_a_notice_one_day_past_the_forty_five_day_mark_is_refused():
    """One day later the insured would get 44 days' warning, and that is too late.

    Everything except the clock is identical to the timely case: the same policy,
    the same carrier, no complaint and no notice yet served. Read at 2027-08-02 the
    warning period has shrunk below 45 days, so the notice is refused and the
    policy stays in force with its per-term and per-period counters at zero.

    PRD: "The clock must be at or before 45 days ahead of the policy's
    `expiration_date`, so that the insured has at least 45 days' warning; a later
    notice is refused with `ERR_NON_RENEWAL_NOTICE_TOO_LATE` and HTTP 422."
    Design: Corner/validations/forty_five_days_notice_is_measured_inclusively_from_expiration
    """
    env = _unfrozen_policy_expiring_2027_09_15()
    set_clock("2027-08-02T00:00:00Z")

    response = api_client.serve_non_renewal_notice(
        env["policy"]["id"], create_non_renewal_payload("One day late."),
        make_servicing_carrier_headers(env["carrier"]["id"]))

    validate_error(response, ApiErrorId.ERR_NON_RENEWAL_NOTICE_TOO_LATE, 422)
    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "IN_FORCE"
    assert policy["non_renewal_notice_count"] == 0
    assert policy["non_renewal_effective_date"] is None
    assert read_carrier(env["carrier"]["id"])["non_renewal_count_current_period"] == 0


# ==========================================================================
# The safety gate runs before the money gate
# ==========================================================================
def _documented_risk_with_no_record_and_no_money():
    """Two valid declinations, no motor-vehicle pull and not a cent posted."""
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    file_two_market_rejections(application["id"], env["producer"]["id"],
                               document_prefix="DEC-23-6")
    application = read_application(application["id"])
    assert application["distinct_rejection_count"] == 2
    assert application["mvr_verified_at"] is None
    assert application["deposit_paid_total_cents"] == 0
    assert application["required_deposit_cents"] == CLEAN_T02_REQUIRED_DEPOSIT_CENTS
    return env, application


def _attempt_certification(application_id):
    return api_client.decide_certification(
        application_id, create_certification_payload("CERTIFY"),
        make_compliance_examiner_headers())


def test_certification_reports_the_unverified_record_and_hides_the_missing_money():
    """Two independent blockers, and the category order decides which is named.

    Neither the record has been pulled nor a cent posted, so the priority-8 safety
    gate and the priority-12 fiscal gate are both broken. The plan names the safety
    failure and never mentions the deposit; only once the record is on file does the
    money become the reported problem, which proves the fiscal gate was there all
    along.

    PRD: "First, on an eligibility certification the documentation gates at
    priority 8 outrank the deposit gate at priority 12, so an applicant with an
    unverified motor-vehicle record or with too few documented declinations is
    refused before the plan looks at the money — the plan does not price an
    ineligible risk."
    Design: Corner/validations/the_safety_gate_runs_before_the_money_gate
    """
    env, application = _documented_risk_with_no_record_and_no_money()

    while_unverified = _attempt_certification(application["id"])

    error = validate_error(while_unverified, ApiErrorId.ERR_MVR_NOT_VERIFIED, 422)
    assert error["error_id"] != ApiErrorId.ERR_DEPOSIT_BELOW_REQUIRED

    verify_mvr(application["id"], [])
    once_verified = _attempt_certification(application["id"])
    validate_error(once_verified, ApiErrorId.ERR_DEPOSIT_BELOW_REQUIRED, 422)

    unchanged = read_application(application["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["certified_at"] is None
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 0


def test_a_zero_cent_deposit_is_refused_on_its_own_axis():
    """The shortfall cannot be papered over with an empty posting.

    A payment of nothing is not a payment: the plan refuses it as an invalid amount
    rather than accepting it and reporting a shortfall, and the ledger is untouched
    — the cumulative total and the uncredited balance both stay at zero.

    PRD: "A deposit of less than one cent is refused with
    `ERR_DEPOSIT_AMOUNT_INVALID` and HTTP 422."
    Design: Corner/validations/the_safety_gate_runs_before_the_money_gate
    """
    env, application = _documented_risk_with_no_record_and_no_money()

    response = api_client.record_deposit(
        application["id"], create_deposit_payload(0),
        make_producer_agent_headers(env["producer"]["id"]))

    validate_error(response, ApiErrorId.ERR_DEPOSIT_AMOUNT_INVALID, 422)
    unchanged = read_application(application["id"])
    assert unchanged["deposit_paid_total_cents"] == 0
    assert unchanged["deposit_balance_cents"] == 0
    assert unchanged["required_deposit_cents"] == CLEAN_T02_REQUIRED_DEPOSIT_CENTS


def test_the_deposit_comparison_is_inclusive_so_one_cent_short_fails_and_exact_passes():
    """38938 is refused and 38939 certifies — the boundary is tested from both sides.

    With the record verified the only remaining gate is the money. One cent below
    the requirement is a shortfall; posting that last cent brings the cumulative
    total to exactly the requirement, which the inclusive comparison accepts, and
    the certification then lands the risk in the assignment queue and raises the
    period's assignable total.

    PRD: "And `deposit_paid_total_cents` must be at least `required_deposit_cents`;
    the comparison is inclusive, so posting exactly the required amount passes, and
    posting less is refused with `ERR_DEPOSIT_BELOW_REQUIRED` and HTTP 422."
    Design: Corner/validations/the_safety_gate_runs_before_the_money_gate
    """
    env, application = _documented_risk_with_no_record_and_no_money()
    verify_mvr(application["id"], [])
    record_deposit(application["id"], env["producer"]["id"],
                   CLEAN_T02_REQUIRED_DEPOSIT_CENTS - 1)

    one_cent_short = _attempt_certification(application["id"])
    validate_error(one_cent_short, ApiErrorId.ERR_DEPOSIT_BELOW_REQUIRED, 422)
    assert read_application(application["id"])["status"] == "SUBMITTED"

    record_deposit(application["id"], env["producer"]["id"], 1)
    exactly_enough = _attempt_certification(application["id"])

    validate_success(exactly_enough)
    certified = read_application(application["id"])
    assert certified["status"] == "CERTIFIED_AWAITING_ASSIGNMENT"
    assert certified["certified_at"] is not None
    assert certified["deposit_paid_total_cents"] == CLEAN_T02_REQUIRED_DEPOSIT_CENTS
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 1


# ==========================================================================
# The auth tiers outrank scope which outranks state
# ==========================================================================
def _pending_assignment_past_its_acceptance_deadline():
    """A designated but unaccepted risk read at a clock past the ten-day window."""
    env = bootstrap_plan()
    risk = bring_application_to_certified(env, document_prefix="DEC-23-7")
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    assignment = assignment_for_application(risk["application"]["id"])
    assert assignment["status"] == "PENDING_ACCEPTANCE"
    stranger = [c for c in env["carriers"] if c["id"] != assignment["carrier_id"]][0]
    set_clock("2026-09-12T00:00:00Z")
    return {"assignment": assignment,
            "designated_carrier_id": assignment["carrier_id"],
            "stranger_carrier_id": stranger["id"]}


def test_the_ownership_scope_check_outranks_the_expired_acceptance_window():
    """A stranger's late acceptance is refused for being a stranger, not for being late.

    The acceptance deadline of 2026-09-11 has passed, so the priority-8 window gate
    is broken for anybody. When the carrier that is not the designated one calls,
    the priority-5 scope gate fails first and that is what the plan reports. The
    designated carrier's own late attempt then reports the window error, proving the
    deadline check was reachable all along and that neither call moved the row.

    PRD: "5. **Ownership scope** — `ERR_CARRIER_SCOPE_FORBIDDEN` or
    `ERR_PRODUCER_SCOPE_FORBIDDEN`, 403.
    6. **State admissibility** — the target row is in a state from which the
    requested transition exists (`ERR_INVALID_APPLICATION_STATE`,
    `ERR_INVALID_ASSIGNMENT_STATE`, `ERR_INVALID_POLICY_STATE`,
    `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_COMPLAINT_STATE`,
    `ERR_INVALID_CYCLE_STATE`, `ERR_INVALID_PERIOD_STATE`), and the carrier the
    operation designates has `status` equal to `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`)
    — all with HTTP 409.
    7. **Optimistic concurrency** — `ERR_STALE_CARRIER_VERSION` or
    `ERR_STALE_POLICY_VERSION`, 412.
    8. **Business safety** — the eligibility and standing gates:
    `ERR_MVR_NOT_VERIFIED`, `ERR_INSUFFICIENT_MARKET_REJECTIONS`,
    `ERR_CARRIER_SUSPENDED`, `ERR_ACCEPTANCE_WINDOW_EXPIRED`,
    `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/validations/the_auth_tiers_outrank_scope_which_outranks_state
    """
    world = _pending_assignment_past_its_acceptance_deadline()

    by_a_stranger = api_client.accept_assignment(
        world["assignment"]["id"],
        make_servicing_carrier_headers(world["stranger_carrier_id"]))

    error = validate_error(by_a_stranger, ApiErrorId.ERR_CARRIER_SCOPE_FORBIDDEN, 403)
    assert error["error_id"] != ApiErrorId.ERR_ACCEPTANCE_WINDOW_EXPIRED

    by_the_designated_carrier = api_client.accept_assignment(
        world["assignment"]["id"],
        make_servicing_carrier_headers(world["designated_carrier_id"]))
    validate_error(by_the_designated_carrier, ApiErrorId.ERR_ACCEPTANCE_WINDOW_EXPIRED, 409)

    assignment = read_assignment(world["assignment"]["id"])
    assert assignment["status"] == "PENDING_ACCEPTANCE"
    assert assignment["accepted_at"] is None
    assert read_carrier(world["designated_carrier_id"])["assigned_risk_count"] == 1
    assert read_carrier(world["stranger_carrier_id"])["assigned_risk_count"] == 0


def test_the_role_check_outranks_the_scope_check_on_the_administrators_rescission():
    """Rescission is administrator-exclusive, so the row is never even looked at.

    A carrier calling the rescission endpoint on an assignment it does not hold
    breaks two tiers at once: it is out of role at priority 2 and out of scope at
    priority 5. The plan reports the role failure, the lower number, and the
    assignment keeps its pending status with no rescission reason recorded.

    PRD: "2. **Authorisation** — the caller's role is listed for the endpoint:
    `ERR_UNAUTHORIZED`, 403.
    3. **Request shape** — required body fields present, enum values in range,
    integers non-negative where required, timestamps well-formed ISO 8601, `limit`
    within 1 through 100 and `offset` not negative: `ERR_INVALID_REQUEST`, 422.
    4. **Existence** — every identifier in the path and then every identifier in
    the body resolves, left to right: the matching not-found error, 404.
    5. **Ownership scope** — `ERR_CARRIER_SCOPE_FORBIDDEN` or
    `ERR_PRODUCER_SCOPE_FORBIDDEN`, 403."
    Design: Corner/validations/the_auth_tiers_outrank_scope_which_outranks_state
    """
    world = _pending_assignment_past_its_acceptance_deadline()

    response = api_client.rescind_assignment(
        world["assignment"]["id"], create_rescission_payload("CARRIER_INELIGIBLE"),
        make_servicing_carrier_headers(world["stranger_carrier_id"]))

    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert error["error_id"] != ApiErrorId.ERR_CARRIER_SCOPE_FORBIDDEN
    assignment = read_assignment(world["assignment"]["id"])
    assert assignment["status"] == "PENDING_ACCEPTANCE"
    assert assignment["rescission_reason_code"] is None
    assert read_carrier(world["designated_carrier_id"])["assigned_risk_count"] == 1


# ==========================================================================
# Closure checks the calendar before it counts the cycles
# ==========================================================================
def _open_period_with_one_unrun_cycle():
    """Period 2026-09-01..2026-11-30 read at its own start, with a live cycle."""
    env = bootstrap_plan()
    cycle = schedule_cycle(env["plan_period"]["id"],
                           window_start="2026-10-02T00:00:00Z",
                           window_end="2026-10-31T00:00:00Z")
    assert cycle["status"] == "SCHEDULED"
    assert read_plan_period(env["plan_period"]["id"])["status"] == "OPEN"
    env["cycle"] = cycle
    return env


def test_closure_reports_the_unelapsed_window_before_the_outstanding_cycle():
    """Both preconditions fail at once, and the temporal one is what the plan names.

    Read at 2026-09-01 the period's window has not elapsed and a cycle is still
    scheduled, so the priority-10 temporal rule and the priority-11 constraint are
    broken together. The plan reports the calendar. Advancing the clock to the
    window end removes the temporal failure and the cycle backlog becomes the
    reported problem, with the period still OPEN throughout.

    PRD: "10. **Business temporal** — window and date rules:
    `ERR_CANCEL_REASON_NOT_PERMITTED`, `ERR_CANCEL_DATE_OUT_OF_TERM`,
    `ERR_POLICY_TERM_OVERLAP`, `ERR_CYCLE_WINDOW_CONFLICT`,
    `ERR_CYCLE_WINDOW_OUTSIDE_PERIOD`, `ERR_PERIOD_WINDOW_CONFLICT`,
    `ERR_POLICY_TERM_INVALID`, `ERR_NON_RENEWAL_NOTICE_TOO_LATE`,
    `ERR_EXIT_NOTICE_TOO_SHORT`, `ERR_LOSS_DATE_OUTSIDE_TERM`,
    `ERR_WINDOW_NOT_REACHED`.
    11. **Business constraint** — plan limits and uniqueness:
    `ERR_CURE_LIMIT_EXCEEDED`, `ERR_REVIEW_ROUND_LIMIT`, `ERR_DUPLICATE_IDENTIFIER`,
    `ERR_NON_RENEWAL_QUOTA_EXCEEDED`, `ERR_CARRIER_NOT_LICENSED_IN_TERRITORY`,
    `ERR_CLEAN_YEARS_INSUFFICIENT`, `ERR_PAYMENT_EXCEEDS_RESERVE`,
    `ERR_PERIOD_NOT_RECONCILING`, `ERR_CYCLE_STILL_SCHEDULED`."
    Design: Corner/validations/closure_checks_the_calendar_before_it_counts_the_cycles
    """
    env = _open_period_with_one_unrun_cycle()

    too_early = api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS)

    error = validate_error(too_early, ApiErrorId.ERR_WINDOW_NOT_REACHED, 409)
    assert error["error_id"] != ApiErrorId.ERR_CYCLE_STILL_SCHEDULED
    assert read_plan_period(env["plan_period"]["id"])["status"] == "OPEN"

    set_clock("2026-11-30T00:00:00Z")
    with_a_live_cycle = api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS)

    validate_error(with_a_live_cycle, ApiErrorId.ERR_CYCLE_STILL_SCHEDULED, 409)
    assert read_plan_period(env["plan_period"]["id"])["status"] == "OPEN"
    assert read_assignment_cycle(env["cycle"]["id"])["status"] == "SCHEDULED"


def test_running_the_empty_cycle_clears_the_way_and_closure_turns_the_page():
    """An empty queue is not an error, and the closure then recovers no lost points.

    The cycle runs against a queue with nothing in it: it completes with both
    counters at zero rather than failing. With no cycle outstanding and the clock at
    the window end, the closure moves the period into reconciliation and turns the
    page for both active carriers — their per-period counters reset and their
    recovery of 10 is capped at the ceiling, so a perfect score stays 100.

    PRD: "It also turns the page for every carrier whose `status` is `ACTIVE`:
    `breach_count_current_period` is reset to 0, `non_renewal_count_current_period`
    is reset to 0, `performance_score` is raised by 10 but never above 100, and
    `posture` is recomputed — which is how a carrier restricted by breaches or by a
    mediocre score can earn its way back to `OPEN`."
    Design: Corner/validations/closure_checks_the_calendar_before_it_counts_the_cycles
    """
    env = _open_period_with_one_unrun_cycle()
    set_clock("2026-11-30T00:00:00Z")

    run_cycle(env["cycle"]["id"])
    completed = read_assignment_cycle(env["cycle"]["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["assigned_count"] == 0
    assert completed["deferred_count"] == 0

    validate_success(api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))

    period = read_plan_period(env["plan_period"]["id"])
    assert period["status"] == "RECONCILING"
    assert period["total_assignable_units"] == 0
    for enrolled in env["carriers"]:
        carrier = read_carrier(enrolled["id"])
        assert carrier["performance_score"] == 100
        assert carrier["breach_count_current_period"] == 0
        assert carrier["non_renewal_count_current_period"] == 0
        assert carrier["posture"] == "OPEN"


def test_a_second_closure_of_a_reconciling_period_is_a_state_refusal():
    """Closure happens once; the repeat is refused on the period's own state.

    Once the period has moved into reconciliation the transition the closure asks
    for no longer exists, so the second call is refused on state admissibility
    rather than on the calendar or on the cycle inventory, and the period stays in
    reconciliation with its frozen totals.

    PRD: "the target row is in a state from which the requested transition exists
    (`ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`,
    `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_CLAIM_STATE`,
    `ERR_INVALID_COMPLAINT_STATE`, `ERR_INVALID_CYCLE_STATE`,
    `ERR_INVALID_PERIOD_STATE`), and the carrier the operation designates has
    `status` equal to `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`) — all with HTTP 409."
    Design: Corner/validations/closure_checks_the_calendar_before_it_counts_the_cycles
    """
    env = _open_period_with_one_unrun_cycle()
    set_clock("2026-11-30T00:00:00Z")
    run_cycle(env["cycle"]["id"])
    validate_success(api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))
    assert read_plan_period(env["plan_period"]["id"])["status"] == "RECONCILING"

    response = api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS)

    error = validate_error(response, ApiErrorId.ERR_INVALID_PERIOD_STATE, 409)
    assert error["error_id"] != ApiErrorId.ERR_WINDOW_NOT_REACHED
    period = read_plan_period(env["plan_period"]["id"])
    assert period["status"] == "RECONCILING"
    assert period["total_assignable_units"] == 0


# ==========================================================================
# A paid closure may not exceed the reserve it declared
# ==========================================================================
def _acknowledged_claim_reserved_at_ninety_thousand():
    """A not-at-fault uninsured-motorist loss, acknowledged inside the standard."""
    env = setup_policy_in_force(policy_number="AR-100014")
    set_clock("2026-09-20T00:00:00Z")
    claim = report_claim(env["policy"]["id"], env["carrier"]["id"],
                         loss_date="2026-09-18T00:00:00Z", at_fault=False,
                         coverage_line="UM", reserve_cents=90000)
    acknowledge_claim(claim["id"], env["carrier"]["id"])
    acknowledged = read_claim(claim["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["standard_breach"] is False
    assert acknowledged["reserve_cents"] == 90000
    env["claim"] = acknowledged
    return env


def _close_claim_as_paid(env, paid_cents):
    return api_client.close_claim(
        env["claim"]["id"], create_claim_closure_payload("PAID", paid_cents=paid_cents),
        make_servicing_carrier_headers(env["carrier"]["id"]))


def test_a_payment_one_cent_above_the_declared_reserve_is_refused():
    """The reserve the carrier declared at intake is a hard ceiling.

    The claim is acknowledged and ready to close, and 90001 cents exceeds the 90000
    the carrier itself reserved. The closure is refused, the claim stays in
    ACKNOWLEDGED with nothing paid, and the reserve is untouched.

    PRD: "A `PAID` closure moves the claim `ACKNOWLEDGED → CLOSED_PAID` and records
    the supplied `paid_cents` as the indemnity paid; `paid_cents` may not exceed the
    claim's `reserve_cents`, and an overpayment is refused with
    `ERR_PAYMENT_EXCEEDS_RESERVE` and HTTP 422."
    Design: Corner/validations/a_paid_closure_may_not_exceed_the_reserve_it_declared
    """
    env = _acknowledged_claim_reserved_at_ninety_thousand()

    response = _close_claim_as_paid(env, 90001)

    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_RESERVE, 422)
    unchanged = read_claim(env["claim"]["id"])
    assert unchanged["status"] == "ACKNOWLEDGED"
    assert unchanged["paid_cents"] == 0
    assert unchanged["reserve_cents"] == 90000


def test_a_payment_of_exactly_the_reserve_closes_the_claim_as_paid():
    """The comparison is an at-most, so paying the reserve to the cent is lawful.

    The same closure that was refused one cent higher succeeds at exactly 90000:
    the claim moves to CLOSED_PAID with the whole reserve recorded as indemnity.
    The acknowledgement was inside the ten-day standard, so no breach is flagged and
    the carrier's score and posture are exactly where they started.

    PRD: "A `PAID` closure moves the claim `ACKNOWLEDGED → CLOSED_PAID` and records
    the supplied `paid_cents` as the indemnity paid; `paid_cents` may not exceed the
    claim's `reserve_cents`, and an overpayment is refused with
    `ERR_PAYMENT_EXCEEDS_RESERVE` and HTTP 422."
    Design: Corner/validations/a_paid_closure_may_not_exceed_the_reserve_it_declared
    """
    env = _acknowledged_claim_reserved_at_ninety_thousand()
    validate_error(_close_claim_as_paid(env, 90001),
                   ApiErrorId.ERR_PAYMENT_EXCEEDS_RESERVE, 422)

    validate_success(_close_claim_as_paid(env, 90000))

    closed = read_claim(env["claim"]["id"])
    assert closed["status"] == "CLOSED_PAID"
    assert closed["paid_cents"] == 90000
    assert closed["standard_breach"] is False
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["performance_score"] == 100
    assert carrier["posture"] == "OPEN"


def test_a_paid_but_not_at_fault_closure_leaves_the_clean_years_clock_alone():
    """Only an at-fault loss is a chargeable event, however much was paid.

    The closure pays the full reserve, but the loss was not the insured's fault, so
    it never enters the chargeable-event set. The applicant keeps the five clean
    years it held before the loss was even reported, and the policy it sits on is
    still in force on both axes.

    PRD: "The plan gathers two kinds of chargeable event: the `conviction_date` of
    every *verified* violation on any of the applicant's applications, and the
    `loss_date` of every claim of the applicant whose `at_fault` flag is true."
    Design: Corner/validations/a_paid_closure_may_not_exceed_the_reserve_it_declared
    """
    env = _acknowledged_claim_reserved_at_ninety_thousand()
    assert read_applicant(env["applicant"]["id"])["clean_years_credited"] == 5

    validate_success(_close_claim_as_paid(env, 90000))

    assert read_claim(env["claim"]["id"])["at_fault"] is False
    applicant = read_applicant(env["applicant"]["id"])
    assert applicant["clean_years_credited"] == 5
    assert applicant["voluntary_market_eligible"] is False
    assert read_policy(env["policy"]["id"])["policy_status"] == "IN_FORCE"
