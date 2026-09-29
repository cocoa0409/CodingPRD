"""Professional gear, storage in transit, claims and personally procured packets."""

import pytest

from test_helpers import (
    ADMIN_ALT,
    COUNSELOR,
    COUNSELOR_USER_ID,
    EXAMINER,
    EXAMINER_ALT,
    EXAMINER_USER_ID,
    EXAMINER_ALT_USER_ID,
    ApiErrorId,
    api_client,
    authorize_sit,
    award_shipment,
    capacity_block_version,
    create_capacity_block,
    create_claim_item_payload,
    create_claim_payload,
    create_ppm_payload,
    create_sit_payload,
    declare_pro_gear,
    deliver_shipment,
    deny_claim_payload,
    disposition_claim_item_payload,
    excess_cost_waiver_payload,
    extend_sit_payload,
    get_success_data,
    pack_shipment,
    pickup_shipment,
    read_capacity_block,
    read_claim,
    read_entitlement,
    read_shipment,
    read_sit,
    read_tsp,
    record_actual_weight,
    record_actual_weight_payload,
    reject_pro_gear_payload,
    release_sit,
    release_sit_payload,
    request_sit,
    resubmit_pro_gear_payload,
    resume_entitlement_payload,
    review_claim_payload,
    set_clock,
    settle_claim_payload,
    setup_picked_up_shipment,
    setup_second_shipment,
    setup_surveyed_shipment,
    setup_delivered_shipment,
    survey_shipment,
    trip_ticket,
    validate_error,
    validate_paginated,
    validate_success,
    verify_pro_gear,
    verify_pro_gear_payload,
)

WEIGH_DATE = "2026-08-17T00:00:00Z"
PICKUP_DATE = "2026-08-17T00:00:00Z"
STORAGE_ENTRY = "2026-08-17T00:00:00Z"
STORAGE_RELEASE = "2026-08-22T00:00:00Z"
FILING_CLOCK = "2026-09-01T00:00:00Z"
NOTICE_DATE = "2026-08-25T00:00:00Z"
E5_ALONE = {"rank_code": "E5", "dependents_count": 0, "spouse_present": False}


def _surveyed_move_with_a_member_declaration(documentation_type):
    """A surveyed 5,286 pound move carrying one 1,200 pound member declaration."""
    scenario = setup_surveyed_shipment()
    scenario["pro_gear"] = declare_pro_gear(
        scenario,
        owner="MEMBER",
        claimed_weight_lbs=1200,
        documentation_type=documentation_type,
    )
    return scenario


def _reject(declaration_id, rejection_reason):
    return get_success_data(
        api_client.reject_pro_gear_declaration(
            declaration_id, reject_pro_gear_payload(rejection_reason), COUNSELOR
        )
    )


def _resubmit(declaration_id, documentation_type):
    return api_client.resubmit_pro_gear_declaration(
        declaration_id,
        resubmit_pro_gear_payload(
            claimed_weight_lbs=1200, documentation_type=documentation_type
        ),
        COUNSELOR,
    )


def _read_declaration(declaration_id):
    return get_success_data(
        api_client.get_pro_gear_declaration(declaration_id, COUNSELOR)
    )


def _picked_up_move():
    """A 4,700 pound shipment weighed and collected on 17 August."""
    return setup_picked_up_shipment(
        weigh_date=WEIGH_DATE, actual_pickup_date=PICKUP_DATE
    )


def _notifications(shipment_id, notification_type):
    return validate_paginated(
        api_client.list_shipment_notifications(
            shipment_id, COUNSELOR, params={"notification_type": notification_type}
        )
    )


def _delivered_move_with_a_draft_claim(claim_type):
    """A move delivered on 20 August with a draft claim opened on 1 September."""
    scenario = setup_delivered_shipment(
        weigh_date=WEIGH_DATE, actual_pickup_date=PICKUP_DATE
    )
    set_clock(FILING_CLOCK)
    scenario["claim"] = get_success_data(
        api_client.create_claim(
            scenario["shipment"]["id"],
            create_claim_payload(NOTICE_DATE, claim_type=claim_type),
            COUNSELOR,
        )
    )
    return scenario


