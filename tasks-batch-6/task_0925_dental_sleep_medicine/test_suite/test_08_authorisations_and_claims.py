"""Prior authorisations, the documentation ladder and the money waterfall."""

from test_helpers import (
    ApiErrorId,
    assert_calendar_date,
    assert_claim,
    assert_money_conservation,
    assert_is_null,
    assert_prior_auth,
    build_scenario,
    draft_claim,
    file_prior_auth,
    open_and_accept_lab_case,
    open_repair,
    record_adherence,
    schedule_and_apply_visit,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def test_prior_auth_denial_and_appeal_cycle_counts_every_attempt(api):
    """PRD §3.4: "A `BillingSpecialist` appeals with a free-text `narrative`, moving the
    authorisation `DENIED → APPEALED` and raising `appeal_attempts` by 1; the appeal is accepted
    only while `appeal_attempts` is strictly below the payer's `appeal_limit`, and the patient's
    records must not be frozen."
    PRD §3.4: "On the denying arm, `SUBMITTED → DENIED`: `denial_reason` is required — one of
    `NOT_MEDICALLY_NECESSARY`, `MISSING_DOCUMENTATION` or `NON_COVERED_ITEM`, with its absence
    answering `ERR_VALIDATION` — and `decided_on` is set the same way, while
    `approval_valid_until` stays null."

    Design: Difficulty/non_linear_state_machine/prior_auth_denial_appeal_cycle_to_denied_final
    """
    scenario = build_scenario(
        "referral_accepted",
        payer_overrides={"prior_auth_required": True, "appeal_limit": 2},
    )
    prior_auth = file_prior_auth(scenario)
    assert_prior_auth(prior_auth)

    denied = validate_success(
        api.decide_prior_auth(
            prior_auth["id"],
            {"decision": "DENIED", "denial_reason": "MISSING_DOCUMENTATION",
             "decided_on": "2026-05-02"},
            scenario["admin_headers"],
        )
    )
    assert denied["status"] == "DENIED"

    appealed = validate_success(
        api.appeal_prior_auth(
            prior_auth["id"], {"narrative": "Chart notes attached"},
            scenario["billing_headers"],
        )
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_attempts"] == 1

    denied_again = validate_success(
        api.decide_prior_auth(
            prior_auth["id"],
            {"decision": "DENIED", "denial_reason": "NOT_MEDICALLY_NECESSARY",
             "decided_on": "2026-05-05"},
            scenario["admin_headers"],
        )
    )
    assert denied_again["status"] == "DENIED", (
        "one attempt remains, so the row returns to DENIED rather than DENIED_FINAL"
    )

    appealed_again = validate_success(
        api.appeal_prior_auth(
            prior_auth["id"], {"narrative": "Peer to peer requested"},
            scenario["billing_headers"],
        )
    )
    assert appealed_again["status"] == "APPEALED"
    assert appealed_again["appeal_attempts"] == 2


def test_prior_auth_lands_in_denied_final_once_the_cap_is_reached(api):
    """PRD §3.4: "The second denial forks on the count: while `appeal_attempts` is still strictly
    below `appeal_limit`, the row returns to `DENIED` with `decided_on` refreshed and the cycle
    may run again; once `appeal_attempts` equals `appeal_limit`, the row lands in `DENIED_FINAL`
    instead, and no further appeal is accepted."
    PRD §3.4: "With the default `appeal_limit` of 2, an authorisation can be denied, appealed,
    denied, appealed, and denied finally."

    Design: Difficulty/non_linear_state_machine/prior_auth_denial_appeal_cycle_to_denied_final
    """
    scenario = build_scenario(
        "referral_accepted",
        payer_overrides={"prior_auth_required": True, "appeal_limit": 2},
    )
    prior_auth = file_prior_auth(scenario)
    for reason, decided_on in (
        ("MISSING_DOCUMENTATION", "2026-05-02"),
        ("NOT_MEDICALLY_NECESSARY", "2026-05-05"),
    ):
        validate_success(
            api.decide_prior_auth(
                prior_auth["id"],
                {"decision": "DENIED", "denial_reason": reason, "decided_on": decided_on},
                scenario["admin_headers"],
            )
        )
        validate_success(
            api.appeal_prior_auth(
                prior_auth["id"], {"narrative": "Appeal"}, scenario["billing_headers"]
            )
        )
    final = validate_success(
        api.decide_prior_auth(
            prior_auth["id"],
            {"decision": "DENIED", "denial_reason": "NOT_MEDICALLY_NECESSARY",
             "decided_on": "2026-05-09"},
            scenario["admin_headers"],
        )
    )
    assert final["status"] == "DENIED_FINAL"
    assert final["appeal_attempts"] == 2


def test_appeal_beyond_the_cap_is_refused(api):
    """PRD §2.6 rung 35: "`appeal_attempts` on the prior authorisation, or on the claim, is
    strictly below the payer's `appeal_limit` before a further appeal is accepted — otherwise
    `ERR_APPEAL_LIMIT_REACHED` (409). Applies to prior-authorisation appeal and claim appeal."
    PRD §3.4: "The friction is worth stating plainly: a stricter reading of the state gate, under
    which only `DENIED` admits an appeal, would answer `ERR_INVALID_STATE` from `DENIED_FINAL`
    and would leave the nominated identifier unreachable there."

    Design: Difficulty/non_linear_state_machine/prior_auth_denial_appeal_cycle_to_denied_final
    """
    scenario = build_scenario(
        "referral_accepted",
        payer_overrides={"prior_auth_required": True, "appeal_limit": 2},
    )
    prior_auth = file_prior_auth(scenario)
    for reason, decided_on in (
        ("MISSING_DOCUMENTATION", "2026-05-02"),
        ("NOT_MEDICALLY_NECESSARY", "2026-05-05"),
    ):
        validate_success(
            api.decide_prior_auth(
                prior_auth["id"],
                {"decision": "DENIED", "denial_reason": reason, "decided_on": decided_on},
                scenario["admin_headers"],
            )
        )
        validate_success(
            api.appeal_prior_auth(
                prior_auth["id"], {"narrative": "Appeal"}, scenario["billing_headers"]
            )
        )
    validate_success(
        api.decide_prior_auth(
            prior_auth["id"],
            {"decision": "DENIED", "denial_reason": "NOT_MEDICALLY_NECESSARY",
             "decided_on": "2026-05-09"},
            scenario["admin_headers"],
        )
    )
    # The specification nominates ERR_APPEAL_LIMIT_REACHED here but records, in the same
    # paragraph, that a stricter reading of the state gate answers ERR_INVALID_STATE, so the
    # assertion admits either without preferring one.
    validate_error_is_one_of(
        api.appeal_prior_auth(
            prior_auth["id"], {"narrative": "Third try"}, scenario["billing_headers"]
        ),
        [
            ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ],
    )
    unchanged = validate_success(
        api.get_prior_auth(prior_auth["id"], scenario["billing_headers"])
    )
    assert unchanged["status"] == "DENIED_FINAL"
    assert unchanged["appeal_attempts"] == 2


def test_claim_allowed_amount_is_capped_at_the_fee_schedule(api):
    """PRD §3.8: "`E0486`, the custom-fabricated appliance, has a fee basis of 185000 cents."
    PRD §3.8: "From that basis, `allowed_cents` is the smaller of `billed_cents` and the fee
    basis, and `adjustment_cents` — the contractual write-off — is `billed_cents` minus
    `allowed_cents`."

    Design: Difficulty/combinatorial_formula/claim_deductible_then_coinsurance_rounding_order
    """
    scenario = build_scenario(
        "delivered",
        payer_overrides={"prior_auth_required": False, "coinsurance_pct": 0.20,
                         "appeal_limit": 2},
        patient_overrides={"deductible_remaining_cents": 50000},
    )
    claim = draft_claim(scenario, billed_cents=250000, written_order_id=scenario["wo_id"])
    submitted = validate_success(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"])
    )
    assert_claim(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["allowed_cents"] == 185000
    assert submitted["adjustment_cents"] == 65000


def test_paid_claim_takes_the_deductible_before_the_coinsurance(api):
    """PRD §3.8: "`deductible_applied_cents` is the smaller of `allowed_cents` and the patient's
    `deductible_remaining_cents` at this instant. The coinsurance base is `allowed_cents` minus
    `deductible_applied_cents`, and `coinsurance_cents` is the payer's `coinsurance_pct`
    multiplied by that base, rounded half up to whole cents. `patient_responsibility_cents` is
    `deductible_applied_cents` plus `coinsurance_cents`, and `payer_paid_cents` is
    `allowed_cents` minus `patient_responsibility_cents`. Finally the ledger syncs: the patient's
    `deductible_remaining_cents` decreases by `deductible_applied_cents`."
    PRD §3.8: "Work an allowed amount of 185000 cents against a patient with 50000 cents of
    deductible left and a 0.20 coinsurance: the deductible takes 50000, the base is 135000,
    coinsurance is 27000, the patient owes **77000** and the payer pays 108000, and the patient's
    remaining deductible falls to 0."

    Design: Difficulty/combinatorial_formula/claim_deductible_then_coinsurance_rounding_order
    """
    scenario = build_scenario(
        "delivered",
        payer_overrides={"prior_auth_required": False, "coinsurance_pct": 0.20,
                         "appeal_limit": 2},
        patient_overrides={"deductible_remaining_cents": 50000},
    )
    claim = draft_claim(scenario, billed_cents=250000, written_order_id=scenario["wo_id"])
    validate_success(api.submit_claim(claim["id"], {}, scenario["billing_headers"]))
    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"outcome": "PAID"}, scenario["admin_headers"])
    )
    assert paid["deductible_applied_cents"] == 50000
    assert paid["coinsurance_cents"] == 27000
    assert paid["patient_responsibility_cents"] == 77000
    assert paid["payer_paid_cents"] == 108000
    assert paid["status"] == "PAID"
    assert_money_conservation(paid)

    patient = validate_success(
        api.get_patient(scenario["pat_id"], scenario["coord_headers"])
    )
    assert patient["deductible_remaining_cents"] == 0


