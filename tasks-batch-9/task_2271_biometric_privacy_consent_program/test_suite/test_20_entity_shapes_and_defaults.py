"""What a freshly written row looks like on the wire.

Declared fields, declared defaults, computed fields and system-minted identity.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    SYSTEM_OPERATOR,
    VENDOR_MANAGER,
    assert_cents,
    assert_common_fields,
    assert_instant_equals,
    assert_is_null,
    assert_program_state,
    create_jurisdiction,
    create_program,
    create_published_policy,
    is_valid_uuid,
    validate_success,
)

WASHINGTON = {
    "state_code": "WA",
    "statute_name": "My Health My Data",
    "private_right_of_action": "LIMITED",
    "damages_model": "STATUTORY_PER_VIOLATION",
    "requires_written_release": False,
    "translation_required": False,
    "required_locales": ["en"],
    "retention_max_days": 730,
    "notice_lead_days": 0,
    "per_violation_negligent_cents": 50000,
    "per_violation_reckless_cents": 200000,
    "cure_period_days": 30,
}


def test_registering_a_program_returns_every_declared_field(api):
    """A brand-new program reports an open posture and a complete inventory.

    PRD §3.1: "A freshly registered program comes up with `posture` at `OPEN`,
    `inventory_completeness_pct` at exactly `100.00` under the empty-inventory
    convention of §3.5, and every derived counter — `consent_gap_count`,
    `gated_asset_count`, `open_deletion_obligation_count` and `pra_exposure_cents`
    — at zero."

    Design: Corner/entities/program_creation_returns_envelope_and_all_declared_fields
    """
    response = api.create_program(
        {
            "org_name": "Northline Retail Group",
            "org_type": "HYBRID",
            "exposure_ceiling_cents": 1093750,
        },
        SYSTEM_OPERATOR,
    )

    program = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]

    assert program["org_name"] == "Northline Retail Group"
    assert program["org_type"] == "HYBRID"
    assert_cents(program["exposure_ceiling_cents"], 1093750, "exposure_ceiling_cents")
    assert_program_state(
        program,
        posture="OPEN",
        consent_gap_count=0,
        gated_asset_count=0,
        open_deletion_obligation_count=0,
        pra_exposure_cents=0,
        inventory_completeness_pct=100.00,
    )
    assert_common_fields(program, expected_version=1)
    assert_instant_equals(program["created_at"], "2026-08-01T00:00:00.000Z", "created_at")
    assert_instant_equals(program["updated_at"], "2026-08-01T00:00:00.000Z", "updated_at")


def test_reading_a_state_profile_echoes_every_stored_statutory_parameter(api):
    """The profile reads back exactly as it was registered.

    PRD §3.1: "Finally it carries the pricing inputs for §3.9:
    `per_violation_negligent_cents` and `per_violation_reckless_cents`, the statutory
    damages per negligent and per reckless or intentional violation;
    `cure_period_days`, the notice-and-cure window in days, where zero means no cure
    right exists; and `statutory_cap_cents`, a hard cap on aggregate exposure for
    that state which defaults to null, meaning uncapped."

    Design: Corner/entities/jurisdiction_retrieval_returns_stored_state_profile
    """
    program = create_program(api)
    created = create_jurisdiction(api, program["id"], **WASHINGTON)

    profile = validate_success(api.get_jurisdiction(created["id"], PRIVACY_OFFICER))

    assert profile["id"] == created["id"]
    assert profile["program_id"] == program["id"]
    assert profile["state_code"] == "WA"
    assert profile["statute_name"] == "My Health My Data"
    assert profile["private_right_of_action"] == "LIMITED"
    assert profile["damages_model"] == "STATUTORY_PER_VIOLATION"
    assert profile["retention_max_days"] == 730
    assert profile["notice_lead_days"] == 0
    assert profile["cure_period_days"] == 30
    assert_is_null(profile["statutory_cap_cents"], "statutory_cap_cents left unsupplied")
    assert_common_fields(profile, expected_version=1)


def test_a_notice_packet_without_an_end_date_takes_its_declared_defaults(api):
    """An omitted `effective_to` leaves the window open-ended.

    PRD §3.4: "A packet begins in `DRAFT` with `published_at` and
    `consent_eligible_from` null."

    PRD §3.4: "and an effective window: `effective_from`, an inclusive ISO 8601 UTC
    start, and an optional `effective_to`, an **exclusive** end that defaults to
    null, where null means the window is open-ended and extends to positive
    infinity."

    Design: Corner/entities/notice_packet_optional_inputs_take_declared_defaults
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    policy = create_published_policy(api, program["id"], [jurisdiction["id"]])

    packet = validate_success(
        api.create_notice_packet(
            {
                "program_id": program["id"],
                "jurisdiction_id": jurisdiction["id"],
                "policy_id": policy["id"],
                "audience": "EMPLOYEE",
                "locales": ["en", "es"],
                "accommodation_channel": "privacy@northline.example",
                "effective_from": "2026-08-01T00:00:00Z",
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )

    assert_is_null(packet["effective_to"], "effective_to left unsupplied")
    assert packet["status"] == "DRAFT"
    assert_is_null(packet["published_at"], "published_at on a draft packet")
    assert_is_null(packet["consent_eligible_from"], "consent_eligible_from on a draft packet")
    assert_common_fields(packet, expected_version=1)
    assert_instant_equals(packet["created_at"], "2026-08-01T00:00:00.000Z", "created_at")


def test_a_vendors_risk_score_is_computed_and_not_taken_from_the_body(api):
    """The score is derived from the disclosed posture, whatever the body says.

    PRD §3.2: "A vendor's `risk_score` is an integer point total, computed at
    registration and recomputed on every attestation change."

    A clean processor contributes the base 20 and nothing else except the 20 points
    its unrequested attestation carries, so the score is 40 even though the request
    body claims zero.

    Design: Corner/entities/vendor_risk_score_computed_client_input_ignored
    """
    program = create_program(api)

    vendor = validate_success(
        api.create_vendor(
            {
                "program_id": program["id"],
                "name": "ClockPoint Systems",
                "sells_biometric_data": False,
                "subprocessor_count": 0,
                "deletion_sla_days": 15,
                "subprocessor_disclosure_complete": True,
                "risk_score": 0,
            },
            VENDOR_MANAGER,
        ),
        expected_status=201,
    )

    assert vendor["risk_score"] == 40, "20 base plus 20 for an unrequested attestation"
    assert vendor["attestation_status"] == "NOT_REQUESTED"
    assert_common_fields(vendor, expected_version=1)


def test_identity_and_version_are_minted_by_the_server(api):
    """Supplied identity fields do not displace the server's own.

    PRD §2.4: "`id` (string): a server-minted UUID. It carries no type prefix and no
    embedded semantics."

    PRD §2.4: "`version` (integer): a counter that increments by exactly 1 on every
    mutation of that row."

    Design: Corner/entities/program_system_fields_generated_and_client_input_ignored
    """
    program = validate_success(
        api.create_program(
            {
                "org_name": "Northline Retail Group",
                "org_type": "EMPLOYER",
                "exposure_ceiling_cents": 500000,
                "id": "prog_client_supplied",
                "version": 99,
                "created_at": "2020-01-01T00:00:00Z",
            },
            SYSTEM_OPERATOR,
        ),
        expected_status=201,
    )

    assert program["id"] != "prog_client_supplied"
    assert is_valid_uuid(program["id"]), "the id is a bare UUID with no type prefix"
    assert program["version"] == 1
    assert_instant_equals(program["created_at"], "2026-08-01T00:00:00.000Z", "created_at")
    assert program["updated_at"] == program["created_at"]

    # The row is genuinely addressable under the id the server chose.
    assert validate_success(api.get_program(program["id"], SYSTEM_OPERATOR))["id"] == program["id"]
