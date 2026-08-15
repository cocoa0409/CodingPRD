"""Dose optimization variants at approval and the clinical-safety approval gates
(PRD §3.4, §3.7)."""
from test_helpers import (
    ApiErrorId,
    activate_biosimilar_policy,
    approve_auth,
    create_biosimilar_policy,
    create_drug,
    create_policy,
    create_provider,
    get_auth,
    setup_drug_with_policy,
    submit_auth,
    TEST_USERS,
    validate_error,
)

MPO = TEST_USERS["mpo_headers"]


def _weight_based_pair():
    """Two weight-based drugs (68.8 kg x 2.5 mg/kg -> raw 172 mg): one VIAL-mode
    (100 mg vials), one INCREMENT-mode (10 mg increment) — PRD §3.4 worked example."""
    vial = setup_drug_with_policy(
        drug_overrides={
            "j_code": "J9001",
            "drug_name": "VialDrug",
            "weight_based_dosing": True,
            "mg_per_kg": 2.5,
            "dose_rounding_mode": "VIAL",
            "vial_size_mg": 100,
            "billing_unit_mg": 10,
            "max_single_dose_mg": 1000,
        },
        with_rate=False,
    )
    incr = setup_drug_with_policy(
        drug_overrides={
            "j_code": "J9002",
            "drug_name": "IncrDrug",
            "weight_based_dosing": True,
            "mg_per_kg": 2.5,
            "dose_rounding_mode": "INCREMENT",
            "rounding_increment_mg": 10,
            "max_single_dose_mg": 1000,
        },
        with_rate=False,
    )
    provider = create_provider(name="Oncology Partners")
    auth_v = submit_auth(
        vial["drug"]["id"], provider["id"], "MEM-1", weight_kg=68.8,
        requested_dose_mg=None,
    )
    auth_i = submit_auth(
        incr["drug"]["id"], provider["id"], "MEM-2", weight_kg=68.8,
        requested_dose_mg=None,
    )
    return vial, incr, auth_v, auth_i


class TestDoseOptimizationVariants:
    def test_vial_variant_rounds_up_to_whole_vial(self, api):
        """PRD §3.4: "Under the `VIAL` variant, the raw dose is divided by `vial_size_mg`,
        rounded up to the next whole vial count, and multiplied back — guaranteeing enough
        drug on hand, so a 172 mg raw dose against 100 mg vials approves at 200 mg."

        Design: Difficulty/dual_variant_calc/dose_rounding_vial_vs_increment
        """
        _, _, auth_v, _ = _weight_based_pair()
        approved = approve_auth(auth_v["id"], 4)
        # ceil(172 / 100) * 100 = 200
        assert approved["approved_dose_mg"] == 200, (
            f"VIAL variant must approve 172 mg raw at 200 mg, got {approved['approved_dose_mg']}"
        )

    def test_increment_variant_rounds_half_up_to_increment(self, api):
        """PRD §3.4: "Under the `INCREMENT` variant, the raw dose is divided by
        `rounding_increment_mg`, rounded half-up to the nearest whole increment, and
        multiplied back — so the same 172 mg raw dose against a 10 mg increment approves
        at 170 mg."

        Design: Difficulty/dual_variant_calc/dose_rounding_vial_vs_increment
        """
        _, _, auth_v, auth_i = _weight_based_pair()
        approved_i = approve_auth(auth_i["id"], 4)
        # round_half_up(172 / 10) * 10 = 170
        assert approved_i["approved_dose_mg"] == 170, (
            f"INCREMENT variant must approve 172 mg raw at 170 mg, got {approved_i['approved_dose_mg']}"
        )
        approved_v = approve_auth(auth_v["id"], 4)
        assert approved_v["approved_dose_mg"] != approved_i["approved_dose_mg"], (
            "identical weight and mg_per_kg inputs diverge across the two variants"
        )


class TestClinicalSafetyGates:
    def test_step_therapy_incomplete_blocks_approval(self, api):
        """PRD §3.4: "When the policy's `step_therapy_required` is set, the
        authorization's `step_therapy_completed` must be true, otherwise
        `ERR_STEP_THERAPY_REQUIRED`."

        Design: Corner/validations/clinical_safety_gates
        """
        backbone = setup_drug_with_policy(
            drug_overrides={"j_code": "J6100", "drug_name": "StepDrug"},
            policy_overrides={"step_therapy_required": True},
            with_rate=False,
        )
        provider = create_provider(name="Safety Provider")
        auth = submit_auth(
            backbone["drug"]["id"],
            provider["id"],
            "MEM-V9",
            requested_dose_mg=100,
            step_therapy_completed=False,
        )
        resp = api.approve_auth(auth["id"], {"max_administrations": 4}, MPO)
        validate_error(resp, ApiErrorId.ERR_STEP_THERAPY_REQUIRED, 422)
        assert get_auth(auth["id"])["status"] == "SUBMITTED"

    def test_mandatory_biosimilar_blocks_reference_drug_approval(self, api):
        """PRD §3.4: "When the policy's `biosimilar_substitution` is `MANDATORY`, no
        `ACTIVE` biosimilar policy for the same reference drug may cover
        `requested_start_date` within its half-open window, otherwise
        `ERR_BIOSIMILAR_SUBSTITUTION_REQUIRED` (§3.7)."

        Design: Corner/validations/clinical_safety_gates
        """
        ref = setup_drug_with_policy(
            drug_overrides={"j_code": "J6101", "drug_name": "RefMand"},
            policy_overrides={"biosimilar_substitution": "MANDATORY"},
            with_rate=False,
        )
        bio = create_drug(j_code="J6102", drug_name="BioMand")
        policy = create_biosimilar_policy(
            ref["drug"]["id"],
            bio["id"],
            member_copay_waiver_pct=1.0,
            effective_start="2026-08-01",
            effective_end="2027-01-01",
        )
        activate_biosimilar_policy(policy["id"])

        provider = create_provider(name="Safety Provider 2")
        # requested_start_date 2026-08-15 falls inside [2026-08-01, 2027-01-01).
        auth = submit_auth(
            ref["drug"]["id"],
            provider["id"],
            "MEM-V10",
            requested_start_date="2026-08-15",
            requested_dose_mg=100,
        )
        resp = api.approve_auth(auth["id"], {"max_administrations": 4}, MPO)
        validate_error(resp, ApiErrorId.ERR_BIOSIMILAR_SUBSTITUTION_REQUIRED, 422)
        assert get_auth(auth["id"])["status"] == "SUBMITTED"
