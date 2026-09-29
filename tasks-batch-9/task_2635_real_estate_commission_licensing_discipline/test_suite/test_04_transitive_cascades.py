"""Cascades that run several levels past the entity the request named."""

from prd_bench_local_runner.testing import validate_success
from test_helpers import fixtures
from test_helpers.assertions import assert_ce_standing, assert_posture
from test_helpers.test_users import make_analyst_headers

CHAIR = "chair-01"
HEARING_START = "2026-08-05T09:00:00Z"
HEARING_END = "2026-08-05T11:00:00Z"


def _school_with_a_licensed_broker_instructor(client):
    """A firm, a school whose instructor is a licensed broker, and two students."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    designated_broker_id = firm["broker"]["id"]

    teacher = fixtures.create_exam_passed_licensee(client, "BROKER", "Nia Tutor", score=91)
    teacher = fixtures.affiliate(client, teacher["id"], brokerage_id, designated_broker_id)

    provider = fixtures.approve_provider(
        client, fixtures.register_provider(client, "Coastal RE Academy")["id"]
    )
    instructor = fixtures.register_instructor(
        client, provider["id"], "Nia Tutor", "LICENSED_BROKER", licensee_id=teacher["id"]
    )
    instructor = fixtures.approve_instructor(client, instructor["id"])

    sam = fixtures.affiliate_new_salesperson(
        client, brokerage_id, designated_broker_id, "Sam Reed"
    )
    tom = fixtures.affiliate_new_salesperson(
        client, brokerage_id, designated_broker_id, "Tom Lane"
    )
    recent = fixtures.record_completion(
        client, sam["id"], instructor["id"], provider["id"],
        credit_hours=12, completed_on="2026-08-01", course_type="CE_CORE",
    )
    older = fixtures.record_completion(
        client, tom["id"], instructor["id"], provider["id"],
        credit_hours=6, completed_on="2025-06-01", course_type="CE_ELECTIVE",
    )
    return {
        "firm": firm,
        "teacher": teacher,
        "provider": provider,
        "instructor": instructor,
        "sam": sam,
        "tom": tom,
        "recent_completion": recent,
        "older_completion": older,
    }


def _revoke_the_teacher_at_a_hearing(client, world):
    complaint = fixtures.complaint_at_probable_cause(
        client, world["teacher"]["id"], "MISREPRESENTATION", 3000000
    )
    outcome = fixtures.issue_order_by_hearing(
        client,
        complaint["id"],
        CHAIR,
        sanction_type="REVOCATION",
        scheduled_start_at=HEARING_START,
        scheduled_end_at=HEARING_END,
        hearing_room="ROOM-A",
    )
    outcome["complaint"] = fixtures.read_complaint(client, complaint["id"])
    return outcome


class TestRevocationCascadeReachesAThirdPartyStudent:
    """One panel-chair decision rewrites an uninvolved licensee's CE balance."""

    def test_the_decision_issues_the_order_and_adjudicates_the_complaint(self, client):
        """Level one: the hearing's finding becomes a sanction order at once.

        The PRD says "A finding of `VIOLATION_FOUND` creates a sanction order
        with `source` `HEARING`, `status` `ISSUED` and `effective_at` at the
        current instant, moves the complaint `HEARING_SCHEDULED → ADJUDICATED`,
        moves the respondent's `discipline_status` `PENDING_HEARING →
        SANCTIONED`, applies the same `license_status` consequence and the same
        revocation cascade as the consent channel, and recomputes the brokerage
        posture."

        Design: Difficulty/transitive_cascade/hearing_revocation_cascades_five_levels_to_a_third_party_student_ce_balance
        """
        world = _school_with_a_licensed_broker_instructor(client)
        outcome = _revoke_the_teacher_at_a_hearing(client, world)

        hearing = outcome["hearing"]
        assert hearing["status"] == "DECIDED"
        assert hearing["finding"] == "VIOLATION_FOUND"
        assert hearing["decided_at"] == HEARING_START

        order = outcome["order"]
        assert order["source"] == "HEARING"
        assert order["status"] == "ISSUED"
        assert order["sanction_type"] == "REVOCATION"
        assert order["effective_at"] == HEARING_START
        assert outcome["complaint"]["status"] == "ADJUDICATED"

    def test_the_revoked_licence_suspends_its_instructor_row_and_probates_the_school(
        self, client
    ):
        """Levels two and three: the licence, then the credential that hangs off it.

        The PRD says "every instructor row whose `licensee_id` is that licensee
        and whose `status` is `PENDING` or `APPROVED` moves to `SUSPENDED` with
        `suspended_reason` `LICENSE_REVOKED`".

        Design: Difficulty/transitive_cascade/hearing_revocation_cascades_five_levels_to_a_third_party_student_ce_balance
        """
        world = _school_with_a_licensed_broker_instructor(client)
        _revoke_the_teacher_at_a_hearing(client, world)

        teacher = fixtures.read_licensee(client, world["teacher"]["id"])
        assert teacher["license_status"] == "REVOKED"
        assert teacher["discipline_status"] == "SANCTIONED"

        instructor = fixtures.read_instructor(client, world["instructor"]["id"])
        assert instructor["status"] == "SUSPENDED"
        assert instructor["suspended_reason"] == "LICENSE_REVOKED"

        provider = fixtures.read_provider(client, world["provider"]["id"])
        assert provider["status"] == "PROBATION"
        assert provider["suspended_instructor_count"] == 1

    def test_only_completions_inside_the_look_back_window_are_invalidated(self, client):
        """Level four is selective: the older completion by the same teacher survives.

        The PRD says "every course completion naming that instructor whose
        `credit_status` is `VALID` and whose `completed_on` falls on or after the
        current calendar date minus a 365-day look-back has its `credit_status`
        flipped to `INVALIDATED` with `invalidated_at` stamped at the current
        instant".

        Design: Difficulty/transitive_cascade/hearing_revocation_cascades_five_levels_to_a_third_party_student_ce_balance
        """
        world = _school_with_a_licensed_broker_instructor(client)
        _revoke_the_teacher_at_a_hearing(client, world)

        invalidated = validate_success(
            client.get_course_completion(world["recent_completion"]["id"], make_analyst_headers())
        )
        assert invalidated["credit_status"] == "INVALIDATED"
        assert invalidated["invalidated_at"] == HEARING_START

        survivor = validate_success(
            client.get_course_completion(world["older_completion"]["id"], make_analyst_headers())
        )
        assert survivor["credit_status"] == "VALID"
        assert survivor["invalidated_at"] is None

        provider = fixtures.read_provider(client, world["provider"]["id"])
        assert provider["invalidated_credit_hours"] == 12, (
            "the out-of-look-back completion is excluded from the rollup"
        )

    def test_a_student_who_is_no_party_to_the_case_falls_into_ce_deficiency(self, client):
        """Level five: the cascade lands on a licensee the complaint never named.

        The PRD says "then every student licensee referenced by an invalidated
        completion has `ce_hours_valid` and `ce_deficient` recomputed, which can
        silently push a compliant agent into deficiency."

        Design: Difficulty/transitive_cascade/hearing_revocation_cascades_five_levels_to_a_third_party_student_ce_balance
        """
        world = _school_with_a_licensed_broker_instructor(client)
        before = fixtures.read_licensee(client, world["sam"]["id"])
        assert_ce_standing(before, valid=12, required=12)

        _revoke_the_teacher_at_a_hearing(client, world)

        after = fixtures.read_licensee(client, world["sam"]["id"])
        assert_ce_standing(after, valid=0, required=12)
        assert after["ce_deficient"] is True

        # Tom's surviving completion predates his own accrual window, so it was
        # never counted and the cascade changes nothing for him.
        tom = fixtures.read_licensee(client, world["tom"]["id"])
        assert_ce_standing(tom, valid=0, required=12)

    def test_the_firm_survives_because_the_revoked_broker_was_not_of_record(self, client):
        """The brokerage keeps trading; only its affiliate count moves.

        The PRD says "`affiliated_licensee_count` counts licensees whose
        `sponsoring_brokerage_id` is this brokerage **and** whose `license_status`
        is `ACTIVE` — inactive, suspended and expired affiliates do not count."

        Design: Difficulty/transitive_cascade/hearing_revocation_cascades_five_levels_to_a_third_party_student_ce_balance
        """
        world = _school_with_a_licensed_broker_instructor(client)
        brokerage_id = world["firm"]["brokerage"]["id"]
        assert fixtures.read_brokerage(client, brokerage_id)["affiliated_licensee_count"] == 4

        _revoke_the_teacher_at_a_hearing(client, world)

        brokerage = fixtures.read_brokerage(client, brokerage_id)
        assert brokerage["status"] == "ACTIVE"
        assert brokerage["affiliated_licensee_count"] == 3


