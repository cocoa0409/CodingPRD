"""Where the notification tier flips, and what the flip costs.

Four hundred ninety-nine exposed individuals against five hundred, then a single
exposed face that reaches the same tier on its own.
"""

from test_helpers import (
    assert_cents,
    assert_instant_equals,
    assessed_incident,
    create_asset,
    create_jurisdiction,
    create_program,
)


def _program_with_one_fingerprint_point(api):
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    point = create_asset(api, program["id"], jurisdiction["id"])
    return program["id"], jurisdiction["id"], point["id"]


def test_the_five_hundredth_exposed_individual_shortens_the_deadline_by_a_month(api):
    """One more exposed individual moves the case from `TIER_2` to `TIER_1`.

    PRD §3.8: "The tier is `TIER_1` when either of two conditions holds: at least one
    affected collection point has a `modality` of `FACE_GEOMETRY` or `IRIS`, or
    `exposed_subject_count` is at least 500."

    PRD §3.8: "The deadline follows from the tier: fifteen days for `TIER_1`,
    forty-five days for `TIER_2`, and `notification_due_at` is `discovered_at` plus
    that many whole days."

    PRD §3.8: "`gross_notice_cents` is 425 cents (US$4.25) for every exposed
    individual plus 15,000 cents (US$150.00) for every non-default locale the
    notification must cover — that is, `exposed_subject_count` multiplied by 425, plus
    `translation_locale_count` multiplied by 15,000."

    PRD §3.8: "**Step two, the regulator surcharge**, keyed on the pre-credit gross and
    never on the net: `regulator_surcharge_cents` is zero when the gross is below
    50,000 cents (US$500.00); it is 25,000 cents (US$250.00) when the gross is at least
    50,000 cents and below 150,000 cents (US$1,500.00); and it is 75,000 cents
    (US$750.00) when the gross is at least 150,000 cents."

    Both cases are discovered on 1 August and both cross the surcharge's top
    threshold, so the tier is the only thing that separates them: the 45-day case is
    due on 15 September and the 15-day case on 16 August, and the extra individual
    adds exactly 425 cents to a cost that is otherwise identically structured.

    Design: Corner/calculations/incident_tier_boundary_at_499_and_500_exposed_subjects_and_modality_override
    """
    program_id, _jurisdiction_id, point_id = _program_with_one_fingerprint_point(api)

    just_below = assessed_incident(
        api,
        program_id,
        [point_id],
        exposed_subject_count=499,
        translation_locale_count=0,
    )
    assert just_below["heightened_tier"] == "TIER_2"
    assert_instant_equals(
        just_below["notification_due_at"], "2026-09-15T00:00:00.000Z", "notification_due_at"
    )
    assert_cents(just_below["gross_notice_cents"], 212075, "gross_notice_cents")
    assert_cents(just_below["regulator_surcharge_cents"], 75000, "regulator_surcharge_cents")
    assert_cents(
        just_below["vendor_indemnity_credit_cents"], 0, "vendor_indemnity_credit_cents"
    )
    assert_cents(just_below["net_incident_cost_cents"], 287075, "net_incident_cost_cents")

    at_the_threshold = assessed_incident(
        api,
        program_id,
        [point_id],
        exposed_subject_count=500,
        translation_locale_count=0,
    )
    assert at_the_threshold["heightened_tier"] == "TIER_1"
    assert_instant_equals(
        at_the_threshold["notification_due_at"],
        "2026-08-16T00:00:00.000Z",
        "notification_due_at",
    )
    assert_cents(at_the_threshold["gross_notice_cents"], 212500, "gross_notice_cents")
    assert_cents(
        at_the_threshold["regulator_surcharge_cents"], 75000, "regulator_surcharge_cents"
    )
    assert_cents(
        at_the_threshold["net_incident_cost_cents"], 287500, "net_incident_cost_cents"
    )


def test_a_single_exposed_face_reaches_the_top_tier_on_its_own(api):
    """The modality route into `TIER_1` does not care how few were exposed.

    PRD §3.8: "Face and iris templates are irrevocable in a way a badge number is not,
    and mass exposure is mass exposure, so both routes into `TIER_1` are independent."

    PRD §3.8: "The deadline follows from the tier: fifteen days for `TIER_1`,
    forty-five days for `TIER_2`, and `notification_due_at` is `discovered_at` plus
    that many whole days."

    PRD §3.8: "Neither dimension waits on the other except at the terminal containment
    step."

    A single exposed individual on a camera prices at 425 cents, far below the
    surcharge's first threshold, and the whole net cost is that gross — yet the
    fifteen-day deadline applies exactly as it did to the five-hundred-subject case.
    Running the notification dimension all the way to `ASSESSED` leaves the containment
    dimension where the case opened.

    Design: Corner/calculations/incident_tier_boundary_at_499_and_500_exposed_subjects_and_modality_override
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    camera = create_asset(
        api,
        program["id"],
        jurisdiction["id"],
        system_category="SECURITY_CAMERA",
        modality="FACE_GEOMETRY",
        template_storage_location="cam-vault-01",
    )

    incident = assessed_incident(
        api,
        program["id"],
        [camera["id"]],
        exposed_subject_count=1,
        translation_locale_count=0,
        exposure_vector="LOST_DEVICE",
        description="A single frame with one enrolled face left a decommissioned laptop.",
    )

    assert incident["heightened_tier"] == "TIER_1"
    assert_instant_equals(
        incident["notification_due_at"], "2026-08-16T00:00:00.000Z", "notification_due_at"
    )
    assert_cents(incident["gross_notice_cents"], 425, "gross_notice_cents")
    assert_cents(incident["regulator_surcharge_cents"], 0, "regulator_surcharge_cents")
    assert_cents(incident["vendor_indemnity_credit_cents"], 0, "vendor_indemnity_credit_cents")
    assert_cents(incident["net_incident_cost_cents"], 425, "net_incident_cost_cents")

    assert incident["notification_status"] == "ASSESSED"
    assert incident["containment_status"] == "DETECTED"
