"""Envelope, patch semantics, computed reads, action endpoints, and child listings."""
from test_helpers import (
    ADMIN,
    ANALYST,
    CLOCK_DEFAULT_STAMP,
    PRESIDING,
    RENEWAL_CLOCK,
    ApiClient,
    ApiErrorId,
    assert_decimal_equals,
    assert_pagination_meta,
    assert_privilege_triple,
    board_config_payload,
    license_version,
    pay_renewal,
    renewal_application_payload,
    reread_license,
    reread_renewal,
    residency_evidence_entry,
    run_sampling,
    seed_active_license,
    seed_board,
    seed_ce_record,
    seed_ce_verified_renewal,
    seed_renewal,
    seed_sibling_license,
    set_clock,
    submit_renewal,
    validate_error,
    validate_paginated,
    validate_success,
    verify_renewal_ce,
)


def test_a_registered_board_reads_back_field_for_field(api: ApiClient):
    """PRD §3.1: "Before anything can be licensed, a `SystemAdmin` must register the
    board itself, supplying at minimum a `state_code` and a `board_name` and
    overriding any of the regulatory parameters catalogued in §2.5."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    PRD §2.6: "`version` (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every mutation, including mutations that
    only touch derived fields."

    PRD §2.6: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, recording when the record was first created, taken from the
    logical clock."

    PRD §2.4: "Before the clock is ever set, it reads exactly
    `2026-08-01T00:00:00Z`; that fixed startup default must never be replaced by
    real wall-clock time."

    Design: Corner/endpoints/create_and_read_back_a_board_config_through_the_standard_crud_pair
    """
    created = api.create_board_config(
        board_config_payload(state_code="MI", board_name="Michigan Board of Nursing",
                             compact_member=False, ce_hours_required=25.00),
        ADMIN,
    )

    board = validate_success(created, 201)
    assert created.json()["meta"]["api_request_id"].startswith("req_"), (
        "The envelope carries a server-minted request identifier"
    )
    assert board["created_at"] == CLOCK_DEFAULT_STAMP, (
        f"The stamp comes from the logical clock, got {board['created_at']}"
    )
    assert board["version"] == 1

    read_back = validate_success(api.get_board_config(board["id"], ANALYST))

    assert read_back["id"] == board["id"]
    assert read_back["state_code"] == "MI"
    assert_decimal_equals(read_back["ce_hours_required"], 25.00, "ce_hours_required")
    assert read_back["compact_member"] is False
    assert read_back["status"] == "ACTIVE"
    assert read_back["version"] == 1, (
        f"A read is not a mutation, got version {read_back['version']}"
    )


def test_amending_two_board_parameters_leaves_the_other_defaults_alone(api: ApiClient):
    """PRD §3.1: "The same role may later amend the board — adjusting
    `compact_member`, any of the continuing-education caps, `practice_hours_required`,
    `renewal_grace_period_days`, `lapse_after_grace_days`, `audit_sample_rate_bp`,
    `criminal_lookback_years`, `disqualifying_offense_codes`, any of the five fee
    amounts, `phi_authorization_required`, `max_concurrent_custodian_holds`,
    `monitoring_clearance_gap_days`, `revocation_vote_threshold_bp`,
    `majority_vote_threshold_bp`, or the board's `status`."

    PRD §3.1: "Each amendment advances the board record's `version` by one."

    PRD §2.6: "`updated_at` (string): an ISO 8601 UTC timestamp in the same format,
    refreshed on every mutation of the record."

    Design: Corner/endpoints/patch_board_config_updates_only_the_supplied_fields
    """
    board = seed_board(api)
    assert_decimal_equals(board["ce_hours_required"], 30.00, "ce_hours_required")
    assert board["max_concurrent_custodian_holds"] == 2
    assert board["audit_sample_rate_bp"] == 500
    assert board["phi_authorization_required"] is True

    amended = validate_success(
        api.patch_board_config(
            board["id"], {"audit_sample_rate_bp": 2500, "phi_authorization_required": False},
            ADMIN,
        )
    )

    assert amended["audit_sample_rate_bp"] == 2500
    assert amended["phi_authorization_required"] is False
    assert_decimal_equals(amended["ce_hours_required"], 30.00, "ce_hours_required")
    assert amended["max_concurrent_custodian_holds"] == 2, (
        "An omitted parameter keeps the value it had"
    )
    assert amended["version"] == 2, (
        f"One amendment, one increment, got version {amended['version']}"
    )
    assert amended["state_code"] == "OH", (
        "The state code is not among the amendable parameters"
    )
    assert amended["updated_at"] == CLOCK_DEFAULT_STAMP


