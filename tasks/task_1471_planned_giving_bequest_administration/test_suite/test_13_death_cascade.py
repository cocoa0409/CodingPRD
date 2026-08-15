"""The donor-death maturity cascade: a single record-death call ripples
through agreements, payments, the reserve fund, and estate auto-creation."""
from test_helpers import (
    list_payments,
    make_active_rate_table,
    make_donor,
    make_draft_agreement,
    make_estate_manager_headers,
    make_funded_cga_with_reserve,
    make_verified_designation,
    validate_paginated,
    validate_success,
    withdraw_reserve,
)

EM1 = make_estate_manager_headers("em-1")


def _death_cascade_scenario(api, gift_admin_headers):
    """CGA ACTIVE (80 payments @150000, total_scheduled 12000000) with the
    reserve drawn down to RESERVE_DEFICIENT, plus an EXECUTED BEQUEST.
    Returns (donor, cga, bequest, pre_death_posture)."""
    donor = make_donor(full_name="Cascade Donor")
    make_active_rate_table()
    cga = make_funded_cga_with_reserve(donor["id"])
    # PRD §4: "generating a payment schedule — return `201 Created`."
    validate_success(api.generate_payment_schedule(cga["id"], gift_admin_headers), 201)
    # Draw the pool below the booked target: RESERVE_DEFICIENT before death.
    pool = withdraw_reserve(1000000)
    assert pool["posture"] == "RESERVE_DEFICIENT"

    bequest = make_draft_agreement(
        donor["id"], vehicle_type="BEQUEST", gift_amount_cents=5000000
    )
    make_verified_designation(bequest["id"], beneficiary_name="University")
    bequest = validate_success(
        api.execute_gift_agreement(bequest["id"], gift_admin_headers)
    )
    return donor, cga, bequest, pool["posture"]


class TestDonorDeathMaturityCascade:
    def test_death_matures_annuity_agreement_and_lapses_payments(
        self, api, gift_admin_headers, estate_manager_headers
    ):
        """PRD §3.1: "**Hop 1:** for each of the donor's gift agreements,
        processed in `created_at` ascending order, if the agreement's status is
        `EXECUTED`, `FUNDED`, `ACTIVE`, or `SUSPENDED` and its `vehicle_type`
        is `CGA`, `CRT_ANNUITY`, or `CRT_UNITRUST`, the agreement becomes
        `MATURED`."
        PRD §3.1: "**Hop 2:** for each agreement matured in hop 1, every linked
        annuity payment in `SCHEDULED`, `DUE`, or `DEFERRED` status becomes
        `LAPSED` with `lapse_reason` set to `DONOR_DEATH`, and the agreement's
        `liability_released_cents` and payment-total derived fields are
        recomputed."

        Design: Difficulty/transitive_cascade/donor_death_maturity_cascade
        """
        donor, cga, _bequest, pre_posture = _death_cascade_scenario(
            api, gift_admin_headers
        )
        assert pre_posture == "RESERVE_DEFICIENT"

        deceased = validate_success(
            api.record_death(donor["id"], {"deceased_on": "2026-09-15T00:00:00Z"}, EM1)
        )
        assert deceased["vital_status"] == "DECEASED"
        assert deceased["deceased_on"].startswith("2026-09-15")

        matured = validate_success(api.get_gift_agreement(cga["id"], estate_manager_headers))
        assert matured["status"] == "MATURED"
        # All 80 SCHEDULED payments lapse; released mass equals the schedule.
        assert matured["liability_released_cents"] == 12000000
        assert matured["total_scheduled_cents"] == 12000000

        lapsed, meta = list_payments(cga["id"], status="LAPSED")
        assert meta["total_count"] == 80
        for payment in lapsed:
            assert payment["lapse_reason"] == "DONOR_DEATH"

    def test_death_flips_reserve_solvent_and_creates_bequest_estate(
        self, api, gift_admin_headers, estate_manager_headers
    ):
        """PRD §3.1: "**Hop 3:** the reserve fund's `booked_target_cents` is
        recomputed, because `MATURED` CGA agreements leave the
        `FUNDED`/`ACTIVE`/`SUSPENDED` inclusion set."
        PRD §3.1: "**Hop 4:** `booked_coverage_bps` and `posture` are
        recomputed from the new target; the posture may flip from
        `RESERVE_DEFICIENT` back to `SOLVENT`."
        PRD §3.1: "**Hop 1b:** if a matured agreement's `vehicle_type` is
        `BEQUEST` and its status was `EXECUTED` or `FUNDED`, it becomes
        `MATURED` and a new `Estate` is auto-created for the donor, linked to
        that agreement, starting in `NOTIFIED` status with `notified_on` set to
        the supplied `deceased_on` and `recorded_by_user_id` set to the acting
        `EstateManager`."

        Design: Difficulty/transitive_cascade/donor_death_maturity_cascade
        """
        donor, cga, bequest, pre_posture = _death_cascade_scenario(
            api, gift_admin_headers
        )
        assert pre_posture == "RESERVE_DEFICIENT"

        validate_success(
            api.record_death(donor["id"], {"deceased_on": "2026-09-15T00:00:00Z"}, EM1)
        )

        pool = validate_success(api.get_reserve_fund(estate_manager_headers))
        # The matured CGA left the booked set: target zeroed, posture flips.
        assert pool["booked_target_cents"] == 0
        assert pool["booked_coverage_bps"] is None
        assert pool["posture"] == "SOLVENT"

        matured_bequest = validate_success(
            api.get_gift_agreement(bequest["id"], estate_manager_headers)
        )
        assert matured_bequest["status"] == "MATURED"

        estates, meta = validate_paginated(
            api.list_estates(estate_manager_headers, params={"gift_agreement_id": bequest["id"]})
        )
        assert meta["total_count"] == 1
        estate = estates[0]
        assert estate["status"] == "NOTIFIED"
        assert estate["donor_id"] == donor["id"]
        assert estate["recorded_by_user_id"] == "em-1"
        assert estate["notified_on"].startswith("2026-09-15")
