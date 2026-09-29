"""Enrollment: three independent dimensions, one compound status, and the gates that guard them."""

from test_helpers import (
    assert_buyback_request,
    assert_compliance_case,
    assert_consultant,
    assert_enrollment_application,
    assert_instant,
    constants as k,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    make_applicant_headers,
    make_consultant_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_agreement_and_kit_dimensions_move_while_the_compound_status_stays_draft(api):
    """The agreement and kit dimensions advance on their own without moving the compound status.

    PRD §3.2: "Otherwise, if `agreement_status` is `ACCEPTED` and `identity_status` is `VERIFIED`
    and `kit_status` is `PAID`, the compound `status` is `READY_FOR_APPROVAL`; in every other
    combination it is `DRAFT`." And: "The dimensions otherwise advance freely and in any order,
    with one coupling: the kit may not be paid before the agreement is accepted, because an
    applicant may not be charged before signing."

    Design: Difficulty/non_linear_state_machine/enrollment_three_dimensions_advance_independently_with_identity_retry_cycle
    """
    env = fx.setup_environment(api)
    email = "pia@ex.test"
    application = fx.create_application(
        api, env, email, full_name="Pia Prospect", identity_document_reference=None
    )
    applicant = make_applicant_headers(email)

    assert application["kit_total_cents"] == 11129, "9900 wholesale plus 825 bp of 14900 SRP"
    assert application["identity_status"] == "UNVERIFIED"
    assert application["identity_attempt_count"] == 0

    accepted = validate_success(
        api.accept_agreement(application["id"], f.accept_agreement_payload(), applicant)
    )
    assert accepted["status"] == "DRAFT", "the agreement alone does not complete the rollup"
    assert accepted["agreement_status"] == "ACCEPTED"
    assert_instant(accepted["agreement_accepted_at"], k.INITIAL_CLOCK, "agreement_accepted_at")

    paid = validate_success(
        api.pay_starter_kit(
            application["id"], f.pay_starter_kit_payload(11129, "KIT-PAY-PIA"), applicant
        )
    )
    assert paid["status"] == "DRAFT", "the kit dimension moved while identity is still UNVERIFIED"
    assert paid["kit_status"] == "PAID"
    assert paid["identity_status"] == "UNVERIFIED"

    submitted = validate_success(
        api.submit_identity_documents(
            application["id"], f.identity_submission_payload("DOC-PIA-1"), applicant
        )
    )
    assert submitted["status"] == "DRAFT", "identity is under review, so the rollup is still DRAFT"
    assert submitted["identity_status"] == "PENDING_REVIEW"
    assert submitted["identity_attempt_count"] == 1, "the first submission is attempt 1"


def test_failed_identity_resubmission_verifies_and_mints_the_consultant(api):
    """A FAILED identity re-enters PENDING_REVIEW, and verification flips the rollup and mints.

    PRD §3.2: "A `FAIL` decision taken while `identity_attempt_count` is still below
    `max_identity_attempts` sets `identity_status` to `FAILED` and records
    `identity_failure_reason` from the payload, leaving the application in `DRAFT` so the applicant
    may resubmit." And: "On success the stored `identity_document_reference` is replaced,
    `identity_attempt_count` is incremented by 1, `identity_status` becomes `PENDING_REVIEW`, and
    `identity_failure_reason` is cleared to null."

    Design: Difficulty/non_linear_state_machine/enrollment_three_dimensions_advance_independently_with_identity_retry_cycle
    """
    env = fx.setup_environment(api)
    email = "pia@ex.test"
    application = fx.create_application(
        api, env, email, full_name="Pia Prospect", identity_document_reference=None
    )
    applicant = make_applicant_headers(email)
    validate_success(api.accept_agreement(application["id"], f.accept_agreement_payload(), applicant))
    validate_success(
        api.pay_starter_kit(
            application["id"], f.pay_starter_kit_payload(11129, "KIT-PAY-PIA"), applicant
        )
    )
    validate_success(
        api.submit_identity_documents(
            application["id"], f.identity_submission_payload("DOC-PIA-1"), applicant
        )
    )

    failed = validate_success(
        api.decide_identity(
            application["id"], f.identity_decision_payload("FAIL", "document illegible"), COMPLIANCE
        )
    )
    assert failed["status"] == "DRAFT", "attempt 1 of 2 failing does not reject the application"
    assert failed["identity_status"] == "FAILED"
    assert failed["identity_failure_reason"] == "document illegible"

    resubmitted = validate_success(
        api.submit_identity_documents(
            application["id"], f.identity_submission_payload("DOC-PIA-2"), applicant
        )
    )
    assert resubmitted["status"] == "DRAFT"
    assert resubmitted["identity_status"] == "PENDING_REVIEW", "FAILED re-enters PENDING_REVIEW"
    assert resubmitted["identity_attempt_count"] == 2
    assert resubmitted["identity_failure_reason"] is None, "the failure reason is cleared"

    verified = validate_success(
        api.decide_identity(application["id"], f.identity_decision_payload("VERIFY"), COMPLIANCE)
    )
    assert verified["identity_status"] == "VERIFIED"
    assert verified["status"] == "READY_FOR_APPROVAL", (
        "the third dimension completing flips the compound status"
    )

    consultant = validate_success(
        api.approve_enrollment_application(application["id"], None, COMPLIANCE), 201
    )
    assert is_valid_uuid(consultant["id"])
    assert consultant["rank_code"] == "CONSULTANT"
    assert consultant["genealogy_depth"] == 0, "a sponsorless application enrolls a genealogy root"
    assert consultant["status"] == "ACTIVE"

    final = validate_success(api.get_enrollment_application(application["id"], ADMIN))
    assert final["status"] == "APPROVED"
    assert final["created_consultant_id"] == consultant["id"]


def test_starter_kit_tax_basis_switches_with_the_facilitator_agreement(api):
    """The taxable basis is the kit's srp_cents in a facilitator state and its wholesale price otherwise.

    PRD §3.2: "The taxable basis is that product's `srp_cents` when the jurisdiction registered
    for `applicant_state_code` has a facilitator agreement active, and its `wholesale_price_cents`
    otherwise." And: "Under a facilitator agreement the applicant therefore pays wholesale for the
    merchandise but is taxed on the higher suggested retail price — the two amounts are
    intentionally different bases in the same calculation."

    Design: Corner/calculations/starter_kit_tax_basis_switches_with_the_facilitator_agreement
    """
    env = fx.setup_environment_both_states(api)
    kit = env["products"]["KIT-STD"]

    tx_response = api.create_enrollment_application(
        f.enrollment_application_payload(
            env["plan"]["id"],
            kit["id"],
            applicant_email="tex@ex.test",
            applicant_full_name="Tex Facilitator",
            applicant_state_code="TX",
        ),
        ADMIN,
    )
    tx_app = validate_success(tx_response, 201)

    nv_response = api.create_enrollment_application(
        f.enrollment_application_payload(
            env["plan"]["id"],
            kit["id"],
            applicant_email="nev@ex.test",
            applicant_full_name="Nev Netprice",
            applicant_state_code="NV",
        ),
        ADMIN,
    )
    nv_app = validate_success(nv_response, 201)

    assert tx_app["kit_charge_cents"] == 9900, "the kit charge is the product's wholesale price"
    assert nv_app["kit_charge_cents"] == 9900, "the kit charge never depends on the tax treatment"
    assert tx_app["kit_tax_cents"] == 1229, "TX taxes 825 bp on the 14900-cent suggested retail price"
    assert nv_app["kit_tax_cents"] == 678, "NV taxes 685 bp on the 9900-cent wholesale price"
    assert tx_app["kit_total_cents"] == 11129, "kit_total_cents is charge plus tax in TX"
    assert nv_app["kit_total_cents"] == 10578, "kit_total_cents is charge plus tax in NV"
    assert tx_app["kit_total_cents"] - nv_app["kit_total_cents"] == 551, (
        "the suggested-retail basis makes the same kit 551 cents dearer in the facilitator state"
    )
    assert_enrollment_application(tx_app)
    assert_enrollment_application(nv_app)


def test_initial_state_of_every_newly_created_row(api):
    """Every machine starts in its declared initial state, the order in two dimensions at once.

    PRD §3.2: "At creation, `agreement_status` is `NOT_ACCEPTED` and `kit_status` is `UNPAID`; if
    `identity_document_reference` was supplied in the creation payload, `identity_status` starts at
    `PENDING_REVIEW` with `identity_attempt_count` at 1, and if it was omitted, `identity_status`
    starts at `UNVERIFIED` with `identity_attempt_count` at 0."
    PRD §3.3: "`payment_status` moves across `PENDING`, `PAID`, `REFUNDED_PARTIAL` and
    `REFUNDED_FULL`, starting at `PENDING`."

    Design: Corner/state_machines/initial_state_of_every_newly_created_row
    """
    setup = fx.setup_single_root(api)
    env, consultant = setup["env"], setup["a"]
    period = env["periods"]["2026-08"]
    order = fx.place_and_pay_order(api, env, consultant, [("SERUM", 30)])
    assert order["total_due_cents"] == 69900, "30 SERUM ships free and is taxed on 120000 cents"

    fresh = validate_success(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                env["plan"]["id"],
                env["products"]["KIT-STD"]["id"],
                applicant_email="new@ex.test",
                applicant_full_name="New Prospect",
            ),
            ADMIN,
        ),
        201,
    )
    assert fresh["status"] == "DRAFT", "the compound status of a bare application is DRAFT"
    assert fresh["agreement_status"] == "NOT_ACCEPTED"
    assert fresh["identity_status"] == "UNVERIFIED", "no document was supplied at creation"
    assert fresh["kit_status"] == "UNPAID"
    assert fresh["identity_attempt_count"] == 0

    read = fx.read_consultant(api, consultant["id"])
    assert read["status"] == "ACTIVE", "a consultant is minted ACTIVE"
    assert read["rank_code"] == "CONSULTANT", "minting sets the rank_order 1 rung"
    assert read["rank_order"] == 1
    assert read["payout_hold"] is False
    assert read["clawback_balance_cents"] == 0
    assert read["reinstatement_count"] == 0
    assert_consultant(read)

    period_read = fx.read_period(api, period["id"])
    assert period_read["status"] == "OPEN", "a period's status starts at OPEN"
    assert period_read["reopen_count"] == 0

    order_read = validate_success(api.get_product_order(order["id"], ADMIN))
    assert order_read["payment_status"] == "PAID", "the paid order moved its payment dimension only"
    assert order_read["fulfillment_status"] == "NEW", "fulfillment starts at NEW and stays there"

    case = validate_success(
        api.create_compliance_case(
            f.compliance_case_payload(consultant["id"], "INCOME_CLAIM", "EV-1"), COMPLIANCE
        ),
        201,
    )
    assert case["status"] == "OPEN", "a case's status starts at OPEN"
    assert case["sanction_order"] == 0
    assert case["appeal_count"] == 0
    assert_compliance_case(case)

    buyback = validate_success(
        api.create_buyback_request(
            f.buyback_request_payload(
                consultant["id"],
                [f.buyback_line(order["id"], env["products"]["SERUM"]["id"], 1, "RESALABLE")],
            ),
            ADMIN,
        ),
        201,
    )
    assert buyback["status"] == "REQUESTED", "a buyback request's status starts at REQUESTED"
    assert buyback["requested_volume_points"] == 20
    assert buyback["gross_refund_cents"] == 1800, "9000 bp of 2000 cents of eligible wholesale"
    assert buyback["net_refund_cents"] == 1800, "no restocking fee at or below 45000 and no clawback"
    assert buyback["volume_reversal_period_code"] == "2026-08"
    assert_buyback_request(buyback)


