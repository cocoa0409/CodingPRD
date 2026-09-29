"""The inventory completeness percentage at its edges.

An empty inventory is complete by convention, and thirds of an inventory are
carried to exactly two decimal places.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    assert_program_state,
    create_asset,
    create_jurisdiction,
    create_program,
    read_program,
    validate_success,
)


def _three_undocumented_points(api):
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    ids = [
        create_asset(
            api,
            program["id"],
            jurisdiction["id"],
            template_storage_location=location,
        )["id"]
        for location in ("tk-vault-01", "tk-vault-02", "tk-vault-03")
    ]
    return program, ids


def test_an_empty_inventory_is_complete_and_undocumented_points_are_not(api):
    """Zero points read 100.00; three discovered points read 0.00.

    PRD §3.5: "The denominator is every collection point of the program whose
    status is not `DECOMMISSIONED`; when that set is empty the figure is exactly
    `100.00` by convention rather than an undefined division."

    A `DISCOVERED` point counts in the denominator but never in the numerator, so
    inventorying three surfaces and analysing none of them drops the figure from
    100.00 to 0.00.

    Design: Difficulty/boundary_precision_check/inventory_completeness_empty_scope_100_and_two_decimal_rounding_at_33_33_and_66_67
    """
    program = create_program(api)
    assert_program_state(program, inventory_completeness_pct=100.00)
    assert_program_state(read_program(api, program["id"]), inventory_completeness_pct=100.00)

    jurisdiction = create_jurisdiction(api, program["id"])
    for location in ("tk-vault-01", "tk-vault-02", "tk-vault-03"):
        create_asset(api, program["id"], jurisdiction["id"], template_storage_location=location)

    assert_program_state(read_program(api, program["id"]), inventory_completeness_pct=0.00)


def test_classifying_one_then_two_of_three_points_reads_33_33_then_66_67(api):
    """Thirds are rounded half-up to two decimal places.

    PRD §3.5: "The percentage is one hundred times the numerator divided by the
    denominator, rounded half-up to two decimal places."

    One documented point out of three is 33.333...% and reads 33.33; two are
    66.666...% and read 66.67; all three read 100.00.

    Design: Difficulty/boundary_precision_check/inventory_completeness_empty_scope_100_and_two_decimal_rounding_at_33_33_and_66_67
    """
    program, asset_ids = _three_undocumented_points(api)

    validate_success(api.transition_asset(asset_ids[0], {"to_status": "CLASSIFIED"}, PRIVACY_OFFICER))
    assert_program_state(read_program(api, program["id"]), inventory_completeness_pct=33.33)

    validate_success(api.transition_asset(asset_ids[1], {"to_status": "CLASSIFIED"}, PRIVACY_OFFICER))
    assert_program_state(read_program(api, program["id"]), inventory_completeness_pct=66.67)

    validate_success(api.transition_asset(asset_ids[2], {"to_status": "CLASSIFIED"}, PRIVACY_OFFICER))
    assert_program_state(read_program(api, program["id"]), inventory_completeness_pct=100.00)
