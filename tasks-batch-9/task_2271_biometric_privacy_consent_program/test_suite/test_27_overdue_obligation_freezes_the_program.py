"""One missed destruction certificate, and the whole program stops.

The obligation is created on 1 August, the deadline passes on 31 August, and by
1 September nothing unrelated can move — including the one move that would cure it.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    PRIVACY_OFFICER,
    SYSTEM_OPERATOR,
    VENDOR_MANAGER,
    ApiErrorId,
    assert_instant_equals,
    assert_is_null,
    assert_program_state,
    create_asset,
    create_jurisdiction,
    create_policy,
    create_program,
    create_vendor,
    create_vendor_contract,
    current_program_version,
    read_asset,
    read_contract,
    read_policy,
    read_program,
    set_clock,
    submit_policy,
    validate_error,
    validate_success,
)


def _program_with_an_obligation_and_two_pending_moves(api):
    """A terminated contract with no certificate, plus a policy awaiting
    publication and a collection point awaiting activation."""
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    vendor = create_vendor(api, program["id"], attestation_status="RECEIVED")
    contract = create_vendor_contract(api, vendor["id"], target_status="TERMINATED")
    policy = create_policy(api, program["id"], [jurisdiction["id"]])
    submit_policy(api, policy["id"])
    asset = create_asset(
        api, program["id"], jurisdiction["id"], target_status="CLASSIFIED"
    )
    return {
        "program_id": program["id"],
        "contract_id": contract["id"],
        "contract": contract,
        "policy_id": policy["id"],
        "asset_id": asset["id"],
    }


def test_a_missed_deletion_deadline_freezes_writes_across_unrelated_entities(api):
    """The sweep reports the freeze, and two unrelated moves are refused by it.

    PRD §2.6: "The **overdue deletion obligations** are the subset of those whose
    `deletion_deadline_at` lies strictly before the current logical clock."

    PRD §2.6: "If at least one overdue deletion obligation exists, `posture` becomes
    `FROZEN`."

    PRD §2.6: "`FROZEN` blocks the activation of a `CLASSIFIED` collection point, the
    re-activation of a `GATED` one, policy publication, notice publication, consent
    solicitation and consent granting."

    PRD §3.5: "For every collection point of the program whose status is `ACTIVE` or
    `GATED`, whose `destruction_due_at` is not null, and whose `destruction_due_at` is
    at or before the current clock, the sweep stamps `templates_destroyed_at` and, when
    the point was `ACTIVE`, transitions it to `GATED`."

    PRD §3.5: "The sweep reports what it did as `swept_asset_count`,
    `destroyed_template_count`, `expired_consent_count`,
    `sla_breached_accommodation_count` and the resulting `program_posture`."

    The program holds one `CLASSIFIED` point and no consent records or accommodations
    at all, so the sweep destroys nothing and its only visible output is the posture it
    recomputes. Neither the policy nor the collection point has anything to do with the
    vendor whose certificate is missing; the freeze reaches them anyway. The
    publication carries a currently valid program version pin, so the only thing that
    can be refusing it is the posture, and the point stays `CLASSIFIED`.

    Design: Corner/calculations/overdue_deletion_obligation_propagates_a_freeze_across_the_program
    """
    ctx = _program_with_an_obligation_and_two_pending_moves(api)
    assert_instant_equals(
        ctx["contract"]["deletion_deadline_at"],
        "2026-08-31T00:00:00.000Z",
        "deletion_deadline_at",
    )
    assert_program_state(read_program(api, ctx["program_id"]), posture="RESTRICTED")

    set_clock(api, "2026-09-01T00:00:00Z")

    sweep = validate_success(api.run_destruction_sweep(ctx["program_id"], SYSTEM_OPERATOR))
    assert sweep["program_posture"] == "FROZEN"
    assert sweep["swept_asset_count"] == 0
    assert sweep["destroyed_template_count"] == 0
    assert sweep["expired_consent_count"] == 0
    assert sweep["sla_breached_accommodation_count"] == 0

    assert_program_state(
        read_program(api, ctx["program_id"]),
        posture="FROZEN",
        open_deletion_obligation_count=1,
    )

    blocked_publication = api.publish_policy(
        ctx["policy_id"],
        {"expected_program_version": current_program_version(api, ctx["program_id"])},
        COMPLIANCE_APPROVER,
    )
    validate_error(blocked_publication, ApiErrorId.PROGRAM_POSTURE_BLOCKED)
    assert read_policy(api, ctx["policy_id"])["status"] == "IN_REVIEW"

    blocked_activation = api.transition_asset(
        ctx["asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER
    )
    validate_error(blocked_activation, ApiErrorId.PROGRAM_POSTURE_BLOCKED)
    assert read_asset(api, ctx["asset_id"])["status"] == "CLASSIFIED"


def test_the_one_move_that_would_lift_the_freeze_is_itself_out_of_time(api):
    """Close-out is time-bound, so a late certificate cannot cure the obligation.

    PRD §3.2: "Close-out is also time-bound: it is permitted only while the current
    logical clock is at or before `deletion_deadline_at`, and a clock strictly after
    that instant yields `ERR_DELETION_DEADLINE_MISSED`."

    PRD §2.6: "The **open deletion obligations** are those vendor contracts, reachable
    through the program's vendors, whose status is `TERMINATED` and whose
    `deletion_certificate_ref` is still null; their count is published as
    `open_deletion_obligation_count`."

    The certificate reference is well-formed and present, so only the clock is at
    fault; the contract keeps a null certificate and the program keeps its single open
    — and now permanently overdue — obligation.

    Design: Corner/calculations/overdue_deletion_obligation_propagates_a_freeze_across_the_program
    """
    ctx = _program_with_an_obligation_and_two_pending_moves(api)

    set_clock(api, "2026-09-01T00:00:00Z")

    too_late = api.transition_vendor_contract(
        ctx["contract_id"],
        {"to_status": "CLOSED_OUT", "deletion_certificate_ref": "cert-late-0001"},
        VENDOR_MANAGER,
    )

    validate_error(too_late, ApiErrorId.DELETION_DEADLINE_MISSED)

    unchanged = read_contract(api, ctx["contract_id"])
    assert unchanged["status"] == "TERMINATED"
    assert_is_null(
        unchanged["deletion_certificate_ref"], "deletion_certificate_ref after a late close-out"
    )

    assert_program_state(
        read_program(api, ctx["program_id"]),
        open_deletion_obligation_count=1,
        posture="FROZEN",
    )
