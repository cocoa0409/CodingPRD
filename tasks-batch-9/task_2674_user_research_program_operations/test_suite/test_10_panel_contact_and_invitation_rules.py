"""Panel enrollment, contact fatigue and the invitation gates that guard a pool.

Every test builds its own preconditions: the server is relaunched with an empty
database before each one, and the logical clock starts at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    RESEARCHER_HEADERS,
    RESEARCH_OPS_ADMIN_HEADERS,
    ApiErrorId,
    approve_guide,
    assert_ledger_partition,
    auto_invite_payload,
    close_fielding,
    create_participant_payload,
    create_participant_pool_payload,
    create_pool,
    create_recruitment_payload,
    create_study,
    enroll_participant,
    field_study,
    grant_consent,
    invite,
    is_valid_uuid,
    read_participant,
    read_pool,
    read_study,
    record_no_show,
    schedule,
    screen,
    set_clock,
    setup_approved_request,
    setup_fielding_study,
    setup_invited_recruitments,
    setup_participant_with_one_strike,
    setup_pool_with_participants,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw,
    write_guide,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_STAMP = "2026-08-01T00:00:00.000Z"


def _field_a_study_on_pool(
    api,
    pool_id,
    *,
    incentive_amount_cents=5000,
    target_participant_count=5,
    fielding_start="2026-08-03T00:00:00Z",
    fielding_end="2026-08-21T00:00:00Z",
    guide_label="G1",
):
    """One more study of an existing pool, carried all the way into the field."""
    intake = setup_approved_request(api)
    study = create_study(
        intake["request"]["id"],
        pool_id,
        api,
        incentive_amount_cents=incentive_amount_cents,
        target_participant_count=target_participant_count,
        fielding_start=fielding_start,
        fielding_end=fielding_end,
    )
    write_guide(
        study["id"], api, guide_version_label=guide_label, guide_question_count=6
    )
    approve_guide(study["id"], api)
    return field_study(study["id"], api)


def _invite_response(api, study_id, participant_id):
    return api.create_recruitment(
        study_id, create_recruitment_payload(participant_id), RESEARCHER_HEADERS
    )


# ===========================================================================
# Enrollment and pool identity
# ===========================================================================


def test_participant_enrollment_starts_eligible_with_every_counter_at_zero(api):
    """A participant created from its four declared inputs starts ELIGIBLE with
    zeroed counters, and the pool's participant_count is re-derived in the same
    request.

    PRD 3.2: "They begin `ELIGIBLE`, with `contacts_in_window` at 0,
    `no_show_strikes` at 0 and `last_contacted_at` null. Enrollment raises the
    pool's `participant_count` by one and re-derives the pool's posture, because
    the suppression ratio that feeds posture has just changed denominator."

    PRD 2.7: "When a nested creation carries the parent's identifier in the path,
    the stored foreign-key field on the new row is taken from that path segment
    and not from the body: a participant's `pool_id`, a recruitment's `study_id`,
    an artifact's `recruitment_id`, an evidence link's `finding_id` and a
    follow-up's `readout_id` are all filled in this way."

    PRD 3.2: "A fresh pool opens with `status` `OPEN`, `incentive_reserved_cents`
    and `incentive_paid_cents` both at 0, `incentive_available_cents` equal to the
    whole `incentive_budget_cents`, `settled_study_ids` an empty list,
    `last_estimate_cents` null, and both `participant_count` and
    `suppressed_participant_count` at 0."

    Design: Corner/entities/participant_creation_applies_declared_defaults
    """
    set_clock(CLOCK_START, api)
    pool = create_pool(
        api,
        name="Defaults pool",
        pool_type="INTERNAL_DOGFOOD",
        contact_cap_per_window=2,
        contact_window_days=30,
        incentive_budget_cents=30000,
    )

    created = validate_success(
        api.enroll_participant(
            pool["id"],
            create_participant_payload(
                external_ref="P-900",
                segment="POWER_USER",
                locale="en-US",
                pii_on_file=True,
            ),
            RESEARCH_OPS_ADMIN_HEADERS,
        ),
        201,
    )

    assert created["pool_id"] == pool["id"], (
        f"Expected pool_id {pool['id']} taken from the path, got {created['pool_id']}"
    )
    assert created["external_ref"] == "P-900", (
        f"Expected external_ref P-900, got {created['external_ref']}"
    )
    assert created["segment"] == "POWER_USER", (
        f"Expected segment POWER_USER, got {created['segment']}"
    )
    assert created["locale"] == "en-US", (
        f"Expected locale en-US, got {created['locale']}"
    )
    assert created["pii_on_file"] is True, (
        f"Expected pii_on_file True, got {created['pii_on_file']}"
    )
    assert created["status"] == "ELIGIBLE", (
        f"Expected a fresh participant to be ELIGIBLE, got {created['status']}"
    )
    assert created["contacts_in_window"] == 0, (
        f"Expected contacts_in_window 0, got {created['contacts_in_window']}"
    )
    assert created["no_show_strikes"] == 0, (
        f"Expected no_show_strikes 0, got {created['no_show_strikes']}"
    )
    assert created["last_contacted_at"] is None, (
        f"Expected last_contacted_at null, got {created['last_contacted_at']}"
    )

    after = read_pool(pool["id"], api)
    assert after["participant_count"] == 1, (
        f"Expected participant_count 1 after one enrollment, got {after['participant_count']}"
    )
    assert after["suppressed_participant_count"] == 0, (
        f"Expected suppressed_participant_count 0, got {after['suppressed_participant_count']}"
    )
    assert after["incentive_reserved_cents"] == 0, (
        f"Expected reserved 0 cents, got {after['incentive_reserved_cents']}"
    )
    assert after["incentive_paid_cents"] == 0, (
        f"Expected paid 0 cents, got {after['incentive_paid_cents']}"
    )
    assert after["incentive_available_cents"] == 30000, (
        f"Expected the whole 30000-cent budget available, got {after['incentive_available_cents']}"
    )
    assert after["status"] == "OPEN", (
        f"Expected an unspent pool to be OPEN, got {after['status']}"
    )
    assert_ledger_partition(after)


def test_pool_creation_ignores_a_client_supplied_id_and_version(api):
    """id, created_at, updated_at and version are minted by the server; a create
    body carrying id and version is honoured only for its declared inputs.

    PRD 2.4: "Every persisted resource carries a server-minted `id`: a UUID string
    with no type prefix of any kind. Clients never supply an `id`; a
    client-supplied `id` in a request body is ignored."

    PRD 2.4: "`updated_at` is an ISO 8601 UTC timestamp in the same format as
    `created_at`; at creation it equals `created_at`, and it is refreshed from the
    logical clock on every mutation of that resource. `version` is an integer that
    starts at 1 when the resource is created and increments by exactly 1 on every
    mutation."

    PRD 2.9: "No other endpoint accepts a version field. Fielding a study,
    screening a recruitment, publishing a finding, revoking consent and every
    other mutation are guarded by state preconditions and business rules alone,
    and supplying an unexpected version field to them has no effect."

    PRD 2.5: "Its startup value is exactly `2026-08-01T00:00:00Z`, and it never
    falls back to the host's wall-clock time."

    Design: Corner/entities/participant_pool_system_fields_are_server_minted_and_client_input_ignored
    """
    set_clock(CLOCK_START, api)
    client_supplied_id = "aaaaaaaa-0000-4000-8000-0000000000ff"
    payload = create_participant_pool_payload(
        name="System field pool",
        pool_type="EXTERNAL_PANEL",
        contact_cap_per_window=3,
        contact_window_days=45,
        incentive_budget_cents=80000,
        version=7,
    )
    payload["id"] = client_supplied_id

    created = validate_success(
        api.create_participant_pool(payload, RESEARCH_OPS_ADMIN_HEADERS), 201
    )

    assert created["id"] != client_supplied_id, (
        "Expected the server to mint its own UUID, got the client-supplied "
        f"{client_supplied_id}"
    )
    assert is_valid_uuid(created["id"]), (
        f"Expected a bare UUID with no type prefix, got {created['id']}"
    )
    assert created["version"] == 1, (
        f"Expected version 1 at creation regardless of the body's 7, got {created['version']}"
    )
    assert created["created_at"] == CLOCK_START_STAMP, (
        f"Expected created_at {CLOCK_START_STAMP} from the logical clock, got {created['created_at']}"
    )
    assert created["updated_at"] == created["created_at"], (
        f"Expected updated_at to equal created_at at creation, got {created['updated_at']}"
    )
    assert created["name"] == "System field pool", (
        f"Expected the declared name to survive, got {created['name']}"
    )
    assert created["pool_type"] == "EXTERNAL_PANEL", (
        f"Expected pool_type EXTERNAL_PANEL, got {created['pool_type']}"
    )
    assert created["contact_cap_per_window"] == 3, (
        f"Expected contact_cap_per_window 3, got {created['contact_cap_per_window']}"
    )
    assert created["contact_window_days"] == 45, (
        f"Expected contact_window_days 45, got {created['contact_window_days']}"
    )
    assert created["incentive_budget_cents"] == 80000, (
        f"Expected incentive_budget_cents 80000, got {created['incentive_budget_cents']}"
    )


def test_enrollment_under_an_unknown_pool_returns_pool_not_found(api):
    """A participant is a child of a pool, so an unresolvable parent in the path is
    the parent's own 404 rather than a complaint about the child's body.

    PRD 2.6: "**Existence, resolved in the order the identifiers are listed
    below** — a referenced row that does not exist yields its own 404 code before
    any body validation, state check or business rule is considered:"

    PRD 2.6: "a `ParticipantPool` named in a path segment or in
    `participant_pool_id`, else `ERR_POOL_NOT_FOUND`, on participant enrollment,
    incentive settlement, pool reads, the pool's participant listing, study
    creation and the study listing;"

    PRD 2.7: "Path parameters are always resolved **left to right**, and the first
    segment that fails to resolve determines the error."

    Design: Corner/entities/participant_creation_under_unknown_pool_returns_pool_not_found
    """
    set_clock(CLOCK_START, api)

    response = api.enroll_participant(
        NON_EXISTENT_UUID,
        create_participant_payload(
            external_ref="P-001",
            segment="POWER_USER",
            locale="en-US",
            pii_on_file=True,
        ),
        RESEARCH_OPS_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.POOL_NOT_FOUND.value)
    validate_error(
        api.list_pool_participants(NON_EXISTENT_UUID, RESEARCH_OPS_ADMIN_HEADERS),
        ApiErrorId.POOL_NOT_FOUND.value,
    )


# ===========================================================================
# The batch selector's ranking
# ===========================================================================


def test_auto_invite_ranks_candidates_by_contacts_then_created_at(api):
    """The selector's ranking is visible in the response order: the participant
    already carrying one contact is placed behind both untouched participants,
    which themselves come back in created_at order.

    PRD 3.4: "A participant is a candidate when their `pool_id` equals the study's
    `participant_pool_id`, their derived posture is `ELIGIBLE`, their `segment` is
    exactly equal to the study's `required_segment` from the screening rubric,
    their `no_show_strikes` is below 2, their `contacts_in_window` is below the
    pool's `contact_cap_per_window`, and no recruitment already exists for this
    study naming them."

    PRD 3.4: "Candidates are ranked by `contacts_in_window` ascending, then by
    `no_show_strikes` ascending, then by `created_at` ascending — the last key is
    unique per participant row and so the ranking is total, with no randomness
    anywhere."

    PRD 3.2: "A participant's `contacts_in_window` is the number of recruitment
    rows naming that participant whose `created_at` falls **strictly after** the
    instant obtained by subtracting `contact_window_days` days from the current
    logical clock, and at or before the clock's current value."

    Design: Corner/calculations/auto_invite_ranks_candidates_by_contacts_then_created_at
    """
    set_clock(CLOCK_START, api)
    panel = setup_pool_with_participants(
        api,
        participant_count=3,
        name="Selector pool",
        pool_type="CUSTOMER_LIST",
        contact_cap_per_window=2,
        contact_window_days=30,
        incentive_budget_cents=100000,
    )
    pool_id = panel["pool"]["id"]
    first, second, third = panel["participants"]

    study_a = _field_a_study_on_pool(
        api,
        pool_id,
        incentive_amount_cents=5000,
        target_participant_count=3,
        fielding_start="2026-08-03T00:00:00Z",
        fielding_end="2026-08-21T00:00:00Z",
        guide_label="GA",
    )
    invite(study_a["id"], first["id"], api)
    study_b = _field_a_study_on_pool(
        api,
        pool_id,
        incentive_amount_cents=5000,
        target_participant_count=3,
        fielding_start="2026-08-04T00:00:00Z",
        fielding_end="2026-08-20T00:00:00Z",
        guide_label="GB",
    )

    before = read_pool(pool_id, api)
    assert before["incentive_reserved_cents"] == 5000, (
        f"Setup drift: expected 5000 reserved by the study A invitation, got {before['incentive_reserved_cents']}"
    )
    assert before["incentive_available_cents"] == 95000, (
        f"Setup drift: expected 95000 available before the batch, got {before['incentive_available_cents']}"
    )
    assert before["status"] == "OPEN", (
        f"Setup drift: expected the pool OPEN at utilization 0.05, got {before['status']}"
    )
    assert read_participant(first["id"], api)["contacts_in_window"] == 1, (
        "Setup drift: the first participant should carry exactly one prior contact"
    )

    rows = validate_success(
        api.auto_invite(study_b["id"], auto_invite_payload(3), RESEARCH_OPS_ADMIN_HEADERS),
        201,
    )

    assert len(rows) == 3, f"Expected 3 rows for count 3, got {len(rows)}"
    ordered = [row["participant_id"] for row in rows]
    assert ordered == [second["id"], third["id"], first["id"]], (
        "Expected the two zero-contact participants in created_at order ahead of "
        f"the one already contacted, got {ordered}"
    )
    for row in rows:
        assert row["status"] == "INVITED", (
            f"Expected status INVITED on every batch row, got {row['status']}"
        )
        assert row["incentive_state"] == "RESERVED", (
            f"Expected incentive_state RESERVED, got {row['incentive_state']}"
        )
        assert row["reserved_cents"] == 5000, (
            f"Expected 5000 reserved cents with no surcharge below 0.50 utilization, got {row['reserved_cents']}"
        )

    after = read_pool(pool_id, api)
    assert after["incentive_reserved_cents"] == 20000, (
        f"Expected 20000 reserved after four 5000-cent reservations, got {after['incentive_reserved_cents']}"
    )
    assert after["incentive_available_cents"] == 80000, (
        f"Expected 80000 available, got {after['incentive_available_cents']}"
    )
    assert after["status"] == "OPEN", (
        f"Expected the pool still OPEN at utilization 0.20, got {after['status']}"
    )
    assert_ledger_partition(after)

    study_b_after = read_study(study_b["id"], api)
    assert study_b_after["invited_count"] == 3, (
        f"Expected invited_count 3, got {study_b_after['invited_count']}"
    )
    assert study_b_after["recruitment_status"] == "RECRUITING", (
        f"Expected recruitment_status RECRUITING, got {study_b_after['recruitment_status']}"
    )

    first_after = read_participant(first["id"], api)
    assert first_after["contacts_in_window"] == 2, (
        f"Expected contacts_in_window 2, got {first_after['contacts_in_window']}"
    )
    assert first_after["status"] == "COOLDOWN", (
        f"Expected COOLDOWN at the cap of 2, got {first_after['status']}"
    )
    for participant in (second, third):
        row = read_participant(participant["id"], api)
        assert row["contacts_in_window"] == 1, (
            f"Expected contacts_in_window 1, got {row['contacts_in_window']}"
        )
        assert row["status"] == "ELIGIBLE", (
            f"Expected still ELIGIBLE below the cap of 2, got {row['status']}"
        )


# ===========================================================================
# Enrollment and invitation refusals
# ===========================================================================


def test_duplicate_external_ref_is_refused_inside_one_pool_only(api):
    """The uniqueness scope of external_ref is the pool: the same reference is
    refused inside one pool and accepted in a second.

    PRD 3.2: "The `ResearchOpsAdmin` supplies an `external_ref` — the person's
    handle in the source system, non-empty and unique inside the pool, with a
    collision refused as `ERR_DUPLICATE_EXTERNAL_REF` — a non-empty `segment`
    label describing their behaviour, a non-empty BCP-47 `locale`, and a
    `pii_on_file` boolean recording whether directly identifying data is held for
    them (true when omitted)."

    Design: Corner/validations/duplicate_external_ref_inside_one_pool_is_rejected
    """
    set_clock(CLOCK_START, api)
    pool_a = create_pool(
        api,
        name="Dup pool A",
        pool_type="CUSTOMER_LIST",
        contact_cap_per_window=2,
        contact_window_days=30,
        incentive_budget_cents=100000,
    )
    pool_b = create_pool(
        api,
        name="Dup pool B",
        pool_type="EXTERNAL_PANEL",
        contact_cap_per_window=2,
        contact_window_days=30,
        incentive_budget_cents=100000,
    )
    enroll_participant(
        pool_a["id"], api, external_ref="P-A01", segment="POWER_USER", locale="en-US"
    )
    pool_a_before = read_pool(pool_a["id"], api)

    repeat = api.enroll_participant(
        pool_a["id"],
        create_participant_payload(
            external_ref="P-A01",
            segment="NEW_USER",
            locale="de-DE",
            pii_on_file=False,
        ),
        RESEARCH_OPS_ADMIN_HEADERS,
    )
    validate_error(repeat, ApiErrorId.DUPLICATE_EXTERNAL_REF.value)

    rows, meta = validate_paginated(
        api.list_pool_participants(pool_a["id"], RESEARCH_OPS_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"Expected the refused enrollment to leave one participant, got {meta['total_count']}"
    )
    assert len(rows) == 1, f"Expected one row in pool A, got {len(rows)}"

    accepted = validate_success(
        api.enroll_participant(
            pool_b["id"],
            create_participant_payload(
                external_ref="P-A01", segment="POWER_USER", locale="en-US"
            ),
            RESEARCH_OPS_ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["external_ref"] == "P-A01", (
        f"Expected the same reference to be accepted under a second pool, got {accepted['external_ref']}"
    )
    assert accepted["pool_id"] == pool_b["id"], (
        f"Expected the new row under pool B, got {accepted['pool_id']}"
    )

    pool_a_after = read_pool(pool_a["id"], api)
    assert pool_a_after["participant_count"] == 1, (
        f"Expected pool A's participant_count still 1, got {pool_a_after['participant_count']}"
    )
    assert pool_a_after["version"] == pool_a_before["version"], (
        f"Expected pool A's version untouched by the refusal, got {pool_a_after['version']} "
        f"instead of {pool_a_before['version']}"
    )


def test_contact_cap_blocks_the_second_invitation_in_the_window(api):
    """The counter is pool-wide, not study-wide: a participant already contacted in
    one study of the pool is refused in a second study once the cap is reached,
    while an untouched participant of the same pool goes through.

    PRD 3.4: "And their `contacts_in_window` must still be strictly below the
    pool's `contact_cap_per_window`, else `ERR_CONTACT_CAP_EXCEEDED`."

    PRD 3.2: "A participant's `contacts_in_window` is the number of recruitment
    rows naming that participant whose `created_at` falls **strictly after** the
    instant obtained by subtracting `contact_window_days` days from the current
    logical clock, and at or before the clock's current value."

    PRD 3.2: "Otherwise, if `contacts_in_window` has reached the pool's
    `contact_cap_per_window`, they are in `COOLDOWN`."

    Design: Corner/validations/contact_cap_blocks_the_second_invitation_in_the_window
    """
    set_clock(CLOCK_START, api)
    panel = setup_pool_with_participants(
        api,
        participant_count=2,
        name="Cap pool",
        pool_type="CUSTOMER_LIST",
        contact_cap_per_window=1,
        contact_window_days=30,
        incentive_budget_cents=100000,
    )
    pool_id = panel["pool"]["id"]
    first, second = panel["participants"]

    study_a = _field_a_study_on_pool(
        api,
        pool_id,
        target_participant_count=3,
        fielding_start="2026-08-03T00:00:00Z",
        fielding_end="2026-08-21T00:00:00Z",
        guide_label="GA",
    )
    study_b = _field_a_study_on_pool(
        api,
        pool_id,
        target_participant_count=3,
        fielding_start="2026-08-04T00:00:00Z",
        fielding_end="2026-08-20T00:00:00Z",
        guide_label="GB",
    )
    invite(study_a["id"], first["id"], api)

    exhausted = read_participant(first["id"], api)
    assert exhausted["contacts_in_window"] == 1, (
        f"Setup drift: expected one contact against a cap of 1, got {exhausted['contacts_in_window']}"
    )
    assert exhausted["status"] == "COOLDOWN", (
        f"Setup drift: expected COOLDOWN at the cap, got {exhausted['status']}"
    )

    refused = _invite_response(api, study_b["id"], first["id"])
    validate_error(refused, ApiErrorId.CONTACT_CAP_EXCEEDED.value)

    unchanged = read_participant(first["id"], api)
    assert unchanged["status"] == "COOLDOWN", (
        f"Expected the refused call to leave COOLDOWN in place, got {unchanged['status']}"
    )
    assert unchanged["contacts_in_window"] == 1, (
        f"Expected contacts_in_window still 1 after the refusal, got {unchanged['contacts_in_window']}"
    )

    accepted = validate_success(
        _invite_response(api, study_b["id"], second["id"]), 201
    )
    assert accepted["participant_id"] == second["id"], (
        "Expected the untouched participant of the same pool to be invitable, got "
        f"{accepted['participant_id']}"
    )
    assert accepted["status"] == "INVITED", (
        f"Expected status INVITED, got {accepted['status']}"
    )

    pool_after = read_pool(pool_id, api)
    assert pool_after["incentive_reserved_cents"] == 10000, (
        "Expected only the two accepted invitations to reserve money, got "
        f"{pool_after['incentive_reserved_cents']}"
    )
    assert_ledger_partition(pool_after)

    study_b_after = read_study(study_b["id"], api)
    assert study_b_after["invited_count"] == 1, (
        f"Expected study B's invited_count 1, got {study_b_after['invited_count']}"
    )


def test_duplicate_recruitment_for_the_same_pair_is_rejected(api):
    """The duplicate check is on the existence of a row for the study-and-participant
    pair, so it fires ahead of the contact cap and survives a withdrawal.

    PRD 3.4: "For a named invitation three participant-level rules follow, in this
    order. A recruitment must not already exist for this study-and-participant
    pair, else `ERR_DUPLICATE_RECRUITMENT`."

    PRD 3.2: "Every recruitment counts regardless of how it ended — a withdrawn
    invitation, a screen-out and a no-show all consume contact budget for the full
    length of the window, because the person was contacted whether or not the
    session happened."

    PRD 2.10: "Withdrawing an invitation moves exactly the same number of cents —
    the recruitment's stored `reserved_cents`, not a recomputed amount — from
    reserved back to available."

    Design: Corner/validations/duplicate_recruitment_for_the_same_pair_is_rejected
    """
    set_clock(CLOCK_START, api)
    ctx = setup_invited_recruitments(
        api,
        participant_count=1,
        invite_count=1,
        target_participant_count=3,
        incentive_amount_cents=5000,
        pool_overrides={
            "name": "Dup invite pool",
            "pool_type": "CUSTOMER_LIST",
            "contact_cap_per_window": 2,
            "contact_window_days": 30,
            "incentive_budget_cents": 100000,
        },
    )
    study_id = ctx["study"]["id"]
    participant_id = ctx["participants"][0]["id"]
    recruitment_id = ctx["recruitments"][0]["id"]

    assert ctx["pool"]["incentive_reserved_cents"] == 5000, (
        f"Setup drift: expected 5000 reserved by the first invitation, got {ctx['pool']['incentive_reserved_cents']}"
    )

    immediate_repeat = _invite_response(api, study_id, participant_id)
    validate_error(immediate_repeat, ApiErrorId.DUPLICATE_RECRUITMENT.value)

    withdraw(recruitment_id, api, reason="Participant asked to be re-approached later")

    after_withdrawal = _invite_response(api, study_id, participant_id)
    validate_error(after_withdrawal, ApiErrorId.DUPLICATE_RECRUITMENT.value)

    pool_after = read_pool(ctx["pool"]["id"], api)
    assert pool_after["incentive_reserved_cents"] == 0, (
        "Expected the withdrawal to release the only reservation, got "
        f"{pool_after['incentive_reserved_cents']}"
    )
    assert_ledger_partition(pool_after)

    study_after = read_study(study_id, api)
    assert study_after["invited_count"] == 1, (
        f"Expected invited_count 1 throughout, got {study_after['invited_count']}"
    )


# ===========================================================================
# The derived posture of a pool as an invitation gate
# ===========================================================================


def test_closed_pool_refuses_further_invitations(api):
    """The fourth reservation carries its surcharge, drives utilization to 0.9643 and
    auto-closes the pool, and the closed-pool guard then pre-empts the fiscal
    business rule that the next reservation would also have failed.

    PRD 3.4: "First, read the pool's utilization **from the state before this
    reservation is applied**: committed money, meaning `incentive_reserved_cents`
    plus `incentive_paid_cents`, divided by `incentive_budget_cents`. From that
    pre-call utilization read a scarcity surcharge percentage: below 0.50 the
    surcharge is zero; from 0.50 up to but not including 0.80 it is five percent;
    at 0.80 or above it is ten percent. Then take the study's
    `incentive_amount_cents`, multiply it by the surcharge percentage, round that
    surcharge term **up** to the next whole cent, and add it to the base — the sum
    is the recruitment's `reserved_cents`."

    PRD 3.2: "The derivation then reads, in this order: at a utilization of **0.95
    or more** the pool is `CLOSED`; otherwise, at a utilization of **0.80 or
    more**, *or* with a suppression ratio strictly **greater than 0.50**, it is
    `RESTRICTED`; otherwise it is `OPEN`."

    PRD 3.2: "While a pool is `CLOSED`, **every** recruitment-creating operation
    against it is refused with `ERR_POOL_CLOSED`, single and batch alike."

    PRD 2.6: "**Remaining state-machine guards, in this order** —
    `ERR_REVISION_LIMIT_REACHED` (409) on resubmit; `ERR_RECRUITMENT_CLOSED` (409)
    on both invitation endpoints; `ERR_POOL_CLOSED` (409) on both invitation
    endpoints; `ERR_POOL_RESTRICTED` (409) on batch invitation only;
    `ERR_SETTLEMENT_NOT_PERMITTED` (409) and then `ERR_ALREADY_SETTLED` (409) on
    incentive settlement; `ERR_NO_PUBLISHED_FINDINGS` (409) on readout delivery."

    Design: Corner/validations/closed_pool_refuses_further_invitations
    """
    set_clock(CLOCK_START, api)
    ctx = setup_fielding_study(
        api,
        participant_count=5,
        target_participant_count=5,
        incentive_amount_cents=5000,
        pool_overrides={
            "name": "Tight pool",
            "pool_type": "CUSTOMER_LIST",
            "contact_cap_per_window": 2,
            "contact_window_days": 30,
            "incentive_budget_cents": 21000,
        },
    )
    study_id = ctx["study"]["id"]
    participants = ctx["participants"]

    for index in range(3):
        row = validate_success(
            _invite_response(api, study_id, participants[index]["id"]), 201
        )
        assert row["reserved_cents"] == 5000, (
            f"Expected invitation {index + 1} to reserve the bare 5000 cents below "
            f"0.50 utilization, got {row['reserved_cents']}"
        )

    fourth = validate_success(
        _invite_response(api, study_id, participants[3]["id"]), 201
    )
    assert fourth["reserved_cents"] == 5250, (
        "Expected 5000 plus a five-percent surcharge of 250 at pre-utilization "
        f"0.7143, got {fourth['reserved_cents']}"
    )

    before_fifth = read_pool(ctx["pool"]["id"], api)
    assert before_fifth["incentive_reserved_cents"] == 20250, (
        f"Setup drift: expected 20250 reserved, got {before_fifth['incentive_reserved_cents']}"
    )
    assert before_fifth["incentive_available_cents"] == 750, (
        f"Setup drift: expected 750 available, got {before_fifth['incentive_available_cents']}"
    )
    assert before_fifth["status"] == "CLOSED", (
        "Expected CLOSED at utilization 20250/21000, which is at or above 0.95, got "
        f"{before_fifth['status']}"
    )
    assert_ledger_partition(before_fifth)

    fifth = _invite_response(api, study_id, participants[4]["id"])
    validate_error(fifth, ApiErrorId.POOL_CLOSED.value)

    study_after = read_study(study_id, api)
    assert study_after["invited_count"] == 4, (
        f"Expected invited_count 4, got {study_after['invited_count']}"
    )
    fifth_participant = read_participant(participants[4]["id"], api)
    assert fifth_participant["contacts_in_window"] == 0, (
        "Expected the refused participant to carry no contact, got "
        f"{fifth_participant['contacts_in_window']}"
    )


def test_restricted_pool_refuses_the_batch_but_permits_a_named_invitation(api):
    """RESTRICTED is a partial capability: the batch selector is refused while a
    named invitation still lands, and that invitation tips the pool into CLOSED
    where the batch is refused on the closed-pool code instead.

    PRD 3.4: "Batch invitation adds one further posture condition — the pool must
    be `OPEN`, so a `RESTRICTED` pool rejects the batch with
    `ERR_POOL_RESTRICTED` while still accepting named invitations."

    PRD 3.2: "While a pool is `RESTRICTED`, batch invitation is refused with
    `ERR_POOL_RESTRICTED` but naming a single participant still works — the intent
    is to stop the platform spending the last fifth of a budget automatically
    while leaving a researcher free to place a specific, deliberate invitation."

    PRD 2.6: "And a batch invitation against a `CLOSED` pool fails with
    `ERR_POOL_CLOSED` rather than `ERR_POOL_RESTRICTED`, because the closed-pool
    check precedes the restricted-pool check."

    Design: Corner/validations/restricted_pool_refuses_batch_but_permits_single_invitation
    """
    set_clock(CLOCK_START, api)
    panel = setup_pool_with_participants(
        api,
        participant_count=4,
        name="Ladder pool",
        pool_type="CUSTOMER_LIST",
        contact_cap_per_window=2,
        contact_window_days=30,
        incentive_budget_cents=100000,
    )
    pool_id = panel["pool"]["id"]
    participants = panel["participants"]

    study_a = _field_a_study_on_pool(
        api,
        pool_id,
        incentive_amount_cents=30000,
        target_participant_count=5,
        fielding_start="2026-08-03T00:00:00Z",
        fielding_end="2026-08-21T00:00:00Z",
        guide_label="GA",
    )
    study_b = _field_a_study_on_pool(
        api,
        pool_id,
        incentive_amount_cents=5000,
        target_participant_count=5,
        fielding_start="2026-08-04T00:00:00Z",
        fielding_end="2026-08-20T00:00:00Z",
        guide_label="GB",
    )

    expected_reservations = [30000, 30000, 31500]
    for index, expected in enumerate(expected_reservations):
        row = validate_success(
            _invite_response(api, study_a["id"], participants[index]["id"]), 201
        )
        assert row["reserved_cents"] == expected, (
            f"Expected reservation {index + 1} of study A to cost {expected} cents, "
            f"got {row['reserved_cents']}"
        )

    restricted = read_pool(pool_id, api)
    assert restricted["incentive_reserved_cents"] == 91500, (
        f"Setup drift: expected 91500 reserved, got {restricted['incentive_reserved_cents']}"
    )
    assert restricted["incentive_available_cents"] == 8500, (
        f"Setup drift: expected 8500 available, got {restricted['incentive_available_cents']}"
    )
    assert restricted["status"] == "RESTRICTED", (
        "Expected RESTRICTED at utilization 91500/100000, inside the 0.80-to-0.95 "
        f"band, got {restricted['status']}"
    )
    assert_ledger_partition(restricted)

    refused_batch = api.auto_invite(
        study_b["id"], auto_invite_payload(1), RESEARCH_OPS_ADMIN_HEADERS
    )
    validate_error(refused_batch, ApiErrorId.POOL_RESTRICTED.value)

    named = validate_success(
        _invite_response(api, study_b["id"], participants[3]["id"]), 201
    )
    assert named["reserved_cents"] == 5500, (
        "Expected 5000 plus a ten-percent surcharge of 500 at pre-utilization "
        f"0.915, got {named['reserved_cents']}"
    )

    closed = read_pool(pool_id, api)
    assert closed["incentive_reserved_cents"] == 97000, (
        f"Expected 97000 reserved after the named invitation, got {closed['incentive_reserved_cents']}"
    )
    assert closed["status"] == "CLOSED", (
        "Expected CLOSED at utilization 97000/100000, which is at or above 0.95, "
        f"got {closed['status']}"
    )
    assert_ledger_partition(closed)

    refused_again = api.auto_invite(
        study_b["id"], auto_invite_payload(1), RESEARCH_OPS_ADMIN_HEADERS
    )
    validate_error(refused_again, ApiErrorId.POOL_CLOSED.value)


# ===========================================================================
# The selector's own exclusions and precedence against them
# ===========================================================================


def test_auto_invite_with_an_empty_candidate_set_returns_the_selector_error(api):
    """The pool is not empty and the budget is untouched: the only member already
    has a recruitment in this study, which is the selector's own exclusion clause,
    and a batch that creates nothing fails and leaves no trace.

    PRD 3.4: "A participant is a candidate when their `pool_id` equals the study's
    `participant_pool_id`, their derived posture is `ELIGIBLE`, their `segment` is
    exactly equal to the study's `required_segment` from the screening rubric,
    their `no_show_strikes` is below 2, their `contacts_in_window` is below the
    pool's `contact_cap_per_window`, and no recruitment already exists for this
    study naming them."

    PRD 3.4: "If the candidate set is empty the whole call fails with
    `ERR_NO_ELIGIBLE_PARTICIPANTS` (HTTP 422)."

    Design: Corner/validations/auto_invite_with_an_empty_candidate_set_returns_the_selector_error
    """
    set_clock(CLOCK_START, api)
    ctx = setup_invited_recruitments(
        api,
        participant_count=1,
        invite_count=1,
        target_participant_count=3,
        incentive_amount_cents=5000,
        pool_overrides={
            "name": "Thin pool",
            "pool_type": "CUSTOMER_LIST",
            "contact_cap_per_window": 2,
            "contact_window_days": 30,
            "incentive_budget_cents": 100000,
        },
    )
    study_id = ctx["study"]["id"]
    pool_before = read_pool(ctx["pool"]["id"], api)
    assert pool_before["incentive_reserved_cents"] == 5000, (
        f"Setup drift: expected 5000 reserved, got {pool_before['incentive_reserved_cents']}"
    )
    assert pool_before["status"] == "OPEN", (
        f"Setup drift: expected the pool OPEN at utilization 0.05, got {pool_before['status']}"
    )

    response = api.auto_invite(
        study_id, auto_invite_payload(1), RESEARCH_OPS_ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.NO_ELIGIBLE_PARTICIPANTS.value)

    pool_after = read_pool(ctx["pool"]["id"], api)
    assert pool_after["incentive_reserved_cents"] == 5000, (
        f"Expected reserved untouched at 5000, got {pool_after['incentive_reserved_cents']}"
    )
    assert pool_after["incentive_available_cents"] == 95000, (
        f"Expected available untouched at 95000, got {pool_after['incentive_available_cents']}"
    )
    assert pool_after["status"] == "OPEN", (
        f"Expected the pool still OPEN, got {pool_after['status']}"
    )
    assert pool_after["version"] == pool_before["version"], (
        f"Expected the pool's version unchanged by a failed batch, got "
        f"{pool_after['version']} instead of {pool_before['version']}"
    )
    assert_ledger_partition(pool_after)

    study_after = read_study(study_id, api)
    assert study_after["invited_count"] == 1, (
        f"Expected invited_count 1, got {study_after['invited_count']}"
    )
    assert study_after["recruitment_status"] == "RECRUITING", (
        f"Expected recruitment_status RECRUITING, got {study_after['recruitment_status']}"
    )

    _, meta = validate_paginated(
        api.list_recruitments(RESEARCH_OPS_ADMIN_HEADERS, {"study_id": study_id})
    )
    assert meta["total_count"] == 1, (
        f"Expected no recruitment row from the failed batch, got {meta['total_count']} in total"
    )


def test_unknown_participant_is_resolved_before_the_contact_cap_is_read(api):
    """Existence resolution precedes every state-dependent check, so an unknown
    participant id against a pool whose cap is already exhausted answers with the
    404 rather than the cap error.

    PRD 2.6: "Because a single request can violate several rules at once, the
    platform evaluates checks in a fixed precedence and returns the **first**
    failure it finds."

    PRD 2.6: "**Existence, resolved in the order the identifiers are listed
    below** — a referenced row that does not exist yields its own 404 code before
    any body validation, state check or business rule is considered:"

    PRD 2.6: "a `Participant` named in a path segment or in `participant_id`, else
    `ERR_PARTICIPANT_NOT_FOUND`, on participant reads, single-participant
    invitation, consent creation, the recruitment listing and the consent-record
    listing;"

    PRD 3.4: "For a named invitation three participant-level rules follow, in this
    order. A recruitment must not already exist for this study-and-participant
    pair, else `ERR_DUPLICATE_RECRUITMENT`."

    Design: Corner/validations/unknown_participant_is_resolved_before_the_contact_cap_is_read
    """
    set_clock(CLOCK_START, api)
    ctx = setup_invited_recruitments(
        api,
        participant_count=1,
        invite_count=1,
        target_participant_count=3,
        incentive_amount_cents=5000,
        pool_overrides={
            "name": "Order pool",
            "pool_type": "CUSTOMER_LIST",
            "contact_cap_per_window": 1,
            "contact_window_days": 30,
            "incentive_budget_cents": 100000,
        },
    )
    study_id = ctx["study"]["id"]
    known = read_participant(ctx["participants"][0]["id"], api)
    assert known["contacts_in_window"] == 1, (
        f"Setup drift: expected the cap of 1 to be exhausted, got {known['contacts_in_window']}"
    )
    assert known["status"] == "COOLDOWN", (
        f"Setup drift: expected COOLDOWN at the cap, got {known['status']}"
    )

    unknown = _invite_response(api, study_id, NON_EXISTENT_UUID)
    validate_error(unknown, ApiErrorId.PARTICIPANT_NOT_FOUND.value)

    exhausted_pair = _invite_response(api, study_id, known["id"])
    validate_error(exhausted_pair, ApiErrorId.DUPLICATE_RECRUITMENT.value)

    pool_after = read_pool(ctx["pool"]["id"], api)
    assert pool_after["incentive_reserved_cents"] == 5000, (
        "Expected neither failure to touch the ledger, got reserved "
        f"{pool_after['incentive_reserved_cents']}"
    )
    assert_ledger_partition(pool_after)


def test_suppressed_participant_cannot_be_invited(api):
    """Suppression is earned across studies of one pool: two no-shows in two studies
    make the participant SUPPRESSED, a third named invitation elsewhere is refused,
    and the selector drops them from the candidate set silently.

    PRD 3.2: "If `no_show_strikes` has reached **2**, the participant is
    `SUPPRESSED`."

    PRD 3.2: "`SUPPRESSED` is absorbing: whether the participant was `ELIGIBLE` or
    in `COOLDOWN` when their second strike landed, the transition into
    `SUPPRESSED` is one-way, it increments the pool's
    `suppressed_participant_count` and then re-runs the pool's posture derivation,
    and every future invitation naming them is refused with
    `ERR_PARTICIPANT_SUPPRESSED`."

    PRD 3.2: "Note the asymmetry between the two thresholds — utilization is
    compared inclusively at its band edges, whereas the suppression ratio must
    strictly exceed one half, so a pool with exactly half its participants
    suppressed and low utilization stays `OPEN`."

    Design: Corner/validations/suppressed_participant_cannot_be_invited
    """
    set_clock(CLOCK_START, api)
    ctx = setup_participant_with_one_strike(
        api,
        participant_count=2,
        invite_count=1,
        target_participant_count=3,
        incentive_amount_cents=5000,
        scheduled_start="2026-08-05T10:00:00Z",
        scheduled_end="2026-08-05T11:00:00Z",
        pool_overrides={
            "name": "Suppression pool",
            "pool_type": "CUSTOMER_LIST",
            "contact_cap_per_window": 5,
            "contact_window_days": 30,
            "incentive_budget_cents": 100000,
        },
    )
    pool_id = ctx["pool"]["id"]
    struck, untouched = ctx["participants"][0], ctx["participants"][1]
    assert struck["no_show_strikes"] == 1, (
        f"Setup drift: expected one strike after study A, got {struck['no_show_strikes']}"
    )
    close_fielding(ctx["study"]["id"], api)

    study_b = _field_a_study_on_pool(
        api,
        pool_id,
        incentive_amount_cents=5000,
        target_participant_count=3,
        fielding_start="2026-08-04T00:00:00Z",
        fielding_end="2026-08-20T00:00:00Z",
        guide_label="GB",
    )
    grant_consent(struck["id"], study_b["id"], api, scopes=["RECORDING"], retention_days=180)
    second_recruitment = invite(study_b["id"], struck["id"], api)
    screen(second_recruitment["id"], api)
    schedule(
        second_recruitment["id"],
        "2026-08-06T10:00:00Z",
        "2026-08-06T11:00:00Z",
        api,
    )
    record_no_show(second_recruitment["id"], api, reason="Cancelled at the door")
    close_fielding(study_b["id"], api)

    study_c = _field_a_study_on_pool(
        api,
        pool_id,
        incentive_amount_cents=5000,
        target_participant_count=3,
        fielding_start="2026-08-07T00:00:00Z",
        fielding_end="2026-08-19T00:00:00Z",
        guide_label="GC",
    )

    suppressed = read_participant(struck["id"], api)
    assert suppressed["status"] == "SUPPRESSED", (
        f"Expected SUPPRESSED at two strikes, got {suppressed['status']}"
    )
    assert suppressed["no_show_strikes"] == 2, (
        f"Expected no_show_strikes 2, got {suppressed['no_show_strikes']}"
    )
    assert suppressed["contacts_in_window"] == 2, (
        f"Expected both invitations still inside the window, got {suppressed['contacts_in_window']}"
    )

    refused = _invite_response(api, study_c["id"], struck["id"])
    validate_error(refused, ApiErrorId.PARTICIPANT_SUPPRESSED.value)

    rows = validate_success(
        api.auto_invite(study_c["id"], auto_invite_payload(1), RESEARCH_OPS_ADMIN_HEADERS),
        201,
    )
    assert len(rows) == 1, (
        f"Expected exactly one batch row for count 1, got {len(rows)}"
    )
    assert rows[0]["participant_id"] == untouched["id"], (
        "Expected the suppressed participant to be filtered out of the candidate "
        f"set, got {rows[0]['participant_id']}"
    )

    pool_after = read_pool(pool_id, api)
    assert pool_after["suppressed_participant_count"] == 1, (
        f"Expected suppressed_participant_count 1, got {pool_after['suppressed_participant_count']}"
    )
    assert pool_after["status"] == "OPEN", (
        "Expected the pool OPEN because a suppression ratio of exactly 0.50 does "
        f"not strictly exceed one half, got {pool_after['status']}"
    )
    assert_ledger_partition(pool_after)

    study_c_after = read_study(study_c["id"], api)
    assert study_c_after["invited_count"] == 1, (
        f"Expected only the batch row to land, got invited_count {study_c_after['invited_count']}"
    )
    assert study_c_after["recruitment_status"] == "RECRUITING", (
        f"Expected recruitment_status RECRUITING, got {study_c_after['recruitment_status']}"
    )


def test_auto_invite_creates_a_partial_batch_when_candidates_run_out(api):
    """A short batch is a success: count 5 against a pool that can offer only two
    candidates answers 201 with two rows, and those rows stay committed.

    PRD 3.4: "The walk stops when `count` rows have been created, when the
    candidate list is exhausted, or when the next candidate's reservation would
    exceed the pool's remaining `incentive_available_cents`. **A short batch is a
    success**: fewer rows than `count` are returned with a 201, and the rows
    already created stay committed."

    PRD 3.4: "A participant is a candidate when their `pool_id` equals the study's
    `participant_pool_id`, their derived posture is `ELIGIBLE`, their `segment` is
    exactly equal to the study's `required_segment` from the screening rubric,
    their `no_show_strikes` is below 2, their `contacts_in_window` is below the
    pool's `contact_cap_per_window`, and no recruitment already exists for this
    study naming them."

    PRD 3.4: "Candidates are ranked by `contacts_in_window` ascending, then by
    `no_show_strikes` ascending, then by `created_at` ascending — the last key is
    unique per participant row and so the ranking is total, with no randomness
    anywhere."

    Design: Corner/endpoints/auto_invite_creates_a_partial_batch_when_candidates_run_out
    """
    set_clock(CLOCK_START, api)
    ctx = setup_fielding_study(
        api,
        participant_count=3,
        target_participant_count=5,
        incentive_amount_cents=5000,
        pool_overrides={
            "name": "Batch pool",
            "pool_type": "CUSTOMER_LIST",
            "contact_cap_per_window": 2,
            "contact_window_days": 30,
            "incentive_budget_cents": 100000,
        },
    )
    pool_id = ctx["pool"]["id"]
    study_id = ctx["study"]["id"]
    already_recruited, second, third = ctx["participants"]
    wrong_segment = enroll_participant(
        pool_id, api, external_ref="P-B04", segment="NEW_USER", locale="en-US"
    )
    invite(study_id, already_recruited["id"], api)

    before = read_pool(pool_id, api)
    assert before["incentive_reserved_cents"] == 5000, (
        f"Setup drift: expected 5000 reserved by the manual invitation, got {before['incentive_reserved_cents']}"
    )
    assert before["status"] == "OPEN", (
        f"Setup drift: expected the pool OPEN, got {before['status']}"
    )

    rows = validate_success(
        api.auto_invite(study_id, auto_invite_payload(5), RESEARCH_OPS_ADMIN_HEADERS),
        201,
    )

    assert len(rows) == 2, (
        f"Expected a short batch of 2 rows even though count was 5, got {len(rows)}"
    )
    assert [row["participant_id"] for row in rows] == [second["id"], third["id"]], (
        "Expected the two remaining eligible participants in created_at order, got "
        f"{[row['participant_id'] for row in rows]}"
    )
    assert wrong_segment["id"] not in [row["participant_id"] for row in rows], (
        "Expected the NEW_USER participant to be excluded on segment, but it was invited"
    )
    assert already_recruited["id"] not in [row["participant_id"] for row in rows], (
        "Expected the already-recruited participant to be excluded, but it was invited again"
    )
    for row in rows:
        assert row["reserved_cents"] == 5000, (
            f"Expected 5000 reserved cents below 0.50 utilization, got {row['reserved_cents']}"
        )

    listed, meta = validate_paginated(
        api.list_recruitments(RESEARCH_OPS_ADMIN_HEADERS, {"study_id": study_id})
    )
    assert meta["total_count"] == 3, (
        f"Expected one manual plus two batch recruitments, got {meta['total_count']}"
    )
    for row in listed:
        assert row["status"] == "INVITED", (
            f"Expected every recruitment INVITED, got {row['status']}"
        )
        assert row["incentive_state"] == "RESERVED", (
            f"Expected every recruitment RESERVED, got {row['incentive_state']}"
        )

    after = read_pool(pool_id, api)
    assert after["incentive_reserved_cents"] == 15000, (
        f"Expected 15000 reserved after three 5000-cent reservations, got {after['incentive_reserved_cents']}"
    )
    assert after["status"] == "OPEN", (
        f"Expected the pool OPEN at utilization 0.15, got {after['status']}"
    )
    assert_ledger_partition(after)

    study_after = read_study(study_id, api)
    assert study_after["invited_count"] == 3, (
        f"Expected invited_count 3, got {study_after['invited_count']}"
    )
    assert study_after["recruitment_status"] == "RECRUITING", (
        f"Expected recruitment_status RECRUITING, got {study_after['recruitment_status']}"
    )