def test_illegal_triggers_on_the_three_enrollment_dimensions(api):
    """Each dimension write is refused with its own error rather than a generic one.

    PRD §3.2: "A write against an application whose `status` is `APPROVED`, `REJECTED` or
    `WITHDRAWN` is refused with `ERR_APPLICATION_TERMINAL`; and a write against an application that
    has already rolled up to `READY_FOR_APPROVAL` is refused with `ERR_APPLICATION_NOT_DRAFT`."
    And: "After the two state guards, the agreement test runs first: an unaccepted agreement is
    refused with `ERR_AGREEMENT_REQUIRED`, and only then is an already-paid kit refused with
    `ERR_KIT_ALREADY_PAID`."

    Design: Corner/state_machines/illegal_triggers_on_the_three_enrollment_dimensions
    """
    env = fx.setup_environment(api)
    ready = fx.create_application(api, env, "rita@ex.test", full_name="Rita Ready")
    fx.advance_application_to_ready(api, ready)
    pending = fx.create_application(
        api, env, "pat@ex.test", full_name="Pat Pending", identity_document_reference="DOC-PAT-1"
    )
    bare = fx.create_application(
        api, env, "bea@ex.test", full_name="Bea Bare", identity_document_reference=None
    )

    ready_read = validate_success(api.get_enrollment_application(ready["id"], ADMIN))
    assert ready_read["status"] == "READY_FOR_APPROVAL", "all three dimensions are satisfied"
    assert pending["identity_status"] == "PENDING_REVIEW", "a document at creation is attempt 1"
    assert pending["identity_attempt_count"] == 1

    validate_error(
        api.submit_identity_documents(
            pending["id"], f.identity_submission_payload("DOC-PAT-2"), ADMIN
        ),
        "ERR_IDENTITY_NOT_RESUBMITTABLE",
        409,
    )
    validate_error(
        api.decide_identity(bare["id"], f.identity_decision_payload("VERIFY"), COMPLIANCE),
        "ERR_IDENTITY_NOT_PENDING",
        409,
    )
    validate_error(
        api.approve_enrollment_application(bare["id"], None, COMPLIANCE),
        "ERR_ENROLLMENT_INCOMPLETE",
        409,
    )
    validate_error(
        api.pay_starter_kit(bare["id"], f.pay_starter_kit_payload(11129, "EARLY"), ADMIN),
        "ERR_AGREEMENT_REQUIRED",
        409,
    )
    validate_error(
        api.submit_identity_documents(
            ready["id"], f.identity_submission_payload("DOC-RITA-2"), ADMIN
        ),
        "ERR_APPLICATION_NOT_DRAFT",
        409,
    )
    validate_error(
        api.withdraw_enrollment_application(ready["id"], f.withdraw_payload("CHANGED_MIND"), ADMIN),
        "ERR_KIT_PAID_NOT_WITHDRAWABLE",
        409,
    )

    assert (
        validate_success(api.get_enrollment_application(ready["id"], ADMIN))["status"]
        == "READY_FOR_APPROVAL"
    ), "the refused writes left the ready application alone"
    assert (
        validate_success(api.get_enrollment_application(bare["id"], ADMIN))["status"] == "DRAFT"
    ), "the refused writes left the bare application in DRAFT"