def test_continued_use_claim_is_blocked_while_the_loop_is_open(api):
    """PRD §2.6 rung 24: "A claim of `claim_type` `CONTINUED_USE` may be submitted only when the
    appliance's referral has `loop_status` `CLOSED` — otherwise `ERR_EFFICACY_LOOP_OPEN` (409).
    Applies to claim submission for that claim type only."
    PRD §3.7: "**On `DISPUTED`**, a `dispute_reason` must be supplied — free text, and its
    absence is `ERR_VALIDATION` — the report moves `SUBMITTED → DISPUTED`,
    `physician_decision_on` is stamped, and the referral's `loop_status` stays `OPEN`, so nothing
    downstream unlocks."

    Design: Corner/validations/continued_use_claim_blocked_while_the_cross_provider_loop_is_open
    """
    scenario = build_scenario("efficacy_submitted", efficacy_events=32)
    claim = draft_claim(
        scenario, claim_type="CONTINUED_USE", billed_cents=20000,
        date_of_service="2026-07-06",
    )
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_EFFICACY_LOOP_OPEN.value,
    )
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["billing_headers"])
    )
    assert referral["loop_status"] == "OPEN"
    report = validate_success(
        api.get_efficacy_report(scenario["rep_id"], scenario["dent_headers"])
    )
    assert report["status"] == "SUBMITTED"
    unchanged = validate_success(
        api.get_claim(claim["id"], scenario["billing_headers"])
    )
    assert unchanged["status"] == "DRAFT"


