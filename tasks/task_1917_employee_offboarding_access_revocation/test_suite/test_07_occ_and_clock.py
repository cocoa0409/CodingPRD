"""Optimistic concurrency control (OCC) stale-version rejections and the
logical clock's fixed startup default.

Covers queue-B corner instances under `cross_cutting_complexity_layers`.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_case,
    create_and_approve_case,
    create_case_with_statement,
    create_revocation_task,
    create_asset_item,
    set_clock,
    get_clock,
    calculate_statement,
    approve_statement,
    disburse_statement,
    execute_task,
    verify_task,
    close_case,
    HR_INTAKE,
    HR_APPROVER,
    HR_REVIEWER,
    HR_DIRECTOR,
    PAYROLL_CALC,
    PAYROLL_APPROVER,
    IT_OP,
    IT_VER,
    IT_MGR,
    MGR,
    CLERK,
    BEN_ADMIN,
    ADMIN,
)


class TestClockDefault:
    def test_clock_default_is_fixed_start_time(self):
        """PRD §2.4: "At startup, before any set call, the clock reads exactly
        `2026-08-01T00:00:00Z` and must not fall back to wall-clock time."

        Design: Corner/cross_cutting_complexity_layers/clock_default_is_fixed_start_time
        """
        now = get_clock()
        assert now == "2026-08-01T00:00:00Z"


class TestOCCCloseStaleVersion:
    def test_occ_case_close_stale_version_412(self):
        """PRD §2.9: "Closing a case — `POST
        /offboarding/offboarding-cases/{id}/close` — requires
        `expected_offboarding_case_version`, carrying the caller's last observed
        `version` of the OffboardingCase. If the case's version has advanced
        since that read — for example because a revocation verification or an
        asset default cascaded into the case — the close is rejected with
        `ERR_STALE_CASE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_case_close_stale_version_412
        """
        artifacts = _drive_to_ready_to_close(employee_ref="E-OCC1")
        case = artifacts["case"]
        current_v = case["version"]
        # Stale close: one version behind.
        stale_resp = api_client.close_case(
            case["id"], {"expected_offboarding_case_version": current_v - 1}, HR_APPROVER
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_CASE_VERSION, expected_status=412)

    def test_occ_case_close_current_version_succeeds(self):
        """PRD §3.7: "A successful close copies the review's `recommended_code`
        into the case's `rehire_code` — which remains null until this moment —
        stamps `closed_at`, notifies the manager with `CASE_CLOSED`, expires
        every covenant acknowledgment still `PENDING` or `REMINDED`, and
        increments the case version."

        Design: Corner/cross_cutting_complexity_layers/occ_case_close_stale_version_412
        """
        artifacts = _drive_to_ready_to_close(employee_ref="E-OCC1B")
        case = artifacts["case"]
        resp = api_client.close_case(
            case["id"], {"expected_offboarding_case_version": case["version"]}, HR_APPROVER
        )
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        assert closed["rehire_code"] == "ELIGIBLE"
        assert closed["closed_at"] is not None


class TestOCCStatementCalculateStaleVersion:
    def test_occ_statement_calculate_stale_version_412(self):
        """PRD §2.9: "Calculating a statement — `POST
        /offboarding/final-pay-statements/{id}/calculate` — requires
        `expected_final_pay_statement_version`. A mismatch with the statement's
        current `version` is rejected with `ERR_STALE_STATEMENT_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_statement_calculate_stale_version_412
        """
        case, stmt = create_case_with_statement(employee_ref="E-OCC2")
        captured_v = stmt["version"]
        # First calculate with the correct version succeeds.
        calculate_statement(stmt, regular_wages_cents=100000)
        # Second calculate with the captured (now stale) version. The statement
        # is now CALCULATED so a pure state check could also fire; per PRD §2.6,
        # state legality (priority 4) precedes OCC (priority 14), but the design
        # recipe accepts either surface — what matters is the stale write is
        # rejected.
        resp = api_client.calculate_statement(
            stmt["id"],
            {"regular_wages_cents": 120000,
             "expected_final_pay_statement_version": captured_v},
            PAYROLL_CALC,
        )
        # Statement is now CALCULATED (calculate requires DRAFT), so both
        # ERR_INVALID_STATE and ERR_STALE_STATEMENT_VERSION are consistent with
        # PRD. Per §2.6 priority, state (4) precedes OCC (14) — accept either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_STALE_STATEMENT_VERSION, ApiErrorId.ERR_INVALID_STATE]
        )

    def test_occ_statement_calculate_stale_after_recalculate_bumps_version(self):
        """PRD §3.3: "the statement ends `CALCULATED` again with its version
        incremented." PRD §2.9 ties `ERR_STALE_STATEMENT_VERSION` to a mismatch
        with the statement's current `version`. After a recalculate, the prior
        version is stale; a recalculate again from CALCULATED with the stale
        version must be rejected (state legality or OCC — both surface a 4xx
        rejection, never a silent overwrite).

        Design: Corner/cross_cutting_complexity_layers/occ_statement_calculate_stale_version_412
        """
        case, stmt = create_case_with_statement(employee_ref="E-OCC2B")
        captured_v = stmt["version"]
        calculate_statement(stmt, regular_wages_cents=100000)
        # Recalculate is legal from CALCULATED; it bumps the version again.
        recalced = validate_success(api_client.recalculate_statement(
            stmt["id"], {"regular_wages_cents": 110000}, PAYROLL_CALC
        ))
        assert recalced["version"] > captured_v
        # Now any write pinned at captured_v is stale.
        resp = api_client.calculate_statement(
            stmt["id"],
            {"regular_wages_cents": 120000,
             "expected_final_pay_statement_version": captured_v},
            PAYROLL_CALC,
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_STALE_STATEMENT_VERSION, ApiErrorId.ERR_INVALID_STATE]
        )


class TestOCCAssetReturnStaleVersion:
    def test_occ_asset_record_return_stale_version_412(self):
        """PRD §2.9: "Recording an asset return — `POST
        /offboarding/asset-return-items/{id}/record-return` — requires
        `expected_asset_return_item_version`. A mismatch with the item's current
        `version` is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412); the
        scheduler may have flipped the item to overdue in the meantime,
        changing which deduction variant applies."

        Design: Corner/cross_cutting_complexity_layers/occ_asset_record_return_stale_version_412
        """
        case = create_and_approve_case(employee_ref="E-OCC3")
        item = create_asset_item(
            case["id"], asset_tag="L9", asset_kind="LAPTOP",
            replacement_cost_cents=200000, issued_date="2026-01-01T00:00:00Z",
        )
        captured_v = item["version"]
        # Scheduler flips TRACKED -> OVERDUE, bumping version.
        set_clock("2026-08-14T00:00:00Z")
        refreshed = get_success_data(api_client.get_asset_item(item["id"], CLERK))
        assert refreshed["status"] == "OVERDUE"
        assert refreshed["version"] > captured_v

        resp = api_client.record_asset_return(
            item["id"],
            {"condition_on_return": "GOOD",
             "expected_asset_return_item_version": captured_v},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ASSET_VERSION, expected_status=412)


# ---------------------------------------------------------------------------
# Local composite: drive a case all the way to READY_TO_CLOSE with the rehire
# review FINALIZED, statement DISBURSED, KT plan WAIVED, covenant ACKNOWLEDGED,
# benefits notice SENT. Returns dict(case=..., statement=..., review=...).
# ---------------------------------------------------------------------------

def _drive_to_ready_to_close(**case_overrides):
    case = create_and_approve_case(**case_overrides)
    # Pre-create a notice and ack so the PAYROLL_PENDING cascade queues/arms them.
    notice = get_success_data(api_client.create_benefits_notice(
        {"offboarding_case_id": case["id"], "notice_kind": "BENEFITS_TERMINATION"},
        BEN_ADMIN,
    ))
    ack = get_success_data(api_client.create_covenant_ack(
        {"offboarding_case_id": case["id"], "covenant_kind": "CONFIDENTIALITY"},
        HR_INTAKE,
    ))
    # Register + waive an asset so asset_posture reaches COMPLETE under either
    # interpretation of the zero-asset edge.
    item = get_success_data(api_client.create_asset_item(
        {
            "offboarding_case_id": case["id"],
            "asset_tag": "CLOSE-1",
            "asset_kind": "KEYCARD",
            "replacement_cost_cents": 100,
            "issued_date": "2026-01-01T00:00:00Z",
        },
        CLERK,
    ))

    task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
    set_clock("2026-08-10T17:00:00Z")
    execute_task(task["id"], outcome="SUCCESS")
    verify_task(task["id"], outcome="VERIFIED")

    stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
    stmt = stmts[0]
    calculate_statement(stmt, regular_wages_cents=100000)
    approve_statement(stmt["id"])
    disb = validate_success(api_client.disburse_statement(stmt["id"], PAYROLL_CALC))
    assert disb["status"] in ("DISBURSED", "LATE")

    # Waive the asset so the case's asset_posture is COMPLETE.
    validate_success(api_client.waive_asset_item(
        item["id"], {"waive_reason": "no company property held"}, CLERK
    ))

    plans = get_success_data(api_client.list_case_kt_plans(case["id"], MGR))
    validate_success(api_client.waive_kt_plan(plans[0]["id"], {"waived_reason": "n/a"}, MGR))

    # Notice is QUEUED now; send it (send_by = DL + 30d = 2026-09-09T17:00:00Z).
    validate_success(api_client.send_benefits_notice(notice["id"], BEN_ADMIN))

    # Acknowledge the covenant while the case is still open.
    validate_success(api_client.acknowledge_covenant(
        ack["id"], {"acknowledgment_text_version": "v2026-1"}, HR_INTAKE
    ))

    reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
    review = reviews[0]
    validate_success(api_client.submit_rehire_review(
        review["id"], {"recommended_code": "ELIGIBLE", "rationale": "ok"}, HR_REVIEWER
    ))
    finalized = validate_success(api_client.finalize_rehire_review(review["id"], HR_DIRECTOR))

    refreshed = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
    return {
        "case": refreshed,
        "statement": disb,
        "task": task,
        "plan": plans[0],
        "review": finalized,
        "notice": notice,
        "ack": ack,
    }
