"""Three "only one of these at a time" rules, and what makes room again.

A live consent per subject-and-point pair, an executed contract per vendor, and a
final exposure figure per state.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    HR_ADMIN,
    PRIVACY_OFFICER,
    VENDOR_MANAGER,
    ApiErrorId,
    assert_cents,
    assert_is_null,
    assert_pagination,
    assert_two_decimal_value,
    baseline_with_active_asset,
    consent_payload,
    create_consent,
    create_data_subject,
    create_jurisdiction,
    create_program,
    create_vendor,
    create_vendor_contract,
    current_jurisdiction_version,
    read_assessment,
    read_contract,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DECLINE_REASON = "prefers a manual timesheet"
VOID_REASON = "priced from consent data that has since moved"


def test_a_second_live_consent_for_the_same_pair_is_refused_until_the_first_closes(api):
    """The pair is unique only among non-terminal records.

    PRD §3.6: "No consent record whose status is `SOLICITED`, `GRANTED` or
    `RESOLICIT_REQUIRED` may already exist for the same pairing of `data_subject_id` and
    `asset_id`, else `ERR_CONSENT_ALREADY_EXISTS`. Records that are `DECLINED`, `REVOKED`
    or `EXPIRED` do not block a fresh solicitation."

    PRD §3.7: "An `HRAdministrator` moves a record `SOLICITED` → `DECLINED`, which is
    terminal for that record."

    The refused second solicitation leaves the point with exactly one consent row; once
    the first record is declined the identical request is accepted, and the individual
    then carries two rows — one closed, one open.

    Design: Corner/errors/second_consent_for_the_same_subject_and_asset_pair_rejected
    """
    ctx = baseline_with_active_asset(api, activation_clock=None)
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    set_clock(api, "2026-08-15T00:00:00Z")
    first = create_consent(api, subject["id"], ctx["asset_id"])

    duplicate = api.create_consent_record(
        consent_payload(subject["id"], ctx["asset_id"]), HR_ADMIN
    )

    validate_error(duplicate, ApiErrorId.CONSENT_ALREADY_EXISTS)
    _rows, meta = validate_paginated(
        api.list_consent_records(HR_ADMIN, {"asset_id": ctx["asset_id"]})
    )
    assert_pagination(meta, total_count=1, has_more=False, limit=10, offset=0)

    declined = validate_success(
        api.transition_consent_record(
            first["id"], {"to_status": "DECLINED", "decline_reason": DECLINE_REASON}, HR_ADMIN
        )
    )
    assert declined["status"] == "DECLINED"

    second = validate_success(
        api.create_consent_record(consent_payload(subject["id"], ctx["asset_id"]), HR_ADMIN),
        expected_status=201,
    )
    assert second["status"] == "SOLICITED"

    rows, meta = validate_paginated(
        api.list_consent_records(HR_ADMIN, {"data_subject_id": subject["id"]})
    )
    assert_pagination(meta, total_count=2, has_more=False, limit=10, offset=0)
    assert {row["id"]: row["status"] for row in rows} == {
        first["id"]: "DECLINED",
        second["id"]: "SOLICITED",
    }


def test_a_vendor_may_carry_only_one_executed_contract_at_a_time(api):
    """The second execution is refused by its sibling, not by its own score.

    PRD §3.2: "Execution is refused if any other contract for the same vendor is already
    `EXECUTED` (`ERR_DUPLICATE_EXECUTED_CONTRACT`) — a vendor may carry at most one
    executed contract at a time — and refused if `compliance_score` is below 82.50
    (`ERR_CONTRACT_SCORE_BELOW_FLOOR`)."

    Both contracts carry all four clauses against a received attestation, so both score
    the full 100.00 and neither is anywhere near the floor. The refused one stays
    `APPROVED`, ready to be executed once the first engagement ends.

    Design: Corner/errors/second_executed_contract_for_one_vendor_rejected
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"], attestation_status="RECEIVED")
    first = create_vendor_contract(api, vendor["id"], target_status="EXECUTED")
    second = create_vendor_contract(
        api, vendor["id"], target_status="APPROVED", effective_from="2026-09-01T00:00:00Z"
    )
    assert_two_decimal_value(second["compliance_score"], 100.00, "compliance_score")

    refused = api.transition_vendor_contract(
        second["id"], {"to_status": "EXECUTED"}, VENDOR_MANAGER
    )

    validate_error(refused, ApiErrorId.DUPLICATE_EXECUTED_CONTRACT)

    unchanged = read_contract(api, second["id"])
    assert unchanged["status"] == "APPROVED"
    assert_two_decimal_value(unchanged["compliance_score"], 100.00, "compliance_score")
    assert read_contract(api, first["id"])["status"] == "EXECUTED"

    _rows, meta = validate_paginated(
        api.list_vendor_contracts(
            VENDOR_MANAGER, {"vendor_id": vendor["id"], "status": "EXECUTED"}
        )
    )
    assert_pagination(meta, total_count=1, has_more=False, limit=10, offset=0)


def test_one_state_carries_one_final_figure_until_that_figure_is_voided(api):
    """The second theory of the same state cannot be committed alongside the first.

    PRD §3.9: "no other assessment for the same pairing of `program_id` and
    `jurisdiction_id` may already be `FINAL`, else `ERR_ASSESSMENT_ALREADY_FINAL`"

    PRD §3.9: "A `ComplianceApprover` may void a `FINAL` assessment, `FINAL` → `VOID`, and
    that move is compensating: `exposure_cents` is subtracted back out of the program's
    `pra_exposure_cents`, restoring the pre-finalization value exactly, then `posture` is
    recomputed and the program's `version` is incremented by 1."

    No consent record exists anywhere, so both estimates price at zero and the fiscal
    ceiling is never in play — the refusal is purely about the sibling. Voiding the
    committed figure vacates the slot and the previously refused finalization then
    succeeds, so the check reads only `FINAL` siblings.

    Design: Corner/errors/second_final_assessment_for_the_same_state_rejected
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])

    stacked = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": jurisdiction["id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": current_jurisdiction_version(
                    api, jurisdiction["id"]
                ),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    capped = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": jurisdiction["id"],
                "variant": "PER_SUBJECT_CAPPED",
                "expected_jurisdiction_version": current_jurisdiction_version(
                    api, jurisdiction["id"]
                ),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    assert_cents(stacked["exposure_cents"], 0, "stacked exposure_cents")
    assert_cents(capped["exposure_cents"], 0, "capped exposure_cents")

    committed = validate_success(
        api.transition_exposure_assessment(
            stacked["id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
        )
    )
    assert committed["status"] == "FINAL"
    assert committed["finalized_by_user_id"] == COMPLIANCE_APPROVER["X-User-ID"]

    refused = api.transition_exposure_assessment(
        capped["id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
    )

    validate_error(refused, ApiErrorId.ASSESSMENT_ALREADY_FINAL)
    still_draft = read_assessment(api, capped["id"])
    assert still_draft["status"] == "DRAFT"
    assert_is_null(still_draft["finalized_by_user_id"], "finalized_by_user_id on a refused commit")

    voided = validate_success(
        api.transition_exposure_assessment(
            stacked["id"], {"to_status": "VOID", "void_reason": VOID_REASON}, COMPLIANCE_APPROVER
        )
    )
    assert voided["status"] == "VOID"

    now_permitted = validate_success(
        api.transition_exposure_assessment(
            capped["id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER
        )
    )
    assert now_permitted["status"] == "FINAL"