def test_claim_naming_the_dental_benefit_is_refused_at_draft_time(api):
    """PRD §3.8: "The medical-benefit routing rung bites already at draft time — a claim naming
    the patient's `dental_payer_id`, or any payer whose `payer_kind` is `DENTAL`, or a medical
    payer that is not this patient's `medical_payer_id`, is refused with
    `ERR_DENTAL_PAYER_ROUTING` before the row is ever created."

    Design: Corner/validations/claim_against_the_dental_benefit_is_refused
    """
    scenario = build_scenario("delivered", with_dental_payer=True)
    validate_error(
        api.create_claim(
            {
                "patient_id": scenario["pat_id"],
                "payer_id": scenario["payer_dent_id"],
                "appliance_id": scenario["app_id"],
                "claim_type": "INITIAL_DEVICE",
                "hcpcs_code": "E0486",
                "date_of_service": "2026-06-01",
                "billed_cents": 250000,
                "written_order_id": scenario["wo_id"],
            },
            scenario["billing_headers"],
        ),
        ApiErrorId.ERR_DENTAL_PAYER_ROUTING.value,
    )
    rows, meta = validate_paginated(
        api.list_claims(scenario["billing_headers"], {"patient_id": scenario["pat_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_claim_without_prior_authorisation_is_refused_when_the_payer_requires_one(api):
    """PRD §2.6 rung 29: "When the payer requires it, an `APPROVED` and unexpired `PriorAuth`
    must back the claim — otherwise `ERR_PRIOR_AUTH_REQUIRED` (422)."
    PRD §2.6: "When the payer's `prior_auth_required` is true and the claim's linked
    authorisation is missing or in any status other than `APPROVED`, the claim submission is
    refused with `ERR_PRIOR_AUTH_REQUIRED` (422) and **no write occurs**."

    Design: Corner/validations/claim_without_prior_authorisation_is_refused_when_the_payer_requires_one
    """
    scenario = build_scenario(
        "delivered", payer_overrides={"prior_auth_required": True}
    )
    claim = draft_claim(scenario, billed_cents=250000, written_order_id=scenario["wo_id"])
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_PRIOR_AUTH_REQUIRED.value,
    )
    unchanged = validate_success(
        api.get_claim(claim["id"], scenario["billing_headers"])
    )
    assert unchanged["status"] == "DRAFT"
    assert_is_null(unchanged["allowed_cents"], "Claim.allowed_cents")


def test_expired_authorisation_is_written_out_before_the_claim_is_refused(api):
    """PRD §2.6: "When the authorisation is `APPROVED` but the clock date has passed its
    `approval_valid_until`, the write happens first — the authorisation's `status` is persisted
    as `EXPIRED` and its `version` rises by 1 — and then the same `ERR_PRIOR_AUTH_REQUIRED` (422)
    is raised."
    PRD §2.6: "On a later submission against an authorisation that is **already** `EXPIRED`,
    nothing pre-empts this rung, because the authorisation is not the path resource of a claim
    submission and rung 12 there examines only the claim's own `DRAFT` status; rung 29 therefore
    fires again, raises the same `ERR_PRIOR_AUTH_REQUIRED` (422), and this time performs **no**
    write and does **not** bump the authorisation's `version`."
    PRD §3.4: "On the approving arm, `SUBMITTED → APPROVED`: `decided_on` is set to the supplied
    date, or to the clock date when none is supplied, and `approval_valid_until` is computed as
    `decided_on` plus 90 days."

    Design: Corner/validations/expired_prior_authorisation_is_persisted_expired_then_refused
    """
    scenario = build_scenario(
        "delivered", payer_overrides={"prior_auth_required": True}
    )
    prior_auth = file_prior_auth(scenario)
    approved = validate_success(
        api.decide_prior_auth(
            prior_auth["id"],
            {"decision": "APPROVED", "decided_on": "2026-05-05"},
            scenario["admin_headers"],
        )
    )
    assert_calendar_date(
        approved["approval_valid_until"], "2026-08-03", "PriorAuth.approval_valid_until"
    )
    claim = draft_claim(
        scenario, billed_cents=250000, prior_auth_id=prior_auth["id"],
        written_order_id=scenario["wo_id"],
    )
    set_clock("2026-08-04T00:00:00Z")
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_PRIOR_AUTH_REQUIRED.value,
    )
    after_flip = validate_success(
        api.get_prior_auth(prior_auth["id"], scenario["billing_headers"])
    )
    assert after_flip["status"] == "EXPIRED", "the expiry write survives the rejection"

    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_PRIOR_AUTH_REQUIRED.value,
    )
    after_second = validate_success(
        api.get_prior_auth(prior_auth["id"], scenario["billing_headers"])
    )
    assert after_second["version"] == after_flip["version"], (
        "the second submission writes nothing"
    )
    unchanged = validate_success(
        api.get_claim(claim["id"], scenario["billing_headers"])
    )
    assert unchanged["status"] == "DRAFT"


def test_claim_without_proof_of_delivery_is_refused(api):
    """PRD §2.6 rung 30: "`pod_signed_on` is not null and `pod_method` is set — otherwise
    `ERR_POD_MISSING` (422). Applies to claim submission for `claim_type` `INITIAL_DEVICE`,
    `REPLACEMENT` or `CONTINUED_USE`."
    PRD §3.5: "Without it, no device claim of any kind may be submitted."

    Design: Corner/validations/claim_without_proof_of_delivery_is_refused
    """
    scenario = build_scenario("delivered", with_pod=False)
    claim = draft_claim(scenario, billed_cents=250000, written_order_id=scenario["wo_id"])
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_POD_MISSING.value,
    )
    captured = validate_success(
        api.capture_proof_of_delivery(
            scenario["app_id"],
            {"pod_signed_on": "2026-06-01", "pod_method": "SHIPPED"},
            scenario["dent_headers"],
        )
    )
    assert captured["pod_method"] == "SHIPPED"
    submitted = validate_success(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"])
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["allowed_cents"] == 185000


def test_replacement_inside_the_useful_lifetime_is_refused(api):
    """PRD §2.6 rung 31: "A payer-funded replacement is admissible only when `date_of_service`
    falls strictly after the predecessor appliance's `useful_lifetime_end_date` — otherwise
    `ERR_USEFUL_LIFETIME_NOT_ELAPSED` (422). Applies to claim submission for `claim_type`
    `REPLACEMENT`."
    PRD §3.5: "When `replaces_appliance_id` is supplied, the predecessor moves `ACTIVE_THERAPY →
    REPLACED`, and as it leaves therapy its `recall_status` is reset to `NOT_SCHEDULED` and its
    `next_recall_due_on` is cleared to null."

    Design: Corner/validations/payer_funded_replacement_inside_the_useful_lifetime_is_refused
    """
    scenario = build_scenario("delivered")
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    open_repair(scenario, reason="LOSS", reported_on="2026-06-20")
    retired = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert retired["lifecycle_status"] == "RETIRED"
    assert_calendar_date(
        retired["useful_lifetime_end_date"], "2031-06-01",
        "Appliance.useful_lifetime_end_date",
    )

    second_case = open_and_accept_lab_case(scenario, shipped_on="2026-06-25")
    successor = validate_success(
        api.create_appliance(
            {
                "lab_order_id": second_case["id"],
                "lot_id": scenario["lot_id"],
                "serial_number": "SN-0002",
                "has_microrecorder": True,
                "replaces_appliance_id": scenario["app_id"],
            },
            scenario["dent_headers"],
        ),
        201,
    )
    assert successor["replaces_appliance_id"] == scenario["app_id"]

    patient = validate_success(
        api.get_patient(scenario["pat_id"], scenario["coord_headers"])
    )
    second_order = validate_success(
        api.create_written_order(
            {
                "patient_id": scenario["pat_id"],
                "ordering_physician_id": scenario["phys_id"],
                "item_hcpcs": "E0486",
                "order_date": "2026-06-28",
                "f2f_encounter_date": "2026-06-20",
                "expected_patient_version": patient["version"],
            },
            scenario["phys_headers"],
        ),
        201,
    )
    validate_success(
        api.sign_written_order(
            second_order["id"], {"signed_on": "2026-06-28"}, scenario["phys_headers"]
        )
    )
    set_clock("2026-07-01T00:00:00Z")
    validate_success(
        api.deliver_appliance(
            successor["id"],
            {"delivered_on": "2026-07-01", "written_order_id": second_order["id"]},
            scenario["dent_headers"],
        )
    )
    validate_success(
        api.capture_proof_of_delivery(
            successor["id"],
            {"pod_signed_on": "2026-07-01", "pod_method": "IN_PERSON"},
            scenario["dent_headers"],
        )
    )
    claim = validate_success(
        api.create_claim(
            {
                "patient_id": scenario["pat_id"],
                "payer_id": scenario["payer_med_id"],
                "appliance_id": successor["id"],
                "claim_type": "REPLACEMENT",
                "hcpcs_code": "E0486",
                "date_of_service": "2026-07-01",
                "billed_cents": 250000,
                "written_order_id": second_order["id"],
            },
            scenario["billing_headers"],
        ),
        201,
    )
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_USEFUL_LIFETIME_NOT_ELAPSED.value,
    )
    unchanged = validate_success(
        api.get_claim(claim["id"], scenario["billing_headers"])
    )
    assert unchanged["status"] == "DRAFT"


