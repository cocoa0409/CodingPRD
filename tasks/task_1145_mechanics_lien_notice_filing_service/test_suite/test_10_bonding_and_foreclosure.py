"""Bonding around a lien and the foreclosure referral track (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_company,
    create_party,
    file_claim,
    get_lien_claim,
    get_project,
    lock_claim,
    make_customer_admin_headers,
    setup_draft_claim,
    setup_filed_claim,
    setup_filed_claim_with_sent_referral,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import (
    create_bonding_request_payload,
    create_foreclosure_referral_payload,
)
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]
_COUNSEL = TEST_USERS["counsel_headers"]


# ─── Referral creation requires a FILED claim (queue A: cross_entity_state_dependency) ──

def test_referral_create_on_locked_claim_rejected():
    """PRD §3.6: "A `CustomerAdmin` refers a `FILED` claim to counsel by
    creating a foreclosure referral with the `lien_claim_id` and a
    `counsel_name`; the claim must be `FILED` (`ERR_CLAIM_NOT_FILED`)"

    Design: Difficulty/cross_entity_state_dependency/referral_create_requires_filed_claim
    """
    ctx = setup_draft_claim(name="Ref Job", county="Sutter",
                            contract_value_cents=300000)
    claim = lock_claim(ctx["claim"]["id"], ctx["company"]["id"])
    assert claim["status"] == "AMOUNT_LOCKED"

    res = api.create_foreclosure_referral(
        create_foreclosure_referral_payload(
            claim["id"], counsel_name="Saul & Associates"
        ),
        make_customer_admin_headers(ctx["company"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_FILED)


def test_referral_create_on_filed_claim_succeeds():
    """PRD §3.6: "A `CustomerAdmin` refers a `FILED` claim to counsel by
    creating a foreclosure referral with the `lien_claim_id` and a
    `counsel_name`; the claim must be `FILED` (`ERR_CLAIM_NOT_FILED`)"
    PRD §3.6: "The referral starts `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/referral_create_requires_filed_claim
    """
    ctx = setup_draft_claim(name="Ref Job", county="Sutter",
                            contract_value_cents=300000)
    claim = lock_claim(ctx["claim"]["id"], ctx["company"]["id"])
    claim = file_claim(claim["id"], "2026-07-01")
    assert claim["status"] == "FILED"

    referral = validate_success(
        api.create_foreclosure_referral(
            create_foreclosure_referral_payload(
                claim["id"], counsel_name="Saul & Associates"
            ),
            make_customer_admin_headers(ctx["company"]["id"]),
        ),
        201,
    )
    assert referral["status"] == "DRAFT"


# ─── Decline / re-refer / suit cycle (queue B) ───────────────────────

def test_referral_decline_rerefer_suit_cycle():
    """PRD §3.6: "A `DECLINED` referral can be re-sent the same way, but only
    with a `counsel_name` that differs from the counsel who declined; the
    recorded `counsel_name` is replaced with the new one." and "Marking the suit
    filed moves the referral to `SUIT_FILED`, stamps `suit_filed_at` (null until
    the suit is filed), drives the linked claim from `FILED` to `FORECLOSED`,
    and turns the project's `lien_posture` to `LITIGATION`."

    Design: Corner/state_machines/referral_decline_rerefer_suit_cycle
    """
    ctx = setup_filed_claim_with_sent_referral(counsel_name="First Counsel LLP")
    referral_id = ctx["referral"]["id"]

    declined = validate_success(
        api.respond_foreclosure_referral(referral_id, {"outcome": "DECLINED"},
                                         _COUNSEL),
        200,
    )
    assert declined["status"] == "DECLINED"

    resent = validate_success(
        api.send_foreclosure_referral(
            referral_id, {"counsel_name": "Second Counsel PC"}, _OPS_AGENT
        ),
        200,
    )
    assert resent["status"] == "SENT"
    assert resent["counsel_name"] == "Second Counsel PC"

    accepted = validate_success(
        api.respond_foreclosure_referral(referral_id, {"outcome": "ACCEPTED"},
                                         _COUNSEL),
        200,
    )
    assert accepted["status"] == "ACCEPTED"

    # foreclosure deadline is 2026-09-29; 2026-09-01 is timely
    suit = validate_success(
        api.mark_suit_filed(referral_id, {"suit_filed_at": "2026-09-01"},
                            _COUNSEL),
        200,
    )
    assert suit["status"] == "SUIT_FILED"

    assert get_lien_claim(ctx["claim"]["id"])["status"] == "FORECLOSED"
    assert get_project(ctx["project"]["id"])["lien_posture"] == "LITIGATION"


# ─── Bonding around a lien (queue B) ─────────────────────────────────

def test_bonding_record_bonds_off_claim_and_cancels_referral():
    """PRD §3.6: "The `bond_amount_cents` is computed at creation as the claim's
    frozen `final_amount_cents` multiplied by the pinned rule's `bond_pct`,
    rounded half-up to whole cents." and "Recording drives the claim itself from
    `FILED` to `BONDED_OFF`: the project's `open_lien_count` decrements by one,
    the posture recomputes, and every open referral on the claim is cancelled to
    `CANCELLED` with `cancel_reason` `MOOT_BONDED`."
    (bond = round_half_up(100000 x 1.25) = 125000.)

    Design: Corner/state_machines/bonding_record_bonds_off_claim_and_cancels_referral
    """
    ctx = setup_filed_claim_with_sent_referral(contract_value_cents=100000)
    surety = create_party(ctx["project"]["id"], ctx["company"]["id"], "SURETY",
                          legal_name="SureBond", address="3 Br Ave")

    bonding = validate_success(
        api.create_bonding_request(
            create_bonding_request_payload(ctx["claim"]["id"], surety["id"]),
            make_customer_admin_headers(ctx["company"]["id"]),
        ),
        201,
    )
    assert bonding["status"] == "REQUESTED"
    assert bonding["bond_amount_cents"] == 125000

    recorded = validate_success(
        api.record_bonding_request(
            bonding["id"], {"recorded_at": "2026-08-01"}, _OPS_AGENT
        ),
        200,
    )
    assert recorded["status"] == "BOND_RECORDED"

    assert get_lien_claim(ctx["claim"]["id"])["status"] == "BONDED_OFF"

    referrals, meta = validate_paginated(
        api.list_claim_foreclosure_referrals(ctx["claim"]["id"], _OPS_AGENT)
    )
    assert meta["total_count"] == 1
    assert referrals[0]["status"] == "CANCELLED"
    assert referrals[0]["cancel_reason"] == "MOOT_BONDED"

    assert get_project(ctx["project"]["id"])["open_lien_count"] == 0


def test_surety_not_verified_rejected():
    """PRD §3.6: "the surety must be a `VERIFIED` party with `party_role`
    `SURETY` on the same project (`ERR_SURETY_NOT_VERIFIED`, HTTP 409; a surety
    from another project draws `ERR_PARTY_PROJECT_MISMATCH`)"

    Design: Corner/validations/surety_not_verified_rejected
    """
    ctx = setup_filed_claim(name="SV Job", contract_value_cents=100000)
    pending_surety = create_party(ctx["project"]["id"], ctx["company"]["id"],
                                  "SURETY", verify=False, legal_name="SureBond",
                                  address="3 Sv Ave")

    res = api.create_bonding_request(
        create_bonding_request_payload(ctx["claim"]["id"], pending_surety["id"]),
        make_customer_admin_headers(ctx["company"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SURETY_NOT_VERIFIED)


def test_mark_suit_filed_past_deadline_rejected():
    """PRD §3.6: "counsel marks the suit filed by recording `suit_filed_at`; the
    referral must be `ACCEPTED`, and the date must fall on or before the claim's
    `foreclosure_deadline` — the last day is inclusive — or the action fails
    with `ERR_FORECLOSURE_DEADLINE_PASSED`."
    (deadline 2026-09-29; suit filed 2026-09-30 is one day too late.)

    Design: Corner/validations/mark_suit_filed_past_deadline_rejected
    """
    ctx = setup_filed_claim_with_sent_referral(name="FD Job",
                                               contract_value_cents=100000)
    referral_id = ctx["referral"]["id"]
    assert ctx["claim"]["foreclosure_deadline"] == "2026-09-29"

    accepted = validate_success(
        api.respond_foreclosure_referral(referral_id, {"outcome": "ACCEPTED"},
                                         _COUNSEL),
        200,
    )
    assert accepted["status"] == "ACCEPTED"

    res = api.mark_suit_filed(referral_id, {"suit_filed_at": "2026-09-30"},
                              _COUNSEL)
    validate_error(res, ApiErrorId.ERR_FORECLOSURE_DEADLINE_PASSED)

    referrals, _meta = validate_paginated(
        api.list_claim_foreclosure_referrals(ctx["claim"]["id"], _OPS_AGENT)
    )
    assert referrals[0]["status"] == "ACCEPTED"
