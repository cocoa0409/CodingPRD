"""/_clock and /_sweep/* admin routes."""

from flask import Blueprint

from app import clock, store
from app.envelope import success_response
from app.routes._helpers import get_json_body, with_auth
from app.services import hap as hap_svc
from app.services import sweeps as svc
from app.util import iso_format


bp = Blueprint("clock_sweeps", __name__)


@bp.post("/__test__/reset")
def test_reset():
    """Test-only support: reset in-memory store and logical clock.

    Conftest probes this endpoint between tests so that each test starts
    with a fresh clock at wall-clock now. Not part of the PRD contract;
    available unconditionally so the runner can drive isolation.
    """
    with store.lock():
        store.reset()
        clock.reset()
        now = clock.now()
    return success_response({"now": iso_format(now)})


@bp.post("/_clock/advance")
@with_auth("PHAAdmin")
def advance_clock(caller=None):
    body = get_json_body()
    with store.lock():
        result = svc.advance_clock(body)
    return success_response({"now": iso_format(result["now"])})


@bp.post("/_sweep/expirations")
@with_auth("PHAAdmin")
def sweep_expirations(caller=None):
    with store.lock():
        expired = svc.sweep_expirations()
    return success_response({"expired_voucher_ids": expired})


@bp.post("/_sweep/abatements")
@with_auth("PHAAdmin")
def sweep_abatements(caller=None):
    with store.lock():
        terminated = svc.sweep_abatements()
    return success_response({"terminated_tenancy_ids": terminated})


@bp.post("/_sweep/reviews")
@with_auth("PHAAdmin")
def sweep_reviews(caller=None):
    with store.lock():
        denied = svc.sweep_reviews()
    return success_response({"denied_review_ids": denied})


@bp.post("/_sweep/monthly-hap")
@with_auth("PHAAdmin")
def sweep_monthly_hap(caller=None):
    body = get_json_body()
    with store.lock():
        created = hap_svc.run_monthly_sweep(body)
    return success_response({"created_payment_ids": created})