def _add_television(claim_id):
    return api_client.create_claim_item(
        claim_id,
        create_claim_item_payload(
            4200.00,
            category="ELECTRONICS",
            age_years=3.0,
            item_description="FLAT PANEL TELEVISION",
        ),
        COUNSELOR,
    )


def _submit(claim_id):
    return api_client.submit_claim(claim_id, {"filing_note": "FILED"}, COUNSELOR)


def _ppm_packet_beside_a_surveyed_move():
    """A surveyed 5,286 pound move plus a delivered self-hauled shipment of 7,200 pounds."""
    scenario = setup_surveyed_shipment()
    scenario["charged_before"] = read_entitlement(scenario["entitlement"]["id"])[
        "charged_billable_weight_lbs"
    ]

    ppm = setup_second_shipment(
        scenario,
        shipment_code="SHP-C02",
        shipment_method="PPM",
        requested_pack_date="2026-08-16T00:00:00Z",
        requested_pickup_date="2026-08-19T00:00:00Z",
        requested_delivery_date="2026-08-26T00:00:00Z",
    )
    ppm = survey_shipment(
        scenario,
        shipment_id=ppm["id"],
        room_estimates=[{"room_name": "SELF_HAULED_LOT", "cube_feet": 40.0}],
    )

    block = create_capacity_block(scenario["tsp"]["id"])
    award_shipment(block["id"], scenario["shipment"]["id"])
    award_shipment(block["id"], ppm["id"], capacity_block_version(block["id"]))

    pack_shipment(scenario, pack_date="2026-08-17T00:00:00Z", shipment_id=ppm["id"])
    record_actual_weight(
        scenario, 6000, 4000, weigh_date="2026-08-19T00:00:00Z", shipment_id=ppm["id"]
    )
    pickup_shipment(
        scenario, actual_pickup_date="2026-08-19T00:00:00Z", shipment_id=ppm["id"]
    )
    deliver_shipment(
        scenario, delivery_date="2026-08-22T00:00:00Z", shipment_id=ppm["id"]
    )

    scenario["ppm_shipment"] = read_shipment(ppm["id"])
    scenario["ppm"] = get_success_data(
        api_client.create_ppm_submission(
            ppm["id"],
            create_ppm_payload(
                trip_tickets=[trip_ticket(1, 9200, 5400), trip_ticket(2, 8600, 5200)]
            ),
            COUNSELOR,
        )
    )
    return scenario


def _approve_packet(ppm_id, approval_note):
    return api_client.approve_ppm_submission(
        ppm_id, {"approval_note": approval_note}, COUNSELOR
    )


