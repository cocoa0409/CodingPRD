"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the server DB is empty at the start of each test. Helpers use
get_success_data() (lenient) internally so setup failures surface clearly.

The context dict returned by the composite helpers carries the ids created along
the way: adj, lic, cli, pol, con, clm, app, pay, dis, sup.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_public_adjuster_headers,
    make_client_headers,
)
from .factories import (
    create_adjuster_payload,
    create_license_payload,
    create_client_payload,
    create_policy_payload,
    create_contract_payload,
    create_claim_payload,
    create_payment_payload,
    create_supplement_payload,
    create_appraisal_payload,
    name_appraisers_payload,
)

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# --------------------------------------------------------------- primitives
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, FIRM))


def new_adjuster(api, **overrides):
    return get_success_data(api.create_adjuster(create_adjuster_payload(**overrides), FIRM))["id"]


def new_license(api, adjuster_id, **overrides):
    return get_success_data(
        api.create_license(create_license_payload(adjuster_id, **overrides), FIRM)
    )


def new_client(api, **overrides):
    return get_success_data(api.create_client(create_client_payload(**overrides), FIRM))["id"]


def new_policy(api, client_id, **overrides):
    return get_success_data(
        api.create_policy(create_policy_payload(client_id, **overrides), FIRM)
    )["id"]


def new_contract(api, client_id, adjuster_id, **overrides):
    return get_success_data(
        api.create_contract(create_contract_payload(client_id, adjuster_id, **overrides), FIRM)
    )["id"]


def sign_contract(api, contract_id, client_id):
    return get_success_data(api.sign_contract(contract_id, make_client_headers(client_id)))


def activate_contract(api, contract_id):
    return get_success_data(api.activate_contract(contract_id, FIRM))


def new_draft_claim(api, policy_id, contract_id, adjuster_id, **overrides):
    return get_success_data(
        api.create_claim(
            create_claim_payload(policy_id, contract_id, **overrides),
            make_public_adjuster_headers(adjuster_id),
        )
    )["id"]


def file_claim(api, claim_id, adjuster_id):
    return get_success_data(api.file_claim(claim_id, make_public_adjuster_headers(adjuster_id)))


def claim_version(api, claim_id):
    return get_success_data(api.get_claim(claim_id, FIRM))["version"]


# ---------------------------------------------------- Tier 1/2: onboarding
def setup_active_contract(api, *, fee_pct=0.10, statutory_cap_pct=0.10,
                          prior_advance_cents=0, coverage_limit_cents=100_000_000,
                          license_state="TX", contract_loss_state="TX"):
    """Adjuster + ACTIVE license + client + policy + contract signed & ACTIVE.

    Returns ctx dict with adj, lic, cli, pol, con.
    """
    adj = new_adjuster(api)
    lic = new_license(api, adj, state_code=license_state)["id"]
    cli = new_client(api)
    pol = new_policy(api, cli, coverage_limit_cents=coverage_limit_cents)
    con = new_contract(
        api, cli, adj,
        loss_state_code=contract_loss_state,
        fee_pct=fee_pct,
        statutory_cap_pct=statutory_cap_pct,
        prior_advance_cents=prior_advance_cents,
    )
    sign_contract(api, con, cli)
    activate_contract(api, con)
    return {"adj": adj, "lic": lic, "cli": cli, "pol": pol, "con": con}


# --------------------------------------------------- Tier 3: claim lifecycle
def setup_filed_claim(api, *, ctx=None, peril_type="WIND",
                      pa_rcv_estimate_cents=10_000_000, depreciation_pct=0.20,
                      date_of_loss="2026-06-15T00:00:00Z", loss_state_code="TX",
                      **contract_kwargs):
    """Active contract + a FILED claim. Returns ctx with clm added."""
    ctx = ctx or setup_active_contract(api, **contract_kwargs)
    clm = new_draft_claim(
        api, ctx["pol"], ctx["con"], ctx["adj"],
        peril_type=peril_type,
        pa_rcv_estimate_cents=pa_rcv_estimate_cents,
        depreciation_pct=depreciation_pct,
        date_of_loss=date_of_loss,
        loss_state_code=loss_state_code,
    )
    file_claim(api, clm, ctx["adj"])
    ctx["clm"] = clm
    return ctx


