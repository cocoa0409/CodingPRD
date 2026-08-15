"""State-license lifecycle and compact-privilege derivation: verification pipeline,
attestation freshness, renewal window/cycle, surrender, privilege evaluation log
(PRD §2.4, §2.5, §2.8, §3.2, §3.3)."""
import pytest

from test_helpers import (
    COMPACT_STATES,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_privilege_evaluation,
    assert_psv,
    assert_state_license,
    attest_license,
    create_active_license,
    create_license_draft,
    create_nurse,
    create_psv_payload,
    get_license,
    get_nurse,
    list_privilege_evals,
    record_psv_verified,
    request_psv,
    run_sweep,
    set_clock,
    setup_credentialed_nurse,
    submit_license,
    surrender_license,
    validate_error,
    validate_paginated,
    validate_success,
    verify_license_via_psv,
)
from test_helpers import api_client, TEST_USERS

SPEC1 = TEST_USERS["specialist_1"]
VER1 = TEST_USERS["verifier_1"]
VER2 = TEST_USERS["verifier_2"]
CO1 = TEST_USERS["compliance_1"]


class TestLicenseStateMachine:
    def test_license_submit_from_pending_rejected(self):
        """PRD §3.2: "Submission to verification is allowed only from `DRAFT`, else
        `ERR_INVALID_LICENSE_STATE`."

        Design: Corner/state_machines/license_submit_from_pending_rejected
        """
        set_clock()
        nurse = create_nurse(full_name="Sub Twice", email="sub.twice@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-ST1")
        submit_license(lic["id"])

        resp = api_client.submit_license(lic["id"], SPEC1)
        validate_error(resp, ApiErrorId.ERR_INVALID_LICENSE_STATE)
        after = get_license(lic["id"])
        assert after["status"] == "PENDING_VERIFICATION"

    def test_surrendered_license_terminal_lockdown(self):
        """PRD §3.2: "Finally, a `ComplianceOfficer` may surrender a license from any
        status other than `SURRENDERED` — attempting surrender on a surrendered license
        is `ERR_INVALID_LICENSE_STATE` — and `SURRENDERED` is terminal."
        PRD §3.2: "a license in any state other than `EXPIRED` or window-eligible
        `ACTIVE` rejects with `ERR_INVALID_LICENSE_STATE`."

        Design: Corner/state_machines/surrendered_license_terminal_lockdown
        """
        set_clock()
        nurse = create_nurse(full_name="Sur Render", email="sur.render@x.com")
        lic = create_active_license(nurse["id"], license_number="RN-AZ-SR1")
        surrendered = surrender_license(lic["id"])
        assert surrendered["status"] == "SURRENDERED"

        resp_attest = api_client.attest_license(lic["id"], VER2)
        validate_error(resp_attest, ApiErrorId.ERR_INVALID_LICENSE_STATE)
        resp_renew = api_client.renew_license(
            lic["id"], {"new_expires_on": "2027-12-31"}, SPEC1
        )
        validate_error(resp_renew, ApiErrorId.ERR_INVALID_LICENSE_STATE)
        after = get_license(lic["id"])
        assert after["status"] == "SURRENDERED", "terminal state is never left"

    def test_psv_record_result_twice_rejected(self):
        """PRD §3.2: "A `PrimarySourceVerifier` records the `outcome` of a verification
        from `REQUESTED` — from any other state the attempt is `ERR_INVALID_PSV_STATE`
        — and the recorder must differ from the requester, else
        `ERR_SEGREGATION_OF_DUTIES`; the recorder is stamped into
        `resolved_by_user_id`."

        Design: Corner/state_machines/psv_record_result_twice_rejected
        """
        set_clock()
        nurse = create_nurse(full_name="Psv Twice", email="psv.twice@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-PT1")
        submit_license(lic["id"])
        psv = request_psv(lic["id"])
        record_psv_verified(psv["id"])

        resp = api_client.record_psv_result(psv["id"], {"outcome": "VERIFIED"}, VER2)
        validate_error(resp, ApiErrorId.ERR_INVALID_PSV_STATE)
        after = validate_success(api_client.get_psv(psv["id"], SPEC1), 200)
        assert_psv(after)
        assert after["status"] == "VERIFIED"
        assert after["resolved_by_user_id"] == "ver-1"


