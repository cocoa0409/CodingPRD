"""The transition record is an audit stamp, not a mutable resource.

A convenience termination with no successor moves the draft file in-house and
writes one transition row.  That row carries the whole handover story and none of
the mutation bookkeeping every other resource carries.
"""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_no_version_field
from test_helpers.test_users import COMPLIANCE


@pytest.fixture()
def in_house_transition(client):
    """One draft file whose custody fell in-house when the contract ended."""
    partner = fx.build_active_partner(client, legal_name="Transition Agency")
    application = fx.create_application(
        client,
        partner["agency_id"],
        partner["program_id"],
        student_ref="STU-001",
    )
    fx.terminate_contract(
        client,
        partner["contract_id"],
        C.TERMINATION_CONVENIENCE,
        C.DEFAULT_CLOCK_DATE,
        "Agency exited the market",
    )
    return {
        "agency_id": partner["agency_id"],
        "contract_id": partner["contract_id"],
        "application_id": application["id"],
    }


class TestFileTransitionImmutability:
    def test_the_single_transition_row_records_the_whole_handover(
        self, client, in_house_transition
    ):
        """One row per moved file, with in-house custody spelled as null.

        "Each file-transition record captures the `application_id`, the
        `from_agency_id` that held custody before the move, the `to_agency_id`
        that holds it after — null for in-house — the `trigger_contract_id` of the
        terminated contract whose cascade produced it, a `reason_code` of
        `TERMINATION_FOR_CAUSE`, `TERMINATION_CONVENIENCE` or
        `TERMINATION_NON_RENEWAL` mirroring the termination reason, the
        `application_status_at_transition` observed at the moment of the move, and
        `disclosure_reset`, which is always true"

        Design: Corner/entities/file_transition_is_immutable_and_has_no_version_field
        """
        env = in_house_transition

        rows, meta = validate_paginated(
            client.list_file_transitions(
                COMPLIANCE, {"application_id": env["application_id"]}
            )
        )
        assert meta["total_count"] == 1
        row = rows[0]

        assert row["application_id"] == env["application_id"]
        assert row["from_agency_id"] == env["agency_id"]
        assert row["to_agency_id"] is None
        assert row["trigger_contract_id"] == env["contract_id"]
        assert row["reason_code"] == C.TRANSITION_REASON_TERMINATION_CONVENIENCE
        assert row["application_status_at_transition"] == C.APPLICATION_DRAFT
        assert row["disclosure_reset"] is True

    def test_the_audit_row_carries_no_version_and_no_update_stamp(
        self, client, in_house_transition
    ):
        """It is the one resource in the domain without mutation bookkeeping.

        "`FileTransition` is the sole exception. A file-transition record is an
        immutable audit stamp written by a cascade and never edited afterwards, so
        it exposes only `id` and `created_at`: it has neither an `updated_at` field
        nor a `version` field."

        Design: Corner/entities/file_transition_is_immutable_and_has_no_version_field
        """
        env = in_house_transition
        rows = fx.read_transitions(client, application_id=env["application_id"])
        transition_id = rows[0]["id"]

        fetched = validate_success(
            client.get_file_transition(transition_id, COMPLIANCE)
        )
        assert fetched["id"] == transition_id
        assert_no_version_field(fetched)

    def test_the_moved_file_is_held_in_house_with_its_disclosure_reset(
        self, client, in_house_transition
    ):
        """Custody becomes null and the disclosure dimension is invalidated.

        "Every application whose `custody_agency_id` is the terminated contract's
        agency and whose `status` is `DRAFT`, `SUBMITTED`, `ADMITTED` or
        `DEPOSIT_PAID` has its `custody_agency_id` reassigned to
        `successor_agency_id`, or to null when the field was omitted, has its
        `disclosure_state` driven to `INVALIDATED`, and gets one file-transition
        record appended."

        Design: Corner/entities/file_transition_is_immutable_and_has_no_version_field
        """
        env = in_house_transition

        application = fx.read_application(client, env["application_id"])
        assert application["custody_agency_id"] is None
        assert application["disclosure_state"] == C.DISCLOSURE_INVALIDATED
        assert application["agency_id"] == env["agency_id"], (
            "the recruiting agency of record is immutable"
        )