def test_enrollment_gate_errors_cover_kit_sponsor_agreement_money_and_identity(api):
    """Seven enrollment gates each fire on a request that is otherwise perfectly formed.

    PRD §3.2: "First, the product named by `starter_kit_product_id` must have `is_starter_kit`
    true; an ordinary catalogue item is refused with `ERR_STARTER_KIT_INVALID`." And: "Third,
    `sponsor_consultant_id` may be omitted or null only by a `PlatformAdmin`, because a sponsorless
    application enrolls a genealogy root; any other caller omitting it is refused with
    `ERR_ROOT_ENROLLMENT_FORBIDDEN`." And PRD §3.3: "No line may name a product whose
    `is_starter_kit` is true, because starter kits are sold only through the enrollment flow; a
    violation is `ERR_PRODUCT_NOT_ORDERABLE`."

    Design: Corner/errors/enrollment_gate_errors_cover_kit_sponsor_agreement_money_and_identity
    """
    setup = fx.setup_single_root(api)
    env, sponsor = setup["env"], setup["a"]
    plan_zero = fx.create_plan(
        api, plan_code="PLAN-ZERO", name="Zero Retry Plan", max_identity_attempts=0
    )
    kit_id = env["products"]["KIT-STD"]["id"]
    serum_id = env["products"]["SERUM"]["id"]
    terminated = fx.enroll_consultant(
        api, env, "bob@example.com", "Bob Gone", sponsor_consultant_id=sponsor["id"]
    )
    terminated = fx.terminate_consultant(api, terminated)
    assert terminated["status"] == "TERMINATED"

    validate_error(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                env["plan"]["id"],
                serum_id,
                applicant_email="e1@ex.test",
                applicant_full_name="Eve One",
                sponsor_consultant_id=sponsor["id"],
            ),
            ADMIN,
        ),
        "ERR_STARTER_KIT_INVALID",
        422,
    )
    validate_error(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                env["plan"]["id"],
                kit_id,
                applicant_email="e2@ex.test",
                applicant_full_name="Eve Two",
            ),
            make_applicant_headers("e2@ex.test"),
        ),
        "ERR_ROOT_ENROLLMENT_FORBIDDEN",
        403,
    )
    validate_error(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                env["plan"]["id"],
                kit_id,
                applicant_email="e3@ex.test",
                applicant_full_name="Eve Three",
                sponsor_consultant_id=terminated["id"],
            ),
            ADMIN,
        ),
        "ERR_SPONSOR_NOT_ELIGIBLE",
        422,
    )

    valid = validate_success(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                env["plan"]["id"],
                kit_id,
                applicant_email="e4@ex.test",
                applicant_full_name="Eve Four",
                sponsor_consultant_id=sponsor["id"],
                identity_document_reference="DOC-E4",
            ),
            ADMIN,
        ),
        201,
    )
    assert valid["agreement_version"] == "AGR-2026-01", "the agreement version defaults"
    assert valid["kit_total_cents"] == 11129, "9900 plus 825 bp of the 14900-cent SRP basis"
    applicant = make_applicant_headers("e4@ex.test")

    validate_error(
        api.accept_agreement(valid["id"], f.accept_agreement_payload("AGR-2025-99"), applicant),
        "ERR_AGREEMENT_VERSION_MISMATCH",
        422,
    )
    accepted = validate_success(
        api.accept_agreement(valid["id"], f.accept_agreement_payload("AGR-2026-01"), applicant)
    )
    assert accepted["agreement_status"] == "ACCEPTED", "the exact version is accepted"
    validate_error(
        api.pay_starter_kit(
            valid["id"], f.pay_starter_kit_payload(11000, "SHORT-PAY"), applicant
        ),
        "ERR_KIT_AMOUNT_MISMATCH",
        422,
    )

    zero = validate_success(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                plan_zero["id"],
                kit_id,
                applicant_email="e5@ex.test",
                applicant_full_name="Eve Five",
            ),
            ADMIN,
        ),
        201,
    )
    assert zero["identity_attempt_count"] == 0
    validate_error(
        api.submit_identity_documents(zero["id"], f.identity_submission_payload("DOC-E5"), ADMIN),
        "ERR_IDENTITY_ATTEMPTS_EXHAUSTED",
        422,
    )

    validate_error(
        api.create_product_order(
            f.product_order_payload(
                sponsor["id"],
                [f.order_line(serum_id, 1), f.order_line(kit_id, 1)],
                order_type="PERSONAL_INVENTORY",
            ),
            ADMIN,
        ),
        "ERR_PRODUCT_NOT_ORDERABLE",
        422,
    )


