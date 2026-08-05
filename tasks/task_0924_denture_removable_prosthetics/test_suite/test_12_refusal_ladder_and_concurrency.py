"""The order of refusal where two rules are broken at once, and the three
supersede-style creates guarded by an expected-version field."""

from test_helpers import (
    ApiErrorId,
    CLINICAL_DIRECTOR_USER_ID,
    PROSTHODONTIST_USER_ID,
    assert_money,
    create_lab_case_payload,
    create_payment_plan_payload,
    fixtures as fx,
    make_clinical_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _delinquent_case_with_a_dispatched_lab_case(name, dob, phone):
    """An arch in LAB_FABRICATION with a DISPATCHED lab case, behind a raised gate.

    The arch version captured before the first lab-case create is returned too, so a
    later create can carry a genuinely stale `expected_case_arch_version`.
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    patient = fx.register_patient(full_name=name, date_of_birth=dob, phone=phone)
    lab = fx.register_lab()
    built = fx.drive_arch_to_lab_fabrication(patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 91)
    stale_arch_version = fx.arch_version(built["arch"]["id"])
    lab_case = fx.draft_lab_case(
        built["arch"]["id"], lab["id"], expected_case_arch_version=stale_arch_version
    )
    fx.dispatch_lab_case(lab_case["id"])
    plan = fx.open_payment_plan(
        patient["id"], built["case"]["id"], first_due_date="2026-05-05T00:00:00Z"
    )
    fx.set_clock("2026-05-20T00:00:00Z")
    plan = fx.assess_delinquency(plan["id"])
    return {
        "patient": patient,
        "lab": lab,
        "case": built["case"],
        "arch": built["arch"],
        "lab_case": lab_case,
        "plan": plan,
        "stale_arch_version": stale_arch_version,
    }


class TestWriteGatePreEmption:
    def test_the_write_gate_pre_empts_the_from_state_check_on_dispatch(self, api, front_office_headers):
        """PRD §2.10: "**Rung 5 — the global write gate.** Detailed in §2.11. Failure:
        `ERR_ACCOUNT_DELINQUENT`, HTTP 403. Scope: the gated family enumerated in
        §2.11. This rung sits above every schema, enum, concurrency, and state check,
        and therefore pre-empts 26 of the 31 rungs below it."
        PRD §2.11: "That policy is implemented as a single gate at rung 5: **the
        patient reached from the target resource must not own any `PaymentPlan` whose
        `plan_status` is `DELINQUENT` or `DEFAULTED`.** When such a plan exists, the
        call is refused with `ERR_ACCOUNT_DELINQUENT` and HTTP 403 *before* any
        body-reference, schema, enum, concurrency, or state check runs."

        Design: Difficulty/priority_pair_validation_conflict/write_gate_wins_over_invalid_state_on_lab_dispatch
        """
        ctx = _delinquent_case_with_a_dispatched_lab_case(
            "Liesel Onwuka", "1954-03-30", "555-0333"
        )
        assert ctx["plan"]["plan_status"] == "DELINQUENT"
        assert ctx["plan"]["missed_count"] == 1
        assert fx.read_patient(ctx["patient"]["id"])["write_gate_active"] is True

        response = api.dispatch_lab_case(ctx["lab_case"]["id"], front_office_headers)
        validate_error(response, ApiErrorId.ERR_ACCOUNT_DELINQUENT.value, 403)

    def test_the_pre_empted_dispatch_leaves_the_lab_case_untouched(self, api, front_office_headers):
        """PRD §2.10: "The server evaluates its checks as a strict ladder of 31 rungs in
        the order below, stops at the first rung that fails, and returns that rung's
        code. A rung that a request does not reach never runs and never writes anything
        (with the two deliberate exceptions called out in §2.12)."
        PRD §2.10: "**Rung 12 — from-state.** The target row's current state is a
        declared origin state of the transition the endpoint drives. Failure:
        `ERR_INVALID_STATE`, HTTP 409. Scope: every state-changing endpoint."

        Design: Difficulty/priority_pair_validation_conflict/write_gate_wins_over_invalid_state_on_lab_dispatch
        """
        ctx = _delinquent_case_with_a_dispatched_lab_case(
            "Liesel Onwuka", "1954-03-30", "555-0333"
        )
        before = fx.read_lab_case(ctx["lab_case"]["id"])
        assert before["lab_status"] == "DISPATCHED"

        validate_error(
            api.dispatch_lab_case(ctx["lab_case"]["id"], front_office_headers),
            ApiErrorId.ERR_ACCOUNT_DELINQUENT.value,
            403,
        )

        after = fx.read_lab_case(ctx["lab_case"]["id"])
        assert after["lab_status"] == "DISPATCHED"
        assert after["version"] == before["version"], (
            "the refused call wrote nothing to the lab case"
        )

    def test_the_write_gate_pre_empts_the_stale_version_check_on_a_lab_case_create(self, api, prosthodontist_headers):
        """PRD §2.10: "**Rung 9 — optimistic concurrency.** The supplied
        `expected_case_arch_version`, `expected_prosthesis_version`, or
        `expected_prosthesis_case_version` equals the current `version` of the named
        parent row, as specified in §2.8. Failure: `ERR_STALE_VERSION`, HTTP 412."
        PRD §2.11: "When such a plan exists, the call is refused with
        `ERR_ACCOUNT_DELINQUENT` and HTTP 403 *before* any body-reference, schema,
        enum, concurrency, or state check runs."

        Design: Difficulty/priority_pair_validation_conflict/write_gate_wins_over_stale_version_on_lab_case_create
        """
        ctx = _delinquent_case_with_a_dispatched_lab_case(
            "Nils Achterberg", "1946-06-06", "555-0355"
        )
        assert fx.arch_version(ctx["arch"]["id"]) > ctx["stale_arch_version"], (
            "the captured arch version is genuinely stale by at least one"
        )

        response = api.create_lab_case(
            create_lab_case_payload(
                ctx["arch"]["id"], ctx["lab"]["id"], ctx["stale_arch_version"], bench_line=2
            ),
            prosthodontist_headers,
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_DELINQUENT.value, 403)

    def test_the_pre_empted_lab_case_create_mints_no_row(self, api, prosthodontist_headers):
        """PRD §2.8: "- `POST /prosthetics/lab-cases` requires
        `expected_case_arch_version`, carrying the client's last observed `version` of
        the `CaseArch` named by `case_arch_id`. If that value does not equal the arch's
        current `version`, the create is rejected with `ERR_STALE_VERSION` and HTTP
        412."
        PRD §2.10: "This rung sits above every schema, enum, concurrency, and state
        check, and therefore pre-empts 26 of the 31 rungs below it."

        Design: Difficulty/priority_pair_validation_conflict/write_gate_wins_over_stale_version_on_lab_case_create
        """
        ctx = _delinquent_case_with_a_dispatched_lab_case(
            "Nils Achterberg", "1946-06-06", "555-0355"
        )

        validate_error(
            api.create_lab_case(
                create_lab_case_payload(
                    ctx["arch"]["id"], ctx["lab"]["id"], ctx["stale_arch_version"], bench_line=2
                ),
                prosthodontist_headers,
            ),
            ApiErrorId.ERR_ACCOUNT_DELINQUENT.value,
            403,
        )

        assert len(fx.lab_cases_of(ctx["arch"]["id"])) == 1, (
            "the refused create left the arch with only its original lab case"
        )


class TestTerminalStatePreEmption:
    def _approved_remake(self):
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Mirek Bassey", "date_of_birth": "1959-12-19", "phone": "555-0344"
            }
        )
        remake = fx.request_remake(
            ctx["arch"]["id"], reason_code="PATIENT_DISSATISFACTION",
            requester_user_id=PROSTHODONTIST_USER_ID,
        )
        fx.approve_remake(remake["id"], director_user_id=CLINICAL_DIRECTOR_USER_ID)
        ctx["remake_request"] = remake
        return ctx

    def test_a_self_approval_of_an_already_approved_remake_reports_the_terminal_gate(self, api):
        """PRD §2.10: "**Rung 10 — terminal state.** The target row is not already in a
        terminal state of the state axis the operation drives."
        PRD §2.10: "**Rung 14 — segregation of duties.** The `X-User-ID` approving or
        denying a remake request differs from that request's `requested_by_user_id`.
        Failure: `ERR_SEGREGATION_OF_DUTIES`, HTTP 403."
        PRD §3.7: "`APPROVED`, `DENIED`, and `FINAL_DENIED` are the three terminal
        states of the authorisation axis."

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_wins_over_segregation_of_duties_on_remake_approve
        """
        ctx = self._approved_remake()

        response = api.approve_remake_request(
            ctx["remake_request"]["id"],
            make_clinical_director_headers(PROSTHODONTIST_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_TERMINAL_STATE.value, 409)

    def test_the_pre_empted_second_approval_performs_no_second_increment(self, api):
        """PRD §3.7: "- **Link 1** sets `authorization_status` to `APPROVED`, records
        `approved_by_user_id` and `decided_at`, and increments the request's `version`
        by 1."
        PRD §3.7: "- **Link 2**, caused by link 1, moves the parent arch to
        `REMAKE_PENDING` — from `DELIVERED` when the appliance was already handed over,
        or from `MILESTONE_PENDING` when a try-in was rejected before any delivery ever
        happened — increases the arch's `remake_count` by one, and increments the arch's
        `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_wins_over_segregation_of_duties_on_remake_approve
        """
        ctx = self._approved_remake()

        validate_error(
            api.approve_remake_request(
                ctx["remake_request"]["id"],
                make_clinical_director_headers(PROSTHODONTIST_USER_ID),
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )

        request_after = fx.read_remake_request(ctx["remake_request"]["id"])
        assert request_after["approved_by_user_id"] == CLINICAL_DIRECTOR_USER_ID
        assert request_after["authorization_status"] == "APPROVED"
        assert fx.read_arch(ctx["arch"]["id"])["remake_count"] == 1, (
            "the refused call performed no second increment"
        )


class TestOptimisticConcurrency:
    def test_a_stale_arch_version_on_a_lab_case_create_is_rejected(self, api, prosthodontist_headers):
        """PRD §2.8: "- `POST /prosthetics/lab-cases` requires
        `expected_case_arch_version`, carrying the client's last observed `version` of
        the `CaseArch` named by `case_arch_id`. If that value does not equal the arch's
        current `version`, the create is rejected with `ERR_STALE_VERSION` and HTTP
        412. The rule exists because a newer draft lab case supersedes an older draft
        lab case on the same arch; without the check a second create working from a
        stale view of the arch would silently discard the first dispatch plan."

        Design: Corner/cross_cutting_layers/stale_case_arch_version_on_lab_case_create_is_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Sirpa Aalto", date_of_birth="1951-10-14", phone="555-1042"
        )
        lab = fx.register_lab()
        built = fx.drive_arch_to_lab_fabrication(patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 90)
        current_version = fx.arch_version(built["arch"]["id"])

        stale = api.create_lab_case(
            create_lab_case_payload(built["arch"]["id"], lab["id"], current_version - 1),
            prosthodontist_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert len(fx.lab_cases_of(built["arch"]["id"])) == 0, "the stale create minted no row"

        created = validate_success(
            api.create_lab_case(
                create_lab_case_payload(built["arch"]["id"], lab["id"], current_version),
                prosthodontist_headers,
            ),
            201,
        )
        assert created["lab_status"] == "DRAFT"
        assert fx.arch_version(built["arch"]["id"]) == current_version + 1, (
            "the successful create advanced the arch's version by exactly one"
        )

    def test_a_stale_case_version_on_a_payment_plan_create_is_rejected(self, api, front_office_headers):
        """PRD §2.8: "- `POST /prosthetics/payment-plans` requires
        `expected_prosthesis_case_version`, carrying the client's last observed
        `version` of the `ProsthesisCase` named by `case_id`. A mismatch with the case's
        current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412. A newer
        plan supersedes the case's current active or delinquent plan and strikes its
        principal from the case's patient responsibility, so a stale view of that amount
        would mint a schedule for the wrong balance."

        Design: Corner/cross_cutting_layers/stale_case_version_on_payment_plan_create_is_rejected
        """
        ctx = fx.setup_case_past_exam(
            patient_overrides={
                "full_name": "Teemu Jokinen", "date_of_birth": "1944-11-15", "phone": "555-1043"
            }
        )
        current_version = fx.case_version(ctx["case"]["id"])

        stale = api.create_payment_plan(
            create_payment_plan_payload(
                ctx["patient"]["id"], ctx["case"]["id"], current_version - 1
            ),
            front_office_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

        _, meta = validate_paginated(
            api.list_payment_plans(
                front_office_headers,
                params={"case_id": ctx["case"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0, "the stale create minted no plan"

        created = validate_success(
            api.create_payment_plan(
                create_payment_plan_payload(
                    ctx["patient"]["id"], ctx["case"]["id"], current_version
                ),
                front_office_headers,
            ),
            201,
        )
        assert_money(created["principal_amount"], 960.00, "PaymentPlan.principal_amount")
        assert len(fx.installments_of(created["id"])) == 3
        assert fx.case_version(ctx["case"]["id"]) == current_version + 1, (
            "the successful create advanced the case's version by exactly one"
        )
