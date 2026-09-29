"""Validation breadth: the terms-coherence clauses at and outside their legal
extremes, the use and insurance gates re-examined at decision time, the
uniqueness and chronology families, exact-amount reconciliation, the transfer
field-completeness and credit gates, appraisal side matching, the met-standard
holdback refusal, cross-lease mortgage naming and one priority ordering."""

from test_helpers import (
    ERR_AMOUNT_NOT_RECONCILED,
    ERR_APPRAISAL_SIDE_MISMATCH,
    ERR_CHRONOLOGY_VIOLATION,
    ERR_CREDIT_RATING_REFUSED,
    ERR_DUPLICATE_RECORD,
    ERR_GFA_ENVELOPE_EXCEEDED,
    ERR_INSURANCE_DEFICIENT,
    ERR_INVALID_REQUEST,
    ERR_MORTGAGE_LEASE_MISMATCH,
    ERR_STANDARD_MET_NO_HOLDBACK,
    ERR_TERMS_INCOHERENT,
    ERR_TRANSFER_FIELDS_MISMATCHED,
    ERR_USE_NOT_PERMITTED,
    assert_deposit_conserved,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_each_broken_terms_clause_is_refused_and_nothing_is_persisted(api):
    """PRD §3.1: "Four coherence rules are then applied to the terms as a set, and any failure is reported as `ERR_TERMS_INCOHERENT`: `reval_collar_min_uplift_bps` must be **strictly** less than `reval_collar_max_uplift_bps`, `percentage_rent_rate_bps` must fall between 100 and 2,000 basis points inclusive, `expiration_date` must be strictly after `commencement_date`, and `total_permitted_gfa_sqft` must be at least 1."

    Design: Corner/validations/lease_terms_coherence_violations_rejected
    """
    lessee = fx.create_lessee(api)
    admin = make_lessor_admin_headers()

    incoherent = [
        ("PIER-102A", {"reval_collar_min_uplift_bps": 5000,
                       "reval_collar_max_uplift_bps": 1000}),
        ("PIER-102B", {"percentage_rent_rate_bps": 50}),
        ("PIER-102C", {"percentage_rent_rate_bps": 2500}),
        ("PIER-102D", {"expiration_date": "2020-01-01T00:00:00Z"}),
        ("PIER-102E", {"total_permitted_gfa_sqft": 0}),
    ]
    for premises_code, overrides in incoherent:
        validate_error(
            api.create_lease(
                f.lease_payload(lessee["id"], premises_code, **overrides), admin
            ),
            ERR_TERMS_INCOHERENT,
            expected_status=422,
        )

    validate_error(
        api.create_lease(
            f.lease_payload(lessee["id"], "PIER-102F", total_permitted_gfa_sqft=-1),
            admin,
        ),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )

    rows, meta = validate_paginated(api.list_leases(admin))
    assert rows == []
    assert meta["total_count"] == 0


def test_terms_sitting_exactly_on_the_legal_extremes_are_accepted(api):
    """PRD §3.1: "`current_annual_base_rent_cents` is set equal to `initial_annual_base_rent_cents`."

    Design: Corner/validations/boundary_lease_terms_at_the_legal_extremes_accepted
    """
    lessee = fx.create_lessee(api)
    admin = make_lessor_admin_headers()

    lease_min = validate_success(
        api.create_lease(
            f.lease_payload(
                lessee["id"], "PIER-103A",
                reval_collar_min_uplift_bps=1, reval_collar_max_uplift_bps=2,
                percentage_rent_rate_bps=100, total_permitted_gfa_sqft=1,
            ),
            admin,
        ),
        expected_status=201,
    )
    assert_fields(
        lease_min,
        percentage_rent_rate_bps=100,
        reval_collar_min_uplift_bps=1,
        reval_collar_max_uplift_bps=2,
        total_permitted_gfa_sqft=1,
        gfa_unallocated_sqft=1,
    )

    lease_max = validate_success(
        api.create_lease(
            f.lease_payload(lessee["id"], "PIER-103B", percentage_rent_rate_bps=2000),
            admin,
        ),
        expected_status=201,
    )
    assert lease_max["percentage_rent_rate_bps"] == 2000

    for lease in (lease_min, lease_max):
        assert_fields(
            lease,
            lease_status="ACTIVE",
            rent_status="BASE_ONLY",
            insurance_status="LAPSED",
            version=1,
        )


def test_the_use_clause_is_rechecked_against_the_use_in_force_at_decision(api):
    """PRD §3.5: "The `proposed_use_code` must still equal the lease's `permitted_use_code`, which means an intervening terms amendment can invalidate a request that was perfectly compliant when submitted; that refusal is again `ERR_USE_NOT_PERMITTED`."

    Design: Corner/validations/alteration_use_clause_rechecked_against_the_use_in_force_at_decision
    """
    env = fx.standard_lease(api, "PIER-104")
    admin = make_lessor_admin_headers()
    window = {
        "requested_gfa_sqft": 1000,
        "construction_window_start": "2027-01-01T00:00:00Z",
        "construction_window_end": "2027-02-01T00:00:00Z",
        "estimated_cost_cents": 100000,
    }

    validate_error(
        api.create_alteration(
            env["lease_id"],
            f.alteration_payload(proposed_use_code="INDUSTRIAL_LOGISTICS", **window),
            env["tenant"],
        ),
        ERR_USE_NOT_PERMITTED,
        expected_status=422,
    )
    _rows, meta = validate_paginated(
        api.list_alterations(admin, {"lease_id": env["lease_id"]})
    )
    assert meta["total_count"] == 0

    alteration = fx.submitted_alteration(
        api, env["lease_id"], env["lessee_id"],
        proposed_use_code="RETAIL_MIXED", **window
    )
    assert_fields(alteration, status="SUBMITTED", proposed_use_code="RETAIL_MIXED")

    amended = validate_success(
        api.amend_terms(
            env["lease_id"], {"permitted_use_code": "INDUSTRIAL_LOGISTICS"}, admin
        )
    )
    assert amended["permitted_use_code"] == "INDUSTRIAL_LOGISTICS"

    validate_error(
        api.decide_alteration(
            alteration["id"], f.decision_payload("APPROVE"),
            make_asset_manager_headers("am-1"),
        ),
        ERR_USE_NOT_PERMITTED,
        expected_status=422,
    )
    still = validate_success(api.get_alteration(alteration["id"], admin))
    assert still["status"] == "SUBMITTED"
    assert still["decided_by_user_id"] is None
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        gfa_allocated_sqft=0,
        gfa_unallocated_sqft=200000,
    )


