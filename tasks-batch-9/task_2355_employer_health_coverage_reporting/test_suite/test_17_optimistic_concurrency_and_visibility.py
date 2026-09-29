"""Version-guarded writes, and the immediate visibility of what they produced.

Two writes in this system legitimately supersede earlier work, so both echo the
parent resource's version back to the server; replaying a token the parent has
since outgrown is refused and changes nothing. What a successful write produces
is carried by the very response that caused it and by every read that follows.

The harness empties the database and relaunches the API before every single
test, so each test builds its own world from the PRD's own endpoints.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = TEST_USERS["compliance_officer"]
PREPARER_1 = TEST_USERS["preparer"]


# ---------------------------------------------------------------------------
# World builders composed from test_helpers.fixtures
# ---------------------------------------------------------------------------
def _determined_group_with_a_replayable_token(api):
    """Season, controlled group, one member with twelve prior-year headcount
    months, and one aggregated determination already run with the group version
    the client read just beforehand. That consumed token is returned so a test
    can replay it."""
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"])
    member = fixtures.create_group_member(api, group["id"], measurement_method="MONTHLY")
    fixtures.record_headcounts(api, member["id"])
    group_v1 = fixtures.current_group_version(api, group["id"])
    determined = validate_success(
        api.run_ale_determination(
            group["id"], f.ale_determination_payload(group_v1, basis="AGGREGATED"), CO
        ),
        200,
    )
    return {
        "season": season,
        "group": group,
        "member": member,
        "group_v1": group_v1,
        "determined": determined,
    }


def _member_with_one_transmittal_holding_its_only_statement(api):
    """The prelude plus one employee and one statement, with the member version
    read *after* the statement was generated and then spent on opening a
    transmittal and attaching that statement to it."""
    ctx = fixtures.determined_ale_group_with_employee(api)
    ctx["form"] = fixtures.generate_form(api, ctx["employee"]["id"], headers=PREPARER_1)
    member_id = ctx["member"]["id"]
    ctx["member_v"] = fixtures.current_member_version(api, member_id, PREPARER_1)
    ctx["transmittal"] = validate_success(
        api.create_transmittal(
            f.transmittal_payload(member_id, ctx["member_v"], transmission_type="ORIGINAL"),
            PREPARER_1,
        ),
        201,
    )
    fixtures.attach_forms(api, ctx["transmittal"]["id"], [ctx["form"]["id"]], PREPARER_1)
    return ctx


def _group_with_prior_and_reporting_year_headcounts(api):
    """Season, controlled group and one member carrying twelve prior-year months
    of 40 full-time / 1200 part-time hours / 60 total plus twelve reporting-year
    months of 30 full-time employees. Nothing is determined yet."""
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"])
    member = fixtures.create_group_member(api, group["id"], measurement_method="MONTHLY")
    fixtures.record_headcounts(
        api,
        member["id"],
        count_year="PRIOR_YEAR",
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    fixtures.record_headcounts(
        api,
        member["id"],
        count_year="REPORTING_YEAR",
        full_time_employee_count=30,
        part_time_hours_total=0,
        total_employee_count=35,
    )
    return season, group, member


# ---------------------------------------------------------------------------
# The determination echoes the controlled group's version
# ---------------------------------------------------------------------------
def test_ale_determination_with_a_stale_group_version_is_rejected(api):
    """PRD §2.8: "Running an applicable-large-employer determination requires
    `expected_controlled_group_version` in the body — a non-optional field
    carrying the `version` the client last read from the controlled group."
    PRD §2.8: "When that value does not equal the group's current `version`, the
    determination is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412)."

    Design: Corner/Cross-Cutting Complexity Layers/occ_ale_determination_stale_group_version_rejected
    """
    ctx = _determined_group_with_a_replayable_token(api)

    refused = api.run_ale_determination(
        ctx["group"]["id"],
        f.ale_determination_payload(
            ctx["group_v1"], basis="SINGLE_MEMBER", single_member_id=ctx["member"]["id"]
        ),
        CO,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_GROUP_VERSION, 412)


def test_successful_determination_advances_the_group_version(api):
    """PRD §3.2: "Whichever branch fires, the determination writes
    `monthly_group_fte`, `annual_average_fte_raw`, `annual_average_fte`,
    `determination_basis` (`AGGREGATED` or `SINGLE_MEMBER`), `ale_reason` and
    `seasonal_exception_applied`, stamps `determined_at` from the logical clock and
    `last_determination_user_id` from the acting officer, and increments the
    group's `version` by one."
    PRD §2.8: "The guard matters because a determination may legitimately replace
    an earlier one; without it, a client holding an outdated view of the group
    would overwrite counts derived from headcount amendments it never saw."

    Design: Corner/Cross-Cutting Complexity Layers/occ_ale_determination_stale_group_version_rejected
    """
    ctx = _determined_group_with_a_replayable_token(api)

    assert ctx["determined"]["version"] == ctx["group_v1"] + 1, (
        f"expected the determination to move the group version from "
        f"{ctx['group_v1']} to {ctx['group_v1'] + 1}, got "
        f"{ctx['determined']['version']} — which is what makes a replay stale"
    )


def test_stale_determination_leaves_the_earlier_verdict_in_place(api):
    """PRD §2.8: "When that value does not equal the group's current `version`, the
    determination is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412)."
    PRD §3.2: "Under the aggregated basis the counted set is every `ACTIVE` member
    of the group; under the single-member basis it is exactly the named member."

    Design: Corner/Cross-Cutting Complexity Layers/occ_ale_determination_stale_group_version_rejected
    """
    ctx = _determined_group_with_a_replayable_token(api)

    refused = api.run_ale_determination(
        ctx["group"]["id"],
        f.ale_determination_payload(
            ctx["group_v1"], basis="SINGLE_MEMBER", single_member_id=ctx["member"]["id"]
        ),
        CO,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_GROUP_VERSION, 412)

    after = fixtures.read_group(api, ctx["group"]["id"])
    assert after["determination_basis"] == "AGGREGATED", (
        f"the refused single-member replay must not rewrite the basis; expected "
        f"AGGREGATED, got {after['determination_basis']!r}"
    )
    assert after["determination_state"] == "DETERMINED_ALE", (
        f"expected the earlier verdict DETERMINED_ALE to stand, got "
        f"{after['determination_state']!r}"
    )
    assert after["annual_average_fte"] == 50, (
        f"expected the earlier aggregated count of 50 to stand, got "
        f"{after['annual_average_fte']}"
    )


def test_determination_replayed_with_the_refreshed_group_version_succeeds(api):
    """PRD §3.2: "Re-running a determination on a group already in
    `DETERMINED_ALE` is a legitimate self-loop that overwrites the previous outputs
    with the new basis and again advances `version`; this is precisely why the
    write is version-guarded."
    PRD §2.8: "The single-group read exposes the `version` value a caller must echo
    back."

    Design: Corner/Cross-Cutting Complexity Layers/occ_ale_determination_stale_group_version_rejected
    """
    ctx = _determined_group_with_a_replayable_token(api)
    fresh_version = fixtures.current_group_version(api, ctx["group"]["id"])

    applied = validate_success(
        api.run_ale_determination(
            ctx["group"]["id"],
            f.ale_determination_payload(
                fresh_version, basis="SINGLE_MEMBER", single_member_id=ctx["member"]["id"]
            ),
            CO,
        ),
        200,
    )
    assert applied["determination_basis"] == "SINGLE_MEMBER", (
        f"the fresh token must let the single-member basis through, got "
        f"{applied['determination_basis']!r}"
    )
    assert applied["version"] == fresh_version + 1, (
        f"expected the self-loop to advance the version to {fresh_version + 1}, "
        f"got {applied['version']}"
    )


# ---------------------------------------------------------------------------
# Opening a transmittal echoes the group member's version
# ---------------------------------------------------------------------------
def test_transmittal_creation_with_a_stale_member_version_is_rejected(api):
    """PRD §2.8: "Opening a transmittal requires `expected_group_member_version`
    in the body — a non-optional field carrying the `version` the client last read
    from the group member."
    PRD §2.8: "A mismatch with the member's current `version` is rejected with
    `ERR_STALE_MEMBER_VERSION` (HTTP 412)."

    Design: Corner/Cross-Cutting Complexity Layers/occ_transmittal_create_stale_member_version_rejected
    """
    ctx = _member_with_one_transmittal_holding_its_only_statement(api)

    refused = api.create_transmittal(
        f.transmittal_payload(
            ctx["member"]["id"], ctx["member_v"], transmission_type="REPLACEMENT"
        ),
        PREPARER_1,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_MEMBER_VERSION, 412)


def test_no_second_transmittal_is_created_when_the_member_version_is_stale(api):
    """PRD §2.8: "A mismatch with the member's current `version` is rejected with
    `ERR_STALE_MEMBER_VERSION` (HTTP 412)."
    PRD §2.8: "A newly built transmittal supersedes the member's prior built
    submission, so a stale view of the member — its `open_transmittal_id`, its
    attached and unattached form counts, or its reporting-year full-time months —
    must not become the basis of a new submission."

    Design: Corner/Cross-Cutting Complexity Layers/occ_transmittal_create_stale_member_version_rejected
    """
    ctx = _member_with_one_transmittal_holding_its_only_statement(api)

    refused = api.create_transmittal(
        f.transmittal_payload(
            ctx["member"]["id"], ctx["member_v"], transmission_type="REPLACEMENT"
        ),
        PREPARER_1,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_MEMBER_VERSION, 412)

    rows, meta = validate_paginated(api.list_transmittals(PREPARER_1))
    assert meta["total_count"] == 1, (
        f"the refused create must leave exactly the one existing transmittal, got "
        f"{meta['total_count']}"
    )
    assert rows[0]["id"] == ctx["transmittal"]["id"], (
        "the surviving transmittal must be the one opened with a fresh token"
    )


def test_opening_and_attaching_both_advance_the_member_version(api):
    """PRD §3.8: "A new transmittal starts at `DRAFT` with `cycle_number` 1, every
    counter at zero and null `channel`, `receipt_id`, `built_at` and
    `transmitted_at`; creating it sets the member's `open_transmittal_id` and
    increments the member's `version`."
    PRD §3.8: "Each attached form moves `NOT_FILED` → `ATTACHED` and records the
    transmittal in its `transmittal_id`, the transmittal's `form_count` increments,
    and the member's `unattached_form_count` moves into `attached_form_count`; the
    member's `version` advances."

    Design: Corner/Cross-Cutting Complexity Layers/occ_transmittal_create_stale_member_version_rejected
    """
    ctx = _member_with_one_transmittal_holding_its_only_statement(api)

    after = fixtures.read_member(api, ctx["member"]["id"])
    assert after["version"] > ctx["member_v"], (
        f"opening the transmittal and attaching the statement both write the "
        f"member's counters, so its version must exceed the token "
        f"{ctx['member_v']} spent on the open, got {after['version']}"
    )
    assert after["attached_form_count"] == 1, (
        f"expected the attached statement to be counted on the member, got "
        f"attached_form_count {after['attached_form_count']}"
    )
    assert after["unattached_form_count"] == 0, (
        f"the attach moves the count out of unattached_form_count, got "
        f"{after['unattached_form_count']}"
    )


def test_transmittal_creation_succeeds_with_the_refreshed_member_version(api):
    """PRD §2.8: "Opening a transmittal requires `expected_group_member_version`
    in the body — a non-optional field carrying the `version` the client last read
    from the group member."
    PRD §3.8: "A `Preparer` opens a **Transmittal**, the 1094-C for one member,
    naming the `group_member_id`, a `transmission_type` of `ORIGINAL`, `CORRECTION`
    or `REPLACEMENT`, the mandatory `expected_group_member_version` of §2.8, and
    optionally `authoritative_indicator`, which defaults to true and marks this as
    the member's authoritative transmittal carrying Part III."

    Design: Corner/Cross-Cutting Complexity Layers/occ_transmittal_create_stale_member_version_rejected
    """
    ctx = _member_with_one_transmittal_holding_its_only_statement(api)
    fresh_version = fixtures.current_member_version(api, ctx["member"]["id"], PREPARER_1)

    opened = validate_success(
        api.create_transmittal(
            f.transmittal_payload(
                ctx["member"]["id"], fresh_version, transmission_type="REPLACEMENT"
            ),
            PREPARER_1,
        ),
        201,
    )
    assert opened["status"] == "DRAFT", (
        f"a newly opened transmittal starts at DRAFT, got {opened['status']!r}"
    )
    assert opened["transmission_type"] == "REPLACEMENT", (
        f"expected the requested transmission type to be recorded, got "
        f"{opened['transmission_type']!r}"
    )
    assert opened["id"] != ctx["transmittal"]["id"], (
        "the refreshed token must open a genuinely new transmittal"
    )


# ---------------------------------------------------------------------------
# The determination's cascade is visible with no lag
# ---------------------------------------------------------------------------
def test_determination_response_already_carries_its_counting_outputs(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.2: "The twelve stored monthly figures are then summed, divided by 12,
    and rounded half up to two decimal places to give `annual_average_fte_raw`;
    truncating that value gives the whole-number `annual_average_fte` that is
    compared against the threshold of 50 full-time-equivalent employees."
    PRD §3.2: "When `annual_average_fte` is at least 50 but that exception does not
    apply, the group becomes `DETERMINED_ALE` with `ale_reason` of `THRESHOLD_MET`
    and `seasonal_exception_applied` false."

    Design: Corner/Consistency Model/immediate_visibility_of_determination_in_same_response
    """
    _season, group, _member = _group_with_prior_and_reporting_year_headcounts(api)
    version = fixtures.current_group_version(api, group["id"])

    determined = validate_success(
        api.run_ale_determination(
            group["id"], f.ale_determination_payload(version, basis="AGGREGATED"), CO
        ),
        200,
    )

    assert determined["determination_state"] == "DETERMINED_ALE", (
        f"expected DETERMINED_ALE in the very response that caused it, got "
        f"{determined['determination_state']!r}"
    )
    assert determined["ale_reason"] == "THRESHOLD_MET", (
        f"expected THRESHOLD_MET, got {determined['ale_reason']!r}"
    )
    assert determined["annual_average_fte"] == 50, (
        f"each month contributes 40 + 1200/120 = 50, so the annual average is 50; "
        f"got {determined['annual_average_fte']}"
    )
    assert determined["annual_average_fte_raw"] == pytest.approx(50.00, abs=0.01), (
        f"expected annual_average_fte_raw 50.00, got "
        f"{determined['annual_average_fte_raw']}"
    )
    assert determined["monthly_group_fte"] == [50] * 12, (
        f"expected twelve truncated monthly group figures of 50, got "
        f"{determined['monthly_group_fte']}"
    )
    assert determined["seasonal_exception_applied"] is False, (
        f"no month exceeded 50, so the seasonal exception cannot apply; got "
        f"seasonal_exception_applied {determined['seasonal_exception_applied']!r}"
    )


