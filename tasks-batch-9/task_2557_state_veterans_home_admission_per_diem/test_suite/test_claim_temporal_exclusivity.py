"""A resident-day and a unit-month are each held by one claim at a time.

A day that a transfer has already assigned to one unit cannot be billed again by
the other, and a unit-month occupied by a live claim admits no second claim until
that claim leaves the occupying set.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CLAIM_PERIOD_OVERLAP


def _august_split_across_two_units(api):
    """August split fifteen days on the source unit and sixteen on the target.

    The checkpoint is deliberately run immediately before the transfer, so the
    first half of the month is materialised against the source unit and only the
    remainder can carry the target.
    """
    scenario = fx.admitted_resident_with_care_plan(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    target = fx.add_unit(api, scenario, care_level="NURSING", licensed_bed_count=2)
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    fx.census_run(api, "2026-08-15", scenario.home_id)
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    validate_success(fx.transfer(api, scenario.resident_id, target["id"], "2026-08-16"), 200)
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)
    return scenario, target


def test_the_month_divides_between_the_two_units_without_loss_or_overlap(api):
    """Two claims for the same month bill fifteen and sixteen days, totalling thirty-one.

    Per the PRD: "A census day belongs to a claim's attributable set when its
    `care_unit_id` matches the claim's, its `service_date` falls inside the claim's
    `claim_month`, and its `per_diem_claim_id` is either null, equal to this claim,
    or points at a claim whose `status` is `REJECTED` or `VOID`."

    Design: Difficulty/resource_temporal_overlap/census_day_single_attribution_across_transferred_units
    """
    scenario, target = _august_split_across_two_units(api)

    source_claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    target_claim = validate_success(
        fx.open_claim(api, scenario.home_id, target["id"], "2026-08", "AUDITED_BASIS"), 201
    )

    assert source_claim["resident_day_count"] == 15
    assert source_claim["claim_amount_cents"] == 177855
    assert target_claim["resident_day_count"] == 16
    assert target_claim["claim_amount_cents"] == 189712
    assert source_claim["resident_day_count"] + target_claim["resident_day_count"] == 31


def test_correcting_the_paid_unit_month_reprices_its_own_fifteen_days_only(api):
    """The correction re-scans the unit, not the resident, so the paid half is not doubled.

    Per the PRD: "Every census day of the unit inside the month whose
    `per_diem_claim_id` is null or points at the target is re-attributed to the new
    claim with `claimed` reset to false". The other unit's sixteen days belong to
    the other claim and stay there.

    Design: Difficulty/resource_temporal_overlap/census_day_single_attribution_across_transferred_units
    """
    scenario, target = _august_split_across_two_units(api)
    source_claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    target_claim = validate_success(
        fx.open_claim(api, scenario.home_id, target["id"], "2026-08", "AUDITED_BASIS"), 201
    )
    validate_success(fx.submit_claim(api, source_claim["id"]), 200)
    paid = validate_success(fx.adjudicate_claim(api, source_claim["id"], "PAID", note="paid in full"), 200)
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 177855

    correction = validate_success(
        fx.correct_claim(api, source_claim["id"], "rate audit rerun"), 201
    )

    assert correction["resident_day_count"] == 15
    assert correction["claim_amount_cents"] == 177855
    assert correction["corrects_claim_id"] == source_claim["id"]
    assert correction["correction_generation"] == 1
    assert correction["claim_month"] == "2026-08"
    assert correction["care_unit_id"] == scenario.unit_id
    assert fx.read_claim(api, target_claim["id"])["status"] == "DRAFT"


def _billed_august_with_one_draft_claim(api):
    """A materialised August and a single draft claim holding the unit-month."""
    scenario = fx.billed_month(
        api, admission_date="2026-08-01", through_date="2026-08-31", care_level="NURSING"
    )
    first = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    return scenario, first


def test_a_draft_claim_holds_the_unit_month_against_a_second_claim(api):
    """While a draft occupies the month, a second plain claim for it is refused.

    Per the PRD: "At most one claim per care unit and `claim_month` may occupy the
    month at a time: opening a plain claim is rejected with
    `ERR_CLAIM_PERIOD_OVERLAP` (HTTP 409) when another claim for the same
    `care_unit_id` and `claim_month` already has `status` `DRAFT` or `SUBMITTED`."

    Design: Difficulty/resource_temporal_overlap/one_open_claim_per_care_unit_month
    """
    scenario, _first = _billed_august_with_one_draft_claim(api)

    validate_error(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"),
        ERR_CLAIM_PERIOD_OVERLAP,
        409,
    )


def test_submitting_the_first_claim_does_not_release_the_unit_month(api):
    """The month stays occupied after submission, so a duplicate is still refused.

    Per the PRD: "A `REJECTED` or `VOID` month is free, and its days are back in the
    pool." Submission moves the claim into the other occupying status rather than out
    of the set, which is why the same refusal repeats.

    Design: Difficulty/resource_temporal_overlap/one_open_claim_per_care_unit_month
    """
    scenario, first = _billed_august_with_one_draft_claim(api)
    validate_error(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"),
        ERR_CLAIM_PERIOD_OVERLAP,
        409,
    )

    validate_success(fx.submit_claim(api, first["id"]), 200)

    validate_error(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"),
        ERR_CLAIM_PERIOD_OVERLAP,
        409,
    )


def test_rejection_reopens_the_unit_month_for_a_fresh_claim(api):
    """A rejected claim vacates the slot and its days return to the pool.

    Per the PRD: "On an outcome of `REJECTED`, a `rejection_code` of
    `CENSUS_MISMATCH`, `RECOGNITION_LAPSE` or `DUPLICATE_PERIOD` is required;
    `status` becomes `REJECTED`, `adjudicated_at` is stamped, `paid_amount_cents` is
    set to 0, the code is stored, and every attributed census day is released with
    `per_diem_claim_id` set back to null and `claimed` back to false, which returns
    those days to the pool."

    Design: Difficulty/resource_temporal_overlap/one_open_claim_per_care_unit_month
    """
    scenario, first = _billed_august_with_one_draft_claim(api)
    validate_success(fx.submit_claim(api, first["id"]), 200)

    rejected = validate_success(
        fx.adjudicate_claim(
            api,
            first["id"],
            "REJECTED",
            rejection_code="CENSUS_MISMATCH",
            note="census under review",
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["paid_amount_cents"] == 0
    assert rejected["rejection_code"] == "CENSUS_MISMATCH"

    replacement = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )

    assert replacement["status"] == "DRAFT"
    assert replacement["resident_day_count"] == 31
    assert replacement["claim_amount_cents"] == 367567
    assert replacement["correction_generation"] == 0
    assert replacement["corrects_claim_id"] is None
