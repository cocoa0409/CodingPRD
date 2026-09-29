"""Temporal windows on agreements and on coverage lines.

An agreement's window is half-open, so touching windows hand over cleanly; a
coverage line's window is closed and must additionally be separated from any other
line for the same journal by more than one day.
"""

from test_helpers import (
    ApiErrorId,
    add_coverage,
    assert_append_only_fields,
    create_agreement_coverage_payload,
    create_transformative_agreement_payload,
    draft_agreement,
    read_publisher,
    register_journal,
    register_publisher,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# private preambles
# --------------------------------------------------------------------------- #
def _setup_publisher_with_first_agreement() -> dict:
    """A publisher carrying one drafted agreement over the half-open window
    [2026-07-01, 2026-10-01)."""
    set_clock("2026-08-01T00:00:00Z")
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-H1",
        effective_from="2026-07-01",
        effective_until="2026-10-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    return {"publisher": publisher, "first_agreement": agreement}


def _setup_two_adjacent_agreements_with_one_coverage_line() -> dict:
    """Two hand-over agreements on the same publisher: the first already carries a
    FULL_APC coverage line closing on 2026-09-30, the second carries none yet."""
    set_clock("2026-08-01T00:00:00Z")
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    journal = register_journal(
        publisher["id"],
        issn="2041-1723",
        title="Meridian Journal of Cell Signalling",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )
    first_agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-H1",
        effective_from="2026-07-01",
        effective_until="2026-10-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    first_coverage = add_coverage(
        first_agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2026-09-30",
    )
    second_agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-H2",
        effective_from="2026-10-01",
        effective_until="2027-01-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    return {
        "publisher": publisher,
        "journal": journal,
        "first_agreement": first_agreement,
        "first_coverage": first_coverage,
        "second_agreement": second_agreement,
    }


# --------------------------------------------------------------------------- #
# half-open agreement windows
# --------------------------------------------------------------------------- #
def test_agreement_starting_on_the_previous_effective_until_is_accepted_as_a_hand_over(
    api, agreement_admin_headers
):
    """A second agreement whose `effective_from` is exactly the first's
    `effective_until` merely touches it, which is a permitted hand-over.

    PRD §2.11: "**Agreement window overlap.** No other transformative agreement of the same publisher whose `status` is `DRAFT`, `ACTIVE` or `EXHAUSTED` has a half-open window from `effective_from` inclusive to `effective_until` exclusive that intersects the new agreement's half-open window. Windows that merely touch — where the new agreement's `effective_from` equals another's `effective_until` — are permitted. Otherwise `ERR_AGREEMENT_WINDOW_OVERLAP` (409). Applies to `POST /transformative-agreements`."
    PRD §3.2: "Because two agreements with the same publisher must not be in force at once, a draft whose half-open window intersects the half-open window of any other `DRAFT`, `ACTIVE` or `EXHAUSTED` agreement of that publisher is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`; a draft that begins exactly on the day another agreement's window ends is a permitted hand-over rather than an overlap."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    PRD §2.10: "`Publisher.active_agreement_count` is the number of that publisher's transformative agreements whose `status` is `ACTIVE`."
    Design: Difficulty/resource_temporal_overlap/agreement_windows_half_open_adjacency_allowed_overlap_conflicts
    """
    scenario = _setup_publisher_with_first_agreement()
    publisher_version = read_publisher(scenario["publisher"]["id"])["version"]

    adjacent = validate_success(
        api.create_transformative_agreement(
            create_transformative_agreement_payload(
                scenario["publisher"]["id"],
                publisher_version,
                agreement_code="TA-MERID-H2",
                effective_from="2026-10-01",
                effective_until="2027-01-01",
                article_quota=5,
                discount_pct=0.20,
                covered_oa_models=["HYBRID"],
            ),
            agreement_admin_headers,
        ),
        expected_status=201,
    )

    assert adjacent["id"] is not None, "the adjacent agreement must have been created"
    assert adjacent["status"] == "DRAFT", (
        f"a newly drafted agreement starts in DRAFT, got {adjacent['status']}"
    )

    rows, _meta = validate_paginated(
        api.list_publisher_agreements(
            scenario["publisher"]["id"], agreement_admin_headers
        )
    )
    assert len(rows) == 2, f"the publisher should hold exactly 2 agreements, got {len(rows)}"
    assert sorted(row["agreement_code"] for row in rows) == [
        "TA-MERID-H1",
        "TA-MERID-H2",
    ], f"unexpected agreement codes: {[row['agreement_code'] for row in rows]}"

    publisher = validate_success(
        api.get_publisher(scenario["publisher"]["id"], agreement_admin_headers)
    )
    assert publisher["active_agreement_count"] == 0, (
        f"both agreements are still DRAFT, so active_agreement_count is 0, "
        f"got {publisher['active_agreement_count']}"
    )