def test_the_posture_summary_echoes_the_credential_without_recomputing_it(
    api: ApiClient,
):
    """PRD §3.3: "A read-only compact posture summary is available for any
    credential. It returns `license_id`, `credential_type`, `license_status`,
    `encumbrance_status`, `multistate_privilege_status`, `privilege_variant`, and
    `privilege_basis_state` from the credential, alongside the inputs that produced
    them: `board_state_code` and `board_compact_member` from the issuing board, and
    `declared_primary_state` and `evidenced_primary_state` from the nurse — the
    latter being the state the evidence-ranked pool would resolve to right now."

    PRD §3.3: "Under `RESIDENCY_DECLARED` — the variant used at issuance, on every
    registration change, and whenever it is requested explicitly — the primary state
    of residence is simply the nurse's `declared_primary_state`, taken at face value."

    PRD §3.3: "Candidates are ranked first by the evidentiary weight of their
    `evidence_type`, where a `DRIVER_LICENSE` outranks a `TAX_RETURN`, which in turn
    outranks a `VOTER_REGISTRATION`; among entries of equal weight, the later
    `effective_date` ranks higher; and if two entries still tie, the one with the
    lower zero-based index in `residency_evidence` wins."

    Design: Corner/endpoints/privilege_summary_computed_read_matches_the_stored_privilege_triple
    """
    ctx = seed_active_license(
        api,
        nurse_overrides={
            "declared_primary_state": "OH",
            "residency_evidence": [
                residency_evidence_entry("DRIVER_LICENSE", "MI", "2026-01-01T00:00:00Z"),
            ],
        },
    )
    assert_privilege_triple(ctx["license"], "MULTISTATE", "RESIDENCY_DECLARED", "OH")
    version_before = ctx["license"]["version"]

    summary = validate_success(api.get_privilege_summary(ctx["license_id"], PRESIDING))

    assert summary["license_id"] == ctx["license_id"]
    assert summary["multistate_privilege_status"] == "MULTISTATE"
    assert summary["privilege_variant"] == "RESIDENCY_DECLARED"
    assert summary["privilege_basis_state"] == "OH"
    assert summary["board_state_code"] == "OH"
    assert summary["board_compact_member"] is True
    assert summary["declared_primary_state"] == "OH"
    assert summary["evidenced_primary_state"] == "MI", (
        f"The summary shows what the documents would resolve to, got "
        f"{summary['evidenced_primary_state']}"
    )
    stored = reread_license(api, ctx["license_id"])
    assert stored["version"] == version_before, (
        f"The computed read did not rewrite the credential, got {stored['version']}"
    )
    assert stored["multistate_privilege_status"] == "MULTISTATE", (
        "Reading the summary did not apply the evidenced variant"
    )