def test_in_warranty_defect_repair_cannot_be_billed(api):
    """PRD §2.6 rung 32: "A repair claim requires the linked repair order's `billable` to be true
    — otherwise `ERR_REPAIR_NOT_BILLABLE` (422). Applies to claim submission for `claim_type`
    `REPAIR`."
    PRD §3.9: "On the in-warranty branch nothing is charged: `labor_units` is 0,
    `repair_charge_cents` is 0, and a repair claim raised against that order is refused with
    `ERR_REPAIR_NOT_BILLABLE`, because the manufacturer covers it."

    Design: Corner/validations/in_warranty_defect_repair_cannot_be_billed
    """
    scenario = build_scenario("delivered")
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    repair = open_repair(
        scenario, reason="DEFECT", reported_on="2026-06-10", labor_minutes=60
    )
    assert repair["in_warranty"] is True
    assert repair["billable"] is False
    assert repair["labor_units"] == 0
    assert repair["repair_charge_cents"] == 0

    claim = draft_claim(
        scenario, claim_type="REPAIR", hcpcs_code="K0739",
        date_of_service="2026-06-10", billed_cents=12000, repair_order_id=repair["id"],
    )
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_REPAIR_NOT_BILLABLE.value,
    )
    unchanged = validate_success(
        api.get_claim(claim["id"], scenario["billing_headers"])
    )
    assert unchanged["status"] == "DRAFT"


