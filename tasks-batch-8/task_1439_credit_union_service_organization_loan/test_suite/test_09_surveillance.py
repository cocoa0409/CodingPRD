"""Surveillance reporting: WAC weighting variants, supersede, and the
stale-version OCC guard (PRD §2.6, §3.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_wac_pool, setup_pool,
    create_active_agreement, register_credit_union, register_cuso,
    make_cuso_officer_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


def _create_report(api, agreement_id, cuso_id, version, weighting_basis=None):
    payload = {"servicing_agreement_id": agreement_id,
               "period_start": "2026-08-01T00:00:00Z",
               "period_end": "2026-08-31T00:00:00Z",
               "expected_servicing_agreement_version": version}
    if weighting_basis is not None:
        payload["weighting_basis"] = weighting_basis
    return api.create_surveillance_report(payload, make_cuso_officer_headers(cuso_id))


class TestSurveillanceWacWeightingVariants:
    def test_outstanding_weighted_average_yield(self, api):
        """PRD §3.8: "`weighted_avg_yield_bps` is the pool's weighted average coupon: each certificate's weight multiplied by its offering's `yield_rate_bps`, summed over the pool, divided by the sum of the weights, rounded half up to whole basis points."
        PRD §3.8: "Under `OUTSTANDING` weighting the weights track current outstanding principal; under `COMMITTED` they track original committed principal, so the identical pool yields a different average coupon under the two bases."

        Design: Difficulty/dual_variant_calc/surveillance_wac_weighting_variants
        """
        ctx = setup_wac_pool()
        # Pool: cert A outstanding 15,052,084 @600bps; cert B outstanding 10,000,000 @700bps.
        # WAC = round_half_up((15,052,084 x 600 + 10,000,000 x 700) / 25,052,084)
        #     = round_half_up(639.92) = 640.
        rep = validate_success(_create_report(
            api, ctx["agreement"]["id"], ctx["cuso"]["id"],
            ctx["agreement_version"], weighting_basis="OUTSTANDING"), 201)
        assert rep["weighted_avg_yield_bps"] == 640

    def test_committed_weighted_average_yield_and_supersede(self, api):
        """PRD §3.8: "Under `OUTSTANDING` weighting the weights track current outstanding principal; under `COMMITTED` they track original committed principal, so the identical pool yields a different average coupon under the two bases."
        PRD §3.8: "Every report is born `CURRENT`, and creating a new report for an agreement supersedes the agreement's prior `CURRENT` report, moving it to `SUPERSEDED` — exactly one report per agreement remains `CURRENT` at any time."

        Design: Difficulty/dual_variant_calc/surveillance_wac_weighting_variants
        """
        ctx = setup_wac_pool()
        cuso_id = ctx["cuso"]["id"]
        rep1 = validate_success(_create_report(
            api, ctx["agreement"]["id"], cuso_id,
            ctx["agreement_version"], weighting_basis="OUTSTANDING"), 201)

        version2 = get_success_data(api.get_servicing_agreement(
            ctx["agreement"]["id"], make_cuso_officer_headers(cuso_id)))["version"]
        # Committed basis: (20,000,000 x 600 + 10,000,000 x 700) / 30,000,000
        # = round_half_up(633.33) = 633.
        rep2 = validate_success(_create_report(
            api, ctx["agreement"]["id"], cuso_id, version2,
            weighting_basis="COMMITTED"), 201)
        assert rep2["weighted_avg_yield_bps"] == 633
        assert rep2["weighted_avg_yield_bps"] != rep1["weighted_avg_yield_bps"]

        rep1_after = validate_success(
            api.get_surveillance_report(rep1["id"], ADMIN), 200)
        assert rep1_after["status"] == "SUPERSEDED"


class TestSurveillanceOccStaleVersion:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.6: "Publication supersedes the agreement's prior `CURRENT` report and increments the agreement's `version` by one, so a request whose `expected_servicing_agreement_version` no longer matches the agreement's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412): the caller's view of which report is `CURRENT` is stale, and accepting the write would let it supersede a report it never observed."

        Design: Corner/cross_cutting/surveillance_occ_stale_version_rejected
        """
        originator = register_credit_union(charter_number="CU-ORIG", cu_type="ORIGINATOR")
        cuso = register_cuso()
        agreement = create_active_agreement(cuso["id"], originator["id"])
        version = get_success_data(api.get_servicing_agreement(
            agreement["id"], make_cuso_officer_headers(cuso["id"])))["version"]

        rep1 = validate_success(
            _create_report(api, agreement["id"], cuso["id"], version), 201)
        # The first create bumped the agreement's version; replaying the captured
        # version is now stale.
        res = _create_report(api, agreement["id"], cuso["id"], version)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        rep1_after = validate_success(api.get_surveillance_report(rep1["id"], ADMIN), 200)
        assert rep1_after["status"] == "CURRENT"
