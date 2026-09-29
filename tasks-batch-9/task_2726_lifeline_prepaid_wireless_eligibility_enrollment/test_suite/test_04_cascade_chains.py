"""Four-link transitive cascades from two different triggering transitions."""

from test_helpers import (
    PROGRAM_ADMIN_ID,
    assert_instant,
    assert_ledger_tuple,
    expected_recoupment,
    fixtures as fx,
)

SWEEP_INSTANT = "2027-08-02T00:00:00Z"


def _dwelling_cohort_with_one_noticed_benefit(api):
    """A flagged dwelling holding one noticed benefit and one co-resident on duplicate hold."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    provider = fx.register_provider(api)
    dwelling = fx.register_address(
        api,
        address_line1="1200 N Main St",
        unit_designator="Apt 4B",
        city="El Paso",
        state_code="TX",
        postal_code="79901",
    )
    applicant = fx.eligible_applicant(api, dwelling["id"])
    enrollment = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        dwelling,
        service_type="VOICE",
        benefit_start_date="2026-08-01T00:00:00Z",
    )

    twin = fx.register_address(
        api,
        address_line1="1200 n. main st.",
        unit_designator="apt 4-b",
        city="EL PASO",
        state_code="TX",
        postal_code="799012214",
    )
    co_resident = fx.create_subscriber(api, dwelling["id"])

    fx.set_clock(api, "2027-06-02T00:00:00Z")
    fx.record_usage(api, enrollment["id"], fx.provider_headers(provider))
    fx.sweep(api, provider["id"])
    check = fx.open_eligibility_check(api, co_resident["id"], proof_document_ref="DOC-G2")
    fx.confirm_eligibility_check(api, check["id"])

    assert fx.refresh_enrollment(api, enrollment["id"])["recert_status"] == "NOTICED", (
        "the first sweep must have issued the recertification notice"
    )
    return {
        "provider": provider,
        "dwelling": dwelling,
        "twin": twin,
        "subscriber": applicant["subscriber"],
        "enrollment": enrollment,
        "co_resident": co_resident,
        "co_resident_check": check,
    }


def test_recert_non_response_stops_the_benefit_and_empties_the_dwelling(api):
    """Links one to three land in the same sweep: lapse, de-enrollment, dwelling release.

    PRD: "Link two, caused by link one, moves `benefit_status` from `ACTIVE` to
    `DE_ENROLLED`, writes `de_enrollment_reason` as `RECERT_NON_RESPONSE`, stamps
    `benefit_end_date` and `de_enrolled_at` with the current instant, and records the
    sweeping operator in `de_enrolled_by_ref`."

    Design: Difficulty/transitive_cascade/sweep_recert_non_response_cascades_to_address_release_and_duplicate_hold_lift
    """
    context = _dwelling_cohort_with_one_noticed_benefit(api)
    enrollment_id = context["enrollment"]["id"]

    fx.set_clock(api, SWEEP_INSTANT)
    sweep = fx.sweep(api, context["provider"]["id"])

    assert sweep["evaluated_enrollment_count"] == 1, (
        "exactly one benefit was ACTIVE when the sweep began"
    )
    assert sweep["recert_non_response_de_enrolled_enrollment_ids"] == [enrollment_id], (
        "step four de-enrolls the unanswered notice"
    )
    assert sweep["non_usage_flagged_enrollment_ids"] == [enrollment_id], (
        "step one had already flagged the same benefit in this request"
    )

    benefit = fx.refresh_enrollment(api, enrollment_id)
    assert benefit["recert_status"] == "NON_RESPONSIVE", "link one"
    assert benefit["usage_status"] == "NON_USAGE_FLAGGED"
    assert benefit["benefit_status"] == "DE_ENROLLED", "link two"
    assert benefit["de_enrollment_reason"] == "RECERT_NON_RESPONSE"
    assert_instant(benefit["benefit_end_date"], SWEEP_INSTANT, "benefit_end_date")
    assert_instant(benefit["de_enrolled_at"], SWEEP_INSTANT, "de_enrolled_at")
    assert benefit["de_enrolled_by_ref"] == PROGRAM_ADMIN_ID, (
        "the sweeping operator's X-User-ID is recorded verbatim"
    )
    assert_instant(
        benefit["appeal_deadline_at"], "2027-09-01T23:59:59.999Z", "appeal_deadline_at"
    )

    dwelling = fx.refresh_address(api, context["dwelling"]["id"])
    assert dwelling["occupied_benefit_slots"] == 0, "link three empties the dwelling"
    assert dwelling["status"] == "RESOLVED_SINGLE_HOUSEHOLD", (
        f"an emptied flagged dwelling resolves itself, got {dwelling['status']}"
    )
    assert dwelling["max_permitted_benefit_slots"] == 1

    carrier = fx.refresh_provider(api, context["provider"]["id"])
    assert carrier["active_enrollment_count"] == 0


def test_the_emptied_dwelling_releases_its_co_resident_from_duplicate_hold(api):
    """Link four lifts the duplicate hold while the twin spelling stays flagged.

    PRD: "Link four, caused by link three, releases every applicant at that dwelling who
    was sitting in `DUPLICATE_HOLD` — to `VERIFIED_ELIGIBLE` where an unexpired confirmed
    check exists and to `PROSPECT` where none does — each with `version` incremented by
    one."

    Design: Difficulty/transitive_cascade/sweep_recert_non_response_cascades_to_address_release_and_duplicate_hold_lift
    """
    context = _dwelling_cohort_with_one_noticed_benefit(api)

    held = fx.refresh_subscriber(api, context["co_resident"]["id"])
    assert held["status"] == "DUPLICATE_HOLD", (
        f"the co-resident is parked behind the flag, got {held['status']}"
    )
    check = fx.refresh_eligibility_check(api, context["co_resident_check"]["id"])
    assert check["status"] == "ELIGIBLE_CONFIRMED"
    assert_instant(check["expires_at"], "2027-08-31T00:00:00Z", "expires_at")

    fx.set_clock(api, SWEEP_INSTANT)
    fx.sweep(api, context["provider"]["id"])

    released = fx.refresh_subscriber(api, context["co_resident"]["id"])
    assert released["status"] == "VERIFIED_ELIGIBLE", (
        f"an unexpired confirmed check releases to VERIFIED_ELIGIBLE, got {released['status']}"
    )
    assert released["version"] > held["version"], "the release increments the applicant's version"

    assert fx.refresh_address(api, context["twin"]["id"])["status"] == "DUPLICATE_FLAGGED", (
        "the other spelling in the cohort is untouched by the release"
    )

    former_holder = fx.refresh_subscriber(api, context["subscriber"]["id"])
    assert former_holder["status"] == "DE_ENROLLED"
    assert former_holder["de_enrollment_count"] == 1, (
        "RECERT_NON_RESPONSE is one of the four fault reasons"
    )


def _carrier_with_two_filed_claims_and_a_drawn_sample(api):
    """Two 1850 cent claims filed a month apart, with a size-2 sample drawn on the later one."""
    fx.set_clock(api, "2026-06-05T00:00:00Z")
    provider = fx.register_provider(api)

    benefits = []
    for index, start in ((1, "2026-01-10T00:00:00Z"), (2, "2026-02-05T00:00:00Z")):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        benefits.append(
            fx.enroll(
                api,
                provider,
                applicant["subscriber"],
                applicant["check"],
                address,
                service_type="VOICE",
                benefit_start_date=start,
            )
        )

    may_claim = fx.file_claim(
        api, fx.draft_claim(api, provider, "2026-05")["id"], provider, "OFFICER-2"
    )
    fx.set_clock(api, "2026-07-02T00:00:00Z")
    june_claim = fx.file_claim(
        api, fx.draft_claim(api, provider, "2026-06")["id"], provider, "OFFICER-2"
    )
    assert may_claim["final_amount_cents"] == 1850, (
        f"the May claim must price two full voice lines, got {may_claim['final_amount_cents']}"
    )
    assert june_claim["final_amount_cents"] == 1850

    ledger_before = fx.refresh_provider(api, provider["id"])
    assert_ledger_tuple(ledger_before, 3700, 0, 3700, False)

    samples = fx.draw_samples(api, june_claim["id"], sample_size=2)
    return {
        "provider": provider,
        "may_claim": may_claim,
        "june_claim": june_claim,
        "samples": samples,
        "early_benefit": benefits[0],
    }


def test_a_failed_sample_drives_its_own_claim_to_audit_failed(api):
    """Links one and two: the adjudication fails and reprices the claim it belongs to.

    PRD: "A failing adjudication on the second claim, with `audit_sample_count` 2 and
    `failed_sample_count` 1, drives it to `AUDIT_FAILED` with `recoupment_amount_cents`
    1018, and the ledger reads `claim_gross_cents` 3700, `recouped_cents` 1018,
    `net_reimbursed_cents` 2682, `audit_hold_flag` true — while the first claim, still
    `FILED`, is now `HELD`."

    Design: Difficulty/transitive_cascade/audit_fail_cascades_claim_then_provider_ledger_then_other_filed_claim_to_held
    """
    context = _carrier_with_two_filed_claims_and_a_drawn_sample(api)
    sample = context["samples"][0]

    adjudicated = fx.adjudicate(
        api,
        sample["id"],
        finding="NON_USAGE_UNCURED",
        finding_note="no traffic in the cure window",
    )
    assert adjudicated["status"] == "ADJUDICATED_FAIL"
    assert adjudicated["finding"] == "NON_USAGE_UNCURED"
    assert adjudicated["claimed_line_cents"] == 925
    assert adjudicated["disallowed_support_cents"] == 925

    claim = fx.refresh_claim(api, context["june_claim"]["id"])
    assert claim["status"] == "AUDIT_FAILED"
    assert claim["final_amount_cents"] == 1850, "the gross figure is never rewritten"
    assert claim["penalty_cents"] == 93, (
        f"925 times 0.10 rounds half up to 93, got {claim['penalty_cents']}"
    )
    assert claim["recoupment_amount_cents"] == 1018
    assert claim["net_payable_cents"] == 832
    assert expected_recoupment(1850, 1, 2)["recoupment_amount_cents"] == 1018

    untouched = fx.refresh_enrollment(api, context["early_benefit"]["id"])
    assert untouched["benefit_status"] == "ACTIVE", (
        "only an INELIGIBLE_SUBSCRIBER finding stops the sampled benefit"
    )


def test_the_hold_flag_sweeps_the_carriers_other_filed_claim_into_held(api):
    """Links three and four: the ledger moves and an untouched sibling claim is held.

    PRD: "Link three, caused by the hold flag becoming true, moves **every other claim of
    that carrier** whose status is `FILED` to `HELD`; those claims are not repriced and
    `claim_gross_cents` still counts them."

    Design: Difficulty/transitive_cascade/audit_fail_cascades_claim_then_provider_ledger_then_other_filed_claim_to_held
    """
    context = _carrier_with_two_filed_claims_and_a_drawn_sample(api)
    fx.adjudicate(api, context["samples"][0]["id"], finding="NON_USAGE_UNCURED")

    carrier = fx.refresh_provider(api, context["provider"]["id"])
    assert_ledger_tuple(carrier, 3700, 1018, 2682, True)

    held = fx.refresh_claim(api, context["may_claim"]["id"])
    assert held["status"] == "HELD", (
        f"the carrier's other FILED claim is held, got {held['status']}"
    )
    assert held["final_amount_cents"] == 1850, "a held claim is not repriced"
    assert held["recoupment_amount_cents"] == 0, "no recoupment is charged to the held claim"