def test_continued_use_claim_needs_a_compliant_objective_download(api):
    """PRD §2.6 rung 33: "A continued-use claim requires the newest objective adherence download
    on the appliance to be compliant and requires `recall_status` not to be `LAPSED` — otherwise
    `ERR_ADHERENCE_NOT_MET` (422). Applies to claim submission for `claim_type` `CONTINUED_USE`."
    PRD §3.8: "A patient-attested download, however flattering its figures, never satisfies that
    last rung."

    Design: Corner/validations/continued_use_claim_needs_compliant_objective_adherence
    """
    scenario = build_scenario("active_therapy", efficacy_events=32)
    record_adherence(
        scenario,
        headers=scenario["patient_headers"],
        source="PATIENT_ATTESTED",
        window_start="2026-07-08", window_end="2026-08-06",
        nights_recorded=30, nights_at_or_above_min_hours=29,
        mean_hours_per_worn_night=7.1,
    )
    record_adherence(
        scenario,
        source="OBJECTIVE_MICRORECORDER",
        window_start="2026-07-08", window_end="2026-08-06",
        nights_recorded=30, nights_at_or_above_min_hours=18,
        mean_hours_per_worn_night=3.8,
    )
    claim = draft_claim(
        scenario, claim_type="CONTINUED_USE", billed_cents=20000,
        date_of_service="2026-08-06",
    )
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_ADHERENCE_NOT_MET.value,
    )
    better = record_adherence(
        scenario,
        source="OBJECTIVE_MICRORECORDER",
        window_start="2026-08-07", window_end="2026-09-05",
        nights_recorded=30, nights_at_or_above_min_hours=21,
        mean_hours_per_worn_night=5.5,
    )
    assert better["compliant"] is True
    submitted = validate_success(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"])
    )
    assert submitted["status"] == "SUBMITTED"
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["billing_headers"])
    )
    assert referral["loop_status"] == "CLOSED"


