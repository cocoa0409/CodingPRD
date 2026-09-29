"""Two workflows in this laboratory do not walk a straight line.

An order can be parked for an unapproved indication, revised back into draft and
submitted again, and a study carries two state dimensions — clinical progress
and chain of custody — that advance independently while sharing one version.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ORDER_STATE_INVALID
from test_helpers.assertions import assert_page, assert_version_is
from test_helpers.test_users import LAB_MANAGER


def _order_requesting_an_unapproved_modality(api):
    """A dyspnoea order that also asks for plethysmography, which is unapproved."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    physician = fx.register_ordering_physician(api)
    physician_headers = fx.make_ordering_physician_headers(physician["id"])
    patient = fx.register_patient(api)
    order = fx.draft_order(
        api,
        patient["id"],
        physician_headers,
        requested_modalities=["SPIROMETRY", "PLETHYSMOGRAPHY"],
    )
    return physician_headers, order


class TestOrderRevisionCycle:
    """DRAFT is visited twice and the second visit lands somewhere else."""

    def test_a_rejected_indication_is_revised_back_to_draft_and_then_clears(self, api):
        """The parked order returns to DRAFT and its second submission is READY.

        PRD 3.4: "An order sitting in `INDICATION_REJECTED` is revised through
        the same update operation the draft used, and applying a revision
        returns it to `DRAFT` and clears `rejection_reason` to null."

        Design: Difficulty/non_linear_state_machine/order_indication_rejection_revision_cycle_returns_to_draft
        """
        physician_headers, order = _order_requesting_an_unapproved_modality(api)

        parked = validate_success(
            api.submit_test_order(order["id"], physician_headers, {}), expected_status=200
        )
        assert parked["status"] == "INDICATION_REJECTED"
        assert parked["rejection_reason"] == "MODALITY_NOT_APPROVED_FOR_INDICATION"
        assert_version_is(parked, 2)

        revised = validate_success(
            api.patch_test_order(
                order["id"], {"requested_modalities": ["SPIROMETRY"]}, physician_headers
            )
        )
        assert revised["status"] == "DRAFT"
        assert revised["rejection_reason"] is None
        assert revised["requested_modalities"] == ["SPIROMETRY"]
        assert_version_is(revised, 3)

        cleared = validate_success(
            api.submit_test_order(order["id"], physician_headers, {}), expected_status=200
        )
        assert cleared["status"] == "READY"
        assert_version_is(cleared, 4)

    def test_the_cycle_is_left_for_good_and_a_third_submission_is_refused(self, api):
        """Once READY the order cannot be submitted again.

        PRD 2.9 rung 23: "**Order state admits the operation** —
        `ERR_ORDER_STATE_INVALID` (409). Submission requires `DRAFT` or
        `INDICATION_REJECTED`"

        Design: Difficulty/non_linear_state_machine/order_indication_rejection_revision_cycle_returns_to_draft
        """
        physician_headers, order = _order_requesting_an_unapproved_modality(api)
        fx.submit_order(api, order["id"], physician_headers)
        validate_success(
            api.patch_test_order(
                order["id"], {"requested_modalities": ["SPIROMETRY"]}, physician_headers
            )
        )
        fx.submit_order(api, order["id"], physician_headers)

        validate_error(
            api.submit_test_order(order["id"], physician_headers, {}),
            ERR_ORDER_STATE_INVALID,
        )

        unchanged = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert unchanged["status"] == "READY"
        assert_version_is(unchanged, 4)


def _occupational_study_scheduled(api):
    """An occupational surveillance study, so its custody dimension is live."""
    lab = fx.build_lab(api)
    session = fx.build_scheduled_session(
        api,
        lab,
        indication_code="OCCUPATIONAL_SURVEILLANCE_ANNUAL",
        test_context="OCCUPATIONAL_SURVEILLANCE",
    )
    return lab, session


