"""Domain assertions and the arithmetic the PRD pins down.

The helpers here fall into three groups: pure arithmetic that reproduces a PRD
formula so a test can state the expected figure and the derivation side by side;
field-level assertions over a single representation; and conservation
assertions that hold across a whole project ledger at any point in time.
"""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import validate_paginated

from . import constants


# ─── Rounding disciplines (PRD §2.5) ──────────────────


def round_half_up(value):
    """Round a rational value to the nearest whole cent, halves upward."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_to_int(value):
    """Truncate toward negative infinity, the discipline for caps and terms."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def developer_fee_cap_cents(hard_and_soft_qre_cents):
    """Fifteen percent of qualifying construction cost, floored (PRD §3.6)."""
    return floor_to_int(
        Decimal(str(hard_and_soft_qre_cents)) * Decimal(str(constants.DEVELOPER_FEE_CAP_RATE))
    )


def substantial_test_threshold_cents(adjusted_basis_cents):
    """The greater of adjusted basis and the statutory floor (PRD §3.6)."""
    return max(adjusted_basis_cents, constants.SUBSTANTIAL_TEST_FLOOR_CENTS)


def annual_credit_cents(qre_total_cents):
    """Four percent of qualified expenditure, rounded half up (PRD §3.6)."""
    return round_half_up(
        Decimal(str(qre_total_cents)) * Decimal(str(constants.CREDIT_RATE_PER_YEAR))
    )


def total_claimable_credit_cents(qre_total_cents):
    """The annual instalment multiplied by five, not five percent of the total."""
    return annual_credit_cents(qre_total_cents) * constants.RATABLE_YEARS


def lease_term_risk_points(lease_term_years):
    """Lease-term component of the risk score, capped at thirty (PRD §3.7)."""
    ratio = Decimal(str(lease_term_years)) / Decimal(
        constants.LEASE_TERM_SAFE_HARBOR_YEARS
    )
    points = round_half_up(Decimal(constants.LEASE_TERM_POINTS_CAP) * ratio)
    return min(constants.LEASE_TERM_POINTS_CAP, points)


def recapture_amount_cents(credit_claimed_to_date_cents, full_years_elapsed):
    """Twenty percent forgiven per full year, remainder recaptured (PRD §3.8)."""
    remaining_pct = Decimal(1) - (
        Decimal(str(constants.RECAPTURE_STEP_RATE)) * Decimal(full_years_elapsed)
    )
    if remaining_pct < 0:
        remaining_pct = Decimal(0)
    return round_half_up(Decimal(str(credit_claimed_to_date_cents)) * remaining_pct)


# ─── Single-representation assertions ─────────────────


def assert_fields(data, label="row", **expected):
    """Assert an exact value for each named field, reporting all mismatches."""
    mismatches = []
    for field, want in expected.items():
        assert field in data, "{0} has no field {1}; got {2}".format(
            label, field, sorted(data.keys())
        )
        got = data[field]
        if isinstance(want, float) or isinstance(got, float):
            same = abs(float(got) - float(want)) < 1e-9
        else:
            same = got == want
        if not same:
            mismatches.append("{0}: expected {1!r}, got {2!r}".format(field, want, got))
    assert not mismatches, "{0} field mismatches -- {1}".format(
        label, "; ".join(mismatches)
    )


def assert_project_state(project, certification_status=None, compliance_status=None):
    """The two dimensions of PRD §2.6, which move independently."""
    if certification_status is not None:
        assert project["certification_status"] == certification_status, (
            "expected certification_status {0}, got {1}".format(
                certification_status, project["certification_status"]
            )
        )
    if compliance_status is not None:
        assert project["compliance_status"] == compliance_status, (
            "expected compliance_status {0}, got {1}".format(
                compliance_status, project["compliance_status"]
            )
        )


def assert_ledger(project, **expected):
    """Assert named money and status fields on a project ledger."""
    assert_fields(project, "project ledger", **expected)


def assert_substantial_test(project, status, threshold_cents=None):
    assert project["substantial_test_status"] == status, (
        "expected substantial_test_status {0}, got {1} (qre_total_final_cents={2},"
        " threshold={3})".format(
            status,
            project["substantial_test_status"],
            project["qre_total_final_cents"],
            project["substantial_test_threshold_cents"],
        )
    )
    if threshold_cents is not None:
        assert project["substantial_test_threshold_cents"] == threshold_cents, (
            "expected threshold {0}, got {1}".format(
                threshold_cents, project["substantial_test_threshold_cents"]
            )
        )


def assert_ratable_schedule(project, expected_annual_cents):
    """The annual instalment and the five-year total agree with each other."""
    assert project["annual_credit_cents"] == expected_annual_cents, (
        "expected annual_credit_cents {0}, got {1}".format(
            expected_annual_cents, project["annual_credit_cents"]
        )
    )
    expected_total = expected_annual_cents * constants.RATABLE_YEARS
    assert project["total_claimable_credit_cents"] == expected_total, (
        "expected total_claimable_credit_cents {0} (annual x {1}), got {2}".format(
            expected_total,
            constants.RATABLE_YEARS,
            project["total_claimable_credit_cents"],
        )
    )