class TestProfessionalGearDeclarationLifecycle:
    """Rejection, the bounded revision loop, and what verification does to the ledger."""

    def test_a_rejected_declaration_cannot_then_be_verified(self):
        """The counselor's rejection is final for that filing, and the pounds stay charged.

        "Rejection is the counselor's other exclusive option. It moves
        `SUBMITTED → REJECTED`, stores the supplied `rejection_reason` and stamps
        `verified_by_user_id`, leaves `verified_weight_lbs` at 0"

        "both require the declaration to be `SUBMITTED` (else
        `ERR_INVALID_PRO_GEAR_STATE`)"

        "Declarations that are `SUBMITTED` or `REJECTED` contribute zero."

        Design: Corner/state_machines/pro_gear_verify_after_rejection_is_refused
        """
        scenario = _surveyed_move_with_a_member_declaration("ITEMIZED_INVENTORY")
        declaration_id = scenario["pro_gear"]["id"]
        _reject(declaration_id, "INVENTORY NOT ITEMISED BY PIECE")

        validate_error(
            api_client.verify_pro_gear_declaration(
                declaration_id, verify_pro_gear_payload(1200), COUNSELOR
            ),
            ApiErrorId.ERR_INVALID_PRO_GEAR_STATE.value,
            409,
        )

        stored = _read_declaration(declaration_id)
        assert stored["status"] == "REJECTED"
        assert stored["verified_weight_lbs"] == 0
        assert stored["rejection_reason"] == "INVENTORY NOT ITEMISED BY PIECE"

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["pro_gear_excluded_lbs"] == 0
        assert shipment["billable_weight_lbs"] == 5286

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["pro_gear_excluded_total_lbs"] == 0
        assert entitlement["charged_billable_weight_lbs"] == 5286

    def test_the_revision_loop_stops_after_two_resubmissions(self):
        """Two rounds of better paperwork are allowed; the third attempt is turned away.

        "both require `documentation_type` to be anything other than `NONE` (else
        `ERR_PRO_GEAR_DOCUMENTATION_REQUIRED`)"

        "A member may then resubmit with a better `claimed_weight_lbs` and
        `documentation_type`, which moves the declaration `REJECTED → SUBMITTED`, replaces
        both values, increments `resubmission_count` and clears `rejection_reason` to null.
        This revision loop is bounded: with `resubmission_count` already at 2, a further
        attempt is refused with `ERR_PRO_GEAR_RESUBMISSION_LIMIT`."

        Design: Corner/state_machines/pro_gear_third_resubmission_hits_the_resubmission_limit
        """
        scenario = _surveyed_move_with_a_member_declaration("NONE")
        declaration_id = scenario["pro_gear"]["id"]

        validate_error(
            api_client.verify_pro_gear_declaration(
                declaration_id, verify_pro_gear_payload(1200), COUNSELOR
            ),
            ApiErrorId.ERR_PRO_GEAR_DOCUMENTATION_REQUIRED.value,
            422,
        )
        assert _read_declaration(declaration_id)["status"] == "SUBMITTED"

        _reject(declaration_id, "NO DOCUMENTATION")
        first = validate_success(_resubmit(declaration_id, "NONE"), 200)
        assert first["status"] == "SUBMITTED"
        assert first["resubmission_count"] == 1
        assert first["rejection_reason"] is None

        _reject(declaration_id, "STILL NO DOCUMENTATION")
        second = validate_success(_resubmit(declaration_id, "EMPLOYER_LETTER"), 200)
        assert second["resubmission_count"] == 2
        assert second["documentation_type"] == "EMPLOYER_LETTER"

        _reject(declaration_id, "LETTER UNSIGNED")
        validate_error(
            _resubmit(declaration_id, "ORDERS_EXTRACT"),
            ApiErrorId.ERR_PRO_GEAR_RESUBMISSION_LIMIT.value,
            409,
        )

        stored = _read_declaration(declaration_id)
        assert stored["status"] == "REJECTED"
        assert stored["resubmission_count"] == 2
        assert stored["documentation_type"] == "EMPLOYER_LETTER"

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["pro_gear_excluded_lbs"] == 0
        assert shipment["billable_weight_lbs"] == 5286

    def test_verifying_gear_lifts_the_excluded_pounds_off_the_ledger(self):
        """1,200 member pounds and 400 spouse pounds come off a 5,286 pound estimate.

        "When the verified figure equals `claimed_weight_lbs`, the declaration moves
        `SUBMITTED → VERIFIED`; when it is greater than zero but strictly less than the
        claimed figure, it moves `SUBMITTED → PARTIALLY_VERIFIED`."

        "Both branches store `verified_weight_lbs` and stamp `verified_by_user_id` from
        `X-User-ID`, both recompute the shipment's `pro_gear_excluded_lbs` and
        `billable_weight_lbs` under whatever basis is currently in force, and both then
        recompute the owning entitlement's `charged_billable_weight_lbs`,
        `pro_gear_excluded_total_lbs`, `excess_weight_lbs`, `gross_excess_cost_usd` and
        `excess_cost_due_usd`."

        Design: Corner/state_machines/pro_gear_verification_reduces_billable_weight_and_the_ledger
        """
        scenario = setup_surveyed_shipment()
        member_declaration = declare_pro_gear(
            scenario,
            owner="MEMBER",
            claimed_weight_lbs=1200,
            documentation_type="ITEMIZED_INVENTORY",
        )
        spouse_declaration = declare_pro_gear(
            scenario,
            owner="SPOUSE",
            claimed_weight_lbs=600,
            documentation_type="EMPLOYER_LETTER",
            item_description="SPOUSE TRADE TOOLS",
        )

        verified = verify_pro_gear(member_declaration["id"], 1200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_weight_lbs"] == 1200
        assert verified["verified_by_user_id"] == COUNSELOR_USER_ID

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["pro_gear_excluded_lbs"] == 1200
        assert shipment["billable_weight_lbs"] == 4086
        assert shipment["billable_basis"] == "ESTIMATED"

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 4086
        assert entitlement["pro_gear_excluded_total_lbs"] == 1200
        assert entitlement["excess_weight_lbs"] == 0
        assert entitlement["gross_excess_cost_usd"] == pytest.approx(0.00, abs=0.01)

        partial = verify_pro_gear(spouse_declaration["id"], 400)
        assert partial["status"] == "PARTIALLY_VERIFIED"
        assert partial["verified_weight_lbs"] == 400

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["pro_gear_excluded_lbs"] == 1600
        assert shipment["billable_weight_lbs"] == 3686

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 3686
        assert entitlement["pro_gear_excluded_total_lbs"] == 1600
        assert entitlement["excess_weight_lbs"] == 0
        assert entitlement["gross_excess_cost_usd"] == pytest.approx(0.00, abs=0.01)


class TestStorageInTransitLifecycle:
    """A stay that is authorized, priced on release, and the guards that refuse the rest."""

    def test_authorizing_and_releasing_storage_prices_a_five_day_stay(self):
        """Five stored days on 4,700 pounds cost 3,461.55 plus a 214.62 fuel surcharge.

        "Authorizing storage is a counselor or program-office action that moves the
        authorization `REQUESTED → AUTHORIZED` and, in the same breath, the shipment
        `PICKED_UP → IN_SIT`."

        "One `PENDING` notification obligation of type `SIT_ENTRY` is created."

        "one day (24 hours) for both `PICKUP_CONFIRMED` and `SIT_ENTRY`"

        "First, `days_used` is the count of whole days from `entry_date` to `release_date`,
        discarding any partial day, but never fewer than one day — a same-day stay still
        bills a day. `excess_days` is `days_used` less `total_authorized_days`, floored at
        zero."

        "the rate is 0.045 when the base is below 1,000.00 US dollars, 0.062 when the base
        is below 5,000.00, and 0.071 when the base is 5,000.00 or more"

        "Finally `member_liability_usd` is 0.00 when `excess_days` is zero"

        Design: Corner/state_machines/sit_authorization_and_release_move_the_shipment_and_price_storage
        """
        scenario = _picked_up_move()
        requested = request_sit(
            scenario, STORAGE_ENTRY, requested_days=10, sit_type="DESTINATION"
        )

        authorized = authorize_sit(requested["id"], 10)
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["authorized_days"] == 10
        assert authorized["total_authorized_days"] == 10

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["movement_status"] == "IN_SIT"
        assert shipment["weight_recon_status"] == "ACTUAL_RECORDED"

        rows, meta = _notifications(scenario["shipment"]["id"], "SIT_ENTRY")
        assert meta["total_count"] == 1
        assert rows[0]["notification_type"] == "SIT_ENTRY"
        assert rows[0]["sla_hours"] == 24
        assert rows[0]["due_by"] == "2026-08-04T00:00:00Z"
        assert rows[0]["status"] == "PENDING"

        released = release_sit(scenario, requested["id"], STORAGE_RELEASE)
        assert released["status"] == "RELEASED"
        assert released["days_used"] == 5
        assert released["excess_days"] == 0
        assert released["sit_base_cost_usd"] == pytest.approx(3461.55, abs=0.01)
        assert released["fuel_surcharge_pct"] == pytest.approx(0.062, abs=0.0001)
        assert released["fuel_surcharge_usd"] == pytest.approx(214.62, abs=0.01)
        assert released["sit_total_cost_usd"] == pytest.approx(3676.17, abs=0.01)
        assert released["member_liability_usd"] == pytest.approx(0.00, abs=0.01)

        assert read_shipment(scenario["shipment"]["id"])["movement_status"] == "PICKED_UP"

    def test_out_of_order_storage_requests_are_each_refused_in_turn(self):
        """Entry before pickup, release before authorization, 100 days and a backdated release.

        "The entry date may not precede the shipment's `actual_pickup_date`, on pain of
        `ERR_SIT_ENTRY_BEFORE_PICKUP`."

        "A new request is `REQUESTED` with `authorized_days` 0, `extension_days` 0,
        `total_authorized_days` 0, `release_date` null, and every cost figure at 0.00."

        "The ceiling is absolute: an authorization or extension that would carry
        `authorized_days` plus `extension_days` above 90 days is refused with
        `ERR_SIT_MAX_DAYS_EXCEEDED`."

        "The supplied `release_date` must not precede `entry_date`, on pain of
        `ERR_RELEASE_BEFORE_ENTRY`, and the authorization must be `AUTHORIZED`."

        Design: Corner/state_machines/sit_state_and_temporal_guards_refuse_out_of_order_storage
        """
        scenario = _picked_up_move()
        shipment_id = scenario["shipment"]["id"]

        validate_error(
            api_client.create_sit_authorization(
                shipment_id,
                create_sit_payload(
                    "2026-08-16T00:00:00Z", requested_days=10, sit_type="ORIGIN"
                ),
                scenario["tsp_headers"],
            ),
            ApiErrorId.ERR_SIT_ENTRY_BEFORE_PICKUP.value,
            422,
        )
        _, empty_meta = validate_paginated(
            api_client.list_shipment_sit_authorizations(
                shipment_id, scenario["tsp_headers"]
            )
        )
        assert empty_meta["total_count"] == 0

        requested = validate_success(
            api_client.create_sit_authorization(
                shipment_id,
                create_sit_payload(
                    STORAGE_ENTRY, requested_days=60, sit_type="DESTINATION"
                ),
                scenario["tsp_headers"],
            ),
            201,
        )
        assert requested["status"] == "REQUESTED"
        assert requested["requested_days"] == 60
        assert requested["authorized_days"] == 0
        assert requested["total_authorized_days"] == 0
        sit_id = requested["id"]

        validate_error(
            api_client.release_sit(
                sit_id, release_sit_payload(STORAGE_RELEASE), scenario["tsp_headers"]
            ),
            ApiErrorId.ERR_INVALID_SIT_STATE.value,
            409,
        )
        assert read_shipment(shipment_id)["movement_status"] == "PICKED_UP"

        authorized = authorize_sit(sit_id, 60)
        assert authorized["total_authorized_days"] == 60
        assert read_shipment(shipment_id)["movement_status"] == "IN_SIT"

        validate_error(
            api_client.extend_sit(sit_id, extend_sit_payload(40), COUNSELOR),
            ApiErrorId.ERR_SIT_MAX_DAYS_EXCEEDED.value,
            422,
        )
        held = read_sit(sit_id)
        assert held["extension_days"] == 0
        assert held["total_authorized_days"] == 60

        extended = validate_success(
            api_client.extend_sit(sit_id, extend_sit_payload(30), COUNSELOR), 200
        )
        assert extended["extension_days"] == 30
        assert extended["total_authorized_days"] == 90

        validate_error(
            api_client.release_sit(
                sit_id,
                release_sit_payload("2026-08-16T00:00:00Z"),
                scenario["tsp_headers"],
            ),
            ApiErrorId.ERR_RELEASE_BEFORE_ENTRY.value,
            422,
        )
        stored = read_sit(sit_id)
        assert stored["status"] == "AUTHORIZED"
        assert stored["release_date"] is None

        _, meta = validate_paginated(
            api_client.list_shipment_sit_authorizations(
                shipment_id, scenario["tsp_headers"]
            )
        )
        assert meta["total_count"] == 1


class TestClaimAdjudicationOutcomes:
    """The guards on the way to a settlement, and the denial that pays nothing."""

    def test_the_claim_guards_fire_in_order_up_to_a_full_settlement(self):
        """A premature review, an empty filing and a pending item are each refused first.

        "the claim must hold at least one item (an empty claim is refused with
        `ERR_CLAIM_ITEM_REQUIRED`)"

        "at most 270 days — filing within nine months of delivery, boundary inclusive —
        earns `FULL_REPLACEMENT_VALUE`"

        "Taking a claim under review moves it `SUBMITTED → UNDER_REVIEW`, may carry a
        `review_note`, and stamps `reviewed_by_user_id` from `X-User-ID`"

        "requires that no item of the claim is still `PENDING` (otherwise
        `ERR_CLAIM_ITEM_PENDING`), requires the acting `X-User-ID` to differ from
        `reviewed_by_user_id`, and stamps `settled_by_user_id`"

        "deduct 5.00 points for each settled claim counted against the provider, deduct a
        further point for every 500.00 US dollars of cumulative settlement"

        Design: Corner/state_machines/claim_review_and_settlement_guards_run_in_priority_order
        """
        scenario = _delivered_move_with_a_draft_claim("DAMAGE")
        claim_id = scenario["claim"]["id"]

        validate_error(
            api_client.review_claim(
                claim_id, review_claim_payload(review_note="PREMATURE"), EXAMINER
            ),
            ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
            409,
        )
        assert read_claim(claim_id)["reviewed_by_user_id"] is None

        validate_error(
            _submit(claim_id), ApiErrorId.ERR_CLAIM_ITEM_REQUIRED.value, 422
        )
        assert read_claim(claim_id)["status"] == "DRAFT"

        item = validate_success(_add_television(claim_id), 201)
        assert item["disposition"] == "PENDING"
        assert item["depreciation_rate_pct_per_year"] == pytest.approx(0.10, abs=0.0001)
        assert item["item_settlement_usd"] == pytest.approx(0.00, abs=0.01)

        filed = validate_success(_submit(claim_id), 200)
        assert filed["status"] == "SUBMITTED"
        assert filed["filed_date"] == FILING_CLOCK
        assert filed["filing_window_days"] == 12
        assert filed["settlement_basis"] == "FULL_REPLACEMENT_VALUE"
        assert filed["claimed_total_usd"] == pytest.approx(4200.00, abs=0.01)
        assert filed["item_count"] == 1

        rows, meta = _notifications(scenario["shipment"]["id"], "CLAIM_ACK")
        assert meta["total_count"] == 1
        assert rows[0]["sla_hours"] == 120

        reviewed = validate_success(
            api_client.review_claim(
                claim_id,
                review_claim_payload(review_note="INSPECTION COMPLETE"),
                EXAMINER,
            ),
            200,
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["reviewed_by_user_id"] == EXAMINER_USER_ID

        validate_error(
            api_client.settle_claim(
                claim_id, settle_claim_payload(settlement_note="TOO EARLY"), EXAMINER_ALT
            ),
            ApiErrorId.ERR_CLAIM_ITEM_PENDING.value,
            409,
        )
        assert read_claim(claim_id)["settlement_total_usd"] == pytest.approx(
            0.00, abs=0.01
        )

        validate_success(
            api_client.disposition_claim_item(
                item["id"],
                disposition_claim_item_payload(
                    "ALLOWED", adjudication_note="DAMAGE CONFIRMED"
                ),
                EXAMINER,
            ),
            200,
        )

        settled = validate_success(
            api_client.settle_claim(
                claim_id,
                settle_claim_payload(settlement_note="PAID AT FRV"),
                EXAMINER_ALT,
            ),
            200,
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_by_user_id"] == EXAMINER_ALT_USER_ID
        assert settled["settlement_total_usd"] == pytest.approx(4200.00, abs=0.01)

        stored_item = get_success_data(api_client.get_claim_item(item["id"], EXAMINER))
        assert stored_item["item_settlement_usd"] == pytest.approx(4200.00, abs=0.01)

        provider = read_tsp(scenario["tsp"]["id"])
        assert provider["settled_claim_count"] == 1
        assert provider["performance_score"] == pytest.approx(86.60, abs=0.01)
        assert provider["status"] == "ACTIVE"

    def test_a_denied_claim_pays_nothing_and_leaves_the_score_alone(self):
        """The provider keeps its perfect score, and the denied claim cannot be reopened.

        "**Denial** moves the claim `UNDER_REVIEW → DENIED`, stores the supplied
        `denial_reason`, leaves `settlement_total_usd` at 0.00, and — importantly — touches
        no provider performance figure at all: denied claims never affect a provider's
        score."

        "Both `SETTLED` and `DENIED` are terminal."

        "Only `SETTLED` claims enter that computation; `DRAFT`, `SUBMITTED`,
        `UNDER_REVIEW`, `INFO_REQUESTED` and `DENIED` claims never do."

        Design: Corner/state_machines/claim_denial_leaves_tsp_performance_untouched
        """
        scenario = _delivered_move_with_a_draft_claim("LOSS")
        claim_id = scenario["claim"]["id"]
        item = validate_success(_add_television(claim_id), 201)
        validate_success(_submit(claim_id), 200)
        validate_success(
            api_client.review_claim(
                claim_id,
                review_claim_payload(review_note="INSPECTION COMPLETE"),
                EXAMINER,
            ),
            200,
        )

        denied = validate_success(
            api_client.deny_claim(
                claim_id,
                deny_claim_payload(
                    denial_reason="ITEM RECOVERED AND RETURNED TO MEMBER"
                ),
                EXAMINER_ALT,
            ),
            200,
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "ITEM RECOVERED AND RETURNED TO MEMBER"
        assert denied["settlement_total_usd"] == pytest.approx(0.00, abs=0.01)

        stored_item = get_success_data(api_client.get_claim_item(item["id"], EXAMINER))
        assert stored_item["disposition"] == "PENDING"
        assert stored_item["item_settlement_usd"] == pytest.approx(0.00, abs=0.01)

        provider = read_tsp(scenario["tsp"]["id"])
        assert provider["settled_claim_count"] == 0
        assert provider["claim_settlement_total_usd"] == pytest.approx(0.00, abs=0.01)
        assert provider["performance_score"] == pytest.approx(100.00, abs=0.01)
        assert provider["status"] == "ACTIVE"

        validate_error(
            api_client.settle_claim(
                claim_id,
                settle_claim_payload(settlement_note="REOPEN ATTEMPT"),
                EXAMINER_ALT,
            ),
            ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
            409,
        )
        assert read_capacity_block(scenario["block"]["id"])["status"] == "OPEN"


class TestPacketApprovalAndSuspensionRecovery:
    """A clamped personally procured payment, and a suspension lifted by a full waiver."""

    def test_the_packet_is_paid_only_for_the_room_left_on_the_cap(self):
        """7,200 hauled pounds are clamped to the 5,714 the 11,000 pound cap still allows.

        "Sum `billable_weight_lbs` over every **other** shipment of the same entitlement
        that is inside the inclusion set of §2.8; subtract that sum from
        `total_billable_cap_lbs` and floor the result at zero. `allowable_weight_lbs` is the
        lesser of `moved_weight_lbs` and that remaining room."

        "`gcc_usd`, the government constructed cost, is `allowable_weight_lbs` expressed in
        hundredweight, multiplied by a rate made of a base of 42.75 US dollars per
        hundredweight plus 3.85 US dollars per hundredweight for each hundred miles of the
        orders' `distance_miles`, with the product rounded half up to cents. From it,
        `incentive_usd` is 95 percent of `gcc_usd`, rounded half up to cents."

        "The shipment's `billable_weight_lbs` is set to `allowable_weight_lbs`, its
        `billable_basis` to `ACTUAL`, and its `weight_recon_status` moves
        `ESTIMATED → ACTUAL_RECORDED`"

        "a packet that is not `SUBMITTED` draws `ERR_INVALID_PPM_STATE`"

        Design: Corner/state_machines/ppm_approval_clamps_to_entitlement_room_and_second_approve_is_refused
        """
        scenario = _ppm_packet_beside_a_surveyed_move()
        packet_id = scenario["ppm"]["id"]
        assert scenario["charged_before"] == 5286

        approved = validate_success(_approve_packet(packet_id, "TICKETS VERIFIED"), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == COUNSELOR_USER_ID
        assert approved["moved_weight_lbs"] == 7200
        assert approved["allowable_weight_lbs"] == 5714
        assert approved["gcc_usd"] == pytest.approx(5082.60, abs=0.01)
        assert approved["incentive_usd"] == pytest.approx(4828.47, abs=0.01)
        assert approved["applied_basis"] == "INCENTIVE_BASIS"
        assert approved["reimbursement_usd"] == pytest.approx(4828.47, abs=0.01)
        assert approved["net_payable_usd"] == pytest.approx(4828.47, abs=0.01)
        assert approved["debt_owed_usd"] == pytest.approx(0.00, abs=0.01)
        assert approved["taxable_amount_usd"] == pytest.approx(4828.47, abs=0.01)

        hauled = read_shipment(scenario["ppm_shipment"]["id"])
        assert hauled["billable_weight_lbs"] == 5714
        assert hauled["billable_basis"] == "ACTUAL"
        assert hauled["weight_recon_status"] == "ACTUAL_RECORDED"

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 11000
        assert entitlement["excess_weight_lbs"] == 0

        validate_error(
            _approve_packet(packet_id, "SECOND ATTEMPT"),
            ApiErrorId.ERR_INVALID_PPM_STATE.value,
            409,
        )
        unchanged = get_success_data(
            api_client.get_ppm_submission(packet_id, COUNSELOR)
        )
        assert unchanged["status"] == "APPROVED"
        assert unchanged["allowable_weight_lbs"] == 5714
        assert unchanged["net_payable_usd"] == pytest.approx(4828.47, abs=0.01)

    def test_a_waiver_covering_the_whole_debt_lets_the_ledger_resume(self):
        """3,005.10 forgiven in full is what makes the resumption lawful.

        "Each tier publishes two allowances in pounds, the first for a move without
        dependents and the second for a move with them"

        "beyond one quarter it is 94.50"

        "The administrative fee, surfaced as `admin_fee_usd`, is zero when that
        transportation charge is below 500.00 US dollars, and otherwise six percent of the
        transportation charge rounded half up to cents"

        "the amount may not exceed the `excess_cost_due_usd` currently outstanding, and a
        larger request is refused with `ERR_WAIVER_EXCEEDS_DUE`"

        "Two conditions apply: the entitlement must currently be `SUSPENDED` (otherwise
        `ERR_INVALID_ENTITLEMENT_STATE`), and `excess_cost_due_usd` must be exactly zero
        (otherwise `ERR_EXCESS_COST_UNPAID`)"

        Design: Corner/state_machines/resume_after_a_full_waiver_lifts_the_suspension
        """
        scenario = setup_surveyed_shipment(
            member_overrides=E5_ALONE, session_overrides={"session_type": "VIRTUAL"}
        )
        entitlement_id = scenario["entitlement"]["id"]
        assert scenario["entitlement"]["total_billable_cap_lbs"] == 7000
        assert scenario["entitlement"]["dependent_status_effective"] == "WITHOUT_DEPENDENTS"

        weighed = validate_success(
            api_client.record_actual_weight(
                scenario["shipment"]["id"],
                record_actual_weight_payload(12000, 2000, WEIGH_DATE),
                scenario["tsp_headers"],
            ),
            200,
        )
        assert weighed["billable_weight_lbs"] == 10000
        assert weighed["billable_basis"] == "ACTUAL"
        assert weighed["reweigh_required"] is True

        suspended = read_entitlement(entitlement_id)
        assert suspended["excess_weight_lbs"] == 3000
        assert suspended["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)
        assert suspended["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "EXCESS_COST_UNPAID"

        validate_error(
            api_client.resume_entitlement(
                entitlement_id,
                resume_entitlement_payload(resume_note="PLEASE LIFT"),
                COUNSELOR,
            ),
            ApiErrorId.ERR_EXCESS_COST_UNPAID.value,
            409,
        )

        validate_error(
            api_client.create_excess_cost_waiver(
                entitlement_id,
                excess_cost_waiver_payload(4000.00, waiver_reason="OVER-SIZED WAIVER"),
                ADMIN_ALT,
            ),
            ApiErrorId.ERR_WAIVER_EXCEEDS_DUE.value,
            422,
        )
        assert read_entitlement(entitlement_id)[
            "excess_cost_waived_usd"
        ] == pytest.approx(0.00, abs=0.01)

        waived = validate_success(
            api_client.create_excess_cost_waiver(
                entitlement_id,
                excess_cost_waiver_payload(
                    3005.10, waiver_reason="MEMBER NOT AT FAULT - TSP OVERPACKED"
                ),
                ADMIN_ALT,
            ),
            200,
        )
        assert waived["excess_cost_waived_usd"] == pytest.approx(3005.10, abs=0.01)
        assert waived["excess_cost_due_usd"] == pytest.approx(0.00, abs=0.01)
        assert waived["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)

        resumed = validate_success(
            api_client.resume_entitlement(
                entitlement_id,
                resume_entitlement_payload(resume_note="WAIVER GRANTED IN FULL"),
                COUNSELOR,
            ),
            200,
        )
        assert resumed["status"] == "AUTHORIZED"
        assert resumed["suspension_reason"] is None
