"""Two submission preconditions fail on the same call.

The disclosure was never issued and the prohibited-claims certification has
lapsed on its exact boundary day.  Both are genuine violations, so only the
group ordering decides which identifier comes back.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents


@pytest.fixture()
def lapsed_training_and_undisclosed_file(client):
    """A file that trips the state group and the business-safety group at once."""
    partner = fx.build_active_partner(client)
    ready = fx.build_submission_ready_application(
        client,
        partner,
        student_ref="STU-1001",
        passport_hash="hash-passport-1001",
        acknowledge=False,
    )

    # 2026-08-01 plus the 180-day prohibited-claims validity lands on 2027-01-28,
    # and the boundary day itself is already lapsed.
    fx.set_clock(client, "2027-01-28T00:00:00Z", headers=fx.COMPLIANCE)

    return {
        "partner": partner,
        "agency_id": partner["agency_id"],
        "application_id": ready["application_id"],
    }


class TestSubmitPrecedencePair:
    def test_the_disclosure_state_failure_is_reported_and_the_training_one_is_not(
        self, client, lapsed_training_and_undisclosed_file
    ):
        """State-machine legality is group nine; training currency is group ten.

        "State-machine legality, in this internal order"

        "disclosure-state legality (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); disclosure
        template staleness (`ERR_DISCLOSURE_VERSION_STALE`)"

        "Business-safety gates, in this internal order: vetting cleared
        (`ERR_AGENCY_NOT_CLEARED`); compliance posture
        (`ERR_AGENCY_POSTURE_BLOCKED`); training currency
        (`ERR_TRAINING_LAPSED`)"

        "Lower-numbered groups are evaluated first, and the first failing check
        produces the response; later checks are never reached and never mask an
        earlier one."

        Design: Difficulty/priority_pair_validation_conflict/submit_disclosure_state_outranks_training_lapse
        """
        env = lapsed_training_and_undisclosed_file

        response = client.submit_application(
            env["application_id"], fx.make_agency_owner_headers(env["agency_id"])
        )
        body = validate_error(response, E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)
        assert body["error_id"] != E.ERR_TRAINING_LAPSED

    def test_the_lower_priority_violation_was_genuinely_present(
        self, client, lapsed_training_and_undisclosed_file
    ):
        """The boundary day already lapsed the certification the sweep touched.

        "`expires_on` is `issued_on` advanced by the module's validity period:
        one full year for `PROGRAM_ACCURACY`, half a year — 180 days — for
        `PROHIBITED_CLAIMS`, and one full year for `VISA_INTEGRITY`, where a full
        year is 365 days."

        "A certification is lapsed the moment the current logical-clock date
        reaches `expires_on`, so the boundary day itself is already lapsed; the
        epoch sweep moves such a record from `VALID` to `EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_disclosure_state_outranks_training_lapse
        """
        env = lapsed_training_and_undisclosed_file

        certifications = fx.read_certifications(
            client, env["agency_id"], module_code=C.MODULE_PROHIBITED_CLAIMS
        )
        assert len(certifications) == 1, f"expected one record, got {certifications!r}"
        lapsed = certifications[0]
        assert lapsed["expires_on"] == "2027-01-28"
        assert lapsed["status"] == C.CERT_EXPIRED

        program_accuracy = fx.read_certifications(
            client, env["agency_id"], module_code=C.MODULE_PROGRAM_ACCURACY
        )
        assert program_accuracy[0]["expires_on"] == "2027-08-01"
        assert program_accuracy[0]["status"] == C.CERT_VALID

    def test_the_refused_submission_pins_nothing_and_freezes_nothing(
        self, client, lapsed_training_and_undisclosed_file
    ):
        """None of submission's four side effects may leak from a refusal.

        "It pins `pinned_contract_id` to the sole contract in `ACTIVE` and
        `pinned_schedule_id` to the rate card effective on that date"

        "And it computes and freezes `projected_commission_cents`, the
        provisional forward-looking projection described in §3.6."

        Design: Difficulty/priority_pair_validation_conflict/submit_disclosure_state_outranks_training_lapse
        """
        env = lapsed_training_and_undisclosed_file

        client.submit_application(
            env["application_id"], fx.make_agency_owner_headers(env["agency_id"])
        )

        application = fx.read_application(client, env["application_id"])
        assert application["status"] == C.APPLICATION_DRAFT
        assert application["disclosure_state"] == C.DISCLOSURE_NOT_ISSUED
        assert application["pinned_contract_id"] is None
        assert application["pinned_schedule_id"] is None
        assert_cents(
            application["projected_commission_cents"],
            0,
            "projected_commission_cents",
        )