def test_member_reporting_year_full_time_months_is_visible_on_the_next_read(api):
    """PRD §3.2: "A determination that lands on `DETERMINED_ALE` additionally
    recomputes `reporting_year_ft_months` for every `ACTIVE` member as the sum over
    months 1 through 12 of that member's reporting-year full-time employee counts —
    the weight both later allocations divide by."
    PRD §3.1: "Members start with `member_status` of `ACTIVE` and every counter at
    zero: `generated_form_count`, `unattached_form_count`, `attached_form_count`,
    `reporting_year_ft_months`, `allocated_exclusion_employees`,
    `allocated_penalty_cents` and `furnishing_penalty_total_cents`, with a null
    `open_transmittal_id`."

    Design: Corner/Consistency Model/immediate_visibility_of_determination_in_same_response
    """
    _season, group, member = _group_with_prior_and_reporting_year_headcounts(api)
    assert member["reporting_year_ft_months"] == 0, (
        "the member's weight starts at zero before any determination"
    )
    version = fixtures.current_group_version(api, group["id"])

    validate_success(
        api.run_ale_determination(
            group["id"], f.ale_determination_payload(version, basis="AGGREGATED"), CO
        ),
        200,
    )

    after = fixtures.read_member(api, member["id"])
    assert after["reporting_year_ft_months"] == 360, (
        f"twelve reporting-year months of 30 full-time employees sum to 360, and "
        f"the figure is written by a side effect on an entity other than the one "
        f"the determination returned; got {after['reporting_year_ft_months']}"
    )


