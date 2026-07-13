"""Launch-ramp passes: seasonal fee by residency, and the closed-interval
same-boater seasonal overlap rule (adjacency counts as overlap)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_marina,
    create_boater,
    create_vessel,
    create_ramp_pass_payload,
)

HARBOR = TEST_USERS["harbormaster_headers"]


class TestRampPassFee:
    def test_seasonal_nonresident_fee_is_20000(self, api):
        """PRD §3.9: "The pass copies the boater's residency into `fee_basis` and
        computes `fee_cents` from the pass type and residency: a seasonal pass
        costs 8,000 cents for a resident and 20,000 cents for a non-resident, while
        a day pass costs 1,000 cents for a resident and 3,000 cents for a
        non-resident."

        Design: Corner/calculations/ramp_pass_fee_seasonal_nonresident_correct
        """
        set_clock(api, "2026-04-01T00:00:00Z")
        create_marina(api)
        boater = create_boater(api, full_name="RampNon N", email="rn@example.com",
                               residency_status="NON_RESIDENT")
        vessel = create_vessel(api, boater["id"], length_ft=18)
        data = validate_success(
            api.create_ramp_pass(
                create_ramp_pass_payload(
                    boater["id"], vessel["id"], pass_type="SEASONAL",
                    valid_from_date="2026-05-01", valid_to_date="2026-10-31",
                ),
                HARBOR,
            ),
            expected_status=201,
        )
        assert data["fee_cents"] == 20000
        assert data["fee_basis"] == "NON_RESIDENT"


class TestRampPassOverlap:
    def _first_pass(self, api):
        set_clock(api, "2026-04-01T00:00:00Z")
        create_marina(api)
        boater = create_boater(api, full_name="Ramp R", email="ramp@example.com")
        vessel = create_vessel(api, boater["id"], length_ft=20)
        pass1 = validate_success(
            api.create_ramp_pass(
                create_ramp_pass_payload(
                    boater["id"], vessel["id"], pass_type="SEASONAL",
                    valid_from_date="2026-05-01", valid_to_date="2026-08-31",
                ),
                HARBOR,
            ),
            expected_status=201,
        )
        return boater, vessel, pass1

    def test_adjacent_seasonal_pass_rejected_as_overlap(self, api):
        """PRD §3.9: "A boater may not hold two overlapping seasonal ramp passes:
        for the same boater, two seasonal passes whose closed
        `valid_from_date`-through-`valid_to_date` intervals overlap — with mere
        adjacency counting as an overlap — are rejected with `ERR_RAMP_PASS_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/ramp_pass_overlap_closed_interval_same_boater
        """
        boater, vessel, _ = self._first_pass(api)
        validate_error(
            api.create_ramp_pass(
                create_ramp_pass_payload(
                    boater["id"], vessel["id"], pass_type="SEASONAL",
                    valid_from_date="2026-08-31", valid_to_date="2026-10-31",
                ),
                HARBOR,
            ),
            ApiErrorId.ERR_RAMP_PASS_OVERLAP,
        )

    def test_first_pass_stays_active_after_rejected_overlap(self, api):
        """PRD §3.9: "A `RAMP_PASS` invoice is issued `UNPAID` and its identifier
        stored in the pass's `invoice_id`; the pass begins `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/ramp_pass_overlap_closed_interval_same_boater
        """
        boater, vessel, pass1 = self._first_pass(api)
        api.create_ramp_pass(
            create_ramp_pass_payload(
                boater["id"], vessel["id"], pass_type="SEASONAL",
                valid_from_date="2026-08-31", valid_to_date="2026-10-31",
            ),
            HARBOR,
        )
        assert get_success_data(api.get_ramp_pass(pass1["id"], HARBOR))["status"] == "ACTIVE"
