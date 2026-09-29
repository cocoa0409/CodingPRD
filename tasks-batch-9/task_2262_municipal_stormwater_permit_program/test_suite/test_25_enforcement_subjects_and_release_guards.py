"""Issuing against exactly one subject, and lifting a stop-work order once
every guard in front of it has been cleared."""

import pytest
from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import INSPECTOR_ONE, INSPECTOR_HEADERS, OFFICER_HEADERS
from test_helpers.types import UserRole

# insp-01 acting in the enforcement capacity: the role passes, the identity does not.
INSPECTOR_AS_OFFICER_HEADERS = build_user_headers(
    INSPECTOR_ONE, UserRole.ENFORCEMENT_OFFICER.value
)


def _issue(payload, headers=OFFICER_HEADERS):
    """Attempt an enforcement action with a hand-built body."""
    return api_client.create_enforcement_action(payload, headers)


class TestTheSubjectBlockIsSettledBeforeTheDutiesCheck:
    """Zero subjects, two subjects and a draft source all answer 422 first."""

    @pytest.fixture
    def documented_site(self, active_program):
        """SITE-A with an APPROVED plan, one FINALIZED and one DRAFT inspection."""
        site = fx.setup_site_with_approved_plan(active_program["term_id"])
        finalized = fx.setup_finalized_esc_inspection(
            site["id"], ("MINOR",), period_start="2026-06-01", period_end="2026-06-10"
        )
        draft = fx.create_esc_inspection(site["id"], "2026-07-01", "2026-07-10")
        facility = fx.create_facility(site["id"])
        return {
            "site": site,
            "finalized": finalized,
            "draft": draft,
            "facility": facility,
        }

    def test_01_an_action_naming_no_subject_at_all_is_refused(self, documented_site):
        """Exactly one subject key is required, and none were supplied.

        PRD: "An enforcement action is issued by an `EnforcementOfficer` under an `ACTIVE`
        permit term against exactly one subject. The officer names the `action_type` at
        which the ladder starts — `NOTICE_OF_VIOLATION`, `ADMINISTRATIVE_ORDER` or
        `CIVIL_PENALTY` — and exactly one of `illicit_discharge_case_id`,
        `construction_site_id` or `post_construction_facility_id`. Supplying none of them,
        or more than one, is refused with `ERR_ENFORCEMENT_SUBJECT_INVALID`."

        Design: Corner/validations/enforcement_subject_coherence_is_checked_before_the_segregation_of_duties
        """
        response = _issue(
            {"action_type": "NOTICE_OF_VIOLATION", "violation_days": 0}
        )

        validate_error(
            response, ApiErrorId.ERR_ENFORCEMENT_SUBJECT_INVALID.value, 422
        )

    def test_02_two_subjects_that_both_resolve_are_still_one_too_many(
        self, documented_site
    ):
        """A real site and a real facility named together fail the same rule.

        PRD: "Supplying none of them, or more than one, is refused with
        `ERR_ENFORCEMENT_SUBJECT_INVALID`." And: "**Body referential integrity.** Every
        foreign key supplied in a request body must resolve, again yielding the entity's
        404."

        Design: Corner/validations/enforcement_subject_coherence_is_checked_before_the_segregation_of_duties
        """
        response = _issue(
            {
                "action_type": "NOTICE_OF_VIOLATION",
                "construction_site_id": documented_site["site"]["id"],
                "post_construction_facility_id": documented_site["facility"]["id"],
                "violation_days": 0,
            }
        )

        validate_error(
            response, ApiErrorId.ERR_ENFORCEMENT_SUBJECT_INVALID.value, 422
        )

    def test_03_a_draft_source_inspection_documents_nothing_yet(self, documented_site):
        """The subject is coherent, so the source inspection's status answers.

        PRD: "Where an inspection documents the violation, the officer also supplies
        `source_inspection_id`; that inspection must have `status` `FINALIZED`, otherwise
        `ERR_SOURCE_INSPECTION_NOT_FINALIZED`, and it must belong to the named subject,
        otherwise `ERR_ENFORCEMENT_SUBJECT_INVALID`."

        Design: Corner/validations/enforcement_subject_coherence_is_checked_before_the_segregation_of_duties
        """
        response = _issue(
            {
                "action_type": "NOTICE_OF_VIOLATION",
                "construction_site_id": documented_site["site"]["id"],
                "source_inspection_id": documented_site["draft"]["id"],
                "violation_days": 0,
            }
        )

        validate_error(
            response, ApiErrorId.ERR_SOURCE_INSPECTION_NOT_FINALIZED.value, 422
        )

    def test_04_only_then_does_the_duties_check_notice_the_finalizer(
        self, documented_site
    ):
        """The same body from the inspector who froze the score is a 409.

        PRD: "The acting operator must differ from that inspection's
        `finalized_by_user_id`, otherwise `ERR_INSPECTOR_CANNOT_ENFORCE`." And:
        "**Segregation of duties.** `ERR_SELF_VALIDATION_FORBIDDEN`,
        `ERR_INSPECTOR_CANNOT_ENFORCE` and `ERR_SAME_USER_CERTIFICATION` (all 409),
        covering sample adjudication, enforcement issuance and report certification
        respectively."

        Design: Corner/validations/enforcement_subject_coherence_is_checked_before_the_segregation_of_duties
        """
        assert documented_site["finalized"]["finalized_by_user_id"] == INSPECTOR_ONE, (
            "the finalized inspection was frozen by insp-01"
        )

        response = _issue(
            {
                "action_type": "NOTICE_OF_VIOLATION",
                "construction_site_id": documented_site["site"]["id"],
                "source_inspection_id": documented_site["finalized"]["id"],
                "violation_days": 0,
            },
            INSPECTOR_AS_OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_INSPECTOR_CANNOT_ENFORCE.value, 409)

    def test_05_the_identical_body_from_another_officer_issues_cleanly(
        self, documented_site
    ):
        """One subject, a finalized source, a different operator: 25000 cents.

        PRD: "From whichever key is set, the server derives `subject_kind` as
        `ILLICIT_DISCHARGE_CASE`, `CONSTRUCTION_SITE` or `POST_CONSTRUCTION_FACILITY`."
        And: "A new action has `status` `ISSUED`, `issued_at` stamped from the logical
        clock, `issued_by_user_id` set to the acting operator, `escalation_count` at 0,
        `last_escalated_at` null, `auto_generated` false, and `compliance_note`,
        `closed_at`, `rescinded_reason` and `rescinded_at` all null." And: "Third,
        `escalation_multiplier` is read from that prior total: 1.00 when
        `prior_assessed_total_cents` is 0; 1.50 when it is greater than 0 but less than
        100000 cents; and 2.25 when it is 100000 cents or more." And: "`penalty_cents` is
        then the ladder base for the action's current `action_type` — 25000 cents for
        `NOTICE_OF_VIOLATION`, 50000 cents for `ADMINISTRATIVE_ORDER`, 100000 cents for
        `CIVIL_PENALTY` — plus 2000 cents for each of the `billable_violation_days`, with
        that sum multiplied by `escalation_multiplier` and the product rounded to whole
        cents."

        Design: Corner/validations/enforcement_subject_coherence_is_checked_before_the_segregation_of_duties
        """
        body = {
            "action_type": "NOTICE_OF_VIOLATION",
            "construction_site_id": documented_site["site"]["id"],
            "source_inspection_id": documented_site["finalized"]["id"],
            "violation_days": 0,
        }
        for refused in [
            {"action_type": "NOTICE_OF_VIOLATION", "violation_days": 0},
            dict(
                body,
                post_construction_facility_id=documented_site["facility"]["id"],
            ),
        ]:
            _issue(refused)

        action = validate_success(_issue(body), 201)

        assert action["subject_kind"] == "CONSTRUCTION_SITE", (
            f"the site key decides the subject kind, got {action['subject_kind']}"
        )
        assert action["status"] == "ISSUED", "a new action starts ISSUED"
        assert action["escalation_multiplier"] == pytest.approx(1.00, abs=0.01), (
            "no prior penalty on this subject leaves the multiplier at 1.00, got "
            f"{action['escalation_multiplier']}"
        )
        assert action["penalty_cents"] == 25000, (
            f"the notice base with no billable days is 25000, got {action['penalty_cents']}"
        )
        assert action["auto_generated"] is False, "an officer asked for this one"
        assert action["escalation_count"] == 0, "it sits on the first rung"

        _, meta = validate_paginated(
            api_client.list_enforcement_actions(OFFICER_HEADERS)
        )
        assert meta["total_count"] == 1, (
            f"the refused attempts stored nothing, got {meta['total_count']} actions"
        )