class TestLicenseCreationRules:
    def test_multistate_flag_non_compact_rejected(self):
        """PRD §3.2: "Setting `multistate_flag` true is allowed only when the
        `state_code` belongs to the compact state set of §3.3; otherwise creation fails
        with `ERR_MULTISTATE_NON_COMPACT_STATE`."
        PRD §3.3: "The compact state set contains eight states: `AZ`, `CO`, `FL`, `GA`,
        `MD`, `NC`, `TN`, and `TX`."

        Design: Corner/validations/multistate_flag_non_compact_rejected
        """
        set_clock()
        nurse = create_nurse(full_name="Cal Ifornia", email="cal.ifornia@x.com",
                             primary_state_of_residence="CA")
        resp = api_client.create_state_license(
            {
                "nurse_id": nurse["id"],
                "state_code": "CA",
                "license_number": "RN-CA-CN1",
                "license_class": "RN",
                "multistate_flag": True,
                "issued_on": "2026-06-15",
                "expires_on": "2027-06-30",
            },
            SPEC1,
        )
        validate_error(resp, ApiErrorId.ERR_MULTISTATE_NON_COMPACT_STATE)

        ok = validate_success(
            api_client.create_state_license(
                {
                    "nurse_id": nurse["id"],
                    "state_code": "TX",
                    "license_number": "RN-TX-CN2",
                    "license_class": "RN",
                    "multistate_flag": True,
                    "issued_on": "2026-06-15",
                    "expires_on": "2027-06-30",
                },
                SPEC1,
            ),
            201,
        )
        assert_state_license(ok)
        assert ok["status"] == "DRAFT"

    def test_psv_create_license_not_found_returns_404(self):
        """PRD §2.9: "5. **Body referential integrity** — foreign keys in the payload
        must resolve: `nurse_id` (`ERR_NURSE_NOT_FOUND`), `license_id`
        (`ERR_LICENSE_NOT_FOUND`), `unit_id` or `target_unit_id`
        (`ERR_UNIT_NOT_FOUND`), and `requirement_id` (`ERR_REQUIREMENT_NOT_FOUND`),
        all 404."

        Design: Corner/validations/psv_create_license_not_found_returns_404
        """
        resp = api_client.create_psv(
            create_psv_payload(NON_EXISTENT_UUID, channel="NURSYS"), SPEC1
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_FOUND)
        _data, meta = validate_paginated(api_client.list_psvs(SPEC1))
        assert meta["total_count"] == 0


class TestRenewalWindow:
    def test_license_renewal_window_boundary(self):
        """PRD §3.2: "Renewal brings an `EXPIRED` license back to life, and — as a
        proactive path — may also be invoked on an `ACTIVE` license whose expiry is at
        most 60 days away. An `ACTIVE` license further from expiry than 60 days rejects
        with `ERR_RENEWAL_WINDOW_NOT_OPEN`, and a license in any state other than
        `EXPIRED` or window-eligible `ACTIVE` rejects with `ERR_INVALID_LICENSE_STATE`."

        Design: Corner/validations/license_renewal_window_boundary
        """
        set_clock("2026-07-01T00:00:00Z")
        nurse = create_nurse(full_name="Ren Window", email="ren.window@x.com",
                             hire_date="2026-06-01")
        lic = create_active_license(
            nurse["id"], license_number="RN-AZ-RW1",
            issued_on="2026-06-01", expires_on="2026-09-30",
        )

        # 61 days before expiry: the renewal window is not yet open.
        set_clock("2026-07-31T00:00:00Z")
        resp = api_client.renew_license(
            lic["id"], {"new_expires_on": "2027-09-30"}, SPEC1
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN)
        mid = get_license(lic["id"])
        assert mid["status"] == "ACTIVE"
        assert mid["expires_on"] == "2026-09-30"

        # Exactly 60 days before expiry (inclusive): renewal opens.
        set_clock("2026-08-01T00:00:00Z")
        ok = validate_success(
            api_client.renew_license(lic["id"], {"new_expires_on": "2027-09-30"}, SPEC1),
            200,
        )
        assert ok["status"] == "ACTIVE"
        assert ok["expires_on"] == "2027-09-30"


