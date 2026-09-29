"""The optimistic-concurrency counter, and the fan-out that lands in one request.

Two creates in this system carry a pinned version of their parent row, because
either of them could legitimately be repeated against identical state. Both are
exercised here against a parent that moved underneath the client: a solicitation
that took an addendum after the bidder read it, and a proceeding whose counter
was advanced by the client's own earlier petition. The counter itself is then
audited write by write, and read by read, to show that only mutations move it.

The last group covers the opposite discipline: when one write implies
consequences elsewhere, the whole of that fan-out has already happened by the
time the creating response is serialised.
"""
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    DEBARMENT_AUTHORITY_HEADERS,
    OFFICER_HEADERS,
    make_vendor_headers,
)


def _read_version(getter, resource_id: str, headers: Dict[str, str]) -> int:
    """The `version` of a row as one particular caller observes it."""
    data = validate_success(getter(resource_id, headers))
    version = data["version"]
    assert isinstance(version, int) and not isinstance(version, bool), (
        "version must be an integer, got {!r}".format(version)
    )
    return version


class TestBidCitingThePreAddendumSolicitationVersion:
    """A bidder that priced its offer against the solicitation as it stood
    before an addendum cannot file that offer without re-reading the row."""

    def _setup(self) -> Dict[str, Any]:
        fx.reset_clock()

        vendor = fx.create_vendor(
            legal_name="Ravensworth Striping",
            tax_id="100000096",
            contact_email="v96@example.gov",
        )
        vendor_headers = make_vendor_headers(vendor["id"])

        solicitation = fx.create_solicitation(
            solicitation_number="SOL-2238-C51",
            title="Pavement Marking Term Contract",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc="2026-08-27T00:00:00Z",
            original_question_deadline_utc="2026-08-20T00:00:00Z",
            mandatory_requirements=[
                {
                    "requirement_code": "REQ-PAINT",
                    "description": "waterborne paint",
                    "materiality": "MATERIAL",
                    "is_waivable": False,
                }
            ],
        )
        solicitation = fx.issue_solicitation(solicitation["id"])
        solicitation_id = solicitation["id"]

        # The bidder reads the row, and only afterwards does the officer amend it.
        stale_version = _read_version(
            api_client.get_solicitation, solicitation_id, vendor_headers
        )
        fx.add_addendum(
            solicitation_id,
            summary="clarifies the paint specification",
            extends_bid_due_by_days=0,
            acknowledgment_required=False,
            new_requirement_codes=[],
        )
        fresh_version = _read_version(
            api_client.get_solicitation, solicitation_id, vendor_headers
        )

        return {
            "vendor_id": vendor["id"],
            "vendor_headers": vendor_headers,
            "solicitation_id": solicitation_id,
            "stale_version": stale_version,
            "fresh_version": fresh_version,
        }

    def test_the_stale_pin_is_refused_and_the_re_read_pin_is_accepted(self):
        """If that value does not equal the stored solicitation's current `version` — because an addendum was issued, because the question period was closed, or because another bid create advanced it — the request is rejected with `ERR_STALE_SOLICITATION_VERSION` (HTTP 412).

        Every successful addendum increments the solicitation's `version` by 1, which is precisely why a bidder holding a stale version cannot submit a bid (see §2.6).

        Every bid create, replacement or not, increments the owning solicitation's `version` by 1.

        Design: Corner/cross_cutting_complexity_layers/corner_occ_rejects_a_bid_citing_the_pre_addendum_solicitation_version
        """
        state = self._setup()
        solicitation_id = state["solicitation_id"]
        stale_version = state["stale_version"]
        fresh_version = state["fresh_version"]

        # The amendment is exactly one step of the counter.
        assert fresh_version == stale_version + 1

        body = {
            "solicitation_id": solicitation_id,
            "vendor_id": state["vendor_id"],
            "total_price_cents": 8000000,
            "acknowledged_addendum_sequences": [1],
            "expected_solicitation_version": stale_version,
        }

        refused = api_client.create_bid(body, state["vendor_headers"])
        validate_error(
            refused,
            ApiErrorId.ERR_STALE_SOLICITATION_VERSION.value,
            expected_status=412,
        )

        # Nothing was filed, and the failed create did not move the counter.
        rows, meta = validate_paginated(
            api_client.list_bids(
                OFFICER_HEADERS, params={"solicitation_id": solicitation_id}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert fx.solicitation_version(solicitation_id) == fresh_version

        # The identical body, re-pinned to the version the bidder can now see.
        retry = dict(body)
        retry["expected_solicitation_version"] = fresh_version
        created = validate_success(
            api_client.create_bid(retry, state["vendor_headers"]),
            expected_status=201,
        )
        assert created["total_price_cents"] == 8000000
        assert created["responsiveness_status"] == "UNREVIEWED"
        assert fx.solicitation_version(solicitation_id) == fresh_version + 1


class TestSecondPetitionCitingThePreFilingProceedingVersion:
    """A vendor whose first petition was denied may file again, but the counter
    its own first filing advanced is the one it has to cite."""

    def _setup(self) -> Dict[str, Any]:
        fx.reset_clock()

        vendor = fx.create_vendor(
            legal_name="Selby Bridge Works",
            tax_id="100000097",
            contact_email="v97@example.gov",
        )
        vendor_id = vendor["id"]
        vendor_headers = make_vendor_headers(vendor_id)

        # REPEATED_NONPERFORMANCE 20 plus SAFETY_VIOLATION 15, no mitigation and
        # no prior strikes, so the final severity of 35.00 buys twelve months.
        proceeding = fx.open_proceeding(
            vendor_id,
            cause_code="REPEATED_NONPERFORMANCE",
            aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
            mitigating_factor_codes=[],
            interim_suspension=False,
        )
        proceeding_id = proceeding["id"]

        fx.set_clock("2026-08-16T00:00:00Z")
        fx.hold_debarment_hearing(proceeding_id, hearing_summary="no response filed")
        decided = fx.decide_debarment(
            proceeding_id,
            outcome="DEBARRED",
            rationale="repeated nonperformance established",
        )
        assert decided["debarment_period_months"] == 12

        fx.set_clock("2027-03-01T00:00:00Z")
        stale_version = _read_version(
            api_client.get_debarment_proceeding, proceeding_id, vendor_headers
        )

        first_petition = validate_success(
            api_client.create_reinstatement_petition(
                proceeding_id,
                {
                    "remediation_evidence_codes": ["TRAINING_COMPLETED"],
                    "narrative": "crew retraining completed",
                    "expected_proceeding_version": stale_version,
                },
                vendor_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.decide_reinstatement_petition(
                first_petition["id"],
                {"outcome": "DENIED", "decision_rationale": "remediation insufficient"},
                DEBARMENT_AUTHORITY_HEADERS,
            )
        )
        fresh_version = _read_version(
            api_client.get_debarment_proceeding, proceeding_id, vendor_headers
        )

        return {
            "vendor_id": vendor_id,
            "vendor_headers": vendor_headers,
            "proceeding_id": proceeding_id,
            "first_petition_id": first_petition["id"],
            "stale_version": stale_version,
            "fresh_version": fresh_version,
        }

    def test_the_retry_on_the_pre_filing_version_is_refused_on_the_pin(self):
        """If that value does not equal the proceeding's stored `version` — most commonly because a prior petition decision advanced it — the create is rejected with `ERR_STALE_PROCEEDING_VERSION` (HTTP 412).

        A denial moves the petition `FILED → DENIED`, stamps `decided_at_utc` and `decision_rationale`, leaves the vendor `DEBARRED`, and allows a further petition to be filed later — which is exactly the situation the version pin of §2.6 protects.

        Design: Corner/cross_cutting_complexity_layers/corner_occ_rejects_a_second_petition_citing_the_pre_filing_proceeding_version
        """
        state = self._setup()
        proceeding_id = state["proceeding_id"]
        stale_version = state["stale_version"]
        fresh_version = state["fresh_version"]

        # The first filing advanced the counter; deciding that petition did not.
        assert fresh_version == stale_version + 1

        body = {
            "remediation_evidence_codes": [
                "TRAINING_COMPLETED",
                "COMPLIANCE_AUDIT_PASSED",
            ],
            "narrative": "audit now passed as well",
            "expected_proceeding_version": stale_version,
        }

        refused = api_client.create_reinstatement_petition(
            proceeding_id, body, state["vendor_headers"]
        )
        error = validate_error(
            refused,
            ApiErrorId.ERR_STALE_PROCEEDING_VERSION.value,
            expected_status=412,
        )
        assert error["error_id"] != ApiErrorId.ERR_PETITION_ALREADY_PENDING.value, (
            "the earlier petition is DENIED rather than FILED, so nothing is "
            "pending and the refusal must be the version pin"
        )

        first = fx.read_petition(state["first_petition_id"])
        assert first["status"] == "DENIED"

        rows, meta = validate_paginated(
            api_client.list_reinstatement_petitions(proceeding_id, OFFICER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [state["first_petition_id"]]

    def test_the_same_body_re_pinned_to_the_current_version_is_accepted(self):
        """The petition is created in `status` `FILED`, with `filed_at_utc` stamped from the logical clock, `months_served_at_filing` computed as the number of whole calendar months elapsed from the proceeding's `debarment_start_utc` to that filing instant, and `decided_at_utc` and `decision_rationale` both null.

        Design: Corner/cross_cutting_complexity_layers/corner_occ_rejects_a_second_petition_citing_the_pre_filing_proceeding_version
        """
        state = self._setup()
        proceeding_id = state["proceeding_id"]

        body = {
            "remediation_evidence_codes": [
                "TRAINING_COMPLETED",
                "COMPLIANCE_AUDIT_PASSED",
            ],
            "narrative": "audit now passed as well",
            "expected_proceeding_version": state["stale_version"],
        }

        validate_error(
            api_client.create_reinstatement_petition(
                proceeding_id, body, state["vendor_headers"]
            ),
            ApiErrorId.ERR_STALE_PROCEEDING_VERSION.value,
            expected_status=412,
        )

        retry = dict(body)
        retry["expected_proceeding_version"] = state["fresh_version"]
        second = validate_success(
            api_client.create_reinstatement_petition(
                proceeding_id, retry, state["vendor_headers"]
            ),
            expected_status=201,
        )
        assert second["status"] == "FILED"
        # Debarment started 2026-08-16 and the filing lands 2027-03-01, which is
        # six whole calendar months served and not yet a seventh.
        assert second["months_served_at_filing"] == 6
        assert second["decided_at_utc"] is None
        assert second["decision_rationale"] is None


class TestEverySolicitationWriteAdvancesTheVersion:
    """The counter is a strictly monotonic basis for the stale-version check:
    each mutation adds exactly one step, and reads add none."""

    def test_create_issue_addendum_and_closure_each_add_exactly_one_step(self):
        """Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on each mutation of that row.

        Closing the question period moves the solicitation `ISSUED → QUESTION_PERIOD_CLOSED` on an officer's action, and requires the logical clock to have reached or passed `question_deadline_utc`; an attempt made too early is refused with `ERR_QUESTION_PERIOD_OPEN`.

        Design: Corner/cross_cutting_complexity_layers/corner_every_solicitation_write_advances_the_version_and_no_read_does
        """
        fx.reset_clock()

        drafted = validate_success(
            api_client.create_solicitation(
                {
                    "solicitation_number": "SOL-2238-C52",
                    "title": "Rest Area Renovation",
                    "issuing_agency_code": "DOT",
                    "estimated_value_cents": 10000000,
                    "original_bid_due_utc": "2026-08-27T00:00:00Z",
                    "original_question_deadline_utc": "2026-08-20T00:00:00Z",
                    "mandatory_requirements": [
                        {
                            "requirement_code": "REQ-ADA",
                            "description": "accessibility compliance",
                            "materiality": "MATERIAL",
                            "is_waivable": False,
                        }
                    ],
                },
                OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        solicitation_id = drafted["id"]
        assert drafted["version"] == 1

        # A read of the freshly drafted row leaves it where it was.
        assert (
            _read_version(api_client.get_solicitation, solicitation_id, OFFICER_HEADERS)
            == 1
        )

        issued = validate_success(
            api_client.issue_solicitation(solicitation_id, OFFICER_HEADERS)
        )
        assert issued["version"] == 2
        assert issued["status"] == "ISSUED"

        validate_success(
            api_client.create_addendum(
                solicitation_id,
                {
                    "summary": "clarifies the accessibility scope",
                    "extends_bid_due_by_days": 0,
                    "acknowledgment_required": False,
                    "new_requirement_codes": [],
                },
                OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert (
            _read_version(api_client.get_solicitation, solicitation_id, OFFICER_HEADERS)
            == 3
        )

        fx.set_clock("2026-08-20T00:00:00Z")
        closed = validate_success(
            api_client.close_question_period(solicitation_id, OFFICER_HEADERS)
        )
        assert closed["status"] == "QUESTION_PERIOD_CLOSED"
        assert closed["version"] == 4

        # And a further read still reports the same step.
        assert (
            _read_version(api_client.get_solicitation, solicitation_id, OFFICER_HEADERS)
            == 4
        )


class TestInterimSuspensionFanOutIsVisibleInTheSameResponse:
    """The notice of proposed debarment settles the whole consequence set before
    it answers: the response itself already carries the interim posture, and the
    rows it touched read back changed at the same logical instant."""

    def _setup(self) -> Dict[str, Any]:
        """A prime and a subcontractor, an opened solicitation carrying the
        subcontractor's own bid, and a cleared tier-one screening of it."""
        fx.reset_clock()

        prime = fx.create_vendor(
            legal_name="Tarnwood Prime",
            tax_id="100000098",
            contact_email="v98@example.gov",
        )
        sub = fx.create_vendor(
            legal_name="Underhill Paving",
            tax_id="100000099",
            contact_email="v99@example.gov",
        )

        solicitation = fx.create_solicitation(
            solicitation_number="SOL-2238-C53",
            title="County Road Overlay",
            issuing_agency_code="DOT",
            estimated_value_cents=10000000,
            original_bid_due_utc="2026-08-27T00:00:00Z",
            original_question_deadline_utc="2026-08-20T00:00:00Z",
            mandatory_requirements=[
                {
                    "requirement_code": "REQ-MIX",
                    "description": "approved asphalt mix design",
                    "materiality": "MATERIAL",
                    "is_waivable": False,
                }
            ],
        )
        solicitation = fx.issue_solicitation(solicitation["id"])
        solicitation_id = solicitation["id"]

        screening = fx.screen_subcontractor(
            solicitation_id, prime["id"], sub["id"], tier=1
        )
        assert screening["result"] == "CLEARED"
        assert screening["rescreened_count"] == 0

        bid = fx.submit_bid(
            solicitation_id,
            sub["id"],
            total_price_cents=8000000,
            acknowledged_addendum_sequences=[],
            expected_solicitation_version=fx.solicitation_version(solicitation_id),
        )

        fx.set_clock("2026-08-20T00:00:00Z")
        fx.close_question_period(solicitation_id)
        fx.set_clock("2026-08-27T00:00:00Z")
        opened = fx.open_bids(solicitation_id)
        assert opened["status"] == "BIDS_OPENED"
        assert fx.read_bid(bid["id"])["responsiveness_status"] == "UNREVIEWED"

        return {
            "prime_id": prime["id"],
            "sub_id": sub["id"],
            "solicitation_id": solicitation_id,
            "bid_id": bid["id"],
            "screening_id": screening["id"],
        }

    def test_the_notice_response_already_carries_the_interim_posture(self):
        """When one operation implies consequences for other rows, those consequences are applied inside the same request, before the response is returned; there is no deferred queue and no eventual reconciliation.

        When the notice is issued with `interim_suspension` set to true and the interim severity clears 35, `interim_status` moves `NONE → INTERIM_SUSPENDED`, `strikes_applied` is set to 1, and the respondent moves `ELIGIBLE → SUSPENDED`.

        Design: Corner/consistency_model/corner_interim_suspension_fan_out_is_visible_in_the_same_response
        """
        state = self._setup()

        notice = validate_success(
            api_client.create_debarment_proceeding(
                {
                    "vendor_id": state["sub_id"],
                    "cause_code": "FRAUD",
                    "aggravating_factor_codes": ["FRAUD"],
                    "mitigating_factor_codes": [],
                    "interim_suspension": True,
                },
                DEBARMENT_AUTHORITY_HEADERS,
            ),
            expected_status=201,
        )

        # Everything the notice itself decides is already in this one payload.
        assert notice["status"] == "NOTICE_ISSUED"
        assert notice["interim_status"] == "INTERIM_SUSPENDED"
        assert notice["severity_score"] == pytest.approx(40.00, abs=0.01)
        assert notice["strikes_applied"] == 1
        assert notice["debarment_period_months"] == 0

    def test_the_vendor_bid_and_screening_read_back_changed_at_the_same_instant(self):
        """Every bid of that vendor on a solicitation in `BIDS_OPENED`, `EVALUATION` or `AWARD_PENDING` whose `responsiveness_status` is `UNREVIEWED` or `RESPONSIVE` becomes `NONRESPONSIVE` with `VENDOR_SUSPENDED` appended to `nonresponsive_reason_codes`, and each affected solicitation then recomputes its `apparent_low_bid_id`.

        And every subcontractor screening naming that vendor as the subcontractor whose `result` is `CLEARED` becomes `BLOCKED_SUSPENDED` with its `rescreened_count` incremented.

        That vendor transition sets `suspension_reason_code` to the proceeding's `cause_code` and `active_debarment_id` to the proceeding's id, and recomputes `debarment_strike_count` as the sum of `strikes_applied` over that vendor's proceedings whose `status` is `DEBARRED` or whose `interim_status` is `INTERIM_SUSPENDED`.

        Design: Corner/consistency_model/corner_interim_suspension_fan_out_is_visible_in_the_same_response
        """
        state = self._setup()

        notice = validate_success(
            api_client.create_debarment_proceeding(
                {
                    "vendor_id": state["sub_id"],
                    "cause_code": "FRAUD",
                    "aggravating_factor_codes": ["FRAUD"],
                    "mitigating_factor_codes": [],
                    "interim_suspension": True,
                },
                DEBARMENT_AUTHORITY_HEADERS,
            ),
            expected_status=201,
        )
        assert notice["interim_status"] == "INTERIM_SUSPENDED"

        # No clock movement, no second write: the reads below sit at the very
        # same logical instant as the notice above.
        vendor = fx.read_vendor(state["sub_id"])
        assert vendor["eligibility_status"] == "SUSPENDED"
        assert vendor["debarment_strike_count"] == 1
        assert vendor["active_debarment_id"] == notice["id"]
        assert vendor["suspension_reason_code"] == "FRAUD"

        bid = fx.read_bid(state["bid_id"])
        assert bid["responsiveness_status"] == "NONRESPONSIVE"
        assert "VENDOR_SUSPENDED" in bid["nonresponsive_reason_codes"]

        screening = fx.read_screening(state["screening_id"])
        assert screening["result"] == "BLOCKED_SUSPENDED"
        assert screening["blocked_reason_code"] == "FRAUD"
        assert screening["rescreened_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_debarred_vendors(
                OFFICER_HEADERS, params={"include_suspended": "true"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [state["sub_id"]]
