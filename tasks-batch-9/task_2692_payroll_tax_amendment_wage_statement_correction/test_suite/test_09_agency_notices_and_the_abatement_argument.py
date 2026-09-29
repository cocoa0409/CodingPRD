"""Agency notices: the correspondence dimension, the waiver tiers and the sweep.

The notice is the only two-dimension entity besides the case, and its waiver
computation is the one place where a fixed-point cut matters: the tier is chosen
from the pre-waiver gross and the de-minimis sweep then runs exactly once, on one
branch only. This file pins that, the FIRST_TIME ceiling, the way a granted waiver
floors the case exposure at zero, and the three refusals around the correspondence.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CORRECTION_CASE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOTICE_RESPONSE_OVERDUE,
)
from test_helpers.assertions import (
    assert_case_rollups,
    assert_notice_dimensions,
    assert_pagination,
)
from test_helpers.constants import CANON_CLOCK, UNKNOWN_CASE_ID
from test_helpers.test_users import ADMIN_HEADERS, OFFICER_HEADERS, PREPARER_HEADERS


DE_MINIMIS_NOTICE = {
    "notice_number": "FED-N-1001",
    "assessed_tax_cents": 0,
    "assessed_penalty_cents": 3000,
    "assessed_interest_cents": 200,
    "response_due_date": "2026-06-30",
}


def _waiver(notice, pct_bps, penalty, interest, net):
    assert notice["waiver_pct_bps"] == pct_bps, notice
    assert notice["waived_penalty_cents"] == penalty, notice
    assert notice["waived_interest_cents"] == interest, notice
    assert notice["net_exposure_cents"] == net, notice


def _granted_count(api, employer_id):
    return validate_success(api.get_employer(employer_id, ADMIN_HEADERS))[
        "granted_abatement_count"
    ]


class TestDeMinimisSweep:
    def test_the_tier_is_read_off_the_pre_waiver_gross_and_the_sweep_clears_the_residue(
        self, api
    ):
        """The tier is chosen from the gross of 3200 cents, the percentage waives the 3000-cent
        penalty, and the 200 cents of interest that `FIRST_TIME` grounds never waive on their
        own are swept away in a single pass because 200 is inside the de-minimis band.

        PRD: "**Step one** forms the pre-waiver gross exposure as `assessed_tax_cents` plus `assessed_penalty_cents` plus `assessed_interest_cents`."
        PRD: "`waived_interest_cents` is the full `assessed_interest_cents` when the grounds are `AGENCY_ERROR`, and 0 for every other grounds value."
        PRD: "If the outcome is `ABATED_FULL` and the resulting net exposure is greater than 0 and no greater than 2500 cents, the sweep replaces `waived_penalty_cents` with the whole `assessed_penalty_cents`, replaces `waived_interest_cents` with the whole `assessed_interest_cents`, and recomputes `net_exposure_cents` as the gross exposure reduced by both of those full amounts."

        Design: Difficulty/combinatorial_formula/de_minimis_sweep_runs_once_without_re_tiering_waiver
        """
        ctx = fx.responded_notice(
            api,
            abatement_grounds="FIRST_TIME",
            requested_penalty_waiver_cents=3000,
            **DE_MINIMIS_NOTICE,
        )
        assert _granted_count(api, ctx["employer_id"]) == 0

        decided = validate_success(
            api.record_notice_outcome(
                ctx["notice_id"],
                f.notice_outcome_payload("ABATED_FULL", agency_decision_reference="LTR-2026-0417"),
                OFFICER_HEADERS,
            )
        )

        _waiver(decided, 10000, 3000, 200, 0)
        assert_notice_dimensions(decided, response_status="CLOSED", abatement_status="GRANTED")
        assert decided["abatement_round"] == 1
        assert decided["agency_decision_reference"] == "LTR-2026-0417"
        assert _granted_count(api, ctx["employer_id"]) == 1

    def test_the_same_assessment_partially_abated_keeps_its_residue(self, api):
        """One branch down, the sweep is simply not run: the identical 3200-cent assessment
        with the identical grounds leaves 200 cents of interest standing, which shows the
        sweep is a property of the full-abatement branch and not a re-tiering of the waiver.

        PRD: "On the `ABATED_PARTIAL` branch the sweep is not applied at all, and on the `UPHELD` branch there is nothing to sweep."
        PRD: "`ABATED_PARTIAL` advances `REQUESTED → PARTIALLY_GRANTED` with the waiver capped at the requested amount and the sweep skipped, and also increments the employer's `granted_abatement_count` by 1."
        PRD: "The sweep never re-runs the percentage selection and never re-tiers."

        Design: Difficulty/combinatorial_formula/de_minimis_sweep_runs_once_without_re_tiering_waiver
        """
        ctx = fx.responded_notice(
            api,
            abatement_grounds="FIRST_TIME",
            requested_penalty_waiver_cents=3000,
            **DE_MINIMIS_NOTICE,
        )

        decided = validate_success(
            api.record_notice_outcome(
                ctx["notice_id"], f.notice_outcome_payload("ABATED_PARTIAL"), OFFICER_HEADERS
            )
        )

        _waiver(decided, 10000, 3000, 0, 200)
        assert_notice_dimensions(
            decided, response_status="CLOSED", abatement_status="PARTIALLY_GRANTED"
        )
        assert _granted_count(api, ctx["employer_id"]) == 1

    def test_a_first_ever_abatement_below_the_ceiling_waives_the_whole_penalty(self, api):
        """A gross of 1250000 cents is well under the 5000000-cent ceiling and the employer has
        never been granted one, so the tier is the full 10000 basis points — and the 50000 cents
        of interest survive, leaving a net far above the de-minimis band.

        PRD: "Otherwise: for `FIRST_TIME` grounds, the percentage is 10000 basis points when the employer's `granted_abatement_count` is 0 **and** the gross exposure is no greater than 5000000 cents, and 5000 basis points in every other case."
        PRD: "`ABATED_FULL` advances `REQUESTED → GRANTED` with the de-minimis sweep in force and increments the employer's `granted_abatement_count` by 1."

        Design: Corner/calculations/first_time_abatement_grants_the_full_waiver_below_the_exposure_ceiling
        """
        ctx = fx.responded_notice(
            api, abatement_grounds="FIRST_TIME", requested_penalty_waiver_cents=200000
        )
        assert ctx["notice"]["correction_case_id"] is None
        assert _granted_count(api, ctx["employer_id"]) == 0

        decided = validate_success(
            api.record_notice_outcome(
                ctx["notice_id"],
                f.notice_outcome_payload("ABATED_FULL", agency_decision_reference="LTR-4021"),
                OFFICER_HEADERS,
            )
        )

        _waiver(decided, 10000, 200000, 0, 1050000)
        assert_notice_dimensions(decided, response_status="CLOSED", abatement_status="GRANTED")
        assert decided["abatement_round"] == 1
        assert _granted_count(api, ctx["employer_id"]) == 1


class TestWaiverAgainstCaseExposure:
    def test_a_granted_waiver_larger_than_the_amendment_gross_floors_the_case_at_zero(self, api):
        """The case has booked 357500 cents of amendment exposure and the agency then waives
        400000; the difference is negative, so both the case and the employer read zero rather
        than a credit, while the amendment itself keeps the penalty it was signed on.

        PRD: "A case's `total_exposure_cents` is computed by first summing, over every amended return on the case whose `status` is `PREPARED`, `SIGNED`, `SUBMITTED` or `ACCEPTED`, that return's `tax_delta_cents` plus `interest_cents` plus `penalty_cents`; then summing, over every agency notice on the case whose `abatement_status` is `GRANTED` or `PARTIALLY_GRANTED`, that notice's `waived_penalty_cents` plus `waived_interest_cents`; and then taking the larger of zero and the first sum reduced by the second."
        PRD: "Both sums are order-insensitive, so no tie-break arises, and the result is floored at zero so that waivers exceeding the summed amendment exposure can never produce a negative figure."

        Design: Corner/calculations/case_exposure_floors_at_zero_when_the_granted_waiver_exceeds_the_gross
        """
        ctx = fx.federal_categorized(api)
        notice = fx.notice_scenario(
            api,
            employer_id=ctx["employer_id"],
            agency_id=ctx["agency_id"],
            correction_case_id=ctx["case_id"],
            assessed_tax_cents=0,
            assessed_penalty_cents=400000,
            assessed_interest_cents=0,
        )["notice"]
        amendment = fx.open_amendment(api, ctx["case_id"])
        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )
        assert prepared["penalty_cents"] == 87500
        assert prepared["voluntary_reduction_applied"] is False
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=357500)

        validate_success(
            api.draft_notice_response(
                notice["id"],
                f.draft_response_payload(
                    abatement_grounds="FIRST_TIME", requested_penalty_waiver_cents=400000
                ),
                OFFICER_HEADERS,
            )
        )
        validate_success(api.respond_to_notice(notice["id"], {}, OFFICER_HEADERS))
        decided = validate_success(
            api.record_notice_outcome(
                notice["id"], f.notice_outcome_payload("ABATED_FULL"), OFFICER_HEADERS
            )
        )

        _waiver(decided, 10000, 400000, 0, 0)
        assert_notice_dimensions(decided, abatement_status="GRANTED")
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=0)
        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_exposure_cents"] == 0
        frozen = validate_success(api.get_amended_return(amendment["id"], PREPARER_HEADERS))
        assert frozen["penalty_cents"] == 87500

    def test_a_request_for_exactly_the_assessed_penalty_is_admitted(self, api):
        """The rule is `may not exceed`, so equality is on the admitted side: the draft is
        accepted and it opens the abatement dimension in the same request.

        PRD: "When `requested_penalty_waiver_cents` is supplied it may not exceed `assessed_penalty_cents`."
        PRD: "On success the notice transitions to `RESPONSE_DRAFTED` — from `RECEIVED` on a first pass, from `INFO_REQUESTED` on a supplemental pass — the narrative, grounds and requested waiver are stored (a supplemental pass overwrites the previously drafted `response_narrative`), `abatement_round` is incremented by 1 on every draft including supplemental rounds, and the notice's `version` is incremented by 1."
        PRD: "When `abatement_grounds` was supplied and the abatement dimension is still at `NONE`, that dimension advances `NONE → REQUESTED` in the same request."

        Design: Corner/validations/waiver_request_equal_to_the_assessed_penalty_is_accepted
        """
        ctx = fx.notice_scenario(api)
        assert ctx["notice"]["assessed_penalty_cents"] == 200000
        assert_notice_dimensions(
            ctx["notice"], response_status="RECEIVED", abatement_status="NONE"
        )

        drafted = validate_success(
            api.draft_notice_response(
                ctx["notice_id"],
                f.draft_response_payload(
                    response_narrative="Reasonable cause narrative attached.",
                    abatement_grounds="REASONABLE_CAUSE",
                    requested_penalty_waiver_cents=200000,
                ),
                OFFICER_HEADERS,
            )
        )

        assert_notice_dimensions(
            drafted, response_status="RESPONSE_DRAFTED", abatement_status="REQUESTED"
        )
        assert drafted["requested_penalty_waiver_cents"] == 200000
        assert drafted["abatement_grounds"] == "REASONABLE_CAUSE"
        assert drafted["abatement_round"] == 1
        assert drafted["version"] == ctx["notice"]["version"] + 1


class TestCorrespondenceGuards:
    def test_a_draft_written_in_time_becomes_unusable_once_the_due_date_passes(self, api):
        """The deadline bites when the response is sent, not when it is written, so the notice
        is stranded in `RESPONSE_DRAFTED` with the abatement request intact but unsent.

        PRD: "Transmitting the response is available from `RESPONSE_DRAFTED` and takes no body."
        PRD: "It requires the current logical instant to be on or before `response_due_date`; a later attempt is refused with `ERR_NOTICE_RESPONSE_OVERDUE`."

        Design: Corner/validations/notice_response_sent_after_the_due_date_returns_response_overdue
        """
        ctx = fx.notice_scenario(api, clock=CANON_CLOCK, response_due_date="2026-05-15")
        drafted = validate_success(
            api.draft_notice_response(
                ctx["notice_id"],
                f.draft_response_payload(
                    abatement_grounds="FIRST_TIME", requested_penalty_waiver_cents=200000
                ),
                OFFICER_HEADERS,
            )
        )
        assert_notice_dimensions(
            drafted, response_status="RESPONSE_DRAFTED", abatement_status="REQUESTED"
        )

        fx.set_clock(api, "2026-06-01T00:00:00Z")
        validate_error(
            api.respond_to_notice(ctx["notice_id"], {}, OFFICER_HEADERS),
            ERR_NOTICE_RESPONSE_OVERDUE,
            422,
        )

        stranded = validate_success(api.get_agency_notice(ctx["notice_id"], OFFICER_HEADERS))
        assert_notice_dimensions(
            stranded, response_status="RESPONSE_DRAFTED", abatement_status="REQUESTED"
        )
        assert stranded["responded_at"] is None

    def test_the_agency_cannot_ask_for_more_when_no_abatement_was_ever_argued(self, api):
        """Half the precondition holds — the notice really is in `RESPONDED` — but with the
        abatement dimension still at `NONE` there is no argument to supplement, so the
        transition is refused and both dimensions stay put.

        PRD: "From `RESPONDED`, and only while the abatement dimension sits at `REQUESTED`, the agency's request for further information can be recorded with an optional `info_request_note`; the notice transitions `RESPONDED → INFO_REQUESTED`, `responded_at` is cleared back to null, and `version` is incremented by 1."
        PRD: "Where no abatement was ever requested, the abatement dimension simply stays at `NONE`."

        Design: Corner/state_machines/notice_request_info_without_an_abatement_request_returns_invalid_state
        """
        ctx = fx.responded_notice(
            api, abatement_grounds=None, requested_penalty_waiver_cents=None
        )
        responded = ctx["notice"]
        assert_notice_dimensions(responded, response_status="RESPONDED", abatement_status="NONE")
        assert responded["responded_at"] == "2026-04-30T00:00:00.000Z"

        validate_error(
            api.request_notice_info(
                ctx["notice_id"], f.request_info_payload(), OFFICER_HEADERS
            ),
            ERR_INVALID_STATE,
            409,
        )

        unchanged = validate_success(api.get_agency_notice(ctx["notice_id"], OFFICER_HEADERS))
        assert_notice_dimensions(unchanged, response_status="RESPONDED", abatement_status="NONE")
        assert unchanged["responded_at"] is not None

    def test_the_optional_case_link_is_validated_rather_than_ignored(self, api):
        """Supplied and valid, the link is stored and is what later feeds the case exposure;
        supplied and dangling, it is a body foreign-key 404 rather than a field quietly dropped.

        PRD: "A `correction_case_id` may be supplied to attach the notice to an open case, or omitted to leave it unattached; when supplied, the notice's employer, agency, tax year and quarter must match the case's, or the request is refused with `ERR_SCOPE_MISMATCH`."
        PRD: "Every such reference must name an existing row of the entity it points at, and a dangling reference produces the same 404 code family: an unknown employer reference yields `ERR_EMPLOYER_NOT_FOUND`, an unknown agency reference `ERR_TAX_AGENCY_NOT_FOUND`, an unknown employee reference `ERR_EMPLOYEE_NOT_FOUND`, an unknown case reference `ERR_CORRECTION_CASE_NOT_FOUND`, an unknown predecessor amendment reference `ERR_AMENDED_RETURN_NOT_FOUND`, and an unknown predecessor statement reference `ERR_STATEMENT_NOT_FOUND`."
        PRD: "A new notice starts with `response_status` at `RECEIVED`, `abatement_status` at `NONE`, `abatement_round` at 0, `waiver_pct_bps`, `waived_penalty_cents`, `waived_interest_cents` and `net_exposure_cents` all at 0, and `response_narrative`, `abatement_grounds`, `requested_penalty_waiver_cents`, `responded_at` and `agency_decision_reference` all at null."

        Design: Corner/endpoints/notice_links_to_a_case_and_an_unknown_case_returns_not_found
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_federal_agency(api)
        case = fx.make_correction_case(api, employer["id"], agency["id"])

        attached = validate_success(
            api.create_agency_notice(
                f.agency_notice_payload(
                    employer["id"],
                    agency["id"],
                    notice_number="CP-136-01",
                    correction_case_id=case["id"],
                    assessed_tax_cents=100000,
                    assessed_penalty_cents=20000,
                    assessed_interest_cents=5000,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert attached["correction_case_id"] == case["id"]
        assert_notice_dimensions(attached, response_status="RECEIVED", abatement_status="NONE")
        assert attached["abatement_round"] == 0
        for field in (
            "waiver_pct_bps",
            "waived_penalty_cents",
            "waived_interest_cents",
            "net_exposure_cents",
        ):
            assert attached[field] == 0, field
        for field in (
            "response_narrative",
            "abatement_grounds",
            "requested_penalty_waiver_cents",
            "responded_at",
            "agency_decision_reference",
        ):
            assert attached[field] is None, field

        validate_error(
            api.create_agency_notice(
                f.agency_notice_payload(
                    employer["id"],
                    agency["id"],
                    notice_number="CP-136-02",
                    correction_case_id=UNKNOWN_CASE_ID,
                    assessed_tax_cents=100000,
                    assessed_penalty_cents=20000,
                    assessed_interest_cents=5000,
                ),
                OFFICER_HEADERS,
            ),
            ERR_CORRECTION_CASE_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(
            api.list_agency_notices({"employer_id": employer["id"]}, OFFICER_HEADERS)
        )
        assert_pagination(meta, total_count=1)