class TestPsvFreshnessBoundary:
    def test_psv_valid_through_inclusive_boundary(self):
        """PRD §3.2: "Attestation also requires a fresh verification on file — at least
        one verification row in `VERIFIED` status whose `valid_through` is on or after
        the current date. The freshness boundary is inclusive: a verification whose
        `valid_through` equals the current date still counts."
        PRD §3.2: "`VERIFIED` sets `verified_on` to the current clock date and
        `valid_through` to `verified_on` plus 180 days, ..."

        Design: Corner/calculations/psv_valid_through_inclusive_boundary
        """
        set_clock()
        nurse = create_nurse(full_name="Vera Fresh", email="vera.fresh@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-VF1")
        psv = verify_license_via_psv(lic["id"])
        assert psv["valid_through"] == "2027-01-28", (
            f"verified_on 2026-08-01 + 180 days; got {psv['valid_through']}"
        )

        set_clock("2027-01-28T00:00:00Z")
        ok = validate_success(api_client.attest_license(lic["id"], VER1), 200)
        assert ok["status"] == "ACTIVE", (
            "valid_through == current_date satisfies the inclusive freshness check"
        )

    def test_attest_response_immediately_consistent(self):
        """PRD §2.8: "Consistency is immediate: every mutation and the cascades it
        triggers commit atomically within the request — or within the sweep run — that
        caused them."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/attest_response_immediately_consistent
        """
        set_clock()
        nurse = create_nurse(full_name="Con Sistent", email="con.sistent@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-CS1")
        verify_license_via_psv(lic["id"])

        attest_data = validate_success(api_client.attest_license(lic["id"], VER1), 200)
        assert attest_data["status"] == "ACTIVE"
        assert attest_data["verified_by_user_id"] == "ver-1"

        read_back = validate_success(api_client.get_state_license(lic["id"], SPEC1), 200)
        assert read_back["status"] == attest_data["status"] == "ACTIVE"
        assert read_back["verified_by_user_id"] == attest_data["verified_by_user_id"] == "ver-1"


class TestPrivilegeDerivation:
    def test_privilege_evaluation_immutable_event(self):
        """PRD §2.4: "One deliberate exception exists: `PrivilegeEvaluation` is an
        append-only event log whose rows carry only `id` and `created_at` — both
        `updated_at` and `version` are absent, and rows are never modified once
        written."
        PRD §3.2: "A successful attestation re-derives the nurse's compact privilege,
        appending a `LICENSE_CHANGE` evaluation when the result moved, and recomputes
        her posture."
        PRD §3.1: "Creation runs an initial privilege derivation so `practice_scope`
        reflects whatever the derivation yields, but no `PrivilegeEvaluation` row is
        appended at this point."

        Design: Corner/entities/privilege_evaluation_immutable_event
        """
        set_clock()
        nurse = create_nurse(full_name="Ed Log", email="ed.log@x.com")
        lic = create_active_license(nurse["id"], license_number="RN-AZ-EL1")

        evals = list_privilege_evals(nurse["id"])
        assert len(evals) == 1, "creation appends nothing; the attest moved NONE -> ELIGIBLE"
        row = evals[0]
        assert_privilege_evaluation(row)
        assert row["trigger_reason"] == "LICENSE_CHANGE"
        assert row["resulting_status"] == "ELIGIBLE_MULTISTATE"
        assert row["resulting_scope"] == sorted(COMPACT_STATES)
        assert row["home_license_id"] == lic["id"]

    def test_privilege_scope_union_and_single_state_fallback(self):
        """PRD §3.3: "When a home license exists, its `multistate_flag` is true, the
        PSOR is one of the compact states, and no open privilege encumbrance exists,
        the nurse is `ELIGIBLE_MULTISTATE` and her scope is the full compact state
        list, sorted ascending."
        PRD §3.3: "Otherwise, the nurse derives from whatever `ACTIVE` licenses she
        holds: the scope is the sorted, distinct set of those licenses' `state_code`
        values; with at least one such license the status is `SINGLE_STATE_ONLY`, and
        with none it is `NONE` and the scope is the empty list."
        PRD §3.2: "Every surrender re-derives privilege (a `LICENSE_CHANGE` row when
        changed) and recomputes posture."

        Design: Corner/calculations/privilege_scope_union_and_single_state_fallback
        """
        set_clock()
        nurse = create_nurse(full_name="Uma Scope", email="uma.scope@x.com",
                             primary_state_of_residence="AZ")
        lic_az = create_active_license(nurse["id"], state_code="AZ",
                                       license_number="RN-AZ-US1")
        _lic_tx = create_active_license(nurse["id"], state_code="TX",
                                        license_number="RN-TX-US2", multistate_flag=False)

        before = get_nurse(nurse["id"])
        assert before["multistate_privilege_status"] == "ELIGIBLE_MULTISTATE"
        assert before["practice_scope"] == sorted(COMPACT_STATES)

        surrender_license(lic_az["id"])
        after = get_nurse(nurse["id"])
        assert after["multistate_privilege_status"] == "SINGLE_STATE_ONLY"
        assert after["practice_scope"] == ["TX"], (
            "single-state fallback over the remaining ACTIVE licenses"
        )


