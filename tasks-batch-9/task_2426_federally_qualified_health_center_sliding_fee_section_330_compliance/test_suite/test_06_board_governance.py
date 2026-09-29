"""The patient-majority verdict, the industry seat cap, and closed-interval seat terms."""

import pytest

from test_helpers import (
    ApiErrorId,
    OFFICER,
    adopt_schedule,
    api_client,
    create_board_member_payload,
    create_patient_seat_payload,
    refresh_health_center,
    resign_board_member_payload,
    same_instant,
    seed_poverty_guidelines,
    setup_baseline_service,
    setup_baseline_site,
    setup_board_seat,
    setup_boot_fs,
    setup_draft_fee_schedule,
    setup_encounter,
    setup_grantee,
    setup_patient,
    setup_verified_patient,
    validate_error,
    validate_success,
)


def _governance_summary(health_center_id):
    return validate_success(
        api_client.get_governance_summary(health_center_id, OFFICER)
    )


def _seat(health_center_id, **overrides):
    return validate_success(
        api_client.create_board_member(
            health_center_id, create_board_member_payload(**overrides), OFFICER
        ),
        201,
    )


def _patient_seat(health_center_id, patient_id, seat_number):
    return validate_success(
        api_client.create_board_member(
            health_center_id,
            create_patient_seat_payload(patient_id, seat_number=seat_number),
            OFFICER,
        ),
        201,
    )


