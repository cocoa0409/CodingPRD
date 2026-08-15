"""Disciplinary-event adjudication, license sanctions, and cascades."""
from test_helpers import (
    ApiErrorId,
    confirm_disciplinary_event,
    create_active_license,
    create_disciplinary_event,
    create_employee,
    create_license_type,
    create_role_requirement,
    get_success_data,
    make_officer_headers,
    setup_nurse_with_active_license,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OFFICER = TEST_USERS["officer_headers"]
OFFICER1 = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")


class TestConfirmCascade:
    def test_disciplinary_confirm_cascades_license_to_employee(self, api):
        """PRD §3.7: "Confirming a `RECEIVED` event moves it to `CONFIRMED`,
        stamps `adjudicated_by_user_id`, and applies the sanction by type: a
        `SUSPENSION` whose effect was not already applied at creation moves an
        `ACTIVE` license to `SUSPENDED`".

        Design: Difficulty/transitive_cascade/disciplinary_confirm_cascades_license_to_employee
        """
        lt, emp, lic = setup_nurse_with_active_license(
            email="nora.cascade@example.com", license_number="RN-8001")
        event = create_disciplinary_event(
            lic["id"], headers=OFFICER1, board_case_number="B-1",
            event_type="SUSPENSION", effective_on="2026-08-01")
        confirmed = confirm_disciplinary_event(event["id"], headers=OFFICER2)
        assert confirmed["status"] == "CONFIRMED"

        lic_after = get_success_data(api.get_license(lic["id"], OFFICER))
        assert lic_after["status"] == "SUSPENDED"

    def test_confirm_cascade_engages_restriction_and_bumps_versions(self, api):
        """PRD §3.7: "Every transition that suspends or revokes forces the
        license's `alert_tier` to `AT_EXPIRY` and re-derives the holder's work
        authorization: suspension engages the `LICENSE_SUSPENDED` reason".
        PRD §2.4: "`version` (integer): a system-managed counter that increments
        by one on every mutation, including mutations driven by cascades such as
        the expiry sweep or a disciplinary confirmation."

        Design: Difficulty/transitive_cascade/disciplinary_confirm_cascades_license_to_employee
        """
        lt, emp, lic = setup_nurse_with_active_license(
            email="nora.cascade2@example.com", license_number="RN-8001b")
        emp_v_before = get_success_data(api.get_employee(emp["id"], OFFICER))["version"]
        lic_v_before = get_success_data(api.get_license(lic["id"], OFFICER))["version"]

        event = create_disciplinary_event(
            lic["id"], headers=OFFICER1, board_case_number="B-2",
            event_type="SUSPENSION", effective_on="2026-08-01")
        confirm_disciplinary_event(event["id"], headers=OFFICER2)

        lic_after = get_success_data(api.get_license(lic["id"], OFFICER))
        assert lic_after["version"] == lic_v_before + 1
        assert lic_after["alert_tier"] == "AT_EXPIRY"

        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["work_authorization"] == "RESTRICTED"
        assert emp_after["restriction_reason"] == "LICENSE_SUSPENDED"
        assert emp_after["version"] == emp_v_before + 1


class TestDismissalCompensation:
    def test_dismiss_reverts_creation_applied_suspension(self, api):
        """PRD §3.7: "when `confirm_at_creation` is set on a `SUSPENSION`, the
        sanction bites immediately: an `ACTIVE` license drops to `SUSPENDED` at
        creation, `applied_at_creation` records that the effect was applied
        early, the event itself still sits at `RECEIVED` awaiting adjudication,
        and a later dismissal will unwind that suspension."

        Design: Corner/state_machines/dismiss_reverts_creation_applied_suspension
        """
        lt, emp, lic = setup_nurse_with_active_license(
            email="nora.dismiss@example.com", license_number="RN-9107")
        event = create_disciplinary_event(
            lic["id"], headers=OFFICER1, board_case_number="B-61",
            event_type="SUSPENSION", effective_on="2026-08-01",
            confirm_at_creation=True)
        assert event["applied_at_creation"] is True
        assert event["status"] == "RECEIVED"
        assert get_success_data(api.get_license(lic["id"], OFFICER))["status"] == "SUSPENDED"

        dismissed = validate_success(api.dismiss_disciplinary_event(
            event["id"], "Feed duplicate, not a real action", OFFICER2), 200)
        assert dismissed["status"] == "DISMISSED"

        assert get_success_data(api.get_license(lic["id"], OFFICER))["status"] == "ACTIVE"
        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["work_authorization"] == "AUTHORIZED"
        assert emp_after["restriction_reason"] is None


class TestDoubleSuspensionResolve:
    def test_second_open_suspension_keeps_license_suspended(self, api):
        """PRD §3.7: "a resolved `SUSPENSION` lifts — the license returns from
        `SUSPENDED` to `ACTIVE` — only when no other open suspension still
        covers that license, where open means another `SUSPENSION` event either
        standing at `CONFIRMED` or still at `RECEIVED` with
        `applied_at_creation` set".

        Design: Corner/state_machines/second_open_suspension_keeps_license_suspended
        """
        lt, emp, lic = setup_nurse_with_active_license(
            email="nora.dbl@example.com", license_number="RN-9104")
        de1 = create_disciplinary_event(
            lic["id"], headers=OFFICER1, board_case_number="B-41",
            event_type="SUSPENSION", effective_on="2026-08-01")
        de2 = create_disciplinary_event(
            lic["id"], headers=OFFICER2, board_case_number="B-42",
            event_type="SUSPENSION", effective_on="2026-08-01")
        confirm_disciplinary_event(de1["id"], headers=OFFICER2)
        confirm_disciplinary_event(de2["id"], headers=OFFICER1)

        validate_success(api.resolve_disciplinary_event(
            de1["id"], "First suspension lifted", OFFICER2), 200)
        mid = get_success_data(api.get_license(lic["id"], OFFICER))
        assert mid["status"] == "SUSPENDED", "B-42 still open keeps the suspension"

        validate_success(api.resolve_disciplinary_event(
            de2["id"], "Second suspension lifted", OFFICER1), 200)
        end = get_success_data(api.get_license(lic["id"], OFFICER))
        assert end["status"] == "ACTIVE"
        assert get_success_data(api.get_employee(
            emp["id"], OFFICER))["work_authorization"] == "AUTHORIZED"


class TestCaseNumberUniqueness:
    def test_duplicate_case_number_rejected(self, api):
        """PRD §3.7: "Case numbers are unique per license: a second event
        repeating an existing `board_case_number` on the same license fails with
        `ERR_DUPLICATE_CASE_NUMBER`."

        Design: Corner/validations/duplicate_case_number_rejected
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.case@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-9303")
        create_disciplinary_event(lic["id"], headers=OFFICER1,
                                  board_case_number="B-71", event_type="WARNING")
        resp = api.create_disciplinary_event(lic["id"], {
            "board_case_number": "B-71", "event_type": "FINE",
            "effective_on": "2026-08-01", "received_via": "MANUAL",
        }, OFFICER1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER, 409)


class TestRestrictionReasonPrecedence:
    def test_restriction_reason_precedence_chain(self, api):
        """PRD §3.2: "In precedence order from highest to lowest:
        `SCREENING_FLAGGED` applies when the employee's `screening_posture` is
        `FLAGGED`; `LICENSE_SUSPENDED` applies when any mandatory row is covered
        by a license in `SUSPENDED`; `LICENSE_LAPSED` applies when any mandatory
        row is covered by a license in `LAPSED` or `REVOKED`".

        Design: Corner/calculations/restriction_reason_precedence_screening_beats_suspension_beats_lapse
        """
        from test_helpers import (
            create_confirmed_match_screening,
            set_clock,
        )
        lt = create_license_type()  # grace 45d
        create_role_requirement(lt["id"], state_code="CA")
        create_role_requirement(lt["id"], state_code="TX")
        emp = create_employee(work_email="nora.prec@example.com")
        lic_ca = create_active_license(emp["id"], lt["id"], state_code="CA",
                                       license_number="RN-9203",
                                       expires_on="2026-12-31")
        lic_tx = create_active_license(emp["id"], lt["id"], state_code="TX",
                                       license_number="RN-9204",
                                       expires_on="2027-06-30", source="NURSYS")

        set_clock("2027-02-15T00:00:00Z")  # RN-CA lapses (expires + 45d = 02-14)
        r1 = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert r1["restriction_reason"] == "LICENSE_LAPSED"

        de = create_disciplinary_event(
            lic_tx["id"], headers=OFFICER1, board_case_number="B-71",
            event_type="SUSPENSION", effective_on="2027-02-15")
        confirm_disciplinary_event(de["id"], headers=OFFICER2)
        r2 = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert r2["restriction_reason"] == "LICENSE_SUSPENDED"

        create_confirmed_match_screening(emp["id"], screened_on="2027-02-15")
        r3 = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert r3["restriction_reason"] == "SCREENING_FLAGGED"

    def test_precedence_suspension_outranks_lapse_without_screening(self, api):
        """PRD §3.2: "`LICENSE_SUSPENDED` applies when any mandatory row is
        covered by a license in `SUSPENDED`; `LICENSE_LAPSED` applies when any
        mandatory row is covered by a license in `LAPSED` or `REVOKED`" —
        precedence order "from highest to lowest" puts SUSPENDED above LAPSED.

        Design: Corner/calculations/restriction_reason_precedence_screening_beats_suspension_beats_lapse
        """
        from test_helpers import set_clock
        lt = create_license_type()
        create_role_requirement(lt["id"], state_code="CA")
        create_role_requirement(lt["id"], state_code="TX")
        emp = create_employee(work_email="nora.prec2@example.com")
        create_active_license(emp["id"], lt["id"], state_code="CA",
                              license_number="RN-9205", expires_on="2026-12-31")
        lic_tx = create_active_license(emp["id"], lt["id"], state_code="TX",
                                       license_number="RN-9206",
                                       expires_on="2027-06-30", source="NURSYS")
        set_clock("2027-02-15T00:00:00Z")
        de = create_disciplinary_event(
            lic_tx["id"], headers=OFFICER1, board_case_number="B-72",
            event_type="SUSPENSION", effective_on="2027-02-15")
        confirm_disciplinary_event(de["id"], headers=OFFICER2)
        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["work_authorization"] == "RESTRICTED"
        assert emp_after["restriction_reason"] == "LICENSE_SUSPENDED"
