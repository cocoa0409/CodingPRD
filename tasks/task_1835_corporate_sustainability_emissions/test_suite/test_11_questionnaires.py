"""Questionnaire responses: framework uniqueness, completeness computation,
the submit-review gate, the review loop, reviewer segregation of duties, and
the EMISSIONS stale-flag lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId, answer_all_cdp_sections, answer_section, approve_record,
    create_questionnaire_payload, get_questionnaire, make_collecting_cycle,
    make_factor, make_lead_headers, make_manager_headers, make_questionnaire,
    make_site, make_target, activate_target, review_decision_payload,
    review_record, submit_record, transition_payload, validate_error,
    validate_success,
)


def test_duplicate_questionnaire_framework_returns_409(api, lead_headers):
    """PRD §3.9: "Only one response per framework per cycle: a second
    response with the same `cycle_id` and `framework` is rejected with
    `ERR_DUPLICATE_QUESTIONNAIRE`."

    Design: Corner/validations/duplicate_questionnaire_framework_returns_409
    """
    cycle = make_collecting_cycle()
    make_questionnaire(cycle["id"], framework="CDP")

    duplicate = api.create_questionnaire(
        create_questionnaire_payload(cycle["id"], framework="CDP"), lead_headers
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_QUESTIONNAIRE, 409)

    other_framework = api.create_questionnaire(
        create_questionnaire_payload(cycle["id"], framework="GRI"), lead_headers
    )
    validate_success(other_framework, 201)


def test_questionnaire_completeness_tracks_required_sections(api, lead_headers):
    """PRD §3.9: "Each framework declares its required sections — `CDP`
    requires `GOVERNANCE`, `RISKS`, `EMISSIONS`, and `TARGETS`; `GRI`
    requires `DISCLOSURE_305` and `ENERGY`; `ECOVADIS` requires `ENVIRONMENT`
    — and `completeness_pct` is the share of required sections answered: the
    count of answered required sections divided by the count of required
    sections, multiplied by 100, rounded half-up to one decimal place."

    Design: Corner/calculations/questionnaire_completeness_75pct
    """
    cycle = make_collecting_cycle()
    questionnaire = make_questionnaire(cycle["id"], framework="CDP")
    assert questionnaire["completeness_pct"] == pytest.approx(0.0, abs=0.05)

    for section_key in ("GOVERNANCE", "RISKS"):
        answer_section(questionnaire["id"], section_key, "text")
    third = answer_section(questionnaire["id"], "EMISSIONS", "Inventory summary")
    assert third["completeness_pct"] == pytest.approx(75.0, abs=0.05), (
        "3 of 4 required CDP sections answered -> 75.0"
    )
    fourth = answer_section(questionnaire["id"], "TARGETS", "50 by 2030")
    assert fourth["completeness_pct"] == pytest.approx(100.0, abs=0.05)


def test_questionnaire_submit_review_requires_complete_sections(api, lead_headers):
    """PRD §3.9: "The gate runs after the cycle check — the parent cycle must
    not be `LOCKED`, `UNDER_ASSURANCE`, `ASSURED`, or `DISCLOSED`, failing
    with `ERR_CYCLE_NOT_COLLECTING` — and requires every framework-required
    section answered with `emissions_section_stale` false, failing with
    `ERR_SECTION_INCOMPLETE`."

    Design: Corner/validations/questionnaire_submit_review_incomplete_sections_returns_error
    """
    cycle = make_collecting_cycle()
    questionnaire = make_questionnaire(cycle["id"], framework="CDP")
    for section_key in ("GOVERNANCE", "RISKS", "EMISSIONS"):
        answer_section(questionnaire["id"], section_key, "text")

    blocked = api.transition_questionnaire(
        questionnaire["id"], transition_payload("IN_REVIEW"), lead_headers
    )
    validate_error(blocked, ApiErrorId.ERR_SECTION_INCOMPLETE, 422)

    answer_section(questionnaire["id"], "TARGETS", "50 by 2030")
    submitted_for_review = validate_success(
        api.transition_questionnaire(
            questionnaire["id"], transition_payload("IN_REVIEW"), lead_headers
        )
    )
    assert submitted_for_review["status"] == "IN_REVIEW"


def test_questionnaire_review_loop_changes_requested(api, lead_headers, manager_headers):
    """PRD §3.9: "The reviewer names a `decision`: `APPROVE` moves
    `IN_REVIEW` to `APPROVED`, while `REQUEST_CHANGES` returns it to `DRAFT`,
    and either way the reviewer's identity is stored in `review_decision_by`
    together with their `review_notes`. The `DRAFT` → `IN_REVIEW` → `DRAFT`
    review loop can repeat."

    Design: Corner/state_machines/questionnaire_review_loop_changes_requested
    """
    cycle = make_collecting_cycle()
    questionnaire = make_questionnaire(cycle["id"], framework="CDP")
    answer_all_cdp_sections(questionnaire["id"])
    validate_success(
        api.transition_questionnaire(
            questionnaire["id"], transition_payload("IN_REVIEW"), lead_headers
        )
    )

    bounced = validate_success(
        api.review_questionnaire(
            questionnaire["id"],
            review_decision_payload("REQUEST_CHANGES", review_notes="Fix targets wording"),
            manager_headers,
        )
    )
    assert bounced["status"] == "DRAFT"
    assert bounced["review_decision_by"] == "manager-1"
    assert bounced["review_notes"] == "Fix targets wording"

    # The review loop repeats: re-submit for review, then approve.
    validate_success(
        api.transition_questionnaire(
            questionnaire["id"], transition_payload("IN_REVIEW"), lead_headers
        )
    )
    approved = validate_success(
        api.review_questionnaire(
            questionnaire["id"],
            review_decision_payload("APPROVE", review_notes="Looks good"),
            manager_headers,
        )
    )
    assert approved["status"] == "APPROVED"


def test_review_decision_by_preparer_returns_sod(api, manager_headers):
    """PRD §2.9: "The manager deciding a questionnaire review must not be the
    user recorded in the response's `prepared_by_user_id`. Any same-user
    attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/roles/review_decision_by_preparer_returns_sod
    """
    cycle = make_collecting_cycle()
    questionnaire = make_questionnaire(cycle["id"], framework="CDP")
    answer_all_cdp_sections(questionnaire["id"])
    validate_success(
        api.transition_questionnaire(
            questionnaire["id"], transition_payload("IN_REVIEW"),
            make_lead_headers("lead-1"),
        )
    )

    same_user = api.review_questionnaire(
        questionnaire["id"], review_decision_payload("APPROVE"),
        make_manager_headers("lead-1"),
    )
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    approved = validate_success(
        api.review_questionnaire(
            questionnaire["id"],
            review_decision_payload("APPROVE", review_notes="ok"),
            manager_headers,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["review_decision_by"] == "manager-1"


def test_reanswering_emissions_clears_stale_flag(api, lead_headers, analyst_headers):
    """PRD §3.9: "Answering the `EMISSIONS` section also clears
    `emissions_section_stale` to false. That flag is the response's only
    staleness marker: the §2.6 cascade sets it whenever the cycle's emissions
    figures may have moved under an already-answered EMISSIONS section, and
    only re-answering that section clears it."

    Design: Corner/consistency_model/reanswering_emissions_clears_stale_flag
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    questionnaire = make_questionnaire(cycle["id"], framework="CDP")
    answer_all_cdp_sections(questionnaire["id"])
    # An ACTIVE target watching the cycle makes the approval cascade fire link 2+3.
    activate_target(make_target()["id"])

    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=100)
    review_record(record["id"])
    approve_record(record["id"])
    stale = get_questionnaire(questionnaire["id"])
    assert stale["emissions_section_stale"] is True, (
        "the approval cascade flags the already-answered EMISSIONS section"
    )

    other_section = answer_section(questionnaire["id"], "TARGETS", "revised targets text")
    assert other_section["emissions_section_stale"] is True, (
        "answering a non-EMISSIONS section does not clear the flag"
    )
    reanswered = answer_section(questionnaire["id"], "EMISSIONS", "revised emissions text")
    assert reanswered["emissions_section_stale"] is False, (
        "re-answering EMISSIONS clears the flag in the same response"
    )