class TestLicenseExpiryRenewalCycle:
    """Difficulty instance: license_expiry_renewal_cycle — the cyclic
    ACTIVE -> EXPIRED (sweep) -> ACTIVE (renew with fresh PSV) loop."""

    def _setup_cycle(self):
        set_clock()
        nurse = create_nurse(full_name="Lena Cycle", email="lena.cycle@x.com")
        lic = create_active_license(nurse["id"], license_number="RN-AZ-LC1",
                                    expires_on="2026-12-31")
        set_clock("2027-01-01T00:00:00Z")
        return nurse, lic

    def test_license_sweep_expire_then_renew_reactivates(self):
        """PRD §2.5: "Expiry is inclusive throughout the platform: a license,
        certification, or competency completion is valid through its `expires_on` date
        inclusive, and lapses only when the current date is strictly after
        `expires_on`."
        PRD §3.9: "First, licenses standing `ACTIVE` or `ENCUMBERED` whose `expires_on`
        has passed move to `EXPIRED`."
        PRD §3.2: "Renewal brings an `EXPIRED` license back to life, ..."

        Design: Difficulty/non_linear_state_machine/license_expiry_renewal_cycle
        """
        _nurse, lic = self._setup_cycle()
        summary = run_sweep()
        assert summary["licenses_expired"] == 1
        expired = get_license(lic["id"])
        assert expired["status"] == "EXPIRED", "2026-12-31 < 2027-01-01"

        psv2 = request_psv(lic["id"], channel="BOARD_PORTAL")
        record_psv_verified(psv2["id"])
        renewed = validate_success(
            api_client.renew_license(lic["id"], {"new_expires_on": "2027-12-31"}, SPEC1),
            200,
        )
        assert renewed["status"] == "ACTIVE", "the EXPIRED -> ACTIVE loop edge closed"
        assert renewed["expires_on"] == "2027-12-31"

    def test_psv_verified_on_expired_license_leaves_state_untouched(self):
        """PRD §3.2: "`VERIFIED` sets `verified_on` to the current clock date and
        `valid_through` to `verified_on` plus 180 days, and — when the underlying
        license stands `PENDING_VERIFICATION` — moves the license to `VERIFIED`;
        recording a verified outcome against a license already `VERIFIED` or `EXPIRED`
        leaves the license state untouched."
        PRD §3.2: "A verification may be requested for a license standing
        `PENDING_VERIFICATION`, `VERIFIED`, or `EXPIRED`; against any other license
        state the request is rejected with `ERR_INVALID_LICENSE_STATE`."

        Design: Difficulty/non_linear_state_machine/license_expiry_renewal_cycle
        """
        _nurse, lic = self._setup_cycle()
        run_sweep()
        assert get_license(lic["id"])["status"] == "EXPIRED"

        psv2 = request_psv(lic["id"], channel="BOARD_PORTAL")
        psv2_done = record_psv_verified(psv2["id"])
        assert psv2_done["status"] == "VERIFIED"
        assert psv2_done["verified_on"] == "2027-01-01"
        assert psv2_done["valid_through"] == "2027-06-30", (
            "verified_on + 180 days"
        )
        after = get_license(lic["id"])
        assert after["status"] == "EXPIRED", (
            "a VERIFIED result against an EXPIRED license moves nothing until renew"
        )