def test_agreement_window_intersecting_the_existing_windows_is_rejected_as_overlapping(
    api, agreement_admin_headers
):
    """A third window from 2026-09-15 to 2026-11-15 intersects both existing
    half-open windows, so the draft is refused and the publisher is left untouched.

    PRD §2.11: "**Agreement window overlap.** No other transformative agreement of the same publisher whose `status` is `DRAFT`, `ACTIVE` or `EXHAUSTED` has a half-open window from `effective_from` inclusive to `effective_until` exclusive that intersects the new agreement's half-open window. Windows that merely touch — where the new agreement's `effective_from` equals another's `effective_until` — are permitted. Otherwise `ERR_AGREEMENT_WINDOW_OVERLAP` (409). Applies to `POST /transformative-agreements`."
    PRD §3.2: "Because two agreements with the same publisher must not be in force at once, a draft whose half-open window intersects the half-open window of any other `DRAFT`, `ACTIVE` or `EXHAUSTED` agreement of that publisher is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`; a draft that begins exactly on the day another agreement's window ends is a permitted hand-over rather than an overlap."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    PRD §2.10: "`Publisher.active_agreement_count` is the number of that publisher's transformative agreements whose `status` is `ACTIVE`."
    Design: Difficulty/resource_temporal_overlap/agreement_windows_half_open_adjacency_allowed_overlap_conflicts
    """
    scenario = _setup_publisher_with_first_agreement()
    draft_agreement(
        scenario["publisher"]["id"],
        agreement_code="TA-MERID-H2",
        effective_from="2026-10-01",
        effective_until="2027-01-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    version_before_rejection = read_publisher(scenario["publisher"]["id"])["version"]

    validate_error(
        api.create_transformative_agreement(
            create_transformative_agreement_payload(
                scenario["publisher"]["id"],
                version_before_rejection,
                agreement_code="TA-MERID-H3",
                effective_from="2026-09-15",
                effective_until="2026-11-15",
                article_quota=5,
                discount_pct=0.20,
                covered_oa_models=["HYBRID"],
            ),
            agreement_admin_headers,
        ),
        ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP.value,
    )

    rows, _meta = validate_paginated(
        api.list_publisher_agreements(
            scenario["publisher"]["id"], agreement_admin_headers
        )
    )
    assert len(rows) == 2, (
        f"the rejected draft must not have been persisted, so 2 agreements remain, "
        f"got {len(rows)}"
    )
    assert sorted(row["agreement_code"] for row in rows) == [
        "TA-MERID-H1",
        "TA-MERID-H2",
    ], f"unexpected agreement codes: {[row['agreement_code'] for row in rows]}"

    publisher = validate_success(
        api.get_publisher(scenario["publisher"]["id"], agreement_admin_headers)
    )
    assert publisher["version"] == version_before_rejection, (
        f"no agreement was drafted, so the publisher's version must stay at "
        f"{version_before_rejection}, got {publisher['version']}"
    )
    assert publisher["active_agreement_count"] == 0, (
        f"both surviving agreements are DRAFT, so active_agreement_count is 0, "
        f"got {publisher['active_agreement_count']}"
    )


# --------------------------------------------------------------------------- #
# closed coverage windows and the one-day separation rule
# --------------------------------------------------------------------------- #
def test_coverage_line_starting_one_day_after_the_previous_covered_until_is_rejected(
    api, agreement_admin_headers
):
    """Back-to-back coverage of the same journal on consecutive days conflicts, even
    though the two parent agreements hand over legally.

    PRD §2.11: "**Coverage window conflict.** No other coverage line for the same `journal_id` has a closed window that is within one day of the new closed window. Concretely, the new line is rejected when its `covered_from` is on or before the other line's `covered_until` plus one day *and* its `covered_until` is on or after the other line's `covered_from` minus one day — so back-to-back coverage of the same journal on consecutive days is a conflict, not an adjacency. Otherwise `ERR_COVERAGE_WINDOW_CONFLICT` (409). Applies to `POST /transformative-agreements/{id}/coverages`."
    PRD §3.2: "Coverage lines for the same journal must additionally be separated by more than one day, as spelled out in rule 24 of §2.11; a violation yields `ERR_COVERAGE_WINDOW_CONFLICT`."
    Design: Difficulty/resource_temporal_overlap/coverage_windows_closed_with_one_day_gap_rule
    """
    scenario = _setup_two_adjacent_agreements_with_one_coverage_line()

    validate_error(
        api.create_agreement_coverage(
            scenario["second_agreement"]["id"],
            create_agreement_coverage_payload(
                scenario["journal"]["id"],
                coverage_type="CAPPED_APC",
                covered_from="2026-10-01",
                covered_until="2026-12-31",
                capped_amount_cents=150000,
            ),
            agreement_admin_headers,
        ),
        ApiErrorId.ERR_COVERAGE_WINDOW_CONFLICT.value,
    )

    rows, _meta = validate_paginated(
        api.list_agreement_coverages(
            scenario["second_agreement"]["id"], agreement_admin_headers
        )
    )
    assert rows == [], (
        f"the rejected line must not have been persisted on the second agreement, got {rows}"
    )


def test_coverage_line_starting_two_days_after_the_previous_covered_until_is_accepted(
    api, agreement_admin_headers
):
    """One clear day of separation satisfies the rule, so the capped line is added to
    the hand-over agreement.

    PRD §2.11: "**Coverage window conflict.** No other coverage line for the same `journal_id` has a closed window that is within one day of the new closed window. Concretely, the new line is rejected when its `covered_from` is on or before the other line's `covered_until` plus one day *and* its `covered_until` is on or after the other line's `covered_from` minus one day — so back-to-back coverage of the same journal on consecutive days is a conflict, not an adjacency. Otherwise `ERR_COVERAGE_WINDOW_CONFLICT` (409). Applies to `POST /transformative-agreements/{id}/coverages`."
    PRD §3.2: "`CAPPED_APC` means the agreement pays up to a per-article ceiling, and for this type `capped_amount_cents` is required and must be greater than zero; for the other two types it must be absent."
    PRD §3.2: "The coverage window must satisfy `covered_until` on or after `covered_from`, and it must lie entirely inside the agreement's own window — on or after the agreement's `effective_from` and strictly before its `effective_until`."
    PRD §2.4: "Two entities are append-only ledger rows that are never revised after insertion, and they therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from an `AgreementCoverage` and from an `EligibilityDetermination`."
    Design: Difficulty/resource_temporal_overlap/coverage_windows_closed_with_one_day_gap_rule
    """
    scenario = _setup_two_adjacent_agreements_with_one_coverage_line()

    coverage = validate_success(
        api.create_agreement_coverage(
            scenario["second_agreement"]["id"],
            create_agreement_coverage_payload(
                scenario["journal"]["id"],
                coverage_type="CAPPED_APC",
                covered_from="2026-10-02",
                covered_until="2026-12-31",
                capped_amount_cents=150000,
            ),
            agreement_admin_headers,
        ),
        expected_status=201,
    )

    assert coverage["id"] is not None, "the separated coverage line must have been created"
    assert coverage["covered_from"] == "2026-10-02", (
        f"covered_from should be 2026-10-02, got {coverage['covered_from']!r}"
    )
    assert coverage["covered_until"] == "2026-12-31", (
        f"covered_until should be 2026-12-31, got {coverage['covered_until']!r}"
    )
    assert coverage["coverage_type"] == "CAPPED_APC", (
        f"coverage_type should be CAPPED_APC, got {coverage['coverage_type']}"
    )
    assert coverage["capped_amount_cents"] == 150000, (
        f"capped_amount_cents should be 150000, got {coverage['capped_amount_cents']}"
    )
    assert_append_only_fields(coverage)

    journal_rows, _journal_meta = validate_paginated(
        api.list_journal_coverages(scenario["journal"]["id"], agreement_admin_headers)
    )
    assert len(journal_rows) == 2, (
        f"the journal is now touched by 2 coverage lines across agreements, "
        f"got {len(journal_rows)}"
    )

    agreement_rows, _agreement_meta = validate_paginated(
        api.list_agreement_coverages(
            scenario["second_agreement"]["id"], agreement_admin_headers
        )
    )
    assert len(agreement_rows) == 1, (
        f"the hand-over agreement holds exactly 1 coverage line, got {len(agreement_rows)}"
    )
