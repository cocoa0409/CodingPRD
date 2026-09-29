"""Restriction intake from the treating provider: filing, the clarification loop,
verification, activation and the five-level supersede cascade."""
from test_helpers import (
    ApiErrorId,
    assert_restriction_set,
    assert_seat_ledger,
    create_restriction_set_payload,
    create_treating_provider_payload,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_registering_a_clinician_with_an_unknown_credential_state_is_refused(
    api, program_admin_headers
):
    """PRD §3.2: "Clinicians are registered by a program administrator with their `full_name`, their ten-digit `npi` National Provider Identifier, their clinical `specialty`, and optionally an initial `credential_status`, which defaults to `PROVISIONAL` and may otherwise be `VERIFIED` or `REVOKED`."
    PRD §2.6: "Request-shape validation covers every required field being present, every enum-typed value lying inside its declared set"

    Design: Corner/entities/treating_provider_invalid_enum_value_returns_invalid_request
    """
    fixtures.reset_clock()

    resp = api.create_treating_provider(
        create_treating_provider_payload(credential_status="GOLD"), program_admin_headers
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_filing_a_restriction_set_computes_the_severity_index(api):
    """PRD §3.2: "A newly filed set lands in `status` `DRAFT` with `clarification_note` null, `clarification_round_count` at zero, `supersedes_restriction_set_id` null, and `active_placement_count` at zero"
    PRD §3.2: "Every restriction set publishes a `severity_index` between 0 and 100, where 0 means clinically unrestricted and 100 means maximally restricted. It is computed when the set is filed"
    PRD §3.2: "The five weighted terms are added together, that contribution is subtracted from 100, and the difference is rounded half up to a whole number and clamped into the range from 0 to 100."

    Design: Corner/entities/restriction_set_severity_index_is_computed_not_supplied
    """
    ctx = fixtures.setup_program()
    payload = create_restriction_set_payload(
        ctx["provider_id"], ctx["claim_version"],
        max_lift_lbs=20, max_continuous_standing_minutes=30, max_hours_per_day=6,
        keyboard_minutes_per_hour=45, overhead_reach_allowed=False, driving_allowed=False,
    )
    assert "severity_index" not in payload, "severity_index is never an input field"

    data = validate_success(
        api.create_restriction_set(ctx["claim_id"], payload, ctx["provider_headers"]), 201
    )

    assert_restriction_set(data)
    assert data["severity_index"] == 60, (
        f"lift 20 / standing 30 / hours 6 / no overhead / no driving scores 60, got "
        f"{data['severity_index']}"
    )
    assert data["status"] == "DRAFT"
    assert data["active_placement_count"] == 0


def test_severity_index_clamps_each_term_at_its_reference_ceiling(api):
    """PRD §3.2: "The lift term takes the lesser of `max_lift_lbs` and the 50-pound reference, divides it by 50, scales the result to a percentage, and weights it at 0.40. The standing term takes the lesser of `max_continuous_standing_minutes` and the 120-minute reference, divides it by 120, scales it to a percentage, and weights it at 0.20. The hours term takes the lesser of `max_hours_per_day` and the eight-hour reference, divides it by 8, scales it to a percentage, and weights it at 0.25."
    PRD §3.2: "The five weighted terms are added together, that contribution is subtracted from 100, and the difference is rounded half up to a whole number and clamped into the range from 0 to 100."

    Design: Corner/calculations/severity_index_clamps_limits_at_their_reference_ceilings
    """
    ctx = fixtures.setup_program()
    payload = create_restriction_set_payload(
        ctx["provider_id"], ctx["claim_version"],
        max_lift_lbs=80, max_continuous_standing_minutes=200, max_hours_per_day=10,
        keyboard_minutes_per_hour=60, overhead_reach_allowed=True, driving_allowed=True,
    )

    data = validate_success(
        api.create_restriction_set(ctx["claim_id"], payload, ctx["provider_headers"]), 201
    )

    assert data["severity_index"] == 0, (
        f"every term clamps at its reference ceiling so the index bottoms out at 0, got "
        f"{data['severity_index']}"
    )


def test_a_revoked_clinician_may_not_file_restrictions(api):
    """PRD §3.2: "Only the administrator may later move a clinician's `credential_status`, and only a clinician standing at `VERIFIED` may originate or submit restrictions; a filing, submission or verification touching a clinician who is `PROVISIONAL` or `REVOKED` is refused at priority 17 with `ERR_PROVIDER_CREDENTIAL_REVOKED` and HTTP 422."

    Design: Corner/validations/revoked_provider_cannot_file_a_restriction_set
    """
    employee = fixtures.create_employee()
    claim = fixtures.open_claim(employee["id"])
    authorized = fixtures.authorize_claim(claim["id"])
    revoked = fixtures.create_treating_provider(
        full_name="Lee Brandt", npi="9998887770", specialty="Orthopedics",
        credential_status="REVOKED",
    )

    resp = api.create_restriction_set(
        claim["id"],
        create_restriction_set_payload(revoked["id"], authorized["version"]),
        fixtures.make_treating_provider_headers(revoked["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_PROVIDER_CREDENTIAL_REVOKED, 422)


def test_verifying_a_draft_set_is_refused_as_an_invalid_state(api, occ_health_nurse_headers):
    """PRD §3.2: "A nurse verifies a submitted set, moving it `SUBMITTED → VERIFIED`, which requires the authoring clinician still to be `VERIFIED`, recomputes `severity_index`, and raises `version` by 1."
    PRD §2.6: "Priority 9 asks whether the row's current state is a declared origin state for the requested transition; if not, the answer is `ERR_INVALID_STATE` with HTTP 409."

    Design: Corner/state_machines/restriction_set_verify_from_draft_returns_invalid_state
    """
    ctx = fixtures.setup_program()
    filed = fixtures.file_restriction_set(ctx)

    resp = api.verify_restriction_set(filed["id"], occ_health_nurse_headers)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    still = validate_success(api.get_restriction_set(filed["id"], occ_health_nurse_headers))
    assert still["status"] == "DRAFT", "the refused verify leaves the set in DRAFT"


def test_clarification_request_records_the_note_and_raises_the_round_count(
    api, occ_health_nurse_headers
):
    """PRD §3.2: "A nurse — or a coordinator — may bounce a submitted set back to the author, moving it `SUBMITTED → CLARIFICATION_REQUESTED` while writing the supplied `note` into `clarification_note`, raising `clarification_round_count` by 1 and raising `version` by 1."

    Design: Difficulty/non_linear_state_machine/restriction_set_clarification_revision_cycle
    """
    ctx = fixtures.setup_program()
    filed = fixtures.file_restriction_set(ctx)
    fixtures.get_success_data(api.submit_restriction_set(filed["id"], ctx["provider_headers"]))

    data = validate_success(
        api.request_restriction_set_clarification(
            filed["id"], {"note": "Clarify keyboard tolerance"}, occ_health_nurse_headers
        )
    )

    assert data["status"] == "CLARIFICATION_REQUESTED"
    assert data["clarification_round_count"] == 1
    assert data["clarification_note"] == "Clarify keyboard tolerance"


def test_resubmitted_set_reaches_verified_with_its_round_count_preserved(
    api, occ_health_nurse_headers
):
    """PRD §3.2: "A clinician submits a set that is in `DRAFT`, moving it `DRAFT → SUBMITTED`; the same submission action also re-submits a set that is in `CLARIFICATION_REQUESTED`, moving it `CLARIFICATION_REQUESTED → SUBMITTED`."
    PRD §3.2: "The `SUBMITTED → CLARIFICATION_REQUESTED → SUBMITTED` loop may run any number of rounds; each round leaves its mark in the round counter."

    Design: Difficulty/non_linear_state_machine/restriction_set_clarification_revision_cycle
    """
    ctx = fixtures.setup_program()
    filed = fixtures.file_restriction_set(ctx)
    fixtures.get_success_data(api.submit_restriction_set(filed["id"], ctx["provider_headers"]))
    fixtures.get_success_data(
        api.request_restriction_set_clarification(
            filed["id"], {"note": "Clarify keyboard tolerance"}, occ_health_nurse_headers
        )
    )

    resubmitted = validate_success(
        api.submit_restriction_set(filed["id"], ctx["provider_headers"])
    )
    verified = validate_success(api.verify_restriction_set(filed["id"], occ_health_nurse_headers))

    assert resubmitted["status"] == "SUBMITTED", "the set re-enters a state it already left"
    assert verified["status"] == "VERIFIED"
    assert verified["clarification_round_count"] == 1, (
        "the completed round is still recorded after the set reaches VERIFIED"
    )


def test_activating_a_set_whose_window_has_already_lapsed_is_refused(api):
    """PRD §3.2: "A coordinator or nurse activates a set that is in `VERIFIED`, moving it `VERIFIED → ACTIVE`; the set's `valid_through` must be on or after the logical clock's calendar date, or the request is refused at priority 18 with `ERR_RESTRICTION_WINDOW_INVALID` and HTTP 422."

    Design: Corner/validations/expired_restriction_window_blocks_activation
    """
    ctx = fixtures.setup_program()
    filed = fixtures.file_restriction_set(
        ctx, effective_from="2026-07-01", valid_through="2026-07-31"
    )
    fixtures.walk_restriction_set_to_verified(ctx, filed["id"])

    resp = api.activate_restriction_set(filed["id"], fixtures.COORD)

    validate_error(resp, ApiErrorId.ERR_RESTRICTION_WINDOW_INVALID, 422)
    still = validate_success(api.get_restriction_set(filed["id"], fixtures.COORD))
    assert still["status"] == "VERIFIED", "the refused activation leaves the set in VERIFIED"


def test_activation_supersedes_the_prior_set_and_stamps_the_pointer(api):
    """PRD §3.2: "At the first level the set becomes `ACTIVE` and the claim's `active_restriction_set_id` is pointed at it. At the second level, caused by the first, the claim's previously `ACTIVE` set moves `ACTIVE → SUPERSEDED` — clearing the claim's `active_restriction_set_id` before the new set writes its own id there — and the new set's `supersedes_restriction_set_id` is stamped with the displaced set's id."

    Design: Difficulty/transitive_cascade/restriction_activation_supersede_cascade_depth_five
    """
    ctx = fixtures.setup_active_placement()
    second = fixtures.file_restriction_set(ctx, max_lift_lbs=8)
    fixtures.walk_restriction_set_to_verified(ctx, second["id"])

    activated = validate_success(api.activate_restriction_set(second["id"], fixtures.COORD))

    assert activated["status"] == "ACTIVE"
    assert activated["supersedes_restriction_set_id"] == ctx["restriction_set_id"]
    displaced = validate_success(
        api.get_restriction_set(ctx["restriction_set_id"], fixtures.COORD)
    )
    assert displaced["status"] == "SUPERSEDED"
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["active_restriction_set_id"] == second["id"]


def test_supersede_cascade_suspends_the_conflicting_placement_and_releases_its_seat(api):
    """PRD §3.2: "At the third level, caused by the second, every placement built on the displaced set whose `placement_status` is `ADJUSTER_PENDING`, `ACTIVE` or `PROGRESSION_HOLD` is re-checked against the new set's limits, and any placement whose transitional job now breaches a limit is moved to `SUSPENDED` with `suspension_reason` set to `RESTRICTION_CONFLICT`, lowering that job's `filled_seats` by 1."

    Design: Difficulty/transitive_cascade/restriction_activation_supersede_cascade_depth_five
    """
    ctx = fixtures.setup_active_placement()
    second = fixtures.file_restriction_set(ctx, max_lift_lbs=8)
    fixtures.walk_restriction_set_to_verified(ctx, second["id"])

    validate_success(api.activate_restriction_set(second["id"], fixtures.COORD))

    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["placement_status"] == "SUSPENDED", (
        "the job's 10 lb demand now breaches the new 8 lb limit"
    )
    assert placement["suspension_reason"] == "RESTRICTION_CONFLICT"
    job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(job, 0)


def test_supersede_cascade_escalates_the_review_opens_a_panel_and_freezes_the_claim(api):
    """PRD §3.2: "At the fourth level, caused by the third, each placement suspended in this way has its progression review whose `review_status` is `SCHEDULED` or `IN_REVIEW` moved to `ESCALATED`, and a case-review panel is created for it with `review_status` `OPEN`, `trigger_reason` `RESTRICTION_CONFLICT`, `quorum_required` 3, and `opened_by_user_id` set to the literal string `system`. At the fifth level, caused by the fourth, the claim's `rtw_posture` is recomputed and necessarily lands on `FROZEN`, because an open panel now exists."

    Design: Difficulty/transitive_cascade/restriction_activation_supersede_cascade_depth_five
    """
    ctx = fixtures.setup_active_placement()
    review_id = ctx["progression_review_id"]
    second = fixtures.file_restriction_set(ctx, max_lift_lbs=8)
    fixtures.walk_restriction_set_to_verified(ctx, second["id"])

    validate_success(api.activate_restriction_set(second["id"], fixtures.COORD))

    review = validate_success(api.get_progression_review(review_id, fixtures.COORD))
    assert review["review_status"] == "ESCALATED"
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["open_case_review_id"] is not None, "a panel is opened for the placement"
    panel = validate_success(
        api.get_case_review(placement["open_case_review_id"], fixtures.NURSE)
    )
    assert panel["review_status"] == "OPEN"
    assert panel["trigger_reason"] == "RESTRICTION_CONFLICT"
    assert panel["quorum_required"] == 3
    assert panel["opened_by_user_id"] == "system"
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["rtw_posture"] == "FROZEN"


def test_submitting_a_superseded_set_is_refused_as_already_terminal(api):
    """PRD §3.2: "`SUPERSEDED` and `EXPIRED` are terminal: any transition request aimed at a set in either state answers `ERR_ALREADY_TERMINAL`."
    PRD §2.6: "Priority 8 asks whether the addressed row already sits in a terminal state of its state machine; if so the answer is `ERR_ALREADY_TERMINAL` with HTTP 409."

    Design: Corner/state_machines/superseded_restriction_set_rejects_further_submit
    """
    ctx = fixtures.setup_active_restriction_set()
    second = fixtures.file_restriction_set(ctx)
    fixtures.walk_restriction_set_to_active(ctx, second["id"])

    resp = api.submit_restriction_set(ctx["restriction_set_id"], ctx["provider_headers"])

    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
    displaced = validate_success(
        api.get_restriction_set(ctx["restriction_set_id"], fixtures.COORD)
    )
    assert displaced["status"] == "SUPERSEDED"
    replacement = validate_success(api.get_restriction_set(second["id"], fixtures.COORD))
    assert replacement["supersedes_restriction_set_id"] == ctx["restriction_set_id"]


def test_advancing_the_clock_past_valid_through_expires_the_active_set(api):
    """PRD §3.2: "When the logical clock advances past a set's `valid_through` while that set is `ACTIVE`, it moves `ACTIVE → EXPIRED`, the owning claim's `active_restriction_set_id` is cleared, the claim's `rtw_posture` is recomputed, and the set's `version` rises by 1; the ids of every set expired by that advance come back in `expired_restriction_set_ids`."

    Design: Corner/state_machines/clock_advance_expires_active_restriction_set_and_clears_pointer
    """
    ctx = fixtures.setup_program()
    filed = fixtures.file_restriction_set(ctx, valid_through="2026-08-15")
    fixtures.walk_restriction_set_to_active(ctx, filed["id"])

    clock = validate_success(api.set_clock("2026-08-20T00:00:00Z", fixtures.ADMIN))

    assert clock["current_utc"].startswith("2026-08-20T00:00:00"), (
        f"the clock answers with the new instant, got {clock['current_utc']!r}"
    )
    assert filed["id"] in clock["expired_restriction_set_ids"]
    lapsed = validate_success(api.get_restriction_set(filed["id"], fixtures.COORD))
    assert lapsed["status"] == "EXPIRED"
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["active_restriction_set_id"] is None


def test_program_wide_listing_narrows_by_treating_provider_and_status(api):
    """PRD §3.2: "Restriction sets can be listed under their claim or across the whole program, and the program-wide listing may be narrowed by `claim_id`, `treating_provider_id`, `supersedes_restriction_set_id` and `status`."
    PRD §2.3: "Filtering is applied before pagination, so `total_count` reports the size of the filtered set rather than the size of the table."

    Design: Corner/endpoints/restriction_sets_filtered_by_treating_provider
    """
    ctx = fixtures.setup_active_restriction_set()

    resp = api.list_restriction_sets(
        fixtures.COORD, params={"treating_provider_id": ctx["provider_id"], "status": "ACTIVE"}
    )

    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"exactly one ACTIVE set was authored by that clinician, got {len(data)}"
    assert data[0]["id"] == ctx["restriction_set_id"]
    assert data[0]["status"] == "ACTIVE"
    assert meta["total_count"] == 1


def test_a_supervisor_may_not_verify_a_restriction_set(api):
    """PRD §2.1: "When a caller's role is not listed among an endpoint's authorized roles in §4, the request is refused with `ERR_UNAUTHORIZED` and HTTP 403."
    PRD §4: "| POST | `/rtw/restriction-sets/{id}/verify` | Occupational-health nurse verifies a submitted restriction set. | `OccHealthNurse` |"

    Design: Corner/rbac/supervisor_cannot_verify_a_restriction_set
    """
    ctx = fixtures.setup_program()
    filed = fixtures.file_restriction_set(ctx)
    fixtures.get_success_data(api.submit_restriction_set(filed["id"], ctx["provider_headers"]))

    resp = api.verify_restriction_set(filed["id"], ctx["supervisor_headers"])

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    still = validate_success(api.get_restriction_set(filed["id"], fixtures.COORD))
    assert still["status"] == "SUBMITTED"


def test_the_authoring_clinician_may_not_activate_their_own_restriction_set(api):
    """PRD §2.1: "When a caller's role is not listed among an endpoint's authorized roles in §4, the request is refused with `ERR_UNAUTHORIZED` and HTTP 403."
    PRD §3.2: "A coordinator or nurse activates a set that is in `VERIFIED`, moving it `VERIFIED → ACTIVE`"

    Design: Corner/rbac/treating_provider_cannot_activate_a_restriction_set
    """
    ctx = fixtures.setup_program()
    filed = fixtures.file_restriction_set(ctx)
    fixtures.walk_restriction_set_to_verified(ctx, filed["id"])

    resp = api.activate_restriction_set(filed["id"], ctx["provider_headers"])

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    still = validate_success(api.get_restriction_set(filed["id"], fixtures.COORD))
    assert still["status"] == "VERIFIED"


def test_a_second_intake_carrying_the_pre_intake_claim_version_is_refused(api):
    """PRD §2.7: "Filing a restriction set against a claim requires `expected_claim_version`, carrying the client's last observed `version` of that `Claim`. If the value does not equal the claim's current `version`, the filing is rejected with `ERR_STALE_CLAIM_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_layers/stale_claim_version_rejects_a_second_restriction_intake
    """
    ctx = fixtures.setup_program()
    stale_version = ctx["claim_version"]
    fixtures.file_restriction_set(ctx, expected_claim_version=stale_version)

    resp = api.create_restriction_set(
        ctx["claim_id"],
        create_restriction_set_payload(
            ctx["provider_id"], stale_version,
            max_lift_lbs=15, max_continuous_standing_minutes=25, max_hours_per_day=5,
            keyboard_minutes_per_hour=40,
        ),
        ctx["provider_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION, 412)

    fresh_version = fixtures.current_claim_version(ctx["claim_id"])
    assert fresh_version == stale_version + 1, "the first intake raised the claim's version by 1"
    retried = validate_success(
        api.create_restriction_set(
            ctx["claim_id"],
            create_restriction_set_payload(
                ctx["provider_id"], fresh_version,
                max_lift_lbs=15, max_continuous_standing_minutes=25, max_hours_per_day=5,
                keyboard_minutes_per_hour=40,
            ),
            ctx["provider_headers"],
        ),
        201,
    )
    assert retried["status"] == "DRAFT", "re-reading the claim and resending succeeds"