class TestLicenseExpiryInclusiveBoundary:
    """Difficulty instance: license_expiry_inclusive_date_boundary — the
    strictly-greater date comparison at expires_on."""

    def _setup_two_active_licenses(self):
        set_clock()
        nurse_m1 = create_nurse(full_name="Mia One", email="mia.one@x.com")
        lic_m1 = create_active_license(nurse_m1["id"], license_number="RN-AZ-MO1",
                                       expires_on="2026-08-15")
        nurse_m2 = create_nurse(full_name="Max Two", email="max.two@x.com")
        lic_m2 = create_active_license(nurse_m2["id"], license_number="RN-AZ-MT1",
                                       expires_on="2026-08-15")
        return lic_m1, lic_m2

    def test_expiry_day_of_expiration_stays_active(self):
        """PRD §2.5: "Expiry is inclusive throughout the platform: a license,
        certification, or competency completion is valid through its `expires_on` date
        inclusive, and lapses only when the current date is strictly after
        `expires_on`. A credential whose `expires_on` equals the current date is still
        valid on that day."

        Design: Difficulty/boundary_precision_check/license_expiry_inclusive_date_boundary
        """
        lic_m1, lic_m2 = self._setup_two_active_licenses()
        set_clock("2026-08-15T23:59:00Z")
        summary = run_sweep()
        assert summary["licenses_expired"] == 0, (
            "expires_on == current_date stays ACTIVE"
        )
        assert get_license(lic_m1["id"])["status"] == "ACTIVE"
        assert get_license(lic_m2["id"])["status"] == "ACTIVE"

    def test_expiry_day_after_expiration_expires(self):
        """PRD §2.5: "Expiry is inclusive throughout the platform: a license,
        certification, or competency completion is valid through its `expires_on` date
        inclusive, and lapses only when the current date is strictly after
        `expires_on`."
        PRD §3.9: "First, licenses standing `ACTIVE` or `ENCUMBERED` whose `expires_on`
        has passed move to `EXPIRED`."

        Design: Difficulty/boundary_precision_check/license_expiry_inclusive_date_boundary
        """
        lic_m1, lic_m2 = self._setup_two_active_licenses()
        set_clock("2026-08-15T23:59:00Z")
        summary_day_of = run_sweep()
        assert summary_day_of["licenses_expired"] == 0

        set_clock("2026-08-16T00:00:00Z")
        summary_day_after = run_sweep()
        assert summary_day_after["licenses_expired"] == 2
        assert get_license(lic_m1["id"])["status"] == "EXPIRED"
        assert get_license(lic_m2["id"])["status"] == "EXPIRED"


class TestAttestGatedOnFreshPsv:
    """Difficulty instance: license_attest_gated_on_fresh_psv — VERIFIED -> ACTIVE
    requires a PSV whose 180-day freshness window still covers the current date."""

    def _setup_verified_license_stale_psv(self):
        set_clock()
        nurse = create_nurse(full_name="Ivan Fresh", email="ivan.fresh@x.com")
        lic = create_license_draft(nurse["id"], license_number="RN-AZ-IF1")
        psv = verify_license_via_psv(lic["id"])
        assert psv["valid_through"] == "2027-01-28"
        set_clock("2027-01-29T00:00:00Z")
        return nurse, lic, psv

    def test_attest_with_stale_psv_rejected(self):
        """PRD §3.2: "With no `VERIFIED` verification at all, or with every `VERIFIED`
        verification stale, attestation fails with `ERR_PSV_STALE`."

        Design: Difficulty/cross_entity_state_dependency/license_attest_gated_on_fresh_psv
        """
        _nurse, lic, _psv = self._setup_verified_license_stale_psv()
        resp = api_client.attest_license(lic["id"], VER1)
        validate_error(resp, ApiErrorId.ERR_PSV_STALE)
        after = get_license(lic["id"])
        assert after["status"] == "VERIFIED", "the rejected attest moves nothing"

    def test_attest_succeeds_after_fresh_psv_recorded(self):
        """PRD §3.2: "Attestation also requires a fresh verification on file — at least
        one verification row in `VERIFIED` status whose `valid_through` is on or after
        the current date."
        PRD §3.2: "recording a verified outcome against a license already `VERIFIED` or
        `EXPIRED` leaves the license state untouched."
        PRD §3.2: "The attester is stamped into `verified_by_user_id`, which stays null
        until attestation."

        Design: Difficulty/cross_entity_state_dependency/license_attest_gated_on_fresh_psv
        """
        _nurse, lic, _psv = self._setup_verified_license_stale_psv()
        psv2 = request_psv(lic["id"], channel="BOARD_PORTAL")
        psv2_done = record_psv_verified(psv2["id"])
        assert psv2_done["verified_on"] == "2027-01-29"
        assert psv2_done["valid_through"] == "2027-07-28", "verified_on + 180 days"
        assert get_license(lic["id"])["status"] == "VERIFIED", (
            "recording VERIFIED against an already-VERIFIED license moves nothing"
        )

        ok = validate_success(api_client.attest_license(lic["id"], VER1), 200)
        assert ok["status"] == "ACTIVE"
        assert ok["verified_by_user_id"] == "ver-1"