class TestParallelCustodyDimension:
    """Custody activity and clinical progress never move each other."""

    def test_each_write_advances_exactly_one_of_the_two_dimensions(self, api):
        """Identity, sealing, effort collection and acceptance interleave cleanly.

        PRD 3.8: "`session_status` is untouched by custody activity, and
        `custody_status` is untouched by maneuvers, quality finalization and
        reporting, yet both share one optimistic-concurrency counter."

        Design: Difficulty/non_linear_state_machine/session_custody_dimension_advances_independently_of_session_status
        """
        lab, session = _occupational_study_scheduled(api)
        assert session["session_status"] == "SCHEDULED"
        assert session["custody_status"] == "CUSTODY_OPEN"
        assert_version_is(session, 1)

        fx.verify_identity(api, session["id"], lab.tech1, "EMPLOYEE_BADGE")
        after_identity = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert after_identity["custody_status"] == "CUSTODY_ID_VERIFIED"
        assert after_identity["session_status"] == "SCHEDULED"

        first_effort = f.STANDARD_MANEUVER_SERIES[0]
        fx.append_maneuver(api, session["id"], first_effort, lab.tech1)
        after_first_effort = validate_success(
            api.get_test_session(session["id"], LAB_MANAGER)
        )
        assert after_first_effort["session_status"] == "IN_PROGRESS"
        assert after_first_effort["custody_status"] == "CUSTODY_ID_VERIFIED"

        fx.apply_seal(api, session["id"], lab.tech1, "SEAL-9001")
        after_seal = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert after_seal["custody_status"] == "CUSTODY_SEALED"
        assert after_seal["session_status"] == "IN_PROGRESS"

        for effort in f.STANDARD_MANEUVER_SERIES[1:]:
            fx.append_maneuver(api, session["id"], effort, lab.tech1)
        accepted = fx.finalize_quality(api, session["id"], lab.tech1)
        assert accepted["session_status"] == "ACCEPTED"
        assert accepted["custody_status"] == "CUSTODY_SEALED"

        fx.witness_session(api, session["id"], "Observed sealing and identity check.")
        after_witness = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert after_witness["custody_status"] == "CUSTODY_SEALED"
        assert after_witness["session_status"] == "ACCEPTED"

    def test_the_witness_attestation_changes_no_state_but_still_bumps_the_version(self, api):
        """Seven writes over one study leave a single shared counter at eight.

        PRD 3.8: "Every custody event, including a witness attestation that
        changes no state, increments the study's `version`."

        Design: Difficulty/non_linear_state_machine/session_custody_dimension_advances_independently_of_session_status
        """
        lab, session = _occupational_study_scheduled(api)

        fx.verify_identity(api, session["id"], lab.tech1, "EMPLOYEE_BADGE")
        fx.append_maneuver(api, session["id"], f.STANDARD_MANEUVER_SERIES[0], lab.tech1)
        fx.apply_seal(api, session["id"], lab.tech1, "SEAL-9001")
        for effort in f.STANDARD_MANEUVER_SERIES[1:]:
            fx.append_maneuver(api, session["id"], effort, lab.tech1)
        fx.finalize_quality(api, session["id"], lab.tech1)
        witness = fx.witness_session(api, session["id"], "Observed sealing and identity check.")

        final = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert_version_is(final, 8)
        assert final["quality_grade"] == "A"
        assert final["acceptable_maneuver_count"] == 3

        chain, meta = validate_paginated(
            api.list_session_custody_events(session["id"], LAB_MANAGER)
        )
        assert_page(meta, total_count=3, has_more=False)
        assert [event["event_type"] for event in chain] == [
            "ID_VERIFIED",
            "SEAL_APPLIED",
            "WITNESS_SIGNED",
        ]
        assert witness["actor_role"] == "ComplianceAuditor"
        assert [event["actor_role"] for event in chain[:2]] == [
            "Technologist",
            "Technologist",
        ]
