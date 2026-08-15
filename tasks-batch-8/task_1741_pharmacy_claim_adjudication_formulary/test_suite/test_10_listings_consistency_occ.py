"""List/filter/pagination behavior, 404 resolution, immediate consistency, OCC."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    NON_EXISTENT_UUID,
    create_claim_payload,
    make_plan, make_drug, make_member, make_pharmacy, make_formulary_entry,
    make_adjudication_scenario, create_paid_claim,
    make_pharmacist_headers, make_member_headers,
)


def test_claims_list_pagination(api, pbm_admin_headers):
    """PRD §2.3: "`limit` caps the number of returned items; it defaults to 10 when
    omitted, with a minimum of 1 and a maximum of 100. `offset` specifies how many items
    to skip and defaults to 0."
    PRD §2.2: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/claims_list_pagination
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9004", "name": "Pageol", "unit_cost_cents": 100,
                        "max_daily_dose_units": 100},
    )
    member_id, drug_id, pharmacy_id = (
        scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
    )
    for fill in ("2026-03-01", "2026-04-01", "2026-05-01"):
        create_paid_claim(member_id, drug_id, pharmacy_id, fill_date=fill)

    data, meta = validate_paginated(
        api.list_claims(pbm_admin_headers,
                        params={"member_id": member_id, "limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_claims(pbm_admin_headers,
                        params={"member_id": member_id, "limit": 2, "offset": 2})
    )
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_fk_reverse_claims_filtered_by_member(api, pbm_admin_headers):
    """PRD §3.4: "Claim listings can be filtered by `member_id`, `pharmacy_id`,
    `drug_id`, `pa_id`, or `status`; `Pharmacist` callers see only their own pharmacy's
    claims and `Member` callers only their own, with the same scoping applied to
    single-claim reads (a member reading another member's claim is
    `ERR_MEMBER_MISMATCH`)."

    Design: Corner/endpoints/fk_reverse_claims_filtered_by_member
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9031", "name": "Filterex", "unit_cost_cents": 100,
                        "max_daily_dose_units": 100},
    )
    member2 = make_member(scenario["plan"]["id"], external_ref="M-FK2",
                          full_name="Pat Two")
    m1 = scenario["member"]["id"]
    create_paid_claim(m1, scenario["drug"]["id"], scenario["pharmacy"]["id"],
                      fill_date="2026-03-01")
    create_paid_claim(m1, scenario["drug"]["id"], scenario["pharmacy"]["id"],
                      fill_date="2026-04-01")
    create_paid_claim(member2["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
                      fill_date="2026-03-01")

    data, meta = validate_paginated(
        api.list_claims(pbm_admin_headers, params={"member_id": m1})
    )
    assert meta["total_count"] == 2
    assert all(c["member_id"] == m1 for c in data), "filter isolation by member_id"


def test_fk_reverse_members_filtered_by_plan(api, pbm_admin_headers):
    """PRD §3.2: "The member list can be filtered by `plan_id` or by `card_drug_id`; a
    `Member` caller reading a member record may read only their own, with anything else
    rejected as `ERR_MEMBER_MISMATCH`."

    Design: Corner/endpoints/fk_reverse_members_filtered_by_plan
    """
    plan1 = make_plan(name="P-FM1")
    plan2 = make_plan(name="P-FM2", assistance_model="MAXIMIZER", card_fill_cap_cents=100)
    member1 = make_member(plan1["id"], external_ref="M-FM1", full_name="Pat FM1")
    member2 = make_member(plan2["id"], external_ref="M-FM2", full_name="Pat FM2")

    data, meta = validate_paginated(
        api.list_members(pbm_admin_headers, params={"plan_id": plan1["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == member1["id"]
    assert all(m["id"] != member2["id"] for m in data)


def test_pa_and_audit_and_entry_get_not_found_returns_404(
    api, pbm_admin_headers, auditor_headers
):
    """PRD §2.7: "The first identifier that fails to resolve determines the error: an
    unknown plan yields `ERR_PLAN_NOT_FOUND`, an unknown drug (whether referenced as
    `drug_id`, `step_drug_id`, or `card_drug_id`) yields `ERR_DRUG_NOT_FOUND`, an unknown
    member yields `ERR_MEMBER_NOT_FOUND`, an unknown pharmacy yields
    `ERR_PHARMACY_NOT_FOUND`, an unknown claim yields `ERR_CLAIM_NOT_FOUND`, an unknown
    prior authorization yields `ERR_PA_NOT_FOUND`, an unknown audit yields
    `ERR_AUDIT_NOT_FOUND`, and an unknown formulary entry yields
    `ERR_FORMULARY_ENTRY_NOT_FOUND` — all HTTP 404."
    PRD §2.6: "a `Pharmacist` `X-User-ID` matching no pharmacy fails here as
    `ERR_PHARMACY_NOT_FOUND`."

    Design: Corner/endpoints/pa_and_audit_and_entry_get_not_found_returns_404
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9032", "name": "Notfoundex", "unit_cost_cents": 100,
                        "max_daily_dose_units": 10},
        entry_overrides={"quantity_limit_per_fill": 30, "max_days_supply": 30},
    )

    res = api.get_prior_authorization(NON_EXISTENT_UUID, pbm_admin_headers)
    validate_error(res, "ERR_PA_NOT_FOUND", expected_status=404)
    res = api.get_audit(NON_EXISTENT_UUID, auditor_headers)
    validate_error(res, "ERR_AUDIT_NOT_FOUND", expected_status=404)
    res = api.get_formulary_entry(NON_EXISTENT_UUID, pbm_admin_headers)
    validate_error(res, "ERR_FORMULARY_ENTRY_NOT_FOUND", expected_status=404)

    res = api.create_claim(
        create_claim_payload(NON_EXISTENT_UUID, scenario["drug"]["id"],
                             fill_date="2026-03-01"),
        scenario["pharmacist_headers"],
    )
    validate_error(res, "ERR_MEMBER_NOT_FOUND", expected_status=404)

    res = api.create_claim(
        create_claim_payload(scenario["member"]["id"], scenario["drug"]["id"],
                             fill_date="2026-03-01"),
        make_pharmacist_headers(NON_EXISTENT_UUID),
    )
    validate_error(res, "ERR_PHARMACY_NOT_FOUND", expected_status=404)


