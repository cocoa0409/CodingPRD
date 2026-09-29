"""Three pairs of rules that both apply to one request: the role gate against
the path lookup, the version guard against the vintage rule, and the duties
check against the version guard."""
from test_helpers import (
    ApiErrorId,
    api_client,
    make_preparer_headers,
    make_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    allowance_transaction_payload,
    certification_payload,
)

MISSING_FACILITY_ID = "00000000-0000-4000-8000-000000000000"
CLOCK = "2026-08-01T00:00:00Z"
DUAL_PREPARER = make_preparer_headers("dual_1")
DUAL_REPRESENTATIVE = make_representative_headers("dual_1")


class TestRoleGateBeatsPathLookup:
    """An unauthorized role never learns whether the row exists."""

    def _one_facility(self):
        fx.set_clock(CLOCK)
        return fx.create_facility()

    def test_the_role_gate_is_evaluated_before_the_facility_is_looked_up(self):
        """The same missing id answers 403 to a QA analyst and 404 to a reviewer.

        PRD: "(3) The role is permitted on this endpoint, else `ERR_UNAUTHORIZED`
        — evaluated before any existence lookup."

        Design: Difficulty/priority_pair_validation_conflict/priority_unauthorized_role_beats_missing_facility_lookup
        """
        self._one_facility()

        unauthorized = api_client.update_facility(
            MISSING_FACILITY_ID, {"max_concurrent_control_outages": 3}, fx.QA
        )
        validate_error(unauthorized, ApiErrorId.ERR_UNAUTHORIZED.value)

        as_reviewer = api_client.update_facility(
            MISSING_FACILITY_ID, {"max_concurrent_control_outages": 3}, fx.REVIEWER
        )
        validate_error(as_reviewer, ApiErrorId.ERR_FACILITY_NOT_FOUND.value)

    def test_the_authorized_patch_lands_on_the_real_row(self):
        """The refused attempts created nothing; the real patch spends one version.

        PRD: "The reviewer may later revise `true_up_deadline_utc`,
        `max_concurrent_control_outages` or `status` — the latter moving the facility
        to `RETIRED` — and each such revision increments the facility's `version` by
        one."

        Design: Difficulty/priority_pair_validation_conflict/priority_unauthorized_role_beats_missing_facility_lookup
        """
        facility = self._one_facility()
        assert facility["version"] == 1

        validate_error(
            api_client.update_facility(
                MISSING_FACILITY_ID, {"max_concurrent_control_outages": 3}, fx.QA
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        validate_error(
            api_client.update_facility(
                MISSING_FACILITY_ID, {"max_concurrent_control_outages": 3}, fx.REVIEWER
            ),
            ApiErrorId.ERR_FACILITY_NOT_FOUND.value,
        )

        patched = validate_success(
            api_client.update_facility(
                facility["id"], {"max_concurrent_control_outages": 3}, fx.REVIEWER
            )
        )
        assert patched["max_concurrent_control_outages"] == 3
        assert patched["version"] == 2

        _, meta = validate_paginated(api_client.list_facilities(fx.REVIEWER))
        assert meta["total_count"] == 1, (
            f"no facility row was created by the refusals, got {meta['total_count']}"
        )


class TestVersionGuardBeatsVintageRule:
    """A request carrying both faults reports the concurrency one."""

    def _account_with_one_settled_purchase(self):
        fx.set_clock(CLOCK)
        facility = fx.create_facility()
        account = fx.open_allowance_account(
            facility["id"],
            holdings_prior_vintage_tons=5.0,
            holdings_current_vintage_tons=5.0,
            holdings_next_vintage_tons=5.0,
        )
        stale_version = account["version"]
        fx.settle_transaction(
            account["id"],
            stale_version,
            transaction_type="PURCHASE",
            quantity_tons=5.0,
            vintage_year=2026,
        )
        refreshed = validate_success(
            api_client.get_allowance_account(account["id"], fx.TRADER)
        )
        return {
            "facility": facility,
            "account": refreshed,
            "stale_version": stale_version,
        }

    def _propose(self, account_id, version, vintage_year):
        return api_client.propose_allowance_transaction(
            allowance_transaction_payload(
                version,
                account_id,
                transaction_type="PURCHASE",
                quantity_tons=3.0,
                vintage_year=vintage_year,
            ),
            fx.TRADER,
        )

    def _rows(self, account_id):
        return validate_paginated(
            api_client.list_allowance_transactions(
                fx.REVIEWER, {"allowance_account_id": account_id}
            )
        )

    def test_a_stale_account_version_outranks_an_illegal_vintage_year(self):
        """Both faults are present and only the 412 is reported.

        PRD: "(11) The version guard of §2.7 — the first rule of this band, and
        therefore ahead of every state, safety and fiscal rule below it."

        Design: Difficulty/priority_pair_validation_conflict/priority_stale_account_version_beats_invalid_vintage_year
        """
        station = self._account_with_one_settled_purchase()
        account_id = station["account"]["id"]

        assert station["account"]["holdings_current_vintage_tons"] == 10.000

        both_faults = self._propose(account_id, station["stale_version"], 2030)
        validate_error(both_faults, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)

        _, meta = self._rows(account_id)
        assert meta["total_count"] == 1, (
            "only the settled setup purchase exists, so the refusal created "
            f"nothing, got {meta['total_count']}"
        )
        unchanged = validate_success(
            api_client.get_allowance_account(account_id, fx.TRADER)
        )
        assert unchanged["version"] == station["account"]["version"]

        vintage_only = self._propose(account_id, unchanged["version"], 2030)
        validate_error(vintage_only, ApiErrorId.ERR_VINTAGE_YEAR_INVALID.value)

        _, meta_after = self._rows(account_id)
        assert meta_after["total_count"] == 1

    def test_a_legal_vintage_with_a_fresh_version_is_accepted(self):
        """2027 is the last year the three buckets can address.

        PRD: "and `vintage_year` must fall within the compliance year of the target
        account minus one through that year plus one, both endpoints accepted, which
        is exactly what makes the three holdings buckets exhaustive
        (`ERR_VINTAGE_YEAR_INVALID`)."

        Design: Difficulty/priority_pair_validation_conflict/priority_stale_account_version_beats_invalid_vintage_year
        """
        station = self._account_with_one_settled_purchase()
        account_id = station["account"]["id"]

        validate_error(
            self._propose(account_id, station["stale_version"], 2030),
            ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value,
        )
        validate_error(
            self._propose(account_id, station["account"]["version"], 2030),
            ApiErrorId.ERR_VINTAGE_YEAR_INVALID.value,
        )

        accepted = validate_success(
            self._propose(account_id, station["account"]["version"], 2027), 201
        )
        assert accepted["status"] == "PROPOSED"
        assert accepted["vintage_year"] == 2027
        assert accepted["debited_prior_tons"] == 0.000
        assert accepted["debited_current_tons"] == 0.000
        assert accepted["debited_next_tons"] == 0.000

        _, meta = self._rows(account_id)
        assert meta["total_count"] == 2, (
            f"the two refusals left no rows behind, got {meta['total_count']}"
        )


class TestDutiesCheckBeatsVersionGuard:
    """On certification signing the ranking is reversed: identity comes first."""

    def _submitted_by_dual_user(self):
        station = fx.setup_facility_and_unit(clock=fx.CLOCK_Q2)
        unit_id = station["unit"]["id"]
        station["system"] = fx.setup_certified_cem(unit_id)["system"]
        station["report"] = fx.open_quarterly_report(unit_id, headers=DUAL_PREPARER)
        fx.append_hours_bulk(
            unit_id,
            station["report"]["version"],
            fx.cems_hours(3),
            headers=DUAL_PREPARER,
        )
        validated = fx.validate_report(station["report"]["id"], headers=DUAL_PREPARER)
        station["stale_version"] = validated["version"]
        submitted = fx.submit_report(station["report"]["id"], headers=DUAL_PREPARER)
        station["fresh_version"] = submitted["version"]
        station["submitted"] = submitted
        return station

    def _sign(self, report_id, version, headers):
        return api_client.sign_certification(
            report_id, certification_payload(version), headers
        )

    def _unit(self, unit_id):
        return validate_success(api_client.get_unit(unit_id, fx.REVIEWER))

    def test_the_duties_conflict_is_reported_even_with_a_stale_version(self):
        """Same stale version: dual_1 gets the 409, dr_1 gets the 412.

        PRD: "(5) On certification signing only, the signer differs from the
        preparer who submitted, else `ERR_SEGREGATION_OF_DUTIES` — deliberately
        ahead of the version guard, so a self-certification attempt reports the
        duties conflict even when the client also holds a stale version."

        Design: Difficulty/priority_pair_validation_conflict/priority_segregation_of_duties_beats_stale_report_version
        """
        station = self._submitted_by_dual_user()
        report_id = station["report"]["id"]

        assert station["submitted"]["status"] == "SUBMITTED"
        assert station["submitted"]["submitted_by_user_id"] == "dual_1"
        assert station["fresh_version"] > station["stale_version"]

        both_faults = self._sign(
            report_id, station["stale_version"], DUAL_REPRESENTATIVE
        )
        validate_error(both_faults, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        _, meta = validate_paginated(
            api_client.list_report_certifications(report_id, DUAL_PREPARER)
        )
        assert meta["total_count"] == 0, (
            f"no certification row was created, got {meta['total_count']}"
        )
        assert self._unit(station["unit"]["id"])["certified_so2_lbs_ytd"] == 0.0

        version_only = self._sign(
            report_id, station["stale_version"], fx.REPRESENTATIVE
        )
        validate_error(version_only, ApiErrorId.ERR_STALE_REPORT_VERSION.value)

    def test_a_fresh_version_does_not_let_the_submitter_certify_itself(self):
        """Only a different representative can sign, and then the ledger moves.

        PRD: "If the signer's `X-User-ID` equals the report's
        `submitted_by_user_id`, the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — and that check runs *ahead of* the
        version guard, so a representative attempting to certify their own
        submission sees the duties conflict even when their version is also stale."

        Design: Difficulty/priority_pair_validation_conflict/priority_segregation_of_duties_beats_stale_report_version
        """
        station = self._submitted_by_dual_user()
        report_id = station["report"]["id"]
        unit_id = station["unit"]["id"]

        self_signed = self._sign(
            report_id, station["fresh_version"], DUAL_REPRESENTATIVE
        )
        validate_error(self_signed, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        certification = validate_success(
            self._sign(report_id, station["fresh_version"], fx.REPRESENTATIVE), 201
        )
        assert certification["certifier_user_id"] == "dr_1"
        assert certification["status"] == "SIGNED"
        assert certification["certified_so2_lbs_snapshot"] == 876.6

        report = validate_success(
            api_client.get_quarterly_report(report_id, DUAL_PREPARER)
        )
        assert report["status"] == "CERTIFIED"
        assert self._unit(unit_id)["certified_so2_lbs_ytd"] == 876.6