class TestReleaseNeedsEveryGuardClearedAtOnce:
    """The open action answers first, the returned plan second, then release."""

    @pytest.fixture
    def stopped_site(self, active_program):
        """SITE-A in STOP_WORK with a RETURNED plan and one ISSUED action."""
        site = fx.setup_site_with_approved_plan(active_program["term_id"])
        validate_success(
            api_client.submit_esc_plan(
                site["id"],
                factories.submit_esc_plan_payload("ESC-A-1"),
                INSPECTOR_HEADERS,
            )
        )
        returned = validate_success(
            api_client.esc_review(
                site["id"], factories.esc_review_payload("RETURN"), INSPECTOR_HEADERS
            )
        )
        assert returned["plan_status"] == "RETURNED", "the plan came back"
        stopped = validate_success(
            api_client.stop_work(
                site["id"], factories.stop_work_payload(), OFFICER_HEADERS
            )
        )
        assert stopped["field_status"] == "STOP_WORK", "the site is stopped"
        action = fx.issue_enforcement_action(
            construction_site_id=site["id"], violation_days=2
        )
        return {"site": site, "action": action}

    def test_06_the_open_action_outranks_the_unapproved_plan(self, stopped_site):
        """Both guards are violated and the enforcement one answers.

        PRD: "The same officer lifts the order by supplying a `corrective_action_note`,
        moving `field_status` from `STOP_WORK` back to `ACTIVE_DISTURBANCE`; this requires
        `open_enforcement_count` to be 0 (otherwise `ERR_SITE_HAS_OPEN_ENFORCEMENT`) and
        `plan_status` to be `APPROVED` (otherwise `ERR_ESC_PLAN_NOT_APPROVED`), and it
        clears `stop_work_reason` to null and `open_deficiency_score` to 0."

        Design: Corner/validations/a_release_that_satisfies_every_guard_at_once_succeeds
        """
        site = fx.read_site(stopped_site["site"]["id"])
        assert site["open_enforcement_count"] == 1, "one action is live"
        assert site["plan_status"] == "RETURNED", "and the plan is not approved"

        response = api_client.release_stop_work(
            site["id"],
            factories.release_stop_work_payload(corrective_action_note="Basin enlarged"),
            OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_SITE_HAS_OPEN_ENFORCEMENT.value, 409)

    def test_07_closing_the_action_uncovers_the_plan_guard(self, stopped_site):
        """With the ledger closed the second guard is the one left standing.

        PRD: "Closing an action documents compliance without forgiving the money. From
        `ISSUED` or `ESCALATED`, and carrying a `compliance_note`, it writes `CLOSED` into
        `status`, stamps `closed_at`, records the note, leaves `penalty_cents` standing in
        the term's ledger, and lowers the subject site's `open_enforcement_count` where
        the subject is a site." And: "this requires `open_enforcement_count` to be 0
        (otherwise `ERR_SITE_HAS_OPEN_ENFORCEMENT`) and `plan_status` to be `APPROVED`
        (otherwise `ERR_ESC_PLAN_NOT_APPROVED`)"

        Design: Corner/validations/a_release_that_satisfies_every_guard_at_once_succeeds
        """
        fx.close_action(
            stopped_site["action"]["id"],
            compliance_note="Discharge stopped and area stabilised",
        )

        site = fx.read_site(stopped_site["site"]["id"])
        assert site["open_enforcement_count"] == 0, (
            f"the closure freed the site, got {site['open_enforcement_count']}"
        )

        response = api_client.release_stop_work(
            site["id"],
            factories.release_stop_work_payload(corrective_action_note="Basin enlarged"),
            OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_ESC_PLAN_NOT_APPROVED.value, 422)

    def test_08_a_re_approved_plan_completes_the_release(self, stopped_site):
        """Approval does not lift the order; the officer still has to.

        PRD: "`APPROVE` writes `APPROVED` into `plan_status` and, if and only if
        `field_status` is still `PRE_CONSTRUCTION`, additionally advances `field_status` to
        `ACTIVE_DISTURBANCE` — the point at which the site becomes eligible for
        erosion-control inspections." And: "The same officer lifts the order by supplying a
        `corrective_action_note`, moving `field_status` from `STOP_WORK` back to
        `ACTIVE_DISTURBANCE`; this requires `open_enforcement_count` to be 0 (otherwise
        `ERR_SITE_HAS_OPEN_ENFORCEMENT`) and `plan_status` to be `APPROVED` (otherwise
        `ERR_ESC_PLAN_NOT_APPROVED`), and it clears `stop_work_reason` to null and
        `open_deficiency_score` to 0."

        Design: Corner/validations/a_release_that_satisfies_every_guard_at_once_succeeds
        """
        site_id = stopped_site["site"]["id"]
        fx.close_action(
            stopped_site["action"]["id"],
            compliance_note="Discharge stopped and area stabilised",
        )
        validate_success(
            api_client.submit_esc_plan(
                site_id,
                factories.submit_esc_plan_payload("ESC-A-R1"),
                INSPECTOR_HEADERS,
            )
        )
        approved = validate_success(
            api_client.esc_review(
                site_id,
                factories.esc_review_payload(
                    "APPROVE", review_notes="Revised basin accepted"
                ),
                INSPECTOR_HEADERS,
            )
        )
        assert approved["field_status"] == "STOP_WORK", (
            "approval leaves a stopped site stopped"
        )

        released = validate_success(
            api_client.release_stop_work(
                site_id,
                factories.release_stop_work_payload(
                    corrective_action_note="Basin enlarged"
                ),
                OFFICER_HEADERS,
            )
        )

        assert released["field_status"] == "ACTIVE_DISTURBANCE", (
            f"work may resume, got {released['field_status']}"
        )
        assert released["plan_status"] == "APPROVED", "with the revised plan in force"
        assert released["open_enforcement_count"] == 0, "and nothing live against it"
        assert released["stop_work_reason"] is None, "the reason was cleared"
        assert released["open_deficiency_score"] == 0, "the carried score was cleared"

    def test_09_the_penalty_stays_on_the_ledger_after_the_release(self, stopped_site):
        """Two documented days of violation are still 29000 cents owed.

        PRD: "`penalty_cents` is then the ladder base for the action's current
        `action_type` — 25000 cents for `NOTICE_OF_VIOLATION`, 50000 cents for
        `ADMINISTRATIVE_ORDER`, 100000 cents for `CIVIL_PENALTY` — plus 2000 cents for
        each of the `billable_violation_days`, with that sum multiplied by
        `escalation_multiplier` and the product rounded to whole cents." And: "Closing an
        action documents compliance without forgiving the money. From `ISSUED` or
        `ESCALATED`, and carrying a `compliance_note`, it writes `CLOSED` into `status`,
        stamps `closed_at`, records the note, leaves `penalty_cents` standing in the term's
        ledger, and lowers the subject site's `open_enforcement_count` where the subject is
        a site."

        Design: Corner/validations/a_release_that_satisfies_every_guard_at_once_succeeds
        """
        action_id = stopped_site["action"]["id"]
        assert stopped_site["action"]["penalty_cents"] == 29000, (
            "25000 plus two days at 2000 is 29000, got "
            f"{stopped_site['action']['penalty_cents']}"
        )

        fx.close_action(action_id, compliance_note="Discharge stopped and area stabilised")
        site_id = stopped_site["site"]["id"]
        validate_success(
            api_client.submit_esc_plan(
                site_id,
                factories.submit_esc_plan_payload("ESC-A-R1"),
                INSPECTOR_HEADERS,
            )
        )
        validate_success(
            api_client.esc_review(
                site_id, factories.esc_review_payload("APPROVE"), INSPECTOR_HEADERS
            )
        )
        validate_success(
            api_client.release_stop_work(
                site_id,
                factories.release_stop_work_payload(
                    corrective_action_note="Basin enlarged"
                ),
                OFFICER_HEADERS,
            )
        )

        action = fx.read_action(action_id)
        assert action["status"] == "CLOSED", f"the action is closed, got {action['status']}"
        assert action["penalty_cents"] == 29000, (
            f"the money was never forgiven, got {action['penalty_cents']}"
        )
