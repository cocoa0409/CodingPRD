"""Volunteer testing and activation: the inclusive pass threshold, the
activation cycle, supersession and its demotion cascade, and the
optimistic-concurrency guard on certification recording."""
from test_helpers import (
    ApiErrorId,
    add_preparer,
    assert_certification,
    assert_volunteer,
    get_volunteer,
    record_certification,
    register_volunteer,
    setup_certified_site,
    setup_open_site,
    transition_volunteer,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_certification_payload


class TestCertificationPassThreshold:
    def test_score_79_fails(self, api):
        """PRD §3.2: "A score of at least 80 passes: the attempt's computed
        `passed` flag is true exactly when the score is 80 or higher."

        Design: Difficulty/boundary_precision_check/certification_pass_threshold_79_vs_80
        """
        ctx = setup_certified_site()
        trainee = register_volunteer(
            ctx.site_id, ctx.coord_headers, full_name="Trainee Tim", email="tim@x.org"
        )
        cert = record_certification(
            trainee["id"], ctx.coord_headers, test_type="BASIC", score=79
        )
        assert_certification(cert)
        assert cert["score"] == 79
        assert cert["passed"] is False, "79 is one below the inclusive threshold"

    def test_score_80_passes(self, api):
        """PRD §3.2: "A score of at least 80 passes: the attempt's computed
        `passed` flag is true exactly when the score is 80 or higher."

        Design: Difficulty/boundary_precision_check/certification_pass_threshold_79_vs_80
        """
        ctx = setup_certified_site()
        trainee = register_volunteer(
            ctx.site_id, ctx.coord_headers, full_name="Trainee Tim", email="tim@x.org"
        )
        cert = record_certification(
            trainee["id"], ctx.coord_headers, test_type="ADVANCED", score=80
        )
        assert_certification(cert)
        assert cert["score"] == 80
        assert cert["passed"] is True, "80 hits the inclusive threshold exactly"


class TestVolunteerActivationCycle:
    def test_activation_round_trip(self, api):
        """PRD §3.2: "Activation — from `REGISTERED` to `ACTIVE`, and again
        from `INACTIVE` back to `ACTIVE` — is performed by a `SiteCoordinator`
        or `SponsorAdmin` and requires the volunteer to hold a `CURRENT`,
        passed `ETHICS` certification for season 2026; without one,
        activation is rejected with `ERR_VOLUNTEER_NOT_CERTIFIED`."

        Design: Difficulty/non_linear_state_machine/volunteer_activation_cycle
        """
        ctx = setup_open_site()
        prep = add_preparer(ctx)
        assert prep["status"] == "ACTIVE"

        prep = transition_volunteer(prep["id"], "INACTIVE", ctx.coord_headers)
        assert_volunteer(prep)
        assert prep["status"] == "INACTIVE"

        prep = transition_volunteer(prep["id"], "ACTIVE", ctx.coord_headers)
        assert prep["status"] == "ACTIVE", (
            "the volunteer cycles back to its original state"
        )

    def test_certified_test_types_survive_cycle(self, api):
        """PRD §3.2: "`certified_test_types` lists the test types for which
        the volunteer currently holds a `CURRENT`, passed certification for
        season 2026."

        Design: Difficulty/non_linear_state_machine/volunteer_activation_cycle
        """
        ctx = setup_open_site()
        prep = add_preparer(ctx)
        prep = transition_volunteer(prep["id"], "INACTIVE", ctx.coord_headers)
        prep = transition_volunteer(prep["id"], "ACTIVE", ctx.coord_headers)

        prep = get_volunteer(prep["id"], ctx.coord_headers)
        assert "ETHICS" in prep["certified_test_types"]
        assert "BASIC" in prep["certified_test_types"], (
            "the CURRENT passed certifications still define the computed view "
            "after the ACTIVE -> INACTIVE -> ACTIVE cycle"
        )


class TestFailedEthicsRecertDemotion:
    def _active_preparer(self, ctx):
        """ACTIVE preparer holding CURRENT passed ETHICS (90) and BASIC."""
        return add_preparer(ctx, ethics_score=90, basic_score=88)

    def test_failed_recert_supersedes_prior_attempt(self, api):
        """PRD §3.2: "Each attempt's `attempt_number` is one plus the count
        of earlier attempts recorded for the same volunteer, test type, and
        season. The newest attempt for a given (volunteer, test type, season)
        triple becomes `CURRENT`, and every earlier attempt for that triple
        is moved to `SUPERSEDED`"

        Design: Difficulty/transitive_cascade/failed_ethics_recert_demotes_volunteer
        """
        ctx = setup_open_site()
        prep = self._active_preparer(ctx)
        certs_before = validate_success(
            api.list_certifications(prep["id"], ctx.coord_headers)
        )
        old_ethics = next(c for c in certs_before if c["test_type"] == "ETHICS")

        new_cert = record_certification(
            prep["id"], ctx.coord_headers, test_type="ETHICS", score=40
        )
        assert_certification(new_cert)
        assert new_cert["passed"] is False
        assert new_cert["status"] == "CURRENT"
        assert new_cert["attempt_number"] == old_ethics["attempt_number"] + 1

        certs_after = validate_success(
            api.list_certifications(prep["id"], ctx.coord_headers)
        )
        old_row = next(c for c in certs_after if c["id"] == old_ethics["id"])
        assert old_row["status"] == "SUPERSEDED", (
            "the prior attempt flips to SUPERSEDED when the new attempt lands"
        )

    def test_failed_recert_demotes_volunteer_to_inactive(self, api):
        """PRD §3.2: "Supersession carries a teeth: if the attempt just
        superseded was the volunteer's only `CURRENT` passed `ETHICS`
        certification for season 2026, and the newly recorded attempt did not
        pass, the volunteer immediately and automatically drops from `ACTIVE`
        to `INACTIVE`, triggering the same cancellation cascade as a manual
        inactivation."

        Design: Difficulty/transitive_cascade/failed_ethics_recert_demotes_volunteer
        """
        ctx = setup_open_site()
        prep = self._active_preparer(ctx)
        record_certification(prep["id"], ctx.coord_headers, test_type="ETHICS", score=40)

        prep = get_volunteer(prep["id"], ctx.coord_headers)
        assert prep["status"] == "INACTIVE", (
            "losing the only CURRENT passed ETHICS cert auto-demotes the volunteer"
        )
        assert "ETHICS" not in prep["certified_test_types"]
        assert "BASIC" in prep["certified_test_types"]


class TestCertificationSupersession:
    def test_second_attempt_supersedes_first(self, api):
        """PRD §3.2: "Each attempt's `attempt_number` is one plus the count
        of earlier attempts recorded for the same volunteer, test type, and
        season. The newest attempt for a given (volunteer, test type, season)
        triple becomes `CURRENT`, and every earlier attempt for that triple
        is moved to `SUPERSEDED`"
        PRD §3.2: "Because recording an attempt mutates the volunteer, the
        call is optimistic-concurrency guarded on the volunteer's `version`
        via `expected_volunteer_version` (§2.7), and a successful recording
        increments the volunteer's `version` by one."

        Design: Corner/entities/certification_supersede_marks_prior
        """
        ctx = setup_certified_site()
        trainee = register_volunteer(
            ctx.site_id, ctx.coord_headers, full_name="Trainee Tim", email="tim@x.org"
        )
        v0 = get_volunteer(trainee["id"], ctx.coord_headers)["version"]

        first = record_certification(
            trainee["id"], ctx.coord_headers, test_type="BASIC", score=85
        )
        assert first["attempt_number"] == 1
        assert first["status"] == "CURRENT"
        v1 = get_volunteer(trainee["id"], ctx.coord_headers)["version"]
        assert v1 == v0 + 1, "one recording increments the volunteer version by 1"

        second = record_certification(
            trainee["id"], ctx.coord_headers, test_type="BASIC", score=90
        )
        assert second["attempt_number"] == 2
        assert second["status"] == "CURRENT"
        v2 = get_volunteer(trainee["id"], ctx.coord_headers)["version"]
        assert v2 == v1 + 1

        certs = validate_success(
            api.list_certifications(trainee["id"], ctx.coord_headers)
        )
        first_row = next(c for c in certs if c["id"] == first["id"])
        assert first_row["status"] == "SUPERSEDED"


class TestActivationGate:
    def test_activation_without_ethics_rejected(self, api):
        """PRD §3.2: "Activation — from `REGISTERED` to `ACTIVE`, and again
        from `INACTIVE` back to `ACTIVE` — is performed by a `SiteCoordinator`
        or `SponsorAdmin` and requires the volunteer to hold a `CURRENT`,
        passed `ETHICS` certification for season 2026; without one,
        activation is rejected with `ERR_VOLUNTEER_NOT_CERTIFIED`."

        Design: Corner/validations/activation_without_ethics_rejected
        """
        ctx = setup_certified_site()
        ned = register_volunteer(
            ctx.site_id, ctx.coord_headers, full_name="New Ned", email="ned@x.org"
        )
        resp = api.transition_volunteer(ned["id"], "ACTIVE", ctx.coord_headers)
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_CERTIFIED)
        ned = get_volunteer(ned["id"], ctx.coord_headers)
        assert ned["status"] == "REGISTERED"


class TestCertificationOcc:
    def test_certification_record_stale_volunteer_version(self, api):
        """PRD §2.7: "Recording a certification attempt against a volunteer
        likewise requires `expected_volunteer_version`, holding the `version`
        of the volunteer the client last observed; a mismatch with the
        volunteer's current `version` is rejected with the same
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_certification_stale
        """
        ctx = setup_certified_site()
        trainee = register_volunteer(
            ctx.site_id, ctx.coord_headers, full_name="Trainee Tim", email="tim@x.org"
        )
        stale_version = trainee["version"]
        record_certification(
            trainee["id"], ctx.coord_headers, test_type="ETHICS", score=90
        )

        payload = create_certification_payload(
            stale_version, test_type="BASIC", score=85
        )
        resp = api.record_certification(trainee["id"], payload, ctx.coord_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        certs = validate_success(
            api.list_certifications(trainee["id"], ctx.coord_headers)
        )
        assert len(certs) == 1, (
            "the rejected recording adds no attempt row"
        )
