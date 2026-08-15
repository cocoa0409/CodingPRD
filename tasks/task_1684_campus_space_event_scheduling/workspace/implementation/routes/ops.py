"""POST /campus/ops/daily-close - the Scheduler-invoked operations checkpoint
(PRD 2.4)."""

from middleware import endpoint
from routes.common import one
from services.daily_close import run_daily_close


@endpoint("POST", "/campus/ops/daily-close", roles=["Scheduler"], code=200)
def daily_close(ctx):
    return one(run_daily_close())
