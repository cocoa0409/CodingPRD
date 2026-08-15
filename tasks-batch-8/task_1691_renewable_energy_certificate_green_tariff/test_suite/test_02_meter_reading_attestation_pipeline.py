"""Meter data pipeline: generator lifecycle gating of reading creation, the
attestation window and segregation of duties, half-open interval overlap,
revision cycles, and terminal-state lockdowns."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    JULY_PERIOD_END,
    JULY_PERIOD_START,
    accept_reading,
    assert_meter_reading,
    attest_reading,
    create_accepted_reading,
    create_active_generator,
    create_meter_reading,
    create_meter_reading_payload,
    get_generator,
    get_meter_reading,
    make_generator_operator_headers,
    make_meter_attester_headers,
    set_clock,
    submit_generator_for_verification,
    validate_error,
    validate_success,
    verify_generator,
)

ADMIN = TEST_USERS["registry_admin_headers"]


# ---------------------------------------------------------------------------
# Generator lifecycle gating of meter-reading creation
# ---------------------------------------------------------------------------

def test_suspended_generator_rejects_meter_reading_then_reinstate_allows(api):
    """PRD §3.1: "Once live, a generator can be suspended and later
    reinstated by a `RegistryAdmin` — `ACTIVE` to `SUSPENDED` and `SUSPENDED`
    back to `ACTIVE`"
    PRD §3.2: "The generator must be `ACTIVE`, or the submission is rejected
    with `ERR_GENERATOR_NOT_ACTIVE`."

    Design: Difficulty/non_linear_state_machine/generator_suspend_reinstate_cycle
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    suspended = validate_success(api.suspend_generator(gen["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"

    payload = create_meter_reading_payload(generator_id=gen["id"], metered_kwh=1000)
    resp = api.create_meter_reading(payload, make_generator_operator_headers(gen["id"]))
    validate_error(resp, ApiErrorId.ERR_GENERATOR_NOT_ACTIVE, expected_status=409)

    reinstated = validate_success(api.reinstate_generator(gen["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"

    reading = validate_success(
        api.create_meter_reading(payload, make_generator_operator_headers(gen["id"])),
        expected_status=201,
    )
    assert_meter_reading(reading)
    assert reading["status"] == "SUBMITTED", (
        "the same payload must succeed after reinstatement completes the cycle"
    )


def test_reading_create_rejected_for_suspended_generator(api):
    """PRD §3.2: "The generator must be `ACTIVE`, or the submission is
    rejected with `ERR_GENERATOR_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reading_requires_generator_active
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    validate_success(api.suspend_generator(gen["id"], ADMIN))

    resp = api.create_meter_reading(
        create_meter_reading_payload(generator_id=gen["id"], metered_kwh=100),
        make_generator_operator_headers(gen["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GENERATOR_NOT_ACTIVE, expected_status=409)
    assert get_generator(gen["id"])["status"] == "SUSPENDED"


def test_reading_create_rejected_for_decommissioned_generator(api, registry_admin_headers):
    """PRD §3.1: "A decommissioned generator accepts no new meter readings:
    submission requires an `ACTIVE` generator and fails with
    `ERR_GENERATOR_NOT_ACTIVE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/reading_requires_generator_active
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    validate_success(api.decommission_generator(gen["id"], ADMIN))

    resp = api.create_meter_reading(
        create_meter_reading_payload(generator_id=gen["id"], metered_kwh=100),
        make_generator_operator_headers(gen["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GENERATOR_NOT_ACTIVE, expected_status=409)

    data = validate_success(
        api.list_meter_readings(registry_admin_headers, params={"generator_id": gen["id"]})
    )
    assert data == [], "a rejected submission must leave no reading rows behind"


def test_generator_suspend_reinstate_cycle_is_repeatable(api):
    """PRD §3.1: "Once live, a generator can be suspended and later
    reinstated by a `RegistryAdmin` — `ACTIVE` to `SUSPENDED` and `SUSPENDED`
    back to `ACTIVE`" — the machine loops back to a prior state rather than
    following a one-way pipeline, so a second suspension is admissible after
    reinstatement.
    PRD §3.1: "Every lifecycle transition increments the generator's
    `version` by one".

    Design: Difficulty/non_linear_state_machine/generator_suspend_reinstate_cycle
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    active_version = gen["version"]

    first_suspend = validate_success(api.suspend_generator(gen["id"], ADMIN))
    assert first_suspend["status"] == "SUSPENDED"
    assert first_suspend["version"] == active_version + 1

    reinstated = validate_success(api.reinstate_generator(gen["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"

    second_suspend = validate_success(api.suspend_generator(gen["id"], ADMIN))
    assert second_suspend["status"] == "SUSPENDED", (
        "the cycle loops: SUSPENDED is reachable again after reinstatement"
    )
    assert second_suspend["version"] == active_version + 3, (
        "each pass through the cycle increments the version exactly once"
    )


# ---------------------------------------------------------------------------
# Generator terminal lockdown
# ---------------------------------------------------------------------------

def test_generator_terminal_lockdown_decommissioned(api, registry_admin_headers):
    """PRD §3.1: "any lifecycle action — verification, rejection, suspension,
    reinstatement, or decommissioning — attempted from a state the transition
    does not allow is rejected with `ERR_INVALID_GENERATOR_STATE`."
    PRD §4: "`ACTIVE` or `SUSPENDED` → `DECOMMISSIONED` (terminal)".

    Design: Corner/state_machines/generator_terminal_lockdown_decommissioned
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    decommissioned = validate_success(api.decommission_generator(gen["id"], ADMIN))
    assert decommissioned["status"] == "DECOMMISSIONED"

    resp_suspend = api.suspend_generator(gen["id"], ADMIN)
    validate_error(resp_suspend, ApiErrorId.ERR_INVALID_GENERATOR_STATE, expected_status=409)

    resp_submit = api.submit_generator_verification(
        gen["id"], make_generator_operator_headers(gen["id"])
    )
    validate_error(resp_submit, ApiErrorId.ERR_INVALID_GENERATOR_STATE, expected_status=409)

    resp_verify = api.verify_generator(gen["id"], ADMIN)
    validate_error(resp_verify, ApiErrorId.ERR_INVALID_GENERATOR_STATE, expected_status=409)

    still = validate_success(api.get_generator(gen["id"], registry_admin_headers))
    assert still["status"] == "DECOMMISSIONED", "terminal state must survive rejected actions"


# ---------------------------------------------------------------------------
# Half-open interval overlap
# ---------------------------------------------------------------------------

def test_reading_interior_overlap_rejected(api):
    """PRD §3.2: "any strict intersection of the two intervals is rejected
    with `ERR_READING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/reading_half_open_interval_overlap
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    create_meter_reading(
        gen["id"], "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z", 100
    )

    resp = api.create_meter_reading(
        create_meter_reading_payload(
            generator_id=gen["id"],
            period_start="2026-07-10T00:00:00Z",
            period_end="2026-07-20T00:00:00Z",
            metered_kwh=100,
        ),
        make_generator_operator_headers(gen["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_READING_PERIOD_OVERLAP, expected_status=409)


def test_reading_exact_adjacency_accepted(api):
    """PRD §3.2: "an existing reading whose `period_end` coincides exactly
    with the new reading's `period_start` is adjacency, not overlap".

    Design: Difficulty/resource_temporal_overlap/reading_half_open_interval_overlap
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    create_meter_reading(gen["id"], "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z", 100)

    adjacent = validate_success(
        api.create_meter_reading(
            create_meter_reading_payload(
                generator_id=gen["id"],
                period_start="2026-07-15T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
                metered_kwh=100,
            ),
            make_generator_operator_headers(gen["id"]),
        ),
        expected_status=201,
    )
    assert_meter_reading(adjacent)
    assert adjacent["status"] == "SUBMITTED", (
        "period_start == existing period_end touches without overlapping under "
        "half-open semantics"
    )


# ---------------------------------------------------------------------------
# Temporal guards on reading creation and attestation
# ---------------------------------------------------------------------------

def test_reading_period_inverted_rejected(api):
    """PRD §3.2: "The period must run forwards — `period_end` strictly after
    `period_start`, else `ERR_PERIOD_INVERTED`".

    Design: Corner/validations/reading_period_inverted_rejected
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    resp = api.create_meter_reading(
        create_meter_reading_payload(
            generator_id=gen["id"],
            period_start="2026-07-10T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            metered_kwh=100,
        ),
        make_generator_operator_headers(gen["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_INVERTED, expected_status=400)


def test_reading_future_period_rejected(api):
    """PRD §3.2: "must not reach into the future: `period_end` may not be
    later than the logical clock, else `ERR_FUTURE_PERIOD`."
    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time."

    Design: Corner/validations/reading_future_period_rejected
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")

    future = api.create_meter_reading(
        create_meter_reading_payload(
            generator_id=gen["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-02T00:00:00Z",
            metered_kwh=100,
        ),
        make_generator_operator_headers(gen["id"]),
    )
    validate_error(future, ApiErrorId.ERR_FUTURE_PERIOD, expected_status=422)

    boundary = validate_success(
        api.create_meter_reading(
            create_meter_reading_payload(
                generator_id=gen["id"],
                period_start="2026-07-31T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                metered_kwh=100,
            ),
            make_generator_operator_headers(gen["id"]),
        ),
        expected_status=201,
    )
    assert boundary["status"] == "SUBMITTED", (
        "period_end exactly equal to the clock is not 'later than' the clock"
    )


def test_attestation_window_boundary(api):
    """PRD §3.2: "it is permitted only while the logical clock is no later
    than thirty days after `period_end`, and an attempt past that window is
    rejected with `ERR_ATTESTATION_WINDOW_EXPIRED`."

    Design: Corner/validations/attestation_window_boundary
    """
    # Default logical clock is exactly 2026-08-01T00:00:00Z (PRD §2.4).
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    r_old = create_meter_reading(
        gen["id"], "2026-06-30T00:00:00Z", "2026-07-01T00:00:00Z", 10
    )
    r_edge = create_meter_reading(
        gen["id"], "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", 10
    )

    # r_edge: period_end 2026-07-02 + 30 days == 2026-08-01 == now (inclusive).
    attested = attest_reading(r_edge["id"], attester_id="att-1")
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_user_id"] == "att-1"

    # r_old: period_end 2026-07-01 + 30 days == 2026-07-31 < now.
    resp = api.attest_reading(r_old["id"], make_meter_attester_headers("att-1"))
    validate_error(resp, ApiErrorId.ERR_ATTESTATION_WINDOW_EXPIRED, expected_status=422)


# ---------------------------------------------------------------------------
# Segregation of duties and operator ownership
# ---------------------------------------------------------------------------

def test_self_attestation_rejected(api):
    """PRD §3.2: "the caller's `X-User-ID` must differ from the reading's
    `submitted_by_user_id`, else the attempt is rejected with
    `ERR_SELF_ATTESTATION`."

    Design: Corner/rbac/self_attestation_rejected
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    reading = create_meter_reading(gen["id"], JULY_PERIOD_START, JULY_PERIOD_END, 100)
    assert reading["submitted_by_user_id"] == gen["id"]

    resp = api.attest_reading(reading["id"], make_meter_attester_headers(gen["id"]))
    validate_error(resp, ApiErrorId.ERR_SELF_ATTESTATION, expected_status=403)

    still = get_meter_reading(reading["id"])
    assert still["status"] == "SUBMITTED"
    assert still["attested_by_user_id"] is None


def test_operator_cannot_submit_reading_for_other_generator(api):
    """PRD §2.1: "A `GeneratorOperator` therefore submits verification only
    for their own generator, creates meter readings only for their own
    generator, and resubmits only readings whose `submitted_by_user_id`
    equals their own `X-User-ID`." and "A request whose role is not permitted
    for the target endpoint — or that fails an ownership, purpose, or scope
    match described below — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/operator_cannot_submit_reading_for_other_generator
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    resp = api.create_meter_reading(
        create_meter_reading_payload(generator_id=gen["id"], metered_kwh=100),
        make_generator_operator_headers("00000000-0000-0000-0000-000000000001"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_attester_cannot_create_readings(api, meter_attester_headers):
    """PRD §2.1: "A request whose role is not permitted for the target
    endpoint — or that fails an ownership, purpose, or scope match described
    below — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST `/greenpower/meter-readings` — "GeneratorOperator" only.

    Design: Corner/rbac/attester_cannot_create_readings
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    resp = api.create_meter_reading(
        create_meter_reading_payload(generator_id=gen["id"], metered_kwh=100),
        meter_attester_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


# ---------------------------------------------------------------------------
# State-vs-temporal priority on attestation (pipeline short-circuit)
# ---------------------------------------------------------------------------

def test_attest_rejected_reading_reports_state_despite_expired_window(api):
    """PRD §2.8: "Every write request traverses a fixed validation pipeline.
    A failure at any stage short-circuits the rest, so the error a client
    sees is always the earliest applicable one." — stage "6. State-machine
    admissibility" precedes stage "9. Temporal rules".
    PRD §3.2: "Any attestation, rejection, resubmission, acceptance, or void
    attempted from a state the transition does not allow is rejected with
    `ERR_INVALID_READING_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_attest
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    reading = create_meter_reading(gen["id"], JULY_PERIOD_START, JULY_PERIOD_END, 1000)
    rejected = validate_success(
        api.reject_reading(
            reading["id"], {"reason": "implausible delta"},
            make_meter_attester_headers("att-1"),
        )
    )
    assert rejected["status"] == "REJECTED"

    # Past the 30-day attestation window (period_end 2026-08-01 + 30d).
    set_clock("2026-09-15T00:00:00Z")
    resp = api.attest_reading(reading["id"], make_meter_attester_headers("att-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_READING_STATE, expected_status=409)
    assert get_meter_reading(reading["id"])["status"] == "REJECTED"


def test_attest_attested_reading_reports_state_despite_expired_window(api):
    """PRD §2.8: "A failure at any stage short-circuits the rest, so the
    error a client sees is always the earliest applicable one." — attestation
    is admissible only from `SUBMITTED`, so a second attestation reports the
    state error even when the 30-day window has also lapsed.
    PRD §3.2: "Attesting moves a reading from `SUBMITTED` to `ATTESTED`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_attest
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    reading = create_meter_reading(gen["id"], JULY_PERIOD_START, JULY_PERIOD_END, 1000)
    attest_reading(reading["id"], attester_id="att-1")

    set_clock("2026-09-15T00:00:00Z")
    resp = api.attest_reading(reading["id"], make_meter_attester_headers("att-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_READING_STATE, expected_status=409)
    assert get_meter_reading(reading["id"])["status"] == "ATTESTED"


# ---------------------------------------------------------------------------
# Revision cycle and terminal lockdowns
# ---------------------------------------------------------------------------

def test_meter_reading_resubmit_cycle_and_reaccept(api):
    """PRD §3.2: "The owning `GeneratorOperator` — identified by `X-User-ID`
    matching `submitted_by_user_id` — may resubmit a `REJECTED` reading,
    returning it to `SUBMITTED` and clearing its `rejection_reason`. This
    revision cycle may repeat as often as needed."

    Design: Corner/state_machines/meter_reading_resubmit_cycle_and_reaccept
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    reading = create_meter_reading(gen["id"], JULY_PERIOD_START, JULY_PERIOD_END, 1000)
    rejected = validate_success(
        api.reject_reading(
            reading["id"], {"reason": "implausible"},
            make_meter_attester_headers("att-1"),
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "implausible"

    resubmitted = validate_success(
        api.resubmit_reading(reading["id"], make_generator_operator_headers(gen["id"]))
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["rejection_reason"] is None, "resubmit must clear rejection_reason"

    attest_reading(reading["id"], attester_id="att-1")
    accepted = accept_reading(reading["id"])
    assert accepted["status"] == "ACCEPTED"

    mint = validate_success(api.mint_run(gen["id"], ADMIN))
    assert mint["minted_count"] == 1, "the recovered reading must mint normally"



def test_reading_voided_terminal_lockdown(api, registry_admin_headers):
    """PRD §3.2: "Any attestation, rejection, resubmission, acceptance, or
    void attempted from a state the transition does not allow is rejected
    with `ERR_INVALID_READING_STATE`." and "a `RegistryAdmin` may void it,
    moving it from `ACCEPTED` to the terminal `VOIDED` state, which debits
    the generator's `cumulative_accepted_kwh` by the same `metered_kwh`".

    Design: Corner/state_machines/reading_voided_terminal_lockdown
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    reading = create_accepted_reading(
        gen["id"], JULY_PERIOD_START, JULY_PERIOD_END, 1000
    )
    assert get_generator(gen["id"])["cumulative_accepted_kwh"] == 1000

    voided = validate_success(
        api.void_reading(reading["id"], {"reason": "meter misread"}, ADMIN)
    )
    assert voided["status"] == "VOIDED"
    assert get_generator(gen["id"])["cumulative_accepted_kwh"] == 0, (
        "voiding debits cumulative_accepted_kwh by the reading's metered_kwh"
    )

    resp_attest = api.attest_reading(reading["id"], make_meter_attester_headers("att-2"))
    validate_error(resp_attest, ApiErrorId.ERR_INVALID_READING_STATE, expected_status=409)

    resp_reject = api.reject_reading(
        reading["id"], {"reason": "again"}, make_meter_attester_headers("att-2")
    )
    validate_error(resp_reject, ApiErrorId.ERR_INVALID_READING_STATE, expected_status=409)

    resp_resubmit = api.resubmit_reading(
        reading["id"], make_generator_operator_headers(gen["id"])
    )
    validate_error(resp_resubmit, ApiErrorId.ERR_INVALID_READING_STATE, expected_status=409)

    resp_void = api.void_reading(reading["id"], {}, ADMIN)
    validate_error(resp_void, ApiErrorId.ERR_INVALID_READING_STATE, expected_status=409)

    assert get_meter_reading(reading["id"])["status"] == "VOIDED"
    assert get_generator(gen["id"])["cumulative_accepted_kwh"] == 0


def test_void_minted_reading_rejected_and_unminted_void_debits(api):
    """PRD §3.2: "Voiding is possible only while the reading has not yet been
    consumed by a mint run: once `minted` is true, the attempt is rejected
    with `ERR_READING_ALREADY_MINTED`." and "a `RegistryAdmin` may void it,
    moving it from `ACCEPTED` to the terminal `VOIDED` state, which debits
    the generator's `cumulative_accepted_kwh` by the same `metered_kwh`".

    Design: Corner/validations/void_minted_reading_rejected_and_unminted_void_debits
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    r_minted = create_accepted_reading(
        gen["id"], JULY_PERIOD_START, JULY_PERIOD_END, 1000
    )
    mint = validate_success(api.mint_run(gen["id"], ADMIN))
    assert mint["minted_count"] == 1, "the July bucket mints 1 REC and consumes the reading"
    assert get_meter_reading(r_minted["id"])["minted"] is True

    set_clock("2026-08-15T00:00:00Z")
    r_late = create_accepted_reading(
        gen["id"], "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z", 700
    )
    assert get_generator(gen["id"])["cumulative_accepted_kwh"] == 1700

    resp = api.void_reading(r_minted["id"], {"reason": "fraud suspected"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_READING_ALREADY_MINTED, expected_status=409)
    assert get_meter_reading(r_minted["id"])["status"] == "ACCEPTED", (
        "a mint-consumed reading is void-proof"
    )

    voided = validate_success(
        api.void_reading(r_late["id"], {"reason": "meter misread"}, ADMIN)
    )
    assert voided["status"] == "VOIDED"
    assert get_generator(gen["id"])["cumulative_accepted_kwh"] == 1000, (
        "the unminted void debits cumulative_accepted_kwh: 1700 - 700"
    )