def test_the_registration_action_refuses_a_target_it_already_stands_at(
    api: ApiClient,
):
    """PRD §3.3: "The **registration dimension** is moved by a `LicensureAnalyst`
    supplying a `to_status`."

    PRD §3.3: "Placing a credential on inactive status, transitioning
    `license_status` from `ACTIVE` to `INACTIVE`, requires that the credential
    currently be `ACTIVE` and that its `encumbrance_status` be either `CLEAR` or
    `INVESTIGATION_PENDING`; the privilege determination is re-run and necessarily
    yields `NOT_ELIGIBLE`, because the credential is no longer `ACTIVE`."

    PRD §3.3: "Accepting a voluntary surrender moves `license_status` to the
    terminal `SURRENDERED` and is permitted from `ACTIVE`, `INACTIVE`, or `EXPIRED`;
    it sets `multistate_privilege_status` to `NOT_ELIGIBLE` outright and queues a
    notification report on the `INTERSTATE_COMPACT` channel with
    `source_entity_type` `LICENSE` and `basis_code` `SURRENDER`."

    PRD §2.11: "The target resource's current state is a declared origin state for
    the requested transition, the resource is not in a terminal state, and the
    governing board configuration is not `ARCHIVED` — otherwise `ERR_INVALID_STATE`."

    Design: Corner/endpoints/status_change_action_endpoint_drives_the_license_status_dimension
    """
    ctx = seed_active_license(api)
    assert ctx["license"]["license_status"] == "ACTIVE"
    assert ctx["license"]["multistate_privilege_status"] == "MULTISTATE"

    first = validate_success(
        api.change_license_status(ctx["license_id"], {"to_status": "INACTIVE"}, ANALYST)
    )

    assert first["license_status"] == "INACTIVE"
    assert first["multistate_privilege_status"] == "NOT_ELIGIBLE", (
        "The action re-ran the determination, which cannot grant a privilege to a "
        "credential that is no longer ACTIVE"
    )
    assert first["version"] == 2

    repeated = api.change_license_status(ctx["license_id"], {"to_status": "INACTIVE"},
                                        ANALYST)

    validate_error(repeated, ApiErrorId.ERR_INVALID_STATE.value)
    stored = reread_license(api, ctx["license_id"])
    assert stored["license_status"] == "INACTIVE", (
        "The refused repeat is not a no-op success"
    )
    assert stored["version"] == 2, (
        f"A refused action does not mutate the record, got {stored['version']}"
    )

    surrendered = validate_success(
        api.change_license_status(ctx["license_id"], {"to_status": "SURRENDERED"},
                                  ANALYST)
    )
    assert surrendered["license_status"] == "SURRENDERED"
    assert surrendered["multistate_privilege_status"] == "NOT_ELIGIBLE"
    validate_error(
        api.change_license_status(ctx["license_id"], {"to_status": "ACTIVE"}, ANALYST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_the_sampler_pools_only_the_filings_whose_credit_has_been_verified(
    api: ApiClient,
):
    """PRD §3.5: "A renewal filing is eligible for sampling when three conditions
    hold together: its `renewal_status` is `CE_VERIFIED`, its `audit_status` is
    `NOT_SELECTED`, and the credential it was filed against has an
    `issuing_board_config_id` equal to the board being sampled."

    PRD §3.5: "The draw size follows the board's `audit_sample_rate_bp` as a
    basis-point rate: multiply `audit_sample_rate_bp` by the eligible count, divide
    by 10000, and round the quotient **up** to the next whole number."

    PRD §3.5: "The highest-ranked filings up to the quota have their `audit_status`
    moved from `NOT_SELECTED` to `SELECTED`."

    PRD §3.5: "The response reports `board_config_id`, `eligible_count`, `quota`,
    `selected_count`, and `selected_renewal_application_ids`."

    Design: Corner/endpoints/run_audit_sampling_conditional_action_reports_eligible_count_and_quota
    """
    ctx = seed_active_license(api)
    sibling = seed_sibling_license(api, ctx)
    set_clock(api, RENEWAL_CLOCK)
    verified = seed_ce_verified_renewal(api, ctx["license_id"], clock=None)
    deficient = seed_renewal(api, sibling["license_id"], clock=None)
    seed_ce_record(api, deficient["id"], minutes=1200)
    seed_ce_record(api, deficient["id"], minutes=600, provider_accredited=False,
                   completion_date="2027-04-01T00:00:00Z")
    pay_renewal(api, deficient["id"])
    submit_renewal(api, deficient["id"])
    deficient = verify_renewal_ce(api, deficient["id"])
    assert verified["renewal_status"] == "CE_VERIFIED"
    assert deficient["renewal_status"] == "CE_DEFICIENT", (
        f"Ten of its thirty claimed hours came from an unaccredited provider, got "
        f"{deficient['renewal_status']}"
    )

    summary = run_sampling(api, ctx["board_id"])

    assert summary["board_config_id"] == ctx["board_id"]
    assert summary["eligible_count"] == 1, (
        f"Only the verified filing is in the pool, got {summary['eligible_count']}"
    )
    assert summary["quota"] == 1, (
        f"A five-percent rate over one filing still draws one, got {summary['quota']}"
    )
    assert summary["selected_count"] == 1
    assert summary["selected_renewal_application_ids"] == [verified["id"]]
    assert reread_renewal(api, verified["id"])["audit_status"] == "SELECTED"
    assert reread_renewal(api, deficient["id"])["audit_status"] == "NOT_SELECTED", (
        "A filing outside the pool is not touched by the pass"
    )


def test_a_renewal_appears_only_under_the_credential_it_names(api: ApiClient):
    """PRD §3.4: "The payload names the credential through `license_id`, carries the
    mandatory `expected_license_version` described in §2.8, and may pre-populate
    `attested_practice_hours` — the practice hours the licensee asserts for the
    period, defaulting to 0 — and `carry_over_hours_claimed`, the
    continuing-education hours the licensee claims to import from the prior period,
    also defaulting to 0."

    PRD §3.4: "A successful create freezes the accounting window: `period_end_on`
    is set to the credential's current `expires_on` and is the exclusive upper bound
    of the window, while `period_start_on` is set to `period_end_on` walked back by
    the board's `renewal_period_months` and is the inclusive lower bound."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before pagination is
    applied), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/endpoints/renewal_creation_links_the_license_and_appears_under_its_child_listing
    """
    ctx = seed_active_license(api)
    sibling = seed_sibling_license(api, ctx)
    version = license_version(api, ctx["license_id"])

    created = validate_success(
        api.create_renewal_application(
            renewal_application_payload(ctx["license_id"], version,
                                        attested_practice_hours=1000),
            ANALYST,
        ),
        201,
    )

    assert created["license_id"] == ctx["license_id"]
    own_rows, own_meta = validate_paginated(
        api.list_license_renewal_applications(ctx["license_id"], ANALYST,
                                              params={"limit": 10, "offset": 0})
    )
    assert own_meta["total_count"] == 1
    assert own_rows[0]["id"] == created["id"]
    other_rows, other_meta = validate_paginated(
        api.list_license_renewal_applications(sibling["license_id"], ANALYST,
                                              params={"limit": 10, "offset": 0})
    )
    assert other_rows == [], (
        "The neighbour's filing does not leak into an unrelated credential's listing"
    )
    assert_pagination_meta(other_meta, 10, 0, 0, False)
    stored = reread_renewal(api, created["id"])
    assert stored["period_start_on"] == "2026-08-01T00:00:00.000Z", (
        f"The window opens two years before expiry, got {stored['period_start_on']}"
    )
    assert stored["period_end_on"] == "2028-08-01T00:00:00.000Z"