AUDITOR = "auditor-07"
AS_OF_DATE = "2026-08-31"
FIELDWORK_START = "2026-08-01T00:00:00Z"
FIELDWORK_END = "2026-08-01T16:00:00Z"


def _firm_with_pending_names_and_a_shortage(client):
    """A live firm with one approved and two pending names, and a 150,000 hole."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name="Harbor Realty Group", broker_name="Dana Broker"
    )
    brokerage_id = firm["brokerage"]["id"]
    account_id = firm["account"]["id"]

    approved = fixtures.submit_advertising_name(
        client, brokerage_id, "Harbor Homes Collective", kind="DBA"
    )
    approved = fixtures.review_advertising_name(client, approved["id"], "APPROVE")
    team = fixtures.submit_advertising_name(
        client,
        brokerage_id,
        "Dana Broker Group",
        kind="TEAM",
        team_lead_licensee_id=firm["broker"]["id"],
    )
    branch = fixtures.submit_advertising_name(
        client, brokerage_id, "Harbor Northside Office", kind="BRANCH"
    )

    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", 1000000, "2026-08-01", "ESCROW-IN-9001"
    )
    fixtures.append_ledger_entry(
        client,
        account_id,
        "DEPOSIT",
        850000,
        "2026-08-01",
        "WIRE-9001",
        cleared_date="2026-08-01",
    )

    audit = fixtures.schedule_audit(
        client,
        account_id,
        AUDITOR,
        basis="BOOK",
        as_of_date=AS_OF_DATE,
        fieldwork_start_at=FIELDWORK_START,
        fieldwork_end_at=FIELDWORK_END,
    )
    audit = fixtures.start_fieldwork(client, audit["id"], AUDITOR)
    return {
        "firm": firm,
        "account_id": account_id,
        "brokerage_id": brokerage_id,
        "audit": audit,
        "approved_name": approved,
        "team_name": team,
        "branch_name": branch,
    }


class TestAuditFindingsCascadeIntoAdvertisingNames:
    """One auditor's findings reject marketing names nobody reviewed."""

    def test_findings_on_a_hole_land_the_audit_in_remediation_not_findings_issued(
        self, client
    ):
        """Level one: the request's own state hop runs two steps, not one.

        The PRD says "When the frozen shortage is greater than 0, the audit
        instead continues `FINDINGS_ISSUED → REMEDIATION_ORDERED` immediately,
        and a four-layer cascade settles before the response is written, **in
        this order**."

        Design: Difficulty/transitive_cascade/audit_findings_cascade_four_levels_into_advertising_name_auto_rejection
        """
        world = _firm_with_pending_names_and_a_shortage(client)
        assert world["audit"]["computed_shortage_cents"] == 150000

        disposed = fixtures.dispose_audit(
            client, world["audit"]["id"], AUDITOR, "ISSUE_FINDINGS", remediation_days=3
        )

        assert disposed["status"] == "REMEDIATION_ORDERED"
        assert disposed["computed_shortage_cents"] == 150000
        assert disposed["remediation_round"] == 1
        assert disposed["remediation_due_at"] == "2026-08-04T00:00:00Z"

    def test_the_account_is_restricted_and_the_firm_is_re_graded(self, client):
        """Levels two and three: the account, then the firm that owns it.

        The PRD says "Third, the owning brokerage's `open_shortage_cents` is
        recomputed and its `supervision_posture` re-graded, landing on
        `RESTRICTED` when the accumulated open shortage has reached 100,000 cents
        and otherwise on `WATCH`."

        Design: Difficulty/transitive_cascade/audit_findings_cascade_four_levels_into_advertising_name_auto_rejection
        """
        world = _firm_with_pending_names_and_a_shortage(client)
        fixtures.dispose_audit(
            client, world["audit"]["id"], AUDITOR, "ISSUE_FINDINGS", remediation_days=3
        )

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["status"] == "RESTRICTED"
        assert account["shortage_cents"] == 150000

        brokerage = fixtures.read_brokerage(client, world["brokerage_id"])
        assert brokerage["open_shortage_cents"] == 150000
        assert_posture(brokerage, "RESTRICTED")
        assert brokerage["overdue_remediation_count"] == 0, (
            "nothing is overdue yet; the deadline is three days out"
        )

    def test_pending_names_are_auto_rejected_and_the_approved_name_is_left_alone(
        self, client
    ):
        """Level four is the cascade's far end, and it is selective.

        The PRD says "Fourth, and only when that re-graded posture landed on
        `RESTRICTED` or `FROZEN`, every advertising name of that brokerage still
        in `SUBMITTED` is auto-rejected with `rejection_reason`
        `POSTURE_RESTRICTED` and `reviewed_by_user_id` left null, since no human
        reviewed it."

        Design: Difficulty/transitive_cascade/audit_findings_cascade_four_levels_into_advertising_name_auto_rejection
        """
        world = _firm_with_pending_names_and_a_shortage(client)
        fixtures.dispose_audit(
            client, world["audit"]["id"], AUDITOR, "ISSUE_FINDINGS", remediation_days=3
        )

        for pending in ("team_name", "branch_name"):
            name = fixtures.read_advertising_name(client, world[pending]["id"])
            assert name["status"] == "REJECTED", f"{name['name_text']} should be swept"
            assert name["rejection_reason"] == "POSTURE_RESTRICTED"
            assert name["reviewed_by_user_id"] is None, (
                "no human reviewed it, so the reviewer stays null"
            )

        survivor = fixtures.read_advertising_name(client, world["approved_name"]["id"])
        assert survivor["status"] == "APPROVED"
        assert survivor["rejection_reason"] is None
