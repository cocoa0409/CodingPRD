"""Role-based access control: exclusive operations, entity-backed ownership and
assignment scoping, provider-type gating, segregation of duties, and the ordering
of the authorization band against the existence band.
"""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    CLOCK_START_UTC,
    COMPLIANCE,
    COMPLIANCE_2,
    FIRMWARE_ENGINEER,
    REIMBURSEMENT,
    REIMBURSEMENT_2,
    REPAIR_TECH,
    ApiErrorId,
    clear_referral,
    file_compliance_override,
    get_success_data,
    make_hearing_professional_headers,
    make_licensed_audiologist_headers,
    make_patient_headers,
    register_patient,
    screening_measurements_payload,
    set_clock,
    setup_authorized_order,
    setup_delivered_order,
    setup_evaluated_referral,
    setup_placed_order,
    setup_registered_patient,
    setup_return_settled,
    validate_error,
    validate_paginated,
    validate_success,
)

# Canonical order economics: list 200000, no discount, no accessories, 1495 shipping.
# tax = 200000 * 0.0725 = 14500, so total_cents = captured_cents = 215995.
ORDER_OVERRIDES = {
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}

NON_EXISTENT_ORDER_ID = "00000000-0000-0000-0000-000000000000"


def _onboard_provider(api, npi, provider_type="TELECARE_FITTER", full_name="Provider"):
    """Onboard one provider with an explicit ten-digit npi (PlatformAdmin-only endpoint)."""
    return get_success_data(
        api.create_provider(
            {
                "provider_type": provider_type,
                "npi": npi,
                "full_name": full_name,
                "licensed_state_codes": ["CA"],
                "daily_capacity_minutes": 480,
                "buffer_minutes": 15,
            },
            ADMIN,
        )
    )


def _start_and_measure_screening(api, patient_id):
    """Start a screening and record its five measurements, leaving it IN_PROGRESS."""
    headers = make_patient_headers(patient_id)
    session = get_success_data(api.start_screening_session(patient_id, {}, headers))
    return get_success_data(
        api.update_screening_session(
            session["id"],
            screening_measurements_payload(
                pure_tone_avg_db=40.0,
                asymmetry_db=5.0,
                self_reported_difficulty_score=20,
                speech_in_noise_pct=70.0,
                symptom_codes=[],
            ),
            headers,
        )
    )


