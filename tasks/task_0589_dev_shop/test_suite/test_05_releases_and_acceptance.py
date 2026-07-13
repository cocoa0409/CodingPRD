"""Staging, QA, client acceptance and deployment — including the three-link
acceptance cascade that reaches all the way into billing."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    CLOCK_DEFAULT,
    assert_instant_equals,
    assert_lines_sum_to_subtotal,
    assert_total_is_subtotal_plus_tax,
    fixtures,
)

DL = TEST_USERS["delivery_lead_headers"]
ENG = TEST_USERS["engineer_headers"]
ENG2 = TEST_USERS["engineer_2_headers"]
FIN = TEST_USERS["finance_officer_headers"]


def test_release_cycles_through_qa_failure_client_rejection_and_a_final_pass(api):
    """PRD 3.7: "Recording a staging QA result is an engineer action on an active engagement and always increments `qa_rounds` by 1."
    PRD 3.7: "An `action` of `REJECT` sends the release back for another round: `QA_PASSED → REWORK`. The linked milestone is deliberately left alone — it stays `PLANNED` — and from `REWORK` the engineer's next passing QA result returns the release to `QA_PASSED`, completing the cycle `QA_PASSED → REWORK → QA_PASSED`."

    Design: Corner/state_machines/release_qa_fail_then_client_reject_then_pass_cycle
    """
    ctx = fixtures.setup_building_release(version_label="v0.9.0")
    release_id = ctx["release"]["id"]

    failed = validate_success(api.record_qa_result(release_id, "FAIL", 2, ENG2))
    assert failed["status"] == "REWORK"
    assert failed["defect_count"] == 2, "defect_count reflects the most recent QA result"
    assert failed["qa_rounds"] == 1

    passed = validate_success(api.record_qa_result(release_id, "PASS", 0, ENG2))
    assert passed["status"] == "QA_PASSED"
    assert passed["qa_rounds"] == 2

    rejected = validate_success(
        api.decide_acceptance(
            release_id, "REJECT", ctx["client_headers"], note="Copy is wrong on the pricing page"
        )
    )
    assert rejected["status"] == "REWORK", "a client rejection sends the release back"

    final = validate_success(api.record_qa_result(release_id, "PASS", 0, ENG2))
    assert final["status"] == "QA_PASSED"
    assert final["qa_rounds"] == 3, f"three QA results were recorded, got {final['qa_rounds']}"
    assert final["defect_count"] == 0

    milestone = validate_success(api.get_milestone(ctx["milestone"]["id"], DL))
    assert milestone["status"] == "PLANNED", "a client REJECT never completes the milestone"
    invoices = validate_success(
        api.list_invoices(FIN, params={"milestone_id": ctx["milestone"]["id"]})
    )
    assert len(invoices) == 0, "no invoice is raised until the milestone is accepted"


def test_deploying_an_already_deployed_release_is_rejected(api):
    """PRD 3.7: "Deployment closes the loop. An engineer deploys an `ACCEPTED` release by supplying the target `environment`, which is recorded on the release as it moves `ACCEPTED → DEPLOYED`. `DEPLOYED` is terminal."
    PRD 2.5: "**Parent-state gates** — the engagement must be `ACTIVE` where the operation demands it (`ERR_ENGAGEMENT_NOT_ACTIVE`), then the sprint-state gates (`ERR_SPRINT_NOT_ACTIVE`), then the transition-legality check (`ERR_INVALID_TRANSITION`), then the milestone-completion gate on issuing (`ERR_MILESTONE_NOT_COMPLETED`), then the active-sprint gate on engagement closure (`ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT`)."

    Design: Corner/state_machines/deploy_a_deployed_release_a_second_time_is_rejected
    """
    ctx = fixtures.setup_accepted_release()
    release_id = ctx["release"]["id"]
    deployed = validate_success(api.deploy_release(release_id, "production", ENG))
    assert deployed["status"] == "DEPLOYED"
    assert deployed["environment"] == "production"

    again = api.deploy_release(release_id, "staging", ENG)
    validate_error(again, ApiErrorId.ERR_INVALID_TRANSITION.value)

    after = validate_success(api.get_release(release_id, DL))
    assert after["status"] == "DEPLOYED"
    assert after["environment"] == "production", (
        "the refused second deploy must not overwrite the recorded environment"
    )


def test_acceptance_cascade_is_visible_in_the_same_response_cycle(api):
    """PRD 3.7: "Second, the milestone named by the release's `milestone_id` transitions `PLANNED → COMPLETED` and gets its own `accepted_at` stamped from the same clock."
    PRD 3.7: "Because a cascade-created invoice arrives without the caller having asked for it, it is discovered by listing invoices filtered on the milestone."

    Design: Corner/consistency_model/acceptance_cascade_is_visible_in_the_same_response_cycle
    """
    ctx = fixtures.setup_qa_passed_release()
    milestone_id = ctx["milestone"]["id"]

    accepted = validate_success(
        api.decide_acceptance(ctx["release"]["id"], "ACCEPT", ctx["client_headers"])
    )
    assert accepted["status"] == "ACCEPTED"

    milestone = validate_success(api.get_milestone(milestone_id, DL))
    assert milestone["status"] == "COMPLETED", (
        "the very next read already sees the completed milestone — no settling delay"
    )

    invoices = validate_success(api.list_invoices(FIN, params={"milestone_id": milestone_id}))
    assert len(invoices) == 1, (
        f"the cascade invoice is listable immediately, got {len(invoices)} invoices"
    )
    assert invoices[0]["status"] == "DRAFT"
    assert invoices[0]["total"] == pytest.approx(5412.50, abs=0.01)


# ---------------------------------------------------------------------------
# The three-link acceptance cascade
# ---------------------------------------------------------------------------
def test_release_acceptance_completes_the_milestone_it_delivers(api):
    """PRD 3.7: "First, the release moves `QA_PASSED → ACCEPTED` and its `accepted_at` is stamped from the logical clock. Second, the milestone named by the release's `milestone_id` transitions `PLANNED → COMPLETED` and gets its own `accepted_at` stamped from the same clock."
    PRD 2.4: "Time in this system is *logical*, not wall-clock. The server holds a logical clock whose startup default is exactly `2026-05-01T00:00:00Z`; before any reposition it reads that default and never falls back to real wall-clock time."

    Design: Difficulty/transitive_cascade/release_acceptance_cascade_to_milestone_and_auto_draft_invoice
    """
    ctx = fixtures.setup_qa_passed_release(
        milestone_overrides={"title": "Phase 1 - Design", "amount": 5000.00}
    )

    accepted = validate_success(
        api.decide_acceptance(ctx["release"]["id"], "ACCEPT", ctx["client_headers"], note="Signed off")
    )
    assert accepted["status"] == "ACCEPTED"
    assert_instant_equals(accepted["accepted_at"], CLOCK_DEFAULT)

    milestone = validate_success(api.get_milestone(ctx["milestone"]["id"], DL))
    assert milestone["status"] == "COMPLETED"
    assert_instant_equals(milestone["accepted_at"], CLOCK_DEFAULT)


def test_release_acceptance_auto_creates_the_draft_milestone_invoice(api):
    """PRD 3.7: "Third — and **only when the engagement's `billing_model` is `FIXED`** — a new invoice is created automatically for that milestone: a `DRAFT` invoice of kind `MILESTONE`, with its `lines`, `subtotal`, `tax` and `total` computed by the invoice rules of §3.8."
    PRD 2.9: "Invoices in `DRAFT` or `VOID` contribute nothing."

    Design: Difficulty/transitive_cascade/release_acceptance_cascade_to_milestone_and_auto_draft_invoice
    """
    ctx = fixtures.setup_qa_passed_release(
        engagement_overrides={"billing_model": "FIXED", "contract_value": 50000.00},
        milestone_overrides={"title": "Phase 1 - Design", "amount": 5000.00},
    )
    validate_success(
        api.decide_acceptance(ctx["release"]["id"], "ACCEPT", ctx["client_headers"])
    )

    invoices = validate_success(
        api.list_invoices(FIN, params={"milestone_id": ctx["milestone"]["id"]})
    )
    assert len(invoices) == 1, f"exactly one cascade invoice, got {len(invoices)}"
    invoice = invoices[0]
    assert invoice["kind"] == "MILESTONE"
    assert invoice["status"] == "DRAFT"
    assert invoice["subtotal"] == pytest.approx(5000.00, abs=0.01)
    assert invoice["tax"] == pytest.approx(412.50, abs=0.01), (
        "8.25 percent of the 5,000.00 subtotal"
    )
    assert invoice["total"] == pytest.approx(5412.50, abs=0.01)
    assert_lines_sum_to_subtotal(invoice)
    assert_total_is_subtotal_plus_tax(invoice)

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["invoiced_amount"] == pytest.approx(0.0, abs=0.01), (
        "a DRAFT invoice is not yet in the money ledger"
    )
    assert engagement["billing_status"] == "UNBILLED"