class TestPrivilegeGatedOnHomeLicenseState:
    """Difficulty instance: privilege_gated_on_home_license_state — the multistate
    privilege exists only while the PSOR home license stands ACTIVE."""

    def _setup_hana_surrendered(self):
        set_clock()
        nurse = create_nurse(full_name="Hana Priv", email="hana.priv@x.com",
                             primary_state_of_residence="AZ")
        lic = create_active_license(nurse["id"], license_number="RN-AZ-HP1")
        surrender_license(lic["id"])
        return nurse, lic

    def test_surrender_collapses_privilege_to_none(self):
        """PRD §3.3: "Otherwise, the nurse derives from whatever `ACTIVE` licenses she
        holds: the scope is the sorted, distinct set of those licenses' `state_code`
        values; with at least one such license the status is `SINGLE_STATE_ONLY`, and
        with none it is `NONE` and the scope is the empty list."
        PRD §3.2: "Every surrender re-derives privilege (a `LICENSE_CHANGE` row when
        changed) and recomputes posture."

        Design: Difficulty/cross_entity_state_dependency/privilege_gated_on_home_license_state
        """
        nurse, lic = self._setup_hana_surrendered()
        assert get_license(lic["id"])["status"] == "SURRENDERED"
        after = get_nurse(nurse["id"])
        assert after["multistate_privilege_status"] == "NONE"
        assert after["practice_scope"] == []

        observed = get_nurse(nurse["id"])
        evaluation = validate_success(
            api_client.create_privilege_evaluation(
                {"nurse_id": nurse["id"],
                 "expected_nurse_version": observed["version"]},
                SPEC1,
            ),
            201,
        )
        assert evaluation["trigger_reason"] == "MANUAL"
        assert evaluation["resulting_status"] == "NONE", (
            "the explicit re-evaluation confirms the license-state-driven collapse"
        )
        assert evaluation["resulting_scope"] == []

    def test_privilege_evaluation_journal_order_after_surrender(self):
        """PRD §2.8: "Whenever an embedded re-derivation changes the nurse's privilege
        status or scope, a `PrivilegeEvaluation` row is appended with a `trigger_reason`
        of `PSOR_CHANGE`, `LICENSE_CHANGE`, `DISCIPLINE_CHANGE`, or `SWEEP`, capturing
        the `resulting_status`, the sorted `resulting_scope` (the full compact state
        list when the nurse is `ELIGIBLE_MULTISTATE`), and the `home_license_id` chosen
        by the home-license selector — null when no home license is eligible."
        PRD §2.3: "Rows are always returned in creation order — `created_at`
        ascending — and rows that share a single clock instant keep their insertion
        sequence."

        Design: Difficulty/cross_entity_state_dependency/privilege_gated_on_home_license_state
        """
        nurse, lic = self._setup_hana_surrendered()
        observed = get_nurse(nurse["id"])
        validate_success(
            api_client.create_privilege_evaluation(
                {"nurse_id": nurse["id"],
                 "expected_nurse_version": observed["version"]},
                SPEC1,
            ),
            201,
        )

        evals = list_privilege_evals(nurse["id"])
        assert len(evals) == 3
        assert (evals[0]["trigger_reason"], evals[0]["resulting_status"]) == (
            "LICENSE_CHANGE", "ELIGIBLE_MULTISTATE",
        ), "attest appended the first row"
        assert (evals[1]["trigger_reason"], evals[1]["resulting_status"]) == (
            "LICENSE_CHANGE", "NONE",
        ), "the surrender cascade appended the second row"
        assert (evals[2]["trigger_reason"], evals[2]["resulting_status"]) == (
            "MANUAL", "NONE",
        ), "the explicit evaluation always appends its row"
        assert evals[0]["home_license_id"] == lic["id"]
        assert evals[2]["home_license_id"] is None