def assert_risk_score(interest, expected_score, expected_variant=None):
    assert interest["disqualification_risk_score"] == expected_score, (
        "expected disqualification_risk_score {0}, got {1}".format(
            expected_score, interest["disqualification_risk_score"]
        )
    )
    if expected_variant is not None:
        assert interest["risk_variant_applied"] == expected_variant, (
            "expected risk_variant_applied {0}, got {1}".format(
                expected_variant, interest["risk_variant_applied"]
            )
        )


def assert_version(data, expected_version, label="row"):
    assert data["version"] == expected_version, (
        "expected {0}.version {1}, got {2}".format(label, expected_version, data["version"])
    )


def assert_version_advanced_by(before, after, steps, label="row"):
    """A single request may bump a version more than once via its cascade."""
    assert after["version"] == before["version"] + steps, (
        "expected {0}.version to advance by {1} from {2}, got {3}".format(
            label, steps, before["version"], after["version"]
        )
    )


def assert_no_mutation_fields(data, label="row"):
    """Identity rows are never mutated, so they carry no version (PRD §2.4)."""
    assert "version" not in data, "{0} must not expose version".format(label)
    assert "updated_at" not in data, "{0} must not expose updated_at".format(label)


# ─── Conservation assertions ──────────────────────────


def assert_classified_cost_conservation(project):
    """Qualified plus nonqualified always equals the classified total."""
    expected = project["qre_total_final_cents"] + project["nonqualified_total_cents"]
    assert project["classified_cost_total_cents"] == expected, (
        "classified_cost_total_cents {0} must equal qre_total_final_cents {1} plus "
        "nonqualified_total_cents {2}".format(
            project["classified_cost_total_cents"],
            project["qre_total_final_cents"],
            project["nonqualified_total_cents"],
        )
    )


def assert_credit_conservation(project):
    """Claimed, recaptured and unclaimed always sum to the claimable total."""
    parts = (
        project["credit_claimed_to_date_cents"]
        + project["credit_recaptured_cents"]
        + project["credit_unclaimed_cents"]
    )
    assert parts == project["total_claimable_credit_cents"], (
        "credit_claimed_to_date_cents {0} + credit_recaptured_cents {1} + "
        "credit_unclaimed_cents {2} must equal total_claimable_credit_cents {3}".format(
            project["credit_claimed_to_date_cents"],
            project["credit_recaptured_cents"],
            project["credit_unclaimed_cents"],
            project["total_claimable_credit_cents"],
        )
    )


def assert_qre_summary_reconciles(summary, project):
    """The computed read repeats the persisted figures it derives from."""
    assert summary["classified_cost_total_cents"] == project[
        "classified_cost_total_cents"
    ], "summary classified total {0} != project {1}".format(
        summary["classified_cost_total_cents"], project["classified_cost_total_cents"]
    )
    assert summary["nonqualified_total_cents"] == project["nonqualified_total_cents"], (
        "summary nonqualified total {0} != project {1}".format(
            summary["nonqualified_total_cents"], project["nonqualified_total_cents"]
        )
    )
    assert summary["substantial_test_threshold_cents"] == project[
        "substantial_test_threshold_cents"
    ], "summary threshold {0} != project {1}".format(
        summary["substantial_test_threshold_cents"],
        project["substantial_test_threshold_cents"],
    )
    if summary["variant_applied"] == "FINAL":
        assert summary["qre_total_cents"] == project["qre_total_final_cents"], (
            "FINAL summary qre_total {0} != project qre_total_final {1}".format(
                summary["qre_total_cents"], project["qre_total_final_cents"]
            )
        )
        assert summary["substantial_test_status_under_variant"] == project[
            "substantial_test_status"
        ], "FINAL summary status {0} != project status {1}".format(
            summary["substantial_test_status_under_variant"],
            project["substantial_test_status"],
        )
    else:
        assert summary["qre_total_cents"] == project["qre_total_provisional_cents"], (
            "PROVISIONAL summary qre_total {0} != project provisional {1}".format(
                summary["qre_total_cents"], project["qre_total_provisional_cents"]
            )
        )


# ─── Collection assertions ────────────────────────────


def assert_page(response, total_count=None, has_more=None, limit=None, offset=None):
    """Validate the pagination envelope of PRD §2.3 and its counters."""
    items, meta = validate_paginated(response)
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            "expected total_count {0}, got {1}".format(total_count, meta["total_count"])
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, "expected has_more {0}, got {1}".format(
            has_more, meta["has_more"]
        )
    if limit is not None:
        assert meta["limit"] == limit, "expected limit {0}, got {1}".format(
            limit, meta["limit"]
        )
    if offset is not None:
        assert meta["offset"] == offset, "expected offset {0}, got {1}".format(
            offset, meta["offset"]
        )
    return items, meta


def assert_ids_equal(items, expected_ids, label="collection"):
    got = [item["id"] for item in items]
    assert got == list(expected_ids), "{0} expected ids {1}, got {2}".format(
        label, list(expected_ids), got
    )


def assert_contains_id(items, expected_id, label="collection"):
    got = [item["id"] for item in items]
    assert expected_id in got, "{0} expected to contain {1}, got {2}".format(
        label, expected_id, got
    )


def assert_ascending_by_created_at(items, label="collection"):
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), (
        "{0} must be ordered by created_at ascending, got {1}".format(label, stamps)
    )