def test_terminal_states_refuse_every_further_trigger(api):
    """Approved and withdrawn applications absorb every trigger, and a termination cannot repeat.

    PRD §3.2: "If `status` is already one of the terminal values `APPROVED`, `REJECTED` or
    `WITHDRAWN`, it is frozen and no re-derivation occurs." And PRD §3.8: "Two checks guard it, in
    this order: the consultant must not already be `TERMINATED`, or
    `ERR_CONSULTANT_ALREADY_TERMINATED`; and no commission run in status `APPROVED` may cover a
    period in which this consultant holds an `ACTIVE` statement, or
    `ERR_APPROVED_RUN_BLOCKS_TERMINATION`, because an approved-but-unpaid run must be settled
    before the earner's genealogy is rewritten under it."

    Design: Corner/state_machines/terminal_states_refuse_every_further_trigger
    """
    env = fx.setup_environment(api)
    approved_app = fx.create_application(api, env, "alice@example.com", full_name="Alice Root")
    fx.advance_application_to_ready(api, approved_app)
    consultant = validate_success(
        api.approve_enrollment_application(approved_app["id"], None, COMPLIANCE), 201
    )

    withdrawn_app = fx.create_application(api, env, "will@ex.test", full_name="Will Withdraw")
    withdrawn = validate_success(
        api.withdraw_enrollment_application(
            withdrawn_app["id"], f.withdraw_payload("CHANGED_MIND"), ADMIN
        )
    )
    assert withdrawn["status"] == "WITHDRAWN", "withdrawal is permitted while the kit is UNPAID"
    assert withdrawn["rejection_reason"] == "CHANGED_MIND"

    validate_error(
        api.accept_agreement(
            approved_app["id"],
            f.accept_agreement_payload(),
            make_applicant_headers("alice@example.com"),
        ),
        "ERR_APPLICATION_TERMINAL",
        409,
    )
    validate_error(
        api.submit_identity_documents(
            withdrawn_app["id"], f.identity_submission_payload("DOC-WILL-2"), ADMIN
        ),
        "ERR_APPLICATION_TERMINAL",
        409,
    )
    validate_error(
        api.approve_enrollment_application(withdrawn_app["id"], None, COMPLIANCE),
        "ERR_APPLICATION_TERMINAL",
        409,
    )

    terminated = fx.terminate_consultant(api, consultant, termination_reason="VOLUNTARY")
    assert terminated["status"] == "TERMINATED"
    assert_instant(terminated["terminated_at"], k.INITIAL_CLOCK, "terminated_at")
    assert terminated["termination_reason"] == "VOLUNTARY"

    validate_error(
        api.terminate_consultant(consultant["id"], f.termination_payload("VOLUNTARY"), COMPLIANCE),
        "ERR_CONSULTANT_ALREADY_TERMINATED",
        409,
    )
    again = fx.read_consultant(api, consultant["id"])
    assert_instant(again["terminated_at"], terminated["terminated_at"], "terminated_at")


