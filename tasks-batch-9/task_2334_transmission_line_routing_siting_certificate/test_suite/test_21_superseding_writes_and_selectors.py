"""Optimistic concurrency on the two superseding writes, and the selector pool.

An offer supersedes the standing offer and an amendment restarts the statutory
clock, so both demand the client's last observed version. The paired accepted
case shows the same request landing once the quoted version is current.
"""

from test_helpers import (
    ApiErrorId,
    assert_is_null,
    assert_ratio,
    assert_score,
    assert_timestamp_equals,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


FIRST_OFFER_CENTS = 4_163_406
SECOND_OFFER_CENTS = 4_371_576


def _offered_tract(api):
    """An issued certificate carrying one tract that has been offered once."""
    ctx = fx.setup_issued_certificate(api)
    fx.create_landowner(api, ctx, "lo1")
    created = fx.create_tract(api, ctx, key="tract1", landowner_key="lo1")
    offered = fx.extend_offer(api, ctx, key="tract1")
    return ctx, created["version"], offered["version"]


def _deficient_application(api):
    """An application filed at 2026-08-31 and returned as deficient."""
    ctx = fx.setup_filed_application(api)
    filed_version = fx.read_application(api, ctx["app"])["version"]
    deficient = fx.review_application(
        api, ctx, outcome="REJECT",
        deficiency_note="Impact assessment for the alternate route is missing",
    )
    return ctx, filed_version, deficient["version"]


class TestTractVersionGate:
    """A stale offer is refused; the same offer at the current version lands."""

    def test_an_offer_quoting_the_pre_offer_version_is_refused(self, api):
        """PRD §2.7: "If `expected_tract_version` does not equal the tract's current
        `version`, the request is rejected with `ERR_STALE_TRACT_VERSION` (HTTP 412) and
        nothing is written."

        Design: Corner/complexity_layers/offer_on_a_stale_tract_version_rejected
        """
        ctx, created_version, offered_version = _offered_tract(api)

        response = api.create_offer(
            ctx["tract1"],
            f.offer_payload(created_version, offer_note="Sweetened from a stale view"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.STALE_TRACT_VERSION, expected_status=412)

        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["offer_round"] == 1, (
            f"The standing offer was not superseded, got {tract['offer_round']}"
        )
        assert tract["offered_compensation_cents"] == FIRST_OFFER_CENTS, (
            f"The first offer still stands unescalated, got "
            f"{tract['offered_compensation_cents']}"
        )
        assert tract["acquisition_status"] == "OFFERED", (
            f"The tract stays at OFFERED, got {tract['acquisition_status']}"
        )
        assert tract["version"] == offered_version, (
            f"Nothing was written, so the version is still the one the offer left, got "
            f"{tract['version']}"
        )

    def test_a_re_offer_quoting_the_current_version_is_accepted(self, api):
        """PRD §2.7: "Extending or re-extending a negotiated easement offer requires the
        request to carry `expected_tract_version`, a mandatory field holding the client's
        last observed `version` of the target easement tract."

        Design: Corner/complexity_layers/offer_on_the_current_tract_version_accepted
        """
        ctx, _created_version, _offered_version = _offered_tract(api)
        rejected = fx.respond_to_offer(
            api, ctx, key="tract1", response="REJECT", note="Below market",
            landowner_key="lo1",
        )

        tract = validate_success(
            api.create_offer(
                ctx["tract1"],
                f.offer_payload(rejected["version"], offer_note="Sweetened offer"),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert tract["acquisition_status"] == "OFFERED", (
            f"A sweetened offer carries the tract REJECTED to OFFERED, got "
            f"{tract['acquisition_status']}"
        )
        assert tract["offer_round"] == 2, (
            f"The second offer was recorded, got {tract['offer_round']}"
        )
        assert tract["offered_compensation_cents"] == SECOND_OFFER_CENTS, (
            f"The second round escalates the base offer by 1.05, got "
            f"{tract['offered_compensation_cents']}"
        )
        assert_is_null(tract, "agreed_compensation_cents", "EasementTract")


class TestApplicationVersionGate:
    """A stale amendment is refused; the same amendment at the current version lands."""

    def test_an_amendment_quoting_the_pre_rejection_version_is_refused(self, api):
        """PRD §2.7: "If `expected_application_version` does not equal the application's
        current `version`, the request is rejected with
        `ERR_STALE_APPLICATION_VERSION` (HTTP 412) and nothing is written."

        Design: Corner/complexity_layers/amendment_on_a_stale_application_version_rejected
        """
        ctx, filed_version, _deficient_version = _deficient_application(api)

        response = api.amend_application(
            ctx["app"],
            f.amendment_payload(
                filed_version,
                amendment_summary="Alternate route impact assessment added",
            ),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.STALE_APPLICATION_VERSION, expected_status=412
        )

        application = fx.read_application(api, ctx["app"])
        assert application["review_status"] == "DEFICIENT", (
            f"The filing is still deficient, got {application['review_status']}"
        )
        assert application["amendment_round"] == 0, (
            f"No amendment was recorded, got {application['amendment_round']}"
        )
        assert application["deficiency_note"] == (
            "Impact assessment for the alternate route is missing"
        ), f"The deficiency stands unanswered, got {application['deficiency_note']!r}"
        assert_timestamp_equals(
            application["filed_at"], "2026-08-31T00:00:00Z", "filed_at"
        )

    def test_an_amendment_quoting_the_current_version_restarts_the_clock(self, api):
        """PRD §3.6: "A successful amendment increments `amendment_round`, clears
        `deficiency_note` back to null, moves the application `DEFICIENT → FILED`, resets
        `filed_at` to the current logical clock reading and recomputes
        `decision_deadline_at` from it."

        Design: Corner/complexity_layers/amendment_on_the_current_application_version_accepted
        """
        ctx, _filed_version, deficient_version = _deficient_application(api)
        fx.set_clock(api, "2026-10-04T00:00:00Z")

        application = validate_success(
            api.amend_application(
                ctx["app"],
                f.amendment_payload(
                    deficient_version,
                    amendment_summary="Alternate route impact assessment added",
                ),
                fx.DEVELOPER_FILER_HEADERS,
            ),
            expected_status=201,
        )

        assert application["review_status"] == "FILED", (
            f"The amendment returns the filing to FILED, got "
            f"{application['review_status']}"
        )
        assert application["amendment_round"] == 1, (
            f"The first amendment was recorded, got {application['amendment_round']}"
        )
        assert_is_null(application, "deficiency_note", "SitingApplication")
        assert_timestamp_equals(
            application["filed_at"], "2026-10-04T00:00:00Z", "filed_at"
        )
        assert_timestamp_equals(
            application["decision_deadline_at"], "2027-10-04T00:00:00Z",
            "decision_deadline_at",
        )
        assert application["record_status"] == "NOT_OPENED", (
            f"The record dimension is untouched by the amendment, got "
            f"{application['record_status']}"
        )


class TestNonTransmissionSelector:
    """The pool is the screened-in non-wires and hybrid candidates, cheapest first."""

    def test_the_selector_ranks_only_the_screened_in_non_wires_pool(self, api):
        """PRD §3.1: "eligible candidates are the alternatives on this study whose `kind`
        is `NON_TRANSMISSION` or `HYBRID` **and** whose `screening_status` is
        `SCREENED_IN`; alternatives of `kind` `TRANSMISSION`, and any alternative still
        `SUBMITTED` or already `SCREENED_OUT`, are excluded from the pool even though
        screened-in transmission alternatives still count toward the two-alternative
        gate. Candidates are ranked by `levelized_cost_cents_per_mw` ascending —
        cheapest first."

        Design: Corner/complexity_layers/non_transmission_selector_ranks_the_eligible_pool
        """
        ctx = {}
        fx.create_project(api, ctx)
        study = get_success_data(
            api.create_planning_study(
                f.planning_study_payload(ctx["proj"]), fx.DEVELOPER_HEADERS
            )
        )
        ctx["study"] = study["id"]
        wires = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="TRANSMISSION",
                    description="New 345kV single-circuit line",
                    capex_cents=80_000_000_000, deliverable_mw=400,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        hybrid = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="HYBRID",
                    description="Reconductor plus storage hybrid",
                    capex_cents=92_000_000_000, deliverable_mw=400,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        storage = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="NON_TRANSMISSION",
                    description="Utility-scale storage portfolio",
                    capex_cents=100_000_000_000, deliverable_mw=400,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        demand_response = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="NON_TRANSMISSION",
                    description="Demand response programme",
                    capex_cents=60_000_000_000, deliverable_mw=400,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        for alternative in (wires, hybrid, storage):
            get_success_data(
                api.screen_alternative(
                    alternative["id"],
                    f.screening_payload(
                        decision="SCREEN_IN", screen_reason="Carried into the analysis"
                    ),
                    fx.ROUTE_ANALYST_HEADERS,
                )
            )
        get_success_data(
            api.screen_alternative(
                demand_response["id"],
                f.screening_payload(
                    decision="SCREEN_OUT",
                    screen_reason="Programme cannot be counted as firm capability",
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )

        certified = validate_success(
            api.certify_study_sufficiency(
                ctx["study"],
                f.sufficiency_certification_payload(
                    attestation_note="Need case reviewed by independent engineer"
                ),
                fx.DEVELOPER_CERTIFIER_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(
            fx.read_alternative(api, demand_response["id"])[
                "levelized_cost_cents_per_mw"
            ],
            150_000_000.00, "levelized_cost_cents_per_mw",
        )
        assert certified["selected_nta_alternative_id"] == hybrid["id"], (
            "The cheapest eligible candidate is the 230000000.00 hybrid, because the "
            "cheaper demand response programme was screened out"
        )
        assert_ratio(certified["need_margin_ratio"], 1.1500, "need_margin_ratio")
        assert certified["alternatives_screened_in_count"] == 3, (
            f"Three alternatives were screened in, the wires option included, got "
            f"{certified['alternatives_screened_in_count']}"
        )
        assert certified["status"] == "CERTIFIED_SUFFICIENT", (
            f"A ratio of exactly 1.1500 certifies the study, got {certified['status']}"
        )
