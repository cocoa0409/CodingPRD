"""Patient release instructions: the two evaluation variants, the inclusive
70 uSv/h boundary, and the one-instruction-per-administration rule."""
from test_helpers import (
    TEST_USERS,
    assert_patient_release_instruction,
    calibrate_vial,
    create_order,
    create_patient_release_instruction_payload,
    make_authorized_user_headers,
    prepare_vial,
    set_clock,
    setup_i131_administered,
    setup_i131_department,
    validate_error,
    validate_paginated,
    validate_success,
    administer_vial,
)

ADMIN = TEST_USERS["admin_headers"]


def _two_i131_administrations(api):
    """I-131 department; two orders (THERAPEUTIC 1000 @ 09:00), two vials
    calibrated 1100.000 at 08:30; clock 09:00; both administered.
    Each administration's exact assay is 1098.024 MBq."""
    ctx = setup_i131_department()
    administrations = []
    for _ in range(2):
        order = create_order(
            ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"],
            use_type="THERAPEUTIC", prescribed_activity_mbq=1000,
            administration_scheduled_at="2026-08-01T09:00:00Z",
        )
        vial = prepare_vial(order["id"], ctx["delivery"]["id"])
        calibrate_vial(vial["id"], 1100, "rp-1")
        administrations.append((order, vial))
    set_clock("2026-08-01T09:00:00Z")
    adm_a = administer_vial(administrations[0][1]["id"], "tech-1")
    adm_b = administer_vial(administrations[1][1]["id"], "tech-1")
    ctx["adm_a"] = adm_a
    ctx["adm_b"] = adm_b
    return ctx


class TestVariantDisagreement:
    """Same administration assay: ACTIVITY_BASED releases against the tabulated
    isotope limit while MEASURED_RATE_BASED rejects against 70 uSv/h."""

    def test_activity_based_variant_releases(self, api):
        """PRD §3.8: "Under `ACTIVITY_BASED`, the administration's
        `assayed_activity_exact_mbq` is compared against the isotope's
        `release_activity_limit_mbq`, and the patient is releasable when the
        assayed value is at or below that limit." and "The two variants can
        disagree for the same administration: an administration assayed at
        1098.024 MBq of an iodine-131 product passes the activity-based
        evaluation against a 1221 MBq limit, while a measured rate of 80.0
        microsieverts per hour fails the measured-rate evaluation against the
        70 limit." and "When the patient is releasable, the instruction is
        created with `releasable` set to true, status `ISSUED`..."

        Design: Difficulty/dual_variant_calc/release_activity_variant_vs_measured_rate_variant
        """
        ctx = _two_i131_administrations(api)
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        res = api.create_patient_release_instruction(
            create_patient_release_instruction_payload(
                ctx["adm_a"]["id"], evaluation_variant="ACTIVITY_BASED"
            ),
            au_headers,
        )
        instruction = validate_success(res, 201)
        assert_patient_release_instruction(instruction)
        assert instruction["releasable"] is True
        assert instruction["status"] == "ISSUED"

    def test_measured_rate_variant_rejects(self, api):
        """PRD §3.8: "Under `MEASURED_RATE_BASED`, the
        `measured_dose_rate_at_1m_usv_h` is compared against the regulatory
        dose-rate limit of 70 microsieverts per hour at one meter, and the
        patient is releasable when the measured rate is at or below 70..." and
        "When the chosen variant evaluates to not releasable, the request is
        rejected with `ERR_RELEASE_CRITERIA_NOT_MET` (HTTP 422) and no
        instruction row is persisted."

        80.0 uSv/h > 70: rejected even though the same assay passed
        ACTIVITY_BASED on the sibling administration.

        Design: Difficulty/dual_variant_calc/release_activity_variant_vs_measured_rate_variant
        """
        ctx = _two_i131_administrations(api)
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        res = api.create_patient_release_instruction(
            create_patient_release_instruction_payload(
                ctx["adm_b"]["id"],
                evaluation_variant="MEASURED_RATE_BASED",
                measured_dose_rate_at_1m_usv_h=80,
            ),
            au_headers,
        )
        validate_error(res, "ERR_RELEASE_CRITERIA_NOT_MET", expected_status=422)

        rows, meta = validate_paginated(
            api.list_patient_release_instructions(
                ADMIN, params={"administration_id": ctx["adm_b"]["id"]}
            )
        )
        assert meta["total_count"] == 0 and rows == [], "no instruction row is persisted"


class TestDoseRateInclusiveBoundary:
    """The 70 uSv/h boundary is inclusive: exactly 70.0 is releasable."""

    def test_rate_exactly_70_releasable(self, api):
        """PRD §3.8: "Under `MEASURED_RATE_BASED`, the
        `measured_dose_rate_at_1m_usv_h` is compared against the regulatory
        dose-rate limit of 70 microsieverts per hour at one meter, and the
        patient is releasable when the measured rate is at or below 70..." and
        "Eligibility is variant-specific, and both boundaries are inclusive."

        Design: Difficulty/boundary_precision_check/release_dose_rate_inclusive_limit
        """
        ctx = setup_i131_administered()
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        res = api.create_patient_release_instruction(
            create_patient_release_instruction_payload(
                ctx["administration"]["id"],
                evaluation_variant="MEASURED_RATE_BASED",
                measured_dose_rate_at_1m_usv_h=70,
            ),
            au_headers,
        )
        instruction = validate_success(res, 201)
        assert instruction["releasable"] is True
        assert instruction["status"] == "ISSUED"

    def test_rate_just_above_70_rejected(self, api):
        """PRD §3.8: "the patient is releasable when the measured rate is at or
        below 70..." and "When the chosen variant evaluates to not releasable,
        the request is rejected with `ERR_RELEASE_CRITERIA_NOT_MET` (HTTP 422)
        and no instruction row is persisted."

        70.001 uSv/h lies above the inclusive 70 boundary.

        Design: Difficulty/boundary_precision_check/release_dose_rate_inclusive_limit
        """
        ctx = setup_i131_administered()
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        res = api.create_patient_release_instruction(
            create_patient_release_instruction_payload(
                ctx["administration"]["id"],
                evaluation_variant="MEASURED_RATE_BASED",
                measured_dose_rate_at_1m_usv_h=70.001,
            ),
            au_headers,
        )
        validate_error(res, "ERR_RELEASE_CRITERIA_NOT_MET", expected_status=422)


class TestOneInstructionPerAdministration:
    def test_duplicate_release_instruction_rejected(self, api):
        """PRD §3.8: "At most one instruction may exist per administration; a
        second issuance against the same administration is rejected with
        `ERR_DUPLICATE_RELEASE_INSTRUCTION` (HTTP 409)."

        The second issuance would pass the variant evaluation; the duplicate
        rule fires regardless.

        Design: Corner/validations/duplicate_release_instruction_rejected
        """
        ctx = setup_i131_administered()
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        first = validate_success(
            api.create_patient_release_instruction(
                create_patient_release_instruction_payload(
                    ctx["administration"]["id"], evaluation_variant="ACTIVITY_BASED"
                ),
                au_headers,
            ),
            201,
        )
        assert first["status"] == "ISSUED"

        res = api.create_patient_release_instruction(
            create_patient_release_instruction_payload(
                ctx["administration"]["id"], evaluation_variant="ACTIVITY_BASED"
            ),
            au_headers,
        )
        validate_error(res, "ERR_DUPLICATE_RELEASE_INSTRUCTION", expected_status=409)
