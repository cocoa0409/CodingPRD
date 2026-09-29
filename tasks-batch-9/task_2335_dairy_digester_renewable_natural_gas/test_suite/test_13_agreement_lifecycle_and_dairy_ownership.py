"""Contracting manure supply: the drafted agreement's system fields, the bounded
negotiation cycle, the counters that derive a dairy's status, and per-row ownership."""
from test_helpers import (
    ADMIN,
    OPERATOR,
    create_dairy,
    create_facility,
    create_offered_agreement,
    create_second_dairy,
    make_dairy_partner_headers,
    set_clock,
    sign_agreement,
    validate_error,
    validate_success,
)

AGREEMENT_TERMS = {
    "committed_tonnes_per_day": 180.000,
    "minimum_total_solids_pct": 6.50,
    "term_start_date": "2026-07-01",
    "term_end_date": "2027-06-30",
    "revenue_share_pct": 0.2200,
    "revenue_share_basis": "NET",
    "curtailable": True,
}


def test_01_a_drafted_agreement_carries_its_system_fields_and_no_negotiation_history(api):
    """The server mints the identity and the negotiation slots start empty.

    PRD: "A drafted agreement begins in `DRAFT` with `negotiation_round` at 0, `countered_tonnes_per_day` and `countered_revenue_share_pct` null, `suspension_reason` null and `signed_at` null."

    Design: Corner/entities/entity_agreement_creation_stamps_system_fields_and_initial_version
    """
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy()
    facility = create_facility()

    payload = {"dairy_id": dairy["id"], "facility_id": facility["id"]}
    payload.update(AGREEMENT_TERMS)
    agreement = validate_success(api.create_agreement(payload, OPERATOR), 201)

    assert isinstance(agreement["id"], str)
    assert agreement["id"] != ""
    assert agreement["created_at"] == agreement["updated_at"]
    assert agreement["created_at"].endswith("Z")
    assert agreement["version"] == 1
    assert agreement["status"] == "DRAFT"
    assert agreement["negotiation_round"] == 0
    assert agreement["signed_at"] is None
    assert agreement["countered_tonnes_per_day"] is None
    assert agreement["countered_revenue_share_pct"] is None
    assert agreement["suspension_reason"] is None


