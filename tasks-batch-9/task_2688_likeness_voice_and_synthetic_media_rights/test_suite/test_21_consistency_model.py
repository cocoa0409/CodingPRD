"""One issuance settled inside its own answer, and one refusal that left no trace."""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADVERTISING_GRANT = {"permitted_use_notes": "Ads"}

VOICE_SAMPLE = {
    "asset_kind": "VOICE_SAMPLE",
    "capture_ref": "cap-001",
    "payload_digest": "sha256:aaa",
}

VOICE_BUILD = {"replica_kind": "VOICE", "build_ref": "build-001"}

SPOTS = (
    ("Spot A", "2026-09-01T00:00:00Z"),
    ("Spot B", "2026-09-02T00:00:00Z"),
    ("Spot C", "2026-09-03T00:00:00Z"),
)

FOUR_MONTH_WINDOW = {
    "distribution_start": "2026-08-01T00:00:00Z",
    "distribution_end": "2026-12-01T00:00:00Z",
    "actual_impressions": 500_000,
}


def _approved_spots_over_an_approved_replica(count):
    """A cleared voice replica carrying `count` approved outputs at 500000 projected."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, ADVERTISING_GRANT)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    fixtures.build_replica(scenario, VOICE_BUILD)
    fixtures.approve_replica(scenario)
    scenario["replica_version_at_approval"] = scenario["replica"]["version"]
    for description, first_use in SPOTS[:count]:
        fixtures.submit_performance(
            scenario,
            {
                "licensee_name": "Northlight",
                "intended_use_description": description,
                "projected_impressions": 500_000,
                "scheduled_first_use_at": first_use,
            },
        )
        fixtures.review_performance(scenario)
    return scenario


def _issued_licence(scenario, performance=None):
    """Issue one licence over the four-month window, echoing the live replica token."""
    fixtures.issue_license(scenario, FOUR_MONTH_WINDOW, performance)
    return scenario["license"]


def test_the_issuance_answer_already_carries_the_fully_priced_licence():
    """The royalty, the obligation, the surcharge and the total arrive together.

    The PRD states: "The result is written to `per_use_final_cents` and posted as a
    `PER_USE_FINAL` ledger entry split three ways." The obligation is resolved in the
    same write: "It also resolves the disclosure obligation from the talent's
    domicile profile: `disclosure_required` is taken from that profile's
    `disclosure_required_advertising` when `channel` is `ADVERTISING` and from
    `disclosure_required_entertainment` when `channel` is `ENTERTAINMENT`." So is the
    billing: "The subtotal is `per_use_final_cents` alone. The surcharge rate is zero
    when `disclosure_required` is false; otherwise it is 0.0175 for an `ADVERTISING`
    license and 0.0125 for an `ENTERTAINMENT` one." And: "`compliance_surcharge_cents`
    is the subtotal multiplied by that rate and rounded **up** to the next whole cent
    — not half up, as every royalty is. `license_total_cents` is the subtotal plus
    that surcharge."

    Design: Corner/consistency_model/one_license_issuance_settles_five_rows_inside_its_own_response
    """
    scenario = _approved_spots_over_an_approved_replica(1)

    issued = _issued_licence(scenario)

    assertions.assert_subset_equal(
        issued,
        {
            "per_use_final_cents": 225_000,
            "disclosure_required": True,
            "compliance_surcharge_cents": 3_938,
            "license_total_cents": 228_938,
            "distribution_status": "ISSUED",
            "compliance_status": "PENDING_LABEL",
        },
    )
    assertions.assert_money_is_number(issued["license_total_cents"])


def test_the_replica_counter_and_both_money_roll_ups_are_settled_by_that_answer():
    """No clock advance and no second write stand between the write and the reads.

    The PRD states: "Issuance finally increments the replica's `open_license_count`
    by one, recomputes the grant's `total_compensation_cents` and the talent's
    `lifetime_compensation_cents`, and advances the replica's and the talent's
    `version` by one each." The roll-ups are never allowed to lag: "Two roll-ups
    follow the ledger and must equal it at all times." The billing item stays out of
    them: "The surcharge funds disclosure labelling and monitoring, is paid by the
    licensee to the clearance office, and is deliberately **never** a ledger entry —
    it never reaches the talent's, the agency's or the administrator's shares."

    Design: Corner/consistency_model/one_license_issuance_settles_five_rows_inside_its_own_response
    """
    scenario = _approved_spots_over_an_approved_replica(1)
    version_at_approval = scenario["replica_version_at_approval"]

    _issued_licence(scenario)

    replica = fixtures.refresh_replica(scenario)
    assert replica["open_license_count"] == 1
    assert replica["version"] == version_at_approval + 1
    assert replica["status"] == "APPROVED_FOR_USE"

    grant = validate_success(
        api_client.get_consent_grant(scenario["grant"]["id"], scenario["admin_headers"]),
        200,
    )
    assert grant["total_compensation_cents"] == 750_000
    assert fixtures.read_talent(scenario)["lifetime_compensation_cents"] == 750_000


def test_the_ledger_holds_three_entries_and_the_final_royalty_splits_exactly():
    """The projection accrual and the delivery accrual both stand, and both split.

    The PRD states: "The provisional accrual is **not** reversed at issuance: both
    amounts coexist in the ledger and both are reflected in the grant's and the
    talent's roll-ups, because the projection accrual and the delivery accrual are
    separate obligations." Each entry is divided as it lands: "Every entry is split
    three ways at the moment it is appended." And the division is exact: "That
    remainder may be negative, and it is never dropped — the talent is the designated
    beneficiary of the rounding remainder, so the three stored slices always
    reconstruct `amount_cents` exactly."

    Design: Corner/consistency_model/one_license_issuance_settles_five_rows_inside_its_own_response
    """
    scenario = _approved_spots_over_an_approved_replica(1)

    _issued_licence(scenario)

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries, ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "PER_USE_FINAL"]
    )
    assertions.assert_ledger_sums_to(entries, 750_000)
    assertions.assert_ledger_entry(entries[2], "PER_USE_FINAL", 225_000, 168_750, 45_000, 11_250)


def _two_licences_filling_the_overlap_cap():
    """Three approved outputs on one replica, two of them already licensed."""
    scenario = _approved_spots_over_an_approved_replica(3)
    _issued_licence(scenario, scenario["performances"][0])
    _issued_licence(scenario, scenario["performances"][1])
    return scenario


def _third_issuance_over_the_same_window(scenario, expected_replica_version):
    """Ask for a third overlapping licence without asserting the outcome."""
    payload = factories.usage_license_payload(
        scenario["performances"][2]["id"], expected_replica_version, **FOUR_MONTH_WINDOW
    )
    return api_client.create_usage_license(payload, scenario["licensee_headers"])


def _licences_over(scenario, performance):
    """The licence collection narrowed to one output."""
    return validate_paginated(
        api_client.list_usage_licenses(
            scenario["licensee_headers"],
            params={"generated_performance_id": performance["id"]},
        )
    )


def test_the_third_overlapping_issuance_is_refused_at_the_cap():
    """Two licences stand over the window, and the token echoed is the live one.

    The PRD states: "At most two usage licenses whose `distribution_status` is
    `ISSUED` or `LIVE` may hold closed inclusive distribution windows that overlap on
    the same `digital_replica_id` while sharing at least one territory code." And:
    "A third such license is refused with `ERR_REPLICA_OVERLAP_CAP_EXCEEDED`." The
    replica's advanced token is what the two accepted issuances left behind:
    "Issuance finally increments the replica's `open_license_count` by one, recomputes
    the grant's `total_compensation_cents` and the talent's
    `lifetime_compensation_cents`, and advances the replica's and the talent's
    `version` by one each."

    Design: Corner/consistency_model/a_refused_multi_row_write_leaves_no_partial_trace
    """
    scenario = _two_licences_filling_the_overlap_cap()
    version_at_approval = scenario["replica_version_at_approval"]

    settled = fixtures.refresh_replica(scenario)
    assert settled["open_license_count"] == 2
    assert settled["version"] == version_at_approval + 2

    refused = _third_issuance_over_the_same_window(scenario, settled["version"])

    validate_error(refused, "ERR_REPLICA_OVERLAP_CAP_EXCEEDED")
    assert refused.status_code == 409


def test_the_refused_issuance_left_the_replica_and_both_roll_ups_where_they_stood():
    """The counter it would have incremented and the version it would have bumped.

    The PRD states what a successful issuance would have done: "Issuance finally
    increments the replica's `open_license_count` by one, recomputes the grant's
    `total_compensation_cents` and the talent's `lifetime_compensation_cents`, and
    advances the replica's and the talent's `version` by one each." Both roll-ups are
    tied to the ledger rather than to attempts: "A consent grant's
    `total_compensation_cents` is the signed sum of `amount_cents` over every entry
    whose `consent_grant_id` is that grant, reversals included. A talent's
    `lifetime_compensation_cents` is the signed sum of `amount_cents` over every
    entry whose `talent_id` is that talent, reversals included." What stands here is
    one creation fee, the three projection accruals and the two delivery accruals:
    "The provisional accrual is **not** reversed at issuance: both amounts coexist in
    the ledger and both are reflected in the grant's and the talent's roll-ups,
    because the projection accrual and the delivery accrual are separate obligations."

    Design: Corner/consistency_model/a_refused_multi_row_write_leaves_no_partial_trace
    """
    scenario = _two_licences_filling_the_overlap_cap()
    settled_version = fixtures.refresh_replica(scenario)["version"]

    _third_issuance_over_the_same_window(scenario, settled_version)

    replica = fixtures.refresh_replica(scenario)
    assert replica["open_license_count"] == 2
    assert replica["version"] == settled_version

    grant = validate_success(
        api_client.get_consent_grant(scenario["grant"]["id"], scenario["admin_headers"]),
        200,
    )
    assert grant["total_compensation_cents"] == 1_425_000
    assert fixtures.read_talent(scenario)["lifetime_compensation_cents"] == 1_425_000


def test_neither_a_seventh_ledger_entry_nor_a_licence_row_survived_the_refusal():
    """Six entries, no reversal, and the third output still carries no licence.

    The PRD states: "Ledger entries have no write endpoint of their own; they exist
    only as consequences of workflow operations, and the collection read is the only
    channel through which a cascade-created reversal can be discovered." The types are
    a closed vocabulary: "Every entry carries an `entry_type`, one of
    `INITIAL_CREATION`, `UNION_TOPUP`, `PER_USE_PROVISIONAL`, `PER_USE_FINAL` or
    `REVERSAL`; a signed `amount_cents`, which is negative only on a `REVERSAL`; a
    machine-generated `memo` explaining why the entry was posted; and `posted_at`, the
    logical instant at which it was appended." The narrowed licence view is declared
    too: "Usage licenses filter on `generated_performance_id`, `licensee_user_id`,
    `distribution_status`, `compliance_status` and `channel`."

    Design: Corner/consistency_model/a_refused_multi_row_write_leaves_no_partial_trace
    """
    scenario = _two_licences_filling_the_overlap_cap()
    settled_version = fixtures.refresh_replica(scenario)["version"]

    _third_issuance_over_the_same_window(scenario, settled_version)

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries,
        [
            "INITIAL_CREATION",
            "PER_USE_PROVISIONAL",
            "PER_USE_PROVISIONAL",
            "PER_USE_PROVISIONAL",
            "PER_USE_FINAL",
            "PER_USE_FINAL",
        ],
    )
    assertions.assert_ledger_sums_to(entries, 1_425_000)
    for entry in entries:
        assert entry["amount_cents"] > 0
        assert entry["reverses_entry_id"] is None

    _rows, meta = _licences_over(scenario, scenario["performances"][2])
    assert meta["total_count"] == 0