def test_the_builders_risk_and_estoppel_insurance_gates_are_both_enforced(api):
    """PRD §3.5: "Where the `scope_code` is `STRUCTURAL_ALTERATION` or `REDEVELOPMENT`, builders-risk cover must be genuinely in place: the lease's `insurance_status` must be `ACTIVE`, `lessor_additional_insured` must be true, `builders_risk_limit_cents` must be at least `estimated_cost_cents`, and `insurance_expires_at` must be at or after `construction_window_end` so that cover does not run out mid-build; any of these four failing is refused with `ERR_INSURANCE_DEFICIENT`."

    Design: Corner/validations/structural_alteration_and_estoppel_insurance_gates_enforced
    """
    lessee = fx.create_lessee(api)
    admin = make_lessor_admin_headers()
    tenant = make_ground_tenant_headers(lessee["id"])
    manager = make_asset_manager_headers("am-1")
    lease_a = fx.create_lease(api, lessee["id"], "PIER-105")
    lease_b = fx.create_lease(api, lessee["id"], "PIER-106")
    mortgage_b = fx.record_senior_mortgage(api, lease_b["id"])

    alteration = fx.submitted_alteration(
        api, lease_a["id"], lessee["id"],
        scope_code="STRUCTURAL_ALTERATION", requested_gfa_sqft=5000,
        estimated_cost_cents=3000000,
        construction_window_end="2027-06-01T00:00:00Z",
    )

    validate_error(
        api.decide_alteration(alteration["id"], f.decision_payload("APPROVE"), manager),
        ERR_INSURANCE_DEFICIENT,
        expected_status=409,
    )

    short = validate_success(
        api.file_insurance_endorsement(
            lease_a["id"],
            f.insurance_payload(
                property_all_risk_limit_cents=100000000,
                builders_risk_limit_cents=2999999,
                lessor_additional_insured=True,
                expires_at="2028-01-01T00:00:00Z",
            ),
            tenant,
        )
    )
    assert_fields(short, insurance_status="ACTIVE",
                  builders_risk_limit_cents=2999999)

    validate_error(
        api.decide_alteration(alteration["id"], f.decision_payload("APPROVE"), manager),
        ERR_INSURANCE_DEFICIENT,
        expected_status=409,
    )

    exact = validate_success(
        api.file_insurance_endorsement(
            lease_a["id"],
            f.insurance_payload(
                property_all_risk_limit_cents=100000000,
                builders_risk_limit_cents=3000000,
                lessor_additional_insured=True,
                expires_at="2028-01-01T00:00:00Z",
            ),
            tenant,
        )
    )
    assert exact["builders_risk_limit_cents"] == 3000000

    approved = validate_success(
        api.decide_alteration(alteration["id"], f.decision_payload("APPROVE"), manager)
    )
    assert approved["status"] == "APPROVED"
    assert_fields(
        fx.read_lease(api, lease_a["id"]),
        gfa_allocated_sqft=5000,
        gfa_unallocated_sqft=195000,
    )

    validate_error(
        api.issue_estoppel(
            f.estoppel_payload(
                lease_b["id"], mortgage_b["id"], fx.lease_version(api, lease_b["id"])
            ),
            make_mortgagee_agent_headers(mortgage_b["id"]),
        ),
        ERR_INSURANCE_DEFICIENT,
        expected_status=409,
    )
    assert fx.read_lease(api, lease_b["id"])["insurance_status"] == "LAPSED"
    _rows, meta = validate_paginated(
        api.list_estoppels(admin, {"lease_id": lease_b["id"]})
    )
    assert meta["total_count"] == 0


