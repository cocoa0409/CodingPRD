"""Attestation campaigns: open/close/finalize, exceptions, cyclic denial."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    assert_pct_equal,
    attest,
    create_campaign,
    create_employee,
    create_regulator,
    create_role,
    find_attestation,
    get_attestation_data,
    get_success_data,
    make_employee_headers,
    open_campaign,
    request_exception,
    set_clock,
    setup_curriculum_stack,
    setup_open_campaign_with_attestation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories

ADMIN = TEST_USERS["compliance_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestExceptionDenialCycle:
    def test_denial_cycles_attestation_back_to_pending(self, api):
        """PRD §3.6: "Denial carries a required `decision_note`, moves the
        exception to `DENIED`, and cycles the attestation back from
        `EXCEPTION_PENDING` to `PENDING` — the employee can still attest."
        PRD §3.6: "The request creates the exception in `REQUESTED` status
        beneath the attestation — the new record's `attestation_id` ties it back
        to that attestation — with `requested_by_manager_id` taken from the
        caller's identity, and moves the attestation from `PENDING` to
        `EXCEPTION_PENDING`."

        Design: Difficulty/non_linear_state_machine/attestation_exception_denial_cycle
        """
        ctx = setup_open_campaign_with_attestation("ATT")
        mgr, att = ctx["manager"], ctx["attestation"]
        assert att["status"] == "PENDING"

        exc = request_exception(att["id"], mgr["id"])
        assert exc["status"] == "REQUESTED"
        assert get_attestation_data(att["id"])["status"] == "EXCEPTION_PENDING"

        resp = api.deny_exception(exc["id"], {"decision_note": "Insufficient justification"}, ADMIN)
        denied = validate_success(resp, 200)
        assert denied["status"] == "DENIED"
        assert get_attestation_data(att["id"])["status"] == "PENDING", (
            "denial loops the attestation back — cyclic revert"
        )

    def test_employee_can_still_attest_after_denial(self, api):
        """PRD §3.6: "Denial carries a required `decision_note`, moves the
        exception to `DENIED`, and cycles the attestation back from
        `EXCEPTION_PENDING` to `PENDING` — the employee can still attest."
        PRD §3.6: "Attesting moves the record to `ATTESTED`, stamps
        `attested_at`, and captures `statement_version_snapshot` from the
        campaign's `statement_version` so the exact wording attested to is
        frozen on the record."

        Design: Difficulty/non_linear_state_machine/attestation_exception_denial_cycle
        """
        ctx = setup_open_campaign_with_attestation("ATT")
        emp, mgr, att = ctx["employee"], ctx["manager"], ctx["attestation"]
        exc = request_exception(att["id"], mgr["id"])
        get_success_data(
            api.deny_exception(exc["id"], {"decision_note": "Insufficient justification"}, ADMIN),
            200,
        )

        attested = attest(att["id"], emp["id"])
        assert attested["status"] == "ATTESTED"
        assert_instant_equal(attested["attested_at"], "2026-08-03T09:00:00Z", "attested_at")
        assert attested["statement_version_snapshot"] == "STMT-2026-08"


def test_campaign_finalize_computes_population_metrics(api):
    """PRD §3.6: "Finalization is reserved for an `Auditor` acting on a `CLOSED`
    campaign (`ERR_CAMPAIGN_NOT_FINALIZABLE` otherwise); it moves the campaign
    to `FINALIZED` — its terminal state — and computes and persists the
    campaign's `metrics`: `population_size` counting all of the campaign's
    attestation rows, `attested_count` of those `ATTESTED`, `exempted_count` of
    those `EXEMPTED`, `expired_count` of those `EXPIRED`, and
    `response_rate_pct` equal to one hundred times the sum of attested and
    exempted counts divided by the population size, rounded half up to 2 decimal
    places — with an empty population reporting 0.00."

    Design: Corner/state_machines/campaign_finalize_computes_population_metrics
    """
    set_clock("2026-08-03T09:00:00Z")
    stack = setup_curriculum_stack("MET")
    mgr_role = create_role(code="R-METM", name="MET Mgr Role")
    mgr = create_employee("M-MET-1", mgr_role["id"], full_name="Met Mgr")
    e1 = create_employee("E-M1", stack["role"]["id"], full_name="Met One", manager_id=mgr["id"])
    e2 = create_employee("E-M2", stack["role"]["id"], full_name="Met Two", manager_id=mgr["id"])
    create_employee("E-M3", stack["role"]["id"], full_name="Met Three", manager_id=mgr["id"])

    camp = create_campaign(stack["regulator"]["id"], statement_version="STMT-MET")
    open_campaign(camp["id"])
    att1 = find_attestation(e1["id"])
    att2 = find_attestation(e2["id"])

    attest(att1["id"], e1["id"])
    exc2 = request_exception(
        att2["id"], mgr["id"], reason_code="MILITARY_DUTY",
        detail="Reserve duty through September",
    )
    get_success_data(api.approve_exception(exc2["id"], ADMIN), 200)

    closed = get_success_data(api.close_campaign(camp["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"

    finalized = get_success_data(api.finalize_campaign(camp["id"], AUDITOR), 200)
    assert finalized["status"] == "FINALIZED"
    metrics = finalized["metrics"]
    assert metrics["population_size"] == 3
    assert metrics["attested_count"] == 1
    assert metrics["exempted_count"] == 1
    assert metrics["expired_count"] == 1, "E-M3 still PENDING at close"
    assert_pct_equal(metrics["response_rate_pct"], 66.67, "response_rate_pct")


def test_campaign_state_gate_errors(api):
    """PRD §3.6: "Opening a campaign requires it to be `DRAFT`
    (`ERR_CAMPAIGN_NOT_DRAFT`) and the current instant to fall inside the
    inclusive window bounded by `window_open_at` and `window_close_at`
    (`ERR_CAMPAIGN_WINDOW_INVALID`)."
    PRD §3.6: "Closing a campaign — manually by a `ComplianceAdmin`, or by step
    5 of the sweep once the current time is strictly later than
    `window_close_at` — requires the campaign to be `OPEN`
    (`ERR_CAMPAIGN_NOT_OPEN`)"
    PRD §3.6: "Finalization is reserved for an `Auditor` acting on a `CLOSED`
    campaign (`ERR_CAMPAIGN_NOT_FINALIZABLE` otherwise)"

    Design: Corner/errors/campaign_state_gate_errors
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-CG", name="CG Regulator")
    camp = create_campaign(reg["id"], statement_version="STMT-CG")

    early_close = api.close_campaign(camp["id"], ADMIN)
    validate_error(early_close, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value)

    opened = get_success_data(api.open_campaign(camp["id"], ADMIN), 200)
    assert opened["status"] == "OPEN"

    reopen = api.open_campaign(camp["id"], ADMIN)
    validate_error(reopen, ApiErrorId.ERR_CAMPAIGN_NOT_DRAFT.value)

    early_finalize = api.finalize_campaign(camp["id"], AUDITOR)
    validate_error(early_finalize, ApiErrorId.ERR_CAMPAIGN_NOT_FINALIZABLE.value)