def _riverbend_with_five_candidate_seats():
    """The industry-seat board plus three patients each seen at the in-scope site."""
    seed_poverty_guidelines()
    health_center = setup_grantee(
        legal_name="Riverbend Community Health", grant_number="H80CS00426"
    )
    site = setup_baseline_site(health_center["id"])
    service = setup_baseline_service(health_center["id"])
    industry_chair = setup_board_seat(
        health_center["id"], derives_over_10pct_income_from_healthcare=True
    )
    draft = setup_draft_fee_schedule(health_center["id"])
    adoption = adopt_schedule(
        health_center["id"], draft["fee_schedule"]["id"], industry_chair["id"]
    )
    ctx = {
        "health_center_id": health_center["id"],
        "site_id": site["id"],
        "service_id": service["id"],
        "chair": industry_chair,
        "chair_id": industry_chair["id"],
        "fee_schedule": adoption["fee_schedule"],
        "fee_schedule_id": adoption["fee_schedule"]["id"],
        "tiers_by_label": {t["tier_label"]: t for t in draft["tiers"]},
    }

    first = setup_verified_patient(
        ctx,
        mrn="MRN-001",
        full_name="Ada Rivera",
        household_size=2,
        declared_annual_income_cents=2190000,
    )
    setup_encounter(ctx, first["patient_id"], encounter_date="2026-03-01T00:00:00Z")
    second = setup_verified_patient(
        ctx,
        mrn="MRN-002",
        full_name="Bo Nkemi",
        household_size=2,
        declared_annual_income_cents=2188000,
        documentation_type="PAY_STUBS",
    )
    setup_encounter(ctx, second["patient_id"], encounter_date="2026-03-01T00:00:00Z")
    third = setup_patient(mrn="MRN-006", full_name="Cy Patel", household_size=1)
    third_encounter = setup_encounter(
        ctx,
        third["id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=10000,
    )

    _patient_seat(health_center["id"], first["patient_id"], 2)
    _patient_seat(health_center["id"], second["patient_id"], 3)

    ctx.update(
        {
            "first_patient_id": first["patient_id"],
            "second_patient_id": second["patient_id"],
            "third_patient": third,
            "third_encounter": third_encounter,
        }
    )
    return ctx


def test_a_patient_majority_of_two_thirds_still_reads_deficient_on_the_industry_seat_cap():
    """A clear patient majority does not rescue a board that breaches the industry cap.

    PRD 3.2: "Fifth, `governance_posture` is `GOVERNANCE_COMPLIANT` when *all four*
    of these hold, and `GOVERNANCE_DEFICIENT` otherwise: the seated board count is at
    least 3; the seated board count is at most 25; `patient_seat_pct` is at least
    51.00 — a rounded value of exactly 51.00 satisfies the majority, it need not
    exceed it; and `healthcare_industry_seat_count` is at most half of
    `non_patient_seat_count` with any fraction discarded, so a board with three
    non-patient seats may carry at most one healthcare-industry seat."

    Design: Difficulty/boundary_precision_check/board_composition_thresholds_min_seats_majority_and_industry_cap
    """
    ctx = _riverbend_with_five_candidate_seats()
    assert ctx["third_encounter"]["patient_charge_cents"] == 10000, (
        "the third patient has no documentation, so the full gross stands, got "
        f"{ctx['third_encounter']['patient_charge_cents']}"
    )
    assert ctx["third_encounter"]["charge_basis"] == "FULL_CHARGE_UNVERIFIED"

    summary = _governance_summary(ctx["health_center_id"])

    assert summary["seated_board_count"] == 3
    assert summary["patient_seat_pct"] == pytest.approx(66.67, abs=0.01), (
        "two qualified patient seats out of three seated is 66.67 percent, got "
        f"{summary['patient_seat_pct']}"
    )
    assert summary["non_patient_seat_count"] == 1
    assert summary["healthcare_industry_seat_count"] == 1
    assert summary["governance_posture"] == "GOVERNANCE_DEFICIENT", (
        "one industry seat exceeds half of one non-patient seat with the fraction "
        f"discarded, got {summary['governance_posture']}"
    )


def test_a_fourth_non_patient_seat_fixes_the_cap_but_only_the_fifth_seat_reaches_compliance():
    """Fifty percent misses the majority by a hundredth; sixty percent clears it.

    PRD 3.2: "Fourth, `patient_seat_pct` is 0.00 when the seated set is empty, and
    otherwise the qualified patient seat count divided by the seated board count,
    multiplied by 100, rounded half up to two decimal places." PRD 3.2 also states:
    "Third, three tallies are taken over the seated set:
    `qualified_patient_seat_count`, the number of seats qualified by step two;
    `non_patient_seat_count`, the number of seats whose `seat_type` is `NON_PATIENT`;
    and `healthcare_industry_seat_count`, the number of non-patient seats whose
    `derives_over_10pct_income_from_healthcare` is true."

    Design: Difficulty/boundary_precision_check/board_composition_thresholds_min_seats_majority_and_industry_cap
    """
    ctx = _riverbend_with_five_candidate_seats()

    _seat(ctx["health_center_id"], seat_number=4, expertise_category="LEGAL")
    at_four = _governance_summary(ctx["health_center_id"])
    assert at_four["patient_seat_pct"] == pytest.approx(50.00, abs=0.01), (
        "two qualified patient seats out of four seated is 50.00 percent, got "
        f"{at_four['patient_seat_pct']}"
    )
    assert at_four["healthcare_industry_seat_count"] == 1
    assert at_four["non_patient_seat_count"] == 2, (
        "the industry cap is satisfied now that one industry seat sits inside two "
        "non-patient seats"
    )
    assert at_four["governance_posture"] == "GOVERNANCE_DEFICIENT", (
        "50.00 fails the 51.00 majority test by one point"
    )

    _patient_seat(ctx["health_center_id"], ctx["third_patient"]["id"], 5)
    at_five = _governance_summary(ctx["health_center_id"])
    assert at_five["patient_seat_pct"] == pytest.approx(60.00, abs=0.01), (
        "three qualified patient seats out of five seated is 60.00 percent, got "
        f"{at_five['patient_seat_pct']}"
    )
    assert at_five["qualified_patient_seat_count"] == 3
    assert at_five["healthcare_industry_seat_count"] == 1
    assert at_five["governance_posture"] == "GOVERNANCE_COMPLIANT", (
        "every one of the four conditions holds at five seats"
    )

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["seated_board_count"] == 5
    assert health_center["patient_seat_pct"] == pytest.approx(60.00, abs=0.01)


def _successor_payload():
    """A seat-1 successor whose term_start is exactly the incumbent's term_end."""
    return create_board_member_payload(
        seat_number=1,
        seat_type="NON_PATIENT",
        expertise_category="COMMUNITY",
        term_start="2028-12-31T00:00:00Z",
        term_end="2031-12-31T00:00:00Z",
    )


def test_a_successor_term_that_starts_on_the_incumbents_last_day_is_an_overlap():
    """Closed board terms collide where half-open fee periods would merely abut.

    PRD 3.2: "Because terms are closed at both ends, touching terms collide: if an
    existing seated member of that seat has a `term_end` exactly equal to the new
    member's `term_start`, the new seating is rejected with
    `ERR_BOARD_SEAT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/board_seat_terms_closed_intervals_reject_adjacent_succession
    """
    ctx = setup_boot_fs()
    assert same_instant(ctx["chair"]["term_end"]) == "2028-12-31T00:00:00Z"
    assert ctx["chair"]["status"] == "SEATED"

    validate_error(
        api_client.create_board_member(
            ctx["health_center_id"], _successor_payload(), OFFICER
        ),
        ApiErrorId.ERR_BOARD_SEAT_OVERLAP.value,
    )

    assert refresh_health_center(ctx["health_center_id"])["seated_board_count"] == 1, (
        "the rejected seating leaves the roster at the single incumbent"
    )
    assert (
        validate_success(api_client.get_board_member(ctx["chair_id"], OFFICER))["status"]
        == "SEATED"
    )


def test_the_identical_successor_seats_once_the_incumbent_resigns_and_frees_the_seat():
    """Exclusivity is scoped to seated rows, so resignation makes the same payload legal.

    PRD 3.2: "The transition is `SEATED → RESIGNED`; it truncates `term_end` down to
    the `resignation_date`, thereby freeing the `seat_number` for a new term, and it
    recomputes the grantee's `seated_board_count`, `patient_seat_pct` and
    `governance_posture` with a `version` increment."

    Design: Difficulty/resource_temporal_overlap/board_seat_terms_closed_intervals_reject_adjacent_succession
    """
    ctx = setup_boot_fs()

    resigned = validate_success(
        api_client.resign_board_member(
            ctx["chair_id"], resign_board_member_payload(), OFFICER
        )
    )
    assert resigned["status"] == "RESIGNED"
    assert same_instant(resigned["term_end"]) == "2026-08-01T00:00:00Z", (
        "term_end is truncated down to the resignation_date, got "
        f"{resigned['term_end']}"
    )

    successor = validate_success(
        api_client.create_board_member(
            ctx["health_center_id"], _successor_payload(), OFFICER
        ),
        201,
    )
    assert successor["status"] == "SEATED"
    assert successor["seat_number"] == 1
    assert successor["patient_seat_qualified"] is False, (
        "a non-patient seat is never a qualified patient seat"
    )

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["seated_board_count"] == 1, (
        "the resigned member leaves the seated set entirely"
    )
    assert health_center["patient_seat_pct"] == pytest.approx(0.00, abs=0.01)
    assert health_center["governance_posture"] == "GOVERNANCE_DEFICIENT"
