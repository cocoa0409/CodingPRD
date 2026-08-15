"""Biosimilar substitution policy windows, activation gates, and in-flight
repricing (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    activate_biosimilar_policy,
    assert_biosimilar_policy,
    create_biosimilar_policy,
    create_drug,
    get_claim,
    get_success_data,
    list_adjustments_for_claim,
    set_clock,
    setup_approved_scenario,
    submit_claim,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def _drug_family():
    ref = create_drug(j_code="J3500", drug_name="RefDrug")
    bio1 = create_drug(j_code="J3501", drug_name="BioOne")
    bio2 = create_drug(j_code="J3502", drug_name="BioTwo")
    bio3 = create_drug(j_code="J3503", drug_name="BioThree")
    return ref, bio1, bio2, bio3


class TestHalfOpenWindowOverlap:
    def test_touching_half_open_boundaries_do_not_overlap(self, api):
        """PRD §3.7: "No other `ACTIVE` policy for the same reference drug may overlap the
        new window: two windows overlap exactly when each window's start is strictly
        before the other window's end, so a touching boundary where one window's end
        equals the other's start does not overlap; violations fail with
        `ERR_POLICY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/biosimilar_window_overlap_half_open
        """
        ref, bio1, bio2, _ = _drug_family()
        p1 = create_biosimilar_policy(
            ref["id"], bio1["id"],
            effective_start="2026-08-01", effective_end="2026-12-01",
        )
        activate_biosimilar_policy(p1["id"])

        # P2 starts exactly at P1's exclusive end: half-open adjacency, no overlap.
        p2 = create_biosimilar_policy(
            ref["id"], bio2["id"],
            effective_start="2026-12-01", effective_end="2027-03-01",
        )
        activated = activate_biosimilar_policy(p2["id"])
        assert activated["status"] == "ACTIVE"

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.7: "two windows overlap exactly when each window's start is strictly
        before the other window's end ... violations fail with
        `ERR_POLICY_WINDOW_OVERLAP`." P3 [2026-11-30, 2027-02-01) starts one day before
        P1's end 2026-12-01: a genuine overlap.

        Design: Difficulty/resource_temporal_overlap/biosimilar_window_overlap_half_open
        """
        ref, bio1, _, bio3 = _drug_family()
        p1 = create_biosimilar_policy(
            ref["id"], bio1["id"],
            effective_start="2026-08-01", effective_end="2026-12-01",
        )
        activate_biosimilar_policy(p1["id"])

        p3 = create_biosimilar_policy(
            ref["id"], bio3["id"],
            effective_start="2026-11-30", effective_end="2027-02-01",
        )
        resp = api.activate_biosimilar_policy(p3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP, 409)
        still = validate_success(api.get_biosimilar_policy(p3["id"], ADMIN))
        assert still["status"] == "DRAFT"


class TestPolicyShapeGuards:
    def test_self_mapping_inverted_window_and_remap_rejected(self, api):
        """PRD §3.7: "Creating a policy names `reference_drug_id` and
        `biosimilar_drug_id` — which must differ, or creation fails with
        `ERR_REFERENCE_SELF_BIOSIMILAR`"; "the end must be later than the start
        (`ERR_INVALID_WINDOW`)"; "Independently, the biosimilar drug must not already be
        mapped by another `ACTIVE` policy, or activation fails with
        `ERR_BIOSIMILAR_ALREADY_MAPPED`."

        Design: Corner/validations/biosimilar_policy_shape_guards
        """
        dref = create_drug(j_code="J8200", drug_name="ShapeRef")
        db1 = create_drug(j_code="J8201", drug_name="ShapeBio1")
        db2 = create_drug(j_code="J8202", drug_name="ShapeBio2")
        p1 = create_biosimilar_policy(
            dref["id"], db1["id"],
            effective_start="2026-08-01", effective_end="2027-01-01",
        )
        activate_biosimilar_policy(p1["id"])

        # Self-mapping rejected at creation.
        resp = api.create_biosimilar_policy(
            {
                "reference_drug_id": dref["id"],
                "biosimilar_drug_id": dref["id"],
                "provider_incentive_addon_pct": 0.02,
                "member_copay_waiver_pct": 0.5,
                "effective_start": "2027-02-01",
                "effective_end": "2027-06-01",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_SELF_BIOSIMILAR, 422)

        # Inverted window rejected at creation.
        resp = api.create_biosimilar_policy(
            {
                "reference_drug_id": dref["id"],
                "biosimilar_drug_id": db2["id"],
                "provider_incentive_addon_pct": 0.02,
                "member_copay_waiver_pct": 0.5,
                "effective_start": "2027-06-01",
                "effective_end": "2027-02-01",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, 422)

        # A biosimilar already mapped by an ACTIVE policy is refused at activation
        # (the PRD attaches this check to activation; creation lands DRAFT).
        p3 = get_success_data(
            api.create_biosimilar_policy(
                {
                    "reference_drug_id": dref["id"],
                    "biosimilar_drug_id": db1["id"],
                    "provider_incentive_addon_pct": 0.03,
                    "member_copay_waiver_pct": 0.5,
                    "effective_start": "2027-02-01",
                    "effective_end": "2027-06-01",
                },
                ADMIN,
            )
        )
        assert p3["status"] == "DRAFT"
        resp = api.activate_biosimilar_policy(p3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BIOSIMILAR_ALREADY_MAPPED, 409)


class TestActivationLifecycle:
    def test_activate_active_policy_rejected(self, api):
        """PRD §3.7: "Activation, also by a `PlanAdmin`, requires a `DRAFT` policy —
        otherwise `ERR_BIOSIMILAR_POLICY_NOT_DRAFT`".

        Design: Corner/state_machines/biosimilar_activate_twice_rejected
        """
        ref = create_drug(j_code="J4900", drug_name="RefB")
        bio = create_drug(j_code="J4901", drug_name="BioB")
        policy = create_biosimilar_policy(
            ref["id"], bio["id"],
            effective_start="2026-08-01", effective_end="2027-01-01",
        )
        activated = activate_biosimilar_policy(policy["id"])
        assert_biosimilar_policy(activated)
        assert activated["status"] == "ACTIVE"

        resp = api.activate_biosimilar_policy(policy["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BIOSIMILAR_POLICY_NOT_DRAFT, 409)
        still = validate_success(api.get_biosimilar_policy(policy["id"], ADMIN))
        assert still["status"] == "ACTIVE"

    def test_policy_expires_when_clock_reaches_end(self, api):
        """PRD §3.7: "When the current clock date reaches `effective_end`, the policy
        expires to `EXPIRED`." The window is half-open, so at exactly 2026-09-01 the
        window [2026-08-01, 2026-09-01) has closed.

        Design: Corner/cross_cutting_layers/biosimilar_policy_expires_via_clock
        """
        ref = create_drug(j_code="J7600", drug_name="RefExp")
        bio = create_drug(j_code="J7601", drug_name="BioExp")
        policy = create_biosimilar_policy(
            ref["id"], bio["id"],
            effective_start="2026-08-01", effective_end="2026-09-01",
        )
        activate_biosimilar_policy(policy["id"])

        set_clock("2026-09-01T00:00:00Z")
        expired = validate_success(api.get_biosimilar_policy(policy["id"], ADMIN))
        assert expired["status"] == "EXPIRED"


class TestInFlightRepricing:
    def test_activation_reprices_unpaid_biosimilar_claim(self, api):
        """PRD §3.7: "Activation also reprices in flight: claims on the biosimilar drug
        that are still unpaid — `APPROVED_FOR_PAYMENT` or `PENDED` — with a `service_date`
        inside the new window are repriced in place with the incentive add-on, producing
        no adjustment record and no ledger movement, exactly as in the unpaid branch of
        §3.3, and their member cost share is recomputed under the new waiver."
        round(10 x 500 x 1.08) = 5400; round(5400 x 0.20 x (1 - 0.5)) = 540.

        Design: Corner/calculations/biosimilar_activation_reprices_in_flight
        """
        ref_drug = create_drug(j_code="J5400", drug_name="RefC")
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J5401", "drug_name": "BioC"},
            member_id="MEM-C3",
        )
        claim = submit_claim(scenario, billed_units=10)
        assert claim["allowed_amount_cents"] == 5300  # 10 x 500 x 1.06
        assert claim["member_cost_share_cents"] == 1060
        assert claim["status"] == "APPROVED_FOR_PAYMENT"

        policy = create_biosimilar_policy(
            ref_drug["id"], scenario["drug"]["id"],
            provider_incentive_addon_pct=0.02,
            member_copay_waiver_pct=0.5,
            effective_start="2026-08-01",
            effective_end="2027-01-01",
        )
        activate_biosimilar_policy(policy["id"])

        after = get_claim(claim["id"])
        assert after["allowed_amount_cents"] == 5400, "incentive add-on 0.06 -> 0.08"
        assert after["member_cost_share_cents"] == 540, "50% waiver recomputed"
        assert after["status"] == "APPROVED_FOR_PAYMENT"
        assert list_adjustments_for_claim(claim["id"]) == [], (
            "in-flight repricing creates no adjustment record"
        )
