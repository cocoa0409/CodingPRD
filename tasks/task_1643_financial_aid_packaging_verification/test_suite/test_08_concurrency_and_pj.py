"""Optimistic concurrency (package lock, PJ approval) and the professional
judgment approval cascade into the packaging snapshots (PRD §2.9, §3.5, §3.6)."""
from test_helpers import (
    SSN_SELECTED_B,
    TEST_USERS,
    ApiErrorId,
    accept_package_in_full,
    assert_pj_case,
    assert_timestamp_format,
    build_package,
    create_package,
    create_pj_case,
    get_package,
    get_package_lines,
    get_success_data,
    import_isir,
    make_aid_officer_headers,
    register_student,
    setup_notified_package,
    setup_open_aid_year,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]
DIRECTOR = TEST_USERS["aid_director_headers"]


class TestPackageLockOcc:
    def test_lock_with_stale_version_rejected(self, api):
        """PRD §2.9: "A request to lock an award package must carry `expected_package_version`, holding the package `version` the client last observed. If the package's current `version` has advanced since that observation — for example because a per-line acceptance released pool reservations and bumped the version — the lock is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412), preventing the client from locking a package it has not observed."

        Design: Corner/errors/error_stale_package_version_on_lock
        """
        env = setup_notified_package(ssn=SSN_SELECTED_B)
        stale_version = get_package(env["package"]["id"])["version"]

        # The acceptance advances the package version past the observation.
        accept_package_in_full(env["package"]["id"], env["student"]["id"])

        resp = api.lock_award_package(env["package"]["id"], stale_version,
                                      OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_PACKAGE_VERSION)
        assert get_package(env["package"]["id"])["status"] == "ACCEPTED"

    def test_lock_with_fresh_version_succeeds(self, api):
        """PRD §3.6: "When the student has accepted, an `AidOfficer` locks the package, moving it from `ACCEPTED` or `PARTIALLY_ACCEPTED` to the terminal `LOCKED`, stamping `version_locked_at` and incrementing `version`."
        PRD §2.9: "A request to lock an award package must carry `expected_package_version`, holding the package `version` the client last observed."

        Design: Corner/cross_cutting_layers/occ_lock_success_with_fresh_version
        """
        env = setup_notified_package(ssn=SSN_SELECTED_B)
        accept_package_in_full(env["package"]["id"], env["student"]["id"])
        observed = get_package(env["package"]["id"])["version"]

        resp = api.lock_award_package(env["package"]["id"], observed, OFFICER)
        locked = validate_success(resp)
        assert locked["status"] == "LOCKED"
        assert locked["version"] == observed + 1
        assert_timestamp_format(locked["version_locked_at"])


