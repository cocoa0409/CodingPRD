"""Autoclave evidence and the rolling sterilization verdict."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_sterilization_record,
    compliance_summary,
    create_permitted_establishment,
    create_sterilization_record_payload,
    file_passing_spore_tests,
    file_sterilization_record,
    make_operator_headers,
    read_establishment,
    register_establishment,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
INSP = TEST_USERS["inspector_headers"]


def test_empty_sterilization_window_is_noncompliant_and_three_passes_are_deficient(api):
    """PRD §3.5: "From that candidate set: if the set is empty, the verdict is
    `NONCOMPLIANT`, since no evidence is not the same as clean evidence; if any
    candidate carries `spore_test_result` of `FAIL` or `PENDING`, the verdict is
    `NONCOMPLIANT`, because an unresolved indicator is treated exactly as harshly as a
    failed one; if the number of candidates carrying `PASS` has reached 4 or more, the
    verdict is `COMPLIANT`; and otherwise — one, two or three clean passes and nothing
    outstanding — the verdict is `DEFICIENT`. Exactly four passes is enough for
    compliance; three is not."
    PRD §3.5: "The verdict then feeds the risk figure through a sterilization penalty:
    25 points when the verdict is `NONCOMPLIANT`, 10 points when it is `DEFICIENT`, and
    nothing at all when it is `COMPLIANT`."

    Design: Difficulty/boundary_precision_check/empty_sterilization_window_is_noncompliant_not_vacuously_compliant
    """
    establishment = create_permitted_establishment(
        name="Empty Window Ink", street_address="2 Larch Pl", establishment_type="PIERCING"
    )

    empty = compliance_summary(establishment["id"])
    assert empty["sterilization_compliance_status"] == "NONCOMPLIANT"
    assert empty["sterilization_candidate_count"] == 0
    assert empty["risk_score_provisional"] == 25

    file_passing_spore_tests(
        establishment["id"],
        ["2026-04-05T00:00:00Z", "2026-04-12T00:00:00Z", "2026-04-19T00:00:00Z"],
    )

    three = compliance_summary(establishment["id"])
    assert three["sterilization_compliance_status"] == "DEFICIENT"
    assert three["sterilization_candidate_count"] == 3
    assert three["risk_score_provisional"] == 10


def test_fourth_clean_spore_test_reaches_compliance_and_clears_the_penalty(api):
    """PRD §3.5: "if the number of candidates carrying `PASS` has reached 4 or more,
    the verdict is `COMPLIANT`; and otherwise — one, two or three clean passes and
    nothing outstanding — the verdict is `DEFICIENT`. Exactly four passes is enough for
    compliance; three is not."
    PRD §3.5: "Filing a record immediately recomputes the establishment's
    `sterilization_compliance_status`, then its `risk_score`, then its
    `operating_posture`, and increments the establishment's `version` by one."

    Design: Difficulty/boundary_precision_check/empty_sterilization_window_is_noncompliant_not_vacuously_compliant
    """
    establishment = create_permitted_establishment(
        name="Empty Window Two", street_address="3 Larch Pl", establishment_type="PIERCING"
    )
    file_passing_spore_tests(
        establishment["id"],
        [
            "2026-04-05T00:00:00Z",
            "2026-04-12T00:00:00Z",
            "2026-04-19T00:00:00Z",
            "2026-04-26T00:00:00Z",
        ],
    )

    four = compliance_summary(establishment["id"])
    assert four["sterilization_compliance_status"] == "COMPLIANT"
    assert four["sterilization_candidate_count"] == 4
    assert four["risk_score_provisional"] == 0

    parent = read_establishment(establishment["id"])
    assert parent["sterilization_compliance_status"] == "COMPLIANT"
    assert parent["operating_posture"] == "OPEN"


def test_sterilization_record_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "Sterilization records are the single exception. An autoclave cycle
    record is immutable once filed: it carries only `id` and `created_at`. It has no
    `updated_at` field and no `version` field, and no route in this specification
    mutates one."
    PRD §3.5: "These records are write-once — nothing in the system edits one after it
    is filed, which is why they carry no `updated_at` and no `version`."

    Design: Corner/entities/sterilization_record_is_immutable_with_only_id_and_created_at
    """
    establishment = register_establishment(
        name="Immutable Ink", street_address="5 Fifth St"
    )
    created = validate_success(
        api.create_sterilization_record(
            create_sterilization_record_payload(
                establishment["id"],
                cycle_completed_at="2026-04-15T00:00:00Z",
                spore_test_result="PASS",
                device_serial="AC-77",
            ),
            make_operator_headers(establishment["id"]),
        ),
        201,
    )
    assert_sterilization_record(created)

    stored = validate_success(api.get_sterilization_record(created["id"], INSP), 200)
    assert stored["device_serial"] == "AC-77"
    assert "version" not in stored, "SterilizationRecord must not expose version"
    assert "updated_at" not in stored, "SterilizationRecord must not expose updated_at"
    assert "id" in stored and "created_at" in stored

    parent = read_establishment(establishment["id"])
    assert parent["sterilization_compliance_status"] == "DEFICIENT"


