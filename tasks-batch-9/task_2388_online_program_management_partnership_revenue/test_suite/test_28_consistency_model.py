"""Consistency model: every derived total is settled by the time the causing call returns."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    factories,
    fixtures,
    make_bursar_headers,
)


class TestImmediateConsistency:
    def test_one_payment_settles_the_enrollment_the_program_and_the_partnership_at_once(self, api):
        """No settling delay: the reads taken straight after the posting are already reconciled.

        PRD: "Each posting recomputes the enrollment's `collected_cents` and `refunded_cents` and the
        partnership's `collected_tuition_cents`, per the conservation rule of §2.7. The very first
        `PAYMENT` entry has a further effect: it takes the enrollment `ENROLLED → ACTIVE`, because a
        student who has paid something is academically live. That transition is a system event rather
        than a client action, and it fires exactly when the enrollment is `ENROLLED` and
        `collected_cents` is greater than zero after the posting."
        PRD: "`active_enrollment_count` counts its enrollments in `ENROLLED` or `ACTIVE`"

        Design: Corner/consistency_model/ledger_updates_are_visible_in_the_same_response_that_causes_them
        """
        context = fixtures.build_launched_program(api)
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]
        lead = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)
        enrollment = fixtures.enroll_lead(api, lead["id"])
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["tuition_charged_cents"] == 562500
        assert fixtures.read_partnership(api, ps_id)["collected_tuition_cents"] == 0

        fixtures.set_clock(api, fixtures.CLOCK_SEP_5)
        entry = validate_success(
            api.create_tuition_payment(
                enrollment["id"],
                factories.tuition_payment_payload(),
                headers=make_bursar_headers(),
            ),
            201,
        )
        assert entry["amount_cents"] == 562500

        stored = fixtures.read_enrollment(api, enrollment["id"])
        assert stored["collected_cents"] == 562500
        assert stored["refunded_cents"] == 0
        assert stored["status"] == "ACTIVE"

        assert fixtures.read_partnership(api, ps_id)["collected_tuition_cents"] == 562500
        assert fixtures.read_program(api, pg_id)["active_enrollment_count"] == 1
