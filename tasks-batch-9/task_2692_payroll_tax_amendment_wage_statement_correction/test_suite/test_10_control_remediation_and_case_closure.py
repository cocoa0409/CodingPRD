"""Control remediation and the closure gates that depend on it.

Closure is the only terminal act on a case, and it is the one place where a child
row the system created for itself can refuse a parent transition. This file pins
the remediation gate and the repayment gate separately, the duty split on
verification, and the version arithmetic of the remediation row itself.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_REMEDIATION_NOT_VERIFIED,
    ERR_REPAYMENT_NOT_SETTLED,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
)
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_case_rollups,
    assert_pagination,
)
from test_helpers.constants import CANON_CLOCK
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    OFFICER_HEADERS,
    OWNER_AUDITOR_HEADERS,
    OWNER_ELI_AUDITOR_HEADERS,
    PREPARER_HEADERS,
    USER_AUDITOR,
    USER_OWNER_CASS,
    USER_OWNER_ELI,
)


def _cascade_remediation(api, case_id):
    """The remediation the acceptance cascade created, reachable only by the list filter."""
    rows, meta = validate_paginated(
        api.list_control_remediations({"correction_case_id": case_id}, AUDITOR_HEADERS)
    )
    assert_pagination(meta, total_count=1)
    return rows[0]


def _open_remediation_count(api, employer_id):
    return validate_success(api.get_employer(employer_id, ADMIN_HEADERS))[
        "open_remediation_count"
    ]


class TestClosureRemediationGate:
    def test_the_ownerless_remediation_the_join_created_refuses_the_close(self, api):
        """Every other precondition is met — the case is in `REMEDIATION_PENDING`, the
        discrepancy count is 0 and no repayment exists — so the only thing left to refuse
        the closure is the remediation the acceptance created, which is still `OPEN` and
        cannot even be submitted for verification because it has no owner.

        PRD: "Closure is available only from `REMEDIATION_PENDING`, accepts an optional `closure_note`, and requires three things beyond that state: the case's `open_discrepancy_count` must be 0; every remediation on the case must be in `status` `VERIFIED`, or the request is refused with `ERR_REMEDIATION_NOT_VERIFIED`; and every wage repayment on the case must be in a terminal status of `COLLECTED`, `WRITTEN_OFF` or `CANCELLED`, or the request is refused with `ERR_REPAYMENT_NOT_SETTLED`."
        PRD: "A remediation with no owner cannot be submitted for verification, so assignment is the act that unlocks it."
        PRD: "Remediation lists can be narrowed by `correction_case_id`, `root_cause_code`, `control_gap_class` and `status`; a remediation that the acceptance cascade created rather than a human is discoverable only through that filtered list, because nothing in the acceptance response names it."

        Design: Difficulty/cross_entity_state_dependency/case_close_depends_on_every_remediation_reaching_verified
        """
        ctx = fx.federal_accepted_amendment(api)
        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(
            case,
            status="REMEDIATION_PENDING",
            filing_status="FILING_COMPLETE",
            statement_status="STMT_NOT_REQUIRED",
        )
        assert_case_rollups(case, open_discrepancy_count=0)
        _, repayment_meta = validate_paginated(
            api.list_wage_repayments({"correction_case_id": ctx["case_id"]}, ANALYST_HEADERS)
        )
        assert_pagination(repayment_meta, total_count=0)
        blocker = _cascade_remediation(api, ctx["case_id"])
        assert blocker["status"] == "OPEN"
        assert blocker["owner_user_id"] is None

        validate_error(
            api.close_case(
                ctx["case_id"],
                f.close_case_payload(
                    closure_note="Filing complete; attempting closure with the remediation open."
                ),
                OFFICER_HEADERS,
            ),
            ERR_REMEDIATION_NOT_VERIFIED,
            409,
        )

        held = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(held, status="REMEDIATION_PENDING")
        assert held["closed_at"] is None
        assert _open_remediation_count(api, ctx["employer_id"]) == 1

    def test_an_assignment_and_an_independent_pass_release_the_closure(self, api):
        """The closer cannot reach `VERIFIED` directly: an owner has to be named, that owner
        has to produce evidence, and a third identity has to accept it. Only then does the
        very same close call succeed and stamp the case terminal.

        PRD: "Assignment is available while the remediation's `status` is `OPEN` or `VERIFICATION_FAILED`; it sets `owner_user_id` from the request, replaces `target_date` when a new one is supplied, and increments the remediation's `version` by 1."
        PRD: "When `passed` is true the remediation transitions `SUBMITTED_FOR_VERIFICATION → VERIFIED`, `verified_by_user_id` is set from the acting `X-User-ID`, `verified_at` is stamped from the logical clock, the employer's `open_remediation_count` is recomputed because this remediation has left the counted set, and `version` is incremented by 1; `VERIFIED` is terminal, and a further transition attempt is refused with `ERR_ALREADY_TERMINAL`."
        PRD: "On success the case transitions `REMEDIATION_PENDING → CLOSED`, `closed_at` is stamped from the logical clock, the employer's `open_exposure_cents` is recomputed so that the case's whole exposure drops out, the employer's `open_remediation_count` is decremented, and the case's `version` is incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/case_close_depends_on_every_remediation_reaching_verified
        """
        ctx = fx.federal_accepted_amendment(api)
        remediation_id = _cascade_remediation(api, ctx["case_id"])["id"]
        validate_error(
            api.close_case(ctx["case_id"], f.close_case_payload(), OFFICER_HEADERS),
            ERR_REMEDIATION_NOT_VERIFIED,
            409,
        )

        assigned = validate_success(
            api.assign_control_remediation(
                remediation_id,
                f.assign_payload(USER_OWNER_CASS, target_date="2026-06-30"),
                AUDITOR_HEADERS,
            )
        )
        assert assigned["owner_user_id"] == USER_OWNER_CASS
        assert assigned["target_date"].startswith("2026-06-30")
        assert assigned["status"] == "OPEN"

        submitted = validate_success(
            api.submit_remediation_verification(
                remediation_id,
                f.submit_verification_payload(
                    evidence_reference="EV-2026-0442 rate table refresh runbook"
                ),
                OWNER_AUDITOR_HEADERS,
            )
        )
        assert submitted["status"] == "SUBMITTED_FOR_VERIFICATION"
        assert submitted["verification_round"] == 1

        verified = validate_success(
            api.verify_control_remediation(
                remediation_id,
                f.verify_payload(True, verification_note="Refresh job scheduled and evidenced."),
                AUDITOR_HEADERS,
            )
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_AUDITOR
        assert verified["verified_at"] == "2026-04-30T00:00:00.000Z"
        assert _open_remediation_count(api, ctx["employer_id"]) == 0

        closed = validate_success(
            api.close_case(
                ctx["case_id"],
                f.close_case_payload(closure_note="Remediation verified; closing."),
                OFFICER_HEADERS,
            )
        )

        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] == "2026-04-30T00:00:00.000Z"
        _, meta = validate_paginated(
            api.list_control_remediations(
                {"correction_case_id": ctx["case_id"], "status": "VERIFIED"}, AUDITOR_HEADERS
            )
        )
        assert_pagination(meta, total_count=1)


def _remediation_awaiting_verification(api, owner_user_id=USER_OWNER_CASS, **overrides):
    """An employer, a federal agency, an open case and one remediation owned by
    `owner_user_id` that its own owner has already evidenced."""
    fx.set_clock(api, CANON_CLOCK)
    employer = fx.make_employer(api)
    agency = fx.make_federal_agency(api)
    case = fx.make_correction_case(api, employer["id"], agency["id"])
    remediation = validate_success(
        api.create_control_remediation(
            f.control_remediation_payload(
                case["id"], owner_user_id=owner_user_id, **overrides
            ),
            AUDITOR_HEADERS,
        ),
        201,
    )
    return {
        "employer_id": employer["id"],
        "case_id": case["id"],
        "remediation": remediation,
        "remediation_id": remediation["id"],
    }


class TestVerificationDutySplit:
    def test_the_owner_is_refused_and_a_second_auditor_accepts_the_same_evidence(self, api):
        """Both calls carry the `ControlsAuditor` role and both are legitimate uses of it, so
        the refusal cannot be a role decision: it is the collision between the acting
        identity and the recorded owner, and moving that identity is the whole fix.

        PRD: "It is available from `SUBMITTED_FOR_VERIFICATION`, takes a boolean `passed` and an optional `verification_note`, and requires the acting `X-User-ID` to differ from the remediation's `owner_user_id`; an owner verifying their own work is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."
        PRD: "The row is written in `status` `OPEN` with `evidence_reference`, `verified_by_user_id` and `verified_at` at null and `verification_round` at 0, and the employer's `open_remediation_count` — the number of remediations belonging to any case of that employer whose `status` is `OPEN`, `SUBMITTED_FOR_VERIFICATION` or `VERIFICATION_FAILED` — is recomputed."
        PRD: "When `passed` is true the remediation transitions `SUBMITTED_FOR_VERIFICATION → VERIFIED`, `verified_by_user_id` is set from the acting `X-User-ID`, `verified_at` is stamped from the logical clock, the employer's `open_remediation_count` is recomputed because this remediation has left the counted set, and `version` is incremented by 1; `VERIFIED` is terminal, and a further transition attempt is refused with `ERR_ALREADY_TERMINAL`."

        Design: Corner/rbac/remediation_owner_cannot_verify_their_own_remediation
        """
        ctx = _remediation_awaiting_verification(api)
        assert ctx["remediation"]["owner_user_id"] == USER_OWNER_CASS
        assert _open_remediation_count(api, ctx["employer_id"]) == 1
        submitted = validate_success(
            api.submit_remediation_verification(
                ctx["remediation_id"], f.submit_verification_payload(), OWNER_AUDITOR_HEADERS
            )
        )
        assert submitted["status"] == "SUBMITTED_FOR_VERIFICATION"

        validate_error(
            api.verify_control_remediation(
                ctx["remediation_id"], f.verify_payload(True), OWNER_AUDITOR_HEADERS
            ),
            ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            403,
        )

        held = validate_success(
            api.get_control_remediation(ctx["remediation_id"], AUDITOR_HEADERS)
        )
        assert held["status"] == "SUBMITTED_FOR_VERIFICATION"
        assert held["verified_by_user_id"] is None
        assert held["verified_at"] is None
        assert _open_remediation_count(api, ctx["employer_id"]) == 1

        verified = validate_success(
            api.verify_control_remediation(
                ctx["remediation_id"], f.verify_payload(True), AUDITOR_HEADERS
            )
        )

        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_AUDITOR
        assert verified["verification_round"] == 1
        assert _open_remediation_count(api, ctx["employer_id"]) == 0


class TestRemediationVersioning:
    def test_each_accepted_write_advances_the_version_and_the_reads_leave_it_alone(self, api):
        """Four values are pinned in sequence — 1 at creation, 2 after the assignment, 3 after
        the evidence and 4 after the pass — with a read interleaved twice to show that
        observing the row is not a mutation of it.

        PRD: "Most entities additionally carry `updated_at`, with the same format as `created_at` and refreshed on every mutation, and `version`, an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row."
        PRD: "Applied to an `OPEN` remediation this is a self-loop — the state does not change, only the fields — and it is the sole route by which an auto-created remediation acquires the owner its next transition requires."
        PRD: "On success the remediation transitions to `SUBMITTED_FOR_VERIFICATION`, the supplied `evidence_reference` is stored, `verification_round` is incremented by 1 — so it counts every attempt, not just the successful one — and `version` is incremented by 1."

        Design: Corner/cross-cutting complexity layers/control_remediation_version_increments_on_every_write
        """
        ctx = _remediation_awaiting_verification(
            api, root_cause_code="MANUAL_ENTRY_ERROR", target_date="2026-06-30"
        )
        created = ctx["remediation"]
        assert created["version"] == 1
        assert created["status"] == "OPEN"

        first_read = validate_success(
            api.get_control_remediation(ctx["remediation_id"], AUDITOR_HEADERS)
        )
        assert first_read["version"] == 1

        assigned = validate_success(
            api.assign_control_remediation(
                ctx["remediation_id"],
                f.assign_payload(USER_OWNER_ELI, target_date="2026-07-31"),
                AUDITOR_HEADERS,
            )
        )
        assert assigned["version"] == 2
        assert assigned["status"] == "OPEN"
        assert assigned["owner_user_id"] == USER_OWNER_ELI
        assert assigned["target_date"].startswith("2026-07-31")

        submitted = validate_success(
            api.submit_remediation_verification(
                ctx["remediation_id"],
                f.submit_verification_payload(evidence_reference="EV-2025Q1-002"),
                OWNER_ELI_AUDITOR_HEADERS,
            )
        )
        assert submitted["version"] == 3
        assert submitted["verification_round"] == 1
        assert submitted["evidence_reference"] == "EV-2025Q1-002"

        second_read = validate_success(
            api.get_control_remediation(ctx["remediation_id"], AUDITOR_HEADERS)
        )
        assert second_read["version"] == 3

        verified = validate_success(
            api.verify_control_remediation(
                ctx["remediation_id"], f.verify_payload(True), AUDITOR_HEADERS
            )
        )
        assert verified["version"] == 4
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_AUDITOR


def _closeable_case_holding_a_proposed_repayment(api):
    """The federal case driven to REMEDIATION_PENDING with its remediation verified, but
    carrying one repayment proposed while the case was still OPEN and never agreed."""
    ctx = fx.federal_categorized(api)
    ctx["repayment"] = fx.proposed_repayment(api, ctx["case_id"], ctx["employee"]["id"])
    amendment = fx.open_amendment(api, ctx["case_id"])
    validate_success(api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS))
    validate_success(api.sign_amended_return(amendment["id"], {}, OFFICER_HEADERS))
    validate_success(api.submit_amended_return(amendment["id"], {}, OFFICER_HEADERS))
    validate_success(
        api.record_agency_outcome(
            amendment["id"], f.agency_outcome_payload("ACCEPTED"), OFFICER_HEADERS
        )
    )
    remediation_id = _cascade_remediation(api, ctx["case_id"])["id"]
    validate_success(
        api.assign_control_remediation(
            remediation_id, f.assign_payload(USER_OWNER_CASS), AUDITOR_HEADERS
        )
    )
    validate_success(
        api.submit_remediation_verification(
            remediation_id, f.submit_verification_payload(), OWNER_AUDITOR_HEADERS
        )
    )
    ctx["remediation"] = validate_success(
        api.verify_control_remediation(
            remediation_id, f.verify_payload(True), AUDITOR_HEADERS
        )
    )
    ctx["remediation_id"] = remediation_id
    ctx["amended_return_id"] = amendment["id"]
    return ctx


class TestClosureRepaymentGate:
    def test_an_unagreed_proposal_holds_the_case_open_until_it_is_cancelled(self, api):
        """The remediation gate is already satisfied, so the only gate left is the repayment
        one — and it does not need the money: cancelling the proposal reaches a terminal
        status and the identical close call then succeeds, recovering nothing.

        PRD: "A single `PROPOSED` or `AGREED` repayment therefore holds a case open indefinitely."
        PRD: "The same act performed earlier means something different: from `PROPOSED`, where the employee never agreed to anything, the write-off cancels the proposal instead of writing off a balance, transitioning `PROPOSED → CANCELLED`, recording the `write_off_reason`, and incrementing `version` by 1."
        PRD: "An employer's `open_exposure_cents` is the sum of `total_exposure_cents` over every case belonging to that employer whose `status` is `OPEN` or `REMEDIATION_PENDING`."

        Design: Corner/errors/close_with_an_unsettled_repayment_returns_repayment_not_settled
        """
        ctx = _closeable_case_holding_a_proposed_repayment(api)
        assert ctx["repayment"]["status"] == "PROPOSED"
        assert ctx["remediation"]["status"] == "VERIFIED"
        booked = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(booked, status="REMEDIATION_PENDING")
        assert_case_rollups(booked, open_discrepancy_count=0, total_exposure_cents=335625)
        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_exposure_cents"] == 335625

        validate_error(
            api.close_case(
                ctx["case_id"],
                f.close_case_payload(
                    closure_note="Filing amended and control remediated."
                ),
                OFFICER_HEADERS,
            ),
            ERR_REPAYMENT_NOT_SETTLED,
            409,
        )

        still_verified = validate_success(
            api.get_control_remediation(ctx["remediation_id"], AUDITOR_HEADERS)
        )
        assert still_verified["status"] == "VERIFIED"
        held = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(held, status="REMEDIATION_PENDING")
        assert held["closed_at"] is None

        cancelled = validate_success(
            api.write_off_wage_repayment(
                ctx["repayment"]["id"],
                f.write_off_payload(
                    write_off_reason="Employee separated; arrangement abandoned before agreement."
                ),
                OFFICER_HEADERS,
            )
        )
        assert cancelled["status"] == "CANCELLED"

        closed = validate_success(
            api.close_case(
                ctx["case_id"],
                f.close_case_payload(
                    closure_note="Filing amended, control remediated, repayment cancelled."
                ),
                OFFICER_HEADERS,
            )
        )

        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] == "2026-04-30T00:00:00.000Z"
        assert_case_rollups(closed, repayment_recovered_cents=0)
        settled = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert settled["open_exposure_cents"] == 0
