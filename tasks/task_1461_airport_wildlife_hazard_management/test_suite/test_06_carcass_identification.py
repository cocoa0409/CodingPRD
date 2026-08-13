"""Carcass-record identification lifecycle: branching shape, AMENDED cascade,
and dispute segregation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    setup_confirmed_strike_with_carcass,
    ApiErrorId,
)


class TestCarcassDisputeResolveCycle:
    """COLLECTED -> IDENTIFIED -> DISPUTED -> RESOLVED with parent-strike
    cascade on species change."""

    def test_full_identify_dispute_resolve_cycle_with_cascade(self, api):
        """PRD §3.2: "Identification can happen directly from `COLLECTED` or
        from `PENDING_ID`, and transitions the record to `IDENTIFIED`"
        PRD §3.2: "When the final species differs from the parent strike's
        `species_id`, the parent strike report is cascaded to `AMENDED`
        automatically and its `species_id` is updated to match the new
        finding."
        PRD §3.2: "Resolution moves a `DISPUTED` record to `RESOLVED`, again
        by a senior biologist other than the original identifier; resolution
        supplies a final `species_id_final`, and if that final species differs
        from the parent strike's `species_id`, the parent is again cascaded to
        `AMENDED`"

        Design: Difficulty/non_linear_state_machine/carcass_record_dispute_resolve_cycle_with_cascade
        """
        ctx = setup_confirmed_strike_with_carcass(icao_code="KFFF")
        carcass = ctx["carcass"]
        strike = ctx["strike"]
        sp1, sp2 = ctx["sp1"], ctx["sp2"]

        identified = validate_success(
            api.identify_carcass(
                carcass["id"],
                {"species_id_final": sp2["id"], "identification_method": "DNA"},
                ctx["b1_headers"],
            ),
            200,
        )
        assert identified["identification_status"] == "IDENTIFIED"
        assert identified["species_id_final"] == sp2["id"]
        assert identified["identified_by_biologist_id"] == ctx["b1"]["id"]

        strike_after = validate_success(
            api.get_strike_report(strike["id"], ctx["b1_headers"]), 200,
        )
        assert strike_after["status"] == "AMENDED", (
            f"species change must cascade the strike to AMENDED, got "
            f"{strike_after['status']}"
        )
        assert strike_after["species_id"] == sp2["id"]

        disputed = validate_success(
            api.dispute_carcass(carcass["id"], ctx["b2_headers"]), 200,
        )
        assert disputed["identification_status"] == "DISPUTED"

        resolved = validate_success(
            api.resolve_carcass(
                carcass["id"], {"species_id_final": sp1["id"]}, ctx["b2_headers"],
            ),
            200,
        )
        assert resolved["identification_status"] == "RESOLVED"
        assert resolved["species_id_final"] == sp1["id"]
        assert resolved["version"] == 4, (
            f"create=1, identify=2, dispute=3, resolve=4; got "
            f"{resolved['version']}"
        )

        strike_final = validate_success(
            api.get_strike_report(strike["id"], ctx["b1_headers"]), 200,
        )
        assert strike_final["status"] == "AMENDED"

    def test_identifier_cannot_dispute_own_identification(self, api):
        """PRD §3.2: "A senior biologist other than the one who recorded the
        identification may dispute it, moving the record `IDENTIFIED →
        DISPUTED`."
        PRD §2.9: "Segregation of duties forbids the same individual who
        performed the prior step — the strike reporter, the mitigation
        proposer, the dispersal performer, the carcass identifier — from
        performing the follow-up review, approval, confirm, complete, dispute,
        or resolve action; violations are rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/non_linear_state_machine/carcass_record_dispute_resolve_cycle_with_cascade
        """
        ctx = setup_confirmed_strike_with_carcass(icao_code="KFFG")
        carcass = ctx["carcass"]

        identified = validate_success(
            api.identify_carcass(
                carcass["id"],
                {"species_id_final": ctx["sp2"]["id"],
                 "identification_method": "DNA"},
                ctx["b1_headers"],
            ),
            200,
        )
        assert identified["identification_status"] == "IDENTIFIED"

        # B1 recorded the identification; B1 may not dispute it.
        res = api.dispute_carcass(carcass["id"], ctx["b1_headers"])
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)