def test_retest_supersedes_the_failed_indicator_and_restores_compliance(api):
    """PRD §3.5: "The candidate set contains every sterilization record of this
    establishment whose `cycle_completed_at` falls inside that window *and* which no
    later record supersedes."
    PRD §3.5: "Superseded records are removed from the candidate set entirely —
    including their failures, which is the whole point of a retest."
    PRD §3.5: "if any candidate carries `spore_test_result` of `FAIL` or `PENDING`, the
    verdict is `NONCOMPLIANT`, because an unresolved indicator is treated exactly as
    harshly as a failed one"
    PRD §3.5: "Sterilization records are readable individually and as a collection
    filterable by `establishment_id`, `supersedes_record_id` and `spore_test_result`."

    Design: Corner/calculations/superseded_fail_spore_test_leaves_the_candidate_set
    """
    establishment = create_permitted_establishment(
        name="Retest Ink", street_address="23 Twentythird St"
    )
    file_passing_spore_tests(
        establishment["id"],
        ["2026-04-05T00:00:00Z", "2026-04-12T00:00:00Z", "2026-04-19T00:00:00Z"],
    )
    failed = file_sterilization_record(
        establishment["id"], "2026-04-26T00:00:00Z", "FAIL", device_serial="AC-5"
    )

    before = compliance_summary(establishment["id"])
    assert before["sterilization_compliance_status"] == "NONCOMPLIANT"
    assert before["sterilization_candidate_count"] == 4

    retest = file_sterilization_record(
        establishment["id"],
        "2026-04-28T00:00:00Z",
        "PASS",
        supersedes_record_id=failed["id"],
        device_serial="AC-5",
    )

    after = compliance_summary(establishment["id"])
    assert after["sterilization_compliance_status"] == "COMPLIANT"
    assert after["sterilization_candidate_count"] == 4
    assert after["sterilization_pass_count"] == 4

    rows, meta = validate_paginated(
        api.list_sterilization_records(
            INSP, params={"supersedes_record_id": failed["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == retest["id"]

    parent = read_establishment(establishment["id"])
    assert parent["risk_score"] == 0
    assert parent["operating_posture"] == "OPEN"


def test_cross_premises_supersede_and_future_cycle_are_rejected(api):
    """PRD §3.5: "That reference must point at a record belonging to the same
    establishment and must point at a record that no other record already supersedes; a
    cross-premises reference or a double-supersede attempt is rejected with
    `ERR_STERILIZATION_SUPERSEDE_INVALID` (HTTP 409), while a reference that resolves
    to nothing at all yields `ERR_STERILIZATION_RECORD_NOT_FOUND` (HTTP 404)."
    PRD §3.5: "A cycle cannot have completed in the future: a `cycle_completed_at`
    after the current logical-clock instant is rejected with
    `ERR_CYCLE_TIMESTAMP_FUTURE` (HTTP 422)."

    Design: Corner/validations/sterilization_supersede_across_establishments_and_future_cycle_rejected
    """
    est_a = register_establishment(
        name="Record Owner Ink", street_address="34 Thirtyfourth St"
    )
    est_b = register_establishment(
        name="Other Owner Ink", street_address="35 Thirtyfifth St"
    )
    record_a = file_sterilization_record(
        est_a["id"], "2026-04-10T00:00:00Z", "PASS", device_serial="AC-20"
    )

    cross = api.create_sterilization_record(
        create_sterilization_record_payload(
            est_b["id"],
            cycle_completed_at="2026-04-20T00:00:00Z",
            spore_test_result="PASS",
            device_serial="AC-21",
            supersedes_record_id=record_a["id"],
        ),
        make_operator_headers(est_b["id"]),
    )
    validate_error(cross, ApiErrorId.ERR_STERILIZATION_SUPERSEDE_INVALID.value)
    assert cross.status_code == 409

    future = api.create_sterilization_record(
        create_sterilization_record_payload(
            est_a["id"],
            cycle_completed_at="2026-06-01T00:00:00Z",
            spore_test_result="PASS",
            device_serial="AC-20",
        ),
        make_operator_headers(est_a["id"]),
    )
    validate_error(future, ApiErrorId.ERR_CYCLE_TIMESTAMP_FUTURE.value)
    assert future.status_code == 422

    _, meta_b = validate_paginated(
        api.list_sterilization_records(INSP, params={"establishment_id": est_b["id"]})
    )
    assert meta_b["total_count"] == 0

    _, meta_a = validate_paginated(
        api.list_sterilization_records(INSP, params={"establishment_id": est_a["id"]})
    )
    assert meta_a["total_count"] == 1