class TestExclusiveOperations:
    """Endpoints listed for a single role deny every other role at the authorization band."""

    def test_owning_patient_cannot_confirm_fit_on_own_order(self, api):
        """PRD §2.1: "If the acting role is permitted on the endpoint but the endpoint is not listed for that role, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §4: "| POST | `/hearing-care/device-orders/{id}/confirm-fit` | Clear the order for shipment: reserves inventory and assigns a device | `CareOpsAgent` |"
        PRD §3.5: "Confirmation moves the fulfillment dimension `PENDING_FIT_CONFIRM → READY_TO_SHIP`, reserves a unit by decrementing that pool's `on_hand_units` by one and incrementing its `reserved_units` by one, assigns an `IN_STOCK` device of the same model by moving that device to `ASSIGNED` and writing the order's identity into the device's `device_order_id`, and increments the order's `version` by one."

        Design: Corner/rbac/rbac_patient_cannot_confirm_fit_care_ops_exclusive
        """
        env = setup_authorized_order(order_overrides=dict(ORDER_OVERRIDES), restock_units=5)
        order_id = env["order"]["id"]
        patient_headers = make_patient_headers(env["patient"]["id"])

        denied = api.confirm_fit(order_id, patient_headers)
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        unchanged = validate_success(api.get_device_order(order_id, CARE_OPS))
        assert unchanged["fulfillment_status"] == "PENDING_FIT_CONFIRM", (
            "a confirm-fit refused at the authorization band must leave fulfillment untouched, "
            f"got {unchanged['fulfillment_status']}"
        )

        allowed = validate_success(api.confirm_fit(order_id, CARE_OPS))
        assert allowed["fulfillment_status"] == "READY_TO_SHIP", (
            "the identical call by the sole authorized role must confirm the fit, "
            f"got {allowed['fulfillment_status']}"
        )

    def test_care_ops_cannot_waive_retained_restocking(self, api):
        """PRD §4: "| POST | `/hearing-care/return-authorizations/{id}/waive-restocking` | Compensating action: refund previously retained restocking | `ComplianceOfficer` |"
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §3.6: "A compliance officer may afterwards waive retained restocking, optionally with a `reason_note`, provided the settled authorization's `restocking_fee_cents` is above 0 and the clock is within 30 days of `settled_at`. This compensating action moves the payment dimension `PARTIALLY_REFUNDED → REFUNDED`, refunding the retained amount so that `refunded_cents` equals `captured_cents`, `retained_cents` becomes 0 and `open_balance_cents` becomes 0, and rewriting the authorization's `restocking_variant` to `WAIVED` with `restocking_fee_cents` and `non_refundable_shipping_cents` set to 0 and `refund_amount_cents` set to `captured_cents`."

        Design: Corner/rbac/rbac_care_ops_cannot_waive_restocking_compliance_exclusive
        """
        env = setup_return_settled(
            inspection_grade="RESELLABLE",
            at_iso="2026-08-11T00:00:00Z",
            order_overrides=dict(ORDER_OVERRIDES),
            restock_units=5,
        )
        rma_id = env["rma"]["id"]

        denied = api.waive_restocking(rma_id, {"reason_note": "goodwill"}, CARE_OPS)
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        settled = validate_success(api.get_return_authorization(rma_id, CARE_OPS))
        assert settled["restocking_fee_cents"] == 20000, (
            "the care operator who received, inspected and settled the return still cannot waive it, "
            f"so the retained restocking must stand at 20000, got {settled['restocking_fee_cents']}"
        )
        assert settled["refund_amount_cents"] == 194500, (
            f"the settled refund must be unchanged at 194500, got {settled['refund_amount_cents']}"
        )

        waived = validate_success(api.waive_restocking(rma_id, {"reason_note": "goodwill"}, COMPLIANCE))
        assert waived["restocking_fee_cents"] == 0, (
            f"the compliance officer's waive must zero the restocking fee, got {waived['restocking_fee_cents']}"
        )
        assert waived["refund_amount_cents"] == 215995, (
            "the waive must set refund_amount_cents to the order's captured_cents of 215995, "
            f"got {waived['refund_amount_cents']}"
        )

    def test_repair_technician_cannot_draft_firmware_campaign(self, api):
        """PRD §4: "| POST | `/hearing-care/firmware-campaigns` | Draft a firmware update campaign | `FirmwareEngineer` |"
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §3.9: "A new campaign's `status` is `DRAFT` with `rollout_count`, `installed_count` and `failure_rate_pct` all 0"

        Design: Corner/rbac/rbac_repair_technician_cannot_create_firmware_campaign
        """
        set_clock(CLOCK_START_UTC)
        payload = {
            "campaign_code": "CAMP-R03",
            "model": "NEO",
            "from_version": "4.0.0",
            "to_version": "4.1.0",
            "is_mandatory_safety": False,
            "batch_size": 5,
            "max_concurrent_installs": 2,
            "window_start_utc": "2026-08-05T00:00:00Z",
            "window_end_utc": "2026-08-30T00:00:00Z",
        }

        denied = api.create_firmware_campaign(payload, REPAIR_TECH)
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        _rows, meta = validate_paginated(
            api.list_firmware_campaigns(FIRMWARE_ENGINEER, params={"limit": 100, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"the refused draft must not have persisted a campaign row, got total_count {meta['total_count']}"
        )

        created = validate_success(api.create_firmware_campaign(payload, FIRMWARE_ENGINEER), 201)
        assert created["status"] == "DRAFT", f"a new campaign starts in DRAFT, got {created['status']}"
        assert created["campaign_code"] == "CAMP-R03", (
            f"the firmware engineer's identical payload must be accepted verbatim, got {created['campaign_code']}"
        )

    def test_hearing_professional_cannot_triage_warranty_claim(self, api):
        """PRD §4: "| POST | `/hearing-care/warranty-claims/{id}/triage` | Triage the claim and compute the deductible | `RepairTechnician` |"
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §3.7: "A depot technician triages the claim, moving it `FILED → TRIAGED` and requiring the device not to be `RETIRED`. Triage stamps `triaged_at`, computes `device_age_months` and `claim_ordinal`, mirrors the age onto the device's `age_months_at_last_claim`, and computes the deductible."
        PRD §3.7: "The kind factor is 0.0 for `DEFECT`, 0.75 for `DAMAGE` and 1.0 for `LOSS`, so a manufacturing defect is never charged a deductible."

        Design: Corner/rbac/rbac_hearing_professional_cannot_triage_warranty_claim
        """
        env = setup_delivered_order(order_overrides=dict(ORDER_OVERRIDES), restock_units=5)
        fitter = _onboard_provider(api, "1000000010", full_name="Fitter HP")
        claim = get_success_data(
            api.create_warranty_claim(
                {"device_id": env["assigned_device"]["id"], "claim_kind": "DEFECT"},
                make_patient_headers(env["patient"]["id"]),
            )
        )

        denied = api.triage_warranty_claim(claim["id"], make_hearing_professional_headers(fitter["id"]))
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        untriaged = validate_success(api.get_warranty_claim(claim["id"], CARE_OPS))
        assert untriaged["status"] == "FILED", (
            f"triage refused at the authorization band leaves the claim FILED, got {untriaged['status']}"
        )
        assert untriaged["triaged_at"] is None, (
            f"the triage calculation must never have run, got triaged_at {untriaged['triaged_at']}"
        )

        triaged = validate_success(api.triage_warranty_claim(claim["id"], REPAIR_TECH))
        assert triaged["status"] == "TRIAGED", (
            f"the depot technician's identical call must triage the claim, got {triaged['status']}"
        )
        assert triaged["deductible_cents"] == 0, (
            f"a DEFECT claim carries a kind factor of 0.0, so the deductible is 0, got {triaged['deductible_cents']}"
        )

    def test_compliance_officer_cannot_author_state_policy(self, api):
        """PRD §4: "| POST | `/hearing-care/state-policies` | Create a state regulatory policy | `PlatformAdmin` |"
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/rbac_compliance_officer_cannot_create_state_policy_platform_admin_exclusive
        """
        set_clock(CLOCK_START_UTC)
        payload = {
            "state_code": "NV",
            "otc_sales_permitted": True,
            "telehealth_fitting_permitted": True,
            "min_age_years": 18,
            "trial_period_days": 45,
            "restocking_fee_mode": "FLAT_PCT",
            "restocking_fee_pct": 0.1,
            "restocking_fee_cap_cents": 0,
            "shipping_refundable": False,
            "referral_validity_days": 180,
            "waiver_required": False,
            "max_loss_damage_claims": 2,
        }

        denied = api.create_state_policy(payload, COMPLIANCE)
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        _rows, meta = validate_paginated(
            api.list_state_policies(ADMIN, params={"limit": 100, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            "reference-data authoring has no hierarchical override, so no policy row may exist, "
            f"got total_count {meta['total_count']}"
        )

    def test_care_ops_cannot_forge_payment_authorization(self, api):
        """PRD §4: "| POST | `/hearing-care/_payments/simulate` | Simulate the payment processor's response for an order authorization | `PlatformAdmin` |"
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §3.5: "A new order's `payment_status` is `PENDING_AUTH`, its `fulfillment_status` is `PENDING_FIT_CONFIRM`, its `delivered_at` and `medical_hold_reason` are null."

        Design: Corner/rbac/rbac_platform_admin_only_simulation_endpoints_denied_to_care_ops
        """
        env = setup_placed_order(order_overrides=dict(ORDER_OVERRIDES), restock_units=5)
        order_id = env["order"]["id"]

        denied = api.simulate_payment({"device_order_id": order_id, "outcome": "AUTHORIZED"}, CARE_OPS)
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        order = validate_success(api.get_device_order(order_id, CARE_OPS))
        assert order["payment_status"] == "PENDING_AUTH", (
            "a care operator cannot forge the processor's answer, so the payment dimension must not move, "
            f"got {order['payment_status']}"
        )
        assert order["captured_cents"] == 0, (
            f"no cash may have moved on the refused simulation, got captured_cents {order['captured_cents']}"
        )


class TestProviderRoleBands:
    """The two provider roles are separated by clinical scope, and the role band is
    consulted before the provider-type band."""

    def test_hearing_professional_role_cannot_invalidate_a_screening(self, api):
        """PRD §4: "| POST | `/hearing-care/screening-sessions/{id}/invalidate` | Licensed audiologist voids a screening for data quality | `LicensedAudiologist` |"
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §2.9: "7. The acting `Provider`'s `provider_type` is `LICENSED_AUDIOLOGIST` for clearance and invalidation operations, namely `POST /provider-referrals/{id}/determination` and `POST /screening-sessions/{id}/invalidate` — otherwise `ERR_PROVIDER_TYPE_NOT_PERMITTED` (403)."
        PRD §3.2: "A licensed audiologist may void an `IN_PROGRESS` session for data quality, moving it to `INVALIDATED` with `invalidated_reason` `DATA_QUALITY`, provided the acting provider's `provider_type` is `LICENSED_AUDIOLOGIST`, their `status` is `ACTIVE`, and their `licensed_state_codes` contains the patient's `state_code`"

        Design: Corner/rbac/rbac_hearing_professional_role_cannot_invalidate_screening
        """
        env = setup_registered_patient()
        fitter = _onboard_provider(api, "1000000001", "TELECARE_FITTER", "Fitter F")
        audiologist = _onboard_provider(api, "1000000002", "LICENSED_AUDIOLOGIST", "Aud A")
        session = _start_and_measure_screening(api, env["patient"]["id"])

        denied = api.invalidate_screening_session(
            session["id"], {"reason_note": "looks noisy"},
            make_hearing_professional_headers(fitter["id"]),
        )
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        untouched = validate_success(api.get_screening_session(session["id"], CARE_OPS))
        assert untouched["status"] == "IN_PROGRESS", (
            "the HearingProfessional role is stopped by the role band, so the session must not be voided, "
            f"got {untouched['status']}"
        )

        voided = validate_success(
            api.invalidate_screening_session(
                session["id"], {"reason_note": "looks noisy"},
                make_licensed_audiologist_headers(audiologist["id"]),
            )
        )
        assert voided["status"] == "INVALIDATED", (
            f"the licensed audiologist's identical call must void the session, got {voided['status']}"
        )
        assert voided["invalidated_reason"] == "DATA_QUALITY", (
            f"a data-quality void stamps invalidated_reason DATA_QUALITY, got {voided['invalidated_reason']}"
        )

    def test_telecare_fitter_presenting_the_audiologist_role_is_denied_by_provider_type(self, api):
        """PRD §2.1: "The distinction between the two provider roles is clinical scope, not identity resolution: a caller may only act as `LicensedAudiologist` when the `Provider` row named by `X-User-ID` has `provider_type` equal to `LICENSED_AUDIOLOGIST`."
        PRD §2.1: "and a caller whose `Provider.provider_type` is `TELECARE_FITTER` attempting a clearance determination or a screening invalidation is rejected with `ERR_PROVIDER_TYPE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.9: "7. The acting `Provider`'s `provider_type` is `LICENSED_AUDIOLOGIST` for clearance and invalidation operations, namely `POST /provider-referrals/{id}/determination` and `POST /screening-sessions/{id}/invalidate` — otherwise `ERR_PROVIDER_TYPE_NOT_PERMITTED` (403)."
        PRD §3.2: "A licensed audiologist may void an `IN_PROGRESS` session for data quality, moving it to `INVALIDATED` with `invalidated_reason` `DATA_QUALITY`, provided the acting provider's `provider_type` is `LICENSED_AUDIOLOGIST`, their `status` is `ACTIVE`, and their `licensed_state_codes` contains the patient's `state_code`"

        Design: Corner/rbac/rbac_provider_type_not_permitted_telecare_fitter_invalidation
        """
        env = setup_registered_patient()
        fitter = _onboard_provider(api, "1000000003", "TELECARE_FITTER", "Fitter G")
        audiologist = _onboard_provider(api, "1000000004", "LICENSED_AUDIOLOGIST", "Aud B")
        session = _start_and_measure_screening(api, env["patient"]["id"])

        denied = api.invalidate_screening_session(
            session["id"], {"reason_note": "data quality"},
            make_licensed_audiologist_headers(fitter["id"]),
        )
        validate_error(denied, ApiErrorId.ERR_PROVIDER_TYPE_NOT_PERMITTED.value)

        untouched = validate_success(api.get_screening_session(session["id"], CARE_OPS))
        assert untouched["status"] == "IN_PROGRESS", (
            "the provider-type band inspects the Provider row behind X-User-ID, so nothing may change, "
            f"got {untouched['status']}"
        )

        voided = validate_success(
            api.invalidate_screening_session(
                session["id"], {"reason_note": "data quality"},
                make_licensed_audiologist_headers(audiologist["id"]),
            )
        )
        assert voided["status"] == "INVALIDATED", (
            "the identical call by a provider whose provider_type is LICENSED_AUDIOLOGIST must succeed, "
            f"got {voided['status']}"
        )

    def test_unassigned_provider_cannot_start_another_providers_session(self, api):
        """PRD §2.1: "a `HearingProfessional` or `LicensedAudiologist` acting on a session or referral whose `provider_id` is not the caller is rejected with `ERR_NOT_ASSIGNED_PROVIDER` (HTTP 403)"
        PRD §2.9: "6. An acting `HearingProfessional` or `LicensedAudiologist` `X-User-ID` equals the targeted `RemoteFittingSession.provider_id` or `ProviderReferral.provider_id`. This applies to `POST /remote-fitting-sessions/{id}/start`, `POST /remote-fitting-sessions/{id}/complete`, `POST /remote-fitting-sessions/{id}/no-show` and `POST /provider-referrals/{id}/determination` — otherwise `ERR_NOT_ASSIGNED_PROVIDER` (403)."
        PRD §3.4: "A provider starts the appointment inside its window, moving it `SCHEDULED → IN_PROGRESS`; the clock must be at or after `scheduled_start_utc` and strictly before `scheduled_end_utc`"

        Design: Corner/rbac/rbac_not_assigned_provider_on_session_start
        """
        env = setup_registered_patient()
        patient_id = env["patient"]["id"]
        assigned = _onboard_provider(api, "1000000005", "TELECARE_FITTER", "Fitter P1")
        bystander = _onboard_provider(api, "1000000006", "TELECARE_FITTER", "Fitter P2")

        session = get_success_data(
            api.create_remote_fitting_session(
                {
                    "patient_id": patient_id,
                    "session_type": "TROUBLESHOOT",
                    "provider_id": assigned["id"],
                    "scheduled_start_utc": "2026-08-02T10:00:00Z",
                    "scheduled_end_utc": "2026-08-02T10:30:00Z",
                },
                make_patient_headers(patient_id),
            )
        )
        set_clock("2026-08-02T10:00:00Z")

        denied = api.start_fitting_session(
            session["id"], make_hearing_professional_headers(bystander["id"])
        )
        validate_error(denied, ApiErrorId.ERR_NOT_ASSIGNED_PROVIDER.value)

        still_scheduled = validate_success(api.get_remote_fitting_session(session["id"], CARE_OPS))
        assert still_scheduled["status"] == "SCHEDULED", (
            "an equally licensed bystander cannot start someone else's appointment, "
            f"got {still_scheduled['status']}"
        )
        assert still_scheduled["provider_id"] == assigned["id"], (
            f"the assignment must be unchanged, got provider_id {still_scheduled['provider_id']}"
        )

        started = validate_success(
            api.start_fitting_session(session["id"], make_hearing_professional_headers(assigned["id"]))
        )
        assert started["status"] == "IN_PROGRESS", (
            f"the assigned provider starts the same session inside its window, got {started['status']}"
        )


class TestOwnershipScoping:
    """Patient-callable endpoints are scoped to the acting Patient's own rows."""

    def test_patient_cannot_read_another_patients_order_summary(self, api):
        """PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's `patient_id` field to `X-User-ID`, including transitively through `device_order_id`, `trial_period_id` or `device_id` when the target resource has no direct `patient_id`."
        PRD §2.1: "A `Patient` acting on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)"
        PRD §2.9: "5. An acting `Patient`'s `X-User-ID` equals the `patient_id` of the targeted resource, directly or transitively through `device_order_id`, `trial_period_id` or `device_id`. This applies to every `Patient`-callable endpoint that targets an existing resource — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."
        PRD §4: "| GET | `/hearing-care/device-orders/{id}/summary` | Computed read: cash conservation breakdown, trial position and fit-exchange history | `Patient`, `CareOpsAgent`, `ComplianceOfficer`, `PlatformAdmin` |"

        Design: Corner/rbac/rbac_not_resource_owner_on_other_patients_order_summary
        """
        env = setup_placed_order(order_overrides=dict(ORDER_OVERRIDES), restock_units=5)
        owner_id = env["patient"]["id"]
        order_id = env["order"]["id"]
        stranger = register_patient(env["policy"]["id"])

        denied = api.get_device_order_summary(order_id, make_patient_headers(stranger["id"]))
        validate_error(denied, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

        validate_success(api.get_device_order_summary(order_id, make_patient_headers(owner_id)))
        validate_success(api.get_device_order_summary(order_id, CARE_OPS))


class TestSegregationOfDuties:
    """Two-person control is enforced on the recorded operator identities."""

    def test_submitting_specialist_cannot_decide_own_reimbursement_claim(self, api):
        """PRD §2.10: "Second, a reimbursement claim's `submitted_by_user_id` cannot equal the `X-User-ID` deciding it, on approve and on deny alike."
        PRD §2.9: "8. Segregation of duties on approval: the approving `X-User-ID` differs from `ReimbursementClaim.submitted_by_user_id`, and the approving `ComplianceOfficer`'s `X-User-ID` differs from the `filed_by_user_id` of the compliance override. This applies to `POST /reimbursement-claims/{id}/decide` and `POST /patients/{patient_id}/compliance-overrides/{override_id}/approve` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
        PRD §3.8: "Deciding the claim supplies a `decision` and, on denial, a `denial_reason`. Both branches require the acting operator identity to differ from `submitted_by_user_id`. An approval moves the claim `UNDER_REVIEW → APPROVED`, records `approved_by_user_id`, and requires `claimed_amount_cents` to be at most `eligible_amount_cents`; benefit conservation holds."

        Design: Corner/rbac/rbac_segregation_of_duties_reimbursement_decide_by_submitter
        """
        env = setup_delivered_order(order_overrides=dict(ORDER_OVERRIDES), restock_units=5)
        claim = get_success_data(
            api.create_reimbursement_claim(
                {
                    "patient_id": env["patient"]["id"],
                    "subject_kind": "DEVICE_ORDER",
                    "device_order_id": env["order"]["id"],
                    "claimed_amount_cents": 80000,
                    "document_codes": ["INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT", "LMN"],
                    "insurance_benefit_cap_cents": 50000,
                    "insurance_benefit_used_cents": 0,
                    "fsa_balance_cents": 20000,
                },
                REIMBURSEMENT,
            )
        )
        get_success_data(api.submit_reimbursement_claim(claim["id"], REIMBURSEMENT))
        get_success_data(api.start_reimbursement_review(claim["id"], REIMBURSEMENT))

        denied = api.decide_reimbursement_claim(claim["id"], {"decision": "APPROVE"}, REIMBURSEMENT)
        validate_error(denied, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        undecided = validate_success(api.get_reimbursement_claim(claim["id"], REIMBURSEMENT))
        assert undecided["status"] == "UNDER_REVIEW", (
            f"the refused decision must leave the claim under review, got {undecided['status']}"
        )
        assert undecided["submitted_by_user_id"] == REIMBURSEMENT["X-User-ID"], (
            "the submitting operator identity is the one being excluded, "
            f"got {undecided['submitted_by_user_id']}"
        )
        assert undecided["approved_by_user_id"] is None, (
            f"no approver may have been recorded, got {undecided['approved_by_user_id']}"
        )

        approved = validate_success(
            api.decide_reimbursement_claim(claim["id"], {"decision": "APPROVE"}, REIMBURSEMENT_2)
        )
        assert approved["status"] == "APPROVED", (
            f"a second specialist approves the identical payload, got {approved['status']}"
        )
        assert approved["approved_by_user_id"] == REIMBURSEMENT_2["X-User-ID"], (
            f"the approving identity must be recorded, got {approved['approved_by_user_id']}"
        )

    def test_filing_officer_cannot_approve_own_compliance_override(self, api):
        """PRD §2.10: "First, a medical-disqualification override is dual-control: the `ComplianceOfficer` whose `X-User-ID` is recorded as `filed_by_user_id` cannot be the one whose `X-User-ID` would be recorded as `approved_by_user_id`, on either the approve or the reject path."
        PRD §2.9: "8. Segregation of duties on approval: the approving `X-User-ID` differs from `ReimbursementClaim.submitted_by_user_id`, and the approving `ComplianceOfficer`'s `X-User-ID` differs from the `filed_by_user_id` of the compliance override. This applies to `POST /reimbursement-claims/{id}/decide` and `POST /patients/{patient_id}/compliance-overrides/{override_id}/approve` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
        PRD §3.3: "A **different** compliance officer then approves it: approval requires the override to be `PENDING`, the acting operator identity to differ from `filed_by_user_id`, and the patient still to be `MEDICALLY_DISQUALIFIED`. Approval moves the override `PENDING → APPROVED`, records `approved_by_user_id` and `decided_at`, moves the patient `MEDICALLY_DISQUALIFIED → SCREENING_IN_PROGRESS`"

        Design: Corner/rbac/rbac_segregation_of_duties_compliance_override_approve_by_filer
        """
        env = setup_evaluated_referral(
            symptom_codes=("VERTIGO",),
            provider_overrides={"npi": "1000000009", "full_name": "Aud SoD"},
        )
        patient_id = env["patient"]["id"]
        clear_referral(env, outcome="NOT_CLEARED", note="retrocochlear suspicion")

        disqualified = validate_success(api.get_patient(patient_id, CARE_OPS))
        assert disqualified["status"] == "MEDICALLY_DISQUALIFIED", (
            f"a NOT_CLEARED determination disqualifies the patient, got {disqualified['status']}"
        )

        override = file_compliance_override(patient_id, "second opinion on file for audit")
        assert override["filed_by_user_id"] == COMPLIANCE["X-User-ID"], (
            f"the filing officer identity must be recorded, got {override['filed_by_user_id']}"
        )

        denied = api.approve_compliance_override(patient_id, override["id"], COMPLIANCE)
        validate_error(denied, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        rows, meta = validate_paginated(
            api.list_compliance_overrides(patient_id, COMPLIANCE, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1, (
            f"exactly the one filed override may exist, got total_count {meta['total_count']}"
        )
        assert rows[0]["status"] == "PENDING", (
            f"the self-approval must leave the override PENDING, got {rows[0]['status']}"
        )
        assert rows[0]["approved_by_user_id"] is None, (
            f"no approver may have been recorded, got {rows[0]['approved_by_user_id']}"
        )
        still_held = validate_success(api.get_patient(patient_id, CARE_OPS))
        assert still_held["status"] == "MEDICALLY_DISQUALIFIED", (
            "the patient stays disqualified until a second officer signs, "
            f"got {still_held['status']}"
        )

        approved = validate_success(
            api.approve_compliance_override(patient_id, override["id"], COMPLIANCE_2)
        )
        assert approved["status"] == "APPROVED", (
            f"a different compliance officer completes the dual control, got {approved['status']}"
        )
        assert approved["approved_by_user_id"] == COMPLIANCE_2["X-User-ID"], (
            f"the approving officer identity must be recorded, got {approved['approved_by_user_id']}"
        )
        released = validate_success(api.get_patient(patient_id, CARE_OPS))
        assert released["status"] == "SCREENING_IN_PROGRESS", (
            f"approval re-admits the patient to screening, got {released['status']}"
        )


class TestAuthorizationBandOrdering:
    """The authorization band answers before the existence band, so an unauthorized
    role learns nothing about which ids exist."""

    def test_unauthorized_role_on_missing_order_is_denied_not_not_found(self, api):
        """PRD §2.9: "When a single request violates more than one rule, the rule with the lowest priority number below wins and its error is the one returned."
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §2.9: "10. Every path-segment resource exists, validated left to right, on every endpoint with path parameters — otherwise `ERR_RESOURCE_NOT_FOUND` (404)."
        PRD §4: "| POST | `/hearing-care/device-orders/{id}/confirm-fit` | Clear the order for shipment: reserves inventory and assigns a device | `CareOpsAgent` |"

        Design: Corner/rbac/rbac_role_check_precedes_resource_not_found
        """
        set_clock(CLOCK_START_UTC)
        fitter = _onboard_provider(api, "1000000011", full_name="Fitter Probe")

        denied = api.confirm_fit(
            NON_EXISTENT_ORDER_ID, make_hearing_professional_headers(fitter["id"])
        )
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        missing = api.confirm_fit(NON_EXISTENT_ORDER_ID, CARE_OPS)
        validate_error(missing, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


class TestSharedReads:
    """A read shared by several roles serves them all the same body, and denies the rest."""

    def test_order_summary_is_shared_by_its_four_declared_roles_only(self, api):
        """PRD §4: "| GET | `/hearing-care/device-orders/{id}/summary` | Computed read: cash conservation breakdown, trial position and fit-exchange history | `Patient`, `CareOpsAgent`, `ComplianceOfficer`, `PlatformAdmin` |"
        PRD §2.9: "4. The acting role appears in the endpoint's authorized-role list in §4, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
        PRD §3.5: "It moves fulfillment `READY_TO_SHIP → SHIPPED` and payment `AUTHORIZED → CAPTURED`, sets `captured_cents` to `total_cents` with `refunded_cents` and `retained_cents` at 0 and `open_balance_cents` equal to `total_cents`"

        Design: Corner/rbac/rbac_shared_read_order_summary_permitted_for_declared_roles_only
        """
        env = setup_delivered_order(order_overrides=dict(ORDER_OVERRIDES), restock_units=5)
        order_id = env["order"]["id"]
        patient_headers = make_patient_headers(env["patient"]["id"])
        fitter = _onboard_provider(api, "1000000012", full_name="Fitter Reader")

        denied = api.get_device_order_summary(order_id, make_hearing_professional_headers(fitter["id"]))
        validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        bodies = {
            role_name: validate_success(api.get_device_order_summary(order_id, headers))
            for role_name, headers in (
                ("Patient", patient_headers),
                ("CareOpsAgent", CARE_OPS),
                ("ComplianceOfficer", COMPLIANCE),
                ("PlatformAdmin", ADMIN),
            )
        }
        reference = bodies["Patient"]
        for role_name, body in bodies.items():
            assert body == reference, (
                f"every declared role reads the identical summary body; {role_name} differed"
            )

        order = validate_success(api.get_device_order(order_id, CARE_OPS))
        assert order["total_cents"] == 215995, (
            f"the canonical order totals 215995 cents, got {order['total_cents']}"
        )
        assert order["captured_cents"] == 215995, (
            f"shipping captured the whole total of 215995 cents, got {order['captured_cents']}"
        )
