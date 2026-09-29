"""Test-driving operations: the logical clock (E55) and the nightly sweep (E56)."""
from flask import Blueprint

import middleware as mw
import response as resp
from db import db
from services import sweep

bp = Blueprint('ops', __name__)


@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    mw.authenticate(('CsOpsAdmin',))
    data = mw.body()
    current_utc = mw.as_datetime(data, 'current_utc')
    raw = data['current_utc']
    db.set_clock(current_utc, raw)
    return resp.payload({'current_utc': raw}, 200)


@bp.route('/_ops/daily-sweep', methods=['POST'])
def daily_sweep():
    mw.authenticate(('CsOpsAdmin',))
    mw.body()
    return resp.payload(sweep.run_daily_sweep(), 200)