def test_consistency_immediate_read_after_write(api):
    """PRD §2.4: "The consistency model is immediate: every mutation and every
    derived-field update caused by a request is fully applied and visible in that
    request's response. There are no eventually-consistent reads."

    Design: Corner/endpoints/consistency_immediate_read_after_write
    """
    scenario = make_adjudication_scenario(
        plan_overrides={"dispensing_fee_cents": 50},
        drug_overrides={"ndc": "00000-9033", "name": "Consistin", "unit_cost_cents": 1000,
                        "max_daily_dose_units": 100},
        entry_overrides={"copay_flat_cents": 150},
    )
    created = validate_success(
        api.create_claim(
            create_claim_payload(scenario["member"]["id"], scenario["drug"]["id"],
                                 fill_date="2026-03-01", quantity=5, days_supply=5),
            scenario["pharmacist_headers"],
        ),
        201,
    )
    fetched = validate_success(
        api.get_claim(created["id"], scenario["pharmacist_headers"]), 200
    )
    for field in ("allowed_cents", "member_pays_cents", "plan_paid_cents",
                  "status", "version"):
        assert fetched[field] == created[field], (
            f"Read-after-write divergence on {field}: {fetched[field]} != {created[field]}"
        )
    assert fetched["allowed_cents"] == 5050
    assert fetched["member_pays_cents"] == 150
    assert fetched["plan_paid_cents"] == 4900
    assert fetched["status"] == "PAID"
    assert fetched["version"] == 1


def test_occ_stale_formulary_entry_version(api, pbm_admin_headers):
    """PRD §2.9: "Such a request must carry `expected_formulary_entry_version` as a
    non-optional field, holding the `version` of the formulary entry the client last
    observed. If that value no longer matches the entry's currently stored `version` —
    because any other writer has mutated the entry in the interim — the update is
    rejected with `ERR_STALE_VERSION` (HTTP 412), protecting terms such as tier,
    quantity limits, and copay structure from being overwritten on the basis of a stale
    read. A successful update increments the entry's `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_formulary_entry_version
    """
    plan = make_plan(name="P-OCC")
    drug = make_drug(ndc="00000-9039", name="Versionex", unit_cost_cents=100,
                     max_daily_dose_units=10)
    entry = make_formulary_entry(plan["id"], drug["id"], tier=1,
                                 quantity_limit_per_fill=30, max_days_supply=30,
                                 copay_type="FLAT", copay_flat_cents=100)
    observed_version = entry["version"]
    assert observed_version == 1

    updated = validate_success(
        api.update_formulary_entry(
            entry["id"],
            {"expected_formulary_entry_version": observed_version, "tier": 3},
            pbm_admin_headers,
        ),
        200,
    )
    assert updated["tier"] == 3
    assert updated["version"] == 2, "successful update increments version by one"

    res = api.update_formulary_entry(
        entry["id"],
        {"expected_formulary_entry_version": observed_version, "tier": 4},
        pbm_admin_headers,
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = get_success_data(api.get_formulary_entry(entry["id"], pbm_admin_headers))
    assert after["tier"] == 3, "stale write must change nothing"
    assert after["version"] == 2