def test_second_application_of_the_same_trigger_is_refused(api):
    """No successful trigger is silently idempotent, so no money effect can be applied twice.

    PRD §3.2: "After the two state guards, `agreement_status` must still be `NOT_ACCEPTED` —
    acceptance is not idempotent, and a second attempt is `ERR_AGREEMENT_ALREADY_ACCEPTED`".
    PRD §3.3: "and only then is `payment_status` required to be `PENDING`, since payment is not
    idempotent and a repeat is `ERR_ORDER_ALREADY_PAID`."
    PRD §3.7: "and `appeal_count` must be 0, since one appeal is permitted per case, or
    `ERR_APPEAL_ALREADY_FILED`."

    Design: Corner/state_machines/second_application_of_the_same_trigger_is_refused
    """
    env = fx.setup_environment(api)
    email = "alice@example.com"
    application = fx.create_application(api, env, email, full_name="Alice Root")
    applicant = make_applicant_headers(email)
    validate_success(api.accept_agreement(application["id"], f.accept_agreement_payload(), applicant))
    validate_success(
        api.decide_identity(application["id"], f.identity_decision_payload("VERIFY"), COMPLIANCE)
    )
    validate_success(
        api.pay_starter_kit(
            application["id"], f.pay_starter_kit_payload(11129, "KIT-PAY-A"), applicant
        )
    )
    consultant = validate_success(
        api.approve_enrollment_application(application["id"], None, COMPLIANCE), 201
    )
    order = fx.place_order(api, env, consultant, [("SERUM", 5)])
    assert order["total_due_cents"] == 12645
    fx.pay_order(api, consultant, order, amount_cents=12645, reference="PAY-A")

    # The order-payment trigger is probed while the consultant is still ACTIVE: PRD §3.3 runs the
    # consultant-status guard before the payment_status guard, so the same probe after the
    # suspension below would correctly answer ERR_CONSULTANT_NOT_ORDER_ELIGIBLE.
    validate_error(
        api.pay_product_order(order["id"], f.pay_order_payload(12645, "PAY-AGAIN"), ADMIN),
        "ERR_ORDER_ALREADY_PAID",
        409,
    )

    case = fx.open_case(api, consultant, claim_type="INCOME_CLAIM")
    fx.review_case(api, case)
    sanctioned = fx.sanction_case(
        api, case, "PROBATION", "2026-08-05T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    assert sanctioned["sanction_level"] == "PROBATION"
    assert sanctioned["sanction_order"] == 2, "PROBATION sits at ladder position 2"
    assert_instant(
        sanctioned["appeal_deadline_at"], "2026-08-19T00:00:00Z", "appeal_deadline_at"
    )
    appealed = fx.appeal_case(api, consultant, case)
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1
    fx.review_case(api, case)
    escalated = fx.sanction_case(
        api, case, "SUSPENSION", "2026-09-20T00:00:00Z", "2026-09-30T00:00:00Z"
    )
    assert escalated["sanction_order"] == 3, "SUSPENSION escalates above the recorded 2"

    # The agreement and kit triggers are probed on a second application still in DRAFT: PRD §3.2
    # runs the terminal check first, so the same probe against the APPROVED application above would
    # correctly answer ERR_APPLICATION_TERMINAL and never reach the idempotence rules.
    second_email = "bea@example.com"
    second = fx.create_application(api, env, second_email, full_name="Bea Draft")
    second_applicant = make_applicant_headers(second_email)
    validate_success(
        api.accept_agreement(second["id"], f.accept_agreement_payload(), second_applicant)
    )
    second_paid = validate_success(
        api.pay_starter_kit(
            second["id"], f.pay_starter_kit_payload(11129, "KIT-PAY-B"), second_applicant
        )
    )
    assert second_paid["status"] == "DRAFT", "identity is still UNVERIFIED, so no state guard fires"

    validate_error(
        api.accept_agreement(second["id"], f.accept_agreement_payload(), second_applicant),
        "ERR_AGREEMENT_ALREADY_ACCEPTED",
        409,
    )
    validate_error(
        api.pay_starter_kit(
            second["id"], f.pay_starter_kit_payload(11129, "KIT-PAY-B-AGAIN"), second_applicant
        ),
        "ERR_KIT_ALREADY_PAID",
        409,
    )
    second_read = validate_success(api.get_enrollment_application(second["id"], ADMIN))
    assert second_read["kit_payment_reference"] == "KIT-PAY-B", "the first reference stands"

    validate_error(
        api.appeal_compliance_case(
            case["id"],
            f.appeal_payload("Second appeal"),
            make_consultant_headers(consultant["id"]),
        ),
        "ERR_APPEAL_ALREADY_FILED",
        409,
    )

    application_read = validate_success(api.get_enrollment_application(application["id"], ADMIN))
    assert_instant(
        application_read["agreement_accepted_at"], k.INITIAL_CLOCK, "agreement_accepted_at"
    )
    assert application_read["kit_payment_reference"] == "KIT-PAY-A", "the first reference stands"

    qualification = fx.qualification_of(api, consultant["id"], env["periods"]["2026-08"]["id"])
    assert qualification["personal_volume_points"] == 100, "the volume was not posted twice"

    final = fx.read_consultant(api, consultant["id"])
    assert final["status"] == "SUSPENDED"
    assert final["highest_sanction_order"] == 3, "the escalation ladder records the highest rung"