def setup_offer_received_claim(api, *, offer_cents=8_000_000, ctx=None, **kwargs):
    """FILED claim + a recorded carrier offer -> OFFER_RECEIVED."""
    ctx = setup_filed_claim(api, ctx=ctx, **kwargs) if ctx is None else ctx
    if "clm" not in ctx:
        ctx = setup_filed_claim(api, ctx=ctx, **kwargs)
    get_success_data(api.record_offer(ctx["clm"], {"offer_cents": offer_cents}, CARRIER))
    return ctx


def setup_settled_claim(api, *, offer_cents=8_000_000, ctx=None, **kwargs):
    """A claim driven to SETTLED via file -> record-offer -> accept-settlement.

    accepted_by_user_id becomes the adjuster's id (used for segregation of duties).
    """
    ctx = setup_filed_claim(api, ctx=ctx, **kwargs)
    get_success_data(api.record_offer(ctx["clm"], {"offer_cents": offer_cents}, CARRIER))
    get_success_data(
        api.accept_settlement(ctx["clm"], make_public_adjuster_headers(ctx["adj"]))
    )
    return ctx


def setup_settled_claim_with_draft_supplement(api, *, offer_cents=8_000_000,
                                              amount_cents=1_000_000, ctx=None, **kwargs):
    """SETTLED claim + one DRAFT supplement. Returns ctx with clm, sup."""
    ctx = setup_settled_claim(api, offer_cents=offer_cents, ctx=ctx, **kwargs)
    ver = claim_version(api, ctx["clm"])
    sup = get_success_data(
        api.create_supplement(
            create_supplement_payload(ctx["clm"], ver, amount_cents=amount_cents),
            make_public_adjuster_headers(ctx["adj"]),
        )
    )["id"]
    ctx["sup"] = sup
    return ctx


def setup_paid_claim_with_disbursement(api, *, offer_cents=8_000_000,
                                       payment_amount_cents=None, prior_advance_cents=0,
                                       ctx=None, **kwargs):
    """A claim driven all the way to PAID with a PENDING disbursement.

    payment_amount_cents defaults to the settlement (offer) so the claim reaches PAID.
    Returns ctx with clm, pay, dis.
    """
    if payment_amount_cents is None:
        payment_amount_cents = offer_cents
    ctx = setup_settled_claim(
        api, offer_cents=offer_cents, ctx=ctx,
        prior_advance_cents=prior_advance_cents, **kwargs
    )
    pay = get_success_data(
        api.create_payment(create_payment_payload(ctx["clm"], payment_amount_cents), CARRIER)
    )["id"]
    get_success_data(api.clear_payment(pay, CARRIER))
    dis = _first_disbursement_id(api, ctx["clm"])
    ctx["pay"] = pay
    ctx["dis"] = dis
    return ctx


def _first_disbursement_id(api, claim_id):
    resp = api.list_disbursements(FIRM, params={"claim_id": claim_id})
    data = get_success_data(resp)
    return data[0]["id"]


# ------------------------------------------------- Tier 3: appraisal branch
def setup_claim_in_appraisal(api, *, offer_cents=6_000_000, ctx=None, peril_type="FIRE", **kwargs):
    """OFFER_RECEIVED claim with an INVOKED appraisal -> claim IN_APPRAISAL.

    Returns ctx with clm, app.
    """
    ctx = setup_offer_received_claim(api, offer_cents=offer_cents, ctx=ctx,
                                     peril_type=peril_type, **kwargs)
    app = get_success_data(
        api.create_appraisal(create_appraisal_payload(ctx["clm"]),
                             make_public_adjuster_headers(ctx["adj"]))
    )["id"]
    ctx["app"] = app
    return ctx


def setup_appraisers_named(api, *, pa_amount=8_000_000, carrier_amount=6_000_000,
                           pa_name="Pat", carrier_name="Casey", ctx=None, **kwargs):
    """Claim IN_APPRAISAL with appraisers named (APPRAISERS_NAMED). Returns ctx with clm, app."""
    ctx = setup_claim_in_appraisal(api, ctx=ctx, **kwargs)
    get_success_data(
        api.name_appraisers(
            ctx["app"],
            name_appraisers_payload(
                pa_appraiser_name=pa_name, pa_appraiser_amount_cents=pa_amount,
                carrier_appraiser_name=carrier_name, carrier_appraiser_amount_cents=carrier_amount,
            ),
            make_public_adjuster_headers(ctx["adj"]),
        )
    )
    return ctx
