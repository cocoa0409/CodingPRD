"""Splitting the bill: routing, the insurance waterfall, settlement and void."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_payload,
    api_client,
    assert_service_line,
    get_encounter,
    get_membership,
    get_policy,
    get_service_line,
    make_billing_headers,
    open_encounter,
    policy_version,
    service_lines_for_encounter,
    setup_insured_active_membership,
    setup_routed_insurance_line,
    submit_billing,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


# ==========================================================================
# The two routes diverge on identical clinical work
# ==========================================================================


def test_insurance_routed_sick_visit_runs_the_deductible_waterfall(api):
    """PRD §3.7: "On the first call the policy has met nothing, so the whole 14 000 is
    applied to the deductible, nothing survives it, the coinsurance and plan-paid figures
    are both 0, the household owes 14 000, and `deductible_met_cents` rises to 14 000."
    PRD §3.7: "The `write_off_cents` is the `billed_amount_cents` minus the
    `allowed_amount_cents`, is booked to the practice, and is never collectable from the
    household."
    PRD §3.7: "On success the line moves `ROUTED → ADJUDICATED` and records the acting
    caller in `adjudicated_by_user_id`."

    Design: Difficulty/dual_variant_calc/service_line_split_insurance_route_vs_membership_route
    """
    scenario = setup_routed_insurance_line(
        submitter_user_id="bs-001",
        started_at="2026-06-15T14:00:00Z",
        complete_clinical_first=True,
        household_name="Nguyen",
        licensed_state_codes=["CA", "NV"],
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )
    line, policy = scenario["service_line"], scenario["policy"]

    adjudicated = validate_success(
        api.adjudicate_service_line(
            line["id"],
            adjudicate_payload(14000, policy_version(policy["id"])),
            make_billing_headers("bs-002"),
        )
    )
    assert_service_line(adjudicated)

    assert adjudicated["route"] == "BILLED_TO_INSURANCE"
    assert adjudicated["service_code"] == "SICK_VISIT"
    assert adjudicated["billed_amount_cents"] == 18000
    assert adjudicated["allowed_amount_cents"] == 14000
    assert adjudicated["write_off_cents"] == 4000
    assert adjudicated["deductible_applied_cents"] == 14000
    assert adjudicated["coinsurance_cents"] == 0
    assert adjudicated["plan_paid_cents"] == 0
    assert adjudicated["patient_responsibility_cents"] == 14000
    assert adjudicated["membership_covered_cents"] == 0
    assert adjudicated["status"] == "ADJUDICATED"

    refreshed_policy = get_policy(policy["id"])
    assert refreshed_policy["deductible_met_cents"] == 14000
    assert refreshed_policy["version"] == 2


def test_membership_routed_well_visit_line_never_reads_the_policy(api):
    """PRD §3.7: "On the membership route the `allowed_amount_cents` equals the
    `billed_amount_cents`, `write_off_cents` is 0, `deductible_applied_cents`,
    `coinsurance_cents` and `plan_paid_cents` are all 0, `patient_responsibility_cents` is
    0, and the entire billed amount lands in `membership_covered_cents`. No policy is read
    and `deductible_met_cents` is not touched."
    PRD §3.6: "a `NEWBORN_WEIGHT_CHECK` maps to `WELL_VISIT`"
    PRD §3.7: "Lines routed `COVERED_BY_MEMBERSHIP` or `PATIENT_RESPONSIBILITY` are
    created directly in status `SETTLED`, with no adjudication step and no cash movement
    required."

    Design: Difficulty/dual_variant_calc/service_line_split_insurance_route_vs_membership_route
    """
    scenario = setup_insured_active_membership(
        clock="2026-06-01T00:00:00Z",
        advance_clock_to="2026-06-15T20:00:00Z",
        household_name="Nguyen",
        licensed_state_codes=["CA", "NV"],
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )

    encounter = open_encounter(
        scenario["membership"]["id"],
        "2026-06-15T16:00:00Z",
        encounter_type="NEWBORN_WEIGHT_CHECK",
    )
    submit_billing(encounter["id"], "bs-001")

    lines = service_lines_for_encounter(encounter["id"])
    assert len(lines) == 1
    line = lines[0]
    assert_service_line(line)

    assert line["route"] == "COVERED_BY_MEMBERSHIP"
    assert line["service_code"] == "WELL_VISIT"
    assert line["billed_amount_cents"] == 22000
    assert line["patient_responsibility_cents"] == 0
    assert line["membership_covered_cents"] == 22000
    assert line["deductible_applied_cents"] == 0
    assert line["policy_id"] is None
    assert line["status"] == "SETTLED"

    assert get_policy(scenario["policy"]["id"])["deductible_met_cents"] == 0


# ==========================================================================
# The rounding boundary in the insurance split
# ==========================================================================


def _half_cent_scenario():
    return setup_routed_insurance_line(
        submitter_user_id="bs-011",
        started_at="2026-06-15T10:00:00Z",
        household_name="Brandt",
        carrier_name="Cedar Mutual",
        deductible_cents=9770,
        coinsurance_rate=0.15,
    )


def test_coinsurance_half_cent_rounds_half_up(api):
    """PRD §3.7: "For the rounding boundary, take a `deductible_cents` of 9 770 and a
    `coinsurance_rate` of 0.15 against the same 18 000 billed and 14 000 allowed: 9 770 is
    applied to the deductible, 4 230 survives, the coinsurance product is 634.5 which
    rounds half-up to 635, the plan pays 3 595, the household owes 10 405 and the practice
    writes off 4 000."
    PRD §2.9: "In the insurance split, the round-half-up is applied exactly once, to the
    coinsurance product, and never to the intermediate deductible or plan-paid figures,
    which are exact integer subtractions."

    Design: Difficulty/combinatorial_formula/insurance_split_nested_min_max_with_half_cent_coinsurance
    """
    scenario = _half_cent_scenario()
    line, policy = scenario["service_line"], scenario["policy"]

    adjudicated = validate_success(
        api.adjudicate_service_line(
            line["id"],
            adjudicate_payload(14000, policy_version(policy["id"])),
            make_billing_headers("bs-012"),
        )
    )

    assert adjudicated["allowed_amount_cents"] == 14000
    assert adjudicated["write_off_cents"] == 4000
    assert adjudicated["deductible_applied_cents"] == 9770
    assert adjudicated["coinsurance_cents"] == 635
    assert adjudicated["coinsurance_cents"] != 634, "634.5 rounds away from zero"
    assert adjudicated["plan_paid_cents"] == 3595
    assert adjudicated["patient_responsibility_cents"] == 10405
    assert adjudicated["membership_covered_cents"] == 0


def test_adjudication_records_the_actor_and_leaves_the_encounter_routed(api):
    """PRD §3.7: "On success the line moves `ROUTED → ADJUDICATED` and records the acting
    caller in `adjudicated_by_user_id`."
    PRD §3.7: "Finally the policy's `deductible_met_cents` increases by the applied
    deductible and the policy's `version` increments by 1."
    PRD §3.6: "And it fires inside line settlement when the last insurance-routed line
    settles, which is why an insurance-routed encounter stops at `BILLING_ROUTED` and
    waits."

    Design: Difficulty/combinatorial_formula/insurance_split_nested_min_max_with_half_cent_coinsurance
    """
    scenario = _half_cent_scenario()
    line, policy, encounter = scenario["service_line"], scenario["policy"], scenario["encounter"]

    adjudicated = validate_success(
        api.adjudicate_service_line(
            line["id"],
            adjudicate_payload(14000, policy_version(policy["id"])),
            make_billing_headers("bs-012"),
        )
    )

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["adjudicated_by_user_id"] == "bs-012"
    assert get_policy(policy["id"])["deductible_met_cents"] == 9770
    assert get_encounter(encounter["id"])["billing_status"] == "BILLING_ROUTED"


# ==========================================================================
# Cross-entity gate: the policy must still be ACTIVE
# ==========================================================================


def _terminated_policy_scenario():
    scenario = setup_routed_insurance_line(
        submitter_user_id="bs-031",
        started_at="2026-06-15T10:00:00Z",
        household_name="Silva",
        carrier_name="Northwind",
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )
    validate_success(
        api_client.terminate_insurance_policy(scenario["policy"]["id"], BILLING)
    )
    return scenario


def test_adjudicating_against_a_terminated_policy_is_refused(api):
    """PRD §3.7: "The policy the line names must currently be `ACTIVE`, failing which the
    response is `ERR_POLICY_INACTIVE` — this is how a terminated policy freezes its
    outstanding lines."
    PRD §3.1: "Terminating a policy moves it `ACTIVE → TERMINATED`, increments the
    policy's `version` by 1, and is permitted exactly once"

    Design: Difficulty/cross_entity_state_dependency/adjudication_gated_on_insurance_policy_still_active
    """
    scenario = _terminated_policy_scenario()
    line, policy = scenario["service_line"], scenario["policy"]

    resp = api.adjudicate_service_line(
        line["id"],
        adjudicate_payload(14000, policy_version(policy["id"])),
        make_billing_headers("bs-032"),
    )
    validate_error(resp, ApiErrorId.ERR_POLICY_INACTIVE)
    assert resp.status_code == 409

    frozen = get_policy(policy["id"])
    assert frozen["status"] == "TERMINATED"
    assert frozen["deductible_met_cents"] == 0


def test_a_terminated_policy_leaves_its_routed_line_frozen_but_intact(api):
    """PRD §3.1: "Termination is deliberately *not* retroactive: service lines already
    routed to that policy keep their `policy_id` and their current status, but they can no
    longer be adjudicated, and `deductible_met_cents` is left exactly where it stood
    rather than being reset."
    PRD §3.7: "On that insurance route the line's `allowed_amount_cents` is null until
    adjudication supplies it, while on the other two routes it equals the
    `billed_amount_cents` from the moment the line exists."

    Design: Difficulty/cross_entity_state_dependency/adjudication_gated_on_insurance_policy_still_active
    """
    scenario = _terminated_policy_scenario()
    line, policy, encounter = scenario["service_line"], scenario["policy"], scenario["encounter"]

    validate_error(
        api.adjudicate_service_line(
            line["id"],
            adjudicate_payload(14000, policy_version(policy["id"])),
            make_billing_headers("bs-032"),
        ),
        ApiErrorId.ERR_POLICY_INACTIVE,
    )

    frozen_line = get_service_line(line["id"])
    assert frozen_line["status"] == "ROUTED"
    assert frozen_line["route"] == "BILLED_TO_INSURANCE"
    assert frozen_line["policy_id"] == policy["id"]
    assert frozen_line["allowed_amount_cents"] is None
    assert frozen_line["patient_responsibility_cents"] == 0

    assert get_encounter(encounter["id"])["billing_status"] == "BILLING_ROUTED"


# ==========================================================================
# Deductible conservation
# ==========================================================================


def _adjudicated_then_cancelled_scenario():
    scenario = setup_routed_insurance_line(
        submitter_user_id="bs-041",
        started_at="2026-06-15T10:00:00Z",
        complete_clinical_first=True,
        household_name="Yildiz",
        carrier_name="Harbor Health",
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )
    validate_success(
        api_client.adjudicate_service_line(
            scenario["service_line"]["id"],
            adjudicate_payload(14000, policy_version(scenario["policy"]["id"])),
            make_billing_headers("bs-042"),
        )
    )
    return scenario


def test_voiding_an_adjudicated_line_gives_the_deductible_back(api):
    """PRD §2.10: "Adjudicating a line adds that line's `deductible_applied_cents` to the
    policy's running total; voiding an already-adjudicated line — which happens when its
    parent encounter is cancelled — subtracts exactly the same amount back out."
    PRD §3.6: "And for each voided line that was routed `BILLED_TO_INSURANCE` and had
    reached `ADJUDICATED`, the policy's `deductible_met_cents` is decreased by exactly that
    line's `deductible_applied_cents` and the policy's `version` is incremented by 1 — the
    compensating action that keeps the deductible identity of §2.10 true."

    Design: Difficulty/compensating_invariant/deductible_met_restored_when_adjudicated_line_is_voided
    """
    scenario = _adjudicated_then_cancelled_scenario()
    line, policy, encounter = scenario["service_line"], scenario["policy"], scenario["encounter"]

    before = get_policy(policy["id"])
    assert before["deductible_met_cents"] == 14000
    assert before["version"] == 2

    line_before = get_service_line(line["id"])
    assert line_before["status"] == "ADJUDICATED"
    assert line_before["deductible_applied_cents"] == 14000
    assert line_before["patient_responsibility_cents"] == 14000

    validate_success(
        api.cancel_encounter(
            encounter["id"], {"reason": "Charge posted to the wrong child"}, ADMIN
        )
    )

    assert get_service_line(line["id"])["status"] == "VOID"

    after = get_policy(policy["id"])
    assert after["deductible_met_cents"] == 0, "exactly its value before adjudication"
    assert after["version"] == 3


def test_cancelling_an_encounter_collapses_both_axes_without_touching_the_membership(api):
    """PRD §3.6: "The clinical axis moves to `CANCELLED` from either `SCHEDULED` or
    `CLINICALLY_COMPLETE` — both paths are permitted and both produce identical
    consequences — and the billing axis moves to `BILLING_VOID` from either
    `BILLING_PENDING` or `BILLING_ROUTED`."
    PRD §3.6: "**Cancelling an encounter collapses both axes at once.** A
    `CareCoordinator`, `PracticeAdmin` or `Physician` supplies a `reason`, which is stored
    in `cancel_reason`."

    Design: Difficulty/compensating_invariant/deductible_met_restored_when_adjudicated_line_is_voided
    """
    scenario = _adjudicated_then_cancelled_scenario()
    encounter, membership = scenario["encounter"], scenario["membership"]

    cancelled = validate_success(
        api.cancel_encounter(
            encounter["id"], {"reason": "Charge posted to the wrong child"}, ADMIN
        )
    )

    assert cancelled["clinical_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "BILLING_VOID"
    assert cancelled["cancel_reason"] == "Charge posted to the wrong child"

    assert get_membership(membership["id"])["status"] == "ACTIVE", (
        "voiding a charge does not disturb the membership"
    )


# ==========================================================================
# Adjudication fences
# ==========================================================================


def test_adjudicating_your_own_submission_is_refused(api):
    """PRD §3.7: "The acting `X-User-ID` must differ from the line's
    `submitted_by_user_id`, and the same operator submitting and adjudicating their own
    charge is refused with `ERR_SEGREGATION_OF_DUTIES` — this rule binds `PracticeAdmin`
    exactly as tightly as it binds `BillingSpecialist`."
    PRD §3.6: "The submission stamps the acting `X-User-ID` onto every line it creates as
    `submitted_by_user_id`, which is the value the segregation-of-duties rule of §3.7 will
    later compare against."

    Design: Corner/validations/corner_adjudicating_your_own_submission_returns_segregation_of_duties
    """
    scenario = setup_routed_insurance_line(
        submitter_user_id="bs-071",
        started_at="2026-06-15T10:00:00Z",
        household_name="Everly",
        carrier_name="Summit",
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )
    line, policy = scenario["service_line"], scenario["policy"]
    version_before = policy_version(policy["id"])

    resp = api.adjudicate_service_line(
        line["id"],
        adjudicate_payload(14000, version_before),
        make_billing_headers("bs-071"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert resp.status_code == 403

    unchanged = get_service_line(line["id"])
    assert unchanged["submitted_by_user_id"] == "bs-071"
    assert unchanged["adjudicated_by_user_id"] is None
    assert unchanged["status"] == "ROUTED"

    policy_after = get_policy(policy["id"])
    assert policy_after["deductible_met_cents"] == 0
    assert policy_after["version"] == version_before


def test_a_membership_routed_line_can_never_be_adjudicated(api):
    """PRD §2.7: "**Route eligibility.** On service-line adjudication, the line's `route`
    must be `BILLED_TO_INSURANCE`; a line routed `COVERED_BY_MEMBERSHIP` or
    `PATIENT_RESPONSIBILITY` can never be adjudicated and is refused with
    `ERR_ROUTE_NOT_ADJUDICABLE` (422)."
    PRD §3.7: "The line must currently be in status `ROUTED`, failing which the response
    is `ERR_INVALID_STATE`."

    Design: Corner/validations/corner_adjudicating_a_membership_routed_line_returns_route_not_adjudicable
    """
    scenario = setup_insured_active_membership(
        clock="2026-06-01T00:00:00Z",
        advance_clock_to="2026-06-15T20:00:00Z",
        household_name="Fairbanks",
        carrier_name="Meridian",
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )

    encounter = open_encounter(
        scenario["membership"]["id"], "2026-06-15T10:00:00Z", encounter_type="ROUTINE_QUESTION"
    )
    submit_billing(encounter["id"], "bs-081")

    line = service_lines_for_encounter(encounter["id"])[0]
    assert line["route"] == "COVERED_BY_MEMBERSHIP"
    assert line["policy_id"] is None
    assert line["status"] == "SETTLED"

    resp = api.adjudicate_service_line(
        line["id"],
        adjudicate_payload(5000, policy_version(scenario["policy"]["id"])),
        make_billing_headers("bs-082"),
    )
    validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_ROUTE_NOT_ADJUDICABLE.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ],
    )

    unchanged = get_service_line(line["id"])
    assert unchanged["membership_covered_cents"] == 12000
    assert unchanged["patient_responsibility_cents"] == 0
    assert unchanged["status"] == "SETTLED"


def test_an_override_above_the_computed_share_is_blocked(api):
    """PRD §3.7: "The adjudication call accepts an optional
    `patient_responsibility_override_cents` as a declared collection figure, and it is
    checked against a hard ceiling: it must be less than or equal to the sum of the
    `deductible_applied_cents` and `coinsurance_cents` the waterfall derived from the
    supplied `allowed_amount_cents`. Anything larger is an attempt to pass the write-off
    to the household and is refused with `ERR_BALANCE_BILLING_BLOCKED`."

    Design: Corner/validations/corner_balance_billing_override_above_computed_share_is_blocked
    """
    scenario = setup_routed_insurance_line(
        submitter_user_id="bs-091",
        started_at="2026-06-15T10:00:00Z",
        household_name="Gallo",
        carrier_name="Anchor",
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )
    line, policy = scenario["service_line"], scenario["policy"]

    resp = api.adjudicate_service_line(
        line["id"],
        adjudicate_payload(
            14000, policy_version(policy["id"]), patient_responsibility_override_cents=15000
        ),
        make_billing_headers("bs-092"),
    )
    validate_error(resp, ApiErrorId.ERR_BALANCE_BILLING_BLOCKED)
    assert resp.status_code == 422

    unchanged = get_service_line(line["id"])
    assert unchanged["status"] == "ROUTED"
    assert unchanged["allowed_amount_cents"] is None
    assert get_policy(policy["id"])["deductible_met_cents"] == 0


def test_settling_the_last_line_bubbles_the_encounter_billing_axis_closed(api):
    """PRD §3.7: "A `BillingSpecialist` or `PracticeAdmin` supplies a
    `payment_received_cents` that must equal the line's `patient_responsibility_cents`
    exactly; any other figure is `ERR_VALIDATION`. The line moves `ADJUDICATED → SETTLED`
    and records the cash in `payment_received_cents`."
    PRD §3.6: "At the end of any request that leaves every service line of the encounter
    in a terminal status, and provided the encounter has at least one line and every one
    of them reads `SETTLED` or `VOID`, the encounter advances
    `BILLING_ROUTED → BILLING_CLOSED`."

    Design: Corner/state_machines/corner_settle_last_line_bubbles_encounter_billing_to_closed
    """
    scenario = setup_routed_insurance_line(
        submitter_user_id="bs-051",
        started_at="2026-06-15T10:00:00Z",
        household_name="Sokolov",
        carrier_name="Ridgeline",
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )
    line, policy, encounter = scenario["service_line"], scenario["policy"], scenario["encounter"]

    assert get_encounter(encounter["id"])["billing_status"] == "BILLING_ROUTED"

    validate_success(
        api.adjudicate_service_line(
            line["id"],
            adjudicate_payload(14000, policy_version(policy["id"])),
            make_billing_headers("bs-052"),
        )
    )
    assert get_encounter(encounter["id"])["billing_status"] == "BILLING_ROUTED"

    settled = validate_success(
        api.settle_service_line(
            line["id"], {"payment_received_cents": 14000}, make_billing_headers("bs-052")
        )
    )
    assert settled["status"] == "SETTLED"
    assert settled["payment_received_cents"] == 14000

    closed = get_encounter(encounter["id"])
    assert closed["billing_status"] == "BILLING_CLOSED"
    assert closed["clinical_status"] == "SCHEDULED", "the clinical axis never moved"

    assert get_policy(policy["id"])["deductible_met_cents"] == 14000


def test_adjudicating_with_a_stale_policy_token_is_rejected(api):
    """PRD §2.8: "A `POST /peds/service-lines/{service_line_id}/adjudicate` request must
    carry `expected_policy_version` holding the client's last observed `version` of the
    InsurancePolicy the line names. A mismatch with the policy's current `version` is
    rejected with `ERR_STALE_VERSION` (412)."
    PRD §2.10: "For every insurance policy, `deductible_met_cents` always equals the sum
    of `deductible_applied_cents` across that policy's service lines currently in
    `ADJUDICATED` or `SETTLED`."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_expected_policy_version_on_adjudicate
    """
    scenario = setup_routed_insurance_line(
        submitter_user_id="bs-111",
        started_at="2026-06-15T10:00:00Z",
        complete_clinical_first=True,
        advance_clock_to="2026-06-15T23:00:00Z",
        household_name="Eriksen",
        carrier_name="Foreland",
        deductible_cents=50000,
        coinsurance_rate=0.20,
    )
    policy = scenario["policy"]
    line_one = scenario["service_line"]
    token_v0 = policy_version(policy["id"])

    second_encounter = open_encounter(scenario["membership"]["id"], "2026-06-15T12:00:00Z")
    submit_billing(second_encounter["id"], "bs-111")
    line_two = service_lines_for_encounter(second_encounter["id"])[0]

    first = validate_success(
        api.adjudicate_service_line(
            line_one["id"], adjudicate_payload(14000, token_v0), make_billing_headers("bs-112")
        )
    )
    assert first["deductible_applied_cents"] == 14000
    assert first["patient_responsibility_cents"] == 14000

    stale = api.adjudicate_service_line(
        line_two["id"], adjudicate_payload(14000, token_v0), make_billing_headers("bs-112")
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    assert get_policy(policy["id"])["deductible_met_cents"] == 14000
    assert get_service_line(line_two["id"])["status"] == "ROUTED"

    token_v1 = policy_version(policy["id"])
    retry = validate_success(
        api.adjudicate_service_line(
            line_two["id"], adjudicate_payload(14000, token_v1), make_billing_headers("bs-112")
        )
    )
    assert retry["deductible_applied_cents"] == 14000
    assert get_policy(policy["id"])["deductible_met_cents"] == 28000
