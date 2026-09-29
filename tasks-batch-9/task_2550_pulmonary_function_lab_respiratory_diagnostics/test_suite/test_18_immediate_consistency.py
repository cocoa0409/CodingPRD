"""Nothing in this laboratory is recomputed lazily.

One study is driven from its first blow to a signed report, and after every write
the very next read is required to agree with the response that write returned —
including the reads of the two records the signature reaches across.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_1dp,
    assert_3dp,
    assert_maneuver_acceptable,
    assert_signed_interpretation,
    assert_unchanged,
)
from test_helpers.test_users import LAB_MANAGER

LATE_MORNING = "2026-08-03T10:00:00Z"
LATE_MORNING_SLOT = ("2026-08-03T11:00:00Z", "2026-08-03T11:30:00Z")

DERIVED_STUDY_FIELDS = (
    "session_status",
    "best_fev1_l",
    "best_fvc_l",
    "fev1_pct_predicted",
    "fvc_pct_predicted",
    "fev1_fvc_ratio",
    "acceptable_maneuver_count",
    "version",
)


class TestDerivedFieldsAreCurrentInTheWritingResponse:
    """Every roll-up is already settled when the write answers."""

    def test_the_study_the_order_and_the_patient_all_read_true_immediately(self, api):
        """No read in the chain lags the write that produced its value.

        PRD 2.8: "Cascades in this API are **immediate and complete**: they are
        applied inside the originating request, before its response is returned,
        and each affected record independently refreshes its own `updated_at` and
        increments its own `version`."

        PRD 3.6: "Every append recomputes the study's aggregate picture from **two
        different pools**, and the difference between them is the crux of the
        calculation."

        PRD 2.8: "Third, when a study becomes `REPORTED`, its order advances from
        `IN_TESTING` to `COMPLETED` and the patient's `completed_order_count` rises
        by one."

        Design: Corner/consistency_model/every_derived_field_is_already_current_in_the_writing_response
        """
        start, end = LATE_MORNING_SLOT
        lab = fx.build_lab(api, clock=LATE_MORNING, interpreters=1)
        order = fx.build_ready_order(api, lab)
        session = fx.build_scheduled_session(
            api,
            lab,
            scheduled_start_at=start,
            scheduled_end_at=end,
            order=order,
        )

        first_effort = fx.append_maneuver(
            api, session["id"], f.STANDARD_MANEUVER_SERIES[0], lab.tech1
        )
        assert first_effort["maneuver_index"] == 1
        assert_maneuver_acceptable(first_effort)

        opened = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert opened["session_status"] == "IN_PROGRESS"
        assert_3dp(opened["best_fev1_l"], 2.400)
        assert_3dp(opened["best_fvc_l"], 3.200)
        assert_1dp(opened["fev1_pct_predicted"], 60.0)
        assert_1dp(opened["fvc_pct_predicted"], 66.7)
        assert_3dp(opened["fev1_fvc_ratio"], 0.750)
        assert opened["acceptable_maneuver_count"] == 1
        assert opened["repeatability_delta_ml"] is None

        reread = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert_unchanged(opened, reread, DERIVED_STUDY_FIELDS)

        for effort in f.STANDARD_MANEUVER_SERIES[1:]:
            fx.append_maneuver(api, session["id"], effort, lab.tech1)

        three_efforts_in = validate_success(
            api.get_test_session(session["id"], LAB_MANAGER)
        )
        assert_3dp(three_efforts_in["best_fev1_l"], 2.400)
        assert_3dp(three_efforts_in["best_fvc_l"], 3.200)
        assert three_efforts_in["acceptable_maneuver_count"] == 3
        assert three_efforts_in["repeatability_delta_ml"] == 150

        accepted = fx.finalize_quality(api, session["id"], lab.tech1)
        assert accepted["session_status"] == "ACCEPTED"
        assert accepted["quality_grade"] == "A"
        assert_unchanged(
            three_efforts_in,
            accepted,
            ("best_fev1_l", "best_fvc_l", "fev1_pct_predicted", "fev1_fvc_ratio"),
        )

        report = fx.assign_report(api, session["id"], accepted["version"])
        assert report["status"] == "ASSIGNED"

        signed = fx.sign_report(api, report["id"], lab.roster.rad1)
        assert_signed_interpretation(signed, "RESTRICTION", "MODERATE", signed_at=LATE_MORNING)

        stored_report = validate_success(
            api.get_interpretation_report(report["id"], LAB_MANAGER)
        )
        assert_unchanged(
            signed, stored_report, ("status", "pattern", "severity", "template_version")
        )

        reported = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert reported["session_status"] == "REPORTED"

        completed = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert completed["status"] == "COMPLETED"

        patient = validate_success(api.get_patient(lab.patient_id, LAB_MANAGER))
        assert patient["completed_order_count"] == 1
