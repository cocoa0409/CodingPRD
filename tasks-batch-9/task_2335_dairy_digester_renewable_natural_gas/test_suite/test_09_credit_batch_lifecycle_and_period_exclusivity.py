"""Credit batches: the truncating RIN branch, the creation screens, period exclusivity,
the terminal reversal, the pathway-version guard and the issuance duty split."""
from test_helpers import (
    PROGRAM,
    USER_DUAL,
    VERIFIER,
    create_facility,
    create_pathway,
    make_program_administrator_headers,
    read_pathway_version,
    setup_claimed_batch,
    setup_issued_batch,
    setup_pipeline_spec_day,
    setup_verified_batch,
    validate_error,
    validate_success,
)

DUAL_PROGRAM = make_program_administrator_headers(USER_DUAL)


def test_01_the_cellulosic_rin_count_is_truncated_not_rounded(api):
    """120.280 MMBtu earns 1410 whole RINs and the remainder is simply dropped.

    PRD: "Under `RFS_D3`, renewable identification numbers are whole instruments and are truncated rather than rounded up: the credit quantity is `delivered_mmbtu` multiplied by 11.727 RINs per MMBtu and then rounded **down** to the nearest whole number, and `credit_value_cents` is that whole count multiplied by the RIN price of 285 cents, rounded half up to a whole cent."

    Design: Corner/calculations/calc_rfs_d3_rin_quantity_floors_and_prices_at_the_declared_constants
    """
    plant = setup_claimed_batch(
        pathway_overrides={
            "program": "RFS_D3",
            "pathway_code": "EPA-D3-DDRNG-2026-01",
        }
    )
    assert plant["batch"]["credit_quantity_provisional"] == 1410

    batch = validate_success(
        api.verify_batch(
            plant["batch"]["id"],
            {"verifier_note": "RIN volumes traced to interconnect statements"},
            VERIFIER,
        )
    )
    assert batch["status"] == "VERIFIED"
    assert batch["delivered_mmbtu"] == 120.280
    assert batch["credit_quantity_final"] == 1410
    assert batch["credit_value_cents"] == 401850


def test_02_batch_creation_screens_the_facility_match_and_the_period_order(api):
    """A foreign facility and a reversed period are refused for their own reasons.

    PRD: "The denormalised `facility_id` must equal the pathway's own facility, or the request is rejected with `ERR_FACILITY_PATHWAY_MISMATCH`."

    Design: Corner/validations/validation_batch_creation_screens_facility_match_and_date_order
    """
    facility = create_facility()
    other_facility = create_facility(name="Kings Digester 2")
    pathway = create_pathway(facility["id"])
    assert pathway["version"] == 1

    validate_error(
        api.create_batch(
            {
                "pathway_id": pathway["id"],
                "facility_id": other_facility["id"],
                "period_start_date": "2026-08-01",
                "period_end_date": "2026-08-31",
                "expected_pathway_version": pathway["version"],
            },
            PROGRAM,
        ),
        "ERR_FACILITY_PATHWAY_MISMATCH",
        422,
    )
    validate_error(
        api.create_batch(
            {
                "pathway_id": pathway["id"],
                "facility_id": facility["id"],
                "period_start_date": "2026-08-31",
                "period_end_date": "2026-08-01",
                "expected_pathway_version": pathway["version"],
            },
            PROGRAM,
        ),
        "ERR_INVALID_DATE_RANGE",
        422,
    )

    untouched = validate_success(api.get_pathway(pathway["id"], PROGRAM))
    assert untouched["status"] == "PROVISIONAL"
    assert untouched["version"] == 1


def test_03_a_claimed_period_is_exclusive_but_a_disjoint_one_is_merely_empty(api):
    """August is locked by the claim; October opens and then finds no injected energy.

    PRD: "No batch on the same pathway whose status is `CLAIMED`, `VERIFIED` or `ISSUED` may have a period overlapping the requested period, or the request is rejected with `ERR_CREDIT_PERIOD_OVERLAP`."

    Design: Corner/validations/validation_overlapping_credit_period_and_empty_claim_period
    """
    plant = setup_claimed_batch()
    pathway_version = read_pathway_version(plant["pathway"]["id"])

    validate_error(
        api.create_batch(
            {
                "pathway_id": plant["pathway"]["id"],
                "facility_id": plant["facility"]["id"],
                "period_start_date": "2026-08-15",
                "period_end_date": "2026-09-15",
                "expected_pathway_version": pathway_version,
            },
            PROGRAM,
        ),
        "ERR_CREDIT_PERIOD_OVERLAP",
        409,
    )

    october = validate_success(
        api.create_batch(
            {
                "pathway_id": plant["pathway"]["id"],
                "facility_id": plant["facility"]["id"],
                "period_start_date": "2026-10-01",
                "period_end_date": "2026-10-31",
                "expected_pathway_version": pathway_version,
            },
            PROGRAM,
        ),
        201,
    )
    validate_error(
        api.claim_batch(
            october["id"], {"claim_note": "October 2026 LCFS claim"}, PROGRAM
        ),
        "ERR_NO_DELIVERED_VOLUME",
        422,
    )

    empty = validate_success(api.get_batch(october["id"], PROGRAM))
    assert empty["status"] == "DRAFT"
    assert empty["delivered_mmbtu"] == 0.000
    august = validate_success(api.get_batch(plant["batch"]["id"], PROGRAM))
    assert august["status"] == "CLAIMED"
    assert august["credit_quantity_provisional"] == 30.826