class TestPjApprovalOcc:
    def _setup_pj_under_review(self, api, ssn=SSN_SELECTED_B):
        env = setup_open_aid_year()
        student = register_student(ssn, full_name="Stale PJ",
                                   email="spj@example.edu")
        import_isir(student["id"], env["aid_year"]["id"], agi_cents=4500000)
        pj = create_pj_case(student["id"], env["aid_year"]["id"],
                            requested_delta_cents=-500000,
                            justification="Documented medical expense "
                                          "catastrophe in family")
        return env, student, pj

    def test_approve_with_stale_pj_version_rejected(self, api):
        """PRD §2.9: "A request to approve a professional judgment case must carry `expected_pj_version`, holding the case `version` the client last observed. If the case's current `version` has advanced since that observation — for example because another writer denied the case — the approval is rejected with `ERR_STALE_PJ_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_pj_version_on_approve
        """
        env, student, pj = self._setup_pj_under_review(api)
        stale_version = pj["version"]

        # begin-review captures the reviewer and advances the case version.
        validate_success(api.begin_review_pj_case(
            pj["id"], make_aid_officer_headers("officer-alpha")))

        resp = api.approve_pj_case(pj["id"], stale_version, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_PJ_VERSION)
        current = get_success_data(api.get_pj_case(pj["id"], OFFICER))
        assert current["status"] == "UNDER_REVIEW"

    def test_approve_from_submitted_is_invalid_state(self, api):
        """PRD §3.5: "Approval is guarded more heavily. The case must be `UNDER_REVIEW`; `documentation_complete` must be true; for an `EFC_ADJUSTMENT` the non-positive delta must also leave the current ISIR's `efc_official_cents` at zero or above once applied; for a `COA_ADJUSTMENT` the delta must be positive; and for a `DEPENDENCY_OVERRIDE` the student must currently be `DEPENDENT`."
        PRD §2.7 (rung 5): "the target entity's state machine permits the requested transition from its current state — otherwise `ERR_INVALID_STATE` (409)."
        PRD §2.7: "The checks are evaluated in the priority order given below, so an earlier failure masks later ones — for example, an unauthenticated caller always sees `ERR_UNAUTHENTICATED` even if the request would also have failed a downstream business rule."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pj_approve
        """
        env, student, pj = self._setup_pj_under_review(api)
        resp = api.approve_pj_case(pj["id"], pj["version"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_pj_case(pj["id"], OFFICER))
        assert current["status"] == "SUBMITTED"

    def test_deny_from_submitted_is_invalid_state(self, api):
        """PRD §3.5: "The case is born `SUBMITTED`. An `AidOfficer` begins review, moving it to `UNDER_REVIEW` and capturing the caller's `X-User-ID` into `reviewed_by_user_id`."
        PRD §2.7 (rung 5): "the target entity's state machine permits the requested transition from its current state — otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pj_approve
        """
        env, student, pj = self._setup_pj_under_review(api)
        resp = api.deny_pj_case(pj["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_pj_case(pj["id"], OFFICER))
        assert current["status"] == "SUBMITTED"


class TestPjApprovalCascade:
    def test_efc_adjustment_applied_at_next_packaging_build(self, api):
        """PRD §3.5: "An approved case takes effect immediately and durably. The `decided_by_user_id` is recorded; for an EFC adjustment `applied_efc_delta_cents` is set to the requested delta (it is zero for the other types), and for a COA adjustment `applied_coa_delta_cents` is set to the requested delta (likewise zero otherwise); a dependency override flips the student's `dependency_status` to `INDEPENDENT`."
        PRD §3.6: "`efc_used_cents` is the current ISIR's `efc_official_cents` minus the sum of `applied_efc_delta_cents` over those approved cases, floored at zero. `need_cents` is the cost snapshot minus the EFC snapshot, floored at zero, and is recomputed whenever the package is rebuilt."

        Design: Corner/cross_cutting_layers/pj_approval_efc_delta_applied_and_packaging_uses_it
        """
        env = setup_open_aid_year()
        student = register_student(SSN_SELECTED_B, full_name="PJ Cascade",
                                   email="pjc@example.edu")
        isir = import_isir(student["id"], env["aid_year"]["id"],
                           agi_cents=4500000, asset_net_worth_cents=50000)
        assert isir["efc_official_cents"] == 742000

        pj = create_pj_case(student["id"], env["aid_year"]["id"],
                            requested_delta_cents=-742000,
                            justification="Parent incarcerated; documented "
                                          "special circumstances file")
        validate_success(api.begin_review_pj_case(
            pj["id"], make_aid_officer_headers("officer-alpha")))
        current = get_success_data(api.get_pj_case(pj["id"], OFFICER))
        approved = validate_success(api.approve_pj_case(
            pj["id"], current["version"], DIRECTOR))
        assert_pj_case(approved)
        assert approved["status"] == "APPROVED"
        assert approved["applied_efc_delta_cents"] == -742000
        assert approved["decided_by_user_id"] == "test-aid-director-1"

        package = create_package(student["id"], env["aid_year"]["id"])
        package = build_package(package["id"])
        # 742_000 - 742_000, floored at zero.
        assert package["efc_used_cents"] == 0
        assert package["need_cents"] == 2400000
        # EFC 0 lands in Pell schedule row [0, 150000] -> full 739_500 offer.
        assert package["total_offered_cents"] == 739500
        lines = get_package_lines(package["id"])
        assert len(lines) == 1
        assert lines[0]["offered_cents"] == 739500
