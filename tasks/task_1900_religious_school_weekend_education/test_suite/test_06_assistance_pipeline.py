"""Tuition assistance: review loop, segregation of duties, award variants."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_admin_headers, make_officer_headers,
    setup_open_year_with_section, setup_open_year,
    create_family, create_student, enroll_students_sequential,
    issue_invoice_fresh, create_application_payload,
    create_application_under_review,
)

ADMIN = TEST_USERS["admin_headers"]


class TestInfoRequestCycle:
    def test_submit_review_loop_repeats_with_reviewer_retained(self):
        """PRD §3.5: "If the committee needs more from the family, requesting
        information returns the application `UNDER_REVIEW` → `SUBMITTED` while
        retaining `reviewed_by_user_id` — the reviewing officer remains the
        segregated party — and the submit/review loop may repeat as needed."
        PRD §3.5: "Starting review moves the application `SUBMITTED` →
        `UNDER_REVIEW` and records the caller's `X-User-ID` as
        `reviewed_by_user_id`".

        Design: Difficulty/non_linear_state_machine/assistance_application_info_request_cycle
        """
        year, _plan = setup_open_year()
        family = create_family()
        app = get_success_data(
            api_client.create_application(
                family["id"], create_application_payload(year["id"]), ADMIN
            ),
            201,
        )
        officer = make_officer_headers("officer-1")
        r1 = get_success_data(api_client.start_review(app["id"], officer))
        assert r1["status"] == "UNDER_REVIEW"
        r2 = get_success_data(api_client.request_info(app["id"], officer))
        assert r2["status"] == "SUBMITTED"
        r3 = get_success_data(api_client.start_review(app["id"], officer))
        assert r3["status"] == "UNDER_REVIEW"
        app_now = get_success_data(api_client.get_application(app["id"], officer))
        assert app_now["reviewed_by_user_id"] == "officer-1"

    def test_reviewed_by_recorded_at_start_review(self):
        """PRD §3.5: "Starting review moves the application `SUBMITTED` →
        `UNDER_REVIEW` and records the caller's `X-User-ID` as
        `reviewed_by_user_id`, fixing the officer who owns the file."

        Design: Difficulty/non_linear_state_machine/assistance_application_info_request_cycle
        """
        year, _plan = setup_open_year()
        family = create_family()
        app = get_success_data(
            api_client.create_application(
                family["id"], create_application_payload(year["id"]), ADMIN
            ),
            201,
        )
        assert app["status"] == "SUBMITTED"
        assert app["reviewed_by_user_id"] is None
        reviewed = get_success_data(
            api_client.start_review(app["id"], make_officer_headers("officer-7"))
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["reviewed_by_user_id"] == "officer-7"


class TestSegregationOfDuties:
    def test_same_id_decide_rejected_different_admin_succeeds(self):
        """PRD §2.10: "a decide call whose `X-User-ID` equals the application's
        recorded `reviewed_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES`." PRD §3.5: "A valid approval persists the
        method and award figure as a snapshot on the application and records the
        decider as `decided_by_user_id`".

        Design: Corner/validations/segregation_of_duties_on_decide
        """
        year, _plan = setup_open_year()
        family = create_family()
        app = create_application_under_review(family["id"], year["id"], "officer-1")
        payload = {"decision": "APPROVED", "award_method": "FLAT_CAP",
                   "award_amount_cents": 50000}
        # Same human id reviewed and decided -> SoD violation.
        resp = api_client.decide_application(
            app["id"], payload, make_admin_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # A different admin id decides -> succeeds.
        ok = api_client.decide_application(app["id"], payload, make_admin_headers("admin-9"))
        ok_data = validate_success(ok, 200)
        assert ok_data["status"] == "APPROVED"
        assert ok_data["decided_by_user_id"] == "admin-9"

    def test_officer_cannot_decide(self):
        """PRD §4: the decide endpoint's Authorized Role(s) list contains only
        "SchoolAdmin". PRD §2.1: "a caller whose role is not on that list is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/officer_cannot_decide
        """
        year, _plan = setup_open_year()
        family = create_family()
        app = create_application_under_review(family["id"], year["id"], "officer-1")
        resp = api_client.decide_application(
            app["id"], {"decision": "DENIED"}, make_officer_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestAwardParams:
    def test_approved_without_method_rejected_denied_needs_none(self):
        """PRD §3.5: "An approval additionally requires the award parameters:
        `award_method` must be present as either `PERCENT_OF_NET` or `FLAT_CAP`...
        An approval missing the method or carrying the wrong or invalid award field
        is rejected with `ERR_AWARD_PARAMS_INVALID`. A valid approval persists the
        method and award figure as a snapshot on the application and records the
        decider as `decided_by_user_id`; a denial records only `decided_by_user_id`."

        Design: Corner/validations/award_params_required_when_approved
        """
        year, _plan = setup_open_year()
        fam_a = create_family()
        fam_b = create_family()
        app_a = create_application_under_review(fam_a["id"], year["id"], "officer-1")
        app_b = create_application_under_review(fam_b["id"], year["id"], "officer-2")
        resp = api_client.decide_application(
            app_a["id"], {"decision": "APPROVED"}, make_admin_headers("admin-9")
        )
        validate_error(resp, ApiErrorId.ERR_AWARD_PARAMS_INVALID)
        ok = api_client.decide_application(
            app_b["id"], {"decision": "DENIED"}, make_admin_headers("admin-9")
        )
        ok_data = validate_success(ok, 200)
        assert ok_data["status"] == "DENIED"


class TestDuplicateApplication:
    def test_second_live_application_rejected(self):
        """PRD §3.5: "a family may have at most one live application per year —
        any existing application for the same family and year in a status other
        than `DENIED` causes the new one to be rejected with
        `ERR_APPLICATION_ALREADY_OPEN`."

        Design: Corner/validations/duplicate_application_rejected
        """
        year, _plan = setup_open_year()
        family = create_family()
        get_success_data(
            api_client.create_application(
                family["id"], create_application_payload(year["id"]), ADMIN
            ),
            201,
        )
        resp = api_client.create_application(
            family["id"], create_application_payload(year["id"]), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_ALREADY_OPEN)


class TestAwardVariants:
    def test_percent_of_net_vs_flat_cap_diverge(self):
        """PRD §3.5: "Under `PERCENT_OF_NET` the award is `award_percent`
        multiplied by the invoice's `gross_cents`, rounded half up to whole cents —
        the percent applies to gross tuition only, never to the activity fee. Under
        `FLAT_CAP` the award is the smaller of `award_amount_cents` and
        `gross_cents`, so the flat award can never exceed the gross. The two methods
        genuinely diverge". PRD §3.5: "the invoice's `award_cents` is computed from
        it and the invoice records the source in `assistance_application_id`".

        Design: Difficulty/dual_variant_calc/assistance_award_percent_of_net_vs_flat_cap
        """
        ctx = setup_open_year_with_section(capacity=10)
        section, year = ctx["section"], ctx["year"]

        def make_family_with_approved_app(award_payload, officer_id):
            fam = create_family()
            kids = [create_student(fam["id"]) for _ in range(3)]
            enroll_students_sequential(section["id"], [k["id"] for k in kids])
            app = create_application_under_review(fam["id"], year["id"], officer_id)
            decided = get_success_data(
                api_client.decide_application(
                    app["id"], award_payload, make_admin_headers("admin-9")
                )
            )
            assert decided["status"] == "APPROVED"
            return fam, app

        fam_p, app_p = make_family_with_approved_app(
            {"decision": "APPROVED", "award_method": "PERCENT_OF_NET",
             "award_percent": 0.25},
            "officer-1",
        )
        fam_q, app_q = make_family_with_approved_app(
            {"decision": "APPROVED", "award_method": "FLAT_CAP",
             "award_amount_cents": 150000},
            "officer-2",
        )
        inv_p = issue_invoice_fresh(fam_p["id"], year["id"])
        inv_q = issue_invoice_fresh(fam_q["id"], year["id"])
        # Identical data: 3 MEMBER students, same ranking -> identical gross.
        assert inv_p["gross_cents"] == 181069
        assert inv_q["gross_cents"] == 181069
        # PERCENT_OF_NET: round_half_up(0.25 * 181069) = 45267
        assert inv_p["award_cents"] == 45267
        # FLAT_CAP: min(150000, 181069) = 150000
        assert inv_q["award_cents"] == 150000
        assert inv_p["total_due_cents"] == 181069 + 5000 - 45267
        assert inv_q["total_due_cents"] == 181069 + 5000 - 150000
        assert inv_p["assistance_application_id"] == app_p["id"]
        assert inv_q["assistance_application_id"] == app_q["id"]

    def test_no_approved_application_zero_award(self):
        """PRD §3.5: "otherwise `award_cents` is 0 and `assistance_application_id`
        is null."

        Design: Difficulty/dual_variant_calc/assistance_award_percent_of_net_vs_flat_cap
        """
        ctx = setup_open_year_with_section()
        section, year = ctx["section"], ctx["year"]
        fam = create_family()
        kid = create_student(fam["id"])
        enroll_students_sequential(section["id"], [kid["id"]])
        inv = issue_invoice_fresh(fam["id"], year["id"])
        assert inv["award_cents"] == 0
        assert inv["assistance_application_id"] is None