def test_recalled_device_blocks_claim_submission_until_remediation(api):
    """PRD §2.6 rung 13: "When the appliance in scope carries `device_hold_status` `RECALL_HOLD`,
    the request is refused with `ERR_DEVICE_RECALL_HOLD` (409)."
    PRD §3.9: "It moves `device_hold_status` `RECALL_HOLD → NONE` and, when the lifecycle axis
    was suspended, moves `TITRATION_SUSPENDED → IN_TITRATION` on the same call. On the lot,
    `remediated_count` rises by 1 and `pending_remediation_count` falls by 1; when
    `pending_remediation_count` reaches 0 the lot moves `RECALL_ISSUED → REMEDIATION_COMPLETE`,
    which is terminal, and the lot stops blocking anything."

    Design: Corner/validations/recalled_device_blocks_claim_submission
    """
    scenario = build_scenario("delivered")
    claim = draft_claim(scenario, billed_cents=250000, written_order_id=scenario["wo_id"])
    validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-3310", "recall_severity": "CLASS_I"},
            scenario["admin_headers"],
        )
    )
    validate_error(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"]),
        ApiErrorId.ERR_DEVICE_RECALL_HOLD.value,
    )
    remediated = validate_success(
        api.remediate_recall(
            scenario["app_id"],
            {"remediation_action": "Device exchanged under notice"},
            scenario["dent_headers"],
        )
    )
    assert remediated["device_hold_status"] == "NONE"
    submitted = validate_success(
        api.submit_claim(claim["id"], {}, scenario["billing_headers"])
    )
    assert submitted["status"] == "SUBMITTED"
    lot = validate_success(
        api.get_appliance_lot(scenario["lot_id"], scenario["admin_headers"])
    )
    assert lot["status"] == "REMEDIATION_COMPLETE"
    assert lot["pending_remediation_count"] == 0