def test_the_four_uniqueness_rules_each_refuse_a_duplicate(api):
    """PRD §2.8: "`ERR_DUPLICATE_RECORD` (HTTP 409) guards seven creates: one appraisal submission per revaluation, side and round; one open revaluation per lease; one arbitration proceeding per revaluation; one reversion assessment per lease; one `premises_unit_code` among a lease's active subleases; one `priority_rank` per lease's mortgages; and a globally unique `Lessee.legal_name`."

    Design: Corner/validations/uniqueness_rules_rejected_on_four_parents
    """
    env = fx.standard_lease(api, "PIER-107")
    admin = make_lessor_admin_headers()
    fx.record_senior_mortgage(api, env["lease_id"])
    reval = fx.open_revaluation(api, env["lease_id"])
    validate_success(
        api.lodge_appraisal(
            reval["id"],
            f.appraisal_payload("LESSOR", 14000000, "COMPARABLE_LAND"),
            make_lessor_admin_headers("appraiser-lessor-1"),
        ),
        expected_status=201,
    )

    validate_error(
        api.create_lessee(
            f.lessee_payload(notice_email="other@harborline.example"), admin
        ),
        ERR_DUPLICATE_RECORD,
        expected_status=409,
    )

    validate_error(
        api.open_revaluation(
            env["lease_id"], f.revaluation_payload("2027-09-01T00:00:00Z"), admin
        ),
        ERR_DUPLICATE_RECORD,
        expected_status=409,
    )
    _revals, reval_meta = validate_paginated(
        api.list_revaluations(admin, {"lease_id": env["lease_id"]})
    )
    assert reval_meta["total_count"] == 1

    validate_error(
        api.record_mortgage(
            env["lease_id"], f.mezz_mortgage_payload(priority_rank=1), admin
        ),
        ERR_DUPLICATE_RECORD,
        expected_status=409,
    )

    validate_error(
        api.lodge_appraisal(
            reval["id"],
            f.appraisal_payload("LESSOR", 13000000, "COMPARABLE_LAND"),
            make_lessor_admin_headers("appraiser-lessor-2"),
        ),
        ERR_DUPLICATE_RECORD,
        expected_status=409,
    )
    rows, meta = validate_paginated(
        api.list_appraisals(admin, {"revaluation_id": reval["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["appraised_annual_rent_cents"] == 14000000


def test_the_chronology_family_is_refused_on_each_of_its_endpoints(api):
    """PRD §2.8: "**Chronology.** `ERR_CHRONOLOGY_VIOLATION` (HTTP 422) guards revaluation opening, statement filing and lessee cure, and is detailed in §2.9."

    Design: Corner/validations/chronology_rules_rejected_across_four_endpoints
    """
    env = fx.standard_lease(api, "PIER-108")
    admin = make_lessor_admin_headers()
    notice = validate_success(
        api.serve_default_notice(
            env["lease_id"], f.default_notice_payload("UNPERMITTED_USE"),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )
    version = fx.lease_version(api, env["lease_id"])

    validate_error(
        api.open_revaluation(
            env["lease_id"], f.revaluation_payload("2026-10-01T00:00:00Z"), admin
        ),
        ERR_CHRONOLOGY_VIOLATION,
        expected_status=422,
    )
    validate_error(
        api.file_statement(
            f.statement_payload(
                env["lease_id"], version,
                "2026-06-01T00:00:00Z", "2027-01-01T00:00:00Z", 120000000,
            ),
            env["tenant"],
        ),
        ERR_CHRONOLOGY_VIOLATION,
        expected_status=422,
    )
    validate_error(
        api.file_statement(
            f.statement_payload(
                env["lease_id"], version,
                "2026-07-01T00:00:00Z", "2026-06-01T00:00:00Z", 120000000,
            ),
            env["tenant"],
        ),
        ERR_CHRONOLOGY_VIOLATION,
        expected_status=422,
    )
    validate_error(
        api.lessee_cure(
            notice["id"], f.lessee_cure_payload("2026-07-25T00:00:00Z", 0),
            env["tenant"],
        ),
        ERR_CHRONOLOGY_VIOLATION,
        expected_status=422,
    )
    assert validate_success(
        api.get_default_notice(notice["id"], admin)
    )["status"] == "SERVED"
    assert fx.read_lease(api, env["lease_id"])["lease_status"] == "IN_DEFAULT"

    validate_error(
        api.create_transfer(
            f.sublease_payload(
                env["lease_id"], "UNIT-A", 12000000, sublet_area_sqft=50000,
                term_start="2019-01-01T00:00:00Z",
                term_end="2030-01-01T00:00:00Z",
            ),
            env["tenant"],
        ),
        ERR_CHRONOLOGY_VIOLATION,
        expected_status=422,
    )

    for lister, params in (
        (api.list_revaluations, {"lease_id": env["lease_id"]}),
        (api.list_statements, {"lease_id": env["lease_id"]}),
        (api.list_transfers, {"lease_id": env["lease_id"]}),
    ):
        _rows, meta = validate_paginated(lister(admin, params))
        assert meta["total_count"] == 0


def test_a_fee_payment_and_an_award_pool_must_reconcile_to_the_cent(api):
    """PRD §2.8: "**Money reconciliation.** `ERR_AMOUNT_NOT_RECONCILED` (HTTP 422) guards loss-proceeds allocation, the reversion holdback and transfer-fee payment."

    Design: Corner/validations/exact_amount_reconciliation_on_fee_payments_and_award_pools
    """
    env = fx.standard_lease(api, "PIER-109")
    admin = make_lessor_admin_headers()
    granted = fx.consented_sublease(
        api, env["lease_id"], env["lessee_id"], "UNIT-A", 12000000,
        sublet_area_sqft=50000,
        term_start="2027-01-01T00:00:00Z", term_end="2030-01-01T00:00:00Z",
        transferee_legal_name="Pier Market Grocers LLC",
    )
    assert granted["total_transfer_fee_cents"] == 4868750
    event = fx.reported_loss_event(
        api, env["lease_id"], headers=make_asset_manager_headers("am-1"),
        event_type="CONDEMNATION", damage_estimate_cents=4000000,
        damaged_area_sqft=10000,
    )

    for amount in (4868749, 4868751):
        validate_error(
            api.pay_transfer_fee(
                granted["id"], f.fee_payment_payload(amount), env["tenant"]
            ),
            ERR_AMOUNT_NOT_RECONCILED,
            expected_status=422,
        )
        still = validate_success(api.get_transfer(granted["id"], admin))
        assert_fields(still, status="CONSENT_GRANTED", transfer_fee_paid_cents=0)

    validate_error(
        api.adjust_loss_event(
            event["id"], f.adjust_payload(0, "BONUS_VALUE"),
            make_asset_manager_headers("am-1"),
        ),
        ERR_AMOUNT_NOT_RECONCILED,
        expected_status=422,
    )
    unmoved = validate_success(api.get_loss_event(event["id"], admin))
    assert unmoved["status"] == "REPORTED"
    assert unmoved["distributable_pool_cents"] is None

    activated = validate_success(
        api.pay_transfer_fee(
            granted["id"], f.fee_payment_payload(4868750), env["tenant"]
        )
    )
    assert_fields(activated, status="ACTIVE", transfer_fee_paid_cents=4868750)
    assert fx.read_lease(api, env["lease_id"])[
        "percentage_rent_sublease_base_cents"] == 6000000


TRANSFEREE = {
    "legal_name": "Bayside Estuary Partners LP",
    "notice_email": "legal@bayside.example",
    "credit_rating_code": "BBB",
}


def test_transfer_field_completeness_is_checked_at_filing_and_credit_at_consent(api):
    """PRD §3.6: "Omitting any field its transfer type requires is refused with `ERR_TRANSFER_FIELDS_MISMATCHED` (HTTP 422)."

    Design: Corner/validations/transfer_field_completeness_and_credit_rating_gates
    """
    env = fx.standard_lease(api, "PIER-110")
    admin = make_lessor_admin_headers()
    manager = make_asset_manager_headers("am-1")
    transferee = fx.create_lessee(api, **TRANSFEREE)

    validate_error(
        api.create_transfer(
            {
                "lease_id": env["lease_id"],
                "transfer_type": "ASSIGNMENT",
                "term_start": "2027-01-01T00:00:00Z",
                "term_end": "2070-01-01T00:00:00Z",
                "transferee_legal_name": TRANSFEREE["legal_name"],
                "transferee_lessee_id": transferee["id"],
                "transferee_credit_rating_code": "BBB",
            },
            env["tenant"],
        ),
        ERR_TRANSFER_FIELDS_MISMATCHED,
        expected_status=422,
    )
    validate_error(
        api.create_transfer(
            {
                "lease_id": env["lease_id"],
                "transfer_type": "SUBLEASE",
                "term_start": "2027-01-01T00:00:00Z",
                "term_end": "2030-01-01T00:00:00Z",
                "transferee_legal_name": "Pier Market Grocers LLC",
                "premises_unit_code": "UNIT-A",
                "annual_sublease_rent_cents": 12000000,
            },
            env["tenant"],
        ),
        ERR_TRANSFER_FIELDS_MISMATCHED,
        expected_status=422,
    )

    speculative = validate_success(
        api.create_transfer(
            f.assignment_payload(
                env["lease_id"], transferee["id"], 40000000,
                transferee_legal_name=TRANSFEREE["legal_name"],
                transferee_credit_rating_code="SPECULATIVE",
                term_start="2027-01-01T00:00:00Z",
            ),
            env["tenant"],
        ),
        expected_status=201,
    )
    assert speculative["status"] == "SUBMITTED"

    validate_error(
        api.decide_transfer(
            speculative["id"], f.decision_payload("APPROVE"), manager
        ),
        ERR_CREDIT_RATING_REFUSED,
        expected_status=422,
    )
    refused = validate_success(api.get_transfer(speculative["id"], admin))
    assert refused["status"] == "SUBMITTED"
    for field in (
        "transfer_fee_gross_cents", "admin_charge_cents",
        "late_surcharge_cents", "total_transfer_fee_cents",
    ):
        assert refused[field] is None, field

    eligible = validate_success(
        api.create_transfer(
            f.assignment_payload(
                env["lease_id"], transferee["id"], 40000000,
                transferee_legal_name=TRANSFEREE["legal_name"],
                term_start="2027-01-01T00:00:00Z",
            ),
            env["tenant"],
        ),
        expected_status=201,
    )
    granted = validate_success(
        api.decide_transfer(eligible["id"], f.decision_payload("APPROVE"), manager)
    )
    assert_fields(
        granted,
        status="CONSENT_GRANTED",
        transfer_fee_gross_cents=1200000,
        admin_charge_cents=30000,
        late_surcharge_cents=0,
        total_transfer_fee_cents=1230000,
    )
    assert granted["allocable_base_rent_cents"] is None
    assert fx.read_lease(api, env["lease_id"])["lessee_id"] == env["lessee_id"]


def test_an_appraisal_lodged_for_the_other_side_is_refused(api):
    """PRD §3.3: "Lodging a `LESSOR`-side appraisal while acting as `GroundTenant`, or a `LESSEE`-side appraisal while acting as `LessorAdmin`, is refused with `ERR_APPRAISAL_SIDE_MISMATCH`."

    Design: Corner/validations/appraisal_side_must_match_the_acting_role_rejected
    """
    env = fx.standard_lease(api, "PIER-111")
    admin = make_lessor_admin_headers()
    reval = fx.open_revaluation(api, env["lease_id"])

    validate_error(
        api.lodge_appraisal(
            reval["id"],
            f.appraisal_payload("LESSEE", 10000000, "INCOME_CAP"),
            make_lessor_admin_headers("appraiser-lessor-1"),
        ),
        ERR_APPRAISAL_SIDE_MISMATCH,
        expected_status=403,
    )
    _rows, empty = validate_paginated(
        api.list_appraisals(admin, {"revaluation_id": reval["id"]})
    )
    assert empty["total_count"] == 0

    validate_error(
        api.lodge_appraisal(
            reval["id"],
            f.appraisal_payload("LESSOR", 14000000, "COMPARABLE_LAND"),
            env["tenant"],
        ),
        ERR_APPRAISAL_SIDE_MISMATCH,
        expected_status=403,
    )

    lessor_row, lessee_row = fx.lodge_both_appraisals(
        api, reval["id"], env["lessee_id"]
    )
    # §2.4: an AppraisalSubmission "carries only `id` and `created_at`", so no
    # `submitted_at` attribute is derivable from the PRD.
    for row in (lessor_row, lessee_row):
        assert_fields(row, round_number=1)

    rows, meta = validate_paginated(
        api.list_appraisals(admin, {"revaluation_id": reval["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_a_holdback_is_refused_where_the_condition_standard_was_met(api):
    """PRD §3.9: "The assessment must be in `INSPECTED`, and `weighted_score_bps` must be **strictly below** the passing score for the snapshotted `required_standard_code`; at exactly the passing score no holdback may be applied and closing is the only available move, with the attempt refused as `ERR_STANDARD_MET_NO_HOLDBACK`."

    Design: Corner/validations/holdback_refused_when_the_condition_standard_is_met
    """
    env = fx.standard_lease(
        api, "PIER-112", expiration_date="2026-09-01T00:00:00Z"
    )
    admin = make_lessor_admin_headers()
    inspector = make_asset_manager_headers("am-1")
    _report, assessment = fx.expire_lease_via_sweep(api, env["lease_id"])
    assert assessment["status"] == "PENDING_INSPECTION"

    inspected = validate_success(
        api.record_inspection(
            assessment["id"], f.inspection_payload(90, 90, 90), inspector
        )
    )
    assert_fields(
        inspected,
        status="INSPECTED",
        weighted_score_bps=9000,
        # §3.9: "`deficiency_bps` is 10,000 less `weighted_score_bps`" — it is
        # not zeroed just because the passing score was met.
        deficiency_bps=1000,
        inspected_by_user_id="am-1",
    )

    validate_error(
        api.apply_holdback(
            assessment["id"], f.holdback_payload(0),
            make_accountant_headers("acct-1"),
        ),
        ERR_STANDARD_MET_NO_HOLDBACK,
        expected_status=409,
    )
    still_inspected = validate_success(
        api.get_reversion_assessment(assessment["id"], admin)
    )
    assert still_inspected["status"] == "INSPECTED"
    assert still_inspected["holdback_cents"] is None
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        deposit_held_cents=5000000,
        deposit_applied_cents=0,
    )

    closed = validate_success(
        api.close_assessment(assessment["id"], make_asset_manager_headers("am-2"))
    )
    assert_fields(closed, status="CLOSED", deposit_released_cents=5000000)
    reverted = fx.read_lease(api, env["lease_id"])
    assert_fields(
        reverted,
        lease_status="REVERTED",
        deposit_held_cents=0,
        deposit_applied_cents=0,
        deposit_refunded_cents=5000000,
    )
    assert_deposit_conserved(reverted)


def test_a_mortgagee_cure_naming_another_leases_mortgage_is_refused(api):
    """PRD §3.7: "Both actions are refused once the logical clock is strictly after `mortgagee_cure_deadline`, with `ERR_CURE_WINDOW_CLOSED`, and both require the named mortgage to sit on the notice's own lease, with a mismatch refused as `ERR_MORTGAGE_LEASE_MISMATCH`."

    Design: Corner/validations/mortgagee_cure_naming_a_mortgage_on_another_lease_rejected
    """
    lessee = fx.create_lessee(api)
    admin = make_lessor_admin_headers()
    lease_a = fx.create_lease(api, lessee["id"], "PIER-113")
    lease_b = fx.create_lease(api, lessee["id"], "PIER-114")
    mortgage_a = fx.record_senior_mortgage(
        api, lease_a["id"], original_principal_cents=3000000
    )
    mortgage_b = fx.record_senior_mortgage(
        api, lease_b["id"],
        mortgagee_legal_name="Tidewater Mezzanine Partners",
        notice_email="agent@tidewater.example",
        original_principal_cents=2000000,
    )
    fx.add_arrears(api, lease_a["id"], 2000000)
    notice = validate_success(
        api.serve_default_notice(
            lease_a["id"],
            f.default_notice_payload("MONETARY_RENT_ARREARS", 2000000),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )

    fx.set_clock(api, "2026-08-12T00:00:00Z")
    fx.run_sweep(api)
    lapsed = validate_success(api.get_default_notice(notice["id"], admin))
    assert_fields(
        lapsed,
        status="LESSEE_CURE_LAPSED",
        mortgagee_cure_deadline="2026-09-10T00:00:00Z",
    )

    validate_error(
        api.mortgagee_cure(
            notice["id"],
            f.mortgagee_cure_payload("ELECT", mortgage_b["id"]),
            make_mortgagee_agent_headers(mortgage_b["id"]),
        ),
        ERR_MORTGAGE_LEASE_MISMATCH,
        expected_status=422,
    )
    assert validate_success(
        api.get_default_notice(notice["id"], admin)
    )["status"] == "LESSEE_CURE_LAPSED"
    assert validate_success(
        api.get_mortgage(mortgage_b["id"], admin)
    )["status"] == "RECORDED"

    elected = validate_success(
        api.mortgagee_cure(
            notice["id"],
            f.mortgagee_cure_payload("ELECT", mortgage_a["id"]),
            make_mortgagee_agent_headers(mortgage_a["id"]),
        )
    )
    assert elected["status"] == "MORTGAGEE_CURING"
    assert validate_success(
        api.get_mortgage(mortgage_a["id"], admin)
    )["status"] == "CURING"
    assert_fields(
        fx.read_lease(api, lease_a["id"]),
        lease_status="IN_DEFAULT",
        arrears_balance_cents=2000000,
    )


def test_the_envelope_aggregate_is_reported_ahead_of_the_use_recheck(api):
    """PRD §3.5: "It is entirely possible for each of several requests to fit individually while the collection exceeds the envelope, which is exactly what this check catches."

    Design: Corner/validations/envelope_aggregate_at_priority_13_beats_the_use_recheck_at_priority_17
    """
    env = fx.standard_lease(api, "PIER-115")
    admin = make_lessor_admin_headers()
    manager = make_asset_manager_headers("am-1")

    fx.approved_alteration(
        api, env["lease_id"], env["lessee_id"],
        requested_gfa_sqft=150000,
        construction_window_start="2027-01-01T00:00:00Z",
        construction_window_end="2027-03-01T00:00:00Z",
        estimated_cost_cents=100000,
    )
    request_b = validate_success(
        api.create_alteration(
            env["lease_id"],
            f.alteration_payload(
                requested_gfa_sqft=100000,
                construction_window_start="2027-04-01T00:00:00Z",
                construction_window_end="2027-06-01T00:00:00Z",
                estimated_cost_cents=100000,
            ),
            env["tenant"],
        ),
        expected_status=201,
    )
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        gfa_allocated_sqft=150000,
        gfa_unallocated_sqft=50000,
    )

    amended = validate_success(
        api.amend_terms(
            env["lease_id"], {"permitted_use_code": "INDUSTRIAL_LOGISTICS"}, admin
        )
    )
    assert amended["permitted_use_code"] == "INDUSTRIAL_LOGISTICS"

    validate_error(
        api.decide_alteration(
            request_b["id"], f.decision_payload("APPROVE"), manager
        ),
        ERR_GFA_ENVELOPE_EXCEEDED,
        expected_status=409,
    )
    assert validate_success(
        api.get_alteration(request_b["id"], admin)
    )["status"] == "SUBMITTED"
    assert_fields(
        fx.read_lease(api, env["lease_id"]),
        gfa_allocated_sqft=150000,
        gfa_unallocated_sqft=50000,
    )
