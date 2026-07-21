"""Invalid state-transition rejections on terminal / wrong-state resources (breadth corner coverage)."""
from test_helpers import (
    validate_error, ApiErrorId, make_analyst_headers, make_client_headers, TEST_USERS,
)
from test_helpers import fixtures as fx

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]


def test_cancel_held_hearing_returns_invalid_state(api):
    """PRD §3.5: "Cancelling it moves it from `SCHEDULED` to `CANCELLED` ... Either action is
    permitted only while the hearing is still `SCHEDULED`."

    Design: Corner/state_machines/corner_cancel_hearing_from_held_returns_invalid_state
    """
    ctx = fx.setup_filed_appeal(api, two_analysts=True)
    hearing = fx.schedule_hearing(api, ctx["analyst_id"], ctx["appeal_id"], ctx["analyst2_id"],
                                  "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z")
    fx.hold_hearing(api, ctx["analyst2_id"], hearing["id"])
    resp = api.cancel_hearing(hearing["id"], make_analyst_headers(ctx["analyst_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_double_accept_fee_agreement_returns_invalid_state(api):
    """PRD §3.1: "An agreement becomes billable only when the bound client accepts it, moving it from
    `PENDING` to `ACTIVE`: acceptance is allowed only while the agreement is still `PENDING`".

    Design: Corner/state_machines/corner_fee_agreement_double_accept_returns_invalid_state
    """
    client = fx.new_client(api)
    fa = fx.new_fee_agreement(api, client["id"], accept=True)  # now ACTIVE
    resp = api.accept_fee_agreement(fa["id"], make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_decide_draft_exemption_returns_invalid_state(api):
    """PRD §3.2: "A decide request on a claim that is not `SUBMITTED` is rejected as an invalid state
    transition."

    Design: Corner/state_machines/corner_exemption_decide_from_draft_returns_invalid_state
    """
    analyst = fx.new_analyst(api)
    client = fx.new_client(api)
    jur = fx.new_jurisdiction(api)
    parcel = fx.new_parcel(api, analyst["id"], client["id"], jur["id"])
    from test_helpers import get_success_data, create_exemption_claim_payload
    ex = get_success_data(api.create_exemption_claim(
        create_exemption_claim_payload(parcel["id"], exemption_type="SENIOR", exemption_value_cents=1000000),
        make_analyst_headers(analyst["id"])))  # DRAFT, never submitted
    resp = api.decide_exemption_claim(ex["id"], {"decision": "APPROVE"}, FIRM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