def test_group_read_matches_the_determination_response_field_for_field(api):
    """PRD §3.2: "Whichever branch fires, the determination writes
    `monthly_group_fte`, `annual_average_fte_raw`, `annual_average_fte`,
    `determination_basis` (`AGGREGATED` or `SINGLE_MEMBER`), `ale_reason` and
    `seasonal_exception_applied`, stamps `determined_at` from the logical clock and
    `last_determination_user_id` from the acting officer, and increments the
    group's `version` by one."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/Consistency Model/immediate_visibility_of_determination_in_same_response
    """
    _season, group, _member = _group_with_prior_and_reporting_year_headcounts(api)
    version = fixtures.current_group_version(api, group["id"])

    determined = validate_success(
        api.run_ale_determination(
            group["id"], f.ale_determination_payload(version, basis="AGGREGATED"), CO
        ),
        200,
    )
    read_back = fixtures.read_group(api, group["id"])

    for field in (
        "determination_state",
        "determination_basis",
        "ale_reason",
        "annual_average_fte",
        "annual_average_fte_raw",
        "monthly_group_fte",
        "seasonal_exception_applied",
        "determined_at",
        "last_determination_user_id",
        "version",
    ):
        assert read_back[field] == determined[field], (
            f"{field}: the read that immediately follows the determination must "
            f"already agree with the response that caused it — response "
            f"{determined[field]!r}, read {read_back[field]!r}"
        )
    assert determined["last_determination_user_id"] == CO["X-User-ID"], (
        f"expected the acting officer {CO['X-User-ID']!r} to be stamped, got "
        f"{determined['last_determination_user_id']!r}"
    )
