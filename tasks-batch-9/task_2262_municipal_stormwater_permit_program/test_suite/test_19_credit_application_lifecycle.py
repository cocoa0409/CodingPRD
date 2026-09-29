"""The credit application's four triggers, each guarding its own status."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fee_chain
from test_helpers.test_users import (
    CLERK_HEADERS,
    CLERK_ONE,
    make_property_owner_headers,
)


def _review(application_id, decision, **overrides):
    return api_client.review_fee_credit_application(
        application_id, factories.credit_review_payload(decision, **overrides), CLERK_HEADERS
    )


def _resubmit(application_id, account_id, pct, description):
    return api_client.resubmit_fee_credit_application(
        application_id,
        factories.credit_resubmit_payload(pct, bmp_description=description),
        make_property_owner_headers(account_id),
    )


def _revoke(application_id, reason):
    return api_client.revoke_fee_credit_application(
        application_id, factories.credit_revoke_payload(reason=reason), CLERK_HEADERS
    )


@pytest.fixture
def commercial_account(draft_term):
    """One commercial parcel of 9020 impervious square feet under a 3000 sqft ERU."""
    return fx.create_account(
        draft_term["id"],
        parcel_id="P-1000",
        parcel_class="COMMERCIAL",
        impervious_area_sqft=9020.0,
        owner_name="Ada Owner",
    )


class TestADeniedApplicationRejectsEveryTrigger:
    """Three triggers, three distinct codes, and one precedence question settled."""

    @pytest.fixture
    def denied_application(self, commercial_account):
        """An application counter-filed by the clerk and then denied by the clerk."""
        application = fx.file_credit_application(
            commercial_account, 0.1000, headers=CLERK_HEADERS
        )
        return {"account": commercial_account, "application": application}

    def test_01_a_denial_records_its_rationale_and_grants_no_credit(
        self, denied_application
    ):
        """DENIED is terminal, and nothing is ever approved on it.

        PRD: "`DENY` writes `DENIED` into `status` and records the supplied
        `return_reason` as the denial rationale; no credit is ever applied and `DENIED`
        is terminal."

        Design: Corner/state_machines/credit_application_triggers_each_guard_their_own_status
        """
        denied = validate_success(
            _review(
                denied_application["application"]["id"],
                "DENY",
                return_reason="Practice does not meet the design standard",
            )
        )

        assert denied["status"] == "DENIED", "the decision writes DENIED"
        assert denied["return_reason"] == "Practice does not meet the design standard", (
            "the denial rationale is recorded"
        )
        assert denied["approved_credit_pct"] is None, "no percentage was approved"
        assert denied["reviewed_by_user_id"] == CLERK_ONE, "the reviewer is recorded"

    def test_02_review_is_refused_because_the_status_is_no_longer_submitted(
        self, denied_application
    ):
        """Review has exactly one legal source status.

        PRD: "Review is the clerk's alone and applies only while `status` is
        `SUBMITTED`, otherwise `ERR_CREDIT_APPLICATION_NOT_SUBMITTED`."

        Design: Corner/state_machines/credit_application_triggers_each_guard_their_own_status
        """
        application_id = denied_application["application"]["id"]
        validate_success(
            _review(
                application_id,
                "DENY",
                return_reason="Practice does not meet the design standard",
            )
        )

        response = _review(application_id, "APPROVE", approved_credit_pct=0.1000)

        validate_error(
            response, ApiErrorId.ERR_CREDIT_APPLICATION_NOT_SUBMITTED.value, 409
        )

        application = fx.read_application(application_id)
        assert application["status"] == "DENIED", "the terminal status holds"
        assert application["approved_credit_pct"] is None, "nothing was approved"

    def test_03_the_state_guard_outranks_the_ownership_guard_on_resubmission(
        self, denied_application
    ):
        """The owner is not the applicant here, and still gets the state error.

        PRD: "A returned application is revived by its own applicant, and only by the
        `PropertyOwner` whose `X-User-ID` equals `applicant_user_id`; anyone else is
        refused with `ERR_NOT_APPLICANT`. Resubmission is available only from
        `RETURNED`, otherwise `ERR_CREDIT_APPLICATION_NOT_RETURNED`, and only while
        `resubmission_count` is below two, otherwise
        `ERR_RESUBMISSION_LIMIT_REACHED`." And: "**State-machine legality.** The target
        row must be in a state from which the requested transition exists; otherwise the
        entity's state error is returned with HTTP 409"

        Design: Corner/state_machines/credit_application_triggers_each_guard_their_own_status
        """
        application_id = denied_application["application"]["id"]
        validate_success(
            _review(
                application_id,
                "DENY",
                return_reason="Practice does not meet the design standard",
            )
        )
        assert denied_application["application"]["applicant_user_id"] == CLERK_ONE, (
            "the counter-filed application belongs to the clerk"
        )

        response = _resubmit(
            application_id,
            denied_application["account"]["id"],
            0.0800,
            "Revised rain garden",
        )

        validate_error(
            response, ApiErrorId.ERR_CREDIT_APPLICATION_NOT_RETURNED.value, 409
        )

        application = fx.read_application(application_id)
        assert application["resubmission_count"] == 0, "no cycle was counted"
        assert application["status"] == "DENIED", "the terminal status holds"

    def test_04_revocation_is_refused_on_an_application_that_was_never_approved(
        self, denied_application
    ):
        """Revocation is the remedy against an approved credit only.

        PRD: "Revocation is the clerk's remedy against an approved credit that no longer
        holds. It applies only while `status` is `APPROVED`, otherwise
        `ERR_CREDIT_APPLICATION_NOT_APPROVED`, carries a `reason`, writes `REVOKED` into
        `status`, stamps `revoked_at` and records `revoked_reason`."

        Design: Corner/state_machines/credit_application_triggers_each_guard_their_own_status
        """
        application_id = denied_application["application"]["id"]
        validate_success(
            _review(
                application_id,
                "DENY",
                return_reason="Practice does not meet the design standard",
            )
        )

        response = _revoke(application_id, "Never approved")

        validate_error(
            response, ApiErrorId.ERR_CREDIT_APPLICATION_NOT_APPROVED.value, 409
        )

        application = fx.read_application(application_id)
        assert application["revoked_at"] is None, "nothing was stamped"
        assert application["revoked_reason"] is None, "no reason was recorded"

    def test_05_the_account_keeps_its_whole_gross_billable_amount(
        self, denied_application
    ):
        """A denied application never touches the account's own credit fields.

        PRD: "In the `FINAL` reckoning — the one behind the account's own stored
        `total_credit_pct` and `current_net_fee_cents` — an application contributes its
        `approved_credit_pct` when its `status` is `APPROVED`, and nothing otherwise.
        `SUBMITTED`, `RETURNED`, `DENIED` and `REVOKED` rows contribute nothing."

        Design: Corner/state_machines/credit_application_triggers_each_guard_their_own_status
        """
        application_id = denied_application["application"]["id"]
        validate_success(
            _review(
                application_id,
                "DENY",
                return_reason="Practice does not meet the design standard",
            )
        )
        _review(application_id, "APPROVE", approved_credit_pct=0.1000)
        _resubmit(
            application_id, denied_application["account"]["id"], 0.0800, "Revised garden"
        )
        _revoke(application_id, "Never approved")

        account = fx.read_account(denied_application["account"]["id"])
        assert_fee_chain(
            account,
            eru_units=3.01,
            gross_fee_cents=26129,
            class_surcharge_cents=3135,
            gross_billable_cents=29264,
            total_credit_pct=0.0000,
            current_net_fee_cents=29264,
        )


class TestResubmissionStopsAfterTwoCycles:
    """The ceiling counts resubmissions, of which there may be two, not reviews."""

    @pytest.fixture
    def returned_application(self, commercial_account):
        """An application filed by the owning property owner and returned once."""
        application = fx.file_credit_application(commercial_account, 0.1000)
        returned = fx.review_credit_application(
            application["id"], "RETURN", return_reason="Attach the as-built drawing"
        )
        return {"account": commercial_account, "application": returned}

    def test_06_the_first_resubmission_overwrites_the_request_and_clears_the_reason(
        self, returned_application
    ):
        """A fresh percentage and narrative replace the stored ones.

        PRD: "It carries a fresh `requested_credit_pct` and `bmp_description`, which
        overwrite the stored values, clears `return_reason` to null, writes `SUBMITTED`
        back into `status`, increments `resubmission_count` by one, and returns the
        requested percentage to the `INTERIM` pool."

        Design: Corner/state_machines/resubmission_stops_after_two_cycles
        """
        revived = validate_success(
            _resubmit(
                returned_application["application"]["id"],
                returned_application["account"]["id"],
                0.1200,
                "Rain garden with as-built drawing",
            )
        )

        assert revived["status"] == "SUBMITTED", "the application is live again"
        assert revived["requested_credit_pct"] == pytest.approx(0.1200, abs=0.00005), (
            "the fresh percentage overwrote the stored one"
        )
        assert revived["return_reason"] is None, "the return reason was cleared"
        assert revived["resubmission_count"] == 1, "one cycle was counted"

    def test_07_the_second_resubmission_is_still_accepted(self, returned_application):
        """Two cycles is the whole allowance, and the second reaches it.

        PRD: "Resubmission is available only from `RETURNED`, otherwise
        `ERR_CREDIT_APPLICATION_NOT_RETURNED`, and only while `resubmission_count` is
        below two, otherwise `ERR_RESUBMISSION_LIMIT_REACHED`."

        Design: Corner/state_machines/resubmission_stops_after_two_cycles
        """
        application_id = returned_application["application"]["id"]
        account_id = returned_application["account"]["id"]
        validate_success(
            _resubmit(application_id, account_id, 0.1200, "Rain garden with as-built drawing")
        )
        validate_success(
            _review(application_id, "RETURN", return_reason="Drawing unsigned")
        )

        second = validate_success(
            _resubmit(application_id, account_id, 0.1500, "Rain garden with signed drawing")
        )

        assert second["status"] == "SUBMITTED", "the second cycle is accepted"
        assert second["requested_credit_pct"] == pytest.approx(0.1500, abs=0.00005), (
            "the newer percentage stands"
        )
        assert second["resubmission_count"] == 2, "both cycles were counted"

    def test_08_the_third_resubmission_is_refused_at_the_ceiling(
        self, returned_application
    ):
        """A third return still leaves no room to revive the filing.

        PRD: "and only while `resubmission_count` is below two, otherwise
        `ERR_RESUBMISSION_LIMIT_REACHED`."

        Design: Corner/state_machines/resubmission_stops_after_two_cycles
        """
        application_id = returned_application["application"]["id"]
        account_id = returned_application["account"]["id"]
        validate_success(
            _resubmit(application_id, account_id, 0.1200, "Rain garden with as-built drawing")
        )
        validate_success(
            _review(application_id, "RETURN", return_reason="Drawing unsigned")
        )
        validate_success(
            _resubmit(application_id, account_id, 0.1500, "Rain garden with signed drawing")
        )
        validate_success(
            _review(application_id, "RETURN", return_reason="Signature illegible")
        )

        response = _resubmit(application_id, account_id, 0.1500, "Third try")

        validate_error(response, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED.value, 422)

        application = fx.read_application(application_id)
        assert application["status"] == "RETURNED", "the refused cycle left it returned"
        assert application["resubmission_count"] == 2, "the cycle count is unchanged"
        assert application["requested_credit_pct"] == pytest.approx(
            0.1500, abs=0.00005
        ), "the refused cycle overwrote nothing"

    def test_09_the_applicant_stays_the_filing_owner_through_every_cycle(
        self, returned_application
    ):
        """No ownership error is ever involved, so the ceiling is the only stop.

        PRD: "A new application has `status` `SUBMITTED`, `submitted_at` stamped from
        the logical clock, `applicant_user_id` set to the submitting actor,
        `approved_credit_pct`, `reviewed_by_user_id`, `approved_at`, `return_reason`,
        `revoked_reason` and `revoked_at` null, and `resubmission_count` at 0."

        Design: Corner/state_machines/resubmission_stops_after_two_cycles
        """
        application_id = returned_application["application"]["id"]
        account_id = returned_application["account"]["id"]
        validate_success(
            _resubmit(application_id, account_id, 0.1200, "Rain garden with as-built drawing")
        )
        validate_success(
            _review(application_id, "RETURN", return_reason="Drawing unsigned")
        )
        validate_success(
            _resubmit(application_id, account_id, 0.1500, "Rain garden with signed drawing")
        )

        application = fx.read_application(application_id)
        assert application["applicant_user_id"] == account_id, (
            "the property owner acting as the account is the applicant throughout"
        )
        assert application["reviewed_by_user_id"] == CLERK_ONE, (
            "the clerk is the reviewer of record"
        )