def test_campaign_window_validation_at_create_and_open(api):
    """PRD §3.6: "a `window_close_at` that is not strictly later than
    `window_open_at` is rejected with `ERR_CAMPAIGN_WINDOW_INVALID`."
    PRD §3.6: "Opening a campaign requires it to be `DRAFT`
    (`ERR_CAMPAIGN_NOT_DRAFT`) and the current instant to fall inside the
    inclusive window bounded by `window_open_at` and `window_close_at`
    (`ERR_CAMPAIGN_WINDOW_INVALID`)."

    Design: Corner/errors/campaign_window_validation_at_create_and_open
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-WV", name="WV Regulator")

    bad = api.create_campaign(
        factories.create_campaign_payload(
            reg["id"], window_open_at="2026-09-01T00:00:00Z",
            window_close_at="2026-08-01T00:00:00Z", statement_version="STMT-WV",
        ),
        ADMIN,
    )
    validate_error(bad, ApiErrorId.ERR_CAMPAIGN_WINDOW_INVALID.value)

    camp2 = create_campaign(
        reg["id"], window_open_at="2026-08-10T00:00:00Z",
        window_close_at="2026-09-01T00:00:00Z", statement_version="STMT-WV",
    )
    early_open = api.open_campaign(camp2["id"], ADMIN)
    validate_error(early_open, ApiErrorId.ERR_CAMPAIGN_WINDOW_INVALID.value)


def test_exception_decision_gates(api):
    """PRD §3.6: "Approval — only on a `REQUESTED` exception, else
    `ERR_EXCEPTION_NOT_PENDING` — moves the exception to `APPROVED` with
    `decided_by` recording the decider's opaque operator id, and moves the
    attestation to `EXEMPTED`."
    PRD §3.6: "The exception states `APPROVED` and `DENIED` are terminal."

    Design: Corner/errors/exception_decision_gates
    """
    ctx = setup_open_campaign_with_attestation("EG")
    mgr, att = ctx["manager"], ctx["attestation"]
    exc = request_exception(
        att["id"], mgr["id"], reason_code="ROLE_TRANSITION",
        detail="Moved departments mid-cycle",
    )

    approved = get_success_data(api.approve_exception(exc["id"], ADMIN), 200)
    assert approved["status"] == "APPROVED"
    assert get_attestation_data(att["id"])["status"] == "EXEMPTED"

    late_deny = api.deny_exception(exc["id"], {"decision_note": "too late"}, ADMIN)
    validate_error(late_deny, ApiErrorId.ERR_EXCEPTION_NOT_PENDING.value)


def test_close_expires_attestation_and_auto_denies_exception(api):
    """PRD §3.6: "Closing a campaign — manually by a `ComplianceAdmin`, or by
    step 5 of the sweep once the current time is strictly later than
    `window_close_at` — requires the campaign to be `OPEN`
    (`ERR_CAMPAIGN_NOT_OPEN`) and expires everything still in flight: `PENDING`,
    `BLOCKED`, and `EXCEPTION_PENDING` attestations all become `EXPIRED`, and
    their still-`REQUESTED` exceptions are denied by the system with the
    `decision_note` string `AUTO_DENIED_AT_CLOSE`."
    PRD §3.6: "the attestation must be `PENDING` — `BLOCKED`, `EXPIRED`, and
    `ATTESTED` all draw `ERR_ATTESTATION_NOT_ACTIONABLE`"

    Design: Corner/errors/attest_on_expired_attestation_and_auto_denied_exception
    """
    ctx = setup_open_campaign_with_attestation("AC")
    emp, mgr, att = ctx["employee"], ctx["manager"], ctx["attestation"]
    request_exception(
        att["id"], mgr["id"], reason_code="OTHER",
        detail="Pending role transition review",
    )

    closed = get_success_data(api.close_campaign(ctx["campaign"]["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    assert get_attestation_data(att["id"])["status"] == "EXPIRED"

    exceptions, meta = validate_paginated(api.list_attestation_exceptions(att["id"], ADMIN))
    assert meta["total_count"] == 1
    assert exceptions[0]["status"] == "DENIED"
    assert exceptions[0]["decision_note"] == "AUTO_DENIED_AT_CLOSE"

    resp = api.attest(att["id"], make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_ATTESTATION_NOT_ACTIONABLE.value)
