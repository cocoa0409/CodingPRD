"""Credit review: the funding cascade, the facility gate and the return/resubmit cycle."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_four_dp
from test_helpers.test_users import (
    CLERK_HEADERS,
    INSPECTOR_HEADERS,
    make_property_owner_headers,
)


@pytest.fixture
def funded_program():
    """An ACTIVE term with a 25000-cent target and one 29264-cent COMMERCIAL parcel."""
    program = fx.setup_active_program(eru_sqft=3000, funding_target_cents=25000)
    account = fx.create_account(
        program["term_id"],
        parcel_id="P-9020",
        parcel_class="COMMERCIAL",
        impervious_area_sqft=9020,
        owner_name="Harborline Retail LLC",
    )
    return {"term_id": program["term_id"], "account": account}


class TestApprovalCascadesToTheFundingSpine:
    """Approval walks the account, then the term revenue, then the funding flag."""

    def test_01_program_starts_adequately_funded_on_the_uncredited_fee(
        self, funded_program
    ):
        """One 29264-cent parcel already covers the 25000-cent target.

        PRD: "It also raises the term's `projected_annual_revenue_cents` and
        refreshes `funding_adequacy_status`."

        Design: Difficulty/transitive_cascade/credit_approval_cascades_to_underfunded_program_status
        """
        account = funded_program["account"]
        assert_cents(account["gross_billable_cents"], 29264, "gross_billable_cents")
        assert_cents(account["current_net_fee_cents"], 29264, "current_net_fee_cents")
        assert_four_dp(account["total_credit_pct"], 0.0000, "total_credit_pct")

        term = fx.read_term(funded_program["term_id"])
        assert_cents(
            term["projected_annual_revenue_cents"], 29264, "projected_annual_revenue_cents"
        )
        assert term["funding_adequacy_status"] == "ADEQUATE", (
            "29264 cents of projected revenue meets the 25000-cent target"
        )

    def test_02_approving_a_credit_flips_the_program_to_underfunded(self, funded_program):
        """0.2755 approved credits 8062 cents and drops revenue to 21202.

        PRD: "Approval writes `APPROVED` into `status`, stamps `approved_at`,
        stores `approved_credit_pct`, raises the account's `total_credit_pct` and
        lowers its `current_net_fee_cents`, lowers the term's
        `projected_annual_revenue_cents`, and may flip `funding_adequacy_status`
        to `UNDERFUNDED`."

        Design: Difficulty/transitive_cascade/credit_approval_cascades_to_underfunded_program_status
        """
        account = funded_program["account"]
        application = fx.file_credit_application(account, 0.2755, headers=CLERK_HEADERS)
        approved = fx.review_credit_application(
            application["id"], "APPROVE", approved_credit_pct=0.2755
        )

        assert approved["status"] == "APPROVED", "the review approved the application"
        assert_four_dp(approved["approved_credit_pct"], 0.2755, "approved_credit_pct")
        assert approved["approved_at"] is not None, "approval stamps approved_at"

        billed = fx.read_account(account["id"])
        assert_four_dp(billed["total_credit_pct"], 0.2755, "total_credit_pct")
        assert_cents(billed["current_net_fee_cents"], 21202, "current_net_fee_cents")
        assert_cents(billed["gross_billable_cents"], 29264, "gross_billable_cents")

        term = fx.read_term(funded_program["term_id"])
        assert_cents(
            term["projected_annual_revenue_cents"], 21202, "projected_annual_revenue_cents"
        )
        assert term["funding_adequacy_status"] == "UNDERFUNDED", (
            "21202 cents of projected revenue falls below the 25000-cent target"
        )

    def test_03_the_funding_cascade_leaves_the_compliance_posture_alone(
        self, funded_program
    ):
        """A credit approval never touches the compliance census.

        PRD: "Otherwise, if `behind_measure_count` is exactly one, or
        `exceeding_outfall_count` is at least one, it becomes `AT_RISK`. In every
        other case it is `COMPLIANT`."

        Design: Difficulty/transitive_cascade/credit_approval_cascades_to_underfunded_program_status
        """
        application = fx.file_credit_application(
            funded_program["account"], 0.2755, headers=CLERK_HEADERS
        )
        fx.review_credit_application(
            application["id"], "APPROVE", approved_credit_pct=0.2755
        )

        term = fx.read_term(funded_program["term_id"])
        assert term["compliance_posture"] == "COMPLIANT", (
            "the funding spine must not move the compliance posture"
        )
        assert term["behind_measure_count"] == 0, "no control measure is behind"
        assert term["exceeding_outfall_count"] == 0, "no outfall is exceeding"


class TestFacilityEligibilityGatesApproval:
    """A pending maintenance agreement blocks the credit that cites the facility."""

    @pytest.fixture
    def application_citing_pending_facility(self, funded_program):
        """A SUBMITTED 0.2245 request substantiated by a facility still PENDING."""
        site = fx.setup_site_with_approved_plan(
            funded_program["term_id"],
            site_name="SITE-G",
            operator_name="Greenfield Homes",
            disturbed_acres=1.20,
        )
        facility = fx.create_facility(
            site["id"],
            "PRIVATE",
            facility_type="BIORETENTION",
            design_capacity_cf=4200,
            service_area_acres=1.20,
        )
        application = fx.file_credit_application(
            funded_program["account"],
            0.2245,
            facility_id=facility["id"],
            headers=CLERK_HEADERS,
        )
        return {
            "term_id": funded_program["term_id"],
            "account": funded_program["account"],
            "facility": facility,
            "application": application,
        }

    def test_04_approval_is_refused_while_the_agreement_is_pending(
        self, application_citing_pending_facility
    ):
        """A PRIVATE facility in PENDING is not credit eligible, so review is refused.

        PRD: "`APPROVE` requires that the substantiating facility, when one is
        named, has `credit_eligible` true — a `MUNICIPAL` facility, one with no
        recorded agreement, or one overdue for maintenance inspection is refused
        with `ERR_FACILITY_NOT_CREDIT_ELIGIBLE` — and that the account's existing
        approved credit total plus this `approved_credit_pct` does not exceed
        0.5000, otherwise `ERR_CREDIT_CEILING_EXCEEDED`."

        Design: Difficulty/cross_entity_state_dependency/credit_approval_blocked_by_facility_agreement_state
        """
        facility = fx.read_facility(application_citing_pending_facility["facility"]["id"])
        assert facility["agreement_status"] == "PENDING", (
            "a privately owned control starts with a pending agreement"
        )
        assert facility["credit_eligible"] is False, (
            "a pending agreement leaves the facility outside the credit programme"
        )

        response = api_client.review_fee_credit_application(
            application_citing_pending_facility["application"]["id"],
            {"decision": "APPROVE", "approved_credit_pct": 0.2245},
            CLERK_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_FACILITY_NOT_CREDIT_ELIGIBLE.value, 422)

    def test_05_the_refused_application_and_account_are_left_untouched(
        self, application_citing_pending_facility
    ):
        """The refusal leaves the request SUBMITTED and the pool empty.

        PRD: "In the `FINAL` reckoning — the one behind the account's own stored
        `total_credit_pct` and `current_net_fee_cents` — an application
        contributes its `approved_credit_pct` when its `status` is `APPROVED`,
        and nothing otherwise."

        Design: Difficulty/cross_entity_state_dependency/credit_approval_blocked_by_facility_agreement_state
        """
        application_id = application_citing_pending_facility["application"]["id"]
        api_client.review_fee_credit_application(
            application_id,
            {"decision": "APPROVE", "approved_credit_pct": 0.2245},
            CLERK_HEADERS,
        )

        application = fx.read_application(application_id)
        assert application["status"] == "SUBMITTED", (
            "a refused review leaves the application where it was"
        )
        assert application["approved_credit_pct"] is None, (
            "no approved percentage may be stored by a refused review"
        )

        account = fx.read_account(application_citing_pending_facility["account"]["id"])
        assert_four_dp(account["total_credit_pct"], 0.0000, "total_credit_pct")
        assert_cents(account["current_net_fee_cents"], 29264, "current_net_fee_cents")

    def test_06_recording_the_agreement_makes_the_facility_credit_eligible(
        self, application_citing_pending_facility
    ):
        """An agreement recorded a month back leaves the facility current.

        PRD: "`credit_eligible` is true exactly when `ownership` is `PRIVATE`,
        `agreement_status` is `RECORDED`, and `inspection_overdue` is false — the
        three conditions the utility credit programme leans on in §3.8."

        Design: Difficulty/cross_entity_state_dependency/credit_approval_blocked_by_facility_agreement_state
        """
        facility = validate_success(
            api_client.record_agreement(
                application_citing_pending_facility["facility"]["id"],
                {
                    "agreement_reference": "AGR-G-1",
                    "recorded_at": "2026-07-01T00:00:00Z",
                    "inspection_interval_months": 12,
                },
                INSPECTOR_HEADERS,
            )
        )

        assert facility["agreement_status"] == "RECORDED", "recording writes RECORDED"
        assert facility["agreement_recorded_at"] is not None, (
            "recording copies recorded_at into agreement_recorded_at"
        )
        assert facility["months_since_last_inspection"] == 1, (
            "one whole month separates 2026-07-01 from the logical clock"
        )
        assert facility["inspection_overdue"] is False, (
            "one month is well inside the twelve-month interval"
        )
        assert facility["credit_eligible"] is True, (
            "a recorded, current, privately owned control is credit eligible"
        )

    def test_07_the_identical_review_succeeds_once_the_agreement_is_recorded(
        self, application_citing_pending_facility
    ):
        """After recordation the same 0.2245 approval credits 6570 cents.

        PRD: "The credit in cents is `gross_billable_cents` multiplied by that
        capped percentage, rounded to whole cents, and the net fee is
        `gross_billable_cents` minus that credit."

        Design: Difficulty/cross_entity_state_dependency/credit_approval_blocked_by_facility_agreement_state
        """
        state = application_citing_pending_facility
        api_client.review_fee_credit_application(
            state["application"]["id"],
            {"decision": "APPROVE", "approved_credit_pct": 0.2245},
            CLERK_HEADERS,
        )

        validate_success(
            api_client.record_agreement(
                state["facility"]["id"],
                {
                    "agreement_reference": "AGR-G-1",
                    "recorded_at": "2026-07-01T00:00:00Z",
                    "inspection_interval_months": 12,
                },
                INSPECTOR_HEADERS,
            )
        )

        approved = validate_success(
            api_client.review_fee_credit_application(
                state["application"]["id"],
                {"decision": "APPROVE", "approved_credit_pct": 0.2245},
                CLERK_HEADERS,
            )
        )
        assert approved["status"] == "APPROVED", (
            "the identical review must succeed once the facility qualifies"
        )
        assert_four_dp(approved["approved_credit_pct"], 0.2245, "approved_credit_pct")

        account = fx.read_account(state["account"]["id"])
        assert_four_dp(account["total_credit_pct"], 0.2245, "total_credit_pct")
        assert_cents(account["gross_billable_cents"], 29264, "gross_billable_cents")
        assert_cents(account["current_net_fee_cents"], 22694, "current_net_fee_cents")

        term = fx.read_term(state["term_id"])
        assert_cents(
            term["projected_annual_revenue_cents"], 22694, "projected_annual_revenue_cents"
        )
        assert term["funding_adequacy_status"] == "UNDERFUNDED", (
            "22694 cents of projected revenue falls below the 25000-cent target"
        )


class TestReturnAndResubmitCycle:
    """The application re-enters SUBMITTED carrying different data each time."""

    @pytest.fixture
    def owner_application(self, funded_program):
        """An owner-filed 0.4000 request, returned, resubmitted at 0.3200, returned again."""
        account = funded_program["account"]
        owner_headers = make_property_owner_headers(account["id"])
        application = fx.file_credit_application(account, 0.4000)
        fx.review_credit_application(
            application["id"], "RETURN", return_reason="No maintenance record supplied"
        )
        validate_success(
            api_client.resubmit_fee_credit_application(
                application["id"],
                {
                    "requested_credit_pct": 0.3200,
                    "bmp_description": "Rooftop cistern reuse with annual service contract",
                },
                owner_headers,
            )
        )
        fx.review_credit_application(
            application["id"], "RETURN", return_reason="Service contract expires mid-year"
        )
        return {
            "account": account,
            "owner_headers": owner_headers,
            "application_id": application["id"],
        }

    def test_08_a_return_parks_the_application_with_its_reason(self, funded_program):
        """RETURN writes RETURNED and records why.

        PRD: "`RETURN` writes `RETURNED` into `status` and records the
        `return_reason`, which removes the requested percentage from the
        `INTERIM` pool while leaving the door open to a revised filing."

        Design: Difficulty/non_linear_state_machine/fee_credit_application_return_resubmit_cycle_reenters_submitted
        """
        application = fx.file_credit_application(funded_program["account"], 0.4000)
        assert application["resubmission_count"] == 0, "a new filing starts at 0"

        returned = fx.review_credit_application(
            application["id"], "RETURN", return_reason="No maintenance record supplied"
        )

        assert returned["status"] == "RETURNED", "the review returned the application"
        assert returned["return_reason"] == "No maintenance record supplied", (
            "the review's reason is recorded on the application"
        )
        assert returned["resubmission_count"] == 0, (
            "a return is not itself a resubmission"
        )

    def test_09_the_second_resubmission_reenters_submitted_with_fresh_data(
        self, owner_application
    ):
        """The third visit to SUBMITTED carries 0.2755 and a cleared reason.

        PRD: "It carries a fresh `requested_credit_pct` and `bmp_description`,
        which overwrite the stored values, clears `return_reason` to null, writes
        `SUBMITTED` back into `status`, increments `resubmission_count` by one,
        and returns the requested percentage to the `INTERIM` pool."

        Design: Difficulty/non_linear_state_machine/fee_credit_application_return_resubmit_cycle_reenters_submitted
        """
        resubmitted = validate_success(
            api_client.resubmit_fee_credit_application(
                owner_application["application_id"],
                {
                    "requested_credit_pct": 0.2755,
                    "bmp_description": "Rooftop cistern reuse with three-year service contract",
                },
                owner_application["owner_headers"],
            )
        )

        assert resubmitted["status"] == "SUBMITTED", (
            "resubmission writes SUBMITTED back into status"
        )
        assert resubmitted["resubmission_count"] == 2, (
            "this is the second resubmission of the application"
        )
        assert resubmitted["return_reason"] is None, (
            "resubmission clears the return reason"
        )
        assert_four_dp(resubmitted["requested_credit_pct"], 0.2755, "requested_credit_pct")
        assert resubmitted["approved_credit_pct"] is None, (
            "no cycle through RETURNED ever approves anything"
        )
        assert (
            resubmitted["bmp_description"]
            == "Rooftop cistern reuse with three-year service contract"
        ), "the fresh narrative overwrites the stored one"

    def test_10_the_applicant_identity_survives_every_cycle(self, owner_application):
        """`applicant_user_id` stays the filing owner across both resubmissions.

        PRD: "A returned application is revived by its own applicant, and only by
        the `PropertyOwner` whose `X-User-ID` equals `applicant_user_id`; anyone
        else is refused with `ERR_NOT_APPLICANT`."

        Design: Difficulty/non_linear_state_machine/fee_credit_application_return_resubmit_cycle_reenters_submitted
        """
        account_id = owner_application["account"]["id"]

        resubmitted = validate_success(
            api_client.resubmit_fee_credit_application(
                owner_application["application_id"],
                {
                    "requested_credit_pct": 0.2755,
                    "bmp_description": "Rooftop cistern reuse with three-year service contract",
                },
                owner_application["owner_headers"],
            )
        )

        assert resubmitted["applicant_user_id"] == account_id, (
            "the applicant recorded at filing time survives the cycle"
        )
        assert resubmitted["stormwater_account_id"] == account_id, (
            "the application stays bound to its account"
        )

    def test_11_no_cycle_through_returned_touches_the_final_credit_pool(
        self, owner_application
    ):
        """The account's stored pool is still empty after two cycles.

        PRD: "`SUBMITTED`, `RETURNED`, `DENIED` and `REVOKED` rows contribute
        nothing."

        Design: Difficulty/non_linear_state_machine/fee_credit_application_return_resubmit_cycle_reenters_submitted
        """
        validate_success(
            api_client.resubmit_fee_credit_application(
                owner_application["application_id"],
                {
                    "requested_credit_pct": 0.2755,
                    "bmp_description": "Rooftop cistern reuse with three-year service contract",
                },
                owner_application["owner_headers"],
            )
        )

        account = fx.read_account(owner_application["account"]["id"])
        assert_four_dp(account["total_credit_pct"], 0.0000, "total_credit_pct")
        assert_cents(account["current_net_fee_cents"], 29264, "current_net_fee_cents")