def test_04_a_reversed_batch_cannot_be_reversed_a_second_time(api):
    """The compensating action runs once and the ledger does not double-count.

    PRD: "The conserved quantity `credit_control_residual` is the issued total less the reversed total less the outstanding total, rounded to 3 decimal places, and it must always equal exactly 0.000 — after an issuance, after its compensating reversal, after a pathway revocation, and after an audit finding rewrites `credit_quantity_final` on batches that are already issued."

    Design: Corner/state_machines/sm_reversing_an_already_reversed_credit_batch_returns_invalid_state
    """
    plant = setup_issued_batch()
    reversed_batch = validate_success(
        api.reverse_batch(
            plant["batch"]["id"], {"reversal_reason": "OPERATOR_WITHDRAWAL"}, PROGRAM
        )
    )
    assert reversed_batch["status"] == "REVERSED"

    validate_error(
        api.reverse_batch(
            plant["batch"]["id"], {"reversal_reason": "REGULATOR_ORDER"}, PROGRAM
        ),
        "ERR_INVALID_STATE",
        409,
    )

    unchanged = validate_success(api.get_batch(plant["batch"]["id"], PROGRAM))
    assert unchanged["status"] == "REVERSED"
    assert unchanged["reversal_reason"] == "OPERATOR_WITHDRAWAL"

    ledger = validate_success(api.get_credit_ledger(plant["pathway"]["id"], PROGRAM))
    assert ledger["credits_issued_total"] == 30.826
    assert ledger["credits_reversed_total"] == 30.826
    assert ledger["credits_outstanding"] == 0.000
    assert ledger["credit_control_residual"] == 0.000


def test_05_a_pathway_version_read_before_certification_is_stale(api):
    """Certification moved the pathway on, so the pre-certification version is refused.

    PRD: "`CERTIFY` moves the pathway `PROVISIONAL → CERTIFIED` and requires that at least one operations day of the facility whose `gas_state` is `PIPELINE_SPEC` or `INJECTED` lies inside that window."

    Design: Corner/cross_cutting_layers/ccl_stale_pathway_version_is_rejected_then_the_refreshed_version_passes
    """
    plant = setup_pipeline_spec_day()
    pathway = create_pathway(plant["facility"]["id"])
    stale_version = pathway["version"]
    certified = validate_success(
        api.certification_decision(
            pathway["id"],
            {
                "decision": "CERTIFY",
                "reference_start_date": "2026-08-01",
                "reference_end_date": "2026-08-31",
            },
            PROGRAM,
        )
    )
    fresh_version = certified["version"]
    assert fresh_version > stale_version

    body = {
        "pathway_id": pathway["id"],
        "facility_id": plant["facility"]["id"],
        "period_start_date": "2026-08-01",
        "period_end_date": "2026-08-31",
        "expected_pathway_version": stale_version,
    }
    validate_error(api.create_batch(dict(body), PROGRAM), "ERR_STALE_VERSION", 412)

    body["expected_pathway_version"] = fresh_version
    batch = validate_success(api.create_batch(dict(body), PROGRAM), 201)
    assert batch["status"] == "DRAFT"
    assert batch["credit_quantity_provisional"] is None

    reread = validate_success(api.get_pathway(pathway["id"], PROGRAM))
    assert reread["status"] == "CERTIFIED"
    assert reread["certified_ci_score"] == -190.40


def test_06_the_verifier_of_a_batch_cannot_also_issue_it(api):
    """Segregation follows the person, not the hat they happen to be wearing.

    PRD: "Issuance returns to the `ProgramAdministrator`, who may record an optional `issuance_reference`. It moves the batch `VERIFIED → ISSUED`, requires the pathway to be `CERTIFIED`, and requires that the acting `X-User-ID` differ from the `X-User-ID` that verified this batch — otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/rbac_the_user_who_verified_a_batch_may_not_issue_it
    """
    plant = setup_verified_batch(verifier_user_id=USER_DUAL)

    validate_error(
        api.issue_batch(
            plant["batch"]["id"],
            {"issuance_reference": "LCFS-2026-08-0001"},
            DUAL_PROGRAM,
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    issued = validate_success(
        api.issue_batch(
            plant["batch"]["id"], {"issuance_reference": "LCFS-2026-08-0002"}, PROGRAM
        )
    )
    assert issued["status"] == "ISSUED"
    assert issued["credit_quantity_final"] == 30.826
    assert issued["credit_value_cents"] == 229654

    pathway = validate_success(api.get_pathway(plant["pathway"]["id"], PROGRAM))
    assert pathway["credits_issued_total"] == 30.826
    assert pathway["credits_outstanding"] == 30.826
    assert pathway["credit_control_residual"] == 0.000
