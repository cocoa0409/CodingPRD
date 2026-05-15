"""Enrollment and depth-3 cascade tests.

Covers PRD §3.10 (Enroll preconditions and the three-hop cascade) and
the cascade interactions across siblings, waitlists, and aid packages.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_applicant,
    create_application,
    create_program,
    create_university,
    enroll_application,
    get_application,
    get_university,
    make_applicant_headers,
    setup_admitted_application,
    setup_admitted_with_aid_accepted,
    setup_admitted_with_aid_offered,
    setup_enroll_cascade_scenario,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Enroll: aid-response gate (PRD §3.10)
# ---------------------------------------------------------------------------
class TestEnrollAidResponseGate:

    def test_enroll_with_aid_accepted_succeeds(self, api):
        """PRD §3.10: "Second, if a financial-aid package exists for
        this application, its status must be ACCEPTED or DECLINED —
        the applicant must have responded to the offer..."

        Claim: enroll succeeds when the linked aid package is ACCEPTED.
        """
        ctx = setup_admitted_with_aid_accepted(round_="REGULAR_DECISION")
        res = api.enroll_application(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "ENROLLED"


# ---------------------------------------------------------------------------
# Enroll: already-enrolled-elsewhere gate (PRD §3.10)
# ---------------------------------------------------------------------------
class TestEnrollAlreadyEnrolledElsewhere:

    def test_enroll_when_already_enrolled_yields_err_already_enrolled_elsewhere(
        self, api,
    ):
        """PRD §3.10: "Third, the applicant must not have another
        application already in ENROLLED (otherwise
        ERR_ALREADY_ENROLLED_ELSEWHERE)."

        Claim: an applicant who has one ENROLLED application cannot
        enroll a second admitted application — gets
        ERR_ALREADY_ENROLLED_ELSEWHERE.
        """
        # Build TWO admitted applications for the same applicant on
        # two universities, neither with aid (so the enroll path is
        # not blocked by aid status). Enroll the first; then attempt
        # the second.
        applicant = create_applicant()
        uni1 = create_university()
        prog1 = create_program(uni1["id"])
        uni2 = create_university()
        prog2 = create_program(uni2["id"])

        from test_helpers import (
            attach_strong_essay, setup_strong_recommendations,
            submit_application,
        )
        # APP1 admitted
        app1 = create_application(applicant["id"], prog1["id"])
        attach_strong_essay(
            applicant["id"], app1["id"],
            university_name=uni1["name"], program_name=prog1["name"],
        )
        setup_strong_recommendations(applicant["id"], app1["id"])
        submit_application(applicant["id"], app1["id"])
        api.begin_review(app1["id"],
                         TEST_USERS["admissions_officer_headers"])
        api.decide_application(
            app1["id"], {"decision": "ADMIT"},
            TEST_USERS["admissions_officer_headers"],
        )
        # APP2 admitted
        app2 = create_application(applicant["id"], prog2["id"])
        attach_strong_essay(
            applicant["id"], app2["id"],
            university_name=uni2["name"], program_name=prog2["name"],
        )
        setup_strong_recommendations(applicant["id"], app2["id"])
        submit_application(applicant["id"], app2["id"])
        api.begin_review(app2["id"],
                         TEST_USERS["admissions_officer_headers"])
        api.decide_application(
            app2["id"], {"decision": "ADMIT"},
            TEST_USERS["admissions_officer_headers"],
        )
        # Enroll APP1.
        enroll_application(applicant["id"], app1["id"])
        # Attempt APP2 enroll — but APP2 should be WITHDRAWN by the
        # enroll-cascade. The PRD §3.10 cascade hop 2 withdraws every
        # other in-flight application of the applicant, so APP2 will
        # be WITHDRAWN. Calling enroll on a WITHDRAWN application
        # yields ERR_INVALID_STATE (state precedes the
        # already-enrolled-elsewhere check per §2.7).
        #
        # To exercise ERR_ALREADY_ENROLLED_ELSEWHERE specifically, the
        # second admit-and-enroll must happen AFTER the first enroll,
        # and there must be a way to admit it. Since the cascade
        # withdraws siblings on enroll, the only path is: admit APP1
        # → enroll APP1 → admit a NEW APP2 (created later) →
        # enroll APP2.
        applicant_new = applicant
        uni3 = create_university()
        prog3 = create_program(uni3["id"])
        app3 = create_application(applicant_new["id"], prog3["id"])
        attach_strong_essay(
            applicant_new["id"], app3["id"],
            university_name=uni3["name"], program_name=prog3["name"],
        )
        setup_strong_recommendations(applicant_new["id"], app3["id"])
        submit_application(applicant_new["id"], app3["id"])
        api.begin_review(app3["id"],
                         TEST_USERS["admissions_officer_headers"])
        api.decide_application(
            app3["id"], {"decision": "ADMIT"},
            TEST_USERS["admissions_officer_headers"],
        )
        # Attempt enroll on APP3 — the applicant is already ENROLLED in APP1.
        res = api.enroll_application(
            app3["id"], make_applicant_headers(applicant_new["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ALREADY_ENROLLED_ELSEWHERE.value)


# ---------------------------------------------------------------------------
# Enroll: depth-3 cascade (PRD §3.10)
# ---------------------------------------------------------------------------
class TestEnrollCascade:

    def test_enroll_increments_university_enrolled_count(self, api):
        """PRD §3.10: "Hop 1: the university's enrolled_count is
        incremented by one."
        """
        ctx = setup_admitted_with_aid_accepted(round_="REGULAR_DECISION")
        uni_before = get_university(ctx["university"]["id"])
        api.enroll_application(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        uni_after = get_university(ctx["university"]["id"])
        assert uni_after["enrolled_count"] == uni_before["enrolled_count"] + 1, (
            f"University.enrolled_count expected "
            f"{uni_before['enrolled_count'] + 1}, "
            f"got {uni_after['enrolled_count']}"
        )

    def test_enroll_cascades_withdraw_to_sibling_applications(self, api):
        """PRD §3.10: "Hop 2: every other application of this applicant
        in DRAFT, SUBMITTED, UNDER_REVIEW, ADMITTED, or WAITLISTED
        transitions to WITHDRAWN..."

        # difficulty: transitive_cascade/enroll_cascades_to_siblings_waitlists_aid
        """
        ctx = setup_enroll_cascade_scenario()
        # APP2 (ADMITTED with OFFERED aid) and APP3 (WAITLISTED) are
        # siblings of APP1.
        # APP1 needs aid response before enroll succeeds — we set up
        # without aid on APP1 in setup_enroll_cascade_scenario; verify.
        # PRD §3.10: aid response required only if package exists.
        applicant_id = ctx["applicant"]["id"]
        api.enroll_application(
            ctx["application_1"]["id"],
            make_applicant_headers(applicant_id),
        )
        # The enroll-cascade requires APP1 to have no aid package or
        # have responded. Our fixture builds APP1 without aid (only
        # APP2 has aid). Now check siblings.
        app2_after = get_application(ctx["application_2"]["id"])
        app3_after = get_application(ctx["application_3"]["id"])
        assert app2_after["status"] == "WITHDRAWN", (
            f"sibling APP2 must cascade to WITHDRAWN, got {app2_after['status']!r}"
        )
        assert app3_after["status"] == "WITHDRAWN", (
            f"sibling APP3 must cascade to WITHDRAWN, got {app3_after['status']!r}"
        )

    def test_enroll_cascades_revoke_to_sibling_aid_package(self, api):
        """PRD §3.10: "Hop 3: any WaitlistEntry tied to a
        withdrawn-as-side-effect application transitions to RELEASED,
        and any FinancialAidPackage tied to such an application
        transitions to REVOKED..."

        # difficulty: transitive_cascade/enroll_cascades_to_siblings_waitlists_aid
        """
        ctx = setup_enroll_cascade_scenario()
        applicant_id = ctx["applicant"]["id"]
        api.enroll_application(
            ctx["application_1"]["id"],
            make_applicant_headers(applicant_id),
        )
        # F2 was OFFERED on APP2 (which got cascaded to WITHDRAWN);
        # F2 must now be REVOKED (cascade hop 3).
        res = api.get_financial_aid(
            ctx["financial_aid_2"]["id"],
            TEST_USERS["financial_aid_officer_headers"],
        )
        f2_after = validate_success(res)
        assert f2_after["status"] == "REVOKED", (
            f"financial aid F2 must cascade to REVOKED, got {f2_after['status']!r}"
        )