def test_02_revising_rewrites_the_commercial_terms_but_not_the_contract_window(api):
    """Three terms are overwritten, the counter slots cleared, the term dates survive.

    PRD: "Revising closes the cycle, moving the agreement `COUNTERED → DRAFT`: the `ProjectOperator` supplies fresh values for `committed_tonnes_per_day`, `minimum_total_solids_pct` and `revenue_share_pct`, which overwrite the previous terms, while `countered_tonnes_per_day` and `countered_revenue_share_pct` are cleared back to null and the agreement's `version` increments by one."

    Design: Corner/entities/entity_agreement_revise_leaves_the_term_dates_untouched
    """
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy()
    facility = create_facility()
    agreement = create_offered_agreement(dairy["id"], facility["id"])

    countered = validate_success(
        api.counter_agreement(
            agreement["id"],
            {
                "countered_tonnes_per_day": 150.000,
                "countered_revenue_share_pct": 0.2500,
                "comment": "Haul capacity is tighter than assumed",
            },
            make_dairy_partner_headers(dairy["id"]),
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["negotiation_round"] == 1

    revised = validate_success(
        api.revise_agreement(
            agreement["id"],
            {
                "committed_tonnes_per_day": 150.000,
                "minimum_total_solids_pct": 7.00,
                "revenue_share_pct": 0.2500,
            },
            OPERATOR,
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["committed_tonnes_per_day"] == 150.000
    assert revised["minimum_total_solids_pct"] == 7.00
    assert revised["revenue_share_pct"] == 0.2500
    assert revised["term_start_date"] == "2026-07-01"
    assert revised["term_end_date"] == "2027-06-30"
    assert revised["countered_tonnes_per_day"] is None
    assert revised["countered_revenue_share_pct"] is None
    assert revised["negotiation_round"] == 1
    assert revised["version"] == 4


def test_03_signing_stamps_the_clock_and_promotes_the_dairy_in_one_call(api):
    """Four declared side effects fire together on the dairy's single signature.

    PRD: "Signing stamps `signed_at` from the logical clock, increments both `active_agreement_count` and `contracted_agreement_count` on the dairy by one, and — because the active count has risen to at least one — re-derives the dairy's `status` from `PROSPECT` to `CONTRACTED`."

    Design: Corner/state_machines/sm_agreement_sign_promotes_the_dairy_and_stamps_signed_at
    """
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy()
    facility = create_facility()
    agreement = create_offered_agreement(dairy["id"], facility["id"])
    assert dairy["status"] == "PROSPECT"

    signed = validate_success(
        api.sign_agreement(
            agreement["id"],
            {"signatory_name": "R. Alvarez"},
            make_dairy_partner_headers(dairy["id"]),
        )
    )
    assert signed["status"] == "ACTIVE"
    assert signed["signed_at"].startswith("2026-08-01T00:00:00")
    assert signed["version"] == 3

    promoted = validate_success(api.get_dairy(dairy["id"], OPERATOR))
    assert promoted["status"] == "CONTRACTED"
    assert promoted["active_agreement_count"] == 1
    assert promoted["contracted_agreement_count"] == 1
    assert promoted["version"] == 2


def test_04_terminating_the_only_agreement_returns_the_dairy_to_prospect(api):
    """Both counters fall to zero, so the derived status skips SUSPENDED entirely.

    PRD: "When the prior status was `ACTIVE`, termination decrements the dairy's `active_agreement_count` by one; from either prior status it decrements `contracted_agreement_count` by one, and because that count has reached zero the dairy's `status` moves to `PROSPECT`."

    Design: Corner/state_machines/sm_dairy_falls_back_to_prospect_when_its_only_agreement_is_terminated
    """
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy()
    facility = create_facility()
    agreement = create_offered_agreement(dairy["id"], facility["id"])
    sign_agreement(agreement["id"], dairy["id"])
    contracted = validate_success(api.get_dairy(dairy["id"], OPERATOR))
    assert contracted["status"] == "CONTRACTED"

    terminated = validate_success(
        api.change_agreement_status(
            agreement["id"], {"action": "TERMINATE", "reason": "Herd sold"}, OPERATOR
        )
    )
    assert terminated["status"] == "TERMINATED"

    demoted = validate_success(api.get_dairy(dairy["id"], OPERATOR))
    assert demoted["active_agreement_count"] == 0
    assert demoted["contracted_agreement_count"] == 0
    assert demoted["status"] == "PROSPECT"


def test_05_a_dairy_holding_the_role_still_cannot_touch_a_neighbours_agreement(api):
    """Both dairy-side actions are refused per row, then the owner signs the same row.

    PRD: "Concretely, a `DairyPartner` countering or signing a feedstock agreement must present an `X-User-ID` equal to that agreement's `dairy_id`; a mismatch is rejected with `ERR_NOT_OWNING_DAIRY` (HTTP 403)."

    Design: Corner/rbac/rbac_dairy_partner_cannot_act_on_another_dairys_agreement
    """
    set_clock("2026-08-01T00:00:00Z")
    owner = create_dairy()
    stranger = create_second_dairy()
    facility = create_facility()
    agreement = create_offered_agreement(owner["id"], facility["id"])
    intruder = make_dairy_partner_headers(stranger["id"])

    validate_error(
        api.counter_agreement(
            agreement["id"],
            {
                "countered_tonnes_per_day": 120.000,
                "countered_revenue_share_pct": 0.3000,
                "comment": "Opportunistic counter by a third party",
            },
            intruder,
        ),
        "ERR_NOT_OWNING_DAIRY",
        403,
    )
    validate_error(
        api.sign_agreement(
            agreement["id"], {"signatory_name": "Someone Else"}, intruder
        ),
        "ERR_NOT_OWNING_DAIRY",
        403,
    )

    signed = validate_success(
        api.sign_agreement(
            agreement["id"],
            {"signatory_name": "R. Alvarez"},
            make_dairy_partner_headers(owner["id"]),
        )
    )
    assert signed["status"] == "ACTIVE"
    assert signed["negotiation_round"] == 0

    assert validate_success(api.get_dairy(owner["id"], ADMIN))["status"] == "CONTRACTED"
    assert validate_success(api.get_dairy(stranger["id"], ADMIN))["status"] == "PROSPECT"
