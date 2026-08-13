"""Post-installation effectiveness verdicts and the removal process
(PRD §3.8)."""
import pytest

from test_helpers import (
    TE,
    ApiErrorId,
    api_client,
    make_resident_headers,
    commission_study,
    get_request,
    make_city_engineer_headers,
    record_observation,
    set_clock,
    setup_effectiveness_certified,
    setup_installed,
    validate_error,
    validate_success,
)


class TestEffectivenessVerdicts:
    def test_variants_diverge_p85_passes_mean_fails(self):
        """PRD §3.8: "Two verdicts are recorded side by side: the official `meets_effectiveness_target`, which is true exactly when `p85_reduction_mph` is at least 3.0 mph, and the advisory `meets_target_mean_variant`, which is true exactly when `mean_reduction_mph` is at least 2.0 mph. The two are computed independently — identical observations can pass one variant while failing the other"
        PRD §3.8: "The new study, commissioned with a `study_type` of `POST_INSTALLATION`, snapshots `baseline_p85_mph` and `baseline_mean_speed_mph` from the request's certified `INITIAL` study at creation"

        Design: Corner/calculations/effectiveness_variants_diverge_p85_passes_mean_fails
        """
        ctx = setup_installed(
            name="Eff Ave", resident_prefix="eff", crew_ref="CREW-1",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
            scheduled_date="2026-08-15",
        )
        # installed at 2026-08-15; the 30-day settling period ends 2026-09-14.
        set_clock("2026-09-14T00:00:00Z")
        study2 = commission_study(
            ctx["request"]["id"], "POST_INSTALLATION",
            "2026-09-14", "2026-09-16",
        )
        assert study2["baseline_p85_mph"] == pytest.approx(40.0, abs=1e-6), (
            f"baseline must snapshot the certified initial p85, "
            f"got {study2['baseline_p85_mph']}"
        )
        for date in ("2026-09-14", "2026-09-15", "2026-09-16"):
            record_observation(
                study2["id"], date, vehicle_count=2800,
                p85_speed_mph=36.5, mean_speed_mph=31.5,
            )
        api_client.analyze_study(study2["id"], TE)
        certified = validate_success(
            api_client.certify_study(study2["id"], TE),
            200,
        )
        assert certified["p85_reduction_mph"] == pytest.approx(3.5, abs=1e-6)
        assert certified["meets_effectiveness_target"] is True, (
            "official verdict: 3.5 >= 3.0 must pass"
        )
        assert certified["mean_reduction_mph"] == pytest.approx(1.5, abs=1e-6)
        assert certified["meets_target_mean_variant"] is False, (
            "advisory variant: 1.5 < 2.0 must fail on the same data"
        )
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "EFFECTIVENESS_CERTIFIED"


class TestRemovalProcess:
    def _setup_certified(self):
        return setup_effectiveness_certified(
            name="Rem Ave", resident_prefix="rem", crew_ref="CREW-3",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
            scheduled_date="2026-08-15",
            post_window=("2026-09-20", "2026-09-22"),
            post_clock="2026-09-20T00:00:00Z",
        )

    def test_removal_before_min_age_rejected(self):
        """PRD §3.8: "the logical clock must have reached or passed the instant exactly three hundred sixty-five days after `installed_at`, so a younger installation fails with `ERR_REMOVAL_MIN_AGE_NOT_MET`."

        Design: Corner/validations/removal_before_min_age_rejected
        """
        ctx = self._setup_certified()
        # installed_at 2026-08-15 + 365 days = 2027-08-15; now is day +200.
        set_clock("2027-03-03T00:00:00Z")
        resp = api_client.create_removal_request(
            ctx["request"]["id"],
            {"reason": "Too noisy"},
            make_resident_headers(
                ctx["residents"][0]["id"]
            ),
        )
        validate_error(resp, ApiErrorId.ERR_REMOVAL_MIN_AGE_NOT_MET)
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "EFFECTIVENESS_CERTIFIED", (
            f"the rejected filing must not move the request, "
            f"got {req['status']}"
        )

    def test_removal_approval_removes_request_and_locks_decision(self):
        """PRD §3.8: "Granting it requires the removal request to be `PENDING_REVIEW` — otherwise `ERR_REMOVAL_INVALID_STATE` — stamps `decided_by_user_id` with the decider's `X-User-ID`, moves the removal request to `REMOVAL_GRANTED`, and ends the traffic calming request's lifecycle at `REMOVED`."
        PRD §3.8: "the logical clock must have reached or passed the instant exactly three hundred sixty-five days after `installed_at`, so a younger installation fails with `ERR_REMOVAL_MIN_AGE_NOT_MET`."

        Design: Corner/state_machines/removal_approval_removes_request_and_locks_decision
        """
        ctx = setup_effectiveness_certified(
            name="Grant Ave", resident_prefix="grt", crew_ref="CREW-8",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
            scheduled_date="2026-08-15",
            post_window=("2026-09-20", "2026-09-22"),
            post_clock="2026-09-20T00:00:00Z",
        )
        # Filing at exactly installed_at + 365 days succeeds (inclusive boundary).
        set_clock("2027-08-15T00:00:00Z")
        removal = validate_success(
            api_client.create_removal_request(
                ctx["request"]["id"],
                {"reason": "Residents want it gone"},
                make_resident_headers(ctx["residents"][0]["id"]),
            ),
            201,
        )
        assert removal["status"] == "PENDING_REVIEW"

        decided = validate_success(
            api_client.approve_removal(
                removal["id"], make_city_engineer_headers("ce-9")
            ),
            200,
        )
        assert decided["status"] == "REMOVAL_GRANTED"
        assert decided["decided_by_user_id"] == "ce-9"
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "REMOVED", (
            f"approval must end the request at REMOVED, got {req['status']}"
        )

        # The decided removal is terminal: a second decision is rejected.
        again = api_client.approve_removal(
            removal["id"], make_city_engineer_headers("ce-9")
        )
        validate_error(again, ApiErrorId.ERR_REMOVAL_INVALID_STATE)
