"""Two write endpoints with narrow mandates.

A partial amendment that touches only what it names, and an action endpoint that is a
small state machine in its own right.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    SYSTEM_OPERATOR,
    VENDOR_MANAGER,
    ApiErrorId,
    assert_cents,
    assert_instant_equals,
    assert_is_null,
    attestation_payload,
    create_jurisdiction,
    create_program,
    create_vendor,
    read_vendor,
    set_clock,
    validate_error,
    validate_success,
)


def test_amending_two_statutory_parameters_leaves_the_rest_and_moves_the_pin(api):
    """The amendment writes the two fields it names and bumps the pinned version.

    PRD §3.1: "Statutory profiles are also amendable, since legislatures move: a
    `SystemOperator` may amend `private_right_of_action`, `damages_model`,
    `requires_written_release`, `translation_required`, `required_locales`,
    `retention_max_days`, `notice_lead_days`, `per_violation_negligent_cents`,
    `per_violation_reckless_cents`, `cure_period_days` or `statutory_cap_cents` on an
    existing profile."

    PRD §3.1: "Every amendment increments that profile's own `version` by 1 — the number
    the exposure-assessment pin observes — and, because a statutory retention ceiling
    has just moved, it recomputes the destruction horizon (per §3.5) for every
    collection point in that state whose status is `ACTIVE` or `GATED`."

    PRD §2.4: "`updated_at` (string): the ISO 8601 UTC instant of the most recent
    mutation, in the same format. Every mutation described anywhere in this document
    refreshes it."

    PRD §2.8: "Its value must equal the current `version` of the `Jurisdiction` named on
    the draft; the canonical read of that number is the state profile's single-resource
    read. A mismatch is rejected with `ERR_STALE_JURISDICTION_VERSION` (412)."

    The amendment is performed four days after registration, so the refreshed
    `updated_at` is visibly distinct from the untouched `created_at`; the pin that was
    valid a moment earlier is now stale, and only version 2 is accepted.

    Design: Corner/endpoints/jurisdiction_patch_updates_only_supplied_fields_and_bumps_the_version
    """
    program = create_program(api)
    profile = create_jurisdiction(api, program["id"])
    assert profile["cure_period_days"] == 0
    assert_is_null(profile["statutory_cap_cents"], "statutory_cap_cents left unsupplied")

    set_clock(api, "2026-08-05T00:00:00Z")

    amended = validate_success(
        api.update_jurisdiction(
            profile["id"], {"cure_period_days": 45, "statutory_cap_cents": 250000}, SYSTEM_OPERATOR
        )
    )

    assert amended["cure_period_days"] == 45
    assert_cents(amended["statutory_cap_cents"], 250000, "statutory_cap_cents")
    assert amended["private_right_of_action"] == "FULL"
    assert amended["damages_model"] == "STATUTORY_PER_VIOLATION"
    assert amended["retention_max_days"] == 1095
    assert amended["notice_lead_days"] == 14
    assert amended["required_locales"] == ["en", "es"]
    assert amended["version"] == 2
    assert_instant_equals(amended["created_at"], "2026-08-01T00:00:00.000Z", "created_at")
    assert_instant_equals(amended["updated_at"], "2026-08-05T00:00:00.000Z", "updated_at")

    stale = api.create_exposure_assessment(
        {
            "program_id": program["id"],
            "jurisdiction_id": profile["id"],
            "variant": "PER_VIOLATION_STACKED",
            "expected_jurisdiction_version": 1,
        },
        PRIVACY_OFFICER,
    )
    validate_error(stale, ApiErrorId.STALE_JURISDICTION_VERSION)

    accepted = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": profile["id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": 2,
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "DRAFT"


def test_the_attestation_endpoint_refuses_skipped_steps_and_terminal_moves(api):
    """Neither a jump nor a rollback is accepted, and neither moves the risk score.

    PRD §3.2: "Only the dedicated attestation operation advances it, and only along the
    permitted order `NOT_REQUESTED` → `REQUESTED` → either `RECEIVED` or `REJECTED`, plus
    a re-request edge `REJECTED` → `REQUESTED`. `RECEIVED` is terminal. Any other pair —
    jumping `NOT_REQUESTED` → `RECEIVED`, or backing `RECEIVED` → `REQUESTED` — is
    rejected with `ERR_INVALID_TRANSITION`."

    PRD §3.2: "The attestation itself contributes 20 points while `NOT_REQUESTED`, 10
    points while `REQUESTED`, nothing once `RECEIVED`, and a punitive 35 points when
    `REJECTED`."

    The processor is otherwise clean, so its score is the base 20 plus whatever the
    attestation contributes: 40, then 30, then 20. Each refused call leaves both the
    status and the score exactly where they were, so the refusals are not partial
    writes.

    Design: Corner/endpoints/attestation_endpoint_only_walks_the_declared_order
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"])
    assert vendor["attestation_status"] == "NOT_REQUESTED"
    assert vendor["risk_score"] == 40

    skipped = api.record_attestation(
        vendor["id"], attestation_payload("RECEIVED"), VENDOR_MANAGER
    )
    validate_error(skipped, ApiErrorId.INVALID_TRANSITION)
    unmoved = read_vendor(api, vendor["id"])
    assert unmoved["attestation_status"] == "NOT_REQUESTED"
    assert unmoved["risk_score"] == 40

    requested = validate_success(
        api.record_attestation(vendor["id"], attestation_payload("REQUESTED"), VENDOR_MANAGER)
    )
    assert requested["attestation_status"] == "REQUESTED"
    assert requested["risk_score"] == 30

    received = validate_success(
        api.record_attestation(vendor["id"], attestation_payload("RECEIVED"), VENDOR_MANAGER)
    )
    assert received["attestation_status"] == "RECEIVED"
    assert received["risk_score"] == 20

    backwards = api.record_attestation(
        vendor["id"], attestation_payload("REQUESTED"), VENDOR_MANAGER
    )
    validate_error(backwards, ApiErrorId.INVALID_TRANSITION)
    terminal = read_vendor(api, vendor["id"])
    assert terminal["attestation_status"] == "RECEIVED"
    assert terminal["risk_score"] == 20
